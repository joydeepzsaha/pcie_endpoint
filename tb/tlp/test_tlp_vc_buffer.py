import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ---------------------------------------------------------------------------
# tlp_vc_buffer -- the VC0 store-and-forward packet FIFO (tlp_layer.sv:455).
#
# NOTE ON THE NAME: this module has no virtual-channel index.  Its storage is
# data_mem[0:PACKET_DEPTH-1][0:MAX_PACKET_WORDS-1] (tlp_vc_buffer.sv:39) -- the
# outer index is a PACKET SLOT, not a VC.  It is the buffer *for* VC0, and it is
# instantiated exactly once.  Everything below says "slot".
#
# The contract this file pins, with anchors:
#   C1 packet atomicity     -- a TLP is visible downstream only once its last
#                              beat has been accepted (:66, :117, :55).
#                              PCIe Base 2.1 SS2.6.1: flow control is accounted
#                              per whole TLP; a partial TLP must not reach DLL.
#   C2 full != overflow     -- a full packet FIFO is ordinary AXIS backpressure
#                              (:53); overflow_o reports only the oversize-packet
#                              case (:82).  AMBA AXI4-Stream SS2.2.
#   C3 credit metadata      -- class and data credits are latched at the
#                              packet's FIRST beat (:88-92).  PCIe Base 2.1
#                              SS2.6.1: 1 data credit = 4 DW = 16 bytes.
#   C4 asynchronous read    -- the four master-side fields are continuous
#                              assigns off the arrays (:60-63); the read returns
#                              pre-edge contents.
#   C6 in-order slots       -- write and read pointers advance and wrap
#                              independently (:96, :110).  PCIe Base 2.1 SS2.4:
#                              no reordering within a traffic class.
#
# The wrapper narrows the module to PACKET_DEPTH=2, MAX_PACKET_WORDS=16 so that
# a full FIFO, a maximum-length packet and a pointer wrap are all reachable in a
# short sim.  test_tlp_vc_buffer_wrap.py re-runs the storage proofs at a
# NON-power-of-two geometry, where the wrap ternaries are actually live.
# ---------------------------------------------------------------------------

PACKET_DEPTH = 2
MAX_PACKET_WORDS = 16

CLASS_POSTED = 0
CLASS_NON_POSTED = 1
CLASS_COMPLETION = 2

# PCIe Base 2.1 SS2.6.1 maps the three TLP classes onto the three flow-control
# credit pools one-for-one.  tlp_class_e's fourth encoding (UNSUPPORTED) has no
# spec-defined credit pool -- the RTL's default arm is a design choice, not a
# spec consequence, so it is deliberately not asserted here.
CREDIT_CLASS_OF = {
    CLASS_POSTED: 0,
    CLASS_NON_POSTED: 1,
    CLASS_COMPLETION: 2,
}

# Idle poison.  If the buffer ever latched a beat it was not handed, or replayed
# a location it was never given, the readback shows one of these and fails.
POISON_DATA = 0xDEADBEEF
POISON_KEEP = 0x0
POISON_USER = 0x0

# Every wait below is bounded.  A buffer whose read path is broken can stop
# raising m_axis_tlast, in which case transmitting_r never clears and
# packet_valid_o never rises again -- an unbounded wait then spins the simulator
# forever instead of failing, which is what a mutation run looked like before
# this guard existed.  No handshake here legitimately takes more than a few tens
# of cycles.  TEST_TIMEOUT_US is the catch-all for anything the loops miss.
WAIT_LIMIT = 200
TEST_TIMEOUT_US = 100


def _data_credits(length_dw):
    """PCIe Base 2.1 SS2.6.1: one data credit covers 4 DW (16 bytes); a partial
    unit consumes a whole credit.  Derived from the spec, not from the RTL."""
    return (length_dw * 4 + 15) // 16


def _beat_data(tag, i):
    """Per-(packet, beat) datum.  No two beats anywhere in this file share a
    value, so any aliasing of one storage location onto another is visible."""
    return (0xC0DE0000 | (tag << 8) | i) & 0xFFFFFFFF


def _beat_keep(tag, i):
    """Non-degenerate tkeep.  Always non-zero (POISON_KEEP is 0).  The module
    stores and replays tkeep verbatim (:61, :85) and never interprets it, so
    varying it mid-packet is legal stimulus and is the only way keep_mem gets
    covered at all."""
    return (0x1, 0x3, 0x7, 0xF)[(tag + i) % 4]


def _beat_user(tag, i):
    """Non-degenerate tuser in 1..7 (POISON_USER is 0).  user_mem had zero
    coverage before this file drove it."""
    return ((tag * 5 + i * 3) % 7) + 1


def _expected(tag, n):
    """The (data, keep, user, last) tuples a packet of n beats must replay."""
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
    """Poison every slave-side input while no beat is being offered."""
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
    """Drive one whole packet in, honouring tready.  Returns the beats it drove."""
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
    """Handshake one packet out of the packet-granular port (C1/C5)."""
    dut.packet_ready.value = 1
    await _wait_high(dut, lambda: int(dut.packet_valid.value), "packet_valid_o")
    dut.packet_ready.value = 0
    await Timer(1, units="ps")


