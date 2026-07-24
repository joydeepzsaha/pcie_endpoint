import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


async def put(dut, words, cls, length):
    dut.s_class.value=cls; dut.s_length.value=length; dut.s_has_data.value=1
    for i,word in enumerate(words):
        dut.s_data.value=word; dut.s_keep.value=0xF; dut.s_last.value=i==len(words)-1
        dut.s_valid.value=1
        while not int(dut.s_ready.value): await RisingEdge(dut.clk_i)
        await RisingEdge(dut.clk_i)
    dut.s_valid.value=0


@cocotb.test()
async def packet_atomicity_credit_metadata_and_backpressure(dut):
    cocotb.start_soon(Clock(dut.clk_i,10,units="ns").start())
    dut.rst_i.value=1; dut.s_valid.value=0; dut.packet_ready.value=0; dut.m_ready.value=0
    for _ in range(3): await RisingEdge(dut.clk_i)
    dut.rst_i.value=0
    await put(dut,[0x10,0x11,0x12],0,5)
    await put(dut,[0x20,0x21],2,1)
    assert int(dut.packet_valid.value)==1
    assert int(dut.packet_class.value)==0 and int(dut.packet_credits.value)==2
    assert int(dut.m_valid.value)==0

    # A full packet FIFO applies ordinary backpressure and does not report overflow.
    dut.s_data.value=0x30; dut.s_keep.value=0xF; dut.s_last.value=1; dut.s_valid.value=1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        assert int(dut.s_ready.value)==0
        assert int(dut.overflow.value)==0
    dut.s_valid.value=0
    dut.packet_ready.value=1; await RisingEdge(dut.clk_i); dut.packet_ready.value=0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        assert int(dut.m_valid.value)==1 and int(dut.m_data.value)==0x10
    dut.m_ready.value=1
    got=[]
    while len(got)<3:
        await Timer(1,units="ps")
        if int(dut.m_valid.value): got.append((int(dut.m_data.value),int(dut.m_last.value)))
        await RisingEdge(dut.clk_i)
    assert got==[(0x10,0),(0x11,0),(0x12,1)]
    await RisingEdge(dut.clk_i)
    assert int(dut.packet_valid.value)==1 and int(dut.packet_class.value)==2
