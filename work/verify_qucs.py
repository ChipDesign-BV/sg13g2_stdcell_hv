#!/usr/bin/env python3
"""Gate the generated Qucs-S views against the shipped SPICE netlist.

Text substitution is easy to get subtly wrong, and 84 schematics is far past
the point where anyone will read them. Three checks, each matched to how the
file was produced:

1. **Strict diff against the thin-oxide original** (82 transformed cells).
   The transform rewrites device model, W and L, and a handful of header
   lines -- nothing else. So every differing line must be one of those, and
   a changed wire or coordinate is a hard failure. This is a stronger claim
   than re-deriving connectivity: it proves the geometry was not touched at
   all, and the thin-oxide topology is the authority.

2. **Device sizes against the netlist** (all 84 cells). Count, type and
   (W, L) multiset per cell must equal the shipped SPICE subcircuit.

3. **Full connectivity** (the 2 tie cells). These are the only schematics
   whose wiring this project composed rather than inherited, so they get an
   actual netlist extraction from the wire graph and a comparison against
   SPICE, terminal by terminal.

Why not extract connectivity for all 84: 73 of the 920 device instances are
rotated or mirrored, so a general extractor has to reimplement Qucs's
placement transforms. Check 1 makes that unnecessary for the cells that were
inherited, and check 3 covers the cells that were not. The tie cells are
placed unrotated, so the fixed pin offsets below are exact for them.

Pin offsets, calibrated against inv_1 (XN0 Y A VSS VSS / XP0 Y A VDD VDD):
NMOS and PMOS carry opposite drain/source orientation, and the bulk pin sits
a short step toward the source side.

    nmos  g(-30,0)  d(0,-30)  s(0,+30)  b(0,+5)
    pmos  g(-30,0)  d(0,+30)  s(0,-30)  b(0,-5)

Usage:  ./verify_qucs.py        (exit 1 on any failure)
"""
import collections
import pathlib
import re
import sys

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
SCH = HV / "sch" / "qucs-s"
SYM = HV / "sym" / "qucs-s"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"

LV = pathlib.Path("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/sch/qucs-s")
TIE_CELLS = {"sg13g2_hv_tiehi", "sg13g2_hv_tielo"}

PIN_OFF = {
    "nmos": {"g": (-30, 0), "d": (0, -30), "s": (0, 30), "b": (0, 5)},
    "pmos": {"g": (-30, 0), "d": (0, 30), "s": (0, -30), "b": (0, -5)},
}

errors = []


def err(msg):
    errors.append(msg)
    print(f"  FAIL  {msg}")


def to_um(s):
    s = s.strip().lower()
    if s.endswith("u"):
        return round(float(s[:-1]), 4)
    if s.endswith("n"):
        return round(float(s[:-1]) / 1000.0, 4)
    return round(float(s), 4)


class Nets:
    """Union-find over integer points, with T-junction merging."""

    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def on_segment(pt, a, b):
    """Is pt strictly inside the axis-aligned segment a-b?"""
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    if x1 == x2 == x:
        return min(y1, y2) < y < max(y1, y2)
    if y1 == y2 == y:
        return min(x1, x2) < x < max(x1, x2)
    return False


def parse(path):
    txt = path.read_text()
    ports, devs, wires = [], [], []
    for m in re.finditer(r'^  <Port (\S+) \d+ (-?\d+) (-?\d+) .*?"(\d+)" \d+ "(\w+)"',
                         txt, re.M):
        ports.append((m.group(1), (int(m.group(2)), int(m.group(3))),
                      int(m.group(4)), m.group(5)))
    for m in re.finditer(
            r'^  <(nmos|pmos) (\S+) \d+ (-?\d+) (-?\d+) .*?"sg13_hv_\w+" 0 "X" 0 '
            r'"\w+" 0 "([^"]+)" \d+ "([^"]+)"', txt, re.M):
        devs.append({"type": m.group(1), "name": m.group(2),
                     "at": (int(m.group(3)), int(m.group(4))),
                     "w": to_um(m.group(5)), "l": to_um(m.group(6))})
    for m in re.finditer(r"^  <(-?\d+) (-?\d+) (-?\d+) (-?\d+) ", txt, re.M):
        wires.append(((int(m.group(1)), int(m.group(2))),
                      (int(m.group(3)), int(m.group(4)))))
    return ports, devs, wires


def netlist(path):
    ports, devs, wires = parse(path)
    n = Nets()
    pts = set()
    for a, b in wires:
        n.union(a, b)
        pts.update((a, b))
    for _, at, _, _ in ports:
        pts.add(at)
    for d in devs:
        for off in PIN_OFF[d["type"]].values():
            pts.add((d["at"][0] + off[0], d["at"][1] + off[1]))
    # T junctions: a point sitting part-way along a wire joins that wire.
    for p in pts:
        for a, b in wires:
            if on_segment(p, a, b):
                n.union(p, a)
    label = {}
    for name, at, _, _ in ports:
        label[n.find(at)] = name
    out = []
    for d in devs:
        sig = {}
        for pin, off in PIN_OFF[d["type"]].items():
            pt = (d["at"][0] + off[0], d["at"][1] + off[1])
            sig[pin] = label.get(n.find(pt), "int")
        out.append((d["type"], d["w"], d["l"], sig["g"], sig["s"], sig["d"],
                    sig["b"]))
    return ports, out


def spice_cells():
    txt = SPICE.read_text()
    cells = {}
    for m in re.finditer(r"^\.subckt (\S+)((?: \S+)*)\n(.*?)^\.ends", txt,
                         re.M | re.S):
        cells[m.group(1)] = (m.group(2).split(), m.group(3))
    return cells


