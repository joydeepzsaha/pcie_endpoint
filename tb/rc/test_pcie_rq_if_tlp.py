"""Commit 2a-i -- pcie_rq_if driving a real tlp_layer (T12..T15).

Same wire, new interface.  T12/T13 re-derive the Commit-1 config goldens and
assert them through the PG213 descriptor path, so a change in the front end
that altered what leaves the chip would show up here.  T14 is the Commit-2b
gate: a single-byte config write at offset 0x19 must emit exactly one TLP with
first_be=0010.  T15 checks that a well-formed multi-segment write produces zero
command_error_valid_o pulses -- the 0277358 property, now guaranteed upstream by
construction.

! FLOW CONTROL.  tlp_layer transmits nothing at all -- and reports no error --
until link_up_i, transmit_enable_i and fc_initialized_i are set and at least
one fc_update_valid_i pulse has loaded non-zero credits (tlp_layer.sv:249,
tlp_credit_manager.sv:53-54, 66-83).  Config requests consume NPH/NPD.  Every
"zero packets" result in this file would otherwise be meaningless.

RTL cited (read, not assumed):
  DW0 assembly ................... src/tlp/tlp_generator.sv:60-73
  DW1 = {rid, tag, last_be, first_be} .. src/tlp/tlp_generator.sv:80
  config DW2 = {address[31:2],00} .. src/tlp/tlp_generator.sv:81-82
  length encode .................. src/tlp/tlp_pkg.sv:85-87
  fmt/type encodings ............. src/tlp/tlp_pkg.sv:8-27
  command_error_valid_o .......... src/tlp/tlp_requester.sv:225-231
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_NS = 4

RQ_MEM_WRITE = 0b0001
RQ_CFG_READ0 = 0b1000
RQ_CFG_READ1 = 0b1001
RQ_CFG_WRITE0 = 0b1010
RQ_CFG_WRITE1 = 0b1011

# tlp_fmt_e / tlp_type_e (tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_MEM = 0b00000
TYPE_CFG0 = 0b00100
TYPE_CFG1 = 0b00101

RID = 0x1234


# --------------------------------------------------------------------------
# Spec goldens, hand-derived
# --------------------------------------------------------------------------
def enc_len(length_dw):
    """PCIe Length field: 1..1023 verbatim, 1024 -> 0 (tlp_pkg.sv:85-87)."""
    assert 1 <= length_dw <= 1024
    return 0 if length_dw == 1024 else (length_dw & 0x3FF)


def golden_dw0(fmt, typ, length_dw, tc=0, attr=0):
    """DW0 per the generator bit map (tlp_generator.sv:60-73)."""
    enc = enc_len(length_dw)
    v = 0
    v |= (fmt & 0x7) << 5
    v |= (typ & 0x1F)
    v |= ((attr >> 2) & 0x1) << 10
    v |= (tc & 0x7) << 12
    v |= ((enc >> 8) & 0x3) << 16
    v |= (attr & 0x3) << 20
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def dw1_fields(dw1):
    """Unpack DW1: {rid[31:16], tag[15:8], last_be[7:4], first_be[3:0]}."""
    return {
        "rid": (dw1 >> 16) & 0xFFFF,
        "tag": (dw1 >> 8) & 0xFF,
        "last_be": (dw1 >> 4) & 0xF,
        "first_be": dw1 & 0xF,
    }


def dw0_length(dw0):
    """Recover length_dw from DW0 (inverse of golden_dw0's encoding)."""
    enc = ((dw0 >> 24) & 0xFF) | (((dw0 >> 16) & 0x3) << 8)
    return 1024 if enc == 0 else enc


def rq_desc(req_type, dword_count, address=0, completer_id=0, tag=0,
            poisoned=0, tc=0, attr=0):
    v = address & ((1 << 64) - 1)
    v |= (dword_count & 0x7FF) << 64
    v |= (req_type & 0xF) << 75
    v |= (poisoned & 1) << 79
    v |= (tag & 0xFF) << 96
    v |= (completer_id & 0xFFFF) << 104
    v |= (tc & 0x7) << 121
    v |= (attr & 0x7) << 124
    return v


def cfg_desc_address(reg_num, ext_reg=0):
    return ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2)


def tuser(first_be, last_be):
    return ((last_be & 0xF) << 4) | (first_be & 0xF)


