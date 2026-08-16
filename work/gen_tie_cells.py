#!/usr/bin/env python3
"""Add sg13g2_hv_tiehi / sg13g2_hv_tielo to the library.

Why these are not produced by layout_retarget.py
------------------------------------------------
The thin-oxide tie cells are among the 18 cells the 1-D retarget has to skip:
their NMOS Activ reaches the library channel cut, so the thick-oxide NW.d1
clearance cannot be opened without giving them a different row height. But a
standard cell library with no tie cell cannot be used by a digital flow at
all -- LibreLane calls Yosys' `hilomap` and OpenROAD's `insert_tiecells`
unconditionally, and a constant that reaches a cell input has nowhere else to
go. So the two cells are built here instead, from a cell that *did* retarget.

Construction
------------
Both are `sg13g2_hv_inv_1` with its input tied off inside the cell:

    tielo : A -> VDD, so the NMOS is on and the output sits at VSS
    tiehi : A -> VSS, so the PMOS is on and the output sits at VDD

The tie is one Metal1 rectangle. In the retargeted inverter the A pin
(x 0.310-0.625, y 1.950-2.725) sits directly between the two source straps,
which occupy the same x range (0.330-0.590) and stop at y 1.640 below and
y 3.645 above. Filling either gap at the strap width merges the gate metal
into that rail and touches nothing else -- the only other Metal1 in the band
is the output strap at x >= 1.175, which keeps 0.585 um of clearance.

This differs topologically from the thin-oxide tie cells, which use a
four-transistor chain to avoid putting a gate on a supply rail. Here the gate
is on the rail, and the rail carries the cells' own well and substrate taps,
so the gate is diode-protected against antenna charging -- which is what the
chain buys in the thin-oxide library. The DRC deck's antenna rules are the
check on that claim; see work/drc.

Views written here: GDS, Liberty, CDL, SPICE, Verilog. Run gen_lef.py
afterwards -- it rebuilds every LEF macro from the GDS, these two included.
Idempotent.
"""
import pathlib
import re
import sys

import pya

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "sg13g2_hv_inv_1"

# (new cell, tie rail, output pin, Metal1 rectangle that makes the tie, in um)
TIES = [
    ("sg13g2_hv_tielo", "VDD", "L_LO", (0.330, 2.725, 0.590, 3.645)),
    ("sg13g2_hv_tiehi", "VSS", "L_HI", (0.330, 1.640, 0.590, 1.950)),
]
A_PIN = (0.310, 1.950, 0.625, 2.725)          # gate metal, becomes rail metal
M1 = (8, 0)
M1_PIN = (8, 2)
M1_TXT = (8, 25)


def rewrite_shapes(cell, layer, fn):
    """Apply fn to every shape on a layer; None drops it.

    The concrete object is extracted before the container is touched -- a
    pya.Shape is a reference into the Shapes container, and holding one across
    a clear() reads freed memory (it segfaults rather than raising).
    """
    out = []
    for s in cell.shapes(layer).each():
        if s.is_text():
            obj = s.text.dup()
        elif s.is_box():
            obj = s.box.dup()
        elif s.is_path():
            obj = s.path.dup()
        else:
            obj = s.polygon.dup()
        obj = fn(obj)
        if obj is not None:
            out.append(obj)
    cell.shapes(layer).clear()
    for obj in out:
        cell.shapes(layer).insert(obj)


def build_gds():
    path = ROOT / "gds" / "sg13g2_stdcell_hv.gds"
    ly = pya.Layout()
    ly.read(str(path))
    base = ly.cell(BASE)
    if base is None:
        sys.exit(f"{BASE} not found in {path}")

    made = []
    for name, rail, outpin, rect in TIES:
        if ly.cell(name) is not None:
            ly.delete_cell(ly.cell(name).cell_index())      # rebuild in place
        cell = ly.create_cell(name)
        cell.copy_tree(base)

        # The tie goes on the drawing layer only. A is no longer a pin, so its
        # shape is dropped from the pin layer too -- left there it is a pin
        # group with no label, which is what gen_lef.py asserts on.
        box = pya.Box(*[int(round(v * 1000)) for v in rect])
        cell.shapes(ly.layer(*M1)).insert(box)

        a_box = pya.Box(*[int(round(v * 1000)) for v in A_PIN])
        rewrite_shapes(cell, ly.layer(*M1_PIN),
                       lambda o: None if isinstance(o, pya.Box) and o == a_box
                       else o)

        # relabel: the gate label would name a second net on the rail
        def relabel(o, outpin=outpin):
            if not isinstance(o, pya.Text):
                return o
            if o.string == "A":
                return None                                  # now part of rail
            if o.string == "Y":
                o.string = outpin
            return o

        rewrite_shapes(cell, ly.layer(*M1_TXT), relabel)
        made.append(name)

    ly.write(str(path))
    print(f"GDS: wrote {', '.join(made)} into {path.name}")


