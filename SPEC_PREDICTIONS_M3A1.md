# SPEC_PREDICTIONS_M3A1 — qualifying `main`'s 19th credit-manager test

Committed **before** any edit to `tb/tlp/test_tlp_credit_manager.py`. Every expected value
below is derived from PCI Express Base 2.1 and from the RTL as it stands on this branch;
nothing here was written after observing a run.

| anchor | hash |
| --- | --- |
| `HEAD` = `origin/kourosh/dev` (M-3 landing) | `4c5205d123ca617553b7be21960e6eb66d2c5645` |
| `origin/main` (unmoved since M-3) | `aca47806b115cc4c4e842814d949527473285a0c` |
| merge base | `2de9afe3edc6e458799afadaf5c3a77456d6635d` |
| M-3 post-gate md5 | `a411e2317a2a6dd954225523ce3c9652` (42 targets / 307 tests) |

Tree state at entry: two **untracked** files, `M3_gate_before.txt.diag` and
`M3_gate_after.txt.diag` — generated warning sidecars left by the M-3 sweep, byte-identical
to each other (28990 B), tracked by nothing and referenced by nothing. Recorded rather than
removed; §8 of the brief puts hygiene out of scope. No tracked file is modified.

---

## 0. Recon results that the predictions rest on

### 0.1 What the test is

`main` rewrites `tb/tlp/test_tlp_credit_manager.py` (blob `42bc5ce` → `1c1fe9a`,
+114/−45). The change is **one added test plus a code move**:

- `HDR_MOD`/`DATA_MOD`/`POSTED`/`NON_POSTED`/`COMPLETION` and the helpers `_advertise` /
  `_reset_and_init` are hoisted from mid-file to the top, character-identical apart from
  `_reset_and_init`'s docstring (*"the FC-initialisation advertisement"* → *"the first FC
  advertisement as initialization"*). That accounts for the deletions.
- The `Commit A` banner comment is replaced by a shorter one.
- One new test, `all_starvation_combinations_and_saturating_guards`, placed second in the
  file.

The other 18 test bodies are untouched — the diff contains no line from any of them.
Test count 18 → 19; `verilate_tlp_credit_manager` is the only target affected.

What it drives, per pool `∈ {P, NP, CPL}`, after `_reset_and_init(7,7,7,7,7,7)`:

| block | advertises (header, data) | request | asserts |
| --- | --- | --- | --- |
| a | 1, 0 | class=pool, data=1, valid | `!ready`, `blocked`, `h_av==1`, `d_av==0` |
| b | 0, 1 | (held) | `!ready`, `blocked`, `h_av==0`, `d_av==1` |
| c | 1, 1 | (held) | `ready`; after one grant edge `h_av==0`, `d_av==0` |
| d | — | re-assert valid for one edge | `h_av==0`, `d_av==0` (no wrap) |

It decides pass by direct assertion on `request_ready`, `blocked`, and the six
`*_available_o` observability ports. No self-checking model, no golden file.

### 0.2 It does **not** stand on RTL this branch lacks — §2.2 answered, no stop

```
git diff 2de9afe3 aca4780 --stat -- src/tlp/tlp_credit_manager.sv   → empty
git diff HEAD     aca4780 --stat -- src/tlp/tlp_credit_manager.sv   → empty
git diff HEAD     aca4780 --stat -- tb/tlp/tb_tlp_credit_manager.sv → empty
```

