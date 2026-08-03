`timescale 1ns/1ps
//
// VC0 transmitter-side Flow Control gate.
//
// Implements the two quantities PCIe Base 2.1 SS2.6.1.1 (p.139-140) requires a
// Transmitter to track per credit type:
//
//   CREDIT_LIMIT      -- the most recent number of FC units advertised by the
//                        Receiver, cumulative since FC initialization, mod
//                        2^[Field Size].  Loaded from fc_*_i.  Never decremented.
//   CREDITS_CONSUMED  -- FC units consumed by transmissions since FC
//                        initialization, mod 2^[Field Size].  Zeroed at FC init,
//                        incremented for each TLP allowed through the gate.
//                        Never loaded from the wire.
//
// [Field Size] is 8 for PH/NPH/CPLH and 12 for PD/NPD/CPLD, which is exactly the
// declared width of each register here, so the required mod-2^[Field Size]
// arithmetic falls out of native N-bit wrapping and needs no masking.
//
// fc_*_i carries the raw cumulative CREDITS_ALLOCATED field lifted off the
// InitFC/UpdateFC DLLP (SS2.6.1.2 p.141) -- see get_fc_values in
// pcie_datalink_pkg.sv:247-251 and dllp_handler.sv:283/301/319, which apply no
// arithmetic to it.  It is therefore a LIMIT, not a remainder; treating it as a
// remainder over-states available credit by all consumption preceding the most
// recent update and overruns the Receiver's buffer.
//
// The gate compares remaining credit against the requirement directly rather
// than transcribing the spec's half-space expression.  The two are exactly
// equivalent given the spec's own cap of 2047 data / 127 header outstanding
// unused credits (SS2.6.1 p.138); the derivation, including the single boundary
// where they would differ and why it is unreachable, is in
// SPEC_PREDICTIONS_CREDIT.md SSJ.
//
// error_o -- IMPLEMENTATION-DEFINED, NOT A SPEC-CONFORMANCE SIGNAL.
//
//   The spec defines no transmitter-side flow-control error output at all.
//   Every Flow Control Protocol Error it names -- more than 2047/127 outstanding
//   unused credits (SS2.6.1 p.138), a non-zero UpdateFC field on a type
//   advertised infinite (p.138), Receiver Overflow (SS2.6.1.2 p.141) -- is
//   optional ("Components may optionally check") and associated with the
//   RECEIVING port.  The only obligation SS2.6.1.1 p.140 places on a Transmitter
//   that lacks credit is behavioural: "it must block the transmission of the
//   TLP".  The spec is likewise silent on requests that can never be satisfied.
//   error_o is therefore a local health signal of this implementation's own
//   choosing, and must not be read as conformance reporting.
//
//   MEANING: the presented request needs more data credits than the Receiver's
//   entire advertised buffer for that type, so no amount of credit return can
//   ever admit it.  Ordinary blocking -- capacity sufficient, current remainder
//   not -- is silent, and a pool advertised infinite can never raise it.
//
//   TIMING: registered and self-clearing.  It asserts for the cycle following
//   each cycle in which such a request is presented, and returns low by itself
//   once the request is withdrawn or replaced.  There is no sticky state and
//   nothing to acknowledge.
//
//   VISIBLE AT: tlp_layer exports it as credit_error_o (tlp_layer.sv:482), which
//   drives tx_error_valid_o (:283) and emits TLP_ERR_CREDIT_UNDERFLOW (:286).
//
// FC initialization is distinguished from a subsequent update by fc_init_seen_r:
// fc_update_valid_i is driven by (update_fc || fc_init_done)
// (pcie_datalink_layer.sv:176) and the InitFC1/InitFC2 cases never assert
// update_fc, so the first strobe after reset is the initial advertisement and
// every later one is an update.  See SPEC_PREDICTIONS_CREDIT.md SSI.2.
//
module tlp_credit_manager
  import tlp_pkg::*;
(
    input  logic              clk_i,
    input  logic              rst_i,
    input  logic              fc_initialized_i,
    input  logic              fc_update_valid_i,
    input  logic [7:0]        fc_ph_i,
    input  logic [11:0]       fc_pd_i,
    input  logic [7:0]        fc_nph_i,
    input  logic [11:0]       fc_npd_i,
    input  logic [7:0]        fc_cplh_i,
    input  logic [11:0]       fc_cpld_i,

    input  logic              request_valid_i,
    output logic              request_ready_o,
    input  tlp_credit_class_e request_class_i,
    input  logic [11:0]       request_data_credits_i,

    output logic              blocked_o,
    output logic              error_o,
    output logic [7:0]        posted_header_available_o,
    output logic [11:0]       posted_data_available_o,
    output logic [7:0]        nonposted_header_available_o,
    output logic [11:0]       nonposted_data_available_o,
    output logic [7:0]        completion_header_available_o,
    output logic [11:0]       completion_data_available_o
);

  // CREDIT_LIMIT per pool -- cumulative advertised, never decremented.
  logic [7:0]  ph_limit_r, nph_limit_r, cplh_limit_r;
  logic [11:0] pd_limit_r, npd_limit_r, cpld_limit_r;

  // CREDITS_CONSUMED per pool -- cumulative consumed, never loaded from wire.
  logic [7:0]  ph_consumed_r, nph_consumed_r, cplh_consumed_r;
  logic [11:0] pd_consumed_r, npd_consumed_r, cpld_consumed_r;

  // Set once the initial advertisement has been captured.
  logic fc_init_seen_r;

  // An advertisement of 00h / 000h made AT FC INITIALIZATION means infinite
  // credit for that type (SS2.6.1 p.138; footnote 33 p.137: "interpreted as
  // infinite by the Transmitter, which will, therefore, never throttle").  The
  // determination is latched at initialization and never re-evaluated: the
  // gating rule states it twice as "specified as infinite during Flow Control
  // initialization" (p.140).  Re-deriving it from the live remainder would let a
  // pool consumed down to zero read as infinite, which is a different thing.
  //
  // Infinite is tracked per pool, not per class: SS2.6.1 p.138 contemplates
  // "only the Data or header advertisement (but not both) for a given type
  // (N, NP, or CPL)".  Table 2-37 p.137-138 makes infinite CPLH/CPLD mandatory
  // for the Root Complex an Endpoint faces, so that pair is the normal case
  // rather than an edge case.
  logic ph_infinite_r, nph_infinite_r, cplh_infinite_r;
  logic pd_infinite_r, npd_infinite_r, cpld_infinite_r;

  // The data advertisement made AT INITIALIZATION, i.e. the Receiver's buffer
  // allocation for that type ("CREDITS_ALLOCATED ... Initially set according to
  // the buffer size and allocation policies of the Receiver", SS2.6.1.2 p.141).
  // Kept separately from *_limit_r because that register goes on to track the
  // cumulative allocated count, which wraps and is therefore not a capacity.
  logic [11:0] pd_capacity_r, npd_capacity_r, cpld_capacity_r;

  // Remaining credit = (CREDIT_LIMIT - CREDITS_CONSUMED) mod 2^[Field Size].
  // Native N-bit subtraction supplies the modulo; a wrapped limit -- including
  // one that has wrapped to exactly zero -- needs no special case.
  logic [7:0]  ph_available, nph_available, cplh_available;
  logic [11:0] pd_available, npd_available, cpld_available;

  assign ph_available   = ph_limit_r   - ph_consumed_r;
  assign pd_available   = pd_limit_r   - pd_consumed_r;
  assign nph_available  = nph_limit_r  - nph_consumed_r;
  assign npd_available  = npd_limit_r  - npd_consumed_r;
  assign cplh_available = cplh_limit_r - cplh_consumed_r;
  assign cpld_available = cpld_limit_r - cpld_consumed_r;

  logic selected_header_available;
  logic selected_data_available;
  logic selected_data_infinite;
  logic [11:0] selected_data_capacity;
  logic request_unsatisfiable;

  always_comb begin
    selected_header_available = 1'b0;
    selected_data_available = 1'b0;
    selected_data_infinite = 1'b0;
    selected_data_capacity = '0;
    case (request_class_i)
      TLP_CREDIT_POSTED: begin
        selected_header_available = ph_infinite_r || (ph_available != 0);
        selected_data_available =
            pd_infinite_r || (pd_available >= request_data_credits_i);
        selected_data_infinite = pd_infinite_r;
        selected_data_capacity = pd_capacity_r;
      end
      TLP_CREDIT_COMPLETION: begin
        selected_header_available = cplh_infinite_r || (cplh_available != 0);
        selected_data_available =
            cpld_infinite_r || (cpld_available >= request_data_credits_i);
        selected_data_infinite = cpld_infinite_r;
        selected_data_capacity = cpld_capacity_r;
      end
      default: begin
        selected_header_available = nph_infinite_r || (nph_available != 0);
        selected_data_available =
            npd_infinite_r || (npd_available >= request_data_credits_i);
        selected_data_infinite = npd_infinite_r;
        selected_data_capacity = npd_capacity_r;
      end
    endcase

    // Permanently unsatisfiable: the request needs more data credits than the
    // Receiver's entire advertised buffer for that type, so no amount of credit
    // return can ever admit it.  Distinct from ordinary blocking, where the
    // capacity suffices and only the current remainder does not.  An infinite
    // pool can never qualify.  See the header note on error_o.
    request_unsatisfiable = fc_initialized_i && !selected_data_infinite &&
                            (request_data_credits_i > selected_data_capacity);
    request_ready_o = fc_initialized_i && selected_header_available &&
                      selected_data_available;
    blocked_o = request_valid_i && !request_ready_o;
  end

  assign posted_header_available_o = ph_available;
  assign posted_data_available_o = pd_available;
  assign nonposted_header_available_o = nph_available;
  assign nonposted_data_available_o = npd_available;
  assign completion_header_available_o = cplh_available;
  assign completion_data_available_o = cpld_available;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      ph_limit_r <= '0;
      pd_limit_r <= '0;
      nph_limit_r <= '0;
      npd_limit_r <= '0;
      cplh_limit_r <= '0;
      cpld_limit_r <= '0;
      ph_consumed_r <= '0;
      pd_consumed_r <= '0;
      nph_consumed_r <= '0;
      npd_consumed_r <= '0;
      cplh_consumed_r <= '0;
      cpld_consumed_r <= '0;
      fc_init_seen_r <= 1'b0;
      ph_infinite_r <= 1'b0;
      pd_infinite_r <= 1'b0;
      nph_infinite_r <= 1'b0;
      npd_infinite_r <= 1'b0;
      cplh_infinite_r <= 1'b0;
      cpld_infinite_r <= 1'b0;
      pd_capacity_r <= '0;
      npd_capacity_r <= '0;
      cpld_capacity_r <= '0;
      error_o <= 1'b0;
    end else begin
      error_o <= 1'b0;
      if (fc_update_valid_i) begin
        fc_init_seen_r <= 1'b1;
        if (!fc_init_seen_r) begin
          // FC initialization: capture the advertisement and latch which pools
          // were advertised infinite.
          ph_limit_r <= fc_ph_i;
          pd_limit_r <= fc_pd_i;
          nph_limit_r <= fc_nph_i;
          npd_limit_r <= fc_npd_i;
          cplh_limit_r <= fc_cplh_i;
          cpld_limit_r <= fc_cpld_i;
          ph_infinite_r <= (fc_ph_i == '0);
          pd_infinite_r <= (fc_pd_i == '0);
          nph_infinite_r <= (fc_nph_i == '0);
          npd_infinite_r <= (fc_npd_i == '0);
          cplh_infinite_r <= (fc_cplh_i == '0);
          cpld_infinite_r <= (fc_cpld_i == '0);
          pd_capacity_r <= fc_pd_i;
          npd_capacity_r <= fc_npd_i;
          cpld_capacity_r <= fc_cpld_i;
        end else begin
          // UpdateFC.  For a pool advertised infinite the credit field "must be
          // set to zero and must be ignored" (SS2.6.1 p.138) -- our own DLL
          // forwards those DLLPs (dllp_handler.sv:331-332), so taking the field
          // would destroy the pool.  Everything else takes the new limit.
          if (!ph_infinite_r)   ph_limit_r   <= fc_ph_i;
          if (!pd_infinite_r)   pd_limit_r   <= fc_pd_i;
          if (!nph_infinite_r)  nph_limit_r  <= fc_nph_i;
          if (!npd_infinite_r)  npd_limit_r  <= fc_npd_i;
          if (!cplh_infinite_r) cplh_limit_r <= fc_cplh_i;
          if (!cpld_infinite_r) cpld_limit_r <= fc_cpld_i;
        end
      end
      // CREDITS_CONSUMED is written by exactly one priority chain, so the load
      // and the accumulate can no longer collide on a shared register the way
      // the previous single-register design did.  The init arm cannot mask a
      // grant: at the initialization strobe the limits still hold their reset
      // value, so request_ready_o is low and no grant can occur.
      if (fc_update_valid_i && !fc_init_seen_r) begin
        ph_consumed_r <= '0;
        pd_consumed_r <= '0;
        nph_consumed_r <= '0;
        npd_consumed_r <= '0;
        cplh_consumed_r <= '0;
        cpld_consumed_r <= '0;
      end else if (request_valid_i && request_ready_o) begin
        case (request_class_i)
          TLP_CREDIT_POSTED: begin
            ph_consumed_r <= ph_consumed_r + 1'b1;
            pd_consumed_r <= pd_consumed_r + request_data_credits_i;
          end
          TLP_CREDIT_COMPLETION: begin
            cplh_consumed_r <= cplh_consumed_r + 1'b1;
            cpld_consumed_r <= cpld_consumed_r + request_data_credits_i;
          end
          default: begin
            nph_consumed_r <= nph_consumed_r + 1'b1;
            npd_consumed_r <= npd_consumed_r + request_data_credits_i;
          end
        endcase
      end
      // Normal credit blocking is not a protocol error and stays silent; only a
      // permanently unsatisfiable request raises error_o.
      if (request_valid_i && request_unsatisfiable)
        error_o <= 1'b1;
    end
  end

endmodule
