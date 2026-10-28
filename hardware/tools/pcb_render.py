"""Render an OpenBoard board (.openboard.json) to a PNG snapshot: outline, zones, traces per layer, pads, vias.

    python hardware/tools/pcb_render.py <board.openboard.json> <out.png> ["Title"]
"""
import json
import math
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Circle, Polygon, Rectangle

BG = "#0d1117"
LAYER = {"F.Cu": "#e8492f", "B.Cu": "#3b82f6", "In1.Cu": "#a3e635", "In2.Cu": "#f59e0b", "In3.Cu": "#c084fc",
         "In4.Cu": "#22d3ee", "In5.Cu": "#f472b6", "In6.Cu": "#facc15"}


def render(path, out, title=None):
    d = json.load(open(path, encoding="utf-8"))
    ol = [(p["x"], p["y"]) for p in d["outline"]]
    xs, ys = [p[0] for p in ol], [p[1] for p in ol]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    fig = plt.figure(figsize=(9, 9 * h / w + 0.6), facecolor=BG)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96 - 0.6 / (9 * h / w + 0.6)])
    ax.set_facecolor(BG)
    ax.add_patch(Polygon(ol, closed=True, fc="#123524", ec="#9ca3af", lw=1.2, zorder=0))
    order = sorted({t["layer"] for t in d.get("traces", [])}, key=lambda n: (n == "F.Cu", n == "B.Cu"))
    for z in d.get("zones", []):
        if z["layer"] in ("F.Cu", "B.Cu"):
            ax.add_patch(Polygon([(p["x"], p["y"]) for p in z["points"]], closed=True,
                                 fc=LAYER.get(z["layer"], "#888"), alpha=0.10, ec="none", zorder=1))
    for i, layer in enumerate(order):                       # inner layers first, F.Cu on top
        segs, lws = [], []
        for t in d["traces"]:
            if t["layer"] != layer:
                continue
            pts = [(p["x"], p["y"]) for p in t["points"]]
            for a, b in zip(pts, pts[1:]):
                segs.append([a, b])
                lws.append(max(0.4, t["width"] * 72 * 9 / w / 25.4 * 25.4))
        a = 0.95 if layer in ("F.Cu", "B.Cu") else 0.55
        ax.add_collection(LineCollection(segs, colors=LAYER.get(layer, "#aaa"), linewidths=lws, alpha=a,
                                         capstyle="round", zorder=2 + i))
    fp = d["footprints"]
    pads = []
    for c in d["components"]:
        f = fp.get(c["footprint"]) or fp.get(c["footprint"] + "?") or {}
        r = math.radians(c.get("rot", 0))
        cs, sn = math.cos(r), math.sin(r)
        mir = -1 if c.get("side", "front") == "back" else 1
        for p in f.get("pads", []):
            px, py = p["x"] * mir, p["y"]
            x = c["x"] + px * cs - py * sn
            y = c["y"] + px * sn + py * cs
            pw, ph = p["w"], p["h"]
            if abs(sn) > 0.5:
                pw, ph = ph, pw
            if p.get("shape") in ("circle", "oval") and abs(pw - ph) < 1e-6:
                pads.append(Circle((x, y), pw / 2))
            else:
                pads.append(Rectangle((x - pw / 2, y - ph / 2), pw, ph))
    ax.add_collection(PatchCollection(pads, fc="#d4a017", ec="none", alpha=0.95, zorder=20))
    ax.add_collection(PatchCollection([Circle((v["x"], v["y"]), v["diameter"] / 2) for v in d.get("vias", [])],
                                      fc="#e5e7eb", ec="none", zorder=21))
    ax.set_xlim(min(xs) - 2, max(xs) + 2)
    ax.set_ylim(max(ys) + 2, min(ys) - 2)
    ax.set_aspect("equal")
    ax.axis("off")
    nt = len(d.get("traces", []))
    sub = f"{w:.0f} × {h:.0f} mm · {len(d['components'])} parts · {nt} traces · {len(d.get('vias', []))} vias · {len(d['layers'])} layers"
    fig.text(0.5, 0.995, (title or d.get("name", "")) + "\n" + sub, color="#e5e7eb", ha="center", va="top", fontsize=11)
    fig.savefig(out, dpi=130, facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
