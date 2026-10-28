"""Antenna radomes in Blender: the four surveillance panels (from design.json + radome.json), the LPDA-H paddle
radome, the bare LPDA-U, and a full site mast with the four receiver enclosures (hardware/enclosure).

    python hardware/antenna/radome_design.py            # first: writes radome.json
    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/antenna/radome_blender.py -- [views]
    views: cutaway family site (default: all)  -> hardware/antenna/render_radome_<view>.png, radome.blend
    PREVIEW=1 for a quick low-sample render.

Panel local frame (mm): x along the array, z up, panel faces -Y; y = 0 is the reflector's front surface.
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "enclosure"))
import enclosure_blender as eb  # noqa: E402  (helpers)
import enclosure_all_blender as ea  # noqa: E402  (the all-in-one receiver enclosure)

MM = eb.MM
AD = json.load(open(os.path.join(HERE, "design.json")))
RD = json.load(open(os.path.join(HERE, "radome.json")))
POLE_D = 114.0
C45, S45 = math.cos(math.radians(45)), math.sin(math.radians(45))
BAND_TEXT = {"uhf": "UHF 470-821 MHz", "mid": "1805-2170 MHz", "high": "2496-2690 MHz", "n78": "n78 3300-3800 MHz"}


# ------------------------------------------------------------------ helpers
def M():
    return {
        "radome": eb.mat("Radome RAL7035", (0.52, 0.53, 0.50), 0.0, 0.55),
        "radome_see": see_through(),
        "tray": eb.mat("Tray powder", (0.42, 0.43, 0.41), 0.0, 0.5),
        "alu": eb.mat("Aluminium", (0.80, 0.80, 0.82), 1.0, 0.32),
        "steel": eb.mat("Galvanised steel", (0.62, 0.63, 0.64), 1.0, 0.4),
        "fr4": eb.mat("FR4 green", (0.01, 0.16, 0.05), 0.0, 0.35),
        "cu": eb.mat("ENIG copper", (0.95, 0.70, 0.38), 1.0, 0.22),
        "metal": eb.mat("Connector metal", (0.85, 0.85, 0.86), 1.0, 0.2),
        "black": eb.mat("Black plastic", (0.02, 0.02, 0.025), 0.0, 0.45),
        "gasket": eb.mat("Gasket EPDM", (0.03, 0.03, 0.03), 0.0, 0.8),
        "grp": eb.mat("GRP arm", (0.70, 0.70, 0.66), 0.0, 0.45),
        "coax": eb.mat("Coax jacket", (0.08, 0.08, 0.10), 0.0, 0.6),
        "pole": eb.mat("Mast steel", (0.55, 0.56, 0.58), 1.0, 0.45),
        "label": eb.mat("Label dark", (0.12, 0.13, 0.14), 0.0, 0.5),
        "concrete": eb.mat("Concrete", (0.42, 0.42, 0.40), 0.0, 0.9),
    }


def see_through():
    m = bpy.data.materials.get("Radome see-through") or bpy.data.materials.new("Radome see-through")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.75, 0.76, 0.74, 1)
    b.inputs["Roughness"].default_value = 0.4
    b.inputs["Alpha"].default_value = 0.10
    try:
        m.surface_render_method = "BLENDED"
    except AttributeError:
        pass
    return m


def rbox(name, col, material, center, size, radius, open_face=None, shell=None, segs=8):
    """box with rounded edges (bevel modifier); open_face '+y'/'-y' removes that face; shell = wall thickness"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((*[s * MM for s in size], 1)))
    if open_face:
        ax = "xyz".index(open_face[1])
        sg = 1 if open_face[0] == "+" else -1
        f = [f for f in bm.faces if f.normal[ax] * sg > 0.9]
        bmesh.ops.delete(bm, geom=f, context="FACES_ONLY")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = Vector(center) * MM
    ob.data.materials.append(material)
    col.objects.link(ob)
    bv = ob.modifiers.new("bevel", "BEVEL")
    bv.width = radius * MM
    bv.segments = segs
    bv.limit_method = "ANGLE"
    if shell:
        so = ob.modifiers.new("shell", "SOLIDIFY")
        so.thickness = shell * MM
        so.offset = -1
        so.use_even_offset = True
    return ob


