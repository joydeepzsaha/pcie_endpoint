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

> **This table is the Type 0 header, and only the Type 0 header.** Figure 7-5 is
> the Type **00h** layout; a Function whose Header Type layout field reads `01h`
> serves a different map, with two BARs instead of six and the bus numbers where
> BAR2 would sit. **See §11.** Nothing else in §2–§9 is type-specific.

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
| `BridgeConfigSpace` (Type 1 configuration space, §11) | `tb/rc/enum_tb_common.py:1326` | `verilate_enum_bridge_tlp` |
| `BridgedTopology` (the §7.3.3 routing/transform core, §12) | `tb/rc/enum_tb_common.py:1405` | `verilate_enum_bridge_tlp` |
| `BridgedCompleter` (the four names over a `BridgedTopology`) | `tb/rc/enum_tb_common.py:1538` | `verilate_enum_bridge_tlp` |

**Entry point for a replacement model:** implement §1's four names, satisfy §2–§4,
and run `verilate_enum_bar_tlp`. If E1 still passes with all seventeen on-wire
Dwords matching, the model is enumerable.

---
---

# Stage D addendum — Type 1, bridges, and CFG1 origination

**Added 2026-08-01, at `2de9afe`** (Stage D closed). §0–§10 above are unchanged
except for the §2.1 pointer and the three additive §10 rows.

Everything in §0–§10 is still correct, and everything outside §2.1 is
type-agnostic. But §2.1's register table is Base 2.1 Figure 7-5 — the **Type 0**
header — and nothing above covers the Type 1 header, bridge forwarding, or the
rule that decides which of CfgRd0/CfgRd1 goes on the wire. All three landed in
Stage D, and the Stage E tree walk depends on all three.

These sections continue the existing numbering rather than nesting under one
"Stage D" head, because the document is organised **by topic** — configuration
space, BARs, injection, observation, error surfaces, flow control, ordering — and
a stage-shaped block would be the only stage-shaped thing in it. §11 extends §2,
§12 extends §4.1, §14 extends §8.1, §15 extends §5, §17 extends §10.

**Citation tags** are those of `SPEC_PREDICTIONS_STAGE_D.md` §0.1: `[BASE]` =
PCI Express Base 2.1, `[PCI30]` = PCI Local Bus 3.0. Both are golden. MindShare
is **never** golden and is cited nowhere below.

---

## 11. Type 1 configuration space — what a bridge model must serve

### 11.1 ⚠️ The normative source, and the one that does not work

**`[PCI30]` is not a source for the Type 01h header layout.** §6.1 **p.214**:

> "Currently three Header Types are defined, 00h which has the layout shown in
> Figure 6-1, **01h which is defined for PCI-to-PCI bridges and is documented in
> the PCI to PCI Bridge Architecture Specification**, and 02h which is defined
> for CardBus bridges…"

That specification is **not on the shelf**. Figure 6-1 is the Type 00h layout and
shows Base Address Registers at 18h — which is exactly the wrong answer for a
bridge, and a plausible-looking one.

**The map of record is `[BASE]` §7.5.3 Figure 7-6 p.492**, "Type 1 Configuration
Space Header", whose own scope note (§7.5.3 p.492) says: *"Register
interpretations described in this section apply to PCI-PCI Bridge structures
representing Switch and Root Ports"* — this project's topology exactly.

**Do not re-derive this.** Opening `[PCI30]`, finding the deferral, and reaching
for a practitioner text instead cost a session once. The substitution is settled.

### 11.2 The register map

`[BASE]` §7.5.3 Figure 7-6 p.492. Register number *N* is byte offset `4N`.

| reg | offset | content |
|---|---|---|
| 0 | `00h` | `{Device ID, Vendor ID}` |
| 1 | `04h` | `{Status, Command}` |
| 2 | `08h` | `{Class Code, Revision ID}` |
| 3 | `0Ch` | `{BIST, Header Type, Primary Latency Timer, Cache Line Size}` |
| **4–5** | `10h`–`14h` | **Base Address registers 0–1 — and there is no BAR 2–5 (§11.6)** |
| **6** | `18h` | **`{Secondary Latency Timer, Subordinate, Secondary, Primary}` (§11.3)** |
| 7 | `1Ch` | `{Secondary Status, I/O Limit, I/O Base}` |
| 8 | `20h` | `{Memory Limit, Memory Base}` |
| 9 | `24h` | `{Prefetchable Memory Limit, Prefetchable Memory Base}` |
| 10 | `28h` | Prefetchable Base Upper 32 Bits |
| 11 | `2Ch` | Prefetchable Limit Upper 32 Bits |
| 12 | `30h` | `{I/O Limit Upper 16 Bits, I/O Base Upper 16 Bits}` |
| 13 | `34h` | `{Reserved, Capability Pointer}` |
| 14 | `38h` | Expansion ROM Base Address |
| 15 | `3Ch` | `{Bridge Control, Interrupt Pin, Interrupt Line}` |

