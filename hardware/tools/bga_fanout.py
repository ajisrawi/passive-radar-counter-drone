"""BGA / plane-pad fan-out (run with KiCad's Python) on <board>/<board>_routed.kicad_pcb.

    python.exe tools/bga_fanout.py board_b

Under a BGA the outer-layer GND pour breaks into small islands that join a few GND balls
(or the GND pads of nearby decoupling caps) but have no via down to the GND planes, so
DRC reports them unconnected. Every such island, and every plane-net pad DRC still reports
unconnected, gets one through via with a short stub from one of its pads:

* BGA balls use a dog-bone: the via sits in a diagonal gap between four balls, the gap
  facing away from the chip centre first.
* Other pads use the first free spot on rings around the pad.

If no pad of an island has a free spot, the spot with the fewest other-net tracks in the
way (at most MAX_RIP) is cleared: those track segments are deleted and their nets listed,
for Freerouting to reroute. Vias and pads are never moved.
"""
import json
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_drc  # noqa: E402  (shared clearance checks)

HW = fix_drc.HW
mm, MM = pcbnew.FromMM, pcbnew.ToMM
STUB_W = 0.2
MAX_RIP = 4


def drc_unconnected_pads(board):
    """(ref, pad number) of pads the last DRC run reports as unconnected."""
    path = os.path.join(HW, board, "drc_after_fix.json")
    out = set()
    if os.path.exists(path):
        for u in json.load(open(path)).get("unconnected_items", []):
            for it in u["items"]:
                d = it["description"]
                if d.startswith("Pad") and " of " in d:
                    out.add((d.split(" of ")[1].split()[0], d.split()[1]))
    return out


def sites_for(pad, bga):
    """Candidate via spots around a pad, best first."""
    px, py = MM(pad.GetPosition().x), MM(pad.GetPosition().y)
    if bga:
        cx, cy, h = bga
        sx = 1 if px >= cx else -1
        sy = 1 if py >= cy else -1
        return [(px + sx * h, py + sy * h), (px + sx * h, py - sy * h), (px - sx * h, py + sy * h),
                (px - sx * h, py - sy * h)]
    half = max(MM(pad.GetBoundingBox().GetWidth()), MM(pad.GetBoundingBox().GetHeight())) / 2
    out = []
    for d in (half + 0.35, half + 0.55, half + 0.8, half + 1.1):
        out += [(px + d * math.cos(2 * math.pi * k / 16), py + d * math.sin(2 * math.pi * k / 16)) for k in range(16)]
    return out


def blockers(obs, x, y, net, layer, px, py, n_orig):
    """Indices of original other-net tracks that stop a via at (x, y) or the stub to it."""
    r = fix_drc.VIA_D / 2
    need_via = max(r + fix_drc.CLR, fix_drc.VIA_HOLE / 2 + fix_drc.HOLE_CLR)
    hit = []
    for i, (ax, ay, bx, by, hw, lay, n) in enumerate(obs.tracks[:n_orig]):
        if n == net or lay == -1:
            continue
        if fix_drc.seg_dist(x, y, ax, ay, bx, by) < need_via + hw:
            hit.append(i)
        elif lay == layer and any(
                fix_drc.seg_dist(px + k / 5 * (x - px), py + k / 5 * (y - py), ax, ay, bx, by)
                < STUB_W / 2 + hw + fix_drc.CLR for k in range(6)):
            hit.append(i)
    return hit


