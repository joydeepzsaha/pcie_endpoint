"""Exhaustive spec-golden bench for decode_8b10b.

Toplevel: decode_8b10b.  Purely combinational -- datain[9:0] + dispin in;
dataout[8:0], dispout, code_err, disp_err out.  No clock, no reset, no state
(see pcie_docs/evidence/decode-8b10b/CENSUS_8B10B.md sec 2).

WHY THIS BENCH IS THE WHOLE TRUTH AND NOT A SAMPLE
    The input space is 10 code bits x 2 running-disparity states = 2048
    combinations.  Every one is driven.  For a combinational module that is a
    complete proof, not coverage -- the same standing byte_scramble's 65536-state
    sweep has in Rung 3.

ORACLE
    Every expected value comes from tb/scrambler/golden_8b10b.py, which carries
    PCI Express Base Spec Rev 2.1 Table B-1 (p.687-694) and Table B-2 (p.695)
    verbatim.  Nothing here is captured from the DUT.  Claims, page cites and the
    MindShare cross-check live in ORACLES_8B10B.md.

    Governing rule, Base 2.1 sec 4.2.1.3 pp.194-195: a Symbol found in the column for
    the wrong running disparity, OR in neither column, must be reported to the
    Data Link Layer as invalid -- a Receiver Error.  The spec requires ONE
    notification for both modes, so conformance is judged on
    (code_err | disp_err); the individual ports are judged only where the spec
    constrains them.

WHAT THIS BENCH DELIBERATELY DOES NOT ASSERT   (ORACLES_8B10B.md sec 5)
    - dataout on an invalid code-group      -- spec defines no decoded value
    - disp_err on an invalid code-group     -- don't-care under 4.2.1.3, and
                                               decode_8b10b.sv:136 says the same
    - dispout on invalid / disparity-error  -- oracles E2/E3, spec-undefined
    Declining these is a choice, recorded so it is not mistaken for an oversight.

FAILURE REPORTING
    Mismatches are collected and classified per oracle, never first-failure-
    aborted.  A divergence produces a complete map of where decode differs, which
    is the deliverable; one expect_fail row per divergent CLASS would then be
    added, not one per vector.
"""
import cocotb
from cocotb.triggers import Timer

import golden_8b10b as G
from golden_8b10b import RD_NEG, RD_POS, SYMBOLS, BY_NAME, decode, encode

SETTLE_NS = 1

# Every assertion-bearing test registers here, so test 15 can prove the suite
# actually executed its checks rather than skipping them (sec 22.17: an assertion
# that never runs is an empty set, and an empty set passes).
EXECUTED = {}


def _record(name, n):
    EXECUTED[name] = EXECUTED.get(name, 0) + n


async def drive(dut, datain, dispin):
    """Present one code-group at one running disparity; return the DUT's outputs."""
    dut.datain.value = datain & 0x3FF
    dut.dispin.value = dispin & 1
    await Timer(SETTLE_NS, units="ns")
    return {
        "dataout": int(dut.dataout.value) & 0x1FF,
        "dispout": int(dut.dispout.value) & 1,
        "code_err": int(dut.code_err.value) & 1,
        "disp_err": int(dut.disp_err.value) & 1,
    }


def _fmt(datain, rd):
    abcdei, fghj = G.datain_to_code(datain)
    return "%s %s (datain=%03Xh) at RD%s" % (abcdei, fghj, datain, "-" if rd == RD_NEG else "+")


def _report(dut, label, bad, checked, expected_checks=None):
    """Log a complete divergence map, then assert."""
    dut._log.info("%s: %d cases driven, %d divergent" % (label, checked, len(bad)))
    if expected_checks is not None:
        assert checked == expected_checks, (
            "%s drove %d cases, expected %d -- the sweep itself is wrong"
            % (label, checked, expected_checks))
    if bad:
        for line in bad[:24]:
            dut._log.error("  %s" % line)
        if len(bad) > 24:
            dut._log.error("  ... and %d more" % (len(bad) - 24))
    assert not bad, "%s: %d of %d cases diverge from Base 2.1 Appendix B" % (
        label, len(bad), checked)


