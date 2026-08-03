// ---------------------------------------------------------------------------
// tb_pcie_rc_if -- cocotb shim for the standalone pcie_rc_if unit tests (U1..U11).
//
// No Transaction Layer in the loop: the bench plays tlp_layer's received-
// completion surface itself. That is not a convenience, it is the point. The
// two failure modes this module exists to prevent -- losing a result under
// m_axis_rc_tready backpressure (U4) and pairing header N with result N-1
// (U10) -- both need the header handshake and the result handshake placed on
// exact cycles relative to each other, which is only possible with the TL out
// of the way. The integration target (verilate_rc_if_tlp) then proves the same
// module behaves against the real thing.
//
// pcie_rc_if has one struct-typed port, received_completion_header_i. cocotb
// cannot drive a packed struct field-wise through a hierarchy, so the CPL
// header fields are raised to the top level as separate signals and assembled
// here. Only the fields a Completion actually carries are exposed; the request-
// only fields (first_be/last_be/address/prefix/digest) are tied off, because a
// parsed CPL never populates them (tlp_parser.sv:163-189) and a bench that
// could set them would be modelling something the TL cannot produce.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_rc_if
  import tlp_pkg::*;
;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32;   // DW-granular (PG213)
  localparam int TL_DATA_WIDTH   = 32;
  localparam int TL_KEEP_WIDTH   = TL_DATA_WIDTH / 8;
  localparam int CONTEXT_WIDTH   = 16;

  logic clk_i = 0;
  logic rst_i;

  // ---- completion header, flattened --------------------------------------
  logic [2:0]  hdr_fmt_i;
  logic [4:0]  hdr_type_i;
  logic [2:0]  hdr_tc_i;
  logic [2:0]  hdr_attr_i;
  logic        hdr_poisoned_i;
  logic [10:0] hdr_length_dw_i;
  logic [15:0] hdr_requester_id_i;
  logic [15:0] hdr_completer_id_i;
  logic [7:0]  hdr_tag_i;
  logic [2:0]  hdr_completion_status_i;
  logic [12:0] hdr_byte_count_i;
  logic [6:0]  hdr_lower_address_i;

  tlp_header_t received_completion_header;
  always_comb begin
    received_completion_header                   = '0;
    received_completion_header.fmt               = hdr_fmt_i;
    received_completion_header.tlp_type          = hdr_type_i;
    received_completion_header.traffic_class     = hdr_tc_i;
    received_completion_header.attributes        = hdr_attr_i;
    received_completion_header.poisoned          = hdr_poisoned_i;
    received_completion_header.length_dw         = hdr_length_dw_i;
    received_completion_header.requester_id      = hdr_requester_id_i;
    received_completion_header.completer_id      = hdr_completer_id_i;
    received_completion_header.tag               = hdr_tag_i;
    received_completion_header.completion_status = hdr_completion_status_i;
    received_completion_header.byte_count        = hdr_byte_count_i;
    received_completion_header.lower_address     = hdr_lower_address_i;
  end

  logic received_completion_valid_i;
  logic received_completion_ready_o;

  logic [TL_DATA_WIDTH-1:0] received_completion_data_i;
  logic [TL_KEEP_WIDTH-1:0] received_completion_keep_i;
  logic                     received_completion_data_valid_i;
  logic                     received_completion_data_last_i;
  logic                     received_completion_data_ready_o;

  logic                     result_valid_i;
  logic                     result_ready_o;
  logic [CONTEXT_WIDTH-1:0] result_context_i;
  logic [2:0]               result_status_i;
  logic                     result_last_i;
  logic                     unexpected_completion_i;
  logic [4:0]               completion_error_code_i;

  logic [AXIS_DATA_WIDTH-1:0] m_axis_rc_tdata;
  logic [AXIS_KEEP_WIDTH-1:0] m_axis_rc_tkeep;
  logic                       m_axis_rc_tvalid;
  logic                       m_axis_rc_tlast;
  logic                       m_axis_rc_tready;

  logic       rc_unexpected_completion_o;
  logic [4:0] rc_completion_error_code_o;
  logic       rc_protocol_error_o;
  logic [3:0] rc_error_code_o;
  logic       rc_gearbox_error_o;

  pcie_rc_if #(
      .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
      .TL_DATA_WIDTH  (TL_DATA_WIDTH),
      .CONTEXT_WIDTH  (CONTEXT_WIDTH)
  ) dut (
      .clk_i(clk_i), .rst_i(rst_i),

      .received_completion_valid_i (received_completion_valid_i),
      .received_completion_ready_o (received_completion_ready_o),
      .received_completion_header_i(received_completion_header),

      .received_completion_data_i      (received_completion_data_i),
      .received_completion_keep_i      (received_completion_keep_i),
      .received_completion_data_valid_i(received_completion_data_valid_i),
      .received_completion_data_last_i (received_completion_data_last_i),
      .received_completion_data_ready_o(received_completion_data_ready_o),

      .result_valid_i         (result_valid_i),
      .result_ready_o         (result_ready_o),
      .result_context_i       (result_context_i),
      .result_status_i        (result_status_i),
      .result_last_i          (result_last_i),
      .unexpected_completion_i(unexpected_completion_i),
      .completion_error_code_i(tlp_error_e'(completion_error_code_i)),

      .m_axis_rc_tdata (m_axis_rc_tdata),
      .m_axis_rc_tkeep (m_axis_rc_tkeep),
      .m_axis_rc_tvalid(m_axis_rc_tvalid),
      .m_axis_rc_tlast (m_axis_rc_tlast),
      .m_axis_rc_tready(m_axis_rc_tready),

      .rc_unexpected_completion_o(rc_unexpected_completion_o),
      .rc_completion_error_code_o(rc_completion_error_code_o),
      .rc_protocol_error_o       (rc_protocol_error_o),
      .rc_error_code_o           (rc_error_code_o),
      .rc_gearbox_error_o        (rc_gearbox_error_o)
  );

endmodule
