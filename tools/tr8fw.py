#!/usr/bin/env python3
"""Roland TR-8 firmware container tool (TR8_UPD.BIN, v1.61 layout).

  tr8fw.py info    TR8_UPD.BIN                     list modules, verify checksums and trailer
  tr8fw.py extract TR8_UPD.BIN OUTDIR              decompress modules + build ELF wrappers
  tr8fw.py pack    TR8_UPD.BIN MODULE NEW.bin OUT  recompress a module (updater|appA|appB),
                                                   fix its header (size, byte-sum), write OUT

Layout (see docs/FINDINGS.md): a raw 4 MiB flash image (file offset = flash offset)
followed by a 16-byte trailer {first block, last block, block size, image size}.
The updater only writes blocks first..last (0x30..0x3DF in v1.61).
Each compressed module starts with a 0x40-byte header:
  +0x00 name[0x28]  ASCII, e.g. "TR-8:Appli      18-0926_11:19:431.610384"
  +0x28 u32 load addr (0x60000000)   +0x2c u32 header size (0x40)
  +0x30 u32 compressed size          +0x34 u32 byte-sum of compressed payload
  +0x38 u32 dest addr                +0x3c u32 decompressed size
Payload = Okumura LZSS (4096 ring, init pos 0xFEE, flag bit 1 = literal).
"""
import struct, sys, os

MODULES = (("updater", 0x8000), ("appA", 0x30000), ("appB", 0x280000))

def lzss(src, dsize):
    ring = bytearray(4096); r = 0xFEE; out = bytearray(); i = 0; flags = 0
    while len(out) < dsize and i < len(src):
        flags >>= 1
        if not flags & 0x100:
            flags = src[i] | 0xFF00; i += 1
        if flags & 1:
            c = src[i]; i += 1
            out.append(c); ring[r] = c; r = (r + 1) & 0xFFF
        else:
            b0, b1 = src[i], src[i + 1]; i += 2
            pos = b0 | ((b1 & 0xF0) << 4); ln = (b1 & 0xF) + 2
            for k in range(ln + 1):
                if len(out) >= dsize: break
                c = ring[(pos + k) & 0xFFF]
                out.append(c); ring[r] = c; r = (r + 1) & 0xFFF
    return bytes(out), i

def lzss_compress(data):
    """Greedy LZSS encoder compatible with lzss() and the boot loader.
    Matches stay within the last 4096-18 bytes, so the ring never wraps onto them."""
    from collections import defaultdict
    MAXD, MAXL = 4096 - 18, 18
    heads = defaultdict(list); out = bytearray(); i = 0; n = len(data)
    def add(j):
        if j + 3 <= n:
            lst = heads[data[j:j + 3]]; lst.append(j)
            if len(lst) > 48: del lst[0]
    while i < n:
        flagpos = len(out); out.append(0); flag = 0
        for bit in range(8):
            if i >= n: break
            best_len = best_j = 0
            if i + 3 <= n:
                for j in reversed(heads.get(data[i:i + 3], ())):
                    if i - j > MAXD: break
                    l = 3; maxl = min(MAXL, n - i)
                    while l < maxl and data[j + l] == data[i + l]: l += 1
                    if l > best_len:
                        best_len, best_j = l, j
                        if l == maxl: break
            if best_len >= 3:
                pos = (0xFEE + best_j) & 0xFFF
                out += bytes([pos & 0xFF, ((pos >> 4) & 0xF0) | (best_len - 3)])
                for k in range(best_len): add(i + k)
                i += best_len
            else:
                flag |= 1 << bit; out.append(data[i]); add(i); i += 1
        out[flagpos] = flag
    return bytes(out)