# ---------------------------------------------------------------------------
# 1 -- the oracle itself, before it is used to judge anything
# ---------------------------------------------------------------------------

@cocotb.test()
async def golden_table_self_test(dut):
    """The golden table must pass its own self-test inside the simulator.

    Run first and separately so that an oracle defect can never be reported as a
    DUT divergence.  Covers: 268 rows with name/hex/bits mutually consistent, the
    popcount invariant off the spec's own table, unambiguous decode within each
    column, a 536/536 encode->decode round trip, the 2048-case partition, eight
    hand-read spot vectors on an independent path from the parser, and a chaining
    control proving the disparity half is not vacuous.
    """
    counts = G.self_test(verbose=False)
    for rd, label in ((RD_NEG, "RD-"), (RD_POS, "RD+")):
        c = counts[rd]
        dut._log.info("golden table at %s: valid %d, disparity_error %d, invalid %d"
                      % (label, c["valid"], c["disparity_error"], c["invalid"]))
        assert (c["valid"], c["disparity_error"], c["invalid"]) == (268, 196, 560)
    _record("golden_table_self_test", 2)


# ---------------------------------------------------------------------------
# 2-4 -- valid decode
# ---------------------------------------------------------------------------

@cocotb.test()
async def exhaustive_valid_d_codes(dut):
    """Oracle A1/A2: all 256 data bytes, both disparities, from Table B-1 p.687-694.

    512 cases.  Each must produce the tabled byte with the K flag CLEAR.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        if sym.is_k:
            continue
        for rd in (RD_NEG, RD_POS):
            code, _ = encode(sym, rd)
            o = await drive(dut, code, rd)
            checked += 1
            if o["dataout"] != sym.dataout:
                bad.append("%s: %s -> dataout %03X, Table B-1 says %03X (%s)"
                           % (sym.name, _fmt(code, rd), o["dataout"], sym.dataout, sym.name))
    _record("exhaustive_valid_d_codes", checked)
    _report(dut, "valid D-code decode", bad, checked, expected_checks=512)


@cocotb.test()
async def exhaustive_valid_k_codes(dut):
    """Oracle B1: all 12 Special Symbols, both disparities, from Table B-2 p.695.

    24 cases.  Each must produce the tabled byte with the K flag SET.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        if not sym.is_k:
            continue
        for rd in (RD_NEG, RD_POS):
            code, _ = encode(sym, rd)
            o = await drive(dut, code, rd)
            checked += 1
            if o["dataout"] != sym.dataout:
                bad.append("%s: %s -> dataout %03X, Table B-2 says %03X"
                           % (sym.name, _fmt(code, rd), o["dataout"], sym.dataout))
    _record("exhaustive_valid_k_codes", checked)
    _report(dut, "valid K-code decode", bad, checked, expected_checks=24)


