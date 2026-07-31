# Stage D — D-0 Recon (read-only)

**Anchor:** `f49d73d` on `kourosh/dev`, `== origin/kourosh/dev`, tree clean at the time of
writing. Read-only: no RTL, no testbench, no `.core` touched by this commit.

**Environment:** `vlsi031.ece.uw.edu`, conda env `pcie`, Verilator 5.050 (rev
conda-forge build 0), cocotb 1.9.2, FuseSoC 2.4.6. `CPATH` verified set by the
`activate.d` hook to `$CONDA_PREFIX/include` — checked, not assumed.

**Baseline:** re-measured from a cold build (`rm -rf build/` first), 36 targets run
strictly sequentially. Result in §9.

Every claim below carries `file:line` evidence read at `f49d73d`. Claims inherited from
earlier recons are marked **[INHERITED]** and were re-verified; where re-verification
changed the answer, the superseded claim is marked, dated, and kept.

---

## 0. Headline findings

Six things here are load-bearing and were not known going in. Three of them change the
shape of a planned increment; two trip the brief's own stop-and-report triggers.

1. **R3 — `tlp_requester`'s config handling is NOT class-shaped.** It is five
   independent per-command OR-lists. The brief asked to "confirm the guard is written
   over an `is_cfg_or_io`-style class the new commands can join"; there is no such
   class on the TX side. **This is brief §10 stop trigger "the guard not class-shaped."**
   See §3. **Resolved by decision A (§11.1): D-1 splits into D-1a refactor + D-1b
   append.**
2. **R4 — `tlp_generator` needs no change at all.** The brief's premise that it "builds
   the config routing DW from Completer-ID BDF + register number" is **wrong at HEAD**:
   the generator is entirely type-agnostic and emits DW2 straight from
   `header.address[31:2]`. See §4.
3. **R1 — the RX side already accepts CFG1 completely, at HEAD.** The 2026-07-21
   pre-merge claim *holds*, re-verified in all four modules. D-1's RX scope is **zero**.
   See §1.
4. **`pcie_cfg_txn` hardcodes Type 0** (`:264`). The brief's D-3 rule "reuse
   `pcie_cfg_txn` … the primitive stays phase-blind" cannot hold unmodified: Type 0
   vs Type 1 is a per-transaction property and the primitive currently cannot express
   it. See §6.3.
5. **`pcie_enum_scan` and `pcie_enum_bar` cannot be re-armed without a reset.** Their
   terminal states self-loop by deliberate design with a stated rationale. D-3 step (3)
   as briefed — "run the existing scan/BAR policy against the device found there" —
   has no mechanism to run them a second time. See §6.4. **This is a structural
   blocker for D-3's briefed shape. Resolved by decision B (§11.2): per-level scan/BAR
   instances, the existing stages never re-armed.**
