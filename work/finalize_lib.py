#!/usr/bin/env python3
"""Finalize the shipped Liberty for P&R consumption.

Three gaps surfaced when the library was smoke-tested with LibreLane on
the IHP-Open-PDK PR #1103 draft (an 8-bit counter, reviewed by Simon
Dorrer), all fixed here as data post-processing on the shipped .lib:

  limits -- the library carried no max_capacitance / max_transition at
      all. OpenSTA then answers "no limit" everywhere, LibreLane's
      max-cap/max-slew checks pass vacuously, and OpenROAD's TritonCTS
      crashes (buffer selection returns an empty cell name and
      getBufferFanoutLimit dereferences it). The limits are derived from
      the characterization itself, not copied from the thin-oxide
      library: an output pin may not be asked to drive more load than
      its tables cover, nor any pin to accept a slower edge than was
      characterized. So per output pin max_capacitance = the top of its
      load axis, per pin max_transition = the top of the slew axis it
      was characterized against, and the library gets the matching
      default_max_capacitance (weakest drive class) and
      default_max_transition (slowest characterized edge).

  stubs -- the physical-only macros (fill_*, decap_*, antennanp) had no
      liberty entry, so filler/decap insertion and diode insertion
      produce cells STA has never heard of. They get area-only stubs in
      the thin-oxide library's style (dont_touch/dont_use,
      is_filler_cell/is_decap_cell). Leakage for the decaps and the
      antenna diode, and the diode's pin capacitance, are measured with
      ngspice from the shipped SPICE netlists -- same approach as
      tie_leakage.py -- not borrowed from the thin-oxide numbers.

  rename -- library () was named plain sg13g2_stdcell_hv; upstream names
      each corner file's library after the corner
      (sg13g2_stdcell_typ_1p20V_25C). Renamed to match the filename.

Every step is idempotent; re-running changes nothing.

strip_layoutless() is not part of the in-repo run: make_pdk_pr.py calls
it on the INSTALLED copy so the PDK ships only cells that can actually
be placed (liberty as a subset of LEF), while the characterization data
for the not-yet-drawn flops stays in this repository.

Usage: python3 finalize_lib.py
"""
import os
import re
import subprocess
import pathlib
import sys

import klayout.db as db

HV = pathlib.Path(__file__).resolve().parent.parent
LIB = HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
GDS = HV / "gds" / "sg13g2_stdcell_hv.gds"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models"

VDD = 3.3
STUBS = ["sg13g2_hv_fill_1", "sg13g2_hv_fill_2", "sg13g2_hv_fill_4",
         "sg13g2_hv_fill_8", "sg13g2_hv_decap_4", "sg13g2_hv_decap_8",
         "sg13g2_hv_antennanp"]

# Characterized in the liberty but not drawn; stripped from the installed
# PDK copy by make_pdk_pr.py. Kept here as the expected set so a drift
# between the views fails loudly instead of silently shipping more or
# fewer cells.
LAYOUTLESS = {
    "sg13g2_hv_dfrbp_1", "sg13g2_hv_dfrbp_2",
    "sg13g2_hv_dfrbpq_1", "sg13g2_hv_dfrbpq_2",
    "sg13g2_hv_sdfrbp_1", "sg13g2_hv_sdfrbp_2",
    "sg13g2_hv_sdfrbpq_1", "sg13g2_hv_sdfrbpq_2",
    "sg13g2_hv_dlhq_1", "sg13g2_hv_dlhr_1",
    "sg13g2_hv_dllr_1", "sg13g2_hv_dllrq_1",
}


def fmt(v):
    return f"{v:g}"


def cell_groups(txt):
    return {m.group(2): m for m in re.finditer(
        r"(^  cell \((\S+)\) \{.*?^  \}(?: /\* end cell \*/)?\n)",
        txt, re.S | re.M)}


# --- limits ------------------------------------------------------------------

def axis_top(table_body, index):
    m = re.search(rf"{index} \(\"([^\"]+)\"\)", table_body)
    return max(float(x) for x in m.group(1).split(",")) if m else None


