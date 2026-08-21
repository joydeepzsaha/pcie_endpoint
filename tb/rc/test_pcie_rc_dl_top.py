"""pcie_rc_dl_top -- the RC-side TL+DLL stack, far end in Python (tests a..g).

First target in which neither side of the RC's DLLP seam is modelled: the
Transaction Layer's TLPs are framed, sequenced and LCRC'd by the real
pcie_datalink_layer, and everything the bench sees is on the PHY-facing
streams.  Design record and predictions P1..P7:
~/pcie_docs/evidence/rc-integration-top/DESIGN_RC_INTEGRATION_TOP.md SS8-9.

Observation points, per test docstring; nothing here asserts on an internal
FSM state or an intermediate value.  The FC seam aliases in the wrapper
(fc_initialized_o = the filter output u_rc.fc_initialized_i is driven by,
fc_initialized_dll = u_dl.fc_initialized_o raw) are the two wires test (a)
exists to compare.

The design's test (d)-positive -- application input reaches the data-link
output -- is subsumed by test (b), which walks the same path from the RQ AXIS
surface instead of the raw command port; recorded there, not as its own test.
"""

import zlib

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, with_timeout
from cocotb.clock import Clock
from cocotbext.axi import AxiStreamBus, AxiStreamSink, AxiStreamSource
from cocotbext.pcie.core.dllp import DllpType
from cocotbext.pcie.core.tlp import Tlp, TlpType
from cocotbext.pcie.core.utils import PcieId

from test_pcie_endpoint_top import (
    MIN_CREDIT_EP,
    PHY_USER_IS_DLLP,
    PHY_USER_IS_TLP,
    build_ack_nak,
    build_fc_dllp,
    add_sequence_and_lcrc,
    calculate_dllp_crc,
    initialize_flow_control,
    receive_dllp_type,
    send_axis,
)
from test_pcie_rq_rc_top import (
    COMPLETER,
    CPL_SC,
    Rc,
    cfg_read,
    decode_rc_desc,
    rq_desc,
    send_rq,
    settle,
    split_packet,
    tuser,
)

CLK_NS = 8

# pcie_rq_rc_pkg::rq_req_type_e (pcie_rq_rc_pkg.sv:64); the config encodings
# come in via test_pcie_rq_rc_top's cfg_read.
RQ_MEM_WRITE = 0b0001


