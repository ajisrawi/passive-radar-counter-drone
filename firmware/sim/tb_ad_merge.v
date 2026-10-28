// Testbench: ad_merge with three unrelated chip clocks (32.0, 31.9, 32.1 MHz-ish with jitter-free phases) feeding
// a 200 MHz processing clock. Each chip sends a counter pattern; the merged stream must keep the three chips'
// k-th samples together, in order, with no loss, for both ref_sel settings.
`timescale 1ns/1ps
module tb_ad_merge;
    reg rst = 1, clk = 0, ref_sel = 0;
    reg [2:0] aclk = 0;
    always #2.5 clk = ~clk;
    always #15.6 aclk[0] = ~aclk[0];
    always #15.7 aclk[1] = ~aclk[1];
    always #15.5 aclk[2] = ~aclk[2];
    reg [2:0] avalid = 0;
    reg [191:0] adata = 0;
    reg [15:0] cnt [0:2];
    wire ov; wire [15:0] ri, rq; wire [63:0] si, sq; wire [2:0] ovf;
    ad_merge dut (.rst(rst), .adc_clk(aclk), .adc_valid(avalid), .adc_data(adata), .clk(clk), .ref_sel(ref_sel),
                  .out_valid(ov), .ref_i(ri), .ref_q(rq), .s_i(si), .s_q(sq), .fifo_overflow(ovf));
    genvar k;
    generate
        for (k = 0; k < 3; k = k + 1) begin : g
            // a sample every 4 chip clocks (2R2T DDR: 4 DATA_CLK cycles per sample), word = {cnt, k, ch}
            reg [1:0] ph = 0;
            always @(posedge aclk[k]) begin
                if (rst) begin cnt[k] <= 0; ph <= 0; avalid[k] <= 0; end
                else begin
                    ph <= ph + 1'b1;
                    avalid[k] <= (ph == 0);
                    if (ph == 0) begin
                        adata[64*k +: 64] <= {cnt[k][11:0], 2'd0, k[1:0], cnt[k][11:0], 2'd1, k[1:0],
                                              cnt[k][11:0], 2'd2, k[1:0], cnt[k][11:0], 2'd3, k[1:0]};
                        cnt[k] <= cnt[k] + 1'b1;
                    end
                end
            end
        end
    endgenerate
    integer n = 0, bad = 0;
    reg [11:0] exp_n = 0;
    always @(posedge clk) if (ov) begin
        // every lane must carry the same sample index; check the chip/lane tags
        if (ri[15:4] != exp_n || si[15:4] != exp_n || si[63:52] != exp_n || sq[31:20] != exp_n) bad = bad + 1;
        if (ri[1:0] != (ref_sel ? 2'd2 : 2'd0) || ri[3:2] != (ref_sel ? 2'd2 : 2'd0)) bad = bad + 1;   // CH5 = chip 2 lane i1
        exp_n = exp_n + 1;
        n = n + 1;
    end
    initial begin
        #200 rst = 0;
        #60000 ref_sel = 1;
        #60000;
        $display("samples %0d mismatches %0d overflow %b", n, bad, ovf);
        if (bad == 0 && n > 900 && ovf == 0) $display("PASS"); else $display("FAIL");
        $display("DONE");
        $finish;
    end
endmodule