**Sixteen Dwords, derived by transcribing Figure 7-6's byte-offset column
`00h`…`3Ch` in steps of 4.** Registers 0–3 are the §7.5.1 "Type 0/1 **Common**
Configuration Space" block (`[BASE]` §7.5.1 p.484: *"These registers are defined
for both Type 0 and Type 1 Configuration Space headers"*), so the Command
register at `04h` needs no Type-1-specific handling — commonality is the spec's
own organisation, not our assumption.

**A model need not serve all sixteen.** The bench model serves **six** —
registers 0, 1, 3, 4, 5, 6 (`enum_tb_common.py:1351-1355`, `:1350`, `:1370`) —
and answers **UR** for the other ten, per §4.1's default arm. That is a
deliberate scope boundary, not an omission: registers 7–15 are the memory/IO
base-limit windows and Bridge Control, which nothing in this design programs.
Count derived by evaluating `BridgeConfigSpace.read(reg)` for `reg` in 0…15 and
partitioning on `is None`: `{0,1,3,4,5,6}` served, `{2,7,…,15}` UR.

### 11.3 Offset 18h — the one Dword that makes routing work

`[BASE]` Figure 7-6 p.492:

| bits | field | width |
|---|---|---|
| `[31:24]` | Secondary Latency Timer | 8 |
| `[23:16]` | Subordinate Bus Number | 8 |
| `[15:8]` | Secondary Bus Number | 8 |
| `[7:0]` | Primary Bus Number | 8 |

All four fields live in **one Dword with no reserved bits**, so the whole-Dword
config write of §2.2 covers it exactly — `first_be = 1111b`, no read-modify-write,
no new byte-enable behaviour. The RTL emits precisely that:

```
pcie_enum_bus.sv:260   cmd_first_be_o = CFG_BE_DWORD            // 4'b1111
pcie_enum_bus.sv:261-262
      cmd_wdata_o = {SEC_LATENCY_TIMER_WDATA, SUB_BUS_NUMBER,
                     SEC_BUS_NUMBER, bridge_bus_i}
```

with `CFG_REG_BUS_NUMBER = 6'h06` (`pcie_enum_pkg.sv:324`, = byte offset `18h`),
`SEC_LATENCY_TIMER_WDATA = 8'h00` (`:340`), `SEC_BUS_NUMBER = 8'h05` (`:333`),
`SUB_BUS_NUMBER = 8'h09` (`:334`), `CFG_BE_DWORD = 4'b1111` (`:87`). With
`bridge_bus_i = 01h` the emitted Dword is **`0x00090501`**, which is the bench
golden `BUS_NUM_WDATA` (`enum_tb_common.py:1317`) — the same number derived
independently on both sides.

### 11.4 ⛔ Secondary Latency Timer is read-only, hardwired `00h`

`[BASE]` §7.5.3.3 **p.493**, in full: *"This register does not apply to PCI
Express. It must be read-only and hardwired to 00h."*

The whole-Dword write at 18h **necessarily drives `[31:24]`**. A model that
accepted that byte, stored it, and returned it on read-back would let a golden
asserting a non-zero Secondary Latency Timer pass — and that golden asserts a
**spec violation**. The failure is silent and in the model, which is §0's whole
subject.

**Requirements:**
1. `[31:24]` reads `00h` **regardless of what was written**. The bench masks on
   the *read* path too (`enum_tb_common.py:1374`), so even a model bug that
   stored the byte could not present it.
2. The ignore arm is **counted** (`latency_byte_writes_ignored`,
   `enum_tb_common.py:1387`) and the acceptance test asserts it fired
   (`test_pcie_enum_bridge_tlp.py:378-379`) — §3.3's present-*and*-proved-live
   rule, applied to a second arm.
