#!/bin/bash
# Rebuild payload.json (per-instrument length, set with LAST STEP + instrument button + pad).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
      -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
      -c poly.c -o poly.o
ld.lld -T link.ld --gc-sections -e poly_trig -u poly_run -u poly_last -u poly_led poly.o -o poly.elf
python3 -I ../../tools/elf2payload.py poly.elf poly_trig poly_run poly_last poly_led poly_pos poly_reset > payload.json
llvm-objdump -d --triple=thumbv7m poly.elf > poly.lst
rm -f poly.o
echo "payload.json updated"
