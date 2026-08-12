# PCIe Endpoint Protocol Integration

## Purpose

This directory contains the protocol-level PCIe endpoint top module. The
endpoint connects the Transaction Layer to the Data Link Layer and exposes:

- An application command interface for generating requests.
- A target interface for requests received by the endpoint.
- Generic Message and Message-with-Data transmit/receive interfaces.
- Completion request and completion result interfaces.
- A packet-oriented AXI-Stream interface toward the Physical Layer.
- Link, configuration, flow-control, and error status.

The top module is [`pcie_endpoint_top.sv`](pcie_endpoint_top.sv). Its FuseSoC
description is [`pcie_endpoint.core`](pcie_endpoint.core).

This top is a protocol endpoint. It does not include the electrical PIPE
interface, LTSSM, lane training, scrambling, or 8b/10b encoding. Those blocks
must be connected below the physical-facing packet streams for a complete
serial-link simulation.

## Layer organization

```text
Endpoint application
  |
  | commands, received requests, completions, results
  v
tlp_layer
  |
  | unsequenced TLP AXI-Stream
  v
pcie_datalink_layer
  |
  | sequenced TLPs, LCRC-protected packets, and DLLPs
  v
Packet-oriented Physical Layer interface
```

The Transaction Layer generates and parses TLPs, manages tags, classifies
requests, decodes BAR accesses, checks ECRC, buffers VC0 traffic, and consumes
flow-control credits. The Data Link Layer performs flow-control initialization,
DLLP processing, sequence numbering, LCRC checking, ACK/NAK handling, and
replay.

Received InitFC and UpdateFC values are exported by the Data Link Layer and
connected directly to the Transaction Layer credit manager. The endpoint
reports flow control as initialized only after the local FC2 advertisement has
been sent and the remote FC2 values have been received.

## Testbench files

The endpoint testbench is located in [`../../tb/endpoint`](../../tb/endpoint):

| File | Purpose |
| --- | --- |
| `tb_pcie_endpoint_top.sv` | Instantiates the endpoint with a single enabled BAR and exposes the internal TLP-to-DLL and DLL-to-TLP streams for verification. |
| `test_pcie_endpoint_top.py` | Cocotb stimulus, monitors, packet construction, CRC checks, and endpoint tests. |
| `tb_pcie_endpoint_top.core` | FuseSoC simulation target using the endpoint RTL and cocotb test. |
| `tb_pcie_endpoint_line_rate.sv` | Instantiates the endpoint behind a parameterized Gen1 logical-PHY model. |
| `pcie_gen1_logical_phy_model.sv` | Testbench-only x1/x4 byte striping, scrambling, 8b/10b coding, and decoded-byte counters. |
| `pcie_gen1_traffic.py` | Independent Python scrambler/8b10b reference, DLLP construction, LCRC construction, and symbol grouping. |
| `test_pcie_endpoint_line_rate.py` | Bidirectional TLP/DLL/logical-PHY data-integrity and Gen1 capacity checks. |
| `tb_pcie_endpoint_line_rate.core` | Separate FuseSoC Verilator targets for Gen1 x1 and Gen1 x4. |

The SystemVerilog harness uses a 32-bit AXI-Stream interface, one enabled
4-KiB BAR at address zero, a shortened replay timer, and verification-only
signals named `mid_tx_axis_*` and `mid_rx_axis_*`.

## Common test setup

Each cocotb test starts from a fresh simulation and performs the following
setup:

1. Start the endpoint clock.
2. Assert reset and hold the physical link down.
3. Initialize all command, target, completion, and result interfaces.
4. Release reset and assert `phy_link_up_i`.
5. Enable logical-idle indications and TLP transmission.
6. Send InitFC1 and InitFC2 DLLPs for posted, non-posted, and completion
   credit classes.
7. Wait for `fc_initialized_o`.
8. Check that the received header credits are visible at the endpoint top.

The physical-facing `tuser` classification used by the test is:

| Value | Packet class |
| ---: | --- |
| `1` | DLLP |
| `2` | TLP/link packet |

## Tests performed

### Application input to Data Link output

`application_input_reaches_data_link_output` submits a Memory Write through the
application command interface.

The test verifies:

- The command and payload are accepted through ready/valid handshakes.
- A complete TLP crosses the Transaction-to-Data-Link boundary.
- The Data Link output contains the same TLP with a two-byte sequence field.
- The output LCRC matches the CRC calculated by the testbench.
- The original payload is present in the generated TLP.
- The Transaction Layer does not report a command error.

### Physical input to endpoint target

`physical_input_reaches_target_through_mid_layer` constructs a Memory Write,
adds sequence number zero and a valid LCRC, and injects it through the
physical-facing input.

The test verifies:

- The Data Link Layer accepts and strips the sequence number and LCRC.
- The TLP at `mid_rx_axis_*` exactly matches the injected raw TLP.
- The Transaction Layer identifies a Memory Write.
- BAR 0 is selected and the decoded offset is correct.
- The request header remains stable while the target interface is stalled.
- The complete payload reaches the target data interface without alteration.

