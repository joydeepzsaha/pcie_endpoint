"""Fix-arc 4 -- the SECOND GEOMETRY for os_generator's per-lane K-mask.

Toplevel: os_generator at MAX_NUM_LANES=2 and USER_WIDTH=5.

WHY A THIRD GEOMETRY EXISTS
---------------------------
The K-mask and its stride are width-parameterised, and neither existing geometry
can catch a stride expression tuned to the default:

  x1  verilate_os_gen_kmask -- every per-lane site in os_generator degenerates to
      the identity at MAX_NUM_LANES=1, so x1 cannot distinguish a per-lane rule
      from a lane-0 rule at all.  That is why Rung 9 added x4.

  x4  verilate_os_gen_x4 -- does NOT override USER_WIDTH, so it runs at the
      module default 4.  There USER_WIDTH == DATA_WIDTH/8 == symbols per beat,
      the special_k stride is ACCIDENTALLY correct, and the stride half of
      tracker §54 #5 is invisible.

phy_transmit instantiates os_generator with USER_WIDTH = 5 (phy_transmit.sv:12),
so the parameterisation that actually ships is the one no unit row exercised.
This target runs a lane count that is neither the default nor the identity, at
the width that ships -- the power-of-two lesson (a wrap expression can be dead at
the depth you happen to test) applied to lane width and to mask stride together.

WHAT IT ASSERTS
---------------
Exactly the per-lane K rule of Base 2.1 Table 4-2 p.201, at two lanes: Symbol 1
(Link Number) and Symbol 2 (Lane Number) are control codes iff THAT lane's byte
is PAD.  The stimulus is lane-distinct -- one assigned lane and one PAD lane --
so a broadcast mask cannot pass it by symmetry.

It also checks the two properties only a non-default width can see: that lane 1's
mask lives at bit offset USER_WIDTH (not 4), and that the phantom fifth bit of
each slice is zero rather than carrying a neighbouring beat's flag.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

NUM_LANES = 2               # -GMAX_NUM_LANES=2
USER_WIDTH = 5              # -GUSER_WIDTH=5, the shipping value
SYMS_PER_BEAT = 4           # DATA_WIDTH/8, DATA_WIDTH defaults to 32

PAD = 0xF7                  # K23.7
COM = 0xBC                  # K28.5
N_FTS = 0xFF
GEN1_BASIC = 0x02
TS1 = 0x4A
TSOS_BITS = 128

G_VALID = 1 << 0
G_GEN_TS1 = 1 << 1
G_SET_LANE = 1 << 9


def ctrl(valid=0, ts1=0, set_lane=0):
    v = 0
    if valid:
        v |= G_VALID
    if ts1:
        v |= G_GEN_TS1
    if set_lane:
        v |= G_SET_LANE
    return v


def tsos(link_num, lane_num, ts_disc=TS1):
    """One pcie_ordered_set_t, little-endian by Symbol index."""
    syms = [COM, link_num, lane_num, N_FTS, GEN1_BASIC, 0x00] + [ts_disc] * 10
    v = 0
    for i, s in enumerate(syms):
        v |= (s & 0xFF) << (8 * i)
    return v


def pack_lanes(per_lane):
    assert len(per_lane) == NUM_LANES
    v = 0
    for lane, os_val in enumerate(per_lane):
        v |= (os_val & ((1 << TSOS_BITS) - 1)) << (TSOS_BITS * lane)
    return v


def sym_of(data, lane, sym_in_beat):
    return (data >> (32 * lane + 8 * sym_in_beat)) & 0xFF


def kmask(tuser, lane):
    """Lane `lane`'s slice of m_axis_tuser: [USER_WIDTH*lane +: USER_WIDTH].

    At USER_WIDTH=5 this is a DIFFERENT bit offset from the 4 that x4 happens to
    use, which is the whole point of running this geometry.
    """
    return (tuser >> (USER_WIDTH * lane)) & ((1 << USER_WIDTH) - 1)


async def reset(dut):
    dut.rst_i.value = 1
    dut.gen_os_ctrl_i.value = 0
    dut.ordered_set_i.value = 0
    dut.curr_data_rate_i.value = 1
    dut.send_ltssm_os_i.value = 0
    dut.preset_i.value = 0
    dut.link_up_i.value = 0
    dut.m_axis_tready.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


async def first_beat(dut, per_lane, set_lane=0, timeout=200):
    dut.ordered_set_i.value = pack_lanes(per_lane)
    dut.gen_os_ctrl_i.value = ctrl(valid=1, ts1=1, set_lane=set_lane)
    dut.m_axis_tready.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        if int(dut.m_axis_tvalid.value) & 1:
            data = int(dut.m_axis_tdata.value)
            tuser = int(dut.m_axis_tuser.value)
            dut.gen_os_ctrl_i.value = 0
            for _ in range(40):
                await RisingEdge(dut.clk_i)
            return data, tuser
    raise AssertionError("os_generator produced no beat within %d cycles" % timeout)


def _fmt_lane(data, lane, k):
    return "lane%d: %s" % (lane, " ".join(
        "%02x%s" % (sym_of(data, lane, s), "K" if (k >> s) & 1 else " ")
        for s in range(SYMS_PER_BEAT)))


@cocotb.test()
async def x2_per_lane_k_flags_at_user_width_5(dut):
    """Symbols 1 and 2 are K iff THAT lane's byte is PAD, at x2 / USER_WIDTH=5.

    Lane 0 is assigned (Link 0x05, Lane 0x00); lane 1 is unassigned and carries
    PAD in both Symbols, as Base 2.1 §4.2.6.3.2.2 p.231 requires of an Upstream
    Port's remaining Lanes.  Lane-distinct by construction.

    PREDICTED DIVERGENCE.  os_generator.sv:180 ORs PAD-ness across lanes into one
    bit and :213 reads lane 0's Lane Number alone, so at x2 lane 1's genuine PAD
    marks lane 0's real Link Number as a control code while lane 1's own slice is
    never written at all (:237 assigns a USER_WIDTH-wide value to a
    USER_WIDTH*MAX_NUM_LANES bus, so lane 1 zero-extends).
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    link_per_lane = [0x05, PAD]
    lane_per_lane = [0x00, PAD]
    sets = [tsos(link_num=link_per_lane[l], lane_num=lane_per_lane[l])
            for l in range(NUM_LANES)]
    data, tuser = await first_beat(dut, sets, set_lane=1)

    bad = []
    for lane in range(NUM_LANES):
        k = kmask(tuser, lane)
        dut._log.info("%s   (driven link=0x%02x lane=0x%02x, slice at bit %d)"
                      % (_fmt_lane(data, lane, k), link_per_lane[lane],
                         lane_per_lane[lane], USER_WIDTH * lane))
        for sym, driven in ((1, link_per_lane[lane]), (2, lane_per_lane[lane])):
            got_byte = sym_of(data, lane, sym)
            assert got_byte == driven, (
                "lane %d Symbol %d byte is 0x%02x, expected the driven 0x%02x"
                % (lane, sym, got_byte, driven))
            want_k = 1 if driven == PAD else 0
            got_k = (k >> sym) & 1
            if got_k != want_k:
                bad.append("lane %d Symbol %d = 0x%02x marked K=%d, Table 4-2 "
                           "p.201 requires K=%d" % (lane, sym, got_byte, got_k, want_k))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d per-lane K-flag violations at x2 / USER_WIDTH=5" % len(bad)


