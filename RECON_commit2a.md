# RECON_commit2a.md — Phase 0 recon for Commit 2a (RQ/RC AXIS requester interface)

**Branch:** `kourosh/dev` @ `f3160d0` · **Mode:** READ-ONLY, no RTL, no commit.
Every load-bearing answer is a quoted `file:line`. Inferences are marked as such.

> 🔁 **RE-ANCHORED 2026-07-28 (Phase B) against `50542d1`.** Every `file:line` below was written
> against the pre-merge tree (`f3160d0`) and has been re-verified post-merge. Anchors are
> corrected in place and each finding carries a **CONFIRMED / MOVED / INVALIDATED** tag.
> Full status table: **§P (Phase-B re-anchor)** at the end of this file.

> ✅ **CORRECTION 2026-07-28 (later the same day, post-`d5a4253`) — read this before anything else.**
> Phase B's headline "byte-granular config is no longer expressible" was written against the
> merge-era admission guard. **`d5a4253` ("tlp_requester: admit any config/IO request that fits
> inside one DW") removed it**, and `67220b5` locked the replacement admission matrix in the TL
> testbench. Admission is now **`byte_count <= 4 − address[1:0]`**, not `byte_count == 4`.
> ⇒ **byte-granular config IS expressible; R1 holds on all paths; T5 is REOPEN; no stop-and-report
> trigger stands.** Sections corrected: **§A.2 (rule 2), §B.3 (reinstated), §B.3a (superseded),
> §B.4 (bullet withdrawn), §P (B1 row + narrative), §Q.** The struck-through merge-era text is
> retained throughout for the record — **do not act on it.**

> **Headline (as written 2026-07-27; amended by §P, then restored by the correction above):**
> The TL command port is a clean landing surface for the RQ wrapper. The
> §4.3 byte-enable collision **resolves to R1 (byte-offset semantics)** and byte-granular
> config access **is expressible today** — the generator masks the emitted config DW's low
> two bits, so the byte offset in `command_address[1:0]` drives the BE and payload
> alignment without corrupting the register number. The RC gap is **much smaller than v2
> feared**: `tlp_layer` exposes the *entire* parsed completion header (`received_completion_header_o`,
> a full `tlp_header_t`) plus a separate DW-serial payload stream — not just the tracker's
> digested `result_*`. RC bit 30 (`Request Completed`) is available as `result_last_o`.
> No `src/tlp/` change is required. **No stop-and-report trigger fired.**

---

## G. Baseline (Q18) — green before anything is touched

Full TL suite, run sequentially (parallel Verilator SIGSEGVs — brief §2.7):

| Target | Tests | Target | Tests |
|---|---|---|---|
| verilate_tlp_requester | 2/2 | verilate_tlp_conf_requester | 10/10 |
| verilate_tlp_request_tracker | 2/2 | verilate_tlp_conf_tracker | 7/7 |
| verilate_tlp_parser | 3/3 | verilate_tlp_conf_parser | 12/12 |
| verilate_tlp_generator | 3/3 | verilate_tlp_conf_completion | 6/6 |
| verilate_tlp_completion_gen | 1/1 | verilate_tlp_conf_generator | 2/2 |
| verilate_tlp_comb | 3/3 | verilate_tlp_conf_classifier | 11/11 |
| verilate_tlp_payload_formatter | 2/2 | verilate_tlp_conf_datalast | 5/5 |
| verilate_tlp_compile | 3/3 | verilate_tlp_conf_formatter | 4/4 |
| verilate_tlp_cfg0_spine | 2/2 | | |

**TL total: 17 targets, 78 tests, 78 PASS, 0 FAIL.**
**Control:** `verilate_conformance` (fusesoc:pcie:tb_ltssm_conformance) = **1/1** — the per-commit
regression anchor cited in T12/U9/V4 (LTSSM layer; outside this commit's blast radius).

Git state: Commit 0/1 files are **committed**, not staged (`git log`: `763e7ee`, `17adf72`,
`f3160d0` on `kourosh/dev`, ahead 7 of origin). Only untracked path is
`tb/ltssm/__pycache__/`. Tree matches this brief's assumptions — no stop trigger.

---

## A. The TL command port (the RQ landing surface)

### A.1 Full command port list — **B3: MOVED** (re-anchored 2026-07-28)
~~Source: `tlp_requester.sv:26-68`, wired identically at `tlp_layer.sv:43-60`.~~
**Current source: `tlp_requester.sv:15-31,49-50`, wired identically at `tlp_layer.sv:54-71`.**

| Signal | Width | Dir | Level/Pulse |
|---|---|---|---|
| `command_valid_i` / `command_ready_o` | 1 | in/out | handshake (`:15-16`) |
| `command_i` | `tlp_cmd_e` (3b) | in | level, latched (`:17`) |
| `command_address_i` | 64 | in | level, latched (`:18`) |
| `command_byte_count_i` | 13 | in | level, latched (authoritative) (`:19`) |
| `command_tc_i` / `command_attr_i` | 3 / 3 | in | latched (`:20-21`) |
| `command_context_i` | `CONTEXT_WIDTH`=16 | in | latched → echoed on completion (`:22`) |
| `command_prefix_valid_i` / `command_prefix_i` | 1 / 32 | in | latched (`:23-24`) |
| ~~`command_digest_valid_i` / `command_digest_i` (1/32)~~ → **`command_ecrc_enable_i`** | 1 | in | ⚠️ **CHANGED by merge**: the 32-bit host-supplied digest is gone; the TL now *computes* ECRC (`tlp_ecrc.sv`) and this pin only enables it (`:25`). Tie **0** to bypass. |
| `command_data_i` / `command_keep_i` | 32 / 4 | in | payload beat (`:27-28`) |
| `command_data_valid_i` / `command_data_last_i` / `command_data_ready_o` | 1 | | payload handshake (`:29-31`) |
| ~~`command_error_o` (1)~~ → **`command_error_valid_o` + `command_error_code_o`** | 1 + `tlp_error_e`(5b) | out | ⚠️ **CHANGED by merge**: split pair, both 1-cyc pulses, registered (`:49-50`) |

Requester params: `DATA_WIDTH=32, KEEP_WIDTH=4, CONTEXT_WIDTH=16` (~~`:22-25`~~ → **`tlp_requester.sv:5-7`**).

**⚠️ NEW at the `tlp_layer` boundary (merge-added; the RQ wrapper must satisfy these to transmit
at all — see §Q/B9):** `link_up_i`, `transmit_enable_i` (`tlp_layer.sv:19-20`) and the
flow-control group `fc_initialized_i`, `fc_update_valid_i`, `fc_ph_i/fc_pd_i/fc_nph_i/fc_npd_i/
fc_cplh_i/fc_cpld_i` (`tlp_layer.sv:31-38`). TX is gated on
`credit_request_ready && transmit_enable_i && link_up_i` (`tlp_layer.sv:249`).

### A.2 Launch handshake (Q2) — **B3: MOVED, plus a NEW admission check**
- Qualifier: `command_ready_o = state_r == REQ_IDLE` (~~`:156`~~ → **`tlp_requester.sv:137`**). Accept fires on
  `command_valid_i && command_ready_o`, **single cycle**, latching every `command_*` field
  (~~`:204-219`~~ → **`tlp_requester.sv:182-204`**).
- `command_byte_count_i` → `remaining_r` is authoritative (~~`:207`~~ → **`:192`**). The requester
  owns MPS/4KB segmentation internally (`calculate_segment`, ~~`:103-120`~~ → **`:84-101`**). `command_data_last_i`
  is compared against `request_last = expected_data_last && (remaining_r <= segment_bytes_r)`
  (~~`:174`~~ → **`:155`**), i.e. **end-of-whole-request**, not per-segment. Mismatch → `command_error_valid_o`
  pulse (~~`:242-243`~~ → **`:227-231`**, code `TLP_ERR_LOCAL_PAYLOAD`); early last → abort to `REQ_IDLE`
  (~~`:244-248`~~ → **`:232-236`**).
- **NEW (merge-added, then relaxed by `d5a4253`; now `tlp_requester.sv:183-199`) — a
  command-admission guard that did not exist pre-merge.** Before latching anything, the FSM
  rejects the command outright (`command_error_valid_o` + `TLP_ERR_BAD_LENGTH`, **no TLP emitted**,
  stays in `REQ_IDLE`) when:
  1. `command_byte_count_i == 0` and the command is not `TLP_CMD_MEM_READ`; **or**
  2. the command is `CFG_READ0`/`CFG_WRITE0`/`IO_READ`/`IO_WRITE` and
     ~~`command_byte_count_i != 4`~~ → ✅ **`command_byte_count_i > (4 − command_address_i[1:0])`**
     (corrected 2026-07-28, `d5a4253`).
  Rule 2 as originally written is what invalidated §B.3; **in its current form it does not** — §B.3
  is reinstated. This is the wrapper's config/IO fit check verbatim.

### A.3 `tlp_cmd_e` members (Q3) — **B2: CONFIRMED verbatim** (2026-07-28)
`tlp_pkg.sv:43-50`: `MEM_READ=0, MEM_WRITE=1, CFG_READ0=2, CFG_WRITE0=3, IO_READ=4, IO_WRITE=5`.
Maps 1:1 to MemRd/MemWr/CfgRd0/CfgWr0/IORd/IOWr. **CFG1 is absent from the command enum** — only
a wire-level `TLP_TYPE_CFG1=5'b00101` exists (`tlp_pkg.sv:21`) with no `tlp_cmd_e` that reaches it.
The requester cannot originate a Type-1 config request → wrapper detects+rejects (§4.2), never
silently maps. ✔ confirms brief §1.
**Append-only audit (`git diff 3aceca8 HEAD -- src/tlp/tlp_pkg.sv`): `tlp_cmd_e`, `tlp_type_e`,
`tlp_fmt_e`, `tlp_class_e`, `tlp_cpl_status_e` are byte-identical — no member inserted, none
reordered, no encoding moved.** The merge only *added* two whole new enums (`tlp_credit_class_e`
`:52-56`, `tlp_error_e` `:58-74`) and new helper functions. Nothing positional went on the wire.
Note `tlp_classifier.sv:38-40` decodes `TLP_TYPE_CFG1` on the **RX** side (a received Type-1 config
is classified, then rejected by BAR/config-hit logic) — still no TX command path to it.

### A.4 Payload path (Q4) — **B4: MOVED (semantics CONFIRMED)**
- `DATA_WIDTH=32`, `KEEP_WIDTH=4` (**`tlp_requester.sv:5-6`**). Valid/ready: `command_data_valid_i` / `command_data_ready_o`.
- `keep` **is honoured on every beat**: `accepted_bytes = Σ command_keep_i[lane]` (popcount,
  ~~`:126-128`~~ → **`:107-109`**), accumulated into `segment_sent_r` (~~`:241`~~ → **`:226`**). Partial final beat is handled by the
  popcount, not assumed full.
- `packet_keep_o = command_keep_i` — straight passthrough to the DLL-facing AXIS (~~`:166`~~ → **`:147`**).
- `packet_data_last_o = expected_data_last || command_data_last_i` (**`:158`**) — still closes the
  transmitted packet **per segment**, independently of the whole-request `request_last`.
- **Gearbox contract:** the downsize output feeding this port must present 32-bit DW beats with
  `tkeep` marking real bytes and assert `last` exactly on the final beat of the whole request
  (byte count from the descriptor). This is the `command_data_last` contract (memory
  [[command-data-last-contract]]).

### A.5 Backpressure (Q5) — **B4: MOVED (semantics CONFIRMED)**
`command_data_ready_o = state_r == REQ_DATA && packet_data_ready_i` (~~`:182`~~ → **`tlp_requester.sv:159`**) —
**combinational**
off the DLL-facing `packet_data_ready_i`. So the requester *can* stall the host mid-request, and
the ready is combinational (a timing note for the gearbox, not a blocker — brief §3.A.5).
**Post-merge addendum:** inside `tlp_layer` that `packet_data_ready_i` now ultimately sources from
`tlp_vc_buffer` (`tlp_layer.sv:421-438`), which backpressures on `packet_count_r < PACKET_DEPTH`
(`tlp_vc_buffer.sv:53`). Credit exhaustion therefore reaches the gearbox as **ordinary AXIS
backpressure**, not as an error — the gearbox contract is unchanged, but stalls can now be long.

---

## B. Byte enables — the ownership question ⭐

### B.1 Where BEs are computed (Q6) — **B1 point 1: MOVED (claim CONFIRMED)**
~~`tlp_pkg.sv:93-116`~~ → **`tlp_pkg.sv:165-193`** defines `tlp_first_be(address_low, byte_length)` /
`tlp_last_be(address_low, byte_length)`. **Only call site in `src/tlp/`:**
~~`tlp_requester.sv:147-148`~~ → **`tlp_requester.sv:129-130`**:

```
header_c.first_be = tlp_first_be(address_r[1:0], segment_bytes_r);
header_c.last_be  = tlp_last_be(address_r[1:0], segment_bytes_r);
```

This is **unconditional** — identical for MemWr/IOWr/CfgWr0/reads; there is *no* config special
case. The TL computes BEs itself from `address_r[1:0]` (a **byte offset** within the DW) and
`segment_bytes_r`. Confirms the v2 hypothesis. (The `dma_if_pcie_us_wr.v` hits in the grep are
unrelated third-party verilog-pcie DMA, not `src/tlp/`.)
**Still true post-merge.** The two BE functions were re-implemented for integer-width lint
(`tlp_pkg.sv:165-193`; `first_lane`/`end_lane`/`end_position` temporaries) but the **mapping is
unchanged** — verified by direct simulation, §B.3a.

### B.2 The collision, resolved (Q8) → **R1 (byte-offset semantics)** — **B1 points 2+3: MOVED (claim CONFIRMED)**
`address_r[1:0]` is used in **two** places for a config request:
1. `tlp_first_be(address_r[1:0], …)` — as a byte offset.
2. `header_c.address = address_r` (~~`:149`~~ → **`tlp_requester.sv:131`**) — as the low bits of the address the generator emits.

There is **no on-wire conflict**, because the generator *forces the emitted config DW's low two
bits to zero*:
- ~~`tlp_generator.sv:70-71`~~ → **`tlp_generator.sv:81-82`**: `dw2 = tlp_is_4dw(fmt) ? address[63:32] : {header_r.address[31:2], 2'b00};`
  (config is always 3DW, so DW2 = `{address[31:2], 2'b00}`).
- ~~`tlp_generator.sv:109`~~ → **`tlp_generator.sv:85`** (4DW DW3 path) likewise masks `{address[31:2], 2'b00}`.
  **Note the merge refactored this:** DW3 is now a named `dw3` signal computed once at `:85` and
  emitted via `axis_dw3` at `:130`, because the new `PCIE_WIRE_ORDER` parameter (`:9`, `:89-93`)
  can byte-swap it. The mask itself is untouched, and `PCIE_WIRE_ORDER` defaults to `0`.
- Point 3 (payload realignment by the same offset): ~~`payload_offset = header_r.address[1:0]`
  (`tlp_generator.sv:79`, formatter `:179`)~~ → **`tlp_generator.sv:98-100`**, now a ternary that
  selects `header_r.lower_address[1:0]` for CPL/CPL_LOCK and `header_r.address[1:0]` otherwise.
  **For every request-path TLP the non-completion arm applies, so the claim holds unchanged**;
  it feeds the formatter's `start_offset_i` at **`tlp_generator.sv:211`** → `count_r`
  (`tlp_payload_formatter.sv:53`).

And the register number lives in `address[7:2]`, **disjoint** from the byte offset `[1:0]`
(matches the Commit-1 config-DW layout: `[31:24]=Bus [23:19]=Dev [18:16]=Fn [11:8]=ExtReg
[7:2]=Reg#`, [[tlp-cfg0-spine]]).

**Resolution: R1.** Commit-1 A.3's "`command_address[1:0] = 2'b00`" was the *DW-aligned* special
case (whole-DW access, `first_be=1111`), **not** a hard constraint. v1's §4.3 (pin `[1:0]=00`) was
wrong; the wrapper must drive `command_address[1:0] = byte offset`.

### B.3 Byte-granular config IS expressible (Q7) — the T5 gate is OPEN — ✅ **REINSTATED 2026-07-28 (post-`d5a4253`)**

> **This section is LIVE again.** It was struck through earlier the same day against the merge-era
> admission guard; `d5a4253` ("tlp_requester: admit any config/IO request that fits inside one DW")
> removed that guard's `byte_count == 4` requirement, and `67220b5` locked the new admission matrix
> in the TL testbench. The reasoning below was never arithmetically wrong — the TL simply refused
> the command. It no longer does. **See §B.3a for the current-truth guard text.**

To write **Secondary Bus Number at config offset `0x19`** (`first_be=4'b0010`):
- `command_address[7:2]` = Reg# = `0x18>>2 = 0x06`; `command_address[1:0] = 2'b01` (byte offset 1);
  `command_byte_count_i = 1`.
- ⇒ `tlp_first_be(2'b01, 13'd1) = 4'b0010` (~~`tlp_pkg.sv:100-103`~~ → **`tlp_pkg.sv:165-180`**, lane∈[1,2)).
- ⇒ `length_dw = 1` (~~`tlp_requester.sv:144`~~ → **`:125-126`**). Config DwordCount = 1. ✔
- ⇒ emitted config DW = `{address[31:2], 2'b00}` — register number intact, `[1:0]=00` on the wire. ✔
- ⇒ payload realigned to the same offset: `payload_offset = header_r.address[1:0]` feeds the
  payload formatter (~~`tlp_generator.sv:79, 179`~~ → **`:98-100`, `:211`**), so the single write
  byte lands in lane 1. ✔

The byte offset coherently drives **BE + payload alignment + a zeroed on-wire DW**. **T5 is
achievable; Commit 2b's bus-number assignment is unblocked.** No stop trigger.

### B.3a ~~Current truth: byte-granular config is NOT expressible~~ — ✅ **SUPERSEDED 2026-07-28 by `d5a4253`**

> **This section's blocking claim is DEAD.** It was written against the merge-era guard, *before*
> `d5a4253` relaxed it. The superseded analysis is retained, struck through, at the end of the
> section. **T5 is REOPEN; Commit 2b's Secondary-Bus-Number write needs no read-modify-write.**

**Current truth (post-`d5a4253`, locked by `67220b5`'s admission matrix).** The guard at
**`tlp_requester.sv:183-199`** now reads:

```systemverilog
REQ_IDLE: if (command_valid_i && command_ready_o) begin
  if ((command_byte_count_i == 0 && command_i != TLP_CMD_MEM_READ) ||
      ((command_i == TLP_CMD_CFG_READ0 || command_i == TLP_CMD_CFG_WRITE0 ||
        command_i == TLP_CMD_IO_READ || command_i == TLP_CMD_IO_WRITE) &&
       command_byte_count_i > (13'd4 - {11'd0, command_address_i[1:0]}))) begin
    command_error_valid_o <= 1'b1;
    command_error_code_o <= TLP_ERR_BAD_LENGTH;
```

Admission is **`byte_count <= 4 − address[1:0]`**, *not* `byte_count == 4`. PCIe Base 2.1 §2.2.7
constrains the config *Length* field, not the byte enables, so a single-byte config write with
`first_be=0010` is legal — and is now admitted. §B.3's worked example is live again:
`CFG_WRITE0 addr=0x19 bc=1` ⇒ `first_be=0010, last_be=0000, length_dw=1`, **one** TLP.

**The two-TLP split is gone by construction.** Every admitted config/IO shape satisfies
`byte_count + address[1:0] <= 4`, so `calculate_segment`'s clamp to `limit − address[1:0]`
(`tlp_requester.sv:93-94`) can no longer split the request, and `length_dw` (`:125-126`) is 1 by
construction. The `bc=4 @ off=1` shape is now **rejected at admission** instead of split.

**Consequences for the RQ wrapper (Commit 2a-i):**
1. **R1 (byte-offset semantics) holds on *all* paths** — memory, memory-read, config and I/O.
   The §D.2 byte-offset derivation is universal; there is no config special case.
2. The wrapper's config/IO legality check is **`byte_count > (4 − off)` ⇒ reject**.
   ⛔ **Do NOT code the `byte_count != 4` / `first_be != 4'hF` check** — it would re-impose a
   restriction the TL no longer has, and would fail T3/T14.
3. **T5 is UNBLOCKED**, and with it Commit 2b's Secondary-Bus-Number assignment as a direct
   single-byte write.
4. The "two config TLPs" latent RTL defect (old point 5) is **fixed** — the shape that produced it
   is no longer admitted.

<details><summary>~~Superseded analysis (merge-era guard, pre-<code>d5a4253</code>) — retained for the record, DO NOT act on it~~</summary>

> ~~**Cause:** the merge (`0e88ac1`, via `b0d3971`) added a command-admission guard at
> `tlp_requester.sv:183-188` that did not exist at `f3160d0`, admitting a CFG/IO command **only**
> when `command_byte_count_i == 4` exactly. `byte_count = 1` — the entire basis of §B.3 — was
> rejected with `TLP_ERR_BAD_LENGTH`, no TLP emitted. And `byte_count = 4` was no workaround:
> `calculate_segment` (`:84-101`) clamped the segment to `limit - address[1:0]` (`:93-94`), so a
> CFG command at byte offset 1 with `byte_count = 4` split into **two** config TLPs.~~
> Simulated on the merge-era RTL (scratchpad harness, Verilator 5.050 — no `src/`/`tb/` touched):

| stimulus | ~~`command_error_code_o`~~ (merge-era) | ~~TLPs~~ | ~~header fields~~ | **post-`d5a4253`** |
|---|---|---|---|---|
| `CFG_WRITE0 addr=0x19 bc=1` | ~~`TLP_ERR_BAD_LENGTH`~~ | ~~0~~ | — | ✅ admitted, 1 TLP, `first_be=0010 len=1` |
| `CFG_READ0  addr=0x19 bc=1` | ~~`TLP_ERR_BAD_LENGTH`~~ | ~~0~~ | — | ✅ admitted, 1 TLP |
| `IO_WRITE   addr=0x19 bc=1` | ~~`TLP_ERR_BAD_LENGTH`~~ | ~~0~~ | — | ✅ admitted, 1 TLP |
| `CFG_WRITE0 addr=0x19 bc=4` | ~~none at admission~~ | ~~2 ⚠️~~ | ~~`#0 first_be=1110`, `#1 first_be=0001`~~ | ⛔ rejected (`4 > 4−1`) — split defect gone |
| `CFG_WRITE0 addr=0x18 bc=4` | none | 1 | `first_be=1111 last_be=0000 len=1` ✔ | unchanged ✔ |
| `MEM_WRITE  addr=0x1019 bc=1` | none | 1 | `first_be=0010 last_be=0000 len=1` ✔ | unchanged ✔ |
| `MEM_WRITE  addr=0x101a bc=2` | none | 1 | `first_be=1100 last_be=0000 len=1` ✔ | unchanged ✔ |
| `MEM_READ   addr=0x1019 bc=1` | none | 1 | `first_be=0010 last_be=0000 len=1` ✔ | unchanged ✔ |

> ~~**Merge-era consequences (all now void):** CFG0/CFG1/IO restricted to `bc == 4` and
> `address[1:0] == 2'b00`; T5 blocked at the TL command port; Commit 2b forced into a whole-DW
> read-modify-write of config DW `0x18`; the two-TLP split a latent RTL defect.~~

</details>

### B.4 What is NOT expressible (Q9) → rejects, listed in KNOWN_GAPS — **MOVED + EXTENDED**
- **Non-contiguous BEs** (e.g. `first_be=4'b1001`): `tlp_first_be`/`tlp_last_be` only produce
  *contiguous* range masks (~~`tlp_pkg.sv:100-103` / `:112-115`~~ → **`tlp_pkg.sv:165-180` / `:182-193`**).
  Not expressible → the wrapper
  must **reject** (`rq_protocol_error_o` + `$warning`) and list in KNOWN_GAPS. (PG213 permits
  non-contiguous BE on ≤2-DW writes; we don't support it this commit.)
- **Zero-length read** (`DwordCount=1, first_be=0`): `byte_length=0` ⇒ `first_be=0` but
  `length_dw` degenerates. Not cleanly expressible → reject, KNOWN_GAP.
  ⚠️ **Post-merge nuance:** `header_c.length_dw` now special-cases `segment_bytes_r == 0 ? 11'd1`
  (`tlp_requester.sv:125-126`), so the degenerate `length_dw = 0` no longer occurs; and the new
  admission guard (`:183-188`) *permits* `byte_count == 0` **only** for `TLP_CMD_MEM_READ`. So a
  zero-length **memory** read is now cleanly expressible (`length_dw = 1`, `first_be = 0`,
  `last_be = 0`); zero-length CFG/IO is rejected. **Re-decide this KNOWN_GAP in Phase 1.**
- ~~⛔ **NEW (from §B.3a) — byte-granular CFG0/IO of any width other than a full aligned DW.**
  Not expressible; the wrapper must reject `is_cfg_or_io && (byte_count != 4 || addr[1:0] != 0)`~~
  ✅ **WITHDRAWN 2026-07-28 (`d5a4253`).** Byte-granular CFG0/IO **is** expressible. The wrapper's
  check is instead the fit condition **`is_cfg_or_io && byte_count > (4 − off)` ⇒ reject**, still
  applied *before* driving the TL so that `TLP_ERR_BAD_LENGTH` is never the first line of defence.
  This is **not** a KNOWN_GAP — it is a legality check on genuinely illegal shapes.
- **§4.3 BE-consistency check:** the wrapper still compares descriptor-implied access vs the
  `s_axis_rq_tuser` BEs; disagreement → `rq_protocol_error_o` rather than silently preferring one.

---

## C. `command_context_i` ⭐

### C.1 It exists and round-trips (Q10) — **B5 (context leg): MOVED (claim CONFIRMED)**
16-bit `command_context_i` (~~`tlp_requester.sv:40`~~ → **`:22`**, `CONTEXT_WIDTH=16` default ~~`:25`~~ → **`:7`**). Echo path:
`command_context_i` → `context_r` (~~`tlp_requester.sv:210`~~ → **`:195`**) → `tag_context_o` (~~`:160`~~ → **`:141`**) →
tracker `allocate_context_i` → `context_r[tag]` (~~`tlp_request_tracker.sv:111`~~ → **`:117`**) → on completion
match `result_context_r` (~~`:120`~~ → **`:138`**) → `result_context_o` at the layer (~~`tlp_layer.sv:289`~~ → **`:361`**).
**Confirmed: stash at request time, echoed on the matching completion. The `command_context_i`
echo is still the right mechanism for RC Lower Address `[11:7]` — RC6 did not touch it** (RC6
changed `allocate_address_i`, an *independent* tracker input; see §D.4).

### C.2 What it can reconstruct (Q11)
16 bits is **not** enough for {LowerAddr[11:0] + orig ByteCount[12:0] + RequesterID[15:0]}=41b.
But — see §D — nearly every RC descriptor field comes directly from the parsed completion header,
so context is a **bonus, not a necessity**. Its one useful job: stash the original request's
`address[11:7]` (5 bits) to close the RC **Lower Address [11:7]** gap the CPL can't carry.
**Timing caveat:** `result_context_o` is **registered** (1 cycle after the completion header is
accepted — ~~`tlp_request_tracker.sv:104,119-120`~~ → **`tlp_request_tracker.sv:110-111,136-142`**),
whereas `received_completion_header_o` is
combinational (~~`tlp_layer.sv:164`~~ → **`tlp_layer.sv:195`**). The RC wrapper must align the two (the skid/FIFO capture in
§7.1 absorbs this skew naturally). **Design decision for 2a-ii:** default the Lower Address
[11:7] to 0 and list in KNOWN_GAPS, OR route `address[11:7]` through context — recommend the
latter only if U-tests show it's needed; for the config-enumeration path (1 DW) it's moot.

---

## D. The completion return surface (the RC source) ⭐

**Key correction to the v2 premise:** `tlp_layer` exposes **two** completion surfaces, not one.

### D.1 Surfaces (Q12) — **B5: MOVED (both surfaces CONFIRMED present)**
1. **`received_completion_*`** (~~`tlp_layer.sv:97-104`, `:164-165, :192-197`~~ →
   **`tlp_layer.sv:108-115`, `:195-197`, `:230-235`**): the *raw parsed CplD*.
   - `received_completion_header_o` = `parsed_header` — the **full `tlp_header_t`** (tag,
     requester_id, completer_id, byte_count, lower_address, completion_status, poisoned, tc,
     attributes, length_dw). ~~`:164`~~ → **`:195`**.
   - `received_completion_data_o[31:0]` / `_keep` / `_valid` / `_last` / `_ready` — the completion
     **payload as a 32-bit DW-serial AXIS stream** (~~`:192-195`~~ → **`:230-235`**). `valid = parsed_header_valid &&
     parsed_completion && tracker_completion_ready` (~~`:165`~~ → **`:196-197`**). Level AXIS handshake.
     ⚠️ **Merge addition:** payload routing is now arbitrated by a registered `route_completion_r`
     (`tlp_layer.sv:151, 228-246`) that steers `parsed_data` to either the target or the completion
     port. The RC payload port is unchanged, but it is only valid while `route_completion_r` is set.
2. **`result_*`** (tracker digest, ~~`tlp_layer.sv:106-113`~~ → **`tlp_layer.sv:117-133`**): `result_valid_o` (**1-cyc pulse**,
   ~~`tlp_request_tracker.sv:82,104`~~ → **`tlp_request_tracker.sv:85,110-111,137`**), `result_context_o[15:0]`, `result_status_o[2:0]`,
   `result_last_o`, `unexpected_completion_o`, `outstanding_o`. Plus `malformed_o` (from parser,
   ~~`:111`~~ → **`tlp_layer.sv:122`**).
   ⚠️ **Merge added a sibling output: `completion_error_code_o`** (`tlp_layer.sv:132`, driven by
   `tlp_request_tracker.sv:126,135`) — a `tlp_error_e` qualifying *why* `unexpected_completion_o`
   fired (`TLP_ERR_UNEXPECTED_COMPLETION` = no tag match, `TLP_ERR_COMPLETION_OVERFLOW` = matched
   but failed the new consistency checks). **The RC wrapper should surface this** rather than
   collapsing both causes into one error bit.

### D.2 RC descriptor derivation (Q13) — §4.4 field-by-field — **B5: MOVED, table still valid**
| RC field | Source | Status |
|---|---|---|
| Lower Address `[11:0]` | `received_completion_header_o.lower_address[6:0]` (~~`parser.sv:174`~~ → **`tlp_parser.sv:188`**) | **[6:0] OK, [11:7] GAP** (context-closeable — see §D.4) |
| Error Code `[15:12]` | derive from `completion_status` + `poisoned` | OK (derived) |
| Byte Count `[28:16]` | `received_completion_header_o.byte_count` ([11:0] from CPL, ~~`parser.sv:157`~~ → **`tlp_parser.sv:168`**; bit12=0) | OK — note the parser now maps encoded `0` → **4096** (`:168`) |
| Locked `[29]` | `0` (no CPL_LOCK path this commit) | OK (const) |
| **Request Completed `[30]`** | **`result_last_o`** (~~`tracker.sv:122-124`~~ → **`tlp_request_tracker.sv:140-142`**) | **OK — B6 CONFIRMED** |
| Dword Count `[42:32]` | `received_completion_header_o.length_dw` | OK |
| Completion Status `[45:43]` | `received_completion_header_o.completion_status` / `result_status_o` | OK |
| Poisoned `[46]` | `received_completion_header_o.poisoned` | OK |
| Requester ID `[63:48]` | `received_completion_header_o.requester_id` | OK |
| Tag `[71:64]` | `received_completion_header_o.tag` | OK |
| Completer ID `[87:72]` | `received_completion_header_o.completer_id` | OK |
| TC `[91:89]` | `received_completion_header_o.traffic_class` | OK |
| Attr `[94:92]` | `received_completion_header_o.attributes` (3b) | OK |

**KNOWN_GAPS (RC):** Lower Address `[11:7]` (CPL carries only 7 bits; drive 0 or route via
context). Everything else is derivable — v2's fear that the RC gap was large is **not** borne out.

### D.3 Split-completion / bit 30 (Q14) — **B6: MOVED (claim CONFIRMED, accounting intact)**
The tracker keeps `remaining_r[tag]` and decrements it by `completion_payload_bytes_i` per CPL
(~~`tlp_request_tracker.sv:122-133`~~ → **`tlp_request_tracker.sv:143-154`**); `completion_payload_bytes` is computed at the layer from
`length_dw` and `lower_address[1:0]`, clamped to the CPL's `byte_count`
(~~`tlp_layer.sv:181-186`~~ → **`tlp_layer.sv:219-224`**). `result_last_o` is set on the CPL where `payload_bytes >= remaining`
(or non-SC / no-data) — **the last-CPL-of-request signal = RC bit 30.** The RC descriptor's own
Byte Count field is taken from the CPL header (`byte_count`), which is spec-defined as "remaining
incl. this CPL." Both present. ✔ (Byte-count accounting was proven in `verilate_tlp_conf_tracker`,
7/7.) No stop trigger.
**Post-merge re-verification:** the `result_last_r` expression is byte-for-byte the pre-merge one
(`tlp_request_tracker.sv:140-142`), and the decrement / tag-release arms (`:143-154`) are
structurally unchanged. **RC5/RC6 did not alter the accounting that drives bit 30** — they added a
*pre-filter* in front of it (`:127-135`, see §D.4), which can only suppress a completion entirely,
never mis-set bit 30 on an accepted one. **Tag-reuse corruption risk: not present.**

### D.4 ⚠️ NEW (RC6) — the completion-consistency pre-filter and the Lower Address story
`tlp_request_tracker` gained an input `allocate_address_i` (`:16`) and a per-tag
`next_lower_address_r[]` (`:41`) seeded at allocation from `allocate_address_i[6:0]` (`:119-120`)
and advanced by `completion_payload_bytes_i[6:0]` per CPL (`:152-153`). The layer drives it as
(`tlp_layer.sv:353-354`):

```systemverilog
.allocate_address_i(requester_header.tlp_type == TLP_TYPE_MEM ?
                    requester_header.address : 64'd0),
```

i.e. **0 for every non-memory request** — correct per PCIe Base 2.1 §2.2.9 (Lower Address is
defined only for Memory Read Completions; all others carry 0).

A matched completion is now additionally **rejected** (`unexpected_completion_o` +
`TLP_ERR_COMPLETION_OVERFLOW`, `:127-135`) unless it satisfies **all** of:
`payload_bytes != 0`, `payload_bytes <= remaining`, `byte_count == remaining`, and
`lower_address == next_lower_address_r` — plus the converse rule that a completion to a
*non-data-expecting* request must carry zero payload.

**Impact on the RC design — two things to carry into 2a-ii:**
1. **The RC descriptor's Lower Address source is unchanged**: still
   `received_completion_header_o.lower_address[6:0]` for `[11:0]`'s low 7 bits, still the
   `command_context_i` echo for `[11:7]`. `allocate_address_i` is an *internal expectation*, not a
   descriptor source, and it is **not exposed on any `tlp_layer` port**. ✔ mechanism intact.
2. **KNOWN_GAP #2 (split-read Lower Address on the 2nd+ CPL) is now solvable in principle but not
   in practice**: the tracker *does* maintain the running per-CPL lower address in
   `next_lower_address_r[]`, but does not expose it. Closing that gap would need a `src/tlp/`
   port addition — **out of scope for Commit 2a; keep the gap documented.**

---

## E. Tag management (Q15) → CORE-MANAGED — **B7: MOVED (claim CONFIRMED)**

The tracker allocates: `allocate_tag_o = first free tag` (~~`tlp_request_tracker.sv:52-62`~~ →
**`tlp_request_tracker.sv:55-65`**). The
requester enters `REQ_TAG` and consumes `tag_i` (~~`tlp_requester.sv:157, 221-223`~~ →
**`tlp_requester.sv:138, 206-209`**). The host does
**not** supply the tag for non-posted requests. ⇒ **PG213 core-managed-tag mode**: the RQ wrapper
should expose `pcie_rq_tag[7:0]` + `pcie_rq_tag_vld` and **ignore `desc[103:96]`** (document it).
Exception: `MEM_WRITE` (posted) skips `REQ_TAG` (~~`tlp_requester.sv:218`~~ → **`:202`** → now
**`:211`, `:253`**) — no tag. On the RC side
the Tag echoes back from the CPL header, so RC descriptor Tag is faithful.

> ✅ **CLOSED 2026-07-28 (`3129114`).** This recon did not notice that `allocated_tag` had **no
> `tlp_layer` port** — it terminated between `requester_inst.tag_i` and `tracker_inst.allocate_tag_o`.
> Commit 2a-i (`96918d5`) therefore shipped `pcie_rq_tag_o` fed from an integrator-supplied
> `rq_tag_i`, i.e. **a different number from the one on the wire** — worse than exposing nothing,
> because it invites a correlation that silently fails. `3129114` added
> **`allocated_tag_o` + `allocated_tag_valid_o`** to `tlp_layer` as pure combinational taps
> (`allocated_tag`, and `tag_valid && tag_ready` — the tracker's own commit condition,
> `tlp_request_tracker.sv:113`), and `pcie_rq_if` now forwards those.
> **T16 asserts the presented tag equals the emitted TLP's DW1 Tag**; T17–T20 cover multiple
> outstanding, posted writes, descriptor-Tag isolation and tag exhaustion.
> ⚠️ The tag is **not** available at command-accept time — the requester allocates in `REQ_TAG` a
> cycle or more after leaving `REQ_IDLE` — which is exactly why PG213 pairs the tag with a valid
> strobe. Do not try to qualify it with `command_ready_o`.
Namespace note for Kourosh (§11): confirm EP-side completer tags and RC-side requester tags can't
collide.
**No move to client-managed tags.** The allocator, the `extended_tag_enable_i` gate (`:59-60`,
capping the search at 32 tags when low), and the requester's `REQ_TAG` consumption are all
pre-merge shape. The only tracker port additions are `allocate_address_i` (§D.4) and
`completion_error_code_o` (§D.1) — neither is a tag-ownership change.

---

## F. Build surface (Q16, Q17)

- **Q16:** `tb/tlp/tb_tlp.core` = `fusesoc:pcie:tb_tlp:1.0.0`, 17 `verilate_tlp_*` targets
  (listed in §G). RTL comes from `::tlp_core:1.0.0` (`src/tlp/tlp_core.core`) unchanged. Commit
  0/1 **committed** (§G). Reported, not fixed.
- **Q17:** `waiver.vlt` lives at `lint/waiver.vlt`, packaged by `fusesoc:pcie:lint:1.0.0`
  (`lint/lint.core`) with `copyto: .`. A new `.core` picks it up by (a) depending on
  `fusesoc:pcie:lint` in its rtl fileset and (b) listing `waiver.vlt` under
  `verilator_options` — exactly the pattern in `tb_tlp.core:13-16` and every target's
  `verilator_options`. **Plan for Commit 2a:** `src/rc/rc_core.core` (new package + gearboxes +
  wrappers) and `tb/rc/tb_rc.core` depend on `fusesoc:pcie:lint` and reuse this waiver.
- `src/rc/` and `tb/rc/` **do not exist yet** — clean slate, no collisions.

---

## Design implications carried into Phase 1 / RTL (for the go/no-go)

1. **§4.3 = R1.** RQ wrapper drives `command_address[1:0] = byte offset` (leading-zero count of
   `first_be`), `command_byte_count = popcount(first_be)+…+popcount(last_be)` for contiguous BEs.
   Non-contiguous BE / zero-length read → reject + KNOWN_GAPS. ~~**Byte-granular config works.**~~
   ⛔ **AMENDED 2026-07-28: R1 applies to the MEMORY path only. Byte-granular config does NOT work
   (§B.3a) — for CFG0/IO the wrapper must force `byte_count = 4` AND `address[1:0] = 2'b00`, and
   reject anything else.**
2. **RC path rides `received_completion_header_o` + `received_completion_data_o`**, with bit 30
   from `result_last_o`. The tracker `result_*` path is for tag/last accounting; the parsed-header
   path carries the descriptor fields. Mind the 1-cycle skew (§C.2) — the §7.1 skid/FIFO absorbs it.
3. **Core-managed tags** → expose `pcie_rq_tag`/`pcie_rq_tag_vld`, ignore descriptor Tag.
4. **`result_valid_o` is a 1-cycle pulse** ([[tlp-cfg0-spine]]) — the RC wrapper *must* capture,
   never passthrough (brief §7.1).
5. **Gearboxes:** `command_data_ready_o` is combinational (§A.5); downsize `DESC_DW=4` feeds the
   RQ payload; upsize `DESC_DW=3` for the RC 3-DW descriptor rotation.

## ⚠️ Phase 1 blocker to flag (not a Phase 0 issue)
The PG213 PDF (`UltraScale-Devices-Integrated-Block-for-PCI-Express-amd.pdf`) referenced in brief
§4 is **not present anywhere on the system** (searched all of `/home/kourosh`; only the PCIe Base
Spec Rev 2.1 and Xilinx UG477/DS821 legacy docs exist under `openPCIE/0.doc/`). Phase 1 requires
citing PG213 page+table for every golden constant (§4, hard constraint §2.9). **Please provide the
PG213 v1.3 PDF before Phase 1**, or approve substituting the PCIe Base Spec + Xilinx UG477 for the
descriptor field tables (UG477 is the 7-series predecessor to PG213 with the same RQ/RC descriptor
shapes).

---

## Stop-and-report triggers — status
*(as of 2026-07-27, pre-merge; **re-evaluated 2026-07-28** in the right-hand column)*

| Trigger | Fired? (pre-merge `f3160d0`) | **Re-evaluated post-merge `50542d1`** |
|---|---|---|
| Wrapper needs `src/tlp/` change | **No** — landing surface sufficient | **No** — surface still sufficient |
| §4.3 = R3 (byte-granular config impossible) | **No** — resolves to R1, expressible | ~~⛔ PARTIALLY YES~~ → ✅ **No** (corrected 2026-07-28, `d5a4253`): R1 holds on **all** paths |
| T5 (single-byte config write) blocked | **No** — achievable (§B.3) | ~~⛔ YES — BLOCKED~~ → ✅ **No — REOPEN** (corrected 2026-07-28, `d5a4253`) |
| TL can't express RC bit 30 / split accounting | **No** — `result_last_o` + tracker (§D.3) | **No** — confirmed intact (§D.3) |
| Pre-existing test red | **No** — 78/78 + conformance 1/1 | **No** — 17 targets / 81 tests + conformance 1/1 |
| New Verilator warning class | N/A (no RTL yet) | N/A (no RTL yet) |
| Commit 0/1 unstaged / tree unexpected | **No** — committed, clean | **No** — clean apart from this file |

**No RTL written. Awaiting go/no-go for Phase 1.**

---

## Post-merge re-verification (HEAD b0d3971) — 🛑 GATE 1 FAILED (2026-07-27)

> ### 🗄️ SUPERSEDED 2026-07-28 — historical record only, do NOT act on this section.
> This appendix was written at HEAD `b0d3971`, **before** the six reconciliation fixes
> (`be34ef9`, `7d471e0`, `0277358`, `53de97f`, `abaa3ad`, `50542d1`) landed. All seven regressions
> it lists are **fixed**; the suite is green at 17 targets / 81 tests, and `verilate_tlp_conf_datalast`
> was re-run 5/5 PASS on 2026-07-28 as a spot check. Its four root causes (RC1–RC4) are retained
> because they explain *why* the merged RTL looks the way it does, and RC1/RC3/RC4 are cited by the
> Phase-B findings in **§P/§Q**. **GATE 1 is now PASSED and Phase B was performed** — see §P.

Re-run of the full 17-target TL suite after Joy's PR#3 merge (`b0d3971`) into
`kourosh/dev`. **The pre-existing TL suite is NOT green.** Per the brief's GATE 1,
Phase B (the B1–B8 re-anchor) is **BLOCKED** and was not performed — the recon's
file:line anchors below (§A–§F) remain **UNVERIFIED against the merged tree** until the
regressions are reconciled. Read-only audit; no RTL touched, no commit.

Tree state at re-verification: HEAD `b0d3971`, `git status` clean, ahead of
`origin/kourosh/dev` by 3.

### Regression table (pre-merge = recon §G, post-merge = this run, Verilator 5.050 / cocotb 1.9.2)

| Target | Pre | Post | Verdict |
|---|---|---|---|
| verilate_tlp_requester | 2/2 | **3/3 PASS** | green (+1 test) |
| verilate_tlp_request_tracker | 2/2 | **2/2 PASS** | green |
| verilate_tlp_parser | 3/3 | **3/3 PASS** | green |
| verilate_tlp_generator | 3/3 | **3/3 PASS** | green |
| verilate_tlp_completion_gen | 1/1 | **2/2 PASS** | green (+1 test) |
| verilate_tlp_comb | 3/3 | **3/3 PASS** | green |
| verilate_tlp_payload_formatter | 2/2 | **2/2 PASS** | green |
| verilate_tlp_compile | 3/3 | **4/4 PASS** | green (+1 test) |
| verilate_tlp_conf_generator | 2/2 | **2/2 PASS** | green |
| verilate_tlp_conf_formatter | 4/4 | **4/4 PASS** | green |
| verilate_tlp_cfg0_spine | 2/2 | **0/2 FAIL** | ⛔ REGRESSION (0 packets) |
| verilate_tlp_conf_requester | 10/10 | **0/10 FAIL** | ⛔ REGRESSION (0 packets) |
| verilate_tlp_conf_tracker | 7/7 | **6/7 FAIL** | ⛔ REGRESSION |
| verilate_tlp_conf_parser | 12/12 | **ELAB BREAK** | ⛔ REGRESSION (structural) |
| verilate_tlp_conf_completion | 6/6 | **HANG @5/6** | ⛔ REGRESSION (timeout) |
| verilate_tlp_conf_classifier | 11/11 | **10/11 FAIL** | ⛔ REGRESSION |
| verilate_tlp_conf_datalast | 5/5 | **3/5 FAIL** | ⛔ REGRESSION (B8 contract reverted) |

**10 targets green, 7 targets regressed.** All 17 are Kourosh-owned pre-existing targets
(`tb/tlp/tb_tlp.core` @ 763e7ee/f3160d0); none are "new (Joy)". No new trusted baseline
exists — the suite is red. Note: Joy's new modules (credit_manager, ecrc, vc_buffer,
end_to_end) have **Makefile** targets only (`0e88ac1`), no FuseSoC `verilate_*` targets,
so they are not in this suite.

### Root causes (4 distinct, all traced to the merged RTL vs unchanged pre-merge tests)

**RC1 — `tlp_layer` added flow-control/credit gating; layer-level tests don't init FC → 0 packets.**
`tlp_layer.sv:249`: `vc_packet_ready = credit_request_ready && transmit_enable_i && link_up_i`,
and `:438` gates `request_valid_i` on the same. The merged layer gained new inputs
`fc_initialized_i` + `fc_ph_i/fc_pd_i/...` (`tlp_layer.sv:31-38`) feeding `tlp_credit_manager`.
`test_tlp_conf_requester.py:112-113` and `test_tlp_cfg0_spine.py:66-67` drive `link_up_i=1`
+ `transmit_enable_i=1` (which sufficed at recon time) but **never initialize flow-control
credits** — so `credit_request_ready` stays 0 and no TLP is ever emitted.
- `cfg0_spine`: `AssertionError: CfgRd0 must be a 3-DW header, got 0 beats: []`
- `conf_requester`: `AssertionError: expected 1 packet, got []` (memrd_3dw_aligned, all 10)
- `conf_tracker`: `tag_exhaustion` — `AssertionError: read 6 should be accepted` (requests back
  up behind the credit-blocked TX, `command_ready_o` deasserts). Same family.
- `conf_completion`: 4/6 pass then **hangs on `unaligned_length` (5/6)** — `tb_tlp_completion_control.sv`
  was touched by the merge (+43 lines); an await on completion output never resolves. (timeout 700 s)

**RC2 — `tlp_parser` gained 3 output ports; the pre-merge wrapper doesn't wire them → elaboration break.**
Merged `tlp_parser.sv:30-32` adds `error_valid_o`, `error_code_o` (`tlp_error_e`), `ecrc_error_o`.
`tb_tlp_conf_parser.sv:70` (unchanged since 763e7ee) instantiates `tlp_parser` without them →
Verilator `%Warning-PINMISSING` ×3, promoted to `%Error` by the lint waiver →
`Failed to build`. **This is an elaboration (structural) break, higher-priority than an
assertion miss.** (Note: `tb_tlp_parser.sv` — used by the passing `verilate_tlp_parser` target —
*was* updated by the merge, +6 lines; only the conf-parser wrapper was missed.)

**RC3 — the `command_data_last` end-of-request fix (17adf72) was REVERTED by taking origin/main's `tlp_requester`.**
Merged `tlp_requester.sv:148`: `expected_data_last = segment_sent_r + accepted_bytes >= segment_bytes_r`
— **per-segment**, with no `remaining_r <= segment_bytes_r` guard. `:220-223`:
`if (command_data_last_i != expected_data_last) command_error_valid_o <= 1'b1` (code
`TLP_ERR_LOCAL_PAYLOAD`). On a valid multi-segment write, at every non-final segment boundary
`expected_data_last=1` while the host's `command_data_last_i=0` → **spurious error**. This is
exactly the pre-17adf72 behaviour the fix removed (recon §A.2 claimed the fix compared against
`request_last = expected_data_last && (remaining_r <= segment_bytes_r)` — **that guard is gone**).
- `conf_datalast`: `valid_stream_two_segments_spurious_error` + `valid_stream_three_segments_generalizes`
  fail — `AssertionError: valid multi-segment write must not error … got 1`. The early-`last`
  violation test (test 2) still passes, so the *contract* is intact but the *end-of-request vs
  per-segment* comparison regressed. **This independently trips stop-trigger #3 (B8 CHANGED).**
  (`tb_tlp_requester.sv` *was* correctly re-wired to `command_error_valid_o`/`command_error_code_o`,
  so `sink.errors` reads the real signal — the failure is a genuine RTL behaviour regression.)

**RC4 — `tlp_classifier` now misclassifies a 64-bit Memory Read as UNSUPPORTED.**
`conf_classifier` `mem64_read_non_posted`: expected `cls==NON_POSTED(1)`, got `cls==3(UNSUPPORTED)`,
`mem==0`. The `tlp_class_e` enum order is unchanged (`tlp_pkg.sv:30-32`: POSTED/NON_POSTED/COMPLETION),
so this is a behavioural change in the classifier/decoder logic on 4-DW mem reads, not an
encoding remap. (1 of 11 tests; the other 10 pass.)

### `command_error_o` → split rename impact (report item 6)
The RTL now drives `command_error_valid_o` + `command_error_code_o` (`tlp_error_e`), not the
single `command_error_o`. Places still referencing the old name:
- **`RECON_commit2a.md:61,72`** (§A.1 port table + §A.2) — stale; must be updated to the split pair.
- **`docs/predictions/SPEC_PREDICTIONS_RQ_RC.md`** — §F "Early `tlast`" row + any "`command_error_o` pulse count == 0"
  T-plan assertion for Commit 2a-0 must map to `command_error_valid_o`.
- **`tb/tlp/test_tlp_conf_datalast.py`** (docstrings only, ~20 refs) — cosmetic; the code already
  reads the new signal via the updated `tb_tlp_requester.sv:80-81`.
- **`src/tlp/tlp_requester.sv:150`** — stale comment (Joy-owned, do not edit).

### Disposition
Phase B (B1–B8) **not performed** — GATE 1 blocks it. B8 is pre-emptively **CHANGED (regression, RC3)**.
The §A–§F anchors above are unverified against `b0d3971`. Next action is the operator's:
reconcile the 4 root causes (init FC in the layer-level tests + wire the parser wrapper's 3 new
pins = test-side; restore the end-of-request `last` comparison + investigate the mem64 classifier
= RTL-side, Joy-owned) and re-run the gate before any Commit 2a RTL.

*(↑ superseded — all four root causes were reconciled; see the banner at the top of this section.)*

---

# §P. Phase-B re-anchor against the merged tree — status table (2026-07-28)

**Tree:** `kourosh/dev` @ `50542d1` (merge `b0d3971` + six fixes). **Mode:** READ-ONLY.
`src/` and `tb/` unmodified this session; the only writes are to this file and
`docs/predictions/SPEC_PREDICTIONS_RQ_RC.md`. Evidence method: every finding re-opened in the *current* file and
quoted; B1 additionally verified by direct Verilator simulation of the merged `tlp_requester`
from a scratchpad-only harness.

| # | Finding | Status | Current evidence |
|---|---|---|---|
| **B1.1** | BEs computed unconditionally from `address_r[1:0]` + segment length, no config special case | **MOVED** | `tlp_requester.sv:129-130` (was `:147-148`); fns `tlp_pkg.sv:165-193` (was `:93-116`) |
| **B1.2** | Generator masks the emitted config DW to `{address[31:2],2'b00}` | **MOVED** | `tlp_generator.sv:81-82` (was `:70-71`); 4DW DW3 `:85` (was `:109`), emitted via `axis_dw3` `:130` |
| **B1.3** | Payload realigned by the same offset | **MOVED** | `tlp_generator.sv:98-100` (was `:79`) — now a CPL/non-CPL ternary; non-CPL arm = `address[1:0]`, unchanged for requests. Formatter hookup `:211` (was `:179`) |
| **B1 ⭐ consequence** | *Byte-granular config access is expressible* | ~~⛔ INVALIDATED~~ → ✅ **CONFIRMED** (corrected 2026-07-28) | ~~Merge-era guard `:183-188` rejected CFG/IO with `byte_count != 4`.~~ **`d5a4253` relaxed it to `byte_count <= 4 − address[1:0]` (`tlp_requester.sv:183-199`); `67220b5` locked the admission matrix.** `CFG_WRITE0 0x19 bc=1` is admitted → 1 TLP, `first_be=0010 len=1`. §B.3/§B.3a |
| **B1 (memory path)** | R1 byte-offset semantics on Mem Rd/Wr | **CONFIRMED** | Simulated `MEM_WRITE 0x1019 bc=1` → `first_be=0010 len_dw=1`; `0x101a bc=2` → `1100`. §B.3a |
| **B2** | `tlp_cmd_e` members/encodings; no CFG1 command | **CONFIRMED** (verbatim) | `tlp_pkg.sv:43-50`, `TLP_TYPE_CFG1` `:21`. Diff proves **append-only**: no member inserted or reordered in any pre-existing enum. §A.3 |
| **B3** | Command port + launch handshake; `command_byte_count_i` authoritative | **MOVED** (+2 port changes, +8 new layer inputs) | Ports `tlp_requester.sv:15-31,49-50` / `tlp_layer.sv:54-71`. `command_digest_valid_i`+`command_digest_i` → **`command_ecrc_enable_i`**; `command_error_o` → **`command_error_valid_o`+`command_error_code_o`**. New TX gating inputs `tlp_layer.sv:19-20,31-38`. §A.1–A.2 |
| **B4** | `DATA_WIDTH=32`/`KEEP_WIDTH=4`, keep popcount, partial final beat, combinational ready | **MOVED** (semantics unchanged) | `:5-6`, `:107-109`, `:226`, `:159`. **Gearbox contract unchanged.** §A.4–A.5 |
| **B5 ⭐** | Both RC surfaces present (full parsed header + DW-serial payload; tracker digest) | **MOVED** (+1 new output) | `tlp_layer.sv:108-115,195-197,230-235` and `:117-133`. New `completion_error_code_o` `:132`. Lower Address mechanism (`command_context_i` echo) **intact** — RC6 changed a different input. §D.1, §D.4 |
| **B6** | RC bit 30 = `result_last_o`; split-completion byte accounting | **CONFIRMED** (anchors moved) | `tlp_request_tracker.sv:140-142` (was `:122-124`); accounting `:143-154`; `completion_payload_bytes` `tlp_layer.sv:219-224`. RC5/RC6 added a *pre-filter* (`:127-135`), did not alter bit-30 logic. **No tag-reuse risk.** §D.3 |
| **B7** | Core-managed tags | **CONFIRMED** (anchors moved) | Allocator `tlp_request_tracker.sv:55-65` (was `:52-62`); `REQ_TAG` consume `tlp_requester.sv:138,206-209`. No move to client-managed tags. §E |
| **B8** | `command_data_last` = end-of-whole-request contract | **CONFIRMED on the merged shape** | `request_last` restored `tlp_requester.sv:155`; guard `:227-231` → `command_error_valid_o` + **`TLP_ERR_LOCAL_PAYLOAD`**; recovery to `REQ_IDLE` `:232-236`. `verilate_tlp_conf_datalast` re-run **5/5 PASS** (2026-07-28). §A.2, §A.4 |
| **B9** | What the merge *added* that Commit 2a must account for | **NEW** | See **§Q** |

## Design impact on Commit 2a

- **2a-0 (gearboxes) is SAFE TO BUILD AS SPECIFIED.** ✅ Everything the gearbox spec rests on
  re-verified unchanged: `DATA_WIDTH=32`/`KEEP_WIDTH=4`, per-beat `keep` popcount accounting,
  partial-final-beat handling, combinational `command_data_ready_o`, and the end-of-request
  `command_data_last` contract. The gearboxes do not touch config-request semantics, so the B1
  question never reached them. **No change to the 2a-0 brief is required.** *(Built at `ccb2a52`.)*
- ~~**RQ wrapper (2a-i): one real design change.** Config/IO command construction must be
  `byte_count = 4` + `address[1:0] = 2'b00` (whole aligned DW)…~~
  ✅ **WITHDRAWN 2026-07-28 (`d5a4253`). No design change.** Config/IO command construction uses
  the **same** byte-offset derivation as memory (`address[1:0] = off`, `byte_count` from the BE
  popcounts). The wrapper's local check is the **fit** condition
  `is_cfg_or_io && byte_count > (4 − off)` ⇒ reject — mirroring `tlp_requester.sv:183-199` so the
  TL's `TLP_ERR_BAD_LENGTH` is never the first line of defence. **T5 is back in Commit 2a's scope.**
- **Commit 2b (bus-number assignment):** ~~whole-DW read-modify-write of config DW `0x18`~~ →
  ✅ a **direct single-byte write** at offset `0x19` (`first_be=0010`, `N=1`). No operator decision
  outstanding.
- **RC wrapper (2a-ii): no design change.** All descriptor sources hold; add `completion_error_code_o`
  to the error surface, and keep the split-read Lower Address gap documented (§D.4).
- **Port renames to propagate everywhere**: `command_error_o` → `command_error_valid_o` /
  `command_error_code_o`; `command_digest_valid_i`/`command_digest_i` → `command_ecrc_enable_i`.

---

# §Q. B9 — new constraints the original brief did not know about (2026-07-28)

### Q.1 `tlp_validator.sv` (NEW, 61 lines) — the §2.2.4.1 rule set
**It is instantiated on the RECEIVE path only** — `tlp_parser.sv:299` and `tlp_classifier.sv:68`
(the classifier's copy runs on `parsed_header`, i.e. also RX). **There is no validator anywhere on
the requester → control → generator → vc_buffer transmit path.** So the RQ wrapper cannot be
*caught* locally by it; but the link partner (and our own loopback / `test_tlp_end_to_end`) applies
the same rules, so the wrapper must satisfy them **by construction**. Rules, in order
(`tlp_validator.sv:117-151`):

| Rule | Line | Error | Can the RQ wrapper trip it? |
|---|---|---|---|
| `fmt` must be one of the four request/completion encodings | `:117-122` | `BAD_FMT_TYPE` | No — requester derives `fmt` itself (`tlp_requester.sv:112-122`) |
| `tlp_type` ∈ {MEM, IO, CFG0, CFG1, CPL, CPL_LOCK} | `:123-129` | `BAD_FMT_TYPE` | No — requester emits only MEM/IO/CFG0 |
| Config/IO/completion must **not** be 4DW | `:130-132` | `BAD_FMT_TYPE` | No — requester forces 3DW for CFG/IO (`:118`, `:121`) |
| 4DW memory with `address[63:32] == 0` | `:133-136` | `BAD_ADDRESS_FORMAT` | No — fmt is chosen *from* `address[63:32]` (`:113-114`). (This is the RC4 case.) |
| **Config/IO `length_dw` must be exactly 1** | `:137` | `BAD_LENGTH` | ~~⚠️ YES — via the `bc=4` + nonzero-offset split~~ → ✅ **No** (2026-07-28, `d5a4253`): every admitted config/IO shape has `byte_count + address[1:0] <= 4`, so `length_dw == 1` **by construction** (`tlp_requester.sv:125-126`) and the split is unreachable. The wrapper's fit check keeps it that way. |
| non-completion `length_dw == 0`; `has_data && length_dw == 0`; `length_dw > 1024` | `:137-141` | `BAD_LENGTH` | No — `length_dw` floors at 1 (`tlp_requester.sv:125-126`) and segmentation caps well under 1024 |
| **`length_dw == 1` ⇒ `last_be` must be 0** | `:144-146` | `BAD_BYTE_ENABLE` | No — `tlp_last_be` returns 0 whenever `offset+len <= 4` (`tlp_pkg.sv:188-189`) |
| **`length_dw > 1` ⇒ `first_be != 0` AND `last_be != 0`** | `:147-150` | `BAD_BYTE_ENABLE` | ⚠️ **Watch** — holds for contiguous BEs, which is all the wrapper may emit anyway (§B.4) |

**⇒ New §4.5 wrapper checks:** ~~reject `is_cfg_or_io && (byte_count != 4 || address[1:0] != 0)`~~
→ ✅ **corrected 2026-07-28 (`d5a4253`):** reject `is_cfg_or_io && byte_count > (4 − off)`;
keep the existing contiguous-BE and `DwordCount ∈ [1,1024]` checks.

### Q.2 `tlp_credit_manager.sv` + flow-control gating — what the RQ path must satisfy to transmit
TX is gated at `tlp_layer.sv:249`: `vc_packet_ready = credit_request_ready && transmit_enable_i && link_up_i`,
with `credit_request_ready` from `tlp_credit_manager.sv:53-54`:
`fc_initialized_i && selected_header_available && selected_data_available`. Credits **load only on
`fc_update_valid_i`** (`:76-83`) and start at 0 (`:66-72`).

**The RQ wrapper's environment must drive, at the `tlp_layer` boundary:** `link_up_i = 1`,
`transmit_enable_i = 1`, `fc_initialized_i = 1`, and at least one `fc_update_valid_i` pulse
carrying non-zero `fc_ph_i/fc_pd_i/fc_nph_i/fc_npd_i/fc_cplh_i/fc_cpld_i`. **Leaving these at 0
produces zero TLPs and no error** — that was regression RC1, and it is exactly the trap a new
`tb/rc/` harness will fall into. Every Commit-2a testbench that instantiates `tlp_layer` must
initialise FC (`tb/tlp/test_tlp_conf_requester.py:112-119` is the reference pattern).
Note `link_up_i` also feeds `layer_reset` (`tlp_layer.sv:194`) — dropping it resets the whole TL.
Credit class is picked per packet at `tlp_layer.sv:262-272` (MemWr → POSTED, CPL → COMPLETION,
everything else including **all config requests** → NON_POSTED), so config enumeration consumes
**NPH/NPD** credit.

### Q.3 `tlp_ecrc.sv` — bypassable; and a spec divergence (report only)
- **Bypassable, and bypassed by default.** `command_ecrc_enable_i` (`tlp_requester.sv:25`) →
  `ecrc_enable_r` (`:198`) → `header_c.digest_present` (`:134`) → the generator's `TX_ECRC` state
  (`tlp_generator.sv:141-145,151-158`). **Drive `command_ecrc_enable_i = 0` and the RQ path is
  ECRC-free** — no extra trailing DW, `m_axis_tlast` lands on the last payload beat (`:138`).
  **The RQ wrapper needs to do nothing about ECRC in Commit 2a beyond tying this pin to 0.**
- ⚠️ **Known §2.7.1 divergence — REPORTED, NOT FIXED.** `tlp_crc32_byte` (`tlp_pkg.sv:135-149`)
  is the standard reflected CRC-32 (poly `0xEDB88320`, init `0xFFFF_FFFF`, final inversion at
  `tlp_ecrc.sv:108`). PCIe ECRC per Base 2.1 §2.7.1 additionally requires the **variant bits**
  (`EP`, and `Type[0]`/`Fmt[0]` handling) to be treated as 1 during computation, which the
  generator does not do — it feeds raw `m_axis_tdata` (`tlp_generator.sv:226`). RX and TX use the
  *same* function so loopback self-consistency holds, but the value would not match a real link
  partner. Out of scope for this session.

### Q.4 `tlp_vc_buffer.sv` / `test_tlp_end_to_end.py` — relevance to RQ/RC
- **`tlp_vc_buffer`**: a store-and-forward packet FIFO between the generator and the DLL
  (`tlp_layer.sv:421-438`), `PACKET_DEPTH = 4` default (`:10`), `MAX_PACKET_WORDS = 1030`
  (`tlp_vc_buffer.sv:9`). Its only effect on the RQ path is **backpressure** (`:53`) — a whole TLP
  is buffered before it is offered for credit. **No interface change for the wrapper**, but it
  means `command_data_ready_o` can stall for a full packet time; the 2a-0 gearbox must not assume
  bounded stall (it already doesn't). `overflow_o` → `vc_overflow_o` (`tlp_layer.sv:130`) is worth
  wiring into the wrapper's error surface.
- **`end_to_end`** (`tb/endpoint/`, `tb/tlp/test_tlp_end_to_end.py`, `src/pcie_endpoint/pcie_endpoint_top.sv`):
  a **new integration level above `tlp_layer`**, not in the 17-target TL suite. Relevant only as
  the eventual place the RQ/RC wrappers get instantiated — **no Commit-2a interface constraint**,
  but note `pcie_endpoint_top.sv` already occupies the `src/pcie_endpoint/` namespace that a future
  wrapper integration would touch.
