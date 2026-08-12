# RECON — Completion Timeout in `tlp_request_tracker` (Phase 0, read-only)

**Branch:** `kourosh/dev` · **Anchor:** `cc1e194` · **Date:** 2026-07-28
**Tree state at start:** clean (`git status --porcelain` empty). `RECON_commit2a.md` was NOT dirty
this session.

Read-only. No RTL was edited before this document existed.

---

## 1. Per-tag storage in `tlp_request_tracker.sv`

Six parallel per-tag arrays plus one occupancy bit-vector — there is no packed struct, no FSM,
and no state enum. State is exactly one bit per tag: `active_r`.

| What | Where | Notes |
|---|---|---|
| occupancy | `tlp_request_tracker.sv:36` | `logic [TAG_COUNT-1:0] active_r` — the entire per-tag state |
| requester ID | `:37` | matched against the CPL's RID |
| bytes still owed | `:38` | `remaining_r`, decremented per partial CPL |
| caller context | `:39` | echoed to `result_context_o` |
| expects data | `:40` | CplD vs Cpl discrimination |
| expected Lower Address | `:41` | `next_lower_address_r`, advanced per partial CPL |

**Allocation** — `:55-65`. Combinational priority-encode over `!active_r[i]`, gated by
`extended_tag_enable_i || i < 32` (`:59-60`); `allocate_ready_o = tag_found` (`:65`). The commit is
at `:113-121` on `allocate_valid_i && allocate_ready_o`.

**Completion match** — `:69-76`. Combinational priority-encode over `active_r[i] && tag match &&
requester_id match`. Note the match requires `active_r[i]`, so today a completion for a freed tag
falls into the `!completion_match` branch (`:124-126`) and raises
`unexpected_completion_o` + `TLP_ERR_UNEXPECTED_COMPLETION`.

**Release (the "bit 30" release)** — `:143-148`. The condition is
`!expects_data || status != TLP_CPL_SC || payload_bytes >= remaining`, i.e. last-CPL-of-request.
The *same* expression drives `result_last_r` at `:140-142`. Confirmed downstream:
`pcie_rc_if.sv:261` `desc_next.request_completed = result_last_i` — RC descriptor bit 30 **is**
`result_last_o`. The partial-CPL branch is `:149-154` (decrement `remaining_r`, advance
`next_lower_address_r`, tag stays allocated).

**Backpressure** — `completion_ready_o = !result_valid_r || result_ready_i` at `:77` (brief's `:77`
estimate exact). `result_valid_o` is *not* a free pulse: it is a registered valid with a real
handshake, cleared at `:110-111`. `pcie_rc_if.sv:41-68` documents and depends on this.

**Reset** — `:91-106`, synchronous, clears `active_r` and every array.

---

## 2. Port-threading path (shorter than the brief assumed)

`tlp_request_tracker` is instantiated **once**, in `tlp_layer.sv:365-389`. It is *not* inside
`pcie_rq_if` or `pcie_rc_if` — those wrappers sit beside `tlp_layer`, not around the tracker. So
the thread is two hops, not four:

```
tlp_request_tracker (src/tlp/tlp_request_tracker.sv)
  └─ tlp_layer.sv:365          ports declared tlp_layer.sv:140-151
       ├─ pcie_rq_rc_top.sv:394-520      ports declared :255-289   ← the 2b socket
       ├─ pcie_endpoint_top.sv:165-287   ports declared :132-143
       ├─ tb/rc/tb_pcie_rq_if_tlp.sv:145
       └─ tb/rc/tb_pcie_rc_if_tlp.sv:198
```

Precedent to copy exactly: `unexpected_completion_o` (`tlp_layer.sv:148` →
`pcie_rq_rc_top.sv:518` → `pcie_rc_if` → `rc_unexpected_completion_o` at `:265`) and the
`allocated_tag_o`/`allocated_tag_valid_o` tap (`tlp_layer.sv:184-185` → `pcie_rq_rc_top.sv:454-455`
→ `pcie_rq_tag_o`/`pcie_rq_tag_vld_o`). The new strobes follow the `allocated_tag_*` shape: raised
straight out of `tlp_layer` to top-level ports, **not** routed through `pcie_rc_if`.

