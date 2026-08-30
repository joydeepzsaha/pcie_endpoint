"""Exhaustive spec-golden bench for encode_8b10b.

Toplevel: encode_8b10b.  Purely combinational -- datain[8:0] + dispin in;
dataout[9:0], dispout, illegal_k_o out.  No clock, no reset, no state.

    illegal_k_o was added by Rung 8 / F1.  Until then the detector existed as an
    internal wire with no port -- correct and unobservable -- so this bench could
    only DECLINE the 488 undefined requests.  It can now assert on them; see T1
    at the end of this file.  ORACLES_ENCODE.md sec 1.1 describes the pre-F1
    state and is superseded on that one point only.

INPUT SPACE, AND THE PART OF IT THE SPEC DOES NOT DEFINE
    9 data bits + 1 disparity bit = 1024 combinations.  All are driven.  But
    unlike the decoder, not all of them have a defined output:

        512  k=0, the 256 D Symbols x 2 disparities   Table B-1 pp.687-694
         24  k=1, the 12 Special Symbols x 2          Table B-2 p.695
        488  k=1, a byte that is NOT a Special Symbol UNDEFINED

    488 of 1024 -- 48% -- have no specified encoding.  This bench asserts on the
    536 defined cases and DECLINES the 488, reporting the count rather than
    quietly skipping them.  Asserting there would invent a requirement.

ORACLE
    tb/scrambler/golden_8b10b.py, which carries Base 2.1 Tables B-1/B-2 verbatim.
    Nothing here is captured from the DUT.

    NOTE the round trip through decode_8b10b is NOT the primary oracle -- see
    ORACLES_ENCODE.md sec 2.2.  A decoder that is the exact inverse of the encoder
    round-trips perfectly whether or not either matches the spec.  X1/X2 compare
    against the table directly and carry the verdict.
"""
import cocotb
from cocotb.triggers import Timer

import golden_8b10b as G
from golden_8b10b import RD_NEG, RD_POS, SYMBOLS, BY_NAME, encode, decode

SETTLE_NS = 1

EXECUTED = {}


def _record(name, n):
    EXECUTED[name] = EXECUTED.get(name, 0) + n


# datain values that are a legal request: k=0 with any byte, or k=1 with one of
# the twelve Special Symbols.  Everything else is undefined input.
DEFINED_DATAIN = {s.dataout: s for s in SYMBOLS}


async def drive(dut, datain, dispin):
    dut.datain.value = datain & 0x1FF
    dut.dispin.value = dispin & 1
    await Timer(SETTLE_NS, units="ns")
    return (int(dut.dataout.value) & 0x3FF, int(dut.dispout.value) & 1)


def _fmt(code):
    abcdei, fghj = G.datain_to_code(code)
    return "%s %s" % (abcdei, fghj)


def _report(dut, label, bad, checked, expected_checks=None):
    dut._log.info("%s: %d cases driven, %d divergent" % (label, checked, len(bad)))
    if expected_checks is not None:
        assert checked == expected_checks, (
            "%s drove %d cases, expected %d -- the sweep itself is wrong"
            % (label, checked, expected_checks))
    for line in bad[:24]:
        dut._log.error("  %s" % line)
    if len(bad) > 24:
        dut._log.error("  ... and %d more" % (len(bad) - 24))
    assert not bad, "%s: %d of %d cases diverge from Base 2.1 Appendix B" % (
        label, len(bad), checked)


@cocotb.test()
async def golden_table_self_test(dut):
    """The oracle passes its own self-test before it is used to judge anything.

    Includes check_comma(): exactly the six (symbol, disparity) pairs of K28.1,
    K28.5 and K28.7 carry the 7-bit comma pattern -- a property independent of the
    parser, the round trip and the partition.
    """
    counts = G.self_test(verbose=False)
    commas = G.check_comma()
    dut._log.info("golden table: comma symbols %s" % ", ".join(commas))
    assert commas == ["K28.1", "K28.5", "K28.7"]
    assert counts[RD_NEG]["valid"] == 268
    _record("golden_table_self_test", 2)


