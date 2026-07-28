"""Area 2 -- Request tracker stress (TL conformance sweep).

The tracker is the completion-catch spine: it allocates tags on origination and
matches returning completions by (tag, requester_id), clearing the outstanding
entry and surfacing a result.  These tests drive real reads out of tlp_layer to
allocate tags, then hand-inject spec-derived completions on the RX AXIS and
assert match / byte-accounting / clear / surface / reject behaviour.

result_valid_o is a 1-cycle pulse drained by held-high result_ready_i, so it is
watched with a concurrent monitor (Commit-1 gotcha, tracker.sv:82,104-105).

RTL cited:
  (tag, RID) match ............ src/tlp/tlp_request_tracker.sv:64-73
  tag allocation / free scan .. src/tlp/tlp_request_tracker.sv:52-62,107-113
  multi-CPL byte accounting ... src/tlp/tlp_request_tracker.sv:122-134
  unexpected (no match) ....... src/tlp/tlp_request_tracker.sv:116-117
  completion_ready backpressure src/tlp/tlp_request_tracker.sv:74
  layer payload-byte calc ..... src/tlp/tlp_layer.sv:181-186
  parser CPL header layout .... src/tlp/tlp_parser.sv:151-181
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CMD_MEM_READ = 0
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CPL = 0b01010
CPL_SC = 0b000
CPL_UR = 0b001

RID = 0x1234
COMPLETER = 0x0113


def init_flow_control(dut):
    """Advertise "FC initialized, credits saturated" on tlp_layer's VC0 inputs.

    The merged tlp_layer gates every TX packet on the credit manager:
      tlp_layer.sv:249   vc_packet_ready = credit_request_ready && ...
      tlp_credit_manager.sv:53  request_ready_o = fc_initialized_i &&
                                selected_header_available && selected_data_available
    The credit registers reset to zero (tlp_credit_manager.sv:67-73) and only
    load on fc_update_valid_i, so a harness that leaves these at 0 never
    transmits.  Tag exhaustion in particular needs TAG_COUNT reads genuinely in
    flight, which a starved credit pool silently caps at the VC buffer depth.
    Flow control has its own tb_tlp_credit_manager bench; here the credit pool is
    held saturated so it is never the limiter.
    """
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1
    dut.fc_ph_i.value = 0xFF
    dut.fc_pd_i.value = 0xFFF
    dut.fc_nph_i.value = 0xFF
    dut.fc_npd_i.value = 0xFFF
    dut.fc_cplh_i.value = 0xFF
    dut.fc_cpld_i.value = 0xFFF


async def init_top(dut, max_read=128):
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
    dut.max_read_bytes_i.value = max_read
    dut.m_dllp_axis_tready.value = 1
    dut.target_request_ready_i.value = 1
    dut.target_data_ready_i.value = 1
    dut.received_completion_ready_i.value = 1
    dut.received_completion_data_ready_i.value = 1
    dut.result_ready_i.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk_i)


class ResultMonitor:
    """Records every drained result pulse as (status, context, last)."""

    def __init__(self, dut):
        self.dut = dut
        self.results = []
        self.data = []
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            await Timer(1, units="ps")
            if int(self.dut.result_valid_o.value) and int(self.dut.result_ready_i.value):
                self.results.append((int(self.dut.result_status_o.value),
                                     int(self.dut.result_context_o.value),
                                     int(self.dut.result_last_o.value)))
            if (int(self.dut.received_completion_data_valid_o.value)
                    and int(self.dut.received_completion_data_ready_i.value)):
                self.data.append(int(self.dut.received_completion_data_o.value))


async def issue_read(dut, address, byte_count, context, cmd=CMD_MEM_READ):
    dut.command_i.value = cmd
    dut.command_address_i.value = address
    dut.command_byte_count_i.value = byte_count
    dut.command_context_i.value = context
    dut.command_tc_i.value = 0
    dut.command_attr_i.value = 0
    dut.command_valid_i.value = 1
    await Timer(1, units="ps")
    guard = 0
    while not int(dut.command_ready_o.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        guard += 1
        if guard > 200:
            break
    accepted = int(dut.command_ready_o.value) == 1
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0
    return accepted


async def send_rx(dut, data, last=False, keep=0xF):
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


def cpl_dw0(has_data, length_dw):
    fmt = FMT_3DW_DATA if has_data else FMT_3DW_NO_DATA
    enc = length_dw & 0x3FF
    v = (fmt << 5) | TYPE_CPL
    v |= ((enc >> 8) & 0x3) << 16
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def cpl_dw1(completer_id, status, byte_count, bcm=0):
    return ((completer_id & 0xFFFF) << 16) | ((status & 0x7) << 13) | \
           ((bcm & 1) << 12) | (byte_count & 0xFFF)


def cpl_dw2(rid, tag, lower_address):
    return ((rid & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | (lower_address & 0x7F)


async def send_cpl(dut, tag, status, byte_count, lower_address, data_dws=None, rid=RID):
    """Send a spec-derived completion.  data_dws=None -> Cpl (no data)."""
    has_data = data_dws is not None
    length = len(data_dws) if has_data else 0
    await send_rx(dut, cpl_dw0(has_data, length))
    await send_rx(dut, cpl_dw1(COMPLETER, status, byte_count))
    if not has_data:
        await send_rx(dut, cpl_dw2(rid, tag, lower_address), last=True)
    else:
        await send_rx(dut, cpl_dw2(rid, tag, lower_address))
        for i, dw in enumerate(data_dws):
            await send_rx(dut, dw, last=(i == length - 1))


async def settle(dut, n=8):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


# --------------------------------------------------------------------------
@cocotb.test()
async def out_of_order_completion(dut):
    """Two reads (tags 0,1); complete tag 1 first, then tag 0.  Both clear."""
    await init_top(dut)
    mon = ResultMonitor(dut); mon.start()
    assert await issue_read(dut, 0x8000, 4, context=0xA1)
    assert await issue_read(dut, 0x8100, 4, context=0xB2)
    await settle(dut)
    assert int(dut.outstanding_o.value) == 2, "two read tags outstanding"

    # complete tag 1 first
    await send_cpl(dut, tag=1, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0x1111_1111])
    await settle(dut)
    assert int(dut.outstanding_o.value) == 1, "tag 1 should clear, tag 0 remain"
    # then tag 0
    await send_cpl(dut, tag=0, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0x0000_0000])
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0, "both tags cleared"
    # results surfaced in completion order, contexts intact
    ctxs = [r[1] for r in mon.results]
    assert ctxs == [0xB2, 0xA1], f"context order {ctxs} != [tag1=0xB2, tag0=0xA1]"
    assert all(r[0] == CPL_SC and r[2] == 1 for r in mon.results), mon.results
    assert int(dut.unexpected_completion_o.value) == 0


@cocotb.test()
async def multi_cpl_byte_accounting(dut):
    """One 128B read answered by two 64B completions; tag clears only on the 2nd.

    remaining starts 128 (segment byte count).  CPL1 delivers 64 bytes
    (payload_bytes 64 < 128) -> partial, tag held, result_last=0.  CPL2 delivers
    the final 64 (64 >= remaining 64) -> clear, result_last=1
    (tracker.sv:122-134, layer.sv:181-186).
    """
    await init_top(dut, max_read=128)
    mon = ResultMonitor(dut); mon.start()
    assert await issue_read(dut, 0x9000, 128, context=0xCC)
    await settle(dut)
    assert int(dut.outstanding_o.value) == 1

    # CPL1: 64 bytes, lower_address=0x00, byte_count=128 (bytes remaining incl this)
    await send_cpl(dut, tag=0, status=CPL_SC, byte_count=128, lower_address=0x00,
                   data_dws=[0xD0000000 | i for i in range(16)])
    await settle(dut)
    assert int(dut.outstanding_o.value) == 1, "partial completion must not clear the tag"
    assert len(mon.results) == 1 and mon.results[0][2] == 0, \
        f"first result must be non-last: {mon.results}"

    # CPL2: final 64 bytes, lower_address=0x40, byte_count=64
    await send_cpl(dut, tag=0, status=CPL_SC, byte_count=64, lower_address=0x40,
                   data_dws=[0xD1000000 | i for i in range(16)])
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0, "final completion clears the tag"
    assert len(mon.results) == 2 and mon.results[1][2] == 1, \
        f"second result must be last: {mon.results}"
    assert mon.results[0][1] == 0xCC and mon.results[1][1] == 0xCC, "context echoed both times"
    assert int(dut.unexpected_completion_o.value) == 0


@cocotb.test()
async def unexpected_completion(dut):
    """Completion whose (tag,RID) matches no outstanding request -> unexpected."""
    await init_top(dut)
    saw_unexpected = []
    async def watch():
        while True:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.unexpected_completion_o.value):
                saw_unexpected.append(int(dut.outstanding_o.value))
    cocotb.start_soon(watch())
    assert int(dut.outstanding_o.value) == 0
    await send_cpl(dut, tag=7, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0xDEADBEEF])
    await settle(dut)
    assert saw_unexpected, "no outstanding tag -> unexpected_completion_o must assert"
    assert int(dut.result_valid_o.value) == 0, "no result for an unmatched completion"


@cocotb.test()
async def duplicate_completion(dut):
    """A second completion for an already-cleared tag is flagged unexpected."""
    await init_top(dut)
    mon = ResultMonitor(dut); mon.start()
    saw_unexpected = []
    async def watch():
        while True:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.unexpected_completion_o.value):
                saw_unexpected.append(1)
    cocotb.start_soon(watch())

    assert await issue_read(dut, 0xA000, 4, context=0x33)
    await settle(dut)
    await send_cpl(dut, tag=0, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0x1234_5678])
    await settle(dut)
    assert int(dut.outstanding_o.value) == 0, "first completion clears the tag"
    assert not saw_unexpected, "first completion must not be flagged"
    # duplicate -- tag 0 no longer active
    await send_cpl(dut, tag=0, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0x1234_5678])
    await settle(dut)
    assert saw_unexpected, "duplicate completion for a cleared tag must be unexpected"


@cocotb.test()
async def malformed_cpl_rejected(dut):
    """A no-data CPL carrying Length!=0 is rejected upstream; tag is untouched.

    classifier.sv:61-63: CPL && !has_data && length!=0 -> UNSUPPORTED, so
    parsed_completion is deasserted and the tracker never matches it.  The
    outstanding tag must survive and no (un)expected result is produced.
    """
    await init_top(dut)
    mon = ResultMonitor(dut); mon.start()
    saw_unexpected = []
    async def watch():
        while True:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.unexpected_completion_o.value):
                saw_unexpected.append(1)
    cocotb.start_soon(watch())

    assert await issue_read(dut, 0xE000, 4, context=0x44)
    await settle(dut)
    assert int(dut.outstanding_o.value) == 1
    # no-data CPL (fmt 3DW no-data) but Length field = 5 -> malformed per spec
    await send_rx(dut, cpl_dw0(has_data=False, length_dw=5))
    await send_rx(dut, cpl_dw1(COMPLETER, CPL_SC, 4))
    await send_rx(dut, cpl_dw2(RID, 0, 0x00), last=True)
    await settle(dut)
    assert int(dut.outstanding_o.value) == 1, "malformed CPL must not clear the tag"
    assert not mon.results, f"malformed CPL must surface no result: {mon.results}"
    assert not saw_unexpected, "rejected-by-classifier CPL is not an unexpected match"


@cocotb.test()
async def tag_exhaustion(dut):
    """Fill all 32 non-extended tags; outstanding caps at 32 until one frees.

    NOTE on the requester contract: command_ready_o == (state==REQ_IDLE)
    (requester.sv:137) signals requester idleness, NOT tag availability -- the
    requester accepts one further command and then wedges in REQ_TAG until a tag
    is free.  The spec-level invariant is therefore that the *tag pool* never
    exceeds TAG_COUNT (no 33rd allocation) and a slot only opens on completion.
    """
    await init_top(dut)
    for i in range(32):
        ok = await issue_read(dut, 0xB000 + i * 0x40, 4, context=i)
        assert ok, f"read {i} should be accepted"
        await settle(dut, 2)
    assert int(dut.outstanding_o.value) == 32, \
        f"all 32 tags should be outstanding, got {int(dut.outstanding_o.value)}"

    # 33rd command: accepted into REQ_TAG but cannot allocate a tag.  Watch that
    # the tag pool NEVER exceeds 32 while it is wedged.
    await issue_read(dut, 0xC000, 4, context=99)
    overflow = []
    async def watch_cap():
        while True:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            if int(dut.outstanding_o.value) > 32:
                overflow.append(int(dut.outstanding_o.value))
    cocotb.start_soon(watch_cap())
    await settle(dut, 20)
    assert not overflow, f"tag pool overflowed past 32: {overflow}"
    assert int(dut.outstanding_o.value) == 32, "still exactly 32 outstanding while wedged"

    # a 34th command cannot even be accepted -- requester is not REQ_IDLE
    dut.command_i.value = CMD_MEM_READ
    dut.command_address_i.value = 0xC100
    dut.command_byte_count_i.value = 4
    dut.command_valid_i.value = 1
    blocked = True
    for _ in range(10):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.command_ready_o.value):
            blocked = False
            break
    dut.command_valid_i.value = 0
    assert blocked, "34th origination must not be accepted while the 33rd is wedged"

    # free tag 5 -> the wedged 33rd request grabs the freed slot: net stays 32
    await send_cpl(dut, tag=5, status=CPL_SC, byte_count=4, lower_address=0x00,
                   data_dws=[0xFEED_0005])
    await settle(dut, 8)
    assert int(dut.outstanding_o.value) == 32, \
        "completing one tag frees a slot the wedged request immediately reuses"


@cocotb.test()
async def result_ready_backpressure(dut):
    """result_valid_o holds while result_ready_i is low, drains when raised.

    Context/status must survive the stall unchanged (tracker.sv:74,104-105).
    """
    await init_top(dut)
    dut.result_ready_i.value = 0  # back-pressure the result sink
    assert await issue_read(dut, 0xD000, 4, context=0x77)
    await settle(dut)
    await send_cpl(dut, tag=0, status=CPL_UR, byte_count=4, lower_address=0x00)
    await settle(dut)
    # result must be pending and held (not drained)
    await Timer(1, units="ps")
    assert int(dut.result_valid_o.value) == 1, "result must hold while ready is low"
    assert int(dut.result_status_o.value) == CPL_UR, "status held during stall"
    assert int(dut.result_context_o.value) == 0x77, "context held during stall"
    # tag already cleared on capture (UR is terminal), but result not yet consumed
    # now raise ready and confirm it drains within a cycle
    dut.result_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.result_valid_o.value) == 0, "result must drain once ready is raised"
