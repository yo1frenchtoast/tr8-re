#!/bin/bash
# Rebuild payload.json, payload_diag.json (no mode conditions), payload_mode.json (record in TR-REC mode) and payload_probe.json (hardware probe, probe.c).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
build() {   # $1 = output suffix, $2 = source, $3.. = extra clang flags
    local sfx=$1 src=$2; shift 2
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Os -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include "$@" \
          -c $src -o motion$sfx.o
    ld.lld -T link.ld --gc-sections -e motion_knob -u motion_step motion$sfx.o -o motion$sfx.elf
    python3 -I ../../tools/elf2payload.py motion$sfx.elf motion_knob motion_step m_last > payload$sfx.json
}
build "" motion.c
build _diag motion.c -DMOTION_DIAG
build _mode motion.c -DMOTION_MODE
build _probe probe.c
llvm-objdump -d --triple=thumbv7m motion.elf > motion.lst
rm -f motion*.o
echo "payload.json, payload_diag.json, payload_mode.json, payload_probe.json updated"
