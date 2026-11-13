# Feature feasibility

Assessments of features that could be added. The facts behind them are in
[FINDINGS.md](FINDINGS.md); how to build a patch is in [DEVELOPING.md](DEVELOPING.md).

## Safety and constraints

- **No protection.** No encryption or signature. The boot loader checks nothing; the updater
  checks the trailer, the module names and, after writing, the module byte-sums. `tr8fw.py pack`
  and `tr8patch.py` rebuild sizes and sums (round trip verified).
- **Recovery.** An update only rewrites flash `0x30000`-`0x3DFFFF`. The boot loader and the
  updater are never written, and step [1] at power-on starts the updater before the application
  ([UPDATE.md](UPDATE.md)). Remaining risks: a power cut while flashing, and a patch that damages
  the user area (back up patterns and kits).
- **Do not modify `appB`** (second processor firmware). A bad handshake stops the boot before
  the application. It is recoverable through the updater, but there is no known reason to touch it.
- **RAM** is not a constraint: the RTOS pool has about 29.5 MB (29.4 MB with `motion-poly`).
- **Code space**: with `motion-poly`, about 1.5 KB of code space is left in the developer dump
  regions, and data goes to patch RAM (64 KB taken from the RTOS pool, [COMBO.md](COMBO.md),
  works on the unit). A larger feature needs the "grow the image" method (FINDINGS section 12,
  not tested) or another dead-code region.

## A. Motion recording: done

Works on a real unit: hold TR-REC to record, hold CLEAR to erase. See [MOTION.md](MOTION.md).

**Per-pattern, saved motion** is the next step:

- Storage: a pattern is a set of parameters (FINDINGS section 6). Only 16 unused 16-bit
  parameters exist per pattern (Ptn2), and the poly patch uses 11 of them. Motion needs its own
  area. Options: a new region in the 128 KB user area (`storage\sf_bios.cpp` stores declared RAM
  ranges; find the free space), or a file on the USB storage at backup time.
- Size: 49 controls x 32 slots = 1568 bytes per pattern with the current layout. A sparse format
  (only controls with motion, for example 8 lanes per pattern) brings it to about 270 bytes.
- Code: pattern change and save/load hooks, so it needs more code space (grow the image).

## B. Longer patterns (more than two bars): bar chain done

A true 32- or 64-step pattern is hard: 16-bit step masks are used everywhere: parameters
(`STEP_<row>1/2`), change handlers, the pattern struct, the stored pattern parameters, and the UI
has 16 step buttons. The step engine limit comes from `LAST_A`/`LAST_B` and the pattern struct
(`FUN_600525F8`). A 32-step view would also need a page selector the panel does not have.

The useful part of the feature is a longer **arrangement**, and that is implemented as the bar
chain ([CHAIN.md](CHAIN.md)): a pattern plays up to 16 bars, painted with A/B + pad and saved
with the pattern. A bar is a whole pattern variation (16 patterns x 2 variations = 32 bars
shared by all songs), so the material is not limited to the two passes of one pattern either; a
song spends one pattern per bar. It is emulation-tested; the step engine is untouched. Selecting
bar *n* switches the pattern being edited, through the firmware's own save/load primitives, so
TR-REC records each bar into its own pattern.

## C. Per-instrument length (polyrhythm): done

Each instrument loops over its own number of steps (1-16). Medium difficulty, no 16-bit limit
involved: the step trigger tests one bit per mask, so a hook swaps in the bit of each
instrument's own head. **Works on a real unit**: playback, panel gesture, step LED view, and
lengths saved with each pattern in unused pattern parameters; see [POLY.md](POLY.md). Combined
with motion in `motion-poly` ([COMBO.md](COMBO.md)), works on the unit.

## D. Other ideas

| Idea | Difficulty | Notes |
|---|---|---|
| Per-step parameter locks (one value per step for one control) | Medium | Same mechanism as motion (`TR8_POST_CTRL` per step); only the input gesture changes |
| Probability / conditional trigs | Medium-hard | Needs a hook in `FUN_60009746` (trigger mask of the step) and storage |
| Random / LFO on a control | Easy-medium | Per-step hook + `TR8_POST_CTRL`; no storage needed |
| Extra MIDI CC mappings | Unknown | Receive path not traced (FINDINGS open question 8) |
| Show values or names on the display | Easy-medium | `TR8_DISPLAY_TEXT` exists; the screen redraws over it |
