#!/usr/bin/env python3
"""Shared queries against the thin-oxide library, which is the reference for
everything the thick-oxide variant is checked against."""
import re, pathlib

LV = pathlib.Path("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell")
HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
LVLIB = LV / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models"
NGSPICE = "/foss/tools/bin/ngspice"


def pininfo():
    """{cell: [(pin, 'I'|'O'|'B'), ...]} from the CDL, in .SUBCKT pin order."""
    info, order, cur = {}, {}, None
    for line in (LV / "cdl" / "sg13g2_stdcell.cdl").read_text().splitlines():
        s = line.strip()
        if s.upper().startswith(".SUBCKT"):
            t = s.split()
            cur = t[1]
            order[cur] = t[2:]
        elif s.startswith("*.PININFO") and cur:
            d = dict(x.split(":") for x in s.split()[1:])
            info[cur] = [(p, d.get(p, "B")) for p in order[cur]]
    return info


def sequential():
    """Cells that hold state, per the thin-oxide Liberty file.

    Three markers, all of which must be honoured:
      ff() / latch()               -- flip-flops and latches
      statetable()                 -- state held without an ff/latch group
      clock_gating_integrated_cell -- integrated clock gates (lgcp, slgcp)
    A cell matching any of these is bistable, so its DC operating point is not
    a well-defined function of its inputs and it cannot be checked by sweeping
    input vectors.
    """
    seq, cur = set(), None
    for line in LVLIB.read_text().splitlines():
        m = re.match(r"\s*cell\s*\((\S+?)\)\s*\{", line)
        if m:
            cur = m.group(1)
        elif cur and re.match(
                r"\s*(ff|latch|statetable)\s*\(|\s*clock_gating_integrated_cell\s*:",
                line):
            seq.add(cur)
    return seq


def hvname(lv):
    return "sg13g2_hv_" + lv[len("sg13g2_"):]


if __name__ == "__main__":
    info, seq = pininfo(), sequential()
    print(f"{len(info)} cells, {len(seq)} stateful:")
    for c in sorted(seq):
        print("   ", c)
