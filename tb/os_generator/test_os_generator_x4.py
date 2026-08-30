"""Rung 9 -- spec-golden per-lane bench for os_generator at MAX_NUM_LANES=4.

Toplevel: os_generator, MAX_NUM_LANES=4.  Rung 8 gave this module its first bench
(test_os_generator_k_mask.py) at x1, where every lane-0 read degenerates to the
identity.  This file is the x4 extension it could not be: it drives ordered sets
that DIFFER FROM LANE TO LANE, which is the only stimulus that can tell a
per-lane rule from a lane-0 rule.

THE ORACLES (evidence/rung9/ORACLES_PHY_TX.md)

  O-3  TS Symbol 1 (Link Number) -- K iff the byte is PAD, PER LANE.
       Base 2.1 Table 4-2 p.201 gives Symbol 1 as "D0.0 - D31.7, K23.7", so
       K-ness is a property of the byte.  Base 2.1 sec 4.2.6.3.2.2 p.231,
       "Upstream Lanes" -- this design's role -- makes it a MUST that the values
       differ per lane:

           "Remaining Lanes must transmit TS1 Ordered Sets with Link and Lane
            numbers set to PAD (K23.7)."

       Base 3.0 repeats that sentence verbatim.  MindShare Figure 14-21 p.550
       draws it: an x4 Upstream Port transmitting Link # = N, N, PAD, N.

  O-4  TS Symbol 2 (Lane Number) -- K iff the byte is PAD, PER LANE.
       Base 2.1 Table 4-2 p.201, "D0.0 - D31.0, K23.7"; Base 3.0 Table 4-5 p.228
       spells it out: "0-31, PAD.  PAD is encoded as K23.7."

  O-5  Symbols 0 and 3-15 are lane-invariant.  Base 2.1 sec 4.2.2 p.194 -- "a
       full Ordered Set appears simultaneously on all Lanes"; Table 4-2 p.202
       for Symbol 4 -- "All Lanes under the control of a common LTSSM must
       transmit the same value in this Symbol."

  O-7/O-9  SKP Ordered Set is one COM followed by three SKP, transmitted
       "simultaneously on all Lanes of a multi-Lane Link" (Base 2.1 sec 4.2.7.1
       p.261).

WHAT THE RTL DOES (census: evidence/rung9/CENSUS_PHY_TX.md)

    os_generator.sv:179-182   OR of link_num == PAD_ ACROSS ALL LANES -> bit 1
    os_generator.sv:213-215   lane 0's lane_num only                  -> bit 2
    os_generator.sv:237       one USER_WIDTH-wide slice, emitted in tuser's
                              lane-0 slice; lane_management.sv:413 broadcasts it

Two different reductions of a per-lane property to a single bit.  Neither is
per-lane.  At MAX_NUM_LANES=1 both degenerate to lane 0, which is why x1 is
clean and why this file has to be x4.

Bench drives only os_generator ports; it never touches RTL internals, and every
expected value is built here from the spec tables, not captured from the DUT.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

NUM_LANES = 4

# ---- pcie_phy_pkg.sv constants ----
PAD = 0xF7          # K23.7   (train_seq_e.PAD_, pkg:35)
COM = 0xBC          # K28.5   (pkg:100)
SKP = 0x1C          # K28.0   (pkg:106)
TS1 = 0x4A          # D10.2   (pkg:32)
TS2 = 0x45          # D5.2    (pkg:33)
N_FTS = 0xFF
GEN1_BASIC = 0x02

# gen_os_struct_t packed layout, LSB first (pkg:269-284)
B_VALID, B_TS1, B_TS2, B_SET_LANE = 0, 1, 2, 9

TSOS_BITS = 128     # one pcie_ordered_set_t
USER_WIDTH = 4      # os_generator's default; the x4 target does not override it


def ctrl(valid=1, ts1=1, ts2=0, set_lane=0):
    return ((valid & 1) << B_VALID) | ((ts1 & 1) << B_TS1) \
         | ((ts2 & 1) << B_TS2) | ((set_lane & 1) << B_SET_LANE)


def tsos(link_num=PAD, lane_num=PAD, ts_disc=TS1, n_fts=N_FTS,
         rate_id=GEN1_BASIC, train_ctrl=0x00, com=COM):
    """One spec-golden 16-Symbol TS Ordered Set, Base 2.1 Table 4-2 p.201.

    Symbol 0 COM, 1 Link Number, 2 Lane Number, 3 N_FTS, 4 Data Rate Identifier,
    5 Training Control, 6-15 the TS identifier (D10.2 = 4Ah for TS1, D5.2 = 45h
    for TS2).  Built here from the table -- nothing captured from the DUT.
    """
    b = [com, link_num & 0xFF, lane_num & 0xFF, n_fts & 0xFF,
         rate_id & 0xFF, train_ctrl & 0xFF] + [ts_disc & 0xFF] * 10
    assert len(b) == 16
    v = 0
    for i, bv in enumerate(b):
        v |= bv << (8 * i)
    return v


def pack_lanes(per_lane):
    """Flatten NUM_LANES pcie_ordered_set_t into the packed input vector.
    Lane 0 occupies the LOW 128 bits (packed-array element 0 is the LSB)."""
    assert len(per_lane) == NUM_LANES
    v = 0
    for lane, os_val in enumerate(per_lane):
        v |= (os_val & ((1 << TSOS_BITS) - 1)) << (TSOS_BITS * lane)
    return v


def sym_of(data, lane, sym_in_beat):
    """Symbol `sym_in_beat` (0..3) of `lane` from a packed m_axis_tdata beat."""
    return (data >> (32 * lane + 8 * sym_in_beat)) & 0xFF


def kmask_lane0(tuser):
    """os_generator emits the K-mask in tuser's lane-0 slice only; the rest of
    the bus is zero-extended (os_generator.sv:237, a USER_WIDTH-wide value
    assigned to a USER_WIDTH*MAX_NUM_LANES signal).  lane_management.sv:413 then
    broadcasts these four bits to every lane, so THIS is the mask every lane
    gets."""
    return tuser & ((1 << USER_WIDTH) - 1)


async def reset(dut):
    dut.rst_i.value = 1
    dut.gen_os_ctrl_i.value = 0
    dut.ordered_set_i.value = 0
    dut.curr_data_rate_i.value = 1          # gen1
    dut.send_ltssm_os_i.value = 0
    dut.preset_i.value = 0
    dut.link_up_i.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


async def first_beat(dut, per_lane, set_lane=0, ts2=False, timeout=200):
    """Drive one per-lane ordered set; return (tdata, tuser) of its FIRST beat.

    Beat 0 carries Symbols 0-3 of every lane, so mask bit n is Symbol n's flag.
    """
    dut.ordered_set_i.value = pack_lanes(per_lane)
    dut.gen_os_ctrl_i.value = ctrl(valid=1, ts1=0 if ts2 else 1,
                                   ts2=1 if ts2 else 0, set_lane=set_lane)
    dut.m_axis_tready.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")           # post-edge: read settled values
        if int(dut.m_axis_tvalid.value) & 1:
            data = int(dut.m_axis_tdata.value)
            tuser = int(dut.m_axis_tuser.value)
            dut.gen_os_ctrl_i.value = 0      # quiesce for the next case
            for _ in range(40):
                await RisingEdge(dut.clk_i)
            return data, tuser
    raise AssertionError("os_generator produced no beat within %d cycles" % timeout)


def _fmt_lane(data, lane, k):
    return "lane%d: %s" % (lane, " ".join(
        "%02x%s" % (sym_of(data, lane, s), "K" if (k >> s) & 1 else " ")
        for s in range(4)))


# --------------------------------------------------------------- O-3, Symbol 1

@cocotb.test(expect_fail=True)
async def symbol1_k_flag_is_per_lane(dut):
    """O-3: Symbol 1's K-flag must be per lane -- K iff THAT lane's byte is PAD.

    Stimulus is the MindShare Figure 14-21 p.550 case, verbatim: an x4 Upstream
    Port with Link # = N, N, PAD, N.  Base 2.1 sec 4.2.6.3.2.2 p.231 makes the
    PAD on the odd lane a MUST ("Remaining Lanes must transmit TS1 Ordered Sets
    with Link and Lane numbers set to PAD").

    PREDICTED DIVERGENCE (PREDICTIONS_R9.md sec 3, O-3).  os_generator.sv:179-182

        for (int i = 0; i < MAX_NUM_LANES; i++)
          if (Q.ordered_set[i].link_num == PAD_) D.special_k[1] = '1;

    ORs the PAD-ness of every lane into one bit.  Lane 2's PAD therefore marks
    lanes 0, 1 and 3's REAL Link Numbers as control codes.  A receiver decoding
    lane 0 sees a K symbol where a D5.0 Link Number belongs, so the Link Number
    it needs to match in Configuration.Linkwidth.Accept never arrives.

    This is the same defect class Rung 7 found in Symbol 2 -- at the symbol
    Rung 8's own comment (os_generator.sv:203-212) holds up as already correct:
    "it is identical on every lane".  Symbol 1 is not.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    link_per_lane = [0x05, 0x05, PAD, 0x05]          # Fig. 14-21 p.550
    sets = [tsos(link_num=ln, lane_num=i) for i, ln in enumerate(link_per_lane)]
    data, tuser = await first_beat(dut, sets)
    k = kmask_lane0(tuser)

    bad = []
    for lane in range(NUM_LANES):
        dut._log.info("%s   (driven link_num=0x%02x)" % (_fmt_lane(data, lane, k),
                                                         link_per_lane[lane]))
        got_byte = sym_of(data, lane, 1)
        assert got_byte == link_per_lane[lane], \
            "lane %d Symbol 1 byte is 0x%02x, expected the driven 0x%02x" \
            % (lane, got_byte, link_per_lane[lane])
        want_k = 1 if got_byte == PAD else 0
        got_k = (k >> 1) & 1
        if got_k != want_k:
            bad.append("lane %d: Symbol 1 = 0x%02x marked K=%d, Base 2.1 "
                       "Table 4-2 p.201 requires K=%d" % (lane, got_byte, got_k, want_k))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d of %d lanes violate Table 4-2 p.201 / sec 4.2.6.3.2.2 p.231" \
                    % (len(bad), NUM_LANES)


# --------------------------------------------------------------- O-4, Symbol 2

@cocotb.test(expect_fail=True)
async def symbol2_k_flag_is_per_lane(dut):
    """O-4: Symbol 2's K-flag must be per lane -- K iff THAT lane's byte is PAD.

    Stimulus: Lane # = 0, 1, PAD, 3.  A x4 port that has assigned three lanes
    and left one out is required to send PAD on the leftover lane (Base 2.1
    sec 4.2.6.3.2.2 p.231) while the other three send their real numbers.

    PREDICTED DIVERGENCE (PREDICTIONS_R9.md sec 3, O-4).  os_generator.sv:213
    reads lane 0 only:

        if (Q.ordered_set[0].lane_num == PAD_) D.special_k[2] = '1;

    Lane 0's Lane Number is 0x00, not PAD, so the mask says D -- and lane 2's
    genuine PAD is transmitted as D23.7.  The receiver never sees a PAD on the
    leftover lane and cannot tell it apart from a lane claiming Lane Number 23.

    Rung 8 chose lane 0 DELIBERATELY (os_generator.sv:203-212) because ORing --
    the shape used for Symbol 1 -- would have been worse.  Both reductions are
    wrong; this test scores the one that is left.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    lane_per_lane = [0x00, 0x01, PAD, 0x03]
    sets = [tsos(link_num=0x05, lane_num=ln) for ln in lane_per_lane]
    data, tuser = await first_beat(dut, sets, set_lane=1)
    k = kmask_lane0(tuser)

    bad = []
    for lane in range(NUM_LANES):
        dut._log.info("%s   (driven lane_num=0x%02x)" % (_fmt_lane(data, lane, k),
                                                         lane_per_lane[lane]))
        got_byte = sym_of(data, lane, 2)
        assert got_byte == lane_per_lane[lane], \
            "lane %d Symbol 2 byte is 0x%02x, expected the driven 0x%02x" \
            % (lane, got_byte, lane_per_lane[lane])
        want_k = 1 if got_byte == PAD else 0
        got_k = (k >> 2) & 1
        if got_k != want_k:
            bad.append("lane %d: Symbol 2 = 0x%02x marked K=%d, Base 2.1 "
                       "Table 4-2 p.201 requires K=%d" % (lane, got_byte, got_k, want_k))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d of %d lanes violate Table 4-2 p.201" % (len(bad), NUM_LANES)


# --------------------------------------------------- O-5, the sound positions

@cocotb.test()
async def symbols_0_and_3_to_15_are_lane_invariant(dut):
    """O-5: the POSITIVE half of the x4 K-mask table.

    Base 2.1 sec 4.2.2 p.194 -- "a full Ordered Set appears simultaneously on
    all Lanes of a multi-Lane Link".  Table 4-2 p.202 for Symbol 4 -- "All Lanes
    under the control of a common LTSSM must transmit the same value in this
    Symbol."  Symbols 0 (COM), 3 (N_FTS), 4 (Data Rate ID), 5 (Training Control)
    and 6-15 (TS identifier) are port-wide, so a SINGLE broadcast K-mask is
    sound at those fourteen positions.

    This test earns the "YES" rows of the requirements table rather than
    asserting them: it drives four sets that differ ONLY in Symbols 1 and 2 and
    proves every other position comes out byte-identical on all four lanes.  If
    a future per-lane-mask fix widened the mask at a position this test covers,
    this row says the widening was unnecessary there.

    It also fixes the mask's bit order: Symbol 0 is COM on every lane and is the
    one position that must be K in every ordered set.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    # Differ ONLY in Symbols 1 and 2.  Everything else identical by construction.
    sets = [tsos(link_num=(PAD if i == 2 else 0x05), lane_num=(PAD if i == 2 else i))
            for i in range(NUM_LANES)]

    # Beat b carries Symbols 4b..4b+3.  Walk all four beats.
    dut.ordered_set_i.value = pack_lanes(sets)
    dut.gen_os_ctrl_i.value = ctrl(valid=1, ts1=1)
    dut.m_axis_tready.value = 1

    beats = []
    for _ in range(400):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.m_axis_tvalid.value) & 1:
            beats.append((int(dut.m_axis_tdata.value), int(dut.m_axis_tuser.value)))
            if len(beats) == 4:
                break
    assert len(beats) == 4, "expected 4 beats of a 16-Symbol ordered set, saw %d" % len(beats)

    golden = tsos(link_num=0x05, lane_num=0)     # the reference for shared positions
    bad = []
    for b, (data, tuser) in enumerate(beats):
        for s in range(4):
            sym_index = 4 * b + s
            if sym_index in (1, 2):
                continue                          # the two per-lane positions
            want = (golden >> (8 * sym_index)) & 0xFF
            vals = [sym_of(data, lane, s) for lane in range(NUM_LANES)]
            dut._log.info("Symbol %-2d  lanes=%s  want=0x%02x"
                          % (sym_index, ["0x%02x" % v for v in vals], want))
            if len(set(vals)) != 1:
                bad.append("Symbol %d differs across lanes: %s" % (sym_index, vals))
            elif vals[0] != want:
                bad.append("Symbol %d is 0x%02x, Table 4-2 p.201 wants 0x%02x"
                           % (sym_index, vals[0], want))

    k0 = kmask_lane0(beats[0][1])
    assert sym_of(beats[0][0], 0, 0) == COM, "Symbol 0 is not COM"
    assert k0 & 1, "Symbol 0 (COM) is not marked K -- the mask's bit order is not what " \
                   "this file assumes and every other assertion here reads the wrong bit"
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d lane-invariant positions violated" % len(bad)
    dut._log.info("14 of 16 Symbol positions confirmed lane-invariant; only 1 and 2 vary")


