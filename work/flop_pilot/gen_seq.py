#!/usr/bin/env python3
"""Parameterized thick-oxide retarget for the undrawn sequential cells.

Generalizes gen_dfrbpq.py (the sg13g2_hv_dfrbpq_1 pilot) to the remaining
flip-flops.  Per cell this script:

  1. removes every p+ Activ finger / neck that butts the VDD rail tap
     (auto-derived: components of the Activ in a probe band just below the
     tap, cut by the deepest rectangle that stays inside the polygon,
     does not split the sub-tap Activ, and touches no gate);  six of the
     seven cells draw the tap strip merged into the device polygon, so the
     cut also separates the tap into its own straddling strip;
  2. applies the library retarget with a per-cell y-map: rail insert
     D_RAIL chosen so the highest NMOS Activ tops out at exactly 1.950 um
     (0.62 below the strict 2.570 well bottom), the balance of the
     library's 0.975 um total insert moved to a channel-cut band above all
     NMOS Activ -- template invariants asserted;
  3. re-extends the fingers to y = 6.99 (butted junction, shipped
     sg13g2_hv_slgcp_1 convention);
  4. rebuilds the upper pSD to the template band 2.635..6.92, plus -- for
     the cells with W=1.0/1.12 PMOS channels reaching down to mapped
     y = 2.984 -- an automatic local jog to 0.40 below the lowest such
     gate (pSD.i1), asserted 0.40 clear of all NFET gates and n+ Activ;
  5. rebuilds the N-well with fix_well_nwc1.py's strict construction
     (overhang +-0.62, bottom 2.570, 0.62 halos); where the low PMOS
     channels force it, the well dips below 2.570 (allowed by the
     convention when >= 0.62 from the cell edges), asserted clear of
     NMOS Activ + 0.62 (NW.d1);
  6. re-tiles rail tap contacts onto site centres (fix_rail_contacts.py
     guards);
  7. auto-repairs M1.e (0.22 um space at > 1.0 um parallel run; every M1
     line is >= 0.16 wide so the deck's width predicate is always true)
     by receding one facing edge with the pilot's guards: grid, no rail,
     no split, M1.a/M1.b preserved, contact enclosures preserved, pin
     labels still on their pins and pins still on a 0.48 track;
  8. asserts every contact is 0.07-enclosed by Activ or GatPoly, and
     prints the pin/track report.

Usage: python3 gen_seq.py <hv_cell_name | all>
Writes work/flop_pilot/<hv_cell>.gds (single top cell), nothing else.
"""
import pathlib
import sys

import klayout.db as db

WORK = pathlib.Path("/foss/designs/sg13g2_stdcell_hv/work")
sys.path.insert(0, str(WORK))
import layout_retarget as rt                                   # noqa: E402

HERE = WORK / "flop_pilot"
DBU = rt.DBU
GRID = rt.GRID

ROW_H = 7.14
SITE = 0.48
TAP_BOT = 6.99
TAP_TOP = 7.29
PSD_BAND = (2.635, 6.92)
PSD_EDGE = 0.07
WELL_OVER = 0.62
WELL_BOT = 2.570
NW_STRICT = 0.62
PSD_GATE_CLEAR = 0.40
CONT = 0.16
ENC_ACTIV = 0.07
ENC_M1 = 0.09
SP_GAT = 0.11
SP_CONT = 0.18
M1_MIN_W = 0.16
M1_MIN_S = 0.18
M1E_S = 0.22
M1E_RUN = 1.0
D_PSD = 0.10
ALLOW_RESIDUAL = True     # debug: keep going despite residual M1.e
LV_TAP_BOT = 3.63          # thin-oxide VDD tap Activ bottom
FINGER_PROBE = (3.605, 3.625)
PMOS_TOP_MAX = 3.5417      # mapped top <= 6.78 -> 0.21 Act.b gap to the tap

