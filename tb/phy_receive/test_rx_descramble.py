"""T2 -- spec-golden unit bench for gen1_scramble (the Gen1 descrambler).

Toplevel: gen1_scramble, driven at pipe_width_i = 8, i.e. one Symbol per clock in
data_in_i[7:0] / data_k_in_i[0].  Outputs are collected while data_valid_o.

Oracles (ORACLES_PHY_RX.md, all from PCI Express Base Spec Rev 2.1):
  A2  sec 4.2.3 p.199    LFSR seed is FFFFh
  A3  sec 4.2.3 p.199    a COM initializes the LFSR (App. C.1: reset, no advance)
  A4  sec 4.2.3 p.199    the LFSR is not advanced on SKP
  A5  sec 4.2.3 p.199    K codes are never descrambled
  A6  sec 4.2.3 p.199 +  D Symbols inside a TS1/TS2 Ordered Set are not descrambled
      sec 4.2.4.1 p.201
  A8  sec 4.2.3 p.199    the LFSR advances once per SYMBOL

Expected byte streams come from rx_golden.Descrambler, which is built from the
Appendix C.1 reference implementation and anchored against the two golden tables
printed at Base 2.1 p.700 (checked by test_rx_lfsr.golden_model_self_check).
Nothing here is captured from the DUT.

Tests marked expect_fail are PREDICTED SPEC DIVERGENCES, pre-registered in
pcie_docs/evidence/phy-rx-golden/PREDICTIONS_PHY_RX.md with the file:line that
raises the suspicion.  They are kept as failing-against-spec records, never
weakened to pass.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, Timer

from rx_golden import (COM, SKP, IDL, FTS, PAD, TS1_ID, TS2_ID, advance, xor_mask,
                       Descrambler, ts_ordered_set, skp_os, fts_os, eios, fmt)

PIPE_WIDTH = 8          # Gen1 PIPE: one Symbol per clock
FLUSH = 10              # extra valid Symbols to push the 4-stage pipeline out


async def setup(dut, settle=4):
    """settle -- idle clocks between reset release and the first Symbol.

    It is a parameter because gen1_scramble.sv:97 advances the LFSR on every
    clock rather than every Symbol, so idle clocks are not neutral: they move
    the descrambler's state.  seed_is_ffff_before_any_com sets settle=0 to
    remove that variable and leave only the pipeline offset.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.data_in_i.value = 0
    dut.data_valid_i.value = 0
    dut.data_k_in_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    await ClockCycles(dut.clk_i, 8)
    dut.rst_i.value = 0
    if settle:
        await ClockCycles(dut.clk_i, settle)


async def drive(dut, stream, gap_after=None, gap_len=0):
    """Feed (byte, is_k[, in_ts]) Symbols one per clock; collect descrambled output.

    gap_after -- if given, hold data_valid_i low for gap_len clocks after that
                 many Symbols have been driven.  Used only by the A8 test.
    Returns the list of (byte, is_k) pairs seen while data_valid_o was asserted.

    Sampling happens ONLY on clocks that carried a Symbol.  Two reasons, both
    structural rather than empirical:

      * gen1_scramble.sv:101 guards the data pipeline with `if (data_valid_i)`,
        but :99 assigns D.data_valid[0] outside it while :105-119 shift stages
        1-3 inside it.  data_valid_o therefore FREEZES at its last value when the
        input goes idle instead of falling, so a sampler that trusts it would
        collect the same stale word repeatedly.
      * Sampling per driven Symbol keeps the output list 1:1 with the input
        stream, which is what lets it be compared against the golden model
        element by element.

    Pipeline latency is 4 clocks -- NumPipelines = 4 (gen1_scramble.sv:19) with
    the output taken from Q.data[NumPipelines-1] -- so the last 4 Symbols of a
    stream are still in flight when driving ends and simply never appear.  That
    is why each test appends FLUSH padding Symbols and asserts a minimum
    comparison count rather than an exact one.
    """
    got = []

    async def sample():
        # A bare read after RisingEdge is pre-edge; step 1 ps to land post-edge.
        await Timer(1, units="ps")
        if int(dut.data_valid_o.value) & 1:
            got.append((int(dut.data_out_o.value) & 0xFF,
                        int(dut.data_k_out_o.value) & 0x1))

    for i, sym in enumerate(stream):
        if gap_after is not None and i == gap_after and gap_len:
            dut.data_valid_i.value = 0
            for _ in range(gap_len):
                await RisingEdge(dut.clk_i)   # no Symbol on this clock: no sample
        dut.data_in_i.value = sym[0] & 0xFF
        dut.data_k_in_i.value = sym[1] & 0x1
        dut.data_valid_i.value = 1
        await RisingEdge(dut.clk_i)
        await sample()

    dut.data_valid_i.value = 0
    return got


