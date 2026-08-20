#!/usr/bin/env python3
"""Apply the sg13cmos5l_stdcell_hv contribution to an ihp-sg13cmos5l checkout.

Companion to make_pdk_pr.py. That script installs the thick-oxide library
into ihp-sg13g2 (IHP-Open-PDK#1103); this one makes the very same files
usable from the SG13CMOS5L PDK -- without copying any of them.

ihp-sg13cmos5l is a separate repository that is cloned *inside* an
IHP-Open-PDK checkout, next to ihp-sg13g2, and it already shares 200
files with its sibling through relative symlinks: a whole library
(libs.ref/sg13cmos5l_sram -> ../../ihp-sg13g2/libs.ref/sg13g2_sram), the
LVS rule decks, the ngspice/xyce model libraries -- including every
thick-oxide one (cornerMOShv.lib, sg13g2_moshv_mod.lib, psp103.osdi).
Because the HV models are literally the same files, the liberty
characterized for #1103 describes this process module too, and the
library needs no re-characterization to cross over.

Installed (17 symlinks, 3 real files, 1 two-line patch):

  libs.ref/sg13cmos5l_stdcell_hv/
      {gds,lef,spice,cdl,verilog}/sg13cmos5l_stdcell_hv.*     -> G2 views
      lib/sg13cmos5l_stdcell_hv_<corner>.lib  -> one per corner #1103 ships
      {sym,sch,doc}                                            -> G2 dirs
      lef/sg13cmos5l_tech.lef -> ../../sg13cmos5l_stdcell/lef/...
  libs.tech/librelane/sg13cmos5l_stdcell_hv/
      {latch,mux2,mux4,tribuff,sdfbbp}_map.v, *_exclude.cells  -> G2 SCL
      tracks.info                (real: copied from sg13cmos5l_stdcell)
      config.tcl                 (real: ../librelane_cmos5l/config.tcl)
  libs.tech/klayout/tech/pymacros/sg13cmos5l_stdcell_hv.lym    (real)
  libs.tech/xschem/xschemrc                                    (patch)

Per-file rather than per-directory symlinks under libs.ref: LibreLane
derives every view path from $STD_CELL_LIBRARY
(libs.ref/$SCL/gds/$SCL.gds and so on), so the files must carry CMOS5L
names -- which a symlink provides for free. sym/, sch/ and doc/ hold
per-cell files whose names are the cell names, so those are whole
directory links.

Three things must NOT come from G2:
  * lef/sg13cmos5l_tech.lef -- CMOS5L is an M1-M4-TM1 stack (no Metal5,
    Via4, TopMetal2, TopVia2), and its PDK config globs the CMOS5L file
    name; it is linked from the thin-oxide library so the two SCLs can
    never diverge in layer definitions;
  * tracks.info -- the CMOS5L routing grid differs (M1 X 0.42 vs 0.48,
    M3 X 0.42, TM1 2.28 vs 3.28);
  * config.tcl -- see librelane_cmos5l/config.tcl.

Cell names keep the sg13g2_hv_ prefix. sg13cmos5l_stdcell renames its
cells (scripts/rename_cells.py, sg13g2_ -> sg13cmos5l_), but renaming
here would fork 3.5 MB of views away from their single source of truth;
sg13cmos5l_sram keeps its RM_IHPSG13_* names for the same reason. Raised
as a maintainer question in the PR.

Usage: python3 make_cmos5l_pr.py --pdk <IHP-Open-PDK checkout root>
       (the root that contains BOTH ihp-sg13g2 -- with #1103 applied --
        and ihp-sg13cmos5l)
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

HV = pathlib.Path(__file__).resolve().parent.parent
G2 = "sg13g2_stdcell_hv"
C5 = "sg13cmos5l_stdcell_hv"
# Liberty corners are discovered, not listed: #1103 grew from one corner to
# three (typ 3.30 V, fast 3.60 V/-40 C, slow 3.00 V/125 C) after this port
# was first written, and a hard-coded name silently ships a subset.
CORNER_RE = re.compile(rf"^{G2}_(.*)\.lib$")

# (path inside ihp-sg13cmos5l, symlink target relative to that path's dir)
VIEW_FILES = [
    (f"libs.ref/{C5}/gds/{C5}.gds", f"gds/{G2}.gds"),
    (f"libs.ref/{C5}/lef/{C5}.lef", f"lef/{G2}.lef"),
    (f"libs.ref/{C5}/spice/{C5}.spice", f"spice/{G2}.spice"),
    (f"libs.ref/{C5}/cdl/{C5}.cdl", f"cdl/{G2}.cdl"),
    (f"libs.ref/{C5}/verilog/{C5}.v", f"verilog/{G2}.v"),
]
VIEW_DIRS = ["sym", "sch", "doc"]
SCL_SHARED = ["latch_map.v", "mux2_map.v", "mux4_map.v", "tribuff_map.v",
              "sdfbbp_map.v", "synth_exclude.cells", "pnr_exclude.cells"]

XSCHEM_ANCHOR = ("append XSCHEM_LIBRARY_PATH "
                 ":${PDK_ROOT}/${PDK}/libs.tech/xschem/sg13cmos5l_pr")
XSCHEM_PATCH = (
    "\n# thick-oxide (3.3 V) standard cells, symlinked from the G2 PDK;\n"
    "# their symbols resolve the schematics through ::SG13G2_HV_SCH\n"
    "append XSCHEM_LIBRARY_PATH "
    ":${PDK_ROOT}/${PDK}/libs.ref/sg13cmos5l_stdcell_hv/sym/xschem\n"
    "set ::SG13G2_HV_SCH "
    "${PDK_ROOT}/${PDK}/libs.ref/sg13cmos5l_stdcell_hv/sch/xschem")


def link(path, target):
    """Create one relative symlink, replacing whatever is there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    os.symlink(target, path)


