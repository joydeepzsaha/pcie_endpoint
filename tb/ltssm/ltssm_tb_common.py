"""
Shared helpers for pcie_ltssm_downstream cocotb testbenches.
State encodings below are copied verbatim (as hex) from the ltssm_state_e
enum in src/ltssm/pcie_ltssm_downstream.sv -- not re-derived/guessed.
"""
import cocotb
from cocotb.triggers import RisingEdge, ClockCycles

NUM_LANES = 4
ALL = (1 << NUM_LANES) - 1  # 0xF

LINK_NUM = 0x01  # link number the "endpoint" echoes back

# ---- ltssm_state_e encodings, from pcie_ltssm_downstream.sv's enum ----
ST_IDLE                = 0x00000
ST_DETECT              = 0x00001
ST_POLLING             = 0x00002
ST_CONFIGURATION       = 0x00003
ST_RECOVERY            = 0x00004
ST_L0                  = 0x00005
ST_L0s                 = 0x00006
ST_L1                  = 0x00007
ST_L2                  = 0x00008
ST_DISABLED            = 0x00009
ST_LOOPBACK            = 0x0000A
ST_HOT_RESET           = 0x0000B

ST_DETECT_WAIT_ONE_MS  = 0x00021
ST_DETECT_QUIET        = 0x00041
ST_DETECT_ACTIVE       = 0x00061
ST_DETECT_RX           = 0x00081

ST_POLLING_ACTIVE      = 0x00022
ST_POLLING_CONFIG      = 0x00042  # ST_POLLING_CONFIGURATION in the RTL
ST_POLLING_COMPLIANCE  = 0x00062

ST_CFG_LW_START        = 0x00023  # ST_CONFIGURATION_LINKWIDTH_START
ST_CFG_LW_ACCEPT       = 0x00043  # ST_CONFIGURATION_LINKWIDTH_ACCEPT
ST_CFG_LN_ACCEPT       = 0x00063  # ST_CONFIGURATION_LANENUM_ACCEPT
ST_CFG_LN_WAIT         = 0x00083  # ST_CONFIGURATION_LANENUM_WAIT
ST_CFG_COMPLETE        = 0x000A3  # ST_CONFIGURATION_COMPLETE
ST_CFG_IDLE            = 0x000E3  # ST_CONFIGURATION_IDLE

ST_RECOVERY_RCVR_LOCK          = 0x00024
ST_RECOVERY_RCVR_LOCK_TIMEOUT  = 0x00044
ST_RECOVERY_EQUAL              = 0x00064
ST_RECOVERY_SPEED              = 0x00084
ST_RECOVERY_SPEED_WAIT         = 0x000A4
ST_RECOVERY_SPEED_EIEOS        = 0x000C4
ST_RECOVERY_RCVR_CFG           = 0x000E4
ST_RECOVERY_IDLE               = 0x00104
ST_RECOVERY_COMPLETE           = 0x00124
ST_RECOVERY_EXT_SYNCH          = 0x00144
ST_RECOVERY_SEND_SDS           = 0x00164
ST_RECOVERY_EQUAL_PHASE_0      = 0x00184
ST_RECOVERY_EQUAL_PHASE_1      = 0x001A4
ST_RECOVERY_EQUAL_PHASE_2      = 0x001C4
ST_RECOVERY_EQUAL_PHASE_3      = 0x001E4

# phy_rxstatus_i is MAX_NUM_LANES*3 bits wide, 3'b011 per lane is the
# "receiver ready" encoding lane_status checks for (pcie_ltssm_downstream.sv,
# `if (phy_phystatus_i[i] && phy_rxstatus_i[3*i+:3] == 3'b011)` latches
# lane_active_r[i]). 0x6DB = 4 lanes x 3'b011.
RXSTATUS_ALL_OK = 0x6DB

