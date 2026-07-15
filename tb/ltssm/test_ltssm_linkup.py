"""
Link-up test for pcie_ltssm_downstream (downstream/RC-side LTSSM).
Drives the control/status handshake a link partner + PIPE PHY would produce,
and asserts the state machine walks Detect -> Polling -> Configuration -> L0.
Requires SIM_FAST_LINK=1 (verilate_fast target).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from ltssm_tb_common import *  # noqa


@cocotb.test()
async def run_test_linkup(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())  # 100 MHz
    await bring_up_link(dut)

    # ---- stay in L0: stop all training traffic, link must stay up ----
    await ClockCycles(dut.clk_i, 50)
    assert int(dut.ltssm_state_o.value) == ST_L0, "fell out of L0"
    assert int(dut.link_up_o.value) == 1, "link_up not asserted in L0"
    dut._log.info("LINK UP: full Detect->Polling->Config->L0 walk verified")