@cocotb.test()
async def reserved_k_codes_decode_without_error(dut):
    """Oracle B2: K28.4, K28.6 and K28.7 are VALID code-groups.

    Table 4-1 p.194 marks K28.4 and K28.6 "Reserved" and K28.7/EIE "Reserved in
    2.5 GT/s".  But sec 4.2.1.3 p.194 defines validity by membership of the
    Appendix B tables, and all three are in Table B-2 p.695.  Reserved-ness is a
    higher-layer property; a receiver must NOT raise a Receiver Error on them.

    This is the one claim where reading Table 4-1 as the validity list instead of
    Appendix B would produce a decoder that rejects a legal code-group.
    """
    bad, checked = [], 0
    for name in ("K28.4", "K28.6", "K28.7"):
        sym = BY_NAME[name]
        for rd in (RD_NEG, RD_POS):
            code, rd_out = encode(sym, rd)
            o = await drive(dut, code, rd)
            checked += 1
            if o["code_err"] or o["disp_err"]:
                bad.append("%s %s: Receiver Error raised (code_err=%d disp_err=%d) "
                           "on a code-group Table B-2 p.695 lists as valid"
                           % (name, _fmt(code, rd), o["code_err"], o["disp_err"]))
            if o["dataout"] != sym.dataout:
                bad.append("%s %s: dataout %03X, Table B-2 says %03X"
                           % (name, _fmt(code, rd), o["dataout"], sym.dataout))
            if o["dispout"] != rd_out:
                bad.append("%s %s: dispout %d, expected %d"
                           % (name, _fmt(code, rd), o["dispout"], rd_out))
    _record("reserved_k_codes_decode_without_error", checked)
    _report(dut, "reserved K codes are valid", bad, checked, expected_checks=6)


# ---------------------------------------------------------------------------
# 5-6 -- the two Receiver Error classes
# ---------------------------------------------------------------------------

@cocotb.test()
async def exhaustive_invalid_code_groups_raise_code_err(dut):
    """Oracle C1: every code-group in NEITHER column must be reported invalid.

    560 per disparity, 1120 cases.  Base 2.1 sec 4.2.1.3 pp.194-195.

    Judged on code_err, because for this class the spec's "does not correspond to
    either column" maps onto exactly that port.  disp_err is NOT judged here --
    it is a don't-care on an invalid code-group (ORACLES sec 5), which
    decode_8b10b.sv:136 states in the RTL's own words.
    """
    bad, checked = [], 0
    for rd in (RD_NEG, RD_POS):
        for code in range(1024):
            if decode(code, rd).cls != "invalid":
                continue
            o = await drive(dut, code, rd)
            checked += 1
            if not o["code_err"]:
                bad.append("%s: code_err=0, but this code-group is in neither "
                           "column of Appendix B" % _fmt(code, rd))
    _record("exhaustive_invalid_code_groups_raise_code_err", checked)
    _report(dut, "invalid code-group -> Receiver Error", bad, checked, expected_checks=1120)


@cocotb.test()
async def exhaustive_disparity_errors_raise_disp_err(dut):
    """Oracle D1: a legal code-group in the WRONG column must be reported invalid.

    196 per disparity, 392 cases.  Base 2.1 sec 4.2.1.3 pp.194-195: "If a received
    Symbol is found in the column corresponding to the incorrect running
    disparity ... the Physical Layer must notify the Data Link Layer that the
    received Symbol is invalid."

    Judged on (code_err | disp_err) -- the spec requires one notification, not a
    particular port -- and separately on disp_err alone, which is what the RTL's
    own comment at :136 claims to provide ("fires for any legal codes that
    violate disparity").  The two are reported as distinct classes so a
    divergence can be attributed to the requirement or to the RTL's own claim.
    """
    bad_spec, bad_port, checked = [], [], 0
    for rd in (RD_NEG, RD_POS):
        for code in range(1024):
            if decode(code, rd).cls != "disparity_error":
                continue
            o = await drive(dut, code, rd)
            checked += 1
            if not (o["code_err"] or o["disp_err"]):
                bad_spec.append("%s: no Receiver Error, but this code-group is "
                                "legal only at the opposite disparity" % _fmt(code, rd))
            if not o["disp_err"]:
                bad_port.append("%s: disp_err=0 (code_err=%d)" % (_fmt(code, rd), o["code_err"]))
    _record("exhaustive_disparity_errors_raise_disp_err", checked)
    dut._log.info("disparity errors: %d driven, %d miss the spec requirement, "
                  "%d miss disp_err specifically" % (checked, len(bad_spec), len(bad_port)))
    _report(dut, "disparity error -> Receiver Error (spec)", bad_spec, checked,
            expected_checks=392)
    _report(dut, "disparity error -> disp_err (RTL's own claim)", bad_port, checked)


