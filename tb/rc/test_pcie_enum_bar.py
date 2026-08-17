"""Commit 2b-3 -- the BAR phase standalone (B1..B24).

The DUT is the WHOLE enumeration assembly: pcie_enum_scan, pcie_enum_bar, the
one pcie_cfg_txn and the REAL static handoff mux.  The Python bench plays their
shared pcie_rq_rc_top socket (enum_tb_common.Socket, which asserts its own
ordering invariants).

WHAT THIS TARGET OWNS: the BAR sizing/assignment/enable policy, every fault path
through it, and the handoff.  pcie_cfg_txn's own behaviour is verilate_enum_txn's
subject and the presence policy is verilate_enum_scan's; neither is re-tested.

!! FOUR TRAPS FROM PART 1, APPLIED PREDICTIVELY RATHER THAN DISCOVERED.

  1. B1 and B5 of SSE.8 have BYTE-IDENTICAL DESCRIPTORS -- both are CfgWr0 to
     register 4 with first_be=1111.  The all-ones sizing write and the assignment
     write are indistinguishable on tdata alone, so a descriptor-only assertion
     would pass against an FSM that emitted the sizing write twice and never
     assigned anything.  EVERY write assertion here carries its payload Dword,
     and Txn below makes that structural: the payload is part of the tuple that
     gets compared, so it cannot be forgotten at a call site.

  2. The "all-ones write removed" mutation only reaches its CONDITION against a
     32-BIT NON-PREFETCHABLE BAR.  With a 64-bit or prefetchable BAR the reset
     readback is 0000000C rather than 00000000 and the mutation survives.  b2
     exists for exactly that and says so.

  3. Every on-wire assertion goes through enum_tb_common's empty-set guards
     (nonempty / expect_count / assert_sequence).  A passing assertion over an
     empty observation set is the same bug as a green diff over an empty file.

  4. settle() stays LOCAL to this file.  It is not an early-exit loop -- it
     always runs its full count -- so its default IS sim time, and sharing it
     would move the other benches off their pinned sim end times.

!! AND NO TEST HERE ASSERTS ANY PROPERTY OF A TAG VALUE.  Tag values are a
property of the socket model, not of the design: the real tracker recycles a tag
as soon as a completion carrying Request Completed retires it (PG213 :4257).

Spec cited (read, not assumed):
  BAR bit layout, Table 6-4 ......... [PCI3] SS6.2.5.1 p.225-226 :11187,:11190,
                                      :11193,:11205,:11207
  all-ones sizing algorithm ......... [PCI3] SS6.2.5.1 p.226 :11222,:11224,:11226
  16-byte floor (overridden) ........ [PCI3] SS6.2.5.1 p.226 :11219
  128-byte floor (governs) .......... [BASE] SS7.5.2.1 p.491-492
  Command bits 0/1/2 + reset state .. [PCI3] SS6.2.2 Table 6-1 p.218 :10761,
                                      :10764,:10767
  Expansion ROM at 30h .............. [PCI3] SS6.2.5.2 p.227 :11283,:11287
  Type 0 header offsets ............. [BASE] Figure 7-5 p.491
  UR for an unimplemented register .. [BASE] SS7.3.3 p.480
Full derivation: docs/predictions/SPEC_PREDICTIONS_ENUM.md SSE.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

from enum_tb_common import (
    BAR_IO, BAR_MEM32, BAR_MEM64, BAR_SLOTS, BDF, CLK_NS, DEVICE, HDR_TYPE0,
    HDR_TYPE1, MEM_BAR_BASE, REG0, SCAN_BUS, VENDOR,
    CMD_ENABLE_VALUE,
    ENUM_ERR_BAR_ADDR32, ENUM_ERR_BAR_SIZE, ENUM_ERR_BAR_TYPE,
    ENUM_ERR_BAR_WINDOW, ENUM_ERR_CA, ENUM_ERR_CRS_EXHAUSTED, ENUM_ERR_NONE,
    ENUM_ERR_TIMEOUT, ENUM_ERR_UR_POST_PROBE,
    CFG_BE_DWORD, CFG_BE_LOWER_HALF,
    CFG_REG_BAR0, CFG_REG_BAR1, CFG_REG_BAR2, CFG_REG_BAR3, CFG_REG_BAR4,
    CFG_REG_BAR5, CFG_REG_CACHE_HEADER, CFG_REG_COMMAND_STATUS,
    CFG_REG_EXPANSION_ROM, CFG_REG_VENDOR_DEVICE,
    CPL_CA, CPL_CRS, CPL_SC, CPL_UR,
    BarSpec, ConfigDevice, Socket,
    assert_rq_descriptor, assert_sequence, decode_rq_desc, decode_tuser,
    err_name, expect_count, nonempty,
)


CRS_RETRY_MAX = 3          # tb_pcie_enum_bar.sv override
MASK64 = (1 << 64) - 1

KB = 1024
MB = 1024 * 1024


# ==========================================================================
# SS ONE OBSERVED TRANSACTION -- payload included BY CONSTRUCTION
#
# Trap 1 in the module docstring.  The payload is a FIELD OF THE TUPLE, so a
# whole-sequence compare cannot silently omit it and a call site cannot forget
# to pass it.  That is the difference between a rule and a convention.
# ==========================================================================
class Txn:
    __slots__ = ("write", "reg", "first_be", "payload")

    def __init__(self, write, reg, first_be, payload):
        self.write = bool(write)
        self.reg = reg
        self.first_be = first_be
        self.payload = payload

    def __eq__(self, other):
        return (self.write, self.reg, self.first_be, self.payload) == \
               (other.write, other.reg, other.first_be, other.payload)

    def __repr__(self):
        kind = "CfgWr0" if self.write else "CfgRd0"
        data = "-" if self.payload is None else f"{self.payload:#010x}"
        return f"{kind}(reg={self.reg:#04x}, fbe={self.first_be:#06b}, data={data})"


def rd(reg):
    """A whole-Dword configuration read."""
    return Txn(False, reg, CFG_BE_DWORD, None)


def wr(reg, data, first_be=CFG_BE_DWORD):
    return Txn(True, reg, first_be, data)


# The two transactions the presence scan always emits first.  Every golden
# sequence in this file starts with them, because the DUT is the whole assembly
# and the handoff is part of what is under test.
SCAN_TXNS = [rd(CFG_REG_VENDOR_DEVICE), rd(CFG_REG_CACHE_HEADER)]

# The last transaction of every successful enumeration -- SSE.6, SSE.8 B15.
CMD_TXN = wr(CFG_REG_COMMAND_STATUS, CMD_ENABLE_VALUE, CFG_BE_LOWER_HALF)


def probe(reg):
    """The all-ones write and readback pair for one candidate register."""
    return [wr(reg, 0xFFFFFFFF), rd(reg)]


# ==========================================================================
# SS THE SOCKET SERVER
#
# Answers the socket's observed requests out of a ConfigDevice, and injects
# faults keyed by (register, LOGICAL occurrence of that register).
#
# !! THE OCCURRENCE COUNTER DOES NOT ADVANCE ON A CRS.  pcie_cfg_txn re-issues a
# CRS'd request as a NEW request (Base 2.1 SS2.3.2 p.121), so each retry is another
# socket request for the same LOGICAL transaction.  Counting retries would make
# every key downstream of a CRS shift, which is the kind of bench fragility that
# turns a real failure into an hour of confusion.
#
# For a 64-bit pair the keys map one-to-one onto SSE.8:
#   (4,0) B1 sizing write   (4,1) B2 readback   (4,2) B5 assign
#   (5,0) B3 sizing write   (5,1) B4 readback   (5,2) B6 assign
# ==========================================================================
class Server:
    def __init__(self, dut, sock, device, faults=None, silent=(), crs=None):
        self.dut = dut
        self.sock = sock
        self.dev = device
        self.faults = dict(faults or {})   # (reg, occ) -> CPL_* status
        self.silent = set(silent)          # (reg, occ) -> answer nothing
        self.crs = dict(crs or {})         # (reg, occ) -> how many CRS first
        self.txns = []                     # observed, in order
        self.answered = 0
        self.ur_default_hits = 0
        self.silent_hits = 0
        self._occ = {}

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            while self.answered < len(self.sock.requests):
                req = self.sock.requests[self.answered]
                self.answered += 1
                await self._serve(req)

    async def _serve(self, req):
        desc = decode_rq_desc(req.desc)
        reg = desc["reg_num"]
        first_be = decode_tuser(req.tuser)["first_be"]
        payload = req.payload[0] if req.write else None
        self.txns.append(Txn(req.write, reg, first_be, payload))

        occ = self._occ.get(reg, 0)
        key = (reg, occ)

        if self.crs.get(key, 0) > 0:
            self.crs[key] -= 1
            await self.sock.complete(req, status=CPL_CRS)
            return                                    # occurrence NOT advanced

        self._occ[reg] = occ + 1

        if key in self.silent:
            self.silent_hits += 1
            return                                    # deliberate silence

        status = self.faults.get(key)
        if status is not None:
            await self.sock.complete(req, status=status)
            return

        if req.write:
            self.dev.write(reg, payload, first_be)
            await self.sock.complete(req, status=CPL_SC)
            return

        value = self.dev.read(reg)
        if value is None:
            # SS7.3.3 p.480 -- a register the device does not implement.
            self.ur_default_hits += 1
            await self.sock.complete(req, status=CPL_UR)
        else:
            await self.sock.complete(req, status=CPL_SC, data=value)

    def logical(self, key):
        """Was this (reg, occ) reached at all?  Guards a vacuous fault test."""
        return self._occ.get(key[0], 0) > key[1]


# ==========================================================================
# SS A VIEW ONTO THE SHIM'S EXTRA INSTANCES
#
# tb_pcie_enum_bar.sv carries two additional pcie_enum_top instances whose
# allocator geometry the shipped defaults cannot reach.  Their socket signals are
# prefixed, so rather than teach Socket about prefixes -- a change that would
# reach the four green enum benches for no benefit to them -- the prefix is
# stripped here.  Socket is used verbatim.
# ==========================================================================
class Sub:
    def __init__(self, dut, prefix):
        self._dut = dut
        self._prefix = prefix

    def __getattr__(self, name):
        if name in ("clk_i", "rst_i"):
            return getattr(self._dut, name)
        return getattr(self._dut, self._prefix + name)


# ==========================================================================
# Harness
# ==========================================================================
def bar_device(bars=None, header_type=HDR_TYPE0, raw=None):
    return ConfigDevice(bars=bars, header_type=header_type, raw=raw)


async def init(dut, device=None, tag_delay=2, faults=None, silent=(), crs=None,
               bar_enable=1, view=None, bus=SCAN_BUS):
    """Bring the DUT up and start a socket plus a server on it.

    `view` selects one of the shim's extra instances (see Sub); it defaults to
    the main DUT.  Reset is driven on the shared clk_i/rst_i, so all three
    instances reset together and the two unused ones simply never start.
    """
    # A fresh clock per test, deliberately: cocotb kills every coroutine when a
    # test ends, so a clock started once and cached would leave test 2 onward
    # with no clock at all -- which presents as every later test failing at
    # 0.00ns and looks nothing like a DUT fault.
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())

    target = view if view is not None else dut

    dut.rst_i.value = 1
    dut.scan_bus_i.value = bus
    dut.tx_fc_blocked_i.value = 0
    for pre in ("", "x_", "h_"):
        getattr(dut, pre + "scan_start_i").value = 0
        getattr(dut, pre + "bar_enable_i").value = 0
        getattr(dut, pre + "s_axis_rq_tready_i").value = 1
        getattr(dut, pre + "pcie_rq_tag_i").value = 0
        getattr(dut, pre + "pcie_rq_tag_vld_i").value = 0
        getattr(dut, pre + "m_axis_rc_tdata_i").value = 0
        getattr(dut, pre + "m_axis_rc_tkeep_i").value = 0
        getattr(dut, pre + "m_axis_rc_tvalid_i").value = 0
        getattr(dut, pre + "m_axis_rc_tlast_i").value = 0
    dut.cpl_timeout_valid_i.value = 0
    dut.cpl_timeout_tag_i.value = 0

    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    target.bar_enable_i.value = bar_enable
    await RisingEdge(dut.clk_i)

    sock = Socket(target, tag_delay=tag_delay)
    sock.start()
    device = device if device is not None else bar_device()
    server = Server(target, sock, device, faults=faults, silent=silent, crs=crs)
    server.start()
    await RisingEdge(dut.clk_i)
    return sock, server, device


async def start_scan(target):
    target.scan_start_i.value = 1
    await RisingEdge(target.clk_i)
    target.scan_start_i.value = 0


async def settle(dut, cycles=30):
    """LOCAL BY DESIGN -- trap 4.  Not an early-exit loop: the default is sim time."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)


