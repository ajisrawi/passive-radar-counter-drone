"""Board A2 placement and board setup in OpenBoard (one band build at a time).

    python tools/layout_a2.py <uhf|mid|high|n78>

Reads board_a2/<band>/board_a2_<band>.netlist.json (the generator's part order) and the
OpenBoard project made by `openpcb sch-to-board` + tools/ob_footprints.py, then applies one
`openpcb batch`: outline, rules, net classes, placement and copper zones.

Stack-up (JLC04161H-7628, 1.6 mm): L1 RF (50 ohm CPW 0.36 mm over L2), L2 GND, L3 GND,
L4 calibration lines (0.36 mm over L3) and power traces. Six RF lanes run left (antenna SMA)
to right (two output SMAs), 18 mm apart. Power along the top, noise source below it.
"""
import json
import os
import subprocess
import sys

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

W, H = 130.0, 170.0
LANE_Y0, LANE_DY = 62.0, 18.0
X_IN, X_OUT = 6.0, 123.0
X_SPLIT = 110.0
SW_ROT = int(os.environ.get("A2_SW_ROT", "270"))
RF_NET = r"^CH[0-9]_(ANT|SW_O1|SW_IN|LNA|F|SPL|OUT)"
POWER = ["+12V", "VIN_RAW", "VIN_FUSED", "+5V6", "+5V_LNA_A", "+5V_LNA_B", "+5V_NS", "+3V3"]


def extents(fp):
    xs, ys = [], []
    for p in fp["pads"]:
        xs += [p["x"] - p["w"] / 2, p["x"] + p["w"] / 2]
        ys += [p["y"] - p["h"] / 2, p["y"] + p["h"] / 2]
    for seg in fp.get("outline", []):
        for pt in seg:
            xs.append(pt["x"])
            ys.append(pt["y"])
    return min(xs), max(xs), min(ys), max(ys)


class Placer:
    def __init__(self, board):
        self.fp = {c["ref"]: board["footprints"][c["footprint"]] for c in board["components"]}
        self.cmds, self.done = [], set()

    def at(self, ref, x, y, rot=0):
        self.cmds.append(["move", ref, f"{x:.3f}", f"{y:.3f}", "--rot", str(rot)])
        self.done.add(ref)

    def pack(self, refs, x0, y0, x1, y1, gap=1.2):
        """Row packing in creation order; footprint extents keep parts apart."""
        x, y, row = x0, y0, 0.0
        for r in refs:
            if r in self.done:
                continue
            a, b, c, d = extents(self.fp[r])
            w, h = b - a, d - c
            if x + w > x1:
                x, y, row = x0, y + row + gap, 0.0
            if y + h > y1:
                raise SystemExit(f"pack overflow at {r}: region {x0},{y0}-{x1},{y1} is too small")
            self.at(r, x - a, y - c)
            x += w + gap
            row = max(row, h)


def channel_parts(parts):
    """Group the generator's ordered parts per channel; rail decaps follow their LNA in order."""
    chans, cur = {}, None
    for ref, p in parts.items():
        nets = set(p["pins"].values())
        tagged = {n.split("_")[0] for n in nets if n[:2] == "CH" and n[2:3].isdigit()}
        if p["sheet"].startswith("channels_"):
            if tagged:
                cur = sorted(tagged)[0]
            chans.setdefault(cur, []).append(ref)
    return chans


def op(*args):
    r = subprocess.run(["node", OPENPCB, *args], capture_output=True, text=True)
    if r.returncode not in (0, 2):  # 2 = DRC found violations
        raise SystemExit(f"openpcb {args[0]} failed: {r.stderr or r.stdout}")
    return r.stdout


def setup(band):
    """Fresh 4-layer board from the OpenSchematic design, with real footprints."""
    base = os.path.join(HW, "board_a2", band)
    proj = os.path.join(base, f"board_a2_{band}.openboard.json")
    if os.path.exists(proj):
        os.remove(proj)
    op("new", proj, "--name", f"board_a2_{band}", "--layers", "4", "--width", str(W), "--height", str(H))
    op("sch-to-board", os.path.join(base, f"board_a2_{band}.sch.json"), proj)
    subprocess.run([sys.executable, os.path.join(HW, "tools", "ob_footprints.py"), proj], check=True)


