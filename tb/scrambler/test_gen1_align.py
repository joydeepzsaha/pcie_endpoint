"""O-ALIGN on candidate A — `gen1_valid`, the depth-matched valid that is never read.

Toplevel: gen1_scramble.  data_valid_o here is Q.data_valid[NumPipelines-1]
(:282) — the valid that rode the same 4-deep struct pipeline as the data.

WHY THIS ROW EXISTS
-------------------
scrambler.sv:61 wires this output to `gen1_valid`, and gen1_valid is NEVER READ.
Its only other occurrence is a commented-out line at :91, inside the disabled
Gen3 rate mux — which shows the author's intent was to publish it.  FA-2 found
that (FINDINGS_STALL.md §5a) and flagged the obvious repair — wire it up — as
the plausible third edit of the §54 #4 fix.

This bench is what stops that.  The commented-out line is an INVITATION TO
INTRODUCE A DEFECT, and the measurement here is the reason not to accept it.

THE MECHANISM
-------------
gen1_scramble drives its valid chain asymmetrically:

     94    D               = Q;                  // hold
     99    D.data_valid[0] = data_valid_i;       // <-- OUTSIDE the if
    102    if (data_valid_i) begin
    119      D.data_valid[i] = Q.data_valid[i-1]; //     stages 1-3, INSIDE the if
    121      D.data[i]       = Q.data[i-1];       //     the data, INSIDE the if

Stage 0's valid updates every clock; stages 1-3 shift only on presented
Symbols.  Two consequences, both measured below:

  (a) during a gap, stages 1-3 do not shift, so the chain HOLDS -- valid stays
      asserted for the whole gap while data_out_o is frozen, republishing one
      stale Symbol L times;
  (b) on resume, stage 1 loads Q.data_valid[0], which :99 set from inside the
      gap, i.e. ZERO -- a hole travels down the chain beside a real data word,
      and exactly one Symbol is published with valid low and lost.

⚠️ Rung 3 hit (a) a whole arc before it was named, and worked around it rather
than recording it as a defect: tb/phy_receive/test_rx_descramble.py:66-70 says
data_valid_o "FREEZES at its last value when the input goes idle instead of
falling, so a sampler that trusts it would collect the same stale word
repeatedly", and that bench samples per driven Symbol instead of trusting the
output valid.  Same DUT, same signal, same behaviour.

Oracle: pcie_docs/evidence/fix-arc-3/ORACLE.md.
Predictions: PREDICTIONS_1.md §2, committed before this file existed.
"""
import cocotb
from cocotb.clock import Clock

from align_common import (DEPTH, STALL_AT, advance_values, fabricated,
                          gap_beats, idle_beats, published, run,
                          silent_advances, stimulus, summarize)

GAPS = (5, 9)


@cocotb.test()
async def test_gen1_align_control_reference_is_rich_and_repeatable(dut):
    """C1+C2+C3: the pipeline's real output is non-empty, all-distinct, repeatable.

    Distinctness is what licenses reading a republished word as a DUPLICATE
    rather than a coincidence.

    ⚠️ It is asserted over advance_values() -- the words the pipeline advanced
    to on the bench's own presentation clocks -- and NOT over the beats the DUT
    published.  The first version of this control did the latter and failed on
    candidate A (33 published, 29 distinct), because candidate A republishes
    stale words during idle: the control was measuring the very defect the rows
    below exist to measure, so a defective candidate could not be assessed at
    all.  A control must be independent of the signal under test (§22.49's
    reasoning, applied to a control rather than an assertion)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = stimulus()
    a = await run(dut, words)
    b = await run(dut, words)
    vals = advance_values(a)
    assert len(vals) >= 20, f"pipeline produced only {len(vals)} real words"
    assert len(set(vals)) == len(vals), (
        f"the pipeline itself produced a repeated word "
        f"({len(vals) - len(set(vals))} repeats) -- duplicate detection below "
        f"could not tell a stale republication from a coincidence"
    )
    assert advance_values(b) == vals, \
        "two identical no-gap runs produced different words -- DUT not deterministic"
    dut._log.info(f"C1/C2/C3 OK: {len(vals)} real words produced, "
                  f"{len(set(vals))} distinct, and repeatable across reset")


@cocotb.test()
async def test_gen1_align_priming_is_correct(dut):
    """O-ALIGN (d) on candidate A -- prediction A5.  ORDINARY PASS.

    The one clause candidate A gets RIGHT, and it is carried deliberately: the
    chain starts all-zero and shifts only on presented Symbols, so valid first
    rises exactly as the first real Symbol emerges.  Nothing is fabricated.

    Its value is attribution.  Candidate B fails exactly this clause and passes
    the other three; candidate A is the mirror image.  A row that showed A
    failing everything would leave open the possibility that the bench itself
    was broken."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=GAPS[0])
    fab = fabricated(trace)
    assert not fab, (
        f"{len(fab)} fabricated beats -- candidate A's chain does not suppress "
        f"the pipeline fill after all"
    )
    dut._log.info("(d) OK: candidate A fabricates 0 beats after reset -- its "
                  "priming is correct, which candidate B's is not")