def spice_sig(body, ports):
    """Same signature form, from the SPICE subcircuit."""
    out = []
    for m in re.finditer(
            r"^\S+ (\S+) (\S+) (\S+) (\S+) sg13_hv_(nmos|pmos) w=([\d.]+)u "
            r"l=([\d.]+)u", body, re.M):
        d, g, s, b = m.group(1), m.group(2), m.group(3), m.group(4)
        f = lambda x: x if x in ports else "int"
        out.append((m.group(5), round(float(m.group(6)), 4),
                    round(float(m.group(7)), 4), f(g), f(s), f(d), f(b)))
    return out


DEV_LINE = re.compile(
    r'^(  <(?:nmos|pmos) \S+ \d+ -?\d+ -?\d+ -?\d+ -?\d+ \d \d ")'
    r'sg13_(?:lv|hv)_(\w+)(" 0 "X" 0 "\w+" 0 ")([^"]+)(" \d+ ")([^"]+)(".*)$')

HEADER_KEYS = ("<DataSet=", "<DataDisplay=", "<Script=", "<FrameText0=",
               "<FrameText1=", "<FrameText2=", "<FrameText3=")


def diff_ok(cell, hv_txt, lv_txt):
    """Every differing line must be a device resize or a header field."""
    a, b = lv_txt.splitlines(), hv_txt.splitlines()
    if len(a) != len(b):
        err(f"{cell}: line count {len(b)} vs thin-oxide {len(a)} -- the "
            "transform must not add or remove lines")
        return
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x == y:
            continue
        mx, my = DEV_LINE.match(x), DEV_LINE.match(y)
        if mx and my:
            # same device, same place, same orientation: only model/W/L move
            if mx.group(1) != my.group(1) or mx.group(3) != my.group(3):
                err(f"{cell}:{i}: device geometry changed, not just its size")
            continue
        if any(k in x for k in HEADER_KEYS) and any(k in y for k in HEADER_KEYS):
            continue
        err(f"{cell}:{i}: unexpected change\n        thin: {x.strip()}\n"
            f"        thick: {y.strip()}")


def sizes(txt, pat):
    out = collections.Counter()
    for m in re.finditer(pat, txt, re.M):
        out[(m.group(1), to_um(m.group(2)), to_um(m.group(3)))] += 1
    return out


def main():
    cells = spice_cells()
    sch = sorted(SCH.glob("*.sch"))
    print(f"schematics: {len(sch)}")

    # --- 1. transformed cells: nothing but sizes and headers may differ ----
    n_diff = 0
    for f in sch:
        if f.stem in TIE_CELLS:
            continue
        lv = LV / f"sg13g2_{f.stem.replace('sg13g2_hv_', '')}.sch"
        if not lv.exists():
            err(f"{f.stem}: no thin-oxide original to compare against")
            continue
        diff_ok(f.stem, f.read_text(), lv.read_text())
        n_diff += 1
    print(f"diffed against the thin-oxide originals: {n_diff} "
          "(geometry and wiring must be untouched)")

    # --- 2. every cell: device sizes match the shipped netlist -------------
    n_dev = 0
    for f in sch:
        name = f.stem
        if name not in cells:
            err(f"{name}: no matching .subckt in the SPICE netlist")
            continue
        sp_ports, body = cells[name]
        got = sizes(f.read_text(),
                    r'<(nmos|pmos) \S+ .*?"sg13_hv_\w+" 0 "X" 0 "\w+" 0 '
                    r'"([^"]+)" \d+ "([^"]+)"')
        want = sizes(body, r"sg13_hv_(nmos|pmos) w=([\d.]+)u l=([\d.]+)u")
        n_dev += sum(got.values())
        if got != want:
            err(f"{name}: device sizes differ from the netlist\n"
                f"        only in schematic: {sorted((got - want).elements())}\n"
                f"        only in netlist:   {sorted((want - got).elements())}")
        ports, _ = netlist(f)
        pnames = [q[0] for q in sorted(ports, key=lambda q: q[2])]
        if pnames != sp_ports:
            err(f"{name}: ports {pnames} vs netlist {sp_ports}")
    print(f"device sizes checked against the netlist: {n_dev}")

    # --- 3. the composed tie cells: full connectivity ----------------------
    for name in sorted(TIE_CELLS):
        f = SCH / f"{name}.sch"
        sp_ports, body = cells[name]
        _, got = netlist(f)
        want = spice_sig(body, set(sp_ports))
        if collections.Counter(got) != collections.Counter(want):
            err(f"{name}: connectivity differs from the netlist\n"
                f"        schematic: {sorted(got)}\n"
                f"        netlist:   {sorted(want)}")
        else:
            print(f"connectivity: {name} matches the netlist "
                  f"({len(got)} devices, terminal by terminal)")

    # --- 4. component XML --------------------------------------------------
    xml = sorted(SYM.glob("*.xml"))
    print(f"component XML: {len(xml)}")
    for x in xml:
        s = x.read_text()
        if x.stem not in cells:
            err(f"{x.name}: names a cell that is not in the netlist")
        m = re.search(r"COMPONENTS_LIBRARY\}/(\S+\.sym)", s)
        if not m:
            err(f"{x.name}: no symbol reference")
        elif not (SYM / m.group(1)).exists():
            err(f"{x.name}: references missing symbol {m.group(1)}")
    for f in sch + xml:
        s = f.read_text()
        for bad in ("sg13_lv_", "IHP SG13G2 Standard Cells"):
            if bad in s:
                err(f"{f.name}: thin-oxide string {bad!r} survived")
        if re.search(r"\bsg13g2_(?!hv_)", s):
            err(f"{f.name}: thin-oxide cell name survived")

    print()
    if errors:
        print(f"RESULT: FAIL ({len(errors)} errors)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
