# SPEC_PREDICTIONS_MERGE_M3 — the resolution policy, committed before the merge runs

**Rung:** M-3, merge `origin/main` into `kourosh/dev`.
**Predecessor:** M-2 at `969ee80` (pushed).
**Written on:** `kourosh/m3-merge`, branched from `969ee80`. Escape hatch: tag `m3-pre-merge`.

| anchor | value |
| --- | --- |
| `HEAD` = `origin/kourosh/dev` | `969ee80faa907b9531108ed466d0e2ba29530e02` |
| `origin/main` | `aca47806b115cc4c4e842814d949527473285a0c` — unmoved since `docs/recon/RECON_MERGE.md` |
| merge base | `2de9afe3edc6e458799afadaf5c3a77456d6635d` (Stage D closure) |

`origin/main` changes **132 paths** against the merge base; this branch changes **58**.
Everything below is derived from `git diff <base> origin/main`, `git merge-tree`, and the
`.core` dependency closure — not from `docs/recon/RECON_MERGE.md` §R6.

---

## §0 The conflict set, recomputed at current HEAD

M-0's zero-conflict result is void: it predates M-1 and M-2's edits to `tlp_pkg.sv`,
`tlp_generator.sv` and `tlp_parser.sv`. Recomputed:

```
git merge-tree $(git merge-base HEAD origin/main) HEAD origin/main
```

| class | count | what git does |
| --- | --- | --- |
| **1. conflicted** | **2** | demands a decision |
| **1b. changed in both, clean auto-merge** | **4** | **blends both sides silently** |
| **2. `main` changed, we did not** | **106** | takes `main`'s content silently (78 of them deletions) |
| **3. added only by `main`** | **20** | appears whole |

**Class 1b is not in the brief's three lists and is the most dangerous of the four.**
Only `tlp_generator.sv` and `tlp_pkg.sv` carry conflict markers. The other four
both-changed paths merge *cleanly* — because **both branches independently made the
identical Attr\[2:0\] placement fix that M-2 landed**, so git sees the overlapping hunks
as agreeing and silently folds `main`'s *other* hunks (the message datapath) in beside
them. `tlp_parser.sv` is the sharpest case: a clean merge there imports main's entire
message parse path with no conflict shown.

2 + 4 + 106 + 20 = 132. ✔

---

## §1 The gate's compile closure — what "inert" is allowed to mean

The 42 targets resolve to exactly three `.core` roots:

| gate root | depends on | RTL reached |
| --- | --- | --- |
| `tb/tlp/tb_tlp.core` (27 targets) | `::tlp_core` + `fusesoc:pcie:lint` | all of `src/tlp/` |
| `tb/rc/tb_rc.core` (14 targets) | `::rc_core` → `::tlp_core` + lint | `src/rc/` + all of `src/tlp/` |
| `tb/ltssm_conformance/…core` (1) | `fusesoc:pcie:ltssm` | `src/ltssm/` |

**Nothing in the gate reaches `src/pcie_cfg/`, `src/dllp/`, `src/pcie_endpoint/`,
`src/scrambler/`, `src/model/`, or any `tb/endpoint/`, `tb/dllp/`, `tb/model/` file.**
`main` touched **nothing** in `src/rc/` or `src/ltssm/`.

So a `theirs` resolution is only defensible for a path that is **both** outside this
closure **and** free of symbols that exist only on `main`'s side.

---

## §2 P1 — the policy table

Resolution is **stated per path before the merge runs**. A path not listed here is a stop
trigger.

### A. Conflicted — 2 paths, all `ours`

| path | res | reason |
| --- | --- | --- |
| `src/tlp/tlp_pkg.sv` | `ours` | M-1 built `tlp_cmd_e` as the deliberate 4-bit, 10-member **union** with MSG/MSG_DATA reserved at 8/9. `main` instead renumbers 6/7 from CFG_READ1/CFG_WRITE1 to MSG/MSG_DATA — colliding with the CFG1 ordinals bound as Python integers in `test_pcie_rq_if.py:60`, `test_tlp_cfg1_spine.py:40`, `test_tlp_conf_cfg1.py:46`. `main` also adds `TLP_TYPE_MSG_*`, a `message_code` header field, and `tlp_is_message()`. |
| `src/tlp/tlp_generator.sv` | `ours` | The two Attr RTL lines are **identical on both sides**; the conflict is our spec-citation comment against `main`'s shorter one. `main`'s remaining delta is the message DW1/DW2/DW3 arms and the `payload_offset` message case, all gated on `tlp_is_message()`, which our `tlp_pkg` does not define. |

### B. Changed in both, clean auto-merge — 4 paths, all forced to `ours`

