// ---------------------------------------------------------------------------
// tb_pcie_rq_if -- cocotb shim for the standalone pcie_rq_if unit tests (T1..T11).
//
// No Transaction Layer in the loop: the bench plays the role of tlp_requester's
// command port directly, so no FC-credit initialisation is needed here (that
// starts at the verilate_rq_if_tlp target, where tlp_layer gates every TX
// packet on the credit manager -- see test_pcie_rq_if_tlp.py).
//
// The shim exists to pin the parameterisation and give the bench stable
// top-level signal names; pcie_rq_if has no struct ports, so nothing needs
// flattening.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_rq_if;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32;   // DW-granular (PG213)
  localparam int AXIS_USER_WIDTH = 60;

  logic clk_i = 0;
  logic rst_i;

  logic [AXIS_DATA_WIDTH-1:0] s_axis_rq_tdata;
  logic [AXIS_KEEP_WIDTH-1:0] s_axis_rq_tkeep;
  logic                       s_axis_rq_tvalid;
  logic                       s_axis_rq_tlast;
  logic [AXIS_USER_WIDTH-1:0] s_axis_rq_tuser;
  logic                       s_axis_rq_tready;

  logic [7:0] rq_tag_i;
  logic [7:0] pcie_rq_tag_o;
  logic       pcie_rq_tag_vld_o;

  logic        command_valid_o;
  logic        command_ready_i;
  logic [2:0]  command_o;
  logic [63:0] command_address_o;
  logic [12:0] command_byte_count_o;
  logic [2:0]  command_tc_o;
  logic [2:0]  command_attr_o;
  logic [15:0] command_context_o;
  logic        command_prefix_valid_o;
  logic [31:0] command_prefix_o;
  logic        command_ecrc_enable_o;

  logic [31:0] command_data_o;
  logic [3:0]  command_keep_o;
  logic        command_data_valid_o;
  logic        command_data_last_o;
  logic        command_data_ready_i;

  logic       rq_protocol_error_o;
  logic [3:0] rq_error_code_o;
  logic       rq_gearbox_error_o;

  pcie_rq_if #(
      .AXIS_DATA_WIDTH(AXIS_DATA_WIDTH),
      .AXIS_USER_WIDTH(AXIS_USER_WIDTH)
  ) dut (
      .clk_i(clk_i), .rst_i(rst_i),

      .s_axis_rq_tdata (s_axis_rq_tdata),
      .s_axis_rq_tkeep (s_axis_rq_tkeep),
      .s_axis_rq_tvalid(s_axis_rq_tvalid),
      .s_axis_rq_tlast (s_axis_rq_tlast),
      .s_axis_rq_tuser (s_axis_rq_tuser),
      .s_axis_rq_tready(s_axis_rq_tready),

      .rq_tag_i         (rq_tag_i),
      .pcie_rq_tag_o    (pcie_rq_tag_o),
      .pcie_rq_tag_vld_o(pcie_rq_tag_vld_o),

      .command_valid_o       (command_valid_o),
      .command_ready_i       (command_ready_i),
      .command_o             (command_o),
      .command_address_o     (command_address_o),
      .command_byte_count_o  (command_byte_count_o),
      .command_tc_o          (command_tc_o),
      .command_attr_o        (command_attr_o),
      .command_context_o     (command_context_o),
      .command_prefix_valid_o(command_prefix_valid_o),
      .command_prefix_o      (command_prefix_o),
      .command_ecrc_enable_o (command_ecrc_enable_o),

      .command_data_o      (command_data_o),
      .command_keep_o      (command_keep_o),
      .command_data_valid_o(command_data_valid_o),
      .command_data_last_o (command_data_last_o),
      .command_data_ready_i(command_data_ready_i),

      .rq_protocol_error_o(rq_protocol_error_o),
      .rq_error_code_o    (rq_error_code_o),
      .rq_gearbox_error_o (rq_gearbox_error_o)
  );

endmodule
