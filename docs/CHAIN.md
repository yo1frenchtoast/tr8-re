# Bar chain: four bars per pattern

Play a pattern as **four bars**, each with its **own A and B step set**. Hold VARIATION A and
press pad 1..4 to pick a bar and its A side, hold VARIATION B and press pad 1..4 for the same bar
on its B side. A bar that has not been recorded is the pattern itself (its A steps on the A side,
its B steps on the B side), so a pattern sounds exactly as before until a bar is edited.

Every pattern has its own four bars and its own chain. Switching pattern switches the phrase;
nothing is carried from one pattern to another and nothing is overwritten.

Status: **works in emulation** (`tests/emu_chain.py`, 79 checks). Not yet tested on hardware.
Like the other patches it is built from your own copy of Roland's v1.61 file.

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_chain.BIN --patch chain
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first). This patch is standalone for now:
it uses the two developer-dump regions, and so do `motion` and `poly`.

| Gesture | Result |
|---|---|
| Hold **VARIATION A**, press pad 1..4 | Bar *n* becomes the bar being edited and played, on its **A** steps. The display shows `  1A` |
| Hold **VARIATION B**, press pad 1..4 | The same bar on its **B** steps. The display shows `  1B` |
| Hold **A + B**, press pad 1..4 | The chain is *n* bars long. The display shows `CH 1`..`CH 4` |
| Hold **A + B + CLEAR**, press a pad | Chain off, back to the stock single-bar A/B behaviour. The display shows `CH--` |
| Press **A** (no pad) | Loop the selected bar's A steps, as before |
| Press **B** (no pad) | Loop the selected bar's B steps, as before |
| Press **A + B** (no pad) | Play the chain: bars 1..*n*, each on its own A or B side |

Selecting a bar also records its side in the chain: `A + pad 3` makes bar 3 the third bar and
plays it on A, `B + pad 2` makes bar 2 play on B. Selecting a bar past the current length
extends the chain, so the four gestures `A + pad 1,2,3,4` alone give a four-bar chain. Bars that were never
selected are the pattern's own steps.

The pads only ever choose a bar 1..4; pads 5..16 stay ordinary step pads and LAST STEP + pad
still sets the pattern length (the poly gesture), because LAST STEP wins over A/B in the patch.

## A typical session

1. On pattern 1, hold **A** and press pads **1, 2, 3, 4** in turn: the panel selects bar 1, 2, 3,
   4, each on its A side. The display confirms each bar.
2. With TR-REC, record different steps into bar 1 and bar 2. Selecting a bar loads its content, so
   each bar keeps its own steps.
3. Hold **B** and press pad 1..4 to record the B side of the same four bars.
4. Press **A + B**: the four bars play in order and wrap. Press **A** or **B**: that side of the
   selected bar loops (editing mode).
5. Select pattern 2: it has its own four bars and its own chain. Pattern 1's bars are unchanged;
   select pattern 1 again to hear them.

## Behaviour

- **Four bars per pattern.** Bars are numbered 1..4 by the pad; pads 5..16 do not select bars.
- **A and B are independent step sets of the same bar**, not the pattern's stock pair: a recorded
  bar has its own 26 step rows for A and for B, plus its own LAST_A/LAST_B. Both sides are
  recordable.
- **Unrecorded bars are the pattern.** A bar with no saved content plays area 4 slot *pattern+1*
  (the pattern's own steps) on the selected side. With no bar recorded, the pattern is stock.
- **The chain is per pattern.** Bits and length live in the pattern's own Ptn2 parameters (below),
  so each pattern's four bars form its own loop. A plain pattern change never rewrites a chain.
- **Only A+B plays the chain.** With the panel on A or B, the sequencer loops that side of the
  selected bar (stock behaviour). The chain starts at bar 1 on every sequencer start and advances
  one bar per pattern wrap.
- **The selected bar is what TR-REC edits.** Selecting a bar loads its steps into the working copy
  (area 4 slot 0) and applies them to the sound; the stock step pads, TR-REC, LAST STEP and
  CLEAR then work on that bar.
- **A bar carries its steps, its LAST_A/LAST_B and its scale.** The scale is in the log entry, so
  a scale change is kept with the bar (the redirected save never writes the pattern slot).
  Weak accents and flams are area-6 parameters and stay with the pattern, shared by its bars.
- **A pattern change selects bar 1** of the new pattern and, on the next pad press or restart,
  loads its content.
- **Power off and on keeps the bars and the chain**; the log is flash and is rescanned on the
  first use.
- The display confirms each gesture; the pads keep showing steps, not bars.

## How it works

| Site | Original | New |
|---|---|---|
| `0x60009614` in `FUN_600095F0` | `bl FUN_6000E404` (apply `VARI`) | `bl chain_var` |
| `0x600098CA` in `FUN_6000989C` | `bl FUN_600095F0` (pattern wrap) | `bl chain_wrap` |
| `0x60013842` in `FUN_600137DE` | `bl FUN_60013B34` (press dispatch) | `bl chain_press` |
| `0x600137D2` in `FUN_6001377C` | `bl FUN_60013B56` (release dispatch) | `bl chain_release` |
| `0x600199F6` in `FUN_6001961E` | `bl FUN_60013168` (LAST STEP check) | `bl chain_pad` |
| `0x6001B7F4` in `FUN_6001B7D8` | `bl FUN_6000FC78` (pattern save) | `bl chain_commit` |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the regions) |

