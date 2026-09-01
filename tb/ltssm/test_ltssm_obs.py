"""
Fix-arc 1, Phase 2 -- the LTSSM's error/success outputs, observed at the port.

WHAT IS BROKEN
  pcie_ltssm_downstream declares `error_o` (:42) and `success_o` (:43) and
  drives NEITHER. Internally the FSM maintains error_c/error_r (:185-:186,
  registered at :416) and success_c/success_r (:187-:188, :417); the raise
  sites are real -- 12 of them for error_c -- but nothing connects them to a
  port. Measured at 7419631:

      $ grep -n 'error_o\\|success_o' src/ltssm/pcie_ltssm_downstream.sv
      42:    output logic  error_o,
      43:    output logic  success_o,
      695:              // us to ST_IDLE either way; this just makes sure error_o

  -- two declarations and one comment, no driver. So an integrator cannot
  observe a training failure or a training success, and four pre-existing gate
  assertions that read `error_o` (test_ltssm_partial_lanes.py:207,:304 and
  test_ltssm_recovery_partial_lanes.py:92,:136) are tautologies: they compare a
  permanently-zero port against zero. That is the `[unsound]` ledger tag on gate
  rows 58 and 63 (Tracker section 55), and repairing it is the point of this
  bench.

  Defect register: FINDINGS_LTSSM.md section 2 Block B, entries B1 and B2;
  Tracker section 54 row 2.

WHAT THIS BENCH ASSERTS -- one divergent assertion per expect_fail row
  obs_error   `error_o` rises after a training failure the FSM already detects.
  obs_success `success_o` is high while the link is up in L0.

  Both are expect_fail on unfixed RTL, where the ports read 0 no matter what
  the FSM does. `assign error_o = error_r;` / `assign success_o = success_r;`
  flips both.

THE PROVOCATION, and why this one
  The cheapest reachable error_c site is :614, Detect.Rx:

      :604  ST_DETECT_RX: begin
      :605    if (timer_r >= TwelveMsTimeOut) begin
      :608      if (|phy_phystatus_r) begin
      :609        if ((lanes_detected_r == receiver_detected_i)) begin ... success
      :613        end else begin
      :614          error_c    = '1;
      :615          next_state = ST_IDLE;

  Reaching it costs one TwelveMsTimeOut, and TwelveMsTimeOut IS SIM_FAST_LINK
  scaled (:111, 1200 cycles) -- unlike TwoMsTimeOut (200 000, :113) or the 24/48
  ms timeouts (2.4 M / 4.8 M) that guard most of the other raise sites. So this
  is a bounded ~1500-cycle provocation where the alternatives cost millions.

  It is exactly the case test_ltssm_partial_lanes.py:150-156 deliberately
  AVOIDS: that bench re-presents the SAME lane mask so :609 succeeds. Here we
  present a DIFFERENT one, so :609 fails and :614 fires.

  x4 is required. At MAX_NUM_LANES=1, `|receiver_detected_i` and
  `&receiver_detected_i` are the same expression, Detect.Active always takes
  :582's all-lanes arm, and ST_DETECT_RX is unreachable -- an x1 target could
  not run this at all.

WHY error_o AND success_o NEED DIFFERENT ASSERTION SHAPES
  They are not symmetric, despite the register listing them as one line each:

      :482   error_c   = error_r;     <- defaults to its own registered value
      :483   success_c = '0;          <- defaults to 0

  No site anywhere assigns error_c to 0 (`grep -E "error_c\\s*=\\s*('0|1'b0|0)"`
  finds nothing), so error_r is STICKY: it latches on the first error and clears
  only on rst_i. success_r is a LEVEL that tracks the state -- high throughout
  ST_L0 (:999), plus one cycle at each Detect success (:583, :610).

  Hence: error_o may be sampled any time after the provocation; success_o must
  be sampled while the FSM is in L0.

NEGATIVE CONTROL
  An expect_fail row goes green if ANYTHING in it raises, including a broken
  setup (10b's D9/D10 lesson, rule 22.66). test_obs_control_provocation_reaches_error_site
  is an ordinary PASS row that runs the same drive sequence and asserts the
  FSM's OBSERVABLE state behaviour -- that it leaves ST_DETECT_RX for ST_IDLE
  shortly after the 12 ms timeout. That transition has only two sources: :615,
  the error arm, and :619 at TwentyFourMsTimeOut, which is 2.4 M cycles away and
  cannot be what fired inside a 1500-cycle window. So the control witnesses that
  :614 executed, using only ports that are driven today -- which is the only way
  to witness it on unfixed RTL, error_r itself not being a port.
  If this control is red, the two rows below prove nothing and are void.

Requires SIM_FAST_LINK=1, MAX_NUM_LANES=4 (verilate_ltssm_obs target).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from ltssm_tb_common import *  # noqa

# Same definitions as test_ltssm_partial_lanes.py:81-95, repeated rather than
# imported: cross-importing one cocotb test module from another makes the
# importer's tests run twice under some runners.
def _mask(active_lanes):
    m = 0
    for lane in active_lanes:
        m |= (1 << lane)
    return m


def _rxstatus_mask(active_lanes):
    """phy_rxstatus_i is MAX_NUM_LANES*3 bits; 3'b011 per active lane, all-zero
    for inactive lanes (lane_status checks phy_rxstatus_i[3*i+:3] == 3'b011,
    pcie_ltssm_downstream.sv:448)."""
    v = 0
    for lane in active_lanes:
        v |= (0b011 << (3 * lane))
    return v


# pcie_ltssm_downstream.sv:111 -- SIM_FAST_LINK ? (12*10**4)/(ClockPeriodNs*10)
# = 1200 cycles at ClockPeriodNs=10.
TWELVE_MS_CYCLES = 1200
SETTLE = 150

FIRST_MASK  = _mask([0, 1])   # partial, so Detect.Active takes the DETECT_RX hop
SECOND_MASK = _mask([0])      # DIFFERENT -> :609 mismatch -> :614 error


def state(dut):
    return int(dut.ltssm_state_o.value)


def sname(s):
    return STATE_NAMES.get(s, hex(s))


def check_geometry(dut):
    n = len(dut.ordered_set_i)
    assert n == 512, (
        f"-GMAX_NUM_LANES=4 did not reach the DUT: ordered_set_i is {n} bits "
        f"(x4 expects 4*128=512); ST_DETECT_RX is unreachable at x1, so this "
        f"bench would be vacuous")


async def drive_to_detect_rx_mismatch(dut):
    """Reset -> Detect.Quiet -> Detect.Active -> Detect.Rx, then re-present a
    DIFFERENT receiver mask at the 12 ms timeout so :609 fails and :614 fires.

    Returns (cycles_waited, landed_state) measured from the moment the second
    phystatus pulse is applied.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    check_geometry(dut)
    drive_idle_inputs(dut)
    dut.rst_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.rst_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    assert state(dut) == ST_IDLE, f"post-reset state is {sname(state(dut))}"

    # ---- IDLE -> DETECT_QUIET ----
    dut.en_i.value = 1
    await wait_state(dut, ST_DETECT_QUIET, 50, "DETECT_QUIET")

    # ---- DETECT_QUIET -> DETECT_ACTIVE on the elec-idle exit edge (1 -> 0) ----
    dut.phy_rxelecidle_i.value = ALL
    await ClockCycles(dut.clk_i, 3)
    dut.phy_rxelecidle_i.value = 0
    await wait_state(dut, ST_DETECT_ACTIVE, 50, "DETECT_ACTIVE")

    # ---- DETECT_ACTIVE -> DETECT_RX: a PARTIAL receiver mask takes :587-:589
    # (lanes_detected_c <- FIRST_MASK) instead of :582's straight-to-Polling. ----
    dut.receiver_detected_i.value = FIRST_MASK
    dut.phy_rxstatus_i.value = _rxstatus_mask([0, 1])
    dut.phy_phystatus_i.value = FIRST_MASK
    await ClockCycles(dut.clk_i, 3)
    dut.phy_phystatus_i.value = 0
    await wait_state(dut, ST_DETECT_RX, 50, "DETECT_RX")
    dut._log.info(
        f"OBS setup: in DETECT_RX with lanes_detected latched to "
        f"{FIRST_MASK:#06b}")

    # ---- ST_DETECT_RX ignores phystatus until timer_r >= TwelveMsTimeOut. ----
    await ClockCycles(dut.clk_i, TWELVE_MS_CYCLES + 100)

    # ---- the provocation: a DIFFERENT mask at the second look ----
    dut.receiver_detected_i.value = SECOND_MASK
    dut.phy_rxstatus_i.value = _rxstatus_mask([0])
    dut.phy_phystatus_i.value = SECOND_MASK
    dut._log.info(
        f"OBS provocation: re-presenting {SECOND_MASK:#06b} != "
        f"{FIRST_MASK:#06b}, so :609 mismatches and :614 raises error_c")

    waited = 0
    landed = state(dut)
    for i in range(SETTLE):
        await ClockCycles(dut.clk_i, 1)
        await Timer(1, units="ps")
        landed = state(dut)
        if landed != ST_DETECT_RX:
            waited = i + 1
            break
    dut.phy_phystatus_i.value = 0
    dut._log.info(
        f"OBS provocation: left DETECT_RX after {waited} cycles -> "
        f"{sname(landed)}")
    return waited, landed


