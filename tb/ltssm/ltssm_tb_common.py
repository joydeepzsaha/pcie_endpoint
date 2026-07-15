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


def pack_tsos(link_num=None, lane_num=None, rate=0, speed_change=0):
    """Build one pcie_tsos_t as an int. None -> PAD for link/lane."""
    ln = PAD if link_num is None else link_num
    la = PAD if lane_num is None else lane_num
    rate_id_byte = ((speed_change & 0x1) << 7) | ((rate & 0x1F) << 1)
    v = 0
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
