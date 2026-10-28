"""PCB generator (run with KiCad's Python): netlist JSON + placement -> .kicad_pcb.

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" boards/layout_a.py
"""
import json
import os

import pcbnew

KICAD_FP = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
HERE = os.path.dirname(os.path.abspath(__file__))
PRC_FP = os.path.abspath(os.path.join(HERE, "..", "lib", "prc.pretty"))
mm = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    path = PRC_FP if lib == "prc" else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise FileNotFoundError(fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


class Layout:
    def __init__(self, name, netlist_json, layers=4, rules=None):
        self.name = name
        self.data = json.load(open(netlist_json))["parts"]
        self.board = pcbnew.BOARD()
        self.board.SetCopperLayerCount(layers)
        self.layers = layers
        self.nets = {}
        self.fps = {}
        self.warnings = []
        r = {"track": 0.15, "clearance": 0.15, "via": 0.6, "drill": 0.3, "hole_clear": 0.25}
        r.update(rules or {})
        ds = self.board.GetDesignSettings()
        ds.m_TrackMinWidth = mm(min(0.1, r["track"]))
        ds.m_MinClearance = mm(min(0.1, r["clearance"]))
        ds.m_ViasMinSize = mm(min(0.45, r["via"]))
        ds.m_MinThroughDrill = mm(min(0.2, r["drill"]))
        ds.SetCustomTrackWidth(mm(r["track"]))
        ds.SetCustomViaSize(mm(r["via"]))
        ds.SetCustomViaDrill(mm(r["drill"]))
        nc = ds.m_NetSettings.GetDefaultNetclass()
        nc.SetTrackWidth(mm(r["track"]))
        nc.SetClearance(mm(r["clearance"]))
        nc.SetViaDiameter(mm(r["via"]))
        nc.SetViaDrill(mm(r["drill"]))
        self.rules = r
        self._build()

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def _build(self):
        for ref, p in self.data.items():
            fp = load_fp(p["footprint"])
            fp.SetReference(ref)
            fp.SetValue(p["value"])
            if p.get("lcsc"):
                fp.SetField("LCSC", p["lcsc"]) if hasattr(fp, "SetField") else None
            pads = {}
            for pad in fp.Pads():
                pads.setdefault(pad.GetNumber(), []).append(pad)
            for pin, netname in p["pins"].items():
                if pin not in pads:
                    self.warnings.append(f"{ref}: footprint {p['footprint']} has no pad '{pin}' (net {netname})")
                    continue
                for pad in pads[pin]:
                    pad.SetNet(self.net(netname))
            # unnumbered pads (thermal vias in exposed pads) inherit the net of the pad they sit in
            for pad in fp.Pads():
                if pad.GetNumber() == "" and pad.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                    for other in fp.Pads():
                        if other.GetNumber() and other.GetNetCode() > 0 and \
                                other.GetBoundingBox().Contains(pad.GetPosition()):
                            pad.SetNet(other.GetNet())
                            break
            self.board.Add(fp)
            self.fps[ref] = fp

    # ------------------------------------------------------------ placement helpers
    def place(self, ref, x, y, rot=0, back=False):
        fp = self.fps[ref]
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        if back and fp.GetLayer() == pcbnew.F_Cu:
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM if hasattr(pcbnew, "FLIP_DIRECTION_TOP_BOTTOM") else False)
        fp.SetFPID(fp.GetFPID())
        self.placed = getattr(self, "placed", set())
        self.placed.add(ref)

    def outline(self, w, h, r=2.0):
        pts = [(0, 0), (w, 0), (w, h), (0, h)]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            s = pcbnew.PCB_SHAPE(self.board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(V(x1, y1))
            s.SetEnd(V(x2, y2))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(mm(0.1))
            self.board.Add(s)
        self.w, self.h = w, h

    def zone(self, netname, layer, inset=0.5, clearance=0.25, priority=0):
        z = pcbnew.ZONE(self.board)
        z.SetLayer(layer)
        z.SetNet(self.net(netname))
        o = z.Outline()
        o.NewOutline()
        for x, y in ((inset, inset), (self.w - inset, inset), (self.w - inset, self.h - inset), (inset, self.h - inset)):
            o.Append(mm(x), mm(y))
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(0.2))
        z.SetAssignedPriority(priority)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.3))
        self.board.Add(z)
        return z

    def via(self, x, y, netname, size=None, drill=None):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(size or self.rules["via"]))
        v.SetDrill(mm(drill or self.rules["drill"]))
        v.SetNet(self.net(netname))
        self.board.Add(v)
        return v

    def track(self, pts, netname, width, layer=pcbnew.F_Cu):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(V(x1, y1))
            t.SetEnd(V(x2, y2))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(self.net(netname))
            self.board.Add(t)

    def _extent(self, fp, back=False):
        """Union of courtyard and pad boxes (some vendor courtyards are smaller than the pads)."""
        bb = None
        try:
            c = fp.GetCourtyard(pcbnew.B_CrtYd if back else pcbnew.F_CrtYd).BBox()
            if c.GetWidth() > 0:
                bb = c
        except Exception:
            pass
        for pad in fp.Pads():
            pb = pad.GetBoundingBox()
            if bb is None:
                bb = pcbnew.BOX2I(pb.GetPosition(), pb.GetSize())
            else:
                bb.Merge(pb)
        if bb is None:
            bb = fp.GetBoundingBox(False, False)
        bb.Inflate(mm(0.15))
        return bb

    def size(self, ref):
        """Placement size in mm at 0 degrees."""
        fp = self.fps[ref]
        fp.SetOrientationDegrees(0)
        bb = self._extent(fp)
        return pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())

    def pack(self, refs, x0, y0, x1, gap=0.6, back=False, y1=None):
        """Shelf-pack parts left->right, top->bottom inside [x0, x1]. Returns the y below the last row."""
        x, y, row_h = x0, y0, 0.0
        for r in refs:
            w, h = self.size(r)
            if x + w > x1 and x > x0:
                x, y, row_h = x0, y + row_h + gap, 0.0
            if y1 is not None and y + h > y1:
                raise RuntimeError(f"pack overflow at {r}")
            fp = self.fps[r]
            self.place(r, 0, 0, 0, back=back)
            bb = self._extent(fp, back)
            cx, cy = pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y)
            self.place(r, x + w / 2 - cx, y + h / 2 - cy, 0, back=back)
            x += w + gap
            row_h = max(row_h, h)
        return y + row_h

    def unplaced(self):
        return [r for r in self.fps if r not in getattr(self, "placed", set())]

    def fill_zones(self):
        pcbnew.ZONE_FILLER(self.board).Fill(self.board.Zones())

    def save(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, self.name + ".kicad_pcb")
        self.board.Save(path)
        return path
