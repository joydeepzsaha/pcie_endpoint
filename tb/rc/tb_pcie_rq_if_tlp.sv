// ---------------------------------------------------------------------------
// tb_pcie_rq_if_tlp -- integration shim: pcie_rq_if driving a real tlp_layer.
//
// Same wire, new interface. The Commit-1 config goldens (CfgRd0 DW0 =
// 0x01000004, CfgWr0 DW0 = 0x01000044) are re-checked here through the RQ
// descriptor path instead of the raw command port, which is the whole point of
// T12/T13: proving the new front end did not change what leaves the chip.
//
// ! Flow control. tlp_layer emits ZERO TLPs and no error unless link_up_i,
// transmit_enable_i and fc_initialized_i are all set AND at least one
// fc_update_valid_i pulse has loaded non-zero credits (tlp_layer.sv:249,
// tlp_credit_manager.sv:53-54, 66-83). Config requests consume NPH/NPD. A
// bench that forgets this observes nothing and concludes the DUT is broken.
// The credit inputs are exposed on this shim so the Python side drives them.
//
// The tlp_header_t ports (target_request_header_o, completion_request_header_i,
// received_completion_header_o) are struct-typed and are deliberately left
// unconnected or tied off locally rather than raised to the top level: this
// bench observes the TX DLLP stream, not the receive surface.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_rq_if_tlp
  import tlp_pkg::*;
