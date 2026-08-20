#!/usr/bin/env python3
"""Characterize the two thick-oxide integrated clock-gate cells with ngspice.

    sg13g2_hv_lgcp_1   (GCLK, CLK, GATE)        latch_posedge
    sg13g2_hv_slgcp_1  (GCLK, CLK, GATE, SCE)   latch_posedge_precontrol

Why this exists
---------------
These two cells are the only library cells the CharLib flow cannot touch:
their thin-oxide reference is described by a `statetable` group, and CharLib
2.1.0 has no statetable input form, so work/gen_charlib_config.py:136-142
skips them ("statetable-based integrated clock gate").  Everything below is
therefore measured directly, one ngspice deck per data point, through the
work/ngspice-osdi-shim wrapper (the PSP103 models are Verilog-A/OSDI).

What is measured
----------------
  delay    CLK -> GCLK propagation and output transition, 7 loads x 7 slews,
           GATE (and SCE=0) held so the clock passes.
  leakage  one settled-tail average of I(VDD) per Liberty `when` state, with
           the latch driven into that state first (the cell holds state, so
           the seq_leakage.py recipe applies: define the state, then average
           the tail).
  cap      charge integration on each input pin: C = |integral i dt| / VDD
           over a full-swing ramp, separately for the rising and the falling
           ramp.
  suh      setup/hold of GATE (and SCE) against the CLK rising edge, by
           bisection on the position of the enable transition relative to the
           edge -- the method of work/seq_delay_procedure.py
           (`_c2q_passes` + `measure_setup_hold`), with the pass criterion
           adapted to a clock gate: the GCLK pulse must be produced full
           swing and undegraded (<= 1.5x the nominal CLK->GCLK delay), or,
           for the opposite captured value, fully suppressed.
  mpw      minimum CLK high time (rise_constraint) and low time
           (fall_constraint) by bisection on the pulse width.

Usage
-----
    ./char_clockgate.py --corner typ all   # everything, raw/*_<corner>.json
    ./char_clockgate.py delay leakage cap suh mpw emit
    ./char_clockgate.py --corner typ emit  # re-emit from cached raw/*.json
"""
import concurrent.futures as cf
import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import corners

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw"   # per-corner files: <task>_<corner>.json
HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"

# Operating point from corners.py; rebound from --corner in __main__.
# Every threshold below is a fraction of VDD, so they follow.
CORNER = corners.CORNERS[corners.DEFAULT]
VDD = CORNER.voltage
VHALF = VDD / 2
V20, V80 = 0.2 * VDD, 0.8 * VDD
V_FULL = 0.9 * VDD          # "pulse produced" threshold
V_BLOCK = 0.1 * VDD         # "pulse suppressed" threshold
JOBS = int(os.environ.get("CG_JOBS", "8"))
# per-deck ngspice wall clock; the grid corners need far more
# than the middle, so it is tunable rather than fixed
TIMEOUT = int(os.environ.get("CG_TIMEOUT", "600"))

# ---------------------------------------------------------------------------
# Grids.  The thick-oxide library scales the thin-oxide axes by 2.66 (slew)
# and 2.20 (load); these are the axes already used by every other cell in
# lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib.
# ---------------------------------------------------------------------------
SLEWS = [0.049480, 0.256960, 0.462840, 0.876200, 1.704530, 3.359580, 6.669680]
LOADS = [0.002200, 0.051480, 0.085800, 0.142560, 0.237600, 0.396000, 0.660000]
# constraint_template_2x3 of the shipped library
CON_DATA = [1.373520, 3.359580]                    # index_1, constrained pin
CON_CLK = [0.462840, 1.373520, 3.359580]           # index_2, related pin
# new 1-D template for min_pulse_width (LV mpw axis x 2.66)
MPW_SLEWS = [0.049480, 1.373520, 3.359580, 6.669680]
# load seen by GCLK during constraint measurement; CharLib's
# metastability_constraint_load default, which is what the shipped HV
# sequential cells were characterized with
CON_LOAD = 0.05

CELLS = {
    "sg13g2_hv_lgcp_1": {
        "ports": ["GCLK", "CLK", "GATE", "VDD", "VSS"],
        "enables": ["GATE"],
        "footprint": "lgcp",
        "icg": "latch_posedge",
        # Liberty `when` -> (levels of the *input* pins for that state).
        # The state variable in the LV reference is the OUTPUT pin GCLK, not
        # the internal node, so a state that pins GCLK low with GATE high
        # implies CLK low, etc.
        "leak": [
            ("!CLK & GATE & !GCLK", {"CLK": 0, "GATE": 1}),
            ("CLK & GATE & GCLK", {"CLK": 1, "GATE": 1}),
            ("!GATE & !GCLK", {"CLK": 0, "GATE": 0}),
        ],
        "statetable": ('"CLK GATE", "int_GATE"',
                       ['table : "L L : - : L ,\\',
                        '               L H : - : H ,\\',
                        '               H - : - : N " ;']),
    },
    "sg13g2_hv_slgcp_1": {
        "ports": ["GCLK", "CLK", "GATE", "SCE", "VDD", "VSS"],
        "enables": ["GATE", "SCE"],
        "footprint": "slgcp",
        "icg": "latch_posedge_precontrol",
        "leak": [
            ("!CLK & GATE & SCE & !GCLK", {"CLK": 0, "GATE": 1, "SCE": 1}),
            ("CLK & GATE & SCE & GCLK", {"CLK": 1, "GATE": 1, "SCE": 1}),
            ("!GATE & SCE & !GCLK", {"CLK": 0, "GATE": 0, "SCE": 1}),
            ("!CLK & GATE & !SCE & !GCLK", {"CLK": 0, "GATE": 1, "SCE": 0}),
            ("CLK & GATE & !SCE & GCLK", {"CLK": 1, "GATE": 1, "SCE": 0}),
            ("!GATE & !SCE & !GCLK", {"CLK": 0, "GATE": 0, "SCE": 0}),
        ],
        "statetable": ('"CLK GATE SCE", "int_GATE"',
                       ['table : "L L L : - : L,\\',
                        '               L L H : - : H,\\',
                        '               L H L : - : H,\\',
                        '               L H H : - : H,\\',
                        '               H - - : - : N" ;']),
    },
}

# area from the LEF MACRO SIZE (width x 7.14); merge_lib.py overrides this
# from the drawn GDS boundary, which is the same number.
AREA = {"sg13g2_hv_lgcp_1": round(14.88 * 7.14, 4),
        "sg13g2_hv_slgcp_1": round(15.36 * 7.14, 4)}


