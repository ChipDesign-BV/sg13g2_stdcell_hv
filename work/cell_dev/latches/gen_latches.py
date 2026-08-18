#!/usr/bin/env python3
"""Generate the four undrawn HV latch cells from their thin-oxide twins.

sg13g2_hv_{dllrq,dlhq,dlhr,dllr}_1 exist in the LV library
(sg13g2_stdcell) but were skipped by work/layout_retarget.py for one
reason: each connects one or two PMOS VDD sources by butting p+ Activ
straight into the n+ VDD rail tap, so a PMOS Activ shape tops out in the
rail band and analyse() refuses the cell ("PMOS Activ runs up into the
VDD rail").  dlhq_1 additionally has PMOS Activ bottoms at 1.905 um,
20 nm below the library band bottom Y0 = 1.925, which trips the second
guard; the slab retarget (retarget_pmos_activ) sets every device width
as snap(2.4 * h) from the slab top independent of the mapped bottom, so
the mapping is still exact (1.12 -> 2.690, matching the shipped CDL).

Recipe (same as work/flop_pilot/gen_dfrbpq.py, which passed signoff, but
with the *library* y-map -- these cells' NMOS bands are low, mapped tops
1.65..1.82 <= 1.95, so no custom cut is needed):

  1. remove the butting fingers from Activ before the map (boxes derived
     from the drawn geometry, asserted to be exactly covered);
  2. run the library retarget machinery: analyse (or its info dict when
     only the known dlhq bottom guard fires), build_maps with the
     library CUT inserts, transform_cell, retile_contacts,
     close_activ_notches, repair_m1e, pad_to_site, add_tgo;
  3. restore the fingers in the thick-oxide frame: from the mapped PMOS
     body top down 0.10 um, up to y = 6.99 where they merge the tap
     strip (sg13g2_hv_slgcp_1 convention; the KLayout LVS deck connects
     the p+/n+ butted junction through psd_ntap_abutt).  The mapped
     strap contacts land back under both the Activ and their M1;
  4. rebuild the N-well with work/fix_well_nwc1.py's strict construction
     (overhang +-0.62, bottom 2.570, NW.c1/d1/f1 square-corner asserts);
  5. re-tile the rail tap contacts onto the site-centred 0.48 um grid
     with the guards of work/fix_rail_contacts.py;
  6. optional per-cell guarded Metal1 edits (M1.e repairs, library
     M1E_EDITS style) -- entries added as cell_verify.py demands.

The mapped (jogged) upper pSD band is kept as the library map places it
for every shipped cell; it is not rebuilt.

Output: one single-cell GDS per latch in this directory.
Usage: python3 gen_latches.py [cellbase ...]   (default: all four)
"""
import pathlib
import sys

import klayout.db as db

WORK = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work")
sys.path.insert(0, str(WORK))
import layout_retarget as rt                                   # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DBU = rt.DBU
GRID = rt.GRID

ROW_H = 7.14
SITE = 0.48
TAP_BOT = 6.99                  # VDD tap Activ bottom (template)
TAP_TOP = 7.29
WELL_BOT = 2.570
NW_STRICT = 0.62
CONT = 0.16
ENC_ACTIV = 0.07
ENC_M1 = 0.09
SP_GAT = 0.11
SP_CONT = 0.18

# The p+ Activ fingers that butt the VDD rail tap in each thin-oxide cell
# (x0, y_body_join, x1, 3.63), from the drawn Activ outlines.
FINGERS = {
    "dllrq": [(2.695, 3.070, 2.995, 3.63)],
    "dlhq":  [(1.825, 3.105, 2.135, 3.63), (5.02, 3.025, 5.32, 3.63)],
    "dlhr":  [(0.95, 2.960, 1.25, 3.63), (2.635, 3.180, 2.92, 3.63)],
    "dllr":  [(2.77, 3.180, 3.12, 3.63)],
}

