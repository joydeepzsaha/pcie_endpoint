`timescale 1ns/1ps
module tlp_ecrc
  import tlp_pkg::*;
(
    input  logic        clk_i,
    input  logic        rst_i,
    input  logic        start_i,
    input  logic [31:0] data_i,
    input  logic [3:0]  keep_i,
    input  logic        data_valid_i,
    input  logic        finish_i,
    output logic [31:0] ecrc_o,
    output logic        ecrc_valid_o
);

  logic [31:0] crc_r;
  logic [31:0] base_crc;
  logic [31:0] next_crc;

  always_comb begin
    base_crc = start_i ? 32'hffff_ffff : crc_r;
    next_crc = data_valid_i ? tlp_crc32_dw(base_crc, data_i, keep_i) : base_crc;
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      crc_r        <= 32'hffff_ffff;
      ecrc_o       <= '0;
      ecrc_valid_o <= 1'b0;
    end else begin
      if (start_i)
        ecrc_valid_o <= 1'b0;
      if (start_i || data_valid_i)
        crc_r <= next_crc;
      if (finish_i && data_valid_i) begin
        ecrc_o       <= ~next_crc;
        ecrc_valid_o <= 1'b1;
      end
    end
  end

endmodule
