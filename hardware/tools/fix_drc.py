"""Post-route DRC cleanup (run with KiCad's Python) on <board>/<board>_routed.kicad_pcb.

    python.exe tools/fix_drc.py board_b

1. Widen tracks narrower than the board minimum (Freerouting neck-downs) to the minimum,
   unless widening would break clearance.
2. Outer-layer GND zones connect pads solidly (no thermal spokes) - fixes starved thermals.
3. Plane-net pads that DRC reports as unconnected get a fan-out via (+ short track) placed
   at the first free spot around the pad; the through via reaches the inner plane.
4. Refill zones, save, and print a DRC summary.
"""
import collections
import json
import math
import os
import subprocess
import sys

import pcbnew

HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
PLANE_NETS = {"board_b": {"GND", "+1V8"}, "board_c": {"GND", "+3V3", "+1V0"}, "board_a": {"GND", "+5V_LNA"}}
mm, MM = pcbnew.FromMM, pcbnew.ToMM

VIA_D, VIA_HOLE, CLR, HOLE_CLR, FAN_W = 0.45, 0.2, 0.1, 0.25, 0.2


def drc(path, out):
    subprocess.run([CLI, "pcb", "drc", "--format", "json", "--severity-error", "--severity-warning", "-o", out, path],
                   capture_output=True)
    return json.load(open(out))


def summary(d):
    c = collections.Counter(v["type"] for v in d.get("violations", []) if not v["type"].startswith("silk"))
    un = collections.Counter()
    for u in d.get("unconnected_items", []):
        desc = u["items"][0]["description"]
        un[desc[desc.find("[") + 1:desc.find("]")] if "[" in desc else desc] += 1
    return dict(c), len(d.get("unconnected_items", [])), dict(un.most_common(30))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def pad_dist(px, py, pad, bb):
    """Distance from a point to a pad's copper edge (exact for round pads, box otherwise)."""
    if pad.GetShape(pcbnew.F_Cu) == pcbnew.PAD_SHAPE_CIRCLE:
        c = pad.GetPosition()
        return max(0.0, math.hypot(px - MM(c.x), py - MM(c.y)) - MM(pad.GetSize(pcbnew.F_Cu).x) / 2)
    return box_dist(px, py, bb)


def box_dist(px, py, bb):
    x0, y0, x1, y1 = MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom())
    dx = max(x0 - px, 0, px - x1)
    dy = max(y0 - py, 0, py - y1)
    return math.hypot(dx, dy)


class Obstacles:
    def __init__(self, board):
        self.pads = [(p, p.GetBoundingBox(), p.GetNetname(), p.GetLayerSet()) for fp in board.GetFootprints()
                     for p in fp.Pads()]
        self.tracks = []
        self.vias = []
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                self.vias.append((MM(t.GetPosition().x), MM(t.GetPosition().y), MM(t.GetWidth(pcbnew.F_Cu)) / 2,
                                  t.GetNetname()))
            else:
                self.tracks.append((MM(t.GetStart().x), MM(t.GetStart().y), MM(t.GetEnd().x), MM(t.GetEnd().y),
                                    MM(t.GetWidth()) / 2, t.GetLayer(), t.GetNetname()))

    def via_ok(self, x, y, net, own_pad):
        r = VIA_D / 2
        for p, bb, n, _ in self.pads:
            if p is own_pad:
                continue
            need = r + CLR if n == net else max(r + CLR, VIA_HOLE / 2 + HOLE_CLR)
            if pad_dist(x, y, p, bb) < need:
                return False
        for (ax, ay, bx, by, hw, _, n) in self.tracks:
            if n != net and seg_dist(x, y, ax, ay, bx, by) < max(r + CLR, VIA_HOLE / 2 + HOLE_CLR) + hw:
                return False
        for (vx, vy, vr, n) in self.vias:
            if math.hypot(x - vx, y - vy) < r + vr + max(CLR, HOLE_CLR):
                return False
        return True

    def track_ok(self, ax, ay, bx, by, layer, net, own_pad):
        hw = FAN_W / 2
        for p, bb, n, ls in self.pads:
            if p is own_pad or n == net or not ls.Contains(layer):
                continue
            for k in range(6):
                t = k / 5
                if box_dist(ax + t * (bx - ax), ay + t * (by - ay), bb) < hw + CLR:
                    return False
        for (cx, cy, dx, dy, w, lay, n) in self.tracks:
            if lay != layer or n == net:
                continue
            for k in range(6):
                t = k / 5
                if seg_dist(ax + t * (bx - ax), ay + t * (by - ay), cx, cy, dx, dy) < hw + w + CLR:
                    return False
        return True