async def _drain(dut, count):
    """Stream `count` beats out of an already-released packet."""
    dut.m_ready.value = 1
    got = []
    guard = 0
    while len(got) < count:
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
    return got


async def _release_and_drain(dut, expect):
    got = await _drain(dut, len(expect))
    assert got == expect, f"replay mismatch\n  got      {got}\n  expected {expect}"


# ---------------------------------------------------------------------------
# The bench that shipped with the inherited RTL, never run until it was wired
# into a target.  Its spec assertions are kept verbatim -- data credits for
# length_dw=5 is 2 by PCIe Base 2.1 SS2.6.1, and the credit-class mapping is the
# spec's one-for-one.  What changed: every sample is now taken settled (the
# original read .value straight off RisingEdge in two places), s_user is driven
# (it was an undriven input), and tkeep/tuser are checked on replay.
# ---------------------------------------------------------------------------
@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def packet_atomicity_credit_metadata_and_backpressure(dut):
    await _reset(dut)

    first = await _put(dut, tag=0x10, n=3, cls=CLASS_POSTED, length_dw=5)
    second = await _put(dut, tag=0x20, n=2, cls=CLASS_COMPLETION, length_dw=1)

    # C1: both packets complete, so the head is offered; nothing is streaming.
    assert int(dut.packet_valid.value) == 1
    assert int(dut.packet_class.value) == CREDIT_CLASS_OF[CLASS_POSTED]
    assert int(dut.packet_credits.value) == _data_credits(5) == 2
    assert int(dut.m_valid.value) == 0

    # C2: a full packet FIFO is backpressure, and must NOT raise overflow.
    dut.s_data.value = _beat_data(0x30, 0)
    dut.s_keep.value = _beat_keep(0x30, 0)
    dut.s_user.value = _beat_user(0x30, 0)
    dut.s_last.value = 1
    dut.s_valid.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        assert int(dut.s_ready.value) == 0
        assert int(dut.overflow.value) == 0
    _idle(dut)

    # C4/C5: once released, the head beat is held stable while m_ready is low.
    await _release(dut)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_data.value) == first[0][0]

    await _release_and_drain(dut, first)

    # C6: the second packet is now the head, with ITS latched credit metadata.
    await Timer(1, units="ps")
    assert int(dut.packet_valid.value) == 1
    assert int(dut.packet_class.value) == CREDIT_CLASS_OF[CLASS_COMPLETION]
    assert int(dut.packet_credits.value) == _data_credits(1) == 1
    await _release(dut)
    await _release_and_drain(dut, second)


