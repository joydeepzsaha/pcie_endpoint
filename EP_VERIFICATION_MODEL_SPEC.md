# EP_VERIFICATION_MODEL_SPEC — the endpoint model the RC benches enumerate

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` · written at the close of Stage C.

This discharges the deliverable owed since the Commit-2b master brief. It
specifies the **completer** side of the Root Complex benches: the surface a
model must present, the behaviour it must implement, and — the part that keeps
being learned the hard way — **the behaviour it must NOT implement**, because a
model that is too polite makes a broken DUT look correct.

It is written so that Joy's protocol-checking endpoint model can be dropped in
behind the same four names and the existing enumeration tests keep their
meaning. It is also the thing that makes Stage E possible.

---

## 0. Why this is a specification and not a README

**Bench code that behaves like RTL is exactly as capable of being wrong as RTL,
and its failure mode is worse.** A broken DUT fails loudly. A broken completer
model produces a green suite.

Every requirement below exists because something in Commits 2b-1 … 2b-3 either
went wrong or was one step away from going wrong. Each carries the reason. Where
a requirement was learned from a measured failure, that is said plainly — those
are the ones most likely to be "simplified" back out by someone who has not hit
them.

The models are therefore **mutation-tested like RTL**. A completer change that
no test notices is a completer requirement that is not actually being relied on,
and should be deleted rather than kept for comfort.

---

## 1. The four-name interface — preserved verbatim across three increments

Every completer, standalone or integration, presents exactly these:

| name | kind | contract |
|---|---|---|
| `.start()` | method | begin observing the request stream. Non-blocking; spawns its own coroutine. |
| `.seen` | list, live | every request observed so far, **in emission order**, decoded. Append-only. |
| `.wait_for(n, cycles=…)` | coroutine | block until `len(.seen) >= n`; raise on exhaustion with the observed list in the message. |
| `.complete(req, status=…, data=…)` | coroutine | deliver exactly one completion for `req`. |

`serve()` — auto-answer everything from a configuration-space model — is an
**additional** convenience and replaces none of the four. A test that needs
transaction-by-transaction control uses the four directly.

**This interface is frozen.** Three completers now implement it
(`ConfigCompleter` 2b-1, `ConfigSpaceCompleter` 2b-2, `BarSpaceCompleter` 2b-3)
and they are genuinely different models — the contract lives here rather than in
a shared base class, deliberately, so a fourth implementation is free to share
nothing but the names.

### 1.1 `wait_for` must raise, never return quietly

On exhaustion it raises with the count and the observed list. A `wait_for` that
returned after a timeout would turn "the DUT emitted nothing" into "the
assertions below ran against an empty list" — see §5.

---

## 2. Configuration space

### 2.1 Registers the model must serve

| register | offset | content | citation |
|---|---|---|---|
| 0 | `00h` | `{Device ID[31:16], Vendor ID[15:0]}` | [BASE] Figure 7-5 p.491 |
| 1 | `04h` | `{Status[31:16], Command[15:0]}` | [BASE] Figure 7-5 p.491 |
| 3 | `0Ch` | `{BIST, Header Type[23:16], MLT, CLS}` | [BASE] Figure 7-5 p.491 |
| 4–9 | `10h`–`24h` | Base Address registers 0–5 | [BASE] Figure 7-5 p.491 |

**Vendor ID must not be `FFFFh`.** Absence is signalled by UR and by nothing
else; a sentinel Vendor ID would let a silent-conversion bug pass unnoticed
(§D of `SPEC_PREDICTIONS_ENUM.md`). The benches use `144Dh`/`A80Ah`.

**Register 12 (`30h`, Expansion ROM) must NOT be modelled.** It is asserted
never to be accessed (P-NO-ROM). Modelling it would give a wrong answer rather
than no answer if the DUT ever reached it, because its bit 0 is Expansion ROM
Enable, not a Memory Space Indicator ([PCI3] p.228 `:11318`).

### 2.2 Byte enables are honoured on writes

A write applies only to the bytes selected by `first_be`. The Command register
is written with `first_be = 0011` precisely so the Status half — several of
whose bits are write-1-to-clear — is not disturbed. **A model that ignored byte
enables would make that distinction untestable**, and the Command write's byte
enables turn out to be the only observable proving the enumeration handoff mux
selects rather than merges (§E.10.4).

---

## 3. ⭐ Base Address register semantics — the part that is easy to get wrong

### 3.1 The requirement

For a BAR of size `S` (a power of two):

```
writable_mask = ~(S - 1)     restricted to the register's writable field
read_only     = the type/prefetch field
read(reg)     = (stored & writable_mask) | read_only
write(reg,v)  = stored := (stored & ~(writable_mask & byte_mask))
                        | (v & writable_mask & byte_mask)
