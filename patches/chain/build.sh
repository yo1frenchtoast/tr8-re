#!/bin/bash
# Rebuild payload.json (bar chain: A/B + pad paints a bar, A+B + pad sets the length).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
      -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
      -c chain.c -o chain.o
SYMS="chain_var chain_wrap chain_pad chain_pad_c chain_pos chain_wrapping"
ld.lld -T link.ld --gc-sections -e chain_var $(printf -- '-u %s ' $SYMS) chain.o -o chain.elf
python3 -I ../../tools/elf2payload.py chain.elf $SYMS > payload.json
llvm-objdump -d --triple=thumbv7m chain.elf > chain.lst
rm -f chain.o
echo "payload.json updated"