# ---- pcie_tsos_t / rate_id_t struct layout, from src/packages/pcie_phy_pkg.sv ----
# See test_ltssm_linkup.py's original header comment for the full derivation;
# summary: pcie_tsos_t is a 128-bit packed struct (first field declared =
# MSB), link_num/lane_num/rate_id sit at byte offsets 8/16/32 from bit 0.
# rate_id_t byte: bit7=speed_change, bit6=autonomous_change, bits[5:1]=rate
# (rate_speed_e), bit0=rsvd0 -- verified against gen1_basic/gen2_basic/
# gen3_basic in pcie_phy_pkg.sv.
# PAD / PAD_ (train_seq_e.PAD_ / phy_layer_special_symbols_e.PAD) = 8'hf7.
PAD = 0xF7
TSOS_WIDTH = 128

# rate_speed_e.gen1 = 5'b00001 (pcie_phy_pkg.sv) -- the 5-bit "rate" subfield
# of rate_id_t, i.e. gen1_basic (8'b000_00010) with speed_change forced 0.
GEN1_RATE = 0x01


# ---- TS Symbol 5 (Training Control), Base 2.1 Table 4-2 ----
# Spec bit assignment: 0 Hot Reset, 1 Disable Link, 2 Loopback,
# 3 Disable Scrambling, 4 Compliance Receive, 7:5 Reserved.
# NOTE: training_ctrl_t (pcie_phy_pkg.sv:209-215) is
#   {rsvd[7:4], scramble[3], loopback[2], dis_link[1], hot_rst[0]}
# so the RTL has no named member for Compliance Receive -- bit 4 falls inside
# its rsvd field. These masks are taken from the SPEC, not from the struct,
# which is why COMPLIANCE_RCV has no RTL counterpart to be checked against.
S5_HOT_RESET      = 1 << 0
S5_DISABLE_LINK   = 1 << 1
S5_LOOPBACK       = 1 << 2
S5_DISABLE_SCRAM  = 1 << 3
S5_COMPLIANCE_RCV = 1 << 4


def pack_tsos(link_num=None, lane_num=None, rate=0, speed_change=0,
              train_ctrl=0):
    """Build one pcie_tsos_t as an int. None -> PAD for link/lane.

    train_ctrl is TS Symbol 5 as a raw byte (see the S5_* masks above);
    it defaults to 0, so every pre-existing caller is unaffected."""
    ln = PAD if link_num is None else link_num
    la = PAD if lane_num is None else lane_num
    rate_id_byte = ((speed_change & 0x1) << 7) | ((rate & 0x1F) << 1)
    v = 0
    v |= (train_ctrl & 0xFF)   << 40  # train_ctrl (Symbol 5), offset 40
    v |= (rate_id_byte & 0xFF) << 32  # rate_id   field, offset 32
    v |= (la & 0xFF)           << 16  # lane_num  field, offset 16
    v |= (ln & 0xFF)           << 8   # link_num  field, offset 8
    # com, n_fts, train_ctrl, ts_s6..9, ts_id all left as 0 -- unused by the
    # link/lane/rate compare logic in pcie_ltssm_downstream.sv.
    return v


def pack_tsos_all_lanes(**kw):
    """Same TS on all lanes; lane_num='index' means per-lane index."""
    v = 0
    for i in range(NUM_LANES):
        f = dict(kw)
        if f.get("lane_num") == "index":
            f["lane_num"] = i
        v |= pack_tsos(**f) << (i * TSOS_WIDTH)
    return v


# ---- train_seq_e discriminator bytes (pcie_phy_pkg.sv) ----
# gen_ts_os() writes TSOS_ into ts_s6..ts_s9 and every ts_id[0..5] byte, so a
# DUT-originated ordered set carries the TS type there. pack_tsos() leaves them
# 0 (the RTL RX keys TS1/TS2 off the ts1_valid_i/ts2_valid_i strobes, not these
# bytes), so the discriminator is only meaningful on DUT *output* (ordered_set_o).
TS1 = 0x4A
TS2 = 0x45


