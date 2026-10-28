// Board C top level: board pins (names = board_c.xdc, generated from the netlist) -> block design (build.tcl).
// EMIO GPIO map (Linux gpiochip "zynq_gpio", EMIO base 54 on the Zynq-7000):
//   o[0] AD_RESETB   o[1] AD_SYNC_IN (multi-chip sync)   o[2] AD_ENABLE   o[3] AD_TXNRX   o[4] AD_EN_AGC
//   o[5] CAL_EN_FPGA (Board A2 noise source)   o[6] LED_PL0   o[7] LED_PL1   o[8] GNSS_RESETN   i[9] FMC_PRSNT_L
`default_nettype none
module system_top (
    inout  wire [14:0] ddr_addr,
    inout  wire [2:0]  ddr_ba,
    inout  wire        ddr_cas_n, ddr_ck_n, ddr_ck_p, ddr_cke, ddr_cs_n, ddr_odt, ddr_ras_n, ddr_reset_n, ddr_we_n,
    inout  wire [3:0]  ddr_dm, ddr_dqs_n, ddr_dqs_p,
    inout  wire [31:0] ddr_dq,
    inout  wire        fixed_io_ddr_vrn, fixed_io_ddr_vrp, fixed_io_ps_clk, fixed_io_ps_porb, fixed_io_ps_srstb,
    inout  wire [53:0] fixed_io_mio,
    input  wire       ad1_dclk_p, ad1_dclk_n, ad1_frame_p, ad1_frame_n,
    input  wire       ad1_rxd0_p, ad1_rxd0_n, ad1_rxd1_p, ad1_rxd1_n, ad1_rxd2_p, ad1_rxd2_n,
    input  wire       ad1_rxd3_p, ad1_rxd3_n, ad1_rxd4_p, ad1_rxd4_n, ad1_rxd5_p, ad1_rxd5_n,
    output wire       ad1_fbclk_p, ad1_fbclk_n,
    input  wire       ad2_dclk_p, ad2_dclk_n, ad2_frame_p, ad2_frame_n,
    input  wire       ad2_rxd0_p, ad2_rxd0_n, ad2_rxd1_p, ad2_rxd1_n, ad2_rxd2_p, ad2_rxd2_n,
    input  wire       ad2_rxd3_p, ad2_rxd3_n, ad2_rxd4_p, ad2_rxd4_n, ad2_rxd5_p, ad2_rxd5_n,
    output wire       ad2_fbclk_p, ad2_fbclk_n,
    input  wire       ad3_dclk_p, ad3_dclk_n, ad3_frame_p, ad3_frame_n,
    input  wire       ad3_rxd0_p, ad3_rxd0_n, ad3_rxd1_p, ad3_rxd1_n, ad3_rxd2_p, ad3_rxd2_n,
    input  wire       ad3_rxd3_p, ad3_rxd3_n, ad3_rxd4_p, ad3_rxd4_n, ad3_rxd5_p, ad3_rxd5_n,
    output wire       ad3_fbclk_p, ad3_fbclk_n,
    output wire       ad_resetb, ad_sync_in, ad_enable, ad_txnrx, ad_en_agc,
    output wire       spi_clk, spi_di, spi_enb1, spi_enb2, spi_enb3,
    input  wire       spi_do,
    output wire       cal_en_fpga, led_pl0, led_pl1,
    input  wire       gnss_pps, gnss_txd,
    output wire       gnss_rxd, gnss_resetn,
    input  wire       fmc_prsnt_l,
    input  wire       fpga_refclk_p, fpga_refclk_n
`ifdef BOARD_C2
    , input wire      mgtref156_p, mgtref156_n
