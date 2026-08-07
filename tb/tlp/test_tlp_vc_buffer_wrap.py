import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ---------------------------------------------------------------------------
# tlp_vc_buffer at a NON-power-of-two geometry: PACKET_DEPTH=3, MAX_PACKET_WORDS=5.
#
# Why a second geometry exists at all.  The slot pointers are
# logic [$clog2(PACKET_DEPTH)-1:0] (tlp_vc_buffer.sv:46).  At PACKET_DEPTH=2 that
# is one bit and at 4 it is two, so the counter wraps on its own width and the
# explicit `wr_packet_r == PACKET_DEPTH-1 ? '0 : wr_packet_r + 1` (:96, and :110
# for the read side) is unobservable -- mutate the bound and nothing changes.
# At PACKET_DEPTH=3 the pointer is two bits wide but must wrap at 2, so the
# ternary is the only thing standing between the buffer and a fourth slot that
# does not exist.  MAX_PACKET_WORDS=5 likewise makes the word bound a real
# comparison rather than a carry-out, which is the case the shipped instance is
# actually in (tlp_layer.sv:455 leaves MAX_PACKET_WORDS at its 1030 default).
#
# Same contract as test_tlp_vc_buffer.py; see that file's header for the anchors.
# ---------------------------------------------------------------------------

PACKET_DEPTH = 3
MAX_PACKET_WORDS = 5

CLASS_POSTED = 0
CLASS_NON_POSTED = 1
CLASS_COMPLETION = 2

CREDIT_CLASS_OF = {
    CLASS_POSTED: 0,
    CLASS_NON_POSTED: 1,
    CLASS_COMPLETION: 2,
}

POISON_DATA = 0xDEADBEEF
POISON_KEEP = 0x0
POISON_USER = 0x0

# Every wait below is bounded; see test_tlp_vc_buffer.py for why an unbounded
# one hangs the simulator rather than failing when the read path is broken.
WAIT_LIMIT = 200
TEST_TIMEOUT_US = 100


def _data_credits(length_dw):
    """PCIe Base 2.1 SS2.6.1: one data credit covers 4 DW (16 bytes)."""
    return (length_dw * 4 + 15) // 16


def _beat_data(tag, i):
    return (0xBEEF0000 | (tag << 8) | i) & 0xFFFFFFFF


def _beat_keep(tag, i):
    return (0x1, 0x3, 0x7, 0xF)[(tag + i) % 4]


def _beat_user(tag, i):
    return ((tag * 5 + i * 3) % 7) + 1


def _expected(tag, n):
    return [
        (_beat_data(tag, i), _beat_keep(tag, i), _beat_user(tag, i), int(i == n - 1))
        for i in range(n)
    ]


async def _wait_high(dut, probe, what):
    """Wait until `probe()` reads high in the settled window before an edge, then
    take that edge.  Bounded so a wedged DUT fails with a message instead of
    spinning the simulator."""
    for _ in range(WAIT_LIMIT):
        await Timer(1, units="ps")
        hit = probe()
        await RisingEdge(dut.clk_i)
        if hit:
            return
    raise AssertionError("timed out after %d cycles waiting for %s" % (WAIT_LIMIT, what))


def _idle(dut):
    dut.s_valid.value = 0
    dut.s_last.value = 0
    dut.s_data.value = POISON_DATA
    dut.s_keep.value = POISON_KEEP
    dut.s_user.value = POISON_USER


