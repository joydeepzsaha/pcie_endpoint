// ---------------------------------------------------------------------------
// tb_pcie_enum_bus -- standalone shim for the bridge bus-number phase.
// Stage D increment 3.
//
// The DUT is pcie_enum_bus PLUS one real pcie_cfg_txn wired to it directly --
// the same style as the scan/BAR standalones, which since the 2b-3 hoist also
// put the real primitive behind the stage under test.  Everything beyond the
// primitive's socket (pcie_rq_if, tlp_layer, pcie_rc_if) is absent and the
// Python bench plays it via enum_tb_common.Socket, which asserts its own
// physical-ordering invariants.
//
// pcie_enum_top is NOT instantiated here on purpose: this target owns the
// sequencer's POLICY (the one write, its outcome classification, the handoff
// ordering), not the widened mux -- that is increment 4's integration target.
// The scan-verdict inputs (device_present_i / unsupported_device_i /
// header_type_i) are bench-driven so every branch of the eligibility check is
// reachable without a scan in the loop.
//
// CRS parameters are 3 retries / 8 cycles, the standard shim override: the
// exhaustion test costs ~32 cycles instead of ~1024, and only the
// P-CRS-BUDGET relationship matters (3*8 = 24 < 4096).
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_enum_bus
  import pcie_rq_rc_pkg::*;
  import pcie_enum_pkg::*;
