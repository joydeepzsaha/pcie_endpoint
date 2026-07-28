"""Area 3 -- Parser robustness (TL conformance sweep).

Feeds hand-built, spec-derived TLP byte streams into tlp_parser (via the
flattening wrapper tb_tlp_conf_parser) and asserts the parsed tlp_header_t
fields, across all three classes, 3DW/4DW, with prefix and ECRC digest, plus
robustness: truncated, malformed-keep, poisoned, and reset-mid-packet recovery.

Golden byte streams are assembled from the PCIe TLP header format by hand.
Field extraction predictions are read from the RTL:
  DW0 field map .............. src/tlp/tlp_parser.sv:114-130
  DW1 req vs CPL ............. src/tlp/tlp_parser.sv:151-167
  DW2 req(3DW/4DW)/CPL ....... src/tlp/tlp_parser.sv:169-195
  CFG address not masked ..... src/tlp/tlp_parser.sv:187-190
  malformed / truncation ..... src/tlp/tlp_parser.sv:106-129,192-234
  prefix ..................... src/tlp/tlp_parser.sv:109-113
  ECRC digest capture ........ src/tlp/tlp_parser.sv:218-235
"""

import struct
import zlib

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

FMT_3DW_NO_DATA = 0b000
FMT_4DW_NO_DATA = 0b001
FMT_3DW_DATA = 0b010
FMT_4DW_DATA = 0b011
FMT_PREFIX = 0b100
TYPE_MEM = 0b00000
TYPE_IO = 0b00010
TYPE_CFG0 = 0b00100
TYPE_CPL = 0b01010
CPL_SC = 0b000
CPL_UR = 0b001


def dw0(fmt, typ, length_dw, tc=0, attr=0, ep=0, td=0, at=0, th=0):
    enc = 0 if length_dw == 1024 else (length_dw & 0x3FF)
    v = (fmt & 7) << 5 | (typ & 0x1F)
    v |= (th & 1) << 8
    v |= (attr & 1) << 10
    v |= (tc & 7) << 12
    v |= ((enc >> 8) & 3) << 16
    v |= (at & 3) << 18
    v |= ((attr >> 1) & 3) << 20
    v |= (ep & 1) << 22
    v |= (td & 1) << 23
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def dw1_req(rid, tag, last_be, first_be):
    return (rid << 16) | (tag << 8) | (last_be << 4) | first_be


def ecrc_of(dws):
    """The ECRC the parser computes over `dws` (the header + payload DWs).

    tlp_ecrc.sv is a reflected CRC-32: init 0xffffffff, polynomial 0xedb88320
    applied LSB-first per byte in ascending lane order (tlp_pkg.sv:135-163), with
    a final complement (tlp_ecrc.sv:35).  That is bit-for-bit standard CRC-32, so
    zlib.crc32 over the little-endian DW bytes reproduces it independently.

    The covered DWs are the ones the parser marks ecrc_data_valid
    (tlp_parser.sv:82-85): every header and payload DW, excluding a TLP prefix.
    """
    return zlib.crc32(b"".join(struct.pack("<I", d & 0xFFFFFFFF) for d in dws)) & 0xFFFFFFFF


def dw1_cpl(cid, status, byte_count, bcm=0):
    return (cid << 16) | (status << 13) | (bcm << 12) | (byte_count & 0xFFF)


def dw2_cpl(rid, tag, lower_address):
    return (rid << 16) | (tag << 8) | (lower_address & 0x7F)


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0xF
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.header_ready.value = 1
    dut.payload_tready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


class HeaderMon:
    """Captures header fields on the header_valid handshake, plus malformed pulses."""

    def __init__(self, dut):
        self.dut = dut
        self.hdrs = []
        self.malformed = 0
        self.payload = []
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await Timer(1, units="ps")
            if int(d.malformed.value):
                self.malformed += 1
            if int(d.header_valid.value) and int(d.header_ready.value):
                self.hdrs.append(dict(
                    fmt=int(d.header_fmt.value), typ=int(d.header_type.value),
                    length=int(d.header_length_dw.value),
                    rid=int(d.header_requester_id.value),
                    cid=int(d.header_completer_id.value),
                    tag=int(d.header_tag.value),
                    first_be=int(d.header_first_be.value),
                    last_be=int(d.header_last_be.value),
                    address=int(d.header_address.value),
                    status=int(d.header_status.value),
                    byte_count=int(d.header_byte_count.value),
                    lower=int(d.header_lower_address.value),
                    poisoned=int(d.header_poisoned.value),
                    prefix_present=int(d.header_prefix_present.value),
                    prefix=int(d.header_prefix.value),
                    digest_present=int(d.header_digest_present.value),
                ))
            if int(d.payload_tvalid.value) and int(d.payload_tready.value):
                self.payload.append(int(d.payload_tdata.value))


async def beat(dut, data, last=False, keep=0xF):
    dut.s_axis_tdata.value = data
    dut.s_axis_tkeep.value = keep
    dut.s_axis_tlast.value = 1 if last else 0
    dut.s_axis_tvalid.value = 1
    await Timer(1, units="ps")
    while not int(dut.s_axis_tready.value):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
    await RisingEdge(dut.clk_i)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0


