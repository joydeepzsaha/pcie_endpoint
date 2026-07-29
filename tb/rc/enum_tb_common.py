"""Shared spec-golden helpers for the Commit 2b enumeration benches.

One importable module rather than a copy per test file: the descriptor builders
and decoders below are GOLDENS, and a golden that exists in three slightly
divergent copies is not a golden.  `tb_rc.core` gives this file its own `copyto`
entry in every fileset that needs it.

Everything here is hand-derived from the specification:

  RQ descriptor, Configuration form ... PG213 v1.3 Table 61
                                        (pg213 markdown :3711,:3720,:3728,:3735)
  RQ Request Type encodings ........... PG213 v1.3 Table 57 (via :3725)
  RC descriptor ....................... PG213 v1.3 Table 65 (:4034); bit 30
                                        "Request Completed" at :4049;
                                        Completion Status [45:43] at :4052
  Configuration Request header ........ PCIe Base 2.1 SS2.2.7 p.79-80
  Completion header ................... PCIe Base 2.1 SS2.2.9 p.97-98
  Config Space Type 0 header offsets .. PCIe Base 2.1 Figure 7-5 p.491

Nothing here is read back from a DUT.  The 128-bit RQ descriptor values these
builders produce are pinned independently in SPEC_PREDICTIONS_ENUM.md SS3.4,
which was committed before any of this RTL existed; `assert_rq_descriptor`
below is what ties the two together.
"""

# ---------------------------------------------------------------------------
# Encodings
# ---------------------------------------------------------------------------

# pcie_rq_rc_pkg::rq_req_type_e  (PG213 Table 57)
RQ_CFG_READ0 = 0b1000
RQ_CFG_WRITE0 = 0b1010

# pcie_rq_rc_pkg::rc_cpl_status_e == PG213 [45:43] == PCIe CPL Completion Status
CPL_SC = 0b000
CPL_UR = 0b001
CPL_CRS = 0b010
CPL_CA = 0b100
# The four RESERVED encodings.  Base 2.1 SS2.3.2 p.122: "Completions with a
# Reserved Completion Status value are treated as if the Completion Status was
# Unsupported Request (UR)."  Named so tests can drive them deliberately.
CPL_RESERVED = (0b011, 0b101, 0b110, 0b111)

# pcie_rq_rc_pkg::rc_desc_error_e
EC_NORMAL = 0b0000
EC_POISONED = 0b0001
EC_BAD_STATUS = 0b0010          # terminated by UR / CA / CRS

# pcie_rq_rc_pkg::rc_error_e
RC_ERR_ORPHAN_DATA = 3

# pcie_enum_pkg::txn_outcome_e
TXN_OK = 0
TXN_UR = 1
TXN_CA = 2
TXN_CRS_EXHAUSTED = 3
TXN_TIMEOUT = 4

TXN_NAME = {
    TXN_OK: "TXN_OK",
    TXN_UR: "TXN_UR",
    TXN_CA: "TXN_CA",
    TXN_CRS_EXHAUSTED: "TXN_CRS_EXHAUSTED",
    TXN_TIMEOUT: "TXN_TIMEOUT",
}

# pcie_enum_pkg config register numbers (Base 2.1 Figure 7-5 p.491)
CFG_REG_VENDOR_DEVICE = 0x00
CFG_REG_COMMAND_STATUS = 0x01
CFG_REG_REVISION_CLASS = 0x02
CFG_REG_CACHE_HEADER = 0x03
CFG_REG_BAR0 = 0x04

# Byte enables.  Base 2.1 SS2.2.7 p.79 pins Last DW BE to 0000b for every
# Configuration Request, so only first_be is ever a choice.
CFG_BE_DWORD = 0b1111
CFG_BE_LOWER_HALF = 0b0011
CFG_BE_BYTE2 = 0b0100
CFG_LAST_BE = 0b0000

# tlp_pkg::tlp_fmt_e / tlp_type_e (tlp_pkg.sv:8-27), for the integration bench
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CFG0 = 0b00100
TYPE_CPL = 0b01010


