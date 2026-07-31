// ---------------------------------------------------------------------------
// tb_pcie_enum_txn -- standalone shim for pcie_cfg_txn (Commit 2b-1).
//
// The DUT is the transaction primitive ALONE. Everything on the other side of
// its socket -- pcie_rq_if, tlp_layer, pcie_rc_if -- is absent, and the Python
// bench plays that socket itself: it consumes RQ beats, strobes the core-managed
// tag with a settable post-accept delay, drives RC descriptors, and fires the
// completion-timeout sideband.
//
// !! THE SOCKET MODEL IS BENCH CODE THAT BEHAVES LIKE RTL, AND THAT IS THE RISK.
//
// A socket model that is too POLITE hides exactly the bugs this target exists to
// catch: one that strobes the tag at command-accept time, or never lowers
// tready, will happily pass a DUT that cannot work against the real thing. The
// four seeded mutations SM-1..SM-4 (SPEC_PREDICTIONS_ENUM.md SS7) are the
// acceptance gate for the model itself -- each must fail at least one test here
// before this target is trusted. See test_pcie_enum_txn.py, SS THE SOCKET MODEL.
//
// CRS parameters are overridden to 3 retries / 8 cycles rather than the shipped
// 16 / 64. The exhaustion test then costs ~32 cycles instead of ~1024, and
// nothing in the retry logic is sensitive to the values -- only to their
// relationship, P-CRS-BUDGET, which 3*8=24 < 4096 still satisfies. The shipped
// defaults are exercised by the elaboration check in pcie_cfg_txn and are
// documented in pcie_enum_pkg.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_enum_txn
  import pcie_rq_rc_pkg::*;
  import pcie_enum_pkg::*;
;

  localparam int AXIS_DATA_WIDTH = 128;
  localparam int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32;
  localparam int AXIS_USER_WIDTH = 60;

  localparam int unsigned CRS_RETRY_MAX      = 3;
  localparam int unsigned CRS_BACKOFF_CYCLES = 8;
  localparam int unsigned CPL_TIMEOUT_CYCLES = 4096;

  localparam int CRS_CNT_W = $clog2(CRS_RETRY_MAX + 1);

  logic clk_i = 0;
  logic rst_i;

  // ---- command port --------------------------------------------------------
  logic        cmd_valid_i;
  logic        cmd_ready_o;
  logic        cmd_write_i;
  logic        cmd_type1_i;
  logic [15:0] cmd_bdf_i;
  logic [5:0]  cmd_reg_num_i;
  logic [3:0]  cmd_ext_reg_i;
  logic [3:0]  cmd_first_be_i;
  logic [31:0] cmd_wdata_i;

  // ---- response port -------------------------------------------------------
  logic         rsp_valid_o;
  logic         rsp_ready_i;
  txn_outcome_e rsp_outcome;
  logic [2:0]   rsp_outcome_o;          // flattened for cocotb
  assign rsp_outcome_o = 3'(rsp_outcome);
  logic [31:0]  rsp_rdata_o;
  logic [2:0]   rsp_status_raw_o;
  logic [CRS_CNT_W-1:0] crs_retries_o;

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

  pcie_cfg_txn #(
      .AXIS_DATA_WIDTH   (AXIS_DATA_WIDTH),
      .AXIS_KEEP_WIDTH   (AXIS_KEEP_WIDTH),
      .AXIS_USER_WIDTH   (AXIS_USER_WIDTH),
      .CRS_RETRY_MAX     (CRS_RETRY_MAX),
      .CRS_BACKOFF_CYCLES(CRS_BACKOFF_CYCLES),
      .CPL_TIMEOUT_CYCLES(CPL_TIMEOUT_CYCLES)
  ) dut (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .cmd_valid_i   (cmd_valid_i),
      .cmd_ready_o   (cmd_ready_o),
      .cmd_write_i   (cmd_write_i),
      .cmd_type1_i   (cmd_type1_i),
      .cmd_bdf_i     (cmd_bdf_i),
      .cmd_reg_num_i (cmd_reg_num_i),
      .cmd_ext_reg_i (cmd_ext_reg_i),
      .cmd_first_be_i(cmd_first_be_i),
      .cmd_wdata_i   (cmd_wdata_i),

      .rsp_valid_o     (rsp_valid_o),
      .rsp_ready_i     (rsp_ready_i),
      .rsp_outcome_o   (rsp_outcome),
      .rsp_rdata_o     (rsp_rdata_o),
      .rsp_status_raw_o(rsp_status_raw_o),
      .crs_retries_o   (crs_retries_o),

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