def cfg_wire_dw2(bus, dev, fn, reg_num, ext_reg=0):
    """The config-request address DW as the generator emits it: [1:0] forced 0."""
    return (((bus & 0xFF) << 24) | ((dev & 0x1F) << 19) | ((fn & 0x7) << 16)
            | ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2))


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
def init_flow_control(dut):
    """Advertise "FC initialized, credits saturated" on tlp_layer's VC0 inputs.

    Without this the credit manager holds request_ready_o low forever
    (tlp_credit_manager.sv:53-54, registers reset to zero at :66-72 and load
    only on fc_update_valid_i at :76-83) and tlp_layer transmits nothing.  This
    target exercises request origination, not flow control -- which has its own
    tb_tlp_credit_manager bench -- so the pool is held saturated and must never
    be the limiter.
    """
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1
    dut.fc_ph_i.value = 0xFF
    dut.fc_pd_i.value = 0xFFF
    dut.fc_nph_i.value = 0xFF
    dut.fc_npd_i.value = 0xFFF
    dut.fc_cplh_i.value = 0xFF
    dut.fc_cpld_i.value = 0xFFF


class Tx:
    """Records TX packets, RQ rejects and TL command errors, concurrently."""

    def __init__(self, dut):
        self.dut = dut
        self.packets = []
        self._cur = []
        self.command_errors = []
        self.rq_errors = []
        self.presented_tags = []   # pcie_rq_tag_o at each pcie_rq_tag_vld_o

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if int(d.rst_i.value):
                continue
            if int(d.m_dllp_axis_tvalid.value) and int(d.m_dllp_axis_tready.value):
                self._cur.append(int(d.m_dllp_axis_tdata.value))
                if int(d.m_dllp_axis_tlast.value):
                    self.packets.append(self._cur)
                    self._cur = []
            if int(d.command_error_valid_o.value):
                self.command_errors.append(int(d.command_error_code_flat.value))
            if int(d.rq_protocol_error_o.value):
                self.rq_errors.append(int(d.rq_error_code_o.value))
            if int(d.pcie_rq_tag_vld_o.value):
                self.presented_tags.append(int(d.pcie_rq_tag_o.value))

    def clear(self):
        self.packets.clear()
        self.command_errors.clear()
        self.rq_errors.clear()
        self.presented_tags.clear()


async def init(dut, max_payload=128, max_read=128):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    dut.transmit_enable_i.value = 0
    dut.s_axis_rq_tdata.value = 0
    dut.s_axis_rq_tkeep.value = 0
    dut.s_axis_rq_tvalid.value = 0
    dut.s_axis_rq_tlast.value = 0
    dut.s_axis_rq_tuser.value = 0
    dut.m_dllp_axis_tready.value = 1
    dut.requester_id_i.value = RID
    dut.max_payload_bytes_i.value = max_payload
    dut.max_read_bytes_i.value = max_read
    dut.fc_initialized_i.value = 0
    dut.fc_update_valid_i.value = 0
    dut.fc_ph_i.value = 0
    dut.fc_pd_i.value = 0
    dut.fc_nph_i.value = 0
    dut.fc_npd_i.value = 0
    dut.fc_cplh_i.value = 0
    dut.fc_cpld_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1
    init_flow_control(dut)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    tx = Tx(dut)
    tx.start()
    await RisingEdge(dut.clk_i)
    return tx


async def send(dut, beats):
    for data, keep, last, user in beats:
        dut.s_axis_rq_tdata.value = data
        dut.s_axis_rq_tkeep.value = keep
        dut.s_axis_rq_tlast.value = 1 if last else 0
        dut.s_axis_rq_tuser.value = user
        dut.s_axis_rq_tvalid.value = 1
        for _ in range(4000):
            await ReadOnly()
            fired = int(dut.s_axis_rq_tready.value) == 1
            await RisingEdge(dut.clk_i)
            if fired:
                break
        else:
            raise AssertionError("s_axis_rq_tready never asserted -- DUT stalled")
    dut.s_axis_rq_tvalid.value = 0
    dut.s_axis_rq_tlast.value = 0


def payload_beats(dwords, first_be, last_be):
    beats = []
    for base in range(0, len(dwords), 4):
        chunk = dwords[base:base + 4]
        data = 0
        for i, dw in enumerate(chunk):
            data |= (dw & 0xFFFFFFFF) << (32 * i)
        beats.append((data, (1 << len(chunk)) - 1,
                      base + 4 >= len(dwords), tuser(first_be, last_be)))
    return beats


