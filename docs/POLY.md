# Per-instrument length (polyrhythm)

Give each instrument its own last step, like the polyrhythm mode of some other drum machines.
An instrument with length L plays its steps 1..L in a loop, independent of the pattern length.

Status: **works on a real TR-8**: playback (hardware test 1), the panel gesture (hardware
test 2), the step LEDs (hardware test 3) and the lengths saved with each pattern (hardware
test 4). To get motion as well, use the `motion-poly` patch; for motion, the bar chain or both as
well, use `poly-chain` or `motion-poly-chain` ([COMBO.md](COMBO.md), [CHAIN.md](CHAIN.md)).

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_poly.BIN --patch poly
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first).

| Gesture | Result |
|---|---|
| Hold **LAST STEP** + an **instrument button**, press pad **n** | That instrument loops over n steps. The display shows `L  n` |
| The same gesture with the same pad again | Back to the pattern length. The display shows `LOFF` |
| Hold LAST STEP + several instrument buttons, press a pad | All of them get that length |
| Hold LAST STEP, press a pad (no instrument button) | Normal: sets the pattern length |
| Hold LAST STEP + an instrument that has a length | The step LEDs show that instrument like the pattern-length view: steps inside its length green, its play position blinking while playing, the other steps off |
| In TR-REC, select an instrument that has a length | The LAST STEP button blinks |
| Change pattern | The lengths of that pattern apply |
| Power off and on | The lengths are kept |

Each pattern has its own lengths. They are saved like any other edit of the pattern (the TR-8
saves pattern edits automatically). A pattern that was never given a length plays as before.

## Behaviour

- Each instrument with a length has a play head. It advances once per step and goes back to
  its step 1 after L steps. The pattern position (step LEDs, last step, A/B) does not change.
- Only steps 1..L of that instrument are used; its other steps are ignored but kept.
- Step, accent and flam of the instrument all follow its head. The global accent row (AC) and
  the weak accent follow the pattern.
- The heads go back to step 1 when the sequencer starts or stops.
- The lengths are per pattern: variations A and B share them.
- When scatter is on, the instruments play as written (no length).

## How it works

The step trigger `FUN_600262F2(P, step, flam)` owns the play position (`P[0x66]`). With step -1
it advances it, then tests one bit, `1 << step`, in every instrument mask of the player object
`P = 0x6014A164` ([FINDINGS.md](FINDINGS.md) section 7, "Step trigger").

`poly_trig` predicts the step the firmware will use, puts bit `pos[i]` of each mask (step,
accent, flam) of a poly instrument at that step, calls the firmware, then puts the masks back.
A mask that changed during the call (a panel edit) is not overwritten.

| Site | Original | New | Task |
|---|---|---|---|
| `0x60009800` in `FUN_600097DA` | `bl FUN_600262F2` (advance) | `bl poly_trig` | sequencer; panel through button 0x1B (see below) |
| `0x6000985A` in `FUN_6000981E` | `bl FUN_600262F2` (advance) | `bl poly_trig` | sequencer; panel through button 0x1B |
| `0x60009884` in `FUN_6000981E` (counter 0) | `bl FUN_600262F2` (advance) | `bl poly_trig` | sequencer; panel through button 0x1B |
| `0x60009A50` in `FUN_60009A04` (delay queue) | `bl FUN_600262F2` (flam hit) | `bl poly_trig` | not traced (reached through a pointer) [hyp: sequencer] |
| `0x6000966E` in `FUN_6000964E` (start) | `bl FUN_60026894` | `bl poly_run` | sequencer; panel through button 0x1B |
| `0x600096AE` in `FUN_6000969A` (stop) | `bl FUN_60026894` | `bl poly_run` | sequencer; panel through button 0x1B; also from `FUN_6000D306`, called by the incoming-note handler `FUN_60004D8C` [hyp: MIDI task] |
| `0x60019A10` in `FUN_6001961E` (button handler: pad with LAST STEP `0x1A` held) | `bl FUN_6001B8D6` (set LAST_A/B) | `bl poly_last` | panel |
| `0x60016438` in `FUN_60016386` (step LED loop, LAST STEP view only) | `bl FUN_6001774E(led, colour)` | `bl poly_led` | panel |
| `0x60016B56` in `FUN_600169A4` (panel repaint, bit `0x02`) | `b.w FUN_60017722(id, a, b)` (tail call: LED 9, or LED 7 while LAST STEP is held) | `b.w poly_lsled` | panel |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the region) | - |

The task of each site comes from `tools/callgraph.py up` ([DEVELOPING.md](DEVELOPING.md) section 3).
The clock tick `FUN_6000989C` is called by the sequencer task (`FUN_60008F6C`) and also by
`FUN_600099B6`, which the panel's button handler `FUN_6001961E` calls for button `0x1B`. So
`poly_trig` and `poly_run`, and the variables they write (`poly_pos`, `poly_reset`), can run in
two tasks. What button `0x1B` does on the unit is not known (FINDINGS section 9); this is an
open point for review rule 1, not a seen fault.

