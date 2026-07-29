// ---------------------------------------------------------------------------
// pcie_enum_top -- the enumeration assembly. Commit 2b-3.
//
// Wiring only. No policy, no mechanism, no state of its own.
//
//   pcie_enum_top
//   |- pcie_cfg_txn    (ONE instance -- the only tag holder)
//   |- pcie_enum_scan  (presence policy)
//   `- [Commit D] pcie_enum_bar + the static handoff mux
//
// ===========================================================================
// SS WHY THIS MODULE EXISTS
// ===========================================================================
//
// Before 2b-3, pcie_enum_scan instantiated the primitive itself. The BAR phase
// (pcie_enum_bar, Commit D) needs the same primitive, and the alternatives to
// hoisting were both worse -- extending pcie_enum_scan in place breaks the 16
// scan tests that assert no traffic after scan_done_o, and giving pcie_enum_bar
// its own pcie_cfg_txn duplicates the primitive and destroys
// single-outstanding-by-construction. See pcie_enum_scan's header, SS THE HOIST.
//
// So this module exists to own the primitive on behalf of every stage that
// needs it, and to prove that exactly one stage drives it at a time.
//
// ===========================================================================
// SS SINGLE OUTSTANDING, STRUCTURALLY
// ===========================================================================
//
// There is ONE pcie_cfg_txn here and there will never be a second. Table 2-37
// p.137 permits a peer to advertise a single NPH credit, so a second config
// request could not be transmitted anyway (pcie_cfg_txn's header). Holding one
// instance makes that a property of the netlist rather than of an FSM's good
// behaviour.
//
// ===========================================================================
// SS THE HANDOFF -- DIRECT TODAY, MUXED IN COMMIT D
// ===========================================================================
//
// !! COMMIT B (this commit) WIRES pcie_enum_scan STRAIGHT TO THE PRIMITIVE.
// There is nothing to hand off to yet: pcie_enum_bar does not exist. The mux
// arrives in COMMIT D, where it becomes:
//
//     scan owns the command port until scan_done_o, then bar owns it
//
// and it is STATIC, not arbitrated -- exactly one stage is live at a time, and
// a Commit-D mutation ("the mux allows both stages to drive the command port")
// must be killed by a test proving so. Wiring it as a direct connection now
// keeps this commit behaviour-neutral, which is the whole point of doing the
// hoist as its own step.
//
// ===========================================================================
// SS THE BDF IS NOT PART OF THE MUXED PORT
// ===========================================================================
//
// cmd_bdf_i is driven from pcie_enum_scan's device_bdf_o for EVERY stage, not
// selected per phase. The target BDF is a property of the device being
// enumerated, not of the phase enumerating it -- the BAR phase configures the
// same Function the scan found. Muxing it would invite the two stages to
// disagree about which device they are talking to.
//
// This also preserves the pre-hoist wiring exactly: pcie_enum_scan used to
// connect cmd_bdf_i to its own device_bdf_o at its instantiation of the
// primitive.
//
// ===========================================================================
// SS WHAT THIS MODULE DELIBERATELY DOES NOT DO
// ===========================================================================
//
// It does not observe pcie_rq_tag_o, decode a completion status, run a timer or
// gate anything on credit. Those belong to the primitive, the tracker and the
// stages respectively. It forwards the pcie_rq_rc_top socket verbatim.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_enum_top
  import pcie_rq_rc_pkg::*;
  import pcie_enum_pkg::*;
