// ---------------------------------------------------------------------------
// tb_pcie_axis_gearbox -- flattened cocotb shim for the 2a-0 width gearboxes.
//
// Three independent instances share one toplevel so the whole G1..G10 sweep
// fits a single Verilator build (parallel builds SIGSEGV on this box):
//
//   dn_*  standalone pcie_axis_dw_downsize  (128 -> 32)   G2, G3, G4, G7, G9, G10
//   up_*  standalone pcie_axis_dw_upsize    (32 -> 128)   G5, G6, G7, G9, G10
//   rt_*  round trip downsize -> upsize     (128 -> 128)  G8
//
// The round-trip pair wires dn m_axis straight into up s_axis with no buffering
// between them, so G8 exercises the two modules against each other with no
// hand-written golden in the middle.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps
module tb_pcie_axis_gearbox;

  logic clk_i = 0;
  logic rst_i;

  // ---- standalone downsize: 128 -> 32 -------------------------------------
  logic [127:0] dn_s_tdata;
  logic [15:0]  dn_s_tkeep;
  logic         dn_s_tvalid;
  logic         dn_s_tlast;
  logic         dn_s_tready;
  logic [31:0]  dn_m_tdata;
  logic [3:0]   dn_m_tkeep;
  logic         dn_m_tvalid;
  logic         dn_m_tlast;
  logic         dn_m_tready;
  logic         dn_error;

  pcie_axis_dw_downsize dn (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata(dn_s_tdata), .s_axis_tkeep(dn_s_tkeep),
      .s_axis_tvalid(dn_s_tvalid), .s_axis_tlast(dn_s_tlast), .s_axis_tready(dn_s_tready),
      .m_axis_tdata(dn_m_tdata), .m_axis_tkeep(dn_m_tkeep),
      .m_axis_tvalid(dn_m_tvalid), .m_axis_tlast(dn_m_tlast), .m_axis_tready(dn_m_tready),
      .gearbox_error_o(dn_error)
  );

  // ---- standalone upsize: 32 -> 128 ---------------------------------------
  logic [31:0]  up_s_tdata;
  logic [3:0]   up_s_tkeep;
  logic         up_s_tvalid;
  logic         up_s_tlast;
  logic         up_s_tready;
  logic [127:0] up_m_tdata;
  logic [15:0]  up_m_tkeep;
  logic         up_m_tvalid;
  logic         up_m_tlast;
  logic         up_m_tready;
  logic         up_error;

  pcie_axis_dw_upsize up (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata(up_s_tdata), .s_axis_tkeep(up_s_tkeep),
      .s_axis_tvalid(up_s_tvalid), .s_axis_tlast(up_s_tlast), .s_axis_tready(up_s_tready),
      .m_axis_tdata(up_m_tdata), .m_axis_tkeep(up_m_tkeep),
      .m_axis_tvalid(up_m_tvalid), .m_axis_tlast(up_m_tlast), .m_axis_tready(up_m_tready),
      .gearbox_error_o(up_error)
  );

  // ---- round trip: 128 -> 32 -> 128 (G8) ----------------------------------
  logic [127:0] rt_s_tdata;
  logic [15:0]  rt_s_tkeep;
  logic         rt_s_tvalid;
  logic         rt_s_tlast;
  logic         rt_s_tready;
  logic [127:0] rt_m_tdata;
  logic [15:0]  rt_m_tkeep;
  logic         rt_m_tvalid;
  logic         rt_m_tlast;
  logic         rt_m_tready;
  logic         rt_dn_error;
  logic         rt_up_error;

  // Intermediate narrow stream, unbuffered.
  logic [31:0]  rt_mid_tdata;
  logic [3:0]   rt_mid_tkeep;
  logic         rt_mid_tvalid;
  logic         rt_mid_tlast;
  logic         rt_mid_tready;

  pcie_axis_dw_downsize rt_dn (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata(rt_s_tdata), .s_axis_tkeep(rt_s_tkeep),
      .s_axis_tvalid(rt_s_tvalid), .s_axis_tlast(rt_s_tlast), .s_axis_tready(rt_s_tready),
      .m_axis_tdata(rt_mid_tdata), .m_axis_tkeep(rt_mid_tkeep),
      .m_axis_tvalid(rt_mid_tvalid), .m_axis_tlast(rt_mid_tlast), .m_axis_tready(rt_mid_tready),
      .gearbox_error_o(rt_dn_error)
  );

  pcie_axis_dw_upsize rt_up (
      .clk_i(clk_i), .rst_i(rst_i),
      .s_axis_tdata(rt_mid_tdata), .s_axis_tkeep(rt_mid_tkeep),
      .s_axis_tvalid(rt_mid_tvalid), .s_axis_tlast(rt_mid_tlast), .s_axis_tready(rt_mid_tready),
      .m_axis_tdata(rt_m_tdata), .m_axis_tkeep(rt_m_tkeep),
      .m_axis_tvalid(rt_m_tvalid), .m_axis_tlast(rt_m_tlast), .m_axis_tready(rt_m_tready),
      .gearbox_error_o(rt_up_error)
  );

endmodule
