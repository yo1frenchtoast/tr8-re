#!/bin/bash
# Rebuild payload.json: motion + poly together (patches/motion/motion.c, patches/poly/poly.c, ram.c).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
CC="clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
    -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include"
$CC -c ../motion/motion.c -o motion.o
$CC -c ../poly/poly.c -o poly.o
$CC -c ram.c -o ram.o
SYMS="motion_knob motion_step m_last poly_trig poly_run poly_last poly_led poly_len poly_pos poly_reset ram_init"
ld.lld -T link.ld --gc-sections -e ram_init $(printf -- '-u %s ' $SYMS) motion.o poly.o ram.o -o combo.elf
python3 -I ../../tools/elf2payload.py combo.elf $SYMS > payload.json
llvm-objdump -d --triple=thumbv7m combo.elf > combo.lst
rm -f *.o
echo "payload.json updated"
