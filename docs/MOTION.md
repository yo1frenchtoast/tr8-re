# Motion recording patch (prototype)

Status: **works on a real TR-8**: hold TR-REC to record (hardware test 5), hold CLEAR to erase (hardware test 6). RAM only, one global buffer.

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN --check          # is this file supported? (v1.61 only)
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion.BIN
```

Then flash it with Roland's normal procedure: see [UPDATE.md](UPDATE.md) (backup first, flash, recovery, and a test checklist for the unit).

The patcher takes the user's own Roland file. It refuses anything other than the exact v1.61 application (SHA-256 of the decompressed module), checks the original bytes at every patched address, and rebuilds the module size and byte-sum so the official updater accepts the file. `--check` only verifies an original input file; a patched file fails it on purpose.

## Builds

| `--patch` | Record | Erase | Status on the unit |
|---|---|---|---|
| `motion` (default) | **TR-REC held** while running (`FUN_60013168(0x11)`) | **CLEAR held** + knob, running or stopped (`FUN_60013168(0x1C)`) | **Works** (record: test 5, CLEAR erase: test 6) |
| `motion-mode` | TR-REC mode active (HMI Setup[0] == 0) while running | Knob while stopped in TR-REC mode | Not tested since the hook fix |
| `motion-diag` | Always while running | Knob while stopped | Works (test 4) |
| `motion-probe` | No motion: audible test of each link | - | Not needed so far |

## Behaviour

| Situation | Result |
|---|---|
Default build (`motion`):

| Situation | Result |
|---|---|
| Hold TR-REC, sequencer running, move a knob or fader | Its value is stored at the current step for that control |
| Next pass of the pattern | The stored values are replayed at their steps |
| Hold TR-REC, move a control that has motion | Recording overwrites; replay of that control pauses for 2 steps after each touch |
| Hold CLEAR, move a control (running or stopped) | The motion of that control is erased (A and B). The knob still changes the sound. CLEAR wins if both buttons are held |
| No button held, move a control | Normal live change only: nothing is recorded or erased, and the motion continues to replay |
| Power off | All motion is lost (RAM only) |

- 49 controls (36 knobs, 11 level controls, 2 others), 16 steps x 2 variations (A/B) each.
- One global motion buffer: it is **not** stored per pattern. Changing pattern keeps the same motion.
- `motion-mode` build: "record on" = HMI Setup parameter 0 (database object `0x60149F38`, global id `0x2A`) must be 0. The payload reads it with the firmware getter `FUN_6001B12E(0x60149F38, 0)`. Evidence: the mode buttons 0x11-0x16 in `FUN_6001961E` set it to 0-5; the step clear function `FUN_600192BA` only works in modes 0 and 3; the MIDI note input in `FUN_60004D8C` records notes into the pattern only in mode 3 (INST REC). So 0 = TR-REC, 3 = INST REC.
- Default build: record = `FUN_60013168(0x11)`, erase = `FUN_60013168(0x1C)`: the button-held bitmap (FINDINGS, "Panel buttons"). Test 5 confirmed that 0x11 is TR-REC. Test 6 confirmed that 0x1C is CLEAR.
- Since test 4 the panel boot mode (`0x6007E574`) and the knob redirect flag (`0x6007E580`) are not tested any more: they belong to the `FUN_6001446A` path, which normal play does not use. So motion also replays while an instrument button is held.

## How it works

| Hook | Original | New |
|---|---|---|
| `0x600138C8` in the HMI event-10 (knob) handler at `0x60013892` | `bl FUN_60013242` (give the event to the active screen) | `bl motion_knob` |
| `0x60009862` in `FUN_6000981E` (sequencer, once per step) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60009808` in `FUN_600097DA` (same, other scale path) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60011E00`, `0x60011E04` in `FUN_60011DBE` | calls to the developer dump functions | `nop.w` |

- The payload (`patches/motion/motion.c`) lives where the developer dump code was: code and small variables at `0x60011150`-`0x60011463` (753 of 788 bytes), the value table at `0x60011488` (1568 of 1838 bytes). The literal pool at `0x60011464`-`0x60011483` is still used by `FUN_60011054`/`FUN_600110A4` and is kept. SDRAM is read/write/execute in the MPU setup (`FUN_60010574`), so data can live there. The image size does not change.
- Capture: `motion_knob(screen, ev)` gets every HMI knob event `{10, id, value}` before the active screen and the global control -> parameter table `FUN_60013F6A`. When record is on it records `(id, value)` at slot `variation*16 + ((counter >> 1) & 15)`, then calls the original `FUN_60013242`. The sequencer counter `0x6007E118` counts **half steps**: `FUN_6000989C` calls the step function only on even values (FINDINGS 2).
- Replay: `motion_step` calls the original function, then for each control with a value at this slot it posts `{0x0B, id, value}` through the ADC change callback `0x60000CC0`. That is the same event as a real knob move. It goes through the panel FIFO, whose push is in a critical section, so posting from the sequencer task is safe. The panel task then applies it with the normal code path, and the display follows.
- Once per step: `FUN_6000981E` also calls `FUN_600097DA`, so both hooked calls usually run for the same step. `motion_step` remembers the last slot (`m_last`) and replays it only once. Without this, the second echo was taken as a user move and blocked the next replays.
- Echo filter: the replayed event comes back into `motion_knob`. A per-control "pending" flag and value lets `motion_knob` recognize it and not record it again.

State read by the payload: sequencer running `0x6007E102`, step `0x6007E118`, variation `0x6012FA74`, and the record/erase condition: TR-REC and CLEAR button state through `FUN_60013168` (default build) or Setup[0] through `FUN_6001B12E` (`motion-mode`).

## Test

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN work/TR8_UPD_motion.BIN
python3 -I tools/tr8fw.py extract work/TR8_UPD_motion.BIN work/patched
pip install unicorn   # in a virtualenv
python3 tests/emu_motion.py work/patched/appA.bin
```

