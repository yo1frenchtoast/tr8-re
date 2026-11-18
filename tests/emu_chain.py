#!/usr/bin/env python3
"""Emulate the bar-chain payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_chain.py work/patched_chain/appA.bin

A pattern is up to eight bars; each bar has its own A and B step set. The payload keeps a bar's steps in
a small flash log and makes the bar the working copy (area 4 slot 0) so the stock TR-REC, step
pads and LAST STEP edit it. Tested here:

  - the gesture: A/B + pad 1..8 selects and paints a bar and makes that side at least that many
    bars long, A+B + pad sets both sides to n, A+B+CLEAR + pad resets both, through the press
    dispatch (the site that runs on the unit, before the screen) and, as a fallback, through the
    LAST STEP branch of FUN_6001961E.
  - the store: one 128-byte log entry per saved bar (magic, sequence, pattern, bar, LAST_A/B,
    scale and the 26 A/B mask rows), appended through the firmware's raw flash primitives
    (run on the flash model of tests/periph.py); the pattern save is redirected, so area 4
    slot n+1 keeps the pattern's own steps; compaction, the ring and the 16-bit sequence wrap
    keep the newest entry per bar, and the 128 keys (16 patterns x 8 bars) fit the 160-slot
    log. The bar index and the code live in the application image above the firmware bss, so
    the image grows and the RTOS pool start moves by 64 KB.
  - playback: chain_var fills the player struct 0x6012FA64 from the bar's log entry (or from the
    pattern slot when the bar was never recorded); A plays bars 1..Na with A steps, B plays
    1..Nb with B steps, A+B plays the A sequence then the B one.
  - bar jump: selecting a bar moves the playhead, so the next boundary (playing) or the next start
    (stopped) is that bar, and the sequence carries on from it.
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
RUN = 0x6007E102                      # sequencer running
HMI = 0x60149B8C                      # panel screen object: low halfword is the repaint bits
SETUP_DB = 0x60149F38                 # Setup database handle: writing it corrupts the database
CNT = 17                              # Ptn2 index for the two side lengths (id 0x138)

# The flash log (chain.c): 5 blocks of 32 entries, 128 bytes each, entry i at FL_BASE + i * 128.
# The eighth build kept 4 blocks at 0x3DC000..0x3DFFFF, entry i at 0x3DF000 - (i // 32) * 0x1000
# + (i % 32) * 128: the same bytes in the opposite block order, now entries 32..159, so the same
# flash content stays readable. Compaction uses the block just below the log.
ENT, EPB, NBLK, BASE, MAGIC = 128, 32, 5, 0x3DB000, 0x31524256
NENT, SCR = NBLK * EPB, 0x3DA000
def ent_off(i):
    return BASE + i * ENT

def crc(e):
    h = 0x811C9DC5
    for i, w in enumerate(e):
        if i != 3:
            h = ((h ^ (w & 0xFFFFFFFF)) * 0x01000193) & 0xFFFFFFFF
    return h

# The flash is the register model of tests/periph.py: the payload's flash calls (FUN_60003E54
# program, FUN_60003EDA erase, FUN_60003EA2 read, FUN_600108AA / FUN_600108BA write session) run
# the firmware's own drivers on it. The chip drops a program or an erase while its status register
# protects the array: the third build hit this on the unit (docs/CHAIN.md, History). Only
# FUN_600108AA (write status 0) ... FUN_600108BA (write status 0x3C) opens a write window, which is
# what the stock store does around its own erase/program sequence. The test's own setup edits FL
# (the chip's array) directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from periph import RomApi, SerialFlash, PowerCut
rom = RomApi(uc)
flash = SerialFlash(uc, rom)
flash.protect_all()                    # the state the firmware leaves the chip in
FL = flash.mem                         # offsets from 0x03000000
PROTECT = {"left_open": 0}

def fl_erase(off):
    FL[off:off + 0x1000] = b"\xff" * 0x1000

def refused():
    """Erases and programs the chip dropped because the array was protected."""
    return sum(st == "protected" for *_, st in flash.ops)

# Fault injection for the storage contract (docs/DEVELOPING.md section 7). CUT["after"] = k runs
# k flash operations (erase or program) and then unwinds the payload as if the power went away;
# DROP["after"] = k drops program k of this save (the chip does not take it, so the read-back
# shows the old bytes). flash.cut_at = k cuts the power halfway through operation k instead.
CUT = {"after": None, "hit": False, "ops": 0}
DROP = {"after": None}

def cut_after(n):
    CUT["after"], CUT["hit"], CUT["ops"] = n, False, 0

def drop_next_program():
    DROP["after"] = 0

def drop_program(k):
    DROP["after"] = k

def _after_op(op, addr, n):
    CUT["ops"] += 1
    if CUT["after"] is not None:
        if CUT["after"] == 0:
            CUT["hit"] = True
            raise PowerCut
        CUT["after"] -= 1

def _drop(op, addr, n):
    if op != 0x02 or DROP["after"] is None:
        return False
    if DROP["after"] == 0:
        DROP["after"] = None
        return True
    DROP["after"] -= 1
    return False

def _command(op, addr, n):
    if op == 0x02:
        WRITES["prog"] += 1
    elif op == 0x20:
        WRITES["erase"] += 1

flash.after_op, flash.drop, flash.on_command = _after_op, _drop, _command

def entry(i):
    o = ent_off(i)
    e = list(struct.unpack_from("<32I", FL, o))
    if e[0] != MAGIC or e[3] != crc(e):
        return None
    return {"pat": (e[1] >> 16) & 0xF, "bar": (e[1] >> 20) & 0xF, "seq": e[1] & 0xFFFF,
            "last": e[2], "scale": e[30] & 3,
            "rows": [(w & 0xFFFF, w >> 16) for w in e[4:30]]}

def entries():
    return [e for e in (entry(i) for i in range(NENT)) if e]

def bar_entry(pat, bar):
    found = [e for e in entries() if e["pat"] == pat and e["bar"] == bar]
    return max(found, key=lambda e: e["seq"]) if found else None

log = []
WRITES = {"prog": 0, "erase": 0}        # flash traffic, to check that playback stays quiet
READS = {"n": 0}                        # flash reads, to check that the sequencer has none
held = set()
STUBS = {0x60013168: "held", 0x60015980: "text", 0x6001B8D6: "set_last", 0x6000E152: "apply",
         0x60013B34: "press", 0x60013B56: "release", 0x600095F0: "restart",
         0x6001B736: "ptn_get", 0x6001B280: "f", 0x6001B12E: "setup_get",
         0x6004BCBE: "engine", 0x6004B962: "engine_go", 0x6004FB34: "f", 0x6000066E: "f",
         0x60050F70: "f", 0x60010148: "notify", 0x60053F38: "f", 0x60053B40: "f",
         0x60051E20: "repaint_panel", 0x60016386: "stepview",
         0x600522E4: "range", 0x600521E8: "f", 0x6000FC78: "commit",
         0x6004BB4C: "led_set", 0x600186FA: "hmi_set"}
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
        elif name == "stepview":
            log.append(("stepview", r0))
        elif name == "repaint_panel":
            # FUN_60051E20: the firmware's own "repaint step pads and numeric text" (0x44 on the
            # panel object). The payload must go through this, not write the object by hand.
            log.append(("repaint_panel",))
            uc.mem_write(HMI, struct.pack("<H", r16(HMI) | 0x44))
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
        elif name == "led_set":
            sp = uc.reg_read(UC_ARM_REG_SP)
            log.append(("led", r0, r1, r2, uc.reg_read(UC_ARM_REG_R3) & 0xFFFFFFFF,
                        struct.unpack("<I", uc.mem_read(sp, 4))[0]))
        elif name == "hmi_set":
            # FUN_600186FA(database, index, value, _): the firmware's parameter setter. On the Ptn
            # database (0x6007ED24) index n is word n of the working copy (area 4 slot 0).
            log.append(("hmi_set", r0, r1, r2))
            if r0 == 0x6007ED24:
                w32(A4 + 4 * r1, r2)
        uc.reg_write(UC_ARM_REG_R0, ret)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)
def count_read(uc, addr, size, _):     # FUN_60003EA2 runs; this only counts the calls
    READS["n"] += 1
uc.hook_add(UC_HOOK_CODE, count_read, begin=0x60003EA2, end=0x60003EA2)

def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v & 0xFFFFFFFF)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    closed = flash.sr & flash.BP == flash.BP
    try:
        uc.emu_start(fn | 1, RET, count=2000000)
    except PowerCut:
        flash.power_cycle()            # the status register keeps what it had (non-volatile)
        return uc.reg_read(UC_ARM_REG_R0)
    if closed and flash.sr & flash.BP != flash.BP:
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

def repaint():
    """0x40 in the screen object's bit word: the panel will repaint its own numeric text."""
    return r8(HMI) & 0x40

def clear_repaint():
    uc.mem_write(HMI, bytes([r8(HMI) & 0xBF]))

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))

# Build regression, before anything runs: the repaint request belongs on the panel object
# (0x60149B8C). An earlier build wrote it into the Setup database handle (0x60149F38), which
# corrupted the database and froze the whole unit (see docs/CHAIN.md, hardware fifth build).
CODE = b"".join(bytes.fromhex(r["data"]) for r in pay["regions"]
                if r["section"].startswith(".text"))
expect("build: the payload never references the Setup database object",
       struct.pack("<I", SETUP_DB) in CODE, False)
