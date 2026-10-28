"""Verify a generated schematic: run KiCad ERC, export KiCad's netlist and compare
it pin-by-pin with the intended netlist (<board>.netlist.json).

    python tools/verify.py board_a
"""
import collections
import json
import os
import subprocess
import sys

from sexp import find, find1, parse

KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def run(board_dir, name):
    sch = os.path.join(board_dir, name + ".kicad_sch")
    erc = os.path.join(board_dir, "erc.json")
    net = os.path.join(board_dir, name + ".net")
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "--severity-all", "-o", erc, sch],
                   check=True, capture_output=True)
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, sch],
                   check=True, capture_output=True)

    # ---- ERC summary
    d = json.load(open(erc))
    counts = collections.Counter()
    examples = {}
    for s in d.get("sheets", []):
        for v in s.get("violations", []):
            k = (v["severity"], v["type"])
            counts[k] += 1
            examples.setdefault(k, v["description"] + " | " +
                                "; ".join(i.get("description", "") for i in v.get("items", [])[:2]))
    print(f"ERC: {sum(counts.values())} violations")
    for k, n in counts.most_common():
        print(f"  {n:4d} {k[0]:<8} {k[1]:<24} e.g. {examples[k][:160]}")

    # ---- netlist comparison
    kn = parse(open(net, encoding="utf-8").read())
    got = {}
    for n in find(find1(kn, "nets"), "net"):
        nm = find1(n, "name")[1].lstrip("/")
        for node in find(n, "node"):
            ref, pin = find1(node, "ref")[1], find1(node, "pin")[1]
            if ref.startswith("#"):
                continue
            got[(ref, pin)] = nm
    want = {}
    intent = json.load(open(os.path.join(board_dir, name + ".netlist.json")))
    for ref, p in intent["parts"].items():
        for pin, nm in p["pins"].items():
            want[(ref, pin)] = nm
    missing = [k for k in want if k not in got]
    wrong = [(k, want[k], got[k]) for k in want if k in got and got[k] != want[k]]
    extra = [k for k in got if k not in want and not got[k].startswith("unconnected-")]
    print(f"Netlist: {len(want)} intended pin connections, {len(missing)} missing, {len(wrong)} different, "
          f"{len(extra)} unexpected")
    for x in (missing[:5] + wrong[:5] + extra[:5]):
        print("   ", x)
    errors = sum(n for k, n in counts.items() if k[0] == "error")
    return errors == 0 and not missing and not wrong and not extra


if __name__ == "__main__":
    name = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    ok = run(os.path.join(here, "..", name), name)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
