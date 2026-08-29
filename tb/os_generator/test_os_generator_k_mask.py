"""Spec-golden bench for os_generator's TS ordered-set K-mask.

Toplevel: os_generator, MAX_NUM_LANES=1.  This module had NO bench of its own
until Rung 8 -- which is exactly why the Rung-7 defect was invisible: every
LTSSM gate target's toplevel is pcie_ltssm_downstream, and os_generator is only
elaborated through phy_transmit.

WHAT IS UNDER TEST
    A TS1/TS2 ordered set is 16 Symbols.  Symbol 0 is COM, Symbol 1 the Link
    Number, Symbol 2 the Lane Number.  os_generator emits a K-mask alongside the
    data (m_axis_tuser); bit n of the first beat's mask marks Symbol n as a
    control (K) code rather than a data (D) code.

THE ORACLE -- Base 2.1 Table 4-2, p.201
        Symbol 1  Link Number   encoded values: D0.0 - D31.7, K23.7
        Symbol 2  Lane Number   encoded values: D0.0 - D31.0, K23.7
    Base 3.0's TS1 table agrees and is more explicit: "0-31, PAD.  PAD is
    encoded as K23.7."

    So for BOTH symbols the K-flag is a function of the BYTE VALUE and nothing
    else: K iff the byte is PAD (0xF7 = K23.7).  It is not a function of any
    LTSSM control signal.  That is the whole rule, and it is what this bench
    asserts.

WHY THIS FINDS A DEFECT
    os_generator.sv:180 implements exactly that rule for Symbol 1 (a value
    check).  os_generator.sv:189 implements a DIFFERENT rule for Symbol 2: K iff
    gen_os_ctrl_i.set_lane is low -- a control check.  The two disagree whenever
    set_lane does not happen to track PAD-ness of the Lane Number, which Rung 7
    showed happens on every link bring-up.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

PAD = 0xF7          # K23.7, pcie_phy_pkg.sv:35
COM = 0xBC          # K28.5
TS1 = 0x4A

# gen_os_struct_t packed layout, LSB first (pcie_phy_pkg.sv:269-284)
B_VALID, B_TS1, B_TS2, B_SET_LANE = 0, 1, 2, 9

# pcie_tsos_t byte offsets (pcie_phy_pkg.sv:254-266, com is the LSB byte)
O_COM, O_LINK, O_LANE = 0, 8, 16


def ctrl(valid=1, ts1=1, ts2=0, set_lane=0):
    return ((valid & 1) << B_VALID) | ((ts1 & 1) << B_TS1) \
         | ((ts2 & 1) << B_TS2) | ((set_lane & 1) << B_SET_LANE)


def tsos(link_num=PAD, lane_num=PAD):
    """One pcie_tsos_t.  Only the three bytes this bench reasons about are set."""
    return (COM << O_COM) | ((link_num & 0xFF) << O_LINK) | ((lane_num & 0xFF) << O_LANE)


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


async def first_beat(dut, link_num, lane_num, set_lane, ts2=False, timeout=200):
    """Drive one ordered set; return (data, kmask) of its FIRST beat.

    Beat 0 carries Symbols 0-3, so kmask bit n is Symbol n's K flag.
    """
    dut.ordered_set_i.value = tsos(link_num, lane_num)
    dut.gen_os_ctrl_i.value = ctrl(valid=1, ts1=0 if ts2 else 1, ts2=1 if ts2 else 0,
                                   set_lane=set_lane)
    dut.m_axis_tready.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")          # post-edge: read settled values
        if int(dut.m_axis_tvalid.value) & 1:
            data = int(dut.m_axis_tdata.value)
            kmask = int(dut.m_axis_tuser.value)
            # quiesce so the next case starts clean
            dut.gen_os_ctrl_i.value = 0
            for _ in range(40):
                await RisingEdge(dut.clk_i)
            return data, kmask
    raise AssertionError("os_generator produced no beat within %d cycles" % timeout)


def _check(dut, bad, label, data, kmask, lane_num):
    sym2 = (data >> 16) & 0xFF
    k2 = (kmask >> 2) & 1
    want_k2 = 1 if lane_num == PAD else 0
    dut._log.info("%-34s Symbol2=0x%02x  K=%d  want K=%d" % (label, sym2, k2, want_k2))
    assert sym2 == lane_num, \
        "%s: Symbol 2 byte is 0x%02x, expected the driven lane_num 0x%02x" \
        % (label, sym2, lane_num)
    if k2 != want_k2:
        bad.append("%s: Symbol 2 = 0x%02x marked K=%d, Base 2.1 Table 4-2 requires K=%d"
                   % (label, sym2, k2, want_k2))


# Was expect_fail for exactly one commit (77315ab), which pre-registered the
# defect as a green row.  F2 made os_generator.sv:189 value-determined; the
# marker comes off here, in that same commit.
@cocotb.test()
async def symbol2_k_flag_follows_the_value_rule(dut):
    """T2a: Symbol 2 is K iff its byte is PAD -- across all four control states.

    Four cases, the full cross of {Lane Number PAD, non-PAD} x {set_lane 0, 1}.
    Two of them are the ones the RTL gets wrong at HEAD:

      lane_num=0x00, set_lane=0  -> RTL marks K.  It is a DATA byte (D0.0).
                                    This is the Rung-7 defect, and it is the
                                    state the LTSSM is in for the whole of
                                    Configuration.Lanenum.Wait.
      lane_num=PAD,  set_lane=1  -> RTL leaves it D.  PAD *is* K23.7, so the
                                    receiver sees D23.7 and never sees a PAD.

    The other two happen to agree with the spec, which is why the defect
    survived: set_lane is correlated with PAD-ness, just not equal to it.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    bad = []
    for lane_num, set_lane, label in (
            (PAD,  0, "PAD,     set_lane=0"),
            (PAD,  1, "PAD,     set_lane=1"),
            (0x00, 0, "0x00,    set_lane=0"),
            (0x03, 1, "0x03,    set_lane=1"),
    ):
        data, kmask = await first_beat(dut, link_num=0x01, lane_num=lane_num,
                                       set_lane=set_lane)
        _check(dut, bad, label, data, kmask, lane_num)
    for line in bad:
        dut._log.error("  %s" % line)
    assert not bad, "%d of 4 control states violate Base 2.1 Table 4-2" % len(bad)


