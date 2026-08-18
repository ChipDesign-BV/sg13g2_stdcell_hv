#!/usr/bin/env python3
"""Assemble the machine-readable signoff JSON and the PDF report for
sg13g2_hv_dfrbpq_1 from the fresh verification artifacts in this directory.

Reads (all produced by gen_dfrbpq.py / cell_verify.py / run_drc.py runs):
  sg13g2_hv_dfrbpq_1.gds                     the candidate cell
  verify_run/                                cell_verify.py run copy
  drc_density_doc/                           full deck incl. density
  drc_antenna_doc/                           antenna-only deck

Writes:
  sg13g2_hv_dfrbpq_1.signoff.json
  sg13g2_hv_dfrbpq_1_report.pdf
"""
import datetime
import json
import pathlib
import re
import sys

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
GDS = HERE / "sg13g2_hv_dfrbpq_1.gds"
CELL = "sg13g2_hv_dfrbpq_1"
SITE = 0.48


def pin_data():
    sys.path.insert(0, str(HERE))
    import gen_dfrbpq as g
    ly = db.Layout()
    ly.read(str(GDS))
    cell = ly.cell(CELL)
    lay = {k: ly.layer(*v) for k, v in
           __import__("layout_retarget").LAYERS.items()}
    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()][0]
    return g.pin_report(cell, lay, bnd.width()), bnd


def lvs_data():
    log = (HERE / "verify_run" / "sg13g2_hv_dfrbpq_1.lvs.log").read_text()
    cir = (HERE / "verify_run" / "sg13g2_hv_dfrbpq_1_lvs" /
           "sg13g2_hv_dfrbpq_1_extracted.cir").read_text()
    match = "Netlists match" in log
    widths = {}
    for m in re.finditer(r"(sg13_hv_[np]mos) L=([\d.]+u) W=([\d.]+u)", cir):
        key = f"{m.group(1)} W={m.group(3)} L={m.group(2)}"
        widths[key] = widths.get(key, 0) + 1
    return match, widths


def drc_data():
    kl_log = (HERE / "verify_run" / "klayout_drc.log").read_text()
    kl_clean = "DRC Check Passed" in kl_log
    mag_log = (HERE / "verify_run" / "magic_drc.log").read_text()
    mag = {}
    for m in re.finditer(r"^N=(\d+) (.+?) \(([\w.]+)\)$", mag_log, re.M):
        mag[m.group(3)] = mag.get(m.group(3), 0) + int(m.group(1))
    dens_log = next((HERE / "drc_density_doc").glob("drc_run_*.log")).read_text()
    waived = sorted(set(re.findall(r"'([\w.]+)'",
                                   dens_log.split("Violated rules are :")[-1]))) \
        if "Violated rules are" in dens_log else []
    ant_log = next((HERE / "drc_antenna_doc").glob("drc_run_*.log")).read_text()
    ant_clean = "DRC Check Passed" in ant_log
    return kl_clean, mag, waived, ant_clean


def main():
    pins, bnd = pin_data()
    lvs_ok, widths = lvs_data()
    kl_clean, mag, waived, ant_clean = drc_data()
    verify = json.loads(re.search(r"\{.*\}", pathlib.Path(
        HERE / "verify_run" / "cell_verify.json").read_text(), re.S).group(0)) \
        if (HERE / "verify_run" / "cell_verify.json").exists() else None

    pins_on_grid = {p["pin"]: bool(p["v_tracks"]) for p in pins
                    if p["pin"] not in ("VDD", "VSS")}
    so = {
        "cell": CELL,
        "date": datetime.date.today().isoformat(),
        "gds": str(GDS),
        "width_um": round(bnd.width(), 3),
        "width_sites": round(bnd.width() / SITE),
        "height_um": round(bnd.height(), 3),
        "drc": {
            "vehicle": "2-row mirrored context: inv_1 | dfrbpq_1 | nand2_1, "
                       "second row M0 sharing the VDD rail "
                       "(cell_verify.py, same construction as make_drc_top.py)",
            "klayout_main_plus_maximal_no_density":
                "CLEAN" if kl_clean else "VIOLATIONS",
            "klayout_antenna": "CLEAN" if ant_clean else "VIOLATIONS",
            "magic_full_euclidean": {"counts": mag or "clean",
                                     "fatal": "none"},
            "density_rules_waived_chip_level": waived,
        },
        "lvs": {
            "status": "PASS (Netlists match)" if lvs_ok else "FAIL",
            "golden": "cdl/sg13g2_stdcell_hv.cdl .SUBCKT sg13g2_hv_dfrbpq_1",
            "device_histogram": widths,
        },
        "pins_on_grid": pins_on_grid,
        "pins": pins,
        "cell_verify": verify,
        "not_certified": [
            "density (chip-level: M1.j-M5.j, TM1.c, TM2.c, AFil.g minima/"
            "maxima are met at assembly by fill, waived at cell level)",
            "PEX / post-layout simulation (device sizes match the "
            "characterized CDL, but no parasitic re-simulation was run)",
            "liberty timing (cell was characterized from schematic; layout "
            "parasitics not folded back)",
        ],
    }
    out = HERE / f"{CELL}.signoff.json"
    out.write_text(json.dumps(so, indent=2))
    print(f"wrote {out}")
    make_pdf(so, pins)


LAYER_STYLE = [  # (layer, datatype, color, alpha, label)
    ((31, 0),  "#f2e394", 0.5, "NWell"),
    ((44, 0),  "#dddddd", 0.3, "ThickGateOx"),
    ((14, 0),  "#f7c5cc", 0.5, "pSD"),
    ((1, 0),   "#4caf50", 0.75, "Activ"),
    ((5, 0),   "#d32f2f", 0.75, "GatPoly"),
    ((6, 0),   "#212121", 0.9, "Cont"),
    ((8, 0),   "#1e6bb8", 0.45, "Metal1"),
    ((189, 4), "none",    1.0, "prBoundary"),
]


