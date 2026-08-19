#!/usr/bin/env python3
"""Measure and insert leakage for the tie cells.

The tie cells were shipped without any leakage_power group: they are built
from inv_1, inv_1's leakage was never measured stand-alone, and borrowing a
number would read as measured. verify_lib.py rightly flags the absence --
synthesis reads a missing group as zero leakage, which is not true of a
gate whose off-device subthreshold current flows whenever power is up.

So measure it: one deck per cell, the input tied internally by the netlist
itself, output floating, average VDD current over the settled tail of a
transient -- the same measurement seq_leakage.py applies to the sequential
cells, minus the state-defining reset pulse a tie cell does not need.

Patches `cell_leakage_power` and a leakage_power group into the shipped
Liberty in place; skips cells that already carry one, so re-running is safe.
"""
import os
import re
import subprocess
import pathlib
import corners


HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
LIB = None            # set from --corner in __main__
# The operating point is a corner property; see corners.py. CORNER is
# rebound from --corner in __main__, and LIB follows it, so a corner run
# can never write its numbers into another corner's Liberty file.
CORNER = corners.CORNERS[corners.DEFAULT]

SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"
SCRATCH = pathlib.Path("/tmp/claude-1000") / "tieleak"

TIE = ["sg13g2_hv_tiehi", "sg13g2_hv_tielo"]


def ports_of(cell):
    m = re.search(rf"^\.subckt {cell} (.+)$", SPICE.read_text(), re.M | re.I)
    return m.group(1).split()


def measure(cell):
    ports = ports_of(cell)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    lines = [f"* leakage {cell}",
             f".lib {MODELS} {CORNER.models}",
             f".include {SPICE}",
             f".option temp={CORNER.temperature:g}",
             f"Vdd vdd 0 {CORNER.voltage}"]
    conns = []
    for p in ports:
        u = p.upper()
        if u == "VDD":
            conns.append("vdd")
        elif u == "VSS":
            conns.append("0")
        else:                       # L_HI / L_LO: the driven constant output
            conns.append(f"o{p}")
    lines.append("Xdut " + " ".join(conns) + f" {cell}")
    lines += [".tran 0.5n 60n",
              ".meas tran ivdd AVG i(Vdd) from=40n to=60n",
              ".control", "run", ".endc", ".end"]
    deck = SCRATCH / f"{cell}.sp"
    deck.write_text("\n".join(lines) + "\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = f"{SHIM}:" + env.get("PATH", "/usr/bin:/bin")
    r = subprocess.run(["ngspice", "-b", str(deck)],
                       capture_output=True, text=True, timeout=300, env=env)
    m = re.search(r"ivdd\s*=\s*(-?[0-9.e+-]+)", r.stdout + r.stderr)
    if not m:
        raise RuntimeError(f"{cell}: no ivdd measure\n{r.stdout[-500:]}")
    i_a = abs(float(m.group(1)))
    return i_a * CORNER.voltage * 1e9          # nW


def main():
    txt = LIB.read_text(errors="surrogateescape")
    for cell in TIE:
        body = re.search(rf"^  cell \({re.escape(cell)}\) \{{.*?^  \}}",
                         txt, re.M | re.S)
        assert body, cell
        if "cell_leakage_power" in body.group(0):
            print(f"{cell}: already has leakage, skipped")
            continue
        p_nw = measure(cell)
        print(f"{cell}: {p_nw:.4f} nW")
        block = (f"    cell_leakage_power : {p_nw:.6f} ;\n"
                 f"    leakage_power () {{\n"
                 f"      value : {p_nw:.6f} ;\n"
                 f"    }} /* end leakage_power */\n")
        pat = rf"(^  cell \({re.escape(cell)}\) \{{\n(?:    area : [0-9.]+ ;\n)?)"
        assert re.search(pat, txt, re.M), cell
        txt = re.sub(pat, rf"\g<1>{block}", txt, count=1, flags=re.M)
    LIB.write_text(txt, errors="surrogateescape")
    print(f"patched into {LIB.name}")


if __name__ == "__main__":
    import argparse
    ap = corners.add_argument(argparse.ArgumentParser(
        description=__doc__.splitlines()[0]))
    args = ap.parse_args()
    CORNER = corners.CORNERS[args.corner]
    LIB = corners.lib_path(CORNER)
    assert LIB.exists(), f"{LIB.name} does not exist yet -- characterize it first"
    print(f"corner {CORNER.name}: {CORNER.models}, {CORNER.voltage} V, "
          f"{CORNER.temperature:g} C -> {LIB.name}")
    main()
