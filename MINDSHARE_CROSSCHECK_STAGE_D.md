# Stage D — MindShare cross-check of the spec predictions

**Written 2026-07-31, at `8c4e3f9`** (= `f49d73d` + D-0 recon + D-P predictions), on
`kourosh/dev`. Doc-only.

**Purpose.** `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` was written spec-first and committed before
this pass — deliberately, so that a practitioner text could not shape which spec
passages got read. This document is the *"what did I miss"* pass: every claim, ordering
rule, corner case or worked-example behaviour in the relevant MindShare chapters that
the predictions document does **not** already cover, or that it appears to contradict.

---

## §0. Source and standing rule

**Book:** Mike Jackson, Ravi Budruk, Joseph Winkles, Don Anderson —
*PCI Express Technology 3.0*, MindShare Press (2012).

**Exact path of the copy read:**

```
/home/kourosh/openPCIE/0.doc/Mike Jackson, Ravi Budruk, Joseph Winkles, Don Anderson - PCI Express Technology 3.0-MindShare Press (2012)-3.pdf
```

50,576,991 bytes. Text layer present and clean; extracted with `pdftotext -layout` into
the session scratchpad (53,526 lines) and read by chapter, never whole. An older,
partial copy (`PCIE-Technology3-0---MindSharePress2012.pdf`) also sits in that
directory and is *not* what was read.

**Chapters read:** Chapter 3 *Configuration Overview* (pp. 85–119, in full for
pp. 98–116) and Chapter 4 *Address Space & Transaction Routing* (the *ID Routing*
section, pp. 155–158, and *Base Address Registers*, pp. 126–135).

### ⚠️ Standing rule, restated

**MindShare is background, never golden.** Nothing in this document becomes a constant,
a golden, or a cited anchor. `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` §0.1 already lists MindShare
under **Never golden**, and that is unchanged. Where an item below caused a prediction
edit, the edit carries the **normative** anchor (`[BASE]` / `[PCI30]`) that this pass
chased the claim back to — the MindShare page is recorded here only, as the thing that
prompted the look.

The tag `[MS]` is used below for MindShare page references. **`[MS]` is not a citation
of record and must never appear in `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` or in a test.**

**The title's "3.0" means PCIe Gen 3, not the PCI 3.0 spec.** These have been confused
before in this project. `[MS]` and `[PCI30]` are unrelated documents.

### Disposition counts

| disposition | count |
|---|---:|
| **Resolved-confirmed** | 9 |
| **Resolved-rejected** | 10 |
| **Unresolved** | 2 |
| **total items** | **21** |

**Prediction edits caused: 4** — items **C6, C7, C8, C9**. All four are additions with
normative anchors; superseded text is marked and dated, not deleted.

**No item contradicted a committed prediction in a way that a normative re-read
supported.** The Part B stop-and-report trigger for a prediction bug did **not** fire.

---

## §1. Resolved-confirmed

Chased back to a normative anchor that the predictions can cite (or already cite).

### C1 — The originator emits Type 1 when the target bus is not the bus directly downstream

`[MS]` p.102, the worked CF8h/CFCh example, step 4: *"Since the target bus is not bus 0,
the Host/PCI bridge initiates a Type 1 Configuration read on bus 0."*

**Disposition: confirms §2.2, no addition needed.** The normative "must" is already
`[PCI30]` §3.2.2.3.x p.49 (predictions **P2.2**), and §2.2's restatement — *emit Type 0
when the target bus equals the bus directly behind the port; Type 1 for any bus beyond
it* — is exactly what this worked example does.

**Worth recording:** MindShare states the originator's rule *only* inside a worked
example, never as a cited rule — the same gap predictions **P2.1** found in `[BASE]`.
Two independent texts declining to state it normatively is corroboration that P2.1's
finding is real and not a search failure.

### C2 — ⚠️ The bus-number write to the bridge is Type 0 — MindShare's walkthrough agrees

This was the brief's headline question for Part B.

`[MS]` pp.109–110, *Single Root Enumeration Example*, steps 1–8. Bridge A sits on bus 0.
Step 4 writes bridge A's Primary/Secondary/Subordinate registers. Bus 0 is the bus
directly downstream of the Host/PCI bridge, so by C1 that write is a **Type 0**
configuration write. Step 8 then writes bridge C's registers — bridge C is on bus 1, so
*that* write is originated as Type 1 and transformed to Type 0 by bridge A.