# ---------------------------------------------------------------------------
# 7-9 -- properties of the valid set
# ---------------------------------------------------------------------------

@cocotb.test()
async def valid_code_groups_raise_no_receiver_error(dut):
    """Oracle A3: a valid code-group at the correct disparity is NOT an error.

    536 cases.  The negative half of oracles A1/B1: a decoder that flagged
    everything would satisfy C1 and D1 and be useless.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            code, _ = encode(sym, rd)
            o = await drive(dut, code, rd)
            checked += 1
            if o["code_err"] or o["disp_err"]:
                bad.append("%s %s: spurious Receiver Error (code_err=%d disp_err=%d)"
                           % (sym.name, _fmt(code, rd), o["code_err"], o["disp_err"]))
    _record("valid_code_groups_raise_no_receiver_error", checked)
    _report(dut, "no false Receiver Error on valid input", bad, checked, expected_checks=536)


@cocotb.test()
async def k_flag_is_set_exactly_for_k_codes(dut):
    """Oracles A4/B1/B3: dataout[8] is set iff the code-group is a Special Symbol.

    536 cases.  Both directions in one test because the claim is an iff: a K flag
    stuck high passes "K codes set it" and a flag stuck low passes "D codes clear
    it".  D28.0 is the nearest miss structurally -- its 6b sub-block is 001110,
    one bit from K28's 001111 -- and is included by construction.
    """
    bad, checked = [], 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            code, _ = encode(sym, rd)
            o = await drive(dut, code, rd)
            checked += 1
            k = (o["dataout"] >> 8) & 1
            if k != (1 if sym.is_k else 0):
                bad.append("%s %s: K flag %d, expected %d"
                           % (sym.name, _fmt(code, rd), k, 1 if sym.is_k else 0))
    _record("k_flag_is_set_exactly_for_k_codes", checked)
    _report(dut, "K flag exact", bad, checked, expected_checks=536)


@cocotb.test()
async def dispout_follows_the_disparity_rule(dut):
    """Oracle E1: after a valid code-group, RD inverts iff popcount != 5.

    536 cases.  Base 2.1 prints no update equation; the rule is DERIVED and the
    derivation is proved off the spec's own table (ORACLES_8B10B.md sec 4):
    every RD- column entry has popcount 5 or 6 and every RD+ entry 4 or 5, which
    makes "invert iff not neutral" the unique consistent assignment.
    """
    bad, checked, flipping = [], 0, 0
    for sym in SYMBOLS:
        for rd in (RD_NEG, RD_POS):
            code, rd_out = encode(sym, rd)
            if rd_out != rd:
                flipping += 1
            o = await drive(dut, code, rd)
            checked += 1
            if o["dispout"] != rd_out:
                bad.append("%s %s: dispout %d, expected %d (popcount %d)"
                           % (sym.name, _fmt(code, rd), o["dispout"], rd_out, G.popcount(code)))
    _record("dispout_follows_the_disparity_rule", checked)
    # sec 22.53: if every case were disparity-neutral, dispout == dispin would pass
    # and the test would prove nothing.  Assert the stimulus is not degenerate.
    assert 0 < flipping < checked, (
        "stimulus is a fixed-point set: %d of %d cases invert disparity" % (flipping, checked))
    dut._log.info("dispout: %d of %d cases invert running disparity" % (flipping, checked))
    _report(dut, "dispout disparity rule", bad, checked, expected_checks=536)


# ---------------------------------------------------------------------------
# 10 -- the complete map
# ---------------------------------------------------------------------------

@cocotb.test()
async def complete_partition_map(dut):
    """All 2048 (code-group, disparity) cases, classified against Appendix B.

    The deliverable of this rung: not "does it work" but a complete map of which
    inputs the RTL treats differently from the spec, grouped by oracle class.

    Checks the Receiver Error requirement -- (code_err | disp_err) iff the case is
    not valid -- over the entire input space, and confirms the DUT's own partition
    has exactly the sizes the B-table arithmetic predicts (268 / 196 / 560 per
    disparity, PREDICTIONS_8B10B.md sec 2).
    """
    wrong = {"valid": [], "disparity_error": [], "invalid": []}
    dut_counts = {"valid": 0, "disparity_error": 0, "invalid": 0}
    spec_counts = {"valid": 0, "disparity_error": 0, "invalid": 0}
    checked = 0

    for rd in (RD_NEG, RD_POS):
        for code in range(1024):
            want = decode(code, rd)
            o = await drive(dut, code, rd)
            checked += 1
            spec_counts[want.cls] += 1
            # How the DUT classifies this case, in the spec's own three-way terms.
            if o["code_err"]:
                got = "invalid"
            elif o["disp_err"]:
                got = "disparity_error"
            else:
                got = "valid"
            dut_counts[got] += 1
            dut_error = bool(o["code_err"] or o["disp_err"])
            if dut_error != want.receiver_error:
                wrong[want.cls].append(
                    "%s: spec says %s (Receiver Error %s), DUT gave "
                    "code_err=%d disp_err=%d"
                    % (_fmt(code, rd), want.cls, want.receiver_error,
                       o["code_err"], o["disp_err"]))

    _record("complete_partition_map", checked)
    assert checked == 2048, "drove %d cases, expected the whole space (2048)" % checked
    dut._log.info("spec partition: %s" % spec_counts)
    dut._log.info("DUT  partition: %s" % dut_counts)
    assert spec_counts == {"valid": 536, "disparity_error": 392, "invalid": 1120}, spec_counts

    total_wrong = sum(len(v) for v in wrong.values())
    for cls, items in wrong.items():
        if items:
            dut._log.error("class %s: %d of %d cases diverge" % (cls, len(items), spec_counts[cls]))
            for line in items[:16]:
                dut._log.error("  %s" % line)
    assert total_wrong == 0, (
        "%d of 2048 cases diverge from the Base 2.1 sec 4.2.1.3 Receiver Error "
        "requirement (valid %d, disparity_error %d, invalid %d)"
        % (total_wrong, len(wrong["valid"]), len(wrong["disparity_error"]),
           len(wrong["invalid"])))


# ---------------------------------------------------------------------------
# 11-14 -- sequences.  The state register is outside this module, so these drive
# the DUT's own dispout back into its dispin, which is what the real receive path
# would do.  Single-shot vectors cannot judge disparity history.
# ---------------------------------------------------------------------------

@cocotb.test()
async def chained_stream_decodes_clean(dut):
    """A 268-Symbol stream, running disparity chained through the DUT itself.

    Every symbol of Tables B-1/B-2 in order, encoded with chained RD as a
    conforming transmitter would, then decoded with the DUT's OWN dispout fed
    back as the next dispin.  Zero Receiver Errors, every byte correct, and the
    DUT's disparity track must match the golden one at every step.

    This is the closest a combinational module gets to a state test: if dispout
    were wrong anywhere, the chain diverges and every subsequent symbol fails.
    """
    names = [s.name for s in SYMBOLS]
    codes, _ = G.encode_stream(names, RD_NEG)
    bad, rd_dut, rd_gold = [], RD_NEG, RD_NEG
    for i, (name, code) in enumerate(zip(names, codes)):
        o = await drive(dut, code, rd_dut)
        sym = BY_NAME[name]
        if o["code_err"] or o["disp_err"]:
            bad.append("step %d %s: Receiver Error (code_err=%d disp_err=%d) at dispin=%d"
                       % (i, name, o["code_err"], o["disp_err"], rd_dut))
        if o["dataout"] != sym.dataout:
            bad.append("step %d %s: dataout %03X != %03X" % (i, name, o["dataout"], sym.dataout))
        rd_gold = decode(code, rd_gold).rd_out
        if o["dispout"] != rd_gold:
            bad.append("step %d %s: dispout %d, golden chain says %d"
                       % (i, name, o["dispout"], rd_gold))
        rd_dut = o["dispout"]
    _record("chained_stream_decodes_clean", len(names))
    _report(dut, "chained 268-Symbol stream", bad, len(names), expected_checks=268)


@cocotb.test()
async def held_disparity_stream_is_rejected(dut):
    """Control for the test above -- proves it is not vacuous.

    The same 268-Symbol stream, but with dispin HELD at RD- instead of chained.
    The golden model says 92 of the 268 symbols then arrive against the wrong
    running disparity, so a conforming decoder must raise a Receiver Error on
    exactly those and on no others.

    Without this control, chained_stream_decodes_clean would pass unchanged
    against a decoder that ignored dispin entirely.
    """
    names = [s.name for s in SYMBOLS]
    codes, _ = G.encode_stream(names, RD_NEG)
    bad, flagged = [], 0
    for i, (name, code) in enumerate(zip(names, codes)):
        want = decode(code, RD_NEG)
        o = await drive(dut, code, RD_NEG)
        err = bool(o["code_err"] or o["disp_err"])
        if err:
            flagged += 1
        if err != want.receiver_error:
            bad.append("step %d %s: %s at held RD-, spec says %s"
                       % (i, name, "flagged" if err else "accepted",
                          "Receiver Error" if want.receiver_error else "valid"))
    expected = sum(1 for c in codes if decode(c, RD_NEG).receiver_error)
    _record("held_disparity_stream_is_rejected", len(names))
    dut._log.info("held-disparity control: DUT flagged %d, golden expects %d, of %d"
                  % (flagged, expected, len(names)))
    assert expected == 92, (
        "the control itself is wrong: golden model expects %d rejections, not 92" % expected)
    _report(dut, "held-disparity control", bad, len(names), expected_checks=268)


@cocotb.test()
async def recovery_after_an_invalid_symbol(dut):
    """An invalid code-group must not poison the next Symbol.

    Base 2.1 sec 4.2.1.3 requires the invalid Symbol be reported; it says nothing
    about running disparity afterwards (oracle E2), so this test does NOT assert
    the DUT's dispout on the invalid Symbol.  What it does assert is that when
    the next Symbol is presented at a KNOWN running disparity -- as a receiver
    that has re-established RD would do -- it decodes correctly and raises no
    error.

    Three invalid code-groups, each followed by every K code, in both disparities.
    """
    invalid = [c for c in range(1024) if decode(c, RD_NEG).cls == "invalid"][:3]
    assert len(invalid) == 3
    bad, checked = [], 0
    for bad_code in invalid:
        for rd in (RD_NEG, RD_POS):
            o = await drive(dut, bad_code, rd)
            if not o["code_err"]:
                bad.append("setup: %s did not raise code_err" % _fmt(bad_code, rd))
            for sym in (s for s in SYMBOLS if s.is_k):
                code, rd_out = encode(sym, rd)
                o2 = await drive(dut, code, rd)
                checked += 1
                if o2["code_err"] or o2["disp_err"]:
                    bad.append("after %s: %s %s raised a Receiver Error"
                               % (_fmt(bad_code, rd), sym.name, _fmt(code, rd)))
                if o2["dataout"] != sym.dataout:
                    bad.append("after %s: %s dataout %03X != %03X"
                               % (_fmt(bad_code, rd), sym.name, o2["dataout"], sym.dataout))
                if o2["dispout"] != rd_out:
                    bad.append("after %s: %s dispout %d != %d"
                               % (_fmt(bad_code, rd), sym.name, o2["dispout"], rd_out))
    _record("recovery_after_an_invalid_symbol", checked)
    _report(dut, "recovery after an invalid Symbol", bad, checked, expected_checks=72)


@cocotb.test()
async def recovery_after_a_disparity_error(dut):
    """A disparity error must not poison the next Symbol either.

    Same shape as the test above, for the other failure class: a legal
    code-group presented at the wrong running disparity, followed by a correctly
    disparate Symbol.  Oracle E3 leaves RD after such a Symbol undefined, so
    again only the recovery Symbol is asserted.
    """
    wrong_disp = [c for c in range(1024) if decode(c, RD_NEG).cls == "disparity_error"][:3]
    assert len(wrong_disp) == 3
    bad, checked = [], 0
    for dcode in wrong_disp:
        for rd in (RD_NEG, RD_POS):
            if decode(dcode, rd).cls != "disparity_error":
                continue
            o = await drive(dut, dcode, rd)
            if not (o["code_err"] or o["disp_err"]):
                bad.append("setup: %s raised no Receiver Error" % _fmt(dcode, rd))
            for sym in (s for s in SYMBOLS if s.is_k):
                code, rd_out = encode(sym, rd)
                o2 = await drive(dut, code, rd)
                checked += 1
                if o2["code_err"] or o2["disp_err"]:
                    bad.append("after %s: %s raised a Receiver Error"
                               % (_fmt(dcode, rd), sym.name))
                if o2["dataout"] != sym.dataout:
                    bad.append("after %s: %s dataout %03X != %03X"
                               % (_fmt(dcode, rd), sym.name, o2["dataout"], sym.dataout))
                if o2["dispout"] != rd_out:
                    bad.append("after %s: %s dispout %d != %d"
                               % (_fmt(dcode, rd), sym.name, o2["dispout"], rd_out))
    _record("recovery_after_a_disparity_error", checked)
    _report(dut, "recovery after a disparity error", bad, checked, expected_checks=36)


# ---------------------------------------------------------------------------
# 15 -- sec 22.17 guard
# ---------------------------------------------------------------------------

@cocotb.test()
async def assertions_were_reached(dut):
    """Prove every earlier test actually drove the DUT the number of times it claims.

    sec 22.17: an assertion inside a loop that never iterates is an empty set, and an
    empty set passes.  Every test above registers its driven-case count; this one
    checks the ledger against the counts the B-table arithmetic predicts, so a
    silently-empty sweep cannot ship green.
    """
    expected = {
        "golden_table_self_test": 2,
        "exhaustive_valid_d_codes": 512,
        "exhaustive_valid_k_codes": 24,
        "reserved_k_codes_decode_without_error": 6,
        "exhaustive_invalid_code_groups_raise_code_err": 1120,
        "exhaustive_disparity_errors_raise_disp_err": 392,
        "valid_code_groups_raise_no_receiver_error": 536,
        "k_flag_is_set_exactly_for_k_codes": 536,
        "dispout_follows_the_disparity_rule": 536,
        "complete_partition_map": 2048,
        "chained_stream_decodes_clean": 268,
        "held_disparity_stream_is_rejected": 268,
        "recovery_after_an_invalid_symbol": 72,
        "recovery_after_a_disparity_error": 36,
    }
    missing = [k for k in expected if k not in EXECUTED]
    wrong = [(k, EXECUTED[k], v) for k, v in expected.items()
             if k in EXECUTED and EXECUTED[k] != v]
    for k, got, want in wrong:
        dut._log.error("  %s drove %d cases, expected %d" % (k, got, want))
    assert not missing, "tests that never registered a case count: %s" % ", ".join(sorted(missing))
    assert not wrong, "%d tests drove the wrong number of cases" % len(wrong)
    total = sum(EXECUTED.values())
    dut._log.info("executed-count guard: %d tests, %d DUT evaluations recorded"
                  % (len(EXECUTED), total))
    assert total == sum(expected.values()), "total evaluation count moved"
