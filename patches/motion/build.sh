#!/bin/bash
# Rebuild payload.json (and payload_diag.json, no mode conditions) from motion.c.
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
build() {   # $1 = output suffix, $2.. = extra clang flags
    local sfx=$1; shift
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Os -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra "$@" \
          -c motion.c -o motion$sfx.o
    ld.lld -T link.ld --gc-sections -e motion_knob -u motion_step motion$sfx.o -o motion$sfx.elf
    python3 -I ../../tools/elf2payload.py motion$sfx.elf motion_knob motion_step m_last > payload$sfx.json
}
build ""
build _diag -DMOTION_DIAG
llvm-objdump -d --triple=thumbv7m motion.elf > motion.lst
rm -f motion*.o
echo "payload.json and payload_diag.json updated"
