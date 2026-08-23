# ---------------------------------------------------------------------------
# stage_s_ooc.tcl -- Stage S, out-of-context synthesis of one RC-side TL+DLL
# stacked top at one clock period.
#
# Non-project batch flow.  Reads a GENERATED file list (synth/stage_s_filelist.sh),
# loads synth/stage_s_ooc.xdc BEFORE synth_design so synthesis is timing-driven,
# synthesizes out-of-context, and writes every report to
# $OUTROOT/<unit>_<period>/ -- OUTSIDE the repository.
#
# THIS SCRIPT CHANGES NO RTL AND WRITES NOTHING INTO THE REPO.
#
# Usage (Vivado on PATH; a shell that has never sourced the conda pcie env):
#
#   vivado -mode batch -nojournal -log <log> -source synth/stage_s_ooc.tcl \
#          -tclargs <unit> <period_ns> <filelist> [out_root] [part]
#
#   <unit> is pcie_rc_dl_top | pcie_enum_dl_top
#
# ---------------------------------------------------------------------------
# ONE SCRIPT, TWO UNITS -- A DELIBERATE DEPARTURE FROM THE BRIEF'S FILE NAMING
#
# The brief asks for synth/rc_dl_ooc.tcl and synth/enum_dl_ooc.tcl.  Those two
# files would differ by exactly one line -- the value of -top -- because both
# units share ONE identical 67-file RTL closure (RECON_STAGE_S.md D6, measured
# by diffing the two FuseSoC .vc lists: the only differing line is the bench).
# Duplicating a 200-line flow script to vary one token is the same second-owner
# failure the brief's own A3 forbids for the file list.  The unit is an
# argument.  Both invocations are recorded in the Stage-S report.
#
# ---------------------------------------------------------------------------
# WHAT THIS FLOW ADDS THAT NO EARLIER FLOW HAD
#
#  1. HOLD.  report_timing_summary -delay_type min_max, plus a dedicated
#     -delay_type min worst-path table.  synth/s1_ooc.tcl:223,225 and
#     synth/par_ooc.tcl:76,84,86 are all -delay_type max: no hold number has
#     ever been computed for this design, at synthesis or implementation.
#
#  2. A PATH-GROUP SPLIT that makes the I/O-delay budget's influence visible.
#     Three separate report_timing calls -- register-to-register,
#     input-bounded, output-bounded.  The reg2reg number is independent of the
#     I/O fraction entirely, so "does the design meet the clock" can be answered
#     without the answer being a function of a budget we guessed.
#
#  3. A GENERATED file list (see the header of synth/stage_s_filelist.sh).
#
# Reports go to files, never to -name GUI sessions.
# ---------------------------------------------------------------------------

# ---- arguments -------------------------------------------------------------
if {[llength $argv] < 3} {
  puts "ERROR: usage: -tclargs <unit> <period_ns> <filelist> \[out_root\] \[part\]"
  exit 1
}

set UNIT     [lindex $argv 0]
set PERIOD   [lindex $argv 1]
set FILELIST [lindex $argv 2]
set OUTROOT  [expr {[llength $argv] > 3 ? [lindex $argv 3] : "/var/tmp/kourosh_synth/stage-s"}]
set PART     [expr {[llength $argv] > 4 ? [lindex $argv 4] : "xczu7ev-ffvc1156-2-e"}]

set KNOWN_UNITS {pcie_rc_dl_top pcie_enum_dl_top}
if {[lsearch -exact $KNOWN_UNITS $UNIT] < 0} {
  puts "ERROR: unknown unit '$UNIT'. Known: $KNOWN_UNITS"
  exit 1
}
if {![string is double -strict $PERIOD] || $PERIOD <= 0.0} {
  puts "ERROR: period_ns must be a positive number; got '$PERIOD'"
  exit 1
}
if {![file exists $FILELIST]} {
  puts "ERROR: file list $FILELIST does not exist. Run synth/stage_s_filelist.sh first (conda pcie shell)."
  exit 1
}

# ---- the constraint globals the XDC reads ----------------------------------
# Every default and every validation lives HERE, not in the XDC: Vivado rejects
# `if` inside an XDC ([Designutils 20-1307], measured on 2023.2).  The bases for
# these values are written out in synth/stage_s_ooc.xdc, next to the constraint
# each one feeds.  Summary: uncertainty is ABSOLUTE (jitter is picoseconds, it
# does not scale with the period); the I/O budget is a FRACTION (a budget share
# must scale, or the two corners are not the same constraint); the I/O min is
# zero (the pessimistic hold assumption -- a non-zero min manufactures hold
# margin we have not earned, and hold is what this rung measures).
set ::STAGE_S_PERIOD_NS      $PERIOD
set ::STAGE_S_UNCERTAINTY_NS 0.100
set ::STAGE_S_IO_FRACTION    0.30
set ::STAGE_S_IO_MIN_NS      0.000

