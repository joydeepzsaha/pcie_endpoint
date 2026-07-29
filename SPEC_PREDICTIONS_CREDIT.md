# SPEC_PREDICTIONS_CREDIT.md — Phase 0 spec read for `tlp_credit_manager`

**Branch:** `kourosh/dev` · **Written against:** `1131fbd` · **Date:** 2026-07-29
Phase 0 of the Credit-Manager Fixes brief (REV 2). Written **before** any RTL was edited.

> ## ⛔ OUTCOME: the §1.4 accounting-model gate returns verdict **(c)** — a real divergence.
> **Commits A (infinite credit) and B (`error_o`) were NOT implemented.** Per the brief's own
> stop condition, the credit-accounting model must be settled as an architecture decision
> before either bug is fixed on top of it. §D is the evidence; §G is what the decision is.
> **No file under `src/` was touched. This document is the only change.**

---

## A. Primary-source spec citations

All quotations read from `~/openPCIE/0.doc/PCIE-base-spec.Rev2-1.pdf` (PCI Express Base
Specification, Rev. 2.1 — "REV. 2.01" in the running header), extracted with `pdftotext -layout`.
Page numbers are the spec's own printed page numbers. Primary read, not transcription.

### A.1 §2.6.1 "Flow Control Rules" — the six credit types, p. 136

Table 2-35 defines exactly six types tracked per Virtual Channel: `PH`, `PD`, `NPH`, `NPD`,
`CPLH`, `CPLD`. Table 2-36 gives consumption: every request consumes exactly **1 header credit**,
plus `n = Roundup(Length / FC unit size)` data credits; the FC data unit is 4 DW (p. 135).

### A.2 §2.6.1 — what "infinite" is, p. 137–138

Footnote 33, p. 137, attached to the CPLH minimum-advertisement row:

> "This value is interpreted as infinite by the Transmitter, which will, therefore, never throttle."

p. 138:

> "If an Infinite Credit advertisement (value of 00h or 000h) has been made during initialization,
> no Flow Control updates are required following initialization.
>  • If UpdateFC DLLPs are sent, the credit value fields must be set to zero and must be ignored
>    by the Receiver."

> "If only the Data or header advertisement (but not both) for a given type (N, NP, or CPL) has
> been made with infinite credits during initialization, the transmission of UpdateFC DLLPs is
> still required, but the credit field corresponding to the Data/header (advertised as infinite)
> must be set to zero and must be ignored by the Receiver."

### A.3 §2.6.1.1 "FC Information Tracked by Transmitter", p. 139–140

> "CREDITS_CONSUMED — Count of the total number of FC units consumed by TLP Transmissions made
> since Flow Control initialization, modulo 2^[Field Size] ... Set to all 0's at interface
> initialization ... Updated for each TLP the Transaction Layer allows to pass the Flow Control
> gate for Transmission:  CREDITS_CONSUMED := (CREDITS_CONSUMED + Increment) mod 2^[Field Size]"

> "CREDIT_LIMIT — The most recent number of FC units legally advertised by the Receiver. **This
> quantity represents the total number of FC credits made available by the Receiver since Flow
> Control initialization**, modulo 2^[Field Size] ... Set to the value indicated during Flow
> Control initialization. For each FC update received, if CREDIT_LIMIT is not equal to the update
> value, set CREDIT_LIMIT to update value." *(emphasis added)*

The gating function, p. 140:

> "CUMULATIVE_CREDITS_REQUIRED = (CREDITS_CONSUMED + <credit units required for pending TLP>)
> mod 2^[Field Size]"

> "Unless CREDIT_LIMIT was specified as 'infinite' during Flow Control initialization, the
> Transmitter is permitted to Transmit a TLP if, for each type of information in the TLP, the
> following equation is satisfied (using unsigned arithmetic):
>   (CREDIT_LIMIT – CUMULATIVE_CREDITS_REQUIRED) mod 2^[Field Size] <= 2^[Field Size] / 2
> If CREDIT_LIMIT was specified as 'infinite' during Flow Control initialization, then the gating
> function is unconditionally satisfied for that type of credit."

### A.4 §2.6.1.2 "FC Information Tracked by Receiver", p. 141

