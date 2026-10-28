"""Write a KiCad 8 format (20240108) copy of a KiCad 10 .kicad_pcb, for importers
(e.g. EasyEDA Pro) that do not read the newer format.

Changes: version tag, KiCad 8 layer numbering, numbered net table (KiCad 10 stores
net names only), net numbers on pads/vias/tracks/zones, and removal of tokens that
KiCad 8 does not know (embedded_fonts, duplicate_pad_numbers_are_jumpers, the v9
via tenting/plugging setup block, plot settings).

    python tools/pcb_to_v8.py board_a/board_a.kicad_pcb board_a/easyeda/board_a.kicad_pcb
"""
import sys

from sexp import Sym, dumps, find1, parse

V8_USER_LAYERS = {
    "B.Adhes": 32, "F.Adhes": 33, "B.Paste": 34, "F.Paste": 35, "B.SilkS": 36, "F.SilkS": 37, "B.Mask": 38,
    "F.Mask": 39, "Dwgs.User": 40, "Cmts.User": 41, "Eco1.User": 42, "Eco2.User": 43, "Edge.Cuts": 44,
    "Margin": 45, "B.CrtYd": 46, "F.CrtYd": 47, "B.Fab": 48, "F.Fab": 49,
}
for i in range(1, 10):
    V8_USER_LAYERS[f"User.{i}"] = 49 + i
DROP = {"embedded_fonts", "duplicate_pad_numbers_are_jumpers", "tenting", "covering", "plugging", "capping",
        "filling", "pcbplotparams", "embedded_files", "component_classes", "variants"}


def convert(src, dst):
    b = parse(open(src, encoding="utf-8").read())
    names = set()

    def collect(n):
        if isinstance(n, list):
            if n and n[0] == "net" and len(n) >= 2 and isinstance(n[1], str) and not isinstance(n[1], Sym):
                names.add(n[1])
            for c in n:
                collect(c)
    collect(b)
    order = [""] + sorted(x for x in names if x)
    num = {n: i for i, n in enumerate(order)}

    def fix(n, parent=None):
        if not isinstance(n, list):
            return n
        if n and n[0] in DROP:
            return None
        head = n[0] if n else None
        if head == "net" and len(n) == 2 and isinstance(n[1], str) and not isinstance(n[1], Sym):
            name = n[1]
            if parent == "pad":
                return [Sym("net"), num[name], name]
            return [Sym("net"), num[name]]
        out = [head] if n else []
        for c in n[1:]:
            r = fix(c, head)
            if r is not None:
                out.append(r)
        if head == "zone":  # KiCad 8 zones carry (net N) and (net_name "...")
            netn = [c for c in n if isinstance(c, list) and c and c[0] == "net"]
            if netn:
                i = out.index([Sym("net"), num[netn[0][1]]])
                out.insert(i + 1, [Sym("net_name"), netn[0][1]])
        return out

    body = []
    for c in b[1:]:
        if isinstance(c, list) and c and c[0] == "version":
            body.append([Sym("version"), Sym("20240108")])
        elif isinstance(c, list) and c and c[0] == "generator_version":
            body.append([Sym("generator_version"), "8.0"])
        elif isinstance(c, list) and c and c[0] == "layers":
            lay = [Sym("layers")]
            cu = [x for x in c[1:] if x[1].endswith(".Cu")]
            inner = [x for x in cu if x[1].startswith("In")]
            lay.append([Sym(0), "F.Cu", Sym("signal")])
            for x in sorted(inner, key=lambda x: int(x[1][2:-3])):
                lay.append([Sym(int(x[1][2:-3])), x[1], Sym(str(x[2]))])
            lay.append([Sym(31), "B.Cu", Sym("signal")])
            for x in c[1:]:
                if x[1] in V8_USER_LAYERS:
                    lay.append([Sym(V8_USER_LAYERS[x[1]])] + x[1:])
            body.append(lay)
        elif isinstance(c, list) and c and c[0] == "setup":
            body.append(fix(c))
            body.extend([[Sym("net"), i, nm] for i, nm in enumerate(order)])
        else:
            r = fix(c)
            if r is not None:
                body.append(r)
    out = [Sym("kicad_pcb")] + body
    with open(dst, "w", encoding="utf-8") as f:
        f.write(dumps(out) + "\n")
    return len(order) - 1


if __name__ == "__main__":
    n = convert(sys.argv[1], sys.argv[2])
    print(f"wrote {sys.argv[2]} (KiCad 8 format, {n} nets)")
