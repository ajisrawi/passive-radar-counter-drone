"""Build release outputs for each board into hardware/release/<board>/.

  <board>_schematic.pdf        all sheets
  <board>_BOM_JLCPCB.csv       Comment, Designator, Footprint, LCSC Part #, MPN, Qty (DNP excluded)
  <board>_CPL_JLCPCB.csv       pick-and-place from the current (unrouted) placement
  <board>_top.png / _bottom.png placement renders
  <board>_easyeda_import.zip   KiCad 8-format project (schematics + PCB + libraries) for EasyEDA Pro

    python tools/release.py
"""
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from pcb_to_v8 import convert  # noqa: E402

CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def run(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)


def bom(board, out):
    parts = json.load(open(os.path.join(HW, board, board + ".netlist.json")))["parts"]
    groups = {}
    for ref, p in parts.items():
        if p["dnp"] or p["footprint"].startswith("MountingHole") or p["lib_id"].startswith("Connector:TestPoint"):
            continue
        key = (p["value"], p["footprint"].split(":")[-1], p["lcsc"], p["mpn"])
        groups.setdefault(key, []).append(ref)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "Qty"])
        for (val, fp, lcsc, mpn), refs in sorted(groups.items(), key=lambda kv: (kv[1][0][0], -len(kv[1]))):
            refs.sort(key=lambda r: (r.rstrip("0123456789"), int("".join(c for c in r if c.isdigit()) or 0)))
            w.writerow([val, ",".join(refs), fp, lcsc, mpn, len(refs)])
    return len(groups)


def cpl(board, pcb, out):
    tmp = out + ".kicad.csv"
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", tmp, pcb)
    with open(tmp, encoding="utf-8") as f, open(out, "w", newline="", encoding="utf-8") as g:
        r = csv.DictReader(f)
        w = csv.writer(g)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for row in r:
            w.writerow([row["Ref"], f"{float(row['PosX']):.3f}mm", f"{-float(row['PosY']):.3f}mm",
                        "Top" if row["Side"].lower().startswith("top") else "Bottom", row["Rot"]])
    os.remove(tmp)


def render(pcb, out_png, layers, mirror=False):
    import fitz
    pdf = out_png[:-4] + ".pdf"
    args = ["pcb", "export", "pdf", "--layers", layers, "--mode-single", "-o", pdf, pcb]
    if mirror:
        args.insert(3, "--mirror")
    run(*args)
    d = fitz.open(pdf)
    p = d[0]
    bb = None
    for dr in p.get_drawings():
        bb = dr["rect"] if bb is None else bb | dr["rect"]
    p.get_pixmap(dpi=150, clip=bb).save(out_png)
    d.close()
    os.remove(pdf)


def easyeda_zip(board, out_dir, out_zip):
    stage = os.path.join(out_dir, "_stage", board)
    shutil.rmtree(os.path.join(out_dir, "_stage"), ignore_errors=True)
    os.makedirs(os.path.join(stage, "lib"))
    src = os.path.join(HW, board)
    for f in glob.glob(os.path.join(src, "*.kicad_sch")) + [os.path.join(src, board + ".kicad_pro")]:
        shutil.copy(f, stage)
    convert(os.path.join(src, board + ".kicad_pcb"), os.path.join(stage, board + ".kicad_pcb"))
    shutil.copy(os.path.join(HW, "lib", "prc.kicad_sym"), os.path.join(stage, "lib"))
    shutil.copytree(os.path.join(HW, "lib", "prc.pretty"), os.path.join(stage, "lib", "prc.pretty"))
    with open(os.path.join(stage, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "prc")(type "KiCad")(uri "${KIPRJMOD}/lib/prc.kicad_sym")(options "")(descr ""))\n)\n')
    with open(os.path.join(stage, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "prc")(type "KiCad")(uri "${KIPRJMOD}/lib/prc.pretty")(options "")(descr ""))\n)\n')
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, os.path.dirname(stage)))
    shutil.rmtree(os.path.join(out_dir, "_stage"))


def main():
    for board in ("board_a", "board_b", "board_c"):
        out = os.path.join(HW, "release", board)
        os.makedirs(out, exist_ok=True)
        sch = os.path.join(HW, board, board + ".kicad_sch")
        pcb = os.path.join(HW, board, board + ".kicad_pcb")
        run("sch", "export", "pdf", "-o", os.path.join(out, board + "_schematic.pdf"), sch)
        n = bom(board, os.path.join(out, board + "_BOM_JLCPCB.csv"))
        cpl(board, pcb, os.path.join(out, board + "_CPL_JLCPCB.csv"))
        render(pcb, os.path.join(out, board + "_top.png"), "F.Cu,F.Fab,Edge.Cuts")
        render(pcb, os.path.join(out, board + "_bottom.png"), "B.Cu,B.Fab,Edge.Cuts", mirror=True)
        easyeda_zip(board, out, os.path.join(out, board + "_easyeda_import.zip"))
        print(f"{board}: {n} BOM lines -> {out}")


if __name__ == "__main__":
    main()
