#!/usr/bin/env python3
"""Re-tile rail-tap contacts onto the site-centred 0.48 um grid.

Why. Every cell taps its rails with contacts that straddle the row boundary
(y in [-0.08, 0.08] around the rail centreline), and in a placed block that
boundary is *shared*: the row above is flipped (FS) onto the same rail. The
retarget mapped each contact from its thin-oxide position through the cell's
own x-map, so each cell's rail contacts sit at cell-specific x positions.
Whenever two different cells meet across a rail, their tap contacts land at
slightly different x and the merged layout carries 0.19-0.32 um Cont bars --
neither a legal 0.16 square (Cnt.a/Cnt.b) nor a legal >= 0.34 ContBar
(CntB.a1). On the spi_slave signoff GDS this was ~19k markers, every one on
a rail. The library's own drc_top array never saw it because each column
stacks the *same* cell, whose contacts coincide exactly.

Fix. Place rail contacts at x = 0.24 + 0.48k (site centres, cell origin
frame). Site centres are preserved by the FS row flip and by the M90 mirror
detailed placement applies (cell widths are site multiples), so any two
library cells sharing a rail either land contacts exactly on top of each
other (a merged 0.16 square, legal) or 0.32 um apart edge-to-edge (>= Cnt.b
0.18, legal). The fill/decap cells already follow this grid.

Every new contact is checked in code before it is written:
  Activ enclosure  >= 0.07  (Cnt.c)
  Metal1 enclosure >= 0.09  (covers Cnt.g1/g2; rails give 0.14 in y)
  GatPoly space    >= 0.11  (Cnt.f)
  space to any untouched contact >= 0.18  (Cnt.b)
and every tap strip that had a contact before must still have one after --
the script fails loudly otherwise, rather than silently dropping a tap.

Usage:  fix_rail_contacts.py [--dry-run]
Rewrites gds/sg13g2_stdcell_hv.gds in place (backup in gds/*.gds.bak).
"""
import pathlib
import shutil
import sys

import klayout.db as db

GDS = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
LEF = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/lef/sg13g2_stdcell_hv.lef")
BOUND = (189, 4)                 # cell boundary marker
L_ACTIV, L_CONT, L_GAT, L_M1 = (1, 0), (6, 0), (5, 0), (8, 0)
L_PSD, L_NWELL = (14, 0), (31, 0)
ROW_H = 7.14                     # rail centrelines at y = 0 and y = ROW_H
SITE = 0.48
CONT = 0.16                      # Cnt.a: fixed contact size
ENC_ACTIV = 0.07                 # Cnt.c
ENC_M1 = 0.09                    # Cnt.g1/g2
SP_GAT = 0.11                    # Cnt.f
SP_CONT = 0.18                   # Cnt.b


def um_box(cx, cy, half, grow=0.0):
    return db.DBox(cx - half - grow, cy - half - grow,
                   cx + half + grow, cy + half + grow)


def region_of(cell, layer_index):
    r = db.Region(cell.begin_shapes_rec(layer_index))
    r.merge()
    return r


def lef_widths():
    import re
    txt = LEF.read_text()
    return {m.group(1): float(m.group(3))
            for m in re.finditer(
                r"MACRO (\S+)(.*?)SIZE ([\d.]+) BY", txt, re.S)}


