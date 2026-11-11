# Motion recording patch (prototype)

Status: **built and tested in emulation only. Never run on a real TR-8.**

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN --check          # is this file supported? (v1.61 only)
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion.BIN
```

Copy `TR8_UPD_motion.BIN` to the TR-8 update storage **renamed to `TR8_UPD.BIN`** and follow Roland's normal update procedure.

The patcher takes the user's own Roland file. It refuses anything other than the exact v1.61 application (SHA-256 of the decompressed module), checks the original bytes at every patched address, and rebuilds the module size and byte-sum so the official updater accepts the file.

Before you try it:

1. Save your patterns and kits (USB backup).
2. Keep the original `TR8_UPD.BIN`.
3. Make sure you know how to start the updater with the button held at power-on (Roland update instructions). The update only rewrites flash 0x30000-0x3DFFFF; the boot loader and the updater are not touched (FINDINGS 1b/1c). If the patched firmware does not start, start the updater that way and flash the original file.

## Behaviour

| Situation | Result |
|---|---|
| Sequencer running, you move a knob or fader | Its value is stored at the current step for that control |
| Next pass of the pattern | The stored values are replayed at their steps |
| You move a control that has motion | Recording overwrites; replay of that control pauses for 2 steps after each touch |
| Sequencer stopped, you move a control | The motion of that control is erased (A and B) |
| Power off | All motion is lost (RAM only) |

- 49 controls (36 knobs, 11 level controls, 2 others), 16 steps x 2 variations (A/B) each.
- One global motion buffer: it is **not** stored per pattern. Changing pattern keeps the same motion.
- Only the default knob mode records. When a button changes what the knobs do (redirect flag) or the panel mode is above 3, nothing is recorded and nothing is replayed.

## How it works

| Hook | Original | New |
|---|---|---|
| `0x60014204` in `FUN_600141DE` (panel task, default knob handler) | `bl FUN_6001446A` | `bl motion_knob` |
| `0x60009862` in `FUN_6000981E` (sequencer, once per step) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60009808` in `FUN_600097DA` (same, other scale path) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60011E00`, `0x60011E04` in `FUN_60011DBE` | calls to the developer dump functions | `nop.w` |

- The payload (`patches/motion/motion.c`) lives where the developer dump code was: code and small variables at `0x60011150`-`0x60011463` (725 of 788 bytes), the value table at `0x60011488` (1568 of 1838 bytes). The literal pool at `0x60011464`-`0x60011483` is still used by `FUN_60011054`/`FUN_600110A4` and is kept. SDRAM is read/write/execute in the MPU setup (`FUN_60010574`), so data can live there. The image size does not change.
- Capture: `motion_knob(ctx, id, value)` records `(id, value)` at slot `variation*16 + (step & 15)`, then calls the original `FUN_6001446A`.
- Replay: `motion_step` calls the original function, then for each control with a value at this slot it posts `{0x0B, id, value}` through the ADC change callback `0x60000CC0`. That is the same event as a real knob move. It goes through the panel FIFO, whose push is in a critical section, so posting from the sequencer task is safe. The panel task then applies it with the normal code path, and the display follows.
- Echo filter: the replayed event comes back into `motion_knob`. A per-control "pending" flag and value lets `motion_knob` recognize it and not record it again.

State read by the payload: sequencer running `0x6007E102`, step `0x6007E118`, variation `0x6012FA74`, panel mode `0x6007E574`, knob redirect `0x6007E580`.

## Test

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN work/TR8_UPD_motion.BIN
python3 -I tools/tr8fw.py extract work/TR8_UPD_motion.BIN work/patched
pip install unicorn   # in a virtualenv
python3 tests/emu_motion.py work/patched/appA.bin
```

`tests/emu_motion.py` runs the payload inside the patched application image with Unicorn. The firmware functions are stubs. 18 scenarios pass (record, hold, replay, echo, A/B, erase, blocked modes).

What the emulation does **not** prove: real timing, the exact meaning of the state addresses at run time, display behaviour, and whether replaying through the knob path has side effects in some screens.

## Known limitations and risks

- Not per pattern, not saved. A real feature would add per-pattern storage (FEASIBILITY B.1).
- The display may show the parameter popup on every replayed value.
- Values are 8-bit (the knob events are 0-255), so replay has the same resolution as the knobs.
- The step slot uses `step & 15`. If the sequencer runs a single 32-step A+B pass with the step counter above 15, A and B would share slots. To check on hardware.
- If a replayed event never reaches `motion_knob` (another screen consumed it), the pending flag stays set until the next replay of that control; one real move with the same value could then be ignored.

## Rebuild the payload

`patches/motion/build.sh` (needs clang and ld.lld) compiles `motion.c` with `link.ld` and writes `payload.json` with the sections and symbols. The patcher only reads `payload.json`, so users need Python only.
