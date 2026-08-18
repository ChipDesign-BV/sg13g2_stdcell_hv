#!/usr/bin/env python3
"""Sign off a candidate cell layout before it joins the library.

One gate for new or repaired cells (the flop/latch/tri-state layouts the
retarget could not produce are drawn separately and must earn their way
in): LVS against the shipped CDL, DRC in an abutted two-row context
through the PDK's KLayout decks (modular + maximal) and through Magic,
the library's well conventions, and the pin/track report.

Per candidate GDS (top cell named after the library cell):

  1. structure -- boundary (189/4) is 7.140 um tall, width a multiple of
     the 0.48 um site; N-well follows fix_well_nwc1.py's strict-rule
     conventions (0.62 enclosure of PMOS active / spacing to NMOS active
     and p-tap within the cell span, bottom at 2.570 um, overhang 620).
  2. LVS -- PDK run_lvs.py vs cdl/sg13g2_stdcell_hv.cdl (verdict from
     "Netlists match" in the log; the runner's exit code is always 0).
  3. DRC -- the candidate abutted between library cells (inv_1 left,
     nand2_1 right; second row mirrored to share the VDD rail), then the
     PDK KLayout runner (feol/beol/geometry + the maximal extra rules;
     density is chip-level and skipped) and Magic (euclidean, full).
     Magic's Cnt.c and M1.e interpretation differences also flag the
     shipped library cells and are reported but not fatal; NW.* is.
  4. pins -- every Metal1.pin (8/2) shape must carry a Metal1.text
     (8/25) label; report which pins sit on the 0.48/0.42 routing grid
     (the shipped library itself has 11 off-track pins, so off-track is
     a warning, not a failure).

Exit 0 only if every candidate passes LVS, KLayout DRC, Magic NW.*
cleanliness and the structure checks.

Usage: python3 cell_verify.py candidate.gds [more.gds ...]
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import klayout.db as db

HV = pathlib.Path(__file__).resolve().parent.parent
CDL = HV / "cdl" / "sg13g2_stdcell_hv.cdl"
LIB_GDS = HV / "gds" / "sg13g2_stdcell_hv.gds"
PDK = pathlib.Path("/foss/pdks/ihp-sg13g2")
KLAYOUT_BIN = "/foss/tools/klayout"
MAGIC = "/foss/tools/magic/bin/magic"
MAGICRC = PDK / "libs.tech" / "magic" / "ihp-sg13g2.magicrc"

L = dict(act=(1, 0), psd=(14, 0), nw=(31, 0), bnd=(189, 4),
         pin=(8, 2), txt=(8, 25))
ENC, NEW_BOT, H = 620, 2570, 7140
SITE = 480
MAGIC_KNOWN = ("Cnt.c", "M1.e")     # magic-vs-klayout interpretation diffs


def region(cell, layer):
    r = db.Region(cell.begin_shapes_rec(layer))
    r.merge()
    return r


def check_structure(cell, li):
    errs = []
    bnd = region(cell, li["bnd"]).bbox()
    if bnd.height() != H:
        errs.append(f"boundary height {bnd.height()} != {H}")
    if bnd.width() % SITE:
        errs.append(f"width {bnd.width()} not a multiple of {SITE}")
    w = bnd.width()
    well = region(cell, li["nw"])
    act, psd = region(cell, li["act"]), region(cell, li["psd"])
    pact, nact = act & psd, act - psd
    pmos = pact.dup(); pmos.select_inside(well)
    ptap = pact - pmos
    nmos = nact.dup(); nmos.select_outside(well)
    span = db.Region(db.Box(-ENC, 0, w + ENC, well.bbox().top or H))
    if not well.is_empty():
        wb = well.bbox()
        if wb.bottom > NEW_BOT:
            errs.append(f"well bottom {wb.bottom} above {NEW_BOT}")
        if wb.left != -ENC or wb.right != w + ENC:
            errs.append(f"well overhang {wb.left}/{wb.right - w}, want +-{ENC}")
        top_clip = db.Region(db.Box(-ENC, 0, w + ENC, wb.top))
        if not ((pmos.sized(ENC) & top_clip) - well).is_empty():
            errs.append("NW.c1: pmos active not enclosed by 0.62")
        if not (well & nmos.sized(ENC)).is_empty():
            errs.append("NW.d1: well within 0.62 of nmos active")
        if not (well & ptap.sized(ENC)).is_empty():
            errs.append("NW.f1: well within 0.62 of p-tap")
    return errs, bnd


def check_pins(cell, li, ly):
    pins, offtrack = [], []
    texts = [(s.text.string, db.Point(s.text.x, s.text.y))
             for s in cell.shapes(ly.layer(*L["txt"])).each() if s.is_text()]
    for s in cell.shapes(ly.layer(*L["pin"])).each():
        if s.is_text():
            continue
        b = s.dbbox()
        label = next((t for t, p in texts
                      if b.contains(db.DPoint(p.x * ly.dbu, p.y * ly.dbu))),
                     None)
        if label is None:
            return [f"unlabelled pin shape at {b}"], []
        if label in ("VDD", "VSS"):
            continue
        on = any(abs(x - round(x / 0.48) * 0.48) < 1e-6 and b.left <= x <= b.right
                 for x in [round(b.left / 0.48) * 0.48,
                           round(b.right / 0.48) * 0.48,
                           round(b.center().x / 0.48) * 0.48])
        pins.append(label)
        if not on:
            offtrack.append(label)
    return [], sorted(set(offtrack))


def build_context(cand_gds, name, out):
    ly = db.Layout()
    ly.read(str(LIB_GDS))
    opts = db.LoadLayoutOptions()
    ly.read(str(cand_gds), opts)      # merges by cell name
    lb = ly.layer(*L["bnd"])
    top = ly.create_cell("ctx_top")
    row = ["sg13g2_hv_inv_1", name, "sg13g2_hv_nand2_1"]
    x = 0.0
    for cn in row:
        c = ly.cell(cn)
        assert c is not None, f"cell {cn} not found"
        b = [s.dbbox() for s in c.shapes(lb).each()][0]
        for trans, y in ((db.DTrans.R0, 0.0), (db.DTrans.M0, 2 * b.height())):
            top.insert(db.DCellInstArray(
                c.cell_index(), db.DTrans(trans, x - b.left, y)))
        x += b.width()
    # keep only the context in the output
    out_ly = ly.dup()
    out_ly.write(str(out))
    return out


def run_lvs(cand_gds, name, run_dir):
    env = dict(os.environ, PATH=f"{KLAYOUT_BIN}:{os.environ.get('PATH', '')}")
    log = run_dir / f"{name}.lvs.log"
    r = subprocess.run(
        [sys.executable, str(PDK / "libs.tech/klayout/tech/lvs/run_lvs.py"),
         f"--layout={cand_gds}", f"--netlist={CDL}", f"--topcell={name}",
         f"--run_dir={run_dir / (name + '_lvs')}", "--combine_devices"],
        capture_output=True, text=True, env=env, timeout=600)
    log.write_text(r.stdout + r.stderr)
    return "Netlists match" in (r.stdout + r.stderr)


def run_klayout_drc(ctx_gds, run_dir):
    env = dict(os.environ, PATH=f"{KLAYOUT_BIN}:{os.environ.get('PATH', '')}")
    r = subprocess.run(
        [sys.executable, str(PDK / "libs.tech/klayout/tech/drc/run_drc.py"),
         f"--path={ctx_gds}", "--topcell=ctx_top", "--no_density",
         f"--run_dir={run_dir / 'klayout_drc'}", "--mp=4"],
        capture_output=True, text=True, env=env, timeout=1800)
    ok = "DRC Check Passed" in (r.stdout + r.stderr)
    (run_dir / "klayout_drc.log").write_text(r.stdout + r.stderr)
    return ok


def run_magic_drc(ctx_gds, run_dir):
    tcl = run_dir / "magic_drc.tcl"
    tcl.write_text(f"""gds read {ctx_gds}
