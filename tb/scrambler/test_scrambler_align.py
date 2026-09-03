"""O-ALIGN on candidate B — the valid every consumer actually sees.

Toplevel: scrambler.  The published data_valid_o comes from scrambler.sv:76,
a 1-stage register copy of data_valid_i.

WHAT THIS ROW SETTLES
---------------------
FA-2 closed with P2.g NOT MEASURED and named this bench as FA-3's first task
(FINDINGS_STALL.md §5a; tracker §59.7 (3)).  F-5 (Rung 9) and P2.g both read the
1-stage publication as a THREE-CYCLE SKEW against a 4-stage data path, which
would have made the §54 #4 fix three edits instead of two.

That premise is predicted FALSE in PREDICTIONS_1.md §4 (P-3), before this file
existed, and the reason is structural: the data pipeline is VALID-GATED — the
whole body from gen1_scramble.sv:102 down, including the XOR at :272, sits
inside `if (data_valid_i)` — so data_out_o changes only on clocks that carried a
Symbol.  Its latency is 4 SYMBOLS, not 4 clocks.  The strobe that marks "this
clock carries a Symbol" is fixed by the input schedule and the pipeline's
advance condition, and is NOT depth-dependent.  A depth-matched valid is the
wrong shape of answer.

Oracle: pcie_docs/evidence/fix-arc-3/ORACLE.md (O-ALIGN, from Base 2.1 §4.2.3
p.199 plus the design's own contract read from ordered_set_handler's seven
per-clock gate sites and block_alignment's capture enable).
Predictions: PREDICTIONS_1.md, committed before this file existed.

Two gap lengths are driven throughout, because "this defect does not depend on
gap length" is a measurement only if two lengths were measured.
"""
import cocotb
from cocotb.clock import Clock

from align_common import (DEPTH, STALL_AT, advance_values, fabricated,
                          gap_beats, idle_beats, published, run,
                          silent_advances, stimulus, summarize)

GAPS = (5, 9)


# ==========================================================================
#  Controls.  §22.2/§22.3 -- the sets the rows below quantify over must be
#  non-empty, and the gap must be shown to have actually opened.
# ==========================================================================

@cocotb.test()
async def test_align_control_reference_is_rich_and_repeatable(dut):
    """C1+C2+C3: the no-gap reference is non-empty, all-distinct and repeatable.

    C2 (all words distinct) is the load-bearing one: it is what licenses reading
    a republished word as a DUPLICATE rather than a coincidence.  Without it,
    idle_beats() would be an observation, not evidence.

    ⚠️ Distinctness is asserted over advance_values() -- the words the pipeline
    advanced to on the bench's own presentation clocks -- NOT over the beats the
    DUT published.  Same control, same form, on both candidates: it must be
    independent of the signal under test, or the candidate that republishes
    stale words fails its own control and cannot be measured at all.  That is
    not hypothetical: it is exactly what candidate A did on the first run."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = stimulus()
    a = await run(dut, words)
    b = await run(dut, words)
    vals = advance_values(a)
    assert len(vals) >= 20, f"pipeline produced only {len(vals)} real words -- too few"
    assert len(set(vals)) == len(vals), (
        f"the pipeline itself produced a repeated word "
        f"({len(vals) - len(set(vals))} repeats) -- duplicate detection below "
        f"could not tell a stale republication from a coincidence"
    )
    assert advance_values(b) == vals, (
        "two identical no-gap runs produced different words -- the DUT is not "
        "deterministic across reset and every comparison below is void"
    )
    dut._log.info(
        f"C1/C2/C3 OK: {len(vals)} real words produced, {len(set(vals))} distinct, "
        f"and two no-gap runs identical -- any difference under a gap is the gap's"
    )


@cocotb.test()
async def test_align_control_the_gap_actually_opens(dut):
    """C4: the stall reached the DUT.

    A gap that never opened would make every row below vacuously green -- the
    §22.24 anti-weakening shape.  Measured from the bench's own drive record and
    corroborated by the data pipeline holding its value throughout."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for L in GAPS:
        trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=L)
        gap = [r for r in trace if r["in_gap"]]
        assert len(gap) == L, f"L={L}: expected {L} gap clocks, drove {len(gap)}"
        assert not any(r["presented"] for r in gap), \
            f"L={L}: a Symbol was presented inside the gap -- the gap did not open"
        held = {r["data"] for r in gap}
        assert len(held) == 1, (
            f"L={L}: data_out_o took {len(held)} values during the gap -- the data "
            f"pipeline did not freeze, so :102 is not read correctly"
        )
        dut._log.info(f"C4 OK: L={L}, {len(gap)} gap clocks, none presented, "
                      f"data_out_o held {list(held)[0]:#010x} throughout")


