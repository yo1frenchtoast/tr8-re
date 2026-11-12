#!/bin/bash
# Build every patch variant from an original v1.61 TR8_UPD.BIN and run all emulation tests.
#
#   tests/run_all.sh path/to/TR8_UPD.BIN
#
# Needs: Python 3 with unicorn (pip install -r requirements-dev.txt).
# Output files go to work/ (git-ignored).
set -euo pipefail
[ $# -eq 1 ] || { sed -n '2,7p' "$0"; exit 1; }
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
mkdir -p work
run() {   # patch name, output dir, test script, extra test args
    local name=$1 dir=$2 test=$3; shift 3
    $PY -I tools/tr8patch.py "$IN" "work/TR8_UPD_${name//-/_}.BIN" --patch "$name" > /dev/null
    $PY -I tools/tr8fw.py extract "work/TR8_UPD_${name//-/_}.BIN" "work/$dir" > /dev/null
    printf '%-14s ' "$name"; $PY "tests/$test" "work/$dir/appA.bin" "$@" | tail -1
}
IN=$1
$PY -I tools/tr8patch.py "$IN" --check
run motion       patched       emu_motion.py
run motion-mode  patched_mode  emu_motion.py --mode
run motion-diag  patched_diag  emu_motion.py --diag
run motion-probe patched_probe emu_probe.py
run poly       patched_poly  emu_poly.py
run motion-poly patched_combo emu_combo.py
printf '%-14s ' "  + motion";  $PY tests/emu_motion.py work/patched_combo/appA.bin --payload patches/combo/payload.json | tail -1
printf '%-14s ' "  + poly";    $PY tests/emu_poly.py   work/patched_combo/appA.bin --payload patches/combo/payload.json | tail -1
# Web flasher: same output as tr8patch.py (needs Node 18+; skipped without it)
if command -v node > /dev/null; then
    $PY -I tools/build_site.py > /dev/null
    git diff --quiet site/patches.json 2> /dev/null || echo "note: site/patches.json changed, commit it with the payloads"
    printf '%-14s ' "site"; node tests/site_check.mjs "$IN" work/TR8_UPD_motion.BIN work/TR8_UPD_poly.BIN work/TR8_UPD_motion_poly.BIN | tail -1
fi
