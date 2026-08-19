#!/usr/bin/env python3
"""Characterize the six thick-oxide tri-state cells directly with ngspice.

Why this exists
---------------
CharLib -- which produced every other cell in sg13g2_stdcell_hv -- has no
concept of a high-impedance output.  There is no `three_state` schema key, no
`three_state_enable`/`three_state_disable` timing type, and no code path that
would ever emit one.  The six tri-state cells were listed in the CharLib
configuration and silently produced nothing usable.  lctime can carry a
`three_state` attribute on the output pin, but it deliberately *pins* the
enable input to its active level and skips the enable/disable arcs entirely,
so it cannot fill them either.

So the arcs are measured here, by hand, with ngspice, using the same decks,
thresholds and grids the rest of the library was built on.

What is measured
----------------
  leakage        settled-tail average of i(Vdd) over a quiet transient window,
                 one state per `when` condition of the thin-oxide counterpart
                 (work/tie_leakage.py's deck style)
  pin capacitance charge integration, VSS->VDD->VSS ramp, Q/VDD per edge --
                 a byte-for-byte reimplementation of the CharLib
                 `charge_integration` procedure that produced every other
                 input capacitance in this library.  Validated by reproducing
                 the shipped sg13g2_hv_buf_4 pin A value.
  A -> Z         ordinary combinational delay/transition with the enable
                 asserted (TE_B = 0)
  enable arc     output starts floating at the opposite rail, held by a keeper
                 resistor; TE_B falls; 50 %-to-50 % delay and 20/80 transition
                 into the grid load
  disable arc    output held at its slew threshold by an ideal source; TE_B
                 rises; delay to the point where the cell's output drive
                 current has decayed to half its enabled value.  See NOTES.md
                 for why a voltage-threshold criterion cannot be used here.

Grids follow the library convention implemented in work/gen_charlib_config.py:
the thin-oxide axes scaled by the factors measured in work/fo4.py (loads x
2.20, slews x 2.66).  Note that the HV templates declare
variable_1 = total_output_net_capacitance, the OPPOSITE order from the
thin-oxide library, so index_1 is the load axis and index_2 the slew axis in
every emitted table.

Outputs
-------
  tristate.lib      six Liberty cell groups, ready for work/merge_lib.py
  measured.json     every raw number, so the Liberty can be re-emitted without
                    re-simulating
  decks/, logs/     every ngspice deck and its output

Usage:  ./char_tristate.py [--reuse]      (--reuse skips simulation if
                                           measured.json is present)
"""
import json
import os
import pathlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import corners

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
WORK = HV / "work" / "char_tristate"
DECKS = WORK / "decks"
LOGS = WORK / "logs"
DATA = WORK / "data"
CACHE = DATA / "cache"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
LEF = HV / "lef" / "sg13g2_stdcell_hv.lef"
SHIM = HV / "work" / "ngspice-osdi-shim"
MODELS = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"

# Operating point from corners.py; rebound from --corner in __main__.
CORNER = corners.CORNERS[corners.DEFAULT]
VDD = CORNER.voltage
TH_LOW, TH_HIGH = 0.2, 0.8          # slew thresholds, from the library header
TH_MID = 0.5                        # input/output propagation threshold
ROW_H = 7.14                        # thick-oxide row height, um

# The library-wide slew axis: the thin-oxide axis x 2.66 (work/fo4.py).
SLEWS = [0.049480, 0.256960, 0.462840, 0.876200, 1.704530, 3.359580, 6.669680]
# The load axis is max_capacitance x these fractions, with the same first
# point (0.001 pF x 2.20) every HV cell uses.
LOAD_FRACTIONS = [0.078, 0.13, 0.216, 0.36, 0.6, 1.0]
MAX_TRANSITION = 6.66968

# Keeper resistance holding a floating output at a defined rail: 1 Gohm, the
# value work/verify_logic.py uses for its high-Z checks.  Whether it is strong
# enough to hold the smallest grid load against the cell's own off-state
# leakage is not assumed -- every enable-arc simulation reports the pre-edge
# output voltage and check_hold() rejects the run if it drifted.  (It does
# hold: thick-oxide off-current is ~1e-4 of the thin-oxide equivalent.  A
# 1 Mohm keeper gives answers within 0.3 %.)
KEEPER_OHM = 1e9
HOLD_TOL = 0.05 * VDD               # keeper must hold within 5 % of the rail

# Cell table: name, footprint, thin-oxide max_capacitance, drive.
# max_capacitance is the thin-oxide value x 2.20.
CELLS = [
    ("sg13g2_hv_ebufn_2", "ebufn", 0.6, "sg13g2_ebufn_2"),
    ("sg13g2_hv_ebufn_4", "ebufn", 1.2, "sg13g2_ebufn_4"),
    ("sg13g2_hv_ebufn_8", "ebufn", 2.4, "sg13g2_ebufn_8"),
    ("sg13g2_hv_einvn_2", "einvn", 0.6, "sg13g2_einvn_2"),
    ("sg13g2_hv_einvn_4", "einvn", 1.2, "sg13g2_einvn_4"),
    ("sg13g2_hv_einvn_8", "einvn", 2.4, "sg13g2_einvn_8"),
]

