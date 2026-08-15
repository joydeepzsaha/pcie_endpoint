# SYNTH_PREDICTIONS_S1 — predictions before the first synthesis of the RC vertical

**Written at HEAD `1fb2c5c`, BEFORE any `synth_design` has been run on this repo.**
This file is committed first and **is never edited afterwards**. Every falsification is
recorded in `SYNTH_FINDINGS_S1.md`, not repaired here.

**Tool:** Vivado 2023.2 ML Standard (`v2023.2`, SW Build 4029153, 2023-10-13).
**Part:** `xczu7ev-ffvc1156-2-e` — see §0.3.
**Placeholder clock:** one `create_clock` on `clk_i`, 250 MHz / 4.000 ns. Gen1-era
placeholder only; the real clocking architecture is blocked on the GTH-attach decision.
**All timing numbers in this document and its findings companion are DIRECTIONAL ONLY.**

---

## 0. Setup facts (measured, not predicted)

### 0.1 The synthesis units

Re-derived at HEAD from `src/rc/rc_core.core`, `src/tlp/tlp_core.core` and the RTL, then
cross-checked against `RECON_STACK_INTEGRATION.md` §4A.

There are exactly two RC-side integration tops in the `rc_core` fileset:

| Unit | Top | Covers | Instantiates |
|---|---|---|---|
| **A** | `pcie_enum_top` (`src/rc/pcie_enum_top.sv:176`) | the enumeration spine | 2× `pcie_enum_scan`, 2× `pcie_enum_bar`, 1× `pcie_enum_bus`, 1× `pcie_cfg_txn`, + the 5-arm static mux |
| **B** | `pcie_rq_rc_top` (`src/rc/pcie_rq_rc_top.sv:226`) | the host surface **and the whole TL** | `pcie_rq_if` → `pcie_axis_dw_downsize`, `tlp_layer` (11 submodules), `pcie_rc_if` → `pcie_axis_dw_upsize` |

**`tlp_layer` is NOT a third unit.** The brief conditions the third unit on the TL not
being inside either top; it is inside Unit B at `src/rc/pcie_rq_rc_top.sv:467`, and
`report_utilization -hierarchical` breaks it out. Adding a standalone `tlp_layer` run
would re-measure the same netlist. Recorded as a decision, not an omission.

`pcie_enum_top` does **not** instantiate `tlp_layer` or `pcie_rq_rc_top` — verified by
scanning every instantiation line in `src/rc/pcie_enum_top.sv` (six instances, all
enumeration-side). The two units are disjoint apart from `tlp_pkg`.

### 0.2 File lists (RTL only, packages first)

Order is the `.core` fileset order with the three packages hoisted to the front.
The hoist is required, not cosmetic: `pcie_rq_rc_pkg.sv` references `tlp_pkg::`
(`src/rc/pcie_rq_rc_pkg.sv`, e.g. the `rq_byte_count` region at :229), so `tlp_pkg`
must compile first even for a unit with no TL in it. `pcie_enum_pkg` imports nothing.

**Unit A — `pcie_enum_top` (8 files):**
```
src/tlp/tlp_pkg.sv
src/rc/pcie_rq_rc_pkg.sv
src/rc/pcie_enum_pkg.sv
src/rc/pcie_cfg_txn.sv
src/rc/pcie_enum_scan.sv
src/rc/pcie_enum_bar.sv
src/rc/pcie_enum_bus.sv
src/rc/pcie_enum_top.sv
```

**Unit B — `pcie_rq_rc_top` (22 files):**
```
src/tlp/tlp_pkg.sv
src/tlp/tlp_ecrc.sv
src/tlp/tlp_validator.sv
src/tlp/tlp_classifier.sv
src/tlp/tlp_bar_decoder.sv
src/tlp/tlp_config_decoder.sv
src/tlp/tlp_parser.sv
src/tlp/tlp_payload_formatter.sv
src/tlp/tlp_request_tracker.sv
src/tlp/tlp_requester.sv
src/tlp/tlp_completion_generator.sv
src/tlp/tlp_control.sv
src/tlp/tlp_generator.sv
src/tlp/tlp_credit_manager.sv
src/tlp/tlp_vc_buffer.sv
src/tlp/tlp_layer.sv
src/rc/pcie_rq_rc_pkg.sv
src/rc/pcie_axis_dw_downsize.sv
src/rc/pcie_axis_dw_upsize.sv
src/rc/pcie_rq_if.sv
src/rc/pcie_rc_if.sv
src/rc/pcie_rq_rc_top.sv
```

