"""Stage D acceptance -- one bridge level enumerated end to end (B1..B5).

    scan (Type 1 verdict) -> enum_bus (18h, Type 0) -> scan2 (CFG1 probe)
    -> bar2 (CFG1 sizing/assignment) -> Command enable (CFG1, last)
    ... against the spec-golden bridge + device pair, every emitted TLP
    asserted IN ORDER against goldens pinned before this RTL ran.

The predicted sequence is docs/predictions/SPEC_PREDICTIONS_STAGE_D.md SS5.4: transactions
1-3 are Type 0 (the bridge is on the local bus -- including the 18h write,
Trap C), everything from the first secondary-bus probe on is Type 1.  The
ordering claim (F3.2, the 18h write precedes the first CFG1) is asserted
explicitly AND discriminated by the stalled-write run (Trap D): the
bridge/device latencies are non-zero and unequal, and B4 stalls the write's
completion long enough that a wrongly-ordered implementation would already
have emitted the probe.

!! P5.1/P5.7 scope: the ordering assertions here are the acceptance
criterion for THIS sequencer, not a spec check -- a legal depth-first
enumerator (provisional Subordinate, descend, rewrite) would violate them.

!! Trap B: no routing assertion below leans on a completion's Completer ID
-- it is 0000h at BOTH Functions through the whole probe phase (P5.6, and
the model implements the capture faithfully).  Routing is proven from the
REQUEST side: dw0[4:0] and the DW2 bus field, which the P5.2 value table
forces apart (buses 1/5/9, four pairwise-distinct IDs).

Spec cited (read, not assumed):
  Type 0 vs Type 1 encodings ...... PCIe Base 2.1 Table 2-3 p.58 (one bit)
  bridge routing / transform ...... PCIe Base 2.1 SS7.3.3 p.481
  originator rule ................. [PCI30] SS3.2.2.3.x p.49
  Type 1 header 18h Dword ......... PCIe Base 2.1 SS7.5.3 Fig 7-6 p.492
  Sec Latency Timer RO 00h ........ PCIe Base 2.1 SS7.5.3.3 p.493 (P4.2)
  two BARs in a Type 1 header ..... PCIe Base 2.1 SS7.5.3.1 p.493 (P4.7)
  CRS at both points .............. PCIe Base 2.1 SS2.3.1 p.113, SS2.3.2 p.121
  minimum FC / drip ............... PCIe Base 2.1 Table 2-37 p.137-138
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

from enum_tb_common import (
    BAR_MEM64, BAR_SLOTS, BRIDGE_BDF, BRIDGE_DEVICE, BRIDGE_VENDOR,
    BUS_NUM_WDATA, CLK_NS, CMD_ENABLE_VALUE, DEVICE, MEM_BAR_BASE, RID,
    SCAN_BUS, SEC_BUS, SEC_DEV_BDF, SEC_DEV_DEVICE, SEC_DEV_VENDOR, VENDOR,
    CFG_BE_DWORD, CFG_BE_LOWER_HALF, CFG_REG_BAR0, CFG_REG_BUS_NUMBER,
    CFG_REG_COMMAND_STATUS, CFG_REG_VENDOR_DEVICE, CFG_REG_CACHE_HEADER,
    TYPE_CFG0, TYPE_CFG1,
    BarSpec, BridgedCompleter, BridgedTopology, ConfigDevice, CreditDrip, Mon,
    assert_cfg_tlp_on_wire, assert_sequence, err_name, expect_count, nonempty,
    cfg_wire_dw0, cfg_wire_dw1, cfg_wire_dw2, set_credits,
)

KB = 1024
MASK64 = (1 << 64) - 1

ACCEPT_BAR_SIZE = 16 * KB       # same NVMe-like shape as the Stage C headline
ACCEPT_BAR_ADDR = MEM_BAR_BASE


def acceptance_topology(**kwargs):
    """The P5.2 topology: bridge 0x1AF4/0x1100 at 01:00.0, device
    0x15B3/0x1017 at 05:00.0 with a 16 KB 64-bit prefetchable pair."""
    device = ConfigDevice(
        bars={CFG_REG_BAR0: BarSpec(BAR_MEM64, ACCEPT_BAR_SIZE, prefetch=True)},
        vendor=SEC_DEV_VENDOR, device=SEC_DEV_DEVICE)
    return BridgedTopology(device=device, **kwargs)


# ⭐ THE SS5.4 SEQUENCE, HAND-TRANSCRIBED AND PINNED BEFORE THE RTL RAN.
# (type1, bus, write, reg_num, first_be, payload).  Deliberately NOT
# generated from a model of the FSMs: these are the numbers in the document.
#   1-2  bridge probe          Type 0, bus 1
#   3    bus-number write 18h  Type 0, bus 1  <- must precede everything below
#   4-5  device probe          Type 1, bus 5
#   6-19 BAR sizing/assignment Type 1, bus 5 (the SSE.8 B1..B14 shape)
#   20   Command enable        Type 1, bus 5, structurally LAST
BRIDGED_GOLDEN_SEQUENCE = [
    (0, 0x01, False, CFG_REG_VENDOR_DEVICE, 0b1111, None),
    (0, 0x01, False, CFG_REG_CACHE_HEADER,  0b1111, None),
    (0, 0x01, True,  CFG_REG_BUS_NUMBER,    0b1111, BUS_NUM_WDATA),
    (1, SEC_BUS, False, CFG_REG_VENDOR_DEVICE, 0b1111, None),
    (1, SEC_BUS, False, CFG_REG_CACHE_HEADER,  0b1111, None),
    (1, SEC_BUS, True,  4, 0b1111, 0xFFFFFFFF),    # sizing, pair low
    (1, SEC_BUS, False, 4, 0b1111, None),
    (1, SEC_BUS, True,  5, 0b1111, 0xFFFFFFFF),    # sizing, pair high
    (1, SEC_BUS, False, 5, 0b1111, None),
    (1, SEC_BUS, True,  4, 0b1111, 0x80000000),    # assign, low
    (1, SEC_BUS, True,  5, 0b1111, 0x00000000),    # assign, high
    (1, SEC_BUS, True,  6, 0b1111, 0xFFFFFFFF),    # the DEVICE's reg 6 -- a
    (1, SEC_BUS, False, 6, 0b1111, None),          # Type 0 header BAR2, and
    (1, SEC_BUS, True,  7, 0b1111, 0xFFFFFFFF),    # Type 1 on the wire: NOT
    (1, SEC_BUS, False, 7, 0b1111, None),          # the bridge's 18h (P4.7)
    (1, SEC_BUS, True,  8, 0b1111, 0xFFFFFFFF),
    (1, SEC_BUS, False, 8, 0b1111, None),
    (1, SEC_BUS, True,  9, 0b1111, 0xFFFFFFFF),
    (1, SEC_BUS, False, 9, 0b1111, None),
    (1, SEC_BUS, True,  CFG_REG_COMMAND_STATUS, 0b0011, CMD_ENABLE_VALUE),
]

# The Stage C direct-attach sequence, restated with the type/bus columns the
# bridged golden carries -- all Type 0, all bus 1 (B5's regression golden).
DIRECT_GOLDEN_SEQUENCE = [
    (0, 0x01, False, CFG_REG_VENDOR_DEVICE, 0b1111, None),
    (0, 0x01, False, CFG_REG_CACHE_HEADER,  0b1111, None),
    (0, 0x01, True,  4, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 4, 0b1111, None),
    (0, 0x01, True,  5, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 5, 0b1111, None),
    (0, 0x01, True,  4, 0b1111, 0x80000000),
    (0, 0x01, True,  5, 0b1111, 0x00000000),
    (0, 0x01, True,  6, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 6, 0b1111, None),
    (0, 0x01, True,  7, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 7, 0b1111, None),
    (0, 0x01, True,  8, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 8, 0b1111, None),
    (0, 0x01, True,  9, 0b1111, 0xFFFFFFFF),
    (0, 0x01, False, 9, 0b1111, None),
    (0, 0x01, True,  CFG_REG_COMMAND_STATUS, 0b0011, CMD_ENABLE_VALUE),
]


def on_wire(req):
    """One observed TLP as the golden tuple shape -- type and bus INCLUDED,
    because they are exactly the two fields Stage D exists to get right."""
    return (1 if req.tlp_type == TYPE_CFG1 else 0, req.bus,
            not req.is_read, req.reg_num, req.first_be,
            req.payload[0] if req.payload else None)


def render(item):
    type1, bus, write, reg, fbe, payload = item
    kind = f"Cfg{'Wr' if write else 'Rd'}{type1}"
    data = "-" if payload is None else f"{payload:#010x}"
    return f"{kind}(bus={bus:#04x}, reg={reg:#04x}, fbe={fbe:#06b}, data={data})"


# ==========================================================================
# Harness
# ==========================================================================
async def init(dut, topo=None, credits=None, serve=True):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    dut.link_up_i.value = 0
    dut.transmit_enable_i.value = 0
    dut.scan_start_i.value = 0
    dut.scan_bus_i.value = SCAN_BUS
    dut.bar_enable_i.value = 1
    dut.bridge_enable_i.value = 1
    dut.s_dllp_axis_tdata.value = 0
    dut.s_dllp_axis_tkeep.value = 0
    dut.s_dllp_axis_tvalid.value = 0
    dut.s_dllp_axis_tlast.value = 0
    dut.s_dllp_axis_tuser.value = 0
    dut.m_dllp_axis_tready.value = 1
    dut.requester_id_i.value = RID
    dut.completer_id_i.value = 0
    dut.bus_number_i.value = 0
    dut.device_number_i.value = 0
    dut.function_number_i.value = 0
    dut.memory_enable_i.value = 1
    dut.extended_tag_enable_i.value = 0
    dut.max_payload_bytes_i.value = 128
    dut.max_read_bytes_i.value = 128
    dut.rcb_128b_i.value = 0
    dut.fc_initialized_i.value = 0
    dut.fc_update_valid_i.value = 0
    set_credits(dut, ph=0, pd=0, nph=0, npd=0, cplh=0, cpld=0)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.link_up_i.value = 1
    dut.transmit_enable_i.value = 1

    set_credits(dut, **(credits or {}))
    dut.fc_initialized_i.value = 1
    dut.fc_update_valid_i.value = 1        # THE INIT STROBE
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    if credits is not None:
        dut.fc_update_valid_i.value = 0    # a drip test pulses its own totals
    for _ in range(4):
        await RisingEdge(dut.clk_i)

    mon = Mon(dut)
    mon.start()
    completer = BridgedCompleter(dut, topo=topo)
    completer.start()
    if serve:
        completer.serve()
    await RisingEdge(dut.clk_i)
    return mon, completer


async def start_enum(dut):
    dut.scan_start_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.scan_start_i.value = 0


async def settle(dut, cycles=40):
    """LOCAL BY DESIGN. Not an early-exit loop: the default IS sim time."""
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)


async def wait_bridged(dut, cycles=60000):
    for _ in range(cycles):
        await ReadOnly()
        reached = int(dut.sec_enum_done_o.value) or int(dut.enum_error_o.value)
        await RisingEdge(dut.clk_i)
        if reached:
            return
    raise AssertionError("the bridged enumeration never reached a terminal state")


async def wait_direct(dut, cycles=60000):
    for _ in range(cycles):
        await ReadOnly()
        reached = int(dut.enum_done_o.value) or int(dut.enum_error_o.value)
        await RisingEdge(dut.clk_i)
        if reached:
            return
    raise AssertionError("the direct-attach enumeration never terminated")


async def status(dut):
    """Both levels' status surfaces, one snapshot."""
    await ReadOnly()
    sizes = int(dut.sec_bar_size_o.value)
    addrs = int(dut.sec_bar_addr_o.value)
    snap = {
        # level 1: the bridge as the scan found it
        "scan_done": int(dut.scan_done_o.value),
        "present": int(dut.device_present_o.value),
        "unsupported": int(dut.unsupported_device_o.value),
        "vendor": int(dut.vendor_id_o.value),
        "device": int(dut.device_id_o.value),
        "header": int(dut.header_type_o.value),
        "error": int(dut.enum_error_o.value),
        "code": int(dut.enum_error_code_o.value),
        "blocked": int(dut.err_credit_blocked_o.value),
        "done": int(dut.enum_done_o.value),
        # bridge path
        "bus_done": int(dut.bus_done_o.value),
        "bus_bypassed": int(dut.bus_bypassed_o.value),
        # level 2: the device behind the bridge
        "sec_scan_done": int(dut.sec_scan_done_o.value),
        "sec_present": int(dut.sec_device_present_o.value),
        "sec_unsupported": int(dut.sec_unsupported_device_o.value),
        "sec_bdf": int(dut.sec_device_bdf_o.value),
        "sec_vendor": int(dut.sec_vendor_id_o.value),
        "sec_device": int(dut.sec_device_id_o.value),
        "sec_done": int(dut.sec_enum_done_o.value),
        "sec_count": int(dut.sec_bar_count_o.value),
        "sec_valid": int(dut.sec_bar_valid_o.value),
        "sec_is64": int(dut.sec_bar_is_64_o.value),
        "sec_prefetch": int(dut.sec_bar_prefetch_o.value),
        "sec_io_mask": int(dut.sec_io_bar_mask_o.value),
        "sec_size": [(sizes >> (64 * i)) & MASK64 for i in range(BAR_SLOTS)],
        "sec_addr": [(addrs >> (64 * i)) & MASK64 for i in range(BAR_SLOTS)],
    }
    await RisingEdge(dut.clk_i)
    return snap