@cocotb.test()
async def x2_control_com_is_k_on_lane0(dut):
    """Control, ordinary PASS before AND after the fix.

    Symbol 0 is COM and is K-marked in LANE 0's mask slice.  This is what proves
    the drive reaches the sampling point and fixes the mask's bit order, so that
    a failure in the rows below is a real K-flag disagreement and not this bench
    reading the wrong bits.

    Independent observation point (§22.80): lane 0's slice at bit 0.  Lane 0 is
    the lane the broadcast layout already writes and Symbol 0 is lane-invariant
    by §4.2.2 p.194, so neither can be moved by the per-lane defect under test.
    A control drawn from lane 1, or from Symbols 1-2, would share a dependency
    with the very thing being measured -- the mistake §22.80 was earned by.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    sets = [tsos(link_num=0x05, lane_num=0x00), tsos(link_num=PAD, lane_num=PAD)]
    data, tuser = await first_beat(dut, sets, set_lane=1)
    k0 = kmask(tuser, 0)
    dut._log.info("%s   (lane 0 slice at bit 0)" % _fmt_lane(data, 0, k0))
    assert sym_of(data, 0, 0) == COM, "lane 0 Symbol 0 is not COM"
    assert k0 & 1, ("lane 0 Symbol 0 (COM) is not marked K -- the mask's bit "
                    "order is not what this file assumes and every other "
                    "assertion here reads the wrong bit")


@cocotb.test()
async def x2_com_is_k_on_every_lane(dut):
    """Base 2.1 §4.2.2 p.194: "a full Ordered Set appears simultaneously on all
    Lanes of a multi-Lane Link".  Symbol 0 is COM on every Lane, so every Lane's
    mask must mark it.

    PREDICTED DIVERGENCE, and a DIFFERENT one from the row above it, which is why
    it gets its own row (§22.66 -- one divergent assertion per expect_fail row,
    never mixed with a conforming one).  This one is caused by
    os_generator.sv:237 alone: a USER_WIDTH-wide value assigned to a
    USER_WIDTH*MAX_NUM_LANES bus, so lane 1's slice is never written and
    zero-extends.  The per-lane rows below are caused by :180 and :213.

    ⚠️ At the INTEGRATED boundary this divergence is currently masked, because
    lane_management.sv:413 broadcasts lane 0's slice to every lane and lane 0's
    bit 0 is set.  It is visible HERE, at os_generator's own boundary, before
    that broadcast hides it -- which is the point of scoring the unit and the
    integrated path separately.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    sets = [tsos(link_num=0x05, lane_num=0x00), tsos(link_num=PAD, lane_num=PAD)]
    data, tuser = await first_beat(dut, sets, set_lane=1)

    bad = []
    for lane in range(NUM_LANES):
        k = kmask(tuser, lane)
        dut._log.info("%s   (slice at bit %d)" % (_fmt_lane(data, lane, k),
                                                  USER_WIDTH * lane))
        assert sym_of(data, lane, 0) == COM, "lane %d Symbol 0 is not COM" % lane
        if not (k & 1):
            bad.append("lane %d: COM at Symbol 0 is not marked K (slice at bit %d "
                       "reads 0x%02x)" % (lane, USER_WIDTH * lane, k))
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, ("%d of %d Lanes do not mark their COM as a control code "
                     "(Base 2.1 §4.2.2 p.194)" % (len(bad), NUM_LANES))