3. On the **originating** side, `00h` is the only defensible value to write into
   that byte — any other asserts a read-back the spec forbids. The RTL writes
   `00h` (`SEC_LATENCY_TIMER_WDATA`, `pcie_enum_pkg.sv:340`, placed at
   `pcie_enum_bus.sv:261`).

### 11.5 Primary Bus Number is read-write, and routes nothing

`[BASE]` §7.5.3.2 **p.493**: *"Except as noted, this register is not used by PCI
Express Functions but must be implemented as read-write for compatibility with
legacy software."*

So a model must **accept and return** it — but **no routing decision may read
it.** Consequence for test authors: an assertion that varies only Primary Bus
Number and claims to prove routing is vacuous *even with distinct values*,
because the spec says nothing reads it. Route-proving assertions must vary
**Secondary** (§12.1). The same subsection carries the cross-reference to the
Bus/Device Number **capture** rule (*"PCI Express Functions capture the Bus (and
Device) Number as described in Section 2.2.6"*) — which is how a Function
actually learns its bus number, and is §15.1's subject.

### 11.6 ⛔ A Type 1 header has TWO BARs, not six

`[BASE]` **§7.5.3.1 "Base Address Registers (Offset 10h/14h)" p.493** names two
offsets. `[BASE]` **§7.5.2.1 "Base Address Registers (Offset 10h - 24h)"** — the
Type 0 subsection — names six. Figure 7-6 p.492 settles it structurally:
**`18h` holds the bus numbers**, exactly where Type 0's BAR2 would sit.

**Derivation of "two":** `(14h − 10h)/4 + 1 = 2`, and Figure 7-6 labels only
`10h` "Base Address Register 0" and `14h` "Base Address Register 1". Against Type
0's `(24h − 10h)/4 + 1 = 6`. The bench encodes the same two
(`enum_tb_common.py:1350`, `self._bars = (4, 5)`), as does the RTL comment block
at `pcie_enum_pkg.sv:320-324`.

**State the consequence plainly: a six-BAR sweep at a bridge destroys the bus
assignment silently.** §3's all-ones sizing write, pointed at register 6, writes
`FFFFFFFF` over `{Subordinate, Secondary, Primary}` — and the corruption lands
*after* the routing it breaks was established, so every probe that preceded it
still passed. Registers 7, 8 and 9 then take Secondary Status, IO Base/Limit and
Memory Base/Limit instead of BARs 3–5.

**Requirement: a BAR stage must never be pointed at a Type 1 Function.** The
acceptance test asserts this as a **negative on the wire** over the whole run
(`test_pcie_enum_bridge_tlp.py:332-361`): no all-ones Type 0 write to register 6
ever appears, the only Type 0 write to register 6 carries `BUS_NUM_WDATA`, and
the bridge's own registers 4–5 are never touched. Negatives, because the
positive — "the device's registers 4–9 were sized" — is true in the same run and
would mask it; the two are distinguished by the *type and bus* of the TLP, not by
the register number.

---

## 12. Bridge behaviour — the arms a model must implement

### 12.1 The three arms, applied in sequence

`[BASE]` §7.3.3 **p.481**, for Root Ports, Switches and PCI Express-PCI Bridges,
on a Type 1 Configuration Request:

| # | condition | the model must | on the wire |
|---|---|---|---|
| 1 | bus == the Downstream Port's own bus (Secondary) | *"Transform the Request to Type 0 by changing the value in the Type[4:0] field of the Request (see Table 2-3) — **all other fields of the Request remain unchanged**"*, then forward to that Port | forwarded DW0 differs from received DW0 in **bit 0 only**; DW1, DW2 and payload byte-identical |
| 2 | Secondary < bus ≤ Subordinate | *"Forward the Request to that Downstream Port interface without modification"* | all Dwords byte-identical |
| 3 | otherwise | *"The Request is invalid – follow the rules for handling Unsupported Requests"* | UR completion |

The aperture that defines "in the range" is `[BASE]` §6.12.1.1 **p.435**: *"the
inclusive range specified by the Secondary Bus Number register and the
Subordinate Bus Number register."*