def assert_bridged_outcome(snap, what=""):
    """Every captured value on both levels, against the P5.2 table."""
    assert snap["error"] == 0, \
        f"{what}enumeration errored {err_name(snap['code'])}: {snap}"
    assert snap["scan_done"] == 1 and snap["present"] == 1, f"{what}{snap}"
    assert snap["unsupported"] == 1, \
        f"{what}the bridge did not classify unsupported-at-level-1: {snap}"
    assert snap["vendor"] == BRIDGE_VENDOR and snap["device"] == BRIDGE_DEVICE, \
        f"{what}level-1 identity {snap['vendor']:#06x}:{snap['device']:#06x}"
    assert snap["header"] & 0x7F == 0x01, f"{what}header {snap['header']:#04x}"
    assert snap["bus_done"] == 1 and snap["bus_bypassed"] == 0, f"{what}{snap}"
    assert snap["sec_scan_done"] == 1 and snap["sec_present"] == 1, \
        f"{what}the secondary scan did not find the device: {snap}"
    assert snap["sec_unsupported"] == 0, f"{what}{snap}"
    assert snap["sec_bdf"] == SEC_DEV_BDF, \
        f"{what}sec_device_bdf_o {snap['sec_bdf']:#06x} != {SEC_DEV_BDF:#06x}"
    assert snap["sec_vendor"] == SEC_DEV_VENDOR and \
        snap["sec_device"] == SEC_DEV_DEVICE, (
        f"{what}level-2 identity {snap['sec_vendor']:#06x}:"
        f"{snap['sec_device']:#06x} -- if these are the BRIDGE's IDs, the "
        "probe was answered locally instead of routed (Trap B)")
    assert snap["sec_done"] == 1, f"{what}{snap}"
    assert snap["sec_count"] == 1 and snap["sec_valid"] == 0b000001, f"{what}{snap}"
    assert snap["sec_is64"] == 0b000001 and snap["sec_prefetch"] == 0b000001, \
        f"{what}{snap}"
    assert snap["sec_io_mask"] == 0, f"{what}{snap}"
    assert snap["sec_size"][0] == ACCEPT_BAR_SIZE, \
        f"{what}sec BAR size {snap['sec_size'][0]:#x}"
    assert snap["sec_addr"][0] == ACCEPT_BAR_ADDR, \
        f"{what}sec BAR addr {snap['sec_addr'][0]:#x}"
    assert snap["blocked"] == 0, f"{what}err_credit_blocked_o on a clean run"