`FUN_600095F0` restarts the pattern at start and at every wrap
([FINDINGS.md](FINDINGS.md) section 7, "Pattern restart and variation"). It first fills the
player struct `0x6012FA64` from area 4 slot 0 (the working copy) and reads the last step after
applying the variation. `chain_var` replaces the variation call inside it: with a chain and
`VARI` = 2 (A+B) it picks the bar, writes that bar's content into the player struct and calls
`FUN_6000E152` to put its A or B masks into the sound. Without a chain, or with `VARI` = 0/1, it
calls the original `FUN_6000E404`.

`chain_wrap` replaces the wrap call and sets a flag around `FUN_600095F0`, so `chain_var` knows
whether this restart is a wrap (advance) or a start (bar 1). Playback never changes the pattern,
the panel selection or the working copy.

**The gesture lives on the press, not in the button handler.** Every button event is offered to
the active screen first: the type 5 (press) handler `FUN_600137DE` sets the held bit and then
calls `FUN_60013B34(id)` (`bl` at `0x60013842`), which gives the screen the press; only when the
screen declines it does the global button handler `FUN_6001961E` run (`0x60013F74`). That is why
LAST STEP + pad reaches `FUN_6001961E` (the screen declines LAST STEP) but a bare pad press never
does: the screen takes it as a step edit or a sound audition. `chain_press` replaces the dispatch
call itself, before the screen: with VARIATION A and/or B held, no LAST STEP and a pad 1..4 it
selects the bar and returns 1, so the screen never sees the pad; otherwise it forwards the id to
`FUN_60013B34` unchanged. `chain_release` replaces the matching `bl FUN_60013B56` at `0x600137D2`
and swallows the release of a pad whose press was taken, so the screen never gets a release
without a press. `chain_pad` still replaces the LAST STEP test in the step-pad branch of
`FUN_6001961E` (pad id still in `r6`, moved to `r0` by a naked trampoline); it keeps the stock
LAST STEP path and is a fallback if a pad press with A/B held ever reaches that branch.

### Editing a bar

TR-REC, the step pads and LAST STEP write area 4 slot 0, so a bar is edited by making it the
working copy:

1. the bar being left is appended to the log (`store_save`), so its steps are never lost,
2. the new bar's content is written into slot 0 (rows, LAST_A, LAST_B, scale, VARI = the selected
   side); a bar with no log entry copies the whole pattern slot,
3. the player struct and the sound masks are filled from slot 0, so the bar plays while it is
   edited,
4. its chain bit and the length are written with the firmware's own Ptn2 setter (which marks the
   pattern changed and leads to the normal save).

No pattern switch happens: `Setup[2]`, the panel's pattern number and the kit are untouched, and
there is no area-6 reload. That is the difference from the earlier "bar = pattern" build.

### Storage

**Working copy.** Area 4 slot 0 is the pattern being edited, as stock. The bar is a copy of that
slot's step rows, so the stock handlers do the editing.

**Bar log.** Extra bar content lives in the unused flash between the application image and the
user area, `0x3DB000`-`0x3DFFFF`:

| Range | Use |
|---|---|
| `0x3DF000`, `0x3DE000`, `0x3DD000`, `0x3DC000` | four log blocks, 32 entries each |
| `0x3DB000` | scratch block for compaction |

