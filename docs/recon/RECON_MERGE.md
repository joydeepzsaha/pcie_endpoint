# RECON_MERGE — what `origin/main` does to the RC

Stage M-0. Read-only recon at the anchors below. No merge, no rebase, no ref moved,
no `.sv` / `.py` / `.core` / script touched. Two verification steps ran **outside**
the repo, in a scratchpad, on blobs extracted with `git show` — the working tree was
verified clean before and after (§1.4).

---

## §1 Anchors and baseline

### 1.1 The five hashes

```
HEAD                  58ae5a7445c57922a1190e6744a34872fbed39f2
origin/kourosh/dev    58ae5a7445c57922a1190e6744a34872fbed39f2
origin/main           aca47806b115cc4c4e842814d949527473285a0c
origin/joy_dev        50fc5c7f44e98f217776337471101f4b5343bed0
merge-base(dev,main)  2de9afe3edc6e458799afadaf5c3a77456d6635d
```

`HEAD == origin/kourosh/dev` ✓. Working tree clean at start ✓ (`git status --porcelain`
empty). `git fetch origin` moved `origin/main` `7e57b68..aca4780` and `origin/joy_dev`
`97ef754..50fc5c7`.

The merge base `2de9afe` is the Stage D close (40/294). Commits on `main` since:

```
aca4780 merge fix1                                    <- origin/main
8386c16 Merge pull request #5 from joydeepzsaha/joy_dev
50fc5c7 Merge branch 'main' into joy_dev              <- origin/joy_dev
5bbe5ae pcie_gen1 dataflow tests for endpoint, ...
7e57b68 Merge pull request #4 from joydeepzsaha/kourosh/dev
```

`origin/joy_dev` is already contained in `origin/main` (via `8386c16`); it is not an
independent input to the merge. Only two branches are actually in play.

### 1.2 The measured baseline

**42 targets / 305 tests / 305 PASS / 0 FAIL / 0 SKIP — matches the expected figure.**

Cold: `rm -rf build/` (2.7 GB removed) before the first target. Sequential, one
`fusesoc run` per target. Full per-target census with the exact commands in
`docs/recon/RECON_MERGE_baseline.txt`.

