# PCIe Transaction Layer

## Purpose

This directory implements the endpoint Transaction Layer. It converts
application commands into Transaction Layer Packets, parses received TLPs, and
routes requests and completions between the PCIe link and endpoint application.

The integration module is [`tlp_layer.sv`](tlp_layer.sv), and
[`tlp_core.core`](tlp_core.core) lists the RTL in compilation order.

## RTL components

| Module | Responsibility |
| --- | --- |
| `tlp_pkg.sv` | TLP formats, types, classes, commands, error codes, packed headers, and helper functions. |
| `tlp_validator.sv` | Header-format and protocol validation. |
| `tlp_classifier.sv` | Posted, non-posted, completion, memory, configuration, Message, read, and write classification. |
| `tlp_bar_decoder.sv` | Address comparison, BAR selection, overlap reporting, and target offset calculation. |
| `tlp_config_decoder.sv` | Configuration request BDF and register-offset decoding. |
| `tlp_parser.sv` | AXI-Stream TLP disassembly, header extraction, payload forwarding, framing checks, and ECRC checking. |
| `tlp_payload_formatter.sv` | Payload alignment, byte masking, segmentation, and backpressure handling. |
| `tlp_request_tracker.sv` | Tag allocation, outstanding-request context, completion accounting, and tag retirement. |
| `tlp_requester.sv` | Application command conversion, request segmentation, tag requests, and Memory/Configuration/I/O/Message header generation. |
| `tlp_completion_generator.sv` | Completion and Completion-with-Data header/payload generation. |
| `tlp_control.sv` | Arbitration between locally generated requests and completions while preserving packet boundaries. |
| `tlp_generator.sv` | TLP serialization, optional prefix insertion, payload emission, and optional ECRC insertion. |
| `tlp_ecrc.sv` | End-to-end CRC calculation. |
| `tlp_credit_manager.sv` | Independent posted, non-posted, and completion header/data credit accounting. |
| `tlp_vc_buffer.sv` | VC0 packet buffering, packet atomicity, credit metadata, and output backpressure. |
| `tlp_layer.sv` | Top-level connection of all Transaction Layer functions. |

## Testbench organization

The Transaction Layer tests are in [`../../tb/tlp`](../../tb/tlp). Small
SystemVerilog wrappers expose packed structures and module ports to cocotb.
Python tests provide stimulus, reference calculations, monitors, and
assertions.

| Test | Primary coverage |
| --- | --- |
| `test_tlp_comb.py` | Package helpers, all traffic classes, BAR boundaries, BAR overlap, and configuration decode boundaries. |
| `test_tlp_parser.py` | Posted/non-posted/completion parsing, payload timing, malformed frames, recovery, prefixes, ECRC, and reset during a packet. |
| `test_tlp_payload_formatter.py` | Payload alignment, lengths, partial keeps, backpressure, and reset cleanup. |
| `test_tlp_request_tracker.py` | Tag exhaustion, split completions, tag reuse, malformed completions, and result backpressure. |
| `test_tlp_requester.py` | Non-posted segmentation, tag timing, 4-KiB boundaries, posted writes, reset, zero-length rejection, and 32/64-bit address selection. |
| `test_tlp_generator.py` | Request headers, prefixes, payloads, digest insertion, stalls, no-data requests/completions, output stability, and reset. |
| `test_tlp_completion_control.py` | Completion fields, completion priority, packet locking, and boundary-level round-robin fairness. |
| `test_tlp_ecrc.py` | Fixed vectors, randomized data, maximum packet length, and reset. |
| `test_tlp_credit_manager.py` | Exact credit consumption, P/NP/Cpl header-only and data-only starvation, short updates, all six independent pools, and blocked-counter wraparound guards. |
| `test_tlp_vc_buffer.py` | Packet atomicity, credit-class metadata, data-credit calculation, queueing, and backpressure. |
| `test_tlp_compile.py` | Layer reset, request routing, malformed timing, local command output, and exact credit-class blocking. |
| `test_tlp_end_to_end.py` | Request families, 3-DW/4-DW formats, prefix/ECRC alignment, segmentation, request-to-completion tracking, malformed traffic, and recovery. |

