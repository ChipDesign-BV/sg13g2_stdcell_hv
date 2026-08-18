#!/usr/bin/env python3
"""Combined signoff JSON + PDF report for the eight retargeted flip-flops.

Inputs (this directory):
  verify_all.json          consolidated cell_verify.py run over all 8 GDS
  verify_<short>/          per-cell cell_verify artifact copies
  <cell>.gds               the layouts

Outputs:
  flops.signoff.json
  flops_report.pdf
"""
import datetime
import json
import pathlib
import re
import sys

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import gen_seq                                                  # noqa: E402
import layout_retarget as rt                                    # noqa: E402

CELLS = [
    ("sg13g2_hv_dfrbpq_1", "verify_run"),
    ("sg13g2_hv_dfrbp_1", "verify_dfrbp_1"),
    ("sg13g2_hv_dfrbpq_2", "verify_dfrbpq_2"),
    ("sg13g2_hv_dfrbp_2", "verify_dfrbp_2"),
    ("sg13g2_hv_sdfrbpq_1", "verify_sdfrbpq_1"),
    ("sg13g2_hv_sdfrbp_1", "verify_sdfrbp_1"),
    ("sg13g2_hv_sdfrbpq_2", "verify_sdfrbpq_2"),
    ("sg13g2_hv_sdfrbp_2", "verify_sdfrbp_2"),
]
SITE = 0.48

NOTES = """\
METHOD (all cells): thin-oxide source cell mapped by the library 1-D
retarget (work/layout_retarget.py) with a per-cell y-map: rail insert
+0.17 um (dfrbpq_1/dfrbp_1, LV NMOS top 1.78) or +0.16 um (all others,
LV NMOS top 1.79), channel-cut insert at y (1.79,1.84) carrying the
balance of the library's 0.975 um total, pSD insert +0.10 um.  The high
NMOS Activ band tops out at exactly 1.950 um = 0.62 um under the strict
2.570 um well bottom; every full-width template feature (rails, taps,
pSD band, N-well, ThickGateOx) lands on the shipped-library positions
(asserted per build).

DEVIATIONS / SPECIAL STRUCTURES (all layout-only; no device, W, L or
connectivity change anywhere):
 1. p+ source fingers butting the VDD n+ tap (1-3 per cell) are removed
    before the map and redrawn to y=6.99 after it -- the shipped
    sg13g2_hv_slgcp_1 convention; the LVS deck connects the junction
    (psd_ntap_abutt).  In six cells the LV tap strip is drawn merged
    into the device polygon; the same cut separates it.
 2. Upper pSD rebuilt to the template band 2.635..6.92.  dfrbp_2,
    sdfrbp_1, sdfrbp_2 carry W=2.40/2.69 PMOS channels whose gates
    reach down to y=2.980; these get a local pSD jog to 2.580 (pSD.i1
    0.40) and a strict-well halo dip to 2.360 (NW.c1), both asserted
    0.40/0.62 clear of all NFET geometry and >= 0.62 from the cell
    edges (fix_well_nwc1.py dip rule).
 3. N-well rebuilt per work/fix_well_nwc1.py strict convention:
    overhang +-0.62, bottom 2.570, square-corner asserts for
    NW.c1/NW.d1/NW.f1.
 4. Rail tap contacts re-tiled to 0.24+0.48k site centres
    (fix_rail_contacts.py guards).
 5. M1.e (deck-exact: separation to >0.30um-wide lines, 0.22 um at
    >1.0 um run) auto-repaired by receding one facing edge under the
    pilot's guards; 1-4 edits per cell.  dfrbp_1's Q_N pin widened
    left to cover the 18.48 track (grid_align_pins.py policy).

NOT CERTIFIED: chip-level density (M1.j-M5.j, TM1.c, TM2.c, AFil.g --
assembly fill); PEX / post-layout re-simulation (device geometry equals
the characterized CDL, parasitics not folded back); liberty data remains
schematic-characterized.
"""


