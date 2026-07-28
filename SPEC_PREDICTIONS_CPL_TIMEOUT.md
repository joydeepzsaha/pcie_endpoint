# SPEC_PREDICTIONS_CPL_TIMEOUT.md — Phase 1 predictions for the `tlp_request_tracker` Completion Timeout

**Branch:** `kourosh/dev` · **Written against:** `cc1e194` · **Date:** 2026-07-28
Companion to `RECON_cpl_timeout.md`. Written **before** any RTL was edited and before any new test
was run. The "Actual" column was filled in afterwards; every falsification is called out in §F.

Pattern note: the established convention in this repo is a repo-root `SPEC_PREDICTIONS_<AREA>.md`
(cf. `SPEC_PREDICTIONS_RQ_RC.md`), not a file under `tb/tlp/`. This follows that.

---

## A. Primary-source spec citations

**All quotations below are read from the PDF on this server**, `~/openPCIE/0.doc/PCIE-base-spec.Rev2-1.pdf`
(PCI Express Base Specification, Rev. 2.1 / "REV. 2.01" in the running header), extracted with
`pdftotext -layout`. Page numbers are the spec's own printed page numbers. This is a **primary
read**, not the off-server transcription discipline that `SPEC_PREDICTIONS_RQ_RC.md` had to use for
PG213.

### A.1 §2.8 "Completion Timeout Mechanism", p. 152

> "In any split transaction protocol, there is a risk associated with the failure of a Requester to
> receive an expected Completion. To allow Requesters to attempt recovery from this situation in a
> standard manner, the Completion Timeout mechanism is defined. This mechanism is intended to be
> activated only when there is no reasonable expectation that the Completion will be returned, and
> should never occur under normal operating conditions."

> "PCI Express device Functions that issue Requests requiring Completions must implement the
> Completion Timeout mechanism. An exception is made for Configuration Requests (see below)."

> "The Completion Timeout mechanism is activated for each Request that requires one or more
> Completions **when the Request is transmitted**. Since Switches do not autonomously initiate
> Requests that need Completions, the requirement for Completion Timeout support is limited only to
> **Root Complexes**, PCI Express-PCI Bridges, and Endpoints." *(emphasis added)*

> "The Completion Timeout mechanism may be disabled by configuration software. The Completion
> Timeout limit is set in the Completion Timeout Value field of the Device Control 2 register."

> "Note: A Memory Read Request for which there are multiple Completions must be considered
> completed only when all Completions have been received by the Requester. If some, but not all,
> requested data is returned before the Completion Timeout timer expires, **the Requester is
> permitted to keep or to discard the data that was returned** prior to timer expiration."

*(§2.8 cross-references "Section 2.2.9" for the Device Control 2 register; that is a spec
cross-reference error — the register is defined in §7.8.16. Noted, not relied on.)*

### A.2 §7.8.16 "Device Control 2 Register (Offset 28h)", Table 7-25, pp. 549–550

Bits 3:0, Completion Timeout Value:

> "A Function that does not support this optional capability must hardwire this field to 0000b and
> is required to implement a timeout value in the range **50 µs to 50 ms**."
> "0000b — Default range: 50 µs to 50 ms"
> "It is **strongly recommended that the Completion Timeout mechanism not expire in less than 10 ms**."

Programmable ranges (Table 7-25, p. 549): Range A 50 µs–10 ms; Range B 10 ms–250 ms;
Range C 250 ms–4 s; Range D 4 s–64 s.

Bit 4, p. 550:

> "Completion Timeout Disable – When Set, this bit disables the Completion Timeout mechanism."

### A.3 §6.2.3.2.4.4 "Requester with Completion Timeout", p. 374

> "When the Requester of a Non-Posted Request times out while waiting for the associated
> Completion, the Requester is permitted to attempt to recover from the error by issuing a separate
> subsequent Request. The Requester is permitted to attempt recovery zero, one, or multiple
> (finite) times…"

### A.4 §6.2.3.2.4.5 "Receiver of an Unexpected Completion", pp. 374–375

