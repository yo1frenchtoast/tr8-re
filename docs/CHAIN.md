# Bar chain: four bars per pattern, a sequence per variation side

Play a pattern as **four bars**, each with its **own A and B step set**. Hold VARIATION A and
press pad 1..4 to pick a bar and its A side, hold VARIATION B and press pad 1..4 for the same bar
on its B side. A bar that has not been recorded is the pattern itself (its A steps on the A side,
its B steps on the B side), so a pattern sounds exactly as before until a bar is edited.

Each side plays its bars in order: **A plays bars 1..Na with the A steps, B plays bars 1..Nb with
the B steps, and A+B plays the A sequence and then the B sequence.** A side's length is the
highest bar selected on that side (1..4), so A can be a two-bar phrase while B is four bars. A
side that was never selected stays stock.

Every pattern has its own four bars and its own two lengths. Switching pattern switches the
phrases; nothing is carried from one pattern to another and nothing is overwritten.

Status: **works in emulation** (`tests/emu_chain.py`, 188 checks). The eighth build (per-side
sequences, green/blink row, stopped editing, bar jump) is confirmed on hardware; the step view
following the bar that is playing is emulation-tested and pending on the unit.
Like the other patches it is built from your own copy of Roland's v1.61 file.

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_chain.BIN --patch chain
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first). This patch is standalone for now:
it uses the two developer-dump regions, and so do `motion` and `poly`.

| Gesture | Result |
|---|---|
| Hold **VARIATION A**, press pad 1..4 | Bar *n* becomes the bar being edited, on its **A** steps, and the A side becomes at least *n* bars long. The display shows `  A1`..`  A4` |
| Hold **VARIATION B**, press pad 1..4 | The same bar on its **B** steps; the B side becomes at least *n* bars long. The display shows `  B1`..`  B4` |
| Hold **A + B**, press pad 1..4 | Both sides are *n* bars long (extend or shrink). The display shows `AB 1`..`AB 4` |
| Hold **A + B + CLEAR**, press a pad | Both sides back to stock (no bar sequence). The display shows `AB--` |
| Press **A** (no pad) | Play the A sequence: bars 1..Na, A steps |
| Press **B** (no pad) | Play the B sequence: bars 1..Nb, B steps |
| Press **A + B** (no pad) | Play the A sequence and then the B sequence, wrapping |

A side's length is the highest bar selected on it, so `A + pad 3` gives A three bars and `B + pad 2`
gives B two. Selecting a lower bar again does not shrink that side; use `A+B + pad n` to set both
sides to *n*, or `A+B+CLEAR + pad` to reset them. A side that has never been selected stays stock:
on the panel, A with no A bars loops the working copy's A side exactly as before. Bars that were
never selected are the pattern's own steps.

Selecting a bar does not depend on the transport: with the machine **stopped**, `A + pad 2`
loads bar 2 into the working copy and redraws the step view at once, so the step pads and TR-REC
edit bar 2; `A + pad 1` stores bar 2 and switches to bar 1, and `A + pad 2` brings it back. The
selection is also a **jump**: the playhead moves to that bar, so while playing the next bar
boundary plays the selected bar (instead of the next one in the order) and the sequence carries
on from it, and while stopped the next start begins at that bar. A bar the side does not have
clamps to its first bar, and switching pattern puts the playhead back on bar 1. The
load sets the screen's "repaint the step view" bit (`0x04` in the halfword at `0x60149B8C`), which
the panel dispatcher serves on its next pass; see the note on the hardware freeze below. That is
the panel's screen object, not the Setup database `0x60149F38` — see
[FINDINGS.md](FINDINGS.md) section 11.

While the machine **plays**, the step view follows the bar that is playing: the step pads and
TR-REC show that bar, so a step recorded during playback lands in the bar you hear, and the view
moves on by itself at every bar boundary. Stopped, the view stays on the bar you selected. The
follow itself writes no flash: a bar nobody edited is never rewritten, so leaving it at a bar
boundary costs nothing (see Storage).

The pads only ever choose a bar 1..4; pads 5..16 stay ordinary step pads and LAST STEP + pad
still sets the pattern length (the poly gesture), because LAST STEP wins over A/B in the patch.

## A typical session