# ---------------------------------------------------------------------------
# ngspice driver
# ---------------------------------------------------------------------------
_env = None


def env():
    global _env
    if _env is None:
        e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        e["PATH"] = f"{SHIM}:" + e.get("PATH", "/usr/bin:/bin")
        # ngspice must be single-threaded here. Its OpenMP barriers spin
        # rather than sleep, so on a machine already running one process
        # per core -- which is exactly what this script does -- the workers
        # burn CPU fighting each other instead of finishing: measured at
        # 130+ CPU-seconds without completing, against ~4 CPU-seconds to
        # completion single-threaded. The failure mode is a hang, not an
        # error, which is why it is worth pinning explicitly.
        e["OMP_NUM_THREADS"] = "1"
        _env = e
    return _env


NUM = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"


def run(name, lines, keep=False):
    """Run one deck; return {measure_name: float or None}."""
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = RAW / "decks"
    tmp.mkdir(exist_ok=True)
    deck = tmp / f"{name}.sp"
    deck.write_text("\n".join(lines) + "\n")
    try:
        r = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True,
                           text=True, timeout=TIMEOUT, env=env(), cwd=str(HERE))
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    res = {}
    for m in re.finditer(rf"^\s*(\w+)\s*=\s*({NUM}|failed)", out, re.M):
        v = m.group(2)
        res[m.group(1)] = None if v == "failed" else float(v)
    if not keep:
        try:
            deck.unlink()
        except OSError:
            pass
    res["_log"] = out
    return res


def head(cell):
    return [f"* {cell}",
            f".lib {MODELS} {CORNER.models}",
            f".option temp={CORNER.temperature:g}",
            f".include {SPICE}",
            # trtol=1 and the default trapezoidal integration: the settings
            # CharLib uses for every other cell in this library
            ".option trtol=1",
            f"Vdd vdd 0 {VDD}"]


def dut(cell, conn):
    """Instance line; conn maps port name -> node."""
    ports = CELLS[cell]["ports"]
    return "Xdut " + " ".join(conn[p] for p in ports) + f" {cell}"


def pwl(points):
    return "PWL(" + " ".join(f"{t:.6f}n {v:.6f}" for t, v in points) + ")"


def edge(t50, tfull, v_from, v_to):
    """Two PWL points for a ramp whose 50 % crossing is t50."""
    return [(t50 - tfull / 2, v_from), (t50 + tfull / 2, v_to)]


def tfull(slew):
    """Full-swing ramp time for a 20-80 % slew."""
    return slew / 0.6


# ---------------------------------------------------------------------------
# 1. CLK -> GCLK propagation (7 loads x 7 slews)
# ---------------------------------------------------------------------------
def delay_point(cell, slew, load):
    tf = tfull(slew)
    thigh = 25.0 + 3 * tf + 40 * load
    t1 = 10.0 + tf                      # CLK 50 % rise
    t2 = t1 + thigh                     # CLK 50 % fall
    tend = t2 + thigh
    clk = [(0.0, 0.0)] + edge(t1, tf, 0.0, VDD) + edge(t2, tf, VDD, 0.0) \
        + [(tend, 0.0)]
    conn = {"GCLK": "gclk", "CLK": "clk", "VDD": "vdd", "VSS": "0"}
    L = head(cell)
    L.append(f"Vclk clk 0 {pwl(clk)}")
    for p in CELLS[cell]["enables"]:
        lvl = VDD if p == "GATE" else 0.0      # SCE inactive, GATE enables
        L.append(f"V{p} n{p} 0 {lvl}")
        conn[p] = f"n{p}"
    L.append(dut(cell, conn))
    L.append(f"Cload gclk 0 {load}p")
    # Max internal timestep.  ngspice always lands on the PWL breakpoints
    # and refines by LTE across a transition, so the step only has to be
    # fine enough for the .meas linear interpolation.  Calibrated in
    # raw/cal/step_cal.txt: at the worst grid point (fastest slew, mid
    # load) 0.01 ns reproduces the 0.002 ns reference to 0.015 % and runs
    # 500x faster.  raw/cal also records that trtol=1 (CharLib's setting,
    # kept here) and the ngspice default agree to 0.02 %.
    step = max(min(tf / 10.0, 0.05), 0.01)
    L += [f".tran {step}n {tend}n",
          f".meas tran cell_rise TRIG v(clk) VAL={VHALF} RISE=1 "
          f"TARG v(gclk) VAL={VHALF} RISE=1",
          f".meas tran rise_transition TRIG v(gclk) VAL={V20} RISE=1 "
          f"TARG v(gclk) VAL={V80} RISE=1",
          f".meas tran cell_fall TRIG v(clk) VAL={VHALF} FALL=1 "
          f"TARG v(gclk) VAL={VHALF} FALL=1",
          f".meas tran fall_transition TRIG v(gclk) VAL={V80} FALL=1 "
          f"TARG v(gclk) VAL={V20} FALL=1",
          f".meas tran gmax MAX v(gclk) FROM={t1}n TO={t2}n",
          ".end"]
    tag = f"delay_{cell}_s{SLEWS.index(slew)}_l{LOADS.index(load)}"
    r = run(tag, L)
    out = {k: (r.get(k) if r.get(k) is None else r[k] * 1e9)
           for k in ("cell_rise", "rise_transition", "cell_fall",
                     "fall_transition")}
    out["gmax"] = r.get("gmax")
    if any(v is None for v in out.values()):
        (RAW / "decks").mkdir(exist_ok=True)
        (RAW / "decks" / f"{tag}.FAILED.log").write_text(r["_log"][-4000:])
    return out


