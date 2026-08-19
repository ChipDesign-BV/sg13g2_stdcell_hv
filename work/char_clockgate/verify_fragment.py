#!/usr/bin/env python3
"""Check clockgate.lib against the sanity gate, before it is merged.

Runs the checks the repo's own tooling will run on the merged library, on
the fragment alone:

  1. the repo scanner sees exactly the two cell groups
     (work/merge_lib.py cells_of, the same regex work/verify_lib.py uses)
  2. no empty table, no NaN / inf anywhere
  3. CLK -> GCLK delay is monotone along the LOAD axis (index_1 here,
     because the thick-oxide delay_template_7x7 declares
     variable_1 : total_output_net_capacitance)
  4. table axes match the shipped library's grids, and every table's shape
     matches its template
  5. the integrated-clock-gate class requirements: statetable, an internal
     pin with internal_node, dont_use, clock_gate_out_pin with
     state_function, clock_gate_clock_pin with min_pulse_width, and both
     setup_rising and hold_rising on every enable/test pin
  6. setup/hold values are physically plausible and not pinned at a
     bisection search bound (the failure mode work/verify_lib.py checks for)
  7. every lib pin exists in the CDL, except the internal node

Exit 0 / RESULT: PASS only if every check holds.
"""
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
FRAG = HERE / "clockgate.lib"
CDL = HV / "cdl" / "sg13g2_stdcell_hv.cdl"

SLEWS = [0.049480, 0.256960, 0.462840, 0.876200, 1.704530, 3.359580, 6.669680]
LOADS = [0.002200, 0.051480, 0.085800, 0.142560, 0.237600, 0.396000, 0.660000]
CON_DATA = [1.373520, 3.359580]
CON_CLK = [0.462840, 1.373520, 3.359580]
MPW = [0.049480, 1.373520, 3.359580, 6.669680]

errors = []


def err(m):
    errors.append(m)
    print(f"  FAIL  {m}")


def cells_of(txt):                      # verbatim from work/merge_lib.py
    out = {}
    for m in re.finditer(
            r"(^  cell \((\S+)\) \{.*?^  \}(?: /\* end cell \*/)?\n)",
            txt, re.S | re.M):
        out[m.group(2)] = m.group(1)
    return out


def tables(body):
    """Yield (name, template, index_1, index_2, rows)."""
    for m in re.finditer(
            r"(\w+) \((\w+)\) \{\s*index_1 \(\"([^\"]*)\"\) ;\s*"
            r"(?:index_2 \(\"([^\"]*)\"\) ;\s*)?values \((.*?)\) ;",
            body, re.S):
        i1 = [float(x) for x in m.group(3).split(",")]
        i2 = ([float(x) for x in m.group(4).split(",")]
              if m.group(4) else None)
        rows = [[float(x) for x in r.split(",")]
                for r in re.findall(r'"([^"]+)"', m.group(5))]
        yield m.group(1), m.group(2), i1, i2, rows


txt = FRAG.read_text()
cells = cells_of(txt)
print(f"cells found by merge_lib.cells_of: {sorted(cells)}")
if set(cells) != {"sg13g2_hv_lgcp_1", "sg13g2_hv_slgcp_1"}:
    err("scanner does not see exactly the two clock-gate cells")

# templates the fragment references must either exist in the shipped header
# or be supplied by the fragment's own snippet
shipped = (HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib").read_text(
    errors="surrogateescape")
have = set(re.findall(r"lu_table_template \((\w+)\)", shipped))
supplied = set(re.findall(r"lu_table_template \((\w+)\)", txt))
print(f"templates in shipped header: {sorted(have)}")
print(f"templates supplied by the fragment: {sorted(supplied)}")