## Unit-test process

Most unit tests follow this sequence:

1. Start the test clock.
2. Drive every input to a known value.
3. Assert reset and verify cleared state.
4. Release reset and enable the link where required.
5. Drive a header, command, payload, completion, or flow-control update.
6. Apply ready/valid backpressure at selected boundaries.
7. Capture the output header, payload, error, tag, credit, or result.
8. Compare it with a reference value calculated by the Python test.
9. Confirm outputs remain stable while `valid` is asserted and `ready` is low.
10. Reset or send a valid follow-up packet to verify recovery.

Tests for stateful modules use a fresh simulator instance so tags, credits,
packet buffers, and parser state cannot leak between suites.

## End-to-end Transaction Layer process

The `tlp_layer` end-to-end test initializes:

- Link-up and transmit-enable state.
- Requester and completer IDs.
- Bus, device, and function numbers.
- BAR configuration and memory enable.
- Maximum payload and maximum read request sizes.
- Posted, non-posted, and completion credits.
- Target, completion, and result ready signals.

It then performs four groups of checks:

1. Generate and decode all supported application request families and
   3-DW/4-DW header forms.
2. Exercise prefix, ECRC, maximum-size, and segmented transfers.
3. Issue a non-posted request, return its completion, check the saved context,
   and confirm tag retirement.
4. Inject malformed timing, header, keep, and ECRC cases, then verify that a
   later valid packet is accepted.

## Running the tests

The repository-level [`../../Makefile`](../../Makefile) contains one target for
each Transaction Layer suite and an aggregate regression target.

Run the complete Transaction Layer regression:

```bash
make tlp-tests SIM=vcs
```

Run one suite:

```bash
make tlp-test-parser SIM=vcs
make tlp-test-requester SIM=vcs
make tlp-test-end-to-end SIM=vcs
```

The available targets are:

```text
tlp-test-comb
tlp-test-parser
tlp-test-payload-formatter
tlp-test-request-tracker
tlp-test-requester
tlp-test-generator
tlp-test-completion-control
tlp-test-ecrc
tlp-test-credit-manager
tlp-test-vc-buffer
tlp-test-layer
tlp-test-end-to-end
```

The Makefile creates a separate simulation build directory and result XML file
for each suite. This prevents simulator artifacts from one unit test from
overwriting another suite's results.

These commands are documentation only and should not be executed until the
changes and the selected simulator have been reviewed and execution has been
approved.

## Pass criteria

A Transaction Layer regression passes when:

- Generated headers, payloads, prefixes, and ECRC values match the reference.
- Received packets are classified and routed correctly.
- BAR and configuration decoding produce the expected hit and offset.
- Tags are neither leaked nor reused while outstanding.
- Split completions retire the request only at the correct boundary.
- Each traffic class consumes only its own header and data credits.
- Packet data stays stable under backpressure.
- Malformed packets report the expected error and do not corrupt the next
  packet.
- Every cocotb result reports a pass with no timeout or unresolved output.

## Scope

The current RTL implements the endpoint Transaction Layer around VC0 and the
interfaces used by this project. Transaction Layer unit-test success does not
by itself prove Data Link replay, LTSSM operation, Physical Layer encoding, or
electrical PCIe compliance. Those are tested at their respective layers and at
the endpoint integration level.

Messages and Messages with Data use four-DWORD headers and posted credits.
The generic interface preserves routing values 0 through 5, the eight-bit
message code, the requester ID, routing-specific 64-bit header data, and any
DWORD-aligned payload. Message-code semantics are intentionally left to the
endpoint application.

## Change log (12-Aug-26)

The receive-path repair is below the Transaction Layer: a good protected frame
must emerge from the DLL as the exact original DWORD-aligned TLP before parser
classification. No TLP header layout or parser behavior should be changed to
compensate for sequence/LCRC alignment failures in the DLL. The endpoint
line-rate tests retain Memory Read, Memory Write, Completion, and Message checks
at the TLP boundary. The associated changes were not simulated when recorded.
