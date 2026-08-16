#!/usr/bin/env python3
"""Turn sg13g2_stdcell_hv's Verilog models into a functional (zero-delay) copy.

The shipped models are vendor-style: the sequential cells feed their UDPs from
`delayed_*` wires and drive a `notifier` reg, and both of those are produced by
the timing checks *inside* the specify block. Icarus cannot compile those
blocks at all -- it rejects `ifnone` on an edge-sensitive path -- and simply
deleting them leaves `delayed_*` undriven and `notifier` at X, so every
flip-flop output sits at X forever.

For a functional gate-level run the specify blocks carry no information, so
this drops them and restores what they used to provide:

  * `assign delayed_<PORT> = <PORT>;` for every delayed_ wire
  * `initial notifier = 1'b0;`

Usage:  make_functional_models.py <in.v> <out.v>
"""
import pathlib
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
lines = pathlib.Path(src).read_text().splitlines(True)

out, skip = [], False
n_spec = n_not = n_del = 0
for ln in lines:
    s = ln.strip()
    if s == "specify":
        skip = True
        n_spec += 1
        continue
    if s == "endspecify":
        skip = False
        continue
    if skip:
        continue
    out.append(ln)

    if s == "reg notifier;":
        out.append("\tinitial notifier = 1'b0;\n")
        n_not += 1

    m = re.match(r"wire\s+(delayed_.*);$", s)
    if m:
        for w in (x.strip() for x in m.group(1).split(",")):
            port = w[len("delayed_"):]
            out.append(f"\tassign {w} = {port};\n")
            n_del += 1

pathlib.Path(dst).write_text("".join(out))
print(f"{dst}: dropped {n_spec} specify blocks, "
      f"tied {n_del} delayed_ wires to their ports, "
      f"initialised {n_not} notifiers")
