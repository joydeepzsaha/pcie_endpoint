# Stage C2(a) — Full-Stack Inventory

**Anchor:** `2c95700` on `kourosh/dev` (= `cc1e194` + `ef32bcd` completion-timeout RTL + `2c95700` tests).
Tree clean at the time of writing. Read-only recon; the only change in this commit is this file.

**Environment:** `vlsi031.ece.uw.edu`, conda env `pcie`, Verilator 5.050, cocotb 1.9.2,
`cocotbext-axi` and `cocotbext-pcie` both importable. Sequential runs only.

**Sanity control (start of session):**
`fusesoc run --target=verilate_conformance fusesoc:pcie:tb_ltssm_conformance` →
`TESTS=1 PASS=1 FAIL=0 SKIP=0`. Environment sane.

> **Note on the VLNV.** The conformance target is reached as
> `fusesoc:pcie:tb_ltssm_conformance`, not as `pcie_endpoint`. There is no core
> named `pcie_endpoint`; `fusesoc run --target=verilate_conformance pcie_endpoint`
> fails with *"'pcie_endpoint' or any of its dependencies requires 'pcie_endpoint',
> but this core was not found"*. Worth writing down because the brief used the short
> form and the next person will hit the same wall.

---

## 0. Headline findings

Five things in this inventory are load-bearing and were not known going in.

1. **The trusted baseline is 27 targets / 151 tests, not 152.** Measured, not counted
   by grep: all 27 were re-run at this HEAD and every one passes. See §2.1.
2. **`tb/endpoint/tb_pcie_endpoint_top.sv` does not elaborate at this HEAD, in any
   simulator.** `ef32bcd` added four completion-timeout ports to `pcie_endpoint_top`;
   the harness connects with `.*` and never declared them. Nothing caught it because
   nothing compiles that harness. See §5.6.
3. **`pcie_endpoint_top` itself is Verilator-clean apart from two `PINMISSING`
   warnings** — it leaves `tlp_layer`'s `allocated_tag_o` / `allocated_tag_valid_o`
   unconnected (added by `31291146`). Under the project's warnings-as-errors
   invocation that is a build failure. See §5.6.
4. **The entire DLL suite already passes under Verilator, unmodified.** Not an
   estimate — measured: `TESTS=1 PASS=1 FAIL=0` in 25 seconds of wall time, all 17
   mandatory phases, zero source edits, zero timeout tuning. The DUT Verilates with
   zero errors and zero warnings and all five internal hierarchy paths resolve under
   `--public-flat-rw`. Bringing the Data Link Layer into Kourosh's flow is writing a
   `.core` file, not a port. See §4.2 and §4.5.
5. **`tlp_credit_manager` has no exhaustion coverage in any FuseSoC target.** Every
   `tlp_layer` harness initialises credits to maximum and never approaches a limit.
   The blocking path is exercised only by a Makefile-only bench. See §3.2.

---

## 1. Module inventory matrix

Scope: the 89 RTL files under `src/` excluding the 1206-file
`src/xilinx_primitives/src/unisims/` vendor dump (simulation models for Xilinx
primitives; not project RTL, not instantiated by any project module, listed in
`src/xilinx_primitives/xilinx_primitives.core` only).

Coverage character:

- **standalone** — a target whose DUT is this module (or a thin SV wrapper around it).
- **integration** — a target whose DUT is a larger assembly, where this module's
  behaviour is what the assertions are about.
- **incidental** — compiled and instantiated inside someone else's DUT, with no
  assertion aimed at it. This is the RC1 category.
- **none** — not exercised by any flow.

### 1.1 LTSSM (`src/ltssm/`)

| Module (file) | Instantiated by (file:line) | Tested by (target(s) + tests) | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `pcie_ltssm_downstream.sv` | `src/pcie_phy_core/pcie_phy_top.sv:301`; `tb/ltssm/tb_ltssm_b2b.sv:149,206` | 12 `tb_ltssm` targets (25 tests) + 4 `tb_ltssm_conformance` targets (4 tests) | FuseSoC-Verilator | standalone + integration | The only live LTSSM module. Monolithic FSM; the per-state files below are not part of it. |
| `pcie_ltssm.sv` | nothing | — | NONE | none | In no `.core` fileset. Dead. |
| `ltssm_configuration.sv` | `tb/ltssm/tb_ltssm_configuration.v:71` (iverilog-era bench, no target) | — | NONE | none | In no `.core`. Dead. |
| `downstream_config.sv` | `` `include ``d by `ltssm_configuration.sv:163` | — | NONE | none | Reachable only from a dead file. |
| `upstream_config.sv` | `` `include ``d by `ltssm_configuration.sv:172` | — | NONE | none | Reachable only from a dead file. |
| `ltssm_detect.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `ltssm_l0.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `ltssm_polling.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `ltssm_recovery.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `iverilog_dump.v` | nothing | — | NONE | none | In no `.core`. Icarus waveform shim. Dead. |

### 1.2 PHY datapath (`src/pcie_phy_core/`, `src/scrambler/`)

| Module (file) | Instantiated by (file:line) | Tested by (target(s) + tests) | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `phy_transmit.sv` | `pcie_phy_top.sv:262` | `verilate_tx_golden` (4), `verilate_tx_x4` (4) | FuseSoC-Verilator | standalone | x1 golden + x4. |
| `os_generator.sv` | `phy_transmit.sv:278` | same two targets | FuseSoC-Verilator | integration | The x4 bench asserts per-lane ordered-set content, so this is real coverage. |
| `frame_symbols.sv` | `phy_transmit.sv:129` | same two targets | FuseSoC-Verilator | incidental | |
| `lane_management.sv` | `phy_transmit.sv:175` | same two targets | FuseSoC-Verilator | incidental | |
| `lfsr.v` | `synchronous_lifo.sv:117` | same two targets | FuseSoC-Verilator | incidental | Only reachable through `synchronous_lifo`, which is itself uninstantiated — so in practice compiled but unreached. |
| `synchronous_lifo.sv` | nothing live (`lane_management.sv:533` is commented out) | — | FuseSoC-Verilator (compiled only) | none | In `phy_transmit.core:9` fileset, so it compiles; no live instantiation. |
| `phy_receive.sv` | `pcie_phy_top.sv:227` | — | NONE | none | `phy_receive.core` has `sim`/`verilate` targets but their `cocotb_module: test_ltssm_configuration` is not in their filesets — vestigial, not runnable. |
| `ordered_set_handler.sv` | `phy_receive.sv:162` | — | NONE | none | RX path entirely unverified. |
| `block_alignment.sv` | `phy_receive.sv:185` | — | NONE | none | |
| `data_handler.sv` | `phy_receive.sv:263` | — | NONE | none | |
| `pack_data.sv` | `phy_receive.sv:206` | — | NONE | none | |
| `synchronous_fifo.sv` | nothing live (`phy_receive.sv:249`, `phy_transmit.sv:209,243`, `lane_management.sv:553` all commented out) | — | compiled only | none | In `phy_receive.core:12`. |
| `packet_reg.sv` | nothing | — | NONE | none | In no `.core` at all. Dead. |
| `pcie_phy_top.sv` | nothing | — | NONE | none | Shipped only by `pcie_phy.core` / `pcie_gtx.core` / `pcie_gtp.core` (FPGA wrappers, no sim target). Named as `toplevel` by `tb_ltssm.core:103,291` and `pcie_ltssm.core:39`, whose filesets do **not** ship the file — those targets cannot elaborate. |
| `scrambler.sv` | `phy_transmit.sv:153`, `phy_receive.sv:143` | `verilate_tx_golden`, `verilate_tx_x4` | FuseSoC-Verilator | incidental | |
| `gen1_scramble.sv` | `scrambler.sv:47` | same | FuseSoC-Verilator | incidental | |
| `gen3_scramble.sv` | `scrambler.sv:32` | same | FuseSoC-Verilator | incidental | Gen3 roadmap stub. |
| `byte_scramble.sv` | `gen1_scramble.sv:74` | same | FuseSoC-Verilator | incidental | |
| `gen3_byte_scramble.sv` | `gen3_scramble.sv:55` | same | FuseSoC-Verilator | incidental | Gen3 roadmap stub. |
| `encode_8b10b.sv` | `tb/scrambler/test_8b10b.v:78`, `tb/dllp/tb_pcie_datalink_layer.v:226,245` | — | NONE | none | In no `.core`. Referenced only by iverilog-era benches with no target. |
| `decode_8b10b.sv` | `tb/scrambler/test_8b10b.v:84`, `tb/dllp/tb_pcie_datalink_layer.v:233,252` | — | NONE | none | Same. **Gen1 needs this on the real wire** — see §3.1. |

### 1.3 DLL (`src/dllp/`, `src/crc/`, `src/bram/`)

Every module here is covered *only* by the VCS/Makefile flow. Nothing in `src/dllp/`
is exercised by any FuseSoC target.