#(
    parameter int AXIS_DATA_WIDTH = 128,
    parameter int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32,
    parameter int AXIS_USER_WIDTH = 60,
    parameter int unsigned CRS_RETRY_MAX      = CRS_RETRY_MAX_DEFAULT,
    parameter int unsigned CRS_BACKOFF_CYCLES = CRS_BACKOFF_CYCLES_DEFAULT,
    parameter int unsigned CPL_TIMEOUT_CYCLES = 32'd4096
) (
    input  logic                        clk_i,
    input  logic                        rst_i,

    // ---- control -----------------------------------------------------------
    input  logic                        scan_start_i,
    input  logic [7:0]                  scan_bus_i,

    // ---- status surface ----------------------------------------------------
    output logic                        scan_busy_o,
    output logic                        scan_done_o,
    output logic                        scan_error_o,
    output enum_error_e                 scan_error_code_o,
    output logic                        err_credit_blocked_o,

    output logic                        device_present_o,
    output logic                        unsupported_device_o,
    output logic [15:0]                 device_bdf_o,
    output logic [15:0]                 vendor_id_o,
    output logic [15:0]                 device_id_o,
    output logic [7:0]                  header_type_o,
    output logic                        multifunction_o,

    // ---- annotation input (NOT control flow) -------------------------------
    input  logic                        tx_fc_blocked_i,

    // ---- pcie_rq_rc_top socket: Requester Request --------------------------
    output logic [AXIS_DATA_WIDTH-1:0]  s_axis_rq_tdata_o,
    output logic [AXIS_KEEP_WIDTH-1:0]  s_axis_rq_tkeep_o,
    output logic                        s_axis_rq_tvalid_o,
    output logic                        s_axis_rq_tlast_o,
    output logic [AXIS_USER_WIDTH-1:0]  s_axis_rq_tuser_o,
    input  logic                        s_axis_rq_tready_i,

    // ---- pcie_rq_rc_top socket: core-managed tag ---------------------------
    input  logic [7:0]                  pcie_rq_tag_i,
    input  logic                        pcie_rq_tag_vld_i,

    // ---- pcie_rq_rc_top socket: Requester Completion -----------------------
    input  logic [AXIS_DATA_WIDTH-1:0]  m_axis_rc_tdata_i,
    input  logic [AXIS_KEEP_WIDTH-1:0]  m_axis_rc_tkeep_i,
    input  logic                        m_axis_rc_tvalid_i,
    input  logic                        m_axis_rc_tlast_i,
    output logic                        m_axis_rc_tready_o,

    // ---- pcie_rq_rc_top socket: completion timeout sideband ----------------
    input  logic                        cpl_timeout_valid_i,
    input  logic [7:0]                  cpl_timeout_tag_i
);

  // -------------------------------------------------------------------------
  // The shared command/response bus between the stages and the primitive.
  // -------------------------------------------------------------------------
  logic         cmd_valid;
  logic         cmd_ready;
  logic         cmd_write;
  logic [5:0]   cmd_reg_num;
  logic [3:0]   cmd_ext_reg;
  logic [3:0]   cmd_first_be;
  logic [31:0]  cmd_wdata;

  logic         rsp_valid;
  logic         rsp_ready;
  txn_outcome_e rsp_outcome;
  logic [31:0]  rsp_rdata;

  // -------------------------------------------------------------------------
  // Presence phase.
  // -------------------------------------------------------------------------
  pcie_enum_scan u_scan (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .scan_start_i(scan_start_i),
      .scan_bus_i  (scan_bus_i),

      .scan_busy_o         (scan_busy_o),
      .scan_done_o         (scan_done_o),
      .scan_error_o        (scan_error_o),
      .scan_error_code_o   (scan_error_code_o),
      .err_credit_blocked_o(err_credit_blocked_o),

      .device_present_o    (device_present_o),
      .unsupported_device_o(unsupported_device_o),
      .device_bdf_o        (device_bdf_o),
      .vendor_id_o         (vendor_id_o),
      .device_id_o         (device_id_o),
      .header_type_o       (header_type_o),
      .multifunction_o     (multifunction_o),

      .tx_fc_blocked_i(tx_fc_blocked_i),

      .cmd_valid_o   (cmd_valid),
      .cmd_ready_i   (cmd_ready),
      .cmd_write_o   (cmd_write),
      .cmd_reg_num_o (cmd_reg_num),
      .cmd_ext_reg_o (cmd_ext_reg),
      .cmd_first_be_o(cmd_first_be),
      .cmd_wdata_o   (cmd_wdata),

      .rsp_valid_i  (rsp_valid),
      .rsp_ready_o  (rsp_ready),
      .rsp_outcome_i(rsp_outcome),
      .rsp_rdata_i  (rsp_rdata)
  );

  // -------------------------------------------------------------------------
  // COMMIT D: pcie_enum_bar is instantiated here, and the seven cmd_* signals
  // plus rsp_ready above become the outputs of the static handoff mux rather
  // than a direct connection from u_scan. Until then there is exactly one
  // driver, so the mux would be an identity function.
  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // The one transaction primitive.
  // -------------------------------------------------------------------------
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
      // Not muxed -- see SS THE BDF IS NOT PART OF THE MUXED PORT.
      .cmd_bdf_i     (device_bdf_o),
      .cmd_reg_num_i (cmd_reg_num),
      .cmd_ext_reg_i (cmd_ext_reg),
      .cmd_first_be_i(cmd_first_be),
      .cmd_wdata_i   (cmd_wdata),

      .rsp_valid_o     (rsp_valid),
      .rsp_ready_i     (rsp_ready),
      .rsp_outcome_o   (rsp_outcome),
      .rsp_rdata_o     (rsp_rdata),
      // Deliberately unused: the raw completion status and the CRS retry count
      // are the primitive's business. The stages act on the classified outcome
      // only -- re-decoding status up here would duplicate policy.
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
