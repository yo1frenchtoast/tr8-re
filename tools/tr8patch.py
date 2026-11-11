#!/usr/bin/env python3
"""Apply feature patches to a user-supplied Roland TR-8 v1.61 TR8_UPD.BIN.

  tr8patch.py TR8_UPD.BIN OUT.BIN [--patch NAME]   build a patched update file (default: motion)
  tr8patch.py TR8_UPD.BIN --check                  only verify that the input is supported
  tr8patch.py --list                               list the available patches

Patches that use the same hook sites (all motion-* variants) cannot be combined.

No Roland code is shipped here: the patcher reads the original file, checks it is exactly
the supported version, rewrites a few instructions, adds the payload and rebuilds the
module header (size and byte-sum) so that the official updater accepts it.
"""
import argparse, hashlib, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr8fw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x60000000
APPA_SHA256 = "3685edab8bbeaef8752df9ef08a73a9fd2a2e69ba8210016132f6d141f6b452e"  # v1.61, decompressed

def thumb_bl(src, dst):
    off = dst - (src + 4)
    assert -(1 << 24) <= off < (1 << 24) and off % 2 == 0
    s = (off >> 24) & 1; i1 = (off >> 23) & 1; i2 = (off >> 22) & 1
    j1 = (~i1 ^ s) & 1; j2 = (~i2 ^ s) & 1
    h1 = 0xF000 | (s << 10) | ((off >> 12) & 0x3FF)
    h2 = 0xD000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF)
    return struct.pack("<HH", h1, h2)

NOP_W = bytes.fromhex("aff30080")

PATCHES = {
    "motion": {
        "doc": "Motion recording: hold TR-REC to record, hold CLEAR to erase (docs/MOTION.md)",
        "payload": "patches/motion/payload.json",
        # free regions the payload may use, and ranges that must stay untouched
        "allowed": [(0x60011150, 0x60011464), (0x60011488, 0x60011BB6)],
        "keep": [(0x60011464, 0x60011484)],
        "sites": [
            # (address, original bytes, replacement: "nop" or a payload symbol to bl to)
            (0x60011E00, thumb_bl(0x60011E00, 0x6001114E), "nop"),          # dev dump 1 (frees the cave)
            (0x60011E04, thumb_bl(0x60011E04, 0x600113B2), "nop"),          # dev dump 2 (frees the cave)
            (0x600138C8, thumb_bl(0x600138C8, 0x60013242), "motion_knob"),  # HMI knob event -> screen
            (0x60009862, thumb_bl(0x60009862, 0x6000978E), "motion_step"),  # per step
            (0x60009808, thumb_bl(0x60009808, 0x6000978E), "motion_step"),  # per step (other scale path)
        ],
    },
}
# Diagnostic variant: same sites, payload built with -DMOTION_DIAG (records whatever the mode).
PATCHES["motion-diag"] = dict(PATCHES["motion"], doc="Motion recording, diagnostic build without mode conditions",
                              payload="patches/motion/payload_diag.json")
# Older rule: record while TR-REC mode is active, erase by turning a knob while stopped.
PATCHES["motion-mode"] = dict(PATCHES["motion"], doc="Motion recording, record in TR-REC mode (older rule)",
                              payload="patches/motion/payload_mode.json")
# Hardware probe: same sites, audible test of each link (patches/motion/probe.c, docs/MOTION.md).
PATCHES["motion-probe"] = dict(PATCHES["motion"], doc="Motion hooks hardware probe (no motion, audible test)",
                               payload="patches/motion/payload_probe.json")

def load_app(img):
    m = tr8fw.parse(img, dict(tr8fw.MODULES)["appA"])
    if not m["name"].startswith("TR-8:Appli      18-0926_11:19:43"):
        sys.exit(f"unsupported application module: {m['name']!r} (only v1.61 is supported)")
    if not m["sum_ok"]:
        sys.exit("application module byte-sum is wrong: corrupted input file")
    app, used = tr8fw.lzss(m["payload"], m["dsz"])
    if hashlib.sha256(app).hexdigest() != APPA_SHA256:
        sys.exit("application does not match the known v1.61 image (already patched, or another version)")
    return bytearray(app)

def check_container(img):
    first, last, bsz, total = tr8fw.trailer(img)
    if total != len(img) - 16 or (first, last, bsz) != (0x30, 0x3DF, 0x1000):
        sys.exit("unexpected trailer: not a TR-8 v1.61 TR8_UPD.BIN")
    for key, base in tr8fw.MODULES:
        if not tr8fw.parse(img, base)["sum_ok"]:
            sys.exit(f"module {key} byte-sum is wrong: corrupted input file")

def apply(app, spec):
    pay = json.load(open(os.path.join(ROOT, spec["payload"])))
    syms = pay["symbols"]
    for addr, orig, repl in spec["sites"]:
        o = addr - BASE
        if app[o:o + 4] != orig:
            sys.exit(f"unexpected bytes at 0x{addr:08x}: {app[o:o+4].hex()} (expected {orig.hex()})")
        app[o:o + 4] = NOP_W if repl == "nop" else thumb_bl(addr, syms[repl] & ~1)
    for r in pay["regions"]:
        a, data = r["addr"], bytes.fromhex(r["data"])
        if not any(lo <= a and a + len(data) <= hi for lo, hi in spec["allowed"]):
            sys.exit(f"payload section {r['section']} at 0x{a:08x} is outside the free regions")
        for lo, hi in spec["keep"]:
            if a < hi and lo < a + len(data):
                sys.exit(f"payload section {r['section']} overlaps a protected range")
        app[a - BASE:a - BASE + len(data)] = data
        print(f"  {r['section']:8s} 0x{a:08x} {len(data)} bytes")
    for addr, _, repl in spec["sites"]:
        print(f"  site     0x{addr:08x} -> {repl}")
    return app

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?"); ap.add_argument("output", nargs="?")
    ap.add_argument("--patch", action="append", choices=sorted(PATCHES), help="default: motion")
    ap.add_argument("--check", action="store_true", help="only verify the input file")
    ap.add_argument("--list", action="store_true", help="list the available patches")
    a = ap.parse_args()
    if a.list:
        for name, spec in PATCHES.items():
            print(f"{name:14s} {spec['doc']}")
        return
    if not a.input: ap.error("input file required")
    img = open(a.input, "rb").read()
    check_container(img)
    app = load_app(img)
    print("input: TR-8 v1.61 TR8_UPD.BIN, all checks OK")
    if a.check: return
    if not a.output: ap.error("output path required")
    for name in a.patch or ["motion"]:
        print(f"patch {name}: {PATCHES[name]['doc']}")
        app = apply(app, PATCHES[name])
    tr8fw.pack(img, "appA", bytes(app), a.output)
    out = open(a.output, "rb").read()
    check_container(out)
    print(f"written {a.output}: rename it to TR8_UPD.BIN and flash it as described in docs/UPDATE.md")

if __name__ == "__main__":
    main()
