# RECON — Stack Integration

**Scope:** read-only reconnaissance of how the layers of this design actually connect
at commit `cfea070` (branch `kourosh/dev`). Nothing is built here. This document
feeds three later wiring briefs — the DLL suite, `pcie_endpoint_top`, and a
cross-layer end-to-end — and its job is to establish what is true *now*, before any
of them is scoped.

**Method and standing caveats:**

- Every claim below carries a `path:line` reference re-derived from the code at HEAD.
- `STACK_INVENTORY.md` was cross-checked throughout. **The RTL at HEAD is
  authoritative**; where the two disagree the disagreement is stated explicitly, and
  those cases are collected in §3.
- All inherited RTL — anything not written in the Stage A–D work — is treated as
  unverified. This document describes what the code *does*. It never asserts that
  the code is correct.
- The hierarchy in §4A was rebuilt by extracting every `module` declaration under
  `src/` and `tb/` and rescanning for instantiations of those names, not by reading
  any existing document.

**Baseline at the time of writing:** cold build (`rm -rf build/`), 40 targets run
sequentially, **294 tests, 294 PASS, 0 FAIL, 0 SKIP** — decomposed tb_tlp 25/124,
RC surface 6/63, enum 8/106, conformance 1/1. The count was re-derived two
independent ways: from the run output, and by counting `@cocotb.test()` decorators
across the twenty-five `tb/tlp` and fourteen gated `tb/rc` test modules plus the
conformance target. Both give 40/294.

---

## 1. The one-paragraph answer

The stack does not exist as a stack. It exists as **three disjoint integration
islands** — `{TL}`, `{TL, DLL}` and `{PHY, LTSSM, DLL}` — and no module anywhere puts
the LTSSM and the Transaction Layer in the same netlist. The 294-test regression
gate covers the first island thoroughly and the other two not at all: the Data Link
Layer has zero targets in the gate, `pcie_endpoint_top` has no Verilator path, and
the PHY receive datapath has no test of any kind. The good news is that the seams
between the islands are all plain 32-bit AXI-Stream port pairs with matching widths,
so a cross-layer back-to-back is a wiring problem rather than a datapath problem —
and it can be built entirely above the PHY serial path, which is the part with no
coverage and no build.

---

## 2. Recon findings — the brief's four questions

## 4A — Instantiation map

### A.1 Method

The hierarchy below was re-derived at HEAD by extracting every `module` declaration
under `src/` and `tb/` and then scanning every first-party file for instantiations of
those names. It is not taken from `STACK_INVENTORY.md`; where the two disagree the
disagreement is called out.

Vendor trees (`src/verilog-axis/`, `src/verilog-pcie/`, `src/xilinx_primitives/`,
`src/async_fifo/`) are excluded from the tree drawings but are real dependencies.

### A.2 The three integration tops, and what each one omits

There are exactly **three** modules at HEAD that integrate more than one layer. None
of them is a whole stack.

**1. `pcie_rq_rc_top` — the RC-side top. TL only.**

```
pcie_rq_rc_top                       src/rc/pcie_rq_rc_top.sv:213
├── pcie_rq_if                       src/rc/pcie_rq_rc_top.sv:405
│   └── pcie_axis_dw_downsize        src/rc/pcie_rq_if.sv:395
├── tlp_layer                        src/rc/pcie_rq_rc_top.sv:454
│   ├── tlp_parser                   src/tlp/tlp_layer.sv:306
│   ├── tlp_classifier               src/tlp/tlp_layer.sv:323
│   ├── tlp_bar_decoder              src/tlp/tlp_layer.sv:330
│   ├── tlp_config_decoder           src/tlp/tlp_layer.sv:339
│   ├── tlp_requester                src/tlp/tlp_layer.sv:346
│   ├── tlp_request_tracker          src/tlp/tlp_layer.sv:372
│   ├── tlp_completion_generator     src/tlp/tlp_layer.sv:401
│   ├── tlp_control                  src/tlp/tlp_layer.sv:423
│   ├── tlp_generator                src/tlp/tlp_layer.sv:441
│   ├── tlp_vc_buffer                src/tlp/tlp_layer.sv:455
│   └── tlp_credit_manager           src/tlp/tlp_layer.sv:474
└── pcie_rc_if                       src/rc/pcie_rq_rc_top.sv:592
    └── pcie_axis_dw_upsize          src/rc/pcie_rc_if.sv:349
```

No DLL. No LTSSM. No PHY. It exposes the Data Link Layer as a **port pair**, not as
an instance: `s_dllp_axis_*` / `m_dllp_axis_*` at `src/rc/pcie_rq_rc_top.sv:286-299`.

It is also **requester-only**. The completer (CQ/CC) surface of `tlp_layer` is tied
off inside it — every `target_*` output is left open and the two ready inputs are
tied high at `src/rc/pcie_rq_rc_top.sv:519-520` and `:539`. A `pcie_rq_rc_top`
cannot answer an inbound request; it can only originate requests and consume
completions.

**2. `pcie_endpoint_top` — the EP-side top. TL + DLL.**

```
pcie_endpoint_top                    src/pcie_endpoint/pcie_endpoint_top.sv:5
├── tlp_layer                        src/pcie_endpoint/pcie_endpoint_top.sv:172
└── pcie_datalink_layer              src/pcie_endpoint/pcie_endpoint_top.sv:305
    ├── pcie_datalink_init           src/dllp/pcie_datalink_layer.sv:184
    ├── pcie_flow_ctrl_init          src/dllp/pcie_datalink_layer.sv:197
    ├── dllp_transmit                src/dllp/pcie_datalink_layer.sv:224
    │   ├── retry_management         src/dllp/dllp_transmit.sv:97
    │   ├── retry_transmit           src/dllp/dllp_transmit.sv:128
    │   └── tlp2dllp                 src/dllp/dllp_transmit.sv:163
    └── dllp_receive                 src/dllp/pcie_datalink_layer.sv:263
        ├── axis_user_demux          src/dllp/dllp_receive.sv:154
        ├── dllp_handler             src/dllp/dllp_receive.sv:188
        ├── dllp_fc_update           src/dllp/dllp_receive.sv:219
        ├── dllp2tlp                 src/dllp/dllp_receive.sv:246
        └── pcie_cfg_wrapper         src/dllp/dllp_receive.sv:280
```

No LTSSM. No PHY. It exposes the Physical Layer as a **port pair**:
`s_phy_axis_*` at `src/pcie_endpoint/pcie_endpoint_top.sv:34-39` and `m_phy_axis_*`
at `:40-45`, 32 bits wide. Link state arrives as a plain input, `phy_link_up_i` at
`:30` — the LTSSM's verdict, supplied by whoever instantiates this.

Unlike `pcie_rq_rc_top`, this one keeps the completer surface **live**: `target_*`
is exposed at `:72-88` and `completion_request_*` at `:94-105`. It can answer an
inbound request — but the answering *policy* is outside the module: something must
watch `target_*` and drive `completion_request_*`.

**3. `pcie_phy_top` — the link-side top. PHY + LTSSM + DLL.**

```
pcie_phy_top                         src/pcie_phy_core/pcie_phy_top.sv:2
├── phy_receive                      src/pcie_phy_core/pcie_phy_top.sv:227
│   ├── scrambler                    src/pcie_phy_core/phy_receive.sv:143
│   ├── ordered_set_handler          src/pcie_phy_core/phy_receive.sv:162
│   ├── block_alignment              src/pcie_phy_core/phy_receive.sv:185
│   ├── pack_data                    src/pcie_phy_core/phy_receive.sv:206
│   └── data_handler                 src/pcie_phy_core/phy_receive.sv:263
├── phy_transmit                     src/pcie_phy_core/pcie_phy_top.sv:262
│   ├── frame_symbols                src/pcie_phy_core/phy_transmit.sv:129
│   ├── scrambler                    src/pcie_phy_core/phy_transmit.sv:153
│   ├── lane_management              src/pcie_phy_core/phy_transmit.sv:175
│   └── os_generator                 src/pcie_phy_core/phy_transmit.sv:278
├── pcie_ltssm_downstream            src/pcie_phy_core/pcie_phy_top.sv:301
└── pcie_datalink_layer              src/pcie_phy_core/pcie_phy_top.sv:363
```