def assert_bridged_wire(completer, what=""):
    """⭐ Every emitted TLP against SS5.4, IN ORDER, payloads included --
    then each header re-derived from Base 2.1 with the right type AND bus."""
    seen = nonempty(completer.seen, f"{what}no TLP reached the wire at all")
    assert_sequence([on_wire(r) for r in seen], BRIDGED_GOLDEN_SEQUENCE,
                    f"{what}SS5.4 on-wire sequence", render=render)
    for index, req in enumerate(seen):
        type1, bus, write, reg, first_be, _payload = BRIDGED_GOLDEN_SEQUENCE[index]
        assert_cfg_tlp_on_wire(req, write=write, reg_num=reg, first_be=first_be,
                               tag=req.tag, type1=bool(type1), bus=bus,
                               what=f"{what}TLP {index} ({req!r}): ")

    # F3.2, stated on its own even though the whole-sequence compare pins it:
    # the 18h write precedes the FIRST Type 1 TLP of the run.
    idx_18h = next(i for i, r in enumerate(seen)
                   if r.tlp_type == TYPE_CFG0 and not r.is_read
                   and r.reg_num == CFG_REG_BUS_NUMBER)
    idx_cfg1 = next(i for i, r in enumerate(seen) if r.tlp_type == TYPE_CFG1)
    assert idx_18h < idx_cfg1, (
        f"{what}the first CFG1 (index {idx_cfg1}) precedes the bus-number "
        f"write (index {idx_18h}) -- F3.2")

    # F3.4: the Command enable is structurally LAST for the device.
    cmd_writes = [i for i, r in enumerate(seen)
                  if r.tlp_type == TYPE_CFG1 and not r.is_read
                  and r.reg_num == CFG_REG_COMMAND_STATUS]
    assert cmd_writes == [len(seen) - 1], (
        f"{what}device Command write(s) at {cmd_writes}, expected exactly one "
        f"at index {len(seen) - 1} (F3.4)")