def main(board):
    path = os.path.join(HW, board, board + "_routed.kicad_pcb")
    b = pcbnew.LoadBoard(path)
    fix_drc.CLR = MM(b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().GetClearance())
    fix_drc.FAN_W = STUB_W
    planes = fix_drc.PLANE_NETS[board]
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    obs = fix_drc.Obstacles(b)
    track_items = [t for t in b.GetTracks() if t.GetClass() != "PCB_VIA"]  # same order as obs.tracks
    n_orig = len(track_items)

    bga = {}  # footprint ref -> (centre x, centre y, half pitch)
    for fp in b.GetFootprints():
        pads = list(fp.Pads())
        if len(pads) >= 100 and "BGA" in str(fp.GetFPID().GetLibItemName()).upper():
            xs = sorted({round(MM(p.GetPosition().x), 3) for p in pads})
            pitch = min(q - p for p, q in zip(xs, xs[1:]))
            bga[fp.GetReference()] = (MM(fp.GetPosition().x), MM(fp.GetPosition().y), pitch / 2)

    # groups of pads that each need one via: outer-pour islands with no via, then lone unconnected pads
    groups = []
    covered = set()
    for z in b.Zones():
        if z.GetNetname() not in planes or z.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        layer, net = z.GetLayer(), z.GetNetname()
        polys = z.GetFilledPolysList(layer)
        net_pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetname() == net and p.IsOnLayer(layer)]
        net_vias = [pcbnew.VECTOR2I(mm(x), mm(y)) for x, y, _, n in obs.vias if n == net]
        for i in range(polys.OutlineCount()):
            o = polys.Outline(i)
            if any(o.PointInside(v) for v in net_vias):
                continue
            pads = [p for p in net_pads if o.PointInside(p.GetPosition())]
            if pads:
                groups.append((layer, pads))
                covered |= {id(p) for p in pads}
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
    for ref, num in sorted(drc_unconnected_pads(board)):
        for p in (fps[ref].Pads() if ref in fps else []):
            if p.GetNumber() == num and p.GetNetname() in planes and id(p) not in covered:
                groups.append((pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu, [p]))

    def place(pad, layer, x, y):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(fix_drc.VIA_D))
        v.SetDrill(mm(fix_drc.VIA_HOLE))
        v.SetNet(pad.GetNet())
        b.Add(v)
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pad.GetPosition())
        t.SetEnd(pcbnew.VECTOR2I(mm(x), mm(y)))
        t.SetWidth(mm(STUB_W))
        t.SetLayer(layer)
        t.SetNet(pad.GetNet())
        b.Add(t)
        px, py = MM(pad.GetPosition().x), MM(pad.GetPosition().y)
        obs.vias.append((x, y, fix_drc.VIA_D / 2, pad.GetNetname()))
        obs.tracks.append((px, py, x, y, STUB_W / 2, layer, pad.GetNetname()))

    free, ripped, failed, removed, ripped_nets = 0, 0, [], set(), set()
    for layer, pads in groups:
        # BGA balls first: their dog-bone spot is the cleanest exit
        pads = sorted(pads, key=lambda p: p.GetParentFootprint().GetReference() not in bga)
        cands = [(p, x, y) for p in pads for x, y in sites_for(p, bga.get(p.GetParentFootprint().GetReference()))]
        done = False
        for p, x, y in cands:
            if obs.via_ok(x, y, p.GetNetname(), p) and obs.track_ok(MM(p.GetPosition().x), MM(p.GetPosition().y),
                                                                      x, y, layer, p.GetNetname(), p):
                place(p, layer, x, y)
                free += 1
                done = True
                break
        if done:
            continue
        best = None
        for p, x, y in cands:
            px, py = MM(p.GetPosition().x), MM(p.GetPosition().y)
            hit = blockers(obs, x, y, p.GetNetname(), layer, px, py, n_orig)
            if len(hit) > MAX_RIP or (best and len(hit) >= len(best[3])):
                continue
            saved = obs.tracks
            obs.tracks = [t for i, t in enumerate(saved) if i not in hit]
            ok = obs.via_ok(x, y, p.GetNetname(), p) and obs.track_ok(px, py, x, y, layer, p.GetNetname(), p)
            obs.tracks = saved
            if ok:
                best = (p, x, y, hit)
        if best is None:
            failed.append(" ".join(f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}" for p in pads[:3]))
            continue
        p, x, y, hit = best
        for i in hit:
            removed.add(i)
            ripped_nets.add(obs.tracks[i][6])
            obs.tracks[i] = (0, 0, 0, 0, 0, -1, "")  # keep indices stable
        place(p, layer, x, y)
        ripped += 1

    for i in sorted(removed, reverse=True):
        b.Delete(track_items[i])
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)
    print(f"{len(groups)} islands/pads needed a via: {free} placed in free space, {ripped} after clearing "
          f"{len(removed)} track segments (nets to reroute: {sorted(ripped_nets)}), no spot found: {failed}")


if __name__ == "__main__":
    main(sys.argv[1])
