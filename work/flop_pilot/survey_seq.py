#!/usr/bin/env python3
"""Survey the LV source cells for the sequential-cell retarget: everything
the per-cell y-map insert split and finger list needs."""
import sys, pathlib
import klayout.db as db
sys.path.insert(0, "/foss/designs/sg13g2_stdcell_hv/work")
import layout_retarget as rt

CELLS = ["sg13g2_dfrbp_1", "sg13g2_dfrbpq_2", "sg13g2_dfrbp_2",
         "sg13g2_sdfrbpq_1", "sg13g2_sdfrbp_1", "sg13g2_sdfrbpq_2",
         "sg13g2_sdfrbp_2", "sg13g2_dfrbpq_1"]

ly = db.Layout(); ly.read(str(rt.LV_GDS))
lay = {k: ly.layer(*v) for k, v in rt.LAYERS.items()}
DBU = 1000

for name in CELLS:
    c = ly.cell(name)
    if c is None:
        print(f"== {name}: NOT FOUND"); continue
    bnd = [s.dbbox() for s in c.shapes(lay["bound"]).each()][0]
    W, H = bnd.width(), bnd.height()
    nw = db.Region(c.shapes(lay["nwell"])).merged()
    gat = db.Region(c.shapes(lay["gatpoly"])).merged()
    act = db.Region(c.shapes(lay["activ"])).merged()
    gates = (act & gat).merged()
    # classify activ shapes
    nmos_tops, pmos_bots, pmos_tops = [], [], []
    fingers = []
    for s in c.shapes(lay["activ"]).each():
        if s.is_text(): continue
        b = s.dbbox()
        if b.width() <= 0: continue
        straddle = b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top
        if straddle: continue
        if rt.is_pmos_dev(b, nw, gat):
            pmos_bots.append(b.bottom); pmos_tops.append(b.top)
            if b.top > 3.6249:
                fingers.append(b)
        else:
            inner = db.Region(db.Box(int(b.left*DBU)+1, int(b.bottom*DBU)+1,
                                     int(b.right*DBU)-1, int(b.top*DBU)-1))
            if not (inner & gat).is_empty():
                nmos_tops.append((b.top, b))
    # gate bottoms (NMOS side)
    ngb = [g.bbox().bottom/DBU for g in gates.each() if g.bbox().top/DBU < H/2]
    pgb = [g.bbox().bottom/DBU for g in gates.each() if g.bbox().top/DBU >= H/2]
    # n+ S/D activ bottoms (non-straddling)
    nact_bots = []
    for s in c.shapes(lay["activ"]).each():
        if s.is_text(): continue
        b = s.dbbox()
        if b.width() <= 0: continue
        if b.bottom < -1e-9 < b.top or b.bottom < H-1e-9 < b.top: continue
        if not rt.is_pmos_dev(b, nw, gat) and b.top < H/2:
            nact_bots.append(b.bottom)
    nmos_top = max(t for t, _ in nmos_tops)
    # activ-free 0.05 windows between nmos_top and 1.875
    free = []
    y = round(nmos_top, 3)
    actr = act
    while y + 0.05 <= 1.876:
        win = db.Region(db.Box(int(-1*DBU), int((y+0.0001)*DBU),
                               int((W+1)*DBU), int((y+0.0499)*DBU)))
        if (actr & win).is_empty():
            free.append(round(y,3)); 
        y = round(y + 0.005, 3)
    # compress free list into ranges
    rngs=[]
    for v in free:
        if rngs and abs(v - rngs[-1][1] - 0.005) < 1e-9: rngs[-1][1]=v
        else: rngs.append([v,v])
    layers_used = []
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if not c.shapes(li).is_empty():
            layers_used.append(f"{info.layer}/{info.datatype}")
    d_rail_max = round(1.95 - nmos_top, 3)
    d_rail_min_gate = round(0.58 - min(ngb), 3)
    d_rail_min_act = round(0.58 - min(nact_bots), 3) if nact_bots else None
    print(f"== {name}: W={W:.2f} H={H:.2f}")
    print(f"   nmos_top={nmos_top:.3f} (shape {[b for t,b in nmos_tops if t==nmos_top][0]})")
    print(f"   min NFET gate bottom={min(ngb):.3f}  min n+SD activ bottom={min(nact_bots):.3f}")
    print(f"   D_RAIL range: hard>={d_rail_min_gate}, soft>={d_rail_min_act}, max<={d_rail_max}")
    print(f"   pmos_bot min={min(pmos_bots):.3f} (need >=2.046 for flat well)  pmos_top(non-finger) max={max((t for t in pmos_tops if t<3.62), default=0):.3f}")
    print(f"   finger shapes (top>3.625): {len(fingers)}")
    for b in fingers: print(f"      {b}")
    print(f"   free 0.05 cut windows (start y): {[tuple(r) for r in rngs]}")
    print(f"   layers: {sorted(layers_used)}")
