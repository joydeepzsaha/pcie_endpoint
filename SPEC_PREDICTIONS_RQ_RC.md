# SPEC_PREDICTIONS_RQ_RC.md — Phase 1 spec predictions for Commit 2a

**Branch:** `kourosh/dev` @ `f3160d0` · **Mode:** documentation only, no RTL, no commit.
Companion to `RECON_commit2a.md`. This is the golden reference the RTL and tbs are checked against.

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
| `[7:2]` | Reg Number | `command_address[7:2]` | Config-DW layout [[tlp-cfg0-spine]]; `tlp_generator.sv:70-71` emits `{addr[31:2],2'b00}` |
| `[11:8]` | Ext Reg Number | `command_address[11:8]` | same |
| `[74:64]` | Dword Count | **must be `11'd1`** → else reject (§F) | config = 1 DW; `command_limit`=4 B for CFG (`tlp_requester.sv:95-97`) |
| `[78:75]` | Request Type | decode → `command_i` (§C) | `1000`→`TLP_CMD_CFG_READ0`, `1010`→`TLP_CMD_CFG_WRITE0` (`tlp_pkg.sv:46-47`) |
| `[79]` | Poisoned | **must be 0 for CfgWr** → else reject | PG213: poison unsupported on Cfg writes |
| `[119:104]` | **Completer ID (target BDF)** | `command_address[31:16]` | Bus`[119:112]`→`addr[31:24]`, Dev`[111:107]`→`addr[23:19]`, Fn`[106:104]`→`addr[18:16]` |
| `[120]` | Requester ID Enable | root-port mode = 1; RC uses its own `requester_id_i` | `tlp_requester.sv:145` forces `requester_id = requester_id_i` |
| `[123:121]` | TC | `command_tc_i` | `tlp_requester.sv:142` |
| `[126:124]` | Attr | `command_attr_i` | `tlp_requester.sv:143` |
| `[103:96]` | Tag | **ignored** (core-managed, §E/Recon Q15) → `pcie_rq_tag`/`pcie_rq_tag_vld` exposed instead | tracker allocates `tlp_request_tracker.sv:52-62` |
| `[127]` | Force ECRC | ignored (ECRC out of scope; `command_digest_valid_i=0`) | brief §1 |
| `command_address[15:12]` | (reserved) | `4'h0` | config DW reserved field |
| `command_address[1:0]` | (byte offset) | **from `first_be` (§D)** | not from descriptor `[1:0]` (which is Reserved) |

**Predicted on-wire goldens (RTL-anchored, from `tlp_generator.sv:49-71`):**
- **T3 — CfgRd0 DW0 = `0x01000004`.** `fmt=000`(3DW-no-data)`, type=00100`(CFG0) → `dw0[7:0]=0x04`;
  `length_dw=1`→`dw0[31:24]=0x01`. **Unchanged from Commit-1.**
- **T4 — CfgWr0 DW0 = `0x01000044`.** `fmt=010`(3DW-data) → `dw0[7:0]=0x44`; `length=1` → `0x01000044`.
- **DW1 = `{requester_id[15:0], tag[7:0], last_be[3:0], first_be[3:0]}`** (`tlp_generator.sv:69`).
- **DW2 (config) = `{command_address[31:2], 2'b00}`** (`tlp_generator.sv:70-71`).
- **T5 — byte-granular CfgWr0 at offset `0x19`:** DW0=`0x01000044`, DW1 low nibble `first_be=0x2`,
  DW2 = the config DW with `[1:0]=00`, payload byte in lane 1. (Derivation in §D.3.)

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

`command_i` selects 3DW vs 4DW automatically from `address_r[63:32]` (`tlp_requester.sv:131-133`) —
the wrapper does not choose fmt.

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

## D. ⭐ Address + BE mapping — **R1 (byte-offset semantics), FINALIZED**

### D.1 Why there is no collision (record this reasoning)
`address_r[1:0]` feeds **both** `tlp_first_be(address_r[1:0], segment_bytes_r)`
(`tlp_requester.sv:147-148`) **and** `header_c.address` (`:149`). For config there is **no on-wire
conflict** because:
1. The register number lives in `command_address[7:2]`, the byte offset in `[1:0]` — **disjoint
   fields**.
2. The generator **masks the emitted config DW** to `{address[31:2], 2'b00}`
   (`tlp_generator.sv:70-71`, and the 4DW DW3 path `:109`), so the byte offset never reaches the
   wire as part of the address.
3. The payload is realigned by the **same** offset: `payload_offset = header_r.address[1:0]`
   (`tlp_generator.sv:79`, feeding the formatter `:179`).

