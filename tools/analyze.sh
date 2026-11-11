#!/bin/bash
# Run Ghidra headless on an extracted module ELF and dump all decompiled C and strings.
#
#   GHIDRA_HOME=/path/to/ghidra tools/analyze.sh work/appA.elf analysis/appA
#
# Output: analysis/appA.c (every function, "//==== FUN_<addr> @ <addr>" separators) and
# analysis/appA.strings (address, string, references). About a minute for the application.
# GHIDRA_HOME is the Ghidra install directory (the one that contains support/analyzeHeadless).
set -euo pipefail
[ $# -eq 2 ] || { sed -n '2,9p' "$0"; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HEADLESS=${GHIDRA_HOME:+$GHIDRA_HOME/support/analyzeHeadless}
HEADLESS=${HEADLESS:-$(command -v analyzeHeadless || true)}
[ -x "$HEADLESS" ] || { echo "set GHIDRA_HOME to your Ghidra install directory" >&2; exit 1; }
mkdir -p "$ROOT/work/gproj" "$(dirname "$2")"
"$HEADLESS" "$ROOT/work/gproj" tr8 -import "$1" \
  -processor ARM:LE:32:Cortex -scriptPath "$ROOT/tools" \
  -preScript Aggr.java -postScript DumpAll.java "$2" -overwrite > "$ROOT/work/ghidra.log" 2>&1
echo "Output: $2.c $2.strings (log: work/ghidra.log)"
