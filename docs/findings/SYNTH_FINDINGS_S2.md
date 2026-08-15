# SYNTH_FINDINGS_S2 — the `tlp_vc_buffer` reshape, measured

Out-of-context synthesis of `pcie_rq_rc_top`, same script (`synth/s1_ooc.tcl`), same part
(`xczu7ev-ffvc1156-2-e`), same 250 MHz placeholder clock, same flow as S-1. Artefacts in
`~/synth_s2/pcie_rq_rc_top/`. `pcie_enum_top` (Unit A) was **not** re-run — the reshape
does not touch it, so its S-1 numbers are carried forward unchanged and labelled as such.

The RTL change under test is one commit: `tlp_vc_buffer`'s four payload arrays go from
`[0:PACKET_DEPTH-1][0:MAX_PACKET_WORDS-1]` to a single flat dimension indexed by
`packet * MAX_PACKET_WORDS + word`. Ports, parameters, pointers, state machine and
overflow policy are untouched. The full Verilator gate — 42 targets, 305 tests — is
**byte-identical before and after**, every target ending at the same sim time to 0.01 ns.

---

## 1. The headline

| | **S-1** (2-D, registers) | **S-2** (1-D, distributed RAM) | Change |
|---|---|---|---|
| **`tlp_vc_buffer` LUT** | **54,877** | **4,184** | **−92.4%** (13.1× smaller) |
| — as Logic | 54,867 | 922 | |
| — as LUTRAM | 10 | 3,262 | |
| **`tlp_vc_buffer` FF** | **152,636** | **31** | **−99.98%** (4,924× smaller) |
| **`pcie_rq_rc_top` LUT** | **60,874** (26.42%) | **9,819** (4.26%) | **−83.9%** |
| — as Logic | 60,096 | 5,789 | |
| — as Distributed RAM | 778 | 4,030 | |
| **`pcie_rq_rc_top` FF** | **156,634** (33.99%) | **4,054** (0.88%) | **−97.4%** |
| Register as Latch | 0 | **0** | — |
| CARRY8 | 67 | 70 | +3 |
| F7 / F8 Muxes | 5,108 / 2,505 | 478 / 216 | −91% / −91% |
| BRAM / URAM / DSP | 0 / 0 / 0 | **0 / 0 / 0** | — |
| DRC violations | 0 | **0** | — |
| WNS | −1.055 ns | −0.695 ns | see §4 ⚠️ |

The VC buffer was **90% of the LUTs and 97% of the flip-flops** of the RC host surface.
It is now **43% of the LUTs and 0.8% of the flip-flops**, and `tlp_request_tracker`
(2,776 LUT / 2,535 FF) is the largest flip-flop consumer in the unit.

**The RC vertical**, both units summed (Unit A carried from S-1 at 1,840 LUT / 2,207 FF):

| | S-1 | S-2 |
|---|---|---|
| LUT | 62,714 (**27.2%**) | **11,659 (5.06%)** |
| FF | 158,841 (**34.5%**) | **6,261 (1.36%)** |

S-1 §3.6 predicted the RC would sit "well under 10% of LUTs" and the VC buffer alone
falsified it. That prediction is now true — **5.06%**. The RC is no longer the term that
decides whether an AraXL fits beside it.

## 2. Predictions vs. measurement

| # | Prediction | Measured | Verdict |
|---|---|---|---|
| **P1** | `RAM64M8`/`RAM64X1S`-family distributed RAM; **no `[Synth 8-11357]`** for data/keep/user | `data_mem` → **`RAM64M8` × 325**; `keep_mem` → **`RAM64M8` × 65**; `last_mem` → `RAM256X1D` × 16 + `RAM16X1D` × 2; `class_mem` → `RAM16X1D` × 2; `credit_mem` → `RAM32M16` × 1. **`8-11357` count: 0** | ✅ **HIT** |
| **P2** | Zero BRAM, zero URAM — the asynchronous read makes BRAM ineligible | 0 / 0 | ✅ **HIT** |
| **P3** | `last_mem` may or may not become RAM; not load-bearing | Became RAM (`RAM256X1D` × 16) | ✅ HIT |
| **P4** | Buffer LUTRAM ≈ **3,400** (range 3,000–4,200) | **3,262** | ✅ **HIT** |
| **P5** | Buffer total LUT ≈ **5,000** (range 3,500–7,000) | **4,184** | ✅ **HIT** |
| **P6** | Buffer FF ≈ **100** (range 80–200) | **31** | ❌ **FALSIFIED — see §3.1** |
| **P7** | Unit LUT ≈ **11,000** (range 9,000–14,000) | **9,819** | ✅ **HIT** (low end) |
| **P8** | Unit FF ≈ **4,100** (range 4,000–4,400) | **4,054** | ✅ **HIT** |
| **P9** | BRAM / URAM / DSP = 0 / 0 / 0 | 0 / 0 / 0 | ✅ HIT |
| **P10** | RC vertical ≈ 12,800 LUT (≈5.6%) / ≈6,300 FF (≈1.4%) | **11,659 (5.06%) / 6,261 (1.36%)** | ✅ **HIT** (LUT 9% high) |
| **P11** | WNS still ≈ **−1.0 ns**, worst paths still the tracker cone | Worst path **is** `parser_inst/header_r_reg[requester_id][11]` → `tracker_inst/next_lower_address_r_reg[1][0]`. But WNS = **−0.695 ns** | ⚠️ **SPLIT — identity held, number falsified. See §4** |
| **P12** | `[Netlist 29-101]` disappears | **count: 0** | ✅ **HIT** |