if "--probe" not in sys.argv:
    expect("build: the repaint request names the panel object",
           struct.pack("<I", HMI) in CODE, True)
    # The code and the 16 patterns x 8 bars index live in the application image itself, above
    # the firmware bss (which the startup code zeroes up to 0x60280987), so the patcher grows the
    # image to cover them and the RTOS pool start (literal 0x600104A8) moves by 64 KB. There is
    # no patch RAM: the payload is written into the image, and the boot zero-fill cannot reach it.
    bss_end, pool = 0x60280987, 0x60290988
    codes = [(r["addr"], r["addr"] + len(r["data"]) // 2) for r in pay["regions"]]
    expect("image: the payload has no patch RAM section", pay.get("ram"), None)
    expect("image: the code and state sit above the firmware bss and below the moved pool",
           (codes[0][0] > bss_end, codes[-1][1] < pool), (True, True))
    expect("image: the RTOS pool start moved from 0x60280988 to 0x60290988",
           r32(0x600104A8), pool)
    expect("image: the patched image covers the payload",
           len(app) >= codes[-1][1] - 0x60000000, True)
    b0, _ = REGIONS[".bss"]
    expect("image: the image itself carries the zeroed bar index",
           set(app[b0 - 0x60000000:b0 - 0x60000000 + len(REGIONS[".bss"][1])]), {0})

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

def sync_panel():
    """The panel task's scan + cache fill. chain_press syncs on every button, pad or not."""
    call(S["chain_press"], 0xFF)       # no pad id: the sequencer guard catches up, no edit
    log.clear()

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
    # The panel copies the pattern into the working copy when it selects it (set_pattern); the
    # VARI word stays the panel's (A here), the tests choose the side.
    uc.mem_write(slot_addr(0) + 4, bytes(uc.mem_read(slot_addr(1) + 4, 4 * C4 - 4)))
    w32(slot_addr(0) + 4 * 56, 0)                # keep word 56 clear (not part of a slot)
    w32(SETUP + 8, 0)          # Setup[2] = pattern 0
    w32(SETUP + 0x3C, 0)       # Setup[0xF] = 0
    uc.mem_write(PTN2, b"\0" * (4 * C6 * 17))   # no side lengths, all pattern slots empty
    w32(VARI, 2)               # panel VARIATION A+B
    w32(EFF, 0)
    w32(RUN, 0)

def set_counts(a, b):
    w32(PTN2 + 4 * CNT, (a & 0xF) | ((b & 0xF) << 4))

def set_pattern(p):
    """Mirror the panel: area 6 slot 0 is the current pattern, slot p+1 the stored one."""
    old = r32(SETUP + 8) & 0xF
    if old != p:
        uc.mem_write(p2base(old + 1), bytes(uc.mem_read(PTN2, 4 * C6)))
        uc.mem_write(PTN2, bytes(uc.mem_read(p2base(p + 1), 4 * C6)))
        uc.mem_write(slot_addr(0), bytes(uc.mem_read(slot_addr(p + 1), 4 * C4)))
    w32(SETUP + 8, p)
    w32(SETUP + 0x3C, p)

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
    SITES.append((0x600199F6, "chain_pad"))     # only the probe has the payload for it
else:
    SITES.append((0x60016C44, "chain_view"))    # only the real build follows the playing bar
for site, sym in SITES:
    t = bl_target(site)
    expect(f"site 0x{site:08x} branches to {sym}", (t & ~1) == (S[sym] & ~1), True)

# --- the bar row ------------------------------------------------------------------
# Pads are LED ids 0x1D..0x2C. While exactly one of VARIATION A/B is held the pads show that
# side's bars: the bars the side has are green (1,9,2) and the bar at that side's head blinks
# yellow (1,0,6; b = 0 is the blink flag), every other pad is off (0,0,2). The head is the bar
# being played on that side, or, stopped, the bar last selected on it. The probe has no side
# lengths: pads 1-4 are all yellow and 5-16 off, which is exactly the hook check it exists for.
LED_OBJ = 0x601488D0
PAD = lambda n: 0x1C + n             # pad 1..16 = LED 0x1D..0x2C
PLAY, BLINK, GREEN, YELLOW, OFF = (1, 0, 2), (1, 0, 6), (1, 9, 2), (1, 9, 6), (0, 0, 2)

def led_call(fn, led, *args, **buttons):
    held.clear(); held.update(buttons.get("held", ())); log.clear()
    call(fn, led, *args)
    held.clear()
    return list(log)

def L(led, a, b, c):
    return [("led", LED_OBJ, led, a, b, c)]

def row(fn, args, buttons):
    return [led_call(fn, PAD(n), *args, held=buttons) for n in (1, 2, 3, 4, 5, 9, 12, 16)]

def want_row(cols, offs=(5, 9, 12, 16)):
    out = [L(PAD(n), *cols[n - 1]) for n in (1, 2, 3, 4)]
    return out + [L(PAD(n), *OFF) for n in offs]

# Raw setters: FUN_6001773A(led, a, b, c) and the copy FUN_60017E08(led, a, b), which always
# passes c = 0. Palette setters: FUN_6001774E(led, colour) and its copy FUN_60017E1E.
RAW_SETTERS = ((0x6001773A, (1, 7, 7), 7), (0x60017E08, (1, 7), 0))
PAL_SETTERS = (0x6001774E, 0x60017E1E)

if "--probe" in sys.argv:
    for fn, args, c0 in RAW_SETTERS:
        expect(f"LED probe raw setter 0x{fn:08x}: A held, pads 1-4 yellow, rest off",
               row(fn, args, (A,)), want_row([YELLOW] * 4))
        expect(f"LED probe raw setter 0x{fn:08x}: B held, same",
               row(fn, args, (B,)), want_row([YELLOW] * 4))
        expect(f"LED probe raw setter 0x{fn:08x}: nothing held passes through",
               led_call(fn, PAD(1), *args), L(PAD(1), 1, 7, c0))
        expect(f"LED probe raw setter 0x{fn:08x}: A+B passes through",
               led_call(fn, PAD(1), *args, held=(A, B)), L(PAD(1), 1, 7, c0))
        expect(f"LED probe raw setter 0x{fn:08x}: non-pad LEDs pass through",
               led_call(fn, 0x2D, *args, held=(A,)), L(0x2D, 1, 7, c0))
    for fn in PAL_SETTERS:
        expect(f"LED probe palette setter 0x{fn:08x}: A held, pads 1-4 yellow, rest off",
               row(fn, (0x2A,), (A,)), want_row([YELLOW] * 4))
        expect(f"LED probe palette setter 0x{fn:08x}: B held, same",
               row(fn, (0x2A,), (B,)), want_row([YELLOW] * 4))
        expect(f"LED probe palette setter 0x{fn:08x}: nothing held passes through",
               led_call(fn, PAD(1), 0x2A), L(PAD(1), *GREEN))
        expect(f"LED probe palette setter 0x{fn:08x}: A+B passes through",
               led_call(fn, PAD(1), 0x2A, held=(A, B)), L(PAD(1), *GREEN))
        expect(f"LED probe palette setter 0x{fn:08x}: non-pad LEDs pass through",
               led_call(fn, 0x0F, 0x2A, held=(A,)), L(0x0F, *GREEN))
else:
    set_counts(3, 2)                    # A = three bars, B = two
    w32(RUN, 0)                         # stopped: each side's head is the bar last selected
    uc.mem_write(S["chain_row"], b"\0\0")
    uc.mem_write(S["chain_sel"], b"\0\0")
    for fn, args, c0 in RAW_SETTERS:
        expect(f"LED raw setter 0x{fn:08x}: A held, three green bars, bar 1 blinks yellow",
               row(fn, args, (A,)), want_row([BLINK, GREEN, GREEN, OFF]))
        expect(f"LED raw setter 0x{fn:08x}: B held shows the B side's two bars",
               row(fn, args, (B,)), want_row([BLINK, GREEN, OFF, OFF]))
        expect(f"LED raw setter 0x{fn:08x}: nothing held passes through",
               led_call(fn, PAD(1), *args), L(PAD(1), 1, 7, c0))
        expect(f"LED raw setter 0x{fn:08x}: A+B passes through",
               led_call(fn, PAD(1), *args, held=(A, B)), L(PAD(1), 1, 7, c0))
        expect(f"LED raw setter 0x{fn:08x}: non-pad LEDs pass through",
               led_call(fn, 0x2D, *args, held=(A,)), L(0x2D, 1, 7, c0))
    for fn in PAL_SETTERS:
        expect(f"LED palette setter 0x{fn:08x}: A held, three green bars, bar 1 blinks yellow",
               row(fn, (0x2A,), (A,)), want_row([BLINK, GREEN, GREEN, OFF]))
        expect(f"LED palette setter 0x{fn:08x}: B held shows the B side's two bars",
               row(fn, (0x2A,), (B,)), want_row([BLINK, GREEN, OFF, OFF]))
        expect(f"LED palette setter 0x{fn:08x}: nothing held passes the palette colour through",
               led_call(fn, PAD(1), 0x2A), L(PAD(1), *GREEN))
        expect(f"LED palette setter 0x{fn:08x}: A+B passes through",
               led_call(fn, PAD(1), 0x2A, held=(A, B)), L(PAD(1), *GREEN))
        expect(f"LED palette setter 0x{fn:08x}: non-pad LEDs pass through",
               led_call(fn, 0x0F, 0x2A, held=(A,)), L(0x0F, *GREEN))

    # Each side has its own head; the row blinks it whatever the panel is doing. Stopped, the
    # head is the bar last selected (chain_sel); running, the bar being played (chain_row).
    uc.mem_write(S["chain_sel"], bytes([2, 1]))     # stopped: A head = bar 3, B head = bar 2
    expect("LED: A head bar 3 -> pad 3 blinks yellow, pads 1-2 green",
           row(0x6001773A, (1, 7, 7), (A,)), want_row([GREEN, GREEN, BLINK, OFF]))
    expect("LED: B head bar 2 -> pad 2 blinks yellow, pad 1 green",
           row(0x6001773A, (1, 7, 7), (B,)), want_row([GREEN, BLINK, OFF, OFF]))
    uc.mem_write(S["chain_row"], bytes([2, 1]))     # running: the sequencer owns the head
    w32(RUN, 1)
    expect("LED: running does not change the head mapping",
           row(0x6001773A, (1, 7, 7), (A,)), want_row([GREEN, GREEN, BLINK, OFF]))
    w32(RUN, 0)
    uc.mem_write(S["chain_row"], b"\0\0")
    uc.mem_write(S["chain_sel"], b"\0\0")

    # Eight bars fill pads 1-8; pad 9 is the first one past the side's last bar.
    set_counts(8, 0)
    uc.mem_write(S["chain_row"], b"\0\0")
    uc.mem_write(S["chain_sel"], b"\0\0")
    expect("LED: eight bars fill pads 1-8, the head bar 1 blinking yellow",
           [led_call(0x6001773A, PAD(n), 1, 7, 7, held=(A,)) for n in range(1, 9)],
           [L(PAD(1), *BLINK)] + [L(PAD(n), *GREEN) for n in range(2, 9)])
    expect("LED: pad 9 is off past the eighth bar",
           led_call(0x6001773A, PAD(9), 1, 7, 7, held=(A,)), L(PAD(9), *OFF))

    # A side never selected: pad 1 steady green (the pattern itself), not the yellow head of a
    # one-bar sequence, which looked the same on the unit (issue #2); B keeps its own two.
    set_counts(0, 2)
    expect("LED: A side unset -> pad 1 steady green, the rest off",
           row(0x6001773A, (1, 7, 7), (A,)), want_row([GREEN, OFF, OFF, OFF]))
    w32(RUN, 1)
    expect("LED: A side unset, running -> the same",
           row(0x6001773A, (1, 7, 7), (A,)), want_row([GREEN, OFF, OFF, OFF]))
    w32(RUN, 0)
    set_counts(1, 2)
    expect("LED: one-bar A sequence -> pad 1 is the yellow head",
           row(0x6001773A, (1, 7, 7), (A,)), want_row([BLINK, OFF, OFF, OFF]))
    set_counts(0, 2)
    expect("LED: B side still two bars",
           row(0x6001773A, (1, 7, 7), (B,)), want_row([BLINK, GREEN, OFF, OFF]))

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
    expect("probe: nothing written to the pattern", pget(CNT), 0)
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

# --- the gesture, with the sequencer stopped: selecting a bar loads it for editing ----------
expect("press: plain pad goes to the firmware", press(3), [("press", 2)])
expect("press: plain pad sets nothing", pget(CNT), 0)
expect("press: pads beyond the four bars go to the firmware", press(9, A), [("press", 8)])
expect("press: LAST STEP + pad keeps the stock path", press(8, LAST), [("press", 7)])
expect("press: LAST STEP + A + pad keeps the stock path", press(2, LAST, A), [("press", 1)])

# A load marks the panel's "repaint the step pads" bit and lets the panel task do the drawing
# on its next pass; the payload does not notify the screens from inside the press dispatch.
uc.mem_write(HMI, b"\0\0")
r = press(1, A)
expect("press: A + pad 1 shows bar 1 A", edits(r), [("text", "  A1")])
expect("press: ... and plays A", applied(r), [("apply", 0)])
expect("press: ... and marks the step pads for the panel to repaint", r8(HMI) & 0x04, 0x04)
expect("press: bar 1 is the pattern itself", slot_rows(0), slot_rows(1))
expect("press: the A side is now one bar", pget(CNT), 0x01)
# Bar 1 is the pattern's own steps and nobody edited them: leaving it costs no flash write.
expect("press: bar 1 needs no entry, it is the pattern itself", bar_entry(0, 0), None)

r = press(2, B)
expect("press: B + pad 2 shows bar 2 B", edits(r), [("text", "  B2")])
expect("press: ... and plays B", applied(r), [("apply", 1)])
expect("press: the working copy is bar 2 of the pattern", slot_rows(0), slot_rows(1))
expect("press: the sides are one and two bars long", pget(CNT), 0x21)
expect("press: the panel variation follows the bar", (r32(VARI), r32(EFF), r32(slot_addr(0))), (1, 1, 1))
if "--probe" not in sys.argv:           # the probe has no current bar
    expect("LED: after A/B + pad 2, holding B blinks pad 2",
           led_call(0x6001773A, PAD(2), 1, 7, 7, held=(B,)), L(PAD(2), *BLINK))
    expect("LED: ... holding A shows its single bar, bar 1 blinking",
           led_call(0x6001773A, PAD(1), 1, 7, 7, held=(A,)), L(PAD(1), *BLINK))
    expect("LED: ... so pad 2 is off on the A row",
           led_call(0x6001773A, PAD(2), 1, 7, 7, held=(A,)), L(PAD(2), *OFF))

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
expect("press: bar 4", edits(press(4, A)), [("text", "  A4")])
expect("press: bar 4 is the untouched pattern", slot_rows(0), slot_rows(1))
expect("press: the A side is now four bars", pget(CNT), 0x24)
r = press(2, B)
expect("press: back to bar 2 B", edits(r), [("text", "  B2")])
expect("press: ... with the recorded masks", slot_rows(0)[5], (0x7777, 0x8888))
expect("press: ... and its last steps", slot_scalars(0), (0x0C, 0x0D))
expect("press: ... and its scale", r32(slot_addr(0) + 4), 2)
expect("press: ... and the B side selected", (r32(VARI), r32(EFF)), (1, 1))

# Stopped, the same on the A side: load a bar, edit it, leave and come back. This is the
# "A + pad loads the bar for editing" flow; nothing here starts the sequencer (RUN stays 0).
expect("stopped: A + pad 3 loads bar 3", edits(press(3, A)), [("text", "  A3")])
w32(slot_addr(0) + 4 * (4 + 2 * 8), 0x0123)     # TR-REC: step 9 of the A side
call(S["chain_commit"], 0, 4, 1, 0)             # the firmware save, redirected to the log
expect("stopped: A + pad 1 loads bar 1", edits(press(1, A)), [("text", "  A1")])
expect("stopped: ... bar 1 is the pattern itself", slot_rows(0), slot_rows(1))
expect("stopped: A + pad 3 loads the edited bar again", edits(press(3, A)), [("text", "  A3")])
expect("stopped: ... with the step edited while stopped", slot_rows(0)[8], (0x0123, 0x5108))

uc.mem_write(HMI, b"\0\0")
r = press(3, A, B)
expect("press: A+B + pad 3 sets both sides to three bars", edits(r), [("text", "AB 3")])
expect("press: ... without reloading the working copy or asking for a repaint", r8(HMI) & 0x04, 0)
expect("press: three bars on both sides", pget(CNT), 0x33)
expect("press: A+B+CLEAR + pad 2 resets both sides", edits(press(2, A, B, CLEAR)), [("text", "AB--")])
expect("press: no side sequence, painted bars kept", pget(CNT), 0)
expect("press: ... and the recorded bar is still there", (bar_entry(0, 1) or {}).get("rows")[5],
       (0x7777, 0x8888))
expect("press: A+B+LAST STEP + pad keeps the stock path", press(2, A, B, LAST), [("press", 1)])

# The row covers eight bars: pads 1..8 select a bar, pads 9..16 keep their stock step function.
uc.mem_write(HMI, b"\0\0")
expect("press: A + pad 8 shows bar 8 A", edits(press(8, A)), [("text", "  A8")])
expect("press: ... the A side is now eight bars", pget(CNT), 0x08)
expect("press: ... and the step pads are marked for repaint", r8(HMI) & 0x04, 0x04)
expect("press: its release is swallowed", release(8), [])
expect("press: B + pad 5 shows bar 5 B", edits(press(5, B)), [("text", "  B5")])
expect("press: ... five B bars beside the eight A bars", pget(CNT), 0x58)
expect("press: its release is swallowed too", release(5), [])
expect("press: pads 9..16 still go to the firmware", press(13, A), [("press", 12)])
expect("press: LAST STEP still wins on pad 8", press(8, A, LAST), [("press", 7)])

# A/B + CLEAR + pad n sets that one side to exactly n bars, so a side can shrink without touching
# the other. The bars beyond the new length are hidden, not deleted: growing the length again
# brings them back (the log still holds them).
set_counts(4, 2)
expect("shrink: A + CLEAR + pad 2 sets A to exactly two bars", edits(press(2, A, CLEAR)),
       [("text", "  A2")])
expect("shrink: ... Ptn2 holds two A bars and two B bars", pget(CNT), 0x22)
expect("shrink: A + CLEAR + pad 4 grows A back to four", edits(press(4, A, CLEAR)),
       [("text", "  A4")])
expect("shrink: ... four A bars, B untouched", pget(CNT), 0x24)
expect("shrink: B + CLEAR + pad 1 sets B to one bar", edits(press(1, B, CLEAR)),
       [("text", "  B1")])
expect("shrink: ... and leaves A alone", pget(CNT), 0x14)
set_counts(3, 0)
expect("shrink: A + pad 1 without CLEAR still only selects, no shrink", edits(press(1, A)),
       [("text", "  A1")])
expect("shrink: ... three A bars are kept", pget(CNT), 0x03)

# A swallowed press must swallow its release, or the screen sees a release without a press.
expect("press: A + pad 3 is taken", edits(press(3, A)), [("text", "  A3")])
clear_repaint()
expect("press: its release is swallowed", release(3), [])
expect("press: ... and leaves the bar on the display", repaint(), 0)
expect("press: other pads still release normally", release(6), [("release", 5)])
expect("press: the same pad releases normally afterwards", release(3), [("release", 2)])

# The bar number is only the confirmation of the pad press. Releasing the variation button calls
# the firmware's own "repaint pads and text" helper (FUN_60051E20, 0x44 on the panel object,
# served by the dispatcher on its next pass), so the default view comes back. The patch must go
# through that helper: writing the panel object by hand is what went wrong in an earlier build.
clear_repaint()
expect("release: VARIATION A goes to the firmware, then asks the panel to repaint",
       release(A + 1), [("release", A), ("repaint_panel",)])
expect("release: ... and hands the display back", repaint(), 0x40)
clear_repaint()
expect("release: VARIATION B goes to the firmware, then asks the panel to repaint",
       release(B + 1), [("release", B), ("repaint_panel",)])
expect("release: ... and hands the display back", repaint(), 0x40)
clear_repaint()
expect("release: another button leaves the display alone", release(0x13), [("release", 0x12)])
expect("release: ... with the bit still clear", repaint(), 0)

# --- playback ---------------------------------------------------------------------
# Every sequence starts on bar 1 and advances one bar per wrap. A side and B side have their own
# length; A+B plays the A sequence and then the B one.
def start(**kw):
    w32(VARI, kw.get("vari", 2))
    w32(EFF, kw.get("eff", 0))
    log.clear()
    uc.mem_write(S["chain_wrapping"], b"\0")
    call(S["chain_var"], PTN)
    return (r32(EFF), r8(S["chain_side"]),
            r8(S["chain_row"] + r8(S["chain_side"])))

def wrap():
    uc.mem_write(S["chain_wrapping"], b"\1")
    call(S["chain_var"], PTN)
    uc.mem_write(S["chain_wrapping"], b"\0")
    return (r32(EFF), r8(S["chain_side"]),
            r8(S["chain_row"] + r8(S["chain_side"])))

def set_chain(a, b):
    set_counts(a, b)

seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)          # a clean log: every bar is the pattern itself
sync_panel()                       # the panel task scans the log and fills the bar cache

# A three-bar phrase on side A.
set_chain(3, 0)
w32(VARI, 0)
expect("A chain: start on A bar 1", start(vari=0), (0, 0, 0))
expect("A chain: bar 1 is the pattern slot", (struct_rows(), struct_scalars()),
       (slot_rows(1), (0x11, 0x21, SCALE[1])))
expect("A chain: bar 1 masks applied with A", log[-1], ("apply", 0))
expect("A chain: bar 2", wrap(), (0, 0, 1))
expect("A chain: bar 3", wrap(), (0, 0, 2))
expect("A chain: wraps back to bar 1", wrap(), (0, 0, 0))

# Shrinking a side while it plays: the playhead is clamped at the next wrap, so the phrase
# restarts from bar 1 instead of playing a bar the side no longer has.
expect("A chain: bar 2 again", wrap(), (0, 0, 1))
set_counts(2, 0)
expect("A chain: shrunk to two bars, the next wrap starts over at bar 1", wrap(), (0, 0, 0))

# Eight bars: the same rule, seven wraps and back to bar 1.
set_chain(8, 0)
expect("A chain: eight bars start on bar 1", start(vari=0), (0, 0, 0))
for b in range(1, 8):
    expect(f"A chain: eight bars, bar {b + 1}", wrap(), (0, 0, b))
expect("A chain: eight bars wrap back to bar 1", wrap(), (0, 0, 0))
set_chain(3, 0)

# Two bars on side B, selected on the panel.
set_chain(0, 2)
w32(VARI, 1)
expect("B chain: start on B bar 1", start(vari=1), (1, 1, 0))
expect("B chain: bar 1 is the pattern slot", struct_rows(), slot_rows(1))
expect("B chain: bar 2", wrap(), (1, 1, 1))
expect("B chain: wraps back to bar 1", wrap(), (1, 1, 0))

# A+B: three A bars, then two B bars, then back to the A sequence.
set_chain(3, 2)
w32(VARI, 2)
expect("A+B: A bar 1", start(vari=2), (0, 0, 0))
expect("A+B: A bar 2", wrap(), (0, 0, 1))
expect("A+B: A bar 3", wrap(), (0, 0, 2))
expect("A+B: B bar 1", wrap(), (1, 1, 0))
expect("A+B: B bar 2", wrap(), (1, 1, 1))
expect("A+B: back to A bar 1", wrap(), (0, 0, 0))

# --- bar jump: A/B + pad moves the playhead, stopped or playing --------------------
# Selecting a bar with A/B + pad is also a jump: a fresh start begins at the selected bar, and
# while playing the next bar boundary is that bar instead of the next one in the order.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
sync_panel()
set_chain(4, 0)
w32(VARI, 0)
expect("jump: nothing selected, a start begins at A bar 1", start(vari=0), (0, 0, 0))
expect("jump: ... bar 2", wrap(), (0, 0, 1))
press(3, A)                                   # select bar 3 while the machine is stopped
expect("jump: bar 3 is the working copy", pget(CNT), 0x04)
expect("jump: a start now begins at the selected bar 3", start(vari=0), (0, 0, 2))
expect("jump: ... carries on with bar 4", wrap(), (0, 0, 3))
expect("jump: ... and wraps to bar 1", wrap(), (0, 0, 0))

press(1, A)                                   # playhead back on bar 1
start(vari=0)                                 # bar 1
expect("jump: playing bar 2", wrap(), (0, 0, 1))
press(2, A)                                   # select the bar that is playing
expect("jump: selecting the playing bar keeps it at the next boundary", wrap(), (0, 0, 1))
press(3, A)                                   # jump to bar 3 while playing
expect("jump: the next boundary is the selected bar 3", wrap(), (0, 0, 2))
expect("jump: ... then bar 4", wrap(), (0, 0, 3))
expect("jump: ... then bar 1", wrap(), (0, 0, 0))

# The B side jumps the same way; a bar the side does not have clamps to its first bar.
set_chain(3, 2)
w32(VARI, 1)
press(2, B)
expect("jump: a start on B begins at the selected B bar 2", start(vari=1), (1, 1, 1))
press(4, A)                                   # A bar 4 is past the B side's two bars
expect("jump: the B side clamps a bar it does not have", start(vari=1), (1, 1, 0))

# Playback moves each side's row head: the bar row blinks the bar of the pass being played.
press(2, B)                                   # the B side's head on its bar 2
press(1, A)                                   # the A playhead back on bar 1
set_chain(3, 2)                               # three A bars, two B bars
w32(RUN, 1)
start(vari=0)
expect("row: the A sequence starts with A bar 1 blinking",
       row(0x6001773A, (1, 7, 7), (A,)), want_row([BLINK, GREEN, GREEN, OFF]))
wrap()
expect("row: ... and moves to A bar 2",
       row(0x6001773A, (1, 7, 7), (A,)), want_row([GREEN, BLINK, GREEN, OFF]))
expect("row: the B side has not played yet, so its head is its first bar",
       row(0x6001773A, (1, 7, 7), (B,)), want_row([BLINK, GREEN, OFF, OFF]))
w32(RUN, 0)

# A side never selected: with the panel on A the stock variation runs; B still has its own
# sequence and A+B plays the B bars (there are no A bars).
set_chain(0, 2)
w32(PTN + 0x14, 0x7777)
w32(PTN + 0x20, 0x1234)
log.clear(); w32(VARI, 0); w32(EFF, 0)
uc.mem_write(S["chain_wrapping"], b"\0")
call(S["chain_var"], PTN)
expect("A never selected, panel A: the stock variation runs, no bar is loaded",
       (r32(EFF), r32(PTN + 0x14), r16(PTN + 0x20)), (0, 0x7777, 0x1234))
expect("A never selected, panel B: B still plays its two bars", start(vari=1), (1, 1, 0))
expect("A never selected, panel B: bar 2", wrap(), (1, 1, 1))
expect("A never selected, A+B: the B bars play", start(vari=2), (1, 1, 0))
expect("A never selected, A+B: bar 2", wrap(), (1, 1, 1))
expect("A never selected, A+B: wraps to B bar 1", wrap(), (1, 1, 0))

# No side selected at all: stock behaviour, A+B toggles every pass, no content is loaded.
set_chain(0, 0)
w32(PTN + 0x14, 0x7777)
w32(PTN + 0x20, 0x1234)
w32(EFF, 0)
expect("no sequence, A+B: stock toggle to B", start(vari=2)[0], 1)
expect("no sequence: the player content was left alone",
       (r32(PTN + 0x14), r16(PTN + 0x20)), (0x7777, 0x1234))
expect("no sequence, A+B: toggle back to A", wrap()[0], 0)

# --- a recorded bar in the sequence -----------------------------------------------
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
press(2, A)                                   # bar 2 becomes the working copy
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x7777)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x8888)
w32(slot_addr(0) + 4, 2)                      # SCALE
w32(slot_addr(0) + 8, 0x0C)                   # LAST_A
w32(slot_addr(0) + 12, 0x0D)                  # LAST_B
call(S["chain_commit"], 0, 4, 1, 0)           # record bar 2
set_chain(3, 0)
w32(VARI, 0)
press(1, A)                                   # put the playhead back on bar 1
expect("recorded bar: start on bar 1, still the pattern",
       (start(vari=0), struct_rows(), struct_scalars()),
       ((0, 0, 0), slot_rows(1), (0x11, 0x21, SCALE[1])))
