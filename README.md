# tr8-re

Reverse engineering of the Roland TR-8 firmware (system program v1.61) and a patcher that adds
new features to it. The first feature is **motion recording**: hold TR-REC and turn a knob, and
the TR-8 plays the movement back with the pattern.

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
| Per-pattern saved motion, 32/64-step patterns | Assessed ([docs/FEASIBILITY.md](docs/FEASIBILITY.md)) |

## Use the motion patch

Needs Python 3 only.

1. Download the TR-8 system program v1.61 from Roland and unzip it (`tr8_sys_v161/TR8_UPD.BIN`).
2. Build the patched file:
   ```sh
   python3 -I tools/tr8patch.py tr8_sys_v161/TR8_UPD.BIN TR8_UPD_motion.BIN
   ```
3. Back up your patterns and kits, then flash `TR8_UPD_motion.BIN` renamed to `TR8_UPD.BIN`
   with Roland's normal procedure: [docs/UPDATE.md](docs/UPDATE.md).
4. How to use it: [docs/MOTION.md](docs/MOTION.md).

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
| [docs/POLY.md](docs/POLY.md) | Per-instrument length (polyrhythm): test build, how it works, hardware checklist |
| [docs/DEVELOPING.md](docs/DEVELOPING.md) | Guide for writing new features |
| [docs/FINDINGS.md](docs/FINDINGS.md) | Firmware reference: file format, boot, memory map, sequencer, controls, buttons, parameters, display, code space |
| [docs/FEASIBILITY.md](docs/FEASIBILITY.md) | Assessment of further features |

## Layout

| Path | Content |
|---|---|
| `tools/tr8fw.py` | Update file tool: `info`, `extract` (LZSS + ELF wrappers), `pack` (recompress a module, fix size and byte-sum) |
| `tools/tr8patch.py` | Patcher: checks the input, applies a patch, rebuilds and re-checks the file (`--list`, `--check`) |
| `tools/elf2payload.py` | Linked payload ELF -> `payload.json` for the patcher |
| `tools/analyze.sh`, `tools/*.java` | Ghidra headless: decompile every function and list strings |
| `patches/include/tr8_v161.h` | Known firmware addresses and functions, with confidence tags |
| `patches/motion/` | Motion recording: `motion.c`, hardware probe `probe.c`, `link.ld`, `build.sh`, generated `payload*.json` |
| `tests/` | Unicorn emulation tests and `run_all.sh` |

`firmware/`, `work/` and `analysis/` are git-ignored: they hold Roland code or output derived from
it and must never be committed.

## License

MIT, see [LICENSE](LICENSE). This covers the code and documentation in this repository only.
Roland's firmware is not included and is not covered by this license; "Roland" and "TR-8" are
trademarks of Roland Corporation.