async def wait_enum(target, cycles=20000):
    """Block until enumeration reaches a terminal state.

    Samples under ReadOnly but RETURNS from a writable phase, so a caller can
    drive a signal immediately afterwards -- returning straight out of ReadOnly
    makes the next write raise "scheduled during a read-only sync phase", a bench
    fault that looks nothing like the DUT behaviour under test.
    """
    for _ in range(cycles):
        await ReadOnly()
        reached = int(target.enum_done_o.value) or int(target.enum_error_o.value)
        await RisingEdge(target.clk_i)
        if reached:
            return
    raise AssertionError("enumeration never reached a terminal state")


async def status(target):
    await ReadOnly()
    sizes = int(target.bar_size_o.value)
    addrs = int(target.bar_addr_o.value)
    snap = {
        "busy": int(target.bar_busy_o.value),
        "done": int(target.enum_done_o.value),
        "error": int(target.enum_error_o.value),
        "code": int(target.enum_error_code_o.value),
        "count": int(target.bar_count_o.value),
        "valid": int(target.bar_valid_o.value),
        "is64": int(target.bar_is_64_o.value),
        "prefetch": int(target.bar_prefetch_o.value),
        "io_mask": int(target.io_bar_mask_o.value),
        "size": [(sizes >> (64 * i)) & MASK64 for i in range(BAR_SLOTS)],
        "addr": [(addrs >> (64 * i)) & MASK64 for i in range(BAR_SLOTS)],
    }
    await RisingEdge(target.clk_i)
    return snap


def assert_ok(snap, what=""):
    assert snap["done"] == 1, f"{what}enumeration did not complete: {snap}"
    assert snap["error"] == 0, \
        f"{what}enumeration errored with {err_name(snap['code'])}: {snap}"
    assert snap["code"] == ENUM_ERR_NONE, \
        f"{what}error code {err_name(snap['code'])} with no error asserted"


def assert_failed(snap, code, what=""):
    assert snap["error"] == 1, \
        f"{what}expected {err_name(code)}, but enumeration did not error: {snap}"
    assert snap["code"] == code, \
        f"{what}expected {err_name(code)}, got {err_name(snap['code'])}"
    assert snap["done"] == 0, \
        f"{what}enum_done_o asserted alongside an error: {snap}"


def assert_descriptors(sock, device_bdf=BDF):
    """Every emitted descriptor matches a freshly built golden, payload included.

    Guarded against an empty request list: an assertion loop that iterates zero
    times is the trap-3 vacuous pass.
    """
    requests = nonempty(sock.requests, "no RQ packet was emitted at all")
    for index, req in enumerate(requests):
        desc = decode_rq_desc(req.desc)
        assert_rq_descriptor(
            req.desc, req.tuser, write=req.write, bdf=device_bdf,
            reg_num=desc["reg_num"],
            first_be=decode_tuser(req.tuser)["first_be"],
            what=f"request {index} ({req!r}): ")
        if req.write:
            assert len(req.payload) == 1, (
                f"request {index} is a write with {len(req.payload)} payload "
                f"Dwords; every configuration write is exactly one "
                f"(Base 2.1 SS2.2.7 p.79)")


def slot(snap, index):
    return {
        "valid": (snap["valid"] >> index) & 1,
        "is64": (snap["is64"] >> index) & 1,
        "prefetch": (snap["prefetch"] >> index) & 1,
        "size": snap["size"][index],
        "addr": snap["addr"][index],
    }


async def run_enum(dut, device, **kwargs):
    """The common body: bring up, scan, enumerate, snapshot."""
    sock, server, dev = await init(dut, device=device, **kwargs)
    target = kwargs.get("view") or dut
    await start_scan(target)
    await wait_enum(target)
    snap = await status(target)
    return sock, server, dev, snap


