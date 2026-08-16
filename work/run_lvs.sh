#!/bin/sh
# LVS the retargeted layouts against the thick-oxide CDL, one cell at a time.
#
# Per cell rather than over the whole GDS: the library has no top level, and a
# per-cell result says which cells pass, not just whether the library does.
#
# klayout is not on the default PATH here, and the PDK runner shells out to it
# by bare name, so it has to be added.
#
# Usage:  ./run_lvs.sh [cell ...]      (default: every cell in the GDS)
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
LIB=$(cd "$HERE/.." && pwd)
GDS="$LIB/gds/sg13g2_stdcell_hv.gds"
CDL="$LIB/cdl/sg13g2_stdcell_hv.cdl"
RUN="$HERE/lvs"
LVSDIR=/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/lvs

mkdir -p "$RUN"

if [ $# -gt 0 ]; then
    CELLS="$*"
else
    CELLS=$(python3 - "$GDS" <<'EOF'
import sys, klayout.db as db
ly = db.Layout(); ly.read(sys.argv[1])
print(" ".join(sorted(ly.cell(c.cell_index()).name for c in ly.each_cell())))
EOF
)
fi

pass=0; fail=0; failed=""
for cell in $CELLS; do
    # The fill cells contain no devices, only rails and taps. KLayout then
    # extracts a circuit without ports (there is no device to anchor a net),
    # while the CDL subckt declares VDD/VSS -- and the comparer reports that
    # port-list difference as a mismatch. IHP's own fill cells fail the same
    # way, so the port check is vacuous for a device-less cell and is relaxed
    # for exactly those four cells. Every cell with devices is compared with
    # the strict flags, where a port mismatch is a real defect.
    case "$cell" in
        *_fill_*) EXTRA="--ignore_top_ports_mismatch" ;;
        *)        EXTRA="" ;;
    esac
    PATH="/foss/tools/klayout:$PATH" python3 "$LVSDIR/run_lvs.py" \
        --layout="$GDS" --netlist="$CDL" --topcell="$cell" \
        --run_dir="$RUN/$cell" --combine_devices $EXTRA \
        > "$RUN/$cell.log" 2>&1 || true
    # The runner exits 0 even when the netlists do not match, so the verdict
    # must come from the log -- otherwise every run is a false pass.
    if grep -q "Netlists match" "$RUN/$cell.log"; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1)); failed="$failed $cell"
    fi
done

echo "LVS: $pass passed, $fail failed"
[ -n "$failed" ] && echo "failed:$failed"
exit 0