**S-1's own extrapolation of 6,300 FF for the reshaped unit is falsified, as S-2 predicted
it would be.** The measurement is 4,054. S-1's figure was a loose projection; the
derivation in SYNTH_PREDICTIONS_S2 §2.2 — 3,998 measured outside the buffer plus what
little sequential state the buffer keeps — was the right way to reach it.

## 3. What the predictions did not anticipate

### 3.1 ⭐ `user_mem` was not converted. It was deleted — and it had been storing a constant all along.

P6 predicted ≈100 flip-flops in the buffer on the arithmetic that its remaining state is
`wr_packet_r` + `rd_packet_r` (2+2), `wr_word_r` + `rd_word_r` (11+11), `packet_count_r`
(3), `transmitting_r` (1), `overflow_o` (1), `class_mem` (4×2 = 8) and `credit_mem`
(4×12 = 48) — 87 bits. The measurement is **31**, and 31 is exactly the first seven terms:
`2+2+11+11+3+1+1`. **`class_mem` and `credit_mem` became LUTRAM too** (`RAM16X1D` × 2 and
`RAM32M16` × 1), which the prediction did not consider because those two arrays were
already 1-D and S-1 had shown them as registers.

The larger surprise came out of a direct netlist query rather than a report. Opening the
checkpoint and filtering by name:

```
cells whose name mentions user_mem: 0
cells whose name mentions last_mem: 285
```

**`user_mem` does not exist in the synthesized netlist at all** — not as RAM, not as
registers. It is not in the Distributed RAM mapping table and Vivado never mentions it in
the log. `last_mem`, the same shape minus two bits, is there.

The cause is upstream and is a finding in its own right: **`tlp_generator.sv:107` drives
`m_axis_tuser = '0`**, a hard constant. That feeds `generated_axis_user`
(`tlp_layer.sv:451`) which feeds the buffer's `s_axis_tuser` (`:462`). So all 4,120 entries
of `user_mem` store a constant zero, and `m_axis_tuser` is constant zero in the integrated
design. In the 1-D form Vivado's RAM-inference pass recognised the constant write data and
eliminated the array; in the 2-D form it did not, and **S-1 was paying 12,360 flip-flops to
store a constant.**

Two things must be said plainly about this:

- **It is not a behavioural change.** `m_axis_tuser` was constant zero before the reshape
  and is constant zero after it. Nothing downstream sees a difference — which is why the
  gate is byte-identical.
- **It is not a hole in the module's tests.** `tlp_vc_buffer` is required to store and
  replay `tuser`, and the Phase-1 tests drive it with distinct per-beat values in 1..7 and
  check every one on replay. The module honours its contract. What is dead is the
  *integration*: nothing in `tlp_layer` ever puts anything in `tuser`.

Scale, stated honestly: `user_mem` is **12,360 of the 152,636 flip-flops S-1 measured, about
8%**. The other 92% is `data_mem` and `keep_mem` genuinely converting from registers to
RAM. The headline is not an artefact of this — but 8% of it is, and a reader comparing the
two numbers deserves to know that.

**Candidate future commit:** either drive `tuser` with something real in `tlp_generator`,
or delete the `tuser` path through the VC buffer. It is dead weight either way. Not made
here — one behaviour change per commit, and this brief's change was the reshape.

### 3.2 The primitive allocation follows 4,120 entries, not 8,192 — the report's depth column is a rounded label