def corners(pdk):
    """Every Liberty corner #1103 ships, newest set at install time."""
    lib = pdk / "ihp-sg13g2" / "libs.ref" / G2 / "lib"
    out = sorted(m.group(1) for m in
                 (CORNER_RE.match(p.name) for p in lib.glob("*.lib")) if m)
    assert out, f"no {G2}_*.lib found in {lib}"
    return out


def install_libs_ref(pdk, c5):
    """Per-file links for the collective views, directory links for the
    per-cell ones, plus the CMOS5L tech LEF the PDK config expects."""
    for corner in corners(pdk):
        link(c5 / "libs.ref" / C5 / "lib" / f"{C5}_{corner}.lib",
             f"../../../../ihp-sg13g2/libs.ref/{G2}/lib/{G2}_{corner}.lib")
    for rel, tail in VIEW_FILES:
        link(c5 / rel, f"../../../../ihp-sg13g2/libs.ref/{G2}/{tail}")
    for d in VIEW_DIRS:
        link(c5 / "libs.ref" / C5 / d,
             f"../../../ihp-sg13g2/libs.ref/{G2}/{d}")
    link(c5 / "libs.ref" / C5 / "lef" / "sg13cmos5l_tech.lef",
         "../../sg13cmos5l_stdcell/lef/sg13cmos5l_tech.lef")
    print(f"libs.ref/{C5}: {len(VIEW_FILES)} view links, "
          f"{len(corners(pdk))} Liberty links "
          f"({', '.join(corners(pdk))}), "
          f"{len(VIEW_DIRS)} directory links, 1 tech LEF link")


def install_librelane(c5):
    scl = c5 / "libs.tech" / "librelane" / C5
    for name in SCL_SHARED:
        link(scl / name,
             f"../../../../ihp-sg13g2/libs.tech/librelane/{G2}/{name}")
    # The CMOS5L grid, not the G2 one: M1 X 0.42, M3 X 0.42, TM1 2.28,
    # and no Metal5/TopMetal2 rows at all.
    src = (c5 / "libs.tech" / "librelane" / "sg13cmos5l_stdcell" /
           "tracks.info")
    shutil.copy2(src, scl / "tracks.info")
    shutil.copy2(HV / "librelane_cmos5l" / "config.tcl", scl / "config.tcl")
    print(f"libs.tech/librelane/{C5}: {len(SCL_SHARED)} links + "
          f"tracks.info (from sg13cmos5l_stdcell) + config.tcl")