async def settle(dut, cycles=64):
    dut.s_axis_rq_tvalid.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)


# ==========================================================================
# T12 -- CfgRd0 on the wire
# ==========================================================================
@cocotb.test()
async def test_t12_cfgrd0_on_wire(dut):
    """T12: a CfgRd0 descriptor still produces DW0 = 0x01000004.

    The Commit-1 golden, reached through the RQ descriptor path instead of the
    raw command port.  fmt=000 (3DW no data), type=00100 (CFG0) -> dw0[7:0]=0x04;
    length_dw=1 -> dw0[31:24]=0x01.
    """
    tx = await init(dut)
    bus, dev, fn, reg, ext = 0x01, 0x02, 0x03, 0x06, 0x0
    bdf = (bus << 8) | (dev << 3) | fn
    await send(dut, [(rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(reg, ext),
                              completer_id=bdf, tag=0xA5),
                      0xF, True, tuser(0xF, 0x0))])
    await settle(dut)

    assert tx.rq_errors == [], f"wrapper rejected a legal CfgRd0: {tx.rq_errors}"
    assert len(tx.packets) == 1, f"expected 1 TLP, got {len(tx.packets)}"
    p = tx.packets[0]
    want = golden_dw0(FMT_3DW_NO_DATA, TYPE_CFG0, 1)
    assert want == 0x01000004, "the hand-derived golden must be the Commit-1 one"
    assert p[0] == want, f"DW0 {p[0]:#010x} != {want:#010x}"

    f = dw1_fields(p[1])
    assert f["rid"] == RID, "the TL supplies the Requester ID, not the descriptor"
    assert f["first_be"] == 0xF and f["last_be"] == 0x0
    assert p[2] == cfg_wire_dw2(bus, dev, fn, reg, ext), \
        f"config DW2 {p[2]:#010x} != {cfg_wire_dw2(bus, dev, fn, reg, ext):#010x}"
    assert len(p) == 3, f"a config read is 3 Dwords, got {len(p)}"
    assert tx.command_errors == []


# ==========================================================================
# T13 -- CfgWr0 on the wire, with payload
# ==========================================================================
@cocotb.test()
async def test_t13_cfgwr0_on_wire(dut):
    """T13: a CfgWr0 descriptor still produces DW0 = 0x01000044 + its payload."""
    tx = await init(dut)
    bus, dev, fn, reg = 0x01, 0x02, 0x03, 0x06
    bdf = (bus << 8) | (dev << 3) | fn
    value = 0xDEADBEEF

    tx.clear()
    await send(dut, [(rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(reg),
                              completer_id=bdf),
                      0xF, False, tuser(0xF, 0x0)),
                     (value, 0x1, True, tuser(0xF, 0x0))])
    await settle(dut)

    assert tx.rq_errors == []
    assert len(tx.packets) == 1, f"expected 1 TLP, got {len(tx.packets)}"
    p = tx.packets[0]
    want = golden_dw0(FMT_3DW_DATA, TYPE_CFG0, 1)
    assert want == 0x01000044, "the hand-derived golden must be the Commit-1 one"
    assert p[0] == want, f"DW0 {p[0]:#010x} != {want:#010x}"

    f = dw1_fields(p[1])
    assert f["first_be"] == 0xF and f["last_be"] == 0x0
    assert p[2] == cfg_wire_dw2(bus, dev, fn, reg)
    assert len(p) == 4, f"a config write is 4 Dwords, got {len(p)}"
    assert p[3] == value, f"payload {p[3]:#010x} != {value:#010x}"
    assert tx.command_errors == []