6. **R8 — the Type 1 layout IS normative on the shelf, but not in the file the brief
   named.** `pci-local-bus-3.0.txt` explicitly *defers* Header Type 01h to the
   PCI-to-PCI Bridge Architecture Specification, which is not on the shelf — the
   brief's ⚠️ was correct. However **PCIe Base 2.1 §7.5.3 Figure 7-6 p.492** defines
   the Type 1 header normatively, including the 18h Dword. The stop condition ("Type 1
   layout not normative on the shelf") therefore **does not fire**. See §8.

---

## 1. R1 — CFG1 acceptance on the RX side

**Verdict: already accepted, in all four modules, at `f49d73d`. Added D-1 scope: none.**

The 2026-07-21 claim was flagged in the brief as "pre-merge and five baselines old."
Re-verified module by module; it survives the merge intact.

| module | evidence at `f49d73d` | verdict |
|---|---|---|
| `tlp_validator` | `:17-19` `config_or_io` includes `TLP_TYPE_CFG1`; `:30-34` legal-type list includes it; `:37` forces 3DW for the config/IO class | accepts |
| `tlp_classifier` | `:38` arm is `TLP_TYPE_IO, TLP_TYPE_CFG0, TLP_TYPE_CFG1:`; `:39-40` asserts `config_request_o` for CFG1 | accepts, **not** in `default:` |
| `tlp_config_decoder` | `:15` already exposes a dedicated `type_one_o` output; `:17-18` `hit_o` covers both types | accepts, and already distinguishes |
| `tlp_parser` | `:198-199` address capture treats CFG1 symmetrically with CFG0 | accepts |

`TLP_TYPE_CFG1 = 5'b00101` has existed in `tlp_pkg.sv:21` all along — the *wire type*
enum is complete; only the *command* enum is not.

**Asymmetry worth recording:** the RX side is class-shaped (`tlp_validator.sv:17-19`
mints a `config_or_io` variable). The TX side is not (§3). The two sides of the same
behaviour were written to different standards.

---

## 2. R2 — the command enum tail

**Verdict: nothing already appended. Confirmed. Plus one finding the brief did not
anticipate.**

`tlp_pkg.sv:43-50`:

```systemverilog
typedef enum logic [2:0] {
  TLP_CMD_MEM_READ,  TLP_CMD_MEM_WRITE,
  TLP_CMD_CFG_READ0, TLP_CMD_CFG_WRITE0,
  TLP_CMD_IO_READ,   TLP_CMD_IO_WRITE
} tlp_cmd_e;
```

Six members, no CFG1, nothing appended. Append-only rule is satisfiable.

**The finding: `tlp_cmd_e` is `logic [2:0]` — capacity exactly 8.** Six members are
used. Appending `TLP_CMD_CFG_READ1` and `TLP_CMD_CFG_WRITE1` takes it to **8 of 8 —
completely full.** D-1 fits with zero bits to spare and needs no width change.

**Consequence, recorded for Stage E:** the *next* command appended after Stage D
requires widening `tlp_cmd_e` to `logic [3:0]`. That is not a local edit — the type
crosses module ports throughout the TL, so it is a wire-format change and, under the
append-only/positional-encoding rule (brief §2.3), it needs its own commit and its own
regression argument. Any Stage E plan that assumes "just append one more" is wrong.

---

## 3. R3 — the requester's CFG0 branch shape ⚠️ STOP TRIGGER

**Verdict: the datapath is shared, but there is no class to join. Config membership is
re-enumerated by hand in five independent places in `tlp_requester.sv`.**

| # | site | line | what it decides | failure if CFG1 omitted here |
|---|---|---|---|---|
| 1 | `command_limit()` | `:76-77` | 4-byte segment limit | CFG1 gets the `max_payload_bytes_i` limit (`:81`) → multi-DW segmentation of a config request |
| 2 | `command_has_data` | `:104-105` | CfgWr is a data command | CfgWr1 emits with a no-data fmt and no payload beat |
| 3 | `header_c.tlp_type` / `fmt` | `:116-118` | emits `TLP_TYPE_CFG0`, forces 3DW | **falls through to `:115` `header_c.tlp_type = TLP_TYPE_MEM`** — a CfgRd1 goes out as a Memory Read |
| 4 | `tag_expects_data_o` | `:142-143` | CfgRd expects a completion with data | CfgRd1's completion is not expected → tracker mismatch |
| 5 | admission guard | `:192-195` | `byte_count <= 4 − address[1:0]` | the one-DW invariant is simply **unenforced** for CFG1 |

The guard at `:192-195` is the brief's `bc <= 4 − address[1:0]` and it reads:

```systemverilog
if ((command_byte_count_i == 0 && command_i != TLP_CMD_MEM_READ) ||
    ((command_i == TLP_CMD_CFG_READ0 || command_i == TLP_CMD_CFG_WRITE0 ||
      command_i == TLP_CMD_IO_READ   || command_i == TLP_CMD_IO_WRITE) &&
     command_byte_count_i > (13'd4 - {11'd0, command_address_i[1:0]}))) begin
```

— a literal four-way OR, not a class predicate.

**Why this is a stop trigger and not just a chore.** Brief §10 lists "the guard not
class-shaped" explicitly. The practical consequence: D-1 is not "add a branch," it is
"extend five lists correctly," and **each of the five omissions is independently
plausible and independently silent.** Site 3 in particular fails *open* — a CFG1
request omitted there is transmitted as a well-formed Memory Read, which no existing
assertion would catch.

**Two ways forward (the brief does not choose between them; this needs a decision):**

- **(a) Extend the five lists in place.** Smallest diff, preserves every existing
  anchor and line number, keeps the commit purely additive. Cost: the five-way
  duplication is now ten-way, and Stage E inherits it.
- **(b) Refactor to a class first** (`is_cfg`, `is_cfg_or_io` functions), as a separate
  no-behaviour-change commit, then add CFG1 to the class. Cost: touches the requester's
  most-asserted lines, so "byte-identical where gated off" (brief §6, D-1 regression
  clause) becomes false for the refactor commit and must be argued by test result
  instead. Benefit: site 3's fail-open mode becomes structurally impossible, and it
  matches how the RX side is already written (§1).

Recommendation: **(b), split as D-1a (refactor, no behaviour change, full 36/258 must
be bit-for-bit identical in verdict and sim end time) and D-1b (append + CFG1)**. It
converts five silent-omission mutation targets into one, and the RX side is already
precedent for the shape. But this is a scope increase over the brief and is exactly the
kind of deviation §10 says to surface rather than absorb.

---

## 4. R4 — generator DW construction ⚠️ BRIEF PREMISE CORRECTED

**Verdict: `tlp_generator` requires no change for CFG1. The brief's description of it
is wrong at HEAD.**

The brief states the generator "builds the config routing DW from Completer-ID BDF +
register number (reported `:81-82`)." What `:81-82` actually does:

```systemverilog
dw2 = tlp_is_4dw(header_r.fmt) ? header_r.address[63:32]
                               : {header_r.address[31:2], 2'b00};
```

The generator never references `completer_id` for a request — `completer_id` appears
only at `:76`, in the *completion* DW1. The generator is **type-agnostic**: DW0's type
field is `dw0[4:0] = header_r.tlp_type` (`:64`), taken verbatim from whatever the
requester put there.

The BDF does reach the wire in DW2, but it is packed *upstream*: `pcie_rq_if.sv:262-268`
lays the descriptor's Completer ID into `desc_address[31:16]` precisely because that
packing is bit-identical to the config Dword layout. So the BDF travels through the TL
inside `header.address`, and the generator just emits it.

**Which header fields differ Type 0 vs Type 1: exactly one — `dw0[4:0]`**, the Type
field (`00100` → `00101`). Predicted by the brief, confirmed by construction here. The
existing bench comment at `enum_tb_common.py:335` describes this correctly and needs no
correction.

**Consequence:** D-1's RTL blast radius is `tlp_pkg.sv` (append 2) + `tlp_requester.sv`
(five sites). Nothing else in the TL.

---

## 5. R5 — RQ descriptor decode

**Verdict: clean. `1001`/`1011` are named and rejected, and do NOT alias to CFG0. No
stop trigger.**

`pcie_rq_rc_pkg.sv:63-79` names all sixteen req_type encodings, including:

```
RQ_CFG_READ0  = 4'b1000,  // -> TLP_CMD_CFG_READ0
RQ_CFG_READ1  = 4'b1001,  // reject -- Type 1 config is Commit 3
RQ_CFG_WRITE0 = 4'b1010,  // -> TLP_CMD_CFG_WRITE0
RQ_CFG_WRITE1 = 4'b1011,  // reject -- Type 1 config is Commit 3
```

They are *named but unmapped*: `pcie_rq_if.sv:240-248`'s `unique case (desc_type)` has
no arm for them, so they fall to `default: type_ok = 1'b0` (`:247`) → `bad_type`
(`:278`) → `RQ_ERR_REQ_TYPE` (`:309`). Rejection is by construction, and the enum
comment shows Stage D was anticipated here.

**The RQ side IS class-shaped** — `desc_is_config` (`:233`, set at `:245-246`) gates
the address assembly (`:262`), `bad_cfg_n` (`:280`), `bad_cfg_fit` (`:282`) and
`bad_at` (`:285`). So D-2 is genuinely two arms in the `unique case`.

**One exception, and it is a trap.** `bad_poison` at `:286` is written *per-command*,
not over the class:

```systemverilog
wire bad_poison = (desc_cmd == TLP_CMD_CFG_WRITE0) && desc.poisoned;
```

Adding `RQ_CFG_WRITE1` without extending `:286` admits a **poisoned CfgWr1**. This is
the D-2 analogue of §3's five-site problem, and it is a required mutation target
(brief §6, D-2 mutation list, which does not currently name it).

---

## 6. R6 — the enum seam, and three D-3 blockers

### 6.1 How the Type 1 exit works today

- Header Type is read as register 3 (`0x0C`): `pcie_enum_scan.sv:412`
  `cmd_reg_num = (state_r == S_HDR_CMD) ? CFG_REG_CACHE_HEADER : CFG_REG_VENDOR_DEVICE`,
  with `CFG_REG_CACHE_HEADER = 6'h03` (`pcie_enum_pkg.sv:66`).
- The byte is extracted at `:302` (`HDR_TYPE_LSB = 16`, `pcie_enum_pkg.sv:179`), masked
  to `[6:0]` at `:303`, compared against `HDR_LAYOUT_TYPE0 = 7'h00`
  (`pcie_enum_pkg.sv:199`) at `:304`.
- The gate is `:383`: `state_r <= hdr_is_type0 ? S_DONE : S_UNSUPPORTED;` — commented
  "A Type 1 header is a bridge or switch: a valid device that … Commit 2b cannot
  enumerate. Terminal, but NOT an error."
- The exit is surfaced as `unsupported_device_o` (`:430`) and counts as
  `scan_done_o` (`:424`).
- The handoff mux consumes it: `pcie_enum_bar.sv:440` starts the BAR phase only on
  `device_present_i && !unsupported_device_i`.

So D-3's trigger signal already exists and is already routed to the right place.

### 6.2 Where the probe's target bus number comes from

**It is a port, not a constant.** `pcie_enum_scan.sv:187` `input logic [7:0] scan_bus_i`,
used at `:420`:

```systemverilog
assign device_bdf_o = {scan_bus_i, 5'd0, 3'd0};
```

and exposed all the way up as `pcie_enum_top.sv:150` → `:258`. **This is the good
news of the recon:** D-3's bus-number state can drive `scan_bus_i` through a mux with
no rework of either the scan or the port list.

### 6.3 `pcie_cfg_txn` is hardwired to Type 0 ⚠️

`pcie_cfg_txn.sv:264` — the single site that names a request type:

```systemverilog
desc.req_type = write_r ? RQ_CFG_WRITE0 : RQ_CFG_READ0;
```

The brief's D-3 rule is "reuse `pcie_cfg_txn` as the only transaction primitive — the
sequencer applies policy, the primitive stays phase-blind." **Type 0 vs Type 1 is not
phase, it is a property of the individual transaction**, and the primitive has no way
to express it. D-3 (or D-2) must add a `cmd_type1_i` input:

```systemverilog
desc.req_type = write_r ? (cmd_type1_i ? RQ_CFG_WRITE1 : RQ_CFG_WRITE0)
                        : (cmd_type1_i ? RQ_CFG_READ1  : RQ_CFG_READ0);
```

This is a one-line change plus a port, and it keeps the primitive phase-blind in the
sense that matters (it does not know *who* is asking). But it is a change to the
primitive, which the brief assumed would not happen. It also means the new input must
join the handoff mux (§6.4), because different stages need different values of it.

### 6.4 The scan and BAR stages cannot be re-armed ⚠️ STRUCTURAL BLOCKER

D-3 step (3) is "hand the discovered device to the existing scan/BAR policy addressed
via CFG1." There is no mechanism to do this.

Both stages are single-shot by deliberate design:

- `pcie_enum_scan.sv:404-406` — `S_DONE: state_r <= S_DONE; S_UNSUPPORTED: state_r <=
  S_UNSUPPORTED; S_ERROR: state_r <= S_ERROR;` with the rationale at `:400-403`:
  *"Terminal states … hold until reset just as S_ERROR does: enumeration is single-shot
  after link-up, and a status surface that could be re-entered would let a consumer
  sample it mid-rescan."*
- `pcie_enum_bar.sv:640` — `S_DONE: state_r <= S_DONE;` likewise.

The only path back to `S_IDLE` is the reset branch (`pcie_enum_scan.sv:323`,
`pcie_enum_bar.sv:401`). `scan_start_i` (`:184`) and `bar_start_i` (`:213`) are
sampled **in `S_IDLE` only** — `pcie_enum_bar.sv:212` says so in a comment.

The rationale is real and was load-bearing: the status outputs are a
sample-anytime surface, and re-entering them would let a consumer read a stale or
mid-flight verdict.

**Three options, none free — this needs a decision before D-3 is written:**

- **(a) Add a re-arm input.** Smallest RTL, but it directly reverses a documented
  invariant, and every consumer of `scan_done_o` / `bar_done_o` / the status outputs
  must be re-audited for the mid-rescan sampling hazard the comment warns about. The
  no-settle test variants the brief mandates for D-3 become the *primary* risk area,
  not a checklist item.
- **(b) Second instances of scan and BAR**, one per bus level, each single-shot,
  selected by the handoff mux. Preserves the invariant exactly and keeps every existing
  assertion meaningful. Costs area (two more FSMs) and widens the mux from a 1-bit
  `bar_owns` select (`pcie_enum_top.sv:350`) to a 4-way. Honest about the topology: one
  bridge level = two bus levels = two scan/BAR pairs, and it makes the "no recursion"
  decision (brief §8.3) *structural* rather than a matter of restraint.
- **(c) Sequencer does its own probe.** Rejected — duplicates scan policy and violates
  the brief's reuse rule.

Recommendation: **(b)**. It is the only option that leaves the existing single-shot
invariant, and therefore the existing 36/258, untouched by construction.

### 6.5 The BDF is not muxed

`pcie_enum_top.sv:393` wires `cmd_bdf_i` directly to `device_bdf_o` for **every**
stage, deliberately (`:109-121`): *"The target BDF is a property of the device being
enumerated, not of the phase enumerating it."*

D-3 needs two different BDFs — the bridge (bus 0) and the device behind it
(secondary bus). Under option (b) above this stays consistent: each scan instance owns
its own bus level, so the BDF is still "a property of the device," and the mux selects
between two `device_bdf_o` sources rather than muxing a bus number into one. Under
option (a) the invariant has to be restated. Another reason to prefer (b).

---

## 7. R7 — completer scaffolding, sized

**Verdict: the bench models one device at one BDF and cannot tell CFG0 from CFG1. All
three gaps are in `enum_tb_common.py`; the four-name interface itself is fine to
extend.**

| capability | status at HEAD | evidence |
|---|---|---|
| two devices at two BDFs | **no** — a single module-level `BDF = 0x0100` (bus 1, dev 0, fn 0) and a single `Socket` with one request stream | `:654`, `:456-476` |
| CFG0 vs CFG1 on the wire | **no** — `cfg_wire_dw0()` hardcodes `TYPE_CFG0` into DW0 and takes no type argument | `:342-356` |
| CFG0 vs CFG1 in the descriptor | **no** — `assert_rq_descriptor()` hardcodes `RQ_CFG_WRITE0 if write else RQ_CFG_READ0` | `:195-208` |
| BDF-parameterised DW2 golden | **yes**, already `cfg_wire_dw2(bus, dev, fn, reg_num, ext_reg)` | `:330-339` |
| the four-name interface | `.start` / `.wait_for` / `.complete` present; `.seen` via `SocketRequest` | `:474`, `:487`, `:557`, `:437` |

**Bench work for D-3, sized:**

1. `cfg_wire_dw0(..., type1=False)` and `assert_rq_descriptor(..., type1=False)` — two
   signature extensions, default-false so every existing caller is unchanged. Small.
   These are also what makes trap 8a (an assertion that omits the Type field is
   vacuous) checkable at all — today it is *structurally* vacuous, because no golden
   can express Type 1.
2. A BDF-routing `Socket` — dispatch on DW2's bus field rather than answering
   everything. Moderate; the existing `TlpRequest` class already decodes bus/dev/fn
   (`:731`), so the routing key is in hand.
3. A spec-golden bridge model that performs the §7.3.3 Type1→Type0 transform. New, and
   the largest single piece. It must not be zero-latency (brief §2.11).

The `Socket` is explicitly documented as invariant-carrying and not to be forked
(`:408`, `:428`) — extend in place, consistent with brief §2.6.

---

## 8. R8 — spec shelf gate

**Verdict: PASS, via a different source than the brief specified. The brief's ⚠️ was
correct about `pci-local-bus-3.0.txt`; the stop condition does not fire because the
layout is normative elsewhere on the shelf.**

**The brief's named source defers.** `pci-local-bus-3.0.txt:10546-10549` (§6.1, PDF
p.213 — page markers are footers, so content after marker 213 is on p.214):

