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
