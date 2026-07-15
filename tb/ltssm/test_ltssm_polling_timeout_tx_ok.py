"""
Polling.Active 24ms timeout with a HEALTHY TX handshake: partner never sends
TS1/TS2, but our own ordered_set_tranmitted_i keeps pulsing normally. This is
the path that already worked before the Bug 4 fix (the watchdog check used to
live inside the ordered_set_tranmitted_i gate) -- it must keep passing
after the fix, proving the fix didn't disturb the previously-working case.
NOTE: TwentyFourMsTimeOut is NOT scaled by SIM_FAST_LINK -- this test
takes several real-world minutes. That is expected, not a hang.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from ltssm_tb_common import *  # noqa

@cocotb.test()
async def run_test_polling_timeout_tx_ok(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)

    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")
    dut.phy_rxelecidle_i.value = ALL
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")

    dut.receiver_detected_i.value = ALL
    dut.phy_rxstatus_i.value = RXSTATUS_ALL_OK
    dut.phy_phystatus_i.value = ALL
    await ClockCycles(dut.clk_i, 3)
    dut.phy_phystatus_i.value = 0
    await wait_state(dut, ST_POLLING_ACTIVE, 100, "POLLING_ACTIVE")

    # Partner is silent (no TS1/TS2 ever), but our own TX handshake is healthy.
    # ordered_set_sent_cnt never advances (it's gated on single_ts1_received),
    # so no success path can fire -- only the 24ms watchdog can end this.
    cocotb.start_soon(os_tx_pulser(dut))

    await wait_state(dut, ST_IDLE, 2_500_000, "ST_IDLE (24ms timeout, TX healthy)")
    dut._log.info("POLLING TIMEOUT (TX healthy) VERIFIED")