**Disposition: directly corroborates §5.4 transaction #3 and §8.3 Trap C.** Predictions
§5.4 has *"Transaction 3 is Type **0** … the bus-number write targets the bridge itself,
not anything behind it"* and §8.3 names the opposite assumption as a trap. MindShare's
worked example writes the bridge over Type 0 and never over Type 1. **No addition.**

The general pattern in MindShare's walkthrough is: *a bridge's own bus-number registers
are always written at the Type-0-transformed level of the bridge itself* — i.e. the
request's target bus is the bridge's **Primary** bus, never its Secondary. That is the
same statement §5.4 makes for the single-level case.

### C3 — The bus-number write precedes the first probe of the bus behind the bridge

`[MS]` p.109, steps 4 → 5 → 6: write bridge A's bus numbers; *"Enumeration software must
perform a depth-first search. Before proceeding to discover additional Devices/Functions
on bus 0, it must proceed to search bus 1"*; then read the Vendor ID of Bus 1, Device 0,
Function 0.

**Disposition: corroborates §5.1's ordering prediction.** MindShare never probes a bus
before assigning the number that makes it reachable — the 00h window predictions §5.1
reasons about is one its walkthrough structurally avoids. **No addition.**

Note what MindShare does *not* provide: any statement about what happens if the probe
comes first. Predictions §5.1's UR-not-timeout claim rests on `[BASE]` §7.3.3 p.481, and
nothing here strengthens or weakens it. See **U1**.

### C4 — Header Type: low 7 bits are the layout code, bit 7 is multifunction

`[MS]` p.108 and Figure 3-12: *"the lower 7 bits of the Header Type register (offset 0Eh
in config space header) identify the basic category of the Function"* — `0` = not a
bridge, `1` = PCI-to-PCI bridge, `2` = CardBus — with bit 7 the single/multi-function
bit. Also *"the Header Type field (DW3, byte 2)"*.

**Disposition: confirms P4.5 in every particular** — offset 0Eh, byte 2 of the register-3
Dword, `HDR_LAYOUT_TYPE1 = 7'h01` as the only new constant, and the existing `[6:0]`
masking at `pcie_enum_scan.sv:303`. Anchor of record remains `[PCI30]` §6.1 p.214.
**No addition** (but see **C9** for a scope clarification P4.5 does need).

### C5 — CRS is legal only for configuration requests; the RC re-issues writes unconditionally

`[MS]` p.107: *"PCIe Functions must always give a Completion with a specific status when
they are temporarily unable to respond to a configuration access, which is the
Configuration Request Retry Status (CRS). This status is only legal in response to a
configuration request…"* and, for the CRS Software Visibility case: *"For configuration
writes or any other configuration reads, the Root must automatically re-issue the
Configuration Request again as a new request."*

**Disposition: confirms P6.1, P6.3 and P6.5.** Anchors of record remain `[BASE]` §2.3.1
p.113 and §2.3.2 p.121.

**One nuance worth having in the record** (it strengthens P6.3, it does not change it):
even *with* CRS Software Visibility enabled, the synthesised-`0001h` behaviour is
confined to a Configuration **Read of both bytes of the Vendor ID**. A configuration
**write** — which is what transaction #3 is — is silently re-issued under **any** CRS SV
setting. So P6.3's claim that `pcie_cfg_txn`'s phase-blind retry covers the bus-number
write is safe independently of P6.4's "CRS SV is not implemented" argument. Two
independent reasons, not one. **No edit required**; recorded here.

### C6 — ⚠️ Completer ID must be `0000h` until the Function's first Type 0 Configuration Write → **PREDICTION EDIT**

**The prompt.** `[MS]` pp.156–157 states the capture rule: *"Each function 'captures' its
own Bus and Device Number every time a Type 0 configuration write is seen on its link
from bytes 8-9 in the TLP Header… The saved Bus and Device numbers are used as the
Requester ID in TLP requests that this Endpoint initiates."* MindShare states the rule
for the Requester ID and omits the pre-capture case entirely.

**Chased to normative anchor.** `[BASE]` **§2.2.9 "Completion Rules" p.99**:

> "Functions must capture the Bus and Device Numbers supplied with all Type 0
> Configuration Write Requests completed by the Function, and supply these numbers in
> the Bus and Device Number fields of the Completer ID for all Completions generated by
> the Device/Function.
> • **If a Function must generate a Completion prior to the initial device Configuration
> Write Request, 0's must be entered into the Bus Number and Device Number fields**"