# ==========================================================================
# B0 -- ⭐ the bench's own guards, proved to fire
#
# !! THIS TEST EXISTS BECAUSE THE MUTATION CAMPAIGN SAID IT HAD TO.
#
# Defeating enum_tb_common.nonempty's assertion, and defeating
# ConfigDevice.assert_mask_exercised, BOTH SURVIVED the first campaign -- and
# they survived for a reason that is correct and useless: a guard only fires on
# a broken run, and every run in a green suite is unbroken. Nor did the two
# mutations that DO break things prove otherwise: "the socket records nothing"
# killed all 29 tests, but by hanging the DUT ("enumeration never reached a
# terminal state"), never once reaching the empty-set guard.
#
# That is 2b-2's "guards that are never exercised aren't guards", recurring on
# the very mechanism the brief added to prevent vacuous passes. The fix is to
# exercise them directly: call each guard with the input it exists to reject and
# assert that it raises. The guards are bench-as-RTL, so testing them is the same
# discipline the socket model already gets.
# ==========================================================================
@cocotb.test()
async def b0_bench_guards_are_load_bearing(dut):
    """Every empty-set guard, and the write-mask check, actually rejects."""
    def must_raise(what, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except AssertionError:
            return
        raise AssertionError(
            f"{what} did NOT raise. The guard is inert, so every assertion "
            "relying on it passes vacuously -- which is the exact bug the guard "
            "was added to prevent.")

    must_raise("nonempty([])", nonempty, [], "self-test")
    must_raise("expect_count([], 1)", expect_count, [], 1, "self-test")
    must_raise("expect_count([x], 2)", expect_count, [rd(0)], 2, "self-test")
    must_raise("assert_sequence(observed=[], golden=[x])",
               assert_sequence, [], [rd(0)], "self-test")
    must_raise("assert_sequence(golden=[])  -- a golden that asserts nothing",
               assert_sequence, [rd(0)], [], "self-test")
    must_raise("assert_sequence on a length mismatch",
               assert_sequence, [rd(0)], [rd(0), rd(1)], "self-test")
    must_raise("assert_sequence on a payload-only difference",
               assert_sequence, [wr(4, 0xFFFFFFFF)], [wr(4, 0x80000000)],
               "self-test")

    # ...and the write-mask check, against a device that echoes writes verbatim.
    echoed = ConfigDevice(bars={CFG_REG_BAR0: BarSpec(BAR_MEM32, 16 * KB)})
    must_raise("assert_mask_exercised() on a device that was never written",
               echoed.assert_mask_exercised, "self-test: ")

    # The positive direction too, or the above would pass against a check that
    # always raises.
    echoed.write(CFG_REG_BAR0, 0xFFFFFFFF)
    echoed.assert_mask_exercised("self-test: a real masked write must satisfy it: ")
    nonempty([1], "self-test")
    expect_count([1, 2], 2, "self-test")
    assert_sequence([rd(0)], [rd(0)], "self-test")

    # ⭐ AND THE PAYLOAD IS PART OF THE COMPARISON -- trap 1, proved rather than
    # asserted in a comment. B1 and B5 of SSE.8 have byte-identical descriptors,
    # so a Txn equality that ignored the payload would make every BAR write
    # assertion in this file vacuous.
    assert wr(CFG_REG_BAR0, 0xFFFFFFFF) != wr(CFG_REG_BAR0, 0x80000000), (
        "the SSE.8 B1 and B5 transactions compare EQUAL. Their descriptors are "
        "byte-identical and only the payload Dword distinguishes them, so this "
        "bench would pass against an FSM that emitted the all-ones sizing write "
        "twice and never assigned anything (SSE.8.2, SSE.9 EF3)")
    assert rd(CFG_REG_BAR0) != wr(CFG_REG_BAR0, 0xFFFFFFFF), \
        "a read and a write to the same register compare equal"

    # No simulation time is consumed and none is needed: every subject here is
    # bench code. The DUT is untouched, deliberately.


# ==========================================================================
# B1 -- one 32-bit memory BAR, end to end
# ==========================================================================
@cocotb.test()
async def b1_single_32bit_memory_bar(dut):
    """A 16 KB 32-bit prefetchable BAR0 is sized, placed and enabled.

    The full transaction sequence is asserted, not just the outcome: sizing
    probes every candidate register 4..9 even though only BAR0 answers, because
    a device cannot be asked "how many BARs do you have" -- SSE.8.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_ok(snap)
    assert_descriptors(sock)
    dev.assert_mask_exercised()

    golden = SCAN_TXNS + probe(CFG_REG_BAR0) + [wr(CFG_REG_BAR0, 0x80000000)]
    for reg in (CFG_REG_BAR1, CFG_REG_BAR2, CFG_REG_BAR3, CFG_REG_BAR4,
                CFG_REG_BAR5):
        golden += probe(reg)
    golden += [CMD_TXN]
    assert_sequence(server.txns, golden, "B1 transaction sequence")

    assert snap["count"] == 1, f"bar_count_o {snap['count']} != 1"
    assert slot(snap, 0) == {"valid": 1, "is64": 0, "prefetch": 1,
                             "size": 16 * KB, "addr": MEM_BAR_BASE}, \
        f"BAR0 slot wrong: {slot(snap, 0)}"
    assert snap["io_mask"] == 0, f"io_bar_mask_o {snap['io_mask']:#08b} != 0"
    assert dev.command == CMD_ENABLE_VALUE, \
        (f"Command register {dev.command:#06x} != {CMD_ENABLE_VALUE:#06x} -- "
         "Memory Space Enable | Bus Master Enable, [PCI3] Table 6-1 p.218")


# ==========================================================================
# B2 -- ⭐ trap 2 / EF7: the 32-bit NON-PREFETCHABLE case
# ==========================================================================
@cocotb.test()
async def b2_explicit_32bit_non_prefetchable_bar(dut):
    """The one BAR shape that can catch a missing all-ones write.

    !! THIS TEST EXISTS FOR A MUTATION, AND THE REASON IS THE POINT.
    An implemented 32-bit non-prefetchable memory BAR reads 00000000 before the
    all-ones write -- bit-for-bit identical to an unimplemented register's
    hardwired zero ([PCI3] p.226 :11224).  A 64-bit or prefetchable BAR reads
    0000000C instead, so with either of those the mutation "the all-ones write is
    removed" reaches the mutated LINE without reaching the mutated CONDITION and
    survives.  SSE.2.2, SSE.9 EF7.

    Also the only test whose BAR has type field 0000, i.e. every one of the four
    read-only bits is legitimately zero.
    """
    dev = bar_device({CFG_REG_BAR2: BarSpec(BAR_MEM32, 128, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_ok(snap)
    assert_descriptors(sock)
    dev.assert_mask_exercised()

    # 128 bytes is exactly the PCIe floor -- [BASE] SS7.5.2.1 p.491-492. One below
    # it is b7's subject.
    assert snap["count"] == 1, f"bar_count_o {snap['count']} != 1"
    assert slot(snap, 0) == {"valid": 1, "is64": 0, "prefetch": 0,
                             "size": 128, "addr": MEM_BAR_BASE}, \
        f"BAR2 slot wrong: {slot(snap, 0)}"

    golden = (SCAN_TXNS + probe(CFG_REG_BAR0) + probe(CFG_REG_BAR1)
              + probe(CFG_REG_BAR2) + [wr(CFG_REG_BAR2, 0x80000000)]
              + probe(CFG_REG_BAR3) + probe(CFG_REG_BAR4) + probe(CFG_REG_BAR5)
              + [CMD_TXN])
    assert_sequence(server.txns, golden, "B2 transaction sequence")

    # The premise, asserted rather than assumed: the readback the FSM decoded was
    # only non-zero BECAUSE of the all-ones write.
    fresh = bar_device({CFG_REG_BAR2: BarSpec(BAR_MEM32, 128, prefetch=False)})
    assert fresh.read(CFG_REG_BAR2) == 0x00000000, (
        "the premise of this test is broken: an unwritten 32-bit "
        "non-prefetchable BAR must read 00000000, identical to unimplemented")
    assert fresh.read(CFG_REG_BAR3) == 0x00000000, "unimplemented must read zero"


# ==========================================================================
# B3 -- ⭐ the 64-bit pair, the NVMe case
# ==========================================================================
@cocotb.test()
async def b3_64bit_prefetchable_pair(dut):
    """BAR0/1 as a 16 KB 64-bit prefetchable pair: SSE.3.4 and SSE.7.4 exactly.

    Base 2.1 independently makes this the EXPECTED shape rather than a corner
    case: prefetchable BARs must support 64-bit addressing (SS7.5.2.1 p.491-492)
    and a compliant memory BAR should be prefetchable.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_ok(snap)
    assert_descriptors(sock)
    dev.assert_mask_exercised()

    # SSE.8 B1..B15, hand-written from the table rather than generated.
    golden = SCAN_TXNS + [
        wr(CFG_REG_BAR0, 0xFFFFFFFF),      # B1  sizing, low half
        rd(CFG_REG_BAR0),                  # B2  -> 0xFFFFC00C
        wr(CFG_REG_BAR1, 0xFFFFFFFF),      # B3  sizing, high half
        rd(CFG_REG_BAR1),                  # B4  -> 0xFFFFFFFF
        wr(CFG_REG_BAR0, 0x80000000),      # B5  assign, low half
        wr(CFG_REG_BAR1, 0x00000000),      # B6  assign, high half
    ] + probe(CFG_REG_BAR2) + probe(CFG_REG_BAR3) \
      + probe(CFG_REG_BAR4) + probe(CFG_REG_BAR5) + [CMD_TXN]
    assert_sequence(server.txns, golden, "B3 transaction sequence (SSE.8)")

    # ⭐ ONE BAR, NOT TWO. A 64-bit pair occupies two registers and counts once.
    # The mutation "the pair is decoded as two independent 32-bit BARs" reports 2.
    assert snap["count"] == 1, (
        f"bar_count_o {snap['count']} != 1. bar_count_o counts BARs, not "
        "registers -- a 64-bit pair is ONE BAR occupying two registers (SSE.7.4)")
    assert slot(snap, 0) == {"valid": 1, "is64": 1, "prefetch": 1,
                             "size": 16 * KB, "addr": MEM_BAR_BASE}, \
        f"the pair decoded wrong: {slot(snap, 0)}"
    assert slot(snap, 1)["valid"] == 0, \
        "a second BAR slot was filled -- the pair was split"

    # The readbacks the FSM actually saw were the SSE.3.4 goldens.
    assert dev.bar_written(CFG_REG_BAR0) == 0x80000000, \
        f"BAR0 holds {dev.bar_written(CFG_REG_BAR0):#010x}, not the low half"
    assert dev.bar_written(CFG_REG_BAR1) == 0x00000000, \
        f"BAR1 holds {dev.bar_written(CFG_REG_BAR1):#010x}, not the high half"

    # ⭐ MEASURED, AND IT CONTRADICTS SSE.4.1's PREDICTED KILL MECHANISM.
    #
    # SSE.4.1 predicted that mis-decoding this pair as two independent 32-bit
    # BARs would be caught BY THE 128-BYTE FLOOR, reasoning that the upper half's
    # sizing readback FFFFFFFF decodes as ~FFFFFFF0 + 1 = 16 bytes -- "precisely
    # PCI 3.0's minimum, which is exactly what PCIe forbids".
    #
    # THE FLOOR IS NEVER REACHED. FFFFFFFF has BIT 0 SET, and bit 0 is the Memory
    # Space Indicator ([PCI3] p.225 :11187), so the I/O check -- which must
    # precede the size decode, because an I/O BAR is sized against a different
    # mask -- claims the register first. A mis-decoding FSM calls the upper half
    # an I/O BAR and SKIPS it. The derivation in SSE.4.1 omitted that step.
    #
    # The mutation is still killed, by the emitted transaction sequence and by
    # bar_count_o / bar_is_64_o -- SSE.4.1's own "secondary predicted kills",
    # which turn out to be the primary ones. Recorded as measured, which SSE.4.1
    # explicitly asked for if the floor did not fire first.
    #
    # The floor only becomes reachable for a pair of 2^36 bytes or more, where
    # the upper half's low nibble is not all ones. No such device is enumerated
    # here, so the claim is pinned as an assertion rather than left as prose.
    # Stated on a FRESH device: by now the real dev holds the assigned address,
    # not the sizing readback. Asserting the live one would read 0x00000000 and
    # say nothing about the sizing step.
    fresh = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    fresh.write(CFG_REG_BAR1, 0xFFFFFFFF)
    upper = fresh.read(CFG_REG_BAR1)
    assert upper == 0xFFFFFFFF, \
        f"the upper half's sizing readback is {upper:#010x}, not 0xFFFFFFFF"
    assert upper & 1 == 1, (
        f"the upper half's sizing readback {upper:#010x} has bit 0 clear. "
        "SSE.4.1's kill analysis, and the note above, both turn on that bit "
        "being SET -- it is what sends a mis-decoding FSM down the I/O arm "
        "instead of into the 128-byte floor")


# ==========================================================================
# B4 -- a mixed set
# ==========================================================================
@cocotb.test()
async def b4_mixed_bar_set(dut):
    """32-bit + 64-bit pair + unimplemented + I/O, all in one device.

    The allocator's ascending, naturally-aligned placement is the real subject:
    a 1 MB BAR following a 256 KB one at 0x80000000 must land at 0x80100000,
    which is above the cursor rather than at it.
    """
    dev = bar_device({
        CFG_REG_BAR0: BarSpec(BAR_MEM32, 256 * KB, prefetch=False),
        CFG_REG_BAR1: BarSpec(BAR_IO, 32),
        CFG_REG_BAR2: BarSpec(BAR_MEM64, 1 * MB, prefetch=True),
        # BAR4 (register 8) unimplemented
        CFG_REG_BAR5: BarSpec(BAR_MEM32, 128, prefetch=False),
    })
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_ok(snap)
    assert_descriptors(sock)
    dev.assert_mask_exercised()

    golden = SCAN_TXNS + (
        probe(CFG_REG_BAR0) + [wr(CFG_REG_BAR0, 0x80000000)]
        + probe(CFG_REG_BAR1)                       # I/O: skipped, no assignment
        + [wr(CFG_REG_BAR2, 0xFFFFFFFF), rd(CFG_REG_BAR2),
           wr(CFG_REG_BAR3, 0xFFFFFFFF), rd(CFG_REG_BAR3),
           wr(CFG_REG_BAR2, 0x80100000), wr(CFG_REG_BAR3, 0x00000000)]
        + probe(CFG_REG_BAR4)                       # unimplemented: skipped
        + probe(CFG_REG_BAR5) + [wr(CFG_REG_BAR5, 0x80200000)]
        + [CMD_TXN])
    assert_sequence(server.txns, golden, "B4 transaction sequence")

    assert snap["count"] == 3, (
        f"bar_count_o {snap['count']} != 3 (one 32-bit, one pair, one 32-bit; "
        "the I/O BAR and the unimplemented register consume no slot)")
    assert slot(snap, 0) == {"valid": 1, "is64": 0, "prefetch": 0,
                             "size": 256 * KB, "addr": 0x8000_0000}, slot(snap, 0)
    assert slot(snap, 1) == {"valid": 1, "is64": 1, "prefetch": 1,
                             "size": 1 * MB, "addr": 0x8010_0000}, slot(snap, 1)
    assert slot(snap, 2) == {"valid": 1, "is64": 0, "prefetch": 0,
                             "size": 128, "addr": 0x8020_0000}, slot(snap, 2)

    # Natural alignment, [PCI3] p.226 :11226 -- asserted as a property, not just
    # as three literal addresses.
    for index in range(snap["count"]):
        s = slot(snap, index)
        assert s["addr"] % s["size"] == 0, (
            f"BAR {index} at {s['addr']:#x} is not aligned to its size "
            f"{s['size']:#x} -- [PCI3] p.226 :11226")
    for index in range(snap["count"] - 1):
        a, b = slot(snap, index), slot(snap, index + 1)
        assert a["addr"] + a["size"] <= b["addr"], \
            f"BAR {index} overlaps BAR {index + 1}: {a} then {b}"


# ==========================================================================
# B5 -- EF4: all BARs unimplemented
# ==========================================================================
@cocotb.test()
async def b5_all_bars_unimplemented(dut):
    """A device with no BARs still enumerates, and is still enabled.

    !! EF4's TRAP. Asserting only bar_count_o == 0 would pass against a DEAD FSM,
    because bar_count_o is reset-low. So done, error AND the count are all
    asserted, and so is the Command write -- Bus Master Enable is meaningful even
    with no memory BAR, and SSE.5's invariant makes the Command write structurally
    the last transaction of every successful enumeration rather than a
    conditional one.
    """
    sock, server, dev, snap = await run_enum(dut, bar_device())

    assert snap["done"] == 1, f"enum_done_o low for a BAR-less device: {snap}"
    assert snap["error"] == 0, f"a BAR-less device is not an error: {snap}"
    assert snap["count"] == 0, f"bar_count_o {snap['count']} != 0"
    assert snap["valid"] == 0, f"bar_valid_o {snap['valid']:#08b} != 0"
    assert snap["io_mask"] == 0, f"io_bar_mask_o {snap['io_mask']:#08b} != 0"
    assert_descriptors(sock)

    golden = SCAN_TXNS + probe(CFG_REG_BAR0) + probe(CFG_REG_BAR1) \
        + probe(CFG_REG_BAR2) + probe(CFG_REG_BAR3) + probe(CFG_REG_BAR4) \
        + probe(CFG_REG_BAR5) + [CMD_TXN]
    assert_sequence(server.txns, golden, "B5 transaction sequence")

    # Proof this was NOT a dead FSM: 6 sizing writes, 6 readbacks, 1 Command
    # write actually happened, and the device really got enabled.
    assert dev.command == CMD_ENABLE_VALUE, \
        f"Command register {dev.command:#06x} -- a BAR-less device is still enabled"
    assert dev.mask_hits == 0, (
        "a write mask fired on a device with no implemented BAR -- the model is "
        "wrong, not the DUT")


# ==========================================================================
# B6 -- the I/O BAR is skipped AND logged
# ==========================================================================
@cocotb.test()
async def b6_io_bar_skipped_and_logged(dut):
    """An I/O BAR is probed, recognised, left unassigned, and reported.

    Skipping is safe only because Command bit 0 stays 0 (SSE.6): the device is
    never told to decode I/O space, so an unassigned I/O BAR is inert. Both
    halves are asserted -- the skip AND the log -- because a skip with no log is
    indistinguishable from not having looked.
    """
    dev = bar_device({
        CFG_REG_BAR0: BarSpec(BAR_IO, 256),
        CFG_REG_BAR3: BarSpec(BAR_IO, 64),
        CFG_REG_BAR4: BarSpec(BAR_MEM32, 4 * KB, prefetch=False),
    })
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_ok(snap)
    assert_descriptors(sock)

    golden = SCAN_TXNS + (
        probe(CFG_REG_BAR0)                              # I/O, skipped
        + probe(CFG_REG_BAR1) + probe(CFG_REG_BAR2)      # unimplemented
        + probe(CFG_REG_BAR3)                            # I/O, skipped
        + probe(CFG_REG_BAR4) + [wr(CFG_REG_BAR4, 0x80000000)]
        + probe(CFG_REG_BAR5)
        + [CMD_TXN])
    assert_sequence(server.txns, golden, "B6 transaction sequence")

    # LOGGED: bit k of io_bar_mask_o names candidate register 4 + k.
    expected_mask = (1 << (CFG_REG_BAR0 - CFG_REG_BAR0)) | \
                    (1 << (CFG_REG_BAR3 - CFG_REG_BAR0))
    assert snap["io_mask"] == expected_mask, (
        f"io_bar_mask_o {snap['io_mask']:#08b} != {expected_mask:#08b} -- "
        "registers 4 and 7 came back with bit 0 set")

    # SKIPPED: neither consumed a slot or a byte of the memory window.
    assert snap["count"] == 1, \
        f"bar_count_o {snap['count']} != 1 -- an I/O BAR consumed a slot"
    assert slot(snap, 0)["addr"] == MEM_BAR_BASE, (
        f"the memory BAR landed at {slot(snap, 0)['addr']:#x}, not at the base -- "
        "an I/O BAR consumed memory address space")
    assert dev.bar_written(CFG_REG_BAR0) == 0xFFFFFF00, (
        "register 4 holds something other than the sizing write, so an "
        "assignment was made to an I/O BAR")

    # Command bit 0 stays 0 -- that is what makes the skip inert.
    assert dev.command & 0x1 == 0, (
        f"Command {dev.command:#06x} has I/O Space Enable set, but no I/O BAR "
        "was ever assigned ([PCI3] Table 6-1 p.218 :10761)")


# ==========================================================================
# B7 -- EF6: a sub-128-byte MEMORY decode is a fault
# ==========================================================================
@cocotb.test()
async def b7_sub_128_byte_memory_decode_errors(dut):
    """A 16-byte memory BAR is legal PCI and illegal PCIe, so it faults.

    !! EF6's TRAP: the condition must be reached with a MEMORY BAR. An I/O BAR
    below 128 bytes is perfectly legal and must NOT error -- b6 uses a 64-byte
    one and expects success -- so a version of this test built on an I/O BAR
    would assert the opposite of the intended property.

    [PCI3] p.226 :11219 allows 16 bytes; [BASE] SS7.5.2.1 p.491-492 requires 128.
    PCIe is tighter and governs. This is also the check that kills the
    "64-bit pair decoded as two 32-bit BARs" mutation, by spec -- SSE.4.1.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 16, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev)

    assert_failed(snap, ENUM_ERR_BAR_SIZE)
    assert_descriptors(sock)

    # Faulted where it should: after reading register 4, before assigning it.
    golden = SCAN_TXNS + probe(CFG_REG_BAR0)
    assert_sequence(server.txns, golden,
                    "B7 must stop the instant the decode is untrustworthy")
    assert snap["count"] == 0, "a BAR was recorded despite the size fault"

    # ...and the readback really was 16 bytes' worth, not something else.
    assert dev.read(CFG_REG_BAR0) == 0xFFFFFFF0, (
        f"the model returned {dev.read(CFG_REG_BAR0):#010x}; this test needs "
        "0xFFFFFFF0, whose two's complement is 16 -- precisely PCI 3.0's minimum")


@cocotb.test()
async def b7b_128_bytes_exactly_is_accepted(dut):
    """The boundary from the other side: 128 bytes is legal, 16 is not.

    Without this, b7 would pass against a floor set anywhere from 32 to 2 GB.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 128, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev)
    assert_ok(snap, "128 bytes is exactly the [BASE] p.491 minimum: ")
    assert slot(snap, 0)["size"] == 128, slot(snap, 0)


