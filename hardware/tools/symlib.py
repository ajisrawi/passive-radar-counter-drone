"""Symbol library access: EasyEDA-derived library + KiCad bundled libraries."""
import os
from sexp import parse, find, find1, prop

KICAD_SYM_DIR = r"C:\Program Files\KiCad\10.0\share\kicad\symbols"
HERE = os.path.dirname(os.path.abspath(__file__))
PRC_LIB = os.path.join(HERE, "..", "lib", "prc.kicad_sym")

_cache = {}


def _load(path):
    if path not in _cache:
        lib = parse(open(path, encoding="utf-8").read())
        _cache[path] = {s[1]: s for s in find(lib, "symbol")}
    return _cache[path]


def get_symbol(lib_id):
    """lib_id 'prc:NAME' or 'Lib:NAME' -> (symbol s-expr with 'extends' resolved, lib path)."""
    lib, name = lib_id.split(":", 1)
    path = PRC_LIB if lib == "prc" else os.path.join(KICAD_SYM_DIR, lib + ".kicad_sym")
    syms = _load(path)
    s = syms[name]
    if lib == "prc":
        s = _unspecified_to_passive(s)
    ext = find1(s, "extends")
    if ext:
        base = syms[ext[1]]
        merged = [s[0], s[1]] + [c for c in base[2:] if not (isinstance(c, list) and c and c[0] == "property")]
        props = {p[1]: p for p in find(base, "property")}
        props.update({p[1]: p for p in find(s, "property")})
        merged += list(props.values())
        # rename base unit sub-symbols to this name
        out = []
        for c in merged:
            if isinstance(c, list) and c and c[0] == "symbol" and isinstance(c[1], str) and c[1].startswith(base[1] + "_"):
                c = [c[0], name + c[1][len(base[1]):]] + c[2:]
            out.append(c)
        s = out
    return s


def _unspecified_to_passive(node):
    """EasyEDA symbols mark most pins 'unspecified'; treat them as passive for ERC."""
    if isinstance(node, list):
        if node and node[0] == "pin" and len(node) > 1 and node[1] == "unspecified":
            node = [node[0], type(node[1])("passive")] + node[2:]
        return [_unspecified_to_passive(c) for c in node]
    return node


def by_lcsc(lcsc):
    for name, s in _load(PRC_LIB).items():
        if prop(s, "LCSC Part") == lcsc:
            return "prc:" + name
    return None


def pins(sym):
    """List of dicts: number, name, unit, x, y, rot, length, etype."""
    out = []
    for sub in find(sym, "symbol"):
        parts = sub[1].rsplit("_", 2)
        unit = int(parts[-2]) if len(parts) >= 3 and parts[-2].isdigit() else 0
        for p in find(sub, "pin"):
            at = find1(p, "at")
            ln = find1(p, "length")
            out.append({
                "number": find1(p, "number")[1], "name": find1(p, "name")[1], "unit": unit,
                "x": float(at[1]), "y": float(at[2]), "rot": float(at[3]) if len(at) > 3 else 0.0,
                "length": float(ln[1]) if ln else 2.54, "etype": str(p[1]),
            })
    return out


def unit_count(sym):
    units = {p["unit"] for p in pins(sym)}
    units.discard(0)
    return max(units) if units else 1
