# Motion recording

Record knob and fader moves per step and play them back with the pattern, like the motion
recording of later Roland drum machines.

Status: **works on a real TR-8** (hardware tests 5 and 6 below). RAM only: one global motion
buffer, lost at power off.

## Use

Build the patched update from your own copy of Roland's v1.61 file, then flash it as described
in [UPDATE.md](UPDATE.md) (back up first; that page also explains how to go back).

```sh
python3 -I tools/tr8patch.py TR8_UPD.BIN --check          # is this file supported? (v1.61 only)
python3 -I tools/tr8patch.py TR8_UPD.BIN TR8_UPD_motion.BIN
```

| Gesture | Result |
|---|---|
| Hold **TR-REC** while the pattern plays and move a knob or fader | The value is stored at the current step for that control |
| Next pass of the pattern | The stored values are played back at their steps |
| Hold TR-REC and move a control that already has motion | New values overwrite the old ones; playback of that control pauses for 2 steps after each touch |
| Hold **CLEAR** and move a control (playing or stopped) | The motion of that control is erased (variations A and B). The control still changes the sound. CLEAR wins if both buttons are held |
| Move a control without holding a button | Normal live change: nothing is recorded or erased, the motion continues |
| Power off | All motion is lost |

- All 49 controls can record: 36 knobs, 11 level faders, shuffle and tempo fine
  ([FINDINGS.md](FINDINGS.md) section 8).
- 16 steps x 2 variations (A/B) per control.
- One global buffer: changing pattern keeps the same motion.
- Playback continues while an instrument button is held.

## How it works

