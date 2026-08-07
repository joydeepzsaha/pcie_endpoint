# SYNTH_PREDICTIONS_S2 — what the `tlp_vc_buffer` reshape should do to `pcie_rq_rc_top`

**Written before the reshape is made and before Vivado is run again.** S-1's numbers are
the baseline; everything below is a falsifiable claim about what changes. Same part
(`xczu7ev-ffvc1156-2-e`), same 250 MHz placeholder clock, same out-of-context flow,
same script (`synth/s1_ooc.tcl`), unit `pcie_rq_rc_top` only.

---

## 0. The one-variable experiment S-1 set up

S-1 found `tlp_vc_buffer` at **54,877 LUT / 152,636 FF** — 90% of the LUTs and 97% of the
flip-flops of the whole RC host surface — and, in the same run, the controlled
counter-example: `tlp_parser`'s `payload_data_mem` (`src/tlp/tlp_parser.sv:41`), a 1-D
unpacked array with the *same* asynchronous continuous-assign read, the *same* clocked
write at a different address, and the *same* absence of reset, which Vivado mapped to
**`RAM64M8` × 80 / 768 LUTRAM**. The only difference is the second unpacked dimension,
and Vivado named it: `[Synth 8-11357] … 3D-RAM … data_mem_reg with 131840 registers`.

S-2 changes exactly that one variable.

## 1. The shape being adopted, and a correction to S-1's parenthetical

S-1's Recommendation 1 suggested indexing `{wr_packet_r, wr_word_r}` — a concatenation —
and noted that `MAX_PACKET_WORDS = 1030` is not a power of two, so a concatenation "wants"
a 2^11 stride. **S-2 does not do that, and the parenthetical is wrong to prefer it.**

`tlp_layer.sv:455` overrides `PACKET_DEPTH` only, leaving `MAX_PACKET_WORDS` at its 1030
default, so the shipped geometry is 4 slots × 1030 words:

| Flattening | Entries | Address logic |
|---|---|---|
| `{packet, word}`, stride 2^11 | 4 × 2048 = **8,192** | none (bit concatenation) |
| `packet * MAX_PACKET_WORDS + word` | 4 × 1030 = **4,120** | 2-bit `packet` selects one of four constants, then an 11-bit add |

The concatenation saves an adder and costs **double the storage**. With `packet` only two
bits wide, `packet * 1030` is not a multiplier at all — it is a four-way constant mux
feeding one 13-bit adder, on the order of tens of LUTs. Paying ~3,400 LUTRAM twice to
avoid that would be a bad trade in a brief whose entire purpose is area. **S-2 uses
`packet * MAX_PACKET_WORDS + word`**, computed once into a `wr_index` / `rd_index` wire
pair so the arrays present the textbook simple-dual-port distributed-RAM shape: one
clocked write port, one asynchronous read port, no reset.

## 2. Predictions

### 2.1 Inference primitive

- **P1.** The four arrays infer **distributed RAM** from the `RAM64M8` / `RAM64X1S`
  family — the same primitives `tlp_parser` already gets. **No `[Synth 8-11357]`
  3D-RAM warning for `data_mem_reg`, `keep_mem_reg` or `user_mem_reg`.**
- **P2.** **Zero BRAM, zero URAM.** The read is asynchronous (`tlp_vc_buffer.sv:60-63`);
  block RAM has no asynchronous read path, so it is not eligible however large the array
  gets. If BRAM appears, something other than the reshape happened.
- **P3.** `last_mem` is 1 bit wide. It may infer as RAM or stay registers without
  materially moving the totals; this one is not load-bearing.

### 2.2 Area — the numbers this note is judged on

Scaling reference: `tlp_parser`'s **measured** 768 LUTRAM for 1,024 × 36 bits (36,864
bits ⇒ ≈48 bits per LUTRAM cell after addressing overhead). The reshaped buffer is
4,120 × 40 bits = **164,800 bits**, 4.47× the parser's memory.