> "Currently three Header Types are defined, 00h which has the layout shown in
> Figure 6-1, **01h which is defined for PCI-to-PCI bridges and is documented in the
> PCI to PCI Bridge Architecture Specification**, and 02h which is defined for CardBus
> bridges…"

Figure 6-1 (`:10600-10620`) is the Type **00h** header — at offset 18h it shows *Base
Address Registers*, not bus numbers. The PCI-to-PCI Bridge Architecture Specification
is **not on the shelf** (full recursive listing of `/home/kourosh/openPCIE/0.doc`
checked; no bridge spec, and the four other PCI/PCIe PDFs are Base 2.1, Base 4.0
Rev 0.3 *draft*, CEM 3.0, and the PCI 3.0 PDF that matches the .txt).

**The layout is nonetheless normative on the shelf.** PCIe Base 2.1 §7.5.3, Figure 7-6,
p.492 ("Type 1 Configuration Space Header") gives the full register map for
"Switch and Root Complex virtual PCI Bridges" — which is exactly this project's
topology. Offset **18h**, most-significant byte first:

| bits | field |
|---|---|
| `[31:24]` | Secondary Latency Timer |
| `[23:16]` | Subordinate Bus Number |
| `[15:8]`  | Secondary Bus Number |
| `[7:0]`   | Primary Bus Number |

