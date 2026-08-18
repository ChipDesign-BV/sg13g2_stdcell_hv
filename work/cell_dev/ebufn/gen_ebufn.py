#!/usr/bin/env python3
"""Generate sg13g2_hv_ebufn_2 / sg13g2_hv_ebufn_8 from the thin-oxide cells.

The library retarget (work/layout_retarget.py) skipped both cells for one
reason: the output-stage PMOS source connects to VDD by butting its p+
Activ straight into the n+ VDD rail tap through a single neck, so the PMOS
Activ top reaches the rail band and the y-map cannot scale the band
without moving the rail.  Same as reason 1 of work/flop_pilot/
gen_dfrbpq.py, and handled the same way:

  * the neck is removed before the map (asserted to be exactly the
    expected box, no contacts on it), leaving a flat-topped PMOS body;
  * the standard LIBRARY maps are applied (unlike dfrbpq no custom y-map
    is needed: both cells' NMOS Activ tops -- 1.28 / 1.36 um -- are below
    the library channel cut at 1.595, so every template feature lands
    exactly where the shipped library puts it, asserted below);
  * the neck is re-drawn afterwards in the thick-oxide frame from the
    (now 2.4x taller) PMOS body top up to y = 6.99 where it merges with
    the tap strip -- identical convention to the shipped
    sg13g2_hv_slgcp_1 (p+ under the pSD cover to 6.92, n+ for the last
    70 nm; the KLayout LVS deck connects the junction through
    psd_ntap_abutt);
  * the mapped upper pSD is rebuilt to the template band (2.635..6.92),
    the N-well to the strict convention of work/fix_well_nwc1.py
    (overhang +-0.62, bottom 2.570, 0.62 halos), and the rail tap
    contacts re-tiled on the site-centred 0.48 um grid as in
    work/fix_rail_contacts.py.

Device widths: the map multiplies every PMOS finger width by 2.40 and
leaves NMOS alone, which reproduces the HV CDL exactly:
  ebufn_2: PMOS 1.12 -> 2.690 (x4 output), 1.00 -> 2.400 (x2 pre-driver);
           NMOS 0.74 (x4 output), 0.64 (x2 pre-driver)  [w=5.380 ng=2,
           2.400 ng=1, 1.480 ng=2, 0.640 ng=1 in the CDL]
  ebufn_8: PMOS 1.12 -> 2.690 (x16 output + x3 pre-driver = 21.520 ng=8,
           5.380 ng=2, 2.690 ng=1); NMOS 0.74 (x16 output + x3
           pre-driver = 5.920 ng=8, 1.480 ng=2, 0.740 ng=1)
LVS runs with --combine_devices, so parallel fingers summing to the CDL
width match.

Output: work/cell_dev/ebufn/sg13g2_hv_ebufn_{2,8}.gds (single top cell).
Nothing outside work/cell_dev/ebufn/ is written.
"""
import pathlib
import sys

import klayout.db as db

WORK = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work")
sys.path.insert(0, str(WORK))
import layout_retarget as rt                                   # noqa: E402

HERE = WORK / "cell_dev" / "ebufn"

DBU = rt.DBU
GRID = rt.GRID

# Per cell: the one p+ Activ neck that butts the VDD tap in the LV cell.
CELLS = {
    "sg13g2_ebufn_2": dict(hv="sg13g2_hv_ebufn_2",
                           necks=[(1.870, 3.180, 2.170, 3.630)]),
    "sg13g2_ebufn_8": dict(hv="sg13g2_hv_ebufn_8",
                           necks=[(7.825, 3.210, 8.125, 3.630)]),
}

ROW_H = 7.14
SITE = 0.48
TAP_BOT = 6.99                  # VDD tap Activ bottom (template)
PSD_TOP_BAND = (2.635, 6.92)    # template upper pSD band
PSD_EDGE = 0.07                 # pSD sideways overhang at the cell edge
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


def library_cut(src, lay, all_cells, gband):
    """The library's channel cut and inserts, derived as rt.main() does."""
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
    print(f"library map: band {Y0:.3f}..{T:.3f}, cut {cut_y:.3f}, "
          f"d_rail {d_rail:.3f} d_nw {d_nw:.3f} track_pad {rt.TRACK_PAD:.3f} "
          f"d_psd {d_psd:.3f} dchan {dchan:.3f}")
    return cut_y, d_nw, d_psd, d_rail, dchan


def check_template_ymap(ymap):
    """The standard map must land every template feature where the shipped
    library puts it (rails, tap Activ, pSD top, NWell top)."""
    for src_y, want in ((3.63, TAP_BOT), (3.93, 7.29),
                        (3.56, 6.825), (4.00, 7.36),
                        (3.60, PSD_TOP_BAND[1]), (4.17, 7.53)):
        got = rt.snap_dbu(ymap(src_y)) / DBU
        assert abs(got - want) < 1e-9, (src_y, got, want)


