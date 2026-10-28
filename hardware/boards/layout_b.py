"""Board B placement (run with KiCad Python). 8 layers, 150 x 105 mm FMC mezzanine (non-standard width).

Stack-up (JLC 8-layer 1.6 mm): L1 RF + components, L2 GND, L3 LVDS/signal, L4 GND,
L5 power (1.3 V islands), L6 signal, L7 GND, L8 components (FMC connector, decoupling).
FMC connector on the bottom (L8) facing the carrier. RF inputs along the top edge.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import pcbnew  # noqa: E402
from pcbgen import Layout  # noqa: E402

W, H = 150.0, 105.0
CHIP_X = {1: 30.0, 2: 75.0, 3: 120.0}
CHIP_Y = 40.0


def nets_of(lay, ref):
    return set(lay.data[ref]["pins"].values())


def main():
    lay = Layout("board_b", os.path.join(HERE, "..", "board_b", "board_b.netlist.json"), layers=8,
                 rules={"track": 0.1, "clearance": 0.1, "via": 0.45, "drill": 0.2})
    lay.outline(W, H)
    data = lay.data
    placed = lambda: getattr(lay, "placed", set())  # noqa: E731

    # RF inputs: SMA along the top edge, then pad -> balun -> AC caps toward the chip
    for ch in range(6):
        chip = ch // 2 + 1
        x = CHIP_X[chip] + (-8.0 if ch % 2 == 0 else 8.0)
        sma = [r for r, d in data.items() if d["pins"].get("5") == f"CH{ch}_IN"][0]
        lay.place(sma, x, 6.0)
        grp = [r for r in data if r not in placed() and any(n.startswith(f"CH{ch}_") for n in nets_of(lay, r))
               and not r.startswith("U")]
        lay.pack(grp, x - 6.0, 11.0, x + 6.0, gap=0.4, y1=25.0)

    # AD9361s and their satellites (rails, RBIAS, SYNC, ENB pull-ups, decoupling)
    for chip, x in CHIP_X.items():
        u = f"U{chip}"
        lay.place(u, x, CHIP_Y)
        mine = [r for r in data if r not in placed() and r != u and
                any(n.startswith(f"AD{chip}_") for n in nets_of(lay, r)) and len(data[r]["pins"]) <= 3]
        # decoupling for this chip's rails goes on the bottom side under/around the BGA
        dec = [r for r in mine if data[r]["value"] in ("100n", "1u") and "GND" in nets_of(lay, r)]
        other = [r for r in mine if r not in dec]
        lay.pack(dec, x - 9.0, CHIP_Y - 9.0, x + 9.0, gap=0.35, back=True, y1=CHIP_Y + 9.0)
        lay.pack(other, x - 16.0, CHIP_Y + 8.0, x + 16.0, gap=0.4, y1=CHIP_Y + 18.0)

    # clock distribution between the chips (centre), symmetric to the three XTALN pins
    clk = [r for r in data if r not in placed() and r != "J1" and
           (nets_of(lay, r) & {"TCXO_OUT", "TCXO_VC", "REF_SEL", "EXT_REF", "+2V5_CLK", "CLK_Y0", "CLK_Y1",
                                "CLK_Y2", "CLK_Y3", "FPGA_REFCLK"} or any(n.endswith(("_CK_A", "_CK_B")) for n in nets_of(lay, r)))]
    lay.pack(clk, 50.0, 58.0, 100.0, gap=0.5, y1=100.0)

    # FMC connector on the bottom, centred, near the lower edge
    lay.place("J1", 75.0, 90.0, 0, back=True)

    # power: buck + LDOs + bulk
    pwr = [r for r in data if r not in placed() and not r.startswith(("H", "J1"))]
    lay.pack(pwr, 6.0, 58.0, 48.0, gap=0.5, y1=100.0)
    rest = [r for r in data if r not in placed() and not r.startswith("H")]
    lay.pack(rest, 102.0, 58.0, 144.0, gap=0.5, y1=100.0)
    for r, (hx, hy) in zip([r for r in data if r.startswith("H")],
                           [(4.5, 4.5), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)]):
        lay.place(r, hx, hy)

    # planes
    for layer in (pcbnew.In1_Cu, pcbnew.In3_Cu, pcbnew.In6_Cu):
        lay.zone("GND", layer)
    lay.zone("GND", pcbnew.F_Cu, clearance=0.2)
    lay.zone("GND", pcbnew.B_Cu, clearance=0.2)
    lay.zone("+1V8", pcbnew.In4_Cu)
    print("unplaced:", lay.unplaced())
    for w in lay.warnings:
        print("WARN", w)
    print("saved", lay.save(os.path.join(HERE, "..", "board_b")))


if __name__ == "__main__":
    main()
