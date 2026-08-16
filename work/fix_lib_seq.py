#!/usr/bin/env python3
"""Fix the sequential-cell modelling in a Liberty file emitted by CharLib.

`fix_lib.py` strips the `Y = ` left-hand side CharLib puts in every `function`
attribute. That is correct for combinational cells, but for a flip-flop or
latch the output pin's function is not an expression over the inputs at all --
it is the state variable declared by the enclosing `ff` / `latch` group:

    pin (Q)   { function : "IQ";  }
    pin (Q_N) { function : "IQN"; }

CharLib instead writes the *next-state* expression there (`"Q = D"`, and after
LHS stripping just `"D"`), which makes every flip-flop look combinational:
Yosys' dfflibmap then finds no async-reset FF in the library at all and aborts
with "dffs with async set or reset are not supported", and a static timing
tool sees a D->Q combinational arc instead of a clock boundary.

Two further deviations from the reference thin-oxide library are repaired at
the same time:

* CharLib emits two state groups per cell, `ff (IQ, IQinv)` for Q and
  `ff (IQN, IQNinv)` for Q_N. The second is redundant -- a Liberty state group
  already declares both the state variable and its complement -- and its extra
  variable names are what forced the wrong pin functions. Collapse to the
  single conventional `ff (IQ,IQN)` / `latch (IQ,IQN)` group.
* A group carrying both `clear` and `preset` must also define
  `clear_preset_var1` / `clear_preset_var2`, the state of Q / QN when both are
  asserted. CharLib omits them; the thin-oxide library uses H / L.

Negations are normalised from Liberty's postfix `X'` to the prefix `!X` the
reference library uses. Both are legal; being consistent keeps a diff against
the thin-oxide library readable.

Idempotent: a file that is already correct is left untouched.

Usage:  fix_lib_seq.py <file.lib> [more.lib ...]
"""
import re
import sys
import pathlib

# a whole ff/latch group, captured with its indentation
GROUP = re.compile(r'([ \t]*)(ff|latch)[ \t]*\(([^)]*)\)[ \t]*\{(.*?)\n[ \t]*\}[ \t]*(?:/\*[^*]*\*/)?',
                   re.S)
CELL = re.compile(r'\n  cell \((\w+)\)')


def norm(expr):
    """Postfix negation X' -> prefix !X, and strip redundant quoting."""
    expr = expr.strip().strip('"').strip()
    expr = re.sub(r'\b(\w+)\s*\'', r'!\1', expr)
    return expr


def rewrite_cell(body):
    """Return (new_body, n_groups_removed, n_funcs_fixed) for one cell body."""
    groups = list(GROUP.finditer(body))
    if not groups:
        return body, 0, 0

    first = groups[0]
    indent, kind, attrs = first.group(1), first.group(2), first.group(4)

    # collect the attributes of the first (IQ) group, in Liberty's order
    keep = {}
    for m in re.finditer(r'(\w+)\s*:\s*("[^"]*"|[^;\n]+)\s*;', attrs):
        keep[m.group(1)] = norm(m.group(2))

    order = ([k for k in ("clear", "clear_preset_var1", "clear_preset_var2",
                          "clocked_on", "data_in", "enable", "next_state",
                          "preset") if k in keep]
             + [k for k in keep if k not in ("clear", "clear_preset_var1",
                                             "clear_preset_var2", "clocked_on",
                                             "data_in", "enable", "next_state",
                                             "preset")])
    if "clear" in keep and "preset" in keep:
        keep.setdefault("clear_preset_var1", "H")
        keep.setdefault("clear_preset_var2", "L")
        for k, pos in (("clear_preset_var1", 1), ("clear_preset_var2", 2)):
            if k not in order:
                order.insert(pos, k)

    lines = [f'{indent}{kind} (IQ,IQN) {{']
    for k in order:
        v = keep[k]
        quoted = f'"{v}"' if k not in ("clear_preset_var1", "clear_preset_var2") else f'"{v}"'
        lines.append(f'{indent}  {k} : {quoted};')
    lines.append(f'{indent}}}')
    new_group = "\n".join(lines)

    # splice: first group replaced, any further groups deleted
    out, prev, removed = [], 0, 0
    for i, m in enumerate(groups):
        out.append(body[prev:m.start()])
        if i == 0:
            out.append(new_group)
        else:
            removed += 1          # drop the redundant complement group
            out.append(m.group(1).rstrip("\n"))
        prev = m.end()
    out.append(body[prev:])
    body = "".join(out)

    # output pin functions -> state variables
    n_func = 0

    def pin_sub(m):
        nonlocal n_func
        pin, inner = m.group(1), m.group(2)
        if pin not in ("Q", "Q_N"):
            return m.group(0)
        want = "IQ" if pin == "Q" else "IQN"
        new_inner, n = re.subn(r'(function\s*:\s*")[^"]*(")',
                               lambda f: f.group(1) + want + f.group(2), inner)
        n_func += n
        return f'pin ({pin}) {{{new_inner}'

    body = re.sub(r'pin \((\w+)\) \{(.*?)(?=\n\s*pin \(|\Z)', pin_sub, body, flags=re.S)
    return body, removed, n_func


def fix(path):
    p = pathlib.Path(path)
    text = p.read_text()

    bounds = [(m.group(1), m.end()) for m in CELL.finditer(text)]
    pieces, prev_end, tot_g, tot_f, cells = [], 0, 0, 0, []
    for i, (name, start) in enumerate(bounds):
        end = bounds[i + 1][1] - len(f"\n  cell ({bounds[i+1][0]})") if i + 1 < len(bounds) else len(text)
        pieces.append(text[prev_end:start])
        body = text[start:end]
        new_body, g, f = rewrite_cell(body)
        if g or f:
            cells.append(name)
        tot_g += g
        tot_f += f
        pieces.append(new_body)
        prev_end = end
    pieces.append(text[prev_end:])
    new_text = "".join(pieces)

    if new_text != text:
        p.write_text(new_text)
    print(f"{p}: {len(cells)} sequential cells repaired "
          f"({tot_f} pin functions -> state variables, "
          f"{tot_g} redundant state groups removed)")
    if cells:
        print("  " + " ".join(cells))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for f in sys.argv[1:]:
        fix(f)
