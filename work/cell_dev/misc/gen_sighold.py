#!/usr/bin/env python3
"""Draw sg13g2_hv_sighold from scratch (no drawn relative in the library).

Topology per cdl/sg13g2_stdcell_hv.cdl (two weak cross-coupled inverters,
single bidirectional pin SH; note the L=0.70 um feedback devices):

    MN1 net1 SH  VSS VSS sg13_hv_nmos w=0.300 l=0.450
    MN0 SH  net1 VSS VSS sg13_hv_nmos w=0.300 l=0.700
    MP1 net1 SH  VDD VDD sg13_hv_pmos w=1.080 l=0.450
    MP0 SH  net1 VDD VDD sg13_hv_pmos w=0.720 l=0.700

Construction follows the library template the way work/gen_tie_cells.py and
work/fix_well_nwc1.py document it (frame conventions read off
sg13g2_hv_inv_1): boundary 189/4 (0,0)-(W,7.140) with W = 6 x 0.48 um sites;
Metal1 rails VSS y[-0.22,0.22] / VDD y[6.825,7.360] with pin 8/2 twins and
8/25 labels; p-substrate tap strip (Activ y[-0.15,0.15] under pSD
y[-0.18,0.18]) and n-well tap strip (Activ y[6.99,7.29]) with 0.16 um rail
contacts on the site-centred 0.48 grid; ThickGateOx 44/0 at -0.42/+0.42 um
vertical, +-0.27 lateral; DigiBnd 16/0 = boundary; N-well 31/0 per the
strict convention: bottom 2.570, top 7.530, lateral overhang exactly 0.62,
>=0.62 to NMOS active / p-tap, >=0.62 enclosure of PMOS active.

Row plan (one shared active per row, x in um):

    net1 | gate A (SH, L=0.45) | VSS-VDD | gate B (net1, L=0.70) | SH

PMOS W steps from 1.08 (MP1) to 0.72 (MP0) at x=1.20, which honours
Act.c (0.23 drain/source extension) on both gates; endcaps are Gat.c=0.18;
diffusion-contact-to-gate gaps >= Cnt.f=0.11; unrelated-gate space 0.46 >=
Gat.b1=0.25; M1 spacings >= 0.18 with contact enclosure >= 0.05.

Writes work/cell_dev/misc/sg13g2_hv_sighold.gds (single top cell).
Verify with: python3 work/cell_verify.py work/cell_dev/misc/sg13g2_hv_sighold.gds
"""
import pathlib

import klayout.db as db

OUT = pathlib.Path(__file__).resolve().parent / "sg13g2_hv_sighold.gds"

L = dict(act=(1, 0), gat=(5, 0), cnt=(6, 0), m1=(8, 0), pin=(8, 2),
         txt=(8, 25), psd=(14, 0), dig=(16, 0), nw=(31, 0), tgo=(44, 0),
         bnd=(189, 4))

W = 6 * 480          # 2.880 um, 6 sites
H = 7140


def main():
    ly = db.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell("sg13g2_hv_sighold")
    li = {k: ly.layer(*v) for k, v in L.items()}

    def box(layer, l, b, r, t):
        cell.shapes(li[layer]).insert(db.Box(l, b, r, t))

    # ---- frame ----------------------------------------------------------
    box("bnd", 0, 0, W, H)
    box("dig", 0, 0, W, H)
    box("tgo", -270, -420, W + 270, 7560)
    # tap strips + rails
    box("act", 0, -150, W, 150)          # p-sub tap (in pSD)
    box("act", 0, 6990, W, 7290)         # n-well tap
    box("psd", -70, -180, W + 70, 180)
    box("psd", -70, 2635, W + 70, 6920)  # PMOS implant region
    box("m1", 0, -220, W, 220)
    box("m1", 0, 6825, W, 7360)
    box("pin", 0, -220, W, 220)
    box("pin", 0, 6825, W, 7360)
    cell.shapes(li["txt"]).insert(db.Text("VSS", db.Trans(W // 2, 0)))
    cell.shapes(li["txt"]).insert(db.Text("VDD", db.Trans(W // 2, H)))
    for k in range(W // 480):
        x = 160 + 480 * k
        box("cnt", x, -80, x + 160, 80)
        box("cnt", x, 7060, x + 160, 7220)

    # ---- devices --------------------------------------------------------
    # NMOS row: both W=0.30
    box("act", 180, 1150, 2470, 1450)
    # PMOS row: W=1.08 left of the step at x=1.20, W=0.72 right of it
    box("act", 180, 3900, 1200, 4980)
    box("act", 1200, 3900, 2470, 4620)
    # gate A: SH, L=0.45; gate B: net1, L=0.70
    box("gat", 520, 970, 970, 5160)
    box("gat", 1430, 970, 2130, 4800)

    # ---- contacts -------------------------------------------------------
    for x in (250, 1140, 2240):                  # net1 | VSS | SH (NMOS)
        box("cnt", x, 1220, x + 160, 1380)
    for x in (250, 1140, 2240):                  # net1 | VDD | SH (PMOS)
        box("cnt", x, 4200, x + 160, 4360)
    box("cnt", 690, 2900, 850, 3060)             # gate A poly contact (SH)
    box("cnt", 1700, 3600, 1860, 3760)           # gate B poly contact (net1)

    # ---- Metal1 ---------------------------------------------------------
    box("m1", 1080, 220, 1360, 1440)             # VSS finger
    box("m1", 1080, 4140, 1360, 7360)            # VDD finger
    box("m1", 200, 1140, 460, 4440)              # net1 column
    box("m1", 200, 3550, 1910, 3810)             # net1 to gate B contact
    box("m1", 2190, 1140, 2450, 4440)            # SH column
    box("m1", 640, 2850, 2450, 3110)             # SH: gate A contact to column

    # ---- N-well (strict convention, cf. fix_well_nwc1.py) ---------------
    act = db.Region(cell.shapes(li["act"]))
    psd = db.Region(cell.shapes(li["psd"]))
    act.merge(); psd.merge()
    pact = act & psd
    nact = act - psd
    ptap = pact & db.Region(db.Box(-1000, -1000, W + 1000, 200))
    pmos = pact - ptap
    ntap = nact & db.Region(db.Box(-1000, 6900, W + 1000, 8000))
    nmos = nact - ntap
    enc, bot, top = 620, 2570, 7530
    well = db.Region(db.Box(-enc, bot, W + enc, top))
    well += pmos.sized(enc) & db.Region(db.Box(-enc, 0, W + enc, top))
    well -= nmos.sized(enc)
    well -= ptap.sized(enc)
    well.merge()
    assert ((pmos.sized(enc) & db.Region(db.Box(-enc, 0, W + enc, top)))
            - well).is_empty(), "NW.c1"
    assert (well & nmos.sized(enc)).is_empty(), "NW.d1"
    assert (well & ptap.sized(enc)).is_empty(), "NW.f1"
    bb = well.bbox()
    assert (bb.left, bb.right, bb.bottom, bb.top) == (-enc, W + enc, bot, top)
    for p in well.each_merged():
        cell.shapes(li["nw"]).insert(p)

    # ---- SH pin ---------------------------------------------------------
    box("pin", 2190, 2400, 2450, 3600)           # inside the SH column
    cell.shapes(li["txt"]).insert(db.Text("SH", db.Trans(2400, 3000)))

    ly.write(str(OUT))
    print(f"wrote {OUT} (W = {W/1000} um = {W//480} sites)")


if __name__ == "__main__":
    main()
