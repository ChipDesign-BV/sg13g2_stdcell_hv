#!/usr/bin/env python3
"""Generate sg13g2_hv_dfrbpq_1 from the thin-oxide sg13g2_dfrbpq_1.

Why the library retarget skipped this cell, and what this script does about
each reason:

1. Three PMOS sources connect to VDD by butting p+ Activ straight into the
   n+ VDD rail tap, so PMOS Activ tops reach the rail band and the y-map
   cannot scale the band without moving the rail.
     -> the fingers are removed before the map (asserted to be exactly the
        expected boxes) and re-drawn afterwards in the thick-oxide frame,
        from the (now 2.4x taller) PMOS body top up to y = 6.99 where they
        merge with the tap strip.  Identical convention to the shipped
        sg13g2_hv_slgcp_1 (p+ under the pSD cover to 6.92, n+ for the last
        70 nm; the KLayout LVS deck connects the junction through
        psd_ntap_abutt).  One finger (x 10.59..10.89) carries contacts and
        an M1 strap from the VDD rail; the restored Activ lands back under
        both.

2. An NMOS Activ band sits at y 1.36..1.78, higher than in any retargeted
   cell.  The library's y-map inserts +0.43 um right above the VSS rail
   (pSD.j1) plus +0.445 um at a channel cut of y = 1.595 (NW.d1 + track
   pad), which would stretch this Activ (changing device W) and land its
   top at 2.21 -- inside the 0.62 um strict N-well clearance below the
   2.570 um well bottom.
     -> this cell gets its own y-map with the SAME total insert (0.975 um),
        split differently: +0.17 at the rail (all this cell's own pSD.j1
        needs: its lowest NFET gate is at 0.57, lowest n+ S/D Activ at
        0.39) and the remaining +0.705 at a cut of y in (1.79, 1.84),
        which is above every NMOS Activ top and below every PMOS bottom.
        The high NMOS band then maps to 1.53..1.95: exactly 0.62 below the
        2.570 well bottom.  Because the total insert and the band segment
        (Y0, T, x2.4) are unchanged, every full-width template feature
        (rails, tap Activ 6.99/7.29, M1 rail 6.825/7.36, pSD top 6.92,
        NWell top 7.53) lands exactly where the shipped library puts it --
        asserted below.

3. The mapped upper pSD band and N-well inherit the thin-oxide bottom jogs,
   which the custom cut would misplace.
     -> both are rebuilt outright to the template: upper pSD = full-width
        band y 2.635..6.92 (asserted >= 0.40 from every NFET gate and
        >= 0.40 below every PFET gate, pSD.j1/i1), N-well per the strict
        convention of work/fix_well_nwc1.py: overhang +-0.62, bottom
        2.570, minus 0.62 halos of NMOS Activ and the p-tap, union the
        0.62 halo of PMOS Activ -- with the same square-corner asserts.

Rail tap contacts are then re-tiled onto the site-centred 0.48 um grid with
the guards of work/fix_rail_contacts.py, and the pin/track report is
printed (0.48 vertical tracks through every signal pin).

Output: work/flop_pilot/sg13g2_hv_dfrbpq_1.gds  (single cell).
Nothing outside work/flop_pilot/ is written.
"""
import pathlib
import sys

import klayout.db as db

WORK = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work")
sys.path.insert(0, str(WORK))
import layout_retarget as rt                                   # noqa: E402

HERE = WORK / "flop_pilot"
OUT = HERE / "sg13g2_hv_dfrbpq_1.gds"
CELL_LV = "sg13g2_dfrbpq_1"
CELL_HV = "sg13g2_hv_dfrbpq_1"

DBU = rt.DBU
GRID = rt.GRID

