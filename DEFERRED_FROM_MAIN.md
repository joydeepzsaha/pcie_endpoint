# DEFERRED_FROM_MAIN — what M-3 set aside, and how to get it back

M-3 resolves 26 paths as **take-ours**. Git records the merge, so **these hunks will never
be offered as a conflict again**. Silence after this point is not evidence they were
considered. This file is the only record that they were.

| anchor | hash |
| --- | --- |
| merge base | `2de9afe3edc6e458799afadaf5c3a77456d6635d` |
| `origin/main` | `aca47806b115cc4c4e842814d949527473285a0c` |
| ours at merge time | `969ee80faa907b9531108ed466d0e2ba29530e02` |

**Reproduce any single path's deferred content after the merge:**

```bash
git diff 2de9afe3edc6e458799afadaf5c3a77456d6635d aca4780 -- <path>   # what main did
git diff HEAD aca4780 -- <path>                                       # what we still lack
git show aca4780:<path>                                               # main's whole file
```

**Reproduce the entire deferral in one command:**

```bash
git diff 2de9afe3edc6e458799afadaf5c3a77456d6635d aca4780 -- \
  src/tlp/tlp_pkg.sv src/tlp/tlp_generator.sv src/tlp/tlp_parser.sv \
  src/tlp/tlp_requester.sv src/tlp/tlp_layer.sv src/tlp/tlp_classifier.sv \
  src/tlp/tlp_validator.sv src/tlp/README.md \
  src/pcie_endpoint/pcie_endpoint_top.sv src/pcie_endpoint/README.md \
  tb/tlp/tb_tlp_requester.sv tb/tlp/tb_tlp_comb.sv tb/tlp/test_tlp_comb.py \
  tb/tlp/test_tlp_requester.py tb/tlp/test_tlp_credit_manager.py \
  tb/tlp/test_tlp_generator.py tb/tlp/test_tlp_parser.py \
  tb/endpoint/
```

---

## 1. The message datapath — 23 paths, owner: **M-3a** (or a dedicated message rung)

The import and the fail-open guard are **one change**. M-1 reserved `TLP_CMD_MSG` /
`TLP_CMD_MSG_DATA` at ordinals 8/9 with no decode path, and recorded that
`tlp_requester` fails open on them: `command_non_posted` is `!= TLP_CMD_MEM_WRITE` (a
message reads as non-posted, but messages are posted), and the `tlp_type` select has no
message arm, so a message command is emitted as a **well-formed Memory Read**. That is
inert only while nothing can drive 8 or 9. Every path below makes them drivable.

### 1.1 Package — the root dependency

| path | `main` blob | base blob |
| --- | --- | --- |
| `src/tlp/tlp_pkg.sv` | `68a60e336c88` | `cfec54630f6e` |

- Adds six `TLP_TYPE_MSG_*` members to `tlp_type_e` at 5'b10000–5'b10101.
- Adds `logic [7:0] message_code` to `tlp_header_t`, between `tag` and `first_be`.
- Adds `tlp_is_message(tlp_type)` — a range test over those six.
- **Renumbers `tlp_cmd_e`:** replaces `TLP_CMD_CFG_READ1`/`CFG_WRITE1` at ordinals 6/7
  with `TLP_CMD_MSG`/`TLP_CMD_MSG_DATA` and keeps the enum 3-bit.
  ⚠️ **This renumbering must not be adopted.** Three bench files bind 6 and 7 as CFG1
  Python integers (`test_pcie_rq_if.py:60`, `test_tlp_cfg1_spine.py:40`,
  `test_tlp_conf_cfg1.py:46`). M-1's 4-bit union at 8/9 already carries `main`'s
  *members*; only the *numbering* is deferred, and it should stay deferred permanently.
  **Only the first three bullets are owed.**

### 1.2 RTL that cannot compile without §1.1

