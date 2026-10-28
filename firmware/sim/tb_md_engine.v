// Testbench: md_engine vs fixedpoint.md_engine(). Vectors from run_tests.py.
//   in.hex    : per sample ref_i ref_q s_i[0..NCH-1] s_q[0..NCH-1] (16-bit hex)
//   prmA/prmB : per target: tau|en<<31, then NCH words {w_i, w_q}  (32-bit hex); A before sample 0,
//               B written during block SWAPB-1 and committed -> active from block SWAPB
//   out.txt   : tgt blk I Q per record (decimal)
`timescale 1ns/1ps
module tb_md_engine;
    parameter NCH = 4, NTGT = 8, N = 384, BLOG2 = 6, OSH = 4, GAP = 12, SWAPB = 3;
    reg clk = 0, rst = 1;
    always #2.5 clk = ~clk;
    reg [15:0] vin [0:N*(2+2*NCH)-1];
    reg [31:0] pa  [0:NTGT*(1+NCH)-1];
    reg [31:0] pb  [0:NTGT*(1+NCH)-1];
    reg in_valid = 0, prm_we = 0, commit = 0;
    reg signed [15:0] ref_i, ref_q;
    reg [NCH*16-1:0] s_i, s_q;
    reg [7:0] prm_tgt, prm_sel; reg [31:0] prm_data;
    wire overrun, out_valid;
    wire [7:0] out_tgt; wire [31:0] out_blk; wire signed [31:0] out_i, out_q;
    md_engine #(.NCH(NCH), .NTGT(NTGT), .DEPTH_LOG2(12)) dut (.clk(clk), .rst(rst), .in_valid(in_valid),
        .ref_i(ref_i), .ref_q(ref_q), .s_i(s_i), .s_q(s_q), .block_log2(BLOG2[3:0]), .out_shift(OSH[4:0]),
        .prm_we(prm_we), .prm_tgt(prm_tgt), .prm_sel(prm_sel), .prm_data(prm_data), .commit(commit),
        .overrun(overrun), .out_valid(out_valid), .out_tgt(out_tgt), .out_blk(out_blk), .out_i(out_i), .out_q(out_q));
    integer f, n, c, t, s, nout;
    task load(input integer which);
        begin
            for (t = 0; t < NTGT; t = t + 1)
                for (s = 0; s <= NCH; s = s + 1) begin
                    @(negedge clk);
                    prm_we = 1; prm_tgt = t; prm_sel = s;
                    prm_data = which ? pb[t*(1+NCH)+s] : pa[t*(1+NCH)+s];
                end
            @(negedge clk); prm_we = 0;
            commit = 1; @(negedge clk); commit = 0;
        end
    endtask
    always @(posedge clk) if (out_valid) begin
        $fwrite(f, "%0d %0d %0d %0d\n", out_tgt, out_blk, out_i, out_q);
        nout = nout + 1;
    end
    initial begin
        $readmemh("in.hex", vin);
        $readmemh("prmA.hex", pa);
        $readmemh("prmB.hex", pb);
        f = $fopen("out.txt", "w");
        nout = 0;
        repeat (4) @(negedge clk);
        rst = 0;
        load(0);
        for (n = 0; n < N; n = n + 1) begin
            if (n == (SWAPB - 1) * (1 << BLOG2) + 7) load(1);
            @(negedge clk);
            in_valid = 1;
            ref_i = vin[n*(2+2*NCH)]; ref_q = vin[n*(2+2*NCH)+1];
            for (c = 0; c < NCH; c = c + 1) begin
                s_i[c*16 +: 16] = vin[n*(2+2*NCH)+2+c];
                s_q[c*16 +: 16] = vin[n*(2+2*NCH)+2+NCH+c];
            end
            @(negedge clk); in_valid = 0;
            repeat (GAP - 2) @(negedge clk);
        end
        repeat (20) @(negedge clk);
        $fclose(f);
        if (overrun) $display("OVERRUN");
        $display("DONE %0d", nout);
        $finish;
    end
endmodule
