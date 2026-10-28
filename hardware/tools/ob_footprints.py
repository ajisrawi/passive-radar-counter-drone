"""Give an OpenBoard project the footprints its schematic asks for.

    python tools/ob_footprints.py <board.openboard.json>

`openpcb sch-to-board` leaves every part as a placeholder ("Lib:Name?") until the project
library holds a footprint with exactly that name, but `openpcb import-footprint` stores KiCad
footprints under their bare name (or the name written inside the file, e.g. "easyeda2kicad:X").
This script imports every footprint the components reference - from KiCad's standard libraries
or the project library (prc = hardware/lib/prc.pretty) - and files each one under the
library-qualified name, then points the components at it.
"""
import json
import os
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
KICAD_FP = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
LIBS = {"prc": os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "prc.pretty")}


def source(qual):
    lib, name = qual.split(":", 1)
    folder = LIBS.get(lib, os.path.join(KICAD_FP, lib + ".pretty"))
    return os.path.join(folder, name + ".kicad_mod")


def unnumbered_pads(path):
    """Unnumbered pads of a .kicad_mod: [(kind, x, y, w, h)] with kind 'paste' (SMD aperture with no
    copper layer) or 'npth' (np_thru_hole: tooling/locating peg). Coordinates are KiCad's (y down).

    OpenBoard's importer numbers these pads "1", "2", ... or the next free number:
      * paste apertures become copper pads shorted to real pins (KiCad VQFN-16-1EP: four EP paste
        squares became pins 1-4 and shorted SW, PG and GND);
      * locating pegs become plated pads with no annular ring.
    """
    import re
    out = []
    txt = open(path, encoding="utf-8").read()
    for m in re.finditer(r'\(pad ""\s+(\w+)\s+\w+.*?\(at\s+([-\d.]+)\s+([-\d.]+).*?\(size\s+([\d.]+)\s+([\d.]+)\)'
                         r'(.*?)\(layers([^)]*)\)', txt, re.S):
        ptype, x, y, w, h, _, layers = m.groups()
        if ptype == "np_thru_hole":
            kind = "npth"
        elif ptype == "smd" and "Cu" not in layers:
            kind = "paste"
        elif ptype == "thru_hole":
            kind = "via"  # e.g. thermal vias in an exposed pad: they belong to the pad they sit in
        else:
            continue
        out.append((kind, float(x), float(y), float(w), float(h)))
    return out


def drop_unnumbered(fp, path):
    """Remove imported paste apertures; turn imported locating pegs into non-plated holes.
    OpenBoard footprints are y-up, so a KiCad pad at (x, y) is imported at (x, -y)."""
    src = unnumbered_pads(path)

    def match(p, x, y, w, h):
        return (abs(p["x"] - x) < 1e-3 and abs(p["y"] + y) < 1e-3 and
                abs(p["w"] - w) < 1e-3 and abs(p["h"] - h) < 1e-3)

    removed = pegs = 0
    keep = []
    for p in fp["pads"]:
        hit = next((s for s in src if match(p, *s[1:])), None)
        if hit and hit[0] == "paste":
            removed += 1
            continue
        if hit and hit[0] == "npth":
            p["npth"] = True
            p["id"] = "NP"  # the importer's "1"/"2" would make the peg a pin of that net (SFP cage: GND, TX_FAULT)
            pegs += 1
        if hit and hit[0] == "via":
            host = next((q for q in fp["pads"] if q is not p and abs(q["x"] - p["x"]) <= q["w"] / 2 and
                         abs(q["y"] - p["y"]) <= q["h"] / 2 and not q.get("th")), None)
            if host:
                p["id"] = host["id"]  # join the exposed pad's net
        keep.append(p)
    fp["pads"] = keep
    return removed, pegs


