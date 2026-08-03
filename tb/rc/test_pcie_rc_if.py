"""Commit 2a-ii -- standalone unit tests for pcie_rc_if (U1..U11).

No Transaction Layer in the loop.  That is deliberate and is the reason this
target exists alongside verilate_rc_if_tlp: the two bugs this module is built to
prevent both live in the CYCLE RELATIONSHIP between tlp_layer's two completion
surfaces, and only a bench that owns both surfaces can place them exactly.

  * the header is COMBINATIONAL  (tlp_layer.sv:219, a direct assign)
  * the tracker result is REGISTERED, one cycle later
    (tlp_request_tracker.sv:123, 137-142)

TlModel below reproduces that offset faithfully: it offers a result starting the
cycle AFTER the header it belongs to was accepted, and it offers payload from
the same cycle (tlp_layer.sv:265-266 sets route_completion_r on the header
handshake).  U10 then puts a second header's handshake in the very cycle the
first result is captured, which is the mis-pairing window.

SPEC-GOLDEN DISCIPLINE.  golden_desc() below is written from PG213 v1.3 Table 65
directly, MSB field by MSB field, and is never read back from the DUT.  It shares
no code with pcie_rq_rc_pkg::rc_descriptor_t, so agreement means something.

RTL cited (read, not assumed):
  RC descriptor struct ............. src/rc/pcie_rq_rc_pkg.sv rc_descriptor_t
  header/result alignment .......... src/rc/pcie_rc_if.sv (hdr_r capture)
  result handshake, not a pulse .... src/tlp/tlp_request_tracker.sv:77, 110
  result_last = last CPL of the
    REQUEST, not last beat ......... src/tlp/tlp_request_tracker.sv:140-142
  tracker filters bad completions .. src/tlp/tlp_request_tracker.sv:127-135
  Lower Address is only [6:0] ...... src/tlp/tlp_parser.sv:188
  context echo carries addr[11:0]
    plus the byte-address flag ..... src/rc/pcie_rq_if.sv command_context_o
  descriptor/payload packing ....... src/rc/pcie_axis_dw_upsize.sv
"""

import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_NS = 4

# tlp_pkg::tlp_fmt_e / tlp_type_e (tlp_pkg.sv:8-27)
FMT_3DW_NO_DATA = 0b000
FMT_3DW_DATA = 0b010
TYPE_CPL = 0b01010

# tlp_pkg::tlp_cpl_status_e (tlp_pkg.sv:36-41) == PG213 Completion Status
CPL_SC = 0b000
CPL_UR = 0b001
CPL_CRS = 0b010
CPL_CA = 0b100

# pcie_rq_rc_pkg::rc_desc_error_e -- PG213 Table 65 Error Code
EC_NORMAL = 0b0000
EC_POISONED = 0b0001
EC_BAD_STATUS = 0b0010
EC_BAD_LENGTH = 0b0011      # unreachable through tlp_layer; see KNOWN_GAPS

# pcie_rq_rc_pkg::rc_error_e -- the wrapper's payload-stream error surface
RC_ERR_NONE = 0
RC_ERR_EARLY_LAST = 1
RC_ERR_MISSING_LAST = 2
RC_ERR_ORPHAN_DATA = 3

# tlp_pkg::tlp_error_e members used here (tlp_pkg.sv:58-73)
TLP_ERR_NONE = 0
TLP_ERR_UNEXPECTED_COMPLETION = 10


# --------------------------------------------------------------------------
# Spec goldens -- PG213 v1.3 Fig 56 / Table 65, written from the table
# --------------------------------------------------------------------------
def golden_desc(lower_address=0, error_code=EC_NORMAL, byte_count=0,
                locked=0, request_completed=0, dword_count=0, status=CPL_SC,
                poisoned=0, requester_id=0, tag=0, completer_id=0, tc=0,
                attr=0):
    """The 96-bit RC descriptor, field by field, LSB field first.

    Reserved bits 31, 47, 88 and 95 are left at 0 by never being written.
    """
    v = lower_address & 0xFFF                       # [11:0]
    v |= (error_code & 0xF) << 12                   # [15:12]
    v |= (byte_count & 0x1FFF) << 16                # [28:16]
    v |= (locked & 1) << 29                         # [29]
    v |= (request_completed & 1) << 30              # [30]
    v |= (dword_count & 0x7FF) << 32                # [42:32]
    v |= (status & 0x7) << 43                       # [45:43]
    v |= (poisoned & 1) << 46                       # [46]
    v |= (requester_id & 0xFFFF) << 48              # [63:48]
    v |= (tag & 0xFF) << 64                         # [71:64]
    v |= (completer_id & 0xFFFF) << 72              # [87:72]
    v |= (tc & 0x7) << 89                           # [91:89]
    v |= (attr & 0x7) << 92                         # [94:92]
    return v


