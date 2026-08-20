#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_par.sh -- OOC place-and-route driver for checkpoints made by run_s1.sh.
#
# Vivado must be available on PATH. By default, inputs and outputs are under
# build/vivado so `make syn` and `make par` use the same deterministic tree.
#
#   ./synth/run_par.sh                    # both units
#   ./synth/run_par.sh pcie_enum_top      # one unit
# ---------------------------------------------------------------------------
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"

REPO="${REPO:-$DEFAULT_REPO}"
SYNROOT="${SYNROOT:-$REPO/build/vivado/syn}"
OUTROOT="${OUTROOT:-$REPO/build/vivado/par}"
PART="${PART:-xczu7ev-ffvc1156-2-e}"

UNITS=("$@")
if [ ${#UNITS[@]} -eq 0 ]; then
  UNITS=(pcie_enum_top pcie_rq_rc_top)
fi

if ! command -v vivado >/dev/null 2>&1; then
  echo "FATAL: vivado not on PATH. Source your Vivado installation's settings64.sh first." >&2
  exit 1
fi

mkdir -p "$OUTROOT"
VIVADO_VERSION="$(vivado -version 2>/dev/null | head -1)"
echo "== PAR: $VIVADO_VERSION"
echo "== part=$PART  synroot=$SYNROOT  outroot=$OUTROOT"

overall=0
for unit in "${UNITS[@]}"; do
  synth_dir="$SYNROOT/$unit"
  input_dcp="$synth_dir/$unit.dcp"
  synth_summary="$synth_dir/run_summary.txt"
  outdir="$OUTROOT/$unit"
  log="$outdir/vivado.log"
  summary="$outdir/run_summary.txt"
  mkdir -p "$outdir"

  start_time="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  start_epoch="$(date '+%s')"

  if [ ! -f "$input_dcp" ]; then
    echo "ERROR: missing synthesis checkpoint $input_dcp" >&2
    echo "       Run 'make syn${unit:+ UNIT=$unit}' first." >&2
    {
      echo "flow=place_and_route"
      echo "status=failed"
      echo "exit_status=1"
      echo "unit=$unit"
      echo "reason=missing synthesis checkpoint"
      echo "input_checkpoint=$input_dcp"
      echo "started=$start_time"
    } > "$summary"
    overall=1
    continue
  fi

  if [ -f "$synth_summary" ] && ! grep -q '^status=success$' "$synth_summary"; then
    echo "ERROR: latest synthesis summary for $unit is not successful." >&2
    echo "       Run 'make syn UNIT=$unit' before place and route." >&2
    {
      echo "flow=place_and_route"
      echo "status=failed"
      echo "exit_status=1"
      echo "unit=$unit"
      echo "reason=latest synthesis was not successful"
      echo "input_checkpoint=$input_dcp"
      echo "started=$start_time"
    } > "$summary"
    overall=1
    continue
  fi

  {
    echo "flow=place_and_route"
    echo "status=running"
    echo "unit=$unit"
    echo "vivado_version=$VIVADO_VERSION"
    echo "part=$PART"
    echo "input_checkpoint=$input_dcp"
    echo "started=$start_time"
  } > "$summary"

  echo
  echo "======================================================================"
  echo "== $unit  ($(date '+%F %T'))"
  echo "======================================================================"

  vivado -mode batch -nojournal -log "$log" \
         -source "$REPO/synth/par_ooc.tcl" \
         -tclargs "$unit" "$REPO" "$SYNROOT" "$OUTROOT" "$PART"
  rc=$?
  echo "== $unit: vivado exit $rc"
  [ $rc -ne 0 ] && overall=1

  end_time="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  end_epoch="$(date '+%s')"
  elapsed_seconds=$((end_epoch - start_epoch))
  place_timing="$(grep -E '^place_design: Time' "$log" 2>/dev/null | tail -1)"
  route_timing="$(grep -E '^route_design: Time' "$log" 2>/dev/null | tail -1)"
  if [ $rc -eq 0 ]; then
    run_status="success"
  else
    run_status="failed"
  fi

  {
    echo "flow=place_and_route"
    echo "status=$run_status"
    echo "exit_status=$rc"
    echo "unit=$unit"
    echo "vivado_version=$VIVADO_VERSION"
    echo "part=$PART"
    echo "input_checkpoint=$input_dcp"
    echo "started=$start_time"
    echo "finished=$end_time"
    echo "elapsed_seconds=$elapsed_seconds"
    echo "place_design_timing=$place_timing"
    echo "route_design_timing=$route_timing"
  } > "$summary"

  grep -oE '^(CRITICAL WARNING|ERROR|WARNING|INFO): \[[^]]+\]' "$log" 2>/dev/null \
    | sort | uniq -c | sort -rn > "$outdir/message_classes.txt"
  grep -cE '^ERROR:' "$log" > "$outdir/error_count.txt" 2>/dev/null || true
done

echo
echo "== PAR driver finished, overall exit $overall"
exit $overall
