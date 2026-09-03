"""
The PIPE-stalling bench — half A of tracker §54 #4, measured for the first time.

WHAT IS BEING MEASURED
----------------------
gen1_scramble.sv's always_comb has exactly six statements before its
`if (data_valid_i)` at :102, and the LFSR advance is one of them:

     94    D                 = Q;                             // hold
     95    D.scramble_reset  = '0;
     96    D.stop_scrambling = '0;
     97    D.lfsr_in         = lfsr_out[(pipe_width_i>>3)];    // <-- UNCONDITIONAL
     98    D.skp_os          = '0;
     99    D.data_valid[0]   = data_valid_i;
    102    if (data_valid_i) begin
    ...       // data pipeline, K detection, byte_cnt, and the XOR at :272 -- gated
    277    end

So when data_valid_i falls mid-stream the DATA FREEZES and the LFSR KEEPS
RUNNING.  The scrambled stream desynchronises from its descrambler by exactly
the stall length, permanently.

⚠️ This is the OPPOSITE of what evidence/rung9/ORACLES_PHY_TX.md:220 and
MUTANTS_R9.md:102 say ("wraps its entire combinational body -- LFSR advance
included -- in if (data_valid_i), so the scrambler stalls rather than
advancing").  Rung 9 cited the behaviour without retesting it and the error was
inherited.  Tracker §54 #4's own wording -- "LFSR advances on every clock" -- is
the correct one.  See evidence/fix-arc-2/PLAN.md §1a.

THE ORACLE  (O-STALL)
---------------------
    Base 2.1 §4.2.3, pp.198-199 -- "The LFSR value is advanced eight serial
    shifts for each Symbol except the SKP."

Per SYMBOL, not per clock.  A clock with data_valid deasserted carries no
Symbol -- that is what the PIPE signal means -- so it must not advance the LFSR.
Hence: across a data_valid_i gap of any length, the output must be IDENTICAL to
what the same symbols would have produced with no gap at all.

The reading is not ambiguous, and the design settles it twice:
  * gen3_scramble.sv:145-150 gates the same advance on data_valid_i, so
    gen1_scramble is the odd one out inside its own module family; and
  * `scrambler` is instantiated as BOTH scrambler_inst (phy_transmit.sv:153)
    and descrambler_inst (phy_receive.sv:143).  Scrambling is XOR and therefore
    self-inverse, so the two ends must advance in lockstep by construction --
    there is no reading under which they may advance by different amounts.

WHY THIS DUT AND NOT phy_transmit
---------------------------------
lane_management.sv:571 hardwires `assign data_valid_o = '1;`, and that feeds
every scrambler through phy_transmit.sv:161.  At the phy_transmit boundary
data_valid is a COMPILE-TIME CONSTANT: no stimulus there can deassert it, only
an RTL edit could, and fix-arc 2 makes none (D-FA2.1).  That is the
cancellation, stated structurally -- half B removes the very stimulus half A
needs -- and it is why §54 #4's two halves must be fixed as a pair.  The
companion bench test_phy_transmit_stall.py measures half B at that boundary.

METHOD -- black box, no internal probe
--------------------------------------
Scrambling is S ⊕ L, so the LFSR never has to be observed directly.  Two runs
over the SAME symbols from the SAME reset state:

    reference (no stall) :  O_ref[i]   = S[i] ⊕ L[i]
    stalled              :  O_stall[i] = S[i] ⊕ L[i+k]   (k = stall × bytes/clk)

O-STALL says the two capture lists are equal.  Under the current RTL they are
not, from the stall onward.  Everything is bounded; nothing is captured from
the DUT and re-asserted against itself.

Only D symbols are driven (data_k_in_i = 0) so the COM / SKP / PAD branches at
:207-:254 never fire, disable_scrambling and skp_os stay 0, and the measurement
isolates the LFSR.  pipe_width_i = 16 is what lane_management.sv:45 drives on
the integrated path (PipeWidthGen1 = 16, two bytes per clock).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# lane_management.sv:45 -- PipeWidthGen1 = 16, i.e. two bytes per clock.
# (data_handler.sv:50 declares its own PipeWidthGen1 = 8; lane_management is the
# one that drives pipe_width_o, so 16 is the integrated-path value.)
PIPE_WIDTH = 16

N_WORDS = 24        # symbols driven per run
STALL_AT = 8        # gap opens just before this word
STALL_LEN = 5       # clocks with data_valid_i low
FLUSH = 8           # extra valid cycles to push the pipeline out (depth is 4)


def _stimulus():
    """A fixed, non-repeating D-symbol sequence.  Deterministic (no RNG) so the
    two runs are identical by construction rather than by seeding discipline,
    and non-constant so that an output that merely holds its value cannot be
    mistaken for a correct one."""
    return [((0x11 * (i + 1)) ^ (0xA5C3 << 8) ^ (i * 0x01010101)) & 0xFFFFFFFF
            for i in range(N_WORDS)]


async def _reset(dut):
    dut.rst_i.value = 1
    dut.data_valid_i.value = 0
    dut.data_in_i.value = 0
    dut.data_k_in_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    dut.lane_number.value = 0
    dut.sync_header_i.value = 0
    dut.block_start_i.value = 0
    dut.curr_data_rate_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 2)


async def _run(dut, words, stall_at=None, stall_len=0, freeze_probe=None):
    """Drive `words` one per valid clock and capture data_out_o on every cycle
    the pipeline actually advances.

    The whole D pipeline (:107-:124) is inside `if (data_valid_i)`, so it steps
    exactly on valid cycles.  Capturing on those cycles therefore gives, in both
    runs, one sample per pipeline step with the same correspondence to the input
    words -- which is what makes the two lists directly comparable.

    If `freeze_probe` is a list, data_out_o is appended to it on each stalled
    cycle, so the caller can assert the pipeline really did freeze.
    """
    await _reset(dut)
    caps = []
    for j, w in enumerate(words):
        if stall_at is not None and j == stall_at:
            dut.data_valid_i.value = 0
            for _ in range(stall_len):
                await RisingEdge(dut.clk_i)
                await Timer(1, units="ps")
                if freeze_probe is not None:
                    freeze_probe.append(int(dut.data_out_o.value))
            dut.data_valid_i.value = 1
        dut.data_in_i.value = w
        dut.data_k_in_i.value = 0
        dut.data_valid_i.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        caps.append(int(dut.data_out_o.value))

    for _ in range(FLUSH):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        caps.append(int(dut.data_out_o.value))
    dut.data_valid_i.value = 0
    return caps


def _first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None


# ==========================================================================
#  Control arms -- ordinary PASS rows.  These exist so that the two expect_fail
#  rows below are known to be measuring the stall and not an artefact.
# ==========================================================================

@cocotb.test()
async def test_stall_control_scrambler_actually_scrambles(dut):
    """C1: the reference capture is non-trivial.

    If the DUT passed data through unscrambled, O_ref would equal S and the
    differential method would be measuring nothing.  Assert the output differs
    from the input for D symbols -- i.e. the LFSR is really being XORed in."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = _stimulus()
    caps = await _run(dut, words)
    assert any(c != 0 for c in caps), "output never left 0 -- DUT produced nothing"
    overlap = set(caps) & set(words)
    assert len(overlap) < len(words), (
        "every captured word appears verbatim in the input -- the scrambler is "
        "passing data through unscrambled, so this bench would measure nothing"
    )
    dut._log.info(
        f"C1 OK: {len(caps)} samples captured, {len(set(caps))} distinct, "
        f"{len(overlap)} coincide with input words -- the LFSR is being applied"
    )


