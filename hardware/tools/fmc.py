"""VITA 57.1 FMC LPC connector pin map (rows C, D, G, H), shared by mezzanine and carrier.

Signal names follow the standard. Pin numbers use the zero-padded form of the
LCSC/EasyEDA symbols ("C01"). VERIFY against ANSI/VITA 57.1 Table 6 before fab.
"""

LPC = {}


def _row(row, names):
    for i, n in enumerate(names, start=1):
        LPC[f"{row}{i:02d}"] = n


_row("C", ["GND", "DP0_C2M_P", "DP0_C2M_N", "GND", "GND", "DP0_M2C_P", "DP0_M2C_N", "GND", "GND",
           "LA06_P", "LA06_N", "GND", "GND", "LA10_P", "LA10_N", "GND", "GND", "LA14_P", "LA14_N", "GND",
           "GND", "LA18_P_CC", "LA18_N_CC", "GND", "GND", "LA27_P", "LA27_N", "GND", "GND", "SCL", "SDA",
           "GND", "GND", "GA0", "12P0V", "GND", "12P0V", "GND", "3P3V", "GND"])
_row("D", ["PG_C2M", "GND", "GND", "GBTCLK0_M2C_P", "GBTCLK0_M2C_N", "GND", "GND", "LA01_P_CC", "LA01_N_CC",
           "GND", "LA05_P", "LA05_N", "GND", "LA09_P", "LA09_N", "GND", "LA13_P", "LA13_N", "GND", "LA17_P_CC",
           "LA17_N_CC", "GND", "LA23_P", "LA23_N", "GND", "LA26_P", "LA26_N", "GND", "TCK", "TDI", "TDO",
           "3P3VAUX", "TMS", "TRST_L", "GA1", "3P3V", "GND", "3P3V", "GND", "3P3V"])
_row("G", ["GND", "CLK1_M2C_P", "CLK1_M2C_N", "GND", "GND", "LA00_P_CC", "LA00_N_CC", "GND", "LA03_P", "LA03_N",
           "GND", "LA08_P", "LA08_N", "GND", "LA12_P", "LA12_N", "GND", "LA16_P", "LA16_N", "GND", "LA20_P",
           "LA20_N", "GND", "LA22_P", "LA22_N", "GND", "LA25_P", "LA25_N", "GND", "LA29_P", "LA29_N", "GND",
           "LA31_P", "LA31_N", "GND", "LA33_P", "LA33_N", "GND", "VADJ", "GND"])
_row("H", ["VREF_A_M2C", "PRSNT_M2C_L", "GND", "CLK0_M2C_P", "CLK0_M2C_N", "GND", "LA02_P", "LA02_N", "GND",
           "LA04_P", "LA04_N", "GND", "LA07_P", "LA07_N", "GND", "LA11_P", "LA11_N", "GND", "LA15_P", "LA15_N",
           "GND", "LA19_P", "LA19_N", "GND", "LA21_P", "LA21_N", "GND", "LA24_P", "LA24_N", "GND", "LA28_P",
           "LA28_N", "GND", "LA30_P", "LA30_N", "GND", "LA32_P", "LA32_N", "GND", "VADJ"])

BY_NAME = {}
for pin, name in LPC.items():
    BY_NAME.setdefault(name, []).append(pin)


def la(n, pol):
    """Pin for LAnn_P / LAnn_N (handles the _CC suffix)."""
    for suffix in ("", "_CC"):
        key = f"LA{n:02d}_{pol}{suffix}"
        if key in BY_NAME:
            return BY_NAME[key][0]
    raise KeyError(n)


# ---- Radar digitizer signal plan (shared by board B and board C) ----
# Each AD9361 uses 9 LVDS pairs: DATA_CLK (on a CC pair), RX_FRAME, RX_D0..5, FB_CLK.
# AD1 + AD2 land in carrier bank 35, AD3 in bank 34, so each chip's clock and data share a bank.
LVDS_PLAN = {}
for chip, (clk, frame, data, fb) in {1: (0, 2, [3, 4, 5, 6, 7, 8], 9),
                                     2: (1, 10, [11, 12, 13, 14, 15, 16], 19),
                                     3: (17, 18, [20, 21, 22, 23, 24, 25], 26)}.items():
    LVDS_PLAN[f"AD{chip}_DCLK"] = clk
    LVDS_PLAN[f"AD{chip}_FRAME"] = frame
    for k, la_n in enumerate(data):
        LVDS_PLAN[f"AD{chip}_RXD{k}"] = la_n
    LVDS_PLAN[f"AD{chip}_FBCLK"] = fb

# Single-ended control on the remaining pairs (2.5 V CMOS, VADJ)
SE_PLAN = {
    "SPI_CLK": (27, "P"), "SPI_DI": (27, "N"), "SPI_DO": (28, "P"), "SPI_ENB1": (28, "N"),
    "SPI_ENB2": (29, "P"), "SPI_ENB3": (29, "N"), "AD_RESETB": (30, "P"), "AD_ENABLE": (30, "N"),
    "AD_TXNRX": (31, "P"), "AD_SYNC_IN": (31, "N"), "CAL_EN_FPGA": (32, "P"), "AD_EN_AGC": (32, "N"),
    "SPARE0": (33, "P"), "SPARE1": (33, "N"),
}
