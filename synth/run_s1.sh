#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_s1.sh -- Stage S-1 driver. Runs every RC-side unit through s1_ooc.tcl
# sequentially and harvests the log-side evidence the Tcl cannot.
#
# MUST be run from a shell that has sourced /home/kourosh/tools/vivado_env.sh,
# and MUST NOT be run from the conda pcie / Verilator environment -- the two
# toolchains are kept in separate shells on purpose. The check below enforces
# it rather than trusting the operator.
#
# Nothing this script produces is committed. Everything lands in $OUTROOT.
#
#   ./synth/run_s1.sh                    # both units
#   ./synth/run_s1.sh pcie_enum_top      # one unit
# ---------------------------------------------------------------------------
set -u -o pipefail

REPO="${REPO:-/home/kourosh/pcie_endpoint}"
OUTROOT="${OUTROOT:-/home/kourosh/synth_s1}"
PART="${PART:-xczu7ev-ffvc1156-2-e}"
PERIOD="${PERIOD:-4.000}"     # 250 MHz placeholder -- see s1_ooc.tcl header

UNITS=("$@")
if [ ${#UNITS[@]} -eq 0 ]; then
  UNITS=(pcie_enum_top pcie_rq_rc_top)
fi

# ---- environment guard ----------------------------------------------------
if ! command -v vivado >/dev/null 2>&1; then
  echo "FATAL: vivado not on PATH. source /home/kourosh/tools/vivado_env.sh first." >&2
  exit 1
fi
if command -v verilator >/dev/null 2>&1; then
  echo "FATAL: verilator is on PATH -- this is the conda pcie shell." >&2
  echo "       Vivado and Verilator must not share a shell. Start a fresh one." >&2
  exit 1
fi

mkdir -p "$OUTROOT"
echo "== S-1: vivado $(vivado -version 2>/dev/null | head -1)"
echo "== part=$PART  period=${PERIOD}ns  outroot=$OUTROOT"

overall=0
for unit in "${UNITS[@]}"; do
  outdir="$OUTROOT/$unit"
  mkdir -p "$outdir"
  log="$outdir/vivado.log"

  echo
  echo "======================================================================"
  echo "== $unit  ($(date '+%F %T'))"
  echo "======================================================================"

  # -nojournal keeps vivado.jou out of the tree; -log pins the full log next
  # to the reports so the grep below and the findings doc read the same file.
  vivado -mode batch -nojournal -log "$log" \
         -source "$REPO/synth/s1_ooc.tcl" \
         -tclargs "$unit" "$REPO" "$OUTROOT" "$PART" "$PERIOD"
  rc=$?
  echo "== $unit: vivado exit $rc"
  [ $rc -ne 0 ] && overall=1

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
