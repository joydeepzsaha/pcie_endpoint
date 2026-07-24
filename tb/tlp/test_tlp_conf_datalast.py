"""command_data_last contract probe for tlp_requester (evidence for Joy).

tb-only, ZERO src edits.  Turns two code-reading suspicions about how
src/tlp/tlp_requester.sv treats command_data_last_i into on-the-wire facts:

  1. Spurious command_error_o on a *valid* multi-segment streaming write, where
     the host follows the AXI-Stream convention and asserts command_data_last_i
     exactly once, at the true end of the whole request.
       Lines: tlp_requester.sv:149 (expected_data_last per-*segment*),
              tlp_requester.sv:213-214 (command_data_last_i != expected_data_last
              -> command_error_o).
       Prediction: N segments -> N-1 spurious command_error_o pulses, data fine.

  2. Malformed TLP on an early command_data_last_i (host terminates mid-segment).
       Lines: tlp_requester.sv:125 (length_dw from full segment_bytes_r),
              tlp_requester.sv:152 (packet_data_last_o = expected||last),
              tlp_requester.sv:215-219 (early-abort -> REQ_IDLE).
       Prediction: header declares length_dw=32 (128 B) but only 16 DW of
       payload beats are emitted -> header length > payload = malformed.  Captured
       as an xfail carrying the two on-wire numbers.

Golden values hand-derived from the PCIe spec + the RTL:
  - MEM_WRITE, aligned addr, MPS=128 => segment_bytes=128 => length_dw=32,
    first_be=last_be=0xF (tlp_pkg::tlp_first_be/tlp_last_be, addr_low=0, len%4==0).
  - 6-byte aligned write => length_dw=2, first_be=0xF, last_be=0x3.
  - fmt: TLP_FMT_3DW_DATA = 3'b010 = 2 (tlp_pkg.sv:11).
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

MEM_WRITE = 1


def popcount4(x):
    return bin(int(x) & 0xF).count("1")


async def reset(dut):
    dut.rst_i.value = 1
    for name in ["command_valid", "command_data_valid", "tag_request_ready",
                 "packet_header_ready", "packet_data_ready"]:
        getattr(dut, name).value = 0
    dut.requester_id.value = 0x1234
    dut.max_payload_bytes.value = 128
    dut.max_read_bytes.value = 128
    dut.command_tc.value = 0
    dut.command_attr.value = 0
    dut.command_context.value = 0
    dut.command_prefix_valid.value = 0
    dut.command_prefix.value = 0
    dut.command_digest_valid.value = 0
    dut.command_digest.value = 0
    dut.command_data.value = 0
    dut.command_keep.value = 0xF
    dut.command_data_last.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)


async def issue(dut, command, address, count, mps=128):
    """Post a command and wait for it to be accepted (REQ_IDLE handshake)."""
    dut.max_payload_bytes.value = mps
    dut.command.value = command
    dut.command_address.value = address
    dut.command_byte_count.value = count
    dut.command_valid.value = 1
    while not int(dut.command_ready.value):
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.command_valid.value = 0


class Sink:
    """Always-ready packet sink + per-cycle monitor.

    Samples at ReadOnly (values settled for the cycle) so every emitted header,
    every forwarded payload beat, and every command_error_o pulse is counted
    exactly once.  command_error_o is a registered 1-cycle pulse (cleared to 0
    every cycle at tlp_requester.sv:173), so #high-cycles == #error events.
    """

    def __init__(self, dut):
        self.dut = dut
        self.headers = []       # (fmt, length_dw, first_be, last_be, address)
        self.beats = 0          # forwarded payload beats (valid && ready)
        self.payload_bytes = 0  # sum of popcount(packet_keep) over forwarded beats
        self.last_beats = 0     # beats carrying packet_data_last_o
        self.errors = 0         # command_error_o pulses
        self.run = True

    async def run_loop(self):
        d = self.dut
        while self.run:
            d.packet_header_ready.value = 1
            d.packet_data_ready.value = 1
            await ReadOnly()
            if int(d.packet_header_valid.value) and int(d.packet_header_ready.value):
                self.headers.append((
                    int(d.packet_fmt.value), int(d.packet_length_dw.value),
                    int(d.packet_first_be.value), int(d.packet_last_be.value),
                    int(d.packet_address.value)))
            if int(d.packet_data_valid.value) and int(d.packet_data_ready.value):
                self.beats += 1
                self.payload_bytes += popcount4(int(d.packet_keep.value))
                if int(d.packet_data_last.value):
                    self.last_beats += 1
            if int(d.command_error.value):
                self.errors += 1
            await RisingEdge(d.clk_i)


async def start_sink(dut):
    dut.packet_header_ready.value = 1
    dut.packet_data_ready.value = 1
    sink = Sink(dut)
    cocotb.start_soon(sink.run_loop())
    return sink


async def stop_sink(dut, sink):
    sink.run = False
    for _ in range(2):
        await RisingEdge(dut.clk_i)


async def stream(dut, total_bytes, last_at_byte, max_cycles=4000):
    """AXI-Stream source: push total_bytes, assert command_data_last_i on the
    beat whose cumulative byte total first reaches last_at_byte.  Holds each beat
    until command_data_ready_o (which drops to 0 while the DUT is in REQ_HEADER
    between segments), so streaming stays continuous across segment boundaries.
    Returns the number of beats the DUT accepted."""
    sent = 0
    accepted = 0
    cyc = 0
    while sent < total_bytes and cyc < max_cycles:
        remaining = total_bytes - sent
        keep = 0xF if remaining >= 4 else (0xF >> (4 - remaining))
        this_bytes = popcount4(keep)
        last = 1 if (sent + this_bytes) >= last_at_byte else 0
        dut.command_data.value = 0xA0000000 | (accepted & 0xFFFF)
        dut.command_keep.value = keep
        dut.command_data_last.value = last
        dut.command_data_valid.value = 1
        await ReadOnly()
        ready = int(dut.command_data_ready.value)
        await RisingEdge(dut.clk_i)
        cyc += 1
        if ready:
            sent += this_bytes
            accepted += 1
    dut.command_data_valid.value = 0
    dut.command_data_last.value = 0
    return accepted


async def push_beats(dut, num_beats, assert_last=False, max_cycles=200):
    """Try to push num_beats full-DW beats (never asserting last unless told),
    tolerating non-acceptance.  Used for the over-run probe: keep command_data
    valid past the command's byte count and confirm the DUT stops accepting."""
    accepted = 0
    cyc = 0
    idle_after = 0
    while accepted < num_beats and cyc < max_cycles:
        dut.command_data.value = 0xB0000000 | accepted
        dut.command_keep.value = 0xF
        dut.command_data_last.value = 1 if assert_last else 0
        dut.command_data_valid.value = 1
        await ReadOnly()
        ready = int(dut.command_data_ready.value)
        idle = int(dut.command_ready.value)
        await RisingEdge(dut.clk_i)
        cyc += 1
        if ready:
            accepted += 1
            idle_after = 0
        elif idle:
            # DUT is back in REQ_IDLE while we still assert valid -> it stopped.
            idle_after += 1
            if idle_after > 3:
                break
    dut.command_data_valid.value = 0
    dut.command_data_last.value = 0
    return accepted