def task_delay():
    """Fill the CLK->GCLK grid, resuming what is already complete.

    The grid's corners are far harder to converge than its middle -- the
    fastest slew forces a tiny internal timestep, the slowest slew with the
    biggest load runs the longest -- so a handful of points can hit the
    per-deck timeout while the other ninety-odd finish. Re-running the whole
    grid to recover them costs an hour and risks losing a different point to
    the same contention, so completed points are kept and only the missing
    ones are re-simulated. Give them more room with
    CG_JOBS=<fewer> CG_TIMEOUT=<longer>.
    """
    res = {}
    path = RAW / f"delay_{CORNER.name}.json"
    if path.exists():
        res = {k: v for k, v in json.loads(path.read_text()).items()
               if all(x is not None for x in v.values())}
    jobs = [(c, s, l) for c in CELLS for s in SLEWS for l in LOADS
            if f"{c}|{s}|{l}" not in res]
    if not jobs:
        print(f"delay: {len(res)} grid points, all cached")
        return
    print(f"delay: {len(res)} cached, {len(jobs)} to simulate "
          f"({JOBS} jobs, {TIMEOUT} s deck timeout)")
    with cf.ThreadPoolExecutor(JOBS) as ex:
        futs = {ex.submit(delay_point, c, s, l): (c, s, l) for c, s, l in jobs}
        for f in cf.as_completed(futs):
            c, s, l = futs[f]
            res[f"{c}|{s}|{l}"] = f.result()
    path.write_text(json.dumps(res, indent=1, sort_keys=True))
    bad = [k for k, v in res.items() if any(x is None for x in v.values())]
    print(f"delay: {len(res)} grid points, {len(bad)} still incomplete")
    for k in bad:
        print(f"  MISSING {k}")


# ---------------------------------------------------------------------------
# 2. leakage per Liberty state
# ---------------------------------------------------------------------------
def leakage_state(cell, levels):
    """Average I(VDD) over a settled tail with the latch driven into `levels`.

    The cell holds state, so CLK-high states are reached by first holding CLK
    low (latch transparent) with the enables at their target levels, then
    raising CLK -- exactly the "define the state first" treatment
    work/seq_leakage.py applies to the flip-flops.
    """
    conn = {"GCLK": "gclk", "CLK": "clk", "VDD": "vdd", "VSS": "0"}
    L = head(cell)
    for p in CELLS[cell]["enables"]:
        L.append(f"V{p} n{p} 0 {VDD * levels[p]}")
        conn[p] = f"n{p}"
    if levels["CLK"]:
        L.append(f"Vclk clk 0 PWL(0 0 20n 0 20.5n {VDD} 200n {VDD})")
    else:
        L.append("Vclk clk 0 0")
    L.append(dut(cell, conn))
    L += [".tran 0.5n 200n",
          ".meas tran ivdd AVG i(Vdd) FROM=150n TO=200n",
          ".meas tran vg AVG v(gclk) FROM=150n TO=200n",
          ".end"]
    tag = f"leak_{cell}_" + "".join(f"{k}{v}" for k, v in sorted(levels.items()))
    r = run(tag, L)
    if r.get("ivdd") is None:
        raise RuntimeError(f"{tag}: no ivdd\n{r['_log'][-2000:]}")
    return abs(r["ivdd"]) * VDD * 1e9, r.get("vg")     # nW, settled GCLK


def task_leakage():
    res = {}
    for cell, spec in CELLS.items():
        for when, levels in spec["leak"]:
            p_nw, vg = leakage_state(cell, levels)
            res[f"{cell}|{when}"] = {"value_nW": p_nw, "gclk_V": vg,
                                     "levels": levels}
            print(f"  {cell:20s} {when:32s} {p_nw:9.6f} nW  "
                  f"GCLK={vg:.3f} V")
    (RAW / f"leakage_{CORNER.name}.json").write_text(json.dumps(res, indent=1,
                                                 sort_keys=True))


# ---------------------------------------------------------------------------
# 3. input pin capacitance (charge integration)
# ---------------------------------------------------------------------------
def cap_pin(cell, pin, rising, others):
    tf = 1.0
    t1, t2 = 20.0, 21.0
    v0, v1 = (0.0, VDD) if rising else (VDD, 0.0)
    pts = [(0.0, v0), (t1, v0), (t1 + tf, v1), (t2 + 20.0, v1)]
    conn = {"GCLK": "gclk", "VDD": "vdd", "VSS": "0"}
    L = head(cell)
    L.append(f"Vp n{pin} 0 {pwl(pts)}")
    conn[pin] = f"n{pin}"
    for p, lvl in others.items():
        L.append(f"V{p} n{p} 0 {VDD * lvl}")
        conn[p] = f"n{p}"
    if "CLK" not in conn:
        raise AssertionError
    L.append(dut(cell, conn))
    L += [".tran 0.005n 45n",
          f".meas tran q INTEG i(Vp) FROM={t1 - 1}n TO={t2 + 15}n",
          ".end"]
    r = run(f"cap_{cell}_{pin}_{'r' if rising else 'f'}", L)
    if r.get("q") is None:
        raise RuntimeError(f"cap {cell}/{pin}: no q\n{r['_log'][-2000:]}")
    return abs(r["q"]) / VDD * 1e12          # pF


def cap_states(cell, pin):
    """Levels of the other input pins while `pin` is swept."""
    st = {}
    for p in ["CLK"] + CELLS[cell]["enables"]:
        if p == pin:
            continue
        if p == "CLK":
            st[p] = 0            # latch transparent: the enable path is live
        else:
            st[p] = 0            # other enables inactive
    return st


