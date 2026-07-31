"""Commit 2b-1 -- pcie_cfg_txn standalone (E1..E13).

The DUT is the configuration transaction primitive ALONE.  Everything on the far
side of its socket is absent and the bench plays it.

! FLOW CONTROL DOES NOT APPEAR HERE.  There is no tlp_layer in this target, so
the four preconditions and the credit pools are the integration target's
subject (test_pcie_enum_txn_tlp.py).  What this target owns is the primitive's
own behaviour: descriptor construction, tag discipline, status classification,
the CRS retry loop, and every failure path.

Spec cited (read, not assumed):
  Configuration Request rules ....... PCIe Base 2.1 SS2.2.7 p.79-80
  Completion Status encodings ....... PCIe Base 2.1 SS2.2.9 p.98
  Reserved status treated as UR ..... PCIe Base 2.1 SS2.3.2 p.122
  CRS terminates the request ........ PCIe Base 2.1 SS2.3.2 IN p.113
  CRS retry loops may be bounded .... PCIe Base 2.1 SS2.3.2 p.121-122
  Non-SC completions carry no data .. PCIe Base 2.1 SS2.3.2 p.122
  Completion timeout is an error .... PCIe Base 2.1 SS2.8 p.152
  RQ descriptor field map ........... PG213 v1.3 Table 61 (:3711,:3720,:3728,:3735)
  RC descriptor / bit 30 ............ PG213 v1.3 Table 65 (:4034), bit 30 (:4049)
  Tag is not valid at accept time ... pcie_rq_rc_top.sv:51-60
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

from enum_tb_common import (
    BDF, CLK_NS,
    CFG_BE_BYTE2, CFG_BE_DWORD, CFG_BE_LOWER_HALF,
    CFG_REG_BAR0, CFG_REG_CACHE_HEADER, CFG_REG_COMMAND_STATUS,
    CFG_REG_VENDOR_DEVICE,
    CPL_CA, CPL_CRS, CPL_RESERVED, CPL_SC, CPL_UR,
    TXN_CA, TXN_CRS_EXHAUSTED, TXN_NAME, TXN_OK, TXN_TIMEOUT, TXN_UR,
    assert_rq_descriptor, encode_rc_desc, rc_beats,
)


# tb_pcie_enum_txn.sv overrides the shipped 16/64 defaults so the exhaustion
# test costs ~32 cycles instead of ~1024.
CRS_RETRY_MAX = 3
CRS_BACKOFF_CYCLES = 8

# CLK_NS / BDF now come from enum_tb_common -- identical in every enum bench.
OTHER_BDF = 0x0208    # bus 2, device 1, function 0

# The socket hands out tags starting here.  DELIBERATELY NON-ZERO: a tag-match
# assertion over an all-zero tag space proves nothing, because every comparison
# succeeds by accident.  This is the U13/V8 degenerate-value lesson, applied to
# the one signal this module correlates on.
FIRST_TAG = 0x5A


# ==========================================================================
# SS THE SOCKET MODEL
#
# This class plays pcie_rq_rc_top's user-facing socket.  It is bench code that
# behaves like RTL, which makes it exactly as capable of being wrong as RTL --
# and its failure mode is worse, because a socket model that is too POLITE makes
# a broken DUT look correct.
#
# The three politenesses that matter, all avoided here:
#
#   * The tag is NOT presented when the descriptor is accepted.  The real core
#     leaves REQ_IDLE and allocates in REQ_TAG a cycle or more later
#     (tlp_requester.sv:211, 215-218), which is why the socket pairs the tag
#     with its own strobe (pcie_rq_rc_top.sv:51-60).  tag_delay defaults to 2.
#
#   * tready is not nailed high.  `stall_beats` inserts back-pressure, and the
#     stall test drives it long enough that no cycle-count assumption survives.
#
#   * Tags are non-zero and increment, so a completion can be aimed at the wrong
#     tag and be seen to be ignored.
#
# Mutations SM-1, SM-2, SM-4 (SPEC_PREDICTIONS_ENUM.md SS7) are seeded into this
# class during verification and each must fail at least one test below.  SM-3
# (orphan-data burst omitted) is NOT expressible here -- the burst is
# rc_protocol_error_o, a pcie_rq_rc_top output the primitive deliberately does
# not consume, so it cannot cross this socket.  Its kill lives in the
# integration target.  E10 is the standalone stand-in: the socket-visible
# consequence of a late completion is a stray packet bearing a tag the
# primitive is no longer waiting for.
# ==========================================================================
class Request:
    """One RQ packet the DUT drove, plus the tag the socket gave it."""

    def __init__(self, beats, tag):
        self.beats = beats
        self.tag = tag
        self.desc = beats[0][0] & ((1 << 128) - 1)
        self.tkeep = beats[0][1]
        self.tuser = beats[0][3]
        self.payload = [b[0] & 0xFFFFFFFF for b in beats[1:]]
        self.write = len(beats) > 1

    def __repr__(self):
        kind = "CfgWr0" if self.write else "CfgRd0"
        return (f"{kind}(tag={self.tag:#04x}, desc=0x{self.desc:032X}, "
                f"payload={[hex(w) for w in self.payload]})")


class Socket:
    def __init__(self, dut, tag_delay=2, first_tag=FIRST_TAG):
        self.dut = dut
        self.tag_delay = tag_delay
        self.requests = []
        self.tags = []
        self.strobed = set()      # tags whose strobe has actually been driven
        self._next_tag = first_tag
        self._stall_left = 0

    def start(self):
        cocotb.start_soon(self._rq())

    def stall_beats(self, cycles):
        """Hold s_axis_rq_tready low for `cycles` cycles, starting now."""
        self._stall_left = cycles

    async def wait_for(self, count, cycles=4000):
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
                    # The descriptor beat is where the command reaches the
                    # Transaction Layer, so this is where a tag gets allocated.
                    self._arm_tag()
                if beats[-1][2]:
                    self.requests.append(Request(beats, self.tags[-1]))
                    beats = []

    def _arm_tag(self):
        tag = self._next_tag
        self._next_tag = (self._next_tag + 1) & 0xFF
        self.tags.append(tag)
        cocotb.start_soon(self._strobe_tag(tag))

    async def _strobe_tag(self, tag):
        d = self.dut
        for _ in range(self.tag_delay):
            await RisingEdge(d.clk_i)
        d.pcie_rq_tag_i.value = tag
        d.pcie_rq_tag_vld_i.value = 1
        await RisingEdge(d.clk_i)
        d.pcie_rq_tag_vld_i.value = 0
        self.strobed.add(tag)

    async def _await_strobe(self, tag, cycles=200):
        """Block until this request's tag strobe has actually been driven.

        ORDERING CONSTRAINT, not a convenience.  A completion cannot physically
        precede the tag strobe: tlp_request_tracker allocates the tag -- which is
        what raises allocated_tag_valid_o -- BEFORE the request TLP is generated
        and transmitted, so the completion is at minimum a link round trip
        later.  A socket model that answered before strobing would be testing an
        ordering the real core cannot produce, and would fail a correct DUT.
        """
        for _ in range(cycles):
            if tag in self.strobed:
                return
            await RisingEdge(self.dut.clk_i)
        raise AssertionError(
            f"tag {tag:#04x} was never strobed -- the socket model is broken, "
            "not the DUT")

    async def complete(self, req=None, tag=None, status=CPL_SC, data=None,
                       request_completed=1, dword_count=None, payload=None,
                       byte_count=None, error_code=None):
        """Deliver one completion on the RC stream.

        Defaults reproduce what pcie_rc_if would build: a Successful Completion
        to a config READ carries one Dword; every other status carries no data
        and sets Request Completed (Base 2.1 SS2.3.2 p.122).
        """
        if req is not None:
            await self._await_strobe(req.tag)
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
            error_code=error_code, completer_id=BDF)
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
            for _ in range(2000):
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

        Subject to the same ordering constraint as complete(): the tracker
        cannot time out a tag it has not yet allocated, so a strobe for an
        allocated tag waits for that tag's strobe first.  A tag the socket never
        handed out is fired immediately -- that is a deliberate stimulus, not an
        ordering violation.
        """
        d = self.dut
        if tag in self.tags:
            await self._await_strobe(tag)
        d.cpl_timeout_tag_i.value = tag
        d.cpl_timeout_valid_i.value = 1
        await RisingEdge(d.clk_i)
        d.cpl_timeout_valid_i.value = 0


