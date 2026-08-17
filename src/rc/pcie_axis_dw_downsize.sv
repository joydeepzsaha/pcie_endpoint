// ---------------------------------------------------------------------------
// pcie_axis_dw_downsize -- AXI-Stream width converter, 128 -> 32 (4:1).
//
// SPEC ANCHORS: none directly. This module implements no PCIe or PG213 rule --
// it is a plain AXI-Stream width converter. The PG213 Dword-aligned RQ layout
// falls out of concatenation at the caller (pcie_rq_if), never here; see the
// DESCRIPTOR-BLIND note below.
//
// One wide beat is serialized into up to four narrow Dword beats, LSB group
// first. A narrow beat is emitted for every 4-byte group that the wide beat's
// tkeep spans; the final narrow beat carries the partial tkeep verbatim. There
// is no phantom trailing Dword and no dropped Dword: the beat count is the
// index of the highest non-empty 4-byte group plus one.
//
// INTERFACE CONVENTIONS (deliberate, see also pcie_axis_dw_upsize)
//
//  * tkeep is BYTE-GRANULAR on both sides -- s_axis_tkeep[15:0] is one bit per
//    byte of the 128-bit word, m_axis_tkeep[3:0] one bit per byte of the Dword.
//    This makes the module a conventional AXI-Stream width converter and it
//    matches the Transaction Layer's byte-granular command_keep_i
//    (tlp_requester.sv KEEP_WIDTH = DATA_WIDTH/8 = 4).
//
//    NOTE for the RQ wrapper (2a-i), NOT a concern here: PG213's
//    s_axis_rq_tkeep is DWORD-granular (4 bits for a 128-bit interface) and the
//    byte enables live in tuser as first_be/last_be. That DW-granular ->
//    byte-granular translation is a descriptor-layer concern and belongs to
//    pcie_rq_if. It is deliberately kept OUT of this gearbox.
//
//  * This module is DESCRIPTOR-BLIND. It has no DESC_DW parameter and no
//    knowledge of PG213 descriptor layout; feeding it desc0,desc1,desc2,payload
//    reproduces the Dword-aligned RQ/RC layout by plain concatenation.
//
//  * s_axis_tready IS REGISTERED. It is driven from state only, never from
//    m_axis_tready, so no combinational ready path runs through the gearbox.
//    The TL's command_data_ready_o is already combinational
//    (tlp_requester.sv:196); chaining a second combinational ready through here
//    would build a long path that simulation ignores and synthesis does not.
//    The cost is one turnaround cycle per wide beat: a full 128-bit beat
//    occupies 5 clocks (4 data + 1 reload) rather than 4, i.e. ~80% of peak.
//    If that is ever measured to matter, the fix is a prefetch/skid register on
//    the wide input, not a combinational tready.
//
// OUT OF SCOPE (documented, not implemented)
//  * Zero-length packets (tvalid with tkeep == 0). Flagged on gearbox_error_o.
//  * Non-contiguous tkeep. Illegal AXI-Stream; flagged on gearbox_error_o and
//    $warning. The beats spanning the pattern are still emitted verbatim (which
//    may include a zero-keep beat) -- data is never invented, moved or dropped,
//    so the corruption stays visible instead of turning into silent
//    misalignment.
//  * tuser passthrough (a 2a-i concern -- first_be/last_be ride in tuser).
//  * Ratios other than 4:1. The parameters exist, but only 128/32 is verified.
//
// Guards use $warning, never $error: under the simulator a procedural $error
// maps to $stop, which would abort the shared multi-test process that
// deliberately trips this guard.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module pcie_axis_dw_downsize #(
    parameter int DATA_WIDTH_WIDE   = 128,
    parameter int DATA_WIDTH_NARROW = 32,
    parameter int KEEP_WIDTH_WIDE   = DATA_WIDTH_WIDE / 8,
    parameter int KEEP_WIDTH_NARROW = DATA_WIDTH_NARROW / 8,
    parameter int RATIO             = DATA_WIDTH_WIDE / DATA_WIDTH_NARROW
) (
    input  logic                         clk_i,
    input  logic                         rst_i,

    // Wide slave (128-bit).
    input  logic [DATA_WIDTH_WIDE-1:0]   s_axis_tdata,
    input  logic [KEEP_WIDTH_WIDE-1:0]   s_axis_tkeep,
    input  logic                         s_axis_tvalid,
    input  logic                         s_axis_tlast,
    output logic                         s_axis_tready,

    // Narrow master (32-bit, Dword-serial).
    output logic [DATA_WIDTH_NARROW-1:0] m_axis_tdata,
    output logic [KEEP_WIDTH_NARROW-1:0] m_axis_tkeep,
    output logic                         m_axis_tvalid,
    output logic                         m_axis_tlast,
    input  logic                         m_axis_tready,

    // One-cycle pulse, coincident with acceptance of an illegal wide beat
    // (non-contiguous tkeep, or tvalid with tkeep == 0). Informational: the
    // beat is still processed as described above.
    output logic                         gearbox_error_o
);

  localparam int PHASE_WIDTH = $clog2(RATIO);

  logic [DATA_WIDTH_WIDE-1:0] data_r;
  logic [KEEP_WIDTH_WIDE-1:0] keep_r;
  logic                       last_r;
  logic                       busy_r;
  logic [PHASE_WIDTH-1:0]     phase_r;   // group currently presented
  logic [PHASE_WIDTH:0]       beats_r;   // total groups this wide beat spans

  // Index of the highest non-empty KEEP_WIDTH_NARROW-byte group, plus one.
  // For the legal (contiguous-from-LSB) patterns this is ceil(popcount/4); for
  // an illegal pattern it still spans every group holding a valid byte, so no
  // byte is silently dropped.
  function automatic logic [PHASE_WIDTH:0] group_span(input logic [KEEP_WIDTH_WIDE-1:0] keep);
    group_span = '0;
    for (int g = 0; g < RATIO; g++)
      if (|keep[g*KEEP_WIDTH_NARROW +: KEEP_WIDTH_NARROW])
        group_span = (PHASE_WIDTH+1)'(g + 1);
  endfunction

  // Legal tkeep is contiguous from bit 0, i.e. (1<<n)-1 for n > 0.
  function automatic logic keep_illegal(input logic [KEEP_WIDTH_WIDE-1:0] keep);
    keep_illegal = (keep == '0) || ((keep & (keep + 1'b1)) != '0);
  endfunction

  wire load_beat = s_axis_tvalid && s_axis_tready;
  wire last_group = busy_r && (({1'b0, phase_r} + 1'b1) >= beats_r);
  wire drain_beat = m_axis_tvalid && m_axis_tready;

  // Registered ready: state only, never m_axis_tready.
  assign s_axis_tready = !busy_r;

  assign m_axis_tvalid = busy_r;
  assign m_axis_tdata  = data_r[phase_r*DATA_WIDTH_NARROW +: DATA_WIDTH_NARROW];
  assign m_axis_tkeep  = keep_r[phase_r*KEEP_WIDTH_NARROW +: KEEP_WIDTH_NARROW];
  // tlast only on the final narrow beat derived from the wide beat that carried it.
  assign m_axis_tlast  = last_r && last_group;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      // Mid-packet reset returns to idle with nothing half-serialized: busy_r
      // low means the holding register is dead, so no fragment can prepend
      // itself to the next packet.
      busy_r          <= 1'b0;
      phase_r         <= '0;
      beats_r         <= '0;
      data_r          <= '0;
      keep_r          <= '0;
      last_r          <= 1'b0;
      gearbox_error_o <= 1'b0;
    end else begin
      gearbox_error_o <= 1'b0;

      if (load_beat) begin
        data_r  <= s_axis_tdata;
        keep_r  <= s_axis_tkeep;
        last_r  <= s_axis_tlast;
        beats_r <= group_span(s_axis_tkeep);
        phase_r <= '0;
        busy_r  <= 1'b1;
        if (keep_illegal(s_axis_tkeep)) begin
          gearbox_error_o <= 1'b1;
          $warning("pcie_axis_dw_downsize: illegal tkeep 0x%0h (must be contiguous from bit 0 and non-zero)",
                   s_axis_tkeep);
        end
      end else if (drain_beat) begin
        if (last_group) busy_r  <= 1'b0;   // releases s_axis_tready next cycle
        else            phase_r <= phase_r + 1'b1;
      end
    end
  end

endmodule
