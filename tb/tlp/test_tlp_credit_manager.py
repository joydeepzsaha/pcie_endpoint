import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# PCIe credit counters wrap at their encoded field widths.
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
    """Reset, then deliver the first FC advertisement as initialization."""
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


@cocotb.test()
async def all_starvation_combinations_and_saturating_guards(dut):
    """Prove independent header/data blocking for P, NP, and Cpl pools."""
    # Initialize every pool as finite before any zero-valued cumulative update.
    # Otherwise a zero used to create a starvation case would correctly latch
    # that pool as infinite during initialization and invalidate the test.
    await _reset_and_init(dut, 7, 7, 7, 7, 7, 7)

    pools = [
        (0, "ph", "pd", "ph_av", "pd_av"),
        (1, "nph", "npd", "nph_av", "npd_av"),
        (2, "cplh", "cpld", "cplh_av", "cpld_av"),
    ]
    for traffic_class, header_in, data_in, header_out, data_out in pools:
        for name in ("ph", "nph", "cplh"):
            getattr(dut, name).value = 7
        for name in ("pd", "npd", "cpld"):
            getattr(dut, name).value = 7

        # Header available but data short.
        getattr(dut, header_in).value = 1
        getattr(dut, data_in).value = 0
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        dut.request_class.value = traffic_class
        dut.request_data_credits.value = 1
        dut.request_valid.value = 1
        await Timer(1, units="ps")
        assert not int(dut.request_ready.value)
        assert int(dut.blocked.value)
        assert int(getattr(dut, header_out).value) == 1
        assert int(getattr(dut, data_out).value) == 0

        # Data available but header absent.
        getattr(dut, header_in).value = 0
        getattr(dut, data_in).value = 1
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        await Timer(1, units="ps")
        assert not int(dut.request_ready.value)
        assert int(dut.blocked.value)
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 1

        # Exactly one header and one 16-byte data credit are consumed once.
        getattr(dut, header_in).value = 1
        getattr(dut, data_in).value = 1
        dut.fc_update_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.fc_update_valid.value = 0
        await Timer(1, units="ps")
        assert int(dut.request_ready.value)
        await RisingEdge(dut.clk_i)
        dut.request_valid.value = 0
        await Timer(1, units="ps")
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 0

        # A blocked request cannot wrap either zero-valued counter.
        dut.request_valid.value = 1
        await RisingEdge(dut.clk_i)
        dut.request_valid.value = 0
        await Timer(1, units="ps")
        assert int(getattr(dut, header_out).value) == 0
        assert int(getattr(dut, data_out).value) == 0


# ---------------------------------------------------------------------------
# PCIe Base 2.1 SS2.6.1.1 cumulative credit accounting coverage.
#
# CREDIT_LIMIT is the cumulative advertisement loaded from fc_* inputs;
# CREDITS_CONSUMED is tracked independently, and availability is their modular
# difference.  The remaining tests also cover infinite-credit initialization.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Commit B -- infinite credit.
#
# An advertisement of 00h/000h made AT FC INITIALIZATION means infinite credit
# for that type (SS2.6.1 p.138, footnote 33 p.137).  The determination is latched
# at initialisation and never re-evaluated (p.140), and the credit field of any
# later UpdateFC for that pool must be ignored (p.138).
# ---------------------------------------------------------------------------


@cocotb.test()
async def infinite_completion_credit_never_throttles(dut):
    """*** The configuration an endpoint actually faces. ***

    Table 2-37 p.137-138: a Root Complex not supporting peer-to-peer traffic
    between all Root Ports -- and an Endpoint -- MUST advertise infinite
    completion credits, an initial credit value of all 0s.  Footnote 33 p.137:
    "This value is interpreted as infinite by the Transmitter, which will,
    therefore, never throttle."

    Before this commit an advertised 0 read as 'nothing available', so the
    mandated configuration deadlocked the completion path outright.
    """
    await _reset_and_init(dut, 8, 100, 8, 100, 0, 0)
    # Far more completion traffic than any finite 8-/12-bit pool could carry.
    for i in range(300):
        assert await _try_request(dut, COMPLETION, 100), (
            f"infinite completion pool throttled at request {i}")


