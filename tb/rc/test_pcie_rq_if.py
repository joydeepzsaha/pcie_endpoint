"""Commit 2a-i -- standalone unit tests for pcie_rq_if (T1..T11).

No Transaction Layer in the loop: this bench plays tlp_requester's command port
itself, so no FC-credit initialisation is required here.  The wire-level TLP
goldens and the FC sequence live in test_pcie_rq_if_tlp.py (T12..T15).

SPEC-GOLDEN DISCIPLINE.  Every expected value below is derived here from the
PG213 descriptor tables and the PCIe byte-enable rules, never read back from the
DUT.  spec_first_be/spec_last_be are a from-scratch reimplementation of the
PCIe rules, independent of tlp_pkg's tlp_first_be/tlp_last_be, so agreement
actually validates something.

RTL cited (read, not assumed):
  descriptor decode / legality ..... src/rc/pcie_rq_if.sv
  byte-count arithmetic ............ src/rc/pcie_rq_rc_pkg.sv rq_byte_count
  TL admission guard mirrored ...... src/tlp/tlp_requester.sv:183-199 (d5a4253)
  TL byte-enable re-derivation ..... src/tlp/tlp_requester.sv:129-130
  TL BE helpers .................... src/tlp/tlp_pkg.sv:165-193
  early-last contract .............. src/tlp/tlp_requester.sv:153-158, 225-236
  payload gearbox .................. src/rc/pcie_axis_dw_downsize.sv
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_NS = 4

# pcie_rq_rc_pkg::rq_req_type_e (PG213 v1.3 Table 57)
RQ_MEM_READ = 0b0000
RQ_MEM_WRITE = 0b0001
RQ_IO_READ = 0b0010
RQ_IO_WRITE = 0b0011
RQ_MEM_FETCH_ADD = 0b0100
RQ_MEM_SWAP = 0b0101
RQ_MEM_CAS = 0b0110
RQ_MEM_RD_LOCKED = 0b0111
RQ_CFG_READ0 = 0b1000
RQ_CFG_READ1 = 0b1001
RQ_CFG_WRITE0 = 0b1010
RQ_CFG_WRITE1 = 0b1011
RQ_MSG_ATS = 0b1111

# The eight encodings with NO command mapping after Stage D-2.  Everything the
# reject matrix (D2-S3) claims about "the rest" is defined by this list, so it
# is written out rather than computed.
RQ_NEVER_MAPPED = (0b0100, 0b0101, 0b0110, 0b0111,
                   0b1100, 0b1101, 0b1110, 0b1111)

# tlp_pkg::tlp_cmd_e (tlp_pkg.sv, typedef tlp_cmd_e)
CMD_MEM_READ = 0
CMD_MEM_WRITE = 1
CMD_CFG_READ0 = 2
CMD_CFG_WRITE0 = 3
CMD_IO_READ = 4
CMD_IO_WRITE = 5
CMD_CFG_READ1 = 6
CMD_CFG_WRITE1 = 7

# pcie_rq_rc_pkg::rq_error_e
ERR_NONE = 0
ERR_REQ_TYPE = 1
ERR_DWORD_COUNT = 2
ERR_CFG_DWORD_COUNT = 3
ERR_CFG_IO_FIT = 4
ERR_4KB = 5
ERR_ADDRESS_TYPE = 6
ERR_POISON_CFG_WR = 7
ERR_BYTE_COUNT_FIT = 8
ERR_BE_MISMATCH = 9
ERR_ZERO_LENGTH = 10
ERR_EARLY_LAST = 11
ERR_MISSING_LAST = 12


# --------------------------------------------------------------------------
# Spec goldens (hand-derived; deliberately not the DUT's functions)
# --------------------------------------------------------------------------
def popcount(v):
    return bin(v & 0xF).count("1")


def be_offset(first_be):
    """Position of the least-significant set bit; 0 for an empty nibble."""
    for i in range(4):
        if (first_be >> i) & 1:
            return i
    return 0


def golden_byte_count(n, first_be, last_be):
    """Bytes transferred.  Piecewise -- the general formula underflows at n==1."""
    if n <= 1:
        return popcount(first_be)
    if n == 2:
        return popcount(first_be) + popcount(last_be)
    return popcount(first_be) + (n - 2) * 4 + popcount(last_be)


def spec_first_be(off, nbytes):
    """PCIe First-BE: bytes [off, off+n) inside the first Dword, capped at 4."""
    if off + nbytes <= 4:
        return (((1 << nbytes) - 1) << off) & 0xF
    return (0xF << off) & 0xF


def spec_last_be(off, nbytes):
    """PCIe Last-BE: zero for a single-Dword transfer, else the tail mask."""
    if off + nbytes <= 4:
        return 0x0
    end = (off + nbytes) & 0x3
    return 0xF if end == 0 else ((1 << end) - 1)


def be_reproducible(first_be, last_be):
    """Can the TL rebuild these byte enables from (offset, byte_count)?"""
    off = be_offset(first_be)
    bc = golden_byte_count(2 if last_be else 1, first_be, last_be)
    return spec_first_be(off, bc) == first_be and spec_last_be(off, bc) == last_be


def cfg_address(completer_id, ext_reg, reg_num, off):
    """Expected command_address for a Configuration request (brief SS4.3 / A.3)."""
    return ((completer_id & 0xFFFF) << 16) | ((ext_reg & 0xF) << 8) | \
           ((reg_num & 0x3F) << 2) | (off & 0x3)


# --------------------------------------------------------------------------
# Descriptor builder -- PG213 v1.3 Table 60/61, bit-for-bit
# --------------------------------------------------------------------------
def rq_desc(req_type, dword_count, address=0, completer_id=0, tag=0,
            requester_id=0, poisoned=0, tc=0, attr=0, rid_en=0, force_ecrc=0):
    v = address & ((1 << 64) - 1)
    v |= (dword_count & 0x7FF) << 64
    v |= (req_type & 0xF) << 75
    v |= (poisoned & 1) << 79
    v |= (requester_id & 0xFFFF) << 80
    v |= (tag & 0xFF) << 96
    v |= (completer_id & 0xFFFF) << 104
    v |= (rid_en & 1) << 120
    v |= (tc & 0x7) << 121
    v |= (attr & 0x7) << 124
    v |= (force_ecrc & 1) << 127
    return v


def cfg_desc_address(reg_num, ext_reg=0):
    """Configuration descriptor's [63:0]: Reg Number [7:2], Ext Reg [11:8]."""
    return ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2)


