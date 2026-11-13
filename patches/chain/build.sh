#!/bin/bash
# Rebuild payload.json (bar chain: A/B + pad paints a bar, A+B + pad sets the length)
# and payload_probe.json (hardware probe, probe.c: display only).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
SYMS="chain_var chain_wrap chain_pad chain_pad_c chain_pos chain_wrapping"
build() {   # $1 = output suffix, $2 = source
    local sfx=$1 src=$2
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
          -c $src -o chain$sfx.o
    ld.lld -T link.ld --gc-sections -e chain_var $(printf -- '-u %s ' $SYMS) chain$sfx.o -o chain$sfx.elf
    python3 -I ../../tools/elf2payload.py chain$sfx.elf $SYMS > payload$sfx.json
}
build "" chain.c
build _probe probe.c
llvm-objdump -d --triple=thumbv7m chain.elf > chain.lst
rm -f chain*.o
echo "payload.json, payload_probe.json updated"