# ==========================================================================
# B8 -- EF8: allocator exhaustion, by CODE
# ==========================================================================
@cocotb.test()
async def b8_allocator_exhaustion_errors(dut):
    """A 256-byte window cannot hold a 4 KB BAR, and says so specifically.

    !! EF8's TRAP: assert the CODE, not merely enum_error_o. A wrapping allocator
    asserts no error at all, so enum_error_o == 1 is the right assertion for the
    FIXED design and proves nothing about WHICH fault fired. ENUM_ERR_BAR_WINDOW
    distinguishes exhaustion from every other way this could stop.
    """
    view = Sub(dut, "x_")
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 4 * KB, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev, view=view)

    assert_failed(snap, ENUM_ERR_BAR_WINDOW)
    assert snap["count"] == 0, "a BAR was recorded despite exhaustion"
    golden = SCAN_TXNS + probe(CFG_REG_BAR0)
    assert_sequence(server.txns, golden, "B8 must stop before assigning")

    # NOT a wraparound: nothing was written to the BAR beyond the sizing probe.
    assert dev.bar_written(CFG_REG_BAR0) == 0xFFFFF000, (
        f"register 4 holds {dev.bar_written(CFG_REG_BAR0):#010x} -- an address "
        "was assigned from a wrapped cursor, which is the silent-overlap failure "
        "SSE.7.1 forbids")


