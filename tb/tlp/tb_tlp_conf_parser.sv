`timescale 1ns/1ps
// TL conformance sweep, Area 3: parser robustness wrapper.
// Flattens the parsed tlp_header_t fields the conformance test asserts on,
// including poisoned (EP) and attributes which the original tb_tlp_parser.sv
// does not expose.  tb-only; drives the unchanged src/tlp/tlp_parser.sv.
module tb_tlp_conf_parser;
  import tlp_pkg::*;
  logic clk_i = 0;
  logic rst_i;
  logic [31:0] s_axis_tdata;
  logic [3:0]  s_axis_tkeep;
  logic        s_axis_tvalid;
  logic        s_axis_tlast;
  logic [2:0]  s_axis_tuser;
  logic        s_axis_tready;
  logic        header_valid;
  logic        header_ready;
  logic [31:0] payload_tdata;
  logic [3:0]  payload_tkeep;
  logic        payload_tvalid;
  logic        payload_tlast;
  logic        payload_tready;
  logic        malformed;
  tlp_header_t header;

  logic [2:0]  header_fmt;
  logic [4:0]  header_type;
  logic [2:0]  header_traffic_class;
  logic [2:0]  header_attributes;
  logic [10:0] header_length_dw;
  logic [15:0] header_requester_id;
  logic [15:0] header_completer_id;
  logic [7:0]  header_tag;
  logic [3:0]  header_first_be;
  logic [3:0]  header_last_be;
  logic [63:0] header_address;
  logic [2:0]  header_status;
  logic [12:0] header_byte_count;
  logic [6:0]  header_lower_address;
  logic        header_poisoned;
  logic [1:0]  header_address_type;
  logic        header_th;
  logic        header_prefix_present;
  logic [31:0] header_prefix;
  logic        header_digest_present;
  logic [31:0] header_digest;

  assign header_fmt           = header.fmt;
  assign header_type          = header.tlp_type;
  assign header_traffic_class = header.traffic_class;
  assign header_attributes    = header.attributes;
  assign header_length_dw     = header.length_dw;
  assign header_requester_id  = header.requester_id;
  assign header_completer_id  = header.completer_id;
  assign header_tag           = header.tag;
  assign header_first_be      = header.first_be;
  assign header_last_be       = header.last_be;
  assign header_address       = header.address;
  assign header_status        = header.completion_status;
  assign header_byte_count    = header.byte_count;
  assign header_lower_address = header.lower_address;
  assign header_poisoned      = header.poisoned;
  assign header_address_type  = header.address_type;
  assign header_th            = header.th;
  assign header_prefix_present  = header.prefix_present;
  assign header_prefix          = header.prefix;
  assign header_digest_present  = header.digest_present;
  assign header_digest          = header.digest;

  tlp_parser dut (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
      .s_axis_tvalid(s_axis_tvalid), .s_axis_tlast(s_axis_tlast),
      .s_axis_tuser(s_axis_tuser), .s_axis_tready(s_axis_tready),
      .header_o(header), .header_valid_o(header_valid), .header_ready_i(header_ready),
      .payload_tdata_o(payload_tdata), .payload_tkeep_o(payload_tkeep),
      .payload_tvalid_o(payload_tvalid), .payload_tlast_o(payload_tlast),
      .payload_tready_i(payload_tready), .malformed_o(malformed)
  );
endmodule
