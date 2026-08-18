import klayout.db as db
ly = db.Layout(); ly.read("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
L = {"activ":(1,0),"gatpoly":(5,0),"cont":(6,0),"m1":(8,0),"m1pin":(8,2),"m1txt":(8,25),
     "psd":(14,0),"nwell":(31,0),"tgo":(44,0),"bound":(189,4),"digibnd":(16,0),
     "via1":(19,0),"m2":(10,0),"nsd":(7,0)}
lay = {k: ly.layer(*v) for k,v in L.items()}
for name in ("sg13g2_hv_inv_1","sg13g2_hv_sdfbbp_1"):
    c = ly.cell(name)
    print("="*70); print(name)
    for k in L:
        boxes = [s.dbbox() for s in c.shapes(lay[k]).each() if not s.is_text()]
        texts = [(s.text.string, s.dtext.x, s.dtext.y) for s in c.shapes(lay[k]).each() if s.is_text()]
        if boxes:
            xs0=min(b.left for b in boxes); ys0=min(b.bottom for b in boxes)
            xs1=max(b.right for b in boxes); ys1=max(b.top for b in boxes)
            print(f"  {k:8s} n={len(boxes):3d} extent=({xs0:.3f},{ys0:.3f})..({xs1:.3f},{ys1:.3f})")
        if texts:
            print(f"  {k:8s} texts: {texts}")
    # rails detail
    bnd = [s.dbbox() for s in c.shapes(lay["bound"]).each()][0]
    print(f"  boundary: {bnd}  W={bnd.width():.3f} sites={bnd.width()/0.48:.2f} H={bnd.height():.3f}")
    for k in ("m1","nwell","tgo","digibnd","psd","nsd"):
        for s in c.shapes(lay[k]).each():
            if s.is_text(): continue
            b=s.dbbox()
            if k=="m1" and (b.bottom<0.3 or b.top>bnd.height()-0.3) and b.width()>bnd.width()*0.9:
                print(f"  rail {k}: {b}")
            if k in ("nwell","tgo","digibnd"):
                print(f"  {k}: {b}")
    # rail-crossing activ
    for s in c.shapes(lay["activ"]).each():
        b=s.dbbox()
        if b.bottom < 0 < b.top or b.bottom < bnd.height() < b.top:
            print(f"  rail-tap activ: {b}")
