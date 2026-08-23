"""pcie_enum_dl_top -- a whole bus enumeration through the REAL data link layer.

The first target in which NO PYTHON SITS BETWEEN THE ENUMERATOR AND THE WIRE.
pcie_enum_top issues the configuration requests; pcie_rc_dl_top frames them,
numbers them and LCRCs them; the credit that gates them came from a real InitFC
exchange rather than a bench assignment.  The Python that remains is the far
end -- the device being enumerated -- which is where a model belongs.

Everything is observed on m_phy_axis / s_phy_axis and the top's own status
ports.  The only exceptions are the verification-only aliases in the wrapper
(tb_pcie_enum_dl_top.sv), and they exist for two reasons the design names: the
FC seam is the start gate this rung deliberately does NOT close in RTL, and the
PG213 socket is internal by design so Mon needs three observation points.

Design record, predictions and the scored recon:
  ~/pcie_docs/evidence/enum-stack/DESIGN_ENUM_STACK_TOP.md
  ~/pcie_docs/evidence/enum-stack/RECON_REFRESH_588f634.md
  ~/pcie_docs/evidence/enum-stack/PREDICTIONS_ENUM_DL.md

Spec cited (read, not assumed):
  FC init completes once per link-up ... PCIe Base 2.1 SS3.3.1 p.160
  Minimum FC advertisements .......... PCIe Base 2.1 Table 2-37 p.137-138
  Configuration Request header ....... PCIe Base 2.1 SS2.2.7 p.79-80
  Completion timeout is an error ..... PCIe Base 2.1 SS2.8 p.152
  Ack/Nak and replay ................. PCIe Base 2.1 SS3.5-3.6
RTL cited:
  header Dword byte mapping .......... src/tlp/tlp_generator.sv:62-81, :124
  the conditional swap, DW1-3 only ... src/tlp/tlp_generator.sv:97-101
  3DW headers skip TX_DW3 ............ src/tlp/tlp_generator.sv:182-186
  RX is symmetric (DW0 raw) .......... src/tlp/tlp_parser.sv:56-61, :142
  the start gate that is not a port .. src/rc/pcie_rc_dl_top.sv:181
  timer runs from ALLOCATION ......... src/tlp/tlp_request_tracker.sv:39
"""

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

from cocotbext.pcie.core.dllp import DllpType
from cocotbext.pcie.core.tlp import Tlp, TlpType

from test_pcie_endpoint_top import (
    MIN_CREDIT_EP,
    PHY_USER_IS_DLLP,
    PHY_USER_IS_TLP,
    add_sequence_and_lcrc,
    build_fc_dllp,
    initialize_flow_control,
    send_axis,
)
from test_pcie_rc_dl_top import RcDlTB
from test_pcie_enum_bar_tlp import (
    BarSpaceCompleter, acceptance_device, assert_acceptance_outcome,
    assert_command_last, assert_rom_untouched, status,
)
from test_pcie_enum_bridge_tlp import DIRECT_GOLDEN_SEQUENCE, on_wire, render
from enum_tb_common import (
    CFG_BE_DWORD, CFG_REG_BAR0, CFG_REG_COMMAND_STATUS, CFG_REG_VENDOR_DEVICE,
    CMD_ENABLE_VALUE, ENUM_ERR_NONE, ENUM_ERR_TIMEOUT, RID, SCAN_BUS,
    Mon, TlpRequest,
    assert_sequence, cfg_wire_dw0, cfg_wire_dw1, cfg_wire_dw2, err_name,
    expect_count, nonempty,
)

import zlib

# A configuration request and a completion are both THREE-Dword headers.
CFG_HDR_DW = 3

# The target device's BDF, matching enum_tb_common's completer conventions.
TARGET_BDF = 0x0100