def tuser(first_be, last_be):
    return ((last_be & 0xF) << 4) | (first_be & 0xF)


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
class Rq:
    """Drives the RQ AXIS slave and records everything the DUT emits."""

    def __init__(self, dut):
        self.dut = dut
        self.commands = []      # (cmd, address, byte_count, tc, attr, context)
        self.payload = []       # (data, keep, last)
        self.errors = []        # rq_error_code_o at each rq_protocol_error_o
        self.tags = []          # pcie_rq_tag_o at each pcie_rq_tag_vld_o
        self.last_early = []    # payload index of every command_data_last_o
        self._tasks = []

    def start(self):
        self._tasks = [cocotb.start_soon(self._monitor())]

    async def _monitor(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if int(d.rst_i.value):
                continue
            if int(d.command_valid_o.value) and int(d.command_ready_i.value):
                self.commands.append((
                    int(d.command_o.value),
                    int(d.command_address_o.value),
                    int(d.command_byte_count_o.value),
                    int(d.command_tc_o.value),
                    int(d.command_attr_o.value),
                    int(d.command_context_o.value),
                ))
            if int(d.command_data_valid_o.value) and int(d.command_data_ready_i.value):
                self.payload.append((
                    int(d.command_data_o.value),
                    int(d.command_keep_o.value),
                    int(d.command_data_last_o.value),
                ))
            if int(d.rq_protocol_error_o.value):
                self.errors.append(int(d.rq_error_code_o.value))
            if int(d.pcie_rq_tag_vld_o.value):
                self.tags.append(int(d.pcie_rq_tag_o.value))

    def clear(self):
        self.commands.clear()
        self.payload.clear()
        self.errors.clear()
        self.tags.clear()

    async def send(self, beats, rng=None, stall_prob=0.0):
        """beats: list of (tdata, tkeep, tlast, tuser)."""
        d = self.dut
        for data, keep, last, user in beats:
            if rng is not None:
                while rng.random() < stall_prob:
                    d.s_axis_rq_tvalid.value = 0
                    await RisingEdge(d.clk_i)
            d.s_axis_rq_tdata.value = data
            d.s_axis_rq_tkeep.value = keep
            d.s_axis_rq_tlast.value = 1 if last else 0
            d.s_axis_rq_tuser.value = user
            d.s_axis_rq_tvalid.value = 1
            # Bounded: a DUT that stops asserting tready is a failure, not a
            # reason to hang the whole regression.
            for _ in range(4000):
                await ReadOnly()
                fired = int(d.s_axis_rq_tready.value) == 1
                await RisingEdge(d.clk_i)
                if fired:
                    break
            else:
                raise AssertionError("s_axis_rq_tready never asserted -- DUT stalled")
        d.s_axis_rq_tvalid.value = 0
        d.s_axis_rq_tlast.value = 0

    async def settle(self, cycles=24):
        self.dut.s_axis_rq_tvalid.value = 0
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)


def payload_beats(dwords, first_be, last_be):
    """Pack Dwords into 128-bit beats with PG213 DW-granular tkeep."""
    beats = []
    for base in range(0, len(dwords), 4):
        chunk = dwords[base:base + 4]
        data = 0
        for i, dw in enumerate(chunk):
            data |= (dw & 0xFFFFFFFF) << (32 * i)
        keep = (1 << len(chunk)) - 1
        beats.append((data, keep, base + 4 >= len(dwords), tuser(first_be, last_be)))
    return beats


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    dut.s_axis_rq_tdata.value = 0
    dut.s_axis_rq_tkeep.value = 0
    dut.s_axis_rq_tvalid.value = 0
    dut.s_axis_rq_tlast.value = 0
    dut.s_axis_rq_tuser.value = 0
    dut.allocated_tag_i.value = 0
    dut.allocated_tag_valid_i.value = 0
    dut.command_ready_i.value = 1
    dut.command_data_ready_i.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk_i)
    rq = Rq(dut)
    rq.start()
    await RisingEdge(dut.clk_i)
    return rq


async def one_shot(rq, desc, first_be=0xF, last_be=0x0, payload=None, last=True):
    """Send one descriptor (+ optional payload) and let it settle."""
    rq.clear()
    beats = [(desc, 0xF, last and payload is None, tuser(first_be, last_be))]
    if payload:
        beats.extend(payload_beats(payload, first_be, last_be))
    await rq.send(beats)
    await rq.settle()


