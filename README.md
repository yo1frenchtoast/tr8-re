# tr8-re

Reverse engineering of the Roland TR-8 firmware (system v1.61, `TR8_UPD.BIN`).
Goal: find out whether new features (longer patterns, **motion recording**) can be added.

Status: container format fully decoded, main application decompressed and loaded in Ghidra,
sequencer tick/step engine located. The knob-to-sound path (needed for motion record) is still being traced.
See [docs/FINDINGS.md](docs/FINDINGS.md) for results and [docs/FEASIBILITY.md](docs/FEASIBILITY.md) for the feature assessment.

## Quick start

```sh
mkdir -p firmware && unzip tr8_sys_v161.zip -d firmware      # from Roland's site, not included here
python3 -I tools/tr8fw.py info firmware/tr8_sys_v161/TR8_UPD.BIN
python3 -I tools/tr8fw.py extract firmware/tr8_sys_v161/TR8_UPD.BIN work   # work/{boot,updater,appA,appB}.{bin,elf}
tools/analyze.sh work/appA.elf analysis/appA                 # Ghidra headless -> analysis/appA.c + .strings (about 70 s)
```

## Layout

| Path | Content |
|---|---|
| `tools/tr8fw.py` | Parse the container, verify checksums, decompress (LZSS), build ELF wrappers. Also contains a LZSS compressor (round-trip tested only, slow). |
| `tools/mkelf.py` | Generic raw-binary to ARM ELF wrapper (copied from the keystep-pro-re project). |
| `tools/analyze.sh`, `tools/*.java` | Ghidra headless run: aggressive ARM instruction finder, then dump of all decompiled functions and strings. |
| `docs/` | Findings and feasibility notes. |

`firmware/`, `work/` and `analysis/` are git-ignored: they hold Roland code or output derived from it.

## Notes

- REA refuses the installed Ghidra 12.2, so `analyzeHeadless` is called directly.
- Addresses in the docs are runtime addresses (app loaded at `0x60000000`). The Ghidra function names are `FUN_<address>`.
- Everything marked "hypothesis" in the docs was inferred from decompiled code and not tested on a real unit.
