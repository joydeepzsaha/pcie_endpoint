"""
Detect.Active's "no Receiver detected" exit goes to ST_IDLE, not Detect.Quiet.

Base 2.1 Rev 2.1, Section 4.2.6.1.2 (p.219):

    "Next state is Detect.Quiet if a Receiver is not detected on any Lanes."

pcie_ltssm_downstream.sv:591-592 instead does

          end else begin
            next_state = ST_IDLE; // Should technically be ST_DETECT_QIUET

-- the author's own comment concedes the target is wrong.

WHY IT IS NOT COSMETIC
ST_IDLE is not Detect.Quiet. Its only exit is `if (en_i)` at :525, so the
retry the spec mandates is conditional on an input that Detect.Quiet does not
consult. With en_i held high the detour costs one cycle; with en_i low the
LTSSM stops here permanently on a path the spec says must loop back and try
again. ST_IDLE also clears gen_os_ctrl_c (:527) and idle_to_rlock_transitioned
(:526), which is why nineteen separate arcs funnel through it -- it is the
RTL's de facto reset hub, and reaching it is materially different from
re-entering Detect.Quiet.

WHAT THIS TEST MEASURES
Drive to Detect.Active, complete a receiver-detection sequence with
receiver_detected_i = 0 (no Receiver on any Lane), and sample ltssm_state_o on
EVERY cycle so the transient is not missed.

  Spec-conformant DUT: DETECT_ACTIVE -> DETECT_QUIET
  This DUT:            DETECT_ACTIVE -> ST_IDLE -> DETECT_QUIET

The assertion states the spec sequence, so this is an expect_fail row recording
the divergence (oracle D7, evidence/rung10/ORACLES_LTSSM.md). No src/ edit.

NOT COVERED HERE, and why (recorded rather than silently dropped):
  * D10 -- the same detour on Detect.Rx's "different Lanes detected" exit
    (:614-615), which additionally asserts error_c where the spec calls the
    path an ordinary retry. ST_DETECT_RX is only entered when SOME BUT NOT ALL
    Lanes detect a Receiver (:582 uses &receiver_detected_i, :581 uses |), and
    at MAX_NUM_LANES=1 those two reductions are identical -- so the state is
    unreachable at x1 and D10 needs an x4 target.
  * D10's error_c half is unobservable at ANY width: error_o is never driven
    (evidence/rung10/CENSUS_LTSSM.md section 3), so no port-level test can see
    it. Untestable-with-reason.

Requires SIM_FAST_LINK=1, MAX_NUM_LANES=1 (verilate_detect_d7 target).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from ltssm_tb_common import *  # noqa

# Cycles to watch after the detection result is presented. The whole transition
# completes in a handful; this is slack, not a timeout budget.
WATCH_CYCLES = 12


def state(dut):
    return int(dut.ltssm_state_o.value)


def sname(s):
    return STATE_NAMES.get(s, hex(s))


@cocotb.test(expect_fail=True)
async def run_test_detect_d7(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    n_bits = len(dut.ordered_set_i)
    assert n_bits == 128, (
        f"-GMAX_NUM_LANES=1 did not reach the DUT: ordered_set_i is {n_bits} "
        f"bits (x1 expects 128)")

    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    assert state(dut) == ST_IDLE

    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")

    # Break electrical idle so Detect.Quiet advances to Detect.Active.
    dut.phy_rxelecidle_i.value = LANE0_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")

    # ---- present a completed detection that found NOTHING ----
    # phy_phystatus_i signals "detection finished"; receiver_detected_i = 0 is
    # the "no Receiver on any Lane" result the spec routes to Detect.Quiet.
    dut.receiver_detected_i.value = 0
    dut.phy_rxstatus_i.value = 0
    dut.phy_phystatus_i.value = LANE0_MASK

    seq = [state(dut)]
    for _ in range(WATCH_CYCLES):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")          # post-edge read, not pre-edge
        s = state(dut)
        if s != seq[-1]:
            seq.append(s)

    dut._log.info("state sequence after an empty detection: "
                  + " -> ".join(sname(s) for s in seq))

    assert ST_DETECT_QUIET in seq, (
        f"never returned to Detect.Quiet at all; sequence was "
        f"{' -> '.join(sname(s) for s in seq)}")

    assert ST_IDLE not in seq[1:], (
        f"D7 (Base 2.1 4.2.6.1.2, p.219): 'Next state is Detect.Quiet if a "
        f"Receiver is not detected on any Lanes.' The DUT went "
        f"{' -> '.join(sname(s) for s in seq)} instead, detouring through "
        f"ST_IDLE (pcie_ltssm_downstream.sv:592, whose own comment reads "
        f"'Should technically be ST_DETECT_QIUET'). ST_IDLE is not "
        f"Detect.Quiet: its only exit is `if (en_i)` at :525, so with en_i "
        f"deasserted the LTSSM would stop here permanently on a path the spec "
        f"requires to retry.")