expect("recorded bar: bar 2 has the edit", (wrap(), struct_rows(), struct_scalars()),
       ((0, 0, 1),
        [(0x7777 if i == 5 else 0x4000 + (1 << 8) + i,
          0x8888 if i == 5 else 0x5000 + (1 << 8) + i) for i in range(26)],
        (0x0C, 0x0D, SCALE[2])))
expect("recorded bar: bar 3 is the pattern again", (wrap(), struct_rows()), ((0, 0, 2), slot_rows(1)))
expect("recorded bar: wraps to bar 1", wrap(), (0, 0, 0))

# --- another pattern: its own bars, its own lengths -------------------------------
# Pattern 2 (area 4 slot 3) gets a recorded bar 1 and a two-bar A sequence.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
set_pattern(2)                        # the panel switches pattern; the Ptn2 slots follow
expect("pattern 2: A + pad 1 selects its bar 1", edits(press(1, A)), [("text", "  A1")])
expect("pattern 2: the working copy is pattern 2", slot_rows(0), slot_rows(3))
expect("pattern 2: its own A length", pget(CNT), 0x01)
w32(slot_addr(0) + 4 * (4 + 2 * 2), 0x6A6A)
call(S["chain_commit"], 0, 4, 3, 0)
expect("pattern 2: its bar was stored on its own", (bar_entry(2, 0) or {}).get("rows")[2][0], 0x6A6A)
expect("pattern 2: pattern 0 has no bars in this log", bar_entry(0, 0), None)
set_counts(2, 0)
w32(VARI, 0)
expect("pattern 2 chain: bar 1 is its recorded bar", (start(vari=0), struct_rows()[2]),
       ((0, 0, 0), (0x6A6A, 0x5000 + (3 << 8) + 2)))
