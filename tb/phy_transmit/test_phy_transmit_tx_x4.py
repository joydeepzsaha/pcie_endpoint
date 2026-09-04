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


TSOS_WIDTH = 128


def pack_os_array(per_lane):
    """Pack a per-lane list of pcie_tsos_t ints into the ordered_set_i array
    (lane l at bits [l*128 +: 128], lane 0 = LSB)."""
    v = 0
    for l, os in enumerate(per_lane):
        v |= (os & ((1 << TSOS_WIDTH) - 1)) << (l * TSOS_WIDTH)
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
    # ordered_set_i is now per-lane (Decision 1): drive each lane its own TS1
    # with lane_num = its index, mimicking the LTSSM RC output. (Under the
    # Stage-1 positional stamp this is redundant; after the stamp is removed it
    # is what carries the lane numbers.)
    dut.ordered_set_i.value = pack_os_array(
        [pack_tsos(link_num=link, lane_num=l, ts_disc=TS1)
         for l in range(NUM_LANES)])
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
async def x4_all_lanes_live(dut):
    """Every active lane must frame a K-coded COM on the wire. Before the
    lane_management K-mask fix, lanes 1-3 had has_COM=False (their COM was
    scrambled because K-mask=0); after it, all four are live. Logs each lane's
    signature so a future x4 regression stays distinguishable."""
    await start_clocks(dut)
    await reset(dut)
    await drive_ts1(dut, 0x05)
    lanes = await capture_lanes(dut, 80)
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        has_com = any(s == COM and k == 1 for s, k in lanes[lane])
        dut._log.info("x4 lane %d: has_COM=%s  decoded=%s"
                      % (lane, has_com, _fmt(os) if os else "<none>"))
        assert has_com, "lane %d has no K-coded COM (K-mask dropped?)" % lane


# Real pass now that BOTH x4 collapses are fixed: the Hop-9 FIFO width
# (fb84c1e, lands per-lane DATA) and the lane_management:405 per-lane K-mask
# broadcast (lands per-lane COM bypass). Predicted per-lane output with link
# 0x05: each lane L emits  bc(K) 05 <lane=L> ff 02 00 4a*10  -- lanes 1-3 go
# from the pre-fix has_COM=False to this, differing from lane 0 only in the
# lane_num byte.
@cocotb.test()
async def x4_all_lanes_ts1(dut):
    """All four lanes must each emit a valid TS1 with lane_num = lane index."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x05
    await drive_ts1(dut, link)
    lanes = await capture_lanes(dut, 80)
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        dut._log.info("x4 lane %d OS: %s" % (lane, _fmt(os) if os else "<none>"))
        check_lane_ts1(lane, os, link)


# ACCEPTANCE GATE for Decision 1 (LTSSM-authoritative lane numbering). A
# steady-state x4 pass does NOT distinguish "echo preserved" from "positional
# stamp" -- both emit 0,1,2,3 when every lane is assigned its index. This test
# drives a MIXED pattern that only the passthrough gets right: lane 2 = PAD
# (unassigned, as during mid-negotiation), lanes 0/1/3 = assigned to their
# numbers, with set_lane HIGH (the state where the old stamp fired).
#
# Prediction (stated before running, per falsifiability):
#   lane 0 -> bc(K) 05 00 ff 02 00 4a*10   (lane_num 0x00)
#   lane 1 -> bc(K) 05 01 ff 02 00 4a*10   (lane_num 0x01)
#   lane 2 -> bc(K) 05 f7 ff 02 00 4a*10   (lane_num PAD 0xf7, NOT re-stamped 02)
#   lane 3 -> bc(K) 05 03 ff 02 00 4a*10   (lane_num 0x03)
# The removed positional stamp would have forced 00/01/02/03 -> lane 2 = 02 and
# this test would FAIL. Passthrough emits the mixed pattern -> passes.
@cocotb.test()
async def x4_mixed_pad_echo(dut):
    """Decision-1 proof: per-lane lane_num passes through unchanged, incl. PAD
    on an unassigned lane -- no positional re-stamp."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x05
    expected = [0x00, 0x01, PAD, 0x03]   # lane 2 unassigned (PAD)
    dut.ordered_set_i.value = pack_os_array(
        [pack_tsos(link_num=link, lane_num=expected[l], ts_disc=TS1)
         for l in range(NUM_LANES)])
    dut.curr_data_rate_i.value = GEN1
    # set_lane HIGH: the exact control state under which os_generator used to
    # overwrite lane_num with the positional index.
    dut.gen_os_ctrl_i.value = G_VALID | G_GEN_TS1 | G_SET_LANE
    dut.send_ordered_set_i.value = 0

    lanes = await capture_lanes(dut, 80)
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        dut._log.info("x4 mixed-PAD lane %d OS: %s"
                      % (lane, _fmt(os) if os else "<none>"))
        assert os is not None, "lane %d: no COM-framed ordered set" % lane
        data = [s for s, k in os]
        assert data[0] == COM and os[0][1] == 1, "lane %d: no K-COM" % lane
        assert data[1] == link, "lane %d link: %02x" % (lane, data[1])
        assert data[2] == expected[lane], (
            "lane %d lane_num: got %02x want %02x (re-stamp bug?)"
            % (lane, data[2], expected[lane]))
        assert all(d == TS1 for d in data[6:16]), "lane %d TS1 disc" % lane
    # Explicit anti-stamp assertion: lane 2 must be PAD, never its index.
    os2 = find_ordered_set(lanes[2])
    assert os2[2][0] == PAD, "lane 2 re-stamped to index instead of PAD"


