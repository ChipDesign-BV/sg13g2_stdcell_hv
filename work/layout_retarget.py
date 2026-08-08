#!/usr/bin/env python3
"""Retarget the thin-oxide standard cell layouts to thick-oxide devices.

The thin-oxide GDS is hand-drawn 2-D layout, not a regular template, so the
thick-oxide cells cannot be generated from a placement template without
rebuilding every cell by hand. What *can* be done exactly is a 1-D retarget:
a monotone piecewise-linear coordinate map applied to every vertex. Because a
monotone map never reorders or merges geometry, the circuit topology -- which
shape touches which -- is preserved, so the retargeted cell is LVS-equivalent
to the original by construction. Only the device dimensions change, which is
precisely what the thick-oxide transform is.

Two maps per cell:

  x:  each gate is widened 0.13 -> 0.45 um (DRC Gat.a3). The map is identity
      outside the gates, so the gaps between gates, and the 0.11 um contact-to-
      gate clearance, are carried over unchanged.

  y:  a slope-2.40 segment across the PMOS band scales every PMOS width by
      2.40. This works because a linear segment scales *every* sub-interval
      ending at the band top by the same factor, and in these cells all PMOS
      actives share a top edge. A second, small segment below the band adds the
      clearance the thick-oxide pSD enclosure rule needs (pSD.i1, 0.4 um inside
      ThickGateOx, against 0.3 um outside). The NMOS band is untouched, because
      NMOS widths do not change.

Contacts must not be stretched -- they are a fixed 0.16 um square. They are
removed before the map and re-tiled afterwards on the 0.34 um pitch inside the
new active, keeping the same x columns so no net changes.

Cells whose PMOS actives do not share a single top edge cannot be retargeted
this way: one linear segment cannot give them all the same scale factor. Those
cells are reported and skipped rather than silently mis-sized.
"""
import math, pathlib, sys
import klayout.db as db

LV_GDS = pathlib.Path(
    "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds")
OUT_GDS = pathlib.Path(
    "/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")

DBU = 1000                       # database units per micron
L_LV, L_HV = 0.13, 0.45          # gate length before / after
KP = 2.40                        # PMOS width factor, from work/vm_sweep.py
GRID = 0.005

CONT = 0.16                      # contact size, fixed by Cnt.a
CONT_PITCH = 0.36              # 0.16 contact + 0.20 space, for Cnt.b1 in tall arrays
CONT_ENC_ACT = 0.07              # Activ enclosure of Cont
PSD_ENC_TGO = 0.40               # pSD.i1, enclosure of PFET gate inside TGO
TGO_MARGIN = 0.27                # TGO.a, ThickGateOx extension over Activ
CUT = [None, 0.0, 0.0, 0.0]      # [cut y, NWell insert, pSD insert, rail insert]
GAT_B1 = 0.25                    # min space between unrelated 3.3 V gates
NW_D1_DIG = 0.31                 # NW.d1.dig, NWell to N+Activ inside TGO+DigiBnd
M1_E_S = 0.22                    # M1.e, space when a line is wide and runs far
M1_E_W = 0.30                    # M1.e, width above which a line counts as wide
M1_E_CR = 1.00                   # M1.e, parallel run above which it applies
M1_C1 = 0.05                     # Metal1 enclosure of Cont
M1_A = 0.16                      # M1.a, minimum Metal1 width
# Routing-grid quantisation. The tech LEF routes horizontally on 0.42 um and
# vertically on 0.48 um; the thin-oxide CoreSite is 0.48 x 3.78 (9 tracks).
# Geometry minimums alone gave 6.910 um = 16.45 tracks, so TRACK_PAD grows
# the mid-cell dead zone (the same place the NW.d1 clearance opened) to
# reach exactly 17 tracks, and pad_to_site() pads every cell width up to a
# SITE_W multiple so a placer can legally abut the cells on a site grid.
H_TRACK = 0.42                   # horizontal routing track pitch
SITE_W = 0.48                    # site width = vertical routing track pitch
TRACK_PAD = 0.230                # 6.910 + 0.230 = 7.140 = 17 x 0.42

LAYERS = {  # name -> (layer, datatype)
    "activ": (1, 0), "gatpoly": (5, 0), "cont": (6, 0),
    "metal1": (8, 0), "metal1_pin": (8, 2), "metal1_text": (8, 25),
    "psd": (14, 0), "nwell": (31, 0), "tgo": (44, 0), "bound": (189, 4),
    "digibnd": (16, 0), "via1": (19, 0),
}


def snap(v):
    return round(v / GRID) * GRID


def snap_dbu(v_um):
    """Micron value -> database units, snapped to the layout grid.

    Every mapped coordinate goes through this. The maps have non-integer
    slopes (0.45/0.13 and 2.40), so raw output lands off-grid and would both
    trip the OffGrid checks and put device widths a nanometre or two away from
    the netlist.
    """
    return int(round(round(v_um / GRID) * GRID * DBU))


def is_pmos_dev(b, nwell, gat):
    """A PMOS device Activ: inside NWell and with a gate crossing it.

    Excluding full-width Activ instead would drop the tie cells, whose PMOS
    spans the whole cell; requiring a gate is what actually distinguishes a
    device from an NWell tap, which has no poly over it.
    """
    inner = db.Box(int(b.left * DBU) + 1, int(b.bottom * DBU) + 1,
                   int(b.right * DBU) - 1, int(b.top * DBU) - 1)
    r = db.Region(inner)
    return not (r & nwell).is_empty() and not (r & gat).is_empty()


class PWL:
    """Monotone piecewise-linear map, built from (start, scale) segments."""

    def __init__(self, segs):
        # segs: sorted list of (lo, hi, scale); gaps between them are slope 1
        self.pts = []           # (in_lo, out_lo, scale)
        cur_in = -1e9
        cur_out = -1e9
        for lo, hi, sc in segs:
            self.pts.append((cur_in, cur_out, 1.0, lo))
            cur_out += (lo - cur_in)
            cur_in = lo
            self.pts.append((cur_in, cur_out, sc, hi))
            cur_out += (hi - lo) * sc
            cur_in = hi
        self.pts.append((cur_in, cur_out, 1.0, 1e9))

    def __call__(self, v):
        for in_lo, out_lo, sc, in_hi in self.pts:
            if v <= in_hi:
                return out_lo + (v - in_lo) * sc
        return v


