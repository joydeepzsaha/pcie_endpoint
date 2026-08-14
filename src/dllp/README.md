# PCIe Data Link Layer and DLLP Logic

## Purpose

This directory implements the PCIe Data Link Layer. Although the directory is
named `dllp`, it handles both Data Link Layer Packets and the reliable transport
of Transaction Layer Packets.

The integration module is
[`pcie_datalink_layer.sv`](pcie_datalink_layer.sv). Generated and
module-specific documentation remains available under [`docs`](docs).

## Main responsibilities

The Data Link Layer:

- Initializes link-level flow control.
- Distinguishes incoming TLPs from DLLPs.
- Adds 12-bit sequence numbers and 32-bit LCRC values to outgoing TLPs.
- Checks sequence numbers and LCRC values on incoming TLPs.
- Generates ACK and NAK DLLPs.
- Stores unacknowledged TLPs in a retry buffer.
- Replays TLPs after a NAK or replay-timer expiration.
- Validates the 16-bit CRC on received DLLPs.
- Decodes InitFC, UpdateFC, ACK, NAK, and Feature Exchange DLLPs.
- Arbitrates TLPs, flow-control DLLPs, ACK/NAK DLLPs, and replay traffic toward
  the Physical Layer.

## RTL components

| Module | Responsibility |
| --- | --- |
| `pcie_datalink_layer.sv` | Top-level Data Link integration and AXI-Stream arbitration. |
| `pcie_datalink_init.sv` | DL_Inactive, initialization, FC1, FC2, and DL_Active control. |
| `pcie_flow_ctrl_init.sv` | InitFC1, InitFC2, and UpdateFC DLLP generation. |
| `dllp_receive.sv` | Incoming TLP/DLLP separation, Data Link receive processing, and configuration-path integration. |
| `dllp_handler.sv` | DLLP framing/CRC validation and ACK/NAK/flow-control decode. |
| `dllp2tlp.sv` | Incoming link-packet sequence/LCRC validation, ACK/NAK scheduling, and raw-TLP delivery. |
| `dllp_transmit.sv` | Outgoing TLP sequencing, LCRC generation, retry storage, and replay coordination. |
| `tlp2dllp.sv` | Outgoing raw-TLP conversion into a Data Link protected link packet. |
| `retry_management.sv` | Outstanding sequence tracking, cumulative ACK processing, NAK replay, timeout, and replay-attempt accounting. |
| `retry_transmit.sv` | Selection and retransmission of stored retry-buffer packets. |
| `axis_retry_fifo.sv` | Packet storage used by the retry path. |
| `axis_user_demux.sv` | Incoming `tuser`-based TLP/DLLP classification. |
| `dllp_fc_update.sv` | Flow-control update generation from receive-side credit consumption. |

## Interface conventions

With the default 32-bit interface:

- `s_tlp_axis_*` accepts raw TLPs from the Transaction Layer.
- `m_tlp_axis_*` returns validated raw TLPs to the Transaction Layer.
- `s_phy_axis_*` accepts link packets and DLLPs from the Physical Layer.
- `m_phy_axis_*` emits link packets and DLLPs toward the Physical Layer.
- Physical input `tuser[0]` identifies a DLLP.
- Physical input `tuser[1]` identifies a TLP/link packet.

The top exports the most recently received posted, non-posted, and completion
credits so the Transaction Layer can make transmit decisions.

## Testbench organization

Data Link tests are in [`../../tb/dllp`](../../tb/dllp).

### Comprehensive integration test

[`test_dll_comprehensive.py`](../../tb/dllp/test_dll_comprehensive.py) drives
`pcie_datalink_layer` through the repository-level Makefile. It is the broadest
Data Link regression and is divided into these phases:

1. Reset, link-up, and InitFC1/InitFC2 exchange.
2. Local Transaction Layer TLP transmission toward the Physical Layer.
3. Valid incoming TLP delivery toward the Transaction Layer.
4. Bad-LCRC NAK generation and sequence-number errors.
5. Received ACK/NAK processing and replay.
6. Malformed TLP and DLLP rejection.
7. UpdateFC handling and zero-credit transmit blocking.
8. Replay-timer retransmission.
9. Corrupt ACK/NAK rejection, cumulative ACK, replay ordering, and sequence
   window boundaries.
10. NAK scheduling suppression and ACK latency.
11. TLP class and 3-DW/4-DW format preservation.
12. Posted, non-posted, and completion flow-control behavior and wraparound.
13. Retry-buffer full behavior and slot reuse.
14. Receive and transmit sequence rollover from `0xFFF` to `0x000`.
15. Optional Physical Layer output backpressure.
16. Link-down/reset behavior with pending traffic or replay.
17. Replay-timer attempt exhaustion.
18. Repeated-NAK replay-attempt exhaustion.

The test uses Python reference functions for DLLP CRC, LCRC, packet formats,
sequence arithmetic, and expected ACK/NAK behavior. A background monitor
classifies every physical output frame and prevents unconsumed protocol
responses from being silently discarded.

