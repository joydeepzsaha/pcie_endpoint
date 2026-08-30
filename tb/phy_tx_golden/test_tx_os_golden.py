"""Rung 9 -- spec-golden ordered-set bench for phy_transmit (Gen1, x1).

Toplevel: phy_transmit, MAX_NUM_LANES=1.  This is the closure bench: the ordered
set travels os_generator -> ordered_set_axis_async_fifo -> lane_management ->
scrambler -> PIPE, and every symbol is checked against a packer built HERE from
the Base 2.1 tables.

WHY THIS IS NOT test_phy_transmit_tx.py
    That file (Rung 2, inherited) says so itself: "Empirically established
    contract (see the golden dumps each test logs)".  Its expectations were read
    off the DUT.  This file's expectations come from Table 4-2 p.201, Table 4-3
    p.203, Table 4-4 p.205 and sec 4.2.2 p.194 and would have been written
    identically if the RTL did not exist.  Both are kept: theirs is a
    regression anchor, this is an oracle.

ORACLES (evidence/rung9/ORACLES_PHY_TX.md)
    O-1   TS1 = COM, Link, Lane, N_FTS, RateID, TrainCtrl, D10.2 x10
          (Base 2.1 Table 4-2 p.201-202; D10.2 = 4Ah)
    O-2   TS2 = same head, D5.2 x10  (Table 4-3 p.203-204; D5.2 = 45h)
    O-6   EIOS = COM IDL IDL IDL, all K  (sec 4.2.4.2 + Table 4-4 p.205)
    O-10  Logical Idle = data byte 00h, SCRAMBLED  (sec 4.2.2 p.194-195)
    O-14  K codes are never scrambled; D codes inside a TS Ordered Set are not
          scrambled either  (sec 4.2.3 p.198-199)
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

# ---- pcie_phy_pkg.sv ----
COM = 0xBC          # K28.5  (pkg:100)
IDL = 0x7C          # K28.3  (pkg:108)
PAD = 0xF7          # K23.7  (pkg:35)
TS1 = 0x4A          # D10.2  (pkg:32)
TS2 = 0x45          # D5.2   (pkg:33)
N_FTS = 0xFF        # gen_ts_os sets n_fts = '1  (pkg:409)
GEN1 = 0x01         # rate_speed_e.gen1
GEN1_BASIC = 0x02   # rate_id_t'(gen1_basic)

# gen_os_struct_t control bits, LSB = valid (pkg:269-284)
G_VALID    = 1 << 0
G_GEN_TS1  = 1 << 1
G_GEN_TS2  = 1 << 2
G_GEN_EIOS = 1 << 5
G_GEN_IDLE = 1 << 7
G_SET_LANE = 1 << 9


def golden_ts(link_num, lane_num, ts_disc, n_fts=N_FTS, rate_id=GEN1_BASIC,
              train_ctrl=0x00):
    """The 16 Symbols of a TS Ordered Set, straight off Base 2.1 Table 4-2 p.201.

    Returns a list of (symbol, is_k) pairs -- the K column comes from the table's
    "Encoded Values" text, not from the RTL: Symbol 0 is K28.5 so K=1; Symbols 1
    and 2 are "D0.0-D31.x, K23.7" so K=1 exactly when the byte is PAD; Symbols
    3-15 have no K code in their encoded-value list, so K=0 always.
    """
    body = [link_num, lane_num, n_fts, rate_id, train_ctrl] + [ts_disc] * 10
    syms = [(COM, 1)]
    syms.append((link_num, 1 if link_num == PAD else 0))
    syms.append((lane_num, 1 if lane_num == PAD else 0))
    syms += [(b, 0) for b in body[2:]]
    assert len(syms) == 16
    return syms


def golden_eios_group():
    """Base 2.1 Table 4-4 p.205: Symbols 0-3 = K28.5, K28.3, K28.3, K28.3.
    All four are K codes, so none of them is scrambled (sec 4.2.3 p.199)."""
    return [(COM, 1), (IDL, 1), (IDL, 1), (IDL, 1)]


def pack_tsos(link_num=PAD, lane_num=PAD, ts_disc=TS1, n_fts=N_FTS,
              rate_id=GEN1_BASIC, train_ctrl=0x00, com=COM):
    """One pcie_tsos_t (128 bits).  com is the LSB byte (pkg:254-266)."""
    b = [com, link_num & 0xFF, lane_num & 0xFF, n_fts & 0xFF,
         rate_id & 0xFF, train_ctrl & 0xFF] + [ts_disc & 0xFF] * 10
    v = 0
    for i, bv in enumerate(b):
        v |= (bv & 0xFF) << (8 * i)
    return v


def pack_eios():
    """The Gen1 EIOS template as pcie_phy_pkg::gen_eios builds it (pkg:653-668):
    every 4th Symbol COM, the rest IDL -- i.e. Table 4-4's four Symbols, four
    times over, because os_generator streams a fixed 16 Symbols (os_pkt_cnt = 3,
    os_generator.sv:174)."""
    v = 0
    for i in range(16):
        v |= (COM if (i & 3) == 0 else IDL) << (8 * i)
    return v


async def start_clocks(dut, rx_ns=10.0, tx_ns=10.0, core_ns=10.0):
    cocotb.start_soon(Clock(dut.clk_i, core_ns, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_rx_usr_clk_i, rx_ns, units="ns").start())
    cocotb.start_soon(Clock(dut.pipe_tx_usr_clk_i, tx_ns, units="ns").start())


async def reset(dut, link_up=0):
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
    dut.link_up_i.value = link_up


def syms_per_word(dut):
    """Symbols carried per 32-bit PIPE word = pipe_width_o >> 3.  Read from the
    DUT so the bench follows the rate's PIPE width instead of hardcoding 2."""
    return max(1, min(4, int(dut.pipe_width_o.value) >> 3))