# ==========================================================================
# Harness
# ==========================================================================
async def init(dut, tag_delay=2, first_tag=FIRST_TAG):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    dut.cmd_valid_i.value = 0
    dut.cmd_write_i.value = 0
    dut.cmd_type1_i.value = 0
    dut.cmd_bdf_i.value = 0
    dut.cmd_reg_num_i.value = 0
    dut.cmd_ext_reg_i.value = 0
    dut.cmd_first_be_i.value = 0
    dut.cmd_wdata_i.value = 0
    dut.rsp_ready_i.value = 0
    dut.s_axis_rq_tready_i.value = 1
    dut.pcie_rq_tag_i.value = 0
    dut.pcie_rq_tag_vld_i.value = 0
    dut.m_axis_rc_tdata_i.value = 0
    dut.m_axis_rc_tkeep_i.value = 0
    dut.m_axis_rc_tvalid_i.value = 0
    dut.m_axis_rc_tlast_i.value = 0
    dut.cpl_timeout_valid_i.value = 0
    dut.cpl_timeout_tag_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)
    sock = Socket(dut, tag_delay=tag_delay, first_tag=first_tag)
    sock.start()
    await RisingEdge(dut.clk_i)
    return sock


async def send_cmd(dut, write, reg_num, first_be=CFG_BE_DWORD, wdata=0,
                   bdf=BDF, ext_reg=0, limit=500, type1=False):
    dut.cmd_write_i.value = 1 if write else 0
    dut.cmd_type1_i.value = 1 if type1 else 0
    dut.cmd_bdf_i.value = bdf
    dut.cmd_reg_num_i.value = reg_num
    dut.cmd_ext_reg_i.value = ext_reg
    dut.cmd_first_be_i.value = first_be
    dut.cmd_wdata_i.value = wdata
    dut.cmd_valid_i.value = 1
    for _ in range(limit):
        await ReadOnly()
        fired = int(dut.cmd_ready_o.value) == 1
        await RisingEdge(dut.clk_i)
        if fired:
            break
    else:
        raise AssertionError("cmd_ready_o never asserted -- primitive stuck")
    dut.cmd_valid_i.value = 0