# ==========================================================================
#  O-ALIGN clauses (a), (b), (c) -- ORDINARY PASS rows.
#  Candidate B is predicted CORRECT across a stall (PREDICTIONS_1.md P-2).
# ==========================================================================

@cocotb.test()
async def test_align_no_duplication_across_a_gap(dut):
    """O-ALIGN (a) on candidate B -- prediction B1.

    The data pipeline is frozen for the whole gap, so any beat published there
    republishes a stale word.  A 1-stage copy of the input strobe is low
    throughout the gap, so it publishes none."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for L in GAPS:
        trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=L)
        summarize(dut, f"scrambler L={L}", trace)
        idle = idle_beats(trace)
        assert not idle, (
            f"L={L}: {len(idle)} beats published on clocks carrying no Symbol "
            f"(of which {len(gap_beats(trace))} in the mid-stream gap), all "
            f"republishing {idle[0]['data']:#010x} -- the consumer would ingest "
            f"one stale Symbol {len(idle)} times"
        )
        dut._log.info(f"(a) OK: L={L}, 0 beats published on any clock that "
                      f"carried no Symbol -- gap or trailing idle")


@cocotb.test()
async def test_align_no_omission_across_a_gap(dut):
    """O-ALIGN (b) on candidate B -- prediction B2.

    A clock where data_out_o changes while valid is low delivers a Symbol the
    consumer was told to ignore, and it is lost silently."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for L in GAPS:
        trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=L)
        lost = silent_advances(trace)
        assert not lost, (
            f"L={L}: the pipeline advanced on {len(lost)} clock(s) with valid low "
            f"(first at clock {trace.index(lost[0])}, data {lost[0]['data']:#010x}) "
            f"-- those Symbols are dropped"
        )
        dut._log.info(f"(b) OK: L={L}, 0 pipeline advances published with valid low")


@cocotb.test()
async def test_align_beat_count_is_unchanged_by_a_gap(dut):
    """O-ALIGN (a)+(b) jointly, as a count -- prediction B3.

    A gap carries no Symbol (Base 2.1 §4.2.3 p.199: the LFSR advance is per
    Symbol), so it must add and remove nothing.  Comparing the gapped beat count
    against the no-gap reference catches duplication and omission together, and
    catches them even if they were ever to cancel numerically."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = stimulus()
    ref = len(published(await run(dut, words)))
    for L in GAPS:
        got = len(published(await run(dut, words, stall_at=STALL_AT, stall_len=L)))
        assert got == ref, (
            f"L={L}: {got} beats published vs {ref} with no gap ({got - ref:+d}) -- "
            f"the gap changed how many Symbols the consumer sees"
        )
        dut._log.info(f"(a)+(b) OK: L={L}, {got} beats published, same as the "
                      f"no-gap reference")


# ==========================================================================
#  O-ALIGN clause (d) -- expect_fail.  A REAL divergence, newly found by this
#  bench, and NOT the one P2.g or F-5 predicted.  Kept as a failing-against-spec
#  record; never weakened to pass.  §22.66: one divergent assertion per row,
#  not mixed with a conforming one -- (a), (b) and (c) are separate rows above.
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_align_no_fabricated_beats_after_reset(dut):
    """O-ALIGN (d) on candidate B -- prediction B4.  PREDICTED DIVERGENCE.

    scrambler.sv:76 copies the input strobe with ONE register, but the data
    needs DEPTH=4 pipeline advances before a presented Symbol reaches
    data_out_o.  So the first DEPTH-1 = 3 beats are published while data_out_o
    still carries the pipeline's reset content scrambled by the LFSR: the
    consumer is handed 3 Symbols that were never presented.

    Bounded and one-time -- the pipeline holds real in-flight Symbols across a
    gap, so this transient recurs only after a reset, never after a stall.  That
    is why it is recorded rather than fixed in this rung: it is a third
    behaviour change that H-AB's pre-committed matrix does not cover
    (PREDICTIONS_1.md P-5).

    ⚠️ This row is INDEPENDENT of §54 #4 and must stay red when the pair fix
    lands.  If it ever flips, something changed the priming behaviour and that
    was not this arc's doing."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=GAPS[0])
    fab = fabricated(trace)
    dut._log.info(
        f"(d) MEASURED: {len(fab)} fabricated beats after reset "
        f"(n_pres = {[r['n_pres'] for r in fab]}, data = "
        f"{[format(r['data'], '#010x') for r in fab]})"
    )
    assert not fab, (
        f"{len(fab)} beats published before {DEPTH} Symbols had been presented -- "
        f"the consumer is handed Symbols the bench never sent"
    )
