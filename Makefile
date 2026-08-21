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

# Vivado non-project flow. Vivado must already be available on PATH; these
# targets deliberately do not select or source a particular installation.
VIVADO_ROOT := $(abspath $(dir $(firstword $(MAKEFILE_LIST))))
VIVADO_OUT ?= $(VIVADO_ROOT)/build/vivado
PART ?= xczu7ev-ffvc1156-2-e
# Leave timing overrides empty to use the selected unit's constraint defaults;
# UNIT=endpoint selects synth/endpoint_constraints.tcl.
PERIOD ?=
UNCERTAINTY ?=
INPUT_DELAY_MIN ?=
INPUT_DELAY_MAX ?=
OUTPUT_DELAY_MIN ?=
OUTPUT_DELAY_MAX ?=
UNIT ?=

# Integrated Gen1 endpoint inputs.  synth/endpoint.tcl remains the ordered
# Vivado manifest; this list gives Make visibility of the complete dependency
# set so missing or renamed endpoint sources fail before Vivado is launched.
ENDPOINT_SYNTH_SOURCES := \
	src/tlp/tlp_pkg.sv \
	src/packages/pcie_datalink_pkg.sv \
	src/packages/pcie_phy_pkg.sv \
	src/packages/pcie_tlp_pkg.sv \
	src/pcie_cfg/pcie_config_reg_pkg.sv \
	src/verilog-axis/rtl/priority_encoder.v \
	src/verilog-axis/rtl/arbiter.v \
	src/verilog-axis/rtl/axis_register.v \
	src/verilog-axis/rtl/axis_arb_mux.v \
	src/verilog-axis/rtl/axis_fifo.v \
	src/verilog-axis/rtl/axis_adapter.v \
	src/verilog-axis/rtl/axis_async_fifo.v \
	src/async_fifo/rtl/fifomem.v \
	src/async_fifo/rtl/fifomem_dp.v \
	src/async_fifo/rtl/rptr_empty.v \
	src/async_fifo/rtl/sync_ptr.v \
	src/async_fifo/rtl/sync_r2w.v \
	src/async_fifo/rtl/sync_w2r.v \
	src/async_fifo/rtl/wptr_full.v \
	src/async_fifo/rtl/async_fifo.v \
	src/async_fifo/rtl/async_bidir_fifo.v \
	src/async_fifo/rtl/async_bidir_ramif_fifo.v \
	src/bram/bram_dp.sv \
	src/bram/bram_sp.sv \
	src/crc/Crc16Gen.sv \
	src/crc/pcie_crc8.v \
	src/crc/pcie_dllp_crc8.v \
	src/crc/pcie_datalink_crc.sv \
	src/crc/pcie_lcrc16.sv \
	src/crc/pcie_lcrc32.sv \
	src/verilog-pcie/rtl/pcie_tlp_fifo_raw.v \
	src/verilog-pcie/rtl/pcie_tlp_fifo.v \
	src/converters/axis_to_pcie_converter.sv \
	src/converters/pcie_to_axis_converter.sv \
	src/pcie_cfg/pcie_config_decode.sv \
	src/pcie_cfg/pcie_config_handler.sv \
	src/pcie_cfg/pcie_config_mux.sv \
	src/pcie_cfg/pcie_config_reg.sv \
	src/pcie_cfg/pcie_cfg_wrapper.sv \
	src/dllp/axis_retry_fifo.sv \
	src/dllp/axis_user_demux.sv \
	src/dllp/dllp_handler.sv \
	src/dllp/dllp_fc_update.sv \
	src/dllp/dllp2tlp.sv \
	src/dllp/retry_transmit.sv \
	src/dllp/retry_management.sv \
	src/dllp/tlp2dllp.sv \
	src/dllp/dllp_receive.sv \
	src/dllp/dllp_transmit.sv \
	src/dllp/pcie_datalink_init.sv \
	src/dllp/pcie_flow_ctrl_init.sv \
	src/dllp/pcie_datalink_layer.sv \
	src/scrambler/byte_scramble.sv \
	src/scrambler/gen3_byte_scramble.sv \
	src/scrambler/gen1_scramble.sv \
	src/scrambler/gen3_scramble.sv \
	src/scrambler/scrambler.sv \
	src/scrambler/encode_8b10b.sv \
	src/scrambler/decode_8b10b.sv \
	src/pcie_phy_core/lfsr.v \
	src/pcie_phy_core/synchronous_lifo.sv \
	src/pcie_phy_core/synchronous_fifo.sv \
	src/pcie_phy_core/packet_reg.sv \
	src/pcie_phy_core/frame_symbols.sv \
	src/pcie_phy_core/lane_management.sv \
	src/pcie_phy_core/os_generator.sv \
	src/pcie_phy_core/ordered_set_handler.sv \
	src/pcie_phy_core/block_alignment.sv \
	src/pcie_phy_core/pack_data.sv \
	src/pcie_phy_core/data_handler.sv \
	src/pcie_phy_core/phy_receive.sv \
	src/pcie_phy_core/phy_transmit.sv \
	src/ltssm/pcie_ltssm_downstream.sv \
	src/tlp/tlp_ecrc.sv \
	src/tlp/tlp_validator.sv \
	src/tlp/tlp_classifier.sv \
	src/tlp/tlp_bar_decoder.sv \
	src/tlp/tlp_config_decoder.sv \
	src/tlp/tlp_parser.sv \
	src/tlp/tlp_payload_formatter.sv \
	src/tlp/tlp_request_tracker.sv \
	src/tlp/tlp_requester.sv \
	src/tlp/tlp_completion_generator.sv \
	src/tlp/tlp_control.sv \
	src/tlp/tlp_generator.sv \
	src/tlp/tlp_credit_manager.sv \
	src/tlp/tlp_vc_buffer.sv \
	src/tlp/tlp_layer.sv \
	src/pcie_endpoint/pcie_endpoint_top.sv

