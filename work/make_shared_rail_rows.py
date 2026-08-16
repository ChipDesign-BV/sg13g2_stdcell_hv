#!/usr/bin/env python3
"""Build a shared-rail DRC array: rows at true 7.14 um pitch, mixed neighbours.

make_drc_rows.py stacks each cell in its own column at the padded bbox pitch
(7.98 um), so rows never actually share a rail and every vertical neighbour
is the same cell -- exactly the two conditions under which the rail-tap
contact clash (see fix_rail_contacts.py) is invisible. This harness builds
what place-and-route actually produces:

  * rows at ROW_H = 7.14 um pitch, alternating N / FS, so adjacent rows
    share their rail centreline;
  * each row is the full cell list in a different rotation of the order, so
    a cell's vertical neighbour across the rail is (almost) always a
    different cell;
  * odd rows also mirror each cell in x (the M90 half of what detailed
    placement's mirroring does), to exercise the mirror-invariance of the
    site-centred contact grid;
  * cells advance by their LEF width (site multiple), so the drawn margins
    overlap exactly as in a placed block.

Run the PDK DRC on the result with the same fixed invocation as drc_top:
  run_drc.py --path=work/drc/shared_rail.gds --topcell=shared_rail
"""
import pathlib
import re

import klayout.db as db

SRC = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
LEF = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/lef/sg13g2_stdcell_hv.lef")
OUT = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work/drc/shared_rail.gds")
BOUND = (189, 4)
ROW_H = 7.14
ROWS = 4


def main():
    widths = {m.group(1): float(m.group(3))
              for m in re.finditer(r"MACRO (\S+)(.*?)SIZE ([\d.]+) BY",
                                   LEF.read_text(), re.S)}
    ly = db.Layout()
    ly.read(str(SRC))
    lb = ly.layer(*BOUND)

    cells = sorted((ly.cell(ci.cell_index()) for ci in ly.each_cell()
                    if not ly.cell(ci.cell_index()).shapes(lb).is_empty()),
                   key=lambda c: c.name)
    total_w = sum(widths[c.name] for c in cells)

    top = ly.create_cell("shared_rail")
    for r in range(ROWS):
        order = cells[r * 17 % len(cells):] + cells[:r * 17 % len(cells)]
        x = 0.0
        for c in order:
            w = widths[c.name]
            if r % 2 == 0:
                # N: upright
                t = db.DTrans(db.DTrans.R0, x, r * ROW_H)
            elif r == 1:
                # S: flipped onto the shared rail AND x-mirrored
                t = db.DTrans(db.DTrans.R180, x + w, (r + 1) * ROW_H)
            else:
                # FS: flipped onto the shared rail, not mirrored
                t = db.DTrans(db.DTrans.M0, x, (r + 1) * ROW_H)
            top.insert(db.DCellInstArray(c.cell_index(), t))
            x += w
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(OUT))
    print(f"{len(cells)} cells x {ROWS} shared-rail rows, "
          f"{total_w:.2f} x {ROWS * ROW_H:.2f} um -> {OUT}")


if __name__ == "__main__":
    main()