@cocotb.test()
async def exhaustive_d_code_encoding(dut):
    """Oracle X1: 256 data bytes x 2 disparities encode per Table B-1 pp.687-694.

    512 cases, compared against the transcribed table -- not against a decoder.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        if sym.is_k:
            continue
        for rd in (RD_NEG, RD_POS):
            want, _ = encode(sym, rd)
            got, _ = await drive(dut, sym.dataout, rd)
            checked += 1
            if got != want:
                bad.append("%s at RD%s: got %s, Table B-1 says %s"
                           % (sym.name, "-" if rd == RD_NEG else "+",
                              _fmt(got), _fmt(want)))
    _record("exhaustive_d_code_encoding", checked)
    _report(dut, "D-code encoding", bad, checked, expected_checks=512)


@cocotb.test()
async def exhaustive_k_code_encoding(dut):
    """Oracle X2/X8: all 12 Special Symbols x 2 disparities, per Table B-2 p.695.

    Includes K28.4 and K28.6, which Table 4-1 p.194 marks "Reserved", and K28.7,
    "Reserved in 2.5 GT/s".  Appendix B gives encodings for all twelve, so all
    twelve must encode.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        if not sym.is_k:
            continue
        for rd in (RD_NEG, RD_POS):
            want, _ = encode(sym, rd)
            got, _ = await drive(dut, sym.dataout, rd)
            checked += 1
            if got != want:
                bad.append("%s at RD%s: got %s, Table B-2 says %s"
                           % (sym.name, "-" if rd == RD_NEG else "+",
                              _fmt(got), _fmt(want)))
    _record("exhaustive_k_code_encoding", checked)
    _report(dut, "K-code encoding", bad, checked, expected_checks=24)


@cocotb.test()
async def dispout_follows_the_disparity_rule(dut):
    """Oracle X3: dispout inverts iff the emitted code-group is not neutral.

    536 cases.  Asserted against the golden chain, and the stimulus is checked not
    to be a fixed-point set (sec 22.53) -- if every case were disparity-neutral,
    dispout == dispin would pass and prove nothing.
    """
    bad, checked, flipping = [], 0, 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            _, want_rd = encode(sym, rd)
            if want_rd != rd:
                flipping += 1
            _, got_rd = await drive(dut, sym.dataout, rd)
            checked += 1
            if got_rd != want_rd:
                bad.append("%s at RD%s: dispout %d, expected %d"
                           % (sym.name, "-" if rd == RD_NEG else "+", got_rd, want_rd))
    _record("dispout_follows_the_disparity_rule", checked)
    assert 0 < flipping < checked, (
        "stimulus is a fixed-point set: %d of %d invert" % (flipping, checked))
    dut._log.info("dispout: %d of %d cases invert running disparity" % (flipping, checked))
    _report(dut, "dispout disparity rule", bad, checked, expected_checks=536)


@cocotb.test()
async def emitted_code_groups_are_legal(dut):
    """Oracle X5: every emitted code-group carries 4, 5 or 6 ones.

    536 cases.  Equivalent to "neutral or +-2", the invariant check_table() proves
    over all 536 entries of Tables B-1/B-2.  Independent of X1/X2: a wrong-but-
    legal code-group passes this and fails those, and a right code-group emitted
    with a corrupted bit fails this.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            got, _ = await drive(dut, sym.dataout, rd)
            checked += 1
            pc = G.popcount(got)
            if pc not in (4, 5, 6):
                bad.append("%s at RD%s: emitted %s with %d ones"
                           % (sym.name, "-" if rd == RD_NEG else "+", _fmt(got), pc))
    _record("emitted_code_groups_are_legal", checked)
    _report(dut, "emitted code-groups are legal", bad, checked, expected_checks=536)


@cocotb.test()
async def emitted_code_group_is_legal_at_the_running_disparity(dut):
    """Oracle X4: the emitted code-group must be in the column for dispin.

    536 cases.  Stronger than X5: it is not enough for the word to be a legal
    code-group, it must be legal AT THE DISPARITY IN FORCE.  Checked by decoding
    the emitted word with the golden model -- the MODEL, not the RTL decoder.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            got, _ = await drive(dut, sym.dataout, rd)
            checked += 1
            d = decode(got, rd)
            if d.cls != "valid":
                bad.append("%s at RD%s: emitted %s, which is %s at that disparity"
                           % (sym.name, "-" if rd == RD_NEG else "+", _fmt(got), d.cls))
    _record("emitted_code_group_is_legal_at_the_running_disparity", checked)
    _report(dut, "emitted code-group legal at the running disparity", bad, checked,
            expected_checks=536)


@cocotb.test()
async def chained_stream_is_disparity_legal(dut):
    """Oracle X4, as a sequence: a 268-Symbol stream with disparity chained
    through the DUT's own dispout.

    Every Symbol of Tables B-1/B-2 in order.  The DUT's dispout feeds its next
    dispin, as a real transmitter would.  Every emitted word must be valid at the
    disparity in force, and the DUT's disparity track must match the golden one at
    every step -- one wrong dispout derails everything after it.
    """
    bad, rd_dut, rd_gold = [], RD_NEG, RD_NEG
    names = [s.name for s in SYMBOLS]
    for i, name in enumerate(names):
        sym = BY_NAME[name]
        got, got_rd = await drive(dut, sym.dataout, rd_dut)
        want, _ = encode(sym, rd_gold)
        if got != want:
            bad.append("step %d %s: emitted %s, expected %s" % (i, name, _fmt(got), _fmt(want)))
        d = decode(got, rd_dut)
        if d.cls != "valid":
            bad.append("step %d %s: emitted a %s code-group" % (i, name, d.cls))
        rd_gold = decode(want, rd_gold).rd_out
        if got_rd != rd_gold:
            bad.append("step %d %s: dispout %d, golden chain says %d"
                       % (i, name, got_rd, rd_gold))
        rd_dut = got_rd
    _record("chained_stream_is_disparity_legal", len(names))
    _report(dut, "chained 268-Symbol transmit stream", bad, len(names), expected_checks=268)