expect("pattern 2 chain: bar 2 is untouched", (wrap(), struct_rows()), ((0, 0, 1), slot_rows(3)))
set_pattern(0)
expect("pattern 0 keeps its own (unset) lengths", pget(CNT), 0)

# --- the step view follows the bar that is playing ---------------------------------
# The step pads are painted from area 4 slot 0, so the patch puts the bar that is playing there
# in the panel task: chain_view replaces the "bl FUN_60016386" at 0x60016C44 (bit 0x04 of the
# panel object) and runs just before that paint. The bar it leaves is stored only when the panel
# edited it, so steady playback writes no flash. Stopped, the working copy stays on the bar the
# user selected.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)

SHOWN = []                           # display text written by the last panel() call
def panel(obj=0x60149B8C):
    """What the panel dispatcher does with bit 0x04: call the payload, then paint the pads.
    The bar shown on the display goes to SHOWN, the rest of the log is returned."""
    log.clear()
    WRITES["prog"] = WRITES["erase"] = 0
    call(S["chain_view"], obj)
    SHOWN[:] = texts(log)
    return ([e for e in log if e[0] != "text"], WRITES["prog"], WRITES["erase"])

SETVIEW = [("stepview", 0x60149B8C)]

# Bar 2 of pattern 0 gets a recorded step, bar 1 stays the pattern's own steps.
press(2, A)
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x7777)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x8888)
call(S["chain_commit"], 0, 4, 1, 0)
press(1, A)                                   # back on bar 1
set_chain(3, 0)
w32(VARI, 0)
w32(RUN, 1)
expect("follow: playing A bar 1", start(vari=0), (0, 0, 0))

expect("follow: bar 1 is already the working copy, no reload", panel(), (SETVIEW, 0, 0))
expect("follow: ... the pads show bar 1", slot_rows(0), slot_rows(1))
expect("follow: bar 2 plays", wrap(), (0, 0, 1))
expect("follow: the panel loads the bar that is playing, and writes nothing",
       panel(), (SETVIEW, 0, 0))