1. On pattern 1, hold **A** and press pads **1, 2, 3, 4** in turn: the panel selects bar 1, 2, 3,
   4, each on its A side, and the A side becomes four bars long. The display confirms each bar.
2. With TR-REC, record different steps into bar 1 and bar 2. Selecting a bar loads its content, so
   each bar keeps its own steps.
3. Hold **B** and press pad **1, 2**: the B side becomes two bars long. Record its steps.
4. Press **A**: the four A bars play in order and wrap. Press **B**: the two B bars play. Press
   **A + B**: the A sequence plays, then the B sequence. Hold A or B to see that side's bar row.
5. Select pattern 2: it has its own four bars and its own two lengths. Pattern 1's bars are
   unchanged; select pattern 1 again to hear them.

## Behaviour

- **Four bars per pattern.** Bars are numbered 1..4 by the pad; pads 5..16 do not select bars.
- **A and B are independent step sets of the same bar**, not the pattern's stock pair: a recorded
  bar has its own 26 step rows for A and for B, plus its own LAST_A/LAST_B. Both sides are
  recordable.
- **Unrecorded bars are the pattern.** A bar with no saved content plays area 4 slot *pattern+1*
  (the pattern's own steps) on the selected side. With no bar recorded, the pattern is stock.
- **Each side has its own length and plays its own bars.** Na and Nb live in the pattern's own
  Ptn2 parameter (below). A plays bars 1..Na with the A steps, B plays 1..Nb with the B steps, and
  A+B plays the A sequence then the B sequence. A side whose length is 0 is never selected: with
  the panel on that side the stock variation runs, and A+B plays only the other side.
- **A plain pattern change never rewrites a sequence.** Each pattern's bars and lengths are its
  own.
- **Every sequence starts at bar 1** on a sequencer start and advances one bar per pattern wrap;
  the A+B sequence wraps from the last B bar back to the first A bar.
- **TR-REC edits the bar the step view shows: the selected one, or while playing the one you
  hear.** Selecting a bar loads its steps into the working copy (area 4 slot 0) and applies them
  to the sound; the stock step pads, TR-REC, LAST STEP and CLEAR then work on that bar. During
  playback the step view follows the playing bar instead (`chain_view`, below), so the bar on the
  pads is always the bar being heard. The load marks the panel's step view for a
  repaint (`0x04` in the screen object's bit word), so the screen redraws the newly selected bar
  on its next pass instead of waiting for some other change; selecting another bar stores the one
  you leave, and leaving a bar nobody edited writes nothing. The repaint is deliberately deferred:
  an earlier build called the firmware's synchronous "slot 0 changed" notification
  (`FUN_60010148(dispatcher, {0, 4})`) from inside the button dispatch, which froze the unit (see
  the hardware note below).
- **A bar carries its steps, its LAST_A/LAST_B and its scale.** The scale is in the log entry, so
  a scale change is kept with the bar (the redirected save never writes the pattern slot).
  Weak accents and flams are area-6 parameters and stay with the pattern, shared by its bars.
- **A pattern change selects bar 1** of the new pattern and, on the next pad press or restart,
  loads its content.
- **Power off and on keeps the bars and the lengths**; the log is flash and is rescanned on the
  first use, and the lengths are ordinary pattern parameters. A firmware update erases the log
  (but not the lengths): the bars then fall back to the pattern's own steps.
- **A bar select is a jump.** `A/B + pad n` moves that side's playhead to bar *n*: while the
  machine plays, the next bar boundary plays bar *n* and the sequence continues from it; while it
  is stopped, the next start begins at bar *n*. Selecting the bar that is already playing repeats
  it once at the next boundary. A fresh patch state and a pattern change start at bar 1, and a
  bar the side does not have clamps to its first bar.
- The display confirms each gesture. While VARIATION A or B is **held**, the pads become that
  side's bar row: the bars the side has are green, the bar at that side's head blinks yellow (it
  is the bar being played, or, stopped, the bar last selected on that side), and the remaining
  pads are off, so only that side's bars are lit. This works in
  every screen (sequencer, PTN SELECT, TR-REC, ...) and after a pattern change. Releasing the
  button gives the pads back to whatever the screen was showing (A+B keeps the length gesture and
  leaves the pads stock). A save the flash chip refused shows **`FAIL`** instead of the bar
  number (see Storage).
- The bar number (`  A1`) is only the confirmation of the pad press. Releasing VARIATION A or B
  calls the firmware's own repaint helper `FUN_60051E20` (`0x44` on the panel object
  `0x60149B8C`), so the panel redraws its pads and its own numeric text on the next pass and the
  display returns to its normal view instead of staying on the bar
  ([FINDINGS.md](FINDINGS.md) section 11).

## How it works

| Site | Original | New |
|---|---|---|
| `0x60009614` in `FUN_600095F0` | `bl FUN_6000E404` (apply `VARI`) | `bl chain_var` |
| `0x600098CA` in `FUN_6000989C` | `bl FUN_600095F0` (pattern wrap) | `bl chain_wrap` |
| `0x60016C44` in `FUN_60016C08` | `bl FUN_60016386` (paint the step pads) | `bl chain_view` |
| `0x60013842` in `FUN_600137DE` | `bl FUN_60013B34` (press dispatch) | `bl chain_press` |
| `0x600137D2` in `FUN_6001377C` | `bl FUN_60013B56` (release dispatch) | `bl chain_release` |
| `0x60017748` in `FUN_6001773A` | `bl FUN_6004BB4C` (raw LED setter) | `bl chain_led4` |
| `0x6001776C` in `FUN_6001774E` | `bl FUN_6004BB4C` (palette LED setter) | `bl chain_led4` |
| `0x60017E18` in `FUN_60017E08` | `bl FUN_6004BB4C` (raw setter copy) | `bl chain_led4` |
| `0x60017E3A` in `FUN_60017E1E` | `bl FUN_6004BB4C` (palette setter copy) | `bl chain_led4` |
| `0x6001B7F4` in `FUN_6001B7D8` | `bl FUN_6000FC78` (pattern save) | `bl chain_commit` |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the regions) |

