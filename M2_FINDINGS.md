# M2_FINDINGS — the `attributes` DW0 placement

Stage M-2, on `kourosh/dev` alone. Nothing from `origin/main` entered the tree.

| commit | hash | content |
|---|---|---|
| predictions | `f611f9b` | `SPEC_PREDICTIONS_MERGE_M2.md`, before any RTL/bench/golden edit |
| placement fix | `b178ae0` | `tlp_generator.sv`, `tlp_parser.sv`, four standalone goldens |
| coverage | `029f5f9` | two new tests, three integration goldens, the RC shared model |
| anchor repair | `06afcd0` | 43 line-range citations → stable anchors, comment-only |
| findings | *this* | this file and the four gate records |

Base: `90b82f6` (M-1).

---

## §1 The normative placement, and which branch matched

### 1.1 Where the spec puts the bits

PCIe Base 2.1 §2.2.1 *Common Packet Header Fields*, **p.57**, field list and Figure 2-5:

> `Attr[1:0]` – Attributes – **bits [5:4] of byte 2**
> `Attr[2]` – Attribute – **bit 2 of byte 1**

§2.2.6.3 *Transaction Descriptor – Attributes Field*, **p.73**, Figure 2-14 names them —
and warns about the exact trap this stage is about:

> "Note that attribute bit 2 is **not adjacent** to bits 1 and 0."

| bit | name |
|---|---|
| `Attr[2]` | ID-Based Ordering (IDO) |
| `Attr[1]` | Relaxed Ordering (RO) |
| `Attr[0]` | No Snoop (NS) |

### 1.2 The byte→DW0 mapping, derived rather than assumed

A byte-and-bit position is meaningless until the header-byte→32-bit-word mapping is
fixed. It was derived from **eight non-attr fields that M-2 does not touch**, all
agreeing: `Fmt`, `Type` (byte 0), `TH`, `TC` (byte 1), `Length[9:8]`, `EP`, `TD`
(byte 2), `Length[7:0]` (byte 3). **Header byte *N* occupies `dw0[8N+7 : 8N]`** —
little-endian within the word. Zero dissent.

### 1.3 The result, and the verdict

| Attr bit | name | header byte, bit | **DW0 bit** |
|---|---|---|---|
| `Attr[2]` | IDO | byte 1, bit 2 | **`dw0[10]`** |
| `Attr[1]` | RO | byte 2, bit 5 | **`dw0[21]`** |
| `Attr[0]` | NS | byte 2, bit 4 | **`dw0[20]`** |

| | `dw0[10]` | `dw0[21]` | `dw0[20]` | matches? |
|---|---|---|---|---|
| **normative** | `attr[2]` | `attr[1]` | `attr[0]` | — |
| `kourosh/dev` at `90b82f6` | `attributes[0]` | `attributes[2]` | `attributes[1]` | **no** |
| `origin/main` | `attributes[2]` | `attributes[1]` | `attributes[0]` | **yes** |

**`origin/main` was spec-faithful; `kourosh/dev` was not.** M-0 asserted this; M-2
derived it from Base 2.1 independently, and the derivation is the authority. Stop
trigger §9.3 (neither branch matches) did not fire.

The derivation's own falsifier was recorded and holds: were the mapping big-endian,
`Attr[2]` would land at `dw0[18]` and `Attr[1:0]` at `dw0[13:12]` — positions this design
gives `address_type` and `traffic_class`. Those fields would then also be misplaced and
`verilate_tlp_conf_parser` would already be failing on TC and AT. It passes.

---

## §2 Conformance defect, not convention mismatch — the §0 question

**Verdict: conformance defect.** The tree *does* assign meaning to individual attribute
bits:

```systemverilog
// src/rc/pcie_rq_rc_pkg.sv:119   (rc_descriptor_t)
logic [2:0]  attr;               // [94:92] 92 No Snoop, 93 RO, 94 IDO
```