async def _reset(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    _idle(dut)
    dut.s_class.value = 0
    dut.s_length.value = 0
    dut.s_has_data.value = 0
    dut.packet_ready.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")


async def _put(dut, tag, n, cls=CLASS_POSTED, length_dw=None, has_data=1):
    if length_dw is None:
        length_dw = n
    dut.s_class.value = cls
    dut.s_length.value = length_dw
    dut.s_has_data.value = has_data
    for i in range(n):
        dut.s_data.value = _beat_data(tag, i)
        dut.s_keep.value = _beat_keep(tag, i)
        dut.s_user.value = _beat_user(tag, i)
        dut.s_last.value = int(i == n - 1)
        dut.s_valid.value = 1
        # s_ready is a function of registered state only (:53), so it is stable
        # across the cycle; sample it settled, then take the edge.
        await _wait_high(dut, lambda: int(dut.s_ready.value),
                         "s_axis_tready at beat %d of packet 0x%x" % (i, tag))
    _idle(dut)
    await Timer(1, units="ps")
    return _expected(tag, n)


async def _release(dut):
    dut.packet_ready.value = 1
    await _wait_high(dut, lambda: int(dut.packet_valid.value), "packet_valid_o")
    dut.packet_ready.value = 0
    await Timer(1, units="ps")


async def _drain(dut, expect):
    dut.m_ready.value = 1
    got = []
    guard = 0
    while len(got) < len(expect):
        guard += 1
        assert guard <= WAIT_LIMIT, "timed out draining a packet"
        await Timer(1, units="ps")
        if int(dut.m_valid.value):
            got.append(
                (
                    int(dut.m_data.value),
                    int(dut.m_keep.value),
                    int(dut.m_user.value),
                    int(dut.m_last.value),
                )
            )
        await RisingEdge(dut.clk_i)
    dut.m_ready.value = 0
    await Timer(1, units="ps")
    assert got == expect, f"replay mismatch\n  got      {got}\n  expected {expect}"


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def slot_pointers_wrap_at_a_non_power_of_two_depth(dut):
    """Nine packets through a three-deep FIFO: each slot pointer crosses the
    2 -> 0 wrap three times.  A wrap bound that lets the pointer reach 3 walks
    off the end of a three-slot array; a wrap that fires one slot early aliases
    two live packets onto one slot.  Both are payload-visible here."""
    await _reset(dut)

    pending = []
    for k in range(9):
        n = 1 + (k % MAX_PACKET_WORDS)
        pending.append((await _put(dut, tag=0x10 + k, n=n, length_dw=n), n))
        if len(pending) == PACKET_DEPTH:
            await Timer(1, units="ps")
            assert int(dut.s_ready.value) == 0, "a full FIFO must backpressure"
            assert int(dut.overflow.value) == 0, "a full FIFO is not an overflow"
            expect, _ = pending.pop(0)
            await _release(dut)
            await _drain(dut, expect)

    while pending:
        expect, _ = pending.pop(0)
        await _release(dut)
        await _drain(dut, expect)

    await Timer(1, units="ps")
    assert int(dut.packet_valid.value) == 0
    assert int(dut.m_valid.value) == 0


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def every_slot_holds_a_maximum_length_packet(dut):
    """All three slots filled with MAX_PACKET_WORDS-word packets at once, so the
    flat index is driven to the very top of its range (slot DEPTH-1, word MAX-1)
    while every other slot still holds live data.  Distinct payloads at equal
    word offsets across all three slots make any aliasing visible."""
    await _reset(dut)

    packets = [
        await _put(dut, tag=0x40 + 0x11 * k, n=MAX_PACKET_WORDS, length_dw=MAX_PACKET_WORDS)
        for k in range(PACKET_DEPTH)
    ]

    # No two slots share a datum at any word offset.
    for off in range(MAX_PACKET_WORDS):
        column = [p[off][0] for p in packets]
        assert len(set(column)) == PACKET_DEPTH, f"stimulus collides at offset {off}"

    await Timer(1, units="ps")
    assert int(dut.s_ready.value) == 0
    assert int(dut.overflow.value) == 0
    assert int(dut.packet_credits.value) == _data_credits(MAX_PACKET_WORDS)

    for expect in packets:
        await _release(dut)
        await _drain(dut, expect)


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def credit_metadata_tracks_the_slot_not_the_head(dut):
    """Three packets with three different classes and lengths resident at once.
    packet_credit_class_o / packet_data_credits_o are combinational reads of
    class_mem/credit_mem at rd_packet_r (:56-57), so this catches a metadata
    array whose slot select disagrees with the payload array's."""
    await _reset(dut)

    spec = [
        (CLASS_COMPLETION, 5, 3),
        (CLASS_POSTED, 1, 1),
        (CLASS_NON_POSTED, 4, 5),
    ]
    packets = []
    for k, (cls, length_dw, n) in enumerate(spec):
        packets.append(await _put(dut, tag=0x70 + k, n=n, cls=cls, length_dw=length_dw))

    for (cls, length_dw, _), expect in zip(spec, packets):
        await Timer(1, units="ps")
        assert int(dut.packet_class.value) == CREDIT_CLASS_OF[cls]
        assert int(dut.packet_credits.value) == _data_credits(length_dw)
        await _release(dut)
        await _drain(dut, expect)


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def no_data_packet_reports_zero_data_credits(dut):
    """C3's other arm: with s_packet_has_data_i low the latched credit count is
    0 regardless of the advertised length (:90-91).  PCIe Base 2.1 SS2.6.1 -- a
    TLP without a data payload consumes header credit only."""
    await _reset(dut)

    a = await _put(dut, tag=0x91, n=2, cls=CLASS_NON_POSTED, length_dw=7, has_data=0)
    await Timer(1, units="ps")
    assert int(dut.packet_credits.value) == 0
    assert int(dut.packet_class.value) == CREDIT_CLASS_OF[CLASS_NON_POSTED]

    b = await _put(dut, tag=0x92, n=2, cls=CLASS_NON_POSTED, length_dw=7, has_data=1)

    await _release(dut)
    await _drain(dut, a)

    # The second packet advertised the same length WITH data: non-zero, and the
    # guard above is therefore not vacuous.
    await Timer(1, units="ps")
    assert int(dut.packet_credits.value) == _data_credits(7) == 2
    await _release(dut)
    await _drain(dut, b)
