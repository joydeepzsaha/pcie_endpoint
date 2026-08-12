# RECON — Commit 2b-3 (BAR sizing / assignment / enable), Phase 0

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` @ `ffea7a4` (== `origin/kourosh/dev`, tree clean)
**Scope:** read-only. No RTL, no testbench, no `.core` changed. Nothing staged.

Discharges the five Phase-0 items in brief §2 and reports against the §12
stop-and-report triggers.

---

## 0. Headline

**No stop-and-report trigger fired.** All five items resolve cleanly and the
brief's structural decision (option (c), the hoist) is confirmed safe by
measurement rather than by inspection alone.

Four things worth reading before Commit A:

1. **Baseline reproduces exactly: 34 targets / 219 tests / 219 PASS / 0 FAIL.**
   Per-target table in §1. No drift from the brief.
2. **The hoist is behavior-neutral, and stronger than the brief assumed: *zero*
   tests reach into the `pcie_cfg_txn` instance hierarchically.** Both scan
   benches touch only shim-level ports. Expected Python diff for Commit B: **zero
   lines.** §3.
3. **Commit C is roughly half-done already.** `tb/rc/enum_tb_common.py` (565
   lines) exists and is imported by all four enum benches. What remains
   duplicated is precisely four helpers; §4 names them and flags the one that
   carries a real sim-time risk (`Mon`'s differing default `cycles`) together
   with the resolution that removes the risk.
4. **`SPEC_PREDICTIONS_ENUM.md` §4 already covers BAR sizing** under the
   `[PCI3-REF]` tag, and **it does not conflict with the brief's §E** — §E
   extends it and discharges its citations. Checked claim by claim in §6. One
   pre-existing decision (§E.4's ERROR-vs-warning question) is **already
   committed to ERROR** at `SPEC_PREDICTIONS_ENUM.md:329`; §E should carry that
   forward, not re-open it.

---

## 1. Measured baseline at `ffea7a4`

Run sequentially, one FuseSoC target at a time (parallel Verilator builds
SIGSEGV — inherited constraint, `RECON_commit2b.md:46`). All 34 exited `rc=0`.

Target enumeration is authoritative, from `fusesoc core show`: `tb_tlp` 23,
`tb_rc` 10, `tb_ltssm_conformance` 1 (`verilate_conformance` only — the
deliberate regression control; the other three `tb_ltssm_conformance` targets
and all `tb_ltssm`/PHY targets stay out, per `RECON_commit2b.md:43-51`).

| target | TESTS | PASS | FAIL | sim ns |
|---|---:|---:|---:|---:|
| `verilate_axis_gearbox` | 11 | 11 | 0 | 195768.01 |
| `verilate_conformance` | 1 | 1 | 0 | 6010.00 |
| `verilate_enum_scan` | 16 | 16 | 0 | 6712.02 |
| `verilate_enum_scan_tlp` | 8 | 8 | 0 | 67840.01 |
| `verilate_enum_txn` | 14 | 14 | 0 | 3652.01 |
| `verilate_enum_txn_tlp` | 9 | 9 | 0 | 39168.01 |
| `verilate_rc_if` | 11 | 11 | 0 | 14620.01 |
| `verilate_rc_if_tlp` | 4 | 4 | 0 | 1028.00 |
| `verilate_rq_if` | 11 | 11 | 0 | 9992.01 |
| `verilate_rq_if_tlp` | 9 | 9 | 0 | 8800.01 |
| `verilate_rq_rc_top` | 9 | 9 | 0 | 53860.01 |
| `verilate_tlp_cfg0_spine` | 2 | 2 | 0 | 550.00 |
| `verilate_tlp_comb` | 3 | 3 | 0 | 108.00 |
| `verilate_tlp_compile` | 4 | 4 | 0 | 690.00 |
| `verilate_tlp_completion_gen` | 2 | 2 | 0 | 890.00 |
| `verilate_tlp_conf_cfgbe` | 7 | 7 | 0 | 21070.01 |
| `verilate_tlp_conf_classifier` | 11 | 11 | 0 | 36.01 |
| `verilate_tlp_conf_completion` | 6 | 6 | 0 | 1580.01 |
| `verilate_tlp_conf_datalast` | 5 | 5 | 0 | 2820.01 |
| `verilate_tlp_conf_formatter` | 4 | 4 | 0 | 610.00 |
| `verilate_tlp_conf_generator` | 2 | 2 | 0 | 340.00 |
| `verilate_tlp_conf_parser` | 12 | 12 | 0 | 1900.01 |
| `verilate_tlp_conf_requester` | 10 | 10 | 0 | 3910.01 |
| `verilate_tlp_conf_tracker` | 7 | 7 | 0 | 4140.01 |
| `verilate_tlp_cpl_timeout` | 5 | 5 | 0 | 6770.02 |
| `verilate_tlp_cpl_timeout_default` | 1 | 1 | 0 | 41390.00 |
| `verilate_tlp_cpl_timeout_off` | 2 | 2 | 0 | 580.00 |
| `verilate_tlp_credit_integration` | 2 | 2 | 0 | 1510.00 |
| `verilate_tlp_credit_manager` | 18 | 18 | 0 | 21220.05 |
| `verilate_tlp_generator` | 3 | 3 | 0 | 490.00 |
| `verilate_tlp_parser` | 3 | 3 | 0 | 860.00 |
| `verilate_tlp_payload_formatter` | 2 | 2 | 0 | 5230.00 |
| `verilate_tlp_request_tracker` | 2 | 2 | 0 | 580.00 |
| `verilate_tlp_requester` | 3 | 3 | 0 | 760.00 |
| **TOTAL** | **219** | **219** | **0** | |

**34 targets / 219 tests, all PASS.** Decomposed: 29 targets/171 tests
(23 TLP + 6 RC) + `verilate_conformance` 1/1 = 30/172, **plus** `enum_txn` 14 +
`enum_txn_tlp` 9 + `enum_scan` 16 + `enum_scan_tlp` 8 = 34/219. Matches the
brief in count and verdict.

Sweep harness: `scratchpad/sweep.sh`, sim-end times parsed from each target's
cocotb `TESTS=/PASS=/FAIL=` summary line. This is the reference table every
later gate compares against.

---

## 2. ⚠️ A method note: the first duplication diff I ran was vacuous

Recorded because it is the same failure shape the brief keeps warning about, and
it fired here on the recon itself.

My first pass at §4's duplication inventory used
`awk '/^class Mon[:(]/,/^[a-zA-Z#@]/'` to slice each class out of both files and
diffed the slices. All three reported **IDENTICAL**. They were identical because
the extraction returned **one line each** — the `class` header — and the range
end pattern matched immediately. A test comparing two empty strings passes.

Caught by checking `wc -l` on the extracted slices before trusting the verdict.
Redone with a real indentation-aware block splitter; the corrected result (§4)
is that **none** of the three are identical.

**Generalization for the Commit-D/E mutation work:** the brief's "check the new
test reaches the mutated *condition*, not just the mutated line" rule has a
sibling — *check the comparison had operands*. A green diff, an empty finding
list, and a passing assertion over an empty set are the same bug.

---

## 3. Item 1 & 2 — the hoist is behavior-neutral, with zero bench reach-in

### 3.1 Current instantiation

`pcie_enum_scan.sv:215-264` instantiates exactly one `pcie_cfg_txn` as `u_txn`,
passing all six parameters straight through and wiring:

| group | signals | after the hoist |
|---|---|---|
| clock/reset | `clk_i`, `rst_i` | stay |
| command port | `cmd_valid_i`, `cmd_ready_o`, `cmd_write_i`, `cmd_bdf_i`, `cmd_reg_num_i`, `cmd_ext_reg_i`, `cmd_first_be_i`, `cmd_wdata_i` | become `pcie_enum_scan` **ports** |
| response port | `rsp_valid_o`, `rsp_ready_i`, `rsp_outcome_o`, `rsp_rdata_o` | become `pcie_enum_scan` **ports** |
| unused response | `rsp_status_raw_o`, `crs_retries_o` | left unconnected at `pcie_enum_top` (unchanged intent, `:243-244`) |
| RQ AXIS (6) | `s_axis_rq_*` | **leave `pcie_enum_scan` entirely** — pure pass-through today (`:246-251`) |
| tag (2) | `pcie_rq_tag_i`, `pcie_rq_tag_vld_i` | **leave entirely** — pass-through (`:253-254`) |
| RC AXIS (5) | `m_axis_rc_*` | **leave entirely** — pass-through (`:256-260`) |
| timeout sideband (2) | `cpl_timeout_valid_i`, `cpl_timeout_tag_i` | **leave entirely** — pass-through (`:262-263`) |

**Confirmed behavior-neutral — measured, not eyeballed.** The 15 socket signals
in the bottom four rows are declared on `pcie_enum_scan`'s port list but appear
in *no expression anywhere in the module*. Each signal was counted individually;
**all 15 occur exactly twice** — once in the port declaration, once in the
`u_txn` connection — with no third reference:

| signal | decl | `u_txn` conn | other refs |
|---|---:|---:|---:|
| `s_axis_rq_tdata_o` / `tkeep_o` / `tvalid_o` / `tlast_o` / `tuser_o` | 181-185 | 246-250 | **0** |
| `s_axis_rq_tready_i` | 186 | 251 | **0** |
| `pcie_rq_tag_i` / `pcie_rq_tag_vld_i` | 188-189 | 253-254 | **0** |
| `m_axis_rc_tdata_i` / `tkeep_i` / `tvalid_i` / `tlast_i` | 191-194 | 256-259 | **0** |
| `m_axis_rc_tready_o` | 195 | 260 | **0** |
| `cpl_timeout_valid_i` / `cpl_timeout_tag_i` | 197-198 | 262-263 | **0** |

`pcie_rq_tag_i` having exactly zero other references independently re-confirms the
module header's standing claim that it never observes the tag
(`pcie_enum_scan.sv:94`) — the Finding-1 discipline the BAR module must inherit.
Moving these 15 up one level is a pure re-parenting.

The two signals that *are* consumed locally stay put:
- `tx_fc_blocked_i` — annotation, read at `:357` and `:385`.
- `scan_bus_i` — drives `device_bdf_o` at `:412`, which is itself the source of
  `cmd_bdf_i`. After the hoist `device_bdf_o` remains an output *and* becomes the
  `cmd_bdf_o` source; no logic change.

**No behavioral edit is required. The brief's Phase-0 gate is satisfied and the
hoist may proceed.**

### 3.2 Item 2 — which tests can the hoist break? **None.**

Searched both scan benches and both scan Python files for dotted paths into the
primitive:

- `tb_pcie_enum_scan.sv` — instantiates `pcie_enum_scan` as `dut` with a **flat
  port map**; no reference to `u_txn`.
- `tb_pcie_enum_scan_tlp.sv` — same, instance named `u_scan`; no reference to
  `u_txn`.
- `test_pcie_enum_scan.py` — every access is `dut.<port>`; the deepest is
  `dut.scan_error_code_o`. No two-level path.
- `test_pcie_enum_scan_tlp.py` — same; deepest is `dut.fc_cpld_i`.

**Zero tests reach into `pcie_cfg_txn`.** The brief anticipated a list of tests
whose hierarchical paths would need updating; the list is empty.

**Consequence — the Commit B gate is sharper than the brief specifies.** Since
every Python access is to a shim-level port, and the shims will keep their port
lists byte-identical while swapping the instantiated module from
`pcie_enum_scan` to `pcie_enum_top`, the expected diff for Commit B is:

- `src/rc/pcie_enum_scan.sv` — instance removed, 12 ports added
- `src/rc/pcie_enum_top.sv` — new
- `src/rc/rc_core.core` — one file added to the `rtl` fileset
- `tb/rc/tb_pcie_enum_scan.sv`, `tb_pcie_enum_scan_tlp.sv` — **module name on one
  line each**
- **`test_pcie_enum_scan.py`, `test_pcie_enum_scan_tlp.py` — zero lines**

Any Python change at all during Commit B is a signal the hoist went wrong.

---

## 4. Item 3 — the owed bench consolidation, inventoried

### 4.1 What is already shared

`tb/rc/enum_tb_common.py` (565 lines) exists and is imported by **all four**
enum benches (`test_pcie_enum_txn.py:29`, `test_pcie_enum_scan.py:34`,
`test_pcie_enum_txn_tlp.py:42`, `test_pcie_enum_scan_tlp.py:36`). It already
holds: the encoding constants, `rq_desc`/`decode_rq_desc`/`tuser`/`decode_tuser`,
`assert_rq_descriptor`, `encode_rc_desc`/`decode_rc_desc`, `rc_beats`,
`packet_dwords`/`split_packet`, the `cfg_wire_dw*`/`cpl_dw*` header builders,
and `SocketRequest`/`Socket`.

So the 2b-2 debt is **partly discharged already**. What follows is the remainder.

### 4.2 What is still duplicated between the two `_tlp` files

Measured with an indentation-aware block splitter (see §2 — the naive version
lied):

| symbol | txn lines | scan lines | verdict | consolidates? |
|---|---:|---:|---|---|
| `set_credits` | 7 | 7 | **IDENTICAL** | ✅ trivially |
| `settle` | 3 | 3 | **IDENTICAL** | ✅ trivially |
| `TlpRequest` | 23 | 21 | differs | ✅ as a **union** |
| `CreditDrip` | 45 | 34 | differs | ✅ as a **union** |
| `Mon` | 83 | 78 | differs | ✅ ⚠️ **see §4.3** |
| `assert_on_wire` | 20 | 20 | differs | ✅ as a **generalization** |

Detail on the four that differ:

- **`TlpRequest`** — same decoder, different *field subsets*. txn extracts
  `tlp_type` and `ext_reg`; scan extracts `bus`/`dev`/`fn` instead (it needs them
  for the device-0 assertion). Union of both field sets is strictly additive and
  changes no existing behavior. **Commit D needs the union anyway** — the BAR
  bench asserts on writes (`tlp_type`) *and* on BDF.
- **`CreditDrip`** — identical arithmetic; txn additionally has `stop()` and the
  `_run_flag` guard, which scan dropped. Keep the txn (superset) version; scan
  simply never calls `stop()`. The rest of the diff is a trimmed docstring.
- **`assert_on_wire`** — the scan version *is* the txn version with `write=False`
  and `first_be=CFG_BE_DWORD` hardcoded, plus a trailing device-0/function-0
  assertion. Generalizes to one function with those as defaulted keyword args and
  the device-0 check opt-out-able. **The per-bench constants are not an
  obstacle:** `RID = 0x1234`, `BDF = 0x0100`, `BUS, DEV, FN = 0x01, 0x00, 0x00`
  and `CPL_TIMEOUT_CYCLES = 4096` are **identical in both files**
  (`test_pcie_enum_txn_tlp.py:56-60`, `test_pcie_enum_scan_tlp.py:45-50`), so
  they move into the shared module as-is.

### 4.3 ⚠️ The one real risk — and why it is removable

`Mon` differs in exactly two load-bearing places, both **default timeout bounds**:

| method | txn default | scan default |
|---|---|---|
| `wait_timeouts` | `CPL_TIMEOUT_CYCLES + 600` | `CPL_TIMEOUT_CYCLES + 900` |
| `wait_lates` | `400` | `600` |

The rest of the `Mon` diff is docstring and string-continuation formatting.

Brief §5 makes "consolidation changes any observed timing" a stop-and-report
trigger. Here is why this particular difference **cannot** move a sim end time,
and what discipline keeps it that way:

Both methods are **early-exit polling loops**: they `return` on the cycle the
expected count is reached, and `raise AssertionError` only if the loop is
exhausted. Exhaustion is a *failure*, never a normal path. Since all 17 `_tlp`
tests currently PASS, **every one of the 8 call sites returns early**, and the
`cycles` default is a pure upper bound that is never reached.

Therefore:

> **Unify the defaults UPWARD — `CPL_TIMEOUT_CYCLES + 900` and `600`.** Raising a
> bound that is never reached cannot change the cycle any call returns on, so
> every sim end time is preserved by construction.

Unifying *downward* (to `+600`/`400`) would be unsafe in exactly one direction:
if any scan call site genuinely needs more than 400/600 cycles it would turn a
PASS into a FAIL. Upward has no such failure mode. The asymmetry is the whole
argument — it is not a coin flip.

Of the 8 call sites, 7 use the default and one passes an explicit
`cycles=CPL_TIMEOUT_CYCLES + 800` (`test_pcie_enum_txn_tlp.py:927`), which is
unaffected by a default change.

### 4.4 What is genuinely per-bench — do not consolidate

| symbol | why it stays |
|---|---|
| `init` | 36-line diff and **different signatures**: txn takes `credits`/`fc_init`; scan takes `space`/`crs_once`/`silent_regs`. Different DUT port sets. |
| `ConfigCompleter` (txn) vs `ConfigSpaceCompleter` (scan) | Genuinely different models — txn answers one transaction under bench control; scan serves a register-space dict with a UR default arm. **Both already expose the four-name interface** (`.start` / `.seen` / `.wait_for` / `.complete`), which brief §5 requires be preserved verbatim. Consolidate the *interface contract* in the EP model spec (Commit F), not the implementations. |
| `send_cmd` / `recv_rsp` / `outcome_name` (txn only) | Primitive-level command port; no scan analogue. |
| `reg3` / `start_scan` / `wait_terminal` / `status` (scan only) | Scan status surface; no txn analogue. |
| the `i*` / `k*` test bodies | The tests themselves. |

**A third completer is coming in Commit D** (BAR write-mask semantics). It should
be a third implementation of the same four-name interface, not a fourth copy of
the surrounding scaffolding.

---

## 5. Item 4 — PCI 3.0 line anchors, verified

All six anchors in brief §2.4 **verified correct** against
`/home/kourosh/openPCIE/0.doc/pci-local-bus-3.0.txt` (16433 lines).

⚠️ **Page-number derivation correction.** The page number in this extraction is a
**footer** — it appears at the *end* of the page it labels, immediately before
the `^L` form feed. Content following marker *N* is therefore on page ***N+1***.
My first mapping read the markers as headers and came out one page low
throughout. Corrected below and cross-checked against two independent internal
consistency points (markers 226 at `:11248` and 227 at `:11299` bracket
`:11283`; the brief's own "§6.2.5.1 p.225-226" matches the corrected mapping and
not the uncorrected one).

| what | line | **page** | first line of quoted text |
|---|---:|---:|---|
| Header Type description | `:10685` | **216** | "Header Type — This byte identifies the layout of the second part of the predefined header…" |
| Table 6-1: Command Register Bits | `:10759` | **218** | table caption; bit 0 begins `:10761` |
| §6.2.5.1 Address Maps | `:11134` | **225** | "Power-up software needs to build a consistent address map…" |
| Table 6-4 reference / prefetch text | `:11192` | **225** | "Address registers, bits 2 and 1 have an encoded meaning as shown in Table 6-4. Bit 3 should be set to 1 if the data is prefetchable…" |
| Table 6-4: Bits 2/1 Encoding | `:11207` | **226** | table caption; `00` row at `:11209` |
| §6.2.5.2 Expansion ROM BAR | `:11283` | **227** | "Some PCI devices, especially those that are intended for use on add-in cards…" |

**Two bonus anchors found that §E should use directly:**

- **`:11202` (page 226) — "Bits 0-3 are read-only."** This is the literal
  normative sentence behind §E.1's "bits 3:0 read-only" claim and behind §E.2's
  `mask = ~4'hF`. Worth citing verbatim rather than paraphrasing; it is the
  single load-bearing sentence for the whole sizing algorithm.
