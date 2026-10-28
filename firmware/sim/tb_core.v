// Testbench: pcl_core configured over AXI4-Lite (as the ARM does), then fed samples.
//   in.hex   : samples (as tb_canceller)        taps.hex : (ch, k) tap_i tap_q (18-bit hex)
//   prm.hex  : md target words (as tb_md_engine)
//   stream.txt : AXI-Stream words (hex) + tlast    md.txt : popped md records (hdr I Q)    regs.txt : misc reads
`timescale 1ns/1ps
module tb_core;
    parameter NCH = 4, NTAPS = 128, NTGT = 8, N = 4096, GAP = 25, BLOG2 = 9, OSH = 12, SVSH = 2;
    reg clk = 0, rst = 1;
    always #2.5 clk = ~clk;
    reg [15:0] vin [0:N*(2+2*NCH)-1];
    reg [17:0] taps [0:2*NCH*NTAPS-1];
    reg [31:0] prm  [0:NTGT*(1+NCH)-1];
    reg in_valid = 0, pps = 0;
    reg signed [15:0] ref_i, ref_q;
    reg [NCH*16-1:0] s_i, s_q;
    wire tv, tl; wire [63:0] td;
    reg [11:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg [31:0] wdata = 0;
    wire awready, wready, bvalid, arready, rvalid, irq, rsel; wire [1:0] bresp, rresp; wire [31:0] rdata;
    pcl_core #(.NCH(NCH), .NTAPS(NTAPS), .P(8), .NTGT(NTGT)) dut (.clk(clk), .rst(rst), .in_valid(in_valid),
        .ref_i(ref_i), .ref_q(ref_q), .s_i(s_i), .s_q(s_q), .pps(pps),
        .m_axis_tvalid(tv), .m_axis_tdata(td), .m_axis_tlast(tl), .m_axis_tready(1'b1),
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready), .s_axil_wdata(wdata),
        .s_axil_wvalid(wvalid), .s_axil_wready(wready), .s_axil_bresp(bresp), .s_axil_bvalid(bvalid),
        .s_axil_bready(bready), .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready), .md_irq(irq), .ref_sel(rsel));

    task axw(input [11:0] a, input [31:0] d);
        reg aw_done, w_done;
        begin
            @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1; aw_done = 0; w_done = 0;
            while (!(aw_done && w_done)) begin
                @(negedge clk);                    // sample handshakes between edges (no race)
                if (awready) begin aw_done = 1; awvalid = 0; end
                if (wready)  begin w_done = 1;  wvalid = 0;  end
            end
            while (!bvalid) @(negedge clk);
            @(negedge clk);
        end
    endtask
    task axr(input [11:0] a, output [31:0] d);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(negedge clk); while (!arready) @(negedge clk);
            arvalid = 0;
            while (!rvalid) @(negedge clk);
            d = rdata;
            @(negedge clk);
        end
    endtask

    integer fs, fm, fr, n, c, k, t, s, lvl;
    reg [31:0] d, hdr, vi, vq;
    always @(posedge clk) if (tv) $fwrite(fs, "%016h %0d\n", td, tl);
    initial begin
        $readmemh("in.hex", vin);
        $readmemh("taps.hex", taps);
        $readmemh("prm.hex", prm);
        fs = $fopen("stream.txt", "w"); fm = $fopen("md.txt", "w"); fr = $fopen("regs.txt", "w");
        repeat (4) @(negedge clk);
        rst = 0;
        axr(12'h000, d); $fwrite(fr, "ID %08h\n", d);
        axw(12'h028, 1); axr(12'h028, d); $fwrite(fr, "REFSEL %0d%0d\n", d, rsel); axw(12'h028, 0);
        axw(12'h008, N);                                   // one CPI
        axw(12'h00C, SVSH);
        axw(12'h010, (OSH << 8) | BLOG2);
        for (c = 0; c < NCH; c = c + 1)
            for (k = 0; k < NTAPS; k = k + 1) begin
                axw(12'h040, (c << 16) | k);
                axw(12'h044, {{14{taps[2*(c*NTAPS+k)][17]}}, taps[2*(c*NTAPS+k)]});
                axw(12'h048, {{14{taps[2*(c*NTAPS+k)+1][17]}}, taps[2*(c*NTAPS+k)+1]});
            end
        for (t = 0; t < NTGT; t = t + 1)
            for (s = 0; s <= NCH; s = s + 1)
                axw(12'h100 + 4 * (8 * t + s), prm[t*(1+NCH)+s]);
        axw(12'h004, 32'h7);                               // enable + both commits
        for (n = 0; n < N; n = n + 1) begin
            @(negedge clk);
            in_valid = 1;
            ref_i = vin[n*(2+2*NCH)]; ref_q = vin[n*(2+2*NCH)+1];
            for (c = 0; c < NCH; c = c + 1) begin
                s_i[c*16 +: 16] = vin[n*(2+2*NCH)+2+c];
                s_q[c*16 +: 16] = vin[n*(2+2*NCH)+2+NCH+c];
            end
            pps = (n >= 1000 && n < 1010);
            @(negedge clk); in_valid = 0;
            repeat (GAP - 2) @(negedge clk);
        end
        repeat (60) @(negedge clk);
        axr(12'h014, d); $fwrite(fr, "STATUS %08h\n", d);
        axr(12'h018, d); $fwrite(fr, "SAMPLES %0d\n", d);
        axr(12'h020, d); $fwrite(fr, "PPS %0d\n", d);
        axr(12'h080, d); lvl = d; $fwrite(fr, "MDLVL %0d\n", lvl);
        for (k = 0; k < lvl; k = k + 1) begin                       // ring window, as the ARM reads it
            axr(12'h800 + 16 * (k % 128), hdr); axr(12'h804 + 16 * (k % 128), vi); axr(12'h808 + 16 * (k % 128), vq);
            $fwrite(fm, "%0d %0d %0d %0d\n", hdr[31:24], hdr[23:0], $signed(vi), $signed(vq));
        end
        axw(12'h084, lvl);
        axr(12'h084, d); $fwrite(fr, "MDRD %0d\n", d);
        $fclose(fs); $fclose(fm); $fclose(fr);
        $display("DONE");
        $finish;
    end
endmodule
