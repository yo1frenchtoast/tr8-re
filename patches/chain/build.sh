#!/bin/bash
# Rebuild payload.json (bar chain: A/B + pad paints a bar, A+B + pad sets the length)
# and payload_probe.json (hardware probe, probe.c: display only).
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
SYMS="chain_var chain_wrap chain_press chain_release chain_commit chain_led4 chain_pos chain_wrapping chain_swallow"
# The probe keeps the LAST STEP fallback (chain_pad) to show what that branch sees.
SYMS_PROBE="$SYMS chain_pad chain_pad_c"

# ld.lld if it is on PATH, else the copy that ships with a Rust toolchain (rust-lld -flavor gnu).
LD=""
for c in ld.lld ld64.lld; do command -v $c >/dev/null && LD=$c && break; done
if [ -z "$LD" ]; then
    LLD=$(ls "$HOME"/.rustup/toolchains/*/lib/rustlib/*/bin/rust-lld 2>/dev/null | head -1)
    [ -n "$LLD" ] && LD="$LLD -flavor gnu"
fi
if [ -z "$LD" ]; then echo "need ld.lld (LLVM) or a Rust toolchain" >&2; exit 1; fi

build() {   # $1 = output suffix, $2 = source, $3 = symbols to keep and export
    local sfx=$1 src=$2 syms=$3
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
          -c $src -o chain$sfx.o
    $LD -T link.ld --gc-sections -e chain_var $(printf -- '-u %s ' $syms) chain$sfx.o -o chain$sfx.elf
    python3 -I ../../tools/elf2payload.py chain$sfx.elf $syms > payload$sfx.json
}
build "" chain.c "$SYMS"
build _probe probe.c "$SYMS_PROBE"
OBJDUMP=$(command -v llvm-objdump || echo /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/llvm-objdump)
[ -x "$OBJDUMP" ] && $OBJDUMP -d --triple=thumbv7m chain.elf > chain.lst
rm -f chain*.o
echo "payload.json, payload_probe.json updated"