class RcDlTB:
    """Clock, reset and the Python far end on the PHY-facing streams."""

    def __init__(self, dut):
        self.dut = dut
        cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
        self.phy_source = AxiStreamSource(
            AxiStreamBus.from_prefix(dut, "s_phy_axis"), dut.clk_i, dut.rst_i
        )
        self.phy_sink = AxiStreamSink(
            AxiStreamBus.from_prefix(dut, "m_phy_axis"), dut.clk_i, dut.rst_i
        )
        # Sequence number of the next TLP the far end transmits; the DUT's
        # receiver expects consecutive numbering from 0.
        self.tx_seq = 0

    async def reset(self):
        d = self.dut
        d.rst_i.value = 1
        d.phy_link_up_i.value = 0
        d.idle_valid_i.value = 0
        d.transmit_enable_i.value = 0
        # A Root Complex's Requester ID is its own BDF -- 00:00.0 in this
        # design's enumeration (design record SS3.4), NOT the DLL's
        # cfg_*_number_o.
        d.requester_id_i.value = 0x0000
        d.completer_id_i.value = 0x0000
        d.bus_number_i.value = 0
        d.device_number_i.value = 0
        d.function_number_i.value = 0
        d.memory_enable_i.value = 1
        d.extended_tag_enable_i.value = 0
        d.max_payload_bytes_i.value = 128
        d.max_read_bytes_i.value = 128
        d.rcb_128b_i.value = 0
        d.s_axis_rq_tdata.value = 0
        d.s_axis_rq_tkeep.value = 0
        d.s_axis_rq_tvalid.value = 0
        d.s_axis_rq_tlast.value = 0
        d.s_axis_rq_tuser.value = 0
        d.m_axis_rc_tready.value = 1
        for _ in range(8):
            await RisingEdge(d.clk_i)
        d.rst_i.value = 0
        d.phy_link_up_i.value = 1
        d.idle_valid_i.value = 1
        d.transmit_enable_i.value = 1
        for _ in range(8):
            await RisingEdge(d.clk_i)

    async def recv_tlp_frame(self):
        """Next TLP frame off m_phy_axis: (sequence, tlp_bytes, frame_bytes).

        Skips DLLP frames (always 6 bytes) and asserts the frame's LCRC
        recomputes before handing anything back.
        """
        while True:
            frame = await with_timeout(self.phy_sink.recv(), 500, "us")
            data = bytes(frame.tdata)
            if len(data) == 6:
                continue
            assert int.from_bytes(data[-4:], "little") == (
                zlib.crc32(data[:-4]) & 0xFFFFFFFF
            ), f"LCRC mismatch on emitted frame {data.hex()}"
            return int.from_bytes(data[:2], "big") & 0xFFF, data[2:-4], data

    async def ack(self, sequence):
        await send_axis(self.phy_source, build_ack_nak(DllpType.ACK, sequence),
                        PHY_USER_IS_DLLP)

    async def nak(self, sequence):
        await send_axis(self.phy_source, build_ack_nak(DllpType.NAK, sequence),
                        PHY_USER_IS_DLLP)

    async def send_tlp(self, tlp_bytes):
        frame = add_sequence_and_lcrc(self.tx_seq, tlp_bytes)
        self.tx_seq = (self.tx_seq + 1) & 0xFFF
        await send_axis(self.phy_source, frame, PHY_USER_IS_TLP)

    async def complete_read(self, req, data):
        """CplD answering a read request TLP, SC, one Dword."""
        cpl = Tlp.create_completion_data_for_tlp(req, PcieId.from_int(COMPLETER))
        cpl.byte_count = 4
        cpl.lower_address = 0
        cpl.set_data(data.to_bytes(4, "little"))
        await self.send_tlp(bytes(cpl.pack()))


class FrameCollector:
    """Collects TLP frames off m_phy_axis and Acks each one promptly.

    The prompt Ack is load-bearing for the frame-counting tests: an unAcked
    TLP is replayed after REPLAY_TIMER_CYCLES and the replay would be counted
    as a second emission.
    """

    def __init__(self, tb):
        self.tb = tb
        self.frames = []

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            frame = await self.tb.phy_sink.recv()
            data = bytes(frame.tdata)
            if len(data) == 6:
                continue
            assert int.from_bytes(data[-4:], "little") == (
                zlib.crc32(data[:-4]) & 0xFFFFFFFF
            ), f"LCRC mismatch on emitted frame {data.hex()}"
            self.frames.append(data)
            await self.tb.ack(int.from_bytes(data[:2], "big") & 0xFFF)


async def wait_frames(dut, collector, count, cycles=2000):
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        if len(collector.frames) >= count:
            return
    raise AssertionError(
        f"expected {count} TLP frames on m_phy_axis, saw {len(collector.frames)} "
        f"after {cycles} cycles -- FC credits?")


async def mem_write(dut, address, data):
    """One 1-Dword posted MemWr on the host RQ interface."""
    desc = rq_desc(RQ_MEM_WRITE, dword_count=1, address=address)
    await send_rq(dut, [
        (desc, 0xF, False, tuser(0xF, 0x0)),
        (data, 0x1, True, 0),
    ])