`main` never touched the DUT or its SV wrapper. The target's whole closure is
`filesets: [rtl, bench_credit_manager, cocotb_credit_manager]`
([tb_tlp.core:532](tb/tlp/tb_tlp.core#L532)) where `rtl` is `::tlp_core:1.0.0` —
`src/tlp/*.sv` only. `src/dllp/` is not in it.

M-3's policy, quoted:

- `tb/tlp/test_tlp_credit_manager.py` → **`ours`** — *"The one non-message thing `main`
  contributes to the measured surface."* (`SPEC_PREDICTIONS_MERGE_M3.md:100`)
- `src/dllp/dllp2tlp.sv`, `tlp2dllp.sv`, `README.md` → **`theirs`** — *"0 message refs;
  `dllp_*.core` not in the gate closure."* (`:118`)

So the only credit-path file `main` changed at all is already in the tree under `theirs`,
and it is outside this target's closure regardless. Every signal the test names
(`ph`/`pd`/`nph`/`npd`/`cplh`/`cpld`, the six `*_av`, `request_*`, `blocked`, `error`,
`fc_*`) is declared in [tb_tlp_credit_manager.sv](tb/tlp/tb_tlp_credit_manager.sv) as it
stands. **No RTL qualification is implied. Proceed.**

---

## 1. P1 — the spec derivation. This is the golden.

Derived from the specification before `main`'s assertions were judged.

### 1.1 Normative text

- **§2.6.1 p.135** — *"The unit of Flow Control credit is 4 DW for data"*. One data credit
  is 16 bytes; `main`'s comment *"one 16-byte data credit"* is correct.
- **§2.6.1 Table 2-36 p.136** — credit consumption per TLP. Every entry is **exactly one
  header unit** of its type plus `n` data units, `n = Roundup(Length / FC unit size)`
  (footnote 31). The header requirement is therefore always 1, which is what licenses the
  RTL's `!= 0` header test as an exact `>= 1`.
- **§2.6.1.1 p.139** — `CREDITS_CONSUMED`: *"Count of the total number of FC units consumed
  by TLP Transmissions made since Flow Control initialization, modulo 2^[Field Size]"*,
  *"Set to all 0's at interface initialization"*, *"**Updated for each TLP the Transaction
  Layer allows to pass the Flow Control gate for Transmission**"*, as
  `CREDITS_CONSUMED := (CREDITS_CONSUMED + Increment) mod 2^[Field Size]`. Field size 8 for
  PH/NPH/CPLH, 12 for PD/NPD/CPLD.
- **§2.6.1.1 p.140** — `CREDIT_LIMIT`: *"The most recent number of FC units legally
  advertised by the Receiver … total … made available since Flow Control initialization,
  modulo 2^[Field Size]"*, and the update rule *"For each FC update received, if
  CREDIT_LIMIT is not equal to the update value, **set CREDIT_LIMIT to update value**"* —
  unconditional, with no legality precondition.
- **§2.6.1.1 p.140 — the gating equation**:

  ```
  CUMULATIVE_CREDITS_REQUIRED = (CREDITS_CONSUMED + <credit units required>) mod 2^N
  permitted iff  (CREDIT_LIMIT - CUMULATIVE_CREDITS_REQUIRED) mod 2^N  <=  2^N / 2
  ```

  *"If CREDIT_LIMIT was specified as 'infinite' during Flow Control initialization, then the
  gating function is unconditionally satisfied for that type of credit."*
- **§2.6.1 p.138** — *"A Receiver must never cumulatively issue more than 2047 outstanding
  unused credits to the Transmitter for data payload or 127 for header."* Checking is
  optional and receiver-side.
- **Table 2-37 p.137–138 + footnote 33 p.137** — infinite is an initial advertisement of
  `00h`/`000h`, *"interpreted as infinite by the Transmitter, which will, therefore, never
  throttle"*. **CPLH/CPLD**: infinite is mandatory only for *"Root Complex (not supporting
  peer-to-peer traffic between all Root Ports) and Endpoint"*; a *"Root Complex (supporting
  peer-to-peer traffic between all Root Ports) and Switch"* advertises **1 FC unit**, and
  p.138 restates it — *"A Root Complex that supports peer-to-peer traffic between all Root
  Ports **may optionally advertise non-infinite Completion credits**."*

  ⚠️ This makes a **finite CPL advertisement legal**, so exercising the CPL pool as finite
  is a conformance case, not a defensive-only one. It also means
  [tlp_credit_manager.sv:116-118](src/tlp/tlp_credit_manager.sv#L116) (*"Table 2-37 p.137-138
  makes infinite CPLH/CPLD mandatory for the Root Complex an Endpoint faces"*) and the
  docstring of `infinite_completion_credit_never_throttles` overstate the rule: mandatory
  only for a non-p2p RC, and an Endpoint below a Switch faces a finite CPL advertiser. A
  comment inaccuracy, not an RTL defect. Recorded, not fixed — out of scope.

### 1.2 The equivalence the RTL relies on

The RTL gates on `available >= required` with `available = (limit_r - consumed_r)` in native
N-bit arithmetic. Writing `R = (CREDIT_LIMIT − CREDITS_CONSUMED) mod 2^N`, the spec's left
side is `(R − required) mod 2^N`, so the two forms agree whenever `R ≤ 2^N/2 − 1`
(guaranteed by the p.138 cap: `127 = 2^8/2 − 1`, `2047 = 2^12/2 − 1`) and
`required ≤ 2^N/2 − 1` (headers always 1; data `n ≤ 256`). They diverge at exactly one
point, `required − R = 2^N/2`, which those bounds exclude. Independently re-derived here
from the p.140 text; it agrees with `SPEC_PREDICTIONS_CREDIT.md §J`.

**Every stimulus in the test under qualification keeps `R ≤ 7` and `required ≤ 5`, so the
divergence point is nowhere near.** The spec equation and the RTL comparison give the same
answer at every assertion point below.

### 1.3 Is the stimulus spec-legal?

The test advertises a pool at 7 during initialization and then updates it to 1 or 0.
Cumulative `CREDITS_ALLOCATED` only ever *increments* (p.141), so `7 → 0` reads as
`Increment = 249 mod 2^8`, not as a retraction — the field cannot express a decrease.
Outstanding unused credit is `R = CREDIT_LIMIT − CREDITS_CONSUMED`, which stays at `0`, `1`,
`2` or `6` throughout — **far inside the 127/2047 cap, so no Flow Control Protocol Error is
raised or raisable**. And p.140's update rule is unconditional. The transmitter's required
behaviour is therefore fully determined by the spec for every stimulus in this test.
The sequence is legal, if not physically meaningful for a real receiver.

### 1.4 The expected-value table — the golden, per pool

Applies identically to P (class 0), NP (class 1) and CPL (class 2); `H`/`D` are that pool's
header and data quantities, `N=8` for `H` and `N=12` for `D`. All pools initialize at 7, so
no pool is infinite and each data pool's latched capacity is 7. Requirement is always
**1 header unit** (Table 2-36) plus the stated data credits.

**For `main`'s test as written** (`req_data = 1` throughout):

| block | limit H,D | consumed H,D | spec H: `(L−(C+1)) mod 256` | spec D: `(L−(C+r)) mod 4096` | permitted? | `h_av` | `d_av` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a | 1, 0 | 0, 0 | `0 ≤ 128` ✓ | `4095 > 2048` ✗ | **block** | 1 | 0 |
| b | 0, 1 | 0, 0 | `255 > 128` ✗ | `0 ≤ 2048` ✓ | **block** | 0 | 1 |
| c | 1, 1 | 0, 0 | `0 ≤ 128` ✓ | `0 ≤ 2048` ✓ | **grant** | 1→0 | 1→0 |
| d | 1, 1 | 1, 1 | `255 > 128` ✗ | `4095 > 2048` ✗ | **block**, `CREDITS_CONSUMED` unchanged (p.139) | 0 | 0 |

Every one of `main`'s 12 assertions per pool matches. **Nothing it asserts contradicts the
derivation — stop trigger 7 does not fire.**

**For the landed (rewritten) test**, values forced apart per §2.4:

| block | advertise H,D | req data | limit H,D | consumed H,D (pre) | spec H | spec D | permitted? | assert `h_av` | assert `d_av` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a | 1, 2 | 5 | 1, 2 | 0, 0 | `(1−1)=0 ≤ 128` ✓ | `(2−5) mod 4096 = 4093 > 2048` ✗ | **block** | **1** | **2** |
| b | 0, 6 | 5 | 0, 6 | 0, 0 | `(0−1) mod 256 = 255 > 128` ✗ | `(6−5)=1 ≤ 2048` ✓ | **block** | **0** | **6** |
| c | 1, 2 | 2 | 1, 2 | 0, 0 | `(1−1)=0 ≤ 128` ✓ | `(2−2)=0 ≤ 2048` ✓ | **grant** | **0** after grant | **0** after grant |
| d | — | 2 | 1, 2 | 1, 2 | `(1−2) mod 256 = 255 > 128` ✗ | `(2−4) mod 4096 = 4094 > 2048` ✗ | **block**, 3 edges, `CREDITS_CONSUMED` unchanged | **0** | **0** |

Post-grant arithmetic in block c, from p.139: `CREDITS_CONSUMED_H := 0+1 = 1` so
`h_av = 1−1 = 0`; `CREDITS_CONSUMED_D := 0+2 = 2` so `d_av = 2−2 = 0`.

---

## 2. P2 — the verdict: **REWRITE**

### 2.1 §2.4 classification: **SPEC-GOLDEN**

Every expected value in `main`'s test is computable from §2.6.1.1 p.140's gating equation
plus p.139's consumption rule plus Table 2-36 p.136, without running anything — §1.4's first
table is that computation, and it reproduces all 36 assertions. The test asserts no
implementation-defined quantity: it never touches `error_o`, whose contract
([tlp_credit_manager.sv:34-55](src/tlp/tlp_credit_manager.sv#L34)) is explicitly
*"IMPLEMENTATION-DEFINED, NOT A SPEC-CONFORMANCE SIGNAL"*. The six `*_available_o` ports it
does read carry `(CREDIT_LIMIT − CREDITS_CONSUMED) mod 2^N`, a difference of two
spec-defined registers.

Evidence it is not a DUT-mirror: the derivation in §1.4 was performed from the p.140 text
before `main`'s assertions were compared against it, and it *predicts* them rather than
recording them. A wrong design — one that granted in block a, or consumed while blocked in
block d — fails the derivation and fails the test.

**This alone would justify adoption.** The rewrite is not about correctness.

### 2.2 §2.5 coverage: genuinely new, and precisely bounded

Mapping the added test against the 18 already present:

**What it reaches that nothing else does.** No existing test ever *blocks* a Non-Posted or a
Completion request against a finite pool. Enumerated:

| existing test | NP touched? | CPL touched? |
| --- | --- | --- |
| `exact_short_update_and_independent_pools` | reads `nph_av`/`npd_av`, **issues no NP request** | one CPL grant; the later `ready==0` is masked by `fc_initialized=0` |
| `header_exhaustion_…_attributable_to_the_header` | `_probe_request(NON_POSTED,1)` asserted **ready==1** — a control, not a block | — |
| `posted_and_completion_pools_are_independent` | asserts NP *unchanged*, issues nothing | 1 grant |
| `infinite_credit_is_honoured_on_every_pool`, `infinite_and_finite_pools_coexist` | NP **infinite** → grant path only | — |
| `infinite_*`, `error_never_fires_for_an_infinite_pool` | — | CPL **infinite** → grant path only |
| the other 12 | POSTED only | POSTED only |

So in [tlp_credit_manager.sv:161-174](src/tlp/tlp_credit_manager.sv#L161) the four branch
*outcomes* `nph_available != 0` **false**, `npd_available >= req` **false**,
`cplh_available != 0` **false**, `cpld_available >= req` **false** are, on this branch
today, **unreached with `fc_initialized_i` high**. The added test reaches all four, with
header-vs-data attribution on each. That is real, and it is the reason to land something
here rather than nothing.

**What it duplicates.** Roughly its POSTED third: block a repeats the scenario of
`error_stays_silent_for_ordinary_credit_blocking`; block b repeats the property of
`a_zero_valued_update_does_not_make_a_finite_pool_infinite`; block d repeats
`blocked_requests_consume_no_credit`, which observes it *more* strongly (it holds 5 edges
and then re-advertises, so eaten credit shows up in the new remainder, rather than reading a
remainder that is 0 either way).

**What it has no power over — the answer to the brief's §2.5 question.** The credit
rebuild's own finding was that the TX side read cumulative `CREDITS_ALLOCATED` as a
remaining balance and decremented it. Exposing that needs a *second* advertisement to a pool
that has already consumed. In the added test, every advertisement to the pool under test
happens with that pool's `CREDITS_CONSUMED` at 0, where `limit − consumed` and
`limit-as-remainder` are numerically identical. The one place consumption does precede an
advertisement — the P pool carried into the NP and CPL iterations — is never asserted.
**Zero power against the defect class the rebuild exists to fix**; that stays
`repeated_updatefc_does_not_overstate_credit`'s job. It reaches neither that class nor the
receiver half — it is new *branch* coverage, not new *defect-class* coverage.

### 2.3 Why rewrite rather than adopt as written

The test's first line claims it will *"Prove independent header/data blocking for P, NP, and
Cpl pools."* It cannot. Every pool is advertised 7; the pool under test is then driven with
header and data both drawn from `{0, 1}`; and `request_data_credits` is 1 throughout. With
the header requirement fixed at 1 by Table 2-36, the header and data quantities are
numerically indistinguishable at every assertion point, and a design that **crossed** the
two — testing header availability against the data remainder and vice versa — produces
byte-identical outputs in all four blocks (worked through in P5/M4). The standing rule
*force values apart, no degenerate space* is not satisfied by the as-written version, and it
is not satisfied precisely on the property the test names.

Two further consequences of `req_data = 1`: the data-consumption increment cannot be
distinguished from `+1` (P5/M5), and the equality case that alone separates `>=` from `>` is
present but carries no other information.

**Verdict: rewrite, minimally.** Keep the test's name, its position among `main`'s
intentions, its four-block structure, all three pools, `main`'s `_reset_and_init(7,…)` and
the reasoning behind it. Change only the numeric values, to §1.4's second table, so the test
can support its own claim. The expected values come from P1, which is on disk before the
test is.

Two deliberate departures from `main`'s file beyond the numbers:

1. **The new test is appended at the end of the file, not inserted second.** `main`'s
   placement forces its 45-line hoist of the helpers and constants above the first test.
   That hoist is pure churn — it changes no behaviour, and the helpers are already defined
   before every caller. Appending makes the change purely additive and leaves the existing
   18 untouched at the byte level.
2. **Block d holds the blocked request across 3 edges rather than 1**, so *"cannot wrap"* is
   evidenced by repetition rather than by a single sample.

Not adopted from `main`: the `_reset_and_init` docstring reword and the banner-comment
replacement, both cosmetic.

---

## 3. P3 — pass or fail on this branch's RTL as it stands

| what is run | prediction | reason |
| --- | --- | --- |
| `main`'s test **as written**, on this branch's `tlp_credit_manager.sv` unmodified | **PASS**, all 19 | §1.4 first table: the spec's gating equation and the RTL comparison agree at every one of the 36 assertion points, and the RTL updates `CREDITS_CONSUMED` only on `request_valid_i && request_ready_o` |
| the **rewritten** test, same RTL | **PASS**, all 19 | §1.4 second table, same argument |

`main`'s test being unexecuted is why this is a prediction and not a fact; a fail on either
is stop trigger 4 and ends the rung.

---

## 4. P4 — the gate delta

Exactly two lines of `M3A1_gate_before.txt` move, both inside
`verilate_tlp_credit_manager`, and nothing else in the file changes:

1. **One `T` row added**, immediately after
   `T|verilate_tlp_credit_manager|test_tlp_credit_manager.error_never_fires_for_an_infinite_pool|PASS|90.00`
   (line 145) and before the `A` row:

   ```
   T|verilate_tlp_credit_manager|test_tlp_credit_manager.all_starvation_combinations_and_saturating_guards|PASS|<sim>
   ```

   `<sim>` is not predicted to the picosecond. Predicted **form**: ≈ 300 ns — 5 clock edges
   in `_reset_and_init` plus 8 per pool × 3 pools = 29 edges at 10 ns — carrying a sub-ns
   tail from the `Timer(1, 'ps')` waits, as `70.01` and `80.01` already do on this target.

2. **One `A` row changed**, line 146:

   ```
   -A|verilate_tlp_credit_manager|rc=0|TESTS=18 PASS=18 FAIL=0 SKIP=0|simend=21220.05
   +A|verilate_tlp_credit_manager|rc=0|TESTS=19 PASS=19 FAIL=0 SKIP=0|simend=<21220.05 + sim>
   ```

   with `simend_after − 21220.05 = <sim>` exactly.

Resulting totals: **42 targets / 308 tests / 308 PASS / 0 FAIL / 0 SKIP**.

Unchanged and re-checked: `verilate_tlp_credit_integration` (different cocotb module,
`test_tlp_credit_integration`), both sim-time invariants
(`verilate_tlp_cpl_timeout_off` and `verilate_tlp_request_tracker` at 580.00 ns), zero
Verilator build diagnostics, and `M3A1_gate_after.txt.diag` byte-identical to
`M3A1_gate_before.txt.diag` — no RTL is edited, so no `$warning` population can move.

**Any row moving that is not one of these two is stop trigger 6.**

---

## 5. P5 — mutation predictions

Two distinct exercises. Do not conflate them.

### 5.1 Verdict-evidence runs — `main`'s test **as written**, predicted to SURVIVE

Run only to establish P2 empirically. These are *not* part of the acceptance gate and their
survival is the predicted, intended outcome; it does not fire stop trigger 5.

| id | mutation | against | prediction |
| --- | --- | --- | --- |
| **M4′** | [:169-171](src/tlp/tlp_credit_manager.sv#L169) NP arm, header and data sources crossed: `selected_header_available = nph_infinite_r \|\| (npd_available != 0)` and `selected_data_available = npd_infinite_r \|\| (nph_available >= request_data_credits_i)` | `main`'s test + the existing 18 | **SURVIVES both.** Block a: crossed header reads `npd_av=0` → false → still blocked. Block b: crossed header reads `npd_av=1` → true, crossed data reads `nph_av=0 >= 1` → false → still blocked. Block c: `1≠0` true and `1>=1` true → still granted. Block d: both 0 → still blocked. Of the existing 18, `header_exhaustion_…` probes NP with `nph_av=8`, `npd_av=4000` → both crossed terms still true → ready==1 holds; every other NP contact is an infinite pool, short-circuited before the comparison. |
| **M5′** | [:280](src/tlp/tlp_credit_manager.sv#L280) `npd_consumed_r <= npd_consumed_r + request_data_credits_i` → `+ 1'b1` | `main`'s test + the existing 18 | **SURVIVES both.** `main` requests exactly 1 data credit, so `+req` and `+1` are the same write. No existing test consumes NP data on a finite pool at all. |

If either is *killed*, P2's evidential basis is gone — see P6.

### 5.2 Acceptance mutation gate — the **landed** (rewritten) test, all predicted KILLED

Reaching the branch condition, not merely the line. Each restored and `git diff`-verified
bit-identical before the next.

| id | mutation | site | predicted killer | predicted assertion | killed by existing 18 too? |
| --- | --- | --- | --- | --- | --- |
| **M1** | credit-check comparison `>=` → `>` | [:171](src/tlp/tlp_credit_manager.sv#L171) `npd_available >= request_data_credits_i` | new test, **NP** block c | `assert int(dut.request_ready.value)` — `npd_av=2`, `req=2`, `2 > 2` false → not ready | **no** — `header_exhaustion_…` probes NP at `npd_av=4000 > 1`, still true; all other NP contacts are infinite |
| **M2** | consumption point: check-time instead of handshake-time | [:268](src/tlp/tlp_credit_manager.sv#L268) `else if (request_valid_i && request_ready_o)` → `else if (request_valid_i)` | new test, **P** block b | `assert int(getattr(dut, header_out).value) == 0` — the block-b update edge is taken with `valid=1, ready=0`, so `ph_consumed` becomes 1 and `ph_av = 0−1 = 255` | **yes** — `blocked_requests_consume_no_credit` was written for exactly this |
| **M3** | counter update direction | [:279](src/tlp/tlp_credit_manager.sv#L279) `nph_consumed_r <= nph_consumed_r + 1'b1` → `- 1'b1` | new test, **NP** block c | `assert int(getattr(dut, header_out).value) == 0` after the grant edge — `nph_consumed = 0−1 = 255`, `nph_av = 1−255 = 2` | **no** — no existing test reads `nph_av` after an NP grant |
| **M4** | the M4′ cross, on the rewritten test | as M4′ | new test, **NP** block c | `assert int(dut.request_ready.value)` — crossed data term reads `nph_av=1 >= 2` → false → not ready | **no** |
| **M5** | the M5′ magnitude, on the rewritten test | as M5′ | new test, **NP** block c | `assert int(getattr(dut, data_out).value) == 0` after the grant edge — `npd_consumed = 1`, `npd_av = 2−1 = 1` | **no** |

M1, M2, M3 are the brief's mandated minimum. M4 and M5 are the two the rewrite exists to
make killable; each is predicted to survive `main`'s version and die on the landed one,
which is the whole argument of P2 reduced to two experiments.

**Any survivor in §5.2 is stop trigger 5.** A survivor is answered with a new test, never a
strengthened assertion.

---

## 6. P6 — the falsifier for P2

P2 says *rewrite* on the single ground that `main`'s value choice is degenerate on the
property the test names. **P2 is falsified if M4′ or M5′ is killed by `main`'s test as
written.** In that case the as-written test already discriminates header from data and
already pins the consumption magnitude, the sole ground for rewriting collapses, and the
correct verdict was *adopt as written* — the rung would land `main`'s file unchanged and
record the reversal.

P2 is **not** falsified by `main`'s test passing (P3 predicts exactly that) nor by M1–M3
being killed by the as-written version (M2 is predicted to be, by the existing 18).

Secondary falsifier, for P1 rather than P2: if any assertion in `main`'s test disagrees with
§1.4's first table, the derivation and the design disagree, and that is stop trigger 7 — a
defect report about the RTL, not a bench decision.

---

## 7. Stop triggers, restated with what would fire each

| # | trigger | fires if |
| --- | --- | --- |
| 1 | pre-gate not 42/307 all PASS, or md5 ≠ `a411e2317a2a6dd954225523ce3c9652`, or a build diagnostic | `M3A1_gate_before.txt` differs from `M3_gate_after.txt` in any byte |
| 2 | test depends on RTL absent here | **already answered no** — §0.2 |
| 3 | derivation unsettleable from Base 2.1 | **already answered no** — §1.1 is verbatim normative text |
| 4 | result contradicts P3 | any FAIL in either run of §3 |
| 5 | any mutation survives | any row of §5.2 not killed |
| 6 | a row moves that P4 did not name | `diff` of the two gates shows anything but §4's two lines |
| 7 | the test asserts something the derivation says is wrong | **already answered no** — §1.4 first table reproduces all 36 assertions |