def decode_desc(v):
    """Inverse of golden_desc, for readable per-field assertions."""
    return {
        "lower_address": v & 0xFFF,
        "error_code": (v >> 12) & 0xF,
        "byte_count": (v >> 16) & 0x1FFF,
        "locked": (v >> 29) & 1,
        "request_completed": (v >> 30) & 1,
        "rsvd31": (v >> 31) & 1,
        "dword_count": (v >> 32) & 0x7FF,
        "status": (v >> 43) & 0x7,
        "poisoned": (v >> 46) & 1,
        "rsvd47": (v >> 47) & 1,
        "requester_id": (v >> 48) & 0xFFFF,
        "tag": (v >> 64) & 0xFF,
        "completer_id": (v >> 72) & 0xFFFF,
        "rsvd88": (v >> 88) & 1,
        "tc": (v >> 89) & 0x7,
        "attr": (v >> 92) & 0x7,
        "rsvd95": (v >> 95) & 1,
    }


def spec_error_code(status, poisoned):
    """PG213 Table 65 Error Code, as pcie_rc_if.sv documents its priority."""
    if status != CPL_SC:
        return EC_BAD_STATUS
    if poisoned:
        return EC_POISONED
    return EC_NORMAL


def ctx(addr_low12=0, mem_read=False):
    """The command_context_i -> result_context_o echo pcie_rq_if loads.

    [11:0] the request's address[11:0]; [12] "these are byte-address bits",
    set for Memory Reads only (pcie_rq_if.sv command_context_o).
    """
    return (addr_low12 & 0xFFF) | ((1 if mem_read else 0) << 12)