| path | `main` blob | base blob | what is deferred |
| --- | --- | --- | --- |
| `src/tlp/tlp_requester.sv` | `7dbc361936bd` | `87c030bfcc58` | `command_message_route_i`/`command_message_code_i` ports and their registers; `command_is_message`; **the fail-open repair** — `command_posted` becomes `MEM_WRITE ‖ message` and `command_non_posted` its inverse; a message header arm setting `fmt`, `tlp_type = {2'b10, route}`, zeroed BE/tag, `message_code`; four legality terms (MSG must be zero-length, MSG_DATA DWORD-aligned and within limit, route ≤ 5); message requests bypass segmentation and skip `REQ_TAG`. |
| `src/tlp/tlp_layer.sv` | `3fc10e108f36` | `e2b006015272` | **Six new ports** — in: `command_message_route_i`, `command_message_code_i`; out: `target_message_o`, `target_message_route_o`, `target_message_code_o`, `target_message_data_o`. Plus `parsed_message` wiring, the classifier port, the requester ports, and messages joining `TLP_CLASS_POSTED` in `tx_packet_class_r`. |
| `src/tlp/tlp_classifier.sv` | `17acd8dbf2ce` | `1e00f975ba74` | `message_request_o` port; six `TLP_TYPE_MSG_*` case arms classifying as `TLP_CLASS_POSTED`; the output cleared on the unsupported path. |
| `src/tlp/tlp_validator.sv` | `e7462b954b6d` | `78d7f1c94066` | `message` term; messages admitted to the fmt/type whitelist; messages **required** to be 4DW; zero-length allowed for messages; messages exempted from both byte-enable rules. |
| `src/tlp/tlp_generator.sv` | `a95dbd8f9d84` | `f312a8ae580f` | Message DW1 (`{requester_id, tag, message_code}`), DW2 (`address[63:32]`), DW3 (full `address[31:0]`, **not** DW-aligned), and `payload_offset = 0`. ⚠️ The Attr lines in this diff are **already landed** by M-2 — identical on both sides. Only the message arms are owed. |
| `src/tlp/tlp_parser.sv` | `64abaff31c7f` | `5fb3e02c2ae9` | Message zero-length rule in both DW0 paths; message DW1 decode into `message_code`; message DW3 taking the full 32 bits. ⚠️ Same Attr caveat — the Attr hunk here is byte-identical to what M-2 already landed. |
| `src/pcie_endpoint/pcie_endpoint_top.sv` | `a0c64706be97` | `67bb6b3df6f3` | Pure propagation: the same 6 ports declared and passed through to `tlp_layer`. Owed **only after** `tlp_layer`; importing it earlier reverses Increment 5's pin repair. |

### 1.3 Benches for the above

| path | `main` blob | base blob | what is deferred |
| --- | --- | --- | --- |
| `tb/tlp/tb_tlp_requester.sv` | `bba11c64408e` | `035800b0cfee` | Two message signals + their DUT connections. ⚠️ Our `command` widening to `[3:0]` is **not** in `main`'s version — this file needs both sides' changes when the rung lands. |
| `tb/tlp/tb_tlp_comb.sv` | `b60331a158df` | `bb7a9a951b95` | `message_request` signal + `.message_request_o` connection. |
| `tb/tlp/test_tlp_comb.py` | `3d2519352ab8` | `33c85390f8ad` | `TYPE_MSG_TO_RC=16`, `TYPE_MSG_GATHER=21`, and test `classifier_accepts_message_routes_as_posted` (**+1 gate row on `verilate_tlp_comb`**, 3 → 4). |
| `tb/tlp/test_tlp_requester.py` | `9b478a615f43` | `b643ecaa52ba` | Two signal initialisations in `reset()`. Same three test names — the name set alone does **not** reveal this. |
| `tb/endpoint/tb_pcie_endpoint_top.{core,sv}`, `test_pcie_endpoint_top.py` | `3b3d76863442`, `e5206d2d873d`, `984b016eb2c1` | `264989dc12cc`, `d6a3873766d3`, `6f8904f4b465` | Message port drives on the endpoint bench, +477 lines of endpoint tests, and one `phy_scrambler` dep line on the `.core`. Interacts with the five endpoint tests the brief holds out of scope. |

