# Scrambler and 8b/10b Verification

## Scope

This directory contains existing scrambler and 8b/10b codec RTL. The endpoint
verification harness instantiates `byte_scramble`, `encode_8b10b`, and
`decode_8b10b` as standalone verification hooks.

They are deliberately not connected to `pcie_endpoint_top`. Testing these
blocks does not add a serial Physical Layer, PIPE, LTSSM, ordered sets, lane
logic, receiver detection, or link training to the protocol endpoint.

## Detailed checks

The endpoint cocotb test
`existing_scrambler_and_8b10b_primitives_are_checked` is intended to:

1. Encode and decode every one of the 256 data bytes with negative and
   positive incoming running disparity.
2. Require exact data recovery, legal-code indication, and matching outgoing
   disparity.
3. Exercise every legal K28.x and K23/K27/K29/K30.7 control symbol at both
   incoming disparities.
4. Inspect every possible 10-bit input and require values outside the legal
   data/control code set to report a code error.
5. Compare representative Gen1 16-bit LFSR states against an independent
   bit-level reference calculation.
6. Confirm that disabling the byte scrambler preserves its LFSR state.

The test has been added but has not been run. Simulation must wait for explicit
approval.

## Remaining codec work

The current standalone check does not prove ordered-set-specific scrambler
bypass/reset rules, multi-lane seeds, continuous Gen1/Gen2 stream
descrambling, Gen3 128b/130b block behavior, or integration through an actual
PHY datapath. Those items require a separately approved Physical Layer
verification scope and are not endpoint protocol functionality.
