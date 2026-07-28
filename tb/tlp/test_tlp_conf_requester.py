"""Area 1 -- Requester origination completeness (TL conformance sweep).

Extends Commit 1 (CFG0/CFG_WRITE0 already spec-locked in test_tlp_cfg0_spine)
to the rest of what the requester can emit: MemRd/MemWr/IORd/IOWr, 3DW vs 4DW
header selection, first/last byte-enable derivation, and segmentation on the
4KB boundary and on MPS/MRRS.

SPEC-GOLDEN DISCIPLINE: every expected DW is hand-derived from the PCIe base
spec TLP header format, NOT read back from the DUT.  Byte-enable golden is a
from-scratch reimplementation of the PCIe first/last-BE rules (independent of
the DUT's tlp_pkg helpers), so agreement actually validates the DUT.

RTL cited (read, not assumed):
  requester header build ...... src/tlp/tlp_requester.sv:103-135
  command_limit (CFG/IO=4B,
    MemRd=MRRS, MemWr=MPS) ..... src/tlp/tlp_requester.sv:75-82
  calculate_segment (4KB +
    aligned MPS/MRRS) .......... src/tlp/tlp_requester.sv:84-101
  generator DW0/DW1/DW2/DW3 ... src/tlp/tlp_generator.sv:49-72,102-112
  length encode ............... src/tlp/tlp_pkg.sv:85-87
  fmt/type encodings .......... src/tlp/tlp_pkg.sv:8-27
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# tlp_cmd_e (tlp_pkg.sv:43-50)
CMD_MEM_READ = 0
CMD_MEM_WRITE = 1
CMD_CFG_READ0 = 2
CMD_CFG_WRITE0 = 3
CMD_IO_READ = 4
CMD_IO_WRITE = 5

# tlp_fmt_e / tlp_type_e (tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_4DW_NO_DATA = 0b001
FMT_3DW_DATA = 0b010
FMT_4DW_DATA = 0b011
TYPE_MEM = 0b00000
TYPE_IO = 0b00010

RID = 0x1234


# --------------------------------------------------------------------------
# Spec-golden helpers (hand-derived, independent of tlp_pkg)
# --------------------------------------------------------------------------
def enc_len(length_dw):
    """PCIe Length field: 1..1023 verbatim, 1024 -> 0 (tlp_pkg.sv:85-87)."""
    assert 1 <= length_dw <= 1024
    return 0 if length_dw == 1024 else (length_dw & 0x3FF)


def golden_dw0(fmt, typ, length_dw, tc=0, attr=0):
    """DW0 per the generator bit map (tlp_generator.sv:49-62)."""
    enc = enc_len(length_dw)
    v = 0
    v |= (fmt & 0x7) << 5
    v |= (typ & 0x1F)
    v |= (attr & 0x1) << 10
    v |= (tc & 0x7) << 12
    v |= ((enc >> 8) & 0x3) << 16
    v |= ((attr >> 1) & 0x3) << 20
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def spec_first_be(off, nbytes):
    """PCIe First-BE: bytes [off, off+n) within the first DW, capped at 4."""
    if off + nbytes <= 4:            # whole transfer fits one DW
        return (((1 << nbytes) - 1) << off) & 0xF
    return (0xF << off) & 0xF        # from off to end of DW


def spec_last_be(off, nbytes):
    """PCIe Last-BE: 0 when the transfer is a single DW, else the tail mask."""
    if off + nbytes <= 4:
        return 0x0
    end = (off + nbytes) & 0x3
    return 0xF if end == 0 else ((1 << end) - 1)


def golden_dw1(rid, tag, first_be, last_be):
    """DW1 non-CPL: {rid, tag, last_be, first_be} (tlp_generator.sv:69)."""
    return ((rid & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | \
           ((last_be & 0xF) << 4) | (first_be & 0xF)


def golden_len_dw(off, nbytes):
    """length_dw = ceil((nbytes+off)/4) (tlp_requester.sv:125)."""
    return (nbytes + off + 3) >> 2


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
def init_flow_control(dut):
    """Advertise "FC initialized, credits saturated" on tlp_layer's VC0 inputs.

    The merged tlp_layer gates every TX packet on the credit manager:
      tlp_layer.sv:249   vc_packet_ready = credit_request_ready && ...
      tlp_credit_manager.sv:53  request_ready_o = fc_initialized_i &&
                                selected_header_available && selected_data_available
    The credit registers reset to zero (tlp_credit_manager.sv:67-73) and only
    load on fc_update_valid_i, so a harness that leaves these at 0 never
    transmits a single packet.  This target exercises requester origination, not
    flow control -- which has its own tb_tlp_credit_manager bench -- so the
    credit pool is held saturated and must never be the limiter.
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
    """Concurrently records every accepted TX beat, split into packets on tlast."""

    def __init__(self, dut):
        self.dut = dut
        self.packets = []
        self._cur = []
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())

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


async def issue_read(dut, cmd, address, byte_count):
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