# ==========================================================================
# T1 -- elaboration and reset behaviour
# ==========================================================================
@cocotb.test()
async def test_t1_reset(dut):
    """T1: the DUT elaborates, comes out of reset idle and accepting."""
    rq = await init(dut)
    await ReadOnly()
    assert int(dut.command_valid_o.value) == 0
    assert int(dut.command_data_valid_o.value) == 0
    assert int(dut.rq_protocol_error_o.value) == 0
    assert int(dut.s_axis_rq_tready.value) == 1, "must accept a descriptor after reset"
    assert int(dut.command_ecrc_enable_o.value) == 0, "ECRC is TL-generated; tie 0"
    assert int(dut.command_prefix_valid_o.value) == 0
    assert len(rq.errors) == 0


# ==========================================================================
# T2 -- CfgRd0 descriptor -> command_*, randomized BDF/register corners
# ==========================================================================
@cocotb.test()
async def test_t2_cfgrd_address_map(dut):
    """T2: command_address is bit-exact per the config mapping, incl. corners."""
    rq = await init(dut)
    rng = random.Random(0x2222)

    cases = [
        (0xFF, 31, 7, 0x3F, 0xF),          # every field saturated
        (0x00, 0, 0, 0x00, 0x0),           # every field zero
        (0x01, 0, 0, 0x06, 0x0),           # bus 1, register 0x18 (2b's target)
    ]
    for _ in range(6):
        cases.append((rng.randrange(256), rng.randrange(32), rng.randrange(8),
                      rng.randrange(64), rng.randrange(16)))

    for bus, dev, fn, reg, ext in cases:
        bdf = (bus << 8) | (dev << 3) | fn
        desc = rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(reg, ext),
                       completer_id=bdf, tag=0xA5, tc=3, attr=5)
        await one_shot(rq, desc, first_be=0xF, last_be=0x0)

        assert len(rq.errors) == 0, f"unexpected reject {rq.errors} for bdf={bdf:04x}"
        assert len(rq.commands) == 1, f"expected 1 command, got {len(rq.commands)}"
        cmd, addr, bc, tc, attr, _ctx = rq.commands[0]
        assert cmd == CMD_CFG_READ0
        want = cfg_address(bdf, ext, reg, 0)
        assert addr == want, \
            f"bdf={bdf:04x} reg={reg:02x} ext={ext:x}: address {addr:#x} != {want:#x}"
        assert bc == 4, f"whole-DW config must be byte_count 4, got {bc}"
        assert tc == 3 and attr == 5, "TC/Attr must pass through"
        assert len(rq.payload) == 0, "a read must not drive payload"


# ==========================================================================
# T3 -- byte-granular config sweep (the d5a4253 gate)
# ==========================================================================
@cocotb.test()
async def test_t3_byte_granular_config(dut):
    """T3: every contiguous first_be at N=1 is ADMITTED, with the right offset.

    This is the test the pre-d5a4253 documents said could not pass.  The TL
    admits any config request with byte_count <= 4 - address[1:0]
    (tlp_requester.sv:183-199), so all seven patterns below are legal.
    """
    rq = await init(dut)
    bdf = 0x0100
    for first_be in (0x1, 0x2, 0x4, 0x8, 0x3, 0xC, 0xF):
        off = be_offset(first_be)
        bc = popcount(first_be)
        desc = rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(0x06),
                       completer_id=bdf)
        await one_shot(rq, desc, first_be=first_be, last_be=0x0, payload=[0xDEADBEEF])

        assert len(rq.errors) == 0, \
            f"first_be={first_be:#x} rejected with {rq.errors} -- d5a4253 admits it"
        assert len(rq.commands) == 1
        _cmd, addr, got_bc, _tc, _attr, _ctx = rq.commands[0]
        assert addr & 0x3 == off, f"first_be={first_be:#x}: offset {addr & 3} != {off}"
        assert got_bc == bc, f"first_be={first_be:#x}: byte_count {got_bc} != {bc}"
        assert addr == cfg_address(bdf, 0, 0x06, off)
        # The TL will rebuild these; they must match what the host asked for.
        assert spec_first_be(off, bc) == first_be
        assert spec_last_be(off, bc) == 0x0
        # Sum of keep popcounts must equal the byte count (the T9 invariant).
        total = sum(popcount(k) for _d, k, _l in rq.payload)
        assert total == bc, f"first_be={first_be:#x}: kept {total} bytes, want {bc}"


# ==========================================================================
# T4 -- config/IO one-Dword fit rejects
# ==========================================================================
@cocotb.test()
async def test_t4_cfg_io_fit_reject(dut):
    """T4: byte_count > 4 - off on an IO request is refused, no command.

    The cells are IO, not config: a config request with Dword Count != 1 is
    already refused by RQ_ERR_CFG_DWORD_COUNT, which has higher priority, so
    the fit check is only reachable through IO (recorded in the report).
    """
    rq = await init(dut)
    # (first_be, last_be) -> off, byte_count over two Dwords
    cells = [(0xE, 0x1), (0xC, 0x1), (0x8, 0x1)]
    for first_be, last_be in cells:
        off = be_offset(first_be)
        bc = golden_byte_count(2, first_be, last_be)
        assert bc > 4 - off, "test cell must actually be a misfit"
        desc = rq_desc(RQ_IO_WRITE, 2, address=0x1000)
        await one_shot(rq, desc, first_be=first_be, last_be=last_be,
                       payload=[0x11111111, 0x22222222])
        assert rq.errors == [ERR_CFG_IO_FIT], \
            f"first_be={first_be:#x} last_be={last_be:#x}: errors {rq.errors}"
        assert len(rq.commands) == 0, "a rejected request must launch no command"
        assert len(rq.payload) == 0, "a rejected request must forward no payload"

    # And the mirror: a config request that DOES fit is admitted.
    desc = rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(0x06), completer_id=0x100)
    await one_shot(rq, desc, first_be=0x2, last_be=0x0, payload=[0x000000AB])
    assert rq.errors == [] and len(rq.commands) == 1