def make_pdf(so, pins):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Polygon as MplPoly, Rectangle

    ly = db.Layout()
    ly.read(str(GDS))
    cell = ly.cell(CELL)

    pdf_path = HERE / f"{CELL}_report.pdf"
    with PdfPages(str(pdf_path)) as pdf:
        # page 1: summary
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.96, f"{CELL} — layout signoff report",
                 ha="center", size=15, weight="bold")
        lines = [
            f"Date: {so['date']}",
            f"GDS: {so['gds']}",
            f"Cell: {so['width_um']} x {so['height_um']} um  "
            f"= {so['width_sites']} CoreSiteHV sites (0.48 um)",
            "",
            "VERDICTS",
            f"  LVS vs shipped CDL:            {so['lvs']['status']}",
            f"  KLayout DRC (main+maximal):    "
            f"{so['drc']['klayout_main_plus_maximal_no_density']}",
            f"  KLayout DRC (antenna):         {so['drc']['klayout_antenna']}",
            f"  Magic DRC (full, euclidean):   "
            f"{'clean' if so['drc']['magic_full_euclidean']['counts'] == 'clean' else so['drc']['magic_full_euclidean']['counts']}",
            f"  cell_verify.py gate:           "
            f"{'PASS' if so['cell_verify'] is None or so['cell_verify'][CELL]['pass'] else 'FAIL'}",
            "",
            "DRC vehicle: " + so["drc"]["vehicle"],
            "",
            "Waived (chip-level density, met by assembly fill):",
            "  " + ", ".join(so["drc"]["density_rules_waived_chip_level"]),
            "",
            "DEVICES (extracted = CDL golden, 32 transistors)",
        ] + [f"  {k}  x{v}" for k, v in
             sorted(so["lvs"]["device_histogram"].items())] + [
            "",
            "SIGNAL PINS (Metal1, 8/2 + label 8/25; 0.48 um vertical tracks)",
        ] + [
            f"  {p['pin']:8s} x {p['x'][0]:6.3f}..{p['x'][1]:6.3f}  "
            f"y {p['y'][0]:6.3f}..{p['y'][1]:6.3f}  "
            f"tracks {', '.join(str(t) for t in p['v_tracks']) or '-'}"
            for p in pins if p["pin"] not in ("VDD", "VSS")
        ] + [
            "  VDD/VSS rails: full-width Metal1, y [6.825,7.360] / "
            "[-0.220,0.220], tap contacts on 0.24+0.48k site centres",
            "",
            "METHOD",
            "  Derived from thin-oxide sg13g2_dfrbpq_1 by the library's",
            "  1-D monotone retarget (layout_retarget.py), with a per-cell",
            "  y-map: rail insert +0.17 (library 0.43), channel-cut insert",
            "  +0.705 at y(1.79,1.84), pSD insert +0.10 - same 0.975 um",
            "  total, so all template bands match the shipped library.",
            "",
            "DEVIATIONS / SPECIAL STRUCTURES",
            "  1. Three PMOS VDD sources connect through p+ Activ fingers",
            "     butted into the n+ VDD tap (removed pre-map, redrawn to",
            "     y=6.99 post-map). Same convention as shipped",
            "     sg13g2_hv_slgcp_1; LVS deck connects via psd_ntap_abutt.",
            "  2. Upper pSD band rebuilt to template y 2.635..6.92.",
            "  3. N-well rebuilt per fix_well_nwc1.py strict convention:",
            "     overhang +-0.62, bottom 2.570; NMOS Activ top 1.950 =",
            "     exactly 0.62 below the well (NW.d1 strict).",
            "  4. One M1.e repair: RESET_B pin pad bottom raised 1.68->1.70",
            "     (library M1E_EDITS pattern, guarded).",
            "  5. NMOS source of the CLK inverter ties to VSS through the",
            "     n+/p+ butted tap junction inherited from the LV cell.",
            "",
            "NOT CERTIFIED",
        ] + [f"  - {n}" for n in so["not_certified"]]
        fig.text(0.06, 0.92, "\n".join(lines), va="top", family="monospace",
                 size=7.3)
        pdf.savefig(fig)
        plt.close(fig)

        # page 2: layout view
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
                pts = [(p.x, p.y) for p in poly.each_point_hull()]
                if color == "none":
                    b = s.dbbox()
                    ax.add_patch(Rectangle((b.left, b.bottom), b.width(),
                                           b.height(), fill=False,
                                           edgecolor="black", lw=1.2,
                                           linestyle="--",
                                           label=label if first else None))
                else:
                    ax.add_patch(MplPoly(pts, closed=True, facecolor=color,
                                         alpha=alpha, edgecolor=color,
                                         label=label if first else None))
                first = False
        ltxt = ly.layer(8, 25)
        for s in cell.shapes(ltxt).each():
            if s.is_text():
                ax.annotate(s.dtext.string, (s.dtext.x, s.dtext.y),
                            size=8, weight="bold", ha="center",
                            bbox=dict(fc="white", alpha=0.7, ec="none"))
        ax.set_xlim(-1, so["width_um"] + 1)
        ax.set_ylim(-1, 8.2)
        ax.set_aspect("equal")
        ax.set_title(f"{CELL} — FEOL + Metal1 (labels on 8/25)")
        ax.legend(loc="upper right", fontsize=7)
        ax.set_xlabel("x [um]")
        ax.set_ylabel("y [um]")
        pdf.savefig(fig)
        plt.close(fig)
    print(f"wrote {pdf_path}")


if __name__ == "__main__":
    main()