# The three p+ Activ fingers that butt the VDD tap in the thin-oxide cell.
FINGERS_LV = [
    (6.075, 3.17, 6.505, 3.63),     # source of XP2 (CLK inverter, w=1.12)
    (9.570, 2.565, 9.810, 3.63),    # shared VDD source of the w=0.42 pair
    (10.590, 2.565, 10.890, 3.63),  # w=0.42 VDD source (contacted, M1 strap)
]

# custom y-map inserts (see module docstring, reason 2)
D_RAIL = 0.17                   # rail insert (library uses 0.43)
CUT_LO, CUT_HI = 1.79, 1.84     # this cell's channel cut band
D_PSD = 0.10                    # kept identical to the library
NMOS_TOP_LV = 1.78              # the high NMOS band this is all about

ROW_H = 7.14
SITE = 0.48
TAP_BOT = 6.99                  # VDD tap Activ bottom (template)
TAP_TOP = 7.29
PSD_TOP_BAND = (2.635, 6.92)    # template upper pSD band
PSD_EDGE = 0.07                 # pSD sideways overhang at the cell edge
WELL_OVER = 0.62                # strict-rule lateral N-well overhang
WELL_BOT = 2.570
NW_STRICT = 0.62
PSD_GATE_CLEAR = 0.40           # pSD.j1 / pSD.i1
CONT = 0.16
ENC_ACTIV = 0.07
ENC_M1 = 0.09
SP_GAT = 0.11
SP_CONT = 0.18


def snap(v):
    return round(v / GRID) * GRID


def um_box(x0, y0, x1, y1):
    return db.Box(int(round(x0 * DBU)), int(round(y0 * DBU)),
                  int(round(x1 * DBU)), int(round(y1 * DBU)))


def region_of(cell, li):
    r = db.Region(cell.begin_shapes_rec(li))
    r.merge()
    return r


def library_total_insert(src, lay, all_cells, gband):
    """The library's total below-band insert, derived as rt.main() does."""
    Y0, T, rail_bot, _ = gband
    need = 0.0
    for c in all_cells:
        psd = [s.dbbox() for s in c.shapes(lay["psd"]).each()]
        if psd:
            need = max(need, rt.PSD_ENC_TGO - (Y0 - min(b.bottom for b in psd)))
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
    total = snap(d_rail + d_nw + rt.TRACK_PAD + d_psd + dchan)
    print(f"library map: band {Y0:.3f}..{T:.3f}, cut {cut_y:.3f}, "
          f"d_rail {d_rail:.3f} d_nw {d_nw:.3f} track_pad {rt.TRACK_PAD:.3f} "
          f"d_psd {d_psd:.3f} dchan {dchan:.3f}  -> total {total:.3f}")
    return total, dchan


def build_custom_ymap(gband, total):
    Y0, T, _, _ = gband
    d_cut = snap(total - D_RAIL - D_PSD)
    assert d_cut > 0
    assert CUT_LO >= NMOS_TOP_LV - 1e-9 and CUT_HI <= Y0 - 0.05 - 1e-9
    ysegs = [
        (0.25, 0.35, 1.0 + D_RAIL / 0.10),
        (CUT_LO, CUT_HI, 1.0 + d_cut / (CUT_HI - CUT_LO)),
        (Y0 - 0.05, Y0, 1.0 + D_PSD / 0.05),
        (Y0, T, rt.KP),
    ]
    ymap = rt.PWL(ysegs)
    # template invariants, all snapped exactly as transform_cell snaps them
    for src_y, want in ((3.63, TAP_BOT), (3.93, TAP_TOP),
                        (3.56, 6.825), (4.00, 7.36),
                        (3.60, PSD_TOP_BAND[1]), (4.17, 7.53),
                        (Y0, snap(Y0 + total)),
                        (NMOS_TOP_LV, WELL_BOT - NW_STRICT)):
        got = rt.snap_dbu(ymap(src_y)) / DBU
        assert abs(got - want) < 1e-9, (src_y, got, want)
    print(f"custom y-map: rail +{D_RAIL}, cut ({CUT_LO},{CUT_HI}) +{d_cut}, "
          f"psd +{D_PSD}; NMOS top -> "
          f"{rt.snap_dbu(ymap(NMOS_TOP_LV)) / DBU}")
    return ymap


