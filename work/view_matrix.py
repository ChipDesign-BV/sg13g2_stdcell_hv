#!/usr/bin/env python3
"""Per-cell view coverage matrix.

One row per cell, one column per view the library ships: SPICE and CDL
subcircuits, Verilog module, xschem symbol and schematic, GDS cell, LEF
macro, Liberty cell (split into timing arcs and leakage). The PDK
contribution decision -- which cells are complete enough to ship -- should
be read off this table, not assembled by hand.

Exit status 0 always; this is a report, not a gate. The last block prints
the derived sets: cells complete in every view, and every incomplete cell
with the views it is missing.
"""
import pathlib
import re
import sys

HV = pathlib.Path(__file__).parent.parent


def spice_cells(path, kw=".subckt"):
    return {m.group(1) for m in
            re.finditer(rf"^\{kw[0]}{kw[1:]}\s+(sg13g2_hv_\w+)",
                        path.read_text(errors="surrogateescape"),
                        re.M | re.I)}


def main():
    spice = spice_cells(HV / "spice" / "sg13g2_stdcell_hv.spice")
    cdl = spice_cells(HV / "cdl" / "sg13g2_stdcell_hv.cdl")
    verilog = {m.group(1) for m in
               re.finditer(r"^module\s+(sg13g2_hv_\w+)",
                           (HV / "verilog" / "sg13g2_stdcell_hv.v")
                           .read_text(), re.M)}
    sym = {p.stem for p in (HV / "sym" / "xschem").glob("sg13g2_hv_*.sym")}
    sch = {p.stem for p in (HV / "sch" / "xschem").glob("sg13g2_hv_*.sch")}
    sch.discard("sg13g2_hv_stdcells")      # the gallery sheet, not a cell

    import pya
    ly = pya.Layout()
    ly.read(str(HV / "gds" / "sg13g2_stdcell_hv.gds"))
    gds = {c.name for c in ly.each_cell()
           if c.name.startswith("sg13g2_hv_")}

    lef = {m.group(1) for m in
           re.finditer(r"^MACRO\s+(sg13g2_hv_\w+)",
                       (HV / "lef" / "sg13g2_stdcell_hv.lef").read_text(),
                       re.M)}

    libtxt = (HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib") \
        .read_text(errors="surrogateescape")
    lib_cells = {}
    for m in re.finditer(r"^  cell \((sg13g2_hv_\w+)\) \{", libtxt, re.M):
        start = m.end()
        nxt = libtxt.find("\n  cell (", start)
        body = libtxt[start:nxt if nxt > 0 else len(libtxt)]
        lib_cells[m.group(1)] = ("timing ()" in body,
                                 "leakage_power" in body)
    lib_t = {c for c, (t, _) in lib_cells.items() if t}
    lib_l = {c for c, (_, l) in lib_cells.items() if l}

    views = [("spice", spice), ("cdl", cdl), ("verilog", verilog),
             ("sym", sym), ("sch", sch), ("gds", gds), ("lef", lef),
             ("lib", set(lib_cells)), ("arcs", lib_t), ("leak", lib_l)]
    cells = sorted(set().union(*(v for _, v in views)))

    hdr = f"{'cell':30s}" + "".join(f"{n:>9s}" for n, _ in views)
    print(hdr + "\n" + "-" * len(hdr))
    for c in cells:
        print(f"{c:30s}" + "".join(
            f"{'x' if c in v else '-':>9s}" for _, v in views))

    # A cell is PDK-complete when every view has it. Timing arcs and
    # leakage are judged only against expectation: fill/decap/tie/antenna
    # cells legitimately carry no timing arcs.
    no_arc_ok = re.compile(
        r"sg13g2_hv_(fill_\d+|decap_\d+|antennanp|sighold|tiehi|tielo)$")
    print()
    complete, incomplete = [], []
    for c in cells:
        missing = [n for n, v in views[:8] if c not in v]
        if not (c in lib_t or no_arc_ok.match(c)):
            missing.append("arcs")
        if missing:
            incomplete.append((c, missing))
        else:
            complete.append(c)
    print(f"complete in all views: {len(complete)} / {len(cells)}")
    for c, missing in incomplete:
        print(f"  {c:30s} missing: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