load ctx_top
select top cell
drc euclidean on
drc style drc(full)
drc check
set out [drc listall why]
foreach {{msg boxes}} $out {{ puts "N=[llength $boxes] $msg" }}
quit -noprompt
""")
    r = subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile",
                        str(MAGICRC), str(tcl)],
                       capture_output=True, text=True, cwd=run_dir,
                       timeout=1800)
    (run_dir / "magic_drc.log").write_text(r.stdout + r.stderr)
    counts = {}
    for m in re.finditer(r"^N=(\d+) (.+?) \(([\w.]+)\)$", r.stdout, re.M):
        counts[m.group(3)] = counts.get(m.group(3), 0) + int(m.group(1))
    fatal = {k: v for k, v in counts.items()
             if not any(k.startswith(p) for p in MAGIC_KNOWN)}
    return counts, fatal


def main(paths):
    run_dir = pathlib.Path(tempfile.mkdtemp(prefix="cellverify_"))
    all_ok = True
    results = {}
    for p in map(pathlib.Path, paths):
        ly = db.Layout()
        ly.read(str(p))
        tops = [c for c in ly.top_cells()]
        assert len(tops) == 1, f"{p}: want exactly one top cell"
        name = tops[0].name
        li = {k: ly.layer(*v) for k, v in L.items()}
        struct_errs, bnd = check_structure(tops[0], li)
        pin_errs, offtrack = check_pins(tops[0], li, ly)
        lvs_ok = run_lvs(p, name, run_dir)
        ctx = build_context(p, name, run_dir / f"{name}_ctx.gds")
        kl_ok = run_klayout_drc(ctx, run_dir)
        mag_counts, mag_fatal = run_magic_drc(ctx, run_dir)
        ok = (not struct_errs and not pin_errs and lvs_ok and kl_ok
              and not mag_fatal)
        all_ok &= ok
        results[name] = {
            "pass": ok, "width_sites": bnd.width() // SITE,
            "structure": struct_errs or "ok",
            "pins_off_track": offtrack,
            "lvs": "match" if lvs_ok else "MISMATCH",
            "klayout_drc": "clean" if kl_ok else "VIOLATIONS",
            "magic": mag_counts,
            "magic_fatal": mag_fatal or "none",
        }
        print(f"{'PASS' if ok else 'FAIL'} {name}  "
              f"(logs: {run_dir})")
    print(json.dumps(results, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