| Module (file) | Instantiated by (file:line) | Tested by | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `pcie_datalink_layer.sv` | `pcie_endpoint_top.sv:300`, `pcie_phy_top.sv:363`, `tb/dllp/tb_pcie_datalink_layer.v:153` | `make sim` → `test_dll_comprehensive.py` (1 cocotb test, 18 phases) | VCS-Makefile | integration | The DUT of the whole DLL suite. |
| `dllp_transmit.sv` | `pcie_datalink_layer.sv:224`, `tb/dllp/tb_dllp_transmit.v:78` | `make sim` (integration); `tb_dllp_transmit` FuseSoC targets exist but see §2.3 | VCS-Makefile | integration | Suite reads `dllp_transmit_inst.retry_err` directly (`:2173,2193`). |
| `dllp_receive.sv` | `pcie_datalink_layer.sv:263` | `make sim` | VCS-Makefile | integration | |
| `dllp_handler.sv` | `dllp_receive.sv:188`, `tb/dllp/tb_dllp_handler.sv:55` | `make sim` | VCS-Makefile | incidental | Has a rich SV bench (`tb_dllp_handler.sv`) reachable from no target. |
| `dllp2tlp.sv` | `dllp_receive.sv:246` | `make sim` | VCS-Makefile | integration | |
| `tlp2dllp.sv` | `dllp_transmit.sv:163`, `tb/dllp/tb_tlp2dllp.v:73` | `make sim` | VCS-Makefile | integration | Suite reads its six credit counters directly (`:1761,1923`). |
| `dllp_fc_update.sv` | `dllp_receive.sv:219` | `make sim` | VCS-Makefile | incidental | |
| `retry_management.sv` | `dllp_transmit.sv:97`, `tb/dllp/tb_retry_management.v:70` | `make sim` phases 8/17/18 | VCS-Makefile | integration | |
| `retry_transmit.sv` | `dllp_transmit.sv:128` | `make sim` | VCS-Makefile | incidental | |
| `axis_retry_fifo.sv` | `retry_transmit.sv:85` | `make sim` phase 13 | VCS-Makefile | incidental | |
| `axis_user_demux.sv` | `dllp_receive.sv:154` | `make sim` | VCS-Makefile | incidental | |
| `pcie_datalink_init.sv` | `pcie_datalink_layer.sv:184` | `make sim` phase 1 | VCS-Makefile | incidental | |
| `pcie_flow_ctrl_init.sv` | `pcie_datalink_layer.sv:197` | `make sim` phase 1/12 | VCS-Makefile | integration | |
| `pcie_datalink_crc.sv` | `dllp_handler.sv:345`, `pcie_flow_ctrl_init.sv:445`, `dllp_fc_update.sv:305`, `tb/dllp/tb_dllp_handler.sv:49` | `make sim` | VCS-Makefile | incidental | |
| `pcie_dllp_crc8.v` | `pcie_datalink_crc.sv:41,47,53,59` | `make sim` | VCS-Makefile | incidental | |
| `pcie_lcrc16.sv` | `tlp2dllp.sv:676`, `dllp2tlp.sv:815` | `make sim` | VCS-Makefile | incidental | |
| `pcie_lcrc32.sv` | `tlp2dllp.sv:682`, `dllp2tlp.sv:821` | `make sim` phase 4 (bad-LCRC NAK) | VCS-Makefile | integration | |
| `Crc16Gen.sv` | nothing | — | compiled only | none | In `crc.core:8`. Dead. |
| `pcie_crc8.v` | nothing | — | compiled only | none | In `crc.core:9`, and is `crc.core`'s default `toplevel`. Never instantiated. Dead. |
| `bram_dp.sv` | nothing (not in `src/`, `tb/`, or the `verilog-axis`/`verilog-pcie`/`async_fifo` submodules) | — | compiled only | none | In `bram.core:8` and in `Makefile:50`'s `VERILOG_SOURCES`. Dead. |
| `bram_sp.sv` | nothing | — | compiled only | none | In `bram.core:9`. Dead. |

### 1.4 TLP (`src/tlp/`)

All FuseSoC coverage. Instantiation column gives the `tlp_layer` line.

| Module (file) | Instantiated by (file:line) | Tested by (target(s) + tests) | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `tlp_layer.sv` | `pcie_endpoint_top.sv:172`, `pcie_rq_rc_top.sv:411`, `tb/rc/tb_pcie_rq_if_tlp.sv:145`, `tb/rc/tb_pcie_rc_if_tlp.sv:202` | `verilate_tlp_compile` (4), `verilate_tlp_cfg0_spine` (2), `verilate_tlp_conf_requester` (10), `verilate_tlp_conf_tracker` (7), `verilate_tlp_conf_cfgbe` (7) + all 3 RC integration targets | FuseSoC-Verilator | standalone + integration | 30 tests drive its real ports directly. |
| `tlp_requester.sv` | `tlp_layer.sv:346`; `tb/tlp/tb_tlp_requester.sv:62` | `verilate_tlp_requester` (3), `verilate_tlp_conf_datalast` (5), `verilate_tlp_conf_requester` (10), `verilate_tlp_conf_cfgbe` (7) | FuseSoC-Verilator | standalone + integration | Best-covered TL module. |
| `tlp_request_tracker.sv` | `tlp_layer.sv:372`; `tb/tlp/tb_tlp_request_tracker.sv:50` | `verilate_tlp_request_tracker` (2), `verilate_tlp_conf_tracker` (7), `verilate_tlp_cpl_timeout` (5), `verilate_tlp_cpl_timeout_default` (1), `verilate_tlp_cpl_timeout_off` (2) | FuseSoC-Verilator | standalone + integration | Completion Timeout added at `ef32bcd`. |
| `tlp_parser.sv` | `tlp_layer.sv:306`; `tb/tlp/tb_tlp_parser.sv:55`, `tb/tlp/tb_tlp_conf_parser.sv:76` | `verilate_tlp_parser` (3), `verilate_tlp_conf_parser` (12) | FuseSoC-Verilator | standalone | |
| `tlp_generator.sv` | `tlp_layer.sv:441`; `tb/tlp/tb_tlp_generator.sv:61` | `verilate_tlp_generator` (3), `verilate_tlp_conf_generator` (2) | FuseSoC-Verilator | standalone | |
| `tlp_completion_generator.sv` | `tlp_layer.sv:401`; `tb/tlp/tb_tlp_completion_control.sv:84` | `verilate_tlp_completion_gen` (2), `verilate_tlp_conf_completion` (6) | FuseSoC-Verilator | standalone | |
| `tlp_control.sv` | `tlp_layer.sv:423`; `tb/tlp/tb_tlp_completion_control.sv:104,121` | same two targets | FuseSoC-Verilator | standalone | Two instances in the bench (default + fair arbitration). |
| `tlp_payload_formatter.sv` | `tlp_generator.sv:203`; `tb/tlp/tb_tlp_payload_formatter.sv:19` | `verilate_tlp_payload_formatter` (2), `verilate_tlp_conf_formatter` (4) | FuseSoC-Verilator | standalone | |
| `tlp_classifier.sv` | `tlp_layer.sv:323`; `tb/tlp/tb_tlp_comb.sv:53` | `verilate_tlp_comb` (3), `verilate_tlp_conf_classifier` (11) | FuseSoC-Verilator | standalone | |
| `tlp_bar_decoder.sv` | `tlp_layer.sv:330`; `tb/tlp/tb_tlp_comb.sv:60,71` | `verilate_tlp_comb` (3) | FuseSoC-Verilator | standalone | |
| `tlp_config_decoder.sv` | `tlp_layer.sv:339`; `tb/tlp/tb_tlp_comb.sv:82` | `verilate_tlp_comb` (3) | FuseSoC-Verilator | standalone | |
| `tlp_validator.sv` | `tlp_classifier.sv:68`, `tlp_parser.sv:299` | `verilate_tlp_comb`, `verilate_tlp_conf_classifier`, `verilate_tlp_conf_parser` | FuseSoC-Verilator | incidental | No bench of its own; its rejections are asserted through the classifier/parser. Acceptable — it is pure combinational and its outputs are the assertion targets. |
| `tlp_ecrc.sv` | `tlp_generator.sv:224`, `tlp_parser.sv:302`; `tb/tlp/tb_tlp_ecrc.sv:8` | **`make tlp-test-ecrc` only** (1 test) | Makefile-only | incidental (FuseSoC) / standalone (Makefile) | Carries the §2.7.1 divergence — see §3.3. |
| `tlp_credit_manager.sv` | `tlp_layer.sv:474`; `tb/tlp/tb_tlp_credit_manager.sv:9` | **`make tlp-test-credit-manager` only** (1 test) | Makefile-only | incidental (FuseSoC) / standalone (Makefile) | **TX critical path.** See §3.2. |
| `tlp_vc_buffer.sv` | `tlp_layer.sv:455`; `tb/tlp/tb_tlp_vc_buffer.sv:10` | **`make tlp-test-vc-buffer` only** (1 test) | Makefile-only | incidental (FuseSoC) / standalone (Makefile) | |
| `tlp_pkg.sv` | imported everywhere in `src/tlp`, `src/rc` | all TLP/RC targets | FuseSoC-Verilator | incidental | Package. Its byte-enable helpers are asserted by `verilate_tlp_conf_cfgbe`. |

### 1.5 RC wrappers (`src/rc/`)