An entry is 128 bytes (32 words):

| Word | Content |
|---|---|
| 0 | magic `0x31524256` (`"VBR1"` little-endian) |
| 1 | sequence number, pattern `<< 16`, bar `<< 20` |
| 2 | `LAST_A | LAST_B << 8` |
| 3 | FNV-1a checksum of the other 31 words |
| 4..29 | 26 step rows, `A mask | B mask << 16` |
| 30 | scale (0..3, the map 8/4/6/3) |
| 31 | 0 (part of the checksum) |

The log is append-only: one save is one 128-byte program, no erase, so a torn write can only lose
the newest entry and never a pattern. When the write pointer reaches a block that is still in use,
the block with the fewest live entries is compacted: its live entries (the newest per
pattern/bar) are copied to the scratch block, the block is erased and they are written back. That
block always keeps a free slot, because there are only 64 live entries (16 patterns x 4 bars) and
128 slots. The newest entry per `(pattern, bar)` wins by sequence number, so the scan is correct
after the ring wraps or a block is compacted; the log is scanned once on first use, after which a
static index of 64 bytes points at each bar's newest entry.

**Pattern save is redirected.** The firmware's pattern save (`FUN_6001B7D8` -> `FUN_6000FC78`)
normally copies area 4 slot 0 over slot *n+1*. `chain_commit` replaces that call for area 4:
instead of the copy it appends the working copy as the current `(pattern, bar)` entry. So area 4
slot *n+1* keeps the pattern's **own** steps, which is exactly what an unrecorded bar plays, and
the pattern is never overwritten with one of its bars. If the save names a pattern the patch has
not loaded (the firmware also saves a pattern the panel only just selected), the working copy is
that pattern and not a bar, so the stock commit runs instead. The area-6 half of the save (weak
accents, flams, the chain parameters) goes through the stock commit unchanged.

**Chain parameters.** Index 15 (global id `0x136`) holds one bit per bar (1 = B), index 16
(`0x137`) the length (0 = no chain, 1..4). They are written with the firmware's Ptn2 setter and
saved with the pattern by the stock area-6 commit, so each pattern keeps its own chain. The poly
patch uses indices 4..14 (`0x12B`..`0x135`) and leaves these two alone; a future combined build
can use both. The updater does not write the log blocks, so a firmware update keeps the bars
(another patch must not claim that flash).

**Backup caveats.** The USB backup stores named parameters only, so neither the Ptn2 chain nor the
bar log is in it: after a restore, the patterns are back to their own steps and every bar falls
back to the pattern. Also, the backup reads area 4 slot 0, which is the selected bar while a bar
is selected, so take a backup with the chain off (or after a fresh start) to capture the
pattern's own steps.

### Code space

The payload uses the two developer-dump regions
(`0x60011150`-`0x60011464` and `0x60011488`-`0x60011BB6`): 584 bytes of `.text.far` plus 1 byte of
`.data` in the first (788 available), 1600 bytes of `.text` plus 214 bytes of `.bss` in the second
(1838 available). The literal pool between them (`0x60011464`-`0x60011484`) is live firmware data
and is never written. The probe build (`payload_probe.json`) needs 460 + 14 bytes. That is why the
patch is standalone for now: `motion-poly` already uses both regions, and a combined build needs
the "grow the image" method or another dead-code region
([DEVELOPING.md](DEVELOPING.md) "Code space").

## Why not a real 32- or 64-step pattern

The step masks, the last-step values, the fills and the panel are all 16-step; a 32-step view
needs a page selector that the 16 pads do not provide, and wider masks in every parameter and
handler. Four bars per pattern give a 64-step phrase from bars that each already have 16 steps,
with no change to the step engine. Each bar still has both A and B sides, so the usable material
is 4 bars x 2 sides per pattern, independent for all 16 patterns.

## If the gesture does nothing

1. **Variation buttons first, pad second.** Hold A (or B, or A+B) and *then* press the pad; the
   press of the pad is what the patch sees. Pressing the pad first and adding A afterwards does
   nothing.
2. **Pads 1..4 only.** Pads 5..16 keep their stock step function.
3. **LAST STEP wins.** LAST STEP + pad is the pattern length (and the poly gesture); do not hold
   it when selecting a bar.
4. **The chain only plays with A+B selected.** A alone or B alone loops that side of the selected
   bar; that is the editing mode.
