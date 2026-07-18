"""
x4 TX unit testbench for phy_transmit -- Phase 4b step A/B (observe-first).

Toplevel: phy_transmit (MAX_NUM_LANES=4). Drives the same TS1 template as the
x1 golden and decodes the per-lane PIPE output for all four lanes.

WHY THIS EXISTS: the ordered_set_axis_async_fifo inside phy_transmit is
instantiated DATA_WIDTH=32 (phy_transmit.sv:300), but its s_axis_tdata is the
full per-lane bus phy_axis_tdata = 32*MAX_NUM_LANES wide. At x1 32==32 (no-op);
at x4 the upper 96 bits (lanes 1-3) are truncated at the FIFO input, so lanes
1-3 lose their ordered set. This bench captures that truncation as an OBSERVED,
predicted failure before the width fix -- see `x4_all_lanes_ts1`
(expect_fail=True until the fix lands).

Bench drives only phy_transmit ports; never touches RTL internals.

SCOPE NOTE (Decision 1): os_generator stamps lane_num = i positionally, so a
green per-lane lane-number assertion here does NOT prove the LTSSM reactive
PAD-until-assigned echo survives -- that echo lives in the LTSSM, absent from
this unit bench. This bench cannot clear Decision 1; a mixed PAD/assigned
per-lane-input test (only possible once ordered_set_i goes per-lane) can.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

NUM_LANES = 4

# ---- constants from src/packages/pcie_phy_pkg.sv (same as x1 golden) ----
COM = 0xBC
PAD = 0xF7
TS1 = 0x4A
GEN1 = 0x01
GEN1_BASIC = 0x02
N_FTS = 0xFF

# ---- gen_os_struct_t control bits (LSB = valid) ----
G_VALID   = 1 << 0
G_GEN_TS1 = 1 << 1
G_SET_LANE = 1 << 9


def pack_tsos(link_num=PAD, lane_num=PAD, rate_id=GEN1_BASIC, ts_disc=TS1,
              com=COM, n_fts=N_FTS, train_ctrl=0x00):
    """One pcie_tsos_t (128-bit) as gen_ts_os(gen1, TSOS_, ...). Byte offsets:
    com@0 link@8 lane@16 n_fts@24 rate_id@32 train_ctrl@40 ts_s6@48.. ts_id@80.."""
    b = [0] * 16
    b[0], b[1], b[2], b[3], b[4], b[5] = (
        com, link_num & 0xFF, lane_num & 0xFF, n_fts & 0xFF,
        rate_id & 0xFF, train_ctrl & 0xFF)
    for i in range(6, 16):
        b[i] = ts_disc & 0xFF
    v = 0
    for i, bv in enumerate(b):
        v |= (bv & 0xFF) << (8 * i)
    return v


async def start_clocks(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_tx_usr_clk_i, 10, units="ns").start())


async def reset(dut):
    dut.rst_i.value = 1
    dut.en_i.value = 0
    dut.link_up_i.value = 0
    dut.num_active_lanes_i.value = NUM_LANES
    dut.send_ordered_set_i.value = 0
    dut.ordered_set_i.value = 0
    dut.gen_os_ctrl_i.value = 0
    dut.curr_data_rate_i.value = GEN1
    dut.s_dllp_axis_tdata.value = 0
    dut.s_dllp_axis_tkeep.value = 0
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0
    dut.s_dllp_axis_tuser.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 8)
    dut.rst_i.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 4)
    dut.en_i.value = 1


def _syms_per_word(dut):
    try:
        w = int(dut.pipe_width_o.value)
    except Exception:
        w = 16
    return max(1, min(4, w >> 3))


async def capture_lanes(dut, cycles):
    """Per-lane (symbol, is_k) streams. pipe_data_o is 32*NUM_LANES wide;
    lane L occupies bits [L*32 +: 32], data_k [L*4 +: 4], valid bit L."""
    streams = [[] for _ in range(NUM_LANES)]
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        data = int(dut.pipe_data_o.value)
        dk = int(dut.pipe_data_k_o.value)
        dv = int(dut.pipe_data_valid_o.value)
        spw = _syms_per_word(dut)
        for lane in range(NUM_LANES):
            if (dv >> lane) & 0x1:
                word = (data >> (lane * 32)) & 0xFFFFFFFF
                k4 = (dk >> (lane * 4)) & 0xF
                for j in range(spw):
                    streams[lane].append(((word >> (8 * j)) & 0xFF, (k4 >> j) & 0x1))
    return streams


def find_ordered_set(syms):
    for i, (s, k) in enumerate(syms):
        if s == COM and k == 1 and i + 16 <= len(syms):
            return syms[i:i + 16]
    return None


def _fmt(pairs):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k in pairs)


async def drive_ts1(dut, link):
    dut.ordered_set_i.value = pack_tsos(link_num=link, lane_num=0, ts_disc=TS1)
    dut.curr_data_rate_i.value = GEN1
    dut.gen_os_ctrl_i.value = G_VALID | G_GEN_TS1 | G_SET_LANE
    dut.send_ordered_set_i.value = 0


def check_lane_ts1(lane, os_pairs, link):
    """Assert one lane's ordered set is a well-formed TS1 with lane_num=index."""
    assert os_pairs is not None, "lane %d: no COM-framed ordered set" % lane
    data = [s for s, k in os_pairs]
    kbit = [k for s, k in os_pairs]
    assert kbit[0] == 1 and data[0] == COM, "lane %d: no K-COM start" % lane
    assert data[1] == link, "lane %d link_num: got %02x want %02x" % (lane, data[1], link)
    assert data[2] == lane, "lane %d lane_num: got %02x want %02x" % (lane, data[2], lane)
    assert data[3] == N_FTS, "lane %d n_fts: got %02x" % (lane, data[3])
    assert data[4] == GEN1_BASIC, "lane %d rate_id: got %02x" % (lane, data[4])
    assert all(d == TS1 for d in data[6:16]), "lane %d TS1 disc: %s" % (lane, _fmt(os_pairs[6:16]))


