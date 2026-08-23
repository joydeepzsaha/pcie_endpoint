#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_stage_s.sh -- Stage S driver: two units x two clock corners = four cold
# Vivado batch runs, plus the log-side evidence the Tcl cannot collect.
#
# Vivado must be on PATH (source ~/tools/vivado_env.sh) in a shell that has
# NEVER sourced the conda pcie environment.  The file list must already exist;
# generate it from the OTHER shell with synth/stage_s_filelist.sh.
#
# Nothing this script produces is committed.  Everything lands in $OUTROOT.
#
#   ./synth/run_stage_s.sh                       # all four cells
#   ./synth/run_stage_s.sh pcie_rc_dl_top        # both corners of one unit
#   PERIODS="8.000" ./synth/run_stage_s.sh       # one corner of both units
#
# ---------------------------------------------------------------------------
# THE TWO CORNERS, AND WHY BOTH ARE REPORTED
#
#   8.000 ns / 125.0 MHz  -- primary
#  16.000 ns /  62.5 MHz  -- relaxed
#
# 62.5 MHz is the Gen1 x1 line-rate FLOOR for a 32-bit datapath (2.5 GT/s,
# 8b/10b -> 250 MB/s -> 250/4 = 62.5 MHz).  125 MHz is one PIPE-natural step
# above it.  Neither is cherry-picked: both are run, both are reported, and
# every number in the report carries its period.  See synth/stage_s_ooc.xdc for
# the full basis.
#
# NO CONSTRAINT CHASING.  If a run errors, capture the log and stop.  Changing a
# constraint to improve a number is a new scored prediction cycle, not a tuning
# loop inside this script.
# ---------------------------------------------------------------------------
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"

OUTROOT="${OUTROOT:-/var/tmp/kourosh_synth/stage-s}"
PART="${PART:-xczu7ev-ffvc1156-2-e}"
FILELIST="${FILELIST:-$OUTROOT/stage_s.f}"
PERIODS="${PERIODS:-8.000 16.000}"

UNITS=("$@")
if [ ${#UNITS[@]} -eq 0 ]; then
  UNITS=(pcie_rc_dl_top pcie_enum_dl_top)
fi

if ! command -v vivado >/dev/null 2>&1; then
  echo "FATAL: vivado not on PATH. source ~/tools/vivado_env.sh first." >&2
  exit 1
fi
# The environment guard that matters: a shell carrying the conda pcie env is the
# wrong shell for Vivado, and the failure mode is a confusing library clash
# rather than a clean error.
if [ -n "${CONDA_PREFIX:-}" ]; then
  echo "FATAL: CONDA_PREFIX=$CONDA_PREFIX is set. Run Vivado from a clean shell." >&2
  exit 1
fi
if [ ! -f "$FILELIST" ]; then
  echo "FATAL: $FILELIST missing. Generate it from the conda pcie shell:" >&2
  echo "         conda activate pcie && ./synth/stage_s_filelist.sh $OUTROOT" >&2
  exit 1
fi

mkdir -p "$OUTROOT"
VIVADO_VERSION="$(vivado -version 2>/dev/null | head -1)"
echo "== Stage S: $VIVADO_VERSION"
echo "== part=$PART"
echo "== filelist=$FILELIST ($(grep -cv '^\s*\(#\|$\)' "$FILELIST") files)"
echo "== units=${UNITS[*]}  periods=$PERIODS"
echo "== outroot=$OUTROOT"

overall=0
for unit in "${UNITS[@]}"; do
  for period in $PERIODS; do
    tag="$(printf '%.3f' "$period")"
    outdir="$OUTROOT/${unit}_${tag}"
    mkdir -p "$outdir"
    log="$outdir/vivado.log"
    summary="$outdir/run_summary.txt"
    start_time="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    start_epoch="$(date '+%s')"

    echo
    echo "======================================================================"
    echo "== $unit @ ${tag} ns  ($(date '+%F %T'))"
    echo "======================================================================"

    vivado -mode batch -nojournal -log "$log" \
           -source "$REPO/synth/stage_s_ooc.tcl" \
           -tclargs "$unit" "$period" "$FILELIST" "$OUTROOT" "$PART"
    rc=$?
    echo "== $unit @ ${tag} ns: vivado exit $rc"
    [ $rc -ne 0 ] && overall=1

    end_epoch="$(date '+%s')"
    elapsed=$((end_epoch - start_epoch))
    # Vivado's own accounting, quoted rather than paraphrased.
    synth_timing="$(grep -E '^synth_design: Time' "$log" 2>/dev/null | tail -1)"
    peak_mem="$(grep -oE 'Memory \(MB\): peak = [0-9.]+' "$log" 2>/dev/null | tail -1)"

    {
      echo "flow=synthesis"
      echo "status=$([ $rc -eq 0 ] && echo success || echo failed)"
      echo "exit_status=$rc"
      echo "unit=$unit"
      echo "period_ns=$tag"
      echo "vivado_version=$VIVADO_VERSION"
      echo "part=$PART"
      [ -f "$outdir/constraint_values.txt" ] && cat "$outdir/constraint_values.txt"
      echo "started=$start_time"
      echo "finished=$(date '+%Y-%m-%dT%H:%M:%S%z')"
      echo "elapsed_seconds=$elapsed"
      echo "synth_design_timing=$synth_timing"
      echo "vivado_peak_memory=$peak_mem"
    } > "$summary"

    # ---- log-side harvest ---------------------------------------------------
    # Latch inference and combinational loops: the netlist-side answer is in
    # latches_netlist.txt (written by the Tcl); this is the corroborating view,
    # and the two disagreeing is itself a finding.
    grep -inE 'latch|combinational loop|inferred' "$log" > "$outdir/latches.txt" 2>/dev/null
    # One line per distinct Vivado message ID with a count, so the findings doc
    # can quote one verbatim example per class instead of thousands of lines.
    grep -oE '^(CRITICAL WARNING|ERROR|WARNING|INFO): \[[^]]+\]' "$log" 2>/dev/null \
      | sort | uniq -c | sort -rn > "$outdir/message_classes.txt"
    grep -cE '^ERROR:' "$log" > "$outdir/error_count.txt" 2>/dev/null || true
    echo "== $unit @ ${tag} ns: elapsed ${elapsed}s, $(cat "$outdir/error_count.txt" 2>/dev/null || echo '?') ERROR line(s), $(wc -l < "$outdir/message_classes.txt") message class(es)"
  done
done

echo
echo "== Stage S driver finished, overall exit $overall"
exit $overall