# ---------------------------------------------------------------------------
# Storage-shape coverage.  Everything below exists so that an index-arithmetic
# error in the 2-D -> 1-D reshape cannot pass.  The original bench read back
# only slot 0, never exceeded word offset 2, and never wrapped a pointer.
# ---------------------------------------------------------------------------


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def cross_slot_isolation_at_equal_word_offsets(dut):
    """Distinct payloads at the SAME word offset in different slots, both read
    back.  A flattening that aliases slot 1 onto slot 0 -- or a read path whose
    slot select is stuck -- shows up here as the wrong packet's data."""
    await _reset(dut)

    a = await _put(dut, tag=0x41, n=6, cls=CLASS_POSTED, length_dw=6)
    b = await _put(dut, tag=0x82, n=6, cls=CLASS_NON_POSTED, length_dw=6)

    # The two packets share every word offset 0..5 and share nothing else.
    assert all(x[0] != y[0] for x, y in zip(a, b))

    assert int(dut.packet_class.value) == CREDIT_CLASS_OF[CLASS_POSTED]
    await _release(dut)
    await _release_and_drain(dut, a)

    await Timer(1, units="ps")
    assert int(dut.packet_class.value) == CREDIT_CLASS_OF[CLASS_NON_POSTED]
    await _release(dut)
    await _release_and_drain(dut, b)


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def boundary_first_and_last_word_of_first_and_last_slot(dut):
    """Two maximum-length packets fill both slots end to end, so the flat index
    is exercised at its four corners: (slot 0, word 0), (slot 0, word MAX-1),
    (slot 1, word 0), (slot 1, word MAX-1)."""
    await _reset(dut)

    a = await _put(dut, tag=0x51, n=MAX_PACKET_WORDS, length_dw=MAX_PACKET_WORDS)
    b = await _put(dut, tag=0x93, n=MAX_PACKET_WORDS, length_dw=MAX_PACKET_WORDS)

    # A packet of exactly MAX_PACKET_WORDS is legal -- it must not have tripped
    # the oversize flag on the way in (C2/C8).
    assert int(dut.overflow.value) == 0
    assert int(dut.packet_credits.value) == _data_credits(MAX_PACKET_WORDS)

    await _release(dut)
    await _release_and_drain(dut, a)
    await _release(dut)
    await _release_and_drain(dut, b)


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def async_read_holds_the_current_word_until_the_edge(dut):
    """C4.  With m_ready high the read pointer advances every cycle; sampling in
    the settled window BEFORE each edge must show word k, never word k+1.  This
    pins the asynchronous-read semantic the reshape has to preserve."""
    await _reset(dut)

    a = await _put(dut, tag=0x61, n=8, length_dw=8)
    await _release(dut)

    dut.m_ready.value = 1
    for k in range(8):
        await Timer(1, units="ps")
        assert int(dut.m_valid.value) == 1
        assert int(dut.m_data.value) == a[k][0], f"pre-edge word {k}"
        assert int(dut.m_keep.value) == a[k][1]
        assert int(dut.m_user.value) == a[k][2]
        assert int(dut.m_last.value) == a[k][3]
        await RisingEdge(dut.clk_i)
    dut.m_ready.value = 0
    await Timer(1, units="ps")
    assert int(dut.m_valid.value) == 0


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def concurrent_write_into_one_slot_while_draining_the_other(dut):
    """The reachable read-during-write case (the writer and reader provably never
    share a slot -- tready is low whenever the FIFO is full).  Writing slot 1 on
    the same edges that stream slot 0 must disturb neither."""
    await _reset(dut)

    a = await _put(dut, tag=0x71, n=6, length_dw=6)
    await _release(dut)

    # Start the drain, then push the second packet in beat by beat while the
    # first is still streaming out.
    b_expect = _expected(0xA4, 6)
    dut.m_ready.value = 1
    dut.s_class.value = CLASS_COMPLETION
    dut.s_length.value = 6
    dut.s_has_data.value = 1
    got = []
    for i in range(6):
        dut.s_data.value = b_expect[i][0]
        dut.s_keep.value = b_expect[i][1]
        dut.s_user.value = b_expect[i][2]
        dut.s_last.value = b_expect[i][3]
        dut.s_valid.value = 1
        await Timer(1, units="ps")
        assert int(dut.s_ready.value) == 1, f"writer stalled at beat {i}"
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
    _idle(dut)
    dut.m_ready.value = 0
    await Timer(1, units="ps")

    assert got == a, f"drain corrupted by the concurrent write\n  got {got}"

    await _release(dut)
    await _release_and_drain(dut, b_expect)


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def back_to_back_packets_wrap_both_pointers(dut):
    """C6.  Five packets of varying length through a two-deep FIFO: the write
    and read slot pointers each cross the wrap boundary twice, and the buffer is
    driven both full and empty along the way."""
    await _reset(dut)

    lengths = [1, 4, 2, MAX_PACKET_WORDS, 3]
    pending = []
    for k, n in enumerate(lengths):
        pending.append(await _put(dut, tag=0xB0 + k, n=n, length_dw=n))
        if len(pending) == PACKET_DEPTH:
            # Full: C2 says backpressure without overflow.
            await Timer(1, units="ps")
            assert int(dut.s_ready.value) == 0
            assert int(dut.overflow.value) == 0
            await _release(dut)
            await _release_and_drain(dut, pending.pop(0))

    while pending:
        await _release(dut)
        await _release_and_drain(dut, pending.pop(0))

    await Timer(1, units="ps")
    assert int(dut.packet_valid.value) == 0
    assert int(dut.m_valid.value) == 0


@cocotb.test(timeout_time=TEST_TIMEOUT_US, timeout_unit="us")
async def oversize_packet_raises_overflow(dut):
    """C8, and the self-test for the `overflow == 0` guards above: those
    assertions are only meaningful if this signal can be made to rise at all.
    A source that runs past MAX_PACKET_WORDS inside one packet gets tready low
    AND the flag -- unlike a merely full FIFO, which gets tready low alone."""
    await _reset(dut)

    dut.s_class.value = CLASS_POSTED
    dut.s_length.value = MAX_PACKET_WORDS
    dut.s_has_data.value = 1
    for i in range(MAX_PACKET_WORDS):
        dut.s_data.value = _beat_data(0xC5, i)
        dut.s_keep.value = _beat_keep(0xC5, i)
        dut.s_user.value = _beat_user(0xC5, i)
        dut.s_last.value = 0          # never terminate: run the packet past MAX
        dut.s_valid.value = 1
        await Timer(1, units="ps")
        assert int(dut.s_ready.value) == 1, f"stalled early at beat {i}"
        assert int(dut.overflow.value) == 0, f"premature overflow at beat {i}"
        await RisingEdge(dut.clk_i)

    # The (MAX+1)-th beat of a single packet is refused, and flagged.
    await Timer(1, units="ps")
    assert int(dut.s_ready.value) == 0
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.overflow.value) == 1
    assert int(dut.packet_valid.value) == 0, "an unterminated packet must not be offered"

    _idle(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.overflow.value) == 0, "overflow must not latch once the source backs off"
