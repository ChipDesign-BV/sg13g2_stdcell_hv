#!/usr/bin/env python3
"""Sequential-cell equivalence: thick-oxide vs thin-oxide, in transient.

A bistable cell has no well-defined DC operating point, so the combinational
vector sweep cannot check it. Instead each stateful cell is clocked through a
stimulus that walks a binary counter over its non-clock inputs, and the
outputs of the thin-oxide cell (at 1.2 V) and the thick-oxide cell (at 3.3 V)
are sampled late in every clock period and required to agree.

Both instances live in one deck and share the same stimulus pattern, scaled to
their own rail, so state and timing are compared on equal footing.

The run starts with a reset period so both instances leave the indeterminate
power-up state into the same known state. Samples where SET_B and RESET_B are
asserted at once are illegal input states with no defined reference value, and
are excluded from the comparison rather than silently counted as passes.
"""
import subprocess, re, pathlib, sys, os
from concurrent.futures import ProcessPoolExecutor
from libinfo import pininfo, sequential, hvname, LV, HV, MODELS, NGSPICE

WORK = pathlib.Path(__file__).parent
DECKS = WORK / "seq_decks"
VLV, VHV = 1.2, 3.3
TCLK = 20e-9          # 140x the thick-oxide FO4 delay, so both settle fully
TR = 0.2e-9
PASSES = 2            # walk the input counter twice, so state carries over


def clock_pin(ins):
    for want in ("CLK", "GATE", "GATE_N"):
        if want in ins:
            return want
    return ins[0]


def stimulus(ins):
    """[(period_index, {pin: level})] -- period 0 resets, then a binary
    counter over the non-clock inputs, walked PASSES times."""
    clk = clock_pin(ins)
    others = [p for p in ins if p != clk]
    seq = [{p: (1 if p.endswith("_B") else 0) for p in others}]  # reset period
    if "RESET_B" in seq[0]:
        seq[0]["RESET_B"] = 0
    for _ in range(PASSES):
        for m in range(2 ** len(others)):
            seq.append({p: (m >> k) & 1 for k, p in enumerate(others)})
    return clk, others, seq


def pwl(levels, vdd, tstart_offset):
    """PWL string: level per clock period, switching just after each period
    boundary so setup time to the next active edge is 0.9*TCLK."""
    pts, prev = [], None
    for m, v in enumerate(levels):
        t = m * TCLK + tstart_offset
        if prev is None:
            pts.append((0.0, v * vdd))
        else:
            if v != prev:
                pts.append((t, prev * vdd))
                pts.append((t + TR, v * vdd))
        prev = v
    return " ".join(f"{t:.12g} {v:.6g}" for t, v in pts)


def build(cell, pins):
    ins = [p for p, d in pins if d == "I"]
    outs = [p for p, d in pins if d == "O"]
    clk, others, seq = stimulus(ins)
    n = len(seq)
    tstop = n * TCLK

    L = [f"* {cell}: sequential equivalence, thin-oxide vs thick-oxide",
         f".lib {MODELS}/cornerMOSlv.lib mos_tt",
         f".lib {MODELS}/cornerMOShv.lib mos_tt",
         f".include {LV/'spice'/'sg13g2_stdcell.spice'}",
         f".include {HV/'spice'/'sg13g2_stdcell_hv.spice'}", ""]
    for var, vdd in (("lv", VLV), ("hv", VHV)):
        L.append(f"V{var}dd {var}dd 0 {vdd}")
        # clock: rises at each period boundary, falls at mid-period
        L.append(f"V{var}_{clk} i_{var}_{clk} 0 pulse(0 {vdd} 0 {TR} {TR} "
                 f"{TCLK/2-TR} {TCLK})")
        for p in others:
            levels = [s[p] for s in seq]
            L.append(f"V{var}_{p} i_{var}_{p} 0 pwl({pwl(levels, vdd, 0.1*TCLK)})")
    L.append("")
    for var, vdd in (("lv", VLV), ("hv", VHV)):
        sub = cell if var == "lv" else hvname(cell)
        nets = []
        for p, d in pins:
            if d == "I":
                nets.append(f"i_{var}_{p}")
            elif d == "O":
                nets.append(f"o_{var}_{p}")
            elif p == "VDD":
                nets.append(f"{var}dd")
            else:
                nets.append("0")
        L.append(f"X{var} {' '.join(nets)} {sub}")
    L += ["", ".control",
          f"tran {TR/4:.12g} {tstop:.12g} uic"]
    vecs = " ".join(f"v(o_{v}_{o})" for o in outs for v in ("lv", "hv"))
    L += [f"wrdata {cell}.dat {vecs}", "quit", ".endc", ".end"]
    return "\n".join(L) + "\n", outs, seq, n


