`timescale 1ns/1ps
module tlp_completion_generator
  import tlp_pkg::*;
#(
    parameter int DATA_WIDTH = 32,
    parameter int KEEP_WIDTH = DATA_WIDTH / 8
) (
    input  logic                  clk_i,
    input  logic                  rst_i,
    input  logic [15:0]           completer_id_i,
    input  logic [12:0]           max_payload_bytes_i,
    input  logic                  rcb_128b_i,

    input  logic                  request_valid_i,
    output logic                  request_ready_o,
    input  tlp_header_t           request_header_i,
    input  logic [2:0]            request_status_i,
    input  logic [12:0]           request_byte_count_i,
    input  logic [6:0]            request_lower_address_i,
    input  logic                  request_ecrc_enable_i,

    input  logic [DATA_WIDTH-1:0] request_data_i,
    input  logic [KEEP_WIDTH-1:0] request_keep_i,
    input  logic                  request_data_valid_i,
    input  logic                  request_data_last_i,
    output logic                  request_data_ready_o,

    output tlp_header_t           packet_header_o,
    output logic                  packet_header_valid_o,
    input  logic                  packet_header_ready_i,
    output logic [DATA_WIDTH-1:0] packet_data_o,
    output logic [KEEP_WIDTH-1:0] packet_keep_o,
    output logic                  packet_data_valid_o,
    output logic                  packet_data_last_o,
    input  logic                  packet_data_ready_i,
    output logic                  error_valid_o,
    output tlp_error_e            error_code_o
);

  typedef enum logic [1:0] {CPL_IDLE, CPL_HEADER, CPL_DATA} cpl_state_e;
  cpl_state_e state_r;
  tlp_header_t header_r;
  logic [12:0] sent_bytes_r;
  logic [12:0] remaining_bytes_r;
  logic [12:0] segment_bytes_r;
  logic [6:0] lower_address_r;
  logic [12:0] accepted_bytes;
  logic [12:0] segment_wire_bytes;
  logic expected_last;
  integer lane;

  function automatic logic [12:0] completion_segment(
      input logic [12:0] remaining,
      input logic [6:0] lower_address
  );
    logic [12:0] limit;
    logic [12:0] boundary;
    limit = max_payload_bytes_i == 0 ? 13'd128 : max_payload_bytes_i;
    boundary = rcb_128b_i ? 13'd128 - {6'd0,lower_address[6:0]} :
                            13'd64 - {7'd0,lower_address[5:0]};
    completion_segment = remaining;
    if (completion_segment > limit) completion_segment = limit;
    if (completion_segment > boundary) completion_segment = boundary;
  endfunction

  always_comb begin
    accepted_bytes = '0;
    for (lane = 0; lane < KEEP_WIDTH; lane = lane + 1)
      accepted_bytes = accepted_bytes + request_keep_i[lane];
    // header_r.length_dw counts the leading partial DW created by an unaligned
    // lower_address, so the payload occupies ceil((segment_bytes +
    // lower_address[1:0]) / 4) beats on the wire.  The data phase must budget
    // those same pad bytes, or it closes the packet a DW short of the length the
    // header already declared.  Only the beat accounting takes the padding --
    // segment_bytes_r stays in true payload-byte space for the RCB/MPS segment
    // advance below.  Identical to the raw byte count when lower_address[1:0]==0.
    segment_wire_bytes = segment_bytes_r + {11'd0, lower_address_r[1:0]};
    expected_last = sent_bytes_r + accepted_bytes >= segment_wire_bytes;
  end

  assign request_ready_o = state_r == CPL_IDLE;
  assign packet_header_o = header_r;
  assign packet_header_valid_o = state_r == CPL_HEADER;
  assign packet_data_o = request_data_i;
  assign packet_keep_o = request_keep_i;
  assign packet_data_valid_o = state_r == CPL_DATA && request_data_valid_i;
  assign packet_data_last_o = expected_last || request_data_last_i;
  assign request_data_ready_o = state_r == CPL_DATA && packet_data_ready_i;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r  <= CPL_IDLE;
      header_r <= '0;
      sent_bytes_r <= '0;
      remaining_bytes_r <= '0;
      segment_bytes_r <= '0;
      lower_address_r <= '0;
      error_valid_o <= 1'b0;
      error_code_o <= TLP_ERR_NONE;
    end else begin
      error_valid_o <= 1'b0;
      error_code_o <= TLP_ERR_NONE;
      unique case (state_r)
        CPL_IDLE: if (request_valid_i && request_ready_o) begin
          header_r <= '0;
          header_r.fmt <= request_byte_count_i == 0 || request_status_i != TLP_CPL_SC ?
                          TLP_FMT_3DW_NO_DATA : TLP_FMT_3DW_DATA;
          header_r.tlp_type <= TLP_TYPE_CPL;
          header_r.traffic_class <= request_header_i.traffic_class;
          header_r.attributes <= request_header_i.attributes;
          header_r.length_dw <= request_byte_count_i == 0 || request_status_i != TLP_CPL_SC ?
              11'd0 : 11'((completion_segment(request_byte_count_i,
              request_lower_address_i) +
              {11'd0, request_lower_address_i[1:0]} + 13'd3) >> 2);
          header_r.requester_id <= request_header_i.requester_id;
          header_r.completer_id <= completer_id_i;
          header_r.tag <= request_header_i.tag;
          header_r.completion_status <= request_status_i;
          header_r.byte_count <= request_byte_count_i;
          header_r.lower_address <= request_lower_address_i;
          header_r.digest_present <= request_ecrc_enable_i;
          sent_bytes_r <= '0;
          remaining_bytes_r <= request_byte_count_i;
          segment_bytes_r <= request_status_i == TLP_CPL_SC ?
              completion_segment(request_byte_count_i, request_lower_address_i) : 0;
          lower_address_r <= request_lower_address_i;
          state_r <= CPL_HEADER;
        end

        CPL_HEADER: if (packet_header_ready_i) begin
          if (header_r.length_dw == 0)
            state_r <= CPL_IDLE;
          else
            state_r <= CPL_DATA;
        end

        CPL_DATA: if (request_data_valid_i && request_data_ready_o) begin
          sent_bytes_r <= sent_bytes_r + accepted_bytes;
          if (request_data_last_i != (expected_last && remaining_bytes_r <= segment_bytes_r)) begin
            error_valid_o <= 1'b1;
            error_code_o <= TLP_ERR_LOCAL_PAYLOAD;
          end
          if (request_data_last_i && !expected_last) begin
            state_r <= CPL_IDLE;
          end else if (expected_last) begin
            if (remaining_bytes_r > segment_bytes_r) begin
              remaining_bytes_r <= remaining_bytes_r - segment_bytes_r;
              lower_address_r <= lower_address_r + segment_bytes_r[6:0];
              header_r.byte_count <= remaining_bytes_r - segment_bytes_r;
              header_r.lower_address <= lower_address_r + segment_bytes_r[6:0];
              segment_bytes_r <= completion_segment(remaining_bytes_r - segment_bytes_r,
                  lower_address_r + segment_bytes_r[6:0]);
              header_r.length_dw <= 11'((completion_segment(
                  remaining_bytes_r - segment_bytes_r,
                  lower_address_r + segment_bytes_r[6:0]) +
                  {11'd0,lower_address_r[1:0] + segment_bytes_r[1:0]} + 13'd3) >> 2);
              sent_bytes_r <= '0;
              state_r <= CPL_HEADER;
            end else state_r <= CPL_IDLE;
          end
        end

        default: state_r <= CPL_IDLE;
      endcase
    end
  end

endmodule