# ==========================================================================
# T14 -- byte-granular CfgWr0 at offset 0x19 (the Commit-2b gate)
# ==========================================================================
@cocotb.test()
async def test_t14_byte_granular_cfgwr(dut):
    """T14: a single-byte config write at 0x19 emits ONE TLP with first_be=0010.

    Secondary Bus Number.  Before d5a4253 the TL refused this command outright
    (TLP_ERR_BAD_LENGTH, zero packets); at byte_count=4 it split into two
    spec-illegal config TLPs.  Both are gone: byte_count + address[1:0] <= 4 for
    every admitted shape, so length_dw is 1 by construction and
    calculate_segment cannot split (tlp_requester.sv:93-94, 125-126).
    """
    tx = await init(dut)
    bus, dev, fn = 0x01, 0x00, 0x00
    bdf = (bus << 8) | (dev << 3) | fn
    reg = 0x18 >> 2                 # register number of config Dword 0x18
    bus_number = 0x02

    tx.clear()
    # first_be=0010 selects byte 1 of Dword 0x18, i.e. config offset 0x19.
    await send(dut, [(rq_desc(RQ_CFG_WRITE0, 1, address=cfg_desc_address(reg),
                              completer_id=bdf),
                      0xF, False, tuser(0x2, 0x0)),
                     (bus_number << 8, 0x1, True, tuser(0x2, 0x0))])
    await settle(dut)

    assert tx.rq_errors == [], \
        f"wrapper refused a byte-granular config write: {tx.rq_errors}"
    assert len(tx.packets) == 1, \
        f"expected exactly ONE TLP (no split), got {len(tx.packets)}"
    p = tx.packets[0]
    assert p[0] == golden_dw0(FMT_3DW_DATA, TYPE_CFG0, 1), f"DW0 {p[0]:#010x}"
    assert dw0_length(p[0]) == 1, "config Length must be exactly 1 Dword"

    f = dw1_fields(p[1])
    assert f["first_be"] == 0b0010, f"first_be {f['first_be']:#06b} != 0010"
    assert f["last_be"] == 0b0000, f"last_be {f['last_be']:#06b} != 0000"
    assert p[2] == cfg_wire_dw2(bus, dev, fn, reg), \
        "the byte offset must not corrupt the register number on the wire"
    assert p[2] & 0x3 == 0, "the emitted config Dword's low bits are forced to 0"
    assert len(p) == 4
    # The payload byte must be realigned into lane 1 by the formatter.
    assert (p[3] >> 8) & 0xFF == bus_number, \
        f"payload {p[3]:#010x}: byte not placed in lane 1"
    assert tx.command_errors == []


# ==========================================================================
# T15 -- multi-segment MemWr, zero command errors
# ==========================================================================
@cocotb.test()
async def test_t15_multisegment_memwr(dut):
    """T15: a 64-Dword MemWr across several MPS segments raises no TL error.

    max_payload_bytes_i = 64 forces four segments, so command_data_last_o must
    be compared against END OF REQUEST, not end of segment (tlp_requester.sv:
    153-158).  Getting that wrong is exactly the 0277358 regression; the
    wrapper now makes it unreachable by deriving last from the descriptor's
    Dword Count.
    """
    tx = await init(dut, max_payload=64, max_read=64)
    rng = random.Random(0x1515)
    n = 64
    dwords = [rng.randrange(1 << 32) for _ in range(n)]

    tx.clear()
    beats = [(rq_desc(RQ_MEM_WRITE, n, address=0x10000), 0xF, False,
              tuser(0xF, 0xF))] + payload_beats(dwords, 0xF, 0xF)
    await send(dut, beats)
    await settle(dut, 400)

    assert tx.rq_errors == [], f"wrapper errors {tx.rq_errors}"
    assert tx.command_errors == [], \
        f"command_error_valid_o pulsed {len(tx.command_errors)} times: {tx.command_errors}"
    assert len(tx.packets) == 4, \
        f"64 Dwords at MPS=64 B is 4 segments, got {len(tx.packets)}"

    # Every segment is a 3DW MemWr header plus its payload, and the payload
    # Dwords concatenate back to exactly what was sent, in order.
    got = []
    for p in tx.packets:
        assert p[0] == golden_dw0(FMT_3DW_DATA, TYPE_MEM, 16), f"DW0 {p[0]:#010x}"
        assert len(p) == 3 + 16, f"segment length {len(p)}"
        got.extend(p[3:])
    assert got == dwords, "payload differs from what the host wrote"

    # And a second request straight afterwards still works.
    tx.clear()
    await send(dut, [(rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(0x06),
                              completer_id=0x0100),
                      0xF, True, tuser(0xF, 0x0))])
    await settle(dut)
    assert len(tx.packets) == 1 and tx.command_errors == []


