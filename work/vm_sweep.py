#!/usr/bin/env python3
"""Find the PMOS/NMOS width ratio that centres the HV inverter switching
threshold, using the LV library's own Vm/VDD fraction as the target.

Method: a self-biased inverter (input tied to output) settles at exactly Vm,
so one .op per candidate ratio gives the answer with no sweep interpolation.
"""
import subprocess, re, pathlib

WORK = pathlib.Path(__file__).parent
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models"
NGSPICE = "/foss/tools/bin/ngspice"

WN = 0.74e-6          # LV sg13g2_inv_1 NMOS width, kept as the HV NMOS width
RATIOS = [round(1.0 + 0.1 * i, 2) for i in range(41)]   # Wp/Wn from 1.0 to 5.0


def build(kind, vdd, length, ratios, wn):
    """kind: 'lv' or 'hv'"""
    lines = [f"* self-biased {kind} inverter Vm extraction", ""]
    lines.append(f".lib {MODELS}/cornerMOS{kind}.lib mos_tt")
    lines.append("")
    lines.append(f".subckt inv y a vdd vss wp=1u wn=1u")
    lines.append(f"XM1 y a vss vss sg13_{kind}_nmos w=wn l={length} ng=1 m=1")
    lines.append(f"XM2 y a vdd vdd sg13_{kind}_pmos w=wp l={length} ng=1 m=1")
    lines.append(".ends")
    lines.append("")
    lines.append(f"Vdd vdd 0 {vdd}")
    for i, r in enumerate(ratios):
        # input tied to output -> node settles at Vm
        lines.append(f"Xi{i} vm{i} vm{i} vdd 0 inv wp={r * wn:.6e} wn={wn:.6e}")
    lines.append("")
    lines.append(".control")
    lines.append("op")
    for i in range(len(ratios)):
        lines.append(f"print v(vm{i})")
    lines.append("quit")
    lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def run(name, text):
    f = WORK / f"{name}.spice"
    f.write_text(text)
    p = subprocess.run([NGSPICE, "-b", str(f)], cwd=WORK,
                       capture_output=True, text=True, timeout=1800)
    vals = []
    for line in p.stdout.splitlines():
        m = re.match(r"\s*v\(vm(\d+)\)\s*=\s*([0-9.eE+-]+)", line)
        if m:
            vals.append((int(m.group(1)), float(m.group(2))))
    if not vals:
        print(p.stdout[-3000:], p.stderr[-3000:])
        raise SystemExit(f"{name}: no results")
    vals.sort()
    return [v for _, v in vals]


# --- reference: what Vm/VDD did IHP actually design the LV inverter to? ---
lv_ratio = [1.12 / 0.74]
lv_vm = run("vm_lv_ref", build("lv", 1.2, "130.00n", lv_ratio, WN))[0]
print(f"LV inv_1  Wp/Wn={lv_ratio[0]:.4f}  Vm={lv_vm*1e3:.1f} mV  "
      f"Vm/VDD={lv_vm/1.2:.4f}")

# --- HV sweep ---
hv = run("vm_hv_sweep", build("hv", 3.3, "450.00n", RATIOS, WN))
target = lv_vm / 1.2 * 3.3
print(f"\nHV target Vm = {target*1e3:.1f} mV  (same Vm/VDD fraction as LV)\n")
print(f"{'Wp/Wn':>7} {'Vm [mV]':>10} {'Vm/VDD':>8}")
for r, v in zip(RATIOS, hv):
    print(f"{r:7.2f} {v*1e3:10.1f} {v/3.3:8.4f}")

# linear interpolation onto the target
best = None
for (r0, v0), (r1, v1) in zip(zip(RATIOS, hv), zip(RATIOS[1:], hv[1:])):
    if (v0 - target) * (v1 - target) <= 0 and v1 != v0:
        best = r0 + (target - v0) * (r1 - r0) / (v1 - v0)
        break
print(f"\n==> HV Wp/Wn for Vm/VDD = {lv_vm/1.2:.4f} : {best:.4f}"
      if best else "\n==> target not bracketed")
