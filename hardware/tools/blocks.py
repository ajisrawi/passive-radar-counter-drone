"""Reusable schematic building blocks (passives, decoupling, regulators)."""
from schgen import Part

FP = {
    "R0402": "Resistor_SMD:R_0402_1005Metric",
    "R0603": "Resistor_SMD:R_0603_1608Metric",
    "C0402": "Capacitor_SMD:C_0402_1005Metric",
    "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric",
    "C1206": "Capacitor_SMD:C_1206_3216Metric",
    "L0402": "Inductor_SMD:L_0402_1005Metric",
    "L0603": "Inductor_SMD:L_0603_1608Metric",
    "L4018": "Inductor_SMD:L_Bourns-SRN4018",
    "FB0603": "Inductor_SMD:L_0603_1608Metric",
    "VQFN16": "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm",
    "SOT23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "VSON10": "Package_SON:VSON-10-1EP_3x3mm_P0.5mm_EP1.65x2.4mm",
    "LED0603": "LED_SMD:LED_0603_1608Metric",
    "TP": "TestPoint:TestPoint_Pad_D1.0mm",
    "HOLE": "MountingHole:MountingHole_3.2mm_M3_Pad_Via",
    "HDR2x5": "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical",
    "HDR2x3": "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical",
    "JTAG14": "Connector_PinHeader_2.00mm:PinHeader_2x07_P2.00mm_Vertical",
}

# JLCPCB "basic" passives (no extended-part fee). Others are matched by value at BOM time.
LCSC = {
    ("C", "100n", "0402"): "C1525", ("C", "1u", "0402"): "C52923", ("C", "10n", "0402"): "C15195",
    ("C", "10u", "0603"): "C19702", ("R", "10k", "0402"): "C25744", ("R", "0", "0402"): "C17168",
    ("C", "22u", "0805"): "C45783", ("R", "100k", "0402"): "C25741", ("R", "4.7k", "0402"): "C25900",
    ("R", "1k", "0402"): "C11702", ("R", "5.1k", "0402"): "C25905",
}


class Refs:
    """Reference designator counters for one design."""

    def __init__(self):
        self.n = {}

    def __call__(self, prefix):
        self.n[prefix] = self.n.get(prefix, 0) + 1
        return f"{prefix}{self.n[prefix]}"


def R(ref, value, a, b, size="0402", **kw):
    return Part(ref, "Device:R", value, FP["R" + size], {"1": a, "2": b},
                lcsc=LCSC.get(("R", value, size), ""), **kw)


def C(ref, value, a, b, size="0402", **kw):
    return Part(ref, "Device:C", value, FP["C" + size], {"1": a, "2": b},
                lcsc=LCSC.get(("C", value, size), ""), **kw)


def L(ref, value, a, b, size="0402", lcsc="", mpn="", **kw):
    return Part(ref, "Device:L", value, FP["L" + size], {"1": a, "2": b}, lcsc=lcsc, mpn=mpn, **kw)


def FB(ref, a, b, value="600R@100MHz", **kw):
    return Part(ref, "Device:FerriteBead_Small", value, FP["FB0603"], {"1": a, "2": b}, **kw)


def decouple(sheet, refs, net, values, gnd="GND"):
    """values like ['100n', '100n', '1u', '10u:0603']"""
    out = []
    for v in values:
        val, size = (v.split(":") + ["0402"])[:2]
        out.append(sheet.add(C(refs("C"), val, net, gnd, size)))
    return out