ENDPOINT_SYNTH_FLOW_FILES := \
	synth/endpoint.tcl \
	synth/endpoint_constraints.tcl \
	synth/s1_ooc.tcl \
	synth/run_s1.sh

ENDPOINT_PAR_FLOW_FILES := \
	synth/endpoint_constraints.tcl \
	synth/par_ooc.tcl \
	synth/run_par.sh

ifeq ($(UNIT),endpoint)
SYN_UNIT_INPUTS := $(ENDPOINT_SYNTH_SOURCES) $(ENDPOINT_SYNTH_FLOW_FILES)
PAR_UNIT_INPUTS := $(ENDPOINT_PAR_FLOW_FILES)
endif

.PHONY: syn par clean-syn clean-par

syn: $(SYN_UNIT_INPUTS)
	@REPO="$(VIVADO_ROOT)" \
	OUTROOT="$(VIVADO_OUT)/syn" \
	PART="$(PART)" PERIOD="$(PERIOD)" \
	UNCERTAINTY="$(UNCERTAINTY)" \
	INPUT_DELAY_MIN="$(INPUT_DELAY_MIN)" \
	INPUT_DELAY_MAX="$(INPUT_DELAY_MAX)" \
	OUTPUT_DELAY_MIN="$(OUTPUT_DELAY_MIN)" \
	OUTPUT_DELAY_MAX="$(OUTPUT_DELAY_MAX)" \
	./synth/run_s1.sh $(UNIT)

par: $(PAR_UNIT_INPUTS)
	@REPO="$(VIVADO_ROOT)" \
	SYNROOT="$(VIVADO_OUT)/syn" \
	OUTROOT="$(VIVADO_OUT)/par" \
	PART="$(PART)" \
	./synth/run_par.sh $(UNIT)

clean-syn:
	@if [ -z "$(strip $(UNIT))" ]; then \
		echo "ERROR: UNIT is required, for example: make clean-syn UNIT=pcie_enum_top" >&2; \
		exit 2; \
	fi
	@case "$(UNIT)" in \
		.|..|*[!A-Za-z0-9_.-]*) \
			echo "ERROR: invalid UNIT name '$(UNIT)'" >&2; exit 2 ;; \
	esac
	@repo=$$(realpath -e -- "$(VIVADO_ROOT)") || exit 2; \
	parent=$$(realpath -m -- "$(abspath $(VIVADO_OUT)/syn)") || exit 2; \
	target="$(abspath $(VIVADO_OUT)/syn/$(UNIT))"; \
	resolved=$$(realpath -m -- "$$target") || exit 2; \
	case "$$parent" in \
		"$$repo/build/"*) ;; \
		*) echo "ERROR: refusing to clean outside $$repo/build/: $$parent" >&2; exit 2 ;; \
	esac; \
	if [ "$$resolved" != "$$parent/$(UNIT)" ]; then \
		echo "ERROR: refusing redirected or symlinked target: $$target" >&2; \
		exit 2; \
	fi; \
	if [ -L "$$target" ]; then \
		echo "ERROR: refusing to remove symlink: $$target" >&2; \
		exit 2; \
	elif [ -e "$$target" ] && [ ! -d "$$target" ]; then \
		echo "ERROR: cleanup target is not a directory: $$target" >&2; \
		exit 2; \
	elif [ -d "$$target" ]; then \
		echo "Removing synthesis build: $$target"; \
		rm -rf -- "$$target"; \
	else \
		echo "No synthesis build found for UNIT=$(UNIT): $$target"; \
	fi

clean-par:
	@if [ -z "$(strip $(UNIT))" ]; then \
		echo "ERROR: UNIT is required, for example: make clean-par UNIT=pcie_enum_top" >&2; \
		exit 2; \
	fi
	@case "$(UNIT)" in \
		.|..|*[!A-Za-z0-9_.-]*) \
			echo "ERROR: invalid UNIT name '$(UNIT)'" >&2; exit 2 ;; \
	esac
	@repo=$$(realpath -e -- "$(VIVADO_ROOT)") || exit 2; \
	parent=$$(realpath -m -- "$(abspath $(VIVADO_OUT)/par)") || exit 2; \
	target="$(abspath $(VIVADO_OUT)/par/$(UNIT))"; \
	resolved=$$(realpath -m -- "$$target") || exit 2; \
	case "$$parent" in \
		"$$repo/build/"*) ;; \
		*) echo "ERROR: refusing to clean outside $$repo/build/: $$parent" >&2; exit 2 ;; \
	esac; \
	if [ "$$resolved" != "$$parent/$(UNIT)" ]; then \
		echo "ERROR: refusing redirected or symlinked target: $$target" >&2; \
		exit 2; \
	fi; \
	if [ -L "$$target" ]; then \
		echo "ERROR: refusing to remove symlink: $$target" >&2; \
		exit 2; \
	elif [ -e "$$target" ] && [ ! -d "$$target" ]; then \
		echo "ERROR: cleanup target is not a directory: $$target" >&2; \
		exit 2; \
	elif [ -d "$$target" ]; then \
		echo "Removing place-and-route build: $$target"; \
		rm -rf -- "$$target"; \
	else \
		echo "No place-and-route build found for UNIT=$(UNIT): $$target"; \
	fi

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
COCOTB_SIM_MAKEFILE = $(shell cocotb-config --makefiles)/Makefile.sim

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

ifeq ($(filter syn par,$(MAKECMDGOALS)),)
include $(shell cocotb-config --makefiles)/Makefile.sim
endif