@cocotb.test()
async def infinite_credit_is_honoured_on_every_pool(dut):
    """Infinite is representable independently on all six pools -- the spec
    phrases it per type and per header/data: "only the Data or header
    advertisement (but not both) for a given type (N, NP, or CPL)" (p.138)."""
    await _reset_and_init(dut, 0, 0, 0, 0, 0, 0)
    for cls in (POSTED, NON_POSTED, COMPLETION):
        for i in range(200):
            assert await _try_request(dut, cls, 200), (
                f"class {cls} throttled at request {i} despite infinite credit")


@cocotb.test()
async def infinite_and_exhausted_stay_distinguishable(dut):
    """The regression guard against implementing this as '0 always means
    available'.  A pool advertised finite and then consumed to zero must still
    block -- which is exactly why the flag has to be latched at initialisation
    rather than derived from the live remainder."""
    await _reset_and_init(dut, 3, 100, 3, 100, 0, 0)
    for _ in range(3):
        assert await _try_request(dut, POSTED, 1)
    assert _avail(dut)["ph"] == 0

    ready, blocked = await _probe_request(dut, POSTED, 1)
    assert ready == 0 and blocked == 1, (
        "a finite pool consumed to zero must block, even though its remainder "
        "now reads 0 exactly as an infinite pool's advertisement did")

    # ...while the genuinely infinite completion pool beside it does not block.
    ready_cpl, _ = await _probe_request(dut, COMPLETION, 4000)
    assert ready_cpl == 1, "infinite completion pool should never block"


@cocotb.test()
async def zero_valued_update_on_an_infinite_pool_is_ignored(dut):
    """SS2.6.1 p.138: once infinite has been advertised, "If UpdateFC DLLPs are
    sent, the credit value fields must be set to zero and must be ignored".  Our
    DLL forwards those DLLPs (dllp_handler.sv:331-332), so the module must ignore
    the field rather than read the zero as a fresh advertisement.

    This is defect SS0.5.  Commit A could only downgrade it from 'wedged' to
    'over-permissive'; here it is actually correct.
    """
    await _reset_and_init(dut, 8, 100, 8, 100, 0, 0)
    for _ in range(5):
        assert await _try_request(dut, COMPLETION, 50)

    # The compliant zero-valued UpdateFC for an infinite type.
    await _advertise(dut, 8, 100, 8, 100, 0, 0)
    for i in range(200):
        assert await _try_request(dut, COMPLETION, 50), (
            f"infinite completion pool throttled at request {i} after a "
            "zero-valued UpdateFC that should have been ignored entirely")


@cocotb.test()
async def a_non_zero_advertisement_is_still_finite(dut):
    """Proves the fix did not simply turn every pool infinite."""
    await _reset_and_init(dut, 4, 40, 4, 40, 4, 40)
    for _ in range(4):
        assert await _try_request(dut, POSTED, 1)
    ready, blocked = await _probe_request(dut, POSTED, 1)
    assert ready == 0 and blocked == 1, "a finite pool must still exhaust"


@cocotb.test()
async def infinite_and_finite_pools_coexist(dut):
    """One pool infinite, another finite and small, all values forced apart: the
    finite pool must still block at its own limit while the infinite one runs,
    and a third pool must be untouched by either."""
    await _reset_and_init(dut, 2, 20, 0, 0, 7, 70)

    # NP is infinite -- run it far past any finite limit.
    for i in range(200):
        assert await _try_request(dut, NON_POSTED, 300), f"NP throttled at {i}"

    # P is finite at 2 headers and must block on the third.
    for _ in range(2):
        assert await _try_request(dut, POSTED, 1)
    ready, _ = await _probe_request(dut, POSTED, 1)
    assert ready == 0, "finite posted pool did not block while NP was infinite"

    # CPL is finite at 7/70 and was touched by neither.
    got = _avail(dut)
    assert (got["cplh"], got["cpld"]) == (7, 70), "CPL pool was disturbed"