def pin_limits(cell_body):
    """Per-pin (max_capacitance, max_transition) from the table axes.

    The delay templates declare variable_1 = total_output_net_capacitance
    (the opposite axis order from IHP's thin-oxide lib), so index_1 is
    the load axis and index_2 the input slew; the constraint template
    puts the constrained pin's slew on index_1. Read from those
    declarations' consequences, not from thin-oxide habits.
    """
    pins = {}          # name -> dict(direction, body)
    for pm in re.finditer(r"^    pin \((\S+)\) \{.*?^    \}",
                          cell_body, re.S | re.M):
        d = re.search(r"direction : (\w+)", pm.group(0))
        pins[pm.group(1)] = {"dir": d.group(1) if d else "?",
                             "body": pm.group(0)}

    # slew tops seen by each input pin: as related_pin of a delay arc...
    slew_of = {}
    for tm in re.finditer(r"timing \(\) \{.*?^      \}", cell_body,
                          re.S | re.M):
        rel = re.search(r"related_pin : (\S+) ;", tm.group(0))
        top = axis_top(tm.group(0), "index_2")
        if rel and top:
            slew_of.setdefault(rel.group(1), []).append(top)

    out = {}
    all_slews = []
    for name, p in pins.items():
        cap = tran = None
        tops1 = [axis_top(t.group(0), "index_1") for t in re.finditer(
            r"(cell_rise|cell_fall|rise_transition|fall_transition)"
            r" \(delay_\S+\) \{.*?\}", p["body"], re.S)]
        tops1 = [t for t in tops1 if t]
        if p["dir"] == "output" and tops1:
            cap = min(tops1)                    # load axis coverage
            tran = axis_top(p["body"], "index_2")
        elif p["dir"] == "input":
            cands = slew_of.get(name, [])
            # ...or as the constrained pin of a setup/hold group
            cands += [t for t in (axis_top(c.group(0), "index_1")
                                  for c in re.finditer(
                          r"(rise|fall)_constraint \(\S+\) \{.*?\}",
                          p["body"], re.S)) if t]
            if cands:
                tran = min(cands)               # within every axis it is on
        if tran:
            all_slews.append(tran)
        out[name] = (cap, tran)
    # inputs with no arcs at all (RESET_B/SET_B have none): bound them by
    # the slowest edge the rest of the cell was characterized with
    for name, p in pins.items():
        if p["dir"] == "input" and out[name] == (None, None) and all_slews:
            out[name] = (None, max(all_slews))
    return out


def inject_limits(txt):
    n_cap = n_tran = 0
    caps, trans = [], []
    for name, m in cell_groups(txt).items():
        body = new_body = m.group(1)
        for pin, (cap, tran) in pin_limits(body).items():
            pin_pat = rf"(^    pin \({re.escape(pin)}\) \{{\n" \
                      rf"      direction : \w+ ;\n)"
            pin_m = re.search(pin_pat, new_body, re.M)
            if not pin_m:
                continue
            ins = ""
            already = re.search(rf"^    pin \({re.escape(pin)}\) \{{.*?^    \}}",
                                new_body, re.S | re.M).group(0)
            if cap and "max_capacitance" not in already:
                ins += f"      max_capacitance : {fmt(cap)} ;\n"
                n_cap += 1
                caps.append(cap)
            if tran and "max_transition" not in already:
                ins += f"      max_transition : {fmt(tran)} ;\n"
                n_tran += 1
                trans.append(tran)
            if ins:
                new_body = (new_body[:pin_m.end()] + ins +
                            new_body[pin_m.end():])
        if new_body != body:
            txt = txt.replace(body, new_body, 1)

    if caps and "default_max_capacitance" not in txt:
        anchor = re.search(r"^  capacitive_load_unit \(1, pF\);\n", txt, re.M)
        assert anchor, "capacitive_load_unit line not found"
        txt = (txt[:anchor.end()] +
               f"  default_max_capacitance : {fmt(min(caps))} ;\n"
               f"  default_max_transition : {fmt(max(trans))} ;\n" +
               txt[anchor.end():])
    print(f"limits: {n_cap} max_capacitance, {n_tran} max_transition pins")
    return txt


# --- stubs -------------------------------------------------------------------

def ngspice(deck_text, name, meas):
    scratch = pathlib.Path("/tmp/claude-1000") / "finalize_lib"
    scratch.mkdir(parents=True, exist_ok=True)
    deck = scratch / f"{name}.sp"
    deck.write_text(deck_text)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = f"{SHIM}:" + env.get("PATH", "/usr/bin:/bin")
    r = subprocess.run(["ngspice", "-b", str(deck)],
                       capture_output=True, text=True, timeout=300, env=env)
    m = re.search(rf"{meas}\s*=\s*(-?[0-9.e+-]+)", r.stdout + r.stderr)
    if not m:
        raise RuntimeError(f"{name}: no {meas} measure\n{r.stdout[-500:]}")
    return float(m.group(1))


def measure_leakage(cell, ports):
    conns = {"VDD": "vdd", "VSS": "0"}
    lines = [f"* leakage {cell}",
             f".lib {MODELS}/cornerMOShv.lib mos_tt",
             f".include {MODELS}/diodes.lib",
             f".include {SPICE}",
             f"Vdd vdd 0 {VDD}",
             "Xdut " + " ".join(conns.get(p.upper(), f"o{p}")
                                for p in ports) + f" {cell}",
             ".tran 0.5n 60n",
             ".meas tran ivdd AVG i(Vdd) from=40n to=60n",
             ".control", "run", ".endc", ".end"]
    i_a = abs(ngspice("\n".join(lines) + "\n", f"leak_{cell}", "ivdd"))
    return i_a * VDD * 1e9          # nW


