"""OpenBoard PCB projects + fab files for the antenna elements and the LPDA-H reference.

    python hardware/antenna/antenna_pcbs.py

Reads design.json (from antenna_design.py) and writes hardware/antenna/pcb/<name>/:
  <name>.openboard.json, fab/<name>-fab.zip (Gerbers + drill), fab/<name>-BOM.csv, fab/<name>-CPL.csv,
  <name>.png (copper preview), <name>_openems.py (full-wave model to run later in openEMS, optional)

Element boards (dipole_uhf/mid/high/n78): double-sided printed dipole with a microstrip-to-parallel-strip balun.
  F.Cu (net RF):  50 ohm microstrip from the edge SMA up the stem -> widens to the parallel-strip width -> left arm.
  B.Cu (net GND): microstrip ground under the stem -> tapers to the parallel-strip width -> right arm.
  The taper runs the full stem height above the reflector (about lambda/4), which is the balun. Two notches on the
  stem edges mark the reflector plane; the board passes through a slot in the reflector and the SMA sits behind it.
LPDA-H: printed twin-boom log-periodic. F.Cu boom (RF) and B.Cu boom (GND) on top of each other; each dipole is one
  half on F.Cu and the other half on B.Cu, alternating side from one dipole to the next (the feed transposition).
  Fed at the short (apex) end by the edge SMA; run the cable back along the boom.
All copper is static zones (drawn exactly as specified), so DRC checks it and the Gerbers carry it unchanged.
"""
import json
import math
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pcb")
OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
SMA_MOD = r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Connector_Coaxial.pretty\SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount.kicad_mod"
SMA_FP = "SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount"
SMA_EDGE = 2.6  # footprint origin (centre pin) to the board edge, mm

ER, DIEL, TAND = 4.4, 1.53, 0.02
M = 3.0         # board margin around copper
W_PS = 4.0      # parallel-strip (balun output) width
W_G = 12.0      # microstrip ground width on the stem
STEM = W_G + 4  # stem board width
TAIL = 12.0     # stem length below the reflector plane (reflector, clearance, SMA)


def op(*args, check=True):
    r = subprocess.run(["node", OPENPCB, *map(str, args)], capture_output=True, text=True)
    if check and r.returncode not in (0, 2):
        raise RuntimeError(f"openpcb {args[0]}: {r.stderr or r.stdout}")
    out = r.stdout.strip()
    return json.loads(out) if out.startswith("{") else {"raw": out}


def pts(seq):
    return [{"x": round(x, 4), "y": round(y, 4)} for x, y in seq]