def assert_bridge_config_untouched(completer, what=""):
    """⭐ The P4.7 NEGATIVE assertions, on the wire over the whole run.

    A Type 1 header has TWO BARs (registers 4-5) and register 6 IS the
    bus-number Dword.  So: no Type 0 all-ones write to register 6 ever
    appears (the sizing write that would destroy the assignment), the only
    Type 0 write to register 6 carries the bus-number Dword, and the
    bridge's own BARs are never sized in Stage D at all.  The deferral is
    recorded with its consequence: the bridge requests no memory aperture in
    this topology; base/limit windows are Stage E/F work.
    (The DEVICE's registers 4-9 are sized -- as Type 1 TLPs on bus 5, which
    is exactly the distinction these filters encode.)
    """
    seen = nonempty(completer.seen, f"{what}P4.7 over an empty set")
    level1 = [r for r in seen if r.tlp_type == TYPE_CFG0]
    assert level1, f"{what}no Type 0 traffic at all?"
    sizing_18h = [r for r in level1 if not r.is_read
                  and r.reg_num == CFG_REG_BUS_NUMBER
                  and r.payload == [0xFFFFFFFF]]
    assert not sizing_18h, (
        f"{what}an all-ones write hit the bridge's register 6 -- the "
        f"bus-number assignment was destroyed by a BAR sweep (P4.7): {sizing_18h}")
    wr_18h = [r for r in level1 if not r.is_read
              and r.reg_num == CFG_REG_BUS_NUMBER]
    assert wr_18h and all(r.payload == [BUS_NUM_WDATA] for r in wr_18h), \
        f"{what}unexpected write(s) to the bridge's register 6: {wr_18h}"
    bridge_bars = [r for r in level1 if r.reg_num in (4, 5)]
    assert not bridge_bars, (
        f"{what}the bridge's own BARs (registers 4-5) were touched -- Stage D "
        f"defers them (predictions SS10 item 7): {bridge_bars}")


