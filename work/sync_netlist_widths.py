#!/usr/bin/env python3
"""Sync the netlist device widths to the drawn layout.

The retarget scales widths by 2.40, but 2.40 x 5 nm = 12 nm, so a scaled width
cannot always land on the 5 nm layout grid. The drawn edges get snapped and the
result sits up to 5 nm away from the computed netlist width -- which LVS
reports as a device parameter mismatch on almost every cell.

Forcing the layout to the computed value is the wrong way round: it means
nudging the Activ edge under a channel, which makes the channel
non-rectangular and the extractor then reports a fractional gate length
(L=0.4508u). The layout has to stay on-grid and rectangular, so the netlist is
brought to it instead. That is also the right direction on principle: the
netlist describes what is drawn.

Only cells that have layout are touched. `as`/`ad`/`ps`/`pd` are recomputed
from the new width with the model deck's own geometry formulas, so they stay
consistent.

Widths are matched between netlist and layout by sorted order within a cell and
device type. The two differ by at most one grid step, so that pairing is
unambiguous.
"""
import re, pathlib, sys
import klayout.db as db
from gen_hv_lib import parasitics, fmt_len, fmt_area, parse_len

HV = pathlib.Path("/foss/designs/sg13g2_stdcell_hv")
GDS = HV / "gds" / "sg13g2_stdcell_hv.gds"
SPICE = HV / "spice" / "sg13g2_stdcell_hv.spice"
CDL = HV / "cdl" / "sg13g2_stdcell_hv.cdl"


def layout_widths():
    """{cell: {'p': [widths sorted], 'n': [...]}} from the drawn channels."""
    ly = db.Layout()
    ly.read(str(GDS))
    la, lg, ln = ly.layer(1, 0), ly.layer(5, 0), ly.layer(31, 0)
    out = {}
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        nw = db.Region(c.shapes(ln)).merged()
        gates = (db.Region(c.shapes(lg)).merged()
                 & db.Region(c.shapes(la)).merged()).merged()
        d = {"p": [], "n": []}
        for poly in gates.each_merged():
            b = poly.bbox()
            k = "p" if not (db.Region(b) & nw).is_empty() else "n"
            # metres: fmt_len() and parasitics() both work in metres, and
            # handing them microns writes w=2400000.000u into the netlist
            # (width, length) in metres. Length is synced too: dlygate4sd2_1
            # staggers an 0.18 um NMOS gate against an 0.25 um PMOS gate at
            # overlapping x, and one monotone 1-D map cannot widen two
            # overlapping intervals by different factors, so its PMOS lands at
            # 0.625 um. Legal, but the netlist has to say so.
            d[k].append((round(b.height() * 1e-9, 12),
                         round(b.width() * 1e-9, 12)))
        d["p"].sort()
        d["n"].sort()
        out[c.name] = d
    return out


DIODE = re.compile(r"^(D\S+\s+.+?\s+(dantenna|dpantenna)\s+)(.*)$", re.I)


def diode_geometry():
    """{cell: {model: (w, l)}} for the antenna diodes, from the layout.

    The y-map stretches the antenna cell too -- it has to, or the cell would
    not be row height -- so its diode area and perimeter change and the
    netlist has to follow. Without this the extracted diode reports
    A=1.2075p / P=4.4u against the thin-oxide netlist's a=1.407p / p=4.78u.
    """
    ly = db.Layout()
    ly.read(str(GDS))
    la, lnw, lb = ly.layer(1, 0), ly.layer(31, 0), ly.layer(189, 4)
    out = {}
    for ci in ly.each_cell():
        c = ly.cell(ci.cell_index())
        bnd = [s.dbbox() for s in c.shapes(lb).each()]
        if not bnd:
            continue
        H = bnd[0].height()
        nw = db.Region(c.shapes(lnw)).merged()
        d = {}
        for s in c.shapes(la).each():
            b = s.dbbox()
            if b.bottom < -1e-9 < b.top or b.bottom < H - 1e-9 < b.top:
                continue                      # rail tap
            inner = db.Region(db.Box(int(b.left * 1000) + 1, int(b.bottom * 1000) + 1,
                                     int(b.right * 1000) - 1, int(b.top * 1000) - 1))
            model = "dpantenna" if not (inner & nw).is_empty() else "dantenna"
            d[model] = (b.width() * 1e-6, b.height() * 1e-6)
        if d:
            out[c.name] = d
    return out


