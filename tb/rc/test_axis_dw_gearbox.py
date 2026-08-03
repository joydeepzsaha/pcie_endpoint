"""Commit 2a-0 -- exhaustive bench for the AXI-Stream width gearboxes.

G1..G10 against pcie_axis_dw_downsize (128 -> 32) and pcie_axis_dw_upsize
(32 -> 128), plus the round-trip pair. No Transaction Layer in the loop, so no
FC-credit initialisation is needed here.

tkeep is byte-granular on both sides (16 bits wide / 4 bits narrow) -- see the
module headers. The gearboxes are descriptor-blind: there is no DESC_DW
parameter and no PG213 descriptor semantics anywhere in this file.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

CLK_NS = 4
WIDE_BYTES = 16
NARROW_BYTES = 4
FULL_WIDE_KEEP = (1 << WIDE_BYTES) - 1
FULL_NARROW_KEEP = (1 << NARROW_BYTES) - 1

# The N-Dword sweep shared by G2, G5 and G8.
N_SWEEP = [1, 2, 3, 4, 5, 7, 8, 15, 16, 17, 64, 1024]


# --------------------------------------------------------------------------
# AXI-Stream helpers
# --------------------------------------------------------------------------
class AxisSource:
    """Drives an AXIS slave port. Zero idle cycles unless a stall is rolled."""

    def __init__(self, dut, prefix):
        self.clk = dut.clk_i
        self.tdata = getattr(dut, prefix + "_tdata")
        self.tkeep = getattr(dut, prefix + "_tkeep")
        self.tvalid = getattr(dut, prefix + "_tvalid")
        self.tlast = getattr(dut, prefix + "_tlast")
        self.tready = getattr(dut, prefix + "_tready")

    def idle(self):
        self.tvalid.value = 0
        self.tdata.value = 0
        self.tkeep.value = 0
        self.tlast.value = 0

    async def send(self, beats, rng=None, stall_prob=0.0):
        for data, keep, last in beats:
            if rng is not None:
                while rng.random() < stall_prob:
                    self.idle()
                    await RisingEdge(self.clk)
            self.tdata.value = data
            self.tkeep.value = keep
            self.tlast.value = 1 if last else 0
            self.tvalid.value = 1
            while True:
                await ReadOnly()
                fired = int(self.tready.value) == 1
                await RisingEdge(self.clk)
                if fired:
                    break
        self.idle()


class AxisSink:
    """Collects (data, keep, last) from an AXIS master port."""

    def __init__(self, dut, prefix):
        self.clk = dut.clk_i
        self.tdata = getattr(dut, prefix + "_tdata")
        self.tkeep = getattr(dut, prefix + "_tkeep")
        self.tvalid = getattr(dut, prefix + "_tvalid")
        self.tlast = getattr(dut, prefix + "_tlast")
        self.tready = getattr(dut, prefix + "_tready")
        self.beats = []
        self.rng = None
        self.stall_prob = 0.0

    async def run(self):
        while True:
            stall = self.rng is not None and self.rng.random() < self.stall_prob
            self.tready.value = 0 if stall else 1
            await ReadOnly()
            if int(self.tvalid.value) and int(self.tready.value):
                self.beats.append((int(self.tdata.value),
                                   int(self.tkeep.value),
                                   int(self.tlast.value)))
            await RisingEdge(self.clk)


class ErrorMonitor:
    """Counts gearbox_error_o pulses."""

    def __init__(self, dut, name):
        self.clk = dut.clk_i
        self.sig = getattr(dut, name)
        self.count = 0

    async def run(self):
        while True:
            await ReadOnly()
            if int(self.sig.value):
                self.count += 1
            await RisingEdge(self.clk)


async def wait_for(sink, count, clk, limit=200000):
    """Wait until the sink has collected `count` beats."""
    for _ in range(limit):
        if len(sink.beats) >= count:
            return
        await RisingEdge(clk)
    raise AssertionError(
        f"timeout waiting for {count} beats, got {len(sink.beats)}")


async def start_dut(dut):
    """Clock up, everything idle, reset released. Returns the sinks/monitors."""
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())

    sources = {p: AxisSource(dut, p) for p in ("dn_s", "up_s", "rt_s")}
    sinks = {p: AxisSink(dut, p) for p in ("dn_m", "up_m", "rt_m")}
    monitors = {n: ErrorMonitor(dut, n)
                for n in ("dn_error", "up_error", "rt_dn_error", "rt_up_error")}

    dut.rst_i.value = 1
    for src in sources.values():
        src.idle()
    for snk in sinks.values():
        snk.tready.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)

    for snk in sinks.values():
        cocotb.start_soon(snk.run())
    for mon in monitors.values():
        cocotb.start_soon(mon.run())
    await RisingEdge(dut.clk_i)
    return sources, sinks, monitors


# --------------------------------------------------------------------------
# packet construction
# --------------------------------------------------------------------------
def dwords(n, seed_val=0):
    """n distinct Dword values -- distinct so any reorder/duplication shows up."""
    return [(0xA5000000 | (seed_val << 16) | (i & 0xFFFF)) ^ (i * 0x01010101) & 0xFFFFFFFF
            for i in range(n)]


def to_wide_beats(dw_list):
    """Pack Dwords into 128-bit beats, full keep except a partial final beat."""
    beats = []
    for pos in range(0, len(dw_list), 4):
        chunk = dw_list[pos:pos + 4]
        data = 0
        keep = 0
        for lane, value in enumerate(chunk):
            data |= value << (32 * lane)
            keep |= FULL_NARROW_KEEP << (4 * lane)
        beats.append((data, keep, pos + 4 >= len(dw_list)))
    return beats


def to_narrow_beats(dw_list):
    return [(dw, FULL_NARROW_KEEP, i + 1 == len(dw_list))
            for i, dw in enumerate(dw_list)]


def mask_beat(beat, width_bytes=WIDE_BYTES):
    """Zero the lanes tkeep does not select, so beats compare on carried bytes.

    Lanes outside tkeep are don't-care in AXI-Stream; the round trip legitimately
    returns them as zero because the downsizer never emits those groups.
    """
    data, keep, last = beat
    masked = 0
    for i in range(width_bytes):
        if keep & (1 << i):
            masked |= ((data >> (8 * i)) & 0xFF) << (8 * i)
    return (masked, keep, last)


def wide_beats_to_bytes(beats):
    """Flatten (data, keep, last) wide beats into the byte stream they carry."""
    out = bytearray()
    for data, keep, _ in beats:
        for byte_index in range(WIDE_BYTES):
            if keep & (1 << byte_index):
                out.append((data >> (8 * byte_index)) & 0xFF)
    return bytes(out)


# --------------------------------------------------------------------------
# G1 -- elaboration / lint / reset idle
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g1_elaborate_and_idle(dut):
    """G1: the pair elaborates, and after reset nothing is driven."""
    _, sinks, monitors = await start_dut(dut)

    for _ in range(20):
        await RisingEdge(dut.clk_i)

    for name, snk in sinks.items():
        assert snk.beats == [], f"{name} produced {len(snk.beats)} beats with no stimulus"
    for name, mon in monitors.items():
        assert mon.count == 0, f"{name} pulsed {mon.count} times at idle"

    assert int(dut.dn_s_tready.value) == 1, "downsize not ready after reset"
    assert int(dut.up_s_tready.value) == 1, "upsize not ready after reset"
    assert int(dut.dn_m_tvalid.value) == 0
    assert int(dut.up_m_tvalid.value) == 0
    dut._log.info("G1: elaboration clean, both gearboxes idle and ready after reset")


# --------------------------------------------------------------------------
# G2 -- downsize N-Dword sweep
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g2_downsize_dw_sweep(dut):
    """G2: N wide-packed Dwords -> exactly N narrow beats, in order, one tlast."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["dn_s"], sinks["dn_m"]

    for n in N_SWEEP:
        snk.beats.clear()
        payload = dwords(n, seed_val=n & 0xFF)
        await src.send(to_wide_beats(payload))
        await wait_for(snk, n, dut.clk_i)

        assert len(snk.beats) == n, f"N={n}: expected {n} narrow beats, got {len(snk.beats)}"
        got_dw = [b[0] for b in snk.beats]
        assert got_dw == payload, f"N={n}: Dword sequence mismatch"
        assert all(b[1] == FULL_NARROW_KEEP for b in snk.beats), f"N={n}: bad tkeep"
        lasts = [i for i, b in enumerate(snk.beats) if b[2]]
        assert lasts == [n - 1], f"N={n}: tlast at {lasts}, expected only [{n-1}]"

    assert monitors["dn_error"].count == 0, "G2 tripped the illegal-tkeep guard"
    dut._log.info("G2: %s -- beat counts, ordering and tlast all exact", N_SWEEP)


