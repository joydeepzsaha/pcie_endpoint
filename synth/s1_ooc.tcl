# ---------------------------------------------------------------------------
# s1_ooc.tcl -- Stage S-1, out-of-context synthesis of one RC-side unit.
#
# Non-project batch flow. Reads one unit's ordered file list, applies ONE
# virtual clock, synthesizes out-of-context, and writes every report to a
# per-unit directory OUTSIDE the repository.
#
# THIS SCRIPT CHANGES NO RTL AND WRITES NOTHING INTO THE REPO. Every artefact
# it produces lands in $OUTROOT/<unit>/ -- nothing generated is ever committed.
#
# Usage (from a shell that has sourced /home/kourosh/tools/vivado_env.sh, and
# ONLY such a shell -- never the conda pcie/Verilator environment):
#
#   vivado -mode batch -nojournal -nolog -source synth/s1_ooc.tcl \
#          -tclargs <unit> [repo_root] [out_root] [part] [period_ns]
#
#   <unit> is one of:  pcie_enum_top | pcie_rq_rc_top
#
# ---------------------------------------------------------------------------
# THE CLOCK IS A PLACEHOLDER.
#
# One create_clock at 250 MHz (4.000 ns) on the unit's clk_i port, and nothing
# else. No XDC, no pin placement, no set_input_delay / set_output_delay, no
# clocking architecture -- all of that is blocked on the GTH-attach decision,
# which is not this brief's to make.
#
# 250 MHz is a Gen1-era stand-in (Gen1 x1 at 2.5 GT/s is 250 MHz of 8-bit
# symbol time; the TL here is 32 bits wide, so this is a shape, not a
# requirement). CONSEQUENCE: with no I/O delays written, only register-to-
# register paths are timed. Every input-to-register and register-to-output
# path is unconstrained and cannot appear in WNS. Read every timing number
# this script produces as DIRECTIONAL ONLY.
# ---------------------------------------------------------------------------

# ---- arguments -------------------------------------------------------------
if {[llength $argv] < 1} {
  puts "ERROR: usage: -tclargs <unit> \[repo_root\] \[out_root\] \[part\] \[period_ns\]"
  exit 1
}

set UNIT   [lindex $argv 0]
set REPO   [expr {[llength $argv] > 1 ? [lindex $argv 1] : "/home/kourosh/pcie_endpoint"}]
set OUTROOT [expr {[llength $argv] > 2 ? [lindex $argv 2] : "/home/kourosh/synth_s1"}]
# xczu7ev-ffvc1156-2-e: free-tier stand-in for the ZCU102's ZU9EG
# (xczu9eg-ffvb1156-2-e -- same family, same speed/temperature grade, not
# visible under ML Standard). A placeholder for area and timing character,
# NOT a board commitment.
set PART   [expr {[llength $argv] > 3 ? [lindex $argv 3] : "xczu7ev-ffvc1156-2-e"}]
set PERIOD [expr {[llength $argv] > 4 ? [lindex $argv 4] : 4.000}]

# ---- the file lists --------------------------------------------------------
# Ordered per the FuseSoC .core filesets (src/tlp/tlp_core.core and
# src/rc/rc_core.core), RTL only -- no tb/, no cocotb glue, no lint waivers --
# with the three packages hoisted to the front.
#
# The hoist is REQUIRED, not cosmetic: pcie_rq_rc_pkg references tlp_pkg::, so
# tlp_pkg must compile first even for pcie_enum_top, which contains no TL.
# pcie_enum_pkg imports nothing.

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

if {![info exists FILES($UNIT)]} {
  puts "ERROR: unknown unit '$UNIT'. Known: [lsort [array names FILES]]"
  exit 1
}

set OUTDIR $OUTROOT/$UNIT
file mkdir $OUTDIR

# ---- progress markers ------------------------------------------------------
# Vivado's own log is written by the -log switch on the caller; these markers
# make the phase boundaries greppable regardless of how the log is captured.
proc mark {msg} {
  puts "===S1=== $msg"
  flush stdout
}

mark "unit=$UNIT part=$PART period=${PERIOD}ns outdir=$OUTDIR"
mark "vivado=[version -short]"

# ---- 1. read -------------------------------------------------------------
mark "PHASE read_verilog ([llength $FILES($UNIT)] files)"
foreach f $FILES($UNIT) {
  set p $REPO/$f
  if {![file exists $p]} {
    puts "ERROR: missing source file $p"
    exit 1
  }
  read_verilog -sv $p
}

# ---- 2. synthesize -------------------------------------------------------
# -mode out_of_context: no I/O buffers inserted, ports stay as ports. Correct
# for a unit that is not the whole device and has no pinout.
# -flatten_hierarchy none: keeps the hierarchy intact so that
# report_utilization -hierarchical and report_timing can NAME the submodule a
# finding belongs to. Without it every path reports against the top and the
# per-submodule area table in the findings doc is not derivable.
mark "PHASE synth_design"
synth_design -mode out_of_context -top $UNIT -part $PART -flatten_hierarchy none

# ---- 3. the one virtual clock --------------------------------------------
# Applied AFTER synth_design so it constrains the elaborated netlist's clock
# port. See the placeholder warning in the header.
mark "PHASE create_clock 250MHz placeholder"
if {[llength [get_ports -quiet clk_i]] == 0} {
  puts "ERROR: no clk_i port on $UNIT -- the clock port name must be re-derived"
  exit 1
}
create_clock -name clk_placeholder -period $PERIOD [get_ports clk_i]

# ---- 4. reports ----------------------------------------------------------
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

# The DRC catches structural problems that neither utilization nor timing
# shows -- unconnected pins, undriven nets, multi-driven nets.
report_drc -ruledecks {default} -file $OUTDIR/drc.rpt

# ---- 5. latches, from the NETLIST rather than from the log ----------------
# The brief asks for a log grep, and the driver does that. This is the stronger
# form of the same question: ask the elaborated netlist what latch primitives
# it actually contains. A log grep can miss a latch Vivado inferred quietly;
# this cannot.
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

# ---- 6. checkpoint --------------------------------------------------------
# So a later brief can re-open this netlist without re-running synthesis.
# Lands outside the repo with everything else.
write_checkpoint -force $OUTDIR/$UNIT.dcp

mark "PHASE done"
exit 0
