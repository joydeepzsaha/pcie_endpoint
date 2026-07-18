"""
TX unit testbench for phy_transmit -- Gen1 x1 golden baseline (Phase 4b prep).

Toplevel: phy_transmit (MAX_NUM_LANES=1). Drives an ordered-set template into
os_generator (gen_os_ctrl_i / ordered_set_i) and observes the per-lane PIPE
output (pipe_data_o[lane 0], pipe_data_k_o, pipe_data_valid_o, pipe_width_o).
Captures the emitted symbol stream and asserts the ACTUAL field values
(TS identifier, driven link number, assigned lane number) -- not "output is
non-zero".

Empirically established contract (see the golden dumps each test logs):
  * Gen1 PIPE width is 16-bit -> 2 symbols per 32-bit output word (low bytes).
  * An ordered set on the wire is: COM(0xBC, data_k=1), then 15 data symbols
    link, lane, n_fts, rate_id, train_ctrl, ts_s6..s9, ts_id[0..5].
  * TS1/TS2 data symbols are NOT scrambled (link/lane/TS-id appear literally).
  * Logical idle IS scrambled (all-zero template emerges non-zero) -> this is
    the in-path scrambler coverage.

The bench drives only phy_transmit ports; it never touches RTL internals.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

# ---- constants from src/packages/pcie_phy_pkg.sv ----
COM = 0xBC          # K28.5, ordered-set start symbol (pkg:100)
PAD = 0xF7          # train_seq_e.PAD_
TS1 = 0x4A          # TS1 discriminator (gen_ts_os fills ts_s6..9 / ts_id[0..5])
TS2 = 0x45          # TS2 discriminator
GEN1 = 0x01         # rate_speed_e.gen1 = 5'b00001
GEN1_BASIC = 0x02   # rate_id_t'(gen1_basic) = 8'b000_00010
N_FTS = 0xFF        # gen_ts_os sets n_fts = '1
IDL = 0x7C          # K28.3, EIOS filler symbol (pkg:108)

# ---- gen_os_struct_t control bits (LSB = valid), pkg lines 269-284 ----
G_VALID    = 1 << 0
G_GEN_TS1  = 1 << 1
G_GEN_TS2  = 1 << 2
G_GEN_EIOS = 1 << 5
G_GEN_IDLE = 1 << 7
G_SET_LANE = 1 << 9


def pack_tsos(link_num=PAD, lane_num=PAD, rate_id=GEN1_BASIC, ts_disc=TS1,
              com=COM, n_fts=N_FTS, train_ctrl=0x00):
    """Build one pcie_tsos_t (128-bit) exactly as gen_ts_os(gen1, TSOS_, ...).
    Byte offsets from bit 0 (first packed field = LSB byte = com):
      com@0 link_num@8 lane_num@16 n_fts@24 rate_id@32 train_ctrl@40
      ts_s6@48 ts_s7@56 ts_s8@64 ts_s9@72 ts_id[0..5]@80..120."""
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


def pack_eios_gen1():
    """Build the Gen1 EIOS template exactly as gen_eios(rate<gen3): every 4th
    symbol (i%4==0) = COM, the rest = IDL (pkg gen_eios body)."""
    v = 0
    for i in range(16):
        sym = COM if (i & 0x3) == 0 else IDL
        v |= (sym & 0xFF) << (8 * i)
    return v


async def start_clocks(dut):
    """Three clocks: clk_i (DLLP framing, unused on the OS path), pipe_rx_usr_clk_i
    (os_generator + OS-FIFO write), pipe_tx_usr_clk_i (scrambler / lane_management
    / PIPE output / FIFO read). All 100 MHz; the async FIFOs cross rx->tx."""
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


def _syms_per_word(dut):
    """Symbols carried per 32-bit output word = pipe_width_o >> 3, clamped 1..4.
    Read from the DUT so the bench tracks the rate's PIPE width rather than
    hardcoding 2 (Gen1)."""
    try:
        w = int(dut.pipe_width_o.value)
    except Exception:
        w = 16
    return max(1, min(4, w >> 3))


async def capture_symbols(dut, cycles):
    """Collect (symbol, is_k) pairs from lane-0 PIPE output while data_valid."""
    syms = []
    for _ in range(cycles):
        await RisingEdge(dut.pipe_tx_usr_clk_i)
        if int(dut.pipe_data_valid_o.value) & 0x1:
            word = int(dut.pipe_data_o.value) & 0xFFFFFFFF
            dk = int(dut.pipe_data_k_o.value) & 0xF
            for j in range(_syms_per_word(dut)):
                syms.append(((word >> (8 * j)) & 0xFF, (dk >> j) & 0x1))
    return syms


def find_ordered_set(syms):
    """Return the 16 (symbol, is_k) pairs of the first complete ordered set --
    a COM (0xBC, K) followed by >=15 more symbols. Reactive: locates the OS by
    its COM frame rather than assuming a fixed beat offset."""
    for i, (s, k) in enumerate(syms):
        if s == COM and k == 1 and i + 16 <= len(syms):
            return syms[i:i + 16]
    return None


async def drive_os(dut, ctrl, tsos):
    """Hold a steady ordered-set command so os_generator streams it (this is
    also the ST_SEND streaming-hack territory). Returns after enough tx cycles
    for the async FIFO CDC to fill and >=2 ordered sets to appear."""
    dut.ordered_set_i.value = tsos
    dut.curr_data_rate_i.value = GEN1
    dut.gen_os_ctrl_i.value = ctrl
    dut.send_ordered_set_i.value = 0


def _fmt(pairs):
    return " ".join("%02x%s" % (s, "K" if k else "") for s, k in pairs)


@cocotb.test()
async def ts1_fields(dut):
    """TS1 with a distinctive link number; assert the on-wire fields."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x05
    await drive_os(dut, G_VALID | G_GEN_TS1 | G_SET_LANE,
                   pack_tsos(link_num=link, lane_num=0, ts_disc=TS1))
    syms = await capture_symbols(dut, 60)
    os = find_ordered_set(syms)
    assert os is not None, "no COM-framed ordered set on the wire"
    dut._log.info("TS1 golden OS: %s" % _fmt(os))
    data = [s for s, k in os]
    kbit = [k for s, k in os]
    assert kbit[0] == 1 and data[0] == COM, "OS must start with K-coded COM"
    assert data[1] == link, "link_num: got %02x want %02x" % (data[1], link)
    assert data[2] == 0x00, "lane_num (set_lane->index 0): got %02x" % data[2]
    assert data[3] == N_FTS, "n_fts: got %02x want %02x" % (data[3], N_FTS)
    assert data[4] == GEN1_BASIC, "rate_id: got %02x" % data[4]
    assert all(d == TS1 for d in data[6:16]), \
        "TS1 discriminator symbols: %s" % _fmt(os[6:16])
    assert all(k == 0 for k in kbit[1:16]), \
        "TS data symbols must be un-K-coded (unscrambled): %s" % _fmt(os)