Two qualifications that matter for D-P, both from the same section:

- §7.5.3 p.492 scopes itself: *"Register interpretations described in this section
  apply to PCI-PCI Bridge structures representing Switch and Root Ports; other device
  Functions such as PCI Express to PCI/PCI-X Bridges … are not covered."* Our bench
  bridge is a virtual PCI bridge — in scope.
- §7.5.3.3 p.492: **Secondary Latency Timer "does not apply to PCI Express. It must be
  read-only and hardwired to 00h."** So the whole-Dword write at 18h (Stage C
  precedent, no read-modify-write) writes `[31:24]` to a byte the device must ignore.
  That is legal and expected — but it means the golden for a *read-back* of 18h must
  expect `[31:24] == 0x00` regardless of what was written. A test that writes
  `0xAA` there and asserts it reads back would be asserting a spec violation.
- §7.5.3.2 p.492: Primary Bus Number "is not used by PCI Express Functions but must be
  implemented as read-write for compatibility with legacy software."

**Base 2.1 gives layout but not the bus-number *semantics*** — there is no §7.5.3.x for
Secondary or Subordinate Bus Number. Those are established operationally elsewhere,
and both anchors are on the shelf:

- §7.3.3 p.480-481 "Configuration Request Routing Rules" — the Type1→Type0 transform
  and the forward-unmodified rule (§8.1 below).
