#!/usr/bin/env python3
"""Make the N-wells clean under the strict (non-DigiBnd) HV rules.

The cells were retargeted to the DigiBnd-relaxed digital well rules
(NW.c1.dig: 0.31 um N-well enclosure of HV P-active), which the KLayout
maximal deck verifies clean. Magic's SG13G2 tech has no DigiBnd concept
and applies the analog rules unconditionally -- NW.c1 enclosure 0.62 um,
NW.d1 spacing to HV N-active 0.62 um -- flagging every cell (25 nm short
in 65 of 68; mux4_1/slgcp_1 need deeper well jogs). Measured against
those rules there is room to fix this in the well layer alone: the
binding constraints leave a window for the well bottom, and the well is
not a device terminal, so nothing about the characterized devices
changes (the HV PSP model cards carry no well-proximity parameters
either). No re-characterization; only the GDS changes.

Construction, per cell:

  new_well = old_well
           | band(x in [-0.62, W+0.62], bottom = 2.570 um)
           | (pmos_active sized +0.62)          <- forces the mux4_1 and
                                                   slgcp_1 jogs
  minus (nmos_active sized +0.62)               <- NW.d1
  minus (p_tap sized +0.62)                     <- NW.f1

The lateral overhang grows from 240 to 620 nm at the same time: with
240 nm, a cell whose P-active sits closer than 620 nm to its edge is
enclosure-clean only through the neighbour's merged well, so the
outermost cell of every row still flags NW.c1. At 620 nm each cell is
clean standalone; in abutment the overhangs merge exactly as before,
and the overhang lives entirely above the 2.570 um band where no
cell's N-active (own or neighbour's, top 1.925 um worst case) can come
within 0.62 um.

2.570 um is the global bottom: >= 0.62 below every cell's P-active
bottom (3.220 um in the 55 shallowest cells) and >= 0.62 above every
cell's N-active top (1.925 um worst case, dlhrq_1) -- also across
abutment with any neighbour, so no jog below 2.570 is allowed within
0.62 um of the cell's left/right boundary (asserted; the two cells that
jog deeper do so well inside their outline). The union with the old
well means the well only ever grows: enclosures cannot regress, and the
mirrored-row P-well width shrinks from 5.25 to at worst 4.56 um, still
2.5x the 1.8 um NW.b1 minimum.

Asserted after construction, per cell (square-corner sizing, i.e. the
corner-inclusive worst case of the euclidian deck rules):

  * pmos_active sized +0.62 inside new_well      (NW.c1)
  * new_well disjoint from nmos_active sized +0.62  (NW.d1)
  * new_well disjoint from p_tap sized +0.62        (NW.f1)
  * well bbox unchanged except the bottom edge
  * result on the 5 nm manufacturing grid

The 9 NW.e1 flags magic raises on the counter are a separate,
block-boundary artifact (the VDD n-tap has 0.24 um well overhang beyond
the top/side of the outermost rows -- legal under the digital rule
NW.e1.dig, merged away wherever rows abut) and are out of scope here:
curing them needs boundary/endcap handling, not a cell edit.

Idempotent: re-running adds nothing. Follow with make_drc_top.py /
make_shared_rail_rows.py and the PDK decks + magic for signoff.

Usage: python3 fix_well_nwc1.py
"""
import pathlib
import sys

import klayout.db as db

HV = pathlib.Path(__file__).resolve().parent.parent
GDS = HV / "gds" / "sg13g2_stdcell_hv.gds"

L_ACTIV = (1, 0)
L_PSD = (14, 0)
L_NWELL = (31, 0)
L_BOUND = (189, 4)

ENC = 620        # nm; NW.c1 / NW.d1 / NW.f1 strict value
NEW_BOT = 2570   # nm; global well bottom
GRID = 5         # nm; manufacturing grid


def region(cell, layer):
    r = db.Region(cell.begin_shapes_rec(layer))
    r.merge()
    return r


def on_grid(r):
    for p in r.each():
        for pt in p.each_point_hull():
            if pt.x % GRID or pt.y % GRID:
                return False
    return True


def main():
    ly = db.Layout()
    ly.read(str(GDS))
    assert ly.dbu == 0.001, ly.dbu
    li = {k: ly.layer(*v) for k, v in
          dict(act=L_ACTIV, psd=L_PSD, nw=L_NWELL, bnd=L_BOUND).items()}

    changed = 0
    for ci in ly.each_cell():
        cell = ly.cell(ci.cell_index())
        bnd = region(cell, li["bnd"])
        if bnd.is_empty():
            continue                      # not a library cell
        w = bnd.bbox().width()
        well = region(cell, li["nw"])
        if well.is_empty():
            continue                      # fill cells still have wells; skip if none
        act = region(cell, li["act"])
        psd = region(cell, li["psd"])
        pact = act & psd
        nact = act - psd
        pmos = pact.dup()
        pmos.select_inside(well)
        ptap = pact - pmos
        nmos = nact.dup()
        nmos.select_outside(well)
        assert (pact - pmos - ptap).is_empty(), cell.name

        bb = well.bbox()
        # the lateral overhang grows 240 -> 620 nm so the outermost cell
        # of a row is enclosure-clean without a neighbour's merged well;
        # in abutment the overhangs merge exactly as before, and every
        # cell's N-active tops out 645+ nm below the 2570 band, so the
        # wider overhang can never approach a neighbour's N-active
        left, right = -ENC, w + ENC
        band = db.Region(db.Box(left, NEW_BOT, right, bb.top))
        # clip the halo to the existing well top: slgcp_1's P-active
        # butts the VDD n-tap, and that butted-junction top side is
        # already accepted by both decks with the existing 7.530 top
        halo = pmos.sized(ENC) & db.Region(db.Box(left, 0, right, bb.top))
        # jogs below the global bottom must keep ENC clear of the cell
        # boundary -- the neighbour's N-active is unknown
        dip = halo & db.Region(db.Box(left, 0, right, NEW_BOT))
        if not dip.is_empty():
            dbb = dip.bbox()
            assert dbb.left >= ENC and dbb.right <= w - ENC, \
                f"{cell.name}: deep well jog too close to the cell boundary"

        new = well + band + halo
        new -= nmos.sized(ENC)
        new -= ptap.sized(ENC)
        new.merge()

        # rule asserts (square sizing = worst case of the euclidian rules)
        assert (halo - new).is_empty(), f"{cell.name}: NW.c1"
        assert (new & nmos.sized(ENC)).is_empty(), f"{cell.name}: NW.d1"
        assert (new & ptap.sized(ENC)).is_empty(), f"{cell.name}: NW.f1"
        nb = new.bbox()
        assert (nb.left, nb.right, nb.top) == (left, right, bb.top), \
            f"{cell.name}: unexpected well outline"
        assert nb.bottom >= NEW_BOT - 400, \
            f"{cell.name}: well bottom {nb.bottom} unexpectedly deep"
        assert on_grid(new), f"{cell.name}: off-grid well vertex"

        if (new ^ well).is_empty():
            continue
        cell.shapes(li["nw"]).clear()
        for poly in new.each_merged():
            cell.shapes(li["nw"]).insert(poly)
        changed += 1

    ly.write(str(GDS))
    print(f"N-well bottom moved to {NEW_BOT / 1000} um in {changed} cells "
          f"-> {GDS.name}")


if __name__ == "__main__":
    sys.exit(main())