async def capture(dut, cycles):
    """Collect (symbol, is_k) from lane 0's PIPE output.

    NOTE pipe_data_valid_o is NOT a gate here.  lane_management.sv:571 ties
    data_valid_o to '1 unconditionally, so the signal is constant 1 after reset
    and carries no information (see CENSUS_PHY_TX.md sec 5).  Everything the
    Transmitter puts on the wire is captured and the ordered set is located by
    its COM frame.
    """
    out = []
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        word = int(dut.pipe_data_o.value) & 0xFFFFFFFF
        dk = int(dut.pipe_data_k_o.value) & 0xF
        for j in range(syms_per_word(dut)):
            out.append(((word >> (8 * j)) & 0xFF, (dk >> j) & 1))
    return out


def find_os(syms, n=16):
    """First K-coded COM with at least n symbols after it."""
    for i, (s, k) in enumerate(syms):
        if s == COM and k == 1 and i + n <= len(syms):
            return syms[i:i + n]
    return None


def fmt(pairs):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k in pairs)


async def drive(dut, ctrl, tsos):
    dut.ordered_set_i.value = tsos
    dut.curr_data_rate_i.value = GEN1
    dut.gen_os_ctrl_i.value = ctrl
    dut.send_ordered_set_i.value = 0


def compare(dut, label, got, want):
    """Symbol-by-symbol and K-by-K against the golden list.  Returns a list of
    complaints rather than asserting, so one run reports every divergence."""
    bad = []
    dut._log.info("%-8s got : %s" % (label, fmt(got)))
    dut._log.info("%-8s want: %s" % ("", fmt(want)))
    for i, ((gs, gk), (ws, wk)) in enumerate(zip(got, want)):
        if gs != ws:
            bad.append("Symbol %d byte 0x%02x, table wants 0x%02x" % (i, gs, ws))
        if gk != wk:
            bad.append("Symbol %d K=%d, table wants K=%d" % (i, gk, wk))
    return bad


# ------------------------------------------------------------------ O-1

