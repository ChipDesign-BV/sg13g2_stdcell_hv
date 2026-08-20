#!/usr/bin/env python3
"""Generate the Qucs-S views (sch/qucs-s, sym/qucs-s) for sg13g2_stdcell_hv.

The thin-oxide library ships a complete Qucs-S view set: one .sch per cell,
one .xml component definition per cell, and a set of .sym gate-shape files
shared across drive strengths. This produces the thick-oxide equivalent.

Why a transform of the thin-oxide schematics rather than fresh drawings:
the two libraries are topologically identical -- same devices, same nets,
same wiring -- and a checked 84-cell comparison against the shipped SPICE
netlist confirms it, with exactly two exceptions (see TIE_CELLS below).
Redrawing 920 devices by hand would introduce differences the transform
cannot.

Device sizes are taken from the shipped SPICE netlist, never computed. A
formula would be wrong: the nominal transform is L 130 nm -> 450 nm and
PMOS width x 2.40, but the library also clamps L 180 nm -> 450 nm (below
the thick-oxide minimum), scales L 250 nm -> 625 nm, and leaves the
explicitly long devices (500 nm, 700 nm, 1 um) untouched. The map below is
built from the netlist and asserted to be unambiguous before use.
"""
import collections
import pathlib
import re
import shutil
import sys

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
LV = pathlib.Path("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell")
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"

# The two cells whose thick-oxide topology genuinely differs: ours are a
# tied-input inv_1 (gate on the diffusion-clamped rail), not the thin-oxide
# four-transistor chain. Transforming their schematics would ship a drawing
# that contradicts the netlist, so they are built from the netlist instead.
TIE_CELLS = {"tiehi", "tielo"}

DATE = "August 2026"
DRAWN_BY = "ChipDesign B.V."
REVISION = "1.0"


def to_um(s):
    """'1.12u' / '130.00n' -> micrometres."""
    s = s.strip().lower()
    if s.endswith("u"):
        return round(float(s[:-1]), 4)
    if s.endswith("n"):
        return round(float(s[:-1]) / 1000.0, 4)
    return round(float(s), 4)


def fmt(v):
    """Micrometres -> the thin-oxide library's own notation."""
    return f"{v * 1000:.2f}n" if v < 1.0 else f"{v:.3f}u"


DEV_RE = re.compile(
    r'^(  <)(nmos|pmos)( \S+ .*?")sg13_lv_(nmos|pmos)(" 0 "X" 0 "\w+" 0 ")'
    r'([^"]+)(" \d+ ")([^"]+)(")', re.M)


def lv_devices(txt):
    return [(m.group(2), to_um(m.group(6)), to_um(m.group(8)))
            for m in DEV_RE.finditer(txt)]


def hv_devices(cell, spice):
    m = re.search(rf"^\.subckt sg13g2_hv_{re.escape(cell)}\s.*?^\.ends",
                  spice, re.M | re.S)
    if not m:
        return None
    return [(d.group(1), round(float(d.group(2)), 4), round(float(d.group(3)), 4))
            for d in re.finditer(r"sg13_hv_(nmos|pmos) w=([\d.]+)u l=([\d.]+)u",
                                 m.group(0))]


def build_map(cells, spice):
    """{(type, lvW, lvL): (hvW, hvL)}, asserted unambiguous.

    Built by sorting each cell's devices of one type and pairing positionally.
    Devices with equal (W, L) are interchangeable, so any permutation among
    them yields the same map; the assertion below is what makes that safe
    rather than merely likely.
    """
    seen = collections.defaultdict(collections.Counter)
    for cell in cells:
        f = LV / "sch" / "qucs-s" / f"sg13g2_{cell}.sch"
        lv = lv_devices(f.read_text())
        hv = hv_devices(cell, spice)
        assert hv is not None, f"{cell}: no subckt in the SPICE netlist"
        for t in ("nmos", "pmos"):
            a = sorted(x for x in lv if x[0] == t)
            b = sorted(x for x in hv if x[0] == t)
            assert len(a) == len(b), (
                f"{cell}: {t} count {len(a)} in the schematic vs {len(b)} in "
                "the netlist -- topology differs, this cell cannot be "
                "transformed")
            for x, y in zip(a, b):
                seen[x][(y[1], y[2])] += 1
    bad = {k: dict(v) for k, v in seen.items() if len(v) > 1}
    assert not bad, f"ambiguous device mapping: {bad}"
    return {k: next(iter(v)) for k, v in seen.items()}


