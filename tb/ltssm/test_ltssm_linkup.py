"""
Link-up test for pcie_ltssm_downstream (downstream/RC-side LTSSM).
Drives the control/status handshake a link partner + PIPE PHY would produce,
and asserts the state machine walks Detect -> Polling -> Configuration -> L0.
Requires SIM_FAST_LINK=1 (verilate_fast target).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, with_timeout

NUM_LANES = 4
ALL = (1 << NUM_LANES) - 1  # 0xF

# ltssm_state_o encodings (from the enum in pcie_ltssm_downstream.sv)
ST_IDLE                = 0x00000
ST_DETECT_QUIET        = 0x00041
ST_DETECT_ACTIVE       = 0x00061
ST_POLLING_ACTIVE      = 0x00022
ST_POLLING_CONFIG      = 0x00042
ST_CFG_LW_START        = 0x00023
ST_CFG_LW_ACCEPT       = 0x00043
ST_CFG_LN_ACCEPT       = 0x00063
ST_CFG_LN_WAIT         = 0x00083
ST_CFG_COMPLETE        = 0x000A3
ST_CFG_IDLE            = 0x000E3
ST_L0                  = 0x00005

LINK_NUM = 0x01  # link number the "endpoint" echoes back

# ---- struct layout, read directly from src/packages/pcie_phy_pkg.sv ----
#
# pcie_tsos_t is a SystemVerilog packed struct. In a packed struct the FIRST
# declared field is the MOST significant bit range and the LAST declared
# field is the LEAST significant (bit 0). Declaration order (top -> bottom):
#
#   ts_generic_symbol_t [5:0]   ts_id;        // 48 bits  (MSB side)
#   ts1_symbol9_t               ts_s9;        //  8 bits
#   ts1_symbol8_t               ts_s8;        //  8 bits
#   ts1_symbol7_t               ts_s7;        //  8 bits
#   ts_symbol6_union_t          ts_s6;        //  8 bits
#   training_ctrl_t             train_ctrl;   //  8 bits
#   rate_id_t                   rate_id;      //  8 bits
#   logic [7:0]                 n_fts;        //  8 bits
#   logic [7:0]                 lane_num;     //  8 bits
#   logic [7:0]                 link_num;     //  8 bits
#   phy_layer_special_symbols_e com;          //  8 bits  (LSB side, bits [7:0])
#
# -> total width 48 + 8*10 = 128 bits, matching pcie_ordered_set_t (16 bytes),
#    which pcie_tsos_t is directly cast to/from in pcie_phy_pkg.sv (gen_ts_os()).
#
# Bit offsets from LSB (0) upward, walking the declaration in reverse:
#   com        : bits [7:0]    offset 0
#   link_num   : bits [15:8]   offset 8
#   lane_num   : bits [23:16]  offset 16
#   n_fts      : bits [31:24]  offset 24
#   rate_id    : bits [39:32]  offset 32
#   train_ctrl : bits [47:40]  offset 40
#   ts_s6      : bits [55:48]  offset 48
#   ts_s7      : bits [63:56]  offset 56
#   ts_s8      : bits [71:64]  offset 64
#   ts_s9      : bits [79:72]  offset 72
#   ts_id      : bits [127:80] offset 80
#
# The DUT (pcie_ltssm_downstream.sv) only ever reads ordered_set_i[lane].link_num,
# .lane_num and .rate_id.{rate,speed_change} on the Detect->Polling->Configuration
# walk (grep confirms .ts_s6 is only inspected in the Recovery.RcvrCfg / equalization
# path, which this test never enters), so com/n_fts/train_ctrl/ts_s6-9/ts_id are left
# as 0 -- they don't gate any transition exercised here.
#
# rate_id_t (8 bits) is itself a packed struct, same MSB-first rule:
#   speed_change (1) | autonomous_change (1) | rate (5, rate_speed_e) | rsvd0 (1)
#   -> bit7=speed_change, bit6=autonomous_change, bits[5:1]=rate, bit0=rsvd0
# Verified against the rate_id_e "basic" constants in pcie_phy_pkg.sv:
#   gen1_basic = 8'b000_00010 -> bits[5:1]=00001 = gen1 (rate_speed_e 5'b00001) [OK]
#   gen2_basic = 8'b000_00110 -> bits[5:1]=00011 = gen2 (rate_speed_e 5'b00011) [OK]
#   gen3_basic = 8'b000_01110 -> bits[5:1]=00111 = gen3 (rate_speed_e 5'b00111) [OK]
#
# PAD / PAD_ : train_seq_e.PAD_ (line 35) and phy_layer_special_symbols_e.PAD
# (line 105) are both 8'hf7 (K23.7) -- the same symbol value under two enum
# names. It means "no link/lane number assigned yet" and is what the DUT
# compares link_num/lane_num against with `== PAD` / `!= PAD`.
PAD = 0xF7
TSOS_WIDTH = 128


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
    # Detect/Polling/Configuration compare logic in pcie_ltssm_downstream.sv.
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


async def wait_state(dut, state, timeout_cycles, name):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if int(dut.ltssm_state_o.value) == state:
            dut._log.info(f"reached {name}")
            return
    raise AssertionError(
        f"never reached {name}; stuck in {int(dut.ltssm_state_o.value):#07x}")


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


@cocotb.test()
async def run_test_linkup(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())  # 100 MHz
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

    # ---- DETECT_ACTIVE -> POLLING: phystatus pulse + all receivers found ----
    dut.receiver_detected_i.value = ALL
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

    # ---- stay in L0: stop all training traffic, link must stay up ----
    dut.idle_valid_i.value = 0
    await ClockCycles(dut.clk_i, 50)
    assert int(dut.ltssm_state_o.value) == ST_L0, "fell out of L0"
    assert int(dut.link_up_o.value) == 1, "link_up not asserted in L0"
    dut._log.info("LINK UP: full Detect->Polling->Config->L0 walk verified")
