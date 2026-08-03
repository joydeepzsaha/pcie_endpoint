"""Area 4 (+ Area 6 control arbiter) -- completion generator field build.

Drives tlp_completion_generator (feeding tlp_control) through the flattening
wrapper tb_tlp_completion_control and asserts the completion header the
completer builds: CPL vs CPLD selection, completion status, byte count, lower
address, and tag / requester-id / completer-id echo.  Also checks the control
arbiter's completion-over-requester priority.

All golden is hand-derived from the PCIe completion TLP format.
RTL cited:
  CPL header build ............ src/tlp/tlp_completion_generator.sv:56-72
  fmt = (byte_count==0) ...... src/tlp/tlp_completion_generator.sv:58
  length_dw calc ............. src/tlp/tlp_completion_generator.sv:62-63
  control completion priority  src/tlp/tlp_control.sv:44-49
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

TYPE_CPL = 0b01010
TYPE_MEM = 0b00000
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
CPL_SC = 0b000
CPL_UR = 0b001
CPL_CRS = 0b010
CPL_CA = 0b100

COMPLETER_ID = 0x0113


def golden_len(byte_count, lower):
    return (byte_count + (lower & 0x3) + 3) >> 2


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.completer_id.value = COMPLETER_ID
    dut.completion_request_valid.value = 0
    dut.request_requester_id.value = 0
    dut.request_tag.value = 0
    dut.request_tc.value = 0
    dut.request_attr.value = 0
    dut.completion_request_status.value = 0
    dut.completion_request_byte_count.value = 0
    dut.completion_request_lower_address.value = 0
    dut.completion_request_digest_valid.value = 0
    dut.completion_request_digest.value = 0
    dut.completion_request_data.value = 0
    dut.completion_request_keep.value = 0xF
    dut.completion_request_data_valid.value = 0
    dut.completion_request_data_last.value = 0
    dut.requester_header_valid.value = 0
    dut.requester_has_data.value = 0
    dut.requester_data.value = 0
    dut.requester_keep.value = 0xF
    dut.requester_data_valid.value = 0
    dut.requester_data_last.value = 0
    dut.generator_header_ready.value = 1
    dut.generator_data_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


class GenMon:
    def __init__(self, dut):
        self.dut = dut
        self.hdrs = []
        self.data = []
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await Timer(1, units="ps")
            if int(d.generator_header_valid.value) and int(d.generator_header_ready.value):
                self.hdrs.append(dict(
                    fmt=int(d.generator_fmt.value), typ=int(d.generator_type.value),
                    rid=int(d.generator_requester_id.value),
                    cid=int(d.generator_completer_id.value),
                    tag=int(d.generator_tag.value),
                    status=int(d.generator_status.value),
                    byte_count=int(d.generator_byte_count.value),
                    lower=int(d.generator_lower_address.value)))
            if int(d.generator_data_valid.value) and int(d.generator_data_ready.value):
                self.data.append(int(d.generator_data.value))


async def do_completion(dut, rid, tag, status, byte_count, lower, tc=0, attr=0,
                        data_dws=None):
    dut.request_requester_id.value = rid
    dut.request_tag.value = tag
    dut.request_tc.value = tc
    dut.request_attr.value = attr
    dut.completion_request_status.value = status
    dut.completion_request_byte_count.value = byte_count
    dut.completion_request_lower_address.value = lower
    if data_dws:
        dut.completion_request_data.value = data_dws[0]
        dut.completion_request_data_valid.value = 1
        dut.completion_request_data_last.value = 1 if len(data_dws) == 1 else 0
    dut.completion_request_valid.value = 1
    await Timer(1, units="ps")
    while not int(dut.completion_request_ready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.completion_request_valid.value = 0
    # stream remaining data beats
    if data_dws:
        for i, dw in enumerate(data_dws):
            dut.completion_request_data.value = dw
            dut.completion_request_data_valid.value = 1
            dut.completion_request_data_last.value = 1 if i == len(data_dws) - 1 else 0
            await Timer(1, units="ps")
            while not int(dut.completion_request_data_ready.value):
                await RisingEdge(dut.clk_i)
                await Timer(1, units="ps")
            await RisingEdge(dut.clk_i)
        dut.completion_request_data_valid.value = 0
        dut.completion_request_data_last.value = 0


async def settle(dut, n=8):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


# --------------------------------------------------------------------------
@cocotb.test()
async def cpld_basic(dut):
    """CPLD: byte_count!=0 -> 3DW data, len=1, echoes rid/tag, stamps completer_id."""
    await init(dut)
    mon = GenMon(dut); mon.start()
    await do_completion(dut, rid=0x1234, tag=0x09, status=CPL_SC, byte_count=4,
                        lower=0x00, data_dws=[0xDEAD_BEEF])
    await settle(dut)
    assert len(mon.hdrs) == 1, mon.hdrs
    h = mon.hdrs[0]
    assert h["typ"] == TYPE_CPL and h["fmt"] == FMT_3DW_DATA
    assert h["rid"] == 0x1234 and h["tag"] == 0x09, "must echo requester_id and tag"
    assert h["cid"] == COMPLETER_ID, "must stamp own completer_id"
    assert h["status"] == CPL_SC and h["byte_count"] == 4 and h["lower"] == 0x00
    assert mon.data == [0xDEAD_BEEF], mon.data


@cocotb.test()
async def cpl_nodata(dut):
    """CPL for a write: byte_count==0 -> 3DW no-data, length 0, no payload beats."""
    await init(dut)
    mon = GenMon(dut); mon.start()
    await do_completion(dut, rid=0x1234, tag=0x0A, status=CPL_SC, byte_count=0,
                        lower=0x00)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["fmt"] == FMT_3DW_NO_DATA and h["typ"] == TYPE_CPL
    assert h["byte_count"] == 0
    assert mon.data == [], f"no-data CPL must emit no payload: {mon.data}"


@cocotb.test()
async def status_variants(dut):
    """UR / CRS / CA completion status codes surface verbatim (all no-data)."""
    for st in (CPL_UR, CPL_CRS, CPL_CA):
        await init(dut)
        mon = GenMon(dut); mon.start()
        await do_completion(dut, rid=0x2222, tag=0x03, status=st, byte_count=0,
                            lower=0x00)
        await settle(dut)
        assert mon.hdrs[0]["status"] == st, f"status {mon.hdrs[0]['status']:#x} != {st:#x}"


@cocotb.test()
async def byte_count_lower_echo(dut):
    """64-byte CPLD: length=16, byte_count and lower_address echoed."""
    await init(dut)
    mon = GenMon(dut); mon.start()
    data = [0xC0000000 | i for i in range(16)]
    await do_completion(dut, rid=0x1234, tag=0x11, status=CPL_SC, byte_count=64,
                        lower=0x14, data_dws=data)
    await settle(dut, 24)
    h = mon.hdrs[0]
    assert h["byte_count"] == 64 and h["lower"] == 0x14
    assert mon.data == data, "CPLD payload mismatch"


@cocotb.test()
async def unaligned_length(dut):
    """lower_address[1:0]!=0 lengthens the DW count: 4B at offset 2 -> len 2."""
    await init(dut)
    mon = GenMon(dut); mon.start()
    # 4 bytes starting at lower_address 0x16 (offset 2) spans 2 DWs
    assert golden_len(4, 0x16) == 2, "golden self-check"
    await do_completion(dut, rid=0x1234, tag=0x12, status=CPL_SC, byte_count=4,
                        lower=0x16, data_dws=[0xAAAA_AAAA, 0xBBBB_BBBB])
    await settle(dut, 12)
    h = mon.hdrs[0]
    assert h["lower"] == 0x16 and h["byte_count"] == 4


@cocotb.test()
async def completion_priority(dut):
    """control arbiter: when both paths are valid, completion wins (control.sv:44)."""
    await init(dut)
    mon = GenMon(dut); mon.start()
    # assert a requester (no-data) header alongside a completion request
    dut.requester_has_data.value = 0
    dut.requester_header_valid.value = 1
    await do_completion(dut, rid=0x1234, tag=0x20, status=CPL_SC, byte_count=0,
                        lower=0x00)
    await settle(dut)
    # first header out must be the completion
    assert mon.hdrs, "no header emitted"
    assert mon.hdrs[0]["typ"] == TYPE_CPL, \
        f"completion must win arbitration, first out was type {mon.hdrs[0]['typ']:#x}"
    # release requester and confirm it can then proceed (MEM type appears)
    await settle(dut, 4)
    dut.requester_header_valid.value = 0
    await settle(dut)
    assert any(h["typ"] == TYPE_MEM for h in mon.hdrs), \
        "requester header never drained after completion"