async def recv_rsp(dut, cycles=6000):
    """Wait for rsp_valid_o, sample the whole response, then consume it."""
    for _ in range(cycles):
        await ReadOnly()
        if int(dut.rsp_valid_o.value):
            got = {
                "outcome": int(dut.rsp_outcome_o.value),
                "rdata": int(dut.rsp_rdata_o.value),
                "status_raw": int(dut.rsp_status_raw_o.value),
                "crs_retries": int(dut.crs_retries_o.value),
            }
            await RisingEdge(dut.clk_i)
            dut.rsp_ready_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.rsp_ready_i.value = 0
            return got
        await RisingEdge(dut.clk_i)
    raise AssertionError("rsp_valid_o never asserted")


async def settle(dut, cycles=20):
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)


def outcome_name(value):
    return TXN_NAME.get(value, f"<unknown {value}>")


# ==========================================================================
# E1 / E2 -- the happy paths, with the descriptor asserted on the wire
# ==========================================================================
@cocotb.test()
async def e1_config_read_successful_completion(dut):
    """A CfgRd0 that gets SC: one packet out, data surfaces, one response."""
    sock = await init(dut)

    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE,
                   first_be=CFG_BE_DWORD)
    await sock.wait_for(1)
    req = sock.requests[0]

    assert not req.write, "a CfgRd0 must be a single-beat packet with no payload"
    assert req.tkeep == 0xF, f"descriptor beat tkeep {req.tkeep:#x}, expected 0xF"
    assert_rq_descriptor(req.desc, req.tuser, write=False, bdf=BDF,
                         reg_num=CFG_REG_VENDOR_DEVICE, first_be=CFG_BE_DWORD,
                         what="E1 ")
    assert req.tag == FIRST_TAG, \
        f"socket handed out tag {req.tag:#04x}, expected {FIRST_TAG:#04x}"
    assert req.tag != 0, "degenerate tag: the match assertion below would be vacuous"

    await sock.complete(req, status=CPL_SC, data=0xC0FFEE01)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_OK, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_OK"
    assert rsp["rdata"] == 0xC0FFEE01, f"read data {rsp['rdata']:#010x}"
    assert rsp["status_raw"] == CPL_SC, f"raw status {rsp['status_raw']:#05b}"
    assert rsp["crs_retries"] == 0, "no CRS was returned"

    await settle(dut)
    assert len(sock.requests) == 1, \
        f"{len(sock.requests)} packets emitted for one command: {sock.requests}"
    assert int(dut.cmd_ready_o.value) == 1, "the primitive must be ready again"


@cocotb.test()
async def e2_config_write_successful_completion(dut):
    """A CfgWr0 that gets SC.

    A configuration write is NON-POSTED: it allocates a tag and it does get a
    completion (only Memory/posted writes do not).  The completion carries no
    data, so rsp_rdata_o must stay zero rather than echoing the written value.
    """
    sock = await init(dut)

    await send_cmd(dut, write=True, reg_num=CFG_REG_COMMAND_STATUS,
                   first_be=CFG_BE_LOWER_HALF, wdata=0x00000006)
    await sock.wait_for(1)
    req = sock.requests[0]

    assert req.write, "a CfgWr0 must carry a payload beat"
    assert req.payload == [0x00000006], \
        f"payload {[hex(w) for w in req.payload]}, expected [0x6]"
    assert req.beats[1][1] == 0x1, \
        f"payload beat tkeep {req.beats[1][1]:#x}, expected 0x1 (one Dword)"
    assert_rq_descriptor(req.desc, req.tuser, write=True, bdf=BDF,
                         reg_num=CFG_REG_COMMAND_STATUS,
                         first_be=CFG_BE_LOWER_HALF, what="E2 ")

    await sock.complete(req, status=CPL_SC)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_OK, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_OK"
    assert rsp["rdata"] == 0, \
        (f"rsp_rdata_o = {rsp['rdata']:#010x} after a WRITE -- a config write "
         "completion carries no data (Base 2.1 SS2.3.2 p.122)")
    assert rsp["crs_retries"] == 0


