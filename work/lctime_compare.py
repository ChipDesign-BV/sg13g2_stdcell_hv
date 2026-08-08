#!/usr/bin/env python3
"""Cross-characterize a subset of cells with lctime and compare to CharLib.

The shipped Liberty is produced by CharLib. lctime (librecell, AGPL-3.0,
https://codeberg.org/librecell/lctime) is an independent characterizer with
its own stimulus generation, measurement code and ngspice coupling -- so
agreement between the two is evidence about the *data*, not about either
tool. This script:

  1. writes a minimal Liberty template for lctime (header + pin directions
     and functions only -- lctime's liberty parser rejects CharLib's
     backslash-continued `values` rows, and it needs no tables anyway);
  2. runs lctime on each cell's own load/slew grid as read from the shipped
     lib (CharLib scales load axes with drive strength), same PSP103/OSDI
     models, thresholds 20/80 slew and 50 % delay;
  3. aligns every (arc, load, slew) delay/transition point of both libraries
     and reports the distribution of relative differences, split by region.

Findings of the recorded run (8 cells, 3 132 points), so that a rerun can
be judged against them:

  * STA region (real loads, slews < 1 ns): delays agree to median 2.9 %,
    output transitions to median 0.0 %.
  * Slow slews (1.7-6.7 ns) show a systematic ~14 % band with lctime always
    FASTER. Root cause is a stimulus convention, not a measurement error:
    lctime's StepWave (piece_wise_linear.py) uses the given slew as the
    full 0-100 % ramp duration, while Liberty slew -- with the thresholds
    this library declares -- is the 20-80 % time, which CharLib converts
    by /0.6. Interpolating our table at 0.6x the slew reproduces lctime's
    value to 0.25 %, and a direct ngspice measurement of inv_1 cell_rise
    at (0.396 pF, 3.35958 ns) gives 2.3605 ns vs the table's 2.3571 ns
    (CharLib +0.15 %) and lctime's 1.9158 ns (-19 %). CharLib matches the
    Liberty definition.
  * The 2.2 fF minimum-load column carries delays of tens of ps where
    relative error is meaningless (worst: 7 ps vs 57 ps).
  * The largest core deviations are all xor2_1 rise_transition at slow
    slews -- the transmission-gate XOR glitches during the slow input
    traversal and the tools latch different crossings (same mechanism as
    the documented xnor2_1 waiver in verify_lib.py).
  * lctime's inv_1 input capacitance is 8.92 fF vs CharLib's 6.44 fF and
    the direct 5.87 fF reference -- +52 %, supporting the choice of
    charge_integration in the CharLib config.

lctime is combinational-only here: the sequential procedures are not
exercised (CharLib's sequential data is verified independently by
verify_lib.py / verify_seq.py).

ngspice note: lctime's `ngspice-basic` backend runs batch decks, and batch
mode DOES read `.spiceinit` from the process working directory -- unlike the
server mode CharLib uses (see ngspice-osdi-shim/). The run directory
therefore gets a copy of work/.spiceinit so OSDI/PSP103 load normally.

Usage: lctime_compare.py [workdir]   (default work/lctime/)
"""
import os
import re
import shutil
import subprocess
import sys
import pathlib

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
LIB = HV / "lib" / "sg13g2_stdcell_hv_typ_3p30V_25C.lib"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"


# Representative combinational subset: one of each topology family that is
# in the GDS (inverter, buffer chain, NAND/NOR stacks, AOI complex gate,
# transmission-gate XOR/XNOR, and the AND with an internal inverter).
CELLS = ["sg13g2_hv_inv_1", "sg13g2_hv_buf_4", "sg13g2_hv_nand2_1",
         "sg13g2_hv_nor2_1", "sg13g2_hv_a21oi_1", "sg13g2_hv_and2_1",
         "sg13g2_hv_xor2_1", "sg13g2_hv_o21ai_1"]


def pin_blocks(cell_body):
    """Yield (pin_name, block_text) with a brace counter (nested groups)."""
    # \b keeps pg_pin ( from matching ('_' is a word char, so no boundary)
    for m in re.finditer(r"\bpin \((\S+)\) \{", cell_body):
        depth, i = 1, m.end()
        while depth and i < len(cell_body):
            if cell_body[i] == "{":
                depth += 1
            elif cell_body[i] == "}":
                depth -= 1
            i += 1
        yield m.group(1), cell_body[m.start():i]


def cells_of(txt):
    return dict(re.findall(r"^  cell \((\S+)\) \{(.*?)^  \}", txt,
                           re.S | re.M))