@cocotb.test()
async def symbol1_k_flag_is_already_value_determined(dut):
    """T2b: the control case -- Symbol 1 is right, and by the rule we want.

    os_generator.sv:180 already value-checks the Link Number.  This asserts it,
    so the bench states the rule for both symbols and shows the asymmetry is in
    Symbol 2 alone.  It passes before and after F2.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    bad = []
    for link_num, label in ((PAD, "link PAD"), (0x01, "link 0x01")):
        data, kmask = await first_beat(dut, link_num=link_num, lane_num=PAD, set_lane=0)
        sym1 = (data >> 8) & 0xFF
        k1 = (kmask >> 1) & 1
        want = 1 if link_num == PAD else 0
        dut._log.info("%-34s Symbol1=0x%02x  K=%d  want K=%d" % (label, sym1, k1, want))
        assert sym1 == link_num, "%s: Symbol 1 byte wrong" % label
        if k1 != want:
            bad.append("%s: Symbol 1 = 0x%02x marked K=%d, want %d" % (label, sym1, k1, want))
    assert not bad, "Symbol 1 violates Table 4-2: %s" % bad


@cocotb.test()
async def symbol0_is_always_a_comma(dut):
    """T2c: Symbol 0 is COM (K28.5) and always marked K, in every control state.

    A frame whose COM is not K does not align.  Cheap, and it anchors the mask's
    bit ordering: if bit 0 were not COM's flag, this fails and every other
    assertion in this file is reading the wrong bit.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    for set_lane in (0, 1):
        data, kmask = await first_beat(dut, link_num=0x01, lane_num=0x00, set_lane=set_lane)
        assert (data & 0xFF) == COM, "Symbol 0 is 0x%02x, expected COM 0xBC" % (data & 0xFF)
        assert (kmask & 1) == 1, "Symbol 0 (COM) not marked K with set_lane=%d" % set_lane
    dut._log.info("Symbol 0 = COM, K=1, in both control states")