@cocotb.test()
async def test_stall_control_reference_is_repeatable(dut):
    """C2: the differential method is sound.

    Two identical no-stall runs from the same reset must produce byte-identical
    captures.  Without this, a difference seen in the stalled run could not be
    attributed to the stall.  This is the control that makes the expect_fail
    rows below evidence rather than an observation."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = _stimulus()
    a = await _run(dut, words)
    b = await _run(dut, words)
    idx = _first_diff(a, b)
    assert idx is None and len(a) == len(b), (
        f"two identical no-stall runs differ at capture index {idx} "
        f"({a[idx]:#010x} vs {b[idx]:#010x}) -- the DUT is not deterministic "
        f"across reset and the differential measurement is void"
    )
    dut._log.info(
        f"C2 OK: two no-stall runs byte-identical over {len(a)} samples -- any "
        f"difference in the stalled run is attributable to the stall"
    )


@cocotb.test()
async def test_stall_control_pipeline_freezes_during_the_gap(dut):
    """C3: the stall was genuinely applied, and half of §54 #4 confirmed.

    Everything from :102 down is gated on data_valid_i, so the data pipeline
    must hold its value for the whole gap.  Observing that hold proves the gap
    reached the DUT -- and it is also the directly-observed confirmation that
    the DATA half freezes, which is the counterpart to the LFSR half that does
    not (measured by the expect_fail rows)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = _stimulus()
    frozen = []
    await _run(dut, words, stall_at=STALL_AT, stall_len=STALL_LEN,
               freeze_probe=frozen)
    assert len(frozen) == STALL_LEN, \
        f"expected {STALL_LEN} stalled-cycle samples, got {len(frozen)}"
    assert len(set(frozen)) == 1, (
        f"data_out_o changed during the {STALL_LEN}-cycle gap "
        f"({[hex(f) for f in frozen]}) -- the data pipeline did not freeze, so "
        f"the read of :102 is wrong"
    )
    dut._log.info(
        f"C3 OK: data_out_o held {frozen[0]:#010x} for all {STALL_LEN} stalled "
        f"cycles -- the DATA half of the module freezes, as :102 says it must"
    )


