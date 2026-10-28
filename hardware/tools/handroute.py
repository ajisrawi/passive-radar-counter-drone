"""Hand-route single open connections on an OpenBoard project (a small grid maze router for the
connections OpenRoute left open in crowded areas).

    python tools/handroute.py <project> NET x1 y1 x2 y2 [--grid 0.05] [--margin 3] [--layers F.Cu,In2.Cu,...]
                              [--width 0.1] [--to-plane] [--dry]

Routes from the copper at (x1, y1) to the copper at (x2, y2) - or, with --to-plane, to any spot where a via
lands on the net's own plane/pour (In1/In8 GND, In4/In5 islands, F/B GND pour). Every other net's pads,
traces and vias are obstacles with the board's clearances; layer changes only use the board's via types
(F-In1, F-In2, In2-In7 buried, In7-B, In8-B). Signal routing stays off the power layers. The new copper is
written unlocked into the project.
"""
import argparse
import heapq
import json
import math

import numpy as np

SIGNAL = ["F.Cu", "In2.Cu", "In3.Cu", "In6.Cu", "In7.Cu", "B.Cu"]


def poly_contains(pts, x, y):
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]["x"], pts[i]["y"]
        x2, y2 = pts[(i + 1) % n]["x"], pts[(i + 1) % n]["y"]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def poly_edge_dist(pts, x, y):
    m = 1e9
    n = len(pts)
    for i in range(n):
        m = min(m, seg_dist(x, y, pts[i]["x"], pts[i]["y"], pts[(i + 1) % n]["x"], pts[(i + 1) % n]["y"]))
    return m


def seg_seg(p, q, u, w):
    """distance between segments p-q and u-w (points as {x, y})"""
    def cross(o, a_, b_):
        return (a_["x"] - o["x"]) * (b_["y"] - o["y"]) - (a_["y"] - o["y"]) * (b_["x"] - o["x"])
    d1, d2, d3, d4 = cross(u, w, p), cross(u, w, q), cross(p, q, u), cross(p, q, w)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(seg_dist(p["x"], p["y"], u["x"], u["y"], w["x"], w["y"]),
               seg_dist(q["x"], q["y"], u["x"], u["y"], w["x"], w["y"]),
               seg_dist(u["x"], u["y"], p["x"], p["y"], q["x"], q["y"]),
               seg_dist(w["x"], w["y"], p["x"], p["y"], q["x"], q["y"]))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


class Board:
    def __init__(self, path):
        self.path = path
        self.d = json.load(open(path, encoding="utf-8"))
        d = self.d
        self.layers = [l["name"] for l in d["layers"]]
        self.li = {n: i for i, n in enumerate(self.layers)}
        self.rules = d["rules"]
        self.cls = {}
        for c in d.get("netClasses", []):
            for n in c["nets"]:
                self.cls[n] = c
        pin_net = {p: n["name"] for n in d["nets"] for p in n["pins"]}
        self.pads = []  # (net, layers set, shape, cx, cy, hw, hh, rot, drill)
        for c in d["components"]:
            fp = d["footprints"][c["footprint"]]
            t = math.radians(c.get("rot", 0))
            back = c.get("side") == "back"
            for p in fp["pads"]:
                x = -p["x"] if back else p["x"]
                cx = c["x"] + x * math.cos(t) - p["y"] * math.sin(t)
                cy = c["y"] + x * math.sin(t) + p["y"] * math.cos(t)
                if p.get("th"):
                    lay = set(range(len(self.layers)))
                else:
                    lay = {self.li["B.Cu"] if back else self.li["F.Cu"]}
                net = pin_net.get(f"{c['ref']}-{p['id']}")
                if p.get("npth"):
                    net = None
                self.pads.append(dict(net=net, layers=lay, shape=p["shape"], x=cx, y=cy, w=p["w"], h=p["h"],
                                      rot=c.get("rot", 0), drill=p.get("drill")))

    def span(self, v):
        a, b = self.li[v.get("from", "F.Cu")], self.li[v.get("to", "B.Cu")]
        return set(range(min(a, b), max(a, b) + 1))

    def clr(self, net):
        c = self.cls.get(net)
        return max(self.rules["clearance"], c["clearance"] if c else 0)


