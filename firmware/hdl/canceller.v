// Direct-signal canceller: per surveillance channel, subtract a complex FIR of the reference.
//
//   y_c[n] = sat16( s_c[n] - round( sum_{k<NTAPS} h_c[k] r[n-k] / 2^16 ) )
//
// Taps are complex Q2.16 (18 bit). NCH channels share one reference delay line. Each channel has P parallel
// complex multipliers, so a sample takes C = NTAPS/P clocks: in_valid must be at least C+2 clocks apart
// (Board C: 200 MHz / 8 MS/s = 25 clocks, NTAPS 128, P 8 -> C = 16).
// Tap memories are double banked: the host writes the idle bank (tap_we), sets commit, and the banks swap on
// the next in_valid with cpi_start, so the taps never change inside a CPI.
// Bit-true model: firmware/model/fixedpoint.py canceller().
`default_nettype none
module canceller #(
    parameter NTAPS = 128,
    parameter NCH   = 4,
    parameter P     = 8
) (
    input  wire                 clk,
    input  wire                 rst,
    // samples
    input  wire                 in_valid,
    input  wire                 cpi_start,          // with in_valid: first sample of a CPI
    input  wire signed [15:0]   ref_i,
    input  wire signed [15:0]   ref_q,
    input  wire [NCH*16-1:0]    s_i,                // channel c at [c*16 +: 16]
    input  wire [NCH*16-1:0]    s_q,
    // tap loading (idle bank)
    input  wire                 tap_we,
    input  wire [7:0]           tap_ch,
    input  wire [15:0]          tap_idx,
    input  wire signed [17:0]   tap_i,
    input  wire signed [17:0]   tap_q,
    input  wire                 commit,             // pulse: swap banks at the next CPI start
    output reg                  bank,               // active bank
    output reg                  overrun,            // sticky: in_valid arrived while busy
    // results
    output reg                  out_valid,
    output reg  signed [15:0]   ref_out_i,          // reference aligned with y
    output reg  signed [15:0]   ref_out_q,
    output reg  [NCH*16-1:0]    y_i,
    output reg  [NCH*16-1:0]    y_q
);
    localparam C  = NTAPS / P;
    localparam CW = (C > 1) ? $clog2(C) : 1;

    // reference history: rh[k] = r[n-k] after the shift for sample n
    reg signed [15:0] rh_i [0:NTAPS-1];
    reg signed [15:0] rh_q [0:NTAPS-1];
    reg [NCH*16-1:0]  s_i_l, s_q_l;
    reg               busy, finish, pend;
    reg [CW-1:0]      cyc;
    integer k;

    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0; finish <= 1'b0; cyc <= 0; bank <= 1'b0; pend <= 1'b0; overrun <= 1'b0;
        end else begin
            finish <= 1'b0;
            if (commit) pend <= 1'b1;
            if (in_valid) begin
                if (busy || finish) overrun <= 1'b1;
                for (k = NTAPS - 1; k > 0; k = k - 1) begin
                    rh_i[k] <= rh_i[k - 1];
                    rh_q[k] <= rh_q[k - 1];
                end
                rh_i[0] <= ref_i;
                rh_q[0] <= ref_q;
                s_i_l <= s_i;
                s_q_l <= s_q;
                if (cpi_start && (pend || commit)) begin
                    bank <= ~bank;
                    pend <= 1'b0;
                end
                busy <= 1'b1;
                cyc  <= 0;
            end else if (busy) begin
                if (cyc == C - 1) begin
                    busy   <= 1'b0;
                    finish <= 1'b1;
                end else
                    cyc <= cyc + 1'b1;
            end
        end
    end

    integer ki;
    initial begin
        for (ki = 0; ki < NTAPS; ki = ki + 1) begin rh_i[ki] = 0; rh_q[ki] = 0; end
    end

    genvar c, p;
    generate
        for (c = 0; c < NCH; c = c + 1) begin : ch
            // per-lane tap memories: lane p holds taps k = j*P + p, j = 0..C-1, two banks
            wire signed [47:0] lane_i [0:P-1];
            wire signed [47:0] lane_q [0:P-1];
            for (p = 0; p < P; p = p + 1) begin : lane
                reg signed [17:0] ti [0:2*C-1];
                reg signed [17:0] tq [0:2*C-1];
                integer j;
                initial for (j = 0; j < 2 * C; j = j + 1) begin ti[j] = 0; tq[j] = 0; end
                always @(posedge clk)
                    if (tap_we && tap_ch == c && (tap_idx % P) == p) begin
                        ti[{~bank, tap_idx[CW+$clog2(P)-1:$clog2(P)]}] <= tap_i;
                        tq[{~bank, tap_idx[CW+$clog2(P)-1:$clog2(P)]}] <= tap_q;
                    end
                wire signed [17:0] hi = ti[{bank, cyc}];
                wire signed [17:0] hq = tq[{bank, cyc}];
                wire signed [15:0] xi = rh_i[cyc * P + p];
                wire signed [15:0] xq = rh_q[cyc * P + p];
                // h * r = (hi xi - hq xq) + j (hi xq + hq xi)
                assign lane_i[p] = hi * xi - hq * xq;
                assign lane_q[p] = hi * xq + hq * xi;
            end

            reg signed [47:0] acc_i, acc_q;
            reg signed [47:0] sum_i, sum_q;
            integer q;
            always @(*) begin
                sum_i = 0; sum_q = 0;
                for (q = 0; q < P; q = q + 1) begin
                    sum_i = sum_i + lane_i[q];
                    sum_q = sum_q + lane_q[q];
                end
            end
            // rounding subtraction and saturation
            wire signed [47:0] est_i = (acc_i + 48'sd32768) >>> 16;
            wire signed [47:0] est_q = (acc_q + 48'sd32768) >>> 16;
            wire signed [47:0] d_i = $signed(s_i_l[c*16 +: 16]) - est_i;
            wire signed [47:0] d_q = $signed(s_q_l[c*16 +: 16]) - est_q;
            wire [15:0] sat_i = (d_i > 48'sd32767) ? 16'sh7fff : (d_i < -48'sd32768) ? 16'sh8000 : d_i[15:0];
            wire [15:0] sat_q = (d_q > 48'sd32767) ? 16'sh7fff : (d_q < -48'sd32768) ? 16'sh8000 : d_q[15:0];

            always @(posedge clk) begin
                if (in_valid) begin
                    acc_i <= 0; acc_q <= 0;
                end else if (busy) begin
                    acc_i <= acc_i + sum_i;
                    acc_q <= acc_q + sum_q;
                end
                if (finish) begin
                    y_i[c*16 +: 16] <= sat_i;
                    y_q[c*16 +: 16] <= sat_q;
                end
            end
        end
    endgenerate

    always @(posedge clk) begin
        out_valid <= finish;
        if (finish) begin
            ref_out_i <= rh_i[0];
            ref_out_q <= rh_q[0];
        end
    end
endmodule
`default_nettype wire