set PERIOD_TAG [format "%.3f" $PERIOD]
set OUTDIR $OUTROOT/${UNIT}_${PERIOD_TAG}
file mkdir $OUTDIR

proc mark {msg} {
  puts "===S=== $msg"
  flush stdout
}

mark "unit=$UNIT part=$PART period=${PERIOD}ns outdir=$OUTDIR"
mark "vivado=[version -short]"

# ---- read RTL --------------------------------------------------------------
set FILES {}
set fh [open $FILELIST r]
foreach line [split [read $fh] "\n"] {
  set line [string trim $line]
  if {$line eq "" || [string index $line 0] eq "#"} { continue }
  lappend FILES $line
}
close $fh

mark "PHASE read_verilog ([llength $FILES] files from $FILELIST)"
foreach f $FILES {
  if {![file exists $f]} {
    puts "ERROR: missing source file $f (regenerate with synth/stage_s_filelist.sh)"
    exit 1
  }
  read_verilog -sv $f
}

# ---- timing constraints, BEFORE synthesis ----------------------------------
set XDC [file join [file dirname [file normalize [info script]]] stage_s_ooc.xdc]
if {![file exists $XDC]} {
  puts "ERROR: missing $XDC"
  exit 1
}
mark "PHASE read_xdc $XDC (before synth_design -- timing-driven)"
read_xdc $XDC

set vf [open $OUTDIR/constraint_values.txt w]
puts $vf "unit=$UNIT"
puts $vf "part=$PART"
puts $vf "clock_period_ns=$::STAGE_S_PERIOD_NS"
puts $vf "clock_frequency_mhz=[format %.3f [expr {1000.0 / $::STAGE_S_PERIOD_NS}]]"
puts $vf "clock_uncertainty_ns=$::STAGE_S_UNCERTAINTY_NS"
puts $vf "io_delay_fraction=$::STAGE_S_IO_FRACTION"
puts $vf "input_delay_max_ns=[format %.3f [expr {$::STAGE_S_IO_FRACTION * $::STAGE_S_PERIOD_NS}]]"
puts $vf "input_delay_min_ns=$::STAGE_S_IO_MIN_NS"
puts $vf "output_delay_max_ns=[format %.3f [expr {$::STAGE_S_IO_FRACTION * $::STAGE_S_PERIOD_NS}]]"
puts $vf "output_delay_min_ns=$::STAGE_S_IO_MIN_NS"
puts $vf "filelist=$FILELIST"
puts $vf "file_count=[llength $FILES]"
close $vf
mark "constraints period=${PERIOD}ns uncertainty=$::STAGE_S_UNCERTAINTY_NS io_fraction=$::STAGE_S_IO_FRACTION io_min=$::STAGE_S_IO_MIN_NS"

# ---- synthesize ------------------------------------------------------------
# -mode out_of_context: no I/O buffers; ports stay ports.  Correct for a unit
# with no pinout, whose eventual boundary is intra-FPGA.
# -flatten_hierarchy none: keeps hierarchy so report_utilization -hierarchical
# and report_timing can NAME the submodule a finding belongs to.
mark "PHASE synth_design"
synth_design -mode out_of_context -top $UNIT -part $PART -flatten_hierarchy none

# ---- validate the objects the constraints assumed --------------------------
if {[llength [get_ports -quiet clk_i]] != 1} {
  puts "ERROR: expected exactly one clk_i port on $UNIT"
  exit 1
}
if {[llength [get_ports -quiet rst_i]] != 1} {
  puts "ERROR: expected exactly one rst_i port on $UNIT"
  exit 1
}
if {[llength [get_clocks -quiet -of_objects [get_ports clk_i]]] != 1} {
  puts "ERROR: expected exactly one clock constraint on $UNIT/clk_i"
  exit 1
}
# The two shape-(iii) ports must survive to the netlist boundary. If a future
# edit lets them be optimised away or renamed, this stops the run rather than
# quietly reporting timing for a design that no longer has the probes.
foreach probe {fc_init_done_o ok_to_issue_o} {
  if {[llength [get_ports -quiet $probe]] != 1} {
    puts "ERROR: shape-(iii) probe port $probe is absent from the synthesized boundary of $UNIT"
    exit 1
  }
}