# ---------------------------------------------------------------------------
# RQ descriptor -- what the DUT must emit
# ---------------------------------------------------------------------------
def rq_desc(req_type, dword_count=1, address=0, completer_id=0, tc=0, attr=0,
            poisoned=0, tag=0, requester_id=0):
    """PG213 Table 61 / Table 60 RQ descriptor, 128 bits.

    Tag [103:96] and Requester ID [95:80] are IGNORED by the core (tags are
    core-managed, the TL uses requester_id_i) but are settable so a test can
    prove the DUT leaves them zero rather than merely that the core ignores them.
    """
    v = address & ((1 << 64) - 1)
    v |= (dword_count & 0x7FF) << 64
    v |= (req_type & 0xF) << 75
    v |= (poisoned & 0x1) << 79
    v |= (requester_id & 0xFFFF) << 80
    v |= (tag & 0xFF) << 96
    v |= (completer_id & 0xFFFF) << 104
    v |= (tc & 0x7) << 121
    v |= (attr & 0x7) << 124
    return v


def cfg_desc_address(reg_num, ext_reg=0):
    """Configuration form of the RQ descriptor address.

    {Reserved[63:12], Ext Reg Number[11:8], Register Number[7:2], Reserved[1:0]}
    -- PG213 Table 61 :3715-3718.  Bits [1:0] are Reserved: the byte within the
    Dword is selected by first_be, never by the address.
    """
    return ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2)


def decode_rq_desc(v):
    """Inverse of rq_desc(), for asserting on what the DUT actually drove."""
    return {
        "address": v & ((1 << 64) - 1),
        "reg_num": (v >> 2) & 0x3F,
        "ext_reg": (v >> 8) & 0xF,
        "dword_count": (v >> 64) & 0x7FF,
        "req_type": (v >> 75) & 0xF,
        "poisoned": (v >> 79) & 1,
        "requester_id": (v >> 80) & 0xFFFF,
        "tag": (v >> 96) & 0xFF,
        "completer_id": (v >> 104) & 0xFFFF,
        "requester_id_en": (v >> 120) & 1,
        "tc": (v >> 121) & 0x7,
        "attr": (v >> 124) & 0x7,
        "force_ecrc": (v >> 127) & 1,
    }


def tuser(first_be, last_be=CFG_LAST_BE):
    """s_axis_rq_tuser: [3:0] first_be, [7:4] last_be (PG213, pcie_rq_if.sv:147)."""
    return ((last_be & 0xF) << 4) | (first_be & 0xF)


def decode_tuser(v):
    return {"first_be": v & 0xF, "last_be": (v >> 4) & 0xF}


def assert_rq_descriptor(observed_desc, observed_tuser, *, write, bdf, reg_num,
                         first_be, ext_reg=0, what=""):
    """Assert one emitted RQ descriptor against a freshly built golden.

    Compares the WHOLE 128-bit word, not a field subset: a field the DUT sets
    that the golden leaves zero is exactly the kind of thing a per-field check
    misses.  Reports the field-level diff on failure so the whole-word compare
    stays debuggable.
    """
    golden = rq_desc(
        RQ_CFG_WRITE0 if write else RQ_CFG_READ0,
        dword_count=1,
        address=cfg_desc_address(reg_num, ext_reg),
        completer_id=bdf,
    )
    if observed_desc != golden:
        got, exp = decode_rq_desc(observed_desc), decode_rq_desc(golden)
        diff = {k: (hex(got[k]), hex(exp[k])) for k in exp if got[k] != exp[k]}
        raise AssertionError(
            f"{what}RQ descriptor mismatch\n"
            f"  observed 0x{observed_desc:032X}\n"
            f"  golden   0x{golden:032X}\n"
            f"  fields (got, expected): {diff}")
    exp_user = tuser(first_be)
    if (observed_tuser & 0xFF) != exp_user:
        raise AssertionError(
            f"{what}tuser mismatch: observed {decode_tuser(observed_tuser & 0xFF)}, "
            f"expected {decode_tuser(exp_user)} "
            f"(Last DW BE must be 0000b for every Configuration Request -- "
            f"Base 2.1 SS2.2.7 p.79)")


