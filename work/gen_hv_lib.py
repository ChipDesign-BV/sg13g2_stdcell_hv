#!/usr/bin/env python3
"""Generate sg13g2_stdcell_hv -- a thick-oxide (3.3 V) variant of the IHP
SG13G2 thin-oxide standard cell library.

Transform applied to every logic device:
  * model    sg13_lv_{n,p}mos            -> sg13_hv_{n,p}mos
  * length   L                           -> max(L, 450 nm)      [DRC Gat.a3]
  * width    NMOS unchanged, PMOS        -> W * KP              [Vm centring]
  * as/ad/ps/pd recomputed with the HV model's own geometry formulas

Symbols are byte-for-byte copies of the LV ones apart from the netlist prefix
and the schematic pointer, so pin names, pin order and drawn geometry are
identical to the thin-oxide library.
"""
import re, pathlib, shutil, datetime

# ---------------------------------------------------------------- constants
SRC = pathlib.Path("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell")
DST = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")

LMIN_HV = 450e-9        # DRC Gat.a3: min GatPoly width for the 3.3 V FET
KP      = 2.40          # global PMOS width factor (see work/vm_sweep.py)
GRID    = 5e-9          # layout grid

# geometry constants from sg13g2_mos{lv,hv}_mod.lib -- identical for both
Z1, Z2, WMIN = 0.34e-6, 0.38e-6, 0.15e-6

SUF = "hv_"             # sg13g2_ -> sg13g2_hv_


def cellname(lv):
    assert lv.startswith("sg13g2_"), lv
    return "sg13g2_" + SUF + lv[len("sg13g2_"):]


# ------------------------------------------------------------- unit helpers
UNIT = {"": 1.0, "n": 1e-9, "u": 1e-6, "p": 1e-12, "f": 1e-15, "m": 1e-3}


def parse_len(s):
    m = re.fullmatch(r"([0-9.]+(?:[eE][+-]?\d+)?)([a-zA-Z]?)", s.strip())
    if not m:
        raise ValueError(s)
    return float(m.group(1)) * UNIT[m.group(2).lower()]


def fmt_len(v):
    """Emit on the 5 nm grid, exactly representable with 3 decimals in um."""
    return f"{v*1e6:.3f}u"


def snap(v):
    return round(v / GRID) * GRID


def fmt_area(v):
    return f"{v:.6g}"


# ------------------------------------------- parasitics, per the model decks
def parasitics(w, ng):
    """Return (as, ad, ps, pd) exactly as sg13g2_mos{lv,hv}_mod.lib computes
    them when the netlist leaves them at zero."""
    wf = max(w / ng, WMIN)
    if ng % 2:                                    # odd number of fingers
        a = wf * (Z1 + ((ng - 1) / 2) * Z2)
        p = 2 * (wf * ((ng - 1) / 2 + 1) + Z1 + (ng - 1) / 2 * Z2)
        return a, a, p, p
    _as = wf * (2 * Z1 + max(0, (ng - 2) / 2) * Z2)
    _ad = wf * Z2 / 2 * ng
    _ps = 2 * (wf * (2 + max(ng - 2, 0) / 2) + 2 * Z1 + max(ng - 2, 0) / 2 * Z2)
    _pd = (wf + Z2) * ng
    return _as, _ad, _ps, _pd


# ------------------------------------------------------- SPICE netlist parse
DEV_RE = re.compile(
    r"^(?P<inst>X\S+)\s+(?P<nets>.+?)\s+(?P<model>sg13_lv_[np]mos)\s+(?P<params>.*)$")
PAR_RE = re.compile(r"(\w+)\s*=\s*(\S+)")