**Three arms, derived by counting the bullets under §7.3.3's "If Configuration
Request Type is 1, apply the following tests, in sequence" on p.481.** A Type 0
request is a fourth, separate case at p.480: the bridge is the link partner, so
it consumes the request into its own configuration space.

**Arm 1 must assert its own postcondition.** The bench does not merely flip the
bit; it checks that nothing else moved (`enum_tb_common.py:1477-1481`). This is
bench code that behaves like hardware, and §0 applies to it.

**⚠️ Arm 2 is unreachable at one bridge level and must not be faked.** With one
level there is exactly one populated bus behind the bridge, so no bus number
satisfies `Secondary < bus ≤ Subordinate` with a device there. Implement it;
do **not** claim it as covered. The acceptance test asserts it **never fired**
(`test_pcie_enum_bridge_tlp.py:376-377`) rather than pretending otherwise — a
test that "exercised" it by pointing at an empty bus would be asserting model
behaviour, not DUT behaviour.

### 12.2 An endpoint must UR any Type 1

`[BASE]` §7.3.3 **p.480**, the Endpoint rules, first bullet: *"If Configuration
Request Type is 1, • Follow the rules for handling Unsupported Requests."*

So the model of the device **behind** the bridge must UR any CFG1 that reaches
it — and in a correct run it should never see one, because arm 1 transformed it
first. That makes the arm a **free live cross-check that the transform actually
happened** (`enum_tb_common.py:1508-1510`; asserted to be zero in the acceptance
run at `test_pcie_enum_bridge_tlp.py:373-375`).

⛔ **"Ignore" is not "UR".** `[PCI30]` p.49 says *"All targets except
PCI-to-PCI bridges ignore Type 1 configuration transactions"* — legacy-PCI
language. On PCI Express a non-posted Request must always be completed. A model
written to "ignore" produces a **completion timeout** where the spec requires a
**UR completion** — and §12.3 turns on exactly that distinction: a wrongly-typed
request must *fail with UR*, not hang.

### 12.3 ⭐ These reject arms are load-bearing, not completeness theatre

§4.1's principle — *the default arm is UR, never silence, and the model counts
it* — carries forward with more force here, because at a bridge the reject arms
are what make **wrong-type** mutations self-detecting.

At reset a bridge has Secondary = Subordinate = `00h`, so a wrongly-typed CfgWr1
at 18h falls into **arm 3** and is answered UR — automatically, by a model
written to the spec rather than to the expected trace. Nothing bespoke has to be
asserted for the mutation to die.

**Measured, not argued.** `SPEC_PREDICTIONS_STAGE_D.md` §7.4 records the Stage D
integration mutation kill-set. Two of the four mutations died on the model's own
physics rather than on an assertion written for them:

- **M4.2** — the CFG1 probe's type-select arm wrong: the mistyped probe was
  claimed **locally** by the bridge, which answered its own Vendor/Device IDs and
  its own Type 1 header. Killed by the forced-apart identity assertions.
- **M4.3** — the BDF mux stuck on the primary scan's value: the CfgRd1 carried
  bus 1, which is outside `[5, 9]`, so **arm 3** UR'd it. Killed *only because
  buses 1/5/9 are forced apart*.

and a third, **F3.3**'s `cmd_type1_o` forced to 1, died in arm 3 at reset state
exactly as the paragraph above describes. Every one of these is the spec's own
arm doing the work.

> **Provenance.** The mutation *outcomes* are the measured column of
> `SPEC_PREDICTIONS_STAGE_D.md` §7.4 — they cannot be re-derived by reading, only
> by re-running the mutations. The *mechanism* each one died on is re-derivable
> and anchored above: `enum_tb_common.py:1453-1469` (the dispatch),
> `:1486-1504` (local claim), `:1303-1305` (the forced-apart bus numbers).

**Requirement.** Implement all three arms and the endpoint rule **literally**,
count each (`enum_tb_common.py:1444-1448`), and let tests assert the counts —
including the ones that must be **zero**. A model that answered "close enough"
for an out-of-range bus would make DUT and model wrong together, which no
assertion catches.

---

## 13. CFG0 vs CFG1 on the wire

### 13.1 Exactly one bit

`[BASE]` **Table 2-3 p.58**, "Fmt[1:0] and Type[4:0] Field Encodings":

