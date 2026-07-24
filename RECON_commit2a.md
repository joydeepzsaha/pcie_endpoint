# RECON_commit2a.md — Phase 0 recon for Commit 2a (RQ/RC AXIS requester interface)

**Branch:** `kourosh/dev` @ `f3160d0` · **Mode:** READ-ONLY, no RTL, no commit.
Every load-bearing answer is a quoted `file:line`. Inferences are marked as such.

> **Headline:** The TL command port is a clean landing surface for the RQ wrapper. The
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

### A.1 Full command port list
Source: `tlp_requester.sv:26-68`, wired identically at `tlp_layer.sv:43-60`.

| Signal | Width | Dir | Level/Pulse |
|---|---|---|---|
| `command_valid_i` / `command_ready_o` | 1 | in/out | handshake |
| `command_i` | `tlp_cmd_e` (3b) | in | level, latched |
| `command_address_i` | 64 | in | level, latched |
| `command_byte_count_i` | 13 | in | level, latched (authoritative) |
| `command_tc_i` / `command_attr_i` | 3 / 3 | in | latched |
| `command_context_i` | `CONTEXT_WIDTH`=16 | in | latched → echoed on completion |
| `command_prefix_valid_i` / `command_prefix_i` | 1 / 32 | in | latched |
| `command_digest_valid_i` / `command_digest_i` | 1 / 32 | in | latched (ECRC — out of scope, tie 0) |
| `command_data_i` / `command_keep_i` | 32 / 4 | in | payload beat |
| `command_data_valid_i` / `command_data_last_i` / `command_data_ready_o` | 1 | | payload handshake |
| `command_error_o` | 1 | out | 1-cyc pulse (contract violation flag) |

Requester params: `DATA_WIDTH=32, KEEP_WIDTH=4, CONTEXT_WIDTH=16` (`tlp_requester.sv:22-25`).

### A.2 Launch handshake (Q2)
- Qualifier: `command_ready_o = state_r == REQ_IDLE` (`tlp_requester.sv:156`). Accept fires on
  `command_valid_i && command_ready_o`, **single cycle**, latching every `command_*` field
  (`tlp_requester.sv:204-219`).
- Post-`f3160d0`: `command_byte_count_i` → `remaining_r` is authoritative (`:207`). The requester
  owns MPS/4KB segmentation internally (`calculate_segment`, `:103-120`). `command_data_last_i`
  is compared against `request_last = expected_data_last && (remaining_r <= segment_bytes_r)`
  (`:174`), i.e. **end-of-whole-request**, not per-segment. Mismatch → `command_error_o` pulse
  (`:242-243`); early last → abort to `REQ_IDLE` (`:244-248`).

### A.3 `tlp_cmd_e` members (Q3)
`tlp_pkg.sv:43-50`: `MEM_READ=0, MEM_WRITE=1, CFG_READ0=2, CFG_WRITE0=3, IO_READ=4, IO_WRITE=5`.
Maps 1:1 to MemRd/MemWr/CfgRd0/CfgWr0/IORd/IOWr. **CFG1 is absent from the command enum** — only
a wire-level `TLP_TYPE_CFG1=5'b00101` exists (`tlp_pkg.sv:21`) with no `tlp_cmd_e` that reaches it.
The requester cannot originate a Type-1 config request → wrapper detects+rejects (§4.2), never
silently maps. ✔ confirms brief §1.

### A.4 Payload path (Q4)
- `DATA_WIDTH=32`, `KEEP_WIDTH=4`. Valid/ready: `command_data_valid_i` / `command_data_ready_o`.
- `keep` **is honoured on every beat**: `accepted_bytes = Σ command_keep_i[lane]` (popcount,
  `:126-128`), accumulated into `segment_sent_r` (`:241`). Partial final beat is handled by the
  popcount, not assumed full.
- `packet_keep_o = command_keep_i` — straight passthrough to the DLL-facing AXIS (`:166`).
- **Gearbox contract:** the downsize output feeding this port must present 32-bit DW beats with
  `tkeep` marking real bytes and assert `last` exactly on the final beat of the whole request
  (byte count from the descriptor). This is the `command_data_last` contract (memory
  [[command-data-last-contract]]).

### A.5 Backpressure (Q5)
`command_data_ready_o = state_r == REQ_DATA && packet_data_ready_i` (`:182`) — **combinational**
off the DLL-facing `packet_data_ready_i`. So the requester *can* stall the host mid-request, and
the ready is combinational (a timing note for the gearbox, not a blocker — brief §3.A.5).

---

## B. Byte enables — the ownership question ⭐

### B.1 Where BEs are computed (Q6)
`tlp_pkg.sv:93-116` defines `tlp_first_be(address_low, byte_length)` /
`tlp_last_be(address_low, byte_length)`. **Only call site in `src/tlp/`:**
`tlp_requester.sv:147-148`:

```
header_c.first_be = tlp_first_be(address_r[1:0], segment_bytes_r);
header_c.last_be  = tlp_last_be(address_r[1:0], segment_bytes_r);
```