@cocotb.test()
async def b8b_a_bar_that_exactly_fills_the_window_is_accepted(dut):
    """The boundary from the other side: 256 bytes fits a 256-byte window.

    Without this, b8 would pass against an allocator that rejected everything.
    """
    view = Sub(dut, "x_")
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 256, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev, view=view)
    assert_ok(snap, "a BAR exactly filling the window must fit: ")
    assert slot(snap, 0) == {"valid": 1, "is64": 0, "prefetch": 0,
                             "size": 256, "addr": 0x8000_0000}, slot(snap, 0)


# ==========================================================================
# B9 -- ⭐ EF5 / P-CMD-LAST, asserted ON THE WIRE
# ==========================================================================
@cocotb.test()
async def b9_command_write_is_the_last_transaction(dut):
    """No CfgWr0 to register 1 appears before the final one, and it is last.

    !! EF5's TRAP: this must be a WIRE property, not "the FSM was in S_CMD last".
    A state-based assertion cannot fail for the mutation it exists to catch --
    "Command write moved before sizing completes" -- because the mutated FSM
    would still be in S_CMD when it wrote. So the whole emitted sequence is
    scanned instead.

    Uses a device with a 64-bit pair and an I/O BAR so that the run contains
    every kind of intermediate transaction the invariant has to survive.
    """
    dev = bar_device({
        CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True),
        CFG_REG_BAR2: BarSpec(BAR_IO, 128),
        CFG_REG_BAR3: BarSpec(BAR_MEM32, 8 * KB, prefetch=False),
    })
    sock, server, dev, snap = await run_enum(dut, dev)
    assert_ok(snap)

    txns = nonempty(server.txns, "P-CMD-LAST over an empty sequence")
    hits = [i for i, t in enumerate(txns)
            if t.write and t.reg == CFG_REG_COMMAND_STATUS]
    assert len(hits) == 1, (
        f"P-CMD-LAST: {len(hits)} writes to register 1, expected exactly 1 "
        f"(at indices {hits}):\n  " + "\n  ".join(repr(t) for t in txns))
    assert hits[0] == len(txns) - 1, (
        f"P-CMD-LAST: the Command write is at index {hits[0]} of "
        f"{len(txns)} transactions, so {len(txns) - 1 - hits[0]} configuration "
        "request(s) followed it. It must be the LAST transaction of "
        f"enumeration (SSE.5):\n  " + "\n  ".join(repr(t) for t in txns))

    # ...and every BAR-phase transaction really did precede it.
    assert txns[hits[0]] == CMD_TXN, \
        f"the final transaction is {txns[hits[0]]!r}, not the SSE.8 B15 golden"
    assert snap["count"] == 2, f"bar_count_o {snap['count']} != 2"

    # Nothing else touched register 1 either -- not even a read.
    assert not [t for t in txns[:-1] if t.reg == CFG_REG_COMMAND_STATUS], \
        "register 1 was accessed before the final Command write"


# ==========================================================================
# B10 -- P-NO-ROM
# ==========================================================================
@cocotb.test()
async def b10_expansion_rom_is_never_touched(dut):
    """No CfgRd0 and no CfgWr0 to register 12 (offset 30h) ever appears.

    The Expansion ROM BAR "functions exactly like a 32-bit Base Address register
    except that the encoding (and usage) of the bottom bits is different"
    ([PCI3] p.227 :11290) and takes the same all-ones sizing procedure (p.228
    :11307).  That near-identity is exactly why the exclusion is asserted rather
    than assumed: its bit 0 is Expansion ROM Enable, not a Memory Space
    Indicator (p.228 :11318, :11323), so feeding it to the SSE.2 decoder would
    give a WRONG answer rather than a harmless one.  SSE.7.3.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(dut, dev)
    assert_ok(snap)

    txns = nonempty(server.txns, "P-NO-ROM over an empty sequence")
    stray = [t for t in txns if t.reg == CFG_REG_EXPANSION_ROM]
    assert not stray, (
        f"P-NO-ROM: register {CFG_REG_EXPANSION_ROM} (offset 30h, the Expansion "
        f"ROM Base Address register) was accessed: {stray}")

    # Stronger, and what actually pins the window: NOTHING outside registers
    # 0, 1, 3 and 4..9 is ever addressed.
    allowed = {CFG_REG_VENDOR_DEVICE, CFG_REG_COMMAND_STATUS,
               CFG_REG_CACHE_HEADER} | set(range(CFG_REG_BAR0, CFG_REG_BAR5 + 1))
    outside = sorted({t.reg for t in txns} - allowed)
    assert not outside, (
        f"registers outside the enumeration window were addressed: {outside}. "
        "The candidate window is 4..9 and nothing else (SSE.7.3)")


# ==========================================================================
# B11..B14 -- every fault outcome, mid BAR phase
# ==========================================================================
@cocotb.test()
async def b11_ur_mid_bar_phase_errors(dut):
    """A UR to a BAR readback is a fault: this device already answered its probe.

    That is the whole reason pcie_enum_bar's outcome policy is FLAT while
    pcie_enum_scan's is phase-dependent -- the same wire event, TXN_UR, is
    "nothing here to enumerate" on the Vendor-ID probe and a fault here.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 16 * KB)})
    sock, server, dev, snap = await run_enum(
        dut, dev, faults={(CFG_REG_BAR0, 1): CPL_UR})   # the readback

    assert_failed(snap, ENUM_ERR_UR_POST_PROBE)
    assert server.logical((CFG_REG_BAR0, 1)), \
        "the injected fault was never reached -- this test is vacuous"
    assert_sequence(server.txns, SCAN_TXNS + probe(CFG_REG_BAR0),
                    "B11 must stop at the faulting transaction")
    assert int(dut.err_credit_blocked_o.value) == 0, \
        "err_credit_blocked_o annotated a UR; it is timeout-only"


