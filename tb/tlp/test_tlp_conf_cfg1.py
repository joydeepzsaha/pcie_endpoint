"""D-1b -- CFG1 (Type 1 configuration) origination, requester level.

TLP_CMD_CFG_READ1 / TLP_CMD_CFG_WRITE1 through tlp_layer's command port:
on-wire goldens for CfgRd1/CfgWr1 (whole-DW0 compares -- see Trap A below),
the full (offset x byte_count) admission matrix re-proven for both new
commands (NOT inherited from the CFG0 matrix in test_tlp_conf_cfgbe), and
the anti-segmentation proof that an over-length CFG1 request is rejected
outright rather than split on command_limit.

TRAP A (docs/predictions/SPEC_PREDICTIONS_STAGE_D.md SS8.1): CfgRd1 differs from CfgRd0 in
exactly ONE bit -- dw0[4:0] is 0b00101 vs 0b00100 (PCIe Base 2.1 Table 2-3
p.58).  Fmt, DW1, DW2, byte enables, length and payload are all identical
between the two types (SS2.2.7 p.79 constrains Configuration Requests as a
single class).  An assertion that omits dw0[4:0] therefore passes identically
for a DUT that emits Type 0 when told to emit Type 1.  Countermeasures here:
  * golden_cfg_dw0(write, type1=False) -- the Type 1 golden is expressible,
    Type 0 remains the default so a CFG0 caller is unchanged;
  * cfg_read1_wire_golden asserts the builder itself puts the two goldens
    exactly one bit apart (dw0 XOR == 0x1) before using either;
  * both wire-golden tests compare the WHOLE DW0, not a field subset;
  * every admitted matrix shape re-checks dw0[4:0] == TYPE_CFG1.

SPEC-GOLDEN DISCIPLINE: every expected DW is hand-derived from the PCIe spec
config-request format; SPEC_FIRST_BE is a hand-enumerated table of the
First-DW-BE rule, not computed with the DUT's tlp_pkg helpers.

Spec anchors:
  CfgRd1/CfgWr1 fmt/type ........ PCIe Base 2.1 Table 2-3 p.58
  Length=1 / Last DW BE=0000 .... PCIe Base 2.1 SS2.2.7 p.79 (class rule,
                                  no Type 0/Type 1 distinction)
RTL cited (read, not assumed):
  tlp_cmd_e ......... src/tlp/tlp_pkg.sv, typedef tlp_cmd_e
  command-class predicates ...... src/tlp/tlp_requester.sv:82-110
  tlp_type/fmt select ........... src/tlp/tlp_requester.sv:138-149
  admission guard ............... src/tlp/tlp_requester.sv:208-222
  generator DW0/DW1/DW2 ......... src/tlp/tlp_generator.sv, the dw0 and dw2 assembly
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# tlp_cmd_e (src/tlp/tlp_pkg.sv, typedef tlp_cmd_e) -- D-1b appends the two CFG1 members
# at the tail, filling the logic [2:0] enum to exactly 8 of 8.
CMD_CFG_READ1 = 6
CMD_CFG_WRITE1 = 7

# tlp_fmt_e / tlp_type_e (src/tlp/tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CFG0 = 0b00100
TYPE_CFG1 = 0b00101

# tlp_error_e (src/tlp/tlp_pkg.sv:60-76): 7th member, zero-based ordinal 6.
TLP_ERR_BAD_LENGTH = 6

RID = 0x1234

# Target BDF for this file -- forced apart from every existing config golden:
# cfg0_spine uses bus=0x01 dev=0x02 fn=0x03 reg=0x10, conf_cfgbe uses raw
# 0x18, cfg1_spine uses bus=0x3B dev=0x1C fn=0x5.  Nothing degenerate: every
# subfield is nonzero so a dropped/aliased field cannot compare 0 == 0.
T1_BUS = 0x2A
T1_DEV = 0x11
T1_FN = 0x6


def cfg_addr(bus, dev, fn, reg_byte_offset, ext_reg=0):
    """Config-request address DW, standard PCIe layout (tlp_config_decoder.sv):
    [31:24]=Bus [23:19]=Device [18:16]=Function [11:8]=ExtReg [7:2]=Register#.
    The requester copies command_address_i into header.address
    (tlp_requester.sv:158) and the generator emits {address[31:2],2'b00}
    as DW2 (tlp_generator.sv, the dw2 assembly)."""
    return (((bus & 0xFF) << 24) | ((dev & 0x1F) << 19) | ((fn & 0x7) << 16)
            | ((ext_reg & 0xF) << 8) | (reg_byte_offset & 0xFC))


# --------------------------------------------------------------------------
# Spec-golden builders (hand-derived, independent of tlp_pkg)
# --------------------------------------------------------------------------
def golden_cfg_dw0(write, type1=False):
    """Whole DW0 of a config request per the generator bit map
    (tlp_generator.sv, the dw0 assembly): fmt=dw0[7:5], type=dw0[4:0], Length=1 always
    (SS2.2.7).  type1=False default keeps every CFG0 caller unchanged."""
    fmt = FMT_3DW_DATA if write else FMT_3DW_NO_DATA
    typ = TYPE_CFG1 if type1 else TYPE_CFG0
    return ((fmt & 0x7) << 5) | (typ & 0x1F) | (1 << 24)


def golden_dw1(rid, tag, first_be, last_be):
    """DW1 non-CPL: {rid, tag, last_be, first_be} (tlp_generator.sv, the dw0 length assignment)."""
    return ((rid & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | \
           ((last_be & 0xF) << 4) | (first_be & 0xF)


# Hand-enumerated First DW BE table for every (offset, byte_count) shape that
# fits inside one DW; every shape NOT in this table spills past the DW and
# must be rejected.  Same spec rule as the CFG0 matrix -- re-stated here, not
# imported, so this file proves CFG1 independently.
SPEC_FIRST_BE = {
    (0, 1): 0b0001, (0, 2): 0b0011, (0, 3): 0b0111, (0, 4): 0b1111,
    (1, 1): 0b0010, (1, 2): 0b0110, (1, 3): 0b1110,
    (2, 1): 0b0100, (2, 2): 0b1100,
    (3, 1): 0b1000,
}

OFFSETS = (0, 1, 2, 3)
BYTE_COUNTS = (1, 2, 3, 4)


# --------------------------------------------------------------------------
# Harness (same tlp_layer drive as test_tlp_conf_cfgbe -- all four FC
# preconditions plus requester_id/max_payload/max_read, or nothing transmits)
# --------------------------------------------------------------------------
def init_flow_control(dut):
    """Saturate VC0 credits: fc_initialized_i + fc_update_valid_i with
    non-zero NPH/NPD, or the credit manager (reset to zero,
    tlp_credit_manager.sv:67-73) never lets a single packet out."""
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1
    dut.fc_ph_i.value = 0xFF
    dut.fc_pd_i.value = 0xFFF
    dut.fc_nph_i.value = 0xFF
    dut.fc_npd_i.value = 0xFFF
    dut.fc_cplh_i.value = 0xFF
    dut.fc_cpld_i.value = 0xFFF


async def init_top(dut, max_payload=128, max_read=128):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    for handle in dut:
        if handle._name.endswith("_i") and handle._name not in {"clk_i", "rst_i"}:
            try:
                handle.value = 0
            except (AttributeError, ValueError):
                pass
    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1
    init_flow_control(dut)
    dut.requester_id_i.value = RID
    dut.completer_id_i.value = 0x5678
    dut.memory_enable_i.value = 1
    dut.extended_tag_enable_i.value = 0
    dut.max_payload_bytes_i.value = max_payload
    dut.max_read_bytes_i.value = max_read
    dut.m_dllp_axis_tready.value = 1
    dut.target_request_ready_i.value = 1
    dut.target_data_ready_i.value = 1
    dut.received_completion_ready_i.value = 1
    dut.received_completion_data_ready_i.value = 1
    dut.result_ready_i.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk_i)


class TxCapture:
    """Records every accepted TX beat, split into packets on tlast."""

    def __init__(self, dut):
        self.dut = dut
        self.packets = []
        self._cur = []

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            await Timer(1, units="ps")
            if int(self.dut.m_dllp_axis_tvalid.value) and int(self.dut.m_dllp_axis_tready.value):
                self._cur.append((int(self.dut.m_dllp_axis_tdata.value),
                                  int(self.dut.m_dllp_axis_tlast.value)))
                if self._cur[-1][1]:
                    self.packets.append(self._cur)
                    self._cur = []


class ErrCapture:
    """Records every command_error_valid_o pulse's code."""

    def __init__(self, dut):
        self.dut = dut
        self.errors = []

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            await Timer(1, units="ps")
            if int(self.dut.command_error_valid_o.value):
                self.errors.append(int(self.dut.command_error_code_o.value))


async def issue(dut, err, cmd, address, byte_count, data_dws=None, keep=0xF):
    """Issue a command; stream payload only if the command was admitted
    (a rejected command never enters REQ_DATA, so an unconditional data
    phase would hang -- same shape as test_tlp_conf_cfgbe)."""
    dut.command_i.value = cmd
    dut.command_address_i.value = address
    dut.command_byte_count_i.value = byte_count
    dut.command_tc_i.value = 0
    dut.command_attr_i.value = 0
    dut.command_context_i.value = 0x55
    dut.command_valid_i.value = 1
    await Timer(1, units="ps")
    while not int(dut.command_ready_o.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.command_valid_i.value = 0
    if data_dws is None:
        return
    n_err = len(err.errors)
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    if len(err.errors) > n_err:
        return
    n = len(data_dws)
    for i, dw in enumerate(data_dws):
        last = (i == n - 1)
        dut.command_data_i.value = dw
        dut.command_keep_i.value = keep if last else 0xF
        dut.command_data_valid_i.value = 1
        dut.command_data_last_i.value = 1 if last else 0
        await Timer(1, units="ps")
        guard = 0
        while not int(dut.command_data_ready_o.value):
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
            guard += 1
            assert guard <= 200, \
                "command_data_ready_o never asserted (no payload phase)"
        await RisingEdge(dut.clk_i)
    dut.command_data_valid_i.value = 0
    dut.command_data_last_i.value = 0


async def settle(dut, n=16):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


def dec_len(dw0):
    """Decode the Length field out of DW0 (tlp_generator.sv, the dw0 assembly)."""
    enc = (((dw0 >> 16) & 0x3) << 8) | ((dw0 >> 24) & 0xFF)
    return 1024 if enc == 0 else enc


def header_fields(packet):
    """(first_be, last_be, length_dw, type5) from DW0/DW1."""
    dw1 = packet[1][0]
    return (dw1 & 0xF, (dw1 >> 4) & 0xF, dec_len(packet[0][0]),
            packet[0][0] & 0x1F)


async def run_case(dut, cmd, address, byte_count, has_data):
    """Reset, issue one command, return (packets, errors)."""
    await init_top(dut)
    cap = TxCapture(dut)
    err = ErrCapture(dut)
    cap.start()
    err.start()
    data = [0xB5A7E9D1] if has_data else None
    await issue(dut, err, cmd, address, byte_count, data,
                keep=((1 << byte_count) - 1) & 0xF)
    await settle(dut)
    return cap.packets, err.errors


# --------------------------------------------------------------------------
# On-wire goldens (F1b.1 / F1b.2)
# --------------------------------------------------------------------------
@cocotb.test()
async def cfg_read1_wire_golden(dut):
    """F1b.1: CfgRd1 on the wire -- whole DW0 (fmt=000, type=00101, len=1),
    DW1, DW2, and the SS2.2.7 class rules (Length=1, Last DW BE=0000)."""
    # Builder self-check: the Type 1 golden differs from the Type 0 golden in
    # exactly dw0 bit 0 (Type[0]) -- Base 2.1 Table 2-3 p.58, prediction P1.1.
    assert golden_cfg_dw0(False, type1=True) ^ golden_cfg_dw0(False, type1=False) == 0x1
    assert golden_cfg_dw0(True, type1=True) ^ golden_cfg_dw0(True, type1=False) == 0x1

    await init_top(dut)
    cap = TxCapture(dut)
    err = ErrCapture(dut)
    cap.start()
    err.start()
    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x3C)
    assert addr == 0x2A8E003C, f"config addr build wrong: {addr:#010x}"
    await issue(dut, err, CMD_CFG_READ1, addr, 4)
    await settle(dut)

    assert err.errors == [], f"legal CfgRd1 rejected: {err.errors}"
    assert len(cap.packets) == 1, f"expected 1 TLP, got {len(cap.packets)}"
    p = cap.packets[0]
    assert len(p) == 3, f"CfgRd1 must be a 3-DW header, got {len(p)} beats: {p}"
    exp_dw0 = golden_cfg_dw0(write=False, type1=True)
    assert p[0][0] == exp_dw0, \
        f"DW0 {p[0][0]:#010x} != {exp_dw0:#010x} (dw0[4:0]={p[0][0] & 0x1F:#07b})"
    assert p[1][0] == golden_dw1(RID, 0, 0xF, 0x0), f"DW1 {p[1][0]:#010x}"
    assert p[2] == (addr, 1), f"DW2 {p[2]}"
    assert int(dut.outstanding_o.value) == 1, "CfgRd1 is non-posted; tag must be held"


@cocotb.test()
async def cfg_write1_wire_golden(dut):
    """F1b.2: CfgWr1 on the wire -- 3DW header + exactly one payload beat,
    whole DW0 (fmt=010, type=00101, len=1), DW1, DW2, payload.

    The beat-count assert comes FIRST: the predicted pre-change failure mode
    is the requester taking the no-data path (command_is_write missing
    CFG_WRITE1) and emitting NO payload beat -- a different defect than
    F1b.1's wrong type, and it must be observed as such."""
    await init_top(dut)
    cap = TxCapture(dut)
    err = ErrCapture(dut)
    cap.start()
    err.start()
    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x48)
    data = 0xA7C3D21E
    await issue(dut, err, CMD_CFG_WRITE1, addr, 4, [data])
    await settle(dut)

    assert err.errors == [], f"legal CfgWr1 rejected: {err.errors}"
    assert len(cap.packets) == 1, f"expected 1 TLP, got {len(cap.packets)}"
    p = cap.packets[0]
    assert len(p) == 4, f"CfgWr1 must be 3-DW header + 1 payload beat, got {len(p)}: {p}"
    exp_dw0 = golden_cfg_dw0(write=True, type1=True)
    assert p[0][0] == exp_dw0, \
        f"DW0 {p[0][0]:#010x} != {exp_dw0:#010x} (dw0[4:0]={p[0][0] & 0x1F:#07b})"
    assert p[1][0] == golden_dw1(RID, 0, 0xF, 0x0), f"DW1 {p[1][0]:#010x}"
    assert p[2][0] == addr, f"DW2 {p[2][0]:#010x}"
    assert p[3] == (data, 1), f"payload {p[3]}"
    assert int(dut.outstanding_o.value) == 1, "CfgWr1 is non-posted; tag must be held"