| Module (file) | Instantiated by (file:line) | Tested by (target(s) + tests) | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `pcie_rq_rc_top.sv` | `tb/rc/tb_pcie_rq_rc_top.sv:141` | `verilate_rq_rc_top` (9) | FuseSoC-Verilator | standalone | 2a-iii. V1–V6 plus V7–V9 (timeout) added at `2c95700`. |
| `pcie_rq_if.sv` | `pcie_rq_rc_top.sv:362`; `tb/rc/tb_pcie_rq_if.sv:57`, `tb/rc/tb_pcie_rq_if_tlp.sv:99`, `tb/rc/tb_pcie_rc_if_tlp.sv:156` | `verilate_rq_if` (11), `verilate_rq_if_tlp` (9) | FuseSoC-Verilator | standalone + integration | |
| `pcie_rc_if.sv` | `pcie_rq_rc_top.sv:549`; `tb/rc/tb_pcie_rc_if.sv:95`, `tb/rc/tb_pcie_rc_if_tlp.sv:313` | `verilate_rc_if` (11), `verilate_rc_if_tlp` (4) | FuseSoC-Verilator | standalone + integration | |
| `pcie_axis_dw_downsize.sv` | `pcie_rq_if.sv:362`; `tb/rc/tb_pcie_axis_gearbox.sv:34,86` | `verilate_axis_gearbox` (11) | FuseSoC-Verilator | standalone | |
| `pcie_axis_dw_upsize.sv` | `pcie_rc_if.sv:349`; `tb/rc/tb_pcie_axis_gearbox.sv:56,95` | `verilate_axis_gearbox` (11) | FuseSoC-Verilator | standalone | |
| `pcie_rq_rc_pkg.sv` | imported by the three RC modules | all 6 RC targets | FuseSoC-Verilator | incidental | Package (PG213 descriptor types). |

### 1.6 Integration top (`src/pcie_endpoint/`)

| Module (file) | Instantiated by (file:line) | Tested by | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `pcie_endpoint_top.sv` | `tb/endpoint/tb_pcie_endpoint_top.sv:155` | **nothing runnable** | (VCS target declared, broken) | none | See §5.6. Its only target is `tb_pcie_endpoint_top.core:16 sim` with `tool: vcs`, and the harness no longer elaborates. |

### 1.7 Config (`src/pcie_cfg/`)

| Module (file) | Instantiated by (file:line) | Tested by | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `pcie_cfg_wrapper.sv` | `dllp_receive.sv:280` | `make sim` | VCS-Makefile | incidental | |
| `pcie_config_decode.sv` | `pcie_cfg_wrapper.sv:132` | `make sim` | VCS-Makefile | incidental | |
| `pcie_config_mux.sv` | `pcie_cfg_wrapper.sv:160` | `make sim` | VCS-Makefile | incidental | |
| `pcie_config_handler.sv` | `pcie_cfg_wrapper.sv:192` | `make sim` | VCS-Makefile | incidental | |
| `pcie_config_reg.sv` | `pcie_cfg_wrapper.sv:242` | `make sim` | VCS-Makefile | incidental | |
| `pcie_config_reg_pkg.sv` | imported | `make sim` | VCS-Makefile | incidental | Package. |

### 1.8 Packages, interfaces, converters

| Module (file) | Instantiated by | Tested by | Flow | Coverage | Notes |
|---|---|---|---|---|---|
| `packages/pcie_datalink_pkg.sv` | imported broadly | LTSSM + PHY + DLL flows | both | incidental | |
| `packages/pcie_phy_pkg.sv` | imported | LTSSM + PHY targets | FuseSoC-Verilator | incidental | |
| `packages/pcie_tlp_pkg.sv` | imported by `src/pcie_cfg/*` | `make sim` | VCS-Makefile | incidental | Distinct from `src/tlp/tlp_pkg.sv`. |
| `interfaces/axi_lite_if.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `interfaces/axi_stream_if.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `interfaces/axis_to_packet.sv` | nothing | — | NONE | none | In no `.core`. Dead. |
| `converters/axis_to_pcie_converter.sv` | nothing | — | NONE | none | In `converters.core:8`, referenced only by `pcie_gtx.core` / `pcie_gtp.core` (FPGA wrappers, no sim target). |
| `converters/pcie_to_axis_converter.sv` | nothing | — | NONE | none | Same. |

---

## 2. Per-flow test census

### 2.1 FuseSoC / Verilator

There are **45** runnable `verilate_*` targets across five `.core` files, totalling
**188** cocotb tests. The **trusted baseline is the 27 TLP + RC targets (151 tests)**;
the 18 LTSSM/PHY targets are an earlier suite and were not re-run by this brief.

**Count-by-grep is exact.** `TestFactory` is imported in six `tb/dllp/*.py` files and
in `tb/ltssm/test_ltssm_configuration.py`, but `grep -rn "TestFactory(" tb/` returns
nothing and there is no `generate_tests` anywhere — it is never instantiated. No
parametrize, no `@pytest`. So `grep -c '@cocotb.test'` per file equals the runtime
test count, which the measured run below confirms file-by-file.

#### Trusted baseline — TLP, `fusesoc:pcie:tb_tlp` (21 targets, 96 tests)

| Target | DUT (toplevel) | Test file | Tests |
|---|---|---|---|
| `verilate_tlp_requester` | `tb_tlp_requester` | `test_tlp_requester.py` | 3 |
| `verilate_tlp_request_tracker` | `tb_tlp_request_tracker` | `test_tlp_request_tracker.py` | 2 |
| `verilate_tlp_parser` | `tb_tlp_parser` | `test_tlp_parser.py` | 3 |
| `verilate_tlp_generator` | `tb_tlp_generator` | `test_tlp_generator.py` | 3 |
| `verilate_tlp_completion_gen` | `tb_tlp_completion_control` | `test_tlp_completion_control.py` | 2 |
| `verilate_tlp_comb` | `tb_tlp_comb` | `test_tlp_comb.py` | 3 |
| `verilate_tlp_payload_formatter` | `tb_tlp_payload_formatter` | `test_tlp_payload_formatter.py` | 2 |
| `verilate_tlp_compile` | `tlp_layer` | `test_tlp_compile.py` | 4 |
| `verilate_tlp_cfg0_spine` | `tlp_layer` | `test_tlp_cfg0_spine.py` | 2 |
| `verilate_tlp_conf_requester` | `tlp_layer` | `test_tlp_conf_requester.py` | 10 |
| `verilate_tlp_conf_tracker` | `tlp_layer` | `test_tlp_conf_tracker.py` | 7 |
| `verilate_tlp_conf_parser` | `tb_tlp_conf_parser` | `test_tlp_conf_parser.py` | 12 |
| `verilate_tlp_conf_completion` | `tb_tlp_completion_control` | `test_tlp_conf_completion.py` | 6 |
| `verilate_tlp_conf_generator` | `tb_tlp_generator` | `test_tlp_conf_generator.py` | 2 |
| `verilate_tlp_conf_classifier` | `tb_tlp_comb` | `test_tlp_conf_classifier.py` | 11 |
| `verilate_tlp_conf_cfgbe` | `tlp_layer` | `test_tlp_conf_cfgbe.py` | 7 |
| `verilate_tlp_conf_datalast` | `tb_tlp_requester` | `test_tlp_conf_datalast.py` | 5 |
| `verilate_tlp_conf_formatter` | `tb_tlp_payload_formatter` | `test_tlp_conf_formatter.py` | 4 |
| `verilate_tlp_cpl_timeout` | `tb_tlp_request_tracker` (`CPL_TIMEOUT_CYCLES=64`) | `test_tlp_cpl_timeout.py` | 5 |
| `verilate_tlp_cpl_timeout_default` | `tb_tlp_request_tracker` | `test_tlp_cpl_timeout_default.py` | 1 |
| `verilate_tlp_cpl_timeout_off` | `tb_tlp_request_tracker` (`CPL_TIMEOUT_CYCLES=0`) | `test_tlp_request_tracker.py` (reused) | 2 |

#### Trusted baseline — RC, `fusesoc:pcie:tb_rc` (6 targets, 55 tests)

| Target | DUT (toplevel) | Test file | Tests |
|---|---|---|---|
| `verilate_axis_gearbox` | `tb_pcie_axis_gearbox` | `test_axis_dw_gearbox.py` | 11 |
| `verilate_rq_if` | `tb_pcie_rq_if` | `test_pcie_rq_if.py` | 11 |
| `verilate_rq_if_tlp` | `tb_pcie_rq_if_tlp` | `test_pcie_rq_if_tlp.py` | 9 |
| `verilate_rc_if` | `tb_pcie_rc_if` | `test_pcie_rc_if.py` | 11 |
| `verilate_rc_if_tlp` | `tb_pcie_rc_if_tlp` | `test_pcie_rc_if_tlp.py` | 4 |
| `verilate_rq_rc_top` | `tb_pcie_rq_rc_top` | `test_pcie_rq_rc_top.py` | 9 |

**Measured at this HEAD:** all 27 re-run sequentially →
`TOTAL targets=27 TESTS=151 PASS=151 FAIL=0`.

**The baseline is 151 tests, not 152.** The arithmetic reconciles cleanly against the
recorded history: `23/134` at `9991b07`; `cc1e194` added `verilate_rq_rc_top` with
6 tests → `24/140`; `2c95700` added three timeout targets (5+1+2 = 8 tests) and three
new tests (V7–V9) to `test_pcie_rq_rc_top.py` → **`27/151`**. The "152" in the brief
is a bookkeeping slip of one, not a missing test — every target passes and no test is
skipped.

