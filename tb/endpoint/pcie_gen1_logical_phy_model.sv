`timescale 1ns/1ps

// Verification-only PCIe Gen1 logical-PHY model.  It models byte striping,
// the Gen1 scrambler, and 8b/10b coding, but intentionally does not model a
// SERDES, PIPE, LTSSM, ordered sets, lane deskew, or lane reversal.
module pcie_gen1_logical_phy_model #(
    parameter int LANE_COUNT = 1,
    parameter int USER_WIDTH = 3
) (
    input  logic                         clk_i,
    input  logic                         rst_i,

    input  logic [31:0]                  s_axis_tdata,
    input  logic [3:0]                   s_axis_tkeep,
    input  logic                         s_axis_tvalid,
    input  logic                         s_axis_tlast,
    input  logic [USER_WIDTH-1:0]        s_axis_tuser,
    output logic                         s_axis_tready,

    output logic [LANE_COUNT*10-1:0]     tx_symbol_data_o,
    output logic [LANE_COUNT-1:0]        tx_symbol_keep_o,
    output logic                         tx_symbol_valid_o,
    output logic                         tx_symbol_sop_o,
    output logic                         tx_symbol_eop_o,
    output logic [USER_WIDTH-1:0]        tx_symbol_user_o,
    input  logic                         tx_symbol_ready_i,

    input  logic [LANE_COUNT*10-1:0]     rx_symbol_data_i,
    input  logic [LANE_COUNT-1:0]        rx_symbol_keep_i,
    input  logic                         rx_symbol_valid_i,
    input  logic                         rx_symbol_sop_i,
    input  logic                         rx_symbol_eop_i,
    input  logic [USER_WIDTH-1:0]        rx_symbol_user_i,
    output logic                         rx_symbol_ready_o,

    output logic [31:0]                  m_axis_tdata,
    output logic [3:0]                   m_axis_tkeep,
    output logic                         m_axis_tvalid,
    output logic                         m_axis_tlast,
    output logic [USER_WIDTH-1:0]        m_axis_tuser,
    input  logic                         m_axis_tready,

    output logic [63:0]                  tx_symbol_count_o,
    output logic [63:0]                  tx_payload_byte_count_o,
    output logic [63:0]                  tx_active_cycle_count_o,
    output logic [63:0]                  rx_symbol_count_o,
    output logic [63:0]                  rx_payload_byte_count_o,
    output logic [63:0]                  rx_active_cycle_count_o,
    output logic [LANE_COUNT-1:0]        rx_code_error_o,
    output logic [LANE_COUNT-1:0]        rx_disparity_error_o
);

  // x1 and x4 are mutually exclusive elaboration branches.  Each branch
  // completely assigns its combinational outputs, but some Verilator builds
  // conservatively report latches while flattening the parameterized packed
  // lane arrays.  Scope the waiver to this simulation-only logical-PHY model.
  /* verilator lint_off LATCH */

  logic [15:0] tx_lfsr_r [0:LANE_COUNT-1];
  logic [15:0] rx_lfsr_r [0:LANE_COUNT-1];
  wire  [15:0] tx_lfsr_next [0:LANE_COUNT-1];
  wire  [15:0] rx_lfsr_next [0:LANE_COUNT-1];
  logic [LANE_COUNT-1:0] tx_disparity_r;
  logic [LANE_COUNT-1:0] rx_disparity_r;

  logic [LANE_COUNT-1:0][7:0] tx_plain_byte;
  wire  [LANE_COUNT-1:0][7:0] tx_scrambled_byte;
  wire  [LANE_COUNT-1:0][8:0] tx_encoder_data;
  wire  [LANE_COUNT-1:0][9:0] tx_encoded_data;
  wire  [LANE_COUNT-1:0]      tx_encoded_disparity;

  wire  [LANE_COUNT-1:0][8:0] rx_decoded_data;
  wire  [LANE_COUNT-1:0]      rx_decoded_disparity;
  wire  [LANE_COUNT-1:0]      rx_decode_code_error;
  wire  [LANE_COUNT-1:0]      rx_decode_disparity_error;
  wire  [LANE_COUNT-1:0][7:0] rx_plain_byte;

  function automatic logic [7:0] scramble_mask(input logic [15:0] state);
    logic [15:0] reversed;
    begin
      for (int bit_index = 0; bit_index < 16; bit_index++)
        reversed[bit_index] = state[15-bit_index];
      return reversed[7:0];
    end
  endfunction

  function automatic logic [2:0] last_keep_index(input logic [3:0] keep);
    begin
      if (keep[3]) return 3;
      if (keep[2]) return 2;
      if (keep[1]) return 1;
      return 0;
    end
  endfunction

  function automatic logic [2:0] keep_count(input logic [3:0] keep);
    return keep[0] + keep[1] + keep[2] + keep[3];
  endfunction

  initial begin
    if (!(LANE_COUNT == 1 || LANE_COUNT == 4))
      $error("pcie_gen1_logical_phy_model supports LANE_COUNT=1 or 4");
  end

  for (genvar lane = 0; lane < LANE_COUNT; lane++) begin : codec
    byte_scramble tx_lfsr_step (
        .disable_scrambling(1'b0),
        .lfsr_q(tx_lfsr_r[lane]),
        .lfsr_out(tx_lfsr_next[lane])
    );
    byte_scramble rx_lfsr_step (
        .disable_scrambling(1'b0),
        .lfsr_q(rx_lfsr_r[lane]),
        .lfsr_out(rx_lfsr_next[lane])
    );
    encode_8b10b tx_encoder (
        .datain(tx_encoder_data[lane]),
        .dispin(tx_disparity_r[lane]),
        .dataout(tx_encoded_data[lane]),
        .dispout(tx_encoded_disparity[lane])
    );
    decode_8b10b rx_decoder (
        .datain(rx_symbol_data_i[lane*10 +: 10]),
        .dispin(rx_disparity_r[lane]),
        .dataout(rx_decoded_data[lane]),
        .dispout(rx_decoded_disparity[lane]),
        .code_err(rx_decode_code_error[lane]),
        .disp_err(rx_decode_disparity_error[lane])
    );

    assign tx_scrambled_byte[lane] =
        tx_plain_byte[lane] ^ scramble_mask(tx_lfsr_r[lane]);
    assign tx_encoder_data[lane] = {1'b0, tx_scrambled_byte[lane]};
    assign tx_symbol_data_o[lane*10 +: 10] = tx_encoded_data[lane];
    assign rx_plain_byte[lane] =
        rx_decoded_data[lane][7:0] ^ scramble_mask(rx_lfsr_r[lane]);
  end

  generate
    if (LANE_COUNT == 4) begin : x4
      logic tx_frame_active_r;

      always_comb begin
        s_axis_tready = tx_symbol_ready_i;
        tx_symbol_valid_o = s_axis_tvalid;
        tx_symbol_keep_o = s_axis_tkeep;
        tx_symbol_sop_o = s_axis_tvalid && !tx_frame_active_r;
        tx_symbol_eop_o = s_axis_tvalid && s_axis_tlast;
        tx_symbol_user_o = s_axis_tuser;
        for (int lane = 0; lane < 4; lane++)
          tx_plain_byte[lane] = s_axis_tdata[lane*8 +: 8];

        rx_symbol_ready_o = m_axis_tready;
        m_axis_tdata = '0;
        m_axis_tkeep = rx_symbol_keep_i;
        m_axis_tvalid = rx_symbol_valid_i;
        m_axis_tlast = rx_symbol_eop_i;
        m_axis_tuser = rx_symbol_user_i;
        for (int lane = 0; lane < 4; lane++)
          m_axis_tdata[lane*8 +: 8] = rx_plain_byte[lane];
      end

      always_ff @(posedge clk_i) begin
        if (rst_i) begin
          tx_frame_active_r <= 1'b0;
          tx_disparity_r <= '0;
          rx_disparity_r <= '0;
          tx_symbol_count_o <= '0;
          tx_payload_byte_count_o <= '0;
          tx_active_cycle_count_o <= '0;
          rx_symbol_count_o <= '0;
          rx_payload_byte_count_o <= '0;
          rx_active_cycle_count_o <= '0;
          rx_code_error_o <= '0;
          rx_disparity_error_o <= '0;
          for (int lane = 0; lane < 4; lane++) begin
            tx_lfsr_r[lane] <= 16'hffff;
            rx_lfsr_r[lane] <= 16'hffff;
          end
        end else begin
          if (tx_symbol_valid_o && tx_symbol_ready_i) begin
            tx_active_cycle_count_o <= tx_active_cycle_count_o + 1'b1;
            tx_symbol_count_o <= tx_symbol_count_o + keep_count(s_axis_tkeep);
            tx_payload_byte_count_o <= tx_payload_byte_count_o + keep_count(s_axis_tkeep);
            tx_frame_active_r <= !s_axis_tlast;
            for (int lane = 0; lane < 4; lane++) begin
              if (s_axis_tkeep[lane]) begin
                tx_lfsr_r[lane] <= tx_lfsr_next[lane];
                tx_disparity_r[lane] <= tx_encoded_disparity[lane];
              end
            end
          end
          if (rx_symbol_valid_i && rx_symbol_ready_o) begin
            rx_active_cycle_count_o <= rx_active_cycle_count_o + 1'b1;
            rx_symbol_count_o <= rx_symbol_count_o + keep_count(rx_symbol_keep_i);
            rx_payload_byte_count_o <= rx_payload_byte_count_o + keep_count(rx_symbol_keep_i);
            for (int lane = 0; lane < 4; lane++) begin
              if (rx_symbol_keep_i[lane]) begin
                rx_lfsr_r[lane] <= rx_lfsr_next[lane];
                rx_disparity_r[lane] <= rx_decoded_disparity[lane];
                rx_code_error_o[lane] <=
                    rx_code_error_o[lane] | rx_decode_code_error[lane];
                rx_disparity_error_o[lane] <=
                    rx_disparity_error_o[lane] | rx_decode_disparity_error[lane];
              end
            end
          end
        end
      end
    end else begin : x1
      logic [31:0] tx_buffer_data_r;
      logic [3:0] tx_buffer_keep_r;
      logic tx_buffer_last_r;
      logic [USER_WIDTH-1:0] tx_buffer_user_r;
      logic [2:0] tx_byte_index_r;
      logic tx_buffer_valid_r;
      logic tx_frame_active_r;
      logic tx_current_last;

      logic [31:0] rx_assembly_data_r;
      logic [3:0] rx_assembly_keep_r;
      logic [2:0] rx_byte_index_r;
      logic [31:0] rx_completed_data;
      logic [3:0] rx_completed_keep;
      logic [31:0] rx_output_data_r;
      logic [3:0] rx_output_keep_r;
      logic rx_output_valid_r;
      logic rx_output_last_r;
      logic [USER_WIDTH-1:0] rx_output_user_r;

      always_comb begin
        tx_current_last = tx_byte_index_r == last_keep_index(tx_buffer_keep_r);
        s_axis_tready = !tx_buffer_valid_r ||
                        (tx_symbol_ready_i && tx_current_last);
        tx_symbol_valid_o = tx_buffer_valid_r;
        tx_symbol_keep_o = tx_buffer_valid_r;
        tx_symbol_sop_o = tx_buffer_valid_r && !tx_frame_active_r;
        tx_symbol_eop_o = tx_buffer_valid_r && tx_buffer_last_r && tx_current_last;
        tx_symbol_user_o = tx_buffer_user_r;
        tx_plain_byte[0] = tx_buffer_data_r[tx_byte_index_r*8 +: 8];

        rx_symbol_ready_o = !rx_output_valid_r || m_axis_tready;
        rx_completed_data = rx_assembly_data_r;
        rx_completed_keep = rx_assembly_keep_r;
        rx_completed_data[rx_byte_index_r*8 +: 8] = rx_plain_byte[0];
        rx_completed_keep[rx_byte_index_r] = 1'b1;
        m_axis_tdata = rx_output_data_r;
        m_axis_tkeep = rx_output_keep_r;
        m_axis_tvalid = rx_output_valid_r;
        m_axis_tlast = rx_output_last_r;
        m_axis_tuser = rx_output_user_r;
      end

      always_ff @(posedge clk_i) begin
        if (rst_i) begin
          tx_buffer_data_r <= '0;
          tx_buffer_keep_r <= '0;
          tx_buffer_last_r <= 1'b0;
          tx_buffer_user_r <= '0;
          tx_byte_index_r <= '0;
          tx_buffer_valid_r <= 1'b0;
          tx_frame_active_r <= 1'b0;
          rx_assembly_data_r <= '0;
          rx_assembly_keep_r <= '0;
          rx_byte_index_r <= '0;
          rx_output_data_r <= '0;
          rx_output_keep_r <= '0;
          rx_output_valid_r <= 1'b0;
          rx_output_last_r <= 1'b0;
          rx_output_user_r <= '0;
          tx_lfsr_r[0] <= 16'hffff;
          rx_lfsr_r[0] <= 16'hffff;
          tx_disparity_r <= '0;
          rx_disparity_r <= '0;
          tx_symbol_count_o <= '0;
          tx_payload_byte_count_o <= '0;
          tx_active_cycle_count_o <= '0;
          rx_symbol_count_o <= '0;
          rx_payload_byte_count_o <= '0;
          rx_active_cycle_count_o <= '0;
          rx_code_error_o <= '0;
          rx_disparity_error_o <= '0;
        end else begin
          if (tx_symbol_valid_o && tx_symbol_ready_i) begin
            tx_lfsr_r[0] <= tx_lfsr_next[0];
            tx_disparity_r[0] <= tx_encoded_disparity[0];
            tx_symbol_count_o <= tx_symbol_count_o + 1'b1;
            tx_payload_byte_count_o <= tx_payload_byte_count_o + 1'b1;
            tx_active_cycle_count_o <= tx_active_cycle_count_o + 1'b1;
            if (tx_symbol_eop_o)
              tx_frame_active_r <= 1'b0;
            else
              tx_frame_active_r <= 1'b1;

            if (!tx_current_last) begin
              tx_byte_index_r <= tx_byte_index_r + 1'b1;
            end else if (s_axis_tvalid) begin
              tx_buffer_data_r <= s_axis_tdata;
              tx_buffer_keep_r <= s_axis_tkeep;
              tx_buffer_last_r <= s_axis_tlast;
              tx_buffer_user_r <= s_axis_tuser;
              tx_byte_index_r <= '0;
              tx_buffer_valid_r <= 1'b1;
            end else begin
              tx_buffer_valid_r <= 1'b0;
              tx_byte_index_r <= '0;
            end
          end else if (!tx_buffer_valid_r && s_axis_tvalid && s_axis_tready) begin
            tx_buffer_data_r <= s_axis_tdata;
            tx_buffer_keep_r <= s_axis_tkeep;
            tx_buffer_last_r <= s_axis_tlast;
            tx_buffer_user_r <= s_axis_tuser;
            tx_byte_index_r <= '0;
            tx_buffer_valid_r <= 1'b1;
          end

          if (rx_output_valid_r && m_axis_tready)
            rx_output_valid_r <= 1'b0;

          if (rx_symbol_valid_i && rx_symbol_ready_o) begin
            rx_lfsr_r[0] <= rx_lfsr_next[0];
            rx_disparity_r[0] <= rx_decoded_disparity[0];
            rx_code_error_o[0] <= rx_code_error_o[0] | rx_decode_code_error[0];
            rx_disparity_error_o[0] <=
                rx_disparity_error_o[0] | rx_decode_disparity_error[0];
            rx_symbol_count_o <= rx_symbol_count_o + 1'b1;
            rx_payload_byte_count_o <= rx_payload_byte_count_o + 1'b1;
            rx_active_cycle_count_o <= rx_active_cycle_count_o + 1'b1;
            if (rx_symbol_eop_i || rx_byte_index_r == 3) begin
              rx_output_data_r <= rx_completed_data;
              rx_output_keep_r <= rx_completed_keep;
              rx_output_valid_r <= 1'b1;
              rx_output_last_r <= rx_symbol_eop_i;
              rx_output_user_r <= rx_symbol_user_i;
              rx_assembly_data_r <= '0;
              rx_assembly_keep_r <= '0;
              rx_byte_index_r <= '0;
            end else begin
              rx_assembly_data_r <= rx_completed_data;
              rx_assembly_keep_r <= rx_completed_keep;
              rx_byte_index_r <= rx_byte_index_r + 1'b1;
            end
          end
        end
      end
    end
  endgenerate

  /* verilator lint_on LATCH */
endmodule
