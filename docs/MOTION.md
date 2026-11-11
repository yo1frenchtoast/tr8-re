# Motion recording patch (prototype)

Status: **built and tested in emulation only. Never run on a real TR-8.**

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN --check          # is this file supported? (v1.61 only)
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion.BIN
```

Then flash it with Roland's normal procedure: see [UPDATE.md](UPDATE.md) (backup first, flash, recovery, and a test checklist for the unit).

The patcher takes the user's own Roland file. It refuses anything other than the exact v1.61 application (SHA-256 of the decompressed module), checks the original bytes at every patched address, and rebuilds the module size and byte-sum so the official updater accepts the file. `--check` only verifies an original input file; a patched file fails it on purpose.

## Behaviour

| Situation | Result |
|---|---|
| TR-REC on, sequencer running, you move a knob or fader | Its value is stored at the current step for that control |
| Next pass of the pattern | The stored values are replayed at their steps |
| TR-REC on, you move a control that has motion | Recording overwrites; replay of that control pauses for 2 steps after each touch |
| TR-REC on, sequencer stopped, you move a control | The motion of that control is erased (A and B) |
| Other mode (INST PLAY, INST REC, ...), you move a control | Normal live change only: nothing is recorded or erased, and the motion continues to replay |
| Power off | All motion is lost (RAM only) |

- 49 controls (36 knobs, 11 level controls, 2 others), 16 steps x 2 variations (A/B) each.
- One global motion buffer: it is **not** stored per pattern. Changing pattern keeps the same motion.
- Recording and erasing need TR-REC: HMI Setup parameter 0 (database object `0x60149F38`, global id `0x2A`) must be 0. The payload reads it with the firmware getter `FUN_6001B12E(0x60149F38, 0)`. Evidence: the mode buttons 0x11-0x16 in `FUN_6001961E` set it to 0-5; the step clear function `FUN_600192BA` only works in modes 0 and 3; the MIDI note input in `FUN_60004D8C` records notes into the pattern only in mode 3 (INST REC). So 0 = TR-REC, 3 = INST REC.
- Only the default knob handler records. When a button changes what the knobs do (redirect flag) or the panel boot mode (`0x6007E574`) is above 3, nothing is recorded and nothing is replayed.

## How it works

| Hook | Original | New |
|---|---|---|
| `0x60014204` in `FUN_600141DE` (panel task, default knob handler) | `bl FUN_6001446A` | `bl motion_knob` |
| `0x60009862` in `FUN_6000981E` (sequencer, once per step) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60009808` in `FUN_600097DA` (same, other scale path) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60011E00`, `0x60011E04` in `FUN_60011DBE` | calls to the developer dump functions | `nop.w` |

- The payload (`patches/motion/motion.c`) lives where the developer dump code was: code and small variables at `0x60011150`-`0x60011463` (753 of 788 bytes), the value table at `0x60011488` (1568 of 1838 bytes). The literal pool at `0x60011464`-`0x60011483` is still used by `FUN_60011054`/`FUN_600110A4` and is kept. SDRAM is read/write/execute in the MPU setup (`FUN_60010574`), so data can live there. The image size does not change.
- Capture: in TR-REC, `motion_knob(ctx, id, value)` records `(id, value)` at slot `variation*16 + ((counter >> 1) & 15)`, then calls the original `FUN_6001446A`. The sequencer counter `0x6007E118` counts **half steps**: `FUN_6000989C` calls the step function only on even values (FINDINGS 2).
- Replay: `motion_step` calls the original function, then for each control with a value at this slot it posts `{0x0B, id, value}` through the ADC change callback `0x60000CC0`. That is the same event as a real knob move. It goes through the panel FIFO, whose push is in a critical section, so posting from the sequencer task is safe. The panel task then applies it with the normal code path, and the display follows.
- Once per step: `FUN_6000981E` also calls `FUN_600097DA`, so both hooked calls usually run for the same step. `motion_step` remembers the last slot (`m_last`) and replays it only once. Without this, the second echo was taken as a user move and blocked the next replays.
- Echo filter: the replayed event comes back into `motion_knob`. A per-control "pending" flag and value lets `motion_knob` recognize it and not record it again.

State read by the payload: sequencer running `0x6007E102`, step `0x6007E118`, variation `0x6012FA74`, panel boot mode `0x6007E574` (not TR-REC: it is set once at panel task start), knob redirect `0x6007E580`, Setup[0] (TR-REC mode) through `FUN_6001B12E`.

## Test

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN work/TR8_UPD_motion.BIN
python3 -I tools/tr8fw.py extract work/TR8_UPD_motion.BIN work/patched
pip install unicorn   # in a virtualenv
python3 tests/emu_motion.py work/patched/appA.bin
```

`tests/emu_motion.py` runs the payload inside the patched application image with Unicorn. The firmware functions are stubs. 28 scenarios pass for the normal build, 21 for the diagnostic build (`--diag`): record, hold, replay, echo, A/B, erase, blocked modes, TR-REC condition, half-step counter, once per step. The Setup getter is a stub that returns the mode the test selects.

What the emulation does **not** prove: real timing, the exact meaning of the state addresses at run time, display behaviour, and whether replaying through the knob path has side effects in some screens.

## Known limitations and risks

- Not per pattern, not saved. A real feature would add per-pattern storage (FEASIBILITY, motion plan step 1).
- The display may show the parameter popup on every replayed value.
- Values are 8-bit (the knob events are 0-255), so replay has the same resolution as the knobs.
- The step slot uses `(counter >> 1) & 15`. With scale value `0x32` the firmware runs a step on odd counter values too; two steps then share one slot. To check on hardware.
- If a replayed event never reaches `motion_knob` (another screen consumed it), the pending flag stays set until the next replay of that control; one real move with the same value could then be ignored.

## Diagnostic build

`--patch motion-diag` builds the same patch without any mode condition: it records whenever the sequencer runs, in every mode, and replays even while a button is held.

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion_diag.BIN --patch motion-diag
```

Use it when the normal build records nothing: if the diagnostic build records, the TR-REC mode test is wrong; if it does not, the hooks or the replay path are wrong.

## History

- First hardware test (normal build, before the half-step and once-per-step fixes): the unit started normally, but no motion was recorded or replayed.

## Rebuild the payload

`patches/motion/build.sh` (needs clang and ld.lld) compiles `motion.c` with `link.ld` and writes `payload.json` and `payload_diag.json` with the sections and symbols. The patcher only reads `payload.json`, so users need Python only.