def write_template(path, lib_txt, names):
    out = ["""library (tmpl) {
  technology (cmos);
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  leakage_power_unit : "1nW";
  current_unit : "1uA";
  pulling_resistance_unit : "1ohm";
  capacitive_load_unit (1, pf);

  nom_process : 1.0;
  nom_voltage : 3.3;
  nom_temperature : 25;
  slew_upper_threshold_pct_rise : 80;
  slew_lower_threshold_pct_rise : 20;
  slew_upper_threshold_pct_fall : 80;
  slew_lower_threshold_pct_fall : 20;
  input_threshold_pct_rise : 50;
  input_threshold_pct_fall : 50;
  output_threshold_pct_rise : 50;
  output_threshold_pct_fall : 50;
  operating_conditions (typical) {
    process : 1.0;
    voltage : 3.3;
    temperature : 25;
  }
"""]
    all_cells = cells_of(lib_txt)
    for name in names:
        out.append(f"  cell ({name}) {{\n")
        for pn, pb in pin_blocks(all_cells[name]):
            d = re.search(r"direction : (\w+)", pb).group(1)
            out.append(f"    pin ({pn}) {{\n      direction : {d};\n")
            f = re.search(r'function : "([^"]+)"', pb)
            if f:
                out.append(f'      function : "{f.group(1)}";\n')
            out.append("    }\n")
        out.append("  }\n")
    out.append("}\n")
    pathlib.Path(path).write_text("".join(out))


def axes_of(cell_body):
    """(loads, slews) of a cell's first cell_rise table. verify_lib.py
    established that variable_1 is total_output_net_capacitance for this
    library, so index_1 is the load axis. CharLib scales the load axis with
    drive strength (buf_4 goes to 2.64 pF), so every cell must be
    characterized on ITS OWN grid, not one global grid."""
    body = re.sub(r"\\\s*\n", " ", cell_body)
    m = re.search(r"cell_rise\s*\(\S+\)\s*\{", body)
    tb, _ = group_body(body, m.end() - 1)
    loads = [float(x) for x in re.search(
        r'index_1\s*\(\s*"([^"]+)"\s*\)', tb).group(1).split(",")]
    slews = [float(x) for x in re.search(
        r'index_2\s*\(\s*"([^"]+)"\s*\)', tb).group(1).split(",")]
    return loads, slews


def run_lctime(workdir, cells, loads_pf, slews_ns):
    out_lib = workdir / "lctime_out.lib"
    if out_lib.exists():                # reuse a finished run
        print(f"reusing {out_lib}")
        return out_lib
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(HV / "work" / ".spiceinit", workdir / ".spiceinit")
    for c in cells:                     # lctime assumes these exist
        (workdir / "run" / c).mkdir(parents=True, exist_ok=True)
    tmpl = workdir / "template.lib"
    write_template(tmpl, LIB.read_text(errors="surrogateescape"), cells)
    cmd = ["lctime", "-l", str(tmpl),
           "--cell", *cells,
           "--spice", str(SPICE),
           "-L", f"{MODELS} mos_tt",
           "--output-loads", ", ".join(str(x) for x in loads_pf),
           "--slew-times", ", ".join(str(x) for x in slews_ns),
           "--workingdir", str(workdir / "run"),
           "--simulator", "ngspice-basic",
           "-j", str(min(8, os.cpu_count() or 1)),
           "-o", str(out_lib)]
    print("+", " ".join(cmd))
    env = dict(os.environ)
    # ngspice is not on the default non-interactive PATH; the shim dir is
    # harmless here (batch/interactive modes pass through untouched)
    env["PATH"] = (f"{HV / 'work' / 'ngspice-osdi-shim'}:/foss/tools/bin:"
                   + env.get("PATH", "/usr/bin:/bin"))
    env.pop("PYTHONPATH", None)         # keep lctime on its own packages
    log = workdir / "lctime.log"
    with open(log, "w") as fh:
        r = subprocess.run(cmd, cwd=workdir, stdout=fh, stderr=fh, env=env)
    if r.returncode != 0 or not out_lib.exists():
        print(log.read_text()[-2000:])
        raise SystemExit(f"lctime failed (rc={r.returncode})")
    return out_lib


def group_body(txt, start):
    """Return (body, end) of the brace group opening at txt[start] == '{'."""
    depth, i = 1, start + 1
    while depth and i < len(txt):
        depth += {"{": 1, "}": -1}.get(txt[i], 0)
        i += 1
    return txt[start:i], i