def unpack_tsos(value):
    """Inverse of pack_tsos() for a single pcie_tsos_t (128-bit int).

    Field offsets are the same packed layout pack_tsos() writes to, read back
    out; derivation in the struct-layout comment above. Returns link_num,
    lane_num, rate/speed_change (from the rate_id byte), train_ctrl, and a
    TS1/TS2 discriminator taken from ts_s6 (offset 48) cross-checked against
    ts_id[0] (offset 80) -- both are written to TSOS_ by gen_ts_os().
    """
    value &= (1 << TSOS_WIDTH) - 1
    b = lambda off: (value >> off) & 0xFF          # noqa: E731
    rate_id_byte = b(32)
    ts_s6 = b(48)
    ts_id0 = b(80)
    # ts_s6 and ts_id0 agree on a real DUT TS; prefer ts_s6, note disagreement.
    if ts_s6 in (TS1, TS2):
        ts_type = ts_s6
    elif ts_id0 in (TS1, TS2):
        ts_type = ts_id0
    else:
        ts_type = None
    return {
        "com":              b(0),
        "link_num":         b(8),
        "lane_num":         b(16),
        "n_fts":            b(24),
        "rate_id_byte":     rate_id_byte,
        "speed_change":    (rate_id_byte >> 7) & 0x1,
        "autonomous_change": (rate_id_byte >> 6) & 0x1,
        "rate":            (rate_id_byte >> 1) & 0x1F,
        "train_ctrl":       b(40),
        "ts_s6":            ts_s6,
        "ts_id0":           ts_id0,
        "ts_type":          ts_type,          # TS1, TS2, or None
        "is_ts1":           ts_type == TS1,
        "is_ts2":           ts_type == TS2,
    }


def _verify_unpack_roundtrip():
    """Standalone self-check: pack_tsos() -> unpack_tsos() must round-trip the
    link/lane/rate/speed_change fields for every representative combination.
    Runs at import so it fails loudly before any test uses the unpacker.
    ts_type is NOT checked here: pack_tsos() deliberately leaves the TS
    discriminator bytes 0 (that path is exercised only on DUT output), so a
    packed value has ts_type None by construction."""
    cases = [
        dict(link_num=None, lane_num=None, rate=0,          speed_change=0,
             train_ctrl=0),
        dict(link_num=0x01, lane_num=None, rate=GEN1_RATE,  speed_change=0,
             train_ctrl=0),
        dict(link_num=0x01, lane_num=0,    rate=GEN1_RATE,  speed_change=0,
             train_ctrl=S5_COMPLIANCE_RCV),
        dict(link_num=0x5A, lane_num=0x03, rate=0x07,       speed_change=1,
             train_ctrl=S5_LOOPBACK | S5_DISABLE_SCRAM),
        dict(link_num=0xFF, lane_num=0xFE, rate=0x1F,       speed_change=1,
             train_ctrl=0xFF),
    ]
    for c in cases:
        u = unpack_tsos(pack_tsos(**c))
        exp_link = PAD if c["link_num"] is None else c["link_num"]
        exp_lane = PAD if c["lane_num"] is None else c["lane_num"]
        assert u["link_num"] == exp_link, (c, u["link_num"], exp_link)
        assert u["lane_num"] == exp_lane, (c, u["lane_num"], exp_lane)
        assert u["rate"] == c["rate"], (c, u["rate"])
        assert u["speed_change"] == c["speed_change"], (c, u["speed_change"])
        assert u["train_ctrl"] == c["train_ctrl"], (c, u["train_ctrl"])
        assert u["ts_type"] is None, (c, u["ts_type"])
    # Negative control: the Symbol 5 byte must land in its own field and not
    # bleed into a neighbour. If train_ctrl were written at the wrong offset
    # this would silently corrupt rate_id or ts_s6 instead of failing.
    probe = unpack_tsos(pack_tsos(train_ctrl=0xFF))
    assert probe["train_ctrl"] == 0xFF, probe["train_ctrl"]
    assert probe["rate_id_byte"] == 0, probe["rate_id_byte"]
    assert probe["ts_s6"] == 0, probe["ts_s6"]
    return True


