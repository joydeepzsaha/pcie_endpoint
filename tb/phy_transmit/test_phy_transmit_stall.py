"""
The PIPE-stalling bench, half B — tracker §54 #4's other half, at the boundary
where it actually ships.

WHAT IS BEING MEASURED
----------------------
    lane_management.sv:571   assign data_valid_o = '1;

That constant feeds every scrambler in the design:

    lane_management.sv:571 -> lm_data_valid[lane]
      -> phy_transmit.sv:161  .data_valid_i (lm_data_valid[lane])
        -> scrambler.sv:60      .data_valid_i
          -> gen1_scramble.sv:102  if (data_valid_i)   <-- always taken
    and scrambler.sv:76  data_valid_o <= data_valid_i  -> pipe_data_valid_o

So `pipe_data_valid_o` is a registered copy of a constant: **1 after reset,
forever, carrying no information**.  Rung 9 recorded this as F-4 and measured
that mutant M11 (`data_valid_o = '1` -> `data_valid_r`) SURVIVED all 8 targets:
nothing in 76 gate rows distinguished a real valid from a tied-off one.  This
file is the row that does.

WHY IT MATTERS -- THE CANCELLATION, OBSERVED
--------------------------------------------
Half A of §54 #4 is gen1_scramble.sv:97, which advances the scrambler LFSR on
every CLOCK rather than every SYMBOL (see tb/scrambler/test_scrambler_stall.py).
Half A is a live desynchronisation bug -- but it is unobservable on the
integrated path precisely BECAUSE of half B: if data_valid is never deasserted,
the LFSR advance and the data pipeline advance together every cycle and the
defect cancels.

That is why the two must be fixed as a pair, and it is why this bench and the
scrambler one are separate DUTs.  At the phy_transmit boundary data_valid into
every scrambler is a COMPILE-TIME CONSTANT: no stimulus available here can
deassert it -- only an RTL edit could, and fix-arc 2 makes none (D-FA2.1).  A
bench cannot inject the stall at this level.  Demonstrating that is the point
of this file, not a limitation of it.

⚠️ Landing half B alone is a REGRESSION, not a partial fix: it lets real gaps
reach a scrambler whose LFSR runs straight through them.  The half-fix mutants
in evidence/fix-arc-2/MUTANTS_FA2.md measure that asymmetry so fix-arc 3 can
size the work correctly.

THE ORACLE
----------
    Base 2.1 §4.2.3, pp.198-199 -- "The LFSR value is advanced eight serial
    shifts for each Symbol except the SKP."

plus the PIPE contract the design itself uses everywhere else: data_valid marks
a clock on which a Symbol is actually being handed to the PHY.  A transmitter
with nothing to send is not transmitting a Symbol, so data_valid must fall.
The sibling implementation agrees -- gen3_scramble.sv:147 gates on data_valid_i
-- and `scrambler` is instantiated as both scrambler_inst (phy_transmit.sv:153)
and descrambler_inst (phy_receive.sv:143), so TX and RX must advance in
lockstep by construction.

Full recon in pcie_docs/evidence/fix-arc-2/PLAN.md.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

GEN1 = 0x01         # rate_speed_e.gen1
IDLE_CYCLES = 200   # a long, entirely quiet window: no OS requested, no DLLP


async def start_clocks(dut):
    """Same three clocks test_phy_transmit_tx.py uses: clk_i (DLLP framing),
    pipe_rx_usr_clk_i (os_generator + OS-FIFO write), pipe_tx_usr_clk_i
    (scrambler / lane_management / PIPE output)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_tx_usr_clk_i, 10, units="ns").start())


async def reset_quiet(dut):
    """Reset with every source of traffic held OFF and kept off: no ordered set
    requested, no DLLP on the AXIS input, link down.  Whatever pipe_data_valid_o
    does in this state, it does with nothing to transmit."""
    dut.rst_i.value = 1
    dut.en_i.value = 0
    dut.link_up_i.value = 0
    dut.num_active_lanes_i.value = 1
    dut.send_ordered_set_i.value = 0
    dut.ordered_set_i.value = 0
    dut.gen_os_ctrl_i.value = 0          # valid=0: os_generator is not asked for anything
    dut.curr_data_rate_i.value = GEN1
    dut.s_dllp_axis_tdata.value = 0
    dut.s_dllp_axis_tkeep.value = 0
    dut.s_dllp_axis_tvalid.value = 0     # no DLLP traffic at all
    dut.s_dllp_axis_tlast.value = 0
    dut.s_dllp_axis_tuser.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 8)
    dut.rst_i.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 4)
    dut.en_i.value = 1