# --------------------------------------------------------------------------
# Completion description -- what the bench hands to the TL model
# --------------------------------------------------------------------------
class Cpl:
    """One received completion: its parsed header, its tracker result, payload.

    result is None for a completion the tracker rejected (no matching tag, or a
    byte-count overrun): the header and payload still arrive, but no result
    follows and no RC packet may be built.
    """

    def __init__(self, tag=0, status=CPL_SC, byte_count=4, lower_address=0,
                 payload=None, requester_id=0x1234, completer_id=0x0113,
                 tc=0, attr=0, poisoned=0, result_last=1, context=0,
                 result=True, length_dw=None, data_last_at=None):
        self.tag = tag
        self.status = status
        self.byte_count = byte_count
        self.lower_address = lower_address
        self.payload = list(payload) if payload else []
        self.requester_id = requester_id
        self.completer_id = completer_id
        self.tc = tc
        self.attr = attr
        self.poisoned = poisoned
        self.result_last = result_last
        self.context = context
        self.has_result = result
        # length_dw normally follows the payload; overridable so a bench can
        # drive the header/payload disagreement the wrapper must survive.
        self.length_dw = len(self.payload) if length_dw is None else length_dw
        # Index of the payload beat carrying tlast; defaults to the real end.
        self.data_last_at = (len(self.payload) - 1 if data_last_at is None
                             else data_last_at)

    @property
    def has_data(self):
        return len(self.payload) > 0

    def expected_desc(self):
        """The descriptor a conformant pcie_rc_if must emit for this CPL."""
        low_high = (self.context >> 7) & 0x1F if (self.context >> 12) & 1 else 0
        return golden_desc(
            lower_address=(low_high << 7) | (self.lower_address & 0x7F),
            error_code=spec_error_code(self.status, self.poisoned),
            byte_count=self.byte_count,
            locked=0,
            request_completed=self.result_last,
            dword_count=self.length_dw if self.has_data else 0,
            status=self.status,
            poisoned=self.poisoned,
            requester_id=self.requester_id,
            tag=self.tag,
            completer_id=self.completer_id,
            tc=self.tc,
            attr=self.attr,
        )


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------
class TlModel:
    """Plays tlp_layer's received-completion surface, offset included.

    One task owns the header and result streams together, because the offset
    between them is the property under test and two independent tasks would
    make it a scheduling accident.  On the cycle a header is accepted, its
    result is armed for the FOLLOWING cycle -- exactly
    tlp_request_tracker.sv:123/137, where result_valid_r is a flop set by the
    completion handshake.
    """

    def __init__(self, dut):
        self.dut = dut
        self.pending = deque()      # Cpl objects yet to be offered
        self.pay_q = deque()        # (data, keep, last) beats
        self.pay_outstanding = 0    # queued payload beats not yet accepted
        self.packets = []           # completed RC packets from the monitor
        self.beats = []             # raw (tdata, tkeep, tlast) of the current one
        self.errors = []            # (rc_error_code_o) at each protocol error
        self.unexpected = []        # completion_error_code at each unexpected
        self._tasks = []

    # ---- driving ---------------------------------------------------------
    # AXI-Stream lets a source change the payload however it likes once a beat
    # has been accepted; nothing obliges it to park the old values.  So when a
    # stream is idle this model drives POISON rather than leaving the last
    # completion sitting on the wires.  That is what makes U4 a capture proof
    # instead of a coincidence: a DUT that keeps reading its inputs after the
    # handshake, rather than registering them, builds its descriptor out of
    # this.  (The real tracker happens to hold its result registers steady, so
    # a bench that mirrored it exactly would let a passthrough design through.)
    POISON_STATUS = 0b111        # not a legal tlp_cpl_status_e
    POISON_ID = 0xDEAD
    POISON_TAG = 0xEE

    def _apply_header(self, cpl):
        d = self.dut
        d.received_completion_valid_i.value = 0 if cpl is None else 1
        if cpl is None:
            d.hdr_fmt_i.value = FMT_3DW_DATA
            d.hdr_type_i.value = TYPE_CPL
            d.hdr_tc_i.value = 0x7
            d.hdr_attr_i.value = 0x7
            d.hdr_poisoned_i.value = 1
            d.hdr_length_dw_i.value = 0x7FF
            d.hdr_requester_id_i.value = self.POISON_ID
            d.hdr_completer_id_i.value = self.POISON_ID
            d.hdr_tag_i.value = self.POISON_TAG
            d.hdr_completion_status_i.value = self.POISON_STATUS
            d.hdr_byte_count_i.value = 0x1FFF
            d.hdr_lower_address_i.value = 0x7F
            return
        d.hdr_fmt_i.value = FMT_3DW_DATA if cpl.has_data else FMT_3DW_NO_DATA
        d.hdr_type_i.value = TYPE_CPL
        d.hdr_tc_i.value = cpl.tc
        d.hdr_attr_i.value = cpl.attr
        d.hdr_poisoned_i.value = cpl.poisoned
        d.hdr_length_dw_i.value = cpl.length_dw if cpl.has_data else 0
        d.hdr_requester_id_i.value = cpl.requester_id
        d.hdr_completer_id_i.value = cpl.completer_id
        d.hdr_tag_i.value = cpl.tag
        d.hdr_completion_status_i.value = cpl.status
        d.hdr_byte_count_i.value = cpl.byte_count
        d.hdr_lower_address_i.value = cpl.lower_address & 0x7F

    def _apply_result(self, cpl):
        d = self.dut
        d.result_valid_i.value = 0 if cpl is None else 1
        if cpl is None:
            d.result_context_i.value = 0x1FFF      # [12] set, [11:0] all ones
            d.result_status_i.value = self.POISON_STATUS
            d.result_last_i.value = 1
            return
        d.result_context_i.value = cpl.context
        d.result_status_i.value = cpl.status
        d.result_last_i.value = cpl.result_last

    async def _completion_driver(self):
        d = self.dut
        hdr = None
        res = None
        res_next = None
        unexpected = None
        while True:
            # tlp_parser replays a whole TLP -- header, then payload -- before
            # it presents the next one, so a header can never overtake the
            # previous completion's payload.  Modelled, not assumed: without it
            # the bench would queue two completions' payloads together and blame
            # the DUT for interleaving them.
            if hdr is None and self.pending and self.pay_outstanding == 0:
                hdr = self.pending.popleft()
            self._apply_header(hdr)
            if res is None:
                res = res_next
                res_next = None
            self._apply_result(res)
            # The tracker's rejection pulse also lands one cycle after the
            # header it rejects (tlp_request_tracker.sv:125-126).
            d.unexpected_completion_i.value = 0 if unexpected is None else 1
            d.completion_error_code_i.value = (
                TLP_ERR_NONE if unexpected is None else TLP_ERR_UNEXPECTED_COMPLETION)
            unexpected = None

            await ReadOnly()
            hdr_fire = hdr is not None and int(d.received_completion_ready_o.value)
            res_fire = res is not None and int(d.result_ready_o.value)
            await RisingEdge(d.clk_i)

            if hdr_fire:
                for index, word in enumerate(hdr.payload):
                    last = index == hdr.data_last_at
                    self.pay_q.append((word, 0xF, last))
                    self.pay_outstanding += 1
                if hdr.has_result:
                    res_next = hdr
                else:
                    unexpected = hdr
                hdr = None
            if res_fire:
                res = None

    async def _payload_driver(self):
        d = self.dut
        cur = None
        while True:
            if cur is None and self.pay_q:
                cur = self.pay_q.popleft()
            d.received_completion_data_valid_i.value = 0 if cur is None else 1
            if cur is not None:
                d.received_completion_data_i.value = cur[0]
                d.received_completion_keep_i.value = cur[1]
                d.received_completion_data_last_i.value = 1 if cur[2] else 0
            await ReadOnly()
            fired = cur is not None and int(d.received_completion_data_ready_o.value)
            await RisingEdge(d.clk_i)
            if fired:
                cur = None
                self.pay_outstanding -= 1

    # ---- monitoring ------------------------------------------------------
    async def _monitor(self):
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if int(d.rst_i.value):
                continue
            if int(d.m_axis_rc_tvalid.value) and int(d.m_axis_rc_tready.value):
                self.beats.append((int(d.m_axis_rc_tdata.value),
                                   int(d.m_axis_rc_tkeep.value),
                                   int(d.m_axis_rc_tlast.value)))
                if self.beats[-1][2]:
                    self.packets.append(self.beats)
                    self.beats = []
            if int(d.rc_protocol_error_o.value):
                self.errors.append(int(d.rc_error_code_o.value))
            if int(d.rc_unexpected_completion_o.value):
                self.unexpected.append(int(d.rc_completion_error_code_o.value))

    def start(self):
        self._tasks = [
            cocotb.start_soon(self._completion_driver()),
            cocotb.start_soon(self._payload_driver()),
            cocotb.start_soon(self._monitor()),
        ]

    def stop(self):
        for task in self._tasks:
            task.kill()
        self._tasks = []

    # ---- helpers ---------------------------------------------------------
    def send(self, *cpls):
        self.pending.extend(cpls)

    def clear(self):
        self.packets.clear()
        self.beats = []
        self.errors.clear()
        self.unexpected.clear()

    async def wait_packets(self, count, cycles=4000):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)
            if len(self.packets) >= count:
                return
        raise AssertionError(
            f"expected {count} RC packets, saw {len(self.packets)} "
            f"(pending={len(self.pending)}, payload={len(self.pay_q)})")

    async def idle(self, cycles=40):
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_i)


