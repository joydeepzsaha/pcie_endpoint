`timescale 1ns/1ps
module tlp_bar_decoder #(
    parameter int BAR_COUNT = 2,
    parameter logic [BAR_COUNT*64-1:0] BAR_BASE = '0,
    parameter logic [BAR_COUNT*64-1:0] BAR_MASK = {{(BAR_COUNT-1){64'd0}}, 64'hffff_ffff_ffff_f000},
    parameter logic [BAR_COUNT-1:0] BAR_ENABLE = {{(BAR_COUNT-1){1'b0}}, 1'b1}
) (
    input  logic [63:0] address_i,
    input  logic [12:0] length_bytes_i,
    input  logic        memory_enable_i,
    output logic        hit_o,
    output logic        overlap_o,
    output logic [((BAR_COUNT <= 1) ? 1 : $clog2(BAR_COUNT))-1:0] bar_o,
    output logic [63:0] offset_o
);

  integer index;
  logic [63:0] base;
  logic [63:0] mask;
  logic [64:0] end_address;
  logic start_match;
  logic end_match;
  integer match_count;

  always_comb begin
    hit_o    = 1'b0;
    overlap_o = 1'b0;
    bar_o    = '0;
    offset_o = '0;
    match_count = 0;
    end_address = {1'b0, address_i} +
                  (length_bytes_i == 0 ? 65'd0 : {52'd0, length_bytes_i} - 1'b1);
    for (index = 0; index < BAR_COUNT; index = index + 1) begin
      base = BAR_BASE[index*64 +: 64];
      mask = BAR_MASK[index*64 +: 64];
      start_match = (address_i & mask) == (base & mask);
      end_match = !end_address[64] && ((end_address[63:0] & mask) == (base & mask));
      if (memory_enable_i && BAR_ENABLE[index] && start_match && end_match) begin
        match_count = match_count + 1;
        if (!hit_o) begin
          hit_o    = 1'b1;
          bar_o    = index[((BAR_COUNT <= 1) ? 1 : $clog2(BAR_COUNT))-1:0];
          offset_o = address_i - base;
        end
      end
    end
    overlap_o = match_count > 1;
    if (overlap_o)
      hit_o = 1'b0;
  end

endmodule