# ==========================================================================
# T16 -- the presented tag IS the tag on the wire
# ==========================================================================
@cocotb.test()
async def test_t16_presented_tag_matches_wire(dut):
    """T16: pcie_rq_tag_o equals the emitted TLP's DW1 Tag field.

    The entire point of 3129114.  Before it, pcie_rq_tag_o carried an
    integrator-supplied rq_tag_i that had no relationship to the tag the
    tracker allocated, so a client correlating RQ against RC would have matched
    on a value that never appeared on the wire.
    """
    tx = await init(dut)
    bdf = (0x01 << 8) | (0x02 << 3) | 0x03

    tx.clear()
    await send(dut, [(rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(0x06),
                              completer_id=bdf, tag=0xA5),
                      0xF, True, tuser(0xF, 0x0))])
    await settle(dut)

    assert tx.rq_errors == [] and tx.command_errors == []
    assert len(tx.packets) == 1, f"expected 1 TLP, got {len(tx.packets)}"
    assert len(tx.presented_tags) == 1, \
        f"expected exactly one presented tag, got {tx.presented_tags}"

    wire_tag = dw1_fields(tx.packets[0][1])["tag"]
    assert tx.presented_tags[0] == wire_tag, \
        f"pcie_rq_tag_o={tx.presented_tags[0]:#04x} but the TLP carries " \
        f"tag={wire_tag:#04x} -- the RQ and RC sides would not correlate"


# ==========================================================================
# T17 -- several non-posted requests outstanding at once
# ==========================================================================
@cocotb.test()
async def test_t17_multiple_outstanding(dut):
    """T17: each presented tag matches ITS OWN TLP; no cross-assignment.

    No completions are injected, so the tracker never frees a tag
    (tlp_request_tracker.sv:113-120) and all four requests are outstanding
    simultaneously with distinct tags.
    """
    tx = await init(dut)
    bdf = (0x01 << 8) | (0x02 << 3) | 0x03

    tx.clear()
    for i in range(4):
        await send(dut, [(rq_desc(RQ_CFG_READ0, 1,
                                  address=cfg_desc_address(0x06 + i),
                                  completer_id=bdf, tag=0xA5),
                          0xF, True, tuser(0xF, 0x0))])
    await settle(dut, 128)

    assert tx.rq_errors == [] and tx.command_errors == []
    assert len(tx.packets) == 4, f"expected 4 TLPs, got {len(tx.packets)}"
    assert len(tx.presented_tags) == 4, \
        f"expected 4 presented tags, got {tx.presented_tags}"

    wire_tags = [dw1_fields(p[1])["tag"] for p in tx.packets]
    assert tx.presented_tags == wire_tags, \
        f"presented {tx.presented_tags} but the wire carried {wire_tags} " \
        "-- tags crossed between requests"
    assert len(set(wire_tags)) == 4, \
        f"four simultaneously outstanding requests must hold distinct tags: {wire_tags}"

    # And each TLP is still addressed to its own register, so the pairing is
    # between the right request and the right tag, not merely a sorted match.
    for i, p in enumerate(tx.packets):
        assert p[2] == cfg_wire_dw2(0x01, 0x02, 0x03, 0x06 + i), \
            f"packet {i} addresses the wrong register"


# ==========================================================================
# T18 -- posted writes allocate nothing
# ==========================================================================
@cocotb.test()
async def test_t18_posted_write_no_tag(dut):
    """T18: a posted MemWr never asserts pcie_rq_tag_vld_o.

    TLP_CMD_MEM_WRITE goes REQ_IDLE -> REQ_HEADER directly and never enters
    REQ_TAG (tlp_requester.sv:211, 253), so the tracker is never asked for a
    tag and the strobe has nothing to fire on.
    """
    tx = await init(dut, max_payload=64, max_read=64)
    rng = random.Random(0x1818)
    n = 32
    dwords = [rng.randrange(1 << 32) for _ in range(n)]

    tx.clear()
    beats = [(rq_desc(RQ_MEM_WRITE, n, address=0x10000), 0xF, False,
              tuser(0xF, 0xF))] + payload_beats(dwords, 0xF, 0xF)
    await send(dut, beats)
    await settle(dut, 256)

    assert tx.rq_errors == [] and tx.command_errors == []
    assert len(tx.packets) == 2, f"32 Dwords at MPS=64 B is 2 segments, got {len(tx.packets)}"
    assert tx.presented_tags == [], \
        f"a posted write allocated no tag, yet {tx.presented_tags} was presented"

    # A non-posted request right afterwards still gets one, so the absence
    # above is about posted writes and not about the strobe being dead.
    tx.clear()
    await send(dut, [(rq_desc(RQ_CFG_READ0, 1, address=cfg_desc_address(0x06),
                              completer_id=0x0100),
                      0xF, True, tuser(0xF, 0x0))])
    await settle(dut)
    assert len(tx.presented_tags) == 1, "the strobe must still work"
    assert tx.presented_tags[0] == dw1_fields(tx.packets[0][1])["tag"]


