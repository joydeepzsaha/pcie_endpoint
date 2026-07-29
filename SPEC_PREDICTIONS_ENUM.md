# SPEC_PREDICTIONS_ENUM — Commit 2b enumeration FSM

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` @ `eb19032` · **Phase 1 of Commit 2b.**
**Written before any FSM RTL exists.** Every value below is derived from the
specification and committed *ahead* of the DUT, so a later disagreement is a DUT
bug or a prediction bug, never a golden retro-fitted to observed behaviour.

**Normative source:** PCI Express Base Specification, Rev. 2.1
(`/home/kourosh/openPCIE/0.doc/PCIE-base-spec.Rev2-1.pdf`), cited as
**§section p.page**. Page numbers are the printed spec pages.
**Interface source:** PG213 v1.3 as markdown
(`/home/kourosh/openPCIE/0.doc/pg213-pcie4-ultrascale-plus.md`), cited as
**PG213:line**. The 512-bit-interface duplicates at `:5222+` are never cited —
wrong width. MindShare and Southwell are background only and are cited nowhere.

---

## ⛔ 0. THREE FINDINGS THAT CHANGE THE WORK — read before anything else

### 0.1 The brief's **P-NPD0 prediction is inverted**. An all-zeros advertisement means INFINITE, not zero.

The Phase-1 brief §C.2 asks for a prediction that advertising `NPD=0` "lets every
enumeration *read* through and **wedges at the first CfgWr0**". **That cannot
happen, and a test written to it would pass while proving nothing.**

> An advertisement of `00h`/`000h` made **at Flow Control initialization** means
> **infinite** credit for that type — §2.6.1 p.138, and footnote 33 p.137:
> *"interpreted as infinite by the Transmitter, which will, therefore, never
> throttle."*

The design implements exactly this and says so: `tlp_credit_manager.sv:106-120`
latches `npd_infinite_r` at init and never re-evaluates it. So driving
`fc_npd_i = 0` produces **infinite NPD** — every CfgWr0 flows, nothing blocks,
`tx_fc_blocked_o` never asserts. A "credit starvation" test built on `NPD=0`
would be a **vacuous pass**: the exact failure mode brief §10 exists to prevent.

My own `RECON_commit2b.md` §2.3 asserted the same wrong thing. **Both are
corrected here**; the recon's §2.3 is superseded by §2 below.

The real starvation vector is a **finite** advertisement with no replenishment —
see **P-NPD1-STALL** (§2.4). This finding cost nothing to catch and would have
cost a whole increment to catch later.

### 0.2 The BAR sizing algorithm is **not in PCIe Base 2.1**. It is PCI 3.0, which is off-shelf.

Brief §7 says "Derive every field from **PCIe Base 2.1**". For the BAR work that
is not possible. Searched exhaustively:

- §7.5.2.1 p.491-492 defines only BAR **usage** policy: prefetchable-bit rules,
  the 64-bit-addressing requirement for prefetchable BARs, and *"The minimum
  Memory Space address range requested by a BAR is 128 bytes."*
- Figure 7-5 p.491 gives the Type 0 header **offsets** (BARs at `10h`–`24h`).
- **Nothing** in Base 2.1 defines BAR bit 0 (Memory/IO indicator), bits [2:1]
  (Type / 32- vs 64-bit), or bit 3 (Prefetchable), and **nothing** describes the
  write-all-ones sizing algorithm. Grep for the algorithm returns zero hits.
- Same gap in the Command register: Table 7-3 §7.5.1.1 p.485-487 defines
  **bit 2 Bus Master Enable** explicitly, but **starts at bit 2** — bit 0 (I/O
  Space Enable) and **bit 1 (Memory Space Enable)** are not defined there.

Those definitions live in the **PCI Local Bus Specification 3.0** (§6.2.5.1 for
BARs), which Base 2.1 incorporates by reference (definitions p.30-31: *"Memory
Space defined in PCI 3.0"*) but which is **not on the spec shelf** (brief §2
lists only Base 2.1, PG213, MindShare, Southwell).

Every constant below carries an explicit **citation-status** tag:

| tag | meaning |
|---|---|
| **[BASE]** | cited to PCIe Base 2.1, section + page. Golden. |
| **[PG213]** | cited to PG213 by line. Interface shape only, never protocol. |
| **[PCI3-REF]** | normative source is PCI 3.0, incorporated by reference by Base 2.1 but **not readable on this shelf**. Value stated from established hardware convention; **citation pending**. |

**This is a gate, not a blocker.** Nothing tagged `[PCI3-REF]` changes the FSM's
*shape* — only the numeric constants in the BAR decode and the Command-register
bit positions. §9 states what I need to close it.

### 0.3 The probe-timeout question resolves to **FAULT**, not absent-continue.

Derived in full in §5.3. Short form: Base 2.1 makes **UR** the device-absence
signal (§2.3.2 Implementation Note p.122 — all-1s read data *"particularly when
probing to determine the existence of a device in the system"*), and makes a
**Completion Timeout a reported error** (§2.8 p.152). Absence and silence are
different events with different spec meanings. **Timeout on the probe → ERROR
state.**

---

## 1. Baseline statement (pinned, un-mixable)

> **Pre-existing set to hold byte-identical: 29 targets / 171 tests
> (23 TLP + 6 RC) + `verilate_conformance` control 1/1 = 30 targets / 172 tests.**

Written decomposed, deliberately. This off-by-one has now occurred three times —
`STACK_INVENTORY.md` §0.1/§2.1 mis-attributed the +1 and declared a prior "152" a
bookkeeping slip, and `RECON_commit2b.md` inherited that exclusion. The control
is a **separate line item** and is neither folded into the TLP+RC subtotal nor
dropped from the grand total. Prior art: `RECON_commit2a.md:51-52`,
`SPEC_PREDICTIONS_CPL_TIMEOUT.md:269-276`.

Measured at `33ba088`, all `rc=0`: subtotal `29/171`, control `1/1`
(6010.00 ns), **`TARGETS=30 TESTS=172 PASS=172 FAIL=0`**. Per-target sim times in
`scratchpad/base33ba088/baseline_record.txt`.

---

## 2. Flow control — consumption facts and the test vector

### 2.1 What a config request actually consumes  **[BASE]** + RTL

| request | credit class | header | data |
|---|---|---|---|
| **CfgRd0** | Non-Posted | **NPH = 1** | **NPD = 0** |
| **CfgWr0** (1 DW) | Non-Posted | **NPH = 1** | **NPD = 1** |

Derivation, read not assumed:

- `tlp_pkg.sv:127-133` — `tlp_credit_class()` maps everything that is not Posted
  or Completion to `TLP_CREDIT_NON_POSTED`; both CFG0 forms land there.
- `tlp_vc_buffer.sv:91` — `s_packet_has_data_i ? tlp_data_credits(length_dw) : 0`.
  A read has no data → **0 data credits**.
- `tlp_pkg.sv:121-125` — `tlp_data_credits(1) = ceil(4 bytes / 16) = 1`.

**Correction to `RECON_commit2b.md` §2.3 and brief §3.** Brief §3's *"config
consumes NPH+NPD"* holds only for **writes**. Brief §4.2's *"Config reads consume
NPH"* is the precise statement.

### 2.2 What a compliant peer must advertise — Table 2-37 **[BASE §2.6.1 p.137-138]**

| type | minimum initial advertisement |
|---|---|
| PH | 1 unit — `01h` |
| PD | largest Max_Payload_Size ÷ FC unit size |
| **NPH** | **1 unit — `01h`** |
| **NPD** | **1 unit — `01h`** (2 units if the receiver supports AtomicOp routing/completion) |
| CPLH | RC-with-p2p and Switch: 1 unit. **RC-without-p2p and Endpoint: infinite — initial value all 0s** |
| CPLD | RC-with-p2p and Switch: MPS ÷ FC unit. **RC-without-p2p and Endpoint: infinite — all 0s** |

Two consequences the brief anticipated and the spec now pins:

1. **Brief §4.2 is confirmed exactly.** NPH may legally be as low as **1**, so
   the FSM must be built for **one config request outstanding at a time**. Tag
   availability is not the binding constraint.
2. **Completion credit really is infinite** — for an **Endpoint** it is
   *mandatory*, not merely likely (Table 2-37 CPLH/CPLD rows, p.137-138). The
   endpoint we enumerate advertises `CPLH=0, CPLD=0`.
3. **NPD ≥ 1 is guaranteed.** `NPD=0` is not a legal advertisement meaning "no
   data credit" — it means infinite (§0.1). This is why P-NPD0 is unwritable.

### 2.3 The required small-credit test vector — **spec-derived, not chosen**

Brief §10 requires one test per increment at realistic small credits. The vector
is fixed by Table 2-37 rather than invented:

```
fc_ph_i   = 0x001     PH  = 1        (Table 2-37 minimum)
fc_pd_i   = 0x008     PD  = 8        (128-byte MPS / 16-byte FC unit; unused —
                                      enumeration originates no Posted request)