SYNTH_PREDICTIONS_S2 §1 argued against S-1's suggested `{packet, word}` concatenation on
the grounds that a 2^11 stride would allocate 8,192 entries where `packet * 1030 + word`
allocates 4,120. The mapping table appears to contradict this — it reports `data_mem` as
`8 K x 32` and `last_mem` as `8 K x 1`.

It does not. `keep_mem` is reported as `8 K x 4` and mapped to **`RAM64M8` × 65**, and
65 × 64 = **4,160**, which is `ceil(4120/64)` segments — the allocation that a 4,120-deep
array needs, not the 128 segments an 8,192-deep one would. The `8 K` in the Size column is
Vivado rounding the descriptor to a power of two, not a statement about silicon. The
argument for the multiply form stands, with the caveat that this table cannot be read
literally.

A clean cross-check on the primitive counts: `RAM64M8` decomposes into 8 `RAMD64E` each,
and the netlist contains **390 `RAM64M8`** (325 data + 65 keep) and **3,248 `RAMD64E`** —
390 × 8 = 3,120, plus 16 `RAM256X1D` × 8 = 128, totalling exactly 3,248.

### 3.3 `word_count_mem` is still dead, and still removed

Unchanged from S-1 §5.2 — `WARNING: [Synth 8-6014] Unused sequential element
word_count_mem_reg[0..3] was removed`, now reported against `tlp_vc_buffer.sv:87`. The
reshape deliberately left it alone; removing it is S-1's Recommendation 2 and its own
commit.

### 3.4 `TIMING-16` disappeared from the methodology report

| Rule | S-1 | S-2 |
|---|---|---|
| `TIMING-16` (large setup violation) | **61** | **0 — rule absent** |
| `TIMING-18` (missing I/O delay) | 565 | 565 |
| `SYNTH-5` (mapped onto distributed RAM because of timing constraints) | — | **16** |

`TIMING-18` is unchanged at 565 and is the expected consequence of writing no XDC.
`SYNTH-5` is new and is exactly what a reshape to distributed RAM should produce.

## 4. ⚠️ Timing — the caveat governs the reading, and it did not become less true

WNS improved from **−1.055 ns to −0.695 ns**. **This is not evidence that the reshape
improved timing, and SYNTH_PREDICTIONS_S2 §2.4 forbids reading it that way.** Carried
forward from S-1 §4.4 and re-verified in this run:

> `tlp_vc_buffer`'s read is a continuous assignment onto `m_dllp_axis_tdata`, an **output
> port**, and this flow writes no `set_output_delay`. That path is unconstrained.

Grepping `vc_buffer` in `~/synth_s2/pcie_rq_rc_top/timing_worst20.rpt` returns **zero
hits**, exactly as it did in S-1. The buffer was invisible to WNS before the reshape and
is invisible to it after. The honest statement about timing is:

- The **worst path is the same cone it was in S-1** — `parser_inst/header_r_reg` →
  `tracker_inst/next_lower_address_r_reg`, the 32-way completion match. **The reshape did
  not touch it and did not fix it.** P11's identity claim held.
- **Failing endpoints barely moved: 1,366 → 1,376.** What collapsed is the *denominator* —
  total endpoints went 317,044 → 38,256, because 152,636 flip-flops left the design. TNS
  improved from −965.139 to −709.214 in step with that.
- The WNS improvement is therefore best read as a **second-order effect of a much smaller,
  less congested netlist** on Vivado's post-synthesis estimates, not as a critical path
  getting faster. `TIMING-16` disappearing is the same effect: the violations dropped below
  that rule's threshold without the cone changing.

**A future brief must not cite −0.695 ns as VC-buffer progress.** Cutting the
parser→tracker cone is still S-1 Recommendation 4, still untouched, and still the thing
that decides Unit B's frequency.

## 5. What this brief did not do

- **Did not re-synthesize `pcie_enum_top`.** Its S-1 numbers are carried forward. Valid —
  the reshape is confined to `src/tlp/tlp_vc_buffer.sv` — but it is a carry-forward, not a
  measurement, and §1's vertical total inherits that.
- **Did not remove `word_count_mem`** (S-1 Rec 2) or the two dead input ports (S-1 Rec 5).
- **Did not touch the tracker cone** (S-1 Rec 4) or the enum allocator chain (S-1 Rec 3).
- **Did not write an XDC**, so every timing number here remains directional only and every
  input-to-register and register-to-output path remains unconstrained.
- **Did not act on §3.1's dead `tuser` path**, which is now the top new candidate.