# ==========================================================================
# T19 -- the descriptor's Tag field goes nowhere
# ==========================================================================
@cocotb.test()
async def test_t19_descriptor_tag_ignored(dut):
    """T19: descriptor Tag [103:96] reaches neither pcie_rq_tag_o nor the wire.

    Driven nonzero and deliberately different from anything the tracker will
    allocate: the tracker hands out the lowest free index (0, 1, 2, ...,
    tlp_request_tracker.sv:56-63), so 0xA5 and 0x7E can never be a coincidence.
    """
    tx = await init(dut)
    bdf = (0x01 << 8) | (0x02 << 3) | 0x03

    for desc_tag in (0xA5, 0x7E, 0xFF):
        tx.clear()
        await send(dut, [(rq_desc(RQ_CFG_WRITE0, 1,
                                  address=cfg_desc_address(0x06),
                                  completer_id=bdf, tag=desc_tag),
                          0xF, False, tuser(0xF, 0x0)),
                         (0x12345678, 0x1, True, tuser(0xF, 0x0))])
        await settle(dut)

        assert tx.rq_errors == [] and len(tx.packets) == 1
        wire_tag = dw1_fields(tx.packets[0][1])["tag"]
        assert wire_tag != desc_tag, \
            f"descriptor Tag {desc_tag:#04x} reached the wire"
        assert desc_tag not in tx.presented_tags, \
            f"descriptor Tag {desc_tag:#04x} reached pcie_rq_tag_o"
        assert tx.presented_tags == [wire_tag], \
            f"presented {tx.presented_tags}, wire carried {wire_tag:#04x}"


# ==========================================================================
# T20 -- the strobe is gated on the allocation COMPLETING, not on asking
# ==========================================================================
@cocotb.test()
async def test_t20_tag_exhaustion_strobe(dut):
    """T20: a stalled allocation must not strobe, and must not repeat.

    tag_valid alone is "the requester is in REQ_TAG"; the tag is only committed
    when tag_ready is also high (tlp_request_tracker.sv:113).  Those two are
    indistinguishable while tags are plentiful, because REQ_TAG lasts a single
    cycle -- which is why this test drains the pool.

    TAG_COUNT is 32 and extended_tag_enable_i is 0, so the tracker refuses the
    33rd allocation (tlp_request_tracker.sv:56-65: tag_found stays low, and
    allocate_ready_o with it).  No completions are injected, so nothing is ever
    freed and the requester parks in REQ_TAG with tag_valid asserted for the
    rest of the test.  An ungated strobe would present a tag every cycle it
    sits there.
    """
    tx = await init(dut)
    bdf = (0x01 << 8) | (0x02 << 3) | 0x03
    tag_count = 32

    tx.clear()
    for i in range(tag_count + 1):
        await send(dut, [(rq_desc(RQ_CFG_READ0, 1,
                                  address=cfg_desc_address(i & 0x3F),
                                  completer_id=bdf),
                          0xF, True, tuser(0xF, 0x0))])
    await settle(dut, 400)

    assert tx.rq_errors == [] and tx.command_errors == []
    assert len(tx.packets) == tag_count, \
        f"only {tag_count} tags exist, so only {tag_count} TLPs can be emitted; " \
        f"got {len(tx.packets)}"
    assert len(tx.presented_tags) == tag_count, \
        f"expected exactly {tag_count} strobes, got {len(tx.presented_tags)} -- " \
        "the strobe is firing while the allocation is stalled"
    assert sorted(tx.presented_tags) == list(range(tag_count)), \
        f"the tracker hands out 0..{tag_count - 1}; presented {tx.presented_tags}"
    assert tx.presented_tags == [dw1_fields(p[1])["tag"] for p in tx.packets], \
        "presented tags diverged from the wire under tag pressure"