# ==========================================================================
# T5 -- Request Type rejects
# ==========================================================================
@cocotb.test()
async def test_t5_request_type_reject(dut):
    """T5: unmapped Request Types are refused, no command, back to idle.

    Stage D-2 moved RQ_CFG_READ1/RQ_CFG_WRITE1 out of this list and into the
    mapped set (D2-S1); two never-mapped atomics keep the sample at five.
    The full 16-encoding matrix is D2-S3.
    """
    rq = await init(dut)
    for req_type in (RQ_MEM_FETCH_ADD, RQ_MEM_CAS, RQ_MEM_SWAP, RQ_MSG_ATS,
                     RQ_MEM_RD_LOCKED):
        desc = rq_desc(req_type, 1, address=0x2000)
        await one_shot(rq, desc, first_be=0xF, last_be=0x0)
        assert rq.errors == [ERR_REQ_TYPE], \
            f"req_type={req_type:#06b}: errors {rq.errors}"
        assert len(rq.commands) == 0
        assert len(rq.payload) == 0

    # Idle and usable straight afterwards.
    desc = rq_desc(RQ_MEM_READ, 1, address=0x3000)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    assert rq.errors == [] and len(rq.commands) == 1


# ==========================================================================
# T6 -- range and boundary checks
# ==========================================================================
@cocotb.test()
async def test_t6_range_checks(dut):
    """T6: N=0, N>1024, config N=2, a 4KB-crossing MemWr and AT!=00."""
    rq = await init(dut)

    # N == 0
    await one_shot(rq, rq_desc(RQ_MEM_READ, 0, address=0x1000))
    assert rq.errors == [ERR_DWORD_COUNT] and not rq.commands

    # N == 1025
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1025, address=0x1000))
    assert rq.errors == [ERR_DWORD_COUNT] and not rq.commands

    # N == 1024 is the largest legal one.  last_be must be non-zero for N > 1
    # (PCIe Base 2.1 SS2.2.7); with last_be = 0 the byte-enable round trip
    # correctly refuses it, which the second half of this case checks.
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1024, address=0x0),
                   first_be=0xF, last_be=0xF)
    assert rq.errors == [] and len(rq.commands) == 1
    assert rq.commands[0][2] == 4096
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1024, address=0x0),
                   first_be=0xF, last_be=0x0)
    assert rq.errors == [ERR_BE_MISMATCH] and not rq.commands

    # Configuration with Dword Count 2.
    await one_shot(rq, rq_desc(RQ_CFG_READ0, 2, address=cfg_desc_address(0x06),
                               completer_id=0x100), first_be=0xF, last_be=0xF)
    assert rq.errors == [ERR_CFG_DWORD_COUNT] and not rq.commands

    # MemWr crossing a 4KB boundary: 2 Dwords starting at 0xFFC.
    await one_shot(rq, rq_desc(RQ_MEM_WRITE, 2, address=0xFFC),
                   first_be=0xF, last_be=0xF, payload=[1, 2])
    assert rq.errors == [ERR_4KB], f"errors {rq.errors}"
    assert not rq.commands

    # The same request one Dword earlier is legal.
    await one_shot(rq, rq_desc(RQ_MEM_WRITE, 2, address=0xFF8),
                   first_be=0xF, last_be=0xF, payload=[1, 2])
    assert rq.errors == [] and len(rq.commands) == 1

    # Address Type != 00 on a memory request.
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1, address=0x1001))
    assert rq.errors == [ERR_ADDRESS_TYPE] and not rq.commands

    # Poisoned configuration write.
    await one_shot(rq, rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(0x06),
                               completer_id=0x100, poisoned=1),
                   first_be=0xF, last_be=0x0, payload=[0])
    assert rq.errors == [ERR_POISON_CFG_WR] and not rq.commands


# ==========================================================================
# T7 -- the by-construction early-last property
# ==========================================================================
@cocotb.test()
async def test_t7_early_last(dut):
    """T7: an early s_axis_rq_tlast never becomes an early command_data_last_o.

    Two sub-cases, treated differently on purpose (pcie_rq_if.sv header):
      (a) tlast on the descriptor beat of a write -- nothing has been launched,
          so the request is refused outright and NO command appears.
      (b) tlast mid-payload -- the command is already out and cannot be
          un-launched; the wrapper flushes and emits one terminating zero-keep
          beat, which is tlp_requester's own documented recovery (:232-236).
    In neither case does command_data_last_o appear on a beat carrying payload
    bytes before the Dword Count is met.
    """
    rq = await init(dut)

    # ---- (a) tlast on the descriptor beat of a 4-Dword write ----
    rq.clear()
    desc = rq_desc(RQ_MEM_WRITE, 4, address=0x2000)
    await rq.send([(desc, 0xF, True, tuser(0xF, 0xF))])
    await rq.settle()
    assert rq.errors == [ERR_EARLY_LAST], f"errors {rq.errors}"
    assert len(rq.commands) == 0, "no command may be launched (case a)"
    assert len(rq.payload) == 0, "no payload beat may reach the TL (case a)"

    # ---- (b) tlast after 4 of 8 payload Dwords ----
    rq.clear()
    desc = rq_desc(RQ_MEM_WRITE, 8, address=0x2000)
    beats = [(desc, 0xF, False, tuser(0xF, 0xF)),
             (0x4444333322221111, 0xF, True, tuser(0xF, 0xF))]
    await rq.send(beats)
    await rq.settle(40)
    assert ERR_EARLY_LAST in rq.errors, f"errors {rq.errors}"
    # Every beat carrying bytes must be non-last: last only ever rides the
    # deliberate terminating beat, which carries keep == 0.
    for idx, (_data, keep, last) in enumerate(rq.payload):
        if last:
            assert keep == 0, \
                f"beat {idx}: command_data_last_o on a beat with keep={keep:#x} " \
                "-- an early last was passed to the TL"
    assert rq.payload and rq.payload[-1][2] == 1, "must terminate the TL cleanly"

    # ---- and the wrapper is immediately reusable ----
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1, address=0x5000))
    assert rq.errors == [] and len(rq.commands) == 1


