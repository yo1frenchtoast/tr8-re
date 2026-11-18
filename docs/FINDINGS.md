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

CPU: ARMv7-M class (Thumb-2 only, `msr basepri`). Section 4, "Processor and peripherals",
gives the details.

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
   and compared. Each block is erased on its own with the SPI sector erase `0x20` (4 KB,
   `FUN_60003B5E`) and then programmed (`FUN_60004E56`); nothing outside first..last is touched,
   and the trailer check compares nothing with a fixed block number. [code] The patcher therefore
   writes `last = 0x3D9` in every file it builds: the blocks above are `0xFF` padding in Roland's
   file and hold the bar chain's flash log (`0x3DA000`-`0x3DFFFF`), which a reflash then keeps.
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

### Processor and peripherals

Method: list every constant that the code loads with `ldr rX, [pc, #n]` and that is in
`0x40000000`-`0x5FFFFFFF` or at `0xE0000000` and above. This was done for the boot loader, the
fast code (`0x01000300`-`0x0100A673`, disassembled as `thumbv7m`) and `appB`.

**Core.** ARMv7-M with the standard System Control Space. [code]

- The code uses the NVIC priorities `0xE000E400`, AIRCR `0xE000ED0C`, VTOR `0xE000ED08`, SHPR
  `0xE000ED18`, ICSR `0xE000ED04`, CFSR `0xE000ED28`, DEMCR `0xE000EDFC`, STIR `0xE000EF00` and
  the ITM `0xE0000E80`.
- It uses the bit-band alias (`0x42xxxxxx`), so the core is a Cortex-M3 or M4.
- No FPU: no CPACR access and no VFP instruction. Six M4-only instructions (`smlad`, `smmla`,
  `pkhtb`...) decode in the application, but they are in areas that look like data tables. So
  nothing shows an M4, and the code is consistent with a Cortex-M3. [code]
- **No SysTick access** in the boot loader, the application or `appB`. The only constant in
  that range, `0xE000E01B`, is the base of a byte write at `+0x400`, which is an NVIC priority
  (`0xE000E41B`, `0x60001DFA`). The RTOS tick comes from a vendor timer. [code]
- The application also uses the MPU (`0xE000ED98`, `FUN_60010574`). [code]

**Memory.** Code and internal RAM at `0x01000000`, serial flash mapped at `0x03000000` (section
1), tightly coupled RAM at `0x20000000`, SDRAM (32 MB) at `0x60000000`. [code]

**Vendor peripherals.** A constant counts as a register address only when the next instructions
use it as the base of a load or a store. Many constants in `0x40000000`-`0x401FFFFF` are the
high words of `double` values (`0x40100000` = 4.0, `0x40140000` = 5.0, `0x40160000` = 5.5): the
blocks `0x4014xxxx`-`0x4017xxxx` that the first scan found are such constants, not peripherals.

| Block | Role | Evidence | Tag |
|---|---|---|---|
| `0x40005000` | **Serial flash controller** (the 4 MB flash) | `FUN_60003D74`-`FUN_60003F8A` write the SPI opcode to +0x18: `0x01` (write status, data `0x3C`), `0x02` (page program), `0x20` (sector erase). +0x1C address, +0x10 length (`0x60000000` + byte count), +0x30 transmit FIFO, +0x08 FIFO level, +0x00 bits 29-30 mode (0 = memory-mapped read, 3 = command). | [code] |
| `0x40029800` | **MIDI UART** | `midi_drv.cpp` (`FUN_60006438`) sets channel 6 to 31250 baud through the ROM table. The receive interrupt (fast code, load address `0x6012F074`) reads the status at `0x40029804` (error bits `0x3800`; bit 11 is reported as error 3, the others as error 2; writing bit 15 clears them), the byte at `0x40029808` and the receive FIFO level at `0x40029818` bits 8-15. The transmit service (load address `0x6012F0CE`) passes `0x40029808` to `FUN_600069A0`, which writes up to 16 queued packets there, then clears bit 9 of `0x40029814` (transmit interrupt enable) when the queue is empty. | [code] |
| `0x40029C00` | Second serial channel, same layout as `0x40029800` | The boot loader initialises both with the same code (`0x01001AC6`, `0x01001B5C`). Use not known. | [code] |
| `0x4002C000` | **ADC** (knobs and faders) | `ad_drv2.c`: `FUN_60001C00` configures it. The interrupt (load address `0x6012B260`) reads 8 results at +0x10-+0x2C for one of 8 multiplexer ports (`ADDRV_CONFIG_NUMOF_MPX`). `FUN_6012B34C` returns the median of 4 samples. | [code] |
| `0x40025000` | **Timer**, channels 0x20 apart | `ad_drv2.c` (`FUN_60001AD4`): period `0x2616` at +0x00, control `0x46` at +0x08. The same values at +0x20/+0x28 (`FUN_60001DC0`). It paces the ADC scan [hyp]. | [code] |
| `0x40007000`, `0x40008000`, `0x40044000` | **USB host** and its DMA | `usbh_dma_drv.cpp` (`FUN_6000075E`, `FUN_600007E6`) writes `0x40008608` and `0x40008C00`. The boot loader sends `appB` to the second processor (`FUN_01002374`) through these three blocks. Which block is the controller, the DMA or the PHY is not known. | [code] |
| `0x40003000` | DMA controller [hyp] | `FUN_600002C0` waits for a free channel, writes +0x94 and +0x9C (addresses [hyp]), then sets bits 30-31 of +0xA0 (enable [hyp]). | [hyp] |
| `0x4002D000` | Memory controller (SDRAM) [hyp] | The boot loader writes +0x00-+0x30 early (`0x010004E0`), before it decompresses to SDRAM. `FUN_6001029A` writes the same offsets. | [hyp] |
| `0x40100000`, `0x40101000` | DSP interface [hyp] | Only fast code uses them, from the `esc2_dsp_drv.cpp` paths (`FUN_6012C9EC` and others). `appB` uses them too. | [hyp] |
| `0x40010000` | System control (clocks, reset) [hyp] | About 30 small read-modify-write functions, from `task_sys.cpp`, `task_dsp.cpp` and the drivers. | [hyp] |
| `0x40001000`, `0x40002000`, `0x40012000`, `0x40017000`, `0x40023000`, `0x40030000`, `0x40040000` | Not known | Few accesses each. `0x40012000`: `esc2_dsp_drv.cpp` path. `0x40040000`: also used by `appB`. | |

