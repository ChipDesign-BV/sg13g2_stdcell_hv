import sys, klayout.db as db
ly = db.Layout(); ly.read("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds")
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
            extra = "" if npts<=4 else f" pts={[(round(pt.x,3),round(pt.y,3)) for pt in p.each_point_hull()]}"
            print(f"  {b}{extra}")