# cell name -> (D_RAIL, (CUT_LO, CUT_HI));  NMOS top 1.78 -> 0.17, 1.79 -> 0.16
CELLS = {
    "sg13g2_hv_dfrbp_1":   (0.17, (1.79, 1.84)),
    "sg13g2_hv_dfrbpq_2":  (0.16, (1.79, 1.84)),
    "sg13g2_hv_dfrbp_2":   (0.16, (1.79, 1.84)),
    "sg13g2_hv_sdfrbpq_1": (0.16, (1.79, 1.84)),
    "sg13g2_hv_sdfrbp_1":  (0.16, (1.79, 1.84)),
    "sg13g2_hv_sdfrbpq_2": (0.16, (1.79, 1.84)),
    "sg13g2_hv_sdfrbp_2":  (0.16, (1.79, 1.84)),
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


def library_total_insert(src, lay, all_cells, gband):
    Y0, T, rail_bot, _ = gband
    need = 0.0
    for c in all_cells:
        psd = [s.dbbox() for s in c.shapes(lay["psd"]).each()]
        if psd:
            need = max(need, rt.PSD_ENC_TGO - (Y0 - min(b.bottom for b in psd)))
    dchan = max(0.0, snap(need))
    ms = [(c, rt.channel_metrics(c, lay)) for c in all_cells]
    ms = [(c, m) for c, m in ms if m and m[1] is not None]
    best = None
    for thr in sorted({m[1] for _, m in ms}):
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
    return snap(d_rail + d_nw + rt.TRACK_PAD + d_psd + dchan), dchan


def build_ymap(gband, total, d_rail, cut):
    Y0, T, _, _ = gband
    cut_lo, cut_hi = cut
    d_cut = snap(total - d_rail - D_PSD)
    assert d_cut > 0
    ysegs = [
        (0.25, 0.35, 1.0 + d_rail / 0.10),
        (cut_lo, cut_hi, 1.0 + d_cut / (cut_hi - cut_lo)),
        (Y0 - 0.05, Y0, 1.0 + D_PSD / 0.05),
        (Y0, T, rt.KP),
    ]
    ymap = rt.PWL(ysegs)
    for src_y, want in ((3.63, TAP_BOT), (3.93, TAP_TOP), (3.56, 6.825),
                        (4.00, 7.36), (3.60, PSD_BAND[1]), (4.17, 7.53),
                        (Y0, snap(Y0 + total))):
        got = rt.snap_dbu(ymap(src_y)) / DBU
        assert abs(got - want) < 1e-9, (src_y, got, want)
    return ymap


def auto_fingers(cell, lay):
    """Find and remove the butting fingers/necks; return removal boxes."""
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    probe = db.Region(um_box(-1000, FINGER_PROBE[0], 1000, FINGER_PROBE[1]))
    below = db.Region(um_box(-1000, -1000, 1000, LV_TAP_BOT))
    removed = []
    for P in [p.dup() for p in act.each_merged()]:
        preg = db.Region(P)
        necks = (preg & probe).merged()
        if necks.is_empty():
            continue
        for n in necks.each():
            nb = n.bbox()
            x0, x1 = nb.left / DBU, nb.right / DBU
            ys = sorted({pt.y / DBU for pt in P.each_point_hull()
                         if pt.y / DBU < FINGER_PROBE[0]}, reverse=True)
            base = (preg & below).merged().count()
            ylo = None
            for y in ys:               # highest legal cut wins
                rect = db.Region(um_box(x0, y, x1, LV_TAP_BOT))
                if (preg & rect).area() != rect.area():
                    continue
                if not (rect & gat).is_empty():
                    continue
                if ((preg - rect) & below).merged().count() != base:
                    continue
                ylo = y
                break
            assert ylo is not None, f"no legal cut for neck {nb}"
            removed.append((x0, ylo, x1, LV_TAP_BOT))
    assert removed, "no butting fingers found?"
    r = act.dup()
    for x0, y0, x1, y1 in removed:
        r -= db.Region(um_box(x0, y0, x1, y1))
    # post-condition: no device Activ close to the tap band any more
    for p in r.each_merged():
        b = p.bbox()
        top, bot = b.top / DBU, b.bottom / DBU
        if bot < 3.5:                       # device-side polygon
            assert top <= PMOS_TOP_MAX + 1e-9, \
                f"activ top {top} still too close to the tap"
    cell.shapes(li).clear()
    for p in r.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)
    for x0, y0, x1, y1 in removed:
        print(f"  cut finger x {x0:.3f}..{x1:.3f} y {y0:.3f}..{y1:.3f}")
    return removed