The Requester-ID counterpart is `[BASE]` §2.2.6.2 p.72; the Type 1 header cross-reference
is `[BASE]` §7.5.3.2 p.493 (*"PCI Express Functions capture the Bus (and Device) Number
as described in Section 2.2.6"*).

**Why it binds Stage D.** Apply it to the predicted sequence in §5.4:

| # | transaction | has the addressed Function seen a Type 0 CfgWr yet? | required Completer ID |
|---|---|---|---|
| 1 | CfgRd0 Vendor/Device → bridge `01:00.0` | no | **`0000h`** |
| 2 | CfgRd0 Header Type → bridge `01:00.0` | no | **`0000h`** |
| 3 | CfgWr0 bus numbers → bridge `01:00.0` | this *is* the first one | `0000h` on this completion; bridge captures `0100h` |
| 4 | CfgRd1 Vendor/Device → device `05:00.0` | no — #3 went to the *bridge* | **`0000h`** |
| 5 | CfgRd1 Header Type → device `05:00.0` | no | **`0000h`** |
| 6…n | BAR sizing/assignment → device `05:00.0` | first CfgWr here | `0000h` until it, `0500h` after |

So for **four of the first five transactions** the Completer ID is `0000h` — and it is
`0000h` at *both* the bridge and the device, simultaneously, throughout the entire probe
phase. A golden asserting `Completer ID == 0x0100` for #1/#2 or `== 0x0500` for #4/#5
would be asserting a **spec violation**.

**This is load-bearing on §8.2 Trap B.** §5.3 established that Device and Function are 0
on both sides by construction, leaving the bus field as the only discriminator. C6 shows
that in the Completer ID specifically, that discriminator is **not merely weak but
identically zero on both sides** during exactly the window a routing assertion would want
it. Trap B's forcing move ("would this still pass with all bus numbers equal?") answers
*yes* for any probe-phase Completer ID assertion — such an assertion is vacuous by
construction, not by accident.

**The live instance.** `tb/rc/test_pcie_enum_bar_tlp.py:193` builds every completion with
`cpl_dw1(BDF, status, …)` — the target BDF in *all* completions including the first
Vendor-ID read, which by definition precedes any configuration write. A Stage D bench
model extended from this pattern inherits the deviation. **This is a bench-fidelity item,
not an RTL defect:** nothing in `src/rc/` or the TL consumes a completion's Completer ID
(grep over `src/` finds it only in the vendored `src/verilog-pcie/` tree and at
`pcie_endpoint_top.sv:191`), so no DUT behaviour depends on it today. It becomes
load-bearing the moment a Stage D golden tries to use it as a routing discriminator —
which is precisely what Trap B predicts someone will reach for.

**Edit made:** new **P5.6** in `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` §5, plus an amendment to
§8.2 Trap B. Anchor cited: `[BASE]` §2.2.9 p.99.

### C7 — ⚠️ A Type 1 header has **two** BARs, not six → **PREDICTION EDIT**

**The prompt.** `[MS]` p.135, *"All BARs Must Be Evaluated Sequentially"*: *"All BARs must
be evaluated, even if software finds a BAR that is not being used… This means software
must evaluate every BAR in the header."* Written throughout for the six-BAR Type 0 case.
The phrase *"every BAR in the header"* is the operative one — it is header-type-relative,
and MindShare never says how many a Type 1 header has.

**Chased to normative anchor.** `[BASE]` **§7.5.3.1 "Base Address Registers (Offset
10h/14h)" p.493** — the Type 1 header's BAR subsection names **two** offsets. Contrast
`[BASE]` **§7.5.2.1 "Base Address Registers (Offset 10h - 24h)"**, the Type 0 subsection,
which names **six**. Figure 7-6 p.492 (already the map of record for §4) shows 18h
holding the bus numbers — i.e. exactly where Type 0's BAR2 would be.

**Why it binds Stage D.** Predictions §5.4 runs BAR sizing against the *device* at
`05:00.0`, which has a Type 0 header and six BARs — that is correct and unaffected. But
the doc never records the bridge's BAR count anywhere, and `docs/recon/RECON_stageD.md` §11.2's
decision gives Stage D a **second, per-level BAR instance**. A BAR stage pointed at the
bridge, sweeping the six offsets a Type 0 header has, would write all-1s into **18h** —
destroying the bus-number assignment made at transaction #3 — and then into 1Ch, 20h and
24h, which on a Type 1 header are the Secondary Status / IO Base-Limit and Memory
Base-Limit registers.