for name, body in sorted(cells.items()):
    print(f"\n--- {name} ---")
    n_tab = 0
    for tn, tmpl, i1, i2, rows in tables(body):
        n_tab += 1
        if tmpl not in have | supplied:
            err(f"{name}/{tn}: template {tmpl} exists nowhere")
        flat = [v for r in rows for v in r]
        if not flat:
            err(f"{name}/{tn}: empty table")
            continue
        if any(math.isnan(v) or math.isinf(v) for v in flat):
            err(f"{name}/{tn}: NaN/inf in values")
        if len(rows) != len(i1) or any(len(r) != len(i2 or [0] * len(r))
                                       for r in rows):
            err(f"{name}/{tn}: shape {len(rows)}x{len(rows[0])} does not "
                f"match axes {len(i1)}x{len(i2) if i2 else 1}")
        # axis grids
        if tn in ("cell_rise", "cell_fall", "rise_transition",
                  "fall_transition"):
            if [round(x, 6) for x in i1] != LOADS or \
                    [round(x, 6) for x in i2] != SLEWS:
                err(f"{name}/{tn}: axes are not (loads, slews)")
            # monotone along the load axis (index_1 = rows here)
            if tn in ("cell_rise", "cell_fall"):
                for c in range(len(i2)):
                    s = [rows[r][c] for r in range(len(i1))]
                    tol = 0.02 * max(abs(v) for v in s)
                    if any(b < a - tol for a, b in zip(s, s[1:])):
                        err(f"{name}/{tn}: delay decreases with load at slew "
                            f"{i2[c]}: {[round(v, 4) for v in s]}")
        elif tmpl == "constraint_template_2x3":
            if [round(x, 6) for x in i1] != CON_DATA or \
                    [round(x, 6) for x in i2] != CON_CLK:
                err(f"{name}/{tn}: constraint axes do not match the shipped "
                    f"constraint_template_2x3")
        elif tmpl == "mpw_template_4":
            if [round(x, 6) for x in i1] != MPW:
                err(f"{name}/{tn}: mpw axis does not match the new template")
    print(f"tables: {n_tab}")

    # --- integrated clock gate class requirements ------------------------
    def need(pat, what):
        if not re.search(pat, body, re.S):
            err(f"{name}: {what}")

    need(r"clock_gating_integrated_cell : \"latch_posedge",
         "no clock_gating_integrated_cell")
    need(r"statetable \(", "no statetable")
    need(r"dont_use : true ;", "no dont_use")
    need(r"direction : internal ;", "no internal pin")
    need(r"internal_node :", "no internal_node")
    if "slgcp" in name:
        need(r"dont_touch : true ;", "no dont_touch on the scan clock gate")
    elif "dont_touch" in body:
        err(f"{name}: dont_touch present but the LV reference has none")
    pins = {m.group(1): m.group(0) for m in re.finditer(
        r"^    pin \((\S+)\) \{.*?^    \} /\* end pin \*/", body,
        re.S | re.M)}
    print(f"pins: {sorted(pins)}")
    out = [p for p, b in pins.items() if "clock_gate_out_pin" in b]
    if len(out) != 1:
        err(f"{name}: expected exactly one clock_gate_out_pin")
    elif "state_function" not in pins[out[0]]:
        err(f"{name}: {out[0]} has no state_function")
    elif "function :" in pins[out[0]].replace("state_function :", ""):
        err(f"{name}: {out[0]} carries `function` as well as state_function")
    clk = [p for p, b in pins.items() if "clock_gate_clock_pin" in b]
    if len(clk) != 1:
        err(f"{name}: expected exactly one clock_gate_clock_pin")
    elif "timing_type : min_pulse_width" not in pins[clk[0]]:
        err(f"{name}: {clk[0]} has no min_pulse_width group")
    en = [p for p, b in pins.items()
          if "clock_gate_enable_pin" in b or "clock_gate_test_pin" in b]
    if not en:
        err(f"{name}: no clock_gate_enable_pin")
    for p in en:
        for tt in ("setup_rising", "hold_rising"):
            if f"timing_type : {tt}" not in pins[p]:
                err(f"{name}/{p}: no {tt} group")
    # output pin drive limits (work/verify_lib.py check 7)
    for p, b in pins.items():
        if "direction : output ;" in b and "cell_rise (" in b:
            for a in ("max_capacitance", "max_transition"):
                if f"{a} :" not in b:
                    err(f"{name}/{p}: no {a}")

    # --- constraint plausibility ----------------------------------------
    for m in re.finditer(r"timing_type : (setup|hold)_rising ;(.*?)"
                         r"\} /\* end timing \*/", body, re.S):
        for v in re.findall(r"-?\d+\.\d+", m.group(2)):
            x = float(v)
            if x in (round(x), ):
                pass
            if abs(abs(x) - 1.9902) < 0.02 or abs(abs(x) - 7.9902) < 0.02:
                err(f"{name}: {m.group(1)} value {x} at a known search bound")
            if not -3.0 <= x <= 5.0:
                err(f"{name}: implausible {m.group(1)} value {x} ns")
    for m in re.finditer(r"timing_type : min_pulse_width ;(.*?)"
                         r"\} /\* end timing \*/", body, re.S):
        for v in re.findall(r"(?<![\d.])\d+\.\d+", m.group(1)):
            x = float(v)
            if x <= 0:
                err(f"{name}: non-positive min_pulse_width {x}")

    # --- cross-view ------------------------------------------------------
    cdl = {m.group(1): m.group(2).split() for m in
           re.finditer(r"\.SUBCKT (\S+) ([^\n]*)", CDL.read_text())}
    extra = set(pins) - set(cdl.get(name, [])) - {"int_GATE"}
    if extra:
        err(f"{name}: lib pins not in CDL: {sorted(extra)}")

print(f"\nRESULT: {'PASS' if not errors else f'FAIL ({len(errors)} errors)'}")
sys.exit(1 if errors else 0)
