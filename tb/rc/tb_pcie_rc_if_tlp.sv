// ---------------------------------------------------------------------------
// tb_pcie_rc_if_tlp -- integration shim: the whole 2a loop.
//
//   host RQ AXIS -> pcie_rq_if -> tlp_layer -> TX DLLP stream
//   RX DLLP stream -> tlp_layer -> pcie_rc_if -> host RC AXIS
//
// Both wrappers are present on purpose. U13 compares the RC descriptor's Tag
// against pcie_rq_tag_o, the tag pcie_rq_if presents at pcie_rq_tag_vld_o, and
// that is the tag the TRACKER allocated and put on the wire (the 54b8a72 fix).
// Closing that loop is the point of the target: a tag that leaves on a CfgRd0
// and comes back in an RC descriptor proves the request and completion halves
// of Commit 2a agree about which request a completion answers, which is the
// property Commit 2b's enumeration FSM is going to build on.
//
// ! Flow control. tlp_layer emits ZERO TLPs and no error unless link_up_i,
// transmit_enable_i and fc_initialized_i are all set AND at least one
// fc_update_valid_i pulse has loaded non-zero credits (tlp_layer.sv:249,
// tlp_credit_manager.sv:53-54, 66-83). This bench MUST originate before it can
// inject: a completion with no outstanding tag behind it is an unexpected
// completion, the tracker produces no result, and pcie_rc_if correctly emits
// nothing. A bench that forgets the credits sees exactly that and blames the
// wrong module.
//
// The struct-typed received_completion_header_o is wired straight from
// tlp_layer into pcie_rc_if and never raised to the top level -- the Python
// side reads the RC descriptor, which is the interface under test, not the
// TL's internal header shape.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_rc_if_tlp
  import tlp_pkg::*;
