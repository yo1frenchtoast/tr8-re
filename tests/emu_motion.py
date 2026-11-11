#!/usr/bin/env python3
"""Emulate the motion payload inside the patched v1.61 application (needs: pip install unicorn).

  python3 tests/emu_motion.py work/patched/appA.bin          # normal build
  python3 tests/emu_motion.py work/patched_diag/appA.bin --diag
  python3 tests/emu_motion.py work/patched_hold/appA.bin --hold

The firmware functions the payload calls are replaced by stubs that log their arguments.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = "--diag" in sys.argv
HOLD = "--hold" in sys.argv
pay = json.load(open(os.path.join(ROOT, "patches/motion/payload%s.json" % ("_diag" if DIAG else "_hold" if HOLD else ""))))
KNOB, STEP = pay["symbols"]["motion_knob"], pay["symbols"]["motion_step"]
app = open(sys.argv[1], "rb").read()

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)            # application + bss
uc.mem_write(0x60000000, app)
uc.mem_map(0x70000000, 0x10000)                # stack + return trap
RET = 0x7000F000
uc.mem_write(RET, b"\xfe\xe7")                 # b .

calls = []
STUBS = {0x60013242: "orig_knob", 0x6001A27C: "modal", 0x60013F6A: "apply", 0x60013168: "held", 0x6000978E: "orig_step", 0x60000CC0: "post", 0x6001B12E: "setup_get"}
setup0 = [0]
held = [1]                                     # TR-REC button held (hold build)                                   # HMI Setup[0]: 0 = TR-REC, 2 = INST PLAY, 3 = INST REC
def hook(uc, addr, size, _):
    if addr in STUBS:
        r = [uc.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        if STUBS[addr] == "orig_knob":                      # (screen, ev*) -> log screen, id, value
            ev = struct.unpack("<3h", uc.mem_read(r[1], 6))
            calls.append(("orig_knob", [r[0], ev[1], ev[2]]))
            uc.reg_write(UC_ARM_REG_R0, 0)
        elif STUBS[addr] == "modal":                         # FUN_6001a27c: no modal state
            uc.reg_write(UC_ARM_REG_R0, 0)
        elif STUBS[addr] == "held":                          # FUN_60013168(button id)
            assert r[0] == 0x11, r
            uc.reg_write(UC_ARM_REG_R0, held[0])
        elif STUBS[addr] == "setup_get":
            assert r[:2] == [0x60149F38, 0], r
            uc.reg_write(UC_ARM_REG_R0, setup0[0])
        else:
            calls.append((STUBS[addr], r))
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)

def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v & 0xFFFFFFFF)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    calls.clear()
    uc.emu_start(fn | 1, RET, count=100000)
    return list(calls)

w8  = lambda a, v: uc.mem_write(a, bytes([v]))
w32 = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
def state(running, step, var=0, mode=0, redirect=0, rec=0, half=0):
    """step = pattern step; the firmware counter at +0x18 counts half steps.
    rec = Setup[0] (0 = TR-REC); in the hold build rec != 0 means "TR-REC not held"."""
    setup0[0] = rec
    held[0] = 1 if rec == 0 else 0
    w8(0x6007E102, running); w32(0x6007E118, 2 * step + half); w32(0x6012FA74, var)
    w32(0x6007E574, mode); w8(0x6007E580, redirect)
EV = 0x70001000
def knob(i, v):
    """HMI knob event {10, id, value} as the event-10 handler passes it to FUN_60013242."""
    uc.mem_write(EV, struct.pack("<3h", 10, i, v))
    return [(n, a[:3] if n == "orig_knob" else a[:2]) for n, a in call(KNOB, 0x1234, EV)]
M_LAST = pay["symbols"]["m_last"]
def step(again=False):
    """One per-step call. again=True: second call for the same step (keeps the dedupe state)."""
    if not again:
        w8(M_LAST, 0xFF)
    return [(n, a[:2]) for n, a in call(STEP, 0x5678, 7) if n != "orig_step"]
step_calls_orig = lambda: [(n, a[:2]) for n, a in call(STEP, 0x5678, 7) if n == "orig_step"]

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))

state(0, 0)
expect("stopped: knob goes to the original handler", knob(5, 100), [("orig_knob", [0x1234, 5, 100])])
state(1, 0)
expect("running: step calls the original per-step function", step_calls_orig(), [("orig_step", [0x5678, 7])])
state(1, 3); knob(5, 100)
state(1, 4); expect("hold 1: lane just touched, no replay", step(), [])
state(1, 5); expect("hold 2: no replay", step(), [])
state(1, 3); expect("replay at recorded step", step(), [("post", [5, 100])])
expect("echo of replay is not recorded", knob(5, 100), [("orig_knob", [0x1234, 5, 100])])
state(1, 4); expect("echo did not re-arm hold, nothing at step 4", step(), [])
state(1, 3); expect("replay again next pass", step(), [("post", [5, 100])])
state(1, 3, var=1); expect("variation B has its own slots", step(), [])
state(1, 3, var=1); knob(7, 200); knob(5, 10)
state(1, 4, var=1); step(); state(1, 5, var=1); step()
state(1, 3, var=1); expect("two lanes replayed in B", step(), [("post", [5, 10]), ("post", [7, 200])])
state(1, 3, var=0); expect("A slot of lane 5 still intact", step(), [("post", [5, 100])])
state(0, 0); knob(5, 1)
state(1, 3); expect("knob while stopped erases its lane", step(), [])
state(1, 3, var=1); expect("erase covers A and B", step(), [("post", [7, 200])])
state(1, 3); expect("out-of-range control id passes through", knob(60, 1), [("orig_knob", [0x1234, 60, 1])])
state(0, 3); expect("stopped: no replay", step(), [])
# Integration: run the firmware's own HMI event-10 handler (0x60013892), not the payload directly
def hmi_knob(i, v):
    uc.mem_write(EV, struct.pack("<3h", 10, i, v))
    return [(n, a[:3]) for n, a in call(0x60013892, EV)]
state(1, 9); expect("firmware knob handler -> payload -> screen -> global table",
                    [(n, x[:2]) for n, x in hmi_knob(30, 99)], [("orig_knob", [0, 30]), ("apply", [30, 99])])
state(1, 10); step(); state(1, 11); step()
state(1, 9); expect("knob seen by the firmware handler is replayed", step(), [("post", [30, 99])])
# Firmware step details
state(1, 12, half=1); knob(20, 33)              # knob between two steps: counter is odd
state(1, 13); step(); state(1, 14); step()       # hold
state(1, 12); expect("half-step counter: recorded at step 12, replayed at 12", step(), [("post", [20, 33])])
expect("second call for the same step does not replay again", step(again=True), [])
state(1, 4); step()
state(1, 12); expect("next pass replays once", step(), [("post", [20, 33])])
state(0, 0); step(again=True); state(1, 12); expect("restart: replay at the same step after a stop", step(again=True), [("post", [20, 33])])
if not DIAG:
    # record condition: TR-REC mode (default build) or TR-REC held (hold build)
    state(1, 8, rec=2); knob(11, 77)
    state(1, 9, rec=2); step(); state(1, 10, rec=2); step()
    state(1, 8, rec=2); expect("record off (other mode / TR-REC not held): knob not recorded", step(), [])
    state(1, 3); knob(5, 100)                      # re-record lane 5 at step 3 in TR-REC
    state(1, 4); step(); state(1, 5); step()
    state(1, 3, mode=4, redirect=1); expect("boot mode and redirect flag are not tested any more", step(), [("post", [5, 100])])
    state(1, 3, rec=3); expect("record off: existing motion still replayed", step(), [("post", [5, 100])])
    state(1, 3, rec=3); knob(5, 42)
    state(1, 3, rec=3); expect("record off: knob neither overwrites nor holds the lane", step(), [("post", [5, 100])])
    state(0, 0, rec=2); knob(5, 1)
    state(1, 3); expect("stopped, record off: lane not erased", step(), [("post", [5, 100])])
    state(0, 0, rec=0); knob(5, 1)
    state(1, 3); expect("stopped, record on: lane erased", step(), [])
else:
    state(1, 8, rec=2, mode=4); knob(11, 77)
    state(1, 9, rec=2, mode=4); step(); state(1, 10); step()
    state(1, 8, rec=2, mode=4); expect("diag: records and replays in any mode", step(), [("post", [11, 77])])
print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
