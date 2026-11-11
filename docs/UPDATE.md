# Flash, check, recover

This page applies to the original Roland file and to a patched file made by `tools/tr8patch.py`.
The procedure is Roland's official one for system v1.61 ([Roland support page](https://www.roland.com/us/support/by_product/tr-8/updates_drivers/9d8e26ad-8810-479e-84d7-13d3f1362497/)).

## Before you start

1. Save your patterns and kits with the TR-8 USB backup.
2. Keep the original `tr8_sys_v161.zip`. You need it to go back.
3. Use the AC adaptor. **Do not cut the power while the update writes.**
4. Check the installed version (below). The patcher only accepts the v1.61 file; the unit itself can run any version before the update.

## Check the version

1. Hold step buttons **[14]** and **[16]** and switch on the power. START/STOP flashes.
2. Push **START/STOP**. The display shows the version as three digits (`161` = v1.61).
3. Switch off the power. Do not push other buttons.

## Update

1. Hold step button **[1]** and switch on the power. The instrument buttons BD to RC flash.
2. Connect the TR-8 to the computer with a USB cable. BD and step [1] flash. A drive named **TR-8** appears.
3. Copy **only** the update file to the root of the TR-8 drive. Its name must be `TR8_UPD.BIN`.
   - Original: `tr8_sys_v161/TR8_UPD.BIN` from the zip.
   - Patched: rename the output of `tr8patch.py` (for example `TR8_UPD_motion.BIN`) to `TR8_UPD.BIN`.
4. Eject the drive, then disconnect the USB cable. SD and step [2] flash.
5. Push step button **[2]**. LT and step [3] flash; the SCATTER LEDs come on from 1 to 10.
6. When BD to RC and steps 1 to 16 all flash, the update is complete. Switch off the power.
7. Check the version again. A patched file keeps the version number `161`.

What the updater checks (FINDINGS 1c): the 16-byte trailer, the module names, a read-back of each written block, and after the write the byte-sum of each module. Error 6 = byte-sum mismatch. `tr8patch.py` recomputes the size and byte-sum, and verifies its output before it writes it.

## Recovery

The update rewrites only flash `0x30000`-`0x3DFFFF` (application and second-processor modules). The boot loader (`0x0`) and the updater (`0x8000`) are never written (FINDINGS 1b, 1c).

If the patched firmware does not start, or behaves badly:

1. Hold step button **[1]** and switch on the power. The boot loader selects the updater before it loads the application, so a broken application cannot stop this.
2. Do the update again with the original `TR8_UPD.BIN`.
3. Restore your patterns and kits from the USB backup if necessary.

The only case this does not cover is a power cut while the updater writes flash. Roland says the unit then needs service.

Not proven: that step button [1] is the GPIO input 12 that the boot table tests. Roland's procedure names step [1], and the boot table needs exactly one button held, so the two agree.

## Test the motion patch on the unit

Do these checks in this order. Note the result of each one.

| # | Action | Expected |
|---|---|---|
| 1 | Switch on after the update | Normal start, patterns and kits present |
| 2 | Play a pattern, do not touch knobs | Normal sound and timing |
| 3 | TR-REC on, pattern running, turn one knob (for example BD decay) during a few steps, then release it | On the next passes the knob movement is replayed at the same steps |
| 4 | Turn the same knob again while running | New values overwrite the old ones at those steps |
| 5 | Stop, turn that knob | Its motion is erased; next play has no motion on it |
| 6 | Record motion, switch to another mode (INST PLAY, INST REC), turn the knob | Live change only; the motion continues to play and is not changed |
| 7 | Record on variation A, then play B | B has its own motion (empty at first) |
| 8 | Hold an instrument button and turn a knob | Normal behaviour (nothing recorded, no replay while held) |
| 9 | Change pattern | The motion stays (one global buffer, by design) |
| 10 | Switch off and on | The motion is gone (RAM only, by design) |

Also watch: a display popup on every replayed value, stuck or jumping parameters, timing drift, and USB backup still working (the patch removes the developer dump calls in the backup path).

If something fails, note the step, the mode, the knob and what the display showed, then recover as above.