No vendor RTL is reachable from either top: every instantiation in `src/tlp/` and
`src/rc/` names a first-party module. `src/verilog-axis/`, `src/verilog-pcie/`,
`src/xilinx_primitives/` and `src/async_fifo/` are **not** dependencies of the RC vertical.
`lint/waiver.vlt` is a Verilator waiver, not RTL, and is excluded.

### 0.3 Part choice

`get_parts xczu7ev*` returns 27 parts across three packages. Chosen:
**`xczu7ev-ffvc1156-2-e`** — `-ffvc1156` per the brief, `-2-e` because that is the
speed/temperature grade of the ZCU102's ZU9EG (`xczu9eg-ffvb1156-2-e`), so the timing
character carries over as directly as a stand-in can. It is also the Vivado board part
for the ZCU106.

Capacity reported by Vivado for this die: **230,400 LUTs, 460,800 FFs, 312 BRAM (36 Kb),
96 URAM, 1,728 DSP.** The ZU9EG is larger (274,080 LUTs / 548,160 FFs / 912 BRAM);
this die is the conservative proxy.

### 0.4 Construct census (grep over the two file lists)

| Construct | Unit A | Unit B | Sites |
|---|---|---|---|
| `always_comb` | 4 | 26 | §2 |
| `always_ff` | 4 | 17 | — |
| `always @(*)` / `always_latch` | 0 | 0 | none anywhere |
| `initial` blocks | **2** | **0** | `pcie_enum_bar.sv:738`, `pcie_cfg_txn.sv:212` |
| `$warning` calls | **5, all inside `initial`** | **10, all inside `always_ff`** | §1.1 |
| `$display`/`$error`/`$fatal`/`$time`/`$random`/`#delay`/`fork` | 0 | 0 | none anywhere |
| SVA (`assert`/`property`) | 0 | 0 | none anywhere |
| 2-D unpacked arrays | 0 | **4** | `tlp_vc_buffer.sv:39-42` |
| unpacked arrays crossing a **port** | 0 | 0 | none anywhere |
| non-constant index / variable part-select | 3 | 6 | §1.3 |
| `unique case` | 2 | 5 | — |

The `$warning` split is a clean natural experiment: **Unit A tests only
`$warning`-inside-`initial`; Unit B tests only `$warning`-inside-`always_ff`.**

---

## 1. Construct acceptance predictions

### P1.1 — `$warning`

**Unit A, inside `initial` (5 sites):** `pcie_enum_bar.sv:742`, `:744`;
`pcie_cfg_txn.sv:214`, `:217`, `:224`.

> **Prediction A1.1:** accepted. Vivado evaluates the elaboration-time conditions and
> **prints the message** (as `WARNING:` or `INFO:` in the log), inferring **zero logic**
> from the `initial` blocks — they contain nothing but `if`/`$warning`.
> **Prediction A1.1b:** with the default parameters actually instantiated by
> `pcie_enum_top` (`MEM_BAR_BASE = 64'h8000_0000` which IS 128-byte aligned,
> `MEM_BAR_WINDOW = 64'h1000_0000` which is non-zero, `CRS_RETRY_MAX = 16` and
> `CRS_BACKOFF_CYCLES = 64` from `pcie_enum_pkg.sv:159-160`, `CPL_TIMEOUT_CYCLES = 4096`
> so the P-CRS-BUDGET product is 16 × 64 = 1024 < 4096),
> **none of the five conditions fires**, so no message text appears. If a message DOES
> appear, the P-CRS-BUDGET guard at `pcie_cfg_txn.sv:224` is the one that fires.

**Unit B, inside `always_ff` (10 sites):** `pcie_axis_dw_downsize.sv:150`,
`pcie_axis_dw_upsize.sv:146`, `pcie_rc_if.sv:417,429,456,465`,
`pcie_rq_if.sv:559,570,595,604`.

> **Prediction B1.1:** accepted and **silently ignored** — no logic inferred, no error.
> Vivado's synthesis front end drops procedural system tasks in a clocked process.
> **Prediction B1.1b:** expect **at most an INFO-level note** per site (or none at all).
> A `$warning` in an `always_ff` will **not** be promoted to an error and will **not**
> block synthesis. *Falsified if any `$warning` produces an ERROR or a critical warning.*