#### Not in the trusted baseline — LTSSM, `fusesoc:pcie:tb_ltssm` (12 targets, 25 tests)

| Target | DUT (toplevel) | Test file | Tests |
|---|---|---|---|
| `verilate` | `pcie_ltssm_downstream` | `pcie_ltssm/tb/test_ltssm_configuration.py` | 1 |
| `verilate_fast` | `pcie_ltssm_downstream` | `test_ltssm_linkup.py` | 1 |
| `verilate_recovery` | `pcie_ltssm_downstream` | `test_ltssm_recovery.py` | 1 |
| `verilate_b2b` | `tb_ltssm_b2b` | `test_ltssm_b2b.py` | 1 |
| `verilate_b2b_x4` | `tb_ltssm_b2b` | `test_ltssm_b2b_x4.py` | 3 |
| `verilate_rc_linkup` | `pcie_ltssm_downstream` | `test_ltssm_rc_linkup.py` | 1 |
| `verilate_detect_retry` | `pcie_ltssm_downstream` | `test_ltssm_detect_retry.py` | 1 |
| `verilate_polling_timeout` | `pcie_ltssm_downstream` | `test_ltssm_polling_timeout.py` | 1 |
| `verilate_polling_timeout_tx_ok` | `pcie_ltssm_downstream` | `test_ltssm_polling_timeout_tx_ok.py` | 1 |
| `verilate_config_timeout` | `pcie_ltssm_downstream` | `test_ltssm_config_timeout.py` | 6 |
| `verilate_partial_lanes` | `pcie_ltssm_downstream` | `test_ltssm_partial_lanes.py` | 5 |
| `verilate_recovery_partial_lanes` | `pcie_ltssm_downstream` | `test_ltssm_recovery_partial_lanes.py` | 3 |

#### Not in the trusted baseline — conformance + PHY (6 targets, 12 tests)

| Target | Core | DUT | Test file | Tests |
|---|---|---|---|---|
| `verilate_conformance` | `tb_ltssm_conformance` | `pcie_ltssm_downstream` | `test_ltssm_conformance.py` | 1 |
| `verilate_realtimer` | `tb_ltssm_conformance` | `pcie_ltssm_downstream` | `test_ltssm_realtimer.py` | 1 |
| `verilate_realtimer_linkup_x1` | `tb_ltssm_conformance` | `pcie_ltssm_downstream` | `test_ltssm_realtimer_linkup_x1.py` | 1 |
| `verilate_realtimer_linkup_x4` | `tb_ltssm_conformance` | `pcie_ltssm_downstream` | `test_ltssm_realtimer_linkup_x4.py` | 1 |
| `verilate_tx_golden` | `tb_phy_transmit` | `phy_transmit` | `test_phy_transmit_tx.py` | 4 |
| `verilate_tx_x4` | `tb_phy_transmit` | `phy_transmit` | `test_phy_transmit_tx_x4.py` | 4 |

#### Declared-but-not-runnable targets

Worth knowing about so nobody wastes an afternoon on them:

- `tb_ltssm.core:88 sim`, `:285 synth` and `pcie_ltssm.core:33 synth` set
  `toplevel: pcie_phy_top`, but their filesets resolve to `fusesoc:pcie:ltssm`, which
  ships only `pcie_ltssm_downstream.sv`. The file is not present in the build.
- `phy_receive.core:35 sim` / `:47 verilate`, `phy_transmit.core:34 sim` / `:46
  verilate`, `scrambler.core:32 sim` / `:44 verilate`, `pcie_config.core:33 sim` /
  `:45 verilate` all set `cocotb_module: test_ltssm_configuration` by copy-paste,
  with no cocotb fileset. `pcie_config.core:31` even sets `toplevel: scrambler`.
- `tb/dllp/tb_dllp*.core` targets (`sim`, `sim_dllp2tlp`, `default`) point at
  `tb/dllp/*.py` benches from the iverilog era. Not part of any baseline; not
  assessed by this brief.

### 2.2 VCS / Makefile (`make sim`)

From reading only — not run (VCS licence, and the brief forbids it).

- **Toplevel:** `pcie_datalink_layer` (`Makefile:15`)
- **`MODULE`:** `test_dll_comprehensive` (`Makefile:18`)
- **`SIM`:** `vcs` (`Makefile:11`); `COMPILE_ARGS` `-full64 -sverilog
  -timescale=1ns/1ps -debug_access+all -kdb -lca +v2k` (`Makefile:60-66`)
- **Default goal:** `test-log` (`Makefile:76`), which runs `make sim` and tees to
  `output_testPcie_python.txt`.

**`VERILOG_SOURCES` (`Makefile:23-57`) — this list *is* what the DLL suite covers:**

```
src/packages/pcie_datalink_pkg.sv      src/dllp/dllp_receive.sv
src/pcie_cfg/pcie_config_reg_pkg.sv    src/dllp/dllp_handler.sv
src/pcie_cfg/pcie_config_reg.sv        src/dllp/dllp_transmit.sv
src/packages/pcie_tlp_pkg.sv           src/dllp/dllp2tlp.sv
src/pcie_cfg/pcie_cfg_wrapper.sv       src/dllp/tlp2dllp.sv
src/pcie_cfg/pcie_config_decode.sv     src/dllp/dllp_fc_update.sv
src/pcie_cfg/pcie_config_mux.sv        src/dllp/retry_management.sv
src/pcie_cfg/pcie_config_handler.sv    src/dllp/retry_transmit.sv
src/crc/pcie_dllp_crc8.v               src/dllp/axis_retry_fifo.sv
src/crc/pcie_datalink_crc.sv           src/dllp/axis_user_demux.sv
src/crc/pcie_crc8.v                    src/bram/bram_dp.sv
src/crc/pcie_lcrc16.sv                 src/verilog-axis/rtl/{arbiter,priority_encoder,
src/crc/pcie_lcrc32.sv                   axis_register,axis_arb_mux,axis_mux,
src/dllp/pcie_datalink_layer.sv          axis_demux,axis_fifo}.v
src/dllp/pcie_datalink_init.sv
src/dllp/pcie_flow_ctrl_init.sv
```

**Confirmed: `src/tlp/` is absent.** The DLL suite exercises the Data Link Layer
against a synthetic TLP stream built in Python (`build_memory_write` etc. at
`test_dll_comprehensive.py:372-470`), never against the real Transaction Layer.

**Test enumeration.** The file is 2701 lines but contains exactly **one**
`@cocotb.test()` — `run_test` at `:2296-2297`. It is a single sequential scenario of
18 numbered phases. Enumerating the phases (a phase is the real unit of intent here):

| Phase | Line | Intent |
|---|---|---|
| 1 | `:2332` | Link-up and flow-control initialisation; wait for `fc_initialized_o`. |
| 2 | `:2374` | Locally generated Memory Write TLP reaches the PHY with seq + LCRC; ACK it. |
| 3 | `:2423` | Three incoming TLPs (1/16/32 DW) delivered intact to the TL, each ACKed with the right sequence. |
| 4 | `:2483` | Bad-LCRC NAK generation; DLLP arbitration priority; seven receive-side sequence-number error cases. |
| 5 | `:2513` | Received ACK/NAK drives replay. |
| 6 | `:2521` | Malformed incoming TLP rejected; bad/malformed DLLPs ignored. |
| 7 | `:2539` | UpdateFC DLLPs update credits; zero credit blocks transmit. |
| 8 | `:2547` | Replay timer expiry retransmits. |
| 9 | `:2554` | Corrupt ACK/NAK CRC; cumulative ACK + ordered multi-packet replay; ACK/NAK window boundaries. |
| 10 | `:2563` | NAK scheduling suppression; ACK latency within limit. |
| 11 | `:2575` | All TLP classes/formats, max payload, ECRC preserved end to end. |
| 12 | `:2584` | All six FC counters: exhaustion, scaling, cumulative wrap (relinks with finite Cpl credits first). |
| 13 | `:2601` | Retry-buffer full and physical slot wraparound. |
| 14 | `:2608` | Real 12-bit receive and transmit sequence rollover (4097 TLPs). |
| 15 | `:2623` | *Optional* `m_phy_axis` backpressure — gated on `PCIE_ENABLE_BACKPRESSURE`, **off by default**. |
| 16 | `:2657` | Link down with pending replay state. |
| 17 | `:2666` | Replay-timer retry-limit exhaustion, recovery by link reset. |
| 18 | `:2674` | Repeated NAK and replay-attempt exhaustion. |

**VCS-specific constructs.** Fewer than expected. There are **no** `force`/`release`,
no `$`-system tasks, no SVA, no timing controls, no randomize/constraints anywhere in
the file. What is simulator-sensitive:

- **Internal hierarchy reads** (`:471` helper, used at `:1770,1771,1926,2173,2193`).
  Paths: `dllp_transmit_inst.retry_err` and `dllp_transmit_inst.tlp2dllp_inst.{ph,pd,
  nph,npd,cplh,cpld}_credit{s_consumed,_limit}_r`. The error message at `:477-479`
  explicitly says *"Compile VCS with `-debug_access+all`"*. Verilator equivalent is
  `--public-flat-rw` — **measured to work**, see §4.2.
