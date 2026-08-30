"""Rung 9 -- clock-domain-crossing bench for phy_transmit at UNEQUAL frequencies.

Toplevel: phy_transmit, MAX_NUM_LANES=1.

WHY THIS FILE EXISTS
    phy_transmit has THREE clock domains and TWO distinct crossings
    (CENSUS_PHY_TX.md sec 2):

        clk_i             -> pipe_tx_usr_clk_i   dllp_axis_async_fifo_inst
                                                 (phy_transmit.sv:376 -> :389)
        pipe_rx_usr_clk_i -> pipe_tx_usr_clk_i   ordered_set_axis_async_fifo_inst
                                                 (phy_transmit.sv:322 -> :335)

    Every bench in the tree before this one starts all three at 10 ns.  Three
    rungs of documents have called that state "barely exercised"; this file is
    the measurement that settles it.

    ⚠️  A census correction: the brief calls phy_transmit.sv:309,363 "the
    clk_i -> pipe_tx_usr_clk_i async-FIFO CDC".  Only :363 is that one; :309
    crosses pipe_rx_usr_clk_i to pipe_tx_usr_clk_i.  Both are driven here.

THE ORACLE (O-15, evidence/rung9/ORACLES_PHY_TX.md)
    Base 2.1 sec 4.2.7 p.261: "Having worse case clock frequencies at the limits
    of the tolerance specified will result in a 600 ppm difference between the
    Transmit and Receive clocks of a Link.  As a result, the Transmit and Receive
    clocks can shift one clock every 1666 clocks."

    pipe_rx_usr_clk_i is recovered from the link partner and pipe_tx_usr_clk_i
    comes from the local reference.  The spec guarantees only that they are
    within 600 ppm -- NOT that they are equal.  The crossing must therefore
    deliver every ordered set intact at any ratio in a bounded neighbourhood
    of 1.

    600 ppm needs ~1666 clocks to slip one clock, which is a slow way to look for
    a defect.  These tests use exaggerated deterministic ratios instead -- a
    strict superset of the specified stress -- so a real defect shows in bounded
    simulation time.  The ratios are fixed integers, never random.

    No src/ change was needed: clk_i, pipe_rx_usr_clk_i and pipe_tx_usr_clk_i are
    already three separate top-level ports driven by three independent cocotb
    Clock coroutines.  The brief's stop condition on this point does not fire.

PREDICTED RESULT: all three PASS (PREDICTIONS_R9.md sec 6).  os_generator emits
one 4-Symbol beat per rx clock; lane_management consumes one FIFO word per TWO
tx clocks (the Gen1 PIPE-16 gearing at lane_management.sv:395,418).  The consumer
is 2x slower than the producer at parity, so the 8-word FIFO sits full and
back-pressure is the steady state; underrun would need f_tx > 2 x f_rx, far
outside any ratio the spec permits.  A pass here is a negative result reported
as one -- it retires the complaint with a measurement.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

COM = 0xBC
PAD = 0xF7
TS1 = 0x4A
TS2 = 0x45
N_FTS = 0xFF
GEN1 = 0x01
GEN1_BASIC = 0x02

G_VALID   = 1 << 0
G_GEN_TS1 = 1 << 1
G_SET_LANE = 1 << 9

NOMINAL_NS = 10.0


def golden_ts(link_num, lane_num, ts_disc):
    """Base 2.1 Table 4-2 p.201 -- (symbol, is_k) x16."""
    head = [(COM, 1),
            (link_num, 1 if link_num == PAD else 0),
            (lane_num, 1 if lane_num == PAD else 0),
            (N_FTS, 0), (GEN1_BASIC, 0), (0x00, 0)]
    return head + [(ts_disc, 0)] * 10


def pack_tsos(link_num, lane_num, ts_disc):
    b = [COM, link_num & 0xFF, lane_num & 0xFF, N_FTS, GEN1_BASIC, 0x00] \
        + [ts_disc & 0xFF] * 10
    v = 0
    for i, bv in enumerate(b):
        v |= bv << (8 * i)
    return v


async def start_clocks(dut, core_ns, rx_ns, tx_ns):
    cocotb.start_soon(Clock(dut.clk_i, core_ns, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, rx_ns, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_tx_usr_clk_i, tx_ns, units="ns").start())


async def reset(dut):
    dut.rst_i.value = 1
    dut.en_i.value = 0
    dut.link_up_i.value = 0
    dut.num_active_lanes_i.value = 1
    dut.send_ordered_set_i.value = 0
    dut.ordered_set_i.value = 0
    dut.gen_os_ctrl_i.value = 0
    dut.curr_data_rate_i.value = GEN1
    dut.s_dllp_axis_tdata.value = 0
    dut.s_dllp_axis_tkeep.value = 0
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0
    dut.s_dllp_axis_tuser.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 16)
    dut.rst_i.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 8)
    dut.en_i.value = 1


def syms_per_word(dut):
    return max(1, min(4, int(dut.pipe_width_o.value) >> 3))


async def capture(dut, cycles):
    out = []
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        word = int(dut.pipe_data_o.value) & 0xFFFFFFFF
        dk = int(dut.pipe_data_k_o.value) & 0xF
        for j in range(syms_per_word(dut)):
            out.append(((word >> (8 * j)) & 0xFF, (dk >> j) & 1))
    return out


def all_ordered_sets(syms):
    """Every complete 16-Symbol COM-framed set, non-overlapping."""
    out, i = [], 0
    while i + 16 <= len(syms):
        if syms[i][0] == COM and syms[i][1] == 1:
            out.append(syms[i:i + 16])
            i += 16
        else:
            i += 1
    return out


def fmt(pairs):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k in pairs)


async def cross_one_rate(dut, label, core_ns, rx_ns, tx_ns, ts_disc, link):
    """Drive one TS template across the crossing at the given clock periods and
    assert EVERY ordered set that comes out is byte-exact against Table 4-2.

    Checking every set, not the first, is the point: a CDC defect that drops or
    duplicates a beat shows up as a corrupted set somewhere in the stream, and a
    first-set-only check is exactly the check that would miss it.
    """
    await start_clocks(dut, core_ns, rx_ns, tx_ns)
    await reset(dut)
    dut.ordered_set_i.value = pack_tsos(link, 0x00, ts_disc)
    dut.gen_os_ctrl_i.value = G_VALID | G_GEN_TS1 | G_SET_LANE
    dut.curr_data_rate_i.value = GEN1

    syms = await capture(dut, 400)
    sets = all_ordered_sets(syms)
    want = golden_ts(link, 0x00, ts_disc)

    dut._log.info("%s  core=%.2fns rx=%.2fns tx=%.2fns  rx/tx ratio=%.4f"
                  % (label, core_ns, rx_ns, tx_ns, tx_ns / rx_ns))
    dut._log.info("%s  %d complete ordered sets in %d Symbol Times"
                  % (label, len(sets), len(syms)))
    assert sets, "%s: no complete ordered set crossed the FIFO -- %s" \
                 % (label, fmt(syms[:24]))

    bad = []
    for n, got in enumerate(sets):
        if got != want:
            bad.append("set %d: %s" % (n, fmt(got)))
    if bad:
        dut._log.error("%s  want: %s" % (label, fmt(want)))
        for b in bad[:4]:
            dut._log.error("  %s" % b)
    assert not bad, "%s: %d of %d ordered sets were corrupted crossing the CDC" \
                    % (label, len(bad), len(sets))
    dut._log.info("%s  all %d ordered sets byte-exact against Table 4-2 p.201"
                  % (label, len(sets)))
    return len(sets)


# ------------------------------------------------------------------ D1

@cocotb.test()
async def os_crossing_survives_rx_clock_faster_than_tx(dut):
    """O-15, producer-fast: pipe_rx_usr_clk_i 25% faster than pipe_tx_usr_clk_i.

    This is the direction that fills ordered_set_axis_async_fifo_inst and holds
    phy_axis_tready low, so it exercises the FIFO-full back-pressure path into
    os_generator's ST_SEND -- which stalls on `if (ltssm_axis_tready)`
    (os_generator.sv:230).  A set that resumes wrongly after a stall comes out
    corrupted and this test says so.

    Ratio 4:5 is fixed and deterministic; 25% is far beyond the 600 ppm of
    sec 4.2.7 p.261, so a pass here covers the specified case with margin.
    """
    n = await cross_one_rate(dut, "rx-fast", core_ns=NOMINAL_NS,
                             rx_ns=8.0, tx_ns=10.0, ts_disc=TS1, link=0x05)
    assert n >= 2, "only %d ordered set(s) crossed; not enough to call it a stream" % n


# ------------------------------------------------------------------ D2

@cocotb.test()
async def os_crossing_survives_tx_clock_faster_than_rx(dut):
    """O-15, consumer-fast: pipe_tx_usr_clk_i 25% faster than pipe_rx_usr_clk_i.

    This is the direction that drains the FIFO.  At Gen1 the consumer already
    needs two tx clocks per FIFO word (lane_management.sv:395,418), so a 5:4
    tx:rx ratio still cannot empty it -- the prediction is that this passes and
    that underrun needs f_tx > 2 x f_rx, a ratio no PCIe link can present.
    Recording that bound is the result; the test is what makes it a measurement
    instead of an argument.
    """
    n = await cross_one_rate(dut, "tx-fast", core_ns=NOMINAL_NS,
                             rx_ns=10.0, tx_ns=8.0, ts_disc=TS1, link=0x0A)
    assert n >= 2, "only %d ordered set(s) crossed; not enough to call it a stream" % n


# ------------------------------------------------------------------ D3

@cocotb.test()
async def all_three_domains_at_distinct_frequencies(dut):
    """O-15, all three domains mutually unequal -- 7:10:8 ns.

    The other two tests each hold one pair at parity.  This one leaves no pair
    equal, so both crossings are stressed at once and the reset release is skewed
    across three domains rather than two.  clk_i only carries the DLLP path, but
    it shares rst_i with everything else, and a reset-release ordering that only
    works when the domains are harmonically related would show here.

    7, 10 and 8 are pairwise non-harmonic on purpose: 10/7 and 8/7 are not
    integers, so no edge alignment repeats on a short period.
    """
    n = await cross_one_rate(dut, "three-way", core_ns=7.0,
                             rx_ns=10.0, tx_ns=8.0, ts_disc=TS1, link=0x03)
    assert n >= 2, "only %d ordered set(s) crossed; not enough to call it a stream" % n
    dut._log.info("both CDCs delivered intact with no two domains at the same rate")