# ==========================================================================
# T8 -- non-contiguous byte enables and the zero-length read
# ==========================================================================
@cocotb.test()
async def test_t8_be_consistency(dut):
    """T8: byte enables the TL cannot rebuild are refused (KNOWN_GAPS)."""
    rq = await init(dut)

    # Non-contiguous first_be.  tlp_first_be builds contiguous masks only.
    for first_be in (0x9, 0x5, 0xA, 0xB):
        assert not be_reproducible(first_be, 0x0), "cell must be irreproducible"
        await one_shot(rq, rq_desc(RQ_MEM_WRITE, 1, address=0x2000),
                       first_be=first_be, last_be=0x0, payload=[0])
        assert rq.errors == [ERR_BE_MISMATCH], \
            f"first_be={first_be:#x}: errors {rq.errors}"
        assert not rq.commands

    # Non-contiguous across two Dwords: last_be must be contiguous from bit 0.
    await one_shot(rq, rq_desc(RQ_MEM_WRITE, 2, address=0x2000),
                   first_be=0xF, last_be=0x2, payload=[0, 0])
    assert rq.errors == [ERR_BE_MISMATCH] and not rq.commands

    # Zero-length read: N=1, first_be=0.  NOT caught by the BE round trip --
    # tlp_first_be(0, 0) is also 0 -- so it has its own check.
    await one_shot(rq, rq_desc(RQ_MEM_READ, 1, address=0x2000), first_be=0x0)
    assert rq.errors == [ERR_ZERO_LENGTH], f"errors {rq.errors}"
    assert not rq.commands


# ==========================================================================
# T9 -- tkeep translation and the sum-of-popcounts invariant
# ==========================================================================
@cocotb.test()
async def test_t9_keep_translation(dut):
    """T9: sum(popcount(command_keep_o)) == command_byte_count_o, every N.

    This is the invariant tlp_requester's accepted_bytes accounting closes on
    (tlp_requester.sv:107-109, 214-231): if it does not hold, the requester
    flags command_error_valid_o.  Exactly one command_data_last_o per request.
    """
    rq = await init(dut)
    rng = random.Random(0x9999)

    for n in (1, 2, 4, 17, 64):
        for first_be, last_be in ((0xF, 0xF if n > 1 else 0x0),
                                  (0xE, 0x3 if n > 1 else 0x0),
                                  (0x8, 0x1 if n > 1 else 0x0)):
            if n == 1 and first_be == 0xE:
                first_be = 0x6      # keep it contiguous and reproducible
            off = be_offset(first_be)
            bc = golden_byte_count(n, first_be, last_be)
            if spec_first_be(off, bc) != first_be or spec_last_be(off, bc) != last_be:
                continue            # not expressible; covered by T8
            if off + bc > 4096:
                continue
            dwords = [rng.randrange(1 << 32) for _ in range(n)]
            await one_shot(rq, rq_desc(RQ_MEM_WRITE, n, address=0x10000),
                           first_be=first_be, last_be=last_be, payload=dwords)

            assert rq.errors == [], f"n={n} be={first_be:#x}/{last_be:#x}: {rq.errors}"
            assert len(rq.commands) == 1
            got_bc = rq.commands[0][2]
            assert got_bc == bc, f"n={n}: byte_count {got_bc} != {bc}"
            assert len(rq.payload) == n, f"n={n}: {len(rq.payload)} beats, want {n}"

            total = sum(popcount(k) for _d, k, _l in rq.payload)
            assert total == got_bc, \
                f"n={n} be={first_be:#x}/{last_be:#x}: sum(popcount(keep))={total} " \
                f"!= command_byte_count_o={got_bc}"

            lasts = [i for i, (_d, _k, l) in enumerate(rq.payload) if l]
            assert lasts == [n - 1], f"n={n}: last on beats {lasts}, want [{n - 1}]"

            # First and last Dwords carry exactly the descriptor's byte enables.
            assert rq.payload[0][1] == first_be
            if n > 1:
                assert rq.payload[-1][1] == last_be
            for _d, k, _l in rq.payload[1:-1]:
                assert k == 0xF, "interior Dwords are whole"


# ==========================================================================
# T10 -- backpressure equivalence
# ==========================================================================
@cocotb.test()
async def test_t10_backpressure(dut):
    """T10: random stalls on every handshake change nothing that is observed."""
    rq = await init(dut)
    rng = random.Random(0x1010)
    n = 17
    dwords = [rng.randrange(1 << 32) for _ in range(n)]
    desc = rq_desc(RQ_MEM_WRITE, n, address=0x20000, tc=2, attr=1)
    beats = [(desc, 0xF, False, tuser(0xE, 0x3))] + payload_beats(dwords, 0xE, 0x3)

    # Reference run, no backpressure anywhere.
    rq.clear()
    dut.command_ready_i.value = 1
    dut.command_data_ready_i.value = 1
    await rq.send(beats)
    await rq.settle(64)
    ref_cmd, ref_pay = list(rq.commands), list(rq.payload)
    assert rq.errors == [] and len(ref_cmd) == 1 and len(ref_pay) == n

    async def stall_ready(sig, seed):
        r = random.Random(seed)
        while True:
            await RisingEdge(dut.clk_i)
            sig.value = 1 if r.random() > 0.4 else 0

    t1 = cocotb.start_soon(stall_ready(dut.command_ready_i, 1))
    t2 = cocotb.start_soon(stall_ready(dut.command_data_ready_i, 2))

    rq.clear()
    await rq.send(beats, rng=random.Random(3), stall_prob=0.45)
    await rq.settle(400)
    t1.kill()
    t2.kill()
    dut.command_ready_i.value = 1
    dut.command_data_ready_i.value = 1

    assert rq.errors == [], f"backpressure produced errors {rq.errors}"
    assert rq.commands == ref_cmd, "command differs under backpressure"
    assert rq.payload == ref_pay, "payload differs under backpressure"


