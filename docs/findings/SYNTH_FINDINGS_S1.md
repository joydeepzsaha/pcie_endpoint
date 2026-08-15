# SYNTH_FINDINGS_S1 — the first synthesis evidence for this stack

Companion to `docs/predictions/SYNTH_PREDICTIONS_S1.md`, which was committed at `681df9f` **before**
the first `synth_design` ran and has not been edited since. Where a prediction was
wrong, this document says so; nothing was back-fitted.

**Tool:** Vivado 2023.2 ML Standard (SW Build 4029153).
**Part:** `xczu7ev-ffvc1156-2-e` — a free-tier stand-in for the ZCU102's ZU9EG
(`xczu9eg-ffvb1156-2-e`, not visible under ML Standard). Same family, same
speed/temperature grade. **A proxy for area and timing character, not a board commitment.**
**Clock:** one `create_clock` on `clk_i` at 250 MHz / 4.000 ns, and nothing else.
**Scripts:** `synth/s1_ooc.tcl` + `synth/run_s1.sh` (committed at `7652b92`).
**Reports:** `~/synth_s1/<unit>/` — outside the repo, nothing generated is committed.

> ## ⚠️ EVERY TIMING NUMBER BELOW IS DIRECTIONAL ONLY
> No XDC, no pin placement, no clocking architecture, no `set_input_delay` /
> `set_output_delay` — all of that is blocked on the GTH-attach decision. Three
> consequences, and the third is the one that bites:
>   1. Only register-to-register paths are timed.
>   2. `WARNING: [Timing 38-242]` — `HD.CLK_SRC` is unset on `clk_i` in
>      out-of-context mode, so **clock delay and skew were not estimated at all**.
>   3. **The largest structure in the RC vertical does not appear in the timing
>      report at any slack** (§4.4). A clean WNS here is not a claim that the
>      design is fast.
>
> **This brief changed zero lines of RTL.** Everything below is a finding. The
> fixes are later commits with their own regression arguments.

---

## 1. Verdict per unit

| Unit | Top | Verdict |
|---|---|---|
| **A** | `pcie_enum_top` | **CLEAN** — synthesized, 0 errors, 0 latches, 0 DRC violations, 4 warning classes; fails the 250 MHz placeholder by 0.317 ns |
| **B** | `pcie_rq_rc_top` | **WARNINGS** — synthesized, 0 errors, 0 latches, 0 DRC violations, 7 warning classes; **`tlp_vc_buffer` maps to 152,636 flip-flops and 54,877 LUTs**, and fails the placeholder by 1.055 ns |

Neither unit is FAILED and neither unit is LATCHES. **The brief's question (1) — does
Vivado accept this RTL at all — is answered yes for the whole RC vertical**, first try,
with no source edits and no waivers. Question (2) — inferred latches — is answered
**zero**, confirmed two independent ways per unit.

Both units were synthesized `-mode out_of_context -flatten_hierarchy none` so that
utilization and timing can name the responsible submodule.

---

## 2. Prediction vs. measurement

Falsifications first, and loudest.

### 2.1 ❌ FALSIFIED

