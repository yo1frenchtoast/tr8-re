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
- **RAM** is not a constraint: the RTOS pool has about 29.5 MB.
- **Code space** is: the developer dump cave is almost full after the motion patch. A larger
  feature needs the "grow the image" method (FINDINGS section 12, designed, not tested on a unit)
  or another dead-code region.

## A. Motion recording: done

Works on a real unit: hold TR-REC to record, hold CLEAR to erase. See [MOTION.md](MOTION.md).

**Per-pattern, saved motion** is the next step:

- Storage: the `TR8_PTN` slots (16 x 0x50 bytes) are full. Motion needs its own area. Options: a
  new region in the 128 KB user area (find the free space and the flash write functions in
  `storage\sf_bios.cpp`), or a file on the USB storage at backup time.
- Size: 49 controls x 32 slots = 1568 bytes per pattern with the current layout. A sparse format
  (only controls with motion, for example 8 lanes per pattern) brings it to about 270 bytes.
- Code: pattern change and save/load hooks, so it needs more code space (grow the image).

## B. Longer patterns (32 or 64 steps)

Hard. 16-bit step masks are used everywhere: parameters (`STEP_<row>1/2`), change handlers, the
pattern struct, the 0x50-byte storage slots, and the UI has 16 step buttons. The step engine
limit comes from `LAST_A`/`LAST_B` and the pattern struct (`FUN_600525F8`); whether the sound side
has a limit is unknown.

A realistic first step: **A+B chained as one 32-step pattern**. Variation A/B already gives two
16-bit masks per row, and the firmware already has an A+B variation setting (`VARI` = 2, [hyp]).
Check first how A+B plays today: if it already alternates A and B, a 32-step view is mostly a UI
change.

## C. Per-instrument length (polyrhythm): works (test build)

Each instrument loops over its own number of steps (1-16). Medium difficulty, no 16-bit limit
involved: the step trigger tests one bit per mask, so a hook swaps in the bit of each
instrument's own head. Test build with fixed lengths **works on a real unit**; see [POLY.md](POLY.md).
Next: a panel gesture, per-pattern storage (11 bytes), code space to combine with motion.

## D. Other ideas

| Idea | Difficulty | Notes |
|---|---|---|
| Per-step parameter locks (one value per step for one control) | Medium | Same mechanism as motion (`TR8_POST_CTRL` per step); only the input gesture changes |
| Probability / conditional trigs | Medium-hard | Needs a hook in `FUN_60009746` (trigger mask of the step) and storage |
| Random / LFO on a control | Easy-medium | Per-step hook + `TR8_POST_CTRL`; no storage needed |
| Extra MIDI CC mappings | Unknown | Receive path not traced (FINDINGS open question 8) |
| Show values or names on the display | Easy-medium | `TR8_DISPLAY_TEXT` exists; the screen redraws over it |
