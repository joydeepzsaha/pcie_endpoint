"""Area 4b -- CPL/CPLD on-wire serialization (TL conformance sweep).

Commit 1 + Area 1 locked the request-path DW serialization; this locks the
completion-path one: the CPL-specific DW1/DW2 layout the generator emits, which
is what an RC actually puts on the wire when it answers an inbound request.

Driven through tb_tlp_generator (flattened header inputs).  Golden hand-derived
from the PCIe completion TLP format.
RTL cited:
  CPL DW1 = {completer_id, status, bcm, byte_count[11:0]} .. src/tlp/tlp_generator.sv, the dw0 th assignment
  CPL DW2 = {requester_id, tag, 1'b0, lower_address}  ...... src/tlp/tlp_generator.sv, the dw0 traffic-class assignment
  DW0 bit map ............................................. src/tlp/tlp_generator.sv, the dw0 assembly
  no-data 3DW tlast at DW2 ............................... src/tlp/tlp_generator.sv, payload_offset
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CPL = 0b01010
CPL_SC = 0b000
CPL_UR = 0b001


def dw0(fmt, typ, length_dw):
    enc = 0 if length_dw in (0, 1024) else (length_dw & 0x3FF)
    v = (fmt & 7) << 5 | (typ & 0x1F)
    v |= ((enc >> 8) & 3) << 16
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    for sig in ("in_fmt", "in_type", "in_tc", "in_attr", "in_length_dw",
                "in_requester_id", "in_completer_id", "in_tag", "in_first_be",
                "in_last_be", "in_address", "in_status", "in_byte_count",
                "in_lower_address", "in_prefix_present", "in_prefix",
                "in_digest_present", "in_digest", "header_valid",
                "payload_tdata", "payload_tkeep", "payload_tvalid", "payload_tlast"):
        getattr(dut, sig).value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


class Tx:
    def __init__(self, dut):
        self.dut = dut
        self.beats = []
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await Timer(1, units="ps")
            if int(d.m_axis_tvalid.value) and int(d.m_axis_tready.value):
                self.beats.append((int(d.m_axis_tdata.value), int(d.m_axis_tlast.value)))


async def emit_cpl(dut, length, completer_id, status, byte_count, requester_id,
                   tag, lower, payload=None):
    dut.in_fmt.value = FMT_3DW_DATA if payload else FMT_3DW_NO_DATA
    dut.in_type.value = TYPE_CPL
    dut.in_length_dw.value = length
    dut.in_completer_id.value = completer_id
    dut.in_status.value = status
    dut.in_byte_count.value = byte_count
    dut.in_requester_id.value = requester_id
    dut.in_tag.value = tag
    dut.in_lower_address.value = lower
    dut.header_valid.value = 1
    await Timer(1, units="ps")
    while not int(dut.header_ready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.header_valid.value = 0
    if payload:
        for i, dw in enumerate(payload):
            dut.payload_tdata.value = dw
            dut.payload_tkeep.value = 0xF
            dut.payload_tlast.value = 1 if i == len(payload) - 1 else 0
            dut.payload_tvalid.value = 1
            await Timer(1, units="ps")
            while not int(dut.payload_tready.value):
                await RisingEdge(dut.clk_i)
                await Timer(1, units="ps")
            await RisingEdge(dut.clk_i)
        dut.payload_tvalid.value = 0
        dut.payload_tlast.value = 0


async def settle(dut, n=10):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


@cocotb.test()
async def cpld_wire(dut):
    """CPLD serialization: DW0/DW1/DW2 spec layout + payload."""
    await init(dut)
    tx = Tx(dut); tx.start()
    await emit_cpl(dut, length=1, completer_id=0x0113, status=CPL_SC, byte_count=4,
                   requester_id=0x1234, tag=0x09, lower=0x04, payload=[0xDEAD_BEEF])
    await settle(dut)
    beats = tx.beats
    assert len(beats) == 4, f"CPLD = 3 header + 1 data, got {len(beats)}: {beats}"
    assert beats[0][0] == dw0(FMT_3DW_DATA, TYPE_CPL, 1), f"DW0 {beats[0][0]:#010x}"
    exp_dw1 = (0x0113 << 16) | (CPL_SC << 13) | (0 << 12) | (4 & 0xFFF)
    assert beats[1][0] == exp_dw1, f"DW1 {beats[1][0]:#010x} != {exp_dw1:#010x}"
    exp_dw2 = (0x1234 << 16) | (0x09 << 8) | (0x04 & 0x7F)
    assert beats[2][0] == exp_dw2, f"DW2 {beats[2][0]:#010x} != {exp_dw2:#010x}"
    assert beats[3] == (0xDEAD_BEEF, 1), f"payload {beats[3]}"


@cocotb.test()
async def cpl_nodata_wire(dut):
    """Cpl (no data) serialization: 3 header DWs, tlast at DW2, no payload."""
    await init(dut)
    tx = Tx(dut); tx.start()
    await emit_cpl(dut, length=0, completer_id=0x0113, status=CPL_UR, byte_count=0,
                   requester_id=0x5678, tag=0x0C, lower=0x00)
    await settle(dut)
    beats = tx.beats
    assert len(beats) == 3, f"Cpl no-data = 3 header DWs, got {len(beats)}: {beats}"
    assert beats[0][0] == dw0(FMT_3DW_NO_DATA, TYPE_CPL, 0)
    exp_dw1 = (0x0113 << 16) | (CPL_UR << 13)
    assert beats[1][0] == exp_dw1, f"DW1 {beats[1][0]:#010x} != {exp_dw1:#010x}"
    exp_dw2 = (0x5678 << 16) | (0x0C << 8)
    assert beats[2] == (exp_dw2, 1), f"DW2 {beats[2]} (must be tlast) != {(exp_dw2, 1)}"
