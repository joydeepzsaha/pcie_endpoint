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

> ### ✅ Citation debt discharged, 2026-07-29 (Commit 2b-3)
>
> **Second normative source added to the shelf:** PCI Local Bus Specification
> 3.0, as text (`/home/kourosh/openPCIE/0.doc/pci-local-bus-3.0.txt`, 16433
> lines), cited as **[PCI3] §section p.page `:line`**. Line anchors were verified
> identical across two independent extractions.
>
> This closes **§0.2** and discharges option (1) of **§9**. The **`[PCI3-REF]`**
> tag — "normative source is PCI 3.0 … not readable on this shelf; citation
> pending" — is **RETIRED**. All eleven occurrences have been replaced in place
> with real citations; where the tag still appears below it is marked
> ~~struck~~ and kept only so the historical record of §9/§10 stays readable.
>
> ⚠️ **Page convention for [PCI3]:** the page number in this extraction is a
> **footer**, printed at the *end* of the page it labels. Content following
> marker *N* is on page ***N+1***. See §E.0.
>
> No prediction changed. As §0.2 anticipated, the debt was only ever about
> numeric constants, never about FSM shape — but the constants are now cited
> rather than asserted from convention. Full anchor table in **§E.0**.

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

My own `docs/recon/RECON_commit2b.md` §2.3 asserted the same wrong thing. **Both are
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
Space defined in PCI 3.0"*) but which was **not on the spec shelf** when this
section was written (brief §2 listed only Base 2.1, PG213, MindShare, Southwell).

> ✅ **RESOLVED in Commit 2b-3.** PCI 3.0 is now on the shelf and every constant
> named in this section carries a real **[PCI3]** citation. See the header note
> and **§E.0**. The paragraph above is kept as written because it is what
> motivated adding the source; the gap it describes no longer exists.

Every constant below carries an explicit **citation-status** tag:

| tag | meaning |
|---|---|
| **[BASE]** | cited to PCIe Base 2.1, section + page. Golden. |
| **[PG213]** | cited to PG213 by line. Interface shape only, never protocol. |
| **[PCI3]** | cited to PCI Local Bus 3.0, **section + page + line**. Golden. Added 2b-3. |
| ~~**[PCI3-REF]**~~ | ~~normative source is PCI 3.0 … not readable on this shelf; citation pending.~~ **RETIRED 2b-3** — every occurrence replaced with a **[PCI3]** citation. |

**This was a gate, not a blocker — and the gate is now open.** Nothing tagged
`[PCI3-REF]` ever changed the FSM's *shape*, only the numeric constants in the
BAR decode and the Command-register bit positions. §9 stated what was needed to
close it; **§E.0 records that it was closed by option (1)**, adding the source.

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
`docs/spec-notes/STACK_INVENTORY.md` §0.1/§2.1 mis-attributed the +1 and declared a prior "152" a
bookkeeping slip, and `docs/recon/RECON_commit2b.md` inherited that exclusion. The control
is a **separate line item** and is neither folded into the TLP+RC subtotal nor
dropped from the grand total. Prior art: `docs/recon/RECON_commit2a.md §G`,
`docs/predictions/SPEC_PREDICTIONS_CPL_TIMEOUT.md §G`.

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

**Correction to `docs/recon/RECON_commit2b.md` §2.3 and brief §3.** Brief §3's *"config
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

> ✅ **Citation status: DISCHARGED in Commit 2b-3.** Every value below now carries
> a **[PCI3]** citation (section + page + line). **§E.1-E.3 is the current,
> fully-cited statement of this material** and supersedes this section on any
> point of detail; §4 is retained because §4.4's assignment policy and the
> `MEM_BAR_BASE`/`BAR_BASE` warning are referenced from later sections.
>
> Originally written when PCI 3.0 was off the shelf (§0.2). The observation that
> motivated the tag still stands and is worth keeping: **Base 2.1 gives the
> offsets and the usage policy; it does not define the BAR bit layout or the
> sizing algorithm.** That is precisely why the second source was needed.

### 4.1 BAR bit layout  **[PCI3 §6.2.5.1 p.225-226 `:11187`,`:11190`,`:11193`,`:11205`,`:11207`]** — full statement in §E.1

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

### 4.2 Sizing algorithm  **[PCI3 §6.2.5.1 p.226 `:11222`-`:11226`]** — full statement in §E.2

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

### 4.3 The 64-bit pair rule  **[PCI3 Table 6-4 §6.2.5.1 p.226 `:11207`]**, cross-checked **[BASE p.491-492]** — full statement in §E.3

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
exists to catch (`docs/recon/RECON_commit2b.md` §5.2.6). Each mutation below is seeded into
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

## 9. ✅ CLOSED — what I needed to close §0.2 (BAR / Command-register citations)

> **Resolved 2026-07-29, Commit 2b-3, by option (1).** PCI 3.0 was added to the
> shelf and every constant re-cited. The section is kept unedited below as the
> record of the decision; **§E.0 is the discharge**. Option (2), which this
> section was proceeding on, was never needed. Option (3) was correctly refused.
>
> The forward-looking claim in option (1) — that Commits 3/4 would need the
> source far more than 2b does — is already bearing out: **§E** cites PCI 3.0 for
> the Header Type layout encodings and the Expansion ROM offset as well as for
> the BAR material, and Stage D's Type 1 header lives in the same chapter.

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
| 2 | **BAR sizing + Command bits 0/1 are not in Base 2.1** (§0.2, §9) | Medium — citation quality, not correctness | No. ~~Tagged `[PCI3-REF]`; proceeding on option (2).~~ ✅ **CLOSED 2b-3 by option (1)** — PCI 3.0 added to the shelf, all eleven constants re-cited (§E.0). |
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

**Bit fields — ✅ [PCI3 §6.2.1 p.216 `:10685`]:** Base 2.1 shows Header Type only
in those figures and nowhere defines its bits. **Discharged in Commit 2b-3** —
this was the third instance of the §0.2 debt (BAR bit layout, Command register
bits 0/1, then Header Type) and the one discharge that falls outside §4's BAR
material. The normative text, quoted:

> *"**Bit 7** in this register is used to identify a **multi-function device**.
> If the bit is 0, then the device is single function. If the bit is 1, then the
> device has multiple functions. **Bits 6 through 0** identify the layout of the
> second part of the predefined header. The encoding **00h** specifies the layout
> shown in Figure 6-1. The encoding **01h** is defined for **PCI-to-PCI
> bridges** … The encoding **02h** is defined for a **CardBus bridge** … **All
> other encodings are reserved.**"*

Two corrections to what this section previously asserted from convention:

1. The section number is **§6.2.1 (Device Identification)**, not §6.1 as guessed
   here before the source was readable.
2. The spec's own closing clause — *"All other encodings are reserved"* — was not
   captured. It **strengthens** the prediction below rather than changing it: an
   encoding of `03h`-`7Fh` is reserved, not merely unknown, so routing it to
   `SCAN_UNSUPPORTED_DEVICE` alongside `01h`/`02h` is the spec-aligned behaviour
   and the FSM needs no separate arm for it.

**Partially corroborated by [BASE], which is worth stating:** Base 2.1
independently establishes that the two layouts *exist* and *who uses which* —
§7.5.2 p.491 titles the Type 0 header as the one for *"PCI Express device
Functions"*, and §7.5.3 p.492 titles Type 1 as the one for *"Switch and Root
Complex virtual PCI Bridges"*. So the **meaning** of the distinction is [BASE];
only the numeric encoding is [PCI3]. That was enough to justify the FSM's
behaviour even before PCI 3.0 was on the shelf — and now both halves are cited.

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

---
---

# E. Commit 2b-3 addendum — BAR sizing, assignment, and enable

