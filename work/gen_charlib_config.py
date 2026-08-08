#!/usr/bin/env python3
"""Build a CharLib configuration for sg13g2_stdcell_hv.

Cell functions, pin directions, state elements and the characterization grids
are all lifted from the thin-oxide Liberty file -- the transform did not change
any cell's logic, so the thin-oxide library is the correct source for all of
it. Only the electrical operating point changes: 3.3 V instead of 1.2 V.

The slew and load grids are the thin-oxide grids rescaled by factors measured
in work/fo4.py, so the tables cover the same electrical territory as the
original rather than an arbitrary range.
"""
import re, pathlib, json, sys
from boolexpr import convert, operands, truth_table, liberty_truth_table
from libinfo import LVLIB, HV, MODELS, hvname


def _gds_areas():
    """{hv cell name: boundary area um^2} for every cell with layout."""
    gds = HV / "gds" / "sg13g2_stdcell_hv.gds"
    if not gds.exists():
        return {}
    import klayout.db as db
    ly = db.Layout()
    ly.read(str(gds))
    lb = ly.layer(189, 4)
    out = {}
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        bnd = [s.dbbox() for s in c.shapes(lb).each()]
        if bnd:
            out[c.name] = round(bnd[0].width() * bnd[0].height(), 4)
    return out


GDS_AREA = _gds_areas()

WORK = pathlib.Path(__file__).parent
VDD = 3.3

# measured in work/fo4.py: HV inv_1 vs LV inv_1
SLEW_SCALE = 2.66      # FO4 delay ratio
LOAD_SCALE = 2.20      # input capacitance ratio

# --- area estimate -----------------------------------------------------------
# No layout exists for this library, so Liberty `area` is an estimate, not a
# measurement. Model: the cell keeps the thin-oxide device arrangement, so the
# number of poly pitches per cell is unchanged and only their size grows.
CPP_LV, L_LV = 0.48, 0.13          # thin-oxide contacted poly pitch and length
# thin-oxide CONSTRAINT_4x4 template index (clock/constrained pin slews)
CONSTRAINT_SLEWS = [0.0186, 0.51636, 1.263, 2.5074]
L_HV = 0.45
CPP_HV = CPP_LV - L_LV + L_HV      # keep the gate-to-contact budget, grow the gate
ROW_LV = 3.78                      # thin-oxide row height, from sg13g2_tech.lef


def scan_cells(text):
    """Split the Liberty file into cell(NAME){...} bodies, brace-balanced."""
    out = {}
    for m in re.finditer(r"^\s*cell\s*\((\S+?)\)\s*\{", text, re.M):
        name = m.group(1)
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        out[name] = text[m.end():i - 1]
    return out


def subgroups(body, kw):
    """All `kw (args) { ... }` groups directly inside body."""
    out = []
    for m in re.finditer(rf"^\s*{kw}\s*\(([^)]*)\)\s*\{{", body, re.M):
        i, depth = m.end(), 1
        while i < len(body) and depth:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        out.append((m.group(1).strip(), body[m.end():i - 1]))
    return out