This is **unconditional** — identical for MemWr/IOWr/CfgWr0/reads; there is *no* config special
case. The TL computes BEs itself from `address_r[1:0]` (a **byte offset** within the DW) and
`segment_bytes_r`. Confirms the v2 hypothesis. (The `dma_if_pcie_us_wr.v` hits in the grep are
unrelated third-party verilog-pcie DMA, not `src/tlp/`.)

### B.2 The collision, resolved (Q8) → **R1 (byte-offset semantics)**
`address_r[1:0]` is used in **two** places for a config request:
1. `tlp_first_be(address_r[1:0], …)` — as a byte offset.
2. `header_c.address = address_r` (`:149`) — as the low bits of the address the generator emits.

There is **no on-wire conflict**, because the generator *forces the emitted config DW's low two
bits to zero*:
- `tlp_generator.sv:70-71`: `dw2 = tlp_is_4dw(fmt) ? address[63:32] : {header_r.address[31:2], 2'b00};`
  (config is always 3DW, so DW2 = `{address[31:2], 2'b00}`).
- `tlp_generator.sv:109` (4DW DW3 path) likewise masks `{address[31:2], 2'b00}`.

And the register number lives in `address[7:2]`, **disjoint** from the byte offset `[1:0]`
(matches the Commit-1 config-DW layout: `[31:24]=Bus [23:19]=Dev [18:16]=Fn [11:8]=ExtReg
[7:2]=Reg#`, [[tlp-cfg0-spine]]).

**Resolution: R1.** Commit-1 A.3's "`command_address[1:0] = 2'b00`" was the *DW-aligned* special
case (whole-DW access, `first_be=1111`), **not** a hard constraint. v1's §4.3 (pin `[1:0]=00`) was
wrong; the wrapper must drive `command_address[1:0] = byte offset`.

### B.3 Byte-granular config IS expressible (Q7) — the T5 gate is OPEN
To write **Secondary Bus Number at config offset `0x19`** (`first_be=4'b0010`):
- `command_address[7:2]` = Reg# = `0x18>>2 = 0x06`; `command_address[1:0] = 2'b01` (byte offset 1);
  `command_byte_count_i = 1`.
- ⇒ `tlp_first_be(2'b01, 13'd1) = 4'b0010` (`tlp_pkg.sv:100-103`, lane∈[1,2)).
- ⇒ `length_dw = (1 + 1 + 3) >> 2 = 1` (`tlp_requester.sv:144`). Config DwordCount = 1. ✔
- ⇒ emitted config DW = `{address[31:2], 2'b00}` — register number intact, `[1:0]=00` on the wire. ✔
- ⇒ payload realigned to the same offset: `payload_offset = header_r.address[1:0]` feeds the
  payload formatter (`tlp_generator.sv:79, 179`), so the single write byte lands in lane 1. ✔

The byte offset coherently drives **BE + payload alignment + a zeroed on-wire DW**. **T5 is
achievable; Commit 2b's bus-number assignment is unblocked.** No stop trigger.

