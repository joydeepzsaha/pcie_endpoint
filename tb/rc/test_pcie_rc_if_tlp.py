"""Commit 2a-ii -- pcie_rc_if behind a real tlp_layer (U12..U15).

The whole 2a loop, both wrappers present:

    host RQ AXIS -> pcie_rq_if -> tlp_layer -> TX DLLP
    RX DLLP -> tlp_layer -> pcie_rc_if -> host RC AXIS

The standalone target (verilate_rc_if) owns the cycle-accurate cases; this one
owns the question the standalone bench cannot answer -- whether the offsets and
field mappings this module assumes are the ones the real Transaction Layer
actually produces.  U13 is the payoff: a tag allocated by the request tracker,
presented on pcie_rq_tag_o, put on the wire in a CfgRd0, returned in the
completion and read back out of the RC descriptor's Tag field.

! FLOW CONTROL.  tlp_layer transmits nothing -- and reports no error -- until
link_up_i, transmit_enable_i and fc_initialized_i are set and at least one
fc_update_valid_i pulse has loaded non-zero credits (tlp_layer.sv:249,
tlp_credit_manager.sv:53-54, 66-83).  Config requests consume NPH/NPD.  This
bench MUST originate before it can inject: a completion with no outstanding tag
is an unexpected completion, the tracker produces no result, and pcie_rc_if
correctly emits nothing.  Forgetting the credits looks exactly like a broken
RC wrapper.

RTL cited (read, not assumed):
  CPL parse, DW1/DW2 fields ....... src/tlp/tlp_parser.sv:163-189
  CPL tc/attr in DW0 .............. src/tlp/tlp_parser.sv:145-147
  tracker match + accounting ...... src/tlp/tlp_request_tracker.sv:67-76, 123-155
  result_last = last CPL of the
    REQUEST ....................... src/tlp/tlp_request_tracker.sv:140-142
  Lower Address seeded 0 for
    non-memory requests ........... src/tlp/tlp_layer.sv:371-378
  DW0 assembly (TX golden) ........ src/tlp/tlp_generator.sv:60-73
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_NS = 4

# pcie_rq_rc_pkg::rq_req_type_e
RQ_CFG_READ0 = 0b1000
RQ_CFG_WRITE0 = 0b1010

# tlp_pkg::tlp_fmt_e / tlp_type_e (tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CFG0 = 0b00100
TYPE_CPL = 0b01010

# tlp_pkg::tlp_cpl_status_e == PG213 Completion Status
CPL_SC = 0b000
CPL_CRS = 0b010

# pcie_rq_rc_pkg::rc_desc_error_e
EC_NORMAL = 0b0000
EC_BAD_STATUS = 0b0010

TLP_ERR_UNEXPECTED_COMPLETION = 10

RID = 0x1234        # the RC's own requester_id_i
COMPLETER = 0x0113  # completer BDF bus=0x01 dev=0x02 fn=0x03


# --------------------------------------------------------------------------
# Descriptor goldens -- shared shape with test_pcie_rc_if.py, derived from
# PG213 v1.3 Table 65, never read back from the DUT.
# --------------------------------------------------------------------------
def decode_desc(v):
    return {
        "lower_address": v & 0xFFF,
        "error_code": (v >> 12) & 0xF,
        "byte_count": (v >> 16) & 0x1FFF,
        "locked": (v >> 29) & 1,
        "request_completed": (v >> 30) & 1,
        "dword_count": (v >> 32) & 0x7FF,
        "status": (v >> 43) & 0x7,
        "poisoned": (v >> 46) & 1,
        "requester_id": (v >> 48) & 0xFFFF,
        "tag": (v >> 64) & 0xFF,
        "completer_id": (v >> 72) & 0xFFFF,
        "tc": (v >> 89) & 0x7,
        "attr": (v >> 92) & 0x7,
    }


def rq_desc(req_type, dword_count, address=0, completer_id=0, tc=0, attr=0):
    """PG213 Table 60/61 RQ descriptor.  Tag [103:96] is ignored (core-managed)."""
    v = address & ((1 << 64) - 1)
    v |= (dword_count & 0x7FF) << 64
    v |= (req_type & 0xF) << 75
    v |= (completer_id & 0xFFFF) << 104
    v |= (tc & 0x7) << 121
    v |= (attr & 0x7) << 124
    return v


def cfg_desc_address(reg_num, ext_reg=0):
    return ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2)


def tuser(first_be, last_be):
    return ((last_be & 0xF) << 4) | (first_be & 0xF)


def cpl_dw0(has_data, length_dw, tc=0, attr=0):
    """CPL DW0 as the parser reads it back (tlp_parser.sv:145-147, 150-155)."""
    fmt = FMT_3DW_DATA if has_data else FMT_3DW_NO_DATA
    enc = length_dw & 0x3FF
    v = (fmt << 5) | TYPE_CPL
    v |= ((attr >> 2) & 0x1) << 10
    v |= (tc & 0x7) << 12
    v |= (attr & 0x3) << 20
    v |= ((enc >> 8) & 0x3) << 16
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def cpl_dw1(completer_id, status, byte_count, bcm=0):
    """{completer_id[31:16], status[15:13], BCM[12], byte_count[11:0]}."""
    return (((completer_id & 0xFFFF) << 16) | ((status & 0x7) << 13)
            | ((bcm & 1) << 12) | (byte_count & 0xFFF))


def cpl_dw2(requester_id, tag, lower_address):
    """{requester_id[31:16], tag[15:8], lower_address[6:0]}."""
    return (((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8)
            | (lower_address & 0x7F))


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
def init_flow_control(dut):
    """Saturate the VC0 credit pool.  See the file header -- without this the
    bench originates nothing and every result below would be vacuous."""
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1
    dut.fc_ph_i.value = 0xFF
    dut.fc_pd_i.value = 0xFFF
    dut.fc_nph_i.value = 0xFF
    dut.fc_npd_i.value = 0xFFF
    dut.fc_cplh_i.value = 0xFF
    dut.fc_cpld_i.value = 0xFFF


class Loop:
    """Records the TX stream, the presented tags and the RC packets."""

    def __init__(self, dut):
        self.dut = dut
        self.tx = []                # completed TX TLPs (lists of Dwords)
        self._cur_tx = []
        self.presented_tags = []    # pcie_rq_tag_o at each pcie_rq_tag_vld_o
        self.rc = []                # completed RC packets (lists of beats)
        self._cur_rc = []
        self.rc_errors = []
        self.unexpected = []

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if int(d.rst_i.value):
                continue
            if int(d.m_dllp_axis_tvalid.value) and int(d.m_dllp_axis_tready.value):
                self._cur_tx.append(int(d.m_dllp_axis_tdata.value))
                if int(d.m_dllp_axis_tlast.value):
                    self.tx.append(self._cur_tx)
                    self._cur_tx = []
            if int(d.pcie_rq_tag_vld_o.value):
                self.presented_tags.append(int(d.pcie_rq_tag_o.value))
            if int(d.m_axis_rc_tvalid.value) and int(d.m_axis_rc_tready.value):
                self._cur_rc.append((int(d.m_axis_rc_tdata.value),
                                     int(d.m_axis_rc_tkeep.value),
                                     int(d.m_axis_rc_tlast.value)))
                if int(d.m_axis_rc_tlast.value):
                    self.rc.append(self._cur_rc)
                    self._cur_rc = []
            if int(d.rc_protocol_error_o.value):
                self.rc_errors.append(int(d.rc_error_code_o.value))
            if int(d.rc_unexpected_completion_o.value):
                self.unexpected.append(int(d.rc_completion_error_code_o.value))

    def clear(self):
        self.tx.clear()
        self._cur_tx = []
        self.presented_tags.clear()
        self.rc.clear()
        self._cur_rc = []
        self.rc_errors.clear()
        self.unexpected.clear()

    async def wait_rc(self, count, cycles=600):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if len(self.rc) >= count:
                return
        raise AssertionError(f"expected {count} RC packets, saw {len(self.rc)}")


def packet_dwords(beats):
    words = []
    for tdata, tkeep, _last in beats:
        for dword in range(4):
            if (tkeep >> dword) & 1:
                words.append((tdata >> (32 * dword)) & 0xFFFFFFFF)
    return words


def split_packet(beats):
    words = packet_dwords(beats)
    assert len(words) >= 3, f"RC packet shorter than a descriptor: {words}"
    return words[0] | (words[1] << 32) | (words[2] << 64), words[3:]


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    dut.transmit_enable_i.value = 0
    dut.s_axis_rq_tdata.value = 0
    dut.s_axis_rq_tkeep.value = 0
    dut.s_axis_rq_tvalid.value = 0
    dut.s_axis_rq_tlast.value = 0
    dut.s_axis_rq_tuser.value = 0
    dut.s_dllp_axis_tdata.value = 0
    dut.s_dllp_axis_tkeep.value = 0
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0
    dut.s_dllp_axis_tuser.value = 0
    dut.m_dllp_axis_tready.value = 1
    dut.m_axis_rc_tready.value = 1
    dut.requester_id_i.value = RID
    dut.max_payload_bytes_i.value = 128
    dut.max_read_bytes_i.value = 128
    dut.fc_initialized_i.value = 0
    dut.fc_update_valid_i.value = 0
    for name in ("fc_ph_i", "fc_pd_i", "fc_nph_i", "fc_npd_i",
                 "fc_cplh_i", "fc_cpld_i"):
        getattr(dut, name).value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1
    init_flow_control(dut)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    loop = Loop(dut)
    loop.start()
    await RisingEdge(dut.clk_i)
    return loop


async def send_rq(dut, beats):
    """beats: (tdata, tkeep, tlast, tuser) on the host RQ AXIS."""
    for data, keep, last, user in beats:
        dut.s_axis_rq_tdata.value = data
        dut.s_axis_rq_tkeep.value = keep
        dut.s_axis_rq_tlast.value = 1 if last else 0
        dut.s_axis_rq_tuser.value = user
        dut.s_axis_rq_tvalid.value = 1
        for _ in range(4000):
            await ReadOnly()
            fired = int(dut.s_axis_rq_tready.value) == 1
            await RisingEdge(dut.clk_i)
            if fired:
                break
        else:
            raise AssertionError("s_axis_rq_tready never asserted -- stalled")
    dut.s_axis_rq_tvalid.value = 0
    dut.s_axis_rq_tlast.value = 0


async def send_rx(dut, words):
    """Push a whole TLP onto the RX AXIS, Dword-serial, tlast on the final one."""
    for index, word in enumerate(words):
        dut.s_dllp_axis_tdata.value = word
        dut.s_dllp_axis_tkeep.value = 0xF
        dut.s_dllp_axis_tlast.value = 1 if index == len(words) - 1 else 0
        dut.s_dllp_axis_tvalid.value = 1
        for _ in range(4000):
            await ReadOnly()
            fired = int(dut.s_dllp_axis_tready.value) == 1
            await RisingEdge(dut.clk_i)
            if fired:
                break
        else:
            raise AssertionError("s_dllp_axis_tready never asserted -- stalled")
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0


async def issue_cfg_read(dut, loop, reg_num, ext_reg=0):
    """Originate one CfgRd0 and return the tag it actually went out with."""
    desc = rq_desc(RQ_CFG_READ0, dword_count=1,
                   address=cfg_desc_address(reg_num, ext_reg),
                   completer_id=COMPLETER)
    await send_rq(dut, [(desc, 0xF, True, tuser(0xF, 0x0))])
    for _ in range(200):
        await RisingEdge(dut.clk_i)
        if loop.tx and loop.presented_tags:
            break
    assert loop.tx, "no CfgRd0 left the Transaction Layer -- FC credits?"
    packet = loop.tx[0]
    assert len(packet) == 3, f"CfgRd0 must be a 3-Dword header, got {packet}"
    wire_tag = (packet[1] >> 8) & 0xFF          # DW1[15:8]
    assert loop.presented_tags, "pcie_rq_tag_vld_o never strobed for a CfgRd0"
    return wire_tag


# ==========================================================================
# U12 -- CfgRd0 out, matching CplD in, RC packet out
# ==========================================================================
@cocotb.test()
async def u12_config_read_completion_end_to_end(dut):
    """A real CfgRd0 answered by a real CplD produces the right RC packet."""
    loop = await init(dut)
    assert int(dut.outstanding_o.value) == 0

    wire_tag = await issue_cfg_read(dut, loop, reg_num=0x04)
    assert int(dut.outstanding_o.value) == 1, "a CfgRd0 must hold a tag"

    read_data = 0x8086100E
    await send_rx(dut, [
        cpl_dw0(has_data=True, length_dw=1),
        cpl_dw1(COMPLETER, CPL_SC, byte_count=4),
        cpl_dw2(RID, wire_tag, lower_address=0),
        read_data,
    ])
    await loop.wait_rc(1)

    desc, payload = split_packet(loop.rc[0])
    fields = decode_desc(desc)
    assert fields["tag"] == wire_tag, \
        f"RC descriptor Tag {fields['tag']:#04x} != the tag on the wire {wire_tag:#04x}"
    assert fields["status"] == CPL_SC and fields["error_code"] == EC_NORMAL
    assert fields["byte_count"] == 4, f"Byte Count {fields['byte_count']} != 4"
    assert fields["dword_count"] == 1, f"Dword Count {fields['dword_count']} != 1"
    assert fields["request_completed"] == 1, "a single-CPL request must set bit 30"
    assert fields["requester_id"] == RID, \
        f"Requester ID {fields['requester_id']:#06x} != {RID:#06x}"
    assert fields["completer_id"] == COMPLETER, \
        f"Completer ID {fields['completer_id']:#06x} != {COMPLETER:#06x}"
    # Lower Address is 0 for every non-Memory-Read completion; the wrapper must
    # not echo the config request's address bits into it (tlp_layer.sv:371-378).
    assert fields["lower_address"] == 0, \
        f"config completion Lower Address {fields['lower_address']:#05x} != 0"
    assert payload == [read_data], f"read data {payload} != [{read_data:#010x}]"

    for _ in range(10):
        await RisingEdge(dut.clk_i)
    assert int(dut.outstanding_o.value) == 0, "the tag did not retire"
    assert loop.unexpected == [], f"completion flagged unexpected: {loop.unexpected}"
    assert loop.rc_errors == [], f"RC protocol errors: {loop.rc_errors}"


# ==========================================================================
# U13 -- the tag round trip
# ==========================================================================
@cocotb.test()
async def u13_tag_round_trip(dut):
    """pcie_rq_tag_o == the RC descriptor's Tag [71:64], four tags at once.

    This is the assertion the 54b8a72 tag fix was made possible for.  Before it
    pcie_rq_tag_o presented the descriptor's Tag field rather than the one the
    tracker allocated, so this comparison would have been checking a value the
    hardware never used.

    Four requests are left OUTSTANDING TOGETHER and then completed in reverse.
    Issuing them one at a time would be close to vacuous: the tracker always
    hands out the lowest free index (tlp_request_tracker.sv:58-63), so a
    request that retires before the next one is issued always gets tag 0 and
    the whole test would compare 0 against 0.  Holding four forces tags
    0..3 to be distinct, and completing them out of order means a wrapper that
    paired completions with requests positionally rather than by tag fails.
    """
    loop = await init(dut)

    regs = (0x04, 0x0C, 0x18, 0x24)
    for reg in regs:
        desc = rq_desc(RQ_CFG_READ0, dword_count=1,
                       address=cfg_desc_address(reg), completer_id=COMPLETER)
        await send_rq(dut, [(desc, 0xF, True, tuser(0xF, 0x0))])

    for _ in range(300):
        await RisingEdge(dut.clk_i)
        if len(loop.tx) >= len(regs) and len(loop.presented_tags) >= len(regs):
            break
    assert len(loop.tx) == len(regs), \
        f"{len(loop.tx)} CfgRd0s left the TL, expected {len(regs)} -- FC credits?"
    assert int(dut.outstanding_o.value) == len(regs), \
        f"outstanding_o {int(dut.outstanding_o.value)} != {len(regs)}"

    wire_tags = [(packet[1] >> 8) & 0xFF for packet in loop.tx]
    assert loop.presented_tags == wire_tags, \
        (f"pcie_rq_tag_o sequence {[hex(t) for t in loop.presented_tags]} != the "
         f"tags in the emitted headers {[hex(t) for t in wire_tags]}")
    assert len(set(wire_tags)) == len(regs), \
        (f"tags {[hex(t) for t in wire_tags]} are not distinct -- the test would "
         "not distinguish a wrapper that always reports the same tag")

    # Complete in reverse, each with its own recognisable read data.
    order = list(reversed(range(len(regs))))
    for slot in order:
        await send_rx(dut, [
            cpl_dw0(has_data=True, length_dw=1),
            cpl_dw1(COMPLETER, CPL_SC, byte_count=4),
            cpl_dw2(RID, wire_tags[slot], lower_address=0),
            0xC0DE0000 | slot,
        ])
    await loop.wait_rc(len(regs), cycles=1200)

    for position, slot in enumerate(order):
        desc, payload = split_packet(loop.rc[position])
        got = decode_desc(desc)["tag"]
        assert got == wire_tags[slot], \
            (f"RC packet {position}: Tag {got:#04x} != pcie_rq_tag_o "
             f"{wire_tags[slot]:#04x} -- the request and completion halves of "
             "Commit 2a disagree about which request this completion answers")
        assert payload == [0xC0DE0000 | slot], \
            (f"RC packet {position}: Tag {got:#04x} arrived with payload {payload}, "
             f"which belongs to another completion")

    for _ in range(10):
        await RisingEdge(dut.clk_i)
    assert int(dut.outstanding_o.value) == 0, "not every tag retired"
    assert loop.unexpected == [], f"a completion was flagged unexpected: {loop.unexpected}"


# ==========================================================================
# U14 -- config-write completion, no data
# ==========================================================================
@cocotb.test()
async def u14_config_write_completion_no_data(dut):
    """CfgWr0 answered by a Cpl with no data: descriptor-only RC packet."""
    loop = await init(dut)

    write_data = 0xCAFEF00D
    desc_in = rq_desc(RQ_CFG_WRITE0, dword_count=1,
                      address=cfg_desc_address(0x10), completer_id=COMPLETER)
    await send_rq(dut, [
        (desc_in, 0xF, False, tuser(0xF, 0x0)),
        (write_data, 0x1, True, 0),
    ])
    for _ in range(200):
        await RisingEdge(dut.clk_i)
        if loop.tx and loop.presented_tags:
            break
    assert loop.tx, "no CfgWr0 left the Transaction Layer -- FC credits?"
    assert len(loop.tx[0]) == 4, f"CfgWr0 must be 3 header + 1 data, got {loop.tx[0]}"
    wire_tag = (loop.tx[0][1] >> 8) & 0xFF
    assert int(dut.outstanding_o.value) == 1, "a non-posted write must hold a tag"

    # A Cpl with no data must carry length_dw == 0 or the classifier rejects it.
    await send_rx(dut, [
        cpl_dw0(has_data=False, length_dw=0),
        cpl_dw1(COMPLETER, CPL_SC, byte_count=4),
        cpl_dw2(RID, wire_tag, lower_address=0),
    ])
    await loop.wait_rc(1)

    beats = loop.rc[0]
    desc, payload = split_packet(beats)
    fields = decode_desc(desc)
    assert fields["dword_count"] == 0, \
        f"Dword Count {fields['dword_count']} != 0 for a Cpl with no data"
    assert payload == [], f"a write completion carried payload {payload}"
    assert fields["lower_address"] == 0, \
        f"Lower Address {fields['lower_address']:#05x} != 0"
    assert fields["tag"] == wire_tag
    assert fields["status"] == CPL_SC and fields["error_code"] == EC_NORMAL
    assert fields["request_completed"] == 1

    assert len(beats) == 1, f"descriptor-only packet must be one beat, got {len(beats)}"
    assert beats[0][1] == 0b0111, \
        f"3 descriptor Dwords -> tkeep 0b0111, got {beats[0][1]:#05b}"
    assert beats[0][2] == 1, "descriptor-only packet must assert tlast on beat 0"

    for _ in range(10):
        await RisingEdge(dut.clk_i)
    assert int(dut.outstanding_o.value) == 0, "the tag did not retire"


# ==========================================================================
# U15 -- CRS, and an unexpected completion, through the real TL
# ==========================================================================
@cocotb.test()
async def u15_crs_and_unexpected_completion(dut):
    """CRS survives the trip intact; a stale tag fabricates nothing.

    (The regression half of U15 -- every existing target still green -- is the
    full fusesoc sweep, not something a cocotb test can assert.)

    CRS is the case Commit 2b depends on: a device may legally answer an early
    Configuration read with Configuration Request Retry Status, and the
    enumeration FSM has to see it to know to retry rather than to conclude the
    function is absent.
    """
    loop = await init(dut)

    # ---- CRS to a config read ----
    wire_tag = await issue_cfg_read(dut, loop, reg_num=0x00)
    # A CRS completion carries no data and terminates the request
    # (tlp_request_tracker.sv:140-142, status != TLP_CPL_SC).
    await send_rx(dut, [
        cpl_dw0(has_data=False, length_dw=0),
        cpl_dw1(COMPLETER, CPL_CRS, byte_count=4),
        cpl_dw2(RID, wire_tag, lower_address=0),
    ])
    await loop.wait_rc(1)

    desc, payload = split_packet(loop.rc[0])
    fields = decode_desc(desc)
    assert fields["status"] == CPL_CRS, \
        (f"Completion Status {fields['status']:#05b} != 010 -- CRS did not survive "
         "the trip and Commit 2b would read it as something else")
    assert fields["error_code"] == EC_BAD_STATUS, \
        f"Error Code {fields['error_code']:#06b} != 0010 for CRS"
    assert fields["request_completed"] == 1, "CRS terminates the request"
    assert fields["dword_count"] == 0 and payload == []
    assert fields["tag"] == wire_tag
    for _ in range(10):
        await RisingEdge(dut.clk_i)
    assert int(dut.outstanding_o.value) == 0, "CRS must retire the tag"

    # ---- a completion for a tag nobody is holding ----
    loop.clear()
    stale_tag = (wire_tag + 7) & 0xFF
    await send_rx(dut, [
        cpl_dw0(has_data=True, length_dw=1),
        cpl_dw1(COMPLETER, CPL_SC, byte_count=4),
        cpl_dw2(RID, stale_tag, lower_address=0),
        0xDEADBEEF,
    ])
    for _ in range(40):
        await RisingEdge(dut.clk_i)

    assert loop.rc == [], \
        f"an unexpected completion fabricated {len(loop.rc)} RC packet(s)"
    assert loop.unexpected == [TLP_ERR_UNEXPECTED_COMPLETION], \
        f"unexpected completion not surfaced: {loop.unexpected}"
    assert int(dut.outstanding_o.value) == 0


# ==========================================================================
# M2-I2 -- attribute placement off the wire, parser direction
# ==========================================================================
# The mirror of M2-I1.  The completion DW0 is assembled here from the spec
# table directly -- NOT from cpl_dw0() -- so that the stimulus and the DUT do
# not share a helper.  If they shared one, a helper wrong in the same way as the
# RTL would make this pass, which is exactly how the misplacement survived.
#
#   PCIe Base 2.1 SS2.2.1 p.57  Attr[2] = bit 2 of byte 1  -> dw0[10]
#                               Attr[1:0] = bits [5:4] of byte 2 -> dw0[21:20]
#   PG213 Table 65              RC descriptor attr[94:92] is {IDO, RO, NS},
#                               matching pcie_rq_rc_pkg.sv:119
#
# So this walks a bit from a Base-2.1 wire position to a PG213 descriptor bit:
# both ends are normative and neither is read back from the DUT.
ATTR_WIRE_POSITION = ((2, 10, "IDO"), (1, 21, "RO"), (0, 20, "NS"))

# Same reasoning as M2-I1: 0 and 7 are fixed points and prove nothing; 1, 2 and
# 4 are one-hot and pin each bit independently.
# See SPEC_PREDICTIONS_MERGE_M2.md SS7.
ATTR_DRIVE_SET = (1, 2, 4, 5, 7)


def spec_cpl_dw0(attr, length_dw=1):
    """A CplD DW0 built straight from Base 2.1 SS2.2.1 p.57, helper-free."""
    v = (FMT_3DW_DATA << 5) | TYPE_CPL
    v |= (length_dw & 0xFF) << 24
    v |= ((length_dw >> 8) & 0x3) << 16
    for src, pos, _ in ATTR_WIRE_POSITION:
        if (attr >> src) & 1:
            v |= 1 << pos
    return v & 0xFFFFFFFF


@cocotb.test()
async def m2i2_completion_attr_decodes_from_spec_wire_positions(dut):
    """M2-I2: Attr bits at their spec DW0 positions reach the RC descriptor.

    A completion is driven with one attribute bit set at the position Base 2.1
    assigns it, and the RC descriptor's Attributes field is checked for the same
    bit.  Round-trip cannot do this job: tlp_parser is the exact inverse of
    tlp_generator under both placements, so a loopback is the identity however
    the bits sit.  See SPEC_PREDICTIONS_MERGE_M2.md SS6.
    """
    loop = await init(dut)
    seen = 0

    for attr in ATTR_DRIVE_SET:
        wire_tag = await issue_cfg_read(dut, loop, reg_num=0x04)
        read_data = 0xC0DE0000 | attr
        await send_rx(dut, [
            spec_cpl_dw0(attr),
            cpl_dw1(COMPLETER, CPL_SC, byte_count=4),
            cpl_dw2(RID, wire_tag, lower_address=0),
            read_data,
        ])
        seen += 1
        await loop.wait_rc(seen)

        desc, payload = split_packet(loop.rc[seen - 1])
        fields = decode_desc(desc)
        assert fields["attr"] == attr, (
            f"RC descriptor Attributes {fields['attr']:#05b} != {attr:#05b} "
            f"driven at the Base 2.1 wire positions; per PG213 Table 65 bit 92 "
            f"is No Snoop, 93 Relaxed Ordering, 94 ID-Based Ordering")
        assert fields["tag"] == wire_tag, "the completion did not match its request"
        assert payload == [read_data], f"payload {payload} != [{read_data:#010x}]"

        for _ in range(10):
            await RisingEdge(dut.clk_i)
        assert int(dut.outstanding_o.value) == 0, \
            f"attr=0b{attr:03b}: the tag did not retire"
        assert loop.unexpected == [], \
            f"attr=0b{attr:03b}: completion flagged unexpected: {loop.unexpected}"
        assert loop.rc_errors == [], \
            f"attr=0b{attr:03b}: RC protocol errors {loop.rc_errors}"
