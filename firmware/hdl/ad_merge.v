// Merge the three AD9361 receive streams (one ADI axi_ad9361 core per chip, each in its own DATA_CLK domain)
// into one aligned sample for the processing clock: ref + 4 surveillance channels, 16-bit I/Q, one in_valid.
//
// Channel map (Board B): CH0 = AD1 RX1, CH1 = AD1 RX2, CH2/CH3 = AD2 RX1/RX2, CH4/CH5 = AD3 RX1/RX2.
//   ref_sel = 0: reference CH0, surveillance CH1..CH4 (stack A)
//   ref_sel = 1: reference CH5, surveillance CH1..CH4 (stack B: its transmitter's reference antenna on CH5)
// Each chip writes {i0, q0, i1, q1} into its async FIFO on adc_valid; the processing side pops all three FIFOs
// together when none is empty. The chips are started together after the AD9361 multi-chip sync, so the k-th
// word of each FIFO is the same sampling instant; a residual fixed skew is measured with the noise source.
`default_nettype none
module ad_merge (
    input  wire         rst,
    // chip k in its own clock domain
    input  wire [2:0]   adc_clk,
    input  wire [2:0]   adc_valid,
    input  wire [191:0] adc_data,          // chip k at [64k +: 64] = {i0, q0, i1, q1}
    // processing clock
    input  wire         clk,
    input  wire         ref_sel,
    output reg          out_valid,
    output reg  [15:0]  ref_i,
    output reg  [15:0]  ref_q,
    output reg  [63:0]  s_i,               // surveillance c at [16c +: 16]
    output reg  [63:0]  s_q,
    output wire [2:0]   fifo_overflow
);
    wire [63:0] q [0:2];
    wire [2:0]  empty;
    wire        pop = (empty == 3'b000);
    genvar k;
    generate
        for (k = 0; k < 3; k = k + 1) begin : chip
            async_fifo #(.W(64), .A(4)) u_fifo (
                .wrst(rst), .wclk(adc_clk[k]), .we(adc_valid[k]), .wdata(adc_data[64*k +: 64]), .overflow(fifo_overflow[k]),
                .rrst(rst), .rclk(clk), .re(pop), .rdata(q[k]), .empty(empty[k]));
        end
    endgenerate

    // {i0, q0, i1, q1} per chip
    wire [15:0] ch_i [0:5];
    wire [15:0] ch_q [0:5];
    generate
        for (k = 0; k < 3; k = k + 1) begin : split
            assign ch_i[2*k]   = q[k][63:48];
            assign ch_q[2*k]   = q[k][47:32];
            assign ch_i[2*k+1] = q[k][31:16];
            assign ch_q[2*k+1] = q[k][15:0];
        end
    endgenerate

    always @(posedge clk) begin
        out_valid <= pop && !rst;
        if (pop) begin
            ref_i <= ref_sel ? ch_i[5] : ch_i[0];
            ref_q <= ref_sel ? ch_q[5] : ch_q[0];
            s_i   <= {ch_i[4], ch_i[3], ch_i[2], ch_i[1]};
            s_q   <= {ch_q[4], ch_q[3], ch_q[2], ch_q[1]};
        end
    end
endmodule

// Dual-clock FIFO, Gray-coded pointers through two-flop synchronisers, first-word-fall-through read data.
module async_fifo #(parameter W = 64, parameter A = 4) (
    input  wire         wrst, wclk, we,
    input  wire [W-1:0] wdata,
    output reg          overflow,
    input  wire         rrst, rclk, re,
    output wire [W-1:0] rdata,
    output wire         empty
);
    reg [W-1:0] mem [0:(1<<A)-1];
    reg [A:0] wb, wg, rb, rg;              // binary / Gray pointers
    reg [A:0] rg_w1, rg_w2, wg_r1, wg_r2;  // synchronised Gray pointers
    wire [A:0] wb_n = wb + 1'b1;
    wire [A:0] rb_n = rb + 1'b1;
    wire full = ({~rg_w2[A:A-1], rg_w2[A-2:0]} == wg);
    always @(posedge wclk) begin
        if (wrst) begin
            wb <= 0; wg <= 0; overflow <= 1'b0; rg_w1 <= 0; rg_w2 <= 0;
        end else begin
            {rg_w2, rg_w1} <= {rg_w1, rg};
            if (we) begin
                if (full) overflow <= 1'b1;
                else begin
                    mem[wb[A-1:0]] <= wdata;
                    wb <= wb_n;
                    wg <= wb_n ^ (wb_n >> 1);
                end
            end
        end
    end
    assign empty = (rg == wg_r2);
    assign rdata = mem[rb[A-1:0]];
    always @(posedge rclk) begin
        if (rrst) begin
            rb <= 0; rg <= 0; wg_r1 <= 0; wg_r2 <= 0;
        end else begin
            {wg_r2, wg_r1} <= {wg_r1, wg};
            if (re && !empty) begin
                rb <= rb_n;
                rg <= rb_n ^ (rb_n >> 1);
            end
        end
    end
endmodule
`default_nettype wire