# leakage_power `when` conditions, mirroring each thin-oxide counterpart
# exactly (einvn_2 spells the output node out in a third term; einvn_4/_8 do
# not; ebufn lists all four input states).
LEAK_WHEN = {
    "ebufn": [("A&TE_B", {"A": 1, "TE_B": 1}),
              ("!A&TE_B", {"A": 0, "TE_B": 1}),
              ("A&!TE_B", {"A": 1, "TE_B": 0}),
              ("!A&!TE_B", {"A": 0, "TE_B": 0})],
    "einvn": [("!A&!TE_B", {"A": 0, "TE_B": 0}),
              ("A&!TE_B", {"A": 1, "TE_B": 0})],
}
LEAK_WHEN_EINVN_2 = [("!A&!TE_B&Z", {"A": 0, "TE_B": 0}),
                     ("A&!TE_B&!Z", {"A": 1, "TE_B": 0})]

def header():
    """Deck preamble for the active corner.

    A function rather than a constant: the corner is chosen at runtime, and
    a module-level string would freeze whichever corner was imported first
    -- which is how a fast-corner run ends up with typical models.
    """
    return (f".lib {MODELS} {CORNER.models}\n"
            f".option temp={CORNER.temperature:g}\n"
            f".include {SPICE}\n")


# --------------------------------------------------------------------------
# ngspice driver
# --------------------------------------------------------------------------
def ngspice(name, text):
    """Run one deck through the OSDI shim; return combined stdout+stderr.

    The shim preloads the PSP103 Verilog-A models; PYTHONPATH must be dropped
    or the interpreter injected into ngspice's environment confuses it.  Same
    recipe as work/tie_leakage.py.
    """
    DECKS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    deck = DECKS / f"{name}.sp"
    deck.write_text(text)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = f"{SHIM}:" + env.get("PATH", "/usr/bin:/bin")
    # One OpenMP thread per ngspice, and no busy-waiting if there ever is more
    # than one.  ngspice defaults to four threads here (~/.spiceinit), and its
    # OpenMP barriers spin rather than sleep: on a machine whose run queue is
    # already ten times its core count -- which this one was throughout, from a
    # second characterization job -- the threads burn their entire scheduled
    # slice spinning at barriers instead of solving.  Measured directly:
    # identical decks accumulated 130+ CPU-seconds without finishing at four
    # threads, against ~4 CPU-seconds to completion at one.  Parallelism is
    # taken at the job level instead, via CT_JOBS.
    env["OMP_NUM_THREADS"] = "1"
    env["OMP_WAIT_POLICY"] = "PASSIVE"
    r = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True,
                       text=True, timeout=1800, env=env, cwd=str(WORK))
    out = r.stdout + r.stderr
    (LOGS / f"{name}.log").write_text(out)
    return out