expect("follow: ... the pads now show the recorded bar 2", slot_rows(0)[5], (0x7777, 0x8888))
expect("follow: a second paint of the same bar does not reload", panel(), (SETVIEW, 0, 0))

# Editing the step view while the sequence plays edits the playing bar; leaving it stores it.
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x1234)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x5678)
expect("follow: bar 3 plays", wrap(), (0, 0, 2))
expect("follow: ... the edited bar 2 is stored, once", panel(), (SETVIEW, 1, 0))
expect("follow: ... with the edit made during playback",
       (bar_entry(0, 1) or {}).get("rows")[5], (0x1234, 0x5678))
expect("follow: ... and bar 3 is the pattern", slot_rows(0), slot_rows(1))

# A bar nobody edited is not rewritten when the sequence leaves it.
expect("follow: wraps to bar 1", wrap(), (0, 0, 0))
expect("follow: the untouched bar 3 costs no write", panel(), (SETVIEW, 0, 0))
expect("follow: ... and bar 1 is back in the working copy", slot_rows(0), slot_rows(1))

# The side is part of the working copy: the same bar on the other side has to be reloaded.
uc.mem_write(S["chain_side"], b"\1")
uc.mem_write(S["chain_row"] + 1, b"\1")
vari0 = r32(slot_addr(0))
expect("follow: the same bar on the B side is reloaded", panel()[1:], (0, 0))
expect("follow: ... and the panel's VARI is kept (following is not a side selection)",
       r32(slot_addr(0)), vari0)

# Stopped, the panel owns the working copy: nothing follows the row head.
w32(RUN, 0)
uc.mem_write(S["chain_side"], b"\0")
uc.mem_write(S["chain_row"], bytes([2]))
expect("follow: stopped, the panel keeps the bar the user selected", panel(),
       (SETVIEW, 0, 0))
expect("follow: ... nothing was loaded", r32(slot_addr(0)), vari0)

# A pattern change while playing: the panel has already put the new pattern into area 4 slot 0, so
# a follow running with the old pattern number would store that new content as a bar of the old
# pattern. chain_view calls sync() first, so the change is noticed and nothing is written.
before = len(entries())
w32(RUN, 1)
w32(SETUP + 8, 1)                             # the panel switched to pattern 2
uc.mem_write(S["chain_side"], b"\0")
uc.mem_write(S["chain_row"], bytes([2]))      # the old pattern was playing bar 3
expect("follow: a pattern change is noticed before any follow", panel(), (SETVIEW, 0, 0))
expect("follow: ... the new pattern's own steps are loaded", slot_rows(0), slot_rows(2))
expect("follow: ... and no bar was written for the old pattern", len(entries()), before)

# --- a step entered while the bar plays is heard at the next pass --------------------
# TR-REC writes the working copy. The bar that is in the working copy is played from there, not
# from the cache, which is only refreshed when the bar is stored: with a one-bar sequence the
# playhead never leaves the bar, so the cached copy played the old steps until a stop (reported
# on the unit: steps entered in TR-REC were silent until stop/start).
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
sync_panel()
set_chain(1, 0)
press(1, A)                                   # bar 1 of side A in the working copy
w32(VARI, 0)
w32(RUN, 1)
expect("live: one A bar plays", start(vari=0), (0, 0, 0))
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x0F0F)  # TR-REC: a step on row 5, A side
expect("live: the next pass is the same bar", wrap(), (0, 0, 0))
expect("live: ... and it plays the step just entered", struct_rows()[5][0], 0x0F0F)
expect("live: ... with nothing written to the flash", entries(), [])

# Two bars: bar 2 is not in the working copy, so it plays its stored content; back on bar 1
# the edit made there is heard even though the panel has not followed yet.
set_chain(2, 0)
w32(slot_addr(0) + 4 * (4 + 2 * 6), 0x3C3C)
expect("live: two bars, bar 2", wrap(), (0, 0, 1))
expect("live: ... bar 2 is the pattern, not the working copy", struct_rows()[6], slot_rows(1)[6])
expect("live: back on bar 1", wrap(), (0, 0, 0))
expect("live: ... with both edits", (struct_rows()[5][0], struct_rows()[6][0]), (0x0F0F, 0x3C3C))
w32(RUN, 0)

# --- power cycle ------------------------------------------------------------------
# Record bar 2, then reset the payload state the way a power cycle does: .data reloaded, .bss
# cleared, the flash log untouched. The Ptn2 lengths are part of the pattern's parameter area in
# the stock store, so they survive too (the test keeps that RAM).
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
press(2, A)
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x7777)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x8888)
w32(slot_addr(0) + 8, 0x0C)
w32(slot_addr(0) + 12, 0x0D)
call(S["chain_commit"], 0, 4, 1, 0)
set_chain(3, 0)
w32(VARI, 0)
# The index is in the image and zeroed at boot; cold_boot clears the payload's .bss the same way.
cold_boot()
sync_panel()
expect("power cycle: the log is rescanned and bar 2 still has the edit",
       (start(vari=0), wrap(), struct_rows()[5]),
       ((0, 0, 0), (0, 0, 1), (0x7777, 0x8888)))
expect("power cycle: the recorded bar keeps its last steps", struct_scalars()[0:2], (0x0C, 0x0D))
expect("power cycle: bar 3 is still the pattern", (wrap(), struct_rows()), ((0, 0, 2), slot_rows(1)))
expect("power cycle: back to bar 1", wrap(), (0, 0, 0))