;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32;
  localparam int AXIS_USER_WIDTH = 60;

  localparam int unsigned CRS_RETRY_MAX      = 3;
  localparam int unsigned CRS_BACKOFF_CYCLES = 8;
  localparam int unsigned CPL_TIMEOUT_CYCLES = 4096;

  logic clk_i = 0;
  logic rst_i;

  // ---- control and verdict inputs (bench drives) ---------------------------
  logic       bus_start_i;
  logic       device_present_i;
  logic       unsupported_device_i;
  logic [7:0] header_type_i;
  logic [7:0] bridge_bus_i;
  logic       tx_fc_blocked_i;

  // ---- status surface ------------------------------------------------------
  logic        bus_busy_o;
  logic        bus_done_o;
  logic        bus_bypassed_o;
  logic        bus_error_o;
  enum_error_e bus_error_code;
  logic [3:0]  bus_error_code_o;           // flattened for cocotb
  assign bus_error_code_o = 4'(bus_error_code);
  logic        err_credit_blocked_o;
  logic [7:0]  sec_bus_o;
  logic        bus_type1_o;

  // ---- sequencer <-> primitive, internal -----------------------------------
  logic         cmd_valid;
  logic         cmd_ready;
  logic         cmd_write;
  logic         cmd_type1;
  logic [5:0]   cmd_reg_num;
  logic [3:0]   cmd_ext_reg;
  logic [3:0]   cmd_first_be;
  logic [31:0]  cmd_wdata;
  logic         rsp_valid;
  logic         rsp_ready;
  txn_outcome_e rsp_outcome;
  logic [31:0]  rsp_rdata;

  // The target BDF: the bridge, dev/fn 0 -- what pcie_enum_top wires from the
  // first scan's device_bdf_o while this stage owns the port.
  wire [15:0] bridge_bdf = {bridge_bus_i, 5'd0, 3'd0};

  // ---- socket: Requester Request (bench consumes) --------------------------
  logic [AXIS_DATA_WIDTH-1:0] s_axis_rq_tdata_o;
  logic [AXIS_KEEP_WIDTH-1:0] s_axis_rq_tkeep_o;
  logic                       s_axis_rq_tvalid_o;
  logic                       s_axis_rq_tlast_o;
  logic [AXIS_USER_WIDTH-1:0] s_axis_rq_tuser_o;
  logic                       s_axis_rq_tready_i;

  // ---- socket: core-managed tag (bench drives) -----------------------------
  logic [7:0] pcie_rq_tag_i;
  logic       pcie_rq_tag_vld_i;

  // ---- socket: Requester Completion (bench drives) -------------------------
  logic [AXIS_DATA_WIDTH-1:0] m_axis_rc_tdata_i;
  logic [AXIS_KEEP_WIDTH-1:0] m_axis_rc_tkeep_i;
  logic                       m_axis_rc_tvalid_i;
  logic                       m_axis_rc_tlast_i;
  logic                       m_axis_rc_tready_o;

  // ---- socket: completion timeout sideband (bench drives) ------------------
  logic       cpl_timeout_valid_i;
  logic [7:0] cpl_timeout_tag_i;

  pcie_enum_bus dut (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .bus_start_i         (bus_start_i),
      .device_present_i    (device_present_i),
      .unsupported_device_i(unsupported_device_i),
      .header_type_i       (header_type_i),
      .bridge_bus_i        (bridge_bus_i),

      .bus_busy_o          (bus_busy_o),
      .bus_done_o          (bus_done_o),
      .bus_bypassed_o      (bus_bypassed_o),
      .bus_error_o         (bus_error_o),
      .bus_error_code_o    (bus_error_code),
      .err_credit_blocked_o(err_credit_blocked_o),
      .sec_bus_o           (sec_bus_o),
      .bus_type1_o         (bus_type1_o),

      .tx_fc_blocked_i(tx_fc_blocked_i),

      .cmd_valid_o   (cmd_valid),
      .cmd_ready_i   (cmd_ready),
      .cmd_write_o   (cmd_write),
      .cmd_type1_o   (cmd_type1),
      .cmd_reg_num_o (cmd_reg_num),
      .cmd_ext_reg_o (cmd_ext_reg),
      .cmd_first_be_o(cmd_first_be),
      .cmd_wdata_o   (cmd_wdata),

      .rsp_valid_i  (rsp_valid),
      .rsp_ready_o  (rsp_ready),
      .rsp_outcome_i(rsp_outcome),
      .rsp_rdata_i  (rsp_rdata)
  );

  pcie_cfg_txn #(
      .AXIS_DATA_WIDTH   (AXIS_DATA_WIDTH),
      .AXIS_KEEP_WIDTH   (AXIS_KEEP_WIDTH),
      .AXIS_USER_WIDTH   (AXIS_USER_WIDTH),
      .CRS_RETRY_MAX     (CRS_RETRY_MAX),
      .CRS_BACKOFF_CYCLES(CRS_BACKOFF_CYCLES),
      .CPL_TIMEOUT_CYCLES(CPL_TIMEOUT_CYCLES)
  ) u_txn (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .cmd_valid_i   (cmd_valid),
      .cmd_ready_o   (cmd_ready),
      .cmd_write_i   (cmd_write),
      .cmd_type1_i   (cmd_type1),
      .cmd_bdf_i     (bridge_bdf),
      .cmd_reg_num_i (cmd_reg_num),
      .cmd_ext_reg_i (cmd_ext_reg),
      .cmd_first_be_i(cmd_first_be),
      .cmd_wdata_i   (cmd_wdata),

      .rsp_valid_o     (rsp_valid),
      .rsp_ready_i     (rsp_ready),
      .rsp_outcome_o   (rsp_outcome),
      .rsp_rdata_o     (rsp_rdata),
      .rsp_status_raw_o(),
      .crs_retries_o   (),

      .s_axis_rq_tdata_o (s_axis_rq_tdata_o),
      .s_axis_rq_tkeep_o (s_axis_rq_tkeep_o),
      .s_axis_rq_tvalid_o(s_axis_rq_tvalid_o),
      .s_axis_rq_tlast_o (s_axis_rq_tlast_o),
      .s_axis_rq_tuser_o (s_axis_rq_tuser_o),
      .s_axis_rq_tready_i(s_axis_rq_tready_i),

      .pcie_rq_tag_i    (pcie_rq_tag_i),
      .pcie_rq_tag_vld_i(pcie_rq_tag_vld_i),

      .m_axis_rc_tdata_i (m_axis_rc_tdata_i),
      .m_axis_rc_tkeep_i (m_axis_rc_tkeep_i),
      .m_axis_rc_tvalid_i(m_axis_rc_tvalid_i),
      .m_axis_rc_tlast_i (m_axis_rc_tlast_i),
      .m_axis_rc_tready_o(m_axis_rc_tready_o),

      .cpl_timeout_valid_i(cpl_timeout_valid_i),
      .cpl_timeout_tag_i  (cpl_timeout_tag_i)
  );

endmodule
