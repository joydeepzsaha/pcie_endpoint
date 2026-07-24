# ============================================================================
# Cocotb 1.9.2 + VCS test for pcie_datalink_layer
#
# DUT:
#   src/dllp/pcie_datalink_layer.sv
#
# Python test:
#   tb/dllp/test_pcie_datalink_layer.py
# ============================================================================

SIM := vcs
TOPLEVEL_LANG := verilog

# Name of the RTL module, not the SystemVerilog testbench.
TOPLEVEL := pcie_datalink_layer

# Python filename without the .py extension.
MODULE := test_dll_comprehensive

# Make the Python test importable by cocotb.
export PYTHONPATH := $(PWD)/tb/dllp:$(PYTHONPATH)

VERILOG_SOURCES := \
	$(PWD)/src/packages/pcie_datalink_pkg.sv \
	$(PWD)/src/pcie_cfg/pcie_config_reg_pkg.sv \
	$(PWD)/src/pcie_cfg/pcie_config_reg.sv \
	$(PWD)/src/packages/pcie_tlp_pkg.sv \
	$(PWD)/src/pcie_cfg/pcie_cfg_wrapper.sv \
	$(PWD)/src/pcie_cfg/pcie_config_decode.sv \
	$(PWD)/src/pcie_cfg/pcie_config_mux.sv \
	$(PWD)/src/pcie_cfg/pcie_config_handler.sv \
	$(PWD)/src/crc/pcie_dllp_crc8.v \
	$(PWD)/src/crc/pcie_datalink_crc.sv \
	$(PWD)/src/crc/pcie_crc8.v \
	$(PWD)/src/crc/pcie_lcrc16.sv \
	$(PWD)/src/crc/pcie_lcrc32.sv \
	$(PWD)/src/dllp/pcie_datalink_layer.sv \
	$(PWD)/src/dllp/pcie_datalink_init.sv \
	$(PWD)/src/dllp/pcie_flow_ctrl_init.sv \
	$(PWD)/src/dllp/dllp_receive.sv \
	$(PWD)/src/dllp/dllp_handler.sv \
	$(PWD)/src/dllp/dllp_transmit.sv \
	$(PWD)/src/dllp/dllp2tlp.sv \
	$(PWD)/src/dllp/tlp2dllp.sv \
	$(PWD)/src/dllp/dllp_fc_update.sv \
	$(PWD)/src/dllp/retry_management.sv \
	$(PWD)/src/dllp/retry_transmit.sv \
	$(PWD)/src/dllp/axis_retry_fifo.sv \
	$(PWD)/src/dllp/axis_user_demux.sv \
	$(PWD)/src/bram/bram_dp.sv \
	$(PWD)/src/verilog-axis/rtl/arbiter.v \
	$(PWD)/src/verilog-axis/rtl/priority_encoder.v \
	$(PWD)/src/verilog-axis/rtl/axis_register.v \
	$(PWD)/src/verilog-axis/rtl/axis_arb_mux.v \
	$(PWD)/src/verilog-axis/rtl/axis_mux.v \
	$(PWD)/src/verilog-axis/rtl/axis_demux.v \
	$(PWD)/src/verilog-axis/rtl/axis_fifo.v

# Options used while VCS compiles the RTL.
COMPILE_ARGS += -full64
COMPILE_ARGS += -sverilog
COMPILE_ARGS += -timescale=1ns/1ps
COMPILE_ARGS += -debug_access+all
COMPILE_ARGS += -kdb
COMPILE_ARGS += -lca
COMPILE_ARGS += +v2k

# Build output directory used by cocotb.
SIM_BUILD := sim_build

# Cocotb result summary. This is XML, separate from the terminal text log.
COCOTB_RESULTS_FILE := results_pcie_datalink.xml

# Preserve the Makefile's existing bare `make` behavior after adding the TLP
# targets below.
.DEFAULT_GOAL := test-log

.PHONY: test-log clean-all print-sources \
	tlp-tests tlp-test-comb tlp-test-parser tlp-test-payload-formatter \
	tlp-test-request-tracker tlp-test-requester tlp-test-generator \
	tlp-test-completion-control tlp-test-ecrc tlp-test-credit-manager \
	tlp-test-vc-buffer tlp-test-layer tlp-test-end-to-end

# TLP regression paths and ordered RTL source list.  Each TLP target invokes
# cocotb's simulator Makefile in tb/tlp, so the main DLL test configuration
# above remains unchanged.
TLP_ROOT := $(abspath $(dir $(firstword $(MAKEFILE_LIST))))
TLP_SRC_DIR := $(TLP_ROOT)/src/tlp
TLP_TB_DIR := $(TLP_ROOT)/tb/tlp
COCOTB_SIM_MAKEFILE := $(shell cocotb-config --makefiles)/Makefile.sim

TLP_RTL_SOURCES := \
	$(TLP_SRC_DIR)/tlp_pkg.sv \
	$(TLP_SRC_DIR)/tlp_ecrc.sv \
	$(TLP_SRC_DIR)/tlp_validator.sv \
	$(TLP_SRC_DIR)/tlp_classifier.sv \
	$(TLP_SRC_DIR)/tlp_bar_decoder.sv \
	$(TLP_SRC_DIR)/tlp_config_decoder.sv \
	$(TLP_SRC_DIR)/tlp_parser.sv \
	$(TLP_SRC_DIR)/tlp_payload_formatter.sv \
	$(TLP_SRC_DIR)/tlp_request_tracker.sv \
	$(TLP_SRC_DIR)/tlp_requester.sv \
	$(TLP_SRC_DIR)/tlp_completion_generator.sv \
	$(TLP_SRC_DIR)/tlp_control.sv \
	$(TLP_SRC_DIR)/tlp_generator.sv \
	$(TLP_SRC_DIR)/tlp_credit_manager.sv \
	$(TLP_SRC_DIR)/tlp_vc_buffer.sv \
	$(TLP_SRC_DIR)/tlp_layer.sv