def restore_fingers(cell, lay, xmap, removed):
    li = lay["activ"]
    act = db.Region(cell.shapes(li)).merged()
    texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
    for x0, y0, x1, y1 in removed:
        mx0, mx1 = snap(xmap(x0)), snap(xmap(x1))
        probe = db.Region(um_box(mx0 + 0.01, 0.5, mx1 - 0.01, TAP_BOT - 0.01))
        pieces = (act & probe).merged()
        assert not pieces.is_empty(), f"no body under finger {mx0}..{mx1}"
        body_top = max(p.bbox().top for p in pieces.each()) / DBU
        assert 2.6 < body_top < TAP_BOT - 0.2, (mx0, body_top)
        act.insert(um_box(mx0, snap(body_top - 0.10), mx1, TAP_BOT))
        print(f"  finger -> x {mx0:.3f}..{mx1:.3f} "
              f"y {snap(body_top - 0.10):.3f}..{TAP_BOT}")
    act.merge()
    cell.shapes(li).clear()
    for p in act.each_merged():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)


def rebuild_upper_psd(cell, lay, W):
    ly = cell.layout()
    li = lay["psd"]
    low, texts = [], []
    for s in cell.shapes(li).each():
        if s.is_text():
            texts.append(s.text.dup())
        elif s.dbbox().bottom < 1.0:
            low.append(s.polygon)
    assert low, "no low pSD band?"
    act = region_of(cell, ly.layer(1, 0))
    gat = region_of(cell, ly.layer(5, 0))
    gates = (act & gat).merged()
    n_gates = [g.bbox() for g in gates.each() if g.bbox().top / DBU < ROW_H / 2]
    p_gates = [g.bbox() for g in gates.each() if g.bbox().top / DBU >= ROW_H / 2]
    lo_gate = min(b.bottom for b in n_gates + p_gates) / DBU
    n_top = max(b.top for b in n_gates) / DBU
    assert PSD_BAND[0] - n_top >= PSD_GATE_CLEAR - 1e-9, n_top
    assert lo_gate - 0.18 >= PSD_GATE_CLEAR - 1e-9, lo_gate

    new = db.Region(um_box(-PSD_EDGE, PSD_BAND[0], W + PSD_EDGE, PSD_BAND[1]))
    lows = [b for b in p_gates
            if b.bottom / DBU < PSD_BAND[0] + PSD_GATE_CLEAR]
    if lows:
        jx0 = snap(min(b.left for b in lows) / DBU - PSD_GATE_CLEAR)
        jx1 = snap(max(b.right for b in lows) / DBU + PSD_GATE_CLEAR)
        jy0 = snap(min(b.bottom for b in lows) / DBU - PSD_GATE_CLEAR)
        # round down to be safe on the 5nm grid
        while jy0 > min(b.bottom for b in lows) / DBU - PSD_GATE_CLEAR + 1e-12:
            jy0 = snap(jy0 - GRID)
        jog = db.Region(um_box(jx0, jy0, jx1, PSD_BAND[0] + 0.01))
        # 0.40 clear of every NFET gate and n+ Activ (square worst case)
        nact = act - new - jog                     # n+ = activ outside p+
        near = jog.sized(int((PSD_GATE_CLEAR - 0.001) * DBU))
        low_nact = db.Region()
        for p in nact.each():
            if p.bbox().top / DBU < ROW_H / 2 and p.bbox().bottom / DBU > 0.2:
                low_nact.insert(p)
        assert (near & low_nact).is_empty(), "pSD jog too close to n+ Activ"
        new += jog
        print(f"  pSD jog x {jx0:.3f}..{jx1:.3f} bottom {jy0:.3f} "
              f"(lowest PFET gate {min(b.bottom for b in lows) / DBU:.3f})")
    cell.shapes(li).clear()
    for p in low:
        cell.shapes(li).insert(p)
    for p in new.merged().each():
        cell.shapes(li).insert(p)
    for t in texts:
        cell.shapes(li).insert(t)
    # final pSD.i1 assert: every PFET gate 0.40-enclosed from below
    psd = region_of(cell, li)
    for b in p_gates:
        need = db.Region(db.Box(b.left, b.bottom - int(PSD_GATE_CLEAR * DBU),
                                b.right, b.bottom))
        assert (need - psd).is_empty(), f"pSD.i1 at gate {b}"