def assert_model_guards_fired(topo, what=""):
    """The bench model's own arms, seen live in THIS run -- and the arms
    that must NOT have fired."""
    n_cfg1 = len([1 for g in BRIDGED_GOLDEN_SEQUENCE if g[0] == 1])
    assert len(topo.transforms) >= n_cfg1, (
        f"{what}{len(topo.transforms)} transforms for {n_cfg1} CFG1 "
        "transactions -- the one-bit transform arm did not carry the run")
    assert topo.route_ur_hits == 0, \
        f"{what}the bridge UR'd {topo.route_ur_hits} request(s) by bus range"
    assert topo.device_type1_ur_hits == 0, (
        f"{what}a raw Type 1 reached the device {topo.device_type1_ur_hits} "
        "time(s) -- the bridge failed to transform (P3.3's cross-check)")
    assert topo.forward_unmodified_hits == 0, \
        f"{what}the forward-unmodified arm fired -- unreachable at one level (P3.2)"
    assert topo.bridge.latency_byte_writes_ignored >= 1, \
        f"{what}the 18h write never exercised the latency-byte ignore arm (P4.2)"
    # P5.6: both Functions captured their BDFs from Type 0 config writes.
    assert topo.bridge_captured_id == BRIDGE_BDF
    assert topo.device_captured_id == SEC_DEV_BDF