⇒ Commit-1's "`command_address[1:0] = 2'b00`" was the DW-aligned special case (`first_be=1111`),
not a hard constraint. **v1's §4.3 (pin `[1:0]=00`) is dead.**

### D.2 The wrapper's derivation (all command types)
Let `off = position of the least-significant set bit of first_be` (0/1/2/3), and for a request
spanning `DwordCount` DWs:

```
command_address[63:2] = desc address bits (mem: desc[63:2]; config: {BDF, 0, ExtReg, Reg})
command_address[1:0]  = off                                   // byte offset from first_be
DwordCount == 1:  command_byte_count = popcount(first_be)      // last_be must be 0
DwordCount >= 2:  command_byte_count = popcount(first_be) + (DwordCount-2)*4 + popcount(last_be)
```

The requester **re-derives** the BEs internally as `tlp_first_be(off, byte_count)` /
`tlp_last_be(off, byte_count)` (`tlp_requester.sv:147-148`), reproducing the requested `tuser` BEs.

### D.3 T5 worked example (the Commit-2b gate)
Config offset `0x19` (Secondary Bus Number), single byte:
`first_be=4'b0010` ⇒ `off=1`; `DwordCount=1` ⇒ `command_byte_count=popcount(0010)=1`;
`command_address[7:2]=0x06` (`0x18>>2`), `[1:0]=01`.
⇒ `tlp_first_be(2'b01,13'd1)=4'b0010` (`tlp_pkg.sv:100-103`); `length_dw=(1+1+3)>>2=1`
(`tlp_requester.sv:144`); emitted DW2 = reg-DW with `[1:0]=00`; payload byte in lane 1. ✔

### D.4 BE-consistency check (mandatory)
Recompute `tlp_first_be(off, bc)` / `tlp_last_be(off, bc)` and compare to the `tuser` BEs. On
mismatch → `rq_protocol_error_o` + `$warning`, no TLP. This catches:
- **Non-contiguous BEs** (e.g. `first_be=4'b1001`): the functions only build contiguous range masks
  (`tlp_pkg.sv:100-103`, `:112-115`) → **reject, KNOWN_GAPS.**
- **Zero-length read** (`DwordCount=1, first_be=0`): `off`/`bc` degenerate → **reject, KNOWN_GAPS.**

## E. RC descriptor derivation (12 B / 96 b, `DESC_DW=3`)
**Source:** PG213 v1.3, Fig 56 / Table 65 (via addendum). RC surface = `received_completion_*` +
`result_*` (`tlp_layer.sv:97-113`). Dword-aligned mode → first payload DW immediately after the
3-DW descriptor (the rotation §4.4 / gearbox G5).

| RC bits | Field | Source | Status |
|---|---|---|---|
| `[11:0]` | Lower Address | `[6:0]`=`received_completion_header_o.lower_address` (`parser.sv:174`); `[11:7]`=**`result_context_o` echo** of request `address[11:7]` | `[6:0]` OK; `[11:7]` via context |
| `[15:12]` | Error Code | derive: `0000` SC · `0001` poisoned · `0010` UR/CA/CRS · `0011` no-data/overrun | derived |
| `[28:16]` | Byte Count | `received_completion_header_o.byte_count` (13 b; CPL carries `[11:0]`, `parser.sv:157`) | OK |
| `[29]` | Locked Read Compl. | `0` (no CPL_LOCK path this commit) | const |
| `[30]` | **Request Completed** | **`result_last_o`** (`tlp_request_tracker.sv:122-124`) | OK |
| `[31]` | Reserved | `0` | |
| `[42:32]` | Dword Count | `received_completion_header_o.length_dw` (I/O-write CPL→0; zero-len read→1) | OK |
| `[45:43]` | Completion Status | `received_completion_header_o.completion_status` / `result_status_o` (incl. **CRS `010`**) | OK |
| `[46]` | Poisoned | `received_completion_header_o.poisoned` | OK |
| `[63:48]` | Requester ID | `received_completion_header_o.requester_id` | OK |
| `[71:64]` | Tag | `received_completion_header_o.tag` (core-assigned, echoed) | OK |
| `[87:72]` | Completer ID | `received_completion_header_o.completer_id` | OK |
| `[91:89]` | TC | `received_completion_header_o.traffic_class` | OK |
| `[94:92]` | Attr | `received_completion_header_o.attributes` (3 b) | OK |

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

## G. Test-list deltas vs brief §6/§7 (from go/no-go)
- **§4.3 fixed to R1** — T2/T5/T11 assert the R1 mapping and the D.4 rejects (non-contiguous,
  zero-length → `KNOWN_GAPS`).
- **RC `[11:7]` via context** — U-tests treat Lower Address `[11:7]` as context-sourced, not 0.
- **NEW U10 (2a-ii): back-to-back completions, different tags on consecutive cycles.** Assert each
  RC packet's descriptor Tag matches *its own* payload. Rationale: `received_completion_header_o` is
  combinational but `result_*` is **registered** (1-cyc later, `tlp_request_tracker.sv:104,119-120`)
  — back-to-back this is a **mis-pairing** risk (header N vs `result` N−1), not just latency the FIFO
  hides. **Design directive:** in `pcie_rc_if`, **register the parsed header to align with `result_*`
  before the capture/skid stage**, rather than relying on the FIFO to fix ordering.

## H. Hard-stop status
No R3, no `src/tlp/` change, T5 open, RC bit 30 present. **Awaiting go/no-go for RTL (HARD STOP #2).**
Next: Phase 2 = Commit 2a-0 gearboxes (`pcie_axis_dw_downsize`/`upsize` + exhaustive tb), no TL in loop.