- **`:10761`–`:10769` (page 218) — Table 6-1 bits 0, 1 and 2**, each ending
  "**State after RST# is 0.**" This directly proves §E.5's ordering premise for
  *all three* bits §E.6 cares about. Note the brief's §E.6 says to cite Base 2.1
  Table 7-3 for bit 2 "which Base does define" — that remains a fine
  cross-check, but **PCI 3.0 Table 6-1 covers bit 2 too**, including its reset
  state, so §E.5/§E.6 need not lean on Base for it.

---

## 6. Conflict check against `SPEC_PREDICTIONS_ENUM.md` @ HEAD

The golden doc **already has a §4 "BAR sizing and assignment"** (lines 307-399),
written under `[PCI3-REF]`. Brief §12 makes a conflict with the golden doc a
stop-and-report trigger, so I checked §E's claims against it one by one.

| brief §E claim | existing §4 | verdict |
|---|---|---|
| E.1 bit layout: `[0]` mem/IO, `[2:1]` type, `[3]` prefetch, `[3:0]` RO | §4.1 table, same | ✅ agrees |
| E.2 `size = ~(readback & mask) + 1`, mask `~4'hF` | §4.2 steps 3-5, `encoded = readback & 0xFFFFFFF0` | ✅ agrees |
| E.2 unimplemented (readback 0) → skip, not 4 GB | §4.2 step 4 | ✅ agrees |
| E.3 64-bit pair consumes N and N+1, advance by 2, write lower then upper | §4.3 steps 1-4 | ✅ agrees |
| E.4 128-byte PCIe floor beats PCI's 16 bytes | §4.1 "must" bullet, §4.3 mutation note | ✅ agrees |
| E.4 mis-decode lands at 16 bytes, caught by the floor | §4.3 "Mutation target" para, computes `0x10` | ✅ agrees |
| E.7 `MEM_BAR_BASE`, not `BAR_BASE` | §4.4 first bullet | ✅ agrees |
| E.7 natural alignment, ascending; I/O skipped | §4.4 bullets 2-3 | ✅ agrees |