`poly_last` checks the instrument buttons (`0x21 + i`, held bitmap): none held -> the original
call; else it sets the lengths and shows the result with `FUN_60015980`.

`poly_led` replaces the colour of each step when an instrument with a length is held: 0 = play
position (blinks), 0x2A = inside the length (green, the pattern-length colour), 0x2D = off. The firmware redraws the step LEDs
when an instrument button or a pad is pressed (flag bit 0x4).

`poly_lsled` replaces the last call of the panel repaint `FUN_600169A4`. That call is a tail call
(`pop.w` then `b.w`), so the hook is a `b.w` too: `poly_lsled` returns straight to the repaint's
caller. With LAST STEP released it sets LED 9 (LAST STEP), lit when the pattern is shorter than 16
steps [code]. In TR-REC (Setup[0] = 0), when the selected row (Setup[7] = row button - `0x1D`) is
an instrument with a length, it sets `(9, a = 1, b = 0)` instead: `b = 0` is the blink flag of the
step pads [unit, CHAIN.md], and it blinks the LAST STEP button too [unit, hardware test 5]. Any other id (LED 7 while LAST STEP is
held) passes through. A row press sets the repaint bits `0x16`, which include `0x02` [code].

### Storage

A pattern is a set of parameters in three areas (FINDINGS section 6). Area 6, "Ptn2", has 40
ids `0x127`-`0x14E`: weak accent, flams, and 16 ids without a name (`0x127`, `0x128`,
`0x12B`-`0x138`). No code reads these 16 ids (they appear only in the Ptn2 index table
`FUN_6001D2CA` and as assert line numbers), and they are 0 in all 16 factory patterns. The
firmware copies and saves whole areas, so these ids are kept in the user flash with each
pattern.

The length of instrument i is id `0x12B + i` (Ptn2 index `4 + i`). Values outside 1..16 mean
"follow the pattern", so 0 (factory, cleared pattern) changes nothing.

- Write: `poly_last` calls the firmware's Ptn2 setter `FUN_6001D432(db, 4 + i, n)`, the function
  the panel uses for a flam edit. It checks the range (0..65535), writes the current pattern
  slot and sends the change notification of group 0x21 (flams), which leads to the normal save.
- Read: the player reads the value of the current pattern in RAM: bank 0, slot 0 of area 6, at
  `0x60146930 + 4 * (id - 0x127)` (table `0x6005D2A4`). The firmware copies a pattern into this
  slot when it changes patterns.
- The USB backup (`TR8_PTN`) writes named parameters only, so it does not contain the lengths
  [code].

Code: `patches/poly/poly.c`. The first developer-dump region (`0x60011150`-`0x60011464`) holds
695 bytes of code and is nearly full, so `poly_lsled` (108 bytes) and the data (6 + 11 bytes) are
in the second one (`0x60011488`-`0x60011505`), which the standalone poly build has to itself.
`motion-poly` links both features into the two regions itself ([COMBO.md](COMBO.md)).
Emulation test: `tests/emu_poly.py` runs the firmware's own `FUN_600262F2` through the hook,
the gesture through the firmware's own button handler `FUN_6001961E`, and the write through
the firmware's own setter (only the message post and the observer call are stubs; the test
checks that the notification is the flam one). The LAST STEP LED runs the firmware's own repaint `FUN_600169A4`
down to the hooked tail call, with the LED setter and the Setup getter as stubs.

## Hardware test 1 (fixed lengths RS 5, CH 3): all checks as expected

Set up a pattern with 16 steps: BD on steps 1, 5, 9, 13; CH on step 1 only; RS on steps 1 and 2.

| Check | Expected | If not |
|---|---|---|
| Unit starts, a factory pattern plays | Normal sound, normal tempo | Recover with step [1] at power-on |
| BD | Four on the floor, as written | Hook breaks the trigger |
| CH | One hit every 3 steps (3 against 4 with BD), drifts across bar lines | Advance hook not on the normal path |
| RS | Two hits every 5 steps | Same |
| Stop, start | CH and RS start again with BD on step 1 | Start/stop hook not reached |
| Add CH on step 2 while playing | Heard on the 2nd step of every 3-step cycle | Mask restore problem |
| CH step 5 or later | Not heard (outside its length) | - |
| Flam on CH step 1, scatter on and off | No crash; flams on the CH hits | Note what happens |

## Hardware test 2 (panel gesture)

Same pattern as test 1 (BD 1, 5, 9, 13; CH on step 1; RS on 1 and 2). Play it.

| # | Action | Expected |
|---|---|---|
| 1 | Play without any gesture | Normal pattern: CH and RS on every bar (no length at boot) |
| 2 | Hold LAST STEP + CH, press pad 3 | Display `L  3`; CH every 3 steps |
| 3 | Hold LAST STEP + RS, press pad 5 | Display `L  5`; RS two hits every 5 steps |
| 4 | Hold LAST STEP + CH, press pad 3 again | Display `LOFF`; CH back to once per bar |
| 5 | Hold LAST STEP, press pad 8 (no instrument) | Pattern length 8, as without the patch |
| 6 | Hold LAST STEP + BD + SD, press pad 12 | Both loop over 12 steps |
| 7 | Change pattern | The lengths stay |
| 8 | Hold an instrument button + pad (no LAST STEP) | Normal behaviour (weak note in TR-REC), no length change |