That failure is silent in the worst way: the corruption lands *after* the routing it
breaks was already established, so the probe transactions that preceded it still passed.

**Edit made:** new **P4.7** in `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` §4, cross-referenced from
§10. Anchor cited: `[BASE]` §7.5.3.1 p.493 vs §7.5.2.1.

### C8 — The provisional-Subordinate protocol: §5.4's single 18h write is not the general algorithm → **PREDICTION EDIT**

**The prompt.** `[MS]` pp.109–112, steps 1, 4, 8, 12, 18, 26, 27, 28, 38. Real enumeration
software writes each bridge's Subordinate Bus Number to **255** on the way *down* —
*"Setting this to the max value means that it won't have to be changed again until all the
bus numbers downstream have been identified"* — and rewrites it with the true value on the
way back *up*: step 18, *"enumeration software updates bridge D, with the real Subordinate
Bus Number of 3."* **Two writes per bridge**, separated by the entire depth-first descent
of that subtree.

Predictions §5.4 has **one** write, carrying final values (`{00h, 09h, 05h, 01h}`).

**Chased to normative anchor — and predictions are not wrong.** `[BASE]` §7.3.3 p.481
leaves bus-number assignment *"implementation specific"*, which predictions **P2.1**
already records. There is no normative ordering to violate: both the one-write and the
two-write protocols are legal. **No prediction is falsified.**

**But the coverage gap is real, and worth stating explicitly.** §5.4's single write is
viable *only* because Stage D fixes Subordinate a priori as a chosen constant (P5.2,
`0x09`), not because it discovered it. A general enumerator cannot know the Subordinate
value at write time — that is the entire reason MindShare's algorithm needs two writes.
Two consequences:

1. **The acceptance test must assert *this implementation's* order and say so.** §5.4's
   ordering assertion — write strictly before probe — would **fail against a perfectly
   correct depth-first implementation** that wrote a provisional Subordinate, probed, and
   rewrote. The assertion is sound as a check on *this* sequencer; it is not a spec check,
   and the document should not let a later reader mistake it for one.
2. **`docs/recon/RECON_stageD.md` §11.2's Stage E caveat gains a second concrete instance.** That
   caveat already says the per-level-instance shape does not scale to a tree walk. C8 adds
   that the *transaction protocol* does not scale either: Stage E's depth-first walk needs
   the two-phase write, so §5.4's shape is Stage-D-specific in two independent ways.

**Edit made:** new **P5.7** in `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` §5, with §5.4's ordering
claim marked as implementation-scoped. Anchor cited: `[BASE]` §7.3.3 p.481
(implementation-specific assignment) — the same anchor P2.1 already uses.

### C9 — P4.5's multifunction claim covers classification, not enumeration → **PREDICTION EDIT**

**The prompt.** `[MS]` p.109, step 3, on finding a bridge: *"The Multifunction bit (bit 7)
in the Header Type register is 0, indicating that Function 0 is the only Function in this
bridge. The spec doesn't preclude implementing multiple Functions within this Device and
each of these Functions, in turn, could represent other virtual PCI-to-PCI bridges or even
non-bridge functions."* Step 16 then enumerates all 8 functions of a device whose bit 7
is 1.

**Chased to normative anchor.** `[PCI30]` §6.1 p.214 (bit 7 = multifunction) — already
cited by P4.5. Nothing normative forbids a multifunction bridge.

**What predictions say, and why it needs narrowing.** P4.5 states: *"the existing bit-7
masking already makes a multi-function bridge classify correctly."* That is **true** —
masking to `[6:0]` before comparing to `7'h01` classifies a multifunction bridge as a
bridge. But *classification is not enumeration*: this design never reads functions 1–7 of
anything, and P5.3 fixes Function to 0 on both sides by construction. As written, P4.5
reads as a broader capability claim than it is.

**Edit made:** clarifying sentence appended to **P4.5** — classification holds;
enumeration of functions 1–7 is out of scope and untested, consistent with P5.3. No
anchor change.

---

## §2. Resolved-rejected

MindShare's claim is Gen-3-era, PC-platform-specific, or about machinery this design does
not have. Recorded with the reason it does not bind, so a later reader does not
re-discover it and assume it was missed.

### R1 — Scanning all 32 devices and all 8 functions