# ==========================================================================
# (a) FC init completes; the TL's view of fc_initialized is monotonic
# ==========================================================================
@cocotb.test()
async def fc_init_monotonic_at_the_tl(dut):
    """(a) Scores P1 and P2.  Observation points: fc_initialized_o (the filter
    output driving u_rc.fc_initialized_i) and fc_initialized_dll
    (u_dl.fc_initialized_o raw), sampled every cycle from reset to 2000 cycles
    past first assertion.

    Positive control: the TL view asserts (initialize_flow_control's bounded
    wait_high, 4000 cycles).  Negative control: the raw DLL output DOES glitch
    low at least once -- without this the test passes identically against a
    DLL that never glitched and proves nothing about the filter (P1 predicts
    one glitch of >= 4 consecutive cycles).  Assertion: the TL view, once
    high, never falls while phy_link_up_i holds (P2).
    """
    tb = RcDlTB(dut)
    await tb.reset()

    stop = [False]
    stats = {"tl_falls": 0, "dll_low_runs": [], "tl_seen": False}

    async def watch():
        tl_prev = 0
        dll_prev = 0
        dll_seen = False
        low_run = 0
        while not stop[0]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not int(dut.phy_link_up_i.value):
                continue
            dll = int(dut.fc_initialized_dll.value)
            tl = int(dut.fc_initialized_o.value)
            if tl:
                stats["tl_seen"] = True
            if tl_prev and not tl:
                stats["tl_falls"] += 1
            if dll_seen:
                if not dll:
                    low_run += 1
                elif low_run:
                    stats["dll_low_runs"].append(low_run)
                    low_run = 0
            if dll:
                dll_seen = True
            tl_prev, dll_prev = tl, dll

    cocotb.start_soon(watch())
    await initialize_flow_control(dut, tb.phy_source)
    for _ in range(2000):
        await RisingEdge(dut.clk_i)
    stop[0] = True

    assert stats["tl_seen"], "positive control: the TL view never asserted"
    assert stats["tl_falls"] == 0, (
        f"P2 FALSIFIED in-run: u_rc.fc_initialized_i fell "
        f"{stats['tl_falls']} time(s) after first assertion with the link up")
    runs = stats["dll_low_runs"]
    assert len(runs) >= 1, (
        "negative control: u_dl.fc_initialized_o never glitched low -- the "
        "filter was not exercised and this run says nothing about it")
    # P1's measured values, for the findings file: glitch count and widths.
    dut._log.info(f"P1 measurement: {len(runs)} glitch(es), widths {runs} cycles")


# ==========================================================================
# (b) One CfgRd0 end to end, generous credit
# ==========================================================================
@cocotb.test()
async def cfgrd0_end_to_end(dut):
    """(b) Scores P7's passing arm (wire order); subsumes the design's
    (d)-positive row (application input reaches the data-link output -- same
    path, RQ AXIS instead of the raw command port).

    Observation points in order: pcie_rq_tag_o/vld strobe (via Rc), the framed
    packet on m_phy_axis, the RC descriptor on m_axis_rc.  The LCRC recompute
    plus the cocotbext decode of the frame body IS the wire-order assertion:
    at PCIE_WIRE_ORDER=0 the header Dwords arrive byte-swapped and the body
    does not decode as a CfgRd0 (P7).
    """
    tb = RcDlTB(dut)
    await tb.reset()
    await initialize_flow_control(dut, tb.phy_source)
    rc = Rc(dut)
    rc.start()

    await cfg_read(dut, reg_num=0x01)
    seq, tlp_bytes, frame = await tb.recv_tlp_frame()
    assert int.from_bytes(frame[-4:], "little") == (
        zlib.crc32(frame[:-4]) & 0xFFFFFFFF), "LCRC does not recompute"

    req = Tlp.unpack(tlp_bytes)
    assert req.fmt_type == TlpType.CFG_READ_0, (
        f"frame body decodes as {req.fmt_type}, not CfgRd0 -- wire order? "
        f"(P7) raw: {tlp_bytes.hex()}")
    assert req.length == 1, f"config request length {req.length} != 1 Dword"
    assert int(req.completer_id) == COMPLETER, (
        f"BDF {int(req.completer_id):#06x} != descriptor's {COMPLETER:#06x}")
    assert req.address == 0x04, f"register address {req.address:#x} != 0x04"
    assert int(req.requester_id) == 0x0000, "Requester ID != requester_id_i"
    await tb.ack(seq)

    assert rc.tags_presented == [req.tag], (
        f"pcie_rq_tag_o strobes {[hex(t) for t in rc.tags_presented]} != the "
        f"tag in the emitted header {req.tag:#04x}")

    read_data = 0x8086100E
    await tb.complete_read(req, read_data)
    await rc.wait_packets(1, cycles=4000)

    desc, payload = split_packet(rc.packets[0])
    f = decode_rc_desc(desc)
    assert f["tag"] == req.tag, f"RC Tag {f['tag']:#04x} != {req.tag:#04x}"
    assert f["status"] == CPL_SC and f["error_code"] == 0
    assert f["dword_count"] == 1 and f["byte_count"] == 4
    assert payload == [read_data], (
        f"payload {[hex(w) for w in payload]} != [{read_data:#010x}]")

    await settle(dut)
    assert int(dut.outstanding_o.value) == 0, "the tag did not retire"
    rc.clean()


