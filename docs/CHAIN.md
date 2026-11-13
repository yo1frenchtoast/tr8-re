# Bar chain (more than two bars)

Play a pattern as a sequence of more than two bars: bar 1 is an A or B pass, bar 2 is an A or B
pass, and so on for up to 16 bars. A four-bar loop with a fill is `A A A B`; an eight-bar phrase
can repeat the same two bars of material.

Status: **works in emulation** (`tests/emu_chain.py`). The first hardware build showed that the
gesture could never reach the old hook site, so the patch now sits on the button press itself
(see "How it works"); that build is not yet tested on a unit. Like the other patches it is built
from your own copy of Roland's v1.61 file.

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_chain.BIN --patch chain
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first). This patch is standalone: it uses
the same code region as `motion` and `poly`, so it cannot be combined with them yet.

| Gesture | Result |
|---|---|
| Hold **VARIATION A**, press pad *n* | Bar *n* is an **A** bar. The display shows `  1A`, ` 12A` |
| Hold **VARIATION B**, press pad *n* | Bar *n* is a **B** bar. The display shows `  1B`, ` 12B` |
| Hold **A + B**, press pad *n* | The chain is *n* bars long. The display shows `CH 4`, `CH12` |
| Hold **A + B + CLEAR**, press a pad | Chain off, back to the stock behaviour. The display shows `CH--` |
| Press **A** (no pad) | Edit and loop variation A, as before |
| Press **B** (no pad) | Edit and loop variation B, as before |
| Press **A + B** (no pad) | Play the chain (stock: alternate A and B) |

Painting a bar past the current length extends the chain; bars that were never painted are **A**.
The chain is a sequence of bars, not a second pattern: bars that are both A play the same 16
steps, and pressing A shows exactly those steps for editing as it always did. So `A A B A` is
two bars of material arranged into four bars.

## Behaviour

- The chain belongs to the current pattern and is saved with it like any other edit (the
  firmware saves a pattern automatically). Changing pattern brings that pattern's chain.
- Power off and on keeps it.
- A plain A or B press takes playback off the chain and loops that variation, which is how you
  edit or audition one bar. A+B puts playback back on the chain at the next bar.
- The chain starts at bar 1 every time the sequencer starts, and advances one bar per pattern
  wrap. It does not use the stock A/B alternation while it plays.
- With no chain (a pattern that was never painted) everything behaves exactly as stock.
- Up to 16 bars. The display confirms every gesture; the pads keep showing steps, not the chain.

## How it works

| Site | Original | New |
|---|---|---|
| `0x60009614` in `FUN_600095F0` | `bl FUN_6000E404` (apply `VARI`) | `bl chain_var` |
| `0x600098CA` in `FUN_6000989C` | `bl FUN_600095F0` (pattern wrap) | `bl chain_wrap` |
| `0x60013842` in `FUN_600137DE` | `bl FUN_60013B34` (press dispatch) | `bl chain_press` |
| `0x600137D2` in `FUN_6001377C` | `bl FUN_60013B56` (release dispatch) | `bl chain_release` |
| `0x600199F6` in `FUN_6001961E` | `bl FUN_60013168` (LAST STEP check) | `bl chain_pad` |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the region) |

`FUN_600095F0` restarts the pattern at start and at every wrap
([FINDINGS.md](FINDINGS.md) section 7, "Pattern restart and variation"). `chain_var` replaces the
variation call inside it: with a chain and `VARI` = 2 (A+B) it picks the bar's variation from the
chain, writes `TR8_SEQ_VARIATION` and calls `FUN_6000E152` to put that variation's masks into the
player. Without a chain, or with `VARI` = 0/1, it calls the original `FUN_6000E404`. The choice
has to happen there because `FUN_600095F0` reads the last step **after** applying the variation.

`chain_wrap` replaces the wrap call and sets a flag around `FUN_600095F0`, so `chain_var` knows
whether this restart is a wrap (advance) or a start (`0x600091A2`, `0x600098E4`; bar 1).