- §6.12.1.1 p.435 — defines the aperture explicitly as *"the inclusive range specified
  by the Secondary Bus Number register and the Subordinate Bus Number register."*

**Recorded for D-P:** this substitution must be written into
`SPEC_PREDICTIONS_STAGE_D.md` as the source-of-record decision, with the PCI 3.0
deferral quoted, so no later session re-derives it or reaches for MindShare/Southwell.

### 8.1 Bonus: the routing anchors D-P needs, located

The brief asked to find the bus-number origination rule's own anchor and not to reuse
§7.3.1 p.479 by proximity. Located:

- **Bridge-side behaviour (Base 2.1 §7.3.3 p.480-481)** — for Root Ports/Switches, if
  Type is 1 and the Bus Number equals a Downstream Port's assigned bus,
  *"Transform the Request to Type 0 by changing the value in the Type[4:0] field of the
  Request (see Table 2-3) — **all other fields of the Request remain unchanged**"*; if
  merely within the range, *"Forward the Request to that Downstream Port interface
  without modification"*; else Unsupported Request. This is directly what the bench
  bridge model must implement, and the "all other fields unchanged" clause is the
  golden for trap 8a.
- **Originator-side rule — note the nuance.** Base 2.1 §7.3.3 does *not* state when the
  Root Complex chooses Type 0 vs Type 1; it says only *"Configuration Requests are
  initiated only by the Host Bridge"* and that RC-internal bus assignment "may be done
  in an implementation specific way." The crisp normative "must" is in **PCI 3.0
  §3.2.2.3.x, p.49** (`pci-local-bus-3.0.txt:2103-2104`): *"If the target of a
  configuration transaction resides on another bus (not the local bus), a Type 1
  configuration transaction must be used."* The bus-number-comparison mechanics
  (match → Type 0, within-subordinate-range → Type 1) are at
  `pci-local-bus-3.0.txt:2258-2265`, but that passage is inside an **IMPLEMENTATION
  NOTE** — non-normative. D-P must cite the normative p.49 sentence for the rule and
  may cite the implementation note only as corroboration.

