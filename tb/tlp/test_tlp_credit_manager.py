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


@cocotb.test()
async def all_starvation_combinations_and_saturating_guards(dut):
    """Prove independent header/data blocking for P, NP, and Cpl pools."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.request_valid.value = 0
    dut.fc_initialized.value = 0
    dut.fc_update_valid.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.fc_initialized.value = 1

    pools = [
        (0, "ph", "pd", "ph_av", "pd_av"),
        (1, "nph", "npd", "nph_av", "npd_av"),
        (2, "cplh", "cpld", "cplh_av", "cpld_av"),
    ]
    for traffic_class, header_in, data_in, header_out, data_out in pools:
        for name in ("ph", "nph", "cplh"):
            getattr(dut, name).value = 7
        for name in ("pd", "npd", "cpld"):
            getattr(dut, name).value = 7

        # Header available but data short.
        getattr(dut, header_in).value = 1
        getattr(dut, data_in).value = 0
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        dut.request_class.value = traffic_class
        dut.request_data_credits.value = 1
        dut.request_valid.value = 1
        await Timer(1, units="ps")
        assert not int(dut.request_ready.value)
        assert int(dut.blocked.value)
        assert int(getattr(dut, header_out).value) == 1
        assert int(getattr(dut, data_out).value) == 0

        # Data available but header absent.
        getattr(dut, header_in).value = 0
        getattr(dut, data_in).value = 1
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        await Timer(1, units="ps")
        assert not int(dut.request_ready.value)
        assert int(dut.blocked.value)
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 1

        # Exactly one header and one 16-byte data credit are consumed once.
        getattr(dut, header_in).value = 1
        getattr(dut, data_in).value = 1
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        await Timer(1, units="ps")
        assert int(dut.request_ready.value)
        await RisingEdge(dut.clk_i)
        dut.request_valid.value = 0
        await Timer(1, units="ps")
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 0

        # A blocked request cannot wrap either zero-valued counter.
        dut.request_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.request_valid.value = 0
        await Timer(1, units="ps")
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 0