# Post-map Activ normalisation.  dlhq_1 and dllr_1 draw some PMOS S/D
# Activ bottom-aligned instead of top-aligned, so the slab retarget
# (which pins each slab to its mapped top and takes 2.4x its height)
# lands those bottoms at 2.85..2.98 -- deeper than the strict N-well
# convention can enclose next to this cell's own NMOS Activ
# (well jog bottom = pmos_bot - 0.62 must stay >= nmos_top + 0.62).
# SHIFTS moves whole Activ sub-regions up (device widths = slab heights
# are preserved; gate endcaps and contact enclosures are asserted
# afterwards).  TRIMS raises the bottom edge of contact-head slabs that
# hold no low contact.  All coordinates are in the final mapped frame.
ACT_SHIFTS = {
    "dllrq": [],
    "dlhq": [((7.5, 2.5, 10.9, 5.6), 0.205)],
    "dlhr": [],
    "dllr": [((9.9, 2.5, 13.0, 5.65), 0.10)],
}
ACT_TRIMS = {
    "dllrq": [],
    "dlhq": [],
    "dlhr": [],
    "dllr": [(3.36, 2.975, 3.795, 3.05), (9.705, 2.91, 9.9, 3.01)],
}

# Guarded post-map Metal1 trims per cell, filled in as cell_verify runs
# demand (M1.e repairs the automatic pass cannot place).  Boxes are
# subtracted from Metal1 (and Metal1.pin when overlapping) in the final
# frame, under the same guards as layout_retarget.fix_m1e_sites.
M1_EDITS = {
    "dllrq": [],
    # dlhq: two M1.e sites (space < 0.22 with a >= 0.30 wide line and
    # > 1.0 um parallel run).  (a) D pin pad right edge (x 1.255) faces
    # the wide column at 1.435 -> narrow the pad to 1.215 (0.22).
    # (b) the wide MP-drain line x 1.255..1.605 faces the contact column
    # at 1.805 over y 4.05..5.805.  Trimming the wide line necks it to
    # 0.15 at its own y4.05 step, so instead split the parallel run
    # sdfbbp_1-style: two 0.02-deep notches in the facing column between
    # its contacts cut the projection into 0.01/0.29/0.405 um pieces,
    # all under the 1.0 um M1.e run threshold; the column keeps 0.215
    # width and every contact keeps > 0.06 clearance to the notches.
    "dlhq": [(1.215, 1.83, 1.255, 3.25),
             (1.805, 4.06, 1.825, 4.59), (1.805, 4.88, 1.825, 5.40)],
    # dlhr: (a) tab edge x8.26..8.53 faces the wide column at 8.71 with a
    # 1.015 um run -- raise the tab bottom 1.91 -> 1.945 (run 0.98 < 1.0;
    # its contact sits at y >= 2.305).  (b) Q pin pad right edge (12.08)
    # faces the contact column at 12.26 (0.18) -- narrow the pad to
    # 12.04 (0.22); the 11.76 routing track stays inside the pin.
    "dlhr": [(8.26, 1.91, 8.53, 1.945), (12.04, 4.19, 12.08, 5.9)],
    # dllr: (a) bar top y1.26 (holds a contact at 0.005 enclosure, so it
    # cannot move) faces the wide block bottom y1.44 over a 1.115 um run
    # -- a 0.02-deep, 0.5-wide notch in the block bottom splits the run
    # into 0.385 + 0.23 um.  (b) D pin pad left edge (0.73) faces the
    # 0.16 line at 0.54 -- narrow the pad to 0.76 (0.22); track 1.2
    # stays inside.  (c) GATE_N pin pad right edge (2.78) faces the
    # column at 2.96 -- narrow to 2.74; tracks 1.68/2.16/2.64 stay.
    # (d) the same wide block's right edge (8.13) faces the column at
    # 8.315 with a 1.105 um run -- notch it at y1.93..2.06 (runs 0.49 +
    # 0.485).
    "dllr": [(7.4, 1.44, 7.9, 1.46), (0.73, 1.91, 0.76, 3.37),
             (2.74, 1.92, 2.78, 3.37), (8.11, 1.90, 8.13, 2.09)],
}
# Guarded post-map Metal1 additions per cell (same-net extensions; each
# checked for M1.b spacing against every other net's metal before use).
M1_ADDS = {
    "dllrq": [],
    "dlhq": [],
    "dlhr": [],
    "dllr": [],
}