| TLP Type | Fmt | Type | |
|---|---|---|---|
| CfgRd0 | `000` | `0 0100` | |
| CfgWr0 | `010` | `0 0100` | |
| CfgRd1 | `000` | `0 0101` | ← Type[0] |
| CfgWr1 | `010` | `0 0101` | ← Type[0] |

**Type[0] alone distinguishes them.** Fmt is unchanged between CFG0 and CFG1 for
the same direction; direction alone selects Fmt. And no other header field
differs: `[BASE]` §2.2.7 p.79 states the Configuration Request restrictions as a
single class with no Type 0/1 distinction, and Figure 2-18 p.80 gives **one**
header format for "Configuration Transactions".

### 13.2 The origination rule, and where it actually lives

**`[BASE]` does not state the originator's selection rule.** §7.3.3 addresses
Root Ports, Switches and Bridges as *receivers and forwarders*; its only remark
about origination is *"Configuration Requests are initiated only by the Host
Bridge"* (p.480), and its Root-Complex rule says bus-number assignment *"may be
done in an implementation specific way"* (p.481).

**The normative home is `[PCI30]` §3.2.2.3.x p.49:**

> "A Type 0 configuration transaction is not propagated beyond the local PCI bus
> and must be claimed by a local device or terminated with Master-Abort. **If the
> target of a configuration transaction resides on another bus (not the local
> bus), a Type 1 configuration transaction must be used.**"

Restated for this topology: **emit Type 0 when the target bus equals the bus
directly behind the port; emit Type 1 for any bus beyond it.**

⚠️ **The familiar bus-number comparison is not the citation of record.**
`[PCI30]` p.52 gives the match/range test (equal to Bus Number register → Type 0;
greater and ≤ Subordinate → Type 1), but that passage sits **inside an
`IMPLEMENTATION NOTE`** headed "Bus Number Registers and Peer Host Bridges". It
is corroboration. Any assertion needing a "must" cites p.49; p.52 may be cited
only as *"consistent with."*

**The non-obvious consequence, and it is a trap:** the bus-number write **to the
bridge** is Type **0**, because the bridge sits on the local bus. The name
"bridge phase" invites the opposite assumption. The RTL states it explicitly at
`pcie_enum_bus.sv:257` (`cmd_type1_o = 1'b0`), and §12.3 is what makes the
opposite self-detecting.

### 13.3 ⛔ Extend the golden builders BEFORE writing tests of the new encoding

Because exactly one bit differs, an on-wire assertion that omits `dw0[4:0]` —
or that compares DW1/DW2/payload only — **passes identically for CfgRd0 and
CfgRd1**. Most of the natural things to assert about a config request are in that
blind set.

**The failure mode is worse than vacuity.** A golden builder that hardcodes the
Type 0 encoding makes a CFG1 test assert the **wrong** golden — so the test goes
green against a DUT emitting the wrong type. Not merely "not testing this
increment": actively certifying the bug.

**Requirements:**
1. Extend the builders with a **default-false** type selector *before* writing
   any test of the new encoding, so every pre-existing caller stays
   byte-identical and a Type 1 golden is expressible at all. Done at
   `enum_tb_common.py:356` (`cfg_wire_dw0(..., type1=False)`), `:202`
   (`assert_rq_descriptor(..., type1=False)`) and `:943`
   (`assert_cfg_tlp_on_wire(..., type1=False, bus=None)`).
2. For every assertion, apply the test: *would this still pass if the DUT emitted
   the other type?* If yes, it is not testing this.
3. **At least one assertion per increment compares the whole DW0**, not a field
   subset.
4. **The builders self-test the one-bit distance at import time**
   (`enum_tb_common.py:376`, called at `:400`): descriptor pairs must differ by
   exactly `1 << 75`, wire pairs by exactly bit 0. A distance that silently grew
   to two bits would mean one of the two goldens had drifted, and the
   "actively wrong" failure above would be back.

---

## 14. What a bridge-capable model must not simplify away

### 14.1 ⭐ Equal latencies are nearly as blind as zero

§8.1 argues that a zero-latency model is blind to ordering, not merely fast. At a
bridge that argument gets stronger and gains a second edge.

**When the headline claim is an ordering claim, equal latencies are nearly as
blind as zero.** Stage D's central claim *is* an ordering claim — the bus-number
write precedes the first CFG1 probe. Two completers answering in the same number
of cycles put every response at a predictable offset from its request, so a
wrongly-ordered implementation produces a trace that still looks regular; there
is no window in which the out-of-order request is observable *as such*.

