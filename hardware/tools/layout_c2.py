"""Board C2 placement and constraints in OpenBoard.

    python tools/setup_c2.py && python tools/layout_c2.py

Coordinates are OpenBoard's (y up). The FFG676 ball groups (footprint frame): banks 12/13 (AD9361
LVDS) on +x, GTX quad 112 at (+x, -y), PS DDR on +y, PS MIO at (-x, +y), bank 33 at (-x, -y). So:
DDR3 above the Zynq, SFP+ cages on the bottom edge below quad 112 (openings facing out), FMC on the
right edge facing banks 12/13, PS peripherals and their connectors on the left, GNSS bottom-left,
power along the top. Board B (mezzanine) sits over the FMC end; tall parts stay clear of it.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout_a2 import extents  # noqa: E402

OPENPCB = r"C:\Users\ahmad\Documents\PCB Router 2022\packages\cli\dist\cli\src\openpcb.js"
HW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(HW, "board_c2")
PROJ = os.path.join(BASE, "board_c2.openboard.json")
W, H = 220.0, 200.0
ZX, ZY = 95.0, 80.0
# +1V0/+1V35 (In3) and +3V3/VADJ (In6) are split planes and only need short via stubs, so they stay at
# default width. Routed as 0.4 mm tracks, +1V35 and VADJ caused 170 conflicts in the FPGA-DDR3 channel.
POWER = ["+12V", "VIN_RAW", "+12V_FMC", "+1V8", "MGTAVCC", "MGTAVCC_SW",
         "MGTAVTT", "MGTAVTT_SW", "MGTVCCAUX", "DDR_VTT", "SFP0_VCCT", "SFP0_VCCR", "SFP1_VCCT", "SFP1_VCCR",
         "PHY_1V0", "VCCPLL", "VCCADC"]


class Placer:
    def __init__(self, board):
        self.fp = {c["ref"]: board["footprints"][c["footprint"]] for c in board["components"]}
        self.cmds, self.done, self.pos = [], set(), {}

    def at(self, ref, x, y, rot=0, back=False):
        cmd = ["move", ref, f"{x:.3f}", f"{y:.3f}", "--rot", str(rot)]
        if back:
            cmd += ["--side", "back"]
        self.cmds.append(cmd)
        self.done.add(ref)
        self.pos[ref] = (x, y)

    def pack(self, refs, x0, y0, x1, y1, gap=1.0, back=False, strict=True):
        """Row packing (rot 0) in the given order; back-side parts are mirrored in x.
        strict=False returns the parts that did not fit instead of stopping."""
        x, y, row = x0, y0, 0.0
        left = []
        for r in refs:
            if r in self.done:
                continue
            a, b, c, d = extents(self.fp[r])
            if back:
                a, b = -b, -a
            w, h = b - a, d - c
            if x + w > x1:
                x, y, row = x0, y + row + gap, 0.0
            if y + h > y1:
                if strict:
                    raise SystemExit(f"pack overflow at {r}: region {x0},{y0}-{x1},{y1}")
                left.append(r)
                continue
            self.at(r, x - a, y - c, back=back)
            x += w + gap
            row = max(row, h)
        return left

    def pack_strips(self, refs, strips, gap=0.45, back=True):
        """Fill the strips (x0, y0, x1, y1) in order; stop when every part has a place."""
        for s in strips:
            refs = self.pack(refs, *s, gap=gap, back=back, strict=False)
            if not refs:
                return
        raise SystemExit(f"strips full, {len(refs)} parts left: {refs[:5]}")


def main():
    parts = json.load(open(os.path.join(BASE, "board_c2.netlist.json")))["parts"]
    board = json.load(open(PROJ, encoding="utf-8"))
    d = board
    d["outline"] = [{"x": 0, "y": 0}, {"x": W, "y": 0}, {"x": W, "y": H}, {"x": 0, "y": H}]
    json.dump(d, open(PROJ, "w", encoding="utf-8"))
    pl = Placer(board)
    sheet = lambda s: [r for r, p in parts.items() if p["sheet"] == s]  # noqa: E731
    val = lambda r: parts[r]["value"]  # noqa: E731
    small_cap = lambda r: r.startswith("C") and val(r) in ("100n", "10n", "470n", "1u")  # noqa: E731

    # ---- anchors
    pl.at("U1", ZX, ZY)
    pl.at("U2", ZX - 6.0, ZY + 35.0)   # 4 mm extra from the FPGA: room for DDR length-tuning serpentines
    pl.at("U3", ZX + 6.0, ZY + 35.0)
    pl.at("J1", W - 8.0, 122.0, 90)                       # FMC carrier, vertical on the right edge
    sfp = [r for r in parts if parts[r]["lib_id"] == "Interface_Optical:SFP+"]
    for k, r in enumerate(sorted(sfp)):                   # openings face the bottom edge
        pl.at(r, ZX + 5.0 + 21.0 * k, 42.2, 90)
    holes = [r for r in parts if r.startswith("H")]
    for r, (hx, hy) in zip(holes, [(4.5, 4.5), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)]):
        pl.at(r, hx, hy)
    # left-edge connectors (openings face -x)
    by = {val(r): r for r in parts}
    pl.at(by["12V DC"], 11.0, 170.0, 0)
    pl.at(by["HR911130C"], 13.0, 135.0, 90)
    pl.at(by["USB-C console"], 5.5, 108.0, 90)
    pl.at(by["microSD"], 11.0, 88.0, 90)
    gnss_sma = next(r for r in sheet("gnss") if val(r) == "GNSS ANT")
    pl.at(gnss_sma, 30.0, 5.0)

    # ---- BGA decoupling: back side, in strips just outside the ball field.
    # With through-vias only, every ball's escape via lands on the back layer; 0402 caps packed under
    # the FFG676 covered 164 of its 625 via sites (26 %) and the router plateaued at ~1700 conflicts.
    # The FPGA's top side is left free: it is the FPGA <-> DDR3 routing channel.
    zh = 14.6  # FFG676 half-size + 0.8 mm
    pl.pack_strips([r for r in sheet("zynq_power") if small_cap(r)],
                   [(ZX - zh - 5.0, ZY - zh, ZX - zh, ZY + zh),           # left
                    (ZX - zh, ZY - zh - 5.0, ZX + zh, ZY - zh),           # bottom
                    (ZX + zh, ZY - zh, ZX + zh + 5.0, ZY + zh)])          # right
    dx0, dx1, dy0, dy1 = ZX - 11.4, ZX + 10.9, ZY + 27.6, ZY + 42.6     # DDR3 pair + 0.8 mm
    pl.pack_strips([r for r in sheet("ddr3") if small_cap(r)],
                   [(dx0, dy1, dx1, dy1 + 5.0),                           # above
                    (dx0 - 5.0, dy0, dx0, dy1 + 5.0),                     # left
                    (dx1, dy0, dx1 + 2.5, dy1)])                          # right (terminations beyond)

    # ---- around the parts they serve
    pl.pack(sheet("ddr3"), ZX + 13.5, ZY + 26.0, ZX + 48.0, ZY + 52.0, gap=0.5)            # VTT terminations
    # SFP support parts. The 156.25 MHz GTX reference clock chain is packed together, last, in signal order
    # (oscillator, 100R termination, AC caps): packed apart, the MGTREF156_N breakout looped 21 mm around the
    # oscillator. (Packed first, the tall oscillator overflowed the region.)
    pre_nets = {}
    for n in board["nets"]:
        for p in n["pins"]:
            pre_nets.setdefault(p.split("-")[0], set()).add(n["name"])
    clk = [r for r in sheet("sfp") if pre_nets.get(r, set()) & {"REF156_P_OSC", "REF156_N_OSC"}]
    clk.sort(key=lambda r: (not r.startswith("Y"), not r.startswith("R"), r))
    pl.pack([r for r in sheet("sfp") if r not in clk] + clk, ZX - 12.0, 46.5, ZX + 48.0, 56.5, gap=0.6)
    # GTX supplies next to quad 112 (bottom-right ball corner), on their own plane islands (In4 MGTAVCC,
    # In5 MGTAVTT). From the power band they were ~100 mm POWER tracks and the two-phase route left
    # MGTAVCC/MGTAVTT/MGTVCCAUX open between the 1 mm balls. Ferrites + bulk caps beside the corner,
    # the two bucks in the empty corner right of the SFP+ cages, fed by a +12V island on In4.
    nets_of = {}
    for n in board["nets"]:
        for p in n["pins"]:
            nets_of.setdefault(p.split("-")[0], set()).add(n["name"])
    mgt = ("MGTAVCC", "MGTAVTT", "MGTVCCAUX")
    fbs = sorted(r for r in parts if r.startswith("FB") and nets_of.get(r, set()) & set(mgt))
    bulk = sorted((r for r in sheet("zynq_power") if r.startswith("C") and not small_cap(r)
                   and nets_of.get(r, set()) & set(mgt)), key=lambda r: int(r[1:]))
    pl.pack(fbs + bulk, ZX + 16.0, 57.5, ZX + 45.0, 65.5, gap=0.8)
    pl.pack(sheet("zynq_power"), ZX - 52.0, ZY - 14.0, ZX - 15.0, ZY + 24.0, gap=0.8)       # bulk caps, config
    pl.pack(sheet("zynq_ps"), 24.0, ZY + 26.0, ZX - 20.0, ZY + 57.0, gap=0.8)              # QSPI, SD, USB-UART
    pl.pack(sheet("ethernet"), 26.0, ZY + 58.0, ZX - 16.0, ZY + 79.0, gap=1.4)   # roomier PHY area
    pl.pack(sheet("gnss"), 8.0, 12.0, ZX - 16.0, ZY - 16.0, gap=1.0)
    pl.pack(sheet("fmc"), ZX + 20.0, ZY - 12.0, W - 20.0, ZY + 18.0, gap=1.0)
    # +1V35 and VADJ bucks sit on their own plane islands (In4 / In5), so each rail reaches its plane
    # directly instead of through a long thin trace from the power band (DRC had left them open).
    order = list(parts)

    def buck_group(u):
        i = order.index(u)
        grp = [u]
        for r in order[i + 1:]:
            if r.startswith("U") or parts[r]["sheet"] != "power":
                break
            grp.append(r)
        return grp

    pl.pack(buck_group("U7"), ZX - 12.0, ZY + 50.0, ZX + 15.0, ZY + 68.0, gap=1.0)   # +1V35, above the DDR3
    pl.pack(buck_group("U9"), ZX + 55.0, ZY + 50.0, ZX + 85.0, ZY + 68.0, gap=1.0)   # VADJ, near the FMC
    by_val = lambda v: next(r for r in parts if parts[r]["value"].startswith(v))  # noqa: E731
    mgt_bucks = [u for u in parts if u.startswith("U") and nets_of.get(u, set()) & {"MGTAVCC_SW", "MGTAVTT_SW"}]
    pl.pack([r for u in sorted(mgt_bucks) for r in buck_group(u)], ZX + 46.0, 6.0, W - 16.0, 46.0, gap=1.2)
    # FMC 12 V fuse + bulk cap beside the FMC's 12 V pins, over the +12V strip (In4)
    fmc12 = sorted(r for r in parts if parts[r]["sheet"] == "power" and "+12V_FMC" in nets_of.get(r, set()))
    pl.pack(fmc12, W - 30.0, 94.0, W - 15.0, 108.0, gap=1.0)
    # DDR3 VTT regulator beside its terminations, on the DDR_VTT island (In5) and the +1V35 island (In4);
    # only the parts wired to it (the netlist order after it also holds unrelated power parts)
    vtt = by_val("TPS51200")
    vtt_nets = nets_of[vtt] - {"GND", "+3V3", "+1V35", "PG_ALL"}
    pl.pack([r for r in buck_group(vtt) if r == vtt or nets_of.get(r, set()) & vtt_nets],
            ZX + 17.0, ZY + 54.0, ZX + 52.0, ZY + 70.0, gap=1.0)
    pl.pack(sheet("power"), 20.0, H - 40.0, W - 12.0, H - 2.0, gap=1.4)
    left = [r for r in parts if r not in pl.done]
    if left:
        raise SystemExit(f"unplaced: {left}")

    # ---- constraints
    # JLCPCB multilayer limits (jlcpcb.com/capabilities): via hole to track 0.2 mm, via hole to hole 0.2 mm,
    # 0.09 mm trace/space; through via 0.4 / 0.2 mm (0.1 mm annular ring).
    # HDI (JLCPCB HDI service, 4-32 layers): laser microvias 0.25 / 0.1 mm (laser drill 0.075-0.15 mm, pad
    # >= drill + 0.15 mm) F.Cu-In1, F.Cu-In2 (skip via, built as stacked), In8-B.Cu, In7-B.Cu; buried
    # mechanical via 0.4 / 0.2 mm In2-In7. Laser hole rules use OpenBoard's defaults, which equal JLCPCB's
    # (0.15 mm hole to copper, 0.24 mm hole to hole on different nets, 0.13 mm same net).
    # With through vias only, 10 layers plateaued at ~160-200 conflicts (FPGA / DDR3 escape).
    HDI = ("0.25:0.1:F.Cu:In1.Cu,0.25:0.1:F.Cu:In2.Cu,0.25:0.1:In8.Cu:B.Cu,0.25:0.1:In7.Cu:B.Cu,"
           "0.4:0.2:In2.Cu:In7.Cu")
    cmds = [["rules", "--width", "0.1", "--clearance", "0.1", "--via", "0.4", "--drill", "0.2", "--clear-via-types",
             "--holeToCopper", "0.2", "--holeToHole", "0.2"],
            ["rules", "--via-type", HDI],
            ["class", "PWR", "--nets", ",".join(POWER), "--width", "0.4", "--clearance", "0.15"]]
    pairs = []
    for k in (0, 1):
        for p_, n_ in ((f"SFP{k}_TXP_FPGA", f"SFP{k}_TXN_FPGA"), (f"SFP{k}_TD_P", f"SFP{k}_TD_N"),
                       (f"SFP{k}_RXP_FPGA", f"SFP{k}_RXN_FPGA"), (f"SFP{k}_RD_P", f"SFP{k}_RD_N")):
            pairs.append((p_, n_, 0.4))
    pairs += [("MGTREF156_P", "MGTREF156_N", 0.4), ("REF156_P_OSC", "REF156_N_OSC", 0.4),
              ("FPGA_REFCLK_P", "FPGA_REFCLK_N", 1.0), ("DDR_CK_P", "DDR_CK_N", 0.3)]
    pairs += [(f"DDR_DQS{k}_P", f"DDR_DQS{k}_N", 0.3) for k in range(4)]
    nets = {n["name"] for n in board["nets"]}
    pairs += [(f"{n[:-2]}_P", f"{n[:-2]}_N", 1.0) for n in sorted(nets) if n.startswith("AD") and n.endswith("_P")
              and f"{n[:-2]}_N" in nets]
    d = json.load(open(PROJ, encoding="utf-8"))
    # maxUncoupled: pairs must be able to split to escape the 1.0 mm BGA (two coupled 0.1 mm lines at
    # 0.15 mm gap barely fit between balls); with 3 mm the probe route had 310 pair-to-pair conflicts there.
    d["diffPairs"] = [{"name": p_[:-2] if p_.endswith(("_P", "_N")) else p_, "p": p_, "n": n_, "gap": 0.2,
                       "tolerance": 0.05, "maxUncoupled": 5.0 if p_.startswith(("SFP", "MGTREF", "REF156")) else 10.0,
                       "maxSkew": skew} for p_, n_, skew in pairs]
    groups = []
    for b in range(4):  # DDR byte lanes
        groups.append({"name": f"DDR_BYTE{b}", "tolerance": 0.5,
                       "nets": [f"DDR_DQ{8*b+k}" for k in range(8)] + [f"DDR_DM{b}", f"DDR_DQS{b}_P", f"DDR_DQS{b}_N"]})
    groups.append({"name": "DDR_ADDR_CMD", "tolerance": 1.0,
                   "nets": [f"DDR_A{k}" for k in range(15)] + [f"DDR_BA{k}" for k in range(3)] +
                   ["DDR_RAS_B", "DDR_CAS_B", "DDR_WE_B", "DDR_CS_B", "DDR_CKE", "DDR_ODT", "DDR_CK_P", "DDR_CK_N"]})
    for chip in (1, 2, 3):  # each AD9361's LVDS bus
        groups.append({"name": f"AD{chip}_LVDS", "tolerance": 1.0,
                       "nets": sorted(n for n in nets if n.startswith(f"AD{chip}_") and n.endswith(("_P", "_N")))})
    d["lengthGroups"] = groups
    json.dump(d, open(PROJ, "w", encoding="utf-8"))

    # ---- neck-down regions: a 0.4 mm / 0.15 mm power track needs 0.70 mm between pads, but the
    # FFG676 has 0.55 mm, the DDR3 0.44 mm, the FMC 0.62 mm and the QFN/TSSOP/SFP+ parts 0.2-0.3 mm.
    # Without these the router fought over those pins for hours (pass 5 > 40 min, 3000+ conflicts).
    import itertools
    pin_net = {p: n["name"] for n in board["nets"] for p in n["pins"]}
    regions = []
    for c in board["components"]:
        ref = c["ref"]
        fp = pl.fp[ref]
        pads = [p for p in fp["pads"] if not p.get("npth")]
        if len(pads) < 3 or not any(pin_net.get(f"{ref}-{p['id']}") in POWER for p in pads):
            continue
        gap = min((max(max(abs(a["x"] - b["x"]) - (a["w"] + b["w"]) / 2, 0),
                       max(abs(a["y"] - b["y"]) - (a["h"] + b["h"]) / 2, 0))
                   for a, b in itertools.combinations(pads, 2) if a["id"] != b["id"]), default=9)
        if gap >= 0.7:
            continue
        a, b, cc, dd = extents(fp)
        rot = next((int(x[x.index("--rot") + 1]) for x in pl.cmds if x[1] == ref), 0)
        if rot in (90, 270):
            a, b, cc, dd = -dd, -cc, a, b
        x, y = pl.pos[ref]
        regions.append(["region", f"NECK_{ref}", f"{x+a-0.8:.2f},{y+cc-0.8:.2f},{x+b+0.8:.2f},{y+dd+0.8:.2f}",
                        "--width", "0.1", "--clearance", "0.1"])
    print(f"neck-down regions: {len(regions)}")

    poly = lambda *pts: ",".join(f"{x:.1f},{y:.1f}" for x, y in pts)  # noqa: E731
    rect = lambda x0, y0, x1, y1: poly((x0, y0), (x1, y0), (x1, y1), (x0, y1))  # noqa: E731
    whole = rect(0, 0, W, H)
    # Plane islands, checked by check_islands() below: no pin of the layer's base net (or of another island)
    # may sit inside an island, or it would lose its plane.
    ISLANDS = {
        "In4.Cu": ("+1V0", [
            ("MGTAVCC", rect(ZX - 14.4, 50.0, ZX + 43.0, ZY - 4.0)),        # GTX corner + ferrite/bulk caps
            ("+12V", poly((ZX + 45.0, 3.0), (W - 13.0, 3.0), (W - 13.0, H - 26.0), (W - 35.0, H - 26.0),
                          (W - 35.0, 50.0), (ZX + 45.0, 50.0))),             # MGT bucks + strip to the band
            ("+1V35", rect(ZX - 18.0, ZY + 17.5, ZX + 53.0, ZY + 71.0)),     # DDR3, terminations, VTT reg
        ]),
        "In5.Cu": ("+3V3", [
            # GTX ball rows + the bottom decap strip + ferrite/bulk caps
            ("MGTAVTT", poly((ZX - 14.4, 57.0), (ZX + 45.0, 57.0), (ZX + 45.0, 66.0), (ZX + 13.8, 66.0),
                             (ZX + 13.8, 73.0), (ZX + 0.6, 73.0), (ZX + 0.6, 66.0), (ZX - 14.4, 66.0))),
            ("+1V8", rect(ZX - 14.4, 64.0, ZX + 2.0, ZY + 3.0)),             # +1V8 ball rows (left half)
            # terminations + VTT regulator, and the VTT decap row above the DDR3 pair
            ("DDR_VTT", poly((ZX + 17.0, ZY + 24.0), (ZX + 52.0, ZY + 24.0), (ZX + 52.0, ZY + 71.0),
                             (ZX + 17.0, ZY + 71.0), (ZX + 17.0, ZY + 48.2), (ZX - 12.0, ZY + 48.2),
                             (ZX - 12.0, ZY + 42.2), (ZX + 17.0, ZY + 42.2))),
            ("VADJ", rect(ZX + 3.5, ZY - 6.0, W - 1.0, H - 46.0)),           # banks 12/13 and the FMC run
        ]),
    }
    planes = []
    for layer, (base, isl) in ISLANDS.items():
        planes.append(["split-plane", layer] + [f"{n}={p}" for n, p in isl] + [f"{base}={whole}", "--gap", "0.5"])
    zones = regions + [
        ["zone", "GND", "In1.Cu", "0", "0", str(W), str(H)], ["zone", "GND", "In8.Cu", "0", "0", str(W), str(H)],
        *planes,
        ["zone", "GND", "F.Cu", "0", "0", str(W), str(H)], ["zone", "GND", "B.Cu", "0", "0", str(W), str(H)]]
    batch = cmds + pl.cmds + zones
    bfile = os.path.join(BASE, "layout_batch.json")
    json.dump(batch, open(bfile, "w"))
    r = subprocess.run(["node", OPENPCB, "batch", PROJ, bfile], capture_output=True, text=True)
    res = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {"ok": False, "raw": r.stdout + r.stderr}
    bad = [x for x in res.get("results", []) if x.get("code")]
    print(json.dumps({"ok": res.get("ok"), "commands": len(batch), "failed": bad[:5], "diff_pairs": len(pairs),
                      "length_groups": len(groups), "raw": res.get("raw", "")[:400]}))
    untwist_series_pairs()
    check_islands(ISLANDS)


def pad_positions(d):
    """Board position and net of every pad: {(ref, pad id): (x, y, net)}."""
    import math
    pin_net = {p: n["name"] for n in d["nets"] for p in n["pins"]}
    out = {}
    for c in d["components"]:
        t = math.radians(c.get("rot", 0))
        for p in d["footprints"][c["footprint"]]["pads"]:
            x = -p["x"] if c.get("side") == "back" else p["x"]
            out[(c["ref"], str(p["id"]))] = (c["x"] + x * math.cos(t) - p["y"] * math.sin(t),
                                            c["y"] + x * math.sin(t) + p["y"] * math.cos(t), pin_net.get(f"{c['ref']}-{p['id']}"))
    return out


def untwist_series_pairs():
    """Series parts of a differential pair (AC-coupling caps, e.g. C(P) and C(N) between REF156_*_OSC and
    MGTREF156_*) placed in the wrong order make the pair's lanes cross: the router cannot route a crossing
    on one layer, so one side detours (MGTREF156 came out 18 mm longer on N). Each such P/N part pair is
    swapped and/or turned 180 degrees, whichever puts every pin nearest the rest of its net."""
    import itertools
    import math
    d = json.load(open(PROJ, encoding="utf-8"))
    comp = {c["ref"]: c for c in d["components"]}
    pads = pad_positions(d)
    pn = {}
    for p in d["diffPairs"]:
        pn[p["p"]], pn[p["n"]] = (p["name"], "p"), (p["name"], "n")
    two = {}
    for (ref, _), (_, _, net) in pads.items():
        two.setdefault(ref, []).append(net)
    series = {r: tuple(sorted(n)) for r, n in two.items() if len(n) == 2 and all(x in pn for x in n)}
    by_key = {}
    for r, (a, b) in series.items():
        key = tuple(sorted((pn[a][0], pn[b][0])))
        by_key.setdefault(key, {})[(pn[a][1], pn[b][1])] = r
    centroid = {}
    for (ref, pid), (x, y, net) in pads.items():
        centroid.setdefault(net, []).append((ref, x, y))

    def cost(ref, cx, cy, rot):
        c = comp[ref]
        t = math.radians(rot)
        s = 0.0
        for p in d["footprints"][c["footprint"]]["pads"]:
            x, y, net = pads[(ref, str(p["id"]))]
            px = cx + p["x"] * math.cos(t) - p["y"] * math.sin(t)
            py = cy + p["x"] * math.sin(t) + p["y"] * math.cos(t)
            others = [(ox, oy) for r2, ox, oy in centroid.get(net, []) if r2 != ref]
            if others:
                s += min(math.hypot(px - ox, py - oy) for ox, oy in others)
        return s

    cmds = []
    for key, m in by_key.items():
        rp, rn = m.get(("p", "p")), m.get(("n", "n"))
        if not rp or not rn or comp[rp].get("side") == "back" or comp[rn].get("side") == "back":
            continue
        A, B = comp[rp], comp[rn]
        best = None
        for swap, flip in itertools.product((False, True), (0, 180)):
            (xa, ya), (xb, yb) = ((B["x"], B["y"]), (A["x"], A["y"])) if swap else ((A["x"], A["y"]), (B["x"], B["y"]))
            ra, rb = (A.get("rot", 0) + flip) % 360, (B.get("rot", 0) + flip) % 360
            c = cost(rp, xa, ya, ra) + cost(rn, xb, yb, rb)
            if best is None or c < best[0] - 1e-6:
                best = (c, swap, flip, (xa, ya, ra), (xb, yb, rb))
        c0 = cost(rp, A["x"], A["y"], A.get("rot", 0)) + cost(rn, B["x"], B["y"], B.get("rot", 0))
        if best[1] or best[2]:
            for ref, (x, y, r) in ((rp, best[3]), (rn, best[4])):
                cmds.append(["move", ref, f"{x:.3f}", f"{y:.3f}", "--rot", str(int(r))])
            print(f"untwist {rp}/{rn} ({key[0]} - {key[1]}): {'swap ' if best[1] else ''}{'turn 180 ' if best[2] else ''}"
                  f"{c0:.1f} -> {best[0]:.1f} mm")
    if cmds:
        bfile = os.path.join(BASE, "untwist_batch.json")
        json.dump(cmds, open(bfile, "w"))
        subprocess.run(["node", OPENPCB, "batch", PROJ, bfile], capture_output=True, text=True, check=True)


def check_islands(islands):
    """Each plane island: which pins of the layer's base net (or of an earlier island) it covers.
    Those pins lose their plane and must be reached by a trace instead."""
    import math
    d = json.load(open(PROJ, encoding="utf-8"))
    pin_net = {p: n["name"] for n in d["nets"] for p in n["pins"]}
    pads = []
    for c in d["components"]:
        t = math.radians(c.get("rot", 0))
        for p in d["footprints"][c["footprint"]]["pads"]:
            x = -p["x"] if c.get("side") == "back" else p["x"]
            n = pin_net.get(f"{c['ref']}-{p['id']}")
            if n:
                pads.append((c["ref"], n, c["x"] + x * math.cos(t) - p["y"] * math.sin(t),
                             c["y"] + x * math.sin(t) + p["y"] * math.cos(t)))
    inside = lambda x, y, pts: sum(  # noqa: E731
        1 for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1])
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay)) % 2 == 1
    for layer, (base, isl) in islands.items():
        polys = []
        for net, ptxt in isl:
            v = [float(s) for s in ptxt.split(",")]
            polys.append((net, list(zip(v[::2], v[1::2]))))
        plane_nets = {base} | {n for n, _ in polys}
        own, lost = {n: 0 for n in plane_nets}, {n: set() for n in plane_nets}
        for r, n, x, y in pads:
            if n not in plane_nets:
                continue
            region = next((m for m, pts in polys if inside(x, y, pts)), base)   # first island wins
            if region == n:
                own[n] += 1
            else:
                lost[n].add(f"{r}(in {region})")
        for n in [m for m, _ in polys] + [base]:
            print(f"plane {layer} {n}: {own[n]} pins on it; off it: {len(lost[n])} {sorted(lost[n])[:6]}")


if __name__ == "__main__":
    main()
