# Stage D — Spec Predictions (CFG1 origination + Type 1 bridge enumeration)

**Written at `7c2e132`** (= `f49d73d` + the D-0 recon commit), on `kourosh/dev`, before
any Stage D RTL exists and before any new test has been run against any DUT. Brief
§2.5: predictions are committed *first*; falsification is **measured**, not asserted.

**Companion:** `RECON_stageD.md` — read-only recon, `file:line` evidence at `f49d73d`,
plus the two architectural decisions (§11) this document builds on.

---

## §0. Source-of-record

### §0.1 Citation tags

Carried unchanged from `SPEC_PREDICTIONS_ENUM.md` §0.2, so a reader moving between the
two documents does not have to re-learn them.

| tag | meaning |
|---|---|
| `[BASE]` | PCI Express Base Specification Rev 2.1 — section + page. **Golden.** |
| `[PCI30]` | PCI Local Bus Specification Rev 3.0 — section + page + `.txt` line. **Golden.** |
| `[PG213]` | Xilinx PG213 — the *socket* contract only, never TLP semantics. |
| `[DESIGN]` | A choice this project makes that the spec permits but does not compel. |
| `[SIM]` | A value chosen for simulation practicality; not spec-real. |

**Never golden:** MindShare, Southwell, and the PCI Express Base 4.0 **Rev 0.3 draft**
that is also on the shelf. None is cited anywhere in this document.

### §0.2 ⚠️ The Type 1 register map comes from Base 2.1, not PCI 3.0

The brief's R8 named `pci-local-bus-3.0.txt` as the source for the Type 01h header
layout. **It is not a source for it.** `[PCI30]` §6.1 p.214 (`:10546-10549`):

> "Currently three Header Types are defined, 00h which has the layout shown in
> Figure 6-1, **01h which is defined for PCI-to-PCI bridges and is documented in the
> PCI to PCI Bridge Architecture Specification**, and 02h which is defined for CardBus
> bridges…"

Figure 6-1 (p.215) is the Type **00h** header; at offset 18h it shows *Base Address
Registers*. The PCI-to-PCI Bridge Architecture Specification is **not on the shelf**
(full recursive listing of `/home/kourosh/openPCIE/0.doc` in `RECON_stageD.md` §8).

**The map used here is `[BASE]` §7.5.3 Figure 7-6 p.492**, which defines the Type 1
Configuration Space Header for "Switch and Root Complex virtual PCI Bridges" — exactly
this project's topology. Its own scope note (§7.5.3 p.493) confirms applicability:
*"Register interpretations described in this section apply to PCI-PCI Bridge structures
representing Switch and Root Ports."*

**Do not re-derive this.** A later session that opens PCI 3.0, finds the deferral, and
reaches for MindShare would be violating §0.1. The substitution is settled here.

### §0.3 Page-marker convention

Page markers in the `.txt` extracts are **footers**: content *after* marker N is on page
N+1. Every page number below was resolved by locating the bracketing markers, not
estimated. Line numbers for `[BASE]` refer to a `pdftotext -layout` extract of
`PCIE-base-spec.Rev2-1.pdf`; they are given as corroboration, and the section+page is
the citation of record.

---

## §1. Type 0 vs Type 1 on the wire

`[BASE]` **Table 2-3 p.58**, "Fmt[1:0] and Type[4:0] Field Encodings" (`:2637-2640`),
transcribed verbatim:

| TLP Type | Fmt (b) | Type (b) | Description |
|---|---|---|---|
| CfgRd0 | `000` | `0 0100` | Configuration Read Type 0 |
| CfgWr0 | `010` | `0 0100` | Configuration Write Type 0 |
| CfgRd1 | `000` | `0 0101` | Configuration Read Type 1 |
| CfgWr1 | `010` | `0 0101` | Configuration Write Type 1 |

**P1.1 — exactly one bit differs.** Type[0]: `0` for Type 0, `1` for Type 1. Fmt is
unchanged between CFG0 and CFG1 for the same direction; direction alone selects Fmt
(`000` read / `010` write, i.e. 3DW-no-data / 3DW-with-data). Confirmed against
`tlp_pkg.sv:20-21` — `TLP_TYPE_CFG0 = 5'b00100`, `TLP_TYPE_CFG1 = 5'b00101` — which
already encode this correctly.

**P1.2 — no other header field differs.** `[BASE]` §2.2.7 p.79 lists the restrictions
for *Configuration Requests* as a single class, with no Type 0/Type 1 distinction:

- `TC[2:0]` must be `000b`
- TH is not applicable; the bit is reserved
- `Attr[2]` reserved; `Attr[1:0]` must be `00b`
- `AT[1:0]` must be `00b`
- `Length[9:0]` must be `00 0000 0001b`
- `Last DW BE[3:0]` must be `0000b`

and Figure 2-18 p.80 gives one header format for "Configuration Transactions", with
DW2 = `{Bus Number, Device Number, Function Number, Reserved, Ext. Reg. Number,
Register Number, R}` — again with no Type 0/1 variation.

**Corroborated structurally, not just textually:** `tlp_generator.sv:81-82` builds DW2
from `header.address[31:2]` and never reads `completer_id`; DW0's type field is
`dw0[4:0] = header_r.tlp_type` (`:64`). So in this implementation the *only* thing that
can differ is `dw0[4:0]` — the RTL cannot express a second difference even if one
existed. (`RECON_stageD.md` §4.)

> **This is trap 8a's foundation.** Because exactly one bit distinguishes the two, an
> on-wire assertion that omits `dw0[4:0]` — or that compares DW1/DW2/payload only —
> passes identically for CfgRd0 and CfgRd1. See §8.1.

---

## §2. The origination rule — and why §7.3.3 is *not* its anchor