async def issue_write(dut, cmd, address, byte_count, data_dws, keep_last=0xF):
    """Issue a write command, then stream data_dws (list of 32-bit DWs)."""
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
    # stream data
    n = len(data_dws)
    for i, dw in enumerate(data_dws):
        last = (i == n - 1)
        dut.command_data_i.value = dw
        dut.command_keep_i.value = keep_last if last else 0xF
        dut.command_data_valid_i.value = 1
        dut.command_data_last_i.value = 1 if last else 0
        await Timer(1, units="ps")
        while not int(dut.command_data_ready_o.value):
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
        await RisingEdge(dut.clk_i)
    dut.command_data_valid_i.value = 0
    dut.command_data_last_i.value = 0


async def settle(dut, n=12):
    for _ in range(n):
        await RisingEdge(dut.clk_i)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
@cocotb.test()
async def memrd_3dw_aligned(dut):
    """MemRd, 32-bit aligned, 4 bytes -> 3DW no-data header, len=1, tag held."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_1000
    await issue_read(dut, CMD_MEM_READ, addr, 4)
    await settle(dut)
    assert len(cap.packets) == 1, f"expected 1 packet, got {cap.packets}"
    p = cap.packets[0]
    assert len(p) == 3, f"MemRd 3DW must be 3 beats, got {len(p)}: {p}"
    assert p[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1), \
        f"DW0 {p[0][0]:#010x} != {golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 1):#010x}"
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(0, 4), spec_last_be(0, 4))
    assert p[2] == (addr & 0xFFFFFFFC, 1), f"DW2 {p[2]}"
    assert int(dut.outstanding_o.value) == 1, "MemRd is non-posted; tag must be held"


@cocotb.test()
async def memrd_3dw_multi_dw(dut):
    """MemRd 64 bytes aligned -> len=16, first_be=last_be=0xF, single packet."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_2000
    await issue_read(dut, CMD_MEM_READ, addr, 64)  # 64<=128 MRRS, no 4KB cross
    await settle(dut)
    assert len(cap.packets) == 1
    p = cap.packets[0]
    assert len(p) == 3
    assert p[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 16)
    assert p[1][0] == golden_dw1(RID, 0, 0xF, 0xF)
    assert p[2][0] == (addr & 0xFFFFFFFC)


@cocotb.test()
async def memrd_unaligned_be(dut):
    """MemRd offset=2, 4 bytes -> len=2, first_be=0xC, last_be=0x3."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_3002
    await issue_read(dut, CMD_MEM_READ, addr, 4)
    await settle(dut)
    p = cap.packets[0]
    off = addr & 0x3
    assert spec_first_be(off, 4) == 0xC and spec_last_be(off, 4) == 0x3, "BE golden self-check"
    assert p[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, golden_len_dw(off, 4))
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(off, 4), spec_last_be(off, 4)), \
        f"DW1 {p[1][0]:#010x}"
    assert p[2][0] == (addr & 0xFFFFFFFC)


@cocotb.test()
async def mem64_read_4dw(dut):
    """MemRd with address[63:32]!=0 -> 4DW no-data header (DW2=hi, DW3=lo)."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_0001_0000_2000
    await issue_read(dut, CMD_MEM_READ, addr, 4)
    await settle(dut)
    p = cap.packets[0]
    assert len(p) == 4, f"Mem64 must be 4DW, got {len(p)}: {p}"
    assert p[0][0] == golden_dw0(FMT_4DW_NO_DATA, TYPE_MEM, 1)
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(0, 4), spec_last_be(0, 4))
    assert p[2][0] == (addr >> 32) & 0xFFFFFFFF, f"DW2(hi) {p[2][0]:#010x}"
    assert p[3] == (addr & 0xFFFFFFFC, 1), f"DW3(lo) {p[3]}"


@cocotb.test()
async def iord_3dw(dut):
    """IORd -> type=IO, 3DW no-data, non-posted (tag held)."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_4000
    await issue_read(dut, CMD_IO_READ, addr, 4)
    await settle(dut)
    p = cap.packets[0]
    assert len(p) == 3
    assert p[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_IO, 1), f"DW0 {p[0][0]:#010x}"
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(0, 4), spec_last_be(0, 4))
    assert p[2][0] == (addr & 0xFFFFFFFC)
    assert int(dut.outstanding_o.value) == 1


@cocotb.test()
async def iowr_3dw(dut):
    """IOWr -> type=IO, 3DW+data, non-posted (tag held, expects no data back)."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_4000
    data = 0x11223344
    await issue_write(dut, CMD_IO_WRITE, addr, 4, [data])
    await settle(dut)
    p = cap.packets[0]
    assert len(p) == 4, f"IOWr must be 3DW+1data, got {len(p)}: {p}"
    assert p[0][0] == golden_dw0(FMT_3DW_DATA, TYPE_IO, 1), f"DW0 {p[0][0]:#010x}"
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(0, 4), spec_last_be(0, 4))
    assert p[2][0] == (addr & 0xFFFFFFFC)
    assert p[3] == (data, 1), f"payload {p[3]}"
    assert int(dut.outstanding_o.value) == 1, "IOWr is non-posted; tag must be held"