# ------------------------------------------------------ fix-arc 4, tracker §54 #5

@cocotb.test()
async def x4_per_lane_k_flags_on_symbols_1_and_2(dut):
    """The K-mask must be PER LANE at Symbols 1 and 2, observed at the PIPE pins.

    Base 2.1 Table 4-2 p.201 gives Symbol 1 as the Link Number and Symbol 2 as
    the Lane Number, each "D0.0 - D31.0, K23.7" -- so each is a control code iff
    THAT Lane's byte is PAD.  §4.2.6.3.2.2 p.231 makes the PAD mandatory on the
    unassigned Lanes of an Upstream Port ("Remaining Lanes must transmit TS1
    Ordered Sets with Link and Lane numbers set to PAD"), which is the normal
    state throughout Configuration.

    ⚠️ WHY THIS ROW EXISTS AT ALL.  os_generator's own x4 bench already scores
    both Symbols, but it observes m_axis_tuser at the UNIT boundary.  Nothing in
    the repository observed per-lane K at the INTEGRATED boundary, so
    lane_management.sv:413 -- the broadcast source index, the fourth of §54 #5's
    coordinated edits -- had no witness at all, and a mutant reverting it alone
    would have survived every one of the 97 gate targets.  Predicted as T6/MB4 in
    pcie_docs/evidence/fix-arc-4/PREDICTIONS_2.md before this row was written.

    That is also why the observation point is pipe_data_k_o rather than any
    internal signal: it is downstream of BOTH the os_generator packing and the
    lane_management broadcast, so it is the only place where the two halves of
    the defect are visible together.

    PREDICTED DIVERGENCE.  Today os_generator emits one USER_WIDTH-wide mask into
    tuser's lane-0 slice (os_generator.sv:237 assigns a USER_WIDTH-wide value to
    a USER_WIDTH*MAX_NUM_LANES bus, so lanes 1-3 zero-extend) and
    lane_management.sv:413 sources every lane from that one slice.  Symbol 1's
    bit is the OR of PAD-ness across all lanes (os_generator.sv:180) and Symbol
    2's is lane 0's alone (:213).  Neither is per-lane.
    """
    await start_clocks(dut)
    await reset(dut)

    link = 0x05
    # Lane 2 unassigned: PAD in BOTH Symbol 1 and Symbol 2, the others real.
    # Lane-distinct by construction, so a broadcast mask cannot pass by symmetry.
    link_per_lane = [link, link, PAD, link]
    lane_per_lane = [0x00, 0x01, PAD, 0x03]
    dut.ordered_set_i.value = pack_os_array(
        [pack_tsos(link_num=link_per_lane[l], lane_num=lane_per_lane[l], ts_disc=TS1)
         for l in range(NUM_LANES)])
    dut.curr_data_rate_i.value = GEN1
    dut.gen_os_ctrl_i.value = G_VALID | G_GEN_TS1 | G_SET_LANE
    dut.send_ordered_set_i.value = 0

    lanes = await capture_lanes(dut, 80)
    bad = []
    for lane in range(NUM_LANES):
        os = find_ordered_set(lanes[lane])
        assert os is not None, "lane %d: no COM-framed ordered set" % lane
        dut._log.info("lane %d OS: %s" % (lane, _fmt(os)))
        for sym, driven in ((1, link_per_lane[lane]), (2, lane_per_lane[lane])):
            got_byte, got_k = os[sym]
            assert got_byte == driven, (
                "lane %d Symbol %d byte is 0x%02x, expected the driven 0x%02x"
                % (lane, sym, got_byte, driven))
            want_k = 1 if driven == PAD else 0
            if got_k != want_k:
                bad.append("lane %d Symbol %d = 0x%02x marked K=%d, Table 4-2 "
                           "p.201 requires K=%d" % (lane, sym, got_byte, got_k, want_k))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, ("%d per-lane K-flag violations at the PIPE boundary "
                     "(Base 2.1 Table 4-2 p.201 / §4.2.6.3.2.2 p.231)" % len(bad))