**Date:** 2026-07-29 · **Branch:** `kourosh/dev` @ `ffea7a4` · **written before
`pcie_enum_bar` and `pcie_enum_top` exist.** Same rule as the rest of this
document: a later disagreement is a DUT bug or a prediction bug, never a golden
fitted to observed behaviour.

**Baseline this section is written against:** 34 targets / 219 tests, all PASS,
reproduced at `ffea7a4` (`docs/recon/RECON_commit2b3.md` §1).

---

## ⭐ E.0 The `[PCI3-REF]` debt is DISCHARGED

`§0.2` opened this document with a citation gap: the BAR bit layout, the sizing
algorithm, the Command-register bit positions and the Header Type bit fields all
have their normative home in the **PCI Local Bus Specification 3.0**, which Base
2.1 incorporates by reference but which was **not on the spec shelf**. Eleven
constants were tagged `[PCI3-REF]` — "value stated from established hardware
convention; citation pending" — and §9 recommended closing the gap by adding
PCI 3.0 to the shelf (option 1) while proceeding on option (2).

**Option (1) has now been taken.** The shelf gained:

```
/home/kourosh/openPCIE/0.doc/pci-local-bus-3.0.txt   (16433 lines)
```

extracted from `pci-local-bus-3.0.pdf`. Line anchors were verified identical
across two independent extractions, so `:line` citations are stable.

**New citation tag, used throughout this section:**

| tag | meaning |
|---|---|
| **[PCI3]** | cited to PCI Local Bus 3.0, **section + page + line**. Golden. |

**`[PCI3-REF]` is retired.** Every one of the eleven occurrences has been
replaced in place with a real `[PCI3]` citation; the tag no longer appears in
this document except in this paragraph and in the historical record of §9/§10.
Nothing about the FSM's *shape* changed — as §0.2 predicted, the debt was only
ever about numeric constants — but the constants are now cited rather than
asserted.

⚠️ **Page-number convention, and a correction.** In this extraction the page
number is a **footer**: it appears at the *end* of the page it labels, just
before the form feed. Content following marker *N* is therefore on page ***N+1***.
A first pass at the anchor table read the markers as headers and came out one
page low throughout; the mapping below is the corrected one, cross-checked
against markers 226 (`:11248`) and 227 (`:11299`) bracketing `:11283`.

| what | section | page | line |
|---|---|---:|---|
| Header Type byte, bit 7 and layout encodings | §6.2.1 | 216 | `:10685` |
| Table 6-1 Command Register Bits (bits 0/1/2) | §6.2.2 | 218 | `:10759` |
| §6.2.5.1 Address Maps (opening) | §6.2.5.1 | 225 | `:11134` |
| I/O BAR: 32-bit, bit 0 = 1, bit 1 reserved reads 0 | §6.2.5.1 | 225 | `:11187` |
| Memory BAR: bit 0 = 0, bits 2/1 per Table 6-4, bit 3 prefetchable | §6.2.5.1 | 225 | `:11190` |
| **"Bits 0-3 are read-only."** | §6.2.5.1 | 226 | `:11205` |
| Table 6-4 Bits 2/1 Encoding (all four rows) | §6.2.5.1 | 226 | `:11207` |
| "power of 2 from 16 bytes to 2 GB" | §6.2.5.1 | 226 | `:11219` |
| **The sizing algorithm paragraph** | §6.2.5.1 | 226 | `:11222` |
| "power of two in size and are naturally aligned" | §6.2.5.1 | 226 | `:11226` |
| §6.2.5.2 Expansion ROM BAR at offset `30h` | §6.2.5.2 | 227 | `:11283` |

Figures 6-5 and 6-6 are cited **by number only, never by their extracted
rendering** — the text extractor interleaved the two captions with one figure
body, so the drawn bit positions in the `.txt` are not trustworthy. Every claim
below rests on prose lines, which are unambiguous.

---

## E.1 BAR bit layout  **[PCI3 §6.2.5.1 p.225-226]**

Discharges the former §4.1. Same values, now cited.

| bits | field | values | citation |
|---|---|---|---|
| `[0]` | Memory Space Indicator | `0` = memory BAR · `1` = I/O BAR | p.225 `:11187`, `:11190` |
| `[2:1]` | Type (memory BARs) | `00` 32-bit · `01` **reserved** · `10` 64-bit · `11` **reserved** | Table 6-4, p.226 `:11207` |
| `[3]` | Prefetchable (memory BARs) | `1` = prefetchable | p.225 `:11193` |
| `[31:4]` | Base address / size-encoding bits | writable above the alignment boundary, read-as-0 below | p.226 `:11222` |

**The load-bearing sentence** — p.226 `:11205`:

> **"Bits 0-3 are read-only."**

That single clause is what makes the sizing algorithm work at all: writing all
1's cannot disturb the type/prefetch encoding, so the readback still identifies
the BAR while its upper bits report the size. It is also the source of §E.2's
`mask = ~4'hF`, and it is the reason a bench completer that echoes writes
verbatim produces garbage (brief §7).

**I/O BARs** — p.225 `:11187`:

> *"Base Address registers that map into I/O Space are **always 32 bits wide**
> with bit 0 hardwired to a **1**. **Bit 1 is reserved and must return 0 on
> reads** and the other bits are used to map the device into I/O Space."*

So an I/O BAR is never part of a 64-bit pair and always advances the candidate
index by exactly 1.

**Memory BARs** — p.225 `:11190`:

> *"Base Address registers that map into Memory Space can be 32 bits or 64 bits
> wide … with bit 0 hardwired to a 0. For Memory Base Address registers, bits 2
> and 1 have an encoded meaning as shown in Table 6-4. Bit 3 should be set to 1
> if the data is prefetchable and reset to 0 otherwise."*

⚠️ **Both reserved encodings must be handled, not just `01`.** The former §4.1
listed `00`, `10` and `01` but omitted `11`. Table 6-4 p.226 `:11207` defines all
four rows, and `11` is Reserved exactly as `01` is. Footnote 46 (`:11243`)
records that `01` formerly meant "below 1 MB" and that *"System software should
recognize this encoding and handle appropriately"* — i.e. it is a legacy
encoding, not a free slot.

**Prediction:** a memory BAR whose `[2:1]` decodes to `01` or `11` is a **sticky
ERROR** with a distinct code, not a silent skip and not a guess at 32-bit. This
design targets PCIe endpoints, where neither encoding can legitimately appear;
treating an unknown type as 32-bit would silently mis-size the device.

---

## E.2 The sizing algorithm  **[PCI3 §6.2.5.1 p.226 `:11222`]**

The normative paragraph, quoted in full because every step below comes from it:

> *"Power-up software can determine how much address space the device requires by
> **writing a value of all 1's to the register and then reading the value back**.
> The device will **return 0's in all don't-care address bits**, effectively
> specifying the address space required. **Unimplemented Base Address registers
> are hardwired to zero.**"*

and immediately following, `:11226`:

> *"This design implies that all address spaces used are a **power of two** in
> size and are **naturally aligned**."*

### E.2.1 The committed arithmetic

For a 32-bit memory BAR at candidate register `r`:

```
1. CfgWr0 reg r, first_be=1111, data = 0xFFFFFFFF
2. CfgRd0 reg r, first_be=1111            -> readback
3. encoded = readback & ~32'hF            ; bits 3:0 are RO   [PCI3 p.226 :11205]
4. if encoded == 0  -> BAR UNIMPLEMENTED, skip, r += 1        [PCI3 p.226 :11224]
5. size = (~encoded) + 1                  ; 32-bit two's complement
```

Masks, stated once so the mutation set has a target:

| BAR kind | mask | why |
|---|---|---|
| memory | `~32'hF` (clear bits 3:0) | bits 3:0 read-only — `:11205` |
| I/O | `~32'h3` (clear bits 1:0) | bit 0 hardwired 1, bit 1 reserved-reads-0 — `:11187` |

