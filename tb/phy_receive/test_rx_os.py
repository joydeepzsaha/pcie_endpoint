"""T3 -- spec-golden unit bench for ordered_set_handler.

Toplevel: ordered_set_handler at pipe_width_i = 8 (one Symbol per clock in
data_in_i[7:0] / data_k_in_i[0]) and DATA_WIDTH = 32.  The module sits directly
downstream of the descrambler inside phy_receive, so its input is already
descrambled Symbols and the stimulus here is driven literally.

Oracles (ORACLES_PHY_RX.md, PCI Express Base Spec Rev 2.1):
  B2  Table 4-2 p.203 / 4-3 p.205   TS1 identifier D10.2 = 4Ah, TS2 D5.2 = 45h
  B3  sec 4.2.4.4 p.208             inverted: D21.5 = B5h, D26.5 = BAh
  C1  Table 4-2 pp.201-203          TS1 = 16 Symbols, Symbols 6-15 all D10.2
  C2  Table 4-3 pp.203-205          TS2 = 16 Symbols, Symbols 6-15 all D5.2
  C3  sec 4.2.4.4 p.208             polarity is decided on Symbols 6-15
  C4  Table 4-4 p.205               EIOS at 2.5 GT/s = COM + three IDL
  C5  Table 4-5 p.206               the EIEOS exists only above 2.5 GT/s;
      Table 4-1 p.194               K28.7 is "Reserved in 2.5 GT/s"

eieos_valid_o is observable ONLY here: phy_receive.sv:180 binds the port to ().
That is the reason this unit bench exists alongside the closure bench.

Tests marked expect_fail are pre-registered spec divergences
(pcie_docs/evidence/phy-rx-golden/PREDICTIONS_PHY_RX.md sec 2, T3).  They are kept
as failing-against-spec records, never weakened to pass.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, Timer

from rx_golden import (COM, IDL, EIE, PAD, TS1_ID, TS2_ID, TS1_ID_INV, TS2_ID_INV,
                       GEN1, ts_ordered_set, eios, fmt)

GEN2 = 0x03             # rate_speed_e.gen2 = 5'b00011 (pcie_phy_pkg.sv:241)
PIPE_WIDTH = 8
OBSERVE = 12            # clocks to watch for the one-cycle validity pulses


async def setup(dut, rate=GEN1):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.data_in_i.value = 0
    dut.data_valid_i.value = 0
    dut.data_k_in_i.value = 0
    dut.sync_header_i.value = 0
    dut.pipe_width_i.value = PIPE_WIDTH
    dut.curr_data_rate_i.value = rate
    await ClockCycles(dut.clk_i, 8)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 4)


def _flags(dut):
    return {
        "ts1": int(dut.ts1_valid_o.value) & 1,
        "ts2": int(dut.ts2_valid_o.value) & 1,
        "idle": int(dut.idle_valid_o.value) & 1,
        "eieos": int(dut.eieos_valid_o.value) & 1,
        "pol": int(dut.polarity_inverted_o.value) & 1,
    }


async def drive_and_observe(dut, syms, observe=OBSERVE):
    """Drive a Symbol stream one per clock, then watch the outputs.

    The validity outputs are single-cycle pulses: check_ordered_set_c defaults to
    '0 (ordered_set_handler.sv:164) and the flags are registered from it at
    :130-134.  So the result is the OR over a window, plus the window length, so
    that a test can prove it actually looked.
    """
    seen = {k: 0 for k in ("ts1", "ts2", "idle", "eieos", "pol")}
    samples = 0

    async def sample():
        nonlocal samples
        await Timer(1, units="ps")     # post-edge; a bare read is pre-edge
        for k, v in _flags(dut).items():
            seen[k] |= v
        samples += 1

    for b, k in syms:
        dut.data_in_i.value = b & 0xFF
        dut.data_k_in_i.value = k & 0x1
        dut.data_valid_i.value = 1
        await RisingEdge(dut.clk_i)
        await sample()

    dut.data_valid_i.value = 0
    dut.data_in_i.value = 0
    dut.data_k_in_i.value = 0
    for _ in range(observe):
        await RisingEdge(dut.clk_i)
        await sample()

    seen["_samples"] = samples
    return seen


def _report(dut, label, syms, seen):
    dut._log.info("%s\n  stream : %s\n  flags  : ts1=%d ts2=%d idle=%d eieos=%d pol=%d"
                  " over %d sampled clocks"
                  % (label, fmt(syms), seen["ts1"], seen["ts2"], seen["idle"],
                     seen["eieos"], seen["pol"], seen["_samples"]))
    assert seen["_samples"] >= len(syms), \
        "sampling loop did not run: %d samples for %d Symbols" % (
            seen["_samples"], len(syms))


# ------------------------------------------------------- C1 / C2, positive

@cocotb.test()
async def ts1_wellformed_is_recognised(dut):
    """C1 + B2: a complete TS1 (COM + Link + Lane + N_FTS + Rate + Ctl + ten
    D10.2, Table 4-2 pp.201-203) must raise ts1_valid_o and must not be mistaken
    for a TS2 or for an inverted Lane."""
    await setup(dut)
    syms = ts_ordered_set(TS1_ID, link=0x05, lane=0x00)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "well-formed TS1", syms, seen)
    assert seen["ts1"] == 1, "a spec-legal TS1 was not recognised"
    assert seen["ts2"] == 0, "a TS1 was also reported as a TS2"
    assert seen["pol"] == 0, "a non-inverted TS1 reported polarity inversion"


@cocotb.test()
async def ts2_wellformed_is_recognised(dut):
    """C2 + B2: a complete TS2 (Symbols 6-15 = D5.2 = 45h, Table 4-3 p.205)."""
    await setup(dut)
    syms = ts_ordered_set(TS2_ID, link=0x05, lane=0x00)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "well-formed TS2", syms, seen)
    assert seen["ts2"] == 1, "a spec-legal TS2 was not recognised"
    assert seen["ts1"] == 0, "a TS2 was also reported as a TS1"
    assert seen["pol"] == 0, "a non-inverted TS2 reported polarity inversion"


@cocotb.test()
async def inverted_ts1_sets_polarity(dut):
    """B3 + C3: under Lane polarity inversion every one of Symbols 6-15 arrives
    as D21.5 = B5h instead of D10.2 (sec 4.2.4.4 p.208).  The Receiver must
    report the inversion; support is mandatory on all Receivers."""
    await setup(dut)
    syms = ts_ordered_set(TS1_ID_INV, link=0x05, lane=0x00)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "polarity-inverted TS1", syms, seen)
    assert seen["pol"] == 1, "an inverted TS1 (all ten Symbols B5h) was not flagged"
    assert seen["ts1"] == 1, "sec 4.2.4.4: it is still a TS1, just inverted"


@cocotb.test()
async def inverted_ts2_sets_polarity(dut):
    """B3 + C3: the TS2 counterpart -- D26.5 = BAh instead of D5.2."""
    await setup(dut)
    syms = ts_ordered_set(TS2_ID_INV, link=0x05, lane=0x00)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "polarity-inverted TS2", syms, seen)
    assert seen["pol"] == 1, "an inverted TS2 (all ten Symbols BAh) was not flagged"
    assert seen["ts2"] == 1, "sec 4.2.4.4: it is still a TS2, just inverted"


# ------------------------------------------------------- C1 / C2, negative

@cocotb.test(expect_fail=True)
async def ts1_corrupt_in_symbols_10_to_15_is_rejected(dut):
    """C1, the requirement's real content: Table 4-2 p.203 gives Symbols
    "6 - 15   D10.2" as the TS1 Identifier.  All TEN must be D10.2.  An Ordered
    Set carrying 4Ah in Symbols 6-9 and rubbish in 10-15 is not a TS1 and must
    not be reported as one.

    PREDICTED DIVERGENCE (PREDICTIONS_PHY_RX.md sec 2, T3).
    ordered_set_handler.sv:380 tests exactly four Symbols:

        if (ordered_set_out_r[8*6+:8] == TS1 && ordered_set_out_r[8*7+:8] == TS1
         && ordered_set_out_r[8*8+:8] == TS1 && ordered_set_out_r[8*9+:8] == TS1)

    Symbols 10-15 are never examined, so six of the ten identifier Symbols carry
    no weight.  Any 16-Symbol set whose 6-9 happen to be 4Ah is accepted as a
    TS1 -- which is how a corrupted training sequence reaches the LTSSM as a good
    one.
    """
    await setup(dut)
    tail = [TS1_ID] * 4 + [0x00] * 6           # Symbols 6-9 good, 10-15 wrong
    syms = ts_ordered_set(TS1_ID, link=0x05, lane=0x00, tail=tail)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "TS1 corrupt in Symbols 10-15", syms, seen)
    assert seen["ts1"] == 0, \
        "Table 4-2 p.203 requires Symbols 6-15 to be D10.2; only 6-9 were checked"


@cocotb.test(expect_fail=True)
async def ts2_corrupt_in_symbols_10_to_15_is_rejected(dut):
    """C2: same requirement for TS2, Table 4-3 p.205, "6 - 15   D5.2".

    PREDICTED DIVERGENCE: ordered_set_handler.sv:389, same four-Symbol shape.
    """
    await setup(dut)
    tail = [TS2_ID] * 4 + [0xFF] * 6
    syms = ts_ordered_set(TS2_ID, link=0x05, lane=0x00, tail=tail)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "TS2 corrupt in Symbols 10-15", syms, seen)
    assert seen["ts2"] == 0, \
        "Table 4-3 p.205 requires Symbols 6-15 to be D5.2; only 6-9 were checked"


@cocotb.test(expect_fail=True)
async def partial_inversion_does_not_set_polarity(dut):
    """C3: sec 4.2.4.4 p.208 -- "the Receiver looks at Symbols 6-15 of the TS1
    and TS2 Ordered Sets as the indicator of Lane polarity inversion".  A set
    that is inverted in 6-9 but upright in 10-15 is not an inverted Lane; it is a
    corrupted Ordered Set, and inverting the received data because of it would
    corrupt a working Lane.

    PREDICTED DIVERGENCE: ordered_set_handler.sv:382 tests Symbols 6-9 only.
    """
    await setup(dut)
    tail = [TS1_ID_INV] * 4 + [TS1_ID] * 6     # inverted 6-9, upright 10-15
    syms = ts_ordered_set(TS1_ID, link=0x05, lane=0x00, tail=tail)
    seen = await drive_and_observe(dut, syms)
    _report(dut, "TS1 inverted in Symbols 6-9 only", syms, seen)
    assert seen["pol"] == 0, \
        "sec 4.2.4.4 p.208 requires Symbols 6-15; only 6-9 were checked"


# --------------------------------------------------------------- C4, EIOS

@cocotb.test()
async def eios_is_recognised(dut):
    """C4: the Electrical Idle Ordered Set at 2.5 GT/s is COM followed by three
    K28.3 IDL (sec 4.2.4.2 p.205, Table 4-4 p.205).  A Receiver must recognise it
    -- it is how the link partner announces entry to Electrical Idle."""
    await setup(dut)
    syms = eios()
    seen = await drive_and_observe(dut, syms)
    _report(dut, "well-formed EIOS", syms, seen)
    assert seen["idle"] == 1, "a spec-legal EIOS (COM IDL IDL IDL) was not recognised"


@cocotb.test(expect_fail=True)
async def malformed_eios_is_rejected(dut):
    """C4, negative: Table 4-4 p.205 defines the EIOS as exactly COM + three IDL.
    COM + one IDL + two data Symbols is not an EIOS and must not be reported as
    Electrical Idle -- acting on it drops a live link into a low-power state.

    PREDICTED DIVERGENCE (PREDICTIONS_PHY_RX.md sec 2, T3).
    ordered_set_handler.sv:279-284 raises idle_valid_c on the FIRST K-coded IDL
    seen after a COM and returns to ST_IDLE.  The confirmation that was meant to
    check the rest is at :406-416, and its body is empty -- the only statement,
    `idle_valid_c = '0'`, is commented out at :409.  So the second and third IDL
    are never required.
    """
    await setup(dut)
    syms = [(COM, 1), (IDL, 1), (0x11, 0), (0x22, 0)]
    seen = await drive_and_observe(dut, syms)
    _report(dut, "malformed EIOS (COM IDL 11 22)", syms, seen)
    assert seen["idle"] == 0, \
        "Table 4-4 p.205 requires three IDL Symbols; one was enough"


# -------------------------------------------------------------- C5, EIEOS

@cocotb.test(expect_fail=True)
async def eieos_is_never_valid_at_gen1(dut):
    """C5: the EIEOS does not exist at 2.5 GT/s.  Table 4-5 p.206 is titled
    "Electrical Idle Exit Sequence Ordered Set (EIEOS) for Data Rates Greater
    Than 2.5 GT/s", sec 4.2.4.1 p.206 says it "is transmitted only when operating
    at speeds other than 2.5 GT/s", and Table 4-1 p.194 marks its K28.7 Symbol
    "Reserved in 2.5 GT/s".  A Gen1 Receiver must never report one.

    PREDICTED DIVERGENCE (PREDICTIONS_PHY_RX.md sec 2, T3).
    ordered_set_handler.sv:376 initialises eieos_valid = '1' and the only Gen1
    clearing logic, :429-433, sits INSIDE the `curr_data_rate_i < gen3` arm at
    :379 -- so the EIEOS check runs at 2.5 GT/s, exactly where the Ordered Set is
    undefined.

    This output is invisible above unit level: phy_receive.sv:180 binds
    .eieos_valid_o () and discards it.
    """
    await setup(dut, rate=GEN1)
    # A legal >2.5 GT/s EIEOS: COM + fourteen K28.7 + D10.2 (Table 4-5 p.206).
    syms = [(COM, 1)] + [(EIE, 1)] * 14 + [(TS1_ID, 0)]
    seen = await drive_and_observe(dut, syms)
    _report(dut, "EIEOS driven at gen1", syms, seen)
    assert seen["eieos"] == 0, \
        "Table 4-5 p.206: no EIEOS exists at 2.5 GT/s, yet one was reported"


@cocotb.test(expect_fail=True)
async def eieos_requires_fourteen_eie_symbols(dut):
    """C5, shape: Table 4-5 p.206 gives the EIEOS as Symbol 0 = COM, Symbols
    1-14 = K28.7 (EIE), Symbol 15 = D10.2.  Fourteen EIE Symbols, not three.

    PREDICTED DIVERGENCE: ordered_set_handler.sv:429-433 loops `for (int i = 1;
    i < 4; i++)`, so only Symbols 1, 2 and 3 are compared against EIE.  Driven at
    5.0 GT/s, where the Ordered Set is at least defined, an Ordered Set with
    three EIE Symbols and twelve arbitrary bytes is still accepted.

    That loop also reads ordered_set_r while the TS1/TS2 checks 50 lines above
    read ordered_set_out_r -- two different registers for the same Ordered Set.
    """
    await setup(dut, rate=GEN2)
    syms = [(COM, 1)] + [(EIE, 1)] * 3 + [(0x5A + i & 0xFF, 0) for i in range(12)]
    seen = await drive_and_observe(dut, syms)
    _report(dut, "three-EIE pseudo-EIEOS at gen2", syms, seen)
    assert seen["eieos"] == 0, \
        "Table 4-5 p.206 requires EIE in Symbols 1-14; only 1-3 were checked"