# --------------------------------------------------------------------------
# G3 -- downsize partial final beat
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g3_downsize_partial_final(dut):
    """G3: a single wide beat with partial tkeep -> exact beat count, no phantom DW."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["dn_s"], sinks["dn_m"]

    # (wide tkeep, expected narrow beats, expected final narrow tkeep)
    cases = [
        (0x000F, 1, 0xF),
        (0x00FF, 2, 0xF),
        (0x0FFF, 3, 0xF),
        (0xFFFF, 4, 0xF),
        (0x0003, 1, 0x3),
        (0x0001, 1, 0x1),
    ]
    data = 0
    for i in range(WIDE_BYTES):
        data |= (0x10 + i) << (8 * i)

    for keep, expect_beats, final_keep in cases:
        snk.beats.clear()
        await src.send([(data, keep, True)])
        await wait_for(snk, expect_beats, dut.clk_i)
        # Give a phantom beat a chance to appear.
        for _ in range(6):
            await RisingEdge(dut.clk_i)

        assert len(snk.beats) == expect_beats, (
            f"tkeep=0x{keep:04X}: expected {expect_beats} beats, got {len(snk.beats)} "
            f"-- phantom or dropped Dword")
        assert snk.beats[-1][1] == final_keep, (
            f"tkeep=0x{keep:04X}: final narrow tkeep 0x{snk.beats[-1][1]:X}, "
            f"expected 0x{final_keep:X}")
        assert snk.beats[-1][2] == 1, f"tkeep=0x{keep:04X}: no tlast on final beat"
        assert sum(b[2] for b in snk.beats) == 1, f"tkeep=0x{keep:04X}: multiple tlast"
        # Bytes carried must equal the bytes the wide beat's keep selected.
        got = bytearray()
        for bdata, bkeep, _ in snk.beats:
            for i in range(NARROW_BYTES):
                if bkeep & (1 << i):
                    got.append((bdata >> (8 * i)) & 0xFF)
        assert bytes(got) == wide_beats_to_bytes([(data, keep, True)]), (
            f"tkeep=0x{keep:04X}: byte payload mismatch")

    assert monitors["dn_error"].count == 0, "G3 used only legal contiguous tkeep"
    dut._log.info("G3: partial final beats 1/2/3/4/1/1, tkeep 0x3 and 0x1 preserved")


# --------------------------------------------------------------------------
# G4 -- downsize illegal non-contiguous tkeep
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g4_downsize_noncontiguous_keep(dut):
    """G4: illegal non-contiguous tkeep is flagged, never silently accepted."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["dn_s"], sinks["dn_m"]
    mon = monitors["dn_error"]

    data = 0
    for i in range(WIDE_BYTES):
        data |= (0x10 + i) << (8 * i)

    # (illegal tkeep, groups the pattern spans)
    cases = [(0x00F0, 2), (0xF00F, 4), (0x0F00, 3), (0xFF00, 4)]

    for keep, span in cases:
        snk.beats.clear()
        before = mon.count
        await src.send([(data, keep, True)])
        await wait_for(snk, span, dut.clk_i)
        for _ in range(6):
            await RisingEdge(dut.clk_i)

        assert mon.count == before + 1, (
            f"tkeep=0x{keep:04X}: gearbox_error_o did not pulse "
            f"(count {before} -> {mon.count}) -- illegal tkeep accepted silently")
        assert len(snk.beats) == span, (
            f"tkeep=0x{keep:04X}: expected {span} beats spanning the pattern, "
            f"got {len(snk.beats)}")
        # No byte may be invented or relocated: each narrow beat's keep must be
        # exactly the corresponding nibble of the wide keep.
        for group, (bdata, bkeep, _) in enumerate(snk.beats):
            expect_keep = (keep >> (4 * group)) & 0xF
            assert bkeep == expect_keep, (
                f"tkeep=0x{keep:04X}: group {group} keep 0x{bkeep:X}, "
                f"expected 0x{expect_keep:X} -- bytes were relocated")
        assert snk.beats[-1][2] == 1, f"tkeep=0x{keep:04X}: no tlast"

    # A zero-keep beat is also illegal and must be flagged.
    before = mon.count
    snk.beats.clear()
    await src.send([(data, 0x0000, True)])
    for _ in range(8):
        await RisingEdge(dut.clk_i)
    assert mon.count == before + 1, "zero tkeep was not flagged"

    dut._log.info("G4: %d illegal patterns flagged, bytes never relocated", len(cases) + 1)


