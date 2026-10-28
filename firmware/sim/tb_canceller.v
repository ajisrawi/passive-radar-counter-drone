// Testbench: canceller vs fixedpoint.canceller(). Vectors from run_tests.py.
//   in.hex   : per sample  ref_i ref_q s_i[0..NCH-1] s_q[0..NCH-1]   (16-bit hex)
//   tapsA/B  : per (ch, k) tap_i tap_q (18-bit hex), loaded before sample 0 / during CPI 0
//   out.txt  : per sample  y_i[0..] y_q[0..] (decimal)
`timescale 1ns/1ps
module tb_canceller;
    parameter NTAPS = 128, NCH = 4, P = 8, N = 600, CPI = 300, GAP = 25;
    reg clk = 0, rst = 1;
    always #2.5 clk = ~clk;
    reg [15:0] vin [0:N*(2+2*NCH)-1];
    reg [17:0] ta  [0:2*NCH*NTAPS-1];
    reg [17:0] tb  [0:2*NCH*NTAPS-1];
    reg in_valid = 0, cpi_start = 0, tap_we = 0, commit = 0;
    reg signed [15:0] ref_i, ref_q;
    reg [NCH*16-1:0] s_i, s_q;
    reg [7:0] tap_ch; reg [15:0] tap_idx; reg signed [17:0] tap_i, tap_q;
    wire bank, overrun, out_valid;
    wire signed [15:0] ro_i, ro_q;
    wire [NCH*16-1:0] y_i, y_q;
    canceller #(.NTAPS(NTAPS), .NCH(NCH), .P(P)) dut (.clk(clk), .rst(rst), .in_valid(in_valid), .cpi_start(cpi_start),
        .ref_i(ref_i), .ref_q(ref_q), .s_i(s_i), .s_q(s_q), .tap_we(tap_we), .tap_ch(tap_ch), .tap_idx(tap_idx),
        .tap_i(tap_i), .tap_q(tap_q), .commit(commit), .bank(bank), .overrun(overrun),
        .out_valid(out_valid), .ref_out_i(ro_i), .ref_out_q(ro_q), .y_i(y_i), .y_q(y_q));
    integer f, n, c, k, nout;
    task load(input integer which);
        begin
            for (c = 0; c < NCH; c = c + 1)
                for (k = 0; k < NTAPS; k = k + 1) begin
                    @(negedge clk);
                    tap_we = 1; tap_ch = c; tap_idx = k;
                    tap_i = which ? tb[2*(c*NTAPS+k)] : ta[2*(c*NTAPS+k)];
                    tap_q = which ? tb[2*(c*NTAPS+k)+1] : ta[2*(c*NTAPS+k)+1];
                end
            @(negedge clk); tap_we = 0;
            commit = 1; @(negedge clk); commit = 0;
        end
    endtask
    always @(posedge clk) if (out_valid) begin
        for (c = 0; c < NCH; c = c + 1) $fwrite(f, "%0d %0d ", $signed(y_i[c*16 +: 16]), $signed(y_q[c*16 +: 16]));
        $fwrite(f, "%0d %0d\n", ro_i, ro_q);
        nout = nout + 1;
    end
    initial begin
        $readmemh("in.hex", vin);
        $readmemh("tapsA.hex", ta);
        $readmemh("tapsB.hex", tb);
        f = $fopen("out.txt", "w");
        nout = 0;
        repeat (4) @(negedge clk);
        rst = 0;
        load(0);                                   // taps A -> swap at sample 0
        for (n = 0; n < N; n = n + 1) begin
            if (n == CPI / 2) load(1);             // taps B, committed mid-CPI -> swap at sample CPI
            @(negedge clk);
            in_valid = 1; cpi_start = (n % CPI == 0);
            ref_i = vin[n*(2+2*NCH)]; ref_q = vin[n*(2+2*NCH)+1];
            for (c = 0; c < NCH; c = c + 1) begin
                s_i[c*16 +: 16] = vin[n*(2+2*NCH)+2+c];
                s_q[c*16 +: 16] = vin[n*(2+2*NCH)+2+NCH+c];
            end
            @(negedge clk); in_valid = 0; cpi_start = 0;
            repeat (GAP - 2) @(negedge clk);
        end
        repeat (40) @(negedge clk);
        $fclose(f);
        if (overrun) $display("OVERRUN");
        $display("DONE %0d", nout);
        $finish;
    end
endmodule