@cocotb.test()
async def ts1_matches_table_4_2(dut):
    """O-1: the emitted TS1 equals Base 2.1 Table 4-2 p.201-202, symbol for
    symbol and K-flag for K-flag.

    Link Number 05h and Lane Number 00h are both real (non-PAD) values, so the
    table says Symbols 1 and 2 are D codes and only Symbol 0 is K.  Symbols 6-15
    must all be D10.2 = 4Ah.
    """
    await start_clocks(dut)
    await reset(dut)
    want = golden_ts(link_num=0x05, lane_num=0x00, ts_disc=TS1)
    await drive(dut, G_VALID | G_GEN_TS1 | G_SET_LANE,
                pack_tsos(link_num=0x05, lane_num=0x00, ts_disc=TS1))
    got = find_os(await capture(dut, 60))
    assert got is not None, "no COM-framed ordered set on the wire"
    bad = compare(dut, "TS1", got, want)
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "TS1 diverges from Table 4-2 p.201 in %d places" % len(bad)


# ------------------------------------------------------------------ O-2

@cocotb.test()
async def ts2_matches_table_4_3(dut):
    """O-2: the emitted TS2 equals Base 2.1 Table 4-3 p.203-204.  Identical head
    to TS1; Symbols 6-15 are D5.2 = 45h.  Driving a DIFFERENT Link Number from
    the TS1 case keeps the pair from agreeing by coincidence."""
    await start_clocks(dut)
    await reset(dut)
    want = golden_ts(link_num=0x0A, lane_num=0x00, ts_disc=TS2)
    await drive(dut, G_VALID | G_GEN_TS2 | G_SET_LANE,
                pack_tsos(link_num=0x0A, lane_num=0x00, ts_disc=TS2))
    got = find_os(await capture(dut, 60))
    assert got is not None, "no COM-framed ordered set on the wire"
    bad = compare(dut, "TS2", got, want)
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "TS2 diverges from Table 4-3 p.203 in %d places" % len(bad)


# ------------------------------------------------------------------ O-1 + O-4

@cocotb.test()
async def ts1_with_pad_fields_is_k_coded(dut):
    """O-1 / O-4 at x1: with Link and Lane Numbers both PAD, Table 4-2 p.201
    says Symbols 1 and 2 are K23.7 and therefore K-coded.

    This is the state a port sits in for the whole of Detect/Polling and for
    Configuration.Linkwidth.Start (Base 2.1 sec 4.2.6.3.1) -- "TS1 Ordered Sets
    with Link and Lane numbers set to PAD (K23.7)" -- so it is not a corner.

    Rung 8 fixed Symbol 2's flag to be value-determined; this asserts the fixed
    behaviour end to end through the FIFO and scrambler rather than at the
    os_generator port, and it is the x1 control for the x4 failures in
    tb/os_generator/test_os_generator_x4.py.
    """
    await start_clocks(dut)
    await reset(dut)
    want = golden_ts(link_num=PAD, lane_num=PAD, ts_disc=TS1)
    await drive(dut, G_VALID | G_GEN_TS1, pack_tsos(link_num=PAD, lane_num=PAD))
    got = find_os(await capture(dut, 60))
    assert got is not None, "no COM-framed ordered set on the wire"
    bad = compare(dut, "TS1/PAD", got, want)
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "PAD TS1 diverges from Table 4-2 p.201 in %d places" % len(bad)


# ------------------------------------------------------------------ O-6

