import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def exact_short_update_and_independent_pools(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.request_valid.value = 0
    dut.fc_initialized.value = 0
    dut.fc_update_valid.value = 0
    for _ in range(3): await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.ph.value=2; dut.pd.value=4; dut.nph.value=1; dut.npd.value=0
    dut.cplh.value=1; dut.cpld.value=3; dut.fc_update_valid.value=1
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid.value=0; dut.fc_initialized.value=1

    dut.request_class.value=0; dut.request_data_credits.value=4; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.request_valid.value=0
    assert int(dut.ph_av.value)==1 and int(dut.pd_av.value)==0

    dut.request_class.value=0; dut.request_data_credits.value=1; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==0 and int(dut.blocked.value)==1
    dut.request_class.value=2; dut.request_data_credits.value=3
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.request_valid.value=0
    assert int(dut.cplh_av.value)==0 and int(dut.cpld_av.value)==0
    assert int(dut.nph_av.value)==1 and int(dut.npd_av.value)==0

    dut.fc_initialized.value=0; dut.fc_update_valid.value=1
    dut.ph.value=255; dut.pd.value=4095
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid.value=0; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==0
