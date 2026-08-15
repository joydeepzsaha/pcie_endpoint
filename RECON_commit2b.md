# RECON — Commit 2b (RC Enumeration FSM), Phase 0

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` @ `33ba088` (== `origin/kourosh/dev`, tree clean)
**Scope:** read-only. No RTL, no testbench, no `.core` changed. Nothing staged.

This document discharges the six Phase-0 items in the brief's §6 and reports the
divergences §11 requires be reported before construction begins.

---

## 0. Headline — two things to decide before Phase 1

1. ~~**The brief's trusted baseline number does not reproduce.**~~
   **⚠️ SUPERSEDED 2026-07-29 (Phase 1, Task A) — this finding was WRONG.** The
   brief's **30 targets / 172 tests** is correct. This recon under-counted by
   excluding `verilate_conformance`, the LTSSM control target, which has been a
   deliberate per-commit regression anchor since Commit 0. Measured at `33ba088`:
   **29 / 171 (23 TLP + 6 RC) + `verilate_conformance` 1/1 = 30 / 172, all PASS.**
   Root cause and the corrected record in §1; the superseded reasoning is kept in
   §1.1 with the error marked.
2. **`pcie_rq_rc_top.sv`'s header and port list match brief §3 in every
   behavioural particular.** One stale comment inside `pcie_rq_if.sv`
   contradicts the top level about `command_context`; the top level is correct.
   Details in §2.4.

Everything else below is confirmation plus the two decisions the brief asked
recon to make (package placement, §4; harness reuse plan, §6).

---

## 1. Measured baseline at `33ba088`

**Corrected 2026-07-29 (Phase 1, Task A).** Run sequentially (parallel Verilator
builds SIGSEGV), one FuseSoC target at a time, all 30 exiting `rc=0`.

Target enumeration for the two main cores is **authoritative, not hand-counted**
— from `fusesoc core show fusesoc:pcie:tb_tlp` (23 targets) and
`fusesoc core show fusesoc:pcie:tb_rc` (6 targets). `tb/dllp/tb_dllp.core` has
no `verilate_*` target (only `default`/`sim`/`synth`/`lint`, tool `vcs`) and
`tb/endpoint/tb_pcie_endpoint_top.core` has only a `sim` target on `vcs`;
neither is in the Verilator baseline.

⚠️ **The LTSSM `verilate_conformance` target IS in the baseline** — as a
deliberate **control**, not as LTSSM coverage. It is the per-commit regression
anchor (`RECON_commit2a.md:51-52`: *"the per-commit regression anchor cited in
T12/U9/V4 (LTSSM layer; outside this commit's blast radius)"*), and it is
counted as a separate line item in the total
(`docs/predictions/SPEC_PREDICTIONS_CPL_TIMEOUT.md §G`). The other 11 `tb_ltssm` targets and
the PHY targets remain out. **The first draft of this recon wrongly excluded the
control** — see §1.1.

| target | TESTS | PASS | FAIL | sim ns |
|---|---|---|---|---|
| `verilate_axis_gearbox` | 11 | 11 | 0 | 195768.01 |
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
| **subtotal (23 TLP + 6 RC)** | **171** | **171** | **0** | |
| | | | | |
| `verilate_conformance` *(control, `tb_ltssm_conformance`)* | 1 | 1 | 0 | 6010.00 |
| **TOTAL** | **172** | **172** | **0** | |

**`TARGETS=30 TESTS=172 PASS=172 FAIL=0`.**

### 1.1 The +1: `verilate_conformance`, and why this recon first got it wrong

**Resolution (Phase 1, Task A).** The brief §0's 30 / 172 was right. The 30th
target is `verilate_conformance` (`tb/ltssm_conformance/tb_ltssm_conformance.core:39`),
run as a **control**: it exercises a layer outside every recent commit's blast
radius, so a change in its verdict means the tree moved under you rather than
that the commit broke something. Verified at `33ba088`: elaborates, **1/1 PASS**,
6010.00 ns, 3 s wall.

Corrected arithmetic:

- `8544a2f`: **28 / 152** = 27 / 151 (21 TLP + 6 RC) **+ control 1/1**.
- `1131fbd` added `verilate_tlp_credit_manager` (18 tests) → 29 / 170.
- `6a8c9de` added `verilate_tlp_credit_integration` (2 tests) → **30 / 172**.

**Root cause of the error — worth recording, because this is its third
occurrence.** `STACK_INVENTORY.md` headline finding 0.1 and §2.1 state *"The
trusted baseline is 27 targets / 151 tests, not 152 … The '152' in the brief is a
bookkeeping slip of one"*. That reconciliation is internally consistent **for the
TLP+RC set alone** and is not wrong about that set — but it mis-attributed the
prior brief's 152, which was never 152-within-TLP+RC. It was 151 + the control,
exactly as `docs/predictions/SPEC_PREDICTIONS_CPL_TIMEOUT.md §G` tabulates it:

```
| Total                     | 27 | 151 |
| plus verilate_conformance |  1 |   1 |
**TOTAL: TESTS=152 PASS=152 FAIL=0**
```

`STACK_INVENTORY.md` then listed LTSSM wholesale under *"Not in the trusted
baseline"*, and **this recon inherited that exclusion without re-deriving it** —
trusting a downstream summary over the two primary records. The lesson is the
same one the project keeps relearning: re-measure, and when a document and an
arithmetic chain disagree, find the line item rather than declaring a slip.

~~*Superseded:* the original §1.1 concluded 29 / 171 was correct and the brief was
one high. That conclusion was wrong for the reason above; the text is replaced
rather than kept, since leaving a confidently-wrong total in a reference document
is the exact hazard that caused this.~~

**Consequence for §12 acceptance:** the pre-existing set to hold byte-identical
is **30 / 172**, recorded in the un-mixable decomposed form:

> **29 targets / 171 tests (23 TLP + 6 RC) + `verilate_conformance` control 1/1
> = 30 targets / 172 tests.**

Record kept at `scratchpad/base33ba088/baseline_record.txt`, which now prints
that decomposition explicitly, with per-target logs beside it.

---

## 2. `pcie_rq_rc_top.sv` header vs brief §3

Read `src/rc/pcie_rq_rc_top.sv` in full (590 lines). **The socket contract in §3
is accurate.** Item-by-item:

| §3 claim | Verdict | Anchor |
|---|---|---|
| Four preconditions or silence; `tx_fc_blocked_o` is the diagnostic; RC1 | ✅ | `pcie_rq_rc_top.sv:20-46` |
| Also drive `requester_id_i`, `max_payload_bytes_i`, `max_read_bytes_i` | ✅ ports exist | `:206, 213, 214` |
| RQ beat 0 = 16-byte descriptor, beats 1..n payload; `tuser[3:0]`/`[7:4]` = first/last BE, beat 0 only | ✅ | `:217-224`; `pcie_rq_if.sv:147, 216-217` |
| Config: `req_type` `1000`/`1010` | ✅ | `pcie_rq_rc_pkg.sv:71, 73` |
| Config `dword_count = 1` enforced | ✅ rejects otherwise (`RQ_ERR_CFG_DWORD_COUNT`) | `pcie_rq_if.sv:274` |
| `address = {ext_reg[11:8], reg_num[7:2], 2'b00}` | ✅ | `pcie_rq_if.sv:260-262` |
| **`completer_id` = target BDF forms the routing DW, not the address** | ✅ | `pcie_rq_if.sv:249-258` (`desc_address[31:16] <= desc.completer_id`) |
| Byte-granular config writes work (`0x19` → reg 6, `first_be=0010`) | ✅ arithmetic checks out; admission is `byte_count <= 4 - offset` | `pcie_rq_if.sv:100-105, 276-277` |
| Descriptor Tag `[103:96]` ignored, core-managed | ✅ | `pcie_rq_rc_pkg.sv:49`; `pcie_rq_if.sv:170` |
| Rejects → no TLP + `rq_protocol_error_o`/`rq_error_code_o` | ✅ 13-code table | `pcie_rq_if.sv:85-98`; `pcie_rq_rc_pkg.sv:86-100` |
| Tag out via `pcie_rq_tag_o`/`_vld_o`, 1-cycle, issue order, one per non-posted TLP; **not available at command-accept time** | ✅ | `pcie_rq_rc_top.sv:51-60, 231-232` |
| Back via RC descriptor Tag `[71:64]` | ✅ | `pcie_rq_rc_pkg.sv:123` |
| Posted writes never strobe, never complete | ✅ | `pcie_rq_rc_top.sv:62-63` |
| `cpl_timeout_valid_o`/`_tag_o`, `late_cpl_valid_o`/`_tag_o` exist at top level | ✅ | `:296-299` |
| ZOMBIE quarantine; freed on late bit-30 CPL or a second interval; `outstanding_o` counts quarantined tags | ✅ | `:106-120, 301-305` |
| **Drained late CPL also raises `RC_ERR_ORPHAN_DATA` once per drained DWord** | ✅ and it is *asserted on*, not merely documented | `pcie_rc_if.sv:346, 403-405`; test V9 `test_pcie_rq_rc_top.py:1007-1015` |
| CRS is a normal completion (`010`), not a timeout | ✅ | `pcie_rq_rc_pkg.sv:148-156` |
| RC beat 0 = 3-DW descriptor in DW0–2, first payload DW in DW3; descriptor-only = 1 beat, `tkeep=0b0111`, `tlast` on beat 0 | ✅ | `pcie_rq_rc_pkg.sv:109-115` |
| RC fields (`tag`, `status`, `dword_count`, bit 30, `byte_count`, `error_code`, `lower_address`) | ✅ exact match | `pcie_rq_rc_pkg.sv:117-135` |
| Release the tag on bit 30 | ✅ | PG213 `:4049`; `pcie_rq_rc_pkg.sv:130` |
| `command_context` internally consumed, not a port | ✅ **at the top level** — see §2.4 | `pcie_rq_rc_top.sv:65-77`; `pcie_rc_if.sv:240, 252` |
| Error Code `0011` unreachable; watch `rc_unexpected_completion_o` | ✅ | `pcie_rq_rc_top.sv:132-138`; `pcie_rq_rc_pkg.sv:162-177` |
| No PG213-style synthesized error CPL for a timeout | ✅ deliberate | `pcie_rq_rc_top.sv:118-120` |
| CQ/CC tied off; `target_*_ready` tied **1** so RX never wedges | ✅ | `:83-99, 476-510` |
| Split memory reads take the first CPL's Lower Address `[11:7]`; config never splits | ✅ | `:139-141` |
| Bounded buffering: ~two more descriptors absorbed after tag exhaustion before `tready` drops | ✅ measured behaviour, asserted | `test_pcie_rq_rc_top.py:709-730` |

**No drift found in §3.** The one correction is not to §3 but to a looser
statement in it — see §2.3.

### 2.1 Confirmed port list (`pcie_rq_rc_top`, `src/rc/pcie_rq_rc_top.sv:186-306`)

Parameters `:173-184` — `AXIS_DATA_WIDTH=128`, `AXIS_KEEP_WIDTH=AXIS_DATA_WIDTH/32`
(**Dword-granular, 4 bits**, `:175-176`), `AXIS_USER_WIDTH=60`, `TL_DATA_WIDTH=32`,
`TL_USER_WIDTH=3`, `CONTEXT_WIDTH=16`, `TAG_COUNT=32`,
`CPL_TIMEOUT_CYCLES=32'd4096`.

| group | ports | line |
|---|---|---|
| clock/reset | `clk_i`, `rst_i` | `:186-187` |
| link + FC | `link_up_i`, `transmit_enable_i`, `fc_initialized_i`, `fc_update_valid_i`, `fc_ph_i[7:0]`, `fc_pd_i[11:0]`, `fc_nph_i[7:0]`, `fc_npd_i[11:0]`, `fc_cplh_i[7:0]`, `fc_cpld_i[11:0]` | `:192-201` |
| identity/limits | `requester_id_i[15:0]`, `completer_id_i[15:0]`, `bus_number_i[7:0]`, `device_number_i[4:0]`, `function_number_i[2:0]`, `memory_enable_i`, `extended_tag_enable_i`, `max_payload_bytes_i[12:0]`, `max_read_bytes_i[12:0]`, `rcb_128b_i` | `:206-215` |
| RQ AXIS slave | `s_axis_rq_tdata[127:0]`, `_tkeep[3:0]`, `_tvalid`, `_tlast`, `_tuser[59:0]`, `_tready` | `:220-225` |
| tag presentation | `pcie_rq_tag_o[7:0]`, `pcie_rq_tag_vld_o` | `:231-232` |
| RC AXIS master | `m_axis_rc_tdata[127:0]`, `_tkeep[3:0]`, `_tvalid`, `_tlast`, `_tready` | `:237-241` |
| DLL streams | `s_dllp_axis_*` (in), `m_dllp_axis_*` (out), 32-bit | `:244-256` |
| RQ errors | `rq_protocol_error_o`, `rq_error_code_o` (`rq_error_e`), `rq_gearbox_error_o` | `:261-263` |
| RC errors | `rc_unexpected_completion_o`, `rc_completion_error_code_o` (`tlp_error_e`), `rc_protocol_error_o`, `rc_error_code_o` (`rc_error_e`), `rc_gearbox_error_o` | `:268-272` |
| TL errors/status | `command_error_valid_o`, `command_error_code_o`, `malformed_o`, `rx_error_valid_o`, `rx_error_code_o`, `rx_ecrc_error_o`, `tx_error_valid_o`, `tx_error_code_o`, `tx_fc_blocked_o`, `credit_error_o`, `vc_overflow_o` | `:275-287` |
| timeout sideband | `cpl_timeout_valid_o`, `cpl_timeout_tag_o[7:0]`, `late_cpl_valid_o`, `late_cpl_tag_o[7:0]` | `:296-299` |
| occupancy | `outstanding_o[$clog2(TAG_COUNT+1)-1:0]` | `:305` |

Every signal the FSM in §8 of the brief needs is present at the top level. No
new port on `pcie_rq_rc_top` is required for Commit 2b.

### 2.2 Enum-typed outputs need flattening for cocotb

`rq_error_code_o`, `rc_error_code_o`, `rc_completion_error_code_o`,
`command_error_code_o`, `rx_error_code_o`, `tx_error_code_o` are enum-typed.
The existing shim flattens each with a width cast
(`tb_pcie_rq_rc_top.sv:96-129`). The 2b shims must do the same; this is
established practice, not new work.

### 2.3 Correction to a §3 statement (loose, not wrong)

§3 says *"config consumes NPH+NPD"*. Read against the RTL that is true only for
config **writes**:

- `tlp_vc_buffer.sv:91` — `s_packet_has_data_i ? tlp_data_credits(length_dw) : 0`
- `tlp_pkg.sv:121-125` — `tlp_data_credits(1) = ceil(4/16) = 1`
- `tlp_pkg.sv:127-133` — both CfgRd0 and CfgWr0 map to `TLP_CREDIT_NON_POSTED`

So **CfgRd0 → NPH=1, NPD=0; CfgWr0 → NPH=1, NPD=1**. §4.2's phrasing
("Config reads consume NPH") is the precise one.

~~**This has teeth for the required small-credit test (§10).** A bench that
advertises `NPH=1, NPD=0` would let every enumeration *read* through and then
wedge forever on the first BAR-sizing *write* — which would look like an FSM
deadlock bug.~~

⚠️ **SUPERSEDED 2026-07-29 (Phase 1) — the second half of this was WRONG.** The
consumption facts above are correct and stand. The `NPD=0` inference is not:
**an advertisement of `00h`/`000h` made at FC initialization means INFINITE
credit**, not zero (PCIe Base 2.1 §2.6.1 p.138 and footnote 33 p.137;
implemented at `tlp_credit_manager.sv:106-120`, which latches `npd_infinite_r` at
init). Driving `fc_npd_i = 0` therefore makes NPD **unlimited** — every config
write flows and nothing ever blocks. A starvation test built on `NPD=0` would be
a **vacuous pass**.

The real starvation vector is a *finite* advertisement with no replenishment.
See `docs/predictions/SPEC_PREDICTIONS_ENUM.md` §0.1 and §2.4 (**P-NPD-INF** / **P-NPD1-STALL**),
which supersede this paragraph. The spec-minimum credit vector, and the
non-obvious requirement that the UpdateFC drip advertise a *cumulative*
increasing count rather than a repeated `1`, are fixed there in §2.3.

### 2.4 One stale comment — `pcie_rq_if.sv:171-173`

```
// command_context_o remains available as a second, wrapper-chosen
// correlation channel -- the TL echoes it back on result_context_o -- and
// the two are complementary, not alternatives.
```

This contradicts `pcie_rq_rc_top.sv:65-77` ("**`command_context` IS NOT
AVAILABLE AS A CLIENT CHANNEL**") and brief §3. **The top level is right**:
`pcie_rq_if` loads the context with `{mem_read_r, addr_r[11:0]}`
(`pcie_rq_if.sv:339`) and `pcie_rc_if` consumes it to rebuild Lower Address
(`pcie_rc_if.sv:240, 252`). No port exposes it. The comment is a leftover from
2a-i, written before 2a-ii claimed the channel.

**No behavioural drift** — there is no port either way, so nothing the FSM could
do differs. Flagging it because it is exactly the kind of comment that would
send a 2b reader down a dead end. Fixing it is a one-line comment edit in
`src/rc/`, in scope, but it is a behaviour-neutral doc change and I have not
made it — recommend folding it into the 2b-1 commit rather than spending a
commit on it. **Awaiting direction.**

---

## 3. Constants today, and the package decision

### 3.1 What exists

`src/rc/pcie_rq_rc_pkg.sv` (241 lines) holds **descriptor** types only:
`rq_descriptor_t`, `rq_req_type_e`, `rq_error_e`, `rc_descriptor_t`,
`rc_cpl_status_e`, `rc_desc_error_e`, plus the byte-enable helpers
`rq_popcount4`, `rq_be_offset`, `rq_byte_count`.

**No enumeration constant exists anywhere in the tree.** Nothing defines the
Vendor ID / Command / Header Type / BAR register offsets, no BAR mask
arithmetic, no enumeration error code. Confirmed by grep across `src/rc/` and
`src/tlp/`.

⚠️ **False friend:** `tlp_bar_decoder.sv:4` and `tlp_layer.sv:15` have a
`BAR_BASE` parameter. That is the **completer/endpoint-side** BAR *decode*
aperture for inbound CQ traffic (tied off in this design) — unrelated to the
RC's outbound BAR *assignment*. The 2b parameter must not be named `BAR_BASE`
or it will read as the same thing. Brief §8's `MEM_BAR_BASE` is a good name;
keep it.

### 3.2 Decision — a new `src/rc/pcie_enum_pkg.sv`

**Recorded choice: new package, not an extension of `pcie_rq_rc_pkg`.**

Three reasons:

1. **Scope.** `pcie_rq_rc_pkg`'s own header states its rule: *"These are
   DESCRIPTOR types, not engine types. They describe the shape of the Xilinx
   PG213 user interface"* (`:5-8`). Enumeration constants are engine and policy
   types — PCI config-space register offsets, BAR size decode, FSM state and
   error encodings. They are not PG213 descriptor shapes, and putting them there
   breaks the stated rule.
2. **Precedent.** The project already refuses this kind of mixing in the other
   direction: `rq_req_type_e` was deliberately kept out of `tlp_pkg`
   (`pcie_rq_rc_pkg.sv:143-146`). Same rule, same answer, one layer up.
3. **Blast radius.** All six existing RC targets compile `pcie_rq_rc_pkg`.
   Leaving it byte-identical means the 2b work cannot perturb them at all — a
   free guarantee toward §12's "pre-existing set byte-identical". A new file is
   purely additive.

The FSM will **import** `pcie_rq_rc_pkg` for `rq_req_type_e` (RQ_CFG_READ0 /
RQ_CFG_WRITE0), `rc_cpl_status_e` and `rc_descriptor_t` — reuse, not
duplication. `pcie_enum_pkg` gets only what does not exist yet.

`src/rc/rc_core.core:28-35` gains `pcie_enum_pkg.sv` (before `pcie_enum_fsm.sv`,
after `pcie_rq_rc_pkg.sv`) — an additive fileset edit, in scope per brief §11.3.

---

## 4. PG213 citations captured (`/home/kourosh/openPCIE/0.doc/pg213-pcie4-ultrascale-plus.md`)

The markdown is greppable and complete for 2b's needs — **the PG213-PDF blocker
recorded in the 2a recon is superseded.** Line numbers for Phase 1:

| what | line |
|---|---|
| Figure 42 — RQ Descriptor Format, **Configuration Requests** | `3647` |
| **Table 61** — RQ Descriptor Fields, Configuration Requests (4 parts) | `3711`, `3720`, `3728`, `3735` |
| Table 60 — RQ Descriptor Fields, Memory/IO/Atomic | `3683`, `3693`, `3700` |
| Table 57 — Request Type encodings (referenced from `3725`) | via `3725` |
| **Table 65** — Requester Completion Descriptor Fields | `4034` |
| RC descriptor figure (field layout art) | `4032` |
| **Bit 30 "Request Completed"** — full normative text | `4049` |
| RC Completion Status `[45:43]`, incl. **CRS `010`** | `4052` |
| RC Error Code table (`0001`/`0010`/`0011`/`0100`/`0101`/`1000`/`1001`) | `4241`–`4253` |
| Error code `1001` = completion timeout, PG213's **dummy descriptor** approach | `4252` |
| Tag-reuse rule: do not reassign until bit 30 seen | `4257` |
| 512-bit variant of the same RC descriptor text (do **not** cite; wrong width) | `5222`, `5240`, `5247` |

Field positions in **Table 61** verified against `rq_descriptor_t` line by line
— `[1:0]` reserved, `[7:2]` Reg Number, `[11:8]` Ext Reg Number, `[63:12]`
reserved, `[74:64]` Dword Count, `[78:75]` Request Type, `[79]` Poisoned,
`[103:96]` Tag, `[119:104]` Completer ID, `[120]` Requester ID Enable,
`[123:121]` TC, `[126:124]` Attr, `[127]` Force ECRC. **Exact match** with
`pcie_rq_rc_pkg.sv:43-55`.

Note for Phase 1: PG213 `:4252` documents the Xilinx core answering a completion
timeout with a **synthesized dummy RC descriptor** (error code `1001`). This
design deliberately does not (`pcie_rq_rc_top.sv:118-120`) and uses sideband
strobes instead. That is a **documented deviation from PG213**, and the
predictions doc should cite `:4252` when stating it, so the deviation is on the
record rather than looking like an oversight.

---

## 5. Test-harness inventory — `tb/rc/`

### 5.1 Reusable as-is (`test_pcie_rq_rc_top.py`, 1036 lines)

| helper | line | note |
|---|---|---|
| `rq_desc(req_type, dword_count, address, completer_id, tc, attr)` | `:73` | PG213 Table 60/61 builder |
| `cfg_desc_address(reg_num, ext_reg)` | `:84` | `{ext_reg, reg_num, 00}` |
| `tuser(first_be, last_be)` | `:89` | |
| `cfg_wire_dw2(bus, dev, fn, reg_num, ext_reg)` | `:93` | on-wire golden for the config address DW |
| `decode_rc_desc(v)` | `:105` | full Table 65 decode |
| `dw0_length`, `cpl_dw0`, `cpl_dw1`, `cpl_dw2` | `:124-152` | CPL construction goldens |
| `Request` | `:177` | parses one TLP off the TX DLL stream |
| `ConfigCompleter` | `:203` | TX watcher + completion injector; `.start/.seen/.wait_for/.complete/._inject` |
| `Rc` | `:285` | concurrent monitor: RC packets, tag strobes, **all** error surfaces, timeouts, lates; `.clean()` at `:364` |
| `packet_dwords` / `split_packet` | `:379`, `:388` | beat → Dword → (descriptor, payload) |
| `init_flow_control` / `init` | `:395`, `:414` | full four-precondition bring-up |
| `send_rq` / `cfg_read` / `cfg_write` / `settle` | `:463`-`:500` | |

`Rc.clean()` (`:364-376`) is the reusable "nothing fired that shouldn't" gate,
including the timeout/late silence assertions the brief §11.6 wants.

The `ConfigCompleter` contract is already documented as swap-ready for Joy's EP
model — four names only: `.start()`, `.seen`, `.wait_for(n)`, `.complete(req,…)`
(`:163-175`). **Commit 2b should preserve that interface exactly**, since §12
owes a spec doc listing what Joy's model must satisfy; keeping the same four
names makes that doc a page instead of a redesign.

### 5.2 What is missing for a multi-transaction enumeration bench

1. **There is no config-space model.** `ConfigCompleter.complete()` returns
   `0xD0000000 | tag` (`:260`) — a fabricated value that exists to make
   mis-pairing visible. It has no register file and no notion of a register
   number. Enumeration needs a completer holding real config space: Vendor/Device
   ID at reg 0, Command at reg 1, Header Type at reg 3, BARs at regs 4–9.
   **This is the single largest new-build item in the bench work.**
2. **No BAR write-mask semantics.** The all-ones sizing probe requires a
   completer that models a BAR's writable/RO bit split (size bits writable above
   the alignment boundary, type/prefetch bits RO below). Nothing today has any
   concept of a writable register.
3. **No small-credit flow control.** Every bench in `tb/rc/` saturates at
   `0xFF`/`0xFFF` in one shot (`:406-411`, and the same in
   `test_pcie_rq_if_tlp.py:130`, `test_pcie_rc_if_tlp.py:141`). The brief §10
   requires one test per increment at **NPH=1 with continuous small UpdateFC
   pulses** — needs a new credit-drip coroutine, plus the `NPD ≥ 1` caveat from
   §2.3 above.
4. **No RC1 negative control anywhere.** Grep confirms the only
   `fc_initialized_i = 0` assignments are reset-time initialisation
   (`test_pcie_rq_rc_top.py:441`, `test_pcie_rq_if_tlp.py:190`,
   `test_pcie_rc_if_tlp.py:241`), never a deliberate drop with a
   zero-TLPs-no-error assertion. Brief §10 wants exactly one. New.
5. **`tx_fc_blocked_o` is wired in all three shims but asserted on nowhere.**
   Grep shows it only in the `.sv` shims. The §4.1 requirement that the FSM
   tolerate arbitrary-length credit stalls needs a test that actually observes
   this signal.
6. **No socket model for the standalone target.** In `verilate_enum_txn` the FSM
   is the DUT and `pcie_rq_rc_top` is *absent*, so the bench must play the
   socket: consume RQ AXIS beats, emit `pcie_rq_tag_o`/`_vld_o` with the
   documented post-accept delay, drive RC AXIS descriptors, and drive the
   timeout/late strobes and the correlated `RC_ERR_ORPHAN_DATA` burst. Nothing
   like this exists — the existing standalone benches
   (`tb_pcie_rq_if.sv`, `tb_pcie_rc_if.sv`) play the *TL* side, not the
   *PG213 socket* side. **New, and it is where the 2b-1 blind spots will live**:
   a socket model that is too polite (e.g. strobing the tag in the same cycle as
   accept, or never delaying `tready`) will hide exactly the bugs the standalone
   target exists to catch.

### 5.3 Patterns worth copying verbatim

- **V9** (`:970-1036`) is the template for the orphan-data correlation the brief
  §5 calls out: it asserts `rc_errors == [RC_ERR_ORPHAN_DATA] * len(payload)` —
  an *exact count*, one per drained Dword — not merely "no failure". 2b's
  late-CPL test should assert at the same strength.
- **V8** (`:927-967`) forces tags apart *and asserts they are distinct*
  (`:942`) before relying on them — the degenerate-value discipline of brief §10
  in practice. The 2b tag-match test must do the same.
- **V4** (`:688-773`) is where the bounded-buffering behaviour is pinned; reread
  `:709-730` before writing any test that reasons about `s_axis_rq_tready`.

---

## 6. Recommended target/file layout for Phase 1+

New files, all additive, all inside the brief's allowed set:

| file | purpose |
|---|---|
| `src/rc/pcie_enum_pkg.sv` | config-space offsets, BAR decode, FSM state + error enums |
| `src/rc/pcie_enum_fsm.sv` | the FSM itself |
| `tb/rc/tb_pcie_enum_txn.sv` | 2b-1 standalone shim (socket model in Python) |
| `tb/rc/tb_pcie_enum_txn_tlp.sv` | 2b-1 integration shim (FSM + `pcie_rq_rc_top`) |
| `tb/rc/test_pcie_enum_txn.py`, `test_pcie_enum_txn_tlp.py` | 2b-1 tests |
| `src/rc/rc_core.core` | +2 files in the `rtl` fileset |
| `tb/rc/tb_rc.core` | +filesets and +targets per increment |

2b-2 and 2b-3 extend the same pair-of-targets pattern
(`verilate_enum_scan(+_tlp)`, `verilate_enum_bar(+_tlp)`).

Shared Python (descriptor builders, the config-space completer, the credit drip)
should live in one importable module rather than being copied per test file —
`tb_rc.core` already uses `copyto: .` per test, so a shared helper needs its own
`copyto` entry in each fileset that imports it. Flagging now because it changes
the `.core` shape slightly and is easier to set up in 2b-1 than to retrofit.

---

## 7. Questions blocking Phase 1 — both RESOLVED

1. ~~**Baseline number.**~~ **RESOLVED (Task A).** The brief was right: **30 / 172**,
   pinned as *29 / 171 (23 TLP + 6 RC) + `verilate_conformance` control 1/1*.
   This recon's 29 / 171 was an under-count; see §1.1.
2. ~~**The stale `command_context` comment.**~~ **RESOLVED (Task B).** Landed as
   its own doc-fix commit ahead of any 2b-1 RTL, per the `32850a4` precedent, so
   the 2b-1 diff stays purely additive.

Phase 1 output is `docs/predictions/SPEC_PREDICTIONS_ENUM.md`.

---

## 8. Summary of §11 triggers checked

| trigger | status |
|---|---|
| 1. §3 vs actual header/port list | **No drift.** One stale internal comment (§2.4) and one loose credit statement (§2.3), both reported, neither behavioural |
| 2. Spec read contradicting the brief | None yet — Phase 1 not started. PG213 `:4252` deviation noted as *known and deliberate*, not a contradiction |
| 3. Need to modify outside `src/rc/` + `tb/rc/` + `.core` | **None identified.** All FSM inputs exist at the `pcie_rq_rc_top` top level |
| 4. Pre-existing test changing verdict/count/sim time | **None** — all 172 pass (171 + control); §1 records per-target sim times for future comparison |
| 5. Mutation survivor with no obvious test | n/a — no RTL yet |
| 6. Error output firing where a prediction said silent | n/a — no predictions yet |
| 7. Temptation to loosen an assertion | None |