The probe build also replaces `0x600199F6` in `FUN_6001961E` (`bl FUN_60013168`, the LAST STEP
test of the step-pad branch) with `bl chain_pad`; the real build does not, to make room in the
second region (see Code space).

`FUN_600095F0` restarts the pattern at start and at every wrap
([FINDINGS.md](FINDINGS.md) section 7, "Pattern restart and variation"). It first fills the
player struct `0x6012FA64` from area 4 slot 0 (the working copy) and reads the last step after
applying the variation. `chain_var` replaces the variation call inside it: it reads the two side
lengths, picks the bar and the side of this pass, writes that bar's content into the player
struct and calls `FUN_6000E152` to put its A or B masks into the sound. With no length set, or
with the panel on a side that has no bars, it calls the original `FUN_6000E404`.

`chain_wrap` replaces the wrap call and sets a flag around `FUN_600095F0`, so `chain_var` knows
whether this restart is a wrap (advance) or a start (bar 1). The tick never changes the pattern,
the panel selection or the working copy: it only fills the player struct.

**The step view follows the playing bar.** The panel paints the step pads from `FUN_60016C08`, the
dispatcher that serves the screen object's repaint bits. Bit `0x04` is the step view: the
dispatcher calls `FUN_60016386` (`bl` at `0x60016C44`) with the panel object in `r0`. `chain_view`
replaces that call. When the sequencer runs and the bar and side it last played differ from the
working copy's (`cur_bar`, `cur_side`), it stores the bar being left and loads the playing one into
area 4 slot 0 with the same `slot_load` the gesture uses, then tail-calls the original paint
(`0x60016387`) with the object unchanged. So the step pads, TR-REC and the sound agree on the bar,
and the load happens in the panel's own pass rather than in the tick or the button dispatch. It
calls `sync()` first, like the gesture does, so a pattern switched while the view was stale is
noticed before anything is stored. Stopped, it does nothing: the working copy stays on the bar the
user selected.

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
without a press.

**The bar row.** Every screen paints the 16 pads through one of four tiny setters, so the hook is
inside them rather than on a view:

| Setter | Signature | Hook |
|---|---|---|
| `FUN_6001773A` | raw `(led, a, b, c)` | `0x60017748` |
| `FUN_6001774E` | palette `(led, colour)` | `0x6001776C` |
| `FUN_60017E08` | raw copy `(led, a, b)` | `0x60017E18` |
| `FUN_60017E1E` | palette copy `(led, colour)` | `0x60017E3A` |

All four end in `bl FUN_6004BB4C`, a veneer to the fast-code LED function `0x01000537` called as
`(object 0x601488D0, led, a, b, c)`. `chain_led4` replaces those four calls and gets the resolved
triple, so it does not care whether the caller used raw levels or a palette colour:

- pads 1..N of the side whose button is held (`led` `0x1D` onward): `(1, 9, 2)` = palette
  `0x2A`, the pattern-length green; the bar at that side's head gets `(1, 0, 6)`, which is the
  play colour's blink flag (`b` = 0) on the yellow colour (`c` = 6), so the head blinks yellow.
  Stopped, the selected bar of that side is the head and blinks,
- every other pad in the same state, including pads N+1..16: `(0, 0, 2)` = palette `0x2D`, off,
  so only the bars that side has are lit,
- everything else (any other LED, or neither/both buttons held) is forwarded unchanged.

Because the hook is in the setters, the row appears in every screen (sequencer, PTN SELECT,
TR-REC, LAST STEP, ...) and keeps working after a pattern change, which is when the screen
switches to another renderer. Each side has its own head, so holding A while the B side plays
shows the A row's own head blinking. A+B is excluded on purpose: it is the both-sides gesture,
not bar selection.

### Editing a bar

TR-REC, the step pads and LAST STEP write area 4 slot 0, so a bar is edited by making it the
working copy:

1. the bar being left is appended to the log (`store_save`), so its steps are never lost,
2. the new bar's content is written into slot 0 (rows, LAST_A, LAST_B, scale, VARI = the selected
   side); a bar with no log entry copies the whole pattern slot,
3. the player struct and the sound masks are filled from slot 0, so the bar plays while it is
   edited,
4. the screen's step-view repaint bit (`0x04` in the halfword at `0x60149B8C`) is set, so the
   panel redraws the step pads and the view on its next pass and they show the bar that was
   loaded. Without this the step view kept the previous bar until something else refreshed it —
   the machine being stopped made that obvious. The earlier build sent the firmware's synchronous
   slot-0 notification here instead; that walk of the screen observers from inside the press
   dispatch froze the unit, so the deferred bit is used now,
5. the side's length in Ptn2 is raised to at least the bar number (A+B sets both lengths),
   with the firmware's own Ptn2 setter (which marks the pattern changed and leads to the normal
   save).

Nothing here depends on the transport: `A + pad` while stopped loads the bar for editing exactly
as it does while playing, and `A + pad` again switches to another bar.

No pattern switch happens: `Setup[2]`, the panel's pattern number and the kit are untouched, and
there is no area-6 reload. That is the difference from the earlier "bar = pattern" build.

### Storage

**Working copy.** Area 4 slot 0 is the pattern being edited, as stock. The bar is a copy of that
slot's step rows, so the stock handlers do the editing.

**Bar log.** Extra bar content lives in the unused flash between the application image and the
user area, `0x3DB000`-`0x3DFFFF`:

| Range | Use |
|---|---|
| `0x3DC000`..`0x3DFFFF` | four log blocks of 32 entries; entry *i* is at `0x3DC000 + i * 128` |
| `0x3DB000` | scratch block for compaction |

The first builds placed entry *i* at `0x3DF000 - (i / 32) * 0x1000 + (i % 32) * 128`, which covers
the same 16 KB in the opposite block order: the addressing was made a plain multiply, so an
upgrade keeps the bars already stored.

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

**Write session.** The three raw primitives only move data; they do not touch the flash chip's
block protection. While the status register protects the array (the state the firmware leaves it
in), a program or erase is silently dropped by the chip. The stock store therefore brackets its
own erase/program sequence with `FUN_600108AA` (write status register `0x00`, indirect mode) and
`FUN_600108BA` (memory-mapped mode, write status `0x3C`, protected again); one session covers many
operations. The payload does the same: `fl_erase`, `fl_write` and `fl_put` each open the session,
do one operation and close it, and `fl_put` reads the entry's magic back. A save that did not land
shows **`FAIL`** on the numeric display instead of the bar number. (The first hardware build
called the primitives without the session, so every program was dropped: edits vanished and a
revisited bar played the pattern's own steps. Emulation could not see that, because the simulated
flash accepted every write; `tests/emu_chain.py` now models the protect latch.)

