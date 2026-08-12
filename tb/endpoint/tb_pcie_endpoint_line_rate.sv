`timescale 1ns/1ps

module tb_pcie_endpoint_line_rate #(
    parameter int LANE_COUNT = 1
);
  import tlp_pkg::*;

  localparam int DATA_WIDTH = 32;
  localparam int KEEP_WIDTH = 4;
  localparam int USER_WIDTH = 3;
  localparam int CONTEXT_WIDTH = 16;
  localparam int TLP_HEADER_WIDTH = $bits(tlp_header_t);

  logic clk_i;
  logic rst_i;
  logic phy_link_up_i;
  logic idle_valid_i;
  logic transmit_enable_i;

  logic [31:0] s_phy_axis_tdata;
  logic [3:0] s_phy_axis_tkeep;
  logic s_phy_axis_tvalid;
  logic s_phy_axis_tlast;
  logic [2:0] s_phy_axis_tuser;
  logic s_phy_axis_tready;
  logic [31:0] m_phy_axis_tdata;
  logic [3:0] m_phy_axis_tkeep;
  logic m_phy_axis_tvalid;
  logic m_phy_axis_tlast;
  logic [2:0] m_phy_axis_tuser;
  logic m_phy_axis_tready;

  logic [LANE_COUNT*10-1:0] rx_symbol_data_i;
  logic [LANE_COUNT-1:0] rx_symbol_keep_i;
  logic rx_symbol_valid_i;
  logic rx_symbol_sop_i;
  logic rx_symbol_eop_i;
  logic [2:0] rx_symbol_user_i;
  logic rx_symbol_ready_o;
  logic [LANE_COUNT*10-1:0] tx_symbol_data_o;
  logic [LANE_COUNT-1:0] tx_symbol_keep_o;
  logic tx_symbol_valid_o;
  logic tx_symbol_sop_o;
  logic tx_symbol_eop_o;
  logic [2:0] tx_symbol_user_o;
  logic tx_symbol_ready_i;

  logic [63:0] tx_symbol_count_o;
  logic [63:0] tx_payload_byte_count_o;
  logic [63:0] tx_active_cycle_count_o;
  logic [63:0] rx_symbol_count_o;
  logic [63:0] rx_payload_byte_count_o;
  logic [63:0] rx_active_cycle_count_o;
  logic [LANE_COUNT-1:0] rx_code_error_o;
  logic [LANE_COUNT-1:0] rx_disparity_error_o;
  wire [7:0] logical_lane_count_o = LANE_COUNT;

  logic memory_enable_i;
  logic extended_tag_enable_i;
  logic [12:0] max_payload_bytes_i;
  logic [12:0] max_read_bytes_i;
  logic rcb_128b_i;

  logic command_valid_i;
  logic command_ready_o;
  tlp_cmd_e command_i;
  logic [63:0] command_address_i;
  logic [12:0] command_byte_count_i;
  logic [2:0] command_tc_i;
  logic [2:0] command_attr_i;
  logic [2:0] command_message_route_i;
  logic [7:0] command_message_code_i;
  logic [15:0] command_context_i;
  logic command_prefix_valid_i;
  logic [31:0] command_prefix_i;
  logic command_ecrc_enable_i;
  logic [31:0] command_data_i;
  logic [3:0] command_keep_i;
  logic command_data_valid_i;
  logic command_data_last_i;
  logic command_data_ready_o;
  logic command_error_valid_o;
  tlp_error_e command_error_code_o;

  logic target_request_valid_o;
  logic target_request_ready_i;
  wire [TLP_HEADER_WIDTH-1:0] target_request_header_o;
  tlp_class_e target_request_class_o;
  logic target_memory_o;
  logic target_config_o;
  logic target_message_o;
  logic [2:0] target_message_route_o;
  logic [7:0] target_message_code_o;
  logic [63:0] target_message_data_o;
  logic target_config_hit_o;
  logic target_config_type_one_o;
  logic [11:0] target_config_offset_o;
  logic target_read_o;
  logic target_write_o;
  logic target_unsupported_o;
  logic target_bar_hit_o;
  logic target_bar_overlap_o;
  logic target_bar_o;
  logic [63:0] target_offset_o;
  logic [31:0] target_data_o;
  logic [3:0] target_keep_o;
  logic target_data_valid_o;
  logic target_data_last_o;
  logic target_data_ready_i;

  logic completion_request_valid_i;
  logic completion_request_ready_o;
  logic [TLP_HEADER_WIDTH-1:0] completion_request_header_i;
  logic [2:0] completion_request_status_i;
  logic [12:0] completion_request_byte_count_i;
  logic [6:0] completion_request_lower_address_i;
  logic completion_request_ecrc_enable_i;
  logic [31:0] completion_request_data_i;
  logic [3:0] completion_request_keep_i;
  logic completion_request_data_valid_i;
  logic completion_request_data_last_i;
  logic completion_request_data_ready_o;

  logic received_completion_valid_o;
  logic received_completion_ready_i;
  wire [TLP_HEADER_WIDTH-1:0] received_completion_header_o;
  logic [31:0] received_completion_data_o;
  logic [3:0] received_completion_keep_o;
  logic received_completion_data_valid_o;
  logic received_completion_data_last_o;
  logic received_completion_data_ready_i;
  logic result_valid_o;
  logic result_ready_i;
  logic [15:0] result_context_o;
  logic [2:0] result_status_o;
  logic result_last_o;

  logic [7:0] cfg_bus_number_o;
  logic [4:0] cfg_device_number_o;
  logic [2:0] cfg_function_number_o;
  logic fc_initialized_o;
  logic fc_update_valid_o;
  logic [7:0] fc_ph_o;
  logic [11:0] fc_pd_o;
  logic [7:0] fc_nph_o;
  logic [11:0] fc_npd_o;
  logic [7:0] fc_cplh_o;
  logic [11:0] fc_cpld_o;
  logic malformed_o;
  logic rx_error_valid_o;
  tlp_error_e rx_error_code_o;
  logic rx_ecrc_error_o;
  logic tx_error_valid_o;
  tlp_error_e tx_error_code_o;
  logic tx_fc_blocked_o;
  logic credit_error_o;
  logic vc_overflow_o;
  logic unexpected_completion_o;
  tlp_error_e completion_error_code_o;
  logic [5:0] outstanding_o;

  tlp_header_t completion_request_header_s;
  tlp_header_t target_request_header_s;
  tlp_header_t received_completion_header_s;

  assign completion_request_header_s = tlp_header_t'(completion_request_header_i);
  assign target_request_header_o = target_request_header_s;
  assign received_completion_header_o = received_completion_header_s;

  // Layer-boundary monitors used by the Python scoreboard.
  wire [31:0] mid_tx_axis_tdata = dut.tlp_to_dll_tdata;
  wire [3:0] mid_tx_axis_tkeep = dut.tlp_to_dll_tkeep;
  wire mid_tx_axis_tvalid = dut.tlp_to_dll_tvalid;
  wire mid_tx_axis_tlast = dut.tlp_to_dll_tlast;
  wire [2:0] mid_tx_axis_tuser = dut.tlp_to_dll_tuser;
  wire mid_tx_axis_tready = dut.tlp_to_dll_tready;
  wire [31:0] mid_rx_axis_tdata = dut.dll_to_tlp_tdata;
  wire [3:0] mid_rx_axis_tkeep = dut.dll_to_tlp_tkeep;
  wire mid_rx_axis_tvalid = dut.dll_to_tlp_tvalid;
  wire mid_rx_axis_tlast = dut.dll_to_tlp_tlast;
  wire [2:0] mid_rx_axis_tuser = dut.dll_to_tlp_tuser;
  wire mid_rx_axis_tready = dut.dll_to_tlp_tready;

  // RX diagnostic boundary immediately after sequence/LCRC processing and
  // before the configuration-space routing wrapper.  This distinguishes a
  // DLL rejection from a later configuration-mux or TLP-parser rejection.
  wire [31:0] post_dll_axis_tdata =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tdata;
  wire [3:0] post_dll_axis_tkeep =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tkeep;
  wire post_dll_axis_tvalid =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tvalid;
  wire post_dll_axis_tlast =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tlast;
  wire [2:0] post_dll_axis_tuser =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tuser;
  wire post_dll_axis_tready =
      dut.datalink_layer_inst.dllp_receive_inst.tlp_to_mac_tready;

  // State/status aliases are intentionally exposed only by the verification
  // top.  They make an RX timeout identify its first failing protocol layer.
  wire [4:0] dll_rx_state =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.curr_state;
  wire [11:0] dll_received_sequence =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.next_transmit_seq_r;
  wire [11:0] dll_expected_sequence =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.next_expected_seq_num_r;
  wire dll_rx_nullified =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.tlp_nullified_r;
  wire dll_response_is_nak =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.response_is_nak_r;
  wire dll_nak_scheduled =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.nak_scheduled_r;
  wire dll_lcrc_match =
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.lcrc32d32 ==
      dut.datalink_layer_inst.dllp_receive_inst.dllp2tlp_inst.crc_from_tlp_r;
  wire [3:0] parser_state = dut.tlp_layer_inst.parser_inst.state_r;
  wire parser_header_valid = dut.tlp_layer_inst.parsed_header_valid;
  wire parser_header_legal = dut.tlp_layer_inst.parser_inst.header_legal;
  wire parser_packet_ended = dut.tlp_layer_inst.parser_inst.packet_ended_r;
  wire parser_classified_completion = dut.tlp_layer_inst.parsed_completion;

  wire [2:0] target_header_fmt = target_request_header_s.fmt;
  wire [4:0] target_header_type = target_request_header_s.tlp_type;
  wire [10:0] target_header_length = target_request_header_s.length_dw;
  wire [63:0] target_header_address = target_request_header_s.address;
  wire [15:0] target_header_requester_id = target_request_header_s.requester_id;
  wire [7:0] target_header_tag = target_request_header_s.tag;
  wire [7:0] target_header_message_code = target_request_header_s.message_code;
  wire [2:0] received_header_fmt = received_completion_header_s.fmt;
  wire [4:0] received_header_type = received_completion_header_s.tlp_type;
  wire [15:0] received_header_requester_id = received_completion_header_s.requester_id;
  wire [15:0] received_header_completer_id = received_completion_header_s.completer_id;
  wire [7:0] received_header_tag = received_completion_header_s.tag;
  wire [2:0] received_header_status = received_completion_header_s.completion_status;
  wire [12:0] received_header_byte_count = received_completion_header_s.byte_count;
  wire [6:0] received_header_lower_address = received_completion_header_s.lower_address;

  pcie_gen1_logical_phy_model #(
      .LANE_COUNT(LANE_COUNT),
      .USER_WIDTH(USER_WIDTH)
  ) logical_phy (
      .clk_i(clk_i),
      .rst_i(rst_i),
      .s_axis_tdata(m_phy_axis_tdata),
      .s_axis_tkeep(m_phy_axis_tkeep),
      .s_axis_tvalid(m_phy_axis_tvalid),
      .s_axis_tlast(m_phy_axis_tlast),
      .s_axis_tuser(m_phy_axis_tuser),
      .s_axis_tready(m_phy_axis_tready),
      .tx_symbol_data_o(tx_symbol_data_o),
      .tx_symbol_keep_o(tx_symbol_keep_o),
      .tx_symbol_valid_o(tx_symbol_valid_o),
      .tx_symbol_sop_o(tx_symbol_sop_o),
      .tx_symbol_eop_o(tx_symbol_eop_o),
      .tx_symbol_user_o(tx_symbol_user_o),
      .tx_symbol_ready_i(tx_symbol_ready_i),
      .rx_symbol_data_i(rx_symbol_data_i),
      .rx_symbol_keep_i(rx_symbol_keep_i),
      .rx_symbol_valid_i(rx_symbol_valid_i),
      .rx_symbol_sop_i(rx_symbol_sop_i),
      .rx_symbol_eop_i(rx_symbol_eop_i),
      .rx_symbol_user_i(rx_symbol_user_i),
      .rx_symbol_ready_o(rx_symbol_ready_o),
      .m_axis_tdata(s_phy_axis_tdata),
      .m_axis_tkeep(s_phy_axis_tkeep),
      .m_axis_tvalid(s_phy_axis_tvalid),
      .m_axis_tlast(s_phy_axis_tlast),
      .m_axis_tuser(s_phy_axis_tuser),
      .m_axis_tready(s_phy_axis_tready),
      .tx_symbol_count_o(tx_symbol_count_o),
      .tx_payload_byte_count_o(tx_payload_byte_count_o),
      .tx_active_cycle_count_o(tx_active_cycle_count_o),
      .rx_symbol_count_o(rx_symbol_count_o),
      .rx_payload_byte_count_o(rx_payload_byte_count_o),
      .rx_active_cycle_count_o(rx_active_cycle_count_o),
      .rx_code_error_o(rx_code_error_o),
      .rx_disparity_error_o(rx_disparity_error_o)
  );

  pcie_endpoint_top #(
      .DATA_WIDTH(DATA_WIDTH),
      .KEEP_WIDTH(KEEP_WIDTH),
      .USER_WIDTH(USER_WIDTH),
      .CONTEXT_WIDTH(CONTEXT_WIDTH),
      .BAR_COUNT(1),
      .BAR_BASE(64'h0000_0000_0000_0000),
      .BAR_MASK(64'hffff_ffff_ffff_f000),
      .BAR_ENABLE(1'b1),
      .REPLAY_TIMER_CYCLES(4096),
      .MAX_REPLAY_ATTEMPTS(3)
  ) dut (
      .completion_request_header_i(completion_request_header_s),
      .target_request_header_o(target_request_header_s),
      .received_completion_header_o(received_completion_header_s),
      .*
  );

endmodule
