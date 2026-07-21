# LTSSM timeout constant table (Phase 7A standing reference)

Source: `src/ltssm/pcie_ltssm_downstream.sv` localparams (lines ~108-121) +
PCIe Base Spec Rev 2.1 §4.2.6 / Table 4-9 (`openPCIE/0.doc/PCIE-base-spec.Rev2-1.pdf`).
Clock: `CLK_RATE=100` MHz ⇒ `ClockPeriodNs = 1000/CLK_RATE = 10 ns`.
Counter: `timer_r` is **`logic [63:0]`** (declared line 184), resets to 0 on every
state transition (line 452-453), free-runs +1/cycle capped at 48 ms (line 459).
Count gate: `MinTS1sPolling` counts on `ordered_set_sent_cnt_r` (`logic [15:0]`, line 243).

| Timeout | RTL constant | fast-sim value (cyc) | real value (cyc) | SIM_FAST_LINK scale | real time | spec ref | states using it | bits needed | width (64) OK |
|---|---|---|---|---|---|---|---|---|---|
| Detect.Quiet → Active | `TwelveMsTimeOut` | 1,200 | 1,200,000 | **÷1000** | 12 ms | §4.2.6.1.1 (12 ms) | DETECT_QUIET(561), DETECT_RX(605) | 21 | ✓ |
| Detect.Wait.One.Ms | `OneMsTimeOut` | 100 | 100,000 | **÷1000** | 1 ms | §4.2.6.1.1 note | DETECT_WAIT_ONE_MS(544) — *unreachable in Gen1* | 17 | ✓ |
| 24 ms watchdog | `TwentyFourMsTimeOut` | 2,400,000 | 2,400,000 | **÷1 (NOT scaled)** | 24 ms | §4.2.6.2.1 (Polling.Active 24 ms); Detect | DETECT_ACTIVE(594), DETECT_RX(618), POLLING_ACTIVE(672,714), CFG_LW_START(803), RECOVERY(1078,1170,1186,1195) | 22 | ✓ |
| 48 ms watchdog | `FourtyEightMsTimeOut` | 4,800,000 | 4,800,000 | **÷1 (NOT scaled)** | 48 ms | §4.2.6.2.3 (Polling.Config 48 ms) | timer cap(459), POLLING_CONFIG(753), RECOVERY_EQUAL(1318), RECOVERY_SPEED(1372) | 23 | ✓ |
| 2 ms watchdog | `TwoMsTimeOut` | 200,000 | 200,000 | **÷1 (NOT scaled)** | 2 ms | §4.2.6.3.2-.6 (Config substates 2 ms) | CFG_LW_ACCEPT(851), LANENUM_ACCEPT(880), LANENUM_WAIT(913), COMPLETE(944), CFG_IDLE(976), RECOVERY_IDLE(1455) | 18 | ✓ |
| 6 µs | `SixUsTimeOut` | 600 | 600 | ÷1 | 6 µs | Recovery.Speed | RECOVERY_SPEED_WAIT(1402) | 10 | ✓ |
| 800 ns | `EigthHundredNanoSecondTimeOut` | 80 | 80 | ÷1 | 800 ns | Recovery.Speed | RECOVERY_SPEED_WAIT(1384) | 7 | ✓ |
| 20 ns | `TwentyNanoSeconds` | 2 | 2 | ÷1 | 20 ns | — (declared) | (declared, no live compare) | 2 | ✓ |
| Polling min TS1 count | `MinTS1sPolling` | 24 | 1024 | **÷~42.7** | n/a (count) | §4.2.6.2.1 (1024 TS1) | POLLING_ACTIVE(659,672) | 11 | ✓ (16-bit ctr) |

## Finding 1 — counter width: CLEAN (no overflow)
`timer_r` is 64-bit; the widest real value (48 ms = 4,800,000 cyc) needs 23 bits.
Every constant fits with ~40 bits of headroom. **No latent counter-width overflow.**
The count gate `ordered_set_sent_cnt_r` is 16-bit; real `MinTS1sPolling=1024`
needs 11 bits — also fine. This is the highest-value thing 7A could have found;
it is genuinely absent here because the counter is over-provisioned.

## Finding 2 — scaling is NOT single-factor (known, already documented)
`SIM_FAST_LINK` scales only **`TwelveMsTimeOut`, `OneMsTimeOut` (÷1000)** and
**`MinTS1sPolling` (÷~42.7)**. `TwentyFourMsTimeOut`, `FourtyEightMsTimeOut`,
`TwoMsTimeOut`, `SixUsTimeOut`, `EigthHundredNanoSecondTimeOut`,
`TwentyNanoSeconds` are **unscaled** — real magnitude in both modes. So:
- fast-sim ↔ real does **not** map by any single factor (three behaviours: ÷1000,
  ÷~42.7, ÷1).
- The 24/48/2 ms watchdog *paths* already run at real magnitude even under
  `SIM_FAST_LINK=1` (this is why `test_ltssm_polling_timeout` /
  `test_ltssm_config_timeout` "take several real-world minutes" — see their
  headers). Those two existing tests already validate the 24 ms / 2 ms guarded
  watchdogs (bugs 4 & 5) at real magnitude.
- This is already noted in `tb/ltssm/test_ltssm_config_timeout.py` and flagged as
  an open question for Joy (should 24/48/2 ms also gain a fast scale?). **Not
  silently changed here — RTL untouched.**

## What `SIM_FAST_LINK=0` (realtimer) actually adds over the fast tests
Only three constants change at real magnitude, so the realtimer suite targets
exactly those:
- **`TwelveMsTimeOut`** — Detect.Quiet's 12 ms "proceed anyway" timer. Never run
  at real magnitude (fast=1,200 cyc; happy path exits Detect.Quiet on elec-idle
  before the timer). → `test_detect_quiet_12ms_real`.
- **`MinTS1sPolling=1024`** — real Polling.Active TS1 count. → exercised by the
  capstone real link-up.
- **`OneMsTimeOut`** — Detect.Wait.One.Ms; **unreachable in a Gen1 link** (entered
  only when `curr_data_rate_r.rate != gen1`, line 531). Documented, not tested
  (would need a contrived non-Gen1 entry).
