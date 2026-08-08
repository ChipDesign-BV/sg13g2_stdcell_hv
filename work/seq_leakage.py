#!/usr/bin/env python3
"""Measure and insert leakage for the sequential cells.

CharLib's leakage procedure runs only for combinational cells (analyse_cell
branches on is_sequential), so the sequential cells merged into the library
carry no leakage_power group at all -- which synthesis reads as zero.

This measures one honest number per cell: all data inputs low, clock/enable
idle, set/reset inactive, a reset pulse to define the internal state, then
the average VDD current over the settled tail of a transient. That is a
single-state approximation -- the combinational cells enumerate all input
states -- and is documented as such in the README.

Patches `cell_leakage_power` and a leakage_power group into the shipped
Liberty in place.
"""
import os
import re
import subprocess
import pathlib

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
LIB = HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"
SCRATCH = pathlib.Path("/tmp/claude-1000") / "seqleak"

SEQ = ["sg13g2_hv_dfrbp_1", "sg13g2_hv_dfrbp_2", "sg13g2_hv_dfrbpq_1",
       "sg13g2_hv_dfrbpq_2", "sg13g2_hv_dlhq_1", "sg13g2_hv_dlhr_1",
       "sg13g2_hv_dlhrq_1", "sg13g2_hv_dllr_1", "sg13g2_hv_dllrq_1",
       "sg13g2_hv_sdfbbp_1", "sg13g2_hv_sdfrbp_1", "sg13g2_hv_sdfrbp_2",
       "sg13g2_hv_sdfrbpq_1", "sg13g2_hv_sdfrbpq_2"]


def ports_of(cell):
    m = re.search(rf"^\.subckt {cell} (.+)$", SPICE.read_text(),
                  re.M | re.I)
    return m.group(1).split()


def measure(cell):
    ports = ports_of(cell)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    lines = [f"* leakage {cell}",
             f".lib {MODELS} mos_tt",
             f".include {SPICE}",
             "Vdd vdd 0 3.3"]
    conns = []
    for p in ports:
        u = p.upper()
        if u == "VDD":
            conns.append("vdd")
        elif u == "VSS":
            conns.append("0")
        elif u in ("Q", "Q_N"):
            conns.append(f"o{p}")
        elif u in ("RESET_B", "SET_B"):
            # inactive except a defining reset pulse on RESET_B
            if u == "RESET_B":
                lines.append(f"V{p} n{p} 0 PWL(0 0 5n 0 5.2n 3.3 60n 3.3)")
            else:
                lines.append(f"V{p} n{p} 0 3.3")
            conns.append(f"n{p}")
        else:
            lines.append(f"V{p} n{p} 0 0")
            conns.append(f"n{p}")
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
    return i_a * 3.3 * 1e9          # nW


def main():
    txt = LIB.read_text(errors="surrogateescape")
    for cell in SEQ:
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
    print(f"patched {len(SEQ)} cells into {LIB.name}")


if __name__ == "__main__":
    main()
