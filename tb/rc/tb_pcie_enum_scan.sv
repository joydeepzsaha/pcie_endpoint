// ---------------------------------------------------------------------------
// tb_pcie_enum_scan -- standalone shim for pcie_enum_scan (Commit 2b-2).
//
// The DUT is the sequencer AND the one pcie_cfg_txn it instantiates; everything
// beyond their shared socket is absent, and the Python bench plays it (see
// enum_tb_common.Socket, which asserts its own ordering invariants).
//
// CRS parameters are overridden to 3 / 8 rather than the shipped 16 / 64 so the
// exhaustion path costs tens of cycles; P-CRS-BUDGET still holds with room
// (3*8 = 24 against CPL_TIMEOUT_CYCLES = 4096).
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_enum_scan
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

  // ---- control -------------------------------------------------------------
  logic       scan_start_i;
  logic [7:0] scan_bus_i;
  logic       tx_fc_blocked_i;

  // ---- status surface, enums flattened for cocotb --------------------------
  logic        scan_busy_o;
  logic        scan_done_o;
  logic        scan_error_o;
  enum_error_e scan_error_code;
  logic [2:0]  scan_error_code_o;
  assign scan_error_code_o = 3'(scan_error_code);
  logic        err_credit_blocked_o;

  logic        device_present_o;
  logic        unsupported_device_o;
  logic [15:0] device_bdf_o;
  logic [15:0] vendor_id_o;
  logic [15:0] device_id_o;
  logic [7:0]  header_type_o;
  logic        multifunction_o;

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

  pcie_enum_scan #(
      .AXIS_DATA_WIDTH   (AXIS_DATA_WIDTH),
      .AXIS_KEEP_WIDTH   (AXIS_KEEP_WIDTH),
      .AXIS_USER_WIDTH   (AXIS_USER_WIDTH),
      .CRS_RETRY_MAX     (CRS_RETRY_MAX),
      .CRS_BACKOFF_CYCLES(CRS_BACKOFF_CYCLES),
      .CPL_TIMEOUT_CYCLES(CPL_TIMEOUT_CYCLES)
  ) dut (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .scan_start_i(scan_start_i),
      .scan_bus_i  (scan_bus_i),

      .scan_busy_o         (scan_busy_o),
      .scan_done_o         (scan_done_o),
      .scan_error_o        (scan_error_o),
      .scan_error_code_o   (scan_error_code),
      .err_credit_blocked_o(err_credit_blocked_o),

      .device_present_o    (device_present_o),
      .unsupported_device_o(unsupported_device_o),
      .device_bdf_o        (device_bdf_o),
      .vendor_id_o         (vendor_id_o),
      .device_id_o         (device_id_o),
      .header_type_o       (header_type_o),
      .multifunction_o     (multifunction_o),

      .tx_fc_blocked_i(tx_fc_blocked_i),

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
