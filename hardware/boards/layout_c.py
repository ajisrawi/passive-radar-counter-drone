"""Board C placement (run with KiCad Python). 8 layers, 135 x 120 mm.

Stack-up (JLC 8-layer 1.6 mm): L1 signal/components, L2 GND, L3 signal (DDR), L4 power,
L5 GND, L6 signal, L7 power, L8 signal/decoupling. Zynq in the middle, DDR3L to its right
with end termination beyond it, power along the top, I/O on the left edge, FMC carrier
connector on the bottom edge (board B stacks above on 10 mm standoffs).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import pcbnew  # noqa: E402
from pcbgen import Layout  # noqa: E402

S = 1.5                      # board scale vs. the original 145 x 125 mm layout
W, H = round(145.0 * S, 1), round(125.0 * S, 1)
ZX, ZY = 68.0 * S, 55.0 * S  # Zynq
DX, DY = ZX + 30.0, ZY       # DDR3L stays 30 mm from the Zynq (short, matched DDR traces)
G = 1.0                      # extra packing gap for routing room


def main():
    lay = Layout("board_c", os.path.join(HERE, "..", "board_c", "board_c.netlist.json"), layers=8,
                 rules={"track": 0.1, "clearance": 0.1, "via": 0.45, "drill": 0.2})
    lay.outline(W, H)
    data = lay.data
    placed = lambda: getattr(lay, "placed", set())  # noqa: E731
    sheet = lambda name: [r for r, d in data.items() if d["sheet"] == name and r not in placed()]  # noqa: E731

    # ---- edge connectors first (openings face out of the board)
    by_val = {d["value"]: r for r, d in data.items()}
    lay.place(by_val["HR911130C"], 12.0, 92.0 * S, 90)      # RJ45 opening faces left edge
    lay.place(by_val["USB-C console"], 4.0, 64.0 * S, 270)  # USB-C opening faces left edge
    lay.place(by_val["microSD"], 34.0 * S, H - 9.9, 0)      # card slot at the bottom edge
    lay.place(by_val["12V DC"], 10.5, 10.0, 0)              # barrel opening faces left edge

    # ---- anchors
    lay.place("U1", ZX, ZY)
    lay.place("U2", DX, DY, 90)
    lay.place("J1", 78.0 * S, H - 11.0, 0)  # FMC carrier, top side, bottom edge

    # ---- Zynq power/config: 0402 decoupling under the BGA (bottom), bulk + config around it
    zp = sheet("zynq_power")
    small = [r for r in zp if data[r]["value"] in ("100n", "10n", "470n") and r.startswith("C")]
    lay.pack(small, ZX - 10.5, ZY - 10.5, ZX + 10.5, gap=0.3, back=True, y1=ZY + 14.0)
    zp = sheet("zynq_power")
    jtag = [r for r in zp if data[r]["value"].startswith("JTAG")]
    lay.place(jtag[0], W - 17.0, H - 26.0, 90)
    lay.pack([r for r in sheet("zynq_power")], ZX - 24.0, ZY + 16.0, ZX + 24.0, gap=G, y1=ZY + 48.0)

    # ---- DDR3L: decoupling under the DRAM (bottom), terminations to the right
    dd = sheet("ddr3")
    ddec = [r for r in dd if data[r]["value"] in ("100n",) and "+1V35" in data[r]["pins"].values()]
    lay.pack(ddec, DX - 7.5, DY - 5.0, DX + 7.5, gap=0.3, back=True, y1=DY + 8.0)
    lay.pack(sheet("ddr3"), DX + 10.0, DY - 30.0, W - 4.0, gap=0.6, y1=DY + 40.0)

    # ---- power band along the top
    holes = [r for r in sheet("power") if r.startswith("H")]
    for r, (hx, hy) in zip(holes, [(4.5, 24.0), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)]):
        lay.place(r, hx, hy)
    lay.pack(sheet("power"), 20.0, 3.0, W - 10.0, gap=G + 0.5, y1=27.5 * S)

    # ---- left edge: USB console (top), Ethernet (below)
    lay.pack(sheet("zynq_ps"), 12.0, 29.0 * S + 2, 50.0 * S, gap=G, y1=78.0 * S)
    lay.pack(sheet("ethernet"), 25.0, 79.0 * S + 2, 52.0 * S, gap=G, y1=H - 22.0)

    # ---- GNSS bottom right, FMC passives near the connector
    lay.pack(sheet("gnss"), 108.0 * S, 88.0 * S, W - 26.0, gap=G, y1=H - 30.0)
    lay.pack(sheet("fmc"), 52.0 * S, 90.0 * S, 104.0 * S, gap=G, y1=H - 20.0)
    left = lay.unplaced()
    if left:
        lay.pack(left, 108.0 * S, 88.0 * S, W - 26.0, gap=G)

    # ---- planes
    for layer in (pcbnew.In1_Cu, pcbnew.In4_Cu):
        lay.zone("GND", layer)
    lay.zone("+3V3", pcbnew.In3_Cu)
    lay.zone("+1V0", pcbnew.In6_Cu)
    lay.zone("GND", pcbnew.F_Cu, clearance=0.2)
    lay.zone("GND", pcbnew.B_Cu, clearance=0.2)
    print("unplaced:", lay.unplaced())
    for w in lay.warnings:
        print("WARN", w)
    print("saved", lay.save(os.path.join(HERE, "..", "board_c")))


if __name__ == "__main__":
    main()