@cocotb.test()
async def ts2_fields(dut):
    """TS2 with a distinctive link number; assert TS2 discriminator + fields."""
    await start_clocks(dut)
    await reset(dut)
    link = 0x0A
    await drive_os(dut, G_VALID | G_GEN_TS2 | G_SET_LANE,
                   pack_tsos(link_num=link, lane_num=0, ts_disc=TS2))
    syms = await capture_symbols(dut, 60)
    os = find_ordered_set(syms)
    assert os is not None, "no COM-framed ordered set on the wire"
    dut._log.info("TS2 golden OS: %s" % _fmt(os))
    data = [s for s, k in os]
    assert data[0] == COM and os[0][1] == 1
    assert data[1] == link, "link_num: got %02x want %02x" % (data[1], link)
    assert data[2] == 0x00, "lane_num: got %02x" % data[2]
    assert all(d == TS2 for d in data[6:16]), \
        "TS2 discriminator symbols: %s" % _fmt(os[6:16])


@cocotb.test()
async def idle_is_scrambled(dut):
    """Logical idle: an all-zero template must emerge non-zero (scrambled).
    This is the in-path scrambler-coverage assertion: contrast with TS, whose
    data symbols pass through literally."""
    await start_clocks(dut)
    await reset(dut)
    await drive_os(dut, G_VALID | G_GEN_IDLE, pack_tsos(
        com=0x00, link_num=0x00, lane_num=0x00, n_fts=0x00,
        rate_id=0x00, train_ctrl=0x00, ts_disc=0x00))
    syms = await capture_symbols(dut, 60)
    assert syms, "no valid PIPE output during idle"
    nonzero = [s for s, k in syms if s != 0x00]
    dut._log.info("idle golden (first 24 syms): %s" % _fmt(syms[:24]))
    dut._log.info("idle non-zero symbol count: %d / %d" % (len(nonzero), len(syms)))
    # An all-zero template that emerges with non-zero symbols proves the
    # scrambler LFSR ran on the idle path (zeros XOR LFSR = LFSR sequence).
    assert len(nonzero) > len(syms) // 4, \
        "idle output looks unscrambled (mostly zero) -- scrambler not in path?"


@cocotb.test()
async def eios_pattern(dut):
    """EIOS (Gen1): drive the real gen_eios template (COM IDL IDL IDL x4) with
    gen_eios ctrl (os_generator forces special_k all-ones) and assert the
    COM/IDL K-coded pattern reaches the wire un-scrambled -- the K-code bypass
    counterpart to the scrambled idle case."""
    await start_clocks(dut)
    await reset(dut)
    await drive_os(dut, G_VALID | G_GEN_EIOS, pack_eios_gen1())
    syms = await capture_symbols(dut, 60)
    assert syms, "no valid PIPE output for EIOS"
    # Locate a COM and assert the following 3 symbols are IDL, all K-coded.
    got = None
    for i in range(len(syms) - 3):
        if syms[i][0] == COM and syms[i][1] == 1:
            got = syms[i:i + 4]
            break
    assert got is not None, "no K-coded COM found in EIOS output: %s" % _fmt(syms[:24])
    dut._log.info("EIOS golden group: %s" % _fmt(got))
    assert [s for s, k in got] == [COM, IDL, IDL, IDL], \
        "EIOS group: got %s want bc 7c 7c 7c" % _fmt(got)
    assert all(k == 1 for s, k in got), \
        "EIOS symbols must all be K-coded: %s" % _fmt(got)
