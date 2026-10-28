"""Board A2 - 6-channel multiband front end (TV + 4G + 5G), one design built in four band versions.

    python boards/board_a2.py <uhf|mid|high|n78|all>   ->  board_a2/<band>/board_a2_<band>.kicad_sch + netlist

The radar runs one receiver stack (A2 + B + C) per band, all locked to one clock (see docs/DESIGN.md).
Each A2 build serves one antenna array and, through a 2-way splitter on every channel, two stacks:

    band   pass band            illuminators served (stack A / stack B)        LNA stages  band filter
    uhf    470-821 MHz          DVB-T  /  LTE B20/B28 + 5G n28                 1           LC 420-920 MHz
    mid    1805-2170 MHz        LTE B3  /  LTE B1                              2           Walsin 1.5-2.4 GHz
    high   2496-2690 MHz        LTE B7  /  5G n41                              2           TDK 2.3-2.69 GHz
    n78    3300-3800 MHz        5G n78  /  spare (second operator)             2           TDK 3.3-4.2 GHz

Per channel:
    SMA in -> DC block -> SKY13351 SPDT (OUTPUT1 = antenna, OUTPUT2 = calibration noise) -> DC block
           -> SPF5043Z LNA1 [-> SPF5043Z LNA2] -> band filter -> 2-way resistive splitter -> 2 x SMA out
Calibration: 50 ohm termination -> 3 x SPF5043Z (3 dB pads between) -> 6-way star splitter -> OUTPUT2
             of every switch. CAL_EN high powers the noise source and turns every switch to OUTPUT2.
Switch control (SKY13351 truth table): VCTL1 = CAL_EN, VCTL2 = NOT CAL_EN (SN74LVC1G04).
Power: 12 V jack -> TPS62130 5.6 V -> 2 x LT3045 5.0 V LNA rails (ch 0-2, ch 3-5; up to 6 x 46 mA each)
       + LT3045 5.0 V noise source (enabled by CAL_EN) -> TLV75533 3.3 V (logic).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

from blocks import FP, C, L, R, Refs, decouple, lt3045, ldo_tlv755, tps62130  # noqa: E402
from schgen import Design, Part  # noqa: E402

N_CH = 6
SPLIT_R = "16.5"  # 2-way resistive splitter arm (50/3 ohm), 6 dB per port, broadband to > 4 GHz in 0402

# LC filter for the UHF build (tools/filter_design.py, 0.1 dB Chebyshev, 50 ohm, 0402 parasitics):
# 0.7 dB at 470-760 MHz, 1.1 dB at 821 MHz, -34 dB at 100 MHz (FM), -39 dB at 1.8 GHz.
UHF_FILTER = [("C_se", "7.5p"), ("L_sh", "15n"), ("C_se", "7.5p"),
              ("C_sh", "3.9p"), ("L_se", "15n"), ("C_sh", "6.8p"), ("L_se", "15n"), ("C_sh", "3.9p")]

BANDS = {
    # dc: DC-block value; choke: (value, size) LNA bias choke; lna2: second LNA stage fitted
    "uhf": dict(title="470-821 MHz (DVB-T, LTE B20/B28, 5G n28)", dc="100p", choke=("220n", "0603"), lna2=False,
                filt=("lc", None)),
    "mid": dict(title="1805-2170 MHz (LTE B3, LTE B1)", dc="33p", choke=("100n", "0603"), lna2=True,
                filt=("chip", ("prc:RFBPF1608060AAT", "RFBPF1608060AAT", "C474007",
                               {"IN": "{i}", "OUT": "{o}", "GND": "GND"}))),
    "high": dict(title="2496-2690 MHz (LTE B7, 5G n41)", dc="22p", choke=("100n", "0603"), lna2=True,
                 filt=("chip", ("prc:DEA162495BT-1289A1", "DEA162495BT-1289A1", "C432966",
                                {"IN": "{i}", "OUT": "{o}", "GND": "GND"}))),
    "n78": dict(title="3300-3800 MHz (5G n78)", dc="10p", choke=("22n", "0402"), lna2=True,
                filt=("chip", ("prc:DEA203750BT-2292A1-H", "DEA203750BT-2292A1-H", "C3156235",
                               {"InputPort": "{i}", "OutputPort": "{o}", "GND": "GND"}))),
}


def lna(sh, ref, b, rail, a_in, a_out):
    sh.add(Part(ref("U"), "prc:SPF5043Z", "SPF5043Z", None, {"RF_IN": a_in, "RF_OUT": a_out, "GND": "GND"},
                lcsc="C470902"))
    sh.add(L(ref("L"), b["choke"][0], rail, a_out, b["choke"][1]))
    decouple(sh, ref, rail, ["100p", "100n"])


def build(band):
    b = BANDS[band]
    d = Design(f"board_a2_{band}", f"Board A2 ({band}) - front end {b['title']} + calibration noise source")
    ref = Refs()

    # ---------------------------------------------------------------- power
    pw = d.sheet("power", "Power: 12 V in, 5.6 V buck, two low-noise 5 V LNA rails, noise-source rail, 3.3 V")
    pw.add(Part(ref("J"), "prc:DC-005C-20A", "12V DC", None, {"1": "VIN_RAW", "2": "GND", "3": "GND"},
                lcsc="C84007", mpn="DC-005C-20A"))
    pw.add(Part(ref("F"), "Device:Polyfuse", "1.5A", "Fuse:Fuse_1206_3216Metric", {"1": "VIN_RAW", "2": "VIN_FUSED"}))
    pw.add(Part(ref("D"), "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", {"A": "VIN_FUSED", "K": "+12V"},
                lcsc="C8678", mpn="SS34"))
    decouple(pw, ref, "+12V", ["22u:1206"])
    tps62130(pw, ref, "+12V", "+5V6", 5.6, en="+12V", pg="PG_5V6", name="BUCK5V6")
    lt3045(pw, ref, "+5V6", "+5V_LNA_A", 5.0, en="+5V6", name="LDO_LNA_A")
    lt3045(pw, ref, "+5V6", "+5V_LNA_B", 5.0, en="+5V6", name="LDO_LNA_B")
    lt3045(pw, ref, "+5V6", "+5V_NS", 5.0, en="CAL_EN", name="LDO_NS")
    ldo_tlv755(pw, ref, "+5V_LNA_A", "+3V3", 3.3)
    pw.add(R(ref("R"), "4.7k", "+3V3", "LED_PWR"))
    pw.add(Part(ref("D"), "Device:LED", "green", FP["LED0603"], {"A": "LED_PWR", "K": "GND"}))
    pw.add(Part(ref("J"), "Connector_Generic:Conn_01x02", "CAL_EN", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                {"1": "CAL_EN", "2": "GND"}))
    pw.add(R(ref("R"), "100k", "CAL_EN", "GND"))  # no cable: antennas selected, noise source off
    pw.add(Part(ref("U"), "prc:SN74LVC1G04DBVR", "SN74LVC1G04DBVR", None,
                {"A": "CAL_EN", "Y": "CAL_EN_N", "VCC": "+3V3", "GND": "GND", "N.C": "NC_INV1"}, lcsc="C7827"))
    decouple(pw, ref, "+3V3", ["100n"])
    pw.add(R(ref("R"), "4.7k", "+5V_NS", "LED_CAL"))
    pw.add(Part(ref("D"), "Device:LED", "yellow", FP["LED0603"], {"A": "LED_CAL", "K": "GND"}))
    for _ in range(4):
        pw.add(Part(ref("H"), "Mechanical:MountingHole_Pad", "M3", FP["HOLE"], {"1": "GND"}))
    pw.note(f"Band build: {band} = {b['title']}. CAL_EN (1.8-3.3 V logic): high = noise source on, all switches on OUTPUT2.")

    # ---------------------------------------------------------------- noise source
    ns = d.sheet("noise_source", "Calibration noise source and 6-way splitter")
    ns.add(R(ref("R"), "49.9", "NS_TERM", "GND"))
    prev = "NS_TERM"
    for k in range(3):
        a_in, a_out = f"NS_A{k}_IN", f"NS_A{k}_OUT"
        ns.add(C(ref("C"), b["dc"], prev, a_in))
        lna(ns, ref, b, "+5V_NS", a_in, a_out)
        pin, pout = f"NS_P{k}_A", f"NS_P{k}_B"  # 3 dB pi pad between stages for stability
        ns.add(C(ref("C"), b["dc"], a_out, pin))
        ns.add(R(ref("R"), "294", pin, "GND"))
        ns.add(R(ref("R"), "17.8", pin, pout))
        ns.add(R(ref("R"), "294", pout, "GND"))
        prev = pout
    for ch in range(N_CH):  # star splitter: 50 * (N-1)/(N+1) = 35.7 ohm per arm
        ns.add(R(ref("R"), "35.7", prev, f"CH{ch}_CAL"))
    ns.note("Noise into every channel: ENR ~39 dB at UHF, falling with SPF5043Z gain to ~15 dB at 3.5 GHz.")

    # ---------------------------------------------------------------- channels
    for half in range(2):
        rail = "+5V_LNA_A" if half == 0 else "+5V_LNA_B"
        sh = d.sheet(f"channels_{half}", f"RF channels {3*half}-{3*half+2}")
        for ch in range(3 * half, 3 * half + 3):
            p = f"CH{ch}"
            sh.add(Part(ref("J"), "prc:BWSMA-KE-Z001", f"ANT{ch}", None,
                        {"5": f"{p}_ANT", "1": "GND", "2": "GND", "3": "GND", "4": "GND"}, lcsc="C496549"))
            sh.add(C(ref("C"), b["dc"], f"{p}_ANT", f"{p}_SW_O1"))
            sh.add(C(ref("C"), b["dc"], f"{p}_CAL", f"{p}_SW_O2"))
            sh.add(Part(ref("U"), "prc:SKY13351-378LF", "SKY13351-378LF", None,
                        {"OUTPUT1": f"{p}_SW_O1", "OUTPUT2": f"{p}_SW_O2", "INPUT": f"{p}_SW_IN",
                         "VCTL1": "CAL_EN", "VCTL2": "CAL_EN_N", "GND": "GND"}, lcsc="C129189"))
            sh.add(C(ref("C"), b["dc"], f"{p}_SW_IN", f"{p}_LNA_IN"))
            lna(sh, ref, b, rail, f"{p}_LNA_IN", f"{p}_LNA_OUT")
            node = f"{p}_LNA_OUT"
            if b["lna2"]:
                sh.add(C(ref("C"), b["dc"], node, f"{p}_LNA2_IN"))
                lna(sh, ref, b, rail, f"{p}_LNA2_IN", f"{p}_LNA2_OUT")
                node = f"{p}_LNA2_OUT"
            kind, chip = b["filt"]
            sh.add(C(ref("C"), b["dc"], node, f"{p}_F_IN"))
            node = f"{p}_F_IN"
            if kind == "lc":
                for i, (k, val) in enumerate(UHF_FILTER):
                    part = C if k[0] == "C" else L
                    if k.endswith("se"):
                        nxt = f"{p}_F{i}"
                        sh.add(part(ref(k[0]), val, node, nxt))
                        node = nxt
                    else:
                        sh.add(part(ref(k[0]), val, node, "GND"))
                out = node
            else:
                lib, val, lcsc, pins = chip
                out = f"{p}_F_OUT"
                sh.add(Part(ref("FL"), lib, val, None,
                            {k: v.format(i=node, o=out) for k, v in pins.items()}, lcsc=lcsc))
            # 2-way resistive splitter: three 16.5 ohm arms from a common node
            sh.add(R(ref("R"), SPLIT_R, out, f"{p}_SPL"))
            for side in ("A", "B"):
                sh.add(R(ref("R"), SPLIT_R, f"{p}_SPL", f"{p}_OUT{side}"))
                sh.add(Part(ref("J"), "prc:BWSMA-KE-Z001", f"OUT{ch}{side}", None,
                            {"5": f"{p}_OUT{side}", "1": "GND", "2": "GND", "3": "GND", "4": "GND"}, lcsc="C496549"))
        sh.note("RF traces: 50 ohm grounded coplanar waveguide on L1 over solid GND on L2. Keep the chain in line.")
    return d


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for band in (BANDS if which == "all" else [which]):
        d = build(band)
        for pr in d.check():
            print(f"[{band}] CHECK:", pr)
        out = d.write(os.path.join(HERE, "..", "board_a2", band))
        print(f"[{band}] wrote {out}: {len(d.parts())} parts, {len(d.nets())} nets")