# --------------------------------------------------------------------------
# Admission matrix (F1b.3) -- re-proven for CFG1, not inherited from CFG0
# --------------------------------------------------------------------------
async def check_admitted(dut, label, cmd, base, has_data, off, bc):
    addr = base + off
    packets, errors = await run_case(dut, cmd, addr, bc, has_data)
    where = f"{label} addr={addr:#010x} off={off} bc={bc}"
    assert errors == [], f"{where}: legal one-DW request rejected, errors={errors}"
    assert len(packets) == 1, f"{where}: expected exactly 1 TLP, got {len(packets)}"
    first_be, last_be, length_dw, type5 = header_fields(packets[0])
    assert type5 == TYPE_CFG1, \
        f"{where}: dw0[4:0] {type5:#07b} != TYPE_CFG1 (Trap A: 00100 here means Type 0)"
    assert length_dw == 1, \
        f"{where}: config must be Length=1 DW (SS2.2.7), got {length_dw}"
    assert first_be == SPEC_FIRST_BE[(off, bc)], \
        f"{where}: first_be {first_be:#06b} != spec {SPEC_FIRST_BE[(off, bc)]:#06b}"
    assert last_be == 0b0000, \
        f"{where}: Last DW BE must be 0000 on a single-DW request, got {last_be:#06b}"


