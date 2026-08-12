"""T1b: pins the tracker's DEFAULT CPL_TIMEOUT_CYCLES.

Runs on verilate_tlp_cpl_timeout_default, which sets no parameter at all, so
this exercises the value the RTL ships with.  The rest of the mechanism is
covered at 64 cycles by test_tlp_cpl_timeout.py; the only thing proved here is
that the default really is 4096 -- nothing fires before it, and it fires inside
the one-scan-period window after it.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

TAG_COUNT = 32
DEFAULT_TIMEOUT = 4096
CLK_NS = 10
RID = 0x1234


@cocotb.test()
async def t1b_default_timeout_is_4096(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    for name in ("allocate_valid", "completion_valid", "extended_tag_enable",
                 "allocate_requester_id", "allocate_byte_count", "allocate_address",
                 "allocate_context", "allocate_expects_data", "completion_requester_id",
                 "completion_tag", "completion_status", "completion_payload_bytes",
                 "completion_byte_count", "completion_lower_address"):
        getattr(dut, name).value = 0
    dut.result_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")

    dut.allocate_requester_id.value = RID
    dut.allocate_byte_count.value = 4
    dut.allocate_expects_data.value = 1
    dut.allocate_valid.value = 1
    await Timer(1, units="ps")
    while not int(dut.allocate_ready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    tag = int(dut.allocate_tag.value)
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.allocate_valid.value = 0
    assert tag == 0

    fired_at = None
    for k in range(1, DEFAULT_TIMEOUT + TAG_COUNT + 8):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.cpl_timeout_valid.value):
            assert fired_at is None, "cpl_timeout_valid must be a one-cycle strobe"
            fired_at = k
            assert int(dut.cpl_timeout_tag.value) == tag

    assert fired_at is not None, \
        f"no timeout within {DEFAULT_TIMEOUT + TAG_COUNT + 7} cycles -- default is too large"
    assert fired_at >= DEFAULT_TIMEOUT, (
        f"fired at k={fired_at}, EARLIER than the {DEFAULT_TIMEOUT}-cycle default -- "
        "the default is smaller than documented")
    assert fired_at <= DEFAULT_TIMEOUT + TAG_COUNT - 1, (
        f"fired at k={fired_at}, later than one scan period past {DEFAULT_TIMEOUT} -- "
        "the default is larger than documented")