> "If the unexpected Completion was a result of misrouting, the Completion Timeout mechanism at the
> associated Requester will trigger eventually… Interference with Requester recovery can be avoided
> by having the Receiver of the unexpected Completion handle the error as an Advisory Non-Fatal
> Error."

---

## B. What the spec justifies, and what it does not

| Brief §1 policy | Spec support | Verdict |
|---|---|---|
| §1.1 timeout is the requester's job, in the TL | §2.8 p.152: "must implement", limited to "Root Complexes, … Endpoints" | ✅ supported |
| §1.2 `0` disables the mechanism | §7.8.16 bit 4 "Completion Timeout Disable" (p.550) | ✅ supported — the escape hatch mirrors a real architected control |
| §1.2 default 4096 cycles | **NOT spec-conformant.** §7.8.16 p.549 requires 50 µs–50 ms and "strongly recommend[s] … not … less than 10 ms". 4096 cycles at the 250 MHz / 4 ns bench clock is **16.4 µs** — inside the 50 µs–50 ms floor only if you round generously, and two orders of magnitude below the recommended 10 ms. | ⚠️ **sim-practical, not spec-real.** Recorded as such in the module header; a real value is a Stage-H concern. 10 ms at 250 MHz = 2 500 000 cycles. |
| §1.3 timer starts at allocation | §2.8 p.152: "activated … when the Request is transmitted" | ✅ supported (allocation is one cycle before transmission here) |
| §1.3 **timer restarts on a received partial completion** | **The spec is SILENT.** §2.8's multi-completion Note governs only whether returned *data* may be kept or discarded; it says nothing about the timer. No text in §2.8, §6.2.3.2.4.4 or §7.8.16 either permits or forbids restart. | ⚠️ **The brief's claim "§2.8 permits this" is not supported by quoted text.** It is *not forbidden*, so it remains a legal implementation choice, and it is the forgiving one. Policy unchanged; the justification is corrected from "permitted by §2.8" to "unspecified by §2.8, therefore implementation-defined". |
| §1.4 QUARANTINE rather than immediate recycle | §6.2.3.2.4.5 p.374–375 explicitly worries about a late/misrouted Completion colliding with Requester recovery | ✅ supported in spirit; the exact quarantine is a design choice |
| §1.6 a timed-out request is failed; partial data is the FSM's problem | §2.8 p.152: "the Requester is permitted to keep or to discard the data that was returned prior to timer expiration" | ✅ explicitly permitted |
| §1.5 late completion drained **silently** (no `unexpected_completion_o`) | A CPL for a tag no longer outstanding is by construction an Unexpected Completion (§6.2.3.2.4.5). We suppress that report and raise the more specific `late_cpl_valid_o` instead. | ⚠️ **deliberate deviation**, documented in the module header. `late_cpl_valid_o` is strictly more information than `unexpected_completion_o` would have been, and §6.2.3.2.4.5 classes the case as an *Advisory* Non-Fatal Error — advisory, not required-fatal. |
| §1.7 ZOMBIE counts in `outstanding_o` | not a spec concern | design choice, see `RECON_cpl_timeout.md` §6 |

---

## C. Timing model (predicted, derived from the design in `RECON_cpl_timeout.md` §6)

`cycle_counter_r` and `scan_index_r` both start at 0 on the first non-reset edge and increment every
cycle, so `scan_index_r == cycle_counter_r mod TAG_COUNT` for `TAG_COUNT = 32`.

Let **C** = value of `cycle_counter_r` sampled at the allocation edge (the edge on which
`allocate_valid_i && allocate_ready_o`), and let **k** count rising edges after that edge. At edge
*k* the scan sees `cycle_counter_r == C + k`, `age == k`.

> **k_fire(T, C) = min { k ≥ CPL_TIMEOUT_CYCLES : (C + k) ≡ T (mod 32) }**