def merged_x_intervals(region, dbu=DBU):
    """Merged gate x-intervals, each with its smallest constituent gate length.

    The length matters because not every gate is a minimum-length one: the
    delay cells and the sighold keeper use 0.5-1.0 um channels, which are
    already above the thick-oxide minimum and must not be stretched. Only
    intervals whose gates are shorter than L_HV get widened.
    """
    iv = []
    for p in region.each_merged():
        b = p.bbox()
        iv.append((b.left / dbu, b.right / dbu))
    iv.sort()
    out = []
    for a, b in iv:
        if out and a <= out[-1][1] + 1e-9:
            lo, hi, w = out[-1]
            out[-1] = (lo, max(hi, b), min(w, b - a))
        else:
            out.append((a, b, b - a))
    return out


def band(ly, cells, lay):
    """The library-wide PMOS band and channel insert.

    It has to be library-wide, not per cell. A standard cell library has one
    row height, and deriving the band from each cell's own geometry gave six
    different heights -- cells that cannot abut, which is not a standard cell
    library at all.

    The band stops below the VDD rail tap. A few cells run a PMOS active up
    into the rail; including the rail in the band would scale the tap itself
    and move the rail off the cell boundary, breaking abutment, so those cells
    are left out instead.
    """
    tops, bots, rails = [], [], []
    for c in cells:
        nwell = db.Region(c.shapes(lay["nwell"])).merged()
        gat = db.Region(c.shapes(lay["gatpoly"])).merged()
        bnd = [s.dbbox() for s in c.shapes(lay["bound"]).each()]
        if not bnd:
            continue
        W, H = bnd[0].width(), bnd[0].height()
        for s in c.shapes(lay["activ"]).each():
            b = s.dbbox()
            if b.width() <= 0:
                continue
            # A rail tap straddles the cell boundary; testing "spans the full
            # cell width" instead also catches the PMOS of narrow cells, which
            # then drags the band top down and breaks the whole calculation.
            if b.bottom < H - 1e-9 < b.top or b.bottom < -1e-9 < b.top:
                if b.top > H - 1e-9:
                    rails.append(b.bottom)
            elif is_pmos_dev(b, nwell, gat):
                tops.append(b.top)
                bots.append(b.bottom)
    # Take the highest: a few cells merge a PMOS Activ straight into the tap,
    # so those straddling shapes start much lower than the tap itself.
    rail_bot = max(rails)
    T = max(t for t in tops if t <= rail_bot + 1e-9)
    bots = [b for b in bots if b <= T + 1e-9]
    Y0 = min(bots)
    return Y0, T, rail_bot, sorted({round(b, 4) for b in bots})


def channel_metrics(cell, lay):
    """(max NMOS Activ top, min NWell bottom, min upper pSD bottom, min PMOS
    Activ bottom) -- what the thick-oxide clearance rules are measured from."""
    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()]
    if not bnd:
        return None
    H = bnd[0].height()
    nwr = db.Region(cell.shapes(lay["nwell"])).merged()
    gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
    ntop, pbot = 0.0, None
    for s in cell.shapes(lay["activ"]).each():
        b = s.dbbox()
        if b.width() <= 0:
            continue
        if b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top:
            continue
        if is_pmos_dev(b, nwr, gat):
            pbot = b.bottom if pbot is None else min(pbot, b.bottom)
        else:
            inner = db.Region(db.Box(int(b.left * DBU) + 1, int(b.bottom * DBU) + 1,
                                     int(b.right * DBU) - 1, int(b.top * DBU) - 1))
            if not (inner & gat).is_empty():
                ntop = max(ntop, b.top)
    nwb = min((s.dbbox().bottom for s in cell.shapes(lay["nwell"]).each()),
              default=None)
    psdb = min((s.dbbox().bottom for s in cell.shapes(lay["psd"]).each()
                if s.dbbox().bottom > 0.5), default=None)
    # The VSS rail tap is p+, so its pSD also has to clear the NFET gates --
    # from below. The thin-oxide layout leaves 0.30 um there, exactly what
    # pSD.j allows; pSD.j1 wants 0.40 um inside ThickGateOx.
    psd_lo_top = max((s.dbbox().top for s in cell.shapes(lay["psd"]).each()
                      if s.dbbox().bottom < 0.5), default=None)
    nbot = None
    for s in cell.shapes(lay["activ"]).each():
        b = s.dbbox()
        if b.width() <= 0:
            continue
        if b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top:
            continue
        if not is_pmos_dev(b, nwr, gat):
            inner = db.Region(db.Box(int(b.left * DBU) + 1, int(b.bottom * DBU) + 1,
                                     int(b.right * DBU) - 1, int(b.top * DBU) - 1))
            if not (inner & gat).is_empty():
                nbot = b.bottom if nbot is None else min(nbot, b.bottom)
    return ntop, nwb, psdb, pbot, psd_lo_top, nbot