def prism(bm, pts, thick, x0, z0, nofs=0.0):
    """PCB-plane polygon pts [(s, y)] extruded `thick` along the normal; the PCB plane is the
    +45 deg slant plane through the Y axis: s -> (cos45, 0, sin45), normal -> (-sin45, 0, cos45)"""
    def P(s, y, n):
        return Vector((x0 + s * C45 - n * S45, y, z0 + s * S45 + n * C45)) * MM
    a = [bm.verts.new(P(s, y, nofs - thick / 2)) for s, y in pts]
    b = [bm.verts.new(P(s, y, nofs + thick / 2)) for s, y in pts]
    bm.faces.new(a[::-1])
    bm.faces.new(b)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))


def element(mb, band, x0, z0):
    """printed slant dipole (ANTENNA.md): bowtie/strip arms on both faces, stem with the taper balun, edge SMA"""
    el = AD["bands"][band]["element"]
    h, L, w, g = el["height_above_reflector_mm"], el["dipole_length_mm"], el["arm_width_mm"], el["feed_gap_mm"]
    wt = 2 * w if band == "uhf" else w
    fr4 = mb.parts.setdefault("fr4", bmesh.new())
    cu = mb.parts.setdefault("cu", bmesh.new())
    stem_w = min(16.0, 0.45 * L)
    for sg in (-1, 1):
        arm = [(sg * g / 2, -h - w / 2), (sg * L / 2, -h - wt / 2), (sg * L / 2, -h + wt / 2), (sg * g / 2, -h + w / 2)]
        pad = [(sg * 0.0, -h - w / 2 - 1.5), (sg * (L / 2 + 1.5), -h - wt / 2 - 1.5), (sg * (L / 2 + 1.5), -h + wt / 2 + 1.5),
               (sg * 0.0, -h + w / 2 + 1.5)]
        prism(fr4, pad if sg > 0 else pad[::-1], 1.6, x0, z0)
        a = arm if sg > 0 else arm[::-1]
        prism(cu, a, 0.07, x0, z0, nofs=(0.84 if sg < 0 else -0.84))      # left arm front face, right arm back face
    prism(fr4, [(-stem_w / 2, 12), (stem_w / 2, 12), (stem_w / 2, -h + w / 2), (-stem_w / 2, -h + w / 2)], 1.6, x0, z0)
    prism(cu, [(-1.4, 12), (1.4, 12), (2.0, -h + w / 2), (-2.0, -h + w / 2)], 0.07, x0, z0, nofs=0.84)     # 50 ohm strip -> 4 mm
    gw = min(12.0, stem_w - 2)
    prism(cu, [(-gw / 2, 12), (gw / 2, 12), (2.0, -h + w / 2), (-2.0, -h + w / 2)], 0.07, x0, z0, nofs=-0.84)  # ground 12 -> 4 mm
    mb.cyl("metal", (x0, 18, z0), 3.2, 12, "Y", 16)                      # edge SMA behind the reflector