class Board:
    def __init__(self, name, w, h):
        self.name = name
        self.dir = os.path.join(OUT, name)
        if os.path.isdir(self.dir):
            shutil.rmtree(self.dir)
        os.makedirs(self.dir)
        self.path = os.path.join(self.dir, f"{name}.openboard.json")
        op("new", self.path, "--name", name, "--layers", 2, "--width", round(w, 3), "--height", round(h, 3))
        op("import-footprint", self.path, SMA_MOD)
        self.d = json.load(open(self.path, encoding="utf-8"))
        d = self.d
        # the connector body overhangs the board edge (x < -SMA_EDGE in the footprint): drop that silkscreen
        sma = next(f for k, f in d["footprints"].items() if k.endswith(SMA_FP))
        sma["outline"] = [seg for seg in sma.get("outline", []) if all(q["x"] >= -SMA_EDGE + 0.2 for q in seg)]
        d["layers"][0].update({"er": ER, "lossTangent": TAND, "dielectric": DIEL})
        d["layers"][1].update({"er": ER, "lossTangent": TAND})
        d["rules"].update({"clearance": 0.2, "width": 0.25, "edgeClearance": 0.3, "viaDiameter": 0.6, "viaDrill": 0.3})
        # back-side legs of the edge SMA (KiCad has them on B.Cu; OpenBoard SMD pads are one-sided): mirrored on
        # placement, so x is negated here to land under the front legs
        d["footprints"]["Antenna:SMA_EdgeMount_rear_legs"] = {
            "name": "Antenna:SMA_EdgeMount_rear_legs",
            "pads": [{"id": "2", "x": 0.25, "y": s * 2.825, "w": 3.7, "h": 1.35, "shape": "rect", "th": False} for s in (1, -1)],
            "outline": [], "body": {"w": 3.7, "h": 7.0}}
        d["nets"] = [{"name": "RF", "pins": ["J1-1"]}, {"name": "GND", "pins": ["J1-2", "J1B-2"]}]

    def nid(self):
        self.d["nextId"] += 1
        return self.d["nextId"]

    def outline(self, poly):
        self.d["outline"] = pts(poly)

    def sma(self, x, y, rot):
        fp = next(k for k in self.d["footprints"] if k.endswith(SMA_FP))
        self.d["components"] = [
            {"ref": "J1", "footprint": fp, "value": "SMA edge 1.6mm", "x": round(x, 4), "y": round(y, 4), "rot": rot, "side": "front"},
            {"ref": "J1B", "footprint": "Antenna:SMA_EdgeMount_rear_legs", "value": "DNP", "x": round(x, 4), "y": round(y, 4),
             "rot": rot, "side": "back"}]

    def zone(self, net, layer, poly):
        self.d["zones"].append({"id": self.nid(), "net": net, "layer": layer, "points": pts(poly),
                                "clearance": self.d["rules"]["clearance"], "dynamic": False})

    def via(self, net, x, y):
        self.d["vias"].append({"id": self.nid(), "net": net, "x": round(x, 4), "y": round(y, 4), "diameter": 0.6, "drill": 0.3})

    def save(self):
        json.dump(self.d, open(self.path, "w", encoding="utf-8"), indent=1)

    def finish(self, preview_title):
        self.save()
        drc = op("drc", self.path)
        fab = os.path.join(self.dir, "fab")
        g = op("gerber", self.path, fab, "--zip", "--name", self.name)
        a = op("assembly", self.path, fab, "--name", self.name)
        ems = op("rf-openems", self.path, os.path.join(self.dir, f"{self.name}_openems.py"), "--nets", "RF,GND",
                 "--ports", "J1-1", check=False)
        preview(self.d, os.path.join(self.dir, f"{self.name}.png"), preview_title)
        return {"drc": drc.get("summary"), "violations": drc.get("violations"), "items": drc.get("items", [])[:6],
                "gerber": g.get("files"), "drills": g.get("drillFiles"), "assembly": a.get("files"),
                "openems": "ok" if ems.get("ok") else str(ems)[:160]}