**MIDI transmit queue** [code]. The MIDI context `0x200057E4` (tightly coupled RAM) holds at +4
a ring of 4-byte USB-MIDI packets (byte 0 = code index number, bytes 1-3 = the MIDI message):
`{vtable, start, end, read, write}`, vtable `{lock, unlock}`. `FUN_6000758A` adds a packet,
`FUN_600075C8` takes one. `FUN_60006964` sends a packet's bytes; the byte count comes from a
table indexed by the code index number (`FUN_60006944`), and `FUN_600068F6` leaves out a status
byte equal to the last one sent (running status, kept at context +0x160). Checked in emulation:
two Note On on the same channel go out as `90 24 7F 26 40` (`tests/emu_periph.py`).

**ROM function table** [code]. The firmware calls on-chip ROM routines through a table of
function pointers at `0x02003000`. The ROM is not in the update file. Entries used: the boot
loader calls +0x0C, +0x14, +0x18, +0x58; the application calls +0x08, +0x0C, +0x58, +0x70,
+0x7C, +0xC8, +0xCC, +0xE0, +0xF0, +0x134, +0x27C, +0x280, +0x284. The flash driver uses +0xCC
before each command (write enable [hyp]), +0xF0 until it returns 0 (controller busy [hyp]) and
+0xC8 until bit 0 is clear (read the chip status [hyp]). `midi_drv.cpp` configures the UART with
+0x280(6), +0x27C(6, 0x40) and +0x284(6, 31250, 0).

**Serial flash registers** [code], from `FUN_60003D74`-`FUN_60003F8A`: +0x00 mode in bits 29-30
(the driver writes `0x80001000` for command mode 0, `0xE0001000` for memory-mapped mode 3);
+0x08 transmit FIFO level in bits 0-4, `0x7F0000` written after each command; +0x10 data length,
`0x60000000` added when there is an address; +0x18 SPI opcode (the write starts the command);
+0x1C address; +0x30 transmit FIFO, one word per write. A program sends the first word before the
opcode and the rest after it. `FUN_60003EA2` (read) switches to mode 3 and reads the window at
`0x03000000`; the erase and program functions switch to mode 0. Each function puts the caller's
mode back. `FUN_60003E54` splits a program into 256-byte commands from the address it gets, so a
write that crosses a page end must start on a page boundary ([DEVELOPING.md](DEVELOPING.md),
"Pitfalls found in review").

The second processor runs a USB **device** driver (`cmni\cmni_usb_dev_drv.cpp` in `appB`). With the
USB host on the main processor, the link between the two ESC2 is probably USB [hyp]. Which chip
drives the USB port at the back of the TR-8 is not known.

**Identity.** The map matches no common microcontroller family that we compared it with (STM32,
NXP LPC17xx/18xx, Microchip SAM3/SAM4, Fujitsu FM3, Toshiba TMPM). For example, an STM32 has its
flash at `0x08000000` and its RCC at `0x40023800`. [hyp]

The board photos answer the question [unit]. The TR-8 has **two Roland ESC2 chips**, both
marked `Roland ESC2 / 5100015275 / JAPAN / 1404 Z68 / E1`. They are on the board
`PWB 5100038970`, with the MIDI jacks, the USB port and the power input. There is no other
processor on this board or on the main board.

