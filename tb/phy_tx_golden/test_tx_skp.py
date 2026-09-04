"""Rung 9 -- SKP Ordered Set bench for phy_transmit (Gen1, x1).

Toplevel: phy_transmit, MAX_NUM_LANES=1, with link_up_i RAISED.

⚠️  THIS PATH HAD NEVER EXECUTED.  os_generator's SKP timer advances only under
    `if (link_up_i)` (os_generator.sv:139-141) and is tested only in ST_IDLE
    (os_generator.sv:158).  All three pre-Rung-9 TX benches hold link_up_i at 0
    and never raise it (test_phy_transmit_tx.py:84, ..._x4.py:80,
    test_os_generator_k_mask.py:64), and os_generator is elaborated by exactly
    those three gate rows.  ST_SKP was therefore dead in all 71 rows of the
    03cea650 baseline.  Every assertion in this file is the first of its kind.

ORACLES (evidence/rung9/ORACLES_PHY_TX.md)
    O-7  "The transmitted SKP Ordered Set is: one COM Symbol followed by three
         consecutive SKP Symbols."         Base 2.1 sec 4.2.7.1 p.261
    O-8  "The SKP Ordered Set shall be scheduled for insertion at an interval
         between 1180 and 1538 Symbol Times."   Base 2.1 sec 4.2.7.1 p.261
    O-7b "Scheduled SKP Ordered Sets shall be transmitted if a packet or Ordered
         Set is not already in progress."       Base 2.1 sec 4.2.7.1 p.261
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

COM = 0xBC          # K28.5  (pkg:100)
SKP = 0x1C          # K28.0  (pkg:106)
TS1 = 0x4A
PAD = 0xF7
N_FTS = 0xFF
GEN1 = 0x01
GEN1_BASIC = 0x02

G_VALID   = 1 << 0
G_GEN_TS1 = 1 << 1
G_SET_LANE = 1 << 9

# Base 2.1 sec 4.2.7.1 p.261
SKP_MIN_SYMBOL_TIMES = 1180
SKP_MAX_SYMBOL_TIMES = 1538


def pack_tsos(link_num=PAD, lane_num=PAD, ts_disc=TS1):
    b = [COM, link_num & 0xFF, lane_num & 0xFF, N_FTS, GEN1_BASIC, 0x00] \
        + [ts_disc & 0xFF] * 10
    v = 0
    for i, bv in enumerate(b):
        v |= bv << (8 * i)
    return v


async def start_clocks(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_tx_usr_clk_i, 10, units="ns").start())


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
    await ClockCycles(dut.pipe_tx_usr_clk_i, 8)
    dut.rst_i.value = 0
    await ClockCycles(dut.pipe_tx_usr_clk_i, 4)
    dut.en_i.value = 1


def syms_per_word(dut):
    """Symbols per PIPE word, read from the DUT's own pipe_width_o.  At Gen1 this
    is 16 >> 3 = 2, so one pipe_tx_usr_clk cycle is TWO Symbol Times -- the
    conversion factor the interval assertion needs, and the reason it is read
    rather than hardcoded."""
    return max(1, min(4, int(dut.pipe_width_o.value) >> 3))


async def collect(dut, cycles):
    """(symbol, is_k, symbol_time) for lane 0.  symbol_time counts Symbol Times
    from the start of collection, using the DUT's PIPE width."""
    out = []
    t = 0
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        word = int(dut.pipe_data_o.value) & 0xFFFFFFFF
        dk = int(dut.pipe_data_k_o.value) & 0xF
        n = syms_per_word(dut)
        for j in range(n):
            out.append(((word >> (8 * j)) & 0xFF, (dk >> j) & 1, t))
            t += 1
    return out


def skp_starts(stream):
    """Symbol-time index of every COM that begins a COM,SKP,SKP,SKP group."""
    hits = []
    for i in range(len(stream) - 3):
        s0, k0, t0 = stream[i]
        if s0 == COM and k0 == 1:
            nxt = [(s, k) for s, k, _ in stream[i + 1:i + 4]]
            if nxt == [(SKP, 1)] * 3:
                hits.append(t0)
    return hits


def fmt(stream, a, b):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k, _ in stream[a:b])


# ------------------------------------------------------------------ O-7