;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_USER_WIDTH = 60;
  localparam int DATA_WIDTH      = 32;
  localparam int KEEP_WIDTH      = DATA_WIDTH / 8;
  localparam int CONTEXT_WIDTH   = 16;

  logic clk_i = 0;
  logic rst_i;

  // ---- host-facing RQ AXIS ------------------------------------------------
  logic [AXIS_DATA_WIDTH-1:0] s_axis_rq_tdata;
  logic [3:0]                 s_axis_rq_tkeep;
  logic                       s_axis_rq_tvalid;
  logic                       s_axis_rq_tlast;
  logic [AXIS_USER_WIDTH-1:0] s_axis_rq_tuser;
  logic                       s_axis_rq_tready;

  logic [7:0] allocated_tag;
  logic       allocated_tag_valid;
  logic [7:0] pcie_rq_tag_o;
  logic       pcie_rq_tag_vld_o;
  logic       rq_protocol_error_o;
  logic [3:0] rq_error_code_o;
  logic       rq_gearbox_error_o;

  // ---- link / flow-control controls, driven from Python -------------------
  logic        link_up_i;
  logic        transmit_enable_i;
  logic [15:0] requester_id_i;
  logic [12:0] max_payload_bytes_i;
  logic [12:0] max_read_bytes_i;
  logic        fc_initialized_i;
  logic        fc_update_valid_i;
  logic [7:0]  fc_ph_i,   fc_nph_i,  fc_cplh_i;
  logic [11:0] fc_pd_i,   fc_npd_i,  fc_cpld_i;

  // ---- TX stream out of the Transaction Layer -----------------------------
  logic [DATA_WIDTH-1:0] m_dllp_axis_tdata;
  logic [KEEP_WIDTH-1:0] m_dllp_axis_tkeep;
  logic                  m_dllp_axis_tvalid;
  logic                  m_dllp_axis_tlast;
  logic [2:0]            m_dllp_axis_tuser;
  logic                  m_dllp_axis_tready;

  // ---- error surface ------------------------------------------------------
  logic       command_error_valid_o;
  tlp_error_e command_error_code_o;
  logic [3:0] command_error_code_flat;
  assign command_error_code_flat = 4'(command_error_code_o);

  logic tx_error_valid_o;
  logic malformed_o;
  logic tx_fc_blocked_o;
  logic credit_error_o;

  // ---- wrapper <-> TL command port ----------------------------------------
  logic                     command_valid;
  logic                     command_ready;
  tlp_cmd_e                 command;
  logic [63:0]              command_address;
  logic [12:0]              command_byte_count;
  logic [2:0]               command_tc;
  logic [2:0]               command_attr;
  logic [CONTEXT_WIDTH-1:0] command_context;
  logic                     command_prefix_valid;
  logic [31:0]              command_prefix;
  logic                     command_ecrc_enable;
  logic [DATA_WIDTH-1:0]    command_data;
  logic [KEEP_WIDTH-1:0]    command_keep;
  logic                     command_data_valid;
  logic                     command_data_last;
  logic                     command_data_ready;

  pcie_rq_if #(
      .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
      .AXIS_USER_WIDTH(AXIS_USER_WIDTH),
      .CONTEXT_WIDTH  (CONTEXT_WIDTH)
  ) u_rq (
      .clk_i(clk_i), .rst_i(rst_i),

      .s_axis_rq_tdata (s_axis_rq_tdata),
      .s_axis_rq_tkeep (s_axis_rq_tkeep),
      .s_axis_rq_tvalid(s_axis_rq_tvalid),
      .s_axis_rq_tlast (s_axis_rq_tlast),
      .s_axis_rq_tuser (s_axis_rq_tuser),
      .s_axis_rq_tready(s_axis_rq_tready),

      .allocated_tag_i(allocated_tag),
      .allocated_tag_valid_i(allocated_tag_valid),
      .pcie_rq_tag_o(pcie_rq_tag_o),
      .pcie_rq_tag_vld_o(pcie_rq_tag_vld_o),

      .command_valid_o       (command_valid),
      .command_ready_i       (command_ready),
      .command_o             (command),
      .command_address_o     (command_address),
      .command_byte_count_o  (command_byte_count),
      .command_tc_o          (command_tc),
      .command_attr_o        (command_attr),
      .command_context_o     (command_context),
      .command_prefix_valid_o(command_prefix_valid),
      .command_prefix_o      (command_prefix),
      .command_ecrc_enable_o (command_ecrc_enable),

      .command_data_o      (command_data),
      .command_keep_o      (command_keep),
      .command_data_valid_o(command_data_valid),
      .command_data_last_o (command_data_last),
      .command_data_ready_i(command_data_ready),

      .rq_protocol_error_o(rq_protocol_error_o),
      .rq_error_code_o    (rq_error_code_o),
      .rq_gearbox_error_o (rq_gearbox_error_o)
  );

  // Struct-typed TL ports this bench does not observe.
  tlp_header_t completion_request_header_tie;
  assign completion_request_header_tie = '0;

  tlp_layer #(
      .DATA_WIDTH   (DATA_WIDTH),
      .CONTEXT_WIDTH(CONTEXT_WIDTH)
  ) u_tl (
      .clk_i(clk_i), .rst_i(rst_i),
      .link_up_i        (link_up_i),
      .transmit_enable_i(transmit_enable_i),
      .requester_id_i   (requester_id_i),
      .completer_id_i   (16'h0000),
      .bus_number_i     (8'h00),
      .device_number_i  (5'h00),
      .function_number_i(3'h0),
      .memory_enable_i  (1'b1),
      .extended_tag_enable_i(1'b0),
      .max_payload_bytes_i  (max_payload_bytes_i),
      .max_read_bytes_i     (max_read_bytes_i),
      .rcb_128b_i           (1'b0),
      .fc_initialized_i (fc_initialized_i),
      .fc_update_valid_i(fc_update_valid_i),
      .fc_ph_i(fc_ph_i), .fc_pd_i(fc_pd_i),
      .fc_nph_i(fc_nph_i), .fc_npd_i(fc_npd_i),
      .fc_cplh_i(fc_cplh_i), .fc_cpld_i(fc_cpld_i),

      // RX DLLP stream: idle, this bench originates only.
      .s_dllp_axis_tdata ('0),
      .s_dllp_axis_tkeep ('0),
      .s_dllp_axis_tvalid(1'b0),
      .s_dllp_axis_tlast (1'b0),
      .s_dllp_axis_tuser ('0),
      .s_dllp_axis_tready(),

      .m_dllp_axis_tdata (m_dllp_axis_tdata),
      .m_dllp_axis_tkeep (m_dllp_axis_tkeep),
      .m_dllp_axis_tvalid(m_dllp_axis_tvalid),
      .m_dllp_axis_tlast (m_dllp_axis_tlast),
      .m_dllp_axis_tuser (m_dllp_axis_tuser),
      .m_dllp_axis_tready(m_dllp_axis_tready),

      .command_valid_i       (command_valid),
      .command_ready_o       (command_ready),
      .command_i             (command),
      .command_address_i     (command_address),
      .command_byte_count_i  (command_byte_count),
      .command_tc_i          (command_tc),
      .command_attr_i        (command_attr),
      .command_context_i     (command_context),
      .command_prefix_valid_i(command_prefix_valid),
      .command_prefix_i      (command_prefix),
      .command_ecrc_enable_i (command_ecrc_enable),
      .command_data_i        (command_data),
      .command_keep_i        (command_keep),
      .command_data_valid_i  (command_data_valid),
      .command_data_last_i   (command_data_last),
      .command_data_ready_o  (command_data_ready),
      .command_error_valid_o (command_error_valid_o),
      .command_error_code_o  (command_error_code_o),
      .allocated_tag_o       (allocated_tag),
      .allocated_tag_valid_o (allocated_tag_valid),

      .target_request_valid_o(),
      .target_request_ready_i(1'b1),
      .target_request_header_o(),
      .target_request_class_o(),
      .target_memory_o(), .target_config_o(), .target_config_hit_o(),
      .target_config_type_one_o(), .target_config_offset_o(),
      .target_read_o(), .target_write_o(), .target_unsupported_o(),
      .target_bar_hit_o(), .target_bar_overlap_o(), .target_bar_o(),
      .target_offset_o(), .target_data_o(), .target_keep_o(),
      .target_data_valid_o(), .target_data_last_o(),
      .target_data_ready_i(1'b1),

      .completion_request_valid_i (1'b0),
      .completion_request_ready_o (),
      .completion_request_header_i(completion_request_header_tie),
      .completion_request_status_i('0),
      .completion_request_byte_count_i('0),
      .completion_request_lower_address_i('0),
      .completion_request_ecrc_enable_i(1'b0),
      .completion_request_data_i('0),
      .completion_request_keep_i('0),
      .completion_request_data_valid_i(1'b0),
      .completion_request_data_last_i(1'b0),
      .completion_request_data_ready_o(),

      .received_completion_valid_o(),
      .received_completion_ready_i(1'b1),
      .received_completion_header_o(),
      .received_completion_data_o(), .received_completion_keep_o(),
      .received_completion_data_valid_o(), .received_completion_data_last_o(),
      .received_completion_data_ready_i(1'b1),

      .result_valid_o(), .result_ready_i(1'b1), .result_context_o(),
      .result_status_o(), .result_last_o(),
      .malformed_o(malformed_o),
      .rx_error_valid_o(), .rx_error_code_o(), .rx_ecrc_error_o(),
      .tx_error_valid_o(tx_error_valid_o), .tx_error_code_o(),
      .tx_fc_blocked_o(tx_fc_blocked_o),
      .credit_error_o(credit_error_o),
      .vc_overflow_o(), .unexpected_completion_o(),
      .completion_error_code_o(),
      .cpl_timeout_valid_o(), .cpl_timeout_tag_o(),
      .late_cpl_valid_o(), .late_cpl_tag_o(),
      .outstanding_o()
  );

endmodule