# ==========================================================================
# T11 -- core-managed tags
# ==========================================================================
async def strobe_tag(dut, tag):
    """Model one tlp_layer allocation: a 1-cycle allocated_tag_valid_i pulse.

    The real strobe is tag_valid && tag_ready inside tlp_layer, i.e. the cycle
    the tracker commits a tag (tlp_request_tracker.sv:113).  The end-to-end
    check that the presented tag is the one that reaches the wire is T16 in
    test_pcie_rq_if_tlp.py; here we only prove the wrapper forwards whatever
    the core allocated, and nothing from the descriptor.
    """
    dut.allocated_tag_i.value = tag
    dut.allocated_tag_valid_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.allocated_tag_valid_i.value = 0
    dut.allocated_tag_i.value = 0      # the value must not linger
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def test_t11_core_managed_tag(dut):
    """T11: pcie_rq_tag_o is the core's allocated tag, never the descriptor's.

    The descriptor-Tag-is-ignored half is unchanged from 2a-i; what changed in
    3129114 is the SOURCE -- the wrapper now forwards tlp_layer's
    allocated_tag_o / allocated_tag_valid_o instead of an integrator-supplied
    value that had no relationship to the tag on the wire.
    """
    rq = await init(dut)

    # A non-posted request whose descriptor Tag is 0xA5.  No allocation strobe
    # yet, so nothing may be presented -- the tag does not exist at the moment
    # the command is accepted (tlp_requester.sv:211, 215-218).
    desc = rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(0x06),
                   completer_id=0x100, tag=0xA5, requester_id=0xBEEF)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    assert rq.errors == []
    assert rq.tags == [], \
        f"tag presented before the core allocated one: {rq.tags}"
    _cmd, addr, _bc, _tc, _attr, _ctx = rq.commands[0]
    assert (addr >> 16) & 0xFFFF == 0x100, "Completer ID drives the address"
    assert 0xA5 not in (addr & 0xFF, (addr >> 8) & 0xFF), \
        "descriptor Tag must not leak into command_address"

    # Now the core allocates.  The wrapper presents exactly that value.
    rq.clear()
    await strobe_tag(dut, 0x17)
    assert rq.tags == [0x17], f"tags {rq.tags} -- must be the core's, not 0xA5"

    # A different allocation, same descriptor: the new value, once.
    rq.clear()
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    await strobe_tag(dut, 0x2C)
    assert rq.tags == [0x2C], f"tags {rq.tags}"

    # Two allocations back to back keep their order and their values.
    rq.clear()
    await strobe_tag(dut, 0x05)
    await strobe_tag(dut, 0x1E)
    assert rq.tags == [0x05, 0x1E], f"tags {rq.tags}"

    # A posted write allocates nothing upstream, so no strobe arrives and
    # nothing is presented -- and the descriptor's 0xA5 still does not appear.
    rq.clear()
    await one_shot(rq, rq_desc(RQ_MEM_WRITE, 1, address=0x2000, tag=0xA5),
                   first_be=0xF, last_be=0x0, payload=[0x12345678])
    assert rq.tags == [], "a posted MemWr must not present a tag"


# ==========================================================================
# Stage D-2 -- CFG1 through the RQ surface (docs/predictions/SPEC_PREDICTIONS_STAGE_D.md SS7.3)
# ==========================================================================
@cocotb.test()
async def test_d2s1_cfg1_admission(dut):
    """D2-S1 (F2.1/F2.2): req_type 1001/1011 admitted and mapped to the D-1b
    commands, with the WHOLE command tuple compared against a golden.

    Every descriptor field is a distinct nonzero value, and the compare is the
    full (cmd, address, byte_count, tc, attr, context) tuple, not a field
    subset -- a 1001 arm that reads the 1000 decode, or drops any field, fails
    here (mutation M2.3).
    """
    rq = await init(dut)

    # ---- CfgRd1: bus 0x2A, dev 3, fn 5, reg 0x11, ext 0x2, tc 2, attr 3 ----
    bdf, reg, ext = (0x2A << 8) | (0x03 << 3) | 0x5, 0x11, 0x2
    desc = rq_desc(RQ_CFG_READ1, 1, address=cfg_desc_address(reg, ext),
                   completer_id=bdf, tag=0x5A, tc=2, attr=3)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    assert rq.errors == [], \
        f"F2.1: CfgRd1 rejected with error code(s) {rq.errors} -- must be admitted"
    assert len(rq.commands) == 1, f"expected 1 command, got {len(rq.commands)}"
    golden = (CMD_CFG_READ1, cfg_address(bdf, ext, reg, 0), 4, 2, 3,
              (ext << 8) | (reg << 2))          # context: mem_read=0, addr[11:0]
    assert rq.commands[0] == golden, \
        f"CfgRd1 command tuple {rq.commands[0]} != golden {golden}"
    assert len(rq.payload) == 0, "a config read must not drive payload"

    # ---- CfgWr1: bus 0x37, dev 1, fn 6, reg 0x2C, ext 0x1, tc 4, attr 1 ----
    bdf, reg, ext = (0x37 << 8) | (0x01 << 3) | 0x6, 0x2C, 0x1
    value = 0xC0FFEE11
    desc = rq_desc(RQ_CFG_WRITE1, 1, address=cfg_desc_address(reg, ext),
                   completer_id=bdf, tc=4, attr=1)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0, payload=[value])
    assert rq.errors == [], \
        f"F2.2: CfgWr1 rejected with error code(s) {rq.errors} -- must be admitted"
    assert len(rq.commands) == 1
    golden = (CMD_CFG_WRITE1, cfg_address(bdf, ext, reg, 0), 4, 4, 1,
              (ext << 8) | (reg << 2))
    assert rq.commands[0] == golden, \
        f"CfgWr1 command tuple {rq.commands[0]} != golden {golden}"
    assert rq.payload == [(value, 0xF, 1)], \
        f"CfgWr1 payload {rq.payload} != one whole-Dword last beat"

    # The Type 0 pair still maps to ITS commands -- the pairs must not alias.
    desc = rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(reg, ext),
                   completer_id=bdf, tc=4, attr=1)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    assert rq.errors == [] and rq.commands[0][0] == CMD_CFG_READ0, \
        "CfgRd0 must still map to TLP_CMD_CFG_READ0"


