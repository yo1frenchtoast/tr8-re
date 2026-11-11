#!/usr/bin/env python3
"""Emulate the hardware probe (patches/motion/probe.c) in the patched image.

  python3 tests/emu_probe.py work/patched_probe/appA.bin
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pay = json.load(open(os.path.join(ROOT, "patches/motion/payload_probe.json")))
STEP = pay["symbols"]["motion_step"]
uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000); uc.mem_write(0x60000000, open(sys.argv[1], "rb").read())
uc.mem_map(0x70000000, 0x10000); RET = 0x7000F000; uc.mem_write(RET, b"\xfe\xe7")
STUBS = {0x60013242: "screen", 0x6001A27C: "modal", 0x60013F6A: "apply", 0x6000978E: "orig_step", 0x60000CC0: "post"}
calls = []
def hook(uc, addr, size, _):
    if addr in STUBS:
        r = [uc.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1)]
        if STUBS[addr] != "modal": calls.append((STUBS[addr], r))
        uc.reg_write(UC_ARM_REG_R0, 0)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)
def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1), args): uc.reg_write(reg, v)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000); uc.reg_write(UC_ARM_REG_LR, RET | 1)
    calls.clear(); uc.emu_start(fn | 1, RET, count=100000); return list(calls)
EV = 0x70001000
def knob(i, v):
    uc.mem_write(EV, struct.pack("<3h", 10, i, v))
    return [n if n != "apply" else (n, a) for n, a in call(0x60013892, EV)]   # firmware event-10 handler
def state(running, step):
    uc.mem_write(0x6007E102, bytes([running])); uc.mem_write(0x6007E118, struct.pack("<I", 2 * step))
step = lambda: [(n, a) for n, a in call(STEP, 0x5678, 0) if n == "post"]
fails = 0
def expect(name, got, want):
    global fails; ok = got == want; fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))
state(0, 0); expect("stopped: knob swallowed", knob(5, 100), [])
state(1, 0); expect("running: knob goes to screen then global table", knob(5, 100), ["screen", ("apply", [5, 100])])
state(1, 1); expect("step 1: last knob posted with 255", step(), [("post", [5, 255])])
expect("same step again: nothing", step(), [])
state(1, 2); expect("step 2: posted with 0", step(), [("post", [5, 0])])
state(1, 3); knob(5, 255); expect("our 255 post does not change the probed control", step(), [("post", [5, 255])])
print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