Also watch: does pressing an instrument button while LAST STEP is held do something else
(instrument selection is expected); does the display text stay long enough to read.

## Hardware test 3 (step LEDs): passed

Set CH to 3 steps (LAST STEP + CH + pad 3).

| # | Action | Expected |
|---|---|---|
| 1 | Hold LAST STEP + CH, stopped | Steps 1-3 green, 4-16 off |
| 2 | Same while playing | The CH play position moves over steps 1-3 |
| 3 | Hold LAST STEP + BD (no length) | The normal pattern-length view |
| 4 | Hold LAST STEP + CH, press pad 6 | CH length 6: steps 1-6 green |
| 5 | Release CH, keep LAST STEP | Back to the pattern view (at the next redraw) [hyp] |

## Hardware test 4 (lengths saved per pattern): passed

Use a pattern you can change (for example pattern 16). Flash the build, then:

| # | Action | Expected |
|---|---|---|
| 1 | Select a pattern. Set CH to 3 (LAST STEP + CH + pad 3). Play | CH every 3 steps, as before |
| 2 | Select another pattern | Its instruments follow the pattern (no length) |
| 3 | Select the first pattern again | CH every 3 steps again |
| 4 | Wait a few seconds, switch off, switch on, select that pattern | CH every 3 steps |
| 5 | LAST STEP + CH: step LEDs | Steps 1-3 green |
| 6 | LAST STEP + CH + pad 3 (off), switch off and on | CH follows the pattern |
| 7 | Flams and weak accent of that pattern | Unchanged |
| 8 | Optional: USB backup then restore | Patterns OK. Lengths after restore: not reported yet |

## Hardware test 5 (LAST STEP blinks): passed

Set CH to 3 steps (LAST STEP + CH + pad 3), leave BD without a length. Pattern length 16.

| # | Action | Expected |
|---|---|---|
| 1 | TR-REC, select CH | LAST STEP blinks. If it is lit steadily or off instead, report it: the blink flag on a button LED is the guess |
| 2 | Select BD | LAST STEP off (stock: pattern length 16) |
| 3 | Select RS, then HC (RS/HC button swap) | RS: as BD; HC: as BD. Then give RS a length: RS blinks, HC does not |
| 4 | Select CH, hold LAST STEP, release it | Held: the stock LED. Released: blinking again (if not, the release does not request the repaint) |
| 5 | Select CH, LAST STEP + CH + pad 3 again (length off) | LAST STEP stops blinking, at once or at the next row press |
| 6 | Select CH, change to a pattern where CH has no length | LAST STEP stops blinking (at the next repaint) |
| 7 | Leave TR-REC (another mode button) | LAST STEP as stock |
| 8 | Pattern length 12 (LAST STEP + pad 12), select BD | LAST STEP lit steadily (stock) |

## Limitations and next steps

1. The USB backup (`TR8_PTN`) does not contain the lengths [code].
2. In the normal view the step LEDs show the pattern position; the head of an instrument is
   shown only while LAST STEP + that instrument are held.
3. Flam timing: the delayed flam hit uses the heads of the last advance, which is right if it
   always lands before the next step [hyp].

## History

- Test build, emulation tests pass.
- Hardware test 1 (2026-11-12, fixed lengths): every check behaved as described: CH every 3
  steps across bar lines, RS 2 of 5, restart aligned on stop/start, live edits follow the head,
  steps beyond the length silent, no problem with flam and scatter. The step trigger hooks are on
  the normal play path.
- Hardware test 2 (2026-11-12, panel gesture): checks 1, 2 and 4-8 as expected. Check 3 failed:
  LAST STEP + RS set the hand clap and LAST STEP + HC set the rim shot. Cause: the instrument
  buttons are in the player order except RS and HC, which are swapped (button 0x26 = HC,
  0x27 = RS). Fixed in `TR8_BTN_INST`; check 3 then passed on the unit.
- Hardware test 3 (2026-11-12, step LEDs): passed with the last step in red (colour 1, confirmed
  red; 0x2A is green, 0 blinks while playing). Then simplified to the firmware's own look: all
  steps of the length green, no red step.
- Lengths saved per pattern in unused Ptn2 parameters (ids `0x12B`-`0x135`), emulation tests
  pass.
- Hardware test 4 (2026-11-12, saved lengths): passed. Lengths follow the pattern on pattern
  change, survive power off, LOFF is saved too, flams and weak accent unchanged.
- LAST STEP blinks in TR-REC when the selected instrument has a length (`poly_lsled`, first
  `b.w` hook site: `tools/tr8patch.py` and the web flasher take `"b:symbol"`). Emulation tests
  pass. Hardware test 5 (2026-11-13, `motion-poly-chain`): passed, every check as described.
