# Feasibility of new features

Nothing here was tested on hardware. The risk of bricking a unit is real: only try on a unit you accept to lose, and find out the recovery procedure first.

## Common good news

- No encryption or signature found; the only integrity value found for the application is a byte-sum in the module header.
- Modified modules can be recompressed (`tr8fw.py` has a compressor, round-trip tested) and the sum recomputed. A module slot is 2.3 MB, the application is 1.2 MB, so there is room.
- The application is in RAM, so code size growth is possible; free flash is large.

## A. Longer patterns (32 or 64 steps)

Hard parts: 16-bit step masks everywhere (parameters, handlers, storage slots of 0x50 bytes), UI with only 16 step buttons, the step engine limits (`LAST_A`/`LAST_B`) and possibly the sound engine. Variation A/B already gives two masks per row. Chaining A+B for 32 steps looks easier than 64.

## B. Motion recording (current focus)

Needed:

1. **Storage**: per pattern, per recorded parameter, one value per step. Patterns have none today. About 16 bytes per parameter per variation. The `TR8_PTN` slot (0x50 bytes) is too small, so the format and the 128 KB user area layout must grow. Old backups must still load.
2. **Capture**: on a knob change while recording, store the value at the current step (`state+0x18`) of the sequencer struct `0x6007E100`. Needs the knob-to-parameter path (open question 1).
3. **Playback**: on each step (hook in `FUN_6000981E` or the callback at `+0x14`), re-apply stored values through the existing parameter handlers or voice functions. The CPU load of that is unknown.
4. **UI**: a way to arm recording and to erase motion (a spare button combination or a menu item). Not analysed.

Assessment so far: the architecture gives clean hook points (one function per clock tick and one callback per step), so playback looks feasible. The main unknown is capture, because the knob consumer has not been found. If knobs go straight to the sound engine in ROM without a parameter in RAM, capture must read the ADC values directly instead.
