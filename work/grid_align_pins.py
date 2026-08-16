#!/usr/bin/env python3
"""Widen signal pins so a vertical routing track crosses every one of them.

The 1-D retarget widens each gate 0.13 -> 0.45 um and then pads the cell to a
whole number of sites. Both move the internal geometry in x, and nothing puts
it back on the 0.48 um Metal1 track grid: 25 of the 68 cells' signal pins end
up with no vertical track passing through them, against 2 in the thin-oxide
library (and those two are the scan pins of sdfbbp_1, which the reference flow
does not use). Metal1 is below RT_MIN_LAYER, so those pins can only be reached
by dropping a via from Metal2, and a via wants a track.

The router copes with most of them, but not all: the first place-and-route of
this library left four nand4_1 B pins with no metal on them at all, and LVS
saw the nets split -- devices matched, nets did not.

The fix is the smallest one that makes the pin reachable: extend its Metal1
rectangle sideways until it covers the nearest track, on the side that has
room. A pin is only extended if the new metal keeps M1.b (0.18 um) to every
other net's Metal1 in the cell; a pin that cannot be extended safely is
reported rather than forced.

Run gen_lef.py afterwards to bring the LEF in step, then re-run DRC and LVS.

Reporting is the default; pass --apply to actually widen. Widening is not
enough on its own -- 11 of the 25 pins, including the nand4_1 B pin that
failed, have no room to reach a track without breaking M1.b, so a design
using this library should also let the router onto Metal1 (RT_MIN_LAYER:
Metal1), which is what the spi-slave flow_hv configs do. Putting the pins on
the grid in the first place is the real fix and belongs in layout_retarget.py.

Usage:  grid_align_pins.py [--apply]
"""
import pathlib
import sys

import pya

ROOT = pathlib.Path(__file__).resolve().parent.parent
GDS = ROOT / "gds" / "sg13g2_stdcell_hv.gds"

TRACK_X = 480          # Metal1 vertical track pitch, dbu (tracks.info)
M1_SPACE = 180         # M1.b minimum Metal1 space, dbu
M1 = (8, 0)
M1_PIN = (8, 2)
M1_TXT = (8, 25)
BOUND = (189, 4)


def track_lines(lo, hi):
    """track x positions that fall inside [lo, hi]"""
    k0 = -(-lo // TRACK_X)
    return [k * TRACK_X for k in range(int(k0), int(hi // TRACK_X) + 1)]


def main(dry_run=True):
    ly = pya.Layout()
    ly.read(str(GDS))
    l_m1, l_pin, l_txt = ly.layer(*M1), ly.layer(*M1_PIN), ly.layer(*M1_TXT)
    l_bnd = ly.layer(*BOUND)

    fixed, skipped, already = [], [], 0
    for ci in sorted(ly.each_cell(), key=lambda c: c.name):
        cell = ly.cell(ci.cell_index())
        bnd = [s.dbbox() for s in cell.shapes(l_bnd).each()]
        if not bnd:
            continue

        labels = [(s.text.string, pya.Point(s.text.x, s.text.y))
                  for s in cell.shapes(l_txt).each() if s.is_text()]
        pin_region = pya.Region(cell.shapes(l_pin)).merged()

        # group -> label
        groups = []
        for g in pin_region.each():
            gb = g.bbox()
            name = None
            for t, p in labels:
                if gb.contains(p):
                    name = t
                    break
            groups.append((name, gb))

        for name, gb in groups:
            if name in (None, "VDD", "VSS"):
                continue
            if track_lines(gb.left, gb.right):
                already += 1
                continue

            # nearest track on each side, and the metal that would be added
            left_track = (gb.left // TRACK_X) * TRACK_X
            right_track = left_track + TRACK_X
            others = (pya.Region(cell.shapes(l_m1)).merged()
                      - pya.Region(gb))
            done = False
            for track in sorted((left_track, right_track),
                                key=lambda t: min(abs(t - gb.left),
                                                  abs(t - gb.right))):
                if track < gb.left:
                    ext = pya.Box(track, gb.bottom, gb.left, gb.top)
                else:
                    ext = pya.Box(gb.right, gb.bottom, track, gb.top)
                if ext.width() <= 0:
                    continue
                # keep M1.b to every other net's metal
                clearance = pya.Region(ext).sized(M1_SPACE - 1)
                touching = clearance & others
                # metal already on this pin's own net does not count
                if not touching.is_empty():
                    continue
                if not dry_run:
                    for lay in (l_m1, l_pin):
                        cell.shapes(lay).insert(ext)
                fixed.append(f"{cell.name}/{name}")
                done = True
                break
            if not done:
                skipped.append(f"{cell.name}/{name}")

    if not dry_run:
        ly.write(str(GDS))

    print(f"pins already on a track: {already}")
    print(f"pins extended to a track: {len(fixed)}")
    if fixed:
        print("   " + " ".join(fixed))
    print(f"pins that could not be extended without violating M1.b: {len(skipped)}")
    if skipped:
        print("   " + " ".join(skipped))
    if not dry_run:
        print(f"wrote {GDS}")


if __name__ == "__main__":
    main(dry_run="--apply" not in sys.argv)
