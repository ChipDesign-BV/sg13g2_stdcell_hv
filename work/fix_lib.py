#!/usr/bin/env python3
"""Fix up a Liberty file emitted by CharLib so real tools will read it.

CharLib writes the pin function attribute as the whole string from its config,
including the left-hand side:

    function : "Y = !(A)" ;

Liberty's `function` attribute is the expression alone -- the pin it belongs
to is already the enclosing pin group -- so the `Y = ` prefix makes the
attribute invalid and readers reject or mis-parse the cell. Strip it.

Also fixes two header attributes CharLib gets wrong, both of which OpenSTA
warns about:

    pulling_resistance_unit : "1uA"    -- that is a current unit, not a
                                          resistance; should be "1ohm"
    bus_naming_style : "%s-%d"         -- not a format OpenSTA accepts;
                                          the conventional value is "%s[%d]"

And normalises the supply pin names to VDD/VSS. The CharLib config has to name
them in lower case to work around a branch-lookup bug (see
charlib_patched.py); CharLib happens to upper-case pg_pin groups already, but
this makes it independent of that behaviour.

Usage:  fix_lib.py <file.lib> [more.lib ...]
"""
import re, sys, pathlib

FUNC = re.compile(r'(function\s*:\s*")\s*[A-Za-z_]\w*\s*=\s*(.*?)(")')


def fix(path):
    p = pathlib.Path(path)
    text = p.read_text()

    text, n_func = FUNC.subn(lambda m: m.group(1) + m.group(2).strip() + m.group(3),
                             text)

    text, n_res = re.subn(r'(pulling_resistance_unit\s*:\s*")[^"]*(")',
                          r'\g<1>1ohm\g<2>', text)
    text, n_bus = re.subn(r'(bus_naming_style\s*:\s*")[^"]*(")',
                          r'\g<1>%s[%d]\g<2>', text)

    # CharLib takes its logic thresholds as fractions (low 0.2, high 0.8,
    # rising/falling 0.5) and writes those same numbers into the Liberty
    # header -- but *_threshold_pct_* is a percentage, so 20/80/50 becomes
    # 0.2/0.8/0.5 and every reader thinks the transition was measured over a
    # 0.6% window instead of 60%. The measurements themselves are fine; only
    # the header is wrong. OpenROAD's resizer is where it surfaces:
    # "[RSZ-0101] RC slew modeling shape factor is out of range".
    def to_pct(m):
        v = float(m.group(2))
        return m.group(1) + (f"{v * 100:g}" if v <= 1.0 else m.group(2))

    text, n_pct = re.subn(
        r'((?:slew_(?:lower|upper)|input|output)_threshold_pct_(?:rise|fall)\s*:\s*)'
        r'([\d.]+)', to_pct, text)

    # explicit, matching the thin-oxide reference library
    n_der = 0
    if "slew_derate_from_library" not in text:
        text, n_der = re.subn(r'(\n\s*)(slew_lower_threshold_pct_rise\s*:)',
                              r'\g<1>slew_derate_from_library : 1 ;\g<1>\g<2>',
                              text, count=1)

    n_pg = 0
    for lo, up in (("vdd", "VDD"), ("vss", "VSS")):
        text, n = re.subn(rf"\b{lo}\b", up, text)
        n_pg += n

    p.write_text(text)
    return n_func, n_pg, n_res + n_bus + n_pct + n_der


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for f in sys.argv[1:]:
        nf, npg, nh = fix(f)
        print(f"{f}: stripped LHS from {nf} function attributes, "
              f"normalised {npg} supply-pin references, "
              f"corrected {nh} header attributes")