# ==========================================================================
#  The two divergences.  expect_fail, one clause each (§22.66 -- never mix a
#  divergent assertion with a conforming one in the same row).
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_gen1_align_no_duplication_across_a_gap(dut):
    """O-ALIGN (a) on candidate A -- predictions A1 + A3.  PREDICTED DIVERGENCE.

    Stages 1-3 do not shift during a gap, so the chain holds its last value and
    publishes the frozen data_out_o once per gap clock.  The count is predicted
    to SCALE with the gap: 5 at L=5, 9 at L=9.  Both lengths are driven, so
    "scales with L" is measured rather than asserted."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    gap_counts, idle_counts = {}, {}
    for L in GAPS:
        trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=L)
        summarize(dut, f"gen1_scramble L={L}", trace)
        dup, idle = gap_beats(trace), idle_beats(trace)
        gap_counts[L], idle_counts[L] = len(dup), len(idle)
        if dup:
            held = {r["data"] for r in dup}
            dut._log.info(
                f"(a) MEASURED: L={L}, {len(dup)} beats published inside the gap, "
                f"{len(held)} distinct value(s) among them "
                f"({', '.join(format(h, '#010x') for h in held)})"
            )
    dut._log.info(f"(a) MEASURED beats-in-gap by gap length: {gap_counts}")
    dut._log.info(f"(a) MEASURED beats-on-any-idle-clock by gap length: {idle_counts} "
                  f"-- the excess over beats-in-gap is the TRAILING idle, so the "
                  f"duplication is not specific to a mid-stream gap")
    assert not any(idle_counts.values()), (
        f"beats published on clocks carrying no Symbol: {idle_counts} (of which "
        f"in-gap: {gap_counts}) -- a stale Symbol is republished once per idle "
        f"clock, so the count scales with the stall"
    )


@cocotb.test(expect_fail=True)
async def test_gen1_align_no_omission_across_a_gap(dut):
    """O-ALIGN (b) on candidate A -- predictions A2 + A3.  PREDICTED DIVERGENCE.

    On resume, stage 1 loads the zero that :99 wrote into stage 0 from inside
    the gap.  That hole reaches the output DEPTH-1 clocks later, beside a real
    data word, and the Symbol is lost.

    Predicted count is ONE, at BOTH gap lengths -- exactly one zero enters the
    chain however long the gap, because stages 1-3 are frozen throughout and
    only the resume edge samples stage 0.  That the omission is
    length-INDEPENDENT while the duplication above is length-PROPORTIONAL is the
    sharpest evidence that these are two distinct defects and not one seen
    twice."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    counts = {}
    for L in GAPS:
        trace = await run(dut, stimulus(), stall_at=STALL_AT, stall_len=L)
        lost = silent_advances(trace)
        counts[L] = len(lost)
        for r in lost:
            dut._log.info(
                f"(b) MEASURED: L={L}, pipeline advanced to {r['data']:#010x} at "
                f"n_pres={r['n_pres']} with valid LOW -- that Symbol is dropped"
            )
    dut._log.info(f"(b) MEASURED counts by gap length: {counts}")
    assert not any(counts.values()), (
        f"Symbols delivered with valid low: {counts} -- one real Symbol is lost "
        f"per gap, independent of gap length"
    )