# ---------------------------------------------------------------------------
# Test 1 -- multi-segment streaming write, host raises `last` once at true end.
# ---------------------------------------------------------------------------

@cocotb.test()
async def valid_stream_two_segments_spurious_error(dut):
    """256 B / MPS 128 => two 128 B TLPs.  Host asserts command_data_last_i only
    on the final beat (correct AXIS).  PREDICT: 2 headers length_dw=32 at 0x2000
    & 0x2080, 64 payload beats / 256 B, and command_error_o fires ZERO times --
    command_error_o now compares against end-of-request (request_last), not the
    per-segment boundary, so a valid multi-segment write is clean."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    sink = await start_sink(dut)

    await issue(dut, MEM_WRITE, 0x2000, 256, mps=128)
    accepted = await stream(dut, total_bytes=256, last_at_byte=256)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    await stop_sink(dut, sink)

    assert accepted == 64, f"accepted beats {accepted} != 64"
    assert sink.beats == 64, f"forwarded beats {sink.beats} != 64"
    assert sink.payload_bytes == 256, f"payload {sink.payload_bytes} != 256"
    assert sink.headers == [
        (2, 32, 0xF, 0xF, 0x2000),
        (2, 32, 0xF, 0xF, 0x2080),
    ], f"headers {[tuple(hex(x) for x in h) for h in sink.headers]}"
    # One packet_data_last per TLP -> confirms the split into two packets.
    assert sink.last_beats == 2, f"last beats {sink.last_beats} != 2"
    # PROOF OF FIX: valid streaming write, correct data, ZERO spurious errors.
    # (Before the end-of-request fix this pulsed N-1=1 time at the internal
    # segment boundary; command_error_o now keys off request_last, not
    # expected_data_last, so genuine host/command disagreements alone flag.)
    assert sink.errors == 0, (
        f"valid multi-segment write must not error (was N-1=1 spurious before "
        f"the request_last fix), got {sink.errors}")
    dut._log.info(
        "TEST1: 2x length_dw=32 TLPs @0x2000/0x2080, 256 B correct payload, "
        "command_error_o pulses=%d (clean after end-of-request fix)",
        sink.errors)


@cocotb.test()
async def valid_stream_three_segments_generalizes(dut):
    """384 B / MPS 128 => three TLPs.  PREDICT: 3 headers, and command_error_o
    fires ZERO times -- the fix generalizes: no per-segment spurious pulses at
    any N (was N-1=2 before the request_last fix)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    sink = await start_sink(dut)

    await issue(dut, MEM_WRITE, 0x2000, 384, mps=128)
    accepted = await stream(dut, total_bytes=384, last_at_byte=384)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    await stop_sink(dut, sink)

    assert accepted == 96, f"accepted beats {accepted} != 96"
    assert sink.beats == 96 and sink.payload_bytes == 384
    assert sink.headers == [
        (2, 32, 0xF, 0xF, 0x2000),
        (2, 32, 0xF, 0xF, 0x2080),
        (2, 32, 0xF, 0xF, 0x2100),
    ], f"headers {[tuple(hex(x) for x in h) for h in sink.headers]}"
    assert sink.last_beats == 3
    assert sink.errors == 0, (
        f"valid 3-segment write must not error (was N-1=2 spurious before the "
        f"request_last fix), got {sink.errors}")
    dut._log.info(
        "TEST1b: 3 segments -> command_error_o pulses=%d (clean, generalizes)",
        sink.errors)


