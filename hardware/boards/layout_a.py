"""Board A placement (run with KiCad Python). 4 layers, 130 x 152 mm (enlarged from 100 x 112 for routing room).

Stack-up (JLC04161H-7628, 1.6 mm): L1 RF/signal, L2 solid GND, L3 power, L4 GND/signal.
50 ohm grounded CPW on L1: 0.36 mm track, 0.20 mm gap to GND pour, 0.21 mm to L2.
Six channel lanes run left (antenna SMA) to right (output SMA), 13 mm apart, with
GND via fences between lanes. Noise source on the left column, power along the top.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import pcbnew  # noqa: E402
from pcbgen import Layout  # noqa: E402

W, H = 130.0, 152.0
LANE_Y0, LANE_DY = 60.0, 16.0  # power band 0-31 mm, noise source 32-51 mm, lanes below
X_SMA_IN, X_SMA_OUT = 7.0, W - 7.0
# x of each chain node: ANT, SW_RF2, SW_C, LNA_IN, LNA_OUT, F0, F2, F4, F6 (series parts sit between nodes)
XS = [15.0, 22.5, 30.0, 38.0, 48.0, 61.0, 74.0, 87.0, 100.0]
X_SW = (XS[1] + XS[2]) / 2   # RF switch centre
X_LNA = (XS[3] + XS[4]) / 2  # LNA centre


def find_series(lay, a, b):
    for ref, p in lay.data.items():
        nets = set(p["pins"].values())
        if a in nets and b in nets and len(p["pins"]) <= 6:
            return ref
    raise KeyError((a, b))


def shunts(lay, net, exclude):
    out = []
    for ref, p in lay.data.items():
        nets = set(p["pins"].values())
        if ref in exclude or net not in nets or len(p["pins"]) != 2:
            continue
        other = (nets - {net}) or {net}
        if other <= {"GND", "+5V_LNA", "+3V3"}:
            out.append(ref)
    return out


def main():
    lay = Layout("board_a", os.path.join(HERE, "..", "board_a", "board_a.netlist.json"), layers=4,
                 rules={"track": 0.2, "clearance": 0.2, "via": 0.6, "drill": 0.3})
    lay.outline(W, H)
    data = lay.data

    # ---------------------------------------------------------------- channel lanes
    for k in range(6):
        y = LANE_Y0 + k * LANE_DY
        p = f"CH{k}"
        sma_in = [r for r, d in data.items() if d["pins"].get("5") == f"{p}_ANT"][0]
        sma_out = [r for r, d in data.items() if d["pins"].get("5") == f"{p}_F6"][0]
        lay.place(sma_in, X_SMA_IN, y, 0)
        lay.place(sma_out, X_SMA_OUT, y, 0)
        chain = [f"{p}_ANT", f"{p}_SW_RF2", f"{p}_SW_C", f"{p}_LNA_IN", f"{p}_LNA_OUT", f"{p}_F0", f"{p}_F2",
                 f"{p}_F4", f"{p}_F6"]
        xs = XS
        series = [find_series(lay, a, b) for a, b in zip(chain, chain[1:])]
        used = set(series) | {sma_in, sma_out}
        for ref, x0, x1 in zip(series, xs, xs[1:]):
            n = len(data[ref]["pins"])
            rot = 0 if n == 2 else (0 if "PE4259" in data[ref]["value"] else 90)
            lay.place(ref, (x0 + x1) / 2, y, rot)
        # shunt parts at each node (filter shunts, LNA choke), alternating above/below
        for i, net in enumerate(chain[4:], start=4):
            for j, ref in enumerate(shunts(lay, net, used)):
                xm = xs[i]
                dy = -3.0 if (j % 2 == 0) else 3.0
                lay.place(ref, xm, y + dy, 90)
                used.add(ref)
        # calibration branch: DC block on RF1 just above the switch, splitter arm resistor beside it
        cal_c = find_series(lay, f"{p}_CAL", f"{p}_SW_RF1")
        lay.place(cal_c, X_SW, y - 4.0, 90)
        arm = [r for r, d in data.items() if set(d["pins"].values()) == {"NS_P2_B", f"{p}_CAL"}][0]
        lay.place(arm, X_SW, y - 7.0, 90)
        used |= {cal_c, arm}
    # lane decoupling (+3V3 for switches, +5V_LNA for LNAs) placed near each lane's parts
    lane_dec = [r for r, d in data.items() if set(d["pins"].values()) in ({"+3V3", "GND"}, {"+5V_LNA", "GND"})
                and r not in getattr(lay, "placed", set()) and d["value"] in ("100p", "100n")]
    by_rail = {"+3V3": [], "+5V_LNA": []}
    for r in lane_dec:
        by_rail[(set(data[r]["pins"].values()) - {"GND"}).pop()].append(r)
    for k in range(6):
        y = LANE_Y0 + k * LANE_DY
        if by_rail["+3V3"]:
            lay.place(by_rail["+3V3"].pop(0), X_SW, y + 3.5, 90)
        for x in (X_LNA - 0.8, X_LNA + 0.8):
            if by_rail["+5V_LNA"]:
                lay.place(by_rail["+5V_LNA"].pop(0), x, y - 4.8, 90)
    # GND via fences between lanes and along the lane edges
    for k in range(7):
        yf = LANE_Y0 - LANE_DY / 2 + k * LANE_DY
        x = 12.0
        while x < W - 12.0:
            lay.via(x, yf, "GND", 0.6, 0.3)
            x += 2.5

    # ---------------------------------------------------------------- noise source (left of lanes, top)
    ns = [r for r, d in data.items() if any(n.startswith("NS_") for n in d["pins"].values())
          and r not in lay.placed]
    ns += [r for r, d in data.items() if set(d["pins"].values()) <= {"+5V_NS", "GND"} and r not in lay.placed
           and d["value"] in ("100p", "100n")]
    lay.pack(ns, 14.0, 33.0, W - 10.0, gap=1.5, y1=LANE_Y0 - LANE_DY / 2 - 0.8)

    # ---------------------------------------------------------------- power (top band)
    jack = [r for r, d in data.items() if d["value"] == "12V DC"][0]
    lay.place(jack, 10.5, 9, 0)
    rest = [r for r in lay.unplaced() if not r.startswith("H")]
    lay.pack(rest, 21.0, 3.0, W - 10.0, gap=2.2, y1=31.0)
    for r, (hx, hy) in zip([r for r in lay.unplaced() if r.startswith("H")],
                           [(4.5, 24.0), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)]):
        lay.place(r, hx, hy)

    # ---------------------------------------------------------------- planes
    lay.zone("GND", pcbnew.In1_Cu, priority=0)
    lay.zone("GND", pcbnew.F_Cu, clearance=0.2, priority=0)
    lay.zone("GND", pcbnew.B_Cu, priority=0)
    lay.zone("+5V_LNA", pcbnew.In2_Cu, priority=0)
    print("unplaced:", lay.unplaced())
    for w in lay.warnings:
        print("WARN", w)
    out = lay.save(os.path.join(HERE, "..", "board_a"))
    print("saved", out, len(lay.fps), "footprints")


if __name__ == "__main__":
    main()
