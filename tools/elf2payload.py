#!/usr/bin/env python3
"""Turn a linked payload ELF into JSON for tr8patch.py: allocated sections (NOBITS as zeros) + symbols.
Sections named .ram* are patch RAM outside the image (zeroed at boot by the payload): they are
listed under "ram" but not written into the image."""
import json, struct, sys

def main(path, *syms):
    e = open(path, "rb").read()
    shoff, = struct.unpack_from("<I", e, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", e, 0x2E)
    sh = [struct.unpack_from("<10I", e, shoff + i * shentsize) for i in range(shnum)]
    strtab = lambda off, tab: e[tab + off:e.index(b"\0", tab + off)].decode()
    shstr = sh[shstrndx][4]
    regions, symbols, ram = [], {}, []
    for s in sh:
        name, typ, flags, addr, off, size = s[0], s[1], s[2], s[3], s[4], s[5]
        if flags & 2 and size and strtab(name, shstr).startswith(".ram"):
            ram.append({"section": strtab(name, shstr), "addr": addr, "size": size})
        elif flags & 2 and size:                          # SHF_ALLOC
            data = bytes(size) if typ == 8 else e[off:off + size]   # 8 = NOBITS
            regions.append({"section": strtab(name, shstr), "addr": addr, "data": data.hex()})
        if typ == 2:                                      # SYMTAB
            link = sh[s[6]][4]
            for i in range(size // 16):
                st_name, value, _, info, _, _ = struct.unpack_from("<IIIBBH", e, off + i * 16)
                n = strtab(st_name, link) if st_name else ""
                if n in syms: symbols[n] = value
    missing = set(syms) - set(symbols)
    if missing: sys.exit(f"missing symbols: {missing}")
    out = {"regions": regions, "symbols": symbols}
    if ram:
        out["ram"] = ram
    json.dump(out, sys.stdout, indent=1)

if __name__ == "__main__":
    main(*sys.argv[1:])
