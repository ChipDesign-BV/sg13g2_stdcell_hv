#!/usr/bin/env python3
"""Assemble the IHP-Open-PDK contribution overlay from this repository.

Builds a directory tree shaped like ihp-sg13g2/ that can be rsync'ed onto a
fresh IHP-Open-PDK checkout:

  libs.ref/sg13g2_stdcell_hv/{cdl,doc,gds,lef,lib,spice,verilog}
  libs.tech/xschem/sg13g2_stdcells_hv/          symbols (+ schematics)
  libs.tech/klayout/tech/pymacros/sg13g2_stdcell_hv.lym

Three deliberate transforms happen on the way -- the repository itself is
the source of truth and stays untouched:

  * The symbols' schematic="tcleval($::SG13G2_HV_SCH/...)" pointer is
    stripped. In the repo, sym/ and sch/ are separate directories and the
    pointer (set up by xschem_lib_sg13g2_stdcell_hv.tcl) bridges them; in
    the PDK the two live in ONE directory, where xschem's default
    same-directory .sym -> .sch resolution works with no tcl at all.
    Without --with-schematics only the symbols ship (the upstream
    sg13g2_stdcells convention) and there is nothing to descend into.

  * The KLayout macro's GDS search gets the PDK-relative candidate
    (tech/pymacros -> ../../../../libs.ref/sg13g2_stdcell_hv/gds/)
    prepended; the SG13G2_HV_HOME override stays.

  * doc/ ships the celllist, ReleaseNotes.txt and the two PDF reports --
    not the work/ scripts, the README or the repo licence files (the PDK's
    top-level Apache-2.0 covers the contribution; attribution lives in
    ReleaseNotes.txt and the per-file headers).

With --with-schematics the overlay is verified the same way the repo is:
the schematics are netlisted through the overlay symbols with xschem and
every cell's device multiset is compared against the SPICE netlist
(verify_sch.py's own machinery, pointed at the overlay directory).

Usage: python3 make_pdk_pr.py [--out DIR] [--with-schematics]
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import verify_sch

HV = pathlib.Path(__file__).resolve().parent.parent
POINTER = re.compile(r'^schematic="tcleval\(\$::SG13G2_HV_SCH/[^"]*\)"\n',
                     re.M)
XSCHEM = "/foss/tools/bin/xschem"

RC = """
set ::env(PDK) ihp-sg13g2
set ::env(PDK_ROOT) /foss/pdks
source /foss/pdks/ihp-sg13g2/libs.tech/xschem/xschemrc
append XSCHEM_LIBRARY_PATH :{overlay}
set netlist_dir {out}
""".strip()


def copy_libs_ref(out):
    ref = out / "libs.ref" / "sg13g2_stdcell_hv"
    for d in ("cdl", "gds", "lef", "lib", "spice", "verilog"):
        shutil.copytree(HV / d, ref / d)
    doc = ref / "doc"
    doc.mkdir(parents=True)
    shutil.copy2(HV / "doc" / "sg13g2_stdcell_hv.celllist", doc)
    shutil.copy2(HV / "doc" / "ReleaseNotes.txt", doc)
    for pdf in (HV / "doc" / "report").glob("*.pdf"):
        shutil.copy2(pdf, doc)
    return ref


def copy_xschem(out, with_sch):
    xs = out / "libs.tech" / "xschem" / "sg13g2_stdcells_hv"
    xs.mkdir(parents=True)
    stripped = 0
    for sym in sorted((HV / "sym" / "xschem").glob("*.sym")):
        text = sym.read_text()
        text, n = POINTER.subn("", text)
        stripped += n
        (xs / sym.name).write_text(text)
    assert not any("SG13G2_HV_SCH" in (xs / p.name).read_text()
                   for p in (HV / "sym" / "xschem").glob("*.sym")), \
        "schematic pointer survived the strip"
    if with_sch:
        for sch in sorted((HV / "sch" / "xschem").glob("*.sch")):
            shutil.copy2(sch, xs / sch.name)
    print(f"xschem: {stripped} schematic pointers stripped, "
          f"{'symbols + schematics' if with_sch else 'symbols only'}")
    return xs


def copy_klayout(out):
    src = HV / "klayout" / "pymacros" / "sg13g2_stdcell_hv.lym"
    dst = out / "libs.tech" / "klayout" / "tech" / "pymacros" / src.name
    dst.parent.mkdir(parents=True)
    old = ('        candidates.append(os.path.join(here, "..", "..", "gds",\n'
           '                                       LIB_NAME + ".gds"))')
    new = ('        candidates.append(os.path.join(\n'
           '            here, "..", "..", "..", "..", "libs.ref", LIB_NAME,\n'
           '            "gds", LIB_NAME + ".gds"))\n'
           '        candidates.append(os.path.join(here, "..", "..", "gds",\n'
           '                                       LIB_NAME + ".gds"))')
    text = src.read_text()
    assert old in text, "GDS candidate block not found in the .lym"
    dst.write_text(text.replace(old, new))
    print(f"klayout: {dst.relative_to(out)} (PDK-relative GDS path added)")


def verify_overlay(xs):
    """Netlist the schematics through the overlay symbols; compare devices."""
    spice = verify_sch.spice_cells()
    cells = sorted(p.stem for p in xs.glob("sg13g2_hv_*.sch")
                   if p.stem != "sg13g2_hv_stdcells")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pdkoverlay_"))
    (tmp / "xschemrc").write_text(RC.format(overlay=xs, out=tmp))
    (tmp / "all_cells.sch").write_text(verify_sch.wrapper(cells))
    subprocess.run([XSCHEM, "--rcfile", str(tmp / "xschemrc"), "-n", "-q",
                    "--no_x", str(tmp / "all_cells.sch")],
                   cwd=tmp, capture_output=True, text=True, timeout=1800)
    txt = (tmp / "all_cells.spice").read_text()
    bad = 0
    for cell in cells:
        m = re.search(rf"^\.subckt\s+{re.escape(cell)}\s", txt, re.M)
        if not m:
            print(f"  FAIL {cell}: no .subckt emitted")
            bad += 1
            continue
        body = txt[m.end():txt.index(".ends", m.end())]
        if verify_sch.devices(body) != spice[cell][1]:
            print(f"  FAIL {cell}: devices differ from SPICE")
            bad += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"overlay netlist check: {len(cells) - bad}/{len(cells)} cells "
          f"match the SPICE netlist")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HV / "work" / "pdk_overlay"))
    ap.add_argument("--with-schematics", action="store_true")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    ref = copy_libs_ref(out)
    xs = copy_xschem(out, args.with_schematics)
    copy_klayout(out)
    n = sum(1 for _ in out.rglob("*") if _.is_file())
    print(f"overlay: {n} files under {out}")

    ok = True
    if args.with_schematics:
        ok = verify_overlay(xs)

    print(f"""
Next steps (in a fresh IHP-Open-PDK clone; check CONTRIBUTING.md and
whether PRs target main or dev):
  rsync -a {out}/ <clone>/ihp-sg13g2/
  register sg13g2_stdcells_hv in ihp-sg13g2/libs.tech/xschem the same way
    sg13g2_stdcells is registered (xschemrc / install.py);
  re-run signoff there: PDK run_drc.py on the two work/drc arrays, LVS,
    OpenSTA read of {ref.relative_to(out)}/lib, iverilog with the PDK's
    sg13g2_udp.v;
  open the PR as a draft; flag the cell-set choice (view_matrix.py),
    schematics yes/no, and the pymacros placement as maintainer questions.
""")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
