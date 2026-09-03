"""Shared machinery for the O-ALIGN benches (fix-arc 3, Phase 1).

O-ALIGN — the valid-to-data alignment oracle at the scrambler's producer
boundary.  Stated in full in pcie_docs/evidence/fix-arc-3/ORACLE.md; restated
here in the form the code enforces:

    Sample (data_out_o, data_valid_o) on EVERY clock.  Let E be the subsequence
    of data_out_o taken from the clocks where data_valid_o is high.  O-ALIGN
    holds iff E renders the transformed input Symbol sequence with
      (a) no duplication   (b) no omission   (c) in order   (d) no fabrication
    and it must hold across a mid-stream data_valid_i gap of ANY length.

WHY THIS MEASUREMENT IS VALUE-FREE
----------------------------------
Half A of tracker §54 #4 is UNFIXED while this bench first runs: across a gap
the LFSR keeps advancing, so the scrambled data VALUES are corrupted (FA-2
measured 24 of 32 samples diverging).  A bench that compared E against a golden
scrambled stream would fail on the values and never reach the alignment
question.

So nothing here compares a data value against a model.  Every claim is
structural — how many beats were published, were any republished, did the
pipeline advance on a clock that published nothing.  That is what lets exactly
the same rows run before the fix and after it, unchanged.

WHY IT IS NOT A DUT-MIRROR  (§22.49)
------------------------------------
The expected beat schedule comes from the bench's OWN drive record — the clocks
on which the bench chose to present a Symbol — and never from sampling the DUT's
data_valid_i pin.  Asserting `data_valid_o(m) == data_valid_i(m-1)` would be
true by construction for the 1-stage candidate and would measure nothing at all.

THE TWO CANDIDATES, AND WHY TWO TOPLEVELS
-----------------------------------------
  candidate A   gen1_scramble.sv:282  Q.data_valid[NumPipelines-1] -- the valid
                that rode the same 4-deep struct pipeline as the data.  Wired to
                `gen1_valid` at scrambler.sv:61 and NEVER READ; its only other
                occurrence is a commented-out line at :91 inside the disabled
                Gen3 rate mux.  Observed by driving gen1_scramble as toplevel.

  candidate B   scrambler.sv:76       data_valid_o <= data_valid_i, a 1-stage
                register copy.  This is what every consumer actually sees.
                Observed by driving scrambler as toplevel.

data_out_o is the SAME signal in both (scrambler.sv:85 assigns it straight from
gen1_data), so the two targets differ in the valid alone — which is the variable
under test.  Black box at each module's own boundary; no internal probe.
"""
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# lane_management.sv:45 -- PipeWidthGen1 = 16, the integrated-path value.
PIPE_WIDTH = 16

N_WORDS = 24        # Symbols presented before the flush
STALL_AT = 8        # the gap opens just before this Symbol
FLUSH = 8           # extra presented Symbols, to push the depth-4 pipeline out
DEPTH = 4           # gen1_scramble.sv:18 -- NumPipelines


def stimulus():
    """Distinct, non-repeating D-Symbols.

    Deterministic (no RNG) so two runs are identical by construction rather than
    by seeding discipline, and non-constant so that an output which merely holds
    its value cannot be mistaken for a correct one (§22.53 — a payload must not
    be a fixed point of the transform under test)."""
    return [((0x11 * (i + 1)) ^ (0xA5C3 << 8) ^ (i * 0x01010101)) & 0xFFFFFFFF
            for i in range(N_WORDS)]


async def reset(dut):
    dut.rst_i.value = 1
    dut.data_valid_i.value = 0
    dut.data_in_i.value = 0
    dut.data_k_in_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    # Present only on the wrapper; gen1_scramble has no such ports.
    for name, val in (("lane_number", 0), ("sync_header_i", 0),
                      ("block_start_i", 0), ("curr_data_rate_i", 0)):
        if hasattr(dut, name):
            getattr(dut, name).value = val
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 2)


