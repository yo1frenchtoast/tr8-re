#!/bin/bash
# Rebuild the bar chain payloads (chain.c, probe.c) and the payloads of the combined patches.
#
#   payload.json               bar chain alone: code and state in the image (0x60281200)
#   payload_probe.json        hardware probe (probe.c): the old cave build, display only
#   payload_motion.json       chain + motion
#   payload_poly.json         chain + poly
#   payload_motion_poly.json  chain + motion-poly (the prelinked combo payload)
#
# The combined payloads are unions of the parts' payload JSONs (tools/merge_payloads.py). The
# parts are linked separately and do not share address space: the chain lives in the image above
# the bss, the cave patches in the developer-dump cave. Rebuild the parts first if their sources
# changed: ../motion/build.sh, ../poly/build.sh and ../combo/build.sh.
#
# Needs clang + ld.lld (LLVM). The patcher itself does not.
set -euo pipefail
cd "$(dirname "$0")"
SYMS="chain_var chain_wrap chain_view chain_press chain_release chain_commit chain_led4 chain_pos chain_side chain_row chain_wrapping chain_swallow chain_sel chain_jump"
# The probe keeps the LAST STEP fallback (chain_pad) to show what that branch sees.
SYMS_PROBE="chain_var chain_wrap chain_press chain_release chain_commit chain_led4 chain_pos chain_wrapping chain_swallow chain_pad chain_pad_c"

# ld.lld if it is on PATH, else the copy that ships with a Rust toolchain (rust-lld -flavor gnu).
LD=""
for c in ld.lld ld64.lld; do command -v $c >/dev/null && LD=$c && break; done
if [ -z "$LD" ]; then
    LLD=$(ls "$HOME"/.rustup/toolchains/*/lib/rustlib/*/bin/rust-lld 2>/dev/null | head -1)
    [ -n "$LLD" ] && LD="$LLD -flavor gnu"
fi
if [ -z "$LD" ]; then echo "need ld.lld (LLVM) or a Rust toolchain" >&2; exit 1; fi

build() {   # $1 = output suffix, $2 = source, $3 = link script, $4 = symbols to keep and export
    local sfx=$1 src=$2 script=$3 syms=$4
    clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Oz -fno-inline -ffreestanding -fno-builtin \
          -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
          -c $src -o chain$sfx.o
    $LD -T $script --gc-sections -e chain_var $(printf -- '-u %s ' $syms) chain$sfx.o -o chain$sfx.elf
    python3 -I ../../tools/elf2payload.py chain$sfx.elf $syms > payload$sfx.json
}
build "" chain.c link.ld "$SYMS"
build _probe probe.c probe.ld "$SYMS_PROBE"
OBJDUMP=$(command -v llvm-objdump || echo /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/llvm-objdump)
[ -x "$OBJDUMP" ] && $OBJDUMP -d --triple=thumbv7m chain.elf > chain.lst
rm -f chain*.o

for part in motion poly combo; do
    case $part in
        motion) out=payload_motion.json ;;
        poly)   out=payload_poly.json ;;
        combo)  out=payload_motion_poly.json ;;
    esac
    python3 -I ../../tools/merge_payloads.py "$out" payload.json ../$part/payload.json
done
echo "payload.json, payload_probe.json, payload_motion.json, payload_poly.json, payload_motion_poly.json updated"
