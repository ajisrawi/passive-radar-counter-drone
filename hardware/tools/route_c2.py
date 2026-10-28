"""Route Board C2 in phases with OpenRoute (OpenBoard's router).

    python tools/route_c2.py [project.openboard.json]

Phase 1a: the 43 differential pairs (10G lanes, reference clocks, DDR CK/DQS, AD9361 LVDS) with the
shape-based router (--gridless), which routes a two-pin pair as one coupled carrier. The grid router only
makes the partner's lane cheaper to follow, and in the earlier two-phase run none of the pairs came out
coupled.
Phase 1b: the single-ended DDR3 nets with the grid router's full script (route, clean, second stage,
tune) on the nearly empty board, so they get the straight paths and the room for serpentines.
Each phase's copper is locked before the next.
Phase 2: everything else around it (--keep).

Pair gaps are 0.2 mm so the partner sits on the routing lattice (width + gap = 0.3 mm = 3 x 0.1 mm).
"""
import json
import os
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(HW, "board_c2")
PROJ = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(BASE, "board_c2.openboard.json")
TAG = os.path.splitext(os.path.splitext(os.path.basename(PROJ))[0])[0]


def route(*extra, log):
    r = subprocess.run(["node", OPENPCB, "route", PROJ, "--log", os.path.join(BASE, f"{TAG}_{log}"), *extra],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    return json.loads(out) if out.startswith("{") else {"raw": (out + r.stderr)[:500]}


def lock(nets):
    d = json.load(open(PROJ, encoding="utf-8"))
    n = 0
    for t in d["traces"]:
        if t["net"] in nets:
            t["locked"] = True
            n += 1
    for v in d["vias"]:
        if v.get("net") in nets:
            v["locked"] = True
    json.dump(d, open(PROJ, "w", encoding="utf-8"))
    return n


def show(tag, r):
    print(tag, json.dumps({k: v for k, v in r.items() if k not in ("imported", "passes")})[:400], flush=True)


def main():
    d = json.load(open(PROJ, encoding="utf-8"))
    pairs = {x for p in d["diffPairs"] for x in (p["p"], p["n"])}
    ddr = {n["name"] for n in d["nets"] if n["name"].startswith("DDR_") and n["name"] not in ("DDR_VTT", "DDR_VREF")} - pairs
    if "--from-1b" not in sys.argv:
        show("phase 1a pairs:", route("--gridless", "--nets", ",".join(sorted(pairs)), "--passes", "8", "--time-limit", "2400", log="p1a.log"))
        # the shape router can lay a connection twice along the same lane; strip it before tuning sees it
        subprocess.run([sys.executable, os.path.join(HW, "tools", "dedupe_traces.py"), PROJ], check=True)
        print(f"locked {lock(pairs)} pair segments", flush=True)
    show("phase 1b DDR3:", route("--nets", ",".join(sorted(ddr)), log="p1b.log"))
    print(f"locked {lock(pairs | ddr)} critical segments", flush=True)
    show("phase 2:", route("--keep", log="p2.log"))


if __name__ == "__main__":
    main()
