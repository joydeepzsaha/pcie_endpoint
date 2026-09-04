"""T4 / T5 -- spec-golden bench for the whole phy_receive closure.

Toplevel: phy_receive.  The same file serves two targets:

  verilate_rx_closure      MAX_NUM_LANES = 1
  verilate_rx_closure_x3   MAX_NUM_LANES = 3   (non-power-of-two geometry)

Only Lane 0 is driven in either case (num_active_lanes_i = 1), so every
assertion reads bit 0 of the per-lane outputs and the pair differ only in the
width of the buses around them.  Brief sec 2's geometry rule asks a
depth-parameterized structure to be re-run at a non-power-of-two size; the
closure has no elastic buffer to vary (CLOSURE_PHY_RX.md sec 4.2 -- both FIFO
instantiations are commented out at phy_receive.sv:229-245 and :249-261), so the
rule is discharged against the lane count instead.

This exercises the real receive chain end to end:
    scrambler -> ordered_set_handler       (per lane)
    block_alignment -> pack_data -> data_handler -> axis_register
                                                 -> axis_async_fifo

Stimulus is PIPE-level Symbols; expected values come from rx_golden, which is
built from Base 2.1 Appendix C.1 and anchored to the tables at p.700.  Nothing is
captured from the DUT.

Oracles: as ORACLES_PHY_RX.md, plus D1/D2 (framing, sec 4.2.2 p.195) for the
AXIS path.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, Timer

from rx_golden import (COM, SDP, STP, END, IDL, TS1_ID, TS2_ID, TS1_ID_INV,
                       GEN1, Descrambler, ts_ordered_set, eios, fmt)

PIPE_WIDTH = 8          # Gen1: one Symbol per clock on each Lane
OBSERVE = 40            # clocks to watch after the stream for the validity pulses


async def setup(dut):
    """Two clock domains: pipe_rx_usr_clk_i carries the whole receive chain,
    clk_i is only the read side of the output axis_async_fifo
    (phy_receive.sv:305 vs :318)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.en_i.value = 0
    dut.link_up_i.value = 0
    dut.pipe_data_i.value = 0
    dut.pipe_data_valid_i.value = 0
    dut.pipe_data_k_i.value = 0
    dut.pipe_sync_header_i.value = 0
    dut.pipe_block_start_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    dut.num_active_lanes_i.value = 1
    dut.curr_data_rate_i.value = GEN1
    dut.m_dllp_axis_tready.value = 1
    await ClockCycles(dut.pipe_rx_usr_clk_i, 10)
    dut.rst_i.value = 0
    dut.en_i.value = 1
    dut.link_up_i.value = 1
    await ClockCycles(dut.pipe_rx_usr_clk_i, 6)


def _lane0(sig):
    return int(sig.value) & 1


IDLE_TAIL = 32          # Logical Idle Symbols appended after every Ordered Set


def with_idle_tail(os_syms, in_ts, n=IDLE_TAIL):
    """Append Logical Idle to an Ordered Set to make a realistic wire stream.

    Base 2.1 sec 4.2.2 p.195: "When the Transmitter is in Logical Idle, the Idle
    data Symbol (00h) shall be transmitted on all Lanes.  This is scrambled
    according to the rules in Section 4.2.3."  A real link never stops driving
    Symbols between Ordered Sets, and the closure needs that: the descrambler is
    a four-stage pipeline (gen1_scramble.sv:19, NumPipelines=4) whose valid chain
    stalls when the input goes idle (:99 vs :105-119), so an Ordered Set driven
    with nothing behind it leaves its last four Symbols stuck in flight and never
    reaches ordered_set_handler at all.

    in_ts -- True if the Ordered Set is a Training Sequence, whose D Symbols are
             not scrambled (sec 4.2.3 p.199, sec 4.2.4.1 p.201).

    Returns the (byte, is_k) stream to drive.
    """
    tx = Descrambler()
    out = []
    for i, (b, k) in enumerate(os_syms):
        tx.symbol(b, k, in_ts and i > 0)      # Symbol 0 is the COM itself
        out.append((b, k))
    out += [(tx.symbol(0x00, is_k=False), 0) for _ in range(n)]
    return out


