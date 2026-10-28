"""Close the open connections DRC reports on Board C2 with tools/handroute.py.

    python tools/fix_opens_c2.py [project] [--margin 3] [--only NET,NET] [--rounds 6]

Plane nets (GND, rails with an In4/In5 island) get a via down to their plane from each open end; signals are
routed end to end. Shortest opens first. A connection that finds no free path is retried with rip-up (other
nets' unlocked wires in the way are cut and become opens of their own for the next round).
"""
import json
import math
import os
import re
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
args = [x for x in sys.argv[1:]]
PROJ = os.path.abspath(args[0]) if args and not args[0].startswith("--") else os.path.join(HW, "board_c2", "board_c2.openboard.json")
MARGIN = args[args.index("--margin") + 1] if "--margin" in args else "3"
ONLY = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
ROUNDS = int(args[args.index("--rounds") + 1]) if "--rounds" in args else 6


def drc():
    r = subprocess.run(["node", OPENPCB, "drc", PROJ], capture_output=True, text=True)
    return json.loads(r.stdout)


def run(tool, extra):
    r = subprocess.run(tool + extra, capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip()
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "err": out[-200:]}


def one_round(rnd):
    d = json.load(open(PROJ, encoding="utf-8"))
    plane_nets = {z["net"] for z in d["zones"]}
    pair_nets = {x for p in d["diffPairs"] for x in (p["p"], p["n"])}
    opens = []
    for it in drc()["items"]:
        if it["kind"] != "unconnected":
            continue
        m = re.match(r"net (\S+): open connection \(([-\d.]+),([-\d.]+)\) to \(([-\d.]+),([-\d.]+)\)", it["message"])
        net, x1, y1, x2, y2 = m.group(1), *map(float, m.groups()[1:])
        if ONLY and net not in ONLY:
            continue
        opens.append((math.hypot(x2 - x1, y2 - y1), net, x1, y1, x2, y2))
    opens.sort()
    print(f"round {rnd}: {len(opens)} opens", flush=True)
    # pairs are never ripped by others (their coupling would be lost)
    keep = ["--keep-nets", ",".join(sorted(pair_nets))]
    for L, net, x1, y1, x2, y2 in opens:
        tool = [sys.executable, os.path.join(HW, "tools", "handroute.py"), PROJ, net]
        ends = [[str(x1), str(y1), "--to-plane"], [str(x2), str(y2), "--to-plane"]] if net in plane_nets else \
            [[str(x1), str(y1), str(x2), str(y2)]]
        for e in ends:
            hw = ["--hweight", "1.6"] if L > 30 else []
            r = run(tool, e + ["--margin", MARGIN] + hw)
            if not r.get("ok"):
                r = run(tool, e + ["--margin", str(float(MARGIN) + 2), "--rip"] + keep + hw)
            if not r.get("ok") and "--to-plane" in e:
                # no plane of this net under that end (e.g. +1V35 balls on the FPGA): go ball to ball
                r = run(tool, [str(x1), str(y1), str(x2), str(y2), "--margin", MARGIN, "--rip"] + keep + hw)
                if r.get("ok"):
                    break
            if not r.get("ok"):
                r = run(tool, e[:4 if "--to-plane" not in e else 3] + ["--margin", str(float(MARGIN) + 4), "--rip", "--rip-locked",
                                "--max-exp", "15000000"] + keep + (["--hweight", "2.0"] if L > 30 else []))
            print(" ", net, f"{L:.1f} mm", json.dumps({k: v for k, v in r.items() if k in ("ok", "vias", "length", "layers", "ripped", "err")}), flush=True)
    return len(opens)


def main():
    for rnd in range(1, ROUNDS + 1):
        if one_round(rnd) == 0:
            break
    print(drc()["summary"])


if __name__ == "__main__":
    main()