@cocotb.test()
async def test_d2s2_cfg1_class_checks_live(dut):
    """D2-S2 (M2.2): the class-shaped config checks bind to CFG1 by
    construction -- prove them LIVE, not merely present.

    bad_cfg_n: Dword Count != 1 refused for both new types.  The byte-granular
    admission (d5a4253) also extends: a single-byte CfgWr1 is admitted with the
    right offset.  bad_cfg_fit stays unreachable through the config class --
    for N=1 every contiguous first_be satisfies popcount+offset <= 4, and for
    N!=1 bad_cfg_n fires first; that is the same recorded fact as T4's CFG0
    note, now inherited by CFG1 through the shared desc_is_config gate.
    """
    rq = await init(dut)
    bdf = (0x2A << 8) | (0x03 << 3) | 0x5

    # bad_cfg_n live for CfgRd1 and CfgWr1.
    await one_shot(rq, rq_desc(RQ_CFG_READ1, 2, address=cfg_desc_address(0x11),
                               completer_id=bdf), first_be=0xF, last_be=0xF)
    assert rq.errors == [ERR_CFG_DWORD_COUNT], \
        f"CfgRd1 N=2: errors {rq.errors} -- bad_cfg_n must gate CFG1"
    assert not rq.commands, "a rejected CfgRd1 must launch no command"

    await one_shot(rq, rq_desc(RQ_CFG_WRITE1, 2, address=cfg_desc_address(0x11),
                               completer_id=bdf), first_be=0xF, last_be=0xF,
                   payload=[1, 2])
    assert rq.errors == [ERR_CFG_DWORD_COUNT], \
        f"CfgWr1 N=2: errors {rq.errors} -- bad_cfg_n must gate CFG1"
    assert not rq.commands and not rq.payload

    # Byte-granular CfgWr1 (the d5a4253 admission, through the class gate):
    # first_be=0100 selects byte 2 -> offset 2, byte_count 1, and 1 <= 4-2.
    await one_shot(rq, rq_desc(RQ_CFG_WRITE1, 1, address=cfg_desc_address(0x2C),
                               completer_id=bdf), first_be=0x4, last_be=0x0,
                   payload=[0x00AB0000])
    assert rq.errors == [], f"byte-granular CfgWr1 rejected: {rq.errors}"
    assert len(rq.commands) == 1
    _cmd, addr, bc, _tc, _attr, _ctx = rq.commands[0]
    assert addr & 0x3 == 2, f"offset {addr & 3} != 2 for first_be=0100"
    assert bc == 1, f"byte_count {bc} != 1 for a single-byte write"
    assert sum(popcount(k) for _d, k, _l in rq.payload) == 1


@cocotb.test()
async def test_d2s3_reject_matrix(dut):
    """D2-S3 (F2.3, the control): every never-mapped encoding is rejected with
    RQ_ERR_REQ_TYPE exactly, and every pre-D-2 mapped type is still admitted.

    This is the test that catches a mis-typed case arm silently widening the
    accept set.  It must pass IDENTICALLY against pre-change and post-change
    RTL, which is why the CFG1 admissions live in D2-S1, not here.
    """
    rq = await init(dut)

    for req_type in RQ_NEVER_MAPPED:
        desc = rq_desc(req_type, 1, address=0x4000)
        await one_shot(rq, desc, first_be=0xF, last_be=0x0)
        assert rq.errors == [ERR_REQ_TYPE], \
            f"req_type={req_type:#06b}: errors {rq.errors} != [RQ_ERR_REQ_TYPE]"
        assert not rq.commands, f"req_type={req_type:#06b} launched a command"
        assert not rq.payload

    # The six pre-D-2 mappings are untouched: admitted, right command.
    for req_type, cmd, payload in (
            (RQ_MEM_READ, CMD_MEM_READ, None),
            (RQ_MEM_WRITE, CMD_MEM_WRITE, [0x11112222]),
            (RQ_IO_READ, CMD_IO_READ, None),
            (RQ_IO_WRITE, CMD_IO_WRITE, [0x33334444]),
    ):
        await one_shot(rq, rq_desc(req_type, 1, address=0x4000),
                       first_be=0xF, last_be=0x0, payload=payload)
        assert rq.errors == [], f"req_type={req_type:#06b}: {rq.errors}"
        assert len(rq.commands) == 1 and rq.commands[0][0] == cmd
    for req_type, cmd, payload in (
            (RQ_CFG_READ0, CMD_CFG_READ0, None),
            (RQ_CFG_WRITE0, CMD_CFG_WRITE0, [0x55556666]),
    ):
        await one_shot(rq, rq_desc(req_type, 1, address=cfg_desc_address(0x06),
                                   completer_id=0x0100),
                       first_be=0xF, last_be=0x0, payload=payload)
        assert rq.errors == [], f"req_type={req_type:#06b}: {rq.errors}"
        assert len(rq.commands) == 1 and rq.commands[0][0] == cmd