# ---------------------------------------------------------------------------
# RC descriptor -- what the socket delivers back
# ---------------------------------------------------------------------------
def encode_rc_desc(tag, status=CPL_SC, dword_count=None, request_completed=1,
                   byte_count=None, error_code=None, lower_address=0,
                   requester_id=0, completer_id=0, tc=0, attr=0, poisoned=0,
                   locked=0):
    """PG213 Table 65, the 96-bit RC descriptor.

    Defaults follow what pcie_rc_if would actually build for a configuration
    completion, so a bench that does not override them is driving a realistic
    packet rather than an arbitrary one:

      * a Successful Completion to a config READ carries one Dword;
      * every non-SC status carries NO data and sets Request Completed --
        Base 2.1 SS2.3.2 p.122 ("No data is included with the Completion ...
        This Completion is the final Completion for the Request") and
        PG213 :4242 for the matching Error Code 0010.
    """
    if dword_count is None:
        dword_count = 1 if status == CPL_SC else 0
    if byte_count is None:
        byte_count = 4 * dword_count if status == CPL_SC else 4
    if error_code is None:
        error_code = EC_NORMAL if status == CPL_SC else EC_BAD_STATUS
    v = lower_address & 0xFFF
    v |= (error_code & 0xF) << 12
    v |= (byte_count & 0x1FFF) << 16
    v |= (locked & 1) << 29
    v |= (request_completed & 1) << 30
    v |= (dword_count & 0x7FF) << 32
    v |= (status & 0x7) << 43
    v |= (poisoned & 1) << 46
    v |= (requester_id & 0xFFFF) << 48
    v |= (tag & 0xFF) << 64
    v |= (completer_id & 0xFFFF) << 72
    v |= (tc & 0x7) << 89
    v |= (attr & 0x7) << 92
    return v


def decode_rc_desc(v):
    """PG213 Table 65."""
    return {
        "lower_address": v & 0xFFF,
        "error_code": (v >> 12) & 0xF,
        "byte_count": (v >> 16) & 0x1FFF,
        "locked": (v >> 29) & 1,
        "request_completed": (v >> 30) & 1,
        "dword_count": (v >> 32) & 0x7FF,
        "status": (v >> 43) & 0x7,
        "poisoned": (v >> 46) & 1,
        "requester_id": (v >> 48) & 0xFFFF,
        "tag": (v >> 64) & 0xFF,
        "completer_id": (v >> 72) & 0xFFFF,
        "tc": (v >> 89) & 0x7,
        "attr": (v >> 92) & 0x7,
    }


def rc_beats(desc, payload=()):
    """RC descriptor + payload -> [(tdata, tkeep, tlast), ...].

    Beat 0 is the 3-Dword descriptor in Dwords 0..2 with the FIRST payload Dword
    in Dword 3; later beats are payload, offset by one Dword
    (pcie_rq_rc_pkg.sv:109-115).  A descriptor-only packet is a single beat with
    tkeep = 0b0111.
    """
    payload = list(payload)
    dwords = [desc & 0xFFFFFFFF, (desc >> 32) & 0xFFFFFFFF,
              (desc >> 64) & 0xFFFFFFFF] + payload
    beats = []
    for base in range(0, len(dwords), 4):
        chunk = dwords[base:base + 4]
        tdata = 0
        keep = 0
        for index, word in enumerate(chunk):
            tdata |= (word & 0xFFFFFFFF) << (32 * index)
            keep |= 1 << index
        beats.append((tdata, keep, 1 if base + 4 >= len(dwords) else 0))
    return beats


def packet_dwords(beats):
    """[(tdata, tkeep, tlast), ...] -> flat Dword list."""
    words = []
    for tdata, tkeep, _last in beats:
        for dword in range(4):
            if (tkeep >> dword) & 1:
                words.append((tdata >> (32 * dword)) & 0xFFFFFFFF)
    return words


def split_packet(beats):
    """(96-bit descriptor, [payload Dwords])."""
    words = packet_dwords(beats)
    assert len(words) >= 3, f"RC packet shorter than a descriptor: {words}"
    return words[0] | (words[1] << 32) | (words[2] << 64), words[3:]