def packet_dwords(beats):
    """Flatten a packet's beats into Dwords using the DW-granular tkeep."""
    words = []
    for tdata, tkeep, _last in beats:
        for dword in range(4):
            if (tkeep >> dword) & 1:
                words.append((tdata >> (32 * dword)) & 0xFFFFFFFF)
    return words


def split_packet(beats):
    """(descriptor, payload Dwords).  The descriptor is the first 3 Dwords."""
    words = packet_dwords(beats)
    assert len(words) >= 3, f"RC packet shorter than a descriptor: {words}"
    desc = words[0] | (words[1] << 32) | (words[2] << 64)
    return desc, words[3:]


async def reset(dut, start_clock=True):
    # One clock per test.  A second start() on the same signal inside a test
    # would drive it from two tasks.
    if start_clock:
        cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    for handle in dut:
        if handle._name.endswith("_i") and handle._name not in {"clk_i", "rst_i"}:
            try:
                handle.value = 0
            except (AttributeError, ValueError):
                pass
    dut.m_axis_rc_tready.value = 1
    dut.rst_i.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


async def tready_pattern(dut, rng, low_prob=0.5):
    """Random m_axis_rc_tready backpressure, forever."""
    while True:
        dut.m_axis_rc_tready.value = 0 if rng.random() < low_prob else 1
        await RisingEdge(dut.clk_i)


def check_desc(got, expected, label):
    if got == expected:
        return
    g, e = decode_desc(got), decode_desc(expected)
    diff = {k: (hex(g[k]), hex(e[k])) for k in g if g[k] != e[k]}
    raise AssertionError(f"{label}: descriptor {got:#026x} != {expected:#026x}; "
                         f"fields (got, want) {diff}")


# ==========================================================================
# U1 -- elaboration and quiescence
# ==========================================================================
@cocotb.test()
async def u1_elaboration_and_idle(dut):
    """The module elaborates, resets clean, and emits nothing unprompted."""
    await reset(dut)
    tl = TlModel(dut)
    tl.start()
    await tl.idle(40)
    assert tl.packets == [], f"RC packets appeared with no completion: {tl.packets}"
    assert int(dut.m_axis_rc_tvalid.value) == 0, "m_axis_rc_tvalid high while idle"
    assert tl.errors == [], f"protocol errors while idle: {tl.errors}"
    # Both readys are the S_IDLE interlock; both must be open when idle or the
    # first completion can never be accepted.
    assert int(dut.received_completion_ready_o.value) == 1
    assert int(dut.result_ready_o.value) == 1