def golden(stream):
    """Expected descrambled bytes for a stream of (byte, is_k[, in_ts])."""
    d = Descrambler()
    return [d.symbol(s[0], s[1], s[2] if len(s) > 2 else False) for s in stream]


def data_syms(values, in_ts=False):
    return [(v & 0xFF, 0, in_ts) for v in values]


def compare(dut, got, want, label):
    """Element-wise compare and report the first divergence with its index."""
    n = min(len(got), len(want))
    assert n > 0, "%s: the DUT produced no valid output at all" % label
    for i in range(n):
        if got[i][0] != want[i]:
            raise AssertionError(
                "%s: Symbol %d descrambled to %02X, Base 2.1 requires %02X\n"
                "  got : %s\n  want: %s"
                % (label, i, got[i][0], want[i],
                   " ".join("%02x" % g[0] for g in got[:n]),
                   " ".join("%02x" % w for w in want[:n])))
    dut._log.info("%s: %d Symbols match the spec-golden stream" % (label, n))
    return n


# --------------------------------------------------------------------- A5

@cocotb.test()
async def k_codes_never_descrambled(dut):
    """A5, sec 4.2.3 p.199: "All special Symbols (K codes) are not scrambled."

    Drive a run of K codes that are NOT COM or SKP (those have their own rules)
    and require each to emerge byte-identical.
    """
    await setup(dut)
    kruns = (IDL, FTS, PAD, IDL, FTS, PAD, IDL, FTS)
    stream = [(COM, 1, False)]                       # anchor the LFSR first
    stream += [(k, 1, False) for k in kruns]
    stream += data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    dut._log.info("K-code stream in : %s" % fmt(stream[:9]))
    # Scope the comparison to the K-code run itself.  What the descrambler does
    # with the DATA Symbols that follow a COM is a separate claim, tested by
    # non_ts_ordered_set_suppresses_descrambling below.
    n = compare(dut, got[:1 + len(kruns)], golden(stream)[:1 + len(kruns)], "K codes")
    assert n == 1 + len(kruns), \
        "only %d of %d K Symbols compared" % (n, 1 + len(kruns))
    assert all(k == 1 for _, k in got[:1 + len(kruns)]), \
        "K Symbols must stay K-coded through the descrambler: %s" % fmt(got[:9])


# ----------------------------------------------------------------- A2 + A3

@cocotb.test()
async def com_reseeds_lfsr_to_ffff(dut):
    """A2 + A3: the seed is FFFFh (sec 4.2.3 p.199) and a COM re-initializes the
    LFSR (App. C.1 p.699 resets and returns without advancing).

    Stimulus: a complete TS1 Ordered Set (COM + 15 Symbols, Table 4-2 p.201) so
    that the not-scrambled-inside-a-TS rule is satisfied, then scrambled data.
    The first data Symbol after the Ordered Set must be descrambled with the
    LFSR advanced exactly 15 times from FFFFh.
    """
    await setup(dut)
    ts = ts_ordered_set(TS1_ID, link=0x05, lane=0x00)
    prefix = [(ts[0][0], ts[0][1], False)]
    prefix += [(b, k, True) for b, k in ts[1:]]         # A6: body not descrambled

    # Base 2.1 App. C.1 p.698: "THE DESCRAMBLE ROUTINE IS IDENTICAL TO THE
    # SCRAMBLE ROUTINE".  So build the wire stream by *scrambling* the payload
    # with the same golden model, through the same prefix -- no hand-counted
    # LFSR advances, and no value taken from the DUT.
    payload = [(0x11 * (i % 16) + i) & 0xFF for i in range(24)]
    tx = Descrambler()
    for b, k, t in prefix:
        tx.symbol(b, k, t)
    on_wire = [tx.symbol(p, is_k=False) for p in payload]

    stream = prefix + data_syms(on_wire) + data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "COM reseed + TS1 + data")
    assert n >= 16 + len(payload), \
        "only %d Symbols compared; the post-Ordered-Set data was not reached" % n
    # The payload must reappear literally -- that is what "descrambled" means.
    body = [g[0] for g in got[16:16 + len(payload)]]
    assert body == payload, ("descrambled payload: got %s want %s"
                             % (" ".join("%02x" % b for b in body),
                                " ".join("%02x" % b for b in payload)))


# --------------------------------------------------------------------- A6

