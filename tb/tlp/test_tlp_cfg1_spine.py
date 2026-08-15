"""D-1b -- CFG1 -> CPL spine at the tlp_layer level (cfg0_spine precedent).

Originate a CfgRd1/CfgWr1 out the TX AXIS, then hand-inject the matching
spec-golden completion on the RX AXIS with the echoed tag + requester ID and
prove the request tracker catches it: result surfaced with the right status
and context, outstanding_o -> 0, unexpected_completion_o == 0.

F1b.4 lives here: cfg_read1_completion_expected asserts the completion
correlation WITHOUT asserting the TX header first, so its failure mode is the
tracker's ("CfgRd1's completion not expected"), not the wire golden's --
pre-change, tag_expects_data_o omits CFG_READ1, the CplD's payload trips the
tracker's !expects_data && payload != 0 guard (tlp_request_tracker.sv:334-340),
unexpected_completion_o goes high and no result ever fires.

TRAP A (docs/predictions/SPEC_PREDICTIONS_STAGE_D.md SS8.1): both spine tests compare the WHOLE
DW0 -- a Type 0 emission differs from Type 1 in exactly dw0[4:0] bit 0 and
would slip past any field-subset assertion.

All four FC preconditions are driven (link_up_i, transmit_enable_i,
fc_initialized_i, fc_update_valid_i with non-zero NPH/NPD) plus
requester_id_i / max_payload_bytes_i / max_read_bytes_i -- without them the
harness silently sees nothing.

Spec anchors:
  CfgRd1/CfgWr1 fmt/type ..... PCIe Base 2.1 Table 2-3 p.58
  config-request class rules . PCIe Base 2.1 SS2.2.7 p.79
RTL cited (read, not assumed):
  tlp_cmd_e ...... src/tlp/tlp_pkg.sv, typedef tlp_cmd_e
  type/fmt select ............ src/tlp/tlp_requester.sv:138-149
  non-MEM lower_address = 0 .. src/tlp/tlp_layer.sv:385-386
  tracker match / clear ...... src/tlp/tlp_request_tracker.sv:200-216,334-360
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# --- tlp_cmd_e members (src/tlp/tlp_pkg.sv, typedef tlp_cmd_e) ---
CMD_CFG_READ1 = 6
CMD_CFG_WRITE1 = 7

# TLP type/fmt encodings (src/tlp/tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CFG1 = 0b00101
TYPE_CPL = 0b01010
CPL_SC = 0b000

RID = 0x1234        # requester_id_i -- the RC's own ID, echoed by the Cpl
# Target behind a bridge: bus=0x3B dev=0x1C fn=0x5 -- distinct from the CFG0
# spine's 01/02/03, from conf_cfg1's 2A/11/6, and from completer_id_i=0x5678.
T1_BUS = 0x3B
T1_DEV = 0x1C
T1_FN = 0x5
# Completer ID the far device answers with: {bus[8], dev[5], fn[3]}.
COMPLETER = (T1_BUS << 8) | (T1_DEV << 3) | T1_FN
CTX_READ = 0x66
CTX_WRITE = 0x77


def cfg_addr(bus, dev, fn, reg_byte_offset, ext_reg=0):
    """Config-request address DW (standard layout, tlp_config_decoder.sv)."""
    return (((bus & 0xFF) << 24) | ((dev & 0x1F) << 19) | ((fn & 0x7) << 16)
            | ((ext_reg & 0xF) << 8) | (reg_byte_offset & 0xFC))


def golden_cfg_dw0(write, type1=False):
    """Whole DW0 of a config request (generator bit map, tlp_generator.sv, the dw0 assembly);
    Length=1 always (SS2.2.7).  type1=False keeps CFG0 callers unchanged."""
    fmt = FMT_3DW_DATA if write else FMT_3DW_NO_DATA
    typ = TYPE_CFG1 if type1 else 0b00100
    return ((fmt & 0x7) << 5) | (typ & 0x1F) | (1 << 24)


def init_flow_control(dut):
    """Saturate VC0 credits (credit registers reset to zero and only load on
    fc_update_valid_i -- leave these at 0 and nothing ever transmits)."""
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1
    dut.fc_ph_i.value = 0xFF
    dut.fc_pd_i.value = 0xFFF
    dut.fc_nph_i.value = 0xFF
    dut.fc_npd_i.value = 0xFFF
    dut.fc_cplh_i.value = 0xFF
    dut.fc_cpld_i.value = 0xFFF


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
    init_flow_control(dut)
    dut.requester_id_i.value = RID
    dut.completer_id_i.value = 0x5678
    dut.memory_enable_i.value = 1
    dut.extended_tag_enable_i.value = 0
    dut.max_payload_bytes_i.value = 128
    dut.max_read_bytes_i.value = 128
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
                        data=None, keep=0xF, context=0x55):
    """Drive one command into the requester port group."""
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
    dut.command_context_i.value = context
    dut.command_valid_i.value = 1
    while not int(dut.command_ready_o.value):
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0


class CompletionMonitor:
    """Records the single-cycle result pulse and completion data (the pulse
    drains the same cycle result_ready_i is high; a post-hoc poll misses it)."""

    def __init__(self, dut):
        self.dut = dut
        self.result = None
        self.data = []
        self.unexpected = 0   # unexpected_completion_o is a 1-cycle pulse
                              # (tlp_request_tracker.sv:267) -- latch it here,
                              # a post-hoc poll reads it after it has cleared

    def start(self):
        cocotb.start_soon(self._run())

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
            if int(self.dut.unexpected_completion_o.value):
                self.unexpected += 1


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


async def inject_cpld(dut, read_data):
    """Spec-golden CplD echoing tag 0 + RID, byte_count=4, lower_address=0
    (non-MEM allocations record address 0 -- tlp_layer.sv:385-386)."""
    cpl_dw0 = (FMT_3DW_DATA << 5) | TYPE_CPL | (1 << 24)
    cpl_dw1 = (COMPLETER << 16) | (CPL_SC << 13) | (0 << 12) | 0x004
    cpl_dw2 = (RID << 16) | (0 << 8) | 0x00
    await send_rx(dut, cpl_dw0)
    await send_rx(dut, cpl_dw1)
    await send_rx(dut, cpl_dw2)
    await send_rx(dut, read_data, last=True)
    for _ in range(6):
        await RisingEdge(dut.clk_i)


@cocotb.test()
async def cfg_read1_spine(dut):
    """RC originates a CfgRd1 (whole-DW0 golden), catches the CplD, tag clears."""
    await init_top(dut)
    assert int(dut.outstanding_o.value) == 0

    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x20)
    assert addr == 0x3BE50020, f"config addr build wrong: {addr:#010x}"

    await issue_command(dut, CMD_CFG_READ1, addr, byte_count=4, context=CTX_READ)
    tx = await capture_tx(dut)

    exp_dw0 = golden_cfg_dw0(write=False, type1=True)
    exp_dw1 = (RID << 16) | (0 << 8) | (0x0 << 4) | 0xF
    assert len(tx) == 3, f"CfgRd1 must be a 3-DW header, got {len(tx)} beats: {tx}"
    assert tx[0][0] == exp_dw0, \
        f"DW0 {tx[0][0]:#010x} != {exp_dw0:#010x} (dw0[4:0]={tx[0][0] & 0x1F:#07b})"
    assert tx[1][0] == exp_dw1, f"DW1 {tx[1][0]:#010x} != {exp_dw1:#010x}"
    assert tx[2] == (addr, 1), f"DW2 {tx[2]}"
    assert int(dut.outstanding_o.value) == 1, "tag should be outstanding after TX"

    mon = CompletionMonitor(dut)
    mon.start()
    read_data = 0x13579BDF
    await inject_cpld(dut, read_data)

    assert mon.result is not None, "tracker never surfaced a result for the CplD"
    assert mon.result == (CPL_SC, CTX_READ), \
        f"result {mon.result} != (SC, context {CTX_READ:#04x})"
    assert mon.data == [read_data], f"read data {mon.data} != [{read_data:#010x}]"
    assert int(dut.outstanding_o.value) == 0, "outstanding tag did not clear"
    assert mon.unexpected == 0, "completion flagged unexpected"


@cocotb.test()
async def cfg_write1_spine(dut):
    """RC originates a CfgWr1 (3DW + payload, whole-DW0 golden), catches the
    no-data Cpl, tag clears."""
    await init_top(dut)
    assert int(dut.outstanding_o.value) == 0

    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x2C)
    write_data = 0x2468ACE0

    await issue_command(dut, CMD_CFG_WRITE1, addr, byte_count=4,
                        data=write_data, keep=0xF, context=CTX_WRITE)
    tx = await capture_tx(dut)
    dut.command_data_valid_i.value = 0

    exp_dw0 = golden_cfg_dw0(write=True, type1=True)
    exp_dw1 = (RID << 16) | (0 << 8) | (0x0 << 4) | 0xF
    assert len(tx) == 4, f"CfgWr1 must be 3-DW header + 1 data, got {len(tx)}: {tx}"
    assert tx[0][0] == exp_dw0, \
        f"DW0 {tx[0][0]:#010x} != {exp_dw0:#010x} (dw0[4:0]={tx[0][0] & 0x1F:#07b})"
    assert tx[1][0] == exp_dw1, f"DW1 {tx[1][0]:#010x} != {exp_dw1:#010x}"
    assert tx[2][0] == addr, f"DW2 {tx[2][0]:#010x}"
    assert tx[3] == (write_data, 1), f"payload {tx[3]}"
    assert int(dut.outstanding_o.value) == 1, "non-posted write must hold a tag"

    # No-data Cpl must carry length_dw = 0 or the classifier rejects it.
    mon = CompletionMonitor(dut)
    mon.start()
    cpl_dw0 = (FMT_3DW_NO_DATA << 5) | TYPE_CPL
    cpl_dw1 = (COMPLETER << 16) | (CPL_SC << 13) | (0 << 12) | 0x000
    cpl_dw2 = (RID << 16) | (0 << 8) | 0x00
    await send_rx(dut, cpl_dw0)
    await send_rx(dut, cpl_dw1)
    await send_rx(dut, cpl_dw2, last=True)
    for _ in range(6):
        await RisingEdge(dut.clk_i)

    assert mon.result is not None, "tracker never surfaced a result for the Cpl"
    assert mon.result == (CPL_SC, CTX_WRITE), \
        f"result {mon.result} != (SC, context {CTX_WRITE:#04x})"
    assert mon.data == [], f"write completion carried unexpected data {mon.data}"
    assert int(dut.outstanding_o.value) == 0, "outstanding tag did not clear"
    assert mon.unexpected == 0, "completion flagged unexpected"


@cocotb.test()
async def cfg_read1_completion_expected(dut):
    """F1b.4 in isolation: a CfgRd1's CplD must be EXPECTED by the tracker.

    Deliberately asserts nothing about the TX header, so this test's failure
    mode is the tracker's and only the tracker's: with CFG_READ1 missing from
    command_is_read, tag_expects_data_o is 0, the CplD's payload trips
    !expects_data && payload != 0 (tlp_request_tracker.sv:334-340) ->
    unexpected_completion_o, and no result ever fires."""
    await init_top(dut)
    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x20)
    await issue_command(dut, CMD_CFG_READ1, addr, byte_count=4, context=CTX_READ)
    await capture_tx(dut)  # drain the request; contents deliberately unasserted
    assert int(dut.outstanding_o.value) == 1, "request never allocated a tag"

    mon = CompletionMonitor(dut)
    mon.start()
    read_data = 0x13579BDF
    await inject_cpld(dut, read_data)

    assert mon.unexpected == 0, \
        "CfgRd1's CplD was not expected (tag_expects_data_o=0 -> tracker mismatch)"
    assert mon.result is not None, "tracker never surfaced a result for the CplD"
    assert mon.result == (CPL_SC, CTX_READ), \
        f"result {mon.result} != (SC, context {CTX_READ:#04x})"
    assert mon.data == [read_data], f"read data {mon.data} != [{read_data:#010x}]"
    assert int(dut.outstanding_o.value) == 0, "outstanding tag did not clear"