def main(band):
    setup(band)
    base = os.path.join(HW, "board_a2", band)
    proj = os.path.join(base, f"board_a2_{band}.openboard.json")
    parts = json.load(open(os.path.join(base, f"board_a2_{band}.netlist.json")))["parts"]
    board = json.load(open(proj, encoding="utf-8"))
    pl = Placer(board)
    cmds = [["rules", "--width", "0.2", "--clearance", "0.2", "--via", "0.6", "--drill", "0.3"],
            ["class", "RF", "--match", RF_NET, "--width", "0.36", "--clearance", "0.2", "--layers", "F.Cu"],
            ["class", "CAL", "--match", r"^(CH[0-9]_CAL|CH[0-9]_SW_O2|NS_)", "--width", "0.36", "--clearance", "0.2"],
            ["class", "PWR", "--nets", ",".join(POWER), "--width", "0.4", "--clearance", "0.2"]]

    # ---------------------------------------------------------------- RF lanes
    for ch, refs in sorted(channel_parts(parts).items()):
        k = int(ch[2:])
        y = LANE_Y0 + k * LANE_DY
        x = None
        lna_x = None
        lc_series = 0
        for ref in refs:
            p = parts[ref]
            nets = set(p["pins"].values())
            v = p["value"]
            if ref.startswith("J") and f"{ch}_ANT" in nets:
                pl.at(ref, X_IN, y)
            elif ref.startswith("J") and f"{ch}_OUTA" in nets:
                pl.at(ref, X_OUT, y - 5.0)
            elif ref.startswith("J") and f"{ch}_OUTB" in nets:
                pl.at(ref, X_OUT, y + 5.0)
            elif f"{ch}_ANT" in nets:  # antenna DC block
                pl.at(ref, 12.5, y)
            elif f"{ch}_CAL" in nets:  # calibration DC block, above the switch
                pl.at(ref, 17.0, y - 3.5, 90)
            elif "SKY13351" in v:
                # pins 4-6 (VCTL2, INPUT, VCTL1) face the LNA: INPUT goes straight right, the two
                # control pins exit up and down; OUTPUT1 (antenna) and OUTPUT2 (cal) face the input SMA
                pl.at(ref, 17.0, y, SW_ROT)
                x = 17.0
            elif "SPF5043Z" in v:
                x += 5.5
                lna_x = x
                pl.at(ref, x, y)
                x += 1.0
            elif ref.startswith("L") and nets & {"+5V_LNA_A", "+5V_LNA_B"}:  # bias choke above the LNA output
                pl.at(ref, lna_x + 2.4, y - 3.4, 90)
            elif ref.startswith("C") and nets <= {"+5V_LNA_A", "+5V_LNA_B", "GND"}:  # choke decoupling
                n = sum(1 for c in pl.cmds if c[0] == "move" and c[1] in refs and parts[c[1]]["pins"] and
                        set(parts[c[1]]["pins"].values()) <= {"+5V_LNA_A", "+5V_LNA_B", "GND"})
                pl.at(ref, lna_x + 4.4 + 1.8 * (n % 2), y - 4.4, 90)
            elif ref.startswith("FL"):
                x += 5.5
                pl.at(ref, x, y)
            elif ref.startswith("R") and f"{ch}_SPL" in nets:
                if f"{ch}_OUTA" in nets:
                    pl.at(ref, X_SPLIT + 4.0, y - 2.2)
                elif f"{ch}_OUTB" in nets:
                    pl.at(ref, X_SPLIT + 4.0, y + 2.2)
                else:
                    pl.at(ref, X_SPLIT, y)
            elif "GND" in nets and len(nets) == 2 and not ref.startswith("C") or (
                    ref.startswith("C") and "GND" in nets and any(n.startswith(f"{ch}_F") for n in nets)):
                pl.at(ref, x + 1.6, y + 2.6, 90)  # LC filter shunt element, below the line
            else:  # series element on the line: DC blocks, LC filter series parts
                x += 3.6 if lc_series else 5.0
                if any(n.startswith(f"{ch}_F") and n != f"{ch}_F_IN" for n in nets):
                    lc_series += 1
                pl.at(ref, x, y)

    # ---------------------------------------------------------------- power band and noise source
    jack = next(r for r, p in parts.items() if p["value"] == "12V DC")
    pl.at(jack, 10.5, 9.0)
    holes = [r for r, p in parts.items() if r.startswith("H")]
    for r, (hx, hy) in zip(holes, [(4.5, 24.0), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)]):
        pl.at(r, hx, hy)
    pl.pack([r for r, p in parts.items() if p["sheet"] == "power"], 21.0, 3.0, W - 10.0, 31.0, gap=2.0)
    pl.pack([r for r, p in parts.items() if p["sheet"] == "noise_source"], 14.0, 34.0, W - 10.0, 52.0, gap=1.6)
    left = [r for r in parts if r not in pl.done]
    if left:
        raise SystemExit(f"unplaced: {left}")

    # ---------------------------------------------------------------- neck-down regions
    # SKY13351 (1 x 1 mm DFN, 0.35 mm pitch, 0.2 mm pad gaps) and the TDK n78 filter (0.045 mm
    # signal-to-GND pad gaps) cannot be entered by a 0.36 mm RF track at 0.2 mm clearance. Inside a
    # 4 x 4 mm region tracks narrow to 0.2 mm at 0.1 mm clearance (JLC 4-layer minimum 0.09 / 0.09 mm).
    pos = {c[1]: (float(c[2]), float(c[3])) for c in pl.cmds if c[0] == "move"}
    regions = []
    for ref, p in parts.items():
        if "SKY13351" in p["value"] or ref.startswith("FL"):
            x, y = pos[ref]
            regions.append(["region", f"NECK_{ref}", f"{x-2:.2f},{y-2:.2f},{x+2:.2f},{y+2:.2f}",
                            "--width", "0.2", "--clearance", "0.1"])
        elif ref.startswith("U") and p["sheet"] in ("power", "noise_source"):
            # fine-pitch power ICs (VQFN-16 0.5 mm, MSOP-12 0.65 mm, SOT-343, SOT-23-5): power tracks neck down
            fp = pl.fp[ref]
            a, b, c, d = extents(fp)
            x, y = pos[ref]
            regions.append(["region", f"NECK_{ref}", f"{x+a-1:.2f},{y+c-1:.2f},{x+b+1:.2f},{y+d+1:.2f}",
                            "--width", "0.25", "--clearance", "0.15"])

    # ---------------------------------------------------------------- switch control buses (pre-routed)
    # With SW_ROT = 270 the switch pads sit at: VCTL1 (CAL_EN) (x+0.49, y+0.35), INPUT (x+0.49, y),
    # VCTL2 (CAL_EN_N) (x+0.49, y-0.35). Each control pin gets a short F.Cu stub to a via, and two
    # straight B.Cu buses link the six switches. The autorouter only joins the bus ends to the header
    # and inverter; left to itself it tangled these lines with the switch INPUT tracks.
    buses = []
    if SW_ROT == 270:
        sw = sorted((pos[r] for r, p in parts.items() if "SKY13351" in p["value"]), key=lambda q: q[1])
        for net, s, xv in (("CAL_EN", +1, 19.2), ("CAL_EN_N", -1, 20.6)):
            bus = []
            for x, y in sw:
                px, py = x + 0.49, y + s * 0.35
                vy = y + s * 0.95
                buses.append(["trace", net, "F.Cu", "0.2", f"{px:.3f}", f"{py:.3f}", f"{px+0.51:.3f}", f"{py:.3f}",
                              f"{px+1.11:.3f}", f"{vy:.3f}", f"{xv:.3f}", f"{vy:.3f}"])
                buses.append(["via", net, f"{xv:.3f}", f"{vy:.3f}"])
                bus += [f"{xv:.3f}", f"{vy:.3f}"]
            buses.append(["trace", net, "B.Cu", "0.25", *bus])
        # switch INPUT -> DC block: straight F.Cu line through the 0.5 mm gap between the control stubs
        # (0.2 mm wide inside the gap, then the 0.36 mm 50 ohm width)
        for ref, p in parts.items():
            if "SKY13351" not in p["value"]:
                continue
            x, y = pos[ref]
            net = p["pins"]["5"]  # SKY13351 pin 5 = INPUT (netlist pins are keyed by number)
            cap = next(r for r, q in parts.items() if r.startswith("C") and net in q["pins"].values())
            cx = pos[cap][0] - 0.48  # left pad of the 0402 DC block
            buses.append(["trace", net, "F.Cu", "0.2", f"{x+0.49:.3f}", f"{y:.3f}", f"{x+1.6:.3f}", f"{y:.3f}"])
            buses.append(["trace", net, "F.Cu", "0.36", f"{x+1.6:.3f}", f"{y:.3f}", f"{cx:.3f}", f"{y:.3f}"])

    # ---------------------------------------------------------------- copper
    zones = regions + buses + [["zone", "GND", "In1.Cu", "0", "0", str(W), str(H)], ["zone", "GND", "In2.Cu", "0", "0", str(W), str(H)],
             ["zone", "GND", "F.Cu", "0", "0", str(W), str(H)], ["zone", "GND", "B.Cu", "0", "0", str(W), str(H)]]
    batch = cmds + pl.cmds + zones
    bfile = os.path.join(base, "layout_batch.json")
    json.dump(batch, open(bfile, "w"), indent=0)
    r = subprocess.run(["node", OPENPCB, "batch", proj, bfile], capture_output=True, text=True)
    res = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {"ok": False, "raw": r.stdout + r.stderr}
    bad = [x for x in res.get("results", []) if x.get("code")]
    print(json.dumps({"ok": res.get("ok"), "commands": len(batch), "failed": bad[:5], "raw": res.get("raw", "")[:500]}))


if __name__ == "__main__":
    main(sys.argv[1])
