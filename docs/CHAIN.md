# Bar chain (more than two bars)

Play a pattern as a sequence of bars: bar 1, bar 2, ... up to 16 bars, each with its own steps,
scale and length. A four-bar loop with a fill is four bars; an eight-bar phrase is eight. A bar
is a **pattern variation**, so a bar has real, independent step content, not a replay of one of
two passes: the 16 patterns x 2 variations are a pool of 32 bars, and the song picks bars out
of that pool.

Status: **works in emulation** (`tests/emu_chain.py`). The gesture sits on the button press
itself (see "How it works"), the earlier hook in the button handler could never be reached on a
unit. This build (bar = pattern) is not yet tested on hardware. Like the other patches it is
built from your own copy of Roland's v1.61 file.

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_chain.BIN --patch chain
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first). This patch is standalone for now:
it uses the two developer-dump regions, and so do `motion` and `poly`.

| Gesture | Result |
|---|---|
| Hold **VARIATION A**, press pad *n* | Bar *n* plays variation A of **pattern *n***. The display shows `  1A`, ` 12A` |
| Hold **VARIATION B**, press pad *n* | Bar *n* plays variation B of pattern *n*. The display shows `  1B`, ` 12B` |
| Hold **A + B**, press pad *n* | The chain is *n* bars long. The display shows `CH 4`, `CH12` |
| Hold **A + B + CLEAR**, press a pad | Chain off, back to the stock behaviour. The display shows `CH--` |
| Press **A** (no pad) | Edit and loop variation A, as before |
| Press **B** (no pad) | Edit and loop variation B, as before |
| Press **A + B** (no pad) | Play the song (stock: alternate A and B) |

Painting a bar past the current length extends the chain; bars that were never painted are the
**A** variation of their pattern. Painting bar *n* also **selects pattern *n* for editing** (the
panel shows that pattern, and the panel variation becomes A or B), because TR-REC records into
the selected pattern. So paint the song, then press **A + B** to hear it. Pressing A or B at any
time takes playback off the song and loops that variation of the current pattern, which is how
one bar is edited or auditioned.

Because each bar is a whole pattern, painting a bar also changes the pattern the panel is on.
The song follows the selection: every gesture saves the pattern it leaves and writes the song
into the pattern it selects, so **after painting, the song lives in the pattern the panel
shows** (the last bar painted) and each pattern you passed through holds a saved copy of the
song as it stood when you left it.

### A typical session

1. Starting on pattern 1, hold **A** and press pads **1, 2, 3, 4**: bars 1-4 are the A variation
   of patterns 1-4. Record each bar's steps with TR-REC while it is selected (the panel already
   follows the bar).
2. Hold **B** and press pads **5, 6, 7, 8**: bars 5-8 are the B variation of patterns 5-8.
3. Press **A + B**: the eight-bar song plays, starting at bar 1 on every start.
4. Hold **A + B** and press pad 6 to make it six bars; **A + B + CLEAR** + pad turns the chain
   off and restores the stock A/B alternation.

A song with *n* bars uses patterns 1..*n*: those patterns are the bars, and selecting them
without a chain plays them stock. The pool is shared, so the same pattern can be a bar in any
number of songs. After step 2 the panel shows pattern 8; that pattern's Ptn2 copy holds the
eight-bar song.

## Behaviour

- The chain belongs to the pattern and is saved with it like any other edit (the firmware saves
  a pattern automatically). Every gesture saves the pattern it leaves (area 4 and area 6, the
  same two commits the firmware uses on a pattern change) and writes the song into the pattern
  it selects, so the selected pattern always holds the current song and older ones keep the
  version they had when you left them.
- Power off and on keeps it: the pattern the panel showed after painting still has the song;
  press A+B.
- The song plays only while the panel is in **A+B**. A or B loops that variation (stock), which
  is the editing mode.
- The song starts at bar 1 every time the sequencer starts, and advances one bar per pattern
  wrap. It does not use the stock A/B alternation while it plays.
