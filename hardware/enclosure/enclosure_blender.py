"""Receiver-node enclosure for one band group (Board A2 front end + two receiver stacks, Board B on Board C2),
built in Blender from parameters and the real board layouts, then rendered.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/enclosure/enclosure_blender.py -- [views]
    views: exterior interior mast (default: all)   -> hardware/enclosure/render_<view>.png, enclosure.blend

Concept (mast-mounted outdoor unit, like a cellular remote radio head):
  * cast-aluminium body, IP65, RAL 7035 light grey; boards stand on the inner back wall;
  * front cover with vertical natural-convection fins and thermal pedestals onto the Zynq and AD9361s;
  * all cables enter from the bottom face (drip-safe): 6 N-type antenna inputs (REF, S1-S4, AUX = A2 CH0-CH5),
    GNSS (TNC), 2 x IP67 fibre (one per stack, from the C2 SFP+), M12 power, pressure-equalising vent, earth stud;
  * mast bracket with two clamps for a 50-114 mm pole on the back.
Boards are drawn from hardware/*/*.openboard.json: outline, and every component as a block of its footprint size
with a height by package type.
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
MM = 0.001

# ------------------------------------------------------------------ parameters (mm)
P = {
    "inner_w": 640.0, "inner_h": 250.0, "inner_d": 70.0,   # X (across), Z (up), Y (depth to the cover)
    "wall": 5.0, "cover_t": 6.0, "fin_d": 28.0, "fin_t": 3.0, "fin_pitch": 11.0,
    "standoff": 8.0, "fmc_gap": 10.0,                     # back wall -> C2, C2 -> B
    "pole_d": 76.0,
}
BOARDS = {
    "C2": "board_c2/board_c2.openboard.json",
    "B": "board_b_bands/n78/board_b_n78.openboard.json",
    "A2": "board_a2/uhf/board_a2_uhf.openboard.json",
}


# ------------------------------------------------------------------ helpers
def mat(name, color, metallic=0.0, rough=0.5, transmission=0.0, emission=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1)
        b.inputs["Emission Strength"].default_value = 3.0
    return m


class MeshBuilder:
    """many boxes / cylinders into one mesh object per material (fast with ~2000 parts)"""

    def __init__(self):
        self.parts = {}

    def box(self, material, center, size, rot_z=0.0):
        bm = self.parts.setdefault(material, bmesh.new())
        m = Matrix.Translation(Vector(center) * MM) @ Matrix.Rotation(rot_z, 4, "Z") @ Matrix.Diagonal((*[s * MM for s in size], 1))
        bmesh.ops.create_cube(bm, size=1.0, matrix=m)

    def cyl(self, material, center, radius, depth, axis="Z", segments=32):
        bm = self.parts.setdefault(material, bmesh.new())
        r = {"Z": Matrix.Identity(4), "X": Matrix.Rotation(math.pi / 2, 4, "Y"), "Y": Matrix.Rotation(math.pi / 2, 4, "X")}[axis]
        m = Matrix.Translation(Vector(center) * MM) @ r
        bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius * MM, radius2=radius * MM,
                              depth=depth * MM, matrix=m)

    def build(self, name, collection, mats):
        objs = []
        for key, bm in self.parts.items():
            me = bpy.data.meshes.new(f"{name}_{key}")
            bm.to_mesh(me)
            bm.free()
            ob = bpy.data.objects.new(f"{name}_{key}", me)
            ob.data.materials.append(mats[key])
            collection.objects.link(ob)
            for p in ob.data.polygons:
                p.use_smooth = False
            objs.append(ob)
        self.parts = {}
        return objs


def height_of(fp):
    n = fp.split(":")[-1].upper()
    for k, h in (("SFP", 9.5), ("RJ45", 13.5), ("DC-IN", 11.0), ("SMA", 8.0), ("USB_C", 3.3), ("TF-SMD", 2.0),
                 ("PINHEADER", 8.5), ("BGA-160", 6.5), ("FBGA", 2.4), ("CSPBGA", 1.2), ("BGA", 1.4), ("TFBGA", 1.2),
                 ("QFN", 0.9), ("SON", 0.9), ("DFN", 0.9), ("SOIC", 1.6), ("SOT", 1.1), ("WSON", 0.8),
                 ("SRN4018", 1.8), ("D_SMB", 2.3), ("1206", 1.2), ("0805", 1.0), ("0603", 0.8), ("0402", 0.5),
                 ("FUSE", 1.2), ("SW_SPST", 3.5), ("UBLOX", 2.5), ("MOUNTINGHOLE", 0.0), ("TESTPOINT", 0.0)):
        if k in n:
            return h
    return 1.2


def comp_material(fp):
    n = fp.split(":")[-1].upper()
    if any(k in n for k in ("SFP", "SMA", "RJ45", "USB", "TF-SMD", "DC-IN")):
        return "metal"
    if any(k in n for k in ("BGA", "QFN", "SON", "DFN", "SOIC", "SOT", "UBLOX", "WSON", "LED")):
        return "ic"
    if "PINHEADER" in n or "BGA-160" in n:
        return "plastic"
    if any(k in n for k in ("C_", "CAPACITOR")):
        return "cap"
    return "passive"


def add_board(mb, key, path, origin, flip=False):
    """board in the XZ plane (standing on the back wall), component side towards -Y (the front cover).
    origin: (x, y, z) of the board's top-left corner in mm; board y (down) maps to -Z."""
    d = json.load(open(os.path.join(HW, path), encoding="utf-8"))
    xs = [p["x"] for p in d["outline"]]
    ys = [p["y"] for p in d["outline"]]
    x0, y0 = min(xs), min(ys)
    w, h = max(xs) - x0, max(ys) - y0
    ox, oy, oz = origin
    t = 1.6
    mb.box(f"pcb_{key}", (ox + w / 2, oy, oz - h / 2), (w, t, h))
    n = 0
    tips = {"sma": [], "sfp": []}
    for c in d["components"]:
        fp = d["footprints"].get(c["footprint"], {})
        body = fp.get("body") or {}
        bw, bh = body.get("w"), body.get("h")
        if not bw:
            pads = fp.get("pads", [])
            if not pads:
                continue
            bw = max(p["x"] + p["w"] / 2 for p in pads) - min(p["x"] - p["w"] / 2 for p in pads)
            bh = max(p["y"] + p["h"] / 2 for p in pads) - min(p["y"] - p["h"] / 2 for p in pads)
        hgt = height_of(c["footprint"])
        if hgt <= 0 or bw > w or bh > h:
            continue
        side = -1 if c.get("side", "front") == "front" else 1          # front faces the cover (-Y)
        cx = ox + (c["x"] - x0)
        cz = oz - (c["y"] - y0)
        cy = oy + side * (t / 2 + hgt / 2)
        if abs(math.sin(math.radians(c.get("rot", 0)))) > 0.5:     # 90 / 270: footprint extents swap
            bw, bh = bh, bw
        mb.box(comp_material(c["footprint"]), (cx, cy, cz), (bw, hgt, bh))
        name = c["footprint"].upper()
        if "SMA" in name and c.get("side", "front") == "front":
            tips["sma"].append((cx, oy - t / 2 - hgt, cz))
        if "SFP" in name:
            tips["sfp"].append((cx, oy - t / 2 - hgt, cz + bh / 2))
        n += 1
    return w, h, n, tips


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def cable(collection, pts, radius, material, name="cable"):
    """smooth cable along points (mm): order-3 NURBS (stays inside its control polygon, no overshoot)"""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius * MM
    cu.bevel_resolution = 4
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for pt, p in zip(sp.points, pts):
        pt.co = (*(Vector(p) * MM), 1.0)
    sp.order_u = 3
    sp.use_endpoint_u = True
    sp.resolution_u = 16
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(material)
    collection.objects.link(ob)
    return ob


