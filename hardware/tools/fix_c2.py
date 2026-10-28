"""Board C2 clean-up after the autoroute (tools/route_c2.py).

    python tools/fix_c2.py

1. Test points of rails that now live on plane islands (MGTAVCC, MGTAVTT, VADJ) move from the power band
   onto their island (their islands are on In4/In5; in the band the test points were left unconnected).
2. Copper that breaks a rule and is easier rerouted than repaired is removed: the SFP1 TX pair (its two lanes
   folded across each other at a cap breakout) and exact duplicate vias (same net, place and padstack).
3. The open connections are finished by OpenRoute's shape-based router (--gridless --finish keeps all copper,
   rip-up-able, and completes the rest).
"""
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout_a2 import extents  # noqa: E402

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(HW, "board_c2")
PROJ = os.path.join(BASE, "board_c2.openboard.json")
REROUTE = ("SFP1_TXP_FPGA", "SFP1_TXN_FPGA")
# test point -> where to look for a free spot (x0, y0, x1, y1): beside the MGT ferrites / on the VADJ island
TP_SPOTS = {"MGTAVCC": (111.0, 52.0, 140.0, 66.0), "MGTAVTT": (111.0, 52.0, 140.0, 66.0),
            "VADJ": (150.0, 100.0, 195.0, 125.0)}


def boxes(d, skip=()):
    out = []
    for c in d["components"]:
        if c["ref"] in skip:
            continue
        a, b, cc, dd = extents(d["footprints"][c["footprint"]])
        r = c.get("rot", 0)
        if r in (90, 270):
            a, b, cc, dd = -dd, -cc, a, b
        if c.get("side") == "back":
            a, b = -b, -a
        out.append((c["x"] + a, c["y"] + cc, c["x"] + b, c["y"] + dd, c.get("side", "front")))
    return out


def free_spot(d, ref, region, taken):
    c = next(x for x in d["components"] if x["ref"] == ref)
    a, b, cc, dd = extents(d["footprints"][c["footprint"]])
    occ = boxes(d, skip=(ref,)) + taken
    # copper on F.Cu is in the way too (the test point is an F.Cu pad)
    wires = [(t["points"], t["width"]) for t in d["traces"] if t["layer"] == "F.Cu"]
    x0, y0, x1, y1 = region
    y = y0
    while y + (dd - cc) <= y1:
        x = x0
        while x + (b - a) <= x1:
            bx = (x - 0.3, y - 0.3, x + (b - a) + 0.3, y + (dd - cc) + 0.3)
            if not any(o[4] == "front" and not (bx[2] <= o[0] or bx[0] >= o[2] or bx[3] <= o[1] or bx[1] >= o[3]) for o in occ):
                cx, cy = x - a, y - cc
                r = max(b - a, dd - cc) / 2 + 0.25
                if all(min_dist(cx, cy, pts) > r + w / 2 for pts, w in wires):
                    return cx, cy
            x += 0.5
        y += 0.5
    return None


def min_dist(px, py, pts):
    m = 1e9
    for p, q in zip(pts, pts[1:]):
        dx, dy = q["x"] - p["x"], q["y"] - p["y"]
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - p["x"]) * dx + (py - p["y"]) * dy) / L2))
        m = min(m, math.hypot(px - p["x"] - t * dx, py - p["y"] - t * dy))
    return m


def main():
    d = json.load(open(PROJ, encoding="utf-8"))
    tp_net = {p.split("-")[0]: n["name"] for n in d["nets"] for p in n["pins"] if p.startswith("TP")}
    cmds, taken = [], []
    for ref, net in sorted(tp_net.items()):
        if net not in TP_SPOTS:
            continue
        spot = free_spot(d, ref, TP_SPOTS[net], taken)
        if not spot:
            print(f"no free spot for {ref} ({net})")
            continue
        cmds.append(["move", ref, f"{spot[0]:.3f}", f"{spot[1]:.3f}", "--rot", "0"])
        taken.append((spot[0] - 1, spot[1] - 1, spot[0] + 1, spot[1] + 1, "front"))
        print(f"{ref} ({net}) -> {spot[0]:.2f}, {spot[1]:.2f}")
    if cmds:
        bfile = os.path.join(BASE, "fix_batch.json")
        json.dump(cmds, open(bfile, "w"))
        subprocess.run(["node", OPENPCB, "batch", PROJ, bfile], capture_output=True, text=True, check=True)

    d = json.load(open(PROJ, encoding="utf-8"))
    n0, v0 = len(d["traces"]), len(d["vias"])
    d["traces"] = [t for t in d["traces"] if t["net"] not in REROUTE]
    seen, vias = set(), []
    for v in d["vias"]:
        if v.get("net") in REROUTE:
            continue
        k = (v.get("net"), round(v["x"], 3), round(v["y"], 3), v.get("drill"), v.get("diameter"),
             v.get("from"), v.get("to"), v.get("layers") and tuple(v["layers"]))
        if k in seen:
            continue
        seen.add(k)
        vias.append(v)
    d["vias"] = vias
    json.dump(d, open(PROJ, "w", encoding="utf-8"))
    print(f"removed {n0 - len(d['traces'])} traces and {v0 - len(d['vias'])} vias")

    r = subprocess.run(["node", OPENPCB, "route", PROJ, "--gridless", "--finish", "--passes", "8",
                        "--time-limit", "3600", "--log", os.path.join(BASE, "fix_route.log")],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    res = json.loads(out) if out.startswith("{") else {"raw": (out + r.stderr)[:400]}
    print(json.dumps({k: v for k, v in res.items() if k not in ("imported", "passes", "log")})[:500])


if __name__ == "__main__":
    main()
