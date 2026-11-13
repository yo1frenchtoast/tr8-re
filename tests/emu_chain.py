#!/usr/bin/env python3
"""Emulate the bar-chain payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_chain.py work/patched_chain/appA.bin

The A/B + pad gesture is tested through the firmware's own button handler FUN_6001961E and the
firmware's own Ptn2 setter FUN_6001D432 (parameter context, range check, write, change
notification); only the message post and the observer call are stubs.
The playback side is tested by calling the payload's chain_var, the function that replaces the
firmware's "bl FUN_6000E404" inside FUN_600095F0: it must set TR8_SEQ_VARIATION (the player's
effective variation) from the chain before the firmware reads the last step. FUN_6000E152
(masks -> sound) is stubbed and records the variation it was called with.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pay = json.load(open(os.path.join(ROOT, "patches/chain/payload.json")))
S = pay["symbols"]
app = open(sys.argv[1], "rb").read()

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)
uc.mem_write(0x60000000, app)
uc.mem_map(0x70000000, 0x10000)
uc.mem_map(0x20000000, 0x10000)                # on-chip RAM: tick counter read by FUN_60010166
RET = 0x7000F000
uc.mem_write(RET, b"\xfe\xe7")

r32 = lambda a: struct.unpack("<I", uc.mem_read(a, 4))[0]
w32 = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

PTN2 = 0x60146930                     # area 6 of the current pattern (bank 0 slot 0)
pget = lambda i: r32(PTN2 + 4 * i)
VARI, EFF = 0x6012FA70, 0x6012FA74    # panel VARI, effective variation (= TR8_SEQ_VARIATION)
OBJ = 0x6012FA64
BITS, LEN = 15, 16                    # Ptn2 indices: ids 0x136, 0x137

log = []
held = set()
STUBS = {0x60013168: "held", 0x60015980: "text", 0x6001B8D6: "set_last", 0x6000E152: "apply",
         0x6001B736: "ptn_get", 0x6001B280: "f", 0x6001B12E: "setup_get",
         0x6004BCBE: "engine", 0x6004B962: "engine_go", 0x6004FB34: "f", 0x6000066E: "f",
         0x60050F70: "f", 0x60010148: "notify", 0x60053F38: "f", 0x60053B40: "f",
         0x600522E4: "range", 0x600521E8: "f"}
def hook(uc, addr, size, _):
    if addr in STUBS:
        name = STUBS[addr]
        r0, r1, r2 = (uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        ret = 0
        if name == "held":
            ret = 1 if r0 in held else 0
        elif name == "setup_get":
            ret = 0xFFFFFFFF if r1 == 3 else 0
        elif name == "ptn_get":
            ret = 15
        elif name == "set_last":
            log.append(("set_last", r1))
        elif name == "apply":
            log.append(("apply", r32(EFF)))
        elif name == "notify":
            log.append(("notify", tuple(uc.mem_read(r1, 2))))
        elif name == "text":
            log.append(("text", bytes(uc.mem_read(r1, 4)).decode()))
        uc.reg_write(UC_ARM_REG_R0, ret)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)

def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v & 0xFFFFFFFF)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    uc.emu_start(fn | 1, RET, count=200000)
    return uc.reg_read(UC_ARM_REG_R0)

def bl_target(a):
    h1, h2 = struct.unpack_from("<HH", app, a - 0x60000000)
    s = (h1 >> 10) & 1
    i1 = 1 - (((h2 >> 13) & 1) ^ s)
    i2 = 1 - (((h2 >> 11) & 1) ^ s)
    imm = ((s << 24) | (i1 << 23) | (i2 << 22)
           | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1))
    if s:
        imm -= 1 << 25
    return (a + 4 + imm) & 0xFFFFFFFF

def texts(entries):
    return [v for k, v in entries if k == "text"]

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))

# Pad press through the firmware button handler FUN_6001961E(ctx, button id 0..15)
A, B, LAST, CLEAR = 0x17, 0x18, 0x1A, 0x1C
def pad(n, *buttons):
    held.clear(); held.update(buttons); log.clear()
    w32(0x6007ECE8 + 0xC, 0)
    call(0x6001961E, 0x70002000, n - 1)
    held.clear()
    return list(log)

# The three hook sites point at the payload
for site, sym in ((0x60009614, "chain_var"), (0x600098CA, "chain_wrap"), (0x600199F6, "chain_pad")):
    t = bl_target(site)
    expect(f"site 0x{site:08x} branches to {sym}", (t & ~1) == (S[sym] & ~1), True)

expect("no chain at boot", (pget(LEN), pget(BITS)), (0, 0))
expect("pad alone: nothing set", texts(pad(4)), [])
expect("A + pad 1: bar 1 is A", texts(pad(1, A)), ["  1A"])
expect("A + pad 3: bar 3 is A", texts(pad(3, A)), ["  3A"])
expect("  ... chain is 3 bars", (pget(LEN), pget(BITS)), (3, 0))
expect("B + pad 2: bar 2 is B", texts(pad(2, B)), ["  2B"])
expect("  ... shown on the display", (pget(LEN), pget(BITS)), (3, 0b010))
expect("A + pad 5 extends the chain to 5 bars", (texts(pad(5, A)), pget(LEN)), (["  5A"], 5))
expect("A + B + pad 8: chain is 8 bars", (texts(pad(8, A, B)), pget(LEN)), (["CH 8"], 8))
expect("A + B + pad 12: two digits", (texts(pad(12, A, B)), pget(LEN)), (["CH12"], 12))
expect("A + B + CLEAR + pad: chain off", (texts(pad(1, A, B, CLEAR)), pget(LEN)), (["CH--"], 0))
expect("... bars kept", pget(BITS), 0b010)
expect("A + pad 16: last bar", (texts(pad(16, A)), pget(LEN)), ([" 16A"], 16))
pad(1, A, B)
expect("A + B + pad 1: back to one bar", (pget(LEN), pget(BITS)), (1, 0b010))
expect("LAST STEP + pad still sets the pattern length", pad(12, LAST), [("set_last", 11)])
expect("A + LAST STEP + pad: LAST STEP wins", pad(7, A, LAST), [("set_last", 6)])
expect("... no bar painted", (pget(LEN), pget(BITS)), (1, 0b010))
expect("other Ptn2 ids untouched (poly's 4..14 included)",
       [pget(i) for i in list(range(15)) + list(range(17, 40))], [0] * 38)

# Playback: chain_var replaces the variation call inside the pattern restart FUN_600095F0
def start(**kw):
    w32(VARI, kw.get("vari", 2))
    w32(EFF, kw.get("eff", 0))
    log.clear()
    uc.mem_write(S["chain_wrapping"], b"\0")            # patched global, see chain.c
    return call(S["chain_var"], OBJ)

def wrap():
    uc.mem_write(S["chain_wrapping"], b"\1")
    r = call(S["chain_var"], OBJ)
    uc.mem_write(S["chain_wrapping"], b"\0")
    return r

def set_chain(bits, n):
    w32(PTN2 + 4 * BITS, bits)
    w32(PTN2 + 4 * LEN, n)

# A A B A: bars 1,2,4 = A, bar 3 = B
set_chain(0b0100, 4)
expect("chain A A B A: start on bar 1 (A)", (start(), r32(EFF)), (0, 0))
expect("... masks applied with the chosen variation", log[-1], ("apply", 0))
expect("bar 2: A", (wrap(), r32(EFF)), (0, 0))
expect("bar 3: B", (wrap(), r32(EFF)), (0, 1))
expect("bar 4: A", (wrap(), r32(EFF)), (0, 0))
expect("wrap: back to bar 1", (wrap(), r32(EFF)), (0, 0))
expect("bar 2 again: A", (wrap(), r32(EFF)), (0, 0))
expect("bar 3 again: B", (wrap(), r32(EFF)), (0, 1))

# Panel selects A or B: the chain is bypassed, that variation loops
w32(VARI, 1)
expect("VARIATION B pressed: loops B (FUN_6000E404 as before)", (call(S["chain_var"], OBJ), r32(EFF)), (0, 1))
w32(VARI, 0)
expect("VARIATION A pressed: loops A", (call(S["chain_var"], OBJ), r32(EFF)), (0, 0))

# No chain: stock behaviour, A+B toggles every pass
set_chain(0, 0)
w32(EFF, 0)
expect("no chain, A+B: stock toggle to B", (start(), r32(EFF)), (0, 1))
expect("no chain, A+B: toggle back to A", (wrap(), r32(EFF)), (0, 0))

# A chain shorter than the stored bits plays only its bars
set_chain(0b1010, 2)      # bars 1..2 = A B, bars 3..4 ignored
expect("2-bar chain A B: bar 1", (start(), r32(EFF)), (0, 0))
expect("2-bar chain A B: bar 2", (wrap(), r32(EFF)), (0, 1))
expect("2-bar chain A B: wraps to bar 1", (wrap(), r32(EFF)), (0, 0))

print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