fc_nph_i  = 0x001     NPH = 1        (Table 2-37 minimum -- THE binding constraint)
fc_npd_i  = 0x001     NPD = 1        (Table 2-37 minimum, non-AtomicOp receiver)
fc_cplh_i = 0x000     CPLH = INFINITE (Table 2-37: mandatory for an Endpoint)
fc_cpld_i = 0x000     CPLD = INFINITE (Table 2-37: mandatory for an Endpoint)
```

⚠️ **Bench requirement the vector implies — the drip must be CUMULATIVE.**
`fc_*_i` is the raw `CREDITS_ALLOCATED` off the wire (§2.6.1.2 p.141); there is
no arithmetic anywhere on the path. So the replenishing UpdateFC stream must
drive an **increasing cumulative count** — `fc_nph_i` = 1, 2, 3, 4 … as each
request retires — **not** a repeated `1`. A drip that re-pulses `1` advertises
"still only ever allocated one credit" and the design will correctly block
forever after the first request. Predicted failure signature if written wrong:
identical to P-NPD1-STALL below, which is why both must exist and be told apart.

### 2.4 Predictions

- **P-NPD-INF** *(replaces the brief's P-NPD0)*. Advertise `fc_npd_i = 0` at FC
  init, everything else per §2.3. **Predicted: NPD is infinite. Every CfgWr0
  flows. `tx_fc_blocked_o` never asserts on the NPD account. Zero errors, zero
  stalls, enumeration completes.** Cited: §2.6.1 p.138 + fn 33 p.137;
  `tlp_credit_manager.sv:106-120`. Kept as a **negative control against the
  vacuous test** — it documents *why* the obvious starvation test is not the
  starvation test.
- **P-NPD1-STALL** *(the real fake-deadlock signature)*. Advertise the §2.3
  vector and then **stop the drip** after FC init. **Predicted: the first CfgWr0
  consumes the single NPD credit and completes; the next CfgWr0 blocks
  indefinitely with `tx_fc_blocked_o` asserted, zero error strobes on any output,
  and the FSM parked waiting on `s_axis_rq_tready`.** This is a *credit* stall,
  not an FSM bug, and §4.1 of the 2b brief requires the FSM to survive it for
  arbitrary spans. Resuming the drip must resume enumeration with no state loss.
- **P-NPH1-SERIAL**. With NPH=1 and a live cumulative drip, **at most one config
  request is ever on the wire**; `outstanding_o` never exceeds 1. This is the
  observable that proves the single-outstanding design is real rather than
  incidental.
- **P-RC1**. Drop `fc_initialized_i` (or never pulse `fc_update_valid_i`): the
  FSM issues its first descriptor, `s_axis_rq_tready` still rises, the command
  still reaches the TL, and then **zero TLPs appear on `m_dllp_axis_*` and no
  error output ever pulses**. The recognisable RC1 signature. One test, once.

---

## 3. Exact RQ descriptors for every enumeration transaction

### 3.1 What the spec fixes for *every* config request  **[BASE §2.2.7 p.79]**

> Configuration Requests route **by ID**, and use a **3 DW header**. Additional
> fields: **Register Number[5:0]**, **Extended Register Number[3:0]**.
> Restrictions: `TC[2:0]` must be `000b` · TH reserved · `Attr[2]` reserved ·
> `Attr[1:0]` must be `00b` · `AT[1:0]` must be `00b` ·
> **`Length[9:0]` must be `00 0000 0001b`** · **`Last DW BE[3:0]` must be `0000b`**.

Figure 2-18 p.80 gives the third header DW:
`{Bus Number[31:24], Device Number[23:19], Function Number[18:16], Reserved[15:12], Ext Reg Number[11:8], Register Number[7:2], R[1:0]}`.

**This matches the RTL exactly** — `tlp_generator.sv:81-82` and the wrapper's
address assembly `pcie_rq_if.sv:256-262`, which places the descriptor's
**Completer ID** into `address[31:16]`. Confirms brief §3's "`completer_id` = the
target BDF forms the routing DW, not the address".

Consequences that are now **spec-mandated, not stylistic**: `dword_count = 1`,
`last_be = 0000`, `tc = 0`, `attr = 0` on every transaction below.

### 3.2 Descriptor field positions  **[PG213 Table 61, `:3711`,`:3720`,`:3728`,`:3735`]**

Verified line-by-line against `pcie_rq_rc_pkg.sv:43-55` — **exact match**:
`[1:0]` Reserved · `[7:2]` Reg Number · `[11:8]` Ext Reg Number · `[63:12]`
Reserved · `[74:64]` Dword Count · `[78:75]` Request Type · `[79]` Poisoned ·
`[103:96]` Tag *(ignored — core-managed)* · `[119:104]` Completer ID · `[120]`
Requester ID Enable · `[123:121]` TC · `[126:124]` Attr · `[127]` Force ECRC.

Request Type encodings **[PG213 Table 57 via `:3725`]**: `1000` = CfgRd0,
`1010` = CfgWr0 (`pcie_rq_rc_pkg.sv:71,73`).

### 3.3 Config-space offsets  **[BASE Figure 7-5 p.491]**

| register | byte offset | reg_num | note |
|---|---|---|---|
| Vendor ID `[15:0]` / Device ID `[31:16]` | `00h` | **0** | [BASE] |
| Command `[15:0]` / Status `[31:16]` | `04h` | **1** | [BASE] |
| Cache Line Size / Master Latency / **Header Type** / BIST | `0Ch` | **3** | Header Type at byte `0Eh` → byte 2 of DW 3 [BASE] |
| Base Address Registers 0–5 | `10h`–`24h` | **4–9** | [BASE] |

### 3.4 The descriptors — target BDF = bus 1, device 0, function 0 (`completer_id = 0x0100`)

All: `dword_count=1`, `last_be=0000`, `tc=0`, `attr=0`, `poisoned=0`,
Tag field zero (ignored). `tuser[3:0]=first_be`, `tuser[7:4]=last_be=0`.

| # | transaction | type | reg | first_be | `s_axis_rq_tdata[127:0]` (beat 0) | on-wire DW2 |
|---|---|---|---|---|---|---|
| E1 | Vendor/Device ID probe | `1000` | 0 | `0b1111` | `0x00010000000040010000000000000000` | `0x01000000` |
| E2 | Header Type read (byte) | `1000` | 3 | `0b0100` | `0x0001000000004001000000000000000C` | `0x0100000C` |
| E3 | Header Type read (whole DW) | `1000` | 3 | `0b1111` | `0x0001000000004001000000000000000C` | `0x0100000C` |
| E4 | BAR0 all-ones write | `1010` | 4 | `0b1111` | `0x00010000000050010000000000000010` | `0x01000010` |
| E5 | BAR0 readback | `1000` | 4 | `0b1111` | `0x00010000000040010000000000000010` | `0x01000010` |
| E6 | BAR1 all-ones write | `1010` | 5 | `0b1111` | `0x00010000000050010000000000000014` | `0x01000014` |
| E7 | BAR1 readback | `1000` | 5 | `0b1111` | `0x00010000000040010000000000000014` | `0x01000014` |
| E8 | BAR5 readback | `1000` | 9 | `0b1111` | `0x00010000000040010000000000000024` | `0x01000024` |
| E9 | Command register write | `1010` | 1 | `0b0011` | `0x00010000000050010000000000000004` | `0x01000004` |

⚠️ **E2 and E3 have identical descriptors.** The byte enables live in `tuser`,
not in the descriptor — a bench that asserts only on `tdata` cannot tell a
byte-granular read from a whole-DW read. Any test distinguishing them **must**
assert on `tuser` and on the emitted header's `1st DW BE` field.

BAR write payload (E4/E6): one beat, `tdata = 0xFFFFFFFF`, `tkeep = 0x1`,
`tlast = 1`. Command write payload (E9): `tdata = 0x00000006`, `tkeep = 0x1`.

### 3.5 BE choice for the Vendor-ID probe — **`1111`, and the spec says so**

**[BASE §2.3.2 p.121, Implementation Note p.113]** CRS Software Visibility
requires that the first access after reset be *"a Configuration Read Request
accessing **both bytes of the Vendor ID field**"*. That sets a **floor** of
`first_be = 0b0011`. Reading the whole Dword (`0b1111`) satisfies the floor and
returns Device ID in the same completion, saving a transaction.

**Prediction: `first_be = 0b1111` on E1.** Legal, spec-satisfying, and strictly
more informative. (The RC in this design does not implement CRS Software
Visibility — see §5.2 — but the probe shape is chosen to remain compatible.)

### 3.6 BE choice for Header Type — **`0b1111` (E3), not the byte-granular E2**

Both are legal and both pass the wrapper's checks (verified below). E3 is chosen:
the byte-granular path is already covered by `verilate_rq_rc_top` V2, and a
whole-DW read of offset `0Ch` returns Cache Line Size, Master Latency Timer,
Header Type **and** BIST in one completion. **E2 is retained as a documented
alternative** so the byte-granular config-read path gets at least one
enumeration-level exercise; the increment that adds it must assert on `tuser`
per §3.4's warning.

### 3.7 Legality pre-check — every descriptor above passes `pcie_rq_if`

Hand-evaluated against `pcie_rq_if.sv:272-319`, so a rejection during 2b-1 is a
real bug and never an expected outcome:

| check | E1/E5/E7/E8 (`fbe=1111`) | E2 (`fbe=0100`) | E9 (`fbe=0011`) |
|---|---|---|---|
| `bad_cfg_n` (`N≠1`) | N=1 ✓ | ✓ | ✓ |
| `bad_zero_len` | `fbe≠0` ✓ | ✓ | ✓ |
| `bad_be` round trip | `off=0,bc=4` → `tlp_first_be=1111`, `tlp_last_be=0000` ✓ | `off=2,bc=1` → `0100`,`0000` ✓ | `off=0,bc=2` → `0011`,`0000` ✓ |
| `bad_cfg_fit` (`bc ≤ 4-off`) | `4 ≤ 4` ✓ | `1 ≤ 2` ✓ | `2 ≤ 4` ✓ |
| `bad_4kb` | `0x24+4 ≪ 4096` ✓ | ✓ | ✓ |
| `bad_poison` | not poisoned ✓ | ✓ | ✓ |

**Prediction: `rq_protocol_error_o` stays low for the entire enumeration
sequence.** Any pulse is a stop-and-report event (brief §11.6).

---

## 4. BAR sizing and assignment

> ⚠️ **Citation status: the arithmetic below is `[PCI3-REF]` except where marked.**
> See §0.2. Base 2.1 gives the offsets and the usage policy; it does **not**
> define the bit layout or the sizing algorithm.

### 4.1 BAR bit layout  **[PCI3-REF — PCI 3.0 §6.2.5.1]**

| bits | field | values |
|---|---|---|
| `[0]` | Memory Space Indicator | `0` = memory BAR, `1` = I/O BAR |
| `[2:1]` | Type | `00` = 32-bit · `10` = 64-bit (BAR occupies **this register and the next**) · `01` reserved (was <1MB) |
| `[3]` | Prefetchable | `1` = prefetchable |
| `[31:4]` | Base address / size-encoding bits | writable above the alignment boundary, read-as-0 below |

**What Base 2.1 *does* say [BASE §7.5.2.1 p.491-492]:**
- A Function requesting Memory Space **must set the Prefetchable bit** unless the
  range has read side effects or does not tolerate write merging.
- Functions other than Legacy Endpoints **must support 64-bit addressing for any
  BAR that requests prefetchable Memory Space**.
- **"The minimum Memory Space address range requested by a BAR is 128 bytes."**
  → **a decoded size below 128 bytes is a malformed device, not a small BAR.**
  This is the one BAR *arithmetic* constraint with a real Base 2.1 citation, and
  the FSM should treat a sub-128-byte decode as an enumeration fault.

### 4.2 Sizing algorithm  **[PCI3-REF]**

For a 32-bit memory BAR at register `r`:

```
1. write  0xFFFFFFFF        to reg r        (CfgWr0, first_be=1111)
2. read   readback          from reg r      (CfgRd0, first_be=1111)
3. mask off the type bits:  encoded = readback & 0xFFFFFFF0
4. if encoded == 0          -> BAR unimplemented; skip it
5. size = (~encoded) + 1                    (32-bit two's complement)
```

Worked example — a 16 KB 32-bit non-prefetchable memory BAR:
`readback = 0xFFFFC000` → `encoded = 0xFFFFC000` → `~encoded = 0x00003FFF` →
`size = 0x00004000 = 16384` ✓.

**Predicted decode of the acceptance-test device (NVMe-like), BAR0/1 as a 64-bit
prefetchable pair sized 16 KB:**

| step | register | written | predicted readback |
|---|---|---|---|
| E4 | reg 4 (BAR0, `10h`) | `0xFFFFFFFF` | `0xFFFFC00C` — size bits + type `10` (64-bit) + prefetch `1` |
| E6 | reg 5 (BAR1, `14h`) | `0xFFFFFFFF` | `0xFFFFFFFF` — upper 32 bits, all size bits writable |

Combined 64-bit decode:
`encoded64 = (0xFFFFFFFF << 32) | (0xFFFFC00C & 0xFFFFFFF0) = 0xFFFFFFFF_FFFFC000`
→ `size = ~encoded64 + 1 = 0x4000 = 16 KB` ✓, `prefetchable = 1`, `type = 10`.

### 4.3 The 64-bit pair rule  **[PCI3-REF]**, cross-checked **[BASE p.491-492]**

When `readback[2:1] == 10`, the BAR is 64-bit and **consumes registers `r` and
`r+1`**. The sizing sequence is therefore:

1. write all-ones to **both** `r` and `r+1`, then read **both**;
2. decode as one 64-bit quantity per §4.2;
3. on assignment, write the low 32 bits to `r` and the high 32 bits to `r+1`;
4. **advance the scan index by 2, not 1.**

Base 2.1 corroborates that this case is the *expected* one rather than exotic:
prefetchable BARs **must** support 64-bit addressing (§7.5.2.1 p.491-492), and a
compliant memory BAR **should** be prefetchable — so an NVMe BAR0/1 pair is the
normal shape.

**Mutation target (brief §10): "64-bit pair treated as two 32-bit BARs."**
Predicted symptom — BAR1's `0xFFFFFFFF` readback decodes as a 32-bit BAR of size
`~0xFFFFFFF0 + 1 = 0x10` (16 bytes). **That is below the 128-byte minimum of
§7.5.2.1 p.491-492**, so the sub-128-byte fault check in §4.1 catches the
mutation *by spec*, not by coincidence. Predicted kill: the size-minimum
assertion, plus a BAR-count mismatch (6 BARs seen instead of 5 slots).

### 4.4 Assignment policy

- Parameter **`MEM_BAR_BASE`** (64-bit). ⚠️ **Not** `BAR_BASE` — that name is
  taken by `tlp_bar_decoder.sv:4` / `tlp_layer.sv:15` for the **endpoint-side
  decode aperture** (inbound CQ, tied off here). Different concept, opposite
  direction; reusing the name would actively mislead.
- Allocate ascending from `MEM_BAR_BASE`, **naturally aligned to each BAR's own
  size** (`addr = (cursor + size - 1) & ~(size - 1)`), cursor advances by `size`.
- **I/O BARs (`readback[0] == 1`) are skipped**, not assigned. Documented
  scope-out: NVMe is memory-BAR only; I/O assignment is future work (brief §13).
- Unimplemented BARs (`encoded == 0`) are skipped and consume no address space.

**Predicted assignment for the acceptance device** with
`MEM_BAR_BASE = 0x0000_0000_8000_0000` and a single 16 KB 64-bit BAR0/1 pair:
BAR0 ← `0x80000000`, BAR1 ← `0x00000000`; cursor ends at `0x80004000`.

---

## 5. Completion-status policy — finalized, with citations

### 5.1 The encodings  **[BASE §2.2.9 p.98]** · **[PG213 `:4052`]**

`000` Successful Completion · `001` Unsupported Request · `010` Configuration
Request Retry Status · `100` Completer Abort · **all others Reserved**.

**[BASE §2.3.2 p.122]** *"Completions with a Reserved Completion Status value are
treated as if the Completion Status was Unsupported Request (UR)."*
→ The FSM's status decode must map **every** unlisted encoding to the UR path,
not to a `default: ERROR`. `rc_cpl_status_e` (`pcie_rq_rc_pkg.sv:152-157`) names
only the four legal values, so the FSM must handle the enum's out-of-range case
explicitly. **This is a real trap**: a `unique case` over four values with no
default is a latch/X-prop hazard on a reserved status.

### 5.2 CRS  **[BASE §2.3.2 p.121, Implementation Note p.113]**

- *"it is only legal to respond with a CRS Completion Status in response to a
  Configuration Request"* (p.113). A CRS on anything else is a protocol error.
- *"Receipt by the Requester of a Completion with CRS Completion Status
  **terminates the Configuration Request**"* (p.113). It is a completed
  transaction, not a partial one — the tag retires and a retry is a **new
  request with a new tag**, not a resumption.
- *"Root Complex handling of a Completion with CRS … is **implementation
  specific**, except for the period following system reset"* (p.121).
- *"If CRS Software Visibility is not enabled, the Root Complex **must re-issue
  the Configuration Request as a new Request**"* (p.121).
- *"A Root Complex implementation **may choose to limit the number of
  Configuration Request/CRS Completion Status loops**"* (p.121-122).
  → **`CRS_RETRY_MAX` is explicitly sanctioned by the spec**, not a local
  invention.
- *"In systems running legacy PCI/PCI-X based software, the Root Complex must
  re-issue the Configuration Request using a **hardware mechanism**"* (p.113).
  → An RTL FSM doing the retry is the spec's own described mechanism.

**Design decisions, stated:**
- **CRS Software Visibility is NOT implemented.** Base 2.1 p.121 makes it
  optional ("For Root Complexes that support CRS Software Visibility…"), and it
  requires synthesizing a fake `0001h` Vendor ID up to a host software
  interface that does not exist in this design (MMIO host interface is deferred,
  brief §13). The FSM therefore takes the "not enabled" branch: **re-issue.**
- **`CRS_RETRY_MAX = 16`** — sim-convenience default, justified as bounded rather
  than tuned. Real hardware waits up to the spec's `Trhfa` recovery window
  (p.113); a real value belongs with the Device Control 2 programming that is
  Stage-H work, exactly like `CPL_TIMEOUT_CYCLES = 4096` (`ef32bcd` precedent).
  **Marked IMPLEMENTATION-DEFINED in the module header.**
- **`CRS_BACKOFF_CYCLES = 64`** — same status. The spec sets no minimum interval;
  any non-zero backoff satisfies it. Chosen small enough that
  `CRS_RETRY_MAX × CRS_BACKOFF_CYCLES = 1024` cycles stays well inside the
  4096-cycle completion timeout, so a CRS retry storm **cannot** be mistaken for
  a timeout. That relationship is the real constraint and must be asserted:
  **P-CRS-BUDGET: `CRS_RETRY_MAX × CRS_BACKOFF_CYCLES < CPL_TIMEOUT_CYCLES`.**

### 5.3 ⭐ Probe timeout — the open derivation, resolved: **FAULT**

The 2b brief §5 left this open: on the Vendor-ID probe, is a completion timeout
"device absent, continue" or "enumeration fault"? **Derived answer: fault.**

**The spec assigns absence to UR, not to silence.**

> **[BASE §2.3.2 Implementation Note p.122, "Read Data Values with UR Completion
> Status"]** *"Some system configuration software depends on reading a data value
> of all 1's when a Configuration Read Request is terminated as an Unsupported
> Request, **particularly when probing to determine the existence of a device in
> the system**. A Root Complex intended for use with software that depends on a
> read-data value of all 1's must synthesize this value when UR Completion Status
> is returned for a Configuration Read Request."*

That is the spec naming the device-existence probe and naming its answer: a
**UR completion**. An absent device is not silent — the request is routed, finds
no completer, and something returns UR.

**The spec assigns silence to error.**

> **[BASE §2.8 p.152]** *"This mechanism is intended to be activated only when
> there is **no reasonable expectation that the Completion will be returned**,
> and **should never occur under normal operating conditions**. … A Completion
> Timeout is a **reported error** associated with the Requester Function (see
> Section 6.2)."*

Probing an empty device number **is** a normal operating condition during
enumeration. If it produced timeouts, §2.8's "should never occur under normal
operating conditions" would be violated on every scan of a sparsely-populated
bus. Therefore a timeout during the probe is *not* the absence path.

**Committed policy: `cpl_timeout_valid_o` during `VENDOR_PROBE` → sticky `ERROR`
state**, code `ENUM_ERR_PROBE_TIMEOUT`. It means the link or the completer
failed, not that the slot is empty.

**⚠️ Consequence for the harness — this is load-bearing.** The spec-golden
completer **must answer every probe**, including probes to device numbers it does
not implement, with a **UR completion**. A completer that simply ignores
unrecognised BDFs would drive the FSM into ERROR on the first empty slot and
look like an FSM bug. This is the single most likely way to mis-build the 2b-2
scan bench.

*(Scope note: in a real topology the UR is generated by the switch or by the RC's
own routing logic when no completer claims the BDF. This design has no such
generator — CQ/CC is tied off — so the bench completer owns that behaviour. That
is a bench responsibility, recorded here and owed to Joy's EP model spec.)*

### 5.4 The finalized table

| event | meaning during enumeration | FSM action | citation |
|---|---|---|---|
| **SC** `000` | success | consume data (reads), advance | §2.2.9 p.98 |
| **UR** `001` **on the probe** | **no device at that BDF** | record absent, continue scan | §2.3.2 IN p.122 |
| **UR** `001` **after the probe** | a device that answered reg 0 now rejects a legal config request | **ERROR** `ENUM_ERR_UR` | §2.3.2 p.120: non-SC/non-CRS ⇒ free resources + Requester-specific error handling |
| **CRS** `010` | device legally not ready; **request terminated** | retry as a **new request** after `CRS_BACKOFF_CYCLES`, ≤ `CRS_RETRY_MAX`; exhausted → **ERROR** `ENUM_ERR_CRS_EXHAUSTED` | §2.3.2 p.121-122; IN p.113 |
| **CA** `100` | completer abort | **ERROR** `ENUM_ERR_CA` | §2.3.2 p.120, p.122 |
| **Reserved** status | treated as UR | route to the UR path above | §2.3.2 p.122 |
| `cpl_timeout_valid_o` **any state** | request failed; tag quarantined | **ERROR** `ENUM_ERR_TIMEOUT` (incl. the probe — §5.3) | §2.8 p.152 |
| `late_cpl_valid_o` + `RC_ERR_ORPHAN_DATA` burst | late completion drained | **not a fault** — count and ignore | design contract; V9 |
| `rc_unexpected_completion_o` | genuine protocol anomaly | **ERROR** `ENUM_ERR_UNEXPECTED` | §2.3.2 p.120 |

`ERROR` is sticky, reported on `enum_error_o` + `enum_error_code_o`, and
recoverable only by reset. No retry loop other than the bounded CRS one.

**P-ORPHAN:** a drained late completion raises `rc_protocol_error_o` with
`rc_error_code_o = RC_ERR_ORPHAN_DATA` **exactly once per drained Dword**
(`pcie_rc_if.sv:403-405`), correlated with a single `late_cpl_valid_o`. The FSM
must not treat that burst as a fault, and the bench must assert the **exact
count**, V9-style (`test_pcie_rq_rc_top.py:1007-1015`) — not merely "no failure".

---

## 6. Known deviations, on the record

1. **No synthesized error completion on timeout.** PG213 `:4252` specifies that
   the Xilinx core answers a completion timeout by *"transmitting a dummy
   completion descriptor on the requester completion interface"* with error code
   `1001`. **This design deliberately does not** (`pcie_rq_rc_top.sv:118-120`):
   the client learns of the failure from `cpl_timeout_valid_o`/`_tag_o`, a
   sideband strobe. The FSM must never wait for such a descriptor.
2. **RC descriptor Error Code `0011` is unreachable** by construction
   (`pcie_rc_if.sv` KNOWN_GAPS; `tlp_request_tracker.sv:127-135` suppresses the
   result and raises `unexpected_completion_o` instead). The FSM watches
   `rc_unexpected_completion_o`, never error code `0011`.
3. **Completion-timeout timer restart on partial completion is
   implementation-defined** (existing, `ef32bcd` header). Restated for
   completeness; config completions never split (Dword Count is always 1 —
   §2.2.7 p.79), so enumeration cannot reach the case.
4. **No CRS Software Visibility** (§5.2). Optional per §2.3.2 p.121.
5. **Single-shot enumeration, no retrain re-entry.** Tracker §20.4: a retrain
   that drops `link_up_i` without `rst_i` clears the credit pools with no fresh
   init pulse and wedges TX. The FSM requires the four preconditions at start and
   does not support re-entry; documented in the module header with the reference.

6. ⚠️ **MEASURED IN 2b-1 — the RC1 signature in `pcie_rq_rc_top.sv:33` is wrong
   about the tag.** It states that with flow control uninitialised there is
   "no TLP on `m_dllp_axis_*`, no pulse on any error output, **no tag on
   `pcie_rq_tag_o`**". The last clause does not hold: a tag **is** allocated and
   presented. The credit gate is at the VC-buffer-to-transmit boundary
   (`tlp_layer.sv:280`), *downstream* of allocation in `REQ_TAG`
   (`tlp_requester.sv:138`, `:211`), which references neither `fc_initialized_i`
   nor any credit signal. Pinned by test **I8**.
   **Consequence for the 2b-2 sequencer: a tag strobe is NOT evidence that a
   request reached the link.**

7. ⚠️ **MEASURED IN 2b-1 — the completion timer runs from ALLOCATION, so a long
   credit stall produces a spurious timeout.** `tlp_request_tracker.sv:39`
   measures per-tag age "from ALLOCATION", and by finding 6 allocation precedes
   the credit gate. A request starved of credit for longer than
   `CPL_TIMEOUT_CYCLES` therefore **times out without ever being transmitted**,
   and reports as `TXN_TIMEOUT` — indistinguishable from a dead device, with no
   error output anywhere. Predicted and confirmed by test **I9**.
   **This bounds the master brief §4.1.** Its requirement that the FSM tolerate
   `tx_fc_blocked_o` "for arbitrary spans — no cycle-count assumptions" cannot be
   met above ~4096 cycles of continuous starvation by *any* FSM against this
   stack; the limit is in the tracker, not in the enumeration logic. Raising
   `CPL_TIMEOUT_CYCLES` toward the spec's recommended 10 ms (Stage-H work, see
   `pcie_rq_rc_top.sv:114-117`) is what actually moves it.

---

## 7. Socket-model mutation set (bench-as-RTL discipline)

The 2b-1 standalone socket model is bench code that behaves like RTL, and a
socket model that is *too polite* hides exactly the bugs the standalone target
exists to catch (`RECON_commit2b.md` §5.2.6). Each mutation below is seeded into
the socket model and **must fail at least one standalone test** before 2b-1 is
accepted.

**RESULTS FILLED IN 2026-07-29 at `3098c37` (Commit 2b-1).** The standalone
target is `verilate_enum_txn` (E1..E14); the integration target is
`verilate_enum_txn_tlp` (I1..I9).

| id | mutation to the socket model | why it is dangerous | MEASURED RESULT |
|---|---|---|---|
| **SM-1** | tag strobed in the same cycle the command is accepted, instead of ≥1 cycle later | The real socket cannot present the tag at accept time (`pcie_rq_rc_top.sv:56-60`). | **KILLED — all 14** (E1–E14). `awaiting_tag_r` is armed *by* the descriptor handshake, so a same-cycle strobe is never captured, no completion ever matches, and every test needing a response fails. The strongest kill in the set. |
| **SM-2** | `s_axis_rq_tready` held high forever | Hides every backpressure bug; §4.1 requires tolerating arbitrary-length stalls. | **KILLED — E12** (`e12_arbitrary_tready_stall`), which asserts zero packets emitted during a 400-cycle stall. |
| **SM-3** | `RC_ERR_ORPHAN_DATA` burst omitted after a late CPL | *(this prediction was wrong about where the burst lives)* | **NOT EXPRESSIBLE STANDALONE — moved to integration.** The burst is `rc_protocol_error_o`, a `pcie_rq_rc_top` **output** the primitive deliberately does not consume (it needs transparency, not counting), so it cannot cross the socket the standalone bench drives. Its kill lives in **I4**, which asserts the exact per-Dword orphan count V9-style through the real `pcie_rc_if`. **E10** is the standalone stand-in: the socket-visible half of a late completion is a stray packet bearing a stale tag. |
| **SM-4** | tag forced to 0 on every request | Degenerate value space — a tag-match assertion over an all-zero tag proves nothing. | **KILLED — 8 tests**: E1, E3, E6, E7, E8, E9, E10, E11. The explicit non-zero/distinct guards fire before anything relies on the tag. |
| **SM-5** | completion delivered with `request_completed` (bit 30) always 1, even on a non-final CPL | Bit 30, not `tlast`, releases the request (PG213 `:4049`). | **COVERED BY E14**, which drives the converse — bit 30 *clear* with `tlast` set — and is the test that killed RTL mutation M5. E14 already forces the two fields apart, which is the property. |

SM-5 was added beyond the brief's four because bit 30 is the single most
load-bearing field in the RC descriptor. That judgement paid: the corresponding
**RTL** mutation was the one survivor of the seven-mutation RTL set, and closing
it needed a new test rather than a strengthened assertion.

**RTL mutation results (Commit 2b-1), for the record:**

| mutation | standalone kill | integration |
|---|---|---|
| tag-match defeated (accept any completion) | E10, E11 | **survives — structurally.** The tracker never delivers a mismatched completion to the RC stream; it raises `rc_unexpected_completion_o` with no RC packet (`pcie_rq_rc_top.sv:266-267`). |
| CRS cap removed | E8 | — |
| timeout strobe ignored | E9, E10 | — |
| reserved-status arm removed (bare `default`) | E6 | — |
| **complete on `tlast` instead of bit 30** | **E14 — a NEW test; survived E1–E13** | **survives — structurally.** The tracker cannot produce a config completion with bit 30 clear. |
| retry rebuilt from response data | E7, E8 | — |
| `rsp_valid_o` pulsed instead of held | E13 | — |
| *(bench)* credit drip re-pulses a constant instead of a cumulative total | n/a | **I5** — proving I5 measures the DUT, not the coroutine |

The two integration survivors are the standalone/integration blind-spot
asymmetry, measured in both directions rather than argued: neither is a missing
test, and both properties are covered standalone. Same lesson as 2a-ii mutation
A (survived all integration) and 2a-iii M4 (survived all standalone), and it is
why both targets exist.

---

## 8. Predicted FAIL set for 2b-1 falsification

Per brief §1, the new tests are run against **pre-2b-1 HEAD** before the RTL
lands, and the expected FAIL set is recorded *first*.

| # | prediction | mechanism |
|---|---|---|
| **F1** | **Every** 2b-1 test fails at **elaboration**, not at runtime, against `eb19032`. | `pcie_enum_fsm` and `pcie_enum_pkg` do not exist; `tb_pcie_enum_txn.sv` instantiates a missing module. Verilator exits non-zero before any cocotb test runs, so the log shows a build failure and `TESTS=0` — **not** `TESTS=n FAIL=n`. |
| **F2** | Distinguishing signature: `%Error: ... Cannot find file containing module: 'pcie_enum_fsm'`. | If instead the targets elaborate and tests fail at runtime, the falsification is invalid — something already defines the module and the increment is not additive. **Stop-and-report.** |
| **F3** | **P-NPD-INF** passes *against pre-2b-1 HEAD too*, if written as a pure credit-manager observation. | It asserts a property of `tlp_credit_manager`, not of the FSM. A credit-vector test that passes without the FSM is measuring the wrong thing — it must be written to observe *FSM progress*, not just `tx_fc_blocked_o`. Recorded so it is not mistaken for coverage. |
| **F4** | **P-RC1** likewise needs FSM stimulus to be non-vacuous. | With no FSM there is no descriptor, so "zero TLPs" is trivially true. The RC1 control must assert that the FSM *tried* — e.g. `s_axis_rq_tvalid` was seen high — before asserting the wire stayed silent. |

F3/F4 are the falsification run's real product: two tests that would have looked
green for the wrong reason.

### 8.1 MEASURED (Commit 2b-1, `3098c37`)

| # | predicted | measured | verdict |
|---|---|---|---|
| **F1** | elaboration failure, `TESTS=0`, not `TESTS=n FAIL=n` | **Commit A:** exit 1, **zero `TESTS=` lines**. **Commit B:** same. | ✅ confirmed, both halves |
| **F2** | signature `Cannot find file containing module: 'pcie_enum_fsm'` | **Commit A:** `%Error: ... Import package not found: 'pcie_enum_pkg'`. **Commit B:** `%Error-MODMISSING: ... Cannot find file containing module: 'pcie_cfg_txn'`. | ⚠️ **partially diverged, benignly.** The module is named `pcie_cfg_txn`, not `pcie_enum_fsm` (2b-1 brief's design decision). And in the standalone half Verilator resolves the shim's **package import** before the instance, so the package — not the module — is the first unresolved symbol. Same mechanism, different first-failing symbol. |
| **F3** | a credit test written as a pure `tx_fc_blocked_o` observation would pass without the FSM | acted on rather than measured: **I5** asserts DUT progress (every transaction reaches `TXN_OK`) and `blocked_seen`, so it cannot pass without the primitive. **I6/I7** likewise assert outcomes, not just the blocked signal. | ✅ designed out |
| **F4** | "zero TLPs" is vacuous without proof the FSM tried | acted on: **I8** asserts `mon.rq_tvalid_seen` **before** asserting silence, then brings FC up and shows the same command completes. | ✅ designed out |

F2's divergence is worth keeping: the predicted *string* was wrong while the
predicted *mechanism* was right, which is the normal outcome when a prediction
names an artefact rather than a behaviour.

Per-test predictions sharpen when the 2b-1 test list is drafted; the structure
and the four firm entries are committed now.

---

## 9. What I need to close §0.2 (BAR / Command-register citations)

Everything tagged `[PCI3-REF]` — BAR bits `[0]`, `[2:1]`, `[3]`, the
write-all-ones sizing algorithm, and Command register bits 0/1 — has its
normative home in **PCI Local Bus Specification 3.0 §6.2.5.1 / §6.2.2**, which
Base 2.1 incorporates by reference but which is not on the shelf.

Three ways to close it, in my order of preference:

1. **Add PCI 3.0 to the spec shelf** and re-cite those constants properly. Small
   effort, permanently removes the gap, and Commits 3/4 (Type 1 headers, bridge
   windows, bus-number assignment) will need it far more than 2b does — every
   Type 1 register in Figure 7-6 p.492 has the same problem.
2. **Accept `[PCI3-REF]` as-is** for 2b, on the grounds that the values are not
   in genuine doubt and §7.5.2.1 p.491-492 independently constrains the two
   things that actually matter (prefetchable/64-bit coupling, and the 128-byte
   minimum that catches the pair-decode mutation by spec).
3. Cite MindShare for the bit layout — **I do not recommend this**; brief §2 is
   explicit that MindShare is background and never golden, and a golden sourced
   from a textbook is exactly the comparison-against-non-spec the project bans.

Proceeding on **(2)** unless told otherwise, with every affected constant tagged
in place so the debt is visible and mechanically greppable rather than buried.

---

## 10. Summary of stop-and-report items raised

| # | item | severity | blocks 2b-1? |
|---|---|---|---|
| 1 | **P-NPD0 inverted** — `NPD=0` at init means infinite; the brief's and the recon's stated prediction is wrong (§0.1) | **High** — would have produced a vacuous "passing" credit test | No. Corrected here; P-NPD-INF / P-NPD1-STALL replace it. |
| 2 | **BAR sizing + Command bits 0/1 are not in Base 2.1** (§0.2, §9) | Medium — citation quality, not correctness | No. Tagged `[PCI3-REF]`; proceeding on option (2). |
| 3 | **Probe timeout ⇒ FAULT** (§5.3) — the derivation resolved *against* the "absent-continue" reading | Medium — and it imposes a hard requirement on the bench completer | No, but §5.3's harness consequence must be built into the 2b-2 completer from the start. |
| 4 | **Reserved completion status must map to UR**, not to a bare `default` (§5.1) | Low, but an X-prop/latch hazard in a `unique case` | No. |
| 5 | Baseline was **30/172**, not the recon's 29/171 (§1) | Resolved | No. |

None of these blocks 2b-1. Items 1 and 3 change what the 2b-1/2b-2 tests must
look like, which is precisely what Phase 1 is for.

---
---

# D. Commit 2b-2 addendum — the presence scan

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` @ `2d8c216` · **written before
`pcie_enum_scan` exists.** Same rule as the rest of this document: a later
disagreement is a DUT bug or a prediction bug, never a golden fitted to
observed behaviour.

---

## ⛔ D.1 THE DEVICE-NUMBER DERIVATION — the answer changes the FSM's shape

**Question:** does an RC's presence scan on a directly-attached link legitimately
cover device numbers **0–31**, or only **device 0**?

**Answer: device 0 ONLY. `DEVICES_TO_SCAN = 1`. The 0–31 loop must not exist in
this FSM.** Two independent sentences of Base 2.1 §7.3.1 p.479 settle it, and
the second is the one that makes the loop actively harmful rather than merely
wasteful.

### D.1.1 Device 1–31 never reaches the link  **[BASE §7.3.1 p.479]**

> *"Switches and Root Complexes Downstream Ports that do not have ARI Forwarding
> enabled **must associate only Device 0** with the device attached to the
> Logical Bus representing the Link from a Switch Downstream Port or a Root
> Port. Configuration Requests targeting the Bus Number associated with a Link
> specifying **Device Number 0 are delivered to the device attached to the
> Link**; Configuration Requests specifying **all other Device Numbers (1-31)
> must be terminated by the Switch Downstream Port or the Root Port with an
> Unsupported Request Completion Status** (equivalent to Master Abort in PCI)."*

In a conventional RC the enumerating software *does* sweep 0–31, and sees UR for
1–31 — but that UR is **synthesized by the Root Port's own downstream-port
logic**, and the request never goes on the wire.

**This design has no such logic.** `pcie_enum_scan → pcie_cfg_txn →
pcie_rq_rc_top` originates the Type 0 request straight onto the link; the CQ/CC
completer surface is tied off (`pcie_rq_rc_top.sv:83-99`) and there is no
Root-Port request-termination path anywhere in the tree. A request naming
device 5 would therefore be *transmitted*, which §7.3.1 forbids.

### D.1.2 …and if it did reach the link, the device would answer it  **[BASE §7.3.1 p.479]**

> *"Non-ARI Devices must not assume that Device Number 0 is associated with their
> Upstream Port, but must capture their assigned Device Number as discussed in
> Section 2.2.6.2. **Non-ARI Devices must respond to all Type 0 Configuration
> Read Requests, regardless of the Device Number specified in the Request.**"*

This is the decisive one. A device is *required* to answer a Type 0 config read
whatever device number it names. So a 0–31 sweep on a direct-attach link, in a
design with no Root-Port filter, would not discover one device and 31 absences —
**it would discover the same device 32 times**, each with identical Vendor/Device
ID, and a sequencer that stopped at "first device found" would be right only by
accident of iteration order.

### D.1.3 Consequences, stated

- **`DEVICES_TO_SCAN = 1`**, a documented constant, not a parameter. There is no
  device loop and no `DEV_SCAN_MAX`.
- §7.3.1's termination rule is satisfied **by construction**: no request naming
  device 1–31 is ever formed, so there is nothing to terminate. This is a
  structural equivalence, not a deviation — a compliant RC's *software* would see
  UR for those device numbers; our *hardware* enumerator simply never asks.
- Building the Root-Port termination path is out of scope for Commit 2b and is
  not needed by anything 2b does. It becomes relevant only when a **switch** can
  appear below the port, i.e. Commits 3/4, where Type 1 and bus-number assignment
  arrive together. Recorded as a Stage-3 item.
- ⚠️ **The §5.2 "flagged trap" is largely defused by this derivation.** The trap
  was that a completer ignoring unmodelled BDFs would drive the FSM to a
  timeout-induced sticky ERROR on the first empty device number. With no empty
  device numbers to probe, that path is unreachable. The completer still needs a
  **UR** arm — see D.5 — but for a different reason: an attached device whose
  Function 0 is unimplemented.

### D.1.4 What "absent" now means

The link is point-to-point and `link_up_i` is a precondition, so a device *is*
attached whenever the scan runs. Absence therefore cannot mean "no device on the
link". It means **"nothing here to enumerate"**, and the spec gives exactly one
signal for it:

> **[BASE §7.3.1 p.479]** *"Any Type 0 Configuration Request targeting an
> unimplemented Function in an ARI Device must be handled as an Unsupported
> Request."*

plus the general Endpoint rule **[BASE §7.3.3 p.480]**: a Type 0 request that
does not address "a valid local Configuration Space of an implemented Function"
→ *"follow rules for handling Unsupported Requests"*.

So `TXN_UR` on the device-0 probe → **`device_present_o = 0`, terminal state
`SCAN_DONE` with no device**, not ERROR. Every other non-OK outcome is a fault.

---

## D.2 Multi-function — capture only, do not scan

**Decision: capture the multi-function bit and stop there.** Functions 1–7 are
not probed in 2b-2.

**[BASE §7.3.1 p.479]** permits *"up to eight independent Functions within that
Device Number"*, and **[BASE §7.3.2 p.480]** says PCI Express *"supports
multi-Function devices using the same discovery mechanism as PCI 3.0"*. So
function scanning is legitimate — it is simply not needed by anything 2b-3 does:
the direct-attach NVMe target is single-function, and BAR sizing operates on
Function 0. Scanning 1–7 would multiply the sequencer's state space for no
consumer.

`multifunction_o` is reported so the deferral is visible to 2b-3 and to Stage E
rather than silently assumed. **Deferred item: function scanning, gated on a
consumer existing.**

---

## D.3 Header Type decode

**Field position — [BASE]:** Figure 7-5 p.491 places Header Type in the Dword at
byte offset `0Ch`, byte 2 — i.e. **register 3, bits [23:16]** of the returned
Dword. The same layout appears in Figure 7-4 p.484 (common header) and
Figure 7-6 p.492 (Type 1).

**Bit fields — [PCI3-REF]:** Base 2.1 shows Header Type only in those figures and
nowhere defines its bits. Bit 7 = Multi-Function, bits [6:0] = header layout, and
the layout encodings `00h`/`01h`/`02h`, are PCI 3.0 §6.1. **Third instance of the
same debt** (BAR bit layout §0.2, Command register bits 0/1 §0.2, now Header
Type). Tagged, not hidden.

**Partially corroborated by [BASE], which is worth stating:** Base 2.1
independently establishes that the two layouts *exist* and *who uses which* —
§7.5.2 p.491 titles the Type 0 header as the one for *"PCI Express device
Functions"*, and §7.5.3 p.492 titles Type 1 as the one for *"Switch and Root
Complex virtual PCI Bridges"*. So the **meaning** of the distinction is [BASE];
only the numeric encoding is [PCI3-REF]. That is enough to justify the FSM's
behaviour even before PCI 3.0 is on the shelf.

**Prediction:** `header_layout != 00h` → terminal state
**`SCAN_UNSUPPORTED_DEVICE`**, *not* `SCAN_ERROR`. A Type 1 response means a
bridge or switch is attached — a valid device that answered correctly and that
this commit simply cannot enumerate (Commits 3/4). Reporting it as an error
would conflate "the link misbehaved" with "the topology is richer than I
handle", and only the first is a fault.

`header_type_o[7:0]` reports the raw byte, so a consumer can tell `01h` from
`02h` without the FSM having to enumerate encodings it does not act on.

---

## D.4 Exact RQ descriptors for the scan

The scan emits exactly two transactions, and both descriptors are **already
pinned in §3.4** — deliberately, so 2b-2 introduces no new goldens:

| # | transaction | type | reg | first_be | `s_axis_rq_tdata[127:0]` | on-wire DW2 |
|---|---|---|---|---|---|---|
| **D-P** | Vendor/Device ID probe | CfgRd0 `1000` | 0 | `0b1111` | `0x00010000000040010000000000000000` | `0x01000000` |
| **D-H** | Header Type read | CfgRd0 `1000` | 3 | `0b1111` | `0x0001000000004001000000000000000C` | `0x0100000C` |

Target BDF `0x0100` = bus 1, device 0, function 0. Bus number is an input
(`scan_bus_i`), so the goldens above are for the default; the assertion helper
rebuilds them from the driven bus number.

Both are `dword_count=1`, `last_be=0000`, `tc=0`, `attr=0`, per **[BASE §2.2.7
p.79]**, and the routing Dword is **[BASE Figure 2-18 p.80]**. Descriptor field
positions **[PG213 Table 61 `:3711,:3720,:3728,:3735`]**.

**BE choice for D-H: whole Dword (`1111`), not byte-granular `0x0E`.** Three
reasons, in order of weight:

1. It returns Cache Line Size, Master Latency Timer, Header Type **and** BIST in
   one completion — strictly more information at identical transaction cost, and
   §2.2.7 p.79 fixes the Length at 1 Dword either way, so the byte-granular form
   saves nothing on the wire.
2. The byte-granular config-read path already has three independent exercises
   (V2 in `verilate_rq_rc_top`, E2/E3 standalone, I2 integration). A fourth here
   would add no coverage.
3. §3.6 already made this exact call for E3 over E2, for the same reason.
   Consistency is worth more than variety.

The FSM extracts Header Type from bits `[23:16]` of the returned Dword (D.3).

---

## D.5 Outcome → policy, phase-dependent

This is the deliverable of the whole increment: `pcie_cfg_txn` reports what
happened, and this table is the only place that decides what it *means*.

| `txn_outcome_e` | during the probe (D-P) | after the probe (D-H) | citation |
|---|---|---|---|
| `TXN_OK` | device present; capture Vendor/Device ID | capture Header Type; advance | — |
| `TXN_UR` | **absent** → `device_present_o=0`, `SCAN_DONE` | **ERROR** `ENUM_ERR_UR_POST_PROBE` | §7.3.1 p.479, §7.3.3 p.480, §2.3.2 IN p.122 |
| `TXN_CA` | ERROR `ENUM_ERR_CA` | ERROR `ENUM_ERR_CA` | §2.3.2 p.120, p.122 |
| `TXN_CRS_EXHAUSTED` | ERROR `ENUM_ERR_CRS_EXHAUSTED` | ERROR (same) | §2.3.2 p.121-122 |
| `TXN_TIMEOUT` | **ERROR** `ENUM_ERR_TIMEOUT` | ERROR (same) | §2.8 p.152; §5.3 above |

The `TXN_UR` row is the entire justification for the two-module split: the same
wire event is *normal termination* in one phase and *fault* in the next, and
`pcie_cfg_txn` has — deliberately — no idea which phase it is in.

### D.5.1 The all-1s payload question: **unreachable as an absence signal, by construction**

**[BASE §2.3.2 Implementation Note p.122]** *"Some system configuration software
depends on reading a data value of all 1's when a Configuration Read Request is
terminated as an Unsupported Request … **A Root Complex** intended for use with
software that depends on a read-data value of all 1's **must synthesize this
value** when UR Completion Status is returned for a Configuration Read Request."*

Read carefully, that note describes a synthesis performed **by the Root Complex,
for software above it**. `pcie_enum_scan` sits where the synthesis would be
*performed*, not where it would be *consumed*: it observes the UR itself, as
`TXN_UR`, because `pcie_cfg_txn` classifies completion status directly.

Therefore:

- **Absence is signalled by `TXN_UR` and by nothing else.** The FSM must **not**
  treat `vendor_id == FFFFh` as absence. The all-1s convention exists precisely
  because software *cannot* see the UR; we can, so re-deriving it from a sentinel
  would discard information the spec took care to keep distinguishable.
- A `TXN_OK` carrying `FFFFFFFF` is a device that answered successfully with that
  data. It is reported as **present**, with `vendor_id_o = FFFFh`. Odd, and
  almost certainly a broken completer — but it is not this module's job to
  reinterpret a Successful Completion.
- **Asserted, not just documented:** a standalone test drives an SC probe
  returning `0xFFFFFFFF` and requires `device_present_o = 1`. Silent conversion
  to absence would pass an unasserted design.
- If a future MMIO host interface is added (deferred, master brief §13), the
  all-1s synthesis belongs *there*, at the software boundary — not here.

---

## D.6 Credit-starvation annotation (Finding 2)

`err_credit_blocked_o` is sampled from `tx_fc_blocked_o` **at the moment a
`TXN_TIMEOUT` is reported** and presented alongside `scan_error_code_o`.

**It is annotation, never control flow.** The state transition on `TXN_TIMEOUT`
is `SCAN_ERROR` regardless of its value, and `tx_fc_blocked_o` does not appear in
any next-state expression. Master brief §4.1 forbids a credit signal gating
control flow, and that prohibition is what mutation `M-CREDIT-CTRL` (§5.5) exists
to enforce: forcing `tx_fc_blocked_o` both ways must produce **identical state
sequences**.

**Predicted signature of the Finding-2 test:**

```
scan_error_o        = 1
scan_error_code_o   = ENUM_ERR_TIMEOUT
err_credit_blocked_o= 1
scan_done_o         = 0
completer.seen      = <unchanged>   -- the request never reached the wire
rq_errors, command_errors, tx_errors, credit_errors = all empty / zero
```

i.e. the I9 signature, one layer up, plus the annotation bit.

**Recorded plainly for the tracker owner:** no FSM above this stack can ride out
continuous credit starvation beyond `CPL_TIMEOUT_CYCLES`. The limit is
`tlp_request_tracker.sv:39` — per-tag age is measured from **allocation**, and
allocation precedes the credit gate (`tlp_layer.sv:280` vs
`tlp_requester.sv:138`). Only raising `CPL_TIMEOUT_CYCLES` toward the ~10 ms the
spec recommends moves it, and that is Stage-H work tied to the Device Control 2
register (§7.8.16). Annotating is the most any client can do; **fixing it is not
a client-side problem.**

---

## D.7 Predicted FAIL sets for the falsification runs

| # | run | prediction |
|---|---|---|
| **DF1** | Commit C: `verilate_enum_scan` with the bench wired and `pcie_enum_scan.sv` absent from `rc_core.core` | Elaboration failure, **zero `TESTS=` lines**, exit non-zero. Expected symbol `%Error-MODMISSING: … Cannot find file containing module: 'pcie_enum_scan'` — the F2 form rather than the F1 package form, because `pcie_enum_pkg` will already be present (extended in the same commit). |
| **DF2** | Commit D: `verilate_enum_scan_tlp` likewise | Same, naming `pcie_enum_scan` from the integration shim. |
| **DF3** | any scan test that asserts only "no TLP emitted" | Vacuous without proof the FSM *tried* — the F4 lesson. Every silence assertion in the scan suite must first establish that a command was accepted and `s_axis_rq_tvalid` was observed. |
| **DF4** | the absence test (`TXN_UR` on the probe) | Must assert `scan_done_o=1` **and** `device_present_o=0` **and** `scan_error_o=0`. Asserting only `device_present_o=0` would pass against a design that never ran, since the port resets to 0. |

DF4 is the one worth writing down: `device_present_o` is reset-low, so the
obvious absence assertion is satisfied by a dead FSM.

---

## D.8 Measured results (Commit 2b-2, `c05ef1b`)

### D.8.1 Falsification

| # | predicted | measured | verdict |
|---|---|---|---|
| **DF1** | `verilate_enum_scan`: elaboration failure, zero `TESTS=`, `MODMISSING … 'pcie_enum_scan'` | exit 1, zero `TESTS=` lines, `%Error-MODMISSING: … Cannot find file containing module: 'pcie_enum_scan'` | ✅ exact |
| **DF2** | `verilate_enum_scan_tlp`: same, from the integration shim | identical, at `tb_pcie_enum_scan_tlp.sv:175` | ✅ exact |
| **DF3** | silence assertions must first prove the FSM tried | acted on: the RC1 control was run once in 2b-1 (`i8`) with `rq_tvalid_seen` asserted first, and is not repeated here | ✅ designed out |
| **DF4** | the absence test must assert `scan_done_o` and `scan_error_o`, not just `device_present_o` (reset-low) | `s2` and `k2` assert all three | ✅ designed out |

### D.8.2 RTL mutations — standalone, all killed first pass

| mutation | killed by |
|---|---|
| UR during probe → ERROR (policy inversion) | `s2` |
| UR after probe → absent (inverse inversion) | `s3` |
| timeout during probe → absent (Phase-1 derivation inverted) | `s7`, `s14`, `s15` |
| scan restarts after `scan_done_o` | `s1`, `s2`, `s9`, `s10`, `s12`, `s13` |
| Vendor/Device ID halves swapped | `s1`, `s3`, `s13` |
| Header-Type layout bits ignored (Type 1 accepted as Type 0) | `s8` |
| MF bit read from bit 6 instead of bit 7 | `s9` |
| `tx_fc_blocked_i` steers control flow | `s14` |

### D.8.3 RTL mutations — integration, and the two that needed new tests

| mutation | integration result |
|---|---|
| UR during probe → ERROR | killed by `k2` |
| `tx_fc_blocked_i` steers the **probe-phase** timeout arm | **survived K1–K6, then survived K7, killed only by K8** |

The second row is the session's main verification lesson and is worth keeping:

1. It survived K1–K6 because **both** existing timeout tests (`k5`, `k6`) time
   out during the **header** phase. The integration suite never reached the
   mutated arm.
2. `k7` was added — a device that never answers its first probe — which does
   reach the probe-phase arm. **It still survived**, because `k7` runs with
   saturated credit, so `tx_fc_blocked_i` is low and the mutated branch is not
   taken.
3. `k8` produces the only killing combination: a probe-phase timeout **while
   credit-blocked** — a CRS-answering device behind a peer advertising the
   Table 2-37 minimum of one NPH credit, where the first attempt spends the
   credit and the retry, still in the probe phase, can never be sent.

Together `k7` and `k8` are what make `err_credit_blocked_o` a diagnostic rather
than decoration: it must be **clear** for a dead device and **set** for a
starved one, and no single test can establish that.

### D.8.4 Bench mutations

| mutation | result |
|---|---|
| socket invariant 1 — completion delivered before the tag strobe | killed 12 of 15 standalone tests |
| socket invariant 2 — timeout strobe before the tag strobe | **survived**; every timeout test happened to `settle()` first. Closed with a new test, **`s16`**, which fires the timeout at the earliest legal moment. Same shape as 2b-1, where `e9` passed only by settling and `e10` caught it. |
| socket invariant 3 — the guard itself removed and `tag_delay = 0` | **survived, and unfalsifiable through this path** — see below |
| socket invariant 3, *property* version (pre-arm the strobe before `ReadOnly`) | killed **all 16** |
| completer's UR default arm replaced with silence | killed `k2` — the Phase-1 trap, made falsifiable |
| credit drip re-pulses a constant instead of a cumulative total | killed `k4` |

⚠️ **Invariant 3's assertion cannot fire, and that is worth recording rather
than patching.** `_arm_tag()` runs inside the `ReadOnly` phase, and cocotb
defers any signal write out of `ReadOnly` to the next writable phase. So even
with `tag_delay = 0` the strobe physically lands in the cycle *after* the
descriptor accept, and `self.cycle > accept_cycle` is always true. The guard is
defence-in-depth against a future refactor that moved the strobe earlier; it is
not load-bearing today.

The **property** it protects is load-bearing and is tested: pre-arming the
strobe before `ReadOnly` (the shape 2b-1's SM-1 used) makes the socket present
the tag in the accept cycle, `awaiting_tag_r` is still low, the tag is never
captured, and all 16 tests fail.

### D.8.5 Scope adaptation recorded in `k6`

The brief asked for "late CPL mid-scan → **scan continues**". That is
unreachable by construction: `late_cpl_valid_o` fires only for a tag in ZOMBIE
quarantine, which requires a completion timeout first, and a timeout is terminal
for this sequencer (§D.5). With one transaction in flight there is no second tag
to continue on.

`k6` asserts the property that *is* reachable and is what actually matters — the
orphan-data burst must not add an error, change the error code, or move any
status output — with the exact per-Dword count, V9-style.

### D.8.6 Baseline after 2b-2

> **29 targets / 171 tests (23 TLP + 6 RC) + `verilate_conformance` control 1/1
> = 30 / 172**, plus `verilate_enum_txn` 14/14, `verilate_enum_txn_tlp` 9/9,
> `verilate_enum_scan` 16/16 and `verilate_enum_scan_tlp` 8/8
> → **34 targets / 219 tests**.

All 32 pre-existing targets identical in count, verdict and sim end time.