def one(args):
    cell, pins = args
    text, outs, seq, n = build(cell, pins)
    f = DECKS / f"{cell}.spice"
    f.write_text(text)
    p = subprocess.run([NGSPICE, "-b", str(f)], cwd=DECKS,
                       capture_output=True, text=True, timeout=3600)
    dat = DECKS / f"{cell}.dat"
    if not dat.exists():
        return cell, None, (p.stdout[-1500:] + p.stderr[-1500:])

    # wrdata writes an (x, y) column pair per vector
    rows = []
    for line in dat.read_text().splitlines():
        t = line.split()
        if len(t) >= 2 * 2 * len(outs) // 2:
            try:
                rows.append([float(x) for x in t])
            except ValueError:
                pass
    if not rows:
        return cell, None, "empty wrdata output"

    time = [r[0] for r in rows]

    def at(t, col):
        for i in range(1, len(time)):
            if time[i] >= t:
                t0, t1 = time[i - 1], time[i]
                y0, y1 = rows[i - 1][col], rows[i][col]
                if t1 == t0:
                    return y1
                return y0 + (y1 - y0) * (t - t0) / (t1 - t0)
        return rows[-1][col]

    def digit(v, vdd):
        if v > 0.9 * vdd:
            return "1"
        if v < 0.1 * vdd:
            return "0"
        return "?"

    results = []
    for m in range(1, n):                      # skip the reset period itself
        s = seq[m]
        if s.get("SET_B", 1) == 0 and s.get("RESET_B", 1) == 0:
            continue                           # illegal: set and reset at once
        t = (m + 0.95) * TCLK
        for oi, o in enumerate(outs):
            clv = 1 + 4 * oi                   # (t, v_lv, t, v_hv) per output
            chv = 3 + 4 * oi
            a = digit(at(t, clv), VLV)
            b = digit(at(t, chv), VHV)
            results.append((m, s, o, a, b))
    return cell, results, None


def main():
    DECKS.mkdir(exist_ok=True)
    info, seq = pininfo(), sequential()
    cells = sorted(seq)
    print(f"{len(cells)} stateful cells, clocked equivalence vs thin-oxide\n")

    fails, total, bad = [], 0, 0
    # ngspice is pinned to one thread in .spiceinit, so one worker per core
    # without oversubscribing
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 2)) as ex:
        for cell, rows, err in ex.map(one, [(c, info[c]) for c in cells]):
            if rows is None:
                print(f"  {cell:22s} ERROR: {err[:200]}")
                fails.append((cell, "-", "-", "sim error", err[:120]))
                continue
            ok = sum(1 for r in rows if r[3] == r[4] and r[3] != "?")
            total += len(rows)
            for m, s, o, a, b in rows:
                if a != b or a == "?":
                    bad += 1
                    if len(fails) < 30:
                        iv = " ".join(f"{k}={v}" for k, v in sorted(s.items()))
                        fails.append((cell, f"period {m} [{iv}]", o,
                                      f"LV={a}", f"HV={b}"))
            print(f"  {cell:22s} {ok:4d}/{len(rows):4d} samples match",
                  flush=True)

    print(f"\nsamples matching: {total-bad}/{total}")
    if fails:
        print("\nfailures:")
        for f in fails[:30]:
            print("  " + "  ".join(str(x) for x in f))
    print("\nRESULT:", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