def snap(v):
    return round(v / GRID) * GRID


def um_box(x0, y0, x1, y1):
    return db.Box(int(round(x0 * DBU)), int(round(y0 * DBU)),
                  int(round(x1 * DBU)), int(round(y1 * DBU)))


def region_of(cell, li):
    r = db.Region(cell.begin_shapes_rec(li))
    r.merge()
    return r


def library_inserts(src, lay, all_cells, gband):
    """Reproduce rt.main()'s global CUT inserts and dchan."""
    Y0, T, rail_bot, _ = gband
    need = 0.0
    for c in all_cells:
        psd = [s.dbbox() for s in c.shapes(lay["psd"]).each()]
        if psd:
            need = max(need,
                       rt.PSD_ENC_TGO - (Y0 - min(b.bottom for b in psd)))
    dchan = max(0.0, snap(need))

    ms = [(c, rt.channel_metrics(c, lay)) for c in all_cells]
    ms = [(c, m) for c, m in ms if m and m[1] is not None]
    cand = sorted({m[1] for _, m in ms})
    best = None
    for thr in cand:
        sub = [(c, m) for c, m in ms
               if m[0] < thr - 1e-9 and m[1] >= thr - 1e-9]
        if best is None or len(sub) > len(best[1]):
            best = (thr, sub)
    cut_y, sub = best
    d_nw = max(0.0,
               snap(rt.NW_D1_DIG - min(m[1] - m[0] for _, m in sub)),
               snap(rt.PSD_ENC_TGO - min(m[2] - m[0] for _, m in sub
                                         if m[2] is not None)))
    d_psd = max(0.0, snap(rt.PSD_ENC_TGO
                          - min(m[3] - m[2] for _, m in sub
                                if m[2] is not None and m[3] is not None)))
    d_rail = max(0.0, snap(rt.PSD_ENC_TGO
                           - min(m[5] - m[4] for _, m in ms
                                 if m[4] is not None and m[5] is not None)))
    return cut_y, d_nw, d_psd, d_rail, dchan


def remove_fingers(cell, lay, fingers):
    li = lay["activ"]
    r = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    for x0, y0, x1, y1 in fingers:
        box = db.Region(um_box(x0, y0, x1, y1))
        got = (r & box).area()
        assert got == box.area(), \
            f"finger {x0},{y0},{x1},{y1}: drawn area {got} != {box.area()}"
        r -= box
    cell.shapes(li).clear()
    for p in r.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)
    print(f"removed {len(fingers)} butting finger(s)")


def restore_fingers(cell, lay, xmap, fingers):
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    add = []
    for x0, y0, x1, y1 in fingers:
        mx0, mx1 = snap(xmap(x0)), snap(xmap(x1))
        probe = db.Region(um_box(mx0 + 0.01, 0.5, mx1 - 0.01, TAP_BOT - 0.01))
        pieces = (act & probe).merged()
        assert not pieces.is_empty(), f"no body under finger at {mx0}..{mx1}"
        body_top = max(p.bbox().top for p in pieces.each()) / DBU
        assert 2.6 < body_top < TAP_BOT - 0.2, (mx0, body_top)
        add.append(um_box(mx0, snap(body_top - 0.10), mx1, TAP_BOT))
        print(f"finger {x0:.3f}..{x1:.3f} -> x {mx0:.3f}..{mx1:.3f}, "
              f"y {snap(body_top - 0.10):.3f}..{TAP_BOT}")
    for b in add:
        act.insert(b)
    act.merge()
    cell.shapes(li).clear()
    for p in act.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)