@cocotb.test()
async def eios_matches_table_4_4(dut):
    """O-6: Base 2.1 sec 4.2.4.2 p.205 -- the EIOS is "a K28.5 (COM) followed by
    three K28.3 (IDL)" at 2.5 GT/s, and Table 4-4 lists exactly Symbols 0-3.
    All four are K codes, so sec 4.2.3 p.199 ("All special Symbols (K codes) are
    not scrambled") says they reach the wire literally.

    os_generator streams a fixed 16 Symbols per burst (os_pkt_cnt = 3,
    os_generator.sv:174), so the burst is four EIOSs back to back.  Every
    4-Symbol group is checked, not just the first -- if the design ever emitted
    a partial or misaligned EIOS in the tail, the first group alone would hide it.
    """
    await start_clocks(dut)
    await reset(dut)
    await drive(dut, G_VALID | G_GEN_EIOS, pack_eios())
    syms = await capture(dut, 60)
    start = None
    for i, (s, k) in enumerate(syms):
        if s == COM and k == 1 and i + 16 <= len(syms):
            start = i
            break
    assert start is not None, "no K-coded COM in the EIOS burst: %s" % fmt(syms[:24])

    want = golden_eios_group()
    bad = []
    for g in range(4):
        group = syms[start + 4 * g: start + 4 * g + 4]
        dut._log.info("EIOS group %d: %s   want: %s" % (g, fmt(group), fmt(want)))
        if group != want:
            bad.append("group %d is %s, Table 4-4 p.205 wants %s"
                       % (g, fmt(group), fmt(want)))
    for b in bad:
        dut._log.error("  %s" % b)
    assert not bad, "%d of 4 EIOS groups diverge from Table 4-4 p.205" % len(bad)


# ----------------------------------------------------------- O-10 + O-14

@cocotb.test()
async def logical_idle_is_scrambled_and_ts_data_is_not(dut):
    """O-10 and O-14 together, as a contrast -- the pair is what makes either
    one meaningful.

    Base 2.1 sec 4.2.2 p.194: Logical Idle "must consist of the data byte 0
    (00 Hexadecimal), SCRAMBLED according to the rules of Section 4.2.3".
    Base 2.1 sec 4.2.3 p.199: "All data Symbols (D codes) EXCEPT those within a
    Training Sequence Ordered Sets (e.g., TS1, TS2) ... are scrambled."

    So the same all-D byte stream must come out DIFFERENT under gen_idle and
    LITERAL inside a TS.  Two different TS templates are driven, not one, so the
    literal-pass-through check cannot be satisfied by a fixed point of the
    scrambler: 05h and 0Ah would have to survive the same transform for the
    wrong reason to fool it.
    """
    await start_clocks(dut)
    await reset(dut)

    # (a) Logical Idle: an all-zero template must not come out all-zero.
    await drive(dut, G_VALID | G_GEN_IDLE,
                pack_tsos(com=0x00, link_num=0x00, lane_num=0x00, n_fts=0x00,
                          rate_id=0x00, train_ctrl=0x00, ts_disc=0x00))
    idle = await capture(dut, 60)
    assert idle, "no PIPE output during Logical Idle"
    nz = [s for s, k in idle if s != 0x00]
    ks = [s for s, k in idle if k]
    dut._log.info("idle first 24: %s" % fmt(idle[:24]))
    dut._log.info("idle non-zero %d / %d symbols, K-coded %d"
                  % (len(nz), len(idle), len(ks)))
    assert len(nz) > len(idle) // 4, \
        "Logical Idle came out mostly 00h -- sec 4.2.2 p.194 requires it scrambled"
    assert not ks, "Logical Idle must be data Symbols only; %d K codes seen" % len(ks)

    # (b) TS D codes, twice with different values -- both must be literal.
    seen = {}
    for link in (0x05, 0x0A):
        await reset(dut)
        await drive(dut, G_VALID | G_GEN_TS1 | G_SET_LANE,
                    pack_tsos(link_num=link, lane_num=0x00, ts_disc=TS1))
        os_ = find_os(await capture(dut, 60))
        assert os_ is not None, "no ordered set for link 0x%02x" % link
        seen[link] = os_[1][0]
        dut._log.info("TS1 link_num driven 0x%02x -> on the wire 0x%02x"
                      % (link, os_[1][0]))
    assert seen[0x05] == 0x05 and seen[0x0A] == 0x0A, \
        "sec 4.2.3 p.199: TS data Symbols must not be scrambled; got %s" % seen
    assert seen[0x05] != seen[0x0A], \
        "the two templates produced the same wire byte -- the literal-pass check " \
        "would be satisfied by a constant and proves nothing"