@cocotb.test()
async def b12_ca_mid_bar_phase_errors(dut):
    """A Completer Abort during the assignment write is a fault."""
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 16 * KB)})
    sock, server, dev, snap = await run_enum(
        dut, dev, faults={(CFG_REG_BAR0, 2): CPL_CA})   # the assignment write

    assert_failed(snap, ENUM_ERR_CA)
    assert server.logical((CFG_REG_BAR0, 2)), \
        "the injected fault was never reached -- this test is vacuous"
    assert snap["count"] == 0, (
        "a BAR was recorded although the device aborted the assignment write. "
        "bar_valid_o means PROGRAMMED, and this one was not")
    assert_sequence(server.txns,
                    SCAN_TXNS + probe(CFG_REG_BAR0) + [wr(CFG_REG_BAR0, 0x80000000)],
                    "B12 must stop at the aborted assignment")


@cocotb.test()
async def b13_crs_exhausted_mid_bar_phase_errors(dut):
    """CRS_RETRY_MAX + 1 consecutive CRS answers to a sizing write is a fault."""
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 16 * KB)})
    sock, server, dev, snap = await run_enum(
        dut, dev, crs={(CFG_REG_BAR0, 0): CRS_RETRY_MAX + 1})

    assert_failed(snap, ENUM_ERR_CRS_EXHAUSTED)
    # The retries really happened: the sizing write was re-issued as a new
    # request each time (Base 2.1 SS2.3.2 p.121).
    attempts = [t for t in server.txns
                if t.write and t.reg == CFG_REG_BAR0 and t.payload == 0xFFFFFFFF]
    expect_count(attempts, CRS_RETRY_MAX + 1,
                 "B13 sizing-write attempts before exhaustion")


@cocotb.test()
async def b14_crs_then_success_mid_bar_phase(dut):
    """A CRS that clears is not a fault -- the retry completes the enumeration.

    The counterpart b13 needs: without it, b13 would pass against an FSM that
    treated the FIRST CRS as fatal.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(
        dut, dev, crs={(CFG_REG_BAR1, 1): 2})    # the upper-half readback, twice

    assert_ok(snap)
    assert slot(snap, 0) == {"valid": 1, "is64": 1, "prefetch": 1,
                             "size": 16 * KB, "addr": MEM_BAR_BASE}, slot(snap, 0)
    reads = [t for t in server.txns if not t.write and t.reg == CFG_REG_BAR1]
    expect_count(reads, 3, "B14 upper-half readback attempts (2 CRS then SC)")


# ==========================================================================
# B15..B16 -- ⭐ SSE.9.1: the settle()-first blind spot, third occurrence
#
# The pattern, twice found and now designed against: a test that calls settle()
# before injecting an event gives the DUT a quiet window it would not have in
# traffic, and hides survivors that depend on the event landing MID-SEQUENCE
# (2b-1 e9/e10; 2b-2 socket invariant 2).
#
# !! NEITHER TEST BELOW CALLS settle() BEFORE ITS EVENT. Both fire at the
# earliest legal moment, and both were chosen because they straddle an awkward
# boundary rather than because they were convenient.
# ==========================================================================
@cocotb.test()
async def b15_timeout_on_the_upper_half_no_settle(dut):
    """A timeout on B4 -- mid-pair, with no quiet window first.

    The FSM has consumed candidate index N and has NOT yet committed N+2: it
    holds a masked lower half in enc_lo_r and nothing else. SSE.9.1's first
    predicted boundary.

    The strobe is fired the moment the socket has a request to time out, from a
    coroutine started BEFORE the scan does -- there is no settle() anywhere ahead
    of it.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, device = await init(
        dut, device=dev, silent={(CFG_REG_BAR1, 1)})     # upper-half readback

    fired = []

    async def strike():
        # Wait only for the target request to exist, then strobe immediately.
        for _ in range(20000):
            await RisingEdge(dut.clk_i)
            if server.silent_hits:
                await sock.fire_timeout(sock.requests[-1].tag)
                fired.append(True)
                return
        raise AssertionError("the silent request never appeared")

    cocotb.start_soon(strike())
    await start_scan(dut)
    await wait_enum(dut)
    snap = await status(dut)

    assert fired, "the timeout strobe never fired -- this test is vacuous"
    assert server.silent_hits == 1, \
        f"the silent arm fired {server.silent_hits}x, expected once"
    assert_failed(snap, ENUM_ERR_TIMEOUT)
    assert snap["count"] == 0, "a BAR was recorded from a half-probed pair"
    assert_sequence(server.txns, SCAN_TXNS + probe(CFG_REG_BAR0)
                    + [wr(CFG_REG_BAR1, 0xFFFFFFFF), rd(CFG_REG_BAR1)],
                    "B15 must stop at the timed-out upper-half readback")
    # No reissue: a timed-out transaction is terminal, not retried.
    reads = [t for t in server.txns if not t.write and t.reg == CFG_REG_BAR1]
    expect_count(reads, 1, "B15 upper-half readback attempts")


