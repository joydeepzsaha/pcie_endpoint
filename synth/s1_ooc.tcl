# ---------------------------------------------------------------------------
# s1_ooc.tcl -- Stage S-1, out-of-context synthesis of one RC-side unit.
#
# Non-project batch flow. Reads one unit's ordered file list, loads the shared
# timing constraints before synthesis, synthesizes out-of-context, and writes
# every report to a per-unit directory OUTSIDE the repository.
#
# THIS SCRIPT CHANGES NO RTL AND WRITES NOTHING INTO THE REPO. Every artefact
# it produces lands in $OUTROOT/<unit>/ -- nothing generated is ever committed.
#
# Usage (Vivado must be available on PATH):
#
#   vivado -mode batch -nojournal -nolog -source synth/s1_ooc.tcl \
#          -tclargs <unit> [repo_root] [out_root] [part] [period_ns] \
#                   [uncertainty_ns] [input_delay_min_ns] \
#                   [input_delay_max_ns] [output_delay_min_ns] \
#                   [output_delay_max_ns]
#
#   <unit> is one of:  pcie_enum_top | pcie_rq_rc_top | endpoint
#
# ---------------------------------------------------------------------------
# THE CLOCK PERIOD IS A PLACEHOLDER.
#
# The default is 250 MHz (4.000 ns) on the unit's clk_i port. The shared
# constraints also apply clock uncertainty and input/output delays. No pin
# placement or clock-buffer site is specified; that remains dependent on the
# final GTH/clock architecture.
#
# Read timing results as directional until the parent-interface timing budgets
# and final clock architecture are known.
# ---------------------------------------------------------------------------

# ---- arguments -------------------------------------------------------------
if {[llength $argv] < 1} {
  puts "ERROR: usage: -tclargs <unit> \[repo_root\] \[out_root\] \[part\] \[period_ns\] \[uncertainty_ns\] \[input_delay_min_ns\] \[input_delay_max_ns\] \[output_delay_min_ns\] \[output_delay_max_ns\]"
  exit 1
}

set SCRIPT_DIR [file dirname [file normalize [info script]]]
set DEFAULT_REPO [file dirname $SCRIPT_DIR]

set UNIT [lindex $argv 0]
set REPO [expr {[llength $argv] > 1 ? [lindex $argv 1] : $DEFAULT_REPO}]
set OUTROOT [expr {[llength $argv] > 2 ? [lindex $argv 2] : "$REPO/build/vivado/syn"}]
set PART [expr {[llength $argv] > 3 ? [lindex $argv 3] : "xczu7ev-ffvc1156-2-e"}]
set PERIOD_OVERRIDE [expr {[llength $argv] > 4 ? [lindex $argv 4] : ""}]
set UNCERTAINTY_OVERRIDE [expr {[llength $argv] > 5 ? [lindex $argv 5] : ""}]
set INPUT_DELAY_MIN_OVERRIDE [expr {[llength $argv] > 6 ? [lindex $argv 6] : ""}]
set INPUT_DELAY_MAX_OVERRIDE [expr {[llength $argv] > 7 ? [lindex $argv 7] : ""}]
set OUTPUT_DELAY_MIN_OVERRIDE [expr {[llength $argv] > 8 ? [lindex $argv 8] : ""}]
set OUTPUT_DELAY_MAX_OVERRIDE [expr {[llength $argv] > 9 ? [lindex $argv 9] : ""}]
set CONSTRAINT_GENERATOR $REPO/synth/pcie_datalink_layer_constraints.tcl
set TOP $UNIT
set SYNTH_GENERICS {}

# ---- ordered RTL lists -----------------------------------------------------
# Package files must precede modules that import them.

set FILES(pcie_enum_top) {
  src/tlp/tlp_pkg.sv
  src/rc/pcie_rq_rc_pkg.sv
  src/rc/pcie_enum_pkg.sv
  src/rc/pcie_cfg_txn.sv
  src/rc/pcie_enum_scan.sv
  src/rc/pcie_enum_bar.sv
  src/rc/pcie_enum_bus.sv
  src/rc/pcie_enum_top.sv
}