| Site | Original | New |
|---|---|---|
| `0x600138C8` in the HMI control-event handler `0x60013892` | `bl FUN_60013242` (give the event to the active screen) | `bl motion_knob` |
| `0x60009862` in `FUN_6000981E` (per step) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60009808` in `FUN_600097DA` (per step, other path) | `bl FUN_6000978E` | `bl motion_step` |
| `0x60011E00`, `0x60011E04` in `FUN_60011DBE` | calls to the developer dump functions | `nop.w` (frees the code cave) |

- **Space.** The payload (`patches/motion/motion.c`) lives where the developer dump code was:
  code and small variables at `0x60011150` (737 of 788 bytes), the value table at `0x60011488`
  (1568 of 1838 bytes). The literal pool `0x60011464`-`0x60011483` between them is still used and
  is kept. The image size does not change.
- **Capture.** `motion_knob(screen, ev)` sees every control event `{10, id, value}` before the
  active screen and the global control table. With TR-REC held and the sequencer running, it
  stores the value at slot `variation * 16 + ((counter >> 1) & 15)`, then calls the original
  `FUN_60013242`. The sequencer counter counts half steps.
- **Erase.** With CLEAR held, the control's 32-bit slot mask is cleared.
- **Playback.** `motion_step` calls the original function, then posts `{0x0B, id, value}` for
  each control with a value at this slot, through the ADC change callback `0x60000CC0`: the same
  event as a real control move. The panel task applies it with the normal code, so the sound and
  the display follow.
- **Once per step.** The per-step code usually runs twice per step; `motion_step` remembers the
  last slot (`m_last`) and plays it once.
- **Echo filter.** The posted event comes back through `motion_knob`. A per-control pending flag
  and value recognise it, so it is not recorded again.

State used: sequencer running `0x6007E102`, counter `0x6007E118`, variation `0x6012FA74`, button
state `FUN_60013168(0x11)` (TR-REC) and `FUN_60013168(0x1C)` (CLEAR).

## Variants

`tools/tr8patch.py --list` shows them. All use the same sites, so only one of these motion
variants can be applied. (`poly`, `motion-poly` and the chain builds add other features; the bar
chain no longer shares the motion code regions.)

| `--patch` | Record | Erase | Status on the unit |
|---|---|---|---|
| `motion` (default) | TR-REC held, playing | CLEAR held | **Works** (tests 5, 6) |
| `motion-mode` | TR-REC mode active (Setup[0] == 0), playing | Control moved while stopped in TR-REC mode | Not tested since the hook fix |
| `motion-diag` | Always while playing | Control moved while stopped | Works (test 4) |
| `motion-probe` | No motion: audible check of each link (below) | - | Not needed so far |

`motion-diag` and `motion-probe` are debugging tools. If a change to the patch stops working on
the unit: the diagnostic build tells a wrong condition from a broken chain; the probe tells
which link of the chain is broken.

| Probe check on the unit | If yes | If no |
|---|---|---|
| Sequencer stopped: controls do nothing | Capture hook runs; the running flag reads 0 when stopped | Hook not reached, or the probe is not installed |
| Sequencer playing: controls work | The running flag reads 1 | Running flag wrong |
| Playing: touch a knob and release it: its parameter jumps between minimum and maximum every step | Step hook runs and posting from the sequencer works | Step hook not reached, or posting does not work |

## Tests

```sh
pip install -r requirements-dev.txt     # unicorn, in a virtualenv
tests/run_all.sh TR8_UPD.BIN            # builds every variant and runs all tests
```

`tests/emu_motion.py` runs the payload inside the patched application with Unicorn; the firmware
functions it calls are stubs. 30 scenarios for `motion`, 27 for `motion-mode`, 22 for
`motion-diag`: record, hold, playback, echo, A/B, erase, record and erase conditions, half-step
counter, once per step, and an integration test that runs the firmware's own control-event
handler `0x60013892`. `tests/emu_probe.py` checks the probe.

The emulation does not prove real timing, display behaviour, or side effects in other screens.

## Limitations

- Not per pattern and not saved. Per-pattern storage needs a new storage area and more code
  space ([FEASIBILITY.md](FEASIBILITY.md)).
- The display may show the parameter value on each played-back step.
- Values are 8-bit (the controls give 0-255), the same resolution as the panel.
- With scale value `0x32` the firmware also runs steps on odd counter values; two steps then
  share one slot. Not checked on the unit.
- If a played-back event never reaches `motion_knob` (another screen took it), the pending flag
  stays set until the next playback of that control; one real move with the same value could
  then be ignored.

## History

Each hardware test was done on one TR-8 with the build of the given commit.

1. First build: the unit started and played normally, but nothing was recorded.
2. Diagnostic build with the half-step and once-per-step fixes: still nothing. As that build has
   no conditions, the capture hook was the problem. Cause: the hook was on `FUN_6001446A`, which
   only some screens use. In normal play the control-event handler `0x60013892` asks the active
   screen and then applies the parameter itself with `FUN_60013F6A`. Fix: hook the `FUN_60013242`
   call at `0x600138C8`. The emulation test now also runs the firmware's own handler.
3. Normal build `8dc6187` (TR-REC mode, boot mode and redirect tests): nothing recorded.
4. Diagnostic build `8dc6187`: **recorded and played back.** The whole chain works; one of the
   normal build's conditions was wrong. The boot-mode (`0x6007E574`) and redirect (`0x6007E580`)
   tests came from the `FUN_6001446A` path and were removed. A "hold TR-REC to record" build was
   added next to the TR-REC mode build.
5. Hold build `e7c4ca4`: **works**. Record while TR-REC is held, live changes otherwise.
   Confirms that button 0x11 is TR-REC and that `FUN_60013168` is the button-held state. (The
   TR-REC mode build was not tried.)
6. `613191c`, hold rule as default plus "hold CLEAR to erase": **works**, playing or stopped,
   other controls keep their motion. Confirms that button 0x1C is CLEAR.

## Rebuild the payload

`patches/motion/build.sh` (clang and ld.lld) compiles `motion.c` and `probe.c` with `link.ld` and
`patches/include/tr8_v161.h`, and writes `payload.json`, `payload_mode.json`, `payload_diag.json`
and `payload_probe.json`. The patcher only reads these JSON files, so users need Python only.
