#!/bin/sh
# Characterize sg13g2_stdcell_hv with CharLib.
#
# Two environment problems have to be worked around, both specific to this
# machine rather than to the library:
#
#   * PYTHONPATH is set globally and lists the system dist-packages ahead of
#     any virtualenv, so it shadows CharLib's own PySpice 1.6 with the system
#     PySpice 1.5. PySpice 1.5 has no top-level Circuit class, so CharLib dies
#     with "module 'PySpice' has no attribute 'Circuit'". Clearing PYTHONPATH
#     lets the venv resolve its own copy.
#
#   * CharLib spawns ngspice through subprocess without a login shell, so
#     /foss/tools/bin has to be on PATH explicitly or it cannot find it.
#
#   * PySpice drives ngspice in server mode, which does not read .spiceinit,
#     so the PDK's OSDI model loads never happen and every PSP103 device is
#     rejected. ngspice-osdi-shim/ngspice injects them. See that script.
#
#   * CharLib's leakage procedure looks the supply current up under a
#     lower-cased name, which PySpice 1.6 never produces. charlib_patched.py
#     makes the lookup case-insensitive at runtime. See that script.
#
# Usage:  ./run_charlib.sh <corner> [charlib filter regex ...]
#         corner is typ | fast | slow (see corners.py)
#
# The corner picks BOTH the configuration and the output file, derived from
# corners.py rather than passed separately. Taking an output path as an
# argument invited the one mistake that matters here -- running the fast
# configuration into the typ Liberty -- and the result would have looked
# entirely normal.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
CORNER=${1:?usage: run_charlib.sh <corner: typ|fast|slow> [filter ...]}
shift

LIBNAME=$(python3 -c "import sys; sys.path.insert(0, '$HERE'); import corners; print(corners.lib_name('$CORNER'))") || {
    echo "unknown corner '$CORNER' (expected typ, fast or slow)" >&2; exit 1; }
CFG="$HERE/charlib_${LIBNAME}.yml"
OUT="$HERE/../lib/${LIBNAME}.lib"
[ -f "$CFG" ] || { echo "missing $CFG -- run: python3 gen_charlib_config.py --corner $CORNER" >&2; exit 1; }
echo "corner $CORNER -> $(basename "$OUT")"

FILTERS=""
if [ $# -gt 0 ]; then
    FILTERS="-f $*"
fi

# Each ngspice is pinned to one thread by the shim, so one job per core (less
# a couple for the driver) keeps the machine busy without oversubscribing it.
# Left unbounded, CharLib's concurrency times ngspice's own threading buries
# the machine and simulations that take 0.4s alone take minutes.
JOBS=${CHARLIB_JOBS:-$(( $(nproc 2>/dev/null || echo 4) - 2 ))}
[ "$JOBS" -lt 1 ] && JOBS=1

mkdir -p "$HERE/charrun"
cp -f "$HERE/.spiceinit" "$HERE/charrun/.spiceinit"

cd "$HERE/charrun"
env -u PYTHONPATH \
    PATH="$HERE/ngspice-osdi-shim:/foss/tools/bin:$PATH" \
    PDK_ROOT="${PDK_ROOT:-/foss/pdks}" PDK="${PDK:-ihp-sg13g2}" \
    /foss/tools/charlib/bin/python "$HERE/charlib_patched.py" run \
       "$CFG" \
       -j "$JOBS" -o "$OUT" $FILTERS

# CharLib writes the pin function with its left-hand side still attached and
# gets two header units wrong; without this the Liberty does not read cleanly.
[ -f "$OUT" ] && python3 "$HERE/fix_lib.py" "$OUT"
