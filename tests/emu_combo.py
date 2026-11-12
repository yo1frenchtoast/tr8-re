#!/usr/bin/env python3
"""Boot part of the motion + poly patch (needs: pip install unicorn).

  python3 tests/emu_combo.py work/patched_combo/appA.bin

The motion and poly behaviour of the same image is tested by emu_motion.py and emu_poly.py
with --payload patches/combo/payload.json. This test covers what only the combined patch does:
the RTOS pool start moved by 64 KB, and ram_init zeroing the patch RAM before the pool setup.
"""
import struct, sys, json, os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pay = json.load(open(os.path.join(ROOT, "patches/combo/payload.json")))
S = pay["symbols"]
app = open(sys.argv[1], "rb").read()
uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)
uc.mem_write(0x60000000, app)
uc.mem_map(0x70000000, 0x10000)
RET = 0x7000F000
uc.mem_write(RET, b"\xfe\xe7")
r32 = lambda a: struct.unpack("<I", uc.mem_read(a, 4))[0]

pool = []                                       # arguments seen by the RTOS pool creation thunk
def hook(uc, addr, size, _):
    if addr == 0x6004BADE:                      # thunk to the RTOS: create pool from {u16 id, size, base}
        sp = uc.reg_read(UC_ARM_REG_R0)
        _, size, base = struct.unpack("<HxxII", uc.mem_read(sp, 12))
        pool.append((hex(base), hex(base + size)))
        uc.reg_write(UC_ARM_REG_R0, 0)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
uc.hook_add(UC_HOOK_CODE, hook)

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"  (want {want})"))

(ram,) = pay["ram"]
lo, hi = ram["addr"], ram["addr"] + ram["size"]
expect("patch RAM is between the firmware bss and the moved pool", 0x60280988 <= lo and hi <= 0x60290988, True)
expect("motion table and poly state are in patch RAM",
       all(lo <= S[n] < hi for n in ("poly_pos",)), True)
uc.mem_write(lo - 16, b"\xAA" * (hi - lo + 32))  # junk, as SDRAM after power-on
# run the firmware's own boot function 0x6001047C up to the pool setup and our hook
uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
uc.reg_write(UC_ARM_REG_LR, RET | 1)
uc.emu_start(0x60010482 | 1, 0x60010486, count=200000)       # the patched "bl" only
expect("patch RAM zeroed at boot", bytes(uc.mem_read(lo, hi - lo)) == bytes(hi - lo), True)
expect("bytes around patch RAM untouched", bytes(uc.mem_read(lo - 16, 16)) + bytes(uc.mem_read(hi, 16)), b"\xAA" * 32)
expect("RTOS pool now 0x60290988 .. end of SDRAM", pool, [("0x60290988", "0x62000000")])
expect("startup stack literal unchanged", hex(r32(0x6012A2FC)), "0x60280988")
print("FAILED" if fails else "ALL PASS"); sys.exit(1 if fails else 0)