### 1.4 The line-rate suite — **added by `main`, not taken** (6 paths, no base blob)

| path | `main` blob |
| --- | --- |
| `tb/endpoint/tb_pcie_endpoint_line_rate.core` | `82e747cc0652` |
| `tb/endpoint/tb_pcie_endpoint_line_rate.sv` | `8cb4c5131b19` |
| `tb/endpoint/test_pcie_endpoint_line_rate.py` | `e45042a23b54` |
| `tb/endpoint/pcie_gen1_logical_phy_model.sv` | `f848ec9ceac8` |
| `tb/endpoint/pcie_gen1_traffic.py` | `670ca394065e` |
| `tb/endpoint/README_LINE_RATE.md` | `7deb8d357c36` |

A Gen1 line-rate endpoint suite: a 350-line logical PHY model, a 299-line bench, 296
lines of traffic generation, and 1070 lines of tests. Deferred **as one unit** — the
`.core` names all four source files, nothing else on `main` references the PHY model or
the traffic generator, and the bench drives `pcie_endpoint_top`'s message ports. Taking
the two uncoupled files alone would orphan them behind a deferred `.core`.

Recover with `git checkout aca4780 -- tb/endpoint/` once §1.2 has landed.

### 1.5 Documentation

| path | `main` blob | base blob | what is deferred |
| --- | --- | --- | --- |
| `src/tlp/README.md` | `cd5cf9fc57e6` | `ebec8d6969ed` | Message rows in the module and test tables; a Messages section; a 12-Aug-26 change-log entry on the DLL receive-path repair. Also `main`'s own admission: *"The associated changes were not simulated when recorded."* |
| `src/pcie_endpoint/README.md` | `86143f9c07af` | `308d40eab3e8` | +106 lines including the generic Message TX/RX interface description. |

---

## 2. Not the message datapath — 1 path, owner: **a named credit rung**

| path | `main` blob | base blob |
| --- | --- | --- |
| `tb/tlp/test_tlp_credit_manager.py` | `1c1fe9a9199f` | `42bc5cefe8f7` |

**The only thing `main` contributes to the measured surface that has nothing to do with
messages.** A competing rewrite of the same file: it hoists `_advertise` /
`_reset_and_init` above the first test and adds
`all_starvation_combinations_and_saturating_guards` — a 19th test on
`verilate_tlp_credit_manager`, which `M2_gate_anchor.txt` records at 18.

The new test walks all three pools proving independent header-vs-data blocking and that a
blocked request cannot wrap either zero-valued counter. It initialises every pool at 7
first, explicitly to avoid the trap recorded in `[credit-manager-fc-model-gate]`: a `0`
cumulative advertisement at init latches a pool **infinite**, not starved.

Deferred **only** because it moves a gate row and M-3 is a merge. It is not message-coupled,
does not depend on `tlp_pkg`, and is the cheapest real item on `main` to qualify. It should
be an early M-3a candidate, sequenced with its own prediction and pre/post gates so the
19th row is a *predicted* change rather than a merge side effect.

---

## 3. Cross-check — what `main` and this branch converged on independently

Not deferred; recorded so the deferral is not misread as broader than it is.

**Both branches independently made the identical Attr\[2:0\] placement fix** — `Attr[2]`
at `dw0[10]`, `Attr[1:0]` at `dw0[21:20]` — in `tlp_generator.sv`, `tlp_parser.sv`,
`test_tlp_generator.py` and `test_tlp_parser.py`. The RTL and golden lines are
byte-identical across the two histories; only our spec-citation comments differ. M-2's
conformance finding is therefore **independently corroborated by `main`**, and nothing
about the Attr fix is deferred.

Consequence: `tlp_parser.sv`, `test_tlp_generator.py` and `test_tlp_parser.py` merge
*cleanly*, which is exactly why the message hunks in them had to be excluded by explicit
policy rather than by a conflict.