set FILES(pcie_rq_rc_top) {
  src/tlp/tlp_pkg.sv
  src/tlp/tlp_ecrc.sv
  src/tlp/tlp_validator.sv
  src/tlp/tlp_classifier.sv
  src/tlp/tlp_bar_decoder.sv
  src/tlp/tlp_config_decoder.sv
  src/tlp/tlp_parser.sv
  src/tlp/tlp_payload_formatter.sv
  src/tlp/tlp_request_tracker.sv
  src/tlp/tlp_requester.sv
  src/tlp/tlp_completion_generator.sv
  src/tlp/tlp_control.sv
  src/tlp/tlp_generator.sv
  src/tlp/tlp_credit_manager.sv
  src/tlp/tlp_vc_buffer.sv
  src/tlp/tlp_layer.sv
  src/rc/pcie_rq_rc_pkg.sv
  src/rc/pcie_axis_dw_downsize.sv
  src/rc/pcie_axis_dw_upsize.sv
  src/rc/pcie_rq_if.sv
  src/rc/pcie_rc_if.sv
  src/rc/pcie_rq_rc_top.sv
}

# The endpoint has a larger, independently maintained dependency manifest and
# a three-clock Gen1 constraint set.  Keep the existing RC unit lists intact.
if {$UNIT eq "endpoint"} {
  set ENDPOINT_MANIFEST $REPO/synth/endpoint.tcl
  if {![file exists $ENDPOINT_MANIFEST]} {
    puts "ERROR: missing endpoint manifest $ENDPOINT_MANIFEST"
    exit 1
  }
  source $ENDPOINT_MANIFEST
  set FILES(endpoint) $ENDPOINT_FILES
  set TOP $ENDPOINT_TOP
  set SYNTH_GENERICS $ENDPOINT_GENERICS
  set CONSTRAINT_GENERATOR $REPO/synth/endpoint_constraints.tcl
}

if {![info exists FILES($UNIT)]} {
  puts "ERROR: unknown unit '$UNIT'. Known: [lsort [array names FILES]]"
  exit 1
}

set OUTDIR $OUTROOT/$UNIT
file mkdir $OUTDIR

# ---- progress markers ------------------------------------------------------
proc mark {msg} {
  puts "===S1=== $msg"
  flush stdout
}

mark "unit=$UNIT part=$PART outdir=$OUTDIR"
mark "vivado=[version -short]"

# ---- read RTL --------------------------------------------------------------
mark "PHASE read_verilog ([llength $FILES($UNIT)] files)"
foreach f $FILES($UNIT) {
  set p $REPO/$f
  if {![file exists $p]} {
    puts "ERROR: missing source file $p"
    exit 1
  }
  read_verilog -sv $p
}

# ---- timing constraints ----------------------------------------------------
if {![file exists $CONSTRAINT_GENERATOR]} {
  puts "ERROR: missing constraint generator $CONSTRAINT_GENERATOR"
  exit 1
}
source $CONSTRAINT_GENERATOR
if {[llength [info commands write_pcie_ooc_constraints]] != 1} {
  puts "ERROR: constraint generator did not define write_pcie_ooc_constraints"
  exit 1
}

foreach {variable override} [list \
    CLK_PERIOD_NS       $PERIOD_OVERRIDE \
    CLK_UNCERTAINTY_NS  $UNCERTAINTY_OVERRIDE \
    INPUT_DELAY_MIN_NS  $INPUT_DELAY_MIN_OVERRIDE \
    INPUT_DELAY_MAX_NS  $INPUT_DELAY_MAX_OVERRIDE \
    OUTPUT_DELAY_MIN_NS $OUTPUT_DELAY_MIN_OVERRIDE \
    OUTPUT_DELAY_MAX_NS $OUTPUT_DELAY_MAX_OVERRIDE] {
  if {$override ne ""} {
    set $variable $override
  }
}