### NAK replay

`data_link_nak_replays_transaction_layer_packet` generates a Memory Read,
captures its raw TLP and link packet, and sends a NAK for the previously
acknowledged sequence number.

The test verifies:

- The initial link packet contains the TLP generated by the Transaction Layer.
- The NAK causes the stored packet to be replayed.
- The replay is byte-for-byte identical to the original link packet.
- A final ACK is supplied to retire the packet.

### Corrupted LCRC rejection

`corrupted_link_input_is_rejected_with_nak` injects a Memory Write with one
LCRC bit inverted.

The test verifies:

- The Data Link Layer returns a NAK for the last good sequence number.
- The corrupted request is not presented to the Transaction Layer target.

### Flow-control blocking and release

`flow_control_blocks_and_releases_mid_layer` sends a posted UpdateFC DLLP that
advertises zero posted credits, then submits a Memory Write.

The test verifies:

- `tx_fc_blocked_o` asserts while posted credits are unavailable.
- The packet does not cross the TLP-to-DLL boundary while blocked.
- A later UpdateFC DLLP replenishes posted credits.
- The queued TLP is released and appears in the Data Link output.

## Verification process

The expected sequence for endpoint verification is:

1. Elaborate the testbench and confirm that both layer packages and all RTL
   dependencies resolve.
2. Complete link and flow-control initialization.
3. Exercise the application-to-link direction.
4. Exercise the link-to-target direction.
5. Compare packets at the internal layer boundary.
6. Inject ACK, NAK, bad-LCRC, and credit-update conditions.
7. Check ready/valid stability during backpressure.
8. Require every cocotb test to finish without assertion failures or timeouts.

The current testbench tests the protocol integration boundary. Full endpoint
qualification should additionally connect the LTSSM and Physical Layer and
test enumeration, configuration-space accesses, BAR assignment, completion
tracking, link recovery, and lane-level behavior.

## Expanded verification plan and ownership

The endpoint target now contains additional test intent. These additions have
not been executed and must be reviewed before the documented simulation
command is approved.

| Verification area | Owner and intended check |
| --- | --- |
| Exact outbound header, initial sequence, posted decrement, and `tuser` | `exact_outbound_header_sequence_credit_and_classification` decodes every applicable Memory Write field, requires initial sequence zero, checks one header/one 16-byte data-credit decrement, and requires TLP classification on every output byte. |
| Consecutive, unaligned, segmented, and 4-DW writes | `consecutive_unaligned_segmented_and_4dw_writes` checks two consecutive writes, byte enables and padding at address `0x81`, a 300-byte write split at a 128-byte MPS, consecutive sequence values, and a write above 4 GiB. |
| Prefix and ECRC | `outbound_prefix_and_ecrc_are_preserved` checks prefix placement and independently recalculates the ECRC. |
| Every receive-header field and poison propagation | `inbound_header_fields_payload_backpressure_and_poison` checks format, type, TC, attributes, TD, EP, TH, AT, length, requester ID, tag, byte enables, address, and prefix-present state. The current implemented behavior reports EP to the target; it does not automatically discard poisoned traffic. |
| Payload backpressure | The same test stalls target payload acceptance and requires data, keep, last, and valid to remain stable. |
| BAR boundary and memory-disable | `bar_boundary_memory_disable_and_config_routing` checks a request crossing the 4-KiB BAR boundary and a request received with memory space disabled. Both are presented as unsupported target requests. |
| Configuration routing | The same test injects matching Configuration Read and Write TLPs and checks BDF hit, operation, and register offset. It does not model enumeration, mutate the generated configuration register block, or produce an automatic configuration completion. |
| Completion generation and outstanding tags | `completion_generation_and_multiple_outstanding_requests` turns a received Memory Read into Completion-with-Data and checks two locally issued reads retain different outstanding tags. |
| Generated ACK sequence | `physical_input_reaches_target_through_mid_layer` explicitly requires ACK sequence zero for the accepted receive TLP. |
| LCRC rejection and one-packet replay | Existing endpoint tests check bad-LCRC rejection and NAK replay byte equality. |
| Multi-packet retry corner cases | `tb/dllp/test_dll_comprehensive.py` owns cumulative ACK, go-back-N replay, invalid NAK windows, corrupt ACK/NAK CRC, timeout replay, retry exhaustion, sequence rollover, retry-buffer full behavior, and link-down cleanup. |
| Credit starvation combinations | `tb/tlp/test_tlp_credit_manager.py` owns independent posted, non-posted, and completion header/data starvation, exact 16-byte credit consumption, and guards against decrement wraparound. Scaled and infinite encodings remain DLLP decode concerns. |
| BAR overlap | `tb/tlp/test_tlp_comb.py` uses deliberately overlapping BAR masks and requires ambiguity to clear the hit indication. The endpoint fixture retains one BAR, so overlap cannot occur in that fixture. |
| Multiple queued traffic classes | `tb/tlp/test_tlp_vc_buffer.py` and `tb/tlp/test_tlp_completion_control.py` own queue metadata, packet locking, and request/completion arbitration. The current endpoint exposes only VC0. |
| Scrambler and 8b/10b | The endpoint harness instantiates verification-only copies of the existing codec primitives. `existing_scrambler_and_8b10b_primitives_are_checked` exhaustively covers all 256 data symbols at both disparities, all legal K symbols, and the 10-bit code space; it also checks disparity behavior and representative reference Gen1 LFSR steps. These instances are not connected to the endpoint datapath. |

