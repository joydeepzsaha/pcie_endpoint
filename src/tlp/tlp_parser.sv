`timescale 1ns/1ps
module tlp_parser
  import tlp_pkg::*;
#(
    parameter int DATA_WIDTH = 32,
    parameter int KEEP_WIDTH = DATA_WIDTH / 8,
    parameter int USER_WIDTH = 3,
    // Set when each AXI byte lane carries the corresponding PCIe wire byte.
    // DW0 already uses lane-oriented fields; later header DWORDs require a
    // byte reversal before their conventional bit fields are decoded.
    parameter bit PCIE_WIRE_ORDER = 1'b0
) (
    input  logic                  clk_i,
    input  logic                  rst_i,
    input  logic [DATA_WIDTH-1:0] s_axis_tdata,
    input  logic [KEEP_WIDTH-1:0] s_axis_tkeep,
    input  logic                  s_axis_tvalid,
    input  logic                  s_axis_tlast,
    input  logic [USER_WIDTH-1:0] s_axis_tuser,
    output logic                  s_axis_tready,
    output tlp_header_t           header_o,
    output logic                  header_valid_o,
    input  logic                  header_ready_i,
    output logic [DATA_WIDTH-1:0] payload_tdata_o,
    output logic [KEEP_WIDTH-1:0] payload_tkeep_o,
    output logic                  payload_tvalid_o,
    output logic                  payload_tlast_o,
    input  logic                  payload_tready_i,
    output logic                  malformed_o,
    output logic                  error_valid_o,
    output tlp_error_e            error_code_o,
    output logic                  ecrc_error_o
);

  typedef enum logic [3:0] {
    RX_FIRST, RX_DW0, RX_DW1, RX_DW2, RX_DW3, RX_VALIDATE,
    RX_PAYLOAD, RX_ECRC, RX_HEADER, RX_REPLAY, RX_DROP
  } rx_state_e;
  rx_state_e state_r;
  tlp_header_t header_r;
  logic [31:0] payload_data_mem [0:1023];
  logic [3:0] payload_keep_mem [0:1023];
  logic [10:0] receive_count_r, replay_count_r;
  logic packet_ended_r;
  logic malformed_r;
  tlp_error_e error_code_r;
  logic header_legal;
  tlp_error_e header_error;
  logic [31:0] calculated_ecrc;
  logic ecrc_valid;
  logic ecrc_start, ecrc_data_valid, ecrc_finish;
  logic [31:0] header_dw;
  wire input_fire = s_axis_tvalid && s_axis_tready;
  wire payload_fire = payload_tvalid_o && payload_tready_i;

  always_comb begin
    header_dw = s_axis_tdata;
    if (PCIE_WIRE_ORDER)
      header_dw = {s_axis_tdata[7:0], s_axis_tdata[15:8],
                   s_axis_tdata[23:16], s_axis_tdata[31:24]};
  end

  assign header_o = header_r;
  assign header_valid_o = state_r == RX_HEADER;
  assign payload_tdata_o = payload_data_mem[replay_count_r[9:0]];
  assign payload_tkeep_o = payload_keep_mem[replay_count_r[9:0]];
  assign payload_tvalid_o = state_r == RX_REPLAY;
  assign payload_tlast_o = replay_count_r + 1'b1 == header_r.length_dw;
  assign malformed_o = malformed_r;
  assign error_valid_o = malformed_r;
  assign error_code_o = error_code_r;
  assign ecrc_error_o = malformed_r && error_code_r == TLP_ERR_ECRC;

  always_comb begin
    s_axis_tready = state_r == RX_FIRST || state_r == RX_DW0 ||
                    state_r == RX_DW1 || state_r == RX_DW2 ||
                    state_r == RX_DW3 || state_r == RX_PAYLOAD ||
                    state_r == RX_ECRC || state_r == RX_DROP;
    ecrc_start = input_fire &&
        ((state_r == RX_FIRST && s_axis_tdata[7:5] != TLP_FMT_PREFIX) ||
         state_r == RX_DW0);
    ecrc_data_valid = input_fire &&
        (state_r == RX_FIRST || state_r == RX_DW0 || state_r == RX_DW1 ||
         state_r == RX_DW2 || state_r == RX_DW3 || state_r == RX_PAYLOAD) &&
        !(state_r == RX_FIRST && s_axis_tdata[7:5] == TLP_FMT_PREFIX);
    ecrc_finish = ecrc_data_valid && header_r.digest_present &&
        ((state_r == RX_DW2 && !tlp_is_4dw(header_r.fmt) && !tlp_has_data(header_r.fmt)) ||
         (state_r == RX_DW3 && !tlp_has_data(header_r.fmt)) ||
         (state_r == RX_PAYLOAD && receive_count_r + 1'b1 == header_r.length_dw));
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r <= RX_FIRST;
      header_r <= '0;
      receive_count_r <= '0;
      replay_count_r <= '0;
      packet_ended_r <= 1'b0;
      malformed_r <= 1'b0;
      error_code_r <= TLP_ERR_NONE;
    end else begin
      malformed_r <= 1'b0;
      error_code_r <= TLP_ERR_NONE;
      unique case (state_r)
        RX_FIRST: if (input_fire) begin
          header_r <= '0;
          receive_count_r <= '0;
          replay_count_r <= '0;
          packet_ended_r <= 1'b0;
          if (s_axis_tkeep != 4'hf) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_BAD_KEEP;
            state_r <= s_axis_tlast ? RX_FIRST : RX_DROP;
          end else if (s_axis_tdata[7:5] == TLP_FMT_PREFIX) begin
            header_r.prefix_present <= 1'b1;
            header_r.prefix <= s_axis_tdata;
            if (s_axis_tlast) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_TRUNCATED_HEADER;
            end else state_r <= RX_DW0;
          end else begin
            header_r.fmt <= s_axis_tdata[7:5];
            header_r.tlp_type <= s_axis_tdata[4:0];
            header_r.th <= s_axis_tdata[8];
            header_r.attributes <= {s_axis_tdata[10], s_axis_tdata[21:20]};
            header_r.traffic_class <= s_axis_tdata[14:12];
            header_r.address_type <= s_axis_tdata[19:18];
            header_r.poisoned <= s_axis_tdata[22];
            header_r.digest_present <= s_axis_tdata[23];
            header_r.length_dw <= ((s_axis_tdata[4:0] == TLP_TYPE_CPL ||
                s_axis_tdata[4:0] == TLP_TYPE_CPL_LOCK) &&
                !tlp_has_data(s_axis_tdata[7:5]) &&
                {s_axis_tdata[17:16],s_axis_tdata[31:24]} == 0) ? 0 :
                tlp_decode_length({s_axis_tdata[17:16],s_axis_tdata[31:24]});
            if (s_axis_tlast) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_TRUNCATED_HEADER;
            end else state_r <= RX_DW1;
          end
        end

        RX_DW0: if (input_fire) begin
          header_r.fmt <= s_axis_tdata[7:5];
          header_r.tlp_type <= s_axis_tdata[4:0];
          header_r.th <= s_axis_tdata[8];
          header_r.attributes <= {s_axis_tdata[10], s_axis_tdata[21:20]};
          header_r.traffic_class <= s_axis_tdata[14:12];
          header_r.address_type <= s_axis_tdata[19:18];
          header_r.poisoned <= s_axis_tdata[22];
          header_r.digest_present <= s_axis_tdata[23];
          header_r.length_dw <= ((s_axis_tdata[4:0] == TLP_TYPE_CPL ||
              s_axis_tdata[4:0] == TLP_TYPE_CPL_LOCK) &&
              !tlp_has_data(s_axis_tdata[7:5]) &&
              {s_axis_tdata[17:16],s_axis_tdata[31:24]} == 0) ? 0 :
              tlp_decode_length({s_axis_tdata[17:16],s_axis_tdata[31:24]});
          if (s_axis_tlast) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_TRUNCATED_HEADER;
            state_r <= RX_FIRST;
          end else state_r <= RX_DW1;
        end

        RX_DW1: if (input_fire) begin
          if (header_r.tlp_type == TLP_TYPE_CPL || header_r.tlp_type == TLP_TYPE_CPL_LOCK) begin
            header_r.completer_id <= header_dw[31:16];
            header_r.completion_status <= header_dw[15:13];
            header_r.byte_count_modified <= header_dw[12];
            header_r.byte_count <= header_dw[11:0] == 0 ? 13'd4096 :
                                   {1'b0,header_dw[11:0]};
          end else begin
            header_r.requester_id <= header_dw[31:16];
            header_r.tag <= header_dw[15:8];
            header_r.last_be <= header_dw[7:4];
            header_r.first_be <= header_dw[3:0];
          end
          if (s_axis_tlast) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_TRUNCATED_HEADER;
            state_r <= RX_FIRST;
          end else state_r <= RX_DW2;
        end

        RX_DW2: if (input_fire) begin
          packet_ended_r <= s_axis_tlast;
          if (header_r.tlp_type == TLP_TYPE_CPL || header_r.tlp_type == TLP_TYPE_CPL_LOCK) begin
            header_r.requester_id <= header_dw[31:16];
            header_r.tag <= header_dw[15:8];
            header_r.lower_address <= header_dw[6:0];
            state_r <= RX_VALIDATE;
          end else if (tlp_is_4dw(header_r.fmt)) begin
            header_r.address[63:32] <= header_dw;
            if (s_axis_tlast) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_TRUNCATED_HEADER;
              state_r <= RX_FIRST;
            end else state_r <= RX_DW3;
          end else begin
            header_r.address <= (header_r.tlp_type == TLP_TYPE_CFG0 ||
                header_r.tlp_type == TLP_TYPE_CFG1) ? {32'd0,header_dw} :
                {32'd0,header_dw[31:2],2'b00};
            state_r <= RX_VALIDATE;
          end
        end

        RX_DW3: if (input_fire) begin
          header_r.address[31:0] <= {header_dw[31:2],2'b00};
          packet_ended_r <= s_axis_tlast;
          state_r <= RX_VALIDATE;
        end

        RX_VALIDATE: begin
          if (!header_legal) begin
            malformed_r <= 1'b1;
            error_code_r <= header_error;
            state_r <= packet_ended_r ? RX_FIRST : RX_DROP;
          end else if (tlp_has_data(header_r.fmt)) begin
            if (packet_ended_r) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_EARLY_EOP;
              state_r <= RX_FIRST;
            end else state_r <= RX_PAYLOAD;
          end else if (header_r.digest_present) begin
            if (packet_ended_r) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_EARLY_EOP;
              state_r <= RX_FIRST;
            end else state_r <= RX_ECRC;
          end else if (!packet_ended_r) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_LATE_EOP;
            state_r <= RX_DROP;
          end else state_r <= RX_HEADER;
        end

        RX_PAYLOAD: if (input_fire) begin
          payload_data_mem[receive_count_r[9:0]] <= s_axis_tdata;
          payload_keep_mem[receive_count_r[9:0]] <= s_axis_tkeep;
          if (s_axis_tkeep == 0 ||
              (receive_count_r != 0 &&
               receive_count_r + 1'b1 < header_r.length_dw && s_axis_tkeep != 4'hf)) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_BAD_KEEP;
            state_r <= s_axis_tlast ? RX_FIRST : RX_DROP;
          end else if (receive_count_r + 1'b1 == header_r.length_dw) begin
            receive_count_r <= receive_count_r + 1'b1;
            if (header_r.digest_present) begin
              if (s_axis_tlast) begin
                malformed_r <= 1'b1;
                error_code_r <= TLP_ERR_EARLY_EOP;
                state_r <= RX_FIRST;
              end else state_r <= RX_ECRC;
            end else if (!s_axis_tlast) begin
              malformed_r <= 1'b1;
              error_code_r <= TLP_ERR_LATE_EOP;
              state_r <= RX_DROP;
            end else state_r <= RX_HEADER;
          end else if (s_axis_tlast) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_EARLY_EOP;
            state_r <= RX_FIRST;
          end else receive_count_r <= receive_count_r + 1'b1;
        end

        RX_ECRC: if (input_fire) begin
          header_r.digest <= s_axis_tdata;
          if (!s_axis_tlast) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_LATE_EOP;
            state_r <= RX_DROP;
          end else if (s_axis_tkeep != 4'hf) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_BAD_KEEP;
            state_r <= RX_FIRST;
          end else if (!ecrc_valid || s_axis_tdata != calculated_ecrc) begin
            malformed_r <= 1'b1;
            error_code_r <= TLP_ERR_ECRC;
            state_r <= RX_FIRST;
          end else state_r <= RX_HEADER;
        end

        RX_HEADER: if (header_ready_i) begin
          replay_count_r <= '0;
          state_r <= tlp_has_data(header_r.fmt) ? RX_REPLAY : RX_FIRST;
        end

        RX_REPLAY: if (payload_fire) begin
          if (payload_tlast_o)
            state_r <= RX_FIRST;
          else
            replay_count_r <= replay_count_r + 1'b1;
        end

        RX_DROP: if (input_fire && s_axis_tlast) state_r <= RX_FIRST;
        default: state_r <= RX_FIRST;
      endcase
    end
  end

  tlp_validator validator_inst (
      .header_i(header_r), .valid_o(header_legal), .error_o(header_error)
  );
  tlp_ecrc ecrc_inst (
      .clk_i(clk_i), .rst_i(rst_i), .start_i(ecrc_start),
      .data_i(s_axis_tdata), .keep_i(s_axis_tkeep),
      .data_valid_i(ecrc_data_valid), .finish_i(ecrc_finish),
      .ecrc_o(calculated_ecrc), .ecrc_valid_o(ecrc_valid)
  );
endmodule