| Board | Part | Function |
|---|---|---|
| `PWB 5100038970` | 2 x Roland ESC2 (`5100015275`) | the two processors |
| `PWB 5100038970` | ISSI `IS42S16160D-7TL` (IC5) | SDRAM, 256 Mbit (32 MB) |
| `PWB 5100038970` | ISSI `IS42S16400F-7TL` (IC10) | SDRAM, 64 Mbit (8 MB) |
| main board `5100035503` | ISSI `IS42S16800F-7TL` (IC8) | SDRAM, 128 Mbit (16 MB) |
| main board | AKM `AK5357VT` (IC16) | audio ADC (external input) [hyp] |
| main board | 2 x AKM `AK4385ET` (IC9, IC18) | audio DACs (outputs) [hyp] |
| main board | IC4, SO-8, marking not readable | the 4 MB serial flash [hyp] |

The main board also carries the crossed-out label `SYSTEM-1 MAIN BOARD ASSY`, so Roland made it
for the System-1 too.

The ESC2 contains the ARMv7-M core described above [code]. Only the 32 MB SDRAM agrees with the
application's memory pool (section 4, table), so IC5 is probably the main processor's SDRAM
[hyp]. Which SDRAM each ESC2 uses is not traced on the board.

The second processor (`appB`, section 1) is the same chip [unit: markings]. The code agrees
[code]:

- its startup code is the same ARMv7-M sequence (`msr basepri`);
- it also runs at `0x60000000`;
- it uses the same framework (`task_frame`, `esc2_dsp_drv`, its own USB device driver
  `cmni_usb_dev_drv`);
- it uses the same peripheral blocks (`0x40028000`, `0x4002D000`, `0x40040000`, `0x40100000`).

The names `ESC91.000` (boot loader) and `BSSESC2` (`appB`) agree with the markings. There is
no public datasheet for the ESC2.

Consequence for emulation: the core and the NVIC are standard, but no emulator has models for
these peripherals. Each model must come from its driver in the fast code
([DEVELOPING.md](DEVELOPING.md), section 4, "Limits of the emulation").

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

**Task table and priorities** [code]. The RTOS is uITRON-like: `task_frame\task_mgr.cpp`
(`FUN_600126B2`) creates the tasks from a table of 9 `T_CTSK`-shaped entries of 0x24 bytes at
`0x600600A4` (`{attribute 2 = start at once, exinf, entry, priority, stack size, stack, index, ...}`)
through the kernel call `0x0100123C`, after `FUN_6001266A` has created the initial task from
`0x600601E8`. As in uITRON, **a lower number is a higher priority**. Each task is named by the
source file whose code surrounds its entry (the entries are only reached through the table):

| Priority | Entry | Task (source file around the entry) | Stack |
|---|---|---|---|
| 6 | `0x60008318` | MIDI receive (`midi\task_midi_rx.cpp`) | 1 KB |
| 8 | `0x60008440` | MIDI parse (`midi\task_parse.cpp`) | 1 KB |
| 9 | `0x60000578` | initial task (`cmni\task_cmni_evt.cpp` area) | 1 KB |
| 10 | `0x60008F5C` | **sequencer** (`seq\task_seq.cpp`) | 1 KB |
| 11 | `0x6001F14C` | DSP (`dsp_firm\task_dsp.cpp`) | 2 KB |
| 12 | `0x600082A4` | MIDI assign (`midi\task_asgn.cpp`) | 1 KB |
| 13 | `0x6000ED8C` | parameters (`prm\task_prm.cpp`) | 1 KB |
| 14 | `0x6000151C` | controls (`control\task_ctrl.cpp`) | 1 KB |
| 15 | `0x60012928` | **panel** (`hmi\task_panel.cpp`) | 2 KB |
| 20 | `0x60011F68` | system (`sys\task_sys.cpp`) | 6 KB |

So **the sequencer task can preempt the panel task** at any point of a payload function that
runs in the panel task, and not the other way round (the panel runs only while the sequencer
waits). The sequencer's entry jumps into the `task_frame` event loop (`0x6001256E`); its event
handler `FUN_60008F6C` calls the clock tick `FUN_6000989C` at `0x600090D0`. [code]

**The clock tick also runs in the panel task.** The button handler `FUN_6001961E` (panel task)
calls `FUN_600099B6`, which calls `FUN_6000989C`, at `0x60019830` (START/STOP `0x1B` while
playing, with TAP (`0x2E`) held; section 9). `FUN_600099B6` is a restart on the fly: stop
(`FUN_6000969A`), MIDI Stop, start (`FUN_6000964E`), MIDI Start, then one tick. `FUN_6000D590` and
`FUN_6000D57C` around the start only post MIDI `0xFC`/`0xFA`: nothing in it stops the sequencer
task (priority 10) from preempting the panel (15). Everything the tick calls, the restart
`FUN_600095F0` included, can therefore run in either task. [code]

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
| 0x8C-0xC2 | 3 | Per instrument (BD SD LT MT HT RS HC CH OH CC RC): `_NUM`, `_PAN`, `_ACC`, `_GR`, `_SE` (kit; `_GR`/`_SE` = reverb/delay send, section "Effects") |
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
| 2 | 0x89-0x8B | Efx: effect types (section "Effects") | `0x60143F38`, 17 slots | `0x600556E4` |
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

