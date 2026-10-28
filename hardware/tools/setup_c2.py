"""Create the Board C2 OpenBoard project from the OpenSchematic design (10 layers, real footprints).

    python tools/setup_c2.py

`openpcb new` makes 2- or 4-layer boards, so the layer list is widened to a 10-layer stack:
F.Cu sig | In1 GND | In2 sig | In3 sig | In4 +1V35/+1V0 | In5 VADJ/+3V3 | In6 sig | In7 sig | In8 GND | B.Cu sig.
Six signal layers: with 8 layers (4 signal) the router plateaued at ~1100 conflicts, 43 % of all copper
and 57 % of the conflicts on F.Cu (escape from the FFG676 and the x32 DDR3 channel). Through vias only
(no blind/buried spans) so JLCPCB's standard multilayer process can build it.
"""
import json
import os
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(HW, "board_c2")
PROJ = os.path.join(BASE, "board_c2.openboard.json")
W, H = 220.0, 190.0
STACK = [("F.Cu", "signal"), ("In1.Cu", "power"), ("In2.Cu", "signal"), ("In3.Cu", "signal"),
         ("In4.Cu", "power"), ("In5.Cu", "power"), ("In6.Cu", "signal"), ("In7.Cu", "signal"),
         ("In8.Cu", "power"), ("B.Cu", "signal")]
DIRECTION = {"F.Cu": "horizontal", "In2.Cu": "vertical", "In3.Cu": "horizontal", "In6.Cu": "vertical",
             "In7.Cu": "horizontal", "B.Cu": "vertical"}


def op(*args):
    r = subprocess.run(["node", OPENPCB, *args], capture_output=True, text=True)
    if r.returncode not in (0, 2):
        raise SystemExit(f"openpcb {args[0]} failed: {r.stderr or r.stdout}")
    return r.stdout


def main():
    if os.path.exists(PROJ):
        os.remove(PROJ)
    op("new", PROJ, "--name", "board_c2", "--layers", "4", "--width", str(W), "--height", str(H))
    d = json.load(open(PROJ, encoding="utf-8"))
    tmpl = d["layers"][0]
    colors = ["#e8492f", "#7f7fd8", "#d8a03f", "#c25fd8", "#5fb3d8", "#9bd85f", "#d85f8f", "#3fd8c2",
              "#a0a0a0", "#3f7fe8"]
    d["layers"] = [dict(tmpl, name=n, type=t, color=c, direction=DIRECTION.get(n, "horizontal"))
                   for (n, t), c in zip(STACK, colors)]
    json.dump(d, open(PROJ, "w", encoding="utf-8"))
    print(op("sch-to-board", os.path.join(BASE, "board_c2.sch.json"), PROJ)[:300])
    subprocess.run([sys.executable, os.path.join(HW, "tools", "ob_footprints.py"), PROJ], check=True)
    print(op("info", PROJ)[:400])


if __name__ == "__main__":
    main()
