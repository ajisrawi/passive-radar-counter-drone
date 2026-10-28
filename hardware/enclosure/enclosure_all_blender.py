"""All-in-one receiver enclosure: the whole site in one box. Four band columns (uhf, mid, high, n78); each column
holds that band's Board A2 at the bottom (next to its 6 antenna bulkheads) and its two receiver stacks
(Board B on Board C2) above. Shared: one 48 V -> 12 V PSU, a GNSS 1:8 splitter, a fibre tray to one
12-fibre IP67 connector, surge protection.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/enclosure/enclosure_all_blender.py -- [views]
    views: exterior interior (default: both) -> hardware/enclosure/render_all_<view>.png, enclosure_all.blend
    PREVIEW=1 for a quick low-sample render.

Uses the helpers of enclosure_blender.py (same frame: X across, Z up, cover inner face y = 0, back wall y = D).
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enclosure_blender as eb  # noqa: E402

MM = eb.MM
BANDS = ["uhf", "mid", "high", "n78"]
BAND_LABEL = {"uhf": "UHF", "mid": "1.8-2.2G", "high": "2.6G", "n78": "n78"}
B_PATH = {"uhf": "board_b/route/board_b_routed.openboard.json",
          "mid": "board_b_bands/mid/board_b_mid.openboard.json",
          "high": "board_b_bands/high/board_b_high.openboard.json",
          "n78": "board_b_bands/n78/board_b_n78.openboard.json"}
A2_PATH = {b: f"board_a2/{b}/board_a2_{b}.openboard.json" for b in BANDS}
C2_PATH = "board_c2/board_c2.openboard.json"

PA = {
    "col_pitch": 245.0, "margin": 12.0,
    "inner_w": 980.0, "inner_h": 690.0, "inner_d": 70.0,
    "wall": 5.0, "cover_t": 6.0, "fin_d": 28.0, "fin_t": 3.0, "fin_pitch": 11.0,
    "standoff": 8.0, "fmc_gap": 10.0, "pole_d": 114.0,
}


def mats():
    m = eb.mat
    return {
        "body": m("Powder RAL7035", (0.46, 0.47, 0.44), 0.0, 0.5),
        "cover": m("Powder RAL7035 cover", (0.44, 0.45, 0.42), 0.0, 0.45),
        "alu": m("Aluminium", (0.80, 0.80, 0.82), 1.0, 0.32),
        "steel": m("Galvanised steel", (0.62, 0.63, 0.64), 1.0, 0.4),
        "gasket": m("Gasket EPDM", (0.03, 0.03, 0.03), 0.0, 0.8),
        "brass": m("N-type brass", (0.85, 0.72, 0.42), 1.0, 0.25),
        "black": m("Black plastic", (0.02, 0.02, 0.025), 0.0, 0.45),
        "blue": m("Fibre blue", (0.05, 0.25, 0.75), 0.0, 0.4),
        "yellow": m("Fibre yellow", (0.85, 0.65, 0.05), 0.0, 0.4),
        "pcb_C2": m("Soldermask green", (0.005, 0.12, 0.035), 0.0, 0.3),
        "pcb_B": m("Soldermask green B", (0.005, 0.12, 0.035), 0.0, 0.3),
        "pcb_A2": m("Soldermask blue A2", (0.005, 0.03, 0.16), 0.0, 0.3),
        "ic": m("IC epoxy", (0.03, 0.03, 0.035), 0.0, 0.4),
        "passive": m("Passive", (0.08, 0.08, 0.08), 0.0, 0.5),
        "cap": m("Ceramic cap", (0.35, 0.26, 0.15), 0.0, 0.5),
        "metal": m("Connector metal", (0.85, 0.85, 0.86), 1.0, 0.2),
        "plastic": m("Connector plastic", (0.08, 0.08, 0.09), 0.0, 0.5),
        "coax": m("Coax jacket", (0.08, 0.08, 0.10), 0.0, 0.6),
        "label": m("Label white", (0.95, 0.95, 0.95), 0.0, 0.5),
        "pole": m("Mast steel", (0.55, 0.56, 0.58), 1.0, 0.45),
        "led": m("LED green", (0.1, 1.0, 0.2), 0.0, 0.3, emission=(0.1, 1.0, 0.2)),
    }


def build(clear=True, with_pole=True):
    """returns {"objs": all objects except the pole, "pole": [...], "bulkheads": {band: [(x,y,z) x6]}, "stats": ...}"""
    if clear:
        eb.clear()
    col = bpy.data.collections.new("NodeAll")
    bpy.context.scene.collection.children.link(col)
    M = mats()
    W, H, D, t = PA["inner_w"], PA["inner_h"], PA["inner_d"], PA["wall"]
    mb = eb.MeshBuilder()
    # ---------------- body
    mb.box("body", (0, D + t / 2, 0), (W + 2 * t, t, H + 2 * t))
    mb.box("body", (-(W + t) / 2, D / 2, 0), (t, D, H + 2 * t))
    mb.box("body", ((W + t) / 2, D / 2, 0), (t, D, H + 2 * t))
    mb.box("body", (0, D / 2, (H + t) / 2), (W, D, t))
    mb.box("body", (0, D / 2, -(H + t) / 2), (W, D, t))
    for sx in (-1, 1):
        for sz in (-1, 1):
            mb.cyl("body", (sx * (W / 2 + t / 2), D / 2 + t / 2, sz * (H / 2 + t / 2)), t * 0.8, D + t, "Y")
    body = mb.build("AllBody", col, M)

    # ---------------- boards: one column per band
    yc = D - PA["standoff"] - 0.8
    yb = yc - PA["fmc_gap"] - 1.6
    ztop = H / 2 - 22
    mb = eb.MeshBuilder()
    stats, tips = {}, []
    xcol = [-W / 2 + PA["margin"] + k * PA["col_pitch"] for k in range(4)]
    for k, band in enumerate(BANDS):
        x = xcol[k]
        pl = []
        for r in range(2):                                    # two stacks per band, stacked vertically
            zc = ztop - r * 220
            pl.append(("C2", C2_PATH, (x, yc, zc), r))
            pl.append(("B", B_PATH[band], (x + 220 - 152, yb, zc - 60), r))
        pl.append(("A2", A2_PATH[band], (x, yc, ztop - 440 - 18), 0))
        for key, path, org, r in pl:
            w, h, n, tp = eb.add_board(mb, key, path, org)
            stats[f"{band}_{key}{r}"] = (round(w), round(h), n)
            tips.append((band, key, r, org, tp))
            for dx in (4.5, w - 4.5):
                for dz in (4.5, h - 4.5):
                    ylen = (D - org[1]) if key != "B" else PA["fmc_gap"]
                    mb.cyl("alu", (org[0] + dx, org[1] + ylen / 2 + 0.8, org[2] - dz), 2.5, ylen - 1.6, "Y", 12)
            if key == "C2":
                mb.box("alu", (org[0] + 95, yc - 4, org[2] - 80), (30, 6, 30))          # thermal pad on the Zynq
        # spare strip right of the A2 (90 x 170 mm): shared modules, one per column
        sx, sz = x + 175, ztop - 440 - 18 - 85
        if k == 0:
            mb.box("alu", (sx, D - 15, sz), (60, 26, 60))                              # GNSS 1:8 splitter
            for i in range(8):
                mb.cyl("metal", (sx - 21 + 6 * i, D - 30, sz + 22), 2.2, 6, "Y", 10)
        elif k == 1:
            mb.box("alu", (sx, D - 22, sz), (80, 40, 160))                             # PSU 48 V -> 12 V, 250 W
            mb.box("black", (sx, D - 43, sz - 60), (60, 3, 20))
        elif k == 2:
            mb.box("plastic", (sx, D - 10, sz), (80, 16, 150))                          # fibre tray
        else:
            mb.box("black", (sx, D - 20, sz + 30), (70, 36, 90))                        # DC surge + terminal block
            mb.box("metal", (sx, D - 39, sz - 40), (70, 4, 30))
    boards = mb.build("AllBoards", col, M)

    # ---------------- bottom face: 4 x 6 N bulkheads under each A2, shared entries
    mb = eb.MeshBuilder()
    zb = -H / 2 - t
    bulk, labels = {}, []
    for k, band in enumerate(BANDS):
        ax = xcol[k] + 10
        n_x = [ax + i * 20 for i in range(6)]
        bulk[band] = [(x, D / 2, zb - 56) for x in n_x]
        for x in n_x:
            mb.cyl("brass", (x, D / 2, zb - 9), 8.0, 18, "Z", 24)
            mb.cyl("brass", (x, D / 2, zb - 2), 11.0, 4, "Z", 6)
            mb.cyl("black", (x, D / 2, zb - 19.5), 4.0, 3, "Z", 16)
            mb.cyl("coax", (x, D / 2, zb - 38), 3.6, 36, "Z", 16)
        for i, (x, s) in enumerate(zip(n_x, ["REF", "S1", "S2", "S3", "S4", "AUX"])):
            labels.append(eb.text(col, s, (x, 10, zb - 0.2), 5, (math.pi, 0, 0), M["label"]))
        labels.append(eb.text(col, BAND_LABEL[band], (ax + 50, 10, zb - 0.2 - 0 + 0), 7, (math.pi, 0, 0), M["label"]))
    shared = [("GNSS", xcol[0] + 175, "brass", 6.5), ("FIBRE x12", xcol[2] + 175, "black", 12.0),
              ("48V", xcol[1] + 175, "black", 12.0), ("VENT", xcol[3] + 155, "black", 7.0), ("VENT", xcol[1] + 205, "black", 7.0)]
    for name, x, m_, r in shared:
        mb.cyl(m_, (x, D / 2, zb - 10), r, 20, "Z", 24)
        mb.cyl(m_, (x, D / 2, zb - 2), r + 3.5, 4, "Z", 6)
        labels.append(eb.text(col, name, (x, 10, zb - 0.2), 5, (math.pi, 0, 0), M["label"]))
    mb.cyl("blue", (xcol[2] + 175, D / 2, zb - 40), 5.0, 40, "Z", 16)
    mb.cyl("black", (xcol[1] + 175, D / 2, zb - 40), 6.0, 40, "Z", 16)
    mb.cyl("coax", (xcol[0] + 175, D / 2, zb - 38), 2.8, 36, "Z", 16)
    mb.cyl("brass", (W / 2 - 15, D / 2, zb - 8), 3.0, 16, "Z", 12)                     # earth stud
    conn = mb.build("AllConnectors", col, M)

    # ---------------- internal cabling
    cables = []
    for k, band in enumerate(BANDS):
        a2 = next(tp for b, key, r, o, tp in tips if b == band and key == "A2")
        xa2 = xcol[k]
        a2_in = sorted([p for p in a2["sma"] if p[0] < xa2 + 40], key=lambda p: -p[2])[:6]
        a2_out = sorted([p for p in a2["sma"] if p[0] > xa2 + 90], key=lambda p: -p[2])
        for i, (x, p) in enumerate(zip([b[0] for b in bulk[band]], a2_in)):
            cables.append(eb.cable(col, [(x, D / 2, -H / 2), (x, 22 + 2 * i, -H / 2 + 22), (p[0] - 16, 18 + 2 * i, p[2] - 6),
                                         (p[0], p[1] - 4, p[2]), p], 1.6, M["coax"], f"in_{band}{i}"))
        bs = [tp for b, key, r, o, tp in tips if b == band and key == "B"]
        for j, p in enumerate(a2_out):
            b = sorted(bs[j % 2]["sma"], key=lambda q: q[0])
            if not b:
                continue
            q = b[(j // 2) % len(b)]
            yy = 10 + (j % 6) * 1.8
            xr = xa2 + 140 + (j % 6) * 3
            cables.append(eb.cable(col, [p, (p[0] + 8, yy, p[2]), (xr, yy, p[2] + 25), (xr, yy, q[2] - 30),
                                         (q[0], yy, q[2] - 12), (q[0], q[1] - 3, q[2]), q], 1.2, M["coax"], f"ab_{band}{j}"))
        for r, tp in enumerate([tp for b, key, r_, o, tp in tips if b == band and key == "C2"]):
            if tp["sfp"]:
                s = tp["sfp"][0]
                tx, tz = xcol[2] + 175, ztop - 440 - 18 - 85 + 60
                cables.append(eb.cable(col, [s, (s[0], 14, s[2] + 10), (s[0] + 20, 12, s[2] + 25), (xa2 + 232, 12, s[2]),
                                             (xa2 + 232, 12, tz + 120), (tx, 14, tz + 40), (tx, 16, tz)],
                                       0.9, M["yellow"], f"fibre_{band}{r}"))

    # ---------------- cover: fins, gasket, screws, pedestals, LED bar
    mb = eb.MeshBuilder()
    ct = PA["cover_t"]
    mb.box("cover", (0, -ct / 2, 0), (W + 2 * t, ct, H + 2 * t))
    nf = int((W - 20) // PA["fin_pitch"])
    x0 = -(nf - 1) * PA["fin_pitch"] / 2
    for i in range(nf):
        mb.box("cover", (x0 + i * PA["fin_pitch"], -ct - PA["fin_d"] / 2, 0), (PA["fin_t"], PA["fin_d"], H - 10))
    nsx, nsz = 8, 5
    for i in range(nsx + 1):
        for sz in (-1, 1):
            mb.cyl("steel", (-W / 2 + i * W / nsx, -ct - 0.6, sz * (H / 2 + t / 2)), 2.8, 1.2, "Y", 16)
    for i in range(1, nsz):
        for sx in (-1, 1):
            mb.cyl("steel", (sx * (W / 2 + t / 2), -ct - 0.6, -H / 2 + i * H / nsz), 2.8, 1.2, "Y", 16)
    mb.box("gasket", (0, 0.5, 0), (W + 1, 1.0, H + 1))
    for k in range(4):
        for r in range(2):
            mb.box("alu", (xcol[k] + 95, 6, ztop - r * 220 - 80), (28, 12, 28))
    mb.box("cover", (W / 2 - 70, -ct - 1, -H / 2 + 16), (120, 2, 14))
    cover = mb.build("AllCover", col, M)
    mb = eb.MeshBuilder()
    for i in range(8):
        mb.box("led", (W / 2 - 119 + 14 * i, -ct - 2.2, -H / 2 + 16), (5, 1.5, 3))
    leds = mb.build("AllLEDs", col, M)

    # ---------------- mast bracket (two clamp rings) and pole
    mb = eb.MeshBuilder()
    yb_ = D + t
    for sz in (-1, 1):
        mb.box("steel", (0, yb_ + 4, sz * 220), (600, 8, 50))
        mb.box("steel", (0, yb_ + 30, sz * 220), (50, 50, 50))
        mb.cyl("steel", (0, yb_ + 55 + PA["pole_d"] / 2, sz * 220), PA["pole_d"] / 2 + 5, 40, "Z", 32)
    bracket = mb.build("AllBracket", col, M)
    pole = []
    if with_pole:
        mb = eb.MeshBuilder()
        mb.cyl("pole", (0, yb_ + 55 + PA["pole_d"] / 2, 0), PA["pole_d"] / 2, 2000, "Z", 48)
        pole = mb.build("AllPole", col, M)
    return {"objs": body + boards + conn + labels + cables + cover + leds + bracket, "cover": cover + leds,
            "pole": pole, "bulkheads": bulk, "stats": stats, "pole_y": yb_ + 55 + PA["pole_d"] / 2}


def render(view, parts):
    s = bpy.context.scene
    for o in list(s.objects):
        if o.type in ("CAMERA", "LIGHT") or o.name == "Floor":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in parts["cover"]:
        o.hide_render = view == "interior"
    eb.light("Key", (-1.6, -2.4, 1.8), (math.radians(55), 0, math.radians(-35)), 520, 1.8)
    eb.light("Fill", (2.2, -1.5, 0.5), (math.radians(80), 0, math.radians(55)), 140, 2.0)
    eb.light("Rim", (0.5, 2.0, 1.6), (math.radians(-50), 0, math.radians(170)), 260, 1.4)
    eb.floor()
    if view == "exterior":
        cam = eb.camera("Cam", (-1.1, -1.75, -0.62), (0.0, 0.0, -0.12), 40)
    else:
        cam = eb.camera("Cam", (0.18, -1.75, 0.45), (0.0, 0.03, -0.02), 38)
    s.camera = cam
    out = os.path.join(HERE, f"render_all_{view}.png")
    s.render.filepath = out
    bpy.ops.render.render(write_still=True)
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    views = argv or ["exterior", "interior"]
    parts = build()
    if os.environ.get("PREVIEW"):
        eb.setup_render(res=(900, 600), samples=10)
    else:
        eb.setup_render(res=(1800, 1200), samples=96)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "enclosure_all.blend"))
    print("BOARDS", len(parts["stats"]), sum(v[2] for v in parts["stats"].values()), "components")
    for v in views:
        print("RENDERED", render(v, parts))


if __name__ == "__main__":
    main()
