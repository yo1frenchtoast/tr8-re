#!/bin/bash
# Rebuild payload.json (bar chain: A/B + pad paints a bar, A+B + pad sets the length)
# and payload_probe.json (hardware probe, probe.c: display only).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
SYMS="chain_var chain_wrap chain_pad chain_pad_c chain_press chain_release chain_pos chain_wrapping chain_swallow"

# ld.lld if it is on PATH, else the copy that ships with a Rust toolchain (rust-lld -flavor gnu).
LD=""
for c in ld.lld ld64.lld; do command -v $c >/dev/null && LD=$c && break; done
if [ -z "$LD" ]; then
    LLD=$(ls "$HOME"/.rustup/toolchains/*/lib/rustlib/*/bin/rust-lld 2>/dev/null | head -1)
    [ -n "$LLD" ] && LD="$LLD -flavor gnu"
fi
if [ -z "$LD" ]; then echo "need ld.lld (LLVM) or a Rust toolchain" >&2; exit 1; fi

build() {   # $1 = output suffix, $2 = source
    local sfx=$1 src=$2
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
          -c $src -o chain$sfx.o
    $LD -T link.ld --gc-sections -e chain_var $(printf -- '-u %s ' $SYMS) chain$sfx.o -o chain$sfx.elf
    python3 -I ../../tools/elf2payload.py chain$sfx.elf $SYMS > payload$sfx.json
}
build "" chain.c
build _probe probe.c
OBJDUMP=$(command -v llvm-objdump || echo /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/llvm-objdump)
[ -x "$OBJDUMP" ] && $OBJDUMP -d --triple=thumbv7m chain.elf > chain.lst
rm -f chain*.o
echo "payload.json, payload_probe.json updated"