# ---------------------------------------------------------------------------
# Test 2 -- early-termination short write (the dangerous case).
# ---------------------------------------------------------------------------

@cocotb.test()
async def early_last_makes_malformed_tlp(dut):
    """command_byte_count=256 (=> segment_bytes=128 => header length_dw=32), but
    the host raises command_data_last_i after only 64 B (16 DW), mid-segment.

    PREDICT (xfail): the emitted TLP header declares length_dw=32 (128 B) while
    only 16 DW of payload beats are actually forwarded with packet_data_last_o
    -> header length > payload sent = malformed TLP a real completer rejects.
    The two on-wire numbers are asserted below; the mismatch is the fact."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    sink = await start_sink(dut)

    await issue(dut, MEM_WRITE, 0x3000, 256, mps=128)
    accepted = await stream(dut, total_bytes=64, last_at_byte=64)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    await stop_sink(dut, sink)

    # On-wire facts, asserted so the numbers are captured whether or not malformed.
    assert accepted == 16, f"accepted beats {accepted} != 16"
    assert len(sink.headers) == 1, f"expected 1 header, got {len(sink.headers)}"
    header_len_dw = sink.headers[0][1]
    payload_dw = sink.payload_bytes // 4
    assert header_len_dw == 32, f"header length_dw {header_len_dw} != 32"
    assert payload_dw == 16, f"payload DW {payload_dw} != 16"
    assert sink.last_beats == 1, "expected exactly one terminating beat"
    assert sink.errors == 1, f"expected 1 command_error_o, got {sink.errors}"
    # DUT recovered for the next command.
    assert int(dut.command_ready.value) == 1

    dut._log.info(
        "TEST2: on-wire header length_dw=%d (%d B) vs payload beats=%d DW (%d B) "
        "-> MALFORMED (header length > payload). command_error_o=%d.",
        header_len_dw, header_len_dw * 4, payload_dw, sink.payload_bytes,
        sink.errors)

    # The malformed-TLP fact, recorded as an xfail: header-declared length must
    # equal payload actually sent; here it does not.
    assert header_len_dw == payload_dw, (
        f"MALFORMED TLP (expected fact): header length_dw={header_len_dw} "
        f"({header_len_dw*4} B) but only payload_dw={payload_dw} "
        f"({sink.payload_bytes} B) forwarded with packet_data_last_o. "
        f"Early command_data_last_i -> REQ_IDLE abort keeps the header's "
        f"length computed from the full segment_bytes_r. See "
        f"tlp_requester.sv:125,152,215-219.")


# Register the malformed-TLP result as an expected failure carrying the numbers.
early_last_makes_malformed_tlp.expect_fail = True


# ---------------------------------------------------------------------------
# Test 3 (optional) -- over-run: host keeps valid past the byte count.
# ---------------------------------------------------------------------------

@cocotb.test()
async def overrun_stops_cleanly_at_byte_count(dut):
    """command_byte_count=64 (single 16-DW segment).  Host keeps command_data
    valid for 24 beats and never asserts last.  PREDICT: DUT forwards exactly 16
    beats (64 B), pulses command_error_o once at the boundary (missing local EOP),
    returns to REQ_IDLE, and forwards NO extra beats past the byte count."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    sink = await start_sink(dut)

    await issue(dut, MEM_WRITE, 0x5000, 64, mps=128)
    accepted = await push_beats(dut, num_beats=24, assert_last=False)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    await stop_sink(dut, sink)

    assert sink.headers == [(2, 16, 0xF, 0xF, 0x5000)], \
        f"headers {[tuple(hex(x) for x in h) for h in sink.headers]}"
    assert sink.beats == 16, f"forwarded {sink.beats} != 16 (over-run leaked)"
    assert sink.payload_bytes == 64, f"payload {sink.payload_bytes} != 64"
    assert accepted == 16, f"DUT accepted {accepted} beats, expected 16"
    assert sink.errors == 1, f"expected 1 error (missing EOP), got {sink.errors}"
    assert int(dut.command_ready.value) == 1
    dut._log.info(
        "TEST3: over-run held valid past byte count; DUT stopped at %d beats "
        "(64 B), no leak; command_error_o=%d.", sink.beats, sink.errors)


