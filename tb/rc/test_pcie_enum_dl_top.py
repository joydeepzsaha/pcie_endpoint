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

from cocotbext.pcie.core.tlp import Tlp, TlpType

from test_pcie_endpoint_top import (
    MIN_CREDIT_EP,
    PHY_USER_IS_TLP,
    add_sequence_and_lcrc,
    initialize_flow_control,
    send_axis,
)
from test_pcie_rc_dl_top import RcDlTB
from test_pcie_enum_bar_tlp import BarSpaceCompleter, acceptance_device
from test_pcie_enum_bridge_tlp import DIRECT_GOLDEN_SEQUENCE, on_wire, render
from enum_tb_common import (
    CFG_BE_DWORD, CFG_REG_BAR0, CFG_REG_COMMAND_STATUS, CFG_REG_VENDOR_DEVICE,
    CMD_ENABLE_VALUE, RID, SCAN_BUS,
    TlpRequest,
    cfg_wire_dw0, cfg_wire_dw1, cfg_wire_dw2,
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
    """

    def __init__(self, tb, **kwargs):
        super().__init__(tb.dut, **kwargs)
        self.tb = tb
        self.frames = []          # raw framed bytes, for the byte-identical NAK check

    async def _watch_tx(self):
        while True:
            seq, body, frame = await self.tb.recv_tlp_frame()
            self.frames.append(frame)
            self.seen.append(request_from_body(body))
            await self.tb.ack(seq)

    async def inject(self, words):
        await self.tb.send_tlp(body_from_dwords(words))


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

    Returns (tb, completer).  The gate is applied HERE rather than inside the
    DUT, which is the shape decision this rung records: fc_init_sticky_r is not
    on pcie_rc_dl_top's port list, so the integrator sequences the start.
    """
    tb = EnumDlTB(dut)
    await tb.reset()
    completer = PhyCompleter(
        tb, device=completer_kwargs.pop("device", None) or acceptance_device(),
        **completer_kwargs)
    completer.start()
    completer.serve()
    await initialize_flow_control(dut, tb.phy_source, credits)
    await tb.wait_fc_init()
    await tb.start_enum()
    return tb, completer
