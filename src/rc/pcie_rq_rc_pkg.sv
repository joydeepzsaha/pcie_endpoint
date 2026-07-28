// ---------------------------------------------------------------------------
// pcie_rq_rc_pkg -- RC-surface types for the PG213 requester/completer
// descriptors (Commit 2a).
//
// These are DESCRIPTOR types, not engine types. They describe the shape of the
// Xilinx PG213 user interface, which is an artefact of the wrapper we are
// building, not of the PCIe Transaction Layer. tlp_pkg stays untouched: it is
// append-only and owned by the TL, and nothing in here belongs there.
//
// Sources for every constant below:
//   RQ descriptor field map ..... PG213 v1.3, Fig 42 / Table 61 (Configuration)
//                                 and Fig 41 / Table 60 (Memory/IO), via the
//                                 addendum -- cited as such, not read from the
//                                 PDF, which is still unavailable.
//   Request Type encodings ...... PG213 v1.3, Table 57.
//   Byte-enable rules ........... PCIe Base Spec 2.1 SS2.2.7.
//
// The byte-count arithmetic here is the wrapper's half of the contract with
// tlp_requester: the TL re-derives the byte enables internally from
// command_address[1:0] and the byte count (tlp_requester.sv:129-130 calling
// tlp_pkg::tlp_first_be / tlp_last_be), so the wrapper must produce an
// (offset, byte_count) pair that reproduces the descriptor's byte enables
// exactly. rq_byte_count() below is that pair's second half; pcie_rq_if checks
// the round trip before launching anything.
// ---------------------------------------------------------------------------
package pcie_rq_rc_pkg;

  // -------------------------------------------------------------------------
  // RQ descriptor -- 128 b, PG213 v1.3 Table 60/61.
  //
  // Declared MSB-first so the packed struct's bit numbering is literally the
  // table's. Fields that differ between the Configuration and Memory/IO forms
  // share a slot and are re-interpreted by the consumer:
  //
  //   address[63:12] : Memory/IO address bits, or Reserved for Configuration
  //   address[11:8]  : Memory/IO address bits, or Ext Reg Number
  //   address[7:2]   : Memory/IO address bits, or Register Number
  //   address[1:0]   : Address Type (AT) for Memory/IO, Reserved for Config
  //   completer_id   : the target BDF for Configuration and ID-routed requests
  // -------------------------------------------------------------------------
  typedef struct packed {
    logic        force_ecrc;       // [127]     ignored -- ECRC is TL-generated
    logic [2:0]  attr;             // [126:124] -> command_attr_i
    logic [2:0]  tc;               // [123:121] -> command_tc_i
    logic        requester_id_en;  // [120]     ignored -- TL uses requester_id_i
    logic [15:0] completer_id;     // [119:104] target BDF
    logic [7:0]  tag;              // [103:96]  IGNORED -- tags are core-managed
    logic [15:0] requester_id;     // [95:80]   IGNORED -- TL uses requester_id_i
    logic        poisoned;         // [79]
    logic [3:0]  req_type;         // [78:75]
    logic [10:0] dword_count;      // [74:64]
    logic [63:0] address;          // [63:0]    see the note above
  } rq_descriptor_t;

  // -------------------------------------------------------------------------
  // Request Type, PG213 v1.3 Table 57. All sixteen encodings are named so the
  // field is total and no value can fall outside the enum -- the six mapped
  // ones become tlp_cmd_e, the other ten are rejected by pcie_rq_if.
  // -------------------------------------------------------------------------
  typedef enum logic [3:0] {
    RQ_MEM_READ        = 4'b0000,  // -> TLP_CMD_MEM_READ
    RQ_MEM_WRITE       = 4'b0001,  // -> TLP_CMD_MEM_WRITE
    RQ_IO_READ         = 4'b0010,  // -> TLP_CMD_IO_READ
    RQ_IO_WRITE        = 4'b0011,  // -> TLP_CMD_IO_WRITE
    RQ_MEM_FETCH_ADD   = 4'b0100,  // reject -- no atomic command path
    RQ_MEM_SWAP        = 4'b0101,  // reject
    RQ_MEM_CAS         = 4'b0110,  // reject
    RQ_MEM_RD_LOCKED   = 4'b0111,  // reject -- locked reads out of scope
    RQ_CFG_READ0       = 4'b1000,  // -> TLP_CMD_CFG_READ0
    RQ_CFG_READ1       = 4'b1001,  // reject -- Type 1 config is Commit 3
    RQ_CFG_WRITE0      = 4'b1010,  // -> TLP_CMD_CFG_WRITE0
    RQ_CFG_WRITE1      = 4'b1011,  // reject -- Type 1 config is Commit 3
    RQ_MSG_ROUTED      = 4'b1100,  // reject -- messages out of scope
    RQ_MSG_ID          = 4'b1101,  // reject
    RQ_MSG_VENDOR      = 4'b1110,  // reject
    RQ_MSG_ATS         = 4'b1111   // reject -- ATS/reserved
  } rq_req_type_e;

  // -------------------------------------------------------------------------
  // Why a descriptor was refused. Reported on rq_error_code_o alongside the
  // one-cycle rq_protocol_error_o pulse. RQ_ERR_NONE is never presented with
  // the pulse asserted.
  // -------------------------------------------------------------------------
  typedef enum logic [3:0] {
    RQ_ERR_NONE            = 4'd0,
    RQ_ERR_REQ_TYPE        = 4'd1,  // Request Type outside the mapped six
    RQ_ERR_DWORD_COUNT     = 4'd2,  // Dword Count 0 or > 1024
    RQ_ERR_CFG_DWORD_COUNT = 4'd3,  // Configuration request with Dword Count != 1
    RQ_ERR_CFG_IO_FIT      = 4'd4,  // config/IO request does not fit one Dword
    RQ_ERR_4KB             = 4'd5,  // request crosses a 4 KB boundary
    RQ_ERR_ADDRESS_TYPE    = 4'd6,  // AT != 00 on a Memory/IO request
    RQ_ERR_POISON_CFG_WR   = 4'd7,  // poisoned Configuration write
    RQ_ERR_BYTE_COUNT_FIT  = 4'd8,  // byte count exceeds command_byte_count_i
    RQ_ERR_BE_MISMATCH     = 4'd9,  // byte enables not reproducible by the TL
    RQ_ERR_ZERO_LENGTH     = 4'd10, // Dword Count 1 with first_be == 0
    RQ_ERR_EARLY_LAST      = 4'd11, // tlast before the Dword Count was met
    RQ_ERR_MISSING_LAST    = 4'd12  // beats continue past the Dword Count
  } rq_error_e;

  // -------------------------------------------------------------------------
  // Byte-enable arithmetic
  // -------------------------------------------------------------------------

  // Number of set bits in a byte-enable nibble (0..4).
  function automatic logic [3:0] rq_popcount4(input logic [3:0] be);
    rq_popcount4 = {3'd0, be[0]} + {3'd0, be[1]} + {3'd0, be[2]} + {3'd0, be[3]};
  endfunction

  // Position of the least-significant set bit of first_be -- the byte offset
  // within the addressed Dword, which becomes command_address[1:0]. Defined as
  // 0 for first_be == 0; that case is rejected separately (RQ_ERR_ZERO_LENGTH),
  // because a zero first_be is NOT caught by the byte-enable round trip:
  // tlp_first_be(0, 0) is also 0, so the comparison agrees and lets it through.
  function automatic logic [1:0] rq_be_offset(input logic [3:0] be);
    if      (be[0]) rq_be_offset = 2'd0;
    else if (be[1]) rq_be_offset = 2'd1;
    else if (be[2]) rq_be_offset = 2'd2;
    else if (be[3]) rq_be_offset = 2'd3;
    else            rq_be_offset = 2'd0;
  endfunction

  // Bytes actually transferred, from the Dword Count and the two byte-enable
  // nibbles. Piecewise on purpose -- a single formula is wrong at n == 1:
  //
  //   n == 1 : only first_be participates; last_be must be 0000 (PCIe 2.1
  //            SS2.2.7), and the general formula's (n-2)*4 term underflows.
  //   n == 2 : the general formula with a zero middle term.
  //   n >= 3 : first Dword partial, (n-2) whole Dwords, last Dword partial.
  //
  // Worst case is n = 1024 -> 4 + 4088 + 4 = 4096, inside the 13-bit
  // command_byte_count_i.
  function automatic logic [12:0] rq_byte_count(input logic [10:0] n,
                                                input logic [3:0]  first_be,
                                                input logic [3:0]  last_be);
    logic [12:0] middle;
    if (n <= 11'd1) begin
      rq_byte_count = {9'd0, rq_popcount4(first_be)};
    end else begin
      middle = (n == 11'd2) ? 13'd0 : 13'({n - 11'd2, 2'b00});
      rq_byte_count = {9'd0, rq_popcount4(first_be)} + middle +
                      {9'd0, rq_popcount4(last_be)};
    end
  endfunction

endpackage