The brief asked for the bus-number rule's own anchor and warned against reusing §7.3.1
p.479 by proximity. Both cautions are justified, and there is a third:

**P2.1 — `[BASE]` does not state the originator's selection rule.** §7.3.3 p.480
addresses Root Ports, Switches and Bridges as *receivers/forwarders*. Its only remark
about origination is *"Configuration Requests are initiated only by the Host Bridge"*
(p.480), and its Root-Complex-specific rule says bus-number assignment "may be done in
an implementation specific way" (p.481). Searching `[BASE]` for a "the Root Complex
emits Type 1 when…" statement finds none.

**P2.2 — the normative rule is `[PCI30]` §3.2.2.3.x p.49** (`:2103-2104`):

> "A Type 0 configuration transaction is not propagated beyond the local PCI bus and
> must be claimed by a local device or terminated with Master-Abort. **If the target of
> a configuration transaction resides on another bus (not the local bus), a Type 1
> configuration transaction must be used.**"

That is the "must" this stage implements. Restated for our topology: **emit Type 0 when
the target bus equals the bus directly behind the port; emit Type 1 for any bus beyond
it.**

**P2.3 — the bus-number *comparison mechanics* are non-normative.** `[PCI30]` p.52
(`:2258-2265`) gives the familiar match/range test (equal to Bus Number register →
Type 0; greater than it and ≤ Subordinate → Type 1). **This passage sits inside an
`IMPLEMENTATION NOTE`** (heading at `:2240`, "Bus Number Registers and Peer Host
Bridges") and is therefore corroboration, not a citation of record. Any Stage D
assertion that needs a "must" cites p.49; p.52 may be cited only as *"consistent
with."*

**P2.4 — §7.3.1 p.479 is the device-number anchor only.** Confirmed: it carries the
Device 0 association and the UR-for-devices-1-31 rule, plus *"Non-ARI Devices must
respond to all Type 0 Configuration Read Requests, regardless of the Device Number."*
It says nothing about bus-number-driven type selection. The brief's warning was correct.

---

## §3. What a bridge does with a Type 1 request

`[BASE]` §7.3.3 **p.481** (`:23372-23392`), for Root Ports, Switches and PCI
Express-PCI Bridges, applied **in sequence** to the Bus Number and Device Number:

1. If equal to the bus assigned to one of its Downstream Ports (or, for a PCI
   Express-PCI Bridge, its secondary PCI bus):
   > "**Transform the Request to Type 0 by changing the value in the Type[4:0] field of
   > the Request (see Table 2-3) — all other fields of the Request remain unchanged**"
   > and "Forward the Request to that Downstream Port."
2. If not equal to any Downstream Port's bus, but **in the range** of buses assigned to
   one: *"Forward the Request to that Downstream Port interface without modification."*
3. Else: *"The Request is invalid – follow the rules for handling Unsupported
   Requests."*

The aperture that defines "in the range" is stated explicitly at `[BASE]` §6.12.1.1
**p.435** (`:21218-21225`): *"the inclusive range specified by the Secondary Bus Number
register and the Subordinate Bus Number register."*

`[PCI30]` p.49 (`:2104-2112`) agrees and adds the negative case: *"All targets except
PCI-to-PCI bridges ignore Type 1 configuration transactions… If the Bus Number is not
for a bus behind the bridge, the transaction is ignored."*

**P3.1 — the bench bridge model's contract, derived.** For a request arriving at the
bridge:

| condition | model must | golden |
|---|---|---|
| Type 1, bus == its Secondary Bus Number | flip Type[0] `1`→`0`, change **nothing else**, deliver to the device | emitted-to-device DW0 differs from received DW0 in bit 0 **only**; DW1 and DW2 byte-identical |
| Type 1, Secondary < bus ≤ Subordinate | forward unmodified | all three DWs byte-identical (unreachable in the one-level topology — see §3.2) |
| Type 1, bus outside `[Secondary, Subordinate]` | complete with **UR** | `[BASE]` §7.3.3 p.481 |
| Type 0 addressed to the bridge's own BDF | consume locally (it is the bridge's own config space) | `[BASE]` §7.3.3 p.480 |

**P3.2 — the forward-unmodified arm is unreachable in Stage D and must not be faked.**
With one bridge level there is exactly one bus behind it, so Secondary == Subordinate
and case 2 has no satisfying bus number. The model should implement it and the tests
should **not** claim to cover it. Writing a test that "exercises" it by setting
Subordinate > Secondary with no device there would assert model behaviour, not DUT
behaviour — `RECON_stageD.md` §11.2's Stage E caveat applies.

**P3.3 — Type 1 requests must NOT be answered by a non-bridge.** `[BASE]` §7.3.3 p.480,
for Endpoints: *"If Configuration Request Type is 1, follow the rules for handling
Unsupported Requests."* The bench's downstream *device* model must therefore **UR any
CFG1 it sees** — it should only ever see CFG0, post-transform. This is a live
cross-check that the bridge model actually transformed, and it is free.

---

## §4. The Type 1 register map

From `[BASE]` §7.5.3 **Figure 7-6 p.492**. Offset **18h**, one Dword:

| bits | field | width |
|---|---|---|
| `[31:24]` | Secondary Latency Timer | 8 |
| `[23:16]` | Subordinate Bus Number | 8 |
| `[15:8]` | Secondary Bus Number | 8 |
| `[7:0]` | Primary Bus Number | 8 |

**P4.1 — one whole-Dword write, no read-modify-write.** All four fields live in one
Dword, so the Stage C precedent (`SPEC_PREDICTIONS_ENUM.md`; whole-DW config writes,
`first_be = 1111b`) covers it exactly. No new byte-enable behaviour is introduced.
This also sidesteps `[PCI30]` §6.1 p.214's read-modify-write requirement for *reserved*
bits — there are no reserved bits in this Dword.