def transform(cell, txt, dmap):
    """One thin-oxide schematic -> its thick-oxide counterpart."""
    new = f"sg13g2_hv_{cell}"
    old = f"sg13g2_{cell}"

    def dev(m):
        key = (m.group(2), to_um(m.group(6)), to_um(m.group(8)))
        w, l = dmap[key]
        return (m.group(1) + m.group(2) + m.group(3) + f"sg13_hv_{m.group(4)}"
                + m.group(5) + fmt(w) + m.group(7) + fmt(l) + m.group(9))

    txt, n = DEV_RE.subn(dev, txt)
    # Header bookkeeping: the dataset/display/script names follow the cell,
    # and the title block records who drew this one.
    # Rewrite the whole value rather than an exact filename: the thin-oxide
    # library is not consistent here (sg13g2_dlhq_1sch.dat, sg13g2_
    # dfrbpq_1sch.m), and an exact-match replace silently left those two
    # files carrying a thin-oxide name.
    txt = re.sub(r"(<(?:DataSet|DataDisplay|Script)=)sg13g2_(?!hv_)",
                 r"\1sg13g2_hv_", txt)
    txt = re.sub(r"<FrameText0=Title: .*?>", f"<FrameText0=Title: {new}>", txt)
    txt = re.sub(r"<FrameText1=Drawn By: .*?>",
                 f"<FrameText1=Drawn By: {DRAWN_BY}>", txt)
    txt = re.sub(r"<FrameText2=Date: .*?>", f"<FrameText2=Date: {DATE}>", txt)
    txt = re.sub(r"<FrameText3=Revision: .*?>",
                 f"<FrameText3=Revision: {REVISION}>", txt)
    assert "sg13_lv_" not in txt, f"{cell}: a thin-oxide device survived"
    stale = re.findall(r"\bsg13g2_(?!hv_)\w*", txt)
    assert not stale, f"{cell}: thin-oxide names survived: {sorted(set(stale))}"
    return txt, n


def transform_xml(cell, txt):
    new = f"sg13g2_hv_{cell}"
    # The cell name appears as an attribute, as a model value and inside the
    # parameter description, so rewrite every occurrence rather than the
    # three that happened to be noticed.
    txt = re.sub(r"\bsg13g2_(?!hv_)", "sg13g2_hv_", txt)
    txt = txt.replace('library="IHP SG13G2 Standard Cells"',
                      'library="IHP SG13G2 Thick-Oxide (3.3 V) Standard Cells"')
    stale = re.findall(r"\bsg13g2_(?!hv_)\w*", txt)
    assert not stale, f"{cell}: thin-oxide names survived: {sorted(set(stale))}"
    assert new in txt, f"{cell}: {new} missing from the component XML"
    return txt


# The thick-oxide tie cells are an inv_1 with the gate clamped to a rail:
#   tiehi  gate -> VSS, so the PMOS conducts and L_HI sits at VDD
#   tielo  gate -> VDD, so the NMOS conducts and L_LO sits at VSS
# Rather than draw them, take the verified inv_1 geometry, drop the input
# port, and tie the gate net to the appropriate rail. The gate runs
# vertically at x=775 between y=300 and y=700, and both rails span x=679..805,
# so a single vertical segment at x=775 reaches either one.
TIE = {
    "tiehi": ("L_HI", "<775 700 775 750 \"\" 0 0 0 \"\">"),   # down to VSS
    "tielo": ("L_LO", "<775 250 775 300 \"\" 0 0 0 \"\">"),   # up to VDD
}


