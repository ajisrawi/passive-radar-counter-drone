"""Freerouting round trip (run with KiCad's Python).

    python.exe tools/freeroute.py export board_b      -> board_b/route/board_b.dsn
    python.exe tools/freeroute.py import board_b      <- board_b/route/board_b.ses -> board_b/board_b_routed.kicad_pcb

Plane layers are marked as power layers in the DSN so Freerouting only routes on the
signal layers (Top, In2, In5, Bottom) and drops vias into the planes for plane nets.
"""
import os
import sys

import pcbnew

HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLANES = {  # inner layers that are solid planes (see boards/layout_*.py)
    "board_b": ["In1.Cu", "In3.Cu", "In4.Cu", "In6.Cu"],
    "board_c": ["In1.Cu", "In3.Cu", "In4.Cu", "In6.Cu"],
    "board_a": ["In1.Cu", "In2.Cu"],
}


def load(board, routed=False):
    name = board + ("_routed" if routed else "")
    return pcbnew.LoadBoard(os.path.join(HW, board, name + ".kicad_pcb"))


def export(board, routed=False):
    """routed=True starts from <board>_routed.kicad_pcb so Freerouting keeps the existing wiring."""
    b = load(board, routed)
    for lname in PLANES[board]:
        b.SetLayerType(b.GetLayerID(lname), pcbnew.LT_POWER)
    os.makedirs(os.path.join(HW, board, "route"), exist_ok=True)
    dsn = os.path.join(HW, board, "route", board + ".dsn")
    ok = pcbnew.ExportSpecctraDSN(b, dsn)
    print("exported", dsn, ok)


def import_ses(board):
    b = load(board)
    for lname in PLANES[board]:
        b.SetLayerType(b.GetLayerID(lname), pcbnew.LT_POWER)
    ses = os.path.join(HW, board, "route", board + ".ses")
    ok = pcbnew.ImportSpecctraSES(b, ses)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    out = os.path.join(HW, board, board + "_routed.kicad_pcb")
    b.Save(out)
    tracks = [t for t in b.GetTracks()]
    vias = [t for t in tracks if t.GetClass() == "PCB_VIA"]
    print("imported", ses, ok, "->", out, f"{len(tracks) - len(vias)} track segments, {len(vias)} vias")


if __name__ == "__main__":
    {"export": export, "export_routed": lambda bd: export(bd, True), "import": import_ses}[sys.argv[1]](sys.argv[2])
