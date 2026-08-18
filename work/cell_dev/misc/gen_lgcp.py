#!/usr/bin/env python3
"""Derive sg13g2_hv_lgcp_1 from the drawn sg13g2_hv_slgcp_1.

CDL diff (net-by-net, slgcp_1 -> lgcp_1; slgcp net names, with the mapping
slgcp{net6,net4,net5,net2,net1} -> lgcp{net1,net6,net3,net5,net2/net4}):

  * remove the SCE input leg: MP2 (net3 SCE VDD, w=2.015) and
    MN2 (net1 SCE VSS, w=0.550) plus the SCE pin;
  * MP3 (net1 GATE net3, 2.015) -> lgcp MP2 (net4 GATE VDD, 2.400):
    its source diffusion (the old series node net3) is tied to VDD and
    the device is widened to 2.400;
  * MP4 (net1 CLKbb net6, 2.015) -> lgcp MP3 (net1 CLKBB net4, 2.400);
  * MN3 (net1 GATE VSS, 0.550) -> lgcp MN3 (net2 GATE VSS, 0.640);
  * MN4 (net6 CLKb net1, 0.550) -> lgcp MN2 (net1 CLKB net2, 0.640);
  * the shared slgcp mid node net1 (PMOS series node == NMOS series node,
    joined in Metal1) splits into two nets in lgcp (net4 on the PMOS side,
    net2 on the NMOS side): the joining Metal1 column is cut.

This reproduces the multiset diff -3 pmos 2.015 / -3 nmos 0.550,
+2 pmos 2.400 / +2 nmos 0.640.

Physical edits, in original slgcp coordinates (nm, dbu=1nm):
  * drop the SCE gate poly, pin metal/label, its poly contact, the VSS/VDD
    rail fingers and contacts that fed MN2/MP2, and the active under MN2/MP2
    (both actives trimmed to x>=1.000);
  * new VDD finger + contacts onto the old net3 diffusion x[1.00,1.38];
  * W resizes by growing the active away from the fixed-convention N-well
    bottom, with Act.c=0.23 lateral cover and Gat.c=0.18 endcap extensions:
      MN3: active top 1.760->1.850 for x[1.15,2.06] (gate poly is continuous
           above, no endcap needed);
      MN4: active bottom 1.020->0.930 for x[3.79,4.70], gate poly extended
           down 0.840->0.750;
      MP3: active top 5.910->6.295 for x[1.15,2.06], poly top 6.345->6.480;
      MP4: active top 5.370->5.755 for x[4.57,5.535] (right edge meets the
           taller neighbouring active region), poly top 5.805->5.940;
  * Metal1 net split: subtract x[2.545,2.830] y[2.555,4.425];
  * shrink by one 0.48 site: all content shifts x-0.48, the frame (rails,
    tap strips, pSD bands, ThickGateOx, DigiBnd, boundary, rail contact
    rows, N-well per the strict convention of fix_well_nwc1.py) is redrawn
    for W=14.880 (31 sites).

Writes work/cell_dev/misc/sg13g2_hv_lgcp_1.gds (single top cell).
Verify with: python3 work/cell_verify.py work/cell_dev/misc/sg13g2_hv_lgcp_1.gds
"""
import pathlib

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
LIB = HERE.parent.parent.parent / "gds" / "sg13g2_stdcell_hv.gds"
OUT = HERE / "sg13g2_hv_lgcp_1.gds"

L = dict(act=(1, 0), gat=(5, 0), cnt=(6, 0), m1=(8, 0), pin=(8, 2),
         txt=(8, 25), psd=(14, 0), dig=(16, 0), nw=(31, 0), tgo=(44, 0),
         bnd=(189, 4))

W_OLD, W, H = 15360, 14880, 7140      # 32 -> 31 sites
DX = -480                             # content shift


def region_of(cell, ly, layer):
    r = db.Region(cell.begin_shapes_rec(ly.layer(*layer)))
    r.merge()
    return r


