// Micro-Doppler engine: continuous range-gated, beamformed slow-time samples for up to NTGT cued targets.
//
// For target t (delay tau samples, weights w_c Q1.15, enabled):
//   b[n] = round( sum_c s_c[n] * conj(w_c) / 2^15 )
//   z[n] = b[n] * conj(r[n - tau])
//   Y[m] = sat32( round( sum_{n in block m} z[n] / 2^out_shift ) ),  block = 2^block_log2 samples
// Y[m] is the CAF value of the target's range cell and beam for block m; its sequence (rate fs / 2^block_log2,
// e.g. 3.9 kHz at 8 MS/s) carries the body Doppler line plus the rotor / wing-beat micro-Doppler, with no gaps.
//
// Targets are processed one per clock after each in_valid, so in_valid must be >= NTGT clocks apart.
// Parameters are written to a shadow set (prm_we) and copied to the active set at the first sample of the next
// block after commit. Bit-true model: firmware/model/fixedpoint.py md_engine().
`default_nettype none
module md_engine #(
    parameter NCH        = 4,
    parameter NTGT       = 8,
    parameter DEPTH_LOG2 = 12            // reference delay line: max tau = 2^DEPTH_LOG2 - 1
) (
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 in_valid,
    input  wire signed [15:0]   ref_i,
    input  wire signed [15:0]   ref_q,
    input  wire [NCH*16-1:0]    s_i,
    input  wire [NCH*16-1:0]    s_q,
    // configuration
    input  wire [3:0]           block_log2,   // 4..15 (change only with all targets disabled)
    input  wire [4:0]           out_shift,
    input  wire                 prm_we,
    input  wire [7:0]           prm_tgt,
    input  wire [7:0]           prm_sel,      // 0: {en, .., tau}; 1+c: {w_i[15:0], w_q[15:0]} of channel c
    input  wire [31:0]          prm_data,
    input  wire                 commit,
    output reg                  overrun,
    // slow-time samples
    output reg                  out_valid,
    output reg  [7:0]           out_tgt,
    output reg  [31:0]          out_blk,
    output reg  signed [31:0]   out_i,
    output reg  signed [31:0]   out_q
);
    localparam TW = (NTGT > 1) ? $clog2(NTGT) : 1;

    // ---------------------------------------------------------------- parameters (shadow / active)
    reg [DEPTH_LOG2-1:0] tau_s [0:NTGT-1], tau_a [0:NTGT-1];
    reg                  en_s  [0:NTGT-1], en_a  [0:NTGT-1];
    reg signed [15:0]    wi_s  [0:NTGT*NCH-1], wi_a [0:NTGT*NCH-1];
    reg signed [15:0]    wq_s  [0:NTGT*NCH-1], wq_a [0:NTGT*NCH-1];
    reg                  pend;
    integer k;

    always @(posedge clk)
        if (prm_we && prm_tgt < NTGT) begin
            if (prm_sel == 0) begin
                tau_s[prm_tgt] <= prm_data[DEPTH_LOG2-1:0];
                en_s[prm_tgt]  <= prm_data[31];
            end else if (prm_sel <= NCH) begin
                wi_s[prm_tgt * NCH + prm_sel - 1] <= prm_data[31:16];
                wq_s[prm_tgt * NCH + prm_sel - 1] <= prm_data[15:0];
            end
        end

    // ---------------------------------------------------------------- reference delay line
    reg [31:0]           ram [0:(1<<DEPTH_LOG2)-1];
    reg [DEPTH_LOG2-1:0] wr_ptr;
    integer i0, i1, i2, i3;
    initial for (i0 = 0; i0 < (1 << DEPTH_LOG2); i0 = i0 + 1) ram[i0] = 0;
    initial for (i1 = 0; i1 < NTGT; i1 = i1 + 1) begin tau_s[i1] = 0; tau_a[i1] = 0; en_s[i1] = 0; en_a[i1] = 0; end
    initial for (i2 = 0; i2 < NTGT * NCH; i2 = i2 + 1) begin wi_s[i2] = 0; wq_s[i2] = 0; wi_a[i2] = 0; wq_a[i2] = 0; end

    // ---------------------------------------------------------------- sample bookkeeping
    reg [15:0]       scnt;               // sample index inside the block
    reg [31:0]       blk;                // block index
    reg [NCH*16-1:0] s_i_l, s_q_l;
    reg [DEPTH_LOG2-1:0] base;           // address of the current sample
    reg              last_l;             // current sample is the last of its block
    reg [31:0]       blk_l;
    reg              iter;
    reg [TW-1:0]     t0;
    wire [15:0]      bmask = (16'd1 << block_log2) - 16'd1;

    always @(posedge clk) begin
        if (rst) begin
            wr_ptr <= 0; scnt <= 0; blk <= 0; iter <= 1'b0; t0 <= 0; pend <= 1'b0; overrun <= 1'b0;
        end else begin
            if (commit) pend <= 1'b1;
            if (in_valid) begin
                if (iter) overrun <= 1'b1;
                ram[wr_ptr] <= {ref_i, ref_q};
                base   <= wr_ptr;
                wr_ptr <= wr_ptr + 1'b1;
                s_i_l  <= s_i;
                s_q_l  <= s_q;
                last_l <= ((scnt & bmask) == bmask);
                blk_l  <= blk;
                if ((scnt & bmask) == 0 && (pend || commit)) begin
                    for (k = 0; k < NTGT; k = k + 1) begin tau_a[k] <= tau_s[k]; en_a[k] <= en_s[k]; end
                    for (k = 0; k < NTGT * NCH; k = k + 1) begin wi_a[k] <= wi_s[k]; wq_a[k] <= wq_s[k]; end
                    pend <= 1'b0;
                end
                if ((scnt & bmask) == bmask) begin
                    scnt <= 0;
                    blk  <= blk + 1'b1;
                end else
                    scnt <= scnt + 1'b1;
                iter <= 1'b1;
                t0   <= 0;
            end else if (iter) begin
                if (t0 == NTGT - 1) iter <= 1'b0;
                else t0 <= t0 + 1'b1;
            end
        end
    end

    // ---------------------------------------------------------------- stage 1: beamform, read delayed reference
    reg signed [36:0] bf_i, bf_q;
    reg [31:0]        rd;
    reg               v1, last1, en1;
    reg [TW-1:0]      t1;
    reg [31:0]        blk1;
    reg signed [36:0] acc_bi, acc_bq;
    integer c;
    always @(*) begin
        acc_bi = 0; acc_bq = 0;
        for (c = 0; c < NCH; c = c + 1) begin
            // s * conj(w) = (si wi + sq wq) + j (sq wi - si wq)
            acc_bi = acc_bi + $signed(s_i_l[c*16 +: 16]) * wi_a[t0 * NCH + c] + $signed(s_q_l[c*16 +: 16]) * wq_a[t0 * NCH + c];
            acc_bq = acc_bq + $signed(s_q_l[c*16 +: 16]) * wi_a[t0 * NCH + c] - $signed(s_i_l[c*16 +: 16]) * wq_a[t0 * NCH + c];
        end
    end
    always @(posedge clk) begin
        v1 <= iter && !rst;
        if (iter) begin
            bf_i  <= acc_bi;
            bf_q  <= acc_bq;
            rd    <= ram[base - tau_a[t0]];
            t1    <= t0;
            last1 <= last_l;
            en1   <= en_a[t0];
            blk1  <= blk_l;
        end
    end

    // ---------------------------------------------------------------- stage 2: b = round(bf / 2^15), z = b * conj(r)
    wire signed [36:0] b_i = (bf_i + 37'sd16384) >>> 15;
    wire signed [36:0] b_q = (bf_q + 37'sd16384) >>> 15;
    wire signed [15:0] r_i = rd[31:16];
    wire signed [15:0] r_q = rd[15:0];
    reg signed [55:0] z_i, z_q;
    reg               v2, last2, en2;
    reg [TW-1:0]      t2;
    reg [31:0]        blk2;
    always @(posedge clk) begin
        v2 <= v1 && !rst;
        // b * conj(r) = (bi ri + bq rq) + j (bq ri - bi rq)
        z_i   <= b_i * r_i + b_q * r_q;
        z_q   <= b_q * r_i - b_i * r_q;
        t2    <= t1;
        last2 <= last1;
        en2   <= en1;
        blk2  <= blk1;
    end

    // ---------------------------------------------------------------- stage 3: accumulate over the block
    reg signed [55:0] acc_i [0:NTGT-1];
    reg signed [55:0] acc_q [0:NTGT-1];
    initial for (i3 = 0; i3 < NTGT; i3 = i3 + 1) begin acc_i[i3] = 0; acc_q[i3] = 0; end
    integer kr;
    wire signed [55:0] tot_i = acc_i[t2] + z_i;
    wire signed [55:0] tot_q = acc_q[t2] + z_q;
    wire signed [55:0] sh_i = (out_shift == 0) ? tot_i : (tot_i + (56'sd1 <<< (out_shift - 1))) >>> out_shift;
    wire signed [55:0] sh_q = (out_shift == 0) ? tot_q : (tot_q + (56'sd1 <<< (out_shift - 1))) >>> out_shift;
    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (rst) begin
            for (kr = 0; kr < NTGT; kr = kr + 1) begin acc_i[kr] <= 0; acc_q[kr] <= 0; end
        end else if (v2) begin
            if (last2) begin
                acc_i[t2] <= 0;
                acc_q[t2] <= 0;
                if (en2) begin
                    out_valid <= 1'b1;
                    out_tgt   <= t2;
                    out_blk   <= blk2;
                    out_i     <= (sh_i > 56'sd2147483647) ? 32'sh7fffffff : (sh_i < -56'sd2147483648) ? 32'sh80000000 : sh_i[31:0];
                    out_q     <= (sh_q > 56'sd2147483647) ? 32'sh7fffffff : (sh_q < -56'sd2147483648) ? 32'sh80000000 : sh_q[31:0];
                end
            end else begin
                acc_i[t2] <= tot_i;
                acc_q[t2] <= tot_q;
            end
        end
    end
endmodule
`default_nettype wire