@cocotb.test()
async def x2_phantom_bit_of_each_slice_is_zero(dut):
    """USER_WIDTH=5 but a beat carries only DATA_WIDTH/8 = 4 Symbols, so bit 4 of
    every lane's slice describes a Symbol that does not exist.

    Rung 9 (FINDINGS_PHY_TX.md §3) named this: special_k strides by USER_WIDTH
    across 4-Symbol beats, so bit 4 of each slice is a phantom fifth Symbol, and
    the layout's `USER_WIDTH == symbols-per-beat` invariant is already false in
    the only instantiation that exists.  A phantom bit that is left to inference
    can carry a neighbouring beat's flag; this row requires it to be WRITTEN
    zero.

    Ordinary PASS on unfixed RTL too -- today only bits 0-2 of beat 0 are ever
    set, so bit 4 happens to be zero.  It is committed as a guard against the
    stride being "fixed" in the direction that lets beat n+1's bit 0 leak into
    beat n's phantom position.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)

    sets = [tsos(link_num=0x05, lane_num=0x00), tsos(link_num=PAD, lane_num=PAD)]
    _, tuser = await first_beat(dut, sets, set_lane=1)

    for lane in range(NUM_LANES):
        k = kmask(tuser, lane)
        phantom = (k >> SYMS_PER_BEAT) & ((1 << (USER_WIDTH - SYMS_PER_BEAT)) - 1)
        dut._log.info("lane %d slice=0x%02x phantom bits [%d:%d]=0x%x"
                      % (lane, k, USER_WIDTH - 1, SYMS_PER_BEAT, phantom))
        assert phantom == 0, (
            "lane %d: bit(s) above Symbol %d of the mask slice are 0x%x, not zero "
            "-- a beat carries %d Symbols and there is no Symbol %d to mark"
            % (lane, SYMS_PER_BEAT - 1, phantom, SYMS_PER_BEAT, SYMS_PER_BEAT))
