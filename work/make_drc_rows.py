#!/usr/bin/env python3
"""Build an N-row DRC context cell, to tell edge artifacts from cell defects.

The two-row array reports two TGO.a violations, one along the very bottom of
the array and one along the very top, each spanning the full row width. The
claim is that these are an artifact of the array being finite: ThickGateOx is
drawn on the cell boundary grown by TGO.a so that abutted cells merge, and at
the outermost edge there is no neighbour to merge with.

If that is right, the count stays at two however many rows are stacked -- the
interior boundaries all merge. If instead it grew with the row count, it would
be a per-cell defect. Run with 2 and 3 rows and compare.

Usage:  make_drc_rows.py [rows]      (default 3)
"""
import pathlib
import sys
import klayout.db as db

SRC = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
BOUND = (189, 4)


def main(rows):
    out = pathlib.Path(
        f"/foss/designs/sg13g2_stdcell_hv/work/drc/drc_top{rows}.gds")
    ly = db.Layout()
    ly.read(str(SRC))
    lb = ly.layer(*BOUND)

    cells = []
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        bnd = [s.dbbox() for s in c.shapes(lb).each()]
        if bnd:
            cells.append((c.cell_index(), bnd[0]))
    cells.sort(key=lambda t: ly.cell(t[0]).name)

    top = ly.create_cell("drc_top")
    H = max(b.height() for _, b in cells)
    x = 0.0
    for ci, b in cells:
        for r in range(rows):
            # alternate rows are mirrored so neighbours share a rail, which is
            # how a placed row is actually built
            if r % 2 == 0:
                t = db.DTrans(db.DTrans.R0, x - b.left, r * H)
            else:
                t = db.DTrans(db.DTrans.M0, x - b.left, (r + 1) * H)
            top.insert(db.DCellInstArray(ci, t))
        x += b.width()

    out.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(out))
    print(f"{len(cells)} cells x {rows} rows, {x:.2f} x {rows * H:.3f} um "
          f"-> {out}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