# ==========================================================================
# E3 -- the descriptors match the values committed BEFORE this RTL existed
# ==========================================================================
@cocotb.test()
async def e3_descriptors_match_committed_goldens(dut):
    """Every emitted descriptor equals the hex pinned in SPEC_PREDICTIONS_ENUM.md SS3.4.

    Those literals were written and committed at 0d96a63, before pcie_cfg_txn
    existed.  Comparing against them, rather than against a builder that could
    have drifted with the RTL, is what makes this a golden and not a mirror.
    """
    sock = await init(dut)

    # (write, reg, first_be, wdata, predicted descriptor)
    cases = [
        (False, CFG_REG_VENDOR_DEVICE,  CFG_BE_DWORD,      0,
         0x00010000000040010000000000000000),  # E1 Vendor/Device ID probe
        (False, CFG_REG_CACHE_HEADER,   CFG_BE_BYTE2,      0,
         0x0001000000004001000000000000000C),  # E2 Header Type, byte-granular
        (False, CFG_REG_CACHE_HEADER,   CFG_BE_DWORD,      0,
         0x0001000000004001000000000000000C),  # E3 Header Type, whole Dword
        (True,  CFG_REG_BAR0,           CFG_BE_DWORD,      0xFFFFFFFF,
         0x00010000000050010000000000000010),  # E4 BAR0 all-ones write
        (False, CFG_REG_BAR0,           CFG_BE_DWORD,      0,
         0x00010000000040010000000000000010),  # E5 BAR0 readback
        (True,  CFG_REG_COMMAND_STATUS, CFG_BE_LOWER_HALF, 0x00000006,
         0x00010000000050010000000000000004),  # E9 Command register write
    ]

    for index, (write, reg, fbe, wdata, predicted) in enumerate(cases):
        await send_cmd(dut, write=write, reg_num=reg, first_be=fbe, wdata=wdata)
        await sock.wait_for(index + 1)
        req = sock.requests[index]
        assert req.desc == predicted, (
            f"case {index} (reg {reg:#04x}, {'write' if write else 'read'}): "
            f"descriptor 0x{req.desc:032X} != SPEC_PREDICTIONS_ENUM.md SS3.4 "
            f"golden 0x{predicted:032X}")
        await sock.complete(req, status=CPL_SC, data=0x1234_0000 | index)
        rsp = await recv_rsp(dut)
        assert rsp["outcome"] == TXN_OK

    # E2 and E3 share a descriptor and differ ONLY in tuser: the byte enables
    # do not live in the descriptor.  A test that asserted on tdata alone could
    # not tell a byte-granular read from a whole-Dword one.
    assert sock.requests[1].desc == sock.requests[2].desc, \
        "the byte-granular and whole-Dword Header Type reads must share a descriptor"
    assert (sock.requests[1].tuser & 0xFF) != (sock.requests[2].tuser & 0xFF), \
        ("the two Header Type reads must differ in tuser -- if they do not, the "
         "byte enables are not reaching the wire at all")


# ==========================================================================
# E4 / E5 / E6 -- the terminating statuses
# ==========================================================================
@cocotb.test()
async def e4_unsupported_request(dut):
    """UR classifies as TXN_UR and carries no data.

    The primitive reports the OUTCOME.  Whether TXN_UR means "no device here"
    (Base 2.1 SS2.3.2 IN p.122, the device-existence probe) or "fault" is the
    sequencer's decision and is deliberately not made in this module.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    await sock.complete(sock.requests[0], status=CPL_UR)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_UR, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_UR"
    assert rsp["status_raw"] == CPL_UR, \
        f"raw status {rsp['status_raw']:#05b}, expected {CPL_UR:#05b}"
    assert rsp["rdata"] == 0, "a UR completion carries no data"
    assert rsp["crs_retries"] == 0


@cocotb.test()
async def e5_completer_abort(dut):
    """CA classifies as TXN_CA."""
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_BAR0)
    await sock.wait_for(1)
    await sock.complete(sock.requests[0], status=CPL_CA)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_CA, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_CA"
    assert rsp["status_raw"] == CPL_CA
    assert rsp["rdata"] == 0


@cocotb.test()
async def e6_reserved_status_classifies_as_unsupported_request(dut):
    """All four RESERVED Completion Status encodings must classify as TXN_UR.

    Base 2.1 SS2.3.2 p.122: "Completions with a Reserved Completion Status value
    are treated as if the Completion Status was Unsupported Request (UR)."

    This is the half of the status space that a `default` arm over a four-value
    enum gets wrong -- either by inventing a behaviour the spec already fixed,
    or by leaving the case incomplete.  The raw encoding must still surface on
    rsp_status_raw_o untranslated, so a sequencer's log can tell a real UR from
    a reserved one even though the classification is identical.
    """
    sock = await init(dut)

    for index, status in enumerate(CPL_RESERVED):
        await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
        await sock.wait_for(index + 1)
        await sock.complete(sock.requests[index], status=status)
        rsp = await recv_rsp(dut)

        assert rsp["outcome"] == TXN_UR, (
            f"reserved status {status:#05b} classified as "
            f"{outcome_name(rsp['outcome'])}, expected TXN_UR "
            "(Base 2.1 SS2.3.2 p.122)")
        assert rsp["status_raw"] == status, (
            f"rsp_status_raw_o = {rsp['status_raw']:#05b} for a completion that "
            f"carried {status:#05b} -- the raw encoding must pass through "
            "untranslated")


# ==========================================================================
# E7 / E8 -- the CRS retry loop
# ==========================================================================
@cocotb.test()
async def e7_crs_then_success(dut):
    """CRS -> backoff -> reissue -> SC.

    A CRS TERMINATES the request (Base 2.1 SS2.3.2 IN p.113), so the retry is a
    NEW request that takes a NEW tag -- not a resumption of the old one.  Both
    halves are asserted: the reissued descriptor is byte-identical, and the tag
    is different.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)

    await sock.complete(sock.requests[0], status=CPL_CRS)
    await sock.wait_for(2)          # the retry must appear on its own
    first, retry = sock.requests[0], sock.requests[1]

    assert retry.desc == first.desc, (
        f"the reissued descriptor 0x{retry.desc:032X} differs from the original "
        f"0x{first.desc:032X} -- a retry must repeat the request exactly")
    assert (retry.tuser & 0xFF) == (first.tuser & 0xFF), \
        "the reissued byte enables differ from the original"
    assert retry.tag != first.tag, (
        f"the retry reused tag {retry.tag:#04x}; a CRS terminates the request, "
        "so the reissue is a new request and must take a new tag")

    await sock.complete(retry, status=CPL_SC, data=0x8086_1234)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_OK, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_OK after the retry"
    assert rsp["rdata"] == 0x8086_1234
    assert rsp["crs_retries"] == 1, \
        f"crs_retries_o = {rsp['crs_retries']}, expected exactly 1"
    assert rsp["status_raw"] == CPL_SC, \
        "the reported raw status must be the FINAL completion's, not the CRS"
    assert len(sock.requests) == 2, \
        f"{len(sock.requests)} packets emitted, expected exactly 2"