# --------------------------------------------------------------------------
# G5 -- upsize N-Dword sweep
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g5_upsize_dw_sweep(dut):
    """G5: N narrow beats -> ceil(N/4) wide beats, final tkeep correct, one tlast."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["up_s"], sinks["up_m"]

    for n in N_SWEEP:
        snk.beats.clear()
        payload = dwords(n, seed_val=(n + 3) & 0xFF)
        expect = (n + 3) // 4
        await src.send(to_narrow_beats(payload))
        await wait_for(snk, expect, dut.clk_i)

        assert len(snk.beats) == expect, (
            f"N={n}: expected {expect} wide beats, got {len(snk.beats)}")
        assert snk.beats == to_wide_beats(payload), f"N={n}: wide packing mismatch"

        tail = n % 4 or 4
        expect_keep = (1 << (4 * tail)) - 1
        assert snk.beats[-1][1] == expect_keep, (
            f"N={n}: final tkeep 0x{snk.beats[-1][1]:04X}, expected 0x{expect_keep:04X}")
        lasts = [i for i, b in enumerate(snk.beats) if b[2]]
        assert lasts == [expect - 1], f"N={n}: tlast at {lasts}"

    assert monitors["up_error"].count == 0, "G5 tripped the illegal-tkeep guard"
    dut._log.info("G5: %s -- ceil(N/4) wide beats, final tkeep exact", N_SWEEP)


# --------------------------------------------------------------------------
# G6 -- upsize early tlast
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g6_upsize_early_tlast(dut):
    """G6: tlast at 1/2/3 beats emits the partial wide beat immediately."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["up_s"], sinks["up_m"]

    for n, expect_keep in ((1, 0x000F), (2, 0x00FF), (3, 0x0FFF)):
        snk.beats.clear()
        payload = dwords(n, seed_val=0x40 + n)

        await src.send(to_narrow_beats(payload))
        # The partial word must be out within a couple of cycles -- not held
        # waiting for a fourth beat that is never coming.
        emitted_within = None
        for cycle in range(6):
            if snk.beats:
                emitted_within = cycle
                break
            await RisingEdge(dut.clk_i)
        assert emitted_within is not None, (
            f"N={n}: no partial wide beat emitted -- upsizer stalled waiting "
            f"for a 4th narrow beat")

        assert len(snk.beats) == 1, f"N={n}: expected 1 wide beat, got {len(snk.beats)}"
        data, keep, last = snk.beats[0]
        assert keep == expect_keep, (
            f"N={n}: tkeep 0x{keep:04X}, expected 0x{expect_keep:04X}")
        assert last == 1, f"N={n}: partial beat missing tlast"
        for lane, value in enumerate(payload):
            assert (data >> (32 * lane)) & 0xFFFFFFFF == value, f"N={n}: lane {lane} wrong"
        dut._log.info("G6: N=%d partial beat out %d cycle(s) after tlast, tkeep=0x%04X",
                      n, emitted_within, keep)

    assert monitors["up_error"].count == 0, "G6 used only legal beats"