def install_klayout(c5):
    """A real file, not a link: the macro hard-codes the library name and
    resolves the GDS relative to itself, so the G2 copy would look for
    sg13g2_stdcell_hv under ihp-sg13cmos5l/libs.ref and find nothing."""
    src = HV / "klayout" / "pymacros" / f"{G2}.lym"
    text = src.read_text()
    old = ('        candidates.append(os.path.join(here, "..", "..", "gds",\n'
           '                                       LIB_NAME + ".gds"))')
    new = ('        candidates.append(os.path.join(\n'
           '            here, "..", "..", "..", "..", "libs.ref", LIB_NAME,\n'
           '            "gds", LIB_NAME + ".gds"))')
    assert old in text, "GDS candidate block not found in the .lym"
    text = text.replace(old, new)
    text = text.replace(G2, C5).replace("SG13G2_HV_HOME", "SG13CMOS5L_HV_HOME")
    # the G2 macro's prose predates the last cells being drawn
    text = text.replace("all 68 drawn cells", "all 84 cells")
    text = text.replace("68 cells, 7.14 um", "84 cells, 7.14 um")
    text = text.replace("IHP SG13G2 thick-oxide", "IHP SG13CMOS5L thick-oxide")
    text = text.replace("the\n# IHP sg13g2 technology", "the\n# IHP sg13cmos5l technology")
    dst = (c5 / "libs.tech" / "klayout" / "tech" / "pymacros" / f"{C5}.lym")
    dst.write_text(text)
    print(f"klayout: {dst.name} (PDK-relative GDS path, CMOS5L names)")


def patch_xschemrc(c5):
    rc = c5 / "libs.tech" / "xschem" / "xschemrc"
    text = rc.read_text()
    if f"{C5}/sym/xschem" in text:
        print("xschemrc: already patched")
        return
    assert XSCHEM_ANCHOR in text, "sg13cmos5l_pr append not found in xschemrc"
    rc.write_text(text.replace(XSCHEM_ANCHOR, XSCHEM_ANCHOR + XSCHEM_PATCH, 1))
    print("xschemrc: 4 lines added after the sg13cmos5l_pr append")


def verify_links(pdk, c5):
    """Every link must resolve, and must resolve into ihp-sg13g2 or into
    the CMOS5L thin-oxide library -- never to a copy."""
    bad = 0
    links = [p for p in c5.rglob("*") if p.is_symlink()
             and (C5 in str(p) or f"pymacros/{C5}" in str(p))]
    for p in links:
        try:
            real = p.resolve(strict=True)
        except OSError:
            print(f"  FAIL dangling link: {p.relative_to(c5)} -> "
                  f"{os.readlink(p)}")
            bad += 1
            continue
        if not str(real).startswith(str(pdk)):
            print(f"  FAIL link escapes the checkout: {p.relative_to(c5)}")
            bad += 1
        if os.readlink(p).startswith("/"):
            print(f"  FAIL absolute link: {p.relative_to(c5)}")
            bad += 1
    print(f"link resolution: {len(links) - bad}/{len(links)} relative links "
          f"resolve inside the PDK root")
    return bad == 0


def verify_paths(pdk, c5):
    """Every path the LibreLane configs name must exist on disk."""
    scl = c5 / "libs.tech" / "librelane" / C5
    wanted = [
        c5 / "libs.ref" / C5 / "gds" / f"{C5}.gds",
        c5 / "libs.ref" / C5 / "lef" / f"{C5}.lef",
        c5 / "libs.ref" / C5 / "lef" / "sg13cmos5l_tech.lef",
        *[c5 / "libs.ref" / C5 / "lib" / f"{C5}_{c}.lib"
          for c in corners(pdk)],
        c5 / "libs.ref" / C5 / "spice" / f"{C5}.spice",
        c5 / "libs.ref" / C5 / "cdl" / f"{C5}.cdl",
        c5 / "libs.ref" / C5 / "verilog" / f"{C5}.v",
        *[c5 / "libs.ref" / "sg13cmos5l_io" / "lib" / f"sg13cmos5l_io_{c}.lib"
          for c in ("typ_1p5V_3p3V_25C", "fast_1p65V_3p6V_m40C",
                    "slow_1p35V_3p0V_125C")],
        scl / "config.tcl", scl / "tracks.info",
        scl / "latch_map.v", scl / "mux2_map.v", scl / "mux4_map.v",
        scl / "tribuff_map.v", scl / "sdfbbp_map.v",
        scl / "synth_exclude.cells", scl / "pnr_exclude.cells",
    ]
    missing = [p for p in wanted if not p.is_file()]
    for p in missing:
        print(f"  FAIL missing: {p.relative_to(c5)}")
    print(f"config paths: {len(wanted) - len(missing)}/{len(wanted)} present")
    return not missing


