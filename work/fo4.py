#!/usr/bin/env python3
"""Input capacitance and fanout-of-4 delay of the thick-oxide inverter,
against the thin-oxide original. Sets the load/slew grids for charlib and
gives the headline speed/area comparison for the library README.
"""
import subprocess, re, pathlib

WORK = pathlib.Path(__file__).parent
LV = "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/spice/sg13g2_stdcell.spice"
HV = "/foss/designs/sg13g2_stdcell_hv/spice/sg13g2_stdcell_hv.spice"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models"
NGSPICE = "/foss/tools/bin/ngspice"


def deck(kind, vdd, sub, tag):
    """Chain: drv -> dut -> 4 load inverters. FO4 delay measured on the dut.
    Cin from the AC input current of an isolated inverter at 1 MHz."""
    per = 40e-9
    return f"""* {tag} FO4 and Cin
.lib {MODELS}/cornerMOS{kind}.lib mos_tt
.include {LV if kind=='lv' else HV}

Vdd vdd 0 {vdd}
Vin  in 0 pulse(0 {vdd} {per/4} {per/200} {per/200} {per/2} {per})

* shaping stage so the dut sees a realistic edge
Xdrv  a  in  vdd 0 {sub}
Xdut  b  a   vdd 0 {sub}
Xl1  n1  b   vdd 0 {sub}
Xl2  n2  b   vdd 0 {sub}
Xl3  n3  b   vdd 0 {sub}
Xl4  n4  b   vdd 0 {sub}

* Isolated copies for input capacitance, biased at the rails. Biasing the
* input at mid-rail instead would put the inverter in its high-gain region and
* Miller-multiply Cgd into the answer -- a rail-biased gate is what a driving
* cell actually sees.
Vac0 ac0 0 dc 0    ac 1
Xcin0 cq0 ac0 vdd 0 {sub}
Vac1 ac1 0 dc {vdd} ac 1
Xcin1 cq1 ac1 vdd 0 {sub}

.control
tran {per/2000} {3*per}
meas tran tphl trig v(a) val={vdd/2} rise=2 targ v(b) val={vdd/2} fall=2
meas tran tplh trig v(a) val={vdd/2} fall=2 targ v(b) val={vdd/2} rise=2
meas tran trise trig v(b) val={0.2*vdd} rise=2 targ v(b) val={0.8*vdd} rise=2
meas tran tfall trig v(b) val={0.8*vdd} fall=2 targ v(b) val={0.2*vdd} fall=2
ac lin 1 1e6 1e6
let cin0 = imag(i(vac0))/(2*3.14159265*1e6)
let cin1 = imag(i(vac1))/(2*3.14159265*1e6)
let cin = (abs(cin0)+abs(cin1))/2
print cin0
print cin1
print cin
quit
.endc
.end
"""


def run(name, text):
    f = WORK / f"{name}.spice"
    f.write_text(text)
    p = subprocess.run([NGSPICE, "-b", str(f)], cwd=WORK,
                       capture_output=True, text=True, timeout=900)
    out = {}
    for line in (p.stdout + p.stderr).splitlines():
        m = re.match(r"\s*(tphl|tplh|trise|tfall)\s*=\s*([0-9.eE+-]+)", line)
        if m:
            out[m.group(1)] = float(m.group(2))
        m = re.match(r"\s*(cin|cin0|cin1)\s*=\s*([0-9.eE+-]+)", line)
        if m:
            out[m.group(1)] = abs(float(m.group(2)))
    if len(out) < 5:
        print(p.stdout[-3000:], p.stderr[-1500:])
    return out


lv = run("fo4_lv", deck("lv", 1.2, "sg13g2_inv_1", "LV inv_1 @1.2V"))
hv = run("fo4_hv", deck("hv", 3.3, "sg13g2_hv_inv_1", "HV inv_1 @3.3V"))

print(f"{'':10} {'LV inv_1 @1.2V':>16} {'HV inv_1 @3.3V':>16} {'HV/LV':>8}")
for k, unit, scale in (("cin", "fF", 1e15), ("tphl", "ps", 1e12),
                       ("tplh", "ps", 1e12), ("trise", "ps", 1e12),
                       ("tfall", "ps", 1e12)):
    if k in lv and k in hv:
        print(f"{k:10} {lv[k]*scale:13.3f} {unit} {hv[k]*scale:13.3f} {unit} "
              f"{hv[k]/lv[k]:8.2f}")
if "tphl" in lv and "tphl" in hv:
    fl = (lv["tphl"] + lv["tplh"]) / 2
    fh = (hv["tphl"] + hv["tplh"]) / 2
    print(f"\nFO4 delay  LV {fl*1e12:.1f} ps   HV {fh*1e12:.1f} ps   "
          f"HV is {fh/fl:.2f}x slower")
    print(f"Cin ratio  {hv['cin']/lv['cin']:.2f}x  "
          f"-> scale the liberty load grid by this")
