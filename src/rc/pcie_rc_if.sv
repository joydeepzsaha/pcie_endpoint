// ---------------------------------------------------------------------------
// pcie_rc_if -- PG213 Requester Completion (RC) AXI4-Stream master. Commit 2a-ii.
//
// The mirror of pcie_rq_if. It takes the completions the Transaction Layer has
// received and parsed, builds the 96-bit / 3-Dword RC descriptor (PG213 v1.3
// Fig 56 / Table 65, via the addendum -- cited as such, the PDF is still
// unavailable), and streams descriptor-then-payload out on m_axis_rc_* at 128
// bits. Payload rides pcie_axis_dw_upsize (Commit 2a-0, ccb2a52).
//
// ---------------------------------------------------------------------------
// SS THE ALIGNMENT PROBLEM (the reason this module has a header register)
// ---------------------------------------------------------------------------
//
// The TL presents a received completion on TWO surfaces that are one cycle
// apart:
//
//   (a) the parsed header, COMBINATIONAL -- received_completion_header_o is a
//       direct assign from parsed_header (tlp_layer.sv:219), valid in the cycle
//       its handshake fires;
//
//   (b) the tracker's digest -- result_valid_o / result_context_o /
//       result_status_o / result_last_o, all REGISTERED, set on the cycle AFTER
//       the tracker accepts that header (tlp_request_tracker.sv:123, 137-142).
//
// So at the cycle result_* describes completion N, received_completion_header_o
// may already be showing completion N+1. Building the descriptor from the
// combinational header at result time therefore pairs header N+1 with result N
// and emits a descriptor whose Tag belongs to a different completion than its
// payload -- silently, with correct-looking framing. No FIFO absorbs this;
// it is a mis-pairing, not latency.
//
// The fix is structural: hdr_r captures the header ON ITS OWN HANDSHAKE, so by
// the time result_* is valid the two are the same completion by construction.
// Everything downstream reads hdr_r, never received_completion_header_i.
//
// The window is real and not merely theoretical: two back-to-back Cpls with no
// data put header N+1's handshake in exactly the cycle result N is captured
// (both need only that this module be in S_IDLE). U10 drives that case.
//
// ---------------------------------------------------------------------------
// SS SKID DEPTH: ONE, AND WHY THAT IS PROVABLE RATHER THAN LUCKY
// ---------------------------------------------------------------------------
//
// result_valid_o is NOT a free-running pulse the wrapper must catch or lose.
// It is a registered valid with a real handshake:
//
//   tlp_request_tracker.sv:77   completion_ready_o = !result_valid_r || result_ready_i
//   tlp_request_tracker.sv:110  if (result_valid_r && result_ready_i) result_valid_r <= 0
//
// Holding result_ready_o low therefore stalls the tracker's completion_ready_o,
// which stalls parsed_header_ready (tlp_layer.sv:240-241), which stalls the
// whole RX completion path at the parser. The wrapper can push back all the way
// upstream, so nothing has to be buffered "just in case".
//
// That bounds the outstanding work at exactly one header beyond the one being
// serialized:
//
//   T    header N handshakes (this module in S_IDLE)
//   T+1  result N valid; captured into desc_r; state leaves S_IDLE.
//        header N+1 MAY handshake in this same cycle -- hdr_r still reads
//        header N here and takes header N+1 at the edge, which is correct.
//   T+2. state is not S_IDLE, so received_completion_ready_o is low and no
//        header N+2 can be accepted; result N+1 sits in the tracker's own
//        register with result_ready_o low until this module is idle again.
//
// One header register plus one descriptor register is sufficient and a deeper
// skid would buy nothing. This is the answer to the "size the skid from the
// evidence" question, and the evidence is the two tracker lines above.
//
// ---------------------------------------------------------------------------
// SS PACKING: LET CONCATENATION DO THE WORK
// ---------------------------------------------------------------------------
//
// The descriptor is 3 Dwords and a 128-bit beat holds 4. The gearbox is fed
// desc0, desc1, desc2, payload0, payload1, ... in order, so beat 0 comes out as
// {payload DW0, desc DW2, desc DW1, desc DW0} and every later beat is offset by
// one Dword -- which IS the PG213 Dword-aligned RC layout. There is no rotation
// logic here and no DESC_DW parameter in the gearbox; it stays descriptor-blind
// exactly as ccb2a52 intended (pcie_axis_dw_upsize.sv:22-25).
//
// ---------------------------------------------------------------------------
// SS LOWER ADDRESS [11:7]
// ---------------------------------------------------------------------------
//
// A CPL header carries Lower Address only as [6:0] (tlp_parser.sv:188); the
// descriptor field is 12 bits. The missing [11:7] comes from the request, via
// the command_context_i -> result_context_o echo that pcie_rq_if already loads
// with the request's address[11:0] plus a "these are byte-address bits" flag in
// [12] (pcie_rq_if.sv, command_context_o). That echo is this design's Split
// Completion Table: PG213's own block keeps a real table keyed by tag, and the
// tracker's per-tag context register is the same storage without the extra
// structure.
//
// [12] clear means the request was not a Memory Read, and PCIe defines Lower
// Address only for Memory Read Completions -- every other completion carries 0
// (the rule tlp_layer.sv:371-378 already applies when seeding the tracker). The
// wrapper then drives [11:7] as 0 rather than echoing a Configuration request's
// {ExtReg, Register#, offset} Dword, which is not a byte address at all.
//
// ---------------------------------------------------------------------------
// SS ERROR CODE (descriptor [15:12])
// ---------------------------------------------------------------------------
//
//   status != SC ...... 0010 RC_DESC_ERR_BAD_STATUS  (terminated by UR/CA/CRS)
//   else poisoned ..... 0001 RC_DESC_ERR_POISONED
//   else .............. 0000 RC_DESC_ERR_NORMAL
//
// Status is checked first because "the request was terminated by a completion
// with UR/CA/CRS status" is the dominant fact about the completion; such a
// completion carries no data for the poison bit to qualify.
//
// CRS (010) is carried through as itself, never folded into a generic error: a
// device may legally answer early Configuration reads with CRS and Commit 2b's
// enumeration FSM has to see it to know to retry.
//
// ---------------------------------------------------------------------------
// SS OUT OF SCOPE (documented, not implemented -- KNOWN_GAPS)
// ---------------------------------------------------------------------------
//
//  * Error Code 0011 (RC_DESC_ERR_BAD_LENGTH -- "no data, or byte count
//    overrun") is NEVER DRIVEN, and cannot be, because the TL filters those
//    completions out before they reach this interface. The tracker suppresses
//    the result entirely for a completion with no data when data was expected,
//    or with a byte count overrunning what is outstanding, raising
//    unexpected_completion_o + TLP_ERR_COMPLETION_OVERFLOW instead
//    (tlp_request_tracker.sv:127-135). No result means no RC packet, so the
//    condition is reported on rc_unexpected_completion_o /
//    rc_completion_error_code_o rather than in a descriptor that does not
//    exist. Separately, this interface could not derive it even if a result did
//    arrive: distinguishing "SC Cpl with no data, and none was expected" (a
//    normal Configuration-write completion) from "SC Cpl with no data, but data
//    was expected" (the error) needs the request's expects_data, which the TL
//    keeps private to the tracker. Rather than invent a value, the field reads
//    0000 and this gap is stated.
//
//  * Split memory reads: Lower Address [11:7] is the FIRST completion's, taken
//    from the context echo. On the 2nd and later CPLs of a split read the
//    correct value is that completion's own first byte, which needs a running
//    byte count this module does not keep. Configuration completions never
//    split (Dword Count is always 1), so this cannot affect Commit 2b's
//    enumeration; a memory-read DMA consumer would need it.
//
//  * tuser. PG213's RC tuser carries per-byte enables, is_sof/is_eof position
//    markers and discontinue. Not driven -- the same descriptor-layer scope cut
//    pcie_rq_if made, and the straddle/position markers only mean anything on
//    the 256/512-bit interfaces this design does not build.
//
//  * Locked Read Completions (descriptor [29]): tied 0. TLP_TYPE_CPL_LOCK has
//    no origination path (pcie_rq_if rejects RQ_MEM_RD_LOCKED), so a locked
//    completion can never be one of ours.
//
//  * Byte Count Modified (CPL header bit) is parsed by the TL
//    (tlp_parser.sv:167) but has no field in the RC descriptor, so it is not
//    forwarded.
//
// Guards use $warning, never $error: a procedural $error maps to $stop under
// the simulator, which would abort the shared multi-test process -- and several
// tests here deliberately trip these guards.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_rc_if
  import tlp_pkg::*;
  import pcie_rq_rc_pkg::*;