**The I/O mask is 2 bits, not 4.** This is the "mask width wrong" mutation in
brief §7 and it is a real spec distinction, not an off-by-one: an I/O BAR has no
prefetch bit and no type field, so bits 3:2 are ordinary address bits.

### E.2.2 ⭐ Why the all-ones write cannot be skipped

A tempting simplification is to read the BAR without writing first and call a
zero readback "unimplemented". **That is wrong, and the difference is
observable.**

After reset, an *implemented* 32-bit non-prefetchable memory BAR reads
`0x00000000` — its base address is unassigned and every size bit is a don't-care
returning 0, while bits `[3:0]` are all legitimately zero (memory, 32-bit, not
prefetchable). It is **bit-for-bit identical** to an unimplemented BAR's
hardwired zero.

Only after the all-ones write do the two diverge: the implemented BAR returns its
size bits, the unimplemented one still returns zero (`:11224`). **Prediction: the
write is mandatory for correctness, not merely conventional**, and a mutation
that removes it mis-reports every unassigned 32-bit non-prefetchable BAR as
absent. (A 64-bit prefetchable BAR would survive such a mutation, reading
`0x0000000C` — which is why the mutation test must use a *32-bit
non-prefetchable* BAR to reach the condition. Brief §7's reach-the-condition
rule, applied ahead of time.)

### E.2.3 Worked examples

| case | readback | `encoded` | size |
|---|---|---|---|
| 16 KB 32-bit non-prefetchable | `0xFFFFC000` | `0xFFFFC000` | `~ + 1 = 0x4000` = 16 KB |
| unimplemented | `0x00000000` | `0x00000000` | skip (step 4) |
| 256-byte 32-bit | `0xFFFFFF00` | `0xFFFFFF00` | `0x100` = 256 B |

---

## E.3 ⭐ 64-bit BAR pairs

**[PCI3 Table 6-4 p.226 `:11207`]** — `[2:1] == 10`:

> *"Base register is 64 bits wide and can be mapped anywhere in the 64-bit
> address space."*

The pair consumes registers **N and N+1**, and the next candidate index is
**N+2**.

### E.3.1 The probe order — lazy, not speculative

The FSM cannot know a BAR is 64-bit until it has read register N. Two orders are
possible:

| order | sequence | verdict |
|---|---|---|
| speculative | W(N), W(N+1), R(N), R(N+1) | rejected |
| **lazy** | **W(N), R(N)** → *decode type* → **W(N+1), R(N+1)** | **chosen** |

**Chosen: lazy.** Rationale, in order of weight:

1. **The speculative order writes a register it may have no business writing.**
   If N turns out to be 32-bit, the all-ones already sitting in N+1 is harmless
   only because N+1 is the next candidate anyway — a coincidence, not an
   argument, and it evaporates if N is the last candidate (register 9).
2. **There is no pipelining to gain.** The stack is single-outstanding by
   construction (§2, and `pcie_enum_top` holds exactly one `pcie_cfg_txn`), so
   both orders cost four serialized transactions. Speculation buys nothing.
3. **The FSM is simpler:** one uniform "probe register" step, plus a *conditional*
   second probe. The speculative form needs a two-register write phase whose
   second half is sometimes wasted.

This is consistent with the brief's §E.3 ("all-ones to both halves, read both") —
lazy still writes and reads both halves, it just interleaves them in register
order.

### E.3.2 The combine

```
encoded64 = {readback_upper, readback_lower & ~32'hF}
size64    = (~encoded64) + 1                        ; 64-bit two's complement
```

The mask applies to the **lower half only** — bits 3:0 of the pair are the lower
register's read-only field; the upper register is 32 ordinary address bits with
no reserved field at all.

### E.3.3 The assignment write order — and why it is immaterial *here*

**Chosen: lower (N) first, then upper (N+1).**

**Whether it matters:** it does **not**, and the reason is exactly §E.5's
invariant. Between the two writes the BAR pair holds a half-updated 64-bit
address — `{old_upper, new_lower}`. On an *enabled* device that transient would
be a real hazard: the device would briefly decode a garbage address range. Here
it cannot be, because **Command bit 1 (Memory Space Enable) is still 0** — it is
0 after reset (`[PCI3]` Table 6-1 p.218 `:10759`) and this FSM does not write it
until B15, after every BAR is assigned.

So the order is chosen for legibility (ascending register order, matching the
probe order) rather than for safety, **and the thing that makes it safe is an
invariant, not the order**. Stated explicitly because it is the kind of
"harmless today" detail that becomes a bug the moment enumeration re-entry is
added (Stage H): a re-enumeration of an already-enabled device would have to
clear Command bit 1 first, and *then* the write order would matter.

### E.3.4 Predicted decode for the acceptance device

NVMe-like: BAR0/1 a 64-bit **prefetchable** 16 KB pair; BAR2-5 unimplemented.

| step | register | written | predicted readback |
|---|---|---|---|
| B1/B2 | reg 4 (BAR0, `10h`) | `0xFFFFFFFF` | `0xFFFFC00C` |
| B3/B4 | reg 5 (BAR1, `14h`) | `0xFFFFFFFF` | `0xFFFFFFFF` |

`0xFFFFC00C` decodes as bit 0 = 0 (memory), `[2:1]` = `10` (64-bit), bit 3 = 1
(prefetchable).

```
encoded64 = 0xFFFFFFFF_FFFFC000
size64    = 0x0000_0000_0000_4000 = 16384 = 16 KB     ✓
```

Base 2.1 independently corroborates that this is the *normal* shape rather than
an exotic one: prefetchable BARs **must** support 64-bit addressing
**[BASE §7.5.2.1 p.491-492]**, and a compliant memory BAR **should** be
prefetchable. **The 64-bit pair is the expected case for the target device, not
a corner case.**

---

## E.4 ⭐ The 16-vs-128-byte divergence — a mutation killer that comes free

Two specifications give different floors for a memory BAR:

| source | floor | citation |
|---|---|---|
| PCI Local Bus 3.0 | **16 bytes** | §6.2.5.1 p.226 `:11219` — *"a single memory size that is a power of 2 from 16 bytes to 2 GB"* |
| PCIe Base 2.1 | **128 bytes** | §7.5.2.1 p.491-492 — *"The minimum Memory Space address range requested by a BAR is 128 bytes."* |

**Resolution: PCIe is tighter and wins.** This design enumerates a PCI Express
link; PCI 3.0 is incorporated only for definitions Base 2.1 does not restate, and
where Base 2.1 *does* state a stricter requirement it governs. A 16-byte memory
BAR is legal PCI and **illegal PCIe**.

**Committed decision: a memory-BAR decode below 128 bytes is a sticky ERROR**,
with its own code, not a warning-and-continue.

> This is **carried forward, not newly decided.** §4.1 already committed to it
> ("the FSM should treat a sub-128-byte decode as an enumeration fault") while
> the supporting citation was still `[PCI3-REF]`. §E re-affirms the decision and
> discharges the citation; the brief's §E.4 "decide and commit" is therefore a
> confirmation step, not an open question.

Rationale for ERROR over warn-and-continue: a sub-128-byte decode is not a small
BAR, it is **evidence the decode itself is wrong**. Continuing would assign an
address derived from a size the FSM has just proved it cannot trust.

### E.4.1 Why this catches the pair mis-decode *by spec*

The brief's most interesting mutation is **"64-bit pair decoded as two
independent 32-bit BARs."** Trace it on the acceptance device:

1. reg 4 readback `0xFFFFC00C` → `[2:1]` = `10` **ignored** → treated as 32-bit
   → `encoded = 0xFFFFC000` → size 16 KB. *Plausible. No alarm.*
2. Candidate index advances by **1** instead of 2 → reg 5 is probed as a BAR in
   its own right.
