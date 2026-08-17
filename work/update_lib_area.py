#!/usr/bin/env python3
"""Set each Liberty cell's area from the LEF macro it ships with.

The characterization config estimated cell areas before any layout existed
(thin-oxide pitch count scaled to the thick-oxide pitch and row height).
Now that gen_lef.py derives macros from the drawn GDS, the real footprint is
known: area = LEF SIZE width x height. This script rewrites the `area`
attribute of every Liberty cell that has a LEF macro and reports the ones
that keep the estimate (cells characterized but not drawn, if any).

Run after gen_lef.py; verify_lib.py still gates the result.
"""
import pathlib
import re
import sys

LIB = pathlib.Path(__file__).parent.parent / "lib"
LEF = pathlib.Path(__file__).parent.parent / "lef" / "sg13g2_stdcell_hv.lef"


def lef_areas():
    """{macro: area_um2} from MACRO ... SIZE w BY h ; blocks."""
    areas = {}
    macro = None
    for line in LEF.read_text().splitlines():
        t = line.split()
        if len(t) == 2 and t[0] == "MACRO":
            macro = t[1]
        elif macro and len(t) == 5 and t[0] == "SIZE" and t[2] == "BY":
            areas[macro] = round(float(t[1]) * float(t[3]), 4)
            macro = None
    return areas


def main():
    areas = lef_areas()
    changed = kept = 0
    for libfile in sorted(LIB.glob("*.lib")):
        text = libfile.read_text()
        out = []
        cell = None
        for line in text.splitlines(keepends=True):
            m = re.match(r"\s*cell \((\S+)\) \{", line)
            if m:
                cell = m.group(1)
            m = re.match(r"(\s*)area : ([0-9.]+)( ;.*\n)", line)
            if m and cell:
                if cell in areas:
                    old = float(m.group(2))
                    new = areas[cell]
                    if abs(old - new) > 5e-5:
                        changed += 1
                        print(f"  {cell:28s} {old:10.4f} -> {new:10.4f}")
                    line = f"{m.group(1)}area : {new}{m.group(3)}"
                else:
                    kept += 1
                    print(f"  {cell:28s} no LEF macro, estimate kept")
                cell = None
            out.append(line)
        libfile.write_text("".join(out))
        print(f"{libfile.name}: {changed} areas set from LEF, "
              f"{kept} estimates kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