**No conflict. No stop-and-report.** §E extends §4 rather than contradicting it.

Three notes for Commit A:

1. **§E.4's "decide and commit" is already decided.** `SPEC_PREDICTIONS_ENUM.md:329`
   states "the FSM should treat a sub-128-byte decode as an enumeration fault" —
   i.e. **ERROR**, not warning-and-continue. §E should record this as *carried
   forward with its citation now discharged*, not re-opened as an open question.
2. **§4.1's `[2:1]` row omits `11`.** It lists `00`, `10`, `01` but not `11`.
   Table 6-4 at `:11207` covers all four encodings; §E.1 should complete the row.
3. **New in §E, absent from §4** — nothing to reconcile, just new work: E.5
   (ordering invariant / Command write last), E.6 (Command value `0006h`), E.7's
   Expansion ROM exclusion, E.8 (exact RQ DWs), E.9 (predicted FAIL sets).

### 6.1 `[PCI3-REF]` discharge inventory

**11 occurrences on 11 distinct lines** to replace with real citations, at
`SPEC_PREDICTIONS_ENUM.md` lines **71, 73, 309, 313, 332, 360, 656, 667, 685,
815, 826** (line 71 is the legend row defining the tag; 656/667/685 are the §9
"what I need to close this" and §10 stop-and-report entries, which become
*closed* rather than merely re-cited). Lines 815/826 are the Header Type bit-field
claims in §D.3 — **anchor `:10685` (page 216) discharges those**, which is the
one discharge that falls outside §4's BAR material.