`endif
);
    wire [15:0] gpio_o;
    wire [15:0] gpio_i = {6'd0, fmc_prsnt_l, 9'd0};
    assign {gnss_resetn, led_pl1, led_pl0, cal_en_fpga, ad_en_agc, ad_txnrx, ad_enable, ad_sync_in, ad_resetb} = gpio_o[8:0];

    system_wrapper bd (
        .ad1_rx_clk_in_p(ad1_dclk_p), .ad1_rx_clk_in_n(ad1_dclk_n), .ad1_rx_frame_in_p(ad1_frame_p), .ad1_rx_frame_in_n(ad1_frame_n),
        .ad1_rx_data_in_p({ad1_rxd5_p, ad1_rxd4_p, ad1_rxd3_p, ad1_rxd2_p, ad1_rxd1_p, ad1_rxd0_p}),
        .ad1_rx_data_in_n({ad1_rxd5_n, ad1_rxd4_n, ad1_rxd3_n, ad1_rxd2_n, ad1_rxd1_n, ad1_rxd0_n}),
        .ad1_tx_clk_out_p(ad1_fbclk_p), .ad1_tx_clk_out_n(ad1_fbclk_n),
        .ad2_rx_clk_in_p(ad2_dclk_p), .ad2_rx_clk_in_n(ad2_dclk_n), .ad2_rx_frame_in_p(ad2_frame_p), .ad2_rx_frame_in_n(ad2_frame_n),
        .ad2_rx_data_in_p({ad2_rxd5_p, ad2_rxd4_p, ad2_rxd3_p, ad2_rxd2_p, ad2_rxd1_p, ad2_rxd0_p}),
        .ad2_rx_data_in_n({ad2_rxd5_n, ad2_rxd4_n, ad2_rxd3_n, ad2_rxd2_n, ad2_rxd1_n, ad2_rxd0_n}),
        .ad2_tx_clk_out_p(ad2_fbclk_p), .ad2_tx_clk_out_n(ad2_fbclk_n),
        .ad3_rx_clk_in_p(ad3_dclk_p), .ad3_rx_clk_in_n(ad3_dclk_n), .ad3_rx_frame_in_p(ad3_frame_p), .ad3_rx_frame_in_n(ad3_frame_n),
        .ad3_rx_data_in_p({ad3_rxd5_p, ad3_rxd4_p, ad3_rxd3_p, ad3_rxd2_p, ad3_rxd1_p, ad3_rxd0_p}),
        .ad3_rx_data_in_n({ad3_rxd5_n, ad3_rxd4_n, ad3_rxd3_n, ad3_rxd2_n, ad3_rxd1_n, ad3_rxd0_n}),
        .ad3_tx_clk_out_p(ad3_fbclk_p), .ad3_tx_clk_out_n(ad3_fbclk_n),
        .spi_sclk(spi_clk), .spi_mosi(spi_di), .spi_miso(spi_do),
        .spi_ss0(spi_enb1), .spi_ss1(spi_enb2), .spi_ss2(spi_enb3), .spi_ss_i_tie(1'b1),
        .gpio_o(gpio_o), .gpio_i(gpio_i),
        .uart0_tx(gnss_rxd), .uart0_rx(gnss_txd),
        .DDR_addr(ddr_addr), .DDR_ba(ddr_ba), .DDR_cas_n(ddr_cas_n), .DDR_ck_n(ddr_ck_n), .DDR_ck_p(ddr_ck_p),
        .DDR_cke(ddr_cke), .DDR_cs_n(ddr_cs_n), .DDR_dm(ddr_dm), .DDR_dq(ddr_dq), .DDR_dqs_n(ddr_dqs_n),
        .DDR_dqs_p(ddr_dqs_p), .DDR_odt(ddr_odt), .DDR_ras_n(ddr_ras_n), .DDR_reset_n(ddr_reset_n), .DDR_we_n(ddr_we_n),
        .FIXED_IO_ddr_vrn(fixed_io_ddr_vrn), .FIXED_IO_ddr_vrp(fixed_io_ddr_vrp), .FIXED_IO_mio(fixed_io_mio),
        .FIXED_IO_ps_clk(fixed_io_ps_clk), .FIXED_IO_ps_porb(fixed_io_ps_porb), .FIXED_IO_ps_srstb(fixed_io_ps_srstb),
        .gnss_pps(gnss_pps)
    );
endmodule
`default_nettype wire