;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32;
  localparam int AXIS_USER_WIDTH = 60;
  localparam int DATA_WIDTH      = 32;
  localparam int KEEP_WIDTH      = DATA_WIDTH / 8;
  localparam int USER_WIDTH      = 3;
  localparam int CONTEXT_WIDTH   = 16;
  localparam int TAG_COUNT       = 32;

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

  // ---- host-facing RC AXIS ------------------------------------------------
  logic [AXIS_DATA_WIDTH-1:0] m_axis_rc_tdata;
  logic [AXIS_KEEP_WIDTH-1:0] m_axis_rc_tkeep;
  logic                       m_axis_rc_tvalid;
  logic                       m_axis_rc_tlast;
  logic                       m_axis_rc_tready;

  logic       rc_unexpected_completion_o;
  tlp_error_e rc_completion_error_code;
  logic [4:0] rc_completion_error_code_o;
  logic       rc_protocol_error_o;
  logic [3:0] rc_error_code_o;
  logic       rc_gearbox_error_o;
  assign rc_completion_error_code_o = 5'(rc_completion_error_code);

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

  // ---- RX stream into the Transaction Layer (completion injection) --------
  logic [DATA_WIDTH-1:0] s_dllp_axis_tdata;
  logic [KEEP_WIDTH-1:0] s_dllp_axis_tkeep;
  logic                  s_dllp_axis_tvalid;
  logic                  s_dllp_axis_tlast;
  logic [USER_WIDTH-1:0] s_dllp_axis_tuser;
  logic                  s_dllp_axis_tready;

  // ---- TX stream out of the Transaction Layer -----------------------------
  logic [DATA_WIDTH-1:0] m_dllp_axis_tdata;
  logic [KEEP_WIDTH-1:0] m_dllp_axis_tkeep;
  logic                  m_dllp_axis_tvalid;
  logic                  m_dllp_axis_tlast;
  logic [2:0]            m_dllp_axis_tuser;
  logic                  m_dllp_axis_tready;

  // ---- error / status surface ---------------------------------------------
  logic       command_error_valid_o;
  tlp_error_e command_error_code_o;
  logic [3:0] command_error_code_flat;
  assign command_error_code_flat = 4'(command_error_code_o);

  logic tx_error_valid_o;
  logic malformed_o;
  logic tx_fc_blocked_o;
  logic credit_error_o;
  logic unexpected_completion_o;
  logic       cpl_timeout_valid_o;
  logic [7:0] cpl_timeout_tag_o;
  logic       late_cpl_valid_o;
  logic [7:0] late_cpl_tag_o;
  logic [$clog2(TAG_COUNT+1)-1:0] outstanding_o;

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

  // ---- TL <-> pcie_rc_if received-completion surface ----------------------
  logic                  received_completion_valid;
  logic                  received_completion_ready;
  tlp_header_t           received_completion_header;
  logic [DATA_WIDTH-1:0] received_completion_data;
  logic [KEEP_WIDTH-1:0] received_completion_keep;
  logic                  received_completion_data_valid;
  logic                  received_completion_data_last;
  logic                  received_completion_data_ready;

  logic                     result_valid;
  logic                     result_ready;
  logic [CONTEXT_WIDTH-1:0] result_context;
  logic [2:0]               result_status;
  logic                     result_last;
  tlp_error_e               completion_error_code;

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
      .CONTEXT_WIDTH(CONTEXT_WIDTH),
      .TAG_COUNT    (TAG_COUNT)
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

      .s_dllp_axis_tdata (s_dllp_axis_tdata),
      .s_dllp_axis_tkeep (s_dllp_axis_tkeep),
      .s_dllp_axis_tvalid(s_dllp_axis_tvalid),
      .s_dllp_axis_tlast (s_dllp_axis_tlast),
      .s_dllp_axis_tuser (s_dllp_axis_tuser),
      .s_dllp_axis_tready(s_dllp_axis_tready),

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

      .received_completion_valid_o     (received_completion_valid),
      .received_completion_ready_i     (received_completion_ready),
      .received_completion_header_o    (received_completion_header),
      .received_completion_data_o      (received_completion_data),
      .received_completion_keep_o      (received_completion_keep),
      .received_completion_data_valid_o(received_completion_data_valid),
      .received_completion_data_last_o (received_completion_data_last),
      .received_completion_data_ready_i(received_completion_data_ready),

      .result_valid_o  (result_valid),
      .result_ready_i  (result_ready),
      .result_context_o(result_context),
      .result_status_o (result_status),
      .result_last_o   (result_last),
      .malformed_o(malformed_o),
      .rx_error_valid_o(), .rx_error_code_o(), .rx_ecrc_error_o(),
      .tx_error_valid_o(tx_error_valid_o), .tx_error_code_o(),
      .tx_fc_blocked_o(tx_fc_blocked_o),
      .credit_error_o(credit_error_o),
      .vc_overflow_o(),
      .unexpected_completion_o(unexpected_completion_o),
      .cpl_timeout_valid_o(cpl_timeout_valid_o), .cpl_timeout_tag_o(cpl_timeout_tag_o),
      .late_cpl_valid_o(late_cpl_valid_o), .late_cpl_tag_o(late_cpl_tag_o),
      .completion_error_code_o(completion_error_code),
      .outstanding_o(outstanding_o)
  );

  pcie_rc_if #(
      .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
      .TL_DATA_WIDTH  (DATA_WIDTH),
      .CONTEXT_WIDTH  (CONTEXT_WIDTH)
  ) u_rc (
      .clk_i(clk_i), .rst_i(rst_i),

      .received_completion_valid_i (received_completion_valid),
      .received_completion_ready_o (received_completion_ready),
      .received_completion_header_i(received_completion_header),

      .received_completion_data_i      (received_completion_data),
      .received_completion_keep_i      (received_completion_keep),
      .received_completion_data_valid_i(received_completion_data_valid),
      .received_completion_data_last_i (received_completion_data_last),
      .received_completion_data_ready_o(received_completion_data_ready),

      .result_valid_i         (result_valid),
      .result_ready_o         (result_ready),
      .result_context_i       (result_context),
      .result_status_i        (result_status),
      .result_last_i          (result_last),
      .unexpected_completion_i(unexpected_completion_o),
      .completion_error_code_i(completion_error_code),

      .m_axis_rc_tdata (m_axis_rc_tdata),
      .m_axis_rc_tkeep (m_axis_rc_tkeep),
      .m_axis_rc_tvalid(m_axis_rc_tvalid),
      .m_axis_rc_tlast (m_axis_rc_tlast),
      .m_axis_rc_tready(m_axis_rc_tready),

      .rc_unexpected_completion_o(rc_unexpected_completion_o),
      .rc_completion_error_code_o(rc_completion_error_code),
      .rc_protocol_error_o       (rc_protocol_error_o),
      .rc_error_code_o           (rc_error_code_o),
      .rc_gearbox_error_o        (rc_gearbox_error_o)
  );

endmodule