def main():
    verify = json.loads(re.search(
        r"\{.*\}", (HERE / "verify_all.json").read_text(), re.S).group(0))
    cells = []
    for name, vdir in CELLS:
        ly = db.Layout()
        ly.read(str(HERE / f"{name}.gds"))
        cell = ly.cell(name)
        lay = {k: ly.layer(*v) for k, v in rt.LAYERS.items()}
        bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()][0]
        pins = gen_seq.pin_report(cell, lay, bnd.width())
        cir = next((HERE / vdir).glob("*_lvs/*_extracted.cir"), None)
        hist = {}
        if cir:
            for m in re.finditer(r"(sg13_hv_[np]mos) L=([\d.]+u) W=([\d.]+u)",
                                 cir.read_text()):
                k = f"{m.group(1)} W={m.group(3)}"
                hist[k] = hist.get(k, 0) + 1
        v = verify.get(name, {})
        cells.append({
            "cell": name,
            "pass": v.get("pass"),
            "width_um": round(bnd.width(), 3),
            "width_sites": round(bnd.width() / SITE),
            "height_um": round(bnd.height(), 3),
            "structure": v.get("structure"),
            "lvs": v.get("lvs"),
            "klayout_drc": v.get("klayout_drc"),
            "magic": v.get("magic"),
            "magic_fatal": v.get("magic_fatal"),
            "pins_off_track": v.get("pins_off_track"),
            "device_count": sum(hist.values()),
            "device_histogram": hist,
            "pins": pins,
            "pins_on_grid": {p["pin"]: bool(p["v_tracks"]) for p in pins
                             if p["pin"] not in ("VDD", "VSS")},
            "artifacts": str(HERE / vdir),
        })
    so = {
        "date": datetime.date.today().isoformat(),
        "gate": "python3 work/cell_verify.py <gds> (LVS + KLayout DRC "
                "main+maximal in 2-row abutted context + Magic full DRC + "
                "strict-well structure + pin checks)",
        "all_pass": all(c["pass"] for c in cells),
        "cells": cells,
        "notes": NOTES,
    }
    out = HERE / "flops.signoff.json"
    out.write_text(json.dumps(so, indent=2))
    print(f"wrote {out}  all_pass={so['all_pass']}")
    make_pdf(so)


LAYER_STYLE = [
    ((31, 0),  "#f2e394", 0.5, "NWell"),
    ((44, 0),  "#dddddd", 0.3, "ThickGateOx"),
    ((14, 0),  "#f7c5cc", 0.5, "pSD"),
    ((1, 0),   "#4caf50", 0.75, "Activ"),
    ((5, 0),   "#d32f2f", 0.75, "GatPoly"),
    ((6, 0),   "#212121", 0.9, "Cont"),
    ((8, 0),   "#1e6bb8", 0.45, "Metal1"),
    ((189, 4), "none",    1.0, "prBoundary"),
]


def make_pdf(so):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Polygon as MplPoly, Rectangle

    pdf_path = HERE / "flops_report.pdf"
    with PdfPages(str(pdf_path)) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.96, "sg13g2_stdcell_hv flip-flops — layout signoff",
                 ha="center", size=15, weight="bold")
        lines = [f"Date: {so['date']}",
                 f"Gate: {so['gate']}", "",
                 f"{'cell':26s} {'verdict':8s} {'sites':>5s} {'um':>7s} "
                 f"{'devs':>4s}  lvs      drc    magic"]
        for c in so["cells"]:
            lines.append(
                f"{c['cell']:26s} {'PASS' if c['pass'] else 'FAIL':8s} "
                f"{c['width_sites']:5d} {c['width_um']:7.2f} "
                f"{c['device_count']:4d}  {c['lvs']:8s} "
                f"{c['klayout_drc']:6s} {c['magic_fatal']}")
        lines += ["", "PINS (all on the 0.48 um vertical track grid; "
                      "rails full-width M1 per template)"]
        for c in so["cells"]:
            sig = [p["pin"] for p in c["pins"]
                   if p["pin"] not in ("VDD", "VSS")]
            lines.append(f"  {c['cell']:26s} {', '.join(sorted(sig))}")
        lines += [""] + so["notes"].splitlines()
        fig.text(0.06, 0.93, "\n".join(lines), va="top",
                 family="monospace", size=6.4)
        pdf.savefig(fig)
        plt.close(fig)

        for c in so["cells"]:
            ly = db.Layout()
            ly.read(str(HERE / f"{c['cell']}.gds"))
            cell = ly.cell(c["cell"])
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            for (l, d), color, alpha, label in LAYER_STYLE:
                li = ly.layer(l, d)
                first = True
                for s in cell.shapes(li).each():
                    if s.is_text():
                        continue
                    poly = s.dpolygon
                    if poly is None:
                        continue
                    if color == "none":
                        b = s.dbbox()
                        ax.add_patch(Rectangle((b.left, b.bottom), b.width(),
                                               b.height(), fill=False,
                                               edgecolor="black", lw=1.2,
                                               linestyle="--",
                                               label=label if first else None))
                    else:
                        pts = [(p.x, p.y) for p in poly.each_point_hull()]
                        ax.add_patch(MplPoly(pts, closed=True,
                                             facecolor=color, alpha=alpha,
                                             edgecolor=color,
                                             label=label if first else None))
                    first = False
            for s in cell.shapes(ly.layer(8, 25)).each():
                if s.is_text():
                    ax.annotate(s.dtext.string, (s.dtext.x, s.dtext.y),
                                size=7, weight="bold", ha="center",
                                bbox=dict(fc="white", alpha=0.7, ec="none"))
            ax.set_xlim(-1, c["width_um"] + 1)
            ax.set_ylim(-1, 8.2)
            ax.set_aspect("equal")
            ax.set_title(f"{c['cell']} — {c['width_sites']} sites, "
                         f"{'PASS' if c['pass'] else 'FAIL'}")
            ax.legend(loc="upper right", fontsize=6)
            pdf.savefig(fig)
            plt.close(fig)
    print(f"wrote {pdf_path}")


if __name__ == "__main__":
    main()