Git will **not** ask about these. Each must be forced.

| path | res | reason |
| --- | --- | --- |
| `src/tlp/tlp_parser.sv` | `ours` | Attr hunks identical both sides ⇒ no conflict. `main`'s other hunks add the message DW1/DW3 arms, `header_r.message_code`, and `tlp_is_message()` in the length rule — none resolvable against our `tlp_pkg`. |
| `tb/tlp/tb_tlp_requester.sv` | `ours` | Ours widens `command` to `[3:0]` (M-1); `main` adds `.command_message_route_i` / `.command_message_code_i` to the DUT instance. **Non-overlapping hunks, so the auto-merge takes both** and connects two ports our `tlp_requester` does not have. |
| `tb/tlp/test_tlp_generator.py` | `ours` | Both sides made the identical `expected_dw0` Attr fix; ours carries the Base 2.1 §2.2.1 citation. |
| `tb/tlp/test_tlp_parser.py` | `ours` | Same, for `dw0()`. |

### C. `main`-only, **inside** the gate closure — 8 paths, all `ours`

| path | res | reason |
| --- | --- | --- |
| `src/tlp/tlp_requester.sv` | `ours` | 21 message references. Rewrites `command_non_posted` via a new `command_posted`, adds the message header arm and four message legality terms. Needs `header_c.message_code`, absent from our pkg. |
| `src/tlp/tlp_layer.sv` | `ours` | **+6 ports** (2 in, 4 out). Three **in-gate** instantiators would go `PINMISSING`: `pcie_rq_rc_top.sv:467`, `tb_pcie_rq_if_tlp.sv:145`, `tb_pcie_rc_if_tlp.sv:202`. Confirmed against the diff, as the brief required. |
| `src/tlp/tlp_classifier.sv` | `ours` | Adds `message_request_o` and six `TLP_TYPE_MSG_*` case arms. Our `tb_tlp_comb.sv` would go `PINMISSING`. |
| `src/tlp/tlp_validator.sv` | `ours` | Six new terms, all gated on `tlp_is_message()`. |
| `tb/tlp/tb_tlp_comb.sv` | `ours` | Connects `.message_request_o`, absent from our classifier. |
| `tb/tlp/test_tlp_comb.py` | `ours` | Adds test `classifier_accepts_message_routes_as_posted` (**a new gate row**) and reads `dut.message_request`. |
| `tb/tlp/test_tlp_requester.py` | `ours` | Drives `dut.command_message_route` / `dut.command_message_code` in `reset()`; those signals do not exist on our bench. Same three test *names*, so the name set alone would not have caught this. |
| `tb/tlp/test_tlp_credit_manager.py` | `ours` | **The one non-message thing `main` contributes to the measured surface.** A competing rewrite of the same file adding `all_starvation_combinations_and_saturating_guards` — a 19th test on a target the anchor records at 18. Not inert ⇒ `theirs` is unavailable under §1. See P2. |

### D. `main`-only, outside the gate but message-coupled — 12 paths, all `ours`

| path | res | reason |
| --- | --- | --- |
| `src/pcie_endpoint/pcie_endpoint_top.sv` | `ours` | 12 message refs; propagates 6 ports into a `tlp_layer` that (per C) has none. Would undo Increment 5's pin repair. |
| `src/pcie_endpoint/README.md` | `ours` | Documents "Generic Message and Message-with-Data transmit/receive interfaces" this tree does not have. |
| `src/tlp/README.md` | `ours` | Documents Message classification/generation **and** `main`'s credit tests. Also carries `main`'s own line: *"The associated changes were not simulated when recorded."* |
| `tb/endpoint/tb_pcie_endpoint_top.{core,sv}`, `test_pcie_endpoint_top.py` | `ours` | One unit. The `.sv` (6 refs) and `.py` (2 refs) drive message ports on our port-less endpoint top; the `.core`'s lone `phy_scrambler` dep line travels with them rather than leaving a half-applied bench. |
| `tb/endpoint/tb_pcie_endpoint_line_rate.{core,sv}`, `test_pcie_endpoint_line_rate.py`, `README_LINE_RATE.md`, `pcie_gen1_logical_phy_model.sv`, `pcie_gen1_traffic.py` | `ours` (not added) | One unit — the `.core` names all four source files and nothing else on `main` references the two uncoupled ones. The bench drives message ports; splitting the unit would orphan the PHY model behind a deferred `.core`. |

### E. `main`-only, outside the gate and uncoupled — 106 paths, all `theirs`