# Run the round-trip check at import -- fails loudly before any test body runs.
_UNPACK_ROUNDTRIP_OK = _verify_unpack_roundtrip()


async def os_tx_pulser(dut):
    """Emulate the PHY-TX 'ordered set transmitted' handshake: the FSM only
    advances its counters on this pulse. One pulse every few cycles."""
    while True:
        dut.ordered_set_tranmitted_i.value = 0
        await ClockCycles(dut.clk_i, 3)
        dut.ordered_set_tranmitted_i.value = 1
        await ClockCycles(dut.clk_i, 1)


STATE_NAMES = {v: k for k, v in globals().items() if k.startswith("ST_")}


async def wait_state(dut, state, timeout_cycles, name):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if int(dut.ltssm_state_o.value) == state:
            dut._log.info(f"reached {name}")
            return
    got = int(dut.ltssm_state_o.value)
    raise AssertionError(
        f"never reached {name}; ended in "
        f"{STATE_NAMES.get(got, hex(got))} ({got:#07x})")


def drive_idle_inputs(dut):
    dut.en_i.value = 0
    for s in ("is_timeout_i","recovery_i","extended_synch_i",
              "directed_speed_change_i","from_l0_i","phy_phystatus_rst_i"):
        getattr(dut, s).value = 0
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = 0
    dut.idle_valid_i.value = 0
    dut.polarity_inverted_i.value = 0
    dut.phy_rxstatus_i.value = 0
    dut.phy_phystatus_i.value = 0
    dut.receiver_detected_i.value = 0
    dut.phy_rxelecidle_i.value = 0
    dut.lane_status_i.value = 0
    dut.lanes_ts2_satisfied_i.value = 0
    dut.config_copmlete_ts2_i.value = 0
    dut.ordered_set_tranmitted_i.value = 0
    dut.ordered_set_i.value = 0


