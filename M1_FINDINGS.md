# M1_FINDINGS — widening `tlp_cmd_e` and reserving ordinals 8/9

Stage M-1, on `kourosh/dev` alone. Nothing from `origin/main` entered the tree.

| commit | hash | content |
|---|---|---|
| predictions | `d26986a` | `docs/predictions/SPEC_PREDICTIONS_MERGE_M1.md`, written before any RTL edit existed |
| widen | `c2ff977` | `tlp_cmd_e` → `logic [3:0]`, member set unchanged at eight |
| reserve | `d8df135` | `TLP_CMD_MSG` = 8, `TLP_CMD_MSG_DATA` = 9, declared not decoded |
| findings | *this* | this file and the three gate records |

Base: `99b7501` (M-0). Total RTL change across both RTL commits: **four files, three
of them a single character.**

---

## §1 The gates, and the identity result

Three cold sweeps. Each: `rm -rf build/`, then 42 targets run sequentially, one
`fusesoc run` per target, target list derived by grep from the `.core` files rather
than transcribed.

Each sweep is recorded as **347 normalised rows**:

```
T|<target>|<module>.<test>|<STATUS>|<SIM TIME ns>          305 rows, one per test
A|<target>|rc=<n>|TESTS=.. PASS=.. FAIL=.. SKIP=..|simend=<ns>    42 rows, one per target
```

`REAL TIME (s)` and `RATIO (ns/s)` are dropped — wall-clock, and the only
non-deterministic columns in the compared record. Nothing else is normalised: no
timestamp rewriting, no path munging, because no other compared field contains either.
Full logs are deliberately not compared — `build/` is deleted before each gate and
Verilator writes absolute paths into it, so full-log identity is unachievable and would
be the wrong target.

**The verdict:**

```
$ diff M1_gate_before.txt M1_gate_widen.txt   && echo IDENTICAL
IDENTICAL
$ diff M1_gate_widen.txt  M1_gate_reserve.txt && echo IDENTICAL
IDENTICAL
$ diff M1_gate_before.txt M1_gate_reserve.txt && echo IDENTICAL
IDENTICAL

$ md5sum M1_gate_*.txt
6492c8ab8f7f0bd3ac533db6ddb3b0d3  M1_gate_before.txt
6492c8ab8f7f0bd3ac533db6ddb3b0d3  M1_gate_reserve.txt
6492c8ab8f7f0bd3ac533db6ddb3b0d3  M1_gate_widen.txt
```

**One md5 across all three.** 42 targets / 305 tests / 305 PASS / 0 FAIL / 0 SKIP in
each, every `rc=0`, every per-test sim time unmoved.

Verilator emitted **zero warnings and zero errors** across all 126 target builds
(42 × 3): `grep -rhoE "%(Warning|Error)-[A-Z]+"` over every saved log returns nothing.

This record is finer than `RECON_MERGE_baseline.txt`, which held only the 42 aggregates.
A per-test row catches two tests trading sim time while their target total holds still —
a change the M-0 format could not have seen. That refinement cost nothing and is the
form later stages should keep.

---

## §2 Predictions scored

| | prediction | verdict |
|---|---|---|
| **P1** | regression byte-identical across both RTL commits | **held** — one md5, three gates |
| **P2** | both sim-time invariants stay 580.00 ns | **held** — `request_tracker` and `cpl_timeout_off` both 580.00 in all three |
| **P3** | no struct changes width, no field moves | **held, and provably vacuous** — see §3.2 |
| **P4** | no case-completeness warning at any site; no resolution required | **held** — zero diagnostics, and zero was the *predicted* number |
| **P5** | six predicates return 0; three derived outcomes do not | **held exactly, all nine statements** — see §4 |
| **P6** | the falsifier is a non-empty gate diff | **not triggered**; its two named blind spots were separately demonstrated — see §5 |

No prediction was falsified. That is a weaker result than a falsification would have
been, and §3.1 records the one thing that *was* wrong going in: not a prediction, but the
census the predictions were built to replace.

---

## §3 The census, and the gap in `RECON_MERGE.md` §R1

### 3.1 ⚠️ Two sites R1 missed, and the class that hid them

R1's site table was built by grepping the type name `tlp_cmd_e`. Two signals carry a
command at a **hard-coded width** and are invisible to that method:

| site | before | after | connects to |
|---|---|---|---|
| [tb/rc/tb_pcie_rq_if.sv:37](tb/rc/tb_pcie_rq_if.sv#L37) | `logic [2:0]  command_o;` | `logic [3:0]` | `pcie_rq_if.command_o` (`tlp_cmd_e`) at [:77](tb/rc/tb_pcie_rq_if.sv#L77) |
| [tb/tlp/tb_tlp_requester.sv:11](tb/tlp/tb_tlp_requester.sv#L11) | `logic [2:0] command;` | `logic [3:0]` | `tlp_requester.command_i` (`tlp_cmd_e`) at [:65](tb/tlp/tb_tlp_requester.sv#L65) |

**The class: a signal declared by raw width that connects to an enum-typed port.** A
type-name grep cannot see it, because the type name never appears.

The census method that closes it — and the one later stages should use — is to work from
the *connections*, not the type: enumerate every `.command_i(` / `.command_o(` port
connection in the tree, then resolve each connected signal's declaration. Six signals
reach a command port; four are `tlp_cmd_e` and widen automatically, and these two are
not.

R1 was not careless; it answered the question it was asked ("every site that *names* a
member or the type"). The finding is about the **method**: for a width change, naming
the type is the wrong index. Bit-width questions must be indexed by connectivity.

### 3.2 No packed struct contains a `tlp_cmd_e` field

Every packed struct in `src/tlp/` and `src/rc/` was enumerated:

| struct | width before | width after | contains `tlp_cmd_e`? |
|---|---|---|---|
| [tlp_header_t](src/tlp/tlp_pkg.sv#L102) | unchanged | unchanged | no — carries wire fields `fmt[2:0]`, `tlp_type[4:0]` |
| [rq_descriptor_t](src/rc/pcie_rq_rc_pkg.sv#L43) | 128 | **128** | no — carries `req_type` as `logic [3:0]` at `[78:75]` |
| [rc_descriptor_t](src/rc/pcie_rq_rc_pkg.sv#L117) | unchanged | unchanged | no |

**Do consumers index those bits by literal? Yes — and it does not matter.** Both
descriptor structs are flattened onto 128-bit AXIS words and indexed by literal position
in RTL and in Python ([enum_tb_common.py:160,188](tb/rc/enum_tb_common.py#L160),
[:278,297](tb/rc/enum_tb_common.py#L278)). Stop trigger §8.3 exists for exactly this
shape and **could not fire**, because the field those consumers index is `req_type` — a
separate 4-bit enum (`rq_req_type_e`) that was already four bits wide — and it is
decoupled from `tlp_cmd_e` by the mapping case at
[pcie_rq_if.sv:263-277](src/rc/pcie_rq_if.sv#L263). The wire encoding and the internal
command encoding are two different alphabets joined by a lookup, which is why widening
one cannot move the other.

That decoupling is the single most load-bearing property in M-1. It is what makes the
widening a package-local change rather than a wire-format change.

### 3.3 No `case` selector is a `tlp_cmd_e`

All 78 `case` / `casez` / `unique case` statements in `src/` were enumerated and their
selectors resolved. **None selects on a `tlp_cmd_e`.** The nearest is
[pcie_rq_if.sv:263](src/rc/pcie_rq_if.sv#L263) `unique case (desc_type)`, whose selector
is `rq_req_type_e` — and which already carries a `default` at
[:277](src/rc/pcie_rq_if.sv#L277).

Command membership is tested **exclusively** by `==` chains inside the six
`command_is_*` functions. That is why adding two members produced no diagnostic
anywhere: there is no exhaustiveness obligation to violate.

### 3.4 Python ordinals: none moved

37 constant definitions across 11 files bind command ordinals; the highest bound is 7.
Because M-1 **appends**, every one is still correct. Three files bind the two ordinals
that the alternative numbering would have taken:

- [test_pcie_rq_if.py:59-60](tb/rc/test_pcie_rq_if.py#L59-L60)
- [test_tlp_cfg1_spine.py:39-40](tb/tlp/test_tlp_cfg1_spine.py#L39-L40)
- [test_tlp_conf_cfg1.py:45-46](tb/tlp/test_tlp_conf_cfg1.py#L45-L46)

---

## §4 P5 in full: what the reserved members actually do

Read back from the source **after** both commits, not assumed.

**All six predicates return 0**, because each is an explicit member list and no term
names a reserved member (`grep` for a predicate naming `MSG` returns nothing):

| function | site | value for `TLP_CMD_MSG` / `TLP_CMD_MSG_DATA` |
|---|---|---|
| `command_is_config` | [tlp_requester.sv:82](src/tlp/tlp_requester.sv#L82) | 0 |
| `command_is_config1` | [:92](src/tlp/tlp_requester.sv#L92) | 0 |
| `command_is_io` | [:96](src/tlp/tlp_requester.sv#L96) | 0 |
| `command_is_config_or_io` | [:100](src/tlp/tlp_requester.sv#L100) | 0 |
| `command_is_read` | [:104](src/tlp/tlp_requester.sv#L104) | 0 |
| `command_is_write` | [:109](src/tlp/tlp_requester.sv#L109) | 0 |

**⚠️ Three derived outcomes are not 0, exactly as predicted:**

| derived | site | value | correct for a real message? |
|---|---|---|---|
| `command_has_data` | [:142](src/tlp/tlp_requester.sv#L142) | 0 | **wrong** for `MSG_DATA` |
| `command_non_posted` | [:143](src/tlp/tlp_requester.sv#L143) | **1** | **wrong — messages are posted** |
| `command_limit` | [:114](src/tlp/tlp_requester.sv#L114) | `max_payload_bytes_i == 0 ? 128 : max_payload_bytes_i` | incidental |
| `header_c.tlp_type` | [:152-160](src/tlp/tlp_requester.sv#L152-L160) | **`TLP_TYPE_MEM`** — no message arm exists | **wrong — emits a well-formed Memory Read** |

**The requester fails open on the reserved members.** This is not a defect M-1
introduced: it is the pre-existing behaviour for any command outside the predicate lists,
and [tlp_requester.sv:84-86](src/tlp/tlp_requester.sv#L84-L86) already documents it
("a command missing from its list was emitted as a well-formed Memory Read").

What M-1 changed is **reachability**: the fail-open was previously reachable only by an
illegal encoding, and is now reachable by a legal enum value. It remains inert solely
because nothing drives ordinal 8 or 9 — not because the requester would cope. That
warning is written at the declaration in
[tlp_pkg.sv:52-75](src/tlp/tlp_pkg.sv#L52-L75), not left to this document, because the
person who needs it will be reading the enum.

---

## §5 P6's two blind spots, demonstrated

The gate is the evidence for inertness. It is **not** evidence for the two width fixes in
§3.1, and this is the one place where "the tests are green" would have been a false
assurance.

`lint/waiver.vlt` waives `WIDTH`, `WIDTHEXPAND` **and** `WIDTHTRUNC`. With the enum
widened and a bench wire left at three bits, Verilator under this repo's own waiver:

```
$ verilator --lint-only --top-module tb_tlp_requester lint/waiver.vlt <files>
   -> exit 0, no %Warning, no %Error
```

Under `-Wall`, the same source:

```
%Warning-WIDTHEXPAND: tb_tlp_requester.sv:65:74: Input port connection 'command_i'
                      expects 4 bits on the pin connection, but pin connection's
                      VARREF 'command' generates 3 bits.
%Warning-WIDTHEXPAND: tb_pcie_rq_if.sv:77:8:    Output port connection 'command_o'
                      expects 4 bits on the pin connection, but pin connection's
                      VARREF 'command_o' generates 3 bits.
```

And because only ordinals 0–7 are ever driven, a silently truncated fourth bit would
**also** not have failed a test. Both channels — the linter and the regression — are
blind. The evidence for those two edits is the edit itself and the `-Wall` output above.

`-Wall` is not otherwise clean in this tree (pre-existing `WIDTHEXPAND` in
`tlp_pkg.sv:178-179`, unrelated to M-1), so the waiver is not gratuitous. But it does
hide this exact class, and any future width change must be checked by inspection or under
a targeted `-Wall`.

---

## §6 Incidental finding: line-range citations rot silently

Nine bench docstrings cite the enum by line range. **Four were already wrong before M-1
started:**

| citation | says | was already stale at `99b7501` |
|---|---|---|
| [test_tlp_cfg0_spine.py:12](tb/tlp/test_tlp_cfg0_spine.py#L12), [:24](tb/tlp/test_tlp_cfg0_spine.py#L24) | `tlp_pkg.sv:43-50` | **yes** |
| [test_tlp_conf_cfgbe.py:47](tb/tlp/test_tlp_conf_cfgbe.py#L47) | `tlp_pkg.sv:43-50` | **yes** |
| [test_tlp_conf_requester.py:28](tb/tlp/test_tlp_conf_requester.py#L28) | `tlp_pkg.sv:43-50` | **yes** |
| `test_pcie_rq_if.py:52`, `test_tlp_cfg1_spine.py:28,38`, `test_tlp_conf_cfg1.py:32,43` | `tlp_pkg.sv:43-52` | no — correct until now |

D-1b (`1c4056d`) appended the CFG1 pair and moved the close brace from 50 to 52, and did
not update the four that named the old range. Nobody noticed across two stages.

After M-1 the enum spans **43-76** and has **ten** members, so **all nine are now stale**,
and two of them additionally say "(8 members)".

**Deliberately not fixed here.** M-1's RTL commits are RTL-only by construction and a
`.py` docstring belongs to neither RTL nor docs; a comment-hygiene sweep is also not what
this brief authorises. The full site list is above so M-2 — which edits several of these
same bench files for the attr convention — can absorb it. The lesson is the one the
brief's §6 already applied to the new members: **cite a stable anchor, not a line
number.** The reserved-member comment names `RECON_MERGE.md` §R1 for that reason.

---

## §7 What M-1 does not establish

- **The reserved members have no decode path and no test.** §4 is a reading of the
  source; nothing in the 42/305 gate exercises ordinal 8 or 9, and no test can construct
  one. Their correctness is unmeasured, and §4 records that the requester would in fact
  handle them wrongly.
- **Nothing here was synthesized.** `SYNTH_FINDINGS_S1.md` and `SYNTH_FINDINGS_S2.md`
  describe a netlist that both RTL commits supersede. Their area and timing numbers are
  now **labels on a superseded netlist** and must not be quoted as current. M-1 does not
  re-measure them; the widening is one bit on a signal that is not in the reported
  critical path, but that is an expectation, not a measurement.
- **`origin/main`'s message behaviour remains unreviewed and unexecuted** — its
  requester rules, generator DW1/2/3 packing, parser decode and classifier POSTED arm.
  `RECON_MERGE.md` §4.1 found that `main` has not compiled since `8386c16`. M-1 reserves
  two encodings; it adopts, ports and validates nothing.
- **P1 identity is evidence of behavioural inertness at the 305 tests that exist**, not
  of coverage. Whatever those tests do not reach is equally unmeasured before and after.
- **The two width fixes are certified by inspection, not by the gate** (§5).

## §8 Are M-2 and M-3 unblocked as written?

**M-2 (attr) — unblocked, no amendment.** It is independent of the command encoding and
touches a disjoint set of RTL. Two carry-forwards from M-0 stand unchanged: `attr=0` and
`attr=7` are fixed points of the rotation and must not be used as the test value, and
`verilate_rq_if_tlp` / `verilate_rc_if_tlp` / `verilate_rq_rc_top` are the three
integration targets currently blind to the convention. **One addition:** M-2 edits
`test_tlp_conf_requester.py`, `test_tlp_conf_parser.py`, `test_tlp_parser.py` and
`enum_tb_common.py` for the attr golden helpers, and four of the nine stale citations in
§6 sit in those same files. Folding the citation fix into M-2 costs nothing.

**M-3 (the merge) — unblocked, and one step is now provably cheaper.** `tlp_pkg.sv` is no
longer a decision: this tree's `tlp_cmd_e` is already the union, so the resolution is
"take ours", tested and gated. What M-0 §5 listed as M-3 step 1 is done.

The other M-3 steps are untouched by M-1 and still required: the six `tlp_layer` /
`pcie_endpoint_top` port connections (`PINMISSING` is fatal under this waiver, so the
build fails without them), the attr convention flip, and `main`'s
`test_pcie_endpoint_line_rate.py:32-33` which binds `CMD_MSG=6`/`CMD_MSG_DATA=7` and must
move to 8/9 to match what this commit reserved.

**M-3a (re-verify what `main` contributes) — still required, and §4 sharpens why.** The
fail-open documented there is precisely what a message datapath has to fix, and it is not
something the merge will surface: it produces no warning, no error and no test failure.
