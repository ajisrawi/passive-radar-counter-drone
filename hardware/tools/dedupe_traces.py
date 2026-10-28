"""Remove copper that a net has laid twice over the same path (same net, same layer).

    python tools/dedupe_traces.py <project.openboard.json>

OpenRoute's shape-based router (--gridless) can commit a pair carrier and, later, a second route of the
same connection along the same lane. On Board C2 that left 32 of the 86 pair nets with ~110 mm of
doubled copper, so length tuning and the DRC skew check saw ~250 mm nets that are ~125 mm long.
Each trace is cut against the copper of the net's earlier traces on its layer; the pieces that remain
are kept with the trace's width and lock flag. Pieces end on the kept copper, so connectivity is unchanged.
"""
import collections
import json
import sys

from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union

TOL = 0.01      # mm: copper this close to an earlier trace's centre-line counts as the same path
MIN_PIECE = 0.05


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    nid = d.get("nextId", 1)
    seen = collections.defaultdict(list)   # (net, layer) -> kept LineStrings
    out, removed = [], 0.0
    for t in d["traces"]:
        ls = LineString([(p["x"], p["y"]) for p in t["points"]])
        key = (t["net"], t["layer"])
        if seen[key] and ls.length > 0:
            rest = ls.difference(unary_union(seen[key]).buffer(TOL, cap_style=2))
            parts = list(rest.geoms) if isinstance(rest, MultiLineString) else ([rest] if not rest.is_empty else [])
            parts = [g for g in parts if isinstance(g, LineString) and g.length >= MIN_PIECE]
            kept = sum(g.length for g in parts)
            if ls.length - kept > MIN_PIECE:
                removed += ls.length - kept
                for k, g in enumerate(parts):
                    # snap the cut ends back onto the earlier copper (the buffer leaves a TOL gap)
                    pts = list(g.coords)
                    u = unary_union(seen[key])
                    for i in (0, -1):
                        q = u.interpolate(u.project(LineString([pts[i], pts[i]]).centroid))
                        if q.distance(LineString([pts[i], pts[i]]).centroid) <= 2 * TOL:
                            pts[i] = (q.x, q.y)
                    n = dict(t, points=[{"x": x, "y": y} for x, y in pts])
                    if k:
                        n["id"] = nid
                        nid += 1
                    out.append(n)
                    seen[key].append(LineString(pts))
                continue
        out.append(t)
        seen[key].append(ls)
    d["traces"] = out
    d["nextId"] = nid
    json.dump(d, open(path, "w", encoding="utf-8"))
    print(f"dedupe: removed {removed:.1f} mm of doubled copper; {len(out)} traces")


if __name__ == "__main__":
    main(sys.argv[1])