### B.4 What is NOT expressible (Q9) → rejects, listed in KNOWN_GAPS
- **Non-contiguous BEs** (e.g. `first_be=4'b1001`): `tlp_first_be`/`tlp_last_be` only produce
  *contiguous* range masks (`tlp_pkg.sv:100-103` / `:112-115`). Not expressible → the wrapper
  must **reject** (`rq_protocol_error_o` + `$warning`) and list in KNOWN_GAPS. (PG213 permits
  non-contiguous BE on ≤2-DW writes; we don't support it this commit.)
- **Zero-length read** (`DwordCount=1, first_be=0`): `byte_length=0` ⇒ `first_be=0` but
  `length_dw` degenerates (`(0+offset+3)>>2` → 0 at offset 0). Not cleanly expressible → reject,
  KNOWN_GAP.
- **§4.3 BE-consistency check:** the wrapper still compares descriptor-implied access vs the
  `s_axis_rq_tuser` BEs; disagreement → `rq_protocol_error_o` rather than silently preferring one.

---

## C. `command_context_i` ⭐

### C.1 It exists and round-trips (Q10)
16-bit `command_context_i` (`tlp_requester.sv:40`, `CONTEXT_WIDTH=16` default `:25`). Echo path:
`command_context_i` → `context_r` (`tlp_requester.sv:210`) → `tag_context_o` (`:160`) →
tracker `allocate_context_i` → `context_r[tag]` (`tlp_request_tracker.sv:111`) → on completion
match `result_context_r` (`:120`) → `result_context_o` at the layer (`tlp_layer.sv:289`).
**Confirmed: stash at request time, echoed on the matching completion.**

### C.2 What it can reconstruct (Q11)
16 bits is **not** enough for {LowerAddr[11:0] + orig ByteCount[12:0] + RequesterID[15:0]}=41b.
But — see §D — nearly every RC descriptor field comes directly from the parsed completion header,
so context is a **bonus, not a necessity**. Its one useful job: stash the original request's
`address[11:7]` (5 bits) to close the RC **Lower Address [11:7]** gap the CPL can't carry.
**Timing caveat:** `result_context_o` is **registered** (1 cycle after the completion header is
accepted — `tlp_request_tracker.sv:104,119-120`), whereas `received_completion_header_o` is
combinational (`tlp_layer.sv:164`). The RC wrapper must align the two (the skid/FIFO capture in
§7.1 absorbs this skew naturally). **Design decision for 2a-ii:** default the Lower Address
[11:7] to 0 and list in KNOWN_GAPS, OR route `address[11:7]` through context — recommend the
latter only if U-tests show it's needed; for the config-enumeration path (1 DW) it's moot.

---

## D. The completion return surface (the RC source) ⭐

**Key correction to the v2 premise:** `tlp_layer` exposes **two** completion surfaces, not one.

### D.1 Surfaces (Q12)
1. **`received_completion_*`** (`tlp_layer.sv:97-104`, `:164-165, :192-197`): the *raw parsed CplD*.
   - `received_completion_header_o` = `parsed_header` — the **full `tlp_header_t`** (tag,
     requester_id, completer_id, byte_count, lower_address, completion_status, poisoned, tc,
     attributes, length_dw). `:164`.
   - `received_completion_data_o[31:0]` / `_keep` / `_valid` / `_last` / `_ready` — the completion
     **payload as a 32-bit DW-serial AXIS stream** (`:192-195`). `valid = parsed_header_valid &&
     parsed_completion && tracker_completion_ready` (`:165`). Level AXIS handshake.
2. **`result_*`** (tracker digest, `tlp_layer.sv:106-113`): `result_valid_o` (**1-cyc pulse**,
   `tlp_request_tracker.sv:82,104`), `result_context_o[15:0]`, `result_status_o[2:0]`,
   `result_last_o`, `unexpected_completion_o`, `outstanding_o`. Plus `malformed_o` (from parser,
   `:111`).

### D.2 RC descriptor derivation (Q13) — §4.4 field-by-field
| RC field | Source | Status |
|---|---|---|
| Lower Address `[11:0]` | `received_completion_header_o.lower_address[6:0]` (`parser.sv:174`) | **[6:0] OK, [11:7] GAP** (context-closeable) |
| Error Code `[15:12]` | derive from `completion_status` + `poisoned` | OK (derived) |
| Byte Count `[28:16]` | `received_completion_header_o.byte_count` ([11:0] from CPL, `parser.sv:157`; bit12=0) | OK |
| Locked `[29]` | `0` (no CPL_LOCK path this commit) | OK (const) |
| **Request Completed `[30]`** | **`result_last_o`** (`tracker.sv:122-124`) | **OK** |
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

### D.3 Split-completion / bit 30 (Q14)
The tracker keeps `remaining_r[tag]` and decrements it by `completion_payload_bytes_i` per CPL
(`tlp_request_tracker.sv:122-133`); `completion_payload_bytes` is computed at the layer from
`length_dw` and `lower_address[1:0]`, clamped to the CPL's `byte_count`
(`tlp_layer.sv:181-186`). `result_last_o` is set on the CPL where `payload_bytes >= remaining`
(or non-SC / no-data) — **the last-CPL-of-request signal = RC bit 30.** The RC descriptor's own
Byte Count field is taken from the CPL header (`byte_count`), which is spec-defined as "remaining
incl. this CPL." Both present. ✔ (Byte-count accounting was proven in `verilate_tlp_conf_tracker`,
7/7.) No stop trigger.

---

## E. Tag management (Q15) → CORE-MANAGED

The tracker allocates: `allocate_tag_o = first free tag` (`tlp_request_tracker.sv:52-62`). The
requester enters `REQ_TAG` and consumes `tag_i` (`tlp_requester.sv:157, 221-223`). The host does
**not** supply the tag for non-posted requests. ⇒ **PG213 core-managed-tag mode**: the RQ wrapper
should expose `pcie_rq_tag[7:0]` + `pcie_rq_tag_vld` and **ignore `desc[103:96]`** (document it).
Exception: `MEM_WRITE` (posted) skips `REQ_TAG` (`tlp_requester.sv:218`) — no tag. On the RC side
the Tag echoes back from the CPL header, so RC descriptor Tag is faithful.
Namespace note for Kourosh (§11): confirm EP-side completer tags and RC-side requester tags can't
collide.

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
   Non-contiguous BE / zero-length read → reject + KNOWN_GAPS. **Byte-granular config works.**
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
| Trigger | Fired? |
|---|---|
| Wrapper needs `src/tlp/` change | **No** — landing surface sufficient |
| §4.3 = R3 (byte-granular config impossible) | **No** — resolves to R1, expressible |
| T5 (single-byte config write) blocked | **No** — achievable (§B.3) |
| TL can't express RC bit 30 / split accounting | **No** — `result_last_o` + tracker (§D.3) |
| Pre-existing test red | **No** — 78/78 + conformance 1/1 |
| New Verilator warning class | N/A (no RTL yet) |
| Commit 0/1 unstaged / tree unexpected | **No** — committed, clean |

**No RTL written. Awaiting go/no-go for Phase 1.**