# ==========================================================================
#  The divergences.  One per row (§22.66).  Both expect_fail on current RTL;
#  both are predicted to flip to PASS under the H-A / H-AB mutants, which is
#  fix-arc 3's pre-committed matrix.
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_stall_lfsr_must_not_advance_while_data_is_invalid(dut):
    """O-STALL, Base 2.1 §4.2.3 pp.198-199: the LFSR advances once per SYMBOL.

    A clock with data_valid_i low carries no Symbol, so the output across a gap
    must be identical to the no-stall reference.

    DIVERGES: gen1_scramble.sv:97 advances the LFSR outside the
    `if (data_valid_i)`, so from the stall onward every symbol is XORed against
    an LFSR that is STALL_LEN x (pipe_width/8) byte-steps ahead of where the
    receiver's is."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = _stimulus()
    ref = await _run(dut, words)
    stalled = await _run(dut, words, stall_at=STALL_AT, stall_len=STALL_LEN)

    idx = _first_diff(ref, stalled)
    n_diff = sum(1 for x, y in zip(ref, stalled) if x != y)
    dut._log.info(
        f"MEASURED: {n_diff} of {len(ref)} samples differ; first divergence at "
        f"capture index {idx} (stall opened before input word {STALL_AT}); "
        f"ref={ref[idx]:#010x} stalled={stalled[idx]:#010x}"
        if idx is not None else
        f"MEASURED: no divergence over {len(ref)} samples"
    )
    assert stalled == ref, (
        f"O-STALL VIOLATED: a {STALL_LEN}-cycle data_valid gap changed the "
        f"scrambled stream. First divergence at capture index {idx}: reference "
        f"{ref[idx]:#010x} vs stalled {stalled[idx]:#010x}; {n_diff} of "
        f"{len(ref)} samples differ. Base 2.1 4.2.3 p.198 advances the LFSR per "
        f"SYMBOL, and a clock with data_valid low carries none -- so the gap "
        f"must be transparent. gen1_scramble.sv:97 advances it per CLOCK."
    )


@cocotb.test(expect_fail=True)
async def test_stall_stream_never_resynchronises_after_the_gap(dut):
    """A distinct claim from the row above: not "was the stream damaged" but
    "is the damage bounded".

    Base 2.1 §4.2.3 gives the LFSR exactly one re-initialisation mechanism --
    "The COM Symbol initializes the LFSR" -- and this stimulus contains no COM.
    So a desynchronised stream has no way back, and the corruption runs to the
    end of the link rather than for the duration of the gap.  A conforming
    implementation satisfies this trivially by never desynchronising.

    Asserted on the TAIL of the capture, far past the gap, so it fails for a
    genuinely different reason than the row above: that one fails at the first
    post-stall sample, this one at the last.

    DIVERGES: the tail differs, so the far end receives silently corrupted
    payload for the remaining life of the link.  Nothing reports it --
    decode_8b10b's code_err/disp_err are computed and reach nothing (Rung 4 G1),
    and `scrambler` has no error output at all."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    words = _stimulus()
    ref = await _run(dut, words)
    stalled = await _run(dut, words, stall_at=STALL_AT, stall_len=STALL_LEN)

    tail = 6
    ref_tail, st_tail = ref[-tail:], stalled[-tail:]
    n_diff_tail = sum(1 for x, y in zip(ref_tail, st_tail) if x != y)
    dut._log.info(
        f"MEASURED TAIL: {n_diff_tail} of the last {tail} samples still differ, "
        f"{len(ref) - STALL_AT} samples after the gap closed"
    )
    assert st_tail == ref_tail, (
        f"NO RESYNCHRONISATION: {n_diff_tail} of the last {tail} samples still "
        f"differ from the reference, long after the {STALL_LEN}-cycle gap "
        f"closed. The LFSR's only re-initialiser is the COM Symbol (Base 2.1 "
        f"4.2.3 p.198) and this stream carries none, so the desynchronisation "
        f"is permanent: every subsequent Symbol reaches the far end corrupted, "
        f"and no error output on this path reports it."
    )
