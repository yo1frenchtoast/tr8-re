// Roland TR-8 v1.61 update file patcher: a port of tools/tr8fw.py + tools/tr8patch.py.
// Runs in the browser and in Node (tests/site_check.mjs). No Roland data here: the user
// supplies the official TR8_UPD.BIN (or the zip); patches.json holds only our payloads.

const BASE = 0x60000000;
const APPA = 0x30000;
const MODULE_BASES = [0x8000, 0x30000, 0x280000]; // updater, appA, appB
const NOP_W = [0xaf, 0xf3, 0x00, 0x80];

export class PatchError extends Error {}

const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const put32 = (b, o, v) => { b[o] = v & 255; b[o + 1] = (v >>> 8) & 255; b[o + 2] = (v >>> 16) & 255; b[o + 3] = (v >>> 24) & 255; };
const sum32 = (b) => { let s = 0; for (let i = 0; i < b.length; i++) s = (s + b[i]) >>> 0; return s; };
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const unhex = (s) => Uint8Array.from(s.match(/../g) || [], (x) => parseInt(x, 16));

export function thumbBl(src, dst, link = true) {   // BL, or B.W (a tail call) without link
  const off = dst - (src + 4);
  const s = (off >> 24) & 1, i1 = (off >> 23) & 1, i2 = (off >> 22) & 1;
  const j1 = (~i1 ^ s) & 1, j2 = (~i2 ^ s) & 1;
  const h1 = 0xf000 | (s << 10) | ((off >> 12) & 0x3ff);
  const h2 = (link ? 0xd000 : 0x9000) | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7ff);
  return [h1 & 255, h1 >> 8, h2 & 255, h2 >> 8];
}

// Okumura LZSS: 4096 ring, initial position 0xFEE, flag bit 1 = literal.
export function lzss(src, dsize) {
  const ring = new Uint8Array(4096), out = new Uint8Array(dsize);
  let r = 0xfee, n = 0, i = 0, flags = 0;
  while (n < dsize && i < src.length) {
    flags >>>= 1;
    if (!(flags & 0x100)) flags = src[i++] | 0xff00;
    if (flags & 1) {
      const c = src[i++]; out[n++] = c; ring[r] = c; r = (r + 1) & 0xfff;
    } else {
      const b0 = src[i], b1 = src[i + 1]; i += 2;
      const pos = b0 | ((b1 & 0xf0) << 4), ln = (b1 & 0xf) + 2;
      for (let k = 0; k <= ln && n < dsize; k++) {
        const c = ring[(pos + k) & 0xfff]; out[n++] = c; ring[r] = c; r = (r + 1) & 0xfff;
      }
    }
  }
  return { out: out.subarray(0, n), used: i };
}

// Same greedy encoder as tr8fw.lzss_compress (same choices, so the same bytes).
export function lzssCompress(data, onProgress) {
  const MAXD = 4096 - 18, MAXL = 18, n = data.length;
  const heads = new Map();
  const out = new Uint8Array(n + Math.ceil(n / 8) + 16);
  let o = 0, i = 0, nextReport = 0;
  const key = (j) => (data[j] << 16) | (data[j + 1] << 8) | data[j + 2];
  const add = (j) => {
    if (j + 3 <= n) {
      const k = key(j);
      let lst = heads.get(k);
      if (!lst) heads.set(k, (lst = []));
      lst.push(j);
      if (lst.length > 48) lst.shift();
    }
  };
  while (i < n) {
    const flagpos = o++;
    let flag = 0;
    for (let bit = 0; bit < 8; bit++) {
      if (i >= n) break;
      let bestLen = 0, bestJ = 0;
      if (i + 3 <= n) {
        const lst = heads.get(key(i));
        if (lst) {
          for (let x = lst.length - 1; x >= 0; x--) {
            const j = lst[x];
            if (i - j > MAXD) break;
            let l = 3;
            const maxl = Math.min(MAXL, n - i);
            while (l < maxl && data[j + l] === data[i + l]) l++;
            if (l > bestLen) { bestLen = l; bestJ = j; if (l === maxl) break; }
          }
        }
      }
      if (bestLen >= 3) {
        const pos = (0xfee + bestJ) & 0xfff;
        out[o++] = pos & 0xff;
        out[o++] = ((pos >> 4) & 0xf0) | (bestLen - 3);
        for (let k = 0; k < bestLen; k++) add(i + k);
        i += bestLen;
      } else {
        flag |= 1 << bit; out[o++] = data[i]; add(i); i++;
      }
    }
    out[flagpos] = flag;
    if (onProgress && i >= nextReport) { onProgress(i / n); nextReport = i + 65536; }
  }
  return out.slice(0, o);
}

function parseModule(img, base) {
  const name = new TextDecoder("latin1").decode(img.subarray(base, base + 0x28)).split("\0")[0];
  const hsz = u32(img, base + 0x2c), csz = u32(img, base + 0x30), csum = u32(img, base + 0x34), dsz = u32(img, base + 0x3c);
  const payload = img.subarray(base + hsz, base + hsz + csz);
  return { name, hsz, csz, csum, dsz, payload, sumOk: sum32(payload) === csum };
}

function trailer(img) {
  const t = img.length - 16;
  return { first: u32(img, t), last: u32(img, t + 4), bsz: u32(img, t + 8), total: u32(img, t + 12) };
}