def lef_macro(text, name, rail, outpin, rect):
    """Derive the tie cell's LEF macro from the inverter's."""
    m = re.search(rf'MACRO {BASE}\n(.*?)END {BASE}\n', text, re.S)
    body = m.group(1)
    body = body.replace(BASE, name)

    # the A pin is gone: its metal, plus the tie rectangle, become obstruction
    body = re.sub(r'  PIN A\n.*?  END A\n', '', body, flags=re.S)
    body = body.replace("  PIN Y\n", f"  PIN {outpin}\n").replace(
        "  END Y\n", f"  END {outpin}\n")
    extra = (f"        RECT {A_PIN[0]} {A_PIN[1]} {A_PIN[2]} {A_PIN[3]} ;\n"
             f"        RECT {rect[0]} {rect[1]} {rect[2]} {rect[3]} ;\n")
    body = body.replace("  OBS\n      LAYER Metal1 ;\n",
                        "  OBS\n      LAYER Metal1 ;\n" + extra)
    return f"MACRO {name}\n{body}END {name}\n"


def build_lef():
    """Deprecated: gen_lef.py regenerates every macro from the GDS.

    Kept only so an existing hand-built macro is removed if this script is
    re-run against a LEF that still carries one.
    """
    path = ROOT / "lef" / "sg13g2_stdcell_hv.lef"
    text = path.read_text()
    for name, rail, outpin, rect in TIES:
        text = re.sub(rf'MACRO {name}\n.*?END {name}\n', '', text, flags=re.S)
        macro = lef_macro(text, name, rail, outpin, rect)
        # macros belong inside the library: anything after END LIBRARY is
        # silently dropped by the LEF reader, and the cell then has no master
        if "END LIBRARY" in text:
            text = text.replace("END LIBRARY", macro + "\nEND LIBRARY", 1)
        else:
            text = text.rstrip("\n") + "\n\n" + macro
    path.write_text(text)
    print(f"LEF: appended {', '.join(t[0] for t in TIES)}")


def build_lib():
    path = next((ROOT / "lib").glob("*.lib"))
    text = path.read_text()
    m = re.search(rf'\n  cell \({BASE}\) \{{\n    area : ([\d.]+)', text)
    area = m.group(1)
    # The inverter these are built from carries no cell_leakage_power, so the
    # tie cells do not invent one either -- they are uncharacterised, and a
    # borrowed number would read as measured.

    for name, rail, outpin, _ in TIES:
        text = re.sub(rf'\n  cell \({name}\) \{{.*?\n  \}}(?: /\* end cell \*/)?',
                      '', text, flags=re.S)
        entry = (f'\n  cell ({name}) {{\n'
                 f'    area : {area} ;\n'
                 f'    pin ({outpin}) {{\n'
                 f'      direction : output ;\n'
                 f'      function : "{"0" if outpin == "L_LO" else "1"}" ;\n'
                 f'    }} /* end pin */\n'
                 f'  }} /* end cell */\n')
        # keep the file alphabetical: tie* sits before xnor2_1
        anchor = '\n  cell (sg13g2_hv_xnor2_1)'
        text = text.replace(anchor, entry + anchor, 1)
    path.write_text(text)
    print(f"Liberty: added {', '.join(t[0] for t in TIES)} (area {area})")


def build_netlists():
    for fname, kind in (("cdl/sg13g2_stdcell_hv.cdl", "cdl"),
                        ("spice/sg13g2_stdcell_hv.spice", "spice")):
        path = ROOT / fname
        text = path.read_text()
        pat = (rf'\.SUBCKT {BASE} .*?\.ENDS' if kind == "cdl"
               else rf'\.subckt {BASE} .*?\.ends')
        m = re.search(pat, text, re.S | re.I)
        base_txt = m.group(0)
        for name, rail, outpin, _ in TIES:
            text = re.sub(rf'\.SUBCKT {name} .*?\.ENDS\n?', '', text,
                          flags=re.S | re.I)
            body = base_txt.replace(BASE, name)
            # port list: drop A, rename Y
            body = re.sub(rf'({name}) Y A ', rf'\1 {outpin} ', body)
            # device connections: Y -> outpin, gate A -> the rail
            body = re.sub(r'^(\s*[XM]\w+ )Y A ', rf'\g<1>{outpin} {rail} ',
                          body, flags=re.M)
            body = body.replace("*.PININFO A:I Y:O", f"*.PININFO {outpin}:O")
            end = ".ENDS" if kind == "cdl" else ".ends"
            text = text.rstrip("\n") + "\n\n" + body.rstrip("\n") + "\n"
        path.write_text(text)
        print(f"{kind.upper()}: added {', '.join(t[0] for t in TIES)}")


def build_verilog():
    path = ROOT / "verilog" / "sg13g2_stdcell_hv.v"
    text = path.read_text()
    for name, rail, outpin, _ in TIES:
        text = re.sub(rf'module {name} .*?endmodule\n', '', text, flags=re.S)
        val = "1'b0" if outpin == "L_LO" else "1'b1"
        text = text.rstrip("\n") + "\n\n" + (
            f"module {name} ({outpin});\n\n"
            f"\toutput {outpin};\n\n"
            f"\t// Function\n\n"
            f"\tbuf ({outpin}, {val});\n\n"
            f"\t// Timing\n\n"
            f"\tspecify\n"
            f"\tendspecify\n\n"
            f"endmodule\n")
    path.write_text(text)
    print(f"Verilog: added {', '.join(t[0] for t in TIES)}")


if __name__ == "__main__":
    build_gds()
    build_lib()
    build_netlists()
    build_verilog()
