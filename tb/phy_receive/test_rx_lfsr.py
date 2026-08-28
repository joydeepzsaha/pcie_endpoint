"""T1 -- spec-golden unit bench for byte_scramble (the 8-shift LFSR advance).

Toplevel: byte_scramble.  Purely combinational: lfsr_q[15:0] + disable_scrambling
in, lfsr_out[15:0] out.  No clock.

Oracle A1 (ORACLES_PHY_RX.md): Base 2.1 Appendix C.1 p.698 gives the sixteen
equations for advancing the scrambling LFSR eight serial shifts in one operation,
for G(X) = X^16 + X^5 + X^4 + X^3 + 1 (sec 4.2.3 p.199).  Because the module is
combinational with a 16-bit state input, the claim can be settled *exhaustively*
rather than sampled -- all 65536 states are driven.

The golden model is anchored independently: Base 2.1 p.700 publishes the first
128 LFSR states following a reset, and the byte sequence produced by repeatedly
scrambling 00h.  test_spec_p700_state_table and test_spec_p700_scrambled_zeros
check the DUT against that published data, not against the equations the model
was built from.

Nothing in this file is captured from the DUT.
"""
import cocotb
from cocotb.triggers import Timer

from rx_golden import advance, xor_mask, Descrambler

SETTLE_NS = 1

# Base 2.1 p.700, first table: the first 128 LFSR values following a reset.
SPEC_LFSR_128 = """
FFFF E817 0328 284B 4DE8 E755 404F 4140 4E79 761E 1466 6574 7DBD B6E5 FDA6 B165
7D09 02E5 E572 673D 34CF CB54 4743 4DEF E055 40E0 EE40 54BE B334 2C7B 7D0C 07E5
E5AF BA3D 248A 8DC4 D995 85A1 BD5D 4425 2BA4 A2A3 B8D2 CBF8 EB43 5763 6E7F 773E
345F 5B54 5853 5F18 14B7 B474 6CD4 DC4C 5C7C 70FC F6F0 E6E6 F376 603B 3260 64C2
CB84 9743 5CBF B3FC E47B 6E04 0C3E 3F2C 29D7 D1D1 C069 7BC0 CB73 6043 4A60 6FFA
F207 1102 01A9 A939 2351 566B 6646 4FF6 F927 3081 85B0 AC5D 478C 82EF F3F2 E43B
2E04 027E 7E72 79AE A501 1A7D 7F2A 2197 9019 0610 1096 9590 8FCD D0E7 F650 46E6
E8D6 C228 3AB2 B70A 129F 9CE2 FC3C 2B5C 5AA3 AF6A 70C7 CDF0 E3D5 C0AB B9C0 D9C1
""".split()

# Base 2.1 p.700, second table: 00h repeatedly encoded after reset.
SPEC_ZERO_SCRAMBLED = """
FF 17 C0 14 B2 E7 02 82 72 6E 28 A6 BE 6D BF 8D
BE 40 A7 E6 2C D3 E2 B2 07 02 77 2A CD 34 BE E0
A7 5D 24 B1 9B A1 BD 22 D4 45 1D D3 D7 EA 76 EE
2C DA 1A FA 28 2D 36 3B 3A 0E 6F 67 CF 06 4C 26
""".split()


async def step(dut, lfsr_q, disable=0):
    """Drive one combinational evaluation and return lfsr_out."""
    dut.lfsr_q.value = lfsr_q & 0xFFFF
    dut.disable_scrambling.value = disable & 1
    await Timer(SETTLE_NS, units="ns")
    return int(dut.lfsr_out.value) & 0xFFFF


@cocotb.test()
async def exhaustive_advance(dut):
    """Oracle A1, exhaustively: for every one of the 65536 LFSR states, the
    RTL's 8-shift advance must equal Base 2.1 App. C.1 p.698.

    This is a complete proof of the module for disable_scrambling=0, not a
    sample: there are exactly 2^16 reachable input states and all are driven.
    """
    checked = 0
    bad = []
    for q in range(0x10000):
        got = await step(dut, q, disable=0)
        want = advance(q)
        if got != want:
            if len(bad) < 8:
                bad.append("lfsr_q=%04X: got %04X want %04X" % (q, got, want))
        checked += 1
    dut._log.info("exhaustive advance: %d/65536 states driven" % checked)
    assert checked == 0x10000, "did not drive the whole state space: %d" % checked
    assert not bad, ("8-shift advance diverges from Base 2.1 App. C.1 p.698 "
                     "in %d+ states: %s" % (len(bad), "; ".join(bad)))