- **X/Z checks** (`:545`, `:1938`, `:2175`, `:2197`, `:2279`, `:2293` via
  `.value.is_resolvable`). Verilator is 2-state, so these become vacuously true.
  Not blocking, but `check_no_unknown_after_reset` (`:2275`) stops being a real
  reset check under Verilator. Worth recording, not worth fixing first.
- `setimmediatevalue` at `:195-200` — supported by both.

**Portable fraction:** effectively **100% structurally**. Nothing in the file needs a
mechanical edit to compile and load under Verilator. The X/Z assertions (6 lines of
2701, ~0.2%) degrade to no-ops rather than failing. See §4.2 for the behavioural
result.

### 2.3 Makefile-only orphans

Four `make` targets in the TLP regression have no FuseSoC equivalent. All four run
via `run_tlp_test` (`Makefile:118-125`) against `$(COCOTB_SIM_MAKEFILE)`.

| `make` target | Line | Toplevel | Test file | Tests |
|---|---|---|---|---|
| `tlp-test-ecrc` | `Makefile:156-157` | `tb_tlp_ecrc` | `test_tlp_ecrc.py` | 1 |
| `tlp-test-credit-manager` | `Makefile:159-160` | `tb_tlp_credit_manager` | `test_tlp_credit_manager.py` | 1 |
| `tlp-test-vc-buffer` | `Makefile:162-163` | `tb_tlp_vc_buffer` | `test_tlp_vc_buffer.py` | 1 |
| `tlp-test-end-to-end` | `Makefile:168-169` | `tlp_layer` (full `TLP_RTL_SOURCES`) | `test_tlp_end_to_end.py` | 4 |

The other eight `tlp-test-*` targets (`comb`, `parser`, `payload-formatter`,
`request-tracker`, `requester`, `generator`, `completion-control`, `layer`) all have
FuseSoC counterparts already; they are duplicates, not gaps.

**What the four actually assert:**

- **`test_tlp_ecrc.py`** (52 lines). Drives `tlp_ecrc` dword-serial with random gaps
  in `data_valid`, for payload lengths 1, 3, 4, 12, 16, 17, 64, 257, 4096 bytes, and
  asserts `ecrc_o == zlib.crc32(payload)` (`:35`). Then asserts reset mid-stream
  clears `ecrc_valid_o` (`:45-52`). Good coverage of the CRC engine and its
  byte-enable handling; encodes the §2.7.1 divergence (§3.3).
- **`test_tlp_credit_manager.py`** (45 lines). One test covering: exact short FC
  update load; a posted request consuming exactly the available data credits; the
  **blocking** path (`request_ready_o==0 && blocked_o==1` at `:30`) when a further
  posted request does not fit; per-class independence (a completion request still
  goes through while posted is exhausted, `:31-33`); the three pools decrementing
  independently (`:37-38`); and that clearing `fc_initialized` re-blocks even with
  large credits reloaded (`:40-45`). This is the **only** exhaustion coverage in the
  repository.
- **`test_tlp_vc_buffer.py`** (47 lines). Packet atomicity (a packet is only
  presented once complete), credit metadata on the packet interface
  (`packet_class`, `packet_credits` at `:25`), that a full packet FIFO backpressures
  via `s_ready` **without** raising `overflow` (`:29-34`), correct dword-by-dword
  drain with `m_last` (`:45`), and that the next packet's metadata appears after the
  first drains (`:47`).
- **`test_tlp_end_to_end.py`** (455 lines, 4 tests) against the real `tlp_layer`:
  `all_request_families_and_header_formats` (`:256`),
  `prefix_ecrc_alignment_maximum_and_segmentation` (`:306`),
  `request_to_completion_to_tag_retirement` (`:370`),
  `malformed_protocol_timing_ecrc_and_recovery` (`:424`). Initialises FC credits at
  `:61-67` (64 header / 512 data), so like every other layer-level bench it never
  approaches exhaustion.

---

## 3. The uncovered list

Ranked by risk. "Critical path" means in the RQ→wire→RC loop or the link-training
path that Gen1 x1 bring-up depends on.

### 3.1 Exercised by NO flow at all

**Critical path — PHY receive datapath (5 modules).** Nothing anywhere compiles a
test against them. This is the single largest verification hole in the stack: the
link cannot come up on real hardware without them, and there is not one assertion
covering any of them.

- `src/pcie_phy_core/phy_receive.sv` — RX top.
- `src/pcie_phy_core/ordered_set_handler.sv` — RX ordered-set detection, the other
  half of the LTSSM conformance work.
- `src/pcie_phy_core/block_alignment.sv` — symbol/block alignment.
- `src/pcie_phy_core/data_handler.sv` — RX data extraction.
- `src/pcie_phy_core/pack_data.sv` — RX repacking.

**Critical path — Gen1 line coding (2 modules).** In no `.core` at all, so they are
not even compiled by any FuseSoC target. Gen1 on a real wire is 8b/10b; these are
the encoder and decoder.

- `src/scrambler/encode_8b10b.sv`
- `src/scrambler/decode_8b10b.sv`

**Critical path — the integration top (1 module).**

- `src/pcie_endpoint/pcie_endpoint_top.sv` — the only thing wiring TL to DLL. Its
  sole harness does not elaborate (§5.6).

**Not critical path — dead code (15 files, in no `.core` at all).** Listing, not
deleting.

```
src/interfaces/axi_lite_if.sv          src/ltssm/ltssm_l0.sv
src/interfaces/axi_stream_if.sv        src/ltssm/ltssm_polling.sv
src/interfaces/axis_to_packet.sv       src/ltssm/ltssm_recovery.sv
src/ltssm/downstream_config.sv         src/ltssm/pcie_ltssm.sv
src/ltssm/iverilog_dump.v              src/ltssm/upstream_config.sv
src/ltssm/ltssm_configuration.sv       src/pcie_phy_core/packet_reg.sv
src/ltssm/ltssm_detect.sv              src/scrambler/encode_8b10b.sv
                                       src/scrambler/decode_8b10b.sv
```

The seven `src/ltssm/*` entries are the remains of a decomposed LTSSM that
`pcie_ltssm_downstream.sv` replaced with a monolithic FSM. `downstream_config.sv` and
`upstream_config.sv` are `` `include ``d by `ltssm_configuration.sv:163,172`, which is
itself dead. None of these are Gen3-roadmap stubs — they are superseded.

**Not critical path — compiled but never instantiated (7 files).** These are in a
`.core` fileset (so they compile into some builds) but nothing instantiates them:

```
src/bram/bram_dp.sv        (also in Makefile:50)   src/crc/Crc16Gen.sv
src/bram/bram_sp.sv                                src/crc/pcie_crc8.v
src/pcie_phy_core/synchronous_fifo.sv              src/converters/axis_to_pcie_converter.sv
src/pcie_phy_core/synchronous_lifo.sv              src/converters/pcie_to_axis_converter.sv
```

`synchronous_fifo` / `synchronous_lifo` have commented-out instantiations at
`phy_receive.sv:249`, `phy_transmit.sv:209,243`, `lane_management.sv:533,553` — they
were designed in and then bypassed. `pcie_crc8.v` is `crc.core`'s declared `toplevel`
yet is instantiated nowhere.

`src/pcie_phy_core/pcie_phy_top.sv` sits between the two categories: it is shipped
only by the three FPGA-wrapper cores (`pcie_phy.core:8`, `pcie_gtx.core:8`,
`pcie_gtp.core:8`), none of which has a sim target, and it is instantiated by
nothing. Effectively uncovered, and it is the module that would integrate LTSSM + PHY
+ DLL for hardware.

### 3.2 Exercised only incidentally — and why it matters

**`tlp_credit_manager` (TX critical path).** This is the RC1 category, and the answer
to the brief's question 2 is: **the RC1 fix left it exercised only in the "credits
initialised so tests pass" sense.**

- `tlp_layer.sv:280` gates the whole TX path on it:
  `assign vc_packet_ready = credit_request_ready && transmit_enable_i && link_up_i;`
  where `credit_request_ready` is the credit manager's `request_ready_o`
  (`tlp_layer.sv:480`).
- `tlp_credit_manager.sv:53-54`: `request_ready_o = fc_initialized_i &&
  selected_header_available && selected_data_available`.
- The RC1 fix (`7d471e0`, "tb/tlp: initialize VC0 flow-control credits in the
  tlp_layer harnesses") does exactly what its subject says. Every FuseSoC harness
  that instantiates `tlp_layer` now loads **maximum** credits and never gets near a
  limit: `test_tlp_cfg0_spine.py:66-73`, `test_tlp_conf_requester.py:112-119`,
  `test_tlp_conf_cfgbe.py:101-108` and `test_pcie_rq_if_tlp.py:126-133`,
  `test_pcie_rc_if_tlp.py:137-144`, `test_pcie_rq_rc_top.py:404-411` all set
  `fc_ph_i=0xFF`, `fc_pd_i=0xFFF`, … `fc_cpld_i=0xFFF`.
- The zeroing at `test_pcie_rc_if_tlp.py:241-244` and `test_pcie_rq_rc_top.py:441-444`
  is pre-reset state only — `init_flow_control(dut)` immediately follows
  (`:252` and `:451` respectively).
- `test_tlp_compile.py:27-33` uses 32/256, still far above anything the tests drive.

So: **infinite-credit and credit-exhaustion paths are tested in exactly one place,
`tb/tlp/test_tlp_credit_manager.py`, which no FuseSoC target runs.** A regression that
broke `request_ready_o`'s blocking behaviour would pass all 151 baseline tests.

Two further observations on the module itself, from reading it:

- **`error_o` is dead.** It is assigned `1'b0` at `:73`, `:75` and `:102` and nowhere
  else. `tlp_layer` exports it as `credit_error_o` and `pcie_endpoint_top.sv:140`
  re-exports it. It can never assert.
