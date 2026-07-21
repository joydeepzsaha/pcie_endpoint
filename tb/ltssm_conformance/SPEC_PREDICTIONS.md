# LTSSM ordered-set conformance — spec-first predictions

**Purpose.** This file is the *falsifiability anchor* for the Phase 7B conformance
suite. Every expected value below is derived from the **PCI Express Base
Specification, Rev. 2.1** (`openPCIE/0.doc/PCIE-base-spec.Rev2-1.pdf`) — read and
written down **before** the DUT was run. The suite (`test_ltssm_conformance.py`)
compares `pcie_ltssm_downstream`'s emitted `ordered_set_o` against these values.
If the DUT disagrees, the DUT is wrong (or a prediction is a genuine spec
ambiguity, flagged below) — the prediction is *not* to be edited to match the DUT.

Observation point: `ordered_set_o` (the 128-bit `pcie_ordered_set_t` the FSM
emits, pre-datapath). DUT configured as the **Downstream Port / Root Complex**
(`IS_ROOT_PORT=1`), x1 (`MAX_NUM_LANES=1`), Gen1, `LINK_NUM=1`, `SIM_FAST_LINK=1`.
"Downstream Lanes" rules apply throughout (§4.2.6.3.*.1).

Cross-ref for the Southwell primer and MindShare book: both are learning
restatements of the same Base-Spec tables; the Base Spec is cited as the primary
source since it is normative. (The in-repo `pci_express.pdf` named in the brief
resolves to `pcie-primer.Simon-Southwell.pdf`; MindShare =
`PCIE-Technology3-0---MindSharePress2012.pdf`.)

---

## Symbol → byte-offset map (codebase encoding, not a spec value)

`pcie_ordered_set_t = logic [15:0][7:0] symbols`. The DUT lays the 16 spec
symbols out so that **spec Symbol N is at byte offset 8·N** (symbols[N]). This is
a SystemVerilog struct-layout fact taken from `src/packages/pcie_phy_pkg.sv` and
confirmed by the existing validated `ltssm_tb_common.unpack_tsos` (which reads
link@8, lane@16, TS-id@48/80). The suite re-derives COM@0 and TS-id@6..15
independently and will fail loudly if the orientation is wrong. Extraction offset
is a codebase fact; the *values* extracted are checked against spec below.

| Spec symbol | Field                | byte offset |
|-------------|----------------------|-------------|
| 0           | COM                  | 0           |
| 1           | Link Number          | 8           |
| 2           | Lane Number          | 16          |
| 3           | N_FTS                | 24          |
| 4           | Data Rate Identifier | 32          |
| 5           | Training Control     | 40          |
| 6 – 15      | TS1/TS2 Identifier   | 48 … 120    |

---

## A. Ordered-set field encodings (per OS type)

8b/10b special/data symbol byte values (Base Spec §4.2.1.3, Table 4-1 special
symbols; D-code = (sub<<5)|num):

| Symbol   | 8b/10b | byte  | Spec ref |
|----------|--------|-------|----------|
| COM      | K28.5  | 0xBC  | Table 4-2/4-3 Symbol 0 |
| PAD      | K23.7  | 0xF7  | Table 4-2/4-3 Symbol 1/2 ("K23.7") |
| IDL      | K28.3  | 0x7C  | Table 4-4 (EIOS) |
| TS1 id   | D10.2  | 0x4A  | Table 4-2 Symbol 6–15 |
| TS2 id   | D5.2   | 0x45  | Table 4-3 Symbol 6–15 |

### A1. TS1 Ordered Set (Table 4-2, p.201–202)
- **Symbol 0 = 0xBC** (COM, K28.5). *spec-confirmed*
- **Symbol 1 = Link Number** — PAD (0xF7) in Polling; non-PAD selected value in
  Configuration. Exact non-PAD value (`LINK_NUM=1`) is **config-derived**, not
  spec (spec only requires non-PAD & consistent). *spec-confirmed: PAD-vs-nonPAD;
  value flagged.*
