"""Board C - Zynq-7020 processing board (FMC LPC carrier for board B).

Zynq XC7Z020-1CLG400C + 512 MB DDR3L (x16) + 32 MB QSPI boot flash + microSD,
Gigabit Ethernet (RTL8211F, RGMII on MIO, 3.3 V), USB-UART console (CP2102N),
u-blox MAX-M10S GNSS (PPS for multi-node time sync), FMC LPC carrier for the digitizer.

Bank voltages: 500/501 (MIO) 3.3 V, 502 DDR 1.35 V, bank 0 3.3 V, bank 13 3.3 V,
banks 34/35 = VADJ 2.5 V (LVDS_25 for the AD9361 data, see tools/fmc.py).
Power: 12 V -> TPS62130 x5: 1.0 V -> 1.8 V -> (1.35 V, 3.3 V, 2.5 V); TPS51200 VTT/VREF.
Sequenced by PG -> EN chaining; PS_POR_B released after all PGs are good.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

from blocks import FP, FB, C, R, Refs, decouple, tps62130  # noqa: E402
from fmc import LPC, LVDS_PLAN, SE_PLAN, la  # noqa: E402
from schgen import Design, Part  # noqa: E402
from symlib import get_symbol, pins  # noqa: E402

ZYNQ = "prc:XC7Z020-1CLG400C"
ZNAMES = {p["name"] for p in pins(get_symbol(ZYNQ))}


def zio(bank, l, pol):
    """Zynq pin name for IO_L<l><P|N>_..._<bank>."""
    rx = re.compile(rf"^IO_L{l}{pol}_T\d(_[A-Z0-9_]+)?_{bank}$")
    m = [n for n in ZNAMES if rx.match(n)]
    if len(m) != 1:
        raise KeyError(f"bank {bank} L{l}{pol}: {m}")
    return m[0]


def carrier_pin(p):  # "C01" -> "c1"
    return p[0].lower() + str(int(p[1:]))


def build():
    d = Design("board_c", "Board C - Zynq-7020 processing board / FMC carrier")
    ref = Refs()
    ref.n.update({"U": 2, "J": 1})  # U1 Zynq, U2 DDR3L, J1 FMC
    z = {}  # Zynq pin name -> net

    # ================================================================ power
    pw = d.sheet("power", "Power: 12 V in, sequenced rails, DDR termination")
    pw.add(Part(ref("J"), "prc:DC-005C-20A", "12V DC", None, {"1": "VIN_RAW", "2": "GND", "3": "GND"},
                lcsc="C84007"))
    pw.add(Part(ref("F"), "Device:Polyfuse", "3A", "Fuse:Fuse_1206_3216Metric", {"1": "VIN_RAW", "2": "+12V"}))
    pw.add(Part(ref("D"), "Device:D_TVS", "SMBJ15A", "Diode_SMD:D_SMB", {"1": "+12V", "2": "GND"}))
    decouple(pw, ref, "+12V", ["22u:1206", "22u:1206"])
    tps62130(pw, ref, "+12V", "+1V0", 1.0, en="+12V", pg="PG_1V0", name="BUCK1V0")
    tps62130(pw, ref, "+12V", "+1V8", 1.8, en="PG_1V0", pg="PG_1V8", name="BUCK1V8")
    tps62130(pw, ref, "+12V", "+1V35", 1.35, en="PG_1V8", pg="PG_ALL", name="BUCK1V35")
    tps62130(pw, ref, "+12V", "+3V3", 3.3, en="PG_1V8", pg="PG_ALL", name="BUCK3V3")
    tps62130(pw, ref, "+12V", "VADJ", 2.5, en="PG_1V8", pg="PG_ALL", name="BUCK2V5")
    # DDR3L termination: VTT = VREF = 1.35 V / 2
    pw.add(Part(ref("U"), "Regulator_Linear:TPS51200DRC", "TPS51200DRCR", FP["VSON10"],
                {"VIN": "+3V3", "VLDOIN": "+1V35", "VO": "DDR_VTT", "VOSNS": "DDR_VTT", "REFIN": "DDR_REFIN",
                 "REFOUT": "DDR_VREF", "EN": "PG_ALL", "PGOOD": "NC_VTT_PG", "GND": "GND"}, lcsc="C34771"))
    pw.add(R(ref("R"), "10k", "+1V35", "DDR_REFIN", fields={"Tolerance": "1%"}))
    pw.add(R(ref("R"), "10k", "DDR_REFIN", "GND", fields={"Tolerance": "1%"}))
    decouple(pw, ref, "DDR_REFIN", ["100n"])
    decouple(pw, ref, "DDR_VTT", ["10u:0603", "10u:0603", "10u:0603"])
    decouple(pw, ref, "DDR_VREF", ["100n"])
    decouple(pw, ref, "+3V3", ["1u"])
    # FMC supply
    pw.add(Part(ref("F"), "Device:Polyfuse", "1A", "Fuse:Fuse_1206_3216Metric", {"1": "+12V", "2": "+12V_FMC"}))
    decouple(pw, ref, "+12V_FMC", ["10u:0805"])
    # power-on reset: all PG open-drain outputs wired together -> RC -> PS_POR_B
    pw.add(R(ref("R"), "10k", "PG_ALL", "+3V3"))
    pw.add(R(ref("R"), "1k", "PG_ALL", "PS_POR_B"))
    pw.add(C(ref("C"), "10u", "PS_POR_B", "GND", "0603"))  # ~10 ms after all PGs
    pw.add(Part(ref("SW"), "Switch:SW_Push", "POR", "Button_Switch_SMD:SW_SPST_TL3342", {"1": "PS_POR_B", "2": "GND"}))
    for i in range(4):
        pw.add(Part(ref("H"), "Mechanical:MountingHole_Pad", "M3", FP["HOLE"], {"1": "GND"}))
    for net in ("+1V0", "+1V8", "+1V35", "+3V3", "VADJ", "DDR_VTT"):
        pw.add(Part(ref("TP"), "Connector:TestPoint", net, FP["TP"], {"1": net}))
    pw.note("Sequence: 1.0 V (VCCINT/VCCPINT) -> 1.8 V (VCCAUX/VCCPAUX) -> 1.35 V, 3.3 V, 2.5 V -> PS_POR_B.")

    # ================================================================ Zynq power + config
    zp = d.sheet("zynq_power", "Zynq power pins, configuration, JTAG, XADC")
    for n, net in {"VCCINT": "+1V0", "VCCBRAM": "+1V0", "VCCPINT": "+1V0", "VCCAUX": "+1V8", "VCCPAUX": "+1V8",
                   "VCCPLL": "VCCPLL", "VCCO_DDR_502": "+1V35", "VCCO_MIO0_500": "+3V3", "VCCO_MIO1_501": "+3V3",
                   "VCCO_0": "+3V3", "VCCO_13": "+3V3", "VCCO_34": "VADJ", "VCCO_35": "VADJ", "GND": "GND",
                   "PS_DDR_VREF0_502": "DDR_VREF", "PS_DDR_VREF1_502": "DDR_VREF",
                   "CFGBVS_0": "+3V3", "RSVDVCC1": "+3V3", "RSVDVCC2": "+3V3", "RSVDVCC3": "+3V3", "RSVDGND": "GND",
                   "VCCBATT_0": "GND", "PROGRAM_B_0": "PROGRAM_B", "INIT_B_0": "INIT_B", "DONE_0": "DONE",
                   "TCK_0": "JTAG_TCK", "TMS_0": "JTAG_TMS", "TDI_0": "JTAG_TDI", "TDO_0": "JTAG_TDO",
                   "VCCADC_0": "VCCADC", "GNDADC_0": "GNDADC", "VREFP_0": "GNDADC", "VREFN_0": "GNDADC",
                   "VP_0": "GNDADC", "VN_0": "GNDADC",
                   "IO_L3P_T0_DQS_PUDC_B_34": "PUDC_B"}.items():
        z[n] = net
    zp.add(FB(ref("FB"), "+1V8", "VCCPLL", value="120R@100MHz"))
    decouple(zp, ref, "VCCPLL", ["10u:0603", "470n", "10n"])
    zp.add(FB(ref("FB"), "+1V8", "VCCADC"))
    zp.add(FB(ref("FB"), "GND", "GNDADC"))
    decouple(zp, ref, "VCCADC", ["100n"], gnd="GNDADC")
    decouple(zp, ref, "+1V0", ["22u:0805", "22u:0805", "4.7u:0603", "4.7u:0603"] + ["100n"] * 10)
    decouple(zp, ref, "+1V8", ["22u:0805", "4.7u:0603"] + ["100n"] * 8)
    decouple(zp, ref, "+1V35", ["22u:0805", "4.7u:0603"] + ["100n"] * 8)
    decouple(zp, ref, "+3V3", ["22u:0805", "4.7u:0603"] + ["100n"] * 8)
    decouple(zp, ref, "VADJ", ["22u:0805", "4.7u:0603"] + ["100n"] * 8)
    zp.add(R(ref("R"), "1k", "PUDC_B", "VADJ"))  # PUDC_B high: no pull-ups on PL I/O during configuration
    zp.add(R(ref("R"), "4.7k", "PROGRAM_B", "+3V3"))
    zp.add(R(ref("R"), "4.7k", "INIT_B", "+3V3"))
    zp.add(R(ref("R"), "330", "DONE", "+3V3"))
    zp.add(R(ref("R"), "1k", "DONE", "LED_DONE"))
    zp.add(Part(ref("D"), "Device:LED", "DONE", FP["LED0603"], {"A": "LED_DONE", "K": "GND"}))
    zp.add(Part(ref("J"), "Connector_Generic:Conn_02x07_Odd_Even", "JTAG (Xilinx 14-pin)", FP["JTAG14"],
                {"1": "GND", "3": "GND", "5": "GND", "7": "GND", "9": "GND", "11": "GND", "13": "GND",
                 "2": "+3V3", "4": "JTAG_TMS", "6": "JTAG_TCK", "8": "JTAG_TDO", "10": "JTAG_TDI",
                 "12": "NC_J12", "14": "NC_J14"}))
    zp.note("VCCBATT_0 tied to GND (no battery-backed key). XADC unused: VREFP/VREFN/VP/VN -> GNDADC (internal ref).")

    # ================================================================ PS: clock, reset, MIO
    ps = d.sheet("zynq_ps", "Zynq PS: clock, reset, boot straps, QSPI, SD, UART, I2C")
    z.update({"PS_CLK_500": "PS_CLK", "PS_POR_B_500": "PS_POR_B", "PS_SRST_B_501": "PS_SRST_B",
              "PS_MIO_VREF_501": "MIO_VREF"})
    ps.add(Part(ref("Y"), "prc:OG1EL89CEI-112YLC-33.333M", "33.333MHz", None,
                {"OE/NC": "+3V3", "GND": "GND", "VOUT": "PS_CLK_OSC", "VDD": "+3V3"}, lcsc="C5346412"))
    ps.add(R(ref("R"), "22", "PS_CLK_OSC", "PS_CLK"))
    decouple(ps, ref, "+3V3", ["100n"])
    ps.add(R(ref("R"), "4.7k", "PS_SRST_B", "+3V3"))
    ps.add(Part(ref("SW"), "Switch:SW_Push", "SRST", "Button_Switch_SMD:SW_SPST_TL3342", {"1": "PS_SRST_B", "2": "GND"}))
    ps.add(R(ref("R"), "1k", "+3V3", "MIO_VREF"))
    ps.add(R(ref("R"), "1k", "MIO_VREF", "GND"))
    mio = {0: "LED_PS", 1: "QSPI_CS", 2: "QSPI_IO0", 3: "QSPI_IO1", 4: "QSPI_IO2", 5: "QSPI_IO3", 6: "QSPI_CLK",
           7: "STRAP_MIO7", 8: "STRAP_MIO8", 9: "USER_BTN_PS", 10: "I2C0_SCL", 11: "I2C0_SDA",
           16: "RGMII_TXC", 17: "RGMII_TXD0", 18: "RGMII_TXD1", 19: "RGMII_TXD2", 20: "RGMII_TXD3",
           21: "RGMII_TXCTL", 22: "RGMII_RXC", 23: "RGMII_RXD0", 24: "RGMII_RXD1", 25: "RGMII_RXD2",
           26: "RGMII_RXD3", 27: "RGMII_RXCTL", 40: "SD_CLK_MIO", 41: "SD_CMD", 42: "SD_D0", 43: "SD_D1",
           44: "SD_D2", 45: "SD_D3", 46: "SD_CD", 47: "ETH_RSTN", 48: "UART_TX", 49: "UART_RX",
           52: "ETH_MDC", 53: "ETH_MDIO"}
    for k, net in mio.items():
        z[f"PS_MIO{k}_{500 if k < 16 else 501}"] = net
    # boot straps (20k): MIO2 JTAG cascade=0, MIO[5:3] boot mode (QSPI 100 / SD 110 with jumper),
    # MIO6 PLL enabled=0, MIO7/8 = bank 500/501 at 3.3 V (0)
    for net in ("QSPI_IO0", "QSPI_IO1", "QSPI_CLK", "STRAP_MIO7", "STRAP_MIO8", "QSPI_IO2"):
        ps.add(R(ref("R"), "20k", net, "GND"))
    ps.add(R(ref("R"), "20k", "QSPI_IO3", "+3V3"))
    ps.add(R(ref("R"), "4.7k", "+3V3", "BOOT_SD_J"))
    ps.add(Part(ref("J"), "Connector_Generic:Conn_01x02", "BOOT: open=QSPI, closed=SD",
                "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", {"1": "BOOT_SD_J", "2": "QSPI_IO2"}))
    # QSPI boot flash
    ps.add(Part(ref("U"), "prc:W25Q256JVEIQTR", "W25Q256JVEIQ", None,
                {"~{CS}": "QSPI_CS", "DO(IO1)": "QSPI_IO1", "WP#(IO2)": "QSPI_IO2", "DI(IO0)": "QSPI_IO0",
                 "CLK": "QSPI_CLK", "HOLD#orRESET#(IO3)": "QSPI_IO3", "VCC": "+3V3", "GND": "GND", "EP": "GND"},
                lcsc="C97522"))
    ps.add(R(ref("R"), "10k", "QSPI_CS", "+3V3"))
    decouple(ps, ref, "+3V3", ["100n"])
    # microSD (3.3 V, bank 501 at 3.3 V so no level shifter)
    ps.add(R(ref("R"), "33", "SD_CLK_MIO", "SD_CLK"))
    ps.add(Part(ref("J"), "prc:TF-01A", "microSD", None,
                {"DAT2(RSV)": "SD_D2", "CDDAT3(CS)": "SD_D3", "CMD(DI)": "SD_CMD", "VDD": "+3V3", "CLK(SCLK)": "SD_CLK",
                 "VSS": "GND", "DAT0(D0)": "SD_D0", "DAT1(RSV)": "SD_D1", "GND": "GND", "CD": "SD_CD"},
                lcsc="C91145"))
    for net in ("SD_CMD", "SD_D0", "SD_D1", "SD_D2", "SD_D3", "SD_CD"):
        ps.add(R(ref("R"), "10k", net, "+3V3"))
    decouple(ps, ref, "+3V3", ["10u:0603", "100n"])
    # I2C0 -> FMC (pull-ups)
    ps.add(R(ref("R"), "4.7k", "I2C0_SCL", "+3V3"))
    ps.add(R(ref("R"), "4.7k", "I2C0_SDA", "+3V3"))
    # LEDs / button
    ps.add(R(ref("R"), "1k", "LED_PS", "LED_PS_A"))
    ps.add(Part(ref("D"), "Device:LED", "PS", FP["LED0603"], {"A": "LED_PS_A", "K": "GND"}))
    ps.add(R(ref("R"), "10k", "USER_BTN_PS", "+3V3"))
    ps.add(Part(ref("SW"), "Switch:SW_Push", "USER", "Button_Switch_SMD:SW_SPST_TL3342", {"1": "USER_BTN_PS", "2": "GND"}))
    # USB-UART console
    ps.add(Part(ref("J"), "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C console",
                "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
                {"VBUS": "USB_VBUS", "GND": "GND", "SHIELD": "GND", "CC1": "USB_CC1", "CC2": "USB_CC2",
                 "D+": "USB_DP", "D-": "USB_DN"}, lcsc="C165948"))
    ps.add(R(ref("R"), "5.1k", "USB_CC1", "GND"))
    ps.add(R(ref("R"), "5.1k", "USB_CC2", "GND"))
    ps.add(Part(ref("U"), "prc:CP2102N-A02-GQFN24R", "CP2102N", None,
                {"GND": "GND", "D+": "USB_DP", "D-": "USB_DN", "VIO": "+3V3", "VDD": "+3V3", "VREGIN": "+3V3",
                 "VBUS": "USB_VBUS_SENSE", "RSTb": "CP_RSTB", "TXD": "UART_RX", "RXD": "UART_TX"}, lcsc="C969151"))
    ps.add(R(ref("R"), "22.1k", "USB_VBUS", "USB_VBUS_SENSE"))
    ps.add(R(ref("R"), "47.5k", "USB_VBUS_SENSE", "GND"))
    ps.add(R(ref("R"), "4.7k", "CP_RSTB", "+3V3"))
    decouple(ps, ref, "+3V3", ["1u", "100n"])
    decouple(ps, ref, "USB_VBUS", ["1u"])
    ps.note("Boot mode MIO[5:3]: QSPI = 1,0,0 (jumper open), SD = 1,1,0 (jumper closed). Console UART1 115200 8N1.")

    # ================================================================ DDR3L
    dd = d.sheet("ddr3", "DDR3L 512 MB x16 (PS DDR, bank 502)")
    dconn = {"VDD": "+1V35", "VDDQ": "+1V35", "VSS": "GND", "VSSQ": "GND", "VREFCA": "DDR_VREF",
             "VREFDQ": "DDR_VREF", "ZQ": "DDR_ZQ", "~{RESET}": "DDR_RESET_B", "CK": "DDR_CK_P", "~{CK}": "DDR_CK_N",
             "CKE": "DDR_CKE", "~{CS}": "DDR_CS_B", "~{RAS}": "DDR_RAS_B", "~{CAS_}": "DDR_CAS_B", "~{WE}": "DDR_WE_B",
             "ODT": "DDR_ODT", "BA0": "DDR_BA0", "BA1": "DDR_BA1", "BA2": "DDR_BA2",
             "DML": "DDR_DM0", "DMU": "DDR_DM1", "DQSL": "DDR_DQS0_P", "~{DQSL}": "DDR_DQS0_N",
             "DQSU": "DDR_DQS1_P", "~{DQSU}": "DDR_DQS1_N"}
    for k in range(15):
        dconn[{10: "A10/AP", 12: "A12/~{BC}"}.get(k, f"A{k}")] = f"DDR_A{k}"
    for k in range(8):
        dconn[f"DQL{k}"] = f"DDR_DQ{k}"
        dconn[f"DQU{k}"] = f"DDR_DQ{k+8}"
    dd.add(Part("U2", "prc:NT5CC256M16ER-EKI", "NT5CC256M16ER-EKI", None, dconn, lcsc="C2841153", match="name"))
    z.update({"PS_DDR_CKP_502": "DDR_CK_P", "PS_DDR_CKN_502": "DDR_CK_N", "PS_DDR_CKE_502": "DDR_CKE",
              "PS_DDR_CS_B_502": "DDR_CS_B", "PS_DDR_RAS_B_502": "DDR_RAS_B", "PS_DDR_CAS_B_502": "DDR_CAS_B",
              "PS_DDR_WE_B_502": "DDR_WE_B", "PS_DDR_ODT_502": "DDR_ODT", "PS_DDR_DRST_B_502": "DDR_RESET_B",
              "PS_DDR_VRN_502": "DDR_VRN", "PS_DDR_VRP_502": "DDR_VRP",
              "PS_DDR_DM0_502": "DDR_DM0", "PS_DDR_DM1_502": "DDR_DM1",
              "PS_DDR_DQS_P0_502": "DDR_DQS0_P", "PS_DDR_DQS_N0_502": "DDR_DQS0_N",
              "PS_DDR_DQS_P1_502": "DDR_DQS1_P", "PS_DDR_DQS_N1_502": "DDR_DQS1_N"})
    for k in range(3):
        z[f"PS_DDR_BA{k}_502"] = f"DDR_BA{k}"
    for k in range(15):
        z[f"PS_DDR_A{k}_502"] = f"DDR_A{k}"
    for k in range(16):
        z[f"PS_DDR_DQ{k}_502"] = f"DDR_DQ{k}"
    dd.add(R(ref("R"), "240", "DDR_ZQ", "GND", fields={"Tolerance": "1%"}))
    dd.add(R(ref("R"), "4.7k", "DDR_RESET_B", "GND"))
    dd.add(R(ref("R"), "80.6", "DDR_VRN", "+1V35", fields={"Tolerance": "1%"}))
    dd.add(R(ref("R"), "80.6", "DDR_VRP", "GND", fields={"Tolerance": "1%"}))
    dd.add(R(ref("R"), "100", "DDR_CK_P", "DDR_CK_N"))  # differential clock termination at the DRAM
    # fly-by end termination of address/command/control to VTT
    for net in [f"DDR_A{k}" for k in range(15)] + [f"DDR_BA{k}" for k in range(3)] + \
               ["DDR_RAS_B", "DDR_CAS_B", "DDR_WE_B", "DDR_CS_B", "DDR_CKE", "DDR_ODT"]:
        dd.add(R(ref("R"), "40.2", net, "DDR_VTT"))
    decouple(dd, ref, "+1V35", ["22u:0805", "10u:0603"] + ["100n"] * 10)
    decouple(dd, ref, "DDR_VREF", ["100n", "100n"])
    decouple(dd, ref, "DDR_VTT", ["100n"] * 6)
    dd.note("16-bit configuration: PS_DDR DQ16-31, DM2/3, DQS2/3 left unconnected (verify with Xilinx UG933).")
    dd.note("Route DQ byte lanes length-matched to their DQS (+/- 0.5 mm); address/command fly-by to VTT.")

    # ================================================================ Ethernet
    et = d.sheet("ethernet", "Gigabit Ethernet: RTL8211F (RGMII 3.3 V) + HR911130C")
    et.add(Part(ref("U"), "prc:RTL8211F-CG", "RTL8211F-CG", None,
                {"MDIP0": "ETH_D0P", "MDIN0": "ETH_D0N", "MDIP1": "ETH_D1P", "MDIN1": "ETH_D1N",
                 "MDIP2": "ETH_D2P", "MDIN2": "ETH_D2N", "MDIP3": "ETH_D3P", "MDIN3": "ETH_D3N",
                 "AVDD10": "PHY_AVDD10", "AVDD33": "+3V3", "DVDD33": "+3V3", "DVDD_RG": "+3V3",
                 "DVDD10": "PHY_1V0", "REG_OUT/LDO_OUT": "PHY_REG_OUT", "PHYRSTB": "ETH_RSTN",
                 "MDC": "ETH_MDC", "MDIO": "ETH_MDIO",
                 "TXD0": "RGMII_TXD0", "TXD1": "RGMII_TXD1", "TXD2": "RGMII_TXD2", "TXD3": "RGMII_TXD3",
                 "TXCTL": "RGMII_TXCTL", "TXC": "RGMII_TXC",
                 "RXDLY/RXD0": "PHY_RXD0", "TXDLY/RXD1": "PHY_RXD1", "PLLOFF/RXD2": "PHY_RXD2",
                 "PHYAD0/RXD3": "PHY_RXD3", "PHYAD2/RXCTL": "PHY_RXCTL", "PHYAD1/RXC": "PHY_RXC",
                 "INTB/PMEB": "PHY_INTB", "CFG_EXT/LED0": "PHY_CFG_EXT", "CFG_LDO0/LED1": "PHY_CFG_LDO0",
                 "CFG_LDO1/LED2": "PHY_CFG_LDO1", "XTAL_IN": "PHY_XI", "XTAL_OUT/EXT_CLK": "PHY_XO",
                 "RSET": "PHY_RSET", "GND": "GND"}, lcsc="C187932"))
    # RX lines: 22R series (source termination at PHY) + strap resistors on the PHY side
    for a, b in (("PHY_RXD0", "RGMII_RXD0"), ("PHY_RXD1", "RGMII_RXD1"), ("PHY_RXD2", "RGMII_RXD2"),
                 ("PHY_RXD3", "RGMII_RXD3"), ("PHY_RXCTL", "RGMII_RXCTL"), ("PHY_RXC", "RGMII_RXC")):
        et.add(R(ref("R"), "22", a, b))
    straps = {"PHY_RXD0": "+3V3",   # RXDLY = 1: PHY adds 2 ns RX clock delay
              "PHY_RXD1": "+3V3",   # TXDLY = 1: PHY adds 2 ns TX clock delay
              "PHY_RXD2": "GND",    # PLLOFF = 0
              "PHY_RXD3": "+3V3",   # PHYAD0 = 1 -> PHY address 1
              "PHY_RXC": "GND", "PHY_RXCTL": "GND",  # PHYAD1/2 = 0
              "PHY_CFG_EXT": "GND", "PHY_CFG_LDO0": "GND", "PHY_CFG_LDO1": "GND"}  # RGMII I/O at 3.3 V
    for net, rail in straps.items():
        et.add(R(ref("R"), "4.7k", net, rail))
    et.add(R(ref("R"), "4.7k", "PHY_INTB", "+3V3"))
    et.add(R(ref("R"), "1.5k", "ETH_MDIO", "+3V3"))
    et.add(R(ref("R"), "10k", "ETH_RSTN", "+3V3"))
    et.add(C(ref("C"), "100n", "ETH_RSTN", "GND"))
    et.add(R(ref("R"), "2.49k", "PHY_RSET", "GND", fields={"Tolerance": "1%"}))
    et.add(Part(ref("Y"), "prc:X322525MOB4SI", "25MHz", None, {"OSC1": "PHY_XI", "OSC2": "PHY_XO", "GND": "GND"},
                lcsc="C9006"))
    et.add(C(ref("C"), "18p", "PHY_XI", "GND"))
    et.add(C(ref("C"), "18p", "PHY_XO", "GND"))
    # internal switching regulator: REG_OUT -> 2.2 uH -> 1.0 V core
    et.add(Part(ref("L"), "Device:L", "2.2u", FP["L0603"], {"1": "PHY_REG_OUT", "2": "PHY_1V0"}))
    decouple(et, ref, "PHY_1V0", ["22u:0805", "100n", "100n"])
    et.add(FB(ref("FB"), "PHY_1V0", "PHY_AVDD10"))
    decouple(et, ref, "PHY_AVDD10", ["1u", "100n", "100n", "100n"])
    decouple(et, ref, "+3V3", ["10u:0603", "100n", "100n", "100n"])
    et.add(Part(ref("J"), "prc:HR911130C", "HR911130C", None,
                {"MDI0+": "ETH_D0P", "MDI0-": "ETH_D0N", "MDI1+": "ETH_D1P", "MDI1-": "ETH_D1N",
                 "MDI2+": "ETH_D2P", "MDI2-": "ETH_D2N", "MDI3+": "ETH_D3P", "MDI3-": "ETH_D3N",
                 "P1": "ETH_CT", "P10": "GND", "SHIELD0": "GND", "SHIELD1": "GND"}, lcsc="C50933"))
    decouple(et, ref, "ETH_CT", ["100n", "100n"])
    et.note("Magjack P1 = centre taps (AC-decoupled; RTL8211F is a voltage-mode driver), P10 = GND. LEDs unused. VERIFY.")

    # ================================================================ GNSS
    gn = d.sheet("gnss", "GNSS: u-blox MAX-M10S, PPS to PL for time sync")
    gn.add(Part(ref("U"), "RF_GPS:MAX-M10S", "MAX-M10S-00B", "RF_GPS:ublox_MAX",
                {"GND": "GND", "TXD": "GNSS_TXD", "RXD": "GNSS_RXD", "TIMEPULSE": "GNSS_PPS", "V_BCKP": "+3V3",
                 "VCC_IO": "+3V3", "VCC": "+3V3", "~{RESET}": "GNSS_RESETN", "RF_IN": "GNSS_RF",
                 "VCC_RF": "GNSS_VCCRF"}, lcsc="C4153167"))
    gn.add(R(ref("R"), "10", "GNSS_VCCRF", "GNSS_BIAS"))
    gn.add(Part(ref("L"), "Device:L", "47n", FP["L0402"], {"1": "GNSS_BIAS", "2": "GNSS_ANT"}))
    gn.add(C(ref("C"), "47p", "GNSS_ANT", "GNSS_RF"))
    gn.add(Part(ref("J"), "prc:BWSMA-KE-Z001", "GNSS ANT", None,
                {"5": "GNSS_ANT", "1": "GND", "2": "GND", "3": "GND", "4": "GND"}, lcsc="C496549"))
    gn.add(R(ref("R"), "10k", "GNSS_RESETN", "+3V3"))
    decouple(gn, ref, "+3V3", ["10u:0603", "100n"])
    decouple(gn, ref, "GNSS_VCCRF", ["100n"])
    gn.note("Active antenna powered from VCC_RF via 10 ohm + 47 nH. PPS -> bank 13 SRCC pin for timestamping.")
    z.update({zio(13, 11, "P"): "GNSS_PPS", zio(13, 11, "N"): "GNSS_TXD", zio(13, 12, "P"): "GNSS_RXD",
              zio(13, 12, "N"): "GNSS_RESETN", zio(13, 13, "P"): "LED_PL0", zio(13, 13, "N"): "LED_PL1",
              zio(13, 14, "P"): "FMC_PRSNT_L"})
    for led in ("LED_PL0", "LED_PL1"):
        gn.add(R(ref("R"), "1k", led, led + "_A"))
        gn.add(Part(ref("D"), "Device:LED", led, FP["LED0603"], {"A": led + "_A", "K": "GND"}))

    # ================================================================ FMC carrier + PL banks
    fm = d.sheet("fmc", "FMC LPC carrier: digitizer LVDS on banks 34/35 (2.5 V)")
    bank35 = [l for l in range(1, 25) if l not in (11, 12, 13)]
    bank34 = [l for l in range(1, 25) if l not in (3, 12)]
    fixed = {"AD1_DCLK": (35, 12), "AD2_DCLK": (35, 13), "AD3_DCLK": (34, 12)}
    alloc = {}
    for name in LVDS_PLAN:
        if name in fixed:
            alloc[name] = fixed[name]
        elif name.startswith(("AD1", "AD2")):
            alloc[name] = (35, bank35.pop(0))
        else:
            alloc[name] = (34, bank34.pop(0))
    se_pairs = {}
    for name, (n_la, pol) in SE_PLAN.items():
        se_pairs.setdefault(n_la, []).append((name, pol))
    for n_la in sorted(se_pairs):
        bank_l = bank34.pop(0)
        for name, pol in se_pairs[n_la]:
            alloc[(name, pol)] = (34, bank_l)
    conn = {}
    for pin, sig in LPC.items():
        cp = carrier_pin(pin)
        if sig == "GND" or sig in ("GA0", "GA1"):
            conn[cp] = "GND"
        elif sig == "12P0V":
            conn[cp] = "+12V_FMC"
        elif sig in ("3P3V", "3P3VAUX"):
            conn[cp] = "+3V3"
        elif sig == "VADJ":
            conn[cp] = "VADJ"
        elif sig == "PG_C2M":
            conn[cp] = "PG_ALL"
        elif sig == "PRSNT_M2C_L":
            conn[cp] = "FMC_PRSNT_L"
        elif sig == "SCL":
            conn[cp] = "I2C0_SCL"
        elif sig == "SDA":
            conn[cp] = "I2C0_SDA"
        elif sig == "CLK0_M2C_P":
            conn[cp] = "FPGA_REFCLK_P"
        elif sig == "CLK0_M2C_N":
            conn[cp] = "FPGA_REFCLK_N"
    z[zio(35, 11, "P")] = "FPGA_REFCLK_P"
    z[zio(35, 11, "N")] = "FPGA_REFCLK_N"
    for name, n_la in LVDS_PLAN.items():
        bank, l = alloc[name]
        for pol in ("P", "N"):
            net = f"{name}_{pol}"
            conn[carrier_pin(la(n_la, pol))] = net
            z[zio(bank, l, pol)] = net
    for name, (n_la, pol) in SE_PLAN.items():
        if name.startswith("SPARE"):
            continue
        bank, l = alloc[(name, pol)]
        conn[carrier_pin(la(n_la, pol))] = name
        z[zio(bank, l, pol)] = name
    fm.add(Part("J1", "prc:ASP-134603-01", "FMC LPC (carrier)", None, conn, lcsc="C2836665"))
    fm.add(R(ref("R"), "10k", "FMC_PRSNT_L", "+3V3"))
    decouple(fm, ref, "+12V_FMC", ["10u:0805"])
    decouple(fm, ref, "VADJ", ["10u:0603", "100n"])
    fm.note("LVDS pairs: 100 ohm differential, all 9 pairs of each AD9361 matched to +/- 1 mm.")
    alloc_txt = ", ".join(f"{k}->B{v[0]}.L{v[1]}" for k, v in alloc.items() if isinstance(k, str) and "DCLK" in k)
    fm.note("Clock-capable pins: " + alloc_txt + ", FPGA_REFCLK->B35.L11 (SRCC).")

    # ================================================================ Zynq symbol (all units)
    zs = d.sheet("zynq", "Zynq XC7Z020-1CLG400C (all units)")
    zs.add(Part("U1", ZYNQ, "XC7Z020-1CLG400C", None, z, lcsc="C2988113", match="name"))
    return d


if __name__ == "__main__":
    d = build()
    for pr in d.check():
        print("CHECK:", pr)
    out = d.write(os.path.join(HERE, "..", "board_c"))
    print(f"wrote {out}: {len(d.parts())} parts, {len(d.nets())} nets")