def pad_dist(p, x, y):
    """distance from point to pad copper (0 inside)"""
    if p["shape"] == "circle":
        return max(0.0, math.hypot(x - p["x"], y - p["y"]) - p["w"] / 2)
    t = math.radians(-p["rot"])
    dx, dy = x - p["x"], y - p["y"]
    lx, ly = dx * math.cos(t) - dy * math.sin(t), dx * math.sin(t) + dy * math.cos(t)
    hw, hh = p["w"] / 2, p["h"] / 2
    if p["shape"] == "oval":
        r = min(hw, hh)
        ax, ay = hw - r, hh - r
        qx, qy = max(abs(lx) - ax, 0), max(abs(ly) - ay, 0)
        return max(0.0, math.hypot(qx, qy) - r)
    qx, qy = max(abs(lx) - hw, 0), max(abs(ly) - hh, 0)
    return math.hypot(qx, qy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("net")
    ap.add_argument("x1", type=float)
    ap.add_argument("y1", type=float)
    ap.add_argument("x2", type=float, nargs="?")
    ap.add_argument("y2", type=float, nargs="?")
    ap.add_argument("--grid", type=float, default=0.05)
    ap.add_argument("--margin", type=float, default=3.0)
    ap.add_argument("--layers", default=",".join(SIGNAL))
    ap.add_argument("--width", type=float, default=0.1)
    ap.add_argument("--to-plane", action="store_true")
    ap.add_argument("--box", default=None, help="search window x0,y0,x1,y1")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--via-cost", type=float, default=1.5)
    ap.add_argument("--rip", action="store_true", help="may cut other nets' unlocked wires (reported as ripped)")
    ap.add_argument("--rip-cost", type=float, default=4.0, help="mm-equivalent cost per grid step through a wire")
    ap.add_argument("--max-exp", type=int, default=6_000_000)
    ap.add_argument("--rip-locked", action="store_true", help="with --rip: locked wires too (not --keep-nets)")
    ap.add_argument("--keep-nets", default="", help="nets never ripped")
    ap.add_argument("--hweight", type=float, default=1.0, help=">1: greedier, faster search for long connections")
    a = ap.parse_args()
    a.keep_nets = set(filter(None, a.keep_nets.split(",")))

    B = Board(a.project)
    d = B.d
    net = a.net
    g = a.grid
    W = a.width
    myclr = B.clr(net)
    if a.box:
        x0, y0, x1, y1 = map(float, a.box.split(","))
    else:
        xs = [a.x1] + ([a.x2] if a.x2 is not None else [])
        ys = [a.y1] + ([a.y2] if a.y2 is not None else [])
        x0, x1 = min(xs) - a.margin, max(xs) + a.margin
        y0, y1 = min(ys) - a.margin, max(ys) + a.margin
    nx, ny = int(round((x1 - x0) / g)) + 1, int(round((y1 - y0) / g)) + 1
    NL = len(B.layers)
    route_layers = [B.li[n] for n in a.layers.split(",")]
    gx = x0 + np.arange(nx) * g
    gy = y0 + np.arange(ny) * g
    XX, YY = np.meshgrid(gx, gy, indexing="ij")

    # blocked[l] : centre-line of a W-wide trace cannot be here.  vblk[l]: via pad (radius rv) cannot be here
    tr_block = np.zeros((NL, nx, ny), bool)
    micro_block = np.zeros((NL, nx, ny), bool)   # micro via (0.25) copper per layer
    bur_block = np.zeros((NL, nx, ny), bool)     # buried via (0.4) copper per layer
    hole_micro = np.zeros((nx, ny), bool)
    hole_bur = np.zeros((nx, ny), bool)
    slack = 0.012  # via rules carry a few microns more clearance than wires (0.105 vs 0.100)
    RM, RB = 0.125, 0.2

    def mark_disc(arr, cx, cy, r):
        if cx + r < x0 or cx - r > x1 or cy + r < y0 or cy - r > y1:
            return
        i0, i1 = max(0, int((cx - r - x0) / g)), min(nx - 1, int((cx + r - x0) / g) + 1)
        j0, j1 = max(0, int((cy - r - y0) / g)), min(ny - 1, int((cy + r - y0) / g) + 1)
        sub = (XX[i0:i1 + 1, j0:j1 + 1] - cx) ** 2 + (YY[i0:i1 + 1, j0:j1 + 1] - cy) ** 2 < r * r
        arr[i0:i1 + 1, j0:j1 + 1] |= sub

    def mark_seg(arr, ax, ay, bx, by, r):
        lo_x, hi_x = min(ax, bx) - r, max(ax, bx) + r
        lo_y, hi_y = min(ay, by) - r, max(ay, by) + r
        if hi_x < x0 or lo_x > x1 or hi_y < y0 or lo_y > y1:
            return
        i0, i1 = max(0, int((lo_x - x0) / g)), min(nx - 1, int((hi_x - x0) / g) + 1)
        j0, j1 = max(0, int((lo_y - y0) / g)), min(ny - 1, int((hi_y - y0) / g) + 1)
        X = XX[i0:i1 + 1, j0:j1 + 1]
        Y = YY[i0:i1 + 1, j0:j1 + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            t = 0
        else:
            t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
        dist2 = (X - ax - t * dx) ** 2 + (Y - ay - t * dy) ** 2
        arr[i0:i1 + 1, j0:j1 + 1] |= dist2 < r * r

    def mark_pad(arrs_r, p):
        # arrs_r: list of (array, extra radius)
        ext = max(r for _, r in arrs_r)
        R = max(p["w"], p["h"]) / 2 + ext
        if p["x"] + R < x0 or p["x"] - R > x1 or p["y"] + R < y0 or p["y"] - R > y1:
            return
        i0, i1 = max(0, int((p["x"] - R - x0) / g)), min(nx - 1, int((p["x"] + R - x0) / g) + 1)
        j0, j1 = max(0, int((p["y"] - R - y0) / g)), min(ny - 1, int((p["y"] + R - y0) / g) + 1)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                dd = pad_dist(p, gx[i], gy[j])
                for arr, r in arrs_r:
                    if dd < r:
                        arr[i, j] = True

    own_pts = []  # same-net copper (for start/target lookup)
    for p in B.pads:
        if p["net"] == net and p["net"] is not None:
            continue
        c = max(myclr, B.clr(p["net"]) if p["net"] else 0)
        for l in p["layers"]:
            mark_pad([(tr_block[l], c + W / 2 + slack), (micro_block[l], c + RM + slack), (bur_block[l], c + RB + slack)], p)
        if p.get("drill"):
            hr = p["drill"] / 2
            mark_disc(hole_micro, p["x"], p["y"], hr + 0.05 + 0.24 + slack)
            mark_disc(hole_bur, p["x"], p["y"], hr + 0.1 + B.rules["holeToHole"] + slack)
            # laser hole to copper / mech hole to copper on every layer
            for l in range(NL):
                mark_disc(micro_block[l], p["x"], p["y"], hr + 0.15 + RM)
    # drilled holes keep hole-to-copper clear of every wire, own net included (a wire ends at the pad's ring)
    h2c = B.rules["holeToCopper"]
    for p in B.pads:
        if p.get("drill"):
            for l in range(NL):
                mark_disc(tr_block[l], p["x"], p["y"], p["drill"] / 2 + h2c + W / 2 + slack)
    # --rip: other nets' unlocked wires are passable at a high cost; the pieces crossed are cut out afterwards
    tr_soft = np.zeros((NL, nx, ny), bool) if a.rip else None
    micro_soft = np.zeros((NL, nx, ny), bool) if a.rip else None
    bur_soft = np.zeros((NL, nx, ny), bool) if a.rip else None
    for t in d["traces"]:
        if t["net"] == net:
            continue
        l = B.li[t["layer"]]
        c = max(myclr, B.clr(t["net"]))
        pts = t["points"]
        hw = t["width"] / 2
        soft = a.rip and (a.rip_locked or not t.get("locked")) and t["net"] not in a.keep_nets
        ta, ma, ba = (tr_soft, micro_soft, bur_soft) if soft else (tr_block, micro_block, bur_block)
        for p, q in zip(pts, pts[1:]):
            mark_seg(ta[l], p["x"], p["y"], q["x"], q["y"], hw + c + W / 2 + slack)
            mark_seg(ma[l], p["x"], p["y"], q["x"], q["y"], hw + c + RM + slack)
            mark_seg(ba[l], p["x"], p["y"], q["x"], q["y"], hw + c + RB + slack)
    for v in d["vias"]:
        same = v.get("net") == net
        sp = B.span(v)
        vr = v["diameter"] / 2
        hr = v["drill"] / 2
        laser = v["drill"] <= 0.1
        if not same:
            c = max(myclr, B.clr(v.get("net")))
            for l in sp:
                mark_disc(tr_block[l], v["x"], v["y"], vr + c + W / 2 + slack)
                mark_disc(micro_block[l], v["x"], v["y"], vr + c + RM + slack)
                mark_disc(bur_block[l], v["x"], v["y"], vr + c + RB + slack)
        # hole to hole (same net too, smaller)
        hh_m = (B.rules["laserHoleToHoleSameNet"] if same else B.rules["laserHoleToHole"]) if laser else B.rules["holeToHole"]
        mark_disc(hole_micro, v["x"], v["y"], hr + 0.05 + max(hh_m, B.rules["laserHoleToHoleSameNet"] if same else 0.24) + slack)
        mark_disc(hole_bur, v["x"], v["y"], hr + 0.1 + B.rules["holeToHole"] + slack)
    # board edge
    ec = B.rules["edgeClearance"]
    ol = d["outline"]
    for l in range(NL):
        for i in range(len(ol)):
            p, q = ol[i], ol[(i + 1) % len(ol)]
            mark_seg(tr_block[l], p["x"], p["y"], q["x"], q["y"], ec + W / 2)
            mark_seg(micro_block[l], p["x"], p["y"], q["x"], q["y"], ec + RM)
            mark_seg(bur_block[l], p["x"], p["y"], q["x"], q["y"], ec + RB)

    # same-net copper touching a point -> layers
    def copper_at(x, y, tol=0.02):
        res = set()
        for k, p in enumerate(B.pads):
            if p["net"] == net and pad_dist(p, x, y) <= tol:
                res |= {(l, k) for l in p["layers"]}
        for v in d["vias"]:
            if v.get("net") == net and math.hypot(v["x"] - x, v["y"] - y) <= v["diameter"] / 2 + tol:
                res |= {(l, None) for l in B.span(v)}
        for t in d["traces"]:
            if t["net"] == net:
                for p, q in zip(t["points"], t["points"][1:]):
                    if seg_dist(x, y, p["x"], p["y"], q["x"], q["y"]) <= t["width"] / 2 + tol:
                        res.add((B.li[t["layer"]], None))
        return res

    def cells_for(x, y):
        """grid cells on the connecting copper (pad area, else the point)"""
        out = set()
        for l, k in copper_at(x, y):
            if k is not None:
                p = B.pads[k]
                R = max(p["w"], p["h"]) / 2
                for i in range(max(0, int((p["x"] - R - x0) / g)), min(nx, int((p["x"] + R - x0) / g) + 2)):
                    for j in range(max(0, int((p["y"] - R - y0) / g)), min(ny, int((p["y"] + R - y0) / g) + 2)):
                        if pad_dist(p, gx[i], gy[j]) <= 0.0 and not (p.get("drill") and math.hypot(
                                gx[i] - p["x"], gy[j] - p["y"]) < p["drill"] / 2 + h2c + W / 2 + slack):
                            out.add((l, i, j))
            else:
                i, j = int(round((x - x0) / g)), int(round((y - y0) / g))
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        if 0 <= i + di < nx and 0 <= j + dj < ny:
                            out.add((l, i + di, j + dj))
        return out

    src = cells_for(a.x1, a.y1)
    if not src:
        raise SystemExit(f"no {net} copper at {a.x1},{a.y1}")
    tgt = set()
    if a.x2 is not None:
        tgt = cells_for(a.x2, a.y2)
    plane_layers = {}
    if a.to_plane:
        # zones of this net on non-routing layers (pours carve around other nets, so landing anywhere inside works)
        for zi, z in enumerate(d["zones"]):
            if z["net"] != net:
                continue
            l = B.li[z["layer"]]
            higher = [zz for zz in d["zones"][:zi] if zz["layer"] == z["layer"] and zz["net"] != net]
            plane_layers.setdefault(l, []).append((z, higher))

    def on_plane(l, x, y):
        for z, higher in plane_layers.get(l, []):
            if poly_contains(z["points"], x, y) and poly_edge_dist(z["points"], x, y) > 0.8 and \
                    not any(poly_contains(h["points"], x, y) or poly_edge_dist(h["points"], x, y) < 0.8 for h in higher):
                return True
        return False

    vtypes = []
    for vt in B.rules["viaTypes"]:
        s = sorted([B.li[vt["from"]], B.li[vt["to"]]])
        vtypes.append((vt, set(range(s[0], s[1] + 1))))

    routable = set(route_layers)
    # start/target cells sit on own copper: let them be free on their layer
    for (l, i, j) in src | tgt:
        tr_block[l, i, j] = False

    def via_ok(vt, sp, i, j):
        micro = vt["drill"] <= 0.1
        if micro:
            if hole_micro[i, j]:
                return False
            return not any(micro_block[l, i, j] for l in sp)
        if hole_bur[i, j]:
            return False
        return not any(bur_block[l, i, j] for l in sp)

    def is_target(l, i, j):
        if (l, i, j) in tgt:
            return True
        return False

    # A*: state (l, i, j)
    tx = [a.x2] if a.x2 is not None else []
    ty = [a.y2] if a.y2 is not None else []

    def h(i, j):
        if not tx:
            return 0.0
        dx, dy = abs(gx[i] - tx[0]), abs(gy[j] - ty[0])
        return a.hweight * (max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)) / g

    dirs = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
            (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]
    dist = {}
    prev = {}
    pq = []
    for s in src:
        dist[s] = 0.0
        heapq.heappush(pq, (h(s[1], s[2]), 0.0, s))
    end = None
    via_cost = a.via_cost / g
    VIA_GAP = int(math.ceil(0.32 / g))
    rip_cost = a.rip_cost / g
    pref = {B.li["F.Cu"]: 1.0, B.li["B.Cu"]: 1.0}
    n_exp = 0
    while pq:
        f, dcur, s = heapq.heappop(pq)
        if dcur > dist.get(s, 1e18):
            continue
        n_exp += 1
        l, i, j = s
        if is_target(l, i, j) and s not in src:
            end = (s, None)
            break
        if l in routable or s in src:
            for di, dj, c in dirs:
                ii, jj = i + di, j + dj
                if not (0 <= ii < nx and 0 <= jj < ny):
                    continue
                if tr_block[l, ii, jj] or (l not in routable and (l, ii, jj) not in src | tgt):
                    continue
                if di and dj and (tr_block[l, i + di, j] and tr_block[l, i, j + dj]):
                    continue
                ns = (l, ii, jj)
                nd = dcur + c * pref.get(l, 1.0)
                if a.rip and tr_soft[l, ii, jj]:
                    nd += c * rip_cost
                if nd < dist.get(ns, 1e18):
                    dist[ns] = nd
                    prev[ns] = (s, None)
                    heapq.heappush(pq, (nd + h(ii, jj), nd, ns))
        # via: never stacked on (or within a few cells of) the path's previous via
        # (straight-line distance to the last via on the path: hole to hole 0.13 mm same net + both drills)
        near_via = False
        t_, steps = s, 0
        while t_ in prev and steps < 4 * VIA_GAP:
            pt, pvt = prev[t_]
            if pvt is not None:
                near_via = math.hypot(gx[t_[1]] - gx[i], gy[t_[2]] - gy[j]) < 0.33
                break
            t_ = pt
            steps += 1
        for vt, sp in vtypes:
            if near_via:
                break
            if l not in sp:
                continue
            if not via_ok(vt, sp, i, j):
                continue
            vsoft = 0.0
            if a.rip:
                sa = micro_soft if vt["drill"] <= 0.1 else bur_soft
                vsoft = rip_cost * 6 * sum(1 for l3 in sp if sa[l3, i, j])
            if plane_layers and any(pl in sp and on_plane(pl, gx[i], gy[j]) for pl in plane_layers):
                ns = ("PLANE", i, j)
                end = (s, vt)
                break
            for l2 in sp:
                if l2 == l or l2 not in routable:
                    continue
                ns = (l2, i, j)
                nd = dcur + via_cost + vsoft
                if nd < dist.get(ns, 1e18):
                    dist[ns] = nd
                    prev[ns] = (s, vt)
                    heapq.heappush(pq, (nd + h(i, j), nd, ns))
        if end:
            break
        if n_exp > a.max_exp:
            break
    if not end:
        print(json.dumps({"ok": False, "net": net, "expanded": n_exp}))
        return 1
    # backtrack
    path = []  # list of (l, i, j, via_type_used_to_get_here)
    s, vt = end
    final_via = vt
    while True:
        path.append(s)
        if s in src and s not in prev:
            break
        if s not in prev:
            break
        ps, pvt = prev[s]
        if pvt is not None:
            path.append(("V", pvt, s[1], s[2]))
        s = ps
    path.reverse()
    traces, vias = [], []
    cur = []
    cur_l = None
    for item in path:
        if item[0] == "V":
            if len(cur) >= 2:
                traces.append((cur_l, cur))
            vt = item[1]
            vias.append((gx[item[2]], gy[item[3]], vt))
            cur, cur_l = [], None
            continue
        l, i, j = item
        if cur_l is None:
            cur_l = l
        cur.append((gx[i], gy[j]))
    if len(cur) >= 2:
        traces.append((cur_l, cur))
    if final_via is not None:
        l, i, j = end[0]
        vias.append((gx[i], gy[j], final_via))

    def simplify(pts):
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = out[-1]
            bx, by = pts[k]
            cx, cy = pts[k + 1]
            if abs((bx - ax) * (cy - by) - (by - ay) * (cx - bx)) < 1e-9:
                continue
            out.append(pts[k])
        out.append(pts[-1])
        return out

    nid = d["nextId"]
    added = {"traces": 0, "vias": 0, "length": 0.0}
    for l, pts in traces:
        pts = simplify(pts)
        d["traces"].append({"id": nid, "net": net, "layer": B.layers[l], "width": W,
                            "points": [{"x": round(x, 4), "y": round(y, 4)} for x, y in pts]})
        nid += 1
        added["traces"] += 1
        added["length"] += sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
    for x, y, vt in vias:
        d["vias"].append({"id": nid, "net": net, "x": round(x, 4), "y": round(y, 4), "diameter": vt["diameter"],
                          "drill": vt["drill"], "from": vt["from"], "to": vt["to"]})
        nid += 1
        added["vias"] += 1
    ripped = set()
    if a.rip:
        new_tr = [t for t in d["traces"][-added["traces"]:]] if added["traces"] else []
        new_v = [v for v in d["vias"][-added["vias"]:]] if added["vias"] else []
        keep = []
        for t in d["traces"]:
            if t["net"] == net or (t.get("locked") and not a.rip_locked) or t["net"] in a.keep_nets:
                keep.append(t)
                continue
            c = max(myclr, B.clr(t["net"]))
            l = B.li[t["layer"]]
            pts = t["points"]
            bad = set()
            for k, (p, q) in enumerate(zip(pts, pts[1:])):
                for nt in new_tr:
                    if nt["layer"] != t["layer"]:
                        continue
                    for u, w in zip(nt["points"], nt["points"][1:]):
                        if seg_seg(p, q, u, w) < t["width"] / 2 + W / 2 + c - 1e-4:
                            bad.add(k)
                for v in new_v:
                    if l in B.span(v) and seg_dist(v["x"], v["y"], p["x"], p["y"], q["x"], q["y"]) < \
                            t["width"] / 2 + v["diameter"] / 2 + c - 1e-4:
                        bad.add(k)
            if not bad:
                keep.append(t)
                continue
            ripped.add(t["net"])
            run = [pts[0]]
            for k in range(len(pts) - 1):
                if k in bad:
                    if len(run) >= 2:
                        keep.append(dict(t, id=nid, points=run))
                        nid += 1
                    run = [pts[k + 1]]
                else:
                    run.append(pts[k + 1])
            if len(run) >= 2:
                keep.append(dict(t, id=nid, points=run))
                nid += 1
        d["traces"] = keep
    d["nextId"] = nid
    added["length"] = round(added["length"], 2)
    added["ripped"] = sorted(ripped)
    if not a.dry:
        json.dump(d, open(a.project, "w", encoding="utf-8"))
    print(json.dumps({"ok": True, "net": net, "expanded": n_exp, **added,
                      "layers": sorted({B.layers[l] for l, _ in traces})}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