async def check_rejected(dut, label, cmd, base, has_data, off, bc):
    addr = base + off
    packets, errors = await run_case(dut, cmd, addr, bc, has_data)
    where = f"{label} addr={addr:#010x} off={off} bc={bc}"
    assert packets == [], \
        f"{where}: spills past the addressed DW; must emit no TLP, got {len(packets)}"
    assert errors == [TLP_ERR_BAD_LENGTH], \
        f"{where}: expected one TLP_ERR_BAD_LENGTH pulse, got {errors}"


async def sweep(dut, label, cmd, base, has_data):
    for off in OFFSETS:
        for bc in BYTE_COUNTS:
            if (off, bc) in SPEC_FIRST_BE:
                await check_admitted(dut, label, cmd, base, has_data, off, bc)
            else:
                await check_rejected(dut, label, cmd, base, has_data, off, bc)


@cocotb.test()
async def cfg_read1_admission_matrix(dut):
    """F1b.3: CfgRd1 admitted iff bc <= 4-off; every admitted shape one
    1-DW Type 1 TLP, every spilling shape rejected with TLP_ERR_BAD_LENGTH."""
    await sweep(dut, "CfgRd1", CMD_CFG_READ1,
                cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x30), False)


@cocotb.test()
async def cfg_write1_admission_matrix(dut):
    """F1b.3: CfgWr1 -- same admission rule, with the payload phase."""
    await sweep(dut, "CfgWr1", CMD_CFG_WRITE1,
                cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x30), True)


