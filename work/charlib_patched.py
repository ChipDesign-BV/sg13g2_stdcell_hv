#!/usr/bin/env python
"""CharLib launcher with a runtime fix for its supply-current lookup.

CharLib 2.1.0's leakage procedure reads the supply current as

    charlib/characterizer/procedures/combinational/leakage_power.py:87
        i_vdd = float(analysis.branches[settings.primary_power.name.lower()][0])

with the comment "ngspice names it <element_name>#branch, simplified to
<element_name> (lower)". That assumption does not hold with PySpice 1.6:
ngspice does return lower-case names, but PySpice's RawFile.fix_case() maps
them back to the circuit's own spelling before building the Analysis, and
PySpice always emits a voltage source with a capital V. So the branch ends up
filed as 'VDD' or 'Vdd', never 'vdd', and every leakage measurement dies with

    KeyError: 'vdd'

No choice of supply name in the CharLib config avoids this -- 'VDD' gives
'VDD' and 'vdd' gives 'Vdd'. It is a CharLib/PySpice version incompatibility,
not a configuration error.

Rather than edit the shared install under /foss/tools/charlib, this launcher
makes Analysis's branch dictionary case-insensitive at import time and then
hands over to CharLib's own CLI. Only that one lookup reads `branches`, so
lower-casing those keys changes nothing else.

Usage: exactly CharLib's, e.g.
    charlib_patched.py run <config.yml> -j 6 -o out.lib [-f filter ...]
"""
import sys

from PySpice.Probe.WaveForm import Analysis

_orig_init = Analysis.__init__


def _init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    # keep the original keys too, so anything expecting exact case still works
    extra = {name.lower(): wf for name, wf in self._branches.items()}
    extra.update(self._branches)
    self._branches = extra


Analysis.__init__ = _init

# Register the clk->Q delay procedure. CharLib 2.1.0's own
# `sequential_worst_case` is an unimplemented stub (returns the liberty
# skeleton unchanged), so sequential cells would get constraint tables but
# no propagation arcs. Importing the module registers the procedure; the
# YAML selects it via settings.simulation.sequential_delay_procedure.
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import seq_delay_procedure  # noqa: F401  (import performs the @register)

if __name__ == '__main__':
    from charlib.cli.main import main
    sys.exit(main())