async def bring_up_link(dut):
    """Reset -> ... -> L0, with lane_active_r properly latched. Returns in L0."""
    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)

    assert int(dut.ltssm_state_o.value) == ST_IDLE
    assert int(dut.link_up_o.value) == 0

    # ---- IDLE -> DETECT_QUIET ----
    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")

    # ---- DETECT_QUIET -> DETECT_ACTIVE via elec-idle *exit edge* (1 -> 0) ----
    dut.phy_rxelecidle_i.value = ALL
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")
    assert int(dut.phy_txdetectrx_o.value) == 1, "RC must request rx-detect"

    # ---- DETECT_ACTIVE -> POLLING: phystatus pulse + all receivers found.
    # phy_rxstatus_i must already read 3'b011 per lane *before* the
    # phy_phystatus_i pulse -- lane_status's always_comb latches
    # lane_active_r[i] on (phy_phystatus_i[i] && phy_rxstatus_i[3*i+:3]==3'b011)
    # combinationally, so ordering here matters. ----
    dut.receiver_detected_i.value = ALL
    dut.phy_rxstatus_i.value = RXSTATUS_ALL_OK
    dut.phy_phystatus_i.value = ALL
    await ClockCycles(dut.clk_i, 3)
    dut.phy_phystatus_i.value = 0
    cocotb.start_soon(os_tx_pulser(dut))
    await wait_state(dut, ST_POLLING_ACTIVE, 100, "POLLING_ACTIVE")

    # ---- POLLING_ACTIVE -> POLLING_CONFIGURATION ----
    # Endpoint answers with TS1s, link=PAD lane=PAD; FSM needs ts1_cnt==8 per
    # lane AND >= MinTS1sPolling(24, fast mode) transmitted after first rx'd TS1.
    dut.ordered_set_i.value = pack_tsos_all_lanes(link_num=None, lane_num=None)
    dut.ts1_valid_i.value = ALL
    await wait_state(dut, ST_POLLING_CONFIG, 2000, "POLLING_CONFIGURATION")

    # ---- POLLING_CONFIGURATION -> CFG_LINKWIDTH_START (TS2s, PAD/PAD) ----
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = ALL
    await wait_state(dut, ST_CFG_LW_START, 2000, "CFG_LINKWIDTH_START")

    # ---- LINKWIDTH_START -> ACCEPT: TS1 with link_num REAL, lane PAD ----
    dut.ts2_valid_i.value = 0
    dut.ordered_set_i.value = pack_tsos_all_lanes(link_num=LINK_NUM, lane_num=None)
    dut.ts1_valid_i.value = ALL
    await wait_state(dut, ST_CFG_LW_ACCEPT, 1000, "CFG_LINKWIDTH_ACCEPT")

    # ---- ACCEPT -> LANENUM_WAIT (link_lanes_formed; keep same TS1s) ----
    await wait_state(dut, ST_CFG_LN_WAIT, 1000, "CFG_LANENUM_WAIT")

    # ---- LANENUM_WAIT -> LANENUM_ACCEPT: lane_num changes from saved PAD ----
    dut.ordered_set_i.value = pack_tsos_all_lanes(link_num=LINK_NUM, lane_num="index")
    await wait_state(dut, ST_CFG_LN_ACCEPT, 1000, "CFG_LANENUM_ACCEPT")

    # ---- LANENUM_ACCEPT -> COMPLETE (link matches, lane != PAD) ----
    await wait_state(dut, ST_CFG_COMPLETE, 1000, "CFG_COMPLETE")

    # ---- COMPLETE -> CFG_IDLE: endpoint sends TS2 w/ matching link+lane ----
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = ALL   # same ordered_set_i: link=LINK_NUM, lane=index
    await wait_state(dut, ST_CFG_IDLE, 2000, "CFG_IDLE")

    # ---- CFG_IDLE -> L0: endpoint sends idles ----
    dut.ts2_valid_i.value = 0
    dut.idle_valid_i.value = ALL
    await wait_state(dut, ST_L0, 2000, "L0")
    dut.idle_valid_i.value = 0


# ==========================================================================
#  Root-Complex-mode driver: TB plays Endpoint, DUT plays Root Complex.
#  x1 (MAX_NUM_LANES=1) only. Reactive -- it samples what the DUT actually
#  originates on ordered_set_o, asserts it, then echoes on ordered_set_i.
#  Nothing about the DUT's transmitted sequence is hardcoded/scripted: every
#  link_num/lane_num/TS-type the DUT sends is read back and checked, so a DUT
#  transmitting garbage fails the assertion instead of being rubber-stamped.
# ==========================================================================

# x1 single-lane masks (this driver is x1-scoped; do not reuse the 4-lane ALL).
LANE0_MASK      = 0x1
RXSTATUS_OK_X1  = 0b011   # one lane x 3'b011, the "receiver ready" encoding