ifeq ($(SIM),vcs)
TLP_COMPILE_ARGS := -full64 -sverilog -timescale=1ns/1ps -debug_access+all -kdb -lca +v2k
else ifeq ($(SIM),icarus)
TLP_COMPILE_ARGS := -g2012 -I$(TLP_SRC_DIR)
else
TLP_COMPILE_ARGS := -timescale=1ns/1ps
endif

define run_tlp_test
	+$(MAKE) -C $(TLP_TB_DIR) -f $(COCOTB_SIM_MAKEFILE) \
		SIM=$(SIM) TOPLEVEL_LANG=verilog TOPLEVEL=$(1) MODULE=$(2) \
		SIM_BUILD=sim_build_$(3)_$(SIM) \
		COCOTB_RESULTS_FILE=results_$(3)_$(SIM).xml \
		COMPILE_ARGS="$(TLP_COMPILE_ARGS)" \
		VERILOG_SOURCES="$(4)"
endef

# Run the complete TLP regression.  The suites are intentionally serialized
# because cocotb simulators create shared transient files in tb/tlp.
.NOTPARALLEL: tlp-tests
tlp-tests: tlp-test-comb tlp-test-parser tlp-test-payload-formatter \
	tlp-test-request-tracker tlp-test-requester tlp-test-generator \
	tlp-test-completion-control tlp-test-ecrc tlp-test-credit-manager \
	tlp-test-vc-buffer tlp-test-layer tlp-test-end-to-end

tlp-test-comb:
	$(call run_tlp_test,tb_tlp_comb,test_tlp_comb,comb,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_validator.sv $(TLP_SRC_DIR)/tlp_classifier.sv $(TLP_SRC_DIR)/tlp_bar_decoder.sv $(TLP_SRC_DIR)/tlp_config_decoder.sv $(TLP_TB_DIR)/tb_tlp_comb.sv)

tlp-test-parser:
	$(call run_tlp_test,tb_tlp_parser,test_tlp_parser,parser,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_ecrc.sv $(TLP_SRC_DIR)/tlp_validator.sv $(TLP_SRC_DIR)/tlp_parser.sv $(TLP_TB_DIR)/tb_tlp_parser.sv)

tlp-test-payload-formatter:
	$(call run_tlp_test,tb_tlp_payload_formatter,test_tlp_payload_formatter,payload_formatter,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_payload_formatter.sv $(TLP_TB_DIR)/tb_tlp_payload_formatter.sv)

tlp-test-request-tracker:
	$(call run_tlp_test,tb_tlp_request_tracker,test_tlp_request_tracker,request_tracker,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_request_tracker.sv $(TLP_TB_DIR)/tb_tlp_request_tracker.sv)

tlp-test-requester:
	$(call run_tlp_test,tb_tlp_requester,test_tlp_requester,requester,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_requester.sv $(TLP_TB_DIR)/tb_tlp_requester.sv)

tlp-test-generator:
	$(call run_tlp_test,tb_tlp_generator,test_tlp_generator,generator,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_ecrc.sv $(TLP_SRC_DIR)/tlp_payload_formatter.sv $(TLP_SRC_DIR)/tlp_generator.sv $(TLP_TB_DIR)/tb_tlp_generator.sv)

tlp-test-completion-control:
	$(call run_tlp_test,tb_tlp_completion_control,test_tlp_completion_control,completion_control,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_completion_generator.sv $(TLP_SRC_DIR)/tlp_control.sv $(TLP_TB_DIR)/tb_tlp_completion_control.sv)

tlp-test-ecrc:
	$(call run_tlp_test,tb_tlp_ecrc,test_tlp_ecrc,ecrc,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_ecrc.sv $(TLP_TB_DIR)/tb_tlp_ecrc.sv)

tlp-test-credit-manager:
	$(call run_tlp_test,tb_tlp_credit_manager,test_tlp_credit_manager,credit_manager,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_credit_manager.sv $(TLP_TB_DIR)/tb_tlp_credit_manager.sv)

tlp-test-vc-buffer:
	$(call run_tlp_test,tb_tlp_vc_buffer,test_tlp_vc_buffer,vc_buffer,$(TLP_SRC_DIR)/tlp_pkg.sv $(TLP_SRC_DIR)/tlp_vc_buffer.sv $(TLP_TB_DIR)/tb_tlp_vc_buffer.sv)

tlp-test-layer:
	$(call run_tlp_test,tlp_layer,test_tlp_compile,layer,$(TLP_RTL_SOURCES))

tlp-test-end-to-end:
	$(call run_tlp_test,tlp_layer,test_tlp_end_to_end,end_to_end,$(TLP_RTL_SOURCES))

# Run cocotb/VCS and save stdout and stderr to the requested text file.
test-log:
	@set -o pipefail; \
	$(MAKE) sim 2>&1 | tee output_testPcie_python.txt

print-sources:
	@printf "%s\n" $(VERILOG_SOURCES)

clean-all:
	rm -rf \
		$(SIM_BUILD) \
		simv \
		simv.daidir \
		csrc \
		DVEfiles \
		ucli.key \
		*.vpd \
		*.vcd \
		*.fsdb \
		*.log \
		results*.xml \
		output_testPcie_python.txt \
		novas.* \
		verdiLog

include $(shell cocotb-config --makefiles)/Makefile.sim