3. reg 5 readback is `0xFFFFFFFF` — the upper half of a 64-bit size field.
   Decoded as a standalone 32-bit BAR: `encoded = 0xFFFFFFF0`,
   `size = ~0xFFFFFFF0 + 1 = 0x10` = **16 bytes**.
4. **16 < 128** → the E.4 floor fires.

**Prediction: the sub-128-byte check kills this mutation, and it does so because
of a Base 2.1 requirement rather than because a test happened to look.** 16 bytes
is not an arbitrary tripwire value — it is precisely PCI 3.0's *minimum legal
32-bit memory BAR* (`:11219`), which is exactly what the upper half of a 64-bit
size field masquerades as. The two specifications' disagreement is what makes the
mis-decode detectable.

Secondary predicted kills for the same mutation: `bar_count_o` reports 6 where 5
is expected, and `bar_is_64_o[0]` reads 0.

⚠️ **Brief §7 requires this be confirmed, not assumed.** If the floor check turns
out *not* to fire first — e.g. if the index-advance error trips an allocator or
candidate-range assertion earlier — that ordering must be recorded in the kill
map as measured, not as predicted here.

---

## E.5 ⭐ Ordering: size everything, enable last

**[PCI3 §6.2.2 Table 6-1 p.218 `:10759`]** gives, for the three Command bits this
FSM cares about, both the meaning and the reset state:

| bit | function | reset state | line |
|---|---|---|---|
| 0 | response to **I/O Space** accesses; 0 disables | **"State after RST# is 0."** | `:10761` |
| 1 | response to **Memory Space** accesses; 0 disables | **"State after RST# is 0."** | `:10764` |
| 2 | ability to act as **bus master**; 0 disables | **"State after RST# is 0."** | `:10767` |

**This is the fact that makes all-ones sizing safe.** At enumeration time the
device's decoders are off, so writing `0xFFFFFFFF` into a BAR — momentarily
naming an enormous address range — cannot cause the device to claim any
transaction. A device with Memory Space Enable already set would, briefly,
decode that range.

**Therefore the invariant:**

> **All sizing and all assignment complete before the Command write, and the
> Command write is the last transaction of enumeration.**

### E.5.1 Predicted as an on-wire property, not an intention

This must be asserted **on the wire**, not inferred from the FSM's structure:

> **P-CMD-LAST:** across an entire enumeration run, **no CfgWr0 to register 1
> appears before the final one**, and that final one is the last Configuration
> Request emitted before `enum_done_o`.

The bench proves this by monitoring every emitted TLP, not by reading a state
variable. A structural argument ("the FSM can't reach S_CMD early") is exactly
what the mutation "Command write moved before sizing completes" invalidates, so
the test must be able to see the violation on the link.

### E.5.2 The interleaving that *is* permitted, and why

The invariant constrains the Command write only. Per-BAR **assignment is
interleaved with sizing** (assign BAR N as soon as N is decoded, then move to the
next candidate) rather than deferred to a second pass. The sequence in §E.8 shows
BAR0/1 assigned at B5/B6 while BAR2-5 are still unprobed.

That is safe for the same reason all-ones sizing is safe — Command bit 1 is still
0, so a BAR holding a real address decodes nothing. **The single invariant covers
both**, which is why it is worth stating once, precisely, rather than as a vague
"do things in the right order".

A second pass would cost 0 extra transactions but would need the FSM to hold all
six decoded sizes and addresses in registers simultaneously. Interleaving needs
only the running allocator cursor.

---

## E.6 The Command register enable value

**Write `0x0006`** — bit 1 (Memory Space Enable) + bit 2 (Bus Master Enable).

| bit | value | why | citation |
|---|---|---|---|
| 0 — I/O Space Enable | **0** | no I/O BAR is assigned (§E.7), so enabling I/O decode would advertise ranges that were never programmed | [PCI3] Table 6-1 p.218 `:10761` |
| 1 — Memory Space Enable | **1** | the whole point: the device must answer the memory ranges just assigned | [PCI3] Table 6-1 p.218 `:10764` |
| 2 — Bus Master Enable | **1** | an NVMe controller DMAs; without this it cannot originate a request | [PCI3] Table 6-1 p.218 `:10767`, and **[BASE Table 7-3]** |
| 15:3 | **0** | not required for first enumeration; SERR#/parity/interrupt policy is Stage H | — |

> **Note on the brief's §E.6 citation plan.** It asks for [PCI3] Table 6-1 on
> bits 0/1 and Base 2.1 Table 7-3 on bit 2, "which Base does define". That split
> is still valid, but it is no longer *necessary*: **PCI 3.0 Table 6-1 covers bit
> 2 as well**, including its reset state (`:10767`). Both are cited above; the
> [PCI3] anchor is the primary one, so all three bits rest on a single table.

**Transaction shape:** register 1, `first_be = 0b0011`, 2 bytes. The Command
register is the **lower** half of the Dword at offset `04h`; the upper half is
the Status register **[BASE Figure 7-5 p.491]**, which must not be disturbed —
several Status bits are write-1-to-clear, so a whole-Dword write would clear
sticky error state the RC has not read.

This reuses the byte-granular config-write path already verified by V2
(`verilate_rq_rc_top`) and I2 (`verilate_enum_txn_tlp`), and its descriptor is
already pinned as **E9** in §3.4. Legality re-checked in §3.7: `off=0, bc=2` →
`tlp_first_be=0011`, `tlp_last_be=0000`, `bc ≤ 4-off` ✓.

---

## E.7 Assignment policy

### E.7.1 The allocator

- Parameter **`MEM_BAR_BASE`**, 64-bit. ⚠️ **Not `BAR_BASE`** — that name is taken
  by `tlp_bar_decoder.sv:4` / `tlp_layer.sv:15` for the **endpoint-side decode
  aperture** (inbound CQ, tied off in this design). Different concept, opposite
  direction. Confirmed still true at `ffea7a4`: `MEM_BAR_BASE` appears nowhere in
  `src/`, `BAR_BASE` appears only in those endpoint-side files.
- Allocate **ascending** from `MEM_BAR_BASE`, each BAR **naturally aligned to its
  own size** — required, not chosen: **[PCI3 §6.2.5.1 p.226 `:11226`]**
  *"all address spaces used are a power of two in size and are naturally
  aligned."*

```
addr   = (cursor + size - 1) & ~(size - 1)      ; round up to natural alignment
cursor = addr + size
```

- **Exhaustion → sticky ERROR with a distinct code.** If `addr + size` would
  exceed a parameterized window (`MEM_BAR_BASE + MEM_BAR_WINDOW`), the FSM stops
  with a dedicated error code. **Never silent wraparound** — a wrapped allocation
  produces overlapping BARs that appear to enumerate successfully and fail much
  later, in Stage F, as data corruption.

### E.7.2 What is skipped

| kind | test | action | citation |
|---|---|---|---|
| unimplemented | `encoded == 0` | skip, index += 1, consumes no address space | [PCI3] p.226 `:11224` |
| **I/O BAR** | `readback[0] == 1` | **skip and log**, index += 1, no assignment | [PCI3] p.225 `:11187` |
| reserved type | `[2:1]` ∈ {`01`,`11`} | sticky ERROR (§E.1) | [PCI3] Table 6-4 p.226 `:11207` |

**I/O BAR deferral, documented.** NVMe is a memory-BAR device; I/O space is a
legacy PC mechanism that a PCIe endpoint on this stack has no use for, and
assigning it would require an I/O address allocator with none of the 64-bit
headroom the memory allocator has. Skipping is safe **because Command bit 0 stays
0** (§E.6) — the device is never told to decode I/O space, so an unassigned I/O
BAR is inert. Assignment is future work (brief §11).

### E.7.3 ⭐ The Expansion ROM BAR is NOT probed