| path(s) | res | reason |
| --- | --- | --- |
| `src/pcie_cfg/pcie_config_mux.sv` | `theirs` | Genuine fix: per-consumer handshake tracking so neither CFG consumer sees a beat twice. `pcie_config.core` is not in the gate closure. |
| `src/pcie_cfg/pcie_config_reg.sv` | `theirs` | Local `MULTIDRIVEN` waiver; already waived globally by `lint/waiver.vlt`. Inert twice over. |
| `src/dllp/dllp2tlp.sv`, `tlp2dllp.sv`, `README.md` | `theirs` | 0 message refs; `dllp_*.core` not in the gate closure. |
| `src/scrambler/scrambler.core`, `README.md` (A) | `theirs` | Adds `encode_8b10b.sv` / `decode_8b10b.sv` to the fileset — **both files already exist** in `src/scrambler/` at HEAD, so the core is not left dangling. Not in the gate closure. |
| `tb/dllp/test_dll_comprehensive.py`, `test_pcie_datalink_layer.py` | `theirs` | DLL suite, not in the gate closure. |
| `tb/tlp/test_tlp_end_to_end.py` | `theirs` | In **no** `.core` target on either branch — cannot affect any of the 42. Meets the `theirs` criterion exactly. |
| `src/model/**` (10, A), `tb/model/**` (5, A) | `theirs` | Pure-Python reference model and its tests. No fusesoc target, never built. The natural first subsystem for M-3a. |
| `pcie_endpoint.txt` (A), `output_testPcie_python.txt`, `results_pcie_datalink.xml` | `theirs` | Run logs / cocotb XML artifacts. |
| `csrc/**` (42 D), `obj_dir/**` (36 D) | `theirs` | `main` deletes committed VCS and Verilator build artifacts. None appears in any fileset; the gate deletes `build/` regardless. Taking `ours` would mean **actively re-adding** 78 artifacts — that is the improvisation, not accepting the deletion. |

**Count check:** 2 + 4 + 8 + 12 + 106 = **132** = `main`'s changed-path count. No path is unlisted.

**`manual` count: zero.** Every path is wholly one side's. This is a consequence of the
message surface being a closed compile-time set, not a convenience.

---

## §3 P2 — the gate prediction

**Claim: the post-merge gate is byte-identical to `M2_gate_anchor.txt`**
(md5 `a411e2317a2a6dd954225523ce3c9652`), **42 targets / 307 tests / 349 rows**, all PASS,
`verilate_tlp_cpl_timeout_off` and `verilate_tlp_request_tracker` both ending at
**580.00 ns**, zero Verilator diagnostics.

**The brief's stated reasoning for this prediction is not quite right, and I am recording
that before the run rather than after.** The brief expects byte-identity "because
everything `main` contributes should be inert with respect to the measured surface."
That premise is **false in exactly one place**: `tb/tlp/test_tlp_credit_manager.py` is
`main`-only, in the gate, not message-coupled, and adds a 19th test to a target the
anchor records at 18. `main` also adds a 4th test to `verilate_tlp_comb`, though that one
*is* message-coupled.

Byte-identity is therefore predicted **because the policy takes `ours` on both**, not
because `main` contributed nothing to the measured surface. The prediction and the
reasoning are separable, and only the reasoning needed correcting.

**Verdict command:** `diff M3_gate_after.txt M3_gate_before.txt && echo IDENTICAL`, plus
`md5sum` of both against `a411e2317a2a6dd954225523ce3c9652`.

---

## §4 P3 — deferral inventory scope

`docs/spec-notes/DEFERRED_FROM_MAIN.md`, committed alongside this file, must capture for every `ours`
path where `main`'s content differs: the path, `main`'s blob hash, the merge-base blob
hash, a one-sentence statement per hunk, the owning rung, and a command that reproduces
the diff **after** the merge has hidden it. 26 paths qualify (A + B + C + D minus the
paths where `main` and base agree).

---

## §5 P4 — the falsifier

**One observation falsifies the policy table: any `theirs` path turning out to be reachable
from the 42 targets.** Concretely — a non-byte-identical post-merge gate whose moved rows
belong to a target whose closure includes an §E path. That would mean the `.core`
dependency closure in §1 is wrong, and every `theirs` decision rests on it.

Secondary falsifiers, each individually decisive:

- Any `ours` path whose staged content is **not** byte-identical to `HEAD`'s — a "take
  ours" that silently absorbed a hunk.
- The merged tree failing to build without a source edit (stop trigger 5) — which would
  mean the message surface is **not** the closed set §2 claims.
- A conflict git raises on a path not in §2's table.

**Not a falsifier:** the gate changing on `verilate_tlp_comb` or
`verilate_tlp_credit_manager`. Those two are predicted to be *unchanged precisely because
the policy excludes `main`'s additions there*; if they move, the resolution failed to
apply, which P1 catches at staging time before the gate ever runs.