§7.3.1 p.479 is confirmed as the anchor for the *device-number* rule only, exactly as
the brief warned — it is not the bus-number anchor.

---

## 9. Baseline — cold, re-measured at `f49d73d`

`rm -rf build/`, then 36 targets run strictly sequentially (parallel builds SIGSEGV).

**Result: 36 targets / 258 tests, all PASS, 0 FAIL, 0 SKIP, every `fusesoc` exit code 0.**
Matches the brief's baseline of record, in decomposed form:

| group | targets | tests |
|---|---:|---:|
| `tb_tlp` | 23 | 116 |
| `tb_rc` — RC surface (`axis_gearbox`, `rq_if`, `rq_if_tlp`, `rc_if`, `rc_if_tlp`, `rq_rc_top`) | 6 | 55 |
| `tb_rc` — enum (`enum_txn`, `enum_txn_tlp`, `enum_scan`, `enum_scan_tlp`, `enum_bar`, `enum_bar_tlp`) | 6 | 86 |
| `tb_ltssm_conformance` → `verilate_conformance` | 1 | 1 |
| **total** | **36** | **258** |

23 TLP + 6 RC = 29 targets / **171** tests, exactly as the brief states.

**One correction to the brief's decomposition** (the total is unaffected). The brief
gives `verilate_enum_bar` 29 and `verilate_enum_bar_tlp` 10. Measured:
**`verilate_enum_bar` 32 and `verilate_enum_bar_tlp` 7** — same sum, 39, different
split. The project's own `SPEC_PREDICTIONS_ENUM.md` §E.10 table also records 32 and 7,
so the measurement and the Stage C record agree and the brief's figure is the outlier.
Use 32/7 as the per-target gate; a later session diffing against 29/10 would chase a
phantom.

