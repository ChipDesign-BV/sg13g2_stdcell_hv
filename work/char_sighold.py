#!/usr/bin/env python3
"""Characterize sg13g2_hv_sighold and patch it into the shipped Liberty.

sighold is a bus holder: two cross-coupled inverters on a single `inout`
pin, drawn but never characterized because it has no output pin, so
CharLib's configuration skips it (gen_charlib_config.py's "no output pin"
branch). It is also the one cell in the library that needs no timing
characterization at all -- the thin-oxide model is purely
`driver_type : bus_hold` plus capacitance and per-state leakage, with
zero timing groups. So it is measured directly here, the same way the
tie cells are (work/tie_leakage.py).

Two measurements, both on the shipped SPICE netlist:

  leakage    -- SH held at each rail by an ideal source at exactly VDD/0,
                so the keeper carries no steady-state current through the
                driving source and i(VDD) is the true subthreshold path
                (off PMOS into the internal node, sunk by the off NMOS).
                Settled-tail average, as seq_leakage.py/tie_leakage.py do.

  capacitance -- 1 MHz small-signal AC, C = Im(I)/(2*pi*f), averaged over
                bias points near both rails (the same method
                finalize_lib.py uses for the antenna diode's pin). Charge
                integration was tried first and rejected: on a bus holder
                the integral is dominated by the keeper fighting the
                driver, so it grows monotonically with the driving edge
                rate (measured: 30.5 fC at a 0.2 ns edge rising to 86.4 fC
                at 5 ns) and is therefore not a reproducible property of
                the cell. The AC value is the physical pin capacitance and
                is edge-independent; the keeper fight-back charge is a
                separate, driver-dependent effect and is reported in
                work/char_sighold/NOTES.md instead of being folded in.
                Mid-rail bias is skipped: the cross-coupled pair has gain
                there and the small-signal result is meaningless.
                rise_ and fall_capacitance are equal because the physical
                capacitance has no direction (the thin-oxide library's
                2.8x asymmetry is a fight-charge artifact of its
                measurement, not a property of the structure).

internal_power is deliberately NOT emitted: the HV library carries no
switching-power tables for any cell, and adding them here alone would
make library-wide power analysis inconsistent.

Idempotent: skips the patch if the cell is already in the Liberty.

Usage: python3 char_sighold.py [--emit-only]
"""
import os
import pathlib
import re
import subprocess
import sys

HV = pathlib.Path(__file__).resolve().parent.parent
LIB = HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib"
LEF = HV / "lef" / "sg13g2_stdcell_hv.lef"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"
SCRATCH = pathlib.Path("/tmp/claude-1000") / "sighold"

CELL = "sg13g2_hv_sighold"
VDD = 3.3
ROW_H = 7.14


def ngspice(deck, name, measures):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / f"{name}.sp"
    path.write_text(deck)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = f"{SHIM}:" + env.get("PATH", "/usr/bin:/bin")
    r = subprocess.run(["ngspice", "-b", str(path)], capture_output=True,
                       text=True, timeout=600, env=env)
    out = r.stdout + r.stderr
    vals = {}
    for m in measures:
        hit = re.search(rf"^{m}\s*=\s*(-?[0-9.eE+-]+)", out, re.M)
        if not hit:
            raise RuntimeError(f"{name}: no '{m}' measurement\n{out[-800:]}")
        vals[m] = float(hit.group(1))
    return vals


def ports():
    m = re.search(rf"^\.subckt {CELL} (.+)$", SPICE.read_text(), re.M | re.I)
    return m.group(1).split()


def instance(sh_node):
    conns = {"VDD": "vdd", "VSS": "0", "SH": sh_node}
    return "Xdut " + " ".join(conns[p.upper()] for p in ports()) + f" {CELL}"


def leakage(level):
    """Static VDD current with SH held at a rail, in nW."""
    deck = "\n".join([
        f"* {CELL} leakage, SH={level}",
        f".lib {MODELS} mos_tt",
        f".include {SPICE}",
        f"Vdd vdd 0 {VDD}",
        f"Vsh sh 0 {level * VDD}",
        instance("sh"),
        ".tran 0.5n 60n",
        ".meas tran ivdd AVG i(Vdd) from=40n to=60n",
        ".control", "run", ".endc", ".end"]) + "\n"
    i = abs(ngspice(deck, f"leak_{level}", ["ivdd"])["ivdd"])
    return i * VDD * 1e9


