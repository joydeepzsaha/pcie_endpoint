"""tlp_layer-level flow-control gating under repeated UpdateFC.

Commit A fixed tlp_credit_manager to track CREDIT_LIMIT and CREDITS_CONSUMED
separately (PCIe Base 2.1 SS2.6.1.1 p.139-140).  test_tlp_credit_manager.py proves
that at the module boundary; this file proves it where it actually matters --
through tlp_layer's `vc_packet_ready` gate (tlp_layer.sv:280), which is what
throttles real TX traffic.

Standalone and integration blind spots have run in both directions on this
project, so the headline case is asserted at both levels deliberately.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

MEM_READ = 0


async def init_layer(dut, nph, npd=3000):
    """Reset the layer and deliver the FC-initialisation advertisement.

    The first fc_update_valid_i strobe after reset is the initial advertisement
    (SPEC_PREDICTIONS_CREDIT.md SSI.2); every later strobe is an UpdateFC.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for handle in dut:
        if handle._name.endswith("_i") and handle._name not in {"clk_i", "rst_i"}:
            try:
                handle.value = 0
            except (AttributeError, ValueError):
                pass
    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1
    dut.requester_id_i.value = 0x1234
    dut.completer_id_i.value = 0x5678
    dut.memory_enable_i.value = 1
    dut.max_payload_bytes_i.value = 128
    dut.max_read_bytes_i.value = 128
    dut.fc_initialized_i.value = 1
    dut.m_dllp_axis_tready.value = 1
    await advertise(dut, nph, npd)
    for _ in range(2):
        await RisingEdge(dut.clk_i)


async def advertise(dut, nph, npd=3000):
    """One fc_update_valid_i strobe carrying a cumulative advertisement.

    P and CPL are held generously so the non-posted pool is the only constraint.
    """
    dut.fc_ph_i.value = 200
    dut.fc_pd_i.value = 3000
    dut.fc_nph_i.value = nph
    dut.fc_npd_i.value = npd
    dut.fc_cplh_i.value = 200
    dut.fc_cpld_i.value = 3000
    dut.fc_update_valid_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid_i.value = 0
    await Timer(1, units="ps")


async def issue_read(dut, address):
    dut.command_i.value = MEM_READ
    dut.command_address_i.value = address
    dut.command_byte_count_i.value = 4
    dut.command_tc_i.value = 0
    dut.command_attr_i.value = 0
    dut.command_context_i.value = address & 0xFFFF
    dut.command_valid_i.value = 1
    for _ in range(60):
        await RisingEdge(dut.clk_i)
        if int(dut.command_ready_o.value):
            break
    else:
        raise AssertionError("requester never accepted the command")
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0


async def await_tlp(dut, cycles=150):
    """Wait for one complete TLP on the DLL AXIS port.  True if one arrived."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        if int(dut.m_dllp_axis_tvalid.value) and int(dut.m_dllp_axis_tready.value):
            if int(dut.m_dllp_axis_tlast.value):
                return True
    return False


async def await_silence(dut, cycles=80):
    """True if no TLP word is presented for the whole window."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
        if int(dut.m_dllp_axis_tvalid.value):
            return False
    return True


@cocotb.test()
async def layer_does_not_transmit_past_the_cumulative_limit(dut):
    """*** The integration form of the accounting bug. ***

    The receiver advertises a cumulative non-posted header limit of 2, the layer
    spends both, and the receiver then re-advertises the SAME cumulative limit
    because it has freed nothing.  Remaining credit is 0, so vc_packet_ready must
    stay low and no third TLP may reach the DLL.

    Against the pre-fix RTL the re-advertisement reloaded the remainder to 2 and
    the layer transmitted a third TLP it had no credit for -- overrunning the
    receiver's buffer.  Expected to FAIL at 03d4915.
    """
    await init_layer(dut, nph=2)

    for i in range(2):
        await issue_read(dut, 0x2000 + 0x100 * i)
        assert await await_tlp(dut), f"credited read {i} was not transmitted"

    # Receiver has freed nothing: same cumulative limit, so 0 credits remain.
    await advertise(dut, nph=2)

    await issue_read(dut, 0x9000)
    assert await await_silence(dut), (
        "layer transmitted a third non-posted TLP after an UpdateFC that "
        "re-advertised an unchanged cumulative limit -- it had no credit for it")
    assert int(dut.tx_fc_blocked_o.value) == 1, "layer should report FC blocking"

    # Receiver frees one header credit: cumulative limit advances 2 -> 3.
    await advertise(dut, nph=3)
    assert await await_tlp(dut), "third read did not go once a credit was freed"


@cocotb.test()
async def layer_still_transmits_on_a_single_advertisement(dut):
    """Regression guard at the layer level: with one advertisement and
    consumption starting from zero, the new model behaves exactly as the old one
    did.  This is the property that keeps every pre-existing harness green."""
    await init_layer(dut, nph=8)
    for i in range(3):
        await issue_read(dut, 0x3000 + 0x100 * i)
        assert await await_tlp(dut), f"read {i} was not transmitted"
    assert int(dut.tx_fc_blocked_o.value) == 0, "should not be credit-blocked"