Per-target counts and sim end times are recorded in §9.1 as the mechanical diff base
for every later increment.

**Sim-time invariant: HOLDS.** `verilate_tlp_cpl_timeout_off` = **580.00 ns** and
`verilate_tlp_request_tracker` = **580.00 ns**, both to the ns.

The two `_trace` targets (`verilate_enum_bar_trace`, `verilate_enum_bar_tlp_trace`)
exist for debugging and are deliberately outside the gate, as established in
`SPEC_PREDICTIONS_ENUM.md` §E.10.

### 9.1 Per-target record

See `RECON_stageD_baseline.txt`, committed alongside this file: one line per target,
`target|rc|TESTS/PASS/FAIL/SKIP|sim end time`. Diff mechanically after every commit;
do not eyeball.

---

## 10. Consequences and deferrals recorded

Carried from brief §8, plus what this recon adds.

1. **Root-Port UR termination for devices 1–31: DEFERRED** (brief §8.1). Unchanged by
   this recon. The tripwire `$warning` in `pcie_rq_if` remains the shipped mitigation.
   Becomes **required** when an MMIO/firmware host or any sweep-capable requester
   exists — Base 2.1 §7.3.1 p.479.
2. **Bridge memory/IO base-limit window programming: DEFERRED** to Stage E/F (brief
   §8.2). Config traffic routes by bus number, so Stage D is unaffected. Memory BARs
   assigned behind the bridge are **not reachable by memory TLPs** until the windows
   are programmed; this must land before Stage F traffic crosses a bridge.
3. **One bridge level, no recursion** (brief §8.3). §6.4 option (b) would make this
   structural rather than a matter of restraint.
4. **NEW — `tlp_cmd_e` is full after Stage D** (§2). The next command append requires
   widening the type to `logic [3:0]`, a wire-format change across the TL. Stage E must
   budget a standalone commit for it. **Do not widen it during Stage D** — see §11.5.
5. **NEW — the RC's own target-side Type 1 register file remains out of scope**
   (brief §1); CQ/CC stay tied off. Note that `tlp_config_decoder.sv:15` already
   exposes `type_one_o` for whenever that lands — the decode is ready, the register
   file is not.
6. **NEW — `pcie_cfg_txn` gains a `cmd_type1_i` port** (§6.3). Recorded because it
   contradicts the brief's "the primitive stays untouched" premise; the primitive stays
   *phase-blind*, which is the property that actually mattered.

---

## 11. Decisions taken (2026-07-31)

Both were raised per brief §10 rather than absorbed, and both are now settled. They
amend the brief; the brief's §6 D-1 and D-3 shapes are superseded to this extent and
**not** deleted — see §11.3.

### 11.1 Decision A — D-1 splits into D-1a (refactor) + D-1b (append)

**Taken: refactor to a class first, then append.** Rejected: extending the five lists
in place.

Rationale of record: site 3's fail-open mode (an omitted CFG1 leaving the requester as
a well-formed Memory Read) is exactly the silent-wrong-TLP class this project keeps
finding; extending the lists in place would double the duplication and hand Stage E the
same shape.

- **D-1a** — introduce `is_cfg()` / `is_cfg_or_io()` helpers in `tlp_requester.sv` and
  route all five sites (§3) through them. **Zero behaviour change.** No `tlp_pkg`
  change in this commit.
- **D-1b** — append `TLP_CMD_CFG_READ1` / `TLP_CMD_CFG_WRITE1` to `tlp_cmd_e` and add
  them to the class. Because all five sites now call the same predicate, this is **one**
  mutation target instead of five.

**D-1a's gate — the inertness argument.** `tlp_requester.sv` is not gated off by a
parameter, so "byte-identical where the change is gated off" (brief §6) cannot apply.
The gate is instead the suite's own inertness argument, the same one that proved the
`pcie_enum_top` hoist: every test in the suite asserts against spec goldens, so an
unchanged PASS set *with identical sim end times* **is** an unchanged set of observed
values. Required for D-1a: full **36 targets / 258 tests** identical in verdict **and**
sim end time, diffed mechanically against `RECON_stageD_baseline.txt`. One commit,
landed before D-1b introduces anything behavioural.

### 11.2 Decision B — D-3 uses per-level scan/BAR instances

**Taken: a second scan+BAR pair, one per bus level, each still single-shot, behind a
widened handoff mux.** Rejected: adding a re-arm input.