# ---------------------------------------------------------------------------
# Test 4 (optional) -- partial-keep final beat, correct AXIS write.
# ---------------------------------------------------------------------------

@cocotb.test()
async def partial_keep_final_beat_accounting(dut):
    """6-byte aligned write (not a multiple of 4).  Beat0 keep=0xF (4 B), beat1
    keep=0x3 (2 B) + command_data_last_i.  PREDICT: header length_dw=2,
    first_be=0xF, last_be=0x3; accepted_bytes popcount accounting closes the
    segment exactly at 6 B with NO command_error_o (host raised last correctly)."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset(dut)
    sink = await start_sink(dut)

    await issue(dut, MEM_WRITE, 0x6000, 6, mps=128)
    accepted = await stream(dut, total_bytes=6, last_at_byte=6)
    for _ in range(4):
        await RisingEdge(dut.clk_i)
    await stop_sink(dut, sink)

    assert accepted == 2, f"accepted beats {accepted} != 2"
    assert sink.headers == [(2, 2, 0xF, 0x3, 0x6000)], \
        f"headers {[tuple(hex(x) for x in h) for h in sink.headers]}"
    assert sink.beats == 2 and sink.payload_bytes == 6, \
        f"beats {sink.beats}, payload {sink.payload_bytes}"
    assert sink.last_beats == 1
    assert sink.errors == 0, (
        f"correct partial-keep write must not error; got {sink.errors}")
    dut._log.info(
        "TEST4: 6 B partial-keep write closed at %d B, first_be=0xF last_be=0x3, "
        "command_error_o=%d (clean).", sink.payload_bytes, sink.errors)