@cocotb.test()
async def spec_p700_state_table(dut):
    """Oracle A1 against published data, not against the equations.

    Base 2.1 p.700 lists the first 128 LFSR values after a reset.  Walk the DUT
    from the FFFFh seed (sec 4.2.3 p.199) and require every state to match the
    printed table.
    """
    q = int(SPEC_LFSR_128[0], 16)
    assert q == 0xFFFF, "p.700 table must start at the sec 4.2.3 seed FFFFh"
    checked = 0
    for i in range(1, len(SPEC_LFSR_128)):
        q = await step(dut, q, disable=0)
        want = int(SPEC_LFSR_128[i], 16)
        assert q == want, ("Base 2.1 p.700 state %d: got %04X want %04X"
                           % (i, q, want))
        checked += 1
    dut._log.info("p.700 LFSR table: %d states matched" % checked)
    assert checked == len(SPEC_LFSR_128) - 1, "assertion loop did not run"


@cocotb.test()
async def spec_p700_scrambled_zeros(dut):
    """Oracle A1 + A7 against published data.

    Base 2.1 p.700 also prints the byte stream produced by repeatedly scrambling
    00h from reset.  Reproducing it exercises the DUT's advance *and* the XOR
    mapping of App. C.1 p.699 (data bit i ^ LFSR bit 15-i), which is the mapping
    gen1_scramble implements with its bit-reversal.
    """
    q = 0xFFFF
    checked = 0
    for i, want_hex in enumerate(SPEC_ZERO_SCRAMBLED):
        got = 0x00 ^ xor_mask(q)
        want = int(want_hex, 16)
        assert got == want, ("Base 2.1 p.700 scrambled-00h byte %d: "
                             "got %02X want %02X" % (i, got, want))
        q = await step(dut, q, disable=0)   # the DUT advances the state
        checked += 1
    dut._log.info("p.700 scrambled-zeros: %d bytes matched" % checked)
    assert checked == len(SPEC_ZERO_SCRAMBLED), "assertion loop did not run"


@cocotb.test()
async def disable_holds_state(dut):
    """RTL behaviour, NOT a spec claim: disable_scrambling=1 holds the LFSR.

    Base 2.1 sec 4.2.3 p.199 lets scrambling be disabled, but says nothing about
    freezing the LFSR -- byte_scramble.sv:9-10 is a design choice.  Recorded as a
    unit-level property because it is *unreachable in the phy_receive closure*:
    gen1_scramble.sv:78 ties the port to '0, so no gate row above this one can
    ever exercise it.  Sampled, not exhaustive, since it is not an oracle.
    """
    checked = 0
    for q in [0x0000, 0xFFFF, 0xAAAA, 0x5555, 0x0001, 0x8000, 0x1234, 0xE817]:
        got = await step(dut, q, disable=1)
        assert got == q, "disable=1 must hold: lfsr_q=%04X got %04X" % (q, got)
        moved = await step(dut, q, disable=0)
        assert moved == advance(q), "disable=0 must advance: %04X" % q
        checked += 1
    dut._log.info("disable-hold: %d state pairs checked" % checked)
    assert checked == 8, "assertion loop did not run"


@cocotb.test()
async def golden_model_self_check(dut):
    """Guard against a vacuous suite (sec 22.17): prove the golden model itself
    reproduces both p.700 tables, independently of the DUT.  If this fails, every
    other verdict in this file is meaningless."""
    q = 0xFFFF
    for i, want in enumerate(SPEC_LFSR_128):
        assert q == int(want, 16), "model LFSR state %d" % i
        q = advance(q)
    d = Descrambler()
    for i, want in enumerate(SPEC_ZERO_SCRAMBLED):
        assert d.symbol(0x00, is_k=False) == int(want, 16), "model zero-scramble %d" % i
    dut._log.info("golden model reproduces both Base 2.1 p.700 tables")
    await Timer(SETTLE_NS, units="ns")