def capacitance():
    """Small-signal pin capacitance near each rail, in pF."""
    caps = []
    for bias in (0.05, 0.30, VDD - 0.30, VDD - 0.05):
        deck = "\n".join([
            f"* {CELL} pin capacitance @ {bias} V",
            f".lib {MODELS} mos_tt",
            f".include {SPICE}",
            f"Vdd vdd 0 {VDD}",
            f"Vsh sh 0 dc {bias} ac 1",
            instance("sh"),
            ".ac lin 1 1Meg 1Meg",
            ".control", "run",
            "let cin = abs(imag(i(Vsh)))/(2*pi*1e6)",
            "print cin", ".endc", ".end"]) + "\n"
        caps.append(ngspice(deck, f"cin_{bias}", ["cin"])["cin"] * 1e12)
    print("  pin C vs bias (pF): "
          + ", ".join(f"{c:.5f}" for c in caps))
    return sum(caps) / len(caps)


def fight_charge():
    """Keeper fight-back charge at a 1 ns driving edge, in fC (for the
    record; not folded into `capacitance` -- it scales with the driver)."""
    deck = "\n".join([
        f"* {CELL} keeper fight charge",
        f".lib {MODELS} mos_tt",
        f".include {SPICE}",
        f"Vdd vdd 0 {VDD}",
        f"Vsh sh 0 pulse(0 {VDD} 10n 1n 1n 30n 80n)",
        instance("sh"),
        ".tran 0.005n 60n",
        ".meas tran qr INTEG i(Vsh) from=9n to=39n",
        ".meas tran qf INTEG i(Vsh) from=40n to=58n",
        ".control", "run", ".endc", ".end"]) + "\n"
    v = ngspice(deck, "fight", ["qr", "qf"])
    return abs(v["qr"]) * 1e15, abs(v["qf"]) * 1e15


def area():
    m = re.search(rf"^MACRO {CELL}\b.*?^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)",
                  LEF.read_text(), re.M | re.S)
    return round(float(m.group(1)) * float(m.group(2)), 4)


def cell_group(a, leak_hi, leak_lo, cap):
    avg_leak = (leak_hi + leak_lo) / 2
    return f"""  cell ({CELL}) {{
    area : {a} ;
    cell_footprint : "sighold" ;
    dont_touch : true ;
    dont_use : true ;
    cell_leakage_power : {avg_leak:.6f} ;
    pin (SH) {{
      direction : inout ;
      driver_type : bus_hold ;
      rise_capacitance : {cap:.6f} ;
      fall_capacitance : {cap:.6f} ;
      capacitance : {cap:.6f} ;
    }} /* end pin */
    pg_pin (VDD) {{
      voltage_name : VDD ;
      pg_type : primary_power ;
    }} /* end pg_pin */
    pg_pin (VSS) {{
      voltage_name : VSS ;
      pg_type : primary_ground ;
    }} /* end pg_pin */
    leakage_power () {{
      when : "SH" ;
      value : {leak_hi:.6f} ;
    }} /* end leakage_power */
    leakage_power () {{
      when : "!SH" ;
      value : {leak_lo:.6f} ;
    }} /* end leakage_power */
  }} /* end cell */
"""


def main():
    txt = LIB.read_text(errors="surrogateescape")
    if re.search(rf"^  cell \({CELL}\) \{{", txt, re.M):
        print(f"{CELL}: already in the Liberty, nothing to do")
        return 0

    a = area()
    leak_hi, leak_lo = leakage(1), leakage(0)
    print(f"{CELL}: area {a} um2")
    print(f"  leakage  SH=1 {leak_hi:.6f} nW   SH=0 {leak_lo:.6f} nW")
    cap = capacitance()
    qr, qf = fight_charge()
    print(f"  capacitance {cap * 1e3:.3f} fF (small-signal, bias-averaged)")
    print(f"  keeper fight charge at a 1 ns edge: "
          f"rise {qr:.1f} fC, fall {qf:.1f} fC (documented, not in `capacitance`)")

    group = cell_group(a, leak_hi, leak_lo, cap)
    out = HV / "work" / "char_sighold" / "sighold.lib"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(group)
    print(f"  wrote {out}")

    if "--emit-only" in sys.argv:
        return 0
    i = txt.rfind("\n}")
    LIB.write_text(txt[:i] + "\n" + group + txt[i:], errors="surrogateescape")
    print(f"  patched into {LIB.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