def read_lv_spice():
    cells, cur = [], None
    for raw in (SRC / "spice" / "sg13g2_stdcell.spice").read_text().splitlines():
        line = raw.rstrip()
        if line.startswith(".subckt"):
            t = line.split()
            cur = {"name": t[1], "pins": t[2:], "devs": [], "raw": []}
        elif line.startswith(".ends"):
            cells.append(cur)
            cur = None
        elif cur is not None and line and not line.startswith("*"):
            m = DEV_RE.match(line)
            if m:
                p = dict(PAR_RE.findall(m.group("params")))
                cur["devs"].append({
                    "inst": m.group("inst"), "nets": m.group("nets").split(),
                    "model": m.group("model"), "params": p, "kind": "mos"})
            else:                                  # diodes in sg13g2_antennanp
                cur["devs"].append({"kind": "raw", "line": line})
    return cells


# ------------------------------------- self-check: formulas vs the LV library
def validate(cells):
    """The LV netlist prints as/ad/ps/pd rounded to 4 significant figures, so
    agreement is judged on relative error: anything above ~5e-4 cannot be
    explained by that rounding and means the formula is wrong."""
    TOL = 1e-3
    n = worst = 0
    worst_at = None
    bad = 0
    for c in cells:
        for d in c["devs"]:
            if d["kind"] != "mos":
                continue
            n += 1
            p = d["params"]
            w, ng = parse_len(p["w"]), int(p["ng"])
            _as, _ad, _ps, _pd = parasitics(w, ng)
            for key, got in (("as", _as), ("ad", _ad), ("ps", _ps), ("pd", _pd)):
                want = parse_len(p[key])
                if want == 0:
                    continue
                rel = abs(got - want) / abs(want)
                if rel > worst:
                    worst, worst_at = rel, f"{c['name']}/{d['inst']}/{key}"
                if rel > TOL:
                    bad += 1
                    if bad < 8:
                        print(f"  MISMATCH {c['name']} {d['inst']} {key}: "
                              f"lib={want:.6g} formula={got:.6g} rel={rel:.2e}")
    print(f"parasitic formula self-check: {n} LV devices checked, "
          f"{bad} above {TOL:.0e} relative")
    print(f"  worst relative error {worst:.2e} at {worst_at} "
          f"(4-sig-fig printing alone allows up to 5.0e-04)")
    return bad == 0


# ------------------------------------------------------------ HV device size
def hv_device(d):
    """Return the transformed parameter dict for one MOS device."""
    p = dict(d["params"])
    is_p = d["model"].endswith("pmos")
    ng = int(p["ng"])
    w, l = parse_len(p["w"]), parse_len(p["l"])

    l_new = max(l, LMIN_HV)
    wf = w / ng
    wf_new = snap(wf * KP) if is_p else wf         # snap per finger, not total
    w_new = wf_new * ng

    _as, _ad, _ps, _pd = parasitics(w_new, ng)
    return {
        "model": ("sg13_hv_pmos" if is_p else "sg13_hv_nmos"),
        "w": w_new, "l": l_new, "ng": ng, "m": p.get("m", "1"),
        "as": _as, "ad": _ad, "ps": _ps, "pd": _pd,
        "l_raised": l_new != l, "w_scaled": is_p,
    }


HEADER = """\
************************************************************************
*
* sg13g2_stdcell_hv -- thick-oxide (3.3 V) standard cell library
*
* Derived from the IHP SG13G2 sg13g2_stdcell thin-oxide library by
* substituting the 3.3 V thick-oxide devices. Topology, pin names and pin
* order are unchanged from the thin-oxide cells.
*
*   model   sg13_lv_{{n,p}}mos -> sg13_hv_{{n,p}}mos
*   length  L -> max(L, 450 nm)     DRC Gat.a3, min gate length of the 3.3 V FET
*   width   NMOS unchanged; PMOS x {kp}
*           so the inverter switching threshold stays at Vm/VDD = 0.5046,
*           the value the thin-oxide library is sized to
*   as/ad/ps/pd recomputed from the HV model deck geometry (z1=0.34u, z2=0.38u)
*
* Generated {date} by work/gen_hv_lib.py
*
* Original library Copyright 2023 IHP PDK Authors, Apache License 2.0.
* This derived work is distributed under the same terms.
*
************************************************************************

"""


