// ---------------------------------------------------------------------------
// pcie_enum_scan -- the presence phase of Root Complex enumeration.
// Commit 2b-2.
//
//   scan_start_i -> Vendor/Device ID probe -> [absent? done]
//                -> Header Type read       -> [Type 1? unsupported]
//                -> scan_done_o
//
// This module instantiates exactly one pcie_cfg_txn and drives it. It contains
// all the POLICY; the primitive contains all the MECHANISM. Nothing here
// decodes a completion status, builds a descriptor or touches a tag, and
// nothing in pcie_cfg_txn knows what phase of enumeration it is serving.
//
// ===========================================================================
// SS WHY THE SPLIT IS REAL, AND NOT BOOKKEEPING
// ===========================================================================
//
// One row of the outcome table justifies the whole two-module structure:
//
//   TXN_UR during the probe      -> "nothing here to enumerate", normal exit
//   TXN_UR after the probe       -> fault
//
// Identical wire event, opposite meaning, and the difference is *which
// transaction we are on* -- context pcie_cfg_txn deliberately does not have.
// Folding the two together would put a phase bit inside the transaction engine,
// which is the shape bugs live in.
//
// ===========================================================================
// SS ⭐ DEVICE 0 ONLY -- THERE IS NO DEVICE-NUMBER LOOP
// ===========================================================================
//
// The PCI-era 0-31 sweep is inherited convention and is WRONG here, not merely
// wasteful. PCIe Base 2.1 SS7.3.1 p.479 says two things:
//
//   1. "Configuration Requests specifying all other Device Numbers (1-31) must
//      be terminated by the Switch Downstream Port or the Root Port with an
//      Unsupported Request Completion Status."
//
//      In a conventional Root Complex the enumerating SOFTWARE does sweep 0-31
//      and sees UR for 1-31 -- but that UR is synthesised by the Root Port's own
//      downstream-port logic and the request never reaches the wire. THIS DESIGN
//      HAS NO SUCH LOGIC: the completer surface is tied off
//      (pcie_rq_rc_top.sv:83-99) and pcie_rq_rc_top originates Type 0 straight
//      onto the link. A request naming device 5 would actually be transmitted.
//
//   2. "Non-ARI Devices must respond to all Type 0 Configuration Read Requests,
//      REGARDLESS of the Device Number specified in the Request."
//
//      So if such a request were transmitted, the attached device would answer
//      it. A 0-31 sweep on a direct-attach link would not find one device and
//      31 absences -- it would find the SAME DEVICE 32 TIMES, each with
//      identical Vendor/Device ID.
//
// Probing device 0 only satisfies the rule BY CONSTRUCTION: no request naming
// device 1-31 is ever formed, so there is nothing to terminate. That is a
// structural equivalence, not a deviation -- a compliant RC's software would see
// UR for those numbers; this hardware enumerator simply never asks.
//
// Building the Root-Port termination path is Commits 3/4 work, where a switch
// can first appear below the port and Type 1 arrives with it.
//
// ===========================================================================
// SS WHAT "ABSENT" MEANS ON A POINT-TO-POINT LINK
// ===========================================================================
//
// link_up_i is a precondition of the whole stack, and a PCIe link is
// point-to-point, so a device IS attached whenever this scan runs. Absence
// therefore cannot mean "no device on the link". It means "nothing here to
// enumerate", and the spec gives exactly one signal for it: an Unsupported
// Request to the Function 0 probe -- SS7.3.1 p.479 for an unimplemented Function
// in an ARI Device, SS7.3.3 p.480 for the general Endpoint rule.
//
// That is why TXN_UR on the probe is a NORMAL exit with device_present_o low,
// and why there is no ENUM_ERR code for it.
//
// !! AND WHY THE ALL-1s CONVENTION IS NOT USED HERE.
//
// SS2.3.2 Implementation Note p.122 has a Root Complex synthesise a read value of
// all 1s "when UR Completion Status is returned for a Configuration Read
// Request", for software that depends on it. That synthesis is performed BY the
// Root Complex FOR software above it. This module sits where it would be
// PERFORMED, not consumed: it sees the UR itself, as TXN_UR.
//
// So absence is signalled by TXN_UR and by nothing else, and vendor_id_o ==
// FFFFh is NOT treated as absence. Re-deriving absence from a sentinel would
// discard information the spec took care to keep distinguishable. A Successful
// Completion carrying FFFFFFFF is reported PRESENT with that Vendor ID; it is
// not this module's business to reinterpret an SC.
//
// ===========================================================================
// SS A TAG STROBE IS NOT EVIDENCE OF TRANSMISSION
// ===========================================================================
//
// This module does not observe pcie_rq_tag_o at all -- it watches only the
// primitive's response port. That is deliberate. Tag allocation sits UPSTREAM
// of the credit gate: tlp_requester raises tag_request_valid_o on entering
// REQ_TAG (tlp_requester.sv:138, 211) with no reference to fc_initialized_i or
// credit, while the gate is at the VC-buffer-to-transmit boundary
// (tlp_layer.sv:280). A tag can therefore be handed out for a request that is
// still parked in the VC buffer and may never leave (measured: Commit 2b-1 test
// i8).
//
// ===========================================================================
// SS NO TIMERS HERE, AND ONE THING THAT CANNOT BE FIXED HERE
// ===========================================================================
//
// The CRS backoff lives in pcie_cfg_txn; the completion timeout lives in
// tlp_request_tracker. This module waits indefinitely on cmd_ready_o and
// rsp_valid_o and has no counter of its own.
//
// tx_fc_blocked_i is sampled ONLY to annotate a TXN_TIMEOUT on
// err_credit_blocked_o. IT APPEARS IN NO NEXT-STATE EXPRESSION. A credit signal
// gating control flow is exactly the watchdog mistake the design forbids, and
// the mutation set proves the state sequence is identical with tx_fc_blocked_i
// forced either way.
//
// The annotation exists because of a bound this module cannot remove:
// tlp_request_tracker measures per-tag age from ALLOCATION (that module's
// header, :39), and allocation precedes the credit gate. A request starved of
// credit for longer than CPL_TIMEOUT_CYCLES therefore times out WITHOUT EVER
// HAVING BEEN TRANSMITTED, and is indistinguishable from a dead device
// (measured: Commit 2b-1 test i9). No FSM above this stack can ride that out.
// err_credit_blocked_o is the most a client can do -- say "this timeout smells
// like credit". Fixing it means raising CPL_TIMEOUT_CYCLES toward the ~10 ms the
// spec recommends, which is Stage-H work.
//
// Guards use $warning, never $error: a procedural $error maps to $stop under
// the simulator, which would abort the shared multi-test process.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_enum_scan
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
    // Sampled in IDLE only. The integrator raises it once the four link/flow
    // control preconditions hold; enumeration is single-shot after link-up and
    // does not support re-entry after a retrain (tracker SS20.4).
    input  logic                        scan_start_i,
    // Bus number of the Logical Bus representing the Link. Device and Function
    // are 0 by SS7.3.1 -- see the header.
    input  logic [7:0]                  scan_bus_i,

    // ---- status surface ----------------------------------------------------
    // scan_done_o marks a terminal NON-ERROR outcome: the scan finished and its
    // results are stable. It covers both "device found" and "nothing to
    // enumerate", and also the unsupported-device exit -- a consumer that wants
    // a configurable Type 0 device asks for
    //     scan_done_o && device_present_o && !unsupported_device_o
    output logic                        scan_busy_o,
    output logic                        scan_done_o,
    output logic                        scan_error_o,
    output enum_error_e                 scan_error_code_o,
    // Diagnostic ONLY, valid with scan_error_o on a timeout: tx_fc_blocked_o was
    // asserted when the timeout was reported, so the request was probably never
    // transmitted. See the header. Never an input to control flow.
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

    // ---- pcie_rq_rc_top socket, forwarded from the primitive ---------------
    output logic [AXIS_DATA_WIDTH-1:0]  s_axis_rq_tdata_o,
    output logic [AXIS_KEEP_WIDTH-1:0]  s_axis_rq_tkeep_o,
    output logic                        s_axis_rq_tvalid_o,
    output logic                        s_axis_rq_tlast_o,
    output logic [AXIS_USER_WIDTH-1:0]  s_axis_rq_tuser_o,
    input  logic                        s_axis_rq_tready_i,

    input  logic [7:0]                  pcie_rq_tag_i,
    input  logic                        pcie_rq_tag_vld_i,

    input  logic [AXIS_DATA_WIDTH-1:0]  m_axis_rc_tdata_i,
    input  logic [AXIS_KEEP_WIDTH-1:0]  m_axis_rc_tkeep_i,
    input  logic                        m_axis_rc_tvalid_i,
    input  logic                        m_axis_rc_tlast_i,
    output logic                        m_axis_rc_tready_o,

    input  logic                        cpl_timeout_valid_i,
    input  logic [7:0]                  cpl_timeout_tag_i
);

  // -------------------------------------------------------------------------
  // The one transaction primitive. One in flight, always -- Table 2-37 p.137
  // permits a peer to advertise a single NPH credit, so a second config request
  // could not be transmitted anyway (see pcie_cfg_txn's header).
  // -------------------------------------------------------------------------
  logic         cmd_valid;
  logic         cmd_ready;
  logic         rsp_valid;
  logic         rsp_ready;
  txn_outcome_e rsp_outcome;
  logic [31:0]  rsp_rdata;

  logic [5:0]   cmd_reg_num;

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
      // Both scan transactions are READS. Nothing here writes.
      .cmd_write_i   (1'b0),
      .cmd_bdf_i     (device_bdf_o),
      .cmd_reg_num_i (cmd_reg_num),
      .cmd_ext_reg_i (CFG_EXT_REG_NONE),
      .cmd_first_be_i(CFG_BE_DWORD),
      .cmd_wdata_i   (32'd0),

      .rsp_valid_o     (rsp_valid),
      .rsp_ready_i     (rsp_ready),
      .rsp_outcome_o   (rsp_outcome),
      .rsp_rdata_o     (rsp_rdata),
      // Deliberately unused: the raw completion status and the CRS retry count
      // are the primitive's business. This module acts on the classified
      // outcome only -- re-decoding status up here would duplicate policy.
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

  // -------------------------------------------------------------------------
  // Sequencer.
  //
  // The probe and header-type phases get their OWN response states rather than
  // sharing one with a phase flag, so that the phase-dependent policy of
  // SPEC_PREDICTIONS_ENUM.md SSD.5 maps one-to-one onto the RTL and a reader can
  // check the TXN_UR rows against the table by eye.
  // -------------------------------------------------------------------------
  typedef enum logic [2:0] {
    S_IDLE,         // waiting for scan_start_i
    S_PROBE_CMD,    // offering the Vendor/Device ID read
    S_PROBE_RSP,    // classifying it -- PROBE policy: UR means absent
    S_HDR_CMD,      // offering the Header Type read
    S_HDR_RSP,      // classifying it -- POST-PROBE policy: UR is a fault
    S_DONE,         // terminal, no error
    S_UNSUPPORTED,  // terminal, no error: a device we cannot enumerate yet
    S_ERROR         // terminal, sticky, reset-only
  } scan_state_e;

  scan_state_e state_r;

  logic [15:0] vendor_id_r, device_id_r;
  logic [7:0]  header_type_r;
  logic        present_r;
  enum_error_e error_code_r;
  logic        credit_blocked_r;

  // Header Type sits in byte 2 of register 3 -- [BASE] Figure 7-5 p.491.
  wire [7:0]  hdr_byte    = rsp_rdata[HDR_TYPE_LSB +: 8];
  wire [6:0]  hdr_layout  = hdr_byte[6:0];
  wire        hdr_is_type0 = (hdr_layout == HDR_LAYOUT_TYPE0);

  // Register 0 is {Device ID[31:16], Vendor ID[15:0]} -- [BASE] Figure 7-5 p.491.
  wire [15:0] probe_vendor = rsp_rdata[15:0];
  wire [15:0] probe_device = rsp_rdata[31:16];

  // A fault that is not UR-specific classifies the same way in both phases.
  // Written once so the two response states cannot drift apart.
  function automatic enum_error_e fault_code(input txn_outcome_e outcome);
    case (outcome)
      TXN_CA:            fault_code = ENUM_ERR_CA;
      TXN_CRS_EXHAUSTED: fault_code = ENUM_ERR_CRS_EXHAUSTED;
      TXN_TIMEOUT:       fault_code = ENUM_ERR_TIMEOUT;
      default:           fault_code = ENUM_ERR_UR_POST_PROBE;
    endcase
  endfunction

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r          <= S_IDLE;
      vendor_id_r      <= '0;
      device_id_r      <= '0;
      header_type_r    <= '0;
      present_r        <= 1'b0;
      error_code_r     <= ENUM_ERR_NONE;
      credit_blocked_r <= 1'b0;
    end else begin
      unique case (state_r)
        S_IDLE: begin
          if (scan_start_i) begin
            vendor_id_r      <= '0;
            device_id_r      <= '0;
            header_type_r    <= '0;
            present_r        <= 1'b0;
            error_code_r     <= ENUM_ERR_NONE;
            credit_blocked_r <= 1'b0;
            state_r          <= S_PROBE_CMD;
          end
        end

        S_PROBE_CMD: if (cmd_ready) state_r <= S_PROBE_RSP;

        // ---- PROBE policy. SPEC_PREDICTIONS_ENUM.md SSD.5, left column. -----
        S_PROBE_RSP: begin
          if (rsp_valid) begin
            case (rsp_outcome)
              TXN_OK: begin
                vendor_id_r <= probe_vendor;
                device_id_r <= probe_device;
                present_r   <= 1'b1;
                state_r     <= S_HDR_CMD;
              end
              // ABSENT, not an error: on a point-to-point link with link_up_i
              // asserted a device is attached, so a UR to the Function 0 probe
              // means "nothing here to enumerate" (SS7.3.1 p.479, SS7.3.3 p.480).
              TXN_UR: begin
                present_r <= 1'b0;
                state_r   <= S_DONE;
              end
              default: begin
                error_code_r     <= fault_code(rsp_outcome);
                credit_blocked_r <= (rsp_outcome == TXN_TIMEOUT) && tx_fc_blocked_i;
                state_r          <= S_ERROR;
              end
            endcase
          end
        end

        S_HDR_CMD: if (cmd_ready) state_r <= S_HDR_RSP;

        // ---- POST-PROBE policy. Same table, right column. -------------------
        S_HDR_RSP: begin
          if (rsp_valid) begin
            case (rsp_outcome)
              TXN_OK: begin
                header_type_r <= hdr_byte;
                // A Type 1 header is a bridge or switch: a valid device that
                // answered correctly and that Commit 2b cannot enumerate.
                // Terminal, but NOT an error.
                state_r       <= hdr_is_type0 ? S_DONE : S_UNSUPPORTED;
              end
              // A device that answered register 0 has no business rejecting a
              // legal configuration read of register 3.
              TXN_UR: begin
                error_code_r <= ENUM_ERR_UR_POST_PROBE;
                state_r      <= S_ERROR;
              end
              default: begin
                error_code_r     <= fault_code(rsp_outcome);
                credit_blocked_r <= (rsp_outcome == TXN_TIMEOUT) && tx_fc_blocked_i;
                state_r          <= S_ERROR;
              end
            endcase
          end
        end

        // Terminal states. S_DONE and S_UNSUPPORTED hold until reset just as
        // S_ERROR does: enumeration is single-shot after link-up, and a status
        // surface that could be re-entered would let a consumer sample it
        // mid-rescan.
        S_DONE:        state_r <= S_DONE;
        S_UNSUPPORTED: state_r <= S_UNSUPPORTED;
        S_ERROR:       state_r <= S_ERROR;
      endcase
    end
  end

  assign cmd_valid   = (state_r == S_PROBE_CMD) || (state_r == S_HDR_CMD);
  assign cmd_reg_num = (state_r == S_HDR_CMD) ? CFG_REG_CACHE_HEADER
                                              : CFG_REG_VENDOR_DEVICE;
  // rsp_ready is a real handshake, not a strobe: the primitive holds rsp_valid_o
  // until it is consumed, so an unready consumer cannot miss an outcome.
  assign rsp_ready   = (state_r == S_PROBE_RSP) || (state_r == S_HDR_RSP);

  // {Bus[15:8], Device[7:3], Function[2:0]}, device and function fixed at 0 --
  // see the header for why there is no device loop.
  assign device_bdf_o = {scan_bus_i, 5'd0, 3'd0};

  assign scan_busy_o          = (state_r != S_IDLE) && (state_r != S_DONE) &&
                                (state_r != S_UNSUPPORTED) && (state_r != S_ERROR);
  assign scan_done_o          = (state_r == S_DONE) || (state_r == S_UNSUPPORTED);
  assign scan_error_o         = (state_r == S_ERROR);
  assign scan_error_code_o    = error_code_r;
  assign err_credit_blocked_o = credit_blocked_r;

  assign device_present_o     = present_r;
  assign unsupported_device_o = (state_r == S_UNSUPPORTED);
  assign vendor_id_o          = vendor_id_r;
  assign device_id_o          = device_id_r;
  assign header_type_o        = header_type_r;
  assign multifunction_o      = header_type_r[HDR_MULTIFUNCTION_BIT];

endmodule