# ==========================================================================
#  Negative control -- ordinary PASS row.
# ==========================================================================

@cocotb.test()
async def test_obs_control_provocation_reaches_error_site(dut):
    """Control: the drive sequence really does execute :614.

    :614 and :615 are the same statement pair, so witnessing the state change
    at :615 witnesses the error_c raise at :614. The only other exit from
    ST_DETECT_RX to ST_IDLE is :619 at TwentyFourMsTimeOut -- 2.4 M cycles,
    which is not SIM_FAST_LINK scaled and so cannot be what fired inside the
    150-cycle window measured here.
    """
    waited, landed = await drive_to_detect_rx_mismatch(dut)
    assert landed == ST_IDLE, (
        f"control failed: the mask mismatch should take :615 to ST_IDLE, got "
        f"{sname(landed)} -- the provocation did not reach :614 and the two "
        f"expect_fail rows in this file are void")
    assert 0 < waited < SETTLE, (
        f"control failed: left DETECT_RX after {waited} cycles, outside the "
        f"bounded window that rules out the 24 ms timeout at :619")
    dut._log.info(
        f"CONTROL OK: :614/:615 executed -- DETECT_RX -> ST_IDLE after "
        f"{waited} cycles, far inside the 2.4 M-cycle 24 ms alternative")


