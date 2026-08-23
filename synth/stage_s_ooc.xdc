# ---------------------------------------------------------------------------
# stage_s_ooc.xdc -- shared out-of-context timing constraints for the two
# RC-side TL+DLL stacked tops: pcie_rc_dl_top and pcie_enum_dl_top.
#
# READ BEFORE synth_design so synthesis is timing-driven.  See
# synth/stage_s_ooc.tcl, which sets every $::STAGE_S_* global below, validates
# it, and echoes the resolved values into the run's constraint_values.txt.
#
# ---------------------------------------------------------------------------
# WHAT AN XDC MAY CONTAIN
#
# Vivado evaluates an XDC as Tcl but rejects control flow: `if` and `puts` in
# an XDC raise "[Designutils 20-1307] Command '...' is not supported in the xdc
# constraint file" (measured, 2023.2).  Variable substitution and `expr` are
# accepted.  So every default, every validation and every message lives in the
# driver Tcl; this file is constraints only.  That split is deliberate -- it
# keeps this file readable as the authored statement of what is constrained.
#
# ---------------------------------------------------------------------------
# THE CLOCK, AND ITS BASIS
#
# $::STAGE_S_PERIOD_NS is 8.000 ns (125 MHz) for the primary corner and
# 16.000 ns (62.5 MHz) for the relaxed corner.  The basis is a datapath
# computation, not a placeholder:
#
#   Gen1 x1 is 2.5 GT/s.  With 8b/10b that is 250 MB/s of payload.  The TL<->DLL
#   seam in both units is fixed at 32 bits (pcie_rc_dl_top.sv:170), so holding
#   line rate needs 250 MB/s / 4 B = 62.5 MHz.  That is the FLOOR, and it is the
#   relaxed corner.  125 MHz is one PIPE-natural step above it and is the
#   primary corner: it leaves 2x headroom for the eventual PHY-interface
#   clocking and for the fact that neither unit sustains one beat per cycle
#   through framing, LCRC and credit arbitration.
#
# The retired 250 MHz (4.000 ns) target is NOT used here.  Its own header at
# 7652b92 conceded it was "a shape, not a requirement" -- it came from Gen1's
# 250 MHz 8-bit symbol clock, which is not this datapath's width.  Every timing
# number from S-1/S-2 was taken at 4.000 ns on a netlist with no DLL in it; see
# ~/pcie_docs/evidence/stage-s/RECON_STAGE_S.md D2.
#
# ---------------------------------------------------------------------------
# CLOCK UNCERTAINTY: ABSOLUTE, NOT A FRACTION
#
# 0.100 ns, held constant across BOTH corners.  Clock uncertainty at this stage
# models period jitter on an MMCM-derived clock, which is a physical quantity in
# picoseconds -- it does not shrink because the period grew.  Scaling it with
# the period would silently hand the relaxed corner margin it has not earned.
#
# The value is inherited from synth/pcie_datalink_layer_constraints.tcl:11,
# where it carried no stated basis.  Stated here: it is a JITTER ALLOWANCE OF
# THE RIGHT ORDER (MMCM output period jitter on this family is order-100 ps),
# not a datasheet extract, and out-of-context there is no clock tree whose skew
# could be added to it.  If the final clock turns out to be GT-recovered rather
# than MMCM-derived, this number must be re-derived, not reused.
#
# ---------------------------------------------------------------------------
# I/O DELAY: A FRACTION OF THE PERIOD, DELIBERATELY
#
# max = 0.30 * period on inputs and 0.30 * period on outputs.
#
# WHY A FRACTION.  The inherited flow used absolute nanoseconds -- 2.752 in and
# 3.000 out against a 6.500 ns clock, i.e. 42% and 46% of the period.  Carried
# unchanged to 16.000 ns those same nanoseconds become 17% and 19%: the
# constraint would loosen as the clock relaxed, and the two corners would not be
# comparable.  Expressing the budget as a share of the period makes the relaxed
# corner a genuinely relaxed version of the same constraint.
#
# WHY 0.30.  Both units are out-of-context blocks whose eventual neighbours
# (PHY/LTSSM below, an application above) are on the same die and not yet
# designed.  30% out and 30% in is the conventional split for an unspecified
# registered neighbour, leaving 40% of the period for this unit's own boundary
# logic.  It is LOOSER than the inherited 42%/46%, and that is stated rather
# than hidden: see the three path-group reports the driver writes
# (timing_reg2reg / timing_from_inputs / timing_to_outputs), which separate the
# register-to-register number -- independent of this fraction entirely -- from
# the two that depend on it.  Any claim about whether the DESIGN meets the clock
# must be made against the reg2reg number.
#
# WHY min = 0.000.  The pessimistic hold assumption: a neighbour whose
# clock-to-out is effectively zero.  A non-zero min would manufacture hold
# margin we have not earned, and hold is the thing this rung is measuring for
# the first time (RECON_STAGE_S.md D3: neither the synthesis nor the
# place-and-route flow has ever run a min-delay report on this design).
#
# ---------------------------------------------------------------------------
# rst_i IS TIMED.  It drives synchronous reset logic throughout both cones, so
# it belongs in the input-delay collection.  Only clk_i is excluded.
#
# THE TWO SHAPE-(iii) PORTS.  fc_init_done_o and ok_to_issue_o
# (pcie_rc_dl_top.sv:89-90, pcie_enum_dl_top.sv:49-50) are ordinary OOC outputs
# and are collected by the DIRECTION == OUT filter below with no special case.
# They exist so an integrator can learn when it is safe to issue without
# reaching hierarchically into fc_init_sticky_r, and they are future ILA / LED
# probe candidates.  DO NOT "simplify" this flow by excluding them from the
# output-delay collection or by letting them be optimised away: a probe that is
# not constrained is a probe whose timing nobody has checked.
# ---------------------------------------------------------------------------

create_clock -name clk_i -period $::STAGE_S_PERIOD_NS [get_ports clk_i]

set_clock_uncertainty $::STAGE_S_UNCERTAINTY_NS [get_clocks clk_i]

set_input_delay -clock [get_clocks clk_i] \
    -max [expr {$::STAGE_S_IO_FRACTION * $::STAGE_S_PERIOD_NS}] \
    [get_ports -quiet -filter {DIRECTION == IN && NAME != clk_i}]
set_input_delay -clock [get_clocks clk_i] \
    -min $::STAGE_S_IO_MIN_NS \
    [get_ports -quiet -filter {DIRECTION == IN && NAME != clk_i}]

set_output_delay -clock [get_clocks clk_i] \
    -max [expr {$::STAGE_S_IO_FRACTION * $::STAGE_S_PERIOD_NS}] \
    [get_ports -quiet -filter {DIRECTION == OUT}]
set_output_delay -clock [get_clocks clk_i] \
    -min $::STAGE_S_IO_MIN_NS \
    [get_ports -quiet -filter {DIRECTION == OUT}]
