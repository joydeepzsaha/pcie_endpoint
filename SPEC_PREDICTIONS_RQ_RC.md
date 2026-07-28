# SPEC_PREDICTIONS_RQ_RC.md — Phase 1 spec predictions for Commit 2a

**Branch:** `kourosh/dev` @ `f3160d0` · **Mode:** documentation only, no RTL, no commit.
Companion to `RECON_commit2a.md`. This is the golden reference the RTL and tbs are checked against.

> 🔁 **RE-ANCHORED 2026-07-28 (Phase B) against `50542d1`** — post Joy PR#3 merge (`b0d3971`) plus
> the six reconciliation fixes. Every RTL `file:line` citation below was written against the
> pre-merge tree and has been re-verified; stale anchors are corrected in place with
> ~~strikethrough~~ → **bold**. **Two substantive changes:**
> 1. ~~⛔ **§D is amended: byte-granular CONFIG access is no longer expressible**~~ →
>    ✅ **RETRACTED — see the correction block below.**
> 2. Two command ports were renamed by the merge: `command_error_o` →
>    `command_error_valid_o` + `command_error_code_o` (`tlp_requester.sv:49-50`), and
>    `command_digest_valid_i`/`command_digest_i` → `command_ecrc_enable_i` (`:25`).
>
> Full status table and the new §4.5 constraints: `RECON_commit2a.md` **§P** and **§Q**.
> **PG213-sourced constants are untouched by this pass** — they still await the PDF.