# ==========================================================================
# (c) MIN_CREDIT_EP: NPH=1 holds all but one frame off the wire
# ==========================================================================
@cocotb.test()
async def min_credit_one_frame_before_completion(dut):
    """(c) Scores P4, P5 and P6, and BOUNDS outstanding_o rather than pinning
    it.  Observation points: emitted TLP frames on m_phy_axis (counted, NOT
    tag strobes), outstanding_o, tx_fc_blocked_o, and the fc_* readback after
    init.

    The credit-side claim is P4: under the Table 2-37 Endpoint minimum
    (NPH=1), three back-to-back CfgRd0s put exactly ONE frame on the wire
    before the first completion.  That is the spec-visible statement, and it
    is asserted directly on m_phy_axis, where the spec can see it.

    outstanding_o is NOT that claim.  It counts ALLOCATED TAGS, not requests
    on the wire (SS41.4), and where the allocator sits relative to the credit
    gate is an implementation choice: today tags allocate in tlp_requester's
    REQ_TAG state, upstream of the VC-buffer release gate (tlp_layer.sv:280),
    so all three tags are held while one frame is out and the measured peak is
    3.  P3 predicted a peak of exactly 1 and is FALSIFIED by that measurement
    (scored in FINDINGS_RC_DL_TOP.md; first run's failure log:
    logs/P3_outstanding.log).  Moving the allocator below the gate would be
    correct RTL and would drive the peak to 1, so the peak is LOGGED here and
    never asserted -- an assertion on it would pin an implementation detail
    (SS22.42, SS22.46).

    What is asserted instead is a two-sided bound that holds for either
    allocator placement, plus the drain:

      * lower -- outstanding_o >= (frames emitted on m_phy_axis) - (CplDs this
        bench has issued).  A request on the wire and unanswered holds a tag
        by definition.  The counter may legitimately sit ABOVE this, which is
        exactly what tags held behind the credit gate look like.
      * upper -- outstanding_o <= (commands issued) - (RC descriptors
        delivered on m_axis_rc).  No phantom allocations: the DUT cannot hold
        more tags than requests were asked for, less those already answered
        downstream.  This is the "never increases after the third command"
        claim in a placement-insensitive form; a strict no-increase rule would
        itself pin the allocator, because an allocator below the credit gate
        necessarily allocates late and so must increase after release.
      * drain -- outstanding_o == 0 once all three CplDs are delivered and
        rc.clean() has passed: zero by retirement, not by a quarantine expiry.

    Credit return: a CplD alone returns no NP credit -- the far end frees its
    request buffer and advertises the new cumulative NPH in an UpdateFC-NP
    DLLP; that, not the completion, is what releases the next frame.

    The whole test must finish well inside CPL_TIMEOUT_CYCLES=4096 of the
    FIRST allocation: all three tags' timers run from allocation, so a slow
    test fabricates a timeout on the held requests.  rc.clean() enforces it.
    """
    tb = RcDlTB(dut)
    await tb.reset()
    await initialize_flow_control(dut, tb.phy_source, MIN_CREDIT_EP)
    # P6 readback (also asserted inside initialize_flow_control): PH/NPH are
    # the finite minima, CPLH is zero-encoded infinite.
    assert int(dut.fc_ph_o.value) == 1
    assert int(dut.fc_nph_o.value) == 1
    assert int(dut.fc_cplh_o.value) == 0

    rc = Rc(dut)
    rc.start()
    collector = FrameCollector(tb)
    collector.start()

    peak = [0]
    blocked_seen = [False]
    stop = [False]
    # Both counters are incremented BEFORE the transfer they name, so each is
    # always at least what the DUT can have acted on.  That keeps the lower
    # bound at its smallest and the upper bound at its widest, and no sample
    # can fail on scheduler ordering alone.
    commands_issued = [0]
    cpls_issued = [0]
    # Why the LOWER bound counts CplDs this bench has ISSUED rather than RC
    # descriptors delivered: the tracker clears active_r in the same cycle it
    # raises result_valid_r (tlp_request_tracker.sv:344-349), so a tag retires
    # strictly BEFORE its descriptor reaches m_axis_rc.  A lower bound counting
    # deliveries would exceed a perfectly correct outstanding_o for that
    # window, at every completion.  Deliveries drive the UPPER bound instead,
    # where the same lag is conservative.  The upper bound assumes one CplD
    # per request, which this test constructs; a split completion would emit
    # two descriptors for one still-held tag.
    violations = []

    async def watch():
        cycle = 0
        while not stop[0]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            cycle += 1
            count = int(dut.outstanding_o.value)
            peak[0] = max(peak[0], count)
            if int(dut.tx_fc_blocked_o.value):
                blocked_seen[0] = True
            unanswered = len(collector.frames) - cpls_issued[0]
            if count < unanswered:
                violations.append(
                    f"cycle {cycle}: outstanding_o={count} is below the "
                    f"{unanswered} request(s) emitted on m_phy_axis and not "
                    f"yet answered -- a request on the wire holds a tag")
            headroom = commands_issued[0] - len(rc.packets)
            if count > headroom:
                violations.append(
                    f"cycle {cycle}: outstanding_o={count} exceeds the "
                    f"{headroom} tag(s) that {commands_issued[0]} command(s) "
                    f"can account for after {len(rc.packets)} RC "
                    f"descriptor(s) -- phantom allocation")

    cocotb.start_soon(watch())

    for reg in (0x00, 0x01, 0x02):
        commands_issued[0] += 1
        await cfg_read(dut, reg_num=reg)
    await settle(dut, 300)

    assert len(collector.frames) == 1, (
        f"P4: {len(collector.frames)} frames emitted before the first "
        "completion; NPH=1 permits exactly one")
    assert len(rc.tags_presented) == 3, (
        f"P5: {len(rc.tags_presented)} tag strobes for three commands -- tags "
        "allocate upstream of the credit gate, so three are expected")
    assert blocked_seen[0] and int(dut.tx_fc_blocked_o.value) == 1, (
        "tx_fc_blocked_o must be high while the second request is held")
    assert violations == [], (
        "outstanding_o left its bounds before the first completion:\n  " +
        "\n  ".join(violations))
    # P3's measured value, LOGGED not asserted -- see the docstring.
    dut._log.info(f"P3 measurement: outstanding_o peak = {peak[0]}")

    # Answer request 1; return one more cumulative NPH credit; frame 2 follows.
    expected = {0: 0x00, 1: 0x04, 2: 0x08}
    data = {0: 0xC0FFEE00, 1: 0xC0FFEE01, 2: 0xC0FFEE02}
    for index in range(3):
        req = Tlp.unpack(collector.frames[index][2:-4])
        assert req.fmt_type == TlpType.CFG_READ_0
        assert req.address == expected[index], (
            f"frame {index} reads register {req.address:#x}, expected "
            f"{expected[index]:#x} -- emission order broke")
        cpls_issued[0] += 1
        await tb.complete_read(req, data[index])
        if index < 2:
            await send_axis(
                tb.phy_source,
                build_fc_dllp(DllpType.UPDATE_FC_NP,
                              hdr_fc=2 + index, data_fc=1),
                PHY_USER_IS_DLLP,
            )
            await wait_frames(dut, collector, index + 2)

    await rc.wait_packets(3, cycles=4000)
    delivered = [decode_rc_desc(split_packet(p)[0])["tag"] for p in rc.packets]
    assert sorted(delivered) == sorted(rc.tags_presented), (
        f"RC descriptors carry tags {delivered}, strobes said "
        f"{rc.tags_presented}")
    await settle(dut)
    stop[0] = True
    assert violations == [], (
        "outstanding_o left its bounds during the drain:\n  " +
        "\n  ".join(violations))
    rc.clean()
    # clean() first: it rules out a completion timeout, so a zero here is zero
    # by retirement and not by a quarantine expiry releasing a held tag.
    assert int(dut.outstanding_o.value) == 0, (
        "outstanding_o did not drain to 0 after all three CplDs were "
        "delivered -- not every tag retired")


