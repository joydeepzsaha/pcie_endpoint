`timescale 1ns/1ps
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

  logic [7:0] ph_r, nph_r, cplh_r;
  logic [11:0] pd_r, npd_r, cpld_r;
  logic selected_header_available;
  logic selected_data_available;

  always_comb begin
    selected_header_available = 1'b0;
    selected_data_available = 1'b0;
    case (request_class_i)
      TLP_CREDIT_POSTED: begin
        selected_header_available = ph_r != 0;
        selected_data_available = pd_r >= request_data_credits_i;
      end
      TLP_CREDIT_COMPLETION: begin
        selected_header_available = cplh_r != 0;
        selected_data_available = cpld_r >= request_data_credits_i;
      end
      default: begin
        selected_header_available = nph_r != 0;
        selected_data_available = npd_r >= request_data_credits_i;
      end
    endcase
    request_ready_o = fc_initialized_i && selected_header_available &&
                      selected_data_available;
    blocked_o = request_valid_i && !request_ready_o;
  end

  assign posted_header_available_o = ph_r;
  assign posted_data_available_o = pd_r;
  assign nonposted_header_available_o = nph_r;
  assign nonposted_data_available_o = npd_r;
  assign completion_header_available_o = cplh_r;
  assign completion_data_available_o = cpld_r;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      ph_r <= '0;
      pd_r <= '0;
      nph_r <= '0;
      npd_r <= '0;
      cplh_r <= '0;
      cpld_r <= '0;
      error_o <= 1'b0;
    end else begin
      error_o <= 1'b0;
      if (fc_update_valid_i) begin
        ph_r <= fc_ph_i;
        pd_r <= fc_pd_i;
        nph_r <= fc_nph_i;
        npd_r <= fc_npd_i;
        cplh_r <= fc_cplh_i;
        cpld_r <= fc_cpld_i;
      end
      if (request_valid_i && request_ready_o) begin
        case (request_class_i)
          TLP_CREDIT_POSTED: begin
            ph_r <= ph_r - 1'b1;
            pd_r <= pd_r - request_data_credits_i;
          end
          TLP_CREDIT_COMPLETION: begin
            cplh_r <= cplh_r - 1'b1;
            cpld_r <= cpld_r - request_data_credits_i;
          end
          default: begin
            nph_r <= nph_r - 1'b1;
            npd_r <= npd_r - request_data_credits_i;
          end
        endcase
      end
      if (request_valid_i && fc_initialized_i &&
          (!selected_header_available || !selected_data_available))
        error_o <= 1'b0; // Normal credit blocking is not a protocol error.
    end
  end

endmodule