@cocotb.test()
async def a_zero_valued_update_does_not_make_a_finite_pool_infinite(dut):
    """The 'latched at initialisation' property, seen from the other side.

    SS2.6.1.1 p.140 states the determination twice as made "during Flow Control
    initialization", and p.138 makes a post-initialisation zero meaningless
    rather than meaningful -- so it must not promote a finite pool to infinite.

    Added because a mutation that re-latched the flag on every UpdateFC survived
    every other test in this file.
    """
    await _reset_and_init(dut, 8, 4000, 8, 4000, 8, 4000)
    for _ in range(3):
        assert await _try_request(dut, POSTED, 1)

    await _advertise(dut, 0, 4000, 8, 4000, 8, 4000)
    for _ in range(400):
        if not await _try_request(dut, POSTED, 1):
            break
    else:
        raise AssertionError(
            "posted pool never blocked after a zero-valued UpdateFC -- a finite "
            "pool was promoted to infinite by a post-initialisation zero")


# ---------------------------------------------------------------------------
# Commit C -- error_o.
#
# IMPLEMENTATION-DEFINED, not conformance: the spec defines no transmitter-side
# flow-control error at all (every FCPE it names is optional and receiver-side).
# error_o means "this request needs more data credits than the Receiver's whole
# advertised buffer for that type, so no credit return can ever admit it".
# Ordinary blocking stays silent; an infinite pool can never raise it.
# ---------------------------------------------------------------------------


@cocotb.test()
async def error_fires_on_a_permanently_unsatisfiable_request(dut):
    """A request larger than the pool's entire advertised buffer can never be
    satisfied by any amount of credit return, so it is reported rather than
    blocked forever in silence."""
    await _reset_and_init(dut, 8, 16, 8, 16, 8, 16)
    assert int(dut.error.value) == 0

    # 20 data credits against a 16-credit buffer: unsatisfiable by construction.
    dut.request_class.value = POSTED
    dut.request_data_credits.value = 20
    dut.request_valid.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.error.value) == 1, "unsatisfiable request did not raise error_o"
    assert int(dut.request_ready.value) == 0, "it must also not be granted"

    # Self-clearing: withdrawing the request returns error_o low with no ack.
    dut.request_valid.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")
    assert int(dut.error.value) == 0, "error_o did not self-clear"


@cocotb.test()
async def error_stays_silent_for_ordinary_credit_blocking(dut):
    """The SS:102 comment stays true: normal credit blocking is not an error.
    This reproduces the bundled bench's py:30 scenario -- the data pool drained
    to zero by consumption, with a request that the buffer could hold."""
    await _reset_and_init(dut, 2, 4, 2, 4, 2, 4)

    assert await _try_request(dut, POSTED, 4)
    assert _avail(dut)["pd"] == 0
    assert int(dut.error.value) == 0

    # Exactly the py:30 case: blocked, but 1 <= capacity 4, so not an error.
    # The request is HELD across the clock edges rather than probed
    # combinationally: error_o is registered, so a probe that drops
    # request_valid before the edge never samples the condition at all.  A
    # mutation that raised error_o on every block survived the probing version
    # of this test untouched.
    dut.request_class.value = POSTED
    dut.request_data_credits.value = 1
    dut.request_valid.value = 1
    for _ in range(4):
        await Timer(1, units="ps")
        assert int(dut.request_ready.value) == 0 and int(dut.blocked.value) == 1
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        assert int(dut.error.value) == 0, "ordinary credit blocking raised error_o"
    dut.request_valid.value = 0
    await Timer(1, units="ps")


@cocotb.test()
async def error_never_fires_for_an_infinite_pool(dut):
    """The interaction between Commits B and C, and the reason C follows B:
    nothing exceeds infinite, so an infinite pool can never be unsatisfiable --
    however large the request."""
    await _reset_and_init(dut, 8, 0, 8, 0, 8, 0)
    for credits in (1, 100, 2000, 4095):
        dut.request_class.value = COMPLETION
        dut.request_data_credits.value = credits
        dut.request_valid.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ps")
        assert int(dut.error.value) == 0, (
            f"infinite pool raised error_o for a {credits}-credit request")
        assert int(dut.request_ready.value) == 1
    dut.request_valid.value = 0