# ==========================================================================
# B1 -- ⭐ THE STAGE D ACCEPTANCE, saturated credit
# ==========================================================================
@cocotb.test()
async def b1_bridge_enumerated_end_to_end(dut):
    """Type 1 discovery -> 18h write -> CFG1 scan/BARs/Command, all on the
    wire, in order, against the SS5.4 goldens."""
    topo = acceptance_topology()
    mon, completer = await init(dut, topo=topo)
    await start_enum(dut)
    await wait_bridged(dut)
    snap = await status(dut)

    assert_bridged_outcome(snap, "B1: ")
    assert_bridged_wire(completer, "B1: ")
    assert_bridge_config_untouched(completer, "B1: ")
    assert_model_guards_fired(topo, "B1: ")

    # The device really was programmed, through the transform.
    topo.device.assert_mask_exercised("B1: ")
    assert topo.device.bar_written(4) == 0x80000000
    assert topo.device.bar_written(5) == 0x00000000
    assert topo.device.command == CMD_ENABLE_VALUE
    # The bridge's registers hold exactly the routing state -- Command never
    # written (no memory aperture to enable), bus Dword as assigned.
    assert topo.bridge.command == 0, "B1: the bridge's Command register moved"
    assert topo.bridge.secondary == SEC_BUS and topo.bridge.subordinate == 0x09
    assert topo.bridge.primary == 0x01

    # P4.2, on the very model instance the run used: a rewrite with a
    # non-zero latency byte reads back 00h in [31:24] -- so no test may ever
    # write non-zero there and expect it back.
    dw2_18h = cfg_wire_dw2(0x01, 0, 0, CFG_REG_BUS_NUMBER)
    who, st, _, _ = topo.handle(
        [cfg_wire_dw0(True), cfg_wire_dw1(RID, 0, CFG_BE_DWORD), dw2_18h,
         0xAA000000 | BUS_NUM_WDATA])
    assert (who, st) == ("bridge", 0), (who, st)
    _, _, readback, _ = topo.handle(
        [cfg_wire_dw0(False), cfg_wire_dw1(RID, 0, CFG_BE_DWORD), dw2_18h])
    assert readback == BUS_NUM_WDATA, \
        f"B1: 18h readback {readback:#010x} -- [31:24] must read 00h (P4.2)"

    mon.clean()


# ==========================================================================
# B2 -- ⭐ the same run under the Table 2-37 minimum credit drip (F3.6)
# ==========================================================================
@cocotb.test()
async def b2_bridge_under_the_minimum_credit_drip(dut):
    """NPH=1, NPD=1, cumulative drip: SAME TLP sequence, SAME order."""
    topo = acceptance_topology()
    mon, completer = await init(dut, topo=topo, credits={
        "ph": 0, "pd": 0, "nph": 1, "npd": 1, "cplh": 0, "cpld": 0})
    drip = CreditDrip(dut, nph=1, npd=1, period=40, step=1)
    drip.start()

    await start_enum(dut)
    await wait_bridged(dut)
    snap = await status(dut)

    assert_bridged_outcome(snap, "B2 (credit drip): ")
    assert_bridged_wire(completer, "B2: ")
    assert_bridge_config_untouched(completer, "B2: ")
    assert_model_guards_fired(topo, "B2: ")
    assert topo.device.command == CMD_ENABLE_VALUE

    assert mon.blocked_seen, (
        "B2: tx_fc_blocked_o never asserted -- the credit never bound, so "
        "this is a duplicate of B1, not the drip run F3.6 demands")
    assert drip.updates >= len(BRIDGED_GOLDEN_SEQUENCE) - 1, (
        f"B2: {drip.updates} UpdateFCs for {len(BRIDGED_GOLDEN_SEQUENCE)} "
        "transactions; with NPH=1 each needs its own")
    mon.clean()