def main(dry_run):
    widths = lef_widths()
    ly = db.Layout()
    ly.read(str(GDS))
    dbu = ly.dbu
    to_dbu = db.CplxTrans(dbu).inverted()

    li = {name: ly.layer(*num) for name, num in
          {"activ": L_ACTIV, "cont": L_CONT, "gat": L_GAT, "m1": L_M1,
           "psd": L_PSD, "nwell": L_NWELL}.items()}
    lb = ly.layer(*BOUND)

    total_old = total_new = 0
    for ci in ly.each_cell():
        cell = ly.cell(ci.cell_index())
        if cell.shapes(lb).is_empty():
            continue
        bb = cell.dbbox()
        width = widths[cell.name]          # LEF placement width, site multiple
        assert abs(width / SITE - round(width / SITE)) < 1e-6, cell.name

        activ = region_of(cell, li["activ"])
        m1 = region_of(cell, li["m1"])
        gat = region_of(cell, li["gat"])
        psd = region_of(cell, li["psd"])
        nwell = region_of(cell, li["nwell"])

        # Split contacts into the rail-straddling ones (per rail) and the rest.
        rail_shapes = {0.0: [], ROW_H: []}
        others = db.Region()
        for sh in cell.each_shape(li["cont"]):
            b = sh.dbbox()
            cy = (b.bottom + b.top) / 2
            for rail in rail_shapes:
                if abs(cy - rail) < 0.02:
                    rail_shapes[rail].append(sh)
                    break
            else:
                others.insert(sh.polygon)
        others.merge()

        for rail, shapes in rail_shapes.items():
            if not shapes:
                continue
            old_x = sorted((s.dbbox().left + s.dbbox().right) / 2
                           for s in shapes)

            # Tap strips: merged x-intervals of Activ across the rail band.
            band = db.Region(to_dbu *
                             db.DBox(bb.left, rail - 0.001, bb.right, rail + 0.001))
            strips = []
            for p in (activ & band).merged().each():
                pb = db.CplxTrans(dbu) * p.bbox()
                strips.append((pb.left, pb.right))

            kept = []
            for k in range(int(round(width / SITE))):
                cx = SITE / 2 + k * SITE
                cont_box = db.Region(to_dbu * um_box(cx, rail, CONT / 2))
                # Implant sanity: the tap strip can share Activ with butted
                # source/drain diffusion, and a contact on the wrong implant
                # under the rail would short a signal net to the supply.
                # VSS rail taps are p+ (inside pSD), VDD rail taps are n+
                # inside NWell (outside pSD).
                if rail == 0.0:
                    if not (cont_box - psd).is_empty():
                        continue
                else:
                    if not (cont_box & psd).is_empty():
                        continue
                    if not (cont_box - nwell).is_empty():
                        continue
                if not (db.Region(to_dbu * um_box(cx, rail, CONT / 2, ENC_ACTIV))
                        - activ).is_empty():
                    continue
                if not (db.Region(to_dbu * um_box(cx, rail, CONT / 2, ENC_M1))
                        - m1).is_empty():
                    continue
                if not (db.Region(to_dbu * um_box(cx, rail, CONT / 2, SP_GAT - dbu))
                        & gat).is_empty():
                    continue
                if not (db.Region(to_dbu * um_box(cx, rail, CONT / 2, SP_CONT - dbu))
                        & others).is_empty():
                    continue
                kept.append(cx)

            # Every strip that was tapped must still be tapped.
            for lo, hi in strips:
                had = any(lo - 0.081 <= x <= hi + 0.081 for x in old_x)
                has = any(lo - 0.081 <= x <= hi + 0.081 for x in kept)
                if had and not has:
                    sys.exit(f"ERROR: {cell.name} rail y={rail}: tap strip "
                             f"[{lo:.3f},{hi:.3f}] would lose its contact")

            total_old += len(shapes)
            total_new += len(kept)
            if not dry_run:
                for sh in shapes:
                    cell.shapes(li["cont"]).erase(sh)
                for cx in kept:
                    cell.shapes(li["cont"]).insert(
                        to_dbu * um_box(cx, rail, CONT / 2))
            print(f"{cell.name:28s} rail y={rail:5.2f}: "
                  f"{len(shapes):3d} -> {len(kept):3d}")

    print(f"\ntotal rail contacts: {total_old} -> {total_new}")
    if dry_run:
        print("dry run, GDS not written")
        return
    bak = GDS.with_suffix(".gds.bak")
    if not bak.exists():
        shutil.copy2(GDS, bak)
    ly.write(str(GDS))
    print(f"wrote {GDS}  (backup: {bak})")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