@cocotb.test()
async def b16_late_completion_during_assignment_no_settle(dut):
    """A stale completion arriving mid-assignment must not move the status surface.

    SSE.9.1's second predicted boundary: the assignment write is the only phase
    where the FSM holds a decoded size AND an allocator cursor. The extra
    completion is injected for a tag the DUT is not waiting on, with no settle()
    before it.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, device = await init(dut, device=dev)

    injected = []

    async def interfere():
        # The moment the low-half assignment write (occurrence 2 of register 4)
        # has been observed, deliver a duplicate completion for it.
        for _ in range(20000):
            await RisingEdge(dut.clk_i)
            hits = [t for t in server.txns
                    if t.write and t.reg == CFG_REG_BAR0 and t.payload == 0x80000000]
            if hits:
                await sock.complete(tag=sock.requests[-1].tag, status=CPL_SC)
                injected.append(True)
                return
        raise AssertionError("the assignment write never appeared")

    cocotb.start_soon(interfere())
    await start_scan(dut)
    await wait_enum(dut)
    snap = await status(dut)

    assert injected, "no late completion was injected -- this test is vacuous"
    assert_ok(snap, "a duplicate completion derailed enumeration: ")
    assert slot(snap, 0) == {"valid": 1, "is64": 1, "prefetch": 1,
                             "size": 16 * KB, "addr": MEM_BAR_BASE}, slot(snap, 0)
    assert snap["count"] == 1, f"bar_count_o {snap['count']} != 1"

    # The status surface did not move afterwards either.
    await settle(dut)
    later = await status(dut)
    assert later == snap, \
        f"the status surface moved after the late completion:\n  {snap}\n  {later}"


# ==========================================================================
# B17 -- status stability
# ==========================================================================
@cocotb.test()
async def b17_status_is_stable_after_enum_done(dut):
    """Every output holds from enum_done_o until reset, and no traffic follows."""
    dev = bar_device({
        CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True),
        CFG_REG_BAR2: BarSpec(BAR_IO, 64),
        CFG_REG_BAR4: BarSpec(BAR_MEM32, 512, prefetch=False),
    })
    sock, server, dev, first = await run_enum(dut, dev)
    assert_ok(first)
    packets = len(nonempty(sock.requests, "nothing was emitted"))

    await settle(dut, 200)
    later = await status(dut)
    assert later == first, (
        f"the status surface moved after enum_done_o:\n  was  {first}\n"
        f"  now  {later}")
    assert len(sock.requests) == packets, (
        f"{len(sock.requests) - packets} further configuration request(s) were "
        "emitted after enum_done_o -- enumeration is single-shot")
    assert dev.command == CMD_ENABLE_VALUE, \
        "the Command register changed after enumeration finished"


# ==========================================================================
# B18..B20 -- the decode faults
# ==========================================================================
async def malformed_run(dut, reg, value):
    """Enumerate a device one of whose BAR registers answers a fixed illegal value.

    ConfigDevice's `raw` mechanism is used rather than a BarSpec, because BarSpec
    deliberately CANNOT build an illegal BAR -- it validates its size and has no
    reserved kind. A malformed register must also IGNORE WRITES; see the note on
    ConfigDevice.__init__ for what happens when it does not.
    """
    dev = bar_device(raw={reg: value})
    sock, server, dev, snap = await run_enum(dut, dev)
    # Premise, asserted: the FSM really did see the illegal value, and its
    # all-ones write really was absorbed rather than changing the answer.
    assert dev.raw_reads >= 1, \
        f"register {reg} was never read -- this test is vacuous"
    assert dev.raw_writes_discarded >= 1, (
        f"no write to register {reg} was absorbed, so the all-ones write would "
        "have replaced the injected value")
    return sock, server, dev, snap


@cocotb.test()
async def b18a_reserved_bar_type_01_errors(dut):
    """Type field 01 is Reserved, and faults rather than being guessed at.

    Table 6-4 p.226 :11207 defines all four rows. Footnote 46 (:11243) records
    that 01 formerly meant "below 1 MB" and that software "should recognize this
    encoding and handle appropriately" -- it is a LEGACY encoding, not a free
    slot. It cannot legitimately appear on a PCI Express endpoint, and treating
    an unknown type as 32-bit would silently mis-size the device.
    """
    sock, server, dev, snap = await malformed_run(
        dut, CFG_REG_BAR0, 0xFFFFC000 | (0b01 << 1))

    assert_failed(snap, ENUM_ERR_BAR_TYPE)
    assert snap["count"] == 0, "a BAR with a reserved type was recorded"
    assert snap["io_mask"] == 0, (
        "the register was classified as an I/O BAR, not as a reserved type -- "
        "check bit 0 of the injected value")
    assert_sequence(server.txns, SCAN_TXNS + probe(CFG_REG_BAR0),
                    "B18a must stop at the offending readback")


@cocotb.test()
async def b18b_reserved_bar_type_11_errors(dut):
    """Type field 11 is Reserved in exactly the same way as 01.

    Split from b18a rather than looped: two encodings in one test would need a
    mid-test reset with a socket and a server still running against the old one,
    and a bench that re-resets a shared DUT mid-test is a source of failures that
    look like DUT faults.
    """
    sock, server, dev, snap = await malformed_run(
        dut, CFG_REG_BAR0, 0xFFFFC000 | (0b11 << 1))

    assert_failed(snap, ENUM_ERR_BAR_TYPE)
    assert snap["count"] == 0, "a BAR with a reserved type was recorded"
    assert snap["io_mask"] == 0, "the register was classified as an I/O BAR"


@cocotb.test()
async def b19_64bit_type_in_the_last_register_errors(dut):
    """A 64-bit BAR declared at register 9 has nothing to pair with.

    Offset 28h is the Cardbus CIS Pointer, not a BAR ([BASE] Figure 7-5 p.491),
    so a device declaring a pair at register 9 is malformed -- and honouring it
    would drive an all-ones write clean out of the candidate window, which is the
    same class of damage P-NO-ROM exists to prevent.
    """
    sock, server, dev, snap = await malformed_run(dut, CFG_REG_BAR5, 0xFFFFC00C)

    assert_failed(snap, ENUM_ERR_BAR_TYPE)
    assert snap["count"] == 0, "a pair with no upper half was recorded"
    # Nothing was written past the window.
    txns = nonempty(server.txns, "B19 emitted nothing")
    beyond = [t for t in txns if t.reg > CFG_REG_BAR5
              and t.reg != CFG_REG_COMMAND_STATUS]
    assert not beyond, (
        f"the FSM addressed a register past the candidate window: {beyond}")
    assert txns[-1] == rd(CFG_REG_BAR5), \
        f"B19 stopped at {txns[-1]!r}, not at the register-9 readback"


@cocotb.test()
async def b20_non_power_of_two_size_errors(dut):
    """A readback whose two's complement is not a power of two is untrustworthy.

    [PCI3] p.226 :11226: "all address spaces used are a power of two in size and
    are naturally aligned." A non-power-of-two decode makes the allocator's
    ~(size-1) alignment mask meaningless, so it shares ENUM_ERR_BAR_SIZE with the
    128-byte floor: both mean THE DECODE ITSELF IS WRONG.
    """
    # ~0xFFFF0F00 + 1 = 0x0000F100 -- 61696 bytes: above the 128-byte floor, and
    # not a power of two. Only a malformed device can produce it, which is why it
    # is injected rather than built.
    assert (~0xFFFF0F00 + 1) & 0xFFFFFFFF == 0xF100, "test premise arithmetic"
    assert 0xF100 > 128, "the premise must clear the floor, or b7 is what fires"
    assert 0xF100 & (0xF100 - 1) != 0, "the premise must NOT be a power of two"

    sock, server, dev, snap = await malformed_run(dut, CFG_REG_BAR0, 0xFFFF0F00)

    assert_failed(snap, ENUM_ERR_BAR_SIZE)
    assert snap["count"] == 0, "a BAR with a non-power-of-two size was recorded"


@cocotb.test()
async def b21_32bit_bar_above_4gb_errors(dut):
    """A 32-bit BAR cannot hold an address MEM_BAR_BASE places above 4 GB.

    Beyond SSE's named fault set; argued in pcie_enum_bar's header under
    SS ONE FAULT SSE DOES NOT NAME. The alternative to faulting is truncating the
    upper half, which produces a BAR overlapping whatever sits low in memory --
    the silent overlap SSE.7.1 forbids, arriving by a different route.
    """
    view = Sub(dut, "h_")
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 4 * KB, prefetch=False)})
    sock, server, dev, snap = await run_enum(dut, dev, view=view)

    assert_failed(snap, ENUM_ERR_BAR_ADDR32)
    assert snap["count"] == 0, "a BAR was recorded at an address it cannot hold"
    assert dev.bar_written(CFG_REG_BAR0) == 0xFFFFF000, (
        f"register 4 holds {dev.bar_written(CFG_REG_BAR0):#010x} -- a truncated "
        "address was assigned")


@cocotb.test()
async def b21b_a_64bit_bar_above_4gb_is_accepted(dut):
    """The counterpart: the same window is perfectly fine for a 64-bit BAR.

    Without this, b21 would pass against an FSM that rejected every BAR whenever
    MEM_BAR_BASE sat high, which is not the property being claimed.
    """
    view = Sub(dut, "h_")
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 4 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(dut, dev, view=view)

    assert_ok(snap, "a 64-bit BAR above 4 GB is legal: ")
    assert slot(snap, 0) == {"valid": 1, "is64": 1, "prefetch": 1,
                             "size": 4 * KB, "addr": 0x0000_0004_0000_0000}, \
        slot(snap, 0)
    # The high half really was written -- the mutation "upper half of a 64-bit
    # assignment never written" cannot survive an address whose upper half is
    # non-zero.
    assert dev.bar_written(CFG_REG_BAR1) == 0x00000004, (
        f"BAR1 holds {dev.bar_written(CFG_REG_BAR1):#010x}, not the address's "
        "upper 32 bits (0x00000004)")


# ==========================================================================
# B22..B23 -- the two devices that get no BAR phase at all
# ==========================================================================
@cocotb.test()
async def b22_absent_device_emits_no_bar_traffic(dut):
    """A UR to the Vendor-ID probe ends enumeration with no BAR transaction.

    enum_done_o still asserts: the sequence FINISHED, and there was nothing to
    configure. A consumer wanting a configured device asks for
    enum_done_o && device_present_o && !unsupported_device_o, exactly as
    pcie_enum_scan documents for scan_done_o.

    !! AND NO COMMAND WRITE EITHER. There is no configured device to enable, so
    S_CHECK goes straight to S_DONE.
    """
    dev = bar_device()
    sock, server, dev, snap = await run_enum(
        dut, dev, faults={(CFG_REG_VENDOR_DEVICE, 0): CPL_UR})

    assert snap["done"] == 1, f"enum_done_o low for an absent device: {snap}"
    assert snap["error"] == 0, "absence is not an error"
    assert snap["count"] == 0, f"bar_count_o {snap['count']} != 0"
    assert int(dut.device_present_o.value) == 0, "device_present_o should be low"
    assert_sequence(server.txns, [rd(CFG_REG_VENDOR_DEVICE)],
                    "B22: an absent device gets exactly one transaction")


@cocotb.test()
async def b23_unsupported_device_emits_no_bar_traffic(dut):
    """A Type 1 header ends enumeration with no BAR transaction and no error.

    A bridge answered correctly; walking it is Stage D. scan_done_o is asserted
    for S_UNSUPPORTED as well as S_DONE, so bar_start_i DOES rise here -- the
    BAR phase is entered and declines in S_CHECK. That is the path this test
    covers, and it is the reason S_CHECK looks at unsupported_device_i at all.
    """
    dev = bar_device(header_type=HDR_TYPE1)
    sock, server, dev, snap = await run_enum(dut, dev)

    assert snap["done"] == 1, f"enum_done_o low for a Type 1 device: {snap}"
    assert snap["error"] == 0, "a bridge that answered correctly is not an error"
    assert snap["count"] == 0, f"bar_count_o {snap['count']} != 0"
    assert int(dut.unsupported_device_o.value) == 1, \
        "unsupported_device_o should be high for a Type 1 header"
    assert_sequence(server.txns, SCAN_TXNS,
                    "B23: a Type 1 device gets the two scan transactions only")


# ==========================================================================
# B24 -- ⭐ the handoff: exactly one stage drives the command port
# ==========================================================================
@cocotb.test()
async def b24_command_write_byte_enables_prove_one_stage_live(dut):
    """first_be == 0011 on the Command write, which only a SELECT can produce.

    ⭐ THIS IS THE TEST FOR THE MUX MUTATION, AND THE MECHANISM IS WORTH STATING.
    pcie_enum_scan drives cmd_first_be_o as a HARD CONSTANT 1111
    (pcie_enum_scan.sv:271), not qualified by state at all. Six of the seven
    command signals are therefore immune to the difference between selecting one
    stage and MERGING both -- scan drives 0 or a matching constant on all of
    them, so an OR is a no-op:

      cmd_valid / cmd_reg_num  scan drives 0 in every terminal state
      cmd_write / cmd_wdata    scan drives a hard 0
      cmd_ext_reg              both stages drive the same constant

    cmd_first_be is the exception. A merged mux forces 1111 onto every BAR-phase
    transaction; fourteen of the fifteen are 1111 anyway, and THE COMMAND WRITE
    IS THE ONE THAT IS NOT. So this single byte-enable field is the only
    observable consequence the two constructions do not share, which makes it
    the proof rather than a nearby detail. See pcie_enum_top,
    SS PROVING EXACTLY ONE STAGE IS LIVE.

    0011 is required independently anyway: the Command register is the low half
    of the Dword at 04h and the high half is Status, whose write-1-to-clear bits
    a whole-Dword write would destroy ([BASE] Figure 7-5 p.491, SSE.6).
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(dut, dev)
    assert_ok(snap)

    txns = nonempty(server.txns, "the handoff proof over an empty sequence")
    cmd = expect_count(
        [t for t in txns if t.write and t.reg == CFG_REG_COMMAND_STATUS],
        1, "B24 Command writes")[0]
    assert cmd.first_be == CFG_BE_LOWER_HALF, (
        f"the Command write carried first_be={cmd.first_be:#06b}, expected "
        f"{CFG_BE_LOWER_HALF:#06b}. 1111 is what pcie_enum_scan drives "
        "unconditionally, so seeing it here means the handoff mux MERGED the two "
        "stages' command ports instead of SELECTING one -- and it would also "
        "clear the Status register's write-1-to-clear bits")
    assert cmd.payload == CMD_ENABLE_VALUE, \
        f"the Command write carried {cmd.payload:#010x}, not {CMD_ENABLE_VALUE:#010x}"

    # The scan's own two transactions are 1111, which is what makes the contrast
    # meaningful rather than a coincidence of this device's layout.
    for txn in txns[:2]:
        assert txn.first_be == CFG_BE_DWORD, \
            f"a scan transaction carried first_be={txn.first_be:#06b}"

    # And the observable really is unique: every OTHER BAR-phase transaction is
    # 1111, so no other field could have caught a merge.
    others = [t for t in txns[2:] if t.reg != CFG_REG_COMMAND_STATUS]
    assert others, "no BAR-phase transactions to compare against"
    assert all(t.first_be == CFG_BE_DWORD for t in others), (
        "a BAR-phase transaction other than the Command write used a byte "
        "enable that is not 1111, which would weaken this test's claim to be "
        "the unique observable")