# --------------------------------------------------------------------------
# G7 -- random backpressure, 1000 seeded packets
# --------------------------------------------------------------------------
G7_SEED = 0x2A00
G7_PACKETS = 1000


def _g7_packets(seed):
    rng = random.Random(seed)
    return [dwords(rng.randint(1, 12), seed_val=i & 0xFF) for i in range(G7_PACKETS)]


@cocotb.test()
async def test_g7_downsize_backpressure(dut):
    """G7: downsize output under random backpressure == the stall-free output."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["dn_s"], sinks["dn_m"]
    packets = _g7_packets(G7_SEED)
    dut._log.info("G7 downsize: seed=0x%X, %d packets", G7_SEED, G7_PACKETS)

    reference = []
    for payload in packets:
        snk.beats.clear()
        await src.send(to_wide_beats(payload))
        await wait_for(snk, len(payload), dut.clk_i)
        reference.append(list(snk.beats))

    rng_src = random.Random(G7_SEED + 1)
    snk.rng = random.Random(G7_SEED + 2)
    snk.stall_prob = 0.4
    for index, payload in enumerate(packets):
        snk.beats.clear()
        await src.send(to_wide_beats(payload), rng=rng_src, stall_prob=0.35)
        await wait_for(snk, len(payload), dut.clk_i)
        assert list(snk.beats) == reference[index], (
            f"packet {index} (seed 0x{G7_SEED:X}) differs under backpressure")
    snk.stall_prob = 0.0
    snk.rng = None

    assert monitors["dn_error"].count == 0, "G7 downsize tripped the guard"
    dut._log.info("G7 downsize: %d packets byte-identical under backpressure", G7_PACKETS)


@cocotb.test()
async def test_g7_upsize_backpressure(dut):
    """G7: upsize output under random backpressure == the stall-free output."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["up_s"], sinks["up_m"]
    packets = _g7_packets(G7_SEED)
    dut._log.info("G7 upsize: seed=0x%X, %d packets", G7_SEED, G7_PACKETS)

    reference = []
    for payload in packets:
        snk.beats.clear()
        await src.send(to_narrow_beats(payload))
        await wait_for(snk, (len(payload) + 3) // 4, dut.clk_i)
        reference.append(list(snk.beats))

    rng_src = random.Random(G7_SEED + 3)
    snk.rng = random.Random(G7_SEED + 4)
    snk.stall_prob = 0.4
    for index, payload in enumerate(packets):
        snk.beats.clear()
        await src.send(to_narrow_beats(payload), rng=rng_src, stall_prob=0.35)
        await wait_for(snk, (len(payload) + 3) // 4, dut.clk_i)
        assert list(snk.beats) == reference[index], (
            f"packet {index} (seed 0x{G7_SEED:X}) differs under backpressure")
    snk.stall_prob = 0.0
    snk.rng = None

    assert monitors["up_error"].count == 0, "G7 upsize tripped the guard"
    dut._log.info("G7 upsize: %d packets byte-identical under backpressure", G7_PACKETS)


# --------------------------------------------------------------------------
# G8 -- round trip downsize -> upsize
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g8_round_trip(dut):
    """G8: 128 -> 32 -> 128 reproduces the input beats exactly (no golden needed)."""
    sources, sinks, monitors = await start_dut(dut)
    src, snk = sources["rt_s"], sinks["rt_m"]

    for n in N_SWEEP:
        snk.beats.clear()
        payload = dwords(n, seed_val=(n * 7) & 0xFF)
        stimulus = to_wide_beats(payload)
        await src.send(stimulus)
        await wait_for(snk, len(stimulus), dut.clk_i)
        assert list(snk.beats) == stimulus, f"N={n}: round trip not byte-identical"

    # Sub-Dword final tkeep must survive the round trip too.
    data = 0
    for i in range(WIDE_BYTES):
        data |= (0x30 + i) << (8 * i)
    for keep in (0x0001, 0x0003, 0x0007, 0x001F, 0x03FF, 0x0FFF, 0xFFFF):
        snk.beats.clear()
        stimulus = [(data, keep, True)]
        await src.send(stimulus)
        await wait_for(snk, 1, dut.clk_i)
        got_data, got_keep, got_last = snk.beats[0]
        assert got_keep == keep, f"keep 0x{keep:04X} came back as 0x{got_keep:04X}"
        assert got_last == 1
        for byte_index in range(WIDE_BYTES):
            if keep & (1 << byte_index):
                expect = (data >> (8 * byte_index)) & 0xFF
                actual = (got_data >> (8 * byte_index)) & 0xFF
                assert actual == expect, (
                    f"keep 0x{keep:04X}: byte {byte_index} came back 0x{actual:02X}, "
                    f"expected 0x{expect:02X}")

    # Multi-beat packets with a partial final beat, under backpressure.
    rng = random.Random(0x8888)
    snk.rng = random.Random(0x9999)
    snk.stall_prob = 0.3
    for trial in range(60):
        snk.beats.clear()
        payload = dwords(rng.randint(1, 20), seed_val=trial & 0xFF)
        stimulus = to_wide_beats(payload)
        tail_keep = rng.choice([0x1, 0x3, 0x7, 0xF])
        last_data, last_keep, _ = stimulus[-1]
        top = last_keep.bit_length() - 4
        stimulus[-1] = (last_data, (last_keep & ((1 << top) - 1)) | (tail_keep << top), True)
        await src.send(stimulus, rng=rng, stall_prob=0.3)
        await wait_for(snk, len(stimulus), dut.clk_i)
        assert [mask_beat(b) for b in snk.beats] == [mask_beat(b) for b in stimulus], (
            f"trial {trial}: round trip mismatch")
    snk.stall_prob = 0.0
    snk.rng = None

    assert monitors["rt_dn_error"].count == 0, "G8 downsize stage flagged an error"
    assert monitors["rt_up_error"].count == 0, "G8 upsize stage flagged an error"
    dut._log.info("G8: round trip byte-identical across %s + partial keeps + backpressure",
                  N_SWEEP)


# --------------------------------------------------------------------------
# G9 -- reset mid-packet
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g9_reset_mid_packet(dut):
    """G9: reset mid-packet returns to idle; the next packet arrives intact."""
    sources, sinks, monitors = await start_dut(dut)

    # --- downsize: interrupt while narrow beats are still draining ----------
    dn_src, dn_snk = sources["dn_s"], sinks["dn_m"]
    dn_snk.beats.clear()
    payload = dwords(8, seed_val=0x11)
    stimulus = to_wide_beats(payload)

    dn_src.tdata.value = stimulus[0][0]
    dn_src.tkeep.value = stimulus[0][1]
    dn_src.tlast.value = 0
    dn_src.tvalid.value = 1
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)   # part-way through serialising beat 0
    dn_src.idle()
    dut.rst_i.value = 1
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)

    assert int(dut.dn_m_tvalid.value) == 0, "downsize still driving tvalid after reset"
    assert int(dut.dn_s_tready.value) == 1, "downsize not ready after reset"

    dn_snk.beats.clear()
    fresh = dwords(6, seed_val=0x22)
    await dn_src.send(to_wide_beats(fresh))
    await wait_for(dn_snk, 6, dut.clk_i)
    for _ in range(6):
        await RisingEdge(dut.clk_i)
    assert len(dn_snk.beats) == 6, (
        f"downsize: {len(dn_snk.beats)} beats after reset, expected 6 -- fragment leaked")
    assert [b[0] for b in dn_snk.beats] == fresh, "downsize: post-reset packet corrupted"
    assert [i for i, b in enumerate(dn_snk.beats) if b[2]] == [5]

    # --- upsize: interrupt with a half-assembled word -----------------------
    up_src, up_snk = sources["up_s"], sinks["up_m"]
    up_snk.beats.clear()
    partial = dwords(2, seed_val=0x33)
    await up_src.send([(partial[0], FULL_NARROW_KEEP, False),
                       (partial[1], FULL_NARROW_KEEP, False)])
    assert up_snk.beats == [], "upsize emitted a word from 2 of 4 beats"

    dut.rst_i.value = 1
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)

    assert int(dut.up_m_tvalid.value) == 0, "upsize still driving tvalid after reset"
    assert int(dut.up_s_tready.value) == 1, "upsize not ready after reset"

    up_snk.beats.clear()
    fresh = dwords(4, seed_val=0x44)
    await up_src.send(to_narrow_beats(fresh))
    await wait_for(up_snk, 1, dut.clk_i)
    for _ in range(6):
        await RisingEdge(dut.clk_i)
    assert len(up_snk.beats) == 1, (
        f"upsize: {len(up_snk.beats)} wide beats after reset, expected 1")
    assert up_snk.beats == to_wide_beats(fresh), (
        "upsize: half-assembled word leaked into the next packet")

    assert monitors["dn_error"].count == 0 and monitors["up_error"].count == 0
    dut._log.info("G9: both gearboxes return to idle on mid-packet reset, no fragment")