# ==========================================================================
# Stage D-2 -- CFG1 on the wire (SPEC_PREDICTIONS_STAGE_D.md SS7.3 / SS8.1)
# ==========================================================================
@cocotb.test()
async def test_d2i1_cfgrd1_on_wire(dut):
    """D2-I1 (F2.1 at the wire): a CfgRd1 descriptor emits DW0 = 0x01000005.

    The WHOLE first Dword is asserted, not a field subset -- Trap A: every
    other DW of a CfgRd1 is bit-identical to a CfgRd0's, so an assertion that
    skips dw0[4:0] passes against a DUT that emitted Type 0.  This is the
    check that kills mutation M2.1 (1001 arm mapped to TLP_CMD_CFG_READ0);
    the standalone descriptor test CANNOT kill it, by design.
    """
    tx = await init(dut)
    bus, dev, fn, reg, ext = 0x2A, 0x03, 0x5, 0x11, 0x2
    bdf = (bus << 8) | (dev << 3) | fn
    await send(dut, [(rq_desc(RQ_CFG_READ1, 1, address=cfg_desc_address(reg, ext),
                              completer_id=bdf, tag=0x5A),
                      0xF, True, tuser(0xF, 0x0))])
    await settle(dut)

    assert tx.rq_errors == [], \
        f"F2.1: wrapper rejected CfgRd1 with error code(s) {tx.rq_errors}"
    assert len(tx.packets) == 1, f"expected 1 TLP, got {len(tx.packets)}"
    p = tx.packets[0]
    want = golden_dw0(FMT_3DW_NO_DATA, TYPE_CFG1, 1)
    assert want == 0x01000005, "hand-derived CfgRd1 golden must be 0x01000005"
    assert p[0] == want, \
        f"DW0 {p[0]:#010x} != {want:#010x} (dw0[4:0]={p[0] & 0x1F:#07b})"

    f = dw1_fields(p[1])
    assert f["rid"] == RID and f["first_be"] == 0xF and f["last_be"] == 0x0
    assert p[2] == cfg_wire_dw2(bus, dev, fn, reg, ext), \
        f"DW2 {p[2]:#010x} != {cfg_wire_dw2(bus, dev, fn, reg, ext):#010x}"
    assert len(p) == 3, f"a config read is 3 Dwords, got {len(p)}"
    assert tx.command_errors == []
    # Tag correlation surface unchanged: the presented tag is the wire tag.
    assert tx.presented_tags == [f["tag"]], \
        f"presented {tx.presented_tags} != wire tag {f['tag']:#04x}"


@cocotb.test()
async def test_d2i2_cfgwr1_on_wire(dut):
    """D2-I2 (F2.2 at the wire): a CfgWr1 emits DW0 = 0x01000045 + payload.

    fmt=010 (3DW with data) -- the D-1b spine proved the requester takes the
    data path for CFG_WRITE1; this proves the RQ descriptor path reaches it
    and that the emitted packet is 4 Dwords with the byte realigned.
    """
    tx = await init(dut)
    bus, dev, fn, reg, ext = 0x37, 0x01, 0x6, 0x2C, 0x1
    bdf = (bus << 8) | (dev << 3) | fn
    value = 0xC0FFEE11

    tx.clear()
    await send(dut, [(rq_desc(RQ_CFG_WRITE1, 1, address=cfg_desc_address(reg, ext),
                              completer_id=bdf),
                      0xF, False, tuser(0xF, 0x0)),
                     (value, 0x1, True, tuser(0xF, 0x0))])
    await settle(dut)

    assert tx.rq_errors == [], \
        f"F2.2: wrapper rejected CfgWr1 with error code(s) {tx.rq_errors}"
    assert len(tx.packets) == 1, f"expected 1 TLP, got {len(tx.packets)}"
    p = tx.packets[0]
    want = golden_dw0(FMT_3DW_DATA, TYPE_CFG1, 1)
    assert want == 0x01000045, "hand-derived CfgWr1 golden must be 0x01000045"
    assert p[0] == want, \
        f"DW0 {p[0]:#010x} != {want:#010x} (dw0[4:0]={p[0] & 0x1F:#07b})"
    assert dw0_length(p[0]) == 1, "config Length must be exactly 1 Dword"

    f = dw1_fields(p[1])
    assert f["first_be"] == 0xF and f["last_be"] == 0x0
    assert p[2] == cfg_wire_dw2(bus, dev, fn, reg, ext)
    assert len(p) == 4, f"a config write is 4 Dwords, got {len(p)}"
    assert p[3] == value, f"payload {p[3]:#010x} != {value:#010x}"
    assert tx.command_errors == []