**A bar is only written when it changed.** `store_save` hashes the working copy before appending:
FNV-1a over words 1..55 of area 4 slot 0 (word 0 is the VARI and is left out, so a side does not
count as an edit), compared with the hash taken when the bar was loaded. If the two match it
returns without touching the flash. This is what makes the follow free: during steady playback the
panel pass loads each new bar and the bar being left is hashed, found unchanged and skipped, so
playback issues no program or erase at all — no wear and no power-cut window. An edit made while
playing changes the hash and is appended once, when the sequence moves on.

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
accents, flams, the two side lengths) goes through the stock commit unchanged.

**Side lengths.** Index 17 (global id `0x138`) holds the two lengths in one parameter: the low
nibble is Na, the high nibble Nb, each 0..4 (0 = that side was never selected). It is written with
the firmware's Ptn2 setter and saved with the pattern by the stock area-6 commit, so each pattern
keeps its own two sequences. The poly patch uses indices 4..14 (`0x12B`..`0x135`), so it does not
collide; a future combined build can use both. The earlier build's indices 15/16 (`0x136`,
`0x137`) are no longer read or written. A firmware update erases the log blocks (the updater
rewrites flash `0x30000`-`0x3DFFFF`, [UPDATE.md](UPDATE.md)), so the bars fall back to the pattern
after an update; the side lengths survive, because they are ordinary pattern parameters in the
user area. Another patch must not claim `0x3DB000`-`0x3DFFFF` while this one is installed.

**Backup caveats.** The USB backup stores named parameters only, so neither the Ptn2 side lengths
nor the bar log is in it: after a restore, the patterns are back to their own steps and every bar
falls back to the pattern. Also, the backup reads area 4 slot 0, which is the selected bar while a
bar is selected, so take a backup with no side sequence set (or after a fresh start) to capture
the pattern's own steps.

### Code space

The payload uses the two developer-dump regions
(`0x60011150`-`0x60011464` and `0x60011488`-`0x60011BB6`): 776 bytes of `.text.far` plus 6 bytes of
`.data` in the first (788 available, 6 free), 1624 bytes of `.text` plus 212 bytes of `.bss` in
the second (1838 available, 2 free). The literal pool between them (`0x60011464`-`0x60011484`) is
live firmware data and is never written. The probe build (`payload_probe.json`) needs 568 + 14
bytes. That is why the patch is standalone for now: `motion-poly` already uses both regions, and a
combined build needs the "grow the image" method or another dead-code region
([DEVELOPING.md](DEVELOPING.md) "Code space"). Fitting the two lengths and the follow needed
`-fno-inline`; the first region carries `sync`, `clen`, `struct_bar`, `slot_load`, `chain_edit`,
`chain_commit`, `ecrc`, `ent_off` and `save_dirty` plus the display buffer and the pattern byte,
the second everything else. Dropping the synchronous notification gave the first region back 12
bytes, and the follow fits in the second because `store_gc`, `store_init` and the display helpers
were rewritten to do less arithmetic (walking the player struct and the row loop, one `eok` that
also checks the key, one shared `show4`). The follow itself, the hash check and the `sync` guard at
the top of `chain_view` then take the second region back to 2 free bytes.

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
4. **Every side plays its own sequence.** With no side length set the pattern is stock. A side
   plays its bars only when the panel is on that side; A+B plays the A bars and then the B bars.
   A selected side whose length is 0 is the editing-only stock side.
5. **The pads show a side's bar row only while A or B is held.** Release the button and the pads
   show what the screen was showing; with A+B they stay stock. In the row, pads after that side's
   last bar are deliberately dark (their step display is hidden while you pick a bar).