# --- an upgrade keeps the bars the earlier builds stored ---------------------------
# The builds before this one numbered entry i as 0x3DF000 - (i // 32) * 0x1000 + (i % 32) * 128,
# i.e. the same 16 KB in the opposite block order: old entry 0 is where entry 96 is addressed
# now, old entry 32 where entry 64 is. The scan must find both and the bars must play.
seed_ram()
FL[:] = b"\xff" * len(FL)
def old_entry(i, bar, row):
    e = [0] * 32
    e[0] = MAGIC
    e[1] = 1 | (bar << 20)                     # seq 1, pattern 0, bar `bar`
    e[2] = 0
    e[4 + 5] = row | ((row + 1) << 16)
    e[3] = crc(e)
    struct.pack_into("<32I", FL, 0x3DF000 - (i // EPB) * 0x1000 + (i % EPB) * ENT, *e)
old_entry(0, 1, 0x1111)                       # pad 2, i.e. bar index 1
old_entry(32, 2, 0x3333)                      # pad 3
set_chain(3, 0)
cold_boot()
sync_panel()
expect("upgrade: the old log is read back at its addresses", start(vari=0), (0, 0, 0))
expect("upgrade: old entry 0 is bar 2", (wrap(), struct_rows()[5]), ((0, 0, 1), (0x1111, 0x1112)))
expect("upgrade: old entry 32 is bar 3", (wrap(), struct_rows()[5]), ((0, 0, 2), (0x3333, 0x3334)))

# --- the log does not lose a bar when a block is full -----------------------------
seed_ram()
cold_boot()
w32(SETUP + 8, 0)
press(1, A)                                   # sync: the patch now owns bar 1
for i in range(NENT + 5):                    # force a compaction
    w32(slot_addr(0) + 4 * (4 + 2 * 0), 0x400 + i)
    call(S["chain_commit"], 0, 4, 1, 0)
expect("log: one entry per bar survives compaction", (bar_entry(0, 0) or {}).get("rows")[0][0], 0x400 + NENT + 4)
expect("log: the entries still fit in five blocks", len(entries()) <= NENT, True)
expect("log: bar 1 is still readable after compaction",
       (bar_entry(0, 0) or {}).get("seq") is not None, True)

# --- the ring wraps and blocks are compacted: the newest entry per bar wins ---------
# 128 keys x 2 rounds is 256 appends, more than the 160 slots, so the write pointer wraps and
# every block is compacted at least once. Each bar carries a distinct marker.
# (The live set is the worst case: 16 patterns x 8 bars = 128 entries in 160 slots.)
seed_ram()
cold_boot()
# Before the patch has seen a pad (cold boot), a save of a pattern it has not loaded is the
# stock commit: the working copy is the pattern itself, not a bar.
log.clear()
call(S["chain_commit"], 0, 4, 1, 0)
expect("save: a pattern the patch has not loaded goes through the stock commit", log, [("commit", 4, 1)])

def marker(rnd, p, b):
    return (0x1000 + (rnd << 8) + p * 8 + b) & 0xFFFF

def save_bar(rnd, p, b):
    w32(SETUP + 8, p)
    w32(SETUP + 0x3C, p)
    press(b + 1, A)                       # select and load the bar
    w32(slot_addr(0) + 4 * 4, marker(rnd, p, b))
    w32(slot_addr(0) + 4 * 5, 0x5000 + marker(rnd, p, b))
    log.clear()
    call(S["chain_commit"], 0, 4, p + 1, 0)

for rnd in range(2):
    for p in range(16):
        for b in range(8):
            save_bar(rnd, p, b)
expect("log: all 128 bars have an entry",
       sorted({(e["pat"], e["bar"]) for e in entries()}),
       [(p, b) for p in range(16) for b in range(8)])

cold_boot()
bad = []
for p in range(16):
    for b in range(8):
        w32(SETUP + 8, p)
        w32(SETUP + 0x3C, p)
        press(b + 1, A)                   # loads the bar through the payload's index
        want = (marker(1, p, b), 0x5000 + marker(1, p, b))
        if slot_rows(0)[0] != want:
            bad.append(((p, b), slot_rows(0)[0], want))
expect("log: every bar reads back its newest entry after wrap and compaction", bad, [])
expect("log: the log still fits in its five blocks", len(entries()) <= NENT, True)
expect("flash: no program or erase was issued while the chip was protected", refused(), 0)
expect("flash: every write session was closed again before returning", PROTECT["left_open"], 0)

# --- the sequence number wraps at 2^16, and a save just after the wrap must be the newest ----
seed_ram()
for blk in range(NBLK):
    fl_erase(BASE + blk * 0x1000)
fl_erase(SCR)
def put_entry(i, seq, pat, bar, a, b):
    e = [MAGIC, seq | (pat << 16) | (bar << 20), 0, 0] + [a | (b << 16)] + [0] * 27
    e[3] = crc(e)
    FL[ent_off(i):ent_off(i) + ENT] = struct.pack("<32I", *e)
put_entry(0, 0xFFFE, 1, 2, 0x1111, 0x2222)
put_entry(1, 0xFFFF, 1, 2, 0x3333, 0x4444)
cold_boot()
w32(SETUP + 8, 1)
w32(SETUP + 0x3C, 1)
expect("sequence wrap: the newest of two entries is loaded", edits(press(3, A)), [("text", "  A3")])
expect("sequence wrap: ... which is the second one", slot_rows(0)[0], (0x3333, 0x4444))
w32(slot_addr(0) + 4 * 4, 0x7777)
call(S["chain_commit"], 0, 4, 2, 0)
expect("sequence wrap: the next save starts at 0",
       [e["seq"] for e in entries() if e["rows"][0][0] == 0x7777], [0])
cold_boot()
w32(SETUP + 8, 1)
w32(SETUP + 0x3C, 1)
press(3, A)
expect("sequence wrap: after a power cycle the bar written after the wrap still wins",
       slot_rows(0)[0], (0x7777, 0x4444))

# --- the panel task owns the flash; a direct start has to wait for it --------------
# chain_var runs in the sequencer task and never scans the log. Until the panel task has seen
# this pattern it plays one stock pass and asks for a repaint; the next boundary uses the chain.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
set_chain(3, 0)
w32(RUN, 0)
w32(VARI, 0)
uc.mem_write(HMI, b"\0\0")
before = struct_rows()
log.clear()
READS["n"] = 0
uc.mem_write(S["chain_wrapping"], b"\0")
call(S["chain_var"], PTN)
expect("sync: a start before the panel scanned plays stock",
       (struct_rows(), r8(HMI) & 0x04, READS["n"]), (before, 0x04, 0))
sync_panel()                                    # the panel task catches up
expect("sync: the panel scanned and cached the bars", READS["n"] > 0, True)
expect("sync: the next start follows the chain", start(vari=0), (0, 0, 0))

# The sequencer never touches the flash: no read, no program, no erase.
READS["n"] = 0
WRITES["prog"] = WRITES["erase"] = 0
start(vari=0); wrap(); wrap()
start(vari=1); wrap()
start(vari=2); wrap(); wrap()
expect("sync: playback issues no flash read", READS["n"], 0)
expect("sync: playback writes no flash", (WRITES["prog"], WRITES["erase"]), (0, 0))

# --- a pattern whose own variation is A+B keeps it across the change ---------------
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
sync_panel()
w32(slot_addr(2), 2)                   # pattern 1's own VARI: A+B
set_pattern(1)
sync_panel()                           # the panel picks the new pattern up (load writes the side)
expect("pattern: A+B survives the bar load of the new pattern", r32(slot_addr(0)), 2)
set_counts(2, 0)
w32(VARI, 2)
expect("pattern: ... and the A+B phrase starts on the A side", start(vari=2), (0, 0, 0))
expect("pattern: ... then bar 2", wrap(), (0, 0, 1))
expect("pattern: ... and wraps to bar 1", wrap(), (0, 0, 0))
set_pattern(0)
sync_panel()

# --- A+B: a B bar selected while stopped starts the B leg there --------------------
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
sync_panel()
set_chain(3, 4)
w32(VARI, 2)
press(3, B)                            # stopped: select B bar 3
expect("A+B jump: a start begins at the selected B bar",
       start(vari=2), (1, 1, 2))
expect("A+B jump: ... then B bar 4", wrap(), (1, 1, 3))
expect("A+B jump: ... and wraps to A bar 1", wrap(), (0, 0, 0))

# --- 7.2 a flash that drops one program -------------------------------------------
# store_save keeps the index, the clean hash and the cache when the read-back fails, so the
# next save of the same bar tries again instead of believing a write that never happened.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
sync_panel()
press(2, A)                                   # bar 2 of pattern 0, A side
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x3333)
w32(slot_addr(0) + 4 * (5 + 2 * 5), 0x4444)
drop_next_program()
log.clear()
call(S["chain_commit"], 0, 4, 1, 0)
expect("drop: the dropped program stored nothing", bar_entry(0, 1), None)
call(S["chain_commit"], 0, 4, 1, 0)           # no drop this time: the same bar is retried
expect("drop: ... and the retry stores the bar",
       (bar_entry(0, 1) or {}).get("rows")[5], (0x3333, 0x4444))
w32(slot_addr(0) + 4 * (4 + 2 * 5), 0x5555)   # an edit that is then lost
drop_next_program()
r = press(1, A)                               # leaving the bar retries the save and fails
expect("drop: a lost edit is shown to the user", "FAIL" in texts(r), True)
expect("drop: ... and the stored bar keeps its old value",
       (bar_entry(0, 1) or {}).get("rows")[5], (0x3333, 0x4444))
expect("drop: ... bar 1 is loaded", "  A1" in texts(r), True)
press(2, A)
expect("drop: ... so bar 2 comes back as it was stored", slot_rows(0)[5], (0x3333, 0x4444))

# --- 7.4 sequence numbers survive 0x7FFF -> 0x8000 --------------------------------
seed_ram()
FL[:] = b"\xff" * len(FL)
def put_seq(i, seq, mark):
    e = [MAGIC, seq | (1 << 16) | (0 << 20), 0, 0, mark | ((mark + 1) << 16)] + [0] * 27
    e[3] = crc(e)
    struct.pack_into("<32I", FL, ent_off(i), *e)
put_seq(0, 0x7FFE, 0x1000)
put_seq(1, 0x7FFF, 0x2000)
put_seq(2, 0x8000, 0x3000)
put_seq(3, 0x8001, 0x4000)
put_seq(4, 0x7FFE, 0x5000)                    # older duplicate above the newest: scan wins
cold_boot()
w32(SETUP + 8, 1)
w32(SETUP + 0x3C, 1)
press(1, A)                                   # pattern 1 bar 1
expect("seq 0x8000: the first valid entry starts the search, not 0",
       slot_rows(0)[0], (0x4000, 0x4001))

# --- 7.3 erased and half-written slots are skipped outside the boot scan -----------
# A full log (160 non-erased first words, so the next append needs a compaction): block 0 has
# four live entries among half-written ones, the other blocks hold the remaining 124 bars. The
# compaction of block 0 must copy the four live entries and skip every torn slot.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)

def put_bar(i, seq, key, mark):
    e = [0] * 32
    e[0] = MAGIC
    e[1] = seq | ((key // 8) << 16) | ((key % 8) << 20)
    e[2] = 0
    e[4] = mark | (((0x8000 + mark) & 0xFFFF) << 16)
    e[3] = crc(e)
    struct.pack_into("<32I", FL, ent_off(i), *e)

def junk(i, kind):
    if kind:
        e = [MAGIC, 1, 0, 0] + [0] * 28       # right magic, wrong checksum
    else:
        e = [0] * 32                          # first word programmed, nothing else
    struct.pack_into("<32I", FL, ent_off(i), *e)

for i in range(32):
    junk(i, i % 2)
for i, key in ((0, 124), (10, 125), (20, 126), (30, 127)):
    put_bar(i, 2, key, 0x2000 + key)
for key in range(124):
    put_bar(32 + key, 2, key, 0x2000 + key)
for i, key in ((156, 0), (157, 1), (158, 2), (159, 3)):
    put_bar(i, 1, key, 0x1000 + key)

cold_boot()
sync_panel()
bad = [key for key in range(128)
       if (bar_entry(key // 8, key % 8) or {}).get("rows", [(0, 0)])[0][0] != 0x2000 + key]
expect("torn: the boot scan skips every half-written slot", bad, [])

press(1, A)                                   # pattern 0 bar 1, A side
w32(slot_addr(0) + 4 * 4, 0x3000)
call(S["chain_commit"], 0, 4, 1, 0)           # slot 0 is used: compacts block 0
bad = [key for key in range(128)
       if (bar_entry(key // 8, key % 8) or {}).get("rows", [(0, 0)])[0][0]
       != (0x3000 if key == 0 else 0x2000 + key)]
expect("torn: a compaction copies the live entries and skips the torn ones", bad, [])
expect("torn: no torn slot became a valid entry", len(entries()), 133)

# --- 7.1 power cut at every step of a compaction ----------------------------------
# The log is full: 120 live bars and 40 older duplicates, so the next append picks block 4 (the
# block with the fewest live entries, 8) and copies it through the scratch block. For each flash
# operation the payload makes, the power is cut right after it; a cold boot must then still find
# every one of the 120 bars that was stored before the save.
seed_ram()
cold_boot()
FL[:] = b"\xff" * len(FL)
for key in range(96):
    put_bar(key, 2, key, 0x2000 + key)
for key in range(96, 112):
    put_bar(key, 2, key, 0x2000 + key)
for key in range(16):
    put_bar(112 + key, 1, key, 0x1000 + key)
for i, key in enumerate(range(112, 120)):
    put_bar(128 + i, 2, key, 0x2000 + key)
for key in range(16, 40):
    put_bar(136 + key - 16, 1, key, 0x1000 + key)
set_pattern(15)
snapshot = bytes(FL)

def cut_save(cut):
    FL[:] = snapshot
    cold_boot()
    w32(SETUP + 8, 15)
    w32(SETUP + 0x3C, 15)
    set_counts(1, 0)                          # pattern 15 has an A side, so saves are redirected
    sync_panel()                              # loads bar 1; scan + recovery, no cut armed
    w32(slot_addr(0) + 4 * 4, 0x3000)
    cut_after(cut)
    log.clear()
    call(S["chain_commit"], 0, 4, 16, 0)
    hit = CUT["hit"]
    cut_after(None)
    cold_boot()
    sync_panel()                              # the boot scan finishes any interrupted compaction
    return hit

def stored_bad():
    return [key for key in range(120)
            if (bar_entry(key // 8, key % 8) or {}).get("rows", [(0, 0)])[0][0]
            != 0x2000 + key]

# Count the operations of one save (the cut is disarmed but every op is counted).
FL[:] = snapshot
cold_boot()
w32(SETUP + 8, 15)
w32(SETUP + 0x3C, 15)
set_counts(1, 0)
sync_panel()
w32(slot_addr(0) + 4 * 4, 0x3000)
CUT["ops"] = 0
call(S["chain_commit"], 0, 4, 16, 0)
OPS = CUT["ops"]
expect("power cut: the save compacts the eight-entry block (1+8+1+8+1 ops)", OPS, 19)

lost = []
for k in range(OPS):
    if not cut_save(k):
        lost.append((k, "no cut"))
        continue
    bad = stored_bad()
    if bad:
        lost.append((k, bad[:4]))
    # The bar being saved is new: either it never landed or it is complete and valid.
    e = bar_entry(15, 0)
    if e is not None and e["rows"][0][0] != 0x3000:
        lost.append((k, "new bar torn"))
expect("power cut: every stored bar survives a cut at every flash operation", lost, [])
cut_save(None)
expect("power cut: the completed save stores the new bar",
       (bar_entry(15, 0) or {}).get("rows")[0][0], 0x3000)

# --- 7.1b the power goes halfway through an erase or a program -----------------------
# A cut between two operations leaves whole sectors and whole entries. A cut inside one leaves a
# half-erased sector or a half-programmed entry (tests/periph.py, cut_at), and the boot scan must
# still find every stored bar.
def torn_save(k):
    FL[:] = snapshot
    flash.protect_all()
    cold_boot()
    w32(SETUP + 8, 15)
    w32(SETUP + 0x3C, 15)
    set_counts(1, 0)
    sync_panel()
    w32(slot_addr(0) + 4 * 4, 0x3000)
    flash.ops.clear()
    flash.cut_at = k
    log.clear()
    call(S["chain_commit"], 0, 4, 16, 0)
    hit = any(st == "cut" for *_, st in flash.ops)
    flash.cut_at = None
    cold_boot()
    sync_panel()
    return hit

lost = []
for k in range(OPS):
    if not torn_save(k):
        lost.append((k, "no cut"))
        continue
    bad = stored_bad()
    if bad:
        lost.append((k, bad[:4]))
    e = bar_entry(15, 0)
    if e is not None and e["rows"][0][0] != 0x3000:
        lost.append((k, "new bar torn"))
expect("torn: every stored bar survives a cut halfway through each erase and program", lost, [])
flash.protect_all()

# --- 7.2b a flash that drops one program during a compaction ------------------------
# Both copies are read back: a dropped copy stops the compaction before the source is gone (the
# copy-to-scratch phase) or keeps the scratch block as the only copy of the entries that were not
# written back (the copy-back phase), and no further save is written until the next boot recovers
# them. A dropped final program is an ordinary failed save: the next save retries.
def drop_save(k):
    FL[:] = snapshot
    cold_boot()
    w32(SETUP + 8, 15)
    w32(SETUP + 0x3C, 15)
    set_counts(1, 0)
    sync_panel()
    w32(slot_addr(0) + 4 * 4, 0x3000)
    log.clear()
    drop_program(k)
    call(S["chain_commit"], 0, 4, 16, 0)
    first = bar_entry(15, 0)
    CUT["ops"] = 0
    call(S["chain_commit"], 0, 4, 16, 0)       # a retry with the chip working again
    ops = CUT["ops"]
    cold_boot()
    sync_panel()                              # the boot scan recovers from the scratch block
    return first, ops, stored_bad(), bar_entry(15, 0)

bad = []
for k in range(17):                            # 8 copies out + 8 copies back + the save
    e, ops, lost, after = drop_save(k)
    if e is not None:
        bad.append((k, "the dropped save landed"))
    if lost:
        bad.append((k, "stored bar lost", lost[:3]))
    if k < 16:                                 # a compaction step failed
        if ops:
            bad.append((k, "a retry wrote after a failed compaction"))
        if after is not None:
            bad.append((k, "the bar landed without a save"))
    elif after is None or after["rows"][0][0] != 0x3000:
        bad.append((k, "the retried save did not land"))
expect("drop during compaction: every stored bar survives and nothing else is written", bad, [])

# chain_wrap marks the restart as a wrap for the duration of the firmware restart call.
w32(S["chain_wrapping"], 0)
log.clear(); call(S["chain_wrap"], PTN)
expect("wrap: the restart runs with the wrap mark set, then the mark is cleared",
       (log, r8(S["chain_wrapping"])), ([("restart", 1)], 0))

# Model self-check: this is the hardware-only failure the first build hit. With the latch closed
# a program is dropped; inside a session it lands. Without this the test would pass a payload
# that never opens a write session, which is exactly what happened before.
uc.mem_write(0x7000E800, b"\0\0\0\0")
fl_erase(0x3D8000)
flash.protect_all()
call(0x60003E54, 0x3D8000, 4, 0x7000E800)
dropped = bytes(FL[0x3D8000:0x3D8004])
call(0x600108AA)
call(0x60003E54, 0x3D8000, 4, 0x7000E800)
call(0x600108BA)
expect("flash model: a protected chip drops a program, an open session accepts it",
       (dropped, bytes(FL[0x3D8000:0x3D8004])), (b"\xff" * 4, b"\0\0\0\0"))

# --- a bar left in the log must not overwrite a pattern that has no sequence any more ------
# A bar recorded while the pattern had a sequence stays in the log after A+B+CLEAR. The stock
# commit saves the pattern from then on, so neither a pattern change (sync) nor the playhead
# follow (chain_view) may load that old bar into the working copy: the next stock save would
# write it into the pattern slot and lose the edits made since.
seed_ram()
for blk in range(NBLK):
    fl_erase(BASE + blk * 0x1000)
fl_erase(SCR)
cold_boot()
set_pattern(0)
sync_panel()
def save_p0():
    """The firmware's pattern save; the stub of the stock commit copies slot 0 to slot 1."""
    log.clear()
    call(S["chain_commit"], 0, 4, 1, 0)
    stock = ("commit", 4, 1) in log
    if stock:
        uc.mem_write(slot_addr(1), bytes(uc.mem_read(slot_addr(0), 4 * C4)))
    return stock
press(1, A)
w32(slot_addr(0) + 4 * 4, 0xAAAA)
expect("stale bar: with a sequence, the bar goes to the log", save_p0(), False)
press(1, A, B, CLEAR)
w32(slot_addr(0) + 4 * 4, 0xBBBB)
expect("stale bar: after A+B+CLEAR the stock commit saves the pattern",
       (save_p0(), slot_rows(1)[0][0]), (True, 0xBBBB))
set_pattern(1)
sync_panel()
set_pattern(0)
sync_panel()
expect("stale bar: back on the pattern, the working copy is the pattern, not the old bar",
       slot_rows(0)[0][0], 0xBBBB)
expect("stale bar: ... and the next save keeps it", (save_p0(), slot_rows(1)[0][0]), (True, 0xBBBB))
uc.mem_write(S["chain_row"], bytes([2, 0]))          # left over from the earlier sequence
uc.mem_write(S["chain_side"], bytes([0]))
w32(RUN, 1)
log.clear()
call(S["chain_view"], 0x70002000)
expect("stale bar: stock playback does not follow an old chain_row", slot_rows(0)[0][0], 0xBBBB)
w32(RUN, 0)

# --- expand (A/B + a tap of LAST STEP) and copy A->B (A + B + a tap) --------------------
# A side of one bar shorter than 16 steps doubles its steps (through the firmware's setter, so the
# normal save stores it); after that the bars double. The length moves only when every bar it
# adds is in the flash.
def fresh(last_a=15, last_b=15, counts=(0, 0)):
    seed_ram()
    cold_boot()
    FL[:] = b"\xff" * len(FL)
    for slot in (0, 1):
        w32(slot_addr(slot) + 8, last_a)
        w32(slot_addr(slot) + 12, last_b)
    set_counts(*counts)
    sync_panel()

def tap_last(*buttons):
    """LAST STEP goes down and up while `buttons` are held; returns the log of both."""
    held.clear(); held.update(buttons); held.add(LAST); log.clear()
    call(S["chain_press"], LAST)
    held.discard(LAST)
    call(S["chain_release"], LAST)
    held.clear()
    return list(log)

def half(bar, s):
    """(LAST, 26 masks) of side s of bar `bar` of pattern 0, as playback would read it."""
    e = bar_entry(0, bar)
    if e:
        return ((e["last"] >> (8 * s)) & 0xFF, [r[s] for r in e["rows"]])
    b = slot_addr(1)
    return (r32(b + 8 + 4 * s), [r32(b + 4 * (4 + 2 * i + s)) & 0xFFFF for i in range(26)])

def counts():
    return (pget(CNT) & 0xF, (pget(CNT) >> 4) & 0xF)

def flash_writes():
    return WRITES["prog"] + WRITES["erase"]

fresh()
PAT_A = half(0, 0)[1]
PAT_B = half(0, 1)[1]
w0 = flash_writes()
expect("expand: a 16-step pattern with no sequence becomes two bars", texts(tap_last(A)), ["A b2"])
expect("expand: ... A has two bars, B none", counts(), (2, 0))
expect("expand: ... bar 2 is the pattern itself: nothing is written", flash_writes() - w0, 0)
w32(slot_addr(0) + 4 * 4, 0x1234)                      # an edit of bar 1 that is not saved yet
expect("expand: 2 -> 4 bars", texts(tap_last(A)), ["A b4"])
expect("expand: ... bar 3 is bar 1 with its unsaved edit", half(2, 0)[1][0], 0x1234)
expect("expand: ... bar 3 keeps the B half and the scale of its own",
       (half(2, 1)[1], bar_entry(0, 2)["scale"]), (PAT_B, 1))
expect("expand: ... bar 4 is bar 2, still the pattern: no entry", bar_entry(0, 3), None)
expect("expand: ... the working copy is still bar 1, edit kept", slot_rows(0)[0][0], 0x1234)
expect("expand: 4 -> 8 bars", (texts(tap_last(A)), counts()), (["A b8"], (8, 0)))
expect("expand: ... bars 5-8 are bars 1-4 (bar 1 is the unsaved working copy)",
       [half(b, 0)[1][0] for b in range(1, 8)], [PAT_A[0], 0x1234, PAT_A[0], 0x1234, PAT_A[0], 0x1234, PAT_A[0]])
w0 = flash_writes()
expect("expand: a side of 8 bars is full", (texts(tap_last(A)), counts()), (["FULL"], (8, 0)))
expect("expand: ... and nothing is written", flash_writes() - w0, 0)
w32(slot_addr(0) + 4 * 5, 0x7777)                      # B half of bar 1
expect("expand: B + LAST STEP doubles B only", (texts(tap_last(B)), counts()), (["B b2"], (8, 2)))
expect("expand: ... bar 2 takes bar 1's B half and keeps its own A half",
       bar_entry(0, 1)["rows"][0], (PAT_A[0], 0x7777))

# 3 -> 6 and 5 -> 8: bars 1..c are appended after the last one.
fresh(counts=(3, 0))
for k in range(3):
    put_entry(k, 10 + k, 0, k, 0x0A00 + k, 0x0B00 + k)
cold_boot()
sync_panel()
expect("expand: 3 -> 6 bars", (texts(tap_last(A)), counts()), (["A b6"], (6, 0)))
expect("expand: ... bars 4-6 are bars 1-3 (A half)", [half(b, 0)[1][0] for b in range(6)],
       [0x0A00, 0x0A01, 0x0A02] * 2)
expect("expand: ... and keep their own B half", [half(b, 1)[1][0] for b in range(3, 6)],
       [PAT_B[0]] * 3)
set_counts(5, 0)
expect("expand: 5 -> 8 bars copies bars 1-3", (texts(tap_last(A)), counts()), (["A b8"], (8, 0)))
expect("expand: ... bars 6-8", [half(b, 0)[1][0] for b in range(5, 8)], [0x0A00, 0x0A01, 0x0A02])

# Steps: 4 -> 8 -> 16, then bars. Every row doubles, accents and flams too (they are rows).
fresh(last_a=3)
for i in range(26):
    w32(slot_addr(0) + 4 * (4 + 2 * i), 0xF0 | (i & 0xF))   # steps 5-8 set: they get cleared
B0 = slot_rows(0)
w0 = flash_writes()
lg = tap_last(A)
expect("expand steps: 4 -> 8", (texts(lg), slot_scalars(0)[0]), (["A  8"], 7))
expect("expand steps: ... steps 1-4 are copied to 5-8, the rest is kept",
       [r[0] for r in slot_rows(0)], [(i & 0xF) * 0x11 for i in range(26)])
expect("expand steps: ... B is untouched", [r[1] for r in slot_rows(0)], [r[1] for r in B0])
expect("expand steps: ... through the Ptn setter only, on A words",
       sorted({(e[1], e[2] % 2) for e in lg if e[0] == "hmi_set"}), [(0x6007ED24, 0)])
expect("expand steps: ... no flash write and no length change", (flash_writes() - w0, counts()),
       (0, (0, 0)))
expect("expand steps: 8 -> 16", (texts(tap_last(A)), slot_scalars(0)[0]), (["A 16"], 15))
expect("expand steps: ... row 3", slot_rows(0)[3][0], 0x3333)
w0 = flash_writes()
expect("expand steps: a 16-step bar doubles the bars", (texts(tap_last(A)), counts()),
       (["A b2"], (2, 0)))
expect("expand steps: ... bar 2 holds the doubled steps", half(1, 0), (15, [r[0] for r in slot_rows(0)]))
fresh(last_a=3, counts=(0, 2))
w32(slot_addr(0) + 4 * 4, 0x0005)
expect("expand steps: A with no sequence while B has one", texts(tap_last(A)), ["A  8"])
expect("expand steps: ... the save goes to the log as bar 1 (A+B side lengths kept)",
       (save_p0(), bar_entry(0, 0)["rows"][0][0], bar_entry(0, 0)["last"] & 0xFF, counts()),
       (False, 0x0055, 7, (0, 2)))
fresh(last_b=11)
w32(slot_addr(0) + 4 * 5, 0x0ABC)
expect("expand steps: B 12 -> 16 copies steps 1-4 to 13-16",
       (texts(tap_last(B)), slot_rows(0)[0][1], slot_scalars(0)), (["B 16"], 0xCABC, (15, 15)))

# Copy A -> B.
fresh(last_a=7, last_b=15)
w0 = flash_writes()
lg = tap_last(A, B)
expect("copy A->B: no sequence: the pattern's B steps and LAST_B take A's",
       (texts(lg), [r[1] for r in slot_rows(0)], slot_scalars(0)),
       (["AB 1"], PAT_A, (7, 7)))
expect("copy A->B: ... through the setter, no flash write, no length",
       (all(e[1] == 0x6007ED24 for e in lg if e[0] == "hmi_set"), flash_writes() - w0, counts()),
       (True, 0, (0, 0)))
fresh(counts=(3, 5))
for k in range(3):
    put_entry(k, 10 + k, 0, k, 0x0A00 + k, 0x0B00 + k)
put_entry(3, 13, 0, 4, 0x0A04, 0x0B04)
cold_boot()
sync_panel()
expect("copy A->B: with a sequence, B takes A's length", (texts(tap_last(A, B)), counts()),
       (["AB 3"], (3, 3)))
expect("copy A->B: ... each of A's bars has B = A", [bar_entry(0, k)["rows"][0] for k in range(3)],
       [(0x0A00 + k, 0x0A00 + k) for k in range(3)])
expect("copy A->B: ... B's hidden bar 5 is kept", bar_entry(0, 4)["rows"][0], (0x0A04, 0x0B04))
expect("copy A->B: ... the working copy (bar 1) shows the copy", slot_rows(0)[0], (0x0A00, 0x0A00))

# The tap is cancelled by any other press; LAST STEP alone does nothing new.
fresh()
held.clear(); held.update((A, LAST)); log.clear()
call(S["chain_press"], LAST)
call(S["chain_press"], 4)
lg = list(log)
held.discard(LAST); log.clear()
call(S["chain_release"], 4)
call(S["chain_release"], LAST)
held.clear()
expect("expand: A + LAST STEP + pad keeps its stock meaning (the pad goes to the firmware)",
       ("press", 4) in lg, True)
expect("expand: ... and the tap is cancelled", (texts(log), counts()), ([], (0, 0)))
expect("expand: LAST STEP without A or B does nothing new", (texts(tap_last()), counts()),
       ([], (0, 0)))

# A bar the chip does not take: FAIL, and the length does not move (DEVELOPING.md 7, rule 2).
fresh(counts=(2, 0))
w32(slot_addr(0) + 4 * 4, 0x1234)
drop_next_program()
expect("expand: a dropped write shows FAIL and keeps the length", (texts(tap_last(A)), counts()),
       (["FAIL"], (2, 0)))
expect("expand: ... no entry for bar 3", bar_entry(0, 2), None)
expect("expand: ... the retry works", (texts(tap_last(A)), counts()), (["A b4"], (4, 0)))
fresh(counts=(2, 0))
w32(slot_addr(0) + 4 * 4, 0x1234)
cut_after(0)
tap_last(A)
cut_after(None)
cold_boot()
sync_panel()
expect("expand: a power cut after the first write keeps the old length", counts(), (2, 0))
# The reboot lost the unsaved edit; bar 3, written before the cut, stayed hidden until now.
expect("expand: ... the retry overwrites the hidden bar 3", (texts(tap_last(A)), counts(), half(2, 0)[1][0]),
       (["A b4"], (4, 0), PAT_A[0]))

# Playback follows the new length on the next wrap.
fresh(counts=(1, 0))
w32(slot_addr(0) + 4 * 4, 0x1234)
expect("expand: one bar of 16 steps -> two bars", (texts(tap_last(A)), counts()), (["A b2"], (2, 0)))
expect("expand: playback starts on bar 1", start(vari=0), (0, 0, 0))
expect("expand: playback plays the new bar 2 on the next wrap", (wrap()[2], wrap()[2]), (1, 0))

# --- A+B keeps playing both sides while the step view follows the bar (unit bug, 2026-11-15) ----
# The firmware refills the panel VARI (+0x0C) from word 0 of the working copy at every restart
# (FUN_6000E0FE, just before chain_var). chain_view loads the playing bar into the working copy;
# it must not write the side into that word, or A+B becomes B after the first B bar and B loops.
fresh(counts=(2, 2))
for k in range(2):
    put_entry(k, 10 + k, 0, k, 0x0A00 + k, 0x0B00 + k)
cold_boot()
sync_panel()
w32(slot_addr(0), 2)                 # the panel's A+B (B pressed while A is held)
w32(RUN, 1)
order = []
w32(VARI, r32(slot_addr(0)))
r = start(vari=2)
for _ in range(6):
    order.append("AB"[r[1]] + str(r[2] + 1))
    panel()                          # the panel follows the bar that plays
    w32(VARI, r32(slot_addr(0)))     # FUN_6000E0FE: the next restart reads VARI from slot 0
    r = wrap()
w32(RUN, 0)
expect("A+B: the step view follows each bar and A+B keeps going",
       order, ["A1", "A2", "B1", "B2", "A1", "A2"])
expect("A+B: ... the working copy's VARI is still A+B", r32(slot_addr(0)), 2)

# The unit's gesture: A plays, then A+B is chosen while it plays (B pressed with A held).
fresh(counts=(2, 2))
for k in range(2):
    put_entry(k, 10 + k, 0, k, 0x0A00 + k, 0x0B00 + k)
cold_boot()
sync_panel()
w32(slot_addr(0), 0)
w32(RUN, 1)
w32(VARI, 0)
r = start(vari=0)
order = []
for k in range(8):
    order.append("AB"[r[1]] + str(r[2] + 1))
    panel()
    if k == 2:
        w32(slot_addr(0), 2)         # FUN_600186FA(Ptn, 0, 2): VARI = A+B, during A1
    w32(VARI, r32(slot_addr(0)))
    r = wrap()
w32(RUN, 0)
expect("A+B: chosen while A plays, B follows the A bars", order,
       ["A1", "A2", "A1", "A2", "B1", "B2", "A1", "A2"])

# --- the bar that plays is on the display, once per pass (panel task) ------------------------
fresh(counts=(2, 1))
w32(RUN, 1)
start(vari=2)
panel()                              # the first paint after the pattern change is skipped
panel()
expect("display: the first pass shows A bar 1 of 2", SHOWN, ["A1-2"])
panel()
expect("display: ... once per pass (a second paint writes nothing)", SHOWN, [])
wrap(); panel()
expect("display: the next pass shows A bar 2", SHOWN, ["A2-2"])
wrap(); panel()
expect("display: A+B goes on with B bar 1", SHOWN, ["B1-1"])
wrap(); panel()
expect("display: a one-bar side is shown again at every pass (it comes back after the tempo)",
       SHOWN, ["A1-2"])
wrap()
held.clear(); held.add(A)
panel()
held.clear()
expect("display: not while A is held (the gesture has its own text)", SHOWN, [])
wrap(); panel()
expect("display: ... and back at the next pass", SHOWN, ["B1-1"])
drop_next_program()
w32(slot_addr(0) + 4 * 4, 0x4321)
wrap(); panel()                      # leaving the edited bar: the chip drops the save
expect("display: a refused save shows FAIL", SHOWN, ["FAIL"])
wrap(); panel()
expect("display: ... and the next pass keeps it", SHOWN, [])
sync_panel()                         # any button press
wrap(); panel()
expect("display: after a press the bar is shown again", SHOWN[-1:], ["B1-1"])
w32(RUN, 0)
wrap(); panel()
expect("display: stopped, nothing is shown", SHOWN, [])
fresh()
w32(RUN, 1)
start(vari=0); panel()
expect("display: a pattern with no sequence keeps the stock display", SHOWN, [])
w32(RUN, 0)

print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
