"""Shared machinery for the O-KGAP benches (fix-arc 4, Phase 1).

O-KGAP — does a K code's scrambler-state pulse survive a `data_valid` gap?
Stated in full in pcie_docs/evidence/fix-arc-4/ORACLE_4C.md; restated here in the
form the code enforces:

    Let S be the sequence of Symbols presented on clocks where data_valid_i is
    high.  Let E be the sequence of Symbols published — (data_out_o, data_k_out_o)
    on clocks where data_valid_o is high.

        O-KGAP:  E is a function of S ALONE.

    Two clock schedules delivering the same Symbol sequence must publish the same
    Symbol sequence, whatever pattern of valid-low clocks separates them.  In
    particular, a COM at position p in S initializes the LFSR for every Symbol
    after p, regardless of any gap.

Base 2.1 §4.2.3 pp.198-199 locates the event in the SYMBOL STREAM, never on a
clock: "The COM Symbol initializes the LFSR"; "Immediately after a COM exits the
Transmit LFSR, the LFSR on the Transmit side is initialized"; "Every time a COM
enters the Receive LFSR on any Lane of that Link, the LFSR on the Receive side is
initialized."  A clock carrying no Symbol is not part of that stream.

WHY THIS BENCH MAY COMPARE VALUES, WHERE THE O-ALIGN BENCH MAY NOT
------------------------------------------------------------------
align_common.py's header records why O-ALIGN had to be value-free: with tracker
§54 #4 open the LFSR advanced through every gap, so EVERY gap corrupted EVERY
later value and a value-comparing bench would have failed on that and never
reached the question it was asking.

§54 #4 is closed (b8d7617).  Gaps are now value-transparent for a Symbol stream
containing no K codes — which is what makes a value differential a sharp
instrument for the K-code question instead of a saturated one.  That
transparency is NOT assumed here: it is control C2, and if it fails the finding
is broader than 4c.

WHY THE OFFSET IS SWEPT AND NOT GUESSED
---------------------------------------
A single-offset test could only say "a gap somewhere near a COM changes the
stream".  Sweeping δ across a window localises the loss to an exact offset and
shows transparency either side of it — a strictly stronger and more falsifiable
claim.  Both gap lengths are driven at every δ, because "this does not depend on
gap length" is a measurement only if two lengths were driven (§60.2's precedent).

⚠️ align_common.py is deliberately NOT reused or edited.  Two green gate targets
depend on it (verilate_scrambler_align, verilate_gen1_align); a shared-helper
edit could move their rows for a reason unrelated to this rung.
"""
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# lane_management.sv:45 -- PipeWidthGen1 = 16, the integrated-path value, so two
# Symbols per clock in data_in_i[15:0] with data_k_in_i[1:0].
PIPE_WIDTH = 16
NBYTES = PIPE_WIDTH // 8

# src/packages/pcie_phy_pkg.sv:100,106
COM = 0xBC          # K28.5
SKP = 0x1C          # K28.0

PRE = 6             # D words before the ordered set: moves the LFSR off FFFFh,
                    # so a LOST re-initialisation is observable at all
POST = 20           # words after: >= 8 to clear the 16-byte disable_scrambling
                    # window, plus room to observe resumed scrambling
FLUSH = 8           # extra presented words to push the depth-4 pipeline out
TAIL = 4

# The swept gap offsets, as deltas from the COM's presentation index j.
OFFSETS = [1, 2, 3, 4, 5, 6]
GAP_LENS = [3, 7]

# ORACLE_4C.md §5: the pulse is raised at j+2 (detection reads pipeline stage 1)
# and consumed at j+3 (`:119` latches the reset).  j+3 is the single vulnerable
# clock.  Named here so the localiser row and the measurement row cannot drift
# apart.
VULNERABLE = 3


def _d(i):
    """A D-Symbol pair.  Deterministic (no RNG, so two runs are identical by
    construction rather than by seeding discipline) and non-repeating, so an
    output that merely holds its value cannot pass for a correct one."""
    lo = (0x31 + 7 * i) & 0xFF
    hi = (0x8D + 5 * i) & 0xFF
    return ((hi << 8) | lo), 0


