"""O-SKPSEED — what LFSR value follows a SKP Ordered Set.  Tracker §54 #9(B).

Toplevel: `scrambler`, the wrapper phy_transmit.sv:153 and phy_receive.sv:143
both instantiate, so this measures the shipping Gen1 path on both directions.

THE CLAIM
---------
Base 2.1 §4.2.3 p.199 is unconditional about the COM:

    "The COM Symbol initializes the LFSR."
    "The LFSR value is advanced eight serial shifts for each Symbol except the
     SKP."
    "The initialized value of an LFSR seed (D0-D15) is FFFFh.  Immediately after
     a COM exits the Transmit LFSR, the LFSR on the Transmit side is
     initialized.  EVERY TIME a COM enters the Receive LFSR on any Lane of that
     Link, the LFSR on the Receive side is initialized."

A SKP Ordered Set is COM + 3×SKP.  No exemption is made for its COM.  So:

    the first data Symbol after a SKP Ordered Set is XORed with FFFFh itself.

WHY THIS BENCH EXISTS — A MEASURED NEAR-MISS, NOT A HYPOTHETICAL
----------------------------------------------------------------
gen1_scramble.sv:73 is what delivers that FFFFh, because :284 takes
`if (!is_skp_os)` and a SKP Ordered Set's COM deliberately never raises
scramble_reset.  The line nonetheless READS like a defect — it hands a SKP the
'1 that looks like it belongs to a COM — and was registered as tracker §54 #9(B)
on exactly that reading, twice, across two recon passes.

Fix-arc 5c measured both directions before editing anything.  As written, the
post-Ordered-Set data matches the spec model at phase 0, all 20 words, bit
exact.  Rewritten as a hold — the "obvious" three-way repair — it matches only
at phase +17: every data Symbol after the Ordered Set corrupted, permanently,
with no resynchronisation because the LFSR's only re-initialiser is a COM.

**No row in the suite caught that.**  The 4c rows are SCHEDULE differentials:
they compare a gapped run against a gap-free reference FROM THE SAME BUILD, so
under the "repair" both move together and both stay green.  The repair would
have landed behind a fully green gate.  These rows are the oracle that was
missing, and they are the reason the near-miss is not repeatable.

Full evidence: pcie_docs/evidence/fix-arc-5/FINDINGS_9B_OBSERVABILITY.md.

ROW SET
-------
  S1  control, ordinary PASS   the instrument DISCRIMINATES -- exactly one phase
                               in a 24-wide sweep reproduces the data, so
                               "matches at 0" is a real constraint and not
                               something many phases would satisfy
  S2  ordinary PASS            THE MEASUREMENT -- that unique phase is 0
  S3  control, ordinary PASS   INDEPENDENT OBSERVATION POINT (§22.80) -- the
                               same model at phase 0 must NOT reproduce the data
                               BEFORE the Ordered Set, so S2 is a property of
                               the post-Ordered-Set segment and not of the
                               stimulus in general

S2 carries ONE divergent assertion (§22.66) and is never mixed with a
conforming one.  No expected value anywhere is captured from the DUT: all three
rows compare against skpseed_common.py, which carries the spec tables.

⚠️ These are ordinary PASS rows, not expect_fail.  They pass on current RTL
BECAUSE THE RTL IS CORRECT; they are a guard against a future "repair", which is
the failure mode actually observed.  A mutant that turns :73 into a hold reddens
S2 and leaves S1 green — recorded in MUTANTS_FA5.md.
"""
import cocotb
from cocotb.clock import Clock

from kgap_common import PRE, POST, _d, build, run
from skpseed_common import matching_phases, publication_skew, seeded_stream

# The SKP Ordered Set in build("skp") is two PIPE words: COM SKP | SKP SKP.
N_OS_WORDS = 2

# How many phases to sweep in S1.  Wide enough that a unique hit is meaningful,
# and it comfortably contains the +17 the "hold" rewrite lands on, so the sweep
# would SEE that variant rather than run off the end of its window.
PHASE_WINDOW = 24

# The POST payload, by value.  kgap_common.build() emits _d(PRE+1+i) for its
# trailing words regardless of how many words the Ordered Set took, so these are
# the data Symbols that follow the Ordered Set.
POST_WORDS = [_d(PRE + 1 + i)[0] for i in range(POST)]


async def start(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())


async def post_ordered_set_data(dut):
    """Drive build("skp") and return the published words that follow the SKP
    Ordered Set, with the publication skew derived from this same run."""
    words, j = build("skp")
    published = await run(dut, words)
    skew = publication_skew(published, j, N_OS_WORDS)
    start_idx = j + N_OS_WORDS + skew
    dut._log.info("O-SKPSEED: Ordered Set presented at word %d, publication "
                  "skew=%d, post-Ordered-Set data published from index %d"
                  % (j, skew, start_idx))
    got = [d for d, _ in published[start_idx:start_idx + POST]]
    assert len(got) == POST, (
        "only %d of %d post-Ordered-Set words were published" % (len(got), POST))
    return got, published, skew, j