def remove_fingers(cell, lay):
    li = lay["activ"]
    r = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    for x0, y0, x1, y1 in FINGERS_LV:
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
    print(f"removed {len(FINGERS_LV)} butting fingers")


def restore_fingers(cell, lay, xmap):
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    add = []
    for x0, y0, x1, y1 in FINGERS_LV:
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


def rebuild_upper_psd(cell, lay, W):
    """Replace the mapped (jogged) upper pSD with the template band."""
    li = lay["psd"]
    low, texts = [], []
    for s in cell.shapes(li).each():
        if s.is_text():
            texts.append(s.text.dup())
        elif s.dbbox().bottom < 1.0:
            low.append(s.polygon)
        # everything else: the upper band, dropped
    assert low, "no low pSD band?"
    cell.shapes(li).clear()
    for p in low:
        cell.shapes(li).insert(p)
    cell.shapes(li).insert(um_box(-PSD_EDGE, PSD_TOP_BAND[0],
                                  W + PSD_EDGE, PSD_TOP_BAND[1]))
    for t in texts:
        cell.shapes(li).insert(t)

    # pSD.j1 / pSD.i1 asserts against the actual gates
    act = region_of(cell, cell.layout().layer(1, 0))
    gat = region_of(cell, cell.layout().layer(5, 0))
    gates = (act & gat).merged()
    lo_gate = min(p.bbox().bottom for p in gates.each()) / DBU
    n_gates = [p.bbox() for p in gates.each()
               if p.bbox().top / DBU < ROW_H / 2]
    p_gates = [p.bbox() for p in gates.each()
               if p.bbox().top / DBU >= ROW_H / 2]
    n_top = max(b.top for b in n_gates) / DBU
    p_bot = min(b.bottom for b in p_gates) / DBU
    assert PSD_TOP_BAND[0] - n_top >= PSD_GATE_CLEAR - 1e-9, n_top
    assert p_bot - PSD_TOP_BAND[0] >= PSD_GATE_CLEAR - 1e-9, p_bot
    assert lo_gate - 0.18 >= PSD_GATE_CLEAR - 1e-9, \
        f"pSD.j1 low: lowest gate {lo_gate}"
    print(f"upper pSD -> y {PSD_TOP_BAND[0]}..{PSD_TOP_BAND[1]} "
          f"(NFET gate top {n_top:.3f}, PFET gate bottom {p_bot:.3f}, "
          f"lowest gate {lo_gate:.3f})")


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
    dip = halo & db.Region(db.Box(left, 0, right, int(WELL_BOT * DBU)))
    assert dip.is_empty(), f"PMOS Activ needs a well jog below {WELL_BOT}"
    new = band + halo
    new -= nmos.sized(enc)
    new -= ptap.sized(enc)
    new.merge()

    assert (halo - new).is_empty(), "NW.c1"
    assert (new & nmos.sized(enc)).is_empty(), "NW.d1"
    assert (new & ptap.sized(enc)).is_empty(), "NW.f1"
    nb = new.bbox()
    assert (nb.left, nb.right, nb.top) == (left, right, top), nb
    assert nb.bottom == int(WELL_BOT * DBU), nb.bottom
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


# M1.e repair, library M1E_EDITS style (layout_retarget.py): the RESET_B
# pin pad bottom (y 1.68, x 3.425..4.545 in the final frame) faces the top
# edge of the wire below (y 1.48) at 0.20 um; the x-map stretched their
# parallel run past 1.0 um.  Raise the pad bottom to 1.70 -> 0.22 um (M1.e).
# The pad's poly contact sits at y >= 2.56, far above the trim.
M1_EDITS = [(3.425, 1.68, 4.545, 1.70)]