```

| BAR kind | read-only bits | field value | citation |
|---|---|---|---|
| 32-bit memory | `[3:0]` | `{prefetch, 0, 0, 0}` | [PCI3] p.225 `:11190`, `:11193` |
| 64-bit memory | `[3:0]` of the LOWER register only | `{prefetch, 1, 0, 0}` | Table 6-4 p.226 `:11207` |
| I/O | `[1:0]` | `01` (bit 0 hardwired 1, bit 1 reserved reads 0) | p.225 `:11187` |

The upper register of a 64-bit pair has **no** read-only field: it is 32
ordinary address bits.

### 3.2 Why — the one sentence the whole thing rests on

[PCI3] §6.2.5.1 p.226 `:11205`: **"Bits 0-3 are read-only."** That clause is what
makes all-ones sizing work at all — the write cannot disturb the type/prefetch
encoding, so the readback still identifies the BAR while its upper bits report
the size. Paired with `:11222`, *"The device will return 0's in all don't-care
address bits."*

### 3.3 ⛔ A completer that echoes BAR writes verbatim makes sizing return garbage

It would report every BAR as 4 GB and destroy the encoding the next read
depends on. **The DUT would look broken when the model is.** This is the 2b-2
silent-UR trap one layer up.

**Requirement: the model counts its own masking, and tests assert the count.**
`assert_mask_exercised()` fails if no write ever had a bit dropped inside the
read-only field. Both halves matter — the arm must be *present* and *proved
live*. Mutation-tested: forcing verbatim echo kills eight tests; disabling the
check kills the guard self-test.

⚠️ **One gate, not two.** An earlier version asserted two counters where the
second strictly implied the first. Defeating the first could not change any
verdict, and it survived mutation. **A redundant assertion is not a stronger
check; it is an untested one.**

### 3.4 Sizes are validated at construction

A BAR spec with a non-power-of-two size is rejected by the model, and there is
deliberately **no way to build a Reserved Type field**. Illegal encodings are
injected through the separate mechanism in §4.2 — a model that could build
malformed devices by accident would let a test think it was exercising the happy
path when it was not.

---

## 4. Fault injection

### 4.1 ⛔ The default arm is UR, never silence

A register the model does not implement is answered with an **Unsupported
Request**. [BASE] §7.3.3 p.480: a Type 0 request not addressing "a valid local
Configuration Space of an implemented Function" must "follow rules for handling
Unsupported Requests".

**Silence would drive the sequencer into a completion timeout and look exactly
like an FSM bug.** The model counts the arm (`ur_default_hits`) so a test can
assert it was, or was not, exercised.

### 4.2 The injection mechanisms, and why each is first-class

| mechanism | effect | why it is a model feature |
|---|---|---|
| `raw={reg: value}` | that register answers a **fixed** value and **absorbs writes** | §4.3 |
| `ur_regs={reg}` | answer UR regardless of the model's contents | §4.3 |
| `crs_once={reg}` | answer CRS the first time, then normally | the retry is a NEW request ([BASE] §2.3.2 p.121) |
| `silent_regs={reg}` | answer nothing; the test drives the timeout | the only way to reach the timeout path |

### 4.3 ⚠️ AN INJECTION THE DUT'S OWN TRAFFIC OVERWRITES IS NOT AN INJECTION

**Measured twice in one increment, in two different benches.**

The obvious way to make a register answer something unusual is to poke it into
the model's register store. It does not work for a BAR, because the DUT's
**all-ones sizing write arrives first**: the poked value is overwritten, the
readback returns `FFFFFFFF`, bit 0 is set, and the FSM correctly classifies the
register as an **I/O BAR and skips it**. Three fault tests passed their DUT and
failed their own premise; one reported `io_bar_mask` set and gave the game away.

The same shape hit the integration bench from the other direction: deleting a
register so the default UR arm would answer it instead **created** the entry on
the sizing write, so the arm never fired.

**Requirements:**
1. An injected value must be **write-immune**, and the model must count the
   writes it absorbed (`raw_writes_discarded`) as well as the reads it served.
2. A test using injection must assert **both counts are non-zero** before
   trusting its result. `malformed_run()` in `test_pcie_enum_bar.py` does this
   for every caller.
3. Never poke private state from a test. If a behaviour is worth injecting, it
   is worth a named model feature.

---

## 5. ⭐ The observation contract

**"A green diff, an empty finding list, and a passing assertion over an empty
set are the same bug."** This fired on the 2b-3 recon itself, on the mutation
harness, and on three tests.

**Requirements for anything that iterates a collected list:**

1. Prove the list is **non-empty** before asserting over it.
2. Prove a whole-sequence comparison's **golden** is non-empty too — a golden
   that is itself empty makes the comparison meaningless in the other direction.
3. Compare **lengths as well as elements**; zipping two lists of different
   lengths silently ignores the tail.
4. ⭐ **Guard the guards.** The empty-set guards SURVIVED being defeated by
   mutation, because a guard only fires on a broken run and a green suite has
   none. The mutation that did break things killed every test by hanging the DUT
   and never reached the guard. **A bench guard needs a self-test that calls it
   with the input it exists to reject.**

---

## 6. ⭐ What the model must let the RC observe, and at what granularity

Two distinct error surfaces describe one bad packet, and a model must not
conflate them:

| surface | granularity | source |
|---|---|---|
| `rc_unexpected_completion_o` | **once per packet** | no allocated tag matches — `tlp_request_tracker.sv:316` |
| `rc_protocol_error_o` = orphan data | **once per Dword** | `pcie_rc_if.sv:403-405` |

A four-Dword orphan burst produces **one** unexpected-completion report and
**four** orphan reports. Both counts are asserted exactly; an inequality would
pass against a report that fired once or a hundred times.

⚠️ This was predicted wrong once: the prediction named the per-Dword count and
then demanded silence everywhere else, and duly failed on a correct stack.

**Silence requirement.** `Mon.clean()` asserts that every error surface the
prediction did not name stayed quiet — `credit_error_o` and uncorrelated
`rc_protocol_error_o` included. A test that expects a surface to fire must say
so by name (`allow_timeouts`, `allow_orphans`, `allow_unexpected`), never by
loosening the check.

---

## 7. Flow control, for integration models

1. **Nothing is emitted and no error is reported** until `link_up_i`,
   `transmit_enable_i`, `fc_initialized_i` and one `fc_update_valid_i` pulse
   with non-zero credits are all present (regression RC1).
2. ⛔ **Zero means INFINITE at FC init** ([BASE] §2.6.1 p.138, fn 33 p.137). You
   cannot starve a pool by advertising 0 — you make it unlimited, and the test
   is a vacuous pass. Starvation needs a **small finite** advertisement with no
   replenishment.
3. ⛔ **A replenishing drip must advertise a CUMULATIVE INCREASING total.**
   `fc_*_i` is the raw `CREDITS_ALLOCATED` off the wire ([BASE] §2.6.1.2 p.141)
   with no arithmetic on the path, so a drip re-pulsing a constant says "I have
   still only ever allocated N" and blocks the transmitter forever — a deadlock
   indistinguishable from the DUT bug it would be hiding.
4. **The spec minimum an Endpoint may advertise** is NPH=1, NPD=1, with CPLH and
   CPLD **infinite** ([BASE] Table 2-37 p.137-138). That is derived, not chosen,
   and is the vector `e2` runs.
5. A credit test must prove the drip was **load-bearing**: `tx_fc_blocked_o` must
   actually have asserted, or the test is a duplicate of the saturated run.

---

## 8. Ordering invariants a socket model must check on itself

For standalone targets, where the Python bench plays `pcie_rq_rc_top`'s socket.
2b-1 lost two bring-up runs to a model that was too **aggressive**, not too
polite.

1. A completion may not be delivered for a transaction whose **tag has not been
   strobed**.
2. A **timeout strobe** may not fire for an allocated tag that has not been
   strobed.
3. The tag strobe follows command accept by **≥ 1 cycle** — the core allocates in
   `REQ_TAG` a cycle or more later (`tlp_requester.sv:211`).

A violated invariant raises `AssertionError`, failing the one test that tripped
it. **Never `$error`/`$stop` equivalents** — those would abort the shared
multi-test process.

### 8.1 ⭐ A zero-latency model is blind to ordering, not merely fast

The socket answers in a handful of cycles; the real stack takes hundreds. A
mutation asserting `enum_done_o` before the final write's completion returned
was **invisible to all 29 standalone tests** and caught incidentally by four
integration tests, purely because the real round trip leaves an observable gap.

**A standalone target is not a substitute for an integration one on anything
ordering-shaped.** Where the standalone target must cover such a property, it
needs a test that makes the outcome *matter* — failing the transaction, or
withholding its completion — rather than one that waits for a terminal state and
snapshots.

---

## 9. What is deliberately NOT specified here

- **Tag values.** No assertion anywhere may depend on one. The tracker recycles
  a tag as soon as a completion carrying Request Completed retires it (PG213
  `:4257`); incrementing tags are a property of the socket model, not the design.
- **`settle()`.** It stays local per bench: it is not an early-exit loop, so its
  default *is* simulation time, and sharing it under one default would move
  pinned sim end times.
- **The completer's internal structure.** Only the four names and the behaviour
  above are contractual.

---

## 10. Where the implementations live

| model | file | target |
|---|---|---|
| `Socket` (plays `pcie_rq_rc_top` for standalone) | `tb/rc/enum_tb_common.py` | `verilate_enum_txn`, `_scan`, `_bar` |
| `ConfigDevice` + `BarSpec` (configuration space, BAR semantics) | `tb/rc/enum_tb_common.py` | `verilate_enum_bar`, `_bar_tlp` |
| `ConfigCompleter` | `tb/rc/test_pcie_enum_txn_tlp.py` | `verilate_enum_txn_tlp` |
| `ConfigSpaceCompleter` | `tb/rc/test_pcie_enum_scan_tlp.py` | `verilate_enum_scan_tlp` |
| `BarSpaceCompleter` | `tb/rc/test_pcie_enum_bar_tlp.py` | `verilate_enum_bar_tlp` |
| `Mon` (error-surface silence gate) | `tb/rc/enum_tb_common.py` | every `_tlp` target |
| guards (`nonempty`, `expect_count`, `assert_sequence`) | `tb/rc/enum_tb_common.py` | all |

**Entry point for a replacement model:** implement §1's four names, satisfy §2–§4,
and run `verilate_enum_bar_tlp`. If E1 still passes with all seventeen on-wire
Dwords matching, the model is enumerable.