def analyse(ly, cell, gband):
    """Everything the maps need, or a reason the cell cannot be retargeted."""
    lay = {k: ly.layer(*v) for k, v in LAYERS.items()}
    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()]
    if not bnd:
        return None, "no prBoundary"
    W, H = bnd[0].width(), bnd[0].height()

    activ = db.Region(cell.shapes(lay["activ"])).merged()
    gat = db.Region(cell.shapes(lay["gatpoly"])).merged()
    gates = gat & activ                      # channel regions only
    if gates.is_empty():
        return {"W": W, "H": H, "gate_iv": [], "nodev": True}, None

    # PMOS = device Activ inside NWell. Using "upper half of the cell"
    # instead misclassifies the small cells (sighold, tiehi, tielo) whose
    # devices do not sit where a logic gate's would, and silently leaves their
    # PMOS unscaled.
    nwell = db.Region(cell.shapes(lay["nwell"])).merged()
    pmos = [b for b in (s.dbbox() for s in cell.shapes(lay["activ"]).each())
            if b.width() > 0 and is_pmos_dev(b, nwell, gat)]
    if not pmos:
        return {"W": W, "H": H, "gate_iv": merged_x_intervals(gates),
                "nodev": True}, None

    Y0, T, rail_bot, _bots = gband
    cm = channel_metrics(cell, lay)
    if cm and CUT[0] is not None and cm[0] >= CUT[0] - 1e-9:
        return None, (f"NMOS Activ reaches y={cm[0]}, at or above the library "
                      f"channel cut {CUT[0]} -- no room to open the NW.d1 "
                      f"clearance the thick-oxide rules need without giving "
                      f"this cell a different row height")
    above = [b for b in pmos if b.top > T + 1e-9]
    if above:
        return None, (f"PMOS Activ runs up into the VDD rail "
                      f"(top {max(b.top for b in above)} > band top {T}) -- "
                      f"scaling the band would move the rail off the cell "
                      f"boundary and break abutment")
    if any(b.bottom < Y0 - 1e-9 for b in pmos):
        return None, "PMOS Activ starts below the library PMOS band"

    return {"W": W, "H": H, "gate_iv": merged_x_intervals(gates),
            "nodev": False}, None


def build_maps(info, gband, dchan):
    # Fixed slope, not L_HV/(b-a): where a cell staggers the NMOS and PMOS
    # gates by a few nm their x-intervals overlap and merge, and scaling the
    # merged span to L_HV would leave each individual gate short of 0.45.
    # A constant L_HV/L_LV slope widens every 0.13 um gate to exactly 0.45
    # however they group, and merely scales the stagger with it.
    xsegs = [(a, b, L_HV / gl) for a, b, gl in info["gate_iv"]
             if b > a and gl < L_HV - 1e-9]

    # Widen any gate-to-gate gap below Gat.b1 (0.25 um between unrelated 3.3 V
    # gates over Activ). The thin-oxide library has 187 gaps under that, and
    # the x map preserves them as-is. Relatedness is not visible here, so every
    # short gap is opened; where the two gates are the same net the poly
    # between them simply stretches with the map and stays connected.
    iv = sorted(info["gate_iv"])
    for (a1, b1, _), (a2, b2, _) in zip(iv, iv[1:]):
        g = a2 - b1
        if 1e-9 < g < GAT_B1 - 1e-9:
            xsegs.append((b1, a2, GAT_B1 / g))
    xsegs.sort()
    xmap = PWL(xsegs)
    # The y-map is applied even to cells with no PMOS (fill, antenna diode):
    # they must end up the same height as everything else or they cannot abut
    # in a row.

    Y0, T, _, bots = gband

    # A single constant-slope segment. Per-device breakpoints that force the
    # exact netlist width cannot work: a device's width is (its top - its
    # bottom), the cells use several different tops, and one monotone 1-D map
    # cannot satisfy every (top, bottom) pair at once -- pinning some cells'
    # widths knocks others off. So widths are 2.40x the drawn thin-oxide width,
    # exact to within the 5 nm grid.
    ysegs = []
    cut_y, d_nw, d_psd, d_rail = CUT
    if d_rail > 0:
        ysegs.append((0.25, 0.35, 1.0 + d_rail / 0.10))
    if cut_y is not None and d_nw > 0:
        a = cut_y - 0.05
        # TRACK_PAD rides on the NW.d1 insert: growing the mid-cell dead
        # zone is the always-safe direction (every clearance it touches gets
        # bigger), and one shared segment keeps the map monotone.
        ysegs.append((a, cut_y, 1.0 + (d_nw + TRACK_PAD) / (cut_y - a)))
    if d_psd > 0:
        a = Y0 - 0.05
        ysegs.append((a, Y0, 1.0 + d_psd / (Y0 - a)))
    if dchan > 0:
        cut = Y0 - 0.1          # plain field below the band, no contacts there
        ysegs.append((cut, Y0, 1.0 + dchan / (Y0 - cut)))
    ysegs.append((Y0, T, KP))
    return xmap, PWL(ysegs)


def retile_contacts(cell, lay, xmap, ymap, ly):
    """Move each contact to its mapped centre, keeping its original size.

    Contacts are deliberately *not* regenerated to fill the taller thick-oxide
    diffusion. Every attempt to do so introduced connectivity errors that only
    LVS could see: contacts grouped across the VSS and VDD taps and tiled
    through open field, contacts landing under a different Metal1 wire and
    shorting it to diffusion, and rail contacts dropped by a floating-point
    comparison, which broke the substrate tie.

    Mapping the existing contacts is correct by construction. The map is
    monotone, so a contact inside a diffusion stays inside it and under the
    same Metal1, spacings only grow, and every contact keeps its net. The cost
    is that the 2.4x taller PMOS carries the thin-oxide contact count, so its
    source/drain contact resistance is relatively higher -- an electrical
    quality issue, not a correctness one, and the right trade against silently
    wrong connectivity.
    """
    seen = set()
    for lname in ("cont", "via1"):
      conts = [s.dbbox() for s in cell.shapes(lay[lname]).each()]
      cell.shapes(lay[lname]).clear()
      for b in conts:
        cx = (xmap(b.left) + xmap(b.right)) / 2
        cy = (ymap(b.bottom) + ymap(b.top)) / 2
        w, h = b.width(), b.height()
        x0, y0 = snap(cx - w / 2), snap(cy - h / 2)
        key = (lname, round(x0, 4), round(y0, 4), round(w, 4), round(h, 4))
        if key in seen:
            continue            # the thin-oxide GDS repeats some cuts
        seen.add(key)
        cell.shapes(lay[lname]).insert(db.DBox(x0, y0, x0 + w, y0 + h))
    return len(seen)