**Requirements:**
1. The bridge model and the device model take **non-zero, unequal** response
   latencies (`enum_tb_common.py:1322-1323`: 5 and 9 cycles), and anything the
   device answers is charged the bridge's forwarding hop as well
   (`:1530-1535`, so 5 vs 14 on the wire).
2. The acceptance test asserts the order of **observed TLPs on the wire**, not
   the order of model callbacks (`test_pcie_enum_bridge_tlp.py:313-321`).
3. At least one variant stalls the bus-number write's completion long enough
   that a wrongly-ordered implementation would already have emitted the probe.
   That is the run which actually discriminates — the happy path does not.

### 14.2 Import-time self-tests on the model itself

§5's requirement 4 — *guard the guards* — applies to the routing core, and more
sharply: the core's arms include ones that only fire on **broken** runs (arm 3's
UR, the endpoint's Type 1 UR, the device-number UR), so a green suite never
exercises them. A guard never seen firing is not known to work.

**Requirement: keep the routing and policy in a *pure* core** — no simulator
dependency — **and drive its arms at import time, in every bench that imports
it.** `BridgedTopology` (`enum_tb_common.py:1405`) is pure for exactly this
reason, and `_selftest_bridged_topology()` (`:1626`, called at `:1719`) drives,
before any DUT exists:

- a wrongly-typed CfgWr1 at 18h against a reset-state bridge → UR, and the
  register verified **untouched**;
- a raw Type 1 reaching the device → UR (§12.2);
- post-assignment, bus == Secondary → the one-bit transform, with
  received-vs-forwarded compared Dword by Dword;
- the §11.4 latency-byte ignore, and the §15.1 capture sequence at both
  Functions;
- that the value table really is pairwise-distinct — §15.2's precondition,
  asserted rather than assumed.

---

## 15. Vacuity boundaries specific to Type 1

§5's observation contract says a passing assertion over an empty set is a bug.
Type 1 adds two boundaries where the set is not empty but the **discriminator**
is degenerate — which no non-emptiness guard can catch.

### 15.1 ⛔ Completer ID is `0000h` through the entire probe phase

`[BASE]` **§2.2.9 "Completion Rules" p.99**:

> "Functions must capture the Bus and Device Numbers supplied with all Type 0
> Configuration Write Requests completed by the Function, and supply these
> numbers in the Bus and Device Number fields of the Completer ID for all
> Completions generated by the Device/Function.
> • **If a Function must generate a Completion prior to the initial device
> Configuration Write Request, 0's must be entered into the Bus Number and
> Device Number fields**"

Applied to a one-bridge enumeration: the bridge's identity probes precede its own
first configuration write; the device's identity probes precede *its* first
write, and the bridge's write does not count for the device. So the Completer ID
is `0000h` **at both Functions simultaneously, throughout the probe phase**, and
`0000h` on the capturing write's **own** completion — capture happens after that
completion is built (`enum_tb_common.py:1498-1500`, `:1522-1524`).

**Consequence, and it cannot be repaired with constants.** A probe-phase routing
assertion built on the Completer ID answers *yes* to §15.2's test — *would this
still pass with all bus numbers equal?* — **by construction**, not by an unlucky
choice of values. No amount of forcing constants apart fixes it.

**Requirements:**
1. The model **captures** the ID; it is not configured with it. Both Functions
   start at `0000h` (`enum_tb_common.py:1438-1439`).
2. A golden asserting a non-zero Completer ID for any probe-phase completion is
   asserting a **spec violation** and must not be written.
3. **Routing is proven from the request side** — the emitted `dw0[4:0]` and the
   DW2 bus field (§13.3) — never from a completion's Completer ID.

⚠️ **Do not inherit the Stage C pattern here.** `test_pcie_enum_bar_tlp.py:193`
builds every completion with the target BDF, including the first Vendor-ID read.
That is bench infidelity, not an RTL defect — nothing in `src/rc/` or the TL
consumes a completion's Completer ID today — but a Stage D model extended from
that pattern inherits it, and §15.1 is exactly the rule that makes it matter.
The Stage D completer's `.complete()` therefore defaults `completer_id=0`
(`enum_tb_common.py:1565`), which is the spec-correct pre-capture value.

