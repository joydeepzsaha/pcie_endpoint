# ---------------------------------------------------------------------------
# par_ooc.tcl -- Out-of-context optimization, placement, and routing.
#
# Opens one checkpoint produced by s1_ooc.tcl and writes implementation
# reports plus a routed checkpoint. This is not a board-level bitstream flow.
#
# Usage:
#   vivado -mode batch -source synth/par_ooc.tcl \
#          -tclargs <unit> [repo_root] [synthesis_root] [output_root] [part]
# ---------------------------------------------------------------------------

if {[llength $argv] < 1} {
  puts "ERROR: usage: -tclargs <unit> \[repo_root\] \[synthesis_root\] \[output_root\] \[part\]"
  exit 1
}

set SCRIPT_DIR [file dirname [file normalize [info script]]]
set DEFAULT_REPO [file dirname $SCRIPT_DIR]

set UNIT [lindex $argv 0]
set REPO [expr {[llength $argv] > 1 ? [lindex $argv 1] : $DEFAULT_REPO}]
set SYNROOT [expr {[llength $argv] > 2 ? [lindex $argv 2] : "$REPO/build/vivado/syn"}]
set OUTROOT [expr {[llength $argv] > 3 ? [lindex $argv 3] : "$REPO/build/vivado/par"}]
set PART [expr {[llength $argv] > 4 ? [lindex $argv 4] : "xczu7ev-ffvc1156-2-e"}]

set INPUT_DCP $SYNROOT/$UNIT/$UNIT.dcp
set OUTDIR $OUTROOT/$UNIT

if {![file exists $INPUT_DCP]} {
  puts "ERROR: missing synthesis checkpoint $INPUT_DCP"
  exit 1
}
file mkdir $OUTDIR

proc mark {msg} {
  puts "===PAR=== $msg"
  flush stdout
}

mark "unit=$UNIT part=$PART input=$INPUT_DCP outdir=$OUTDIR"
mark "vivado=[version -short]"

mark "PHASE open_checkpoint"
open_checkpoint $INPUT_DCP

if {[llength [get_ports -quiet clk_i]] != 1} {
  puts "ERROR: expected exactly one clk_i port in $INPUT_DCP"
  exit 1
}
if {[llength [get_clocks -quiet -of_objects [get_ports clk_i]]] != 1} {
  puts "ERROR: expected exactly one clock constraint on $UNIT/clk_i"
  exit 1
}
if {$UNIT eq "endpoint"} {
  foreach port_name {pipe_rx_usr_clk_i pipe_tx_usr_clk_i} {
    if {[llength [get_ports -quiet $port_name]] != 1} {
      puts "ERROR: expected exactly one $port_name port in $INPUT_DCP"
      exit 1
    }
    if {[llength [get_clocks -quiet -of_objects [get_ports $port_name]]] != 1} {
      puts "ERROR: expected exactly one clock constraint on $UNIT/$port_name"
      exit 1
    }
  }
}

mark "PHASE opt_design"
opt_design

mark "PHASE place_design"
place_design

mark "PHASE phys_opt_design"
phys_opt_design

report_timing_summary -delay_type max -max_paths 20 -input_pins \
  -file $OUTDIR/timing_post_place.rpt

mark "PHASE route_design"
route_design

mark "PHASE reports"
report_route_status          -file $OUTDIR/route_status.rpt
report_timing_summary -delay_type max -max_paths 20 -input_pins \
                             -file $OUTDIR/timing_post_route.rpt
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
                             -file $OUTDIR/timing_worst20_post_route.rpt
report_utilization           -file $OUTDIR/utilization_post_route.rpt
report_utilization -hierarchical -hierarchical_depth 4 \
                             -file $OUTDIR/utilization_hier_post_route.rpt
report_clocks                -file $OUTDIR/clocks.rpt
report_clock_utilization     -file $OUTDIR/clock_utilization.rpt
report_methodology           -file $OUTDIR/methodology.rpt
report_drc -ruledecks {default} \
                             -file $OUTDIR/drc.rpt
check_timing -verbose        -file $OUTDIR/check_timing.rpt

mark "PHASE checkpoint"
write_checkpoint -force $OUTDIR/${UNIT}_routed.dcp

mark "PHASE done"
exit 0
