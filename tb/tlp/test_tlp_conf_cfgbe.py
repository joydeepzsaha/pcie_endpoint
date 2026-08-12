"""Config/IO byte-enable admission matrix -- one DW, any byte enables.

PCIe Base 2.1 SS2.2.7 requires every Configuration and IO Request to carry
Length = 1 DW.  It constrains the *Length field*; it does not require all four
byte enables to be set.  A single-byte config write (First DW BE = 0010, Last
DW BE = 0000) is a legal one-DW request.

So the requester's admission rule must be "the request fits inside the
addressed DW", i.e.

    admit  iff  1 <= byte_count <= 4 - address[1:0]

and every admitted shape must produce exactly one TLP with length_dw == 1 and
last_be == 0000.  Two distinct defects live on either side of that line, and
this bench pins both:

  * TOO STRICT.  The guard used to demand byte_count == 4 exactly, so legal
    byte-granular config access (CFG_WRITE0 @0x19 bc=1) was rejected with
    TLP_ERR_BAD_LENGTH.

  * TOO PERMISSIVE, and spec-illegal.  byte_count == 4 at a *nonzero* offset
    was admitted, but calculate_segment (src/tlp/tlp_requester.sv:93-94) clamps
    a segment to limit - address[1:0], so CFG_READ0 @0x19 bc=4 emitted TWO
    config TLPs (first_be=1110 @0x19 then first_be=0001 @0x1c).  See
    cfg_io_unaligned_full_dw_must_not_split -- that is the anti-split
    regression test, and it is the reason the rejected half of this matrix is
    asserted as hard as the admitted half.

SPEC-GOLDEN DISCIPLINE: SPEC_FIRST_BE below is a hand-written table of the
PCIe First-DW-BE rule, enumerated from the spec, not read back from the DUT
and not computed with the DUT's tlp_pkg helpers.

RTL cited (read, not assumed):
  admission guard ............. src/tlp/tlp_requester.sv:183-199
  calculate_segment clamp ..... src/tlp/tlp_requester.sv:84-101
  length_dw / first_be /
    last_be build ............. src/tlp/tlp_requester.sv:125-129
  command_limit (CFG/IO = 4B) . src/tlp/tlp_requester.sv:75-82
  generator DW0/DW1/DW2 ....... src/tlp/tlp_generator.sv:49-72,81-85
  tlp_error_e ................. src/tlp/tlp_pkg.sv:58-74
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# tlp_cmd_e (src/tlp/tlp_pkg.sv:43-50)
CMD_MEM_WRITE = 1
CMD_CFG_READ0 = 2
CMD_CFG_WRITE0 = 3
CMD_IO_READ = 4
CMD_IO_WRITE = 5

# tlp_error_e (src/tlp/tlp_pkg.sv:58-74): 7th member, zero-based ordinal 6.
TLP_ERR_BAD_LENGTH = 6

RID = 0x1234

# A config register DW (0x18 = Primary/Secondary/Subordinate bus numbers) and
# an IO base, both DW-aligned so that +off lands anywhere inside one DW.
CFG_BASE = 0x18
IO_BASE = 0x1000

# ---------------------------------------------------------------------------
# Spec golden: PCIe First DW BE for a transfer of `bc` bytes starting at byte
# `off` of the addressed DW.  Enumerated by hand from the byte-enable rule --
# bit i set means byte i of the DW participates -- for exactly the shapes that
# fit in one DW.  Every (off, bc) NOT in this table spills past the DW and must
# be rejected.
# ---------------------------------------------------------------------------
SPEC_FIRST_BE = {
    (0, 1): 0b0001, (0, 2): 0b0011, (0, 3): 0b0111, (0, 4): 0b1111,
    (1, 1): 0b0010, (1, 2): 0b0110, (1, 3): 0b1110,
    (2, 1): 0b0100, (2, 2): 0b1100,
    (3, 1): 0b1000,
}

OFFSETS = (0, 1, 2, 3)
BYTE_COUNTS = (1, 2, 3, 4)

CONFIG_IO_COMMANDS = (
    ("CfgWr0", CMD_CFG_WRITE0, CFG_BASE, True),
    ("CfgRd0", CMD_CFG_READ0, CFG_BASE, False),
    ("IOWr", CMD_IO_WRITE, IO_BASE, True),
    ("IORd", CMD_IO_READ, IO_BASE, False),
)


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
def init_flow_control(dut):
    """Saturate VC0 credits.

    The merged tlp_layer gates every TX packet on the credit manager
    (tlp_layer.sv:249, tlp_credit_manager.sv:53); the credit registers reset to
    zero and only load on fc_update_valid_i, so a harness that leaves these at
    0 never transmits a packet.  This bench exercises command admission, not
    flow control, so the pool is held saturated and must never be the limiter.
    """
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
    """Issue a command; stream payload only if the command was admitted.

    A rejected command never enters REQ_DATA, so command_data_ready_o never
    asserts and an unconditional data phase would hang.  Waiting out the
    admission pulse first keeps one helper usable for both halves of the
    matrix.
    """
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
            assert guard <= 200, "command_data_ready_o never asserted"
        await RisingEdge(dut.clk_i)
    dut.command_data_valid_i.value = 0
    dut.command_data_last_i.value = 0


async def settle(dut, n=16):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


def dec_len(dw0):
    """Decode the Length field out of DW0 (tlp_generator.sv:49-62)."""
    enc = (((dw0 >> 16) & 0x3) << 8) | ((dw0 >> 24) & 0xFF)
    return 1024 if enc == 0 else enc


def header_fields(packet):
    """(first_be, last_be, length_dw) from a captured packet's DW0/DW1."""
    dw1 = packet[1][0]
    return (dw1 & 0xF, (dw1 >> 4) & 0xF, dec_len(packet[0][0]))


