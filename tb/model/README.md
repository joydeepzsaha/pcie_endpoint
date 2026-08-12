# Python Endpoint BFM testbench

`test_endpoint_bfm.py` verifies `PcieEndpointBfm`, the Python behavioral
equivalent of `pcie_endpoint_top`. `test_protocol.py` contains focused tests
for TLP/DLLP codecs, Flow Control, and the Data Link Layer.
`test_gen1_phy.py` covers the bidirectional Gen1 scrambler and 8b/10b symbol
paths. `test_support.py` supplies deterministic eRC packet and payload
builders.

The testbench uses the Python standard-library `unittest` framework and does
not require a vendor simulator or third-party package.

The BFM suites cover:

* Application commands, partial first/last DWORDs, MPS and 4-KiB
  segmentation, 3DW/4DW selection, prefix/ECRC, and invalid local payloads.
* Target classification, BAR hit/full-span miss/overlap behavior,
  configuration BDF routing, offsets, payload delivery, and unsupported flags.
* Non-Posted tag allocation, context tracking, Completion delivery/result
  retirement, and unexpected or inconsistent Completions.
* Application-generated successful and error Completions, MPS/RCB splitting,
  lower addresses, byte counts, ECRC, and arbitration against requests.
* P/NP/Cpl credit gating, starvation/release, link initialization, and
  link-down cleanup.
* All 256 8b/10b data values and all twelve legal PCIe K symbols at both
  incoming running disparities.
* Invalid 10-bit codes, wrong running disparity, persistent TX/RX disparity,
  Gen1 LFSR reference states, scrambling/descrambling round trips, control
  bypass, SKP hold, and COM reset.

The lower-layer suites additionally cover:

* TLP and DLLP encoding, CRC corruption, 3DW/4DW addressing, and the special
  1024-DW length encoding.
* Header legality, byte enables, 4-KiB boundaries, MPS, and MRRS.
* Independent P/NP/Cpl header/data credits, exact exhaustion, updates,
  CL/CC gating, Credit Allocated/Credits Received overflow checking,
  wraparound through `CA == CR`, infinite initial credits, and receive-credit
  return.
* All Data Link Layer states, early/duplicate InitFC traffic, link loss, and
  reinitialization.
* Sequence rollover, duplicate TLPs, bad LCRC, future sequence numbers,
  ACK/NAK, replay, replay timeout, and queue backpressure.
* Deterministic mixed traffic and reset cleanup.

The eRC agent constructs protocol-level link events, while focused codec tests
check the serialized TLP/DLLP fields and CRC corruption behavior at the raw
word/byte boundary.

No execution is performed automatically. When execution is explicitly
authorized, the standard-library discovery command from the repository root
is:

```bash
python3 -m unittest discover -s tb/model -p 'test_*.py'
```