# ---------------------------------------------------------------------------
# On-wire TLP goldens -- integration bench only
# ---------------------------------------------------------------------------
def cfg_wire_dw2(bus, dev, fn, reg_num, ext_reg=0):
    """The Configuration Request's third header Dword, as emitted.

    {Bus[31:24], Device[23:19], Function[18:16], Reserved[15:12],
     Ext Reg[11:8], Register[7:2], R[1:0]} -- PCIe Base 2.1 Figure 2-18 p.80,
    built by tlp_generator.sv:81-82.  The BDF comes from the RQ descriptor's
    Completer ID field, NOT from the address.
    """
    return (((bus & 0xFF) << 24) | ((dev & 0x1F) << 19) | ((fn & 0x7) << 16)
            | ((ext_reg & 0xF) << 8) | ((reg_num & 0x3F) << 2))


def cfg_wire_dw0(write, length_dw=1, tc=0, attr=0):
    """Configuration Request DW0 as tlp_generator assembles it (:60-73).

    Base 2.1 SS2.2.7 p.79 fixes Length to 1 and TC/Attr/AT to zero for every
    Configuration Request; the fmt bit is the only thing read vs write changes.
    """
    fmt = FMT_3DW_DATA if write else FMT_3DW_NO_DATA
    enc = length_dw & 0x3FF
    v = (fmt << 5) | TYPE_CFG0
    v |= (attr & 0x1) << 10
    v |= (tc & 0x7) << 12
    v |= ((attr >> 1) & 0x3) << 20
    v |= ((enc >> 8) & 0x3) << 16
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def cfg_wire_dw1(requester_id, tag, first_be, last_be=0):
    """{Requester ID[31:16], Tag[15:8], Last DW BE[7:4], 1st DW BE[3:0]}.

    tlp_generator.sv:80.  Base 2.1 SS2.2.7 p.79: Last DW BE must be 0000b.
    """
    return (((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8)
            | ((last_be & 0xF) << 4) | (first_be & 0xF))


def dw0_length(dw0):
    """Recover length_dw from a TX DW0 (inverse of tlp_generator.sv:60-73)."""
    enc = ((dw0 >> 24) & 0xFF) | (((dw0 >> 16) & 0x3) << 8)
    return 1024 if enc == 0 else enc


def cpl_dw0(has_data, length_dw, tc=0, attr=0):
    """CPL DW0 as the parser reads it back (tlp_parser.sv:145-147, 150-155)."""
    fmt = FMT_3DW_DATA if has_data else FMT_3DW_NO_DATA
    enc = length_dw & 0x3FF
    v = (fmt << 5) | TYPE_CPL
    v |= (attr & 0x1) << 10
    v |= (tc & 0x7) << 12
    v |= ((attr >> 1) & 0x3) << 20
    v |= ((enc >> 8) & 0x3) << 16
    v |= (enc & 0xFF) << 24
    return v & 0xFFFFFFFF


def cpl_dw1(completer_id, status, byte_count, bcm=0):
    """{Completer ID[31:16], Status[15:13], BCM[12], Byte Count[11:0]}."""
    return (((completer_id & 0xFFFF) << 16) | ((status & 0x7) << 13)
            | ((bcm & 1) << 12) | (byte_count & 0xFFF))


def cpl_dw2(requester_id, tag, lower_address=0):
    """{Requester ID[31:16], Tag[15:8], R[7], Lower Address[6:0]}."""
    return (((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8)
            | (lower_address & 0x7F))


# ===========================================================================
# SS THE SOCKET MODEL (Commit 2b-2)
#
# Plays pcie_rq_rc_top's user-facing socket for a standalone target.  This is
# bench code that behaves like RTL, which makes it exactly as capable of being
# wrong as RTL -- and its failure mode is worse, because a socket model that is
# too POLITE makes a broken DUT look correct.
#
# !! IT ASSERTS ITS OWN PHYSICAL ORDERING RATHER THAN BEING TRUSTED TO PRESERVE
# IT.  Commit 2b-1's bring-up lost two runs to this class of bug, both the model
# being too AGGRESSIVE rather than too polite: it delivered completions, and
# fired timeout strobes, before it had strobed the tag.  Neither ordering is
# physically possible -- tlp_request_tracker allocates the tag, which is what
# raises allocated_tag_valid_o, BEFORE the request TLP is generated and
# transmitted, so any response is at minimum a link round trip later.  The three
# invariants are now checked in the model:
#
#   1. a completion may not be delivered for a transaction whose tag has not
#      been strobed;
#   2. a timeout strobe may not fire for an allocated tag that has not been
#      strobed;
#   3. the tag strobe follows command accept by >= 1 cycle -- the surface
#      mutation SM-1 attacks.
#
# A violated invariant raises AssertionError, which fails the ONE test that
# tripped it.  That is the Python equivalent of the $warning-never-$error rule:
# it must not take down the shared multi-test process.
#
# NOTE ON DUPLICATION: test_pcie_enum_txn.py carries an earlier, module-local
# copy of this class without the invariants.  It is left alone deliberately --
# the 2b-2 brief forbids touching an existing testbench, and rewriting a green
# suite to share code is not worth perturbing a baseline for.  Migrate it the
# next time that file is opened for a real reason.
# ===========================================================================
import cocotb                                          # noqa: E402
from cocotb.triggers import ReadOnly, RisingEdge       # noqa: E402


class SocketRequest:
    """One RQ packet the DUT drove, plus the tag the socket gave it."""

    def __init__(self, beats, tag, accept_cycle):
        self.beats = beats
        self.tag = tag
        self.accept_cycle = accept_cycle
        self.desc = beats[0][0] & ((1 << 128) - 1)
        self.tkeep = beats[0][1]
        self.tuser = beats[0][3]
        self.payload = [b[0] & 0xFFFFFFFF for b in beats[1:]]
        self.write = len(beats) > 1

    def __repr__(self):
        kind = "CfgWr0" if self.write else "CfgRd0"
        return (f"{kind}(tag={self.tag:#04x}, reg={(self.desc >> 2) & 0x3F:#04x}, "
                f"desc=0x{self.desc:032X})")


class Socket:
    """pcie_rq_rc_top's socket, played in Python.  See the block comment above."""

    def __init__(self, dut, tag_delay=2, first_tag=0x5A):
        assert tag_delay >= 1, (
            "INVARIANT 3: tag_delay must be >= 1. The core cannot present the "
            "tag in the cycle the descriptor is accepted -- it allocates in "
            "REQ_TAG a cycle or more later (tlp_requester.sv:211, 215-218), "
            "which is why the socket pairs the tag with its own strobe.")
        self.dut = dut
        self.tag_delay = tag_delay
        self.requests = []
        self.tags = []
        self.strobed = {}          # tag -> cycle the strobe was driven
        self.cycle = 0
        self._next_tag = first_tag
        self._stall_left = 0

    def start(self):
        cocotb.start_soon(self._cycle_counter())
        cocotb.start_soon(self._rq())

    def stall_beats(self, cycles):
        """Hold s_axis_rq_tready low for `cycles` cycles, starting now."""
        self._stall_left = cycles

    async def _cycle_counter(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            self.cycle += 1

    async def wait_for(self, count, cycles=6000):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if len(self.requests) >= count:
                return
        raise AssertionError(
            f"expected {count} RQ packets, saw {len(self.requests)}: {self.requests}")

    async def _rq(self):
        d = self.dut
        beats = []
        while True:
            await RisingEdge(d.clk_i)
            if int(d.rst_i.value):
                d.s_axis_rq_tready_i.value = 1
                beats = []
                continue
            ready = 0 if self._stall_left > 0 else 1
            if self._stall_left > 0:
                self._stall_left -= 1
            d.s_axis_rq_tready_i.value = ready
            await ReadOnly()
            if ready and int(d.s_axis_rq_tvalid_o.value):
                beats.append((int(d.s_axis_rq_tdata_o.value),
                              int(d.s_axis_rq_tkeep_o.value),
                              int(d.s_axis_rq_tlast_o.value),
                              int(d.s_axis_rq_tuser_o.value)))
                if len(beats) == 1:
                    self._accept_cycle = self.cycle
                    self._arm_tag()
                if beats[-1][2]:
                    self.requests.append(
                        SocketRequest(beats, self.tags[-1], self._accept_cycle))
                    beats = []

    def _arm_tag(self):
        tag = self._next_tag
        self._next_tag = (self._next_tag + 1) & 0xFF
        self.tags.append(tag)
        cocotb.start_soon(self._strobe_tag(tag, self.cycle))

    async def _strobe_tag(self, tag, accept_cycle):
        d = self.dut
        for _ in range(self.tag_delay):
            await RisingEdge(d.clk_i)
        # INVARIANT 3, checked rather than assumed.
        assert self.cycle > accept_cycle, (
            f"INVARIANT 3 violated: tag {tag:#04x} strobed in the same cycle "
            f"the descriptor was accepted ({accept_cycle}). The real core "
            "cannot do this (pcie_rq_rc_top.sv:51-60).")
        d.pcie_rq_tag_i.value = tag
        d.pcie_rq_tag_vld_i.value = 1
        await RisingEdge(d.clk_i)
        d.pcie_rq_tag_vld_i.value = 0
        self.strobed[tag] = self.cycle

    async def _await_strobe(self, tag, cycles=400):
        """Block until this request's tag strobe has actually been driven.

        ORDERING CONSTRAINT, not a convenience -- see INVARIANT 1 above.
        """
        for _ in range(cycles):
            if tag in self.strobed:
                return
            await RisingEdge(self.dut.clk_i)
        raise AssertionError(
            f"INVARIANT 1: tag {tag:#04x} was never strobed, so no completion "
            "for it can legally be delivered. The socket model is broken, not "
            "the DUT.")

    async def complete(self, req=None, tag=None, status=CPL_SC, data=None,
                       request_completed=1, dword_count=None, payload=None,
                       byte_count=None, error_code=None):
        """Deliver one completion on the RC stream."""
        if req is not None:
            await self._await_strobe(req.tag)          # INVARIANT 1
        if tag is None:
            tag = req.tag
        is_read = (req is not None) and (not req.write)
        has_data = is_read and status == CPL_SC
        if payload is None:
            payload = [0xD0000000 | tag if data is None else data] if has_data else []
        if dword_count is None:
            dword_count = len(payload)
        desc = encode_rc_desc(
            tag=tag, status=status, dword_count=dword_count,
            request_completed=request_completed, byte_count=byte_count,
            error_code=error_code)
        await self._drive_rc(rc_beats(desc, payload))

    async def _drive_rc(self, beats):
        d = self.dut
        for tdata, tkeep, tlast in beats:
            d.m_axis_rc_tdata_i.value = tdata
            d.m_axis_rc_tkeep_i.value = tkeep
            d.m_axis_rc_tlast_i.value = tlast
            d.m_axis_rc_tvalid_i.value = 1
            # The DUT ties tready high, but honour it anyway: a socket that
            # ignored tready could not detect a DUT that started lowering it.
            for _ in range(4000):
                await ReadOnly()
                fired = int(d.m_axis_rc_tready_o.value) == 1
                await RisingEdge(d.clk_i)
                if fired:
                    break
            else:
                raise AssertionError("m_axis_rc_tready_o never asserted")
        d.m_axis_rc_tvalid_i.value = 0
        d.m_axis_rc_tlast_i.value = 0

    async def fire_timeout(self, tag):
        """One-cycle cpl_timeout_valid_o strobe naming `tag`.

        INVARIANT 2: the tracker cannot time out a tag it has not allocated, so
        a strobe for an allocated tag waits for that tag's strobe first.  A tag
        the socket never handed out fires immediately -- that is deliberate
        stimulus, not an ordering violation.
        """
        d = self.dut
        if tag in self.tags:
            await self._await_strobe(tag)
        d.cpl_timeout_tag_i.value = tag
        d.cpl_timeout_valid_i.value = 1
        await RisingEdge(d.clk_i)
        d.cpl_timeout_valid_i.value = 0