- **Infinite credits are not representable.** PCIe Base 2.1 §2.6.1 defines an
  advertised value of 0 during FC init as *infinite* credit for that type. Here
  `ph_r != 0` (`:41`) means zero advertised = permanently blocked. Any real link
  partner advertising infinite completion credit — which is what an Endpoint is
  required to do for Cpl — would deadlock this TX path. Not exercised by anything,
  because every bench advertises finite maxima. **This is a spec bug, not just a
  coverage gap**, and it is on the critical path.

**Other incidental-only modules** (lower risk, listed for completeness):
`tlp_validator` (asserted through classifier/parser, acceptable), `tlp_ecrc` and
`tlp_vc_buffer` (compiled into every TLP/RC target but no FuseSoC assertion),
`frame_symbols`, `lane_management`, the scrambler chain, and all of `src/pcie_cfg/`
(incidental inside `make sim` only).

### 3.3 The ECRC §2.7.1 divergence

Confirmed at this HEAD, with the anchor.

`src/tlp/tlp_ecrc.sv:20-40` computes a plain CRC-32 (`tlp_crc32_dw`, seeded
`32'hffff_ffff`, final `~next_crc`) over whatever dwords are presented. There is **no**
logic anywhere in `src/tlp/` that forces `Type[0]` or the `EP` bit to 1 for the
purpose of the calculation — `grep -niE 'type\[0\]|ep_bit|2\.7\.1'` across
`tlp_ecrc.sv`, `tlp_generator.sv` and `tlp_parser.sv` returns nothing.

PCIe Base 2.1 §2.7.1 requires that, when computing ECRC, bit 0 of the Type field and
the EP bit are treated as 1 regardless of their actual values. The implementation
omits this. It is self-consistent — `tlp_generator.sv:224` and `tlp_parser.sv:302`
use the same engine, so generated and checked ECRC agree — but it **diverges from any
spec-compliant device**. Joy's bench encodes the same convention:
`tb/tlp/test_tlp_ecrc.py:35` asserts `int(dut.ecrc.value) == zlib.crc32(payload)`,
i.e. the unmodified CRC.

Consequence for the program: ECRC is optional in PCIe, but if it is ever enabled
against a real SSD, every TLP will be rejected. Cheap to fix (two bit-forces in the
generator/parser feed) but it must be fixed *and* the bench golden updated together.

---

## 4. Verilator-feasibility assessment

All probes were run from `/tmp`; nothing was written into the repo. Commands below are
verbatim modulo `$R` = repo root and `$W` = a scratch directory.

### 4.1 Priority 1 — `credit_manager` (plus `vc_buffer`, `ecrc` in the same probe)

```
verilator --cc --timing --timescale 1ns/1ns $R/lint/waiver.vlt \
  $R/src/tlp/tlp_pkg.sv $R/src/tlp/tlp_credit_manager.sv \
  $R/tb/tlp/tb_tlp_credit_manager.sv --top-module tb_tlp_credit_manager
```

| Module | Result | Errors | Warnings |
|---|---|---|---|
| `tb_tlp_credit_manager` | elaborates | 0 | 0 |
| `tb_tlp_vc_buffer` | elaborates | 0 | 0 |
| `tb_tlp_ecrc` | elaborates | 0 | 0 |

No cocotb-level blockers: all three tests drive only top-level ports of the SV
wrapper (`dut.<port>.value`), no hierarchy traversal, no `--public-flat-rw` needed.
`test_tlp_credit_manager.py` and `test_tlp_vc_buffer.py` use `Timer(1, units="ps")`
for combinational settling, which Verilator handles with `--timing` (already the
project default via the `timescale` flow option).

### 4.2 Priority 2 — the DLL suite

**Elaboration.** With the exact `Makefile:23-57` source list:

```
verilator --cc --timing --timescale 1ns/1ns $R/lint/waiver.vlt \
  <Makefile VERILOG_SOURCES> --top-module pcie_datalink_layer
```

→ **exit 0, 0 errors, 0 warnings.** The DLL DUT is completely Verilator-clean at this
HEAD. (Without `--timescale` it emits `TIMESCALEMOD` warnings only, because
`pcie_dllp_crc8.v:3` carries a timescale and the SystemVerilog files do not; the
FuseSoC `timescale: 1ns/1ns` flow option already covers this.)

**Cocotb hierarchy access.** A scratch cocotb test resolved all five internal paths
the suite depends on, under `--public-flat-rw`:

```
RESOLVED dllp_transmit_inst.retry_err
RESOLVED dllp_transmit_inst.tlp2dllp_inst.ph_credit_limit_r
RESOLVED dllp_transmit_inst.tlp2dllp_inst.pd_credit_limit_r
RESOLVED dllp_transmit_inst.tlp2dllp_inst.ph_credits_consumed_r
RESOLVED dllp_transmit_inst.tlp2dllp_inst.cpld_credits_consumed_r
PROBE RESULT resolved=5 unresolved=0        TESTS=1 PASS=1 FAIL=0
```

So the "compile VCS with `-debug_access+all`" requirement at
`test_dll_comprehensive.py:477-479` maps cleanly onto `--public-flat-rw`, and the
suite needs **no source edit** to find its signals.

**Full-suite behavioural run.** See §4.5 — this is the one probe whose result
determines S vs M.

### 4.3 Priority 3/4 — `end_to_end`, and the endpoint top

`test_tlp_end_to_end.py`'s toplevel is `tlp_layer` with the full TL source list —
exactly what `verilate_tlp_compile` already builds and passes. Elaboration is proven
by that target; wiring is a fileset plus a target.

`pcie_endpoint_top` elaborates under Verilator **only once `PINMISSING` is waived**
(§5.6). With `-Wno-PINMISSING` the whole TL+DLL integration builds with 0 errors and
0 warnings. Its harness `tb_pcie_endpoint_top.sv` does **not** elaborate — 4 errors,
see §5.6.

### 4.4 Feasibility table

| Candidate | Elaborates? | cocotb blockers | Effort | Reason |
|---|---|---|---|---|
| `credit_manager` | yes (0/0) | none | **S** | Add a `bench_credit_manager` fileset + `cocotb_credit_manager` fileset + one `verilate_tlp_credit_manager` target to `tb/tlp/tb_tlp.core`. Test runs as-is. |
| `vc_buffer` | yes (0/0) | none | **S** | Identical shape to the above. |
| `ecrc` | yes (0/0) | none | **S** | Identical shape. Consider landing the §2.7.1 fix separately so the golden change is its own commit. |
| `end_to_end` | yes (via `verilate_tlp_compile`) | none | **S** | New `cocotb_end_to_end` fileset + target with `toplevel: tlp_layer`. No SV wrapper needed. |
| **DLL suite** | yes (0/0) | none — all 5 paths resolve with `--public-flat-rw`, **and the full suite passes unmodified** (§4.5) | **S** | A `tb/dllp/tb_dll_comprehensive.core` with `depend: fusesoc:pcie:dllp_core` + `fusesoc:pcie:axis`, `toplevel: pcie_datalink_layer`, `--public-flat-rw`. Tests run as-is: measured PASS in 25 s with zero source edits and no timeout tuning. |
| `pcie_endpoint_top` | yes with `-Wno-PINMISSING` | harness broken | **M** | Two blockers, both one-line: declare the four missing signals in `tb_pcie_endpoint_top.sv`, and either connect or explicitly `()`-tie `allocated_tag_o`/`allocated_tag_valid_o` in `pcie_endpoint_top.sv:185`. Both are RTL/tb edits, hence not `S`. |
| `phy_receive` | not probed | unknown | **L** | No bench exists at all. Five modules, a new harness, and golden RX ordered-set vectors to derive from the spec. This is new verification, not wiring. |

### 4.5 DLL full-suite behavioural probe — **it passes, unmodified**

The decisive probe. A scratch cocotb Makefile in `/tmp` (`SIM=verilator`,
`TOPLEVEL=pcie_datalink_layer`, `MODULE=test_dll_comprehensive`, `EXTRA_ARGS`
`--timing --timescale 1ns/1ns --public-flat-rw $R/lint/waiver.vlt`, `VERILOG_SOURCES`
taken verbatim from `Makefile:23-57`) running an **unmodified copy** of
`tb/dllp/test_dll_comprehensive.py`:

```
** TEST                             STATUS  SIM TIME (ns)  REAL TIME (s)  RATIO (ns/s) **
** test_dll_comprehensive.run_test   PASS     1216145.00          24.82      49004.94  **
** TESTS=1 PASS=1 FAIL=0 SKIP=0               1216145.00          25.31      48050.96  **
```

`PCIe Data Link Layer relaxed functional test PASSED`, with the suite's own tally:
`FC frames sent=7, outgoing TLPs verified=1, incoming TLPs verified=3, malformed TLPs
rejected=1, robust DLLP checks=31`.

