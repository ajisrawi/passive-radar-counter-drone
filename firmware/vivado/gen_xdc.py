"""Generate the PL pin constraints (XDC) for Board C / C2 from the board netlists, so they cannot drift from the PCB.

    python firmware/vivado/gen_xdc.py            -> firmware/vivado/board_c.xdc, board_c2.xdc

For every Zynq ball whose symbol pin is a PL I/O (IO_L.._<bank>, banks other than 500/501/502):
  location from the netlist (ball -> net), I/O standard from the bank's VCCO rail:
    2.5 V: LVDS_25 for _P/_N pairs (DIFF_TERM on the AD9361 -> FPGA inputs), LVCMOS25 otherwise
    3.3 V: LVCMOS33       1.8 V: LVCMOS18
GT reference clock pins (MGTREFCLK*) get a location only. Port names are the net names (lower case).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.abspath(os.path.join(HERE, "..", "..", "hardware"))
sys.path.insert(0, os.path.join(HW, "tools"))
from symlib import get_symbol, pins  # noqa: E402

BOARDS = {
    "board_c": {"symbol": "prc:XC7Z020-1CLG400C", "netlist": "board_c/board_c.netlist.json",
                "vcco": {"0": 3.3, "13": 3.3, "34": 2.5, "35": 2.5}},
    "board_c2": {"symbol": "prc:XC7Z035-2FFG676I", "netlist": "board_c2/board_c2.netlist.json",
                 "vcco": {"0": 3.3, "12": 2.5, "13": 2.5, "33": 1.8, "34": 1.8, "35": 1.8}},
}
# AD9361 -> FPGA LVDS inputs get the internal 100 ohm termination; FB_CLK goes FPGA -> AD9361
INPUT_DIFF = re.compile(r"^AD\d_(DCLK|FRAME|RXD\d)_[PN]$")


def symbol_for(netlist_path, default):
    d = json.load(open(netlist_path))
    for ref, p in d["parts"].items():
        if "XC7Z" in p.get("value", "") or "XC7Z" in p.get("lib_id", ""):
            return ref, p.get("lib_id", default), p["pins"]
    raise RuntimeError("no Zynq in " + netlist_path)


def gen(name, b):
    ref, lib_id, ball_net = symbol_for(os.path.join(HW, b["netlist"]), b["symbol"])
    sym_pins = {p["number"]: p["name"] for p in pins(get_symbol(lib_id))}
    lines = [f"# {name}: PL pins generated from {b['netlist']} by firmware/vivado/gen_xdc.py - do not edit",
             f"# FPGA {ref} = {lib_id}", ""]
    nets = {}
    skipped = []
    for ball, net in sorted(ball_net.items(), key=lambda kv: kv[1] or ""):
        pname = sym_pins.get(ball, "")
        if not net or net.startswith(("GND", "+", "VADJ", "NC")) or net.endswith("_unconnected") or net == "PUDC_B":
            continue                                   # PUDC_B: configuration strap with a resistor, not a port
        m = re.match(r"^IO_.*_(\d+)$", pname)
        if pname.startswith("MGTREFCLK"):
            nets[net] = (ball, None, pname)
            continue
        if not m or m.group(1) in ("500", "501", "502"):
            continue                                   # PS MIO / DDR / config / power: not in the XDC
        bank = m.group(1)
        v = b["vcco"].get(bank)
        if v is None:
            skipped.append((net, ball, pname))
            continue
        nets[net] = (ball, v, pname)
    diff = {n for n in nets if re.search(r"_[PN]$", n) and n[:-1] + ("N" if n.endswith("P") else "P") in nets}
    for net, (ball, v, pname) in sorted(nets.items()):
        port = net.lower()
        lines.append(f"set_property PACKAGE_PIN {ball} [get_ports {{{port}}}]   ;# {pname}")
        if v is None:
            continue
        if net in diff and v == 2.5:
            lines.append(f"set_property IOSTANDARD LVDS_25 [get_ports {{{port}}}]")
            if INPUT_DIFF.match(net):
                lines.append(f"set_property DIFF_TERM TRUE [get_ports {{{port}}}]")
        else:
            std = {3.3: "LVCMOS33", 2.5: "LVCMOS25", 1.8: "LVCMOS18"}[v]
            lines.append(f"set_property IOSTANDARD {std} [get_ports {{{port}}}]")
    lines += ["", "# clocks: AD9361 DATA_CLK (LVDS, up to 245.76 MHz on C2 / 32 MHz on C at 8 MS/s x 4 in 2R2T DDR)",
              *[f"create_clock -name {n.lower()[:-2]} -period 4.069 [get_ports {{{n.lower()}}}]"
                for n in sorted(nets) if re.match(r"^AD\d_DCLK_P$", n)],
              "set_clock_groups -asynchronous -group [get_clocks -include_generated_clocks clk_fpga_0] "
              + " ".join(f"-group [get_clocks -include_generated_clocks {n.lower()[:-2]}]"
                         for n in sorted(nets) if re.match(r"^AD\d_DCLK_P$", n))]
    out = os.path.join(HERE, f"{name}.xdc")
    open(out, "w").write("\n".join(lines) + "\n")
    return {"xdc": os.path.relpath(out, HERE), "pins": len(nets), "lvds_pairs": len(diff) // 2,
            "inputs_with_diff_term": sum(1 for n in diff if INPUT_DIFF.match(n)), "skipped_no_vcco": skipped}


if __name__ == "__main__":
    for name, b in BOARDS.items():
        print(name, gen(name, b))
