#!/usr/bin/env python3
"""Build a DRC context cell for the retargeted library.

Checking a standard cell in isolation gives false errors: the power rails run
off both ends of the cell, the rail Activ crosses the cell boundary, and the
ThickGateOx region ends at the cell edge. All of those are only legal because
cells abut. So place every cell in an abutted row, with a second row mirrored
above it so the two share a rail, which is how they are actually used.
"""
import pathlib
import klayout.db as db

SRC = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
OUT = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work/drc/drc_top.gds")
BOUND = (189, 4)


def main():
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
        # row 0, then row 1 mirrored in y so the two rows share the VDD rail
        top.insert(db.DCellInstArray(
            ci, db.DTrans(db.DTrans.R0, x - b.left, 0.0)))
        top.insert(db.DCellInstArray(
            ci, db.DTrans(db.DTrans.M0, x - b.left, 2 * H)))
        x += b.width()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(OUT))
    print(f"{len(cells)} cells, row width {x:.2f} um, row height {H:.3f} um")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