> **Prediction 1.1c (shared):** neither unit's `$warning` sites cause a **width-mismatch**
> or format-string diagnostic, despite the `%0h`/`%0d` on enum-typed arguments
> (`desc_error` at `pcie_rq_if.sv:560` is `rq_error_e`, `desc.req_type` is `rq_req_type_e`).

### P1.2 — `initial` blocks

> **Prediction 1.2:** the two `initial` blocks contribute **0 LUT, 0 FF**. They perform no
> assignment to any signal — only `$warning`. No "initial value ignored" warning class,
> because no register is being initialised.

### P1.3 — non-constant indexing and variable part-selects

Every site found by grep, with a per-site accept/reject prediction:

| # | Site | Shape | Prediction |
|---|---|---|---|
| A-a | `pcie_enum_bar.sv:483` | `io_bar_mask_r[cand_r - CFG_REG_BAR_FIRST] <= 1'b1` — 6-bit index into a 6-entry vector | **Accepted.** Index can exceed 5 in unreachable states, so expect an **index-out-of-range INFO/WARNING** class. Synthesis builds a 6-way decoder with the out-of-range writes dropped. |
| A-b | `pcie_enum_bar.sv:585-589`, `:611-615` | `slot_valid_r[slot_r]`, `slot_size_r[slot_r]`, `slot_addr_r[slot_r]` — `slot_r` is `logic [2:0]` (0–7) indexing `BAR_SLOTS = 6` | **Accepted**, same out-of-range warning class. This is the **most likely single source of a range warning in Unit A.** |
| A-c | `pcie_enum_bar.sv:726-731` | `bar_size_o[i*64 +: 64]` in an unrolled `for (int i…)` | **Accepted, no warning** — `i` is constant per unrolled iteration. |
| B-a | `tlp_vc_buffer.sv:59-62` | `data_mem[rd_packet_r][rd_word_r]` in a **continuous assign** — asynchronous read of a 2-D unpacked array | **Accepted.** This is the memory-inference question — see §3.1. |
| B-b | `tlp_vc_buffer.sv:94-97` | `data_mem[wr_packet_r][wr_word_r] <= …` — clocked write, different address from the read | **Accepted**, simple-dual-port shape. |
| B-c | `tlp_request_tracker.sv:216` | `remaining_r[completion_index]`, `expects_data_r[completion_index]` — 5-bit index into 32 entries | **Accepted.** Full range covered, **no out-of-range warning.** Builds a 32:1 mux. |
| B-d | `tlp_request_tracker.sv:222,224` | `alloc_time_r[scan_index_r]`, `active_r[scan_index_r]` | **Accepted, no warning** — `TAG_INDEX_WIDTH = 5` exactly covers 32. |
| B-e | `pcie_axis_dw_upsize.sv:121-122` | `merged_data[phase_r*DATA_WIDTH_NARROW +: DATA_WIDTH_NARROW] = …` — variable indexed part-select as an **LHS** | **Accepted.** `+:` with a variable base is the synthesizable form. **No warning.** |
| B-f | `tlp_bar_decoder.sv:34-35` | `BAR_BASE[index*64 +: 64]` on a parameter | **Accepted, no warning** — unrolled. |

> **Prediction 1.3 (aggregate):** **no site is rejected.** Unit A produces one or two
> index-range warning *classes* (from A-a and A-b); Unit B produces **none**.

### P1.4 — everything else

> **Prediction 1.4a:** all 6 `tlp_pkg` `automatic` functions used in the datapath —
> including `tlp_crc32_dw` (`tlp_pkg.sv:153`), whose body is an unrolled 8-iteration
> bit loop per byte — synthesize into combinational XOR trees with no diagnostic.
> **Prediction 1.4b:** `unique case` produces **no** "unique case has no default" or
> "case is not full" warning in either unit — every `unique case` either enumerates all
> values of its selector or carries an explicit `default` (verified per block in §2).
> **Prediction 1.4c:** `-mode out_of_context` inserts **no I/O buffers**; `report_utilization`
> shows **IO = 0** and `report_timing_summary` reports a large number of **unconstrained
> input and output ports** (no `set_input_delay`/`set_output_delay` is written — brief rule 6).
> **Prediction 1.4d:** both units **elaborate and synthesize to completion**. Neither fails.
> *This is the brief's question (1), and the prediction is "yes" for both.*

