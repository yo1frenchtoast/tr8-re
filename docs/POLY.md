# Per-instrument length (polyrhythm)

Give each instrument its own last step, like the polyrhythm mode of some other drum machines.
An instrument with length L plays its steps 1..L in a loop, independent of the pattern length.

Status: **works on a real TR-8** (hardware test 1 below). Test build: fixed lengths in the
code, rim shot (RS) 5 steps and closed hi-hat (CH) 3 steps; all other instruments follow the
pattern. No panel control yet, nothing saved. Cannot be combined with the motion patch (both use the same free region).

## Use

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_poly.BIN --patch poly-test
```

Flash as described in [UPDATE.md](UPDATE.md) (back up first).

## Behaviour

- Each instrument with a length has a play head. It advances once per step and goes back to
  its step 1 after L steps. The pattern position (step LEDs, last step, A/B) does not change.
- Only steps 1..L of that instrument are used; its other steps are ignored but kept.
- Step, accent and flam of the instrument all follow its head. The global accent row (AC) and
  the weak accent follow the pattern.
- The heads go back to step 1 when the sequencer starts or stops.
- When scatter is on, the instruments play as written (no length).

## How it works

The step trigger `FUN_600262F2(P, step, flam)` owns the play position (`P[0x66]`). With step -1
it advances it, then tests one bit, `1 << step`, in every instrument mask of the player object
`P = 0x6014A164` ([FINDINGS.md](FINDINGS.md) section 7, "Step trigger").

`poly_trig` predicts the step the firmware will use, puts bit `pos[i]` of each mask (step,
accent, flam) of a poly instrument at that step, calls the firmware, then puts the masks back.
A mask that changed during the call (a panel edit) is not overwritten.

| Site | Original | New |
|---|---|---|
| `0x60009800` in `FUN_600097DA` | `bl FUN_600262F2` (advance) | `bl poly_trig` |
| `0x6000985A` in `FUN_6000981E` | `bl FUN_600262F2` (advance) | `bl poly_trig` |
| `0x60009884` in `FUN_6000981E` (counter 0) | `bl FUN_600262F2` (advance) | `bl poly_trig` |
| `0x60009A50` in `FUN_60009A22` (delay queue) | `bl FUN_600262F2` (flam hit) | `bl poly_trig` |
| `0x6000966E` in `FUN_6000964E` (start) | `bl FUN_60026894` | `bl poly_run` |
| `0x600096AE` in `FUN_6000969A` (stop) | `bl FUN_60026894` | `bl poly_run` |
| `0x60011E00`, `0x60011E04` | developer dump calls | `nop.w` (frees the region) |

Code: `patches/poly/poly.c`, 370 bytes in `0x60011150`-`0x60011464`.
Emulation test: `tests/emu_poly.py` runs the firmware's own `FUN_600262F2` through the hook.

## Hardware test checklist (test 1: all checks as expected)

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

## Limitations and next steps

1. A panel gesture to set the length (hold an instrument button + press a step?). The
   LAST STEP button id is not known yet ([FINDINGS.md](FINDINGS.md) open question 6).
2. Save the lengths per pattern (11 bytes; same storage problem as motion).
3. More code space, to combine with motion.
4. The step LEDs show the pattern position, not the head of the selected instrument.
5. Flam timing: the delayed flam hit uses the heads of the last advance, which is right if it
   always lands before the next step [hyp].

## History

- Test build, emulation tests pass.
- Hardware test 1 (2026-11-12): every check of the checklist behaved as described: CH every
  3 steps across bar lines, RS 2 of 5, restart aligned on stop/start, live edits follow the head,
  steps beyond the length silent, no problem with flam and scatter. The step trigger hooks are on
  the normal play path.
