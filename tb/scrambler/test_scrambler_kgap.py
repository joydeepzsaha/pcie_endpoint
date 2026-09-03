"""O-KGAP — K codes across a data_valid gap.  Tracker §54 4c, fix-arc 4 Phase 1.

Toplevel: `scrambler`, the wrapper phy_transmit.sv:153 and phy_receive.sv:143
both instantiate.  data_valid_i is a real input port here, and since fix-arc 3
closed §54 #4 it is also a real signal at the integrated boundary
(lane_management.sv:582 now drives data_valid_r where it hardwired '1) — so the
gaps this bench injects are reachable in the shipping configuration rather than
hypothetical.

THE QUESTION
------------
§54 4c was registered by FA-3 as a QUESTION, not a finding: gen1_scramble.sv
clears scramble_reset / stop_scrambling / skp_os on EVERY clock, while the COM
that raises them and the LFSR reset that consumes them both sit inside
`if (data_valid_i)`.  Raised inside the guard, cleared outside it, consumed
inside it — so a pulse whose lifetime is one clock may expire during a gap
without ever being acted on.  No bench in the repository drove K codes across a
gap, so it stayed unmeasured.  This is that bench.

Oracle, controls, the derivation from Base 2.1 §4.2.3 pp.198-199 and the
predictions are in pcie_docs/evidence/fix-arc-4/ORACLE_4C.md and
PREDICTIONS_1.md, both committed before this ran.

⚠️ THE REGISTER'S LINE NUMBERS ARE STALE.  §54 4c cites :95,:96,:98.  At HEAD
skp_os is :97 and :98 is `D.data_valid[0] = data_valid_i`, which MUST stay
outside the guard: inside it, stage 0's valid would hold high through idle,
which is gen1_valid's duplicate-and-drop shape (§54 4b, standing "do not wire it
up").  The site set is :95,:96,:97.  See ORACLE_4C.md §1.

ROW SET
-------
  C1  control, ordinary PASS   determinism
  C2  control, ordinary PASS   gaps are transparent with NO K code present
  C3  control, ordinary PASS   the COM is observable at the boundary at all
  L   localiser, ordinary PASS every offset OUTSIDE the one-clock window is
                               transparent — true BEFORE and AFTER the fix, so
                               it creates no rewrite debt (FA-2's debt (a),
                               avoided by construction)
  K1  expect_fail              O-KGAP over the full swept window, COM arm
  K2  expect_fail              O-KGAP over the full swept window, SKP arm

K1 and K2 carry ONE divergent assertion each and are never mixed with a
conforming one (§22.66).
"""
import cocotb
from cocotb.clock import Clock

from kgap_common import (GAP_LENS, OFFSETS, VULNERABLE, build, first_diff, fmt,
                         run, sweep)


async def start(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())


# ------------------------------------------------------------------ C1

@cocotb.test()
async def control_two_gap_free_runs_are_identical(dut):
    """C1 — determinism.

    Two gap-free runs of the same stimulus must publish the same Symbols.  This
    is what makes any difference in a gap run attributable to the gap and not to
    run-to-run variation.

    Independent observation point (§22.80): the second gap-free run.  The gap
    variable is absent from both runs, so this control shares no dependency with
    the thing under test.
    """
    await start(dut)
    words, _ = build("com")
    a = await run(dut, words)
    b = await run(dut, words)
    dut._log.info("C1: len(a)=%d len(b)=%d first_diff=%s" % (len(a), len(b), first_diff(a, b)))
    assert len(a) > 0, "no beats published at all"
    assert a == b, "two gap-free runs differ at E[%s]" % first_diff(a, b)


# ------------------------------------------------------------------ C2

@cocotb.test()
async def control_gaps_are_transparent_without_k_codes(dut):
    """C2 — a gap in a K-free stream changes nothing.

    Establishes that stalling per se is already handled, so a difference seen
    near a COM is attributable to the K path and not to gaps in general.  It is
    also a regression check on fix-arc 3's own half A: with §54 #4 open every gap
    corrupted every later Symbol, and this row would have been impossible.

    Independent observation point (§22.80): a stimulus in which the K path is
    ABSENT, not merely unexercised.  A control that still contained a COM would
    share a dependency with the path under measurement — the mistake FA-3's C2
    made and was caught by (§60.8).
    """
    await start(dut)
    _, _, results = await sweep(dut, "nok", "C2/no-K")
    bad = {k: v for k, v in results.items() if v is not None}
    assert not bad, (
        "a gap changed the stream with NO K code present, at (delta,gap)=%s. "
        "That is broader than §54 4c: it would mean §54 #4 half A does not hold."
        % sorted(bad))


# ------------------------------------------------------------------ C3

@cocotb.test()
async def control_the_com_is_observable_gap_free(dut):
    """C3 — the COM changes the published stream on a gap-free schedule.

    Without this, "no divergence at any offset" could not be distinguished from
    "the COM never did anything observable and this bench measured nothing" —
    the vacuous green §22.67 exists for.  C3 is what gives a null result its
    meaning, so it is an ordinary PASS row and not an expect_fail.

    Independent observation point (§22.80): a gap-free schedule.  The variable
    that differs between the two runs is the SYMBOL, not the schedule.
    """
    await start(dut)
    com_words, _ = build("com")
    nok_words, _ = build("nok")
    a = await run(dut, com_words)
    b = await run(dut, nok_words)
    fd = first_diff(a, b)
    dut._log.info("C3: COM vs no-COM first_diff=%s" % fd)
    dut._log.info("C3:  com[%s..] %s" % (fd, fmt(a, fd or 0)))
    dut._log.info("C3:  nok[%s..] %s" % (fd, fmt(b, fd or 0)))
    assert fd is not None, (
        "a COM in the stream changed NOTHING at the boundary -- the LFSR reset "
        "is not observable here, so this bench has no power and 4c cannot be "
        "scored either way")