@cocotb.test()
async def round_trip_through_the_golden_decoder(dut):
    """Oracle X6 -- CORROBORATING ONLY, deliberately not the verdict.

    536 cases.  A decoder that is the exact inverse of the encoder round-trips
    perfectly whether or not either matches the spec, so this test has near-zero
    power on its own (ORACLES_ENCODE.md sec 2.2).  It is run because decode_8b10b was
    independently proven over its whole input space in the previous rung, which
    makes a round-trip failure localise to the encoder -- a property of that
    result, not of the round trip.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            got, _ = await drive(dut, sym.dataout, rd)
            checked += 1
            d = decode(got, rd)
            if d.dataout != sym.dataout:
                bad.append("%s at RD%s: round trip gave %03X, expected %03X"
                           % (sym.name, "-" if rd == RD_NEG else "+",
                              d.dataout if d.dataout is not None else -1, sym.dataout))
    _record("round_trip_through_the_golden_decoder", checked)
    _report(dut, "round trip (corroborating)", bad, checked, expected_checks=536)


@cocotb.test()
async def undefined_k_requests_are_driven_and_declined(dut):
    """Oracle X7: the 488 inputs with no defined encoding.

    k=1 with a byte that is not one of the twelve Special Symbols is a request the
    spec gives no encoding for.  This test asserts NOTHING about dataout or dispout
    and still should not: Base 2.1 defines no output for these inputs, so any
    assertion here would invent a requirement.  (What the module DOES now do is
    raise illegal_k_o on all 488 -- asserted by T1a, not here.)

    What it does do is drive all 488, confirm the count matches the arithmetic,
    and record what the module actually emits -- so the silence is measured rather
    than assumed.  Two things are worth knowing and are logged, not asserted:
    how many of those emissions are nevertheless legal code-groups at the
    disparity in force, and how many collide with a real Symbol's encoding.

    Declining to assert here is a decision, not an oversight.  Asserting would
    invent a requirement Base 2.1 does not make.
    """
    driven = 0
    legal_anyway = 0
    as_control = 0
    as_data = 0
    control_examples = []
    for byte in range(256):
        datain = 0x100 | byte
        if datain in DEFINED_DATAIN:
            continue
        for rd in (RD_NEG, RD_POS):
            got, _ = await drive(dut, datain, rd)
            driven += 1
            d = decode(got, rd)
            if d.cls == "valid" and d.symbol is not None:
                legal_anyway += 1
                if d.symbol.is_k:
                    as_control += 1
                    if len(control_examples) < 12:
                        control_examples.append(
                            "K+%02Xh at RD%s -> %s (%s)"
                            % (byte, "-" if rd == RD_NEG else "+",
                               _fmt(got), d.symbol.name))
                else:
                    as_data += 1
    _record("undefined_k_requests_are_driven_and_declined", driven)
    dut._log.info("undefined K requests: %d driven, %d emitted a code-group that is "
                  "LEGAL at the running disparity and decodes as a real Symbol "
                  "(%d as a CONTROL Symbol, %d as a data Symbol); %d emitted something "
                  "a conforming receiver would reject"
                  % (driven, legal_anyway, as_control, as_data, driven - legal_anyway))
    for ex in control_examples:
        dut._log.info("    silently becomes a control Symbol: %s" % ex)
    assert driven == 488, (
        "expected 488 undefined (datain, disparity) inputs, drove %d -- the "
        "partition arithmetic in ORACLES_ENCODE.md sec 1.2 is wrong" % driven)
    # The only assertion: the space adds up.  512 + 24 + 488 = 1024.
    assert driven + 536 == 1024


@cocotb.test()
async def assertions_were_reached(dut):
    """sec 22.17 guard: every test drove the number of cases it claims."""
    expected = {
        "golden_table_self_test": 2,
        "exhaustive_d_code_encoding": 512,
        "exhaustive_k_code_encoding": 24,
        "dispout_follows_the_disparity_rule": 536,
        "emitted_code_groups_are_legal": 536,
        "emitted_code_group_is_legal_at_the_running_disparity": 536,
        "chained_stream_is_disparity_legal": 268,
        "round_trip_through_the_golden_decoder": 536,
        "undefined_k_requests_are_driven_and_declined": 488,
    }
    missing = [k for k in expected if k not in EXECUTED]
    wrong = [(k, EXECUTED[k], v) for k, v in expected.items()
             if k in EXECUTED and EXECUTED[k] != v]
    for k, got, want in wrong:
        dut._log.error("  %s drove %d cases, expected %d" % (k, got, want))
    assert not missing, "tests that never registered a count: %s" % ", ".join(sorted(missing))
    assert not wrong, "%d tests drove the wrong number of cases" % len(wrong)
    dut._log.info("executed-count guard: %d tests, %d DUT evaluations recorded"
                  % (len(EXECUTED), sum(EXECUTED.values())))


# ---------------------------------------------------------------------------
# T1 (Rung 8 / F1): the illegal-K detector, now that it has a port.
#
# Before F1 the detector existed as an internal wire and drove nothing.  That
# was proved, not assumed: Rung 5's M12b mutation forced `illegalk` permanently
# false and the suite still passed 10/10 (pcie_docs/evidence/rung5/
# MUTANTS_ENCODE.md).  F1 added `illegal_k_o`; these three tests are the first
# that can observe it.
#
# The rule is exact and needs no oracle table: a request is illegal iff it asks
# for a K encoding (datain[8]=1) of a byte that is not one of the twelve Special
# Symbols.  DEFINED_DATAIN already carries that set.
# ---------------------------------------------------------------------------


def _is_illegal_request(datain):
    """True iff datain asks for a K code that Base 2.1 Appendix B does not define."""
    return bool(datain & 0x100) and datain not in DEFINED_DATAIN


@cocotb.test()
async def illegal_k_o_flags_exactly_the_undefined_requests(dut):
    """T1a: over all 1024 inputs, illegal_k_o == "this request has no encoding".

    Exhaustive and two-sided: 488 must flag, 536 must not.  A detector that is
    merely correlated with illegality -- say, one that flags all 256 k=1 bytes --
    fails on the 24 Special-Symbol cases.
    """
    bad = []
    flagged = clear = 0
    for datain in range(512):
        want = _is_illegal_request(datain)
        for rd in (RD_NEG, RD_POS):
            await drive(dut, datain, rd)
            got = int(dut.illegal_k_o.value) & 1
            if got:
                flagged += 1
            else:
                clear += 1
            if got != int(want):
                bad.append("datain=%03x rd=%s: illegal_k_o=%d want %d"
                           % (datain, "-" if rd == RD_NEG else "+", got, want))
    dut._log.info("illegal_k_o: %d flagged, %d clear" % (flagged, clear))
    assert flagged == 488, "expected 488 illegal requests flagged, got %d" % flagged
    assert clear == 536, "expected 536 defined requests clear, got %d" % clear
    _record("illegal_k_o_exact", 1024)
    _report(dut, "T1a illegal_k_o == undefined-request", bad, 1024, 1024)


@cocotb.test()
async def illegal_k_o_is_low_for_every_defined_encoding(dut):
    """T1b: no false positive on any input the spec DOES define.

    Stated separately from T1a because this is the direction that would break a
    working link: a detector that fired on a legal Symbol would reject valid
    traffic.  536 cases -- the 256 D Symbols and 12 K Symbols, both disparities.
    """
    bad = []
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            await drive(dut, sym.dataout, rd)
            if int(dut.illegal_k_o.value) & 1:
                bad.append("%s (datain=%03x) rd=%s: illegal_k_o asserted on a DEFINED Symbol"
                           % (sym.name, sym.dataout, "-" if rd == RD_NEG else "+"))
    _record("illegal_k_o_no_false_positive", len(SYMBOLS) * 2)
    _report(dut, "T1b illegal_k_o low on defined Symbols", bad,
            len(SYMBOLS) * 2, 536)


@cocotb.test()
async def illegal_k_o_is_independent_of_running_disparity(dut):
    """T1c: illegality is a property of the request, not of the link state.

    Whether a code-group exists is a table-membership question; running disparity
    only selects which column.  So the two disparity columns must agree on every
    one of the 512 datain values.  If they ever disagreed, the detector would be
    reading disparity logic it has no business reading.
    """
    bad = []
    for datain in range(512):
        await drive(dut, datain, RD_NEG)
        neg = int(dut.illegal_k_o.value) & 1
        await drive(dut, datain, RD_POS)
        pos = int(dut.illegal_k_o.value) & 1
        if neg != pos:
            bad.append("datain=%03x: illegal_k_o RD- =%d but RD+ =%d" % (datain, neg, pos))
    _record("illegal_k_o_disparity_independent", 512)
    _report(dut, "T1c illegal_k_o independent of dispin", bad, 512, 512)