async def drive_lane0(dut, syms, observe=OBSERVE):
    """Drive a Symbol stream on Lane 0 and collect what the closure reports.

    Returns the OR of each per-lane validity output over the whole window, the
    number of sampled clocks, and every AXIS beat seen on the DLLP master port.
    """
    seen = {k: 0 for k in ("ts1", "ts2", "idle", "pol")}
    beats = []
    samples = 0

    async def sample():
        nonlocal samples
        await Timer(1, units="ps")      # post-edge; a bare read is pre-edge
        seen["ts1"] |= _lane0(dut.ts1_valid_o)
        seen["ts2"] |= _lane0(dut.ts2_valid_o)
        seen["idle"] |= _lane0(dut.idle_valid_o)
        seen["pol"] |= _lane0(dut.polarity_inverted_o)
        samples += 1

    async def axis_monitor():
        while True:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.m_dllp_axis_tvalid.value) & 1:
                beats.append((int(dut.m_dllp_axis_tdata.value) & 0xFFFFFFFF,
                              int(dut.m_dllp_axis_tkeep.value) & 0xF,
                              int(dut.m_dllp_axis_tlast.value) & 1))

    mon = cocotb.start_soon(axis_monitor())

    for b, k in syms:
        dut.pipe_data_i.value = b & 0xFF          # Lane 0 occupies the low byte
        dut.pipe_data_k_i.value = k & 0x1         # and data_k bit 0
        dut.pipe_data_valid_i.value = 1
        await RisingEdge(dut.pipe_rx_usr_clk_i)
        await sample()

    dut.pipe_data_valid_i.value = 0
    dut.pipe_data_i.value = 0
    dut.pipe_data_k_i.value = 0
    for _ in range(observe):
        await RisingEdge(dut.pipe_rx_usr_clk_i)
        await sample()

    mon.kill()
    seen["_samples"] = samples
    seen["_beats"] = beats
    return seen


def _report(dut, label, syms, seen):
    dut._log.info(
        "%s\n  stream : %s\n  flags  : ts1=%d ts2=%d idle=%d pol=%d"
        " over %d sampled clocks, %d AXIS beats"
        % (label, fmt(syms), seen["ts1"], seen["ts2"], seen["idle"], seen["pol"],
           seen["_samples"], len(seen["_beats"])))
    assert seen["_samples"] >= len(syms), \
        "sampling loop did not run: %d samples for %d Symbols" % (
            seen["_samples"], len(syms))


# ------------------------------------------------------------ recognition

@cocotb.test()
async def ts1_reaches_the_top(dut):
    """C1 + B2 through the full closure: a spec-legal TS1 (Table 4-2 pp.201-203)
    driven as PIPE Symbols must raise ts1_valid_o[0].

    This also proves the descrambler leaves a Training Sequence intact end to
    end (A6, sec 4.2.4.1 p.201): if the TS body were XORed on the way through,
    the identifier Symbols would never match.
    """
    await setup(dut)
    syms = with_idle_tail(ts_ordered_set(TS1_ID, link=0x05, lane=0x00), in_ts=True)
    seen = await drive_lane0(dut, syms, observe=60)
    _report(dut, "TS1 through the closure", syms, seen)
    assert seen["ts1"] == 1, "a spec-legal TS1 did not reach ts1_valid_o"
    assert seen["ts2"] == 0, "the same Ordered Set was also reported as a TS2"
    assert seen["pol"] == 0, "a non-inverted TS1 reported polarity inversion"


@cocotb.test()
async def ts2_reaches_the_top(dut):
    """C2 + B2 through the full closure: Symbols 6-15 = D5.2 (Table 4-3 p.205)."""
    await setup(dut)
    syms = with_idle_tail(ts_ordered_set(TS2_ID, link=0x05, lane=0x00), in_ts=True)
    seen = await drive_lane0(dut, syms, observe=60)
    _report(dut, "TS2 through the closure", syms, seen)
    assert seen["ts2"] == 1, "a spec-legal TS2 did not reach ts2_valid_o"
    assert seen["ts1"] == 0, "the same Ordered Set was also reported as a TS1"


@cocotb.test()
async def inverted_ts1_reaches_the_top(dut):
    """B3 + C3 through the closure: sec 4.2.4.4 p.208 makes polarity-inversion
    detection mandatory on every Receiver, per Lane independently.  An inverted
    TS1 arrives with D21.5 = B5h in Symbols 6-15."""
    await setup(dut)
    syms = with_idle_tail(ts_ordered_set(TS1_ID_INV, link=0x05, lane=0x00), in_ts=True)
    seen = await drive_lane0(dut, syms, observe=60)
    _report(dut, "inverted TS1 through the closure", syms, seen)
    assert seen["pol"] == 1, "polarity inversion was not reported at the top"


@cocotb.test()
async def eios_reaches_the_top(dut):
    """C4 through the closure: COM + three IDL (Table 4-4 p.205) must raise
    idle_valid_o -- this is how the link partner announces Electrical Idle."""
    await setup(dut)
    syms = with_idle_tail(eios(), in_ts=False)
    seen = await drive_lane0(dut, syms, observe=60)
    _report(dut, "EIOS through the closure", syms, seen)
    assert seen["idle"] == 1, "a spec-legal EIOS did not reach idle_valid_o"


