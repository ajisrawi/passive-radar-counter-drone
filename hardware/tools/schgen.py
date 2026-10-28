"""Schematic generator: Python netlist description -> KiCad schematic files.

Connectivity is made with a global label on every connected pin (no wires), and a
no-connect flag on every unconnected pin, so the drawing is the netlist. The
written files use the KiCad 8 format (20231120), which KiCad 8-10 and EasyEDA
Pro's KiCad importer read.

Usage:
    d = Design("board_a")
    sh = d.sheet("rf_channels", "RF channels")
    sh.add(Part("U1", "prc:SPF5043Z", "SPF5043Z", conn={"RF_IN": "CH0_LNA_IN", ...}))
    d.write(out_dir)
"""
import copy
import json
import os
import uuid as _uuid

from sexp import Sym, dumps, find, find1
from symlib import get_symbol, pins as sym_pins

GRID = 2.54
FONT = [Sym("font"), [Sym("size"), 1.27, 1.27]]


def uid():
    return str(_uuid.uuid4())


def snap(v):
    return round(v / GRID) * GRID


class Part:
    def __init__(self, ref, lib_id, value, footprint=None, conn=None, lcsc=None, mpn=None, dnp=False,
                 fields=None, match="auto"):
        """match: 'auto' (pin number first, then name), or 'name' (BGA parts whose
        signal names look like ball numbers, e.g. DDR address A1 vs ball A1)."""
        self.match = match
        self.ref, self.lib_id, self.value = ref, lib_id, value
        self.sym = get_symbol(lib_id)
        self.pins = sym_pins(self.sym)
        self.footprint = footprint or _sym_prop(self.sym, "Footprint") or ""
        self.lcsc = lcsc or _sym_prop(self.sym, "LCSC Part") or ""
        self.mpn = mpn or _sym_prop(self.sym, "MPN") or ""
        self.dnp = dnp
        self.fields = fields or {}
        self.pin_net = {}  # pin number -> net
        for key, net in (conn or {}).items():
            self.connect(key, net)

    def connect(self, key, net):
        key = str(key)
        nums = [] if self.match == "name" else [p["number"] for p in self.pins if p["number"] == key]
        if not nums:
            nums = [p["number"] for p in self.pins if p["name"] == key]
        if not nums:
            raise KeyError(f"{self.ref} ({self.lib_id}): no pin '{key}'")
        if net.startswith("NC_"):
            return  # explicitly unconnected: gets a no-connect flag
        for n in nums:
            if n in self.pin_net and self.pin_net[n] != net:
                raise ValueError(f"{self.ref} pin {n} connected to both {self.pin_net[n]} and {net}")
            self.pin_net[n] = net

    def units(self):
        u = sorted({p["unit"] for p in self.pins})
        return [x for x in u if x != 0] or [1]


def _sym_prop(sym, name):
    for p in find(sym, "property"):
        if p[1] == name:
            return p[2]
    return None


class Sheet:
    def __init__(self, design, fname, title, paper=None):
        self.design, self.fname, self.title, self.paper = design, fname, title, paper
        self.parts = []
        self.uuid = uid()
        self.sheet_sym_uuid = uid()
        self.notes = []

    def add(self, *parts):
        for p in parts:
            p.sheet = self.fname
            self.parts.append(p)
            self.design._register(p)
        return parts[0] if len(parts) == 1 else parts

    def note(self, text):
        self.notes.append(text)


