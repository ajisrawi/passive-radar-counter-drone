"""Remove dangling copper (run with KiCad's Python) from <board>/<board>_routed.kicad_pcb.

    python.exe tools/clean_dangling.py board_b

Repeatedly deletes track segments with a free end (an end touching no pad, via or other
segment of the same net) and signal-net vias with at most one track attached, until none
are left. Vias on plane nets are kept: they connect through the inner planes.
"""
import collections
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_drc import HW, PLANE_NETS  # noqa: E402

TOL = 2000  # nm; endpoints closer than this count as joined


def key(p):
    return (round(p.x / TOL), round(p.y / TOL))


def main(board):
    path = os.path.join(HW, board, board + "_routed.kicad_pcb")
    b = pcbnew.LoadBoard(path)
    planes = PLANE_NETS[board]
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    removed_t = removed_v = 0
    while True:
        tracks = [t for t in b.GetTracks() if t.GetClass() != "PCB_VIA"]
        vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
        ends = collections.Counter()
        for t in tracks:
            for p in (t.GetStart(), t.GetEnd()):
                ends[(t.GetNetCode(), t.GetLayer(), key(p))] += 1

        def anchored(net, layer, p):
            if any(v.GetNetCode() == net and v.HitTest(p) for v in vias):
                return True
            return any(pd.GetNetCode() == net and pd.IsOnLayer(layer) and pd.HitTest(p) for pd in pads)

        dead = [t for t in tracks if any(ends[(t.GetNetCode(), t.GetLayer(), key(p))] < 2 and
                                         not anchored(t.GetNetCode(), t.GetLayer(), p) for p in (t.GetStart(), t.GetEnd()))]
        lone = []
        for v in vias:
            if v.GetNetname() in planes:
                continue
            n = sum(1 for t in tracks if t.GetNetCode() == v.GetNetCode() and (v.HitTest(t.GetStart()) or v.HitTest(t.GetEnd())))
            if n <= 1 and not any(pd.GetNetCode() == v.GetNetCode() and pd.HitTest(v.GetPosition()) for pd in pads):
                lone.append(v)
        if not dead and not lone:
            break
        for t in dead:
            b.Delete(t)
        for v in lone:
            b.Delete(v)
        removed_t += len(dead)
        removed_v += len(lone)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)
    print(f"removed {removed_t} dangling track segments and {removed_v} dangling vias")


if __name__ == "__main__":
    main(sys.argv[1])