# ==========================================================================
# SS THE FRAME SHIM -- the single largest risk item in this rung
#
# ⭐ THE TRANSFORM IS NON-UNIFORM, AND IT IS HEADER-RELATIVE, NOT INDEX-RELATIVE.
#
# The TL's Dwords are not all laid out the same way on the wire, and a uniform
# byte-swap corrupts the ones that are not.  From the RTL, not from a document:
#
#   * DW0 is BUILT byte-mapped -- "byte N at dw0[8N+7:8N]", tlp_generator.sv:70,
#     the mapping every other field in that block uses -- and is emitted
#     UNSWAPPED (:124, m_axis_tdata = dw0).
#   * DW1..DW3 are FIELD-mapped (requester_id in the high bits) and ARE swapped
#     when PCIE_WIRE_ORDER=1 (:97-101), which pcie_rc_dl_top hard-wires (:197).
#   * The payload passes through formatted_data with NO swap (:141, :143).
#
# ⛔ AND DW3 IS NOT A HEADER DWORD HERE.  tlp_generator.sv:182-186:
#
#       TX_DW2: if (output_fire) begin
#         if (tlp_is_4dw(header_r.fmt))  state_r <= TX_DW3;
#         else                           state_r <= TX_PAYLOAD_START;
#
# A configuration request is a 3DW header, so TX_DW3 is NEVER ENTERED and beat
# 3 is the first PAYLOAD Dword -- little-endian.  Both source documents for this
# rung publish a table reading "DW1...DW3 big-endian" AND "payload (DW3+ of a
# 3DW header) little-endian", which cannot both hold at index 3.  The RTL
# settles it and this is what the RTL says.  Recorded in
# RECON_REFRESH_588f634.md SS2.3 before a line of this file was written.
#
# !! WHY IT MATTERS RATHER THAN BEING PEDANTRY.  0xFFFFFFFF is a FIXED POINT of
# a byte swap, and eleven of the seventeen golden rows carry it or no payload at
# all.  Getting the rule wrong therefore breaks exactly three rows -- B5
# (0x80000000 -> 0x00000080), B6 and B15 (0x00000006 -> 0x06000000) -- which
# reads precisely like a BAR-assignment FSM bug and not like a bench bug.
#
# The RX direction is symmetric and needs no second rule: tlp_parser.sv:142
# reads DW0 from raw s_axis_tdata while :165-206 read the swapped header_dw,
# and the payload memory is unswapped.  One rule, inverted.
#
# Byte order within a beat is little-endian, which is this bench family's AXIS
# convention -- test_pcie_endpoint_top.py:90, word_bytes().
# ==========================================================================
def _beat_is_big_endian(index, header_dw):
    """True iff Dword `index` is a field-mapped header Dword (hence swapped)."""
    return 1 <= index < header_dw


