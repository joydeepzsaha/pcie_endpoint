#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_s1.sh -- Stage S-1 driver. Runs every RC-side unit through s1_ooc.tcl
# sequentially and harvests the log-side evidence the Tcl cannot.
#
# Vivado must be available on PATH. Source the settings64.sh file from the
# Vivado installation being used before running this script when necessary.
#
# Nothing this script produces is committed. Everything lands in $OUTROOT.
#
#   ./synth/run_s1.sh                    # both units
#   ./synth/run_s1.sh pcie_enum_top      # one unit
#   ./synth/run_s1.sh endpoint           # integrated Gen1 endpoint
# ---------------------------------------------------------------------------
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"

REPO="${REPO:-$DEFAULT_REPO}"
OUTROOT="${OUTROOT:-$REPO/build/vivado/syn}"
PART="${PART:-xczu7ev-ffvc1156-2-e}"
PERIOD="${PERIOD-}"
UNCERTAINTY="${UNCERTAINTY-}"
INPUT_DELAY_MIN="${INPUT_DELAY_MIN-}"
INPUT_DELAY_MAX="${INPUT_DELAY_MAX-}"
OUTPUT_DELAY_MIN="${OUTPUT_DELAY_MIN-}"
OUTPUT_DELAY_MAX="${OUTPUT_DELAY_MAX-}"

UNITS=("$@")
if [ ${#UNITS[@]} -eq 0 ]; then
  UNITS=(pcie_enum_top pcie_rq_rc_top)
fi

# ---- environment guard ----------------------------------------------------
if ! command -v vivado >/dev/null 2>&1; then
  echo "FATAL: vivado not on PATH. Source your Vivado installation's settings64.sh first." >&2
  exit 1
fi

mkdir -p "$OUTROOT"
VIVADO_VERSION="$(vivado -version 2>/dev/null | head -1)"
echo "== S-1: $VIVADO_VERSION"
echo "== part=$PART"
echo "== empty timing overrides use the selected unit's constraint defaults"
echo "== outroot=$OUTROOT"

overall=0
for unit in "${UNITS[@]}"; do
  outdir="$OUTROOT/$unit"
  mkdir -p "$outdir"
  log="$outdir/vivado.log"
  summary="$outdir/run_summary.txt"
  start_time="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  start_epoch="$(date '+%s')"

  {
    echo "flow=synthesis"
    echo "status=running"
    echo "unit=$unit"
    echo "vivado_version=$VIVADO_VERSION"
    echo "part=$PART"
    echo "clock_period_override_ns=$PERIOD"
    echo "clock_uncertainty_override_ns=$UNCERTAINTY"
    echo "input_delay_min_override_ns=$INPUT_DELAY_MIN"
    echo "input_delay_max_override_ns=$INPUT_DELAY_MAX"
    echo "output_delay_min_override_ns=$OUTPUT_DELAY_MIN"
    echo "output_delay_max_override_ns=$OUTPUT_DELAY_MAX"
    echo "started=$start_time"
  } > "$summary"

  echo
  echo "======================================================================"
  echo "== $unit  ($(date '+%F %T'))"
  echo "======================================================================"

  # -nojournal keeps vivado.jou out of the tree; -log pins the full log next
  # to the reports so the grep below and the findings doc read the same file.
  vivado -mode batch -nojournal -log "$log" \
         -source "$REPO/synth/s1_ooc.tcl" \
         -tclargs "$unit" "$REPO" "$OUTROOT" "$PART" "$PERIOD" \
                  "$UNCERTAINTY" "$INPUT_DELAY_MIN" "$INPUT_DELAY_MAX" \
                  "$OUTPUT_DELAY_MIN" "$OUTPUT_DELAY_MAX"
  rc=$?
  echo "== $unit: vivado exit $rc"
  [ $rc -ne 0 ] && overall=1

  end_time="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  end_epoch="$(date '+%s')"
  elapsed_seconds=$((end_epoch - start_epoch))
  synth_timing="$(grep -E '^synth_design: Time' "$log" 2>/dev/null | tail -1)"
  if [ $rc -eq 0 ]; then
    run_status="success"
  else
    run_status="failed"
  fi

  {
    echo "flow=synthesis"
    echo "status=$run_status"
    echo "exit_status=$rc"
    echo "unit=$unit"
    echo "vivado_version=$VIVADO_VERSION"
    echo "part=$PART"
    if [ -f "$outdir/constraint_values.txt" ]; then
      cat "$outdir/constraint_values.txt"
    else
      echo "clock_period_override_ns=$PERIOD"
      echo "clock_uncertainty_override_ns=$UNCERTAINTY"
      echo "input_delay_min_override_ns=$INPUT_DELAY_MIN"
      echo "input_delay_max_override_ns=$INPUT_DELAY_MAX"
      echo "output_delay_min_override_ns=$OUTPUT_DELAY_MIN"
      echo "output_delay_max_override_ns=$OUTPUT_DELAY_MAX"
    fi
    echo "started=$start_time"
    echo "finished=$end_time"
    echo "elapsed_seconds=$elapsed_seconds"
    echo "synth_design_timing=$synth_timing"
  } > "$summary"

  # ---- the log-side harvest ----------------------------------------------
  # Latch inference, combinational loops, and anything Vivado says it
  # "inferred" -- per the brief. The netlist-side answer is in
  # latches_netlist.txt, written by the Tcl; this is the corroborating view.
  grep -inE 'latch|combinational loop|inferred' "$log" > "$outdir/latches.txt" 2>/dev/null
  echo "== $unit: latches.txt $(wc -l < "$outdir/latches.txt") line(s)"

  # Warning/error census: one line per distinct Vivado message ID with a
  # count, so the findings doc can quote one verbatim example per class
  # instead of pasting thousands of lines.
  grep -oE '^(CRITICAL WARNING|ERROR|WARNING|INFO): \[[^]]+\]' "$log" 2>/dev/null \
    | sort | uniq -c | sort -rn > "$outdir/message_classes.txt"
  echo "== $unit: $(wc -l < "$outdir/message_classes.txt") distinct message class(es)"

  grep -cE '^ERROR:' "$log" > "$outdir/error_count.txt" 2>/dev/null || true
  echo "== $unit: $(cat "$outdir/error_count.txt" 2>/dev/null || echo '?') ERROR line(s)"
done

echo
echo "== S-1 driver finished, overall exit $overall"
exit $overall