def gate_list(cell, lay):
    """(is_pmos, x_centre, x_lo, x_hi, y_lo, y_hi) for every poly-over-Activ."""
    nw = db.Region(cell.shapes(lay["nwell"])).merged()
    g = (db.Region(cell.shapes(lay["gatpoly"])).merged()
         & db.Region(cell.shapes(lay["activ"])).merged()).merged()
    out = []
    for poly in g.each_merged():
        b = poly.bbox()
        out.append((not (db.Region(b) & nw).is_empty(),
                    (b.left + b.right) / 2 / DBU,
                    b.left / DBU, b.right / DBU,
                    b.bottom / DBU, b.top / DBU))
    return sorted(out, key=lambda r: (r[0], r[1]))


# fix_widths() was removed. Nudging the Activ edge under a channel to force an
# exact width makes the channel non-rectangular, and the extractor then reports
# a fractional gate length (L=0.4508u instead of 0.45u). The netlist is synced
# to the drawn layout instead -- see sync_netlist_widths.py.



def retarget_pmos_activ(poly, xmap, ymap, gat):
    """Map one PMOS Activ polygon, giving every device an exact width.

    The polygon is cut into vertical slabs at each vertex x. Within a slab the
    Activ has one vertical extent per connected piece, so each piece is
    re-emitted as [mapped_top - snap(KP*height), mapped_top].

    Per *piece*, not per slab bounding box: a non-convex polygon can have two
    disjoint lobes at the same x, and taking the slab's bounding box spans the
    gap between them, merging two channels into one. That silently deleted two
    PMOS from dfrbp_1.

    Per slab rather than per polygon, because a notch is how this library gives
    devices in one diffusion different widths: forcing the whole polygon to one
    height collapses them, while snapping each edge independently gives the
    same device 2.685 um at one y and 2.690 um at another, which LVS reports as
    MatchWithWarning.
    """
    xs = sorted({pt.x for pt in poly.each_point_hull()})
    src = db.Region(poly)
    slabs = []                    # [x0, y0, x1, y1, is_channel] in target DBU
    for x0, x1 in zip(xs, xs[1:]):
        if x1 <= x0:
            continue
        box = db.Region(db.Box(x0, -10 ** 9, x1, 10 ** 9))
        slab = src & box
        for piece in slab.merged().each():
            bb = piece.bbox()
            b, tp = bb.bottom / DBU, bb.top / DBU
            y1 = snap_dbu(ymap(tp))
            chan = not (gat & db.Region(piece)).is_empty()
            slabs.append([snap_dbu(xmap(x0 / DBU)),
                          y1 - snap_dbu(snap(KP * (tp - b))),
                          snap_dbu(xmap(x1 / DBU)), y1, chan])

    # Align sub-grid steps between x-adjacent slabs. Each slab's bottom is
    # mapped_top - snap(KP*h), computed independently, and the source's own
    # 5 nm jogs plus the height snap can land neighbouring slabs one grid
    # step apart. The merged outline then carries 5 nm staircase edges, and
    # each one within 0.23 um of a gate edge is an Act.c violation (a
    # 0.12 um slab flanked by such steps was sdfbbp_1's Act.a).
    #
    # A slab that carries gate poly is a channel and is FROZEN: its height IS
    # the device width, and moving it 5 nm makes two formerly identical
    # devices differ (2.400 vs 2.405). The width itself would be legal, but
    # sync_netlist_widths pairs devices to drawn channels by sorted width,
    # which is ambiguous between near-equal devices on different nets -- the
    # widths land on the wrong instances and LVS loses the net
    # correspondence (that broke five cells, slgcp_1 outright). Only
    # source/drain slabs move, toward their channel neighbours, so the
    # repair provably never changes any device.
    g = int(GRID * DBU)

    def adjacent(a, b):
        return ((a[2] == b[0] or b[2] == a[0])
                and a[1] < b[3] and b[1] < a[3])

    # Anchored slabs hold a definitive edge value: channels always, and any
    # S/D slab that has adopted a value from an anchored neighbour. Anchoring
    # spreads outward from the channels, so a chain of S/D slabs between two
    # channels takes each channel's value from its own side and cannot
    # oscillate.
    anchored = [s[4] for s in slabs]
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(slabs):
            if anchored[i]:
                continue
            for j, b in enumerate(slabs):
                if i == j or not anchored[j] or not adjacent(a, b):
                    continue
                took = False
                if 0 < abs(a[1] - b[1]) <= g:
                    a[1] = b[1]
                    took = True
                if 0 < abs(a[3] - b[3]) <= g:
                    a[3] = b[3]
                    took = True
                if took or (a[1] == b[1] and a[3] == b[3]):
                    anchored[i] = True
                    changed = True
                    break
    # Remaining unanchored S/D pairs (no channel anywhere in the chain):
    # plain min/max fixpoint, as before.
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(slabs):
            if slabs[i][4]:
                continue
            for j, b in enumerate(slabs):
                if i == j or b[4] or anchored[j] != anchored[i]:
                    continue
                if not adjacent(a, b):
                    continue
                if 0 < abs(a[1] - b[1]) <= g:
                    a[1] = b[1] = min(a[1], b[1])
                    changed = True
                if 0 < abs(a[3] - b[3]) <= g:
                    a[3] = b[3] = max(a[3], b[3])
                    changed = True

    out = db.Region()
    for x0, y0, x1, y1, _ in slabs:
        out.insert(db.Box(x0, y0, x1, y1))
    return out.merged()


