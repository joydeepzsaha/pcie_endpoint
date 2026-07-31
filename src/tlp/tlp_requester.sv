`timescale 1ns/1ps
module tlp_requester
  import tlp_pkg::*;
#(
    parameter int DATA_WIDTH = 32,
    parameter int KEEP_WIDTH = DATA_WIDTH / 8,
    parameter int CONTEXT_WIDTH = 16
) (
    input  logic                     clk_i,
    input  logic                     rst_i,
    input  logic [15:0]              requester_id_i,
    input  logic [12:0]              max_payload_bytes_i,
    input  logic [12:0]              max_read_bytes_i,

    input  logic                     command_valid_i,
    output logic                     command_ready_o,
    input  tlp_cmd_e                 command_i,
    input  logic [63:0]              command_address_i,
    input  logic [12:0]              command_byte_count_i,
    input  logic [2:0]               command_tc_i,
    input  logic [2:0]               command_attr_i,
    input  logic [CONTEXT_WIDTH-1:0] command_context_i,
    input  logic                     command_prefix_valid_i,
    input  logic [31:0]              command_prefix_i,
    input  logic                     command_ecrc_enable_i,

    input  logic [DATA_WIDTH-1:0]    command_data_i,
    input  logic [KEEP_WIDTH-1:0]    command_keep_i,
    input  logic                     command_data_valid_i,
    input  logic                     command_data_last_i,
    output logic                     command_data_ready_o,

    output logic                     tag_request_valid_o,
    input  logic                     tag_request_ready_i,
    input  logic [7:0]               tag_i,
    output logic [15:0]              tag_requester_id_o,
    output logic [12:0]              tag_byte_count_o,
    output logic [CONTEXT_WIDTH-1:0] tag_context_o,
    output logic                     tag_expects_data_o,

    output tlp_header_t              packet_header_o,
    output logic                     packet_header_valid_o,
    input  logic                     packet_header_ready_i,
    output logic [DATA_WIDTH-1:0]    packet_data_o,
    output logic [KEEP_WIDTH-1:0]    packet_keep_o,
    output logic                     packet_data_valid_o,
    output logic                     packet_data_last_o,
    input  logic                     packet_data_ready_i,
    output logic                     command_error_valid_o,
    output tlp_error_e               command_error_code_o
);

  typedef enum logic [2:0] {REQ_IDLE, REQ_TAG, REQ_HEADER, REQ_DATA} req_state_e;
  req_state_e state_r;
  tlp_cmd_e command_r;
  logic [63:0] address_r;
  logic [12:0] remaining_r;
  logic [12:0] segment_bytes_r;
  logic [12:0] segment_sent_r;
  logic [2:0] tc_r;
  logic [2:0] attr_r;
  logic [CONTEXT_WIDTH-1:0] context_r;
  logic [7:0] tag_r;
  logic prefix_valid_r;
  logic [31:0] prefix_r;
  logic ecrc_enable_r;
  tlp_header_t header_c;
  logic command_has_data;
  logic command_non_posted;
  logic [12:0] accepted_bytes;
  logic expected_data_last;
  logic request_last;
  integer lane;

  // Command-class predicates.  Every site below that needs "is this config", "is
  // this config or IO", or the read/write direction calls one of these instead of
  // re-enumerating the members inline.  The RX side already works this way --
  // tlp_validator.sv:17-19 mints config_or_io once from the header -- and the TX
  // side used to spell the same memberships out by hand in five places, one of
  // which (the tlp_type select) failed open: a command missing from its list was
  // emitted as a well-formed Memory Read.
  function automatic logic command_is_config(input tlp_cmd_e command);
    return command == TLP_CMD_CFG_READ0 || command == TLP_CMD_CFG_WRITE0;
  endfunction

  function automatic logic command_is_io(input tlp_cmd_e command);
    return command == TLP_CMD_IO_READ || command == TLP_CMD_IO_WRITE;
  endfunction

  function automatic logic command_is_config_or_io(input tlp_cmd_e command);
    return command_is_config(command) || command_is_io(command);
  endfunction

  function automatic logic command_is_read(input tlp_cmd_e command);
    return command == TLP_CMD_MEM_READ || command == TLP_CMD_CFG_READ0 ||
           command == TLP_CMD_IO_READ;
  endfunction

  function automatic logic command_is_write(input tlp_cmd_e command);
    return command == TLP_CMD_MEM_WRITE || command == TLP_CMD_CFG_WRITE0 ||
           command == TLP_CMD_IO_WRITE;
  endfunction

  function automatic logic [12:0] command_limit(input tlp_cmd_e command);
    if (command_is_config_or_io(command))
      return 13'd4;
    if (command == TLP_CMD_MEM_READ)
      return max_read_bytes_i == 0 ? 13'd128 : max_read_bytes_i;
    return max_payload_bytes_i == 0 ? 13'd128 : max_payload_bytes_i;
  endfunction

  function automatic logic [12:0] calculate_segment(
      input logic [63:0] address,
      input logic [12:0] remaining,
      input logic [12:0] limit
  );
    logic [12:0] value;
    logic [12:0] boundary;
    logic [12:0] aligned_limit;
    boundary = 13'd4096 - {1'b0, address[11:0]};
    aligned_limit = limit > {11'd0, address[1:0]} ?
                    limit - {11'd0, address[1:0]} : 13'd1;
    value = remaining;
    if (value > aligned_limit)
      value = aligned_limit;
    if (value > boundary)
      value = boundary;
    return value;
  endfunction

  always_comb begin
    command_has_data   = command_is_write(command_r);
    command_non_posted = command_r != TLP_CMD_MEM_WRITE;
    accepted_bytes = '0;
    for (lane = 0; lane < KEEP_WIDTH; lane = lane + 1)
      accepted_bytes = accepted_bytes + command_keep_i[lane];

    header_c = '0;
    header_c.fmt = command_has_data ?
        (address_r[63:32] == 0 ? TLP_FMT_3DW_DATA : TLP_FMT_4DW_DATA) :
        (address_r[63:32] == 0 ? TLP_FMT_3DW_NO_DATA : TLP_FMT_4DW_NO_DATA);
    header_c.tlp_type = TLP_TYPE_MEM;
    if (command_is_config(command_r)) begin
      header_c.tlp_type = TLP_TYPE_CFG0;
      header_c.fmt = command_has_data ? TLP_FMT_3DW_DATA : TLP_FMT_3DW_NO_DATA;
    end else if (command_is_io(command_r)) begin
      header_c.tlp_type = TLP_TYPE_IO;
      header_c.fmt = command_has_data ? TLP_FMT_3DW_DATA : TLP_FMT_3DW_NO_DATA;
    end
    header_c.traffic_class = tc_r;
    header_c.attributes    = attr_r;
    header_c.length_dw     = segment_bytes_r == 0 ? 11'd1 :
        11'((segment_bytes_r + {11'd0, address_r[1:0]} + 13'd3) >> 2);
    header_c.requester_id  = requester_id_i;
    header_c.tag           = tag_r;
    header_c.first_be      = tlp_first_be(address_r[1:0], segment_bytes_r);
    header_c.last_be       = tlp_last_be(address_r[1:0], segment_bytes_r);
    header_c.address       = address_r;
    header_c.prefix_present = prefix_valid_r;
    header_c.prefix         = prefix_r;
    header_c.digest_present = ecrc_enable_r;
  end

  assign command_ready_o = state_r == REQ_IDLE;
  assign tag_request_valid_o = state_r == REQ_TAG;
  assign tag_requester_id_o = requester_id_i;
  assign tag_byte_count_o = segment_bytes_r == 0 ? 13'd4 : segment_bytes_r;
  assign tag_context_o = context_r;
  assign tag_expects_data_o = command_is_read(command_r);
  assign packet_header_o = header_c;
  assign packet_header_valid_o = state_r == REQ_HEADER;
  assign packet_data_o = command_data_i;
  assign packet_keep_o = command_keep_i;
  assign packet_data_valid_o = state_r == REQ_DATA && command_data_valid_i;
  assign expected_data_last = segment_sent_r + accepted_bytes >= segment_bytes_r;
  // End of the whole request: this beat closes the current segment
  // (expected_data_last) AND there is no further segment to send
  // (remaining_r <= segment_bytes_r => this is the final segment).  The host's
  // command_data_last_i means "whole request done", so command_error_valid_o must
  // be compared against this, not the per-segment expected_data_last.
  assign request_last = expected_data_last && (remaining_r <= segment_bytes_r);
  // Always close the transmitted packet if the local producer terminates early;
  // command_error_o identifies that its length disagreed with the command.
  assign packet_data_last_o = expected_data_last || command_data_last_i;
  assign command_data_ready_o = state_r == REQ_DATA && packet_data_ready_i;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r         <= REQ_IDLE;
      command_r       <= TLP_CMD_MEM_READ;
      address_r       <= '0;
      remaining_r     <= '0;
      segment_bytes_r <= '0;
      segment_sent_r  <= '0;
      tc_r            <= '0;
      attr_r          <= '0;
      context_r       <= '0;
      tag_r           <= '0;
      prefix_valid_r  <= 1'b0;
      prefix_r        <= '0;
      ecrc_enable_r   <= 1'b0;
      command_error_valid_o <= 1'b0;
      command_error_code_o <= TLP_ERR_NONE;
    end else begin
      command_error_valid_o <= 1'b0;
      command_error_code_o <= TLP_ERR_NONE;
      unique case (state_r)
        REQ_IDLE: if (command_valid_i && command_ready_o) begin
          // Config and IO requests must be exactly one DW long (PCIe Base 2.1
          // SS2.2.7), but the spec constrains the Length field, not the byte
          // enables: a single-byte config write with first_be=0010 is legal.
          // So admit any request that fits inside the addressed DW -- i.e.
          // byte_count <= 4 - address[1:0], with byte_count == 0 still
          // rejected by the first clause below.  Every admitted shape then has
          // byte_count + address[1:0] <= 4, so length_dw (:125-126) is 1 by
          // construction, and calculate_segment's clamp to 4 - address[1:0]
          // (:93-94) can no longer split the request across two config TLPs.
          if ((command_byte_count_i == 0 && command_i != TLP_CMD_MEM_READ) ||
              (command_is_config_or_io(command_i) &&
               command_byte_count_i > (13'd4 - {11'd0, command_address_i[1:0]}))) begin
            command_error_valid_o <= 1'b1;
            command_error_code_o <= TLP_ERR_BAD_LENGTH;
          end else begin
            command_r   <= command_i;
            address_r   <= command_address_i;
            remaining_r <= command_byte_count_i;
            tc_r        <= command_tc_i;
            attr_r      <= command_attr_i;
            context_r   <= command_context_i;
            prefix_valid_r <= command_prefix_valid_i;
            prefix_r       <= command_prefix_i;
            ecrc_enable_r  <= command_ecrc_enable_i;
            segment_bytes_r <= calculate_segment(command_address_i, command_byte_count_i,
                                                 command_limit(command_i));
            segment_sent_r <= '0;
            state_r <= command_i == TLP_CMD_MEM_WRITE ? REQ_HEADER : REQ_TAG;
          end
        end

        REQ_TAG: if (tag_request_ready_i) begin
          tag_r <= tag_i;
          state_r <= REQ_HEADER;
        end

        REQ_HEADER: if (packet_header_ready_i) begin
          if (command_has_data) begin
            state_r <= REQ_DATA;
          end else if (remaining_r > segment_bytes_r) begin
            address_r <= address_r + {51'd0, segment_bytes_r};
            remaining_r <= remaining_r - segment_bytes_r;
            segment_bytes_r <= calculate_segment(address_r + {51'd0, segment_bytes_r},
                remaining_r - segment_bytes_r, command_limit(command_r));
            state_r <= REQ_TAG;
          end else begin
            state_r <= REQ_IDLE;
          end
        end

        REQ_DATA: if (command_data_valid_i && command_data_ready_o) begin
          segment_sent_r <= segment_sent_r + accepted_bytes;
          if (command_data_last_i != request_last)
            begin
              command_error_valid_o <= 1'b1;
              command_error_code_o <= TLP_ERR_LOCAL_PAYLOAD;
            end
          if (command_data_last_i && !expected_data_last) begin
            // The source ended before the byte count promised by the command.
            // Abort this command after forwarding a terminating beat so that
            // both interfaces can recover for the next command.
            state_r <= REQ_IDLE;
          end else if (expected_data_last) begin
            if (remaining_r > segment_bytes_r) begin
              address_r <= address_r + {51'd0, segment_bytes_r};
              remaining_r <= remaining_r - segment_bytes_r;
              segment_bytes_r <= calculate_segment(address_r + {51'd0, segment_bytes_r},
                  remaining_r - segment_bytes_r, command_limit(command_r));
              segment_sent_r <= '0;
              state_r <= command_non_posted ? REQ_TAG : REQ_HEADER;
            end else begin
              state_r <= REQ_IDLE;
            end
          end
        end

        default: state_r <= REQ_IDLE;
      endcase
    end
  end

endmodule