---

## 2. Latch predictions — per `always_comb` block

**Headline prediction: ZERO inferred latches in either unit.** Below is the per-block
basis, so a single falsification is locatable rather than blanket.

The structural reason the count is expected to be zero is stronger than "the code is
tidy": there is **no `always_latch` and no `always @(*)` anywhere in the RC vertical** —
every combinational process is `always_comb`, which Vivado checks, and every one of the
30 blocks either opens with a full default assignment or closes every branch.

### 2.1 The two named suspects from the tracker

**Suspect 1 — "the enumeration FSM next-state logic".**

> **Prediction S1: no latch, and the suspect does not exist in the form named.**
> `pcie_enum_scan.sv` has **zero** `always_comb` blocks; its FSM is a single-process
> `always_ff` at `src/rc/pcie_enum_scan.sv:334`. `pcie_enum_bus.sv` likewise has zero
> (`always_ff` at `:213`). `pcie_enum_bar.sv` has exactly one `always_comb` (`:720`) and
> it is the output fan-out, **not** next-state; the FSM is the `always_ff` at `:410`.
> A single-process FSM cannot infer a latch — there is no combinational process to latch in.
> *Falsified if any latch is reported inside `u_scan`, `u_scan2`, `u_bus`, `u_bar` or `u_bar2`.*

**Suspect 2 — "the 5-arm static mux".**

> **Prediction S2: no latch.** `pcie_enum_top.sv` contains **zero** `always_comb` blocks.
> All five arms of the mux are **continuous assignments** — `cmd_valid` through
> `rsp_ready` at `src/rc/pcie_enum_top.sv:598-632`, `cmd_type1` at `:640`, `cmd_bdf` at
> `:646`, and the gated back-channels at `:652-661`. A nested conditional operator is
> total by construction: the trailing `: bar2_cmd_valid` is the else-of-last-resort.
> A continuous assignment cannot infer a latch. **The mux is structurally latch-proof.**
> *Falsified if any latch is reported at the `pcie_enum_top` level.*

### 2.2 Unit A — all 4 `always_comb` blocks

| Block | Signals driven | Basis | Verdict |
|---|---|---|---|
| `pcie_cfg_txn.sv:281` | `desc` | `desc = '0` at :282 defaults every field before the per-field writes | **no latch** |
| `pcie_cfg_txn.sv:358` | `status_is_crs`, `status_outcome` | ⚠️ **highest-risk block in the whole vertical.** `status_is_crs` is defaulted at :359; **`status_outcome` has no default** and is assigned only inside `unique case (rc_desc.completion_status)`. That selector is `logic [2:0]` (`pcie_rq_rc_pkg.sv:127`) and the case lists **all 8 of 8** patterns (:361-368) with **no `default` arm**. | **no latch** — full case. *If a latch appears anywhere in Unit A, predict it is here, on `status_outcome`.* |
| `pcie_enum_bar.sv:720` | `bar_valid_o`, `bar_is_64_o`, `bar_prefetch_o`, `bar_size_o`, `bar_addr_o` | all five defaulted to `'0` at :721-725 before the unrolled loop | **no latch** |
| `pcie_enum_scan` / `pcie_enum_bus` | — | no `always_comb` exists | **no latch** |

### 2.3 Unit B — all 26 `always_comb` blocks

