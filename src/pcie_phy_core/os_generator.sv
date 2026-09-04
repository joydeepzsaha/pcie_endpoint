module os_generator
  import pcie_phy_pkg::*;
#(
    parameter int CLK_RATE      = 100,             //!Clock speed in MHz, Defualt is 100
    parameter int MAX_NUM_LANES = 4,               //! Maximum number of lanes module can support
    // TLP data width
    parameter int DATA_WIDTH    = 32,              //! AXIS data width
    // TLP keep width
    parameter int KEEP_WIDTH    = DATA_WIDTH / 8,
    parameter int USER_WIDTH    = 4
    // parameter int LINK_NUM      = 0,
    // parameter int IS_UPSTREAM   = 0,                  //downstream by default
    // parameter int CROSSLINK_EN  = 0,                  //crosslink not supported
    // parameter int UPCONFIG_EN   = 0                   //upconfig not supported
) (
    //clocks and resets
    input  logic                                               clk_i,             // Clock signal
    input  logic                                               rst_i,             // Reset signal
    //gen os control signals
    input  gen_os_struct_t                                     gen_os_ctrl_i,
    input  rate_speed_e                                        curr_data_rate_i,
    input  logic                                               send_ltssm_os_i,
    output logic                                               os_sent_o,
    // Per-lane ordered sets from the LTSSM (Decision 1: LTSSM-authoritative
    // lane numbers). Lane l's OS already carries its own lane_num.
    input  pcie_ordered_set_t [             MAX_NUM_LANES-1:0] ordered_set_i,
    input  presets_coeff_t    [             MAX_NUM_LANES-1:0] preset_i,
    input  logic                                               link_up_i,
    //! @virtualbus master_axis_bus @dir out
    output logic              [(DATA_WIDTH*MAX_NUM_LANES)-1:0] m_axis_tdata,
    output logic              [(KEEP_WIDTH*MAX_NUM_LANES)-1:0] m_axis_tkeep,
    output logic                                               m_axis_tvalid,
    output logic                                               m_axis_tlast,
    output logic              [(USER_WIDTH*MAX_NUM_LANES)-1:0] m_axis_tuser,
    input  logic                                               m_axis_tready
    //! @end

);

  typedef enum logic [7:0] {
    ST_IDLE,
    ST_BUILD,
    ST_SEND,
    ST_SKP
  } os_gen_state_e;

  // The SKP scheduling threshold, in counts of pipe_rx_usr_clk_i.  Solved in
  // §54 #9(C) from the MEASURED relation interval = 2N + 2 -- see the derivation
  // at the ST_IDLE test below.  It is a localparam because TWO decision sites
  // now consult it (ST_IDLE, and the ST_SEND boundary added by §54 #9(A)), and
  // two bare literals governing one schedule is a drift hazard.
  localparam logic [31:0] SkpIntervalCounts = 32'h2A6;


  // os_gen_state_e                                  curr_state;
  // os_gen_state_e                                  D.state;

  // logic          [                           7:0] D.axis_pkt_cnt;
  // logic          [                           7:0] Q.axis_pkt_cnt;

  // logic          [                           7:0] os_pkt_cnt_c;
  // logic          [                           7:0] Q.os_pkt_cnt;

  // logic          [(USER_WIDTH*8)-1:0] D.special_k;
  // logic          [(USER_WIDTH*8)-1:0] Q.special_k;

  // pcie_tsos_t    [             MAX_NUM_LANES-1:0] D.ordered_set;
  // pcie_tsos_t    [             MAX_NUM_LANES-1:0] Q.ordered_set;
  //! internal_axis_signals
  logic [(DATA_WIDTH*MAX_NUM_LANES)-1:0] ltssm_axis_tdata;
  logic [(KEEP_WIDTH*MAX_NUM_LANES)-1:0] ltssm_axis_tkeep;
  logic                                  ltssm_axis_tvalid;
  logic                                  ltssm_axis_tlast;
  logic [(USER_WIDTH*MAX_NUM_LANES)-1:0] ltssm_axis_tuser;
  logic                                  ltssm_axis_tready;
  // logic                                           D.os_sent;


  typedef struct {
    os_gen_state_e                  state;
    logic [7:0]                     axis_pkt_cnt;
    logic [7:0]                     os_pkt_cnt;
    // E5 of tracker sec 54 #5's bundle -- the shape change the other four need.
    //
    // WAS: logic [(USER_WIDTH*8)-1:0] special_k -- ONE mask for the whole Link,
    // strided by USER_WIDTH.  Two things were wrong with that.
    //
    // (a) One mask cannot be per-lane.  Base 2.1 Table 4-2 p.201 gives Symbols 1
    //     and 2 as the Link and Lane Numbers, each "D0.0 - D31.0, K23.7" -- so
    //     each is a control code iff THAT Lane's byte is PAD, and sec 4.2.6.3.2.2
    //     p.231 makes PAD on the remaining Lanes of an Upstream Port mandatory.
    //     Lanes legitimately disagree here, so the mask must too.
    //
    // (b) The stride was USER_WIDTH where a beat carries DATA_WIDTH/8 Symbols.
    //     phy_transmit instantiates this module with USER_WIDTH = 5 and
    //     DATA_WIDTH = 32 (phy_transmit.sv:12), so the mask strode by 5 across
    //     4-Symbol beats and bit 4 of every slice was a phantom fifth Symbol.
    //     Inert only because bits 0-2 of beat 0 are the only ones ever set --
    //     the layout's USER_WIDTH == symbols-per-beat invariant was already
    //     false in the only instantiation that exists.
    //
    // Now: one mask PER LANE, each strided by KEEP_WIDTH = symbols per beat.
    // This is what makes lane_management.sv:413's source index expressible at
    // all: the tuser lane stride is USER_WIDTH, and without (b) there is no
    // coherent bit position for lane l's mask to live at.
    logic [MAX_NUM_LANES-1:0][(KEEP_WIDTH*8)-1:0] special_k;
    pcie_tsos_t [MAX_NUM_LANES-1:0] ordered_set;
    pcie_tsos_t                     temp_ordered_set;
    logic                           os_sent;
    logic [31:0]                    skp_cnt;
    gen_os_struct_t                 gen_os_ctrl;

  } os_gen_t;

  os_gen_t Q, D;

  // pcie_tsos_t        [             MAX_NUM_LANES-1:0] ordered_set_i;


  //! main sequential block
  always_ff @(posedge clk_i) begin : main_seq
    if (rst_i) begin
      Q <= '{
          state: ST_IDLE,
          ordered_set: pcie_tsos_t'('0),
          temp_ordered_set: pcie_tsos_t'('0),
          gen_os_ctrl: gen_os_struct_t'(00),
          default: 'd0
      };
      // curr_state     <= ST_IDLE;
      // Q.ordered_set  <= '0;
      // os_sent_o      <= '0;
      // Q.axis_pkt_cnt <= '0;
      // Q.os_pkt_cnt   <= '0;
      // Q.special_k    <= '0;
    end else begin
      Q <= D;
      // curr_state     <= D.state;
      // Q.ordered_set  <= D.ordered_set;
      // os_sent_o      <= D.os_sent;
      // Q.axis_pkt_cnt <= D.axis_pkt_cnt;
      // Q.os_pkt_cnt   <= os_pkt_cnt_c;
      // Q.special_k    <= D.special_k;
    end
    //non-resetable
  end

  assign os_sent_o = D.os_sent;

  always_comb begin : send_ordered_set
    pcie_tsos_t temp_os;
    D                 = Q;
    // D.axis_pkt_cnt    = Q.axis_pkt_cnt;
    // os_pkt_cnt_c      = Q.os_pkt_cnt;
    //axis signals
    ltssm_axis_tdata  = '0;
    ltssm_axis_tkeep  = '0;
    ltssm_axis_tvalid = '0;
    ltssm_axis_tlast  = '0;
    ltssm_axis_tuser  = '0;
    // ordered_set_tx_in_process_c = ordered_set_tx_in_process_r;
    // D.state        = curr_state;
    //ordered set
    // D.ordered_set     = Q.ordered_set;
    D.os_sent         = '0;
    temp_os           = Q.ordered_set;


    if (link_up_i) begin
      D.skp_cnt = Q.skp_cnt + 1;
    end


    // D.special_k       = Q.special_k;
    case (Q.state)
      ST_IDLE: begin
        if (gen_os_ctrl_i.valid) begin
          D.skp_cnt = '0;
          for (int i = 0; i < MAX_NUM_LANES; i++) begin
            D.ordered_set[i] = ordered_set_i[i];
          end
          D.temp_ordered_set = ordered_set_i[0];
          // D.ordered_set = ordered_set_i;
          D.axis_pkt_cnt     = '0;
          D.gen_os_ctrl      = gen_os_ctrl_i;
          D.state            = ST_BUILD;
        end
        // SKP scheduling interval.  Base 2.1 sec 4.2.7.1 p.261: "The SKP Ordered
        // Set shall be scheduled for insertion at an interval between 1180 and
        // 1538 Symbol Times."  0xB0 = 176 counts scheduled one every 354, which
        // is 3.3x too often -- every SKP costs four Symbol Times of Link
        // bandwidth, and sec 4.2.7.2 p.261 only obliges a Receiver to tolerate
        // an AVERAGE inside that window.
        //
        // The constant is solved from a MEASURED relation, not a derived one.
        // The bench printed eight consecutive intervals of 354 Symbol Times at
        // 0xB0, so:
        //
        //     interval = 2N + 2      N counts of pipe_rx_usr_clk_i
        //                            2  Symbol Times per clock (PipeWidthGen1
        //                               = 16 bits, lane_management.sv:45)
        //                            +2 for ST_SKP's own cycle before the FSM
        //                               returns here
        //
        //     require  2N + 2 in [1180, 1538]  ->  N in [589, 768] = [0x24D, 0x300]
        //     centre   (1180+1538)/2 = 1359    ->  N = 678 = 0x2A6 -> 1358
        //
        // ⚠️ 0x2A6 is the window CENTRE on purpose, not an endpoint: the 2N+2
        // relation rests on one measurement, so 178 Symbol Times of margin below
        // and 180 above is worth more than a rounder constant.  A first pass
        // derived 2N (352) and doubted the register's 354; the register was
        // right and the derivation was two short -- which is exactly why the
        // constant is solved from the artifact.
        if (Q.skp_cnt >= SkpIntervalCounts) begin
          D.skp_cnt = '0;
          D.state   = ST_SKP;
        end
      end
      ST_SKP: begin
        if (ltssm_axis_tready) begin
          ltssm_axis_tdata = 32'h1c1c1cbc;
          ltssm_axis_tuser = '1;
          ltssm_axis_tkeep = '1;
          ltssm_axis_tvalid = '1;
          ltssm_axis_tlast = '1;
          D.state = ST_IDLE;
        end
      end
      ST_BUILD: begin
        D.os_pkt_cnt   = 32'd3;
        D.special_k    = '0;
        // Symbol 0 is COM on every Lane -- Base 2.1 sec 4.2.2 p.194, "a full
        // Ordered Set appears simultaneously on all Lanes of a multi-Lane Link".
        // Per-lane now that the mask is per-lane (E5).
        for (int i = 0; i < MAX_NUM_LANES; i++) begin
          D.special_k[i][0] = '1;
        end
        D.axis_pkt_cnt = '0;
        if ((gen_os_ctrl_i.gen_ts1 || gen_os_ctrl_i.gen_ts2)) begin
          for (int i = 0; i < MAX_NUM_LANES; i++) begin
            // E1 -- Symbol 1, the Link Number.  WAS D.special_k[1], one bit for
            // the whole Link, so this loop OR-ed the PAD-ness of every Lane
            // together.  A single PAD anywhere then marked EVERY Lane's real
            // Link Number as a control code -- and PAD-on-some-Lanes is the
            // NORMAL state throughout Configuration, so this was the worse of
            // the two reductions: it corrupted the MAJORITY (measured 3 of 4
            // Lanes), where the Symbol-2 lane-0 read corrupts the minority.
            // A receiver decoding Lane 0 saw a K where a D Link Number belongs,
            // so the Link Number it must match in Configuration.Linkwidth.Accept
            // never arrived.
            if (Q.ordered_set[i].link_num == PAD_) begin
              D.special_k[i][1] = '1;
            end

            // E2 -- Symbol 2, the Lane Number.  WAS a separate check further
            // down reading Q.ordered_set[0].lane_num ONLY, so Lane 2's genuine
            // PAD was transmitted as a D symbol and a receiver could not tell an
            // unassigned Lane from one claiming Lane Number 23 (measured 1 of 4
            // Lanes).  Folded into this loop because it is the same rule at a
            // different Symbol: K iff THAT Lane's byte is PAD.  Base 2.1
            // Table 4-2 p.201; Base 3.0's TS1 table agrees and spells it out
            // ("0-31, PAD.  PAD is encoded as K23.7").
            //
            // Rung 8 chose the lane-0 read DELIBERATELY, because ORing -- the
            // shape Symbol 1 used -- would have been worse, and left a TODO(x4)
            // saying a genuinely per-lane mask needs the tuser packing and the
            // lane_management broadcast changed together.  This bundle is that
            // change; both reductions are gone.
            if (Q.ordered_set[i].lane_num == PAD_) begin
              D.special_k[i][2] = '1;
            end

            // if (Q.ordered_set[i].ts_s6.ts1.ec != '0) begin
            //   D.ordered_set[i].ts_s6.ts1.trans_preset =
            //   preset_i[i].lane_equal_reg.downstream_tx_preset;
            // end
          end

          // The Symbol-2 check that used to sit here read Q.ordered_set[0]
          // ONLY.  It moved INTO the per-lane loop above (E2) -- see the comment
          // there for why Rung 8 chose lane 0 and why this bundle supersedes it.
          // Rung 8's own TODO(x4) named exactly this change as the condition.
        end

        if (gen_os_ctrl_i.gen_idle) begin
          D.special_k = '0;
          // os_pkt_cnt_c = 32'd1;
        end

        if (gen_os_ctrl_i.gen_eios) begin
          D.special_k = '1;
        end
        D.state = ST_SEND;
      end
      ST_SEND: begin
        //packet accepted or empty
        if (ltssm_axis_tready) begin
          //increment packet count
          D.axis_pkt_cnt = Q.axis_pkt_cnt + 1;
          //build axis packet
          for (int i = 0; i < MAX_NUM_LANES; i++) begin
            ltssm_axis_tdata[32*i+:32] = Q.ordered_set[i][32*Q.axis_pkt_cnt+:32];
          end
          // E3 -- emit a mask slice PER LANE.  WAS one USER_WIDTH-wide value
          // assigned to a (USER_WIDTH*MAX_NUM_LANES)-wide bus, which
          // zero-extended: Lanes 1..N-1's slices were never written at all, so
          // there was no per-lane mask for lane_management to read even in
          // principle.  tuser is packed lane-major exactly as tdata is on the
          // line above -- lane l at [USER_WIDTH*l +: USER_WIDTH].
          //
          // Only KEEP_WIDTH bits are written per Lane because a beat carries
          // KEEP_WIDTH = DATA_WIDTH/8 Symbols; the assignment to '0 first leaves
          // the remaining bits of each slice EXPLICITLY zero rather than leaving
          // a phantom Symbol position to inference (E5(b)).
          ltssm_axis_tuser = '0;
          for (int i = 0; i < MAX_NUM_LANES; i++) begin
            ltssm_axis_tuser[USER_WIDTH*i+:KEEP_WIDTH] =
                Q.special_k[i][KEEP_WIDTH*Q.axis_pkt_cnt+:KEEP_WIDTH];
          end
          ltssm_axis_tkeep  = '1;
          ltssm_axis_tvalid = '1;
          ltssm_axis_tlast  = '0;
          if (Q.axis_pkt_cnt >= Q.os_pkt_cnt) begin
            // §54 #9(A) -- A PENDING SKP WINS THIS BOUNDARY.
            //
            // Base 2.1 §4.2.7.1 p.261: "Scheduled SKP Ordered Sets shall be
            // transmitted if a packet or Ordered Set is not already in progress,
            // otherwise they are accumulated and then inserted consecutively at
            // the next packet or Ordered Set boundary."  The second clause had
            // no implementation.  skp_cnt is tested only in ST_IDLE, and the
            // streaming lock below keeps the FSM out of ST_IDLE for as long as
            // the LTSSM holds a steady command -- so during continuous training
            // the state that could schedule a SKP was never visited.  Measured:
            // 206 Ordered Sets and ZERO SKPs over 3332 Symbol Times, against a
            // spec window that closes at 1538.  Total starvation, not a slow
            // timer: with no Ordered Set requested the same DUT emits on a
            // perfect 1358-Symbol-Time cadence.
            //
            // ⚠️ THIS TEST IS AT THE BOUNDARY ON PURPOSE.  It sits inside
            // `Q.axis_pkt_cnt >= Q.os_pkt_cnt`, where tlast has been asserted and
            // os_sent raised, so THE ORDERED SET IN FLIGHT ALWAYS COMPLETES and
            // only the next one is delayed.  Emitting from inside ST_SEND
            // without this guard is the "obvious" one-line version and it is
            // forbidden by the same spec sentence -- four foreign Symbols inside
            // a TS make it unrecognisable to the receiver's 16-Symbol matcher.
            // skp_does_not_interrupt_an_ordered_set is the row that says so, and
            // mutant ME (divert without the boundary test) reddens it.
            //
            // The GTP/GTX streaming lock is PRESERVED, not removed: it still
            // governs every boundary at which no SKP is due, which is all but
            // one in 678.  What changes is that it no longer wins unconditionally
            // against a spec-mandated insertion point.
            if (Q.skp_cnt >= SkpIntervalCounts) begin
              D.skp_cnt = '0;
              D.state   = ST_SKP;
            end
            //this hack allows for streamin uninterrupted ordered sets
            //required by the GTP/GTX transievers
            else if (Q.gen_os_ctrl == gen_os_ctrl_i && !send_ltssm_os_i
            && (ordered_set_i[0] == Q.temp_ordered_set)) begin

            end else begin
              D.state = ST_IDLE;
            end
            //assert last
            ltssm_axis_tlast = '1;
            D.os_sent        = '1;
            D.axis_pkt_cnt   = '0;
          end

        end
      end
      default: begin
      end
    endcase

  end


  //axi-stream output register instance
  axis_register #(
      .DATA_WIDTH(DATA_WIDTH * MAX_NUM_LANES),
      .KEEP_ENABLE('1),
      .KEEP_WIDTH(KEEP_WIDTH * MAX_NUM_LANES),
      .LAST_ENABLE('1),
      .ID_ENABLE('0),
      .ID_WIDTH(1),
      .DEST_ENABLE('0),
      .DEST_WIDTH(1),
      .USER_ENABLE('1),
      .USER_WIDTH(USER_WIDTH * MAX_NUM_LANES),
      .REG_TYPE(SkidBuffer)
  ) axis_register_inst (
      .clk          (clk_i),
      .rst          (rst_i),
      .s_axis_tdata (ltssm_axis_tdata),
      .s_axis_tkeep (ltssm_axis_tkeep),
      .s_axis_tvalid(ltssm_axis_tvalid),
      .s_axis_tready(ltssm_axis_tready),
      .s_axis_tlast (ltssm_axis_tlast),
      .s_axis_tuser (ltssm_axis_tuser),
      .s_axis_tid   ('0),
      .s_axis_tdest ('0),
      .m_axis_tdata (m_axis_tdata),
      .m_axis_tkeep (m_axis_tkeep),
      .m_axis_tvalid(m_axis_tvalid),
      .m_axis_tready(m_axis_tready),
      .m_axis_tlast (m_axis_tlast),
      .m_axis_tuser (m_axis_tuser),
      .m_axis_tid   (),
      .m_axis_tdest ()
  );

  // assign os_sent_o = os_sent_r;



endmodule