# ==========================================================================
# (e) NAK -> replay, byte-identical
# ==========================================================================
@cocotb.test()
async def nak_replays_byte_identical_frame(dut):
    """(e) Observation point: m_phy_axis.  A NAK for the frame before this one
    makes the DLL replay it; the replayed frame -- sequence number, TLP body
    and LCRC -- must be byte-identical to the original.  Ported from the
    endpoint's data_link_nak_replays_transaction_layer_packet; replay is a
    DLL property and layer-agnostic.
    """
    tb = RcDlTB(dut)
    await tb.reset()
    await initialize_flow_control(dut, tb.phy_source)
    rc = Rc(dut)
    rc.start()

    await cfg_read(dut, reg_num=0x02)
    seq, tlp_bytes, frame = await tb.recv_tlp_frame()

    await tb.nak((seq - 1) & 0xFFF)
    _, _, replay = await tb.recv_tlp_frame()
    assert replay == frame, (
        f"replayed frame differs from the original:\n  first  {frame.hex()}\n"
        f"  replay {replay.hex()}")
    await tb.ack(seq)

    req = Tlp.unpack(tlp_bytes)
    await tb.complete_read(req, 0x5EED0002)
    await rc.wait_packets(1, cycles=4000)
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0
    rc.clean()


# ==========================================================================
# (f) corrupted RX -> NAK; nothing reaches the RC surface
# ==========================================================================
@cocotb.test()
async def corrupted_rx_nakked_and_no_rc_descriptor(dut):
    """(f) Observation points: the NAK DLLP on m_phy_axis, m_axis_rc, and
    rc_unexpected_completion_o.  Adapted from the endpoint's
    corrupted_link_input_is_rejected_with_nak: the "never reaches the target"
    half becomes "no RC descriptor and no unexpected-completion strobe",
    because the completer surface is tied off.  Recovery: the far end
    retransmits the same sequence with a good LCRC and the completion then
    lands normally.
    """
    tb = RcDlTB(dut)
    await tb.reset()
    await initialize_flow_control(dut, tb.phy_source)
    rc = Rc(dut)
    rc.start()

    await cfg_read(dut, reg_num=0x03)
    seq, tlp_bytes, _ = await tb.recv_tlp_frame()
    await tb.ack(seq)
    req = Tlp.unpack(tlp_bytes)

    cpl = Tlp.create_completion_data_for_tlp(req, PcieId.from_int(COMPLETER))
    cpl.byte_count = 4
    cpl.lower_address = 0
    cpl.set_data((0xA5A5A5A5).to_bytes(4, "little"))
    cpl_bytes = bytes(cpl.pack())

    corrupt = bytearray(add_sequence_and_lcrc(tb.tx_seq, cpl_bytes))
    corrupt[-1] ^= 1
    await send_axis(tb.phy_source, bytes(corrupt), PHY_USER_IS_TLP)

    nak = await receive_dllp_type(tb.phy_sink, DllpType.NAK)
    assert nak.seq == 0xFFF, (
        f"NAK carries {nak.seq:#05x}; nothing was received yet, so the "
        "last-good sequence is 0xFFF")
    for _ in range(32):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        assert not int(dut.m_axis_rc_tvalid.value), \
            "a corrupted completion produced an RC descriptor"
        assert not int(dut.rc_unexpected_completion_o.value), \
            "a corrupted completion strobed rc_unexpected_completion_o"
    assert rc.packets == [] and rc.unexpected == []

    # Far-end retransmit, same sequence, good LCRC.
    await tb.send_tlp(cpl_bytes)
    await rc.wait_packets(1, cycles=4000)
    f = decode_rc_desc(split_packet(rc.packets[0])[0])
    assert f["tag"] == req.tag and f["status"] == CPL_SC
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0
    rc.clean()