## Unsupported or intentionally excluded behavior

The present RTL does not implement automatic Unsupported Request Completion
generation, Message-specific side effects, Atomic operations, locked requests, AER,
interrupt/MSI/MSI-X generation, request timeouts, power-management DLLPs, or
Root-Complex enumeration/BAR assignment. Tests must report these as
capability gaps; they must not claim simulated support.

Message TLPs are transported generically. The endpoint preserves the routing
encoding, message code, routing-specific header data, and optional payload.
It does not interpret a message code by changing power, interrupt, or AER
state; those semantic handlers remain application responsibilities.

No new production physical functionality is part of this endpoint work. In particular,
the endpoint does not add or integrate LTSSM/link training, PIPE, serialization,
receiver detection, lane alignment/reversal, TS1/TS2 or ordered-set handling,
scrambling in the production packet path, or 8b/10b encoding in the production
packet path. The line-rate harness connects a verification-only logical PHY to
the endpoint packet interface; it does not change `pcie_endpoint_top`.

## Gen1 logical-PHY line-rate test

The line-rate harness uses a 250-MHz symbol clock. `LANE_COUNT=1` emits one
8b/10b symbol per cycle and packs four decoded bytes into each 32-bit endpoint
beat. `LANE_COUNT=4` emits four independent symbols per cycle and maps them
directly to one endpoint beat. The corresponding decoded capacities are
250 MB/s for x1 and 1 GB/s for x4 before TLP, DLLP, ACK, and framing overhead.

Each lane has independent scrambler and running-disparity state. The Python
reference independently generates RX symbols and decodes TX symbols. Tests
compare the raw TLP at `mid_tx_axis_*`/`mid_rx_axis_*`, the sequence and LCRC
protected packet, and the application or target payload. Counters report
protected bytes and active symbol cycles. Protocol stalls are visible as
elapsed cycles beyond the ideal `ceil(bytes / lanes)` active-cycle count.

The x4 model assumes ideal synchronized lanes and deterministic byte striping.
It does not model deskew, lane reversal, SKP insertion, ordered sets, electrical
timing, or transceiver behavior. Simulation establishes logical capacity and
functional integrity; an FPGA timing report and external PCIe link partner are
still required to establish hardware line rate.

Functional coverage and code-coverage collection are also not configured.
Adding coverage goals and simulator coverage-report generation is a separate
verification-infrastructure task.

## Running the test

From the repository root, register the repository if it is not already in the
FuseSoC library:

```bash
fusesoc library add pcie-endpoint-controller ./
```

The endpoint simulation target is:

```bash
fusesoc run --target=sim fusesoc:pcie:tb_endpoint_protocol:1.0.0
```

The target currently selects VCS and requires the Python packages used by
cocotb, `cocotbext-axi`, and `cocotbext-pcie`.

The separate open-source logical-PHY targets are:

```bash
fusesoc run --target=sim_x1 fusesoc:pcie:tb_endpoint_line_rate:1.0.0
fusesoc run --target=sim_x4 fusesoc:pcie:tb_endpoint_line_rate:1.0.0
```

These targets select Verilator, which supports the SystemVerilog constructs
used by the endpoint and Data Link dependencies. They do not depend on VCS or
Icarus.

These commands are documentation only. They should be run only after the RTL
and testbench changes have been reviewed and test execution has been approved.

## Pass criteria

The endpoint test passes when:

- Flow-control initialization completes.
- Every AXI-Stream transfer obeys ready/valid semantics.
- Raw TLPs match at the Transaction/Data Link boundary.
- Sequence numbers, LCRC values, ACK/NAK responses, and replay behavior match
  the expected values.
- BAR targeting and payload delivery are correct.
- Credit starvation blocks traffic and a valid update releases it.
- No cocotb assertion or timeout occurs.



## Warnings and Errors (Documentation purposes) 
* Multiple MULTIDRIVE warnings in within pcie_config_reg.sv
* Multiple Latch warnings in tb_pcie_endpoint_rate.sv

## Safekeeping note (2026-08-12)

Gen1 x1 delivers a 32-bit endpoint word over four symbol clocks, so idle cycles
between endpoint AXI words are expected. The Data Link receive path must use
accepted words, not cycle-adjacent look-ahead, when removing the sequence field
and validating LCRC. The x4 path exercises the same logic without those x1
packing gaps.

The endpoint fixture has a three-entry retry TLP buffer. Tests that generate
more than three unacknowledged requests must receive and cumulatively ACK each
batch before submitting another batch. Command and payload handshakes have
bounded waits so credit starvation or a full retry buffer reports a diagnostic
instead of hanging indefinitely. These changes were documented without running
the simulation, per the execution restriction.