def cached(name, fn):
    """Memoise one measurement on disk.

    Every simulation here is a pure function of its deck, and the machine this
    runs on is shared, so a run that gets starved out can be restarted without
    throwing away the work that did finish.  Delete data/cache to force a full
    re-measurement.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    v = fn()
    f.write_text(json.dumps(v))
    return v


MEAS_RE = re.compile(r"^\s*(\w+)\s*=\s*(-?[0-9]+\.?[0-9]*(?:[eE][-+]?\d+)?)\s",
                     re.M)


def measures(out):
    """Parse `.meas` results.  Failed measurements are simply absent."""
    d = {}
    for m in MEAS_RE.finditer(out):
        d.setdefault(m.group(1).lower(), float(m.group(2)))
    return d


def ports_of(cell):
    m = re.search(rf"^\.subckt {cell} (.+)$", SPICE.read_text(), re.M | re.I)
    return m.group(1).split()


def lef_areas():
    """{cell: width x 7.14} from the LEF MACRO SIZE statements."""
    txt = LEF.read_text()
    out = {}
    for m in re.finditer(r"MACRO (\S+)(.*?)END \1", txt, re.S):
        s = re.search(r"SIZE ([0-9.]+) BY ([0-9.]+)", m.group(2))
        if s:
            out[m.group(1)] = round(float(s.group(1)) * float(s.group(2)), 4)
    return out


def pwl(points):
    return "pwl(" + " ".join(f"{t:.6f}n {v:.6f}" for t, v in points) + ")"


def edge(t0, slew, v_from, v_to):
    """A slew-rate-correct ramp.  Liberty defines the input slew between the
    20 % and 80 % thresholds, so the full rail-to-rail ramp is slew/0.6 --
    CharLib's utils.slew_pwl, and therefore the convention every other table
    in this library was measured with."""
    return t0 + slew / (TH_HIGH - TH_LOW)


# --------------------------------------------------------------------------
# 1. leakage
# --------------------------------------------------------------------------
def measure_leakage(cell, state):
    """Settled-tail average of i(Vdd), in nW.

    Deck style copied from work/tie_leakage.py.  When TE_B holds the output in
    high-Z the output node has no DC path of its own, so it is tied to
    mid-rail through 1 Gohm -- work/verify_logic.py's trick for making a
    floating tri-state node well defined.  In that state the keeper carries
    exactly the cell's own net leakage into Z, which is part of what is being
    measured.

    In the *driven* states there is no keeper, and that is not a detail.  With
    one attached, a cell driving Z high pushes (VDD - 1.65)/1 Gohm = 1.65 nA
    out through the keeper and back to ground, and that current flows through
    Vdd: it lands in i(Vdd) as 5.4 nW of fictitious leakage, two orders above
    the real number.  Thick-oxide leakage is small enough that a 1 Gohm
    resistor is not a negligible load.
    """
    hiz = state.get("TE_B") == 1        # TE_B is active low
    L = [f"* leakage {cell} {state}", header().rstrip(), f"Vdd vdd 0 {VDD}"]
    if hiz:
        L.append(f"Vmid vmid 0 {VDD / 2}")
    conns = []
    for p in ports_of(cell):
        u = p.upper()
        if u == "VDD":
            conns.append("vdd")
        elif u == "VSS":
            conns.append("0")
        elif u in state:
            conns.append("vdd" if state[u] else "0")
        else:                                   # the output
            conns.append("z")
    L.append("Xdut " + " ".join(conns) + f" {cell}")
    if hiz:
        L.append("Rkeep z vmid 1G")
    L += [".tran 0.5n 60n",
          ".meas tran ivdd AVG i(Vdd) from=40n to=60n",
          ".meas tran vz FIND v(z) AT=59n",
          ".control", "run", ".endc", ".end"]
    tag = "".join(f"{k}{v}" for k, v in sorted(state.items()))
    m = cached(f"leak_{cell}_{tag}",
               lambda: measures(ngspice(f"leak_{cell}_{tag}", "\n".join(L))))
    if "ivdd" not in m:
        raise RuntimeError(f"leakage {cell} {state}: no ivdd")
    return abs(m["ivdd"]) * VDD * 1e9, m.get("vz")


# --------------------------------------------------------------------------
# 2. pin capacitance -- charge integration
# --------------------------------------------------------------------------
def measure_cap(cell, target, ties, tag):
    """C = |Q| / VDD per edge, from a VSS->VDD->VSS ramp on `target`.

    Reimplements CharLib's charge_integration procedure with its defaults, and
    deliberately does not deviate from them: t_slew = the fastest grid slew,
    t_wait = 1000 x t_slew, every pin that is not the target isolated with
    10 Gohm + 1 pF to ground.  `ties` exists for pin Z, which has to be
    measured with the cell disabled.

    CharLib's defaults are kept rather than tuned.  Shortening t_wait and
    tying the non-target input were both tried during development and appeared
    to be catastrophically slower; that was an artefact of a second
    characterization run saturating all eight cores of this machine at the
    time, and ngspice's "Total analysis time" being elapsed time rather than
    CPU time.  Neither change was a real improvement, and the defaults are
    what the rest of the library was measured with.
    """
    ts = SLEWS[0]
    tw = 1000 * ts
    L = [f"* cap {cell} {target} {tag}", header().rstrip(), f"Vdd vdd 0 {VDD}",
         "Vstim vin 0 " + pwl([(0, 0), (tw, 0), (tw + ts, VDD),
                               (2 * tw + ts, VDD), (2 * tw + 2 * ts, 0)])]
    conns = []
    for p in ports_of(cell):
        u = p.upper()
        if u == "VDD":
            conns.append("vdd")
        elif u == "VSS":
            conns.append("0")
        elif u == target:
            conns.append("vin")
        elif u in ties:
            conns.append("vdd" if ties[u] else "0")
        else:
            conns.append(f"n{p}")
            L.append(f"C{p} n{p} 0 1p")
            L.append(f"R{p} n{p} 0 10G")
    L.append("Xdut " + " ".join(conns) + f" {cell}")
    e = 1e-9                                    # ns -> s for the .meas windows
    L += [f".tran {ts / 10:.6f}n {3 * tw + 2 * ts:.6f}n",
          f".meas tran q_rise INTEG i(Vstim) from={tw * e:.6g} "
          f"to={(tw + ts) * e:.6g}",
          f".meas tran q_fall INTEG i(Vstim) from={(2 * tw + ts) * e:.6g} "
          f"to={(2 * tw + 2 * ts) * e:.6g}",
          ".control", "run", ".endc", ".end"]
    m = cached(f"cap_{cell}_{target}_{tag}",
               lambda: measures(ngspice(f"cap_{cell}_{target}_{tag}",
                                        "\n".join(L))))
    if "q_rise" not in m or "q_fall" not in m:
        raise RuntimeError(f"cap {cell}/{target}: no charge measurement")
    # farads -> pF
    return abs(m["q_rise"]) / VDD * 1e12, abs(m["q_fall"]) / VDD * 1e12


# --------------------------------------------------------------------------
# 3. combinational A -> Z
# --------------------------------------------------------------------------
def measure_comb(cell, kind, loads, slew):
    """Delay and transition for the A -> Z arc with the enable asserted.

    One deck per input slew holding seven independent copies of the cell, one
    per load point, all driven by the same ideal PWL source: identical
    stimulus by construction, and a seventh of the simulations.
    """
    T = slew / (TH_HIGH - TH_LOW)
    t1 = max(3 * slew, 1.0)
    settle = max(8 * slew, 28.0)
    t2, t3 = t1 + T, t1 + T + settle
    t4, tend = t3 + T, t3 + T + settle
    L = [f"* comb {cell} slew={slew}", header().rstrip(), f"Vdd vdd 0 {VDD}",
         "Vte te 0 0",
         "Va a 0 " + pwl([(0, 0), (t1, 0), (t2, VDD), (t3, VDD), (t4, 0)])]
    for i, c in enumerate(loads):
        L.append(f"X{i} z{i} a te vdd 0 {cell}")
        L.append(f"C{i} z{i} 0 {c:.9f}p")
    mid, lo, hi = TH_MID * VDD, TH_LOW * VDD, TH_HIGH * VDD
    for i in range(len(loads)):
        # ebufn is positive unate (A rise -> Z rise), einvn negative unate.
        z_rise_from = "rise" if kind == "ebufn" else "fall"
        z_fall_from = "fall" if kind == "ebufn" else "rise"
        L += [f".meas tran cr{i} trig v(a) val={mid} {z_rise_from}=1 "
              f"targ v(z{i}) val={mid} rise=1",
              f".meas tran rt{i} trig v(z{i}) val={lo} rise=1 "
              f"targ v(z{i}) val={hi} rise=1",
              f".meas tran cf{i} trig v(a) val={mid} {z_fall_from}=1 "
              f"targ v(z{i}) val={mid} fall=1",
              f".meas tran ft{i} trig v(z{i}) val={hi} fall=1 "
              f"targ v(z{i}) val={lo} fall=1"]
    L += [f".tran {min(slew / 8, 0.01):.6f}n {tend:.6f}n",
          ".control", "run", ".endc", ".end"]
    m = cached(f"comb_{cell}_{slew}",
               lambda: measures(ngspice(f"comb_{cell}_{slew}", "\n".join(L))))
    out = {}
    for key, pfx in (("cell_rise", "cr"), ("rise_transition", "rt"),
                     ("cell_fall", "cf"), ("fall_transition", "ft")):
        vals = []
        for i in range(len(loads)):
            if f"{pfx}{i}" not in m:
                raise RuntimeError(f"comb {cell} slew={slew}: missing {pfx}{i}")
            vals.append(m[f"{pfx}{i}"] * 1e9)    # s -> ns
        out[key] = vals
    return out


# --------------------------------------------------------------------------
# 4. three_state_enable
# --------------------------------------------------------------------------
def measure_enable(cell, kind, loads, slew, direction):
    """Hi-Z -> driven.

    The output starts floating at the rail opposite the one it will be driven
    to, held there by a keeper resistor and started there with .ic, so the
    full swing is measured.  TE_B then falls with the grid slew and the cell
    takes the node over.  Delay is TE_B 50 % to Z 50 %; transition is 20/80,
    exactly as for a combinational arc.
    """
    # A level that makes Z settle to `direction` once enabled
    if kind == "ebufn":
        a_level = 1 if direction == "rise" else 0
    else:
        a_level = 0 if direction == "rise" else 1
    start_v = 0.0 if direction == "rise" else VDD
    rail = "0" if direction == "rise" else "vdd"

    T = slew / (TH_HIGH - TH_LOW)
    t1 = max(3 * slew, 2.0)
    tend = t1 + T + max(8 * slew, 28.0)
    L = [f"* enable {cell} slew={slew} {direction}", header().rstrip(),
         f"Vdd vdd 0 {VDD}", f"Va a 0 {VDD if a_level else 0}",
         "Vte te 0 " + pwl([(0, VDD), (t1, VDD), (t1 + T, 0)])]
    for i, c in enumerate(loads):
        L.append(f"X{i} z{i} a te vdd 0 {cell}")
        L.append(f"C{i} z{i} 0 {c:.9f}p")
        L.append(f"Rk{i} z{i} {rail} {KEEPER_OHM:.6g}")
    L.append(".ic " + " ".join(f"v(z{i})={start_v}" for i in range(len(loads))))
    mid, lo, hi = TH_MID * VDD, TH_LOW * VDD, TH_HIGH * VDD
    for i in range(len(loads)):
        if direction == "rise":
            L += [f".meas tran d{i} trig v(te) val={mid} fall=1 "
                  f"targ v(z{i}) val={mid} rise=1",
                  f".meas tran t{i} trig v(z{i}) val={lo} rise=1 "
                  f"targ v(z{i}) val={hi} rise=1"]
        else:
            L += [f".meas tran d{i} trig v(te) val={mid} fall=1 "
                  f"targ v(z{i}) val={mid} fall=1",
                  f".meas tran t{i} trig v(z{i}) val={hi} fall=1 "
                  f"targ v(z{i}) val={lo} fall=1"]
        # the pre-edge output level -- proof the keeper actually held Hi-Z
        L.append(f".meas tran h{i} FIND v(z{i}) AT={t1:.6f}n")
    L += [f".tran {min(slew / 8, 0.01):.6f}n {tend:.6f}n",
          ".control", "run", ".endc", ".end"]
    m = cached(f"en_{cell}_{slew}_{direction}",
               lambda: measures(ngspice(f"en_{cell}_{slew}_{direction}",
                                        "\n".join(L))))
    delay, trans, hold = [], [], []
    for i in range(len(loads)):
        if f"d{i}" not in m or f"t{i}" not in m:
            raise RuntimeError(f"enable {cell} {slew} {direction}: missing {i}")
        delay.append(m[f"d{i}"] * 1e9)
        trans.append(m[f"t{i}"] * 1e9)
        hold.append(m.get(f"h{i}"))
    return delay, trans, hold


def check_hold(hold, direction, ctx):
    """The keeper must have held the floating node at its rail."""
    want = 0.0 if direction == "rise" else VDD
    for i, v in enumerate(hold):
        if v is None or abs(v - want) > HOLD_TOL:
            raise RuntimeError(
                f"{ctx}: keeper failed to hold load point {i} "
                f"(v={v}, wanted {want} +/- {HOLD_TOL})")


# --------------------------------------------------------------------------
# 5. three_state_disable
# --------------------------------------------------------------------------
def disable_states(kind, direction):
    """(A level, held output voltage) for a disable arc.

    `direction` is the direction the output is released TOWARDS, matching the
    Liberty table name: cell_rise means the cell was driving low and lets the
    node rise, so the output sits at the LOW rail and its slew threshold on
    the way out is 20 % of VDD.
    """
    driven_high = (direction == "fall")
    if kind == "ebufn":
        a_level = 1 if driven_high else 0
    else:
        a_level = 0 if driven_high else 1
    v_hold = (TH_HIGH if driven_high else TH_LOW) * VDD
    return a_level, v_hold


def measure_disable(cell, kind, slew):
    """Driven -> Hi-Z, as the decay of the cell's output drive current.

    The output node is held by an ideal source at exactly the slew threshold
    it would cross on its way out of the driven level (20 % of VDD when the
    cell drives low, 80 % when it drives high).  While enabled the cell pushes
    a large current I_on through that source; once TE_B disables it, that
    current collapses.  The disable delay is TE_B's 50 % crossing to the last
    time |I| falls through I_on/2 -- the same 50 % convention every other
    propagation number in this library uses, applied to the quantity that
    actually goes away.

    A voltage-threshold measurement is not possible here: after the driver
    lets go, nothing but the keeper moves the node, so the answer would be
    0.2 x R_keeper x C_load (hundreds of microseconds, and proportional to the
    load) rather than a property of the cell.  See NOTES.md.

    Both polarities ride in one deck, sharing the TE_B source.  The waveforms
    are written out and the crossings found in Python, which also yields the
    10 % criterion for the log without a second simulation.
    """
    T = slew / (TH_HIGH - TH_LOW)
    t1 = max(3 * slew, 1.0)
    tend = t1 + T + max(4 * slew, 8.0)
    a_r, v_r = disable_states(kind, "rise")
    a_f, v_f = disable_states(kind, "fall")
    DATA.mkdir(parents=True, exist_ok=True)
    out_file = DATA / f"dis_{cell}_{slew}.txt"
    L = [f"* disable {cell} slew={slew}", header().rstrip(), f"Vdd vdd 0 {VDD}",
         "Vte te 0 " + pwl([(0, 0), (t1, 0), (t1 + T, VDD)]),
         f"Var ar 0 {VDD if a_r else 0}", f"Vhr zr 0 {v_r:.6f}",
         f"Xr zr ar te vdd 0 {cell}",
         f"Vaf af 0 {VDD if a_f else 0}", f"Vhf zf 0 {v_f:.6f}",
         f"Xf zf af te vdd 0 {cell}",
         f".tran {min(slew / 50, 0.002):.6f}n {tend:.6f}n",
         ".control", "run",
         "let ir = abs(i(vhr))", "let iff = abs(i(vhf))",
         f"wrdata {out_file} v(te) ir iff", ".endc", ".end"]
    if not out_file.exists():
        ngspice(f"dis_{cell}_{slew}", "\n".join(L))
    cols = []
    for line in out_file.read_text().splitlines():
        f = [float(x) for x in line.split()]
        if len(f) == 6:                          # t v(te) t ir t iff
            cols.append((f[0], f[1], f[3], f[5]))
    if not cols:
        raise RuntimeError(f"disable {cell} {slew}: no waveform data")
    t = [c[0] for c in cols]
    te = [c[1] for c in cols]
    t_te50 = cross(t, te, TH_MID * VDD, "rise")
    res = {}
    for k, idx in (("rise", 2), ("fall", 3)):
        cur = [c[idx] for c in cols]
        # I_on: the settled drive current just before the edge starts
        pre = [cur[i] for i in range(len(t)) if t[i] <= t1 * 1e-9]
        i_on = sum(pre[-20:]) / len(pre[-20:]) if pre else cur[0]
        vals = {}
        for frac in (0.5, 0.1):
            tc = cross(t, cur, frac * i_on, "fall", last=True)
            vals[frac] = None if tc is None else (tc - t_te50) * 1e9
        res[k] = {"i_on": i_on, "d50": vals[0.5], "d10": vals[0.1]}
    return res


def cross(xs, ys, level, sense, last=False):
    """Linearly interpolated crossing of `level`.  `last` takes the final one."""
    hits = []
    for i in range(1, len(xs)):
        a, b = ys[i - 1], ys[i]
        if sense == "rise" and a < level <= b or \
           sense == "fall" and a > level >= b:
            f = (level - a) / (b - a) if b != a else 0.0
            hits.append(xs[i - 1] + f * (xs[i] - xs[i - 1]))
    if not hits:
        return None
    return hits[-1] if last else hits[0]


# --------------------------------------------------------------------------
# calibration: reproduce a shipped capacitance
# --------------------------------------------------------------------------
CAL_REF = {"rise": 0.009166, "fall": 0.008236}    # shipped sg13g2_hv_buf_4 A


def calibrate():
    """The charge-integration harness must reproduce a number already in the
    shipped library, or it is not the same measurement the rest of the library
    was built with.  sg13g2_hv_buf_4 pin A: rise 0.009166 pF, fall 0.008236.

    Launched into the pool alongside the cell measurements rather than ahead of
    them.  buf_4's deck is, for whatever reason, by far the most expensive one
    here -- hundreds of ngspice CPU-seconds against single digits for the
    tri-state cells -- and running it first put one slow simulation in front of
    the other ~180.  The result is reported at the end of the run instead.
    """
    r, f = measure_cap("sg13g2_hv_buf_4", "A", {}, "cal")
    err = max(abs(r - CAL_REF["rise"]) / CAL_REF["rise"],
              abs(f - CAL_REF["fall"]) / CAL_REF["fall"])
    return {"rise": r, "fall": f, "ref_rise": CAL_REF["rise"],
            "ref_fall": CAL_REF["fall"], "err": err}


# --------------------------------------------------------------------------
# measurement driver
# --------------------------------------------------------------------------
def measure_all():
    """Measure every cell.

    All ~165 simulations for all six cells are submitted to the pool up front,
    then collected.  Submitting them phase by phase per cell -- leakage, then
    capacitance, then the seven combinational slews, then enable, then disable
    -- capped the useful concurrency at seven no matter how large CT_JOBS was,
    and every phase boundary drained the pool to a single straggler.
    """
    areas = lef_areas()
    result = {"cells": {}}
    pool = ThreadPoolExecutor(max_workers=int(os.environ.get("CT_JOBS", 4)))
    cal_job = pool.submit(calibrate)

    plan = {}
    for cell, kind, lv_maxcap, lv_name in CELLS:
        maxcap = round(lv_maxcap * 2.20, 6)
        loads = [0.0022] + [round(maxcap * f, 6) for f in LOAD_FRACTIONS]
        whens = LEAK_WHEN[kind]
        if cell.endswith("einvn_2"):
            whens = LEAK_WHEN_EINVN_2
        # einvn emits only a three_state_enable_rise group (its thin-oxide
        # counterpart does the same), so its fall arc is never used and is not
        # simulated.  ebufn emits both.
        dirs = ("rise", "fall") if kind == "ebufn" else ("rise",)
        plan[cell] = {
            "kind": kind, "lv_name": lv_name, "area": areas[cell],
            "max_capacitance": maxcap, "loads": loads, "slews": SLEWS,
            "whens": whens, "dirs": dirs,
            "leak": [(w, pool.submit(measure_leakage, cell, s))
                     for w, s in whens],
            # Output pin capacitance is the load a *disabled* cell presents to
            # whoever else drives the net, so TE_B is tied inactive.  Both A
            # states are measured and the worst taken, as CharLib does for
            # rise vs fall.
            "cap": {pin: pool.submit(measure_cap, cell, pin, {}, "in")
                    for pin in ("A", "TE_B")},
            "capz": [pool.submit(measure_cap, cell, "Z", {"TE_B": 1, "A": a},
                                 f"hiz_a{a}") for a in (0, 1)],
            "comb": {s: pool.submit(measure_comb, cell, kind, loads, s)
                     for s in SLEWS},
            "en": {(d, s): pool.submit(measure_enable, cell, kind, loads, s, d)
                   for d in dirs for s in SLEWS},
            "dis": {s: pool.submit(measure_disable, cell, kind, s)
                    for s in SLEWS},
        }

    for cell, _, _, _ in CELLS:
        j = plan[cell]
        print(f"\n{cell}", flush=True)
        c = {k: j[k] for k in ("kind", "lv_name", "area", "max_capacitance",
                               "loads", "slews")}
        loads = j["loads"]

        leaks = []
        for when, job in j["leak"]:
            pw, vz = job.result()
            leaks.append({"when": when, "value": pw, "v_out": vz})
            print(f"  leakage {when:16s} {pw:12.6f} nW", flush=True)
        c["leakage"] = leaks
        c["cell_leakage_power"] = sum(x["value"] for x in leaks) / len(leaks)

        c["cap"] = {}
        for pin in ("A", "TE_B"):
            r, f = j["cap"][pin].result()
            c["cap"][pin] = {"rise": r, "fall": f, "value": max(r, f)}
            print(f"  cap {pin:6s} rise {r:.6f} fall {f:.6f} pF", flush=True)
        zr = zf = 0.0
        for a, job in zip((0, 1), j["capz"]):
            r, f = job.result()
            zr, zf = max(zr, r), max(zf, f)
            print(f"  cap Z (Hi-Z, A={a}) rise {r:.6f} fall {f:.6f} pF",
                  flush=True)
        c["cap"]["Z"] = {"rise": zr, "fall": zf, "value": max(zr, zf)}

        comb = {k: [] for k in ("cell_rise", "rise_transition",
                                "cell_fall", "fall_transition")}
        for s in SLEWS:
            r = j["comb"][s].result()
            for k in comb:
                comb[k].append(r[k])            # [slew][load]
        # transpose to [load][slew] -- HV index_1 is the LOAD axis
        c["comb"] = {k: transpose(v) for k, v in comb.items()}
        print(f"  A->Z   cell_rise "
              f"{min(map(min, c['comb']['cell_rise'])):.4f} - "
              f"{max(map(max, c['comb']['cell_rise'])):.4f} ns", flush=True)

        c["enable"] = {}
        for d in j["dirs"]:
            delays, transs = [], []
            for s in SLEWS:
                dl, tr, hold = j["en"][(d, s)].result()
                check_hold(hold, d, f"enable {cell} slew={s} {d}")
                delays.append(dl)
                transs.append(tr)
            c["enable"][d] = {"delay": transpose(delays),
                              "transition": transpose(transs)}
            print(f"  enable {d}  {min(map(min, c['enable'][d]['delay'])):.4f} "
                  f"- {max(map(max, c['enable'][d]['delay'])):.4f} ns",
                  flush=True)

        dis = {"rise": [], "fall": [], "raw": {}}
        for s in SLEWS:
            r = j["dis"][s].result()
            dis["raw"][str(s)] = r
            for d in ("rise", "fall"):
                if r[d]["d50"] is None:
                    raise RuntimeError(f"disable {cell} {s} {d}: no crossing")
                dis[d].append(r[d]["d50"])
        c["disable"] = dis
        print(f"  disable rise {['%.4f' % x for x in dis['rise']]}", flush=True)
        print(f"  disable fall {['%.4f' % x for x in dis['fall']]}", flush=True)

        result["cells"][cell] = c

    cal = cal_job.result()
    print(f"\ncalibration sg13g2_hv_buf_4 A: rise {cal['rise']:.6f} "
          f"(lib {cal['ref_rise']}), fall {cal['fall']:.6f} "
          f"(lib {cal['ref_fall']}) -> {cal['err'] * 100:.1f}% apart")
    if cal["err"] > 0.05:
        raise RuntimeError(
            "charge-integration harness does not reproduce the shipped "
            f"sg13g2_hv_buf_4 pin A capacitance ({cal['err'] * 100:.1f}% off); "
            "the measured capacitances are not comparable with the rest of "
            "the library")
    result["calibration"] = cal
    pool.shutdown()
    return result


def transpose(m):
    return [list(r) for r in zip(*m)]


# --------------------------------------------------------------------------
# Liberty emission
# --------------------------------------------------------------------------
def axis(vals):
    return ", ".join(f"{v:.6f}" for v in vals)


def table(name, rows, loads, slews, indent):
    """A 7x7 lookup table in the shipped HV style: index_1 = loads (the HV
    templates declare variable_1 = total_output_net_capacitance), index_2 =
    slews, values row-major over the load axis."""
    p = " " * indent
    L = [f'{p}{name} (delay_template_7x7) {{',
         f'{p}  index_1 ("{axis(loads)}") ;',
         f'{p}  index_2 ("{axis(slews)}") ;',
         f'{p}  values ( \\']
    for r in rows:
        L.append(f'{p}    "{axis(r)}" \\')
    L[-1] = L[-1][:-2]                          # no continuation on the last
    L.append(f'{p}  ) ;')
    L.append(f'{p}}} /* end {name} */')
    return L


def const_rows(values, nloads):
    """A table that is constant along the load axis: one row per load, each
    row the per-slew vector.  Mirrors the thin-oxide library, whose disable
    tables are load-independent."""
    return [list(values) for _ in range(nloads)]


def emit_cell(cell, c):
    kind = c["kind"]
    loads, slews = c["loads"], c["slews"]
    L = [f"  cell ({cell}) {{",
         f"    area : {c['area']} ;",
         f'    cell_footprint : "{kind}" ;',
         f"    cell_leakage_power : {c['cell_leakage_power']:.6f} ;"]
    for lk in c["leakage"]:
        L += ["    leakage_power () {",
              f'      when : "{lk["when"]}" ;',
              f"      value : {lk['value']:.6f} ;",
              "    } /* end leakage_power */"]

    # ---- pin (Z) --------------------------------------------------------
    fn = "A" if kind == "ebufn" else "!(A)"
    unate = "positive_unate" if kind == "ebufn" else "negative_unate"
    cz = c["cap"]["Z"]
    L += ["    pin (Z) {",
          "      direction : output ;",
          f"      max_capacitance : {c['max_capacitance']} ;",
          f"      max_transition : {MAX_TRANSITION} ;",
          f'      function : "{fn}" ;',
          '      three_state : "TE_B" ;',
          f"      rise_capacitance : {cz['rise']:.6f} ;",
          f"      fall_capacitance : {cz['fall']:.6f} ;",
          f"      capacitance : {cz['value']:.6f} ;"]

    # combinational A -> Z
    L += ["      timing () {",
          "        related_pin : A ;",
          f"        timing_sense : {unate} ;",
          "        timing_type : combinational ;"]
    for t in ("cell_rise", "rise_transition", "cell_fall", "fall_transition"):
        L += table(t, c["comb"][t], loads, slews, 8)
    L.append("      } /* end timing */")

    # three_state_disable
    dis_type = ("three_state_disable" if kind == "ebufn"
                else "three_state_disable_rise")
    L += ["      timing () {",
          "        related_pin : TE_B ;",
          "        sdf_edges : start_edge ;",
          "        timing_sense : positive_unate ;",
          f"        timing_type : {dis_type} ;"]
    dr = const_rows(c["disable"]["rise"], len(loads))
    df = const_rows(c["disable"]["fall"], len(loads))
    # The output does not traverse a slew after the driver lets go, so the
    # transition table repeats the delay -- the thin-oxide library's own
    # convention (its disable cell_rise and rise_transition are identical).
    L += table("cell_rise", dr, loads, slews, 8)
    L += table("rise_transition", dr, loads, slews, 8)
    if kind == "ebufn":
        L += table("cell_fall", df, loads, slews, 8)
        L += table("fall_transition", df, loads, slews, 8)
    L.append("      } /* end timing */")

    # three_state_enable
    en_type = ("three_state_enable" if kind == "ebufn"
               else "three_state_enable_rise")
    L += ["      timing () {",
          "        related_pin : TE_B ;",
          "        sdf_edges : start_edge ;",
          "        timing_sense : negative_unate ;",
          f"        timing_type : {en_type} ;"]
    L += table("cell_rise", c["enable"]["rise"]["delay"], loads, slews, 8)
    L += table("rise_transition", c["enable"]["rise"]["transition"],
               loads, slews, 8)
    if kind == "ebufn":
        L += table("cell_fall", c["enable"]["fall"]["delay"], loads, slews, 8)
        L += table("fall_transition", c["enable"]["fall"]["transition"],
                   loads, slews, 8)
    L.append("      } /* end timing */")
    L.append("    } /* end pin */")

    # ---- input pins -----------------------------------------------------
    for pin in ("A", "TE_B"):
        cp = c["cap"][pin]
        L += [f"    pin ({pin}) {{",
              "      direction : input ;",
              f"      max_transition : {MAX_TRANSITION} ;",
              f"      rise_capacitance : {cp['rise']:.6f} ;",
              f"      fall_capacitance : {cp['fall']:.6f} ;",
              f"      capacitance : {cp['value']:.6f} ;",
              "    } /* end pin */"]

    L += ["    pg_pin (VDD) {",
          "      voltage_name : VDD ;",
          "      pg_type : primary_power ;",
          "    } /* end pg_pin */",
          "    pg_pin (VSS) {",
          "      voltage_name : VSS ;",
          "      pg_type : primary_ground ;",
          "    } /* end pg_pin */",
          "  } /* end cell */"]
    return "\n".join(L) + "\n"


def emit(data):
    return "".join(emit_cell(cell, data["cells"][cell])
                   for cell, *_ in CELLS)


# --------------------------------------------------------------------------
def main():
    js = WORK / f"measured_{CORNER.name}.json"
    if "--reuse" in sys.argv and js.exists():
        data = json.loads(js.read_text())
        print(f"reusing {js}")
    else:
        data = measure_all()
        js.write_text(json.dumps(data, indent=1))
        print(f"\nwrote {js}")
    out = WORK / f"tristate_{CORNER.name}.lib"
    out.write_text(emit(data))
    print(f"wrote {out}")


if __name__ == "__main__":
    import argparse
    ap = corners.add_argument(argparse.ArgumentParser(
        description="Characterize the 6 tri-state cells at one PVT corner."))
    ap.add_argument("--reuse", action="store_true",
                    help="re-emit from measured.json without re-simulating")
    args = ap.parse_args()
    CORNER = corners.CORNERS[args.corner]
    # HOLD_TOL is derived from VDD at module level, so it has to be
    # recomputed with it: rebinding VDD alone would leave the keeper
    # tolerance holding the previous corner's volts -- a check that still
    # runs, still passes or fails, and is quietly against the wrong rail.
    VDD = CORNER.voltage
    HOLD_TOL = 0.05 * VDD
    print(f"corner {CORNER.name}: {CORNER.models}, {VDD} V, "
          f"{CORNER.temperature:g} C")
    main()