`MEM_BAR_BASE` confirmed not to exist anywhere in `src/` yet; `BAR_BASE` confirmed
present and EP-side as §4.4 warns (`tlp_layer.sv:15`, `tlp_bar_decoder.sv:4,34`).

---

## 7. Item 5 — `.core` shape for a shared Python helper

**Already solved and in production.** The pattern flagged as an open question in
the 2b-1 recon is the one `enum_tb_common.py` uses today: a **per-fileset
`copyto` entry**, repeated in each cocotb fileset that needs the module —
`tb_rc.core:86, 99, 114, 127`:

```yaml
  cocotb_enum_scan:
    files:
      - enum_tb_common.py      : {file_type : user, copyto : .}
      - test_pcie_enum_scan.py : {file_type : user, copyto : .}
```

FuseSoC copies both into the target build directory, so a plain
`from enum_tb_common import ...` resolves. Confirmed working across all four
existing enum targets in the §1 sweep. There is **no** need for a `PYTHONPATH`
flow option or a packaged module.

**For Commits C–E this means:** the shared module keeps its name and gains the
remaining helpers from §4.2; the two new filesets (`cocotb_enum_bar`,
`cocotb_enum_bar_tlp`) each repeat the same two-line `copyto` stanza. No new
`.core` mechanism is introduced.

`src/rc/rc_core.core` needs `pcie_enum_top.sv` (Commit B) and
`pcie_enum_bar.sv` (Commit D) appended to its single `rtl` fileset, after
`pcie_enum_scan.sv`. Note the fileset is **order-sensitive** for Verilator
elaboration in the existing style (packages first: `pcie_rq_rc_pkg.sv`,
`pcie_enum_pkg.sv` precede all modules) — the two new modules go last, and
`pcie_enum_top.sv` must follow `pcie_enum_scan.sv`.

---

## 8. Stop-and-report status

| brief §12 trigger | status |
|---|---|
| Conflict with `SPEC_PREDICTIONS_ENUM.md` | **none** — §6 |
| Hoist requiring a behavioral edit | **none** — §3.1 |
| Consolidation moving any sim end time | **avoidable by construction** — §4.3 |
| Any on-wire DW differing from §E.8 | n/a (Part 2) |
| Any pre-existing target moving | **none** — §1 is 34/219, identical to the brief |
| Mutation survivor with no obvious new test | n/a (Part 2) |
| Error output firing where a prediction said silent | n/a (Part 2) |
| Inherited-stack surprise | **none this increment** |

**Phase 0 complete. Clear to begin Commit A.**
