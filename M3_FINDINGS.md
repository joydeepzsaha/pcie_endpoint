# M3_FINDINGS — one history, a green tree, and an inventory of what was not executed

**Rung:** M-3, merge `origin/main` into `kourosh/dev`. **Landed and pushed.**

| hash | what |
| --- | --- |
| `969ee80` | M-2, the pre-merge anchor. Tag `m3-pre-merge` still points here. |
| `aca4780` | `origin/main`, unmoved since `RECON_MERGE.md`. Stop trigger 1 did not fire. |
| `2de9afe` | merge base (Stage D closure). |
| `08ef1a5` | M-3 docs — policy + deferral inventory, committed **before** the merge. |
| `d2eb70e` | the merge. Parents `08ef1a5` + `aca4780`. |
| `8d5d20c` | the two gates. `HEAD` = `origin/kourosh/dev`, verified from the fetched ref. |

---

## 1. What `main` actually contributed to the measured surface

**Nothing.**

Both gates are byte-identical to `M2_gate_anchor.txt` — md5
`a411e2317a2a6dd954225523ce3c9652` across all three — 349 rows, 42 targets,
**307 tests, 307 PASS, 0 FAIL, 0 SKIP, rc=0 on every target**, both sim-time
invariants at 580.00 ns, zero Verilator build diagnostics.

That answer needs one qualification, and it is the most useful thing this rung
produced. "Nothing" is the outcome **after** the policy ran, not a property of
`main`. `main` does touch the measured surface, in two places:

| what `main` adds inside the gate | target | anchor | with `theirs` |
| --- | --- | --- | --- |
| `classifier_accepts_message_routes_as_posted` | `verilate_tlp_comb` | 3 tests | 4 |
| `all_starvation_combinations_and_saturating_guards` | `verilate_tlp_credit_manager` | 18 tests | 19 |

The first is message-coupled and could not have come across regardless. **The
second is not**, and it is the single thing `main` offers that the deferral
argument does not reach. It was taken `ours` because a merge must not move a gate
row — not because it is wrong. See §5.

---

## 2. The policy as executed, and every deviation from P1

**Deviations: none.** All 132 paths resolved exactly as P1 stated; nothing was
decided at merge time.

| class | paths | resolution | executed |
| --- | --- | --- | --- |
| A — conflicted | 2 | `ours` | ✅ `tlp_pkg.sv`, `tlp_generator.sv` — the only two git raised |
| B — changed in both, clean auto-merge | 4 | `ours` (forced) | ✅ |
| C — `main`-only, inside the gate closure | 8 | `ours` (forced) | ✅ |
| D — `main`-only, outside the gate, message-coupled | 12 | `ours` / not added | ✅ |
| E — `main`-only, outside the gate, uncoupled | 106 | `theirs` | ✅ |
| — | **132** | 26 `ours` / 106 `theirs` / **0 `manual`** | |

**Verification, not assumption** (§6 required proof, not trust):

| check | result |
| --- | --- |
| every `ours` path staged byte-identical to `HEAD` | **20/20 OK** |
| the 6 line-rate paths absent from index **and** worktree | **6/6 OK** |
| every `theirs` path staged byte-identical to `origin/main` | **28/28 OK, 0 mismatches** |
| the 78 artifact deletions applied | **0 of 78 still tracked** |
| paths staged that appear in none of §2's lists | **0** |
| unmerged paths remaining | **0** |

106 staged changes against `HEAD` = 28 `theirs` files + 78 deletions. The 26
`ours` paths contribute zero delta, which is the definition of a take-ours that
did not absorb a hunk.

**No RTL was edited.** Stop trigger 5 was never approached: the merged tree built
cold, twice, with no source change.

---

## 3. P1–P4 scored

| | verdict | note |
| --- | --- | --- |
| **P1** policy table | **held** | 132/132 entries; zero improvisation; the two conflicts git raised were the two predicted |
| **P2** gate byte-identical | **held** | three matching md5s; **but its stated *reasoning* was falsified before the run and corrected in the prediction doc** — see §5 |
| **P3** deferral scope | **held** | 26 paths in `DEFERRED_FROM_MAIN.md` with blob hashes, per-hunk statements, owning rungs, reproduction commands |
| **P4** falsifier | **not exercised** | no `theirs` path proved reachable from the 42 targets; the `.core` closure in §1 of the prediction doc stands |

### The brief's §2 taxonomy was incomplete, and the missing class was the dangerous one

The brief asked for three lists: conflicted, auto-merged-`main`-only, added-only.
There is a fourth — **changed in both, auto-merges cleanly** — and it holds four
paths that git would have blended silently:

`src/tlp/tlp_parser.sv`, `tb/tlp/tb_tlp_requester.sv`,
`tb/tlp/test_tlp_generator.py`, `tb/tlp/test_tlp_parser.py`.

They merge cleanly because **both branches independently made the identical
Attr\[2:0\] placement fix**. Git read the overlapping hunks as agreeing and would
have folded `main`'s *other* hunks — the message datapath — in beside them with
no conflict shown. `tlp_parser.sv` is the sharpest case: a clean merge there
imports the entire message parse path silently. Had the rung trusted "git raised
two conflicts, so there are two decisions," four message imports would have
landed unnoticed and the gate would still have been green, because none of the
four is exercised by a message stimulus that does not exist.

**Side finding, and a real one: `main` independently corroborates M-2.** The Attr
RTL and golden lines are byte-identical across two histories that never
communicated. M-2's conformance claim — Attr\[2\] at `dw0[10]`, Attr\[1:0\] at
`dw0[21:20]` — is now confirmed by an independent implementation.

### The message surface is a closed compile-time set

Not a preference. `main`'s `tlp_requester`, `tlp_layer`, `tlp_classifier`,
`tlp_validator`, `tlp_generator` and `tlp_parser` all reference
`tlp_is_message()`, `TLP_TYPE_MSG_*` or `header.message_code` — symbols that exist
only in `main`'s `tlp_pkg`. Take-ours on the package **forces** take-ours on all
six. There was no partial import available.

The brief's `tlp_layer` concern was confirmed, with a mechanism it did not name.
The six new ports do not break the `tlp_layer`-toplevel targets — cocotb drives a
toplevel's ports directly, so a toplevel has no missing pins. The `PINMISSING`
break comes from three **RC-side** instantiators, all inside the gate:
`pcie_rq_rc_top.sv:467`, `tb_pcie_rq_if_tlp.sv:145`, `tb_pcie_rc_if_tlp.sv:202`.
`PINMISSING` is not waived in `lint/waiver.vlt`, so the clean cold build is direct
evidence the ports did not come across.

---

## 4. The `theirs` inventory — `main`'s content now in the tree, **unexecuted**

This is M-3a's input list. Every path below is in the tree and has **never been
run by anything**; none is reachable from the 42 targets' `.core` closure.

| group | paths | what it is |
| --- | --- | --- |
| `src/model/**` | 10 | Python reference model: `endpoint_bfm` (977 L), `data_link` (447), `flow_control` (348), `gen1_phy` (338), `tlp` (360), `types` (281), `config`, `crc`, `__init__`, README |
| `tb/model/**` | 5 | its pytest suite: `test_endpoint_bfm`, `test_gen1_phy`, `test_protocol`, `test_support`, README |
| `src/dllp/` | 3 | `dllp2tlp.sv` (488 L changed), `tlp2dllp.sv` (208), README |
| `src/pcie_cfg/` | 2 | `pcie_config_mux.sv` — per-consumer handshake tracking so neither CFG consumer sees a beat twice; `pcie_config_reg.sv` — a local `MULTIDRIVEN` waiver already covered globally |
| `tb/dllp/` | 2 | `test_dll_comprehensive.py`, `test_pcie_datalink_layer.py` |
| `src/scrambler/` | 2 | `.core` adds `encode_8b10b.sv`/`decode_8b10b.sv` — both files already existed, so nothing dangles |
| `tb/tlp/test_tlp_end_to_end.py` | 1 | in **no** `.core` target on either branch |
| logs/artifacts | 3 | `pcie_endpoint.txt`, `output_testPcie_python.txt`, `results_pcie_datalink.xml` |
| `csrc/**`, `obj_dir/**` | 78 (deleted) | committed VCS/Verilator build artifacts `main` removes; in no fileset. Refusing would have meant *actively re-adding* them |

**28 files + 78 deletions = 106.**

Two observations for whoever qualifies these:

- `src/tlp/README.md` on `main` — deferred, not taken — contains `main`'s own
  sentence: *"The associated changes were not simulated when recorded."* That is
  `main` stating its DLL receive-path work is unqualified. Treat the whole
  `theirs` list accordingly.
- `main`'s `test_tlp_end_to_end.py` adds a `TLP_HEADER_FIELDS` packing table that
  **omits `message_code`**, though `main`'s own `tlp_header_t` contains it between
  `tag` and `first_be`. The table is wrong against `main`'s own struct. It is dead
  code on both branches, so it costs nothing today — but it must not be trusted as
  a layout reference.

---