**No TL.** This is the only module anywhere that puts LTSSM and DLL in the same
netlist, and it stops one layer below the Transaction Layer.

### A.3 The question the brief asked

> Does any single module instantiate LTSSM + DLL + TL together on the RC side?

**No — and not on any side.** The three tops above partition the stack into
`{TL}`, `{TL, DLL}` and `{PHY, LTSSM, DLL}`. LTSSM and TL never appear in the same
netlist at HEAD. The highest integration point that exists is:

| Side | Highest integrating module | Contains | Omits |
|---|---|---|---|
| RC | `pcie_rq_rc_top` | RQ/RC gearboxes + TL | DLL, LTSSM, PHY; completer surface tied off |
| EP | `pcie_endpoint_top` | TL + DLL | LTSSM, PHY |
| Link | `pcie_phy_top` | PHY RX/TX + LTSSM + DLL | **TL** |

The FuseSoC dependency graph mirrors this: `::rc_core` depends on `::tlp_core` and
nothing else (`src/rc/rc_core.core:30-32`); it never pulls in `dllp_core`. There is
no `.core` anywhere whose dependency closure contains both `pcie_ltssm_downstream`
and `tlp_layer`.

### A.4 What the enumeration benches actually drive

The 106 enumeration tests split across eight targets and **two** DUT boundaries.

Bare targets — DUT is the enumeration engine, driven at the **PG213 AXIS RQ/RC
socket**, with the completer modelled in the bench:

| Target | Toplevel | Instantiates | Tests |
|---|---|---|---|
| `verilate_enum_txn` | `tb_pcie_enum_txn` | `pcie_cfg_txn` (`tb/rc/tb_pcie_enum_txn.sv:89`) | 17 |
| `verilate_enum_scan` | `tb_pcie_enum_scan` | `pcie_enum_top` (`tb/rc/tb_pcie_enum_scan.sv:74`) | 16 |
| `verilate_enum_bar` | `tb_pcie_enum_bar` | `pcie_enum_top` ×3 (`tb/rc/tb_pcie_enum_bar.sv:107,235,350`) | 32 |
| `verilate_enum_bus` | `tb_pcie_enum_bus` | `pcie_enum_bus` + `pcie_cfg_txn` (`tb/rc/tb_pcie_enum_bus.sv:101,137`) | 10 |

`_tlp` targets — same engine, but with a **real `pcie_rq_rc_top` behind it**, so the
on-wire TLPs are produced by the actual Transaction Layer:

| Target | Toplevel | Instantiates | Tests |
|---|---|---|---|
| `verilate_enum_txn_tlp` | `tb_pcie_enum_txn_tlp` | `pcie_cfg_txn` + `pcie_rq_rc_top` (`tb/rc/tb_pcie_enum_txn_tlp.sv:188,239`) | 11 |
| `verilate_enum_scan_tlp` | `tb_pcie_enum_scan_tlp` | `pcie_enum_top` + `pcie_rq_rc_top` (`tb/rc/tb_pcie_enum_scan_tlp.sv:175,263`) | 8 |
| `verilate_enum_bar_tlp` | `tb_pcie_enum_bar_tlp` | `pcie_enum_top` + `pcie_rq_rc_top` (`tb/rc/tb_pcie_enum_bar_tlp.sv:196,278`) | 7 |
| `verilate_enum_bridge_tlp` | `tb_pcie_enum_bridge_tlp` | `pcie_enum_top` + `pcie_rq_rc_top` (`tb/rc/tb_pcie_enum_bridge_tlp.sv:204,294`) | 5 |

`pcie_enum_top`'s own boundary is the AXIS socket: it drives `s_axis_rq_*` out and
consumes `m_axis_rc_*` in (`src/rc/pcie_enum_top.sv:260-280`).

**So the 106 enum tests exercise:** the RC enumeration sequencers (`pcie_enum_scan`,
`pcie_enum_bar`, `pcie_enum_bus`, `pcie_enum_top`), the config transaction primitive
(`pcie_cfg_txn`), and — in the four `_tlp` targets only — the RQ/RC gearboxes and the
full Transaction Layer.

**They do not exercise:** the Data Link Layer, the LTSSM, or the Physical Layer, in
any of the eight targets. `tb/rc/tb_pcie_enum_bridge_tlp.sv:10` states this plainly
in the bench's own header: *"The bench plays the Data Link Layer."* The DLL-facing
AXIS port of `pcie_rq_rc_top` is where the stimulus stops and the bench model starts.

### A.5 What the back-to-back LTSSM bench connects

`tb/ltssm/tb_ltssm_b2b.sv` instantiates **two `pcie_ltssm_downstream` instances** and
nothing else:

- Root Complex: `IS_ROOT_PORT(1)`, `LINK_NUM(1)`, at `tb/ltssm/tb_ltssm_b2b.sv:149`
- Endpoint: `IS_ROOT_PORT(0)`, `LINK_NUM(0)`, at `tb/ltssm/tb_ltssm_b2b.sv:206`

**Signal level of the cross-connect: the decoded `pcie_tsos_t` struct**, not a serial
byte stream. Each side's receive input is assigned directly from the peer's transmit
output at `tb/ltssm/tb_ltssm_b2b.sv:127-128`:

```systemverilog
ep_ordered_set_i[l] = pcie_tsos_t'(rc_ordered_set_o[l]);  // EP rx RC's lane l
rc_ordered_set_i[l] = pcie_tsos_t'(ep_ordered_set_o[l]);  // RC rx EP's lane l
```

The `ts1_valid` / `ts2_valid` / `idle_valid` strobes are recomputed in the bench
(`:135-143`) by replicating `ordered_set_handler`'s four-byte TS-ID compare, and the
transmit-complete pulse is a periodic beat (`:95`).

The bench header (`:13-40`) documents *why* this is a shim rather than the real
datapath, and the reason is directly load-bearing for 4D: `ordered_set_handler` does
not consume a `pcie_ordered_set_t`, it consumes a **serialized, scrambled PIPE byte
stream** across two user clocks. Using it for real would mean instantiating the whole
`phy_transmit` + `phy_receive` datapath per side plus a bit-exact serial loopback
including scrambler LFSR sync and TX/RX clock-domain crossing — the header estimates
this at "~80% of `pcie_phy_top` twice."

**A tie-off claim in that header does not hold at HEAD.** The header (`:56-60`)
groups `is_timeout_i`, `recovery_i`, `lanes_ts2_satisfied_i`, `config_copmlete_ts2_i`,
`from_l0_i`, `extended_synch_i` and `lane_status_i` as "unconnected/unused in the RTL
body". Re-derived against the code:

| Input | Used in `pcie_ltssm_downstream`? | In `pcie_phy_top`? |
|---|---|---|
| `is_timeout_i` (`:40`) | only inside a commented-out line, `:1036` | unconnected `()` at `pcie_phy_top.sv:315` |
| `recovery_i` (`:41`) | only inside a commented-out line, `:1036` | unconnected `()` at `:316` |
| `lanes_ts2_satisfied_i` (`:62`) | declaration only — unused | unconnected `()` at `:337` |
| `config_copmlete_ts2_i` (`:63`) | declaration only — unused | unconnected `()` at `:338` |
| `from_l0_i` (`:64`) | declaration only — unused | unconnected `()` at `:339` |
| `lane_status_i` (`:94`) | declaration only — unused | **connected** to `lane_status` at `:350` |
| `extended_synch_i` (`:89`) | **live use** — `if (extended_synch_i)` at `:1061` | **unconnected `()`** at `:348` |

The last row is a defect in inherited RTL, not in the bench: `pcie_phy_top.sv:349`
leaves `extended_synch_i` unconnected while `pcie_ltssm_downstream.sv:1061` branches
on it. `lint/waiver.vlt:5` waives `PINCONNECTEMPTY`, so this passes the build
silently. `pcie_phy_top` has no cocotb bench at HEAD, so nothing would catch it.

Note also the misspelled port `config_copmlete_ts2_i` (`pcie_ltssm_downstream.sv:63`),
propagated to both call sites.

## 4B — DLL suite wiring surprises

### B.1 The file, and a correction about its shape

`tb/dllp/test_dll_comprehensive.py`, **2701 lines** exactly — the brief's figure is
right. The "17 phases" figure needs two corrections.