@cocotb.test()
async def e8_crs_exhausted(dut):
    """CRS every time -> TXN_CRS_EXHAUSTED after exactly CRS_RETRY_MAX retries.

    Base 2.1 SS2.3.2 p.121-122 explicitly permits the bound: "A Root Complex
    implementation may choose to limit the number of Configuration Request/CRS
    Completion Status loops".  What must NOT happen is an unbounded loop, so the
    test asserts the exact packet count as well as the outcome.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)

    expected_packets = CRS_RETRY_MAX + 1        # the original plus its retries
    for attempt in range(expected_packets):
        await sock.wait_for(attempt + 1)
        await sock.complete(sock.requests[attempt], status=CPL_CRS)

    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_CRS_EXHAUSTED, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_CRS_EXHAUSTED"
    assert rsp["crs_retries"] == CRS_RETRY_MAX, \
        f"crs_retries_o = {rsp['crs_retries']}, expected {CRS_RETRY_MAX}"
    assert rsp["status_raw"] == CPL_CRS

    await settle(dut, 4 * CRS_BACKOFF_CYCLES)
    assert len(sock.requests) == expected_packets, (
        f"{len(sock.requests)} packets emitted, expected exactly "
        f"{expected_packets} -- the retry loop is not bounded")
    goldens = {r.desc for r in sock.requests}
    assert len(goldens) == 1, \
        f"the {len(sock.requests)} attempts did not all carry the same descriptor"
    tags = [r.tag for r in sock.requests]
    assert len(set(tags)) == len(tags), \
        f"attempts reused tags {[hex(t) for t in tags]}; each is a new request"


# ==========================================================================
# E9 / E10 -- completion timeout and its aftermath
# ==========================================================================
@cocotb.test()
async def e9_completion_timeout(dut):
    """The timeout strobe naming our tag ends the transaction as TXN_TIMEOUT.

    Base 2.1 SS2.8 p.152 makes a Completion Timeout a reported error, not an
    absence indication -- absence is signalled by UR (SS2.3.2 IN p.122).  The
    primitive reports the outcome; the sequencer decides what it means.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    req = sock.requests[0]
    assert req.tag != 0, "degenerate tag would make the strobe match vacuous"

    await settle(dut, 10)
    await sock.fire_timeout(req.tag)
    rsp = await recv_rsp(dut)

    assert rsp["outcome"] == TXN_TIMEOUT, \
        f"outcome {outcome_name(rsp['outcome'])}, expected TXN_TIMEOUT"
    assert rsp["rdata"] == 0, "a timed-out request returns no data"
    assert len(sock.requests) == 1, \
        "a timeout must not trigger a reissue -- only CRS retries"

    # The primitive must be usable again immediately: the quarantined tag is the
    # tracker's problem, not this module's.
    await send_cmd(dut, write=False, reg_num=CFG_REG_BAR0)
    await sock.wait_for(2)
    await sock.complete(sock.requests[1], status=CPL_SC, data=0xABCD_0001)
    rsp2 = await recv_rsp(dut)
    assert rsp2["outcome"] == TXN_OK, "the primitive did not recover from a timeout"
    assert rsp2["rdata"] == 0xABCD_0001


