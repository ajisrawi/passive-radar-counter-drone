# Vivado build for the passive-radar receiver node.
#
#   vivado -mode batch -source firmware/vivado/build.tcl -tclargs c     (Board C,  XC7Z020-1CLG400)
#   vivado -mode batch -source firmware/vivado/build.tcl -tclargs c2    (Board C2, XC7Z035-2FFG676)
#
# Needs: Vivado 2023.2 (ADI hdl main branch target), and ADI's HDL library built once:
#   git clone https://github.com/analogdevicesinc/hdl ; make -C hdl/library/axi_ad9361 ; set ADI_HDL=<path>/hdl
# NOT RUN IN THE DEVELOPMENT ENVIRONMENT (no Vivado there). The RTL it pulls in (firmware/hdl) is simulated
# bit-true in Icarus (firmware/sim/run_tests.py) and synthesises in Yosys for xc7; this script, the PS7 settings
# and the pin constraints still need their first Vivado run.
#
# Block design:
#   sys_ps7 (FCLK0 100 MHz AXI-Lite, FCLK1 200 MHz processing + IDELAYCTRL reference)
#   axi_ad9361 x3 (LVDS, RX only used) -> ad_merge (CDC, channel map, ref select) -> pcl_core
#   pcl_core.m_axis -> axi_dma S2MM (scatter-gather) -> HP0 -> DDR -> pcl_streamd -> GEM0     (Board C)
#   pcl_core.m_axis -> 10 GbE UDP (Board C2: see FIRMWARE.md, not in this script yet)
#   address map: pcl_core 0x43C0_0000 (4 KB, UIO), axi_ad9361 0x7902_0000 / 0x7904_0000 / 0x7906_0000,
#                axi_dma 0x4040_0000; IRQ_F2P[0] = md_irq, [1] = dma s2mm
#   EMIO: SPI0 (SPI_CLK/DI/DO, SPI_ENB1..3 = chip selects of the three AD9361), GPIO (AD_RESETB, CAL_EN_FPGA,
#         LED_PL0/1, AD9361 ENABLE/TXNRX)

set board [lindex $argv 0]
if {$board eq ""} { set board c }
set here [file dirname [file normalize [info script]]]
set fw   [file dirname $here]
set adi  $::env(ADI_HDL)
if {$board eq "c"} {
    set part xc7z020clg400-1 ; set ddr_width {16 Bit} ; set ntaps 128 ; set p 8 ; set ntgt 8 ; set fclk1 200
} else {
    # C2: 61.44 MS/s at 245.76 MHz = 4 clocks per sample -> 64-tap canceller with 32 lanes, 3 md slots per engine
    set part xc7z035ffg676-2 ; set ddr_width {32 Bit} ; set ntaps 64 ; set p 32 ; set ntgt 3 ; set fclk1 245.76
}

create_project pcl_node_$board $here/build_$board -part $part -force
set_property ip_repo_paths [list $adi/library] [current_project]
update_ip_catalog
add_files -norecurse [glob $fw/hdl/*.v] $here/system_top_$board.v
add_files -fileset constrs_1 -norecurse $here/board_$board.xdc

create_bd_design system

# ------------------------------------------------------------------ PS7 (settings from the board netlist MIO map)
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 sys_ps7]
set_property -dict [list \
    CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 3.3V} \
    CONFIG.PCW_QSPI_PERIPHERAL_ENABLE 1 CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE 1 \
    CONFIG.PCW_I2C0_PERIPHERAL_ENABLE 1 CONFIG.PCW_I2C0_I2C0_IO {MIO 10 .. 11} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE 1 CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE 1 CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE 1 CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_SD0_GRP_CD_ENABLE 1 CONFIG.PCW_SD0_GRP_CD_IO {MIO 46} \
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE 1 CONFIG.PCW_UART1_UART1_IO {MIO 48 .. 49} \
    CONFIG.PCW_GPIO_MIO_GPIO_ENABLE 1 CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE 1 \
    CONFIG.PCW_SPI0_PERIPHERAL_ENABLE 1 CONFIG.PCW_SPI0_SPI0_IO {EMIO} \
    CONFIG.PCW_USE_S_AXI_HP0 1 CONFIG.PCW_USE_FABRIC_INTERRUPT 1 CONFIG.PCW_IRQ_F2P_INTR 1 \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100 CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ $fclk1 CONFIG.PCW_EN_CLK1_PORT 1 \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH $ddr_width \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_WRITE_LEVEL 1 CONFIG.PCW_UIPARAM_DDR_TRAIN_READ_GATE 1 \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_DATA_EYE 1 CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY0 0.18 \
    ] $ps
if {$board eq "c2"} {
    set_property -dict [list CONFIG.PCW_I2C1_PERIPHERAL_ENABLE 1 CONFIG.PCW_I2C1_I2C1_IO {MIO 12 .. 13}] $ps
}
# NT5CC256M16ER-EK (DDR3L 4 Gb x16) is not in Vivado's list; MT41K256M16 RE-125 has the same organisation and
# speed bin family. Board delays: from the routed DDR lengths (hardware/board_c*/), refine after the first build.

apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "0"} $ps

# ------------------------------------------------------------------ resets, clocks
set rst100 [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_100]
set rstp   [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_proc]
connect_bd_net [get_bd_pins sys_ps7/FCLK_CLK0] [get_bd_pins rst_100/slowest_sync_clk]
connect_bd_net [get_bd_pins sys_ps7/FCLK_CLK1] [get_bd_pins rst_proc/slowest_sync_clk]
connect_bd_net [get_bd_pins sys_ps7/FCLK_RESET0_N] [get_bd_pins rst_100/ext_reset_in] [get_bd_pins rst_proc/ext_reset_in]

# ------------------------------------------------------------------ three AD9361 interfaces (ADI)
# explicit, named BD ports (system_top_<board>.v connects them to the pins of board_<board>.xdc)
for {set k 1} {$k <= 3} {incr k} {
    set c [create_bd_cell -type ip -vlnv analog.com:user:axi_ad9361 axi_ad9361_$k]
    set_property -dict [list CONFIG.ID [expr {$k - 1}] CONFIG.CMOS_OR_LVDS_N 0 CONFIG.ADC_INIT_DELAY 23                              CONFIG.DAC_DDS_DISABLE 1 CONFIG.ADC_USERPORTS_DISABLE 0] $c
    foreach {port pin dir w} {rx_clk_in_p rx_clk_in_p I 1 rx_clk_in_n rx_clk_in_n I 1 rx_frame_in_p rx_frame_in_p I 1                               rx_frame_in_n rx_frame_in_n I 1 rx_data_in_p rx_data_in_p I 6 rx_data_in_n rx_data_in_n I 6                               tx_clk_out_p tx_clk_out_p O 1 tx_clk_out_n tx_clk_out_n O 1} {
        if {$w > 1} { create_bd_port -dir $dir -from [expr {$w-1}] -to 0 ad${k}_$port } else { create_bd_port -dir $dir ad${k}_$port }
        connect_bd_net [get_bd_ports ad${k}_$port] [get_bd_pins axi_ad9361_$k/$pin]
    }
    connect_bd_net [get_bd_pins sys_ps7/FCLK_CLK1] [get_bd_pins axi_ad9361_$k/delay_clk]
}
# PS SPI0 (EMIO) to the three AD9361 SPI ports, PS GPIO (EMIO) for control lines, PS UART0 (EMIO) to the GNSS
set_property -dict [list CONFIG.PCW_GPIO_EMIO_GPIO_IO 16 CONFIG.PCW_UART0_PERIPHERAL_ENABLE 1                          CONFIG.PCW_UART0_UART0_IO {EMIO}] [get_bd_cells sys_ps7]
foreach {port pin dir w} {spi_sclk SPI0_SCLK_O O 1 spi_mosi SPI0_MOSI_O O 1 spi_miso SPI0_MISO_I I 1                           spi_ss0 SPI0_SS_O O 1 spi_ss1 SPI0_SS1_O O 1 spi_ss2 SPI0_SS2_O O 1                           gpio_o GPIO_O O 16 gpio_i GPIO_I I 16 uart0_tx UART0_TX O 1 uart0_rx UART0_RX I 1} {
    if {$w > 1} { create_bd_port -dir $dir -from [expr {$w-1}] -to 0 $port } else { create_bd_port -dir $dir $port }
    connect_bd_net [get_bd_ports $port] [get_bd_pins sys_ps7/$pin]
}
create_bd_port -dir I -type data gnss_pps
create_bd_port -dir I -type data spi_ss_i_tie
connect_bd_net [get_bd_ports spi_ss_i_tie] [get_bd_pins sys_ps7/SPI0_SS_I]

