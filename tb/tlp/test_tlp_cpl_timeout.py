"""Completion Timeout in tlp_request_tracker -- standalone, CPL_TIMEOUT_CYCLES=64.

Runs on verilate_tlp_cpl_timeout, which overrides the tracker's 4096-cycle
default down to 64 so an expiry costs 64 cycles of simulation instead of 4096.
The mechanism is identical at either value; verilate_tlp_cpl_timeout_default
pins the real default separately.

TIMING MODEL (predicted in SPEC_PREDICTIONS_CPL_TIMEOUT.md SSC, before any of
this ran).  cycle_counter_r and scan_index_r both start at 0 on the first
non-reset edge and increment every cycle, so scan_index_r == cycle_counter_r %
TAG_COUNT.  With C = the cycle_counter_r value the tracker stamps into
alloc_time_r at the allocation edge, and k counting rising edges after it, the
scan sees age == k at edge k, and

    k_fire(tag, C) = min { k >= TIMEOUT : (C + k) % TAG_COUNT == tag }

The strobe is REGISTERED, so cocotb (RisingEdge then a settle delay) reads it as
1 at sample index k_fire -- the N+1 registered-state offset.

WHY C IS READ FROM THE RTL AND NOT MIRRORED IN PYTHON.  The first draft kept a
Python counter ticking alongside cycle_counter_r.  It was wrong twice: once
because it started after reset release, and once because a coroutine reading it
at the same timestamp the mirror wrote it raced the scheduler.  Reading
cycle_counter_r itself (--public-flat-rw) has neither failure mode: a signal
read after the edge has settled is the value the RTL committed.  The predictions
being checked are still independent -- k_fire above is computed in Python.

SCHEDULING DISCIPLINE.  The strobe monitor samples at edge+1ps; every test and
helper settles at edge+SETTLE_PS (3ps), strictly after, so a test never reads
the monitor's log before the monitor has written it.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

TAG_COUNT = 32
TIMEOUT = 64          # must match CPL_TIMEOUT_CYCLES in the target's opts
CLK_NS = 10
SETTLE_PS = 3
RID = 0x1234
CPL_SC = 0


def k_fire(tag, c):
    """First edge after allocation at which `tag` expires.  See module docstring."""
    k = TIMEOUT
    while (c + k) % TAG_COUNT != tag % TAG_COUNT:
        k += 1
    return k


def cyc(dut):
    """cycle_counter_r as committed by the most recent edge."""
    return int(dut.dut.cycle_counter_r.value)


def fire_cycle(tag, c):
    """The cycle_counter_r value the monitor RECORDS for this tag's expiry.

    The scan fires at the edge whose PRE-edge counter is c + k_fire; every
    observer reads counters after that edge, so the recorded value is one
    higher.  Keeping this in one place is the fix for having compared a
    pre-edge prediction against a post-edge observation.
    """
    return c + k_fire(tag, c) + 1


class StrobeMonitor:
    """Records every timeout / late-drain / result beat, tagged with the cycle."""

    def __init__(self, dut):
        self.dut = dut
        self.timeouts = []     # (cycle_counter_r after the fire edge, tag)
        self.lates = []        # (cycle_counter_r after the fire edge, tag)
        self.results = []      # (cycle, context, status, last)

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.dut.clk_i)
            await Timer(1, units="ps")
            now = cyc(self.dut)
            if int(self.dut.cpl_timeout_valid.value):
                self.timeouts.append((now, int(self.dut.cpl_timeout_tag.value)))
            if int(self.dut.late_cpl_valid.value):
                self.lates.append((now, int(self.dut.late_cpl_tag.value)))
            if int(self.dut.result_valid.value) and int(self.dut.result_ready.value):
                self.results.append((now, int(self.dut.result_context.value),
                                     int(self.dut.result_status.value),
                                     int(self.dut.result_last.value)))


async def settle(dut):
    await Timer(SETTLE_PS, units="ps")


async def step(dut, n):
    """Advance n rising edges and settle after the strobe monitor has sampled."""
    for _ in range(n):
        await RisingEdge(dut.clk_i)
    await settle(dut)


async def init(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_NS, units="ns").start())
    dut.rst_i.value = 1
    for name in ("allocate_valid", "completion_valid", "extended_tag_enable",
                 "allocate_requester_id", "allocate_byte_count", "allocate_address",
                 "allocate_context", "allocate_expects_data", "completion_requester_id",
                 "completion_tag", "completion_status", "completion_payload_bytes",
                 "completion_byte_count", "completion_lower_address"):
        getattr(dut, name).value = 0
    dut.result_ready.value = 1
    mon = StrobeMonitor(dut)
    mon.start()
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await step(dut, 1)
    assert cyc(dut) == 1, f"counter should be 1 one edge after reset release, got {cyc(dut)}"
    return mon


async def allocate(dut, byte_count=4, context=0, expects_data=True, rid=RID):
    """Allocate one tag.  Returns (tag, C) where C is what alloc_time_r captured."""
    dut.allocate_requester_id.value = rid
    dut.allocate_byte_count.value = byte_count
    dut.allocate_context.value = context
    dut.allocate_expects_data.value = expects_data
    dut.allocate_address.value = 0
    dut.allocate_valid.value = 1
    await settle(dut)
    while not int(dut.allocate_ready.value):
        await step(dut, 1)
    tag = int(dut.allocate_tag.value)
    await step(dut, 1)
    dut.allocate_valid.value = 0
    c = cyc(dut) - 1
    assert int(dut.dut.alloc_time_r[tag].value) == c, (
        f"alloc_time_r[{tag}]={int(dut.dut.alloc_time_r[tag].value)} but C was computed as {c}")
    return tag, c


async def complete(dut, tag, payload_bytes, byte_count=None, lower=0,
                   status=CPL_SC, rid=RID):
    """Deliver one completion header.  Returns the counter value at the accepting edge."""
    dut.completion_requester_id.value = rid
    dut.completion_tag.value = tag
    dut.completion_status.value = status
    dut.completion_payload_bytes.value = payload_bytes
    dut.completion_byte_count.value = payload_bytes if byte_count is None else byte_count
    dut.completion_lower_address.value = lower
    dut.completion_valid.value = 1
    await settle(dut)
    while not int(dut.completion_ready.value):
        await step(dut, 1)
    await step(dut, 1)
    dut.completion_valid.value = 0
    return cyc(dut) - 1


@cocotb.test()
async def t1_basic_fire(dut):
    """T1: one unanswered request times out at the exact predicted cycle.

    The tag goes to ZOMBIE, not FREE: it stops being offered by the allocator
    but still counts in outstanding_o, per brief SS1.7.
    """
    mon = await init(dut)
    tag, c = await allocate(dut, byte_count=4, context=0xBEE)
    assert tag == 0, f"first allocation should be tag 0, got {tag}"

    expect = k_fire(tag, c)
    assert TIMEOUT <= expect <= TIMEOUT + TAG_COUNT - 1, \
        f"predicted fire k={expect} outside the [{TIMEOUT}, {TIMEOUT+TAG_COUNT-1}] window"

    base = cyc(dut)
    fired_at = None
    for k in range(1, TIMEOUT + TAG_COUNT + 8):
        await step(dut, 1)
        if int(dut.cpl_timeout_valid.value):
            assert fired_at is None, "cpl_timeout_valid must be a ONE-cycle strobe"
            fired_at = k
            assert int(dut.cpl_timeout_tag.value) == tag, \
                f"strobe carried tag {int(dut.cpl_timeout_tag.value)}, expected {tag}"
            assert int(dut.outstanding.value) == 1, \
                f"a zombie still holds its tag; outstanding={int(dut.outstanding.value)}"

    assert fired_at == expect, f"timeout fired at k={fired_at}, predicted k={expect}"
    assert mon.timeouts == [(fire_cycle(tag, c), tag)], f"unexpected strobe log {mon.timeouts}"
    assert base + expect == fire_cycle(tag, c), "fire_cycle and the k-count must agree"

    # Quarantine: still allocatable, but never this tag.
    assert int(dut.allocate_ready.value) == 1, "31 tags are still free"
    assert int(dut.allocate_tag.value) == 1, \
        f"zombie tag 0 must not be offered, allocator offered {int(dut.allocate_tag.value)}"
    assert not mon.results, "a timed-out request must deliver no result"
    assert int(dut.unexpected_completion.value) == 0
    assert not mon.lates, "no completion was sent, so no late drain"


@cocotb.test()
async def t2_wedge_regression(dut):
    """T2 (headline): TAG_COUNT+2 unanswered requests -- the interface RECOVERS.

    Against cc1e194 only 32 allocations are ever possible: allocate_ready_o
    falls and never rises again, so the recorded allocation count stays at 32
    and the final assert fires.  With the timeout every tag walks
    IN_FLIGHT -> ZOMBIE -> FREE and requests 33 and 34 are served.
    """
    mon = await init(dut)
    want = TAG_COUNT + 2
    allocations = []

    async def driver():
        dut.allocate_requester_id.value = RID
        dut.allocate_byte_count.value = 4
        dut.allocate_context.value = 0
        dut.allocate_expects_data.value = True
        dut.allocate_address.value = 0
        dut.allocate_valid.value = 1
        while len(allocations) < want:
            await RisingEdge(dut.clk_i)
            await Timer(1, units="ps")
        dut.allocate_valid.value = 0

    async def watcher():
        while True:
            await Timer(1, units="ps")
            if (int(dut.allocate_valid.value) and int(dut.allocate_ready.value)
                    and len(allocations) < want):
                allocations.append((cyc(dut), int(dut.allocate_tag.value)))
            await RisingEdge(dut.clk_i)

    cocotb.start_soon(watcher())
    cocotb.start_soon(driver())

    await step(dut, TAG_COUNT + 1)
    assert len(allocations) == TAG_COUNT, \
        f"expected exactly {TAG_COUNT} allocations before the pool empties, got {len(allocations)}"
    assert [t for _, t in allocations] == list(range(TAG_COUNT)), \
        f"tags should be 0..{TAG_COUNT-1} in order, got {[t for _, t in allocations]}"
    assert int(dut.allocate_ready.value) == 0, "pool is empty; allocate_ready must be low"
    assert int(dut.outstanding.value) == TAG_COUNT

    bound = 3 * TIMEOUT + 4 * TAG_COUNT
    for _ in range(bound):
        await step(dut, 1)
        if len(allocations) >= want:
            break

    timed_out = sorted(t for _, t in mon.timeouts)
    assert timed_out == list(range(TAG_COUNT)), \
        f"every tag must time out exactly once; got {timed_out}"
    assert len(allocations) == want, (
        f"THE WEDGE: only {len(allocations)} of {want} requests were ever served. "
        "Without a completion timeout the tag pool never recovers.")
    assert allocations[TAG_COUNT][1] in range(TAG_COUNT), "recovered tag must be a real tag"
    assert not mon.lates, "no completions were sent, so no late drains"


@cocotb.test()
async def t3_timer_restarts_on_partial(dut):
    """T3: a partial completion of a split read restarts the timer.

    byte_count=8 answered by a 4-byte first CplD leaves the tag IN_FLIGHT, so
    its clock must reset: the original deadline passes in silence and the real
    expiry is a full interval after the PARTIAL, not after the allocation.
    """
    mon = await init(dut)
    tag, c = await allocate(dut, byte_count=8, context=0x5A5)
    assert tag == 0
    original_fire = fire_cycle(tag, c)

    await step(dut, 60)      # land the partial before the original deadline
    assert not mon.timeouts, "fired before the interval elapsed"
    assert cyc(dut) < original_fire, "test staging error: original deadline already passed"

    c2 = await complete(dut, tag, payload_bytes=4, byte_count=8, lower=0)
    assert len(mon.results) == 1, f"the partial must be delivered, got {mon.results}"
    assert mon.results[0][3] == 0, "a partial completion is not the last CPL"
    assert int(dut.outstanding.value) == 1, "tag stays outstanding after a partial"
    assert c2 > c, "the completion must land after the allocation"

    predicted_fire = fire_cycle(tag, c2)

    # The ORIGINAL deadline must pass in silence -- this is the restart itself.
    await step(dut, (original_fire + 4) - cyc(dut))
    assert not mon.timeouts, (
        f"timer did NOT restart: strobe at {mon.timeouts}, but a partial landed at C={c2} "
        f"and should have pushed the deadline to {predicted_fire}")

    await step(dut, (predicted_fire + 4) - cyc(dut))
    assert len(mon.timeouts) == 1, f"expected exactly one strobe, got {mon.timeouts}"
    fired_cycle, fired_tag = mon.timeouts[0]
    assert fired_tag == tag
    assert fired_cycle == predicted_fire, (
        f"restarted timeout fired at counter {fired_cycle}, predicted {predicted_fire} "
        f"(k'={k_fire(tag, c2)} after the partial at C={c2})")


@cocotb.test()
async def t4_late_completion_single(dut):
    """T4: a late completion is drained silently and returns the tag to FREE.

    Then the tag is reused and a fresh request/completion round-trips on it --
    exactly the property immediate recycle would have broken.
    """
    mon = await init(dut)
    tag, c = await allocate(dut, byte_count=4, context=0xAAA)
    assert tag == 0

    await step(dut, k_fire(tag, c) + 2)
    assert len(mon.timeouts) == 1 and mon.timeouts[0][1] == tag, \
        f"expected one timeout for tag {tag}, got {mon.timeouts}"
    assert not mon.results

    # payload >= remaining, so the last-CPL condition holds: RC descriptor bit 30.
    await complete(dut, tag, payload_bytes=4, byte_count=4, lower=0)

    assert len(mon.lates) == 1, f"expected one late_cpl strobe, got {mon.lates}"
    assert mon.lates[0][1] == tag, f"late strobe carried tag {mon.lates[0][1]}"
    assert not mon.results, \
        "a late completion must NOT be delivered on the result interface"
    assert int(dut.unexpected_completion.value) == 0, \
        "a drained late completion is not an unexpected completion"
    assert int(dut.outstanding.value) == 0, "a bit-30 late CPL returns the tag to FREE"

    tag2, _ = await allocate(dut, byte_count=4, context=0x777)
    assert tag2 == tag, f"the freed tag should be reusable, allocator gave {tag2}"
    await complete(dut, tag2, payload_bytes=4, byte_count=4, lower=0)
    assert len(mon.results) == 1, "the reused tag's completion must be delivered"
    assert mon.results[0][1] == 0x777, \
        f"reused tag delivered context {mon.results[0][1]:#x}, expected 0x777"
    assert mon.results[0][3] == 1, "and it is the last CPL"
    assert len(mon.lates) == 1, "no second late drain"


@cocotb.test()
async def t5_second_expiry_frees(dut):
    """T5: with nothing ever arriving, the zombie is released one interval later.

    Exactly TIMEOUT edges, with no phase term: the scan rewrites the timestamp
    at the timeout edge, and that edge is congruent to the tag mod TAG_COUNT by
    construction (SPEC_PREDICTIONS SSC).
    """
    mon = await init(dut)
    tag, c = await allocate(dut, byte_count=4, context=0x111)
    assert tag == 0

    await step(dut, k_fire(tag, c) + 1)
    assert len(mon.timeouts) == 1, f"expected the first timeout, got {mon.timeouts}"
    timeout_cycle = mon.timeouts[0][0]
    assert int(dut.outstanding.value) == 1, "zombie still counts as outstanding"

    # One edge short of the second interval: still quarantined.
    await step(dut, (timeout_cycle + TIMEOUT - 1) - cyc(dut))
    assert int(dut.outstanding.value) == 1, \
        "released a cycle early -- the second interval is not a full TIMEOUT"
    assert int(dut.allocate_tag.value) == 1, "still not offering the quarantined tag"

    await step(dut, 1)
    assert int(dut.outstanding.value) == 0, (
        f"the zombie must be FREE exactly {TIMEOUT} edges after the timeout edge "
        f"(counter {timeout_cycle + TIMEOUT}), outstanding={int(dut.outstanding.value)}")
    assert int(dut.allocate_tag.value) == tag, "and offered again"
    assert not mon.lates, "T5 sends no completion, so late_cpl must never fire"
    assert len(mon.timeouts) == 1, "the ZOMBIE -> FREE release is silent"
    assert not mon.results
