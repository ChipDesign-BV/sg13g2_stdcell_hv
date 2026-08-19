#!/usr/bin/env python3
"""The process/voltage/temperature corners this library is characterized at.

One definition, imported by every script that measures anything, so a
corner cannot drift between the CharLib run and the half-dozen bespoke
measurements (tri-state enable arcs, clock gates, bus holder, tie cells,
physical-cell stubs) that CharLib cannot do. Each of those scripts used
to hardcode `mos_tt` and 3.3 V independently; that is exactly the kind of
duplication that ships a "fast" corner containing typical leakage.

Voltages follow the PDK's own 3.3 V domain rather than a strict +-10 %:
sg13g2_io ships its 3.3 V corners at 3.6 V and 3.0 V, and a stdcell
library that disagreed with the pad ring it sits next to would be a trap.
(The thin-oxide 1.2 V library does use +-10 %: 1.32 / 1.08.)

The slew and load grids are deliberately NOT corner-dependent: the tables
must span the same electrical territory at every corner or an STA tool
cannot interpolate across them.
"""
import collections

Corner = collections.namedtuple(
    "Corner", "name models voltage temperature process")

CORNERS = {
    # name    ngspice .lib section   VDD    T degC   liberty nom_process
    "typ":  Corner("typ",  "mos_tt", 3.30,   25.0, 1.00),
    "fast": Corner("fast", "mos_ff", 3.60,  -40.0, 1.00),
    "slow": Corner("slow", "mos_ss", 3.00,  125.0, 1.00),
}

DEFAULT = "typ"
MODELS_HV = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOShv.lib"
MODELS_DIO = "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerDIO.lib"


def volt_tag(v):
    """3.3 -> '3p30', 3.6 -> '3p60' -- the PDK's filename convention."""
    return f"{v:.2f}".replace(".", "p")


def temp_tag(t):
    """25 -> '25', -40 -> 'm40' -- negative temperatures take an 'm'."""
    i = int(round(t))
    return f"m{abs(i)}" if i < 0 else f"{i}"


def lib_name(corner):
    c = CORNERS[corner] if isinstance(corner, str) else corner
    return (f"sg13g2_stdcell_hv_{c.name}_"
            f"{volt_tag(c.voltage)}V_{temp_tag(c.temperature)}C")


def lib_path(corner, root=None):
    import pathlib
    root = pathlib.Path(root) if root else \
        pathlib.Path(__file__).resolve().parent.parent / "lib"
    return root / f"{lib_name(corner)}.lib"


def spice_header(corner, include=None, diodes=False):
    """The deck preamble every measurement script needs: the MOS models at
    this corner's process section, optionally the cell netlist and the
    diode models (only antennanp needs those), and the temperature.

    Temperature is set with .option temp -- it is part of the corner, and
    a script that sets the model section but forgets the temperature
    produces a fast-process library at 25 C, which looks plausible and is
    wrong.
    """
    c = CORNERS[corner] if isinstance(corner, str) else corner
    lines = [f".lib {MODELS_HV} {c.models}"]
    if diodes:
        lines.append(f".include {MODELS_DIO}")
    if include:
        lines.append(f".include {include}")
    lines.append(f".option temp={c.temperature:g}")
    return lines


def add_argument(parser):
    parser.add_argument("--corner", default=DEFAULT, choices=sorted(CORNERS),
                        help="PVT corner to measure (default: %(default)s)")
    return parser


if __name__ == "__main__":
    for k in ("typ", "fast", "slow"):
        c = CORNERS[k]
        print(f"{k:5s} {c.models:7s} {c.voltage:.2f} V  {c.temperature:+6.1f} C"
              f"   {lib_name(k)}.lib")