All 17 mandatory phases executed and passed: 1–14 and 16–18. Phase 15 is the
opt-in backpressure phase, correctly skipped because `PCIE_ENABLE_BACKPRESSURE` is
unset (`test_dll_comprehensive.py:2623`) — that is the file's designed default, not a
Verilator limitation.

**Zero source edits. Zero timeout tuning. 25 seconds of wall time**, against a suite
whose relaxed default timeouts were written for a slow commercial simulator. The
whole run is 1.2 ms of simulated time including the 4097-TLP sequence-rollover phase.

Two benign notes:

- `src/dllp/dllp_receive.sv:365` contains a `$dumpvars` that Verilator reports as
  `$dumpvar ignored, as Verilated without --trace`. Informational; adding
  `--trace-fst` (as every other FuseSoC target does) would honour it.
- The six X/Z assertions (§2.2) pass vacuously, as predicted. The suite's real
  assertions — CRC, sequence, credit, replay, arbitration — are all value-based and
  fully meaningful under a 2-state simulator.

**Conclusion: the DLL suite is an `S`.** The obstacle was never portability; it was
that nobody had tried. The remaining work is writing a `.core` file.

---

## 5. Answers to the §3 checklist

### 5.1 Is `tlp_core.core` still an orphan? Does any `.core` reference the four Makefile-only modules?

**No, and yes — but not in the way that helps.** Re-verified at this HEAD, not
inherited.

`::tlp_core:1.0.0` is no longer an orphan. It is depended on by three cores:
`src/rc/rc_core.core:26`, `src/pcie_endpoint/pcie_endpoint.core:12`, and
`tb/tlp/tb_tlp.core:15`. Its own `default` target (`src/tlp/tlp_core.core:27-30`) is
still a bare elaboration target with `toplevel: tlp_layer` and no cocotb testbench,
but the *core* is now the RTL supplier for 27 of the 45 FuseSoC targets. The
2026-07-21 finding is superseded.

All four Makefile-only modules **are** referenced by a `.core`: `tlp_ecrc.sv`
(`tlp_core.core:9`), `tlp_credit_manager.sv` (`:21`), `tlp_vc_buffer.sv` (`:22`) are
in the `rtl` fileset, so they compile into every TLP/RC target; `end_to_end` is a
test, and its DUT `tlp_layer.sv` is at `:23`. **What does not exist is a FuseSoC
*target* whose DUT is any of them** — their SV benches (`tb/tlp/tb_tlp_ecrc.sv`,
`tb_tlp_credit_manager.sv`, `tb_tlp_vc_buffer.sv`) are in no fileset anywhere. That
is precisely the incidental-vs-standalone distinction, and it is why §3.2 matters.

### 5.2 `tlp_credit_manager` coverage post-RC1

Answered in full at §3.2. Summary: RC1's fix (`7d471e0`) initialised credits so the
layer would emit packets — it did not add credit coverage. Every FuseSoC harness sets
maximum credits and never approaches a limit. Infinite-credit and credit-exhaustion
paths are tested only in `tb/tlp/test_tlp_credit_manager.py`, which no FuseSoC target
runs. Plus two RTL findings: `error_o` can never assert, and advertised-0 = infinite
credit (PCIe Base 2.1 §2.6.1) is implemented backwards as "permanently blocked".

### 5.3 Does the DLL suite depend on VCS-only behaviour? What fraction is portable?

**No VCS-only behaviour. 100% portable — measured, not estimated: the suite runs
unmodified under Verilator and passes** (§4.5). Detail at §2.2 and §4.2.

There is no `force`/`release`, no `$`-system task, no SVA, no timing control, no
constrained randomisation in the 2701 lines. The only two simulator-sensitive
categories are (a) internal hierarchy reads, which map onto `--public-flat-rw` and
were measured to resolve, and (b) six `.value.is_resolvable` X/Z assertions
(`:545,1938,2175,2197,2279,2293`, ~0.2% of the file) which become vacuously true
under a 2-state simulator. Neither blocks compilation or loading. The DUT itself
Verilates with 0 errors and 0 warnings.

The behavioural question is settled too: the suite was run end to end under Verilator
with an unmodified copy of the file and **passed** — all 17 mandatory phases, 25
seconds wall time, no timeout tuning (§4.5). The only functional loss is that the six
X/Z checks stop being real, which matters least of everything the suite tests.

### 5.4 `src/` files reachable from no top

Listed at §3.1: **15 files in no `.core` at all** (dead), plus **7 files compiled but
never instantiated**, plus `pcie_phy_top.sv` which is shipped only by FPGA-wrapper
cores and instantiated by nothing. Nothing deleted.

None of these are Gen3-roadmap stubs. The actual Gen3 stubs — `gen3_scramble.sv`,
`gen3_byte_scramble.sv` — *are* live and compiled (`scrambler.sv:32`,
`gen3_scramble.sv:55`), just not exercised at Gen3 rates.

### 5.5 Stale "flag for Joy" / ownership comments

Eight references to Joy remain in `src/` + `tb/`. All are in `tb/`; **`src/` is
clean**. For later cleanup, not edited here:

| File:line | Text |
|---|---|
| `tb/tlp/tb_tlp.core:4` | "…harness for Joy's WIP Transaction Layer…" |
| `tb/tlp/tb_tlp.core:9` | "RTL comes from `::tlp_core:1.0.0` (Joy's core) unchanged…" |
| `tb/tlp/tb_tlp.core:12` | "Joy's TL RTL (all of `src/tlp`, `tlp_pkg` first)…" |
| `tb/tlp/tb_tlp.core:114` | "command_data_last_i contract probe (evidence for Joy)…" |
| `tb/tlp/tb_tlp.core:379` | "---- command_data_last_i contract probe (evidence for Joy) ----" |
| `tb/tlp/test_tlp_conf_datalast.py:1` | "command_data_last contract probe for tlp_requester (evidence for Joy)." |
| `tb/rc/tb_pcie_rq_rc_top.sv:13` | "…replacing it with Joy's protocol-checking endpoint model…" |
| `tb/rc/test_pcie_rq_rc_top.py:163` | "It is meant to be REPLACED. Joy is building a protocol-checking endpoint…" |

Also: `tb/ltssm_conformance/TIMER_CONSTANTS.md:42` records an open question addressed
to Joy about fast-scaling the 24/48/2 ms timers. That one is a real unresolved
technical question, not stale attribution — it should be answered, not deleted.

### 5.6 What instantiates `pcie_endpoint_top`, and is it covered?

**One thing instantiates it, and that thing is broken.**

`tb/endpoint/tb_pcie_endpoint_top.sv:155` is the only instantiation anywhere in the
repository. Its only target is `tb/endpoint/tb_pcie_endpoint_top.core:16 sim`, with
`tool: vcs`. So `pcie_endpoint_top` has **no coverage under FuseSoC/Verilator at
all**, and its Python bench (`test_pcie_endpoint_top.py`, 5 tests at `:240,261,301,
330,353`) has never run in the flow Kourosh can execute.

**Two defects, both introduced by recent commits and both invisible because nothing
compiles this path:**

1. **The harness does not elaborate — in any simulator, VCS included.** `ef32bcd`
   added `cpl_timeout_valid_o`, `cpl_timeout_tag_o`, `late_cpl_valid_o` and
   `late_cpl_tag_o` to `pcie_endpoint_top` (`src/pcie_endpoint/pcie_endpoint_top.sv:
   144-148`). `tb_pcie_endpoint_top.sv:171` connects with `.*` and the harness never
   declares them (it does declare `outstanding_o` at `:127`, which `ef32bcd` also
   added — so the omission is partial, not systematic). Verilator:

   ```
   %Error: tb/endpoint/tb_pcie_endpoint_top.sv:166:5: Can't find definition of
           variable: 'cpl_timeout_valid_o'   (and cpl_timeout_tag_o,
           late_cpl_valid_o, late_cpl_tag_o)
   ```

   Fix is four `logic` declarations. `ef32bcd` touched `tb/rc/*` and `tb/tlp/*` but
   not `tb/endpoint/`.

2. **`pcie_endpoint_top` leaves two `tlp_layer` outputs unconnected.** Commit
   `31291146` ("tlp_layer: expose the tracker-allocated tag") added `allocated_tag_o`
   and `allocated_tag_valid_o`; `pcie_endpoint_top.sv:185`'s instantiation was never
   updated:

   ```
   %Warning-PINMISSING: src/pcie_endpoint/pcie_endpoint_top.sv:185:5:
           Instance has missing pin: 'allocated_tag_o'
   %Warning-PINMISSING: ... 'allocated_tag_valid_o'
   %Error: Exiting due to 2 warning(s)
   ```

   `lint/waiver.vlt:5` waives `PINCONNECTEMPTY` but not `PINMISSING`, so under the
   project's standard warnings-as-errors invocation this is a **build failure**.
   Functionally harmless (unconnected outputs), but it blocks the build.

   With `-Wno-PINMISSING`, `pcie_endpoint_top` builds with **0 errors, 0 warnings**.

Neither defect is in the trusted baseline's blast radius — all 151 tests still pass —
but both mean the TL↔DLL integration point has silently rotted since `cc1e194`.

---

## 6. Gap list and effort sketch