The strobe is a **registered** output set at edge `k_fire`, so cocotb sampling
(`await RisingEdge; await Timer(1, 'ps')`) reads `cpl_timeout_valid_o == 1` **at sample index
k_fire** — one edge later than the age first reaches the threshold in the general case. This is the
**N+1 registered-state off-by-one** the realtimer work measured; it is predicted here, not
discovered.

Window form (used where the phase is not pinned): `k_fire ∈ [CPL_TIMEOUT_CYCLES,
CPL_TIMEOUT_CYCLES + 31]`.

**Second expiry (ZOMBIE→FREE).** The scan rewrites `alloc_time_r[T] = C + k_fire` at the timeout
edge, and `C + k_fire ≡ T (mod 32)` by construction. So the second expiry is at exactly
`k' = CPL_TIMEOUT_CYCLES` further edges when `CPL_TIMEOUT_CYCLES` is a multiple of 32 — **exactly
64 for the standalone target, exactly 4096 for the default.** No phase term.

---

## D. Predicted-behaviour table

Standalone tests run on **`verilate_tlp_cpl_timeout`** with `CPL_TIMEOUT_CYCLES = 64`,
`TAG_COUNT = 32`, 10 ns clock (`tb_tlp_request_tracker`, tracker ports driven directly).
Integration tests run on **`verilate_rq_rc_top`** at the **default 4096**, 4 ns clock.

