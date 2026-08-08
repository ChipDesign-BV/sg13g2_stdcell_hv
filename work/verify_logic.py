#!/usr/bin/env python3
"""Functional equivalence: thick-oxide library vs the thin-oxide original.

Every combinational cell is driven with every input vector in both libraries
-- LV at 1.2 V, HV at 3.3 V -- and the digitised outputs are required to
agree. The thin-oxide library is the golden reference, so no truth tables are
written by hand and a topology error introduced by the transform cannot hide.

Both libraries go into one deck per cell: the LV and HV model decks define
disjoint model names, so they coexist, and the two variants are guaranteed to
see identical input vectors.

Tri-state outputs are held by a 1 Gohm resistor to their own mid-rail, so a
high-Z output sits at mid-rail and is distinguishable from a driven 0 or 1.
"""
import subprocess, re, pathlib, sys, itertools, os
from concurrent.futures import ProcessPoolExecutor
from libinfo import pininfo, sequential, hvname, LV, HV, MODELS, NGSPICE

WORK = pathlib.Path(__file__).parent
DECKS = WORK / "decks"
VLV, VHV = 1.2, 3.3


def build(cell, pins):
    """One deck holding every input vector of `cell` in both libraries."""
    ins = [p for p, d in pins if d == "I"]
    outs = [p for p, d in pins if d == "O"]
    L = [f"* {cell}: exhaustive vectors, thin-oxide vs thick-oxide",
         f".lib {MODELS}/cornerMOSlv.lib mos_tt",
         f".lib {MODELS}/cornerMOShv.lib mos_tt",
         f".include {LV/'spice'/'sg13g2_stdcell.spice'}",
         f".include {HV/'spice'/'sg13g2_stdcell_hv.spice'}", "",
         f"Vlv vlv 0 {VLV}", f"Vhv vhv 0 {VHV}",
         f"Vlvh vlvh 0 {VLV/2}", f"Vhvh vhvh 0 {VHV/2}", ""]
    probes = []
    for vi, vec in enumerate(itertools.product([0, 1], repeat=len(ins))):
        for var, rail, mid, sub in (("lv", "vlv", "vlvh", cell),
                                    ("hv", "vhv", "vhvh", hvname(cell))):
            nets = []
            for p, d in pins:
                if d == "I":
                    nets.append(rail if vec[ins.index(p)] else "0")
                elif d == "O":
                    nets.append(f"o_{var}_{vi}_{p}")
                elif p == "VDD":
                    nets.append(rail)
                else:
                    nets.append("0")
            L.append(f"X{var}{vi} {' '.join(nets)} {sub}")
            for o in outs:
                L.append(f"Rk{var}{vi}{o} o_{var}_{vi}_{o} {mid} 1G")
        for o in outs:
            probes.append((vec, o, f"o_lv_{vi}_{o}", f"o_hv_{vi}_{o}"))
    L += ["", ".control", "op"]
    for _, _, a, b in probes:
        L += [f"print v({a})", f"print v({b})"]
    L += ["quit", ".endc", ".end"]
    return "\n".join(L) + "\n", probes, ins


def digit(v, vdd):
    if v > 0.9 * vdd:
        return "1"
    if v < 0.1 * vdd:
        return "0"
    if 0.35 * vdd < v < 0.65 * vdd:
        return "Z"
    return "?"


def one(args):
    cell, pins = args
    text, probes, ins = build(cell, pins)
    f = DECKS / f"{cell}.spice"
    f.write_text(text)
    p = subprocess.run([NGSPICE, "-b", str(f)], cwd=WORK,
                       capture_output=True, text=True, timeout=1800)
    # ngspice folds node names to lower case in its output
    vals = {}
    for line in p.stdout.splitlines():
        m = re.match(r"\s*v\((\S+)\)\s*=\s*([0-9.eE+-]+)\s*$", line)
        if m:
            vals[m.group(1).lower()] = float(m.group(2))
    rows = []
    for vec, o, A, B in probes:
        a, b = A.lower(), B.lower()
        if a not in vals or b not in vals:
            rows.append((vec, ins, o, None, None, None, None))
            continue
        rows.append((vec, ins, o, digit(vals[a], VLV), digit(vals[b], VHV),
                     vals[a], vals[b]))
    return cell, rows


def main():
    DECKS.mkdir(exist_ok=True)
    info = pininfo()
    seq = sequential()
    comb = sorted(c for c in info
                  if c not in seq and any(d == "O" for _, d in info[c])
                  and sum(1 for _, d in info[c] if d == "I") <= 6)
    skipped = sorted(set(info) - set(comb) - seq)
    print(f"{len(info)} cells: {len(seq)} sequential (checked separately), "
          f"{len(comb)} combinational under test, "
          f"{len(skipped)} with no output pin")
    print(f"  no-output cells: {', '.join(skipped)}")
    print(f"  sequential cells: {', '.join(sorted(seq))}\n")

    jobs = [(c, info[c]) for c in comb]
    results = {}
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 2)) as ex:
        for cell, rows in ex.map(one, jobs):
            results[cell] = rows
            ok = sum(1 for r in rows if r[3] is not None and r[3] == r[4])
            print(f"  {cell:26s} {ok:3d}/{len(rows):3d} vectors match",
                  flush=True)

    total = bad = miss = zc = 0
    fails = []
    for cell, rows in results.items():
        for vec, ins, o, a, b, va, vb in rows:
            total += 1
            if a is None:
                miss += 1
                fails.append((cell, vec, ins, o, "no result", ""))
                continue
            if a == "Z":
                zc += 1
            if a != b:
                bad += 1
                fails.append((cell, vec, ins, o,
                              f"LV={a}({va:.3f}V)", f"HV={b}({vb:.3f}V)"))

    print(f"\ncells fully matching: "
          f"{sum(1 for c, r in results.items() if all(x[3] == x[4] and x[3] for x in r))}"
          f"/{len(results)}")
    print(f"vectors matching    : {total-bad-miss}/{total}"
          f"   (high-Z states exercised: {zc})")
    if fails:
        print("\nfailures:")
        for cell, vec, ins, o, x, y in fails[:40]:
            iv = " ".join(f"{p}={v}" for p, v in zip(ins, vec))
            print(f"  {cell:26s} [{iv}] {o}: {x} {y}")
    print("\nRESULT:", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