@cocotb.test()
async def memwr_3dw_single(dut):
    """MemWr aligned 4 bytes -> 3DW+data, posted (no tag held)."""
    await init_top(dut)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_5000
    data = 0xCAFEF00D
    await issue_write(dut, CMD_MEM_WRITE, addr, 4, [data])
    await settle(dut)
    p = cap.packets[0]
    assert len(p) == 4, f"MemWr must be 3DW+1data, got {len(p)}: {p}"
    assert p[0][0] == golden_dw0(FMT_3DW_DATA, TYPE_MEM, 1), f"DW0 {p[0][0]:#010x}"
    assert p[1][0] == golden_dw1(RID, 0, spec_first_be(0, 4), spec_last_be(0, 4))
    assert p[2][0] == (addr & 0xFFFFFFFC)
    assert p[3] == (data, 1), f"payload {p[3]}"
    assert int(dut.outstanding_o.value) == 0, "MemWr is posted; no tag"


@cocotb.test()
async def memrd_mrrs_segmentation(dut):
    """MemRd 256B with MRRS=128 -> two 128B (len=32) reads, tags 0 and 1."""
    await init_top(dut, max_read=128)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_6000
    await issue_read(dut, CMD_MEM_READ, addr, 256)
    await settle(dut, 24)
    assert len(cap.packets) == 2, f"expected 2 segments, got {len(cap.packets)}"
    # seg0
    p0 = cap.packets[0]
    assert p0[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 32), f"seg0 DW0 {p0[0][0]:#010x}"
    assert p0[1][0] == golden_dw1(RID, 0, 0xF, 0xF), f"seg0 DW1 {p0[1][0]:#010x}"
    assert p0[2][0] == addr
    # seg1 -- address advanced by 128, next tag
    p1 = cap.packets[1]
    assert p1[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 32), f"seg1 DW0 {p1[0][0]:#010x}"
    assert p1[1][0] == golden_dw1(RID, 1, 0xF, 0xF), f"seg1 DW1 {p1[1][0]:#010x}"
    assert p1[2][0] == addr + 128, f"seg1 addr {p1[2][0]:#010x}"
    assert int(dut.outstanding_o.value) == 2, "both read tags outstanding"


@cocotb.test()
async def memrd_4kb_boundary_split(dut):
    """MemRd 512B starting 256B below a 4KB boundary -> split 256+256.

    addr=0x6F00 (addr[11:0]=0xF00), MRRS=512.  calculate_segment:
      boundary = 4096-0xF00 = 0x100 = 256  -> seg0 = 256B (len=64) at 0x6F00
      seg1 = remaining 256B (len=64) at 0x7000  (tlp_requester.sv:92-100)
    """
    await init_top(dut, max_read=512)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_6F00
    await issue_read(dut, CMD_MEM_READ, addr, 512)
    await settle(dut, 24)
    assert len(cap.packets) == 2, f"expected split at 4KB, got {len(cap.packets)}"
    p0, p1 = cap.packets
    assert p0[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 64), f"seg0 DW0 {p0[0][0]:#010x}"
    assert p0[2][0] == addr, f"seg0 addr {p0[2][0]:#010x}"
    assert p1[0][0] == golden_dw0(FMT_3DW_NO_DATA, TYPE_MEM, 64), f"seg1 DW0 {p1[0][0]:#010x}"
    assert p1[2][0] == 0x0000_7000, f"seg1 addr {p1[2][0]:#010x} != 0x7000"


@cocotb.test()
async def memwr_mps_segmentation(dut):
    """MemWr 256B with MPS=128 -> two posted 128B (len=32) writes, no tags."""
    await init_top(dut, max_payload=128)
    cap = TxCapture(dut); cap.start()
    addr = 0x0000_7000
    data = [0xA0000000 | i for i in range(64)]  # 64 DW = 256 bytes
    await issue_write(dut, CMD_MEM_WRITE, addr, 256, data)
    await settle(dut, 40)
    assert len(cap.packets) == 2, f"expected 2 MPS segments, got {len(cap.packets)}"
    p0, p1 = cap.packets
    assert p0[0][0] == golden_dw0(FMT_3DW_DATA, TYPE_MEM, 32), f"seg0 DW0 {p0[0][0]:#010x}"
    assert p0[2][0] == addr
    assert len(p0) == 3 + 32, f"seg0 must carry 32 payload DW, got {len(p0)-3}"
    assert [d for d, _ in p0[3:]] == data[:32], "seg0 payload mismatch"
    assert p1[0][0] == golden_dw0(FMT_3DW_DATA, TYPE_MEM, 32), f"seg1 DW0 {p1[0][0]:#010x}"
    assert p1[2][0] == addr + 128, f"seg1 addr {p1[2][0]:#010x}"
    assert [d for d, _ in p1[3:]] == data[32:], "seg1 payload mismatch"
    assert int(dut.outstanding_o.value) == 0, "posted writes hold no tag"
