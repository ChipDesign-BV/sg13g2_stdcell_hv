#!/bin/sh
# Characterize one PVT corner end to end.
#
# The order below is not arbitrary and is the reason this script exists:
#
#   * CharLib runs first and produces only what it can express. The
#     sequential cells need the project's own procedures, so they are a
#     second CharLib invocation filtered to the flops and latches, merged
#     into the same file.
#   * The cells CharLib cannot model at all -- tri-states (no Hi-Z in its
#     schema), the statetable clock gates, the bus holder (no output pin),
#     the tie cells -- are measured directly and merged next.
#   * finalize_lib runs LAST of the content steps, because it derives
#     max_capacitance / max_transition from the table axes of whatever is
#     present. Run it before the merges and the tri-states and clock gates
#     ship without drive limits -- which is exactly the gap that crashed
#     OpenROAD's CTS on the first revision of this library.
#   * update_lib_area then replaces every area with the drawn LEF footprint,
#     and verify_lib gates the result as data.
#
# Usage:  ./run_corner.sh <typ|fast|slow> [first_stage]
#         first_stage lets a failed run resume: config, charlib, seq, direct,
#         finalize, verify
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
CORNER=${1:?usage: run_corner.sh <typ|fast|slow> [first_stage]}
FROM=${2:-config}

LIBNAME=$(python3 -c "import sys; sys.path.insert(0,'$HERE'); import corners; print(corners.lib_name('$CORNER'))")
LIB="$HERE/../lib/${LIBNAME}.lib"
SEQ_FILTER='sg13g2_hv_(sdf|dfr|dlh|dll)'

stage() {   # stage <name> -- true if this stage should run
    case "$FROM" in
        config)   return 0 ;;
        charlib)  [ "$1" != config ] ;;
        seq)      [ "$1" != config ] && [ "$1" != charlib ] ;;
        direct)   [ "$1" = direct ] || [ "$1" = finalize ] || [ "$1" = verify ] ;;
        finalize) [ "$1" = finalize ] || [ "$1" = verify ] ;;
        verify)   [ "$1" = verify ] ;;
        *) echo "unknown stage '$FROM'" >&2; exit 1 ;;
    esac
}

echo "=== corner $CORNER -> $LIBNAME.lib (from stage: $FROM) ==="

if stage config; then
    echo "--- [1/6] configuration ---"
    python3 "$HERE/gen_charlib_config.py" --corner "$CORNER"
fi

if stage charlib; then
    echo "--- [2/6] CharLib: combinational + everything it can express ---"
    "$HERE/run_charlib.sh" "$CORNER"
fi

if stage seq; then
    echo "--- [3/6] CharLib: sequential cells via the project procedures ---"
    JOBS=${CHARLIB_JOBS:-$(( $(nproc 2>/dev/null || echo 4) - 2 ))}
    [ "$JOBS" -lt 1 ] && JOBS=1
    mkdir -p "$HERE/charrun"
    cp -f "$HERE/.spiceinit" "$HERE/charrun/.spiceinit"
    ( cd "$HERE/charrun" && env -u PYTHONPATH \
        PATH="$HERE/ngspice-osdi-shim:/foss/tools/bin:$PATH" \
        PDK_ROOT="${PDK_ROOT:-/foss/pdks}" PDK="${PDK:-ihp-sg13g2}" \
        /foss/tools/charlib/bin/python "$HERE/charlib_patched.py" run \
          "$HERE/charlib_${LIBNAME}.yml" -f "$SEQ_FILTER" \
          -o "$HERE/seq_${CORNER}.lib" -j "$JOBS" )
    python3 "$HERE/merge_lib.py" "$LIB" "$HERE/seq_${CORNER}.lib"
fi

if stage direct; then
    echo "--- [4/6] cells CharLib cannot model: measured directly ---"
    python3 "$HERE/seq_leakage.py"  --corner "$CORNER"
    python3 "$HERE/tie_leakage.py"  --corner "$CORNER"
    python3 "$HERE/char_sighold.py" --corner "$CORNER"
    python3 "$HERE/char_tristate/char_tristate.py" --corner "$CORNER"
    python3 "$HERE/merge_lib.py" "$LIB" "$HERE/char_tristate/tristate_${CORNER}.lib"
    python3 "$HERE/char_clockgate/char_clockgate.py" --corner "$CORNER" all
    python3 "$HERE/merge_lib.py" "$LIB" "$HERE/char_clockgate/clockgate_${CORNER}.lib"
fi

if stage finalize; then
    echo "--- [5/6] drive limits, physical stubs, areas ---"
    python3 "$HERE/finalize_lib.py" --corner "$CORNER"
    python3 "$HERE/update_lib_area.py"
fi

if stage verify; then
    echo "--- [6/6] gate ---"
    python3 "$HERE/verify_lib.py" --corner "$CORNER"
fi

echo "=== corner $CORNER done: $LIB ==="
