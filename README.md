# tr8-re

Reverse engineering of the Roland TR-8 firmware (system v1.61, `TR8_UPD.BIN`).
Goal: find out whether new features (longer patterns, **motion recording**) can be added, and ship them as a patcher for the user's own Roland file.

This repository contains no Roland code. You download the official update from Roland and the tools work on your copy.

## Status

| Topic | State |
|---|---|
| Container, compression, module checks | Decoded; a module can be rebuilt (`tr8fw.py pack`) |
| Boot loader, updater, recovery path | Decoded; boot checks nothing, the updater is never rewritten |
| Sequencer engine, knob path, TR-REC mode flag | Located (FINDINGS 2) |
| Motion recording | Prototype patch; **diagnostic build records and replays on the unit (test 4)**; **`motion-hold` (record while TR-REC is held) works on the unit (test 5)** |
| 32/64-step patterns | Assessed only (FEASIBILITY A): hard |

## Documents

| File | Read it for |
|---|---|
| [docs/UPDATE.md](docs/UPDATE.md) | How to flash, check the version, recover, and test the patch on the unit |
| [docs/MOTION.md](docs/MOTION.md) | What the motion patch does, how it works, limitations |
| [docs/FINDINGS.md](docs/FINDINGS.md) | Firmware analysis: container, boot, memory map, parameters, sequencer, knob path, panel mode |
| [docs/FEASIBILITY.md](docs/FEASIBILITY.md) | Flash safety, code/RAM space, feature assessments, next steps |

## Motion recording patch

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN --check               # is this a supported original file?
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion.BIN
```

Then follow [docs/UPDATE.md](docs/UPDATE.md): back up, rename the output to `TR8_UPD.BIN`, flash with step [1] held at power-on. Only Python 3 is needed.

In TR-REC, with the pattern running, knob and fader moves are recorded per step (16 steps x A/B) and replayed. In TR-REC with the sequencer stopped, moving a control erases its motion. Motion is kept in RAM only.

## Analysis quick start

```sh
mkdir -p firmware && unzip tr8_sys_v161.zip -d firmware      # from Roland's site, not included here
python3 -I tools/tr8fw.py info firmware/tr8_sys_v161/TR8_UPD.BIN
python3 -I tools/tr8fw.py extract firmware/tr8_sys_v161/TR8_UPD.BIN work   # work/{boot,updater,appA,appB}.{bin,elf}
tools/analyze.sh work/appA.elf analysis/appA                 # Ghidra headless -> analysis/appA.c + .strings (about 70 s)
```

Payload development (needs clang, ld.lld, and unicorn in a virtualenv):

```sh
patches/motion/build.sh                                      # motion.c -> payload.json
python3 -I tools/tr8patch.py firmware/tr8_sys_v161/TR8_UPD.BIN work/TR8_UPD_motion.BIN
python3 -I tools/tr8fw.py extract work/TR8_UPD_motion.BIN work/patched
python3 tests/emu_motion.py work/patched/appA.bin
```

## Layout

| Path | Content |
|---|---|
| `tools/tr8fw.py` | `info` (trailer + module checks), `extract` (LZSS decompress + ELF wrappers), `pack` (recompress a module, fix size and byte-sum). |
| `tools/tr8patch.py` | Patcher: checks the input is v1.61, applies the patch sites and the payload, rebuilds the module, verifies the output. |
| `tools/elf2payload.py` | Converts a linked payload ELF into `payload.json` for the patcher. |
| `patches/motion/` | Motion recording payload `motion.c`, hardware probe `probe.c`, `link.ld`, `build.sh`, generated `payload*.json` and `motion.lst`. |
| `tests/emu_motion.py`, `tests/emu_probe.py` | Unicorn emulation tests of the motion payload and of the hardware probe inside the patched image. |
| `tools/mkelf.py` | Generic raw-binary to ARM ELF wrapper. |
| `tools/analyze.sh`, `tools/*.java` | Ghidra headless run: aggressive ARM instruction finder, then dump of all decompiled functions and strings. |

`firmware/`, `work/` and `analysis/` are git-ignored: they hold Roland code or output derived from it.

## Notes

- REA refuses the installed Ghidra 12.2, so `analyzeHeadless` is called directly.
- Addresses are runtime addresses (application loaded at `0x60000000`). Ghidra function names are `FUN_<address>`.
- Everything marked "hypothesis" or "not proven" was inferred from decompiled code and not tested on a real unit.