# ------------------------------------------------------------------ L

@cocotb.test()
async def gaps_outside_the_consumption_window_are_transparent(dut):
    """L — the localiser.

    ORACLE_4C.md §5 derives a ONE-CLOCK window: the pulse is raised at j+2, when
    detection reads pipeline stage 1, and consumed at j+3, when `:119` latches
    the reset.  A gap at j+1 or j+2 merely DELAYS detection — the pipeline is
    valid-gated, so the COM waits at its stage and detection fires on the first
    valid clock after the gap.  A gap at j+4 or later comes after consumption.

    So every offset except j+3 must be transparent, and this row asserts exactly
    that.  It is TRUE on unfixed RTL and stays true after the fix, so unlike a
    row asserting "exactly one offset diverges" it creates no rewrite debt.

    Together with K1 this localises the defect precisely: K1 says the window is
    not transparent, L says everything either side of it is.
    """
    await start(dut)
    _, _, results = await sweep(dut, "com", "L/outside-window")
    bad = {k: v for k, v in results.items()
           if k[0] != VULNERABLE and v is not None}
    assert not bad, (
        "a gap OUTSIDE the one-clock consumption window changed the stream, at "
        "(delta,gap)=%s -- the defect is not where ORACLE_4C.md §5 derives it"
        % sorted(bad))


# ------------------------------------------------------------------ K1

@cocotb.test(expect_fail=True)
async def com_lfsr_reset_survives_a_data_valid_gap(dut):
    """K1 — O-KGAP, COM arm.  THE MEASUREMENT.

    Base 2.1 §4.2.3 p.199: "The COM Symbol initializes the LFSR", and
    "Immediately after a COM exits the Transmit LFSR, the LFSR on the Transmit
    side is initialized.  EVERY TIME a COM enters the Receive LFSR on any Lane
    of that Link, the LFSR on the Receive side is initialized."  The trigger is
    the COM's position in the SYMBOL STREAM.  A clock carrying no Symbol is not
    part of that stream, so no pattern of valid-low clocks may change the
    published Symbols.

    PREDICTED DIVERGENCE (PREDICTIONS_1.md P1): gen1_scramble.sv raises
    scramble_reset at :248 INSIDE `if (data_valid_i)`, clears it at :95 OUTSIDE,
    and consumes it at :119 INSIDE.  A one-clock pulse that needs a valid clock
    to be used is lost whenever the clock after it is idle.

    ONE divergent assertion (§22.66): the published Symbol sequence must not
    depend on the clock schedule.
    """
    await start(dut)
    ref, j, results = await sweep(dut, "com", "K1/COM")
    bad = sorted(k for k, v in results.items() if v is not None)
    for (delta, glen) in bad:
        fd = results[(delta, glen)]
        dut._log.info("K1: DIVERGENCE delta=j+%d gap=%d first at E[%d] (j=%d, "
                      "so the gap opened at presentation %d)"
                      % (delta, glen, fd, j, j + delta))
    assert not bad, (
        "a data_valid gap changed the scrambled Symbol stream after a COM, at "
        "(delta,gap)=%s.  Base 2.1 §4.2.3 p.199 initializes the LFSR on EVERY "
        "COM and locates that event in the Symbol stream, not on a clock; a gap "
        "carries no Symbol and must not be able to cancel it." % bad)


# ------------------------------------------------------------------ K2

@cocotb.test(expect_fail=True)
async def skp_state_survives_a_data_valid_gap(dut):
    """K2 — O-KGAP, SKP arm.

    §4.2.3 p.199's other Symbol-located rule: "The LFSR value is advanced eight
    serial shifts for each Symbol EXCEPT THE SKP."  A SKP Ordered Set sets
    skp_os (:257 / :265, inside the guard), which is cleared at :97 outside it
    and consumed at :73 / :165 / :283.  Identical shape to K1's scramble_reset.

    This row asserts SCHEDULE INDEPENDENCE only — the same O-KGAP claim — and
    deliberately makes no claim about whether the module's SKP semantics are
    otherwise correct.  Those belong to §54 #9 (SKP interval and starvation) and
    are out of this rung's scope fence (D-FA4.3).

    ONE divergent assertion (§22.66).
    """
    await start(dut)
    ref, j, results = await sweep(dut, "skp", "K2/SKP")
    bad = sorted(k for k, v in results.items() if v is not None)
    for (delta, glen) in bad:
        dut._log.info("K2: DIVERGENCE delta=j+%d gap=%d first at E[%d]"
                      % (delta, glen, results[(delta, glen)]))
    assert not bad, (
        "a data_valid gap changed the Symbol stream around a SKP Ordered Set, "
        "at (delta,gap)=%s.  §4.2.3 p.199 exempts the SKP from the advance by "
        "its position in the Symbol stream, which a valid-low clock cannot "
        "occupy." % bad)
