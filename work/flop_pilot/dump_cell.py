import sys, klayout.db as db
ly = db.Layout(); ly.read("/foss/designs/sg13g2_stdcell_hv/gds/sg13g2_stdcell_hv.gds")
c = ly.cell(sys.argv[1])
for li in ly.layer_indexes():
    info = ly.get_info(li)
    shapes = list(c.shapes(li).each())
    if not shapes: continue
    print(f"--- layer {info.layer}/{info.datatype} ({len(shapes)} shapes)")
    for s in shapes:
        if s.is_text():
            print(f"  TEXT {s.dtext.string!r} at ({s.dtext.x},{s.dtext.y})")
        else:
            b = s.dbbox()
            p = s.dpolygon
            npts = p.num_points() if p else 0
            extra = "" if npts<=4 else f" pts={[(pt.x,pt.y) for pt in p.each_point_hull()]}"
            print(f"  {b}{extra}")
