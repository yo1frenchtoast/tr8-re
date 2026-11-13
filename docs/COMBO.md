# Motion + per-instrument length

Both features in one firmware: [motion recording](MOTION.md) and
[per-instrument length](POLY.md). The gestures are the same as in each document.

Status: **works on a real TR-8** (hardware test 1 below).

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_both.BIN --patch motion-poly
```

## Why a separate patch

Alone, each patch fits in the free region left by the developer dump code (788 + 1838 bytes),
but together they do not: the motion patch keeps its 1568-byte value table there. Most of that
space is zero-initialised data, which does not need to be in the image at all.

## Memory layout

| What | Where | Size |
|---|---|---|
| Motion code + `.data` | `0x60011150`-`0x60011463` (region A) | about 340 bytes |
| Poly code + RAM init + `.data` | `0x60011488`-`0x60011BB5` (region B) | about 840 bytes |
| All zero-initialised data (motion table, masks, poly heads) | **patch RAM** `0x60280A00` | 1916 bytes |

**Patch RAM.** The RTOS memory pool starts right after the firmware bss, at `0x60280988`. The
patch moves its start to `0x60290988` (literal at `0x600104A8`), so the 64 KB below it belong to
the patches. The pool keeps about 29.4 MB. This RAM is not part of the image and is not zeroed by
the startup code, so `ram_init` (hook at `0x60010482`, the call to the pool setup at boot) zeroes
the `.ram` section and then creates the pool as before. Details: [FINDINGS.md](FINDINGS.md)
section 12.

The source files are the same as the single patches (`patches/motion/motion.c`,
`patches/poly/poly.c`); only the link (`patches/combo/link.ld`) and `patches/combo/ram.c` are new.
The space left in both regions (about 1.5 KB of code) and in patch RAM (about 62 KB) is free for
the next features.

## With the bar chain

The [bar chain](CHAIN.md) is a module too: its code and its 128-byte bar index live in the
application image at `0x60281200` (above the bss; the patcher grows the decompressed image and
moves the pool start by the same 64 KB). It therefore takes no developer-dump space and no patch
RAM, and combines with every cave patch:

| Build | `--patch` | Payload |
|---|---|---|
| chain + motion | `motion-chain` | `patches/chain/payload_motion.json` |
| chain + poly | `poly-chain` | `patches/chain/payload_poly.json` |
| chain + motion + poly | `motion-poly-chain` | `patches/chain/payload_motion_poly.json` |

Each payload is the union of the parts' JSONs (`tools/merge_payloads.py`, run by
`patches/chain/build.sh`); the hook sites are the union of the parts' sites. Chain's gesture
(`A/B + pad 1..8`) is disjoint from motion (TR-REC/CLEAR + a control) and poly (LAST STEP +
instrument + pad), and the three keep their own storage: chain in the flash log and Ptn2 index 17,
poly in Ptn2 indices 4..14, motion in patch RAM. The three-way build is the only one that still
needs `ram_init` and the `motion-poly` patch RAM; the chain does not touch either.

The chain does not change the `motion-poly` memory layout: its region starts at `0x60281200`,
while the patch RAM ends at `0x60281183`.

| Site | New |
|---|---|
| all motion sites ([MOTION.md](MOTION.md)) | as in `motion` |
| all poly sites ([POLY.md](POLY.md)) | as in `poly` |
| `0x60010482` `bl FUN_60010430` (pool setup) | `bl ram_init` |
| `0x600104A8` literal `0x60280988` (pool start) | `0x60290988` |

## Tests

- `tests/emu_combo.py`: patch RAM zeroed at boot (and nothing around it), pool created at
  `0x60290988`-`0x62000000`, startup stack unchanged.
- `tests/emu_motion.py` and `tests/emu_poly.py` with `--payload patches/combo/payload.json`:
  every motion and poly scenario on the combined image.
- `tests/emu_chain.py` on `chain`, `motion-chain`, `poly-chain` and `motion-poly-chain` (262
  chain checks each, including the image growth and the moved pool); `emu_motion.py` on
  `motion-chain`, `emu_poly.py` on `poly-chain`, `emu_combo.py` on `motion-poly-chain`, with the
  merged payload.
- `tests/site_check.mjs` builds all seven variants and compares them byte for byte with
  `tr8patch.py`, including the grown image.

## Hardware test checklist (test 1: all checks passed)

| # | Action | Expected |
|---|---|---|
| 1 | Switch on | Normal start, patterns and kits present |
| 2 | Play a factory pattern for a few minutes, change patterns and kits | Normal sound, no freeze |
| 3 | Motion checks 3-6 of [UPDATE.md](UPDATE.md) | As with the motion patch |
| 4 | Poly test 2 (gesture), test 3 (step LEDs) and test 5 (LAST STEP blinks) of [POLY.md](POLY.md) | As with the poly patch |
| 5 | CH at 3 steps + record a BD decay motion | Both at the same time, no interference |
| 6 | Edit a pattern (the TR-8 saves it automatically), USB backup | Works (the memory pool is 64 KB smaller) |
| 7 | Switch off and on | Motion gone (RAM only), lengths kept with their pattern (tested, [POLY.md](POLY.md) test 4), unit starts normally |
| 8 | Same with the chain (`motion-chain`, `poly-chain`, `motion-poly-chain`) | All features at once: chain checks 1-11 of [CHAIN.md](CHAIN.md), motion and poly as above, no gesture collision; see the image-build checklist in [CHAIN.md](CHAIN.md) for the new boot path |

If the unit does not start at all, the pool move is the first suspect: recover with step [1] at
power-on and the official file.

## History

- Built and emulated.
- The poly lengths are now saved with each pattern (no patch RAM needed for them); see
  [POLY.md](POLY.md) hardware test 4.
- Hardware test 1 (2026-11-12): every check passed: normal start and play, motion and poly
  as with the single patches and at the same time, pattern save and USB backup, clean restart.
  The pool start move is safe on the unit.