def sync_diodes(path, dg):
    text = path.read_text().splitlines()
    out, cur, n = [], None, 0
    for ln in text:
        s = ln.strip()
        if s.lower().startswith(".subckt"):
            cur = s.split()[1]
        m = DIODE.match(s)
        if m and cur in dg and m.group(2).lower() in dg[cur]:
            w, l = dg[cur][m.group(2).lower()]
            params = m.group(3)
            params = re.sub(r"\bw=\S+", "w=" + fmt_len(w), params)
            params = re.sub(r"\bl=\S+", "l=" + fmt_len(l), params)
            params = re.sub(r"\ba=\S+", "a=" + fmt_area(w * l), params)
            params = re.sub(r"\bp=\S+", "p=" + fmt_area(2 * (w + l)), params)
            out.append(m.group(1) + params)
            n += 1
            continue
        out.append(ln)
    path.write_text("\n".join(out) + "\n")
    return n


DEV_SP = re.compile(r"^(X\S+\s+.+?\s+sg13_hv_([np])mos\s+)(.*)$")
DEV_CDL = re.compile(r"^(M\S+\s+.+?\s+sg13_hv_([np])mos\s+)(.*)$")


def retarget_lines(lines, dev_re, widths, fmt):
    """Rewrite one cell's device lines with the drawn widths.

    Matching is per *finger*, not per device: a folded device draws ng separate
    channels, so buf_4's four netlist devices correspond to six drawn gates.
    Pairing device-to-gate instead mis-assigned the folded PMOS and left the
    netlist claiming 8.06 um where the layout drew 10.74 um.
    """
    fingers = {"p": [], "n": []}
    for i, ln in enumerate(lines):
        m = dev_re.match(ln.strip())
        if m:
            w = parse_len(re.search(r"\bw=(\S+)", m.group(3)).group(1))
            l = parse_len(re.search(r"\bl=(\S+)", m.group(3)).group(1))
            ng = int(re.search(r"\bng=(\S+)", m.group(3)).group(1))
            fingers[m.group(2)].append((w / ng, l, ng, i))

    newidx = {}
    for k, devs in fingers.items():
        devs.sort()                       # by per-finger width
        pool = sorted(widths[k])
        pos = 0
        for wf, _l, ng, i in devs:
            take = pool[pos:pos + ng]
            pos += ng
            if take:
                newidx[i] = take[0]       # fingers of one device are equal

    out = []
    for i, ln in enumerate(lines):
        m = dev_re.match(ln.strip())
        if not m or i not in newidx:
            out.append(ln)
            continue
        params = m.group(3)
        ng = int(re.search(r"\bng=(\S+)", params).group(1))
        wf, gl = newidx[i]
        w = wf * ng
        params = re.sub(r"\bw=\S+", "w=" + fmt_len(w), params)
        params = re.sub(r"\bl=\S+", "l=" + fmt_len(gl), params)
        if "ad=" in params:
            _as, _ad, _ps, _pd = parasitics(w, ng)
            params = re.sub(r"\bas=\S+", "as=" + fmt_area(_as), params)
            params = re.sub(r"\bad=\S+", "ad=" + fmt_area(_ad), params)
            params = re.sub(r"\bps=\S+", "ps=" + fmt_area(_ps), params)
            params = re.sub(r"\bpd=\S+", "pd=" + fmt_area(_pd), params)
        out.append(m.group(1) + params)
    return out


def process(path, dev_re, lw, subckt_kw):
    text = path.read_text().splitlines()
    out, buf, cur = [], None, None
    n = 0
    for ln in text:
        s = ln.strip()
        if s.lower().startswith(subckt_kw):
            cur = s.split()[1]
            buf = []
            out.append(ln)
            continue
        if s.lower().startswith(".ends") and cur is not None:
            if cur in lw:
                buf = retarget_lines(buf, dev_re, lw[cur], fmt_len)
                n += 1
            out.extend(buf)
            out.append(ln)
            cur, buf = None, None
            continue
        (buf if buf is not None else out).append(ln)
    path.write_text("\n".join(out) + "\n")
    return n


if __name__ == "__main__":
    lw = layout_widths()
    a = process(SPICE, DEV_SP, lw, ".subckt")
    b = process(CDL, DEV_CDL, lw, ".subckt")
    dg = diode_geometry()
    da = sync_diodes(SPICE, dg)
    dbn = sync_diodes(CDL, dg)
    print(f"synced {da + dbn} antenna-diode lines to the drawn layout")
    print(f"synced {a} subcircuits in {SPICE.name}, {b} in {CDL.name} "
          f"to the drawn layout ({len(lw)} cells have layout)")