### 15.2 ⛔ The bus field is the only discriminator a routing assertion has

Working out which BDF fields **can** legally differ between the bridge and the
device behind it:

- **Device** — `[BASE]` §7.3.1 p.479 requires a Downstream Port without ARI
  Forwarding to *"associate only Device 0 with the device attached to the Logical
  Bus"*, and to terminate Device Numbers 1–31 with UR. The secondary link is
  point-to-point, so the same reasoning applies below the bridge as above it:
  **Device is 0 on both sides by construction.**
- **Function** — single-function on both sides; functions 1–7 are never read, of
  a bridge or anything else. **Function is 0 on both sides by construction.**
- **Bus** — free.

**So exactly one of the three fields can differ, and every routing assertion
rests on it alone.** This is not a weakening of the force-values-apart rule; it
is the honest answer to its own question, and it is *why* the bus numbers have to
be forced apart so carefully.

**Requirements for a model author:**
1. Bus numbers **pairwise distinct and non-consecutive** — the bench uses
   primary `01h`, Secondary `05h`, Subordinate `09h`
   (`enum_tb_common.py:1303-1305`; `pcie_enum_pkg.sv:333-334`). Secondary is not
   primary + 1, so "off by one from the parent" is distinguishable from correct;
   Subordinate ≠ Secondary, so an implementation writing the same value into both
   fields is caught by the whole-Dword golden. Every byte of the 18h Dword is a
   different value: `00h / 09h / 05h / 01h`.
2. Vendor and Device IDs **pairwise distinct** across bridge, device and the
   pre-existing Stage C goldens, and none `FFFFh` (§2.1). The bench uses
   `1AF4h`/`1100h` and `15B3h`/`1017h` (`enum_tb_common.py:1307-1310`).
3. Any assertion whose discriminating power rests on Device or Function differing
   is **vacuous by construction**. Check each one against this.
4. Routing assertions must vary **Secondary**, never Primary (§11.5).

---

## 16. Open questions — recorded as OPEN, not resolved

Neither has a normative anchor either way. They are recorded so a later increment
re-examines them rather than inheriting a phrasing.

### 16.1 Does `00h` in a Secondary Bus Number register at reset mean "unassigned", or "bus 0"?

§12.1's arm 1 asks whether the target bus is equal to the bus assigned to a
Downstream Port — and at reset that register **holds `00h`**. Read literally, a
Type 1 request targeting bus `00h` would therefore *match* and be transformed,
not answered UR.

The case is unreachable in this design — bus 0 is the local bus, so §13.2's rule
originates **Type 0** for it and never Type 1 — so "at reset every Type 1 request
is answered UR" is safe here. But the more general claim one would want, that
`00h` means "unassigned" rather than "bus 0", is **not anchored**: not in
`[BASE]` §7.3.3 p.481, not in §6.12.1.1 p.435, not in `[PCI30]` §3.2.2.3.x p.49.

**OPEN.** Precise only for target bus ≠ `00h`. A later increment that widens the
topology must re-examine it.

### 16.2 May a bridge itself CRS a Type 1 request it cannot forward?

§12.1 gives a bridge three outcomes for a Type 1 request — transform-and-forward,
forward-unmodified, or UR — and CRS is not among them. That argument is sound
about the **forwarding** path. It is an argument **from silence** about the
bridge acting as a Completer in its own right when it cannot forward at all (for
instance, secondary link not up): `[BASE]` §2.3.1 p.113 makes CRS legal *"in
response to a Configuration Request"* without restricting which Function may
issue it.

**OPEN.**

**What the bench model does regardless — and this is a bench choice, not a
resolution.** It URs, per §12.1 arm 3, and never synthesises CRS on behalf of the
device: the CRS hooks are per-Function, and a forwarded request can only be CRS'd
by the Function it was forwarded to (`enum_tb_common.py:1429-1430`, `:1490-1493`,
`:1514-1517`). It is the conservative reading and it makes the model
deterministic. If a Stage E bench ever needs a bridge that stalls, this is the
question that must be answered properly.

---

## 17. The Stage D acceptance gate

§10's entry point covers a Type 0 endpoint model. A **bridge-capable** model has
an equivalent gate.