# ==========================================================================
# U2 -- spec CplD, SC, 1 Dword
# ==========================================================================
@cocotb.test()
async def u2_single_dword_cpld(dut):
    """Every descriptor bit against a hand-derived golden; beat-0 layout."""
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    cpl = Cpl(tag=0x27, status=CPL_SC, byte_count=4, lower_address=0x04,
              payload=[0xDEADBEEF], requester_id=0x1234, completer_id=0x0113,
              tc=0x5, attr=0x3, result_last=1, context=ctx(0x104, mem_read=True))
    tl.send(cpl)
    await tl.wait_packets(1)

    desc, payload = split_packet(tl.packets[0])

    # Hand-derived, field by field, from PG213 Table 65 -- not from the DUT.
    want = golden_desc(
        lower_address=(0x104 >> 7 << 7) | 0x04,   # [11:7] from the echo, [6:0] from the CPL
        error_code=EC_NORMAL,                     # SC and not poisoned
        byte_count=4,
        request_completed=1,                      # result_last_i
        dword_count=1,                            # payload Dwords in this packet
        status=CPL_SC,
        requester_id=0x1234,
        tag=0x27,
        completer_id=0x0113,
        tc=0x5,
        attr=0x3,
    )
    check_desc(desc, want, "U2")
    assert desc == cpl.expected_desc(), "U2: Cpl.expected_desc disagrees with the literal golden"
    assert payload == [0xDEADBEEF], f"U2 payload {payload}"

    fields = decode_desc(desc)
    assert fields["rsvd31"] == 0 and fields["rsvd47"] == 0
    assert fields["rsvd88"] == 0 and fields["rsvd95"] == 0, "reserved bit set"
    assert fields["locked"] == 0, "Locked Read Completion must be 0"

    # Beat 0 is {payload DW0, desc DW2, desc DW1, desc DW0} -- the packing the
    # gearbox produces by plain concatenation, with no rotation logic anywhere.
    assert len(tl.packets[0]) == 1, f"1-DW CplD must be a single beat, got {len(tl.packets[0])}"
    tdata, tkeep, tlast = tl.packets[0][0]
    exp_beat = ((desc & 0xFFFFFFFF)
                | (((desc >> 32) & 0xFFFFFFFF) << 32)
                | (((desc >> 64) & 0xFFFFFFFF) << 64)
                | (0xDEADBEEF << 96))
    assert tdata == exp_beat, f"beat 0 {tdata:#034x} != {exp_beat:#034x}"
    assert tkeep == 0xF, f"beat 0 tkeep {tkeep:#x} != 0xF (4 Dwords valid)"
    assert tlast == 1, "beat 0 must carry tlast"


# ==========================================================================
# U3 -- Cpl with no data (a Configuration-write completion)
# ==========================================================================
@cocotb.test()
async def u3_completion_no_data(dut):
    """Dword Count 0, descriptor-only packet, tlast on beat 0."""
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    cpl = Cpl(tag=0x03, status=CPL_SC, byte_count=4, lower_address=0,
              payload=[], result_last=1, context=ctx(0x1130010 & 0xFFF))
    tl.send(cpl)
    await tl.wait_packets(1)

    desc, payload = split_packet(tl.packets[0])
    check_desc(desc, cpl.expected_desc(), "U3")
    assert decode_desc(desc)["dword_count"] == 0, "Dword Count must be 0 for a Cpl with no data"
    assert payload == [], f"a Cpl with no data must carry no payload, got {payload}"

    assert len(tl.packets[0]) == 1, "descriptor-only packet must be one beat"
    _tdata, tkeep, tlast = tl.packets[0][0]
    assert tkeep == 0b0111, f"3 descriptor Dwords -> tkeep 0b0111, got {tkeep:#05b}"
    assert tlast == 1, "descriptor-only packet must assert tlast on beat 0"


# ==========================================================================
# U4 -- the pulse-capture proof
# ==========================================================================
@cocotb.test()
async def u4_tready_low_across_the_result(dut):
    """m_axis_rc_tready low across the whole result handshake and 8 cycles on.

    A design that passes result_* through to the descriptor instead of capturing
    it loses the completion here: by the time tready rises the tracker has moved
    on.  Nothing may be lost.
    """
    await reset(dut)
    dut.m_axis_rc_tready.value = 0
    tl = TlModel(dut)
    tl.start()

    cpl = Cpl(tag=0x11, status=CPL_SC, byte_count=8, lower_address=0x00,
              payload=[0xA0A0A0A0, 0xB1B1B1B1], result_last=1,
              context=ctx(0x280, mem_read=True))
    tl.send(cpl)

    # Hold tready low well past the result handshake.  The result is consumed
    # (result_ready_o is the S_IDLE interlock, not a function of tready), so if
    # the descriptor were not captured it would be gone by now.
    saw_result_handshake = False
    for _ in range(24):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        if int(dut.result_valid_i.value) and int(dut.result_ready_o.value):
            saw_result_handshake = True
    # The loop above ends inside the read-only phase; step past it before
    # driving anything.
    await RisingEdge(dut.clk_i)
    assert saw_result_handshake, "U4 never exercised the result handshake"
    assert tl.packets == [], "a packet escaped while tready was low"

    dut.m_axis_rc_tready.value = 1
    await tl.wait_packets(1)

    desc, payload = split_packet(tl.packets[0])
    check_desc(desc, cpl.expected_desc(), "U4")
    assert payload == [0xA0A0A0A0, 0xB1B1B1B1], f"U4 payload {payload}"