class Design:
    def __init__(self, name, title=""):
        self.name, self.title = name, title
        self.sheets = []
        self.root_uuid = uid()
        self._refs = {}

    def sheet(self, fname, title, paper=None):
        s = Sheet(self, fname, title, paper)
        self.sheets.append(s)
        return s

    def _register(self, p):
        if p.ref in self._refs:
            raise ValueError(f"duplicate reference {p.ref}")
        self._refs[p.ref] = p

    def parts(self):
        return [p for s in self.sheets for p in s.parts]

    def nets(self):
        nets = {}
        for p in self.parts():
            for num, net in p.pin_net.items():
                nets.setdefault(net, []).append((p.ref, num))
        return nets

    # ------------------------------------------------------------------ checks
    def check(self):
        """Basic sanity: nets with a single pin are probably typos."""
        problems = []
        for net, members in self.nets().items():
            if len(members) < 2 and not net.startswith("NC_"):
                problems.append(f"single-pin net {net}: {members}")
        return problems

    # ------------------------------------------------------------------ writing
    def write(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        power_nets = self._power_nets_without_driver()
        for i, s in enumerate(self.sheets):
            self._write_sheet(s, out_dir, page=i + 2)
        self._write_root(out_dir, power_nets)
        self._write_project(out_dir)
        self._write_netlist_json(out_dir)
        return os.path.join(out_dir, self.name + ".kicad_sch")

    def _power_nets_without_driver(self):
        has_in, has_out = set(), set()
        for p in self.parts():
            bynum = {q["number"]: q for q in p.pins}
            for num, net in p.pin_net.items():
                et = bynum[num]["etype"]
                if et == "power_in":
                    has_in.add(net)
                elif et == "power_out":
                    has_out.add(net)
        return sorted(has_in - has_out)

    def _lib_symbols(self, lib_ids):
        out = [Sym("lib_symbols")]
        for lid in sorted(lib_ids):
            s = copy.deepcopy(get_symbol(lid))
            s[1] = lid
            s = _strip_ids(s)
            out.append(s)
        return out

    def _write_sheet(self, sheet, out_dir, page):
        items = []
        lib_ids = {p.lib_id for p in sheet.parts}
        # ---- placement (shelf packing) ----
        blocks = []
        for p in sheet.parts:
            for u in p.units():
                ups = [q for q in p.pins if q["unit"] in (u, 0)]
                xs = [q["x"] for q in ups] or [0]
                ys = [q["y"] for q in ups] or [0]
                lab = max([len(p.pin_net.get(q["number"], "")) for q in ups] + [4]) * 1.0 + 6
                w = (max(xs) - min(xs)) + 2 * lab + 10
                h = (max(ys) - min(ys)) + 14
                blocks.append((p, u, w, h, min(xs), max(ys), lab))
        page_w = max(420.0, min(1600.0, max(b[2] for b in blocks) * 1.05 + 40)) if blocks else 420
        if sum(b[2] * b[3] for b in blocks) > 0:
            page_w = max(page_w, min(1600.0, (sum(b[2] * b[3] for b in blocks) * 1.6) ** 0.5))
        x, y, row_h = 20.0, 30.0, 0.0
        placed = []
        for p, u, w, h, minx, maxy, lab in blocks:
            if x + w > page_w - 10 and x > 20:
                x, y, row_h = 20.0, y + row_h + 8, 0.0
            ox = snap(x + lab + 5 - minx)
            oy = snap(y + 7 + maxy)
            placed.append((p, u, ox, oy))
            x += w + 6
            row_h = max(row_h, h)
        page_h = y + row_h + 30
        # smallest standard ISO landscape sheet that fits (custom "User" sizes are not read by every tool,
        # e.g. OpenSchematic falls back to a small default page and flags parts as outside it)
        need_w, need_h = page_w, max(297.0, page_h)
        iso = [("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
        fit = next((name for name, w, h in iso if w >= need_w and h >= need_h), None)
        paper = [Sym("paper"), fit] if fit else [Sym("paper"), "User", round(need_w), round(need_h)]

        for p, u, ox, oy in placed:
            items.append(self._symbol_instance(p, u, ox, oy, sheet))
            for q in p.pins:
                if q["unit"] not in (u, 0):
                    continue
                px, py = ox + q["x"], oy - q["y"]
                net = p.pin_net.get(q["number"])
                if net is None:
                    if q["etype"] != "no_connect":
                        items.append([Sym("no_connect"), [Sym("at"), px, py], [Sym("uuid"), uid()]])
                    continue
                items.append(_global_label(net, px, py, (q["rot"] + 180) % 360))

        ty = 12
        texts = [_text(f"{sheet.title}", 20, ty, 3.0)]
        for i, n in enumerate(sheet.notes):
            texts.append(_text(n, 20, ty + 6 + i * 4, 1.5))

        doc = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")], [Sym("generator"), "eeschema"],
               [Sym("generator_version"), "8.0"], [Sym("uuid"), sheet.uuid], paper,
               [Sym("title_block"), [Sym("title"), sheet.title], [Sym("company"), "Passive radar receiver"],
                [Sym("comment"), 1, "Generated by hardware/tools/schgen.py - edit the Python source, not this file"]],
               self._lib_symbols(lib_ids)] + texts + items
        with open(os.path.join(out_dir, sheet.fname + ".kicad_sch"), "w", encoding="utf-8") as f:
            f.write(dumps(doc) + "\n")

    def _symbol_instance(self, p, unit, x, y, sheet):
        path = f"/{self.root_uuid}/{sheet.sheet_sym_uuid}"
        ys = [q["y"] for q in p.pins if q["unit"] in (unit, 0)] or [0]
        top, bot = y - max(ys) - 3, y - min(ys) + 3
        if len(p.pins) <= 3:  # small part: labels sit above/below, so put text to the side
            props = [_prop("Reference", p.ref, x + 2.8, y - 1.3, left=True),
                     _prop("Value", p.value, x + 2.8, y + 1.3, left=True)]
        else:
            props = [_prop("Reference", p.ref, x, top), _prop("Value", p.value, x, bot)]
        props += [
            _prop("Footprint", p.footprint, x, bot + 2, hide=True),
            _prop("Datasheet", _sym_prop(p.sym, "Datasheet") or "", x, bot + 4, hide=True),
            _prop("LCSC", p.lcsc, x, bot + 6, hide=True),
            _prop("MPN", p.mpn, x, bot + 8, hide=True),
        ]
        for i, (k, v) in enumerate(p.fields.items()):
            props.append(_prop(k, v, x, bot + 10 + 2 * i, hide=True))
        pins = [[Sym("pin"), q["number"], [Sym("uuid"), uid()]] for q in p.pins if q["unit"] in (unit, 0)]
        return ([Sym("symbol"), [Sym("lib_id"), p.lib_id], [Sym("at"), x, y, 0], [Sym("unit"), unit],
                 [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
                 [Sym("dnp"), Sym("yes" if p.dnp else "no")], [Sym("uuid"), uid()]] + props + pins +
                [[Sym("instances"), [Sym("project"), self.name,
                                     [Sym("path"), path, [Sym("reference"), p.ref], [Sym("unit"), unit]]]]])

    def _write_root(self, out_dir, power_nets):
        items = []
        x, y = 30.0, 40.0
        for i, s in enumerate(self.sheets):
            sx, sy = x + (i % 4) * 90, y + (i // 4) * 50
            items.append([Sym("sheet"), [Sym("at"), sx, sy], [Sym("size"), 70, 30],
                          [Sym("fields_autoplaced"), Sym("yes")],
                          [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]],
                          [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]], [Sym("uuid"), s.sheet_sym_uuid],
                          [Sym("property"), "Sheetname", s.title, [Sym("at"), sx, sy - 0.7, 0],
                           [Sym("effects"), FONT, [Sym("justify"), Sym("left"), Sym("bottom")]]],
                          [Sym("property"), "Sheetfile", s.fname + ".kicad_sch", [Sym("at"), sx, sy + 30.6, 0],
                           [Sym("effects"), FONT, [Sym("justify"), Sym("left"), Sym("top")]]],
                          [Sym("instances"), [Sym("project"), self.name,
                                              [Sym("path"), f"/{self.root_uuid}", [Sym("page"), str(i + 2)]]]]])
        # PWR_FLAGs for power nets that have no power_out pin (keeps ERC meaningful)
        lib = {"power:PWR_FLAG"} if power_nets else set()
        fy = y + ((len(self.sheets) - 1) // 4 + 1) * 50 + 20
        for i, net in enumerate(power_nets):
            fx, fyy = snap(30 + (i % 6) * 60), snap(fy + (i // 6) * 15)
            items.append([Sym("symbol"), [Sym("lib_id"), "power:PWR_FLAG"], [Sym("at"), fx, fyy, 0], [Sym("unit"), 1],
                          [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("no")],
                          [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()],
                          _prop("Reference", f"#FLG{i+1:03d}", fx, fyy - 6, hide=True),
                          _prop("Value", "PWR_FLAG", fx, fyy - 4),
                          _prop("Footprint", "", fx, fyy, hide=True), _prop("Datasheet", "~", fx, fyy, hide=True),
                          [Sym("pin"), "1", [Sym("uuid"), uid()]],
                          [Sym("instances"), [Sym("project"), self.name,
                                              [Sym("path"), f"/{self.root_uuid}", [Sym("reference"), f"#FLG{i+1:03d}"],
                                               [Sym("unit"), 1]]]]])
            items.append(_global_label(net, fx, fyy, 270))
        doc = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")], [Sym("generator"), "eeschema"],
               [Sym("generator_version"), "8.0"], [Sym("uuid"), self.root_uuid], [Sym("paper"), "A3"],
               [Sym("title_block"), [Sym("title"), self.title or self.name]],
               self._lib_symbols(lib), _text(self.title or self.name, 30, 20, 4.0)] + items + \
              [[Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
        with open(os.path.join(out_dir, self.name + ".kicad_sch"), "w", encoding="utf-8") as f:
            f.write(dumps(doc) + "\n")

    def _write_project(self, out_dir):
        rel = os.path.relpath(os.path.join(os.path.dirname(__file__), "..", "lib"), out_dir).replace("\\", "/")
        with open(os.path.join(out_dir, self.name + ".kicad_pro"), "w", encoding="utf-8") as f:
            json.dump({"meta": {"filename": self.name + ".kicad_pro", "version": 1},
                       "sheets": [[self.root_uuid, "Root"]] + [[s.sheet_sym_uuid, s.title] for s in self.sheets]},
                      f, indent=2)
        with open(os.path.join(out_dir, "sym-lib-table"), "w") as f:
            f.write(f'(sym_lib_table\n  (version 7)\n  (lib (name "prc")(type "KiCad")(uri "${{KIPRJMOD}}/{rel}/prc.kicad_sym")(options "")(descr "LCSC/EasyEDA parts"))\n)\n')
        with open(os.path.join(out_dir, "fp-lib-table"), "w") as f:
            f.write(f'(fp_lib_table\n  (version 7)\n  (lib (name "prc")(type "KiCad")(uri "${{KIPRJMOD}}/{rel}/prc.pretty")(options "")(descr "LCSC/EasyEDA footprints"))\n)\n')

    def _write_netlist_json(self, out_dir):
        data = {"parts": {p.ref: {"lib_id": p.lib_id, "value": p.value, "footprint": p.footprint,
                                  "lcsc": p.lcsc, "mpn": p.mpn, "dnp": p.dnp, "sheet": p.sheet,
                                  "pins": p.pin_net}
                          for p in self.parts()}}
        with open(os.path.join(out_dir, self.name + ".netlist.json"), "w") as f:
            json.dump(data, f, indent=1)


def _strip_ids(node):
    if isinstance(node, list):
        if node and node[0] == "property":
            node = [c for c in node if not (isinstance(c, list) and c and c[0] == "id")]
        return [_strip_ids(c) for c in node]
    return node


def _prop(name, value, x, y, hide=False, left=False):
    eff = [Sym("effects"), FONT]
    if left:
        eff.append([Sym("justify"), Sym("left")])
    if hide:
        eff.append([Sym("hide"), Sym("yes")])
    return [Sym("property"), name, value, [Sym("at"), x, y, 0], eff]


def _global_label(net, x, y, angle):
    just = "left" if angle in (0, 90) else "right"
    return [Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), x, y, angle],
            [Sym("fields_autoplaced"), Sym("yes")], [Sym("effects"), FONT, [Sym("justify"), Sym(just)]],
            [Sym("uuid"), uid()],
            [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
             [Sym("effects"), FONT, [Sym("hide"), Sym("yes")]]]]


def _text(s, x, y, size):
    return [Sym("text"), s, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), x, y, 0],
            [Sym("effects"), [Sym("font"), [Sym("size"), size, size]], [Sym("justify"), Sym("left"), Sym("bottom")]],
            [Sym("uuid"), uid()]]