**First: there is exactly ONE `@cocotb.test()` in the file.** The decorator is at
`:2296` and the function is `async def run_test(dut)` at `:2297`. Everything else is
a helper. This matters for the regression gate: landing this suite adds **1** to the
target count and **1** to the test count, not 17. Any per-phase failure surfaces as
a single failed test. Cross-check: `results_pcie_datalink.xml:4` records exactly one
`<testcase name="run_test" classname="test_dll_comprehensive" lineno="2296">`.

**Second: the file defines 18 phases; 17 run by default.** Phases are sequential
blocks inside `run_test`, each demarcated by a `# Phase N:` banner comment plus a
matching `tb.log.info("PHASE N: ...")`. Phase 15 (`:2621`) is gated behind
`if env_flag("PCIE_ENABLE_BACKPRESSURE"):` at `:2623`, and `env_flag` defaults to
`"0"` (`:109`). So 1-14 and 16-18 execute — seventeen.

| Phase | Banner | Phase | Banner |
|---|---|---|---|
| 1 | `:2330` | 10 | `:2561` |
| 2 | `:2372` | 11 | `:2573` |
| 3 | `:2421` | 12 | `:2582` |
| 4 | `:2481` | 13 | `:2599` |
| 5 | `:2511` | 14 | `:2606` |
| 6 | `:2519` | **15** | `:2621` — **env-gated off** |
| 7 | `:2537` | 16 | `:2655` |
| 8 | `:2545` | 17 | `:2664` |
| 9 | `:2552` | 18 | `:2672` |