export function checkContainer(img) {
  if (img.length < 0x300000) throw new PatchError("file too small: not a TR-8 TR8_UPD.BIN");
  const t = trailer(img);
  if (t.total !== img.length - 16 || t.first !== 0x30 || t.last !== 0x3df || t.bsz !== 0x1000)
    throw new PatchError("unexpected trailer: not a TR-8 v1.61 TR8_UPD.BIN");
  for (const b of MODULE_BASES)
    if (!parseModule(img, b).sumOk) throw new PatchError(`module at 0x${b.toString(16)}: byte-sum is wrong (corrupted file)`);
}

async function sha256(bytes) {
  return hex(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)));
}

export async function loadApp(img, manifest) {
  const m = parseModule(img, APPA);
  if (!m.name.startsWith(manifest.app_name))
    throw new PatchError(`unsupported application "${m.name.trim()}": only system v${manifest.version} is supported`);
  const { out } = lzss(m.payload, m.dsz);
  if (out.length !== m.dsz || (await sha256(out)) !== manifest.app_sha256)
    throw new PatchError("the application does not match the official v1.61 (already patched, or another version)");
  return Uint8Array.from(out);
}

export function applyPatch(app, spec, log) {
  const syms = spec.symbols;
  for (const s of spec.sites) {
    const o = s.addr - BASE, orig = unhex(s.orig);
    for (let k = 0; k < 4; k++)
      if (app[o + k] !== orig[k]) throw new PatchError(`unexpected bytes at 0x${s.addr.toString(16)} (patches cannot be combined?)`);
    app.set(s.repl.bytes ? unhex(s.repl.bytes) : s.repl === "nop" ? NOP_W
            : s.repl.startsWith("b:") ? thumbBl(s.addr, syms[s.repl.slice(2)] & ~1, false)
            : thumbBl(s.addr, syms[s.repl] & ~1), o);
  }
  for (const r of spec.regions) {
    const data = unhex(r.data), a = r.addr;
    if (!spec.allowed.some(([lo, hi]) => lo <= a && a + data.length <= hi))
      throw new PatchError(`payload ${r.section} outside the free regions`);
    if (spec.keep.some(([lo, hi]) => a < hi && lo < a + data.length))
      throw new PatchError(`payload ${r.section} overlaps a protected range`);
    const end = a - BASE + data.length;
    if (end > app.length) {                     // image region above the bss: grow the image
      const grown = new Uint8Array(end);
      grown.set(app);
      app = grown;
    }
    app.set(data, a - BASE);
    log?.(`  ${r.section.padEnd(6)} 0x${a.toString(16)}  ${data.length} bytes`);
  }
  for (const r of spec.ram || []) log?.(`  ${r.section.padEnd(6)} 0x${r.addr.toString(16)}  ${r.size} bytes (patch RAM)`);
  for (const s of spec.sites) log?.(`  site   0x${s.addr.toString(16)} -> ${s.repl.bytes ? "0x" + s.repl.bytes : s.repl}`);
  return app;
}

export function pack(img, newApp, onProgress) {
  const m = parseModule(img, APPA);
  const comp = lzssCompress(newApp, onProgress);
  const chk = lzss(comp, newApp.length);
  if (chk.used !== comp.length || chk.out.length !== newApp.length || chk.out.some((v, k) => v !== newApp[k]))
    throw new PatchError("internal error: compressor round trip failed");
  const t = trailer(img);
  const limit = MODULE_BASES.find((b) => b > APPA) - APPA - m.hsz;
  if (APPA + m.hsz + comp.length > (t.last + 1) * t.bsz || comp.length > limit)
    throw new PatchError("patched application too big");
  const out = Uint8Array.from(img);
  put32(out, APPA + 0x30, comp.length);
  put32(out, APPA + 0x34, sum32(comp));
  put32(out, APPA + 0x3c, newApp.length);
  const start = APPA + m.hsz, end = start + Math.max(comp.length, m.csz);
  out.fill(0xff, start, end);
  out.set(comp, start);
  return out;
}

// Full build: check the input, patch, recompress, re-check the output.
export async function build(img, manifest, names, { log, progress } = {}) {
  checkContainer(img);
  let app = await loadApp(img, manifest);
  log?.("input: TR-8 v1.61 TR8_UPD.BIN, all checks OK");
  const groups = new Set();
  for (const name of names) {
    const spec = manifest.patches[name];
    if (!spec) throw new PatchError(`unknown patch ${name}`);
    if (groups.has(spec.group)) throw new PatchError("these patches use the same free memory and cannot be combined");
    groups.add(spec.group);
    log?.(`patch ${name}`);
    app = applyPatch(app, spec, log);
  }
  log?.("compressing the application...");
  const out = pack(img, app, progress);
  checkContainer(out);
  log?.("output checked: trailer and module sums OK");
  return out;
}

// Accept the official zip as well: find TR8_UPD.BIN inside it (stored or deflate).
export async function extractUpdate(bytes) {
  if (!(bytes[0] === 0x50 && bytes[1] === 0x4b)) return bytes;
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--)
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new PatchError("zip file not readable");
  let p = dv.getUint32(eocd + 16, true);
  const count = dv.getUint16(eocd + 10, true);
  for (let e = 0; e < count; e++) {
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true);
    const nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const local = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (!/(^|\/)TR8_UPD\.BIN$/i.test(name)) continue;
    const start = local + 30 + dv.getUint16(local + 26, true) + dv.getUint16(local + 28, true);
    const data = bytes.subarray(start, start + csize);
    if (method === 0) return Uint8Array.from(data);
    if (method !== 8) throw new PatchError("zip compression method not supported");
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  throw new PatchError("no TR8_UPD.BIN inside this zip");
}