`[MS]` p.109 step 2 (*"each of the 32 possible devices on bus 0"*), step 16 (*"all 8
possible functions"*), steps 17 and 25 (*"devices 1 - 31"*).

**Does not bind.** This is the legacy shared-bus algorithm. MindShare contradicts it for
PCIe itself, twice: p.99, *"Endpoints on an external Link will always be Device 0"*; and
p.155, *"external PCIe links are always point-to-point… The device number for an external
link is forced by the downstream port to always be Device 0."* Normative anchor already in
the predictions: `[BASE]` §7.3.1 p.479 (P5.3). This confirms the standing
`DEVICES_TO_SCAN = 1` decision and the recorded reason for it — a 0–31 sweep on a
point-to-point link finds the same device 32 times.

### R2 — ⚠️ "Endpoints know to ignore Type 1 Requests"

`[MS]` p.100: *"Devices that are not bridges (Endpoints) know to ignore Type 1 Requests
since the target resides on a different bus."*

**Does not bind — and predictions are right to say the opposite.** This is legacy-PCI
language; `[PCI30]` p.49 says the same thing (*"All targets except PCI-to-PCI bridges
ignore Type 1 configuration transactions"*) and predictions §3 already quotes it. On PCIe
a non-posted Request must always be completed: `[BASE]` **§7.3.3 p.480** requires an
Endpoint receiving a Configuration Request of Type 1 to *"follow the rules for handling
Unsupported Requests"* — i.e. return a Completion with UR status.

**Recorded because the difference is observable and matters.** Predictions **P3.3** makes
the bench device model UR any CFG1 it sees. A model written to MindShare's "ignore" would
produce a **completion timeout** where the spec requires a **UR completion** — and
predictions §5.1 explicitly distinguishes those two outcomes (*"must fail with UR rather
than a timeout"*). Adopting MindShare's wording here would have broken exactly the
assertion §5.1 depends on. P3.3 stands unchanged.

### R3 — CRS Software Visibility, the synthesised `0001h` Vendor ID, the Root Control register

`[MS]` pp.107–108 and Figure 3-11.

**Does not bind.** Predictions **P6.4** already rejects this: the behaviour is conditional
on the CRS SV Enable bit in the Root Control register (`[BASE]` §7.8.12), and this design
has no Root Control register. A bench expecting `0001h` would be modelling an
unimplemented feature. Unchanged from the Stage C position.

### R4 — Configuration access mechanisms: CF8h/CFCh, ECAM, the 256MB window, ACPI

`[MS]` pp.91–98 and pp.102–104, including Table 3-1's address-bit map and the *Some Rules*
paragraph (no required support for dword-boundary-crossing accesses or bus locking).

**Does not bind.** These are host-platform mechanisms for turning a processor access into
a Configuration Request. This design's RC originates configuration TLPs directly and
models no configuration access mechanism at all — there is no address port, no data port
and no memory-mapped config window anywhere in the design. The `[MS]` p.102 worked example
is used above (**C1**) only for its *type-selection* conclusion, which is independent of
the mechanism that triggered it.

### R5 — Multi-root enumeration and the bus 64 / 128 conventions

`[MS]` pp.114–116.

**Does not bind.** Single-root topology. MindShare itself disclaims any normative force:
*"this is just a software convention. There are no PCI or PCIe rules requiring that
configuration."*

### R6 — The Host/PCI bridge's own Secondary and Subordinate Bus Number registers

`[MS]` p.109 step 1 (*"Software updates the Host/PCI bridge Secondary Bus Number to zero
and the Subordinate Bus Number to 255"*).

**Does not bind.** This design has no Host/PCI bridge configuration space; the RC's own
port is not modelled as an enumerable Function, and predictions record no equivalent
transaction. Predictions §10 item 4 already places the RC's own target-side Type 1
register file out of scope.

### R7 — Initialisation timing: 100 ms, Trhfa, the 1.0 s CRS validity window

`[MS]` pp.106–107.

**Does not bind.** Wall-clock platform timing. Stage C established `[SIM]` timeout values
(`tlp_layer.sv:11`) with the CRS retry inequality as the real constraint — predictions
**P6.3**: `CRS_RETRY_MAX (16) × CRS_BACKOFF_CYCLES (64) = 1024 < CPL_TIMEOUT_CYCLES
(4096)`. Stage D perturbs neither side of it. Adopting a 1.0 s window would make the suite
untestable in simulation for no spec-fidelity gain.

### R8 — ARI (Alternative Routing-ID Interpretation)

`[MS]` pp.155–156, and the ARI footnotes in the `[BASE]` capture rule quoted at C6.

**Does not bind.** No ARI in this design. Predictions **P5.3** already cites the *non-ARI*
clause of `[BASE]` §7.3.1 p.479 specifically, which is the correct scoping.

### R9 — Resizable BARs

`[MS]` p.135.

**Does not bind.** An extended-configuration-space capability structure; not implemented,
and Stage C's BAR sizing is the fixed-size protocol. Out of scope for Stage D and not
referenced by any prediction.

### R10 — The Express-PCI bridge and the PCI bus below it

`[MS]` p.104 Figure 3-9 and p.112 steps 33–35 (bridge J, bus 9, PCI devices at Dev 1/2/3).

**Does not bind.** A PCI Express-to-PCI bridge fronting a legacy shared PCI bus is the one
topology where multiple device numbers on one bus is real. This design has no such bridge;
`[BASE]` §7.3.3 p.481's *"or, for a PCI Express-PCI Bridge, its secondary PCI bus"* clause
is quoted in predictions §3 but is inapplicable here for the same reason.

---

## §3. Unresolved

No normative anchor found either way. **Recorded as open questions, not silently
adopted.** Neither has caused a prediction edit.

### U1 — What does a bridge do with a Type 1 request for bus `00h` while Secondary = Subordinate = `00h`?

Predictions §5.1 argues that at reset, *"Secondary = Subordinate = 00h, so by §3's test 1
and 2 no bus number matches or falls in range, and every Type 1 request is answered UR."*

Read literally against `[BASE]` §7.3.3 p.481, that is not quite right: test 1 asks whether
the target bus is *"equal to the bus assigned to one of its Downstream Ports"*, and at
reset that register **holds `00h`**. A Type 1 request targeting bus `00h` would therefore
*match* and be transformed to Type 0, not answered UR.

**Why it does not matter here — and why that resolution is only partial.** The case is
unreachable in this design: bus 0 is the local bus, so by P2.2 the RC originates **Type 0**
for it and never a Type 1. That argument is solid. What is *not* anchored is the more
general claim one would want: that `00h` in a Secondary Bus Number register means
"unassigned" rather than "bus 0". Neither `[BASE]` §7.3.3, nor §6.12.1.1 p.435, nor
`[PCI30]` §3.2.2.3.x p.49 says so, and MindShare does not address the reset state at all —
its walkthrough (**C3**) structurally avoids the window.

**Recommendation, not adopted:** §5.1's blanket phrasing is safe for Stage D but is
precise only for target bus ≠ `00h`. Left as-is; flagged here so a later increment that
widens the topology re-examines it rather than inheriting the phrasing.

### U2 — May a bridge itself return CRS to a Type 1 request addressed to a Function behind it?

Predictions **P6.2** says a bridge must not *synthesise* CRS on behalf of a device, arguing
that `[BASE]` §7.3.3 p.481 gives the bridge only three outcomes for a Type 1 request —
transform-and-forward, forward-unmodified, or UR — and CRS is not among them.

That argument is sound about the **forwarding** path. It is an argument from silence about
the bridge acting as a **Completer in its own right** when it cannot forward at all (for
instance, secondary link not up). `[BASE]` §2.3.1 p.113 makes CRS legal *"in response to a
Configuration Request"* without restricting which Function may issue it, and MindShare
p.107 frames CRS purely as a Function's own not-ready response, saying nothing about
bridges.

**Not adopted either way.** P6.2 is retained unchanged — it is the conservative reading and
it makes the bench model deterministic. Recorded because if a Stage E bench ever needs a
bridge that stalls, this is the question that will have to be answered properly.

---

## §4. What this pass did not change

Stated so the absence is visible rather than looking like an oversight.

- **No constant, golden or anchor in `docs/predictions/SPEC_PREDICTIONS_STAGE_D.md` derives from
  MindShare.** The four edits (C6–C9) each carry a `[BASE]` anchor located during this
  pass; MindShare's role was to prompt the look, and that role is recorded here only.
- **No `[MS]` citation was added to any prediction, test or RTL comment.**
- **No prediction was falsified.** The Part B stop-and-report trigger — a MindShare claim
  contradicting a committed prediction *with normative support for MindShare* — did not
  fire. The one apparent contradiction (**R2**, "Endpoints ignore Type 1") resolved
  **against** MindShare on a normative re-read.
- **§7's per-increment failure predictions are untouched.** Nothing in this pass bears on
  D-1a or D-1b; C6 and C7 bear on D-3, C8 on D-3 and Stage E, C9 on documentation scope.
- **The baseline and invariants (§9) are untouched.** This is a doc-only pass.
