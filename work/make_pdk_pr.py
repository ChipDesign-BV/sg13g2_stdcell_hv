#!/usr/bin/env python3
"""Apply the sg13g2_stdcell_hv contribution to an IHP-Open-PDK checkout.

Targets the *dev* branch conventions (the branch IHP pull requests merge
into). dev keeps every standard-cell view under libs.ref -- commits
1c0757e0 / c90378d8 moved the xschem symbols and schematics INTO
libs.ref/sg13g2_stdcell/{sym,sch}/xschem, which is exactly this
repository's layout -- so the library drops in unchanged:

  libs.ref/sg13g2_stdcell_hv/{cdl,doc,gds,lef,lib,spice,verilog,sym,sch}
  libs.tech/librelane/sg13g2_stdcell_hv/                 (LibreLane SCL)
  libs.tech/klayout/tech/pymacros/sg13g2_stdcell_hv.lym
  libs.tech/xschem/xschemrc                              (2-line patch)
  libs.tech/librelane/config.tcl                         (HV corner block)

LibreLane support (added for PR #1103 rev. 2 after Simon Dorrer's smoke
test) is four pieces:
  * the SCL directory (site CoreSiteHV 0.48 x 7.14, HV cell maps, tracks,
    exclude lists, and sdfbbp_map.v -- the flip-flop techmap designs must
    reference via SYNTH_EXTRA_MAPPING_FILE, which LibreLane does not let
    a PDK set);
  * a conditional block in the PDK-level librelane/config.tcl -- the LIB
    dict, corner list and core voltage there hardcode the thin-oxide
    1.2 V liberty filenames, and LibreLane validates the LIB paths
    eagerly, so an HV run needs them overridden at the source;
  * a copy of the thin-oxide tech LEF into the HV lib's lef/ dir (the
    PDK config globs libs.ref/$STD_CELL_LIBRARY/lef/sg13g2_tech.lef and
    a missing file is a hard Tcl error);
  * the installed liberty is stripped to the cells that have a LEF macro
    (finalize_lib.strip_layoutless): the characterization data for the
    not-yet-drawn flops stays in this repo, but the PDK must not
    advertise timing for cells that cannot be placed.

The symbols keep their schematic="tcleval($::SG13G2_HV_SCH/...)" pointer.
Upstream's own stdcell symbols resolve schematics through the
hierarchy_config proc, which is hard-wired to the thin-oxide sch
directory; rather than generalize that proc (a maintainer decision), the
xschemrc patch defines ::SG13G2_HV_SCH next to the mirrored
XSCHEM_LIBRARY_PATH append -- two added lines, no existing line touched,
idempotent.

The KLayout macro gets the PDK-relative GDS candidate prepended
(tech/pymacros -> ../../../../libs.ref/sg13g2_stdcell_hv/gds/); upstream
registers no stdcell GDS as a KLayout library today, so the macro is
flagged as a maintainer question in the PR.

doc/ ships the celllist, ReleaseNotes.txt and the two PDF reports -- not
work/, the README or the repo licence files (the PDK's top-level
Apache-2.0 covers the contribution; attribution lives in ReleaseNotes.txt
and per-file headers).

After applying, the schematics are netlisted through the installed
symbols with xschem USING THE CHECKOUT'S OWN (patched) xschemrc, and
every cell's device multiset is compared against the SPICE netlist --
the same gate verify_sch.py runs against this repository.

Usage: python3 make_pdk_pr.py --pdk <IHP-Open-PDK checkout root>
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import finalize_lib
import verify_sch

HV = pathlib.Path(__file__).resolve().parent.parent
XSCHEM = "/foss/tools/bin/xschem"
LIB_NAME = "sg13g2_stdcell_hv_typ_3p30V_25C.lib"

ANCHOR_LL = 'set ::env(DEFAULT_CORNER) "nom_typ_1p20V_25C"'
PATCH_LL = '''

# Thick-oxide (3.3 V) standard-cell library: one characterized corner so
# far. Overrides the thin-oxide LIB dict / corner list / core voltage
# above (LibreLane validates every LIB path eagerly, so the thin-oxide
# entries must not survive into an HV run).
if { $::env(STD_CELL_LIBRARY) eq "sg13g2_stdcell_hv" } {
    set ::env(VDD_PIN_VOLTAGE) "3.30"
    set ::env(LIB) [dict create]
    dict set ::env(LIB) "*_typ_3p30V_25C" "\\
        $::env(PDK_ROOT)/$::env(PDK)/libs.ref/sg13g2_stdcell_hv/lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib\\
        $::env(PDK_ROOT)/$::env(PDK)/libs.ref/sg13g2_io/lib/sg13g2_io_typ_1p5V_3p3V_25C.lib\\
    "
    set ::env(STA_CORNERS) "nom_typ_3p30V_25C"
    set ::env(DEFAULT_CORNER) "nom_typ_3p30V_25C"
}'''

ANCHOR = ("append XSCHEM_LIBRARY_PATH "
          ":${PDK_ROOT}/${PDK}/libs.ref/sg13g2_stdcell/sym/xschem")
PATCH = (
    "append XSCHEM_LIBRARY_PATH "
    ":${PDK_ROOT}/${PDK}/libs.ref/sg13g2_stdcell_hv/sym/xschem\n"
    "# thick-oxide stdcell symbols resolve their schematics through this\n"
    "set ::SG13G2_HV_SCH "
    "${PDK_ROOT}/${PDK}/libs.ref/sg13g2_stdcell_hv/sch/xschem\n")


def copy_libs_ref(pdk):
    ref = pdk / "ihp-sg13g2" / "libs.ref" / "sg13g2_stdcell_hv"
    if ref.exists():
        shutil.rmtree(ref)
    for d in ("cdl", "gds", "lef", "lib", "spice", "verilog", "sym", "sch"):
        shutil.copytree(HV / d, ref / d)
    doc = ref / "doc"
    doc.mkdir(parents=True)
    shutil.copy2(HV / "doc" / "sg13g2_stdcell_hv.celllist", doc)
    shutil.copy2(HV / "doc" / "ReleaseNotes.txt", doc)
    for pdf in (HV / "doc" / "report").glob("*.pdf"):
        shutil.copy2(pdf, doc)
    n = sum(1 for p in ref.rglob("*") if p.is_file())
    print(f"libs.ref/sg13g2_stdcell_hv: {n} files")
    return ref


def copy_tech_lef(pdk, ref):
    """The PDK-level librelane config globs
    libs.ref/$STD_CELL_LIBRARY/lef/sg13g2_tech.lef; Tcl glob errors on no
    match. Copy the checkout's own thin-oxide tech LEF so the two SCLs
    can never diverge in layer definitions."""
    src = (pdk / "ihp-sg13g2" / "libs.ref" / "sg13g2_stdcell" / "lef" /
           "sg13g2_tech.lef")
    shutil.copy2(src, ref / "lef" / "sg13g2_tech.lef")
    print("lef/sg13g2_tech.lef: copied from sg13g2_stdcell")


def copy_librelane(pdk):
    dst = (pdk / "ihp-sg13g2" / "libs.tech" / "librelane" /
           "sg13g2_stdcell_hv")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(HV / "librelane", dst)
    n = sum(1 for p in dst.iterdir())
    print(f"libs.tech/librelane/sg13g2_stdcell_hv: {n} files")


def patch_librelane_config(pdk):
    cfg = pdk / "ihp-sg13g2" / "libs.tech" / "librelane" / "config.tcl"
    text = cfg.read_text()
    if "sg13g2_stdcell_hv" in text:
        print("librelane config.tcl: already patched")
        return
    assert ANCHOR_LL in text, "DEFAULT_CORNER line not found in config.tcl"
    cfg.write_text(text.replace(ANCHOR_LL, ANCHOR_LL + PATCH_LL, 1))
    print("librelane config.tcl: HV corner block added after DEFAULT_CORNER")


def patch_xschemrc(pdk):
    rc = pdk / "ihp-sg13g2" / "libs.tech" / "xschem" / "xschemrc"
    text = rc.read_text()
    if "sg13g2_stdcell_hv/sym/xschem" in text:
        print("xschemrc: already patched")
        return rc
    assert ANCHOR in text, "thin-oxide sym append not found in xschemrc"
    text = text.replace(ANCHOR, ANCHOR + "\n" + PATCH.rstrip(), 1)
    rc.write_text(text)
    print("xschemrc: 3 lines added after the thin-oxide sym append")
    return rc


def copy_klayout(pdk):
    src = HV / "klayout" / "pymacros" / "sg13g2_stdcell_hv.lym"
    dst = (pdk / "ihp-sg13g2" / "libs.tech" / "klayout" / "tech" /
           "pymacros" / src.name)
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
    print(f"klayout: {dst.name} (PDK-relative GDS path prepended)")


def verify_install(pdk):
    """Netlist all schematics through the installed symbols, with the
    checkout's own xschemrc, and compare devices against SPICE."""
    spice = verify_sch.spice_cells()
    sch_dir = (pdk / "ihp-sg13g2" / "libs.ref" / "sg13g2_stdcell_hv" /
               "sch" / "xschem")
    cells = sorted(p.stem for p in sch_dir.glob("sg13g2_hv_*.sch")
                   if p.stem != "sg13g2_hv_stdcells")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pdkinstall_"))
    (tmp / "xschemrc").write_text(
        f"set ::env(PDK) ihp-sg13g2\n"
        f"set ::env(PDK_ROOT) {pdk}\n"
        f"source {pdk}/ihp-sg13g2/libs.tech/xschem/xschemrc\n"
        f"set netlist_dir {tmp}\n")
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
    print(f"install netlist check (checkout xschemrc): "
          f"{len(cells) - bad}/{len(cells)} cells match the SPICE netlist")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", required=True,
                    help="IHP-Open-PDK checkout root (on the dev branch)")
    args = ap.parse_args()
    pdk = pathlib.Path(args.pdk).resolve()
    assert (pdk / "ihp-sg13g2" / "libs.ref").is_dir(), \
        f"{pdk} is not an IHP-Open-PDK checkout"

    ref = copy_libs_ref(pdk)
    copy_tech_lef(pdk, ref)
    finalize_lib.strip_layoutless(ref / "lib" / LIB_NAME,
                                  ref / "lef" / "sg13g2_stdcell_hv.lef")
    copy_librelane(pdk)
    patch_librelane_config(pdk)
    patch_xschemrc(pdk)
    copy_klayout(pdk)
    ok = verify_install(pdk)

    print("""
Next steps in the checkout (PRs target the dev branch; commits need a
Developer Certificate of Origin sign-off, i.e. git commit -s):
  re-run signoff with the checkout's decks: run_drc.py on the two
    work/drc arrays, per-cell LVS, OpenSTA read of the .lib, iverilog
    against the checkout's sg13g2_udp.v;
  smoke-test LibreLane: STD_CELL_LIBRARY: sg13g2_stdcell_hv plus, at
    design level, SYNTH_EXTRA_MAPPING_FILE:
    pdk_dir::libs.tech/librelane/sg13g2_stdcell_hv/sdfbbp_map.v
    (flip-flops; the variable is not PDK-scoped in LibreLane);
  branch from dev, commit, push to a fork, open the PR as a draft;
  flag as maintainer questions: cell set (view_matrix.py), the KLayout
    macro, hierarchy_config unification, missing qucs-s views, and the
    IO liberty paired with the HV corner (sg13g2_io_typ_1p5V_3p3V_25C is
    the closest existing file; none is characterized for a 3.3 V core).
""")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
