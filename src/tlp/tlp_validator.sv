`timescale 1ns/1ps
module tlp_validator
  import tlp_pkg::*;
(
    input  tlp_header_t header_i,
    output logic        valid_o,
    output tlp_error_e  error_o
);

  logic completion;
  logic config_or_io;
  logic message;
  logic has_data;

  always_comb begin
    completion  = header_i.tlp_type == TLP_TYPE_CPL ||
                  header_i.tlp_type == TLP_TYPE_CPL_LOCK;
    config_or_io = header_i.tlp_type == TLP_TYPE_CFG0 ||
                   header_i.tlp_type == TLP_TYPE_CFG1 ||
                   header_i.tlp_type == TLP_TYPE_IO;
    message = tlp_is_message(header_i.tlp_type);
    has_data = tlp_has_data(header_i.fmt);
    valid_o = 1'b1;
    error_o = TLP_ERR_NONE;

    if (!(header_i.fmt == TLP_FMT_3DW_NO_DATA ||
          header_i.fmt == TLP_FMT_4DW_NO_DATA ||
          header_i.fmt == TLP_FMT_3DW_DATA ||
          header_i.fmt == TLP_FMT_4DW_DATA)) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_FMT_TYPE;
    end else if (!(header_i.tlp_type == TLP_TYPE_MEM ||
                   header_i.tlp_type == TLP_TYPE_IO ||
                   header_i.tlp_type == TLP_TYPE_CFG0 ||
                   header_i.tlp_type == TLP_TYPE_CFG1 ||
                   completion || message)) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_FMT_TYPE;
    end else if ((config_or_io || completion) && tlp_is_4dw(header_i.fmt)) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_FMT_TYPE;
    end else if (message && !tlp_is_4dw(header_i.fmt)) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_FMT_TYPE;
    end else if (header_i.tlp_type == TLP_TYPE_MEM &&
                 tlp_is_4dw(header_i.fmt) && header_i.address[63:32] == 0) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_ADDRESS_FORMAT;
    end else if ((config_or_io && header_i.length_dw != 1) ||
                 (!completion && !message && header_i.length_dw == 0) ||
                 (completion && !has_data && header_i.length_dw != 0) ||
                 (message && !has_data && header_i.length_dw != 0) ||
                 (has_data && header_i.length_dw == 0) ||
                 header_i.length_dw > 1024) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_LENGTH;
    end else if (!completion && !message && header_i.length_dw == 1 &&
                 header_i.last_be != 0) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_BYTE_ENABLE;
    end else if (!completion && !message && header_i.length_dw > 1 &&
                 (header_i.first_be == 0 || header_i.last_be == 0)) begin
      valid_o = 1'b0;
      error_o = TLP_ERR_BAD_BYTE_ENABLE;
    end
  end

endmodule