`tb_pcie_rq_rc_top.sv:137-220` is the bench wrapper for the integration tests; it already surfaces
`pcie_rq_tag_o`/`pcie_rq_tag_vld_o` (`:71-72,176-177`) which V-T1's tag correlation needs.

---

## 3. Payload beats vs the tracker's match decision — **the brief's §2.3 premise is wrong, in our favour**

**The tracker has no payload interface at all.** Its completion port is header-only:
`completion_valid_i` / `completion_header_i` / `completion_payload_bytes_i` (`:21-24`) — one
handshake per completion, carrying a 13-bit *byte count*, never beats.

`tlp_layer` splits the two surfaces:

* header → tracker: `completion_valid_i = parsed_header_valid && parsed_completion &&
  received_completion_ready_i` (`tlp_layer.sv:381`); `completion_payload_bytes` is computed
  combinationally at `:243-248` from `length_dw`, `lower_address[1:0]` and `byte_count`.
* payload beats → **bypass the tracker entirely**: `received_completion_data_o` /
  `_valid_o` / `_last_o` (`tlp_layer.sv:254-257`), routed by `route_completion_r`, which latches
  `parsed_completion` on the header handshake (`:265-266`) and clears on `parsed_data_last`
  (`:267-268`). Payload ready comes from `received_completion_data_ready_i` (`:258-259`).

**Consequence: a ZOMBIE drain in the tracker is beat-free.** It consumes exactly one header
handshake and produces no result. Nothing about payload accounting lives in the module being
changed.

**And the beat drain already exists.** `pcie_rc_if.sv:341-343`:

```
received_completion_data_ready_o = (state_r == S_PAYLOAD) ? gb_tready
                                 : (state_r == S_IDLE)    ? !result_valid_i : 1'b0;
```

S_IDLE is documented at `:277` as "waiting for a result; draining any payload that has none", and
`:406` `$warning`s once per orphaned Dword. A ZOMBIE completion produces no result, so
`result_valid_i` stays low, so the drain stays ready for the whole packet. **No wedge, and no new
byte-counting code anywhere.** This is the same path the existing `unexpected_completion` tests
already exercise.

### Recurring-failure-mode check (header length vs beats actually sent — the RC3/RC5 class)

