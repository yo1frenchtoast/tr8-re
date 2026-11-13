# Bar chain (more than two bars)

Play a pattern as a sequence of more than two bars: bar 1 is an A or B pass, bar 2 is an A or B
pass, and so on for up to 16 bars. A four-bar loop with a fill is `A A A B`; an eight-bar phrase
can repeat the same two bars of material.

Status: **works in emulation** (`tests/emu_chain.py`), not yet tested on a unit. Like the other
patches it is built from your own copy of Roland's v1.61 file.

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

`chain_pad` replaces the LAST STEP test at the head of the step-pad branch of `FUN_6001961E`,
where the pad id is still in `r6`; a naked trampoline moves it to `r0`. No A/B held: it returns
the stock LAST STEP condition. A/B held: it writes the chain and returns 0, so the pad is
handled and ignored like a pad pressed without a modifier. LAST STEP wins over the chain gesture,
so the poly gesture keeps working.

### Storage

The chain is two of the Ptn2 parameters that no code reads and the firmware stores with every
pattern ([POLY.md](POLY.md) "Storage"): index 15 (global id `0x136`) holds one bit per bar
(1 = B), index 16 (`0x137`) holds the length (0 = no chain, 1..16). The gesture writes them with
the firmware's own Ptn2 setter, so the pattern is marked changed and saved as after any edit.
The poly patch uses indices 4..14 (`0x12B`..`0x135`) and leaves these two alone; a future combined
build can use both.

### Code space

464 bytes of code and 12 bytes of state in the first developer-dump region (788 bytes). That is
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

## Test history

- Emulation (`tests/emu_chain.py`): the gesture through the firmware's button handler and Ptn2
  setter (paint, extend, length, chain off, two digits, LAST STEP still wins, no other Ptn2 id
  touched); the playback decision through the patched hook (`A A B A` and `A B` chains, start at
  bar 1, wrap order, A/B bypass, stock toggle with no chain); the three sites branch into the
  payload.
- Not yet on a unit. Hardware checklist:
  1. Press A+B: stock A/B alternation still works (no chain).
  2. Hold A, press pads 1, 2, 3; hold B, press pad 4. Press A+B, start: the four bars play
     A A A B, the display confirmed each gesture, and the tempo display comes back.
  3. Stop and start: the chain starts at bar 1 again.
  4. Change pattern and back: the chain is still there (saved).
  5. Press A, then A+B: editing bar A does not disturb the chain.
  6. Power cycle: the chain is still there.
  7. Hold LAST STEP and press a pad: the pattern length still changes (no bar painted).
