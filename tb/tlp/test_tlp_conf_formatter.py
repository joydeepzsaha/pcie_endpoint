"""Area 6 -- payload_formatter byte-lane realignment (TL conformance sweep).

tlp_payload_formatter shifts a source payload so it begins at byte offset
start_offset within the first output DW (used by the generator for unaligned
writes/completions).  These tests feed hand-computed byte streams and assert
the realigned output DWs, keep masks, tlast placement, and backpressure hold.

Golden is hand-traced from the append/shift logic:
  offset seed / byte append .. src/tlp/tlp_payload_formatter.sv:53,58-67
  32-bit DW output + shift .... src/tlp/tlp_payload_formatter.sv:36-39,73-84
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.start_valid.value = 0
    dut.start_offset.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


class OutMon:
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
                self.beats.append((int(d.m_axis_tdata.value),
                                   int(d.m_axis_tkeep.value),
                                   int(d.m_axis_tlast.value)))


async def start_fmt(dut, offset):
    dut.start_offset.value = offset
    dut.start_valid.value = 1
    await Timer(1, units="ps")
    while not int(dut.start_ready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.start_valid.value = 0


async def feed(dut, tdata, tkeep, last):
    dut.s_axis_tdata.value = tdata
    dut.s_axis_tkeep.value = tkeep
    dut.s_axis_tlast.value = 1 if last else 0
    dut.s_axis_tvalid.value = 1
    await Timer(1, units="ps")
    while not int(dut.s_axis_tready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0


async def settle(dut, n=10):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


# --------------------------------------------------------------------------
@cocotb.test()
async def passthrough_offset0(dut):
    """offset 0, full DW -> unchanged single DW, keep 0xF, tlast."""
    await init(dut)
    mon = OutMon(dut); mon.start()
    await start_fmt(dut, 0)
    await feed(dut, 0x4433_2211, 0xF, last=True)
    await settle(dut)
    assert mon.beats == [(0x4433_2211, 0xF, 1)], mon.beats


@cocotb.test()
async def offset2_two_bytes(dut):
    """offset 2, 2 bytes -> single DW with the two bytes in lanes 2,3, keep 0xC."""
    await init(dut)
    mon = OutMon(dut); mon.start()
    await start_fmt(dut, 2)
    # bytes: lane0=0xAA, lane1=0xBB, keep=0x3
    await feed(dut, 0x0000_BBAA, 0x3, last=True)
    await settle(dut)
    assert mon.beats == [(0xBBAA_0000, 0xC, 1)], f"got {mon.beats}"


@cocotb.test()
async def offset1_carry_to_second_dw(dut):
    """offset 1, a full source DW spans two output DWs (5-byte span)."""
    await init(dut)
    mon = OutMon(dut); mon.start()
    await start_fmt(dut, 1)
    await feed(dut, 0x4433_2211, 0xF, last=True)
    await settle(dut)
    # DW0 = bytes[3:0]={33,22,11,--} keep 0xE not-last; DW1 = {--,--,--,44} keep 0x1 last
    assert mon.beats == [(0x3322_1100, 0xE, 0), (0x0000_0044, 0x1, 1)], f"got {mon.beats}"


@cocotb.test()
async def output_backpressure_holds(dut):
    """With m_ready deasserted, the output DW is held stable until ready rises."""
    await init(dut)
    await start_fmt(dut, 0)
    dut.m_axis_tready.value = 0
    await feed(dut, 0xCAFE_F00D, 0xF, last=True)
    # formatter should reach OUTPUT and hold valid without draining
    for _ in range(6):
        await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.m_axis_tvalid.value) == 1, "output must be valid and waiting"
    assert int(dut.m_axis_tdata.value) == 0xCAFE_F00D, "held data must be stable"
    assert int(dut.m_axis_tlast.value) == 1, "single-DW payload -> tlast held"
    # release and confirm it drains
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.m_axis_tvalid.value) == 0, "output must drain once ready is raised"