def remove_necks(cell, lay, necks):
    li = lay["activ"]
    r = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    for x0, y0, x1, y1 in necks:
        box = db.Region(um_box(x0, y0, x1, y1))
        got = (r & box).area()
        assert got == box.area(), \
            f"neck {x0},{y0},{x1},{y1}: drawn area {got} != {box.area()}"
        r -= box
    cell.shapes(li).clear()
    for p in r.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)
    print(f"removed {len(necks)} butting neck(s)")


def restore_necks(cell, lay, xmap, necks):
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    add = []
    for x0, y0, x1, y1 in necks:
        mx0, mx1 = snap(xmap(x0)), snap(xmap(x1))
        probe = db.Region(um_box(mx0 + 0.01, 0.5, mx1 - 0.01, TAP_BOT - 0.01))
        pieces = (act & probe).merged()
        assert not pieces.is_empty(), f"no body under neck at {mx0}..{mx1}"
        body_top = max(p.bbox().top for p in pieces.each()) / DBU
        assert 2.6 < body_top < TAP_BOT - 0.2, (mx0, body_top)
        add.append(um_box(mx0, snap(body_top - 0.10), mx1, TAP_BOT))
        print(f"neck {x0:.3f}..{x1:.3f} -> x {mx0:.3f}..{mx1:.3f}, "
              f"y {snap(body_top - 0.10):.3f}..{TAP_BOT}")
    for b in add:
        act.insert(b)
    act.merge()
    cell.shapes(li).clear()
    for p in act.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)
    # The LV necks carry a VDD-strap contact (source tie from the M1 rail
    # stub).  The mapped contact must land back inside the restored Activ
    # with full Cnt enclosure, and keep its Metal1 cover.
    m1 = db.Region(cell.shapes(lay["metal1"])).merged()
    for b in add:
        fr = db.Region(b)
        for s in cell.shapes(lay["cont"]).each():
            cb = s.dbbox()
            if (db.Region(um_box(cb.left, cb.bottom, cb.right, cb.top))
                    & fr).is_empty():
                continue
            act_pad = um_box(cb.left - ENC_ACTIV, cb.bottom - ENC_ACTIV,
                             cb.right + ENC_ACTIV, cb.top + ENC_ACTIV)
            m1_pad = um_box(cb.left - 0.05, cb.bottom - 0.05,
                            cb.right + 0.05, cb.top + 0.05)
            assert (db.Region(act_pad) - act).is_empty(), \
                f"neck contact {cb} loses Activ enclosure"
            assert (db.Region(m1_pad) - m1).is_empty(), \
                f"neck contact {cb} loses Metal1 enclosure"
            print(f"neck contact {cb.left:.3f},{cb.bottom:.3f} kept "
                  f"(Activ+M1 enclosed)")


def rebuild_upper_psd(cell, lay, W):
    """Replace the mapped upper pSD with the template band."""
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
    assert top == int(7.53 * DBU), top
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
        out.append(dict(pin=label, x=(lo, hi),
                        y=(b.bottom / DBU, b.top / DBU), v_tracks=vt))
    return out


def gen(cell_lv, spec):
    print(f"=== {cell_lv} -> {spec['hv']}")
    src = db.Layout()
    src.read(str(rt.LV_GDS))
    lay = {k: src.layer(*v) for k, v in rt.LAYERS.items()}
    all_cells = [src.cell(ci.cell_index()) for ci in src.each_cell()]

    gband = rt.band(src, all_cells, lay)
    cut_y, d_nw, d_psd, d_rail, dchan = library_cut(src, lay, all_cells, gband)
    rt.CUT[0], rt.CUT[1], rt.CUT[2], rt.CUT[3] = cut_y, d_nw, d_psd, d_rail

    cell = src.cell(cell_lv)
    assert cell is not None
    remove_necks(cell, lay, spec["necks"])

    info, why = rt.analyse(src, cell, gband)
    assert info is not None, f"retarget refuses the cell: {why}"
    xmap, ymap = rt.build_maps(info, gband, dchan)
    check_template_ymap(ymap)

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

    restore_necks(cell, lay, xmap, spec["necks"])
    rebuild_upper_psd(cell, lay, W)
    rebuild_nwell(cell, lay, W)
    retile_rail_contacts(cell, lay, W)
    for r in pin_report(cell, lay, W):
        on = "ON-TRACK" if r["v_tracks"] else "OFF-TRACK"
        print(f"pin {r['pin']:8s} x {r['x'][0]:.3f}..{r['x'][1]:.3f} "
              f"y {r['y'][0]:.3f}..{r['y'][1]:.3f}  {on}  v={r['v_tracks']}")

    keep = cell.cell_index()
    for ci in [c.cell_index() for c in src.each_cell()]:
        if ci != keep:
            src.delete_cell(ci)
    cell.name = spec["hv"]
    out = HERE / f"{spec['hv']}.gds"
    src.write(str(out))
    print(f"wrote {out}")
    return out


def main():
    outs = [gen(lv, spec) for lv, spec in CELLS.items()]
    print("generated:", ", ".join(str(o) for o in outs))


if __name__ == "__main__":
    main()