| # | Prediction | Measurement | Why it was wrong |
|---|---|---|---|
| **§3.1b** | `tlp_vc_buffer`'s four arrays infer **distributed RAM**, ≈2,500–4,000 LUTRAM | **Registers.** `[Synth 8-11357] … 3D-RAM … data_mem_reg with 131840 registers`, `keep_mem_reg 16480`, `user_mem_reg 12360`. `vc_buffer_inst` = **54,877 LUT / 152,636 FF**, of which only **10** are LUTRAM. | I predicted the *absence* of reset would be sufficient for RAM inference. It is not. The **shape** is disqualifying: Vivado will not infer RAM from a 2-D unpacked array. Named alternative §3.1c was right. See §5.1 — the same run contains the controlled counter-example. |
| **§3.3 LUT** | Unit B ≈ **4,500** logic LUT (band 1,500–18,000) | **60,096** logic LUT | 3.3× above the band ceiling — **entirely** because of §3.1b. Subtract `vc_buffer_inst` and the rest of Unit B is **5,229 logic LUT + 768 LUTRAM**, i.e. within 16% of the point estimate. |
| **§3.3 FF** | Unit B ≈ **5,500** FF (band 2,750–11,000) | **156,634** FF | Same cause. Non-VC-buffer subtotal is **3,998 FF** — inside the band. The §3.1c alternative predicted "≈170,000 FF"; actual 156,634 is within 9% of that. |
| **§3.4** | Three largest Unit B submodules: `tlp_vc_buffer` > `tlp_request_tracker` > **`pcie_rq_if`** | `tlp_vc_buffer` (54,877) > `tlp_request_tracker` (3,047) > **`tlp_parser`** (1,439) | First two right. Third wrong: `pcie_rq_if` is only 309 LUT, sixth. I underweighted `tlp_parser`, which carries its own 1K×32 payload replay memory (§5.1). |
| **§4.2b** | Unit B's WNS is **less negative** than Unit A's — "the tracker's search is wide but shallow, the allocator's carry chain is deep" | Unit A **−0.317 ns**, Unit B **−1.055 ns**. B is **3.3× worse**. | The reasoning inverted the real cost. Unit A's chain is 11 CARRY8 — deep but on *dedicated carry silicon*, 1.674 ns of logic. Unit B's is 17 general LUT levels, only 1.479 ns of logic but **3.471 ns of routing (70%)** across a 32-tag structure with fanouts of 178 and 110. Depth in CARRY8 is cheap; width in LUTs with high fanout is not. |
| **§4.4** | **< 50** failing endpoints per unit — "localized arithmetic problems, not a globally slow netlist" | Unit A **256**, Unit B **1,366** | The *diagnosis* survives — Unit B's 61 large-setup violations are 61-for-61 `parser_inst → tracker_inst`, and Unit A's worst path is one arithmetic chain. But the endpoint **count** was off by 5× and 27×, because one slow cone fans out to many destination registers. |
| **§1.3 A-a/A-b** | Unit A emits an **index-out-of-range** warning class from `slot_r`/`cand_r` | **No such warning class exists** in either log. Unit A's only warning classes are `8-7129`, `8-11067`, `8-7080`, `38-242`. | Vivado silently builds the decoder and drops out-of-range writes. It does not warn. Prediction 14 in the summary table is dead. |

### 2.2 ✅ CONFIRMED