**Target: `verilate_enum_bridge_tlp`** (`tb/rc/tb_rc.core:366`), five tests
**B1–B5** (`test_pcie_enum_bridge_tlp.py:389, 434, 466, 510, 565`). The
acceptance test is **B1**.

**B1 emits twenty Configuration TLPs — 3 Type 0, then 17 Type 1 — asserted in
order, payload Dwords included.** Derived by counting the rows of
`BRIDGED_GOLDEN_SEQUENCE` (`test_pcie_enum_bridge_tlp.py:78-99`) and partitioning
on its `type1` column: 20 rows total, 3 with `type1 == 0`, 17 with `type1 == 1`.
The shape is: two Type 0 identity/header probes of the bridge → the Type 0
bus-number write at 18h → two Type 1 probes of the device on the secondary bus →
fourteen Type 1 BAR sizing/assignment TLPs → one Type 1 Command-register write,
structurally last. B5's `DIRECT_GOLDEN_SEQUENCE` (`:103-121`) is **seventeen**
rows, all Type 0 — same derivation.

**In that run the model performs seventeen transforms**, one per Type 1 request:
every CFG1 in the sequence carries bus `05h`, which equals Secondary once the 18h
write has landed, so all seventeen take §12.1's arm 1. Derived by replaying
`BRIDGED_GOLDEN_SEQUENCE` through `BridgedTopology.handle()` and reading
`len(topo.transforms)`; the same run leaves `route_ur_hits`,
`forward_unmodified_hits` and `device_type1_ur_hits` all **zero**, and
`latency_byte_writes_ignored` at **one**.

> ⚠️ **This corrects a recorded count.** `SPEC_PREDICTIONS_STAGE_D.md` §7.4's F3.1
> measured column says *"16 transforms"* alongside the correct *"twenty"* TLPs.
> Those two cannot both hold: 20 emitted TLPs minus 3 Type 0 leaves 17 Type 1, and
> every one is transformed. **17 is the derived value.** The acceptance test's own
> guard is `>=` (`test_pcie_enum_bridge_tlp.py:367-370`, computing the expected
> count from the golden rather than hardcoding it), so the discrepancy is in the
> prose only and no test verdict moves.

**Entry point for a bridge-capable replacement model:** implement §1's four names
— unchanged; Stage D needed no fifth — satisfy §11–§15, and run
`verilate_enum_bridge_tlp`. If **B1 passes with all twenty emitted TLPs matching
in order**, and B5 (the direct-attach regression, seventeen Type 0 TLPs, run with
the bridge path enabled) still passes, the model is bridge-enumerable.

> **§1 is intact.** `BridgedCompleter` presents `.start` / `.seen` / `.wait_for` /
> `.complete` and nothing else contractual (`enum_tb_common.py:1548`, `:1553`,
> `:1556`, `:1565`). The only difference from the three Stage C completers is
> inside `.complete`'s optional keywords, which §1 leaves as `…`: it takes
> `completer_id=0` where they take `byte_count=None`. §9 already places a
> completer's internal structure outside the contract. **No fifth name was
> needed, and none was added.**

> **Note on units.** §10 says E1 matches "all seventeen on-wire **Dwords**". The
> count is right and the unit is not: `GOLDEN_SEQUENCE` in
> `test_pcie_enum_bar_tlp.py:92-114` has seventeen rows, each one a **TLP** of
> three or four Dwords — as that file's own docstring says at `:9`, *"every one
> of the seventeen emitted TLPs."* §10's number needs no correction; read it as
> TLPs. Recorded here rather than edited in place, because §10's numbering is
> cited elsewhere.

**Five model behaviours the gate will not let you skip**, each of which a
too-polite model would silently satisfy:

| behaviour | §11–§15 | what breaks if simplified |
|---|---|---|
| `[31:24]` of 18h reads `00h` regardless of writes | §11.4 | a spec-violating golden passes |
| two BARs, never six, at a Type 1 Function | §11.6 | the bus assignment is destroyed *after* the probes that proved it |
| arm 3 URs an out-of-aperture Type 1 | §12.1, §12.3 | wrong-type mutations stop being self-detecting |
| the device URs any raw Type 1 | §12.2 | a failure to transform becomes invisible |
| unequal, non-zero latencies | §14.1 | the ordering claim the stage exists to prove goes unobservable |