def custom_pads(path):
    """[(number, pad_x, pad_y, [(x, y), ...])] for KiCad custom-shape pads (gr_poly primitive, pad rotation 0)."""
    import re
    txt = open(path, encoding="utf-8").read()
    out = []
    for m in re.finditer(r'\(pad\s+"?([^"\s]*)"?\s+\w+\s+custom\s+\(at\s+([-\d.]+)\s+([-\d.]+)[^)]*\).*?\(pts\s+(.*?)\)\s*\)',
                         txt, re.S):
        pts = [(float(a), float(b)) for a, b in re.findall(r'\(xy\s+([-\d.]+)\s+([-\d.]+)', m.group(4))]
        out.append((m.group(1), float(m.group(2)), float(m.group(3)), pts))
    return out


def poly_to_rects(pts):
    """Cover a polygon with horizontal slabs, each cut to the x-range valid over the whole slab (never larger)."""
    ys = sorted({y for _, y in pts})
    edges = list(zip(pts, pts[1:] + pts[:1]))

    def spans(y):
        xs = sorted(x0 + (y - y0) * (x1 - x0) / (y1 - y0) for (x0, y0), (x1, y1) in edges
                    if (y0 <= y < y1) or (y1 <= y < y0))
        return list(zip(xs[0::2], xs[1::2]))

    rects = []
    for y0, y1 in zip(ys, ys[1:]):
        e = (y1 - y0) * 1e-3
        lo, hi = spans(y0 + e), spans(y1 - e)
        for (a0, b0), (a1, b1) in zip(lo, hi):
            a, b = max(a0, a1), min(b0, b1)
            if b - a > 0.02 and y1 - y0 > 0.02:
                rects.append((a, b, y0, y1))
    return rects


def fix_custom(fp, path):
    """OpenBoard keeps only the 0.005 mm anchor of a custom pad; rebuild it as rectangles with the same number."""
    fixed = 0
    for num, px, py, pts in custom_pads(path):
        fp["pads"] = [p for p in fp["pads"] if not (p["id"] == num and p["w"] < 0.05 and p["h"] < 0.05)]
        for a, b, y0, y1 in poly_to_rects(pts):
            # OpenBoard footprints are y-up: y_ob = -(y_kicad)
            fp["pads"].append({"id": num, "x": round(px + (a + b) / 2, 4), "y": round(-(py + (y0 + y1) / 2), 4),
                               "w": round(b - a, 4), "h": round(y1 - y0, 4), "shape": "rect", "th": False})
            fixed += 1
    return fixed


def main(board):
    d = json.load(open(board, encoding="utf-8"))
    wanted = sorted({c["footprint"].rstrip("?") for c in d["components"]})
    missing = [q for q in wanted if q not in d["footprints"]]
    files = [source(q) for q in missing]
    absent = [f for f in files if not os.path.exists(f)]
    if absent:
        raise SystemExit(f"footprint files not found: {absent}")
    if files:
        r = subprocess.run(["node", OPENPCB, "import-footprint", board, *files], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stderr or r.stdout)
        d = json.load(open(board, encoding="utf-8"))
    linked = 0
    for q in missing:
        name = q.split(":", 1)[1]
        key = next((k for k in d["footprints"] if k == name or k.split(":")[-1] == name), None)
        if key is None:
            raise SystemExit(f"import did not produce {q}")
        fp = dict(d["footprints"][key], name=q)
        dropped, pegs = drop_unnumbered(fp, source(q))
        if dropped or pegs:
            print(f"{q}: removed {dropped} paste-only pads, made {pegs} locating pegs non-plated")
        rebuilt = fix_custom(fp, source(q))
        if rebuilt:
            print(f"{q}: rebuilt custom-shape pad(s) as {rebuilt} rectangles")
        d["footprints"][q] = fp
        if key != q:
            del d["footprints"][key]
        linked += 1
    fixed = 0
    for c in d["components"]:
        if c["footprint"].endswith("?") and c["footprint"][:-1] in d["footprints"]:
            c["footprint"] = c["footprint"][:-1]
            fixed += 1
    json.dump(d, open(board, "w", encoding="utf-8"))
    left = [c["ref"] for c in d["components"] if c["footprint"].endswith("?")]
    print(json.dumps({"footprints_linked": linked, "components_resolved": fixed, "still_placeholder": left}))


if __name__ == "__main__":
    main(sys.argv[1])
