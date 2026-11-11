# Feasibility of new features

Nothing here was tested on hardware. The risk of bricking a unit is real: only try on a unit you accept to lose, and find out the recovery procedure first.

## Common good news

- No encryption or signature found; the only integrity value found for the application is a byte-sum in the module header.
- Modified modules can be recompressed (`tr8fw.py` has a compressor, round-trip tested) and the sum recomputed. A module slot is 2.3 MB, the application is 1.2 MB, so there is room.
- The application is in RAM, so code size growth is possible; free flash is large.

## A. Longer patterns (32 or 64 steps)

Hard parts: 16-bit step masks everywhere (parameters, handlers, storage slots of 0x50 bytes), UI with only 16 step buttons, the step engine limits (`LAST_A`/`LAST_B`) and possibly the sound engine. Variation A/B already gives two masks per row. Chaining A+B for 32 steps looks easier than 64.

## B. Motion recording (current focus)

Updated after tracing the knob path (see FINDINGS, "Knob input").

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
5. **UI**: arm/erase with a button combination. Not analysed yet.
6. **Knob takeover**: after playback has moved a parameter, the physical knob is no longer at that value. The firmware already has a threshold per knob; a "pickup" rule may be needed.

### Assessment

Feasible. Capture and playback each need one small detour (two patched calls plus about 0.5 to 1 KB of new code). RAM-only motion (lost when the pattern changes or at power off) is the realistic first prototype. Saving motion with the pattern is a second step because it changes the storage format.

### Still unknown

- Free RAM and a place for new code. Candidates: replace debug code such as the factory-pattern dumper `FUN_600113B2` (a code cave), or grow the module (decompressed size field) if the RAM after the image is free.
- What the boot code checks besides the byte-sum.
- The full control id -> parameter id -> name table.
- Recovery procedure if a patched firmware does not boot.