**[PCI3 §6.2.5.2 p.227 `:11283`]** places the Expansion ROM Base Address register
at offset **`30h`** in a Type 0 header — *"The four-byte register at offset 30h
in a type 00h predefined header"* (`:11287`) — i.e. **register 12** (`0x30 / 4`).
The Figure 6-1 header map at p.215 `:10623` independently confirms the offset.

It behaves *almost* like a BAR — p.227 `:11290` says it *"functions exactly like
a 32-bit Base Address register except that the encoding (and usage) of the bottom
bits is different"*, and p.228 `:11307` gives it the same all-ones sizing
procedure — which is exactly why it is worth an explicit exclusion rather than
silence.

⚠️ The ROM material **straddles a page break**: `:11283`-`:11298` are on p.227,
`:11300` onward on p.228 (markers 227 at `:11299`). Anchors below carry their own
page because they fall on the far side of it.

**Candidate registers are 4–9 only.** Prediction, asserted on the wire:

> **P-NO-ROM:** no CfgRd0 and no CfgWr0 to **register 12** ever appears during
> enumeration.

Reasons: the ROM is an add-in-card boot mechanism with no role in this design;
its bottom bits use a *different* encoding (bit 0 is Expansion ROM Enable, not a
Memory Space Indicator — Figure 6-7, p.228 `:11318`,`:11323`), so feeding it to
the §E.2 decoder would produce a wrong answer rather than a harmless one; and
p.228 `:11331` notes the
ROM decodes only when *both* Memory Space Enable and the ROM Enable bit are set,
so leaving it untouched is inert by construction.

### E.7.4 Predicted assignment for the acceptance device

`MEM_BAR_BASE = 0x0000_0000_8000_0000`, one 16 KB 64-bit prefetchable pair:

| BAR | size | assigned address | register writes |
|---|---|---|---|
| 0/1 (64-bit pair) | 16 KB | `0x0000_0000_8000_0000` | reg 4 ← `0x80000000`, reg 5 ← `0x00000000` |
| 2–5 | — | unimplemented, skipped | none |

Cursor ends at `0x8000_4000`. `bar_count_o = 1` (**one BAR**, not two — a 64-bit
pair is one BAR occupying two registers), `bar_is_64_o[0] = 1`,
`bar_prefetch_o[0] = 1`, `bar_size_o[0] = 0x4000`.

⚠️ **`bar_count_o` counts BARs, not registers.** The mutation "64-bit pair
treated as two 32-bit BARs" reports 2 here. Stated because "count" is ambiguous
in English and unambiguous in the RTL, and the test must assert the RTL's meaning.

---

## E.8 Exact RQ descriptors for the BAR sequence

Same method as §3.4 and §D.4. Target BDF = bus 1, device 0, function 0
(`completer_id = 0x0100`). All: `dword_count = 1`, `last_be = 0000`, `tc = 0`,
`attr = 0`, `poisoned = 0`, Tag field zero (core-managed, ignored).
`tuser[3:0] = first_be`, `tuser[7:4] = last_be = 0`.

Field positions **[PG213 Table 61 `:3711`,`:3720`,`:3728`,`:3735`]**; request type
encodings **[PG213 Table 57 via `:3725`]**; on-wire DW2 packing
**[BASE Figure 2-18 p.80]**; the fixed Length/Last-DW-BE/TC/Attr
**[BASE §2.2.7 p.79]**.

**Sequence for the acceptance device** (64-bit prefetchable BAR0/1, BAR2-5
unimplemented) — 15 transactions:

| # | transaction | type | reg | first_be | `s_axis_rq_tdata[127:0]` | on-wire DW2 | payload |
|---|---|---|---|---|---|---|---|
| **B1** | BAR0 all-ones write | CfgWr0 `1010` | 4 | `0b1111` | `0x00010000000050010000000000000010` | `0x01000010` | `0xFFFFFFFF` |
| **B2** | BAR0 readback | CfgRd0 `1000` | 4 | `0b1111` | `0x00010000000040010000000000000010` | `0x01000010` | — |
| **B3** | BAR1 all-ones write | CfgWr0 `1010` | 5 | `0b1111` | `0x00010000000050010000000000000014` | `0x01000014` | `0xFFFFFFFF` |
| **B4** | BAR1 readback | CfgRd0 `1000` | 5 | `0b1111` | `0x00010000000040010000000000000014` | `0x01000014` | — |
| **B5** | BAR0 assign (lower) | CfgWr0 `1010` | 4 | `0b1111` | `0x00010000000050010000000000000010` | `0x01000010` | `0x80000000` |
| **B6** | BAR1 assign (upper) | CfgWr0 `1010` | 5 | `0b1111` | `0x00010000000050010000000000000014` | `0x01000014` | `0x00000000` |
| **B7** | BAR2 all-ones write | CfgWr0 `1010` | 6 | `0b1111` | `0x00010000000050010000000000000018` | `0x01000018` | `0xFFFFFFFF` |
| **B8** | BAR2 readback | CfgRd0 `1000` | 6 | `0b1111` | `0x00010000000040010000000000000018` | `0x01000018` | — |
| **B9** | BAR3 all-ones write | CfgWr0 `1010` | 7 | `0b1111` | `0x0001000000005001000000000000001C` | `0x0100001C` | `0xFFFFFFFF` |
| **B10** | BAR3 readback | CfgRd0 `1000` | 7 | `0b1111` | `0x0001000000004001000000000000001C` | `0x0100001C` | — |
| **B11** | BAR4 all-ones write | CfgWr0 `1010` | 8 | `0b1111` | `0x00010000000050010000000000000020` | `0x01000020` | `0xFFFFFFFF` |
| **B12** | BAR4 readback | CfgRd0 `1000` | 8 | `0b1111` | `0x00010000000040010000000000000020` | `0x01000020` | — |
| **B13** | BAR5 all-ones write | CfgWr0 `1010` | 9 | `0b1111` | `0x00010000000050010000000000000024` | `0x01000024` | `0xFFFFFFFF` |
| **B14** | BAR5 readback | CfgRd0 `1000` | 9 | `0b1111` | `0x00010000000040010000000000000024` | `0x01000024` | — |
| **B15** | **Command write** | CfgWr0 `1010` | 1 | `0b0011` | `0x00010000000050010000000000000004` | `0x01000004` | `0x00000006` |

Write payloads are one beat: `tdata` as shown, `tkeep = 0x1`, `tlast = 1`.

### E.8.1 Cross-check against the goldens pinned before this section existed

The descriptor builder used to generate the table above was independently
re-derived from §3.2's field positions, then checked against the **eight**
descriptors already pinned in §3.4 and §D.4 — which were committed in earlier
increments, before `pcie_enum_bar` was contemplated:

| §3.4 / §D.4 golden | reg | type | result |
|---|---|---|---|
| E1 / D-P | 0 | CfgRd0 | ✅ match |
| E3 / D-H | 3 | CfgRd0 | ✅ match |
| E4 | 4 | CfgWr0 | ✅ match |
| E5 | 4 | CfgRd0 | ✅ match |
| E6 | 5 | CfgWr0 | ✅ match |
| E7 | 5 | CfgRd0 | ✅ match |
| E8 | 9 | CfgRd0 | ✅ match |
| E9 | 1 | CfgWr0 | ✅ match |

**All eight match exactly.** The four descriptors that are new here (regs 6, 7,
8 — B7-B12) follow the identical construction with only `reg_num` varying, so the
whole table rests on a builder validated against previously committed goldens
rather than on fresh arithmetic.

### E.8.2 Descriptors that repeat, and what the bench must therefore assert

⚠️ **B1, B5 and B2 differ only in payload and request type; B1 and B5 have
byte-identical descriptors.** Both are CfgWr0 to register 4 with `first_be=1111`.
The all-ones write and the assignment write are indistinguishable on `tdata`
alone.

