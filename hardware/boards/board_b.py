"""Board B - 6-channel coherent digitizer: 3 x AD9361 on an FMC LPC mezzanine.

Channels: CH0 (reference) -> AD1 RX1A, CH1 -> AD1 RX2A, CH2 -> AD2 RX1A, CH3 -> AD2 RX2A,
          CH4 -> AD3 RX1A, CH5 -> AD3 RX2A.  (TX paths unused.)
Coherence: one 40 MHz TCXO (or external reference) -> LMK1C1104 1:4 buffer -> XTALN of all three
           AD9361 + FPGA reference. Multi-chip sync (MCS) pulse SYNC_IN fanned out from the FPGA.
           Residual LO phase offsets between chips are measured with board A's noise source.
Interface: AD9361 LVDS mode, RX only, 9 pairs per chip on FMC LA pairs (see tools/fmc.py).
Power:     FMC 12P0V -> TPS62130 1.8 V -> 3 x ADP1755 1.3 V (one per AD9361),
           FMC 3P3V -> TCXO, VDD_GPO, 2.5 V clock LDO; FMC VADJ (must be 2.5 V) -> VDD_INTERFACE.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

from blocks import FP, FB, C, R, Refs, adp1755, decouple, ldo_tlv755, tps62130  # noqa: E402
from fmc import LPC, LVDS_PLAN, SE_PLAN, la  # noqa: E402
from schgen import Design, Part  # noqa: E402

AD_LIB = "prc:AD9361BBCZ"
GROUP_RF = ["VDDA1P3_RX_RF", "VDDA1P3_RX_TX", "VDDA1P3_RX_LO", "VDDA1P3_TX_LO", "VDDA1P3_TX_LO_BUFFER"]
GROUP_SYN = ["VDDA1P3_RX_SYNTH", "VDDA1P3_TX_SYNTH", "VDDA1P3_RX_VCO_LDO", "VDDA1P3_TX_VCO_LDO"]
UNUSED_NC = ["RX1B_P", "RX1B_N", "RX1C_P", "RX1C_N", "RX2B_P", "RX2B_N", "RX2C_P", "RX2C_N",
             "TX1A_P", "TX1A_N", "TX1B_P", "TX1B_N", "TX2A_P", "TX2A_N", "TX2B_P", "TX2B_N",
             "TX_MON1", "TX_MON2", "TX_EXT_LO_IN", "RX_EXT_LO_IN", "AUXDAC1", "AUXDAC2", "AUXADC",
             "XTALP", "CLK_OUT", "GPO_0", "GPO_1", "GPO_2", "GPO_3", "NC",
             "CTRL_OUT0", "CTRL_OUT1", "CTRL_OUT2", "CTRL_OUT3", "CTRL_OUT4", "CTRL_OUT5", "CTRL_OUT6",
             "CTRL_OUT7", "TX_FRAME_P", "TX_FRAME_N"] + \
    [f"P0_D{2*k+1}/TX_D{k}_P" for k in range(6)] + [f"P0_D{2*k}/TX_D{k}_N" for k in range(6)]


def ad9361(sheet, ref, chip):
    p = f"AD{chip}"
    ch_a, ch_b = 2 * (chip - 1), 2 * (chip - 1) + 1
    conn = {"VSSA": "GND", "VSSD": "GND", "TEST/ENABLE": "GND", "EN_AGC": "AD_EN_AGC",
            "CTRL_IN0": "GND", "CTRL_IN1": "GND", "CTRL_IN2": "GND", "CTRL_IN3": "GND",
            "RBIAS": f"{p}_RBIAS", "XTALN": f"{p}_XTALN",
            "RX1A_P": f"CH{ch_a}_RXP", "RX1A_N": f"CH{ch_a}_RXN", "RX2A_P": f"CH{ch_b}_RXP", "RX2A_N": f"CH{ch_b}_RXN",
            "SPI_CLK": "SPI_CLK", "SPI_DI": "SPI_DI", "SPI_DO": "SPI_DO", "SPI_ENB": f"SPI_ENB{chip}",
            "RESETB": "AD_RESETB", "ENABLE": "AD_ENABLE", "TXNRX": "AD_TXNRX", "SYNC_IN": f"{p}_SYNC",
            "DATA_CLK_P": f"{p}_DCLK_P", "DATA_CLK_N": f"{p}_DCLK_N",
            "RX_FRAME_P": f"{p}_FRAME_P", "RX_FRAME_N": f"{p}_FRAME_N",
            "FB_CLK_P": f"{p}_FBCLK_P", "FB_CLK_N": f"{p}_FBCLK_N",
            "VDD_INTERFACE": "VADJ", "VDD_GPO": "+3V3",
            "VDDD1P3_DIG": f"{p}_1V3_DIG", "VDDA1P3_BB": f"{p}_1V3_BB",
            "RX_VCO_LDO_OUT": f"{p}_RXVCO_1V1", "VDDA1P1_RX_VCO": f"{p}_RXVCO_1V1",
            "TX_VCO_LDO_OUT": f"{p}_TXVCO_1V1", "VDDA1P1_TX_VCO": f"{p}_TXVCO_1V1"}
    for k in range(6):  # LVDS RX data: RX_Dk_P = P1_D(2k+1), RX_Dk_N = P1_D(2k)
        conn[f"P1_D{2*k+1}/RX_D{k}_P"] = f"{p}_RXD{k}_P"
        conn[f"P1_D{2*k}/RX_D{k}_N"] = f"{p}_RXD{k}_N"
    for n in GROUP_RF:
        conn[n] = f"{p}_1V3_RF"
    for n in GROUP_SYN:
        conn[n] = f"{p}_1V3_SYN"
    u = Part(f"U{chip}", AD_LIB, "AD9361BBCZ", None, conn, lcsc="C515884", mpn="AD9361BBCZ", match="name")
    for n in UNUSED_NC:
        pass  # left unconnected -> no-connect flags
    sheet.add(u)
    sheet.add(R(ref("R"), "14.3k", f"{p}_RBIAS", "GND", fields={"Tolerance": "1%"}))
    sheet.add(R(ref("R"), "22", "AD_SYNC_IN", f"{p}_SYNC"))  # MCS fan-out, matched lengths
    sheet.add(R(ref("R"), "10k", f"SPI_ENB{chip}", "VADJ"))
    # ---- per-chip 1.3 V tree: LDO -> ferrite beads -> rail groups (ADI FMCOMMS2-style split)
    for grp in ("RF", "SYN", "BB", "DIG"):
        sheet.add(FB(ref("FB"), f"{p}_1V3", f"{p}_1V3_{grp}"))
    decouple(sheet, ref, f"{p}_1V3_RF", ["1u", "100n", "100n", "100n", "100n", "100n"])
    decouple(sheet, ref, f"{p}_1V3_SYN", ["1u", "100n", "100n", "100n", "100n"])
    decouple(sheet, ref, f"{p}_1V3_BB", ["1u", "100n"])
    decouple(sheet, ref, f"{p}_1V3_DIG", ["1u", "100n", "100n"])
    decouple(sheet, ref, f"{p}_RXVCO_1V1", ["1u", "100n"])
    decouple(sheet, ref, f"{p}_TXVCO_1V1", ["1u", "100n"])
    decouple(sheet, ref, "VADJ", ["100n"])
    decouple(sheet, ref, "+3V3", ["100n"])
    return u


# Band variants (one receiver stack per band, see docs/DESIGN.md 3.1). Only the input balun and the
# AC-coupling capacitors change. TCM1-63AX+ (10 MHz-6 GHz, 50:50) is the balun ADI uses in front of the
# AD9361 on AD-FMCOMMS3; pins 3 = primary dot (unbalanced in), 2 = primary/GND, 6 = secondary dot, 4 = secondary,
# 1/5 not used. Coupling caps follow the board A2 DC-block values for the band.
BAND = "uhf"
BAND_PARTS = {
    "uhf": dict(cap="100p"),
    "mid": dict(cap="33p"),
    "high": dict(cap="22p"),
    "n78": dict(cap="10p"),
}


def rf_input(sheet, ref, ch):
    """SMA -> optional pi attenuator (0 ohm fitted) -> 1:1 balun -> AC coupling -> AD9361 RXxA."""
    n = f"CH{ch}"
    cap = BAND_PARTS[BAND]["cap"]
    sheet.add(Part(ref("J"), "prc:BWSMA-KE-Z001", f"RF_IN{ch}", None,
                   {"5": f"{n}_IN", "1": "GND", "2": "GND", "3": "GND", "4": "GND"}, lcsc="C496549"))
    sheet.add(R(ref("R"), "DNP", f"{n}_IN", "GND", dnp=True))
    sheet.add(R(ref("R"), "0", f"{n}_IN", f"{n}_BAL"))
    sheet.add(R(ref("R"), "DNP", f"{n}_BAL", "GND", dnp=True))
    if BAND == "uhf":
        # TDK ATB2012-50011 1:1 balun, 40-860 MHz. Pads: 1 unbalanced, 2 GND, 3/4 balanced (verify datasheet).
        sheet.add(Part(ref("T"), "Device:Transformer_1P_1S", "ATB2012-50011", "prc:XFMR-SMD_ATB2012-50011-T000",
                       {"1": f"{n}_BAL", "2": "GND", "4": f"{n}_BP", "3": f"{n}_BN"}, lcsc="C92015",
                       mpn="ATB2012-50011-T000"))
    else:
        sheet.add(Part(ref("T"), "prc:TCM1-63AX+", "TCM1-63AX+", None,
                       {"PRIMARYDOT": f"{n}_BAL", "PRIMARY": "GND", "SECONDARY-DOT": f"{n}_BP",
                        "SECONDARY": f"{n}_BN", "NOTUSED": f"NC_{n}_T"}, lcsc="C494678", mpn="TCM1-63AX+",
                       match="name"))
    sheet.add(C(ref("C"), cap, f"{n}_BP", f"{n}_RXP"))
    sheet.add(C(ref("C"), cap, f"{n}_BN", f"{n}_RXN"))
    sheet.add(C(ref("C"), "DNP", f"{n}_RXP", f"{n}_RXN", dnp=True))  # differential match position


def build():
    d = Design("board_b", "Board B - 6-channel coherent digitizer (3 x AD9361, FMC LPC)")
    ref = Refs()
    ref.n.update({"U": 3, "J": 1})  # U1-U3 = AD9361s, J1 = FMC connector

    # ---------------------------------------------------------------- AD9361s
    for chip in (1, 2, 3):
        sh = d.sheet(f"ad9361_{chip}", f"AD9361 #{chip} (CH{2*chip-2}, CH{2*chip-1})")
        ad9361(sh, ref, chip)
        sh.note("Pin-strap/unused-pin handling follows ADI UG-570 and the AD-FMCOMMS2 reference design; verify.")
        if chip == 1:
            sh.add(R(ref("R"), "10k", "AD_RESETB", "VADJ"))
            sh.add(R(ref("R"), "10k", "AD_EN_AGC", "GND"))
            sh.add(R(ref("R"), "10k", "AD_ENABLE", "GND"))
            sh.add(R(ref("R"), "10k", "AD_TXNRX", "GND"))

    # ---------------------------------------------------------------- RF inputs
    rf = d.sheet("rf_inputs", "RF inputs: SMA, attenuator positions, baluns")
    for ch in range(6):
        rf_input(rf, ref, ch)
    rf.note("CH0 = reference antenna. Route each P/N pair as 100 ohm differential, equal lengths for all 6 channels.")

    # ---------------------------------------------------------------- clock
    ck = d.sheet("clock", "40 MHz reference distribution")
    ck.add(Part(ref("Y"), "prc:BT0507BH3I507BN40B", "40MHz TCXO 0.5ppm", None,
                {"VDD": "+3V3", "GND": "GND", "FO": "TCXO_OUT", "VCON": "TCXO_VC"}, lcsc="C516506"))
    ck.add(R(ref("R"), "10k", "+3V3", "TCXO_VC"))
    ck.add(R(ref("R"), "10k", "TCXO_VC", "GND"))
    decouple(ck, ref, "+3V3", ["100n", "10u:0603"])
    # select TCXO (fitted) or external 40 MHz reference SMA (DNP): level shift 3.3 V -> 2.5 V
    ck.add(R(ref("R"), "470", "TCXO_OUT", "REF_SEL"))
    ck.add(Part(ref("J"), "prc:BWSMA-KE-Z001", "EXT_REF", None,
                {"5": "EXT_REF", "1": "GND", "2": "GND", "3": "GND", "4": "GND"}, lcsc="C496549"))
    ck.add(R(ref("R"), "DNP", "EXT_REF", "REF_SEL", dnp=True))
    ck.add(R(ref("R"), "1.5k", "REF_SEL", "GND"))
    ldo_tlv755(ck, ref, "+3V3", "+2V5_CLK", 2.5)
    ck.add(Part(ref("U"), "prc:LMK1C1104PWR", "LMK1C1104PWR", None,
                {"CLKIN": "REF_SEL", "1G": "+2V5_CLK", "VDD": "+2V5_CLK", "GND": "GND",
                 "Y0": "CLK_Y0", "Y1": "CLK_Y1", "Y2": "CLK_Y2", "Y3": "CLK_Y3"}, lcsc="C1855734"))
    decouple(ck, ref, "+2V5_CLK", ["100n", "1u"])
    for chip, y in ((1, "CLK_Y0"), (2, "CLK_Y1"), (3, "CLK_Y2")):
        p = f"AD{chip}"
        # 2.5 V CMOS -> ~1.0 Vpp AC-coupled into XTALN (max 1.3 Vpp). Equal trace lengths.
        ck.add(R(ref("R"), "33", y, f"{p}_CK_A"))
        ck.add(R(ref("R"), "120", f"{p}_CK_A", f"{p}_CK_B"))
        ck.add(R(ref("R"), "100", f"{p}_CK_B", "GND"))
        ck.add(C(ref("C"), "100n", f"{p}_CK_B", f"{p}_XTALN"))
    ck.add(R(ref("R"), "33", "CLK_Y3", "FPGA_REFCLK"))
    ck.note("All three XTALN traces must be length-matched (< 1 mm). FPGA_REFCLK -> FMC CLK0_M2C_P.")

    # ---------------------------------------------------------------- power
    pw = d.sheet("power", "Power: 12 V -> 1.8 V -> 3 x 1.3 V low-noise LDOs")
    tps62130(pw, ref, "+12V_FMC", "+1V8", 1.8, en="PG_C2M", pg="PG_1V8", name="BUCK1V8")
    for chip in (1, 2, 3):
        adp1755(pw, ref, "+1V8", f"AD{chip}_1V3", 1.3, en="PG_1V8", name=f"LDO_AD{chip}")
    decouple(pw, ref, "+12V_FMC", ["10u:0805"])
    decouple(pw, ref, "VADJ", ["10u:0603", "1u"])
    decouple(pw, ref, "+3V3", ["10u:0603", "1u"])
    pw.add(R(ref("R"), "100k", "PG_C2M", "GND"))
    for i in range(4):
        pw.add(Part(ref("H"), "Mechanical:MountingHole_Pad", "M3", FP["HOLE"], {"1": "GND"}))
    for net in ("AD1_1V3", "AD2_1V3", "AD3_1V3", "+1V8"):
        pw.add(Part(ref("TP"), "Connector:TestPoint", net, FP["TP"], {"1": net}))

    # ---------------------------------------------------------------- FMC + board A control
    fm = d.sheet("fmc", "FMC LPC mezzanine connector")
    conn = {}
    for pin, sig in LPC.items():
        if sig == "GND":
            conn[pin] = "GND"
        elif sig == "12P0V":
            conn[pin] = "+12V_FMC"
        elif sig == "3P3V":
            conn[pin] = "+3V3"
        elif sig == "VADJ":
            conn[pin] = "VADJ"
        elif sig == "PG_C2M":
            conn[pin] = "PG_C2M"
        elif sig == "PRSNT_M2C_L":
            conn[pin] = "GND"
        elif sig == "TDI":
            conn[pin] = "FMC_TDI_TDO"  # no JTAG devices on the mezzanine: loop TDI -> TDO
        elif sig == "TDO":
            conn[pin] = "FMC_TDI_TDO"
        elif sig == "CLK0_M2C_P":
            conn[pin] = "FPGA_REFCLK"
    for name, n_la in LVDS_PLAN.items():
        conn[la(n_la, "P")] = f"{name}_P"
        conn[la(n_la, "N")] = f"{name}_N"
    for name, (n_la, pol) in SE_PLAN.items():
        if name in ("SPARE0", "SPARE1"):
            continue
        conn[la(n_la, pol)] = name if name != "AD_SYNC_IN" else "AD_SYNC_IN"
    fm.add(Part("J1", "prc:ASP-134604-01", "FMC LPC (mezzanine)", None, conn, lcsc="C2830435"))
    fm.add(R(ref("R"), "33", "CAL_EN_FPGA", "CAL_EN"))
    fm.add(Part(ref("J"), "Connector_Generic:Conn_01x02", "CAL_EN to board A",
                "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", {"1": "CAL_EN", "2": "GND"}))
    fm.add(R(ref("R"), "100k", "CAL_EN", "GND"))
    fm.note("VADJ must be set to 2.5 V by the carrier (LVDS_25 banks). LA pair plan: tools/fmc.py.")

    # rename LVDS nets to match AD9361 pin nets
    return d


def _alias_lvds(d):
    """AD9361 pins use AD1_DCLK_P etc.; FMC uses the same names -> already identical."""
    return d


if __name__ == "__main__":
    # python boards/board_b.py                -> board_b/ (UHF build, ATB2012 baluns)
    # python boards/board_b.py <mid|high|n78> -> board_b_bands/<band>/board_b_<band> (TCM1-63AX+ baluns)
    BAND = sys.argv[1] if len(sys.argv) > 1 else "uhf"
    d = build()
    if BAND != "uhf":
        d.name = f"board_b_{BAND}"
    for pr in d.check():
        print("CHECK:", pr)
    out = d.write(os.path.join(HERE, "..", "board_b" if BAND == "uhf" else os.path.join("board_b_bands", BAND)))
    print(f"wrote {out}: {len(d.parts())} parts, {len(d.nets())} nets")