| # | Prediction | Measurement |
|---|---|---|
| §1.4d | Both units elaborate and synthesize to completion | Both `exit 0`, **0 `ERROR:` lines** in either log |
| **§2, all 30 blocks** | **Zero inferred latches** | **Zero, both units, two ways:** `report_utilization` "Register as Latch **0**", and a direct netlist query `get_cells -hier -filter {PRIMITIVE_SUBGROUP == LATCH}` returning **0** (`latches_netlist.txt`). No `SYNTH-*` latch rule in `report_methodology`. |
| §S1 | The enumeration FSMs cannot latch — they are single-process `always_ff`, there is no combinational next-state block | 0 latches in `u_scan`, `u_scan2`, `u_bus`, `u_bar`, `u_bar2` |
| §S2 | The 5-arm mux cannot latch — it is continuous assignment | 0 latches at the `pcie_enum_top` level (72 LUTs of pure mux) |
| §2.4 (`pcie_cfg_txn.sv:358`) | `status_outcome` has no default but the `unique case` covers all 8 of 8 values of a 3-bit selector → no latch | No latch. The highest-risk block in the vertical held. |
| §2.5 | Zero combinational loops | Zero, both units |
| §A1.1b | With the parameters `pcie_enum_top` actually instantiates, **none of the five `$warning` conditions fires**, so no message text appears | Zero occurrences of any guard's message text in the Unit A log. (`CRS_RETRY_MAX`=16 × `CRS_BACKOFF_CYCLES`=64 = 1024 < `CPL_TIMEOUT_CYCLES`=4096, so P-CRS-BUDGET holds; `MEM_BAR_BASE`=8000_0000h is 128-byte aligned; `MEM_BAR_WINDOW`≠0.) |
| §B1.1 | `$warning` inside `always_ff` is accepted and ignored — **not** promoted to an error | 10 sites, **zero** diagnostics of any kind, zero errors. Also §1.1c held: no format-string or width complaint on the enum-typed `%0d`/`%0h` arguments. |
| §1.2 | The two `initial` blocks contribute 0 LUT / 0 FF | No logic attributable to them; Unit A's area is fully accounted for by the FSMs and the allocator |
| §1.3 (9 sites) | **No construct is rejected** | All nine non-constant-index / variable-part-select sites accepted, including `merged_data[phase_r*W +: W]` as an LHS and the 2-D `data_mem[a][b]` |
| §1.4a | `tlp_crc32_dw`'s unrolled bit loop synthesizes to XOR trees with no diagnostic | `ecrc_inst` = 272 LUT / 65 FF, no diagnostic |
| §1.4b | No "case is not full" / "no default" warning | None. All 18 `unique case` sites clean. *(Correction: the predictions' §0.4 census undercounted these as 2 + 5. `INFO: [Synth 8-294]` reports 5 in Unit A and 13 in Unit B, and a re-grep agrees — 5 and 13. The verdict is unaffected; the census number was simply wrong.)* |
| §1.4c | OOC inserts no I/O buffers; many unconstrained ports | `IO = 0`; Unit A `no_input_delay 78` / `no_output_delay 1653`, Unit B `265` / `235`; `TIMING-18` ×1000 (A, capped) and ×565 (B) |
| **§3.1a** | **BRAM = URAM = DSP = 0 in both units** | Exactly 0/312, 0/96, 0/1728 in both. The asynchronous read forbids block RAM, as predicted. |
| §3.2 LUT | Unit A ≈ 3,000 (band 750–12,000) | **1,840** — inside, 1.6× low |
| §3.2 FF | Unit A ≈ 2,600 (band 1,300–5,200) | **2,207** — inside, 1.2× low |
| §3.5 | Unit A's two largest submodules are the two `pcie_enum_bar` instances, within 10% of each other | `u_bar` **802 LUT / 990 FF**, `u_bar2` **801 LUT / 990 FF** — **0.1% apart** |
| §4.0 | Unconstrained-port count is large; `check_timing` flags it | Confirmed both units |
| **§4.1** | Unit A fails 250 MHz, WNS in −3.0…0.0 ns, worst path inside a `pcie_enum_bar` instance through the 65-bit allocator | **WNS −0.317 ns.** Worst path runs `…/size_r[11]_i_9` → `size32[21]` → `addr_r[28]_i_10` → `align_mask65[33]` → `addr_r_reg[35]_i_2` → `u_bar/error_code_r_reg[0]/CE`. **The named mechanism, exactly.** |
| **§4.2** | Unit B fails 250 MHz, WNS in −2.5…0.0 ns, worst path inside the request tracker's 32-way search | **WNS −1.055 ns.** Path: `parser_inst/header_r_reg[requester_id][3]` → `tracker_inst/zombie_r[11]_i_9/_i_4/_i_3` (the 32-way match on a 16-bit `requester_id`) → `remaining_r[…]` → `result_valid_r` → `tracker_inst/remaining_r_reg[5][0]/CE`. **The named mechanism, exactly**, and all 61 `TIMING-16` violations are 61-for-61 `parser_inst → tracker_inst`. |
| **§4.2 caveat** | "`m_axis_tdata` is a port, so the VC buffer's read mux **may not appear in WNS at all** even if it is physically the slowest thing" | **`vc_buffer` appears zero times in the worst-20 paths** — 90% of the LUTs and 97% of the FFs are invisible to the timing report. See §4.4. |
| §4.3 | **Neither unit meets 250 MHz** | Neither does |

### 2.3 ⊘ NOT REACHED

| # | Prediction | Why |
|---|---|---|
| §A1.1 | `$warning` inside `initial` **prints** its message at elaboration | Untestable in this configuration — §A1.1b was right that no guard condition fires, so there was nothing to print. Whether Vivado would print it remains unmeasured. To reach it, a future run must instantiate `pcie_enum_bar` with `MEM_BAR_WINDOW = 0`. |

**Score: 20 confirmed, 7 falsified, 1 not reached.** The single root cause behind four
of the seven falsifications (§3.1b, §3.3 LUT, §3.3 FF, and the magnitude in §3.4) is
`tlp_vc_buffer`'s memory shape — §5.1.

---

## 3. Latches

**Zero. Both units. Every one of the 30 `always_comb` blocks in the RC vertical.**

Asked two independent ways, because a log grep can miss a quietly inferred latch:

```
report_utilization → "Register as Latch        0  ...  460800  0.00"   (both units)
get_cells -hier -filter {PRIMITIVE_SUBGROUP == LATCH} → 0 cells        (both units)
report_methodology → no SYNTH-* rule of any kind                        (both units)
```

`latches.txt` (the brief's log grep) is non-empty for both units, but every hit is
either script echo or `INFO: [Synth 8-802] inferred **FSM**` — the word "inferred"
matching an FSM message, not a latch. **There is no file:line to report in this section,
because there is nothing to report.**

Worth recording *why* the result was structural rather than lucky: the RC vertical
contains **no `always_latch` and no `always @(*)` at all**. Every combinational process
is `always_comb`, and each of the 30 either opens with a full default assignment or
closes every branch. The two suspects the tracker named could not have failed:
`pcie_enum_scan` and `pcie_enum_bus` have **zero** `always_comb` blocks (single-process
`always_ff` FSMs at `src/rc/pcie_enum_scan.sv:334` and `src/rc/pcie_enum_bus.sv:213`),
and `pcie_enum_top` has **zero** (the 5-arm mux is continuous assignment,
`src/rc/pcie_enum_top.sv:598-661`).

---

## 4. Area

### 4.1 Unit A — `pcie_enum_top`

| Metric | Used | Available | Util% |
|---|---|---|---|
| CLB LUTs | **1,840** | 230,400 | 0.80% |
| — as Logic | 1,840 | | |
| — as Memory | 0 | 101,760 | 0.00% |
| CLB Registers | **2,207** | 460,800 | 0.48% |
| — as Latch | **0** | | 0.00% |
| CARRY8 | 134 | 28,800 | 0.47% |
| BRAM / URAM / DSP | **0 / 0 / 0** | 312 / 96 / 1,728 | 0.00% |

Register style: 2,196 sync-reset + CE, 11 sync-set + CE. No asynchronous resets anywhere.

| Instance | Module | LUT | FF |
|---|---|---|---|
| `pcie_enum_top` | (top) | **1,840** | **2,207** |
| `(pcie_enum_top)` | the 5-arm mux, glue only | 72 | 0 |
| `u_bar` | `pcie_enum_bar` | **802** | **990** |
| `u_bar2` | `pcie_enum_bar` | **801** | **990** |
| `u_txn` | `pcie_cfg_txn` | 74 | 114 |
| `u_scan` | `pcie_enum_scan` | 39 | 53 |
| `u_scan2` | `pcie_enum_scan` | 39 | 53 |
| `u_bus` | `pcie_enum_bus` | 13 | 7 |

87% of the enumeration spine is the two BAR-phase instances, and 80% of *their* FF cost
is the 6-slot × (64-bit size + 64-bit address) result array. `pcie_enum_bus` is 13 LUTs.

### 4.2 Unit B — `pcie_rq_rc_top`

| Metric | Used | Available | Util% |
|---|---|---|---|
| CLB LUTs | **60,874** | 230,400 | **26.42%** |
| — as Logic | 60,096 | | 26.08% |
| — as Distributed RAM | 778 | 101,760 | 0.76% |
| CLB Registers | **156,634** | 460,800 | **33.99%** |
| — as Latch | **0** | | 0.00% |
| CARRY8 | 67 | 28,800 | 0.23% |
| F7 / F8 Muxes | 5,108 / 2,505 | 115,200 / 57,600 | 4.4% / 4.4% |
| BRAM / URAM / DSP | **0 / 0 / 0** | 312 / 96 / 1,728 | 0.00% |

| Instance | Module | Total LUT | Logic LUT | LUTRAM | FF |
|---|---|---|---|---|---|
| `pcie_rq_rc_top` | (top) | **60,874** | 60,096 | 778 | **156,634** |
| `u_tlp_layer/vc_buffer_inst` | `tlp_vc_buffer` | **54,877** | 54,867 | 10 | **152,636** |
| `u_tlp_layer/tracker_inst` | `tlp_request_tracker` | **3,047** | 3,047 | 0 | **2,534** |
| `u_tlp_layer/parser_inst` | `tlp_parser` (incl. ecrc, validator) | **1,439** | 671 | **768** | 238 |
| `u_tlp_layer/requester_inst` | `tlp_requester` | 432 | 432 | 0 | 128 |
| `u_tlp_layer/generator_inst` | `tlp_generator` (incl. formatter) | 394 | 394 | 0 | 200 |
| `u_rq_if` | `pcie_rq_if` (incl. downsize) | 309 | 309 | 0 | 285 |
| `u_rc_if` | `pcie_rc_if` (incl. upsize) | 197 | 197 | 0 | 488 |
| `u_tlp_layer/credit_manager_inst` | `tlp_credit_manager` | 115 | 115 | 0 | 110 |
| `u_tlp_layer/classifier_inst` | `tlp_classifier` (incl. validator) | 23 | 23 | 0 | 0 |
| `u_tlp_layer/control_inst` | `tlp_control` | 3 | 3 | 0 | 1 |

**`tlp_vc_buffer` is 90% of the LUTs and 97% of the flip-flops of the entire RC host
surface.** Everything else in Unit B — the parser, the tracker, the generator, the
credit manager, both PG213 interfaces and both gearboxes together — is **5,997 LUT and
3,998 FF**, about 3× Unit A.

### 4.3 Fit on the die *(proxy — ZU7EV standing in for ZU9EG)*

The RC vertical as it stands today, both units summed, is **62,714 LUTs (27.2%) and
158,841 FFs (34.5%)** of the ZU7EV. **§3.6 predicted "well under 10% of LUTs" and is
falsified by the VC buffer alone.**

With `tlp_vc_buffer` reshaped to the form `tlp_parser` already uses, the projection is
roughly **12,000 LUTs (~5%) and 6,300 FFs (~1.4%)** — back under the 10% line, and the
RC stops being the term that decides whether an AraXL fits beside it. That LUT figure
is an extrapolation, not a measurement: 7,837 measured LUTs outside the VC buffer, plus
≈4,300 for a reshaped 4,120×40 distributed RAM, scaled from `tlp_parser`'s **measured**
768 LUTRAM for 1,024×36 plus an output mux tree. **Candidate 1 in §6 is what would turn
it into a measurement.** As things stand today, the RC *is* the deciding term.

### 4.4 ⚠️ The timing report is blind to 90% of Unit B

`tlp_vc_buffer`'s read is a continuous assignment onto `m_dllp_axis_tdata`, an **output
port**. With no `set_output_delay` written (brief rule 6), that path is unconstrained.
So the 54,877 LUTs of 4,120:1 multiplexer that Vivado built **do not appear in the
worst-20 timing paths at all** — grep for `vc_buffer` in `timing_worst20.rpt` returns
**zero hits**.

Unit B's WNS of −1.055 ns is therefore a statement about `tlp_request_tracker`, not
about the design. `WARNING: [Netlist 29-101]` is the corroborating signal from a
different direction: *"Netlist 'pcie_rq_rc_top' is not ideal for floorplanning, since
the cellview 'tlp_vc_buffer' contains a large number of primitives."*

**Do not read a future improvement in Unit B's WNS as progress on the VC buffer.**

---

## 5. Findings the predictions did not anticipate

### 5.1 ⭐ The VC buffer's memory shape — and the in-tree counter-example

The single most valuable result of S-1, because the same synthesis run contains a
controlled experiment that isolates the cause to one variable.

| | `tlp_parser` | `tlp_vc_buffer` |
|---|---|---|
| Declaration | `logic [31:0] payload_data_mem [0:1023]` (`src/tlp/tlp_parser.sv:41`) | `logic [DATA_WIDTH-1:0] data_mem [0:PACKET_DEPTH-1][0:MAX_PACKET_WORDS-1]` (`src/tlp/tlp_vc_buffer.sv:39`) |
| Shape | **1-D** unpacked | **2-D** unpacked |
| Depth × width | 1,024 × 32 | 4,120 × 32 |
| Read | asynchronous, continuous assign (`:65`) | asynchronous, continuous assign (`:59`) |
| Write | clocked, different address (`:236`) | clocked, different address (`:94`) |
| Reset of the array | none | none |
| **Vivado result** | **`RAM64M8` × 80 — distributed RAM** | **131,840 registers** |

Every variable that could matter is held constant — same access pattern, same
asynchronous read, same absence of reset, comparable depth. **The only difference is
the second unpacked dimension**, and Vivado names it explicitly:

```
WARNING: [Synth 8-11357] Potential Runtime issue for 3D-RAM or RAM from
         Record/Structs for RAM  data_mem_reg with 131840 registers
WARNING: [Synth 8-11357] ...  keep_mem_reg with 16480 registers
WARNING: [Synth 8-11357] ...  user_mem_reg with 12360 registers
```

131,840 + 16,480 + 12,360 + 4,120 (`last_mem`, below the warning threshold) = **164,800
bits**, all flip-flops, plus a 4,120:1 mux per bit — which is where 54,877 LUTs, 5,108
F7 muxes and 2,505 F8 muxes went. Note the two *1-D* arrays in the same module DID
infer: `credit_mem` (4×12) and `class_mem` (4×2) became LUTRAM via `[Synth 8-6904]`.

The implication is that this is a **shape problem, not an architecture problem**, and
the repo already contains the proof that the correct shape works at nearly the same
depth. It is a mechanical, behaviour-preserving change — see §6, candidate 1.

### 5.2 Dead ports and dead storage

Real, small, and each one implies a data dependency that does not exist:

| Site | Finding |
|---|---|
| `src/rc/pcie_enum_bus.sv:181` | `input logic [31:0] rsp_rdata_i` is declared and **referenced exactly zero times** in the module. A dead 32-bit input, wired live at `src/rc/pcie_enum_top.sv:479`. Vivado flagged 11 of its 32 bits as unloaded. |
| `src/rc/pcie_cfg_txn.sv:196` | `input logic [AXIS_KEEP_WIDTH-1:0] m_axis_rc_tkeep_i` — declared, **never referenced**. All 4 bits unloaded. |
| `src/tlp/tlp_vc_buffer.sv:43` | `word_count_mem` is **written** (`:78`, `:94`) and **never read**. All four entries removed: `WARNING: [Synth 8-6014] Unused sequential element word_count_mem_reg[0..3] was removed`. |
| `src/rc/pcie_rc_if.sv:391` | 11 bits of the latched completion header `hdr_r` removed as unused (`8-6014`). |
| `src/tlp/tlp_generator.sv:164` | 2 bits of `header_r` removed as unused. |
| `src/tlp/tlp_payload_formatter.sv:59` | `append_index_reg` removed as unused. |

Two more are **by design** and should be left alone, recorded so a future reader does
not chase them: `pcie_cfg_txn.m_axis_rc_tdata_i` has 84 of 128 bits unloaded (it reads
exactly four RC-descriptor fields — `request_completed` b30, `completion_status` b45:43,
`tag` b71:64, and the payload Dword b127:96), and `pcie_enum_bus.header_type_i[7]` is
unread because the module tests `[6:0]` only (`:199`). All 100 of Unit B's `8-7129`
warnings are the same benign class: `pcie_rc_if` reads a small subset of the wide
`received_completion_header_i` struct.

### 5.3 Unreachable FSM states

```
WARNING: [Synth 8-3332] Sequential element (FSM_onehot_state_r_reg[2]) is unused
                        and will be removed from module tlp_completion_generator.
                        ... [1], [0]  — three states
WARNING: [Synth 8-3332] Sequential element (FSM_onehot_state_r_reg[7]) is unused
                        and will be removed from module tlp_generator.
                        ... [4]  — two states
```

Five one-hot state bits across two TL modules are **unreachable** and were deleted. This
is a coverage signal that 294 passing tests could not produce: states declared in the
enum that no input sequence can enter. Worth a look before assuming the FSMs are minimal.

### 5.4 Constants propagated through registers

`INFO: [Synth 8-3333]`, nine sites, each naming a register that is provably constant:

- `requester_inst/tag_r_reg[7]` and `tracker_inst/cpl_timeout_tag_o_reg[7]` — constant 0.
  Expected: `TAG_COUNT = 32` means tags are 0..31, so `tag[7:5]` can never be set. The
  8-bit tag port is three bits wider than the design can use. Relevant to any future
  extended-tag work.
- `error_code` bit 4 in **four** modules (`tracker_inst`, `requester_inst`,
  `parser_inst`, `completion_generator_inst`) — constant 0. The error enums are 5 bits
  wide and never use the top bit.
- `completion_generator_inst/header_r_reg[poisoned]` and `header_r_reg[fmt][0]` — constant.
- `parser_inst/header_r_reg[prefix][6]` — constant.

### 5.5 `unique case` is implemented as `parallel_case`

`INFO: [Synth 8-294]`, 5 sites in Unit A and 13 in Unit B, e.g.
`src/rc/pcie_enum_scan.sv:344`, `src/rc/pcie_cfg_txn.sv:360`.

This matters for a repo whose whole verification argument is simulation-based: `unique`
is an assertion in simulation and a **synthesis directive** in Vivado. If a `unique case`
selector ever takes a value not listed, simulation reports a violation while the netlist
silently produces don't-care behaviour. **The 294-test gate cannot see that divergence.**
No action implied here — but it is a class of simulation/synthesis mismatch the current
gate is structurally blind to, and it should inform how S-2 is scoped.

### 5.6 `parameter` inside a package

`WARNING: [Synth 8-11067]` ×3, both units: `TLP_DATA_WIDTH`, `TLP_KEEP_WIDTH`,
`TLP_MAX_PAYLOAD_BYTES` at `src/tlp/tlp_pkg.sv:4-6` are declared `parameter` inside a
package and "shall be treated as localparam". Harmless, one-line fix, and it is the only
warning class shared by both units that has an unambiguous correct answer.

### 5.7 FSM encodings Vivado chose

`INFO: [Synth 8-3354]` — one-hot for `pcie_enum_scan`, `pcie_enum_bar`, `pcie_cfg_txn`,
`pcie_rq_if`, `tlp_requester`, `tlp_completion_generator`, `tlp_generator`; **sequential**
for `pcie_enum_bus`. Recorded because the encoding is a synthesis decision the RTL does
not make and a future timing fix might want to override.

---

## 6. Ranked RTL-change candidates

**None of these was made. They are future commits, each needing its own regression
argument against the 40-target / 294-test gate.**

| # | Change | Evidence | Rough scope | Risk |
|---|---|---|---|---|
| **1** | **Reshape `tlp_vc_buffer`'s four memories from 2-D unpacked to 1-D**, indexing `{wr_packet_r, wr_word_r}` into a flat `[0:PACKET_DEPTH*MAX_PACKET_WORDS-1]` array | §5.1 — 54,877 LUT + 152,636 FF vs. `tlp_parser`'s 80 `RAM64M8` for the same access pattern | 4 declarations + 8 index expressions in one file; no port, no protocol, no state-machine change | **Low.** Behaviour-identical by construction. Must re-run the full gate; the VC buffer is exercised by the whole TL suite. Note `MAX_PACKET_WORDS=1030` is not a power of two — flattening wants `2^11` stride to keep the index a concatenation rather than a multiply. |
| **2** | **Delete `word_count_mem`** (`tlp_vc_buffer.sv:43`, `:78`, `:94`) | §5.2 — written, never read; Vivado already removes it | 3 lines | **Very low.** Netlist-neutral by definition. |
| **3** | **Break the `pcie_enum_bar` allocator's combinational chain** — register `alloc_size` (or `size_r`) one stage before the address round-up, adding one FSM state on the sizing path | §2.2 / §4.1 — Unit A's WNS −0.317 ns, 11 CARRY8 through `size32 → align_mask65 → alloc_addr65 → alloc_end65 → window_bad` | one extra state in the `S_SIZE_RD_RSP` / `S_UP_RD_RSP` arms, ×1 file (both instances inherit) | **Medium.** Adds a cycle to the BAR sizing path; the enum tests assert on transaction *sequences*, so cycle counts may be visible. Only worth doing once the target frequency is known — 231 MHz may be fine. |
| **4** | **Cut the `parser → tracker` cone** — the 32-way completion match compares a full 16-bit `requester_id_r` per tag (`tlp_request_tracker.sv:202-208`). Pre-compare against a registered ID, or pipeline the match one stage | §4.2 — Unit B's WNS −1.055 ns, 61/61 `TIMING-16` violations are this cone, 70% of the delay is routing across the 32-tag array | one `always_comb` + one pipeline register in `tlp_request_tracker` | **High.** The tracker's completion path is the most heavily tested thing in the repo (tag release, zombie quarantine, `result_last`). Do not attempt before a real frequency target exists. |
| **5** | **Remove the two dead input ports** — `pcie_enum_bus.rsp_rdata_i` (`:181`) and `pcie_cfg_txn.m_axis_rc_tkeep_i` (`:196`) | §5.2 | port lists + the `pcie_enum_top` instantiations + every bench that drives them | **Low risk, wide blast radius.** Touches testbenches. Alternatively document them as reserved. |
| **6** | **`parameter` → `localparam` in `tlp_pkg.sv:4-6`** | §5.6 | 3 words | **Very low.** |
| **7** | **Investigate the 5 unreachable FSM states** in `tlp_completion_generator` and `tlp_generator` | §5.3 | read-only investigation first | n/a — this is a question, not yet a change |

Candidates 1, 2 and 6 are behaviour-preserving and could ship as one commit with one
regression run. **Candidate 1 alone recovers roughly 90% of Unit B's LUTs and 97% of its
flip-flops** and is the only item on this list that changes the fit conversation.

Candidates 3 and 4 should wait. Both trade cycles for frequency, and **there is no
frequency target yet** — that is downstream of the GTH-attach decision. 231 MHz and
198 MHz may both be entirely adequate.

---

## 7. What S-2 should be

S-1 answered its four questions and produced one large surprise. The next increment
follows from what is now known, not from the original plan.

1. **Re-measure Unit B after candidate 1** (a one-unit re-run of the same script, no new
   infrastructure). This is the cheapest high-value action available and it settles the
   fit question. It also tests whether §3.3's original point estimate — which was within
   16% once the VC buffer is subtracted — was right all along.

2. **Extend the vertical downward: the DLL and `pcie_endpoint_top`.** S-1 deliberately
   covered only the RC. `docs/recon/RECON_STACK_INTEGRATION.md` §4A names `pcie_endpoint_top`
   (TL + DLL) and `pcie_phy_top` (PHY + LTSSM + DLL) as the other two integration tops,
   and neither has ever been through synthesis. Given that the one memory S-1 looked at
   was mapped to 164,800 flip-flops, **the DLL's retry buffer is the obvious next
   suspect** — and `pcie_endpoint_top` currently has no Verilator path either, so
   synthesis would be its first mechanical check of any kind.

3. **Sweep the 2-D-unpacked-array pattern across the whole repo.** S-1 found it by
   accident in the one module it happened to synthesize. A grep for
   `\]\s*\w+\s*\[.*\]\s*\[` over `src/` costs nothing and tells us whether §5.1 is one
   bug or a house style.

4. **Do NOT write constraints yet.** Everything in §4 is directional because the
   clocking architecture is Patrick's decision, and §4.4 shows that adding output delays
   would change Unit B's timing picture qualitatively, not marginally. Constraints are
   S-3 at the earliest, gated on GTH-attach.

5. **Consider whether §5.5 deserves its own increment.** The gate cannot see
   `unique case` simulation/synthesis divergence. That is a verification-methodology
   question rather than a synthesis one, but S-1 is where it surfaced.

---

## 8. Reproducing this

```bash
# a FRESH shell -- never the conda pcie/Verilator environment
source /home/kourosh/tools/vivado_env.sh
cd /home/kourosh/pcie_endpoint
./synth/run_s1.sh                      # both units, sequentially
./synth/run_s1.sh pcie_enum_top        # one unit
```

The driver refuses to start if `verilator` is on `PATH`. Reports land in
`~/synth_s1/<unit>/`: `vivado.log`, `utilization.rpt`, `utilization_hier.rpt`,
`timing_summary.rpt`, `timing_worst20.rpt`, `methodology.rpt`, `clocks.rpt`, `drc.rpt`,
`latches.txt` (log grep), `latches_netlist.txt` (netlist query),
`message_classes.txt`, and a `.dcp` checkpoint. Wall clock on `vlsi031`, end to end:
**Unit A 1 m 38 s** (06:44:04 → 06:45:42), **Unit B 10 m 52 s** (06:46:07 → 06:56:59) —
almost all of the difference is the 164,800-register VC buffer.