#(
    parameter int AXIS_DATA_WIDTH = 128,
    // PG213 m_axis_rc_tkeep is DWORD-granular: one bit per Dword. The gearbox
    // is byte-granular on both sides (a deliberate 2a-0 decision), so the
    // reduction happens here, on the descriptor layer, where it belongs.
    parameter int AXIS_KEEP_WIDTH = AXIS_DATA_WIDTH / 32,
    parameter int TL_DATA_WIDTH   = 32,
    parameter int TL_KEEP_WIDTH   = TL_DATA_WIDTH / 8,
    parameter int CONTEXT_WIDTH   = 16
) (
    input  logic                        clk_i,
    input  logic                        rst_i,

    // ---- TL received-completion header -----------------------------------
    // Wire straight to tlp_layer's received_completion_valid_o /
    // received_completion_header_o / received_completion_ready_i.
    input  logic                        received_completion_valid_i,
    output logic                        received_completion_ready_o,
    input  tlp_header_t                 received_completion_header_i,

    // ---- TL received-completion payload ----------------------------------
    input  logic [TL_DATA_WIDTH-1:0]    received_completion_data_i,
    input  logic [TL_KEEP_WIDTH-1:0]    received_completion_keep_i,
    input  logic                        received_completion_data_valid_i,
    input  logic                        received_completion_data_last_i,
    output logic                        received_completion_data_ready_o,

    // ---- TL request-tracker digest ---------------------------------------
    // A registered valid with a real handshake, not a pulse to be caught --
    // see SS SKID DEPTH above.
    input  logic                        result_valid_i,
    output logic                        result_ready_o,
    input  logic [CONTEXT_WIDTH-1:0]    result_context_i,
    input  logic [2:0]                  result_status_i,
    input  logic                        result_last_i,
    // One-cycle pulses from the tracker; no handshake, and no result
    // accompanies them, so no RC packet is fabricated for them.
    input  logic                        unexpected_completion_i,
    input  tlp_error_e                  completion_error_code_i,

    // ---- PG213 Requester Completion AXI4-Stream master -------------------
    output logic [AXIS_DATA_WIDTH-1:0]  m_axis_rc_tdata,
    output logic [AXIS_KEEP_WIDTH-1:0]  m_axis_rc_tkeep,
    output logic                        m_axis_rc_tvalid,
    output logic                        m_axis_rc_tlast,
    input  logic                        m_axis_rc_tready,

    // ---- error surface ---------------------------------------------------
    // The completion had no matching outstanding tag, or overran its byte
    // count. Forwarded from the tracker; NO RC packet accompanies it.
    output logic                        rc_unexpected_completion_o,
    output tlp_error_e                  rc_completion_error_code_o,
    // One-cycle pulse about the PAYLOAD stream; rc_error_code_o is valid in the
    // same cycle and holds until the next pulse.
    output logic                        rc_protocol_error_o,
    output rc_error_e                   rc_error_code_o,
    // Forwarded from the descriptor/payload gearbox: illegal tkeep.
    output logic                        rc_gearbox_error_o
);

  localparam int DESC_DWORDS    = 3;                        // PG213 Table 65
  localparam int AXIS_BYTE_KEEP = AXIS_DATA_WIDTH / 8;      // gearbox tkeep

  // -------------------------------------------------------------------------
  // SS Header capture -- the alignment fix
  // -------------------------------------------------------------------------
  tlp_header_t hdr_r;
  wire hdr_beat = received_completion_valid_i && received_completion_ready_o;
  wire hdr_has_data = tlp_has_data(hdr_r.fmt);

  // -------------------------------------------------------------------------
  // Descriptor build. Every field reads hdr_r (the ALIGNED header) or the
  // tracker digest; received_completion_header_i is deliberately read nowhere
  // below.
  // -------------------------------------------------------------------------
  // [11:7] only when the echo says the request was a Memory Read.
  wire [4:0] lower_address_high = result_context_i[12] ? result_context_i[11:7] : 5'd0;

  rc_desc_error_e desc_error_code;
  always_comb begin
    if      (result_status_i != TLP_CPL_SC) desc_error_code = RC_DESC_ERR_BAD_STATUS;
    else if (hdr_r.poisoned)                desc_error_code = RC_DESC_ERR_POISONED;
    else                                    desc_error_code = RC_DESC_ERR_NORMAL;
  end

  rc_descriptor_t desc_next;
  always_comb begin
    desc_next                   = '0;   // every Reserved field reads 0
    desc_next.lower_address     = {lower_address_high, hdr_r.lower_address};
    desc_next.error_code        = desc_error_code;
    desc_next.byte_count        = hdr_r.byte_count;
    desc_next.locked_read       = 1'b0;                     // KNOWN_GAP, see header
    // Bit 30 is last-CPL-of-the-REQUEST, not last-beat-of-this-CPL. The tracker
    // computes exactly that: !expects_data || status != SC ||
    // payload_bytes >= remaining (tlp_request_tracker.sv:140-142), i.e. the
    // request is finished. Commit 2b releases tags on it, so driving it from a
    // beat counter instead would corrupt tags far from here.
    desc_next.request_completed = result_last_i;
    // Payload Dwords IN THIS packet -- 0 for a Cpl with no data.
    desc_next.dword_count       = hdr_has_data ? hdr_r.length_dw : 11'd0;
    desc_next.completion_status = hdr_r.completion_status;
    desc_next.poisoned          = hdr_r.poisoned;
    desc_next.requester_id      = hdr_r.requester_id;
    desc_next.tag               = hdr_r.tag;
    desc_next.completer_id      = hdr_r.completer_id;
    desc_next.tc                = hdr_r.traffic_class;
    desc_next.attr              = hdr_r.attributes;
  end

  // -------------------------------------------------------------------------
  // FSM
  // -------------------------------------------------------------------------
  typedef enum logic [1:0] {
    S_IDLE,     // waiting for a result; draining any payload that has none
    S_DESC,     // pushing the 3 descriptor Dwords into the gearbox
    S_PAYLOAD   // forwarding completion payload into the gearbox
  } rc_state_e;

  rc_state_e      state_r;
  rc_descriptor_t desc_r;
  logic [1:0]     desc_idx_r;   // 0..2
  logic [11:0]    dw_rem_r;     // payload Dwords still owed to the gearbox
  logic           has_data_r;

  wire [95:0] desc_bits = desc_r;

  // The header stream is accepted only when idle: that is what keeps hdr_r from
  // being overwritten while its own result is still in flight, and what bounds
  // the design to a depth-1 skid.
  assign received_completion_ready_o = (state_r == S_IDLE);
  assign result_ready_o              = (state_r == S_IDLE);

  // -------------------------------------------------------------------------
  // Descriptor/payload gearbox, 32 -> 128.
  // -------------------------------------------------------------------------
  logic [TL_DATA_WIDTH-1:0]   gb_tdata;
  logic [TL_KEEP_WIDTH-1:0]   gb_tkeep;
  logic                       gb_tvalid, gb_tlast, gb_tready;
  logic [AXIS_DATA_WIDTH-1:0] gb_m_tdata;
  logic [AXIS_BYTE_KEEP-1:0]  gb_m_tkeep;

  always_comb begin
    gb_tdata  = received_completion_data_i;
    gb_tkeep  = received_completion_keep_i;
    gb_tvalid = 1'b0;
    gb_tlast  = 1'b0;
    unique case (state_r)
      S_DESC: begin
        unique case (desc_idx_r)
          2'd0:    gb_tdata = desc_bits[31:0];
          2'd1:    gb_tdata = desc_bits[63:32];
          default: gb_tdata = desc_bits[95:64];
        endcase
        gb_tkeep  = {TL_KEEP_WIDTH{1'b1}};
        gb_tvalid = 1'b1;
        // A Cpl with no data is a descriptor-only packet: tlast lands on the
        // third descriptor Dword and the gearbox emits the partial beat at once.
        gb_tlast  = (desc_idx_r == 2'(DESC_DWORDS - 1)) && !has_data_r;
      end
      S_PAYLOAD: begin
        gb_tvalid = received_completion_data_valid_i;
        // Counter-derived, like pcie_rq_if's command_data_last_o: the header's
        // own Dword Count decides where the packet ends. The stream's tlast is
        // ORed in only so a short payload cannot wedge the gearbox mid-word;
        // the disagreement is reported below.
        gb_tlast  = (dw_rem_r == 12'd1) || received_completion_data_last_i;
      end
      default: ;
    endcase
  end

  // Payload is taken only in S_PAYLOAD. The S_IDLE case is the orphan drain:
  // a completion the tracker rejected still has its payload replayed by the
  // parser, and nothing else will ever consume it, so the RX path would wedge.
  // It is gated on !result_valid_i because a GOOD completion's first payload
  // Dword and its result arrive in the same cycle -- draining unconditionally
  // would eat payload Dword 0.
  assign received_completion_data_ready_o =
      (state_r == S_PAYLOAD) ? gb_tready :
      (state_r == S_IDLE)    ? !result_valid_i : 1'b0;

  wire gb_beat  = gb_tvalid && gb_tready;
  wire orphan_beat = received_completion_data_valid_i &&
                     received_completion_data_ready_o && (state_r == S_IDLE);

  pcie_axis_dw_upsize #(
      .DATA_WIDTH_NARROW(TL_DATA_WIDTH),
      .DATA_WIDTH_WIDE  (AXIS_DATA_WIDTH)
  ) u_rc_pack (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata (gb_tdata),  .s_axis_tkeep (gb_tkeep),
      .s_axis_tvalid(gb_tvalid), .s_axis_tlast (gb_tlast),
      .s_axis_tready(gb_tready),
      .m_axis_tdata (gb_m_tdata), .m_axis_tkeep (gb_m_tkeep),
      .m_axis_tvalid(m_axis_rc_tvalid), .m_axis_tlast(m_axis_rc_tlast),
      .m_axis_tready(m_axis_rc_tready),
      .gearbox_error_o(rc_gearbox_error_o)
  );

  assign m_axis_rc_tdata = gb_m_tdata;

  // Byte-granular -> Dword-granular. Completion payload is Dword-granular on
  // the wire (byte significance is conveyed by Lower Address and Byte Count,
  // not by the payload's keep), so each nibble is 0x0 or 0xF and the reduction
  // is lossless.
  always_comb begin
    for (int d = 0; d < AXIS_KEEP_WIDTH; d++)
      m_axis_rc_tkeep[d] = |gb_m_tkeep[d*4 +: 4];
  end

  // -------------------------------------------------------------------------
  // Sequential
  // -------------------------------------------------------------------------
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_r                    <= S_IDLE;
      hdr_r                      <= '0;
      desc_r                     <= '0;
      desc_idx_r                 <= 2'd0;
      dw_rem_r                   <= '0;
      has_data_r                 <= 1'b0;
      rc_unexpected_completion_o <= 1'b0;
      rc_completion_error_code_o <= TLP_ERR_NONE;
      rc_protocol_error_o        <= 1'b0;
      rc_error_code_o            <= RC_ERR_NONE;
    end else begin
      rc_protocol_error_o        <= 1'b0;
      // Forwarded, not re-derived: an unexpected or overrunning completion
      // never becomes a result, so it never becomes an RC packet either.
      rc_unexpected_completion_o <= unexpected_completion_i;
      rc_completion_error_code_o <= completion_error_code_i;

      // SS The alignment capture. hdr_r is written on the HEADER's handshake,
      // one cycle before its result, so the pair read in S_IDLE below is always
      // the same completion.
      if (hdr_beat) hdr_r <= received_completion_header_i;

      unique case (state_r)
        S_IDLE: begin
          if (orphan_beat) begin
            rc_protocol_error_o <= 1'b1;
            rc_error_code_o     <= RC_ERR_ORPHAN_DATA;
            $warning("pcie_rc_if: completion payload Dword 0x%08h with no result behind it -- drained",
                     received_completion_data_i);
          end
          if (result_valid_i && result_ready_o) begin
            // Alignment tripwire. The tracker copies the header's own
            // completion_status into result_status_r (tlp_request_tracker.sv:
            // 139), so these two can only disagree if hdr_r and result_* have
            // come apart -- the exact failure this module is built to prevent.
            // It does not catch every mis-pairing (two completions with the
            // same status look identical here), so it supplements the
            // structural fix rather than standing in for it.
            if (hdr_r.completion_status != result_status_i)
              $warning("pcie_rc_if: header/result misalignment -- header status %0d, result status %0d, tag %0d",
                       hdr_r.completion_status, result_status_i, hdr_r.tag);
            desc_r     <= desc_next;
            has_data_r <= hdr_has_data;
            dw_rem_r   <= hdr_has_data ? {1'b0, hdr_r.length_dw} : 12'd0;
            desc_idx_r <= 2'd0;
            state_r    <= S_DESC;
          end
        end

        // ------------------------------------------------- 3 descriptor Dwords
        S_DESC: if (gb_beat) begin
          if (desc_idx_r == 2'(DESC_DWORDS - 1))
            state_r <= has_data_r ? S_PAYLOAD : S_IDLE;
          else
            desc_idx_r <= desc_idx_r + 2'd1;
        end

        // ------------------------------------------------------------ payload
        S_PAYLOAD: if (gb_beat) begin
          dw_rem_r <= dw_rem_r - 12'd1;
          if (received_completion_data_last_i && (dw_rem_r != 12'd1)) begin
            // The payload stopped short of the header's Dword Count. The RC
            // packet has already been framed with that count, so it goes out
            // truncated and flagged rather than being held open forever.
            rc_protocol_error_o <= 1'b1;
            rc_error_code_o     <= RC_ERR_EARLY_LAST;
            $warning("pcie_rc_if: completion payload ended %0d Dwords before the header's Dword Count %0d",
                     dw_rem_r - 12'd1, hdr_r.length_dw);
            state_r <= S_IDLE;
          end else if (!received_completion_data_last_i && (dw_rem_r == 12'd1)) begin
            // Surplus beats. The gearbox packet is already closed by the
            // counter; the leftovers are swallowed by the S_IDLE orphan drain
            // rather than prepending themselves to the next completion.
            rc_protocol_error_o <= 1'b1;
            rc_error_code_o     <= RC_ERR_MISSING_LAST;
            $warning("pcie_rc_if: completion payload continued past the header's Dword Count %0d",
                     hdr_r.length_dw);
            state_r <= S_IDLE;
          end else if (dw_rem_r == 12'd1) begin
            state_r <= S_IDLE;
          end
        end

        default: state_r <= S_IDLE;
      endcase
    end
  end

endmodule