def transform_cell(ly, cell, xmap, ymap, lay, info):
    """Apply the maps to every layer except Cont.

    Device widths come from the y-map alone. Forcing the Activ box height to a
    computed value instead diverges from the gate height on the irregular
    cells (the tie cells, the sighold keeper, the jogged-poly XOR), where poly
    does not span the full Activ and so W is set by poly-over-Activ, not by
    the Activ box.
    """
    # Activ with no gate over it -- the antenna diodes -- is translated, not
    # scaled. Such a region is a diode, not a channel: stretching it changes
    # its area and perimeter, and then the netlist no longer describes it.
    # Rail taps are excluded because they sit outside the band and are
    # unaffected anyway.
    # Devices with the same thin-oxide width must end up with the same
    # thick-oxide width. Snapping the two Activ edges independently gives
    # 2.685 um at one y and 2.690 um at another for what was the same 1.12 um
    # device; the netlist then cannot say which is which, and LVS reports the
    # pair as MatchWithWarning on every DFF.
    #
    # Only rectangular Activ is adjusted. A notched polygon hosts devices of
    # different widths, and forcing it to one height collapses them -- that is
    # what turned and2_1's three PMOS into 2.69 um.
    pmos_h = {}
    nwell_r = db.Region(cell.shapes(lay["nwell"])).merged()
    gatp_r = db.Region(cell.shapes(lay["gatpoly"])).merged()
    for s in cell.shapes(lay["activ"]).each():
        if s.is_text():
            continue
        poly = s.polygon
        if poly is None:
            continue
        b = s.dbbox()
        if b.width() > 0 and is_pmos_dev(b, nwell_r, gatp_r):
            pmos_h[(round(b.left, 4), round(b.bottom, 4),
                    round(b.right, 4), round(b.top, 4))] = snap(KP * b.height())

    ungated = {}
    gat_r = db.Region(cell.shapes(lay["gatpoly"])).merged()
    H = info["H"]
    for s in cell.shapes(lay["activ"]).each():
        b = s.dbbox()
        if b.width() <= 0:
            continue
        if b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top:
            continue
        inner = db.Region(db.Box(int(b.left * DBU) + 1, int(b.bottom * DBU) + 1,
                                 int(b.right * DBU) - 1, int(b.top * DBU) - 1))
        if (inner & gat_r).is_empty():
            ungated[(round(b.left, 4), round(b.bottom, 4),
                     round(b.right, 4), round(b.top, 4))] = (b.width(), b.height())

    # Every layer in the file, not just the ones named in LAYERS. The GDS also
    # carries Metal2, Via1 and marker layers; leaving those at thin-oxide
    # coordinates while everything else moves silently corrupts the cell -- it
    # is what clipped the antenna diode's extracted area.
    # Cut layers are fixed-size and must be translated, never scaled -- a
    # stretched via fails its own width rule (V1.a).
    fixed = {lay["cont"], lay["via1"]}
    all_layers = [li for li in ly.layer_indexes() if li not in fixed]
    for li in all_layers:
        shapes = cell.shapes(li)
        new = []
        for s in shapes.each():
            if li == lay["activ"] and not s.is_text():
                b = s.dbbox()
                key = (round(b.left, 4), round(b.bottom, 4),
                       round(b.right, 4), round(b.top, 4))
                if key in ungated:
                    w, h = ungated[key]
                    x0 = snap_dbu(xmap(b.left)) / DBU
                    y0 = snap_dbu(ymap(b.bottom)) / DBU
                    new.append(db.DBox(x0, y0, x0 + w, y0 + h))
                    continue
                if key in pmos_h:
                    for q in retarget_pmos_activ(s.polygon, xmap, ymap,
                                                 gat_r).each():
                        new.append(q)
                    continue
            if s.is_text():
                txt = s.text.dup()
                txt.x = snap_dbu(xmap(txt.x / DBU))
                txt.y = snap_dbu(ymap(txt.y / DBU))
                new.append(txt)
            else:
                poly = s.polygon
                if poly is None:
                    continue
                new.append(db.Polygon(
                    [db.Point(snap_dbu(xmap(pt.x / DBU)),
                              snap_dbu(ymap(pt.y / DBU)))
                     for pt in poly.each_point_hull()]))
        shapes.clear()
        for o in new:
            shapes.insert(o)


def close_activ_notches(cell, lay):
    """Fill one-grid-step notches left by the slab retarget.

    Slabs whose thin-oxide heights differ by less than a grid step land on
    neighbouring grid lines after scaling, so the Activ edge steps by 5 nm.
    That step is invisible as a width change but is a real notch: where it
    falls next to a gate it takes the drain/source extension from 0.230 to
    0.225 (Act.c), and where two steps face each other it necks the Activ
    below 0.15 (Act.a).

    A morphological close fills any notch narrower than 2*GRID and leaves
    every convex edge alone, so nothing that was drawn on purpose moves. The
    channel can gain 5 nm of width where a step abutted it, which is why
    sync_netlist_widths.py runs after this and not before.
    """
    r = db.Region(cell.shapes(lay["activ"])).merged()
    if r.is_empty():
        return 0
    g = int(GRID * DBU)
    closed = r.sized(g).sized(-g)
    if (closed ^ r).is_empty():
        return 0
    texts = [s.text.dup() for s in cell.shapes(lay["activ"]).each()
             if s.is_text()]
    cell.shapes(lay["activ"]).clear()
    for p in closed.each():
        cell.shapes(lay["activ"]).insert(p)
    for t in texts:
        cell.shapes(lay["activ"]).insert(t)
    return 1


def _cont_enclosure_ok(m1, conts, need):
    """Every contact that Metal1 enclosed before must still be enclosed."""
    for cb in conts:
        if not (db.Region(cb.enlarged(need, need)) - m1).is_empty():
            return False
    return True