def normalise_activ(cell, lay, shifts, trims):
    """Shift/trim Activ sub-regions in the mapped frame (see ACT_SHIFTS).

    Asserts afterwards: every contact overlapping a touched region keeps
    its 0.07 Activ enclosure and is not clipped; every gate (GatPoly over
    Activ) keeps a 0.18 endcap; no slab height inside a shifted region
    changed (device widths preserved by pure translation).
    """
    if not shifts and not trims:
        return
    ly = cell.layout()
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    touched = db.Region()
    for (x0, y0, x1, y1), dy in shifts:
        box = db.Region(um_box(x0, y0, x1, y1))
        part = (act & box).merged()
        assert not part.is_empty(), f"shift box {x0},{y0} selects nothing"
        # the box must not cut through any polygon horizontally: every
        # selected polygon's bbox must lie strictly inside the box in y
        for p in part.each():
            pb = p.bbox()
            assert pb.bottom > int(y0 * DBU) and pb.top < int(y1 * DBU), \
                f"shift box clips a polygon vertically: {pb}"
        act -= box
        moved = part.moved(0, int(round(dy * DBU)))
        act += moved
        touched += moved
    for x0, y0, x1, y1 in trims:
        box = db.Region(um_box(x0, y0, x1, y1))
        got = (act & box).area()
        assert got == box.area(), f"trim {x0},{y0}: not fully in Activ"
        act -= box
        touched += db.Region(um_box(x0, y0, x1, y1 + 0.2))
    act.merge()
    cell.shapes(li).clear()
    for p in act.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)

    # guards
    near = touched.sized(int(0.3 * DBU))
    for s in cell.shapes(ly.layer(6, 0)).each():
        cb = s.bbox()
        if (db.Region(cb) & near).is_empty():
            continue
        if not (db.Region(cb) & act).is_empty():
            assert (db.Region(cb.enlarged(70, 70)) - act).is_empty(), \
                f"cont at {cb} lost its Activ enclosure"
    gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
    for p in (gat & act).merged().each():
        b = p.bbox()
        if (db.Region(b) & near).is_empty():
            continue
        leg = gat & db.Region(db.Box(b.left, b.bottom - 1000,
                                     b.right, b.top + 1000))
        lb = leg.bbox()
        assert lb.top >= b.top + 180 and lb.bottom <= b.bottom - 180, \
            f"gate endcap broken at {b}"
    print(f"normalised Activ: {len(shifts)} shift(s), {len(trims)} trim(s)")