def measure_pin_cap(cell, pin, ports):
    """Small-signal input capacitance, averaged over the swing.

    Charge integration (the characterization's method for gate pins) is
    unusable here: the antenna diodes' breakdown model forces ~1 ps
    transient steps and the deck runs for minutes. The pin is a pair of
    reverse-biased junctions, so a 1 MHz AC measurement of the branch
    current at a few DC bias points -- Cin = Im(I)/(2*pi*f) -- captures
    the same voltage-averaged junction capacitance in milliseconds.
    """
    conns = {"VDD": "vdd", "VSS": "0", pin.upper(): "a"}
    caps = []
    for bias in (0.05, VDD / 2, VDD - 0.05):
        lines = [f"* cin {cell}/{pin} @ {bias}V",
                 f".lib {MODELS}/cornerMOShv.lib mos_tt",
                 f".include {MODELS}/diodes.lib",
                 f".include {SPICE}",
                 f"Vdd vdd 0 {VDD}",
                 f"Vin a 0 dc {bias} ac 1",
                 "Xdut " + " ".join(conns.get(p.upper(), f"o{p}")
                                    for p in ports) + f" {cell}",
                 ".ac lin 1 1Meg 1Meg",
                 ".control", "run",
                 "let cin = abs(imag(i(Vin)))/(2*pi*1e6)",
                 "print cin", ".endc", ".end"]
        caps.append(ngspice("\n".join(lines) + "\n", f"cin_{cell}", "cin"))
    return sum(caps) / len(caps) * 1e12          # pF


def add_stubs(txt):
    ly = db.Layout()
    ly.read(str(GDS))
    lb = ly.layer(189, 4)
    areas = {}
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        b = [s.dbbox() for s in c.shapes(lb).each()]
        if b:
            areas[c.name] = round(b[0].width() * b[0].height(), 4)
    spice_txt = SPICE.read_text()
    added = 0
    for cell in STUBS:
        if re.search(rf"^  cell \({re.escape(cell)}\) \{{", txt, re.M):
            continue
        kind = cell.rsplit("_", 1)[0].rsplit("_", 1)[-1] \
            if not cell.endswith("antennanp") else "antennanp"
        ports = re.search(rf"^\.subckt {cell} (.+)$", spice_txt,
                          re.M | re.I).group(1).split()
        body = [f"  cell ({cell}) {{",
                f"    area : {areas[cell]} ;",
                f"    cell_footprint : \"{kind}\" ;"]
        if kind == "fill":                      # empty netlist, no devices
            leak = 0.0
        else:
            leak = measure_leakage(cell, ports)
            print(f"  {cell}: leakage {leak:.4f} nW")
        body += [f"    cell_leakage_power : {leak:.6g} ;",
                 "    dont_touch : true ;",
                 "    dont_use : true ;"]
        if kind == "fill":
            body.append("    is_filler_cell : true ;")
        elif kind == "decap":
            body.append("    is_decap_cell : true ;")
        else:                                   # the antenna diode
            cin = measure_pin_cap(cell, "A", ports)
            print(f"  {cell}: pin A {cin * 1e3:.3f} fF")
            body += ["    pin (A) {",
                     "      direction : input ;",
                     f"      capacitance : {cin:.6g} ;",
                     "    } /* end pin */"]
        body.append("  } /* end cell */")
        i = txt.rfind("\n}")
        txt = txt[:i] + "\n" + "\n".join(body) + txt[i:]
        added += 1
    print(f"stubs: {added} physical-only cells added")
    return txt


# --- rename ------------------------------------------------------------------

def rename_library(txt):
    corner = LIB.stem
    old = "library (sg13g2_stdcell_hv){"
    if old in txt:
        txt = txt.replace(old, f"library ({corner}){{", 1)
        print(f"library renamed to {corner}")
    return txt


# --- install-time filter (called by make_pdk_pr.py) --------------------------

def strip_layoutless(lib_path, cell_lef_path):
    """Remove liberty cells that have no LEF macro, so the installed PDK
    never advertises timing for a cell that cannot be placed."""
    lib_path, cell_lef_path = pathlib.Path(lib_path), pathlib.Path(cell_lef_path)
    txt = lib_path.read_text(errors="surrogateescape")
    macros = set(re.findall(r"^MACRO\s+(\S+)", cell_lef_path.read_text(), re.M))
    assert macros, f"no MACROs in {cell_lef_path}"
    removed = set()
    for name, m in cell_groups(txt).items():
        if name not in macros:
            txt = txt.replace(m.group(1), "", 1)
            removed.add(name)
    assert removed <= LAYOUTLESS, \
        f"unexpected layout-less lib cells: {sorted(removed - LAYOUTLESS)}"
    if removed:
        assert removed == LAYOUTLESS, \
            f"expected {len(LAYOUTLESS)} layout-less cells, " \
            f"removed {len(removed)}: {sorted(removed)}"
    lib_path.write_text(txt, errors="surrogateescape")
    print(f"install lib: {len(removed)} layout-less cells stripped, "
          f"{len(cell_groups(txt))} shipped")
    return removed


def main():
    txt = LIB.read_text(errors="surrogateescape")
    txt = inject_limits(txt)
    txt = add_stubs(txt)
    txt = rename_library(txt)
    LIB.write_text(txt, errors="surrogateescape")
    print(f"finalized {LIB.name}: {len(cell_groups(txt))} cells")


if __name__ == "__main__":
    sys.exit(main())