# ==========================================================================
# (g) posted PH exhaustion blocks; UpdateFC-P releases
# ==========================================================================
@cocotb.test()
async def posted_ph_exhaustion_blocks_until_updatefc(dut):
    """(g) Observation points: m_phy_axis frame count and tx_fc_blocked_o.
    Under MIN_CREDIT_EP (PH=1), the first 1-Dword MemWr consumes the posted
    header pool; the second is held with tx_fc_blocked_o high and no second
    frame, until an UpdateFC-P advertises one more cumulative PH credit.
    Posted requests hold no tag, so no pcie_rq_tag_o strobe fires.  Ported
    from the endpoint's flow_control_blocks_and_releases_mid_layer, folded
    onto the PH pool per the design's (d) table.
    """
    tb = RcDlTB(dut)
    await tb.reset()
    await initialize_flow_control(dut, tb.phy_source, MIN_CREDIT_EP)
    rc = Rc(dut)
    rc.start()
    collector = FrameCollector(tb)
    collector.start()

    await mem_write(dut, 0x1000, 0xA5A50001)
    await wait_frames(dut, collector, 1)
    first = Tlp.unpack(collector.frames[0][2:-4])
    assert first.fmt_type == TlpType.MEM_WRITE
    assert first.address == 0x1000
    assert bytes(first.data) == (0xA5A50001).to_bytes(4, "little")

    await mem_write(dut, 0x2000, 0xA5A50002)
    await settle(dut, 200)
    assert len(collector.frames) == 1, (
        f"{len(collector.frames)} frames with PH exhausted -- the second "
        "MemWr must be held")
    await ReadOnly()
    assert int(dut.tx_fc_blocked_o.value) == 1, \
        "tx_fc_blocked_o low while a posted write is held for credit"

    await send_axis(
        tb.phy_source,
        build_fc_dllp(DllpType.UPDATE_FC_P, hdr_fc=2, data_fc=16),
        PHY_USER_IS_DLLP,
    )
    await wait_frames(dut, collector, 2)
    second = Tlp.unpack(collector.frames[1][2:-4])
    assert second.fmt_type == TlpType.MEM_WRITE
    assert second.address == 0x2000
    assert bytes(second.data) == (0xA5A50002).to_bytes(4, "little")

    assert rc.tags_presented == [], "a posted write must not allocate a tag"
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0
    rc.clean()