@cocotb.test()
async def test_d2s4_poison_membership(dut):
    """D2-S4 (F2.4 + the IO non-widening pin): bad_poison covers EXACTLY the
    two config writes.

    Rejected: poisoned CfgWr0 (pre-D-2 behaviour) and poisoned CfgWr1 (F2.4).
    Admitted: poisoned CfgRd1 (reads carry no data to poison), poisoned
    IO_WRITE and poisoned MEM_WRITE (poison origination is out of scope and
    they are forwarded unpoisoned, per KNOWN_GAPS) -- widening the check to IO
    would be a second behaviour change, and this test pins it out.
    """
    rq = await init(dut)
    bdf = (0x37 << 8) | (0x01 << 3) | 0x6

    await one_shot(rq, rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(0x06),
                               completer_id=0x0100, poisoned=1),
                   first_be=0xF, last_be=0x0, payload=[0])
    assert rq.errors == [ERR_POISON_CFG_WR], \
        f"poisoned CfgWr0: errors {rq.errors} != [RQ_ERR_POISON_CFG_WR]"
    assert not rq.commands

    await one_shot(rq, rq_desc(RQ_CFG_WRITE1, 1, address=cfg_desc_address(0x2C),
                               completer_id=bdf, poisoned=1),
                   first_be=0xF, last_be=0x0, payload=[0])
    assert rq.errors == [ERR_POISON_CFG_WR], \
        f"F2.4: poisoned CfgWr1 errors {rq.errors} != [RQ_ERR_POISON_CFG_WR]"
    assert not rq.commands, "a poisoned CfgWr1 must launch no command"

    # Poisoned CfgRd1: admitted -- only config WRITES are poison-gated.
    await one_shot(rq, rq_desc(RQ_CFG_READ1, 1, address=cfg_desc_address(0x11),
                               completer_id=bdf, poisoned=1),
                   first_be=0xF, last_be=0x0)
    assert rq.errors == [], f"poisoned CfgRd1 rejected: {rq.errors}"
    assert len(rq.commands) == 1 and rq.commands[0][0] == CMD_CFG_READ1

    # Poisoned IO and Memory writes: admitted unchanged (forwarded unpoisoned).
    await one_shot(rq, rq_desc(RQ_IO_WRITE, 1, address=0x1000, poisoned=1),
                   first_be=0xF, last_be=0x0, payload=[0x77778888])
    assert rq.errors == [], f"poisoned IO_WRITE rejected: {rq.errors}"
    assert len(rq.commands) == 1 and rq.commands[0][0] == CMD_IO_WRITE

    await one_shot(rq, rq_desc(RQ_MEM_WRITE, 1, address=0x2000, poisoned=1),
                   first_be=0xF, last_be=0x0, payload=[0x9999AAAA])
    assert rq.errors == [], f"poisoned MEM_WRITE rejected: {rq.errors}"
    assert len(rq.commands) == 1 and rq.commands[0][0] == CMD_MEM_WRITE


@cocotb.test()
async def test_d2s5_tripwire_pin(dut):
    """D2-S5: a Type 0 config request naming device != 0 is ADMITTED and
    forwarded UNCHANGED.

    This pins the DEFERRED consequence documented in pcie_rq_if's header
    (Stage D brief SS8.1): Base 2.1 SS7.3.1 p.479 wants such a request
    UR-terminated by a Root Port, but no sweep-capable requester exists yet,
    so the wrapper only fires a $warning tripwire (observable in the log, not
    a reject).  When real UR termination lands, THIS test must break -- the
    behaviour change is then a visible test change, not a silent one.
    """
    rq = await init(dut)

    # Bus 0x1C, DEVICE 5, fn 0 -- the device field is the point.
    bdf = (0x1C << 8) | (0x05 << 3) | 0x0
    desc = rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(0x00),
                   completer_id=bdf)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0)
    assert rq.errors == [], \
        f"deferred consequence violated: device!=0 CfgRd0 rejected {rq.errors}"
    assert len(rq.commands) == 1, "the request must be admitted"
    _cmd, addr, bc, _tc, _attr, _ctx = rq.commands[0]
    assert (addr >> 16) & 0xFFFF == bdf, \
        f"BDF {addr >> 16 & 0xFFFF:#06x} altered -- the device field must " \
        f"pass through unchanged ({bdf:#06x})"
    assert (addr >> 19) & 0x1F == 5, "the device number itself must survive"
    assert bc == 4

    # Same deferral for a Type 0 config WRITE to device != 0.
    desc = rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(0x01),
                   completer_id=bdf)
    await one_shot(rq, desc, first_be=0xF, last_be=0x0, payload=[0x0B0B0B0B])
    assert rq.errors == [] and len(rq.commands) == 1
    assert (rq.commands[0][1] >> 16) & 0xFFFF == bdf