`STACK_INVENTORY.md:112` ("18 phases") and `:670` ("all 17 mandatory phases…
1-14 and 16-18") are both correct once the gate is understood.

### B.2 DUT top

`pcie_datalink_layer`, declared at `src/dllp/pcie_datalink_layer.sv:15` (419 lines).
The Makefile and the Python agree: `Makefile:15` sets
`TOPLEVEL := pcie_datalink_layer` and `Makefile:18` sets
`MODULE := test_dll_comprehensive`; the Python's own guard function
`require_dut_signals()` (`:135-181`) names the top in its failure text at `:178-180`.
All 36 signals that guard checks are real ports, and the four parameter defaults the
Python assumes (`:93-96`) match the RTL defaults at
`src/dllp/pcie_datalink_layer.sv:24-27` exactly — so no `parameters:` override is
needed.

### B.3 Why `--public-flat-rw` — and the surprise that it is already there

The suite never **writes** an internal signal; every `.value =` targets a top-level
port. What it does is **read** internals through a dotted-path resolver,
`get_internal_handle()` at `:471-483`, whose own error text states the requirement:
*"Required internal signal '{}' is unavailable. Compile VCS with `-debug_access+all`
or expose this status at the top level."* `--public-flat-rw` is the Verilator
spelling of that.

The paths it resolves, all verified as non-ports:

| Read at | Path | Declared |
|---|---|---|
| `:2173`, `:2193` | `dllp_transmit_inst.retry_err` | `src/dllp/dllp_transmit.sv:92` |
| `:1770` | `…tlp2dllp_inst.*h_credit_limit_r` | `src/dllp/tlp2dllp.sv:136,142,146` |
| `:1771` | `…tlp2dllp_inst.*d_credit_limit_r` | `src/dllp/tlp2dllp.sv:138,140,144` |
| `:1926-1938` | 12 × `*_credits_consumed_r` / `*_credit_limit_r` | `src/dllp/tlp2dllp.sv:123-146` |

Without the flag Verilator inlines and prunes these, `hasattr()` fails, and the run
dies at `:476` in Phase 11.

**The surprise: edalize injects `--public-flat-rw` unconditionally.** The generated
command file for a target whose `.core` does *not* list it —
`build/fusesoc_pcie_tb_tlp_1.0.0/verilate_tlp_cfg1_spine/fusesoc_pcie_tb_tlp_1.0.0.vc`
— contains `--vpi` and `--public-flat-rw --prefix Vtop` on lines 5-6, while the
source target `tb/tlp/tb_tlp.core:287-297` lists only `-Iincludes/` and `waiver.vlt`.
The same holds for `verilate_tlp_request_tracker` and `verilate_tlp_comb`.

So the explicit `--public-flat-rw` at `tb/tlp/tb_tlp.core:466`,
`tb/ltssm/tb_ltssm.core:158,177` and
`tb/ltssm_conformance/tb_ltssm_conformance.core:52` is a **no-op under FuseSoC**. It
is only load-bearing when the suite is driven directly through cocotb's
`Makefile.sim`. Listing it in a new `.core` is harmless and self-documenting.

### B.4 Other Verilator-hostile constructs in the compile set

| Construct | Finding |
|---|---|
| `#` delays | exactly one — `#1;` at `src/dllp/dllp_receive.sv:366`, inside the `ifdef COCOTB_SIM` dump block. Needs `--timing` only if `COCOTB_SIM` is defined |
| `force` / `release` | none |
| `initial` with timing | only the dump block above; the other three are zero-delay parameter checks (B.6) |
| x/z in RTL | one literal, `RESP_X = 'X` in an enum at `src/packages/pcie_datalink_pkg.sv:27`; no x/z-dependent logic |
| x/z in the **testbench** | six `is_resolvable` assertions — `:1943`, `:2175`, `:2201`, `:2279`, `:2282`, `:2294`. Under 2-state Verilator these **pass vacuously**: they do not fail, they simply stop testing anything |
| `$display`/`$monitor`/`$random`/`$time` | none |
| timescale | only 12 of 34 files carry one, so Verilator emits `TIMESCALEMOD` unless `timescale:` is set. FuseSoC's `timescale: 1ns/1ns` covers it |

The six vacuous `is_resolvable` checks are worth flagging: they are the kind of
assertion that reads as coverage in a diff and provides none under Verilator.

### B.5 What a `.core` + Makefile target would need

*Listing only — no `.core` was written in this brief.*

The union of `src/dllp/dllp_core.core:8-10`, `dllp_receive.core:8-12` and
`dllp_transmit.core:8-12` reproduces the Makefile's DLL module list exactly, and
`dllp_core`'s dependency closure (`:12-19`) covers packages, crc, bram, axis, lint
and pcie_config. So:

**Filesets**
1. `rtl` — `depend: [fusesoc:pcie:dllp_core]`, no `files:` needed; the whole closure
   arrives transitively. **`fusesoc:pcie:axis` does not need to be named** — it
   arrives via `src/dllp/dllp_core.core:16`. (`STACK_INVENTORY.md:653` recommends
   adding it explicitly; that is redundant, though harmless.)
2. `cocotb_dll_comprehensive` — one entry,
   `test_dll_comprehensive.py : {file_type: user, copyto: .}`. **No other Python
   file is needed**: the suite imports only stdlib, `cocotb`, `cocotbext.axi` and
   `cocotbext.pcie.core.{dllp,tlp}` (`:27-48`). It does not import `pcie_base`,
   `pcie_sequences`, `dllp_agent`, `phy_agent` or `tlp_agent`.

**Target** (`flow: sim`, `tool: verilator`)
- `cocotb_module: test_dll_comprehensive`
- `toplevel: [pcie_datalink_layer]`
- `timescale: 1ns/1ns` — required, mixed-timescale sources
- `filesets: [rtl, cocotb_dll_comprehensive]`
- `verilator_options:` `waiver.vlt`; `--public-flat-rw` (redundant, list anyway);
  `--timing` only if `COCOTB_SIM` ends up defined
- **no `--trace-fst`** — see B.6
- no `parameters:` override

**Makefile target.** The root `Makefile` has no FuseSoC-driven DLL rule today; every
existing DLL invocation goes through cocotb's `Makefile.sim` (`Makefile:196`). A new
rule would be a `fusesoc run --target=<name> fusesoc:pcie:tb_dllp_core` invocation
against the `pcie-endpoint-controller` library in `fusesoc.conf:1-5`.

**Delta to be aware of:** the FuseSoC route compiles **five files the Makefile does
not** — `pcie_phy_pkg.sv`, `Crc16Gen.sv`, `bram_sp.sv`, `axis_adapter.v`,
`axis_async_fifo.v` — and **skips two** the Makefile lists, `axis_mux.v` and
`axis_demux.v`. All five extras exist on disk and none is instantiated in the DLL
hierarchy. Two of them carry procedural `$error` blocks (B.6).

### B.6 FST mechanism: **RTL-embedded, not flag-driven**

The dump is written into the RTL itself. `src/dllp/dllp_receive.sv:361-368`, the last
thing in the file before `endmodule`:

```systemverilog
  // the "macro" to dump signals
`ifdef COCOTB_SIM
  initial begin
    $dumpfile("dllp_receive.fst");
    $dumpvars(0, dllp_receive);
    #1;
  end
`endif
```

- `$dumpfile("dllp_receive.fst")` at **`:364`** — hardcoded name, no path, no env
  override; it lands in whatever the simulation CWD is.
- `$dumpvars(0, dllp_receive)` at **`:365`** — level `0` means the **entire subtree**:
  `dllp_handler`, `dllp2tlp`, `dllp_fc_update`, `axis_user_demux`,
  `pcie_cfg_wrapper` and every `axis_register`/`axis_fifo` beneath. That recursive
  scope over a 1.2 ms run is the ~66 MB.
- The whole block is guarded by `` `ifdef COCOTB_SIM ``.

**Who defines `COCOTB_SIM`: every Icarus target does, and no Verilator target does.**
The Icarus targets pass `-g2012 -DCOCOTB_SIM` — `src/dllp/dllp_receive.core:30`,
`dllp_core.core:28`, `dllp_transmit.core:29`, `tb/dllp/tb_dllp.core:26`,
`tb_dllp_receive.core:25`, `tb_dllp_transmit.core:23`, and fifteen more. The
generated Verilator command files under `build/` contain no `-D` or `+define+` at
all — independently confirmed: `grep -rl COCOTB_SIM build/` returns nothing after a
full 40-target sweep.

**So under FuseSoC + Verilator the dump block is preprocessed away entirely** — no
`$dumpvars`, no `#1`, no FST. That is why the 40-target sweep in step 3 emitted zero
waveform files. Under cocotb's own `Makefile.sim`, cocotb defines `COCOTB_SIM`
itself, which is why `STACK_INVENTORY.md:684-686` reports Verilator printing
`$dumpvar ignored, as Verilated without --trace`.

**Nothing was modified over this**, per the brief. The practical consequence for a
future `.core`: `tb/dllp/tb_dllp.core:41-43`, `tb_dllp_receive.core:38,50` and
`tb_dllp_transmit.core:36` all carry `--trace-fst`, so a new target that copies one
of them *and* ends up with `COCOTB_SIM` defined would recreate the 66 MB dump.
**Omit `--trace-fst`.** `docs/predictions/SPEC_PREDICTIONS_ENUM.md §E.11` already records this lesson
from the tb/rc side, and `tb/rc/tb_rc.core:393-397` states that `--trace-fst` was
removed from every functional target and survives only in the two opt-in `_trace`
targets, which are not part of the regression gate.

**The ~66 MB figure itself is NOT VERIFIED** — no `dllp_receive.fst` exists in the
tree at HEAD. The mechanism that would produce it is verified above.

### B.7 `$error` in the DLL compile set

Scanned all 34 files from `Makefile:24-57`.

- **`$fatal`: zero. `$stop`: zero. SystemVerilog `assert`/`assume`/`cover`: zero.**
- **All 15 `$error` occurrences are procedural**, inside zero-delay `initial` blocks.
  None is an assertion action block — the distinction the brief asks about resolves
  cleanly, because there are no assertion-form `$error`s at all.

All fifteen follow the same vendored parameter-sanity idiom
(`initial begin if (<param expr>) begin $error(...); $finish; end end`):

| File | `initial` at | `$error` lines |
|---|---|---|
| `src/verilog-axis/rtl/axis_fifo.v` | `:143` | `:145, 150, 155, 160, 165, 170, 175` |
| `src/verilog-axis/rtl/axis_arb_mux.v` | `:101` | `:104, 109` |
| `src/verilog-axis/rtl/axis_demux.v` | `:102` | `:105, 110` |

**None is reachable at `--top-module pcie_datalink_layer`:**

1. `axis_demux.v` is never instantiated in the DLL hierarchy — `axis_user_demux.sv`
   uses two `axis_register` instances (`:126`, `:161`), not `axis_demux`. Verilator
   elaborates only the tree under the top, so its `initial` never runs.
2. `axis_arb_mux.v` is instantiated three times
   (`src/dllp/pcie_datalink_layer.sv:321`, `:361`, `src/dllp/dllp_transmit.sv:204`).
   `UPDATE_TID` is not overridden at any site, so the guard at `:102` is false and
   both branches are dead.
3. `axis_fifo.v` is instantiated once (`src/dllp/dllp2tlp.sv:663`). Walking all seven
   guards with the parameters actually passed (`LAST_ENABLE(1)`, `FRAME_FIFO(1)`,
   `USER_BAD_FRAME_MASK('1)`, `DROP_BAD_FRAME(1)`, `DROP_WHEN_FULL(0)`,
   `DROP_OVERSIZE_FRAME` defaulting to `FRAME_FIFO`=1, `MARK_WHEN_FULL` defaulting
   to 0) — **all seven evaluate false.**

⚠️ **The FuseSoC route adds two more files with the same idiom** that the Makefile
never compiles: `src/verilog-axis/rtl/axis_adapter.v` (`$error` at `:103, 108, 113`)
and `src/verilog-axis/rtl/axis_async_fifo.v` (`$error` at `:153, 158, 163, 168, 173,
178, 183`). Neither is instantiated in the DLL hierarchy either, so neither
elaborates — but this is the one behavioural delta between "what the Makefile
compiles" and "what a `.core` depending on `fusesoc:pcie:axis` compiles", and it is
worth knowing before the first red target gets blamed on something else.

**Nothing was changed.** Report only, per the brief's standing `$warning` rule.

## 4C — `pcie_endpoint_top` target state

### C.1 Headline: the two recorded blockers are gone, and the doc that records them is stale

`STACK_INVENTORY.md:775-812` (§5.6) states that `tb_pcie_endpoint_top.sv` "does not
elaborate — in any simulator, VCS included", for two reasons: four timeout signals
never declared in the harness, and two `tlp_layer` pins missing on the
`pcie_endpoint_top` instantiation. **Neither holds at HEAD.**

- The four signals **are** declared, at `tb/endpoint/tb_pcie_endpoint_top.sv:132-135`.
- The two pins **are** connected named-empty, at
  `src/pcie_endpoint/pcie_endpoint_top.sv:241-242`, with a comment at `:238-240`
  explaining the choice: named-empty rather than omitted so `PINMISSING` stays
  enabled for genuine omissions.

Both were repaired by commit `08b05d0` ("fix: repair pcie_endpoint_top pin
connections and testbench declarations"), which is an ancestor of HEAD and postdates
`8544a2f`, the commit that wrote `STACK_INVENTORY.md`. The doc's cited line numbers
(`tb:155`, `tb:171`, `tb:127`) do not correspond to anything at HEAD — the
instantiation is now `tb/endpoint/tb_pcie_endpoint_top.sv:164-180` with the `.*` at
`:179`.

What §5.6 still gets right: `pcie_endpoint_top` has **no Verilator coverage**. Its
only runnable target is `tb/endpoint/tb_pcie_endpoint_top.core:16`, pinned
`tool: vcs` (`:19`).

### C.2 Port/parameter mismatch table — there are no mismatches

Every `dut.<name>` the Python touches was diffed against the 113 ports of
`src/pcie_endpoint/pcie_endpoint_top.sv:28-149` and the top-level declarations in
`tb/endpoint/tb_pcie_endpoint_top.sv:12-162`.

**Result: zero mismatches — no missing signal, no width mismatch, no wrong
direction, no rename.** The reverse direction also holds: all 113 DUT ports are
declared at tb top level, so the `.*` at `tb:179` has nothing to fail on.
Parameter-derived widths agree too — `BAR_COUNT(1)` (`tb:169`) makes `target_bar_o`
`[0:0]` (`top:86`) and the tb declares 1 bit (`tb:70`); `TAG_COUNT` defaults to 32
(`top:11`) making `outstanding_o` `[5:0]` (`top:149`), and the tb declares `[5:0]`
(`tb:136`).

The only names not on the DUT are two tb-internal tap buses,
`mid_tx_axis_*` (`tb:151-156`) and `mid_rx_axis_*` (`tb:157-162`), which are
hierarchical observation points on `dut.tlp_to_dll_*` (`top:152-157`) and
`dut.dll_to_tlp_*` (`top:159-164`) — the TL↔DLL seam, tapped so a test can compare
what the TL emitted against what the DLL wrapped.

Those taps are **hierarchical references into the DUT's internals** (e.g.
`wire [31:0] mid_tx_axis_tdata = dut.tlp_to_dll_tdata;` at `tb:151`), which is the
same class of access that makes the DLL suite need `--public-flat-rw` (§4B.3). Here
the reference is resolved in SystemVerilog at elaboration rather than through VPI at
runtime, so it does not depend on the flag — but it is worth noting that this
harness, like the DLL one, is built around observing the layer seam from inside.

### C.3 The two on-record claims, re-derived

**(a) "the four timeout signals are declared-but-unasserted."** The count is right;
the word "unasserted" needs splitting.

| Signal | Declared | Driven in the RTL? |
|---|---|---|
| `cpl_timeout_valid_o` | `top:145` | yes — `tlp_layer_inst` output, `top:300` |
| `cpl_timeout_tag_o` | `top:146` | yes — `top:300` |
| `late_cpl_valid_o` | `top:147` | yes — `top:301` |
| `late_cpl_tag_o` | `top:148` | yes — `top:301` |
| (`outstanding_o`) | `top:149` | yes — `top:302` (same sideband group, not timeout-named) |

All five are driven, tracing back through `tlp_layer.sv:396-397` to
`tlp_request_tracker.sv:255,257,284,322`. So "unasserted" is **false** if it means
undriven in RTL, and **true** if it means nothing in the verification asserts on
them — `test_pcie_endpoint_top.py` contains zero accesses to any of them, which the
harness says of itself at `tb:127-128` ("Observed-only here -- nothing in this bench
asserts on them yet").

A consequence worth recording: the tb does not override `CPL_TIMEOUT_CYCLES`
(`tb:164-174` overrides ten other parameters but not this one), so the default 4096
(`top:14`) applies. At the 8 ns clock (`test_pcie_endpoint_top.py:139`) that is
32.768 µs. Test T3 issues a `MEM_READ` at `:308` that is never completed; if that
test ever ran past ~33 µs a completion timeout would fire silently and unobserved.

**(b) "the timeout tag ports are hard-coded `[7:0]`."** Confirmed verbatim:

```
src/pcie_endpoint/pcie_endpoint_top.sv:146:    output logic [7:0]  cpl_timeout_tag_o,
src/pcie_endpoint/pcie_endpoint_top.sv:148:    output logic [7:0]  late_cpl_tag_o,
```

and the literal propagates unbroken down through `tlp_layer.sv:154,156` to
`tlp_request_tracker.sv:147,149`.

**There is no `TAG_WIDTH` parameter being ignored — no such parameter exists.**
`TAG_WIDTH` appears only in vendored third-party example code under
`src/verilog-pcie/example/`. The real parameter is `TAG_COUNT` (`top:11`,
`tlp_layer.sv:8`, `tlp_request_tracker.sv:108`, default 32), from which the tracker
derives `TAG_INDEX_WIDTH = TAG_COUNT <= 1 ? 1 : $clog2(TAG_COUNT)`
(`tlp_request_tracker.sv:165`) and uses that for all internal indexing. So the design
carries two parallel tag widths: an 8-bit port/wire width and a `$clog2(TAG_COUNT)`
internal index width.

At the default `TAG_COUNT=32` the 8-bit port is three bits wider than needed and
harmless — `cpl_timeout_tag_o <= 8'(scan_index_r)` (`tracker:284`) zero-extends. The
8-bit choice is defensible on spec grounds, since `tlp_header_t.tag` is itself
`logic [7:0]` (`src/tlp/tlp_pkg.sv:90`). But it is **silently wrong for
`TAG_COUNT > 256`**: `allocate_tag_o = search_index[7:0]` (`tracker:193`) and the
match at `tracker:204` both truncate, and no elaboration assertion guards it.
By contrast `outstanding_o` **is** parameterised, `[$clog2(TAG_COUNT+1)-1:0]`
(`top:149`, `tlp_layer.sv:157`, `tracker:151`) — the asymmetry is real, and the tb
comment at `tb:127-131` documents it with citations that are correct at HEAD.

### C.4 What the five tests actually claim

Tests are at `test_pcie_endpoint_top.py:239, 260, 300, 329, 352` (380 lines total).
All five share a preamble that asserts `fc_ph_o == 32`, `fc_nph_o == 32`,
`fc_cplh_o == 32` after flow-control init (`:211-213`) — content-asserting, and the
only checks on flow control anywhere. The **data** credits `fc_pd_o` / `fc_npd_o` /
`fc_cpld_o` are never asserted.

| Test | Line | What it claims | Assessment |
|---|---|---|---|
| `application_input_reaches_data_link_output` | 240 | A MemWr command emitted by the TL arrives byte-identical in the DLL frame body | `link_packet[2:-4] == mid_tlp` (`:252`) is strong. But `assert payload in mid_tlp` (`:256`) only checks the 8 payload bytes appear *somewhere* — fmt/type, address, length, BEs, requester ID and tag are all unchecked |
| `physical_input_reaches_target_through_mid_layer` | 261 | An injected MemWr TLP reaches the completer surface intact | **The strongest test in the file.** `stripped_tlp == raw_tlp` (`:296`) and payload equality (`:297`) plus `target_offset_o == 0x80` (`:291`). Note `saved_header` at `:285-286` is compared only against itself — that proves stability, not correctness |
| `data_link_nak_replays_transaction_layer_packet` | 301 | A NAK causes byte-exact replay | `replay == first` (`:320`) is byte-exact, but the tb sets `REPLAY_TIMER_CYCLES(64)` (`tb:173`) = 512 ns, so a **spontaneous timer-driven** retransmission satisfies it identically. The test cannot distinguish NAK-caused from timer-caused replay. The trailing ACK (`:322-326`) has no assertion at all |
| `corrupted_link_input_is_rejected_with_nak` | 329 | A bad LCRC is NAKed and not forwarded | `nak.seq == 0xFFF` (`:346`) — but `0xFFF` is the reset "nothing received yet" value, so a DUT that unconditionally NAKs `0xFFF` passes. **No positive control**: a completely dead RX path also passes the 32-cycle negative check at `:348-349` |
| `flow_control_blocks_and_releases_mid_layer` | 352 | Zero credits block the TX, restored credits release it | `assert not mid_capture.done()` (`:371`) is a single-instant read with no dwell. The release check (`:380`) does not establish the UpdateFC *caused* the release. Also, whether "advertise 0" starves a pool at all depends on the credit manager's absolute-vs-incremental model — unproven here |

Three of the five (T1, T3, T5) rest on the same `link_packet[2:-4] == mid_tlp`
self-consistency check. That proves the DLL faithfully wraps whatever the TL
produced; it says nothing about whether the TL produced a spec-correct TLP. **No
test in the file decodes or asserts a single header field of a TLP the DUT
originated.** Both the TX and RX paths also share one unvalidated LCRC model
(Python's `zlib.crc32`, `:56`), so a systematic CRC error would cancel out.

### C.5 An integration gap in the RTL, found while auditing the port lists

Both instantiations are complete — every child port connected, no extra ports, no
duplicates (`tlp_layer`: 116/116 at `top:186-302`; `pcie_datalink_layer`: 48/48 at
`top:316-363`). But six DLL outputs are connected named-empty at `top:355-360`, and
four of them matter:

```
top:355:      .ext_tag_enable_o(),
top:356:      .rcb_128b_o(),
top:357:      .max_read_request_size_o(),
top:358:      .max_payload_size_o(),
```

These are the DLL's **config-space-derived** device settings. The transaction
layer's corresponding inputs are instead driven from top-level ports —
`.extended_tag_enable_i(extended_tag_enable_i)`, `.max_payload_bytes_i(...)`,
`.max_read_bytes_i(...)`, `.rcb_128b_i(...)` at `top:196-199`, from ports `top:48-51`.

**So whatever a Root Complex writes into this endpoint's config space for Extended
Tag, RCB, Max Payload Size or Max Read Request Size is discarded and never reaches
the Transaction Layer.** The representations differ as well — the DLL emits `[2:0]`
encoded fields (`pcie_datalink_layer.sv:80-81`) while the TL expects `[12:0]` byte
counts (`tlp_layer.sv:30-31`) — so a direct wire would not have type-matched either.
A decode stage is missing. This is a functional gap in inherited RTL, not a wiring
error, and no test at HEAD would see it.

Also noted: `.PCIE_WIRE_ORDER(1'b1)` (`top:180`) overrides the child default of
`1'b0` (`tlp_layer.sv:13`) and is not exposed as a top-level parameter, so wire order
is fixed at this integration point.

### C.6 The core file, and the elaboration question

`tb/endpoint/tb_pcie_endpoint_top.core` is 23 lines. VLNV
`fusesoc:pcie:tb_endpoint_protocol:1.0.0` (`:3`). One target, `sim` (`:16`), with
`tool: vcs` (`:19`), `cocotb_module: test_pcie_endpoint_top` (`:20`),
`timescale: 1ns/1ps` (`:21`), toplevel `tb_pcie_endpoint_top` (`:23`). One fileset
`tb` (`:7`) depending on `fusesoc:pcie:endpoint_protocol:1.0.0` (`:13`).

It is the **only** non-vendored `.core` in the repo that names `vcs` as its sim tool.

**On `-Wall`:** the file has no `verilator_options` block at all, so there is no
`-Wall`, no `waiver.vlt`, and no `-Iincludes/`. The on-record "no `-Wall`" note is
consistent but slightly misleading — there is nothing here to omit it *from*. For
contrast, every working `verilate_*` target in `tb/tlp/tb_tlp.core` passes
`-Iincludes/` + `waiver.vlt` and not `-Wall`; the one place `-Wall` does appear is
the lint target at `src/dllp/dllp_core.core:49`.

`pcie_endpoint_top.sv` is referenced by exactly one core,
`src/pcie_endpoint/pcie_endpoint.core:9`. Two targets would build it:
`pcie_endpoint.core:16` (`default`, but it declares no `flow:` and no tool, so it is
elaboration-only with no simulator behind it) and the VCS-pinned `sim` above.
**No Verilator target anywhere in the repository builds `pcie_endpoint_top.sv`.**

### C.7 Elaboration at HEAD — it works, and it no longer needs the waiver

**Measured, this session. Elaboration only — no test was run** (`--lint-only` stops
after elaboration).

```
verilator --lint-only --timescale 1ns/1ns lint/waiver.vlt \
          --top-module tb_pcie_endpoint_top <55 sources>
```

Source list is the dependency closure of `tb/endpoint/tb_pcie_endpoint_top.core`:
its `tb` fileset, plus `fusesoc:pcie:endpoint_protocol` (`pcie_endpoint.core:9`),
plus that core's `::tlp_core` and `fusesoc:pcie:dllp_core` dependencies
(`pcie_endpoint.core:12-13`) and their transitive closure.

**Result: exit 0. Zero errors, zero warnings.** Verilator 5.050, 56 modules from
21.779 MB of sources, walltime **131.4 s** (elaboration 130.9 s).

Three things follow.

1. **`STACK_INVENTORY.md:779-781`'s "does not elaborate — in any simulator, VCS
   included" is false at HEAD.** It was true when written; `08b05d0` fixed it.

2. **`-Wno-PINMISSING` is no longer required.** `lint/waiver.vlt` waives
   `PINCONNECTEMPTY` but **not** `PINMISSING` (the file lists 14 rules and
   `PINMISSING` is not among them), and `PINMISSING` is a warning Verilator exits
   on. A clean exit 0 without that flag is therefore positive proof that no
   instantiation in this hierarchy has a missing pin — which is exactly what
   `STACK_INVENTORY.md:786-798` recorded as the second open blocker. The
   named-empty connections at `pcie_endpoint_top.sv:241-242` are what closed it,
   and the comment there (`:238-240`) explicitly says they were written named-empty
   rather than omitted so that `PINMISSING` would stay useful for real omissions.
   That choice is now doing its job.

3. **The "~83 s" note is stale on timing but right in spirit.** Measured 131.4 s
   here. That is machine- and load-dependent and not worth chasing; the point that
   matters for a later brief is that this is a **two-minute elaboration**, roughly
   50× the cost of a typical `verilate_tlp_*` target, so it should not be added to
   the regression gate casually.

**What this does not establish.** Elaboration is not execution. The five tests in
`test_pcie_endpoint_top.py` remain unrun, and §4C.4 gives reasons to expect at least
two of them to be weak once they do run. Nothing here says the DUT behaves
correctly — only that it builds.

## 4D — `end_to_end`: what it was actually scoped to, and a b2b proposal

### D.1 The premise correction: `end_to_end` is not a stack increment

The brief asks which two module stacks the S-rated `end_to_end` increment was scoped
to connect, and whether the PHY serial path is inside or outside that scope. The
answer is that the question does not apply, because **`end_to_end` never left the
Transaction Layer.**

`STACK_INVENTORY.md:650` rates it S with the reason: *"New `cocotb_end_to_end`
fileset + target with `toplevel: tlp_layer`. No SV wrapper needed."* Re-derived from
the code:

- The test is `tb/tlp/test_tlp_end_to_end.py` — 455 lines, **4** `@cocotb.test()`
  functions at `:255, :305, :369, :423`.
- Its toplevel is `tlp_layer`, and its RTL source list is the existing
  `TLP_RTL_SOURCES` (`Makefile:92-108`), driven by the VCS target
  `tlp-test-end-to-end` at `Makefile:168-169`.
- `STACK_INVENTORY.md:634-636` says elaboration is already proven by
  `verilate_tlp_compile`, which shares the same toplevel and source list.

So "end to end" here means **end to end within the TL** — a command in at
`command_*`, a TLP out at the DLL-facing AXIS port, a completion back in, a tag
retired. It connects no two stacks. It crosses no layer boundary. The PHY serial
path is outside its scope for the trivial reason that so is every layer other than
the TL.

**It is still unported at HEAD.** There is no `verilate_tlp_end_to_end` target in
`tb/tlp/tb_tlp.core`. Two other TL test modules are in the same state:
`tb/tlp/test_tlp_ecrc.py` (1 test) and `tb/tlp/test_tlp_vc_buffer.py` (1 test) have
no `verilate_*` target either, though `tb_tlp_ecrc.sv` and `tb_tlp_vc_buffer.sv`
both exist. That is 6 written-but-unrun tests sitting in `tb/tlp/` alone.

### D.2 What a real cross-layer end-to-end would have to connect

From 4A, the stack partitions into `{TL}`, `{TL, DLL}` and `{PHY, LTSSM, DLL}`, and
the seams between them are ordinary 32-bit AXI-Stream port pairs:

| Seam | Exposed by | Width |
|---|---|---|
| TL ↔ DLL | `pcie_rq_rc_top.s_dllp_axis_*` / `m_dllp_axis_*` (`src/rc/pcie_rq_rc_top.sv:286-299`) | 32b data, 4b keep, 3b user |
| TL ↔ DLL | `pcie_datalink_layer.s_tlp_axis_*` / `m_tlp_axis_*` (`src/dllp/pcie_datalink_layer.sv:33-45`) | 32b data, 4b keep, 3b user |
| DLL ↔ PHY | `pcie_datalink_layer.s_phy_axis_*` / `m_phy_axis_*` (`src/dllp/pcie_datalink_layer.sv:47-60`) | 32b data, 4b keep, 3b user |
| DLL ↔ PHY | `pcie_endpoint_top.s_phy_axis_*` / `m_phy_axis_*` (`src/pcie_endpoint/pcie_endpoint_top.sv:34-45`) | 32b data, 4b keep, 3b user |

**These mate directly.** `TL_DATA_WIDTH`/`TL_KEEP_WIDTH`/`TL_USER_WIDTH` on
`pcie_rq_rc_top` (32/4/3, `src/rc/pcie_rq_rc_top.sv:221-223`) equal
`DATA_WIDTH`/`KEEP_WIDTH`/`USER_WIDTH` on `pcie_datalink_layer` (32/4/3,
`src/dllp/pcie_datalink_layer.sv:19-22`). No gearbox, no adapter.

The flow-control interface mates too, and in the right direction: the DLL **emits**
`fc_initialized_o`, `fc_update_valid_o`, `fc_ph_o`, `fc_pd_o`, `fc_nph_o`,
`fc_npd_o`, `fc_cplh_o`, `fc_cpld_o` (`src/dllp/pcie_datalink_layer.sv:65-73`) and
`pcie_rq_rc_top` **consumes** exactly that set as inputs
(`src/rc/pcie_rq_rc_top.sv:230-239`). Today the enum `_tlp` benches drive those
inputs from a Python model; a real DLL would drive them from silicon.

The one signal with no producer on either side is **`link_up_i`**
(`src/rc/pcie_rq_rc_top.sv:227`) / **`phy_link_up_i`**
(`src/pcie_endpoint/pcie_endpoint_top.sv:30`). That is the LTSSM's verdict, and
since no module integrates LTSSM with TL (4A.3), it has to be driven by the bench.

### D.3 PROPOSAL — a TL ↔ DLL ↔ DLL ↔ TL back-to-back

*Everything in this section is a proposal on paper. It is not a design commitment,
nothing here was built, and no `.core` or RTL was written for it.*

**Closest existing template:** `tb/rc/tb_pcie_enum_bridge_tlp.sv`. It already
instantiates a real `pcie_enum_top` in front of a real `pcie_rq_rc_top`
(`:204`, `:294`) and models the DLL in the bench. The proposal is to delete that
model and put real silicon where it was. The second template is
`tb/ltssm/tb_ltssm_b2b.sv`, for the *shape* of a two-peer harness with no Python
driving the protocol.

**Topology.** Two asymmetric sides, because the two tops are asymmetric:

```
  RC side                                          EP side
  ───────                                          ───────
  pcie_enum_top                                    pcie_endpoint_top
    │ s_axis_rq_* / m_axis_rc_* (128b PG213)         ├── tlp_layer
    ▼                                                └── pcie_datalink_layer
  pcie_rq_rc_top   (pcie_rq_if + tlp_layer + pcie_rc_if)      │
    │ m_dllp_axis_* / s_dllp_axis_* (32b)                     │
    ▼                                                         │
  pcie_datalink_layer  (standalone, RC-side)                  │
    │ m_phy_axis_* / s_phy_axis_* (32b)                       │ m_phy_axis_* / s_phy_axis_*
    └──────────────── cross-wired ────────────────────────────┘
```

Cross-connect, mirroring `tb_ltssm_b2b.sv:127-128`: RC `m_phy_axis_*` →
EP `s_phy_axis_*`, and EP `m_phy_axis_*` → RC `s_phy_axis_*`.

**Why this split and not two of the same top.** `pcie_rq_rc_top` cannot be the EP
side: its completer surface is tied off (`src/rc/pcie_rq_rc_top.sv:519-520, :539`),
so it can never answer a config read — and answering config reads is the entire
point of enumeration. `pcie_endpoint_top` cannot be the RC side: it exposes the raw
TL `command_*` port (`src/pcie_endpoint/pcie_endpoint_top.sv:53-68`), not the PG213
AXIS RQ/RC socket that `pcie_enum_top` drives (`src/rc/pcie_enum_top.sv:260-280`).
The two tops are complements, which is convenient, but it means the RC side needs a
**standalone `pcie_datalink_layer` instance** that no module currently provides —
there is no RC-side equivalent of `pcie_endpoint_top`.

**What gets tied off / driven by the bench:**
- `link_up_i` (RC, `pcie_rq_rc_top.sv:227`) and `phy_link_up_i` (EP,
  `pcie_endpoint_top.sv:30`) — driven high by the bench. No LTSSM in the netlist.
- `idle_valid_i` on both DLLs (`pcie_datalink_layer.sv:74`) — normally from
  `ordered_set_handler`; bench-driven.
- The EP's completer response: `pcie_endpoint_top` exposes `target_*`
  (`:72-88`) but the answering policy is external — something must observe
  `target_*` and drive `completion_request_*` (`:94-105`). The spec-golden
  completer models already written for the enum benches
  (`tb/rc/enum_tb_common`, per `tb/rc/tb_pcie_enum_bridge_tlp.sv:12-16`) are the
  obvious source, but they currently answer at the *TLP* level, not at this
  port-level surface, so they would need re-targeting.
- The RC side's `transmit_enable_i` (`pcie_rq_rc_top.sv:226`) and the four-way
  transmit gate documented at `pcie_rq_rc_top.sv:224-226`.

**What is explicitly OUT of scope, and why it can be:** the entire PHY serial path.
Because both sides expose a 32-bit AXIS PHY seam, the cross-connect happens *above*
`phy_transmit`/`phy_receive`. No scrambler, no 8b/10b, no PIPE byte stream, no
LFSR sync, no TX/RX clock-domain crossing. This is the same reasoning
`tb/ltssm/tb_ltssm_b2b.sv:13-40` gives for its own shim, and it is what makes this
increment tractable at all. It also sidesteps two hard blockers:
- `phy_receive` and all five of its submodules have **no test anywhere** — the only
  repo-wide hits are Vivado project artifacts, not benches.
- `encode_8b10b` / `decode_8b10b` appear in **no `.core` file** at all
  (`src/scrambler/scrambler.core:8-12` lists five files and omits both), so the Gen1
  line coder is not buildable through FuseSoC today.

**What is missing before this could be built** (in rough order):
1. **A `pcie_datalink_layer` standalone instance on the RC side.** No existing
   module or `.core` provides one; it would be new bench wiring.
2. **A port-level completer responder for the EP.** See above.
3. **Flow-control handshake between two real DLLs.** Every TL-level test to date has
   had the FC values fed from Python. Two real `pcie_flow_ctrl_init` instances
   (`pcie_datalink_layer.sv:197`) negotiating with each other is untested ground —
   and `pcie_datalink_layer` is inherited, unverified RTL.
4. **A resolution for the config-space gap in C.5.** The EP discards
   `ext_tag_enable_o` / `rcb_128b_o` / `max_read_request_size_o` /
   `max_payload_size_o` (`pcie_endpoint_top.sv:355-358`), so an RC that enumerates
   this EP and writes those fields would see no behavioural change. An end-to-end
   test that expects config writes to take effect would fail, correctly.
5. **A Verilator path for `pcie_endpoint_top`**, which has none (C.6).
6. **Whatever the DLL suite needs** — see 4B; the DLL is the one layer in this
   topology with no target in the 40-target regression gate.

**Honest risk note.** This proposal puts three pieces of unverified inherited RTL
(`pcie_datalink_layer` and its subtree, twice) on the critical path of a test whose
failures would be ambiguous between a DLL bug and an integration bug. That is
exactly the failure mode `tb/ltssm/tb_ltssm_b2b.sv:24-31` cites as its reason for
*not* using the real datapath. Landing the DLL suite as its own regression target
(4B) before attempting this b2b would make the ambiguity tractable.

---

## 3. Where `STACK_INVENTORY.md` and the code disagree

The RTL at HEAD is authoritative in every row below.

| # | Doc claim | Code at HEAD | Severity |
|---|---|---|---|
| 1 | `STACK_INVENTORY.md:775-812` §5.6 — `tb_pcie_endpoint_top.sv` "does not elaborate — in any simulator, VCS included"; four timeout signals undeclared; two `tlp_layer` pins missing | Both defects were repaired by `08b05d0`. The signals are declared at `tb/endpoint/tb_pcie_endpoint_top.sv:132-135`; the pins are connected named-empty at `src/pcie_endpoint/pcie_endpoint_top.sv:241-242`. The doc's cited lines (`tb:155`, `:171`, `:127`) match nothing at HEAD | **material** — the doc names two blockers that no longer exist |
| 2 | `STACK_INVENTORY.md:650` rates `end_to_end` feasibility **S** in a section about stack integration | `end_to_end` is `tb/tlp/test_tlp_end_to_end.py`, toplevel `tlp_layer` — entirely inside the TL. It integrates no two layers | **material** — the name misleads about scope |
| 3 | `STACK_INVENTORY.md:653` — a new DLL `.core` needs `depend: fusesoc:pcie:dllp_core` **+ `fusesoc:pcie:axis`** | `fusesoc:pcie:axis` arrives transitively via `src/dllp/dllp_core.core:16` | minor — redundant, harmless |
| 4 | `STACK_INVENTORY.md:653` and `tb/tlp/tb_tlp.core:466` treat `--public-flat-rw` as a flag you must add | edalize's cocotb+verilator flow injects it unconditionally; verified in generated `.vc` files for three targets whose cores omit it | minor — the explicit listings are no-ops under FuseSoC |
| 5 | `STACK_INVENTORY.md:684-686` — "adding `--trace-fst` would honour" the `$dumpvars` in `dllp_receive.sv` | Under FuseSoC the block never reaches Verilator at all: it is `` `ifdef COCOTB_SIM ``-guarded and no Verilator target defines that macro. Also the file is named at `:364`, not `:365` | minor, but the suggestion is a trap — see §4B.6 |
| 6 | `STACK_INVENTORY.md` baseline prose ("all 151 tests still pass", `:820`) | 294 tests across 40 targets at HEAD | stale, already known |
| 7 | `tb/rc/tb_rc.core:397` — `verilate_enum_bar_trace` "runs the same 25 tests" | `verilate_enum_bar` runs **32** (`tb/rc/test_pcie_enum_bar.py`, 32 `@cocotb.test()`, confirmed by the sweep) | minor — stale comment in a live core file |
| 8 | `Makefile:1-9` header — "Python test: `tb/dllp/test_pcie_datalink_layer.py`" | `Makefile:18` sets `MODULE := test_dll_comprehensive` | minor — stale header comment |
| 9 | `tb/ltssm/tb_ltssm_b2b.sv:56-60` — `extended_synch_i` is among the inputs "unconnected/unused in the RTL body" | `pcie_ltssm_downstream.sv:1061` branches on it live, and `pcie_phy_top.sv:349` leaves it unconnected | **material** — see §4.2 |

## 4. Ranked surprises

Ordered by how much they change what a later brief would do.

### 4.1 `end_to_end` was never a stack increment — the S rating is real but the name is not

The single most misleading thing found. A brief scoped from the name would set out
to connect two stacks; the actual increment adds one FuseSoC target around
`tb/tlp/test_tlp_end_to_end.py` with `toplevel: tlp_layer` and touches no layer
boundary. It is genuinely S, and genuinely worth doing — it is 4 written tests that
have never run — but it is TL housekeeping, not integration. Two sibling modules are
in the same state: `test_tlp_ecrc.py` (1 test) and `test_tlp_vc_buffer.py` (1 test)
also have no `verilate_*` target. **Six written-but-unrun tests in `tb/tlp` alone.**

### 4.2 A live floating input in `pcie_phy_top`

`pcie_phy_top.sv:349` leaves `extended_synch_i` unconnected, while
`pcie_ltssm_downstream.sv:1061` reads it in a live `if`. `lint/waiver.vlt:5` waives
`PINCONNECTEMPTY`, so the build is silent, and `pcie_phy_top` has no cocotb bench at
HEAD, so nothing exercises it. This was found by checking a claim in
`tb/ltssm/tb_ltssm_b2b.sv:56-60` that turned out to be right about six of its seven
signals and wrong about this one. Inherited RTL, reported not fixed.

### 4.3 The DLL suite is one test, not seventeen

`test_dll_comprehensive.py` has exactly **one** `@cocotb.test()` (`:2296-2297`).
The 18 "phases" (17 of which run — Phase 15 is env-gated at `:2623`) are sequential
blocks inside it. Landing this suite moves the gate from 40/294 to **41/295**, not
41/311, and any phase failure appears as one red test with no isolation. If
per-phase granularity is wanted, that is a testbench restructuring, not a wiring
task — and it should be decided before the `.core` is written, not after.

### 4.4 `pcie_endpoint_top`'s two recorded blockers are already fixed

`STACK_INVENTORY.md` §5.6 is the basis for the "M, harness broken" rating, and both
of its blockers were repaired by `08b05d0`. A full diff of every `dut.<name>` the
Python touches against the DUT's 113 ports and the harness declarations found
**zero mismatches** in either direction.

**And it elaborates.** Measured this session (§4C.7): `verilator --lint-only` over
the core's full dependency closure returns **exit 0, zero errors, zero warnings** in
131.4 s — and it does so **without** `-Wno-PINMISSING`. Since `lint/waiver.vlt` does
not waive `PINMISSING` and Verilator exits on it, that clean run is positive proof
that the missing-pin defect is gone rather than merely suppressed. The rating this
target carries should be re-derived: the two things that made it "M" are both
closed, and what remains is a `.core` target plus the fact that the five tests have
never executed.

### 4.5 `--public-flat-rw` is already injected by edalize

Verified from generated `.vc` files for three targets whose `.core` files do not list
it. This retires a compile-flag question that has been carried as an open item.

### 4.6 The FST is RTL-embedded, and FuseSoC already defeats it

`src/dllp/dllp_receive.sv:361-368` contains `$dumpfile`/`$dumpvars(0, dllp_receive)`
behind `` `ifdef COCOTB_SIM ``. No Verilator target in the repo defines that macro —
confirmed by grepping the whole `build/` tree after a 40-target sweep. So the FST
policy is already satisfied by the flow, with no RTL change needed. The risk is
forward-looking: three DLL cores still carry `--trace-fst`
(`tb/dllp/tb_dllp.core:41-43`, `tb_dllp_receive.core:38,50`,
`tb_dllp_transmit.core:36`), so a new target copied from one of them could
resurrect a full-subtree dump over a 1.2 ms run.

### 4.7 The EP silently discards its own config-space settings

`pcie_endpoint_top.sv:355-358` leaves the DLL's `ext_tag_enable_o`, `rcb_128b_o`,
`max_read_request_size_o` and `max_payload_size_o` connected-empty, while the TL gets
those four values from top-level ports (`:196-199`). A Root Complex that enumerates
this endpoint and writes Extended Tag / RCB / MPS / MRRS would see no behavioural
change. The representations differ too (`[2:0]` encoded vs `[12:0]` byte counts), so
a decode stage is missing, not just a wire. Found while auditing port lists; no test
at HEAD would catch it.

### 4.8 Two of the five `pcie_endpoint_top` tests can pass without proving their claim

`data_link_nak_replays_transaction_layer_packet` cannot distinguish a NAK-caused
replay from a timer-caused one, because the harness sets
`REPLAY_TIMER_CYCLES(64)` = 512 ns (`tb/endpoint/tb_pcie_endpoint_top.sv:173`).
`corrupted_link_input_is_rejected_with_nak` asserts `nak.seq == 0xFFF`, which is the
reset "nothing received yet" value, and has no positive control — a completely dead
RX path passes it. These are unverified artifacts, as the brief assumed; the detail
is in §4C.4.

### 4.9 `pcie_ltssm` is dead code

`src/ltssm/pcie_ltssm.sv:2` declares `pcie_ltssm`, and the name appears nowhere else
in `src/` or `tb/` — no instantiation, no reference. It is in no `.core` either:
`src/ltssm/pcie_ltssm.core:8` lists only `pcie_ltssm_downstream.sv`, so the file is
not even compiled. `pcie_ltssm_downstream` is the
live module, and it is a flat FSM: it does not instantiate `ltssm_detect`,
`ltssm_polling`, `ltssm_configuration`, `ltssm_l0` or `ltssm_recovery`. Four of those
five are orphaned entirely; only `ltssm_configuration` is instantiated anywhere, by
`tb/ltssm/tb_ltssm_configuration.v:71`.

### 4.10 The lint waiver is broad enough to hide integration defects

`lint/waiver.vlt` turns off 14 rules, including `PINCONNECTEMPTY`, `UNUSEDSIGNAL`,
`LATCH`, `MULTIDRIVEN` and `IMPLICIT`. That is what let §4.2 through. Not something
to change inside a wiring brief, but worth knowing when a future integration target
comes up clean.

### 4.11 Minor: a typo'd port name is load-bearing across three files

`config_copmlete_ts2_i` (`src/ltssm/pcie_ltssm_downstream.sv:63`) is misspelled and
propagated to both call sites (`pcie_phy_top.sv:339`, `tb/ltssm/tb_ltssm_b2b.sv`).
Renaming it is a mechanical change across three files, and it is the sort of thing
worth folding into a port-rename commit rather than doing on its own.
