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

# Per-instrument pattern length (patches/poly/poly.c, docs/POLY.md).
# Uses the first motion region alone: cannot be combined with motion.
PATCHES["poly"] = {
    "doc": "Per-instrument length: hold LAST STEP + instrument, press a pad (docs/POLY.md)",
    "payload": "patches/poly/payload.json",
    "allowed": [(0x60011150, 0x60011464)],
    "keep": [(0x60011464, 0x60011484)],
    "sites": [
        (0x60011E00, thumb_bl(0x60011E00, 0x6001114E), "nop"),          # dev dump 1 (frees the cave)
        (0x60011E04, thumb_bl(0x60011E04, 0x600113B2), "nop"),          # dev dump 2 (frees the cave)
        (0x60009800, thumb_bl(0x60009800, 0x600262F2), "poly_trig"),    # step advance (pre-step path)
        (0x6000985A, thumb_bl(0x6000985A, 0x600262F2), "poly_trig"),    # step advance
        (0x60009884, thumb_bl(0x60009884, 0x600262F2), "poly_trig"),    # step advance at counter 0
        (0x60009A50, thumb_bl(0x60009A50, 0x600262F2), "poly_trig"),    # delayed flam hit
        (0x6000966E, thumb_bl(0x6000966E, 0x60026894), "poly_run"),     # sequencer start
        (0x600096AE, thumb_bl(0x600096AE, 0x60026894), "poly_run"),     # sequencer stop
        (0x60019A10, thumb_bl(0x60019A10, 0x6001B8D6), "poly_last"),    # pad with LAST STEP held
        (0x60016438, thumb_bl(0x60016438, 0x6001774E), "poly_led"),     # step LEDs, LAST STEP view
    ],
}

# Bar chain (patches/chain/chain.c, docs/CHAIN.md).
# Up to eight bars per pattern, each with its own A and B step set: A/B + pad 1..8 selects the bar
# and grows that side's sequence, A+B + pad sets both lengths. Same free regions as motion and
# poly: standalone. The 128-byte bar index lives in patch RAM, so the RTOS pool start moves by
# 64 KB (the motion-poly move).
PATCHES["chain"] = {
    "doc": "Bar chain: A/B + pad 1..8 selects a bar and sets its side's length, A+B + pad both (docs/CHAIN.md)",
    "payload": "patches/chain/payload.json",
    "allowed": [(0x60011150, 0x60011464), (0x60011488, 0x60011BB6)],
    "keep": [(0x60011464, 0x60011484)],
    "sites": [
        (0x60011E00, thumb_bl(0x60011E00, 0x6001114E), "nop"),          # dev dump 1 (frees the cave)
        (0x60011E04, thumb_bl(0x60011E04, 0x600113B2), "nop"),          # dev dump 2 (frees the cave)
        (0x60009614, thumb_bl(0x60009614, 0x6000E404), "chain_var"),    # restart: variation of the pass
        (0x600098CA, thumb_bl(0x600098CA, 0x600095F0), "chain_wrap"),   # pattern wrap: mark it as a wrap
        (0x60016C44, thumb_bl(0x60016C44, 0x60016386), "chain_view"),  # panel paints the step pads
        (0x60013842, thumb_bl(0x60013842, 0x60013B34), "chain_press"),  # button press: before the screen
        (0x600137D2, thumb_bl(0x600137D2, 0x60013B56), "chain_release"),# matching release of that pad
        (0x60017748, thumb_bl(0x60017748, 0x6004BB4C), "chain_led4"),  # raw pad setter
        (0x6001776C, thumb_bl(0x6001776C, 0x6004BB4C), "chain_led4"),  # palette pad setter
        (0x60017E18, thumb_bl(0x60017E18, 0x6004BB4C), "chain_led4"),  # raw pad setter (copy)
        (0x60017E3A, thumb_bl(0x60017E3A, 0x6004BB4C), "chain_led4"),  # palette pad setter (copy)
        (0x6001B7F4, thumb_bl(0x6001B7F4, 0x6000FC78), "chain_commit"), # pattern save: store the bar, not the slot
        (0x600104A8, struct.pack("<I", 0x60280988), struct.pack("<I", 0x60290988)),  # RTOS pool +64 KB: patch RAM
    ],
}

# Hardware probe: same sites, display only (patches/chain/probe.c, docs/CHAIN.md). It keeps the
# LAST STEP fallback dropped in the real build, to show what that branch sees.
PATCHES["chain-probe"] = dict(PATCHES["chain"],
                              doc="Bar chain hardware probe: pads and modifiers on the display (no edits)",
                              payload="patches/chain/payload_probe.json",
                              sites=[s for s in PATCHES["chain"]["sites"]
                                     if s[2] != "chain_view" and s[0] != 0x600104A8] + [
                                  (0x600199F6, thumb_bl(0x600199F6, 0x60013168), "chain_pad"),
                              ])

# Motion + poly together (patches/combo). Code in both developer-dump regions; tables in patch
# RAM: the RTOS pool start moves from 0x60280988 to 0x60290988 (64 KB), zeroed by ram_init at boot.
_motion_sites = [s for s in PATCHES["motion"]["sites"] if s[2] != "nop"]
_poly_sites = [s for s in PATCHES["poly"]["sites"] if s[2] != "nop"]
PATCHES["motion-poly"] = {
    "doc": "Motion recording + per-instrument length together (docs/COMBO.md)",
    "payload": "patches/combo/payload.json",
    "allowed": PATCHES["motion"]["allowed"],
    "keep": PATCHES["motion"]["keep"],
    "sites": PATCHES["motion"]["sites"][:2] + _motion_sites + _poly_sites + [
        (0x60010482, thumb_bl(0x60010482, 0x60010430), "ram_init"),     # pool setup: zero patch RAM first
        (0x600104A8, struct.pack("<I", 0x60280988), struct.pack("<I", 0x60290988)),  # RTOS pool start +64 KB
    ],
}

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
        if isinstance(repl, bytes):                     # raw replacement (a literal)
            app[o:o + 4] = repl
        else:
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
    for r in pay.get("ram", []):
        print(f"  {r['section']:8s} 0x{r['addr']:08x} {r['size']} bytes (patch RAM, not in the image)")
    for addr, _, repl in spec["sites"]:
        print(f"  site     0x{addr:08x} -> {repl.hex() if isinstance(repl, bytes) else repl}")
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