def rebuild_nwell(cell, lay, W):
    ly = cell.layout()
    li = lay["nwell"]
    old = db.Region(cell.shapes(li)).merged()
    top = old.bbox().top
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
    if not dip.is_empty():
        dbb = dip.bbox()
        assert dbb.left >= enc and dbb.right <= int(W * DBU) - enc, \
            f"well dip too close to the cell edge: {dbb}"
        print(f"  well dip to {dbb.bottom / DBU:.3f} "
              f"x {dbb.left / DBU:.3f}..{dbb.right / DBU:.3f}")
    new = band + halo
    new -= nmos.sized(enc)
    new -= ptap.sized(enc)
    new.merge()
    assert (halo - new).is_empty(), "NW.c1"
    assert (new & nmos.sized(enc)).is_empty(), "NW.d1"
    assert (new & ptap.sized(enc)).is_empty(), "NW.f1"
    nb = new.bbox()
    assert (nb.left, nb.right, nb.top) == (left, right, top), nb
    assert nb.bottom <= int(WELL_BOT * DBU), nb.bottom
    for p in new.each():
        for pt in p.each_point_hull():
            assert pt.x % 5 == 0 and pt.y % 5 == 0, pt
    cell.shapes(li).clear()
    for p in new.each_merged():
        cell.shapes(li).insert(p)


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
        print(f"  rail y={rail}: {len(shapes)} -> {len(kept)} contacts")


def m1e_check(m1):
    """The deck's M1.e, verbatim: separation of Metal1 to lines wider than
    0.30 um (opening by M1_e_w/2 = 0.15) below 0.22 um at > 1.0 um run."""
    wide = m1.sized(-150).sized(150)
    return m1.separation_check(wide, int(M1E_S * DBU), False,
                               db.Region.Euclidian, None,
                               int(M1E_RUN * DBU) + 1, None)


def track_state(pins_reg, texts, W):
    st = {}
    for label, tp in texts:
        grp = next((p for p in pins_reg.each() if p.bbox().contains(tp)), None)
        if grp is None:
            st[label] = None
            continue
        b = grp.bbox()
        st[label] = any(b.left <= int(round((SITE / 2 + k * SITE) * DBU)) <= b.right
                        for k in range(int(W / SITE) + 1))
    return st


def widen_offtrack_pins(cell, lay, W):
    """grid_align_pins.py policy: extend an off-track pin sideways to the
    nearest 0.48 track, if the new metal keeps M1.b to everything else."""
    ly = cell.layout()
    lm1, lpin, ltxt = ly.layer(8, 2 - 2), ly.layer(8, 2), ly.layer(8, 25)
    texts = [(s.text.string, db.Point(s.text.x, s.text.y))
             for s in cell.shapes(ltxt).each() if s.is_text()]
    for label, tp in texts:
        if label in ("VDD", "VSS"):
            continue
        pins = db.Region(cell.shapes(lpin)).merged()
        m1 = db.Region(cell.shapes(lm1)).merged()
        grp = next((p for p in pins.each() if p.bbox().contains(tp)), None)
        assert grp is not None, label
        b = grp.bbox()
        tracks = [int(round((SITE / 2 + k * SITE) * DBU))
                  for k in range(int(W / SITE) + 1)]
        if any(b.left <= t <= b.right for t in tracks):
            continue
        lt = max((t for t in tracks if t < b.left), default=None)
        rt_ = min((t for t in tracks if t > b.right), default=None)
        cands = []
        if lt is not None:
            cands.append(db.Box(lt - 40, b.bottom, b.left + 5, b.top))
        if rt_ is not None:
            cands.append(db.Box(b.right - 5, b.bottom, rt_ + 40, b.top))
        cands.sort(key=lambda c: c.width())
        done = False
        for ext in cands:
            er = db.Region(ext)
            m1_new = (m1 + er).merged()
            if m1_new.count() != m1.count():
                continue                      # merged a foreign wire: short
            if not m1_new.space_check(int(M1_MIN_S * DBU)).is_empty():
                continue
            if m1e_check(m1_new).count() > m1e_check(m1).count():
                continue                      # no NEW wide-line violations
            pins_new = (pins + er).merged()
            for li_, reg in ((lm1, m1_new), (lpin, pins_new)):
                txs = [s.text.dup() for s in cell.shapes(li_).each()
                       if s.is_text()]
                cell.shapes(li_).clear()
                for p in reg.each():
                    cell.shapes(li_).insert(p)
                for t in txs:
                    cell.shapes(li_).insert(t)
            print(f"  widened pin {label} onto track "
                  f"({ext.left / DBU:.3f}..{ext.right / DBU:.3f})")
            done = True
            break
        assert done, f"cannot put pin {label} on a track"


