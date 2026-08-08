#!/usr/bin/env python3
"""Check the xschem schematics and the CDL against the SPICE netlist.

All three views are produced by different code paths in gen_hv_lib.py: the
SPICE netlist is rewritten from the thin-oxide netlist device by device, the
CDL is rewritten from the thin-oxide CDL, and the schematics are rewritten by
substituting symbol attributes in place. A device that got the wrong width,
length or model in one view but not another would pass every simulation-based
check, because those all run on the SPICE netlist. So both other views are
compared against it.

Compared per cell: the subcircuit pin list, and the multiset of
(model, w, l, ng, m) over all devices. Connectivity is not compared because
the schematics inherit their wiring unchanged from the thin-oxide originals --
only component attributes were touched -- but the pin list is, since that is
what the rest of the design sees.
"""
import subprocess, re, pathlib, sys, os, tempfile, shutil

WORK = pathlib.Path(__file__).parent
HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
XSCHEM = "/foss/tools/bin/xschem"

RC = """
set ::env(PDK) ihp-sg13g2
set ::env(PDK_ROOT) /foss/pdks
source /foss/pdks/ihp-sg13g2/libs.tech/xschem/xschemrc
source {tcl}
set netlist_dir {out}
""".strip()

DEV = re.compile(
    r"^(X\S+)\s+(.+?)\s+(sg13_hv_[np]mos)\s+(.*)$")
CDL_DEV = re.compile(
    r"^(M\S+)\s+(.+?)\s+(sg13_hv_[np]mos)\s+(.*)$")
PAR = re.compile(r"(\w+)\s*=\s*(\S+)")


def norm(v):
    """Normalise a SPICE number so 0.740u and 740.00n compare equal."""
    m = re.fullmatch(r"([0-9.]+(?:[eE][+-]?\d+)?)([a-zA-Z]?)", v.strip())
    if not m:
        return v
    mul = {"": 1.0, "n": 1e-9, "u": 1e-6, "p": 1e-12, "f": 1e-15, "m": 1e-3}
    return round(float(m.group(1)) * mul[m.group(2).lower()], 15)


def devices(text, dev_re=DEV):
    """Sorted multiset of device tuples from a .subckt body."""
    out = []
    for line in text.splitlines():
        m = dev_re.match(line.strip())
        if not m:
            continue
        p = dict(PAR.findall(m.group(4)))
        out.append((m.group(3), norm(p.get("w", "0")), norm(p.get("l", "0")),
                    int(p.get("ng", 1)), int(p.get("m", 1))))
    return sorted(out)


def subckts(path, dev_re=DEV):
    """{cell: (pins, devices)} from a SPICE-like netlist."""
    cells, cur, buf, pins = {}, None, [], None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.lower().startswith(".subckt"):
            t = s.split()
            cur, pins, buf = t[1], t[2:], []
        elif s.lower().startswith(".ends") and cur:
            cells[cur] = (pins, devices("\n".join(buf), dev_re))
            cur = None
        elif cur is not None:
            buf.append(line)
    return cells


def spice_cells():
    return subckts(HV / "spice" / "sg13g2_stdcell_hv.spice")


def wrapper(cells):
    """A schematic instantiating every cell symbol.

    Netlisting a cell schematic directly makes it the top-level circuit, which
    xschem emits as a commented `**.subckt`. Instantiating the symbols instead
    makes xschem descend through each symbol into its schematic and emit a real
    .subckt for each -- which also exercises the symbol -> schematic resolution
    that xschem_lib_sg13g2_stdcell_hv.tcl sets up, for all 84 cells at once.
    """
    L = ["v {xschem version=3.4.7 file_version=1.2}", "G {}", "K {}", "V {}",
         "S {}", "E {}"]
    for i, c in enumerate(cells):
        L.append(f"C {{{c}.sym}} {(i % 12) * 200} {(i // 12) * 200} 0 0 "
                 f"{{name=x{i}}}")
    return "\n".join(L) + "\n"


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="schcheck_"))
    (tmp / "xschemrc").write_text(
        RC.format(tcl=HV / "xschem_lib_sg13g2_stdcell_hv.tcl", out=tmp))

    spice = spice_cells()
    # sg13g2_hv_stdcells.sch is the gallery sheet, not a cell -- it lives in
    # the same directory so xschem can open it by name, but it has no symbol
    # and netlists to nothing.
    cells = sorted(p.stem for p in (HV / "sch" / "xschem").glob("*.sch")
                   if p.stem != "sg13g2_hv_stdcells")
    (tmp / "all_cells.sch").write_text(wrapper(cells))
    print(f"netlisting {len(cells)} schematics with xschem and comparing "
          f"against {len(spice)} SPICE subcircuits\n")

    p = subprocess.run(
        [XSCHEM, "--rcfile", str(tmp / "xschemrc"), "-n", "-q", "--no_x",
         str(tmp / "all_cells.sch")],
        cwd=tmp, capture_output=True, text=True, timeout=1800)
    out = tmp / "all_cells.spice"
    if not out.exists():
        print("xschem produced no netlist")
        print((p.stdout + p.stderr)[-3000:])
        return 1
    txt = out.read_text()

    bad, checked, ndev = [], 0, 0
    for cell in cells:
        m = re.search(rf"^\.subckt\s+{re.escape(cell)}\s+(.*)$", txt, re.M)
        if not m:
            bad.append((cell, "no .subckt emitted by xschem", ""))
            continue
        sch_pins = m.group(1).split()
        body = txt[m.end():txt.index(".ends", m.end())]
        sch_devs = devices(body)

        sp_pins, sp_devs = spice[cell]
        checked += 1
        ndev += len(sch_devs)
        if sch_pins != sp_pins:
            bad.append((cell, "pin list differs",
                        f"sch={sch_pins} spice={sp_pins}"))
        elif sch_devs != sp_devs:
            only_s = [d for d in sch_devs if d not in sp_devs]
            only_p = [d for d in sp_devs if d not in sch_devs]
            bad.append((cell, "devices differ",
                        f"sch-only={only_s[:3]} spice-only={only_p[:3]}"))
        else:
            print(f"  {cell:26s} {len(sch_devs):2d} devices, pins + sizes match",
                  flush=True)

    print(f"\nschematics: {checked}/{len(cells)} cells checked, "
          f"{ndev} devices compared")

    # --- CDL vs SPICE ---
    cdl = subckts(HV / "cdl" / "sg13g2_stdcell_hv.cdl", CDL_DEV)
    ncdl = 0
    for cell in sorted(spice):
        if cell not in cdl:
            bad.append((cell, "missing from the CDL", ""))
            continue
        sp_pins, sp_devs = spice[cell]
        cd_pins, cd_devs = cdl[cell]
        ncdl += len(cd_devs)
        if sp_pins != cd_pins:
            bad.append((cell, "CDL pin list differs",
                        f"cdl={cd_pins} spice={sp_pins}"))
        elif sp_devs != cd_devs:
            bad.append((cell, "CDL devices differ", ""))
    extra = sorted(set(cdl) - set(spice))
    for cell in extra:
        bad.append((cell, "in the CDL but not the SPICE netlist", ""))
    print(f"CDL       : {len(cdl)}/{len(spice)} cells checked, "
          f"{ncdl} devices compared")

    if bad:
        print("\nmismatches:")
        for c, what, detail in bad[:25]:
            print(f"  {c:26s} {what}: {detail}")
    ok = not bad and checked == len(cells) and len(cdl) == len(spice)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