def _dump_rc_trace(dut, trace, note):
    """On hang/assertion-failure, dump the per-state transmit trace plus the
    DUT-internal counters/flags that decide each Configuration exit."""
    dut._log.error(f"==== RC Configuration FAILURE: {note} ====")
    dut._log.error("---- per-state ordered_set_o the DUT transmitted ----")
    for t in trace:
        dut._log.error(
            f"  {t['name']:17s} entry-tx: ts={t['ts']} "
            f"link={t['link']:#04x} lane={t['lane']:#04x}"
            + (f"  exit-tx: ts={t['exit_ts']} link={t['exit_link']:#04x} "
               f"lane={t['exit_lane']:#04x}" if 'exit_ts' in t else ""))
    cur = int(dut.ltssm_state_o.value)
    dut._log.error(f"---- hang point: state={STATE_NAMES.get(cur, hex(cur))} "
                   f"({cur:#07x}) ----")

    def rd(path):
        try:
            return hex(int(eval("dut." + path + ".value")))  # noqa: S307
        except Exception as e:                                # noqa: BLE001
            return f"<n/a: {type(e).__name__}>"
    for sig in ("link_number_selected", "link_width_satisfied",
                "link_lanes_formed", "link_lanes_nums_match",
                "ts1_lanenum_wait_satisfied", "lane_num_formed",
                "lane_active_r", "ordered_set_sent_cnt_r"):
        dut._log.error(f"  {sig:28s} = {rd(sig)}")
    for sig in ("gen_cnt_ts1[0].ts1_cnt", "gen_cnt_ts1[0].ts2_cnt",
                "gen_cnt_ts1[0].lane_in_save"):
        dut._log.error(f"  {sig:28s} = {rd(sig)}")


def _assert_tx(dut, trace, name, exp_ts, exp_link, exp_lane):
    """Sample ordered_set_o, record it, and assert the DUT originated exactly
    the (TS type, link_num, lane_num) the spec requires for this state."""
    u = unpack_tsos(int(dut.ordered_set_o.value))
    trace.append({"name": name, "ts": "TS1" if u["is_ts1"] else
                  ("TS2" if u["is_ts2"] else f"?{u['ts_s6']:#04x}"),
                  "link": u["link_num"], "lane": u["lane_num"]})
    ts_ok = u["is_ts1"] if exp_ts == TS1 else u["is_ts2"]
    if not (ts_ok and u["link_num"] == exp_link and u["lane_num"] == exp_lane):
        _dump_rc_trace(dut, trace,
                       f"{name}: DUT transmitted the wrong ordered set")
        raise AssertionError(
            f"{name}: expected {'TS1' if exp_ts == TS1 else 'TS2'} "
            f"link={exp_link:#04x} lane={exp_lane:#04x}; got "
            f"ts={trace[-1]['ts']} link={u['link_num']:#04x} "
            f"lane={u['lane_num']:#04x}")
    return u