def main():
    src = db.Layout()
    src.read(str(LIB))
    assert src.dbu == 0.001
    slg = src.cell("sg13g2_hv_slgcp_1")
    assert slg is not None

    def R(name):
        return region_of(slg, src, L[name])

    def B(*a):
        return db.Region(db.Box(*a))

    # ---------------- contacts ----------------
    cnt = R("cnt")
    keep = db.Region()
    for p in cnt.each_merged():
        c = p.bbox().center()
        if -220 < c.y < 7000:                       # drop rail rows
            keep.insert(p)
    cnt = keep
    for bx in ((425, 3035, 585, 3195),              # SCE poly contact
               (280, 1400, 440, 1560),              # MN2 VSS source contact
               (280, 4655, 440, 4815),              # MP2 VDD source contacts
               (280, 5470, 440, 5630)):
        cnt -= B(*bx)
    cnt += B(1110, 4655, 1270, 4815)                # new VDD contacts on the
    cnt += B(1110, 5470, 1270, 5630)                # old net3 diffusion

    # ---------------- gate poly ----------------
    gat = db.Region()
    for p in R("gat").each_merged():
        if p.bbox().right > 1010:                   # drop the SCE gate poly
            gat.insert(p)
    gat += B(1380, 6295, 1830, 6480)                # MP3 endcap extension
    gat += B(4800, 5755, 5250, 5940)                # MP4 endcap extension
    gat += B(4020, 750, 4470, 900)                  # MN4 endcap extension
    gat.merge()

    # ---------------- active ----------------
    act = R("act")
    act -= B(-500, -300, W_OLD + 500, 150)          # p-tap strip (frame)
    act -= B(0, 6990, W_OLD, 7290)                  # n-tap strip (frame)
    act -= B(-500, 150, 1000, 2000)                 # MN2 channel + source
    act -= B(-500, 3000, 1000, 6500)                # MP2 channel + source
    act += B(1150, 1760, 2060, 1850)                # MN3 0.550 -> 0.640
    act += B(3790, 930, 4700, 1020)                 # MN4 0.550 -> 0.640
    act += B(1150, 5910, 2060, 6295)                # MP3 2.015 -> 2.400
    act += B(4570, 5370, 5535, 5755)                # MP4 2.015 -> 2.400
    act.merge()

    # ---------------- pSD (keep only the content dip) ----------------
    psd = R("psd")
    psd -= B(-1000, -1000, W_OLD + 1000, 180)       # lower strip (frame)
    psd -= B(-160, 2635, W_OLD + 160, 6920)         # upper band (frame)

    # ---------------- Metal1 ----------------
    m1 = R("m1")
    m1 -= B(355, 1940, 775, 3430)                   # SCE pin metal
    m1 -= B(230, 220, 490, 1595)                    # VSS finger of MN2
    m1 -= B(230, 4375, 490, 6825)                   # VDD finger of MP2
    m1 -= B(2545, 2555, 2830, 4425)                 # net4 / net2 split cut
    m1 -= B(0, -220, W_OLD, 220)                    # rails (frame)
    m1 -= B(0, 6825, W_OLD, 7360)
    m1 += B(1060, 4400, 1320, 7000)                 # new VDD finger

    # ---------------- pins / labels ----------------
    pins = []
    for s in slg.shapes(src.layer(*L["pin"])).each():
        if s.is_text():
            continue
        b = s.box
        if b == db.Box(355, 1940, 775, 3430):       # SCE pin
            continue
        if b.height() >= 530 and b.width() == W_OLD:  # rail pins (frame)
            continue
        pins.append(db.Box(b.left + DX, b.bottom, b.right + DX, b.top))
    texts = []
    for s in slg.shapes(src.layer(*L["txt"])).each():
        t = s.text
        if t.string in ("SCE", "VDD", "VSS"):
            continue
        texts.append((t.string, t.x + DX, t.y))

    # ---------------- shift content, build the new cell ----------------
    out = db.Layout()
    out.dbu = 0.001
    cell = out.create_cell("sg13g2_hv_lgcp_1")
    li = {k: out.layer(*v) for k, v in L.items()}
    tr = db.Trans(db.Vector(DX, 0))

    def put(layer, region):
        region.merge()
        for p in region.each_merged():
            cell.shapes(li[layer]).insert(p)

    for name, r in (("cnt", cnt), ("gat", gat), ("act", act),
                    ("psd", psd), ("m1", m1)):
        put(name, r.transformed(tr))

    # frame at the new width
    def box(layer, l, b, r, t):
        cell.shapes(li[layer]).insert(db.Box(l, b, r, t))

    box("bnd", 0, 0, W, H)
    box("dig", 0, 0, W, H)
    box("tgo", -270, -420, W + 270, 7560)
    box("act", 0, -150, W, 150)
    box("act", 0, 6990, W, 7290)
    box("psd", -300, -180, W + 300, 180)
    box("psd", -160, 2635, W + 160, 6920)
    box("m1", 0, -220, W, 220)
    box("m1", 0, 6825, W, 7360)
    box("pin", 0, -220, W, 220)
    box("pin", 0, 6825, W, 7360)
    for k in range(W // 480):
        x = 160 + 480 * k
        box("cnt", x, -80, x + 160, 80)
        box("cnt", x, 7060, x + 160, 7220)
    for b in pins:
        cell.shapes(li["pin"]).insert(b)
    for s, x, y in texts:
        cell.shapes(li["txt"]).insert(db.Text(s, db.Trans(x, y)))
    cell.shapes(li["txt"]).insert(db.Text("VSS", db.Trans(W // 2, 0)))
    cell.shapes(li["txt"]).insert(db.Text("VDD", db.Trans(W // 2, H)))

    # ---------------- N-well, strict convention ----------------
    act_f = db.Region(cell.shapes(li["act"]));  act_f.merge()
    psd_f = db.Region(cell.shapes(li["psd"]));  psd_f.merge()
    pact = act_f & psd_f
    nact = act_f - psd_f
    ptap = pact & B(-1000, -1000, W + 1000, 200)
    pmos = pact - ptap
    ntap = nact & B(-1000, 6900, W + 1000, 8000)
    nmos = nact - ntap
    enc, bot, top = 620, 2570, 7530
    clip = B(-enc, 0, W + enc, top)
    well = B(-enc, bot, W + enc, top)
    well += pmos.sized(enc) & clip
    well -= nmos.sized(enc)
    well -= ptap.sized(enc)
    well.merge()
    assert ((pmos.sized(enc) & clip) - well).is_empty(), "NW.c1"
    assert (well & nmos.sized(enc)).is_empty(), "NW.d1"
    assert (well & ptap.sized(enc)).is_empty(), "NW.f1"
    bb = well.bbox()
    assert (bb.left, bb.right, bb.top) == (-enc, W + enc, top), bb
    assert bb.bottom <= bot
    put("nw", well)

    # ---------------- device self-check ----------------
    gates = db.Region(cell.shapes(li["gat"])) & act_f
    nm, pm = [], []
    for p in gates.each_merged():
        b = p.bbox()
        (pm if not (db.Region(p) & psd_f).is_empty() else nm).append(
            (b.width(), b.height()))
    nm.sort(); pm.sort()
    assert sorted(w for _, w in nm) == \
        [420, 420, 640, 640, 640, 640, 740, 740, 740, 740], nm
    assert sorted(w for _, w in pm) == \
        [1010, 1010, 2015, 2015, 2015, 2015, 2400, 2400, 2690, 2690], pm
    assert all(l == 450 for l, _ in nm + pm)

    out.write(str(OUT))
    print(f"wrote {OUT} (W = {W/1000} um = {W//480} sites, "
          f"{len(nm)} NMOS + {len(pm)} PMOS)")


if __name__ == "__main__":
    main()