| # | Quantity | S-1 measured | **S-2 predicted** |
|---|---|---|---|
| **P4** | `tlp_vc_buffer` LUTRAM | 10 | **≈ 3,400** (range 3,000–4,200) |
| **P5** | `tlp_vc_buffer` total LUT | 54,877 | **≈ 5,000** (range 3,500–7,000) |
| **P6** | `tlp_vc_buffer` FF | 152,636 | **≈ 100** (range 80–200) |
| **P7** | `pcie_rq_rc_top` total LUT | 60,874 | **≈ 11,000** (range 9,000–14,000) |
| **P8** | `pcie_rq_rc_top` FF | 156,634 | **≈ 4,100** (range 4,000–4,400) |
| **P9** | `pcie_rq_rc_top` BRAM / URAM / DSP | 0 / 0 / 0 | **0 / 0 / 0** |

**P6/P8 derivation, stated so it can be checked rather than believed.** Once the four
payload arrays leave the flip-flops, the only sequential state left in the buffer is
`wr_packet_r`+`rd_packet_r` (2+2), `wr_word_r`+`rd_word_r` (11+11), `packet_count_r` (3),
`transmitting_r` (1), `overflow_o` (1), `class_mem` (4×2 = 8) and `credit_mem`
(4×12 = 48) — **87 bits**, plus whatever Vivado keeps around the RAM address paths.
`word_count_mem`'s 44 bits do not count: S-1 §5.2 recorded Vivado already deleting them
as unread. S-1 §4.2 measured everything in Unit B *outside* the buffer at **5,997 LUT /
3,998 FF**, and the reshape does not touch any of it, so P7 = 5,997 + P5 and
P8 = 3,998 + P6.

**This is where S-2 departs from S-1's own projection.** S-1 §4.3 extrapolated "roughly
12,000 LUTs and 6,300 FFs". The LUT figure is close to P7. The **6,300 FF figure is not
reachable** — 3,998 FFs exist outside the buffer and the buffer cannot plausibly retain
2,300 once its arrays are RAM. P8 says **≈4,100**. If the measurement lands near 6,300,
P8 is falsified and S-1's extrapolation was right for a reason S-2 has not understood.

### 2.3 Fit

- **P10.** The RC vertical (both units summed) drops from 62,714 LUT / 158,841 FF to
  **≈12,800 LUT (≈5.6%) / ≈6,300 FF (≈1.4%)** of the ZU7EV, putting it back under the
  10% line that S-1 §3.6 predicted and the VC buffer alone falsified.

### 2.4 Timing — and the caveat that governs how it may be read

- **P11.** WNS will still be negative and still around **−1.0 ns**, and the worst paths
  will still be the `tlp_request_tracker` completion-match cone identified in S-1 §4.2.

> ⚠️ **The WNS number is not evidence about the VC buffer, before or after.** Carried
> forward verbatim from S-1 §4.4: the buffer's read is a continuous assignment onto
> `m_dllp_axis_tdata`, an **output port**, and this flow writes no `set_output_delay`.
> That path is therefore **unconstrained** — the 54,877 LUTs of multiplexer S-1 measured
> produced **zero** hits when grepping `vc_buffer` in `timing_worst20.rpt`. A reshaped
> buffer will be equally invisible. **An improved WNS in S-2 would not be VC-buffer
> progress, and an unchanged or worse WNS would not be a VC-buffer regression.** The
> only honest timing statement S-2 can make is about what the reshape does to the
> *tracker's* cone, which is nothing, because it does not touch it.

- **P12.** `WARNING: [Netlist 29-101]` ("cellview `tlp_vc_buffer` contains a large number
  of primitives", S-1 §4.4) **disappears**. This is a better proxy for the reshape
  landing than any timing number in the report.

## 3. What would make this a failure rather than a falsification

The reshape is behaviour-preserving by construction — same ports, same pointers, same
state machine, only the storage declaration and eight index expressions change. It is
gated on the Phase-1 test suite: 11 tests across two geometries, including cross-slot
isolation at equal word offsets, all four corners of the flat index, the asynchronous-read
semantic sampled pre-edge, and a non-power-of-two geometry where the slot-wrap ternary is
load-bearing. **A red test is a revert, not an iteration.** Predictions P1–P12 are about
the netlist; none of them licenses a behavioural change.