async def bring_up_link_rc(dut):
    """Reset -> ... -> L0 with the DUT as Root Complex (IS_ROOT_PORT=1) and the
    TB as its Endpoint link partner. x1 only. Returns in L0."""
    assert _UNPACK_ROUNDTRIP_OK  # unpacker self-check ran at import
    LINK = LINK_NUM              # the Link Number the DUT (RC) originates
    trace = []

    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    assert int(dut.ltssm_state_o.value) == ST_IDLE
    assert int(dut.link_up_o.value) == 0

    # ---- Detect + Polling: role-neutral, same handshake as bring_up_link,
    #      x1 masks. ----
    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")

    dut.phy_rxelecidle_i.value = LANE0_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")
    assert int(dut.phy_txdetectrx_o.value) == 1, "RC must request rx-detect"

    dut.receiver_detected_i.value = LANE0_MASK
    dut.phy_rxstatus_i.value = RXSTATUS_OK_X1
    dut.phy_phystatus_i.value = LANE0_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_phystatus_i.value = 0
    cocotb.start_soon(os_tx_pulser(dut))
    await wait_state(dut, ST_POLLING_ACTIVE, 100, "POLLING_ACTIVE")

    # Polling.Active: EP answers TS1 PAD/PAD (role-neutral).
    dut.ordered_set_i.value = pack_tsos(link_num=None, lane_num=None)
    dut.ts1_valid_i.value = LANE0_MASK
    await wait_state(dut, ST_POLLING_CONFIG, 2000, "POLLING_CONFIGURATION")

    # Polling.Config: EP answers TS2 PAD/PAD (role-neutral).
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = LANE0_MASK
    await wait_state(dut, ST_CFG_LW_START, 2000, "CFG_LINKWIDTH_START")

    # ---- Configuration: DUT (RC) originates; TB samples, asserts, echoes. ----
    # (state, name, DUT-transmits TS/link/lane, echo strobe, echo pack kwargs)
    steps = [
        (ST_CFG_LW_START,  "LINKWIDTH_START",  TS1, LINK, PAD,
         "ts1", dict(link_num=LINK, lane_num=None)),
        (ST_CFG_LW_ACCEPT, "LINKWIDTH_ACCEPT", TS1, LINK, PAD,
         "ts1", dict(link_num=LINK, lane_num=None)),
        (ST_CFG_LN_WAIT,   "LANENUM_WAIT",     TS1, LINK, 0,
         "ts1", dict(link_num=LINK, lane_num=0)),
        (ST_CFG_LN_ACCEPT, "LANENUM_ACCEPT",   TS1, LINK, 0,
         "ts1", dict(link_num=LINK, lane_num=0)),
        (ST_CFG_COMPLETE,  "COMPLETE",         TS2, LINK, 0,
         "ts2", dict(link_num=LINK, lane_num=0)),
    ]
    next_names = ["CFG_LINKWIDTH_ACCEPT", "CFG_LANENUM_WAIT",
                  "CFG_LANENUM_ACCEPT", "CFG_COMPLETE", "CFG_IDLE"]
    next_states = [ST_CFG_LW_ACCEPT, ST_CFG_LN_WAIT, ST_CFG_LN_ACCEPT,
                   ST_CFG_COMPLETE, ST_CFG_IDLE]

    for i, (st, name, exp_ts, exp_link, exp_lane, strobe, echo) in \
            enumerate(steps):
        # DUT is already in this state (waited for it). Settle one cycle so
        # ordered_set_o (registered from the prior state's exit build) is stable.
        await RisingEdge(dut.clk_i)
        _assert_tx(dut, trace, name, exp_ts, exp_link, exp_lane)

        # Echo the ordered set that closes this state's RX exit condition.
        dut.ordered_set_i.value = pack_tsos(**echo)
        dut.ts1_valid_i.value = LANE0_MASK if strobe == "ts1" else 0
        dut.ts2_valid_i.value = LANE0_MASK if strobe == "ts2" else 0

        try:
            await wait_state(dut, next_states[i], 4000, next_names[i])
        except AssertionError as e:
            # Record what the DUT was transmitting at the hang, then dump.
            u = unpack_tsos(int(dut.ordered_set_o.value))
            trace[-1].update(exit_ts=("TS1" if u["is_ts1"] else
                             ("TS2" if u["is_ts2"] else f"?{u['ts_s6']:#04x}")),
                             exit_link=u["link_num"], exit_lane=u["lane_num"])
            _dump_rc_trace(dut, trace, f"stuck in {name}: {e}")
            raise

    # ---- Configuration.Idle: DUT transmits a zeroed/idle OS; EP sends idles. ----
    await RisingEdge(dut.clk_i)
    u = unpack_tsos(int(dut.ordered_set_o.value))
    trace.append({"name": "IDLE", "ts": "idle/zero",
                  "link": u["link_num"], "lane": u["lane_num"]})
    if u["is_ts1"] or u["is_ts2"]:
        _dump_rc_trace(dut, trace, "IDLE: DUT still transmitting a TS ordered set")
        raise AssertionError(
            f"CFG_IDLE: expected idle/zeroed OS, got "
            f"{'TS1' if u['is_ts1'] else 'TS2'}")
    dut.ts1_valid_i.value = 0
    dut.ts2_valid_i.value = 0
    dut.ordered_set_i.value = 0
    dut.idle_valid_i.value = LANE0_MASK
    try:
        await wait_state(dut, ST_L0, 4000, "L0")
    except AssertionError as e:
        _dump_rc_trace(dut, trace, f"stuck in CFG_IDLE: {e}")
        raise
    dut.idle_valid_i.value = 0