async def run(dut, words, stall_at=None, stall_len=0, tail=4):
    """Drive `words`, sampling (data_out_o, data_valid_o) on EVERY clock.

    Returns a list of per-clock records, one per clock edge after reset:

        {"presented": bool,   # did the bench present a Symbol on THIS edge
         "n_pres":    int,    # Symbols presented on edges 0..this one inclusive
         "data":      int,    # data_out_o sampled just after the edge
         "valid":     bool,   # data_valid_o sampled just after the edge
         "in_gap":    bool}   # this edge lies inside the mid-stream gap

    `n_pres` is the bench's own count, and it is what makes the fabrication test
    possible without a data model: the pipeline is valid-gated (the whole body
    from gen1_scramble.sv:102 down is inside `if (data_valid_i)`), so it advances
    exactly once per presented Symbol.  After k presentations the output holds
    presented word k-DEPTH, which exists only once k >= DEPTH.  Any beat
    published while n_pres < DEPTH is therefore fabricated from the pipeline's
    reset content, by counting alone.

    A bare read after RisingEdge is PRE-edge; Timer(1 ps) lands post-edge.
    """
    await reset(dut)
    trace = []
    n_pres = 0

    async def step(presented, in_gap=False):
        nonlocal n_pres
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if presented:
            n_pres += 1
        trace.append({
            "presented": presented,
            "n_pres": n_pres,
            "data": int(dut.data_out_o.value),
            "valid": bool(int(dut.data_valid_o.value) & 1),
            "in_gap": in_gap,
        })

    for j, w in enumerate(words):
        if stall_at is not None and j == stall_at and stall_len:
            dut.data_valid_i.value = 0
            for _ in range(stall_len):
                await step(presented=False, in_gap=True)
        dut.data_in_i.value = w
        dut.data_k_in_i.value = 0
        dut.data_valid_i.value = 1
        await step(presented=True)

    for _ in range(FLUSH):
        dut.data_in_i.value = 0
        dut.data_valid_i.value = 1
        await step(presented=True)

    dut.data_valid_i.value = 0
    for _ in range(tail):
        await step(presented=False)
    return trace


# ---------------------------------------------------------------------------
#  Derived quantities.  Each one is one O-ALIGN clause, computed from the trace.
# ---------------------------------------------------------------------------

def published(trace):
    """The beats E — the clocks on which the DUT said "here is a Symbol"."""
    return [r for r in trace if r["valid"]]


def advance_values(trace):
    """The real output words, identified WITHOUT consulting the valid under test.

    The pipeline is valid-gated, so it advances exactly on the clocks where the
    bench presented a Symbol, and the word it advanced to is real once DEPTH
    presentations have happened.  Both facts come from the bench's own drive
    record.

    ⚠️ This exists because the first version of the C2 control asserted
    distinctness over `published()` — i.e. over the output of the very signal
    being judged — and candidate A failed it (33 beats, 29 distinct) for the
    same reason it fails clause (a): it republishes stale words during idle.
    A control must not depend on the signal under test, or a defective candidate
    cannot even be measured.  Caught by the control firing, which is what
    §22.3 says controls are for."""
    return [r["data"] for r in trace if r["presented"] and r["n_pres"] >= DEPTH]


def idle_beats(trace):
    """(a) DUPLICATION, general form: beats published on a clock that carried no
    Symbol.

    The data pipeline is frozen whenever nothing is presented (gated at :102,
    and FA-2's C3 measured the hold directly), so every such beat republishes a
    stale word.  A correct valid publishes none — including in the trailing idle
    after the stream ends, not just in a mid-stream gap."""
    return [r for r in trace if r["valid"] and not r["presented"]]


def gap_beats(trace):
    """(a) restricted to the mid-stream gap, so the count can be shown to SCALE
    with gap length while the omission count does not."""
    return [r for r in trace if r["in_gap"] and r["valid"]]


def silent_advances(trace):
    """(b) OMISSION: clocks where data_out_o changed while valid was LOW.

    The pipeline advanced and delivered a Symbol the consumer was told to
    ignore, so that Symbol is lost.  Restricted to n_pres >= DEPTH: before the
    pipeline primes there is no real Symbol to omit, and the reset content
    naturally changes while candidate A's chain is still correctly low."""
    out = []
    for prev, cur in zip(trace, trace[1:]):
        if cur["n_pres"] >= DEPTH and not cur["valid"] and cur["data"] != prev["data"]:
            out.append(cur)
    return out


def fabricated(trace):
    """(d) FABRICATION: beats published before any real Symbol can have emerged.

    n_pres < DEPTH means fewer than DEPTH pipeline advances have happened, so
    data_out_o still carries the reset content transformed by the LFSR.  A beat
    published there announces a Symbol the bench never presented."""
    return [r for r in trace if r["valid"] and r["n_pres"] < DEPTH]


def summarize(dut, label, trace):
    """Print the four clause counts beside each other, every run, so a log line
    exists for each number a report will later quote (§22.67 — read the log for
    the lines the test should have printed; §22.68 — no hand-written counts)."""
    p, g, s, f = (published(trace), gap_beats(trace),
                  silent_advances(trace), fabricated(trace))
    dut._log.info(
        f"O-ALIGN[{label}]: clocks={len(trace)} presented={trace[-1]['n_pres']} "
        f"published={len(p)} real={len(advance_values(trace))} | "
        f"(a) idle_beats={len(idle_beats(trace))} of which gap={len(g)} "
        f"(b) silent_advances={len(s)} (d) fabricated={len(f)}"
    )
    return p, g, s, f
