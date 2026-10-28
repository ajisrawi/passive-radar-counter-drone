"""Remove the copper behind each clearance / hole-to-hole DRC error on Board C2, so tools/fix_opens_c2.py can
route that piece again around the obstacle.

    python tools/rip_c2.py [project]

clearance "pad P to wire N"   -> the segment of N's wire nearest the error is cut out of its trace
clearance "wire A to wire B"  -> the segment of the wire not locked (else B) is cut out
hole-to-hole (same net)       -> one via of the two is removed (prefer the unlocked one, then the micro via)
"""
import json
import math
import os
import re
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJ = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HW, "board_c2", "board_c2.openboard.json")


def seg_dist(px, py, a, b):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - a["x"]) * dx + (py - a["y"]) * dy) / L2))
    return math.hypot(px - a["x"] - t * dx, py - a["y"] - t * dy)


def main():
    items = json.loads(subprocess.run(["node", OPENPCB, "drc", PROJ], capture_output=True, text=True).stdout)["items"]
    d = json.load(open(PROJ, encoding="utf-8"))
    nid = d["nextId"]
    for it in items:
        x, y, layer = it["at"]["x"], it["at"]["y"], it["layer"]
        if it["kind"] in ("clearance", "hole-to-copper"):
            m = re.match(r"(pad|wire|via|blind via) (\S+)(?: hole)? to (pad|wire|trace|via|blind via) (\S+):", it["message"].replace(" to trace ", " to wire "))
            if not m:
                print("skip", it["message"])
                continue
            cands = []
            if m.group(3) == "wire":
                cands.append(m.group(4))
            if m.group(1) == "wire":
                cands.append(m.group(2))
            best = None
            for t in d["traces"]:
                if t["net"] not in cands or t["layer"] != layer:
                    continue
                for k, (p, q) in enumerate(zip(t["points"], t["points"][1:])):
                    dist = seg_dist(x, y, p, q) - t["width"] / 2
                    key = (bool(t.get("locked")), dist)
                    if dist < 0.8 and (best is None or key < best[0]):
                        best = (key, t, k)
            if not best:
                print("nothing to cut for", it["message"])
                continue
            _, t, k = best
            pts = t["points"]
            d["traces"].remove(t)
            for part in (pts[:k + 1], pts[k + 1:]):
                if len(part) >= 2:
                    nt = dict(t, id=nid, points=part)
                    nt.pop("locked", None)
                    d["traces"].append(nt)
                    nid += 1
            print(f"cut {t['net']} {layer} segment {k} near ({x:.2f},{y:.2f})")
        elif it["kind"] == "hole-to-hole":
            m = re.match(r"via (\S+) to via (\S+):", it["message"])
            if not m or m.group(1) != m.group(2):
                print("skip", it["message"])
                continue
            vs = sorted((v for v in d["vias"] if v.get("net") == m.group(1) and math.hypot(v["x"] - x, v["y"] - y) < 0.4),
                        key=lambda v: (bool(v.get("locked")), -(v["drill"] <= 0.1)))
            if len(vs) >= 2:
                d["vias"].remove(vs[0])
                print(f"removed via {vs[0]['net']} {vs[0]['from']}-{vs[0]['to']} at ({vs[0]['x']},{vs[0]['y']})")
    d["nextId"] = nid
    json.dump(d, open(PROJ, "w", encoding="utf-8"))


if __name__ == "__main__":
    main()