def verify_tracked(c5):
    """Fail if anything just installed would be invisible to git.

    Same guard as make_pdk_pr.py -- see its docstring for the *.spice
    incident. This repository's .gitignore carries no such rule, but the
    check is free and the failure mode (a view that every local tool
    reads and no clone receives) is expensive.
    """
    if not (c5 / ".git").exists():
        print("git visibility: not a checkout, skipped")
        return True
    roots = [c5 / "libs.ref" / C5,
             c5 / "libs.tech" / "librelane" / C5,
             c5 / "libs.tech" / "klayout" / "tech" / "pymacros" / f"{C5}.lym"]
    files = []
    for r in roots:
        files += [r] if r.is_file() else [p for p in r.rglob("*")
                                          if p.is_file() or p.is_symlink()]
    rel = [str(p.relative_to(c5)) for p in files]
    r = subprocess.run(["git", "-C", str(c5), "check-ignore", "--stdin",
                        "--no-index"],
                       input="\n".join(rel), capture_output=True, text=True)
    ignored = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if ignored:
        print(f"  FAIL git visibility: {len(ignored)} installed path(s) are "
              f"ignored and would never reach the PR:")
        for f in ignored[:20]:
            print(f"    {f}")
        return False
    print(f"git visibility: all {len(rel)} installed paths are trackable")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", required=True,
                    help="IHP-Open-PDK checkout root containing both "
                         "ihp-sg13g2 (with #1103 applied) and "
                         "ihp-sg13cmos5l")
    args = ap.parse_args()
    pdk = pathlib.Path(args.pdk).resolve()
    c5 = pdk / "ihp-sg13cmos5l"
    assert (c5 / "libs.ref" / "sg13cmos5l_stdcell").is_dir(), \
        f"{c5} is not an ihp-sg13cmos5l checkout"
    assert (pdk / "ihp-sg13g2" / "libs.ref" / G2).is_dir(), \
        (f"{pdk}/ihp-sg13g2/libs.ref/{G2} is missing -- apply "
         f"make_pdk_pr.py (IHP-Open-PDK#1103) first")

    install_libs_ref(pdk, c5)
    install_librelane(c5)
    install_klayout(c5)
    patch_xschemrc(c5)
    ok = verify_links(pdk, c5)
    ok = verify_paths(pdk, c5) and ok
    ok = verify_tracked(c5) and ok

    print("""
Next steps in the checkout (PRs target ihp-sg13cmos5l's *main* branch;
commits need a Developer Certificate of Origin sign-off, git commit -s):
  re-run signoff with the CMOS5L decks: run_drc.py (modular + maximal +
    the CMOS5L forbidden-layer table) on the two work/drc arrays,
    per-cell LVS with libs.tech/klayout/tech/lvs/run_lvs.py, OpenSTA read
    of the liberty, iverilog on the verilog view;
  smoke-test LibreLane with PDK ihp-sg13cmos5l and
    STD_CELL_LIBRARY sg13cmos5l_stdcell_hv, and confirm the SCL config
    wins over the PDK-level VDD_PIN_VOLTAGE of 1.20 V;
  keep the PR a draft until IHP-Open-PDK#1103 merges into dev -- every
    link dangles until then, including in this repo's CI, which clones
    IHP-Open-PDK dev and overlays this checkout onto it.
""")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
