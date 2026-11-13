# TR-8 firmware v1.61: reverse engineering reference

This is the reference for everything known about the Roland TR-8 system program v1.61
(`TR8_UPD.BIN`, application built `18-0926_11:19:43`). To write your own feature, start with
[DEVELOPING.md](DEVELOPING.md); come back here for the details.

Conventions:

- Addresses are runtime addresses. The application runs at `0x60000000`; Ghidra names its
  functions `FUN_<address>`, and this document uses the same names.
- Confidence: **[unit]** confirmed on a real TR-8, **[code]** read from the code and consistent,
  **[hyp]** hypothesis. Untagged statements are [code].
- "Control" = knob or fader (ids 0-48). "Button" = panel button (ids 0x00-0x3F).

Contents: [1 Update file](#1-update-file-tr8_updbin) · [2 Boot loader](#2-boot-loader) ·
[3 Updater](#3-updater) · [4 Memory map](#4-application-memory-map) ·
[5 Structure](#5-application-structure) · [6 Parameters and storage](#6-parameters-and-storage) ·
[7 Sequencer](#7-sequencer) · [8 Controls](#8-controls-knobs-and-faders) ·
[9 Buttons and modes](#9-buttons-and-panel-mode) · [10 Sound parameters](#10-sound-parameters-internal-midi-cc) ·
[11 Display and LEDs](#11-display-and-leds) · [12 Code space](#12-code-space-for-patches) ·
[13 Open questions](#13-open-questions)

## 1. Update file (`TR8_UPD.BIN`)

4,194,320 bytes: a raw 4 MiB flash image (file offset = flash offset; flash is mapped at
`0x03000000`), followed by a 16-byte trailer. No encryption, no signature.

| Flash offset | Content |
|---|---|
| `0x0000` | Boot loader "ESC91.000" (0x33AC bytes), plaintext. Vector table at +0x30 (SP `0x01011718`, reset `0x01000BD9`), runs at `0x01000000`. Contains the LZSS decompressor (`0x01000C76`). |
| `0x4000` | Second "ESC91.000" image (0x103C bytes), plaintext. Not analysed. |
| `0x8000` | `TR-8:Updater 12-0801`, compressed, 180 KB decompressed |
| `0x30000` | `TR-8:Appli 18-0926_11:19:43`: the main application (compressed), 1,243,616 bytes decompressed |
| `0x280000` | Second `TR-8:Appli` module, 1,074,732 bytes: firmware of a **second processor** (section 2). Contains `BSSESC2` strings. |
| `0x2F8000`-end | 0xFF fill |
| trailer | `{0x30, 0x3DF, 0x1000, 0x400000}`: first block, last block, block size, image size |

Module header (0x40 bytes, little-endian):

| Offset | Field |
|---|---|
| +0x00 | name, 0x28 bytes ASCII |
| +0x28 | load address (`0x60000000`) |
| +0x2C | header size (0x40) |
| +0x30 | compressed size |
| +0x34 | **32-bit byte-sum of the compressed payload** |
| +0x38 | destination address |
| +0x3C | decompressed size (0 = stored, not compressed) |

Compression: Okumura LZSS. 4096-byte ring starting zeroed, initial position `0xFEE`, flag byte
LSB first, flag bit 1 = literal; a match is 2 bytes: 12-bit absolute ring position and 4-bit
length + 3. `tools/tr8fw.py` decompresses and recompresses it (round trip verified).

CPU: ARMv7-M class (Thumb-2 only, `msr basepri`).

## 2. Boot loader

Runs from flash at `0x01000000`. Main flow at `0x01000B7A`:

1. `FUN_0100038E` selects the image from a table at `0x01010090` (initial data at boot.bin 0x3318):
   - entry 0: no condition, image `0x03030000` (application);
   - entry 1: GPIO conditions at `0x01010008`: input 12 reads 1 and inputs 0-11 and 13-15 read 0,
     image `0x03008000` (updater).
   Roland's update procedure holds step button [1] at power-on, so GPIO input 12 is step [1]. [unit]
2. For the application, it first sends the module at `0x03280000` to the second processor
   (`FUN_01002374`: 0x40-byte header, then 0x200-byte chunks, handshake byte 0x10; a bad handshake
   stops the boot loader).
3. It loads the selected module to `0x60000000` (`FUN_01000B3C`: LZSS if the decompressed size is
   not 0, else a plain copy) and jumps to it.

**The boot loader checks no checksum and no signature.**

## 3. Updater

`FUN_600053C0` (`writer\force_updater.cpp`) searches the USB storage for `TR8_ROM.BIN`, then
`BSSESC2.BIN`, then `TR8_UPD.BIN`. For `TR8_UPD.BIN`:

1. Trailer (`FUN_6000530A`): file size - 16 = image size, last block >= first block, block size
   not 0, file size >= (last + 1) x block size.
2. Names (`FUN_60005078`): the first 16 bytes at file offsets 0x8000, 0x30000 and 0x280000 must be
   `"TR-8:Updater    "`, `"TR-8:Appli      "`, `"TR-8:Appli      "`.
3. Write (`FUN_60005152`): blocks first..last (flash `0x30000`-`0x3DFFFF`), each block read back
   and compared.
4. Verify (`FUN_60004F3E`): re-reads the three modules from flash and compares each byte-sum with
   header +0x34. A mismatch is error 6. The display shows the sums.

Consequence: with the original trailer, an update **never rewrites the boot loader or the
updater**. If a modified application does not start, step [1] at power-on still reaches the
updater, which can flash the original file. [unit: the procedure works; a failed boot was never needed]

## 4. Application memory map

Scatter table at `0x60000000` (copied and zeroed by the startup code):

| Region | Content |
|---|---|
| `0x60000000`-`0x601264EB` | Code and constants, executed from SDRAM |
| `0x601264EC`-`0x6013085F` (load) -> `0x01000300`-`0x0100A673` (run) | "Fast" code copied to internal RAM: RTOS kernel and drivers. All `thunk_EXT_FUN_0100xxxx` calls go there. Address `0x0100xxxx` = image address `xxxx - 0x300 + 0x601264EC`. |
| `0x601309E0` | End of the loaded image (decompressed size `0x1309E0`) |
| `0x01010000`-`0x01015273` | Internal RAM data + bss |
| `0x01020000`-`0x01027FFF` | Internal RAM, zeroed (stacks [hyp]) |
| `0x20000000`-`0x2000624F` | Tightly coupled RAM data + bss |
| `0x601264EC`-`0x60280987` | Main bss (1.4 MB), zeroed after the fast-code copy |
| `0x60280988`-`0x61FFFFFF` | RTOS memory pool (`FUN_60010430`, about 29.5 MB). SDRAM is 32 MB. |

- MPU (`FUN_60010574`): SDRAM is read/write/execute, so patch code and data can live in the image
  or in the pool. Internal RAM `0x01000000`-`0x0101FFFF` is read-only except its data regions.
- `0x0100A674`-`0x0100FFFF` (about 22 KB) is not in the scatter table [hyp: free, but read-only].
- Ghidra: the ELF made by `tr8fw.py` maps only `0x60000000`. To follow `thunk_EXT_*` calls, add a
  memory block at `0x01000300` from image offset `0x1264EC` (length `0xA374`).
- Reference: the decompressed application has SHA-256
  `3685edab8bbeaef8752df9ef08a73a9fd2a2e69ba8210016132f6d141f6b452e`.

## 5. Application structure

C++, task based (RTOS in the fast code). Source paths in assert strings:
`seq\task_seq.cpp`, `midi\{task_parse,task_asgn,task_midi_rx,midi_drv,midi_tx}.cpp`,
`prm_mgr\*`, `storage\sf_bios.cpp`, `hmi\task_panel*.cpp`, `hmi\manager\*`,
`hmi\parameter\hmi_prm_{patch,patch2,setup,system,ptn,ptn2,efx,testmode}.cpp`,
`control\task_ctrl*.cpp`, `dsp_firm\*`, `driver\{ad_drv2,led_drv,led_drv_mgr,esc2_dsp_drv}.*`,
`writer\force_updater.cpp`, `task_frame\*`.

Tasks that matter for patches:

| Task | Role | Runs |
|---|---|---|
| `task_ctrl` | ADC scan of the controls, change events | on ADC completion |
| `task_panel` | Panel FIFO, HMI dispatcher, screens, parameter changes, display | on events |
| sequencer | Clock tick handler `FUN_6000989C`, per-step functions | per clock tick |

Rule for patches: change parameters from the panel task, or post an event (section 8) so the
panel task does it. The motion patch posts from the sequencer task. [unit]

The panel task starts in a **boot mode** chosen by the buttons held at power-on
(`control\task_ctrl_bootmode.cpp`, 13 modes). It is stored at `0x6007E574` (setter `0x60014026`)
and is 0 in normal use [hyp]. `FUN_600143D4` blocks knobs when it is above 3.

## 6. Parameters and storage

Parameter descriptors: 0x1C-byte records at `0x6005EF4E` (148 entries):
`[0] = 0, [1] = kind, [2:4] = id, [4:] = ASCII name`.

| Ids | Kind | Names |
|---|---|---|
| 0x8C-0xC2 | 3 | Per instrument (BD SD LT MT HT RS HC CH OH CC RC): `_NUM`, `_PAN`, `_ACC`, `_GR`, `_SE` (kit) |
| 0xC3-0xFA | 4 | `VARI`, `SCALE`, `LAST_A`, `LAST_B`, then `STEP_<row>1/2` for 26 rows (AC RV EC SC, 11 instruments, 11 `ACC_<inst>`); each is a 16-bit step mask, 1/2 = variation A/B |
| 0xFB-0x105 | 5 | `<inst>_LEV` (11) |
| 0x129-0x14E | 6 | `WEAK_ACC1/2`, `FLAM_<inst>1/2` |

A pattern stores 16-bit step masks only: **no per-step parameter data**.

USB backup: `TR8_PTN` = 16 patterns x 0x50 named parameters, `TR8_KIT` = 16 kits x 0x42 named
parameters, written as text (`name=value`) by `FUN_600110A4` from the descriptor table; unnamed
ids are not in it. The user flash is a 128 KB area (`TR8_USERAREA.BIN`; USB backup/restore at
`0x60011DBE` / `0x60011E2E`).

Parameter areas (`prm_mgr`; area table `0x6005EB0C`, 16 bytes each: first id, count, slots, ?):

| Area | Ids | Content | Bank 0 (RAM) | Bank 1 (factory, ROM) |
|---|---|---|---|---|
| 0 | 0x00-0x29 | | `0x60143C6C`, 2 slots | |
| 1 | 0x2A-0x88 | Setup / system | `0x60143DBC`, 1 slot | |
| 2 | 0x89-0x8B | | `0x60143F38`, 17 slots | `0x600556E4` |
| 3 | 0x8C-0xC2 | Kit | `0x60144004`, 17 slots | `0x60055864` |
| 4 | 0xC3-0xFA | Ptn | `0x60144EA0`, 17 slots | `0x600581A4` |
| 5 | 0xFB-0x126 | Levels, 0x106-0x11B per-instrument values, 0x11C-0x126 unused (range -1) | `0x60145D80`, 17 slots | `0x60059DA4` |
| 6 | 0x127-0x14E | Ptn2: weak accent, flams, 16 unnamed ids | `0x60146930`, 17 slots | `0x6005BEA4` |

Bank table `0x6005D2A4` (bank x 0x40 + area x 8: base, slots). A value is a 32-bit word at
`base + 4 * (count * slot + id - first)`. Slot 0 is the current pattern or kit; the handlers read
it with `FUN_6000F80E(ctx, area, 0)` + `FUN_6000F844(ctx, id, &v)`. Setters (`FUN_6000F9E0` init,
`FUN_6000FA2C` -> `FUN_6000F920` write, `FUN_6000FA20` commit) check the range in the parameter
table `0x6005D3EC` (16 bytes per id: min, max, default, flags; flags byte 2 = change group), mark
the group and notify (`FUN_60010148`), which leads to the save. `prm_storage_sub.cpp`
(`FUN_6000FD28`, `FUN_6000FE80`) copies whole areas between slots and to flash
(`FUN_60010E92`; `storage\sf_bios.cpp` stores RAM ranges in 256-byte journaled pages).
Ptn2 unnamed ids `0x127`, `0x128`, `0x12B`-`0x138` are read by no code and are 0 in all factory
patterns; the poly patch uses `0x12B`-`0x135` (docs/POLY.md "Storage") and the chain patch index 17
(id `0x138`, docs/CHAIN.md "Storage"). `FUN_600113B2` dumps the factory patterns as C text
(`data_fact_ptn.inc`), a developer function.

Low-level access: `FUN_6000F80E(ctx, area, n)` then `FUN_6000F844(ctx, id, &out)` reads a value by
global id. Change handlers (`FUN_6000A15A`..`FUN_6000AFDC`) copy values into the pattern struct at
`0x6012FA64`.

### Slot copy, commit and pattern load

Two different 12-byte contexts exist; mixing them silently copies nothing:

- **Getter context** (reading): `FUN_6000F80E(ctx, area, slot)` fills
  `{+0 pointer to the first value word, +4 area, +5 0x25, +8 first id}`; `FUN_6000F844(ctx, id,
  &out)` then reads `ctx[0] + 4 * (id - ctx[8])`.
- **Storage descriptor** (copying): `FUN_6000F3C2(ctx, area, slot)` fills
  `{u8 area, pad, u32 slot, u8 0xFF, ...}` — an area/slot address, not a value pointer.

`FUN_6000F3EC(ctx, area, src, 0)` copies area slot `src` into the descriptor's destination slot
and notifies when the destination is slot 0. The pattern load `FUN_6001B842` is exactly
`FUN_6000F3C2(ctx, 4, 0)` + `FUN_6000F3EC(ctx, 4, n+1, 0)` (area 4 slot `n+1` -> working copy).

**The notification** (what a patch that writes slot 0 directly has to reproduce): after the copy,
`FUN_6000F3EC` calls `FUN_60050F70` (no arguments; returns the dispatcher object `0x601264C8`)
and then `FUN_60010148(dispatcher, event)`. `FUN_60010148` walks a circular list of observers
(`{vtable, ..., next}`, next at +8) and calls `vtable[0](observer, event)`. The event is two
bytes `{u8 slot, u8 area}`: `0` for the current slot of the area, `1` for another slot (the
copy sites `0x6000F294`, `0x6000F380`, `0x6000F45A` and the setters' `0x6000F31C`, `0x6000F3BA`
pass 0 and 1 respectively). `FUN_60050F70` may also flush an event queue first. This is how the
screens learn that the working copy changed, and it is what makes a bar selected while the
machine is stopped show up immediately. Do not send it from a payload hook: an early chain build
sent `{0, 4}` from the press dispatch and the synchronous observer walk froze the unit. The chain
patch sets the repaint bit `0x04` of `TR8_HMI_PANEL` instead.

`FUN_6000FC78(_, area, slot, _)` is the **commit**: it copies area slot 0 into slot `slot` and
writes the result to flash (disassembly `0x6000FC82`-`0x6000FCC2`: `FUN_6000F3C2`, `FUN_6000F3EC`,
then `FUN_60010E92` store). The firmware calls it on a pattern change, so it is also the safe way
for a patch to persist the pattern being left. Only this one touches flash; the copies above are
RAM only.

The chain patch redirects the area-4 half of that save (`0x6001B7F4`, inside `FUN_6001B7D8`)
while the current pattern has a side sequence, and keeps the area-6 half stock: area 4 slot *n+1*
keeps the pattern's own steps and the edited bar is appended to a 128-byte-entry log in the
unused flash at `0x3DB000`-`0x3DFFFF` (five blocks of 32 entries, entry *i* at
`0x3DB000 + i * 128`, scratch block at `0x3DA000`, newest entry per pattern/bar wins;
[CHAIN.md](CHAIN.md) "Storage"). A pattern with no side sequence keeps the stock commit.
That range is erased by any firmware update: the updater rewrites blocks over flash
`0x30000`-`0x3DFFFF` (section 3), so the bars are lost on an update, while the two side lengths
survive in the user area. The raw primitives used are `FUN_60003E54(off, len, src)` (program, chunks <=
0x100, 4-byte words), `FUN_60003EA2(off, len, dst)` (read through the mapping at `off + 0x03000000`)
and `FUN_60003EDA(off)` (erase 4 KB); each saves and restores the flash mapping itself.

**They do not touch block protection, and that is a trap.** While the chip's status register
protects the array, a program or an erase is silently dropped — no error, the data simply does not
change. The stock store (`FUN_60010BB6`) brackets its erase/program loop with
`FUN_600108AA` (`bl` at `0x60010BE0`) and `FUN_600108BA` (`bl` at `0x60010D14`):
`FUN_600108AA` writes status register `0x00` (nothing protected) and switches to indirect mode,
`FUN_600108BA` returns to memory-mapped mode and writes `0x3C` (protected again). One session
covers many operations (the factory flash test at `0x60001EEA` opens it once and runs 16 programs).
`FUN_60003E02` is the status write, `FUN_60003DB0` writes `0x3C`. A patch that programs flash
outside a session — as the first bar-chain build did — saves nothing at all, and an emulated
flash that accepts every write hides the failure.
[CHAIN.md](CHAIN.md) "Storage" has the entry layout.

Area 4 (Ptn) slot word order is the descriptor order: word 0 = `VARI` (id `0xC3`), 1 = `SCALE`
(`0xC4`), 2 = `LAST_A` (`0xC5`), 3 = `LAST_B` (`0xC6`), then the 26 A/B mask pairs. A plain
VARIATION A/B press changes `VARI` through the Ptn database object `0x6007ED24`:
`FUN_600186FA(0x6007ED24, 0, 0 or 1, 0)` (index 0 = `VARI`), so writing slot 0 word 0 has the same
effect as the button.

HMI parameter databases (names at `0x6007EC0C`): System, Setup, Efx, Patch, Ptn, Patch2, Ptn2,
Testmode, TMP. Each has a getter `get(db, index, default)` that maps a local index to a global id:

| Database | Getter | Notes |
|---|---|---|
| Setup | `FUN_6001B12E` | index n = global `0x2A + n` (`hmi_prm_setup.cpp`). Object `0x60149F38`. |
| System | `FUN_6001B432` | |
| Ptn | `FUN_6001B736` | index 0 = `VARI`, 1 = `SCALE`, index -> id `0xC3 + index` (`FUN_6001B606`) |
| Ptn2 | `FUN_6001D3FA` | weak accent, flams |
| Patch / Patch2 | `FUN_6001A99A` / `FUN_6001AD68` | kit |

Setters: `FUN_6001B166` (Setup) and the generic `FUN_600186FA(obj, index, value, sub)`, which
asks the range (vtable +0x1C), clamps, reads the current value (+0x08) and writes only on change
(+0x18).

Known Setup indexes: 0 = panel mode (section 9), 6 = master volume, 0x13 = tempo fine (-10..+10),
0x14 = shuffle (0..100), 0x15 = toggled by button 0x1B [hyp: sync/start state].

## 7. Sequencer

State struct at `0x6007E100`:

| Offset | Meaning |
|---|---|
| +0x02 | **running** (1 while playing) [unit] |
| +0x03 / +0x04 | started / pre-step flags |
| +0x14 | step callback, called as `cb(step, variation)` (installed at run time, not traced) |
| +0x18 | **step counter in half steps** [unit]: the step functions run on even values; with scale value `0x32` on odd values too |
| +0x1C | last counter value of the pattern (from the pattern struct) |
| +0x20 | tick inside the half step |
| +0x24, +0x2C | tick period and timing values (from the tempo, float) |
| +0x28 | scale/clock mode (`0x32` seen) |
| +0x30 | ticks per half step |

- `FUN_6000989C`: clock tick handler. Increments +0x20; at +0x30 it advances +0x18, wraps after
  +0x1C (`FUN_600095F0` resets), then runs the step function.
- `FUN_6000981E` (even counter) and `FUN_600097DA` (odd counter in scale `0x32`) both call
  `FUN_6000978E(p, step)` and the step callback. `FUN_6000981E` first calls `FUN_600097DA` when
  +0x04 is 0, so **the per-step code usually runs twice per step** [unit]. Call sites
  `0x60009862` and `0x60009808` are good per-step hooks.
- `FUN_60009746` builds the triggers of the step, then `FUN_6000DE34(ctx, mask, levels[11],
  accentMask)` fires the 11 voices (`FUN_60027120`..`FUN_60027384`).
- `FUN_60009AF8`: 32-slot x 0x14-byte delay queue for scheduled triggers (flam, shuffle).
- Pattern struct at `0x6012FA64`: +0x10 = current variation (0 = A, other = B) [unit], read at
  `0x6012FA74`; +0x14 / +0x18 = last step values (`FUN_600525F8`).
  Per-row records of 6 bytes `{u16 A, u16 B, u8 mute}`: +0x20 + 4n (AC RV EC SC, no mute byte),
  +0x30 + 6i (instrument i steps), +0x72 + 6i (accents), +0xBA + 6i (flams). Instrument order
  BD SD LT MT HT RS HC CH OH CC RC. Read with `FUN_600528CC` / `FUN_600525D0` / `FUN_6005260A(obj, i)`:
  the mask of the current variation, 0 if muted [code].

### Pattern restart and variation

`FUN_600095F0` restarts the pattern: it resets the counters, loads the panel parameters into the
pattern struct `0x6012FA64`, applies the variation, reads the last step and runs the player. It is
called at sequencer start (`0x600091A2`, `0x600098E4`) and at **every pattern wrap**
(`0x600098CA`, from `FUN_6000989C` when the counter passes +0x1C).

Inside it, `FUN_6000E404` applies the variation: struct +0x0C is the panel setting `VARI`
(0 = A, 1 = B, 2 = A+B, written by buttons `0x17`/`0x18`), and if it is 2 the effective
variation (+0x10, read as `0x6012FA74`) is toggled, else `VARI` is stored. Then `FUN_6000E152`
writes the step, accent and flam masks of that variation into the player object. The last step is
read **after** this (`FUN_600525F8`), so the variation must be set before `FUN_600095F0` returns.

The struct is filled from area 4 **slot 0** (the working copy) just before that, by
`FUN_6000E0FE` (called at `0x6000960E`): `+0x0C` = id `0xC3` (`VARI`), `+0x14` = `0xC5`
(`LAST_A`), `+0x18` = `0xC6` (`LAST_B`), `+0x1C` = `0xC4` (`SCALE`, passed through
`FUN_6000E0E0`, which maps 0->8, 1->4, 2->6, **3->3**), then the 26 mask pairs. So a restart
always reloads the working copy; a patch that wants other content must write the struct after
`FUN_6000E0FE` and before the last-step read (this is what the chain patch does at `0x60009614`,
filling it from the bar and side of this pass and leaving `FUN_6000E404` as the stock fallback for
a side that has no sequence).

`FUN_6000E4A6` (pass end, called from `0x60009964`) is gated by `FUN_6000E472` and only loads a
*pending* pattern change, so it does not clobber content written by such a hook during playback.

Button handler `FUN_6001961E` dispatches button id 0x00-0x0F to `0x600199F4`, which first tests
LAST STEP (`0x1A`) and then sets the pattern length (`FUN_6001B8D6` at `0x60019A10`). The pad id
is still in `r6` there, so a hook on the `bl FUN_60013168` at `0x600199F6` can read it. Button
`0x17`/`0x18` with TR-REC held is already used by the firmware (`0x6001974C`, `0x60019798`, calls
`FUN_6001B736` and rewrites +0x10), so it is not free for patches.

### Step trigger

The masks that play are copies in the **player object `P = 0x6014A164`** (`uint32_t` words),
written by `FUN_6000E152` and the change handlers (setters `FUN_60026AAE`... ) [code]:

| Word | Meaning |
|---|---|
| P[1] | run: set by `FUN_60026894(P, 0, run)` (start `0x6000966E`, stop `0x600096AE`) |
| P[3] | last step index (`FUN_600268F4`) |
| P[0x20] | global accent mask; P[0x4D] weak accent |
| P[0x21 + i] | step mask of instrument i |
| P[0x42 + i] | accent mask of instrument i |
| P[0x66] | **play position** (step 0..last). Stop sets it to last, so the next advance plays 0 |
| P[0x67 + i] | flam mask of instrument i |
| byte +0x1D8, s16 +0x1DA, bytes +0x1DC | scatter: order length, index (-1 = off), step order |

`FUN_600262F2(P, step, flam)` plays one step. With step -1 it advances P[0x66] (if P[1]: +1, 0
after P[3]), then applies the scatter order. It then tests the single bit `1 << step` in every
mask and sends the hits to the sound engine. flam != 0 (explicit step, from the delay queue at
`0x60009A50`) also needs the flam mask. Returns bit i = instrument i fired. **[unit]**: hooking
the calls below and swapping mask bits changes what plays (POLY.md hardware test 1).
Callers with -1: `0x60009800`, `0x6000985A`, `0x60009884` (at counter 0, after setting P[3] to
0, which forces step 0), `0x60026910`. This is the hook used by [POLY.md](POLY.md).

## 8. Controls (knobs and faders)

### Control ids

49 controls. The id is what every layer above the ADC uses. Names come from the factory test
table at `0x6007E874` (16-byte records `{id, name, LED group, 0}`, short names at `0x6007D6A0`)
and the fader table at `0x6007E7EC` (12-byte records `{id, name, 0}`). Type: 0 = knob,
1 = fader, 2 = knob with a centre detent (bipolar). CC = the internal MIDI CC the global table
sends (section 10).

| Id | Name | Control | Type | CC |
|---|---|---|---|---|
| 0 | VOLM | Master volume | 0 | Setup[6] |
| 1 | ACLV | Accent level | 0 | 71 |
| 2 | GRGT | Reverb gate | 0 | 90 |
| 3 | GRLV | Reverb level | 0 | 91 |
| 4 | GRTM | Reverb time | 0 | 89 |
| 5 | SETM | Delay time | 0 | 17 |
| 6 | SEFB | Delay feedback | 0 | 18 |
| 7 | SELV | Delay level | 0 | 16 |
| 8 | BDTU | BD tune | 0 | 20 |
| 9 | BDAT | BD attack | 0 | 21 |
| 10 | BDCO | BD compression | 0 | 22 |
| 11 | BDDC | BD decay | 0 | 23 |
| 12 | BD | BD level | 1 | 24 |
| 13 | SDTU | SD tune | 0 | 25 |
| 14 | SDSN | SD snappy | 0 | 26 |
| 15 | SDCO | SD compression | 0 | 27 |
| 16 | SDDC | SD decay | 0 | 28 |
| 17 | SD | SD level | 1 | 29 |
| 18, 19, 20 | LTTU, LTDC, LT | LT tune, decay, level | 0, 0, 1 | 46, 47, 48 |
| 21, 22, 23 | MTTU, MTDC, MT | MT tune, decay, level | 0, 0, 1 | 49, 50, 51 |
| 24, 25, 26 | HTTU, HTDC, HT | HT tune, decay, level | 0, 0, 1 | 52, 53, 54 |
| 27, 28, 29 | RSTU, RSDC, RS | RS tune, decay, level | 0, 0, 1 | 55, 56, 57 |
| 30, 31, 32 | HCTU, HCDC, HC | HC tune, decay, level | 0, 0, 1 | 58, 59, 60 |
| 33, 34, 35 | CHTU, CHDC, CH | CH tune, decay, level | 0, 0, 1 | 61, 62, 63 |
| 36, 37, 38 | OHTU, OHDC, OH | OH tune, decay, level | 0, 0, 1 | 80, 81, 82 |
| 39, 40, 41 | CCTU, CCDC, CC | CC tune, decay, level | 0, 0, 1 | 83, 84, 85 |
| 42, 43, 44 | RCTU, RCDC, RC | RC tune, decay, level | 0, 0, 1 | 86, 87, 88 |
| 45 | SHFL | Shuffle | 2 | Setup[0x14] = v x 100 / 255, then CC 9 |
| 46 | FINE | Tempo fine | 2 | Setup[0x13] = v x 21 / 255 - 10, then tempo |
| 47 | EXLV | External input level | 0 | 12 |
| 48 | EXSC | External input side-chain | 0 | 13 |

The control meanings come from the names and the TR-8 panel; the CC column comes from the code.
All CC numbers in this table agree with the official Roland TR-8 MIDI Implementation Chart
(v1.11, Nov. 18, 2014). The chart also lists CC 68, 69, 70 (SCATTER TYPE, DEPTH, SW) as receive
only; the scatter controls are not in these 49 ids [open: where the firmware reads them].
BD tune (id 8) is [unit] (used in the motion tests).

### Control path (normal play)

1. **ADC scan.** `driver\ad_drv2.c` scans 8 mux x 8 channels. The completion callbacks
   (`0x6000152C`, `0x60001534`, registered by `FUN_60001556`) set event flags on `task_ctrl`.
2. **Control table.** `task_ctrl` runs `0x60000D2A`, which walks the 49 entries at `0x600544D0`
   (8 bytes: `type, index`) and calls `handler[type](index)` (table `0x60054658`):
   type 0 `0x60000F72` (knob table `0x60054688`: id, ADC channel, change threshold),
   type 1 `0x60001076` (fader table `0x60054718`), type 2 `FUN_60001242`. Values are 0-255.
3. **Change event.** When a value moves past its threshold, the handler calls the callback
   `0x60000CC0(id, value)` (registered by `FUN_60000D06`). It posts `{u8 0x0B, u8 id, u16 value}`
   with `FUN_60001A2E` to the listener list at `0x6007DC28`. **Calling `0x60000CC0` yourself is
   the same as moving the control.** [unit]
4. **Panel FIFO.** The `task_panel` listener (`FUN_60012D94`, 0x400-byte `pdw_fifo`) queues it.
   The push (`FUN_60001930` / `FUN_600017E4`) is inside a critical section (`0x6004B87C` /
   `0x6004B886`), so other tasks can post. The pop callback `0x60014114` -> `0x6001406C`
   dispatches on the first byte; 0x0B goes to `FUN_60013DE0(id, value)`, which pushes the HMI
   event `{s16 10, s16 id, s16 value}` into the HMI ring (`FUN_60013B94`, 256 x 12 bytes).
5. **HMI dispatcher** `FUN_60013C3E` (switch on the event type). Type 10 (control) goes to
   `0x60013892`:
   - returns if `FUN_6001A27C(DAT_60013950)` reports a modal state;
   - stores the value in the per-control table `0x60148924 + 0x28 + id * 8`;
   - calls `FUN_60013242(screen, event)` (**`bl` at `0x600138C8`**) so the active screen can
     take the event;
   - if the screen returns 0, tail-calls **`FUN_60013F6A(id, value)`**, the global control table
     (`0x60019B36`, a switch: section 10). [unit: hooking `0x600138C8` sees every control move]
6. **Screen handlers.** Screen manager state at `0x6007E510` (+0x06, +0x2E = screen ids compared
   by `FUN_60013242`). Some screens use the base class handler `FUN_600141DE`, which calls
   `FUN_6001446A(ctx, id, value)` (another control -> HMI parameter map) unless the knob redirect
   byte `0x6007E580` is set. **`FUN_6001446A` is not on the normal path**: the first motion
   prototype hooked it and recorded nothing. [unit]

## 9. Buttons and panel mode

### Button events

The HMI dispatcher handles button press as type 5 (sets the button bit, see below) and type 6
[hyp: release]. Panel FIFO events 1 and 2 go to `FUN_60013BC2` / `FUN_60013CE0`. The main button
handler is `FUN_6001961E(ctx, id)`:

| Id | Button / action | Confidence |
|---|---|---|
| 0x00-0x0F | Step buttons 1-16. In step mode they call `FUN_6001B8D6` (write through the Ptn database) | code |
| 0x11 | **TR-REC**. Sets Setup[0] = 0 | **unit** |
| 0x12-0x16 | Mode buttons: Setup[0] = 1..5 (0x13 gives 8 while 0x11 is held) | code |
| 0x17, 0x18 | Write `VARI` = 0/1/2 (variation A, B, A+B) | hyp |
| 0x19 | Cycles `SCALE` 0..3 | code |
| 0x1B | Toggles Setup[0x15], may call the sequencer (`FUN_600099B6`) | unclear |
| 0x1A | **LAST STEP** (modifier). A step pad with it held calls `FUN_6001B8D6(obj, pad)` (`0x60019A10`), which sets `LAST_A`/`LAST_B` (Ptn index 2 + variation) | **unit** (POLY.md test 2) |
| 0x1C | **CLEAR** (modifier). With CLEAR held, an instrument button clears its row (`FUN_600193E0`); `FUN_600192BA` (clear a step) also needs it | **unit** |
| 0x1D-0x2B | Row buttons: 0x1D-0x20 = AC RV EC SC; 0x21-0x2B = instruments BD SD LT MT HT **HC RS** CH OH CC RC: RS and HC are swapped compared with the pattern/player order (POLY.md test 2) | **unit** (RS/HC), code (others) |
| above 0x2B | Not mapped (0x2E, 0x37 are used as modifiers somewhere) | - |

### Button held state

`FUN_60013168(id)` returns 1 while button `id` is held. **[unit]** It reads one bit per id in a
bitmap at `0x6014893C` (`0x60148924 + 0x18`), set by the type-5 event. The firmware uses it for
button combinations; patches can use it the same way (the motion patch: TR-REC and CLEAR).

### Press and release dispatch: the screen goes first

A press (event type 5) goes to `FUN_600137DE`, which sets the held bit and then calls
`FUN_60013B34(id)` (`bl` at `0x60013842`). That call offers the press to the **active screen**;
the global button handler `FUN_6001961E` runs only if the screen declines it (`0x60013F74`, i.e.
`FUN_60013F6A`). Releases (type 6) go to `FUN_6001377C`, which clears the held bit and calls
`FUN_60013B56(id)` (`bl` at `0x600137D2`) with the same screen-first order (`0x60013F7E`).

Consequences for patches:

- A **bare step pad** press is taken by the screen (step edit, sound audition), so it never
  reaches `FUN_6001961E`. LAST STEP + pad and the variation buttons are declined by the screen
  and do reach it; that is why the stock LAST STEP gesture is implemented there.
- A patch that must see **every** press (the bar chain, `docs/CHAIN.md`) has to replace the
  `bl` at `0x60013842`, before the screen, and swallow the matching release at `0x600137D2` if
  it takes the press.
- The held bitmap is already set when the dispatch is called, so `FUN_60013168` inside such a
  patch sees the pressing button itself as held. [unit: the first chain build's probe]

### Panel mode

The mode chosen with the mode buttons is **Setup[0]** (object `0x60149F38`, global id `0x2A`),
read with `FUN_6001B12E(0x60149F38, 0, 0)`.

- `FUN_600192BA` (clear a step bit) works only in modes 0 and 3.
- `FUN_60004D8C` (incoming note) writes it into the pattern (`FUN_6001912C`) only in mode 3.
- 0 = TR-REC (step edit) [unit: 0x11 = TR-REC sets 0], 3 = INST REC (real-time record).
  Modes 1, 2, 4, 5 and 8 are not identified; `FUN_6004D21C`, `FUN_6004D7C0` and `FUN_6004D814`
  seem to set 6 and 7.

Do not confuse it with the boot mode at `0x6007E574` (section 5).

## 10. Sound parameters (internal MIDI CC)

The global control table `0x60019B36` (reached from `FUN_60013F6A`) maps a control id to a
number and calls `FUN_60015906(obj, n, value)`. That function builds the 4-byte message
`{0x0B, 0xB0, n, value}`, a **MIDI Control Change** (status 0xB0), and gives it to
`FUN_60006E70`, the internal MIDI message queue. The numbers are the TR-8 MIDI implementation
CC numbers (BD tune 20, BD attack 21, ...; table in section 8). So:

- To change a sound parameter, a patch can call `FUN_60015906(0, cc, value)` with the panel's
  0-255 value [code; the value range on this path is the raw knob value].
- Posting a control event (section 8, step 3) also updates the screen state and the display; a
  direct CC does not.

Exceptions in the table: id 0 (VOLM) sets Setup[6]; ids 45 and 46 (SHFL, FINE) set Setup 0x14 and
0x13 and, for FINE, recompute the tempo (`FUN_600089E6`, `FUN_60008A2A`). The tempo itself is
HMI index 0x12 / 10 (`FUN_600089E6`).

## 11. Display and LEDs

- **Text:** `FUN_60015980(any, const char *s)` loads the display object `0x6014891C` and jumps to
  the fast-code function `0x01000460` (thunk `0x6004BB24`). Screens build their text with
  `FUN_60049F9C` (an `sprintf`, for example `" %c%2d"`) and call it. The factory test shows the
  4-letter control names with the same call (`FUN_6001A406`). The active screen overwrites the
  text on its next refresh. [code]
- **The screen's repaint bits.** The screen object is `0x60149B8C` (not the Setup database object
  `0x60149F38`; the two are `0x3AC` apart). It keeps a halfword of dirty bits at +0. The panel
  dispatcher `FUN_60016C08(obj)` serves them one per pass and clears each: `0x01` the pad LEDs
  (`FUN_60016BB8`), `0x02` `FUN_600169A4`, `0x04` `FUN_60016386` (the view-0 step pads), `0x08`
  `FUN_60016026`, `0x10` `FUN_60015EFA`, `0x20` `FUN_60015C8C`, `0x40` the screen's own numeric
  text (`FUN_60015986`); any bit still left ends with the whole word cleared.
  The firmware's own "repaint pads and text" is `FUN_60051E20`: `ldr r0,[0x60051E2C]` =
  `0x60149B8C`, `ldrh r1,[r0]; orr r1,#0x44; strh r1,[r0]; bx lr` — thumb `0x60051E21`. The panel
  calls it at `0x60008CDA`, `0x60008D4C`, `0x60008DA4`, `0x60008DC8` and `0x60008E36`.
  The tick `FUN_60016D00` counts down and tail-calls the dispatcher, and the setter
  `FUN_60016D58(obj, value)` writes `value` at +8, sets `0x40` and lets the dispatcher draw it
  (`str r1,[r0,#8]; ldrh; orr #0x40; strh; bx lr`). So a patch can show its own text and then set
  `0x40` to have the screen paint its normal value again on the next tick; calling
  `FUN_60051E20` sets both `0x04` and `0x40`. The chain patch sets `0x04` itself (a halfword OR
  on `0x60149B8C`) to redraw the step view after it loads a bar into area 4 slot 0, and calls
  `FUN_60051E20` when the variation button is released. [code]
  **Never write `0x60149F38`:** it is the Setup parameter database (the `db` of
  `FUN_6001B12E(db, idx, def)`), and ORing a repaint bit into its first byte corrupts the
  database; the panel then reads through a bad pointer and the whole unit hangs (the chain
  builds `8941d9e` and `bd5fcdc` froze that way). [unit]
  Do not call the slot-0 notification `FUN_60010148` from inside the button dispatch either: the
  chain build that did froze the unit when a bar was changed. [unit]
- **LEDs:** `FUN_6001A7EC(id, a, b, c)` calls the fast-code function `0x01000536` with the LED
  object `0x601488D0`. Seen: `FUN_6001A7EC(0x2A, 1, 0, 0x10)`, instrument LEDs 0x1D-0x25. The
  argument meaning is not decoded. [hyp]
- **Step/pad pads and the palette.** Pads (step LEDs) are ids `0x1D`+step (`0x1D`-`0x2C`). All
  screens paint them through four small setters, and every one of them ends in
  `bl FUN_6004BB4C`, a veneer to the fast-code LED function `0x01000537` called as
  `(object 0x601488D0, led, a, b, c)`:
  - `FUN_6001773A(led, a, b, c)` raw levels (`0x60017748`),
  - `FUN_6001774E(led, colour)` palette lookup (`0x6001776C`),
  - `FUN_60017E08(led, a, b)` a copy of the raw setter that always passes c = 0 (`0x60017E18`),
  - `FUN_60017E1E(led, colour)` a copy of the palette setter (`0x60017E3A`).

  Because the hook can sit in the setters, one function covers the sequencer, PTN SELECT, TR-REC
  and every other view, and survives a pattern change (which switches screen and renderer). The
  palette table is at `0x6006061C`, 12-byte entries `{u8 a; u32 b; u32 c}`, looked up by
  `FUN_60015846(obj 0x6007EB08, colour, out)`. Resolved triples seen: `0` = `(1, 0, 2)` the play
  position (the firmware blinks it), `1`/`2` = red/orange, `3` = `(1, 9, 6)` the yellow step
  group, `4` = white, `0x2A` = `(1, 9, 2)` green (inside the pattern length in the LAST STEP
  view), `0x2D` = `(0, 0, 2)` off. The normal step view `FUN_600162D2` does not use the palette:
  it calls `FUN_6001773A(led, a, b, c)` with raw levels at `0x60016376`. The view-0 pad loop of
  `FUN_60016386` uses `FUN_6001774E` (for example `0x60016506`). [code]

## 12. Code space for patches

- **Developer dump cave** (used by the `motion`, `poly` and `motion-poly` patches): `FUN_6001114E`
  and `FUN_600113B2` are only called from a developer branch of the USB backup (`0x60011E00`,
  `0x60011E04` in `FUN_60011DBE`). With those two calls replaced by `nop.w`,
  `0x60011150`-`0x60011463` (788 bytes) and `0x60011488`-`0x60011BB5` (1838 bytes) are free. The
  literal pool `0x60011464`-`0x60011483` is still used and must stay. The motion patch uses
  737 + 1568 bytes; `motion-poly` uses about 340 + 730 bytes, its zeroed data is in patch RAM
  (below). The bar chain used these regions in its earlier builds and no longer does.
- **Grow the image (used by the bar chain since the module build).** Code appended at the end of
  the image (`0x601309E0`) would be erased, because the bss zero-fill covers
  `0x601264EC`-`0x60280987`. Instead:
  1. extend the decompressed size so that the image reaches the new code. The bytes between
     `0x601309E0` and the code are zeros and compress well: reaching `0x60282794` costs about
     164 KB of compressed application (0xA5CF7 -> 0xCEDDD), and the module still ends at file
     offset 0xFEE1D, far below `appB` at 0x280000. `tr8patch.py` and the web flasher extend the
     application array themselves when a payload lies beyond the current end.
  2. put the new code and data at `0x60281200` (above the bss, so it is not zeroed). Not
     `0x60280988`: `motion-poly`'s patch RAM occupies `0x60280A00`-`0x60281183`, and the 64 KB
     below the moved pool is that reservation. The chain's `.text` is
     `0x60281200`-`0x60281E66` (3174 bytes) and its `.bss` (including the 2 KB playback cache)
     runs to `0x60282794`; the patcher reserves 8 KB, `0x60281200`-`0x60283200`.
  3. move the RTOS pool start by N: the literal `0x60280988` at `0x600104A8`
     (`FUN_60010430`) becomes `0x60290988`, the same move `motion-poly` makes. The other copy at
     `0x6012A2FC` is the startup stack top, not the pool (see the next item). The bss zero-fill
     has its own bounds, literals `0x601264EC` at `0x6000015C` and size `0x15A49C` at
     `0x60000160` (startup code `bl 0x6000009E` at `0x60000078`), so moving the pool start does
     **not** extend the zeroing over the new code.
  The boot loader decompresses any size into SDRAM: `FUN_01000B3C` reads the decompressed size
  from the header and `FUN_01000C76` is bounded only by `destination + size`, with no fixed cap.
  The updater only checks sizes and sums. Emulation passes (249 chain checks and the three
  combinations); a unit run is pending, and the first boot is the thing to watch.
- **Patch RAM by moving the pool start (used by `motion-poly`).** The pool setup `FUN_60010430`
  (called once at boot from `0x60010482`, before the RTOS starts) reads its start from the
  literal at `0x600104A8` and its end (`0x62000000`) from `0x600104A4`. Changing the start to
  `0x60290988` gives 64 KB of SDRAM, `0x60280988`-`0x60290987`, that nothing else uses: no other
  literal in the image (main or fast code) points into it [code]; **[unit]**: the `motion-poly`
  patch runs with it (COMBO.md test 1). The other copy of `0x60280988`
  (`0x6012A2FC`, fast code `0x01004100`) is the startup stack top returned by RVCT
  `__user_initial_stackheap` (stack `0x60280788`-`0x60280988`), not the pool: leave it. This RAM
  is not zeroed at boot; `patches/combo/ram.c` zeroes it before calling the pool setup. Do not
  move the pool end instead: a table at `0x6007638E` lists SDRAM blocks up to `0x62000000`. The
  chain only uses the pool move to keep the pool off its image region; it needs no patch RAM.
- **Other dead code:** not searched systematically. Candidates: developer and test functions
  reachable only from the boot modes above 3.

## 13. Open questions

1. Panel mode values 1, 2, 4, 5, 6, 7, 8.
2. Where the step callback (+0x14) is installed.
3. Is the 16-step limit only in the application, or also in the sound engine (fast code, second
   processor)?
4. What runs on the second processor (`appB`) and over which link?
5. LED function arguments; display text lifetime and how to keep a message visible.
6. Button ids above 0x2B (START/STOP, PATTERN, ...). LAST STEP is 0x1A (section 9).
7. The "grow the image" method (section 12) on a real unit: the bar chain uses it, the boot path
   is emulation-tested only.
8. MIDI: the receive path (`midi\task_midi_rx.cpp`) and whether external CCs take the same path
   as `FUN_60015906`.