**P4.2 — ⚠️ Secondary Latency Timer is read-only 00h.** `[BASE]` §7.5.3.3 **p.493**:
*"This register does not apply to PCI Express. It must be read-only and hardwired to
00h."*

> **Consequence for the goldens.** The write at 18h necessarily drives `[31:24]`,
> and the device must **ignore** it. A read-back golden must expect `[31:24] == 00h`
> **regardless of what was written.** A test that writes a non-zero Secondary Latency
> Timer and asserts it reads back is asserting a *spec violation* and must not be
> written. Predicted: writing `00h` there is the only defensible choice, so the
> emitted 18h Dword is `{8'h00, Subordinate, Secondary, Primary}`.

**P4.3 — Primary Bus Number is read-write but functionally inert on PCIe.** `[BASE]`
§7.5.3.2 **p.493**: *"Except as noted, this register is not used by PCI Express
Functions but must be implemented as read-write for compatibility with legacy
software."* So the RC must still write a correct value (the bench bridge must accept
and return it), but **no routing decision depends on it.** Any test that claims to
prove routing by varying Primary Bus Number alone would be vacuous — see §8.2.

**P4.4 — Secondary and Subordinate have no §7.5.3.x subsection in `[BASE]`.** Their
*layout* is Figure 7-6; their *semantics* come from §7.3.3 p.481 (the match/range tests)
and §6.12.1.1 p.435 (the aperture definition). Recorded so a later reader does not
search for a subsection that does not exist and conclude the map is incomplete.

**P4.5 — Header Type field.** `[PCI30]` §6.1 p.214 places Header Type at offset **0Eh**
and defines bit 7 as the multi-function bit with `[6:0]` the layout code, `01h` being
the PCI-to-PCI bridge layout. This matches the existing RTL exactly:
`pcie_enum_pkg.sv:179` `HDR_TYPE_LSB = 16` (byte 2 of the register-3 Dword = offset
0Eh ✓), `:199` `HDR_LAYOUT_TYPE0 = 7'h00`, and `pcie_enum_scan.sv:303` masking to
`[6:0]` before comparison. **Predicted: `HDR_LAYOUT_TYPE1 = 7'h01` is the only new
constant needed**, and the existing bit-7 masking already makes a multi-function bridge
classify correctly.

> **Scope clarification, added 2026-07-31** (`MINDSHARE_CROSSCHECK_STAGE_D.md` C9). The
> claim above is about **classification only**: masking to `[6:0]` before comparing to
> `7'h01` classifies a multi-function bridge *as a bridge*. It is **not** a claim that
> this design enumerates a multi-function device. It does not — functions 1–7 are never
> read, of a bridge or of anything else, and §5.3 fixes Function to 0 on both sides by
> construction. A multi-function bridge is therefore **out of scope and untested** in
> Stage D. `[PCI30]` §6.1 p.214 (bit 7) is unchanged as the anchor; nothing normative
> forbids a multi-function bridge, so this is a scope boundary, not a spec limit.

**P4.6 — the Command register for a bridge.** `[BASE]` §7.5.1 is titled **"Type 0/1
Common Configuration Space"** (**p.484**) and states of the registers in Figure 7-4:
*"These registers are defined for both Type 0 and Type 1 Configuration Space
headers."* The Command register is one of them — §7.5.1.1 **"Command Register (Offset
04h)" p.485** — and Figure 7-6 p.492 confirms 04h holds Command in the Type 1 layout
too. **Predicted: no new handling** — the Stage C Command-register enable applies
unchanged to a Type 1 Function, and the register is common by the spec's own
organisation, not by our assumption. Note that the bridge's
*Bridge Control* register (3Ch, Figure 7-6) is a separate register and is **out of
scope** (it gates secondary-side error/reset behaviour, not config routing).

**P4.7 — ⚠️ a Type 1 header has TWO BARs (10h/14h), not six.** *Added 2026-07-31;
`MINDSHARE_CROSSCHECK_STAGE_D.md` C7.* `[BASE]` **§7.5.3.1 "Base Address Registers
(Offset 10h/14h)" p.493** names two offsets for the Type 1 header. Contrast `[BASE]`
**§7.5.2.1 "Base Address Registers (Offset 10h - 24h)"**, the Type 0 subsection, which
names six. Figure 7-6 p.492 — already the map of record for this section — shows **18h
holding the bus numbers**, i.e. exactly where Type 0's BAR2 would sit.

> **Consequence, and the trap it creates.** §5.4 runs BAR sizing against the *device* at
> `05:00.0`, which has a Type 0 header and six BARs — correct and unaffected. But
> `RECON_stageD.md` §11.2 gives Stage D a **second, per-level BAR instance**, and a BAR
> stage pointed at the *bridge* would sweep six offsets against a two-BAR header. The
> first casualty is **18h**: an all-1s sizing write there **destroys the bus-number
> assignment made at transaction #3**, after which 1Ch, 20h and 24h take the Secondary
> Status, IO Base/Limit and Memory Base/Limit registers.
>
> This fails silently in the worst way — the corruption lands *after* the routing it
> breaks was established, so every probe transaction that preceded it still passed.
> **A BAR stage must never be pointed at a Type 1 Function in Stage D.** See §10 item 7.

---

## §5. Bus-number assignment order

**P5.1 — the write must precede the first CFG1 probe.** A bridge at reset has
Secondary = Subordinate = 00h, so by §3's test 1 and 2 *no* bus number matches or falls
in range, and every Type 1 request is answered **UR** (§3 case 3). Therefore:

> **Ordering prediction:** the bus-number Dword write at 18h is the **structurally
> first** transaction of the bridge sequence, and the first CFG1 probe is
> **structurally after** it. A trace showing the probe first must fail the acceptance
> test, and must fail with UR rather than a timeout.
>
> **⚠️ Scoped 2026-07-31 — see P5.7.** This is the acceptance criterion for **this**
> sequencer, **not** a spec check. `[BASE]` §7.3.3 p.481 leaves bus-number assignment
> implementation-specific, and the standard two-phase protocol (provisional Subordinate,
> descend, rewrite) would legally violate it. The claim is retained unchanged; the
> acceptance test must state which of the two it asserts.

**P5.2 — the values, forced apart per brief §7.** Existing goldens use
`VENDOR = 0x144D`, `DEVICE = 0xA80A`, `BDF = 0x0100` (bus 1, dev 0, fn 0) —
`enum_tb_common.py:937,939,654`. Stage D values must avoid all three and must not be
mutually degenerate.

| quantity | value | why this value |
|---|---:|---|
| bridge's bus (= Primary Bus Number) | `0x01` | forced: the bridge sits on the bus the existing scan already probes |
| Secondary Bus Number | `0x05` | non-zero, ≠ primary, **not** primary+1 — so "off by one from the parent" is distinguishable from correct |
| Subordinate Bus Number | `0x09` | ≠ secondary, so an implementation that writes the same value into both fields is caught |
| bridge Vendor / Device ID | `0x1AF4` / `0x1100` | distinct from `0x144D` / `0xA80A` |
| device (behind bridge) Vendor / Device ID | `0x15B3` / `0x1017` | distinct from the bridge's **and** from the 2b goldens' |

All four ID values are `[DESIGN]` — arbitrary but deliberately pairwise-distinct, and
none is `0xFFFF` (which `enum_tb_common.py:937` reserves as the absence signal).

**Every field of the 18h Dword is a different value:** `00h` / `09h` / `05h` / `01h`.
An implementation that swapped Secondary and Subordinate, or that wrote Primary into
Secondary, produces a different Dword and is caught by the whole-word golden.

**P5.3 — ⚠️ the BDFs can differ in the bus field ONLY, and this qualifies brief §7.**
Brief §7 requires the bridge's and the device's BDFs to "differ in **every** field that
can differ." Working out which fields *can*: `[BASE]` §7.3.1 p.479 requires a
Downstream Port without ARI Forwarding to *"associate only Device 0 with the device
attached to the Logical Bus"*, and the secondary link in a one-bridge topology is
point-to-point — the same reasoning that gives `DEVICES_TO_SCAN = 1` on the primary
link applies unchanged below the bridge. Function is 0 for the same single-function
reason as Stage C.

> **So Device and Function are 0 on both sides by construction, and only Bus can
> differ.** Bridge BDF `0x0100` (bus 1) vs device BDF `0x0500` (bus 5). This is not a
> weakening of brief §7 — it is the honest answer to its own question, and it is why
> the bus numbers themselves (P5.2) had to be forced apart so carefully: **the bus
> field is the only discriminator the routing assertions have.**
>
> Recorded consequence: any Stage D assertion whose discriminating power rests on
> Device or Function differing is vacuous by construction. Check each against this.

**P5.4 — the predicted sequence.** Structurally ordered; the acceptance test asserts
the order, not merely the set.

| # | transaction | target | type | register |
|---|---|---|---|---|
| 1 | CfgRd0 Vendor/Device | `01:00.0` | **0** | 00h |
| 2 | CfgRd0 Header Type | `01:00.0` | **0** | 0Ch |
| — | *scan classifies Type 1 → bridge sequencer starts* | | | |
| 3 | **CfgWr0 bus numbers** | `01:00.0` | **0** | **18h** ← must precede #4 |
| 4 | CfgRd1 Vendor/Device | `05:00.0` | **1** | 00h |
| 5 | CfgRd1 Header Type | `05:00.0` | **1** | 0Ch |
| 6…n | BAR sizing / assignment | `05:00.0` | **1** | 10h… |
| last | Command-register enable | `05:00.0` | **1** | 04h |

Transactions 1–2 are Type **0** because the bridge is on the bus directly behind the
port (§2.2). Transactions 3 is Type **0** for the same reason — *the bus-number write
targets the bridge itself*, not anything behind it. Everything from 4 on is Type **1**
because bus 5 is beyond the port's own bus (§2.2).

> **This is the second high-value trap.** It is natural to assume "the bridge phase
> uses Type 1." It does not: transaction 3 addresses the bridge, which is on the local
> bus, so it is Type **0**. An implementation that emits CfgWr1 for the bus-number
> write would be spec-wrong *and* would be answered UR by a correct bridge model
> (§3 case 3 — at that instant Secondary is still 00h). See §8.3.

**P5.5 — the Command-register enable stays structurally last.** Brief §6 D-3 requires
it, and Stage C already proves it for the direct-attach case; the prediction is that
this is preserved unchanged when the target is addressed via CFG1, because the ordering
is a property of the BAR stage, not of the config type.

**P5.6 — ⚠️ Completer ID is `0000h` until the Function's first Type 0 Configuration
Write.** *Added 2026-07-31; `MINDSHARE_CROSSCHECK_STAGE_D.md` C6.* `[BASE]` **§2.2.9
"Completion Rules" p.99**:

> "Functions must capture the Bus and Device Numbers supplied with all Type 0
> Configuration Write Requests completed by the Function, and supply these numbers in
> the Bus and Device Number fields of the Completer ID for all Completions generated by
> the Device/Function.
> • **If a Function must generate a Completion prior to the initial device Configuration
> Write Request, 0's must be entered into the Bus Number and Device Number fields**"

The Requester-ID counterpart is `[BASE]` §2.2.6.2 **p.72**; `[BASE]` §7.5.3.2 **p.493**
cross-references the same capture rule from the Type 1 header's Primary Bus Number
entry (which is why P4.3's "functionally inert" register is *not* how a Function learns
its bus number — capture is).