@cocotb.test()
async def skp_ordered_set_composition(dut):
    """O-7: Base 2.1 sec 4.2.7.1 p.261 -- "The transmitted SKP Ordered Set is:
    one COM Symbol followed by three consecutive SKP Symbols."

    COM is K28.5 = BCh, SKP is K28.0 = 1Ch (pcie_phy_pkg.sv:100,106).  All four
    are K codes, so sec 4.2.3 p.199 keeps them unscrambled and they must appear
    literally on the wire.

    First execution of ST_SKP in the project's history.
    """
    await start_clocks(dut)
    await reset(dut)
    dut.gen_os_ctrl_i.value = 0          # park os_generator in ST_IDLE
    dut.link_up_i.value = 1              # arm os_generator.sv:139-141

    # ⚠️ Window WIDENED in FA-5b -- a TEST change forced by a DESIGN fix, not a
    # fix to make a row pass.  SS54 #9(C) moved the SKP interval from 354 to a
    # spec-legal 1358 Symbol Times, so the old 600-clock (1200 Symbol Time)
    # window no longer reaches the first SKP.  PREDICTIONS_34B.md C3
    # pre-registered this row going red for want of window.
    #
    # ⚠️ AND the first widening -- one interval plus margin -- was STILL too
    # short, which is the more useful half of the lesson.  The first SKP does not
    # arrive one interval after link_up_i; it arrives about THREE.  That was
    # already visible in the pre-fix numbers had anyone looked: at 354 the first
    # landed at Symbol Time 1080 ~= 3 x 354, and the old 1200-Symbol-Time window
    # caught it only just.  At 1358 the first lands at 4092 ~= 3 x 1358 -- the
    # same structure, scaled.
    #
    # So the budget is taken from the SIBLING row that is proven to reach two
    # SKPs (the O-8 interval row uses four spec-maximum intervals), rather than
    # invented here.  Derived from the spec bound, so it stays correct for any
    # conforming constant.
    cycles = 4 * SKP_MAX_SYMBOL_TIMES // 2 + 64     # 3140 clocks = 6280 Symbol Times
    stream = await collect(dut, cycles)
    hits = skp_starts(stream)
    assert hits, "no COM,SKP,SKP,SKP group in %d Symbol Times after link_up_i " \
                 "(os_generator.sv:158 fires at 176 counts): %s" \
                 % (len(stream), fmt(stream, 0, 24))
    i = next(n for n, (s, k, t) in enumerate(stream) if t == hits[0])
    dut._log.info("SKP Ordered Set at Symbol Time %d: %s" % (hits[0], fmt(stream, i, i + 4)))
    got = [(s, k) for s, k, _ in stream[i:i + 4]]
    want = [(COM, 1), (SKP, 1), (SKP, 1), (SKP, 1)]
    assert got == want, "SKP OS is %s, sec 4.2.7.1 p.261 wants bcK 1cK 1cK 1cK" \
                        % fmt(stream, i, i + 4)
    dut._log.info("ST_SKP reached and its composition matches sec 4.2.7.1 p.261")


# ------------------------------------------------------------------ O-8

@cocotb.test()
async def skp_scheduling_interval_is_1180_to_1538_symbol_times(dut):
    """O-8: Base 2.1 sec 4.2.7.1 p.261 -- "The SKP Ordered Set shall be scheduled
    for insertion at an interval between 1180 and 1538 Symbol Times."

    Base 3.0 repeats the same two numbers; MindShare p.391 states them and
    defines the unit ("a Symbol time is the time required to send one Symbol and
    is 10 bit times, so at 2.5 GT/s, a Symbol time is 4ns").

    The interval is MEASURED here -- SKP COM to SKP COM on the wire, converted to
    Symbol Times through the DUT's own pipe_width_o -- and then compared to the
    window.  Nothing is hardcoded except the two spec numbers.

    WAS a predicted divergence (Rung 9, PREDICTIONS_R9.md sec 3, O-8) and carried
    expect_fail until FA-5b.  os_generator fired at 0xB0 = 176 counts of
    pipe_rx_usr_clk_i, scheduling one SKP every 354 Symbol Times -- roughly 3.3x
    more often than the 1180 floor.  Over-frequent SKPs are not a silent
    inefficiency: every one costs four Symbol Times of link bandwidth, and
    sec 4.2.7.2 p.261 only obliges a Receiver to tolerate an AVERAGE interval
    "between 1180 to 1538 Symbol Times".

    SS54 #9(C) moved the constant to 0x2A6 = 678, solved from the MEASURED
    relation interval = 2N + 2 (two Symbol Times per Gen1 PIPE-16 clock, plus one
    clock for ST_SKP itself).  Measured after the fix: a single interval of
    exactly 1358 Symbol Times, the window centre, predicted before the run.

    ⚠️ Rung 9's docstring said "about 356"; the artifact says 354, eight times
    identically.  The register's 354 was right.
    """
    await start_clocks(dut)
    await reset(dut)
    dut.gen_os_ctrl_i.value = 0
    dut.link_up_i.value = 1

    # Two SKPs are needed for one interval.  Bound the wait at four nominal
    # spec-maximum intervals so a design that never emits one fails fast.
    budget_symbol_times = 4 * SKP_MAX_SYMBOL_TIMES
    cycles = budget_symbol_times // 2 + 64
    stream = await collect(dut, cycles)
    hits = skp_starts(stream)
    dut._log.info("SKP Ordered Sets at Symbol Times: %s (window %d Symbol Times)"
                  % (hits[:8], len(stream)))
    assert len(hits) >= 2, \
        "need two SKP Ordered Sets to measure an interval; saw %d in %d Symbol Times" \
        % (len(hits), len(stream))

    intervals = [b - a for a, b in zip(hits, hits[1:])]
    measured = intervals[0]
    dut._log.info("measured SKP intervals (Symbol Times): %s" % intervals)
    dut._log.info("spec window sec 4.2.7.1 p.261: %d .. %d Symbol Times"
                  % (SKP_MIN_SYMBOL_TIMES, SKP_MAX_SYMBOL_TIMES))
    assert SKP_MIN_SYMBOL_TIMES <= measured <= SKP_MAX_SYMBOL_TIMES, \
        "SKP scheduled every %d Symbol Times; sec 4.2.7.1 p.261 requires %d..%d " \
        "(os_generator.sv:158 counts to 0xB0 = 176 clocks, and a Gen1 PIPE-16 " \
        "clock is %d Symbol Times)" \
        % (measured, SKP_MIN_SYMBOL_TIMES, SKP_MAX_SYMBOL_TIMES, syms_per_word(dut))


