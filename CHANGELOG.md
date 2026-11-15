# Changelog

Each release is a tag of this repository. A release contains the sources only: no firmware file
is attached, because a patched `TR8_UPD.BIN` contains Roland's code. Build yours from the official
v1.61 file with the [web flasher](https://yo1frenchtoast.github.io/tr8-re/) or
`tools/tr8patch.py`. The web flasher shows the release it builds at the bottom of the page.

"Unit" means checked on a real TR-8; everything is also checked in emulation
(`tests/run_all.sh`).

## v1.0 (2026-11-15)

The first release. Three mods for the TR-8 system program v1.61, in any combination, built from
your own copy of Roland's update file.

### Motion recording ([docs/MOTION.md](docs/MOTION.md))

- Hold TR-REC and move a knob or fader while the pattern plays: the movement is played back on
  every pass. Hold CLEAR and move a control to erase it.
- RAM only: the moves are lost at power off. One buffer for all patterns.
- Unit: passed.

### Per-instrument length, "poly" ([docs/POLY.md](docs/POLY.md))

- Hold LAST STEP + an instrument button and press a pad: that instrument loops over that many
  steps (polyrhythms). The same gesture again goes back to the pattern length.
- In TR-REC, LAST STEP blinks while the selected instrument has its own length.
- The firmware's restart on the fly (TAP + START/STOP while playing) keeps every instrument in
  step.
- Saved with each pattern. Unit: passed.

### Bar chain ([docs/CHAIN.md](docs/CHAIN.md))

- Up to eight bars per pattern, each with its own A and B steps. A plays bars 1..Na, B plays
  bars 1..Nb, A+B (hold one and press the other) plays the A bars and then the B bars.
- Hold A or B + pad 1..8 to select a bar and make the side at least that long;
  A/B + CLEAR + pad sets the exact length; A+B + pad sets both sides; A+B + CLEAR + pad resets.
- **Expand**: A or B + a tap of LAST STEP doubles that side, first its steps (4 -> 8 -> 16), then
  its bars (1 -> 2 -> 4 -> 8). **Copy A to B**: A + B + a tap of LAST STEP.
- While a pattern with bars plays, the display shows the bar and the side's length (`A1-4`), and
  the step pads show the bar you hear. Hold A or B to see that side's bars on the pads.
- The bars are saved in the TR-8's flash: they survive power off and flashing another build made
  by this project. Roland's own update file erases them. The USB backup does not contain them.
- Unit: passed, alone and with motion and poly in one firmware.

### Tools

- [Web flasher](https://yo1frenchtoast.github.io/tr8-re/), English and French, with a tutorial
  for each mod. It produces the same file as `tools/tr8patch.py`, byte for byte.
- `tools/tr8patch.py --version` prints the release.

### Known limits

- Only system v1.61 is supported, unmodified.
- Open points of the bar chain (none seen as a fault on the unit) are listed in
  [docs/CHAIN.md](docs/CHAIN.md), "Open points".