async def settle(dut, n=6):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


# --------------------------------------------------------------------------
@cocotb.test()
async def parse_memwr_3dw(dut):
    """3DW MemWr: fmt/type/len, rid/tag, first/last BE, masked address, payload."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_3DW_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0xABCD, 0x05, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_1002)                     # addr; parser masks [1:0]
    await beat(dut, 0xDEAD_BEEF, last=True)
    await settle(dut)
    assert len(mon.hdrs) == 1, f"one header expected: {mon.hdrs}"
    h = mon.hdrs[0]
    assert h["fmt"] == FMT_3DW_DATA and h["typ"] == TYPE_MEM
    assert h["length"] == 1
    assert h["rid"] == 0xABCD and h["tag"] == 0x05
    assert h["first_be"] == 0xF and h["last_be"] == 0x0
    assert h["address"] == 0x0000_1000, f"addr {h['address']:#x} (must mask [1:0])"
    assert mon.payload == [0xDEAD_BEEF], mon.payload
    assert mon.malformed == 0


@cocotb.test()
async def parse_memrd_3dw(dut):
    """3DW MemRd ends at DW2 with tlast; not malformed, no payload."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 16))
    await beat(dut, dw1_req(0x1234, 0x07, last_be=0xF, first_be=0xF))
    await beat(dut, 0x0000_2000, last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["fmt"] == FMT_3DW_NO_DATA and h["typ"] == TYPE_MEM
    assert h["length"] == 16 and h["tag"] == 0x07
    assert h["address"] == 0x0000_2000
    assert mon.payload == [] and mon.malformed == 0


@cocotb.test()
async def parse_mem64_4dw(dut):
    """4DW MemRd: DW2=address[63:32], DW3=address[31:0] masked."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_4DW_NO_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_0001)                     # addr hi = 1
    await beat(dut, 0x0000_2006, last=True)          # addr lo; [1:0] masked off -> 0x2004
    await settle(dut)
    h = mon.hdrs[0]
    assert h["fmt"] == FMT_4DW_NO_DATA
    assert h["address"] == 0x0000_0001_0000_2004, \
        f"addr {h['address']:#x} != 0x1_00002004 (hi=1, lo 0x2006 masked to 0x2004)"
    assert mon.malformed == 0


@cocotb.test()
async def parse_cpld(dut):
    """CplD: completer_id/status/byte_count, requester_id/tag/lower_address, payload."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_3DW_DATA, TYPE_CPL, 2))
    await beat(dut, dw1_cpl(0x0113, CPL_SC, byte_count=8))
    await beat(dut, dw2_cpl(0x1234, 0x09, lower_address=0x04))
    await beat(dut, 0x1111_1111)
    await beat(dut, 0x2222_2222, last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["typ"] == TYPE_CPL and h["fmt"] == FMT_3DW_DATA
    assert h["length"] == 2
    assert h["cid"] == 0x0113 and h["status"] == CPL_SC
    assert h["byte_count"] == 8
    assert h["rid"] == 0x1234 and h["tag"] == 0x09 and h["lower"] == 0x04
    assert mon.payload == [0x1111_1111, 0x2222_2222], mon.payload
    assert mon.malformed == 0


@cocotb.test()
async def parse_cpl_nodata(dut):
    """Cpl (no data): length forced 0, byte_count parsed, ends at DW2."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    # A spec-legal Cpl (no data) carries Length field == 0.  The parser is
    # transparent to the field otherwise (a nonzero field survives and is left
    # for the classifier to reject), so the golden here uses field 0.
    nodata_cpl_dw0 = (FMT_3DW_NO_DATA << 5) | TYPE_CPL   # all length bits 0
    await beat(dut, nodata_cpl_dw0)
    await beat(dut, dw1_cpl(0x0113, CPL_UR, byte_count=4))
    await beat(dut, dw2_cpl(0x1234, 0x0A, lower_address=0x00), last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["typ"] == TYPE_CPL and h["fmt"] == FMT_3DW_NO_DATA
    assert h["length"] == 0, f"no-data CPL must parse length 0, got {h['length']}"
    assert h["status"] == CPL_UR and h["byte_count"] == 4
    assert h["tag"] == 0x0A
    assert mon.malformed == 0


@cocotb.test()
async def parse_cfg_address_unmasked(dut):
    """CFG0 request: DW2 copied verbatim into address (config DW, NOT [1:0]-masked)."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    cfg_dw = 0x0113_0011                                  # reg#... low bits meaningful
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_CFG0, 1))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF))
    await beat(dut, cfg_dw, last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["typ"] == TYPE_CFG0
    assert h["address"] == cfg_dw, \
        f"CFG DW must be copied verbatim, got {h['address']:#x} != {cfg_dw:#x}"
    assert mon.malformed == 0


@cocotb.test()
async def parse_prefix(dut):
    """A prefix DW (fmt=100) is recorded, then the following header parses."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    prefix_val = (FMT_PREFIX << 5) | 0x0A            # some prefix payload in low bits
    await beat(dut, prefix_val)                      # prefix DW
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_3000, last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["prefix_present"] == 1, "prefix flag not set"
    assert h["prefix"] == prefix_val, f"prefix {h['prefix']:#x} != {prefix_val:#x}"
    assert h["typ"] == TYPE_MEM and h["address"] == 0x0000_3000
    assert mon.malformed == 0


@cocotb.test()
async def parse_ecrc_digest(dut):
    """MemWr with digest_present: payload then a trailing ECRC DW captured.

    The merged parser validates the digest rather than merely capturing it
    (tlp_parser.sv:274 -- a mismatch is TLP_ERR_ECRC and the packet is dropped),
    so the trailing DW must be the real CRC over the preceding header+payload
    DWs.  It is computed here independently via zlib, not read back from the DUT.
    """
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    hdr = [dw0(FMT_3DW_DATA, TYPE_MEM, 1, td=1),
           dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF),
           0x0000_4000]
    payload = 0x5555_5555
    digest = ecrc_of(hdr + [payload])
    for dw in hdr:
        await beat(dut, dw)
    await beat(dut, payload)                         # payload (len=1, not last: ECRC follows)
    await beat(dut, digest, last=True)               # ECRC DW
    await settle(dut)
    h = mon.hdrs[0]
    assert h["digest_present"] == 1, "digest_present flag not set from DW0[23]"
    assert mon.payload == [payload], mon.payload
    # digest is captured into header_r during RX_ECRC (after header_valid); read it now
    await Timer(1, units="ps")
    assert int(dut.header_digest.value) == digest, \
        f"ECRC {int(dut.header_digest.value):#x} != {digest:#x}"
    assert mon.malformed == 0, "a correct ECRC must not be flagged malformed"
    assert int(dut.ecrc_error.value) == 0, "ecrc_error_o asserted on a valid digest"


@cocotb.test()
async def parse_poisoned(dut):
    """EP (poisoned) bit DW0[22] surfaces in header.poisoned."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_3DW_DATA, TYPE_MEM, 1, ep=1))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_5000)
    await beat(dut, 0xBAD0_DA7A, last=True)
    await settle(dut)
    h = mon.hdrs[0]
    assert h["poisoned"] == 1, "poisoned (EP) bit not surfaced"
    assert mon.malformed == 0


@cocotb.test()
async def parse_truncated(dut):
    """A read terminated early (tlast on DW1) is flagged malformed, then recovers."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0x0, first_be=0xF), last=True)  # truncated!
    await settle(dut)
    assert mon.malformed >= 1, "truncated packet must raise malformed_o"
    assert mon.hdrs == [], "truncated packet must not surface a header"
    # recovery: a clean packet now parses
    m2 = HeaderMon(dut); m2.start()
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 4))
    await beat(dut, dw1_req(0x1234, 0x11, last_be=0xF, first_be=0xF))
    await beat(dut, 0x0000_6000, last=True)
    await settle(dut)
    assert len(m2.hdrs) == 1 and m2.hdrs[0]["tag"] == 0x11, "parser did not recover"


@cocotb.test()
async def parse_bad_keep(dut):
    """First beat with tkeep!=0xF is malformed and dropped; parser recovers."""
    await init(dut)
    mon = HeaderMon(dut); mon.start()
    # malformed multi-beat packet: first beat keep=0x7, not last -> DROP until tlast
    await beat(dut, dw0(FMT_3DW_DATA, TYPE_MEM, 1), keep=0x7)
    await beat(dut, 0xAAAA_AAAA)
    await beat(dut, 0xBBBB_BBBB, last=True)
    await settle(dut)
    assert mon.malformed >= 1, "bad tkeep on first beat must raise malformed_o"
    assert mon.hdrs == [], "dropped packet must not surface a header"
    # recovery
    m2 = HeaderMon(dut); m2.start()
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0x1234, 0x22, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_7000, last=True)
    await settle(dut)
    assert len(m2.hdrs) == 1 and m2.hdrs[0]["tag"] == 0x22, "parser did not recover from DROP"


@cocotb.test()
async def parse_reset_mid_packet(dut):
    """Reset asserted mid-packet: no lockup, clean packet after parses correctly."""
    await init(dut)
    # feed a partial packet
    await beat(dut, dw0(FMT_3DW_DATA, TYPE_MEM, 4))
    await beat(dut, dw1_req(0x1234, 0x00, last_be=0xF, first_be=0xF))
    # yank reset mid-packet
    dut.rst_i.value = 1
    dut.s_axis_tvalid.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)
    mon = HeaderMon(dut); mon.start()
    # a clean packet must now parse from scratch
    await beat(dut, dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1))
    await beat(dut, dw1_req(0x1234, 0x33, last_be=0x0, first_be=0xF))
    await beat(dut, 0x0000_8000, last=True)
    await settle(dut)
    assert len(mon.hdrs) == 1, "parser locked up after mid-packet reset"
    assert mon.hdrs[0]["tag"] == 0x33 and mon.hdrs[0]["address"] == 0x0000_8000
    assert mon.malformed == 0