# ==========================================================================
# B3 -- CRS at BOTH points: the bridge's own 18h write, and the device's
# first CFG1 probe.  Retries preserve the type; the sequence completes.
# ==========================================================================
@cocotb.test()
async def b3_crs_at_both_points_preserves_type(dut):
    topo = acceptance_topology(bridge_crs_once=(CFG_REG_BUS_NUMBER,),
                               device_crs_once=(CFG_REG_VENDOR_DEVICE,))
    mon, completer = await init(dut, topo=topo)
    await start_enum(dut)
    await wait_bridged(dut)
    snap = await status(dut)

    assert_bridged_outcome(snap, "B3: ")
    assert topo.bridge_crs_hits == 1, "the bridge CRS arm never fired"
    assert topo.device_crs_hits == 1, "the device CRS arm never fired"

    seen = nonempty(completer.seen, "B3: nothing on the wire")
    assert len(seen) == len(BRIDGED_GOLDEN_SEQUENCE) + 2, \
        f"B3: {len(seen)} TLPs, expected two retries on top of the sequence"

    # The 18h write appears twice, BOTH CfgWr0 with identical headers: the
    # retry did not decay (P6.3) -- and this is a Type 0 retry.
    wr18 = expect_count([r for r in seen if not r.is_read
                         and r.reg_num == CFG_REG_BUS_NUMBER
                         and r.tlp_type == TYPE_CFG0], 2,
                        "B3: 18h write attempts")
    assert wr18[0].dw0 == wr18[1].dw0 and wr18[0].dw2 == wr18[1].dw2
    assert wr18[0].payload == wr18[1].payload == [BUS_NUM_WDATA]

    # The device probe appears twice, BOTH CfgRd1: a Type 1 retry.
    probes = expect_count([r for r in seen if r.is_read
                           and r.reg_num == CFG_REG_VENDOR_DEVICE
                           and r.tlp_type == TYPE_CFG1], 2,
                          "B3: device probe attempts")
    assert probes[0].dw0 == probes[1].dw0 and probes[0].dw2 == probes[1].dw2

    # Drop the two CRS'd attempts; the remainder is the pinned sequence.
    del completer.seen[completer.seen.index(wr18[0])]
    del completer.seen[completer.seen.index(probes[0])]
    assert_bridged_wire(completer, "B3 (retries dropped): ")
    assert_bridge_config_untouched(completer, "B3: ")
    mon.clean()