* **How many beats can a late completion have?** TL_DATA_WIDTH is 32, so one beat per Dword:
  `length_dw` beats, 1 … 1024 (the parser's ceiling). A CplD for a config read is always exactly 1.
* **How does the drain count them?** It doesn't — and that is the point. The drain is
  `ready = 1` for as long as the FSM is in S_IDLE with no result; termination comes from the
  parser's `tlast` clearing `route_completion_r` (`tlp_layer.sv:267-268`), not from a counter this
  work adds. **The new code introduces no byte-accounting logic, so it cannot reproduce RC3/RC5.**
  The residual risk is entirely in the pre-existing parser length contract, unchanged here.
* The tracker's own byte accounting (`remaining_r`, `next_lower_address_r`) is **skipped** on the
  ZOMBIE path by policy §1.4 ("silently drains"), so the malformed-CPL guard at `:127-135` does not
  run for a zombie. This is a deliberate, documented deviation — see SPEC_PREDICTIONS §D.
* T6 must therefore be an **integration** test (`tlp_layer` in the loop) to have any beats at all.
  A standalone-tracker T6 would be vacuous: there is no payload port to drive.

---

## 4. Does any existing test hold a tag long enough to trip 4096 cycles? — **No. Measured, not estimated.**

Both tag-heavy targets were run at `cc1e194` and their per-test sim times read off the cocotb
summary:

| Target | Longest test | Sim time | Clock | **Cycles** | Headroom vs 4096 |
|---|---|---|---|---|---|
| `verilate_tlp_conf_tracker` | `tag_exhaustion` | 1770 ns | 10 ns | **177** | 23× |
| `verilate_rq_rc_top` | `v4_backpressure_tag_exhaustion_recovery` | 2424 ns | 4 ns | **606** | 6.8× |

`v4` is the tightest case in the whole suite and still has 6.8× margin. Every cocotb test in
tb/tlp and tb/rc calls an `init_top`-style helper that pulses `rst_i` (e.g.
`test_tlp_conf_tracker.py:69-75`), and `rst_i` clears `active_r` (`:92-93`), so **timers cannot
accumulate across tests** — each test's clock starts from its own reset.

Static sweep for long waits: the only `ClockCycles(..., >=1000)` calls in the repo are in
`tb/ltssm/` (`test_ltssm_partial_lanes.py:152,296`, `test_ltssm_recovery_partial_lanes.py:179`),
and no LTSSM bench instantiates `tlp_layer`.

**No STOP condition. 4096 stands as the default.** §5.2 will confirm this empirically with a live
strobe monitor rather than resting on this analysis.

---

## 5. Does anything already resemble a timeout / expiry path? — **No. Verified, not inherited.**

`grep -niE "timeout|expire|expiry|timer|watchdog|stale|zombie"` over `src/tlp/*.sv` and
`src/rc/*.sv`, excluding comment-only lines, returns **zero hits**. The only mentions of the word
are the KNOWN_GAPS prose at `pcie_rq_rc_top.sv:106-119` that motivated this brief. There is no
free-running counter in `tlp_request_tracker`, `tlp_layer` or `tlp_requester`; the only sequential
state in the tracker is the six arrays plus the result register.

---

## 6. Proposed mechanism (refinement of the brief's suggestion — the structure fits it)

The brief's shape (free-running counter + per-tag timestamp + round-robin scan) fits the existing
array-per-field layout exactly, so it is adopted as written, with three refinements the recon
forced:

1. **Scan/completion conflict.** The scan writes `active_r[scan_index_r]`; the completion path
   writes `active_r[completion_index]`. Same cycle, same index is possible. Rather than rely on
   last-assignment-wins, the scan is *guarded* to be mutually exclusive:
   `scan_expired &&= !(completion_fires && completion_index == scan_index_r)`. A completion landing
   in the exact expiry cycle wins, and no false `cpl_timeout_valid_o` is emitted for a tag that
   actually completed. Allocation cannot collide (it only picks `!active && !zombie`; the scan only
   fires on `active || zombie`).
2. **The timestamp is reused for the ZOMBIE interval** — on the IN_FLIGHT→ZOMBIE transition the
   scan rewrites `alloc_time_r[i] <= cycle_counter_r`, so §1.4(b)'s "second expiry" is one more
   full `CPL_TIMEOUT_CYCLES`. No second timer.
3. **Timer restart (§1.3) is applied on *any* matched completion handshake**, including one
   rejected by the malformed-CPL guard at `:127-135`, since that CPL leaves the tag IN_FLIGHT. This
   is the forgiving reading of "restarts on every received completion for that tag" and is
   documented in the module header as such.

`scan_index_r` is a plain wrapping counter, so with `TAG_COUNT=32` it tracks `cycle_counter_r[4:0]`
and expiry timing is fully deterministic — which is what makes T1's exact-cycle assertion possible
rather than a window. Worst-case detection latency is `TAG_COUNT` cycles; irrelevant at 4096-cycle
granularity, documented in the header. `cycle_counter_r` is 32-bit and modular subtraction makes
wraparound correct for any `CPL_TIMEOUT_CYCLES < 2^31`.

Nothing needs to be added to `tlp_pkg` — the ZOMBIE state is a second per-tag bit-vector
(`zombie_r`) alongside `active_r`, not an enum.

### `outstanding_o` (§1.7)

Today `outstanding_o` is a combinational popcount of `active_r` (`:79-82`), documented at
`pcie_rq_rc_top.sv:285-287` as "non-posted requests currently holding a tag". A ZOMBIE **is**
holding a tag (it is not allocatable), so it must count — `popcount(active_r | zombie_r)` keeps the
documented contract self-consistent. With `CPL_TIMEOUT_CYCLES=0`, `zombie_r` is permanently 0 and
the expression is bit-identical to today's.

### Parameter plumbing

No `.core` in this repo overrides a parameter for a tb target; the only precedent is
`pcie_phy.core:81,122-127` (`parameters: [SIM_FAST_LINK=1]` + a `parameters:` block with
`paramtype: vlogparam`). That mechanism applies to the **toplevel** module, so
`tb_tlp_request_tracker` gains a pass-through `CPL_TIMEOUT_CYCLES` parameter and `tlp_layer` gains
a real one. No `-G` on the CLI, per brief §6.