# ==========================================================================
# U5 -- UR / CA / CRS
# ==========================================================================
@cocotb.test()
async def u5_completion_status_and_error_code(dut):
    """Status carried verbatim; Error Code 0010 for every non-SC status.

    CRS especially: a device may answer early Configuration reads with CRS and
    Commit 2b has to see it, so it must not be folded into a generic error.
    """
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    cases = [(CPL_UR, 0b001), (CPL_CA, 0b100), (CPL_CRS, 0b010)]
    for index, (status, encoding) in enumerate(cases):
        assert status == encoding, "status constant disagrees with its encoding"
        tl.clear()
        # A non-SC completion terminates the request, so result_last is set --
        # tlp_request_tracker.sv:140-142 (status != TLP_CPL_SC).
        cpl = Cpl(tag=0x40 + index, status=status, byte_count=4, payload=[],
                  result_last=1, context=ctx(0))
        tl.send(cpl)
        await tl.wait_packets(1)

        desc, payload = split_packet(tl.packets[0])
        fields = decode_desc(desc)
        assert fields["status"] == status, \
            f"status {fields['status']:#05b} != {status:#05b}"
        assert fields["error_code"] == EC_BAD_STATUS, \
            f"Error Code {fields['error_code']:#06b} != 0010 for status {status:#05b}"
        assert fields["request_completed"] == 1, "a non-SC completion ends the request"
        assert payload == [], "an error completion carries no payload"
        check_desc(desc, cpl.expected_desc(), f"U5 status {status:#05b}")

    # And a poisoned SC completion is Error Code 0001, not 0010.
    tl.clear()
    poisoned = Cpl(tag=0x4F, status=CPL_SC, byte_count=4, payload=[0x0BADF00D],
                   poisoned=1, result_last=1, context=ctx(0))
    tl.send(poisoned)
    await tl.wait_packets(1)
    desc, _payload = split_packet(tl.packets[0])
    fields = decode_desc(desc)
    assert fields["error_code"] == EC_POISONED, \
        f"poisoned SC completion Error Code {fields['error_code']:#06b} != 0001"
    assert fields["poisoned"] == 1, "descriptor bit 46 must mirror the CPL's EP bit"


# ==========================================================================
# U6 -- split completion: bit 30 on the SECOND CPL only
# ==========================================================================
@cocotb.test()
async def u6_split_completion_request_completed(dut):
    """Two CPLs answering one Memory Read.

    Bit 30 is Request Completed -- last CPL OF THE REQUEST, not last beat of
    this CPL.  Commit 2b releases tags on it, so a bit 30 driven from a beat
    counter would set it on both packets and retire the tag while the second
    completion was still in flight.  Byte Count counts down across the pair.
    """
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    tag = 0x0C
    # 32-byte read split 16 + 16 at a 64-byte RCB.  Byte Count is the bytes
    # REMAINING including this CPL, so 32 then 16.
    first = Cpl(tag=tag, status=CPL_SC, byte_count=32, lower_address=0x00,
                payload=[0x1000 + i for i in range(4)], result_last=0,
                context=ctx(0x200, mem_read=True))
    second = Cpl(tag=tag, status=CPL_SC, byte_count=16, lower_address=0x10,
                 payload=[0x2000 + i for i in range(4)], result_last=1,
                 context=ctx(0x200, mem_read=True))
    tl.send(first, second)
    await tl.wait_packets(2)

    desc0, pay0 = split_packet(tl.packets[0])
    desc1, pay1 = split_packet(tl.packets[1])
    f0, f1 = decode_desc(desc0), decode_desc(desc1)

    assert f0["request_completed"] == 0, \
        "bit 30 set on the FIRST CPL of a split read -- the tag would retire early"
    assert f1["request_completed"] == 1, "bit 30 clear on the last CPL of the request"
    assert f0["byte_count"] == 32 and f1["byte_count"] == 16, \
        f"Byte Count {f0['byte_count']}/{f1['byte_count']} != 32/16"
    assert f0["dword_count"] == 4 and f1["dword_count"] == 4
    assert f0["tag"] == tag and f1["tag"] == tag
    assert pay0 == [0x1000 + i for i in range(4)], f"first CPL payload {pay0}"
    assert pay1 == [0x2000 + i for i in range(4)], f"second CPL payload {pay1}"
    check_desc(desc0, first.expected_desc(), "U6 first")
    check_desc(desc1, second.expected_desc(), "U6 second")


# ==========================================================================
# U7 -- multi-Dword payloads
# ==========================================================================
@cocotb.test()
async def u7_multi_dword_payloads(dut):
    """N in {2,3,4,5,16,17}: the one-Dword descriptor offset holds throughout."""
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    for n in (2, 3, 4, 5, 16, 17):
        tl.clear()
        payload = [(0xC0DE0000 | (n << 16) | i) for i in range(n)]
        cpl = Cpl(tag=n, status=CPL_SC, byte_count=4 * n, lower_address=0x00,
                  payload=payload, result_last=1, context=ctx(0x400, mem_read=True))
        tl.send(cpl)
        await tl.wait_packets(1)

        beats = tl.packets[0]
        desc, got = split_packet(beats)
        check_desc(desc, cpl.expected_desc(), f"U7 n={n}")
        assert decode_desc(desc)["dword_count"] == n
        assert got == payload, f"U7 n={n} payload {got} != {payload}"

        # 3 descriptor Dwords + n payload Dwords, 4 per beat, partial final beat.
        total = 3 + n
        assert len(beats) == (total + 3) // 4, \
            f"U7 n={n}: {len(beats)} beats for {total} Dwords"
        assert beats[-1][2] == 1 and all(b[2] == 0 for b in beats[:-1]), \
            f"U7 n={n}: tlast is not on the final beat only"
        tail = total % 4
        want_keep = 0xF if tail == 0 else (1 << tail) - 1
        assert beats[-1][1] == want_keep, \
            f"U7 n={n}: final tkeep {beats[-1][1]:#06b} != {want_keep:#06b}"
        for beat in beats[:-1]:
            assert beat[1] == 0xF, f"U7 n={n}: a non-final beat has partial tkeep"


