"""Selected parts (LCSC numbers) for the passive radar receiver boards.

Stock figures were observed at JLCPCB/LCSC on 2026-10-20 and will change.
Symbols and footprints are fetched from the LCSC/EasyEDA library with
easyeda2kicad, so pin names and land patterns come from the vendor library.
"""

PARTS = {
    # ---- RF front end (board A) ----
    "LNA":        ("C470902",  "SPF5043Z",            "50 MHz-4 GHz LNA, NF 0.8 dB, OIP3 35 dBm, 5 V 46 mA"),
    "RFSW":       ("C470892",  "PE4259-63",           "SPDT 10 MHz-3 GHz, 0.35 dB IL, antenna / calibration select"),
    "LDO_LN":     ("C580012",  "LT3045EMSE#PBF",      "0.8 uVrms LDO, 500 mA (LNA 5 V rail, noise source)"),
    "SMA":        ("C496549",  "BWSMA-KE-Z001",       "SMA jack, through-hole, 6 GHz"),
    # ---- 10 GbE processing board (board C2), stock observed 2026-10-26 ----
    "ZYNQ35":     ("C1884735", "XC7Z035-2FFG676I",    "Zynq-7035, 8 GTX to 10.3125 Gbit/s (-2, FFG676)"),
    "SFP_CONN":   ("C305914",  "TE 1888247-1",        "SFP+ 20-pin SMD connector"),
    "SFP_CAGE":   ("C589577",  "TE 2227302-1",        "SFP+ 1x1 press-fit cage"),
    "OSC156":     ("C7425469", "OB2EL89CLIB112YLC-156.25M", "156.25 MHz LVDS oscillator, GTX reference"),
    "I2C_MUX":    ("C2653307", "TCA9543APWR",         "2-channel I2C mux (both SFP+ modules at 0xA0/0xA2)"),
    "BALUN_WB":   ("C494678",  "TCM1-63AX+",          "1:1 balun 10 MHz-6 GHz (board B mid/high/n78)"),
    # ---- multiband front end (board A2), stock observed 2026-10-26 ----
    "RFSW_6G":    ("C129189",  "SKY13351-378LF",      "SPDT 20 MHz-6 GHz, 0.35 dB IL, VCTL1/VCTL2 complementary"),
    "INV":        ("C7827",    "SN74LVC1G04DBVR",     "single inverter, makes VCTL2 = NOT CAL_EN"),
    "BPF_MID":    ("C474007",  "RFBPF1608060AAT",     "LTCC band-pass 1.5-2.4 GHz, 0.95 dB (LTE B3 + B1)"),
    "BPF_HIGH":   ("C432966",  "DEA162495BT-1289A1",  "LTCC band-pass 2.3-2.69 GHz, 1.4 dB (LTE B7 + 5G n41)"),
    "BPF_N78":    ("C3156235", "DEA203750BT-2292A1-H", "LTCC band-pass 3.3-4.2 GHz, 1.5 dB, ~40 dB at 1.8-2.7 GHz (5G n78)"),
    # ---- digitizer (board B) ----
    "AD9361":     ("C515884",  "AD9361BBCZ",          "RF agile transceiver, 2 RX / 2 TX, 12-bit, BGA-144"),
    "BALUN":      ("C92015",   "ATB2012-50011-T000",  "1:1 balun 40-860 MHz, 0805"),
    "TCXO40":     ("C516506",  "BT0507BH3I507BN40B",  "40 MHz TCXO, +/-0.5 ppm, CMOS, 3.3 V"),
    "CLKBUF":     ("C1855734", "LMK1C1104PWR",        "1:4 LVCMOS clock buffer, < 50 fs additive jitter"),
    "LDO_1V3":    ("C403695",  "ADP1755ACPZ-R7",      "1.2 A low-noise LDO (AD9361 1.3 V rails)"),
    "FMC_MEZZ":   ("C2830435", "ASP-134604-01",       "FMC LPC mezzanine (plug), 160 pin"),
    # ---- processing board (board C) ----
    "ZYNQ":       ("C2988113", "XC7Z020-1CLG400C",    "Zynq-7020 SoC, CLG400"),
    "DDR3L":      ("C2841153", "NT5CC256M16ER-EKI",   "DDR3L 4 Gbit x16, 933 MHz, -40..95 C"),
    "QSPI":       ("C97522",   "W25Q256JVEIQ",        "256 Mbit QSPI NOR boot flash"),
    "ETH_PHY":    ("C187932",  "RTL8211F-CG",         "Gigabit Ethernet PHY, RGMII"),
    "RJ45":       ("C50933",   "HR911130C",           "Gigabit RJ45 with magnetics and LEDs"),
    "XTAL25":     ("C9006",    "X322525MOB4SI",       "25 MHz crystal for the PHY"),
    "OSC33":      ("C5346412", "OG1EL89CEI-112YLC-33.333M", "33.333 MHz PS_CLK oscillator"),
    "USB_UART":   ("C969151",  "CP2102N-A02-GQFN24R", "USB-UART console"),
    "USBC":       ("C165948",  "TYPE-C-31-M-12",      "USB-C receptacle (console)"),
    "MICROSD":    ("C91145",   "TF-01A",              "microSD socket"),
    "GNSS":       ("C4153167", "MAX-M10S-00B",        "u-blox M10 GNSS, timepulse for multi-node sync"),
    "FMC_CARRIER":("C2836665", "ASP-134603-01",       "FMC LPC carrier (socket), 160 pin"),
    "BUCK_3A":    ("C43590",   "TPS62130RGTR",        "3 A buck (all digital rails)"),
    "DDR_VTT":    ("C34771",   "TPS51200DRCR",        "DDR VTT / VREF termination regulator"),
    "LDO_3V3":    ("C404027",  "TLV75533PDBVR",       "3.3 V 500 mA LDO"),
    "DCJACK":     ("C84007",   "DC-005C-20A",         "12 V input jack, 3 A"),
}