# --------------------------------------------------------------- O-7 / O-9, SKP

@cocotb.test(expect_fail=True)
async def skp_ordered_set_is_transmitted_on_all_lanes(dut):
    """O-9: "the SKP Ordered Set shall be transmitted simultaneously on all
    Lanes of a multi-Lane Link" -- Base 2.1 sec 4.2.7.1 p.261.  O-7 gives its
    content: "one COM Symbol followed by three consecutive SKP Symbols".

    So at x4 every one of the four lanes must carry BC 1C 1C 1C.

    PREDICTED DIVERGENCE (PREDICTIONS_R9.md sec 3, O-9).  os_generator.sv:165

        ltssm_axis_tdata = 32'h1c1c1cbc;

    assigns a bare 32-bit literal to a signal that is DATA_WIDTH*MAX_NUM_LANES
    wide.  Lanes 1-3 zero-extend: they transmit 00 00 00 00 while lane 0 carries
    the SKP Ordered Set, and the accompanying tuser is all-ones, so those zero
    bytes are marked as control codes.  The link partner's elastic buffer gets
    its clock-compensation opportunity on lane 0 only.

    ⚠️ This path had never executed before this bench.  skp_cnt advances only
    under `if (link_up_i)` (os_generator.sv:139) and all three pre-Rung-9 TX
    benches hold link_up_i at 0, so ST_SKP was dead in all 71 gate rows.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    # No LTSSM command: the FSM parks in ST_IDLE and the internal SKP timer runs.
    dut.gen_os_ctrl_i.value = 0
    dut.ordered_set_i.value = 0
    dut.m_axis_tready.value = 1
    dut.link_up_i.value = 1                       # <-- arms os_generator.sv:139-141

    # os_generator.sv:158 fires at skp_cnt >= 0xB0 = 176.  Bound generously.
    data = None
    for _ in range(600):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.m_axis_tvalid.value) & 1:
            data = int(dut.m_axis_tdata.value)
            tuser = int(dut.m_axis_tuser.value)
            break
    assert data is not None, "no SKP Ordered Set within 600 cycles of link_up_i " \
                             "(os_generator.sv:158 expects 176)"

    want = [COM, SKP, SKP, SKP]
    bad = []
    for lane in range(NUM_LANES):
        got = [sym_of(data, lane, s) for s in range(4)]
        dut._log.info("lane%d SKP OS: %s   want: %s"
                      % (lane, " ".join("%02x" % v for v in got),
                         " ".join("%02x" % v for v in want)))
        if got != want:
            bad.append("lane %d carries %s, sec 4.2.7.1 p.261 requires COM SKP SKP SKP"
                       % (lane, " ".join("%02x" % v for v in got)))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d of %d lanes do not carry the SKP Ordered Set" % (len(bad), NUM_LANES)
