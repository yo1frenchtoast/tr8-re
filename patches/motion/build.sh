#!/bin/bash
# Rebuild payload.json from motion.c. Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Os -ffreestanding -fno-builtin \
      -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -c motion.c -o motion.o
ld.lld -T link.ld --gc-sections -e motion_knob -u motion_step motion.o -o motion.elf
python3 -I ../../tools/elf2payload.py motion.elf motion_knob motion_step > payload.json
llvm-objdump -d --triple=thumbv7m motion.elf > motion.lst
echo "payload.json updated"