# ==========================================================================
# U8 -- unexpected completion
# ==========================================================================
@cocotb.test()
async def u8_unexpected_completion_makes_no_packet(dut):
    """No matching tag -> flagged on the dedicated output, no RC packet.

    The tracker refuses to produce a result at all for such a completion
    (tlp_request_tracker.sv:124-126), so the wrapper has nothing to build a
    descriptor from -- and must not invent one.  Its payload still arrives and
    must be drained, or the RX path wedges for every completion after it.
    """
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    orphan = Cpl(tag=0x7E, status=CPL_SC, byte_count=8,
                 payload=[0xBADBAD00, 0xBADBAD01], result=False)
    good = Cpl(tag=0x01, status=CPL_SC, byte_count=4, payload=[0x600DF00D],
               result_last=1, context=ctx(0))
    tl.send(orphan, good)
    await tl.wait_packets(1)
    await tl.idle(20)

    assert len(tl.packets) == 1, \
        f"an unexpected completion fabricated an RC packet: {len(tl.packets)} packets"
    desc, payload = split_packet(tl.packets[0])
    assert decode_desc(desc)["tag"] == 0x01, "the surviving packet is not the good completion"
    assert payload == [0x600DF00D], f"good completion payload {payload}"

    assert tl.unexpected == [TLP_ERR_UNEXPECTED_COMPLETION], \
        f"unexpected completion not surfaced: {tl.unexpected}"
    assert tl.errors == [RC_ERR_ORPHAN_DATA] * 2, \
        f"orphan payload not drained-and-flagged: {tl.errors}"


# ==========================================================================
# U9 -- Lower Address
# ==========================================================================
@cocotb.test()
async def u9_lower_address(dut):
    """Config completion -> [11:0] == 0.  Memory read -> [6:0] CPL, [11:7] echo.

    PCIe defines Lower Address only for Memory Read Completions; everything
    else carries 0, which is why the echo's [12] flag exists at all.  Echoing a
    Configuration request's address bits would be inventing a Lower Address out
    of a {ExtReg, Register#, offset} Dword.
    """
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    # A Configuration read completion.  The request's context echo carries the
    # config Dword's low bits, but [12] is clear, so none of it may appear.
    config = Cpl(tag=0x02, status=CPL_SC, byte_count=4, lower_address=0x00,
                 payload=[0x8086100E], result_last=1,
                 context=ctx(0x0110, mem_read=False))
    tl.send(config)
    await tl.wait_packets(1)
    desc, _ = split_packet(tl.packets[0])
    assert decode_desc(desc)["lower_address"] == 0, \
        (f"config completion Lower Address {decode_desc(desc)['lower_address']:#05x} != 0 "
         "-- the context echo leaked into a non-Memory-Read completion")

    # A Memory Read completion at address 0x0000_0AB4.
    tl.clear()
    address = 0x0AB4
    memory = Cpl(tag=0x03, status=CPL_SC, byte_count=4, lower_address=address & 0x7F,
                 payload=[0x11223344], result_last=1,
                 context=ctx(address & 0xFFF, mem_read=True))
    tl.send(memory)
    await tl.wait_packets(1)
    desc, _ = split_packet(tl.packets[0])
    got = decode_desc(desc)["lower_address"]
    assert got & 0x7F == address & 0x7F, f"[6:0] {got & 0x7F:#04x} != {address & 0x7F:#04x}"
    assert (got >> 7) & 0x1F == (address >> 7) & 0x1F, \
        f"[11:7] {(got >> 7) & 0x1F:#04x} != {(address >> 7) & 0x1F:#04x} -- echo not used"
    assert got == address & 0xFFF, f"Lower Address {got:#05x} != {address & 0xFFF:#05x}"