def panel(col, band, see=False, pole_r=POLE_D / 2, label=True):
    """one surveillance panel in its radome; returns objects (local frame)"""
    mats = M()
    b, r = AD["bands"][band], RD["panels"][band]
    el = b["element"]
    Lr, Wr, FH = b["reflector_length_mm"], el["reflector_width_mm"], el["flange_height_mm"]
    ix, iz, iy = r["cover_inner_mm"]
    t, fl, td, rad = r["wall_mm"], r["flange_mm"], r["tray_depth_mm"], r["corner_radius_mm"]
    ox, oz = ix + 2 * t, iz + 2 * t
    objs = []
    cover_mat = mats["radome_see"] if see else mats["radome"]
    objs.append(rbox(f"{band}_cover", col, cover_mat, (0, -(iy + t) / 2, 0), (ox, iy + t, oz), rad, open_face="+y", shell=t))
    # cover flange (screwed to the tray face) and tray
    mb = eb.MeshBuilder()
    for sz in (-1, 1):
        mb.box("radome" if not see else "radome_see", (0, -2, sz * (oz / 2 + fl / 2 - 1)), (ox + 2 * fl, 4, fl))
        mb.box("radome" if not see else "radome_see", (sz * (ox / 2 + fl / 2 - 1), -2, 0), (fl, 4, oz))
    mb.box("gasket", (0, -0.2, 0), (ox + 2 * fl - 4, 0.6, oz + 2 * fl - 4))
    n_scr = 0
    per = 2 * (ox + oz + 4 * fl)
    pitch = per / max(8, round(per / 95))
    s = pitch / 2
    while s < per:                                                        # screws round the flange
        u = s
        X, Z = ox / 2 + fl / 2, oz / 2 + fl / 2
        if u < 2 * X:
            p = (-X + u, Z)
        elif u < 2 * X + 2 * Z:
            p = (X, Z - (u - 2 * X))
        elif u < 4 * X + 2 * Z:
            p = (X - (u - 2 * X - 2 * Z), -Z)
        else:
            p = (-X, -Z + (u - 4 * X - 2 * Z))
        mb.cyl("metal", (p[0], -4.6, p[1]), 3.6, 1.6, "Y", 12)
        n_scr += 1
        s += pitch
    objs += mb.build(f"{band}_flange", col, mats)
    objs.append(rbox(f"{band}_tray", col, mats["tray"], (0, td / 2, 0), (ox + 2 * fl, td, oz + 2 * fl), min(rad, 12)))
    # reflector + flanges + elements inside
    mb = eb.MeshBuilder()
    mb.box("alu", (0, -0.6, 0), (Lr, 1.2, Wr))
    for sz in (-1, 1):
        mb.box("alu", (0, -FH / 2, sz * Wr / 2), (Lr, FH, 2))
    for i in range(4):
        element(mb, band, (i - 1.5) * b["spacing_mm"], 0)
    # bottom face: 4 N bulkheads, vent, drain
    zb = -(oz / 2 + fl)
    for i in range(4):
        x = (i - 1.5) * min(45, ox / 5)
        mb.cyl("metal", (x, td / 2, zb - 9), 8.0, 18, "Z", 24)
        mb.cyl("metal", (x, td / 2, zb - 2), 11.0, 4, "Z", 6)
    mb.cyl("black", (ox / 2 - 25, td / 2, zb - 6), 6.0, 12, "Z", 20)    # pressure vent
    mb.cyl("black", (-ox / 2 + 20, td / 2, zb - 1), 2.5, 2.5, "Z", 12)   # drain
    # pole clamps on the back
    yb = td
    zc = [-oz * 0.28, oz * 0.28] if oz > 200 else [0.0]
    for z in zc:
        mb.box("steel", (0, yb + 3, z), (min(ox * 0.6, 260), 6, 36))
        mb.box("steel", (0, yb + 30, z), (36, 50, 36))
        mb.cyl("steel", (0, yb + 55 + pole_r, z), pole_r + 4, 28, "Z", 32)
    objs += mb.build(f"{band}_inside", col, mats)
    if label:
        objs.append(eb.text(col, "PCL  " + BAND_TEXT[band] + "  +45", (0, -(iy + t) - 0.3, -oz / 2 + max(12, oz * 0.07)),
                            max(5, min(14, oz * 0.045)), (math.radians(90), 0, 0), mats["label"]))
    return objs, {"pole_y": td + 55 + pole_r, "bottom_z": zb - 18, "td": td, "ox": ox, "oz": oz + 2 * fl}


