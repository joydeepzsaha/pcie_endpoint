# SPEC_PREDICTIONS_MERGE_M2 — the `attributes` DW0 placement

Written and committed **before any RTL, bench or golden edit exists**, at `90b82f6`, on
`kourosh/dev`. Every number a bench later asserts must be traceable to §1 of this file.

---

## §1 P1 — the normative placement (this *is* the golden)

### 1.1 Where the spec puts the bits

PCIe Base 2.1, §2.2.1 *Common Packet Header Fields*, **page 57** (PDF page 57), the
field list and Figure 2-5:

> `Attr[1:0]` – Attributes (see Section 2.2.6.3) – **bits [5:4] of byte 2**
> `Attr[2]` – Attribute (see Section 2.2.6.3) – **bit 2 of byte 1**

§2.2.6.3 *Transaction Descriptor – Attributes Field*, **page 73**, Figure 2-14, names
them, and warns about exactly the trap this stage is about:

> "Note that attribute bit 2 is **not adjacent** to bits 1 and 0."

| bit | name | citation |
|---|---|---|
| `Attr[2]` | **ID-Based Ordering (IDO)** | Base 2.1 §2.2.6.3 p.73, Fig 2-14 |
| `Attr[1]` | **Relaxed Ordering (RO)** | Base 2.1 §2.2.6.3 p.73, Fig 2-14 |
| `Attr[0]` | **No Snoop (NS)** | Base 2.1 §2.2.6.3 p.73, Fig 2-14 |

### 1.2 The byte→DW0 convention, derived from the code not assumed

A byte-and-bit position is meaningless until the header-byte→32-bit-word mapping is
fixed. This design's mapping is **derived from six non-attr fields**, which agree
unanimously and none of which M-2 touches:

| field | spec position (p.57) | this design | implies |
|---|---|---|---|
| `Fmt` | byte 0 bits 7:5 | `dw0[7:5]` ([tlp_generator.sv:63](../../src/tlp/tlp_generator.sv#L63)) | byte 0 = `dw0[7:0]` |
| `Type` | byte 0 bits 4:0 | `dw0[4:0]` ([:64](../../src/tlp/tlp_generator.sv#L64)) | byte 0 = `dw0[7:0]` |
| `TH` | byte 1 bit 0 | `dw0[8]` ([:65](../../src/tlp/tlp_generator.sv#L65)) | byte 1 = `dw0[15:8]` |
| `TC` | byte 1 bits 6:4 | `dw0[14:12]` ([:67](../../src/tlp/tlp_generator.sv#L67)) | byte 1 = `dw0[15:8]` |
| `Length[9:8]` | byte 2 bits 1:0 | `dw0[17:16]` ([:68](../../src/tlp/tlp_generator.sv#L68)) | byte 2 = `dw0[23:16]` |
| `EP` | byte 2 bit 6 | `dw0[22]` ([:71](../../src/tlp/tlp_generator.sv#L71)) | byte 2 = `dw0[23:16]` |
| `TD` | byte 2 bit 7 | `dw0[23]` ([:72](../../src/tlp/tlp_generator.sv#L72)) | byte 2 = `dw0[23:16]` |
| `Length[7:0]` | byte 3 bits 7:0 | `dw0[31:24]` ([:73](../../src/tlp/tlp_generator.sv#L73)) | byte 3 = `dw0[31:24]` |

**Convention: header byte *N* occupies `dw0[8N+7 : 8N]`** — little-endian byte order
within the word. Eight fields, zero dissent.

### 1.3 ⇒ The normative DW0 placement

| Attr bit | name | header byte, bit | **DW0 bit** | citation |
|---|---|---|---|---|
| `Attr[2]` | IDO | byte 1, bit 2 | **`dw0[10]`** | Base 2.1 §2.2.1 p.57 |
| `Attr[1]` | RO | byte 2, bit 5 | **`dw0[21]`** | Base 2.1 §2.2.1 p.57 |
| `Attr[0]` | NS | byte 2, bit 4 | **`dw0[20]`** | Base 2.1 §2.2.1 p.57 |

Encode form: `dw0[10] = attr[2]; dw0[21:20] = attr[1:0];`
Decode form: `attr <= {tdata[10], tdata[21:20]};`

**Every value written into a bench in §5 or §6 must be derivable from this table alone.**

---

## §2 P2 — which branch is correct

| | `dw0[10]` | `dw0[21]` | `dw0[20]` | matches §1.3? |
|---|---|---|---|---|
| **normative** | `attr[2]` | `attr[1]` | `attr[0]` | — |
| `kourosh/dev` HEAD ([tlp_generator.sv:66,70](../../src/tlp/tlp_generator.sv#L66)) | `attributes[0]` | `attributes[2]` | `attributes[1]` | **no** |
| `origin/main` (`tlp_generator.sv:68,72`) | `attributes[2]` | `attributes[1]` | `attributes[0]` | **yes** |

**Prediction: `origin/main` is spec-faithful and `kourosh/dev` is not.** M-0 asserted
this; §1 derives it independently from Base 2.1, and the derivation — not M-0 — is the
authority.

**Both branches are internally self-consistent.** `dev`'s parser decodes
`{tdata[21:20], tdata[10]}` ([tlp_parser.sv:125,146](../../src/tlp/tlp_parser.sv#L125)),
which is the exact inverse of its encoder. So `dev` round-trips perfectly while being
wrong on the wire. **A branch that is self-consistent but wrong passes every round-trip
test ever written** — that is the situation here, and P5 is about it.

**Falsifier for the derivation:** if the byte→DW0 mapping in §1.2 were big-endian
instead, `Attr[2]` would land at `dw0[8·2+2]=dw0[18]` and `Attr[1:0]` at `dw0[13:12]` —
positions this design assigns to `address_type` and `traffic_class`. Those two fields
would then also be misplaced, and `verilate_tlp_conf_parser` / `verilate_tlp_generator`
would already be failing on TC and AT. They pass, so the mapping is little-endian and
§1.3 stands.

---

## §3 The §0 question: defect or mismatch?

**Prediction: this is a conformance defect, not a convention mismatch.** The tree *does*
assign meaning to individual attribute bits, in one place:

```systemverilog
// src/rc/pcie_rq_rc_pkg.sv:119   (rc_descriptor_t)
logic [2:0]  attr;               // [94:92] 92 No Snoop, 93 RO, 94 IDO
```

so `attr[0]=NS`, `attr[1]=RO`, `attr[2]=IDO` — **identical to PCIe `Attr[2:0]`**.

PG213 defines the same for the *request* descriptor, whose `attr` field is the one that
reaches the wire ([pg213 line 3122](/home/kourosh/openPCIE/0.doc/pg213-pcie4-ultrascale-plus.md), Table 60):

> "Bit 124 is the No Snoop bit and bit-125 is the relaxed ordering bit. Bit 126 is the
> ID-Based ordering bit"

i.e. `rq_descriptor_t.attr[2:0]` = {IDO, RO, NS} = PCIe `Attr[2:0]`. That value flows to
DW0 **unmodified** through five hops, none of which permutes it:

`desc.attr` → [pcie_rq_if.sv:472](../../src/rc/pcie_rq_if.sv#L472) `command_attr_o` →
[pcie_rq_rc_top.sv:447,516](../../src/rc/pcie_rq_rc_top.sv#L447) →
[tlp_layer.sv:354](../../src/tlp/tlp_layer.sv#L354) →
[tlp_requester.sv:239](../../src/tlp/tlp_requester.sv#L239) `attr_r` → `header_c.attributes` →
generator DW0.

**So a PG213-conformant descriptor produces a non-conformant TLP today**, and all three
bits are wrong, not merely renamed:

| driver intends | `dev` puts it at | which the spec reads as |
|---|---|---|
| NS (`attr[0]`) | `dw0[10]` | **IDO** |
| RO (`attr[1]`) | `dw0[20]` | **NS** |
| IDO (`attr[2]`) | `dw0[21]` | **RO** |

**Stop trigger 7 does not fire.** The bit-naming comment at `pcie_rq_rc_pkg.sv:119` is
**byte-identical on both branches** — the two sides do not disagree about what the bits
mean, only about where `tlp_generator` puts them. That file differs between branches
only in unrelated line-number citations inside comments.

**Falsifier:** if `pcie_rq_rc_pkg.sv:119`'s comment turned out to be the only naming and
were itself wrong per PG213, this would collapse to a naming question. PG213 line 3463
(RC descriptor) and 3122 (RQ descriptor) both agree with it, so it is not.

---

## §4 P3 — the red list

Ten sites encode a DW0 attr placement. **All ten carry the `dev` convention**
`(attr & 1) << 10 | ((attr >> 1) & 3) << 20`:

| file | lines | class |
|---|---|---|
| [test_tlp_generator.py](../../tb/tlp/test_tlp_generator.py#L66) | 66-67 | standalone |
| [test_tlp_parser.py](../../tb/tlp/test_tlp_parser.py#L10) | 10-11 | standalone |
| [test_tlp_conf_requester.py](../../tb/tlp/test_tlp_conf_requester.py#L62) | 62,65 | standalone |
| [test_tlp_conf_parser.py](../../tb/tlp/test_tlp_conf_parser.py#L43) | 43,47 | standalone |
| [enum_tb_common.py](../../tb/rc/enum_tb_common.py#L368) | 368,370 (`cfg_wire_dw0`), 423,425 (`cpl_dw0`) | RC shared model |
| [test_pcie_rq_if_tlp.py](../../tb/rc/test_pcie_rq_if_tlp.py#L65) | 65,68 | integration |
| [test_pcie_rc_if_tlp.py](../../tb/rc/test_pcie_rc_if_tlp.py#L111) | 111,113 | integration |
| [test_pcie_rq_rc_top.py](../../tb/rc/test_pcie_rq_rc_top.py#L139) | 139,141 | integration |
| [test_tlp_end_to_end.py](../../tb/tlp/test_tlp_end_to_end.py#L143) | 143 (decode) | **orphan — in no target** |

**P3a — counterfactual red list (RTL changed, goldens left alone).** Exactly **one test
in one target**:

- `verilate_tlp_generator` :: `request_headers_prefix_payload_digest_and_stalls`
- Failure mode: [test_tlp_generator.py:89](../../tb/tlp/test_tlp_generator.py#L89) asserts
  `result[1] == (expected_dw0(2, 0, 2, 3, 5, 1), 0xF, 0)`. With `attr=5` (`3'b101`) the
  corrected RTL emits `dw0[21:20] = 2'b01`, the stale golden expects `2'b10`. **DW0
  mismatch, `0x00A2_...` vs `0x0022_...` in bits 21:20 only.**

This counterfactual will be **run and recorded**, on that single target, as the evidence
that the goldens are spec-derived rather than DUT-mirrored.

**P3b — actual gate delta after Commit 2 (RTL + standalone goldens together): EMPTY.**
`docs/gates/M2_gate_fix.txt` is predicted **byte-identical** to `docs/gates/M2_gate_before.txt`, md5 and all.
Attr placement is wiring, not timing: no sim time moves, no test changes status. The one
test that observes attr is corrected in lockstep, and the other three standalone goldens
are exercised only at `attr=0`, where both conventions produce the same zero bits.

**Anything else going red is a stop trigger** (§9.4), in either direction.

---

## §5 P4 — the blind list, and why each is blind

**Every target other than `verilate_tlp_generator` passes unchanged.** Three distinct
reasons, and the distinction matters because only one of them is fixable by driving a
different value:

| target(s) | why blind | fixable by driving non-zero attr? |
|---|---|---|
| `verilate_rq_if` | attr is an **RQ-descriptor field** at `[126:124]`, passed through by [pcie_rq_if.sv:472](../../src/rc/pcie_rq_if.sv#L472); no generator in the DUT. Drives `attr=1,3,5`. | **no** — no DW0 exists in this DUT |
| `verilate_rc_if` | [tb_pcie_rc_if.sv:4](../../tb/rc/tb_pcie_rc_if.sv#L4) states "No Transaction Layer in the loop"; [:55](../../tb/rc/tb_pcie_rc_if.sv#L55) drives `received_completion_header.attributes` **as a struct field**. Drives `attr=2,4` and `randrange(0,8)`. | **no** — no parser in the DUT |
| `verilate_tlp_completion_gen` | DUT is `tlp_completion_generator` + `tlp_control`; no `tlp_generator`. Drives `request_attr=5`. | **no** |
| **`verilate_rq_if_tlp`, `verilate_rc_if_tlp`, `verilate_rq_rc_top`** | **real `tlp_layer` in the loop**, golden carries the `dev` convention, **every call site uses `attr=0`** | **YES — this is what Commit 3 fixes** |
| `verilate_tlp_parser`, `verilate_tlp_conf_parser`, `verilate_tlp_conf_requester` | goldens carry `dev` convention but every caller uses the default `attr=0` | yes, but standalone; Commit 2 corrects the goldens |
| all `verilate_enum_*` | `cfg_wire_dw0` / `cpl_dw0` called with default `attr=0` throughout | Commit 3 corrects the model |
| `verilate_tlp_end_to_end` | **does not exist** — [test_tlp_end_to_end.py](../../tb/tlp/test_tlp_end_to_end.py) is in no `.core` target on either branch, despite holding the tree's most thorough attr sweep | n/a |

---

## §6 P5 — the round-trip trap

**Prediction: a generator→parser round-trip test cannot detect this defect, on either
branch, ever.**

`dev`'s decoder is the exact inverse of its encoder: encode `dw0[10]=a[0]`, decode
`a[0]=dw0[10]`. So `parse(generate(a)) == a` holds identically under both conventions.
The composition is the identity regardless of where the bits physically sit, so a
round-trip assertion has **zero** discriminating power over placement.

**What an assertion must look like instead — against absolute DW0 bit positions:**

```python
# spec-derived from P1 section 1.3; NOT read back from the DUT
assert (dw0 >> 10) & 1 == (attr >> 2) & 1, "Attr[2] (IDO) must be DW0 bit 10"
assert (dw0 >> 21) & 1 == (attr >> 1) & 1, "Attr[1] (RO)  must be DW0 bit 21"
assert (dw0 >> 20) & 1 == (attr >> 0) & 1, "Attr[0] (NS)  must be DW0 bit 20"
```

Equivalently, one comparison against a `dw0` built by a spec-placement helper — but the
helper must be the *spec* one, and it must not be the same function the DUT's output is
fed through.

---

## §7 The drive set — values that can prove something

**Fixed points.** A value `v` produces identical DW0 attr bits under both conventions iff
`v[2]=v[0]`, `v[1]=v[2]` and `v[0]=v[1]` — i.e. all three equal. **`attr=0` and
`attr=7` are fixed points and prove nothing.** Any test relying on either is vacuous.

**A single non-fixed value is also insufficient.** Take `attr=5` (`101`): bits 2 and 0
are set, bit 1 clear. Any mapping that sends the *pair* {2,0} to the same *pair* of
destinations yields identical DW0, however it permutes 2 against 0 between them. So
`attr=5` distinguishes `dev` from spec but cannot distinguish spec from the map
`{2→dw0[20], 1→dw0[21], 0→dw0[10]}`.

**The minimum determining set is the one-hot triple `{1, 2, 4}`.** Each isolates one
source bit, so the observed DW0 position *is* that bit's destination — three
observations pin the map completely, with no residual ambiguity:

| drive | spec DW0 attr bits set | `dev` DW0 attr bits set |
|---|---|---|
| `attr=4` (`100`, IDO) | **`dw0[10]`** | `dw0[21]` |
| `attr=2` (`010`, RO) | **`dw0[21]`** | `dw0[20]` |
| `attr=1` (`001`, NS) | **`dw0[20]`** | `dw0[10]` |

One-hot also detects non-permutation faults a rotation-only test would miss: a dropped
bit lights no position, a duplicated bit lights two, a stuck bit lights the wrong one.

**§6 drive list: `{1, 2, 4}` mandatory**, plus `5` for continuity with the existing
generator test, plus `7` **explicitly labelled a negative control that proves nothing**.

---

## §8 P6 — mutation predictions

Each mutation is applied to `tlp_generator.sv` alone, gated, then restored and verified
bit-identical.

| # | mutation | predicted killer | predicted assertion |
|---|---|---|---|
| **M1** | swap the two adjacent bits: `dw0[21:20] = {attr[0], attr[1]}` | new integration test at `attr=2` **and** `attr=1`; also `verilate_tlp_generator` at `attr=5` | `Attr[1] (RO) must be DW0 bit 21` fires at `attr=2`; `Attr[0] (NS) must be DW0 bit 20` fires at `attr=1` |
| **M2** | move the third bit to a neighbour: `dw0[9] = attr[2]` instead of `dw0[10]` | new integration test at `attr=4` | `Attr[2] (IDO) must be DW0 bit 10` fires — reads 0 at bit 10 |
| **M3** | tie attr to zero: `dw0[10]='0; dw0[21:20]='0` | new integration test at any of `{1,2,4}` | the corresponding `Attr[n]` assertion reads 0 where 1 expected |

**M1 is the mutation that matters.** It is invisible to `attr=0`, invisible to `attr=7`,
and invisible to any round-trip — it is the exact fault class §7 exists to catch. If M1
survives, the drive set or the assertion form is wrong.

**A survivor requires a new test, never a strengthened assertion.**

---

## §9 P7 — the `enum_tb_common.py` correction is inert

**Prediction: correcting `cfg_wire_dw0` and `cpl_dw0` changes no RC test outcome.** Every
caller of both helpers uses the default `attr=0`, where the two conventions agree
bit-for-bit.

Per stop trigger §9.6, if any RC test outcome *does* move, that means an RC path depends
on attr placement — contradicting the blindness account in §5 — and it is a design
finding to report, not an edit to absorb.

---

## §10 What these predictions do not cover

- **No hardware and no synthesis evidence.** Nothing here is measured on silicon or
  through a netlist; `SYNTH_FINDINGS_S1/S2.md` describe a netlist already superseded by
  M-1.
- **`origin/main`'s attr RTL remains unexecuted** regardless of which side §2 vindicates.
  `docs/recon/RECON_MERGE.md` §4.1 found `main` has not compiled since `8386c16`, so "main is
  correct" is a statement about its source text, never about its behaviour.
- **Only DW0 attr placement is in scope.** TC, AT, TH, EP, TD share the same byte
  mapping and are asserted only incidentally, by the tests that already pass.
- **The `attributes` field's three bits are still carried opaquely everywhere except
  `pcie_rq_rc_pkg.sv:119`.** M-2 fixes placement; it does not introduce per-bit named
  signals, and no device-control-register gating of the attributes is implemented on
  either branch.