> "CREDITS_ALLOCATED — Count of the total number of credits granted to the Transmitter since
> initialization, modulo 2^[Field Size] ... **This value is included in the InitFC and UpdateFC
> DLLPs** (see Section 3.4) ... Incremented as the Receiver Transaction Layer makes additional
> receive buffer space available by processing Received TLPs." *(emphasis added)*

### A.5 §2.6.1 — the outstanding-credit cap, p. 138

> "A Receiver must never cumulatively issue more than 2047 outstanding unused credits to the
> Transmitter for data payload or 127 for header."

---

## B. §1.1 — What makes an advertisement infinite, and for which types

**Condition.** An advertised value of `00h` (header fields, 8-bit) or `000h` (data fields, 12-bit)
**made during Flow Control initialization** (A.2, p. 138).

**Which types — not uniform, and the answer has two halves:**

| | Can be advertised infinite? | Is it *required* to be? |
|---|---|---|
| CPLH, CPLD | yes | **Yes** — Table 2-37, p. 137–138: Root Complex not supporting peer-to-peer between all Root Ports, **and Endpoint**: "infinite FC units – initial credit value of all 0s". Restated as a rule on p. 138: "A Root Complex that does not support peer-to-peer traffic between all Root Ports **must** advertise infinite Completion credits." |
| PH, NPH | mechanism is generic (A.2's "for a given type (N, NP, or CPL)") | No — Table 2-37 sets a minimum of 1 unit (`01h`), so a compliant partner will not advertise 0 |
| PD | as above | No — minimum is Max_Payload_Size / FC unit size |
| NPD | as above | No — minimum 1 unit, or 2 for AtomicOp-capable receivers |

**Conclusion for implementation:** infinite must be **representable independently on all six
pools** — the spec's own phrasing ("only the Data or header advertisement (but not both) for a
given type (N, NP, or CPL)", p. 138) contemplates exactly that, per-pool granularity. But the
case that actually matters in this design is **CPLH/CPLD**, which a conforming Root Complex is
*required* to advertise as infinite. The brief's ⭐ on the CPL test is correct and, if anything,
understated: this is not an edge case, it is the mandated normal case for an endpoint.

## C. §1.2 — When the determination is made: **latched at initialization**

Decisive, and stated twice in the gating rule itself (A.3, p. 140): *"Unless CREDIT_LIMIT was
specified as 'infinite' **during Flow Control initialization**"* / *"If CREDIT_LIMIT was specified
as 'infinite' **during Flow Control initialization**, then the gating function is unconditionally
satisfied."*

It is **not** re-evaluated on updates, and A.2 (p. 138) closes the door from the other side: once
infinite has been advertised, any UpdateFC for that type carries a credit field that "must be set
to zero and must be ignored by the Receiver". So a zero arriving *after* initialization carries no
meaning at all — it may not be read as "infinite", and it may not be read as "zero credit".

Two implementation consequences follow:

1. Latch the flag at FC init. A combinational re-derivation from the current value would let a
   pool consumed to zero re-read as infinite — this is the brief's mutation **M-d**, and the spec
   text above is what makes it wrong rather than merely inelegant.
2. **A defect the brief did not anticipate.** `tlp_credit_manager.sv:77-82` reloads the pool
   registers on *every* `fc_update_valid_i`, unconditionally. Against a spec-compliant partner
   that has advertised infinite CPL credit and therefore sends zero-valued UpdateFC_Cpl DLLPs
   (which our DLL does forward — `dllp_handler.sv:331`, `update_fc_c` at `:332`), the current RTL
   **zeroes `cplh_r`/`cpld_r` on every such update**. The pool must ignore those fields entirely.

## D. ⛔ §1.4 GATE — the accounting model. Verdict: **(c), a real divergence**

### D.1 The two models

**Spec (A.3):** two separate quantities per pool. `CREDIT_LIMIT` = cumulative credits *allocated*
since init. `CREDITS_CONSUMED` = cumulative credits *consumed* since init. Both monotonic mod 2^N.
The true remaining credit is their difference.

**RTL:** one register per pool. Loaded from the advertised value (`tlp_credit_manager.sv:77-82`),
decremented on each grant (`:87-96`), compared directly (`:41,:42,:45,:46,:49,:50`).

### D.2 The decrementing *form* is fine — this is not where the divergence is

Let `R = (CREDIT_LIMIT − CREDITS_CONSUMED) mod 2^N` be the true remainder. The spec test
(A.3) is `(R − required) mod 2^N <= 2^N/2`. The RTL test is `R >= required`
(and `!= 0` for headers, which is `>= 1`, exactly the header requirement per Table 2-36).

These are **equivalent**, given the spec's own cap of ≤2047 data / ≤127 header outstanding unused
credits (A.5, p. 138) — i.e. `R <= 2^N/2`:
- `R >= required` → `R − required ∈ [0, 2^N/2]` → test true. ✓
- `R < required` → `(R − required) mod 2^N = 2^N − (required − R)`, and since a single TLP's
  requirement is bounded well under `2^N/2`, this exceeds `2^N/2` → test false. ✓

The spec's `<= 2^N/2` half-space form exists precisely to tolerate the modulo wrap of two
cumulative counters. A design that keeps the *difference* directly does not need it. **So the
decrementing-remainder design is a legitimate reformulation.**

### D.3 Where the divergence actually is — the reload substitutes CREDIT_LIMIT for R

The RTL never computes `R`. On every update it executes `ph_r <= fc_ph_i` — it assigns
**CREDIT_LIMIT directly into the register that is supposed to hold the remainder.**

Traced end to end at this HEAD, `fc_ph_i` is the raw cumulative wire field, with no arithmetic
anywhere on the path:

| Stage | File:line | What it does |
|---|---|---|
| Wire field | — | `HdrFC`/`DataFC` of InitFC/UpdateFC = `CREDITS_ALLOCATED`, cumulative (A.4, p. 141) |
| Extract | `pcie_datalink_pkg.sv:247-251` | `get_fc_values` — pure bit-field concatenation, **no arithmetic** |
| Capture | `dllp_handler.sv:283` (InitFC1_P), `:301` (InitFC2_P), `:319` (UpdateFC_P) | `tx_fc_ph_c` ← raw field |
| Export | `pcie_datalink_layer.sv:177` | `assign fc_ph_o = tx_fc_ph;` |
| Wire through | `pcie_endpoint_top.sv:202` → `tlp_layer.sv:476` | straight through |
| **Consume** | `tlp_credit_manager.sv:77` | `ph_r <= fc_ph_i` — **treated as a remainder** |

So after an update, the RTL holds `CREDIT_LIMIT_latest − (consumed since that update)`, whereas
the true remainder is `CREDIT_LIMIT_latest − CREDITS_CONSUMED_total`. The RTL therefore
**over-states available credit by exactly the consumption that occurred before the update** —
a quantity that grows monotonically (mod 2^N) for the life of the link.

**Direction of the error is the dangerous one.** The transmitter believes it has more credit than
the receiver has buffer, so it keeps transmitting past the limit. That is a receiver-buffer
overrun — the precise condition the spec's optional Receiver Overflow check exists to catch
(§2.6.1.2, p. 141). It is not a stall or a lost packet; it is silent corruption of the peer's
buffer accounting.

### D.4 Corroboration: this design's own receiver half implements the spec model correctly

The RX side of the same endpoint tracks credits **cumulatively and monotonically**, exactly per
A.4 — `dllp2tlp.sv:571-588` only ever does `*_credits_consumed_r + 1` / `+ n`, never decrements,
and `dllp_fc_update.sv:186,212` sends those cumulative values as the DLLP credit fields.

So the two halves of one design use two different accounting models: the receiver half is
spec-correct cumulative, the transmitter half decrements a register loaded from a cumulative
number. This is strong evidence the TX side is a **mismatch rather than a deliberate equivalent
reformulation** — nobody reformulated anything; the two halves were written to different mental
models and never reconciled.

### D.5 Why no test has ever caught it

Every wired harness performs a **single one-shot `fc_update_valid_i` pulse carrying maximal
credits**, then drops it for the rest of the run — `test_tlp_compile.py:27-35` (32s),
`test_tlp_cfg0_spine.py:67-72` (`0xFF`/`0xFFF`), `test_pcie_rq_rc_top.py:405-410`. With exactly
one load and a pool that never drains, `CREDITS_CONSUMED` at update time is 0 and the RTL's model
and the spec's model **coincide exactly**. The divergence requires repeated UpdateFC DLLPs against
sustained traffic — i.e. a real link partner. This is a textbook instance of the project's
recurring degenerate-value-space lesson, now in its fifth instance.

### D.6 Verdict

**(c) — a real divergence that will bite against a real device.** Per the brief §1.4, **STOP.**

Note this **subsumes §0.3**. The brief asked whether `fc_*_i` is "an absolute reload or an
increment"; the spec answer is **neither** — it is a cumulative allocation counter against which
cumulative consumption must be subtracted. Once a separate `CREDITS_CONSUMED` register exists, the
`:76-99` update/consume collision dissolves on its own, because the load and the decrement stop
targeting the same register. The collision is a symptom of the missing counter, not an independent
bug.

## E. §1.3 — What the transmitter must do once infinite is in force

- **Gating:** "unconditionally satisfied for that type of credit" (A.3, p. 140); "will, therefore,
  never throttle" (fn 33, p. 137).
- **Tracking:** the spec states `CREDITS_CONSUMED` is updated "for each TLP the Transaction Layer
  allows to pass the Flow Control gate" (A.3, p. 139) with **no infinite exception**. So tracking
  continues; only the gating stops depending on it.
- **Receiver obligation:** "no Flow Control updates are required following initialization" for an
  infinite type; if sent anyway, credit fields must be zero and must be ignored (A.2, p. 138).

## F. §1.5 — What the spec leaves silent or implementation-defined

Recording these explicitly, per the brief's instruction and the completion-timeout precedent that
"the spec permits X" did not survive a primary read. **Silence is not permission.**

1. **All Flow-Control Protocol Error checks are optional and receiver-side.** Every FCPE the spec
   names — >2047/127 outstanding credits (p. 138), non-zero UpdateFC on an infinite type (p. 138),
   Receiver Overflow (p. 141) — is introduced with "Components **may optionally** check". All are
   associated with the *Receiving* Port.

2. **⚠️ The spec defines no transmitter-side flow-control error output at all.** This bears
   directly on Commit B. The brief's §3.1 presents the `error_o` condition ("requested credits
   exceed the advertised limit") as decided; that is a reasonable local design choice, but it is
   **not a spec-defined condition** and must be documented as implementation-defined rather than
   as conformance. The spec's only stated transmitter obligation on insufficient credit is
   behavioural, not diagnostic: *"If the Transmitter does not have enough credits to transmit the
   TLP, it must block the transmission of the TLP"* (p. 140).

3. **The spec is silent on permanently-unsatisfiable requests.** It draws no distinction between a
   request temporarily blocked and one whose requirement exceeds the advertised limit forever, and
   prescribes no timeout, error, or escape for the latter. The `:102` comment ("Normal credit
   blocking is not a protocol error") is therefore correct *and* complete as far as the spec goes —
   there is no spec-mandated condition being suppressed there.

4. **Not silent, contrary to a plausible assumption:** whether infinite pools still track
   consumption *is* specified (see §E) — no exemption is granted.

## G. What the architecture decision needs to settle

Not a bug fix; recorded here so the decision is made once, with the evidence in front of it.

1. **Adopt the spec's two-register model per pool** — a `credit_limit_r` latched/updated from
   `fc_*_i`, and a monotonic `credits_consumed_r`. Keep the cheap `R >= required` comparison
   (§D.2 proves it exact under the spec's own outstanding-credit cap); compute `R` as
   `credit_limit_r − credits_consumed_r` rather than storing it. This is a contained change to
   `tlp_credit_manager.sv` with **no port changes** — `fc_*_i` already carries the right quantity;
   it is only being interpreted wrongly.
2. **Then, and only then,** the infinite flag (Commit A) drops in cleanly: latch six flags at FC
   init, bypass the gate for flagged pools, and ignore the credit field of subsequent updates for
   those pools (§C.2).
3. **Commit B (`error_o`) should be re-scoped** in light of §F.2 — either define it explicitly as
   an implementation-defined local health signal, or reconsider whether the more useful transmitter
   error is the spec-adjacent one: detecting that our own consumption has passed the advertised
   limit, which is only computable once §G.1 exists.

## H. Prediction recorded before any run

Existing harnesses set credits to `0xFF`/`0xFFF` in a single pulse, so **nothing pre-existing
should move** under any of this. Recorded per the brief; not exercised, since no RTL was changed.

---
---

# REV 3 — the implementation, written against `03d4915`

Sections A–H above are the Phase 0 read that stopped REV 2 at its gate. Everything below is the
REV 3 build that acts on it. **§J was written and committed before the modified DUT was run.**

## I. Recon (§2.1) — answers

### I.1 Pool set and widths — confirmed six, spec-matched

`tlp_credit_manager.sv:31-32` declares exactly six: `ph_r`/`nph_r`/`cplh_r` at **8 bits** and
`pd_r`/`npd_r`/`cpld_r` at **12 bits**. These are already the spec's `[Field Size]` moduli
(§2.6.1.1, p.139: "8 for PH, NPH, and CPLH and 12 for PD, NPD and CPLD"), so **plain N-bit
arithmetic gives the required `mod 2^[Field Size]` behaviour for free** — no explicit masking is
needed anywhere, provided every counter and every subtraction stays at its native width.

### I.2 ⭐ Can the module distinguish InitFC from UpdateFC? — **Yes, without a port change**

This was the brief's stated hinge for Commit B. The answer is yes, and the mechanism is
**"the first `fc_update_valid_i` pulse after reset is the FC-initialisation load."** Evidence:

1. `pcie_datalink_layer.sv:176`: `assign fc_update_valid_o = update_fc || fc_init_done;` — the
   strobe has exactly two sources.
2. `update_fc` is asserted **only** by the three `UpdateFC_*` cases in `dllp_handler.sv`
   (`update_fc_c = '1` at `:320`, `:326`, `:332`). The six `InitFC1_*`/`InitFC2_*` cases store
   values but **never** set it (`:281-316`).
3. `fc_init_done` (`pcie_datalink_layer.sv:413`) is
   `fc2_values_stored && !fc2_values_stored_reg` — a **one-cycle rising-edge pulse** on
   "all three InitFC2 DLLPs stored", i.e. precisely FC-initialisation completion.
4. Per §3.3, UpdateFC DLLPs cannot legally precede the exit from FC_INIT2.

So the first strobe the module ever sees carries the **initial advertisement**, and every later
strobe carries an **update**. A single `fc_init_seen_r` bit is sufficient; no DLL-side signal and
no new port is required. **Commit B is feasible as scoped.**

*Why not use `fc_initialized_i` instead:* it is `fc2_values_sent && fc2_values_stored`
(`pcie_datalink_layer.sv:175`), which gates on *our* InitFC2 having been sent as well. Its rising
edge therefore need not coincide with the `fc_init_done` strobe, so it is not a reliable
same-cycle discriminator. It remains what it already is — the transmit-enable gate at `:53`.

*Caveat recorded, not acted on:* `fc2_values_stored` is cleared only by the DLL's `rst_i`
(`dllp_handler.sv:164-166`), while the credit manager is reset by
`layer_reset = rst_i || !link_up_i` (`tlp_layer.sv:225`). A retrain that drops `link_up_i` without
asserting `rst_i` would reset the credit manager without producing a fresh `fc_init_done`, leaving
the pools at zero and TX wedged. That is a **pre-existing relink concern in the DLL/TL reset
coupling**, orthogonal to this brief, and is not addressed here.

### I.3 Consumers of the module's outputs

| Output | Consumer | Note |
|---|---|---|
| `request_ready_o` | `tlp_layer.sv:280` → `vc_packet_ready` | the TX gate |
| `blocked_o` | `tlp_layer.sv:481` → `tx_fc_blocked_o` | externally visible |
| `error_o` | `tlp_layer.sv:283` → `tx_error_valid_o`; `:286` → `TLP_ERR_CREDIT_UNDERFLOW` | **not inert** — Commit C's assertion raises the TL error path |
| all six `*_available_o` | **unconnected** — `tlp_layer.sv:482-485` | read only by the bench |

The six `*_available_o` being unconnected means their semantics are free. **They keep reporting the
remainder** (`limit − consumed`), which is what the existing bench's `ph_av`/`pd_av`/`cplh_av`/
`cpld_av`/`nph_av`/`npd_av` assertions already expect — so no existing assertion needs to move.

## J. The gating comparison — derivation and wrap argument

*(Committed before the modified DUT was run, per brief §7.2.)*

**Claim.** With `R` the N-bit remainder computed as `limit_r − consumed_r` (native N-bit
subtraction, hence automatically `mod 2^N`), the simple unsigned test

> `R >= required`

is **exactly equivalent** to the spec's half-space test (§2.6.1.1, p.140)

> `(CREDIT_LIMIT − CUMULATIVE_CREDITS_REQUIRED) mod 2^N <= 2^N / 2`

under two preconditions, both of which the spec itself guarantees.

**Preliminary.** `CUMULATIVE_CREDITS_REQUIRED = (CREDITS_CONSUMED + required) mod 2^N`, so the
spec's left-hand side is `(limit − consumed − required) mod 2^N = (R − required) mod 2^N`.

**Precondition 1 — `R <= 2^N/2 − 1`.** §2.6.1, p.138: *"A Receiver must never cumulatively issue
more than 2047 outstanding unused credits to the Transmitter for data payload or 127 for header."*
Outstanding unused credits *is* `R`. And `2047 = 2^12/2 − 1`, `127 = 2^8/2 − 1` — the spec's cap is
exactly this bound, for both widths.

**Precondition 2 — `required <= 2^N/2 − 1`.** Headers: Table 2-36 (p.136) gives every TLP exactly
**1** header credit, so `required = 1`. Data: `n = Roundup(Length / FC unit size)` with the FC data
unit 4 DW (p.135) and Length at most 1024 DW, so `n <= 256`, well under 2047.

**Proof.**
- *Case `R >= required`.* Then `R − required ∈ [0, R] ⊆ [0, 2^N/2 − 1]`; no borrow, so
  `(R − required) mod 2^N = R − required <= 2^N/2`. Spec test **true**; simple test **true**. ✓
- *Case `R < required`.* Then `required − R ∈ [1, 2^N/2 − 1]` by Precondition 2, so
  `(R − required) mod 2^N = 2^N − (required − R) ∈ [2^N/2 + 1, 2^N − 1]`, strictly greater than
  `2^N/2`. Spec test **false**; simple test **false**. ✓

**Where it would break, and why it cannot.** The two forms diverge at exactly one point: if
`required − R = 2^N/2`, the spec's expression evaluates to `2^N/2`, which *satisfies* `<= 2^N/2`
while the simple test rejects. Precondition 2 excludes that point by a strict inequality, and it is
excluded with enormous margin (256 vs 2048 for data; 1 vs 128 for headers). This is the only
boundary in the equivalence and it is worth naming rather than hand-waving past.

**Header form.** Since `required = 1` always for headers, `R >= 1` ≡ `R != 0`. The existing
`!= 0` comparisons at `:41,:45,:49` are therefore kept verbatim — they are already the correct
test, they were merely being applied to the wrong quantity.

**Why the modulo needs no explicit handling.** Both `limit_r` and `consumed_r` are cumulative
counters that wrap at `2^N` (spec: "modulo 2^[Field Size]", p.139/p.141). Their N-bit difference is
`(limit − consumed) mod 2^N` regardless of whether either has wrapped, which by Precondition 1 is
the true outstanding credit. A wrapped `CREDIT_LIMIT` — including one that has wrapped to exactly
`0` — therefore needs no special case: it is a legitimate cumulative value and the subtraction
handles it. This is precisely the property the old single-register design destroyed.

## K. What Commit A alone fixes, and what it does not

Recorded so the interim state is not overstated (brief §2.3.4).

**A fixes:** the over-statement of available credit under repeated UpdateFC (§D.3); the `:76-99`
load/consume collision, which disappears structurally because limits and consumption now live in
different registers written by disjoint logic (§0.6).

**A does *not* fix §0.5** — it changes its failure mode. A zero-valued `UpdateFC` on a pool that
should be infinite currently zeroes the remainder and **wedges** TX. After A, that zero is
interpreted as a legitimately-wrapped cumulative limit, giving `R = (0 − consumed) mod 2^N`, a
large value — so the pool becomes **over-permissive** instead of wedged. Neither is correct.
Only **Commit B** makes it correct, by latching the pool as infinite at init and thereafter
**ignoring** the credit field of updates for that pool (p.138). Test 2.3.4 asserts the
not-wedged property that A does deliver, and Commit B's tests close the rest.