`tests/emu_motion.py` runs the payload inside the patched application image with Unicorn. The firmware functions are stubs. 30 scenarios pass for the default build, 27 for `motion-mode` (`--mode`), 22 for the diagnostic build (`--diag`): record, hold, replay, echo, A/B, erase (CLEAR held, running or stopped), record condition, half-step counter, once per step, and the firmware's own knob event handler calling the payload. The Setup getter and the button-held function are stubs that return the state the test selects.

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

## Hardware probe

`--patch motion-probe` (source `patches/motion/probe.c`, test `tests/emu_probe.py`) uses the same hook sites but no motion. Each link of the chain gives an effect you can hear:

| Check on the unit | If yes | If no |
|---|---|---|
| Sequencer stopped: knobs do nothing | Capture hook runs, and the "running" flag `0x6007E102` reads 0 when stopped | Hook not reached (or the flashed file is not the probe) |
| Sequencer running: knobs work | "Running" flag reads 1 | Running flag wrong |
| Running: touch one knob, release it: its parameter jumps min/max on every step | Step hook runs and posting from the sequencer reaches the parameter | Step hook not reached, or posting from the sequencer context does not work |

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion_probe.BIN --patch motion-probe
```

## History

- Test 1 (first build): the unit started normally, but no motion was recorded or replayed.
- Test 2 (diagnostic build with the half-step and once-per-step fixes): still nothing. As the diagnostic build has no mode condition, the capture hook was the problem.
- Cause: the hook was on `FUN_6001446A`. That function is only the knob handler of some screens (`FUN_600141DE`). In normal use the event-10 handler `0x60013892` asks the active screen (`FUN_60013242`), and when the screen does not take the event it applies the parameter itself with `FUN_60013F6A`. `FUN_6001446A` is not on that path. Fix: hook the `FUN_60013242` call at `0x600138C8`, which sees all knob events. The emulation test now also runs the firmware's own event-10 handler.
- Test 3 (normal build `8dc6187`, hook at `0x600138C8`, TR-REC, BD TUNE turned during one bar while running): still nothing recorded or replayed.
- Test 4 (diagnostic build `8dc6187`, no mode conditions): **motion is recorded and replayed.** The whole chain works on the unit: capture hook `0x600138C8`, running flag, half-step counter, step hooks, replay through `0x60000CC0`. So one of the conditions of the normal build is wrong: the TR-REC test (Setup[0] == 0), the panel boot mode test (`0x6007E574` <= 3) or the knob redirect test (`0x6007E580`).
- After test 4: boot mode and redirect tests removed (wrong path, see Behaviour). Two builds for test 5: `motion` (TR-REC mode) and `motion-hold` (TR-REC held, the user's proposal). If `motion` records now, one of the removed tests was the cause; if only `motion-hold` records, the Setup[0] value is wrong.
- Test 5 (`motion-hold`, `e7c4ca4`): **works perfectly** according to the user: record while TR-REC is held, live tweak otherwise. This also proves that button id 0x11 is TR-REC and that `FUN_60013168` is the button-held state. (`motion` not reported.)
- After test 5, at the user's request: erase = hold **CLEAR** (0x1C) and turn the knob, running or stopped. The hold rule became the default build `motion`; the old Setup[0] rule is now `motion-mode`; `motion-hold` was removed.
- Test 6 (`motion`, `613191c`): **works perfectly** according to the user: CLEAR held + knob erases that control's motion, while running or stopped, other motion is kept. This confirms that button id 0x1C is CLEAR.

## Rebuild the payload

`patches/motion/build.sh` (needs clang and ld.lld) compiles `motion.c` with `link.ld` and writes `payload.json` (default), `payload_mode.json`, `payload_diag.json` and `payload_probe.json` (from `probe.c`) with the sections and symbols. The patcher only reads `payload.json`, so users need Python only.