@cocotb.test()
async def ts_body_is_not_descrambled(dut):
    """A6, sec 4.2.3 p.199 bullet 3 and sec 4.2.4.1 p.201: "Training sequence
    Ordered Sets are never scrambled."

    A TS1 whose Symbols 1-15 are driven literally must emerge literally.  If the
    descrambler wrongly XORed the body, the link/lane/N_FTS fields the LTSSM
    reads would be garbage.
    """
    await setup(dut)
    ts = ts_ordered_set(TS1_ID, link=0x05, lane=0x03, n_fts=0xFF, rate_id=0x02)
    stream = [(ts[0][0], ts[0][1], False)]
    stream += [(b, k, True) for b, k in ts[1:]]
    stream += data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "TS1 body")
    assert n >= 16, "only %d Symbols compared; the Ordered Set was not covered" % n
    out = [g[0] for g in got[:16]]
    assert out == [b for b, _ in ts], (
        "TS1 must pass through literally:\n  got : %s\n  want: %s"
        % (" ".join("%02x" % b for b in out),
           " ".join("%02x" % b for b, _ in ts)))


# --------------------------------------------------------------------- A4

@cocotb.test()
async def skp_does_not_advance_lfsr(dut):
    """A4, sec 4.2.3 p.199: "The LFSR value is advanced eight serial shifts for
    each Symbol except the SKP."  App. C.1 p.698: `if (inbyte == SKIP) return`.

    A SKP Ordered Set (COM + three SKP, sec 4.2.7.1 p.261) is inserted mid-stream.
    Because a receiver may add or delete SKP Symbols in its elastic buffer, the
    LFSR must be unaffected by them -- so the data after the SKP OS descrambles
    with the LFSR state the COM re-seeded, advanced only by the non-SKP Symbols.
    """
    await setup(dut)
    stream = [(COM, 1, False)]
    stream += [(b, k, True) for b, k in ts_ordered_set(TS1_ID)[1:]]
    stream += [(b, k, False) for b, k in skp_os(3)]     # COM + SKP SKP SKP
    stream += data_syms([0x5A] * 12)
    stream += data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "SKP Ordered Set")
    assert n >= 20 + 12, \
        "only %d Symbols compared; the post-SKP data was not reached" % n


@cocotb.test()
async def skp_os_of_five_symbols(dut):
    """C6, sec 4.2.7.2 p.262: "Receivers shall recognize received SKP Ordered Set
    consisting of one COM Symbol followed consecutively by ONE TO FIVE SKP
    Symbols."  The transmitter form is three (sec 4.2.7.1 p.261); a receiver that
    only tolerates three is non-conformant.

    NOTE: this is the one claim in the oracle table with no cross-check --
    MindShare gives only the transmitter's three-SKP form (ORACLES §6, F-4).
    """
    await setup(dut)
    stream = [(COM, 1, False)]
    stream += [(b, k, True) for b, k in ts_ordered_set(TS1_ID)[1:]]
    stream += [(b, k, False) for b, k in skp_os(5)]     # COM + five SKP
    stream += data_syms([0xA5] * 12)
    stream += data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "five-Symbol SKP Ordered Set")
    assert n >= 22 + 12, "only %d Symbols compared" % n


# --------------------------------------------------------------------- A8

@cocotb.test(expect_fail=True)
async def lfsr_advances_per_symbol_not_per_clock(dut):
    """A8, sec 4.2.3 p.199: the LFSR "is advanced eight serial shifts for each
    SYMBOL".  MindShare p.402 agrees: "for every character (D or K character)
    RECEIVED."  A clock with data_valid_i low carries no Symbol and must not
    advance the LFSR.

    PREDICTED DIVERGENCE (PREDICTIONS_PHY_RX.md sec 2, T2).
    gen1_scramble.sv:97 assigns
        D.lfsr_in = lfsr_out[(pipe_width_i>>3)];
    OUTSIDE the `if (data_valid_i)` guard that opens at :101, so the LFSR steps on
    every clock edge.  The data pipeline does stall (D.data[] is written only
    inside the guard), so after a gap the two are out of step and every
    subsequent Symbol descrambles wrongly.

    Consequence on real hardware: any PIPE stall -- and the RX interface is not
    guaranteed gapless -- silently corrupts the rest of the packet stream.  Kept
    as expect_fail; see FINDINGS_PHY_RX_GOLDEN.md.
    """
    await setup(dut)
    stream = [(COM, 1, False)]
    stream += [(b, k, True) for b, k in ts_ordered_set(TS1_ID)[1:]]
    stream += data_syms([0x3C] * 8)
    gap_at = len(stream)
    stream += data_syms([0x3C] * 8)
    stream += data_syms([0x00] * FLUSH)
    got = await drive(dut, stream, gap_after=gap_at, gap_len=3)
    n = compare(dut, got, golden(stream), "one-Symbol-per-clock LFSR (3-clock gap)")
    assert n >= gap_at + 8, "only %d Symbols compared" % n


# ------------------------------------------------- A6, negative direction