def dwords_from_body(body, header_dw=CFG_HDR_DW):
    """TLP body bytes off the data link layer -> the Dword list TlpRequest wants.

    `body` is what RcDlTB.recv_tlp_frame() returns: the frame with the two-byte
    sequence number and the four-byte LCRC already stripped, LCRC verified.
    """
    assert len(body) % 4 == 0, f"TLP body is not a whole number of Dwords: {len(body)}"
    return [
        int.from_bytes(
            body[n:n + 4],
            "big" if _beat_is_big_endian(n // 4, header_dw) else "little")
        for n in range(0, len(body), 4)
    ]


def body_from_dwords(words, header_dw=CFG_HDR_DW):
    """The inverse: a Dword list -> TLP body bytes for injection.

    Same rule, inverted -- see the RX symmetry note above.
    """
    return b"".join(
        int(w).to_bytes(
            4, "big" if _beat_is_big_endian(index, header_dw) else "little")
        for index, w in enumerate(words)
    )


def request_from_body(body):
    """One observed frame body as the TlpRequest the goldens are written over."""
    return TlpRequest(dwords_from_body(body))


# ==========================================================================
# SS THE SELF-TEST -- runs at import, BEFORE ANY DUT EXISTS
#
# House style: enum_tb_common._selftest_type1_one_bit:383 and
# _selftest_bridged_topology:1637.  A shim whose guard has never been seen
# firing is not known to work.
#
# ⭐ TWO INDEPENDENT DECODERS, ONE WIRE.  cocotbext.pcie's Tlp.unpack is already
# green on this exact frame body in the 46/324 gate -- test_pcie_rc_dl_top.py
# applies it at :290, :457, :518, :548, :606 and :626 -- so it is an oracle this
# rung did not write and cannot accidentally agree with.
#
# ⛔ THE PAYLOADS ARE CHOSEN TO BE DISCRIMINATING.  0xFFFFFFFF is a fixed point
# of a byte swap and proves nothing on its own.  0x80000000 and CMD_ENABLE_VALUE
# (0x00000006) are the two values that separate the correct rule from the
# published one, so they are the ones asserted.
# ==========================================================================
def _selftest_frame_shim():
    cases = [
        ("CfgRd0 vendor/device", False, CFG_REG_VENDOR_DEVICE, CFG_BE_DWORD, None),
        ("CfgWr0 BAR0 sizing (swap fixed point)", True, CFG_REG_BAR0,
         CFG_BE_DWORD, 0xFFFFFFFF),
        ("CfgWr0 BAR0 assign (DISCRIMINATING)", True, CFG_REG_BAR0,
         CFG_BE_DWORD, 0x80000000),
        ("CfgWr0 Command enable (DISCRIMINATING)", True, CFG_REG_COMMAND_STATUS,
         0b0011, CMD_ENABLE_VALUE),
    ]

    for what, write, reg, first_be, payload in cases:
        tag = 0x21
        words = [
            cfg_wire_dw0(write),
            cfg_wire_dw1(RID, tag, first_be),
            cfg_wire_dw2(SCAN_BUS, 0, 0, reg),
        ]
        if payload is not None:
            words.append(payload)

        body = body_from_dwords(words)

        # -- direction 1: our encoder vs. the independent decoder -------------
        tlp = Tlp.unpack(body)
        assert tlp.fmt_type == (TlpType.CFG_WRITE_0 if write
                                else TlpType.CFG_READ_0), (
            f"{what}: Tlp.unpack read fmt_type {tlp.fmt_type}, expected a "
            f"Cfg{'Wr' if write else 'Rd'}0 -- the DW0 rule is wrong")
        assert int(tlp.requester_id) == RID, (
            f"{what}: Requester ID {int(tlp.requester_id):#06x} != {RID:#06x} "
            "-- the DW1 rule is wrong")
        assert tlp.tag == tag, f"{what}: tag {tlp.tag:#04x} != {tag:#04x}"
        assert tlp.first_be == first_be, (
            f"{what}: first_be {tlp.first_be:#06b} != {first_be:#06b}")
        assert int(tlp.completer_id) == TARGET_BDF, (
            f"{what}: completer BDF {int(tlp.completer_id):#06x} != "
            f"{TARGET_BDF:#06x} -- the DW2 rule is wrong")
        assert tlp.address == reg * 4, (
            f"{what}: register address {tlp.address:#x} != {reg * 4:#x}")
        if payload is None:
            assert not bytes(tlp.data), f"{what}: a read carries payload"
        else:
            assert bytes(tlp.data) == payload.to_bytes(4, "little"), (
                f"{what}: Tlp.unpack sees payload {bytes(tlp.data).hex()}, "
                f"expected {payload.to_bytes(4, 'little').hex()} -- ⛔ THIS IS "
                "THE DW3 RULE.  A uniform big-endian rule for DW1..DW3 lands "
                "here and nowhere else.")

        # -- direction 2: round trip through our own pair ---------------------
        assert dwords_from_body(body) == words, (
            f"{what}: dwords_from_body(body_from_dwords(w)) != w\n"
            f"  in  {[hex(x) for x in words]}\n"
            f"  out {[hex(x) for x in dwords_from_body(body)]}")

        # -- direction 3: the field view the GOLDENS actually compare ---------
        req = request_from_body(body)
        assert on_wire(req) == (0, SCAN_BUS, write, reg, first_be, payload), (
            f"{what}: on_wire() gives {on_wire(req)}, expected "
            f"{(0, SCAN_BUS, write, reg, first_be, payload)}")

    # -- and that a full frame survives the sequence+LCRC wrapper -------------
    words = [cfg_wire_dw0(True), cfg_wire_dw1(RID, 0x05, CFG_BE_DWORD),
             cfg_wire_dw2(SCAN_BUS, 0, 0, CFG_REG_BAR0), 0x80000000]
    frame = add_sequence_and_lcrc(0x123, body_from_dwords(words))
    assert int.from_bytes(frame[:2], "big") & 0xFFF == 0x123
    assert int.from_bytes(frame[-4:], "little") == (
        zlib.crc32(frame[:-4]) & 0xFFFFFFFF), "self-test frame LCRC does not close"
    assert dwords_from_body(frame[2:-4]) == words, (
        "a framed body did not survive strip -> transform")


_selftest_frame_shim()


# ==========================================================================
# SS THE HARNESS
# ==========================================================================
class EnumDlTB(RcDlTB):
    """RcDlTB's clock, PHY streams and DLL helpers, plus the enum surface.

    Everything DUT-facing that already existed is inherited unchanged:
    recv_tlp_frame() (skips DLLP frames, verifies LCRC), ack(), nak() and
    send_tlp() (adds sequence + LCRC).  Only reset() is overridden, because
    this top's surface is not pcie_rc_dl_top's: the PG213 RQ/RC socket is gone
    (it is the internal seam) and the enumeration control ports are new.
    """

    async def reset(self, scan_bus=SCAN_BUS, bar_enable=1, bridge_enable=0):
        d = self.dut
        d.rst_i.value = 1
        d.phy_link_up_i.value = 0
        d.idle_valid_i.value = 0
        d.transmit_enable_i.value = 0

        # A Root Complex's Requester ID is its own BDF and stays a top-level
        # input; enum's bus assignment does NOT feed back here
        # (pcie_rc_dl_top.sv:17-20).  RID is what enum_tb_common's completer
        # addresses its completions to, so the two must agree or every
        # completion would be classified unexpected.
        d.requester_id_i.value = RID
        d.completer_id_i.value = 0x0000
        d.bus_number_i.value = 0
        d.device_number_i.value = 0
        d.function_number_i.value = 0
        d.memory_enable_i.value = 1
        d.extended_tag_enable_i.value = 0
        d.max_payload_bytes_i.value = 128
        d.max_read_bytes_i.value = 128
        d.rcb_128b_i.value = 0

        # Enumeration control.  scan_start_i is a LEVEL-triggered pulse the
        # integrator sequences -- this module does not gate it, and the reason
        # is the whole subject of the start-gate negative control.
        d.scan_start_i.value = 0
        d.scan_bus_i.value = scan_bus
        d.bar_enable_i.value = bar_enable
        d.bridge_enable_i.value = bridge_enable

        for _ in range(8):
            await RisingEdge(d.clk_i)
        d.rst_i.value = 0
        d.phy_link_up_i.value = 1
        d.idle_valid_i.value = 1
        d.transmit_enable_i.value = 1
        for _ in range(8):
            await RisingEdge(d.clk_i)

    async def start_enum(self):
        """One scan_start_i pulse.  Callers gate this themselves -- see
        wait_fc_init() -- because the RTL does not."""
        self.dut.scan_start_i.value = 1
        await RisingEdge(self.dut.clk_i)
        self.dut.scan_start_i.value = 0
        await RisingEdge(self.dut.clk_i)

    async def wait_fc_init(self, cycles=4000):
        """Bounded wait on the TRANSACTION LAYER's view of FC init.

        ⭐ THIS IS THE START GATE.  Not phy_link_up_i: Base 2.1 SS3.3.1 p.160 has
        FC initialisation complete once per link-up, and a transmitter holds no
        credit until it does.  fc_initialized_o is the wrapper's alias for
        dut.u_rcdl.fc_init_sticky_r, the filtered signal that actually drives
        u_rc.fc_initialized_i -- NOT the DLL's raw, glitching output.
        """
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if self.dut.fc_initialized_o.value.is_resolvable and \
                    int(self.dut.fc_initialized_o.value):
                return
        raise AssertionError(
            f"fc_init_sticky_r did not assert within {cycles} cycles -- the "
            "InitFC exchange never completed, so no TLP could ever be sent")


class PhyCompleter(BarSpaceCompleter):
    """BarSpaceCompleter with its two DUT-facing methods moved to the DLL boundary.

    ⭐ EVERYTHING ELSE TRANSFERS UNCHANGED, and that is the point of the split
    enum_tb_common describes at :1552-1554: the policy is pure.  _serve(),
    _answer() -- with its silent / UR-injected / CRS-once / write / read arms --
    complete(), wait_for(), start(), and the whole ConfigDevice write-mask model
    with real BAR sizing semantics are inherited verbatim.  Only the two methods
    that touch a bus are replaced:

        _watch_tx : m_dllp_axis, one Dword per beat  ->  m_phy_axis frames
        inject    : s_dllp_axis, one Dword per beat  ->  send_tlp (seq + LCRC)

    !! THE PROMPT ACK IS LOAD-BEARING, not politeness.  An unAcked TLP is
    replayed after the replay timer and the replay is a second frame on the
    wire; every frame-counting assertion in this file would then be off by one
    or more.  test_pcie_rc_dl_top.py:150-155 records the same finding.

    ⭐ AND IT RETURNS NON-POSTED CREDIT, because a completion does not.
    Every one of the seventeen configuration requests is NON-POSTED, so each
    consumes one NPH.  A CplD frees the far end's buffer but advertises
    nothing: it is the UpdateFC-NP DLLP that returns the credit
    (SS2.6.1.2 p.141, and test_pcie_rc_dl_top.py:465-470 does exactly this).
    Under MIN_CREDIT_EP the pool is ONE, so without this the enumeration
    deadlocks after the first request and the test would fail for a bench
    reason wearing an RTL costume.  The advertisement is CUMULATIVE and must
    increase; zero at init means infinite, so it starts from the profile's own
    value and counts up from there.

    The credit is returned AFTER the completion, not before, which is both
    legal and what makes the credit stall observable rather than raced away.
    """

    def __init__(self, tb, nph_initial=32, nak_at=None, credit_return_delay=0,
                 **kwargs):
        super().__init__(tb.dut, **kwargs)
        self.tb = tb
        self.frames = []          # raw framed bytes, for the byte-identical NAK check
        self.replays = []         # frames dropped as duplicates of an earlier sequence
        self.nak_at = nak_at      # frame index to NAK instead of Ack
        self.naks_sent = 0
        self.completions_sent = 0
        self.credit_return_delay = credit_return_delay
        self._nph_cum = nph_initial
        self._rx_next_seq = 0

    async def _watch_tx(self):
        while True:
            seq, body, frame = await self.tb.recv_tlp_frame()

            # A DLL receiver discards a duplicate sequence number rather than
            # handing it up twice (Base 2.1 SS3.6).  Modelling that here is what
            # makes "the enumerator sees ONE completion" a real property of the
            # NAK test rather than an artefact of the bench never replaying.
            if seq != self._rx_next_seq:
                self.replays.append(frame)
                await self.tb.ack((self._rx_next_seq - 1) & 0xFFF)
                continue

            index = len(self.frames)
            self.frames.append(frame)
            self._rx_next_seq = (seq + 1) & 0xFFF
            self.seen.append(request_from_body(body))

            if self.nak_at is not None and index == self.nak_at:
                # Force one replay: report the PREVIOUS sequence as the last
                # good one.  The frame has already been accepted above, so the
                # enumeration proceeds and the replay arrives as a duplicate.
                self.naks_sent += 1
                await self.tb.nak((seq - 1) & 0xFFF)
            else:
                await self.tb.ack(seq)

    async def inject(self, words):
        await self.tb.send_tlp(body_from_dwords(words))
        self.completions_sent += 1
        # credit_return_delay: how long the far end holds the request buffer
        # before advertising it again.  Zero is the prompt case; see the
        # measured finding in test_full_enumeration_min_credit's docstring for
        # why the credit-gated test does NOT use zero.
        for _ in range(self.credit_return_delay):
            await RisingEdge(self.tb.dut.clk_i)
        self._nph_cum = (self._nph_cum + 1) & 0xFF
        await send_axis(
            self.tb.phy_source,
            build_fc_dllp(DllpType.UPDATE_FC_NP, hdr_fc=self._nph_cum,
                          data_fc=self._nph_cum),
            PHY_USER_IS_DLLP,
        )


async def settle(dut, cycles=40):
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)


async def wait_frames(dut, completer, count, cycles=20000):
    """Bounded wait on frames observed at the DLL boundary."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        if len(completer.frames) >= count:
            return
    raise AssertionError(
        f"expected {count} TLP frames on m_phy_axis, saw "
        f"{len(completer.frames)} after {cycles} cycles -- FC credits, or the "
        "sequence never issued?")


async def wait_enum(dut, cycles=60000):
    """Bounded wait for the enumeration to terminate, either way."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        if int(dut.enum_done_o.value) or int(dut.enum_error_o.value):
            return
    raise AssertionError(
        f"neither enum_done_o nor enum_error_o asserted within {cycles} cycles")


async def bring_up(dut, credits=None, **completer_kwargs):
    """Reset, InitFC, far end attached, start gated on the TL's FC view.

    Returns (tb, completer, mon).  The gate is applied HERE rather than inside
    the DUT, which is the shape decision this rung records: fc_init_sticky_r is
    not on pcie_rc_dl_top's port list, so the integrator sequences the start.

    Mon starts before scan_start_i so no error strobe can be missed; it reads
    only real top-level ports plus the three seam aliases the wrapper provides.
    """
    tb = EnumDlTB(dut)
    await tb.reset()
    mon = Mon(dut)
    mon.start()
    completer = PhyCompleter(
        tb,
        device=completer_kwargs.pop("device", None) or acceptance_device(),
        nph_initial=(credits or {}).get(DllpType.INIT_FC2_NP, (32, 256))[0],
        **completer_kwargs)
    completer.start()
    completer.serve()
    await initialize_flow_control(dut, tb.phy_source, credits)
    await tb.wait_fc_init()
    await tb.start_enum()
    return tb, completer, mon


def assert_golden_on_the_wire(completer, what=""):
    """The seventeen emitted TLPs against the Stage C/D direct-attach golden.

    The golden is DIRECT_GOLDEN_SEQUENCE (test_pcie_enum_bridge_tlp.py:102) --
    field-level tuples over TlpRequest, hand-transcribed from the prediction
    document before the RTL existed, and carrying the type and bus columns.
    Nothing in it depends on how the Dwords were obtained, which is why it
    transfers across the DLL boundary unchanged once the shim exists.
    """
    seen = nonempty(completer.seen, f"{what}no TLP reached the wire at all")
    assert_sequence([on_wire(r) for r in seen], DIRECT_GOLDEN_SEQUENCE,
                    f"{what}direct-attach on-wire sequence", render=render)


# ==========================================================================
# (1) The headline: a whole enumeration, on the wire, through the real DLL
# ==========================================================================
@cocotb.test()
async def test_full_enumeration_on_wire(dut):
    """Scores D-P1.  Observation point: m_phy_axis frames, LCRC verified and
    stripped, transformed to Dwords and compared field-for-field against
    DIRECT_GOLDEN_SEQUENCE; then the top's own status ports.

    ⭐ WHAT THIS PROVES THAT NO EXISTING TARGET DOES.  Two things: the
    configuration requests survive real LCRC framing and sequence numbering
    byte-for-byte, and the credit that gated them came from a real InitFC
    exchange rather than set_credits().

    Positive controls, so a vacuous pass is not available: nonempty() on the
    observation set, an exact frame count, and the full captured BAR table.
    """
    tb, completer, mon = await bring_up(dut)
    await wait_enum(dut)

    snap = await status(dut)
    assert snap["done"] == 1 and snap["error"] == 0, (
        f"enumeration ended {err_name(snap['code'])}, not done: {snap}")

    assert_golden_on_the_wire(completer)
    expect_count(completer.frames, 17,
                 "TLP frames on m_phy_axis for a full direct-attach enumeration")
    assert completer.replays == [], (
        f"{len(completer.replays)} unexpected replay(s) on a clean run -- an "
        "unAcked frame would be retransmitted and counted twice")

    # The device table, against the Stage C acceptance goldens: a 16 KB 64-bit
    # prefetchable pair at BAR0/1 assigned at MEM_BAR_BASE.
    assert_acceptance_outcome(snap)
    assert_command_last(completer)
    assert_rom_untouched(completer)
    mon.clean()


# ==========================================================================
# (2) The same golden under the Table 2-37 Endpoint minimum
# ==========================================================================
@cocotb.test()
async def test_full_enumeration_min_credit(dut):
    """Scores D-P2.  Observation points: m_phy_axis frame count and ordering,
    tx_fc_blocked_o, and the fc_* readback after init.

    The spec-visible claim is that NPH = 1 (Base 2.1 Table 2-37 p.137, the
    Endpoint minimum) changes the TIMING and nothing else: the same seventeen
    transactions, in the same order, with the same payloads.

    ⭐ THE STALL IS COUNTED FROM FC-GATED STATES, NOT FROM CYCLES.  What is
    asserted is the number of times tx_fc_blocked_o ROSE -- each rise is one
    request the credit gate actually held -- not how long it stayed high, which
    would pin a latency rather than a behaviour.

    !! The enumerator cannot pace itself and must not be expected to.  It reads
    neither outstanding_o nor any tag -- structurally, the sequencers have no
    port on which they could see one (pcie_enum_scan.sv:145-150) -- so it
    issues, and the host's credit gate holds the TLP in the VC buffer.  That is
    why the observation is on the wire, where the spec can see it.

    ⛔ MEASURED, AND IT FALSIFIED THE PREDICTION: WITH A PROMPTLY-RETURNING FAR
    END, NPH=1 IS NEVER BINDING AND THE STALL COUNT IS ZERO.  Prediction D-P2
    said at least one stall would be observable; the first run measured none,
    with the golden and the frame count both correct.  The reason is that the
    enumerator is SINGLE-OUTSTANDING three times over -- cmd_ready_o is low from
    acceptance until the response is consumed (pcie_cfg_txn.sv:490), there is
    exactly one pcie_cfg_txn instance, and the credit gate sits behind both.  So
    request N+1 is not offered until the completion for N has been consumed, and
    a far end that advertises the freed buffer in the same breath as the
    completion has always restored the credit before anything wants it.

    That is a true statement about the design and NOT a reason to delete the
    assertion: it means the one-deep pool is never exercised by enumeration
    traffic, so a test that merely ran and passed would say nothing about the
    credit gate at all.  What makes NPH=1 binding is the far end holding its
    buffer for a while, which is legal and realistic.  credit_return_delay does
    exactly that, and it changes only the timing -- the seventeen-row golden
    below is asserted unchanged, which is the actual claim.
    """
    tb, completer, mon = await bring_up(dut, MIN_CREDIT_EP,
                                        credit_return_delay=64)

    # Negative control on the profile itself: prove the minima actually took,
    # or "no second frame in flight" would be trivially true under NPH=32.
    await ReadOnly()
    assert int(dut.fc_ph_o.value) == 1, "PH is not the Table 2-37 minimum"
    assert int(dut.fc_nph_o.value) == 1, "NPH is not the Table 2-37 minimum"
    assert int(dut.fc_cplh_o.value) == 0, "CPLH is not zero-encoded infinite"
    await RisingEdge(dut.clk_i)

    stalls = [0]
    stop = [False]
    peak_in_flight = [0]
    violations = []

    async def watch_blocked():
        prev = 0
        cycle = 0
        while not stop[0]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            cycle += 1
            now = int(dut.tx_fc_blocked_o.value)
            if now and not prev:
                stalls[0] += 1
            prev = now
            # Frames emitted and not yet answered.  Completions are counted
            # AFTER the send, so this is the largest value consistent with the
            # far end's own record -- the conservative direction for an upper
            # bound.
            in_flight = len(completer.frames) - completer.completions_sent
            peak_in_flight[0] = max(peak_in_flight[0], in_flight)
            if in_flight > 1:
                violations.append(
                    f"cycle {cycle}: {in_flight} configuration frames on the "
                    "wire unanswered; a one-deep non-posted header pool "
                    "permits exactly one")

    cocotb.start_soon(watch_blocked())
    await wait_enum(dut)
    stop[0] = True

    assert violations == [], (
        "two config frames were in flight at once under NPH=1:\n  "
        + "\n  ".join(violations[:8]))

    snap = await status(dut)
    assert snap["done"] == 1 and snap["error"] == 0, (
        f"enumeration under the credit minimum ended {err_name(snap['code'])}: "
        f"{snap}")

    assert_golden_on_the_wire(completer, "MIN_CREDIT_EP: ")
    expect_count(completer.frames, 17,
                 "MIN_CREDIT_EP: TLP frames on m_phy_axis")
    assert stalls[0] >= 1, (
        "tx_fc_blocked_o never rose under NPH=1 even with the far end holding "
        f"its buffer for {completer.credit_return_delay} cycles -- the credit "
        "gate was not exercised, so this run says nothing about it")
    assert_acceptance_outcome(snap, "MIN_CREDIT_EP: ")
    # allow_timeouts stays FALSE: pacing must not fabricate a completion
    # timeout, and the timers run from ALLOCATION, not from transmission.
    mon.clean()
    dut._log.info(
        f"D-P2 measurement: {stalls[0]} credit stall(s), peak "
        f"{peak_in_flight[0]} frame(s) in flight (prompt-return control "
        "measured 0 stalls -- see docstring)")


# ==========================================================================
# (3) A NAK inside the sequence: byte-identical replay, no duplicate above
# ==========================================================================
@cocotb.test()
async def test_nak_inside_sequence(dut):
    """Scores D-P3.  Observation point: m_phy_axis.

    ⭐ FRAME 8 IS CHOSEN, NOT ARBITRARY.  It is the BAR2 sizing write -- a CfgWr
    CARRYING A PAYLOAD.  A NAK on a payload-free CfgRd would compare a replay
    whose payload Dwords do not exist, and would pass against a DLL that
    replayed the header correctly and dropped the data.

    Two independent claims, because the byte comparison alone does not cover
    the second: the replayed frame is byte-identical INCLUDING its sequence
    number and LCRC (a data-link property), and the Transaction Layer above
    sees the transaction ONCE (an integration property -- a duplicate delivered
    upward would add an eighteenth row to the golden).
    """
    nak_index = 8
    assert DIRECT_GOLDEN_SEQUENCE[nak_index][2], \
        "premise: the NAKed frame must be a WRITE so the replay carries payload"

    tb, completer, mon = await bring_up(dut, nak_at=nak_index)
    await wait_enum(dut)

    snap = await status(dut)
    assert snap["done"] == 1 and snap["error"] == 0, (
        f"enumeration did not survive one NAK: {err_name(snap['code'])} {snap}")

    assert completer.naks_sent == 1, (
        f"the bench sent {completer.naks_sent} NAK(s) -- if it sent none, this "
        "test proves nothing and passes vacuously")
    replays = expect_count(completer.replays, 1,
                           "replayed frames after one NAK")
    assert replays[0] == completer.frames[nak_index], (
        "the replayed frame is not byte-identical to the original:\n"
        f"  first  {completer.frames[nak_index].hex()}\n"
        f"  replay {replays[0].hex()}")

    # The TL saw it once: the golden is unchanged and still seventeen rows.
    assert_golden_on_the_wire(completer, "after one NAK: ")
    expect_count(completer.frames, 17, "accepted TLP frames after one NAK")
    assert_acceptance_outcome(snap, "after one NAK: ")
    mon.clean()


# ==========================================================================
# (4) ⛔ THE START-GATE NEGATIVE CONTROL -- its pass condition is a FAILURE
# ==========================================================================
@cocotb.test()
async def test_start_gate_negative_control(dut):
    """Scores D-P4.  Observation points: m_phy_axis frame count in a bounded
    window, then enum_error_o / enum_error_code_o.

    ⭐ THIS TEST DEMONSTRATES THE HAZARD THAT SHAPE (iii) EXISTS TO CLOSE, rather
    than describing it in a comment.  scan_start_i is pulsed at phy_link_up_i
    and BEFORE flow control has initialised -- the mistake a self-starting top
    gated on link-up would make.

    The causal chain, all of it already in the RTL:
      * a transmitter holds no credit until FC init completes -- Base 2.1
        SS3.3.1 p.160, quoted at pcie_rc_dl_top.sv:176-177;
      * tag allocation sits UPSTREAM of the credit gate --
        pcie_enum_scan.sv:137-144;
      * the completion timer measures from ALLOCATION --
        tlp_request_tracker.sv:39.
    So the first CfgRd is tagged, parked in the VC buffer, and times out HAVING
    NEVER BEEN TRANSMITTED.

    ⛔ IF THIS TEST EVER SEES ENUMERATION SUCCEED, THAT IS A STOP CONDITION, not
    a pass.  It would mean the hazard closed without the port being added and
    the reasoning above is wrong somewhere.

    This test deliberately leaves the DUT in an errored state, so every test is
    written to reset first; bring_up() does.
    """
    tb = EnumDlTB(dut)
    await tb.reset()
    mon = Mon(dut)
    mon.start()
    completer = PhyCompleter(tb, device=acceptance_device())
    completer.start()
    completer.serve()

    # NO initialize_flow_control, and NO wait on fc_init_sticky_r.  The link is
    # up; that is the whole point, and it is not enough.
    await ReadOnly()
    assert int(dut.phy_link_up_i.value) == 1, "premise: the link must be up"
    assert int(dut.fc_initialized_o.value) == 0, (
        "premise: flow control must NOT be initialised yet, or this test is "
        "just a slow version of test 1")
    await RisingEdge(dut.clk_i)
    await tb.start_enum()

    # Nothing may reach the wire while the credit pool is empty.
    for _ in range(4000):
        await RisingEdge(dut.clk_i)
        assert completer.frames == [], (
            "⛔ SURPRISE: a TLP reached m_phy_axis before flow control "
            "initialised.  A transmitter holds no credit until FC init "
            "completes (Base 2.1 SS3.3.1 p.160), so this falsifies either the "
            "credit gate or the premise of the whole start-gate argument")

    # ... and the request that never left times out, from ALLOCATION.
    # CPL_TIMEOUT_CYCLES is 4096, so the bound is generous but finite.
    await wait_enum(dut, cycles=20000)
    await ReadOnly()
    done = int(dut.enum_done_o.value)
    error = int(dut.enum_error_o.value)
    code = int(dut.enum_error_code_o.value)

    assert not done, (
        "⛔ STOP CONDITION: enumeration COMPLETED although it was started "
        "before flow control initialised.  The hazard this rung documents is "
        "not present, and the shape (iii) argument needs re-deriving")
    assert error and code == ENUM_ERR_TIMEOUT, (
        f"the parked request ended {err_name(code)}, expected a completion "
        "timeout -- the failure mode is right but its classification is not")
    assert completer.frames == [], (
        "a frame escaped after the timeout fired")
    assert mon.timeouts, (
        "enum reported a timeout but cpl_timeout_valid_o never strobed -- the "
        "timeout must come from the tracker, the single timer for this job "
        "(pcie_cfg_txn.sv:92-98)")
    dut._log.info(
        f"D-P4: no frame in 4000 cycles; enum ended {err_name(code)} with "
        f"{len(mon.timeouts)} tracker timeout strobe(s)")


# ==========================================================================
# (5) Parameter coherence across the two children
# ==========================================================================
@cocotb.test()
async def test_parameter_coherence(dut):
    """Scores D-P5.  Read from the ELABORATED design through hierarchical
    references -- no plusargs, no bench-side restatement of the value.

    ⚠️ THE ITEM IS COHERENCE, NOT TIMER ARBITRATION.  There is ONE completion
    timer in the system, not two.  pcie_cfg_txn's CPL_TIMEOUT_CYCLES arms no
    counter at all -- pcie_cfg_txn.sv:92-98 says so, and its ONLY use is the
    elaboration-time P-CRS-BUDGET guard at :222-225, which checks that the CRS
    retry budget cannot outlast the timeout.  The timer that actually fires is
    tlp_request_tracker's, reached through pcie_rc_dl_top:196 -> u_rc ->
    tlp_layer:374.

    So the two copies must agree, or the guard silently validates a number no
    timer uses and a slow device is misreported as dead with no warning.  The
    wrapper makes that structural by passing one parameter to both children;
    this test proves the structure survived elaboration.

    ⛔ AND A SILENT GUARD IS INDISTINGUISHABLE FROM AN ABSENT ONE.  The guard
    does not fire in this configuration (3 * 8 = 24 < 4096) and does not fire
    at the library defaults either (16 * 64 = 1024 < 4096), so its silence
    proves nothing on its own.  What is asserted here is the input it is
    checking, at both ends.
    """
    tb = EnumDlTB(dut)
    await tb.reset()

    def param(path, name):
        obj = dut
        for part in path.split("."):
            obj = getattr(obj, part)
        return int(getattr(obj, name).value)

    # The four shared parameters, read on BOTH children.
    shared = {
        "AXIS_DATA_WIDTH": 128,
        "AXIS_KEEP_WIDTH": 4,
        "AXIS_USER_WIDTH": 60,
        "CPL_TIMEOUT_CYCLES": 4096,
    }
    for name, expected in shared.items():
        enum_value = param("dut.u_enum", name)
        rcdl_value = param("dut.u_rcdl", name)
        assert enum_value == rcdl_value, (
            f"{name} differs across the seam: u_enum={enum_value}, "
            f"u_rcdl={rcdl_value} -- one localparam must feed both")
        assert enum_value == expected, (
            f"{name} elaborated to {enum_value}, expected {expected}")

    # ⭐ The end-to-end claim, at the two places that matter: the value the
    # P-CRS-BUDGET guard checks, and the value the only real timer counts to.
    guard_value = param("dut.u_enum.u_txn", "CPL_TIMEOUT_CYCLES")
    timer_value = param("dut.u_rcdl.u_rc.u_tlp_layer.tracker_inst",
                        "CPL_TIMEOUT_CYCLES")
    assert guard_value == timer_value == shared["CPL_TIMEOUT_CYCLES"], (
        f"the P-CRS-BUDGET guard checks {guard_value} while the completion "
        f"timer counts to {timer_value} -- the guard is validating a number no "
        "timer uses")

    # The CRS budget the guard exists to bound, from the elaborated design.
    retries = param("dut.u_enum.u_txn", "CRS_RETRY_MAX")
    backoff = param("dut.u_enum.u_txn", "CRS_BACKOFF_CYCLES")
    assert retries * backoff < timer_value, (
        f"P-CRS-BUDGET: {retries} retries x {backoff} cycles >= the "
        f"{timer_value}-cycle timeout -- CRS retries could outlast it")

    # ⭐ THE SHARED SET IS EXACTLY FOUR, and this is the assertion that makes
    # "no parameter left implicitly different between the two sides" checkable
    # rather than a claim.  A parameter present on both children but passed by
    # the wrapper to only one would show up here as a name that resolves on
    # both and is therefore NOT in the child-specific list.
    def has(path, name):
        obj = dut
        for part in path.split("."):
            obj = getattr(obj, part)
        return hasattr(obj, name)

    for name in ("TAG_COUNT", "CONTEXT_WIDTH"):
        assert has("dut.u_rcdl", name), f"{name} should exist on u_rcdl"
        assert not has("dut.u_enum", name), (
            f"{name} resolves on u_enum too -- the shared set is larger than "
            "the four this wrapper unifies, and the extra one is unmanaged")
    for name in ("CRS_RETRY_MAX", "CRS_BACKOFF_CYCLES", "MEM_BAR_BASE",
                 "MEM_BAR_WINDOW"):
        assert has("dut.u_enum", name), f"{name} should exist on u_enum"
        assert not has("dut.u_rcdl", name), (
            f"{name} resolves on u_rcdl too -- the shared set is larger than "
            "the four this wrapper unifies, and the extra one is unmanaged")

    assert param("dut.u_rcdl", "TAG_COUNT") == 32, (
        "TAG_COUNT is not pcie_rc_dl_top's tested default")