# --------------------------------------------------------------------------
# G10 -- back-to-back packets, zero idle cycles
# --------------------------------------------------------------------------
@cocotb.test()
async def test_g10_back_to_back(dut):
    """G10: packets with no idle cycle between them do not leak into each other."""
    sources, sinks, monitors = await start_dut(dut)

    sizes = [1, 4, 2, 8, 3, 5, 1, 16, 7, 4, 1, 1, 2, 3]

    # --- downsize -----------------------------------------------------------
    dn_src, dn_snk = sources["dn_s"], sinks["dn_m"]
    dn_snk.beats.clear()
    payloads = [dwords(n, seed_val=0x50 + i) for i, n in enumerate(sizes)]
    stream = []
    for payload in payloads:
        stream.extend(to_wide_beats(payload))
    await dn_src.send(stream)          # AxisSource inserts no gaps when rng is None
    await wait_for(dn_snk, sum(sizes), dut.clk_i)
    for _ in range(8):
        await RisingEdge(dut.clk_i)

    assert len(dn_snk.beats) == sum(sizes), (
        f"downsize: {len(dn_snk.beats)} beats, expected {sum(sizes)} -- fragment leaked "
        f"across a packet boundary")
    pos = 0
    for index, payload in enumerate(payloads):
        chunk = dn_snk.beats[pos:pos + len(payload)]
        assert [b[0] for b in chunk] == payload, f"downsize packet {index}: data mismatch"
        assert [b[2] for b in chunk] == [0] * (len(payload) - 1) + [1], (
            f"downsize packet {index}: tlast misplaced -- boundary leak")
        assert all(b[1] == FULL_NARROW_KEEP for b in chunk)
        pos += len(payload)

    # --- upsize -------------------------------------------------------------
    up_src, up_snk = sources["up_s"], sinks["up_m"]
    up_snk.beats.clear()
    stream = []
    expect = []
    for payload in payloads:
        stream.extend(to_narrow_beats(payload))
        expect.extend(to_wide_beats(payload))
    await up_src.send(stream)
    await wait_for(up_snk, len(expect), dut.clk_i)
    for _ in range(8):
        await RisingEdge(dut.clk_i)

    assert len(up_snk.beats) == len(expect), (
        f"upsize: {len(up_snk.beats)} wide beats, expected {len(expect)}")
    # This is the leak that matters: a 1-DW packet followed immediately by
    # another must not carry stale keep bits or stale lanes from its
    # predecessor.
    assert list(up_snk.beats) == expect, "upsize: fragment leaked across a packet boundary"

    # --- round trip, back to back ------------------------------------------
    rt_src, rt_snk = sources["rt_s"], sinks["rt_m"]
    rt_snk.beats.clear()
    stream = []
    for payload in payloads:
        stream.extend(to_wide_beats(payload))
    await rt_src.send(stream)
    await wait_for(rt_snk, len(stream), dut.clk_i)
    for _ in range(8):
        await RisingEdge(dut.clk_i)
    assert list(rt_snk.beats) == stream, "round trip: boundary leak between packets"

    for name in ("dn_error", "up_error", "rt_dn_error", "rt_up_error"):
        assert monitors[name].count == 0, f"G10 tripped {name}"
    dut._log.info("G10: %d back-to-back packets, zero idle cycles, no boundary leak",
                  len(sizes))