Plain language, for Patrick. Each item: what exists, what is proven, what is not, and
roughly how long to close.

### Link training (LTSSM)

**Exists and works.** The link-training state machine is the most thoroughly verified
part of the design: 16 separate test runs covering link-up, recovery, timeouts,
partial-lane operation, back-to-back Root-Complex-to-Endpoint training at both one
and four lanes, and an independent conformance check that compares what the machine
puts on the wire against values written down from the PCIe specification *before* the
design was run. It negotiates a four-lane link today.

**Not proven.** Nothing here is tested against a real clock domain or real serial
hardware; it has only ever run in simulation against another copy of itself.

**Effort to close:** covered under FPGA bring-up below.

### Physical layer — transmit

**Exists and works.** The transmit datapath has a golden one-lane reference and a
four-lane test that checks each lane emits the right content.

**Not proven.** Nothing above the ordered-set level; no real serialiser.

**Effort:** small — days — to extend the existing bench, once there is a reason to.

### Physical layer — receive

**Does not exist as verified logic.** Five modules make up the receive datapath and
**not one of them has a single test anywhere in the project.** Neither does the Gen1
line-coding decoder, which is required for any real PCIe wire. The link cannot come
up on hardware without this path working, and today there is no evidence that it does.

**This is the largest single gap in the stack.**

**Effort:** 3–4 weeks. New testbenches, and receive-side golden vectors derived from
the specification the same way the transmit and link-training ones were.

### Data Link Layer

**Exists and is well tested — but only in a tool we cannot run.** There is a
substantial 2700-line test covering eighteen areas: acknowledgement and retry,
sequence numbering including full rollover, corrupted-packet rejection, flow-control
credit accounting, retry-buffer capacity, and link-down recovery. It is genuinely
thorough work.

**The problem is access, not quality.** It runs only under a commercial simulator
(VCS) that requires a licence, through a separate build system, and Kourosh — now the
only engineer on this vertical — has never run it. It has never been exercised in the
project's main test flow.

**Good news from this inventory — and this is the biggest single result here.** The
obstacle was never technical. As part of this recon the entire test was run against
the free simulator, unmodified, and **it passed: all eighteen areas, in twenty-five
seconds.** No edits to the test, no adjustment of timeouts, no missing signals. The
belief that the Data Link Layer was locked behind a commercial licence was simply
never tested.

**Effort:** 1–2 days to bring the whole Data Link Layer into the one flow Kourosh can
run — the single highest-value-per-day item on this list, and the cheapest.

### Transaction Layer

**Exists and is the best-covered layer.** 96 tests across 21 runs, all passing:
request generation, tag tracking, packet parsing and validation, completion handling,
and a specification-golden conformance sweep. Completion timeouts landed recently
with dedicated tests.

**Not proven — three specific holes.**

1. **Credit management.** The logic that stops the transmitter when the link partner
   has no buffer space is on the critical path, and every test hands it unlimited
   credits, so its blocking behaviour is never exercised in the main flow. This
   already caused one regression. Worse, reading the code shows it treats the
   specification's "infinite credit" encoding as "no credit at all" — against a real
   drive, which advertises infinite credit for completions, the transmitter would
   deadlock. **Effort: 1 day to wire up the existing test; 2–3 days to fix and
   re-verify the infinite-credit handling.**
2. **End-to-end checksum (ECRC).** Computed in a way that is self-consistent but
   differs from the specification, so a real drive would reject every packet if the
   feature were enabled. **Effort: 1 day.**
3. **Three unit tests exist but do not run in the main flow** (checksum, credit
   manager, packet buffer). **Effort: 1 day total.**

### Root Complex interface

**Exists and works.** 55 tests covering the full request-out / completion-back loop,
out-of-order completions, tag exhaustion under backpressure, and the two error cases
a real drive produces during start-up. This is the newest and cleanest part.

**Not proven.** Only against a simulated drive model written in Python, not against
real hardware or Joy's protocol-checking endpoint model.

### Layer integration

**Broken today.** The one module that wires the Transaction Layer to the Data Link
Layer has a testbench that no longer compiles — recent changes added signals the
testbench never picked up, and because nothing in the automated flow builds it, the
breakage went unnoticed. Five integration tests exist and cannot run.

**Effort:** 1 day to repair and bring into the main flow. Cheap, and it restores the
only test that proves the two layers talk to each other.

### Known majors from the tracker

- **Full-width four-lane datapath.** Link training negotiates four lanes, but the
  data path does not yet split traffic across them and reassemble it. Today only one
  lane carries data. **Effort: 2–3 weeks.**
- **Full-datapath back-to-back integration.** The layers are currently connected in
  tests by wiring individual signals together rather than running a complete stack.
  **Effort: 1–2 weeks, and it depends on the integration repair above.**
- **Completion-timeout real values.** The mechanism works and is tested; the shipped
  timeout value is a simulation convenience, not the specification's real range.
  **Effort: 2–3 days.**
- **Enumeration state machine.** The next planned increment: the logic that walks the
  bus discovering devices. **Effort: 1–2 weeks.**
- **Type 1 configuration.** Needed to configure anything behind a bridge.
  **Effort: 1 week.**
- **Memory-mapped access path.** Deferred by decision; not scheduled.
- **FPGA and transceiver bring-up.** Nothing has run on real silicon. This is where
  every simulation-only assumption gets tested at once, and it depends on the receive
  datapath above. **Effort: 4–6 weeks, and the hardest to estimate.**
- **Gen3.** Scrambling stubs exist; the rate change, the different encoding scheme,
  and equalisation do not. **Effort: 6+ weeks after Gen1 x4 works on hardware.**

### Suggested order

1. Wire the Data Link Layer into the main flow (1–2 days) — biggest coverage gain per
   day, removes the licence dependency, and the test is already proven to pass.
2. Repair the layer-integration testbench (1 day) — restores a test that already
   exists.
3. Wire the four orphan Transaction Layer tests in (1–2 days).
4. Fix credit handling and the checksum divergence (3–4 days) — both are latent
   hardware failures.
5. Build receive-datapath verification (3–4 weeks) — the largest hole, and a hard
   prerequisite for hardware.

Items 1–4 total roughly two weeks and convert most of this document's red into green
without writing new verification from scratch.

---

## 7. Proposed wiring plan (phase (b) increments)

One brief per increment, each independently landable and each with a predicted test
count so the baseline arithmetic stays checkable.

| # | Increment | Core / target shape | Predicted | New baseline |
|---|---|---|---|---|
| 1 | `tlp_credit_manager` standalone | `tb/tlp/tb_tlp.core`: `bench_credit_manager` (`tb_tlp_credit_manager.sv`) + `cocotb_credit_manager` filesets, target `verilate_tlp_credit_manager`, `toplevel: tb_tlp_credit_manager` | +1 target, +1 test | 28 / 152 |
| 2 | `tlp_vc_buffer` standalone | same shape, `toplevel: tb_tlp_vc_buffer` | +1 / +1 | 29 / 153 |
| 3 | `tlp_ecrc` standalone | same shape, `toplevel: tb_tlp_ecrc`. Land the §2.7.1 divergence **as a documented divergence** here; fix it in its own later commit with the golden. | +1 / +1 | 30 / 154 |
| 4 | TL end-to-end | `cocotb_end_to_end` fileset, target `verilate_tlp_end_to_end`, `toplevel: tlp_layer`, no SV wrapper | +1 / +4 | 31 / 158 |
| 5 | Repair `tb_pcie_endpoint_top.sv` + `pcie_endpoint_top` pins | tb edit (4 `logic` decls) + RTL edit (connect or `()`-tie two pins). No new target yet — this increment only restores elaboration. | +0 / +0 | 31 / 158 |
| 6 | `pcie_endpoint_top` into FuseSoC | new `verilate_endpoint` target on `tb/endpoint/tb_pcie_endpoint_top.core`, `toplevel: tb_pcie_endpoint_top`, depends `fusesoc:pcie:endpoint_protocol` | +1 / +5 | 32 / 163 |
| 7 | **DLL suite into FuseSoC** | new `tb/dllp/tb_dll_comprehensive.core`, depends `fusesoc:pcie:dllp_core` + `fusesoc:pcie:axis`; target `verilate_dll_comprehensive`, `toplevel: pcie_datalink_layer`, `--public-flat-rw` | +1 / +1 (17 phases; measured PASS) | 33 / 164 |
| 8 | Credit-manager infinite-credit fix | RTL fix in `tlp_credit_manager.sv` + new tests on the increment-1 target | +0 / +3–4 | 33 / ~168 |
| 9 | ECRC §2.7.1 fix | RTL fix + golden update on the increment-3 target | +0 / +1–2 | 33 / ~170 |

Increments 1–4 are pure additions with no RTL change and no risk to the baseline.
Increment 5 is the first that touches tracked RTL and should be its own commit.

**Increment 7 can be pulled to the front.** It is listed at 7 only to keep the
`.core`-editing increments grouped; now that the suite is measured to pass unmodified
(§4.5), it carries no more risk than increments 1–4 and delivers far more coverage.
If the goal is the largest reduction in single-person risk per day spent, do it first.

Not in this plan, because they are new verification rather than wiring: the PHY
receive datapath, 8b/10b, and `pcie_phy_top`. Those need their own briefs.