def repair_m1e(cell, lay):
    """Open Metal1 gaps that the retarget pushed under the wide-metal rule.

    M1.e only bites when a line is at least 0.30 um wide and the parallel run
    exceeds 1.0 um. Retargeting creates both conditions out of nothing: the
    y-map thickens horizontal lines past 0.30, and the x-map lengthens runs
    past 1.0. A 0.18 um gap that was legal under the plain spacing rule
    (M1.b) in the thin-oxide cell is then illegal here, without anything
    having moved closer together.

    The repair trims the facing edge of one of the two lines by the shortfall.
    A trim is only kept if it survives every guard below; otherwise the other
    side is tried, and if neither works the violation is left alone. An
    unfixed M1.e is a far smaller problem than a repair that breaks something
    else, which is exactly what the first version of this function did: it
    traded 6 M1.e for 37 new violations (off-grid edges, sub-minimum widths,
    broken contact enclosures) because it trimmed on DRC-reported coordinates
    with only a contact check.

    Guards, all evaluated on the candidate region before it is accepted:
      * the strip is snapped outward to the 5 nm grid, so no trimmed edge can
        land off-grid;
      * Metal1 keeps its minimum width (M1.a);
      * every contact keeps its Metal1 enclosure (M1.c1), and the strip may
        not come near a contact at all;
      * the polygon count is unchanged, so no shape is split or deleted --
        a split would be an open circuit that DRC cannot see;
      * pin shapes are never trimmed (Pin.e).
    """
    m1 = db.Region(cell.shapes(lay["metal1"])).merged()
    if m1.is_empty():
        return 0
    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()]
    H = bnd[0].height() if bnd else None

    conts = [s.dbbox() for s in cell.shapes(lay["cont"]).each()
             if not s.is_text()]
    enc = M1_C1
    kept = [cb for cb in conts
            if (db.Region(cb.enlarged(enc, enc)) - m1).is_empty()]
    # keep-out around every contact: enclosure plus a grid step of slack
    keepout = db.Region()
    for cb in conts:
        keepout.insert(db.Box(int((cb.left - enc - GRID) * DBU),
                              int((cb.bottom - enc - GRID) * DBU),
                              int((cb.right + enc + GRID) * DBU),
                              int((cb.top + enc + GRID) * DBU)))
    keepout.merge()
    pins = db.Region(cell.shapes(lay["metal1_pin"])).merged()
    n_poly = m1.count()
    g = int(GRID * DBU)

    def acceptable(cand):
        if cand.count() != n_poly:
            return False                      # a shape was split or lost
        if not cand.width_check(int(M1_A * DBU)).is_empty():
            return False                      # M1.a
        return _cont_enclosure_ok(cand, kept, enc)

    fixed = 0
    for _ in range(8):                      # each pass can expose the next gap
        wide = m1.sized(int(-M1_E_W / 2 * DBU)).sized(int(M1_E_W / 2 * DBU))
        if wide.is_empty():
            break
        gaps = m1.separation_check(
            wide, int(M1_E_S * DBU),
            min_projection=int(M1_E_CR * DBU) + 1).polygons()
        gaps = [g.bbox() for g in gaps.each()]
        if not gaps:
            break
        progress = False
        for gb in gaps:
            horiz = gb.width() < gb.height()     # gap is thin in x
            span = gb.width() if horiz else gb.height()
            deficit = int(M1_E_S * DBU) - span
            if deficit <= 0:
                continue
            for side in (0, 1):
                if horiz:
                    strip = (db.Box(gb.left - deficit, gb.bottom,
                                    gb.right, gb.top) if side == 0 else
                             db.Box(gb.left, gb.bottom,
                                    gb.right + deficit, gb.top))
                else:
                    strip = (db.Box(gb.left, gb.bottom - deficit,
                                    gb.right, gb.top) if side == 0 else
                             db.Box(gb.left, gb.bottom,
                                    gb.right, gb.top + deficit))
                # Snap outward to the grid. The gap comes from a DRC edge
                # pair and is not grid-aligned (227.178 um, for one), so
                # subtracting it verbatim leaves off-grid Metal1 edges.
                strip = db.Box((strip.left // g) * g, (strip.bottom // g) * g,
                               -((-strip.right) // g) * g,
                               -((-strip.top) // g) * g)
                sr = db.Region(strip)
                if not (sr & keepout).is_empty():
                    continue                  # would cut near a contact
                if not (sr & pins).is_empty():
                    continue                  # would cut a pin shape
                # never cut into a power rail: it has to reach the boundary
                touches_rail = False
                if H is not None:
                    for p in (sr & m1).each():
                        pb = p.bbox()
                        if (pb.bottom / DBU < 1e-6
                                or pb.top / DBU > H - 1e-6):
                            touches_rail = True
                            break
                if touches_rail:
                    continue
                cand = m1 - sr
                if not acceptable(cand):
                    continue
                m1 = cand
                fixed += 1
                progress = True
                break
        if not progress:
            break

    if fixed:
        cell.shapes(lay["metal1"]).clear()
        for p in m1.each():
            cell.shapes(lay["metal1"]).insert(p)
    return fixed


# Hand re-routes for the M1.e sites the automatic repair proved unfixable by
# blind trimming: each gap abuts a contact column or a pin pad, so the fix has
# to know which edge is safe to move. Derived from the flat replication of the
# rule (M1.e: space < 0.22 when one line's interior is >= 0.30 wide and the
# parallel projection exceeds 1.0 um). Coordinates are cell-local um, applied
# after the retarget, before renaming.
#
#   dlygate4sd2_1  A2 pin pad bottom faces a rail-attached line 0.185 away
#                  with a 1.02 um run -- raise the pad bottom to open 0.22.
#   mux2_1         same shape: pin pad at 0.20 -- raise its bottom to 0.22.
#   sdfbbp_1 (1)   internal strap bottom 0.18 over a rail stub -- raise it,
#                  starting 0.16 past the junction with a 0.16-wide arm: a
#                  cut flush with that corner leaves a 0.106 um diagonal
#                  width (M1.a, caught by the guard). The 0.29 um of bottom
#                  edge left at the old height projects only 0.29 onto the
#                  rail stub, under the 1.0 um threshold.
#   sdfbbp_1 (2)   two vertical runs 0.205 apart for 2.33 um. The left line
#                  is only 0.17 wide, so it cannot lose 15 nm (M1.a); the
#                  right line holds a contact column at exactly 0.05
#                  enclosure -- but with a contact-free span between the two
#                  contacts. That span takes a 15 nm-deep, 930 nm-wide bite
#                  ending exactly 0.05 from each contact, splitting the
#                  parallel run into 0.79 + 0.45 um -- both under 1.0.
#   and4_2         X pin pad right edge 0.18 from a contact strap whose own
#                  enclosure is exactly 0.05 -- narrow the pad 0.8 -> 0.76.
M1E_EDITS = {
    "sg13g2_dlygate4sd2_1": {
        "metal1": [(0.205, 1.855, 1.230, 1.890)],
        "metal1_pin": [(0.205, 1.855, 1.230, 1.890)],
    },
    "sg13g2_mux2_1": {
        "metal1": [(3.225, 1.830, 4.345, 1.850)],
        "metal1_pin": [(3.225, 1.830, 4.345, 1.850)],
    },
    "sg13g2_sdfbbp_1": {
        "metal1": [(14.150, 1.725, 15.200, 1.765),
                   (13.875, 3.870, 13.890, 4.800)],
    },
    "sg13g2_and4_2": {
        "metal1": [(5.565, 1.070, 5.605, 5.865)],
        "metal1_pin": [(5.565, 3.585, 5.605, 5.865)],
    },
    # The three sites below appeared with TRACK_PAD: the 0.230 um stretch
    # carried three vertical runs past the 1.0 um parallel-run threshold.
    # Same shape as the pad fixes above: a pin pad faces a strap at 0.18 or
    # 0.20 um, and the pad gives up 20-40 nm.
    "sg13g2_and4_1": {
        "metal1": [(0.725, 1.885, 0.745, 3.045)],
        "metal1_pin": [(0.725, 1.885, 0.745, 3.045)],
    },
    "sg13g2_dlhrq_1": {
        "metal1": [(2.925, 1.935, 2.965, 3.080)],
        "metal1_pin": [(2.925, 1.935, 2.965, 3.080)],
    },
    "sg13g2_or4_2": {
        "metal1": [(3.845, 1.975, 3.885, 3.020)],
        "metal1_pin": [(3.845, 1.975, 3.885, 3.020)],
    },
}
# Coordinates are in the final 17-track (7.140 um) cell frame: TRACK_PAD
# inserts 0.230 um at the mapped channel cut (HV y = 2.24), so any y above
# it carries the +0.230 relative to the 6.910 um frame the edits were first
# derived in. The in-code guards (exact 0.05 contact enclosures among them)
# re-verify every edit on every build, so a mis-shifted edit cannot ship.


def fix_m1e_sites(cell, lay):
    """Apply the M1E_EDITS for this cell and verify nothing else broke.

    Every check that the first, unguarded repair attempt failed is asserted
    here: connectivity (merged polygon count unchanged -- a split would be an
    open circuit LVS may not see if it splits equal-potential metal), minimum
    width (M1.a), space/notch (M1.b), contact enclosure (M1.c1), and the
    5 nm grid. A failed assertion aborts the build rather than shipping the
    defect.
    """
    edits = M1E_EDITS.get(cell.name)
    if not edits:
        return 0
    n = 0
    for lname, boxes in edits.items():
        li = lay[lname]
        r = db.Region(cell.shapes(li)).merged()
        texts = [s.text.dup() for s in cell.shapes(li).each() if s.is_text()]
        before = r.count()
        conts = [s.dbbox() for s in cell.shapes(lay["cont"]).each()
                 if not s.is_text()]
        kept = [cb for cb in conts
                if (db.Region(cb.enlarged(M1_C1, M1_C1)) - r).is_empty()]
        for x0, y0, x1, y1 in boxes:
            for v in (x0, y0, x1, y1):
                assert abs(v / GRID - round(v / GRID)) < 1e-6, \
                    f"{cell.name}: off-grid edit {v}"
            r -= db.Region(db.Box(int(x0 * DBU), int(y0 * DBU),
                                  int(x1 * DBU), int(y1 * DBU)))
            n += 1
        assert r.count() == before, \
            f"{cell.name}/{lname}: edit split or removed a polygon"
        if lname == "metal1":
            assert r.width_check(int(M1_A * DBU)).is_empty(), \
                f"{cell.name}: edit violates M1.a"
            assert r.space_check(180).is_empty(), \
                f"{cell.name}: edit violates M1.b"
            assert _cont_enclosure_ok(r, kept, M1_C1), \
                f"{cell.name}: edit breaks a contact enclosure"
        cell.shapes(li).clear()
        for p in r.each():
            cell.shapes(li).insert(p)
        for t in texts:
            cell.shapes(li).insert(t)
    return n


def pad_to_site(cell, lay):
    """Pad the cell width up to the next SITE_W multiple.

    The x-map stretches only around gates, so mapped cell widths share no
    quantum beyond the layout grid -- and a placer needs a SITE. Padding
    moves the right boundary out and extends with it exactly the shapes
    that continue across an abutment: everything whose geometry reaches the
    old right boundary (rails, rail Activ, tap implants, NWell, DigiBnd,
    the boundary itself). Interior shapes have no edge at the boundary and
    are untouched, so no device and no signal wire changes.
    """
    bnd = [s for s in cell.shapes(lay["bound"]).each()]
    if not bnd:
        return 0.0
    b = bnd[0].dbbox()
    w = b.width()
    W = round((-((-w) // SITE_W)) * SITE_W, 4)      # ceil to site multiple
    dx = round(W - w, 4)
    if dx < GRID / 2:
        return 0.0
    edge = int(round(w * DBU))
    dxi = int(round(dx * DBU))
    for li in ly_layer_indexes(cell.layout()):
        shapes = cell.shapes(li)
        new = []
        changed = False
        for s in shapes.each():
            if s.is_text():
                new.append(s.text.dup())
                continue
            poly = s.polygon
            if poly is None:
                continue
            pts = []
            moved = False
            for pt in poly.each_point_hull():
                if pt.x >= edge - 1:
                    pts.append(db.Point(pt.x + dxi, pt.y))
                    moved = True
                else:
                    pts.append(pt)
            new.append(db.Polygon(pts) if moved else poly)
            changed = changed or moved
        if changed:
            shapes.clear()
            for o in new:
                shapes.insert(o)
    return dx


def ly_layer_indexes(ly):
    return list(ly.layer_indexes())


def add_tgo(cell, lay):
    """ThickGateOx over the whole cell.

    Drawn on the cell boundary grown by TGO.a, so abutted cells merge into one
    region (TGO.e merges anything closer than 0.86 um) and no internal TGO.b /
    TGO.d edge is created inside a row.
    """
    bnd = [s.dbbox() for s in cell.shapes(lay["bound"]).each()]
    if not bnd:
        return
    # In y the margin is TGO.a plus the 0.15 um the rail Activ crosses the
    # cell boundary (the abutting row shares the rail, so half of its 0.30 um
    # Activ belongs to this cell's side). With only the 0.27 um TGO.a margin,
    # an unabutted row edge -- the outermost row of a block, or of a test
    # array -- leaves just 0.12 um of ThickGateOx past the rail Activ and
    # fails TGO.a. With 0.42 um the cell is correct even at a block edge, and
    # interior rows still merge (they overlap outright, far under the 0.86 um
    # TGO.e merge distance).
    b = bnd[0].enlarged(TGO_MARGIN, TGO_MARGIN + 0.15)
    cell.shapes(lay["tgo"]).insert(db.DBox(b.left, b.bottom, b.right, b.top))
    # DigiBnd selects the digital variants of the well rules. NW.d1 wants
    # 0.62 um of NWell-to-N+Activ inside ThickGateOx; NW.d1.dig wants 0.31,
    # which is what a standard cell library is expected to be checked against.
    cell.shapes(lay["digibnd"]).insert(
        db.DBox(bnd[0].left, bnd[0].bottom, bnd[0].right, bnd[0].top))


def main():
    src = db.Layout()
    src.read(str(LV_GDS))
    lay = {k: src.layer(*v) for k, v in LAYERS.items()}

    all_cells = [src.cell(ci.cell_index()) for ci in src.each_cell()]
    gband = band(src, all_cells, lay)
    Y0, T, rail_bot, _bots = gband

    # pSD.i1 needs 0.4 um from the pSD edge to the PFET gate; the thin-oxide
    # layout only carries what pSD.i (0.3) needs. One library-wide insert, so
    # every cell keeps the same height.
    need = 0.0
    for c in all_cells:
        psd = [s.dbbox() for s in c.shapes(lay["psd"]).each()]
        if psd:
            need = max(need, PSD_ENC_TGO - (Y0 - min(b.bottom for b in psd)))
    dchan = max(0.0, snap(need))
    print(f"library PMOS band {Y0:.3f}..{T:.3f} um  (VDD rail tap at {rail_bot:.3f}), "
          f"channel insert {dchan:.3f} um")

    # Global channel cut and inserts. The thick-oxide rules want more room
    # between the NMOS band and the well than the thin-oxide layout carries:
    # NW.d1.dig 0.31 um of NWell to N+Activ, and pSD.i1 0.40 um of pSD around
    # the PFET gate. Both are opened by inserting space at a single cut, so
    # every cell keeps the same row height.
    ms = [(c, channel_metrics(c, lay)) for c in all_cells]
    ms = [(c, m) for c, m in ms if m and m[1] is not None]
    cand = sorted({m[1] for _, m in ms})
    best = None
    for thr in cand:
        sub = [(c, m) for c, m in ms if m[0] < thr - 1e-9 and m[1] >= thr - 1e-9]
        if best is None or len(sub) > len(best[1]):
            best = (thr, sub)
    cut_y, sub = best
    # The insert has to satisfy both clearances measured across the channel:
    #   NW.d1.dig  0.31 um   NWell edge      -> N+Activ
    #   pSD.j1     0.40 um   pSD edge        -> NFET gate
    # Sizing for the NWell rule alone left 104 pSD.j1 violations.
    d_nw = max(0.0,
               snap(NW_D1_DIG - min(m[1] - m[0] for _, m in sub)),
               snap(PSD_ENC_TGO - min(m[2] - m[0] for _, m in sub
                                      if m[2] is not None)))
    d_psd = max(0.0, snap(PSD_ENC_TGO - min(m[3] - m[2] for _, m in sub
                                            if m[2] is not None and m[3] is not None)))
    # Third insert, below the NMOS band: the VSS rail's p+ pSD must clear the
    # NFET gates by pSD.j1 = 0.40 um from below, and the thin-oxide layout
    # leaves only the 0.30 um that pSD.j allows.
    d_rail = max(0.0, snap(PSD_ENC_TGO - min(m[5] - m[4] for _, m in ms
                                             if m[4] is not None and m[5] is not None)))
    CUT[0], CUT[1], CUT[2], CUT[3] = cut_y, d_nw, d_psd, d_rail
    print(f"channel cut y={cut_y:.3f}  NWell insert {d_nw:.3f} um  "
          f"pSD insert {d_psd:.3f} um  rail insert {d_rail:.3f} um")

    ok, skipped = [], []
    n_notch, n_m1e = 0, 0
    pad_total = 0.0
    for cell in all_cells:
        info, why = analyse(src, cell, gband)
        if info is None:
            skipped.append((cell.name, why))
            continue
        xmap, ymap = build_maps(info, gband, dchan)
        transform_cell(src, cell, xmap, ymap, lay, info)
        retile_contacts(cell, lay, xmap, ymap, src)
        n_notch += close_activ_notches(cell, lay)
        n_m1e += fix_m1e_sites(cell, lay)
        n_m1e += repair_m1e(cell, lay)
        pad_total += pad_to_site(cell, lay)
        add_tgo(cell, lay)
        ok.append((cell.name, info))
    print(f"closed Activ notches in {n_notch} cells, "
          f"applied {n_m1e} Metal1 edits for M1.e, "
          f"site padding total {pad_total:.2f} um")

    # drop the cells that could not be retargeted
    for name, _ in skipped:
        src.delete_cell(src.cell_by_name(name))

    # rename to the thick-oxide cell names
    for ci in list(src.each_cell()):
        c = src.cell(ci.cell_index())
        if c.name.startswith("sg13g2_"):
            c.name = "sg13g2_hv_" + c.name[len("sg13g2_"):]

    OUT_GDS.parent.mkdir(parents=True, exist_ok=True)
    src.write(str(OUT_GDS))

    print(f"retargeted {len(ok)} cells -> {OUT_GDS}")
    print(f"skipped {len(skipped)}:")
    for name, why in sorted(skipped):
        print(f"  {name:24s} {why}")
    return ok, skipped


if __name__ == "__main__":
    main()
