// Requantise and pack the stream: reference to REF_BITS, surveillance residuals to SV_BITS (rounded, saturated),
// one sample = {ref I, ref Q, ch0 I, ch0 Q, ... ch3 Q} LSB first, cut into 64-bit AXI-Stream words.
// 12 + 12 + 4 x (8 + 8) = 88 bits; 128 samples = 1408 bytes = 176 words = one UDP payload (TLAST on word 175).
// Samples must be >= 2 clocks apart. Bit-true model: fixedpoint.py requant() + pack_samples().
`default_nettype none
module stream_pack #(
    parameter NCH      = 4,
    parameter REF_BITS = 12,
    parameter SV_BITS  = 8,
    parameter PKT_WORDS = 176
) (
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 in_valid,
    input  wire signed [15:0]   ref_i,
    input  wire signed [15:0]   ref_q,
    input  wire [NCH*16-1:0]    s_i,
    input  wire [NCH*16-1:0]    s_q,
    input  wire [3:0]           ref_shift,
    input  wire [3:0]           sv_shift,
    output reg                  m_valid,
    output reg  [63:0]          m_data,
    output reg                  m_last,
    output reg                  overflow           // sticky: a word was produced while the sink was not ready
    , input wire                m_ready
);
    localparam SBITS = 2 * REF_BITS + 2 * NCH * SV_BITS;
    localparam BUFW  = 64 + SBITS;

    function [31:0] rq;  // round, shift, saturate to n bits (returned sign-extended in 32)
        input signed [15:0] x;
        input [3:0] sh;
        input integer n;
        reg signed [31:0] v;
        begin
            v = (sh == 0) ? x : (($signed({{16{x[15]}}, x}) + (32'sd1 <<< (sh - 1))) >>> sh);
            if (v > (32'sd1 <<< (n - 1)) - 1) v = (32'sd1 <<< (n - 1)) - 1;
            if (v < -(32'sd1 <<< (n - 1))) v = -(32'sd1 <<< (n - 1));
            rq = v;
        end
    endfunction

    reg [SBITS-1:0] smp;
    integer c;
    always @(*) begin
        smp = 0;
        smp[REF_BITS-1:0]            = rq(ref_i, ref_shift, REF_BITS);
        smp[2*REF_BITS-1:REF_BITS]   = rq(ref_q, ref_shift, REF_BITS);
        for (c = 0; c < NCH; c = c + 1) begin
            smp[2*REF_BITS + (2*c)*SV_BITS   +: SV_BITS] = rq(s_i[c*16 +: 16], sv_shift, SV_BITS);
            smp[2*REF_BITS + (2*c+1)*SV_BITS +: SV_BITS] = rq(s_q[c*16 +: 16], sv_shift, SV_BITS);
        end
    end

    reg [BUFW-1:0] buf_;
    reg [7:0]      nb;
    reg [15:0]     wcnt;
    wire           emit = (nb >= 64);
    wire [BUFW-1:0] after = emit ? (buf_ >> 64) : buf_;
    wire [7:0]      nb2   = emit ? nb - 8'd64 : nb;

    always @(posedge clk) begin
        if (rst) begin
            buf_ <= 0; nb <= 0; wcnt <= 0; m_valid <= 1'b0; m_last <= 1'b0; overflow <= 1'b0;
        end else begin
            m_valid <= emit;
            if (emit) begin
                m_data <= buf_[63:0];
                m_last <= (wcnt == PKT_WORDS - 1);
                wcnt   <= (wcnt == PKT_WORDS - 1) ? 16'd0 : wcnt + 1'b1;
                if (m_valid && !m_ready) overflow <= 1'b1;
            end
            if (in_valid) begin
                buf_ <= after | ({{(BUFW-SBITS){1'b0}}, smp} << nb2);
                nb   <= nb2 + SBITS;
            end else begin
                buf_ <= after;
                nb   <= nb2;
            end
        end
    end
endmodule
`default_nettype wire
