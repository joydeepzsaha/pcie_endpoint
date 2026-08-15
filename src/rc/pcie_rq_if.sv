// ---------------------------------------------------------------------------
// pcie_rq_if -- PG213 Requester Request (RQ) AXI4-Stream slave -> TL command
// port. Commit 2a-i.
//
// SPEC ANCHORS
//   PG213 v1.3 Table 60/61 ....... the 16-byte RQ descriptor on beat 0
//                                  (Memory/IO and Configuration respectively).
//   PG213 v1.3 Table 57 .......... req_type encodings, mapped to tlp_cmd_e.
//   PCIe Base 2.1 SS2.2.4.1 ...... the legality rules this module is the last
//                                  line of defence for -- there is NO validator
//                                  anywhere on the transmit path.
//   PCIe Base 2.1 SS2.2.7 ........ byte-enable rules; transfer size comes from
//                                  the Length field, not the byte enables.
//   PCIe Base 2.1 SS7.3.1 p.479 .. Downstream Ports associate with Device 0 --
//                                  the basis of the Type 0 tripwire below.
//
// Beat 0 of every packet is a 16-byte RQ descriptor (PG213 v1.3 Table 60/61);
// beats 1..n are payload. The descriptor is decoded into the Transaction
// Layer's existing command_* port and the payload is narrowed 128 -> 32 by
// pcie_axis_dw_downsize (Commit 2a-0, ccb2a52).
//
// WHAT THIS MODULE IS RESPONSIBLE FOR
//
//  * Legality. tlp_validator.sv is instantiated on the RECEIVE path only
//    (tlp_parser.sv:299, tlp_classifier.sv:68) -- there is NO validator
//    anywhere on the requester -> control -> generator -> vc_buffer transmit
//    path. Nothing downstream will catch a malformed request, so this wrapper
//    is the last line of defence and must satisfy PCIe Base 2.1 SS2.2.4.1 BY
//    CONSTRUCTION. Every check in the reject table below exists for that
//    reason, and every reject emits no TLP at all.
//
//  * The DW-granular -> byte-granular tkeep translation. PG213's
//    s_axis_rq_tkeep is one bit per Dword (4 bits at 128 bits); the gearbox and
//    the TL both want byte granularity. This translation was deliberately kept
//    out of the gearbox (see pcie_axis_dw_downsize.sv's header) because it is a
//    descriptor-layer concern: the byte validity of the first and last Dwords
//    comes from first_be/last_be in tuser, not from tkeep at all.
//
//    It is applied on the NARROW side, after the gearbox, not before it. The
//    gearbox rejects tkeep that is not contiguous from bit 0 (keep_illegal(),
//    pcie_axis_dw_downsize.sv:109-111) -- correctly, since that is illegal
//    AXI-Stream -- and a byte-granular mask like first_be=0010 is exactly that
//    shape. Feeding whole-Dword keeps into the gearbox and masking its 4-bit
//    output with first_be/last_be gives an identical result without ever
//    presenting the gearbox an illegal pattern, so gearbox_error_o stays
//    meaningful instead of firing on every byte-granular config write.
//
//  * Tags. The TL's request tracker allocates them (tlp_request_tracker.sv:
//    55-65); the descriptor's Tag field [103:96] is IGNORED, per PG213's
//    core-managed-tag mode. pcie_rq_tag_o presents the REAL allocated tag,
//    taken from tlp_layer's allocated_tag_o / allocated_tag_valid_o, so it is
//    the value that appears in the emitted header's DW1 and that the matching
//    completion returns. See the port note below for why it arrives after the
//    command was accepted rather than with it.
//
// SS THE BY-CONSTRUCTION PROPERTY (the point of the module)
//
// command_byte_count_o and command_data_last_o are BOTH derived from the same
// descriptor field, dword_count [74:64], plus one internal Dword counter
// (dw_sent_r). last is asserted exactly when that counter reaches the Dword
// Count. s_axis_rq_tlast never drives it.
//
// tlp_requester compares command_data_last_i against request_last =
// expected_data_last && (remaining_r <= segment_bytes_r) -- end of the WHOLE
// request, not of a segment (tlp_requester.sv:153-158, the f3160d0 contract
// restored by 0277358) -- and raises command_error_valid_o /
// TLP_ERR_LOCAL_PAYLOAD on disagreement (:225-231). Because both sides of that
// comparison descend from the same dword_count, they cannot disagree for a
// well-formed packet: the early-last protocol violation is structurally
// unreachable from the AXIS side. That is what T7 tests.
//
// ABORT PATH (the one place last is not counter-derived, and why)
//
// If the host asserts s_axis_rq_tlast before the Dword Count is satisfied, the
// packet is malformed. Two cases, treated differently on purpose:
//
//   (a) before the command has been launched (tlast on the descriptor beat of a
//       write): the request is rejected outright -- rq_protocol_error_o, NO
//       command, back to idle. Nothing reached the TL.
//
//   (b) mid-payload, after the command was launched: the command cannot be
//       un-launched, and simply stopping would strand tlp_requester in REQ_DATA
//       forever. The wrapper instead flushes the gearbox and emits ONE
//       terminating beat with command_keep_o = 0 and command_data_last_o = 1.
//       That is the TL's own documented recovery: "Abort this command after
//       forwarding a terminating beat so that both interfaces can recover for
//       the next command" (tlp_requester.sv:232-236). The TL sees
//       command_data_last_i != request_last, pulses TLP_ERR_LOCAL_PAYLOAD, and
//       returns to REQ_IDLE. Both ends land idle within a bounded number of
//       cycles and no half-formed TLP is emitted.
//
//   Case (b) is NOT the property SS above is about. There, last disagreeing with
//   the byte count would be a wrapper arithmetic bug on a VALID packet; here it
//   is the deliberate abort signal for an INVALID one, and it is the only exit
//   that does not deadlock the TL.
//
// REJECTS (all: rq_protocol_error_o + rq_error_code_o + $warning, no TLP, the
// rest of the AXIS packet drained, FSM back to idle)
//
//   Request Type not one of the eight mapped .. rq_error_e RQ_ERR_REQ_TYPE
//   Dword Count 0 or > 1024 ................... RQ_ERR_DWORD_COUNT
//   Configuration with Dword Count != 1 ....... RQ_ERR_CFG_DWORD_COUNT
//   config/IO not inside one Dword ............ RQ_ERR_CFG_IO_FIT
//   4 KB boundary crossing .................... RQ_ERR_4KB
//   Address Type != 00 on Memory/IO ........... RQ_ERR_ADDRESS_TYPE
//   poisoned Configuration write .............. RQ_ERR_POISON_CFG_WR
//   byte count wider than command_byte_count_i  RQ_ERR_BYTE_COUNT_FIT
//   byte enables the TL cannot reproduce ...... RQ_ERR_BE_MISMATCH
//   zero-length read (N=1, first_be=0) ........ RQ_ERR_ZERO_LENGTH
//   early / missing tlast ..................... RQ_ERR_EARLY_LAST / _MISSING_LAST
//
// The config/IO check is the FIT condition byte_count <= 4 - offset, mirroring
// tlp_requester.sv:183-199 as relaxed by d5a4253 and locked by 67220b5. It is
// deliberately NOT "byte_count == 4": the spec constrains the Configuration
// Length field, not the byte enables (PCIe Base 2.1 SS2.2.7), so a single-byte
// config write with first_be=0010 is legal and must be forwarded. Rejecting it
// would break Commit 2b's Secondary Bus Number write.
//
// OUT OF SCOPE (documented, not implemented -- KNOWN_GAPS)
//  * Non-contiguous byte enables. PG213 permits them on <=2-Dword writes; the
//    TL's tlp_first_be/tlp_last_be build contiguous range masks only
//    (tlp_pkg.sv:165-193), so they are not expressible. Rejected.
//  * Zero-length reads. Expressible at the TL for memory reads since the
//    admission guard permits byte_count == 0 for TLP_CMD_MEM_READ
//    (tlp_requester.sv:193), but rejected here for uniformity across the
//    command types; revisit if a consumer needs them.
//  * Atomics, locked reads, messages, ATS: rejected, no command path.
//  * Poison origination: command_* has no poison input; poisoned writes other
//    than config are forwarded unpoisoned. Flagged here, not silently dropped.
//  * ECRC: command_ecrc_enable_o is tied 0. The TL computes ECRC itself
//    (tlp_ecrc.sv); descriptor bit [127] Force ECRC is ignored.
//
// Guards use $warning, never $error: a procedural $error maps to $stop under
// the simulator, which would abort the shared multi-test process -- and several
// tests here deliberately trip these guards.
//
// DEFERRED (Stage D master brief SS8.1) -- Type 0 config to device != 0.
// PCIe Base 2.1 SS7.3.1 p.479 associates Downstream Ports with Device 0; a
// Root Port must terminate a Type 0 Configuration Request naming any other
// device number as an Unsupported Request.  This surface has no sweep-capable
// requester yet (the enumerator probes device 0 only), so that termination is
// NOT implemented: an admitted Type 0 config request naming device != 0 is
// forwarded UNCHANGED, and a $warning tripwire below marks each one.  The
// deferral becomes untenable the moment a requester that sweeps device
// numbers exists -- the tripwire (and the D2-S5 pin test, which asserts the
// forwarded-unchanged consequence) is there so that landing the real UR
// termination shows up as a visible test change, not a silent one.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_rq_if
  import tlp_pkg::*;
  import pcie_rq_rc_pkg::*;