def tables_of(cell_body, loads_pf):
    """{(out_pin, related_pin, table_kind): {(load, slew): value}}

    Tolerates both emitters: CharLib writes `values ( \\ "..." \\ ... ) ;`
    with per-row backslash continuations and a space before ';'; lctime
    additionally continues index_1/index_2 over lines and writes `);`.
    Backslash-newline is stripped up front so one regex serves both.
    """
    out = {}
    for pn, pb in pin_blocks(cell_body):
        for tg in re.finditer(r"timing \(\) \{", pb):
            body, _ = group_body(pb, tg.end() - 1)
            body = re.sub(r"\\\s*\n", " ", body)
            rel = re.search(r"related_pin : \"?(\w+)\"?", body).group(1)
            for tm in re.finditer(
                    r"(cell_rise|cell_fall|rise_transition|fall_transition)"
                    r"\s*\(\S+\)\s*\{", body):
                tb, _ = group_body(body, tm.end() - 1)
                idx1 = [float(x) for x in re.search(
                    r'index_1\s*\(\s*"([^"]+)"\s*\)', tb).group(1).split(",")]
                idx2 = [float(x) for x in re.search(
                    r'index_2\s*\(\s*"([^"]+)"\s*\)', tb).group(1).split(",")]
                rows = [[float(x) for x in r.split(",")] for r in
                        re.findall(r'"([^"]+)"',
                                   re.search(r"values\s*\((.*?)\)\s*;",
                                             tb, re.S).group(1))]
                key = (pn, rel, tm.group(1))
                pts = {}
                # normalize axis order on the declared value sets: whichever
                # index holds the load capacitances is the load axis
                for i1, a in enumerate(idx1):
                    for i2, b in enumerate(idx2):
                        load, slew = (a, b) if a in loads_pf else (b, a)
                        pts[(load, slew)] = rows[i1][i2]
                out[key] = pts
    return out


def stats(ds):
    ds = sorted(ds)
    n = len(ds)
    return (f"median {ds[n // 2] * 100:5.1f}%  mean "
            f"{sum(ds) / n * 100:5.1f}%  p95 {ds[int(n * 0.95)] * 100:5.1f}%"
            f"  max {ds[-1] * 100:6.1f}%  (n={n})")


def main():
    workdir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 \
        else HV / "work" / "lctime"
    ours = cells_of(LIB.read_text(errors="surrogateescape"))

    # one lctime invocation per distinct grid (CharLib scales load axes
    # with drive strength)
    grids = {}
    for c in CELLS:
        loads, slews = axes_of(ours[c])
        grids.setdefault((tuple(loads), tuple(slews)), []).append(c)
    theirs, cell_loads = {}, {}
    for gi, ((loads, slews), cells) in enumerate(sorted(grids.items())):
        out_lib = run_lctime(workdir / f"g{gi}", cells, loads, slews)
        theirs.update(cells_of(out_lib.read_text(errors="surrogateescape")))
        for c in cells:
            cell_loads[c] = set(loads)

    print(f"\n{'cell':<22}{'arcs':>5}{'points':>8}{'median':>9}"
          f"{'mean':>8}{'p95':>8}{'max':>8}  worst point")
    all_pts = []            # (rel_diff, load, min_load, base_value)
    for cell in CELLS:
        loads = cell_loads[cell]
        ta = tables_of(ours[cell], loads)
        tb = tables_of(theirs[cell], loads)
        diffs, worst = [], None
        for key in sorted(set(ta) & set(tb)):
            for pt in set(ta[key]) & set(tb[key]):
                a, b = ta[key][pt], tb[key][pt]
                if a <= 0.0:                       # skip degenerate points
                    continue
                d = abs(b - a) / a
                diffs.append(d)
                all_pts.append((d, pt[0], min(loads), a))
                if worst is None or d > worst[0]:
                    worst = (d, key, pt, a, b)
        if not diffs:
            print(f"{cell:<22}  -- no comparable arcs --")
            continue
        diffs.sort()
        n = len(diffs)
        w = (f"{worst[1][2]} {worst[1][1]}->{worst[1][0]} "
             f"@({worst[2][0]}pF,{worst[2][1]}ns): "
             f"{worst[3]:.3f} vs {worst[4]:.3f}")
        print(f"{cell:<22}{len(set(ta) & set(tb)):>5}{n:>8}"
              f"{diffs[n // 2] * 100:>8.1f}%{sum(diffs) / n * 100:>7.1f}%"
              f"{diffs[int(n * 0.95)] * 100:>7.1f}%{diffs[-1] * 100:>7.1f}%"
              f"  {w}")

    # The near-unloaded first column (2.2 fF -- far below any real fanout)
    # carries delays of tens of ps, where the two tools' measurement
    # conventions diverge and relative error is meaningless. Split it out.
    print(f"\nALL points:             {stats([p[0] for p in all_pts])}")
    core = [p[0] for p in all_pts if p[1] != p[2]]
    print(f"load > min column:      {stats(core)}")
    fast = [p[0] for p in all_pts if p[1] != p[2] and p[3] >= 0.05]
    print(f"  ... and value >=50ps: {stats(fast)}")


if __name__ == "__main__":
    main()