5. **The display is the feedback.** The pads keep showing steps; they never show bars.
6. **The build must be this one.** The first hardware build hooked the pad branch of
   `FUN_6001961E`, which a bare pad never reaches; A + pad showed nothing there (see "How it
   works"). Build the file again from the current tree and check the sha256.

The **probe build** shows what the firmware actually sees:

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_probe.BIN --patch chain-probe
```

It uses the same hooks and only displays, so it never writes the chain, a bar or the pattern:

| Display | Meaning |
|---|---|
| `St00` / `St11` / `St20` on start | payload runs; `St20` = panel VARI 2 (A+B), effective variation of the pass 0 |
| ` 1A-` (A + pad 1) | hook runs and the firmware reports VARIATION A held: the press never reached the screen |
| `12B-` (B + pad 12) | same for B, two-digit pad (pads 5..16 are not bars) |
| ` 3C-` (A+B + pad 3) | both variation buttons held |
| ` 3--` (plain pad 3) | hook runs on every press and sees no modifier; the text is written after the firmware handled the pad |
| ` 8-L` (LAST STEP + pad 8) | LAST STEP is held, so the press goes to the firmware first (pattern length) and the text is written after it |
| ` 3CL` (A+B + LAST STEP + pad 3) | the same with both variation buttons held: LAST STEP wins, no bar selection |
| nothing at all | the payload is not running: the build is not the patched one |

## Test history

- Emulation (`tests/emu_chain.py`): all six hook sites branch into the payload; the gesture
  through the press dispatch (`A/B + pad 1..4`, pads 5..16 forwarded, LAST STEP wins, length and
  chain off, display strings, release swallowed); bar selection and the working copy (bar 1 =
  pattern, bar 2 loaded after a save, last steps and B side); the pattern-save redirect (no
  pattern slot written, one log entry with the 26 rows and LAST_A/B, area 4 slot *n+1* unchanged);
  playback of a four-bar chain `A A B A` with the recorded bar's content (masks, last steps,
  scale), A/B bypass, stock
  toggle with no chain; a second pattern with its own bars and chain; a power cycle rescanning the
  log; compaction after more than a block of saves; the ring wrapped and every block compacted
  (192 saves over all 64 bars, each bar read back through the payload's index); the sequence
  number wrapping from 0xFFFF to 0 (an entry written after the wrap still wins); the stock commit
  for a pattern the patch has not loaded; `chain_wrap` marks the restart. The probe
  build (`--probe`, `payload_probe.json`): display strings on the press path and on the global
  LAST STEP branch, a pass-through save redirect, no pattern writes, `St` line on start.
- Hardware, first build (pad branch of `FUN_6001961E`): LAST STEP + pad set the pattern length,
  stock A/B alternation worked, A + pad showed nothing. Diagnosis: the screen takes a bare pad
  press, so the global button handler never runs for it; the press dispatch is the first code
  that can see the gesture.
- Hardware, second build (bar = pattern, press dispatch): A + pad 2 showed ` 2A` and selected
  pattern 2, A+B played the bars. Superseded by this build (four bars per pattern, its own A and
  B step set each); the old build remains recoverable from git (`bd94eef`).
- Hardware checklist for this build:
  1. Plain pattern, no bar selection: A, B and A+B behave exactly as stock.
  2. Hold A, press pads 1..4: the display shows `  1A`..`  4A`; with A+B all four bars play and
     wrap; A alone loops bar 1's A steps.
  3. Record steps into bar 1, select bar 2, record different steps; select bar 1 again: its steps
     are back. Do the same on the B side and check A/B are independent.
  4. Select bar 4 and back: the display follows the pad, the pattern number and kit do not change.
  5. Select patterns 2..5 and press A: each still sounds like its own stock pattern (no bar
     recorded there yet); pattern 1's four bars are unchanged when you return.
  6. Give pattern 2 its own four bars and chain; switch 1 <-> 2: each pattern plays its own
     phrase.
  7. Power cycle: bars, sides and chain are still there.
  8. Hold A+B and press pad 2: `CH 2`; A+B+CLEAR + pad: `CH--` and the chain is off, but the
     recorded bars still play when selected with A / B.
  9. LAST STEP + pad still changes the pattern length, and the poly LAST STEP + instrument + pad
     gesture still works.
  10. Change the pattern: playback starts at bar 1 of the new pattern, and the previous
      pattern's bars are not overwritten.