def tps62130(sheet, refs, vin, vout_net, vout, en, pg=None, gnd="GND", name=""):
    """TPS62130 3 A buck. FB divider: Vout = 0.8 V * (1 + Rtop/Rbot), Rbot = 100k (datasheet 8.2.2)."""
    u = refs("U")
    fb = f"{name}_FB"
    sw = f"{name}_SW"
    ss = f"{name}_SS"
    rtop_k = round(100 * (vout / 0.8 - 1), 1)
    conn = {"VIN": vin, "GND": gnd, "SW": sw, "EN": en, "FB": fb, "VOS": vout_net, "SS/TR": ss,
            "FSW": gnd, "DEF": gnd, "PG": pg or f"NC_{name}_PG"}
    sheet.add(Part(u, "Regulator_Switching:TPS62130", "TPS62130RGTR", FP["VQFN16"], conn, lcsc="C43590",
                   mpn="TPS62130RGTR"))
    sheet.add(L(refs("L"), "2.2u", sw, vout_net, "4018", mpn="SRN4018-2R2M"))
    sheet.add(R(refs("R"), f"{rtop_k:g}k" if rtop_k else "0", vout_net, fb))
    sheet.add(R(refs("R"), "100k", fb, gnd))
    sheet.add(C(refs("C"), "3.3n", ss, gnd))  # ~1 ms soft start
    decouple(sheet, refs, vin, ["10u:0805", "10u:0805", "100n"], gnd)
    decouple(sheet, refs, vout_net, ["22u:0805", "22u:0805", "100n"], gnd)
    if pg:
        if vout < 1.5:
            # PG often drives the next EN (internal ~400k pull-down, V_IH ~0.9 V): a pull-up to a
            # ~1 V rail would sit too low. Pull up from VIN through a divider instead (PG abs max 7 V).
            sheet.add(R(refs("R"), "100k", pg, vin))
            sheet.add(R(refs("R"), "47k", pg, gnd))
        else:
            sheet.add(R(refs("R"), "100k", pg, vout_net))
    return u


def ldo_tlv755(sheet, refs, vin, vout_net, volts, en=None, gnd="GND"):
    lib = {3.3: "TLV75533PDBV", 2.5: "TLV75525PDBV"}[volts]
    lcsc = {3.3: "C404027", 2.5: ""}[volts]
    u = refs("U")
    sheet.add(Part(u, f"Regulator_Linear:{lib}", lib + "R", FP["SOT23-5"],
                   {"IN": vin, "GND": gnd, "EN": en or vin, "OUT": vout_net}, lcsc=lcsc))
    decouple(sheet, refs, vin, ["1u"], gnd)
    decouple(sheet, refs, vout_net, ["1u", "100n"], gnd)
    return u


def lt3045(sheet, refs, vin, vout_net, volts, en, pg=None, gnd="GND", name=""):
    """LT3045: Vout = 100 uA * R_SET. R_ILIM sets current limit (~ 150 mA*kOhm / I)."""
    u = refs("U")
    rset = f"{volts / 100e-6 / 1e3:.1f}k"
    conn = {"IN": vin, "EN/UV": en, "PG": pg or f"NC_{name}_PG", "ILIM": f"{name}_ILIM", "PGFB": vin,
            "SET": f"{name}_SET", "GND": gnd, "EP": gnd, "OUTS": vout_net, "OUT": vout_net}
    sheet.add(Part(u, "prc:LT3045EMSE#PBF", "LT3045EMSE", None, conn, lcsc="C580012", mpn="LT3045EMSE#PBF"))
    sheet.add(R(refs("R"), rset, f"{name}_SET", gnd, fields={"Tolerance": "0.1%"}))
    sheet.add(C(refs("C"), "4.7u", f"{name}_SET", gnd, "0603"))  # noise filter on SET
    sheet.add(R(refs("R"), "300", f"{name}_ILIM", gnd))  # ~500 mA limit
    decouple(sheet, refs, vin, ["10u:0603", "100n"], gnd)
    decouple(sheet, refs, vout_net, ["10u:0603", "100n"], gnd)
    return u


def adp1755(sheet, refs, vin, vout_net, volts, en, pg=None, gnd="GND", name=""):
    """ADP1755 adjustable: Vout = 0.5 V * (1 + R1/R2), R2 = 10k."""
    u = refs("U")
    r1 = 10 * (volts / 0.5 - 1)
    conn = {"VIN": vin, "EN": en, "PG": pg or f"NC_{name}_PG", "GND": gnd, "SS": f"{name}_SS",
            "ADJ": f"{name}_ADJ", "VOUT": vout_net, "EP": gnd}
    sheet.add(Part(u, "prc:ADP1755ACPZ-R7", "ADP1755ACPZ-R7", None, conn, lcsc="C403695"))
    sheet.add(R(refs("R"), f"{r1:g}k", vout_net, f"{name}_ADJ", fields={"Tolerance": "1%"}))
    sheet.add(R(refs("R"), "10k", f"{name}_ADJ", gnd, fields={"Tolerance": "1%"}))
    sheet.add(C(refs("C"), "10n", f"{name}_SS", gnd))
    decouple(sheet, refs, vin, ["10u:0603", "100n"], gnd)
    decouple(sheet, refs, vout_net, ["10u:0603", "1u", "100n"], gnd)
    return u