# ---- reports ---------------------------------------------------------------
mark "PHASE reports"

# Setup AND hold in one summary -- the WHS/THS columns appear only with min_max.
report_timing_summary -delay_type min_max -max_paths 20 -input_pins \
                             -file $OUTDIR/timing_summary.rpt

# Worst setup paths, and -- new in this flow -- worst HOLD paths.
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
                             -file $OUTDIR/timing_setup_worst20.rpt
report_timing -delay_type min -max_paths 20 -nworst 20 -sort_by slack \
                             -file $OUTDIR/timing_hold_worst20.rpt

# The path-group split.  timing_reg2reg.rpt is the number that does NOT depend
# on the I/O-delay fraction; the other two do, and are labelled so in the
# report.  No timing claim without its constraint stated next to it.
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
              -from [all_registers] -to [all_registers] \
                             -file $OUTDIR/timing_reg2reg.rpt
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
              -from [all_inputs] \
                             -file $OUTDIR/timing_from_inputs.rpt
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
              -to [all_outputs] \
                             -file $OUTDIR/timing_to_outputs.rpt

report_utilization           -file $OUTDIR/utilization.rpt
report_utilization -hierarchical -hierarchical_depth 4 \
                             -file $OUTDIR/utilization_hier.rpt
report_clocks                -file $OUTDIR/clocks.rpt
report_clock_networks        -file $OUTDIR/clock_networks.rpt
report_methodology           -file $OUTDIR/methodology.rpt
check_timing -verbose        -file $OUTDIR/check_timing.rpt
report_drc -ruledecks {default} \
                             -file $OUTDIR/drc.rpt

# ---- netlist queries, not log greps ----------------------------------------
mark "PHASE netlist queries"
set latch_cells [get_cells -hier -quiet -filter {PRIMITIVE_SUBGROUP == LATCH}]
set lf [open $OUTDIR/latches_netlist.txt w]
puts $lf "unit: $UNIT"
puts $lf "latch primitives in the synthesized netlist: [llength $latch_cells]"
foreach c $latch_cells { puts $lf "  $c  ref=[get_property REF_NAME $c]" }
close $lf
mark "LATCH_COUNT [llength $latch_cells]"

# ---- machine-readable scalars for the report table -------------------------
# Phase E's table is assembled from these rather than from a human reading a
# .rpt, so a transcription slip cannot enter the record.
proc path_slack {args} {
  set p [get_timing_paths -quiet {*}$args]
  if {[llength $p] == 0} { return "n/a" }
  return [get_property SLACK [lindex $p 0]]
}
proc path_name {args} {
  set p [get_timing_paths -quiet {*}$args]
  if {[llength $p] == 0} { return "n/a" }
  set p [lindex $p 0]
  return "[get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
}

set sf [open $OUTDIR/summary.txt w]
puts $sf "unit=$UNIT"
puts $sf "period_ns=$PERIOD"
puts $sf "part=$PART"
puts $sf "vivado=[version -short]"
puts $sf "latches=[llength $latch_cells]"
puts $sf "wns_setup_ns=[path_slack -delay_type max -max_paths 1]"
puts $sf "wns_setup_path=[path_name -delay_type max -max_paths 1]"
puts $sf "whs_hold_ns=[path_slack -delay_type min -max_paths 1]"
puts $sf "whs_hold_path=[path_name -delay_type min -max_paths 1]"
puts $sf "wns_reg2reg_ns=[path_slack -delay_type max -max_paths 1 -from [all_registers] -to [all_registers]]"
puts $sf "wns_reg2reg_path=[path_name -delay_type max -max_paths 1 -from [all_registers] -to [all_registers]]"
puts $sf "whs_reg2reg_ns=[path_slack -delay_type min -max_paths 1 -from [all_registers] -to [all_registers]]"
puts $sf "whs_reg2reg_path=[path_name -delay_type min -max_paths 1 -from [all_registers] -to [all_registers]]"
puts $sf "wns_from_inputs_ns=[path_slack -delay_type max -max_paths 1 -from [all_inputs]]"
puts $sf "wns_to_outputs_ns=[path_slack -delay_type max -max_paths 1 -to [all_outputs]]"
close $sf
mark "SUMMARY written"

write_checkpoint -force $OUTDIR/$UNIT.dcp

mark "PHASE done"
exit 0