def rebuild_nwell(cell, lay, W):
    """fix_well_nwc1.py's strict-rule construction, single cell."""
    ly = cell.layout()
    li = lay["nwell"]
    old = db.Region(cell.shapes(li)).merged()
    top = old.bbox().top          # dbu
    act = region_of(cell, ly.layer(1, 0))
    psd = region_of(cell, ly.layer(14, 0))
    pact = act & psd
    nact = act - psd
    pmos = pact.dup(); pmos.select_inside(old)
    ptap = pact - pmos
    nmos = nact.dup(); nmos.select_outside(old)

    enc = int(NW_STRICT * DBU)
    left, right = -enc, int(round(W * DBU)) + enc
    band = db.Region(db.Box(left, int(WELL_BOT * DBU), right, top))
    halo = pmos.sized(enc) & db.Region(db.Box(left, 0, right, top))
    # Deep PMOS Activ (mapped bottoms < WELL_BOT + 0.62) gets a local well
    # jog, exactly as work/fix_well_nwc1.py allows: the jog must keep the
    # 0.62 overhang distance to the cell boundary (the neighbour's
    # N-active is unknown), and the NW.d1/NW.f1 subtractions below must
    # not carve into it (asserted via NW.c1).
    dip = halo & db.Region(db.Box(left, 0, right, int(WELL_BOT * DBU)))
    if not dip.is_empty():
        dbb = dip.bbox()
        assert (dbb.left >= enc and dbb.right <= int(round(W * DBU)) - enc), \
            f"well jog too close to the cell boundary: {dbb}"
        assert dbb.bottom >= int(WELL_BOT * DBU) - 400, dbb.bottom
        print(f"well jog below {WELL_BOT}: x {dbb.left / DBU:.3f}.."
              f"{dbb.right / DBU:.3f}, bottom {dbb.bottom / DBU:.3f}")
    new = band + halo
    new -= nmos.sized(enc)
    new -= ptap.sized(enc)
    new.merge()

    assert (halo - new).is_empty(), "NW.c1"
    assert (new & nmos.sized(enc)).is_empty(), "NW.d1"
    assert (new & ptap.sized(enc)).is_empty(), "NW.f1"
    nb = new.bbox()
    assert (nb.left, nb.right, nb.top) == (left, right, top), nb
    assert nb.bottom >= int(WELL_BOT * DBU) - 400, nb.bottom
    for p in new.each():
        for pt in p.each_point_hull():
            assert pt.x % 5 == 0 and pt.y % 5 == 0, pt
    cell.shapes(li).clear()
    for p in new.each_merged():
        cell.shapes(li).insert(p)
    n_top = max((p.bbox().top for p in nmos.each()), default=0) / DBU
    print(f"nwell: [{left / DBU:.2f}, {right / DBU:.2f}] x "
          f"[{WELL_BOT}, {top / DBU}], NMOS Activ top {n_top:.3f} "
          f"(clearance {WELL_BOT - n_top:.3f})")


def retile_rail_contacts(cell, lay, W):
    ly = cell.layout()
    li = lay["cont"]
    activ = region_of(cell, ly.layer(1, 0))
    m1 = region_of(cell, ly.layer(8, 0))
    gat = region_of(cell, ly.layer(5, 0))
    psd = region_of(cell, ly.layer(14, 0))
    nwell = region_of(cell, ly.layer(31, 0))

    rails = {0.0: [], ROW_H: []}
    others = db.Region()
    for sh in cell.each_shape(li):
        b = sh.dbbox()
        cy = (b.bottom + b.top) / 2
        for rail in rails:
            if abs(cy - rail) < 0.02:
                rails[rail].append(sh)
                break
        else:
            others.insert(sh.polygon)
    others.merge()

    def sq(cx, cy, grow=0.0):
        h = CONT / 2 + grow
        return db.Region(um_box(cx - h, cy - h, cx + h, cy + h))

    for rail, shapes in rails.items():
        assert shapes, f"no rail contacts at y={rail}"
        old_x = sorted((s.dbbox().left + s.dbbox().right) / 2 for s in shapes)
        band = db.Region(um_box(-1, rail - 0.001, W + 1, rail + 0.001))
        strips = [(p.bbox().left / DBU, p.bbox().right / DBU)
                  for p in (activ & band).merged().each()]
        kept = []
        for k in range(int(round(W / SITE))):
            cx = SITE / 2 + k * SITE
            cb = sq(cx, rail)
            if rail == 0.0:
                if not (cb - psd).is_empty():
                    continue
            else:
                if not (cb & psd).is_empty():
                    continue
                if not (cb - nwell).is_empty():
                    continue
            if not (sq(cx, rail, ENC_ACTIV) - activ).is_empty():
                continue
            if not (sq(cx, rail, ENC_M1) - m1).is_empty():
                continue
            if not (sq(cx, rail, SP_GAT - 0.001) & gat).is_empty():
                continue
            if not (sq(cx, rail, SP_CONT - 0.001) & others).is_empty():
                continue
            kept.append(cx)
        for lo, hi in strips:
            had = any(lo - 0.081 <= x <= hi + 0.081 for x in old_x)
            has = any(lo - 0.081 <= x <= hi + 0.081 for x in kept)
            assert not (had and not has), \
                f"rail y={rail}: strip [{lo:.3f},{hi:.3f}] loses its contact"
        for sh in shapes:
            cell.shapes(li).erase(sh)
        for cx in kept:
            cell.shapes(li).insert(um_box(cx - CONT / 2, rail - CONT / 2,
                                          cx + CONT / 2, rail + CONT / 2))
        print(f"rail y={rail}: {len(shapes)} -> {len(kept)} contacts")


