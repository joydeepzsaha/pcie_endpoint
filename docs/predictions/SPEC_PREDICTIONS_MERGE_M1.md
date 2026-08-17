# SPEC_PREDICTIONS_MERGE_M1 — widening `tlp_cmd_e` and reserving 8/9

Written and committed **before any RTL edit exists**, at `99b7501`, on `kourosh/dev`.
Every statement below is falsifiable and carries its observation method. A falsified
prediction is the useful outcome and will be recorded as such in `docs/findings/M1_FINDINGS.md`.

The change M-1 makes, in two commits:

1. `tlp_cmd_e`'s base type goes `logic [2:0]` → `logic [3:0]`. **Member set unchanged
   at eight.**
2. `TLP_CMD_MSG` and `TLP_CMD_MSG_DATA` are appended at ordinals **8** and **9**,
   declared and never decoded. Members 0–7 keep their ordinals and meanings.

---

## §0 The census these predictions rest on

Re-derived from the tree at `99b7501`, not copied from `docs/recon/RECON_MERGE.md` §R1.

### 0.1 Declaration and literal-width sites

One declaration: [tlp_pkg.sv:43](../../src/tlp/tlp_pkg.sv#L43) `typedef enum logic [2:0]`.

Twelve sites name the type and therefore widen automatically: ports at
[tlp_layer.sv:58](../../src/tlp/tlp_layer.sv#L58),
[tlp_requester.sv:17](../../src/tlp/tlp_requester.sv#L17),
[pcie_rq_if.sv:211](../../src/rc/pcie_rq_if.sv#L211),
[pcie_endpoint_top.sv:55](../../src/pcie_endpoint/pcie_endpoint_top.sv#L55); signals at
[pcie_rq_if.sv:255](../../src/rc/pcie_rq_if.sv#L255),
[pcie_rq_if.sv:380](../../src/rc/pcie_rq_if.sv#L380),
[pcie_rq_rc_top.sv:369](../../src/rc/pcie_rq_rc_top.sv#L369),
[tlp_requester.sv:55](../../src/tlp/tlp_requester.sv#L55),
[tb_pcie_rq_if_tlp.sv:84](../../tb/rc/tb_pcie_rq_if_tlp.sv#L84),
[tb_pcie_rc_if_tlp.sv:124](../../tb/rc/tb_pcie_rc_if_tlp.sv#L124),
[tb_pcie_endpoint_top.sv:39](../../tb/endpoint/tb_pcie_endpoint_top.sv#L39); plus six
function arguments at [tlp_requester.sv:82-114](../../src/tlp/tlp_requester.sv#L82-L114).

**⚠️ Two sites carry a command signal at a hard-coded width and are invisible to a
`tlp_cmd_e` grep — `docs/recon/RECON_MERGE.md` §R1 lists neither:**

| site | declaration | connected to |
|---|---|---|
| [tb/rc/tb_pcie_rq_if.sv:37](../../tb/rc/tb_pcie_rq_if.sv#L37) | `logic [2:0] command_o;` | `pcie_rq_if.command_o` (`tlp_cmd_e`), at [:77](../../tb/rc/tb_pcie_rq_if.sv#L77) |
| [tb/tlp/tb_tlp_requester.sv:11](../../tb/tlp/tb_tlp_requester.sv#L11) | `logic [2:0] command;` | `tlp_requester.command_i` (`tlp_cmd_e`), at [:65](../../tb/tlp/tb_tlp_requester.sv#L65) |

These are the complete set: every `.command_i(` / `.command_o(` port connection in the
tree was enumerated, and every connected signal's declaration resolved. Six signals
connect to a command port; four are `tlp_cmd_e`, these two are `logic [2:0]`.

No `$bits(tlp_cmd_e)`, no `tlp_cmd_e'(…)` cast from a literal-width expression, and no
bit-slice of any command signal exists anywhere in the tree.

### 0.2 Packed structs containing a `tlp_cmd_e` field

**None.** Every packed struct in `src/tlp/` and `src/rc/` was enumerated:

| struct | contains `tlp_cmd_e`? | note |
|---|---|---|
| [tlp_header_t](../../src/tlp/tlp_pkg.sv#L78) (`tlp_pkg.sv:78-101`) | **no** | carries `fmt[2:0]` + `tlp_type[4:0]`, wire fields — not a command |
| [rq_descriptor_t](../../src/rc/pcie_rq_rc_pkg.sv#L43) (`pcie_rq_rc_pkg.sv:43-55`) | **no** | carries `req_type` as `logic [3:0]` at `[78:75]`, cast to `rq_req_type_e` at [pcie_rq_if.sv:252](../../src/rc/pcie_rq_if.sv#L252) |
| [rc_descriptor_t](../../src/rc/pcie_rq_rc_pkg.sv#L117) (`pcie_rq_rc_pkg.sv:117-135`) | **no** | completion side; no command field |

`tlp_cmd_e` travels only as a standalone port or signal. It is never a struct member,
never flattened onto a bus, never stored, never compared as part of a wider aggregate.

### 0.3 `case` / `casez` / `unique case` selectors of type `tlp_cmd_e`

**None.** All 78 case statements in `src/` were enumerated and their selectors resolved.
The nearest miss is [pcie_rq_if.sv:263](../../src/rc/pcie_rq_if.sv#L263)
`unique case (desc_type)`, whose selector is `rq_req_type_e` (a separate 4-bit enum,
10 of 16 encodings named) **and which already has a `default` arm** at
[:277](../../src/rc/pcie_rq_if.sv#L277). Every other selector is an FSM state, a `tlp_type`,
a credit class, a `tkeep`, or an enum-scan outcome.

Command membership is tested exclusively by `==` chains inside the six
`command_is_*` functions, never by a case.

### 0.4 Python ordinals

37 constant definitions across 11 files bind ordinals 0–7. Highest bound ordinal is
**7** (`CMD_CFG_WRITE1`, in `test_pcie_rq_if.py:60`, `test_tlp_cfg1_spine.py:40`,
`test_tlp_conf_cfg1.py:46`). No Python constant binds 8 or 9. Because M-1 appends and
does not renumber, **no ordinal in 0–7 changes**.

---

## §1 P1 — the regression is byte-identical

**Claim.** The normalised run record is **identical**, byte for byte, across both RTL
commits: `docs/gates/M1_gate_before.txt` ≡ `docs/gates/M1_gate_widen.txt` ≡ `docs/gates/M1_gate_reserve.txt`.

**What is compared.** Per target, two record kinds:

```
T|<target>|<module>.<test name>|<STATUS>|<SIM TIME ns>      one row per test   (305 rows)
A|<target>|rc=<n>|TESTS=.. PASS=.. FAIL=.. SKIP=..|simend=<ns>   one per target ( 42 rows)
```

**347 rows total.** This is deliberately finer than the M-0 baseline, which recorded
only the 42 aggregates: a per-test row catches a change where two tests trade sim time
while the target total is unmoved. The M-0 baseline could not have seen that.

**Normalisation, and why.** Two columns of the cocotb summary table are dropped:
`REAL TIME (s)` and `RATIO (ns/s)`. Both are wall-clock and vary run to run on an
unloaded machine, let alone a loaded one. Nothing else is normalised — no timestamp
rewriting, no path munging — because nothing else in the compared rows contains a
timestamp or a path. Full logs are *not* compared: `build/` is deleted before each gate
and Verilator emits absolute paths into it, so full-log identity is unachievable and
would be the wrong target.

**Commands.** Each gate is a cold sequential sweep:

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate pcie
cd /home/kourosh/pcie_endpoint
rm -rf build/
# target list derived from the .core files, never transcribed:
TLP=$(grep -oE '^  verilate_[a-z0-9_]+:' tb/tlp/tb_tlp.core | tr -d ' :')
RC=$(grep -oE '^  verilate_[a-z0-9_]+:' tb/rc/tb_rc.core | tr -d ' :' \
     | grep -vE '^(verilate_enum_bar_trace|verilate_enum_bar_tlp_trace)$')
for t in $TLP; do fusesoc run --target=$t fusesoc:pcie:tb_tlp; done
for t in $RC;  do fusesoc run --target=$t fusesoc:pcie:tb_rc;  done
fusesoc run --target=verilate_conformance fusesoc:pcie:tb_ltssm_conformance
```

Row extraction from each target's stdout:

```bash
# per-test rows
awk '/^[[:space:]]*\*\*[[:space:]]+[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_]/ \
     { printf "T|%s|%s|%s|%s\n", TARGET, $2, $3, $4 }'
# aggregate row (last match wins)
awk '/TESTS=[0-9]+ PASS=[0-9]+ FAIL=[0-9]+ SKIP=[0-9]+/ \
     { for (i=1;i<=NF;i++) if ($i ~ /^TESTS=/) { c=i; break }
       printf "A|%s|rc=%s|%s %s %s %s|simend=%s\n", TARGET, RC, $c,$(c+1),$(c+2),$(c+3),$(c+4) }'
```

**The verdict command.**

```bash
diff docs/gates/M1_gate_before.txt docs/gates/M1_gate_widen.txt   && echo IDENTICAL
diff docs/gates/M1_gate_widen.txt  docs/gates/M1_gate_reserve.txt && echo IDENTICAL
```

**Falsified by:** any non-empty `diff`.

## §2 P2 — the sim-time invariants hold

**Claim.** `verilate_tlp_cpl_timeout_off` and `verilate_tlp_request_tracker` both end at
**580.00 ns**, to the ns, in all three gates.

**Observation.** `grep -E 'cpl_timeout_off|request_tracker' M1_gate_*.txt | grep '^A|'`.

**Falsified by:** either value moving off 580.00 in any gate. Subsumed by P1, but stated
separately because it is the invariant carried forward from
`docs/recon/RECON_MERGE_baseline.txt` and every prior stage, and it should be checkable without
running a diff.

## §3 P3 — per-struct width predictions

**Claim: no struct changes width, and no field moves — because no packed struct contains
a `tlp_cmd_e` field** (§0.2).

| struct | width before | width after | fields above the command field |
|---|---|---|---|
| `tlp_header_t` | unchanged | unchanged | n/a — no command field |
| `rq_descriptor_t` | 128 | 128 | n/a — `req_type` is `rq_req_type_e`, already `[3:0]` at `[78:75]`, untouched |
| `rc_descriptor_t` | unchanged | unchanged | n/a — no command field |

**Does any consumer index those bits by literal?** Yes — `rq_descriptor_t` and
`rc_descriptor_t` are flattened onto 128-bit AXIS descriptor words and indexed by
literal bit position in both RTL and the Python benches
([enum_tb_common.py:160,188](../../tb/rc/enum_tb_common.py#L160),
[:278,297](../../tb/rc/enum_tb_common.py#L278)). **This is exactly the hazard §8.3 names as a
stop trigger — and it does not fire, because the field those consumers index is
`req_type`, which is not `tlp_cmd_e` and does not widen.** The mapping from `req_type`
to `tlp_cmd_e` happens *inside* `pcie_rq_if` at [:263-277](../../src/rc/pcie_rq_if.sv#L263),
after the descriptor has been unpacked. The two encodings are decoupled by that case
statement, and M-1 touches neither side of it.

**Falsified by:** any change in a descriptor field's bit position, or any `$bits` of a
struct changing. Observable as a red descriptor test in `verilate_rq_if` /
`verilate_rc_if` / `verilate_enum_*`, which assert literal bit positions.

## §4 P4 — case completeness

**Claim: no case-completeness warning appears at any site, after either commit, because
no `case` selector in the tree is a `tlp_cmd_e`** (§0.3).

| selector | type | has `default`? | predicted warning after reserving 8/9 |
|---|---|---|---|
| `pcie_rq_if.sv:263` `desc_type` | `rq_req_type_e` | **yes**, `:277` | **none** — different enum, unaffected |
| all 77 others | FSM state / `tlp_type` / credit class / `tkeep` / outcome | — | **none** — no `tlp_cmd_e` selector exists |

**Predicted resolution required: none.** No `default` needs adding and no arm list needs
extending, at any site.

**Falsified by:** any `UNIQUE`/`CASEINCOMPLETE`/`CASEOVERLAP` diagnostic naming a site,
after either commit. Per §8.4 an unpredicted warning is a **stop**, not a patch: it
would mean the §0.3 census was incomplete and the correct response is a corrected
census.

## §5 P5 — classification functions on the reserved members

Neither reserved member is ever driven by anything in the tree, so these are statements
about what the code *would* compute, verified by reading the returning expression, not
by simulation.

**Claim: all six classification functions return `0` for both reserved members.**

| function | site | returns for `TLP_CMD_MSG` / `TLP_CMD_MSG_DATA` | where that `0` is produced |
|---|---|---|---|
| `command_is_config` | [tlp_requester.sv:82](../../src/tlp/tlp_requester.sv#L82) | **0** | 4-term `==` OR-chain, no term matches; `\|\|` of four false |
| `command_is_config1` | [:92](../../src/tlp/tlp_requester.sv#L92) | **0** | 2-term `==` OR-chain, neither matches |
| `command_is_io` | [:96](../../src/tlp/tlp_requester.sv#L96) | **0** | 2-term `==` OR-chain, neither matches |
| `command_is_config_or_io` | [:100](../../src/tlp/tlp_requester.sv#L100) | **0** | `0 \|\| 0` from the two above |
| `command_is_read` | [:104](../../src/tlp/tlp_requester.sv#L104) | **0** | 4-term `==` OR-chain, no term matches |
| `command_is_write` | [:109](../../src/tlp/tlp_requester.sv#L109) | **0** | 4-term `==` OR-chain, no term matches |

Each is an explicit member list, so an unlisted member yields `0` by construction — the
property [tlp_requester.sv:88-90](../../src/tlp/tlp_requester.sv#L88-L90) already relies on
deliberately ("deriving it from `command_r[0]` would tie correctness to the enum's
positional encoding").

**⚠️ Three derived outcomes are NOT `0`, and are predicted explicitly so the findings
cannot claim a clean sweep it did not earn:**

| derived signal | site | value for a reserved member | correct for a real message? |
|---|---|---|---|
| `command_has_data` | [:141](../../src/tlp/tlp_requester.sv#L141) `= command_is_write(command_r)` | **0** | wrong for `MSG_DATA` |
| `command_non_posted` | [:142](../../src/tlp/tlp_requester.sv#L142) `= command_r != TLP_CMD_MEM_WRITE` | **1** | **wrong — messages are posted** |
| `command_limit` | [:114](../../src/tlp/tlp_requester.sv#L114) | **`max_payload_bytes_i == 0 ? 128 : max_payload_bytes_i`** | incidental |
| `header_c.tlp_type` | [:152-159](../../src/tlp/tlp_requester.sv#L152-L159) | falls through to **`TLP_TYPE_MEM`** | **wrong — emits a well-formed Memory Read** |

That last row is the fail-open behaviour [tlp_requester.sv:84-86](../../src/tlp/tlp_requester.sv#L84-L86)
documents: *"a command missing from its list was emitted as a well-formed Memory Read."*

**This is pre-existing behaviour for an out-of-range command, not a defect M-1
introduces.** What M-1 changes is that the fail-open becomes reachable by a *legal enum
value* for the first time, rather than only by an illegal encoding. It stays inert
because nothing drives 8 or 9 and no test can construct them — but it is the first thing
M-3a must close when a message datapath lands. **Predicting it here is the point: the
reservation is inert, and it is inert only because the members are undriven, not because
the requester would handle them.**

**Falsified by:** any of the six returning non-zero, or any derived value differing from
the table, when read back in `docs/findings/M1_FINDINGS.md` against the post-change source.

## §6 P6 — the falsifier

**The single observation that would prove M-1 is not inert:**

> A non-empty `diff` between two consecutive gate files.

Any one differing row falsifies inertness. The row's shape names the cause without
further investigation:

- a **`T|` row differing in `SIM TIME`** → timing moved: the widening changed synthesis
  of a comparison or a mux, and the change is not free.
- a **`T|` row differing in `STATUS`** → a functional break.
- an **`A|` row differing in `rc=`** → a build or elaboration failure.
- an **`A|` row differing in `TESTS=`** → a test stopped being collected, most likely a
  Python constant or a bench signal silently changed meaning.
- **rows present in one file and absent in the other** → a target stopped running.

**Two additional falsifiers that are *not* visible in the diff**, recorded so they are
not mistaken for success:

1. **A silent width mismatch at either §0.1 raw-width site.** `lint/waiver.vlt` waives
   `WIDTH`, `WIDTHEXPAND` **and** `WIDTHTRUNC`. A 3-bit bench wire left on a 4-bit port
   would therefore produce **no diagnostic at all**, and — because only ordinals 0–7 are
   ever driven — **no test failure either**. The gate is structurally blind to it. It
   must be fixed by inspection in Commit 1, and `docs/findings/M1_FINDINGS.md` must state that the
   evidence for it is the edit, not the gate.
2. **A `PINMISSING` or elaboration error** would show as `rc≠0` in the `A|` row, which
   *is* in the diff — noted only to distinguish it from case 1.

---

## §7 What these predictions do not cover

- The reserved members have **no decode path and no test**. P5 is a reading of the
  source, not a simulation result; nothing in the 42/305 gate exercises ordinal 8 or 9.
- **Nothing here is synthesized.** The S-1/S-2 area and timing numbers
  (`docs/findings/SYNTH_FINDINGS_S1.md`, `docs/findings/SYNTH_FINDINGS_S2.md`) describe a netlist this change
  supersedes, and M-1 does not re-measure them.
- The message *behaviour* on `origin/main` — the requester rules, the generator's DW1/2/3
  packing, the parser's decode, the classifier's POSTED arm — remains **unreviewed and
  unexecuted**, exactly as `docs/recon/RECON_MERGE.md` §4.1 found. M-1 reserves two encodings; it
  does not adopt, port, or validate any of that.
- P1 identity is evidence of behavioural inertness at the 305 tests that exist. It is not
  evidence of coverage. Anything those tests do not reach is unmeasured before and after
  alike.
