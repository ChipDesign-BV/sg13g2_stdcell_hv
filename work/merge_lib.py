#!/usr/bin/env python3
"""Merge characterized sequential cells into the shipped Liberty file.

The combinational library and the sequential cells are characterized in
separate CharLib runs (the sequential run needs the custom procedures and
its own grids), each producing a complete Liberty file. This merges the
cell groups of the second into the first:

  * cells present in the merge source replace any same-named cell in the
    target (there are none today -- the shipped lib is combinational only);
  * new lu_table_template groups from the source header are carried over
    (the sequential run introduces constraint templates);
  * everything else in the target header is left untouched.

Areas in the merged cells are set from the drawn GDS boundaries, same as
the combinational flow.

Usage: merge_lib.py <target.lib> <source.lib>
"""
import re
import sys
import pathlib

import klayout.db as db

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")


def cells_of(txt):
    out = {}
    for m in re.finditer(
            r"(^  cell \((\S+)\) \{.*?^  \}(?: /\* end cell \*/)?\n)",
            txt, re.S | re.M):
        out[m.group(2)] = m.group(1)
    return out


def templates_of(txt):
    out = {}
    for m in re.finditer(r"(^  lu_table_template \((\S+)\) \{.*?^  \}"
                         r"(?: /\* end lu_table_template \*/)?\n)",
                         txt, re.S | re.M):
        out[m.group(2)] = m.group(1)
    return out


def main(target_path, source_path):
    target = pathlib.Path(target_path).read_text(errors="surrogateescape")
    source = pathlib.Path(source_path).read_text(errors="surrogateescape")

    src_cells = cells_of(source)
    src_tmpl = templates_of(source)
    tgt_tmpl = templates_of(target)

    # areas from the drawn boundaries
    ly = db.Layout()
    ly.read(str(HV / "gds" / "sg13g2_stdcell_hv.gds"))
    lb = ly.layer(189, 4)
    areas = {}
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        b = [s.dbbox() for s in c.shapes(lb).each()]
        if b:
            areas[c.name] = round(b[0].width() * b[0].height(), 4)

    merged, replaced, added = target, 0, 0

    # new templates go after the last existing template
    new_tmpl = "".join(v for k, v in src_tmpl.items() if k not in tgt_tmpl)
    if new_tmpl:
        last = None
        for m in re.finditer(r"^  lu_table_template \(\S+\) \{.*?^  \}"
                             r"(?: /\* end lu_table_template \*/)?\n",
                             merged, re.S | re.M):
            last = m
        assert last, "target has no lu_table_template to anchor on"
        merged = merged[:last.end()] + new_tmpl + merged[last.end():]

    for name, body in sorted(src_cells.items()):
        if name in areas:
            body = re.sub(r"(cell \(\S+\) \{\n)(?:    area : [0-9.]+ ;\n)?",
                          rf"\g<1>    area : {areas[name]} ;\n", body,
                          count=1)
        if re.search(rf"^  cell \({re.escape(name)}\) \{{", merged, re.M):
            merged = re.sub(
                rf"^  cell \({re.escape(name)}\) \{{.*?^  \}}"
                rf"(?: /\* end cell \*/)?\n",
                body.replace("\\", "\\\\"), merged, count=1,
                flags=re.S | re.M)
            replaced += 1
        else:
            # insert before the closing brace of the library group
            i = merged.rfind("\n}")
            merged = merged[:i] + "\n" + body + merged[i:]
            added += 1

    pathlib.Path(target_path).write_text(merged, errors="surrogateescape")
    print(f"merged {added} new cells, replaced {replaced}, "
          f"{len(src_tmpl) - len(set(src_tmpl) & set(tgt_tmpl))} new "
          f"templates -> {target_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