def emit_spice(cells, hv):
    out = [HEADER.format(kp=KP, date=datetime.date.today().isoformat())]
    for c in cells:
        name = cellname(c["name"])
        out.append(f"* Library name: sg13g2_stdcell_hv")
        out.append(f"* Cell name: {name}")
        out.append(f"* View name: schematic")
        out.append(f".subckt {name} " + " ".join(c["pins"]))
        for d in c["devs"]:
            if d["kind"] == "raw":
                out.append(d["line"])
                continue
            n = hv[(c["name"], d["inst"])]
            out.append(
                f"{d['inst']} {' '.join(d['nets'])} {n['model']} "
                f"w={fmt_len(n['w'])} l={fmt_len(n['l'])} ng={n['ng']} "
                f"ad={fmt_area(n['ad'])} as={fmt_area(n['as'])} "
                f"pd={fmt_area(n['pd'])} ps={fmt_area(n['ps'])} m={n['m']}")
        out.append(".ends")
        out.append("* End of subcircuit definition.")
        out.append("")
    return "\n".join(out)


def emit_cdl(cells, hv):
    src = (SRC / "cdl" / "sg13g2_stdcell.cdl").read_text().splitlines()
    out, cur = [], None
    for line in src:
        s = line.strip()
        if s.startswith("* Library Name:"):
            out.append("* Library Name: sg13g2_stdcell_hv")
            continue
        if s.startswith("* Cell Name:"):
            cur = s.split()[-1]
            out.append(f"* Cell Name:    {cellname(cur)}")
            continue
        if s.upper().startswith(".SUBCKT"):
            t = s.split()
            cur = t[1]
            out.append(f".SUBCKT {cellname(cur)} " + " ".join(t[2:]))
            continue
        m = re.match(r"^(M\S+)\s+(.+?)\s+(sg13_lv_[np]mos)\s+(.*)$", s)
        if m and cur:
            inst = "X" + m.group(1)[1:]            # CDL uses M<n>, SPICE X<n>
            key = (cur, inst)
            if key not in hv:
                key = (cur, m.group(1))
            n = hv[key]
            out.append(f"{m.group(1)} {m.group(2)} {n['model']} m={n['m']} "
                       f"w={fmt_len(n['w'])} l={fmt_len(n['l'])} ng={n['ng']}")
            continue
        out.append(line)
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------- schematics
SYM_RE = re.compile(
    r"(?P<head>C\s*\{sg13_lv_(?P<t>[np])mos\.sym\}[^{]*\{)"
    r"(?P<attr>[^}]*)(?P<tail>\})",
    re.DOTALL)


def emit_sch(cellnames, hv):
    written = 0
    for lv in cellnames:
        src = SRC / "sch" / "xschem" / f"{lv}.sch"
        if not src.exists():
            print(f"  WARNING no schematic for {lv}")
            continue
        txt = src.read_text()

        def sub(m):
            t = m.group("t")
            attr = m.group("attr")
            n = hv_by_symref(hv, lv, attr, t)
            attr = re.sub(r"\bw=\S+", f"w={fmt_len(n['w'])}", attr)
            attr = re.sub(r"\bl=\S+", f"l={fmt_len(n['l'])}", attr)
            attr = re.sub(r"\bmodel=sg13_lv_[np]mos", f"model={n['model']}", attr)
            head = m.group("head").replace(f"sg13_lv_{t}mos.sym",
                                           f"sg13_hv_{t}mos.sym")
            return head + attr + m.group("tail")

        txt = SYM_RE.sub(sub, txt)
        (DST / "sch" / "xschem" / f"{cellname(lv)}.sch").write_text(txt)
        written += 1
    return written