@cocotb.test()
async def x4_lane0_ok(dut):
    """Lane 0 must always carry a correct TS1 -- before AND after the FIFO fix
    (the truncation keeps lane 0's 32-bit slice). Guards against the fix
    breaking the one lane that worked."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x05
    await drive_ts1(dut, link)
    lanes = await capture_lanes(dut, 80)
    os0 = find_ordered_set(lanes[0])
    dut._log.info("x4 lane 0 OS: %s" % (_fmt(os0) if os0 else "<none>"))
    check_lane_ts1(0, os0, link)


@cocotb.test()
async def x4_truncation_signature(dut):
    """DIAGNOSTIC (always passes): record exactly what lanes 1-3 emit on the
    CURRENT (unfixed) RTL, so a later real x4 regression is distinguishable
    from this known truncation. Not an assertion of correctness."""
    await start_clocks(dut)
    await reset(dut)
    await drive_ts1(dut, 0x05)
    lanes = await capture_lanes(dut, 80)
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        has_com = any(s == COM and k == 1 for s, k in lanes[lane])
        dut._log.info("x4 lane %d: has_COM=%s  first16=%s"
                      % (lane, has_com, _fmt(lanes[lane][:16])))
        if os:
            dut._log.info("x4 lane %d decoded OS: %s" % (lane, _fmt(os)))


# Step A: expect_fail=True -- current RTL truncates lanes 1-3 at the OS FIFO
# (Hop 9). Step B flips this to expect_fail=False once the FIFO DATA_WIDTH is
# widened to 32*MAX_NUM_LANES.
@cocotb.test(expect_fail=True)
async def x4_all_lanes_ts1(dut):
    """All four lanes must each emit a valid TS1 with lane_num = lane index.
    FAILS on current RTL (lanes 1-3 dropped by the 32-bit OS FIFO); PASSES once
    the FIFO width fix lands."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x05
    await drive_ts1(dut, link)
    lanes = await capture_lanes(dut, 80)
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        dut._log.info("x4 lane %d OS: %s" % (lane, _fmt(os) if os else "<none>"))
        check_lane_ts1(lane, os, link)
