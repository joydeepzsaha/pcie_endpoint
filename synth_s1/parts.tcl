foreach p [lsort [get_parts xczu7ev*]] {
  puts "PART $p  LUT=[get_property LUT_ELEMENTS $p] FF=[get_property FLIPFLOPS $p] BRAM=[get_property BLOCK_RAMS $p] URAM=[get_property ULTRA_RAMS $p] DSP=[get_property DSP $p] SPEED=[get_property SPEED $p]"
}
