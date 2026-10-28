"""Board A - 6-channel UHF front end with built-in calibration noise source.

Per channel:
    SMA in -> PE4259 SPDT (antenna / calibration noise) -> SPF5043Z LNA (0.8 dB NF, 18 dB)
           -> 3rd-order high-pass (420 MHz) + 5th-order low-pass (780 MHz) -> SMA out
Calibration:
    50 ohm termination -> 3 x SPF5043Z (~50 dB) -> 6-way resistive star splitter
    -> RF1 port of every switch. Powered only while CAL_EN is high (LT3045 EN).
    Gives ~39 dB ENR of *the same* noise into all channels, so the digitizer can
    measure and remove channel-to-channel phase/gain differences.
Power: 12 V jack -> TPS62130 (5.6 V) -> LT3045 x2 (5.0 V LNAs, 5.0 V noise source)
       -> TLV75533 (3.3 V switches).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

from blocks import FP, C, L, R, Refs, decouple, lt3045, ldo_tlv755, tps62130  # noqa: E402
from schgen import Design, Part  # noqa: E402

N_CH = 6
# Filter from tools/filter_design.py (0.1 dB Chebyshev, 50 ohm): 0.7 dB in band, -34 dB @ 100 MHz, -44 dB @ 1.8 GHz
FILTER = [("C_se", "7.5p"), ("L_sh", "15n"), ("C_se", "7.5p"),
          ("C_sh", "4.7p"), ("L_se", "15n"), ("C_sh", "8.2p"), ("L_se", "15n"), ("C_sh", "4.7p")]
RF_CHOKE = "220n"  # LNA bias choke: 0603 wire-wound, > 650 ohm at 470 MHz


def build():
    d = Design("board_a", "Board A - UHF front end + calibration noise source")
    ref = Refs()

    # ---------------------------------------------------------------- power
    pw = d.sheet("power", "Power: 12 V in, 5.6 V buck, low-noise 5 V and 3.3 V")
    pw.add(Part(ref("J"), "prc:DC-005C-20A", "12V DC", None, {"1": "VIN_RAW", "2": "GND", "3": "GND"},
                lcsc="C84007", mpn="DC-005C-20A"))
    pw.add(Part(ref("F"), "Device:Polyfuse", "1.5A", "Fuse:Fuse_1206_3216Metric", {"1": "VIN_RAW", "2": "VIN_FUSED"}))
    pw.add(Part(ref("D"), "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", {"A": "VIN_FUSED", "K": "+12V"},
                lcsc="C8678", mpn="SS34"))
    decouple(pw, ref, "+12V", ["22u:1206"])
    tps62130(pw, ref, "+12V", "+5V6", 5.6, en="+12V", pg="PG_5V6", name="BUCK5V6")
    lt3045(pw, ref, "+5V6", "+5V_LNA", 5.0, en="+5V6", name="LDO_LNA")
    lt3045(pw, ref, "+5V6", "+5V_NS", 5.0, en="CAL_EN", name="LDO_NS")
    ldo_tlv755(pw, ref, "+5V_LNA", "+3V3", 3.3)
    pw.add(R(ref("R"), "4.7k", "+3V3", "LED_PWR"))
    pw.add(Part(ref("D"), "Device:LED", "green", FP["LED0603"], {"A": "LED_PWR", "K": "GND"}))
    pw.add(Part(ref("J"), "Connector_Generic:Conn_01x02", "CAL_EN", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                {"1": "CAL_EN", "2": "GND"}))
    pw.add(R(ref("R"), "100k", "CAL_EN", "GND"))  # default: antennas selected, noise source off
    pw.add(R(ref("R"), "4.7k", "+5V_NS", "LED_CAL"))
    pw.add(Part(ref("D"), "Device:LED", "yellow", FP["LED0603"], {"A": "LED_CAL", "K": "GND"}))
    for i in range(4):
        pw.add(Part(ref("H"), "Mechanical:MountingHole_Pad", "M3", FP["HOLE"], {"1": "GND"}))
    pw.note("CAL_EN (from the digitizer/FPGA, 1.8-3.3 V logic): high = noise source on and all switches on RF1 (cal).")

    # ---------------------------------------------------------------- noise source
    ns = d.sheet("noise_source", "Calibration noise source and 6-way splitter")
    node = "NS_TERM"
    ns.add(R(ref("R"), "49.9", node, "GND"))
    prev = node
    for k in range(3):
        a_in, a_out = f"NS_A{k}_IN", f"NS_A{k}_OUT"
        ns.add(C(ref("C"), "100p", prev, a_in))
        ns.add(Part(ref("U"), "prc:SPF5043Z", "SPF5043Z", None, {"RF_IN": a_in, "RF_OUT": a_out, "GND": "GND"},
                    lcsc="C470902"))
        ns.add(L(ref("L"), RF_CHOKE, "+5V_NS", a_out, "0603"))
        decouple(ns, ref, "+5V_NS", ["100p", "100n"])
        # 3 dB pi attenuator between stages for stability (292 / 17.6 / 292 ohm)
        pin, pout = f"NS_P{k}_A", f"NS_P{k}_B"
        ns.add(C(ref("C"), "100p", a_out, pin))
        ns.add(R(ref("R"), "294", pin, "GND"))
        ns.add(R(ref("R"), "17.8", pin, pout))
        ns.add(R(ref("R"), "294", pout, "GND"))
        prev = pout
    # star splitter: arm resistance 50 * (N-1)/(N+1) = 35.7 ohm, 15.6 dB loss per port
    for ch in range(N_CH):
        ns.add(R(ref("R"), "35.7", prev, f"CH{ch}_CAL"))
    ns.note("Expected output: about -134 dBm/Hz per channel (ENR ~39 dB) after the 15.6 dB splitter.")

    # ---------------------------------------------------------------- channels
    for half in range(2):
        sh = d.sheet(f"channels_{half}", f"RF channels {3*half}-{3*half+2}")
        for ch in range(3 * half, 3 * half + 3):
            p = f"CH{ch}"
            sh.add(Part(ref("J"), "prc:BWSMA-KE-Z001", f"ANT{ch}", None, {"5": f"{p}_ANT", "1": "GND", "2": "GND",
                                                                          "3": "GND", "4": "GND"}, lcsc="C496549"))
            # switch: RF1 = calibration noise, RF2 = antenna, RFC -> LNA. Single-pin mode: pin 6 = VDD.
            sh.add(C(ref("C"), "100p", f"{p}_ANT", f"{p}_SW_RF2"))
            sh.add(C(ref("C"), "100p", f"{p}_CAL", f"{p}_SW_RF1"))
            sh.add(Part(ref("U"), "prc:PE4259-63", "PE4259-63", None,
                        {"RF1": f"{p}_SW_RF1", "RF2": f"{p}_SW_RF2", "RFC": f"{p}_SW_C", "CTRL": "CAL_EN",
                         "CTRL#orVDD": "+3V3", "GND": "GND"}, lcsc="C470892"))
            decouple(sh, ref, "+3V3", ["100p"])
            sh.add(C(ref("C"), "100p", f"{p}_SW_C", f"{p}_LNA_IN"))
            sh.add(Part(ref("U"), "prc:SPF5043Z", "SPF5043Z", None,
                        {"RF_IN": f"{p}_LNA_IN", "RF_OUT": f"{p}_LNA_OUT", "GND": "GND"}, lcsc="C470902"))
            sh.add(L(ref("L"), RF_CHOKE, "+5V_LNA", f"{p}_LNA_OUT", "0603"))
            decouple(sh, ref, "+5V_LNA", ["100p", "100n"])
            node = f"{p}_LNA_OUT"
            for i, (kind, val) in enumerate(FILTER):
                if kind.endswith("se"):
                    nxt = f"{p}_F{i}"
                    part = C if kind[0] == "C" else L
                    sh.add(part(ref(kind[0]), val, node, nxt))
                    node = nxt
                else:
                    part = C if kind[0] == "C" else L
                    sh.add(part(ref(kind[0]), val, node, "GND"))
            sh.add(Part(ref("J"), "prc:BWSMA-KE-Z001", f"OUT{ch}", None, {"5": node, "1": "GND", "2": "GND",
                                                                          "3": "GND", "4": "GND"}, lcsc="C496549"))
            # rename the last filter node to the output name for readability is not needed; it is the SMA net
        sh.note("RF traces: 50 ohm grounded coplanar waveguide on L1 over solid GND on L2. Keep filter parts in line.")
    return d


if __name__ == "__main__":
    d = build()
    probs = d.check()
    for pr in probs:
        print("CHECK:", pr)
    out = d.write(os.path.join(HERE, "..", "board_a"))
    n = d.parts()
    print(f"wrote {out}: {len(n)} parts, {len(d.nets())} nets")