# ------------------------------------------------------------------ merge + core (RTL module references)
set mg [create_bd_cell -type module -reference ad_merge ad_merge_0]
set core [create_bd_cell -type module -reference pcl_core pcl_core_0]
set_property -dict [list CONFIG.NTAPS $ntaps CONFIG.P $p CONFIG.NTGT $ntgt] $core
for {set k 1} {$k <= 3} {incr k} {
    # ad_merge takes {clk, valid, {i0,q0,i1,q1}} per chip; a small concat in system_top would also do
    set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat cat_$k]
    set_property -dict [list CONFIG.NUM_PORTS 4 CONFIG.IN0_WIDTH 16 CONFIG.IN1_WIDTH 16 CONFIG.IN2_WIDTH 16 CONFIG.IN3_WIDTH 16] $cc
    connect_bd_net [get_bd_pins axi_ad9361_$k/adc_data_q1] [get_bd_pins cat_$k/In0]
    connect_bd_net [get_bd_pins axi_ad9361_$k/adc_data_i1] [get_bd_pins cat_$k/In1]
    connect_bd_net [get_bd_pins axi_ad9361_$k/adc_data_q0] [get_bd_pins cat_$k/In2]
    connect_bd_net [get_bd_pins axi_ad9361_$k/adc_data_i0] [get_bd_pins cat_$k/In3]
}
foreach {sig pins} {adc_clk l_clk adc_valid adc_valid_i0} {
    set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat cat_$sig]
    set_property CONFIG.NUM_PORTS 3 $cc
    for {set k 1} {$k <= 3} {incr k} { connect_bd_net [get_bd_pins axi_ad9361_$k/$pins] [get_bd_pins cat_$sig/In[expr {$k-1}]] }
    connect_bd_net [get_bd_pins cat_$sig/dout] [get_bd_pins ad_merge_0/$sig]
}
set cd [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat cat_data]
set_property -dict [list CONFIG.NUM_PORTS 3 CONFIG.IN0_WIDTH 64 CONFIG.IN1_WIDTH 64 CONFIG.IN2_WIDTH 64] $cd
for {set k 1} {$k <= 3} {incr k} { connect_bd_net [get_bd_pins cat_$k/dout] [get_bd_pins cat_data/In[expr {$k-1}]] }
connect_bd_net [get_bd_pins cat_data/dout] [get_bd_pins ad_merge_0/adc_data]
connect_bd_net [get_bd_pins sys_ps7/FCLK_CLK1] [get_bd_pins ad_merge_0/clk] [get_bd_pins pcl_core_0/clk]
connect_bd_net [get_bd_pins rst_proc/peripheral_reset] [get_bd_pins ad_merge_0/rst] [get_bd_pins pcl_core_0/rst]
foreach {a b} {out_valid in_valid ref_i ref_i ref_q ref_q s_i s_i s_q s_q} {
    connect_bd_net [get_bd_pins ad_merge_0/$a] [get_bd_pins pcl_core_0/$b]
}
connect_bd_net [get_bd_pins pcl_core_0/ref_sel] [get_bd_pins ad_merge_0/ref_sel]
connect_bd_net [get_bd_ports gnss_pps] [get_bd_pins pcl_core_0/pps]

# ------------------------------------------------------------------ stream DMA (Board C)
if {$board eq "c"} {
    set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma axi_dma_0]
    set_property -dict [list CONFIG.c_include_mm2s 0 CONFIG.c_include_sg 1 CONFIG.c_sg_length_width 16 \
                             CONFIG.c_s2mm_burst_size 64 CONFIG.c_m_axi_s2mm_data_width 64] $dma
    connect_bd_intf_net [get_bd_intf_pins pcl_core_0/m_axis] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
}

# ------------------------------------------------------------------ AXI wiring, interrupts, addresses
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master /sys_ps7/M_AXI_GP0 Clk Auto} [get_bd_intf_pins pcl_core_0/s_axil]
for {set k 1} {$k <= 3} {incr k} {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master /sys_ps7/M_AXI_GP0 Clk Auto} [get_bd_intf_pins axi_ad9361_$k/s_axi]
}
if {$board eq "c"} {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master /sys_ps7/M_AXI_GP0 Clk Auto} [get_bd_intf_pins axi_dma_0/S_AXI_LITE]
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Slave /sys_ps7/S_AXI_HP0 Clk Auto} [get_bd_intf_pins axi_dma_0/M_AXI_SG]
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Slave /sys_ps7/S_AXI_HP0 Clk Auto} [get_bd_intf_pins axi_dma_0/M_AXI_S2MM]
}
set irq [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat irq_cat]
set_property CONFIG.NUM_PORTS 2 $irq
connect_bd_net [get_bd_pins pcl_core_0/md_irq] [get_bd_pins irq_cat/In0]
if {$board eq "c"} { connect_bd_net [get_bd_pins axi_dma_0/s2mm_introut] [get_bd_pins irq_cat/In1] }
connect_bd_net [get_bd_pins irq_cat/dout] [get_bd_pins sys_ps7/IRQ_F2P]
assign_bd_address
set_property offset 0x43C00000 [get_bd_addr_segs {sys_ps7/Data/SEG_pcl_core_0_reg0}]
set_property range 4K [get_bd_addr_segs {sys_ps7/Data/SEG_pcl_core_0_reg0}]
for {set k 1} {$k <= 3} {incr k} {
    set_property offset [format 0x%08X [expr {0x79000000 + 0x20000 * $k}]] [get_bd_addr_segs "sys_ps7/Data/SEG_axi_ad9361_${k}_axi_lite"]
}
if {$board eq "c"} { set_property offset 0x40400000 [get_bd_addr_segs {sys_ps7/Data/SEG_axi_dma_0_Reg}] }
validate_bd_design
save_bd_design
make_wrapper -files [get_files system.bd] -top
add_files -norecurse [glob $here/build_$board/*.gen/sources_1/bd/system/hdl/system_wrapper.v]
set_property top system_top [current_fileset]

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
write_hw_platform -fixed -include_bit -force $here/build_$board/pcl_node_$board.xsa
puts "done: $here/build_$board/pcl_node_$board.xsa"