async def run_case(dut, cmd, address, byte_count, has_data):
    """Reset, issue one command, return (packets, errors)."""
    await init_top(dut)
    cap = TxCapture(dut)
    err = ErrCapture(dut)
    cap.start()
    err.start()
    data = [0xDEADBEEF] if has_data else None
    await issue(dut, err, cmd, address, byte_count, data,
                keep=((1 << byte_count) - 1) & 0xF)
    await settle(dut)
    return cap.packets, err.errors


# --------------------------------------------------------------------------
# The admitted half
# --------------------------------------------------------------------------
async def check_admitted(dut, label, cmd, base, has_data, off, bc):
    addr = base + off
    packets, errors = await run_case(dut, cmd, addr, bc, has_data)
    where = f"{label} addr={addr:#06x} off={off} bc={bc}"
    assert errors == [], f"{where}: legal one-DW request rejected, errors={errors}"
    assert len(packets) == 1, \
        f"{where}: expected exactly 1 TLP, got {len(packets)}"
    first_be, last_be, length_dw = header_fields(packets[0])
    assert length_dw == 1, \
        f"{where}: config/IO must be Length=1 DW (SS2.2.7), got {length_dw}"
    assert first_be == SPEC_FIRST_BE[(off, bc)], \
        f"{where}: first_be {first_be:#06b} != spec {SPEC_FIRST_BE[(off, bc)]:#06b}"
    assert last_be == 0b0000, \
        f"{where}: Last DW BE must be 0000 on a single-DW request, got {last_be:#06b}"


async def check_rejected(dut, label, cmd, base, has_data, off, bc):
    addr = base + off
    packets, errors = await run_case(dut, cmd, addr, bc, has_data)
    where = f"{label} addr={addr:#06x} off={off} bc={bc}"
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
async def cfg_write0_byte_enable_matrix(dut):
    """CfgWr0: admitted iff bc <= 4-off, each admitted shape one 1-DW TLP."""
    await sweep(dut, "CfgWr0", CMD_CFG_WRITE0, CFG_BASE, True)


@cocotb.test()
async def cfg_read0_byte_enable_matrix(dut):
    """CfgRd0: same admission rule, no payload phase."""
    await sweep(dut, "CfgRd0", CMD_CFG_READ0, CFG_BASE, False)


@cocotb.test()
async def io_write_byte_enable_matrix(dut):
    """IOWr: IO shares the config one-DW limit (command_limit, :75-82)."""
    await sweep(dut, "IOWr", CMD_IO_WRITE, IO_BASE, True)


@cocotb.test()
async def io_read_byte_enable_matrix(dut):
    """IORd: IO shares the config one-DW limit (command_limit, :75-82)."""
    await sweep(dut, "IORd", CMD_IO_READ, IO_BASE, False)