def text(collection, s, loc, size, rot, material):
    cu = bpy.data.curves.new(f"t_{s}", "FONT")
    cu.body = s
    cu.size = size * MM
    cu.align_x = "CENTER"
    cu.extrude = 0.15 * MM
    ob = bpy.data.objects.new(f"label_{s}", cu)
    ob.location = Vector(loc) * MM
    ob.rotation_euler = rot
    ob.data.materials.append(material)
    collection.objects.link(ob)
    return ob


# ------------------------------------------------------------------ model
def build():
    clear()
    scene = bpy.context.scene
    col = bpy.data.collections.new("Node")
    scene.collection.children.link(col)
    M = {
        "body": mat("Powder RAL7035", (0.46, 0.47, 0.44), 0.0, 0.5),
        "cover": mat("Powder RAL7035 cover", (0.44, 0.45, 0.42), 0.0, 0.45),
        "alu": mat("Aluminium", (0.80, 0.80, 0.82), 1.0, 0.32),
        "steel": mat("Galvanised steel", (0.62, 0.63, 0.64), 1.0, 0.4),
        "gasket": mat("Gasket EPDM", (0.03, 0.03, 0.03), 0.0, 0.8),
        "brass": mat("N-type brass", (0.85, 0.72, 0.42), 1.0, 0.25),
        "black": mat("Black plastic", (0.02, 0.02, 0.025), 0.0, 0.45),
        "blue": mat("Fibre blue", (0.05, 0.25, 0.75), 0.0, 0.4),
        "pcb_C2": mat("Soldermask green", (0.005, 0.12, 0.035), 0.0, 0.3),
        "pcb_B": mat("Soldermask green B", (0.005, 0.12, 0.035), 0.0, 0.3),
        "pcb_A2": mat("Soldermask blue A2", (0.005, 0.03, 0.16), 0.0, 0.3),
        "ic": mat("IC epoxy", (0.03, 0.03, 0.035), 0.0, 0.4),
        "passive": mat("Passive", (0.08, 0.08, 0.08), 0.0, 0.5),
        "cap": mat("Ceramic cap", (0.35, 0.26, 0.15), 0.0, 0.5),
        "metal": mat("Connector metal", (0.85, 0.85, 0.86), 1.0, 0.2),
        "plastic": mat("Connector plastic", (0.08, 0.08, 0.09), 0.0, 0.5),
        "coax": mat("Coax jacket", (0.08, 0.08, 0.10), 0.0, 0.6),
        "label": mat("Label white", (0.95, 0.95, 0.95), 0.0, 0.5),
        "pole": mat("Mast steel", (0.55, 0.56, 0.58), 1.0, 0.45),
        "led": mat("LED green", (0.1, 1.0, 0.2), 0.0, 0.3, emission=(0.1, 1.0, 0.2)),
    }
    W, H, D, t = P["inner_w"], P["inner_h"], P["inner_d"], P["wall"]
    # coordinates: X across, Z up, Y from the cover (y = 0 inner face of the cover) to the back wall (y = D)
    mb = MeshBuilder()
    # ---------------- body: back wall + four side walls (open towards -Y), flange for the cover
    mb.box("body", (0, D + t / 2, 0), (W + 2 * t, t, H + 2 * t))
    mb.box("body", (-(W + t) / 2, D / 2, 0), (t, D, H + 2 * t))
    mb.box("body", ((W + t) / 2, D / 2, 0), (t, D, H + 2 * t))
    mb.box("body", (0, D / 2, (H + t) / 2), (W, D, t))
    mb.box("body", (0, D / 2, -(H + t) / 2), (W, D, t))
    # rounded look: corner fillets as cylinders
    for sx in (-1, 1):
        for sz in (-1, 1):
            mb.cyl("body", (sx * (W / 2 + t / 2), D / 2 + t / 2, sz * (H / 2 + t / 2)), t * 0.8, D + t, "Y")
    body = mb.build("Body", col, M)

    # ---------------- inside: boards on standoffs from the back wall
    board_y_c = D - P["standoff"] - 0.8          # C2 plane (component side faces -Y)
    board_y_b = board_y_c - P["fmc_gap"] - 1.6   # B on the FMC, 10 mm in front of C2
    x_left = -W / 2 + 12
    placements = []
    for k in range(2):
        x = x_left + k * 235
        placements.append(("C2", BOARDS["C2"], (x, board_y_c, H / 2 - 22)))
        # B over the FMC end of the C2 (FMC at the right edge of C2): B spans the right 150 mm, mid height
        placements.append(("B", BOARDS["B"], (x + 220 - 152, board_y_b, H / 2 - 22 - 60)))
    placements.append(("A2", BOARDS["A2"], (W / 2 - 12 - 130, board_y_c, H / 2 - 30)))
    mb = MeshBuilder()
    stats = {}
    tips = []
    for key, path, org in placements:
        w, h, n, tp = add_board(mb, key, path, org)
        stats[key] = (round(w), round(h), n)
        tips.append((key, tp))
        # standoffs at the four corners
        for dx in (4, w - 4):
            for dz in (4, h - 4):
                ylen = (D - org[1]) if key != "B" else P["fmc_gap"]
                y0 = org[1] + ylen / 2 + 0.8
                mb.cyl("alu", (org[0] + dx, y0, org[2] - dz), 2.5, ylen - 1.6, "Y", 12)
    # thermal pads on the hot parts (Zynq and AD9361s), shown as grey blocks for the cover pedestals
    for k in range(2):
        x = x_left + k * 235
        mb.box("alu", (x + 95, board_y_c - 4, H / 2 - 22 - 80), (30, 6, 30))
    # PSU module (48 V PoE++ / DC in -> 12 V), bottom left
    mb.box("alu", (-W / 2 + 70, D - 18, -H / 2 + 30), (110, 30, 45))
    boards = mb.build("Boards", col, M)

    # ---------------- bottom-face connectors (cable entry)
    mb = MeshBuilder()
    zb = -H / 2 - t
    ax = W / 2 - 12 - 130 + 10
    n_x = [ax + i * 20 for i in range(6)]                     # 6 N-type antenna inputs under A2
    for x in n_x:
        mb.cyl("brass", (x, D / 2, zb - 9), 8.0, 18, "Z", 24)   # N bulkhead body
        mb.cyl("brass", (x, D / 2, zb - 2), 11.0, 4, "Z", 6)    # hex nut
        mb.cyl("black", (x, D / 2, zb - 19.5), 4.0, 3, "Z", 16)
    others = [("GNSS", ax - 30, "brass", 6.5), ("FIBRE A", -W / 2 + 120, "black", 9.0), ("FIBRE B", -W / 2 + 355, "black", 9.0),
              ("PWR", -W / 2 + 40, "black", 10.0), ("VENT", 40, "black", 7.0)]
    for name, x, m, r in others:
        mb.cyl(m, (x, D / 2, zb - 10), r, 20, "Z", 24)
        mb.cyl(m, (x, D / 2, zb - 2), r + 3.5, 4, "Z", 6)
    mb.cyl("brass", (W / 2 - 15, D / 2, zb - 8), 3.0, 16, "Z", 12)    # earth stud
    # fibre cables and antenna coax hanging down (short stubs for the render)
    for x in n_x:
        mb.cyl("coax", (x, D / 2, zb - 38), 3.6, 36, "Z", 16)
    for x in (-W / 2 + 120, -W / 2 + 355):
        mb.cyl("blue", (x, D / 2, zb - 38), 3.0, 36, "Z", 16)
    mb.cyl("black", (-W / 2 + 40, D / 2, zb - 38), 4.5, 36, "Z", 16)
    mb.cyl("coax", (ax - 30, D / 2, zb - 38), 2.8, 36, "Z", 16)
    conn = mb.build("Connectors", col, M)
    labels = []
    for i, (x, s) in enumerate(zip(n_x, ["REF", "S1", "S2", "S3", "S4", "AUX"])):
        labels.append(text(col, s, (x, 10, zb - 0.2), 6, (math.pi, 0, 0), M["label"]))
    for name, x, *_ in others:
        labels.append(text(col, name, (x, 10, zb - 0.2), 6, (math.pi, 0, 0), M["label"]))

    # ---------------- internal cabling: bulkheads -> A2 inputs, A2 outputs -> both digitizers, SFP -> glands
    cables = []
    a2 = next(tp for k, tp in tips if k == "A2")
    xa2 = W / 2 - 12 - 130
    a2_in = sorted([p for p in a2["sma"] if p[0] < xa2 + 40], key=lambda p: -p[2])[:6]
    a2_out = sorted([p for p in a2["sma"] if p[0] > xa2 + 90], key=lambda p: -p[2])
    bs = [tp for k, tp in tips if k == "B"]
    for i, (x, p) in enumerate(zip(n_x, a2_in)):
        cables.append(cable(col, [(x, D / 2, -H / 2), (x, 22 + 2 * i, -H / 2 + 25), (p[0] - 18, 18 + 2 * i, p[2] - 8),
                                  (p[0], p[1] - 4, p[2]), (p[0], p[1], p[2])], 1.6, M["coax"], f"coax_in{i}"))
    for j, p in enumerate(a2_out):
        b = sorted(bs[j % 2]["sma"], key=lambda q: q[0])
        if not b:
            continue
        q = b[(j // 2) % len(b)]
        yy = 10 + (j % 6) * 1.8
        ztop = H / 2 - 8 - (j % 6) * 2.5
        cables.append(cable(col, [p, (p[0], yy, p[2]), (p[0] - 30, yy, ztop), (q[0], yy, ztop),
                                  (q[0], yy + 2, q[2] + 10), q], 1.2, M["coax"], f"coax_ab{j}"))
    for k, (key, tp) in enumerate([t_ for t_ in tips if t_[0] == "C2"]):
        if tp["sfp"]:
            s = tp["sfp"][0]
            gx = -W / 2 + 120 + 235 * k
            cables.append(cable(col, [s, (s[0], 14, s[2] + 12), (gx + 30, 12, 0), (gx, 20, -H / 2 + 20), (gx, D / 2, -H / 2)],
                                1.0, M["blue"], f"fibre{k}"))

    # ---------------- front cover with fins, gasket, screws, LEDs
    mb = MeshBuilder()
    ct = P["cover_t"]
    mb.box("cover", (0, -ct / 2, 0), (W + 2 * t, ct, H + 2 * t))
    nf = int((W - 20) // P["fin_pitch"])
    x0 = -(nf - 1) * P["fin_pitch"] / 2
    for i in range(nf):
        mb.box("cover", (x0 + i * P["fin_pitch"], -ct - P["fin_d"] / 2, 0), (P["fin_t"], P["fin_d"], H - 10))
    for sx in (-1, 1):                                         # cover screws in the flange
        for k in range(5):
            x = -W / 2 + k * W / 4
            for sz in (-1, 1):
                mb.cyl("steel", (x, -ct - 0.6, sz * (H / 2 + t / 2)), 2.8, 1.2, "Y", 16)
    mb.box("gasket", (0, 0.5, 0), (W + 1, 1.0, H + 1))
    # pedestals onto the Zynqs (inner side)
    for k in range(2):
        mb.box("alu", (x_left + k * 235 + 95, 6, H / 2 - 22 - 80), (28, 12, 28))
    mb.box("cover", (W / 2 - 40, -ct - 1, -H / 2 + 16), (60, 2, 14))   # LED window bar
    cover = mb.build("Cover", col, M)
    mb = MeshBuilder()
    for k in range(3):
        mb.box("led", (W / 2 - 58 + 18 * k, -ct - 2.2, -H / 2 + 16), (5, 1.5, 3))
    leds = mb.build("LEDs", col, M)

    # ---------------- mast bracket and pole
    mb = MeshBuilder()
    yb = D + t
    for sz in (-1, 1):
        mb.box("steel", (0, yb + 3, sz * 80), (300, 6, 40))                     # bracket arm on the back
        mb.box("steel", (0, yb + 30, sz * 80), (40, 50, 40))                     # stand-off to the pole
        mb.cyl("steel", (0, yb + 55 + P["pole_d"] / 2, sz * 80), P["pole_d"] / 2 + 4, 30, "Z", 32)   # clamp ring
    mb.cyl("pole", (0, yb + 55 + P["pole_d"] / 2, 0), P["pole_d"] / 2, 1600, "Z", 48)
    mast = mb.build("Mast", col, M)
    # UHF surveillance panel above the box (hardware/antenna/design.json): reflector, flanges, 4 slant bowties
    panel = []
    try:
        ad = json.load(open(os.path.join(HW, "antenna", "design.json")))
        u = ad["bands"]["uhf"]
        el = u["element"]
        RL, RW, FH = u["reflector_length_mm"], el["reflector_width_mm"], el["flange_height_mm"]
        hgt, L, wa = el["height_above_reflector_mm"], el["dipole_length_mm"], el["arm_width_mm"]
        zc = H / 2 + 420 + RW / 2
        yf = -40.0                                         # reflector plane (panel faces -Y)
        mb = MeshBuilder()
        mb.box("alu", (0, yf, zc), (RL, 2, RW))
        for s_ in (-1, 1):
            mb.box("alu", (0, yf - FH / 2, zc + s_ * RW / 2), (RL, FH, 2))
            mb.box("steel", (0, yf + 40, zc + s_ * RW * 0.3), (60, 80, 30))     # panel clamps to the pole
        mb.cyl("coax", (0, yf + 20, zc - RW / 2 - 200), 4, 380, "Z", 12)        # cable run down to the box
        panel = mb.build("Panel", col, M)
        mb = MeshBuilder()
        for i in range(4):
            x = (i - 1.5) * u["spacing_mm"]
            mb.box("plastic", (x, yf - hgt / 2, zc), (10, hgt, 10))            # element stem (PCB edge-on)
            for s_ in (-1, 1):                                                  # bowtie arms at +45 deg
                ln = (L / 2) * 0.95
                cx = x + s_ * ln / 2 * math.cos(math.radians(45))
                cz = zc + s_ * ln / 2 * math.sin(math.radians(45))
                bm = mb.parts.setdefault("pcb_C2", bmesh.new())
                m = (Matrix.Translation(Vector((cx, yf - hgt, cz)) * MM) @ Matrix.Rotation(math.radians(-45), 4, "Y")
                     @ Matrix.Diagonal((ln * MM, 1.6 * MM, wa * 1.5 * MM, 1)))
                bmesh.ops.create_cube(bm, size=1.0, matrix=m)
        panel += mb.build("Elements", col, M)
    except (OSError, KeyError):
        pass
    return {"cables": cables, "panel": panel,"body": body, "boards": boards, "connectors": conn, "cover": cover, "leds": leds, "mast": mast,
            "labels": labels, "stats": stats}


# ------------------------------------------------------------------ scene, lights, cameras, render
def setup_render(res=(1800, 1100), samples=96):
    s = bpy.context.scene
    s.render.engine = "CYCLES"
    s.cycles.samples = samples
    s.cycles.use_denoising = True
    s.render.resolution_x, s.render.resolution_y = res
    s.render.film_transparent = False
    s.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in s.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    w = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    s.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes.get("Background")
    grad = nt.nodes.new("ShaderNodeTexGradient")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(coord.outputs["Generated"], sep.inputs[0])
    mp = nt.nodes.new("ShaderNodeMapRange")
    mp.inputs["From Min"].default_value = -0.2
    mp.inputs["From Max"].default_value = 0.8
    nt.links.new(sep.outputs["Z"], mp.inputs["Value"])
    nt.links.new(mp.outputs["Result"], ramp.inputs[0])
    ramp.color_ramp.elements[0].color = (0.82, 0.86, 0.92, 1)
    ramp.color_ramp.elements[1].color = (0.35, 0.50, 0.75, 1)
    nt.links.new(ramp.outputs[0], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.35
    del grad


def light(name, loc, rot, power, size):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = power
    ld.size = size
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = rot
    bpy.context.scene.collection.objects.link(ob)
    return ob


def camera(name, loc, target, lens=50):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    ob = bpy.data.objects.new(name, cd)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def floor():
    me = bpy.data.meshes.new("Floor")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=6)
    bm.to_mesh(me)
    ob = bpy.data.objects.new("Floor", me)
    ob.location = (0, 0, -0.9)
    ob.data.materials.append(mat("Floor", (0.5, 0.52, 0.5), 0.0, 0.8))
    bpy.context.scene.collection.objects.link(ob)
    return ob


def render(view, parts):
    s = bpy.context.scene
    for o in list(s.objects):
        if o.type in ("CAMERA", "LIGHT") or o.name == "Floor":
            bpy.data.objects.remove(o, do_unlink=True)
    show = lambda objs, on: [setattr(o, "hide_render", not on) for o in objs]
    show(parts["cover"] + parts["leds"], view != "interior")
    show(parts["mast"] + parts["panel"], view == "mast")
    light("Key", (-1.2, -1.6, 1.4), (math.radians(55), 0, math.radians(-35)), 260, 1.2)
    light("Fill", (1.6, -1.0, 0.4), (math.radians(80), 0, math.radians(55)), 70, 1.5)
    light("Rim", (0.4, 1.4, 1.2), (math.radians(-50), 0, math.radians(170)), 150, 1.0)
    if view == "exterior":
        cam = camera("Cam", (-0.62, -0.95, -0.28), (0.0, 0.0, -0.06), 45)
        floor()
    elif view == "interior":
        cam = camera("Cam", (0.12, -0.78, 0.25), (0.0, 0.03, -0.02), 40)
        floor()
    else:
        cam = camera("Cam", (-1.55, -2.3, 0.75), (0.0, 0.05, 0.33), 40)
    s.camera = cam
    out = os.path.join(HERE, f"render_{view}.png")
    s.render.filepath = out
    bpy.ops.render.render(write_still=True)
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    views = argv or ["exterior", "interior", "mast"]
    parts = build()
    if os.environ.get("PREVIEW"):
        setup_render(res=(900, 550), samples=12)
    else:
        setup_render()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "enclosure.blend"))
    print("BOARDS", parts["stats"])
    for v in views:
        print("RENDERED", render(v, parts))


if __name__ == "__main__":
    main()