@cocotb.test()
async def e10_stray_completion_for_quarantined_tag_is_ignored(dut):
    """A completion bearing the timed-out tag must not be consumed by the NEXT
    transaction.

    This is the socket-visible half of the late-completion story.  Upstream, a
    late completion for a quarantined tag is drained by the tracker and raises
    late_cpl_valid_o plus one RC_ERR_ORPHAN_DATA per drained Dword -- none of
    which crosses this module's socket, which is why the primitive has no ports
    for them.  What CAN reach the socket is a packet carrying a stale tag, and
    accepting one would let a dead request answer a live one.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    dead = sock.requests[0]
    await sock.fire_timeout(dead.tag)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_TIMEOUT

    # A second transaction is now in flight on a DIFFERENT tag.
    await send_cmd(dut, write=False, reg_num=CFG_REG_BAR0)
    await sock.wait_for(2)
    live = sock.requests[1]
    assert live.tag != dead.tag, \
        "the test needs distinct tags or it proves nothing"

    # The late completion for the dead request arrives, carrying data that must
    # never be delivered.
    await sock.complete(live, tag=dead.tag, status=CPL_SC, data=0xDEAD_BEEF)
    await settle(dut, 20)
    assert int(dut.rsp_valid_o.value) == 0, (
        "a completion for the quarantined tag was accepted as the live "
        "transaction's response")

    # The real completion still works, with its own data.
    await sock.complete(live, status=CPL_SC, data=0x600D_0001)
    rsp2 = await recv_rsp(dut)
    assert rsp2["outcome"] == TXN_OK
    assert rsp2["rdata"] == 0x600D_0001, (
        f"read data {rsp2['rdata']:#010x} -- the stale completion's payload was "
        "delivered instead of the live one's")


# ==========================================================================
# E11 -- tag discipline
# ==========================================================================
@cocotb.test()
async def e11_wrong_tag_completion_is_ignored(dut):
    """A completion for another tag is consumed off the stream and ignored.

    Consumed, not back-pressured: this is the only consumer on the RC stream and
    stalling it would wedge the receive path for traffic the primitive is not
    even waiting for -- the same reasoning that ties CQ ready high in
    pcie_rq_rc_top.sv:87-92.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    req = sock.requests[0]
    wrong = (req.tag + 0x11) & 0xFF
    assert wrong != req.tag and req.tag != 0 and wrong != 0, \
        "the two tags must be distinct and non-zero or the match proves nothing"

    await sock.complete(req, tag=wrong, status=CPL_SC, data=0xBAD0_BAD0)
    await settle(dut, 20)
    assert int(dut.rsp_valid_o.value) == 0, \
        f"a completion tagged {wrong:#04x} answered a request tagged {req.tag:#04x}"

    await sock.complete(req, status=CPL_SC, data=0x600D_600D)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK
    assert rsp["rdata"] == 0x600D_600D, \
        f"read data {rsp['rdata']:#010x} came from the wrong completion"


# ==========================================================================
# E12 / E13 -- back-pressure on both ports
# ==========================================================================
@cocotb.test()
async def e12_arbitrary_tready_stall(dut):
    """An arbitrarily long s_axis_rq_tready stall must not perturb anything.

    A real link partner advertises real credit and can hold the requester off
    for an unbounded span; the primitive has no cycle-count assumption anywhere
    and must simply wait.  The stall is long enough here (400 cycles, ~12x the
    whole happy path) that any hidden timer would have fired.
    """
    sock = await init(dut)

    sock.stall_beats(400)
    await send_cmd(dut, write=True, reg_num=CFG_REG_BAR0,
                   first_be=CFG_BE_DWORD, wdata=0xFFFFFFFF, limit=2000)
    await settle(dut, 100)
    assert len(sock.requests) == 0, \
        "a packet was emitted while s_axis_rq_tready was low"

    await sock.wait_for(1)
    req = sock.requests[0]
    assert_rq_descriptor(req.desc, req.tuser, write=True, bdf=BDF,
                         reg_num=CFG_REG_BAR0, first_be=CFG_BE_DWORD,
                         what="E12 post-stall ")
    assert req.payload == [0xFFFFFFFF], \
        f"payload {[hex(w) for w in req.payload]} survived the stall wrong"

    await sock.complete(req, status=CPL_SC)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK, \
        f"outcome {outcome_name(rsp['outcome'])} after a long stall"
    assert len(sock.requests) == 1, "the stall caused a duplicate packet"


