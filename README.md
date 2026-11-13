# tr8-re

Reverse engineering of the Roland TR-8 firmware (system program v1.61) and a patcher that adds
new features to it: **motion recording** (hold TR-REC and turn a knob: the TR-8 plays the
movement back with the pattern) and **per-instrument length** (each instrument loops over its
own number of steps, for polyrhythms).

**Web flasher: <https://yo1frenchtoast.github.io/tr8-re/>**. Tick one mod or both, drop Roland's
official update, download the patched `TR8_UPD.BIN`. Everything runs in the browser.

This repository contains **no Roland code**. You download the official update from Roland; the
patcher checks that it is exactly v1.61 and writes a modified copy that the TR-8's own updater
accepts.

> Not affiliated with or endorsed by Roland. Flashing modified firmware is at your own risk. The
> update never rewrites the boot loader or the updater, so the original firmware can always be
> flashed again ([docs/UPDATE.md](docs/UPDATE.md)), except after a power cut during the flash.

## Status

| Topic | State |
|---|---|
| Update file format, compression, checks | Decoded; modules can be rebuilt |
| Boot loader, updater, recovery path | Decoded; recovery confirmed in use |
| Sequencer, controls, buttons, panel mode, sound parameter path | Mapped ([docs/FINDINGS.md](docs/FINDINGS.md)) |
| **Motion recording** | **Works on a real TR-8**: hold TR-REC to record, hold CLEAR to erase. RAM only, one global buffer |
| **Per-instrument length** | **Works on a real TR-8**: hold LAST STEP + an instrument, press a pad. Saved with each pattern ([docs/POLY.md](docs/POLY.md)) |
| **Motion + per-instrument length together** | **Works on a real TR-8** ([docs/COMBO.md](docs/COMBO.md)) |
| **Bar chain (more than two bars)** | **Emulation-tested**: hold A or B + a pad 1..4 to paint a bar and set that side's length; each side plays its own bars in order and A+B plays A then B. A + pad also loads that bar for editing while the machine is stopped (TR-REC edits it, another pad switches bar). While playing, the step view follows the bar you hear. While A or B is held the pads show that side's bars (green, playing bar blinking yellow), the rest dark, on every screen. Saved with each pattern ([docs/CHAIN.md](docs/CHAIN.md)) |
| Web flasher | Same output as `tr8patch.py`, byte for byte (`tests/site_check.mjs`) |
| Per-pattern saved motion, more than two bars | Assessed; the bar chain is implemented ([docs/FEASIBILITY.md](docs/FEASIBILITY.md), [docs/CHAIN.md](docs/CHAIN.md)) |

## Use a patch