# --------------------------------------------------------------------------
# Anti-segmentation (F1b.5)
# --------------------------------------------------------------------------
@cocotb.test()
async def cfg1_not_segmented_by_mps(dut):
    """F1b.5: an over-length CFG1 request is rejected outright -- its segment
    limit is the config/IO 4-byte rule (command_limit), never
    max_payload/max_read.

    Predicted pre-change failure: command_limit falls through to
    max_payload_bytes_i, so CfgRd1 bc=16 is ADMITTED and goes out as ONE
    multi-DW TLP (len=4) -- fails here by absence of rejection, with the
    single-packet emission as the recorded evidence that the limit in force
    was MPS/MRRS, not 4."""
    # Read, 16 bytes: with max_read=128 a mem-limited path would emit one
    # len=4 TLP; the config rule must instead reject (zero TLPs, BAD_LENGTH).
    addr = cfg_addr(T1_BUS, T1_DEV, T1_FN, 0x50)
    packets, errors = await run_case(dut, CMD_CFG_READ1, addr, 16, False)
    where = f"CfgRd1 addr={addr:#010x} bc=16"
    assert packets == [], \
        f"{where}: over-length CFG1 admitted, emitted {len(packets)} TLP(s) " \
        f"({[header_fields(p) for p in packets]})"
    assert errors == [TLP_ERR_BAD_LENGTH], f"{where}: errors={errors}"

    # Write, 8 bytes: same rule on the data path.
    packets, errors = await run_case(dut, CMD_CFG_WRITE1, addr, 8, True)
    where = f"CfgWr1 addr={addr:#010x} bc=8"
    assert packets == [], \
        f"{where}: over-length CFG1 admitted, emitted {len(packets)} TLP(s)"
    assert errors == [TLP_ERR_BAD_LENGTH], f"{where}: errors={errors}"