# ==========================================================================
# B4 -- ⭐ the STALLED-WRITE run: the discriminating ordering check (Trap D)
# ==========================================================================
@cocotb.test()
async def b4_stalled_write_completion_discriminates_the_order(dut):
    """The 18h write's completion is withheld for 800 cycles.  In that
    window a wrongly-ordered implementation would already have emitted the
    CFG1 probe -- the wire must stay SILENT until the completion lands.

    This is the run that actually discriminates F3.2: with zero-latency
    completers a wrong-order FSM is unobservable (SS8.4), and even B1's
    unequal latencies leave only a narrow window.  Here the window is ~25x
    the whole happy path.
    """
    topo = acceptance_topology()
    mon, completer = await init(dut, topo=topo, serve=False)   # manual serve
    await start_enum(dut)

    # Answer the two probe reads normally.
    for index in range(2):
        await completer.wait_for(index + 1)
        req = completer.seen[index]
        who, st, data, cid = topo.handle(req.dwords)
        await completer.complete(req, status=st, data=data, completer_id=cid)

    # The 18h write arrives -- and its completion is WITHHELD.
    await completer.wait_for(3)
    write18 = completer.seen[2]
    assert not write18.is_read and write18.reg_num == CFG_REG_BUS_NUMBER
    await settle(dut, 800)
    assert len(completer.seen) == 3, (
        f"B4: {len(completer.seen) - 3} TLP(s) emitted while the bus-number "
        "write was still uncompleted -- the sequencer handed off before the "
        f"bridge could route (F3.2): {completer.seen[3:]}")
    snap = await status(dut)
    assert snap["bus_done"] == 0 and snap["sec_scan_done"] == 0, \
        f"B4: the handoff surface asserted during the stall: {snap}"

    # Release it, then serve the rest of the run to completion.
    who, st, data, cid = topo.handle(write18.dwords)
    await completer.complete(write18, status=st, data=data, completer_id=cid)
    for index in range(3, len(BRIDGED_GOLDEN_SEQUENCE)):
        await completer.wait_for(index + 1)
        req = completer.seen[index]
        who, st, data, cid = topo.handle(req.dwords)
        await completer.complete(req, status=st, data=data, completer_id=cid)

    await wait_bridged(dut)
    snap = await status(dut)
    assert_bridged_outcome(snap, "B4: ")
    assert_bridged_wire(completer, "B4: ")
    mon.clean()


# ==========================================================================
# B5 -- the direct-attach regression: a Type 0 device at bus 1, with the
# bridge path ENABLED, enumerates exactly as Stage C did.
# ==========================================================================
@cocotb.test()
async def b5_direct_attach_unchanged_with_bridge_path_enabled(dut):
    """bridge_enable_i is HIGH and the new stages still never take
    ownership: the wire carries the Stage C sequence, all Type 0, and the
    bridge-path status shows a clean structural bypass.

    (The per-target gate proves the same thing for every existing bench,
    where bridge_enable_i is tied low; this run proves the bypass is decided
    by the VERDICT, not by the enable.)
    """
    # The local Function is a plain Type 0 endpoint -- the Stage C acceptance
    # shape with the Stage C identity.  BridgedTopology's local slot is
    # duck-typed: a ConfigDevice serves Type 0 requests exactly as the bench
    # bridge would serve its own; no CFG1 can be emitted on this run for the
    # secondary arms to matter (and a mutant that emitted one would fail on
    # the model's routing state, loudly).
    local = ConfigDevice(
        bars={CFG_REG_BAR0: BarSpec(BAR_MEM64, ACCEPT_BAR_SIZE, prefetch=True)})
    topo = BridgedTopology(bridge=local)
    mon, completer = await init(dut, topo=topo)
    await start_enum(dut)
    await wait_direct(dut)
    await settle(dut, 80)          # room for any stray bridge-path traffic
    snap = await status(dut)

    assert snap["error"] == 0 and snap["present"] == 1, f"B5: {snap}"
    assert snap["unsupported"] == 0, f"B5: {snap}"
    assert snap["vendor"] == VENDOR and snap["device"] == DEVICE, f"B5: {snap}"
    assert snap["scan_done"] == 1 and snap["done"] == 1, \
        f"B5: level 1 did not complete: {snap}"
    # ⭐ the structural bypass: decided by the verdict, not the enable.
    assert snap["bus_bypassed"] == 1 and snap["bus_done"] == 0, (
        f"B5: the bridge path did not bypass a Type 0 device: {snap}")
    assert snap["sec_scan_done"] == 0 and snap["sec_done"] == 0, \
        f"B5: the second level ran on a direct-attach topology: {snap}"

    seen = nonempty(completer.seen, "B5: nothing on the wire")
    assert_sequence([on_wire(r) for r in seen], DIRECT_GOLDEN_SEQUENCE,
                    "B5: Stage C direct-attach sequence", render=render)
    assert all(r.tlp_type == TYPE_CFG0 for r in seen), \
        "B5: a Type 1 TLP appeared on a direct-attach run"
    assert topo.transforms == [] and topo.route_ur_hits == 0, \
        "B5: the bridge-model routing arms fired with no CFG1 emitted?"
    local.assert_mask_exercised("B5: ")
    assert local.command == CMD_ENABLE_VALUE
    mon.clean()