**Consequence, the same shape as §3.4's E2/E3 warning:** a test that asserts only
on the RQ descriptor cannot tell the sizing write from the assignment write, and
would pass against an FSM that emitted the all-ones write twice and never
assigned anything. **Every BAR-phase write assertion must include the payload
Dword**, and the acceptance test must assert the payloads in sequence.

This is the §E.9 `EF3` prediction and it is the most likely way to build a
vacuously-passing BAR bench.

### E.8.3 Legality pre-check

Every descriptor above is a `first_be=1111` or `first_be=0011` single-Dword
config request to a register in `[1, 9]`. These are the same two shapes already
hand-evaluated against `pcie_rq_if.sv:272-319` in §3.7, with only `reg_num`
varying — and `reg_num` enters only `bad_4kb` (`0x24 + 4 ≪ 4096` ✓).

**Prediction: `rq_protocol_error_o` stays low for the entire BAR sequence.** Any
pulse is a stop-and-report event.

---

## E.9 Predicted FAIL sets for the falsification runs

Following §D.7's method: predict what the *first* run does before the RTL exists,
so a surprise is informative.

| # | run | prediction |
|---|---|---|
| **EF1** | Commit D: `verilate_enum_bar` with the bench wired and `pcie_enum_bar.sv` / `pcie_enum_top.sv` absent from `rc_core.core` | Elaboration failure, **zero `TESTS=` lines**, exit non-zero. Expected `%Error-MODMISSING: … Cannot find file containing module: 'pcie_enum_top'` — naming **`pcie_enum_top`**, not `pcie_enum_bar`, because the shim instantiates the top and Verilator reports the first unresolvable module it reaches. |
| **EF2** | Commit E: `verilate_enum_bar_tlp` likewise | Same, naming `pcie_enum_top` from the integration shim. |
| **EF3** | ⭐ any BAR write test asserting only on the RQ **descriptor** | **Vacuous** — §E.8.2. B1 and B5 have identical descriptors, so such a test passes against an FSM that never assigns. Every write assertion must include the payload Dword. |
| **EF4** | the "all BARs unimplemented" test | Must assert `enum_done_o = 1` **and** `bar_count_o = 0` **and** `enum_error_o = 0`. Asserting only `bar_count_o = 0` passes against a dead FSM — `bar_count_o` is reset-low. **This is DF4's shape, one increment on**; the reset-value trap recurs wherever a "nothing found" outcome is encoded as a zero. |
| **EF5** | the E.5 ordering test (P-CMD-LAST) | Must be asserted **on the wire** over the whole run, not as "the FSM was in S_CMD last". A state-based assertion cannot fail for the mutation it exists to catch. |
| **EF6** | the sub-128-byte test | Must reach the condition with a **memory** BAR. An I/O BAR decoding below 128 bytes is legal and must *not* error, so a test using an I/O BAR would assert the opposite of the intended property. |
| **EF7** | ⭐ the "all-ones write removed" mutation test | Must use a **32-bit non-prefetchable** BAR (§E.2.2). With a 64-bit or prefetchable BAR the readback is `0x0000000C`, not `0x00000000`, and the mutation survives — the test would reach the mutated *line* without reaching the mutated *condition*. Brief §7's rule, applied before the test is written. |
| **EF8** | the allocator-exhaustion test | Must distinguish exhaustion from wraparound: assert the **error code**, not merely `enum_error_o`. A wrapping allocator asserts no error at all, so `enum_error_o = 1` is the right assertion for the *fixed* design and proves nothing about *which* fault fired. |

### E.9.1 The `settle()`-first blind spot — designed against, third occurrence

Brief §7 requires this be addressed explicitly rather than discovered a third
time. The pattern: a test that calls `settle()` before injecting an event gives
the DUT a quiet window it would not have in traffic, and hides survivors that
depend on an event landing *mid-sequence* (2b-1 e9/e10; 2b-2 socket invariant 2).

**Committed for Commit D:** at least two BAR-phase tests must exercise a timeout
or late-CPL event **with no preceding `settle()`** — the event lands while a
transaction is in flight and the FSM is between candidate registers.

Predicted candidates, chosen because they straddle the awkward boundaries:

| test | event lands | why this boundary |
|---|---|---|
| timeout on the **upper half** of a 64-bit pair (B4) | between B3 and B4, no settle | the FSM is mid-pair — it has consumed index N but not yet committed N+2 |
| late CPL arriving during the **assignment** write (B5/B6) | mid-assignment, no settle | the only phase where the FSM holds a decoded size *and* an allocator cursor |

**Whether this changes any kill is an open measurement**, to be recorded in the
Commit-D kill map either way. Recording "it changed nothing" is a real result and
must not be silently dropped — that is what makes the third occurrence a test of
the *pattern* rather than another anecdote.

---

## E.10 Measured results (Commit 2b-3 Part 2)

**Landed:** `8703a3e` (Commit 0, `--trace-fst`), `979b2de` (Commit D,
`pcie_enum_bar` + the handoff mux), `064fdca` (Commit E, integration and the
acceptance test).

### E.10.0 Cold-build baseline, and the environment fault it was checking

Two genuinely cold builds (`rm -rf build/`) back to back, before any new work:

| | targets | tests | PASS | FAIL | sim end times | wall |
|---|---:|---:|---:|---:|---|---:|
| with `--trace-fst` | 34 | 219 | 219 | 0 | all match `docs/recon/RECON_commit2b3.md` §1 | 1131 s |
| without | 34 | 219 | 219 | 0 | **byte-identical**, diffed mechanically | 834 s |

The `activate.d` CPATH hook works: a cold `--trace-fst` build compiled
`verilated_fst_c.o` with no manual export, which is what Part 1 proved could not
happen before. Commit 0 then removed the flag from all 33 targets in
`tb_rc.core` and `tb_tlp.core`, deleting the fragility at its root. −297 s, −26 %
on a full sequential sweep.

⚠️ **Brief §0.1 says 32 targets; the real count is 33** (`tb_rc` 10 + `tb_tlp`
23). A 34th, `verilate_conformance`, also carries the flag but lives in
`tb_ltssm_conformance.core`, outside this increment's file surface, and was left
alone. Immaterial to the gate, recorded because the number is in the brief.

### E.10.1 Falsification (EF1)

⚠️ **The §E.9 EF1 row's PREMISE had expired.** It was written at `ffea7a4`, when
*both* `pcie_enum_bar.sv` and `pcie_enum_top.sv` were absent from
`rc_core.core`, and predicted the error would name `pcie_enum_top`. Commit B
(`f3997f5`) added the top. Re-predicted for the actual state, in writing, before
running:

| # | predicted (re-derived) | measured | verdict |
|---|---|---|---|
| EF1a | elaboration failure, exit non-zero | `rc=1` | ✅ |
| EF1b | **zero** `TESTS=` lines | 0 | ✅ |
| EF1c | names **`pcie_enum_bar`**, not `pcie_enum_top` | `%Error-MODMISSING: pcie_enum_top.sv:299:3: Cannot find file containing module: 'pcie_enum_bar'` | ✅ |
| EF1d | `verilate_enum_scan` fails identically via the shared `rtl` fileset | `rc=1`, same error | ✅ |

EF1d is not in §E.9 and is worth keeping: every RC target compiles one
`rc_core` fileset, so an unresolvable module in `pcie_enum_top` takes down all
of them. That coupling is why "one behaviour change per commit" is load-bearing
here rather than stylistic.

The other §E.9 rows were all designed out ahead of the first run — EF3 by making
the payload a field of the compared tuple, EF4 by `b5` asserting done/error/count
together, EF5 by `b9` scanning the whole wire sequence, EF6 by `b7` using a
memory BAR (and `b6` proving a 64-byte I/O BAR does *not* error), EF7 by `b2`,
EF8 by `b8` asserting the code.

