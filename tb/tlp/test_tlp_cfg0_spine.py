"""Commit 1 -- CFG0 -> CPL spine at the tlp_layer level.

FIRST-EVER exercise of RC-originated config requests through tlp_layer:
originate a CfgRd0/CfgWr0 out the TX AXIS, then hand-inject the matching
completion on the RX AXIS and prove the request tracker catches it and the
outstanding tag clears.

All golden values are derived from the PCIe spec config-request/completion TLP
formats and cross-checked against the RTL byte layout, NOT transcribed from DUT
output.  file:line citations accompany each expectation.

tlp_cmd_e encoding .............. src/tlp/tlp_pkg.sv:43-50
CFG0 header build (requester) ... src/tlp/tlp_requester.sv:116-130
TX serialization (generator) .... src/tlp/tlp_generator.sv:49-79
config-address bit layout ....... src/tlp/tlp_config_decoder.sv (round-trip)
RX completion parse ............. src/tlp/tlp_parser.sv:151-195
tracker tag+RID match / clear ... src/tlp/tlp_request_tracker.sv:64-73,115-135
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# --- tlp_cmd_e members (tlp_pkg.sv:43-50) ---
CMD_CFG_READ0 = 2
CMD_CFG_WRITE0 = 3

# TLP type/fmt encodings (tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CFG0 = 0b00100
TYPE_CPL = 0b01010
CPL_SC = 0b000

RID = 0x1234       # requester_id_i -- the RC's own ID (init_top)
COMPLETER = 0x0113  # completer BDF: bus=0x01 dev=0x02 fn=0x03 -> {08:bus,05:dev,03:fn}


def cfg_addr(bus, dev, fn, reg_byte_offset, ext_reg=0):
    """Build the config-request address DW exactly as the DUT interprets it.

    The requester copies command_address_i straight into header.address
    (tlp_requester.sv:130) and the generator emits {address[31:2],2'b00} as the
    3rd DW (tlp_generator.sv:70-71).  The design's own config decode reads these
    same fields (tlp_config_decoder.sv), so this is the standard PCIe layout:
      [31:24]=Bus  [23:19]=Device  [18:16]=Function
      [15:12]=rsvd [11:8]=ExtReg   [7:2]=Register#  [1:0]=00
    """
    return (((bus & 0xFF) << 24) | ((dev & 0x1F) << 19) | ((fn & 0x7) << 16)
            | ((ext_reg & 0xF) << 8) | (reg_byte_offset & 0xFC))


async def init_top(dut):
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
    dut.requester_id_i.value = RID
    dut.completer_id_i.value = 0x5678
    dut.memory_enable_i.value = 1
    dut.extended_tag_enable_i.value = 0
    dut.max_payload_bytes_i.value = 128
    dut.max_read_bytes_i.value = 128
    # keep all TX/RX downstream sinks permanently ready
    dut.m_dllp_axis_tready.value = 1
    dut.target_request_ready_i.value = 1
    dut.target_data_ready_i.value = 1
    dut.received_completion_ready_i.value = 1
    dut.received_completion_data_ready_i.value = 1
    dut.result_ready_i.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk_i)


async def capture_tx(dut, max_cycles=80):
    """Collect m_dllp_axis beats until tlast."""
    words = []
    for _ in range(max_cycles):
        await RisingEdge(dut.clk_i)
        if int(dut.m_dllp_axis_tvalid.value) and int(dut.m_dllp_axis_tready.value):
            words.append((int(dut.m_dllp_axis_tdata.value),
                          int(dut.m_dllp_axis_tlast.value)))
            if words[-1][1]:
                break
    return words


async def issue_command(dut, cmd, address, byte_count=4,
                        data=None, keep=0xF):
    """Drive one command into the requester port group (tlp_layer.sv:43-59)."""
    if data is not None:
        dut.command_data_i.value = data
        dut.command_keep_i.value = keep
        dut.command_data_valid_i.value = 1
        dut.command_data_last_i.value = 1
    dut.command_i.value = cmd
    dut.command_address_i.value = address
    dut.command_byte_count_i.value = byte_count
    dut.command_tc_i.value = 0
    dut.command_attr_i.value = 0
    dut.command_context_i.value = 0x55
    dut.command_valid_i.value = 1
    while not int(dut.command_ready_o.value):
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0


class CompletionMonitor:
    """Concurrently records the single-cycle result pulse and completion data.

    result_valid_o is a 1-cycle pulse (tracker.sv:82,104-105) and is drained
    immediately when result_ready_i is held high, so it must be watched every
    edge -- a post-hoc poll races the drain and misses it.
    """

    def __init__(self, dut):
        self.dut = dut
        self.result = None       # (status, context) captured on the pulse
        self.data = []           # completion payload DWs captured on the wire
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            await Timer(1, units="ps")
            if (int(self.dut.result_valid_o.value)
                    and int(self.dut.result_ready_i.value) and self.result is None):
                self.result = (int(self.dut.result_status_o.value),
                               int(self.dut.result_context_o.value))
            if (int(self.dut.received_completion_data_valid_o.value)
                    and int(self.dut.received_completion_data_ready_i.value)):
                self.data.append(int(self.dut.received_completion_data_o.value))


async def send_rx(dut, data, last=False, keep=0xF):
    """Push one beat onto the RX AXIS (s_dllp_axis) -- the completion path."""
    dut.s_dllp_axis_tdata.value = data
    dut.s_dllp_axis_tkeep.value = keep
    dut.s_dllp_axis_tlast.value = 1 if last else 0
    dut.s_dllp_axis_tvalid.value = 1
    await Timer(1, units="ps")
    while not int(dut.s_dllp_axis_tready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.s_dllp_axis_tvalid.value = 0


@cocotb.test()
async def cfg_read0_spine(dut):
    """RC originates a CfgRd0, catches the returning CplD, tag clears."""
    await init_top(dut)
    assert int(dut.outstanding_o.value) == 0

    addr = cfg_addr(bus=0x01, dev=0x02, fn=0x03, reg_byte_offset=0x10)
    assert addr == 0x01130010, f"config addr build wrong: {addr:#010x}"

    # ---- Originate ----
    await issue_command(dut, CMD_CFG_READ0, addr, byte_count=4)
    tx = await capture_tx(dut)

    # ---- Spec golden for the emitted CfgRd0 (3DW, no data) ----
    # DW0: fmt=000(3DW-no-data) type=00100(CFG0) length=1
    #   dw0[7:5]=fmt dw0[4:0]=type dw0[31:24]=len[7:0] dw0[17:16]=len[9:8]
    #   -> 0x01000000 | 0x04  (generator.sv:51-62)
    exp_dw0 = (FMT_3DW_NO_DATA << 5) | TYPE_CFG0 | (1 << 24)
    # DW1: {requester_id, tag=0, last_be=0x0, first_be=0xF} (generator.sv:69)
    #   1-DW read -> first_be=1111 last_be=0000 (tlp_pkg tlp_first_be/tlp_last_be)
    exp_dw1 = (RID << 16) | (0 << 8) | (0x0 << 4) | 0xF
    # DW2: {address[31:2],2'b00} = the config-request DW (generator.sv:70-71)
    exp_dw2 = addr

    assert len(tx) == 3, f"CfgRd0 must be a 3-DW header, got {len(tx)} beats: {tx}"
    assert tx[0][0] == exp_dw0, f"DW0 {tx[0][0]:#010x} != {exp_dw0:#010x}"
    assert tx[1][0] == exp_dw1, f"DW1 {tx[1][0]:#010x} != {exp_dw1:#010x}"
    assert tx[2] == (exp_dw2, 1), f"DW2 {tx[2]} != {(exp_dw2, 1)}"
    assert int(dut.outstanding_o.value) == 1, "tag should be outstanding after TX"

    # ---- Inject the matching CplD on RX (parser.sv:151-195) ----
    # Completion returns the tag(0) and requester_id(RID) the request carried;
    # the tracker matches on exactly (tag, requester_id) (tracker.sv:66-73).
    mon = CompletionMonitor(dut)
    mon.start()
    cpl_dw0 = (FMT_3DW_DATA << 5) | TYPE_CPL | (1 << 24)          # 1 DW data
    cpl_dw1 = (COMPLETER << 16) | (CPL_SC << 13) | (0 << 12) | 0x004  # byte_count=4
    cpl_dw2 = (RID << 16) | (0 << 8) | 0x00                       # requester_id,tag,lower_addr
    read_data = 0xDEADBEEF
    await send_rx(dut, cpl_dw0)
    await send_rx(dut, cpl_dw1)
    await send_rx(dut, cpl_dw2)
    await send_rx(dut, read_data, last=True)
    for _ in range(6):
        await RisingEdge(dut.clk_i)

    # ---- Assert the catch: result pulsed, data surfaced, tag cleared ----
    assert mon.result is not None, "tracker never surfaced a result for the completion"
    assert mon.result == (CPL_SC, 0x55), f"result {mon.result} != (SC, context 0x55)"
    assert mon.data == [read_data], f"read data {mon.data} != [{read_data:#010x}]"
    assert int(dut.outstanding_o.value) == 0, "outstanding tag did not clear"
    assert int(dut.unexpected_completion_o.value) == 0, "completion flagged unexpected"


@cocotb.test()
async def cfg_write0_spine(dut):
    """RC originates a CfgWr0, catches the returning Cpl (no data), tag clears."""
    await init_top(dut)
    assert int(dut.outstanding_o.value) == 0

    addr = cfg_addr(bus=0x01, dev=0x02, fn=0x03, reg_byte_offset=0x10)
    write_data = 0xCAFEF00D

    # ---- Originate (3DW + 1 data DW) ----
    await issue_command(dut, CMD_CFG_WRITE0, addr, byte_count=4,
                        data=write_data, keep=0xF)
    tx = await capture_tx(dut)
    dut.command_data_valid_i.value = 0

    # DW0: fmt=010(3DW-data) type=00100(CFG0) length=1
    exp_dw0 = (FMT_3DW_DATA << 5) | TYPE_CFG0 | (1 << 24)
    exp_dw1 = (RID << 16) | (0 << 8) | (0x0 << 4) | 0xF
    exp_dw2 = addr

    assert len(tx) == 4, f"CfgWr0 must be 3-DW header + 1 data, got {len(tx)}: {tx}"
    assert tx[0][0] == exp_dw0, f"DW0 {tx[0][0]:#010x} != {exp_dw0:#010x}"
    assert tx[1][0] == exp_dw1, f"DW1 {tx[1][0]:#010x} != {exp_dw1:#010x}"
    assert tx[2][0] == exp_dw2, f"DW2 {tx[2][0]:#010x} != {exp_dw2:#010x}"
    assert tx[3] == (write_data, 1), f"payload {tx[3]} != {(write_data, 1)}"
    assert int(dut.outstanding_o.value) == 1, "non-posted write must hold a tag"

    # ---- Inject the matching Cpl (no data, length=0) ----
    # CPL no-data must carry length_dw=0 or the classifier rejects it
    # (tlp_classifier.sv: CPL && !has_data && length!=0 -> unsupported).
    mon = CompletionMonitor(dut)
    mon.start()
    cpl_dw0 = (FMT_3DW_NO_DATA << 5) | TYPE_CPL          # length=0
    cpl_dw1 = (COMPLETER << 16) | (CPL_SC << 13) | (0 << 12) | 0x000
    cpl_dw2 = (RID << 16) | (0 << 8) | 0x00
    await send_rx(dut, cpl_dw0)
    await send_rx(dut, cpl_dw1)
    await send_rx(dut, cpl_dw2, last=True)
    for _ in range(6):
        await RisingEdge(dut.clk_i)

    # ---- Assert the catch (no data DW for a write completion) ----
    assert mon.result is not None, "tracker never surfaced a result for the write completion"
    assert mon.result == (CPL_SC, 0x55), f"result {mon.result} != (SC, context 0x55)"
    assert mon.data == [], f"write completion carried unexpected data {mon.data}"
    assert int(dut.outstanding_o.value) == 0, "outstanding tag did not clear"
    assert int(dut.unexpected_completion_o.value) == 0, "completion flagged unexpected"