def fix_m1e_site(cell, lay):
    ly = cell.layout()
    conts = [s.dbbox() for s in cell.each_shape(ly.layer(6, 0))]
    for lnum in ((8, 0), (8, 2)):
        li = ly.layer(*lnum)
        r = db.Region(cell.shapes(li)).merged()
        texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
        before = r.count()
        kept = [cb for cb in conts
                if (db.Region(um_box(cb.left - 0.05, cb.bottom - 0.05,
                                     cb.right + 0.05, cb.top + 0.05))
                    - r).is_empty()]
        for x0, y0, x1, y1 in M1_EDITS:
            box = db.Region(um_box(x0, y0, x1, y1))
            assert (r & box).area() == box.area(), f"edit {x0},{y0} not in M1"
            for cb in kept:
                assert (db.Region(um_box(cb.left - 0.06, cb.bottom - 0.06,
                                         cb.right + 0.06, cb.top + 0.06))
                        & box).is_empty(), "edit near a contact"
            r -= box
        assert r.count() == before, "edit split or removed a polygon"
        if lnum == (8, 0):
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
    print(f"applied {len(M1_EDITS)} M1.e edit(s)")


def pin_report(cell, lay, W):
    ly = cell.layout()
    lpin, ltxt = ly.layer(8, 2), ly.layer(8, 25)
    texts = [(s.text.string, s.text.x / DBU, s.text.y / DBU)
             for s in cell.shapes(ltxt).each() if s.is_text()]
    pins = db.Region(cell.shapes(lpin)).merged()
    out = []
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
        ht = [round(0.21 + k * 0.42, 3) for k in range(0, 20)
              if b.bottom / DBU - 1e-9 <= 0.21 + k * 0.42 <= b.top / DBU + 1e-9]
        out.append(dict(pin=label, x=(lo, hi),
                        y=(b.bottom / DBU, b.top / DBU),
                        v_tracks=vt, h_tracks=ht))
    return out


def main():
    src = db.Layout()
    src.read(str(rt.LV_GDS))
    lay = {k: src.layer(*v) for k, v in rt.LAYERS.items()}
    all_cells = [src.cell(ci.cell_index()) for ci in src.each_cell()]

    gband = rt.band(src, all_cells, lay)
    total, dchan = library_total_insert(src, lay, all_cells, gband)
    ymap = build_custom_ymap(gband, total)
    # analyse()'s NMOS guard tests against CUT[0]; our custom cut is above
    # every NMOS Activ top of this cell
    rt.CUT[0], rt.CUT[1], rt.CUT[2], rt.CUT[3] = CUT_LO, 0.0, 0.0, 0.0

    cell = src.cell(CELL_LV)
    assert cell is not None
    remove_fingers(cell, lay)

    info, why = rt.analyse(src, cell, gband)
    assert info is not None, f"retarget refuses the cell: {why}"
    xmap, _libymap = rt.build_maps(info, gband, dchan)

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

    restore_fingers(cell, lay, xmap)
    rebuild_upper_psd(cell, lay, W)
    rebuild_nwell(cell, lay, W)
    retile_rail_contacts(cell, lay, W)
    fix_m1e_site(cell, lay)
    for r in pin_report(cell, lay, W):
        on = "ON-TRACK" if r["v_tracks"] else "OFF-TRACK"
        print(f"pin {r['pin']:8s} x {r['x'][0]:.3f}..{r['x'][1]:.3f} "
              f"y {r['y'][0]:.3f}..{r['y'][1]:.3f}  {on}  v={r['v_tracks']}")

    keep = cell.cell_index()
    for ci in [c.cell_index() for c in src.each_cell()]:
        if ci != keep:
            src.delete_cell(ci)
    cell.name = CELL_HV
    OUT.parent.mkdir(parents=True, exist_ok=True)
    src.write(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