def hv_by_symref(hv, lv, attr, t):
    """Map a schematic MOS instance onto its transformed sizes.

    The schematic instance names (M1, M2, ...) do not match the SPICE instance
    names (XN0, XP1, ...), so match on (type, w, l) instead -- within one cell
    that tuple is what determines the transform, and the transform is a pure
    function of it.
    """
    w = parse_len(re.search(r"\bw=(\S+)", attr).group(1))
    l = parse_len(re.search(r"\bl=(\S+)", attr).group(1))
    ng = int(re.search(r"\bng=(\S+)", attr).group(1))
    fake = {"params": {"w": f"{w}", "l": f"{l}", "ng": str(ng), "m": "1"},
            "model": f"sg13_lv_{t}mos"}
    return hv_device(fake)


# -------------------------------------------------------------------- symbols
def emit_sym(cellnames):
    n = 0
    for lv in cellnames:
        src = SRC / "sym" / "xschem" / f"{lv}.sym"
        if not src.exists():
            print(f"  WARNING no symbol for {lv}")
            continue
        txt = src.read_text()
        # netlist prefix -> sg13g2_hv_  (the @prefix token in format= then
        # produces the thick-oxide subcircuit name)
        txt = txt.replace("prefix=sg13g2_", f"prefix=sg13g2_{SUF}")
        # point the subcircuit at this library's schematic directory
        txt = txt.replace(
            'schematic="tcleval([hierarchy_config @symname])"',
            'schematic="tcleval($::SG13G2_HV_SCH/@symname.sch)"')
        # the LV symbols take their type from the PDK's stdcell view switch;
        # this library has a single view, so pin it to subcircuit
        txt = txt.replace("type=tcleval([symtype])", "type=subcircuit")
        (DST / "sym" / "xschem" / f"{cellname(lv)}.sym").write_text(txt)
        n += 1
    return n


# -------------------------------------------------------------------- verilog
def emit_verilog(cellnames):
    txt = (SRC / "verilog" / "sg13g2_stdcell.v").read_text()
    # longest first so sg13g2_nand2b_1 is not clipped by sg13g2_nand2_1
    for lv in sorted(cellnames, key=len, reverse=True):
        txt = re.sub(rf"\b{re.escape(lv)}\b", cellname(lv), txt)
    return txt


# ----------------------------------------------------------------------- main
def main():
    for d in ("spice", "cdl", "verilog", "sch/xschem", "sym/xschem", "doc",
              "lib", "work"):
        (DST / d).mkdir(parents=True, exist_ok=True)

    cells = read_lv_spice()
    print(f"parsed {len(cells)} cells from the thin-oxide SPICE netlist")
    if not validate(cells):
        raise SystemExit("parasitic formulas disagree with the LV library "
                         "-- refusing to generate")

    hv, raised, scaled = {}, [], 0
    for c in cells:
        for d in c["devs"]:
            if d["kind"] != "mos":
                continue
            n = hv_device(d)
            hv[(c["name"], d["inst"])] = n
            if n["l_raised"]:
                raised.append((c["name"], d["inst"], d["params"]["l"]))
            if n["w_scaled"]:
                scaled += 1

    names = [c["name"] for c in cells]
    (DST / "spice" / "sg13g2_stdcell_hv.spice").write_text(emit_spice(cells, hv))
    (DST / "cdl" / "sg13g2_stdcell_hv.cdl").write_text(emit_cdl(cells, hv))
    (DST / "verilog" / "sg13g2_stdcell_hv.v").write_text(emit_verilog(names))
    nsch = emit_sch(names, hv)
    nsym = emit_sym(names)
    (DST / "doc" / "sg13g2_stdcell_hv.celllist").write_text(
        "\n".join(cellname(n) for n in names) + "\n")

    print(f"wrote {len(cells)} subcircuits, {nsch} schematics, {nsym} symbols")
    print(f"PMOS devices width-scaled by {KP}: {scaled}")
    print(f"devices with L raised to {LMIN_HV*1e9:.0f} nm: {len(raised)}")
    seen = set()
    for cn, inst, l in raised:
        if cn not in seen:
            seen.add(cn)
    print("  cells affected:", ", ".join(sorted(seen)))


if __name__ == "__main__":
    main()