- A bar's step content is the pattern's step content: masks, scale, LAST STEP and variation all
  come from the bar's pattern. The **area-6 parameters (weak accent, flams) come with the bar's
  pattern** too, since area 6 is loaded and saved with it; only the **kit** stays with the
  current pattern (it is a separate area, not part of a pattern).
- With no chain everything behaves exactly as stock.
- Up to 16 bars. The display confirms every gesture; the pads keep showing steps, not the song.

## How it works

| Site | Original | New |
|---|---|---|
| `0x60009614` in `FUN_600095F0` | `bl FUN_6000E404` (apply `VARI`) | `bl chain_var` |
| `0x600098CA` in `FUN_6000989C` | `bl FUN_600095F0` (pattern wrap) | `bl chain_wrap` |
| `0x60013842` in `FUN_600137DE` | `bl FUN_60013B34` (press dispatch) | `bl chain_press` |
| `0x600137D2` in `FUN_6001377C` | `bl FUN_60013B56` (release dispatch) | `bl chain_release` |
| `0x600199F6` in `FUN_6001961E` | `bl FUN_60013168` (LAST STEP check) | `bl chain_pad` |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the regions) |

`FUN_600095F0` restarts the pattern at start and at every wrap
([FINDINGS.md](FINDINGS.md) section 7, "Pattern restart and variation"). It first fills the
player struct `0x6012FA64` from area 4 slot 0 (the working copy) and reads the last step after
applying the variation. `chain_var` replaces the variation call inside it: with a chain and
`VARI` = 2 (A+B) it takes the effective variation from the chain, then fills the player struct
**from the bar's own pattern slot** and calls `FUN_6000E152` to put that variation's masks into
the sound. Without a chain, or with `VARI` = 0/1, it calls the original `FUN_6000E404`.

The bar's content comes from area 4 slot *n+1* (pattern *n*), or from slot 0 when the bar is the
pattern that is currently selected, which is already the working copy. The fill writes the 26
A/B mask pairs, LAST_A/LAST_B and the scale through `FUN_6000E0E0` (scale 0..3 -> 8, 4, 6, 3).
No pattern is selected or loaded during playback: the chain is not disturbed, and the sound
follows the bar from one wrap to the next.

`chain_wrap` replaces the wrap call and sets a flag around `FUN_600095F0`, so `chain_var` knows
whether this restart is a wrap (advance) or a start (`0x600091A2`, `0x600098E4`; bar 1).

**The gesture lives on the press, not in the button handler.** Every button event is offered
to the active screen first: the type 5 (press) handler `FUN_600137DE` sets the held bit and then
calls `FUN_60013B34(id)` (`bl` at `0x60013842`), which gives the screen the press; only when the
screen declines it does the global button handler `FUN_6001961E` run (`0x60013F74`). That is why
LAST STEP + pad reaches `FUN_6001961E` (the screen declines LAST STEP) but a bare pad press never
does: the screen takes it as a step edit or a sound audition. The first hardware build put the
gesture in the pad branch of `FUN_6001961E`, and on the unit A + pad did nothing, exactly as
that path predicts. `chain_press` replaces the dispatch call itself, before the screen: with
VARIATION A and/or B held and no LAST STEP it paints/lengths the chain and returns 1, so the
screen never sees the pad; otherwise it forwards the id to `FUN_60013B34` unchanged.
`chain_release` replaces the matching `bl FUN_60013B56` at `0x600137D2` and swallows the release
of a pad whose press was taken, so the screen never gets a release without a press.

`chain_pad` still replaces the LAST STEP test at the head of the step-pad branch of
`FUN_6001961E`, where the pad id is still in `r6`; a naked trampoline moves it to `r0`. It keeps
the stock LAST STEP path (return the stock condition) and is a fallback for a pad press that ever
does reach that branch with A/B held; LAST STEP wins over the chain gesture there, so the poly
gesture keeps working.