#(
    parameter int AXIS_DATA_WIDTH = 128,
    // PG213 s_axis_rq_tkeep is DWORD-granular: one bit per Dword.
    parameter int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32,
    parameter int AXIS_USER_WIDTH = 60,
    parameter int TL_DATA_WIDTH   = 32,
    parameter int TL_KEEP_WIDTH   = TL_DATA_WIDTH / 8,
    parameter int CONTEXT_WIDTH   = 16
) (
    input  logic                        clk_i,
    input  logic                        rst_i,

    // ---- PG213 Requester Request AXI4-Stream slave -----------------------
    input  logic [AXIS_DATA_WIDTH-1:0]  s_axis_rq_tdata,
    input  logic [AXIS_KEEP_WIDTH-1:0]  s_axis_rq_tkeep,
    input  logic                        s_axis_rq_tvalid,
    input  logic                        s_axis_rq_tlast,
    // [3:0] first_be, [7:4] last_be, valid in beat 0 (PG213 Table 62).
    input  logic [AXIS_USER_WIDTH-1:0]  s_axis_rq_tuser,
    output logic                        s_axis_rq_tready,

    // ---- core-managed tag presentation -----------------------------------
    // Wire allocated_tag_i / allocated_tag_valid_i straight to tlp_layer's
    // allocated_tag_o / allocated_tag_valid_o. That is the tag the request
    // tracker actually handed out, so it is the one in the emitted header's
    // DW1 and the one the matching completion carries back -- the whole point
    // of presenting it at all.
    //
    // Timing: the tag is NOT available when the command is accepted. The
    // requester leaves REQ_IDLE and only allocates in REQ_TAG a cycle or more
    // later (tlp_requester.sv:247, 251-252), which is why PG213 pairs the tag
    // with a valid strobe instead of qualifying it with the command handshake.
    // The wrapper forwards the strobe rather than re-timing it, so a host that
    // pipelines requests still sees one tag per emitted TLP in issue order.
    //
    // Posted writes are absent from this stream by construction: MEM_WRITE
    // never enters REQ_TAG (tlp_requester.sv:247), so nothing is
    // allocated and the strobe cannot fire. A segmented non-posted request
    // strobes once per segment, each with that segment's own tag.
    //
    // The descriptor's Tag field [103:96] is read nowhere in this module.
    //
    // command_context_o is NOT a spare correlation channel. It is INTERNALLY
    // CONSUMED by the 2a-ii wrapper pair: this module loads it with
    // {mem_read_r, addr_r[11:0]} (:345 below) and pcie_rc_if reads it back to
    // reconstruct the RC descriptor's Lower Address, which the CPL header does
    // not otherwise carry (pcie_rc_if.sv:251, 252). It is not raised to a port
    // on pcie_rq_rc_top and must not be treated as client-visible -- see that
    // module's header, pcie_rq_rc_top.sv:78-90, which is authoritative.
    // Correlate completions BY TAG, via pcie_rq_tag_o / pcie_rq_tag_vld_o.
    input  logic [7:0]                  allocated_tag_i,
    input  logic                        allocated_tag_valid_i,
    output logic [7:0]                  pcie_rq_tag_o,
    output logic                        pcie_rq_tag_vld_o,

    // ---- Transaction Layer command port ----------------------------------
    output logic                        command_valid_o,
    input  logic                        command_ready_i,
    output tlp_cmd_e                    command_o,
    output logic [63:0]                 command_address_o,
    output logic [12:0]                 command_byte_count_o,
    output logic [2:0]                  command_tc_o,
    output logic [2:0]                  command_attr_o,
    output logic [CONTEXT_WIDTH-1:0]    command_context_o,
    output logic                        command_prefix_valid_o,
    output logic [31:0]                 command_prefix_o,
    output logic                        command_ecrc_enable_o,

    output logic [TL_DATA_WIDTH-1:0]    command_data_o,
    output logic [TL_KEEP_WIDTH-1:0]    command_keep_o,
    output logic                        command_data_valid_o,
    output logic                        command_data_last_o,
    input  logic                        command_data_ready_i,

    // ---- error surface ---------------------------------------------------
    // One-cycle pulse; rq_error_code_o is valid in the same cycle and holds
    // until the next rejection.
    output logic                        rq_protocol_error_o,
    output rq_error_e                   rq_error_code_o,
    // Forwarded from the payload gearbox: illegal tkeep on the narrow stream.
    output logic                        rq_gearbox_error_o
);

  localparam int AXIS_DW = AXIS_DATA_WIDTH / 32;              // Dwords per beat
  localparam int AXIS_BYTE_KEEP = AXIS_DATA_WIDTH / 8;        // gearbox tkeep

  // -------------------------------------------------------------------------
  // Descriptor decode (combinational, on beat 0)
  // -------------------------------------------------------------------------
  rq_descriptor_t desc;
  assign desc = rq_descriptor_t'(s_axis_rq_tdata[127:0]);

  wire [3:0]  desc_first_be = s_axis_rq_tuser[3:0];
  wire [3:0]  desc_last_be  = s_axis_rq_tuser[7:4];
  wire [1:0]  desc_off      = rq_be_offset(desc_first_be);
  wire [10:0] desc_n        = desc.dword_count;
  wire [12:0] desc_bc       = rq_byte_count(desc_n, desc_first_be, desc_last_be);

  rq_req_type_e desc_type;
  assign desc_type = rq_req_type_e'(desc.req_type);

  logic     type_ok;
  tlp_cmd_e desc_cmd;
  logic     desc_is_config, desc_is_io, desc_has_data;

  always_comb begin
    type_ok        = 1'b1;
    desc_cmd       = TLP_CMD_MEM_READ;
    desc_is_config = 1'b0;
    desc_is_io     = 1'b0;
    unique case (desc_type)
      RQ_MEM_READ:   desc_cmd = TLP_CMD_MEM_READ;
      RQ_MEM_WRITE:  desc_cmd = TLP_CMD_MEM_WRITE;
      RQ_IO_READ:  begin desc_cmd = TLP_CMD_IO_READ;    desc_is_io     = 1'b1; end
      RQ_IO_WRITE: begin desc_cmd = TLP_CMD_IO_WRITE;   desc_is_io     = 1'b1; end
      RQ_CFG_READ0:  begin desc_cmd = TLP_CMD_CFG_READ0;  desc_is_config = 1'b1; end
      RQ_CFG_WRITE0: begin desc_cmd = TLP_CMD_CFG_WRITE0; desc_is_config = 1'b1; end
      // Stage D-2: the Type 1 pair, mapped to the D-1b commands.  Setting
      // desc_is_config is the WHOLE integration with the legality checks --
      // bad_cfg_n, bad_cfg_fit, bad_at and the config address packing below
      // are class-shaped and bind to CFG1 with no edit (docs/recon/RECON_stageD.md SS5).
      RQ_CFG_READ1:  begin desc_cmd = TLP_CMD_CFG_READ1;  desc_is_config = 1'b1; end
      RQ_CFG_WRITE1: begin desc_cmd = TLP_CMD_CFG_WRITE1; desc_is_config = 1'b1; end
      default:       type_ok = 1'b0;
    endcase
  end

  // Per-command like bad_poison below, NOT class-shaped: this is the second
  // of the two decode sites docs/recon/RECON_stageD.md SS5's "two arms" survey missed
  // (the RQ-level analogue of tlp_requester's command_has_data, D-1b site 2).
  // Leaving CFG_WRITE1 out here silently reclassifies a CfgWr1 as payload-
  // less and rejects its packet with RQ_ERR_MISSING_LAST.
  assign desc_has_data = type_ok && (desc_cmd == TLP_CMD_MEM_WRITE ||
                                     desc_cmd == TLP_CMD_CFG_WRITE0 ||
                                     desc_cmd == TLP_CMD_CFG_WRITE1 ||
                                     desc_cmd == TLP_CMD_IO_WRITE);

  // Address assembly. Config lays the target BDF into address[31:16] because
  // the Completer ID's {Bus[7:0], Dev[4:0], Fn[2:0]} packing is bit-identical
  // to the Commit-1 config-Dword layout the generator emits
  // (tlp_generator.sv:81-82 masks [1:0] to zero on the wire, so the byte offset
  // in [1:0] drives the byte enables without corrupting the register number).
  logic [63:0] desc_address;
  always_comb begin
    if (desc_is_config) begin
      desc_address          = 64'd0;
      desc_address[31:16]   = desc.completer_id;   // {Bus, Dev, Fn}
      desc_address[15:12]   = 4'h0;                // reserved in the config DW
      desc_address[11:8]    = desc.address[11:8];  // Ext Reg Number
      desc_address[7:2]     = desc.address[7:2];   // Register Number
      desc_address[1:0]     = desc_off;            // byte offset -> first_be
    end else begin
      desc_address          = {desc.address[63:2], desc_off};
    end
  end

  // -------------------------------------------------------------------------
  // Legality checks. Evaluated together on beat 0; the first failing one in
  // this priority order names the error.
  // -------------------------------------------------------------------------
  wire bad_type      = !type_ok;
  wire bad_n         = (desc_n == 11'd0) || (desc_n > 11'd1024);
  wire bad_cfg_n     = desc_is_config && (desc_n != 11'd1);
  // The relaxed admission condition, tlp_requester.sv:183-199 (d5a4253).
  wire bad_cfg_fit   = (desc_is_config || desc_is_io) &&
                       (desc_bc > (13'd4 - {11'd0, desc_off}));
  wire bad_4kb       = ({1'b0, desc_address[11:0]} + {1'b0, desc_bc}) > 14'd4096;
  wire bad_at        = !desc_is_config && (desc.address[1:0] != 2'b00);
  // Membership is EXACTLY the two config writes.  IO_WRITE stays out on
  // purpose: poisoned IO/memory writes are forwarded unpoisoned (KNOWN_GAPS
  // above), and widening this check would be a second behaviour change.
  wire bad_poison    = (desc_cmd == TLP_CMD_CFG_WRITE0 ||
                        desc_cmd == TLP_CMD_CFG_WRITE1) && desc.poisoned;
  // command_byte_count_i is 13 bits; rq_byte_count() is too, so this can only
  // fire if desc_n slipped past bad_n. Kept as an explicit guard rather than
  // relying on truncation.
  wire bad_bc_fit    = desc_bc > 13'd4096;
  // Zero-length read: NOT caught by the round trip below, since
  // tlp_first_be(0, 0) == 0 agrees with first_be == 0. Explicit.
  wire bad_zero_len  = (desc_n == 11'd1) && (desc_first_be == 4'h0);
  // The round trip: does the TL, given (offset, byte_count), rebuild exactly
  // the byte enables the descriptor asked for? This is what catches
  // non-contiguous byte enables -- tlp_first_be/tlp_last_be produce contiguous
  // range masks only (tlp_pkg.sv:165-193).
  wire bad_be        = (tlp_first_be(desc_off, desc_bc) != desc_first_be) ||
                       (tlp_last_be (desc_off, desc_bc) != desc_last_be);
  // A write whose packet ends on the descriptor beat carries no payload at all.
  wire bad_early_hdr = desc_has_data && s_axis_rq_tlast;
  // A read (or a rejected request) whose packet does not end on beat 0.
  wire bad_extra_hdr = !desc_has_data && !s_axis_rq_tlast;

  logic      desc_reject;
  rq_error_e desc_error;
  always_comb begin
    desc_reject = 1'b1;
    if      (bad_type)      desc_error = RQ_ERR_REQ_TYPE;
    else if (bad_n)         desc_error = RQ_ERR_DWORD_COUNT;
    else if (bad_cfg_n)     desc_error = RQ_ERR_CFG_DWORD_COUNT;
    else if (bad_zero_len)  desc_error = RQ_ERR_ZERO_LENGTH;
    else if (bad_be)        desc_error = RQ_ERR_BE_MISMATCH;
    else if (bad_cfg_fit)   desc_error = RQ_ERR_CFG_IO_FIT;
    else if (bad_at)        desc_error = RQ_ERR_ADDRESS_TYPE;
    else if (bad_4kb)       desc_error = RQ_ERR_4KB;
    else if (bad_poison)    desc_error = RQ_ERR_POISON_CFG_WR;
    else if (bad_bc_fit)    desc_error = RQ_ERR_BYTE_COUNT_FIT;
    else if (bad_early_hdr) desc_error = RQ_ERR_EARLY_LAST;
    else if (bad_extra_hdr) desc_error = RQ_ERR_MISSING_LAST;
    else begin
      desc_error  = RQ_ERR_NONE;
      desc_reject = 1'b0;
    end
  end

  // -------------------------------------------------------------------------
  // FSM
  // -------------------------------------------------------------------------
  typedef enum logic [2:0] {
    S_DESC,        // accepting beat 0
    S_PAYLOAD,     // forwarding payload beats into the gearbox
    S_FLUSH,       // AXIS done; draining the gearbox into the TL
    S_ABORT_FLUSH, // malformed mid-payload: discarding the gearbox contents
    S_ABORT_TERM,  // emitting the terminating zero-keep beat (case (b) above)
    S_DRAIN        // swallowing the rest of a rejected AXIS packet
  } rq_state_e;

  rq_state_e state_r;

  tlp_cmd_e    cmd_r;
  logic [63:0] addr_r;
  logic [12:0] bc_r;
  logic [2:0]  tc_r, attr_r;
  logic        mem_read_r;   // context[12]: addr_r[11:0] is a real byte address
  logic [10:0] n_r;          // descriptor Dword Count
  logic [3:0]  first_be_r, last_be_r;
  logic [11:0] dw_rem_r;     // payload Dwords not yet handed to the gearbox
  logic [10:0] dw_sent_r;    // payload Dwords accepted by the TL
  logic        cmd_pending_r;
  // Set only on the RQ_ERR_MISSING_LAST path: the AXIS packet overran its own
  // Dword Count, so the surplus beats must be swallowed WHILE the TL is still
  // being fed the Dwords it was legitimately promised. Without this the drain
  // would gate command_data_valid_o off and strand tlp_requester in REQ_DATA.
  logic        drain_owes_tl_r;

  // -------------------------------------------------------------------------
  // Payload gearbox, 128 -> 32. Fed WHOLE-Dword byte keeps only (contiguous
  // from bit 0, always legal); the byte-enable mask is applied to its output.
  // -------------------------------------------------------------------------
  logic [AXIS_DATA_WIDTH-1:0] pay_s_tdata;
  logic [AXIS_BYTE_KEEP-1:0]  pay_s_tkeep;
  logic                       pay_s_tvalid, pay_s_tlast, pay_s_tready;
  logic [TL_DATA_WIDTH-1:0]   pay_m_tdata;
  logic [TL_KEEP_WIDTH-1:0]   pay_m_tkeep;
  logic                       pay_m_tvalid, pay_m_tlast, pay_m_tready;

  pcie_axis_dw_downsize #(
      .DATA_WIDTH_WIDE  (AXIS_DATA_WIDTH),
      .DATA_WIDTH_NARROW(TL_DATA_WIDTH)
  ) u_payload (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata (pay_s_tdata),  .s_axis_tkeep (pay_s_tkeep),
      .s_axis_tvalid(pay_s_tvalid), .s_axis_tlast (pay_s_tlast),
      .s_axis_tready(pay_s_tready),
      .m_axis_tdata (pay_m_tdata),  .m_axis_tkeep (pay_m_tkeep),
      .m_axis_tvalid(pay_m_tvalid), .m_axis_tlast (pay_m_tlast),
      .m_axis_tready(pay_m_tready),
      .gearbox_error_o(rq_gearbox_error_o)
  );

  // Dwords this wide beat should carry, and the resulting all-ones byte keep.
  wire [11:0] beat_dw   = (dw_rem_r >= 12'(AXIS_DW)) ? 12'(AXIS_DW) : dw_rem_r;
  wire        beat_last = dw_rem_r <= 12'(AXIS_DW);

  logic [AXIS_BYTE_KEEP-1:0] beat_keep;
  always_comb begin
    beat_keep = '0;
    for (int d = 0; d < AXIS_DW; d++)
      if (12'(d) < beat_dw) beat_keep[d*4 +: 4] = 4'hF;
  end

  assign pay_s_tdata  = s_axis_rq_tdata;
  assign pay_s_tkeep  = beat_keep;
  assign pay_s_tvalid = (state_r == S_PAYLOAD) && s_axis_rq_tvalid;
  // tlast into the gearbox is the wrapper's own count, or the host's when the
  // host ends early -- in the latter case only so the gearbox returns to idle
  // with nothing half-serialized; the beat is then discarded in S_ABORT_FLUSH.
  assign pay_s_tlast  = beat_last || s_axis_rq_tlast;

  // -------------------------------------------------------------------------
  // SS Byte-enable mask on the narrow side, and the counter-derived last.
  // -------------------------------------------------------------------------
  wire first_dw = dw_sent_r == 11'd0;
  wire last_dw  = dw_sent_r == (n_r - 11'd1);

  wire [3:0] keep_mask = (first_dw ? first_be_r : 4'hF) &
                         ((last_dw && (n_r > 11'd1)) ? last_be_r : 4'hF);

  wire payload_to_tl = ((state_r == S_PAYLOAD) || (state_r == S_FLUSH) ||
                        ((state_r == S_DRAIN) && drain_owes_tl_r)) && !cmd_pending_r;

  assign command_data_o       = (state_r == S_ABORT_TERM) ? '0 : pay_m_tdata;
  assign command_keep_o       = (state_r == S_ABORT_TERM) ? '0
                                                          : (pay_m_tkeep & keep_mask);
  assign command_data_valid_o = (state_r == S_ABORT_TERM) ? 1'b1
                                                          : (payload_to_tl && pay_m_tvalid);
  // Derived from n_r and dw_sent_r ONLY -- never from s_axis_rq_tlast.
  assign command_data_last_o  = (state_r == S_ABORT_TERM) ? 1'b1
                                                          : (payload_to_tl && last_dw);

  assign pay_m_tready = (state_r == S_ABORT_FLUSH) ? 1'b1
                                                   : (payload_to_tl && command_data_ready_i);

  // -------------------------------------------------------------------------
  // Command port
  // -------------------------------------------------------------------------
  assign command_valid_o        = cmd_pending_r;
  assign command_o              = cmd_r;
  assign command_address_o      = addr_r;
  assign command_byte_count_o   = bc_r;
  assign command_tc_o           = tc_r;
  assign command_attr_o         = attr_r;
  // Echoed back on the completion so pcie_rc_if (2a-ii) can rebuild the RC
  // descriptor's Lower Address [11:7], which the parsed header only carries
  // down to [6:0] (tlp_parser.sv:188).
  //
  // [11:0] is the request's address[11:0]; [12] says whether those bits are a
  // BYTE ADDRESS at all. They are only for Memory Reads: PCIe defines Lower
  // Address solely for Memory Read Completions and every other completion
  // carries 0 (the same rule tlp_layer.sv:371-378 applies when it seeds the
  // tracker), and a Configuration request's addr_r is a
  // {BDF, ExtReg, Register#, offset} Dword rather than a byte address, so
  // echoing its [11:7] into a Lower Address would be inventing a value. This
  // bit is what lets pcie_rc_if drive Lower Address [11:7] from the echo for a
  // memory read and hard 0 for everything else without guessing.
  //
  // Posted memory writes never produce a completion, so [12] is set for
  // TLP_CMD_MEM_READ only -- the one command whose completion has a Lower
  // Address the RC descriptor must reproduce.
  assign command_context_o      = {{(CONTEXT_WIDTH-13){1'b0}}, mem_read_r,
                                   addr_r[11:0]};
  assign command_prefix_valid_o = 1'b0;   // TLP prefixes out of scope
  assign command_prefix_o       = 32'd0;
  assign command_ecrc_enable_o  = 1'b0;   // the TL computes ECRC itself

  // -------------------------------------------------------------------------
  // AXIS ready
  // -------------------------------------------------------------------------
  always_comb begin
    unique case (state_r)
      S_DESC:    s_axis_rq_tready = !cmd_pending_r;
      S_PAYLOAD: s_axis_rq_tready = pay_s_tready;
      S_DRAIN:   s_axis_rq_tready = 1'b1;
      default:   s_axis_rq_tready = 1'b0;
    endcase
  end

  wire desc_beat = (state_r == S_DESC) && s_axis_rq_tvalid && s_axis_rq_tready;
  wire pay_beat  = (state_r == S_PAYLOAD) && s_axis_rq_tvalid && s_axis_rq_tready;
  wire tl_beat   = command_data_valid_o && command_data_ready_i;

  // -------------------------------------------------------------------------
  // Sequential
  // -------------------------------------------------------------------------
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r             <= S_DESC;
      cmd_r               <= TLP_CMD_MEM_READ;
      addr_r              <= '0;
      bc_r                <= '0;
      tc_r                <= '0;
      attr_r              <= '0;
      mem_read_r          <= 1'b0;
      n_r                 <= 11'd1;
      first_be_r          <= 4'h0;
      last_be_r           <= 4'h0;
      dw_rem_r            <= '0;
      dw_sent_r           <= '0;
      cmd_pending_r       <= 1'b0;
      drain_owes_tl_r     <= 1'b0;
      pcie_rq_tag_o       <= 8'h00;
      pcie_rq_tag_vld_o   <= 1'b0;
      rq_protocol_error_o <= 1'b0;
      rq_error_code_o     <= RQ_ERR_NONE;
    end else begin
      rq_protocol_error_o <= 1'b0;
      pcie_rq_tag_vld_o   <= 1'b0;

      if (cmd_pending_r && command_ready_i) cmd_pending_r <= 1'b0;
      if (tl_beat && (state_r != S_ABORT_TERM)) dw_sent_r <= dw_sent_r + 11'd1;

      // Core-managed tag. Forwarded from the tracker's allocation strobe, not
      // from the descriptor accept: the tag does not exist yet at accept time
      // (tlp_requester.sv:247, 251-252). Registered rather than combinational,
      // like every other output here, so nothing drives a path from inside the
      // TL straight out to the host. One presented tag per emitted TLP, in
      // issue order; posted writes allocate nothing and so never appear.
      if (allocated_tag_valid_i) begin
        pcie_rq_tag_o     <= allocated_tag_i;
        pcie_rq_tag_vld_o <= 1'b1;
      end

      unique case (state_r)
        // -------------------------------------------------------------- beat 0
        S_DESC: if (desc_beat) begin
          if (desc_reject) begin
            rq_protocol_error_o <= 1'b1;
            rq_error_code_o     <= desc_error;
            $warning("pcie_rq_if: rejected RQ descriptor (code %0d, type %0d, dw_count %0d, first_be 0x%0h, last_be 0x%0h)",
                     desc_error, desc.req_type, desc_n, desc_first_be, desc_last_be);
            drain_owes_tl_r <= 1'b0;
            state_r         <= s_axis_rq_tlast ? S_DESC : S_DRAIN;
          end else begin
            // Stage D-2 tripwire, NO behaviour change: see the DEFERRED note
            // in the header.  Type 0 only -- a Type 1 request legitimately
            // names any device on its remote bus.
            if ((desc_cmd == TLP_CMD_CFG_READ0 ||
                 desc_cmd == TLP_CMD_CFG_WRITE0) &&
                desc.completer_id[7:3] != 5'd0)
              $warning("pcie_rq_if: Type 0 config request to device %0d (BDF 0x%04h) admitted and forwarded unchanged -- Base 2.1 SS7.3.1 p.479 wants UR termination once a sweep-capable requester exists (deferred, Stage D brief SS8.1)",
                       desc.completer_id[7:3], desc.completer_id);
            cmd_r         <= desc_cmd;
            addr_r        <= desc_address;
            bc_r          <= desc_bc;
            tc_r          <= desc.tc;
            attr_r        <= desc.attr;
            mem_read_r    <= desc_cmd == TLP_CMD_MEM_READ;
            n_r           <= desc_n;
            first_be_r    <= desc_first_be;
            last_be_r     <= desc_last_be;
            dw_rem_r      <= {1'b0, desc_n};
            dw_sent_r     <= '0;
            cmd_pending_r <= 1'b1;
            state_r <= desc_has_data ? S_PAYLOAD : S_DESC;
          end
        end

        // ------------------------------------------------------------ payload
        S_PAYLOAD: if (pay_beat) begin
          dw_rem_r <= dw_rem_r - beat_dw;
          if (s_axis_rq_tlast && !beat_last) begin
            // Case (b): the host ended before the Dword Count was satisfied.
            rq_protocol_error_o <= 1'b1;
            rq_error_code_o     <= RQ_ERR_EARLY_LAST;
            $warning("pcie_rq_if: s_axis_rq_tlast %0d Dwords before the descriptor's Dword Count %0d was met",
                     dw_rem_r - beat_dw, n_r);
            state_r <= S_ABORT_FLUSH;
          end else if (!s_axis_rq_tlast && beat_last) begin
            // The host kept going past the Dword Count. The TL has already had
            // every Dword it was promised, so let this request complete
            // normally and drain the surplus rather than corrupting it.
            rq_protocol_error_o <= 1'b1;
            rq_error_code_o     <= RQ_ERR_MISSING_LAST;
            $warning("pcie_rq_if: beats continue past the descriptor's Dword Count %0d", n_r);
            drain_owes_tl_r <= 1'b1;
            state_r         <= S_DRAIN;
          end else if (beat_last) begin
            state_r <= S_FLUSH;
          end
        end

        // ------------- AXIS side done; wait for the TL to take every Dword
        S_FLUSH: if (tl_beat && last_dw) state_r <= S_DESC;

        // --------------------------------------------------- abort, case (b)
        // Discard whatever the gearbox still holds so no fragment of the
        // malformed packet can prepend itself to the next one.
        S_ABORT_FLUSH: if (pay_m_tvalid && pay_m_tlast) state_r <= S_ABORT_TERM;

        S_ABORT_TERM: if (command_data_ready_i) state_r <= S_DESC;

        // ---------------------------------------------------------- draining
        // If the TL is still owed Dwords when the surplus ends, finish paying
        // them out in S_FLUSH rather than dropping back to S_DESC and stalling.
        S_DRAIN: if (s_axis_rq_tvalid && s_axis_rq_tlast) begin
          drain_owes_tl_r <= 1'b0;
          state_r <= (drain_owes_tl_r && (dw_sent_r != n_r)) ? S_FLUSH : S_DESC;
        end

        default: state_r <= S_DESC;
      endcase
    end
  end

endmodule
