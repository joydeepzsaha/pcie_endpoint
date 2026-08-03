// ---------------------------------------------------------------------------
// pcie_axis_dw_upsize -- AXI-Stream width converter, 32 -> 128 (4:1).
//
// Up to four narrow Dword beats are packed into one wide beat, LSB group first.
// On tlast the partial wide beat is emitted IMMEDIATELY with the tkeep actually
// accumulated -- the module never stalls waiting for a fourth beat that is not
// coming.
//
// INTERFACE CONVENTIONS (deliberate, see also pcie_axis_dw_downsize)
//
//  * tkeep is BYTE-GRANULAR on both sides -- s_axis_tkeep[3:0] is one bit per
//    byte of the Dword, m_axis_tkeep[15:0] one bit per byte of the 128-bit
//    word. This makes the module a conventional AXI-Stream width converter and
//    it matches the Transaction Layer's byte-granular command_keep_i
//    (tlp_requester.sv KEEP_WIDTH = DATA_WIDTH/8 = 4).
//
//    NOTE for the RC wrapper (2a-ii), NOT a concern here: PG213's descriptor
//    interfaces carry Dword-granular tkeep plus byte enables in tuser. That
//    translation is a descriptor-layer concern and is deliberately kept OUT of
//    this gearbox.
//
//  * This module is DESCRIPTOR-BLIND. It has no DESC_DW parameter: packing
//    desc0,desc1,desc2,payload0,... reproduces the Dword-aligned RC layout by
//    plain concatenation, so the 3-Dword descriptor "rotation" falls out of the
//    arithmetic for free without any extra state in the fragile module.
//
//  * s_axis_tready IS REGISTERED. It is driven from state only, never from
//    m_axis_tready, so no combinational ready path runs through the gearbox --
//    see the matching note in pcie_axis_dw_downsize. The cost is one turnaround
//    cycle per wide beat (5 clocks per full 128-bit word instead of 4, ~80% of
//    peak); the fix, if ever needed, is an output skid register.
//
// OUT OF SCOPE (documented, not implemented)
//  * Zero-length packets (tvalid with tkeep == 0). Flagged on gearbox_error_o.
//  * Non-contiguous tkeep, and a partial (non-full) tkeep on a beat that is not
//    tlast -- both would punch a hole into the packed word. Flagged on
//    gearbox_error_o and $warning; the beat is still packed verbatim so the
//    corruption stays visible rather than becoming a silent misalignment.
//  * tuser passthrough (a 2a-i/2a-ii concern).
//  * Ratios other than 4:1. The parameters exist, but only 32/128 is verified.
//
// Guards use $warning, never $error: under the simulator a procedural $error
// maps to $stop, which would abort the shared multi-test process.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_axis_dw_upsize #(
    parameter int DATA_WIDTH_NARROW = 32,
    parameter int DATA_WIDTH_WIDE   = 128,
    parameter int KEEP_WIDTH_NARROW = DATA_WIDTH_NARROW / 8,
    parameter int KEEP_WIDTH_WIDE   = DATA_WIDTH_WIDE / 8,
    parameter int RATIO             = DATA_WIDTH_WIDE / DATA_WIDTH_NARROW
) (
    input  logic                         clk_i,
    input  logic                         rst_i,

    // Narrow slave (32-bit, Dword-serial).
    input  logic [DATA_WIDTH_NARROW-1:0] s_axis_tdata,
    input  logic [KEEP_WIDTH_NARROW-1:0] s_axis_tkeep,
    input  logic                         s_axis_tvalid,
    input  logic                         s_axis_tlast,
    output logic                         s_axis_tready,

    // Wide master (128-bit).
    output logic [DATA_WIDTH_WIDE-1:0]   m_axis_tdata,
    output logic [KEEP_WIDTH_WIDE-1:0]   m_axis_tkeep,
    output logic                         m_axis_tvalid,
    output logic                         m_axis_tlast,
    input  logic                         m_axis_tready,

    // One-cycle pulse, coincident with acceptance of an illegal narrow beat.
    output logic                         gearbox_error_o
);

  localparam int PHASE_WIDTH = $clog2(RATIO);

  // Accumulator: fills LSB group first.
  logic [DATA_WIDTH_WIDE-1:0] acc_data_r;
  logic [KEEP_WIDTH_WIDE-1:0] acc_keep_r;
  logic [PHASE_WIDTH-1:0]     phase_r;

  // Output holding register.
  logic [DATA_WIDTH_WIDE-1:0] out_data_r;
  logic [KEEP_WIDTH_WIDE-1:0] out_keep_r;
  logic                       out_last_r;
  logic                       out_valid_r;

  // A narrow beat is legal only if its tkeep is contiguous from bit 0 and
  // non-zero; anything short of full is legal only on the final beat.
  function automatic logic keep_illegal(input logic [KEEP_WIDTH_NARROW-1:0] keep,
                                        input logic                        last);
    keep_illegal = (keep == '0) ||
                   ((keep & (keep + 1'b1)) != '0) ||
                   (!last && (keep != {KEEP_WIDTH_NARROW{1'b1}}));
  endfunction

  // Registered ready: state only, never m_axis_tready.
  assign s_axis_tready = !out_valid_r;

  assign m_axis_tvalid = out_valid_r;
  assign m_axis_tdata  = out_data_r;
  assign m_axis_tkeep  = out_keep_r;
  assign m_axis_tlast  = out_last_r;

  wire accept_beat = s_axis_tvalid && s_axis_tready;
  wire drain_beat  = m_axis_tvalid && m_axis_tready;
  // The accumulator completes on the fourth group, or early on tlast -- the
  // partial word goes out immediately, never waiting for a fourth beat.
  wire word_done   = accept_beat && (s_axis_tlast || (phase_r == PHASE_WIDTH'(RATIO-1)));

  // Accumulator contents with this beat merged in.
  logic [DATA_WIDTH_WIDE-1:0] merged_data;
  logic [KEEP_WIDTH_WIDE-1:0] merged_keep;
  always_comb begin
    merged_data = acc_data_r;
    merged_keep = acc_keep_r;
    merged_data[phase_r*DATA_WIDTH_NARROW +: DATA_WIDTH_NARROW] = s_axis_tdata;
    merged_keep[phase_r*KEEP_WIDTH_NARROW +: KEEP_WIDTH_NARROW] = s_axis_tkeep;
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      // Mid-packet reset drops the half-assembled word on the floor: the
      // accumulator and its keep both clear, so no fragment can leak into the
      // next packet.
      acc_data_r      <= '0;
      acc_keep_r      <= '0;
      phase_r         <= '0;
      out_data_r      <= '0;
      out_keep_r      <= '0;
      out_last_r      <= 1'b0;
      out_valid_r     <= 1'b0;
      gearbox_error_o <= 1'b0;
    end else begin
      gearbox_error_o <= 1'b0;

      if (drain_beat) out_valid_r <= 1'b0;   // releases s_axis_tready next cycle

      if (accept_beat) begin
        if (keep_illegal(s_axis_tkeep, s_axis_tlast)) begin
          gearbox_error_o <= 1'b1;
          $warning("pcie_axis_dw_upsize: illegal tkeep 0x%0h (tlast=%0b); must be contiguous from bit 0, non-zero, and full unless final",
                   s_axis_tkeep, s_axis_tlast);
        end

        if (word_done) begin
          out_data_r  <= merged_data;
          out_keep_r  <= merged_keep;
          out_last_r  <= s_axis_tlast;
          out_valid_r <= 1'b1;
          // Clear the accumulator so the next packet starts from group 0 with
          // no stale keep bits -- the back-to-back-packet leak path.
          acc_data_r  <= '0;
          acc_keep_r  <= '0;
          phase_r     <= '0;
        end else begin
          acc_data_r <= merged_data;
          acc_keep_r <= merged_keep;
          phase_r    <= phase_r + 1'b1;
        end
      end
    end
  end

endmodule