def build(kind):
    """Return (words, j) where words is a list of (data32, k4) and j is the
    presentation index of the ordered set.

    kind == "com"  a TS-style ordered set: COM in byte 0, a D-Symbol in byte 1.
                   The D-Symbol matters: gen1_scramble.sv:242 reads byte 1 to
                   decide is_skp_os, and a SKP there would take the other branch.
    kind == "skp"  a SKP ordered set: COM SKP | SKP SKP, taking the :257 branch.
    kind == "nok"  the SAME stream with NO K code anywhere -- the K path is
                   ABSENT from the stimulus, not merely unexercised.  Used by
                   controls C2 and C3 (§22.80: a control must not share a
                   dependency with the path under test).
    """
    words = [_d(i) for i in range(PRE)]
    j = len(words)
    if kind == "com":
        words.append((((0x4A) << 8) | COM, 0b01))
    elif kind == "skp":
        words.append(((SKP << 8) | COM, 0b11))
        words.append(((SKP << 8) | SKP, 0b11))
    elif kind == "nok":
        words.append((((0x4A) << 8) | 0x5D, 0b00))
    else:
        raise ValueError(kind)
    words += [_d(PRE + 1 + i) for i in range(POST)]
    return words, j


async def reset(dut):
    dut.rst_i.value = 1
    dut.data_valid_i.value = 0
    dut.data_in_i.value = 0
    dut.data_k_in_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    for name, val in (("lane_number", 0), ("sync_header_i", 0),
                      ("block_start_i", 0), ("curr_data_rate_i", 0)):
        if hasattr(dut, name):
            getattr(dut, name).value = val
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 2)


async def run(dut, words, stall_at=None, stall_len=0):
    """Drive `words`, returning E — the published Symbol sequence.

    E is collected gated on data_valid_o, which at this toplevel is
    scrambler.sv:76's 1-stage register copy of data_valid_i.  FA-3 measured that
    candidate against O-ALIGN and found it publishes 0 beats on Symbol-less
    clocks and drops 0 Symbols, so len(E) is the presented-word count in every
    run and the two lists compare elementwise.

    A bare read after RisingEdge is PRE-edge; Timer(1 ps) lands post-edge.
    """
    await reset(dut)
    out = []

    async def step(present, w=0, k=0):
        if present:
            dut.data_in_i.value = w
            dut.data_k_in_i.value = k
            dut.data_valid_i.value = 1
        else:
            dut.data_valid_i.value = 0
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.data_valid_o.value) & 1:
            out.append((int(dut.data_out_o.value),
                        int(dut.data_k_out_o.value) & 0xF))

    for idx, (w, k) in enumerate(words):
        if stall_at is not None and idx == stall_at and stall_len:
            for _ in range(stall_len):
                await step(False)
        await step(True, w, k)

    for _ in range(FLUSH):
        await step(True, 0, 0)

    for _ in range(TAIL):
        await step(False)
    return out


def first_diff(a, b):
    """Index of the first differing element, or None. Length mismatch reports at
    the shorter length so a truncation is never silently read as agreement."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def fmt(seq, lo, n=8):
    return " ".join("%08x/%x" % (d, k) for d, k in seq[lo:lo + n])


async def sweep(dut, kind, label):
    """Run the gap-free reference and every (δ, L) combination.

    Returns (ref, results) where results maps (delta, gap_len) -> first-diff
    index or None.  Every combination is logged, so a log line exists for each
    number a report will later quote (§22.67, §22.68).
    """
    words, j = build(kind)
    ref = await run(dut, words)
    results = {}
    for delta in OFFSETS:
        for glen in GAP_LENS:
            got = await run(dut, words, stall_at=j + delta, stall_len=glen)
            fd = first_diff(ref, got)
            results[(delta, glen)] = fd
            if fd is None:
                dut._log.info(
                    "O-KGAP[%s] j=%d delta=j+%d gap=%d : IDENTICAL "
                    "(len ref=%d got=%d)" % (label, j, delta, glen, len(ref), len(got)))
            else:
                # Does it ever resynchronise?  The LFSR's only re-initialiser is
                # a COM (§4.2.3 p.199), so a lost initialisation is permanent
                # rather than self-healing -- but that is a claim, so it is
                # counted rather than asserted in prose.
                tail = list(zip(ref[fd:], got[fd:]))
                same = sum(1 for x, y in tail if x == y)
                dut._log.info(
                    "O-KGAP[%s] j=%d delta=j+%d gap=%d : DIFFERS at E[%d] "
                    "(len ref=%d got=%d) tail=%d of which still-equal=%d "
                    "-> resynchronised=%s"
                    % (label, j, delta, glen, fd, len(ref), len(got),
                       len(tail), same, "YES" if same else "NO"))
                dut._log.info("O-KGAP[%s]   ref[%d..] %s" % (label, fd, fmt(ref, fd)))
                dut._log.info("O-KGAP[%s]   got[%d..] %s" % (label, fd, fmt(got, fd)))
    diverging = sorted({d for (d, _), fd in results.items() if fd is not None})
    dut._log.info("O-KGAP[%s] diverging offsets = %s (vulnerable window = j+%d)"
                  % (label, ["j+%d" % d for d in diverging], VULNERABLE))
    return ref, j, results
