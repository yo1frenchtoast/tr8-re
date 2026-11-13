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
  works on the unit). A larger feature can use the "grow the image" method (FINDINGS section 12):
  the bar chain now does, and passes in emulation; its boot path is waiting for the first unit
  run ([CHAIN.md](CHAIN.md)). Another dead-code region is the alternative.

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
chain ([CHAIN.md](CHAIN.md)): each pattern plays up to eight bars, each with its own A and B step
set, painted with VARIATION A/B + pad 1..8 and saved with the pattern. Bars are independent
content, not replays of the pattern's two passes: the selected bar is loaded into the working copy
so TR-REC records it, and the pattern save is redirected to an append-only log in unused flash
(`0x3DA000`-`0x3DFFFF`), which leaves the pattern's own steps intact as the default for unrecorded
bars. Each side of a pattern has its own length: A plays bars 1..Na with its A steps, B plays
1..Nb with its B steps, and A+B plays the A sequence then the B sequence. Each pattern keeps its
own eight bars and its own two lengths, so switching pattern switches the phrases. Its code and
its 128-byte bar index do not fit the two developer-dump regions, so the chain uses the "grow the
image" method: the patcher extends the decompressed image to cover 0x602827FC and puts the code
and state at 0x60281200, above the firmware bss that the startup code zeroes, and moves the RTOS
pool start by 64 KB (0x60280988 -> 0x60290988) so the pool cannot reach it. The cave stays free
for motion/poly, so the chain combines with them and the web flasher offers every combination. It
is emulation-tested (249 chain checks plus the three combinations, including a simulated power
cycle, log compaction and the chip's write protection); the step engine is untouched and no
pattern slot is spent on a bar. The larger image still ends far below `appB`, and the flash log
lives outside the application's compressed range. While
VARIATION A or B is held, the pads show that side's bars: green, with the playing bar blinking
yellow, and the remaining pads dark, so only the bars that side has are lit; releasing the button
returns the pads to whatever the screen was showing, on any screen, and the row keeps working
after a pattern change. During playback the step view follows the bar that is playing, so TR-REC
edits what you hear, and a bar nobody edited is not rewritten (steady playback writes no flash).
A side's length grows with A + pad n and is set exactly (shrunk) with A + CLEAR + pad n.

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