Rationale of record: the re-arm option reverses a documented invariant whose
mid-rescan sampling rationale is real (`pcie_enum_scan.sv:400-403`), forces a re-audit
of every done/status consumer, and makes the no-settle variants the primary risk area —
too much destabilisation of the most recently proven modules for no structural gain.
Per-level instances keep 36/258 untouched by construction and make "one bridge level,
no recursion" (brief §8.3) structural rather than a matter of restraint.

Consequent shape:

- `pcie_cfg_txn` gains the **minimal per-transaction Type 0/1 select** (§6.3). It stays
  phase-blind — it does not learn *who* is asking — which is the property that mattered.
- `scan_bus_i` is already a port (§6.2), so the bus-number state drives it with **no
  port rework**.
- The mux at `pcie_enum_top.sv:350` widens from the 1-bit `bar_owns` select to a 4-way,
  and `cmd_type1_i` joins the muxed set (different stages need different values).

**⚠️ Caveat recorded so Stage E does not inherit a false premise.** *Neither* option
scales to the depth-first tree walk: Stage E needs **iteration**, and per-level
instances do not provide it — a two-level topology would want a third pair, and an
arbitrary tree wants none of this shape. The sequencing layer above `pcie_cfg_txn` is
therefore **expected to be redesigned at Stage E**, and the 4-way mux **must not be
treated as load-bearing architecture**. It is the low-risk shape for one bridge level,
chosen because it leaves the proven modules alone — not because it is the endpoint.
`pcie_cfg_txn` itself, being phase-blind, is expected to survive that redesign.

### 11.3 Amendments to the brief carried by these decisions

| brief clause | status | replacement |
|---|---|---|
| §6 D-1, one commit | **superseded**, not deleted | D-1a + D-1b (§11.1) |
| §6 D-1 "byte-identical where gated off" | **superseded** for D-1a | inertness argument: unchanged verdicts + identical sim end times (§11.1) |
| §6 D-3 "reuse `pcie_cfg_txn` … the primitive stays phase-blind" | **amended** | primitive gains `cmd_type1_i`; stays phase-blind in the sense that mattered (§6.3, §11.2) |
| §6 D-3 step (3) "run the existing scan/BAR policy" | **superseded** | per-level second instances; the existing stages are never re-armed (§6.4, §11.2) |
| §6 D-2 mutation list | **extended** | + "poison check not extended to `CFG_WRITE1`" (§11.4) |
| §4 R4 premise (generator builds the config DW from Completer ID) | **corrected** | generator is type-agnostic and needs no change (§4) |
| §4 R8 source (`pci-local-bus-3.0.txt`) | **substituted** | PCIe Base 2.1 §7.5.3 Fig 7-6 p.492 (§8) |
| baseline split `enum_bar` 29 / `enum_bar_tlp` 10 | **corrected** | 32 / 7; total 258 unchanged (§9) |

### 11.4 Required D-2 mutation, added by decision A's review

Brief §6's D-2 mutation list does not name it. **Required:** *"poison check not extended
to `TLP_CMD_CFG_WRITE1`"* — mutate by leaving `pcie_rq_if.sv:286` as
`desc_cmd == TLP_CMD_CFG_WRITE0`. The accompanying test must **catch an admitted
poisoned CfgWr1**; per brief §2.8 a survivor gets a new test, never a strengthened
assertion. Note this mutation is *already live* in the code today — `:286` is written
per-command while every other config check on that path is class-shaped (§5), so
adding `RQ_CFG_WRITE1` without touching `:286` is the natural mistake, not a contrived
one.

### 11.5 Stage E prerequisite — `tlp_cmd_e` saturation

Recorded here and flagged for the tracker. After D-1b, `tlp_cmd_e` holds **8 of 8**
values in its `logic [2:0]` width (§2). **Do not widen it now** — D-1b fits exactly.
The *next* command appended, at Stage E or later, requires widening to `logic [3:0]`,
which is a wire-format change across every TL port carrying the type and therefore
needs its own commit and its own regression argument under the append-only/positional
-encoding rule (brief §2.3). Any Stage E plan assuming "just append one more" is wrong.

---

## 12. State of `SPEC_PREDICTIONS_STAGE_D.md`

**Not written.** Decisions A and B are now settled, so it is unblocked: prediction
item 5 (bus-number assignment order) and item 7 (per-increment failure predictions)
follow decision B's shape, and the D-1 falsification set splits across D-1a (predicts
*no* change — the inertness argument) and D-1b (predicts new-test failures against
pre-change RTL). It is the first deliverable of the next session, and must land
**before** any DUT run of new tests, per brief §2.5.
