#!/bin/bash
# Run Ghidra headless on an extracted module ELF and dump decompiled C + strings.
# Usage: tools/analyze.sh work/appA.elf analysis/appA
# REA refuses Ghidra 12.2, so analyzeHeadless is used directly.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
GHIDRA_HOME=${GHIDRA_HOME:-/home/linuxbrew/.linuxbrew/opt/ghidra/libexec}
mkdir -p "$ROOT/work/gproj" "$ROOT/analysis"
"$GHIDRA_HOME/support/analyzeHeadless" "$ROOT/work/gproj" tr8 -import "$1" \
  -processor ARM:LE:32:Cortex -scriptPath "$ROOT/tools" \
  -preScript Aggr.java -postScript DumpAll.java "$2" -overwrite > "$ROOT/work/ghidra.log" 2>&1
echo "Output: $2.c $2.strings"
