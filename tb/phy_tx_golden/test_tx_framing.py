"""Rung 9 -- spec-golden framing bench for frame_symbols (Gen1).

Toplevel: frame_symbols standalone, USER_WIDTH=5 -- the width phy_transmit
actually instantiates it with (phy_transmit.sv:12,130).  frame_symbols is the
one module of the transmit closure that had NO bench of its own: Rung 5's trace
found it constant-safe for the K path and stopped there, so its framing
behaviour has never been asserted against the spec.

THE ORACLE (O-11 / O-12, evidence/rung9/ORACLES_PHY_TX.md)
    Base 2.1 sec 4.2.2 p.194:

        "The Framing mechanism uses Special Symbol K28.2 'SDP' to start a DLLP
         and Special Symbol K27.7 'STP' to start a TLP.  The Special Symbol
         K29.7 'END' is used to mark the end of either a TLP or a DLLP."

        "TLPs must be framed by placing an STP Symbol at the start of the TLP
         and an END Symbol or EDB Symbol at the end of the TLP ...  DLLPs must
         be framed by placing an SDP Symbol at the start of the DLLP and an END
         Symbol at the end of the DLLP."

    STP = FBh, SDP = 5Ch, ENDP = FDh (pcie_phy_pkg.sv:102-104).  All three are
    K codes, so sec 4.2.3 p.199 requires them un-scrambled and K-marked.

    "placed" is defined by the spec itself, one line above the rules: "a
    requirement on the Transmitter to put the Symbol into the proper Lane of a
    Link."  A framing symbol that reaches the wire but is not marked as a
    control code has not been placed -- it decodes as ordinary data.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# ---- pcie_phy_pkg.sv:102-104 ----
STP = 0xFB          # K27.7, starts a TLP
SDP = 0x5C          # K28.2, starts a DLLP
ENDP = 0xFD         # K29.7, ends either
GEN1 = 0x01         # rate_speed_e.gen1

PAYLOAD = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]


def word(bs):
    v = 0
    for i, b in enumerate(bs):
        v |= (b & 0xFF) << (8 * i)
    return v


async def reset(dut):
    dut.rst_i.value = 1
    dut.curr_data_rate_i.value = GEN1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


async def send_packet(dut, payload, is_dllp, collect_cycles=40):
    """Push `payload` (a multiple of 4 bytes) in and collect the framed output.

    Returns the output as a flat list of (symbol, is_k) plus the per-beat
    tlast flags, so the framing tests and the tlast test read the same capture.
    """
    beats = [payload[i:i + 4] for i in range(0, len(payload), 4)]
    out_syms, out_last = [], []

    async def sink():
        for _ in range(collect_cycles):
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.m_axis_tvalid.value) & 1 and int(dut.m_axis_tready.value) & 1:
                data = int(dut.m_axis_tdata.value)
                keep = int(dut.m_axis_tkeep.value)
                user = int(dut.m_axis_tuser.value)
                last = int(dut.m_axis_tlast.value) & 1
                n = 0
                for b in range(4):
                    if (keep >> b) & 1:
                        out_syms.append(((data >> (8 * b)) & 0xFF, (user >> b) & 1))
                        n += 1
                out_last.append((last, n))

    task = cocotb.start_soon(sink())

    dut.m_axis_tready.value = 1
    for n, beat in enumerate(beats):
        dut.s_axis_tdata.value = word(beat)
        dut.s_axis_tkeep.value = 0xF
        dut.s_axis_tvalid.value = 1
        dut.s_axis_tlast.value = 1 if n == len(beats) - 1 else 0
        dut.s_axis_tuser.value = 1 if is_dllp else 0
        # hold until accepted
        for _ in range(40):
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.s_axis_tready.value) & 1:
                break
        else:
            raise AssertionError("frame_symbols never asserted s_axis_tready on beat %d" % n)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    await task
    return out_syms, out_last


def fmt(pairs):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k in pairs)


def check_framing(dut, label, syms, start_sym, payload):
    """Base 2.1 sec 4.2.2 p.194: <start> <payload...> END, start and END both
    K-marked, payload passed through in order and NOT K-marked."""
    bad = []
    want = [(start_sym, 1)] + [(b, 0) for b in payload] + [(ENDP, 1)]
    dut._log.info("%-5s got : %s" % (label, fmt(syms)))
    dut._log.info("%-5s want: %s" % ("", fmt(want)))
    if len(syms) < len(want):
        return ["only %d Symbols came out; the frame needs %d"
                % (len(syms), len(want))]
    for i, ((gs, gk), (ws, wk)) in enumerate(zip(syms, want)):
        role = ("start" if i == 0 else "END" if i == len(want) - 1
                else "payload[%d]" % (i - 1))
        if gs != ws:
            bad.append("%s: got 0x%02x, sec 4.2.2 p.194 wants 0x%02x" % (role, gs, ws))
        if gk != wk:
            bad.append("%s: K=%d, wants K=%d (sec 4.2.3 p.199)" % (role, gk, wk))
    return bad


# ------------------------------------------------------------------ O-12

@cocotb.test()
async def dllp_is_framed_by_sdp_and_end(dut):
    """O-12: "DLLPs must be framed by placing an SDP Symbol at the start of the
    DLLP and an END Symbol at the end of the DLLP." -- Base 2.1 sec 4.2.2 p.194.

    An 8-byte DLLP goes in; SDP (K28.2 = 5Ch, K-marked), the eight payload bytes
    in order un-marked, then END (K29.7 = FDh, K-marked) must come out.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    syms, _ = await send_packet(dut, PAYLOAD, is_dllp=True)
    bad = check_framing(dut, "DLLP", syms, SDP, PAYLOAD)
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "DLLP framing diverges from sec 4.2.2 p.194 in %d places" % len(bad)


