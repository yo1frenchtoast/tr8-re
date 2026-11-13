#!/usr/bin/env python3
"""Merge payload JSON files (tools/elf2payload.py output) into one.

  merge_payloads.py OUT.json IN.json [IN.json...]

Combined patches need the code of every part but one payload file per patch name, because the
tests and the web flasher read a single file. The parts were linked separately and do not share
address space except for identical duplicates (the bar chain's sites and the cave patches' are
disjoint, and their payload regions are too), so the merge is a union:

- regions: same address -> the bytes must be identical (the same section linked twice), otherwise
  they must not overlap at all;
- ram: same address -> same size;
- symbols: same name -> same value.

Nothing here links code: run the parts' build scripts first.
"""
import json, sys


def overlap(a, b):
    return a["addr"] < b["addr"] + len(b["data"]) // 2 and b["addr"] < a["addr"] + len(a["data"]) // 2


def main(out_path, *in_paths):
    if not in_paths:
        sys.exit("usage: merge_payloads.py OUT.json IN.json [IN.json...]")
    regions, ram, symbols = {}, {}, {}
    for path in in_paths:
        pay = json.load(open(path))
        for r in pay["regions"]:
            other = next((o for o in regions.values() if overlap(r, o)), None)
            if other is None:
                regions[r["addr"]] = dict(r)
            elif other["addr"] != r["addr"] or other["data"] != r["data"]:
                sys.exit(f"{path}: {r['section']} at 0x{r['addr']:08x} overlapping "
                         f"{other['section']} at 0x{other['addr']:08x}")
            # else: the same section, linked twice
        for r in pay.get("ram", []):
            old = ram.get(r["addr"])
            if old and old["size"] != r["size"]:
                sys.exit(f"{path}: patch RAM at 0x{r['addr']:08x} has two sizes")
            ram[r["addr"]] = dict(r)
        for name, value in pay["symbols"].items():
            if symbols.get(name, value) != value:
                sys.exit(f"{path}: symbol {name} has two values")
            symbols[name] = value
    merged = {
        "regions": [regions[a] for a in sorted(regions)],
        "symbols": dict(sorted(symbols.items())),
    }
    if ram:
        merged["ram"] = [ram[a] for a in sorted(ram)]
    json.dump(merged, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