### E.10.2 RTL mutations — standalone (`verilate_enum_bar`, 32 tests)

| mutation | killed by | note |
|---|---:|---|
| size formula ×2 | 5 | |
| size formula ÷2 | 5 | |
| mask 2-bit instead of 4-bit | 10 | |
| 64-bit pair advances N by 1 | 4 | |
| 64-bit pair decoded as two 32-bit BARs | 7 | ⚠️ see §E.10.5 |
| pair's upper assignment never written | 3 | |
| unimplemented treated as implemented | 16 | |
| I/O BAR not skipped | 4 | |
| alignment ignored | 1 (`b4`) | only the mixed set has a BAR needing round-up |
| all-ones write removed | 26 | |
| Command write reordered before sizing | 13 | |
| Command value bit 0 instead of bit 1 | 9 | |
| **`enum_done_o` before the Command write completes** | **SURVIVED** → 2 | §E.10.4 |
| mux merges instead of selecting | 19, incl. `b24` | the designated proof fired |

### E.10.3 Bench mutations

| mutation | killed by | note |
|---|---:|---|
| completer echoes BAR writes verbatim | 8 | ≥1 sizing test, as brief §3.6 required |
| read-only bits 3:0 made writable | 7 | |
| socket records nothing | 32 | ⚠️ but by **hanging**, never reaching the guard |
| **empty-set guard defeated** | **SURVIVED** → 1 (`b0`) | §E.10.4 |
| **`assert_mask_exercised` defeated** | **SURVIVED twice** → 1 (`b0`) | §E.10.4 |