def combined(col, see=False, pole_r=POLE_D / 2):
    """all four surveillance panels in one radome (radome.json 'combined'): UHF on top, 4G/5G row below"""
    mats = M()
    c = RD["combined"]
    ix, iz, iy = c["cover_inner_mm"]
    t, fl, td, rad = c["wall_mm"]["uhf_zone"], c["flange_mm"], c["tray_depth_mm"], c["corner_radius_mm"]
    ox, oz = ix + 2 * t, iz + 2 * t
    cm = "radome_see" if see else "radome"
    objs = [rbox("all_cover", col, mats[cm], (0, -(iy + t) / 2, 0), (ox, iy + t, oz), rad, open_face="+y", shell=t)]
    mb = eb.MeshBuilder()
    for sz in (-1, 1):
        mb.box(cm, (0, -2, sz * (oz / 2 + fl / 2 - 1)), (ox + 2 * fl, 4, fl))
        mb.box(cm, (sz * (ox / 2 + fl / 2 - 1), -2, 0), (fl, 4, oz))
    mb.box(cm, (0, -iy / 2, c["z_rib_mm"]), (ix, iy, 4))                # GRP rib between the two zones
    mb.box("gasket", (0, -0.2, 0), (ox + 2 * fl - 4, 0.6, oz + 2 * fl - 4))
    X, Z = ox / 2 + fl / 2, oz / 2 + fl / 2
    for i in range(11):                                                 # flange screws
        for sz in (-1, 1):
            mb.cyl("metal", (-X + i * 2 * X / 10, -4.6, sz * Z), 3.6, 1.6, "Y", 12)
    for i in range(1, 7):
        for sx in (-1, 1):
            mb.cyl("metal", (sx * X, -4.6, -Z + i * 2 * Z / 7), 3.6, 1.6, "Y", 12)
    objs += mb.build("all_flange", col, mats)
    objs.append(rbox("all_tray", col, mats["tray"], (0, td / 2, 0), (ox + 2 * fl, td, oz + 2 * fl), 12))
    mb = eb.MeshBuilder()
    layout = {"uhf": (0.0, c["z_uhf_mm"])}
    layout.update({b: (x, c["z_small_mm"]) for b, x in c["x_small_mm"].items()})
    for band, (xc, zc) in layout.items():
        b = AD["bands"][band]
        Lr, Wr, FH = b["reflector_length_mm"], b["element"]["reflector_width_mm"], b["element"]["flange_height_mm"]
        mb.box("alu", (xc, -0.6, zc), (Lr, 1.2, Wr))
        for sz in (-1, 1):
            mb.box("alu", (xc, -FH / 2, zc + sz * Wr / 2), (Lr, FH, 2))
        for i in range(4):
            element(mb, band, xc + (i - 1.5) * b["spacing_mm"], zc)
    zb = -(oz / 2 + fl)
    bulk = {}
    for g, band in enumerate(("uhf", "mid", "high", "n78")):
        gx = -345 + g * 230
        bulk[band] = []
        for i in range(4):
            x = gx + (i - 1.5) * 24
            mb.cyl("metal", (x, td / 2, zb - 9), 8.0, 18, "Z", 24)
            mb.cyl("metal", (x, td / 2, zb - 2), 11.0, 4, "Z", 6)
            bulk[band].append((x, td / 2, zb - 18))
    mb.cyl("black", (ox / 2 - 15, td / 2, zb - 6), 6.0, 12, "Z", 20)    # pressure vent
    mb.cyl("black", (-ox / 2 + 12, td / 2, zb - 1), 2.5, 2.5, "Z", 12)   # drain
    for z in (-oz * 0.28, oz * 0.28):
        mb.box("steel", (0, td + 3, z), (300, 6, 40))
        mb.box("steel", (0, td + 30, z), (40, 50, 40))
        mb.cyl("steel", (0, td + 55 + pole_r, z), pole_r + 4, 30, "Z", 32)
    objs += mb.build("all_inside", col, mats)
    objs.append(eb.text(col, "PCL  UHF + 1.8-2.2 + 2.6 + 3.5 GHz  +45", (0, -(iy + t) - 0.3, -oz / 2 + 22), 12,
                        (math.radians(90), 0, 0), mats["label"]))
    return objs, {"pole_y": td + 55 + pole_r, "bulk": bulk, "oz": oz + 2 * fl, "ox": ox + 2 * fl}


