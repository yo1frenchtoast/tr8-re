#!/usr/bin/env python3
"""Roland TR-8 firmware container tool (TR8_UPD.BIN, v1.61 layout).

  tr8fw.py info    TR8_UPD.BIN            list modules and verify checksums
  tr8fw.py extract TR8_UPD.BIN OUTDIR     decompress modules + build ELF wrappers

Layout (see docs/FINDINGS.md): 0x10-byte prefix, then a 4 MiB flash image.
Each compressed module starts with a 0x40-byte header:
  +0x00 name[0x28]  ASCII, e.g. "TR-8:Appli      18-0926_11:19:431.610384"
  +0x28 u32 load addr (0x60000000)   +0x2c u32 header size (0x40)
  +0x30 u32 compressed size          +0x34 u32 byte-sum of compressed payload
  +0x38 u32 dest addr                +0x3c u32 decompressed size
Payload = Okumura LZSS (4096 ring, init pos 0xFEE, flag bit 1 = literal).
"""
import struct, sys, os

FLASH_PREFIX = 0x10
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
    """Greedy LZSS encoder, format-compatible with the decoder above (untested on hardware)."""
    ring = bytearray(4096); r = 0xFEE; out = bytearray(); i = 0
    while i < len(data):
        flagpos = len(out); out.append(0); flag = 0
        for bit in range(8):
            if i >= len(data): break
            best_len, best_pos = 0, 0
            maxl = min(18, len(data) - i)
            if maxl >= 3:
                for pos in range(4096):
                    l = 0
                    # simulate ring evolution while matching (overlap allowed by decoder)
                    tmp = bytearray(ring); rr = r
                    while l < maxl and tmp[(pos + l) & 0xFFF] == data[i + l]:
                        tmp[rr] = data[i + l]; rr = (rr + 1) & 0xFFF; l += 1
                    if l > best_len: best_len, best_pos = l, pos
                    if best_len == maxl: break
            if best_len >= 3:
                out += bytes([best_pos & 0xFF, ((best_pos >> 4) & 0xF0) | (best_len - 3)])
                for k in range(best_len):
                    ring[r] = data[i + k]; r = (r + 1) & 0xFFF
                i += best_len
            else:
                flag |= 1 << bit; out.append(data[i]); ring[r] = data[i]; r = (r + 1) & 0xFFF; i += 1
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

def main():
    if len(sys.argv) < 3: sys.exit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    img = open(path, "rb").read()
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
