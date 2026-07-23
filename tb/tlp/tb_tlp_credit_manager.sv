`timescale 1ns/1ps
module tb_tlp_credit_manager;
  import tlp_pkg::*;
  logic clk_i=0, rst_i, fc_initialized, fc_update_valid, request_valid;
  logic [7:0] ph,nph,cplh,ph_av,nph_av,cplh_av;
  logic [11:0] pd,npd,cpld,pd_av,npd_av,cpld_av,request_data_credits;
  logic [1:0] request_class;
  logic request_ready,blocked,error;
  tlp_credit_manager dut(.clk_i(clk_i),.rst_i(rst_i),
    .fc_initialized_i(fc_initialized),.fc_update_valid_i(fc_update_valid),
    .fc_ph_i(ph),.fc_pd_i(pd),.fc_nph_i(nph),.fc_npd_i(npd),
    .fc_cplh_i(cplh),.fc_cpld_i(cpld),.request_valid_i(request_valid),
    .request_ready_o(request_ready),.request_class_i(request_class),
    .request_data_credits_i(request_data_credits),.blocked_o(blocked),.error_o(error),
    .posted_header_available_o(ph_av),.posted_data_available_o(pd_av),
    .nonposted_header_available_o(nph_av),.nonposted_data_available_o(npd_av),
    .completion_header_available_o(cplh_av),.completion_data_available_o(cpld_av));
endmodule
