`timescale 1ns/1ps
module tb_tlp_vc_buffer;
  import tlp_pkg::*;
  logic clk_i=0,rst_i;
  logic [31:0] s_data,m_data; logic [3:0] s_keep,m_keep;
  logic s_valid,s_last,s_ready,m_valid,m_last,m_ready,packet_valid,packet_ready,overflow;
  logic [2:0] s_user,m_user; logic [1:0] s_class,packet_class;
  logic s_has_data;
  logic [10:0] s_length; logic [11:0] packet_credits;
  tlp_vc_buffer #(.PACKET_DEPTH(2),.MAX_PACKET_WORDS(16)) dut(
    .clk_i(clk_i),.rst_i(rst_i),.s_axis_tdata(s_data),.s_axis_tkeep(s_keep),
    .s_axis_tvalid(s_valid),.s_axis_tlast(s_last),.s_axis_tuser(s_user),
    .s_axis_tready(s_ready),.s_packet_class_i(s_class),.s_packet_length_dw_i(s_length),
    .s_packet_has_data_i(s_has_data),
    .packet_valid_o(packet_valid),.packet_ready_i(packet_ready),
    .packet_credit_class_o(packet_class),.packet_data_credits_o(packet_credits),
    .m_axis_tdata(m_data),.m_axis_tkeep(m_keep),.m_axis_tvalid(m_valid),
    .m_axis_tlast(m_last),.m_axis_tuser(m_user),.m_axis_tready(m_ready),.overflow_o(overflow));
endmodule