def preview(d, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    fig, ax = plt.subplots(figsize=(7, 7))
    ol = [(p["x"], p["y"]) for p in d["outline"]]
    ax.add_patch(Polygon(ol, closed=True, fc="#2e6b3a", ec="k", alpha=0.35))
    for z in d["zones"]:
        col = "#d9822b" if z["layer"] == "F.Cu" else "#3b7fd9"
        ax.add_patch(Polygon([(p["x"], p["y"]) for p in z["points"]], closed=True, fc=col, ec=col,
                             alpha=0.75 if z["layer"] == "F.Cu" else 0.5))
    for v in d["vias"]:
        ax.add_patch(plt.Circle((v["x"], v["y"]), v["diameter"] / 2, fc="k"))
    xs, ys = [p[0] for p in ol], [p[1] for p in ol]
    ax.set_xlim(min(xs) - 3, max(xs) + 3)
    ax.set_ylim(max(ys) + 3, min(ys) - 3)
    ax.set_aspect("equal")
    ax.set_title(title + "\norange = F.Cu (RF), blue = B.Cu (GND), mm", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def arm(x_root, x_tip, yc, w_root, w_tip):
    return [(x_root, yc - w_root / 2), (x_tip, yc - w_tip / 2), (x_tip, yc + w_tip / 2), (x_root, yc + w_root / 2)]


def dipole_board(band, el, w50):
    L, w, h = el["dipole_length_mm"], el["arm_width_mm"], el["height_above_reflector_mm"]
    wt = 2 * w if el["arm_shape"].startswith("bowtie") else w
    BW = L + 2 * M
    x0 = BW / 2
    ya = M + wt / 2                      # arm centre line
    yr = ya + h                          # reflector plane
    yb = yr + TAIL                       # bottom edge (SMA)
    ybar = ya + wt / 2 + M               # bottom of the arm bar
    yp = ya + wt / 2 + 1.0               # balun taper ends: parallel strips from here up
    b = Board(f"dipole_{band}", BW, yb)
    s = STEM / 2
    n = 0.8                              # reflector-plane notch depth / half height
    b.outline([(0, 0), (BW, 0), (BW, ybar), (x0 + s, ybar), (x0 + s, yr - n), (x0 + s - n, yr - n), (x0 + s - n, yr + n),
               (x0 + s, yr + n), (x0 + s, yb), (x0 - s, yb), (x0 - s, yr + n), (x0 - s + n, yr + n), (x0 - s + n, yr - n),
               (x0 - s, yr - n), (x0 - s, ybar), (0, ybar)])
    b.sma(x0, yb - SMA_EDGE, 270)
    # B.Cu GND: microstrip ground -> taper -> parallel strip -> right arm
    b.zone("GND", "B.Cu", [(x0 - W_G / 2, yb - 0.4), (x0 + W_G / 2, yb - 0.4), (x0 + W_G / 2, yr), (x0 + W_PS / 2, yp),
                           (x0 + W_PS / 2, ya + w / 2), (x0 + L / 2, ya + wt / 2), (x0 + L / 2, ya - wt / 2),
                           (x0 - W_PS / 2, ya - w / 2), (x0 - W_PS / 2, yp), (x0 - W_G / 2, yr)])
    # F.Cu RF: 50 ohm microstrip -> widens to the parallel strip -> left arm
    b.zone("RF", "F.Cu", [(x0 - w50 / 2, yb - SMA_EDGE), (x0 + w50 / 2, yb - SMA_EDGE), (x0 + w50 / 2, yr), (x0 + W_PS / 2, yp),
                          (x0 + W_PS / 2, ya - w / 2), (x0 - L / 2, ya - wt / 2), (x0 - L / 2, ya + wt / 2),
                          (x0 - W_PS / 2, ya + w / 2), (x0 - W_PS / 2, yp), (x0 - w50 / 2, yr)])
    # F.Cu GND beside the microstrip at the SMA (front ground legs), stitched to the B.Cu ground
    g = w50 / 2 + 1.0
    for sgn in (1, -1):
        xa, xb = x0 + sgn * g, x0 + sgn * W_G / 2
        b.zone("GND", "F.Cu", [(min(xa, xb), yb - 0.4), (max(xa, xb), yb - 0.4), (max(xa, xb), yb - 7.0), (min(xa, xb), yb - 7.0)])
        for yy in (yb - 1.6, yb - 5.6):
            b.via("GND", x0 + sgn * (W_G / 2 - 1.0), yy)
    info = {"board_mm": [round(BW, 1), round(yb, 1)], "reflector_plane_from_top_mm": round(yr, 1),
            "reflector_slot_mm": [round(STEM + 0.4, 1), 2.0], "taper_mm": round(yr - yp, 1)}
    res = b.finish(f"Element '{band}': {L:.1f} mm dipole, {h:.1f} mm above reflector (notches)")
    return {**info, **res}


def lpda_board(lp, w50):
    Ls = lp["element_lengths_mm"]          # longest first
    sp = lp["spacings_mm"]                 # from the long end
    e = 1.5                                # half-element strip width
    WB = 3.0                               # boom width (both faces)
    xa = SMA_EDGE + 6.0                    # shortest dipole
    xs = [0.0] * len(Ls)
    xs[-1] = xa
    for i in range(len(Ls) - 2, -1, -1):
        xs[i] = xs[i + 1] + sp[i]
    BL = xs[0] + e / 2 + M
    H = Ls[0] + 2 * M
    yc = H / 2
    b = Board("lpda_h", BL, H)
    b.outline([(0, 0), (BL, 0), (BL, H), (0, H)])
    b.sma(SMA_EDGE, yc, 0)
    # booms: F.Cu (RF) from the SMA pin, B.Cu (GND) widened under the SMA for the ground legs and vias
    b.zone("RF", "F.Cu", [(SMA_EDGE, yc - WB / 2), (xs[0] + e / 2, yc - WB / 2), (xs[0] + e / 2, yc + WB / 2), (SMA_EDGE, yc + WB / 2)])
    b.zone("GND", "B.Cu", [(0.4, yc - 4.0), (6.0, yc - 4.0), (6.0, yc - WB / 2), (xs[0] + e / 2, yc - WB / 2),
                           (xs[0] + e / 2, yc + WB / 2), (6.0, yc + WB / 2), (6.0, yc + 4.0), (0.4, yc + 4.0)])
    for i, (x, L) in enumerate(zip(xs, Ls)):
        up = 1 if i % 2 == 0 else -1     # F.Cu half: up for even dipoles, down for odd (transposed feed)
        for net, layer, sgn in (("RF", "F.Cu", up), ("GND", "B.Cu", -up)):
            y_end = yc - sgn * L / 2
            b.zone(net, layer, [(x - e / 2, yc), (x + e / 2, yc), (x + e / 2, y_end), (x - e / 2, y_end)])
    for sgn in (1, -1):
        b.zone("GND", "F.Cu", [(0.4, yc + sgn * (WB / 2 + 1.0)), (6.0, yc + sgn * (WB / 2 + 1.0)), (6.0, yc + sgn * 4.0), (0.4, yc + sgn * 4.0)])
        b.via("GND", 5.2, yc + sgn * 3.25)
    res = b.finish(f"LPDA-H {lp['f_MHz'][0]:.0f}-{lp['f_MHz'][1]:.0f} MHz, {len(Ls)} dipoles, boom {xs[0]-xs[-1]:.1f} mm")
    return {"board_mm": [round(BL, 1), round(H, 1)], "dipole_x_from_feed_edge_mm": [round(x, 2) for x in xs], **res}


def field_solved_w50():
    """50 ohm microstrip width on this stack-up from OpenBoard's field solver (probe board with a ground pour)."""
    probe = os.path.join(OUT, "_probe_w50.openboard.json")
    os.makedirs(OUT, exist_ok=True)
    op("new", probe, "--layers", 2, "--width", 30, "--height", 30)
    d = json.load(open(probe, encoding="utf-8"))
    d["layers"][0].update({"er": ER, "lossTangent": TAND, "dielectric": DIEL})
    d["layers"][1].update({"er": ER, "lossTangent": TAND})
    d["zones"].append({"id": 9999, "net": "GND", "layer": "B.Cu", "points": pts([(0, 0), (30, 0), (30, 30), (0, 30)]),
                       "clearance": 0.2, "dynamic": False})
    json.dump(d, open(probe, "w", encoding="utf-8"))
    # bisection on the field-solved Z0 at a point over the pour (impedance-width has no --at reference point)
    lo, hi, r = 2.0, 4.5, {}
    for _ in range(10):
        mid = (lo + hi) / 2
        r = op("fieldsolve", probe, "--layer", "F.Cu", "--width", round(mid, 4), "--at", "15,15", "--freq", 2)
        if r["z0"] > 50:
            lo = mid
        else:
            hi = mid
    os.remove(probe)
    return round((lo + hi) / 2, 2), {"z0": round(r["z0"], 2), "eeff": round(r["eeff"], 3)}


def main():
    design = json.load(open(os.path.join(HERE, "design.json")))
    w50, fs = field_solved_w50()
    report = {"w50_mm": w50, "field_solver": {k: v for k, v in fs.items() if k != "ok"}, "boards": {}}
    for band, v in design["bands"].items():
        report["boards"][f"dipole_{band}"] = dipole_board(band, v["element"], w50)
    report["boards"]["lpda_h"] = lpda_board(next(l for l in design["lpda"] if l["name"] == "H"), w50)
    json.dump(report, open(os.path.join(OUT, "pcb_report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