def build_tie(cell, inv_txt, lv_txt):
    """Compose a tie cell from inv_1's devices and the thin-oxide symbol.

    The symbol, ports and frame come from the thin-oxide tie cell -- its
    interface (L_HI/L_LO, VDD, VSS) is the one we implement -- while the
    device network comes from our own inv_1, because the thick-oxide cell is
    a two-transistor circuit and the thin-oxide one is four.
    """
    port, tie_wire = TIE[cell]
    new = f"sg13g2_hv_{cell}"

    head = lv_txt[:lv_txt.index("<Components>")]
    head = head.replace(f"sg13g2_{cell}.dat", f"{new}.dat")
    head = head.replace(f"sg13g2_{cell}.dpl", f"{new}.dpl")
    head = head.replace(f"sg13g2_{cell}.m", f"{new}.m")
    head = re.sub(r"<FrameText0=Title: .*?>", f"<FrameText0=Title: {new}>", head)
    head = re.sub(r"<FrameText1=Drawn By: .*?>",
                  f"<FrameText1=Drawn By: {DRAWN_BY}>", head)
    head = re.sub(r"<FrameText2=Date: .*?>", f"<FrameText2=Date: {DATE}>", head)
    head = re.sub(r"<FrameText3=Revision: .*?>",
                  f"<FrameText3=Revision: {REVISION}>", head)

    comps, wires = [], []
    for line in inv_txt[inv_txt.index("<Components>"):].splitlines():
        s = line.strip()
        if s.startswith("<Port A "):
            continue                                  # no input pin
        if s.startswith("<Port Y "):
            line = line.replace("<Port Y ", f"<Port {port} ")
            line = line.replace('"1" 1 "out"', '"1" 1 "out"')
        elif s.startswith("<Port VDD "):
            line = line.replace('"3" 1 "inout"', '"2" 1 "inout"')
        elif s.startswith("<Port VSS "):
            line = line.replace('"4" 1 "inout"', '"3" 1 "inout"')
        if s.startswith("<715 500 775 500"):
            continue                                  # the old input wire
        if s == "</Wires>":
            wires.append("  " + tie_wire)
        (wires if (wires or s == "<Wires>") else comps).append(line)
    body = "\n".join(comps + wires)
    return head + body + "\n"


def main():
    spice = SPICE.read_text()
    lv_sch = LV / "sch" / "qucs-s"
    cells = sorted(p.stem.replace("sg13g2_", "") for p in lv_sch.glob("*.sch"))
    doable = [c for c in cells if c not in TIE_CELLS]
    dmap = build_map(doable, spice)
    print(f"device map: {len(dmap)} distinct (type, W, L) -> (W, L), "
          "no ambiguity")

    out_sch = HV / "sch" / "qucs-s"
    out_sym = HV / "sym" / "qucs-s"
    out_sch.mkdir(parents=True, exist_ok=True)
    out_sym.mkdir(parents=True, exist_ok=True)

    n_dev = 0
    for cell in doable:
        txt, n = transform(cell, (lv_sch / f"sg13g2_{cell}.sch").read_text(),
                           dmap)
        (out_sch / f"sg13g2_hv_{cell}.sch").write_text(txt)
        n_dev += n
    print(f"schematics: {len(doable)} written, {n_dev} devices retargeted")

    inv = (out_sch / "sg13g2_hv_inv_1.sch").read_text()
    for cell in sorted(TIE_CELLS):
        lv = (lv_sch / f"sg13g2_{cell}.sch").read_text()
        (out_sch / f"sg13g2_hv_{cell}.sch").write_text(
            build_tie(cell, inv, lv))
    print(f"            {len(TIE_CELLS)} tie cells composed from inv_1: "
          f"{', '.join(sorted(TIE_CELLS))}")

    # Component XML: one per cell, including the tie cells -- only names and
    # models change there, and those are correct regardless of topology.
    lv_sym = LV / "sym" / "qucs-s"
    n_xml = 0
    for p in sorted(lv_sym.glob("*.xml")):
        cell = p.stem.replace("sg13g2_", "")
        (out_sym / f"sg13g2_hv_{cell}.xml").write_text(
            transform_xml(cell, p.read_text()))
        n_xml += 1
    # Gate shapes are function-level and identical between the libraries.
    n_sym = 0
    for p in sorted(lv_sym.glob("*.sym")):
        shutil.copy2(p, out_sym / p.name)
        n_sym += 1
    print(f"symbols: {n_xml} component XML, {n_sym} shared .sym geometry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
