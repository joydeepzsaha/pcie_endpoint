"""
Polling.Active: WHEN the "1024 TS1 transmitted" limb is required to be met.

Base 2.1 Rev 2.1, Section 4.2.6.2.1 (p.220 and p.221) states the exit condition
in two places, and the two are NOT the same:

  p.220, line 13 -- the PRIMARY exit:
    "Next state is Polling.Configuration after at least 1024 TS1 Ordered Sets
     were transmitted, and all Lanes that detected a Receiver during Detect
     receive eight consecutive training sequences (or their complement)
     satisfying any of the following conditions: ..."

  p.221, line 10 -- inside the "Otherwise, after a 24 ms timeout" branch:
    "... and a minimum of 1024 TS1 Ordered Sets are transmitted AFTER
     RECEIVING ONE TS1 Ordered Set."

The qualifier "after receiving one TS1 Ordered Set" belongs to the 24 ms
timeout branch only. On the primary exit the 1024 transmitted Ordered Sets are
counted from entry to Polling.Active, with no dependence on what has been
received.

pcie_ltssm_downstream.sv:649-653 applies the timeout-branch rule to BOTH:

    if (ordered_set_tranmitted_i) begin
      // Only start counting after receiving one TS1
      if (|single_ts1_received ) begin
      ordered_set_sent_cnt_c = ordered_set_sent_cnt_r + 1;
      end

so ordered_set_sent_cnt_r stays 0 for every Ordered Set transmitted before the
first TS1 arrives, and the primary exit at :659 then demands a further
MinTS1sPolling transmissions that the spec does not ask for.

WHAT THIS TEST MEASURES
  Phase A: sit in Polling.Active with ts1_valid_i deasserted and deliver
           TX_PRELOAD ordered-set-transmitted pulses. Under the spec this
           satisfies the "at least 1024 (=MinTS1sPolling) transmitted" limb.
  Phase B: assert a PAD/PAD TS1 and count how many further transmit pulses
           elapse before the FSM leaves Polling.Active.

  Spec-conformant DUT: phase B costs ~0 pulses -- the transmit limb is already
  met, so the exit fires as soon as the eight consecutive TS1 land.
  This DUT: phase B costs a full MinTS1sPolling pulses.

The assertion below states the SPEC value, so this test is an expect_fail row
recording the divergence (oracle P4, evidence/rung10/ORACLES_LTSSM.md).
It is not a repair: no src/ file is touched by this rung.

Requires SIM_FAST_LINK=1 (MinTS1sPolling = 24), MAX_NUM_LANES=1
(verilate_polling_p4 target).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from ltssm_tb_common import *  # noqa

# pcie_ltssm_downstream.sv:121 -- SIM_FAST_LINK ? 24 : 1024.
MIN_TS1S_POLLING_FAST = 24

# Ordered sets transmitted in phase A, before any TS1 is received. Comfortably
# above MinTS1sPolling so the spec's transmit limb is unambiguously satisfied.
TX_PRELOAD = 40

# The spec-conformant budget for phase B. Eight consecutive TS1 are consumed by
# the per-lane counter at one per clock, which is far quicker than the ~4-cycle
# transmit-pulse period, so a conformant DUT needs at most a pulse or two of
# slack to notice and act.
SPEC_PHASE_B_BUDGET = 2

# Hard ceiling so a hang fails loudly rather than running to the cocotb timeout.
PHASE_B_CEILING = 200


async def tx_pulse(dut):
    """One ordered_set_tranmitted_i pulse, matching os_tx_pulser's shape
    (3 low cycles, 1 high cycle). Driven manually here because this test needs
    to COUNT transmissions, not just supply them."""
    dut.ordered_set_tranmitted_i.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.ordered_set_tranmitted_i.value = 1
    await ClockCycles(dut.clk_i, 1)


def state(dut):
    return int(dut.ltssm_state_o.value)


@cocotb.test(expect_fail=True)
async def run_test_polling_p4(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    n_bits = len(dut.ordered_set_i)
    assert n_bits == 128, (
        f"-GMAX_NUM_LANES=1 did not reach the DUT: ordered_set_i is {n_bits} "
        f"bits (x1 expects 128)")

    # ---- reset -> Detect -> Polling.Active (role-neutral handshake) ----
    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    assert state(dut) == ST_IDLE

    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")

    dut.phy_rxelecidle_i.value = LANE0_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")

    dut.receiver_detected_i.value = LANE0_MASK
    dut.phy_rxstatus_i.value = RXSTATUS_OK_X1
    dut.phy_phystatus_i.value = LANE0_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_phystatus_i.value = 0
    await wait_state(dut, ST_POLLING_ACTIVE, 200, "POLLING_ACTIVE")

    # ---- phase A: transmit with nothing received ----
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = 0
    dut.ordered_set_i.value = 0

    for i in range(TX_PRELOAD):
        await tx_pulse(dut)
        assert state(dut) == ST_POLLING_ACTIVE, (
            f"left Polling.Active during phase A at pulse {i} -- nothing has "
            f"been received yet, so no exit condition can be satisfied")

    dut._log.info(
        f"phase A complete: {TX_PRELOAD} ordered sets transmitted with "
        f"ts1_valid_i deasserted (MinTS1sPolling={MIN_TS1S_POLLING_FAST})")

    # ---- phase B: start receiving TS1 PAD/PAD, count pulses to the exit ----
    dut.ordered_set_i.value = pack_tsos(link_num=None, lane_num=None)
    dut.ts1_valid_i.value = LANE0_MASK

    pulses = 0
    while state(dut) == ST_POLLING_ACTIVE and pulses < PHASE_B_CEILING:
        await tx_pulse(dut)
        pulses += 1

    # Settle past the edge so ltssm_state_o reads post-edge, not pre-edge.
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    reached = state(dut)

    dut._log.info(
        f"phase B: left Polling.Active after {pulses} further transmit pulses, "
        f"into {STATE_NAMES.get(reached, hex(reached))} ({reached:#07x})")

    assert reached == ST_POLLING_CONFIG, (
        f"expected Polling.Configuration, got "
        f"{STATE_NAMES.get(reached, hex(reached))} ({reached:#07x})")

    # The measurement that decides P4. A DUT that counts transmissions from
    # entry to Polling.Active (as p.220 requires) has already met the limb and
    # exits almost immediately; this DUT restarts the count at the first TS1.
    assert pulses <= SPEC_PHASE_B_BUDGET, (
        f"P4 (Base 2.1 4.2.6.2.1, p.220 vs p.221): the primary Polling.Active "
        f"exit requires 1024 TS1 transmitted since ENTRY to Polling.Active; "
        f"the 'after receiving one TS1' qualifier belongs only to the 24 ms "
        f"timeout branch on p.221. {TX_PRELOAD} ordered sets were transmitted "
        f"before any TS1 was received, so the transmit limb was already "
        f"satisfied and the exit should have followed the eight consecutive "
        f"TS1 within {SPEC_PHASE_B_BUDGET} transmit pulses. It took {pulses} "
        f"-- consistent with pcie_ltssm_downstream.sv:651 gating "
        f"ordered_set_sent_cnt_c on |single_ts1_received and so re-counting a "
        f"full MinTS1sPolling ({MIN_TS1S_POLLING_FAST}) after the first TS1.")
