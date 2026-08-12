# Endpoint Gen1 Logical-PHY Line-Rate Test

This testbench drives the real `pcie_endpoint_top` through the application,
TLP, Data Link, and packet-facing PHY boundaries in both directions. A
verification-only logical PHY adds Gen1 scrambling and 8b/10b coding after TX
and removes them before RX.

## Configurations

| FuseSoC target | Lanes | Encoded rate | Decoded capacity |
| --- | ---: | ---: | ---: |
| `sim_x1` | 1 | 2.5 GT/s | 250 MB/s |
| `sim_x4` | 4 | 10 GT/s aggregate | 1 GB/s aggregate |

Both configurations use a 250-MHz symbol clock. In x1, four consecutive
single-lane symbols are packed into one 32-bit endpoint beat. In x4, four lane
symbols map directly to one endpoint beat. Partial final groups use the symbol
keep mask.

## TX path checked

```text
Python command/payload
  -> endpoint requester and TLP generator
  -> mid_tx_axis (raw TLP)
  -> Data Link sequence/LCRC/retry path
  -> packet-facing AXI stream
  -> per-lane scrambler
  -> per-lane 8b/10b encoder
  -> Python decoder and packet scoreboard
```

The tests compare the raw TLP against the protected link packet, recalculate
LCRC, check sequence values and payloads, and ACK transmitted packets. They
cover 3-DW Memory Writes, 4-DW segmented Memory Writes, Memory Reads,
Completions with Data, Messages, and Messages with Data. A three-packet
128-byte burst reports protected-byte throughput and endpoint utilization for
both lane counts.

## RX path checked

```text
Python TLP/sequence/LCRC construction
  -> Python per-lane scrambler and 8b/10b encoder
  -> SystemVerilog per-lane decoder and descrambler
  -> packet-facing AXI stream
  -> Data Link sequence/LCRC validation and ACK
  -> mid_rx_axis (raw TLP)
  -> TLP parser/BAR routing
  -> target header and payload
```

The RX tests compare reconstructed raw TLPs and target/application payloads,
check BAR routing and header fields, and require the generated ACK sequence.
An incoming Memory Read is completed through the endpoint completion-request
interface. A locally generated Memory Read receives Completion-with-Data and
must return the original context and payload. Generic Message traffic checks
all six routing encodings, message codes, routing-specific header data, and
payload backpressure.

RX request tests retain the most recent complete frame at three boundaries:
decoded logical-PHY output, post-DLL/pre-configuration routing, and TLP parser
input. If a target request times out, the failure reports exact/missing/frame
mismatch status for each boundary together with DLL sequence/LCRC decisions,
parser state and legality, ACK/NAK state, and codec error flags. This makes the
first layer that rejected or altered the packet explicit in the test result.

## Dataflow test matrix

| Test | End-to-end behavior |
| --- | --- |
| `tx_crosses_tlp_dll_and_gen1_logical_phy_at_lane_rate` | Application Memory Write through TLP, DLL, scrambling, 8b/10b, and lane output. |
| `tx_back_to_back_packets_measure_endpoint_utilization` | Three consecutive posted writes and cumulative throughput. |
| `rx_crosses_gen1_logical_phy_dll_and_tlp_at_lane_rate` | Encoded Memory Write through PHY decode, DLL validation, TLP parsing, BAR routing, and target payload. |
| `tx_4dw_memory_write_mps_segmentation_preserves_data` | A payload above MPS split into consecutive 4-DW writes without loss or reordering. |
| `tx_unaligned_and_4k_split_memory_writes_preserve_valid_bytes` | Unaligned byte enables/padding and mandatory 4-KiB request splitting. |
| `tx_memory_read_and_rx_completion_return_application_data` | Local Memory Read, tag allocation, returned Completion-with-Data, context match, and tag retirement. |
| `multiple_outstanding_reads_accept_out_of_order_completion_data` | Two live tags completed in reverse order with independent payload/context checks. |
| `rx_memory_read_and_tx_completion_cross_every_layer` | Incoming Memory Read followed by application-generated Completion-with-Data across the TX stack. |
| `messages_and_messages_with_data_cross_tx_and_rx` | TX/RX Message and Message-with-Data transport, including routing values 0 through 5. |
| `mixed_posted_nonposted_and_message_traffic_preserves_order` | Ordered posted, non-posted, and Message traffic, cumulative ACK, and completion return. |
| `rx_illegal_8b10b_symbol_is_reported_and_packet_is_rejected` | Illegal symbol reporting, packet rejection, and NAK generation. |

The Message command interface uses `command_message_route_i` and
`command_message_code_i`. `command_address_i` carries the routing-specific
64-bit header data for a Message. Received messages assert `target_message_o`;
their route, code, and routing data appear on `target_message_route_o`,
`target_message_code_o`, and `target_message_data_o`. Message-with-Data uses
the normal target payload stream.

## Rate accounting

`tx/rx_payload_byte_count_o` count decoded protected-link bytes accepted by the
logical PHY. `tx/rx_active_cycle_count_o` count cycles containing at least one
symbol group. The ideal active cycles for a frame are:

```text
ceil(protected_frame_bytes / lane_count)
```

Wall-clock cycles can be higher because of TLP generation, credit checks,
DLLP arbitration, LCRC alignment, ACK handling, or application backpressure.
The cocotb log reports both active capacity and elapsed endpoint utilization.

## FuseSoC commands

After registering the repository, the targets are:

```bash
fusesoc run --target=sim_x1 fusesoc:pcie:tb_endpoint_line_rate:1.0.0
fusesoc run --target=sim_x4 fusesoc:pcie:tb_endpoint_line_rate:1.0.0
```

The targets use Verilator and require cocotb plus `cocotbext-pcie`. Verilator
is selected because the endpoint dependencies use legal SystemVerilog
streaming concatenations, assignment patterns, and `inside` expressions that
Icarus does not support. They are separate from the VCS endpoint functional
target.

The generated PeakRDL configuration block uses separate sequential processes
for disjoint leaves of one aggregate. Its source locally waives Verilator's
`MULTIDRIVEN` warning for that generated module only. The simulation-only x1/x4
logical-PHY model similarly scopes the conservative `LATCH` warning associated
with its mutually exclusive parameter branches. Neither warning is disabled
globally, so the same warnings in other RTL remain visible.

## Boundaries

This is a logical simulation model, not a transceiver or electrical compliance
test. SOP/EOP and packet class are verification metadata rather than encoded K
symbols. Lanes are ideally synchronized. The test does not implement LTSSM,
PIPE, ordered sets, SKP insertion, receiver detection, deskew, lane reversal,
equalization, or a serial channel. Hardware proof still requires synthesis,
timing closure, a board-specific transceiver wrapper, and a PCIe link partner
or analyzer.

## Safekeeping note (2026-08-12)

The x1 logical PHY naturally places idle cycles between 32-bit endpoint words;
the endpoint RX regression therefore depends on handshake-based, bubble-safe
DLL sequence/LCRC removal. Standalone DLL regressions also inject a repeatable
three-idle/one-transfer source pattern to preserve coverage of this behavior.

The Message TX/RX test submits traffic in groups of three because the fixture's
retry buffer holds three unacknowledged TLPs. Each group is decoded and retired
with a cumulative ACK before the next group. Command-header and payload waits
are bounded and identify retry-buffer or credit backpressure on timeout. No
simulation was run while making these changes; the FuseSoC commands above await
explicit approval.