The silent-UR arm and the constant-re-pulse credit drip (brief §3.6) have no
reachable condition in the standalone target — it has no flow control, and its
completer answers every register the FSM addresses. Both belong to the
integration target and are covered there (`e4` drives the finite-advertisement
path; the drip's cumulative-total requirement is asserted live in `e2`).

### E.10.4 ⭐ The three survivors, and what each one was actually about

**`enum_done_o` before the Command write completes.** Survived all 29 tests.
Reach-the-condition, applied: the mutated *condition* is the interval between
the Command write being accepted by `pcie_cfg_txn` and its completion returning.
Every test reached the mutated *line*; none reached the condition, because all
of them wait for `done || error` and then snapshot — and the mutant's snapshot
is identical, since `bar_count_o` and every slot were committed before
`S_CMD_WR` was entered. **The gap was never a weak assertion. No test made the
Command write's OUTCOME matter.** `b26` fails that write; `b27` withholds its
completion and asserts `bar_busy_o`.

⭐ **And the integration target kills it incidentally, by four tests.** The real
stack takes hundreds of cycles for the write to reach the completer, so a
premature `done` leaves the Command register unwritten and the seventeenth TLP
unobserved. **A zero-latency socket model is not merely faster than the stack —
it is BLIND to a class of ordering bug.** Worth remembering the next time a
standalone target is proposed as a stand-in for an integration one.

**The empty-set guard, defeated.** Survived, correctly and uselessly: a guard
only fires on a broken run, and a green suite has none. Nor did "socket records
nothing" prove otherwise — it killed all 29 by *hanging the DUT*, never once
reaching the guard. **This is §D.8's "guards that are never exercised aren't
guards", recurring on the very mechanism the brief added to prevent vacuous
passes.** `b0` now calls every guard with the input it exists to reject.

**`assert_mask_exercised`, defeated — survived TWICE, and the second time was my
bug.** It carried two assertions, with a comment claiming the second caught
something the first did not. The comment was wrong: `ro_low_hits` counts a
subset of `mask_hits`, so the second strictly implies the first and defeating
the first alone could not change any verdict. **A redundant assertion is not a
stronger check; it is an untested one.** Collapsed to one gate, re-mutated,
killed.

### E.10.5 ⚠️ §E.4.1's predicted kill mechanism is WRONG, measured

§E.4.1 predicted the 128-byte floor would kill the pair mis-decode, reasoning
that the upper half's sizing readback `FFFFFFFF` decodes as
`~FFFFFFF0 + 1 = 16` bytes — "precisely PCI 3.0's minimum, which is exactly what
PCIe forbids".

**The floor is never reached.** `FFFFFFFF` has **bit 0 set**, and bit 0 is the
Memory Space Indicator (`[PCI3]` p.225 `:11187`). The I/O check *must* precede
the size decode — an I/O BAR is sized against a different mask — so a
mis-decoding FSM classifies the upper half as an **I/O BAR and skips it**. The
derivation omitted that step.

The mutation is still killed, by the emitted transaction sequence and by
`bar_count_o` / `bar_is_64_o` — §E.4.1's own "secondary predicted kills", which
turn out to be the primary ones. §E.4.1 asked for exactly this to be recorded as
measured if the floor did not fire first; it is, and `b3` now pins the premise
as an assertion rather than leaving it as prose.

The floor becomes reachable only for a pair of 2^36 bytes or more, where the
upper half's low nibble is not all ones. **The 128-byte floor is still
load-bearing** — `b7` reaches it directly with a 16-byte memory BAR, and `b7b`
proves 128 bytes exactly is accepted, so the constant is pinned from both sides.

### E.10.6 The `settle()`-first blind spot — third occurrence, measured

Two BAR-phase tests fire their event with **no preceding `settle()`**, at the
boundaries §E.9.1 predicted:

| test | event | boundary |
|---|---|---|
| `b15` | timeout on the **upper half** of a 64-bit pair (B4) | mid-pair: index N consumed, N+2 not committed |
| `b16` | late CPL during the **assignment** write (B5) | the only phase holding a decoded size *and* an allocator cursor |

**Did it change any kill? No — and that is the result.** Every mutation these
two tests kill is also killed by at least one `settle()`-first test, and neither
appears as a sole killer anywhere in §E.10.2. Recording "it changed nothing" was
required either way; what makes it a test of the *pattern* rather than another
anecdote is that the answer was not decided in advance.

The honest reading is narrower than "the blind spot is closed": these two tests
found nothing **because the BAR FSM has no timer and no event-driven path** —
every transition waits on `cmd_ready_i` or `rsp_valid_i`, so a quiet window
cannot change its state the way it could for the CRS backoff (2b-1 e9/e10) or
the tag-strobe ordering (2b-2 socket invariant 2). The pattern is worth keeping
for modules that *do* have timers; here it was cheap insurance that measured
zero.

### E.10.7 Integration mutations (`verilate_enum_bar_tlp`, 7 tests)

| mutation | standalone | integration | note |
|---|---:|---:|---|
| mux merges instead of selecting | 19 | 5 | |
| pair advances N by 1 | 4 | 5 | |
| pair as two 32-bit BARs | 7 | 5 | |
| pair's upper assignment never written | 3 | 2 | narrowest here |
| `enum_done_o` early | 2 (new tests) | 4 | ⭐ §E.10.4 |
| all-ones write removed | 26 | 7 (all) | |

Different kill sets, as brief §4 predicted. The asymmetry is measured, not
assumed, and the `enum_done_o` row is the one that carries a lesson.

### E.10.8 Two bench-side predictions that measured wrong in Commit E

**`e5`'s silence prediction.** Predicted exactly four per-Dword orphan reports
from `pcie_rc_if` (`:403-405`) and silence everywhere else. The four were exact;
the silence was not. The tracker **also** reports the packet once on
`rc_unexpected_completion_o` with `TLP_ERR_UNEXPECTED_COMPLETION`
(`tlp_request_tracker.sv:316`), because no allocated tag matches it. Two
surfaces describing two different facts about one packet: *"a completion arrived
for nobody"* and *"here is how much payload had nowhere to go"*. Now asserted
explicitly with an exact count and an exact code, not waived.

**`e6`'s UR injection.** Deleting a register from the model and letting the
completer's default arm answer did not work: the all-ones **sizing write**
arrives first and `ConfigDevice.write()` re-created the entry, so the later read
found a value and the UR arm never fired. Identical in shape to the
raw-readback injection bug Commit D hit — **an injection that the DUT's own
traffic overwrites**. Both are now first-class model features (`raw=` for a
fixed malformed readback, `ur_regs=` for explicit UR injection) rather than
pokes at private state.

### E.10.9 Baseline after 2b-3

| | targets | tests |
|---|---:|---:|
| pre-existing (23 TLP + 6 RC + `verilate_conformance` + 4 enum) | 34 | 219 |
| `verilate_enum_bar` | 1 | 32 |
| `verilate_enum_bar_tlp` | 1 | 7 |
| **total** | **36** | **258** |

All PASS, 0 FAIL. The 34 pre-existing targets are identical in count, verdict
**and sim end time** after every commit, diffed mechanically rather than
eyeballed. Two `_trace` variants exist for debugging and are not part of the
gate.

**Stage C is closed.** `enum_done_o` asserts on a fully configured device.

---

## E.11 Tracker-9 drafts

Lift verbatim; each is written to stand alone.

**1. Stage C is closed.** Root Complex enumeration runs end to end: presence
detection (device 0, Type 0), BAR sizing and assignment, and the Command-register
enable, with `enum_done_o` asserting on a fully configured device. Proved by an
acceptance test that enumerates an NVMe-like endpoint (64-bit prefetchable
BAR0/1, one CRS'd probe) through the real stack from FC init, asserting all
seventeen emitted TLPs on the wire against goldens pinned before the RTL existed,
under both saturated credit and the Table 2-37 spec-minimum drip. 36 targets /
258 tests.

**2. The D.1 device-0-only derivation.** A conventional 0–31 device sweep is
wrong here, not merely wasteful. Base 2.1 §7.3.1 p.479 says both that requests
naming devices 1–31 must be terminated with UR by the Root Port, and that
non-ARI devices must answer Type 0 reads *regardless of Device Number*. This
design has no Root-Port termination logic, so such a request would actually be
transmitted — and answered. A 0–31 sweep on a direct-attach link finds the same
device 32 times. Probing device 0 only satisfies §7.3.1 **by construction**.
Root-Port termination becomes required when a switch can sit below the port
(Stage D/E).

**3. Both inherited-stack findings, still standing.** (a) A tag strobe is not
evidence of transmission — allocation precedes the credit gate, so a
credit-starved request times out having never left the VC buffer. Now
*structural* in the enumeration RTL: neither sequencer has a `pcie_rq_tag_i`
port. (b) The completion timer runs from allocation
(`tlp_request_tracker.sv:39`), so credit starvation is indistinguishable from a
dead device; `err_credit_blocked_o` annotates it and is never control flow.
Confirmed a third time in `e4`, now in a third phase. Fixing (b) means raising
`CPL_TIMEOUT_CYCLES` toward the ~10 ms the spec recommends — Stage H.

**4. The reach-the-condition rule, and its cost when skipped.** When a mutation
survives, write down the mutated branch's *condition* first, then check the new
test reaches it — not merely the mutated *line*. Third increment running. This
time: "`enum_done_o` before the Command write completes" survived 29 tests that
all reached the line and none the condition, because none made the write's
*outcome* matter.

**5. The vacuous-comparison rule, in both its forms.** A comparison proves
nothing unless (a) it **had operands** — a green diff over an empty extraction, a
passing assertion over an empty observation set, and an empty finding list are
the same bug; and (b) its **scope was wide enough** — a descriptor-only assertion
cannot distinguish two transactions with byte-identical descriptors. Both bit
during 2b-3: (a) was designed against with explicit guards, which then had to be
mutation-tested themselves (see 6); (b) was designed against by making the
payload Dword a *field of the compared tuple* rather than an optional argument.

**6. ⭐ Guards that are never exercised aren't guards — now on the guard
mechanism itself.** The empty-set guards added specifically to prevent vacuous
passes SURVIVED being defeated, because a guard only fires on a broken run. The
mutation that *did* break things killed all 29 tests by hanging the DUT and never
reached the guard at all. Bench guards need their own self-test that calls each
one with the input it exists to reject. Related: an assertion whose sibling
strictly implies it is not a stronger check, it is an untested one — found by
mutation in `assert_mask_exercised` and collapsed.

**7. The `settle()`-first blind spot: measured, and it changed nothing here.**
Third occurrence, designed against in advance with two no-`settle()` tests at the
boundaries §E.9.1 named. Neither is a sole killer of any mutation. The reason is
specific and worth keeping: the BAR FSM has **no timer and no event-driven
path** — every transition waits on a handshake — so a quiet window cannot change
its state the way it could for a CRS backoff or a tag-strobe ordering. Keep the
pattern for modules that have timers.

**8. ⭐ A zero-latency model is blind to ordering, not just slow.** The socket
model answers in a handful of cycles; the real stack takes hundreds. A
premature-`enum_done_o` mutation was invisible to all 29 standalone tests and
caught incidentally by four integration tests, purely because the real
round-trip leaves an observable gap. Standalone targets are not a substitute for
integration ones on anything ordering-shaped.

**9. The PCI 3.0 shelf addition, and `[PCI3-REF]` discharged.**
`/home/kourosh/openPCIE/0.doc/pci-local-bus-3.0.txt` (16433 lines, line anchors
verified across two extractions). All eleven `[PCI3-REF]` constants now carry
section + page + line. ⚠️ **Page markers in this extraction are FOOTERS** —
content after marker *N* is on page *N+1*; a first pass read them as headers and
came out one page low throughout. Unblocks Stage D: the Type 1 header layout is
in the same chapter.

**10. A spec prediction that measured wrong.** §E.4.1 predicted the 128-byte
floor would catch a 64-bit pair mis-decoded as two 32-bit BARs, via the upper
half decoding as 16 bytes. It does not: the upper half reads `FFFFFFFF`, whose
**bit 0 is set**, so the I/O-BAR check — which necessarily precedes the size
decode — claims it first. The mutation is still killed, by the transaction
sequence and `bar_count_o`. Recorded because the prediction was specific,
plausible, cited, and wrong; the floor itself is still load-bearing and pinned
from both sides by `b7` / `b7b`.

**11. ⭐ The environment fault, and why every prior sweep was misleading.**
Verilator's FST tracer includes `<lz4.h>`; the conda env ships lz4 under
`$CONDA_PREFIX/include` and nothing put it on the compiler's search path. Every
sweep since the tracer object was first built had reused a cached
`verilated_fst_c.o`, so **a genuinely cold build could not have succeeded** and
no one would have known. Fixed twice over: a conda `activate.d` hook, and
removing `--trace-fst` from all 33 functional targets, since nothing in the flow
consumed a waveform. −26 % wall clock on a full sweep. *Generalisable: a build
that is never done cold is not known to work.*

**12. The §7 handoff reframing.** "Prove exactly one stage drives the shared
port" turned out to rest on a single field. Six of the seven command signals
cannot distinguish SELECTING one stage from MERGING both, because
`pcie_enum_scan` drives 0 or a matching constant on all of them — an OR is a
no-op. `cmd_first_be` is the exception: the scan drives a hard `1111` unqualified
by state, and the Command write must be `0011`. **The proof of the mux is a
byte-enable assertion**, and finding that out required enumerating which signals
*could not* show the difference — a useful habit for any shared-resource handoff.

**13. The BAR-phase enable is a design decision, not a test hook.**
`bar_enable_i` is tied low in both scan shims because three scan tests assert the
exact transaction count a presence scan emits, and those assertions are correct
and are the scan's own subject. It also serves a real integrator need — "what is
attached?" without configuring it. Recorded because the alternative (rewriting
24 green tests to accommodate a stage they do not test) was the tempting one.
