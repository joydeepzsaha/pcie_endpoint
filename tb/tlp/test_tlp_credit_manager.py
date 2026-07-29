import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def exact_short_update_and_independent_pools(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.request_valid.value = 0
    dut.fc_initialized.value = 0
    dut.fc_update_valid.value = 0
    for _ in range(3): await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.ph.value=2; dut.pd.value=4; dut.nph.value=1; dut.npd.value=0
    dut.cplh.value=1; dut.cpld.value=3; dut.fc_update_valid.value=1
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid.value=0; dut.fc_initialized.value=1

    dut.request_class.value=0; dut.request_data_credits.value=4; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.request_valid.value=0
    assert int(dut.ph_av.value)==1 and int(dut.pd_av.value)==0

    dut.request_class.value=0; dut.request_data_credits.value=1; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==0 and int(dut.blocked.value)==1
    dut.request_class.value=2; dut.request_data_credits.value=3
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    dut.request_valid.value=0
    assert int(dut.cplh_av.value)==0 and int(dut.cpld_av.value)==0
    assert int(dut.nph_av.value)==1 and int(dut.npd_av.value)==0

    dut.fc_initialized.value=0; dut.fc_update_valid.value=1
    dut.ph.value=255; dut.pd.value=4095
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid.value=0; dut.request_valid.value=1
    await Timer(1, units="ps")
    assert int(dut.request_ready.value)==0


# ---------------------------------------------------------------------------
# Commit A -- PCIe Base 2.1 SS2.6.1.1 two-register accounting model.
#
# The module tracks CREDIT_LIMIT (cumulative advertised, loaded from fc_*_i) and
# CREDITS_CONSUMED (cumulative consumed) separately and gates on their
# difference.  Everything below is new coverage; see SPEC_PREDICTIONS_CREDIT.md
# SSI-SSK.  The first fc_update_valid strobe after reset is FC initialisation,
# every later strobe is an UpdateFC (SSI.2).
# ---------------------------------------------------------------------------

HDR_MOD = 1 << 8
DATA_MOD = 1 << 12

POSTED = 0
NON_POSTED = 1
COMPLETION = 2


async def _advertise(dut, ph, pd, nph, npd, cplh, cpld):
    """One fc_update_valid strobe carrying a cumulative advertisement."""
    dut.ph.value = ph
    dut.pd.value = pd
    dut.nph.value = nph
    dut.npd.value = npd
    dut.cplh.value = cplh
    dut.cpld.value = cpld
    dut.fc_update_valid.value = 1
    await RisingEdge(dut.clk_i)
    dut.fc_update_valid.value = 0
    await Timer(1, units="ps")


async def _reset_and_init(dut, ph, pd, nph, npd, cplh, cpld):
    """Reset, then deliver the FC-initialisation advertisement."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_i.value = 1
    dut.request_valid.value = 0
    dut.request_class.value = 0
    dut.request_data_credits.value = 0
    dut.fc_initialized.value = 0
    dut.fc_update_valid.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await RisingEdge(dut.clk_i)
    await _advertise(dut, ph, pd, nph, npd, cplh, cpld)
    dut.fc_initialized.value = 1
    await Timer(1, units="ps")


async def _try_request(dut, cls, data_credits):
    """Present one request for a cycle.  Returns True if it was granted."""
    dut.request_class.value = cls
    dut.request_data_credits.value = data_credits
    dut.request_valid.value = 1
    await Timer(1, units="ps")
    granted = int(dut.request_ready.value) == 1
    await RisingEdge(dut.clk_i)
    dut.request_valid.value = 0
    await Timer(1, units="ps")
    return granted


async def _probe_request(dut, cls, data_credits):
    """Present a request combinationally without advancing the clock, so
    nothing is consumed.  Returns (request_ready, blocked)."""
    dut.request_class.value = cls
    dut.request_data_credits.value = data_credits
    dut.request_valid.value = 1
    await Timer(1, units="ps")
    result = (int(dut.request_ready.value), int(dut.blocked.value))
    dut.request_valid.value = 0
    await Timer(1, units="ps")
    return result


def _avail(dut):
    return {
        "ph": int(dut.ph_av.value), "pd": int(dut.pd_av.value),
        "nph": int(dut.nph_av.value), "npd": int(dut.npd_av.value),
        "cplh": int(dut.cplh_av.value), "cpld": int(dut.cpld_av.value),
    }


@cocotb.test()
async def repeated_updatefc_does_not_overstate_credit(dut):
    """*** The test that exposes the accounting bug.  Expected to FAIL at 03d4915. ***

    PCIe Base 2.1 SS2.6.1.1 p.140: CREDIT_LIMIT is the cumulative total advertised
    since FC initialisation, so remaining credit is (limit - consumed_total).  The
    pre-fix RTL loaded the advertised value straight into the register it then
    decremented, so after any UpdateFC it reported
    (limit - consumed_since_that_update) -- over-stating available credit by every
    credit consumed beforehand, and growing without bound over the link's life.
    """
    await _reset_and_init(dut, 10, 100, 10, 100, 10, 100)
    assert _avail(dut)["ph"] == 10

    for _ in range(4):
        assert await _try_request(dut, POSTED, 1)
    assert _avail(dut)["ph"] == 6
    assert _avail(dut)["pd"] == 96

    # The receiver has freed nothing, so it re-advertises the same cumulative
    # limit.  True remaining credit is unchanged at 6.
    await _advertise(dut, 10, 100, 10, 100, 10, 100)
    got = _avail(dut)["ph"]
    assert got == 6, (
        "UpdateFC re-advertising an unchanged cumulative limit must not restore "
        f"credit: expected 6 remaining, got {got} (10 is the pre-fix "
        "over-statement -- exactly the defect this commit fixes)")
    assert _avail(dut)["pd"] == 96

    # Receiver frees 2 header / 20 data credits: the cumulative limit advances.
    for _ in range(3):
        assert await _try_request(dut, POSTED, 1)
    assert _avail(dut)["ph"] == 3
    await _advertise(dut, 12, 120, 10, 100, 10, 100)
    got = _avail(dut)
    assert got["ph"] == 5, f"expected limit 12 - consumed 7 = 5, got {got['ph']}"
    assert got["pd"] == 113, f"expected limit 120 - consumed 7 = 113, got {got['pd']}"


@cocotb.test()
async def single_update_matches_the_old_model_exactly(dut):
    """Regression guard.  With one advertisement and consumption starting from
    zero the two-register model and the old decrementing one coincide exactly --
    which is why no pre-existing harness moves: every wired harness pulses
    fc_update_valid once and never approaches a limit."""
    await _reset_and_init(dut, 6, 60, 6, 60, 6, 60)
    consumed_ph = 0
    consumed_pd = 0
    for _ in range(6):
        assert await _try_request(dut, POSTED, 3)
        consumed_ph += 1
        consumed_pd += 3
        got = _avail(dut)
        assert got["ph"] == 6 - consumed_ph
        assert got["pd"] == 60 - consumed_pd
    # Header pool exactly exhausted; the seventh request must block.
    assert _avail(dut)["ph"] == 0
    assert not await _try_request(dut, POSTED, 3)


@cocotb.test()
async def cumulative_counters_wrap_correctly(dut):
    """Both quantities are cumulative mod 2^[Field Size] -- 8 bits for headers,
    12 for data (SS2.6.1.1 p.139).  Drive consumption AND the advertised limit
    through both wraps and check remaining credit stays exact throughout.

    Advertisements stay inside the spec's cap of 127 header / 2047 data
    outstanding unused credits (SS2.6.1 p.138), which is the precondition the
    simple 'remaining >= required' comparison relies on
    (SPEC_PREDICTIONS_CREDIT.md SSJ)."""
    raw_limit_ph, raw_limit_pd = 100, 1500
    raw_consumed_ph, raw_consumed_pd = 0, 0
    await _reset_and_init(dut, raw_limit_ph, raw_limit_pd, 200, 3000, 200, 3000)

    dc = 16
    for i in range(400):
        need_adv = False
        if raw_limit_ph - raw_consumed_ph <= 40:
            raw_limit_ph += 60
            need_adv = True
        if raw_limit_pd - raw_consumed_pd <= 600:
            raw_limit_pd += 1000
            need_adv = True
        if need_adv:
            await _advertise(dut, raw_limit_ph % HDR_MOD, raw_limit_pd % DATA_MOD,
                             200, 3000, 200, 3000)

        assert await _try_request(dut, POSTED, dc), f"blocked at iteration {i}"
        raw_consumed_ph += 1
        raw_consumed_pd += dc

        got = _avail(dut)
        assert got["ph"] == (raw_limit_ph - raw_consumed_ph) % HDR_MOD, (
            f"iteration {i}: header remainder wrong")
        assert got["pd"] == (raw_limit_pd - raw_consumed_pd) % DATA_MOD, (
            f"iteration {i}: data remainder wrong")
        # The precondition the comparison proof depends on.
        assert got["ph"] <= 127 and got["pd"] <= 2047

    # Prove the wraps were actually crossed rather than merely approached.
    assert raw_consumed_ph > HDR_MOD, "header consumption never wrapped"
    assert raw_consumed_pd > DATA_MOD, "data consumption never wrapped"
    assert raw_limit_ph > HDR_MOD, "header limit never wrapped"
    assert raw_limit_pd > DATA_MOD, "data limit never wrapped"


@cocotb.test()
async def zero_valued_update_no_longer_wedges_the_pool(dut):
    """Defect SS0.5.  A partner that advertised infinite credit sends zero-valued
    UpdateFC DLLPs (SS2.6.1 p.138) and our DLL forwards them
    (dllp_handler.sv:331-332).  The pre-fix RTL loaded that zero straight into the
    remainder and wedged TX permanently.

    Commit A alone does not make this correct: it reinterprets the zero as a
    legitimately wrapped cumulative limit, which is over-permissive rather than
    wedged.  Commit B fixes it properly, by latching the pool infinite at
    initialisation and thereafter ignoring the credit field of updates for it.
    This test pins only the not-wedged property that Commit A delivers."""
    await _reset_and_init(dut, 8, 100, 8, 100, 8, 100)
    for _ in range(3):
        assert await _try_request(dut, POSTED, 1)
    assert _avail(dut)["ph"] == 5

    await _advertise(dut, 0, 0, 8, 100, 8, 100)
    assert await _try_request(dut, POSTED, 1), (
        "a zero-valued UpdateFC must not wedge the posted pool")


@cocotb.test()
async def header_exhaustion_blocks_and_is_attributable_to_the_header(dut):
    """Increment 1 SS3 found the 'header != 0' comparison was never once observed
    returning false: the only block the bundled bench saw was caused by data, and
    the later one was masked by fc_initialized going low.  Drive a header pool to
    exhaustion with data credits ample and prove the block is the header's."""
    await _reset_and_init(dut, 2, 4000, 8, 4000, 8, 4000)
    for _ in range(2):
        assert await _try_request(dut, POSTED, 1)

    got = _avail(dut)
    assert got["ph"] == 0, "posted header pool should be exactly exhausted"
    assert got["pd"] >= 1, "posted data credits must still be ample"

    ready, blocked = await _probe_request(dut, POSTED, 1)
    assert ready == 0 and blocked == 1, "exhausted header pool must block"

    # Attribution: the identical data requirement on a class whose header pool is
    # not exhausted is granted, so the block above was the header's doing alone.
    ready_np, _ = await _probe_request(dut, NON_POSTED, 1)
    assert ready_np == 1, "block was not attributable to the posted header pool"


@cocotb.test()
async def posted_and_completion_pools_are_independent(dut):
    """Increment 1 SS3: only the 'NP untouched' direction was ever asserted; the
    P-vs-CPL direction was not.  All six advertisements are forced apart so a
    crossed pool cannot coincidentally pass."""
    await _reset_and_init(dut, 5, 50, 9, 90, 3, 30)

    for _ in range(2):
        assert await _try_request(dut, POSTED, 7)
    got = _avail(dut)
    assert (got["ph"], got["pd"]) == (3, 36)
    assert (got["cplh"], got["cpld"]) == (3, 30), "posted traffic touched the CPL pool"
    assert (got["nph"], got["npd"]) == (9, 90), "posted traffic touched the NP pool"

    assert await _try_request(dut, COMPLETION, 11)
    got = _avail(dut)
    assert (got["cplh"], got["cpld"]) == (2, 19)
    assert (got["ph"], got["pd"]) == (3, 36), "completion traffic touched the P pool"
    assert (got["nph"], got["npd"]) == (9, 90), "completion traffic touched the NP pool"


async def _hold_blocked_request(dut, cls, data_credits, cycles):
    """Hold a request that cannot be granted across several clock edges."""
    dut.request_class.value = cls
    dut.request_data_credits.value = data_credits
    dut.request_valid.value = 1
    for _ in range(cycles):
        await Timer(1, units="ps")
        assert int(dut.request_ready.value) == 0, "request was expected to block"
        assert int(dut.blocked.value) == 1
        await RisingEdge(dut.clk_i)
    dut.request_valid.value = 0
    await Timer(1, units="ps")


@cocotb.test()
async def blocked_requests_consume_no_credit(dut):
    """SS2.6.1.1 p.139: CREDITS_CONSUMED is updated "for each TLP the Transaction
    Layer allows to pass the Flow Control gate for Transmission" -- so a TLP the
    gate blocks must consume nothing.  Without this a stalled request silently
    eats credit and the pool never fully recovers when the receiver frees space.

    Added because mutation M-d (increment on every valid request, granted or not)
    survived the rest of this file untouched.
    """
    await _reset_and_init(dut, 3, 100, 3, 100, 3, 100)
    for _ in range(3):
        assert await _try_request(dut, POSTED, 1)
    assert _avail(dut)["ph"] == 0

    # Hold the blocked request across several edges; nothing may be consumed.
    await _hold_blocked_request(dut, POSTED, 1, 5)

    # Receiver frees 5 header credits: cumulative limit 3 -> 8.  Exactly 5 must
    # become available -- any credit eaten while blocked shows up right here.
    await _advertise(dut, 8, 100, 3, 100, 3, 100)
    got = _avail(dut)["ph"]
    assert got == 5, (
        f"expected limit 8 - consumed 3 = 5 available, got {got}: a blocked "
        "request consumed credit it was never granted")