async def sample_valid(dut, cycles):
    """Collect pipe_data_valid_o (lane 0) once per pipe_tx_usr_clk_i edge."""
    seen = []
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        await Timer(1, units="ps")
        seen.append(int(dut.pipe_data_valid_o.value) & 0x1)
    return seen


# ==========================================================================
#  Control arm -- ordinary PASS.  Records the CURRENT behaviour at the port,
#  which is the only way to witness the cancellation on unfixed RTL (the same
#  pattern fix-arc 1 used for error_o before it was driven).
# ==========================================================================

@cocotb.test()
async def test_stall_control_pipe_valid_is_constant_one_when_idle(dut):
    """C4: the cancellation, OBSERVED rather than inferred.

    Hold the DUT completely quiet -- no ordered set requested, no DLLP, link
    down -- for IDLE_CYCLES and assert pipe_data_valid_o is 1 on every single
    cycle.  There is nothing to transmit for the whole window, so a
    Symbol-accurate valid would be 0 throughout; measuring a constant 1 is the
    direct observation that lane_management.sv:571's hardwire reaches the port.

    This is an ordinary PASS row deliberately: it asserts what the RTL does
    today, so it stays green until fix-arc 3 changes it, and it is the row that
    proves the drive sequence reached the sampling point for the expect_fail
    row below."""
    await start_clocks(dut)
    await reset_quiet(dut)
    seen = await sample_valid(dut, IDLE_CYCLES)

    assert len(seen) == IDLE_CYCLES
    assert all(v == 1 for v in seen), (
        f"pipe_data_valid_o was not constant 1 across {IDLE_CYCLES} idle "
        f"cycles: {seen.count(0)} cycles read 0. If this fails, "
        f"lane_management.sv:571 is no longer hardwired and the cancellation "
        f"described in this file's header no longer holds -- re-read §54 #4."
    )
    dut._log.info(
        f"C4 OK: pipe_data_valid_o == 1 on all {IDLE_CYCLES} cycles with NOTHING "
        f"to transmit (no OS requested, no DLLP, link down). lane_management.sv:571 "
        f"reaches the port through scrambler.sv:76. This constant is what hides "
        f"gen1_scramble.sv:97 -- the two halves of §54 #4 cancel."
    )


# ==========================================================================
#  The divergence.  One assertion (§22.66).
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_stall_pipe_valid_must_track_symbol_transmission(dut):
    """pipe_data_valid_o must mark the clocks on which a Symbol is actually
    being handed to the PHY.

    With no ordered set requested, no DLLP offered and the link down, no Symbol
    is being transmitted, so a conforming transmitter deasserts valid for at
    least part of the window.

    DIVERGES: lane_management.sv:571 hardwires `data_valid_o = '1`, so the
    signal is a registered constant and carries no information.  Rung 9's M11
    survived all 8 targets for exactly this reason -- nothing distinguished a
    real valid from a tied-off one.

    ⚠️ This row also documents why no stall can be injected at THIS boundary:
    the same constant that makes the assertion fail is the one that makes
    data_valid unreachable from any port, which is why half A needs its own DUT
    (tb/scrambler/test_scrambler_stall.py)."""
    await start_clocks(dut)
    await reset_quiet(dut)
    seen = await sample_valid(dut, IDLE_CYCLES)

    zeros = seen.count(0)
    dut._log.info(
        f"MEASURED: pipe_data_valid_o read 0 on {zeros} of {IDLE_CYCLES} idle "
        f"cycles (a Symbol-accurate valid would read 0 on all of them)"
    )
    assert zeros > 0, (
        f"pipe_data_valid_o stayed 1 for all {IDLE_CYCLES} cycles while the "
        f"transmitter had nothing to send. Base 2.1 4.2.3 p.198 advances the "
        f"scrambler LFSR once per SYMBOL; a valid that cannot fall makes "
        f"'per Symbol' and 'per clock' indistinguishable, which is exactly what "
        f"hides gen1_scramble.sv:97's ungated advance. Site: "
        f"lane_management.sv:571 `assign data_valid_o = '1;`."
    )
