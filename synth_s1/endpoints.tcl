# Scratch analysis (NOT part of the repo flow): re-open a checkpoint and list
# the distinct failing endpoints, grouped by owning submodule.
set UNIT [lindex $argv 0]
open_checkpoint /home/kourosh/synth_s1/$UNIT/$UNIT.dcp
create_clock -name clk_placeholder -period 4.000 [get_ports clk_i]
set paths [get_timing_paths -max_paths 400 -nworst 1 -slack_lesser_than 0 -unique_pins]
puts "===EP=== unit=$UNIT failing_paths=[llength $paths]"
array set bymod {}
foreach p $paths {
  set d [get_property ENDPOINT_PIN $p]
  set s [get_property STARTPOINT_PIN $p]
  set sl [get_property SLACK $p]
  # owning submodule = first hierarchy level of the endpoint
  set mod [lindex [split $d /] 0]
  if {[llength [split $d /]] > 2} { set mod [join [lrange [split $d /] 0 1] /] }
  if {![info exists bymod($mod)]} { set bymod($mod) [list 0 999] }
  lassign $bymod($mod) n w
  set bymod($mod) [list [expr {$n+1}] [expr {$sl < $w ? $sl : $w}]]
}
foreach m [lsort [array names bymod]] {
  lassign $bymod($m) n w
  puts "===EP=== $UNIT  endpoints=$n  worst_slack=$w  module=$m"
}
puts "===EP=== top5 distinct:"
foreach p [lrange $paths 0 4] {
  puts "===EP===   slack=[get_property SLACK $p]  [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
}
exit 0