def lpda_h(col):
    """paddle radome around the printed LPDA-H, rolled +45 deg; boom along +x (beam points +x); rear stub at x=0"""
    mats = M()
    r = RD["lpda_h"]
    lx, lw, ld = r["outer_mm"]
    objs = [rbox("lpdah_radome", col, mats["radome"], (lx / 2, 0, 0), (lx, ld, lw), 8)]
    objs[0].rotation_euler = (math.radians(45), 0, 0)
    mb = eb.MeshBuilder()
    mb.cyl("black", (-8, 0, 0), 7, 16, "X", 20)                         # cable gland
    mb.cyl("grp", (-160, 0, 0), 12.5, 300, "X", 24)                     # GRP mast arm
    objs += mb.build("lpdah_arm", col, mats)
    return objs


def lpda_u(col):
    """aluminium twin-boom LPDA-U, rolled +45 deg; long end at x=0, beam points +x"""
    mats = M()
    u = AD["lpda"][0]
    mb = eb.MeshBuilder()
    xs = [120.0]
    for s in u["spacings_mm"]:
        xs.append(xs[-1] + s)
    bl = xs[-1] + 30
    bm_ = mb.parts.setdefault("alu", bmesh.new())
    R = Matrix.Rotation(math.radians(45), 4, "X")
    def put(center, size):
        m = R @ Matrix.Translation(Vector(center) * MM) @ Matrix.Diagonal((*[q * MM for q in size], 1))
        bmesh.ops.create_cube(bm_, size=1.0, matrix=m)
    for sn in (-1, 1):
        put((bl / 2, 0, sn * 10), (bl, 12, 12))                          # two booms, 8 mm gap
    for k, (x, l) in enumerate(zip(xs, u["element_lengths_mm"])):
        sg = 1 if k % 2 == 0 else -1
        for sn in (-1, 1):                                                  # half-elements alternate booms
            put((x, sn * sg * (l / 4 + 6), sn * 10), (4, l / 2, 4))
    mb.cyl("steel", (60, 0, 0), 30, 50, "X", 24)                        # boom clamp
    mb.cyl("grp", (-130, 0, 0), 12.5, 330, "X", 24)                     # mast arm
    return mb.build("lpdau", col, mats)


def place(objs, loc, rot_z=0.0, name="grp"):
    e = bpy.data.objects.new(name, None)
    e.location = Vector(loc) * MM
    e.rotation_euler = (0, 0, rot_z)
    bpy.context.scene.collection.objects.link(e)
    for o in objs:
        o.parent = e
    return e


def descendants(e):
    return [e] + [d for c in e.children for d in descendants(c)]


