# Feasibility of new features

Nothing here was tested on hardware.

## Flashing safety

- No encryption or signature. The boot loader checks nothing; the updater checks the trailer, the module names and, after writing, the module byte-sums.
- `tr8fw.py pack` rebuilds a module (compress, size, byte-sum). Round trip on the unmodified application: identical after decompression, all checks OK.
- **Recovery path**: the update only rewrites flash 0x30000-0x3DFFFF. The boot loader and the updater stay untouched, and the updater starts when step [1] is held at power-on (boot table, FINDINGS 1b). A modified application that crashes can then be replaced by the original `TR8_UPD.BIN`. Procedure: [UPDATE.md](UPDATE.md).
- Remaining risks: a hardware fault during the flash itself (power cut), and a patched application that damages the user area (patterns/kits): make a backup first. Do not modify `appB` (second processor): a bad handshake stops the boot before the application starts. It is still recoverable through the updater, but there is no reason to touch it.

## Space for new code and data

- **RAM for data**: plenty. The RTOS memory pool is about 29.5 MB above the bss. The cleanest option is to grow the bss: add N bytes to the zero-fill length at `0x60000158` and move the pool base literal (`0x60280988`, used at `0x600104A8` and in the fast-code region) by the same amount.
- **Code**: appending code after the image does not work directly, because the bss zero-fill starts inside the loaded image (`0x601264EC`). Options:
  1. Code cave: `FUN_6001114E` + `FUN_600113B2` (about 2.6 KB) are only used by a developer branch of the USB backup (`FUN_60011DBE`, when the flag set by `FUN_60011F48` is on). Turn that branch into a no-op and reuse the space. **Used by the motion patch** (753 of 788 bytes in the first region, 1568 of 1838 in the second): a next feature needs option 2 or the RTOS pool.
  2. Grow the image and move the bss: more work (scatter table, pool base), but no size limit.

## A. Longer patterns (32 or 64 steps)

Hard parts: 16-bit step masks everywhere (parameters, handlers, storage slots of 0x50 bytes), UI with only 16 step buttons, the step engine limits (`LAST_A`/`LAST_B`) and possibly the sound engine. Variation A/B already gives two masks per row. Chaining A+B for 32 steps looks easier than 64.

## B. Motion recording (current focus)

**Status:** a RAM-only prototype is implemented and passes emulation: see [MOTION.md](MOTION.md). It records only in TR-REC. The plan below is the original design; MOTION.md describes what was built.

### Hook points found

| Need | Hook | Why |
|---|---|---|
| Capture | `FUN_6001446A(ctx, control_id, value)`, or the call to `FUN_600186FA` at its end | Every knob move in the normal screen goes through it, already mapped to an HMI parameter id. Recording `(step, param, value)` here records exactly what the user did. |
| Current step | `*(u32*)(0x6007E100 + 0x18)`, and the variation | A global, readable from the panel task. |
| Playback | Step change in `FUN_6000981E` (or the step callback at `+0x14`) | Called once per step with the step number. |
| Apply a value | `FUN_600186FA(DAT_60014668, param, value, 0)` | The same setter as the knobs, so the sound engine and the display follow normally. |

### Plan

1. **Storage**: a motion table per pattern and variation: for each recorded parameter, 16 values (0xFF = no value). Start with a fixed small set (for example 8 lanes x 16 steps x 2 variations = 256 bytes per pattern). It cannot fit in the `TR8_PTN` slot (0x50 bytes), so either extend the user area format or keep motion in RAM only for a first prototype.
2. **Capture**: patch the call in `FUN_6001446A` (or `FUN_600141DE`) to a new function: when recording is armed and the sequencer runs, write the value into the lane of that parameter at the current step, then continue to the normal setter.
3. **Playback**: patch `FUN_6000981E` to call a new function. For each lane with a value at this step, post the change.
4. **Thread safety**: playback runs in the sequencer context (clock tick), capture in the panel task. Calling the HMI setter from the sequencer context may not be safe. The safer option is to post a synthetic event `{0x0B, control_id, value}` the same way the ADC callback does (`0x60000CC0`), so the panel task applies it. Then playback reuses the full knob path, including the display. Check first that the listener FIFO tolerates a second producer.
5. **UI**: built as: record in TR-REC while running, erase in TR-REC while stopped (FINDINGS, "Panel mode"). No extra button combination.
6. **Knob takeover**: after playback has moved a parameter, the physical knob is no longer at that value. The firmware already has a threshold per knob; a "pickup" rule may be needed.

### Assessment

Feasible. Capture and playback each need one small detour (two patched calls plus about 0.5 to 1 KB of new code). RAM-only motion (lost when the pattern changes or at power off) is the realistic first prototype. Saving motion with the pattern is a second step because it changes the storage format.

### Next steps

1. Hardware test of the prototype ([UPDATE.md](UPDATE.md), test checklist).
2. Per-pattern motion and saving it: needs a new storage area next to `TR8_PTN` (0x50-byte slots are full) and more code space (grow the image, Space option 2).
3. Map control id -> parameter -> knob name, to show useful names and to choose which controls can record.