The 42 is composed as `[stack-inventory / gearbox-contract]` records: 27 `verilate_*`
in `tb/tlp/tb_tlp.core`, plus 14 of the 16 in `tb/rc/tb_rc.core` (excluding
`verilate_enum_bar_trace` and `verilate_enum_bar_tlp_trace`, which
[tb_rc.core:397](../../tb/rc/tb_rc.core#L397) declares out of the gate), plus
`verilate_conformance` from `tb/ltssm_conformance/tb_ltssm_conformance.core`. Counting
all 16 RC targets gives 44, not 42 — the exclusion is load-bearing and is re-derived
mechanically by the sweep script, not asserted.

### 1.3 Sim-time invariant

| target | expected | measured |
|---|---|---|
| `verilate_tlp_cpl_timeout_off` | 580.00 ns | **580.00 ns** |
| `verilate_tlp_request_tracker` | 580.00 ns | **580.00 ns** |

Both hold to the ns.

### 1.4 Out-of-tree verification, and the clean-tree check

Two findings below (R1, R7) are elaboration claims about trees that are not checked
out. They were verified by extracting blobs with `git show <ref>:<path>` into
`$SCRATCH/`, and running `verilator --lint-only` there. Nothing was written into the
repo, no worktree was created, no merge was performed. `git status --porcelain` was
re-run after and is **empty** — the tree is clean.

---

## §2 Findings

### R1 — The `tlp_cmd_e` collision surface

#### 1. Member lists, in declaration order

Both branches declare `typedef enum logic [2:0]`, 8 members, positional (no explicit
values), so each member takes its ordinal.

| pos | `origin/kourosh/dev` [tlp_pkg.sv:43-52](../../src/tlp/tlp_pkg.sv#L43-L52) | `origin/main` `src/tlp/tlp_pkg.sv:49-58` |
|---|---|---|
| 0 | `TLP_CMD_MEM_READ` | `TLP_CMD_MEM_READ` |
| 1 | `TLP_CMD_MEM_WRITE` | `TLP_CMD_MEM_WRITE` |
| 2 | `TLP_CMD_CFG_READ0` | `TLP_CMD_CFG_READ0` |
| 3 | `TLP_CMD_CFG_WRITE0` | `TLP_CMD_CFG_WRITE0` |
| 4 | `TLP_CMD_IO_READ` | `TLP_CMD_IO_READ` |
| 5 | `TLP_CMD_IO_WRITE` | `TLP_CMD_IO_WRITE` |
| 6 | `TLP_CMD_CFG_READ1` | **`TLP_CMD_MSG`** |
| 7 | `TLP_CMD_CFG_WRITE1` | **`TLP_CMD_MSG_DATA`** |

Positions 0–5 are identical. Positions 6 and 7 collide. The union is **10 members**.

#### ⚠️ 1a. The brief's premise is wrong: `origin/main` does not elaborate

The brief frames R1 as a collision between two coherent 8-member sets. It is not.
**`origin/main`'s RTL references two enum members that `origin/main`'s own package does
not declare.**

`origin/main:src/tlp/tlp_requester.sv` lines 89-90, 99, 112, 117 and
`origin/main:src/rc/pcie_rq_if.sv` lines 262, 263, 275, 313 all name
`TLP_CMD_CFG_READ1` / `TLP_CMD_CFG_WRITE1`, which exist only on `kourosh/dev`:

```systemverilog
// origin/main:src/tlp/tlp_requester.sv:88-90
function automatic logic command_is_config(input tlp_cmd_e command);
  return command == TLP_CMD_CFG_READ0 || command == TLP_CMD_CFG_WRITE0 ||
         command == TLP_CMD_CFG_READ1 || command == TLP_CMD_CFG_WRITE1;
```

Verified by lint on the extracted blobs (§1.4):

```
%Error: tlp_requester.sv:90:23: Can't find definition of variable: 'TLP_CMD_CFG_READ1'
      : ... Suggested alternative: 'TLP_CMD_CFG_READ0'
%Error: tlp_requester.sv:90:55: Can't find definition of variable: 'TLP_CMD_CFG_WRITE1'
%Error: Exiting due to 2 error(s)
```
```
%Error: pcie_rq_if.sv:262:39: Can't find definition of variable: 'TLP_CMD_CFG_READ1'
%Error: pcie_rq_if.sv:263:39: Can't find definition of variable: 'TLP_CMD_CFG_WRITE1'
```

`tlp_requester.sv` is in `origin/main:src/tlp/tlp_core.core:17`, the fileset every TL
target depends on. **`origin/main` has no compiling Transaction Layer.** PR #5
(`8386c16`) took `joy_dev`'s `tlp_pkg.sv` — which had replaced CFG1 with MSG — while
keeping `kourosh/dev`'s CFG1-aware `tlp_requester.sv` and `pcie_rq_if.sv` from PR #4.
`aca4780` ("merge fix1") repaired the *admission logic* damage from that merge (R4) but
did not touch the package.

The practical consequence for M-1: there is no "main member set" to hold, because no
`main` test has ever run against one. The union is not a negotiation between two
working designs; it is dev's working set plus two members that only ever existed as a
broken half-merge.

#### 2. Declared width today, and at `logic [3:0]`

Declared width is **3 bits** on both branches, from the `logic [2:0]` in the typedef —
not inferred from the member count. Ten members need 4 bits. At `logic [3:0]` every
signal and port of type `tlp_cmd_e` widens 3→4 by declaration; no site declares the
width independently, so nothing goes stale silently.

#### 3. Ports and structs that change width

`tlp_cmd_e` is **not a member of any struct or packed type** in either tree — grep for
`tlp_cmd_e` inside a struct declaration returns nothing. It travels only as a
standalone port or signal. Twelve sites, of which **four cross a module boundary**:

| site | kind | crosses boundary |
|---|---|---|
| [tlp_layer.sv:58](../../src/tlp/tlp_layer.sv#L58) `command_i` | input port | **yes** |
| [tlp_requester.sv:17](../../src/tlp/tlp_requester.sv#L17) `command_i` | input port | **yes** |
| [pcie_rq_if.sv:211](../../src/rc/pcie_rq_if.sv#L211) `command_o` | output port | **yes** |
| [pcie_endpoint_top.sv:55](../../src/pcie_endpoint/pcie_endpoint_top.sv#L55) `command_i` | input port | **yes** |
| [pcie_rq_if.sv:255](../../src/rc/pcie_rq_if.sv#L255) `desc_cmd` | internal | no |
| [pcie_rq_if.sv:380](../../src/rc/pcie_rq_if.sv#L380) `cmd_r` | internal | no |
| [pcie_rq_rc_top.sv:369](../../src/rc/pcie_rq_rc_top.sv#L369) `command` | wire between the two above | **yes** (both ends widen together) |
| [tlp_requester.sv:55](../../src/tlp/tlp_requester.sv#L55) `command_r` | internal | no |
| [tb_pcie_rq_if_tlp.sv:84](../../tb/rc/tb_pcie_rq_if_tlp.sv#L84) `command` | bench wire | **yes** |
| [tb_pcie_rc_if_tlp.sv:124](../../tb/rc/tb_pcie_rc_if_tlp.sv#L124) `command` | bench wire | **yes** |
| [tb_pcie_endpoint_top.sv:39](../../tb/endpoint/tb_pcie_endpoint_top.sv#L39) `command_i` | bench wire | **yes** |
| [tlp_requester.sv:82-114](../../src/tlp/tlp_requester.sv#L82-L114) | 6 function args | no |

Because every one of these is spelled `tlp_cmd_e` and never `logic [2:0]`, the RTL side
of the widening is genuinely mechanical: one edit to the typedef.

#### 4. ⚠️ Positional dependence — the question that decides M-1

**Yes, extensively — but all of it is in Python, and none of it is in RTL.**

*RTL: clean.* No comparison against an integer literal, no cast, no bit-slice of a
command signal anywhere in either tree. `pcie_rq_if.sv:264-275` maps the 4-bit `RQ_*`
descriptor `req_type` to `tlp_cmd_e` through an explicit `case`, not arithmetic.
[tlp_requester.sv:88-90](../../src/tlp/tlp_requester.sv#L88-L90) even carries a comment
saying the choice was deliberate: *"deriving it from `command_r[0]` would tie
correctness to the enum's positional encoding."*

*Python: fully positional.* Every cocotb bench drives `command_i` with a raw integer.
**13 files** hardcode the ordinals:

| file | constants |
|---|---|
| [tb/rc/test_pcie_rq_if.py:53-60](../../tb/rc/test_pcie_rq_if.py#L53-L60) | all 8, `CMD_MEM_READ=0` … **`CMD_CFG_READ1=6`, `CMD_CFG_WRITE1=7`** |
| [tb/tlp/test_tlp_cfg1_spine.py:39-40](../../tb/tlp/test_tlp_cfg1_spine.py#L39-L40) | **`CMD_CFG_READ1=6`, `CMD_CFG_WRITE1=7`** |
| [tb/tlp/test_tlp_conf_cfg1.py:45-46](../../tb/tlp/test_tlp_conf_cfg1.py#L45-L46) | **`CMD_CFG_READ1=6`, `CMD_CFG_WRITE1=7`** |
| [tb/tlp/test_tlp_conf_requester.py:29-34](../../tb/tlp/test_tlp_conf_requester.py#L29-L34) | 0–5 |
| [tb/tlp/test_tlp_conf_cfgbe.py:48-52](../../tb/tlp/test_tlp_conf_cfgbe.py#L48-L52) | 1–5 |
| [tb/tlp/test_tlp_cfg0_spine.py:25-26](../../tb/tlp/test_tlp_cfg0_spine.py#L25-L26) | 2, 3 |
| [tb/tlp/test_tlp_conf_tracker.py:26](../../tb/tlp/test_tlp_conf_tracker.py#L26) | 0 |
| [tb/tlp/test_tlp_conf_datalast.py:33](../../tb/tlp/test_tlp_conf_datalast.py#L33) | 1 |
| [tb/tlp/test_tlp_credit_integration.py:17](../../tb/tlp/test_tlp_credit_integration.py#L17) | 0 |
| [tb/endpoint/test_pcie_endpoint_top.py:19-20](../../tb/endpoint/test_pcie_endpoint_top.py#L19-L20) | 0, 1 |
| [tb/tlp/test_tlp_end_to_end.py:6-11](../../tb/tlp/test_tlp_end_to_end.py#L6-L11) | 0–5 (orphan file, see §3) |
| `origin/main:tb/endpoint/test_pcie_endpoint_line_rate.py:32-33` | **`CMD_MSG=6`, `CMD_MSG_DATA=7`** |

The last row is the collision made concrete: `main` pins `CMD_MSG=6`/`CMD_MSG_DATA=7`
in Python, on exactly the two slots three `dev` bench files pin to CFG1.

**This decides the union ordering.** Appending `TLP_CMD_MSG=8`, `TLP_CMD_MSG_DATA=9`
after dev's 0–7 costs **two constants in one file that has never executed** (main's
line-rate bench cannot run — the TL it needs does not elaborate). Adopting main's
numbering and moving CFG1 to 8/9 costs **six constants across three files that are all
inside the green 42/305 gate**. The append-only rule and the cheaper repair agree.

---

### R2 — The `attributes` convention surface

#### The delta

Both branches are **internally self-consistent**: on each, generator∘parser is the
identity. They differ by a **one-bit rotation of the internal `attributes` field
relative to the wire**.

| | `dev` generator | `dev` parser | `main` generator | `main` parser |
|---|---|---|---|---|
| | [tlp_generator.sv:66,70](../../src/tlp/tlp_generator.sv#L66) | [tlp_parser.sv:125,146](../../src/tlp/tlp_parser.sv#L125) | `tlp_generator.sv:68,72` | `tlp_parser.sv:125,148` |
| dw0[10] | `attributes[0]` | → `attributes[0]` | `attributes[2]` | → `attributes[2]` |
| dw0[21:20] | `attributes[2:1]` | → `attributes[2:1]` | `attributes[1:0]` | → `attributes[1:0]` |

#### Which is right: `main`

PCIe Base 2.1 header byte order, mapped onto this little-endian 32-bit AXI word:
byte 1 = `dw0[15:8]`, so byte-1 bit 2 = `dw0[10]` = **Attr[2] (IDO)**; byte 2 =
`dw0[23:16]`, so byte-2 bits 5:4 = `dw0[21:20]` = **Attr[1:0] (RO, NS)**. The
surrounding fields corroborate the byte mapping unambiguously — `dw0[14:12]`=TC,
`dw0[17:16]`=Length[9:8], `dw0[19:18]`=AT, `dw0[22]`=EP, `dw0[23]`=TD all land where
the spec puts them.

So `main`'s `header.attributes[2:0]` **is** PCIe `Attr[2:0]`. `dev`'s field is a
left-rotate-by-one of it: `dev.attributes[0]` carries IDO. `main` adds a comment saying
exactly this. **The convention decision is settled by the spec, not by taste: `main` is
correct and `dev` is rotated.** Note this is a relabelling, not a wire-format change —
both branches emit the same bits for the same *spec* attr value only if the driver
rotates; today dev's `command_attr_i` semantics are rotated end-to-end.

#### Tests that would go red under `main`'s convention

**Exactly one target, one test.**

- **`verilate_tlp_generator`** — [test_tlp_generator.py:84](../../tb/tlp/test_tlp_generator.py#L84)
  drives `attr=5` and asserts against
  [`expected_dw0`:66-67](../../tb/tlp/test_tlp_generator.py#L66-L67), which encodes the dev
  convention `((attr&1)<<10) | (((attr>>1)&3)<<20)`. With `attr=5` (`3'b101`): dev's
  RTL and the bench both produce `dw0[21:20]=2'b10`; main's RTL produces `2'b01`. The
  assertion at [:89](../../tb/tlp/test_tlp_generator.py#L89) fails on DW0.

#### Tests that are structurally blind

Every other attr site. Three distinct reasons:

1. **Rotation-invariant path (no packing).** `verilate_rc_if` drives `attr=2`, `4` and
   `randrange(0,8)` ([test_pcie_rc_if.py:827,830,886](../../tb/rc/test_pcie_rc_if.py#L827)),
   but [tb_pcie_rc_if.sv:4](../../tb/rc/tb_pcie_rc_if.sv#L4) states *"No Transaction Layer in
   the loop"* and [:55](../../tb/rc/tb_pcie_rc_if.sv#L55) assigns
   `received_completion_header.attributes = hdr_attr_i` **directly as a struct field**.
   The value never crosses a parser. Same for `verilate_rq_if`
   ([test_pcie_rq_if.py:325,628,751,766,780](../../tb/rc/test_pcie_rq_if.py#L325)) — attr is
   an RQ-descriptor field at `[126:124]`, and
   [pcie_rq_if.sv:472](../../src/rc/pcie_rq_if.sv#L472) passes it through unmodified. And for
   `verilate_tlp_completion_gen`
   ([test_tlp_completion_control.py:34](../../tb/tlp/test_tlp_completion_control.py#L34),
   `request_attr=5`) — that DUT is `tlp_completion_generator` + `tlp_control`, no
   `tlp_generator`.

2. **⚠️ Real integration path, but driven with `attr=0`.** `verilate_rq_if_tlp`,
   `verilate_rc_if_tlp` and `verilate_rq_rc_top` each put a **real `tlp_layer`**
   (generator *and* parser) in the loop, and each hardcodes the **dev** convention in
   its own DW0 helper —
   [test_pcie_rq_if_tlp.py:65,68](../../tb/rc/test_pcie_rq_if_tlp.py#L65),
   [test_pcie_rc_if_tlp.py:111,113](../../tb/rc/test_pcie_rc_if_tlp.py#L111),
   [test_pcie_rq_rc_top.py:139,141](../../tb/rc/test_pcie_rq_rc_top.py#L139). **Every call
   site uses the default `attr=0`.** So three integration targets carry the wrong
   convention in their golden model and cannot detect it.

3. **Same for the TL conformance helpers** —
   [enum_tb_common.py:368,370](../../tb/rc/enum_tb_common.py#L368) (`cfg_wire_dw0`),
   [:423,425](../../tb/rc/enum_tb_common.py#L423) (`cpl_dw0`),
   [test_tlp_conf_requester.py:62,65](../../tb/tlp/test_tlp_conf_requester.py#L62),
   [test_tlp_conf_parser.py:43,47](../../tb/tlp/test_tlp_conf_parser.py#L43),
   [test_tlp_parser.py:10-11](../../tb/tlp/test_tlp_parser.py#L10-L11). All dev convention,
   all called with `attr=0` only.

#### Does the blind list contain an integration target? Yes — three

`verilate_rq_if_tlp`, `verilate_rc_if_tlp`, `verilate_rq_rc_top`.

**What a test that closed the blindness would have to drive.** In `verilate_rc_if_tlp`:
build a completion wire word with `cpl_dw0(has_data=True, length_dw=1, attr=A)`, push it
through the real `tlp_parser`, and assert the emitted RC descriptor's attr field
`[94:92]` equals `A`. In `verilate_rq_if_tlp`, the mirror: drive an RQ descriptor with
`attr=A` and assert the emitted DW0 carries `dw0[10]==A[2]` and `dw0[21:20]==A[1:0]`.

**⚠️ The trap:** `A=0` and `A=7` are **fixed points of the rotation** — `{A[2],A[1:0]}`
equals `{A[1:0],A[2]}` for both. A test written with `attr=7` would look like coverage
and prove nothing. Use `A ∈ {1,2,3,4,5,6}`; `A=5` is the strongest single value because
it differs in both moved positions. This is the same shape of vacuity as the
"advertise 0 to starve a pool" trap in [credit-manager-fc-model-gate].

---

### R3 — `tlp_layer` and `pcie_endpoint_top` port deltas

`main` adds **six** ports to `tlp_layer` (`git diff … -- src/tlp/tlp_layer.sv`):

| port | dir | width |
|---|---|---|
| `command_message_route_i` | **input** | `[2:0]` |
| `command_message_code_i` | **input** | `[7:0]` |
| `target_message_o` | output | 1 |
| `target_message_route_o` | output | `[2:0]` |
| `target_message_code_o` | output | `[7:0]` |
| `target_message_data_o` | output | `[63:0]` |

and the same six, verbatim, to `pcie_endpoint_top`.

#### `tlp_layer` — four instantiation sites, three leave all six unconnected

| site | connects the six? |
|---|---|
| `origin/main:src/pcie_endpoint/pcie_endpoint_top.sv:191` | **yes**, all six |
| `origin/main:src/rc/pcie_rq_rc_top.sv:461` | **no — none** |
| [tb/rc/tb_pcie_rq_if_tlp.sv:145](../../tb/rc/tb_pcie_rq_if_tlp.sv#L145) (identical on both branches) | **no — none** |
| [tb/rc/tb_pcie_rc_if_tlp.sv:202](../../tb/rc/tb_pcie_rc_if_tlp.sv#L202) (identical on both branches) | **no — none** |

`main` changed `pcie_rq_rc_top.sv` only in comments; its port list is byte-identical to
the base. The two RC benches `main` never touched at all.

**Separating inputs from outputs, and what an unconnected input reads as:** the four
`target_message_*` are **outputs** — omitting them is harmless in principle (the RC
does not consume messages). The two `command_message_*` are **inputs**; if the omission
were tolerated, Verilator's 2-state model would resolve them to `0` — which for
`command_message_route_i` is `MSG_TO_RC` and for `command_message_code_i` is code `00h`.
But:

#### ⚠️ It never gets that far — `PINMISSING` is fatal under this repo's own waivers

[lint/waiver.vlt](../../lint/waiver.vlt) waives `PINCONNECTEMPTY` (an explicitly empty
`.port()`) but **not `PINMISSING`** (a port omitted from the list). The `tlp`/`rc`
targets pass `waiver.vlt` with no `-Wno-fatal`. Measured on a two-module synthetic case
with this repo's actual waiver file:

```
%Warning-PINMISSING: m.sv:5:9: Instance has missing pin: 'b_i'
%Error: Exiting due to 1 warning(s)
verilator exit code = 1
```

So under `main`'s `tlp_layer`, **`verilate_rq_if_tlp`, `verilate_rc_if_tlp` and
`verilate_rq_rc_top` hard-fail the build** — a second, independent breakage stacked on
top of R1's undeclared enum members. Both must be fixed before *anything* in the RC
compiles. (`main`'s new line-rate core passes `--Wno-fatal`; the `tlp`/`rc` cores do
not.)

#### `pcie_endpoint_top` — two instantiation sites, both fine, and *why* they are

[src/pcie_endpoint/pcie_endpoint_top.sv:5](../../src/pcie_endpoint/pcie_endpoint_top.sv#L5)
is the module. Instantiations: `origin/main:tb/endpoint/tb_pcie_endpoint_top.sv:248`
and `origin/main:tb/endpoint/tb_pcie_endpoint_line_rate.sv:281`.

The reason the endpoint island survives the port addition and the RC island does not is
a **connection-style difference, not a diligence difference**:

```systemverilog
// origin/main:tb/endpoint/tb_pcie_endpoint_top.sv:248-253
) dut (
    .completion_request_header_i(completion_request_header_s),
    .target_request_header_o(target_request_header_s),
    .received_completion_header_o(received_completion_header_s),
    .*
);
```

`.*` connects every remaining port to a same-named signal in scope, so the six new ports
attach automatically — `main` declares matching signals at `:44-45` and `:64-67`. A
`.*` instantiation **cannot** raise `PINMISSING`.

The three RC sites use **explicit named connections** with no `.*` —
[tb_pcie_rq_if_tlp.sv:148ff](../../tb/rc/tb_pcie_rq_if_tlp.sv#L148),
[tb_pcie_rc_if_tlp.sv:202ff](../../tb/rc/tb_pcie_rc_if_tlp.sv#L202),
`origin/main:src/rc/pcie_rq_rc_top.sv:461ff`. Every added port must be listed by hand or
the build fails. **The endpoint island is internally consistent on `main` because of
`.*`; the RC island is not because it is explicit.** That also means the endpoint side
would have silently connected a *misnamed* port to nothing — the RC's explicitness is
the safer style and is being punished here only because `main` never built against it.

---

### R4 — Semantic deltas on the config path

#### `tlp_validator.sv` — every changed condition is gated by `message`, and `message` is disjoint from config

`main` adds `logic message = tlp_is_message(header_i.tlp_type)` and threads it through
five conditions. `tlp_is_message` is **new on `main`** (absent from dev's `tlp_pkg.sv`):

```systemverilog
// origin/main:src/tlp/tlp_pkg.sv:118-120
function automatic logic tlp_is_message(input logic [4:0] tlp_type);
  return tlp_type >= TLP_TYPE_MSG_TO_RC && tlp_type <= TLP_TYPE_MSG_GATHER;
endfunction
```

`TLP_TYPE_MSG_TO_RC = 5'b10000` … `TLP_TYPE_MSG_GATHER = 5'b10101`. Config types are
`TLP_TYPE_CFG0 = 5'b00100` and `TLP_TYPE_CFG1 = 5'b00101`. **Disjoint — no Type 0 or
Type 1 configuration request can reach any changed condition.**

| changed condition | reachable by CFG0/CFG1? | verdict for the config class |
|---|---|---|
| fmt/type legality `… \|\| completion \|\| message` | no | **unchanged** |
| new arm `message && !tlp_is_4dw(fmt)` | no | **unchanged** (and its insertion point is *after* the `(config_or_io \|\| completion) && tlp_is_4dw` arm, so it cannot shadow a config path) |
| `(!completion && !message && length_dw == 0)` | no | **unchanged** |
| new `(message && !has_data && length_dw != 0)` | no | **unchanged** |
| `!completion && !message && length_dw == 1 && last_be != 0` | no | **unchanged** |
| `!completion && !message && length_dw > 1 && (first_be==0 \|\| last_be==0)` | no | **unchanged** |
| **`(config_or_io && header_i.length_dw != 1)`** | **yes** | **UNTOUCHED — the one-DW rule survives verbatim at the validator** |

**No loosening for the config class at the validator.**

#### `tlp_classifier.sv` — one new arm, no config impact, one behaviour change for messages

`main` adds `message_request_o` and a case arm for the six `TLP_TYPE_MSG_*` types
setting `class_o = TLP_CLASS_POSTED`. Config arms are untouched. **Unchanged for
config.** But on `dev` those six types fell through to `default: unsupported_o = 1'b1`;
on `main` they classify as a legal posted request. **That is a loosening for messages**:
an RC that receives an unexpected message TLP no longer reports it unsupported. Not a
config-path issue, but it is a real change in UR behaviour and it merges cleanly.

#### `tlp_requester.sv` and `aca4780` — is the result internally consistent? **Yes**

`aca4780` is a hand-repair of damage `8386c16` (PR #5) did. What PR #5 had left:

- **A duplicated `always_comb` assignment pair.** `command_has_data` and
  `command_non_posted` were each assigned twice in the same block, the second
  overwriting the first. `aca4780` deletes the second pair.
- **A dangling predicate.** Two `if (…)` statements in `REQ_IDLE`, the first with no
  body — the message-rule `if` opened, then the config/IO comment block, then a second
  `if` carrying the `begin`. `aca4780` fuses them into one condition.

Post-repair state, `origin/main:src/tlp/tlp_requester.sv:147-152` and `:254-263`:

```systemverilog
always_comb begin
  command_has_data   = command_is_write(command_r) ||
                       command_r == TLP_CMD_MSG_DATA;
  command_is_message = command_r == TLP_CMD_MSG || command_r == TLP_CMD_MSG_DATA;
  command_posted     = command_r == TLP_CMD_MEM_WRITE || command_is_message;
  command_non_posted = !command_posted;
```

**Internally consistent: no duplicated assignment, no unreachable arm, no dangling
predicate.** And it is a strict superset of dev's semantics — dev has
`command_has_data = command_is_write(command_r)` and
`command_non_posted = command_r != TLP_CMD_MEM_WRITE`; with no message commands in
existence, `!(MEM_WRITE || message) ≡ !MEM_WRITE`. **Behaviour-preserving for every
command the RC can generate.**

#### The A.3 contract survives on `origin/main` — verbatim

```systemverilog
// origin/main:src/tlp/tlp_requester.sv:262-263
(command_is_config_or_io(command_i) &&
 command_byte_count_i > (13'd4 - {11'd0, command_address_i[1:0]}))
```

Identical to dev. The rule is on the fit-inside-the-addressed-DW quantity, not on the
byte enables, exactly as `[post-merge-tl-baseline]` recorded, and the ten-line comment
justifying it (Base 2.1 §2.2.7 p.79) is preserved. **The contract survives — but only
textually: `command_is_config_or_io` → `command_is_config` → `TLP_CMD_CFG_READ1`, which
`main` does not declare (R1). The guard is correct and uncompilable at the same time.**

#### ⚠️ Beyond the brief's three files: `pcie_config_mux.sv` is also on the config path

The brief scopes R4 to validator/classifier/requester. `src/pcie_cfg/pcie_config_mux.sv`
(67 lines changed, merges cleanly) is also a config-path module and changes meaning.

The routing predicate, base/dev → main:

```systemverilog
-  if (1 & tlp_dw0.byte0.Type inside {IORd, CfgRd0, TCfgRd,MsgD,IOWr, CfgWr0,TCfgWr})
+  if (tlp_dw0.byte0 inside {CfgRd0, CfgWr0})
```

[pcie_tlp_pkg.sv:5-8](../../src/packages/pcie_tlp_pkg.sv#L5-L8) declares `byte0` as
`{Fmt[7:5], Type[4:0]}`, so `byte0.Type` is **5 bits**, while
[pcie_datalink_pkg.sv:83-105](../../src/packages/pcie_datalink_pkg.sv#L83-L105) declares the
constants as **8 bits**. The old comparison zero-extends the 5-bit field to 8, so:

| constant | value | matched a 5-bit `Type`? |
|---|---|---|
| `IORd` = `8'b0000_0010` | 2 | yes → routed IO **read and write** (Type is shared) |
| `CfgRd0` = `8'b0000_0100` | 4 | yes → routed CFG0 **read and write** |
| `TCfgRd` = `8'b0001_1011` | 27 | yes → routed TCfg r/w |
| `IOWr` = `8'b0100_0010` | 0x42 | **never** — dead list entry |
| `CfgWr0` = `8'b0100_0100` | 0x44 | **never** — dead list entry |
| `TCfgWr` = `8'b0101_1011` | 0x5B | **never** — dead list entry |
| `MsgD` = `8'b0111_0???` | ≥0x70 | **never** — dead list entry |

So the old seven-member list was effectively `Type ∈ {IO, CFG0, TCfg}`, with four
entries unreachable and the leading `1 &` a no-op. The `WIDTH` waiver in
`lint/waiver.vlt` is why this never surfaced.

Per class:

- **CFG0 read/write** — routed before and after. `main` now matches the **full 8-bit
  `byte0`**, so Fmt is checked too: a CFG0 with a wrong Fmt no longer routes. **Tightened,
  correctly.**
- **IO read/write** — **no longer reaches the config handler. Tightened.**
- **TCfgRd/TCfgWr** — no longer routed. **Tightened** (deprecated types).
- **MsgD** — never routed on either branch; the list entry was always dead. **Unchanged.**
- **CFG1 (Type 1)** — routed on **neither** branch. **Unchanged**, and correct for an
  endpoint, which must UR a Type 1 config request.

Second change, and this one is a **loosening**: `main` adds `cfg_beat_sent_r` /
`tlp_beat_sent_r` so a CFG0 request is delivered to **both** the config handler *and*
the TLL target interface with independently tracked handshakes. On dev,
`tlp_axis_tvalid` was commented out on the config arm — the TLP never reached the target
port. **A new consumer now sees CFG0 traffic.** The dev code also asserted
`skid_axis_tready = tlp_axis_tready && cfg_axis_tready` in `ST_IDLE` before knowing
which arm it would take; `main` computes readiness per arm. That is a genuine
backpressure fix.

---

### R5 — The DLL delta against the §20 credit rebuild

#### `tlp2dllp.sv`: **orthogonal** to the credit rebuild — different module, different layer, different defect

The credit rebuild (`6a8c9de` / `140f250` / `33ba088`) rebuilt
`src/tlp/tlp_credit_manager.sv`, whose defect was that the TX side read cumulative
`CREDITS_ALLOCATED` as a remainder. `tlp2dllp.sv` is in `src/dllp/` and keeps its **own**
`*_credit_limit_r` / `*_credits_consumed_r` pair, already gating on
`limit - consumed >= 1` — i.e. it already had the correct two-register model. The
rebuild never touched it and this change never touches the rebuild. **No overlap, no
contradiction.**

Worth recording nonetheless: **the stack carries two independent credit accountings** —
`tlp_credit_manager` inside `tlp_layer`, and `tlp2dllp`'s internal counters in the DLL.
Nothing reconciles them.

What `main` actually fixed is an **AXIS handshake bug**, and the credit move is its
consequence. The old `ST_CHECK_CREDITS_*` arms did this:

```systemverilog
if ((nph_credit_limit_r - nph_credits_consumed_r) >= 1'b1) begin
  nph_credits_consumed_c = nph_credits_consumed_r + 1'b1;   // consume on the CHECK
  has_nph_credit         = '1;
end
if (has_nph_credit) begin
  tlp_axis_tvalid  = skid_axis_tvalid;
  skid_axis_tready = '1;                 // dequeue unconditionally
  next_state       = ST_TLP_STREAM;      // advance unconditionally
end
```

`tlp_axis_tready` is **not consulted**. The input is dequeued and the FSM advances even
if the downstream did not accept the beat — the beat is dropped. `main` wraps all of it
in `if (initial_axis_tvalid && tlp_axis_tready)` and makes
`skid_axis_tready = !prefix_r && tlp_axis_tready`. Credit then lands once per
*transmitted* TLP instead of once per cycle spent in the check state. Same direction of
travel as the §20 rebuild — count against the right event — but an independent defect.

`ST_PREFIX` is additive: a new state plus `prefix_r` and the `initial_axis_*` mux, so a
`TLP_PREFIX` DW is held while credit classification uses the *following* DW0. It does
not alter any existing credit arithmetic.

#### `dllp2tlp.sv`: **zero changed lines are reachable from anything the RC instantiates**

`git grep` for `tlp2dllp|dllp2tlp|pcie_datalink` across `src/rc/` and `tb/rc/` returns
**nothing**. The only instantiations in either tree are
[dllp_transmit.sv:163](../../src/dllp/dllp_transmit.sv#L163) (`tlp2dllp`) and
[dllp_receive.sv:246](../../src/dllp/dllp_receive.sv#L246) (`dllp2tlp`), reachable only
through the DLL/EP island. **All 488 changed lines in `dllp2tlp.sv`, and all 208 in
`tlp2dllp.sv`, are EP-only.** This confirms the three-disjoint-islands picture in
[stack-integration-recon] at the current anchors.

Scope note on `dllp2tlp.sv`: 172 added / 316 removed. `main` **deletes three FSM
states** that exist at the merge base — `ST_CHECK_TLP_TYPE`, `ST_TLP_LAST`,
`ST_DRAIN_LCRC` — together with the comments documenting why they existed (e.g. *"buffer
makes ST_IDLE interpret it as a new two-byte truncated TLP"*). That is a rewrite, not a
patch, and it discards recorded reasoning. It is out of the RC's path today, so it costs
the RC nothing to take — but it should not be taken as *reviewed* merely because it
merges.

#### The two standing facts, tested not assumed

- **Completion credit infinite; NPH may be one unit.** `tlp2dllp` encodes the infinite
  case explicitly: `if ((cplh_credit_limit_r == '0) || …)` — a zero cumulative limit is
  treated as unlimited, on both branches, unchanged by `main`. The NPH arm has no such
  clause, so a one-unit NPH advertisement does gate to one outstanding non-posted
  request. **Both hold.**
- **A long credit stall fabricates a completion timeout.** Unchanged and still true —
  `main` touches neither `tlp_request_tracker` nor the tag-allocation point, and
  [cpl-timeout-contract]'s finding stands. `main`'s handshake fix makes the stall
  *longer-lived* (the FSM now waits for `tlp_axis_tready` instead of dropping the beat),
  which if anything **widens** the window in which that fabrication can occur.

---

### R6 — Build-relevance census of `main`'s additions

23 paths are added on `origin/main` relative to both `origin/kourosh/dev` and the merge
base (identical lists — `main` has added nothing that dev also added).

#### Build-relevant — 5 paths, all in one new target pair

| path | target(s) |
|---|---|
| `tb/endpoint/tb_pcie_endpoint_line_rate.core` | defines `fusesoc:pcie:tb_endpoint_line_rate:1.0.0` |
| `tb/endpoint/pcie_gen1_logical_phy_model.sv` | `sim_x1`, `sim_x4` (fileset `tb`) |
| `tb/endpoint/tb_pcie_endpoint_line_rate.sv` | `sim_x1`, `sim_x4` (toplevel) |
| `tb/endpoint/pcie_gen1_traffic.py` | `sim_x1`, `sim_x4` (`copyto`) |
| `tb/endpoint/test_pcie_endpoint_line_rate.py` | `sim_x1`, `sim_x4` (`cocotb_module`) |

New external dependency: `cocotbext.pcie`. **It is present in the `pcie` env** —
`from cocotbext.pcie.core.dllp import Dllp, DllpType` imports cleanly. So the target is
runnable dependency-wise, though not enum-wise (R1).

#### Inert — 18 paths, no FuseSoC target compiles or imports them

- `src/model/` — 9 Python files + README. **No `.core` in either tree references it.**
  `test_pcie_endpoint_line_rate.py` imports `cocotbext.pcie` and the local
  `pcie_gen1_traffic`, **not** `src/model`. Confirmed by reading its import block.
- `tb/model/` — 4 test files + README. These are plain `unittest` modules that do
  `sys.path.insert(0, REPO_ROOT/"src")` then `from model import …`. A real, separately
  runnable suite, but **no FuseSoC target runs them** and nothing in the 42-target gate
  touches them.
- `src/scrambler/README.md`, `tb/endpoint/README_LINE_RATE.md`, `src/model/README.md`,
  `tb/model/README.md` — docs.
- `pcie_endpoint.txt` — a 207,990-byte root-level artifact, referenced by nothing.

#### One modified `.core` worth flagging

`tb/endpoint/tb_pcie_endpoint_top.core` gains `- fusesoc:pcie:phy_scrambler:1.0.0`.
That core name exists on dev already
([scrambler.core:2](../../src/scrambler/scrambler.core#L2)), and `main` adds
`encode_8b10b.sv` / `decode_8b10b.sv` to its fileset — **both files already exist on
dev** in `src/scrambler/`. So this dependency resolves cleanly post-merge.

---

### R7 — The two conflict sets

Computed with the form the brief specifies (git 2.27 supports only the legacy
signature; `--write-tree` needs 2.38+):

```bash
git merge-tree $(git merge-base origin/kourosh/dev origin/main) \
               origin/kourosh/dev origin/main
```

No worktree was created, no merge was started, nothing was written into the repo.
`git status --porcelain` after: **empty**.

#### The textual conflict set is EMPTY

```
  78  removed in remote
  31  merged
  23  added in remote
   0  changed in both
   0  conflict markers  (grep -c '<<<<<<<' → 0)
```

**Zero conflicted paths.** The reason is that the two branches touched **disjoint
files**:

- `dev` changed **25** paths since `2de9afe` — all of `src/rc/*` (9 files),
  `src/tlp/tlp_vc_buffer.sv`, the four VC-buffer bench/core files, and docs/synth
  scripts.
- `main` changed **132** paths since `2de9afe` — `src/tlp/tlp_{pkg,requester,generator,
  parser,classifier,validator,layer}.sv`, `src/dllp/*`, `src/pcie_cfg/*`,
  `src/pcie_endpoint/*`, `tb/endpoint/*`, `tb/tlp/*`.
- `git diff --name-only 2de9afe origin/main -- src/rc/` is **empty** — `main` has not
  touched a single RC file since the base.

Cross-check on the `merge-tree` parse: `78 removed + 23 added + 31 merged = 132`, which
is exactly `git diff --name-only 2de9afe origin/main | wc -l`. Every path `main` touched
is accounted for in one of the three buckets, and none of them is a conflict.

The intersection of the two change sets is **∅**. Git therefore has nothing to resolve.

`main` also deletes 78 tracked build artifacts (`csrc/*` VCS output, `obj_dir/*`
Verilator output) — a genuine hygiene improvement it brings for free.

#### The semantic set — files that merge cleanly and change meaning

All 31 "merged" paths land without a marker. The load-bearing ones, fed by R1–R5:

| path | what silently changes |
|---|---|
| `src/tlp/tlp_pkg.sv` | **enum members 6/7 swap CFG1 → MSG** (R1) |
| `src/tlp/tlp_requester.sv` | message admission rules; references undeclared members (R1, R4) |
| `src/tlp/tlp_generator.sv` | **attr rotation** + message DW1/DW2/DW3 packing (R2) |
| `src/tlp/tlp_parser.sv` | **attr rotation** + message header decode (R2) |
| `src/tlp/tlp_layer.sv` | +6 ports; message class routing (R3) |
| `src/tlp/tlp_validator.sv` | message-gated loosenings; config path unchanged (R4) |
| `src/tlp/tlp_classifier.sv` | messages POSTED instead of unsupported (R4) |
| `src/pcie_cfg/pcie_config_mux.sv` | **config routing narrowed; CFG0 gains a second consumer** (R4) |
| `src/dllp/tlp2dllp.sv` | credit on handshake, not check; `ST_PREFIX` (R5) |
| `src/dllp/dllp2tlp.sv` | three FSM states deleted (R5) |
| `src/pcie_endpoint/pcie_endpoint_top.sv` | +6 ports (R3) |
| `tb/tlp/test_tlp_generator.py` | dev's attr golden survives → **goes red** (R2) |
| `tb/tlp/test_tlp_credit_manager.py` | helper hoist repaired by `aca4780` |

#### ⚠️ The two sets are disjoint

**The textual conflict set and the semantic set are disjoint — in those words.** The
textual set is empty; the semantic set has thirteen entries. Every single behavioural
change in this merge arrives without a conflict marker.

#### Proof that the clean merge produces a tree that does not elaborate

Because the change sets are disjoint, the merge result for each file is exactly one
side's version — no resolution, no judgement. So the outcome is computable without
merging. Taking `origin/main:src/tlp/tlp_pkg.sv` (main-only change) together with
`origin/main:src/tlp/tlp_requester.sv` (main-only change) and
`origin/kourosh/dev:src/rc/pcie_rq_if.sv` (dev-only change), linted in the scratchpad:

```
### tlp_requester (merge result) ###
%Error: tlp_requester.sv:90:23: Can't find definition of variable: 'TLP_CMD_CFG_READ1'
%Error: tlp_requester.sv:90:55: Can't find definition of variable: 'TLP_CMD_CFG_WRITE1'
### pcie_rq_if (merge result) ###
%Error: pcie_rq_if.sv:274:39: Can't find definition of variable: 'TLP_CMD_CFG_READ1'
%Error: pcie_rq_if.sv:275:39: Can't find definition of variable: 'TLP_CMD_CFG_WRITE1'
```

**A conflict-free merge yields a tree that fails to elaborate in two files, plus three
`PINMISSING` build failures from R3.** This is the merge hazard in its strongest form:
git reports total success and nothing compiles.

---

### R8 — Hygiene census at `origin/main`

```bash
git ls-tree -r -l origin/main | awk '$4>1048576 {printf "%12d  %s\n", $4, $5}' | sort -rn
git ls-tree -r -l origin/main | awk '{s+=$4} END {print s}'
du -sh .git
```

- **35 tracked files over 1 MB**, totalling ~330 MB.
- **Total tracked content at `origin/main`: 475,964,440 bytes = 453.9 MB.**
- **`.git`: 1000 MB.**

Top of the list:

| bytes | path |
|---|---|
| 49,480,808 | `tb/vivado_sim/pcie_7x_0_ex/…/xsim.dir/board_behav/obj/xsim.lnx64.a` |
| 43,344,202 | `tb/openPCIe_Sim/…/xsim.dir/board_behav/obj/xsim.lnx64.a` |
| 35,742,448 | `tb/vivado_sim/pcie_7x_0_ex/…/xsim.dir/board_behav/xsimk` |
| 34,830,514 | `tb/openPCIe_Sim/…/xsim.dir/board_behav/xsim.reloc` |
| 31,599,048 | `tb/openPCIe_Sim/…/xsim.dir/board_behav/xsimk` |
| 27,643,513 | `tb/vivado_sim/pcie_7x_0_ex/…/xsim.dir/board_behav/xsim.reloc` |
| 17,593,398 | `tb/openPCIe_Sim/…/behav/xsim/board_behav.wdb` |
| 13,522,388 | `tb/vivado_sim/…/xsim.dir/board_behav/xsim.mem` |
| 12,246,981 | `tb/openPCIe_Sim/…/xsim.dir/board_behav/xsim.mem` |
| 8,088,155 | `src/xilinx_primitives/src/XilinxCoreLib/pci_exp_4_lane_64b_dsport.v` |

(Remaining 25 in the same two `xsim.dir` trees, `ILA_analyser_output/*.csv`, `simv`,
and Xilinx primitive sources.)

**Newly tracked by `main` vs already shared history:** **all 35 are shared history** —
not one appears in `main`'s 23-path addition list. `main` adds **zero** files over 1 MB;
its largest addition is `pcie_endpoint.txt` at 207,990 bytes. `main` in fact *removes*
78 tracked build artifacts (§R7).

So the 1 GB `.git` is entirely a pre-existing inheritance, unchanged in character by
this merge. No deletions performed here — and as the brief notes, the history purge is
free only at the repo migration.

---

## §3 Doc-vs-code disagreements

1. **This brief, §4/R1 — "hold both member sets."** There is no coherent `main` member
   set to hold. `main` references `TLP_CMD_CFG_READ1`/`TLP_CMD_CFG_WRITE1` without
   declaring them; its TL does not elaborate (R1a). The union is dev's working set plus
   two members that never compiled.

2. **This brief, §4/R2 — "`origin/main`'s convention."** Framed as a convention choice.
   It is a spec question with a determinate answer: `main` is correct, `dev` is rotated
   by one bit (R2). Both branches are internally self-consistent, so neither is "broken"
   — but only one is spec-labelled.

3. **This brief, §5/M-2 — "a non-zero-attr integration test … so that it goes red on the
   merge."** Correct in intent, but `attr=0` and `attr=7` are fixed points of the
   rotation; a test using 7 would be vacuous (R2).

4. **This brief, §4/R5 — "`tlp2dllp.sv` moves credit consumption from the credit check
   to the completed handshake."** Accurate, but incomplete: the change that *forced* it
   is an AXIS handshake bug — the old `ST_CHECK_CREDITS_*` arms never consulted
   `tlp_axis_tready` and dropped beats (R5).

5. **This brief, §6 stop trigger 1 — "The cold baseline is not 42 targets / 305 tests."**
   The baseline measured exactly 42/305, all PASS, both sim times 580.00 ns. Not a
   disagreement — recording that the one stop trigger with a numeric threshold did
   **not** fire.

6. **`origin/main:src/rc/pcie_rq_rc_top.sv:28`** — cites `(tlp_layer.sv:249,
   tlp_credit_manager.sv:53-54, 66-83.)` for the flow-control gate. On `main`,
   `tlp_layer.sv:249` is `(parsed_config && !target_config_hit_o)`. The gate is at
   `main`'s `tlp_layer.sv:290`. **The citation is wrong on `main`.** Dev's equivalent,
   [pcie_rq_rc_top.sv:40](../../src/rc/pcie_rq_rc_top.sv#L40), cites `tlp_layer.sv:280` and is
   **right** — [tlp_layer.sv:280](../../src/tlp/tlp_layer.sv#L280) is exactly
   `vc_packet_ready = credit_request_ready && transmit_enable_i && link_up_i`.

7. **`origin/main:src/rc/pcie_rq_rc_top.sv:47`** — the same commit renumbered the
   citation above but left this one citing `link_up_i (tlp_layer.sv:280)`. On `main`,
   `:280` is inside an `always_ff` reset block. **Also wrong, and inconsistent with the
   citation 19 lines above it** — one was updated, the other was not. Both are correct
   on `dev`. `main`'s edit broke working references.

8. **`origin/main:src/rc/pcie_rq_rc_top.sv`** deletes the entire `SPEC ANCHORS` block
   (PG213 v1.3 Table 60/61/65, PCIe Base 2.1 §2.6) that dev's version carries from
   [:16](../../src/rc/pcie_rq_rc_top.sv#L16). Pure doc regression in a file `main` otherwise
   did not functionally change at all — its port list and logic are byte-identical to
   the base (R3).

9. **[tb/tlp/test_tlp_end_to_end.py](../../tb/tlp/test_tlp_end_to_end.py) is an orphan.**
   `grep end_to_end tb/tlp/tb_tlp.core tb/rc/tb_rc.core` returns nothing on either
   branch. It has the most thorough attr coverage in the tree —
   [:275](../../tb/tlp/test_tlp_end_to_end.py#L275) sweeps `attr=(number ^ 3) & 7` and
   [:283](../../tb/tlp/test_tlp_end_to_end.py#L283) asserts the decode — **and none of it
   runs.** `main` modifies this file (75 lines) as though it were live.

10. **`lint/waiver.vlt` does not waive `PINMISSING`** although it waives
    `PINCONNECTEMPTY`. Nothing states this; the consequence (R3) is that omitting a port
    is a build failure while explicitly emptying it is fine — the opposite of the
    intuition that the empty connection is the sloppier one.

11. **The `1 &` in the base/dev `pcie_config_mux.sv` routing predicate is dead**, and
    four of the seven constants in its list could never match (R4). The code reads as a
    seven-way classifier; it is a three-way one.

12. **`[stack-inventory-c2a]`'s note that `docs/spec-notes/STACK_INVENTORY.md` claims "27/151 not 152"**
    remains uncorrected in the tree at this anchor. Unrelated to the merge, restated so
    it is not re-derived a third time.

---

## §4 Ranked surprises, by consequence to the RC

1. **`origin/main` does not elaborate.** Its TL references two undeclared enum members
   (R1a). This is not a merge risk — it is a defect already on `main`, and it means the
   entire `main` TL/RC test surface has been unverifiable since `8386c16`. Everything
   `main` contributes (messages, attr fix, DLL handshake fix) is **unreviewed by
   execution**.

2. **A conflict-free merge produces a non-elaborating tree** (R7). Zero conflict
   markers, two undeclared-identifier errors, three `PINMISSING` build failures. The
   textual and semantic sets are disjoint. Any future session that runs the merge and
   sees "0 conflicts" will draw exactly the wrong conclusion.

3. **The `tlp_cmd_e` union is decided by Python, not RTL** (R1.4). RTL is positionally
   clean; 13 bench files hardcode ordinals, including three in the green gate that pin
   CFG1=6/7 and one on `main` that pins MSG=6/7. Appending MSG at 8/9 costs two
   constants in a file that has never run; adopting `main`'s numbering costs six
   constants inside the 42/305 gate.

4. **Three integration targets carry the wrong attr convention in their golden model and
   cannot detect it** (R2). `verilate_rq_if_tlp`, `verilate_rc_if_tlp`,
   `verilate_rq_rc_top` all put a real `tlp_layer` in the loop, all hardcode dev's
   rotation, all call with `attr=0`. Only `verilate_tlp_generator` goes red — the
   integration layer is silent, which is exactly backwards from what the gate should do.

5. **`PINMISSING` is fatal, so `main`'s six new `tlp_layer` ports break three RC targets
   independently of the enum** (R3). Two must-fix items, not one, before anything
   compiles.

6. **`pcie_config_mux.sv` changes the config path and is not in the brief's R4 scope**
   (R4). IO and TCfg lose their route to the config handler; CFG0 gains a second
   consumer at the TLL target interface. Merges cleanly, changes meaning, and would have
   gone unexamined.

7. **The stack carries two unreconciled credit accountings** (R5) — `tlp_credit_manager`
   in the TL and `tlp2dllp`'s internal counters in the DLL. The §20 rebuild fixed one;
   `main` fixes a different defect in the other. Neither knows about the other.

8. **`main`'s DLL rewrite deletes three documented FSM states** (R5). Out of the RC's
   path, so free to take — but it is a rewrite, not a patch, and merging it is not
   reviewing it.

9. **`test_tlp_end_to_end.py` has the tree's best attr coverage and runs in no target**
   (§3.9). Wiring it up is the cheapest coverage available for R2.

10. **`main` brings free hygiene**: 78 tracked build artifacts deleted, zero new files
    over 1 MB (R7, R8). The only genuinely good news in this merge.

---

## §5 Proposed merge ladder

The brief's hypothesis is **structurally right but mis-scoped at M-1 and under-scoped at
M-3**. The correction: M-1 cannot be "widen the enum holding both member sets", because
`main`'s set does not exist in compilable form; and M-3 must land the `tlp_layer` port
wiring as a *precondition* of the merge compiling at all, not as one of three parallel
concerns. Revised:

### M-1 — Widen `tlp_cmd_e` to `logic [3:0]`, appending MSG at 8/9

On `kourosh/dev` alone. Final member order: dev's 0–7 unchanged, then
`TLP_CMD_MSG = 8`, `TLP_CMD_MSG_DATA = 9`.

*Ordering argument.* This is first because it is the only rung that changes a wire
format, and it must be provably behaviour-neutral before anything else moves.
Appending honours the `tlp_pkg` append-only rule; preserving 0–7 keeps all six
in-gate Python constants (R1.4) valid, so the 42/305 gate must come back **byte-identical
to `docs/recon/RECON_MERGE_baseline.txt`, every target to 0.01 ns** — the same equivalence standard
S-2 met. If any sim end time moves, the widening was not neutral. The two members are
dead on arrival (nothing generates them yet), which is the point: they cost nothing to
carry and they remove the collision before the merge can express it.

### M-2 — Non-zero-attr integration coverage, written against the **current** rotation

One test each in `verilate_rq_if_tlp` and `verilate_rc_if_tlp`, driving `attr ∈
{1,…,6}` — **never 0 or 7**, which are fixed points of the rotation (R2). Green on
`kourosh/dev` today; goes red the moment M-3 lands the convention flip. That is the
whole purpose: coverage that exists *before* the change it is meant to catch.

*Ordering argument.* Before M-3, because after M-3 a test written against the new
convention proves only that the new code agrees with itself. Also cheap: the DW0 helpers
in both benches already take an `attr` parameter — only the call sites and assertions
are new. Consider wiring `test_tlp_end_to_end.py` into a target here too (§3.9); it is
the best attr coverage in the tree and currently runs nowhere.

### M-3 — The merge

Now genuinely one commit, in this order internally:

1. **Enum union** — take dev's `tlp_pkg.sv` (already 10 members from M-1), *not*
   `main`'s. This is the one file where the clean-merge result must be overridden.
2. **`tlp_layer` / `pcie_endpoint_top` port wiring** — connect or explicitly empty the
   six new ports at `src/rc/pcie_rq_rc_top.sv`, `tb/rc/tb_pcie_rq_if_tlp.sv`,
   `tb/rc/tb_pcie_rc_if_tlp.sv`. `PINCONNECTEMPTY` is waived and `PINMISSING` is not
   (R3), so `.target_message_o()` is the correct idiom for the four outputs; the two
   inputs need real ties. **Without this the merge does not build even with the enum
   fixed.**
3. **Attr convention** — adopt `main`'s spec-faithful rotation, and update dev's five
   golden helpers ([test_tlp_generator.py:66-67](../../tb/tlp/test_tlp_generator.py#L66-L67),
   `test_tlp_conf_requester.py:62,65`, `test_tlp_conf_parser.py:43,47`,
   `test_tlp_parser.py:10-11`, `enum_tb_common.py:368,370,423,425`) plus the three `_tlp`
   bench helpers. M-2's tests are the check that this was done everywhere.
4. **`main`'s Python constant fix** — `test_pcie_endpoint_line_rate.py:32-33` to 8/9.

*Ordering argument.* Steps 1 and 2 are build preconditions; step 3 is the only one with
a behavioural gate, and M-2 supplies it. Splitting 1–2 from 3 into separate commits is
defensible but they cannot be separately *tested* — nothing runs until both land.

### M-3a — **New rung.** Re-verify what `main` contributes, because nothing has

Because `main`'s TL has not compiled since `8386c16`, everything it brings is untested
by execution: the message path (requester/validator/classifier/generator/parser), the
attr fix, `pcie_config_mux`'s routing narrowing, and both DLL rewrites. The merge makes
it *compile*; it does not make it *verified*. Minimum: a message-origination test
mirroring `verilate_tlp_cfg1_spine`, and a config-mux test covering the IO/TCfg routes
that R4 shows were silently withdrawn.

*Ordering argument.* This is the rung the brief's ladder omits, and it is the one that
matters most for "trust nothing inherited." Skipping it means the 42/305 gate grows to
cover `main`'s code by *inclusion* rather than by *proof*.

### M-4 — Hygiene, then the RC-side TL+DLL top recon

Unchanged from the brief. `main` already deletes 78 tracked build artifacts for free
(R7); the >1 MB inheritance is untouched and stays a migration-time item (R8).

---

## §6 Stop triggers hit

**Trigger 4 — "A site or dependency is found that this brief does not anticipate."**
Hit, twice, both reported rather than worked around:

- **`origin/main` does not elaborate** (R1a). The brief's R1 presumes two coherent
  member sets. `main` has one coherent set and RTL that needs a different one. Verified
  out-of-tree by lint on extracted blobs; no working-tree modification was required, so
  trigger 2 did not fire.
- **`PINMISSING` is fatal under this repo's own waivers** (R3), making `main`'s six new
  `tlp_layer` ports a second independent build failure. Verified with a synthetic
  two-module case in the scratchpad against the real `lint/waiver.vlt`.

Triggers **not** hit:

- **1** — baseline measured 42 targets / 305 tests / all PASS; both sim end times
  580.00 ns.
- **2** — no finding required modifying the working tree; the two elaboration claims
  were settled on `git show` blobs in a scratchpad.
- **3** — the conflict set was computed with `git merge-tree` alone. No worktree, no
  merge state, `git status --porcelain` empty afterwards.
- **5** — `HEAD == origin/kourosh/dev`, tree clean at start.

Neither trigger-4 hit blocks M-1, which is `kourosh/dev`-only and does not depend on
anything `main` contains. Both are preconditions for M-3.
