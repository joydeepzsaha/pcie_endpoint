`timescale 1ns/1ps
module tb_tlp_ecrc;
  logic clk_i = 0, rst_i, start, data_valid, finish;
  logic [31:0] data;
  logic [3:0] keep;
  logic [31:0] ecrc;
  logic ecrc_valid;
  tlp_ecrc dut(.clk_i(clk_i), .rst_i(rst_i), .start_i(start), .data_i(data),
      .keep_i(keep), .data_valid_i(data_valid), .finish_i(finish),
      .ecrc_o(ecrc), .ecrc_valid_o(ecrc_valid));
endmodule
