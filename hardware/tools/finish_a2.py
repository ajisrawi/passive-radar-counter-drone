"""Finish a routed Board A2 build in OpenBoard: CAL length matching, RF via fences, checks, fab files.

    python tools/finish_a2.py <uhf|mid|high|n78>

1. Length group "CAL" (CH0_CAL..CH5_CAL, 0.2 mm tolerance) + `openpcb tune`. Every calibration
   line from the noise splitter to a switch must have the same electrical length, otherwise the
   difference shows up as a channel phase error during calibration.
2. GND via fences along every RF lane net on F.Cu (`openpcb fence`, 2 mm pitch).
3. DRC and pour connectivity (`openpcb drc`, `openpcb pourcheck --net GND`).
4. Gerber + Excellon (zip) and JLCPCB BOM / pick-and-place into board_a2/<band>/fab/.
"""
import json
import math
import os
import re
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RF_NET = re.compile(r"^CH[0-9]_(ANT|SW_O1|SW_IN|LNA|F|SPL|OUT)")


def op(*args):
    r = subprocess.run(["node", OPENPCB, *args], capture_output=True, text=True)
    if r.returncode not in (0, 2):
        raise SystemExit(f"openpcb {args[0]} failed: {r.stderr or r.stdout}")
    out = r.stdout.strip()
    return json.loads(out) if out.startswith("{") else {"raw": out}


def net_lengths(proj, nets):
    d = json.load(open(proj, encoding="utf-8"))
    via_len = d["rules"].get("viaLength", 1.6)
    out = {n: 0.0 for n in nets}
    for t in d["traces"]:
        if t.get("net") in out:
            pts = t.get("points") or [t.get("a"), t.get("b")]
            out[t["net"]] += sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(pts, pts[1:]))
    for v in d["vias"]:
        if v.get("net") in out:
            out[v["net"]] += via_len
    return {k: round(v, 2) for k, v in out.items()}


def fill_bom(base, band):
    """OpenBoard's BOM leaves 'JLCPCB Part #' empty (the LCSC field does not survive the schematic
    import); copy each designator's LCSC number from the generator netlist. Generic passives stay
    blank for JLCPCB's value/footprint matcher, as in the original release BOMs."""
    import csv
    parts = json.load(open(os.path.join(base, f"board_a2_{band}.netlist.json")))["parts"]
    path = os.path.join(base, "fab", f"board_a2_{band}-BOM.csv")
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    head, body = rows[0], rows[1:]
    col = head.index("JLCPCB Part #")
    filled = 0
    for r in body:
        refs = [x.strip() for x in r[1].split(",")]
        codes = {parts[x]["lcsc"] for x in refs if x in parts and parts[x].get("lcsc")}
        if len(codes) == 1:
            r[col] = codes.pop()
            filled += 1
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([head] + body)
    return filled, len(body)


def main(band):
    base = os.path.join(HW, "board_a2", band)
    proj = os.path.join(base, f"board_a2_{band}.openboard.json")
    cal = [f"CH{k}_CAL" for k in range(6)]

    # 1. matched CAL lengths
    d = json.load(open(proj, encoding="utf-8"))
    d["lengthGroups"] = [g for g in d.get("lengthGroups", []) if g["name"] != "CAL"] + [
        {"name": "CAL", "nets": cal, "tolerance": 0.2}]
    json.dump(d, open(proj, "w", encoding="utf-8"))
    before = net_lengths(proj, cal)
    tune = op("tune", proj)
    after = net_lengths(proj, cal)

    # 2. RF via fences
    rf = sorted(n["name"] for n in d["nets"] if RF_NET.match(n["name"]))
    bfile = os.path.join(base, "fence_batch.json")
    json.dump([["fence", "--net", n, "--guard", "GND", "--spacing", "2", "--layers", "F.Cu"] for n in rf], open(bfile, "w"))
    fence = op("batch", proj, bfile)
    added = sum((x.get("result") or {}).get("added", 0) for x in fence.get("results", []))

    # 3. checks
    drc = op("drc", proj)
    pour = op("pourcheck", proj, "--net", "GND")

    # 4. fabrication outputs
    fab = os.path.join(base, "fab")
    os.makedirs(fab, exist_ok=True)
    gerb = op("gerber", proj, fab, "--zip", "--name", f"board_a2_{band}")
    asm = op("assembly", proj, fab, "--name", f"board_a2_{band}")
    asm["bom_lines_with_lcsc"] = "%d of %d" % fill_bom(base, band)
    report = {"band": band, "cal_before_mm": before, "cal_after_mm": after,
              "cal_spread_after_mm": round(max(after.values()) - min(after.values()), 2),
              "tune": {k: v for k, v in tune.items() if k != "raw"} or tune.get("raw", "")[:300],
              "fence_vias": added, "drc": drc.get("summary"), "drc_violations": drc.get("violations"),
              "gnd_pour": {k: v for k, v in pour.items() if not isinstance(v, list)},
              "gerber": gerb.get("file") or gerb, "assembly": {k: v for k, v in asm.items() if k != "ok"}}
    json.dump(report, open(os.path.join(base, "finish_report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1)[:3000])


if __name__ == "__main__":
    main(sys.argv[1])