def task_cap():
    res = {}
    for cell, spec in CELLS.items():
        for pin in ["CLK"] + spec["enables"]:
            others = cap_states(cell, pin)
            cr = cap_pin(cell, pin, True, others)
            cf_ = cap_pin(cell, pin, False, others)
            res[f"{cell}|{pin}"] = {"rise": cr, "fall": cf_,
                                    "others": others}
            print(f"  {cell:20s} {pin:5s} rise {cr*1e3:7.3f} fF  "
                  f"fall {cf_*1e3:7.3f} fF")
    (RAW / f"cap_{CORNER.name}.json").write_text(json.dumps(res, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# 4. setup / hold of the enable pins against the CLK rising edge
# ---------------------------------------------------------------------------
# One family of decks: the enable pin makes a single transition whose 50 %
# crossing sits `off` nanoseconds from the CLK rising edge (negative = before
# the edge).  From the same family two boundaries are extracted, with the two
# criteria of a clock gate:
#
#   enable RISING  : pulse produced & undegraded for off <= X_a  -> setup
#                    pulse fully suppressed        for off >= X_b  -> hold
#   enable FALLING : pulse fully suppressed        for off <= Y_b  -> setup
#                    pulse produced & undegraded   for off >= Y_a  -> hold
#
# so   setup_rise = -X_a,  hold_rise = X_b,
#      setup_fall = -Y_b,  hold_fall = Y_a
# which is exactly the LV reference's rise_constraint/fall_constraint split
# (the constrained transition names the constraint).
def suh_trial(cell, pin, rising, dslew, cslew, off):
    tfd, tfc = tfull(dslew), tfull(cslew)
    thigh = 25.0 + 3 * tfc
    te = 20.0 + 2 * (tfd + tfc) + max(0.0, -off)      # CLK 50 % rise
    tsw = te + off
    tend = te + thigh + tfc + 10.0
    clk = [(0.0, 0.0)] + edge(te, tfc, 0.0, VDD) \
        + edge(te + thigh, tfc, VDD, 0.0) + [(tend, 0.0)]
    v0, v1 = (0.0, VDD) if rising else (VDD, 0.0)
    dat = [(0.0, v0)] + edge(tsw, tfd, v0, v1) + [(tend, v1)]
    conn = {"GCLK": "gclk", "CLK": "clk", "VDD": "vdd", "VSS": "0"}
    L = head(cell)
    L.append(f"Vclk clk 0 {pwl(clk)}")
    L.append(f"Vd n{pin} 0 {pwl(dat)}")
    conn[pin] = f"n{pin}"
    for p in CELLS[cell]["enables"]:
        if p == pin:
            continue
        L.append(f"V{p} n{p} 0 0")        # other enables inactive
        conn[p] = f"n{p}"
    L.append(dut(cell, conn))
    L.append(f"Cload gclk 0 {CON_LOAD}p")
    step = max(min(min(tfd, tfc) / 10.0, 0.05), 0.01)
    L += [f".tran {step}n {tend}n",
          f".meas tran gmax MAX v(gclk) FROM={te}n TO={te + thigh}n",
          f".meas tran tprop TRIG v(clk) VAL={VHALF} RISE=1 "
          f"TARG v(gclk) VAL={VHALF} RISE=1",
          ".end"]
    tag = f"suh_{cell}_{pin}_{'r' if rising else 'f'}_{dslew}_{cslew}_{off:.4f}"
    r = run(tag, L)
    return {"gmax": r.get("gmax"),
            "tprop": None if r.get("tprop") is None else r["tprop"] * 1e9}


def bisect(pred, lo, hi, tol=0.01):
    """Smallest x in [lo,hi] with pred(x) true, assuming pred monotone up.

    Returns (x, bracketed): bracketed is False when pred is already true at
    lo or still false at hi -- the value is then pinned at a search bound and
    must not be shipped as a measurement.
    """
    if pred(lo):
        return lo, False
    if not pred(hi):
        return hi, False
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if pred(mid):
            hi = mid
        else:
            lo = mid
    return hi, True


def suh_point(cell, pin, dslew, cslew):
    cache = {}

    def trial(off):
        key = round(off, 4)
        if key not in cache:
            cache[key] = suh_trial(cell, pin, True, dslew, cslew, key), None
        return cache[key][0]

    span = 4.0 * max(tfull(dslew), tfull(cslew)) + 4.0

    def make(rising):
        c = {}

        def t(off):
            k = round(off, 4)
            if k not in c:
                c[k] = suh_trial(cell, pin, rising, dslew, cslew, k)
            return c[k]
        return t

    out = {}
    for rising in (True, False):
        t = make(rising)
        # nominal, undegraded propagation: enable settled far from the edge
        nom_off = -span if rising else +span
        nom = t(nom_off)
        if nom["gmax"] is None or nom["gmax"] < V_FULL or nom["tprop"] is None:
            raise RuntimeError(f"{cell}/{pin} {'rise' if rising else 'fall'} "
                               f"d{dslew} c{cslew}: no clean pulse even at "
                               f"off={nom_off} (gmax={nom['gmax']})")
        tnom = nom["tprop"]

        def blocked(off):
            g = t(off)["gmax"]
            return g is not None and g <= V_BLOCK

        def produced(off):
            r = t(off)
            return (r["gmax"] is not None and r["gmax"] >= V_FULL
                    and r["tprop"] is not None and r["tprop"] <= 1.5 * tnom)

        if rising:
            # X_a: largest off still producing -> smallest off blocking-ish;
            # bisect the complement so the predicate is monotone increasing
            xa, ok_a = bisect(lambda o: not produced(o), -span, span)
            xb, ok_b = bisect(blocked, -span, span)
            out["setup_rise"] = -(xa)
            out["hold_rise"] = xb
            out["_brack_setup_rise"] = ok_a
            out["_brack_hold_rise"] = ok_b
        else:
            yb, ok_b = bisect(lambda o: not blocked(o), -span, span)
            ya, ok_a = bisect(produced, -span, span)
            out["setup_fall"] = -(yb)
            out["hold_fall"] = ya
            out["_brack_setup_fall"] = ok_b
            out["_brack_hold_fall"] = ok_a
        out[f"_tnom_{'rise' if rising else 'fall'}"] = tnom
        out["_span"] = span
    return out


def task_suh():
    """Setup/hold of the enable pins against the rising clock edge.

    The largest task in the flow: 18 grid points, each of which is four
    bisections (setup/hold x rise/fall). Resumable and incrementally
    persisted for the same reason task_delay and task_mpw are -- on a
    contended machine this runs for hours, and it used to hold everything
    in memory and write once at the end, so an interruption near the end
    cost the whole run.
    """
    res = {}
    path = RAW / f"suh_{CORNER.name}.json"
    if path.exists():
        res = {k: v for k, v in json.loads(path.read_text()).items()
               if isinstance(v, dict)
               and all(v.get(f) is not None for f in
                       ("setup_rise", "setup_fall", "hold_rise", "hold_fall"))}
    jobs = [(c, p, d, k) for c, s in CELLS.items() for p in s["enables"]
            for d in CON_DATA for k in CON_CLK
            if f"{c}|{p}|{d}|{k}" not in res]
    if not jobs:
        print(f"suh: {len(res)} points, all cached", flush=True)
    else:
        print(f"suh: {len(res)} cached, {len(jobs)} to measure "
              f"({JOBS} jobs, {TIMEOUT} s deck timeout)", flush=True)
        with cf.ThreadPoolExecutor(JOBS) as ex:
            futs = {ex.submit(suh_point, c, p, d, k): (c, p, d, k)
                    for c, p, d, k in jobs}
            for f in cf.as_completed(futs):
                c, p, d, k = futs[f]
                res[f"{c}|{p}|{d}|{k}"] = f.result()
                v = res[f"{c}|{p}|{d}|{k}"]
                path.write_text(json.dumps(res, indent=1, sort_keys=True))
                print(f"  {c:20s} {p:4s} d{d:8.4f} c{k:8.4f}  "
                      f"su_r {v['setup_rise']:+7.3f} "
                      f"su_f {v['setup_fall']:+7.3f} "
                      f"ho_r {v['hold_rise']:+7.3f} "
                      f"ho_f {v['hold_fall']:+7.3f}", flush=True)
    path.write_text(json.dumps(res, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# 5. minimum CLK pulse width
# ---------------------------------------------------------------------------
def pulse(t50a, t50b, tf, v_lo, v_hi):
    """Trapezoid (or triangle, if the width is below the ramp time) whose
    50 % crossings are t50a and t50b."""
    w = t50b - t50a
    if w >= tf:
        return [(t50a - tf / 2, v_lo), (t50a + tf / 2, v_hi),
                (t50b - tf / 2, v_hi), (t50b + tf / 2, v_lo)]
    pk = v_lo + (v_hi - v_lo) * (w + tf) / (2 * tf)
    return [(t50a - tf / 2, v_lo), ((t50a + t50b) / 2, pk),
            (t50b + tf / 2, v_lo)]


def mpw_trial(cell, slew, width, high):
    """One CLK pulse of `width` (50 %-to-50 %); high=True -> a high pulse."""
    tf = tfull(slew)
    settle = 20.0 + 2 * tf
    obs = 25.0 + 3 * tf
    conn = {"GCLK": "gclk", "CLK": "clk", "VDD": "vdd", "VSS": "0"}
    L = head(cell)
    if high:
        t1 = settle
        t2 = t1 + width
        pts = [(0.0, 0.0)] + pulse(t1, t2, tf, 0.0, VDD)
        tend = t2 + tf / 2 + obs
        pts += [(tend, 0.0)]
        meas = [f".meas tran gmax MAX v(gclk) FROM={t1}n TO={tend}n"]
    else:
        # CLK high, a low pulse of `width`, then high again
        t0 = settle                     # first rise (50 %)
        t1 = t0 + obs                   # start of the low pulse (50 %)
        t2 = t1 + width                 # end of the low pulse (50 %)
        pts = [(0.0, 0.0)] + edge(t0, tf, 0.0, VDD)
        pts += pulse(t1, t2, tf, VDD, 0.0)
        tend = t2 + tf / 2 + obs
        pts += [(tend, VDD)]
        meas = [f".meas tran gmin MIN v(gclk) FROM={t1}n TO={t2 + tf/2}n",
                f".meas tran gmax MAX v(gclk) FROM={t2}n TO={tend}n"]
    L.append(f"Vclk clk 0 {pwl(pts)}")
    for p in CELLS[cell]["enables"]:
        lvl = VDD if p == "GATE" else 0.0
        L.append(f"V{p} n{p} 0 {lvl}")
        conn[p] = f"n{p}"
    L.append(dut(cell, conn))
    L.append(f"Cload gclk 0 {CON_LOAD}p")
    step = max(min(min(tf, width) / 10.0, 0.05), 0.01)
    L += [f".tran {step}n {tend}n"] + meas + [".end"]
    tag = f"mpw_{cell}_{'h' if high else 'l'}_{slew}_{width:.4f}"
    r = run(tag, L)
    return r


def mpw_point(cell, slew, high):
    tf = tfull(slew)
    hi = 3 * tf + 15.0
    lo = 0.001

    def ok(w):
        r = mpw_trial(cell, slew, w, high)
        if high:
            return r.get("gmax") is not None and r["gmax"] >= V_FULL
        # low pulse: GCLK must fall out of the high state and the following
        # high phase must still produce a full pulse
        return (r.get("gmin") is not None and r["gmin"] <= V_BLOCK
                and r.get("gmax") is not None and r["gmax"] >= V_FULL)

    w, bracketed = bisect(ok, lo, hi, tol=0.01)
    return {"width": w, "bracketed": bracketed, "hi": hi}


def task_mpw():
    """Bisect the minimum CLK high/low pulse width.

    Resumable, and incrementally persisted, for the same reason task_delay
    is: this is the slowest task in the flow -- hours on a loaded machine --
    and it used to build its results in memory and write once at the end, so
    an interruption at 95 % threw away everything.

    Only *bracketed* points count as cached. An unbracketed result is not a
    measurement -- emit() refuses to ship it, because the returned number is
    a search bound -- and the remedy is to re-bisect it with a longer deck
    timeout. Treating it as done would make the re-run a no-op.
    """
    res = {}
    path = RAW / f"mpw_{CORNER.name}.json"
    if path.exists():
        res = {k: v for k, v in json.loads(path.read_text()).items()
               if isinstance(v, dict) and v.get("bracketed")}
    jobs = [(c, s, h) for c in CELLS for s in MPW_SLEWS for h in (True, False)
            if f"{c}|{s}|{'high' if h else 'low'}" not in res]
    if not jobs:
        print(f"mpw: {len(res)} points, all bracketed and cached", flush=True)
    else:
        print(f"mpw: {len(res)} cached, {len(jobs)} to bisect "
              f"({JOBS} jobs, {TIMEOUT} s deck timeout)", flush=True)
        with cf.ThreadPoolExecutor(JOBS) as ex:
            futs = {ex.submit(mpw_point, c, s, h): (c, s, h)
                    for c, s, h in jobs}
            for f in cf.as_completed(futs):
                c, s, h = futs[f]
                res[f"{c}|{s}|{'high' if h else 'low'}"] = f.result()
                path.write_text(json.dumps(res, indent=1, sort_keys=True))
    for k in sorted(res):
        print(f"  {k:45s} {res[k]['width']:8.4f} ns "
              f"{'' if res[k]['bracketed'] else '  *** PINNED ***'}")
    (RAW / f"mpw_{CORNER.name}.json").write_text(json.dumps(res, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# Liberty emission
# ---------------------------------------------------------------------------
def fmt(x, n=6):
    return f"{x:.{n}f}"


def idx(vals):
    return ", ".join(f"{v:.6f}" for v in vals)


def table(name, tmpl, indent, index1, index2, rows):
    p = " " * indent
    L = [f"{p}{name} ({tmpl}) {{",
         f'{p}  index_1 ("{idx(index1)}") ;']
    if index2 is not None:
        L.append(f'{p}  index_2 ("{idx(index2)}") ;')
    L.append(f"{p}  values ( \\")
    for i, row in enumerate(rows):
        s = ", ".join(f"{v:.6f}" for v in row)
        L.append(f'{p}    "{s}" \\')
    L.append(f"{p}  ) ;")
    L.append(f"{p}}} /* end {name} */")
    return L


def emit():
    delay = json.loads((RAW / f"delay_{CORNER.name}.json").read_text())
    # A grid point that failed to measure is stored as all-None so the delay
    # task can resume it. It must never reach a table: fmt(None) would either
    # raise here or, worse, write the literal "None" into a Liberty the STA
    # tool would then read. The mpw bisection already refuses to ship an
    # unbracketed search; this is the same rule for the delay grid.
    holes = sorted(k for k, v in delay.items()
                   if any(x is None for x in v.values()))
    assert not holes, (
        f"delay_{CORNER.name}.json has {len(holes)} unmeasured grid "
        f"point(s); re-run the delay task before emitting:\n  "
        + "\n  ".join(holes)
        + "\n\nThese are usually deck timeouts on a loaded machine, not "
          "physics: re-run with a longer timeout and fewer parallel jobs, "
          "e.g. CG_TIMEOUT=2400 CG_JOBS=6 ./char_clockgate.py "
          f"--corner {CORNER.name} delay -- only the incomplete points are "
          "re-simulated.")
    leak = json.loads((RAW / f"leakage_{CORNER.name}.json").read_text())
    cap = json.loads((RAW / f"cap_{CORNER.name}.json").read_text())
    suh = json.loads((RAW / f"suh_{CORNER.name}.json").read_text())
    mpw = json.loads((RAW / f"mpw_{CORNER.name}.json").read_text())

    out = []
    for cell, spec in CELLS.items():
        L = [f"  cell ({cell}) {{",
             f"    area : {AREA[cell]} ;",
             f'    cell_footprint : "{spec["footprint"]}" ;']
        vals = [leak[f"{cell}|{w}"]["value_nW"] for w, _ in spec["leak"]]
        L.append(f"    cell_leakage_power : {fmt(sum(vals)/len(vals))} ;")
        L.append(f'    clock_gating_integrated_cell : "{spec["icg"]}" ;')
        if cell.endswith("slgcp_1"):
            L.append("    dont_touch : true ;")
        L.append("    dont_use : true ;")
        args, tbl = spec["statetable"]
        L.append(f"    statetable ({args}) {{")
        L += ["      " + t for t in tbl]
        L.append("    } /* end statetable */")
        L += ["    pin (int_GATE) {",
              "      direction : internal ;",
              '      internal_node : "int_GATE" ;',
              "    } /* end pin */"]

        # ---- GCLK ----------------------------------------------------------
        L += ["    pin (GCLK) {",
              "      clock_gate_out_pin : true ;",
              "      direction : output ;",
              f"      max_capacitance : {LOADS[-1]:.6f} ;",
              f"      max_transition : {SLEWS[-1]:.5f} ;",
              '      state_function : "CLK * int_GATE" ;',
              "      timing () {",
              "        related_pin : CLK ;",
              "        timing_sense : positive_unate ;"]
        for tname in ("cell_rise", "rise_transition", "cell_fall",
                      "fall_transition"):
            rows = [[delay[f"{cell}|{s}|{l}"][tname] for s in SLEWS]
                    for l in LOADS]
            assert all(all(v is not None for v in r) for r in rows), \
                f"{cell} {tname}: missing point"
            L += table(tname, "delay_template_7x7", 8, LOADS, SLEWS, rows)
        L += ["      } /* end timing */",
              "    } /* end pin */"]

        # ---- CLK -----------------------------------------------------------
        c = cap[f"{cell}|CLK"]
        L += ["    pin (CLK) {",
              "      clock : true ;",
              "      clock_gate_clock_pin : true ;",
              "      direction : input ;",
              f"      max_transition : {SLEWS[-1]:.5f} ;",
              f"      rise_capacitance : {fmt(c['rise'])} ;",
              f"      fall_capacitance : {fmt(c['fall'])} ;",
              f"      capacitance : {fmt(max(c['rise'], c['fall']))} ;",
              "      timing () {",
              "        related_pin : CLK ;",
              "        timing_type : min_pulse_width ;"]
        for nm, key in (("rise_constraint", "high"), ("fall_constraint",
                                                      "low")):
            pts = [mpw[f"{cell}|{s}|{key}"] for s in MPW_SLEWS]
            # bisect() reports `bracketed: False` when the answer lies outside
            # the search range -- the returned number is then a search bound,
            # not a measurement, and shipping it is exactly the failure mode
            # verify_lib.py checks for on the sequential cells. A pinned
            # min_pulse_width is not a harmless overestimate either: at the
            # upper bound it would tell STA that this clock gate needs a
            # ~48 ns pulse, and every realistic clock would be reported as
            # too narrow.
            unbr = [f"{cell} {nm} slew {s:g} (= {p['width']:.4f}, bound "
                    f"{p['hi']:.4f})" for s, p in zip(MPW_SLEWS, pts)
                    if not p.get("bracketed")]
            assert not unbr, (
                "min_pulse_width bisection did not bracket:\n  "
                + "\n  ".join(unbr)
                + "\nRe-run `mpw` with fewer jobs and a longer deck timeout "
                  "(CG_JOBS=3 CG_TIMEOUT=2400); an unconverged trial returns "
                  "no measurement, which the predicate reads as 'failed' at "
                  "every width.")
            row = [p["width"] for p in pts]
            L += table(nm, "mpw_template_4", 8, MPW_SLEWS, None, [row])
        L += ["      } /* end timing */",
              "    } /* end pin */"]

        # ---- enable pins ---------------------------------------------------
        for pin in spec["enables"]:
            c = cap[f"{cell}|{pin}"]
            L.append(f"    pin ({pin}) {{")
            if pin == "GATE":
                L.append("      clock_gate_enable_pin : true ;")
            else:
                L.append('      clock_gate_test_pin : "true" ;')
            L += ["      direction : input ;",
                  f"      max_transition : {SLEWS[-1]:.5f} ;",
                  f"      rise_capacitance : {fmt(c['rise'])} ;",
                  f"      fall_capacitance : {fmt(c['fall'])} ;",
                  f"      capacitance : {fmt(max(c['rise'], c['fall']))} ;"]
            for kind in ("hold", "setup"):
                L += ["      timing () {",
                      "        related_pin : CLK ;",
                      "        sdf_edges : both_edges ;",
                      f"        timing_type : {kind}_rising ;"]
                for nm, key in (("rise_constraint", f"{kind}_rise"),
                                ("fall_constraint", f"{kind}_fall")):
                    rows = [[suh[f"{cell}|{pin}|{d}|{k}"][key]
                             for k in CON_CLK] for d in CON_DATA]
                    L += table(nm, "constraint_template_2x3", 8, CON_DATA,
                               CON_CLK, rows)
                L.append("      } /* end timing */")
            L.append("    } /* end pin */")
        # pg_pin and the leakage_power groups close the cell, the placement
        # every other cell in the shipped thick-oxide library uses
        L += ["    pg_pin (VDD) {",
              "      voltage_name : VDD ;",
              "      pg_type : primary_power ;",
              "    } /* end pg_pin */",
              "    pg_pin (VSS) {",
              "      voltage_name : VSS ;",
              "      pg_type : primary_ground ;",
              "    } /* end pg_pin */"]
        for when, _ in spec["leak"]:
            L += ["    leakage_power () {",
                  f'      when : "{when}" ;',
                  f'      value : {fmt(leak[f"{cell}|{when}"]["value_nW"])} ;',
                  "    } /* end leakage_power */"]
        L.append("  } /* end cell */")
        out.append("\n".join(L))

    hdr = [
        "/* Integrated clock-gate cells for sg13g2_stdcell_hv.",
        " *",
        " * Measured with ngspice by work/char_clockgate/char_clockgate.py;",
        " * see work/char_clockgate/NOTES.md for the measurement definitions.",
        " * Paste the two cell groups into",
        " * lib/sg13g2_stdcell_hv_typ_3p30V_25C.lib (or merge with",
        " * work/merge_lib.py), and add the lu_table_template below to the",
        " * library header -- it is the only new template these cells need.",
        " */",
        "",
        "/* --- NEW LIBRARY-HEADER TEMPLATE (add next to the other",
        "       lu_table_template groups, before the first cell) --- */",
        "  lu_table_template (mpw_template_4) {",
        "    variable_1 : constrained_pin_transition ;",
        f'    index_1 ("{idx(MPW_SLEWS)}") ;',
        "  } /* end lu_table_template */",
        "",
        "/* --- CELL GROUPS --- */",
        "",
    ]
    (HERE / f"clockgate_{CORNER.name}.lib").write_text("\n".join(hdr) + "\n".join(out) + "\n")
    print(f"wrote {HERE / f'clockgate_{CORNER.name}.lib'}")


TASKS = {"delay": task_delay, "leakage": task_leakage,
         "cap": task_cap, "suh": task_suh, "mpw": task_mpw,
         "emit": emit}


# ---------------------------------------------------------------------------
# HV / LV cross-check (sanity gate 1)
# ---------------------------------------------------------------------------
LVLIB = pathlib.Path("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
                     "sg13g2_stdcell_typ_1p20V_25C.lib")
SLEW_SCALE, LOAD_SCALE = 2.66, 2.20
LV_NAME = {"sg13g2_hv_lgcp_1": "sg13g2_lgcp_1",
           "sg13g2_hv_slgcp_1": "sg13g2_slgcp_1"}


def _block(txt, start):
    """Text of the brace-delimited group starting at index `start`."""
    i = txt.index("{", start)
    depth, j = 0, i
    while True:
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return txt[i:j + 1]
        j += 1


def lv_cell(name):
    txt = LVLIB.read_text(errors="surrogateescape")
    m = re.search(rf"^  cell \({re.escape(name)}\) ", txt, re.M)
    return _block(txt, m.start())


def lv_tables(body, pin, tnames, sub=None):
    """{table name: [[values]]} for the tables of one pin (optionally only
    inside the sub-group whose header line contains `sub`)."""
    m = re.search(rf"\n    pin \({re.escape(pin)}\) ", body)
    pb = _block(body, m.start())
    if sub:
        k = pb.index(sub)
        pb = _block(pb, pb.rindex("timing ()", 0, k))
    out = {}
    for t in tnames:
        mm = re.search(rf"\n\s*{t} \(", pb)
        if not mm:
            continue
        tb = _block(pb, mm.start())
        # The thin-oxide library closes a table with ");" and this project's
        # own emitter writes ") ;" -- the original pattern required the space
        # and so never matched a single LV table, which is why this
        # cross-check has never once produced a report.
        mv = re.search(r"values \((.*?)\)\s*;", tb, re.S)
        assert mv, f"{t}: no values block in the LV table"
        vals = mv.group(1)
        out[t] = [[float(x) for x in row.split(",")]
                  for row in re.findall(r'"([^"]+)"', vals)]
    return out


def task_ratio():
    delay = json.loads((RAW / f"delay_{CORNER.name}.json").read_text())
    suh = json.loads((RAW / f"suh_{CORNER.name}.json").read_text())
    mpw = json.loads((RAW / f"mpw_{CORNER.name}.json").read_text())
    leak = json.loads((RAW / f"leakage_{CORNER.name}.json").read_text())
    cap = json.loads((RAW / f"cap_{CORNER.name}.json").read_text())
    out = ["# HV / LV ratio cross-check", "",
           "Thin-oxide reference: sg13g2_stdcell_typ_1p20V_25C.lib.",
           "The library's port factors are 2.66 (time) and 2.20 (load), so",
           "each thick-oxide grid point has exactly one thin-oxide twin.", ""]
    flags = []
    for hv, lv in LV_NAME.items():
        body = lv_cell(lv)
        out += [f"## {hv} vs {lv}", ""]
        # --- propagation -------------------------------------------------
        t = lv_tables(body, "GCLK", ("cell_rise", "cell_fall",
                                     "rise_transition", "fall_transition"))
        out += ["### CLK -> GCLK (ratio HV/LV, rows = load, cols = slew)", ""]
        for tn in ("cell_rise", "cell_fall", "rise_transition",
                   "fall_transition"):
            rs = []
            out.append(f"{tn}:")
            out.append("| load\\slew | " + " | ".join(f"{s:g}" for s in SLEWS)
                       + " |")
            out.append("|" + "---|" * (len(SLEWS) + 1))
            for li, l in enumerate(LOADS):
                row = []
                for si, s in enumerate(SLEWS):
                    h = delay[f"{hv}|{s}|{l}"][tn]
                    v = t[tn][si][li]              # LV: index_1 slew, _2 load
                    row.append(h / v)
                    rs.append(h / v)
                out.append(f"| {l:g} | " + " | ".join(f"{x:.2f}" for x in row)
                           + " |")
            out += ["", f"  min {min(rs):.2f}  max {max(rs):.2f}  "
                        f"mean {sum(rs)/len(rs):.2f}", ""]
            bad = [x for x in rs if not 2.2 <= x <= 3.2]
            if bad:
                flags.append(f"{hv} {tn}: {len(bad)}/{len(rs)} ratios outside "
                             f"2.2-3.2 (min {min(rs):.2f}, max {max(rs):.2f})")
        # --- min pulse width ---------------------------------------------
        t = lv_tables(body, "CLK", ("rise_constraint", "fall_constraint"),
                      sub="min_pulse_width")
        out += ["### min_pulse_width (ns)", "",
                "| CLK slew HV (LV) | HV | LV | ratio |", "|---|---|---|---|"]
        for nm, key in (("rise_constraint", "high"),
                        ("fall_constraint", "low")):
            for i, s in enumerate(MPW_SLEWS):
                h = mpw[f"{hv}|{s}|{key}"]["width"]
                v = t[nm][0][i]
                out.append(f"| {nm} {s:g} ({s/SLEW_SCALE:.4f}) | {h:.4f} | "
                           f"{v:.4f} | {h/v:.2f} |")
                if not 1.5 <= h / v <= 4.0:
                    flags.append(f"{hv} mpw {nm} slew {s:g}: ratio {h/v:.2f}")
        out.append("")
        # --- setup / hold --------------------------------------------------
        for pin in CELLS[hv]["enables"]:
            out += [f"### {pin} setup/hold vs CLK (ns)", "",
                    "| constraint | data slew | clk slew | HV | LV | ratio |",
                    "|---|---|---|---|---|---|"]
            for kind in ("setup", "hold"):
                t = lv_tables(body, pin, ("rise_constraint",
                                          "fall_constraint"),
                              sub=f"{kind}_rising")
                for nm, key in (("rise_constraint", f"{kind}_rise"),
                                ("fall_constraint", f"{kind}_fall")):
                    for d in CON_DATA:
                        for k in CON_CLK:
                            h = suh[f"{hv}|{pin}|{d}|{k}"][key]
                            # LV constraint axes: 0.0186, 0.51636, 1.263,
                            # 2.5074 on both. 0.46284/2.66 = 0.174 is not an
                            # LV grid point -> interpolate along the clock
                            # axis for that column only.
                            lvax = [0.0186, 0.51636, 1.263, 2.5074]
                            di = lvax.index(round(d / SLEW_SCALE, 5))
                            kk = k / SLEW_SCALE
                            if round(kk, 5) in lvax:
                                v = t[nm][di][lvax.index(round(kk, 5))]
                                note = ""
                            else:
                                a = max(i for i, x in enumerate(lvax)
                                        if x < kk)
                                f = ((kk - lvax[a]) / (lvax[a + 1] - lvax[a]))
                                v = (t[nm][di][a] * (1 - f)
                                     + t[nm][di][a + 1] * f)
                                note = " (interp)"
                            r = (h / v) if abs(v) > 1e-6 else float("nan")
                            out.append(f"| {kind} {nm} | {d:g} | {k:g}{note} "
                                       f"| {h:+.4f} | {v:+.4f} | {r:.2f} |")
            out.append("")
        # --- leakage / capacitance ----------------------------------------
        lvleak = {m.group(2): float(m.group(1)) for m in re.finditer(
            r'value : ([0-9.]+);\s*\n\s*when : "([^"]+)"', body)}
        out += ["### leakage (HV nW, LV pW -- different library units)", "",
                "| state | HV nW | LV pW |", "|---|---|---|"]
        for when, _ in CELLS[hv]["leak"]:
            lvwhen = when.replace(" ", "")
            out.append(f"| {when} | "
                       f"{leak[f'{hv}|{when}']['value_nW']:.6f} | "
                       f"{lvleak.get(lvwhen, float('nan')):.3f} |")
        out += ["", "### input capacitance (fF)", "",
                "| pin | HV | LV | ratio |", "|---|---|---|---|"]
        for pin in ["CLK"] + CELLS[hv]["enables"]:
            m = re.search(rf"\n    pin \({pin}\) ", body)
            pb = _block(body, m.start())
            lvc = float(re.search(r"\n      capacitance : ([0-9.e-]+);",
                                  pb).group(1)) * 1e3
            hvc = max(cap[f"{hv}|{pin}"]["rise"],
                      cap[f"{hv}|{pin}"]["fall"]) * 1e3
            out.append(f"| {pin} | {hvc:.3f} | {lvc:.3f} | {hvc/lvc:.2f} |")
        out.append("")
    out += ["## flags", ""] + ([f"* {f}" for f in flags] or
                               ["* none: every ratio inside its band"])
    (RAW / "ratio.md").write_text("\n".join(out) + "\n")
    print("\n".join(l for l in out if l.startswith(("  min", "* ", "##"))))
    print(f"wrote {RAW / 'ratio.md'}")


TASKS["ratio"] = task_ratio


if __name__ == "__main__":
    ORDER = ["leakage", "cap", "delay", "mpw", "suh", "emit", "ratio"]
    argv = sys.argv[1:]
    if "--corner" in argv:
        i = argv.index("--corner")
        CORNER = corners.CORNERS[argv[i + 1]]
        del argv[i:i + 2]
        # Every threshold is derived from VDD at module level, so they all
        # have to be recomputed together: rebinding VDD alone would leave
        # VHALF/V20/V80/V_FULL/V_BLOCK holding the previous corner's volts,
        # and the run would measure at the wrong trip points while looking
        # perfectly healthy.
        VDD = CORNER.voltage
        VHALF = VDD / 2
        V20, V80 = 0.2 * VDD, 0.8 * VDD
        V_FULL, V_BLOCK = 0.9 * VDD, 0.1 * VDD
        print(f"corner {CORNER.name}: {CORNER.models}, {VDD} V, "
              f"{CORNER.temperature:g} C", flush=True)
    args = argv or ["all"]
    if args == ["all"]:
        args = ORDER
    for a in args:
        t0 = time.time()
        print(f"== {a} ==", flush=True)
        TASKS[a]()
        print(f"   ({time.time() - t0:.0f} s)", flush=True)
