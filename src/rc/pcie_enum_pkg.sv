// ---------------------------------------------------------------------------
// pcie_enum_pkg -- enumeration ENGINE and POLICY types for the Root Complex.
// Commit 2b-1.
//
// WHY THIS IS NOT IN pcie_rq_rc_pkg
//
// pcie_rq_rc_pkg states its own scope in its header: "These are DESCRIPTOR
// types, not engine types. They describe the shape of the Xilinx PG213 user
// interface." Everything here is the other thing -- PCI Configuration Space
// register numbers, transaction outcome classification, retry policy. None of
// it describes a descriptor field, so none of it belongs there. It is the same
// rule that keeps rq_req_type_e out of tlp_pkg (pcie_rq_rc_pkg.sv:143-146),
// applied one layer up.
//
// A second, practical reason: all six existing RC targets compile
// pcie_rq_rc_pkg. Leaving that file byte-identical means Commit 2b cannot
// perturb them at all. This package is purely additive.
//
// This package IMPORTS nothing and is imported alongside pcie_rq_rc_pkg by the
// enumeration RTL. Descriptor shapes are reused from there, never duplicated.
//
// ===========================================================================
// SS CITATION STATUS -- read before adding a constant
// ===========================================================================
//
// Every value here carries one of the tags established in
// SPEC_PREDICTIONS_ENUM.md SS0.2:
//
//   [BASE]      PCI Express Base Specification Rev 2.1, section + page. Golden.
//   [PCI3-REF]  the normative source is the PCI Local Bus Specification 3.0,
//               which Base 2.1 incorporates by reference (definitions p.30-31)
//               but which is NOT on this project's spec shelf. Citation pending.
//
// !! NOTHING TAGGED [PCI3-REF] IS IN THIS FILE, DELIBERATELY.
//
// The Command register's Memory Space Enable (bit 1) and I/O Space Enable
// (bit 0) are [PCI3-REF]: Base 2.1's Table 7-3 (SS7.5.1.1 p.485-487) maps only
// the bits whose PCI Express interpretation differs, and it STARTS AT BIT 2
// (Bus Master Enable, which IS [BASE]). The BAR bit layout and the
// write-all-ones sizing algorithm are [PCI3-REF] for the same reason -- Base
// 2.1 SS7.5.2.1 p.491-492 gives only usage policy and the 128-byte minimum.
//
// Those constants are deliberately NOT added ahead of the acquisition decision
// recorded in SPEC_PREDICTIONS_ENUM.md SS9. They arrive with Commit 2b-3, by
// which time PCI 3.0 is required to be on the shelf. Adding them now would put
// uncited numbers in the tree for an increment that does not use them.
//
// The REGISTER NUMBERS below are a different matter: they are read straight off
// Base 2.1 Figure 7-5 p.491, the Type 0 Configuration Space Header, and are
// [BASE] in full.
// ---------------------------------------------------------------------------
package pcie_enum_pkg;

  // -------------------------------------------------------------------------
  // Configuration Space register numbers, Type 0 header.
  // [BASE] PCIe Base 2.1 SS7.5.2 Figure 7-5 p.491.
  //
  // A Configuration Request addresses a DWORD, not a byte: the header carries
  // Register Number[5:0] and Extended Register Number[3:0] (SS2.2.7 p.79), and
  // the byte within that Dword is selected by the byte enables. So
  // reg_num == byte_offset >> 2 throughout.
  // -------------------------------------------------------------------------
  localparam logic [5:0] CFG_REG_VENDOR_DEVICE  = 6'h00;  // 00h Vendor/Device ID
  localparam logic [5:0] CFG_REG_COMMAND_STATUS = 6'h01;  // 04h Command/Status
  localparam logic [5:0] CFG_REG_REVISION_CLASS = 6'h02;  // 08h Revision/Class Code
  localparam logic [5:0] CFG_REG_CACHE_HEADER   = 6'h03;  // 0Ch CLS/MLT/HdrType/BIST
  localparam logic [5:0] CFG_REG_BAR0           = 6'h04;  // 10h
  localparam logic [5:0] CFG_REG_BAR1           = 6'h05;  // 14h
  localparam logic [5:0] CFG_REG_BAR2           = 6'h06;  // 18h
  localparam logic [5:0] CFG_REG_BAR3           = 6'h07;  // 1Ch
  localparam logic [5:0] CFG_REG_BAR4           = 6'h08;  // 20h
  localparam logic [5:0] CFG_REG_BAR5           = 6'h09;  // 24h

  // No Extended Configuration Space is reached by 2b: every register above is
  // inside the first 256 bytes, so Extended Register Number is always zero.
  localparam logic [3:0] CFG_EXT_REG_NONE = 4'h0;

  // -------------------------------------------------------------------------
  // Byte enables for the transactions Commit 2b issues.
  // [BASE] SS2.2.5 p.67 (First/Last DW BE rules); SS2.2.7 p.79 pins Last DW BE
  // to 0000b for every Configuration Request, so only first_be is ever chosen.
  // -------------------------------------------------------------------------
  // Whole Dword. Used for the Vendor/Device ID probe: SS2.3.2 p.121 and the
  // Implementation Note p.113 require the post-reset probe to access BOTH BYTES
  // of the Vendor ID field, which sets a floor of 4'b0011; reading the whole
  // Dword satisfies that floor and returns Device ID in the same completion.
  localparam logic [3:0] CFG_BE_DWORD     = 4'b1111;
  // Bytes 0-1 of a Dword -- the Command register half of register 1.
  localparam logic [3:0] CFG_BE_LOWER_HALF = 4'b0011;
  // Byte 2 of a Dword -- Header Type, at byte offset 0Eh inside register 3.
  localparam logic [3:0] CFG_BE_BYTE2      = 4'b0100;

  // Every Configuration Request: Length must be 1 DW and Last DW BE must be
  // 0000b (SS2.2.7 p.79). Both are structural here, not runtime choices.
  localparam logic [10:0] CFG_DWORD_COUNT = 11'd1;
  localparam logic [3:0]  CFG_LAST_BE     = 4'b0000;

  // -------------------------------------------------------------------------
  // How one configuration transaction ended.
  //
  // These are OUTCOMES, not policies. The same outcome means different things
  // at different points in an enumeration -- TXN_UR on a Vendor-ID probe means
  // "no device at that BDF" (SS2.3.2 Implementation Note p.122, which names the
  // existence probe explicitly), while TXN_UR on any later access to a device
  // that has already answered is a fault. pcie_cfg_txn reports; the sequencer
  // decides. Keeping that split is why the primitive is its own module.
  //
  // There is deliberately NO reserved-status outcome. Base 2.1 SS2.3.2 p.122:
  // "Completions with a Reserved Completion Status value are treated as if the
  // Completion Status was Unsupported Request (UR)." A reserved encoding is
  // therefore indistinguishable from UR by design, and inventing a sixth code
  // would invite a consumer to treat it differently than the spec allows.
  // rsp_status_raw_o carries the untranslated encoding for logging.
  // -------------------------------------------------------------------------
  typedef enum logic [2:0] {
    TXN_OK             = 3'd0,  // Successful Completion; read data valid
    TXN_UR             = 3'd1,  // Unsupported Request, or a Reserved status
    TXN_CA             = 3'd2,  // Completer Abort
    TXN_CRS_EXHAUSTED  = 3'd3,  // CRS returned CRS_RETRY_MAX times over
    TXN_TIMEOUT        = 3'd4   // completion timeout; tag quarantined upstream
  } txn_outcome_e;

  // -------------------------------------------------------------------------
  // CRS retry policy defaults. Both are IMPLEMENTATION-DEFINED.
  //
  // Base 2.1 SS2.3.2 p.121 makes Root Complex handling of a CRS Completion
  // "implementation specific", requires the not-CRS-Software-Visible case to
  // "re-issue the Configuration Request as a new Request", and explicitly
  // permits a bound: "A Root Complex implementation may choose to limit the
  // number of Configuration Request/CRS Completion Status loops" (p.121-122).
  // So the cap is sanctioned by the spec; its VALUE is not specified anywhere.
  //
  // These are simulation-convenience values, in the same spirit as
  // CPL_TIMEOUT_CYCLES = 4096 (tlp_request_tracker.sv). Real hardware must
  // tolerate the PCI/PCI-X Trhfa recovery window (SS2.3.2 Implementation Note
  // p.113); choosing a real pair belongs with the Device Control 2 programming
  // that is Stage-H work.
  //
  // !! THE RELATIONSHIP IS THE REAL CONSTRAINT, NOT EITHER NUMBER.
  // P-CRS-BUDGET (SPEC_PREDICTIONS_ENUM.md SS5.2):
  //     CRS_RETRY_MAX * CRS_BACKOFF_CYCLES < CPL_TIMEOUT_CYCLES
  // If a retry storm can outlast the completion timeout, a device that is
  // merely slow to initialise becomes indistinguishable from a dead one.
  // 16 * 64 = 1024, comfortably inside 4096. pcie_cfg_txn checks this at
  // elaboration so an override cannot silently break it.
  // -------------------------------------------------------------------------
  localparam int unsigned CRS_RETRY_MAX_DEFAULT     = 16;
  localparam int unsigned CRS_BACKOFF_CYCLES_DEFAULT = 64;

endpackage