# ------------------------------------------------------------------ O-11

@cocotb.test()
async def tlp_is_framed_by_stp_and_end(dut):
    """O-11: "TLPs must be framed by placing an STP Symbol at the start of the
    TLP and an END Symbol or EDB Symbol at the end of the TLP." -- sec 4.2.2
    p.194.  Same payload as the DLLP case, so the only difference in the
    expected output is the start symbol: STP (K27.7 = FBh) instead of SDP.

    Driving both with identical payload is deliberate.  frame_symbols picks the
    start symbol from a single ternary on s_axis_tuser[0] (frame_symbols.sv:147);
    two runs that differ ONLY in that bit are the minimum stimulus that shows
    the ternary is live in both directions rather than constant.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    syms, _ = await send_packet(dut, PAYLOAD, is_dllp=False)
    bad = check_framing(dut, "TLP", syms, STP, PAYLOAD)
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "TLP framing diverges from sec 4.2.2 p.194 in %d places" % len(bad)


# ------------------------------------------------- O-11/O-12, the tlast half

@cocotb.test()
async def the_beat_carrying_end_asserts_tlast(dut):
    """The frame boundary reaches the AXI-Stream port.  CLOSED -- tracker sec 54 #10.

    frame_symbols' output is an AXI4-Stream, and tlast is how the end of the
    frame is carried to everything downstream: dllp_axis_async_fifo_inst is
    instantiated LAST_ENABLE=1 (phy_transmit.sv:382), and lane_management leaves
    ST_LANE_MNGT_TX_DATA only on `if (s_dllp_axis_tlast)` (lane_management.sv:382).
    A frame whose final beat never asserts tlast is a frame that never ends.

    WAS a PREDICTED DIVERGENCE (Rung 9, PREDICTIONS_R9.md sec 3) and carried
    expect_fail until FA-5.  frame_symbols.sv:175-194 handles the tail by
    looking at s_axis_tkeep:

        4'b0001 -> ENDP placed, phy_axis_tlast = '1     (:183)
        4'b0011 -> ENDP placed, phy_axis_tlast = '1     (:188)
        default -> next_state = ST_FRAME_LAST           (:192)

    and ST_FRAME_LAST emitted the final beat with the END Symbol while never
    assigning phy_axis_tlast.  FA-5 added the assignment there.

    ⚠️ Rung 9's docstring said frame_symbols "never asserts tlast"; that was
    wrong and the correction is why the fix is one line.  It asserts at :183,
    :188, :205 and :304 -- only ST_FRAME_LAST omitted it.  ⚠️ And :177's
    commented-out `// phy_axis_tlast = '1;` is NOT the repair it looks like:
    asserting there marks the SHIFTED beat last while ST_FRAME_LAST still owes
    one more, truncating the frame and stranding END.

    The `default` arm is not a corner: it is taken whenever the last input beat
    has tkeep 4'b0111 or 4'b1111, i.e. for EVERY word-aligned packet -- the
    ordinary case.  This test drives an 8-byte DLLP, tkeep=4'b1111 on the final
    beat, and asserts that the beat carrying END sets tlast.

    Measured across the fix, same stimulus, same 10 Symbols out
    (5cK 11 22 33 44 55 66 77 88 fdK):
        before  per-beat (tlast, symbols) = [(0, 4), (0, 4), (0, 2)]
        after   per-beat (tlast, symbols) = [(0, 4), (0, 4), (1, 2)]
    Only the boundary marker moved; the data path is byte-identical.

    ⚠️ This row does NOT prove the lane_management hang is gone -- nothing in
    this closure drives a DLLP through lane_management.  It proves the frame
    now ends.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    syms, per_beat_last = await send_packet(dut, PAYLOAD, is_dllp=True)

    dut._log.info("output Symbols: %s" % fmt(syms))
    dut._log.info("per-beat (tlast, symbols): %s" % per_beat_last)
    assert syms and syms[-1] == (ENDP, 1), \
        "the frame did not end with a K-marked END; got %s" % fmt(syms[-3:])

    # Walk beats accumulating symbol counts to find the beat carrying the last
    # Symbol, then read that beat's tlast.
    total = sum(n for _, n in per_beat_last)
    assert total == len(syms), "beat accounting mismatch: %d vs %d" % (total, len(syms))
    last_beat_tlast = per_beat_last[-1][0]
    any_tlast = any(l for l, _ in per_beat_last)

    dut._log.info("beat carrying END: tlast=%d   any tlast in the frame: %d"
                  % (last_beat_tlast, any_tlast))
    assert last_beat_tlast == 1, \
        "the beat carrying END has tlast=0 -- frame_symbols.sv:262-281 " \
        "(ST_FRAME_LAST) never assigns phy_axis_tlast, so a word-aligned packet " \
        "tail produces an AXI-Stream frame with no end. lane_management.sv:382 " \
        "waits on that bit."