# ------------------------------------------------------------------ O-7b

@cocotb.test()
async def skp_does_not_interrupt_an_ordered_set(dut):
    """O-7b: Base 2.1 sec 4.2.7.1 p.261 -- "Scheduled SKP Ordered Sets shall be
    transmitted if a packet or Ordered Set is not already in progress, otherwise
    they are accumulated and then inserted consecutively at the next packet or
    Ordered Set boundary."

    A SKP that lands inside a TS Ordered Set destroys it: the receiver's
    ordered-set handler is matching 16 consecutive Symbols from a COM, and four
    foreign Symbols in the middle make the TS unrecognisable.  So with link_up_i
    raised AND a TS1 stream running, no COM,SKP,SKP,SKP group may appear between
    a TS COM and its Symbol 15.

    This passes because os_generator tests skp_cnt only in ST_IDLE
    (os_generator.sv:158) and so structurally cannot pre-empt ST_SEND.

    The test also LOGS whether any SKP was emitted during the stream at all.
    That number is evidence for a separate observation recorded in
    FINDINGS_PHY_TX.md: the ST_SEND streaming hack (os_generator.sv:244-249)
    keeps the FSM out of ST_IDLE while the LTSSM holds a steady command, so the
    "accumulated and then inserted at the next Ordered Set boundary" half of the
    rule has no implementation.  It is logged, not asserted -- the assertion
    here is the half the spec sentence puts first.
    """
    await start_clocks(dut)
    await reset(dut)
    dut.link_up_i.value = 1
    dut.ordered_set_i.value = pack_tsos(link_num=0x05, lane_num=0x00)
    dut.gen_os_ctrl_i.value = G_VALID | G_GEN_TS1 | G_SET_LANE

    stream = await collect(dut, 700)
    skps = skp_starts(stream)

    # Every TS Ordered Set is a K-coded COM followed by 15 symbols that are not
    # a SKP group.  Walk the stream and check no SKP start falls strictly inside
    # one of those 16-Symbol windows.
    ts_starts = []
    for i in range(len(stream) - 16):
        s, k, t = stream[i]
        if s == COM and k == 1 and stream[i + 1][0] != SKP:
            ts_starts.append(t)

    violations = [(ts, sk) for ts in ts_starts for sk in skps if ts < sk < ts + 16]
    dut._log.info("TS Ordered Sets seen: %d   SKP Ordered Sets seen: %d"
                  % (len(ts_starts), len(skps)))
    dut._log.info("SKP groups landing inside a TS Ordered Set: %d" % len(violations))
    if not skps:
        dut._log.info("NOTE: no SKP was emitted during %d Symbol Times of continuous "
                      "TS1.  sec 4.2.7.1 p.261 also requires scheduled SKPs to be "
                      "'accumulated and then inserted consecutively at the next "
                      "packet or Ordered Set boundary'; recorded in FINDINGS_PHY_TX.md, "
                      "not asserted here." % len(stream))
    assert ts_starts, "no TS Ordered Set on the wire -- stimulus did not take"
    assert not violations, \
        "sec 4.2.7.1 p.261: a SKP Ordered Set was inserted inside an Ordered Set " \
        "already in progress at Symbol Times %s" % violations[:4]