### Editing a bar

TR-REC writes into area 4 slot 0, so a bar's pattern has to be the working copy to record into
it. Painting bar *n* therefore does a real pattern switch with the verified primitives, in the
same order the firmware uses (`FUN_6001B7D8` saves, `FUN_6001B842` loads):

1. save the pattern being left: `FUN_6000FC78(0, 4, cur+1, 0)` (Ptn) and
   `FUN_6000FC78(0, 6, cur+1, 0)` (Ptn2). The firmware's pattern save does exactly these two
   commits. Area 6 slot 0 still holds the song as it stood before this bar was added, so the
   pattern being left keeps a saved copy up to the previous gesture,
2. copy area 4 slot *n* and area 6 slot *n* into slot 0 (`FUN_6000F3C2` + `FUN_6000F3EC`, the
   firmware's own slot copy; it also notifies slot 0). Area 6 must be loaded as well, or the
   next save would write the previous pattern's weak accents and flams into this one,
3. write the song (chain bits and length) into the new area 6 slot 0 again, so it is carried to
   the pattern now selected rather than replaced by that pattern's own chain,
4. write `Setup[2]` (pattern that slot 0 belongs to) and `Setup[0xF]` (pattern shown by the
   panel) raw through the area-1 value pointer, so the panel and the save path agree,
5. fill the player struct from the new working copy and select the bar's variation.

The stock pattern-change function `FUN_6001B842` itself is not called: it also needs `Setup[5]`
notification, the storage lock and the HMI vtable, none of which exist in a headless test. The
primitives above are the parts of that path that matter, and they are exercised by
`tests/emu_chain.py` (the emulator runs the real slot copies and stubs only the flash commit).

### Storage

The chain is two of the Ptn2 parameters that no code reads and the firmware stores with every
pattern ([POLY.md](POLY.md) "Storage"): index 15 (global id `0x136`) holds one bit per bar
(1 = B), index 16 (`0x137`) holds the length (0 = no chain, 1..16). The gesture writes them with
the firmware's own Ptn2 setter, so the pattern is marked changed and saved as after any edit.
The poly patch uses indices 4..14 (`0x12B`..`0x135`) and leaves these two alone; a future combined
build can use both.

### Code space

408 bytes of code in the first developer-dump region, 504 bytes (the bar edit and the LAST STEP
fallback) plus 14 bytes of state in the second: the first region holds 788 bytes
(`0x60011150`-`0x60011464`) and the second 1838 (`0x60011488`-`0x60011BB6`). The literal pool
between them (`0x60011464`-`0x60011484`) is live firmware data and is never written. The probe
build (`payload_probe.json`) needs 444 + 14 bytes. That is why the patch is standalone for now:
`motion-poly` already uses both regions, and a combined build needs the "grow the image" method
or another dead-code region ([DEVELOPING.md](DEVELOPING.md) "Code space").

## Why not a real 32- or 64-step pattern

The step masks, the last-step values, the fills and the panel are all 16-step; a 32-step view
needs a page selector that the 16 pads do not provide, and wider masks in every parameter and
handler. The chain gets longer phrases by arranging bars that already exist, each with its own
16 steps, and needs no change to the step engine. Since a bar is a whole pattern variation, the
step content is not limited to two passes any more; the only price is that a song occupies one
pattern per bar.

## If the gesture does nothing

1. **Variation buttons first, pad second.** Hold A (or B, or A+B) and *then* press the pad; the
   press of the pad is what the patch sees. Pressing the pad first and adding A afterwards does
   nothing.
2. **The song only plays with A+B selected.** A alone or B alone loops that variation; that is
   the editing mode. A+B is stock (press and hold one variation button, then press the other).
3. **The display is the feedback.** The pads keep showing steps; they never show the song.
4. **The build must be this one.** The first hardware build hooked the pad branch of
   `FUN_6001961E`, which a bare pad never reaches; A + pad showed nothing there (see "How it
   works"). Build the file again from the current tree and check the sha256.

The **probe build** shows what the firmware actually sees:

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_probe.BIN --patch chain-probe
```

It uses the same hooks and only displays, so it never writes the chain, the pattern or Setup:

| Display | Meaning |
|---|---|
| `St00` / `St11` / `St20` on start | payload runs; `St20` = panel VARI 2 (A+B), effective variation of the pass 0 |
| ` 1A-` (A + pad 1) | hook runs and the firmware reports VARIATION A held: the press never reached the screen |
| `12B-` (B + pad 12) | same for B, two-digit pad |
| ` 3C-` (A+B + pad 3) | both variation buttons held |
| ` 3--` (plain pad 3) | hook runs on every press and sees no modifier; the text is written after the firmware handled the pad |
| ` 8-L` (LAST STEP + pad 8) | LAST STEP is held, so the press goes to the firmware first (pattern length) and the text is written after it |
| ` 3CL` (A+B + LAST STEP + pad 3) | the same with both variation buttons held: LAST STEP wins, no chain edit |
| nothing at all | the payload is not running: the build is not the patched one |

## Test history

- Emulation (`tests/emu_chain.py`): the gesture through the press dispatch (`chain_press`), the
  real Ptn2 setter and the release path (`paint, extend, length, chain off, two digits, LAST STEP
  forwarded to the firmware, release swallowed, other Ptn2 ids untouched`); the edit switch
  (area 4 and area 6 of the pattern left are saved, working copy = the bar's pattern in both
  areas, the song written again into the new current pattern, `Setup[2]`/`Setup[0xF]`, the bar's
  variation written into the pattern and the player); playback with five distinct pattern
  slots (`A A B A`: start at bar 1, bar *n* uses area 4 slot *n+1*, slot 0 when it is the current
  pattern, masks / LAST STEP / scale from that slot, A/B bypass, stock toggle with no chain,
  chain shorter than the stored bits); `chain_wrap` marks the restart; all five hook sites
  branch into the payload. The probe build (`--probe`, `payload_probe.json`): display strings on
  the press path and on the global LAST STEP branch, no pattern writes, LAST STEP does not set a
  length, `St` line on start.
- Hardware, first build (pad branch of `FUN_6001961E`): LAST STEP + pad set the pattern length,
  stock A/B alternation worked, A + pad showed nothing. Diagnosis: the screen takes a bare pad
  press, so the global button handler never runs for it; the press dispatch is the first code
  that can see the gesture.
- Hardware checklist for the current build:
  1. Press A+B with no chain: stock A/B alternation still works.
  2. Hold A, press pads 1, 2, 3; hold B, press pad 4: the display confirms each bar and the
     panel selects patterns 1, 2, 3, 4 in turn; with A+B the four bars play A A A B and the
     tempo display comes back.
  3. Record different steps into bar 1 and bar 2 (TR-REC) and hear them in the song; editing
     bar 2 must not change bar 1.
  4. Stop and start: the song starts at bar 1 again.
  5. The panel shows the last bar's pattern after painting; press A+B there: the song plays.
     Power cycle and press A+B on that pattern: still there. Select an earlier painted pattern:
     it has the song as it stood when you left it, and its weak accents and flams are its own
     (the area-6 load, not the pattern you painted from).
  6. The bar's own LAST STEP and scale play on that bar (set a shorter bar 2).
  7. Press A, then A+B: auditioning one variation does not disturb the song.
  8. Hold LAST STEP and press a pad: the pattern length still changes (no bar painted).
  9. The step LEDs follow the selected bar's pattern; check that the panel's pattern number and
     kit follow the bar switch (they are written raw, see "Editing a bar").
  10. Paint a song, then select patterns 5..16 stock: their weak accents and flams must be
      unchanged (the area-6 load/save), and each keeps its own chain.
