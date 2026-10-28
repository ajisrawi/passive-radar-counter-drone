"""Copy EasyEDA's routing (Altium ASCII .pcbdoc export) onto the KiCad board (run with KiCad's Python).

    python.exe tools/import_easyeda_routing.py board_a <path/to/board_a.pcbdoc>
        -> <board>/<board>_easyeda_routed.kicad_pcb

Copper tracks and vias are read from the text records; the mil / Y-up coordinates are
mapped to KiCad mm / Y-down with a transform fitted on all component positions, so the
copper lands exactly on the KiCad footprints. Vias already present (e.g. GND fences) are
not duplicated.
"""
import math
import os
import sys

import pcbnew

HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
mm, MM = pcbnew.FromMM, pcbnew.ToMM
LAYERS = {"TOP": pcbnew.F_Cu, "BOTTOM": pcbnew.B_Cu, "MID1": pcbnew.In1_Cu, "MID2": pcbnew.In2_Cu,
          "MID3": pcbnew.In3_Cu, "MID4": pcbnew.In4_Cu, "MID5": pcbnew.In5_Cu, "MID6": pcbnew.In6_Cu}


def mil(v):
    return float(v.replace("mil", ""))


def main(board, pcbdoc):
    txt = open(pcbdoc, encoding="latin-1").read()
    recs = [dict(kv.split("=", 1) for kv in r.strip("|").split("|") if "=" in kv)
            for r in txt.split("\n") if r.startswith("|RECORD=")]
    net_names = {int(r["ID"]): r["NAME"] for r in recs if r["RECORD"] == "Net"}

    b = pcbnew.LoadBoard(os.path.join(HW, board, board + ".kicad_pcb"))
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}

    # fit x_k = s*x + ox, y_k = -s*y + oy (s = 0.0254 mm/mil) on matching components
    s = 0.0254
    pairs = [(mil(r["X"]), mil(r["Y"]), fps[r["SOURCEDESIGNATOR"]]) for r in recs
             if r["RECORD"] == "Component" and r.get("SOURCEDESIGNATOR") in fps]
    ox = sum(MM(fp.GetPosition().x) - s * x for x, y, fp in pairs) / len(pairs)
    oy = sum(MM(fp.GetPosition().y) + s * y for x, y, fp in pairs) / len(pairs)
    resid = max(math.hypot(s * x + ox - MM(fp.GetPosition().x), -s * y + oy - MM(fp.GetPosition().y))
                for x, y, fp in pairs)
    print(f"{len(pairs)} components matched, transform offset ({ox:.3f}, {oy:.3f}) mm, max residual {resid:.4f} mm")
    if resid > 0.05:
        raise SystemExit("placement differs between EasyEDA and KiCad - aborting")

    def P(x, y):
        return pcbnew.VECTOR2I(mm(s * mil(x) + ox), mm(-s * mil(y) + oy))

    def net(r):
        n = r.get("NET")
        return b.FindNet(net_names[int(n)]) if n not in (None, "-1") and int(n) in net_names else None

    existing = {(round(MM(t.GetPosition().x), 2), round(MM(t.GetPosition().y), 2))
                for t in b.GetTracks() if t.GetClass() == "PCB_VIA"}
    n_tr = n_via = skipped = 0
    for r in recs:
        if r["RECORD"] == "Track" and r["LAYER"] in LAYERS:
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(P(r["X1"], r["Y1"]))
            t.SetEnd(P(r["X2"], r["Y2"]))
            t.SetWidth(mm(s * mil(r["WIDTH"])))
            t.SetLayer(LAYERS[r["LAYER"]])
            n_ = net(r)
            if n_:
                t.SetNet(n_)
            b.Add(t)
            n_tr += 1
        elif r["RECORD"] == "Via":
            p = P(r["X"], r["Y"])
            key = (round(MM(p.x), 2), round(MM(p.y), 2))
            if key in existing:
                skipped += 1
                continue
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(p)
            v.SetWidth(mm(s * mil(r["DIAMETER"])))
            v.SetDrill(mm(s * float(r["HOLESIZE"].replace("mil", ""))))
            n_ = net(r)
            if n_:
                v.SetNet(n_)
            b.Add(v)
            existing.add(key)
            n_via += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    out = os.path.join(HW, board, board + "_easyeda_routed.kicad_pcb")
    b.Save(out)
    print(f"added {n_tr} tracks and {n_via} vias ({skipped} vias already present) -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
