#!/usr/bin/env python3
"""Emulate the poly payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_poly.py work/patched_poly/appA.bin

poly_trig calls the firmware's real step trigger FUN_600262F2; only its far callees (sound
engine thunks, message queue, float helpers) are stubs. Its return value (bit i = instrument i
fired) shows which instruments play at each step.
The LAST STEP gesture is tested through the firmware's own button handler FUN_6001961E.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pay = json.load(open(os.path.join(ROOT, "patches/poly/payload.json")))
S = pay["symbols"]
app = open(sys.argv[1], "rb").read()

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)
uc.mem_write(0x60000000, app)
uc.mem_map(0x70000000, 0x10000)
RET = 0x7000F000
uc.mem_write(RET, b"\xfe\xe7")

P = 0x6014A164
BD, SD, LT, MT, HT, RS, HC, CH, OH, CC, RC = range(11)
INST, ACC, FLAM, POS, RUN, LAST = 0x21, 0x42, 0x67, 0x66, 1, 3
r32 = lambda a: struct.unpack("<I", uc.mem_read(a, 4))[0]
w32 = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
pw = lambda i, v: w32(P + 4 * i, v)
pr = lambda i: r32(P + 4 * i)

log = []
held = set()                                   # buttons held (FUN_60013168)
STUBS = {0x60013168: "held", 0x6001B8D6: "set_last", 0x60015980: "text", 0x6001B12E: "setup_get",
         0x6004BCBE: "engine", 0x6004B962: "engine_go", 0x6000F9E0: "msg", 0x6000FA2C: "msg",
         0x6000FA20: "msg", 0x60053F38: "f", 0x60053B40: "f", 0x600522E4: "range", 0x600521E8: "f"}
during = []                                    # callbacks run at the first engine call
def hook(uc, addr, size, _):
    if addr in STUBS:
        name = STUBS[addr]
        r0, r1 = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
        ret = 0
        if name == "engine" and during:
            during.pop(0)()
        elif name == "held":
            ret = 1 if r0 in held else 0
        elif name == "setup_get":
            ret = 0xFFFFFFFF if r1 == 3 else 0     # Setup[3] == -1: the firmware's own pad condition
        elif name == "set_last":
            log.append(("set_last", r1))
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

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))

def bits(*steps):
    return sum(1 << s for s in steps)

def setup(last=15, scatter=-1):
    for i in range(0x80):
        pw(i, 0)
    pw(LAST, last)
    uc.mem_write(P + 0x1DA, struct.pack("<h", scatter))
    pw(INST + BD, bits(0, 4, 8, 12))           # four on the floor, follows the pattern
    pw(INST + CH, bits(0))                     # CH, length 3: plays every 3 steps
    pw(INST + RS, bits(0, 1))                  # RS, length 5: plays 2 of every 5 steps
    pw(ACC + CH, bits(0))                      # CH accent on its own step 0
    call(S["poly_run"], P, 0, 1)               # start: firmware sets P[1] = 1
    expect("start: original run-state setter called (P[1] = 1)", pr(RUN), 1)

def play(n, flam=0):
    """n advances; returns the list of fired-instrument masks."""
    return [call(S["poly_trig"], P, -1, flam) for _ in range(n)]

def fired(masks, inst):
    return [t for t, m in enumerate(masks) if m >> inst & 1]

expect("no length set at boot", list(uc.mem_read(S["poly_len"], 11)), [0] * 11)

# LAST STEP gesture through the firmware button handler FUN_6001961E(ctx, button id)
LASTSTEP = 0x1A
INSTBTN = lambda i: 0x21 + {RS: HC, HC: RS}.get(i, i)   # buttons 0x26 = HC, 0x27 = RS [unit]
def pad(n, *buttons):
    """Press step pad n (1..16) with these buttons held; returns what the stubs logged."""
    held.clear(); held.update(buttons); log.clear()
    w32(0x6007ECE8 + 0xC, 0)
    call(0x6001961E, 0x70002000, n - 1)
    held.clear()
    return list(log)
lens = lambda: list(uc.mem_read(S["poly_len"], 11))
expect("LAST STEP + pad: pattern last step, as before", pad(12, LASTSTEP), [("set_last", 11)])
expect("pad alone: nothing set", pad(12), [])
expect("LAST STEP + CH + pad 3: CH length 3, shown", pad(3, LASTSTEP, INSTBTN(CH)), [("text", "L  3")])
expect("... pattern last step untouched, lengths", lens(), [0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0])
expect("LAST STEP + RS + pad 5", pad(5, LASTSTEP, INSTBTN(RS)), [("text", "L  5")])
expect("RS button is 0x27 (hardware test 2)", (INSTBTN(RS), lens()[RS], lens()[HC]), (0x27, 5, 0))
expect("LAST STEP + BD + SD + pad 12: both set", pad(12, LASTSTEP, INSTBTN(BD), INSTBTN(SD)), [("text", "L 12")])
expect("same gesture again: back to the pattern length", pad(12, LASTSTEP, INSTBTN(BD), INSTBTN(SD)), [("text", "LOFF")])
expect("lengths after the gestures", lens(), [0, 0, 0, 0, 0, 5, 0, 3, 0, 0, 0])

setup()
pw(POS, 15)                                    # as after a stop: the next advance plays step 0
m = play(40)
expect("BD (no length) follows the 16-step pattern", fired(m, BD), [0, 4, 8, 12, 16, 20, 24, 28, 32, 36])
expect("CH length 3 plays every 3rd step across pattern loops", fired(m, CH), list(range(0, 40, 3)))
expect("RS length 5 plays its steps 1-2 of every 5", fired(m, RS), [t for t in range(40) if t % 5 < 2])
expect("firmware position still follows the pattern", pr(POS), 39 % 16)
expect("masks restored after the call", [pr(INST + BD), pr(INST + CH), pr(INST + RS), pr(ACC + CH)],
       [bits(0, 4, 8, 12), bits(0), bits(0, 1), bits(0)])

# Restart: heads go back to 0 at start, even in the middle of a cycle
call(S["poly_run"], P, 0, 0)                   # stop (the firmware sets the position to LAST)
pw(POS, 15)
call(S["poly_run"], P, 0, 1)
m = play(7)
expect("after stop/start: CH from its step 0 again", fired(m, CH), [0, 3, 6])

# Pattern shorter than 16 steps: CH keeps its own cycle
setup(last=7)
pw(POS, 7)
m = play(24)
expect("LAST = 8 steps: BD follows the pattern", fired(m, BD), [0, 4, 8, 12, 16, 20])
expect("LAST = 8 steps: CH still every 3", fired(m, CH), list(range(0, 24, 3)))

# Counter-0 path: the sequencer sets LAST to 0 so the advance wraps to step 0
setup()
pw(POS, 15); play(5)                           # heads: CH at 4 % 3 = 1
pw(LAST, 0)
mm = call(S["poly_trig"], P, -1, 0)
expect("forced wrap: firmware plays step 0, CH head keeps counting (5 % 3 != 0)", (pr(POS), mm >> CH & 1, mm >> BD & 1), (0, 0, 1))
pw(LAST, 15)

# A panel edit during the trigger wins over the restore
setup()
pw(POS, 15)
during.append(lambda: pw(INST + CH, bits(0, 2)))
play(1)
expect("mask changed during the call is kept", pr(INST + CH), bits(0, 2))

# Scatter active: the step order is the firmware's, poly does not remap
setup(scatter=0)
uc.mem_write(P + 0x1D8, bytes([4]))            # scatter table length 4
uc.mem_write(P + 0x1DC, bytes([0, 1, 2, 3]))
pw(POS, 15)
m = play(8)
expect("scatter: CH plays as written (step 0 of the 4-step order)", fired(m, CH), [0, 4])

# Flam hit (explicit step, flam = 1): uses the heads of the last advance
setup()
pw(FLAM + CH, bits(0))
pw(POS, 15); play(4)                           # last advance: step 3, CH head 3 % 3 = 0
mm = call(S["poly_trig"], P, 3, 1)
expect("flam at step 3: CH flam follows its own head", mm >> CH & 1, 1)
mm = call(S["poly_trig"], P, 3, 1)
expect("flam does not advance the heads", mm >> CH & 1, 1)
expect("flam does not move the firmware position", pr(POS), 3)

print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