# ------------------------------------------------------------------ scenes
def build():
    node = ea.build(clear=True, with_pole=False)                       # all-in-one receiver enclosure
    col = bpy.data.collections.new("Antennas")
    bpy.context.scene.collection.children.link(col)
    mats = M()
    groups = {"cutaway": [], "family": [], "site": []}

    # ---- cutaway: the combined radome, see-through cover, on a test stand
    objs, info = combined(col, see=True)
    mb = eb.MeshBuilder()
    mb.cyl("pole", (0, info["pole_y"], -900 + (900 + info["oz"] / 2) / 2), POLE_D / 2, 900 + info["oz"] / 2, "Z", 48)
    mb.cyl("steel", (0, info["pole_y"], -900), 220, 12, "Z", 48)
    objs += mb.build("stand", col, mats)
    groups["cutaway"].append(place(objs, (20000, 0, 0), name="cutaway"))

    # ---- family: the combined radome + LPDA-H + LPDA-U, upright on the floor
    objs, info = combined(col)
    mb = eb.MeshBuilder()
    mb.cyl("pole", (0, info["pole_y"], -(info["oz"] / 2) - 150), POLE_D / 2, info["oz"] + 300, "Z", 32)
    mb.cyl("steel", (0, info["pole_y"], -info["oz"] / 2 - 300 + 3), 160, 8, "Z", 32)
    objs += mb.build("stand_all", col, mats)
    groups["family"].append(place(objs, (10000 + info["ox"] / 2, 0, info["oz"] / 2 + 300 - 900), name="fam_all"))
    x = info["ox"] + 80
    a = math.radians(-35)                                               # LPDAs point right-front: profile visible
    for fn, arm, px, py, z, nm in ((lpda_h, 310, x + 20, 250, 420, "fam_lpdah"), (lpda_u, 295, x + 120, 650, 560, "fam_lpdau")):
        e_ = place(fn(col), (10000 + px + arm * math.cos(a), py + arm * math.sin(a), -900 + z), rot_z=a, name=nm)
        groups["family"].append(e_)
        mb = eb.MeshBuilder()
        mb.cyl("pole", (10000 + px, py, -900 + z / 2), 12.5, z, "Z", 24)
        mb.cyl("steel", (10000 + px, py, -900 + 3), 70, 6, "Z", 24)
        groups["family"] += mb.build(f"{nm}_post", col, mats)

    # ---- site: one mast, one antenna radome, one receiver enclosure
    site = []
    zg = -2300.0                                                        # ground (roof) level
    mb = eb.MeshBuilder()
    mb.cyl("pole", (0, 0, (zg + 1150) / 2), POLE_D / 2, 1150 - zg, "Z", 48)
    mb.cyl("steel", (0, 0, zg + 6), 200, 12, "Z", 48)
    mb.box("concrete", (0, 0, zg - 40), (900, 900, 80))
    for z_ in (1000, 880):                                              # side-arm clamps for the references
        mb.cyl("steel", (0, 0, z_), POLE_D / 2 + 5, 40, "Z", 32)
    site += mb.build("site_mast", col, mats)
    objs, ainfo = combined(col)
    az = 300.0
    site.append(place(objs, (0, -ainfo["pole_y"], az), name="site_antennas"))
    for fn, arm_end, z, azim, nm in ((lpda_u, 295, 1000, 25, "site_lpdau"), (lpda_h, 310, 880, 145, "site_lpdah")):
        a = math.radians(azim)                                          # arm's far end sits on the mast axis
        site.append(place(fn(col), (arm_end * math.cos(a), arm_end * math.sin(a), z), rot_z=a, name=nm))
    # one receiver enclosure for all four band groups, on the front of the mast below the panels
    bz, by = -1150.0, -node["pole_y"]
    site.append(place(node["objs"], (0, by, bz), name="box_all"))
    zbox_top = bz + ea.PA["inner_h"] / 2 + ea.PA["wall"]
    for band in ("uhf", "mid", "high", "n78"):
        # 4 phase-matched cables: radome bulkheads -> down the mast -> round the box side -> enclosure S1-S4
        side = -1 if band in ("uhf", "mid") else 1
        xside = side * (ea.PA["inner_w"] / 2 + 45 + 10 * (["uhf", "mid", "high", "n78"].index(band) % 2))
        for i in range(4):
            lx, ly, lz = ainfo["bulk"][band][i]
            x0, y0, z0 = lx, -ainfo["pole_y"] + ly, az + lz
            xm = side * (40 + 10 * i + 45 * (["uhf", "mid", "high", "n78"].index(band) % 2))
            ym = -POLE_D / 2 - 12
            bx_, by_, bz_ = node["bulkheads"][band][i + 1]
            ex, ey, ez = bx_, by + by_, bz + bz_
            pts = [(x0, y0, z0), (x0, y0, z0 - 60), (xm * 0.6 + x0 * 0.4, (y0 + ym) / 2, z0 - 160), (xm, ym, z0 - 300),
                   (xm, ym, zbox_top + 160), (xside, ym - 30, zbox_top + 40), (xside + side * 4 * i, by + 35, zbox_top - 200),
                   (xside + side * 4 * i, by + 35, ez - 40), (ex, ey, ez - 90), (ex, ey, ez - 30), (ex, ey, ez)]
            site.append(eb.cable(col, pts, 4.0, mats["coax"], f"feed_{band}{i}"))
    groups["site"] = site
    return groups, zg