def attr(body, name):
    m = re.search(rf"^\s*{name}\s*:\s*(.+?);", body, re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"')


def grids(body):
    """First index_1 (input slew, ns) and index_2 (load, pF) in the cell."""
    i1 = re.search(r'index_1\s*\("([^"]+)"\)', body)
    i2 = re.search(r'index_2\s*\("([^"]+)"\)', body)
    f = lambda m: [float(x) for x in m.group(1).split(",")] if m else None
    return f(i1), f(i2)


def build():
    text = LVLIB.read_text()
    cells = scan_cells(text)

    # library-wide row height: the widest PMOS finger grew by KP, and the row
    # has to accommodate it
    import gen_hv_lib as g
    lv_cells = g.read_lv_spice()
    max_lv_p = max_hv_p = 0.0
    for c in lv_cells:
        for d in c["devs"]:
            if d["kind"] != "mos" or not d["model"].endswith("pmos"):
                continue
            ng = int(d["params"]["ng"])
            wf = g.parse_len(d["params"]["w"]) / ng
            max_lv_p = max(max_lv_p, wf)
            max_hv_p = max(max_hv_p, g.hv_device(d)["w"] / ng)
    row_hv = ROW_LV + (max_hv_p - max_lv_p) * 1e6
    print(f"widest PMOS finger: thin-oxide {max_lv_p*1e6:.3f} um -> "
          f"thick-oxide {max_hv_p*1e6:.3f} um")
    print(f"estimated row height {ROW_LV:.2f} um -> {row_hv:.2f} um, "
          f"poly pitch {CPP_LV:.2f} um -> {CPP_HV:.2f} um")

    out, skipped, seq_cells = {}, {}, []
    for name, body in sorted(cells.items()):
        pins = subgroups(body, "pin")
        ins = [p for p, b in pins if attr(b, "direction") == "input"]
        outs = [(p, b) for p, b in pins
                if attr(b, "direction") == "output"]
        ff = subgroups(body, "ff")
        latch = subgroups(body, "latch")
        st = subgroups(body, "statetable")

        if not outs:
            skipped[name] = "no output pin (fill / decap / antenna diode)"
            continue
        if st and not (ff or latch):
            skipped[name] = ("statetable-based integrated clock gate; CharLib "
                             "has no statetable input form")
            continue

        funcs, bad = [], None
        state = []
        internal = {}
        if ff or latch:
            args, gbody = (ff or latch)[0]
            q, qn = [x.strip() for x in args.split(",")][:2]
            internal[q] = True
            internal[qn] = False
            nxt = attr(gbody, "next_state") or attr(gbody, "data_in")
            en = attr(gbody, "clocked_on") or attr(gbody, "enable")
            # The state expression stays the PURE data function: CharLib's
            # Function class discovers preset/clear pins by their configured
            # roles and wraps the expression in a StateMachineEvaluator that
            # handles them (and the clock) itself. Folding RESET_B into the
            # expression as a level term crashes its truth-table enumeration
            # with "missing positional argument 'RESET_B'".
            #
            # Both storage nodes get their own state entry: an output
            # function "Q_N = !IQ" does NOT read through to IQ's state in
            # CharLib (the lookup is by exact string), which silently made
            # every Q_N arc unmeasurable.
            expr = convert(nxt)
            state = [f"{q} = {expr}", f"{qn} = !({expr})"]

        for p, pb in outs:
            fn = attr(pb, "function")
            if fn is None:
                bad = f"output {p} has no function"
                break
            fn = fn.strip()
            if fn in internal:
                # map the output directly onto its own state node -- CharLib
                # resolves "Q = IQ" by exact match against the state list,
                # so Q_N must map to IQN, never to "!IQ"
                funcs.append(f"{p} = {fn}")
                continue
            conv = convert(fn)
            fins = operands(fn)
            if all(x in ins for x in fins):
                if truth_table(conv, fins) != liberty_truth_table(fn, fins):
                    bad = f"translation of {p} = {fn} is not equivalent"
                    break
            funcs.append(f"{p} = {conv}")
        if bad:
            skipped[name] = bad
            continue

        i1, i2 = grids(body)
        if not i1 or not i2:
            skipped[name] = "no timing tables in the thin-oxide library"
            continue

        lv_area = float(attr(body, "area") or 0)
        est_area = round((lv_area / ROW_LV / CPP_LV) * CPP_HV * row_hv, 4)
        # Layout exists now: prefer the drawn boundary area (site-padded
        # width x 17-track height) over the pre-layout estimate above.
        if hvname(name) in GDS_AREA:
            est_area = GDS_AREA[hvname(name)]

        entry = {
            "netlist": str(HV / "spice" / "sg13g2_stdcell_hv.spice"),
            "models": [f"{MODELS}/cornerMOShv.lib mos_tt"],
            "inputs": ins,
            "outputs": [p for p, _ in outs],
            "functions": funcs,
            "area": est_area,
            "data_slews": [round(x * SLEW_SCALE, 5) for x in i1],
            "loads": [round(x * LOAD_SCALE, 5) for x in i2],
        }
        if ff or latch:
            args, gbody = (ff or latch)[0]
            en = attr(gbody, "clocked_on") or attr(gbody, "enable")
            clear = attr(gbody, "clear")
            preset = attr(gbody, "preset")
            if ff:
                entry["clock"] = ("negedge " + en[1:].strip()
                                  if en.startswith("!")
                                  else "posedge " + en.strip())
            else:
                entry["enable"] = ("not " + en[1:].strip() if en.startswith("!")
                                   else en.strip())
            if clear:
                entry["reset"] = ("! " + clear[1:].strip()
                                  if clear.startswith("!") else clear.strip())
            if preset:
                entry["set"] = ("! " + preset[1:].strip()
                                if preset.startswith("!") else preset.strip())
            entry["state"] = state
            # CharLib's `inputs` key validates against self.inputs, which
            # holds only LOGIC-role pins -- the clock/enable/set/reset pins
            # get special roles and must not be listed.
            special = {entry.get(k, "").split()[-1]
                       for k in ("clock", "enable", "set", "reset")
                       if entry.get(k)}
            entry["inputs"] = [p for p in ins if p not in special]
            # Every sequential procedure iterates
            # config.variations('data_slews', 'clock_slews', ...), and
            # variations() indexes self.parameters[key] directly -- a cell
            # without clock_slews raises KeyError inside the generator,
            # analyse_cell throws, and omit_on_failure swallows the cell
            # whole. THIS was the silent "configured but produce nothing":
            # not one sequential simulation ever ran.
            #
            # The grids are deliberately coarser than the combinational
            # ones, and exclude the fastest slew point. The setup/hold
            # contour steps its transient at min(slew)/4 and runs dozens of
            # simulations per (data_slew x clock_slew x path) variation --
            # measured at ~6 min per variation with the 0.0495 ns point in
            # the grid, ~50x the whole combinational budget. Dropping that
            # point (contour step 8x coarser) and using 2 x 3 constraint
            # grids brings a cell to minutes while still bracketing
            # realistic edges. clk->Q delay tables use clock_slews x the
            # full 7-point load grid.
            entry["data_slews"] = [round(x * SLEW_SCALE, 5)
                                   for x in CONSTRAINT_SLEWS[1:3]]
            entry["clock_slews"] = [0.46284] + [
                round(x * SLEW_SCALE, 5) for x in CONSTRAINT_SLEWS[1:3]]
            seq_cells.append(name)

        out[hvname(name)] = entry

    return out, skipped, seq_cells, row_hv


def yaml_dump(cfg, seq_cells):
    """Minimal YAML writer -- no PyYAML in the base interpreter."""
    L = [
        "# CharLib configuration for sg13g2_stdcell_hv (thick-oxide, 3.3 V).",
        "#",
        "# Generated by work/gen_charlib_config.py. Cell functions, pin",
        "# directions and state elements come from the thin-oxide Liberty",
        "# file, because the thick-oxide transform did not change any cell's",
        "# logic -- only its devices and operating voltage.",
        "#",
        "# `area` is an ESTIMATE derived from the thin-oxide cell area: this",
        "# library has no layout, so no area has been measured. See the README.",
        "",
        "settings:",
        "  lib_name: sg13g2_stdcell_hv",
        "  omit_on_failure: true",
        "  simulation:",
        "    # Must be the shared backend. With ngspice-subprocess, PySpice",
        "    # parses only the raw file and never reads .meas results back --",
        "    # NgSpice/RawFile.py has no measurement handling at all -- so every",
        "    # delay measurement silently comes back empty and the emitted",
        "    # Liberty has timing() groups containing no cell_rise/cell_fall",
        "    # tables. Leakage and pin capacitance still work, which makes the",
        "    # failure easy to miss.",
        "    backend: ngspice-shared",
        "    # The default ac_sweep procedure measures input capacitance as",
        "    # a conductance slope at a floating DC bias, which Miller-",
        "    # multiplies Cgd and reported 6.8-7.5x the true gate capacitance",
        "    # (inv_1: 43.8 fF against 5.87 fF measured directly by",
        "    # work/fo4.py). charge_integration ramps the pin VSS->VDD->VSS",
        "    # and integrates the charge -- the same both-rails method fo4.py",
        "    # validated. Caught by work/verify_lib.py, check 5.",
        "    input_capacitance_procedure: charge_integration",
        "    # CharLib 2.1.0's sequential_worst_case delay procedure is an",
        "    # unimplemented stub; sequential_clk_to_q is provided by",
        "    # work/seq_delay_procedure.py and registered by",
        "    # charlib_patched.py at startup. It measures clock/enable-to-",
        "    # output propagation and transition with a preload-pulse-then-",
        "    # measured-edge scheme; see that module's docstring.",
        "    sequential_delay_procedure: sequential_clk_to_q",
        "    # The stock setup/hold contour builds transients whose point",
        "    # count explodes on these cells (1.2 GB allocations; libngspice",
        "    # then enters a fatal state and poisons the worker). The",
        "    # bisection procedure in seq_delay_procedure.py bounds the",
        "    # search at ~24 short simulations per constraint.",
        "    setup_hold_constraint_procedure: setup_hold_bisection",
        "  # The supply node names are lower case on purpose. CharLib's",
        "  # leakage procedure reads the supply current as",
        "  #     analysis.branches[settings.primary_power.name.lower()]",
        "  # but PySpice restores the netlist's original case when naming",
        "  # branches, so an upper-case VDD source is filed under 'VDD' and the",
        "  # lookup raises KeyError: 'vdd'. Naming the source in lower case",
        "  # makes both spellings agree. SPICE is case-insensitive, so the",
        "  # circuit is unchanged; fix_lib.py restores VDD/VSS in the",
        "  # Liberty output afterwards.",
        "  named_nodes:",
        "    primary_power:",
        "      name: vdd",
        f"      voltage: {VDD}",
        "    primary_ground:",
        "      name: vss",
        "      voltage: 0",
        "  units:",
        "    time: ns",
        "    voltage: V",
        "    capacitive_load: pF",
        "    current: uA",
        "    leakage_power: nW",
        "    energy: fJ",
        "  logic_thresholds:",
        "    low: 0.2",
        "    high: 0.8",
        "    falling: 0.5",
        "    rising: 0.5",
        "  temperature: 25",
        "  cell_defaults:",
        "    # Setup/hold constraints come from a 2D contour sweep whose cost",
        "    # is this number squared, per constraint, per sequential cell. The",
        "    # default of 40 means 1600 simulations per constraint and puts the",
        "    # sequential cells into the tens of hours; 16 keeps them tractable",
        "    # at coarser setup/hold resolution. Raise it for a production",
        "    # sign-off library.",
        "    metastability_constraint_sweep_samples: 16",
        "",
        "cells:",
    ]
    for name, e in cfg.items():
        L.append(f"  {name}:")
        for k in ("netlist", "area", "clock", "enable", "reset", "set"):
            if k in e:
                v = e[k]
                L.append(f"    {k}: {json.dumps(v)}"
                         if isinstance(v, str) else f"    {k}: {v}")
        for k in ("models", "inputs", "outputs", "functions", "state"):
            if k in e and e[k]:
                L.append(f"    {k}:")
                for v in e[k]:
                    L.append(f"      - {json.dumps(v)}")
        for k in ("data_slews", "loads", "clock_slews"):
            if k in e:
                L.append(f"    {k}: [{', '.join(str(x) for x in e[k])}]")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    cfg, skipped, seq_cells, row_hv = build()
    (WORK / "charlib_sg13g2_stdcell_hv.yml").write_text(yaml_dump(cfg, seq_cells))
    print(f"\nconfigured {len(cfg)} cells "
          f"({len(seq_cells)} sequential, {len(cfg)-len(seq_cells)} combinational)")
    if skipped:
        print(f"\nnot characterized ({len(skipped)}):")
        for k, v in sorted(skipped.items()):
            print(f"  {k:24s} {v}")
    print(f"\nwrote {WORK/'charlib_sg13g2_stdcell_hv.yml'}")