| # | Test | Predicted behaviour | Predicted fire cycle | Predicted result | Actual |
|---|---|---|---|---|---|
| **T1** | basic fire | one allocation, no completion ever. `cpl_timeout_valid_o` pulses **exactly one cycle**, `cpl_timeout_tag_o == 0`. Tag → ZOMBIE: `allocate_ready_o` still 1 (31 tags free) but tag 0 is **not** the next tag offered. `outstanding_o` stays **1** (§1.7). No `result_valid_o`, no `unexpected_completion_o`. | `k_fire = min{k ≥ 64 : (C+k) ≡ 0 mod 32}`, window **[64, 95]**; test asserts the **exact** value using a Python mirror of `cycle_counter_r` | PASS | |
| **T1b** | default value pinned (`verilate_tlp_cpl_timeout_default`, param = 4096) | same shape, proves the **default** is 4096 and not the test value | no strobe anywhere in k ∈ [1, 4095]; strobe in window **[4096, 4127]** | PASS | |
| **T2** | **wedge regression (headline)** | 34 unanswered allocations. Only 32 allocate (tags 0…31, one per cycle); `allocate_ready_o` falls to 0 and `outstanding_o == 32`. All 32 then time out one cycle apart, `outstanding_o` **stays 32** (zombies count). Second expiry frees them one cycle apart; `allocate_ready_o` **rises again** and requests 33 and 34 are accepted. | tag *i* allocated at `C0+i` fires at the same offset for every *i* (allocations are 1 cycle apart, so fires are too); FREE at exactly **+64** after its own fire edge | PASS — **and this test HANGS against `cc1e194`** (`allocate_ready_o` never returns; the cocotb wait for it times out). That failure-against-baseline is the point of the test. | |
| **T3** | timer restart | allocate tag 0, `expects_data=1`, `byte_count=8`. At k=60 (before the 64 threshold) deliver a **partial** CplD: `payload_bytes=4, byte_count=8, lower_address=0` → accepted (passes the `:127-135` guard), `result_valid_o` pulses with `result_last_o == 0`, `remaining_r` → 4. **No `cpl_timeout_valid_o` at the original k_fire.** Then silence → strobe one full interval after the partial. | no strobe in [1, 60+63]; strobe at `min{k' ≥ 64 : (C+60+k') ≡ 0 mod 32}` measured from the **partial's** edge, window **[64, 95]** after it | PASS | |
| **T4** | late completion, single | allocate tag 0 (`expects_data=1, byte_count=4`), let it time out → ZOMBIE. Then deliver a CplD `status=SC, payload_bytes=4, byte_count=4, lower_address=0` → last-CPL true ⇒ RC descriptor **bit 30 set**. Expect: `late_cpl_valid_o` 1-cycle pulse with `late_cpl_tag_o == 0`; **`result_valid_o` never asserts**; `unexpected_completion_o` never asserts; `outstanding_o` → 0. Reallocation then **returns tag 0**, and a fresh request+completion on it delivers a normal `result_valid_o` with the new context. | late strobe at the edge following the completion handshake (registered, N+1) | PASS | |
| **T5** | second expiry | allocate, time out, then nothing ever arrives. Tag → FREE; **no `late_cpl_valid_o` ever**; `outstanding_o` 1 → 1 (zombie) → 0. | FREE at exactly **+64** edges after the timeout edge (no phase term, §C) | PASS | |
| **T6 / V-T3** | multi-beat late drain (integration, `verilate_rq_rc_top`) | a **memory read** for 16 bytes (4 DW) times out, then a 4-DW CplD arrives. All **4 payload beats** are consumed (`received_completion_data_ready` high throughout the packet via `pcie_rc_if.sv:341-343` S_IDLE orphan drain), **no `m_axis_rc` packet is emitted**, `late_cpl_valid_o` pulses once, and the design does **not** wedge — a subsequent request + completion round-trips normally. 4 beats, not 1: length and drain accounting are forced apart. | drain spans the whole packet; `pcie_rc_if.sv:406` `$warning` fires once per orphaned Dword (expected, benign) | PASS | |
| **T7** | disabled control (`verilate_tlp_cpl_timeout_off`, param = 0) | the **unmodified** `test_tlp_request_tracker` module re-run with `CPL_TIMEOUT_CYCLES = 0`. Every test passes and the **total sim time matches `verilate_tlp_request_tracker` to the ns**. Neither strobe ever asserts. | n/a | PASS, sim end time identical | |
| **V-T1** | integration, config read with no completion | via `pcie_rq_rc_top`: a CfgRd0 is emitted, `pcie_rq_tag_vld_o` pulses with tag *t*. No completion. `cpl_timeout_valid_o` is observable **at the top level** with `cpl_timeout_tag_o == t` (tag correlation against the earlier `pcie_rq_tag_o`). The interface accepts subsequent requests **immediately** (31 tags remain free — recovery here does not need the zombie to expire). | window **[4096, 4127]** edges after the tag-allocation edge | PASS | |
| **V-T2** | integration, mixed load | three reads issued → tags **0, 1, 2** (forced apart, not all zero). Only tag **1** is answered. Predict: tag 1's completion produces a correct RC packet with the right context; tags **0 and 2** each raise exactly one `cpl_timeout_valid_o`, one cycle apart in tag order; no timeout is reported for tag 1; no result is delivered for 0 or 2; `outstanding_o` ends at 2 (two zombies) before their second expiry. | tags 0 and 2 fire 2 cycles apart (scan visits 0 then 2) | PASS | |

### Mutation predictions (stated before running)

| Mutation | Predicted catcher |
|---|---|
| **M-a** ZOMBIE immediately allocatable (drop quarantine) | **T4** — reallocation returns tag 0 too early and the late completion then lands on a live request |
| **M-b** timer does not restart on a partial completion | **T3** |
| **M-c** late drain delivers the completion on the result interface | **T4** (and T6/V-T3) |
| **M-d** expiry comparison off by one interval (`>` a doubled threshold) | **T1** exact-cycle assert |

---

## E. Behaviour-neutrality prediction (brief §5.2)

With the default 4096, **no existing test fires either strobe.** Basis: the longest-running test in
the entire TL/RC suite is `v4_backpressure_tag_exhaustion_recovery` at 606 cycles, and the longest
tracker test is `tag_exhaustion` at 177 cycles (`RECON_cpl_timeout.md` §4). Every test resets the
DUT first, so timers cannot accumulate across tests. Predicted margin: **6.8×** at the tightest
point. To be confirmed by a live monitor over the full sequential regression, not by this argument.

---

## F. Falsifications and corrections

Filled in after the runs. Anything predicted above that did not happen is recorded here verbatim
rather than smoothed into the table.