The easiest way is the [web flasher](https://yo1frenchtoast.github.io/tr8-re/): tick one mod or
both. When you tick both, it builds the `motion-poly` patch. With Python 3 instead:

1. Download the TR-8 system program v1.61 from Roland and unzip it (`tr8_sys_v161/TR8_UPD.BIN`).
2. Build the patched file:
   ```sh
   python3 -I tools/tr8patch.py tr8_sys_v161/TR8_UPD.BIN TR8_UPD_motion.BIN               # motion
   python3 -I tools/tr8patch.py tr8_sys_v161/TR8_UPD.BIN TR8_UPD_poly.BIN --patch poly   # lengths
   python3 -I tools/tr8patch.py tr8_sys_v161/TR8_UPD.BIN TR8_UPD_chain.BIN --patch chain # bar chain
   python3 -I tools/tr8patch.py tr8_sys_v161/TR8_UPD.BIN TR8_UPD_both.BIN --patch motion-poly
   ```
3. Back up your patterns and kits, then flash the file you built, renamed to `TR8_UPD.BIN`,
   with Roland's normal procedure: [docs/UPDATE.md](docs/UPDATE.md).
4. How to use them: [docs/MOTION.md](docs/MOTION.md), [docs/POLY.md](docs/POLY.md),
   [docs/COMBO.md](docs/COMBO.md), [docs/CHAIN.md](docs/CHAIN.md). The bar chain is standalone
   for now (same code region as motion and poly); the web flasher does not offer it yet.

## Write your own feature

Start with [docs/DEVELOPING.md](docs/DEVELOPING.md). It covers the tools, how a patch hooks the
firmware, the known firmware functions (`patches/include/tr8_v161.h`), testing in emulation, and
testing on the unit. Quick start:

```sh
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
mkdir -p firmware && unzip tr8_sys_v161.zip -d firmware
F=firmware/tr8_sys_v161/TR8_UPD.BIN
python3 -I tools/tr8fw.py info "$F"
python3 -I tools/tr8fw.py extract "$F" work          # work/appA.bin and .elf: the application
GHIDRA_HOME=/path/to/ghidra tools/analyze.sh work/appA.elf analysis/appA
patches/motion/build.sh                              # needs clang + ld.lld
tests/run_all.sh "$F"                                # build every patch, run all emulation tests
```

## Documents

| File | Content |
|---|---|
| [docs/UPDATE.md](docs/UPDATE.md) | Flash, check the version, recover, test checklist for the unit |
| [docs/MOTION.md](docs/MOTION.md) | Motion recording: use, how it works, variants, test history |
| [docs/COMBO.md](docs/COMBO.md) | Motion + per-instrument length together: memory layout, hardware checklist |
| [docs/POLY.md](docs/POLY.md) | Per-instrument length (polyrhythm): use, how it works, storage per pattern, test history |
| [docs/CHAIN.md](docs/CHAIN.md) | Bar chain (more than two bars): gestures, display, how it works, storage, test history |
| [docs/DEVELOPING.md](docs/DEVELOPING.md) | Guide for writing new features |
| [docs/FINDINGS.md](docs/FINDINGS.md) | Firmware reference: file format, boot, memory map, sequencer, controls, buttons, parameters, display, code space |
| [docs/FEASIBILITY.md](docs/FEASIBILITY.md) | Assessment of further features |

## Layout

| Path | Content |
|---|---|
| `tools/tr8fw.py` | Update file tool: `info`, `extract` (LZSS + ELF wrappers), `pack` (recompress a module, fix size and byte-sum) |
| `tools/tr8patch.py` | Patcher: checks the input, applies a patch, rebuilds and re-checks the file (`--list`, `--check`) |
| `tools/elf2payload.py` | Linked payload ELF -> `payload.json` for the patcher |
| `tools/build_site.py` | Patch table -> `site/patches.json` for the web flasher |
| `tools/analyze.sh`, `tools/*.java` | Ghidra headless: decompile every function and list strings |
| `patches/include/tr8_v161.h` | Known firmware addresses and functions, with confidence tags |
| `patches/motion/` | Motion recording: `motion.c`, hardware probe `probe.c`, `link.ld`, `build.sh`, generated `payload*.json` |
| `patches/poly/` | Per-instrument length: `poly.c`, `link.ld`, `build.sh`, generated `payload.json` |
| `patches/chain/` | Bar chain (more than two bars): `chain.c`, `link.ld`, `build.sh`, generated `payload.json` |
| `patches/combo/` | Motion + poly: `ram.c` (patch RAM), `link.ld`, `build.sh`, generated `payload.json` |
| `site/` | Web flasher (static page, `tr8patch.js` = JS port of the patcher) |
| `tests/` | Unicorn emulation tests, `site_check.mjs` (web flasher = Python output) and `run_all.sh` |

`firmware/`, `work/` and `analysis/` are git-ignored: they hold Roland code or output derived from
it and must never be committed.

## License

MIT, see [LICENSE](LICENSE). This covers the code and documentation in this repository only.
Roland's firmware is not included and is not covered by this license; "Roland" and "TR-8" are
trademarks of Roland Corporation.