def apply_m1_edits(cell, lay, edits, adds):
    """Guarded Metal1 trims/extensions in the final frame."""
    if not edits and not adds:
        return
    ly = cell.layout()
    conts = [s.dbbox() for s in cell.each_shape(ly.layer(6, 0))]
    for lnum in ((8, 0), (8, 2)):
        li = ly.layer(*lnum)
        r = db.Region(cell.shapes(li)).merged()
        if r.is_empty():
            continue
        texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
        before = r.count()
        kept = [cb for cb in conts
                if (db.Region(um_box(cb.left - 0.05, cb.bottom - 0.05,
                                     cb.right + 0.05, cb.top + 0.05))
                    - r).is_empty()]
        changed = False
        for x0, y0, x1, y1 in edits:
            box = db.Region(um_box(x0, y0, x1, y1))
            if (r & box).is_empty():
                continue                     # pin layer may not carry it
            if lnum == (8, 0):
                assert (r & box).area() == box.area(), \
                    f"edit {x0},{y0} not fully in M1"
            for cb in kept:
                assert (db.Region(um_box(cb.left - 0.06, cb.bottom - 0.06,
                                         cb.right + 0.06, cb.top + 0.06))
                        & box).is_empty(), "edit near a contact"
            r -= box
            changed = True
        if lnum == (8, 0):
            for x0, y0, x1, y1 in adds:
                r += db.Region(um_box(x0, y0, x1, y1))
                changed = True
        if not changed:
            continue
        r.merge()
        if lnum == (8, 0):
            assert r.count() <= before, "edit split a polygon"
            assert r.width_check(160).is_empty(), "edit violates M1.a"
            assert r.space_check(180).is_empty(), "edit violates M1.b"
            for cb in kept:
                assert (db.Region(um_box(cb.left - 0.05, cb.bottom - 0.05,
                                         cb.right + 0.05, cb.top + 0.05))
                        - r).is_empty(), "edit breaks a contact enclosure"
        cell.shapes(li).clear()
        for p in r.each():
            cell.shapes(li).insert(p)
        for t in texts:
            cell.shapes(li).insert(t)
    print(f"applied {len(edits)} M1 trim(s), {len(adds)} M1 addition(s)")


def pin_report(cell, lay, W):
    ly = cell.layout()
    lpin, ltxt = ly.layer(8, 2), ly.layer(8, 25)
    texts = [(s.text.string, s.text.x / DBU, s.text.y / DBU)
             for s in cell.shapes(ltxt).each() if s.is_text()]
    pins = db.Region(cell.shapes(lpin)).merged()
    for label, tx, ty in texts:
        grp = next((p for p in pins.each()
                    if p.bbox().contains(db.Point(int(tx * DBU),
                                                  int(ty * DBU)))), None)
        assert grp is not None, f"pin text {label} not on a pin shape"
        b = grp.bbox()
        lo, hi = b.left / DBU, b.right / DBU
        vt = [round(SITE / 2 + k * SITE, 3)
              for k in range(int(W / SITE) + 1)
              if lo - 1e-9 <= SITE / 2 + k * SITE <= hi + 1e-9]
        on = "ON-TRACK" if vt else "OFF-TRACK"
        print(f"pin {label:8s} x {lo:.3f}..{hi:.3f}  {on}  v={vt}")