# ==========================================================================
# B26..B27 -- ⭐ enum_done_o means the device is CONFIGURED, not "asked to be"
#
# !! BOTH TESTS EXIST BECAUSE A MUTATION SURVIVED, AND THE SURVIVOR ANALYSIS IS
# THE INTERESTING PART.
#
# The mutation was "enum_done_o asserts before the Command write completes" --
# S_CMD_WR jumping straight to S_DONE on cmd_ready_i instead of waiting for
# S_CMD_WR_RSP. It survived all 29 tests. Applying the reach-the-condition rule:
# write down the mutated branch's CONDITION first, then check what reaches it.
#
#   condition: the interval between the Command write being ACCEPTED by
#              pcie_cfg_txn and its COMPLETION coming back.
#
# Every test reached the mutated LINE -- all of them issue a Command write. Not
# one reached the condition, because all of them called wait_enum(), which polls
# until done||error and then snapshots. The mutant asserts done a few cycles
# early and the snapshot is identical, because bar_count_o and every slot were
# already committed before S_CMD_WR was entered at all.
#
# So the gap was never "an assertion was too weak". It was that no test made the
# Command write's OUTCOME matter. b26 makes it matter by failing it; b27 makes
# the timing itself observable by withholding the completion.
# ==========================================================================
@cocotb.test()
async def b26_a_failed_command_write_is_an_error_not_done(dut):
    """A UR to the Command write must error -- the device was never enabled.

    This is the one transaction whose failure the mutant reports as SUCCESS, and
    it is the worst possible one to get wrong: enum_done_o would be telling an
    integrator that Memory Space Enable and Bus Master Enable are set on a device
    that rejected the write, so every later MMIO and every DMA would be
    unclaimed.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, dev, snap = await run_enum(
        dut, dev, faults={(CFG_REG_COMMAND_STATUS, 0): CPL_UR})

    assert server.logical((CFG_REG_COMMAND_STATUS, 0)), \
        "the Command write never happened -- this test is vacuous"
    assert_failed(snap, ENUM_ERR_UR_POST_PROBE)
    assert dev.command != CMD_ENABLE_VALUE, (
        "the model recorded the Command write although the completer rejected "
        "it -- the bench, not the DUT, is wrong")

    # The BAR itself was still sized and assigned; only the enable failed. That
    # is worth asserting: the error must not be mistaken for an earlier fault.
    assert_sequence(server.txns, SCAN_TXNS + [
        wr(CFG_REG_BAR0, 0xFFFFFFFF), rd(CFG_REG_BAR0),
        wr(CFG_REG_BAR1, 0xFFFFFFFF), rd(CFG_REG_BAR1),
        wr(CFG_REG_BAR0, 0x80000000), wr(CFG_REG_BAR1, 0x00000000),
    ] + probe(CFG_REG_BAR2) + probe(CFG_REG_BAR3) + probe(CFG_REG_BAR4)
      + probe(CFG_REG_BAR5) + [CMD_TXN],
        "B26 must fail at the Command write and nowhere earlier")


@cocotb.test()
async def b27_done_waits_for_the_command_write_to_complete(dut):
    """While the Command write is outstanding, the FSM is BUSY and not done.

    The timing property directly, rather than via an outcome. The completer is
    told to answer nothing at all, so the write sits outstanding for as long as
    the test cares to look; enum_done_o must stay low throughout. Then the
    completion timeout resolves it -- as an ERROR, because a device that never
    answered the enable was never enabled.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM32, 4 * KB, prefetch=False)})
    sock, server, device = await init(
        dut, device=dev, silent={(CFG_REG_COMMAND_STATUS, 0)})
    await start_scan(dut)

    # Wait for the Command write to be issued and left unanswered.
    for _ in range(20000):
        await RisingEdge(dut.clk_i)
        if server.silent_hits:
            break
    else:
        raise AssertionError("the Command write was never issued")

    await settle(dut, 200)
    await ReadOnly()
    done, busy, error = (int(dut.enum_done_o.value), int(dut.bar_busy_o.value),
                         int(dut.enum_error_o.value))
    await RisingEdge(dut.clk_i)

    assert done == 0, (
        "enum_done_o asserted while the Command write was still outstanding. "
        "enum_done_o means the device IS configured, not that it was asked to "
        "be -- the completer has not answered the enable write")
    assert busy == 1, "bar_busy_o low with a transaction outstanding"
    assert error == 0, "an unanswered write is not yet an error"

    # Resolve it the only way the stack can: the completion timeout.
    await sock.fire_timeout(sock.requests[-1].tag)
    await wait_enum(dut)
    snap = await status(dut)
    assert_failed(snap, ENUM_ERR_TIMEOUT)


# ==========================================================================
# B25 -- the enable is real
# ==========================================================================
@cocotb.test()
async def b25_bar_enable_low_emits_no_bar_traffic(dut):
    """With bar_enable_i low the scan runs and the BAR phase does not.

    This is the property the two scan targets depend on: they tie bar_enable_i
    low precisely so their transaction-count assertions stay theirs. Asserting it
    HERE rather than only there means a regression shows up in the target that
    owns the signal.
    """
    dev = bar_device({CFG_REG_BAR0: BarSpec(BAR_MEM64, 16 * KB, prefetch=True)})
    sock, server, device = await init(dut, device=dev, bar_enable=0)
    await start_scan(dut)

    for _ in range(4000):
        await ReadOnly()
        done = int(dut.scan_done_o.value)
        await RisingEdge(dut.clk_i)
        if done:
            break
    else:
        raise AssertionError("the scan never completed")

    await settle(dut, 300)
    await ReadOnly()
    enum_done = int(dut.enum_done_o.value)
    busy = int(dut.bar_busy_o.value)
    error = int(dut.enum_error_o.value)
    await RisingEdge(dut.clk_i)

    assert_sequence(server.txns, SCAN_TXNS,
                    "B25: with the BAR phase disabled only the scan transacts")
    assert enum_done == 0, "enum_done_o asserted with bar_enable_i low"
    assert busy == 0, "bar_busy_o asserted with bar_enable_i low"
    assert error == 0, "enum_error_o asserted with bar_enable_i low"
    assert int(dut.scan_done_o.value) == 1, "the scan itself must still complete"
