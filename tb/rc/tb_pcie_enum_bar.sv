// ---------------------------------------------------------------------------
// tb_pcie_enum_bar -- standalone shim for the BAR phase (Commit 2b-3).
//
// The DUT is the WHOLE enumeration assembly -- pcie_enum_scan, pcie_enum_bar,
// the one pcie_cfg_txn and the REAL static handoff mux -- with everything
// beyond their shared pcie_rq_rc_top socket absent. The Python bench plays that
// socket (enum_tb_common.Socket, which asserts its own ordering invariants).
//
// !! THE MUX IS THE REAL ONE, NOT A BENCH SUBSTITUTE. That is the point of
// pointing the shim at pcie_enum_top rather than at pcie_enum_bar: the handoff
// from scan to bar is part of what this target tests, and the transaction
// sequence a test observes therefore begins with the two scan transactions.
//
// bar_enable_i is HIGH here and low in the two scan shims. See pcie_enum_top,
// SS WHY THE BAR PHASE NEEDS AN ENABLE.
//
// CRS parameters are overridden to 3 / 8 rather than the shipped 16 / 64 so the
// exhaustion path costs tens of cycles; P-CRS-BUDGET still holds with room
// (3*8 = 24 against CPL_TIMEOUT_CYCLES = 4096).
//
// MEM_BAR_BASE / MEM_BAR_WINDOW are left at their SHIPPED defaults, so the
// addresses this target asserts are the ones SPEC_PREDICTIONS_ENUM.md SSE.7.4
// pinned before the RTL existed. Two tests need a different allocator geometry
// -- exhaustion, and a 32-bit BAR that cannot be named in 32 bits -- and they
// get their own top-level instances below rather than a parameter the other
// tests would have to reason about.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_enum_bar
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
  logic       bar_enable_i;
  logic       tx_fc_blocked_i;

  // ---- presence-phase status, enums flattened for cocotb -------------------
  logic        scan_busy_o;
  logic        scan_done_o;
  logic        scan_error_o;
  enum_error_e scan_error_code;
  logic [3:0]  scan_error_code_o;
  assign scan_error_code_o = 4'(scan_error_code);
  logic        err_credit_blocked_o;

  logic        device_present_o;
  logic        unsupported_device_o;
  logic [15:0] device_bdf_o;
  logic [15:0] vendor_id_o;
  logic [15:0] device_id_o;
  logic [7:0]  header_type_o;
  logic        multifunction_o;

  // ---- BAR-phase status ----------------------------------------------------
  logic        bar_busy_o;
  logic        enum_done_o;
  logic        enum_error_o;
  enum_error_e enum_error_code;
  logic [3:0]  enum_error_code_o;
  assign enum_error_code_o = 4'(enum_error_code);

  logic [3:0]              bar_count_o;
  logic [BAR_SLOTS-1:0]    bar_valid_o;
  logic [BAR_SLOTS-1:0]    bar_is_64_o;
  logic [BAR_SLOTS-1:0]    bar_prefetch_o;
  logic [BAR_SLOTS*64-1:0] bar_size_o;
  logic [BAR_SLOTS*64-1:0] bar_addr_o;
  logic [BAR_SLOTS-1:0]    io_bar_mask_o;

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

  pcie_enum_top #(
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
      .bar_enable_i(bar_enable_i),

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

      .bar_busy_o       (bar_busy_o),
      .enum_done_o      (enum_done_o),
      .enum_error_o     (enum_error_o),
      .enum_error_code_o(enum_error_code),

      .bar_count_o   (bar_count_o),
      .bar_valid_o   (bar_valid_o),
      .bar_is_64_o   (bar_is_64_o),
      .bar_prefetch_o(bar_prefetch_o),
      .bar_size_o    (bar_size_o),
      .bar_addr_o    (bar_addr_o),
      .io_bar_mask_o (io_bar_mask_o),

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

  // ===========================================================================
  // SS TWO ALLOCATOR GEOMETRIES THE DEFAULT CANNOT REACH
  //
  // Both faults below are properties of MEM_BAR_BASE / MEM_BAR_WINDOW, not of
  // any device, so they are unreachable at the shipped defaults no matter what
  // the completer answers. Rather than parameterise the main instance -- which
  // would make every OTHER test's golden addresses depend on a knob -- each gets
  // its own small instance driven from its own socket.
  //
  // Each exposes the FULL BAR status surface. A first pass exposed only what
  // each test was expected to assert; status() in the Python bench reads the
  // whole surface, so those tests died on a missing signal rather than on a DUT
  // property. Trimming a status surface to a prediction is the same mistake as
  // trimming an assertion to one.
  // ===========================================================================

  // ---- exhaustion: a window far too small for the device's BARs ------------
  localparam logic [63:0] TINY_BASE   = 64'h0000_0000_8000_0000;
  localparam logic [63:0] TINY_WINDOW = 64'h0000_0000_0000_0100;   // 256 bytes

  logic        x_scan_start_i;
  logic        x_bar_enable_i;
  logic        x_enum_done_o;
  logic        x_enum_error_o;
  enum_error_e x_enum_error_code;
  logic [3:0]  x_enum_error_code_o;
  assign x_enum_error_code_o = 4'(x_enum_error_code);
  logic [3:0]              x_bar_count_o;
  logic [BAR_SLOTS-1:0]    x_bar_valid_o;
  logic [BAR_SLOTS-1:0]    x_bar_is_64_o;
  logic [BAR_SLOTS-1:0]    x_bar_prefetch_o;
  logic [BAR_SLOTS*64-1:0] x_bar_size_o;
  logic [BAR_SLOTS*64-1:0] x_bar_addr_o;
  logic [BAR_SLOTS-1:0]    x_io_bar_mask_o;
  logic                    x_bar_busy_o;
  logic        x_scan_done_o;
  logic        x_device_present_o;

  logic [AXIS_DATA_WIDTH-1:0] x_s_axis_rq_tdata_o;
  logic [AXIS_KEEP_WIDTH-1:0] x_s_axis_rq_tkeep_o;
  logic                       x_s_axis_rq_tvalid_o;
  logic                       x_s_axis_rq_tlast_o;
  logic [AXIS_USER_WIDTH-1:0] x_s_axis_rq_tuser_o;
  logic                       x_s_axis_rq_tready_i;
  logic [7:0]                 x_pcie_rq_tag_i;
  logic                       x_pcie_rq_tag_vld_i;
  logic [AXIS_DATA_WIDTH-1:0] x_m_axis_rc_tdata_i;
  logic [AXIS_KEEP_WIDTH-1:0] x_m_axis_rc_tkeep_i;
  logic                       x_m_axis_rc_tvalid_i;
  logic                       x_m_axis_rc_tlast_i;
  logic                       x_m_axis_rc_tready_o;

  pcie_enum_top #(
      .AXIS_DATA_WIDTH   (AXIS_DATA_WIDTH),
      .AXIS_KEEP_WIDTH   (AXIS_KEEP_WIDTH),
      .AXIS_USER_WIDTH   (AXIS_USER_WIDTH),
      .CRS_RETRY_MAX     (CRS_RETRY_MAX),
      .CRS_BACKOFF_CYCLES(CRS_BACKOFF_CYCLES),
      .CPL_TIMEOUT_CYCLES(CPL_TIMEOUT_CYCLES),
      .MEM_BAR_BASE      (TINY_BASE),
      .MEM_BAR_WINDOW    (TINY_WINDOW)
  ) dut_tiny (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .scan_start_i(x_scan_start_i),
      .scan_bus_i  (scan_bus_i),
      .bar_enable_i(x_bar_enable_i),

      .scan_busy_o         (),
      .scan_done_o         (x_scan_done_o),
      .scan_error_o        (),
      .scan_error_code_o   (),
      .err_credit_blocked_o(),

      .device_present_o    (x_device_present_o),
      .unsupported_device_o(),
      .device_bdf_o        (),
      .vendor_id_o         (),
      .device_id_o         (),
      .header_type_o       (),
      .multifunction_o     (),

      .bar_busy_o       (x_bar_busy_o),
      .enum_done_o      (x_enum_done_o),
      .enum_error_o     (x_enum_error_o),
      .enum_error_code_o(x_enum_error_code),

      .bar_count_o   (x_bar_count_o),
      .bar_valid_o   (x_bar_valid_o),
      .bar_is_64_o   (x_bar_is_64_o),
      .bar_prefetch_o(x_bar_prefetch_o),
      .bar_size_o    (x_bar_size_o),
      .bar_addr_o    (x_bar_addr_o),
      .io_bar_mask_o (x_io_bar_mask_o),

      .tx_fc_blocked_i(1'b0),

      .s_axis_rq_tdata_o (x_s_axis_rq_tdata_o),
      .s_axis_rq_tkeep_o (x_s_axis_rq_tkeep_o),
      .s_axis_rq_tvalid_o(x_s_axis_rq_tvalid_o),
      .s_axis_rq_tlast_o (x_s_axis_rq_tlast_o),
      .s_axis_rq_tuser_o (x_s_axis_rq_tuser_o),
      .s_axis_rq_tready_i(x_s_axis_rq_tready_i),

      .pcie_rq_tag_i    (x_pcie_rq_tag_i),
      .pcie_rq_tag_vld_i(x_pcie_rq_tag_vld_i),

      .m_axis_rc_tdata_i (x_m_axis_rc_tdata_i),
      .m_axis_rc_tkeep_i (x_m_axis_rc_tkeep_i),
      .m_axis_rc_tvalid_i(x_m_axis_rc_tvalid_i),
      .m_axis_rc_tlast_i (x_m_axis_rc_tlast_i),
      .m_axis_rc_tready_o(x_m_axis_rc_tready_o),

      .cpl_timeout_valid_i(1'b0),
      .cpl_timeout_tag_i  (8'h0)
  );

  // ---- a 32-bit BAR that cannot be named in 32 bits ------------------------
  // MEM_BAR_BASE above 4 GB is legitimate for a 64-bit-BAR-only device; a
  // 32-bit BAR placed there is ENUM_ERR_BAR_ADDR32, never a truncation.
  localparam logic [63:0] HIGH_BASE   = 64'h0000_0004_0000_0000;   // 16 GB
  localparam logic [63:0] HIGH_WINDOW = 64'h0000_0000_1000_0000;

  logic        h_scan_start_i;
  logic        h_bar_enable_i;
  logic        h_enum_done_o;
  logic        h_enum_error_o;
  enum_error_e h_enum_error_code;
  logic [3:0]  h_enum_error_code_o;
  assign h_enum_error_code_o = 4'(h_enum_error_code);
  logic [3:0]              h_bar_count_o;
  logic [BAR_SLOTS-1:0]    h_bar_valid_o;
  logic [BAR_SLOTS-1:0]    h_bar_is_64_o;
  logic [BAR_SLOTS-1:0]    h_bar_prefetch_o;
  logic [BAR_SLOTS*64-1:0] h_bar_size_o;
  logic [BAR_SLOTS*64-1:0] h_bar_addr_o;
  logic [BAR_SLOTS-1:0]    h_io_bar_mask_o;
  logic                    h_bar_busy_o;
  logic        h_scan_done_o;

  logic [AXIS_DATA_WIDTH-1:0] h_s_axis_rq_tdata_o;
  logic [AXIS_KEEP_WIDTH-1:0] h_s_axis_rq_tkeep_o;
  logic                       h_s_axis_rq_tvalid_o;
  logic                       h_s_axis_rq_tlast_o;
  logic [AXIS_USER_WIDTH-1:0] h_s_axis_rq_tuser_o;
  logic                       h_s_axis_rq_tready_i;
  logic [7:0]                 h_pcie_rq_tag_i;
  logic                       h_pcie_rq_tag_vld_i;
  logic [AXIS_DATA_WIDTH-1:0] h_m_axis_rc_tdata_i;
  logic [AXIS_KEEP_WIDTH-1:0] h_m_axis_rc_tkeep_i;
  logic                       h_m_axis_rc_tvalid_i;
  logic                       h_m_axis_rc_tlast_i;
  logic                       h_m_axis_rc_tready_o;

  pcie_enum_top #(
      .AXIS_DATA_WIDTH   (AXIS_DATA_WIDTH),
      .AXIS_KEEP_WIDTH   (AXIS_KEEP_WIDTH),
      .AXIS_USER_WIDTH   (AXIS_USER_WIDTH),
      .CRS_RETRY_MAX     (CRS_RETRY_MAX),
      .CRS_BACKOFF_CYCLES(CRS_BACKOFF_CYCLES),
      .CPL_TIMEOUT_CYCLES(CPL_TIMEOUT_CYCLES),
      .MEM_BAR_BASE      (HIGH_BASE),
      .MEM_BAR_WINDOW    (HIGH_WINDOW)
  ) dut_high (
      .clk_i(clk_i),
      .rst_i(rst_i),

      .scan_start_i(h_scan_start_i),
      .scan_bus_i  (scan_bus_i),
      .bar_enable_i(h_bar_enable_i),

      .scan_busy_o         (),
      .scan_done_o         (h_scan_done_o),
      .scan_error_o        (),
      .scan_error_code_o   (),
      .err_credit_blocked_o(),

      .device_present_o    (),
      .unsupported_device_o(),
      .device_bdf_o        (),
      .vendor_id_o         (),
      .device_id_o         (),
      .header_type_o       (),
      .multifunction_o     (),

      .bar_busy_o       (h_bar_busy_o),
      .enum_done_o      (h_enum_done_o),
      .enum_error_o     (h_enum_error_o),
      .enum_error_code_o(h_enum_error_code),

      .bar_count_o   (h_bar_count_o),
      .bar_valid_o   (h_bar_valid_o),
      .bar_is_64_o   (h_bar_is_64_o),
      .bar_prefetch_o(h_bar_prefetch_o),
      .bar_size_o    (h_bar_size_o),
      .bar_addr_o    (h_bar_addr_o),
      .io_bar_mask_o (h_io_bar_mask_o),

      .tx_fc_blocked_i(1'b0),

      .s_axis_rq_tdata_o (h_s_axis_rq_tdata_o),
      .s_axis_rq_tkeep_o (h_s_axis_rq_tkeep_o),
      .s_axis_rq_tvalid_o(h_s_axis_rq_tvalid_o),
      .s_axis_rq_tlast_o (h_s_axis_rq_tlast_o),
      .s_axis_rq_tuser_o (h_s_axis_rq_tuser_o),
      .s_axis_rq_tready_i(h_s_axis_rq_tready_i),

      .pcie_rq_tag_i    (h_pcie_rq_tag_i),
      .pcie_rq_tag_vld_i(h_pcie_rq_tag_vld_i),

      .m_axis_rc_tdata_i (h_m_axis_rc_tdata_i),
      .m_axis_rc_tkeep_i (h_m_axis_rc_tkeep_i),
      .m_axis_rc_tvalid_i(h_m_axis_rc_tvalid_i),
      .m_axis_rc_tlast_i (h_m_axis_rc_tlast_i),
      .m_axis_rc_tready_o(h_m_axis_rc_tready_o),

      .cpl_timeout_valid_i(1'b0),
      .cpl_timeout_tag_i  (8'h0)
  );

endmodule