# ==========================================================================
#  B1 -- error_o must report a training failure the FSM already detected.
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_obs_error_o_reports_training_failure(dut):
    """B1: `error_o` is never driven, so it reads 0 even though error_r is 1.

    The control above proves :614 ran. error_r is sticky (:482 defaults
    error_c to error_r and no site clears it), so by the time this samples,
    error_r has been 1 since the provocation. A conforming module reports that
    on its port.
    """
    _waited, landed = await drive_to_detect_rx_mismatch(dut)
    assert landed == ST_IDLE, (
        f"setup did not reach the error site (landed in {sname(landed)}); see "
        f"the control row")
    await ClockCycles(dut.clk_i, 20)

    got = int(dut.error_o.value)
    dut._log.info(
        f"B1: after a Detect.Rx lane-set mismatch, error_o = {got} "
        f"(the FSM raised error_c at :614; a driven port would read 1)")
    assert got == 1, (
        "B1 violated: error_o reads 0 after a training failure the FSM itself "
        "detected at pcie_ltssm_downstream.sv:614. The port is declared at :42 "
        "and never assigned -- error_c/error_r reach no port at all, so no "
        "integrator can observe a training failure, and the four assertions on "
        "gate rows 58/63 that read error_o are tautologies. Fix: "
        "assign error_o = error_r;")


# ==========================================================================
#  B2 -- success_o must report a trained link.
# ==========================================================================

@cocotb.test(expect_fail=True)
async def test_obs_success_o_reports_link_trained(dut):
    """B2: `success_o` is never driven, so it reads 0 while the link is up.

    success_c is unconditional in ST_L0 (:999) and success_r registers it
    (:417), so a driven port reads 1 for as long as the FSM stays in L0. This
    samples while link_up_o is high, which pins the two together.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    check_geometry(dut)
    await bring_up_link(dut)
    assert state(dut) == ST_L0, f"setup did not reach L0, got {sname(state(dut))}"
    await ClockCycles(dut.clk_i, 20)
    assert state(dut) == ST_L0, "fell out of L0 before the sample"
    assert int(dut.link_up_o.value) == 1, "link_up_o low in L0 -- setup is broken"

    got = int(dut.success_o.value)
    dut._log.info(
        f"B2: in L0 with link_up_o=1, success_o = {got} "
        f"(the FSM holds success_c at :999; a driven port would read 1)")
    assert got == 1, (
        "B2 violated: success_o reads 0 in ST_L0 while link_up_o reads 1. The "
        "port is declared at :43 and never assigned, so a trained link is "
        "unobservable on it. Fix: assign success_o = success_r;")