set RUN_XDC $OUTDIR/${UNIT}_timing.xdc
write_pcie_ooc_constraints $RUN_XDC

set values_file [open $OUTDIR/constraint_values.txt w]
puts $values_file "clock_period_ns=$CLK_PERIOD_NS"
puts $values_file "clock_uncertainty_ns=$CLK_UNCERTAINTY_NS"
puts $values_file "input_delay_min_ns=$INPUT_DELAY_MIN_NS"
puts $values_file "input_delay_max_ns=$INPUT_DELAY_MAX_NS"
puts $values_file "output_delay_min_ns=$OUTPUT_DELAY_MIN_NS"
puts $values_file "output_delay_max_ns=$OUTPUT_DELAY_MAX_NS"
if {[info exists PIPE_RX_PERIOD_NS]} {
  puts $values_file "pipe_rx_period_ns=$PIPE_RX_PERIOD_NS"
}
if {[info exists PIPE_TX_PERIOD_NS]} {
  puts $values_file "pipe_tx_period_ns=$PIPE_TX_PERIOD_NS"
}
close $values_file

mark "constraints period=${CLK_PERIOD_NS}ns uncertainty=${CLK_UNCERTAINTY_NS}ns input=${INPUT_DELAY_MIN_NS}:${INPUT_DELAY_MAX_NS}ns output=${OUTPUT_DELAY_MIN_NS}:${OUTPUT_DELAY_MAX_NS}ns"
mark "PHASE read_xdc $RUN_XDC"
read_xdc $RUN_XDC

# ---- synthesize ------------------------------------------------------------
mark "PHASE synth_design"
set synth_args [list -mode out_of_context -top $TOP -part $PART \
                     -flatten_hierarchy none]
if {[llength $SYNTH_GENERICS] > 0} {
  lappend synth_args -generic $SYNTH_GENERICS
}
synth_design {*}$synth_args

# ---- validate required objects -------------------------------------------
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
if {$UNIT eq "endpoint"} {
  foreach port_name {pipe_rx_usr_clk_i pipe_tx_usr_clk_i} {
    if {[llength [get_ports -quiet $port_name]] != 1} {
      puts "ERROR: expected exactly one $port_name port on $TOP"
      exit 1
    }
    if {[llength [get_clocks -quiet -of_objects [get_ports $port_name]]] != 1} {
      puts "ERROR: expected exactly one clock constraint on $TOP/$port_name"
      exit 1
    }
  }
}

# ---- reports ---------------------------------------------------------------
mark "PHASE reports"
report_utilization           -file $OUTDIR/utilization.rpt
report_utilization -hierarchical -hierarchical_depth 4 \
                             -file $OUTDIR/utilization_hier.rpt
report_timing_summary -delay_type max -max_paths 20 -input_pins \
                             -file $OUTDIR/timing_summary.rpt
report_timing -delay_type max -max_paths 20 -nworst 20 -sort_by slack \
                             -file $OUTDIR/timing_worst20.rpt
report_methodology           -file $OUTDIR/methodology.rpt
report_clocks                -file $OUTDIR/clocks.rpt
check_timing -verbose        -file $OUTDIR/check_timing.rpt
report_drc -ruledecks {default} \
                             -file $OUTDIR/drc.rpt

# ---- netlist latch check ---------------------------------------------------
mark "PHASE latch query"
set latch_cells [get_cells -hier -quiet -filter {PRIMITIVE_SUBGROUP == LATCH}]
set lf [open $OUTDIR/latches_netlist.txt w]
puts $lf "unit: $UNIT"
puts $lf "latch primitives in the synthesized netlist: [llength $latch_cells]"
foreach c $latch_cells {
  puts $lf "  $c  ref=[get_property REF_NAME $c]"
}
close $lf
mark "LATCH_COUNT [llength $latch_cells]"

# ---- checkpoint ------------------------------------------------------------
write_checkpoint -force $OUTDIR/$UNIT.dcp

mark "PHASE done"
exit 0