Applied to P5.4's sequence:

| # | transaction | has the **addressed** Function seen a Type 0 CfgWr yet? | required Completer ID |
|---|---|---|---|
| 1 | CfgRd0 Vendor/Device → bridge `01:00.0` | no | **`0000h`** |
| 2 | CfgRd0 Header Type → bridge `01:00.0` | no | **`0000h`** |
| 3 | CfgWr0 bus numbers → bridge `01:00.0` | this **is** its first | `0000h` on this completion; bridge captures `0100h` |
| 4 | CfgRd1 Vendor/Device → device `05:00.0` | no — #3 addressed the **bridge** | **`0000h`** |
| 5 | CfgRd1 Header Type → device `05:00.0` | no | **`0000h`** |
| 6…n | BAR sizing/assignment → device `05:00.0` | its first CfgWr is in here | `0000h` until it, `0500h` after |

> **Predicted: a golden asserting `Completer ID == 0x0100` for #1/#2, or `== 0x0500` for
> #4/#5, is asserting a spec violation and must not be written.** The device captures
> `05:00.0` only on the first *write* it completes — which arrives post-transform as a
> CfgWr0 (§3 case 1) during the BAR stage, not during the probe.
>
> **Live instance to fix, not inherit:** `tb/rc/test_pcie_enum_bar_tlp.py:193` builds
> every completion with `cpl_dw1(BDF, …)`, including the first Vendor-ID read. This is
> **bench fidelity, not an RTL defect** — nothing in `src/rc/` or the TL consumes a
> completion's Completer ID today — but a Stage D model extended from that pattern
> inherits the deviation, and P5.6 is exactly the rule that makes it matter.

**P5.7 — ⚠️ P5.4's single 18h write is Stage-D-specific, not the general algorithm.**
*Added 2026-07-31; `MINDSHARE_CROSSCHECK_STAGE_D.md` C8.* A general enumerator cannot
know the Subordinate Bus Number at write time — it is discovered by descending. The
standard shape is therefore **two writes per bridge**: a provisional wide Subordinate on
the way down, and the true value rewritten on the way back up.

P5.4's single write is viable **only** because Stage D fixes Subordinate a priori as a
chosen constant (P5.2, `0x09`), not because it discovered it. `[BASE]` §7.3.3 **p.481**
leaves bus-number assignment *"implementation specific"* (already recorded at P2.1), so
**both shapes are legal and no prediction here is falsified.** Two consequences:

1. **P5.1's ordering claim is scoped to this implementation.** *Marked, not withdrawn:*
   "the bus-number Dword write at 18h is the **structurally first** transaction of the
   bridge sequence" remains the acceptance criterion for **this** sequencer, but it is
   **not a spec check** — a correct depth-first enumerator that wrote a provisional
   Subordinate, probed, then rewrote would violate it. The acceptance test must say
   which of the two it is asserting.
2. **`RECON_stageD.md` §11.2's Stage E caveat gains a second instance.** That caveat
   already says the per-level-instance *structure* does not scale to a tree walk. P5.7
   adds that the *transaction protocol* does not either: Stage E's depth-first walk needs
   the two-phase write. P5.4's shape is Stage-D-specific in two independent ways.

---

## §6. CRS through a bridge