- **Symbol 2 = Lane Number** — PAD (0xF7) until assigned; assigned value ∈ 0..n-1.
  For x1 the only lane is **0** (spec §4.2.6.3.2.1: "range from 0 to n-1 …
  include either Lane 0"). *spec-confirmed for x1 = 0x00.*
- **Symbol 3 = N_FTS** — "number of Fast Training Sequences required by the
  Receiver." Implementation-defined 0–255; **spec does NOT pin a value.** → could
  not confirm (see list).
- **Symbol 4 = Data Rate Identifier** — bit0=0 (Rsvd), **bit1=1** (2.5 GT/s
  supported, mandatory), bits[5:3]=0, bit7=0 outside Recovery. For a clean Gen1
  link the byte = **0x02**. bit2 (5.0 GT/s) and bit6 (autonomous) are
  advertise/state-dependent → the fixed bits (0,1,3,4,5,7) are spec-confirmed;
  full byte 0x02 assumes Gen1-only advertisement (flagged).
- **Symbol 5 = Training Control** — normal link-up asserts none: Hot Reset=0,
  Disable Link=0, Loopback=0, Disable Scrambling=0, Compliance=0, [7:5] Rsvd=0 ⇒
  **0x00**. *spec-confirmed for the clean-linkup path.*
- **Symbols 6–15 = 0x4A** (D10.2, TS1 identifier). *spec-confirmed.*

### A2. TS2 Ordered Set (Table 4-3, p.203–204)
Same as TS1 for Symbols 0–5 (Symbol 5 Rsvd is [7:4] here, still 0x00 clean), and
**Symbols 6–15 = 0x45** (D5.2, TS2 identifier). *spec-confirmed.*

### A3. Idle (Configuration.Idle, §4.2.6.3.6)
Spec: "Transmitter sends Idle data Symbols." At 2.5 GT/s idle data is scrambled
zeros on the wire; **at the pre-scramble struct level the FSM's idle is not a TS
ordered set.** Prediction: in Config.Idle `ordered_set_o` carries **no TS
identifier** (is_ts1=is_ts2=False) and the idle control (`gen_os_ctrl_o.gen_idle`)
is asserted. The specific "all-zero struct" encoding is an **RTL representation
choice**, flagged; the spec-level fact (not TS1/TS2, is idle) is asserted.

### A4. EIOS (Table 4-4) — not asserted
EIOS = COM + 3×IDL, emitted only before entering Electrical Idle (§4.2.4.2). The
x1 clean-linkup path to L0 does not traverse an EIOS-emitting transition, so this
OS type is documented but not exercised by this suite (would need a
disable/L2/loopback path). Noted, not a gap in the A/B/C scope.

---

## B. Per-state sequence counts & the 16-after-1 gating

**Magnitudes are scaled by `SIM_FAST_LINK`** (e.g. Polling MinTS1 1024→24), so
absolute counts are not spec-observable in fast mode. What IS spec-invariant and
tested is the **gating relationship** — counting the exit OS only *after* the
first matching OS is received. Derived from spec, independent of the RTL:

- **Polling.Configuration → Configuration** (§4.2.6.2.3, p.224): exit after 8
  consecutive TS2 (PAD/PAD) received **and 16 TS2 transmitted after receiving one
  TS2**.
- **Configuration.Complete → Configuration.Idle** (§4.2.6.3.5.1, p.234): exit
  after 8 consecutive TS2 with matching non-PAD Link/Lane received **and 16 TS2
  sent after receiving one TS2**.
- **Configuration.Idle → L0** (§4.2.6.3.6, p.237): exit after 8 consecutive Idle
  received **and 16 Idle data Symbols sent after receiving one Idle**.

**Prediction (spec):** while the state is entered but the first matching OS has
NOT yet been received, the transmit-count must **not advance** toward its
threshold. Once one matching OS is received, counting begins. A *raw* free-running
count from state-entry would be a **conformance defect**.

Test method: enter Complete (and Idle), pulse many `ordered_set_tranmitted_i`
with the matching RX strobe withheld, and assert the internal
`ordered_set_sent_cnt_r` stays 0 and `single_ts2_received`/`single_idle_received`
= 0; then supply the RX strobe and assert the count begins to advance. (Internal
signals observed via `--public-flat-rw`; the *expected* behaviour is spec-derived.)

---

## C. Configuration.Lanenum.Wait — the "1 ms settle" (§4.2.6.3.4.1, p.233)

**Careful spec reading:** the 1 ms is a **permitted** delay, not a mandatory
minimum — verbatim: *"The Upstream Lanes are permitted [to] delay up to 1 ms
before transitioning to Configuration.Lanenum.Accept. The reason for delaying up
to 1 ms … is to prevent received errors or skew between Lanes affecting the final
configured Link width."* So:

- **Mandatory (spec-required) gate:** next state is Lanenum.Accept only after two
  consecutive TS1 are received whose **Lane Number differs from the value when the
  lane entered Lanenum.Wait**, with non-PAD Link. *Prediction: DUT must NOT exit
  on an unchanged Lane Number; it MUST exit once the Lane Number changes.* This is
  what the suite asserts.
- **1 ms window:** an *upper-bound allowance* to absorb lane-to-lane skew, **not a
  required floor.** Therefore an implementation that evaluates the changed-lane
  condition promptly (no settle delay) is **spec-compliant**. Absence of a settle
  window is a **hardware multi-lane-skew robustness gap**, not a conformance
  violation — and at x1 (single lane, no inter-lane skew) it is entirely benign.

This corrects the brief's framing ("assert the RTL honors a settle window"): the
spec does not mandate one. The suite therefore asserts the *changed-lane* gate
(spec-required) and separately *reports* whether a settle floor exists
(informational, skew-robustness).

---

## Could-not-confirm-from-spec list (required deliverable)

1. **N_FTS (Symbol 3) exact value** — spec §4.2.4.1 Table 4-2 defines it as
   "number of FTS required by the Receiver," implementation-defined 0–255. No spec
   value. The suite records the DUT's value and asserts only that it is a stable
   byte; the specific number is **RTL-derived, not spec-confirmed.**
2. **Data Rate Identifier full byte (Symbol 4)** — bits 0,1,3,4,5,7 are
   spec-fixed for a clean Gen1 link (⇒ 0x02); **bit2 (5.0 GT/s advertised) and
   bit6 (autonomous/de-emphasis) are advertise/state-dependent.** The suite
   asserts the fixed bits; equality to exactly 0x02 assumes Gen1-only
   advertisement and is flagged if the DUT advertises more.
3. **Idle struct encoding (Config.Idle)** — spec says "Idle data"; the
   all-zero-`pcie_ordered_set_t` + `gen_idle` representation is an **RTL encoding
   choice**, not a spec-mandated struct. The suite asserts the spec-level fact
   (not a TS OS; idle asserted), not the zero-pattern per se.
4. **Specific Link Number value (=1)** — spec requires only non-PAD & consistent;
   the value 1 is the `LINK_NUM` parameter, **config-derived.**
