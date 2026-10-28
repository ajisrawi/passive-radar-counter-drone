"""Apply a Board B band variant to the routed OpenBoard layout as a minimal ECO.

    python tools/eco_b_band.py <mid|high|n78>

Starts from board_b/route/board_b_routed.openboard.json (finished, DRC-clean) and changes only what
the variant schematic changes (boards/board_b.py BAND_PARTS):
  * T1-T6: ATB2012-50011 (40-860 MHz) -> TCM1-63AX+ (10 MHz-6 GHz). Pins: BAL -> 3, GND -> 2,
    BP -> 6 (secondary dot), BN -> 4. The larger body is rotated 90 deg and moved 0.7 mm away from
    the SMA so it clears the connector and the coupling caps.
  * The 12 AC-coupling caps get the band value.
Copper on the balun nets (CHx_BAL/BP/BN) and any GND via/trace under the new body is removed for
`openpcb route --keep` to redo. A full `openpcb sch-to-board` sync is not used: it also removes
the DNP footprints (optional attenuator pads) and renames footprints the routed board already has.
Writes board_b_bands/<band>/board_b_<band>.openboard.json.
"""
import json
import os
import shutil
import subprocess
import sys

HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TCM = "prc:XFMR-SMD_TCM1-63AX"
DY, ROT = -0.7, 90  # move away from the SMA (board y-up: SMA sits above, at larger y)
DX = {"T6": 2.0}    # channel 5's attenuator resistors (R29-R31) sit right beside its balun


def main(band):
    base = os.path.join(HW, "board_b_bands", band)
    proj = os.path.join(base, f"board_b_{band}.openboard.json")
    shutil.copy(os.path.join(HW, "board_b", "route", "board_b_routed.openboard.json"), proj)
    want = json.load(open(os.path.join(base, f"board_b_{band}.netlist.json")))["parts"]
    d = json.load(open(proj, encoding="utf-8"))
    comps = {c["ref"]: c for c in d["components"]}

    # 1. parts: baluns and coupling caps
    changed = []
    for ref, p in want.items():
        c = comps.get(ref)
        if c is None:
            raise SystemExit(f"{ref} missing from the routed board")
        if ref.startswith("T") and p["value"] != c["value"]:
            c.update(footprint=TCM + "?", value=p["value"], rot=ROT, y=round(c["y"] + DY, 3),
                     x=round(c["x"] + DX.get(ref, 0.0), 3))
            changed.append(ref)
        elif ref.startswith("C") and p["value"] != c["value"] and not p.get("dnp"):
            c["value"] = p["value"]
            changed.append(ref)

    # 2. nets: balun pin numbers follow the new footprint
    pinmap = {ref: {num: net for num, net in want[ref]["pins"].items()} for ref in changed if ref.startswith("T")}
    for n in d["nets"]:
        n["pins"] = [x for x in n["pins"] if x.split("-")[0] not in pinmap]
    by_name = {n["name"]: n for n in d["nets"]}
    for ref, pins in pinmap.items():
        for num, net in pins.items():
            by_name[net]["pins"].append(f"{ref}-{num}")

    # 3. rip up copper the swap disturbs
    rip_nets = {f"CH{k}_{s}" for k in range(6) for s in ("BAL", "BP", "BN")}
    boxes = [(comps[r]["x"] - 3.2, comps[r]["y"] - 2.6, comps[r]["x"] + 3.2, comps[r]["y"] + 2.6) for r in pinmap]

    def under(x, y):
        return any(a <= x <= b and c <= y <= e for a, c, b, e in boxes)

    t0, v0 = len(d["traces"]), len(d["vias"])
    d["traces"] = [t for t in d["traces"] if t["net"] not in rip_nets and
                   not (t["net"] == "GND" and any(under(p["x"], p["y"]) for p in t["points"]))]
    d["vias"] = [v for v in d["vias"] if v.get("net") not in rip_nets and not under(v["x"], v["y"])]
    json.dump(d, open(proj, "w", encoding="utf-8"))
    subprocess.run([sys.executable, os.path.join(HW, "tools", "ob_footprints.py"), proj], check=True)
    print(json.dumps({"changed": changed, "traces_removed": t0 - len(d["traces"]), "vias_removed": v0 - len(d["vias"])}))


if __name__ == "__main__":
    main(sys.argv[1])
