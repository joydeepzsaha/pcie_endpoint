import random
import zlib
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def reset(dut):
    dut.rst_i.value = 1
    dut.start.value = 0
    dut.data_valid.value = 0
    dut.finish.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0


async def run_bytes(dut, payload, rng):
    chunks = [payload[i:i + 4] for i in range(0, len(payload), 4)]
    for index, chunk in enumerate(chunks):
        for _ in range(rng.randrange(4)):
            dut.data_valid.value = 0
            await RisingEdge(dut.clk_i)
        dut.data.value = int.from_bytes(chunk.ljust(4, b"\0"), "little")
        dut.keep.value = (1 << len(chunk)) - 1
        dut.start.value = index == 0
        dut.finish.value = index == len(chunks) - 1
        dut.data_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.start.value = 0
        dut.finish.value = 0
        dut.data_valid.value = 0
    await RisingEdge(dut.clk_i)
    assert int(dut.ecrc_valid.value) == 1
    assert int(dut.ecrc.value) == zlib.crc32(payload)


@cocotb.test()
async def fixed_random_maximum_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    rng = random.Random(0xEC2C)
    for length in [1, 3, 4, 12, 16, 17, 64, 257, 4096]:
        await run_bytes(dut, bytes(rng.randrange(256) for _ in range(length)), rng)
    dut.start.value = 1
    dut.data_valid.value = 1
    dut.data.value = 0xDEADBEEF
    dut.keep.value = 0xF
    await RisingEdge(dut.clk_i)
    dut.rst_i.value = 1
    await RisingEdge(dut.clk_i)
    assert int(dut.ecrc_valid.value) == 0