def main(board):
    path = os.path.join(HW, board, board + "_routed.kicad_pcb")
    before = drc(path, os.path.join(HW, board, "drc_before_fix.json"))
    print("before:", summary(before))
    b = pcbnew.LoadBoard(path)
    min_w = b.GetDesignSettings().m_TrackMinWidth
    global CLR
    CLR = MM(b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().GetClearance())  # board's own rule
    bad = {i.get("uuid") for v in before.get("violations", []) if v["type"] == "clearance"
           for i in v["items"] if i["description"].startswith("Via")}
    for t in list(b.GetTracks()):  # vias that break clearance (e.g. from an earlier pass) are removed and re-placed
        if t.GetClass() == "PCB_VIA" and t.m_Uuid.AsString() in bad:
            b.Delete(t)

    # 1. widen neck-downs; tracks that then clash keep JLCPCB's multilayer minimum (0.09 mm)
    clash = {i.get("uuid") for v in before.get("violations", []) if v["type"] == "clearance"
             for i in v["items"] if i["description"].startswith("Track")}
    widened = 0
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            continue
        if t.m_Uuid.AsString() in clash and t.GetWidth() > mm(0.09):
            t.SetWidth(mm(0.09))
        elif t.GetWidth() < min_w:
            t.SetWidth(min_w)
            widened += 1
    if clash:
        b.GetDesignSettings().m_TrackMinWidth = mm(0.09)

    # 2. solid pad connections on outer GND pours
    for z in b.Zones():
        if z.GetNetname() == "GND" and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)

    # 3. fan-out vias for unconnected plane-net pads
    want = collections.defaultdict(set)
    for u in before.get("unconnected_items", []):
        for it in u["items"]:
            d = it["description"]
            if d.startswith("Pad") and " of " in d and "[" in d:
                net = d[d.find("[") + 1:d.find("]")]
                if net in PLANE_NETS[board]:
                    num = d.split()[1]
                    ref = d.split(" of ")[1].split()[0]
                    want[(ref, num)].add(net)
    obs = Obstacles(b)
    added, failed = 0, []
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
    for (ref, num), nets in sorted(want.items()):
        fp = fps.get(ref)
        pads = [p for p in fp.Pads() if p.GetNumber() == num] if fp else []
        if not pads:
            failed.append((ref, num))
            continue
        pad = pads[0]
        net = pad.GetNetname()
        layer = pcbnew.F_Cu if pad.GetLayerSet().Contains(pcbnew.F_Cu) else pcbnew.B_Cu
        px, py = MM(pad.GetPosition().x), MM(pad.GetPosition().y)
        half = max(MM(pad.GetBoundingBox().GetWidth()), MM(pad.GetBoundingBox().GetHeight())) / 2
        done = False
        for d in (0.8 * math.sqrt(0.5), half + 0.35, half + 0.55, half + 0.8, half + 1.1, half + 1.5):
            for k in range(16):
                a = 2 * math.pi * k / 16
                x, y = px + d * math.cos(a), py + d * math.sin(a)
                if obs.via_ok(x, y, net, pad) and obs.track_ok(px, py, x, y, layer, net, pad):
                    v = pcbnew.PCB_VIA(b)
                    v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
                    v.SetWidth(mm(VIA_D))
                    v.SetDrill(mm(VIA_HOLE))
                    v.SetNet(pad.GetNet())
                    b.Add(v)
                    t = pcbnew.PCB_TRACK(b)
                    t.SetStart(pad.GetPosition())
                    t.SetEnd(pcbnew.VECTOR2I(mm(x), mm(y)))
                    t.SetWidth(mm(FAN_W))
                    t.SetLayer(layer)
                    t.SetNet(pad.GetNet())
                    b.Add(t)
                    obs.vias.append((x, y, VIA_D / 2, net))
                    obs.tracks.append((px, py, x, y, FAN_W / 2, layer, net))
                    added += 1
                    done = True
                    break
            if done:
                break
        if not done:
            failed.append((ref, num))

    # 4. GND stitching: every outer-layer GND pour island gets up to 2 vias to the inner GND planes
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    gnd_net = b.FindNet("GND")
    stitched = 0
    for z in list(b.Zones()):
        if z.GetNetname() != "GND" or z.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        polys = z.GetFilledPolysList(z.GetLayer())
        for i in range(polys.OutlineCount()):
            outline = polys.Outline(i)
            bb = outline.BBox()
            x0, y0, x1, y1 = MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom())
            placed = 0
            step = 0.5
            y = y0 + 0.3
            while y < y1 and placed < 2:
                x = x0 + 0.3
                while x < x1 and placed < 2:
                    pt = pcbnew.VECTOR2I(mm(x), mm(y))
                    inside = outline.PointInside(pt) and all(
                        outline.PointInside(pcbnew.VECTOR2I(mm(x + dx), mm(y + dy)))
                        for dx, dy in ((0.3, 0), (-0.3, 0), (0, 0.3), (0, -0.3)))
                    if inside and obs.via_ok(x, y, "GND", None) and all(
                            math.hypot(x - vx, y - vy) > 1.5 for vx, vy, _, n in obs.vias if n == "GND"):
                        v = pcbnew.PCB_VIA(b)
                        v.SetPosition(pt)
                        v.SetWidth(mm(VIA_D))
                        v.SetDrill(mm(VIA_HOLE))
                        v.SetNet(gnd_net)
                        b.Add(v)
                        obs.vias.append((x, y, VIA_D / 2, "GND"))
                        placed += 1
                        stitched += 1
                    x += step
                y += step
    print(f"stitching vias added: {stitched}")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)
    after = drc(path, os.path.join(HW, board, "drc_after_fix.json"))
    print(f"widened {widened} tracks, added {added} fan-out vias, no room for {len(failed)}: {failed[:15]}")
    print("after:", summary(after))


if __name__ == "__main__":
    main(sys.argv[1])