# ------------------------------------------------------------------ S1

@cocotb.test()
async def control_the_seed_phase_is_uniquely_determined(dut):
    """S1 — the instrument discriminates.

    If many phases reproduced the published data, "it matches at phase 0" would
    be a coincidence rather than a measurement, and S2 would be a vacuous green
    (§22.67).  With a 16-bit LFSR and 20 words a spurious second hit is
    overwhelmingly unlikely, but "unlikely" is not "measured", so it is counted.

    Independent observation point (§22.80): this row never mentions phase 0.  It
    asks only HOW MANY phases fit, so it shares no expected value with S2.
    """
    await start(dut)
    got, _, _, _ = await post_ordered_set_data(dut)
    hits = matching_phases(POST_WORDS, got, PHASE_WINDOW)
    dut._log.info("S1: phases in 0..%d reproducing the post-Ordered-Set data: %s"
                  % (PHASE_WINDOW - 1, hits))
    assert len(hits) == 1, (
        "expected exactly ONE LFSR phase to reproduce the data, found %d (%s). "
        "With 0 the model has no power here; with >1 the phase is not pinned "
        "and S2's verdict would not be a measurement." % (len(hits), hits))


# ------------------------------------------------------------------ S2

@cocotb.test()
async def data_after_a_skp_ordered_set_is_seeded_ffffh(dut):
    """S2 — THE MEASUREMENT.

    Base 2.1 §4.2.3 p.199 initializes the LFSR on EVERY COM and exempts only the
    SKP from the advance.  A SKP Ordered Set is COM + 3×SKP, so it leaves the
    LFSR at FFFFh and the next data Symbol meets FFFFh itself — phase 0.

    ⚠️ This row is what stands between gen1_scramble.sv:73 and a plausible,
    spec-quoting, entirely wrong "repair".  See the module docstring.

    ONE divergent assertion (§22.66): the phase that reproduces the published
    post-Ordered-Set data is 0.
    """
    await start(dut)
    got, _, _, _ = await post_ordered_set_data(dut)
    expected = seeded_stream(POST_WORDS, 0)
    fd = next((i for i, (x, y) in enumerate(zip(expected, got)) if x != y), None)
    if fd is not None:
        hits = matching_phases(POST_WORDS, got, PHASE_WINDOW)
        dut._log.info("S2: FIRST DIFFERENCE at word %d -- spec %04x, published "
                      "%04x; the published stream instead fits phase(s) %s"
                      % (fd, expected[fd], got[fd], hits))
        dut._log.info("S2:   spec[%d..] %s" % (fd, " ".join("%04x" % v for v in expected[fd:fd + 8])))
        dut._log.info("S2:   dut [%d..] %s" % (fd, " ".join("%04x" % v for v in got[fd:fd + 8])))
    else:
        dut._log.info("S2: all %d post-Ordered-Set words match the FFFFh-seeded "
                      "spec model" % len(expected))
    assert fd is None, (
        "the data following a SKP Ordered Set is not seeded FFFFh -- first "
        "difference at word %d (spec %04x, published %04x).  Base 2.1 §4.2.3 "
        "p.199: the Ordered Set's COM initializes the LFSR and its three SKPs "
        "do not advance it, so the next data Symbol is XORed with FFFFh itself."
        % (fd, expected[fd] if fd is not None else 0, got[fd] if fd is not None else 0))


# ------------------------------------------------------------------ S3

@cocotb.test()
async def control_the_model_does_not_fit_the_pre_ordered_set_data(dut):
    """S3 — independent observation point.

    The FFFFh-seeded model must NOT reproduce the data that precedes the Ordered
    Set.  Those words are scrambled from whatever state the LFSR reached after
    reset, which is not FFFFh at their position, so a model that fitted them too
    would be fitting the stimulus rather than the seed and S2 would prove
    nothing about the Ordered Set.

    Independent observation point (§22.80): a DIFFERENT SEGMENT of the same run,
    one the Ordered Set has not yet influenced.  It shares the stimulus and the
    model with S2 but not the thing under test.
    """
    await start(dut)
    _, published, skew, j = await post_ordered_set_data(dut)
    pre_words = [_d(i)[0] for i in range(PRE)]
    pre_got = [d for d, _ in published[skew:skew + PRE]]
    dut._log.info("S3: pre-Ordered-Set published words %s"
                  % " ".join("%04x" % v for v in pre_got))
    assert seeded_stream(pre_words, 0) != pre_got, (
        "the FFFFh-seeded model reproduced the data BEFORE the Ordered Set too. "
        "That would mean the model fits this stimulus generally rather than the "
        "seed the Ordered Set leaves behind, and S2 would carry no information.")
