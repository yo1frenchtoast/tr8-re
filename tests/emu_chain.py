#!/usr/bin/env python3
"""Emulate the bar-chain payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_chain.py work/patched_chain/appA.bin

A bar is a pattern variation, so three things are tested:

  - the gesture: A/B + pad paints a bar of the song, A+B + pad sets its length, through the
    press dispatch (the site that runs on the unit, before the screen) and, as a fallback,
    through the LAST STEP branch of the firmware's own button handler FUN_6001961E. The
    firmware's own Ptn2 setter FUN_6001D432 does the write (parameter context, range check,
    change notification); only the message post and the observer call are stubs.
  - the content: chain_var must fill the player struct 0x6012FA64 from the bar's pattern slot
    (area 4 slot pos+1, or slot 0 when the bar is the current pattern): the 26 A/B mask pairs,
    LAST_A/LAST_B and the scale. FUN_6000E152 (masks -> sound) is stubbed and records the
    variation it was called with.
  - editing: painting a bar saves the pattern being left (FUN_6000FC78 for area 4 and area 6,
    stubbed and logged), copies the bar's pattern (both areas) into the working copy, writes the
    song into the new current pattern and points Setup[2]/Setup[0xF] at it, so TR-REC records
    into that pattern.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# --payload PATH: the probe build (patches/chain/payload_probe.json), see --probe below
PAYLOAD = sys.argv[sys.argv.index("--payload") + 1] if "--payload" in sys.argv else "patches/chain/payload.json"
pay = json.load(open(os.path.join(ROOT, PAYLOAD)))
S = pay["symbols"]
app = open(sys.argv[1], "rb").read()

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)
uc.mem_write(0x60000000, app)
uc.mem_map(0x70000000, 0x10000)
uc.mem_map(0x20000000, 0x10000)                # on-chip RAM: tick counter read by FUN_60010166
RET = 0x7000F000
uc.mem_write(RET, b"\xfe\xe7")

r16 = lambda a: struct.unpack("<H", uc.mem_read(a, 2))[0]
r32 = lambda a: struct.unpack("<I", uc.mem_read(a, 4))[0]
w32 = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

PTN2 = 0x60146930                     # area 6 of the current pattern (bank 0 slot 0)
C6 = 40                               # area 6: 40 ids (0x127..0x14E)
pget = lambda i: r32(PTN2 + 4 * i)
p2base = lambda slot: PTN2 + 4 * C6 * slot
SETUP = 0x60143DBC                    # area 1 slot 0: Setup[n] at SETUP + 4*n
A4, C4 = 0x60144EA0, 56               # area 4 (Ptn), 17 slots; slot 0 = working copy
PTN = 0x6012FA64                      # player struct
VARI, EFF = 0x6012FA70, 0x6012FA74    # panel VARI, effective variation (= TR8_SEQ_VARIATION)
BITS, LEN = 15, 16                    # Ptn2 indices: ids 0x136, 0x137

def r8(a):
    return uc.mem_read(a, 1)[0]

log = []
held = set()
STUBS = {0x60013168: "held", 0x60015980: "text", 0x6001B8D6: "set_last", 0x6000E152: "apply",
         0x60013B34: "press", 0x60013B56: "release", 0x600095F0: "restart",
         0x6001B736: "ptn_get", 0x6001B280: "f", 0x6001B12E: "setup_get",
         0x6004BCBE: "engine", 0x6004B962: "engine_go", 0x6004FB34: "f", 0x6000066E: "f",
         0x60050F70: "f", 0x60010148: "notify", 0x60053F38: "f", 0x60053B40: "f",
         0x600522E4: "range", 0x600521E8: "f", 0x6000FC78: "commit"}
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
        elif name == "press":
            log.append(("press", r0))
        elif name == "release":
            log.append(("release", r0))
        elif name == "restart":
            log.append(("restart", r8(S["chain_wrapping"])))
        elif name == "commit":
            log.append(("commit", r1, r2))          # FUN_6000FC78(_, area, slot, _)
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
    return [e[1] for e in entries if e[0] == "text"]

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

# Pad press through the press dispatch, the site that runs before the screen: the payload
# replaces "bl FUN_60013B34" with chain_press(id) (id in r0, held bit already set by the
# type 5 handler). A press the payload does not take must reach the firmware helper.
def press(n, *buttons):
    held.clear(); held.update(buttons); log.clear()
    call(S["chain_press"], n - 1)
    held.clear()
    return list(log)

def release(n, *buttons):
    held.clear(); held.update(buttons); log.clear()
    call(S["chain_release"], n - 1)
    held.clear()
    return list(log)

# Area 4 slots 1..5 are patterns 0..4 (slot n is pattern n-1); slot 0 is the working copy and
# starts as a copy of pattern 0 with a marker in LAST_A so the tests can tell them apart.
SCALE = [8, 4, 6, 3]                  # pattern scale word -> player struct +0x1C
def seed():
    for s in range(0, 6):
        b = A4 + 4 * C4 * s
        w32(b + 0, s & 1)                       # VARI
        w32(b + 4, s % 4)                       # scale
        w32(b + 8, (0xAA if s == 0 else 0x10 + s))   # LAST_A (slot 0 marker)
        w32(b + 12, 0x20 + s)                   # LAST_B
        for i in range(26):
            w32(b + 4 * (4 + 2 * i), 0x4000 + (s << 8) + i)   # A mask
            w32(b + 4 * (5 + 2 * i), 0x5000 + (s << 8) + i)   # B mask
    w32(SETUP + 8, 0)          # Setup[2] = pattern 0
    w32(SETUP + 0x3C, 0)       # Setup[0xF] = 0
    for s in range(0, 6):                      # area 6 slots: weak accent marker
        w32(p2base(s), 0x60 + s)
    w32(PTN2 + 4 * BITS, 0)    # no chain
    w32(PTN2 + 4 * LEN, 0)
    w32(VARI, 2)               # panel VARIATION A+B
    w32(EFF, 0)

def slot_rows(slot):
    b = A4 + 4 * C4 * slot
    return [(r32(b + 4 * (4 + 2 * i)) & 0xFFFF, r32(b + 4 * (5 + 2 * i)) & 0xFFFF)
            for i in range(26)]

def struct_rows():
    return [(r16(PTN + (0x20 + 4 * i if i < 4 else 0x30 + 6 * (i - 4))),
             r16(PTN + (0x22 + 4 * i if i < 4 else 0x32 + 6 * (i - 4)))) for i in range(26)]

def struct_scalars():
    return (r32(PTN + 0x14), r32(PTN + 0x18), r32(PTN + 0x1C))

seed()

# The hook sites point at the payload
for site, sym in ((0x60009614, "chain_var"), (0x600098CA, "chain_wrap"),
                  (0x60013842, "chain_press"), (0x600137D2, "chain_release"),
                  (0x600199F6, "chain_pad")):
    t = bl_target(site)
    expect(f"site 0x{site:08x} branches to {sym}", (t & ~1) == (S[sym] & ~1), True)

if "--probe" in sys.argv:
    # patches/chain/probe.c: display only, no pattern writes, LAST STEP does not set a length.
    # Press dispatch (the site that runs on the unit).
    expect("probe: plain pad is shown after the firmware handled it", press(3),
           [("press", 2), ("text", " 3--")])
    expect("probe: A + pad 1", press(1, A), [("text", " 1A-")])
    expect("probe: B + pad 12", press(12, B), [("text", "12B-")])
    expect("probe: A+B + pad 3", press(3, A, B), [("text", " 3C-")])
    expect("probe: A+B+LAST STEP + pad 3 goes to the firmware first",
           press(3, A, B, LAST), [("press", 2), ("text", " 3CL")])
    expect("probe: LAST STEP + pad 8 goes to the firmware first",
           press(8, LAST), [("press", 7), ("text", " 8-L")])
    expect("probe: the taken press swallows its release", (press(5, A), release(5)),
           ([("text", " 5A-")], []))
    # The LAST STEP branch inside the firmware button handler still shows what it sees.
    expect("probe: global pad branch, plain pad", texts(pad(3)), [" 3--"])
    expect("probe: global pad branch, A + pad 1", texts(pad(1, A)), [" 1A-"])
    expect("probe: nothing written to the pattern", pget(BITS) + pget(LEN), 0)
    expect("probe: LAST STEP + pad does not set the length", pad(8, LAST), [("text", " 8-L")])

    def probe_start(vari, eff):
        log.clear(); w32(VARI, vari); w32(EFF, eff)
        uc.mem_write(S["chain_wrapping"], b"\0")
        call(S["chain_var"], PTN)
        return texts(log)

    expect("probe: start shows VARI 0", probe_start(0, 0), ["St00"])
    expect("probe: start shows VARI 1", probe_start(1, 0), ["St11"])
    expect("probe: start shows VARI 2 (A+B), stock toggle", probe_start(2, 1), ["St20"])
    print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)

# The gesture on the press dispatch (the path the unit takes; the screen never sees it).
# The firmware Ptn2 setter notifies the observers ("notify"); the variation is applied to the
# sound ("apply"); neither is interesting for the chain bookkeeping here.
def edits(entries):
    return [e for e in entries if e[0] not in ("notify", "apply", "commit")]

def applied(entries):
    return [e for e in entries if e[0] == "apply"]

expect("press: plain pad goes to the firmware, no edit", press(3), [("press", 2)])
expect("press: plain pad sets nothing", (pget(LEN), pget(BITS)), (0, 0))
r = press(1, A)
expect("press: A + pad 1 paints bar 1 A", edits(r), [("text", "  1A")])
expect("press: ... and plays A", applied(r), [("apply", 0)])
expect("press: bar 1 is A, chain 1", (pget(LEN), pget(BITS)), (1, 0))
r = press(4, B)
expect("press: B + pad 4 paints bar 4 B", edits(r), [("text", "  4B")])
expect("press: ... and plays B", applied(r), [("apply", 1)])
expect("press: chain 4 with bar 4 B", (pget(LEN), pget(BITS)), (4, 1 << 3))
expect("press: B + pad 3 paints bar 3 B", edits(press(3, B)), [("text", "  3B")])
expect("press: treating a B bar as A", edits(press(3, A)), [("text", "  3A")])
expect("press: bar 3 back to A", (pget(LEN), pget(BITS)), (4, 1 << 3))
expect("press: A+B + pad 2 sets the length", edits(press(2, A, B)), [("text", "CH 2")])
expect("press: length 2", pget(LEN), 2)
expect("press: A+B+CLEAR + pad 2 turns it off", edits(press(2, A, B, CLEAR)), [("text", "CH--")])
expect("press: chain off, painted bars kept", (pget(LEN), pget(BITS)), (0, 1 << 3))
expect("press: LAST STEP + pad keeps the stock path", press(8, LAST), [("press", 7)])
expect("press: LAST STEP + A + pad keeps the stock path", press(2, LAST, A), [("press", 1)])
expect("press: A+B+LAST STEP + pad keeps the stock path", press(2, A, B, LAST), [("press", 1)])
expect("press: those presses changed no bar", (pget(LEN), pget(BITS)), (0, 1 << 3))
# A swallowed press must swallow its release, or the screen sees a release without a press.
expect("press: A + pad 5 is taken", edits(press(5, A)), [("text", "  5A")])
expect("press: its release is swallowed", release(5), [])
expect("press: other pads still release normally", release(6), [("release", 5)])
expect("press: the same pad releases normally afterwards", release(5), [("release", 4)])

# Editing a bar means editing its pattern: the pattern being left is saved (area 4 and area 6),
# the bar's pattern is copied into the working copy (area 4 and area 6), the song is written into
# the new current pattern, and Setup points at it.
seed()
expect("edit: bar 3 of pattern 0", (texts(press(3, A)), pget(LEN), pget(BITS)), (["  3A"], 3, 0))
expect("edit: the pattern being left is saved (area 4 and area 6)",
       [e for e in log if e[0] == "commit"], [("commit", 4, 1), ("commit", 6, 1)])
expect("edit: the working copy is the bar's pattern", struct_rows(), slot_rows(3))
expect("edit: ... and so is its area 6 (weak accent, flams, own chain)",
       pget(0), 0x63)
expect("edit: ... with its own last steps and scale",
       struct_scalars(), (0x13, 0x23, SCALE[3]))
expect("edit: Setup says the working copy is that pattern",
       (r32(SETUP + 8), r32(SETUP + 0x3C)), (2, 2))
expect("edit: the working variation is written into the pattern and the player",
       (r32(A4), r32(VARI), r32(EFF)), (0, 0, 0))
r = press(2, B)                                  # now on pattern 2 (pad 3): move to pad 2
expect("edit: bar 2 B", edits(r), [("text", "  2B")])
expect("edit: the pattern being left is saved to its own slot",
       [e for e in log if e[0] == "commit"], [("commit", 4, 3), ("commit", 6, 3)])
expect("edit: the working copy is now pattern 1", struct_rows(), slot_rows(2))
expect("edit: Setup follows", (r32(SETUP + 8), r32(SETUP + 0x3C)), (1, 1))
expect("edit: the chain now has bar 2 B and 3 bars", (pget(LEN), pget(BITS)), (3, 0b010))

# Playback: chain_var replaces the variation call inside the pattern restart FUN_600095F0 and
# fills the player struct from the bar's pattern slot (not by switching patterns).
def start(**kw):
    w32(VARI, kw.get("vari", 2))
    w32(EFF, kw.get("eff", 0))
    log.clear()
    uc.mem_write(S["chain_wrapping"], b"\0")            # patched global, see chain.c
    call(S["chain_var"], PTN)
    return r32(EFF)

def wrap():
    uc.mem_write(S["chain_wrapping"], b"\1")
    call(S["chain_var"], PTN)
    uc.mem_write(S["chain_wrapping"], b"\0")
    return r32(EFF)

def set_chain(bits, n):
    w32(PTN2 + 4 * BITS, bits)
    w32(PTN2 + 4 * LEN, n)

seed()
# A A B A: bars 1,2,4 = A, bar 3 = B. The working copy is pattern 0, so bar 1 uses slot 0.
set_chain(0b0100, 4)
expect("chain A A B A: start on bar 1 (A)", start(), 0)
expect("bar 1 content is the working copy (marker)",
       struct_scalars(), (0xAA, 0x20, SCALE[0]))
expect("bar 1 masks", struct_rows(), slot_rows(0))
expect("... applied with the chosen variation", log[-1], ("apply", 0))
expect("bar 2: A", wrap(), 0)
expect("bar 2 is pattern 1 (slot 2): last steps and scale",
       struct_scalars(), (0x12, 0x22, SCALE[2]))
expect("bar 2 masks come from that pattern slot", struct_rows(), slot_rows(2))
expect("bar 3: B", wrap(), 1)
expect("bar 3 is pattern 2 (slot 3) and plays B", (struct_rows(), struct_scalars()),
       (slot_rows(3), (0x13, 0x23, SCALE[3])))
expect("... applied with B", log[-1], ("apply", 1))
expect("bar 4: A", wrap(), 0)
expect("bar 4 is pattern 3 (slot 4)",
       (struct_rows(), struct_scalars()), (slot_rows(4), (0x14, 0x24, SCALE[0])))
expect("wrap: back to bar 1", wrap(), 0)
expect("bar 1 again uses the working copy", struct_rows(), slot_rows(0))
expect("bar 2 again", (wrap(), struct_scalars()), (0, (0x12, 0x22, SCALE[2])))

# The current pattern is not pattern 0 any more: bar 1 must use its own slot (no marker).
w32(SETUP + 8, 2)                      # Setup[2] = pattern 2 (pad 3)
expect("bar 1 of a different current pattern uses that pattern's slot",
       (start(), struct_rows(), struct_scalars()),
       (0, slot_rows(1), (0x11, 0x21, SCALE[1])))
expect("... not the working copy", r32(PTN + 0x14) != 0xAA, True)

# Panel selects A or B: the chain is bypassed, that variation loops.
w32(VARI, 1)
expect("VARIATION B pressed: loops B (FUN_6000E404 as before)", (start(vari=1), r32(EFF)), (1, 1))
w32(VARI, 0)
expect("VARIATION A pressed: loops A", (start(vari=0), r32(EFF)), (0, 0))
w32(VARI, 2)

# No chain: stock behaviour, A+B toggles every pass, no content is loaded.
set_chain(0, 0)
w32(PTN + 0x14, 0x7777)
w32(PTN + 0x20, 0x1234)
w32(EFF, 0)
expect("no chain, A+B: stock toggle to B", (start(), r32(EFF)), (1, 1))
expect("no chain: the player content was left alone",
       (r32(PTN + 0x14), r16(PTN + 0x20)), (0x7777, 0x1234))
expect("no chain, A+B: toggle back to A", (wrap(), r32(EFF)), (0, 0))

# A chain shorter than the stored bits plays only its bars
set_chain(0b1010, 2)      # bars 1..2 = A B, bars 3..4 ignored
w32(SETUP + 8, 0)
expect("2-bar chain A B: bar 1", (start(), r32(EFF)), (0, 0))
expect("2-bar chain A B: bar 2", (wrap(), r32(EFF)), (1, 1))
expect("2-bar chain A B: wraps to bar 1", (wrap(), r32(EFF)), (0, 0))

# chain_wrap marks the restart as a wrap for the duration of the firmware restart call.
w32(S["chain_wrapping"], 0)
log.clear(); call(S["chain_wrap"], PTN)
expect("wrap: the restart runs with the wrap mark set, then the mark is cleared",
       (log, r8(S["chain_wrapping"])), ([("restart", 1)], 0))

print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
