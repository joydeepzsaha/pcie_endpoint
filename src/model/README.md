# PCIe Gen1 Endpoint bus functional model

This directory contains a cycle-stepped Python bus functional
model of [`pcie_endpoint_top.sv`](../pcie_endpoint/pcie_endpoint_top.sv).
`model.PcieEndpointBfm` is the canonical top. Its boundary is:

```text
eRC packet agent
       |
       | 10-bit Gen1 symbols: 8b/10b + scrambling
       v
Gen1PhyCodec TX/RX
       |
       | LinkEvent: sequenced TLPs, DLLPs, LCRC
       v
PcieEndpointBfm
       |
       | EndpointCommand / TargetRequest
       | CompletionRequest / ReceivedCompletion / CompletionResult
       v
Endpoint application BFM
```

The protocol model is packet- and transaction-accurate, rather than AXI beat-
or electrical-cycle-accurate. Whole packet objects replace the 32-bit
ready/valid streams while retaining their backpressure through bounded queues.
The optional symbol boundary maintains independent persistent transmitter and
receiver scrambler and running-disparity state. It is independent of
AXI-Stream, Avalon-ST, PIPE, and vendor PCIe IP.

The BFM includes Gen1 scrambling/descrambling and 8b/10b
encoding/decoding, including all 256 data values, the twelve legal PCIe K
symbols, running-disparity tracking, and code/disparity errors. It does not
implement analog serialization, clock recovery, receiver detection, PIPE,
LTSSM/lane training, lane alignment, or electrical behavior.

## Model coverage

* Application command bus for Memory Read/Write, Configuration Type-0
  Read/Write, and I/O Read/Write.
* Request segmentation at MPS, MRRS, and 4-KiB boundaries; 3DW/4DW headers,
  byte enables, prefixes, ECRC, and fixed-capacity payload buses.
* Received target-request bus with classification, read/write indication,
  static BAR full-span decode/overlap detection, Configuration BDF decode,
  and unsupported indication.  The application decides how to respond.
* Application completion-request generation split at MPS and 64/128-byte RCB
  boundaries.
* Received-completion and result buses with tag allocation, context return,
  lower-address/byte-count validation, multi-completion retirement, and
  unexpected-completion reporting.
* Gen1 Data Link state machine: `INACTIVE`, `FC_INIT1`, `FC_INIT2`,
  `DL_ACTIVE`.
* InitFC1, InitFC2, and UpdateFC DLLPs for Posted, Non-Posted, and Completion
  header/data credits.
* Transmitter Pending-TLP queues, cumulative Credit Limit (CL), Credits
  Consumed (CC), and the PCIe modulo `CL - (CC + PTLP)` gating equation.
* Receiver cumulative Credit Allocated and Credits Received counters,
  physical buffer occupancy, periodic credit return, modulo wrap, starvation,
  infinite-credit handling, and strict `CA-CR` fatal overflow detection
  (`CA == CR` remains legal).
* 12-bit sequence numbers, ACK/NAK, duplicate suppression, LCRC, replay
  timeout, replay limits, and link-down cleanup.
* Receive header/payload validation, poisoned-request propagation, the
  1024-DW length encoding, queue backpressure, and link-down cleanup.
* Independent Gen1 TX and RX symbol paths: 16-bit per-lane LFSRs,
  scrambling/descrambling, legal K-symbol bypass, 8b/10b running disparity,
  invalid-code detection, and disparity-error reporting.

## Integration contract

Import the model from the repository `src` directory:

```python
from model import PcieEndpointBfm

endpoint = PcieEndpointBfm()
```

Call `PcieEndpointBfm.tick()` once per model clock. Drive link state through
`set_phy_link_up()`, place received framed traffic into `push_link_rx()`, and
retrieve transmitted traffic with `pop_link_tx()`.

Use `submit_command()` for the RTL command input bus, `pop_target_request()` for
the target output bus, `submit_completion()` for the completion-request input,
and `pop_received_completion()`/`pop_result()` for the corresponding outputs.
Queue-full return values represent deasserted ready.  Status events remain
latched until `clear_status_events()` so a testbench cannot miss a one-cycle
RTL-style pulse.

Use `encode_phy_tx_symbol()` for the persistent transmitter path and
`decode_phy_rx_symbol()` for the persistent receiver path. The latter latches
`phy_rx_code_error` and `phy_rx_disparity_error` in `EndpointBfmStatus`.
Both methods accept ordered-set controls for LFSR advance and reset. For
example, a SKP symbol can use `advance_lfsr=False`, while a COM that
initializes the following stream can use `reset_lfsr_after=True`.

`LinkEvent` is the packet-level PHY boundary. `ModelConfig.GEN1_TRANSFER_RATE`
records the
2.5-GT/s Gen1 operating point, but serialization timing is deliberately owned
by the adapter.  This lets the same BFM connect to an eRC packet agent or to any
FPGA-IP shim without embedding vendor-specific interfaces.

The implementation uses only the Python standard library. Queue, replay, tag,
BAR, and payload limits are defined in `config.py`; bounded FIFO objects model
ready/valid backpressure. It is a software BFM and is not synthesizable FPGA
logic.

## File ownership

| File | Behavior |
| --- | --- |
| `endpoint_bfm.py` | Complete Endpoint application buses, requester, completer, tags, BAR/BDF routing, and status. |
| `data_link.py` | Link state, sequencing, ACK/NAK, replay, LCRC, and DLLP scheduling. |
| `flow_control.py` | P/NP/Cpl CL/CC/CA/CR counters, modulo gating, updates, and overflow checking. |
| `tlp.py` | TLP/DLLP codecs, classification, validation, ECRC, and LCRC. |
| `types.py` | Protocol enums, packets, status, credits, and bounded queues. |
| `config.py` | Gen1 operating point and model capacities. |
| `crc.py` | CRC16 and CRC32 primitives. |
| `gen1_phy.py` | Bidirectional Gen1 LFSR scrambler/descrambler and 8b/10b codec. |
| `__init__.py` | Public package API. |
