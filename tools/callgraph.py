#!/usr/bin/env python3
"""Who calls what in the TR-8 application, from your own local analysis files.

  python3 -I tools/callgraph.py callers 0x6000989C       # call sites, with their function
  python3 -I tools/callgraph.py up 0x600095F0 [depth]     # caller tree (default depth 6)
  python3 -I tools/callgraph.py callees 0x600099B6        # what a function calls
  python3 -I tools/callgraph.py refs 0x60008F5C           # literal pointers to it (tables, vtables)
  python3 -I tools/callgraph.py func 0x600090D0           # the function that contains an address

Use it before you hook a site: a function with more than one caller can run in more than one
task (docs/DEVELOPING.md section 3, "Task context"). A function with no direct caller is reached
through a pointer: `refs` finds the literal (Thumb address + 1), for example a task table entry.

Inputs, all produced locally from your own copy of Roland's file (README "Write your own
feature"); nothing here is committed:
  work/appA.dis      llvm-objdump -d --triple=thumbv7m work/appA.elf > work/appA.dis
  analysis/appA.c    tools/analyze.sh (function starts, "//==== FUN_x @ addr")
  work/appA.bin      tools/tr8fw.py extract (for `refs`)
The index is cached in work/callgraph.pkl and rebuilt when appA.dis changes.
"""
import bisect, os, pickle, re, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIS = os.path.join(ROOT, "work", "appA.dis")
CSRC = os.path.join(ROOT, "analysis", "appA.c")
BIN = os.path.join(ROOT, "work", "appA.bin")
CACHE = os.path.join(ROOT, "work", "callgraph.pkl")
BASE = 0x60000000

CALL = re.compile(r"^\s*([0-9a-f]{8}):.*?\t(bl|blx|b\.w|b)\s+0x([0-9a-f]+)")


def build():
    sites = []                                  # (site, target, kind)
    with open(DIS) as f:
        for line in f:
            m = CALL.match(line)
            if m:
                sites.append((int(m.group(1), 16), int(m.group(3), 16), m.group(2)))
    starts = []
    if os.path.exists(CSRC):
        with open(CSRC) as f:
            starts = sorted(int(m.group(1), 16) for m in re.finditer(r"^//==== \S+ @ ([0-9a-f]+)", f.read(), re.M))
    # A short "b" stays inside its function (loops, if/else); keep it only when it lands on a
    # known function start, which is a tail call.
    known = set(starts)
    sites = [s for s in sites if s[2] != "b" or s[1] in known]
    return {"mtime": os.path.getmtime(DIS), "sites": sites, "starts": starts}


def index():
    if not os.path.exists(DIS):
        sys.exit(f"missing {os.path.relpath(DIS, ROOT)}: see the docstring (python3 -I tools/callgraph.py)")
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            idx = pickle.load(f)
        if idx.get("mtime") == os.path.getmtime(DIS):
            return idx
    idx = build()
    with open(CACHE, "wb") as f:
        pickle.dump(idx, f)
    return idx


def func_of(idx, addr):
    s = idx["starts"]
    i = bisect.bisect_right(s, addr) - 1
    return s[i] if i >= 0 else None


def name(idx, addr):
    f = func_of(idx, addr)
    if f is None:
        return "?"
    return f"FUN_{f:08X}" + (f"+0x{addr - f:X}" if addr != f else "")


def callers(idx, target):
    return [(s, k) for s, t, k in idx["sites"] if t == target]


def cmd_callers(idx, a):
    hits = callers(idx, a)
    for s, k in hits:
        print(f"0x{s:08X}  {k:<4} in {name(idx, s)}")
    if not hits:
        print("no direct call: try `refs` (called through a pointer)")


def cmd_up(idx, a, depth=6):
    seen = set()

    def walk(t, d):
        print("  " * d + f"0x{t:08X}" + ("  (seen)" if t in seen else ""))
        if t in seen or d >= depth:
            return
        seen.add(t)
        for f in sorted({func_of(idx, s) for s, _ in callers(idx, t)} - {None}):
            walk(f, d + 1)
    walk(func_of(idx, a) or a, 0)


def cmd_callees(idx, a):
    f = func_of(idx, a)
    s = idx["starts"]
    i = s.index(f) if f in s else -1
    end = s[i + 1] if 0 <= i < len(s) - 1 else f + 0x1000
    for site, t, k in idx["sites"]:
        if f <= site < end:
            print(f"0x{site:08X}  {k:<4} -> 0x{t:08X}")


def cmd_refs(_idx, a):
    data = open(BIN, "rb").read()
    want = {a | 1, a & ~1}
    hits = [BASE + i for i in range(0, len(data) - 3, 2) if struct.unpack_from("<I", data, i)[0] in want]
    for h in hits:
        print(f"0x{h:08X}  holds 0x{struct.unpack_from('<I', data, h - BASE)[0]:08X}")
    if not hits:
        print("no literal found")


def main(argv):
    if len(argv) < 3 or argv[1] not in ("callers", "up", "callees", "refs", "func"):
        sys.exit(__doc__)
    a = int(argv[2], 16)
    idx = index()
    if argv[1] == "func":
        print(name(idx, a))
    elif argv[1] == "up":
        cmd_up(idx, a, int(argv[3]) if len(argv) > 3 else 6)
    else:
        {"callers": cmd_callers, "callees": cmd_callees, "refs": cmd_refs}[argv[1]](idx, a)


if __name__ == "__main__":
    main(sys.argv)
