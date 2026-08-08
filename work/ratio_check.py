#!/usr/bin/env python3
"""Cross-checks on the global PMOS width factor.

1. Which criterion did IHP size the LV inverter to -- Vm centring or Idsat
   matching?  Measure both for the LV inv_1 pair.
2. Is the HV Wp/Wn ratio width-independent?  A single global PMOS factor is
   only valid across the library's 300n..18u width range if it is.
"""
import subprocess, re, pathlib

WORK = pathlib.Path(__file__).parent
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models"
NGSPICE = "/foss/tools/bin/ngspice"


def run(name, text, keys):
    f = WORK / f"{name}.spice"
    f.write_text(text)
    p = subprocess.run([NGSPICE, "-b", str(f)], cwd=WORK,
                       capture_output=True, text=True, timeout=1800)
    out = {}
    for line in p.stdout.splitlines():
        m = re.match(r"\s*([a-z0-9_()]+)\s*=\s*([0-9.eE+-]+)\s*$", line)
        if m and m.group(1) in keys:
            out[m.group(1)] = float(m.group(2))
    if len(out) < len(keys):
        print(p.stdout[-4000:], p.stderr[-2000:])
        raise SystemExit(f"{name}: missing {set(keys) - set(out)}")
    return out


# ---- 1. Idsat of the LV inv_1 pair, and of an HV pair at several ratios ----
def idsat_deck(kind, vdd, length, devs):
    """devs: list of (tag, 'nmos'|'pmos', w)"""
    L = [f"* Idsat {kind}", f".lib {MODELS}/cornerMOS{kind}.lib mos_tt", ""]
    L.append(f"Vdd vdd 0 {vdd}")
    for tag, typ, w in devs:
        if typ == "nmos":
            L.append(f"V{tag} d{tag} 0 {vdd}")
            L.append(f"X{tag} d{tag} vdd 0 0 sg13_{kind}_nmos "
                     f"w={w:.6e} l={length} ng=1 m=1")
        else:
            L.append(f"V{tag} d{tag} 0 0")
            L.append(f"X{tag} d{tag} 0 vdd vdd sg13_{kind}_pmos "
                     f"w={w:.6e} l={length} ng=1 m=1")
    L += ["", ".control", "op"]
    for tag, _, _ in devs:
        L.append(f"print abs(i(v{tag}))")     # supply-branch current magnitude
    L += ["quit", ".endc", ".end"]
    return "\n".join(L) + "\n"


lv = run("id_lv", idsat_deck("lv", 1.2, "130.00n",
                             [("n", "nmos", 0.74e-6), ("p", "pmos", 1.12e-6)]),
         {"abs(i(vn))", "abs(i(vp))"})
idn, idp = lv["abs(i(vn))"], lv["abs(i(vp))"]
print("LV sg13g2_inv_1 pair @1.2V, L=130n, Wn=0.74u Wp=1.12u")
print(f"  Idsat_n = {idn*1e6:8.2f} uA")
print(f"  Idsat_p = {idp*1e6:8.2f} uA")
print(f"  Idsat_p / Idsat_n = {idp/idn:.4f}   "
      f"(1.000 would mean IHP sized for equal drive)")

# per-micron strength ratio of the HV pair -> the Idsat-matched Wp/Wn
hv = run("id_hv", idsat_deck("hv", 3.3, "450.00n",
                             [("n", "nmos", 1.0e-6), ("p", "pmos", 1.0e-6)]),
         {"abs(i(vn))", "abs(i(vp))"})
print(f"\nHV per-micron @3.3V, L=450n: "
      f"In={hv['abs(i(vn))']*1e6:.2f} uA/um  Ip={hv['abs(i(vp))']*1e6:.2f} uA/um")
print(f"  Wp/Wn for equal HV drive = {hv['abs(i(vn))']/hv['abs(i(vp))']:.4f}")

lvpm = run("id_lvpm", idsat_deck("lv", 1.2, "130.00n",
                                 [("n", "nmos", 1.0e-6), ("p", "pmos", 1.0e-6)]),
           {"abs(i(vn))", "abs(i(vp))"})
print(f"  Wp/Wn for equal LV drive = "
      f"{lvpm['abs(i(vn))']/lvpm['abs(i(vp))']:.4f}   "
      f"(LV library actually uses 1.5135)")


# ---- 2. width-independence of the HV Vm ratio ----
def vm_deck(wn, ratios):
    L = ["* HV Vm vs width", f".lib {MODELS}/cornerMOShv.lib mos_tt", ""]
    L.append(".subckt inv y a vdd vss wp=1u wn=1u")
    L.append("XM1 y a vss vss sg13_hv_nmos w=wn l=450.00n ng=1 m=1")
    L.append("XM2 y a vdd vdd sg13_hv_pmos w=wp l=450.00n ng=1 m=1")
    L.append(".ends")
    L.append("Vdd vdd 0 3.3")
    for i, r in enumerate(ratios):
        L.append(f"Xi{i} vm{i} vm{i} vdd 0 inv wp={r*wn:.6e} wn={wn:.6e}")
    L += ["", ".control", "op"]
    L += [f"print v(vm{i})" for i in range(len(ratios))]
    L += ["quit", ".endc", ".end"]
    return "\n".join(L) + "\n"


TARGET = 0.5046 * 3.3
RS = [round(3.0 + 0.05 * i, 2) for i in range(25)]     # 3.00 .. 4.20
print("\nHV Wp/Wn giving Vm/VDD = 0.5046, vs NMOS width:")
print(f"{'Wn':>10} {'Wp/Wn':>8}")
for wn in (0.3e-6, 0.74e-6, 1.48e-6, 4.0e-6, 11.84e-6, 17.92e-6):
    res = run(f"vm_w{int(wn*1e9)}", vm_deck(wn, RS),
              {f"v(vm{i})" for i in range(len(RS))})
    vs = [res[f"v(vm{i})"] for i in range(len(RS))]
    best = None
    for (r0, v0), (r1, v1) in zip(zip(RS, vs), zip(RS[1:], vs[1:])):
        if (v0 - TARGET) * (v1 - TARGET) <= 0 and v1 != v0:
            best = r0 + (TARGET - v0) * (r1 - r0) / (v1 - v0)
            break
    print(f"{wn*1e6:9.2f}u {best:8.4f}" if best
          else f"{wn*1e6:9.2f}u   not bracketed in [{RS[0]},{RS[-1]}]")