@cocotb.test()
async def corrupt_ts1_must_not_reach_the_ltssm(dut):
    """C1 at integration level -- the consequence of the unit defect.

    verilate_rx_os.ts1_corrupt_in_symbols_10_to_15_is_rejected shows
    ordered_set_handler.sv:380 checking only Symbols 6-9.  This test shows the
    same corrupt Ordered Set travelling the whole receive chain and arriving at
    ts1_valid_o, which is the port the LTSSM counts training sequences on
    (pcie_phy_top.sv wires it straight through).  A defect that stops at a
    module boundary is a code-quality item; one that reaches the top port is a
    conformance defect, and this is the latter.

    PREDICTED DIVERGENCE (PREDICTIONS_PHY_RX.md sec 2, T3).
    
    ⚠️ FLIPPED by the §54 #6 + #6b bundle -- AND THE REASON MATTERS.

    A first attempt at §54 #6 widened the check ALONE.  This row went green then
    too, and it was a FALSE POSITIVE: with the capture register still missing
    Symbols 14-15 the DUT rejected EVERY Training Sequence, so "the corrupt one
    is rejected" passed for a reason that had nothing to do with corruption.  A
    negative assertion cannot distinguish "rejects the bad one" from "rejects
    everything".

    What discriminates is the company it keeps: this row is green in the SAME
    RUN as ts1_reaches_the_top, ts2_reaches_the_top and
    inverted_ts1_reaches_the_top.  Under the failed attempt all three of those
    FAILED.  Do not read this row's verdict without them.
    """
    await setup(dut)
    tail = [TS1_ID] * 4 + [0x00] * 6
    syms = with_idle_tail(
        ts_ordered_set(TS1_ID, link=0x05, lane=0x00, tail=tail), in_ts=True)
    seen = await drive_lane0(dut, syms, observe=60)
    _report(dut, "corrupt TS1 through the closure", syms, seen)
    assert seen["ts1"] == 0, \
        "Table 4-2 p.203 requires Symbols 6-15; a set corrupt in 10-15 was " \
        "reported as a valid TS1 at the closure's top-level port"


# ------------------------------------------------------------ framing path

@cocotb.test()
async def dllp_frame_reaches_the_axis_port(dut):
    """D2, sec 4.2.2 p.195: "DLLPs must be framed by placing an SDP Symbol at the
    start of the DLLP and an END Symbol at the end."  A framed DLLP arriving on
    the PIPE interface must emerge on the m_dllp_axis_* master port -- that port
    is the closure's entire reason for existing.

    The payload is scrambled on the wire, as sec 4.2.3 p.199 requires for D
    characters, and is expected to arrive descrambled.  The TS1 Ordered Set in
    front of it re-seeds the LFSR (A3) and gives pack_data a 4-Symbol-aligned
    starting point.
    """
    await setup(dut)
    ts = ts_ordered_set(TS1_ID, link=0x05, lane=0x00)
    prefix = [(ts[0][0], ts[0][1], False)] + [(b, k, True) for b, k in ts[1:]]

    payload = [0xDE, 0xAD, 0xBE, 0xEF, 0x12, 0x34]
    tx = Descrambler()
    for b, k, t in prefix:
        tx.symbol(b, k, t)
    on_wire = [(tx.symbol(SDP, is_k=True), 1)]
    on_wire += [(tx.symbol(p, is_k=False), 0) for p in payload]
    on_wire += [(tx.symbol(END, is_k=True), 1)]

    syms = [(b, k) for b, k, _ in prefix] + on_wire
    syms += [(tx.symbol(0x00, is_k=False), 0) for _ in range(24)]  # logical idle
    seen = await drive_lane0(dut, syms, observe=80)
    _report(dut, "SDP-framed DLLP through the closure", syms, seen)
    beats = seen["_beats"]
    dut._log.info("AXIS beats: %s"
                  % " ".join("%08x/k%x%s" % (d, k, "/LAST" if l else "")
                             for d, k, l in beats))
    assert beats, ("a framed DLLP (SDP + 6 bytes + END, sec 4.2.2 p.195) "
                   "produced no beat on m_dllp_axis_*")

    # The payload must arrive DESCRAMBLED and in order.  Both expectations are
    # computed from what was sent, never from what was seen: sec 4.2.3 p.199
    # scrambles D characters on the wire and the receiver must undo exactly that.
    want0 = (payload[0] | payload[1] << 8 | payload[2] << 16 | payload[3] << 24)
    assert beats[0][0] == want0, (
        "first DLLP beat: got %08x want %08x (payload %s)"
        % (beats[0][0], want0, " ".join("%02x" % p for p in payload)))
    assert len(beats) >= 2, "a 6-byte DLLP payload needs two 32-bit beats"
    want1_lo = payload[4] | payload[5] << 8
    assert (beats[1][0] & 0xFFFF) == want1_lo, (
        "second DLLP beat, low half: got %04x want %04x"
        % (beats[1][0] & 0xFFFF, want1_lo))
    assert beats[-1][2] == 1, "the last DLLP beat must assert tlast"
    # Not asserted, but recorded: tkeep on the final beat is 0xF even though only
    # two payload bytes remain (data_handler.sv:247).  That is an AXIS-convention
    # question, not a Base 2.1 claim, so it is a finding rather than a check.
    dut._log.info("final-beat tkeep = 0x%x (2 payload bytes remain)" % beats[-1][1])