**P6.1 — CRS is legal for both transactions in question, and for no others here.**
`[BASE]` **§2.3.1 p.113**, the "Configuration Request Retry Status" implementation note
(`:5426-5428`; the note sits in §2.3.1 *Request Handling Rules* and defers Root Complex
handling to §2.3.2): *"it is only legal to respond with a CRS Completion Status in
response to a Configuration Request. Sending this Completion Status in response to any
other Request type is illegal."* Both the
bus-number write (#3, a CfgWr0) and the first CFG1 probe (#4, a CfgRd1) **are**
Configuration Requests. So:

- **Can the bridge return CRS to the bus-number write? Yes** — it is a Configuration
  Request to the bridge's own Function, and a bridge is as entitled to a
  self-initialisation period as any device.
- **Can the downstream device return CRS to the first CFG1 probe? Yes** — post-transform
  the device sees a CfgRd0 to its own Function (§3), which is precisely the case
  `[BASE]` §2.3.2 p.121 describes.

**P6.2 — a bridge must not *synthesise* CRS on behalf of a device.** Nothing in §7.3.3
p.481 permits it: the bridge's only choices for a Type 1 request are transform-and-
forward, forward-unmodified, or UR. A CRS seen by the RC therefore always originated at
the Function the request was addressed to. The bench bridge model must not invent one.

**P6.3 — existing `pcie_cfg_txn` CRS retry covers both, unchanged.** `[BASE]` §2.3.2
**p.121** (`:5753-5754`): with CRS Software Visibility not enabled, *"the Root Complex
must re-issue the Configuration Request as a new Request."* That is exactly what
`pcie_cfg_txn` does, and it is **phase-blind** — it retries whatever request it was
given, so it retries a CfgWr0-to-bridge and a CfgRd1-to-device identically.

The retry budget is unchanged and still satisfies the Stage C inequality recorded at
`pcie_enum_pkg.sv:141`:

```
CRS_RETRY_MAX (16) * CRS_BACKOFF_CYCLES (64) = 1024  <  CPL_TIMEOUT_CYCLES (4096)
```

`[SIM]` on the timeout value (`tlp_layer.sv:11`); the inequality is the real
constraint and Stage D does not perturb either side of it.

**P6.4 — CRS Software Visibility is NOT implemented and must not be modelled.**
`[BASE]` §2.3.2 p.121 makes the 0001h synthesised-Vendor-ID behaviour conditional on
the CRS SV Enable bit in the Root Control register (§7.8.12). This design has no Root
Control register. **Predicted: the RC retries silently and never synthesises 0001h.** A
bench that expected 0001h would be modelling an unimplemented feature. This restates
the Stage C position; it is not new, and Stage D does not change it.

**P6.5 — CRS is not a timeout and not an error.** Restating brief §2.10 for the new
phase: status `010b` — `[BASE]` **Table 2-28, "Completion Status Field Values", p.98**
(`:4703-4710`; `000` SC, `001` UR, `010` CRS, `100` CA, *"all others Reserved"*) — a
*normal* completion. The bridge sequencer must not reclassify it. Likewise
`RC_ERR_ORPHAN_DATA` bursts correlated with `late_cpl_valid_o` remain non-faults that
`pcie_cfg_txn` already absorbs — the sequencer must not re-interpret them
(brief §2.10).

---

## §7. Per-increment failure predictions (to be MEASURED)

Brief §2.5: each row claiming a pre-change failure gets **run against pre-change RTL**
and the observed count recorded. The "measured" column stays empty until then; filling
it in from expectation rather than from a run is the failure this column exists to
prevent.

### §7.1 D-1a — the class refactor (`tlp_requester.sv`), zero behaviour change

| id | prediction | measured |
|---|---|---|
| **F1a.1** | **No test changes state.** All 36 targets / 258 tests PASS, and **every sim end time is identical** to `RECON_stageD_baseline.txt`. This is the whole gate. | |
| **F1a.2** | No new test is added in D-1a. Adding one would confound the inertness argument — a new test passing proves nothing about whether old observations moved. | |

**The inertness argument, stated for the record** (decision A, `RECON_stageD.md` §11.1).
`tlp_requester.sv` has no parameter gating it off, so "byte-identical where gated off"
cannot apply. Instead: every test in the suite asserts against **spec goldens**, so an
unchanged PASS set *with identical sim end times* **is** an unchanged set of observed
values — a refactor that altered any emitted value would either flip a golden
comparison or shift a handshake and move a sim end time. Same argument that proved the
`pcie_enum_top` hoist. It is weaker than a byte-diff and is accepted here **only**
because the refactor is confined to predicate extraction with no state, no timing and
no port changes; if D-1a turns out to need anything more, this gate is void and the
commit must be re-scoped.

### §7.2 D-1b — append + CFG1 origination

Tests here are new and **must fail against pre-change RTL**. Because `tlp_cmd_e` gains
its members in this same commit, "pre-change" means: the new test file run against the
tree with `tlp_requester.sv`'s class **not** extended to the new members, but the enum
members present. That isolates the behaviour from the compile.

| id | new test | prediction against pre-change RTL | measured |
|---|---|---|---|
| **F1b.1** | CfgRd1 on-wire golden — all three DWs | **FAIL.** `dw0[4:0]` reads `00000` (`TLP_TYPE_MEM`), not `00101`. Site 3 fail-open: `tlp_requester.sv:115` is the default and `:116` never matches. Fmt also wrong (`000` is right by luck for a read; a **CfgWr1 emits `010` with a 4DW-vs-3DW hazard**). | |
| **F1b.2** | CfgWr1 on-wire golden — all three DWs + payload | **FAIL**, and predicted to fail *differently* from F1b.1: `command_has_data` (`:104-105`) omits `CFG_WRITE1`, so the requester takes the no-data path and **emits no payload beat at all**. Distinct failure mode from F1b.1 — recorded because a single "it fails" observation would hide that these are two independent sites. | |
| **F1b.3** | Rejection matrix for CFG1: offset × byte_count, re-proven for the new commands (not inherited from CFG0) | **FAIL — and this is the dangerous one.** The guard at `:192-195` omits the new members, so requests with `byte_count > 4 − address[1:0]` are **admitted**. Predicted symptom: acceptance where the matrix demands rejection, i.e. the test fails by *not* seeing a rejection, not by seeing a wrong value. | |
| **F1b.4** | CfgRd1 completion correlates to the right tag and status | **FAIL.** `tag_expects_data_o` (`:142-143`) omits `CFG_READ1`, so the read's completion is not expected and the tracker mismatches. | |
| **F1b.5** | CFG1 segment limit is 4 bytes | **FAIL.** `command_limit()` (`:76-77`) omits the new members and returns `max_payload_bytes_i` (`:81`). | |

> Five rows because there are five sites (`RECON_stageD.md` §3) — **but after D-1a they
> are one predicate.** Predicted: post-D-1a, a single mutation (removing the new members
> from `is_cfg()`) kills all five rows at once. **If it does not — if some row survives
> a mutation that should kill it — the refactor missed a site**, and that is the
> highest-value signal D-1b can produce. Record which rows die together.

**Regression:** 36/258 unmoved, 580.00 ns invariant on both timeout targets.

### §7.3 D-2 — CFG1 through the RQ/RC surface

| id | new test | prediction against pre-change RTL | measured |
|---|---|---|---|
| **F2.1** | `req_type = 1001` admitted, maps to `TLP_CMD_CFG_READ1` | **FAIL.** Falls to `pcie_rq_if.sv:247` `default: type_ok = 1'b0` → `RQ_ERR_REQ_TYPE` (`:309`). | |
| **F2.2** | `req_type = 1011` admitted, maps to `TLP_CMD_CFG_WRITE1` | **FAIL**, same path. | |
| **F2.3** | Reject-set unchanged: all 12 other encodings still rejected, **and** rejected with `RQ_ERR_REQ_TYPE` specifically | **PASS** against pre-change RTL (nothing rejected today becomes accepted). Kept as a **control** — it is the test that catches a mis-typed case arm silently widening the accept set. | |
| **F2.4** | Poisoned CfgWr1 rejected | **FAIL** — see mutation M2.4 below; `:286` names `TLP_CMD_CFG_WRITE0` only. | |
| **F2.5** | CFG1 completion returns like any config completion; tag correlation and status decode unchanged | **PASS** against pre-change RTL is impossible (nothing emits CFG1 yet), so this runs only post-change and is a **non-falsifiable row** — recorded as such rather than dressed up as a prediction. | |

**Required mutations, standalone and integration kill-sets recorded separately:**

| id | mutation | must be killed by |
|---|---|---|
| **M2.1** | `RQ_CFG_READ1 → TLP_CMD_CFG_READ0` (mis-decode) | F2.1 + an on-wire type check; a descriptor-only assertion will **not** catch it |
| **M2.2** | `desc_is_config` not set for the new arms (guard bypassed) | F1b.3's analogue at the RQ layer |
| **M2.3** | descriptor field aliased between the two type pairs | whole-word descriptor compare |
| **M2.4** | **`bad_poison` left as `desc_cmd == TLP_CMD_CFG_WRITE0`** | **F2.4** |

> **M2.4 is not contrived — it is the current state of the code.** `pcie_rq_if.sv:286`
> is written per-command while every other config check on that path is class-shaped
> (`RECON_stageD.md` §5). Adding `RQ_CFG_WRITE1` without touching `:286` is the natural
> mistake. Added to the brief's D-2 mutation list, which did not name it.

### §7.4 D-3 — the bridge sequencer

| id | new test | prediction | measured |
|---|---|---|---|
| **F3.1** | Full acceptance: bridge + device pair, all emitted TLPs asserted **in order** against goldens pinned before the RTL | no pre-change run is meaningful (the module does not exist); the falsifiable content is the **ordering**, per F3.2–F3.4 | |
| **F3.2** | The 18h write **precedes** the first CFG1 | falsifiable by construction: reorder the sequencer's two states and this must fail | |
| **F3.3** | Transaction #3 is Type **0**, not Type 1 (§5.4) | mutation: emit CfgWr1 for the bus-number write → bridge model answers **UR** → sequencer errors | |
| **F3.4** | Command-register enable is structurally last for the device | Stage C's assertion, re-run with the device addressed via CFG1 | |
| **F3.5** | **No-settle variants — mandatory.** Timeout and late-completion events are live under this FSM; brief §2.11's 2b-3 "no timer, null result" exemption does **not** carry over | | |
| **F3.6** | Acceptance run **twice**: credit-saturated, and under a Table 2-37 credit drip (`nph=1, npd=1`) | same TLP sequence, same order, both runs | |

---

## §8. Prospective traps

Written **before the tests exist** (brief §2.11 rule 9 / §5.8). Each names the vacuity
and the forcing move.

### §8.1 Trap A — the one-bit difference makes most assertions vacuous

**The vacuity.** CfgRd0 and CfgRd1 differ in exactly one bit of one Dword (§1). Any
on-wire assertion that compares DW1, DW2, byte enables, length, tag or payload — but
not `dw0[4:0]` — **passes identically for both types.** Most of the natural things to
assert about a config request are in this blind set.

**How it would happen.** `enum_tb_common.py:342` `cfg_wire_dw0(write, ...)` currently
hardcodes `TYPE_CFG0`. The path of least resistance for a new CFG1 test is to reuse it,
which silently asserts the *Type 0* golden — and then passes against a DUT that emitted
Type 0 when it should have emitted Type 1. The test would be not merely vacuous but
**actively wrong**, and it would go green.

**The forcing move.** Extend `cfg_wire_dw0(..., type1=False)` and
`assert_rq_descriptor(..., type1=False)` **before** writing any CFG1 test, so a Type 1
golden is expressible at all. Then, for every CFG1 assertion, apply the check:
*would this still pass if the DUT emitted Type 0?* If yes, it is not testing this
increment. At least one assertion per increment must compare the **whole DW0**, not a
field subset.

**Self-test for the trap itself:** point a CFG1 test at a CFG0 golden and confirm it
**fails**. A guard that has never been seen to fire is not known to work
(`RECON_stageD.md` §11 / brief §2.11).

### §8.2 Trap B — look-alike IDs and bus numbers collapse routing assertions into `0 == 0`

**The vacuity.** If the bridge and the device share a bus number, a Vendor ID, or a
Device ID, then every assertion of the form "this response came from the bridge, not
the device" degenerates. §5.3 makes this acute: **Device and Function are 0 on both
sides by construction, so the bus field is the only discriminator any routing assertion
has.** Collapse the bus numbers and there is nothing left.

**How it would happen.** Reusing `BDF = 0x0100` for both, or reaching for the existing
`VENDOR = 0x144D` / `DEVICE = 0xA80A` for the new device because they are already
imported.

**The forcing move.** §5.2's table — five pairwise-distinct values, none equal to a 2b
golden, bus numbers `1 / 5 / 9` chosen non-consecutive so that an off-by-one is
distinguishable from correct. Then apply brief §7's test to every assertion
individually: *would this still pass with all bus numbers equal?* If yes, it is vacuous.

**A specific instance worth pre-empting:** by §4.3, **Primary Bus Number drives no
routing decision on PCIe.** An assertion that varies only Primary Bus Number and claims
to prove routing is vacuous *even with distinct values* — the spec says nothing reads
it. Route-proving assertions must vary **Secondary**.

**A second instance, added 2026-07-31** (`MINDSHARE_CROSSCHECK_STAGE_D.md` C6; anchor
`[BASE]` §2.2.9 p.99 via P5.6). **The Completer ID is `0000h` at the bridge *and* at the
device, simultaneously, throughout the entire probe phase** — transactions #1, #2, #4 and
#5 all precede the first Type 0 Configuration Write to the Function they address. So in
the Completer ID specifically, the bus field is not merely a weak discriminator, it is
**identically zero on both sides exactly where a routing assertion would want it.**

> Trap B's own test — *"would this still pass with all bus numbers equal?"* — answers
> **yes** for any probe-phase Completer ID assertion. Such an assertion is vacuous **by
> construction**, not by an unlucky choice of constants, and no amount of forcing the
> §5.2 values apart repairs it. Routing must be proven from the **request** side (the
> emitted `dw0[4:0]` type and the DW2 bus number, §8.1) — not from the Completer ID of
> the response.

### §8.3 Trap C — assuming "the bridge phase uses Type 1"

**The vacuity.** The bus-number write (#3) targets the **bridge**, which sits on the
local bus, so it is Type **0** (§5.4). The name "bridge sequencer" invites the opposite
assumption, and a bench bridge model written to the same wrong assumption would
*accept* a CfgWr1 at 18h — making DUT and model wrong together, which no assertion
catches.

**The forcing move.** The bench bridge model must implement §3's table **literally**,
including case 3: a Type 1 request whose bus is outside `[Secondary, Subordinate]` gets
**UR**. At the moment of transaction #3, Secondary is still `00h`, so a wrongly-typed
CfgWr1 is *automatically* answered UR and the sequencer visibly errors. Writing the
model to the spec rather than to the expected trace makes this trap self-detecting —
which is the whole reason for the spec-golden-not-DUT-mirror rule (brief §2.6).

### §8.4 Trap D — the zero-latency bridge hides the ordering this stage exists to prove

**The vacuity.** Stage D's central claim is an **ordering** claim (§5.1: the bus-number
write precedes the first CFG1). A completer that answers in zero time can make a
wrong-order implementation look right, because there is no window in which the
out-of-order request is observable as such. Brief §2.11 already bans zero-latency
completer models; it bites harder here than anywhere in Stage C, because Stage C's
claims were mostly about *values* and Stage D's headline claim is about *time*.

**The forcing move.** Both the bridge model and the device model take non-zero,
**unequal** response latencies, and the acceptance test asserts the order of observed
TLPs on the wire rather than the order of model callbacks. Additionally: at least one
no-settle variant (F3.5) must stall the bus-number write's completion long enough that
a wrongly-ordered implementation would have already emitted the CFG1 probe — that is
the run which actually discriminates.

---

## §9. Baseline and invariants this stage must not move

From `RECON_stageD_baseline.txt`, measured cold at `f49d73d`:

- **36 targets / 258 tests, all PASS**, every `fusesoc` exit code 0.
- **Sim-time invariant:** `verilate_tlp_cpl_timeout_off` and
  `verilate_tlp_request_tracker` both end at **580.00 ns**, checked after every commit.
- Per-target counts and end times diffed **mechanically**, not eyeballed.
- Note the corrected split: `verilate_enum_bar` **32**, `verilate_enum_bar_tlp` **7**
  (the brief says 29/10; total 258 is unaffected — `RECON_stageD.md` §9).
- The two `_trace` targets are outside the gate.

Growth is by named new targets only, stated in decomposed form (brief §9).

---

## §10. Predictions this document deliberately does NOT make

Recorded so their absence is visible rather than looking like an oversight.

1. **Root-Port UR termination for device numbers 1–31.** Deferred (brief §8.1); a
   `$warning` tripwire ships instead. `[BASE]` §7.3.1 p.479 is the anchor for when it
   becomes required.
2. **Bridge memory/IO base-limit window programming.** Deferred (brief §8.2). Config
   traffic routes by bus number, so Stage D is unaffected; memory TLPs cannot reach
   behind the bridge until Stage E/F programs the windows.
3. **Recursion beyond one bridge level.** Stage E. Per `RECON_stageD.md` §11.2, the
   per-level-instance shape does **not** scale to a tree walk and must not be treated
   as load-bearing architecture.
4. **The RC's own target-side Type 1 register file.** Out of scope; CQ/CC stay tied
   off. `tlp_config_decoder.sv:15` already exposes `type_one_o` for whenever it lands.
5. **CRS Software Visibility** (§6.4) — no Root Control register exists.
6. **`tlp_cmd_e` widening** — D-1b fills it to 8 of 8 exactly; do **not** widen during
   Stage D (`RECON_stageD.md` §11.5).
7. **BAR sizing of the bridge's own two BARs** (10h/14h, P4.7). Not needed — the bridge
   requests no memory resources in this topology, and the memory/IO base-limit windows
   are already deferred (item 2). Recorded here because P4.7's trap is the *opposite*
   error: pointing a six-BAR Type 0 sizing sweep at the Type 1 header, which would
   overwrite 18h and destroy the bus-number assignment.
8. **Multi-function enumeration** (functions 1–7, of a bridge or otherwise) — out of
   scope, §4.5's scope clarification and §5.3.

---

## §11. Cross-check pass (added 2026-07-31)

`MINDSHARE_CROSSCHECK_STAGE_D.md` records a background cross-check of this document
against MindShare's *PCI Express Technology 3.0* (2012), chapters 3 and 4. **21 items:
9 resolved-confirmed, 10 resolved-rejected, 2 unresolved.**

Four items caused the edits above — **P4.5** (scope clarification), **P4.7**, **P5.6**
+ §8.2, and **P5.7** + §5.1's scoping. Each carries a `[BASE]` anchor located during
that pass; **no MindShare citation appears in this document**, per §0.1. No prediction
was falsified: the one apparent contradiction (MindShare's "Endpoints *ignore* Type 1
Requests") resolved **against** MindShare on a normative re-read, leaving P3.3's
UR requirement unchanged.

The two unresolved items — the meaning of `00h` in a Secondary Bus Number register at
reset, and whether a bridge may itself CRS a Type 1 request it cannot forward — are
recorded as open questions in that document and are **not** adopted here.