def repair_m1e(cell, lay, W):
    """Open every deck-M1.e gap by receding one facing edge, guarded."""
    ly = cell.layout()
    lm1, lpin, ltxt = ly.layer(8, 0), ly.layer(8, 2), ly.layer(8, 25)
    conts = [s.dbbox() for s in cell.each_shape(ly.layer(6, 0))]
    g = int(GRID * DBU)
    texts = [(s.text.string, db.Point(s.text.x, s.text.y))
             for s in cell.shapes(ltxt).each() if s.is_text()]

    def regions():
        return (db.Region(cell.shapes(lm1)).merged(),
                db.Region(cell.shapes(lpin)).merged())

    m1_0, pins_0 = regions()
    base_tracks = track_state(pins_0, texts, W)

    def guards_ok(m1_old, m1_new, pins_new):
        if m1_new.count() != m1_old.count():
            return False
        if not m1_new.width_check(int(M1_MIN_W * DBU)).is_empty():
            return False
        if not m1_new.space_check(int(M1_MIN_S * DBU)).is_empty():
            return False
        for cb in conts:
            r = db.Region(um_box(cb.left - 0.05, cb.bottom - 0.05,
                                 cb.right + 0.05, cb.top + 0.05))
            if (r - m1_old).is_empty() and not (r - m1_new).is_empty():
                return False
        st = track_state(pins_new, texts, W)
        for label, ok in st.items():
            if ok is None:
                return False                    # label fell off its pin
            if base_tracks[label] and not ok:
                return False                    # was on-track, now off
        return True

    fixed = 0
    for _ in range(12):
        m1, pins = regions()
        viol = m1e_check(m1)
        if viol.is_empty():
            break
        progress = False
        for ep in viol.each():
            bb = ep.bbox()
            horiz = bb.width() < bb.height()      # gap is thin in x
            span = bb.width() if horiz else bb.height()
            deficit = int(M1E_S * DBU) - span
            if deficit <= 0:
                continue
            if horiz:
                cands = [db.Box(bb.right, bb.bottom, bb.right + deficit, bb.top),
                         db.Box(bb.left - deficit, bb.bottom, bb.left, bb.top)]
            else:
                cands = [db.Box(bb.left, bb.top, bb.right, bb.top + deficit),
                         db.Box(bb.left, bb.bottom - deficit, bb.right, bb.bottom)]
            done = False
            for cbox in cands:
                strip = db.Box((cbox.left // g) * g, (cbox.bottom // g) * g,
                               -((-cbox.right) // g) * g,
                               -((-cbox.top) // g) * g)
                sr = db.Region(strip)
                if (sr & m1).is_empty():
                    continue
                touches_rail = False
                for p in m1.each():
                    pb = p.bbox()
                    if not (db.Region(p) & sr).is_empty() and \
                       (pb.bottom < 0 or pb.top > int(ROW_H * DBU)):
                        touches_rail = True
                if touches_rail:
                    continue
                m1_new = m1 - sr
                pins_new = pins - sr
                if not guards_ok(m1, m1_new, pins_new):
                    continue
                for li_, reg in ((lm1, m1_new), (lpin, pins_new)):
                    txs = [s.text.dup() for s in cell.shapes(li_).each()
                           if s.is_text()]
                    cell.shapes(li_).clear()
                    for p in reg.each():
                        cell.shapes(li_).insert(p)
                    for t in txs:
                        cell.shapes(li_).insert(t)
                fixed += 1
                progress = True
                done = True
                break
            if done:
                break
        if not progress:
            break
    m1, _ = regions()
    resid = m1e_check(m1)
    if not resid.is_empty():
        print("  RESIDUAL M1.e pairs:")
        for ep in resid.each():
            print(f"    {ep.bbox()}")
        if not ALLOW_RESIDUAL:
            raise AssertionError(f"unrepairable M1.e ({resid.count()} pairs)")
    print(f"  m1e auto-repairs: {fixed}")


def final_checks(cell, lay, W):
    ly = cell.layout()
    act = region_of(cell, ly.layer(1, 0))
    gat = region_of(cell, ly.layer(5, 0))
    cover = act + gat
    cover.merge()
    conts = region_of(cell, ly.layer(6, 0))
    # euclidean enclosure, as the deck's Cnt.c/Cnt.d measure it
    viol = cover.enclosing_check(conts, int(ENC_ACTIV * DBU))
    assert viol.is_empty(), \
        f"contact landing lost: {[e.bbox() for e in viol.each()]}"
    # and no contact may float outside the cover entirely
    assert (conts - cover).is_empty(), "floating contact"


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
        vt = [round(SITE / 2 + k * SITE, 3) for k in range(int(W / SITE) + 1)
              if b.left / DBU - 1e-9 <= SITE / 2 + k * SITE <= b.right / DBU + 1e-9]
        out.append(dict(pin=label, x=(b.left / DBU, b.right / DBU),
                        y=(b.bottom / DBU, b.top / DBU), v_tracks=vt))
    return out


def generate(hv_name):
    d_rail, cut = CELLS[hv_name]
    lv_name = hv_name.replace("sg13g2_hv_", "sg13g2_")
    print(f"### {hv_name}  (from {lv_name}, d_rail {d_rail}, cut {cut})")
    src = db.Layout()
    src.read(str(rt.LV_GDS))
    lay = {k: src.layer(*v) for k, v in rt.LAYERS.items()}
    all_cells = [src.cell(ci.cell_index()) for ci in src.each_cell()]
    gband = rt.band(src, all_cells, lay)
    total, dchan = library_total_insert(src, lay, all_cells, gband)
    ymap = build_ymap(gband, total, d_rail, cut)
    # analyse()'s guard is "NMOS top >= CUT[0]"; our cut band starts exactly
    # at the NMOS top (a vertex at the segment start maps unstretched), so
    # give the advisory check a 10 nm margin -- the real constraints are
    # asserted in build_ymap and the post-map checks.
    rt.CUT[0], rt.CUT[1], rt.CUT[2], rt.CUT[3] = cut[0] + 0.01, 0.0, 0.0, 0.0

    cell = src.cell(lv_name)
    assert cell is not None, lv_name
    # NMOS-top precondition for the chosen d_rail
    nw = db.Region(cell.shapes(lay["nwell"])).merged()
    gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
    H = 3.78
    nmos_top = 0.0
    for s in cell.shapes(lay["activ"]).each():
        if s.is_text():
            continue
        b = s.dbbox()
        if b.width() <= 0 or b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top:
            continue
        if not rt.is_pmos_dev(b, nw, gat):
            nmos_top = max(nmos_top, b.top)
    assert abs(snap(nmos_top + d_rail) - (WELL_BOT - NW_STRICT)) < 1e-9, \
        f"d_rail {d_rail} does not put NMOS top {nmos_top} at 1.95"

    removed = auto_fingers(cell, lay)
    info, why = rt.analyse(src, cell, gband)
    assert info is not None, f"retarget refuses: {why}"
    xmap, _ = rt.build_maps(info, gband, dchan)
    rt.transform_cell(src, cell, xmap, ymap, lay, info)
    rt.retile_contacts(cell, lay, xmap, ymap, src)
    rt.close_activ_notches(cell, lay)
    pad = rt.pad_to_site(cell, lay)
    rt.add_tgo(cell, lay)

    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()][0]
    W = bnd.width()
    assert abs(W / SITE - round(W / SITE)) < 1e-6, W
    assert abs(bnd.height() - ROW_H) < 1e-9
    print(f"  cell {W:.2f} x 7.14 um = {round(W / SITE)} sites (pad {pad:.3f})")

    restore_fingers(cell, lay, xmap, removed)
    rebuild_upper_psd(cell, lay, W)
    rebuild_nwell(cell, lay, W)
    retile_rail_contacts(cell, lay, W)
    widen_offtrack_pins(cell, lay, W)
    repair_m1e(cell, lay, W)
    final_checks(cell, lay, W)
    for r in pin_report(cell, lay, W):
        on = "ON-TRACK" if r["v_tracks"] else "OFF-TRACK"
        print(f"  pin {r['pin']:8s} x {r['x'][0]:.3f}..{r['x'][1]:.3f} "
              f"y {r['y'][0]:.3f}..{r['y'][1]:.3f}  {on}")

    keep = cell.cell_index()
    for ci in [c.cell_index() for c in src.each_cell()]:
        if ci != keep:
            src.delete_cell(ci)
    cell.name = hv_name
    out = HERE / f"{hv_name}.gds"
    src.write(str(out))
    print(f"  wrote {out}")
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(CELLS) if which == "all" else [which]
    for n in names:
        generate(n)
