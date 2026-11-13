#!/usr/bin/env python3
"""Emulate the bar-chain payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_chain.py work/patched_chain/appA.bin

A pattern is four bars; each bar has its own A and B step set. The payload keeps a bar's steps in
a small flash log and makes the bar the working copy (area 4 slot 0) so the stock TR-REC, step
pads and LAST STEP edit it. Tested here:

  - the gesture: A/B + pad 1..4 selects and paints a bar, A+B + pad sets the length, A+B+CLEAR +
    pad turns the chain off, through the press dispatch (the site that runs on the unit, before
    the screen) and, as a fallback, through the LAST STEP branch of FUN_6001961E.
  - the store: one 128-byte log entry per saved bar (magic, sequence, pattern, bar, LAST_A/B,
    scale and the 26 A/B mask rows), appended through the firmware's raw flash primitives
    (simulated here); the pattern save is redirected, so area 4 slot n+1 keeps the pattern's own
    steps; compaction, the ring and the 16-bit sequence wrap keep the newest entry per bar.
  - playback: chain_var fills the player struct 0x6012FA64 from the bar's log entry (or from the
    pattern slot when the bar was never recorded) and applies the bar's A/B side.
  - power cycle: the payload state is cleared, the log is rescanned, and the recorded bars play.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYLOAD = sys.argv[sys.argv.index("--payload") + 1] if "--payload" in sys.argv else "patches/chain/payload.json"
pay = json.load(open(os.path.join(ROOT, PAYLOAD)))
S = pay["symbols"]
REGIONS = {r["section"]: (r["addr"], bytes.fromhex(r["data"])) for r in pay["regions"]}
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
BITS, LEN = 15, 16                    # Ptn2 indices for the chain (ids 0x136, 0x137)

# The flash log (chain.c): 4 blocks of 32 entries, 128 bytes each, top block first.
ENT, EPB, TOP, MAGIC = 128, 32, 0x3DF000, 0x31524256
def ent_off(i):
    return TOP - (i // EPB) * 0x1000 + (i % EPB) * ENT

def crc(e):
    h = 0x811C9DC5
    for i, w in enumerate(e):
        if i != 3:
            h = ((h ^ (w & 0xFFFFFFFF)) * 0x01000193) & 0xFFFFFFFF
    return h

FL = bytearray(b"\xff" * 0x400000)     # simulated raw flash, offsets from 0x03000000

# The chip's block protection, the unit-only failure that the first build hit. FUN_60003E54
# (program) and FUN_60003EDA (erase) are raw commands: while the status register protects the
# array they are silently dropped. Only FUN_600108AA (write status 0, indirect mode) ... 
# FUN_600108BA (memory-mapped mode, write status 0x3C) opens a write window, which is what the
# stock store does around its own erase/program sequence. The log must do the same, so the
# emulated chip refuses a write outside a session exactly like the real one.
# `through_chip` is set for calls made by the payload; the test's own calls edit FL directly.
PROTECT = {"on": True, "refused": 0, "left_open": 0}

def fl_erase(off, through_chip=False):
    if through_chip and PROTECT["on"]:
        PROTECT["refused"] += 1
        return
    FL[off:off + 0x1000] = b"\xff" * 0x1000

def fl_prog(off, n, src, through_chip=False):
    if through_chip and PROTECT["on"]:
        PROTECT["refused"] += 1
        return
    for i, b in enumerate(uc.mem_read(src, n)):
        FL[off + i] &= b               # programming can only clear bits

def fl_read(off, n, dst):              # reads work in either mode
    uc.mem_write(dst, bytes(FL[off:off + n]))

def entry(i):
    o = ent_off(i)
    e = list(struct.unpack_from("<32I", FL, o))
    if e[0] != MAGIC or e[3] != crc(e):
        return None
    return {"pat": (e[1] >> 16) & 0xF, "bar": (e[1] >> 20) & 3, "seq": e[1] & 0xFFFF,
            "last": e[2], "scale": e[30] & 3,
            "rows": [(w & 0xFFFF, w >> 16) for w in e[4:30]]}

def entries():
    return [e for e in (entry(i) for i in range(4 * EPB)) if e]

def bar_entry(pat, bar):
    found = [e for e in entries() if e["pat"] == pat and e["bar"] == bar]
    return max(found, key=lambda e: e["seq"]) if found else None

log = []
held = set()
STUBS = {0x60013168: "held", 0x60015980: "text", 0x6001B8D6: "set_last", 0x6000E152: "apply",
         0x60013B34: "press", 0x60013B56: "release", 0x600095F0: "restart",
         0x6001B736: "ptn_get", 0x6001B280: "f", 0x6001B12E: "setup_get",
         0x6004BCBE: "engine", 0x6004B962: "engine_go", 0x6004FB34: "f", 0x6000066E: "f",
         0x60050F70: "f", 0x60010148: "notify", 0x60053F38: "f", 0x60053B40: "f",
         0x600522E4: "range", 0x600521E8: "f", 0x6000FC78: "commit",
         0x600108AA: "fl_begin", 0x600108BA: "fl_end",
         0x6004BB4C: "led_set",
         0x60003E54: "fl_prog", 0x60003EDA: "fl_erase", 0x60003EA2: "fl_read"}
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
        elif name == "fl_prog":
            fl_prog(r0, r1, r2, through_chip=True)
        elif name == "fl_erase":
            fl_erase(r0, through_chip=True)
        elif name == "fl_begin":
            PROTECT["on"] = False
        elif name == "fl_end":
            PROTECT["on"] = True
        elif name == "led_set":
            sp = uc.reg_read(UC_ARM_REG_SP)
            log.append(("led", r0, r1, r2, uc.reg_read(UC_ARM_REG_R3) & 0xFFFFFFFF,
                        struct.unpack("<I", uc.mem_read(sp, 4))[0]))
        elif name == "fl_read":
            fl_read(r0, r1, r2)
        uc.reg_write(UC_ARM_REG_R0, ret)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)

def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v & 0xFFFFFFFF)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    uc.emu_start(fn | 1, RET, count=400000)
    if not PROTECT["on"]:
        PROTECT["left_open"] += 1      # the payload returned with the chip still writable
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

def r8(a):
    return uc.mem_read(a, 1)[0]

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

SCALE = [8, 4, 6, 3]                  # pattern scale word -> player struct +0x1C
def slot_addr(s):
    return A4 + 4 * C4 * s

def seed_ram():
    """Area 4: slot n+1 is pattern n, slot 0 is the working copy of pattern 0."""
    for s in range(0, 6):
        b = slot_addr(s)
        w32(b + 0, s & 1)                        # VARI
        w32(b + 4, s % 4)                        # scale
        w32(b + 8, 0x10 + s)                     # LAST_A
        w32(b + 12, 0x20 + s)                    # LAST_B
        for i in range(26):
            w32(b + 4 * (4 + 2 * i), 0x4000 + (s << 8) + i)   # A mask
            w32(b + 4 * (5 + 2 * i), 0x5000 + (s << 8) + i)   # B mask
    w32(slot_addr(0) + 4 * 56, 0)                # keep word 56 clear (not part of a slot)
    w32(SETUP + 8, 0)          # Setup[2] = pattern 0
    w32(SETUP + 0x3C, 0)       # Setup[0xF] = 0
    w32(PTN2 + 4 * BITS, 0)    # no chain
    w32(PTN2 + 4 * LEN, 0)
    w32(VARI, 2)               # panel VARIATION A+B
    w32(EFF, 0)

def cold_boot():
    """Power cycle: .data is reloaded, .bss cleared, the flash log stays."""
    a, data = REGIONS[".data"]
    uc.mem_write(a, data)
    a, data = REGIONS[".bss"]
    uc.mem_write(a, b"\0" * len(data))

def slot_rows(slot):
    b = slot_addr(slot)
    return [(r32(b + 4 * (4 + 2 * i)) & 0xFFFF, r32(b + 4 * (5 + 2 * i)) & 0xFFFF)
            for i in range(26)]

def slot_scalars(slot):
    b = slot_addr(slot)
    return (r32(b + 8), r32(b + 12))

def struct_rows():
    return [(r16(PTN + (0x20 + 4 * i if i < 4 else 0x30 + 6 * (i - 4))),
             r16(PTN + (0x22 + 4 * i if i < 4 else 0x32 + 6 * (i - 4)))) for i in range(26)]

def struct_scalars():
    return (r32(PTN + 0x14), r32(PTN + 0x18), r32(PTN + 0x1C))

seed_ram()

# The hook sites point at the payload. chain_pad (the LAST STEP fallback of the step-pad branch)
# is only in the probe build: the real one drops it to make room for the bar row.
SITES = [(0x60009614, "chain_var"), (0x600098CA, "chain_wrap"),
         (0x60013842, "chain_press"), (0x600137D2, "chain_release"),
         (0x60017748, "chain_led4"), (0x6001776C, "chain_led4"),
         (0x60017E18, "chain_led4"), (0x60017E3A, "chain_led4"),
         (0x6001B7F4, "chain_commit")]
if "--probe" in sys.argv:
    SITES.append((0x600199F6, "chain_pad"))
for site, sym in SITES:
    t = bl_target(site)
    expect(f"site 0x{site:08x} branches to {sym}", (t & ~1) == (S[sym] & ~1), True)

# --- the bar row ------------------------------------------------------------------
# Pads are LED ids 0x1D..0x2C. While exactly one of VARIATION A/B is held pads 1-4 are the four
# bars (the selected one in the play triple 1,0,2 = palette 0, the rest 1,9,6 = palette 3) and
# pads 5-16 are off (0,0,2 = palette 0x2D). Everything else, and every pad with neither/both
# buttons held, must reach the LED veneer unchanged. There are two raw and two palette setters;
# all four are exercised, since different screens use different ones.
LED_OBJ = 0x601488D0
PAD = lambda n: 0x1C + n             # pad 1..16 = LED 0x1D..0x2C
PLAY, YELLOW, OFF = (1, 0, 2), (1, 9, 6), (0, 0, 2)
BAR1 = PLAY if "--probe" not in sys.argv else YELLOW   # the probe has no current bar

def led_call(fn, led, *args, **buttons):
    held.clear(); held.update(buttons.get("held", ())); log.clear()
    call(fn, led, *args)
    held.clear()
    return list(log)

def L(led, a, b, c):
    return [("led", LED_OBJ, led, a, b, c)]

# Raw setters: FUN_6001773A(led, a, b, c) and the copy FUN_60017E08(led, a, b), which always
# passes c = 0. Palette setters: FUN_6001774E(led, colour) and its copy FUN_60017E1E.
RAW_SETTERS = ((0x6001773A, (1, 7, 7), 7), (0x60017E08, (1, 7), 0))
PAL_SETTERS = (0x6001774E, 0x60017E1E)

for fn, args, c0 in RAW_SETTERS:
    expect(f"LED raw setter 0x{fn:08x}: A held, bar 1 is the play triple",
           led_call(fn, PAD(1), *args, held=(A,)), L(PAD(1), *BAR1))
    expect(f"LED raw setter 0x{fn:08x}: A held, bars 2-4 are yellow",
           [led_call(fn, PAD(n), *args, held=(A,)) for n in (2, 3, 4)],
           [L(PAD(n), *YELLOW) for n in (2, 3, 4)])
    expect(f"LED raw setter 0x{fn:08x}: A held, pads 5-16 are off",
           [led_call(fn, PAD(n), *args, held=(A,)) for n in (5, 9, 12, 16)],
           [L(PAD(n), *OFF) for n in (5, 9, 12, 16)])
    expect(f"LED raw setter 0x{fn:08x}: B held lights the same row",
           led_call(fn, PAD(3), *args, held=(B,)), L(PAD(3), *YELLOW))
    expect(f"LED raw setter 0x{fn:08x}: nothing held passes through",
           led_call(fn, PAD(1), *args), L(PAD(1), 1, 7, c0))
    expect(f"LED raw setter 0x{fn:08x}: A+B (length gesture) passes through",
           led_call(fn, PAD(1), *args, held=(A, B)), L(PAD(1), 1, 7, c0))
    expect(f"LED raw setter 0x{fn:08x}: non-pad LEDs pass through",
           led_call(fn, 0x2D, *args, held=(A,)), L(0x2D, 1, 7, c0))

for fn in PAL_SETTERS:
    expect(f"LED palette setter 0x{fn:08x}: A held, bar 1 is the play triple",
           led_call(fn, PAD(1), 0x2A, held=(A,)), L(PAD(1), *BAR1))
    expect(f"LED palette setter 0x{fn:08x}: A held, bar 4 is yellow",
           led_call(fn, PAD(4), 0x2A, held=(A,)), L(PAD(4), *YELLOW))
    expect(f"LED palette setter 0x{fn:08x}: A held, pads 5-16 are off",
           [led_call(fn, PAD(n), 0x2A, held=(A,)) for n in (5, 11, 16)],
           [L(PAD(n), *OFF) for n in (5, 11, 16)])
    expect(f"LED palette setter 0x{fn:08x}: nothing held passes the palette colour through",
           led_call(fn, PAD(1), 0x2A), L(PAD(1), 1, 9, 2))
    expect(f"LED palette setter 0x{fn:08x}: A+B passes through",
           led_call(fn, PAD(1), 0x2A, held=(A, B)), L(PAD(1), 1, 9, 2))
    expect(f"LED palette setter 0x{fn:08x}: non-pad LEDs pass through",
           led_call(fn, 0x0F, 0x2A, held=(A,)), L(0x0F, 1, 9, 2))

if "--probe" in sys.argv:
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
    expect("probe: global pad branch, plain pad", texts(pad(3)), [" 3--"])
    expect("probe: global pad branch, A + pad 1", texts(pad(1, A)), [" 1A-"])
    expect("probe: nothing written to the pattern", pget(BITS) + pget(LEN), 0)
    expect("probe: LAST STEP + pad does not set the length", pad(8, LAST), [("text", " 8-L")])
    log.clear()
    expect("probe: the redirect site is a pass-through", call(S["chain_commit"], 0, 4, 1, 0), 0)
    expect("probe: ... which is the firmware commit", log, [("commit", 4, 1)])

    def probe_start(vari, eff):
        log.clear(); w32(VARI, vari); w32(EFF, eff)
        uc.mem_write(S["chain_wrapping"], b"\0")
        call(S["chain_var"], PTN)
        return texts(log)

    expect("probe: start shows VARI 0", probe_start(0, 0), ["St00"])
    expect("probe: start shows VARI 1", probe_start(1, 0), ["St11"])
    expect("probe: start shows VARI 2 (A+B), stock toggle", probe_start(2, 1), ["St20"])
    print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)

def edits(e):
    return [x for x in e if x[0] not in ("notify", "apply", "commit")]

def applied(e):
    return [x for x in e if x[0] == "apply"]

seed_ram()
cold_boot()

# --- the gesture ------------------------------------------------------------------
expect("press: plain pad goes to the firmware", press(3), [("press", 2)])
expect("press: plain pad sets nothing", (pget(LEN), pget(BITS)), (0, 0))
expect("press: pads beyond the four bars go to the firmware", press(9, A), [("press", 8)])
expect("press: LAST STEP + pad keeps the stock path", press(8, LAST), [("press", 7)])
expect("press: LAST STEP + A + pad keeps the stock path", press(2, LAST, A), [("press", 1)])

r = press(1, A)
expect("press: A + pad 1 shows bar 1 A", edits(r), [("text", "  1A")])
expect("press: ... and plays A", applied(r), [("apply", 0)])
expect("press: bar 1 is the pattern itself", slot_rows(0), slot_rows(1))
expect("press: chain is now bar 1", (pget(LEN), pget(BITS)), (1, 0))
expect("press: bar 1 was stored", (bar_entry(0, 0) or {}).get("rows"), slot_rows(1))

r = press(2, B)
expect("press: B + pad 2 shows bar 2 B", edits(r), [("text", "  2B")])
expect("press: ... and plays B", applied(r), [("apply", 1)])
expect("press: the working copy is bar 2 of the pattern", slot_rows(0), slot_rows(1))
expect("press: chain is now two bars, bar 2 on B", (pget(LEN), pget(BITS)), (2, 0b10))
expect("press: the panel variation follows the bar", (r32(VARI), r32(EFF), r32(slot_addr(0))), (1, 1, 1))
if "--probe" not in sys.argv:           # the probe has no current bar
    expect("LED: after A/B + pad 2, pad 2 is the blinking bar",
           led_call(0x6001773A, PAD(2), 1, 7, 7, held=(A,)), L(PAD(2), *PLAY))
    expect("LED: ... and pad 1 is now a plain yellow bar",
           led_call(0x6001773A, PAD(1), 1, 7, 7, held=(A,)), L(PAD(1), *YELLOW))

# TR-REC records into the working copy; the firmware's pattern save is redirected to the log.
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x7777)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x8888)
w32(slot_addr(0) + 4, 2)                        # SCALE
w32(slot_addr(0) + 8, 0x0C)                     # LAST_A
w32(slot_addr(0) + 12, 0x0D)                    # LAST_B
before = slot_rows(1)
log.clear()
call(S["chain_commit"], 0, 4, 1, 0)
expect("save: the pattern save wrote no pattern slot", log, [])
expect("save: ... it appended the bar to the log", (bar_entry(0, 1) or {}).get("rows"),
       [(0x7777 if i == 5 else 0x4000 + (1 << 8) + i,
         0x8888 if i == 5 else 0x5000 + (1 << 8) + i) for i in range(26)])
expect("save: ... with its last steps", (bar_entry(0, 1) or {}).get("last"), 0x0C | (0x0D << 8))
expect("save: ... and its scale", (bar_entry(0, 1) or {}).get("scale"), 2)
expect("save: area 4 slot 1 still holds the pattern's own steps", slot_rows(1), before)

# Selecting another bar and coming back restores the recorded content. Leaving bar 2 saves it
# again (the working copy is what it is), so the entry must stay the one just edited.
expect("press: bar 4", edits(press(4, A)), [("text", "  4A")])
expect("press: bar 4 is the untouched pattern", slot_rows(0), slot_rows(1))
expect("press: chain is four bars, 4 on A", (pget(LEN), pget(BITS)), (4, 0b010))
r = press(2, B)
expect("press: back to bar 2 B", edits(r), [("text", "  2B")])
expect("press: ... with the recorded masks", slot_rows(0)[5], (0x7777, 0x8888))
expect("press: ... and its last steps", slot_scalars(0), (0x0C, 0x0D))
expect("press: ... and its scale", r32(slot_addr(0) + 4), 2)
expect("press: ... and the B side selected", (r32(VARI), r32(EFF)), (1, 1))

expect("press: A+B + pad 3 sets the length", edits(press(3, A, B)), [("text", "CH 3")])
expect("press: length 3", pget(LEN), 3)
expect("press: A+B+CLEAR + pad 2 turns it off", edits(press(2, A, B, CLEAR)), [("text", "CH--")])
expect("press: chain off, painted bars kept", (pget(LEN), pget(BITS)), (0, 0b010))
expect("press: A+B+LAST STEP + pad keeps the stock path", press(2, A, B, LAST), [("press", 1)])

# A swallowed press must swallow its release, or the screen sees a release without a press.
expect("press: A + pad 3 is taken", edits(press(3, A)), [("text", "  3A")])
expect("press: its release is swallowed", release(3), [])
expect("press: other pads still release normally", release(6), [("release", 5)])
expect("press: the same pad releases normally afterwards", release(3), [("release", 2)])

# --- playback ---------------------------------------------------------------------
def start(**kw):
    w32(VARI, kw.get("vari", 2))
    w32(EFF, kw.get("eff", 0))
    log.clear()
    uc.mem_write(S["chain_wrapping"], b"\0")
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

seed_ram()
w32(SETUP + 8, 0)
set_chain(0b0100, 4)          # bars 1,2,4 = A, bar 3 = B
expect("chain A A B A: start on bar 1 (A)", start(), 0)
expect("bar 1 is the pattern slot", (struct_rows(), struct_scalars()),
       (slot_rows(1), (0x11, 0x21, SCALE[1])))
expect("bar 1 masks applied with A", log[-1], ("apply", 0))
expect("bar 2: A", wrap(), 0)
expect("bar 2 is the recorded bar 2", (struct_rows(), struct_scalars()),
       ([(0x7777 if i == 5 else 0x4000 + (1 << 8) + i,
          0x8888 if i == 5 else 0x5000 + (1 << 8) + i) for i in range(26)], (0x0C, 0x0D, SCALE[2])))
expect("bar 3: B", wrap(), 1)
expect("bar 3 is the untouched pattern, B side", (struct_rows(), struct_scalars()),
       (slot_rows(1), (0x11, 0x21, SCALE[1])))
expect("bar 4: A", wrap(), 0)
expect("wrap: back to bar 1", wrap(), 0)

# Panel selects A or B: the chain is bypassed, that side of the working copy loops.
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

# --- another pattern: its own bars, its own chain ---------------------------------
# Pattern 2 (area 4 slot 3) gets a recorded bar 1 and a chain of two bars.
seed_ram()
w32(SETUP + 8, 2)
w32(SETUP + 0x3C, 2)
expect("pattern 2: A + pad 1 selects its bar 1", edits(press(1, A)), [("text", "  1A")])
expect("pattern 2: the working copy is pattern 2", slot_rows(0), slot_rows(3))
w32(slot_addr(0) + 4 * (4 + 2 * 2), 0x6A6A)
call(S["chain_commit"], 0, 4, 3, 0)
expect("pattern 2: its bar was stored on its own", (bar_entry(2, 0) or {}).get("rows")[2][0], 0x6A6A)
expect("pattern 2: pattern 0's bars are untouched", (bar_entry(0, 0) or {}).get("rows")[2][0],
       0x4000 + (1 << 8) + 2)
set_chain(0b10, 2)          # bar 1 = A, bar 2 = B
w32(SETUP + 8, 2)
expect("pattern 2 chain: bar 1 A", (start(), struct_rows()[2]),
       (0, (0x6A6A, 0x5000 + (3 << 8) + 2)))
expect("pattern 2 chain: bar 2 B", wrap(), 1)
expect("pattern 2 chain: bar 2 is untouched", struct_rows(), slot_rows(3))

# --- power cycle ------------------------------------------------------------------
seed_ram()
cold_boot()
w32(SETUP + 8, 0)
w32(SETUP + 0x3C, 0)
set_chain(0b0100, 4)
expect("power cycle: the log is rescanned and bar 2 still has the edit",
       (start(), wrap(), struct_rows()[5]),
       (0, 0, (0x7777, 0x8888)))
expect("power cycle: the recorded bar keeps its last steps", struct_scalars()[0:2], (0x0C, 0x0D))
expect("power cycle: bar 1 still the pattern", (wrap(), struct_rows()), (1, slot_rows(1)))

# --- the log does not lose a bar when a block is full -----------------------------
seed_ram()
cold_boot()
w32(SETUP + 8, 0)
press(1, A)                                   # sync: the patch now owns bar 1
for i in range(4 * EPB + 5):                  # force a compaction
    w32(slot_addr(0) + 4 * (4 + 2 * 0), 0x400 + i)
    call(S["chain_commit"], 0, 4, 1, 0)
expect("log: one entry per bar survives compaction", (bar_entry(0, 0) or {}).get("rows")[0][0], 0x400 + 4 * EPB + 4)
expect("log: the entries still fit in four blocks", len(entries()) <= 4 * EPB, True)
expect("log: bar 1 is still readable after compaction",
       (bar_entry(0, 0) or {}).get("seq") is not None, True)

# --- the ring wraps and blocks are compacted: the newest entry per bar wins ---------
# 64 keys x 3 rounds is 192 appends, more than the 128 slots, so the write pointer wraps and
# every block is compacted at least once. Each bar carries a distinct marker.
seed_ram()
cold_boot()
# Before the patch has seen a pad (cold boot), a save of a pattern it has not loaded is the
# stock commit: the working copy is the pattern itself, not a bar.
log.clear()
call(S["chain_commit"], 0, 4, 1, 0)
expect("save: a pattern the patch has not loaded goes through the stock commit", log, [("commit", 4, 1)])

def marker(rnd, p, b):
    return (0x1000 + (rnd << 8) + p * 4 + b) & 0xFFFF

def save_bar(rnd, p, b):
    w32(SETUP + 8, p)
    w32(SETUP + 0x3C, p)
    press(b + 1, A)                       # select and load the bar
    w32(slot_addr(0) + 4 * 4, marker(rnd, p, b))
    w32(slot_addr(0) + 4 * 5, 0x5000 + marker(rnd, p, b))
    log.clear()
    call(S["chain_commit"], 0, 4, p + 1, 0)

for rnd in range(3):
    for p in range(16):
        for b in range(4):
            save_bar(rnd, p, b)
expect("log: all 64 bars have an entry",
       sorted({(e["pat"], e["bar"]) for e in entries()}),
       [(p, b) for p in range(16) for b in range(4)])

cold_boot()
bad = []
for p in range(16):
    for b in range(4):
        w32(SETUP + 8, p)
        w32(SETUP + 0x3C, p)
        press(b + 1, A)                   # loads the bar through the payload's index
        want = (marker(2, p, b), 0x5000 + marker(2, p, b))
        if slot_rows(0)[0] != want:
            bad.append(((p, b), slot_rows(0)[0], want))
expect("log: every bar reads back its newest entry after wrap and compaction", bad, [])
expect("log: the log still fits in its four blocks", len(entries()) <= 4 * EPB, True)
expect("flash: no program or erase was issued while the chip was protected", PROTECT["refused"], 0)
expect("flash: every write session was closed again before returning", PROTECT["left_open"], 0)

# --- the sequence number wraps at 2^16, and a save just after the wrap must be the newest ----
seed_ram()
for blk in range(4):
    fl_erase(0x3DF000 - blk * 0x1000)
fl_erase(0x3DB000)
def put_entry(i, seq, pat, bar, a, b):
    e = [MAGIC, seq | (pat << 16) | (bar << 20), 0, 0] + [a | (b << 16)] + [0] * 27
    e[3] = crc(e)
    FL[ent_off(i):ent_off(i) + ENT] = struct.pack("<32I", *e)
put_entry(0, 0xFFFE, 1, 2, 0x1111, 0x2222)
put_entry(1, 0xFFFF, 1, 2, 0x3333, 0x4444)
cold_boot()
w32(SETUP + 8, 1)
w32(SETUP + 0x3C, 1)
expect("sequence wrap: the newest of two entries is loaded", edits(press(3, A)), [("text", "  3A")])
expect("sequence wrap: ... which is the second one", slot_rows(0)[0], (0x3333, 0x4444))
w32(slot_addr(0) + 4 * 4, 0x7777)
call(S["chain_commit"], 0, 4, 2, 0)
expect("sequence wrap: the next save starts at 0",
       [e["seq"] for e in entries() if e["rows"][0][0] == 0x7777], [1])
cold_boot()
w32(SETUP + 8, 1)
w32(SETUP + 0x3C, 1)
press(3, A)
expect("sequence wrap: after a power cycle the bar written after the wrap still wins",
       slot_rows(0)[0], (0x7777, 0x4444))

# chain_wrap marks the restart as a wrap for the duration of the firmware restart call.
w32(S["chain_wrapping"], 0)
log.clear(); call(S["chain_wrap"], PTN)
expect("wrap: the restart runs with the wrap mark set, then the mark is cleared",
       (log, r8(S["chain_wrapping"])), ([("restart", 1)], 0))

# Model self-check: this is the hardware-only failure the first build hit. With the latch closed
# a program is dropped; inside a session it lands. Without this the test would pass a payload
# that never opens a write session, which is exactly what happened before.
uc.mem_write(0x7000E800, b"\0\0\0\0")
fl_erase(0x3DA000)
PROTECT["on"] = True
fl_prog(0x3DA000, 4, 0x7000E800, through_chip=True)
dropped = FL[0x3DA000:0x3DA004]
PROTECT["on"] = False
fl_prog(0x3DA000, 4, 0x7000E800, through_chip=True)
expect("flash model: a protected chip drops a program, an open session accepts it",
       (dropped, FL[0x3DA000:0x3DA004]), (b"\xff" * 4, b"\0\0\0\0"))

print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