## 5. The one thing `main` contributes that is neither message nor inert

`tb/tlp/test_tlp_credit_manager.py`. `main`-only, inside the gate, no message
coupling, no `tlp_pkg` dependency. It restructures the file and adds
`all_starvation_combinations_and_saturating_guards`: all three pools walked,
proving independent header-vs-data blocking and that a blocked request cannot wrap
either zero-valued counter. It initialises every pool at 7 **before** creating a
starvation case — explicitly avoiding the trap that a `0` cumulative advertisement
at init latches a pool *infinite*, not starved.

This is why P2's stated reasoning needed correcting **before** the run, not after.
The brief predicted byte-identity "because everything `main` contributes should be
inert with respect to the measured surface." That premise is false here. The
*prediction* held; the *reason* did not. Byte-identity is a consequence of the
policy taking `ours`, not of `main` being inert.

It is the cheapest real item on `main` to qualify — no RTL, no ports, one file —
and it should carry its own prediction and pre/post gates so the 19th row lands as
a **predicted** change rather than a merge side effect.

---

## 6. What M-3 does not establish

- **No file from `main` has been executed.** Not one of the 28 `theirs` paths is
  reachable from any of the 42 targets. A green gate says nothing about them.
- **The message datapath is absent**, and the fail-open at ordinals 8/9 remains
  reachable only in principle: `tlp_requester` still derives `command_non_posted`
  as `!= TLP_CMD_MEM_WRITE` and still has no message arm in its `tlp_type` select,
  so a message command would emit a well-formed Memory Read. Nothing drives 8 or 9,
  so nothing is wrong today. **The import and the guard are one change.**
- **`main`'s `tlp_cmd_e` renumbering is refused permanently**, not deferred. M-1's
  4-bit union already carries `main`'s members at 8/9; adopting `main`'s numbering
  would move CFG_READ1/CFG_WRITE1 off 6 and 7, which three bench files bind as
  Python integers. Only the numbering is refused — the members are already present.
- **No synthesis.** The S-1/S-2 area and timing numbers now describe a
  **twice-superseded** netlist: once by M-1/M-2, again by this merge.
- **Nothing about the DLL, endpoint, config-mux or scrambler paths** — all outside
  the gate closure, all unmeasured here.
- **The five `pcie_endpoint_top` tests and the line-rate suite were not run**, and
  the line-rate suite is not in the tree at all.

---

## 7. M-3a

**Unblocked as written.** It has a merged history, a green tree at
`a411e2317a2a6dd954225523ce3c9652`, and an explicit 28-path input list where every
entry is present-but-unexecuted.

**First subsystem: `src/model/` + `tb/model/`.** It is the largest thing `main`
brings (~5,200 lines), it is self-contained Python with its own pytest suite, it
has **zero RTL coupling and no fusesoc target**, and qualifying it cannot perturb
the 42 targets. It is the only group on the list that can be taken from
unexecuted to qualified without touching the gate at all.

**Second, and cheap: `tb/tlp/test_tlp_credit_manager.py`** — §5. One file, one
predicted row, no RTL.

**Not M-3a: the message datapath.** Six RTL files, six `tlp_layer` ports, three
in-gate instantiators to rewire, the fail-open repair in `tlp_requester`, four
benches, and `pcie_endpoint_top`'s propagation — one change, its own rung, its own
mutation gate. `DEFERRED_FROM_MAIN.md` §1 is its work order.

---

## 8. Stop triggers

| # | trigger | fired |
| --- | --- | --- |
| 1 | `origin/main` moved since `aca4780` | no |
| 2 | pre-gate not byte-identical to `M2_gate_anchor.txt` | no — md5 matched |
| 3 | a path needing a resolution P1 lacks | no — 132/132 covered |
| 4 | an `ours`/`theirs` path not byte-identical after staging | no — 54/54 verified |
| 5 | merged tree requiring a source edit to build | no — no RTL edited |
| 6 | post-gate not byte-identical to pre-gate | no — `diff` empty both ways |
| 7 | any Verilator diagnostic | no — 0 build diagnostics, 0 lint rule tags |

All 124 `%Warning` lines in each sweep carry a sim-time prefix: they are `$warning`
calls the RTL emits from **passing** tests (`pcie_rq_if` descriptor rejections,
`pcie_rc_if` drained payloads, gearbox `tkeep` legality), identical across both
gates. Zero lines lack a sim-time prefix, which is what a Verilator build
diagnostic would look like.

**Attribution:** zero matches across all 14 commits `m3-pre-merge..HEAD`.
Tag `m3-pre-merge` → `969ee80`, retained.