@cocotb.test()
async def e13_response_backpressure(dut):
    """rsp_valid_o is a held handshake, not a pulse.

    With rsp_ready_i low the outcome must stay presented and stable, the
    primitive must not accept a new command, and it must not reissue anything.
    A consumer that is busy for a while cannot be allowed to miss an outcome --
    this is the compression hazard that bit result_valid in 2a-ii.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    req = sock.requests[0]
    await sock.complete(req, status=CPL_SC, data=0x5EED_0002)

    # rsp_ready_i is left low by init(); hold it there and watch.
    for _ in range(60):
        await RisingEdge(dut.clk_i)
    await ReadOnly()
    assert int(dut.rsp_valid_o.value) == 1, \
        "rsp_valid_o dropped while rsp_ready_i was low -- the outcome was lost"
    assert int(dut.rsp_rdata_o.value) == 0x5EED_0002, "the held response changed"
    assert int(dut.rsp_outcome_o.value) == TXN_OK
    assert int(dut.cmd_ready_o.value) == 0, \
        "cmd_ready_o rose with an unconsumed response still pending"
    await RisingEdge(dut.clk_i)
    assert len(sock.requests) == 1, \
        "the primitive reissued the request while waiting to be read"

    # Now consume it, and confirm the primitive comes back.
    dut.rsp_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.rsp_ready_i.value = 0
    await RisingEdge(dut.clk_i)
    await ReadOnly()
    assert int(dut.rsp_valid_o.value) == 0, "rsp_valid_o stayed high after consumption"
    assert int(dut.cmd_ready_o.value) == 1, "the primitive did not return to idle"


# ==========================================================================
# E14 -- bit 30, not tlast, ends the request
#
# ADDED IN RESPONSE TO A MUTATION SURVIVOR.  Replacing
#     rc_done = rc_match && rc_desc.request_completed
# with
#     rc_done = rc_match && m_axis_rc_tlast_i
# passed all of E1..E13.  It had to: a configuration completion is a single
# beat carrying Request Completed, so bit 30 and tlast coincide on every packet
# those tests drive, and no assertion over a value space the tests collapse can
# tell the two apart.  This test forces them apart, which is the only thing that
# can.
# ==========================================================================
@cocotb.test()
async def e14_completion_without_bit30_does_not_end_the_request(dut):
    """A completion that ends its PACKET but not its REQUEST must not respond.

    PG213 :4049 defines bit 30 as the descriptor of "the last Completion of a
    request", and is explicit that user logic must not retire a request until it
    sees a matching tag WITH that bit set.  tlast is a different thing entirely:
    it ends one packet.

    For a configuration request the two always coincide -- Length is fixed at 1
    Dword (Base 2.1 SS2.2.7 p.79) so a config completion never splits -- which is
    precisely why gating on tlast is a bug that hides.  It is correct here by
    coincidence and wrong the moment this primitive is pointed at anything that
    can split, and it is wrong in the most expensive direction: a request
    retired early frees a tag whose completions are still in flight.

    Reassembling split read data is NOT this module's job and is not asserted
    here: a config transaction is one Dword by construction.  What is asserted
    is the gating.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE)
    await sock.wait_for(1)
    req = sock.requests[0]

    # tlast = 1 (single-beat packet), request_completed = 0.  The two disagree.
    await sock.complete(req, status=CPL_SC, data=0x1111_1111,
                        request_completed=0)
    await settle(dut, 20)
    assert int(dut.rsp_valid_o.value) == 0, (
        "a completion with Request Completed clear ended the transaction -- the "
        "request was retired on tlast instead of on bit 30 (PG213 :4049)")

    # The real last completion of the request.
    await sock.complete(req, status=CPL_SC, data=0x2222_2222)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK, \
        f"outcome {outcome_name(rsp['outcome'])} on the bit-30 completion"
    assert rsp["rdata"] == 0x2222_2222, (
        f"read data {rsp['rdata']:#010x} -- the response carried the non-final "
        "completion's payload")
    assert len(sock.requests) == 1, "no reissue was expected"


# ==========================================================================
# E15 / E16 / E17 -- Stage D increment 1: the per-transaction Type select
#
# Structurally non-falsifiable pre-change: a type1=1 test cannot RUN against
# the pre-change RTL because the port does not exist, so the compile fails
# before any assertion can.  Recorded per SPEC_PREDICTIONS_STAGE_D.md SS7.4;
# the mutation set (type1 ignored / type1 inverted) carries the proof weight
# instead, and the kill map lives in the commit message.
# ==========================================================================
@cocotb.test()
async def e15_cfg1_whole_descriptor_goldens(dut):
    """type1=1 selects the CFG1 descriptor pair -- whole 128-bit compare.

    req_type 1001 (read) / 1011 (write), one bit from the Type 0 encodings
    (Base 2.1 Table 2-3 p.58 on the wire; pcie_rq_rc_pkg.sv:63-79 at the
    descriptor level).  assert_rq_descriptor compares the WHOLE word: a
    field-subset check would pass identically for a DUT that ignored the
    input (Trap A, SPEC_PREDICTIONS_STAGE_D.md SS8.1).
    """
    sock = await init(dut)

    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE,
                   first_be=CFG_BE_DWORD, type1=True)
    await sock.wait_for(1)
    read = sock.requests[0]
    assert not read.write, "a CfgRd1 is a single-beat packet with no payload"
    assert_rq_descriptor(read.desc, read.tuser, write=False, bdf=BDF,
                         reg_num=CFG_REG_VENDOR_DEVICE, first_be=CFG_BE_DWORD,
                         type1=True, what="E15 read ")
    await sock.complete(read, status=CPL_SC, data=0x1017_15B3)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK
    assert rsp["rdata"] == 0x1017_15B3, \
        "a CfgRd1 completion must deliver data exactly as a CfgRd0's does"

    # The write: payload beat present, one Dword, and the whole-word golden.
    await send_cmd(dut, write=True, reg_num=CFG_REG_COMMAND_STATUS,
                   first_be=CFG_BE_LOWER_HALF, wdata=0x00000006, type1=True)
    await sock.wait_for(2)
    write = sock.requests[1]
    assert write.write, "a CfgWr1 must carry a payload beat"
    assert write.payload == [0x00000006], \
        f"payload {[hex(w) for w in write.payload]}, expected [0x6]"
    assert_rq_descriptor(write.desc, write.tuser, write=True, bdf=BDF,
                         reg_num=CFG_REG_COMMAND_STATUS,
                         first_be=CFG_BE_LOWER_HALF, type1=True,
                         what="E15 write ")
    await sock.complete(write, status=CPL_SC)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK


@cocotb.test()
async def e16_type0_pin_one_bit_from_cfg1(dut):
    """type1=0 still emits the Type 0 descriptor -- pinned, not inherited.

    E1/E2 assert this through send_cmd's default; this test drives type1=0
    EXPLICITLY back to back with a type1=1 twin of the same command and pins
    the distance between the two observed descriptors at exactly bit 75 (the
    req_type LSB).  This is the test that kills the inverted-input mutation:
    an inversion turns the explicit 0 into req_type 1001 and the whole-word
    golden below fails.
    """
    sock = await init(dut)

    await send_cmd(dut, write=False, reg_num=CFG_REG_CACHE_HEADER,
                   first_be=CFG_BE_DWORD, type1=False)
    await sock.wait_for(1)
    t0 = sock.requests[0]
    assert_rq_descriptor(t0.desc, t0.tuser, write=False, bdf=BDF,
                         reg_num=CFG_REG_CACHE_HEADER, first_be=CFG_BE_DWORD,
                         type1=False, what="E16 type1=0 ")
    await sock.complete(t0, status=CPL_SC, data=0x0001_0000)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK

    await send_cmd(dut, write=False, reg_num=CFG_REG_CACHE_HEADER,
                   first_be=CFG_BE_DWORD, type1=True)
    await sock.wait_for(2)
    t1 = sock.requests[1]
    assert_rq_descriptor(t1.desc, t1.tuser, write=False, bdf=BDF,
                         reg_num=CFG_REG_CACHE_HEADER, first_be=CFG_BE_DWORD,
                         type1=True, what="E16 type1=1 ")
    assert t0.desc ^ t1.desc == 1 << 75, (
        f"the type1=0 and type1=1 descriptors differ by "
        f"{t0.desc ^ t1.desc:#x}, expected exactly bit 75 (the req_type LSB) "
        "-- something besides the Type moved with the select")
    await sock.complete(t1, status=CPL_SC, data=0x0001_0000)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK


@cocotb.test()
async def e17_crs_retry_preserves_type1(dut):
    """A CRS'd CfgRd1 is reissued as a CfgRd1 -- the retry must not decay.

    P6.3: the retry loop is phase-blind and reissues whatever it latched.  The
    type1 flag is part of the latched command, so the reissued descriptor must
    be byte-identical -- INCLUDING req_type 1001.  A retry path that rebuilt
    the descriptor from anything but the latch (or re-sampled cmd_type1_i,
    which this test holds at 0 during the retry window) would emit the CFG0
    twin and pass every assertion except the whole-word compare.
    """
    sock = await init(dut)
    await send_cmd(dut, write=False, reg_num=CFG_REG_VENDOR_DEVICE,
                   first_be=CFG_BE_DWORD, type1=True)
    # De-assert the input immediately: the retry must come from the latch.
    dut.cmd_type1_i.value = 0
    await sock.wait_for(1)

    await sock.complete(sock.requests[0], status=CPL_CRS)
    await sock.wait_for(2)
    first, retry = sock.requests[0], sock.requests[1]

    assert retry.desc == first.desc, (
        f"the reissued descriptor 0x{retry.desc:032X} differs from the "
        f"original 0x{first.desc:032X} -- a CRS retry must repeat the request "
        "exactly, Type included (P6.3)")
    assert (retry.desc >> 75) & 0xF == 0b1001, (
        f"the retry's req_type is {(retry.desc >> 75) & 0xF:#06b} -- the CRS "
        "reissue decayed to Type 0")
    assert (retry.tuser & 0xFF) == (first.tuser & 0xFF)

    await sock.complete(retry, status=CPL_SC, data=0x1AF4_1100)
    rsp = await recv_rsp(dut)
    assert rsp["outcome"] == TXN_OK
    assert rsp["rdata"] == 0x1AF4_1100
    assert rsp["crs_retries"] == 1