def parse(img, base):
    name = img[base:base + 0x28].split(b"\0")[0].decode("latin1")
    load, hsz, csz, csum, dest, dsz = struct.unpack("<6I", img[base + 0x28:base + 0x40])
    payload = img[base + hsz:base + hsz + csz]
    return dict(name=name, load=load, hsz=hsz, csz=csz, csum=csum, dest=dest, dsz=dsz,
                payload=payload, sum_ok=(sum(payload) & 0xFFFFFFFF) == csum)

def mkelf(data, base, entry):
    eh = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\0" * 8
    eh += struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, entry, 52, 0, 0x05000200, 52, 32, 1, 0, 0, 0)
    ph = struct.pack("<IIIIIIII", 1, 0x1000, base, base, len(data), len(data), 5, 0x1000)
    out = eh + ph
    return out + b"\0" * (0x1000 - len(out)) + data

def trailer(img):
    first, last, bsz, total = struct.unpack("<4I", img[-16:])
    return first, last, bsz, total

def pack(img, key, new, out_path):
    base = dict(MODULES)[key]
    m = parse(img, base)
    comp = lzss_compress(new)
    chk, used = lzss(comp, len(new))
    assert chk == new and used == len(comp), "compressor round-trip failed"
    nxt = sorted(b for _, b in MODULES if b > base)
    limit = (nxt[0] if nxt else len(img) - 16) - base - m["hsz"]
    first, last, bsz, total = trailer(img)
    if base + m["hsz"] + len(comp) > (last + 1) * bsz:
        sys.exit("module would end beyond the last block the updater writes")
    if len(comp) > limit:
        sys.exit(f"compressed module too big: 0x{len(comp):x} > 0x{limit:x}")
    img = bytearray(img)
    hdr = bytearray(img[base:base + 0x40])
    struct.pack_into("<I", hdr, 0x30, len(comp))
    struct.pack_into("<I", hdr, 0x34, sum(comp) & 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 0x3C, len(new))
    region_end = base + m["hsz"] + max(len(comp), m["csz"])
    img[base:base + 0x40] = hdr
    img[base + m["hsz"]:region_end] = comp + b"\xff" * (region_end - base - m["hsz"] - len(comp))
    open(out_path, "wb").write(img)
    print(f"{key}: csz 0x{m['csz']:x} -> 0x{len(comp):x}, dsz 0x{len(new):x}, sum 0x{sum(comp) & 0xFFFFFFFF:08x}")

def main():
    if len(sys.argv) < 3: sys.exit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    img = open(path, "rb").read()
    if cmd == "pack":
        return pack(img, sys.argv[3], open(sys.argv[4], "rb").read(), sys.argv[5])
    first, last, bsz, total = trailer(img)
    print(f"trailer: blocks 0x{first:x}..0x{last:x} x 0x{bsz:x} (flash 0x{first*bsz:x}..0x{(last+1)*bsz-1:x}), image 0x{total:x}"
          f" {'OK' if total == len(img) - 16 else 'BAD'}")
    for key, base in MODULES:
        m = parse(img, base)
        out, used = lzss(m["payload"], m["dsz"])
        ok = len(out) == m["dsz"] and used == m["csz"]
        print(f"{key:8s} @0x{base:06x} {m['name']!r} load=0x{m['load']:08x} "
              f"csz=0x{m['csz']:x} dsz=0x{m['dsz']:x} sum={'OK' if m['sum_ok'] else 'BAD'} lzss={'OK' if ok else 'BAD'}")
        if cmd == "extract":
            od = sys.argv[3]; os.makedirs(od, exist_ok=True)
            open(f"{od}/{key}.bin", "wb").write(out)
            open(f"{od}/{key}.elf", "wb").write(mkelf(out, m["dest"], m["dest"] | 1))
    if cmd == "extract":
        open(f"{od}/boot.bin", "wb").write(img[0x30:0x33AC])  # vector table + boot code, base 0x01000000
        open(f"{od}/boot.elf", "wb").write(mkelf(img[0x30:0x33AC], 0x01000000, 0x01000BD9))

if __name__ == "__main__":
    main()