def gen(base):
    lv_name = f"sg13g2_{base}_1"
    hv_name = f"sg13g2_hv_{base}_1"
    print(f"\n===== {lv_name} -> {hv_name} =====")
    src = db.Layout()
    src.read(str(rt.LV_GDS))
    lay = {k: src.layer(*v) for k, v in rt.LAYERS.items()}
    all_cells = [src.cell(ci.cell_index()) for ci in src.each_cell()]

    gband = rt.band(src, all_cells, lay)
    cut_y, d_nw, d_psd, d_rail, dchan = library_inserts(
        src, lay, all_cells, gband)
    rt.CUT[0], rt.CUT[1], rt.CUT[2], rt.CUT[3] = cut_y, d_nw, d_psd, d_rail
    print(f"library map: band {gband[0]:.3f}..{gband[1]:.3f}, cut {cut_y}, "
          f"inserts nw={d_nw} psd={d_psd} rail={d_rail} dchan={dchan}")

    cell = src.cell(lv_name)
    assert cell is not None, lv_name
    remove_fingers(cell, lay, FINGERS[base])

    info, why = rt.analyse(src, cell, gband)
    if info is None:
        # dlhq_1: PMOS Activ bottoms 20 nm below the band bottom.  The
        # slab retarget takes each width as snap(2.4*h) from the slab
        # top, so the mapping stays exact; accept this one reason.
        assert "below the library PMOS band" in why, why
        activ = db.Region(cell.shapes(lay["activ"])).merged()
        gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
        bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()][0]
        pmos_bot = min(
            b.bottom for b in (s.dbbox()
                               for s in cell.shapes(lay["activ"]).each())
            if b.width() > 0 and rt.is_pmos_dev(
                b, db.Region(cell.shapes(lay["nwell"])).merged(), gat))
        assert pmos_bot >= gband[0] - 0.05 - 1e-9, pmos_bot
        info = {"W": bnd.width(), "H": bnd.height(),
                "gate_iv": rt.merged_x_intervals(activ & gat),
                "nodev": False}
        print(f"analyse override ({why.split(' -- ')[0]}; "
              f"pmos bottom {pmos_bot})")

    xmap, ymap = rt.build_maps(info, gband, dchan)
    # template invariants of the library y-map
    for src_y, want in ((3.63, TAP_BOT), (3.93, TAP_TOP),
                        (3.56, 6.825), (4.00, 7.36), (4.17, 7.53)):
        got = rt.snap_dbu(ymap(src_y)) / DBU
        assert abs(got - want) < 1e-9, (src_y, got, want)

    rt.transform_cell(src, cell, xmap, ymap, lay, info)
    rt.retile_contacts(cell, lay, xmap, ymap, src)
    n_notch = rt.close_activ_notches(cell, lay)
    n_m1e = rt.repair_m1e(cell, lay)
    pad = rt.pad_to_site(cell, lay)
    rt.add_tgo(cell, lay)
    print(f"notches closed: {n_notch}, m1e repairs: {n_m1e}, pad {pad:.3f}")

    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()][0]
    W = bnd.width()
    assert abs(W / SITE - round(W / SITE)) < 1e-6, W
    assert abs(bnd.height() - ROW_H) < 1e-9, bnd.height()
    print(f"cell {W:.2f} x {bnd.height():.2f} um = {round(W / SITE)} sites")

    normalise_activ(cell, lay, ACT_SHIFTS[base], ACT_TRIMS[base])
    restore_fingers(cell, lay, xmap, FINGERS[base])
    rebuild_nwell(cell, lay, W)
    retile_rail_contacts(cell, lay, W)
    apply_m1_edits(cell, lay, M1_EDITS[base], M1_ADDS[base])
    pin_report(cell, lay, W)

    keep = cell.cell_index()
    for ci in [c.cell_index() for c in src.each_cell()]:
        if ci != keep:
            src.delete_cell(ci)
    cell.name = hv_name
    out = HERE / f"{hv_name}.gds"
    src.write(str(out))
    print(f"wrote {out}")
    return out


def main(argv):
    bases = argv or ["dllrq", "dlhq", "dlhr", "dllr"]
    for b in bases:
        gen(b)


if __name__ == "__main__":
    main(sys.argv[1:])