# ==========================================================================
# U10 -- the mis-pairing test
# ==========================================================================
@cocotb.test()
async def u10_back_to_back_different_tags(dut):
    """Two completions, different tags, headers on consecutive cycles.

    THE test for this module.  The header is combinational and the result is
    registered a cycle later, so a design that reads the header at result time
    pairs header N+1 with result N and emits a descriptor whose Tag belongs to a
    different completion than its payload.  Nothing else in this file catches
    it: with even one idle cycle between completions the naive design looks
    correct.

    Completions with no data are used because that is the shape that puts the
    second header's handshake in the very cycle the first result is captured --
    a CplD forces payload beats in between.
    """
    await reset(dut)
    tl = TlModel(dut)
    tl.start()

    first = Cpl(tag=0xA1, status=CPL_SC, byte_count=4, payload=[],
                completer_id=0x0111, requester_id=0x1234, tc=1, attr=2,
                result_last=1, context=ctx(0))
    second = Cpl(tag=0xB2, status=CPL_SC, byte_count=4, payload=[],
                 completer_id=0x0222, requester_id=0x1234, tc=3, attr=4,
                 result_last=1, context=ctx(0))
    tl.send(first, second)
    await tl.wait_packets(2)

    desc0, _ = split_packet(tl.packets[0])
    desc1, _ = split_packet(tl.packets[1])
    assert decode_desc(desc0)["tag"] == 0xA1, \
        (f"packet 0 Tag {decode_desc(desc0)['tag']:#04x} != 0xA1 -- header/result "
         "MIS-PAIRING: the descriptor belongs to a different completion")
    assert decode_desc(desc1)["tag"] == 0xB2, \
        f"packet 1 Tag {decode_desc(desc1)['tag']:#04x} != 0xB2"
    check_desc(desc0, first.expected_desc(), "U10 first")
    check_desc(desc1, second.expected_desc(), "U10 second")

    # The same window with payload attached: here a mis-paired Tag would ship a
    # descriptor pointing at the other completion's data.
    tl.clear()
    third = Cpl(tag=0xC3, status=CPL_SC, byte_count=4, payload=[0x33333333],
                result_last=1, context=ctx(0))
    fourth = Cpl(tag=0xD4, status=CPL_SC, byte_count=4, payload=[0x44444444],
                 result_last=1, context=ctx(0))
    tl.send(third, fourth)
    await tl.wait_packets(2)
    for index, (want_tag, want_data) in enumerate(((0xC3, 0x33333333),
                                                   (0xD4, 0x44444444))):
        desc, payload = split_packet(tl.packets[index])
        assert decode_desc(desc)["tag"] == want_tag and payload == [want_data], \
            (f"packet {index}: Tag {decode_desc(desc)['tag']:#04x} with payload "
             f"{payload} -- descriptor and payload are from different completions")


# ==========================================================================
# U11 -- random backpressure equivalence
# ==========================================================================
@cocotb.test()
async def u11_random_backpressure(dut):
    """200 seeded completions, byte-identical under backpressure and without."""
    rng_spec = random.Random(0x2A11)
    stream = []
    for index in range(200):
        n = rng_spec.choice([0, 0, 1, 1, 2, 3, 4, 5, 7, 8])
        status = rng_spec.choice([CPL_SC] * 6 + [CPL_UR, CPL_CA, CPL_CRS])
        if status != CPL_SC:
            n = 0
        address = rng_spec.randrange(0, 1 << 12) & ~0x3
        mem = bool(n) and rng_spec.random() < 0.5
        stream.append(Cpl(
            tag=rng_spec.randrange(0, 256),
            status=status,
            byte_count=(4 * n) if n else 4,
            lower_address=(address & 0x7F) if mem else 0,
            payload=[rng_spec.randrange(0, 1 << 32) for _ in range(n)],
            requester_id=rng_spec.randrange(0, 1 << 16),
            completer_id=rng_spec.randrange(0, 1 << 16),
            tc=rng_spec.randrange(0, 8),
            attr=rng_spec.randrange(0, 8),
            poisoned=rng_spec.randrange(0, 2) if status == CPL_SC and n else 0,
            result_last=rng_spec.randrange(0, 2),
            context=ctx(address, mem_read=mem),
        ))

    # ---- reference run: tready always high ----
    await reset(dut)
    tl = TlModel(dut)
    tl.start()
    dut.m_axis_rc_tready.value = 1
    tl.send(*stream)
    await tl.wait_packets(len(stream), cycles=40000)
    reference = [packet_dwords(p) for p in tl.packets]

    expected = [cpl.expected_desc() for cpl in stream]
    for index, (words, want) in enumerate(zip(reference, expected)):
        desc = words[0] | (words[1] << 32) | (words[2] << 64)
        check_desc(desc, want, f"U11 reference packet {index}")
        assert words[3:] == stream[index].payload, \
            f"U11 reference packet {index} payload {words[3:]}"

    # ---- backpressured run: identical output required ----
    tl.stop()
    await reset(dut, start_clock=False)
    tl = TlModel(dut)
    tl.start()
    rng_bp = random.Random(0xBEEF)
    cocotb.start_soon(tready_pattern(dut, rng_bp, low_prob=0.6))
    tl.send(*stream)
    await tl.wait_packets(len(stream), cycles=200000)
    backpressured = [packet_dwords(p) for p in tl.packets]

    assert len(backpressured) == len(reference), \
        f"packet count {len(backpressured)} != {len(reference)} under backpressure"
    for index, (got, want) in enumerate(zip(backpressured, reference)):
        assert got == want, (f"U11 packet {index} differs under backpressure:\n"
                             f"  got  {[hex(w) for w in got]}\n"
                             f"  want {[hex(w) for w in want]}")
    assert tl.errors == [], f"U11 raised protocol errors: {set(tl.errors)}"