> ✅ **CORRECTION 2026-07-28 (later the same day, post-`d5a4253`) — read this before anything else.**
> Change 1 above was written against the merge-era admission guard. **`d5a4253` ("tlp_requester:
> admit any config/IO request that fits inside one DW") removed it**; `67220b5` locked the
> replacement admission matrix in the TL testbench. The guard (`tlp_requester.sv:183-199`) now
> admits any config/IO request satisfying **`byte_count <= 4 − address[1:0]`** — the spec
> constrains the config *Length* field, not the byte enables (PCIe Base 2.1 §2.2.7).
>
> ⇒ **§D's R1 byte-offset mapping applies to memory, I/O AND config alike. There is no config
> special case. T5 is REOPEN and back in the Commit-2a test plan; T5′ is withdrawn.** The RQ
> wrapper's config/IO check is the **fit** condition `byte_count > (4 − off)` ⇒ reject.
> ⛔ **Do not code a `byte_count != 4` or `first_be != 4'hF` check.**
> Sections corrected: **§A (rows + T5), §B (memory/IO split), §D header, §D.2, §D.3, §D.3a, §D.4,
> §F table, §H/§verdict.** Struck-through merge-era text is retained for the record.

### Provenance (read before trusting any constant)
Descriptor field maps are transcribed from **PG213 v1.3 (20 Nov 2025), Chapter 4**, via the
**off-server addendum** the PDF is not on `vlsi031`. Every constant below is cited as
**`PG213 v1.3, Table N (via addendum, transcribed off-server)`** — secondary transcription, not a
primary PDF read. **When the PDF reaches the server, re-verify every constant and upgrade the
citation in place, recording the verification date here.** PCIe-level facts (TLP header layout, CPL
rules) cite **PCIe Base Spec Rev 2.1** (on disk, `openPCIE/0.doc/`). **UG477 is deliberately NOT
cited** — the 7-series block predates the descriptor-based RQ/RC interface and is not a substitute.

Corroboration: PG213 documents each descriptor twice (64/128/256-bit ch.4 ~pp.179–213 and the
512-bit twin ~pp.264–297); the two field maps agree, which is weak-but-real corroboration.

---

## A. RQ Configuration-Request descriptor → TL `command_*` (CFG0)
**Source:** PG213 v1.3, Fig 42 / Table 61 (via addendum). RQ is 16 B, one 128-bit beat (beat 0).
BEs are in `s_axis_rq_tuser` (§D), not the descriptor.

| Desc bits | Field | → maps to | Evidence |
|---|---|---|---|
| `[7:2]` | Reg Number | `command_address[7:2]` | Config-DW layout [[tlp-cfg0-spine]]; ~~`tlp_generator.sv:70-71`~~ → **`tlp_generator.sv:81-82`** emits `{addr[31:2],2'b00}` |
| `[11:8]` | Ext Reg Number | `command_address[11:8]` | same |
| `[74:64]` | Dword Count | **must be `11'd1`** → else reject (§F) | config = 1 DW; `command_limit`=4 B for CFG (~~`tlp_requester.sv:95-97`~~ → **`:76-78`**) |
| `[78:75]` | Request Type | decode → `command_i` (§C) | `1000`→`TLP_CMD_CFG_READ0`, `1010`→`TLP_CMD_CFG_WRITE0` (`tlp_pkg.sv:46-47`) ✔ unchanged |
| `[79]` | Poisoned | **must be 0 for CfgWr** → else reject | PG213: poison unsupported on Cfg writes |
| `[119:104]` | **Completer ID (target BDF)** | `command_address[31:16]` | Bus`[119:112]`→`addr[31:24]`, Dev`[111:107]`→`addr[23:19]`, Fn`[106:104]`→`addr[18:16]` |
| `[120]` | Requester ID Enable | root-port mode = 1; RC uses its own `requester_id_i` | ~~`tlp_requester.sv:145`~~ → **`:127`** forces `requester_id = requester_id_i` |
| `[123:121]` | TC | `command_tc_i` | ~~`tlp_requester.sv:142`~~ → **`:123`** |
| `[126:124]` | Attr | `command_attr_i` | ~~`tlp_requester.sv:143`~~ → **`:124`** |
| `[103:96]` | Tag | **ignored** (core-managed, §E/Recon Q15) → `pcie_rq_tag`/`pcie_rq_tag_vld` exposed instead | tracker allocates ~~`tlp_request_tracker.sv:52-62`~~ → **`:55-65`** |
| `[127]` | Force ECRC | ignored (ECRC out of scope; ~~`command_digest_valid_i=0`~~ → **`command_ecrc_enable_i = 0`**, `tlp_requester.sv:25`) | brief §1; RECON §Q.3 |
| `command_address[15:12]` | (reserved) | `4'h0` | config DW reserved field |
| `command_address[1:0]` (byte offset) — **from `first_be` (§D)** | ~~⛔ must be `2'b00` for CFG/IO~~ → ✅ **byte offset, same as memory** | **RESTORED 2026-07-28 (`d5a4253`)** | `tlp_requester.sv:183-199` admits CFG/IO whenever `byte_count <= 4 − address[1:0]`; the split shape is now rejected at admission, not emitted |
| — | ~~⛔ `command_byte_count_i` must be exactly `13'd4` for CFG/IO~~ → ✅ **`byte_count <= 4 − off`** | **CORRECTED 2026-07-28 (`d5a4253`)** | `tlp_requester.sv:183-199`, `TLP_ERR_BAD_LENGTH` only outside that range |

**Predicted on-wire goldens (RTL-anchored, from ~~`tlp_generator.sv:49-71`~~ → **`tlp_generator.sv:60-85`**):**
- **T3 — CfgRd0 DW0 = `0x01000004`.** `fmt=000`(3DW-no-data)`, type=00100`(CFG0) → `dw0[7:0]=0x04`;
  `length_dw=1`→`dw0[31:24]=0x01`. **Unchanged from Commit-1.** ✔ re-verified: `dw0` assembly
  `tlp_generator.sv:62-73` is byte-identical post-merge.
- **T4 — CfgWr0 DW0 = `0x01000044`.** `fmt=010`(3DW-data) → `dw0[7:0]=0x44`; `length=1` → `0x01000044`. ✔
- **DW1 = `{requester_id[15:0], tag[7:0], last_be[3:0], first_be[3:0]}`** (~~`:69`~~ → **`tlp_generator.sv:80`**).
  ⚠️ emitted as `axis_dw1` (`:120`), which byte-swaps when `PCIE_WIRE_ORDER=1` (`:9`, `:89-93`).
  **`tlp_layer` defaults it to 0** (`tlp_layer.sv:11`) — assert that in the T-plan rather than assuming it.
- **DW2 (config) = `{command_address[31:2], 2'b00}`** (~~`:70-71`~~ → **`tlp_generator.sv:81-82`**).
- ✅ **T5 — byte-granular CfgWr0 at offset `0x19`** (**REINSTATED 2026-07-28, `d5a4253`**):
  DW0=`0x01000044`, DW1 low nibble `first_be=0x2` and `last_be=0x0`, DW2 = the config DW with
  `[1:0]=00`, payload byte in lane 1, **exactly one TLP** (no split). (Derivation in §D.3.)
  > ~~**T5 IS DEAD (2026-07-28).** The TL rejects the command before any TLP is generated
  > (`TLP_ERR_BAD_LENGTH`, 0 packets — simulated, RECON §B.3a). The only valid config golden is
  > the aligned whole-DW form `byte_count=4`, `address[1:0]=00`. **Replacement test (T5′):**
  > assert the wrapper *rejects* a byte-granular config descriptor.~~
  > **Retracted:** the guard was relaxed to `byte_count <= 4 − address[1:0]`. **T5′ is withdrawn**
  > — a byte-granular config descriptor is legal input and must be *forwarded*, not rejected.
  > What the wrapper still rejects is only the **misfit** case, `byte_count > 4 − off` (§F).

## B. RQ Memory/IO-Request descriptor → `command_*`
**Source:** PG213 v1.3, Fig 41 / Table 60 (via addendum).

| Desc bits | Field | → maps to | Note |
|---|---|---|---|
| `[1:0]` | Address Type (AT) | **must be `2'b00`** (untranslated) → else reject | ATS out of scope |
| `[63:2]` | Address | `command_address[63:2]` | `command_address[1:0]` = byte offset from BE (§D) |
| `[74:64]` | Dword Count | → `command_byte_count_i` (with BEs, §D); reject `>1024` (§F) | |
| `[78:75]` | Request Type | decode (§C): `0000/0001/0010/0011` | Mem/IO Rd/Wr |
| `[79]` | Poisoned | pass to `command_*`? → **drive 0** this commit | poison origination out of scope |
| `[103:96]` Tag / `[126:124]` Attr / `[123:121]` TC | as §A | |

`command_i` selects 3DW vs 4DW automatically from `address_r[63:32]` (~~`tlp_requester.sv:131-133`~~ →
**`tlp_requester.sv:112-114`**) — the wrapper does not choose fmt. ✔ **CONFIRMED.** This is also
what makes the validator's `BAD_ADDRESS_FORMAT` rule (`tlp_validator.sv:133-136`) untrippable from
the RQ path — the fmt is *derived from* the address, never supplied independently.

~~⚠️ **Memory/IO split 2026-07-28:** the R1 byte-offset mapping in §D applies to `TLP_CMD_MEM_READ`
and `TLP_CMD_MEM_WRITE` only; `TLP_CMD_IO_READ`/`TLP_CMD_IO_WRITE` are subject to the same
`byte_count == 4` admission guard as config and must be driven as aligned whole-DW accesses.~~
✅ **WITHDRAWN 2026-07-28 (`d5a4253`).** There is no memory/IO split. The R1 byte-offset mapping
applies to **every** command. I/O (like config) additionally has to *fit* in the addressed DW —
`byte_count <= 4 − off` (`tlp_requester.sv:183-199`) — but within that it is byte-granular.

## C. Request Type decode (`desc[78:75]`) — map vs reject
**Source:** PG213 v1.3, Table 57 (via addendum).

| Enc | Type | Commit 2a | `command_i` |
|---|---|---|---|
| `0000` | Memory Read | **map** | `TLP_CMD_MEM_READ` |
| `0001` | Memory Write | **map** | `TLP_CMD_MEM_WRITE` |
| `0010` | I/O Read | **map** | `TLP_CMD_IO_READ` |
| `0011` | I/O Write | **map** | `TLP_CMD_IO_WRITE` |
| `1000` | **Type 0 Config Read** | **map (primary path)** | `TLP_CMD_CFG_READ0` |
| `1010` | **Type 0 Config Write** | **map (primary path)** | `TLP_CMD_CFG_WRITE0` |
| `1001`/`1011` | Type 1 Config Rd/Wr | **REJECT** → `rq_protocol_error_o` | no `tlp_cmd_e` exists (`tlp_pkg.sv:43-50`) — Commit 3 |
| `0100`–`0111` | Atomics / Locked Read | **REJECT** | no command path |
| `1100`–`1111` | Messages / ATS / Reserved | **REJECT** | no command path |

All rejects: `rq_protocol_error_o` + `$warning`, **no TLP emitted**, FSM → idle (brief §4.5).

## D. ⭐ Address + BE mapping — **R1 (byte-offset semantics)** — ✅ **ALL PATHS** (correction 2026-07-28)

> ~~**Scope correction (Phase B): MEMORY PATH ONLY.** The merged requester rejects CFG0/IO commands
> whose `command_byte_count_i != 4` (`tlp_requester.sv:183-188`), so the byte-offset mapping can no
> longer be used for config or I/O. D.3 (the T5 worked example) is consequently INVALIDATED.~~
>
> ✅ **That scope correction is RETRACTED (`d5a4253`, same day).** R1's three structural premises
> (D.1) are true and the D.2 derivation is correct for **memory, I/O and config alike**. The one
> extra rule for config/I/O is a *fit* rule, not an alignment rule: the request must lie inside
> the addressed DW (`byte_count <= 4 − off`, `tlp_requester.sv:183-199`). **D.3 is reinstated;
> D.3a is superseded.**

### D.1 Why there is no collision (record this reasoning) — **CONFIRMED, anchors MOVED**
`address_r[1:0]` feeds **both** `tlp_first_be(address_r[1:0], segment_bytes_r)`
(~~`tlp_requester.sv:147-148`~~ → **`:129-130`**) **and** `header_c.address` (~~`:149`~~ → **`:131`**).
For config there is **no on-wire conflict** because:
1. The register number lives in `command_address[7:2]`, the byte offset in `[1:0]` — **disjoint
   fields**.
2. The generator **masks the emitted config DW** to `{address[31:2], 2'b00}`
   (~~`tlp_generator.sv:70-71`, and the 4DW DW3 path `:109`~~ → **`tlp_generator.sv:81-82`, 4DW DW3
   path `:85` emitted via `axis_dw3` `:130`**), so the byte offset never reaches the
   wire as part of the address.
3. The payload is realigned by the **same** offset: `payload_offset = header_r.address[1:0]`
   (~~`tlp_generator.sv:79`, feeding the formatter `:179`~~ → **`tlp_generator.sv:98-100`**, now a
   CPL/non-CPL ternary whose non-CPL arm is `header_r.address[1:0]`; **feeding the formatter's
   `start_offset_i` at `:211`** → `tlp_payload_formatter.sv:53`).

⇒ Commit-1's "`command_address[1:0] = 2'b00`" was the DW-aligned special case (`first_be=1111`),
not a hard constraint. **v1's §4.3 (pin `[1:0]=00`) is dead** — ~~*for memory*; for config/IO it
turns out to be the only legal form after all~~ ✅ **for every command type** (correction
2026-07-28, `d5a4253`; see D.3a).

### D.2 The wrapper's derivation — ✅ **all command types** (corrected 2026-07-28)
Let `off = position of the least-significant set bit of first_be` (0/1/2/3), and for a request
spanning `DwordCount` DWs:

```
command_address[63:2] = desc address bits (mem/IO: desc[63:2]; config: BDF + ExtReg + Reg, §A)
command_address[1:0]  = off                                   // byte offset from first_be
DwordCount == 1:  command_byte_count = popcount(first_be)      // last_be must be 0
DwordCount == 2:  command_byte_count = popcount(first_be) + popcount(last_be)
DwordCount >= 3:  command_byte_count = popcount(first_be) + (DwordCount-2)*4 + popcount(last_be)
```
*(The `DwordCount == 1` case is called out separately because the general formula's `(N-2)*4`
term underflows there; `N == 2` is the general formula with a zero middle term.)*

The requester **re-derives** the BEs internally as `tlp_first_be(off, byte_count)` /
`tlp_last_be(off, byte_count)` (~~`tlp_requester.sv:147-148`~~ → **`:129-130`**), reproducing the
requested `tuser` BEs. **Verified post-merge by simulation** (RECON §B.3a): `MEM_WRITE addr=…19 bc=1`
⇒ `first_be=0010, last_be=0000, length_dw=1`; `addr=…1a bc=2` ⇒ `first_be=1100`.

~~**For CFG0/CFG1/IO the derivation is instead fixed:** `command_address[1:0] = 2'b00` and
`command_byte_count = 13'd4`, mandatory; reject any config/IO descriptor whose BEs are not
`first_be=4'hF, last_be=4'h0`.~~
✅ **WITHDRAWN 2026-07-28 (`d5a4253`).** CFG0/IO use the **same** derivation as above. The only
extra requirement is the DW **fit**:
```
is_cfg_or_io:  reject unless  command_byte_count <= 4 - off     // tlp_requester.sv:183-199
```
which guarantees `length_dw == 1` (`:125-126`) and makes `calculate_segment`'s split (`:93-94`)
unreachable. ⛔ **Do not code `byte_count != 4` or `first_be != 4'hF`** — those would reject
legal, now-admitted requests.

### D.3 T5 worked example (the Commit-2b gate) — ✅ **REINSTATED 2026-07-28 (`d5a4253`)**
Config offset `0x19` (Secondary Bus Number), single byte:
`first_be=4'b0010` ⇒ `off=1`; `DwordCount=1` ⇒ `command_byte_count=popcount(0010)=1`;
`command_address[7:2]=0x06` (`0x18>>2`), `[1:0]=01`.
- Fit check: `1 <= 4 − 1` ✔ **admitted**.
- ⇒ `tlp_first_be(2'b01,13'd1)=4'b0010` (~~`tlp_pkg.sv:100-103`~~ → **`:165-180`**);
  `last_be=4'b0000` (**`:182-193`**, since `off+bc <= 4`); `length_dw=1`
  (~~`tlp_requester.sv:144`~~ → **`:125-126`**); emitted DW2 = reg-DW with `[1:0]=00`;
  payload byte in lane 1; **exactly one TLP**. ✔

### D.3a ~~Current truth: config byte granularity is unreachable~~ — ✅ **SUPERSEDED 2026-07-28 (`d5a4253`)**
~~`tlp_requester.sv:183-188` rejects the command at `REQ_IDLE` (`TLP_ERR_BAD_LENGTH`, **no TLP**)
whenever a CFG/IO command carries `command_byte_count_i != 4`.~~ The guard now reads
`command_byte_count_i > (13'd4 - command_address_i[1:0])` (**`tlp_requester.sv:183-199`**).
Merge-era simulation results, with the current outcome alongside:

| stimulus | ~~merge-era result~~ | **post-`d5a4253`** |
|---|---|---|
| `CFG_WRITE0 addr=0x19 bc=1` | ~~`TLP_ERR_BAD_LENGTH`, 0 TLPs~~ | ✅ **1 TLP**, `first_be=0010 last_be=0000 length_dw=1` |
| `CFG_READ0 addr=0x19 bc=1` / `IO_WRITE addr=0x19 bc=1` | ~~`TLP_ERR_BAD_LENGTH`, 0 TLPs~~ | ✅ **1 TLP** each |
| `CFG_WRITE0 addr=0x19 bc=4` | ~~**2 TLPs** — `first_be=1110 @0x19`, then `first_be=0001 @0x1c` (spec-illegal)~~ | ⛔ **rejected at admission** (`4 > 4−1`) — the illegal split is now unreachable |
| `CFG_WRITE0 addr=0x18 bc=4` | **1 TLP**, `first_be=1111 last_be=0000 length_dw=1` ✔ | unchanged ✔ (one legal form among several, no longer "the only" one) |

**Consequences:** T5 is removed from the Commit-2a plan (replaced by T5′, §A). Commit 2b's
Secondary-Bus-Number write must become a **whole-DW read-modify-write of config DW `0x18`** —
**operator decision.** Full detail and the anchor evidence: `RECON_commit2a.md` §B.3a.

### D.4 BE-consistency check (mandatory) — **CONFIRMED, anchors MOVED + one item extended**
Recompute `tlp_first_be(off, bc)` / `tlp_last_be(off, bc)` and compare to the `tuser` BEs. On
mismatch → `rq_protocol_error_o` + `$warning`, no TLP. This catches:
- **Non-contiguous BEs** (e.g. `first_be=4'b1001`): the functions only build contiguous range masks
  (~~`tlp_pkg.sv:100-103`, `:112-115`~~ → **`tlp_pkg.sv:165-180`, `:182-193`**) → **reject, KNOWN_GAPS.**
  *(The functions were re-implemented for integer-width lint; the mapping is unchanged.)*
- **Zero-length read** (`DwordCount=1, first_be=0`): `off`/`bc` degenerate → **reject, KNOWN_GAPS.**
  ⚠️ **Re-decide in Phase 1:** post-merge, `length_dw` floors at 1 (`tlp_requester.sv:125-126`) and
  the admission guard *permits* `byte_count == 0` for `TLP_CMD_MEM_READ` (`:183`), so a zero-length
  **memory** read is now cleanly expressible. Zero-length CFG/IO remains rejected.
- ~~⛔ **NEW — config/IO with `first_be != 4'hF` or `last_be != 4'h0`** → reject (D.2).~~
  ✅ **WITHDRAWN 2026-07-28 (`d5a4253`).** Byte-granular config/IO BEs are legal. The reject is the
  **fit** condition only: `is_cfg_or_io && byte_count > (4 − off)` (D.2). Note this subsumes the
  `last_be != 0` case for config — any config descriptor with a non-zero `last_be` necessarily
  spans past the addressed DW and fails the fit check.

## E. RC descriptor derivation (12 B / 96 b, `DESC_DW=3`) — **B5: re-verified 2026-07-28, table stands**
**Source:** PG213 v1.3, Fig 56 / Table 65 (via addendum). RC surface = `received_completion_*` +
`result_*` (~~`tlp_layer.sv:97-113`~~ → **`tlp_layer.sv:108-115` + `:117-133`**). Dword-aligned mode → first payload DW immediately after the
3-DW descriptor (the rotation §4.4 / gearbox G5).

**Every source below re-checked against the merged ports — no field lost its source.** ✔

| RC bits | Field | Source | Status |
|---|---|---|---|
| `[11:0]` | Lower Address | `[6:0]`=`received_completion_header_o.lower_address` (~~`parser.sv:174`~~ → **`tlp_parser.sv:188`**); `[11:7]`=**`result_context_o` echo** of request `address[11:7]` | `[6:0]` OK; `[11:7]` via context — **mechanism CONFIRMED intact**, see note ⚑ |
| `[15:12]` | Error Code | derive: `0000` SC · `0001` poisoned · `0010` UR/CA/CRS · `0011` no-data/overrun | derived; **now also informable by `completion_error_code_o`** (`tlp_layer.sv:132`) |
| `[28:16]` | Byte Count | `received_completion_header_o.byte_count` (13 b; CPL carries `[11:0]`, ~~`parser.sv:157`~~ → **`tlp_parser.sv:168`**) | OK — parser maps encoded `0` → **4096** (`:168`) |
| `[29]` | Locked Read Compl. | `0` (no CPL_LOCK path this commit) | const |
| `[30]` | **Request Completed** | **`result_last_o`** (~~`tlp_request_tracker.sv:122-124`~~ → **`:140-142`**) | **OK — B6 CONFIRMED**, accounting `:143-154` unchanged |
| `[31]` | Reserved | `0` | |
| `[42:32]` | Dword Count | `received_completion_header_o.length_dw` (I/O-write CPL→0; zero-len read→1) | OK |
| `[45:43]` | Completion Status | `received_completion_header_o.completion_status` / `result_status_o` (incl. **CRS `010`**) | OK (`tlp_parser.sv:166`) |
| `[46]` | Poisoned | `received_completion_header_o.poisoned` | OK |
| `[63:48]` | Requester ID | `received_completion_header_o.requester_id` | OK |
| `[71:64]` | Tag | `received_completion_header_o.tag` (core-assigned, echoed) | OK |
| `[87:72]` | Completer ID | `received_completion_header_o.completer_id` | OK |
| `[91:89]` | TC | `received_completion_header_o.traffic_class` | OK |
| `[94:92]` | Attr | `received_completion_header_o.attributes` (3 b) | OK |

⚑ **RC6 note (`tlp_layer.sv:353-354`, `tlp_request_tracker.sv:119-120,152-153`).** The merge added
a tracker input `allocate_address_i`, driven **0 for every non-memory request**, which seeds a
per-tag `next_lower_address_r[]`. This is an **internal expectation used to police incoming CPLs**
(`tlp_request_tracker.sv:127-135`), *not* an RC descriptor source, and it is not exposed on any
`tlp_layer` port. **The `command_context_i` echo remains the correct and only mechanism for
Lower Address `[11:7]`.** Side effect worth knowing: a completion whose `lower_address` disagrees
with the tracker's running expectation is now dropped as `unexpected_completion_o` +
`TLP_ERR_COMPLETION_OVERFLOW` rather than reaching `result_*` — **the RC wrapper must surface
`completion_error_code_o`, or such completions vanish silently.**

⚑ **New RC output to wire: `completion_error_code_o`** (`tlp_layer.sv:132`) distinguishes
`TLP_ERR_UNEXPECTED_COMPLETION` (no tag match) from `TLP_ERR_COMPLETION_OVERFLOW` (matched but
failed the consistency pre-filter). Add it to the RC error surface.

⚑ **Payload routing:** the completion payload port is now arbitrated by a registered
`route_completion_r` (`tlp_layer.sv:151,228-246`); `received_completion_data_valid_o` is only
asserted while it is set (`:232`). No wrapper change, but the T-plan should cover a
request-then-completion back-to-back to exercise the arbiter.

### `KNOWN_GAPS` (RC)
1. **Lower Address `[11:7]`** — a CPL header carries only 7 bits; recovered from the
   `command_context_i` echo (stash request `address[11:7]` at launch). This is the *same* mechanism
   PG213's own block uses (its Split Completion Table), one fewer structure. Encode the pack/unpack
   in `pcie_rq_rc_pkg`. For the config-enumeration path (1 DW) it is moot.
2. **Split-read Lower Address on the 2nd+ CPL** — PG213 requires it to be *that completion's* first
   byte, which needs a running byte count, not the stashed request address. **Config completions
   never split**, so this cannot affect enumeration → documented gap, **not solved in Commit 2a**.
3. **IDO attribute bit** and any field absent from a CPL header → `0`, listed here and commented in
   the RTL header. Never fabricated.

## F. §4.5 range / boundary checks (wrapper is the last catch)
**Source:** PG213 v1.3 Table 57/60/61 + "Requester …Operation" (via addendum); PCIe Base Spec 2.1.
All rejects: `rq_protocol_error_o` + `$warning`, **no TLP**, FSM → idle.

| Check | Rule | Predicted reject condition |
|---|---|---|
| Dword Count range | 1–1024 DW (11 b encodes 2047; surplus illegal) | `DwordCount == 0 \|\| DwordCount > 1024` |
| Config Dword Count | exactly 1 for CFG0 | `is_config && DwordCount != 1` |
| Byte-count fit | `DwordCount×4` must fit `command_byte_count_i` (13 b ≤ 8191 B) | explicit overflow reject — do **not** rely on truncation |
| 4 KB boundary | user app must not cross 4 KB (PG213; the FSM will not) | `address[11:0] + byte_count > 4096` |
| Address Type | untranslated only | `desc[1:0] != 2'b00` (mem/IO descriptor) |
| Request Type | §C map set only | anything outside `{0000,0001,0010,0011,1000,1010}` |
| Poisoned Cfg write | unsupported | `is_cfg_write && desc[79]` |
| BE consistency | contiguous, reproducible | §D.4 mismatch (non-contiguous / zero-length) |
| Early `tlast` | host ends before byte count | early `s_axis_rq_tlast` → reject, never pass early `last` to TL ([[command-data-last-contract]]) |
| ✅ **NEW — config/IO one-DW fit** *(corrected 2026-07-28, `d5a4253`)* | CFG0/IO must **fit inside the addressed DW** — byte-granular within it is legal | **`is_cfg_or_io && byte_count > (4 − off)`** → reject. ~~`(byte_count != 4 \|\| address[1:0] != 2'b00 \|\| first_be != 4'hF \|\| last_be != 4'h0)`~~ — that form is **withdrawn**; it would reject legal requests. Mirrors `tlp_requester.sv:183-199`. §D.2/§D.3a |

### F.1 ⚠️ Signal renames for the T-plan (merge-imposed, 2026-07-28)
Any Commit-2a assertion written against the old names must be re-pointed:
- `command_error_o` → **`command_error_valid_o`** (1-cyc pulse) **+ `command_error_code_o`**
  (`tlp_error_e`), `tlp_requester.sv:49-50` / `tlp_layer.sv:70-71`. The "*`command_error_o` pulse
  count == 0*" assertion for a well-formed 2a-0 stream becomes
  "*`command_error_valid_o` pulse count == 0*"; a violation test should additionally assert
  `command_error_code_o == TLP_ERR_LOCAL_PAYLOAD` (early `last`) or `TLP_ERR_BAD_LENGTH`
  (bad admission).
- `command_digest_valid_i` / `command_digest_i` → **`command_ecrc_enable_i`** (`:25`). **Tie 0.**
  The TL now computes ECRC itself (`tlp_ecrc.sv`); there is no host-supplied digest to drive.

### F.2 ⚠️ NEW — flow-control preconditions for every Commit-2a testbench
`tlp_layer` will emit **zero TLPs and no error** unless its environment drives `link_up_i=1`,
`transmit_enable_i=1`, `fc_initialized_i=1`, and at least one `fc_update_valid_i` pulse with
non-zero credits (`tlp_layer.sv:19-20, 31-38, 249`; `tlp_credit_manager.sv:53-54, 76-83`).
Config requests consume **NPH/NPD** credit (`tlp_layer.sv:262-272`). Reference init sequence:
`tb/tlp/test_tlp_conf_requester.py:112-119`. Full detail: `RECON_commit2a.md` §Q.2.

## G. Test-list deltas vs brief §6/§7 (from go/no-go)
- **§4.3 fixed to R1** — T2/T5/T11 assert the R1 mapping and the D.4 rejects (non-contiguous,
  zero-length → `KNOWN_GAPS`).
  ~~⛔ **AMENDED 2026-07-28:** T2/T11 keep the R1 mapping but **on memory commands only**.
  **T5 is deleted** and replaced by **T5′** (assert the wrapper rejects a byte-granular config
  descriptor with `rq_protocol_error_o` and emits no TLP).~~
  ✅ **RE-AMENDED 2026-07-28 (`d5a4253`):** T2/T11 keep the R1 mapping on **all** command types.
  **T5 is reinstated** and **T5′ is withdrawn**. The aligned whole-DW config golden (old T5″) is
  kept as one point in a **byte-granular sweep** over `first_be ∈ {1,2,4,8,3,C,F}` at `N=1`, all of
  which must be **admitted**; the reject cases are the misfits `bc > 4 − off`.
- **RC `[11:7]` via context** — U-tests treat Lower Address `[11:7]` as context-sourced, not 0.
- **NEW U10 (2a-ii): back-to-back completions, different tags on consecutive cycles.** Assert each
  RC packet's descriptor Tag matches *its own* payload. Rationale: `received_completion_header_o` is
  combinational but `result_*` is **registered** (1-cyc later,
  ~~`tlp_request_tracker.sv:104,119-120`~~ → **`tlp_request_tracker.sv:110-111,136-142`**)
  — back-to-back this is a **mis-pairing** risk (header N vs `result` N−1), not just latency the FIFO
  hides. **Design directive:** in `pcie_rc_if`, **register the parsed header to align with `result_*`
  before the capture/skid stage**, rather than relying on the FIFO to fix ordering. ✔ **re-verified
  2026-07-28: the skew is still present and U10 is still required.**
- **NEW U11 (2a-ii), from RC6:** a completion rejected by the tracker's consistency pre-filter
  (`tlp_request_tracker.sv:127-135`) produces **no `result_*`** — assert the RC wrapper reports it
  via `unexpected_completion_o` + `completion_error_code_o` and does not stall waiting for a
  `result_valid_o` that never comes.
- **NEW (2a-0/2a-i harness requirement):** every testbench instantiating `tlp_layer` must initialise
  flow control (§F.2) or it will silently observe zero TLPs.

## H. Hard-stop status
~~No R3, no `src/tlp/` change, T5 open, RC bit 30 present.~~ **Awaiting go/no-go for RTL (HARD STOP #2).**
Next: Phase 2 = Commit 2a-0 gearboxes (`pcie_axis_dw_downsize`/`upsize` + exhaustive tb), no TL in loop.

~~**Amended 2026-07-28 (Phase B):** no `src/tlp/` change needed; **RC bit 30 present and confirmed**;
**R1 confirmed on memory, but config is effectively R3 and T5 is CLOSED** (§D.3a).~~

✅ **RE-AMENDED 2026-07-28 (later, post-`d5a4253`) — the final status of this document:**
no `src/tlp/` change needed; **RC bit 30 present and confirmed**; **R1 confirmed on *all* paths —
memory, I/O and config**; **T5 is REOPEN**. `d5a4253` relaxed the admission guard to
`byte_count <= 4 − address[1:0]` and `67220b5` locked the matrix; the "config is effectively R3"
conclusion was a property of the merge-era guard and no longer holds. **No hard stop stands.**
Commit 2a-0 (gearboxes) landed at `ccb2a52`; Commit 2a-i (`pcie_rq_if`) builds against this
document as corrected.
**2a-0 (gearboxes) is unaffected and remains safe to build as specified** — its contract
(`DATA_WIDTH=32`/`KEEP_WIDTH=4`, per-beat `keep` popcount, partial final beat, combinational
`command_data_ready_o`, end-of-request `command_data_last`) re-verified unchanged. The open
operator decisions are (a) Commit 2b's bus-number write becoming a whole-DW RMW, and (b) whether to
re-open the zero-length-memory-read KNOWN_GAP (§D.4).