| Block | Basis | Verdict |
|---|---|---|
| `tlp_bar_decoder.sv:25` | 4 outputs + `match_count` defaulted :26-30; `base`/`mask`/`start_match`/`end_match` written unconditionally every unrolled iteration | no latch |
| `tlp_classifier.sv:18` | 7 outputs defaulted :19-25; `unique case` has `default` :49 | no latch |
| `tlp_completion_generator.sv:66` | `accepted_bytes` defaulted :67; rest unconditional | no latch |
| `tlp_config_decoder.sv:14` | all three unconditional | no latch |
| `tlp_control.sv:44` | all ten unconditional | no latch |
| `tlp_credit_manager.sv:148` | 4 selected_* defaulted :149-152; `case` has `default` :168 | no latch |
| `tlp_ecrc.sv:20` | both unconditional | no latch |
| `tlp_generator.sv:60` | `dw0 = '0` :62; `dw1`/`dw2` written in **both** arms :75-83; `dw3`/`axis_dw*` unconditional then overridden | no latch |
| `tlp_generator.sv:102` | 6 outputs defaulted :103-108; `unique case` has `default: ;` :146 | no latch |
| `tlp_generator.sv:150` | all three unconditional | no latch |
| `tlp_layer.sv:240` | unconditional then conditional override | no latch |
| `tlp_layer.sv:250` | unconditional then conditional override | no latch |
| `tlp_parser.sv:56` | unconditional then conditional override | no latch |
| `tlp_parser.sv:74` | all four unconditional | no latch |
| `tlp_request_tracker.sv:184` | `tag_found`/`allocate_tag_o` defaulted :185-186; `completion_match`/`completion_index` defaulted :200-201; `active_count` defaulted :230; the remaining seven unconditional | no latch |
| `tlp_requester.sv:141` | `header_c = '0` :148 before the field writes; `accepted_bytes` defaulted :144 | no latch |
| `tlp_validator.sv:14` | `valid_o`/`error_o` defaulted :21-22 ahead of the `if`/`else if` chain | no latch |
| `pcie_axis_dw_upsize.sv:118` | `merged_data`/`merged_keep` written whole at :119-120 before the part-select overwrite | no latch |
| `pcie_rc_if.sv:254` | `if`/`else if`/**`else`** — chain is closed at :257 | no latch |
| `pcie_rc_if.sv:261` | `desc_next = '0` :262 | no latch |
| `pcie_rc_if.sv:316` | 4 gb_* defaulted :317-320; outer `unique case` has `default: ;` :342; inner has `default:` :326 | no latch |
| `pcie_rc_if.sv:380` | loop covers all `AXIS_KEEP_WIDTH` bits of `m_axis_rc_tkeep` — every bit assigned | no latch |
| `pcie_rq_if.sv:258` | 4 signals defaulted :259-262; `unique case` has `default` :276 | no latch |
| `pcie_rq_if.sv:296` | `if` arm opens with `desc_address = 64'd0`; `else` arm writes the whole vector | no latch |
| `pcie_rq_if.sv:346` | ⚠️ `desc_error` has **no default**, but the 12-deep `else if` chain is closed by a final `else` at :360 that assigns it | no latch |
| `pcie_rq_if.sv:499` | ⚠️ `s_axis_rq_tready` has **no default**, but the `unique case` carries `default:` at :504 | no latch |

> **Prediction 2.4:** the log grep for `LATCH` / `inferred latch` returns **zero hits** in
> both units, and `report_methodology` reports **no** `SYNTH-*` latch rule violation.
> **Prediction 2.5:** the grep for `combinational loop` also returns **zero** hits.

---

## 3. Area predictions

Order-of-magnitude only; the brief's bar is a factor of ~4. Stated as a point estimate
plus the band that counts as "confirmed".

### 3.1 The one that matters — `tlp_vc_buffer`'s memory

`tlp_layer` instantiates `tlp_vc_buffer` (`tlp_layer.sv:455`) with `PACKET_DEPTH = 4` and
the default `MAX_PACKET_WORDS = 1030`, `DATA_WIDTH = 32`, `KEEP_WIDTH = 4`, `USER_WIDTH = 3`.
That is four 2-D unpacked arrays (`tlp_vc_buffer.sv:39-42`) totalling

```
4 packets × 1030 words × (32 + 4 + 3 + 1) bits = 164,800 bits
```

which is **the single largest storage structure in the RC vertical by two orders of magnitude.**

> **Prediction 3.1a — BRAM = 0 in Unit B.** The read is a **continuous assign**
> (`tlp_vc_buffer.sv:59-62`), i.e. asynchronous. Block RAM requires a registered read;
> no BRAM can be inferred. **Predicted BRAM: 0. Predicted URAM: 0. Predicted DSP: 0
> in both units.**
> **Prediction 3.1b — no register fallback.** The four arrays are deliberately **not**
> reset (only `word_count_mem` is, at `:77`), which is the condition RAM inference needs.
> Predict Vivado infers **distributed RAM (LUTRAM)**, reported on the
> "LUT as Memory" / `LUTRAM` line: **≈ 2,500–4,000 LUTRAM** (4,120 entries deep needs
> ~65 LUT6 per bit plus a 65:1 output mux tree, × 40 bits).
> **Prediction 3.1c — the named alternative.** If inference **fails** — which is the real
> risk, because Vivado's RAM inference is documented against 1-D arrays of packed vectors
> and these are 2-D unpacked — the fallback is registers: **≈ 164,800 FF (36% of the die's
> FFs) plus a 4,120:1 mux per bit ≈ 40,000+ LUTs.** The measurement that decides between
> 3.1b and 3.1c is the FF count: **under 10,000 ⇒ RAM inferred; over 100,000 ⇒ registers.**
> **This is the prediction I most expect to be falsified, and the most valuable one either way.**

### 3.2 Unit A — `pcie_enum_top`

Basis: 2× `pcie_enum_bar` dominates. Each holds `slot_valid_r`/`slot_is64_r`/
`slot_prefetch_r` (6 × 1) + `slot_size_r`/`slot_addr_r` (6 × 64 each) = 786 FF of slot
array, plus `cursor_r` (65), `size_r`/`addr_r` (64 each), `enc_lo_r` (32) and the FSM ≈
**~1,050 FF per instance**. `pcie_cfg_txn` ≈ 150 FF, each `pcie_enum_scan` ≈ 80 FF,
`pcie_enum_bus` ≈ 50 FF, `pcie_enum_top` itself ≈ 0 (wiring only, no state of its own).

| Metric | Point estimate | "Confirmed" band |
|---|---|---|
| LUT (logic) | **3,000** | 750 – 12,000 |
| LUTRAM | **0** | 0 |
| FF | **2,600** | 1,300 – 5,200 |
| BRAM / URAM / DSP | **0 / 0 / 0** | exact |

### 3.3 Unit B — `pcie_rq_rc_top`

Basis, excluding the VC buffer: `tlp_request_tracker` at `TAG_COUNT = 32` holds
`requester_id_r` (512) + `alloc_time_r` (1,024) + `context_r` (512) + `remaining_r` (416)
+ `next_lower_address_r` (224) + `active_r`/`zombie_r` (64) + counters ≈ **2,900 FF** and
is the largest non-memory register bank. Header registers in parser/generator/requester/
completion-generator ≈ 800 FF; `tlp_credit_manager` ≈ 250 FF; `pcie_rq_if` + `pcie_rc_if`
descriptor staging ≈ 400 FF; the two gearboxes ≈ 200 FF.

| Metric | Point estimate (RAM-inferred path) | "Confirmed" band | If §3.1c instead |
|---|---|---|---|
| LUT (logic) | **4,500** | 1,500 – 18,000 | ≈ 40,000+ |
| LUTRAM | **3,000** | 1,000 – 12,000 | 0 |
| FF | **5,500** | 2,750 – 11,000 | ≈ 170,000 |
| BRAM / URAM / DSP | **0 / 0 / 0** | exact | same |

> **Prediction 3.4:** the three largest submodules of Unit B by LUT, in order, are
> **`tlp_vc_buffer` > `tlp_request_tracker` > `pcie_rq_if`**.
> **Prediction 3.5:** the two largest submodules of Unit A by LUT are the **two
> `pcie_enum_bar` instances**, and they are within 10% of each other (identical RTL,
> `u_bar2` differs only in its `cmd_type1` arm, which lives in the parent).

### 3.6 Fit

> **Prediction 3.6:** the RC vertical (Units A + B summed, double-counting nothing since
> they are disjoint) occupies **well under 10% of the ZU7EV's 230,400 LUTs** on the
> RAM-inferred path — i.e. the RC is *not* the thing that decides whether an AraXL fits
> beside it. **On the §3.1c register-fallback path it crosses 20% of LUTs and 36% of FFs,
> and it becomes the deciding term.** Labeled proxy: ZU7EV standing in for ZU9EG.

---

## 4. Timing predictions (250 MHz placeholder, directional only)

Only `create_clock` is written — no `set_input_delay`/`set_output_delay` (brief rule 6).
So **only register-to-register paths are timed**; every input-to-register and
register-to-output path is unconstrained and cannot appear in WNS.

> **Prediction 4.0:** both units report a **large unconstrained-port count** and
> `report_timing_summary` shows a populated "check_timing" section flagging
> `no_input_delay` / `no_output_delay`. This is expected, not a finding.

### 4.1 Unit A worst path

The allocator in `pcie_enum_bar` is a chain of 64/65-bit carry operations, all
combinational between registers (`src/rc/pcie_enum_bar.sv:355-386`):

```
size32/size64  = (~enc) + 1          64-bit invert + increment   :355, :360
alloc_size     = pair_now ? …        64-bit mux                  :373
align_mask65   = alloc_size65 - 1    65-bit subtract             :377
alloc_addr65   = (cursor_r + align_mask65) & ~align_mask65   65-bit add + mask  :378
alloc_end65    = alloc_addr65 + alloc_size65   65-bit add        :379
window_bad     = alloc_end65 > MEM_BAR_LIMIT   65-bit compare    :385
                 → back into cursor_r / slot_addr_r / state_r    :589-592
```

Three to four chained 65-bit carry chains plus a 65-bit comparator, in one cycle.

> **Prediction 4.1:** Unit A **fails 250 MHz**. Predicted **WNS between −3.0 ns and 0.0 ns**
> (i.e. a max frequency somewhere in 140–250 MHz). The worst path **starts at `cursor_r`
> and ends at `cursor_r` or `slot_addr_r[…]` inside `u_bar` or `u_bar2`**, passing through
> `alloc_addr65`/`alloc_end65`. *Falsified if WNS ≥ 0, or if the worst path is outside
> a `pcie_enum_bar` instance.*

### 4.2 Unit B worst path

Candidates, in predicted order:

1. **`tlp_request_tracker`** (`src/tlp/tlp_request_tracker.sv:184-233`) — a 32-deep
   priority search (:189), a 32-way match that compares a full 16-bit `requester_id_r`
   per tag (:202-208), then `remaining_r[completion_index]` through a 32:1 13-bit mux
   feeding `completion_last` (:216), all of it reg→reg into the `always_ff` at :242.
   Plus a 32-bit popcount at :231.
2. **`tlp_vc_buffer`'s read mux** — only if §3.1c happens **and** the mux output reaches a
   register rather than an output port. `m_axis_tdata` is a port
   (unconstrained), so **this path may not appear in WNS at all** even if it is physically
   the slowest thing in the netlist. Worth stating: a good WNS here would not mean the
   buffer is fast.
3. `pcie_rq_if`'s legality block (`:346`) — a 12-deep priority chain over predicates that
   include 64-bit address arithmetic (`bad_4kb`).

> **Prediction 4.2:** Unit B **fails 250 MHz**. Predicted **WNS between −2.5 ns and 0.0 ns**.
> The worst path is **inside `tlp_layer/request_tracker_inst`**. *Falsified if WNS ≥ 0, or
> if the worst path names a module other than `tlp_request_tracker`.*
> **Prediction 4.2b:** Unit B's WNS is **less negative** than Unit A's — the tracker's
> 32-way search is wide but shallow, the allocator's carry chain is deep.

### 4.3 Aggregate

> **Prediction 4.3:** **neither unit meets 250 MHz.** *Falsified for any unit with WNS ≥ 0.*
> **Prediction 4.4:** TNS is dominated by a small number of endpoints (< 50 failing
> endpoints per unit), not spread across the design — these are localized arithmetic
> problems, not a globally slow netlist.

---

## 5. Summary — the falsifiable claims

| # | Claim | Where measured |
|---|---|---|
| 1 | Both units elaborate and synthesize to completion | §1.4d |
| 2 | Zero inferred latches, both units | §2 (30 blocks, per-block basis) |
| 3 | Zero combinational loops | §2.5 |
| 4 | `$warning`-in-`initial` prints, infers nothing | §1.1 A |
| 5 | `$warning`-in-`always_ff` is ignored, not an error | §1.1 B |
| 6 | No construct is rejected | §1.3, §1.4 |
| 7 | BRAM = URAM = DSP = 0, both units | §3.1a |
| 8 | `tlp_vc_buffer` maps to LUTRAM, not registers | §3.1b vs §3.1c |
| 9 | Unit A ≈ 3,000 LUT / 2,600 FF | §3.2 |
| 10 | Unit B ≈ 7,500 LUT+LUTRAM / 5,500 FF | §3.3 |
| 11 | Unit A worst path is `pcie_enum_bar`'s 65-bit allocator | §4.1 |
| 12 | Unit B worst path is `tlp_request_tracker`'s 32-way search | §4.2 |
| 13 | Neither unit meets 250 MHz | §4.3 |
| 14 | Index-range warnings in Unit A only, from `slot_r`/`cand_r` | §1.3 A-a, A-b |