# ==========================================================================
# M2-I1 -- attribute placement on the wire, generator direction
# ==========================================================================
# The positions below are SPEC-DERIVED and written out literally rather than
# built by a helper, so this test cannot agree with a wrong golden.
#
#   PCIe Base 2.1 SS2.2.1 p.57  Attr[2] is bit 2 of byte 1
#                               Attr[1:0] are bits [5:4] of byte 2
#   SS2.2.6.3 p.73              Attr[2]=ID-Based Ordering, Attr[1]=Relaxed
#                               Ordering, Attr[0]=No Snoop -- and the spec's own
#                               text warns "attribute bit 2 is not adjacent to
#                               bits 1 and 0", which is the trap this catches.
#
# With header byte N at dw0[8N+7:8N] -- the mapping every other DW0 field in
# tlp_generator already uses -- that is dw0[10] and dw0[21:20].  PG213 Table 60
# gives the RQ descriptor's attr[126:124] the same {IDO, RO, NS} order, so
# descriptor bit n and Attr[n] are the same bit and no translation is involved.
ATTR_WIRE_POSITION = ((2, 10, "IDO"), (1, 21, "RO"), (0, 20, "NS"))
ATTR_DW0_MASK = (1 << 10) | (1 << 21) | (1 << 20)

# 0 and 7 are FIXED POINTS of the misplacement this test exists to catch: with
# all three bits equal, every permutation produces the same DW0.  They prove
# nothing on their own and are here only as controls.  5 is what the standalone
# generator test drives, and it pins only two of the three bits, because
# attr[0] == attr[2] there leaves dw0[10] identical under both placements.
# 1, 2 and 4 are one-hot: each isolates a single source bit, so the DW0 position
# that lights up IS that bit's destination, and the three together determine the
# map with no residual ambiguity.  See SPEC_PREDICTIONS_MERGE_M2.md SS7.
ATTR_DRIVE_SET = (1, 2, 4, 5, 7)


@cocotb.test()
async def test_m2i1_attr_bits_land_at_spec_wire_positions(dut):
    """M2-I1: Attr[2:0] from the RQ descriptor reaches its spec DW0 positions.

    Absolute-position assertions, never a round trip.  tlp_parser is the exact
    inverse of tlp_generator under BOTH placements, so parse(generate(a)) == a
    holds however the bits are physically arranged and a loopback has zero
    discriminating power -- which is why a misplacement survived three
    integration targets that each carry a real tlp_layer.  See
    SPEC_PREDICTIONS_MERGE_M2.md SS6.
    """
    tx = await init(dut)
    base_dw0 = golden_dw0(FMT_3DW_DATA, TYPE_MEM, 1)
    assert base_dw0 & ATTR_DW0_MASK == 0, \
        "the attr=0 golden must leave every attr bit clear, else the mask is wrong"

    for attr in ATTR_DRIVE_SET:
        tx.clear()
        # Dword Count 1 means last_be MUST be 0 -- the wrapper rejects
        # anything else as RQ_ERR_BE_MISMATCH, because the TL derives the byte
        # enables from address[1:0] and the byte count and cannot reproduce a
        # non-zero last_be on a single-Dword write (pcie_rq_rc_pkg.sv:96).
        await send(dut, [(rq_desc(RQ_MEM_WRITE, 1, address=0x10000, attr=attr),
                          0xF, False, tuser(0xF, 0x0))]
                        + payload_beats([0xA5A50000 | attr], 0xF, 0x0))
        await settle(dut)

        assert tx.rq_errors == [], \
            f"attr=0b{attr:03b} rejected by the wrapper: {tx.rq_errors}"
        assert tx.command_errors == [], \
            f"attr=0b{attr:03b} raised command errors {tx.command_errors}"
        assert len(tx.packets) == 1, \
            f"attr=0b{attr:03b}: expected 1 TLP, got {len(tx.packets)}"
        dw0 = tx.packets[0][0]

        for src, pos, name in ATTR_WIRE_POSITION:
            want = (attr >> src) & 1
            got = (dw0 >> pos) & 1
            assert got == want, (
                f"Attr[{src}] ({name}) must be DW0 bit {pos} "
                f"(Base 2.1 SS2.2.1 p.57): attr=0b{attr:03b} dw0={dw0:#010x} "
                f"bit{pos}={got}, expected {want}")

        assert dw0 & ~ATTR_DW0_MASK == base_dw0 & ~ATTR_DW0_MASK, (
            f"attr=0b{attr:03b} disturbed a non-attr DW0 field: "
            f"{dw0:#010x} vs {base_dw0:#010x}")
