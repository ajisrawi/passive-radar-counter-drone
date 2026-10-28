// Passive-radar PL core (shared by Board C / XC7Z020 and Board C2 / XC7Z035).
//
//   aligned samples (ref + 4 surveillance, 16-bit I/Q, one in_valid per sample)
//     -> canceller (direct signal / clutter, host taps)  -> stream_pack (12/8-bit) -> AXI-Stream to DMA / UDP
//                                                         -> md_engine (cued targets) -> FIFO -> AXI-Lite (ARM)
//
// AXI4-Lite register map (byte offsets):
//   0x000 ID           RO  0x50434C01 ("PCL", version 1)
//   0x004 CTRL         RW  bit0 stream enable, bit1 canceller commit (W1P), bit2 md commit (W1P)
//   0x008 CPI_LEN      RW  samples per CPI (canceller taps swap only on CPI boundaries)
//   0x00C SHIFTS       RW  [3:0] surveillance requant shift, [7:4] reference requant shift
//   0x010 MD_CFG       RW  [3:0] block_log2, [12:8] out_shift
//   0x014 STATUS       RO  bit0 canceller overrun, bit1 md overrun, bit2 stream overflow, bit3 md fifo overflow,
//                          bit4 active tap bank
//   0x018 SAMPLE_LO    RO  sample counter (latched into SAMPLE_HI on read of LO)
//   0x01C SAMPLE_HI    RO
//   0x020 PPS_LO       RO  sample counter at the last PPS rising edge
//   0x024 PPS_HI       RO
//   0x028 REF_SEL      RW  bit0: reference channel CH5 instead of CH0 (stack B node), drives ad_merge
//   0x040 TAP_ADDR     RW  [23:16] channel, [15:0] tap index
//   0x044 TAP_I        RW  Q2.16 (18-bit signed)
//   0x048 TAP_Q        WO  writing TAP_Q stores the tap into the idle bank
//   0x080 MD_WR        RO  slow-time records written so far (32-bit count)
//   0x084 MD_RD        RW  records consumed by software (write back after reading; used for overflow detection)
//   0x100 + 4*(8*t + sel)  WO  md target t parameters (sel 0: {en, tau}; sel 1..4: {w_i, w_q} of channel sel-1)
//   0x800-0xFFF  MD ring RO  record r (r = count mod 2^RING_LOG2) at 0x800 + 16 r:
//                           +0 {tgt[7:0], blk[23:0]}, +4 I, +8 Q, +C blk[31:0]
//                 Software copies [MD_RD, MD_WR) in one memcpy from the mapped window (no per-record pops).
`default_nettype none
module pcl_core #(
    parameter NCH        = 4,
    parameter NTAPS      = 128,
    parameter P          = 8,
    parameter NTGT       = 8,
    parameter DEPTH_LOG2 = 12,
    parameter RING_LOG2  = 7          // 128 records = the 2 KB window 0x800-0xFFF
) (
    input  wire                 clk,
    input  wire                 rst,
    // aligned samples from the AD9361 front ends
    input  wire                 in_valid,
    input  wire signed [15:0]   ref_i,
    input  wire signed [15:0]   ref_q,
    input  wire [NCH*16-1:0]    s_i,
    input  wire [NCH*16-1:0]    s_q,
    input  wire                 pps,
    // AXI-Stream to DMA / UDP engine
    output wire                 m_axis_tvalid,
    output wire [63:0]          m_axis_tdata,
    output wire                 m_axis_tlast,
    input  wire                 m_axis_tready,
    // AXI4-Lite slave
    input  wire [11:0]          s_axil_awaddr,
    input  wire                 s_axil_awvalid,
    output reg                  s_axil_awready,
    input  wire [31:0]          s_axil_wdata,
    input  wire                 s_axil_wvalid,
    output reg                  s_axil_wready,
    output reg  [1:0]           s_axil_bresp,
    output reg                  s_axil_bvalid,
    input  wire                 s_axil_bready,
    input  wire [11:0]          s_axil_araddr,
    input  wire                 s_axil_arvalid,
    output reg                  s_axil_arready,
    output reg  [31:0]          s_axil_rdata,
    output reg  [1:0]           s_axil_rresp,
    output reg                  s_axil_rvalid,
    input  wire                 s_axil_rready,
    output wire                 md_irq,               // md ring not empty
    output reg                  ref_sel
);
    // ---------------------------------------------------------------- registers
    reg        en, canc_commit, md_commit;
    reg [31:0] cpi_len;
    reg [3:0]  sv_shift, ref_shift;
    reg [3:0]  block_log2;
    reg [4:0]  out_shift;
    reg [23:0] tap_ch_idx;
    reg signed [17:0] tap_i_r;
    reg        tap_we;
    reg signed [17:0] tap_q_r;
    reg        prm_we;
    reg [7:0]  prm_tgt, prm_sel;
    reg [31:0] prm_data;

    // ---------------------------------------------------------------- sample counter, CPI, PPS
    reg [63:0] scnt, pps_cnt;
    reg [31:0] cpi_cnt;
    reg        pps_d;
    wire       cpi_start = (cpi_cnt == 0);
    always @(posedge clk) begin
        if (rst) begin
            scnt <= 0; cpi_cnt <= 0; pps_d <= 1'b0; pps_cnt <= 0;
        end else begin
            pps_d <= pps;
            if (pps && !pps_d) pps_cnt <= scnt;
            if (in_valid) begin
                scnt    <= scnt + 1'b1;
                cpi_cnt <= (cpi_cnt + 1 >= cpi_len) ? 32'd0 : cpi_cnt + 1'b1;
            end
        end
    end

    // ---------------------------------------------------------------- datapath
    wire               c_valid, c_bank, c_ovr;
    wire signed [15:0] c_ri, c_rq;
    wire [NCH*16-1:0]  c_yi, c_yq;
    canceller #(.NTAPS(NTAPS), .NCH(NCH), .P(P)) u_canc (
        .clk(clk), .rst(rst), .in_valid(in_valid), .cpi_start(cpi_start), .ref_i(ref_i), .ref_q(ref_q),
        .s_i(s_i), .s_q(s_q), .tap_we(tap_we), .tap_ch(tap_ch_idx[23:16]), .tap_idx(tap_ch_idx[15:0]),
        .tap_i(tap_i_r), .tap_q(tap_q_r), .commit(canc_commit), .bank(c_bank), .overrun(c_ovr),
        .out_valid(c_valid), .ref_out_i(c_ri), .ref_out_q(c_rq), .y_i(c_yi), .y_q(c_yq));

    wire s_ovf;
    stream_pack #(.NCH(NCH), .REF_BITS(12), .SV_BITS(8)) u_pack (
        .clk(clk), .rst(rst | ~en), .in_valid(c_valid), .ref_i(c_ri), .ref_q(c_rq), .s_i(c_yi), .s_q(c_yq),
        .ref_shift(ref_shift), .sv_shift(sv_shift),
        .m_valid(m_axis_tvalid), .m_data(m_axis_tdata), .m_last(m_axis_tlast), .overflow(s_ovf), .m_ready(m_axis_tready));

    wire               md_v, md_ovr;
    wire [7:0]         md_t;
    wire [31:0]        md_b;
    wire signed [31:0] md_i, md_q;
    md_engine #(.NCH(NCH), .NTGT(NTGT), .DEPTH_LOG2(DEPTH_LOG2)) u_md (
        .clk(clk), .rst(rst), .in_valid(c_valid), .ref_i(c_ri), .ref_q(c_rq), .s_i(c_yi), .s_q(c_yq),
        .block_log2(block_log2), .out_shift(out_shift), .prm_we(prm_we), .prm_tgt(prm_tgt), .prm_sel(prm_sel),
        .prm_data(prm_data), .commit(md_commit), .overrun(md_ovr),
        .out_valid(md_v), .out_tgt(md_t), .out_blk(md_b), .out_i(md_i), .out_q(md_q));

    // ---------------------------------------------------------------- md ring (records: hdr, I, Q, blk)
    reg [31:0] r_hdr [0:(1<<RING_LOG2)-1];
    reg [31:0] r_i   [0:(1<<RING_LOG2)-1];
    reg [31:0] r_q   [0:(1<<RING_LOG2)-1];
    reg [31:0] r_blk [0:(1<<RING_LOG2)-1];
    reg [31:0] f_wr, f_rd;
    reg        f_ovf;
    assign md_irq = (f_wr != f_rd);
    always @(posedge clk) begin
        if (rst) begin
            f_wr <= 0; f_ovf <= 1'b0;
        end else if (md_v) begin
            if (f_wr - f_rd >= (1 << RING_LOG2)) f_ovf <= 1'b1;     // software fell behind: oldest record lost
            r_hdr[f_wr[RING_LOG2-1:0]] <= {md_t, md_b[23:0]};
            r_i[f_wr[RING_LOG2-1:0]]   <= md_i;
            r_q[f_wr[RING_LOG2-1:0]]   <= md_q;
            r_blk[f_wr[RING_LOG2-1:0]] <= md_b;
            f_wr <= f_wr + 1'b1;
        end
    end

    // ---------------------------------------------------------------- AXI4-Lite
    reg [11:0] awaddr_l;
    reg        aw_ok, w_ok;
    reg [31:0] wdata_l;
    reg [31:0] scnt_hi_l;
    always @(posedge clk) begin
        if (rst) begin
            s_axil_awready <= 1'b0; s_axil_wready <= 1'b0; s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            s_axil_arready <= 1'b0; s_axil_rvalid <= 1'b0; s_axil_rresp <= 2'b00;
            aw_ok <= 1'b0; w_ok <= 1'b0;
            en <= 1'b0; cpi_len <= 32'd2000000; sv_shift <= 4'd0; ref_shift <= 4'd0;
            block_log2 <= 4'd11; out_shift <= 5'd16; ref_sel <= 1'b0; canc_commit <= 1'b0; md_commit <= 1'b0;
            tap_we <= 1'b0; prm_we <= 1'b0; tap_ch_idx <= 0; f_rd <= 0;
        end else begin
            canc_commit <= 1'b0; md_commit <= 1'b0; tap_we <= 1'b0; prm_we <= 1'b0;
            // write: accept address and data independently, act when both are held
            s_axil_awready <= 1'b0; s_axil_wready <= 1'b0;
            if (s_axil_awvalid && !aw_ok && !s_axil_awready) begin awaddr_l <= s_axil_awaddr; aw_ok <= 1'b1; s_axil_awready <= 1'b1; end
            if (s_axil_wvalid && !w_ok && !s_axil_wready)   begin wdata_l <= s_axil_wdata;  w_ok  <= 1'b1; s_axil_wready  <= 1'b1; end
            if (aw_ok && w_ok && !s_axil_bvalid) begin
                aw_ok <= 1'b0; w_ok <= 1'b0; s_axil_bvalid <= 1'b1;
                case (awaddr_l)
                    12'h004: begin en <= wdata_l[0]; canc_commit <= wdata_l[1]; md_commit <= wdata_l[2]; end
                    12'h008: cpi_len <= wdata_l;
                    12'h00C: begin sv_shift <= wdata_l[3:0]; ref_shift <= wdata_l[7:4]; end
                    12'h010: begin block_log2 <= wdata_l[3:0]; out_shift <= wdata_l[12:8]; end
                    12'h028: ref_sel <= wdata_l[0];
                    12'h040: tap_ch_idx <= wdata_l[23:0];
                    12'h044: tap_i_r <= wdata_l[17:0];
                    12'h048: begin tap_q_r <= wdata_l[17:0]; tap_we <= 1'b1; end
                    12'h084: f_rd <= wdata_l;
                    default:
                        if (awaddr_l >= 12'h100 && awaddr_l < 12'h100 + 32 * NTGT) begin
                            prm_we   <= 1'b1;
                            prm_tgt  <= (awaddr_l - 12'h100) >> 5;
                            prm_sel  <= ((awaddr_l - 12'h100) >> 2) & 8'h7;
                            prm_data <= wdata_l;
                        end
                endcase
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;
            // read
            s_axil_arready <= 1'b0;
            if (s_axil_arvalid && !s_axil_rvalid && !s_axil_arready) begin
                s_axil_arready <= 1'b1;
                s_axil_rvalid  <= 1'b1;
                case (s_axil_araddr)
                    12'h000: s_axil_rdata <= 32'h50434C01;
                    12'h004: s_axil_rdata <= {31'd0, en};
                    12'h008: s_axil_rdata <= cpi_len;
                    12'h00C: s_axil_rdata <= {24'd0, ref_shift, sv_shift};
                    12'h010: s_axil_rdata <= {19'd0, out_shift, 4'd0, block_log2};
                    12'h014: s_axil_rdata <= {27'd0, c_bank, f_ovf, s_ovf, md_ovr, c_ovr};
                    12'h018: begin s_axil_rdata <= scnt[31:0]; scnt_hi_l <= scnt[63:32]; end
                    12'h01C: s_axil_rdata <= scnt_hi_l;
                    12'h020: s_axil_rdata <= pps_cnt[31:0];
                    12'h024: s_axil_rdata <= pps_cnt[63:32];
                    12'h028: s_axil_rdata <= {31'd0, ref_sel};
                    12'h040: s_axil_rdata <= {8'd0, tap_ch_idx};
                    12'h080: s_axil_rdata <= f_wr;
                    12'h084: s_axil_rdata <= f_rd;
                    default:
                        if (s_axil_araddr[11])                  // md ring window 0x800-0xFFF
                            case (s_axil_araddr[3:2])
                                2'd0: s_axil_rdata <= r_hdr[s_axil_araddr[RING_LOG2+3:4]];
                                2'd1: s_axil_rdata <= r_i[s_axil_araddr[RING_LOG2+3:4]];
                                2'd2: s_axil_rdata <= r_q[s_axil_araddr[RING_LOG2+3:4]];
                                default: s_axil_rdata <= r_blk[s_axil_araddr[RING_LOG2+3:4]];
                            endcase
                        else
                            s_axil_rdata <= 32'hDEADBEEF;
                endcase
            end
            if (s_axil_rvalid && s_axil_rready) s_axil_rvalid <= 1'b0;
        end
    end
endmodule
`default_nettype wire