# --------------------------------------------------------------------------
# The anti-split regression test
# --------------------------------------------------------------------------
@cocotb.test()
async def cfg_io_unaligned_full_dw_must_not_split(dut):
    """A 4-byte config/IO request at a nonzero offset must be REJECTED.

    PCIe Base 2.1 SS2.2.7: a Configuration or IO Request carries Length = 1 DW.
    Four bytes starting at byte 1 of a DW straddle a DW boundary, so it cannot
    be expressed as one such request.  The requester must refuse it outright.

    It must specifically NOT be segmented: calculate_segment clamps to
    limit - address[1:0] (src/tlp/tlp_requester.sv:93-94), which once turned
    CFG_READ0 @0x19 bc=4 into two config TLPs on the wire (first_be=1110 @0x19
    then first_be=0001 @0x1c).  Two config TLPs for one request violates
    SS2.2.7 and, for a write, tears a register update in half.  Assert zero
    TLPs, not merely "not two".
    """
    for label, cmd, base, has_data in CONFIG_IO_COMMANDS:
        for off in (1, 2, 3):
            addr = base + off
            packets, errors = await run_case(dut, cmd, addr, 4, has_data)
            where = f"{label} addr={addr:#06x} bc=4"
            assert len(packets) == 0, (
                f"{where}: emitted {len(packets)} TLP(s) "
                f"({[header_fields(p) for p in packets]}); a 4-byte config/IO "
                f"request at offset {off} must be rejected, never split")
            assert errors == [TLP_ERR_BAD_LENGTH], \
                f"{where}: expected TLP_ERR_BAD_LENGTH, got {errors}"


# --------------------------------------------------------------------------
# Regressions: the guard must not reach anything else
# --------------------------------------------------------------------------
@cocotb.test()
async def memory_path_byte_enables_unchanged(dut):
    """Memory writes keep byte granularity -- the guard is config/IO only.

    command_limit gives memory MPS/MRRS, not 4 bytes (:75-82), so these are
    ordinary sub-DW memory writes and must be unaffected by the config rule.
    """
    for addr, bc, expect_first_be in (
        (0x1019, 1, 0b0010),
        (0x101A, 2, 0b1100),
        (0x1018, 4, 0b1111),
        (0x101B, 1, 0b1000),
    ):
        packets, errors = await run_case(dut, CMD_MEM_WRITE, addr, bc, True)
        where = f"MemWr addr={addr:#06x} bc={bc}"
        assert errors == [], f"{where}: unexpected error {errors}"
        assert len(packets) == 1, f"{where}: expected 1 TLP, got {len(packets)}"
        first_be, last_be, length_dw = header_fields(packets[0])
        assert (first_be, last_be, length_dw) == (expect_first_be, 0b0000, 1), \
            (f"{where}: got first_be={first_be:#06b} last_be={last_be:#06b} "
             f"len={length_dw}, want first_be={expect_first_be:#06b} "
             f"last_be=0b0000 len=1")


@cocotb.test()
async def rejection_does_not_wedge_the_requester(dut):
    """A rejected command must leave the FSM able to accept the next one.

    The guard rejects without latching, staying in REQ_IDLE
    (src/tlp/tlp_requester.sv:182-189), so an illegal config request must cost
    nothing but its error pulse.
    """
    await init_top(dut)
    cap = TxCapture(dut)
    err = ErrCapture(dut)
    cap.start()
    err.start()

    # Illegal: 4 bytes at offset 3 spills three bytes past the DW.
    await issue(dut, err, CMD_CFG_WRITE0, CFG_BASE + 3, 4, [0xDEADBEEF], keep=0xF)
    await settle(dut)
    assert cap.packets == [], "illegal request emitted a TLP"
    assert err.errors == [TLP_ERR_BAD_LENGTH], f"errors={err.errors}"

    # Legal follow-up on the same offset: one byte fits.
    await issue(dut, err, CMD_CFG_WRITE0, CFG_BASE + 3, 1, [0xDEADBEEF], keep=0x1)
    await settle(dut)
    assert len(cap.packets) == 1, \
        f"requester wedged: legal follow-up emitted {len(cap.packets)} TLPs"
    assert err.errors == [TLP_ERR_BAD_LENGTH], \
        f"legal follow-up raised an extra error: {err.errors}"
    first_be, last_be, length_dw = header_fields(cap.packets[0])
    assert (first_be, last_be, length_dw) == (0b1000, 0b0000, 1), \
        f"follow-up first_be={first_be:#06b} last_be={last_be:#06b} len={length_dw}"