@cocotb.test(expect_fail=True)
async def non_ts_ordered_set_suppresses_descrambling(dut):
    """A6, the exemption's BOUNDARY: sec 4.2.3 p.199 bullet 3 exempts D Symbols
    "within a Training Sequence Ordered Sets (e.g., TS1, TS2), and the Compliance
    Pattern ... and the Modified Compliance Pattern" -- and nothing else.

    An FTS Ordered Set is four Symbols: COM + three K28.1 (sec 4.2.4.5 p.208).
    The Symbols that follow it are ordinary scrambled data and MUST be
    descrambled.  Same for the four-Symbol EIOS (Table 4-4 p.205).

    DIVERGENCE.  gen1_scramble.sv:232 opens a fixed SIXTEEN-Symbol
    no-descramble window on every COM that is not immediately followed by SKP:

        D.byte_cnt = (pipe_width_i >> 3) - (byte_idx);
        for (...) if (d_idx >= byte_idx) D.disable_scrambling[d_idx] = '1';

    and :164 only re-enables once `(Q.byte_cnt + byte_idx + 1) > 16`.  Sixteen is
    the length of a TS1/TS2 Ordered Set (Table 4-2 p.201), so the window is right
    for a TS and wrong for every shorter Ordered Set: after a 4-Symbol FTS OS or
    EIOS, Symbols 4-15 are real data that the RTL passes through unscrambled.

    The SKP OS escapes this because :240 takes a separate `is_skp_os` path that
    holds the LFSR without opening the window -- which is why
    skp_does_not_advance_lfsr passes.

    NOT PRE-REGISTERED: found while authoring T2, after PREDICTIONS_PHY_RX.md was
    committed.  Recorded as such in FINDINGS_PHY_RX_GOLDEN.md; it is not scored
    as a prediction win.
    """
    await setup(dut)
    prefix = [(b, k, False) for b, k in fts_os()]     # COM + FTS FTS FTS
    payload = [(0x37 + i) & 0xFF for i in range(16)]
    tx = Descrambler()
    for b, k, t in prefix:
        tx.symbol(b, k, t)
    on_wire = [tx.symbol(p, is_k=False) for p in payload]

    stream = prefix + data_syms(on_wire) + data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "data after a 4-Symbol FTS Ordered Set")
    assert n >= len(prefix) + len(payload), "only %d Symbols compared" % n


# --------------------------------------------------------------- A2, alone

@cocotb.test(expect_fail=True)
async def seed_is_ffff_before_any_com(dut):
    """A2 in isolation: sec 4.2.3 p.199 -- "The initialized value of an LFSR seed
    (D0-D15) is FFFFh."  App. C.1 p.699 starts `lfsr = 0xffff` and XORs the very
    first byte with it.

    Every other test in this file anchors on a COM first, and a COM re-seeds the
    LFSR through a different path (gen1_scramble.sv:~230 scramble_reset, forcing
    '1 at :76-77).  None of them can tell the reset seed from the COM seed, so
    this drives data straight out of reset with no COM at all.

    DIVERGENCE, and NOT the one predicted.  PREDICTIONS_PHY_RX.md sec 2 called
    this "conforms" on the strength of gen1_scramble.sv:85 holding the right
    value -- that reasoning was about the register and not about what is
    observable, and it is scored a loss.

    The seed register IS FFFFh.  What fails is alignment: :85 loads the LFSR the
    instant reset releases, while the data it must XOR against is still three
    stages away from the output (the XOR at :272 pairs the current lfsr_out with
    Q.data[NumPipelines-2]).  By the time the first Symbol arrives at that stage
    the LFSR has advanced three times, so it descrambles with the fourth state
    instead of the seed.  A COM hides this because its reset propagates through
    the same pipeline and re-anchors both sides together -- which is why a link
    that always begins with training sequences never notices.

    settle=0 removes the idle-clock variable (:97 advances the LFSR every clock,
    the A8 defect), leaving the pipeline offset as the only cause.
    """
    await setup(dut, settle=0)
    payload = [(0x2A + 3 * i) & 0xFF for i in range(16)]
    tx = Descrambler()                       # starts at the spec seed, no COM
    on_wire = [tx.symbol(p, is_k=False) for p in payload]
    stream = data_syms(on_wire) + data_syms([0x00] * FLUSH)
    got = await drive(dut, stream)
    n = compare(dut, got, golden(stream), "reset seed, no COM")
    assert n >= len(payload), "only %d Symbols compared" % n
    body = [g[0] for g in got[:len(payload)]]
    assert body == payload, ("descrambled from the reset seed: got %s want %s"
                             % (" ".join("%02x" % b for b in body),
                                " ".join("%02x" % b for b in payload)))