**Pattern lock.** The pattern save `FUN_6001B7D8` first reads System id `0x27`
(`FUN_6001B432(db, 0x27, 0)`) and saves nothing (no area 4, no area 6) when it is not 0 [code].
`FUN_6004CC9C` sets it through `FUN_6001BCC2`: with PTN SELECT (button `0x12`) held, a knob turn
writes 1 to the right and 0 to the left (`0 < delta`); its first event only shows the current value
[code]. The knob is TEMPO [unit], and the airainfo.org TR-8 cheatsheet lists it as "Pattern Lock:
hold PTN SELECT, turn TEMPO to `LcK`". The texts are `Lock` and ` OFF` (`0x60015DFC`), and the PTN SELECT screen picks `Lock`
when the value is 1 [code]. On the unit, every step edit was lost on a pattern change with every
build, poly alone included; holding PTN SELECT and turning TEMPO to the left made saving work
again [unit, 2026-11-18, issue #2]. The PTN SELECT screen did not show `Lock` then, so the
condition of that display is not understood [unit]. A lock is kept across power off and
reflashes (System area), so a lost edit is first a reason to check it.

The chain patch redirects the area-4 half of that save (`0x6001B7F4`, inside `FUN_6001B7D8`)
while the current pattern has a side sequence, and keeps the area-6 half stock: area 4 slot *n+1*
keeps the pattern's own steps and the edited bar is appended to a 128-byte-entry log in the
unused flash at `0x3DB000`-`0x3DFFFF` (five blocks of 32 entries, entry *i* at
`0x3DB000 + i * 128`, scratch block at `0x3DA000`, newest entry per pattern/bar wins;
[CHAIN.md](CHAIN.md) "Storage"). A pattern with no side sequence keeps the stock commit.
Roland's update file erases that range (its trailer names blocks `0x30`-`0x3DF`, section 3), so
the bars are lost on a stock update, while the two side lengths survive in the user area. Files
written by `tr8patch.py` and the web flasher end the range at block `0x3D9`, so they keep it. The raw primitives used are `FUN_60003E54(off, len, src)` (program, chunks <=
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
The same object takes every word of the working copy: Ptn index *n* is word *n* of area 4
slot 0, so index 2 + *v* is the LAST of variation *v* (`FUN_6001B8D6` sets it that way) and
index 4 + 2*i* + *v* is the step mask of row *i* (the row table at `0x6007EC54` holds 4, 6, 8, ...).
The button handler `FUN_600193E0` (CLEAR + instrument) calls `FUN_600186FA` on it several times in a
row from the panel task [code]. The bar chain's expand writes steps and LAST through this setter,
so the pattern is marked changed and saved by the normal path ([CHAIN.md](CHAIN.md), "Expand and
copy A to B"); that use from the button dispatch works on the unit [unit].

HMI parameter databases (names at `0x6007EC0C`): System, Setup, Efx, Patch, Ptn, Patch2, Ptn2,
Testmode, TMP. Each has a getter `get(db, index, default)` that maps a local index to a global id:

| Database | Getter | Notes |
|---|---|---|
| Setup | `FUN_6001B12E` | index n = global `0x2A + n` (`hmi_prm_setup.cpp`). Object `0x60149F38`. |
| System | `FUN_6001B432` | index n = global id n (area 0, `hmi_prm_system.cpp`). Object `0x6007ED20`. |
| Efx | `FUN_6001BD2E` | index 0, 1, 2 = global `0x89`, `0x8A`, `0x8B` (`FUN_6001BD0A`, `hmi_prm_efx.cpp`). Object `0x6007ED28`. Setter `FUN_6001BD66`. |
| Ptn | `FUN_6001B736` | index 0 = `VARI`, 1 = `SCALE`, index -> id `0xC3 + index` (`FUN_6001B606`) |
| Ptn2 | `FUN_6001D3FA` | weak accent, flams |
| Patch / Patch2 | `FUN_6001A99A` / `FUN_6001AD68` | kit |

Setters: `FUN_6001B166` (Setup) and the generic `FUN_600186FA(obj, index, value, sub)`, which
asks the range (vtable +0x1C), clamps, reads the current value (+0x08) and writes only on change
(+0x18).

Known Setup indexes: 0 = panel mode (section 9), 6 = master volume, 9-0xC = scatter (section 8,
"Scatter"), 0x19 = held-step mask (section 7, "Step trigger"), 0x13 = tempo fine (-10..+10),
0x14 = shuffle (0..100), 0x15 = playing, toggled by START/STOP [code: the toggle sends MIDI Start `0xFA` or Stop `0xFC`].

### Effects

**Effect types.** Area 2 (Efx) holds three values, global ids `0x89`, `0x8A`, `0x8B` (Efx index 0,
1, 2). The range is -1..7, the default is 0 (parameter table `0x6005D3EC`). Factory bank 1
(`0x600556E4`): slot 0 = (0, 0, 0), slot *n*+1 = (*n* mod 8) for all three values. The pad LED
code (`FUN_60016386`, case 5) reads Efx index 0, 1, 2 when
Setup[7] is 1, 2, 3, and lights the pad of the current type. [code]

- Index 0 (`0x89`) = reverb, 1 (`0x8A`) = delay, 2 (`0x8B`) = side chain (External In) [code].
  Each id has a callback in the parameter-change table (`0x6007F250`, `0x6007F25C`,
  `0x6007F268`: `0x600210C8`, `FUN_600216E2`, `0x60021CD8`). After the type change, each callback
  re-sends the knob values of its effect from a list at `0x600690DC` (count, then ids):
  reverb `0x80`, `0x81`, `0x82` (CC 89, 90, 91); delay `0x83`, `0x84`, `0x85` (CC 17, 18, 16)
  and `0x3C` (tempo); side chain `0x87` (CC 13) and `0x3C`. The CC -> id map is the MIDI receive
  switch `FUN_60004966`. Only delay and side chain read the tempo, as the EFX Type List says
  (no reverb type is synced). The LED code agrees: Setup[7] = 1, 2, 3 (row buttons `0x1E`-`0x20`,
  RV EC SC) selects Efx index 0, 1, 2.
- The meaning of -1 is not known.
- Each value is the type 0..7, shown on pads 1..8 [hyp: consistent with the 8 types of each effect].

**Effects per pattern.** System id `0x16` (range 0..1, default 0) selects where the types are kept
[code]:

- 0: area 2 slot 0 is global. A pattern change does not touch it.
- 1: the pattern select `FUN_60005148` first commits area 2 slot 0 to slot *old*+1 and writes
  flash (`FUN_6001BDD0` -> `FUN_6000FC78`), then loads slot *new*+1 into slot 0 (`FUN_6001BE22`).
  `FUN_6001A068` (purpose not traced; it returns early when System id 7 is 0) also commits
  area 2 to slots 1, 2, 3, ... when System id `0x16` is 1.

Roland documents this option as the KIT button of the setup mode (hold PTN SELECT at power on,
light KIT, press START/STOP to save; Roland Australia, "The Ultimate Guide to the AIRA TR-8",
tip 10). That the KIT button writes System id `0x16` is [hyp].

**Sends per instrument.** Kit ids `<inst>_GR` (`0xAD`-`0xB7`) and `<inst>_SE` (`0xB8`-`0xC2`) have
the range 0..1, default 1 [code]. They are the reverb and delay send of each instrument [hyp:
from the names (`GRLV` = reverb level, `SELV` = delay level, section 8) and the manual: KIT + hold
the STEP button of REVERB or DELAY, then the 11 instrument buttons; all are on by default]. They
are kit data, so they change with the kit, not with the pattern.

**The 8 types of each effect** come from Roland's "TR-8 EFX Type List" (2014/3/11, Ver. 1.02).
The original URL (`roland.co.jp/.../63080412/TR-8_EfxParameter.pdf`) is gone; copies are in
L. Duffar's French guide (June 2018, chapter 4) and at `airainfo.org/files/tr-8_fx.pdf`. That
the pad number is the stored value + 1 is [hyp].

| Pad | Reverb (LEVEL / TIME / GATE) | Delay (LEVEL / TIME / FEEDBACK) | Side chain (LEVEL / DEPTH) |
|---|---|---|---|
| 1 | Non Attack | One Head Tape | Sin Curve: hold 16th, sin 8th |
| 2 | Room | Three Head Tape | Square Curve: hold 12th, sin 16th |
| 3 | 16 Note Pre Delay (16th at 128 BPM) | Digital Single Delay | Saw Squared Curve: hold 16th, saw² 8th |
| 4 | Plate and Filter (Manual): TIME = time + feedback, GATE = cutoff | Digital Pan Delay | Square Gate: hold 32nd, sin 32nd, gate |
| 5 | Plate and Filter (Auto): TIME = time + feedback, GATE = sweep time | Reverse Single Delay | Sin Very Short Curve: hold 128th, sin 64th |
| 6 | Spring | Reverse Pan Delay | Saw Squared Long Curve: hold 8th, saw² "6 note" |
| 7 | Non Attack and Metal | Stereo Flanger: LEVEL = dry/wet, TIME = rate, FEEDBACK = resonance | Square Short Gate: hold 64th, sin 64th, gate |
| 8 | High Pass | Bit Crusher: LEVEL = dry/wet, TIME = sample rate, FEEDBACK = filter cutoff | Up Down Curve: hold 16th, up-down 8th |

Tempo sync, from the same list: no reverb type; delay types 1-7 (TIME is a note value); all side
chain types. The list gives no value ranges and nothing on the scatter (section 8, "Scatter").

**Setup mode** (hold PTN SELECT at power on), from the manual and user guides, not traced in the
code [hyp]: TEMPO sets the MIDI channel (display `C10` by default); TAP + TEMPO to `OFF` stops the
demo; A or B + instrument buttons send an instrument to the ASSIGNABLE OUT A or B; KIT = effects
per pattern (above); START/STOP saves.

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
| byte +0x1D8, s16 +0x1DA, bytes +0x1DC | held-step order: length, index (-1 = off), step list (see below) |

`FUN_600262F2(P, step, flam)` plays one step. With step -1 it advances P[0x66] (if P[1]: +1, 0
after P[3]), then applies the held-step order. It then tests the single bit `1 << step` in every
mask and sends the hits to the sound engine. flam != 0 (explicit step, from the delay queue at
`0x60009A50`) also needs the flam mask. Returns bit i = instrument i fired. **[unit]**: hooking
the calls below and swapping mask bits changes what plays (POLY.md hardware test 1).
**Held-step order.** The bytes P+0x1C8..+0x1D7 (one per step) and the list at +0x1D8..+0x1EB come
from Setup index 0x19 (global `0x43`, a 16-bit step mask): its change callback (`0x60023758`, table
entry at `0x6007EF98`) calls `FUN_6002765C(P, mask)`, which keeps the held steps in ascending order
(`FUN_600275B4` inserts or removes one step; mask 0 sets the index to -1). Only the pad press and
release handlers `FUN_6004F570` / `FUN_6004F4EC` of one screen (vtable `0x6007C778`, factory
`FUN_600157A8`) write that mask; a mode button (0x11-0x16) or LAST STEP (0x1A) clears it [code].
That screen is **screen 17**: entry 17 of the screen table at `0x6006022C` (16-byte entries, word 0
= pointer to the factory pointer) points to `FUN_600157A8`, and `FUN_6001961E` requests screen
`0x11` (`FUN_60013972`) when button 0x13 is pressed with TR-REC (0x11) held, which also sets
Setup[0] = 8 [code]. Button 0x13 is INST PLAY [code: section 9, "Panel mode"]. So
**TR-REC + INST PLAY** opens a step-loop mode: while the pattern plays, holding pads makes the
sequencer loop over the held steps, in step order [unit: TR-REC + INST PLAY, hold pads 1 and 5,
only steps 1 and 5 play; the latch rule below is code only]. Rules in
`FUN_6004F570` (press) and `FUN_6004F4EC` (release):
- one pad held alone: the mask is that step only;
- a pad pressed while other pads are held adds its step;
- a released pad removes its step, unless a row button (0x1D-0x2A: AC RV EC SC and the
  instruments, `FUN_6004F6B4`) was held at the press: then the steps stay (latch);
- a mode button (0x11-0x16) or LAST STEP sets the mask to 0 (index -1: normal play).
The scatter callbacks (section 8, "Scatter") do not write it,
so +0x1DA is not a scatter field (`TR8_PL_HELD_IDX` in `tr8_v161.h`; an earlier name was
`TR8_PL_SCATTER`). The poly patch only needs "-1 = the firmware does not pick the step from the
list" ([POLY.md](POLY.md)).
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
only; the scatter controls are not in these 49 ids (see "Scatter" below).
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

### Scatter

The scatter state is in the Setup database (object `0x60149F38`) [code]:

| Setup index | Global id | Range | Meaning |
|---|---|---|---|
| 9 | `0x33` | 0..1 | ON |
| 10 | `0x34` | 0..1 | the dial edits the depth (1) or the type (0) [hyp: DEPTH mode] |
| 0xB | `0x35` | 0..9 | type (dial positions 1..10) |
| 0xC | `0x36` | 0..9 | depth |

System id `0x12` keeps a copy of the type: the dial handler writes it after each type change, and
`FUN_6004E31C` copies it back into Setup 0xB (power-on restore [hyp]).

**Inputs** [code]:

- **Dial**: rotary encoder 0. `FUN_60013FB0(0, delta)` adds the delta with `FUN_600185F0`
  (relative set, clamped to the range): to Setup 0xC when Setup 10 is 1, else to Setup 0xB (then
  System `0x12`). With LAST STEP (0x1A) held, the dial writes System `0x24` instead. The same
  function handles encoder 1 [hyp: TEMPO].
- **ON**: button `0x2D` (press, `FUN_6001961E`). With button `0x2C` held while playing, it sets
  the one-cycle flag (+0x18 of the handler object), as in the manual: DEPTH + ON stops the scatter
  at the end of the cycle [hyp: `0x2C` = DEPTH]. When System id `0x25` is 0 and the flag is clear,
  the press toggles Setup 9 (`FUN_6004D6F6` writes "value == 0"); otherwise it sets Setup 9 = 1
  [hyp: System `0x25` selects latch or momentary]. START/STOP that stops the sequencer clears the
  flag and Setup 9 when the flag is set.
- **MIDI** (`FUN_60004966`, receive): CC 68 -> Setup 0xB and System `0x12`, value
  `(v * 18 / 127 + 1) >> 1` (0..9); CC 69 -> Setup 0xC, same scaling; CC 70 -> Setup 9 = `v >= 64`.

**Effect.** The parameter-change callback table (12-byte entries `{global id, on change, second
callback}`, around `0x6007EE48`-`0x6007F730`) has, for the scatter ids, entries at `0x6007EF2C`
(`0x33`), `0x6007EF44` (`0x35`), `0x6007EF50` (`0x36`). They call, with the scatter object
**S = `0x6014A130`** [code]:

- `0x33` -> `FUN_6002A16E(S, ?, on, word +4 of the Setup object)`: S[2] = on, then it programs
  the engine (calls into the fast code through `thunk_EXT_FUN_0100746E`) for the current type.
- `0x35` -> `0x6002A1AA`: if value < 10, S[0xB] (+0x2C) = type, then `0x60029BFC`.
- `0x36` -> `0x6002A1B4`: if value < 10, S[0xC] (+0x30) = depth, then `0x60029BFC`.

**Type table**: 10 records of 0x124 bytes at `0x6006B548`, record *t* = dial position *t* + 1.
Word 0 is the algorithm, which selects one of 14 setup functions in `FUN_6002A16E` (0 =
`FUN_60028FD6`, 1 = `FUN_600297B4`, ..., 13 = `FUN_60029830`). Word 0 for the 10 types:
10, 10, 12, 13, 10, 10, 0, 0, 10, 11. Words 2 and 3 are a range that the depth (S[0xC]) scales
(500..5000 for most types, 500..3000 for type 3, 100..5000 for types 6-10) [code: the
interpolation follows the switch; what the range controls is not known]. The rest of each record
is not decoded.

S is 0x34 bytes below the player object P (`0x6014A164`, section 7); whether both are parts of one
sequencer object is not known.

## 9. Buttons and panel mode

### Button events

The HMI dispatcher handles button press as type 5 (sets the button bit, see below) and type 6
[hyp: release]. Panel FIFO events 1 and 2 go to `FUN_60013BC2` / `FUN_60013CE0`. The main button
handler is `FUN_6001961E(ctx, id)`:

| Id | Button / action | Confidence |
|---|---|---|
| 0x00-0x0F | Step buttons 1-16. In step mode they call `FUN_6001B8D6` (write through the Ptn database) | code |
| 0x11 | **TR-REC**. Sets Setup[0] = 0 | **unit** |
| 0x12-0x16 | Mode buttons: Setup[0] = 1..5 (section 9, "Panel mode"). 0x13 with TR-REC (0x11) held gives Setup[0] = 8 and the step-loop screen 17 (section 7, "Step trigger") | code |
| 0x17, 0x18 | Write `VARI` = 0/1/2 (variation A, B, A+B): in `FUN_6001961E`, A pressed while B is held (or B while A is held) writes 2. A/B LEDs in A+B (`FUN_600169A4`): in TR-REC (Setup[0] = 0, with Setup[8] = 1) they show the side being edited (lit) and the other one blinking, which only a press changes (B held + A selects A); while playing in another mode they follow the variation that the sequencer passes to the step callback (`FUN_60012C22` stores it at Setup object +8), so the side that plays is lit [code; unit: INST PLAY follows the playing side, TR-REC stays on the edit side] | code |
| 0x19 | Cycles `SCALE` 0..3 | code |
| 0x1B | **START/STOP**: toggles Setup[0x15] (playing) and sends MIDI Start `0xFA` / Stop `0xFC` (`FUN_60006A94`). While playing with TAP (`0x2E`) held, it restarts the pattern from step 1 without stopping (`FUN_600099B6`, from the panel task, section 5) | code; **unit** (TAP + START/STOP restarts, SCATTER ON + START/STOP stops) |
| 0x1A | **LAST STEP** (modifier). A step pad with it held calls `FUN_6001B8D6(obj, pad)` (`0x60019A10`), which sets `LAST_A`/`LAST_B` (Ptn index 2 + variation) | **unit** (POLY.md test 2) |
| 0x1C | **CLEAR** (modifier). With CLEAR held, an instrument button clears its row (`FUN_600193E0`); `FUN_600192BA` (clear a step) also needs it | **unit** |
| 0x1D-0x2B | Row buttons: 0x1D-0x20 = AC RV EC SC; 0x21-0x2B = instruments BD SD LT MT HT **HC RS** CH OH CC RC: RS and HC are swapped compared with the pattern/player order (POLY.md test 2) | **unit** (RS/HC), code (others) |
| 0x2E | **TAP** (modifier of START/STOP, see 0x1B) | **unit** |
| other ids above 0x2B | Not mapped (0x37 is used as a modifier somewhere) | - |

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
- Each mode button also requests a screen (`FUN_60013972`): 0x11 -> screen 5, 0x12 -> 6,
  0x13 -> 7, 0x14 -> 8, 0x15 -> 9, 0x16 -> 10; TR-REC + 0x13 -> screen 17 (mode 8, step loop).
- The step LED code `FUN_60016386` (switch on the mode) paints modes 2 and 3 the same way:
  pads 1-11 = instruments, 12-15 = the roll bits (Setup[0xE]), 16 = MUTE (Setup[0xD]). So
  2 = INST PLAY (button 0x13) [code; unit: TR-REC + INST PLAY opens the step loop]. Mode 5 shows the effect type on pads 1-8 for the RV, EC
  and SC rows (section 6, "Effects"), as the manual says for DRUM SELECT INST: 5 = INST
  (button 0x16) [code]. 1 = PTN SELECT (0x12) and 4 = KIT (0x15) [hyp: the remaining buttons;
  mode 1 shows pattern values Setup[2], [3]].
- `FUN_6004D21C`, `FUN_6004D7C0` and `FUN_6004D814` seem to set 6 and 7.

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
- **Button LEDs.** `FUN_60017722(id, a, b)` calls `FUN_6004BB4C(object, id, a, b, 0)`. The panel
  repaint `FUN_600169A4` (bit `0x02`) sets with it: LED `9` = LAST STEP, `(9, 1, 9)` when the
  pattern of the current variation is shorter than 16 steps, `(9, 0, 9)` at 16; while LAST STEP is
  held `(9, 3, 9)`, or `(9, 1, 9)` when Setup[3] = -1 (what `a = 3` looks like is not known). LEDs
  `6`/`7` are set next to it (variation A/B) [hyp], `8` and `0x42 + n` (n = 0..3, the scale) [hyp]. The
  last LED call of that repaint is a tail call (`b.w` at `0x60016B56`). `b = 0` blinks a pad
  (play colour `(1, 0, 2)`) [unit] and the LAST STEP button LED `(9, 1, 0)` [unit: the poly
  LAST STEP hook, [POLY.md](POLY.md) hardware test 5]. [code]
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
  737 + 1568 bytes, `poly` 691 + 120 bytes; `motion-poly` uses about 340 + 840 bytes, its zeroed
  data is in patch RAM (below). The bar chain used these regions in its earlier builds and no longer does.
- **Grow the image (used by the bar chain since the module build).** Code appended at the end of
  the image (`0x601309E0`) would be erased, because the bss zero-fill covers
  `0x601264EC`-`0x60280987`. Instead:
  1. extend the decompressed size so that the image reaches the new code. The bytes between
     `0x601309E0` and the code are zeros and compress well: reaching `0x60282EE4` costs about
     165 KB of compressed application (0xA5CF7 -> 0xCF305), and the module still ends at file
     offset 0xFF345, far below `appB` at 0x280000. `tr8patch.py` and the web flasher extend the
     application array themselves when a payload lies beyond the current end.
  2. put the new code and data at `0x60281200` (above the bss, so it is not zeroed). Not
     `0x60280988`: `motion-poly`'s patch RAM occupies `0x60280A00`-`0x60281183`, and the 64 KB
     below the moved pool is that reservation. The chain's `.text` is
     `0x60281200`-`0x602823F5` (4598 bytes) and its `.bss` (including the 2 KB playback cache)
     runs to `0x60282EE4`; the patcher reserves 8 KB, `0x60281200`-`0x60283200`.
  3. move the RTOS pool start by N: the literal `0x60280988` at `0x600104A8`
     (`FUN_60010430`) becomes `0x60290988`, the same move `motion-poly` makes. The other copy at
     `0x6012A2FC` is the startup stack top, not the pool (see the next item). The bss zero-fill
     has its own bounds, literals `0x601264EC` at `0x6000015C` and size `0x15A49C` at
     `0x60000160` (startup code `bl 0x6000009E` at `0x60000078`), so moving the pool start does
     **not** extend the zeroing over the new code.
  The boot loader decompresses any size into SDRAM: `FUN_01000B3C` reads the decompressed size
  from the header and `FUN_01000C76` is bounded only by `destination + size`, with no fixed cap.
  The updater only checks sizes and sums. Emulation passes (249 chain checks and the three
  combinations), and the `motion-poly-chain` build boots and works on a real TR-8. [unit]
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

1. Panel mode values 6 and 7; confirm 1 = PTN SELECT and 4 = KIT.
2. Where the step callback (+0x14) is installed.
3. Is the 16-step limit only in the application, or also in the sound engine (fast code, second
   processor)?
4. What runs on the second processor (`appB`) and over which link? It is the same chip as the
   main processor, a Roland ESC2 [unit]. The link is probably USB: host on the main processor,
   device on the second [hyp] (section 4, "Processor and peripherals").
9. ~~Which chip is the main processor?~~ Answered: two Roland ESC2 chips, read on the board
   (section 4, "Processor and peripherals"). [unit]
5. LED function arguments; display text lifetime and how to keep a message visible.
6. Button ids above 0x2B (START/STOP, PATTERN, ...). LAST STEP is 0x1A (section 9).
7. ~~The "grow the image" method (section 12) on a real unit.~~ Answered: the bar chain's
   `motion-poly-chain` build uses it and works on a real TR-8 ([CHAIN.md](CHAIN.md)). [unit]
8. MIDI: the receive path (`midi\task_midi_rx.cpp`) and whether external CCs take the same path
   as `FUN_60015906`.
10. Effects (section 6, "Effects"): what the value -1 means; whether the setup-mode KIT button writes System id `0x16`. Scatter: what
    the 0x124-byte type records hold.