`attr[0]=NS`, `attr[1]=RO`, `attr[2]=IDO` — identical to PCIe `Attr[2:0]`. PG213 defines
the *request* descriptor, whose `attr` is the one that reaches the wire, the same way
(Table 60): *"Bit 124 is the No Snoop bit and bit-125 is the relaxed ordering bit. Bit
126 is the ID-Based ordering bit."*

That value flows to DW0 through **five hops, none permuting it**:
`desc.attr` → [pcie_rq_if.sv:472](src/rc/pcie_rq_if.sv#L472) → `pcie_rq_rc_top` →
`tlp_layer` → `tlp_requester` `attr_r` → `header_c.attributes` → generator DW0.

**So a PG213-conformant descriptor produced a non-conformant TLP, with all three bits
misplaced — not one renamed:**

| driver intends | `dev` put it at | a receiver reads that as |
|---|---|---|
| No Snoop | `dw0[10]` | **IDO** |
| Relaxed Ordering | `dw0[20]` | **No Snoop** |
| IDO | `dw0[21]` | **Relaxed Ordering** |

**Stop trigger §9.7 did not fire.** The naming comment at `pcie_rq_rc_pkg.sv:119` is
**byte-identical on both branches** — the two sides never disagreed about what the bits
mean, only about where `tlp_generator` puts them. That file differs between branches
only in unrelated line-number citations.

---

## §3 Predictions scored

| | prediction | verdict |
|---|---|---|
| **P1** | the normative placement table | **held** — derived from Base 2.1 §2.2.1 p.57 + §2.2.6.3 p.73 |
| **P2** | `main` correct, `dev` not | **held** |
| **P3a** | RTL alone reddens exactly one test | **held** — measured, see §4 |
| **P3b** | RTL + goldens ⇒ gate byte-identical | **held** — same md5 as the pre-gate |
| **P4** | the blind list, with a reason per entry | **held**, with one *correction* — see §6 |
| **P5** | round-trip cannot detect this | **held**, and mutation M4 demonstrates it |
| **P6** | mutation kills and their assertions | **held in substance, imprecise in detail** — see §5 |
| **P7** | the `enum_tb_common` correction is inert | **held** — all 305 pre-existing rows unmoved |

### Prediction errors, recorded rather than quietly fixed

1. **P3a cited the failing assertion at `test_tlp_generator.py:89`; it is `:91`.** The
   test, the assertion and the failure mode were right; the line number was off by two —
   itself another instance of the rot §7 is about.
2. **P1 §1.2 called it "six non-attr fields" in prose while its own table listed eight.**
   The conclusion is unaffected.
3. **P6 predicted M1's RO assertion would fire at `attr=2` and the NS assertion at
   `attr=1`.** In fact the RO assertion fires at `attr=1`: the loop tests `Attr[2]`,
   `Attr[1]`, `Attr[0]` in that order, so the first failing drive value reports the
   highest-indexed mismatched bit. Same kill, different reporting order.

No prediction was falsified in substance.

---

## §4 ⚠️ The counterfactual, and what it measured

The goldens are spec-derived, and the commit ordering is what makes that *checkable*
rather than merely claimed. The placement was committed in `f611f9b` before any file was
edited. The RTL was then corrected **with the goldens deliberately left alone**, and that
state was run on one target:

```
verilate_tlp_generator: TESTS=3 PASS=2 FAIL=1 SKIP=0
  test_tlp_generator.py:91 in request_headers_prefix_payload_digest_and_stalls
  assert result[1] == (expected_dw0(2, 0, 2, 3, 5, 1), 0xF, 0)
  AssertionError: assert (43004992, 15, 0) == (44053568, 15, 0)
```

Exactly one test, the predicted one, with the predicted assertion. Only then were the
goldens moved to the number already on disk.

**And the counterfactual measured something the reasoning had only argued:**

```
golden (dev placement)  = 0x02a03440   bit21=1 bit20=0 bit10=1
actual (spec placement) = 0x02903440   bit21=0 bit20=1 bit10=1
XOR = 0x00300000  ->  differing bits: [20, 21]
```

**`dw0[10]` is identical under both placements**, because the test drives `attr=5` and
`0b101` has bit 0 equal to bit 2. **The single test in the entire tree that could see
this defect was exercising two of its three misplaced bits.** That is the §7 one-hot
argument confirmed by measurement, and it is why the new coverage drives `{1,2,4}`.

---

## §5 The mutation gate

Five mutations, five kills, five bit-identical restores.

| # | mutation | file | killed by | assertion that fired |
|---|---|---|---|---|
| **M1** | `dw0[21:20] = {attr[0], attr[1]}` | generator | `rq_if_tlp` @`attr=1`; **also** `tlp_generator` @`attr=5` | `Attr[1] (RO) must be DW0 bit 21` |
| **M2** | IDO to `dw0[9]` | generator | `rq_if_tlp` @`attr=4` | `Attr[2] (IDO) must be DW0 bit 10` |
| **M3** | `dw0[10] = 1'b0` | generator | `rq_if_tlp` @`attr=4` | `Attr[2] (IDO) must be DW0 bit 10` |
| **M3b** | `dw0[21:20] = 2'b00` | generator | `rq_if_tlp` @`attr=1` | `Attr[0] (NS) must be DW0 bit 20` |
| **M4** | revert parser decode | **parser** | `rc_if_tlp` @`attr=1` | `RC descriptor Attributes 0b010 != 0b001` |

Every restore verified by md5 against the pre-mutation file.

**M4 was not in the brief's list.** The brief specifies three generator mutations; M-2
added a parser-direction test, and a test nobody has tried to break is a test whose
sensitivity is unknown. M4 reverts only the parser decode and is caught by `m2i2` — that
is the evidence `m2i2` is position-sensitive rather than vacuous.

**M2 was correctly *not* caught by `rc_if_tlp`.** It is a generator mutation and that
target drives a hand-built wire word into the parser. The two new tests cover opposite
directions and the non-overlap is the evidence that neither is redundant.

**A bench bug the DUT caught first.** The first `m2i1` drove a single-Dword write with
`last_be=0xF` and was rejected with `RQ_ERR_BE_MISMATCH`: the TL derives byte enables
from `address[1:0]` and the byte count and cannot reproduce a non-zero `last_be` on one
Dword. The descriptor was malformed — a bench defect surfaced by the wrapper's own
legality check, not a DUT defect. The reason is now a comment at the site.

---

## §6 The blindness account

**Blind before, and why.** Three distinct reasons, and the distinction matters because
only one is fixable by driving a different value:

| target(s) | reason | fixable by driving non-zero attr? |
|---|---|---|
| `verilate_rq_if` | attr is an RQ-descriptor field passed through; **no generator in the DUT**. Drove `attr=1,3,5` throughout. | no |
| `verilate_rc_if` | [tb_pcie_rc_if.sv:4](tb/rc/tb_pcie_rc_if.sv#L4): "No Transaction Layer in the loop"; attr is driven **as a struct field**. Drove `attr=2,4` and `randrange(0,8)`. | no |
| `verilate_tlp_completion_gen` | DUT has no `tlp_generator`. Drove `request_attr=5`. | no |
| **`rq_if_tlp`, `rc_if_tlp`, `rq_rc_top`** | **real `tlp_layer` in the loop**, golden carried the wrong placement, **every call site used `attr=0`** | **yes — this is what M-2 fixed** |
| `verilate_tlp_parser`, `_conf_parser`, `_conf_requester` | goldens wrong, all callers `attr=0` | goldens corrected in `b178ae0` |
| all `verilate_enum_*` | see below — **blind by spec** | **no, and must stay that way** |

**Now covered.** `test_m2i1_attr_bits_land_at_spec_wire_positions`
(`verilate_rq_if_tlp`) asserts the generator direction against absolute DW0 positions;
`m2i2_completion_attr_decodes_from_spec_wire_positions` (`verilate_rc_if_tlp`) asserts
the parser direction by walking a bit from a Base 2.1 wire position to a PG213 descriptor
bit. Both drive `{1,2,4,5,7}`; both are proven position-sensitive by §5.

`m2i2` deliberately does **not** use `cpl_dw0` — it assembles the completion DW0 from the
spec table directly, so stimulus and DUT share no helper and a helper wrong in the same
way as the RTL could not make it pass.

### ⚠️ Correction to P4: the `enum_*` targets are blind **by spec**, not by omission

P4 listed the enum targets as merely "called with `attr=0`". That is true but understates
it. **Base 2.1 §2.2.7 p.79:**

> Configuration Requests have the following restrictions:
> • `TC[2:0]` must be 000b • `TH` … reserved • **`Attr[2]` is reserved** •
> **`Attr[1:0]` must be 00b** • `AT[1:0]` must be 00b • `Length[9:0]` must be 1 …

The enumeration targets drive configuration requests exclusively, so **driving a non-zero
attr through `cfg_wire_dw0` would construct an illegal TLP.** They are attr-blind because
the spec forbids the alternative, and no coverage should ever be added there. Both helpers
now say so at the definition, so a later session does not "add coverage" by driving an
illegal value. `cpl_dw0` is the one that may legitimately carry attributes — a completion
echoes the request's — and that is the shape `m2i2` exercises.

This also satisfies the brief's §6 requirement to drive non-zero attr through an RC
integration path: `m2i2` does exactly that, on the only request class where it is legal.

**Still blind by design:** `verilate_rq_if`, `verilate_rc_if`,
`verilate_tlp_completion_gen` — none contains a generator or parser, so there is no DW0
for placement to be right or wrong in. Their non-zero attr values test field
pass-through, which is a different property and remains covered.

---

## §7 Incidental: line-range citation rot, and M-2's own contribution

M-1 §6 recorded nine stale bench citations of `tlp_cmd_e`'s line range. The class is
**much larger**: 32 `tlp_generator.sv` and 20 `tlp_parser.sv` line citations across `tb/`.

**And `b178ae0` staled more of them.** The eight-line spec comment added above the attr
assignment shifted every `tlp_generator.sv` citation to a line ≥66 by +8.

The anchor-repair commit therefore went beyond the mandated nine and converted **43
citations** to stable anchors — `tlp_generator.sv, the dw0 assembly` rather than a number
that stales on the next edit. Fixing nine while leaving 32 broken by this very stage
would have been worse than not touching them.

**Deliberately not swept: the 20 `tlp_parser.sv` citations.** M-2 made two in-place edits
to that file and moved no line numbers, so those citations are no more stale than they
were. A full anchor sweep is a hygiene brief, not a rider on a conformance change.

Verification that the repair was inert: **every changed `.py` file compared identical by
AST with docstrings stripped**, and every changed `.sv` line begins `//`. The gate is
byte-identical regardless.

---

## §8 The gates

| gate | commit | rows | md5 |
|---|---|---|---|
| `M2_gate_before.txt` | pre-change (`90b82f6`) | 347 | `6492c8ab8f7f0bd3ac533db6ddb3b0d3` |
| `M2_gate_fix.txt` | `b178ae0` | 347 | `6492c8ab8f7f0bd3ac533db6ddb3b0d3` |
| `M2_gate_cover.txt` | `029f5f9` | **349** | `a411e2317a2a6dd954225523ce3c9652` |
| `M2_gate_anchor.txt` | `06afcd0` | 349 | `a411e2317a2a6dd954225523ce3c9652` |

Two md5 pairs, and the boundary between them is the only commit meant to change what
the gate sees. The verdict commands:

```bash
diff M2_gate_before.txt M2_gate_fix.txt    && echo IDENTICAL   # placement fix: inert
diff M2_gate_cover.txt  M2_gate_anchor.txt && echo IDENTICAL   # anchor repair: inert
diff M2_gate_fix.txt    M2_gate_cover.txt                      # coverage: +2 rows only
```

The pre-gate also matched M-1's closing gate byte for byte, confirming nothing drifted
between stages.

**Per-step delta:**

- **before → fix: empty.** Placement is wiring; no sim time moves, and the one test that
  observes attr was corrected in lockstep with the RTL.
- **fix → cover:** exactly two new `T|` rows and the two `A|` count bumps that follow
  them. **All 305 pre-existing rows unmoved**, including every `enum_*` — the predicted
  evidence that the `enum_tb_common` correction is inert (P7), and the reason stop trigger
  §9.6 did not fire.
- **cover → anchor: empty.**

New baseline: **42 targets / 307 tests / 349 rows.** Zero Verilator diagnostics at every
step.

---

## §9 What M-2 does not establish

- **No hardware, no synthesis.** Nothing is measured on silicon or through a netlist.
  `SYNTH_FINDINGS_S1.md` / `S2.md` already described a netlist superseded by M-1; M-2
  supersedes it again and does not re-measure.
- **`origin/main`'s attr RTL remains unexecuted.** `RECON_MERGE.md` §4.1 found `main` has
  not compiled since `8386c16`. "`main` was correct" is a statement about its source
  text, never about its behaviour. M-2 vindicates `main`'s *reading* of the spec; it
  says nothing about `main`'s code working.
- **Only DW0 attr placement is in scope.** `TC`, `AT`, `TH`, `EP`, `TD` share the byte
  mapping and are asserted only incidentally by tests that already passed.
- **No device-control gating.** PG213 notes the core forces attribute bits to 0 when the
  corresponding attribute is not enabled in the Function's Device Control register.
  **Neither branch implements that**, and M-2 does not add it. The TL emits whatever the
  descriptor supplies.
- **The bits are still opaque everywhere except `pcie_rq_rc_pkg.sv:119`.** M-2 fixes
  placement; it introduces no per-bit named signals.
- **Coverage is at two targets, not three.** `verilate_rq_rc_top`'s golden was corrected
  but no non-zero-attr test was added there — its DW0 path is the same `tlp_layer`
  already covered by `rq_if_tlp`, so a third test would duplicate rather than extend. It
  remains blind, now with a correct golden.

---

## §10 Is M-3 unblocked?

**Yes, and one more file is now decided.**

`src/tlp/tlp_generator.sv` and `src/tlp/tlp_parser.sv` now hold the same *placement* as
`origin/main`. They are **not** textually "take theirs": `main`'s versions also carry the
message datapath (DW1/DW2/DW3 message packing, `tlp_is_message` length rules), which
M-2 deliberately did not import. The correct M-3 resolution for these two files is
**take ours, then port `main`'s message additions on top** — and with the attr question
closed, that port is now a pure message change with no placement question tangled into it.

Running tally of M-3's resolution, from `RECON_MERGE.md` §5 as amended by M-1 and M-2:

| file | resolution | settled by |
|---|---|---|
| `src/tlp/tlp_pkg.sv` | **take ours** — already the union | M-1 |
| `src/tlp/tlp_generator.sv` | **take ours**, port messages on top | M-2 |
| `src/tlp/tlp_parser.sv` | **take ours**, port messages on top | M-2 |
| `tlp_layer` / `pcie_endpoint_top` ports | **still open** — six ports, `PINMISSING` is fatal | — |
| `main`'s `test_pcie_endpoint_line_rate.py:32-33` | `CMD_MSG` 6/7 → **8/9** | M-1 |
| everything `main` contributes | **unexecuted; M-3a still required** | M-0 |