### Focused tests

| Test | Primary coverage |
| --- | --- |
| `test_dllp_handler.py` | Two-beat DLLP framing, CRC validation, ACK/NAK decode, InitFC/UpdateFC storage, reserved fields, bad CRC, and reset. |
| `test_dllp_recieve.py` | Integrated receive demultiplexing and forwarding. The filename retains the existing spelling. |
| `test_dllp2tlp.py` | Sequence/LCRC checking, TLP forwarding, ACK/NAK generation, and receive-side credit accounting. |
| `test_tlp2dllp.py` | Sequence insertion, LCRC generation, and outgoing TLP framing. |
| `test_retry_management.py` | ACK retirement, NAK replay selection, timers, retry limits, and retry slot state. |
| `test_dllp_transmit.py` | Outgoing sequencing, replay buffering, flow-control interaction, and Physical Layer stream generation. |
| `test_pcie_datalink_layer.py` | Earlier integrated Data Link functional coverage and shared helper routines. |
| `test_pcie_dllp_core.py` | FuseSoC-oriented Data Link core test. |

SystemVerilog harnesses in the same directory instantiate focused modules when
the raw RTL module is not used directly as the cocotb top.

## Common test process

A Data Link test generally performs these steps:

1. Start the clock and assert reset.
2. Drive all AXI-Stream inputs and status inputs to known values.
3. Confirm output `valid` signals and initialization status are cleared.
4. Release reset and assert `phy_link_up_i`.
5. Exchange all required InitFC1 and InitFC2 DLLPs.
6. Wait for Data Link initialization to complete.
7. Send a raw TLP from the Transaction Layer or a protected link packet from
   the Physical Layer.
8. Capture every output frame and determine whether it is a TLP or DLLP.
9. Recalculate CRC/LCRC and compare sequence numbers and payload bytes.
10. Send ACK, NAK, UpdateFC, malformed, or corrupted traffic as required.
11. Check replay-buffer, timeout, flow-control, and backpressure behavior.
12. Confirm a later valid packet succeeds after every injected error.

All source and sink transfers use ready/valid handshakes. When backpressure is
enabled, the test verifies that `tdata`, `tkeep`, `tlast`, and `tuser` remain
stable until the transfer completes.

## Running the tests

### Comprehensive VCS regression

The repository-level [`../../Makefile`](../../Makefile) selects
`test_dll_comprehensive` and writes both a cocotb XML result and a text log.

```bash
make test-log
```

### Focused FuseSoC tests

Run the complete Data Link core test with Icarus:

```bash
fusesoc run --target=default fusesoc:pcie:tb_dllp_core:1.0.0
```

Run receive-focused tests:

```bash
fusesoc run --target=default fusesoc:pcie:tb_dllp_receive:1.0.0
fusesoc run --target=sim_dllp2tlp fusesoc:pcie:tb_dllp_receive:1.0.0
```

Run the transmit-focused test:

```bash
fusesoc run --target=default fusesoc:pcie:tb_dllp_transmit:1.0.0
```

Simulator support differs between targets: the comprehensive Makefile selects
VCS, while the default focused FuseSoC targets select Icarus and some `sim`
targets select Verilator.

These commands are documentation only. They should not be executed until the
documentation and RTL state have been reviewed and test execution has been
explicitly approved.

## Pass criteria

A Data Link regression passes when:

- InitFC exchange reaches the initialized state with the expected credits.
- Outgoing TLPs contain the correct sequence number and LCRC.
- Incoming good TLPs are delivered exactly once and produce the expected ACK.
- Bad LCRC or future sequence values do not reach the Transaction Layer and
  produce the expected NAK.
- Duplicate packets are not delivered twice.
- ACKs retire the correct cumulative set of retry entries.
- NAK and timeout replays preserve packet bytes and ordering.
- Invalid or corrupt DLLPs do not change retry or credit state.
- Credit exhaustion blocks transmission without dropping the packet.
- Sequence and credit counters behave correctly across wraparound.
- Link reset clears pending protocol state.
- No cocotb assertion, unknown-value check, or timeout fails.

## Scope

These tests validate the RTL model's Data Link behavior at packet-stream
boundaries. They do not validate analog signaling, equalization, lane
alignment, LTSSM compliance, or the physical symbol encoding used on an actual
PCIe link.

## Change notes (12-Aug-26)

The receive aligner in `dllp2tlp.sv` stores only AXI words that complete a
ready/valid handshake. It uses one accepted protected word plus one pending TLP
DWORD to remove the two-byte sequence prefix, separate the four-byte LCRC, and
mark the final FIFO beat good or bad. Do not restore raw-input look-ahead or
delay taps whose input-ready ports are disconnected: either change makes LCRC
checking depend on adjacent valid cycles and breaks x1 traffic containing
normal source-idle gaps.

Both DLL regression suites insert three idle source cycles between accepted
words of one valid receive TLP. This protects the bubble-safe alignment rule.
The changes were intentionally not simulated when added; run the documented
regressions only after explicit execution approval.