6. **The build must be this one.** The first hardware build hooked the pad branch of
   `FUN_6001961E`, which a bare pad never reaches; A + pad showed nothing there (see "How it
   works"). Build the file again from the current tree and check the sha256.

The **probe build** shows what the firmware actually sees:

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_probe.BIN --patch chain-probe
```

It uses the same hooks (plus the LAST STEP branch of `FUN_6001961E`) and only displays, so it never
writes a side length, a bar or the pattern:

| Display | Meaning |
|---|---|
| `St00` / `St11` / `St20` on start | payload runs; `St20` = panel VARI 2 (A+B), effective variation of the pass 0 |
| ` 1A-` (A + pad 1) | hook runs and the firmware reports VARIATION A held: the press never reached the screen |
| `12B-` (B + pad 12) | same for B, two-digit pad (pads 5..16 are not bars) |
| ` 3C-` (A+B + pad 3) | both variation buttons held |
| ` 3--` (plain pad 3) | hook runs on every press and sees no modifier; the text is written after the firmware handled the pad |
| ` 8-L` (LAST STEP + pad 8) | LAST STEP is held, so the press goes to the firmware first (pattern length) and the text is written after it |
| ` 3CL` (A+B + LAST STEP + pad 3) | the same with both variation buttons held: LAST STEP wins, no bar selection |
| pads 5-16 dark while A is held | the bar row: pads 1-4 lit (the probe has no side lengths, so all four are yellow; the real build shows only that side's bars, green, with the head blinking yellow), the rest off |
| nothing at all | the payload is not running: the build is not the patched one |

## Test history

- Emulation (`tests/emu_chain.py`, 188 checks): all hook sites of the real build branch into the
  payload (the probe also has `chain_pad`); the gesture through the press dispatch (`A/B + pad
  1..4` sets the bar and that side's length, `A+B + pad n` sets both, `A+B+CLEAR + pad` resets
  both, pads 5..16 forwarded, LAST STEP wins, display strings, release swallowed); bar selection
  and the working copy (bar 1 = pattern, bar 2 loaded after a save, last steps and B side; the
  same round trip while stopped: `A + pad 3`, edit a step, `A + pad 1`, back to `A + pad 3` with
  the edit, and the step-view repaint bit `0x04` set after every load but not after the A+B
  length gesture, and no slot-0 notification at all); the bar jump (a select moves the playhead
  while stopped and while playing, selecting the playing bar repeats it, the side's first bar
  clamps a bar it does not have); the display hand-back (releasing VARIATION
  A or B calls the firmware's repaint helper — the payload must go through `FUN_60051E20` and
  never write the object by hand — a swallowed pad release leaves it alone, another button does
  not touch it); two build-level checks that the payload never references the Setup database
  object `0x60149F38` and does reference the panel object `0x60149B8C`; the
  pattern-save redirect (no pattern slot written, one log entry with the 26 rows and LAST_A/B,
  area 4 slot *n+1* unchanged); playback of an A sequence, a B sequence and the A+B A-then-B
  sequence, with the recorded bar's content (masks, last steps, scale); a side that was never
  selected stays stock on the panel and contributes no A+B pass; stock A+B toggle with no lengths
  at all; a second pattern with its own bars and lengths (and its own Ptn2 slot); a power cycle
  rescanning the log; compaction after more than a block of saves; the ring wrapped and every
  block compacted (192 saves over all 64 bars, each bar read back through the payload's index);
  the sequence number wrapping from 0xFFFF to 0 (an entry written after the wrap still wins); the
  stock commit for a pattern the patch has not loaded; `chain_wrap` marks the restart. The
  simulated flash models the chip's block protection: program/erase outside a write session are
  dropped, as on the unit, and the run checks that every operation happened inside a session and
  every session was closed. The step view follows the playing bar: the first paint of the bar
  already in the working copy does not reload it, a bar change does and writes nothing when the
  bar was not edited, an edit made while playing is stored exactly once at the next boundary, the
  same bar on the other side is reloaded, a pattern change is noticed before the follow (so the
  new pattern's steps are never stored as a bar of the old one), and a stopped machine never
  follows. An *upgrade* also
  keeps the previous build's bars: entries written at its addresses (old entry 0 is new entry 96,
  old 32 is new 64) are read back and played. The bar row: all four pad setters (both raw, both
  palette) resolve that side's bars to green, the head bar to the blinking yellow triple and every
  other pad to off while exactly one of A/B is held, and forward the original triple when neither
  or both are held and for every other LED; after a bar press the A row stays one bar and the B row
  shows the new bar. The probe build (`--probe`, `payload_probe.json`, 47 checks): display strings
  on the press path and on the global LAST STEP branch, a pass-through save redirect, no Ptn2
  writes, `St` line on start.
- Hardware, first build (pad branch of `FUN_6001961E`): LAST STEP + pad set the pattern length,
  stock A/B alternation worked, A + pad showed nothing. Diagnosis: the screen takes a bare pad
  press, so the global button handler never runs for it; the press dispatch is the first code
  that can see the gesture.
- Hardware, second build (bar = pattern, press dispatch): A + pad 2 showed ` 2A` and selected
  pattern 2, A+B played the bars. Superseded (four bars per pattern, its own A and B step set
  each); the old build remains recoverable from git (`bd94eef`).
- Hardware, third build (four bars per pattern): selecting pads 1, 2, 3 and returning to 1 lost the
  edit and bar 1 played the unrecorded pattern again. Diagnosis: the log's programs were issued
  while the chip's block protection was on, so the chip dropped them (the emulated flash accepted
  them). Fixed by opening a write session around every program/erase and reading each entry back.
  Superseded build: git `9beb1ed`.
- Hardware, fourth build (bar row on all four pad setters): the four bars played and recorded and
  the row was correct on every screen. Confirmed on the unit; the old chain build is recoverable
  from git (`bd94eef`, write-session fix `bfdc63d`).
- Hardware, fifth build (`8941d9e`, the display hand-back) and sixth build (`bd5fcdc`, the
  deferred repaint instead of the slot-0 notification): the unit froze. Every report has the same
  shape — hold VARIATION A on its own, or `A + pad 5` stopped, or `A + pad n` while playing, or
  `A+B + pad n` — and the unit dies within a second or two, taking sound, buttons and display
  with it. Diagnosis: both builds asked for the repaint by writing the bit into `0x60149F38`,
  which is the **Setup parameter database** (the `db` handle of `FUN_6001B12E(db, idx, def)`),
  not a panel object. The panel's screen object is `0x60149B8C`, `0x3AC` higher
  ([docs/FINDINGS.md](FINDINGS.md) section 11). ORing `0x04`/`0x40` into the database's first
  byte corrupted it, the panel then read through the bad pointer, and the unit hung. That the two
  objects are different is also why emulation never saw it: the panel and the database are both
  stubbed there, so a write to the wrong one has no visible effect. The notification was not the
  cause (`A+B + pad n` touches no flash and never notified, and still froze).
- Seventh build: the repaint requests now go to the panel object only. `chain_edit` ORs `0x04`
  into `0x60149B8C` (the panel's own pass redraws the step pads, leaving the bar number on the
  display), and `chain_release` calls the firmware's own `FUN_60051E20` (thumb `0x60051E21`, which
  sets `0x44`), so the patch no longer writes a firmware object by hand. This build also carries
  the sequential per-side playback, the two side lengths, the green/blink row and the stopped bar
  editing. Confirmed on the hardware: the freeze was gone, the four bars played and recorded, the
  row was right on every screen, and a bar selected while stopped loaded for editing and could be
  switched again. The previous confirmed build is `bd47883`, kept as `work/TR8_UPD_chain_b4.BIN`
  as an immediate fallback.
- Eighth build: `A/B + pad n` is also a **bar jump**. The selection writes the playhead
  (`chain_pos` = *n* - 1 in `chain_edit`, so the next boundary lands on *n*) and a fresh start
  begins at the bar last selected (`cur_bar`, which `sync` resets on a pattern change, so a new
  pattern still starts at bar 1). Cost 4 bytes in the second region, which was full: the display
  buffer `txt` moved to the first region (`.data.far`), next to the other small state. Confirmed on
  the hardware: the jump works stopped and playing, and the four bars still record. Emulation
  passes (163 checks at that point).
- Ninth build (this one): the step view **follows the bar that is playing**. `chain_view` replaces
  the step-view paint call in the panel dispatcher (`0x60016C44`), so during playback the working
  copy and the step pads move to each bar as it starts and TR-REC edits the bar you hear; stopped,
  nothing follows. Leaving a bar is free when nobody edited it: `store_save` hashes the working
  copy and skips the flash write when the hash matches the one taken at load, so steady playback
  writes nothing. The log addressing became a plain `FL_BASE + i * 128` (same bytes, so the bars of
  the eighth build stay readable), and `store_init`, `store_gc` and the display helpers were
  rewritten to keep the payload inside the two regions: 782/788 bytes in the first region (6 free)
  and 1836/1838 in the second (2 free). Emulation passes (188 checks). Hardware check pending.
- Hardware checklist for this build:
  0. **Freeze check (do this first):** hold VARIATION A alone for a few seconds and release it
     (the smallest failing case of the previous build); then `A + pad 5` while stopped; then,
     while playing, `A + pad n` and `B + pad n`, releasing A/B each time; then `A+B + pad n`.
     Nothing may freeze, the normal text must come back after each release, and audio must keep
     running. Repeat once while stopped. If it freezes, power cycle, flash
     `work/TR8_UPD_chain_b4.BIN` (the confirmed fourth build) and report which case did it.
  1. Plain pattern, no side selected: A, B and A+B behave exactly as stock; while A or B is held
     the row shows just bar 1 (the pattern itself) blinking yellow and pads 2-16 dark.
  2. Give A four bars (`A + pad 1`, then 2, 3, 4): the display shows `  A1`..`  A4`, and each
     disappears again when A is released (the panel draws its normal text); while A is
     held, all four bars are green and the playing bar blinks yellow, pads 5-16 dark. Press A: the
     four A bars play in order and wrap. Press B: B has no bars yet, so it is stock. Press A+B:
     the A sequence only. **`FAIL` in place of the bar number means the flash chip refused the
     save of the bar being left** (stop here and report it).
  3. Give B two bars (`B + pad 1`, `B + pad 2`): while B is held only pads 1-2 are green, and the
     playing B bar blinks yellow. Press B: two bars in order. Press A+B: four A bars, then two B bars
     (watch the bar row change side), then back to A bar 1.
  4. Set A to two bars with `A+B + pad 2` (`AB 2`): the A sequence shortens. `A+B+CLEAR + pad`
     (`AB--`) returns both sides to stock.
  4b. **Bar jump:** with four A bars, press A and let it play; while bar 1 plays, `A + pad 3`:
     the next bar boundary must play bar 3 (not bar 2) and carry on to bar 4, then bar 1. Stop,
     then `A + pad 2` and press A: playback must start at bar 2. `B + pad 2` then B: B starts at
     its bar 2. Switch to another pattern and press A: it starts at its bar 1.
  4c. **The step view follows the playing bar.** With four A bars holding different steps, press A
     and watch the 16 pad LEDs in the sequencer screen: they must change at every bar boundary to
     the bar being heard (compare with the blinking bar in the A row) and must not lag a bar.
     While it plays, press REC and toggle a step: it must land in the bar that is playing, and
     after the sequence wraps the step must come back with that bar. Stop: the pads stay on the
     bar they show, and `A + pad n` still selects for editing as before. Play for a while with no
     edits: the display must not show `FAIL` and the unit must not slow down (a bar boundary
     writes nothing when the bar was not edited).
  5. Record different steps into A bar 1, A bar 2 and B bar 1; play A, B and A+B: each bar's own
     steps come back. Select a bar again: the display follows the pad and the steps are restored.
  6. **Stopped bar editing:** with the sequencer stopped, `A + pad 2`, record a step, `A + pad 1`,
     then `A + pad 2` again. The screen shows bar 2's steps as soon as the pad is pressed (no play
     needed) and the step recorded while stopped is still there.
  7. Select patterns 2..5 and press A: each still sounds like its own stock pattern (no side
     selected); pattern 1's bars and lengths are unchanged when you return.
  8. Give pattern 2 its own bars and lengths; switch 1 <-> 2: each pattern plays its own phrase.
  9. Power cycle: bars, steps and side lengths are still there; a recorded bar still plays its
     own steps.
  10. LAST STEP + pad still changes the pattern length, and the poly LAST STEP + instrument + pad
     gesture still works.
  11. Change the pattern: playback starts at bar 1 of the new pattern, and the previous pattern's
      bars are not overwritten.