**The gesture lives on the press, not in the button handler.** Every button event is offered
to the active screen first: the type 5 (press) handler `FUN_600137DE` sets the held bit and then
calls `FUN_60013B34(id)` (`bl` at `0x60013842`), which gives the screen the press; only when the
screen declines it does the global button handler `FUN_6001961E` run (`0x60013F74`). That is why
LAST STEP + pad reaches `FUN_6001961E` (the screen declines LAST STEP) but a bare pad press never
does: the screen takes it as a step edit or a sound audition. The first build put the gesture in
the pad branch of `FUN_6001961E`, and on the unit A + pad did nothing, exactly as that path
predicts. `chain_press` replaces the dispatch call itself, before the screen: with VARIATION A
and/or B held and no LAST STEP it paints/lengths the chain and returns 1, so the screen never
sees the pad; otherwise it forwards the id to `FUN_60013B34` unchanged. `chain_release` replaces
the matching `bl FUN_60013B56` at `0x600137D2` and swallows the release of a pad whose press was
taken, so the screen never gets a release without a press.

`chain_pad` still replaces the LAST STEP test at the head of the step-pad branch of
`FUN_6001961E`, where the pad id is still in `r6`; a naked trampoline moves it to `r0`. It keeps
the stock LAST STEP path (return the stock condition) and is a fallback for a pad press that ever
does reach that branch with A/B held; LAST STEP wins over the chain gesture there, so the poly
gesture keeps working.

### Storage

The chain is two of the Ptn2 parameters that no code reads and the firmware stores with every
pattern ([POLY.md](POLY.md) "Storage"): index 15 (global id `0x136`) holds one bit per bar
(1 = B), index 16 (`0x137`) holds the length (0 = no chain, 1..16). The gesture writes them with
the firmware's own Ptn2 setter, so the pattern is marked changed and saved as after any edit.
The poly patch uses indices 4..14 (`0x12B`..`0x135`) and leaves these two alone; a future combined
build can use both.

### Code space

634 bytes of code and 14 bytes of state in the first developer-dump region (788 bytes). That is
why the patch is standalone for now: `motion-poly` already uses that region, and a combined build
needs the "grow the image" method or another dead-code region
([DEVELOPING.md](DEVELOPING.md) "Code space").

## Why not a real 32- or 64-step pattern

The step masks, the last-step values, the fills and the panel are all 16-step; a 32-step view
needs a page selector that the 16 pads do not provide, and wider masks in every parameter and
handler. The chain gets the same musical result — longer phrases, fills on chosen bars — by
arranging the two 16-step passes that already exist, and it needs no change to the step engine.
More *material* than two bars needs either C/D variation storage or a chain of whole patterns;
the pattern field could be added to the same gesture later (8 bars x (4-bit pattern + 1-bit
variation) still fits in the spare ids).

## If the gesture does nothing

1. **Variation buttons first, pad second.** Hold A (or B, or A+B) and *then* press the pad; the
   press of the pad is what the patch sees. Pressing the pad first and adding A afterwards does
   nothing.
2. **The chain only plays with A+B selected.** A alone or B alone loops that variation; that is
   the editing mode. A+B is stock (press and hold one variation button, then press the other).
3. **The display is the feedback.** The pads keep showing steps; they never show the chain.
4. **The build must be this one.** The first hardware build hooked the pad branch of
   `FUN_6001961E`, which a bare pad never reaches; A + pad showed nothing there (see "How it
   works"). Build the file again from the current tree and check the sha256.

The **probe build** shows what the firmware actually sees:

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_probe.BIN --patch chain-probe
```

It uses the same hooks and only displays, so it never writes the chain or the pattern:

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
  forwarded to the firmware, release swallowed, other Ptn2 ids untouched`); the playback decision
  through the patched hook (`A A B A` and `A B` chains, start at bar 1, wrap order, A/B bypass,
  stock toggle with no chain); all five hook sites branch into the payload. The probe build
  (`--probe`, `payload_probe.json`): display strings on the press path and on the global LAST STEP
  branch, no pattern writes, LAST STEP does not set a length, `St` line on start.
- Hardware, first build (pad branch of `FUN_6001961E`): LAST STEP + pad set the pattern length,
  stock A/B alternation worked, A + pad showed nothing. Diagnosis: the screen takes a bare pad
  press, so the global button handler never runs for it; the press dispatch is the first code
  that can see the gesture. This build moves the gesture there and is not yet on a unit.
- Hardware checklist for the current build:
  1. Press A+B: stock A/B alternation still works (no chain).
  2. Hold A, press pads 1, 2, 3; hold B, press pad 4. Press A+B, start: the four bars play
     A A A B, the display confirmed each gesture, and the tempo display comes back.
  3. Stop and start: the chain starts at bar 1 again.
  4. Change pattern and back: the chain is still there (saved).
  5. Press A, then A+B: editing bar A does not disturb the chain.
  6. Power cycle: the chain is still there.
  7. Hold LAST STEP and press a pad: the pattern length still changes (no bar painted).