def floor(z, center=(0, 0), size=8.0, mat_=None):
    me = bpy.data.meshes.new("Floor")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    bm.to_mesh(me)
    ob = bpy.data.objects.new("Floor", me)
    ob.location = (center[0], center[1], z * MM)
    ob.data.materials.append(mat_ or eb.mat("Floor", (0.5, 0.52, 0.5), 0.0, 0.8))
    bpy.context.scene.collection.objects.link(ob)
    return ob


def render(view, groups, zg):
    s = bpy.context.scene
    for o in list(s.objects):
        if o.type in ("CAMERA", "LIGHT") or o.name.startswith("Floor"):
            bpy.data.objects.remove(o, do_unlink=True)
    for k, objs in groups.items():
        for root in objs:
            for o in descendants(root):
                o.hide_render = (k != view)
    if view == "cutaway":
        ox = 20.0
        eb.light("Key", (ox - 1.2, -1.8, 1.4), (math.radians(55), 0, math.radians(-35)), 330, 1.4)
        eb.light("Fill", (ox + 1.8, -1.2, 0.3), (math.radians(80), 0, math.radians(55)), 90, 1.6)
        eb.light("Rim", (ox + 0.4, 1.5, 1.2), (math.radians(-50), 0, math.radians(170)), 160, 1.0)
        floor(-906, (ox, 0))
        cam = eb.camera("Cam", (ox - 0.95, -1.7, 0.45), (ox + 0.02, 0.02, 0.0), 40)
    elif view == "family":
        ox = 10.0
        eb.light("Key", (ox - 0.4, -2.6, 1.6), (math.radians(55), 0, math.radians(-15)), 600, 2.5)
        eb.light("Fill", (ox + 3.6, -1.5, 0.4), (math.radians(80), 0, math.radians(60)), 160, 2.0)
        eb.light("Rim", (ox + 1.2, 2.0, 1.4), (math.radians(-50), 0, math.radians(170)), 220, 2.0)
        floor(-900, (ox + 1.3, 0))
        cam = eb.camera("Cam", (ox + 0.45, -3.3, 0.6), (ox + 1.05, 0.1, -0.45), 36)
    else:
        eb.light("Sun1", (-2.5, -3.5, 3.0), (math.radians(50), 0, math.radians(-35)), 1400, 3.0)
        eb.light("Fill", (3.5, -2.0, 0.0), (math.radians(80), 0, math.radians(60)), 300, 3.0)
        eb.light("Rim", (1.0, 3.0, 2.5), (math.radians(-45), 0, math.radians(170)), 500, 2.5)
        floor(zg - 80, (0, 0), 12.0)
        cam = eb.camera("Cam", (-2.5, -4.4, 0.6), (0.0, 0.0, -0.42), 33)
    s.camera = cam
    out = os.path.join(HERE, f"render_radome_{view}.png")
    s.render.filepath = out
    bpy.ops.render.render(write_still=True)
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    views = argv or ["cutaway", "family", "site"]
    eb.P["pole_d"] = POLE_D
    groups, zg = build()
    if os.environ.get("PREVIEW"):
        eb.setup_render(res=(900, 600), samples=10)
    else:
        eb.setup_render(res=(1800, 1200), samples=96)
    bpy.context.scene.view_settings.exposure = -1.4
    try:
        bpy.context.scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "radome.blend"))
    for v in views:
        print("RENDERED", render(v, groups, zg))


if __name__ == "__main__":
    main()
