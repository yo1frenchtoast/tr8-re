# Findings: TR-8 firmware v1.61

## 1. Container (`TR8_UPD.BIN`, 4,194,320 bytes)

A raw 4 MiB flash image (file offset = flash offset, flash mapped at `0x03000000`), followed by a 16-byte trailer.

| Flash offset | Content |
|---|---|
| 0x0000 | Boot loader "ESC91.000" (0x33AC bytes), plaintext. Vector table at +0x30 (SP `0x01011718`, reset `0x01000BD9`), runs at `0x01000000`. Contains the LZSS decompressor (`0x01000C76`). |
| 0x4000 | Second "ESC91.000" image (0x103C bytes), plaintext. Not analysed. |
| 0x8000 | `TR-8:Updater 12-0801` (compressed), 180 KB decompressed |
| 0x30000 | `TR-8:Appli 18-0926_11:19:43` = v1.61 main application (compressed), 1,243,616 bytes decompressed |
| 0x280000 | Second `TR-8:Appli` module, 1,074,732 bytes: firmware of a **second processor** (see boot flow). Contains `BSSESC2` strings. |
| 0x2F8000 - end | 0xFF fill |
| trailer | `{0x30, 0x3DF, 0x1000, 0x400000}` = first block, last block, block size, image size |

Module header (0x40 bytes): name (0x28), load address `0x60000000`, header size, compressed size, **byte-sum32 of the compressed payload**, destination address, decompressed size.
Compression is Okumura LZSS: 4096-byte ring, initial position `0xFEE`, flag bit 1 = literal, match = 12-bit absolute ring position + 4-bit length (+3). The ring starts zeroed.

CPU: ARMv7-M class (Thumb-2, `msr basepri`).

## 1b. Boot loader (flash 0x0, runs at 0x01000000)

Main flow at `0x01000B7A`:

1. `FUN_0100038E` picks the image to start from a table at `0x01010090` (initial data at boot.bin 0x3318):
   - entry 0: no condition, image `0x03030000` (application);
   - entry 1: ADC conditions = none, GPIO conditions at `0x01010008` = input 12 must read 1 and inputs 0-11, 13-15 must read 0, image `0x03008000` (updater).
   So holding one specific panel button at power-on starts the updater. Roland's procedure holds step button [1] (see [UPDATE.md](UPDATE.md)), so GPIO input 12 is probably step [1].
2. If the application was chosen, it first loads the module at `0x03280000` into RAM and sends it to the second processor (`FUN_01002374`: 0x40-byte header, then 0x200-byte chunks, handshake byte 0x10; on a bad handshake the boot loader stops in a loop).
3. It loads the chosen module (`FUN_01000B3C`: LZSS decompress if the decompressed size is not 0, else a plain copy) to `0x60000000` and jumps to it.

**The boot loader checks no checksum or signature.** It only reads the header sizes.

## 1c. Updater (flash 0x8000)

`FUN_600053C0` (`writer\force_updater.cpp`) looks on USB storage for `TR8_ROM.BIN`, then `BSSESC2.BIN`, then `TR8_UPD.BIN`. For `TR8_UPD.BIN`:

1. Trailer check (`FUN_6000530A`): file size - 16 = trailer image size, last block >= first block, block size not 0. File size >= (last+1) x block size.
2. Name check (`FUN_60005078`): the first 16 bytes at file offsets 0x8000, 0x30000, 0x280000 must be `"TR-8:Updater    "`, `"TR-8:Appli      "`, `"TR-8:Appli      "`.
3. Write (`FUN_60005152`): blocks first..last (flash 0x30000-0x3DFFFF in v1.61), each block read back and compared.
4. After the write (`FUN_60004F3E`): it re-reads the three modules from flash and recomputes each byte-sum against header +0x34. A mismatch gives error 6. The sums are shown on the display.

Consequence: a `TR8_UPD.BIN` with the original trailer **never rewrites the boot loader (0x0) or the updater (0x8000)**. If a modified application does not start, the button-at-power-on path still reaches the untouched updater, which can flash the original file again.

## 1d. Application memory map (scatter table at `0x60000000`)

| Region | Content |
|---|---|
| `0x60000000`-`0x601264EB` | Code and constants (run in SDRAM) |
| `0x601264EC`-`0x6013085F` (load) -> `0x01000300`-`0x0100A673` (run) | "Fast" code copied to internal RAM: RTOS kernel and drivers. All `thunk_EXT_FUN_0100xxxx` calls go here. An address `0x0100xxxx` in this range = image address `xxxx - 0x300 + 0x601264EC`. |
| `0x01010000`-`0x01015273` | Internal RAM data + bss |
| `0x01020000`-`0x01027FFF` | Internal RAM, zeroed (stacks, probably) |
| `0x20000000`-`0x2000624F` | Tightly coupled RAM data + bss |
| `0x601264EC`-`0x60280987` | Main bss (1.4 MB, zeroed after the fast-code copy) |
| `0x60280988`-`0x61FFFFFF` | RTOS memory pool (`FUN_60010430`, about 29.5 MB). SDRAM is 32 MB. |

MPU (`FUN_60010574`): SDRAM `0x60000000` is read/write/execute, so patched code and its data can both live in the image or the pool. Internal RAM `0x01000000`-`0x0101FFFF` is read-only except its data regions (the fast code cannot be patched at run time).

Reference image: the decompressed v1.61 application has SHA-256 `3685edab8bbeaef8752df9ef08a73a9fd2a2e69ba8210016132f6d141f6b452e` (checked by `tr8patch.py`).

Free internal RAM (hypothesis): `0x0100A674`-`0x0100FFFF` (about 22 KB) is not covered by the scatter table.

Ghidra note: the ELF built by `tr8fw.py` maps only `0x60000000`. To follow `thunk_EXT_*` calls, add a second memory block at `0x01000300` from image offset `0x1264EC` (length `0xA374`).

## 2. Application structure

C++ task-based firmware. Source paths from assert strings: `seq\task_seq.cpp`, `midi\{task_parse,task_asgn,task_midi_rx,midi_drv,midi_tx}.cpp`, `prm_mgr\*`, `storage\sf_bios.cpp`, `hmi\parameter\hmi_prm_{patch,patch2,setup,system,ptn,ptn2,efx,testmode}.cpp`, `dsp_firm\*`, `driver\{ad_drv2,led_drv,esc2_dsp_drv}.*`.

### Parameters and storage

Parameter descriptors are 0x1C-byte records at `0x6005EF4E` (148 entries): `[0]=0, [1]=kind, [2:4]=id, [4:]=ASCII name`.

| Ids | Kind | Names |
|---|---|---|
| 0x8C-0xC2 | 3 | Per instrument (BD SD LT MT HT RS HC CH OH CC RC): `_NUM`, `_PAN`, `_ACC`, `_GR`, `_SE` (kit "patch" params) |
| 0xC3-0xFA | 4 | `VARI`, `SCALE`, `LAST_A`, `LAST_B`, then `STEP_<row>1/2` for 26 rows (AC RV EC SC + 11 instruments + 11 `ACC_<inst>`), each a 16-bit step mask. 1 and 2 = variation A and B |
| 0xFB-0x105 | 5 | `<inst>_LEV` (11) |
| 0x129-0x14E | 6 | `WEAK_ACC1/2`, `FLAM_<inst>1/2` |

A pattern therefore stores 16-bit step masks only. There is **no per-step parameter data** in a pattern.
Storage: `TR8_PTN` = 16 slots x 0x50 bytes, `TR8_KIT` = 16 slots x 0x42 bytes, inside a 128 KB user area (`TR8_USERAREA.BIN`, backup/restore code at `0x60011DBE` / `0x60011E2E`). `FUN_600113B2` dumps the factory patterns as C text (`data_fact_ptn.inc`).
Parameter access: `FUN_6000F80E(ctx, area, n)` + `FUN_6000F844(ctx, id, &out)` read a value. Change notification handlers (`FUN_6000A15A`..`FUN_6000AFDC`) copy values into the sequencer struct at `0x6012FA64`.

### Sequencer engine (located)

State struct at `0x6007E100` (all in RAM, zero at load):

| Offset | Meaning (inferred) |
|---|---|
| +0x02 / +0x03 / +0x04 | running / started / paused flags |
| +0x14 | **step callback** function pointer, called as `cb(step, variation)` |
| +0x18 | step counter in **half steps** (the step function runs on even values; with scale `0x32` on odd values too, through `FUN_600097DA`) |
| +0x1C | last step |
| +0x20 | tick counter inside the step |
| +0x24, +0x2C | tick period and timing values (tempo derived, float math) |
| +0x28 | scale/clock mode (0x32 seen) |
| +0x30 | ticks per step |

- `FUN_6000989C(ctx)`: per-clock-tick handler. Increments `+0x20`; when it reaches `+0x30` it advances `+0x18`, wraps at `+0x1C` (`FUN_600095F0` resets), then `FUN_6000981E` calls the callback.
- `FUN_60009746`: builds the triggers for the step, then `FUN_6000DE34(ctx, mask, levels[11], accentMask)` fires the 11 voices through `FUN_60027120`..`FUN_60027384`. Voice functions end in `thunk_EXT_FUN_01007752` (float-converted parameter message to the sound engine in ROM).
- `FUN_6000981E` and `FUN_600097DA` (other scale path) both call `FUN_6000978E(p, step)`. `FUN_6000981E` also calls `FUN_600097DA` first when `+0x04` is 0, so the call usually runs twice per step, at `0x60009862` and `0x60009808`. These two calls are the motion patch step hooks.
- Pattern struct at `0x6012FA64`: `+0x10` = current variation (0 = A, other = B), read at `0x6012FA74`.
- `FUN_60009AF8`: 32-slot x 0x14-byte delay queue (scheduled triggers, used for flam/shuffle latency).
- Callback pointer assignment (`+0x14`) not found yet (set at runtime through a path I did not trace).

### Knob input (traced end to end)

Chain from the ADC to the parameter database:

1. **ADC scan.** `driver\ad_drv2.c` scans 8 mux x 8 channels. The ADC completion callbacks (`0x6000152C`, `0x60001534`, registered by `FUN_60001556` in `task_ctrl`) only set event flags 4/8 on `task_ctrl`.
2. **Control table.** On flag 4, `task_ctrl` runs `0x60000D2A`. It walks 49 controls described at `0x600544D0` (8 bytes each: `type, index`) and calls `handler[type](index)` from `0x60054658`:
   - type 0 at `0x60000F72`: 36 knobs (raw value from `FUN_6004B8B8`, per-knob table at `0x60054688`: control id + change threshold).
   - type 1 at `0x60001076`: 11 faders/level controls (table at `0x60054718`).
   - type 2 at `FUN_60001242`: 2 controls with a non-linear curve (ids 45, 46).
   - Control ids are 0..48. Knob ids skip 12, 17, 20, 23 ... 44 (those are the type 1 controls).
3. **Change event.** When a value moves past its threshold, the handler calls the shared callback `0x60000CC0(id, value)` (registered by `FUN_60000D06`). It builds the event `{u8 0x0B, u8 id, u16 value}` and posts it with `FUN_60001A2E` to the listener list at `0x6007DC28`.
4. **Panel FIFO.** The `task_panel` listener (`FUN_60012D94`, 0x400-byte `pdw_fifo`) queues the event. The push (`FUN_60001930` / `FUN_600017E4`) runs inside a critical section (`0x6004B87C` enter, `0x6004B886` leave), so another task (the sequencer) can post the same event safely. On pop, the callback `0x60014114` -> `0x6001406C` dispatches on the event byte. Event 0x0B goes to `FUN_60013DE0(id, value)`, which pushes the HMI event `{u16 0x0A, u16 id, s16 value}` into the HMI ring (`FUN_60013B94`, 256 x 12 bytes).
5. **HMI event 10 handler** (`0x60013892`, case 10 of the HMI dispatcher `FUN_60013C3E`). It returns at once if `FUN_6001A27C(DAT_60013950)` reports a modal state. It stores the value in a per-control table (`0x60148924 + 0x28 + id*8`), then calls `FUN_60013242(screen id, event)` (`bl` at `0x600138C8`) to let the active screen handle it. If the screen returns 0, it tail-calls **`FUN_60013F6A(id, value)`, the global control -> HMI parameter table** (same rescale for ids 45/46), which calls `FUN_600186FA`. This is the normal path in play.
   **Screen handler.** The active screen receives the event. Screen manager state is at `0x6007E510` (`+0x06` and `+0x2E` = screen ids compared by `FUN_60013242`, which calls the active screen's handler).
   **Knob redirect:** byte `0x6007E580`, read by `FUN_6001465C(DAT_600143C4)`. Not 0 while a button changes what the knobs do (for example an instrument button held); the knob event then goes to the screen override, not to `FUN_6001446A`. In the screens that use the base class handler, `FUN_600141DE` calls `FUN_6001446A(ctx, id, value)` unless the screen overrides it (vtable +0x48, for example while an instrument button is held). `FUN_600143D4` blocks knobs in some panel modes (mode >= 4).
6. **Control to parameter.** `FUN_6001446A` maps the control id to an HMI parameter id (0x06 .. 0x5E), with a rescale for ids 45 (`*101/255`) and 46 (`*21/255 - 10`). It then calls `FUN_600186FA(DAT_60014668, param, value, 0)`.
7. **Parameter set.** `FUN_600186FA(obj, id, value, sub)` is the generic setter of the HMI parameter manager (object at `0x60149F38`): it asks the range (vtable +0x1C), clamps, reads the current value (+0x08) and writes only on change (+0x18). The same setter is used elsewhere, for example the tempo (`FUN_600089E6`: ids 0x12 and 10).

Names of the controls (short-name table at `0x6007D698`): `<inst>TU` (tune), `<inst>DC` (decay), `BDAT` (BD attack), `BDCO`/`SDCO` (comp), `SDSN` (snappy), `SHFL`, `FINE`, `VOLM`, `SETM`, `GRTM`, `GRGT`, `SEFB`, `EXSC`, and the level names `ACLV`, `SELV`, `GRLV`, `EXLV`. The exact control id -> name pairing is not mapped yet.

HMI parameter databases (names at `0x6007EC0C`): System, Setup, Efx, Patch, Ptn, Patch2, Ptn2, Testmode, TMP.
Each database has a getter that maps a local index to a global parameter id and reads it with `FUN_6000F80E`/`FUN_6000F844`. Examples: Setup `FUN_6001B12E` (index n -> global `0x2A + n`, `hmi_prm_setup.cpp`), System `FUN_6001B432`, Ptn `FUN_6001B736`, Ptn2 `FUN_6001D3FA`, Patch `FUN_6001A99A`, Patch2 `FUN_6001AD68`. The matching setters are `FUN_6001B166` (Setup) and the generic `FUN_600186FA`.

### Panel buttons

Panel button events have types 1 and 2, dispatched by `0x6001406C` to `FUN_60013BC2` and `FUN_60013CE0` (hypothesis: press and release). The main button handler `FUN_6001961E` uses these button ids:

| Id | Action | Confidence |
|---|---|---|
| 0x00-0x0F | Step buttons 1-16; in step mode they call `FUN_6001B8D6`, which writes through the Ptn database | Code |
| 0x11-0x16 | Mode buttons: write Setup[0] = 0..5 (see Panel mode) | Code |
| 0x17, 0x18 | Write Ptn parameter 0 (`VARI`) = 0/1/2: variation A, B, A+B | Hypothesis from the values |
| 0x19 | Cycles Ptn parameter 1 (`SCALE`) 0..3 | Code |
| 0x1B | Toggles Setup 0x15 and may call the sequencer (`FUN_600099B6`) | Role unclear |

Ids above 0x1B are not mapped yet.

**Button held state:** `FUN_60013168(id)` returns 1 while button `id` is held. It reads a bitmap at `0x6014893C` (`0x60148924 + 0x18`, one bit per button id). Case 5 of the HMI dispatcher `FUN_60013C3E` sets the bit on press; case 6 probably clears it on release (not checked). The firmware uses it for combinations, for example `FUN_60013168(0x11)` in `FUN_6001961E` (button 0x13 with button 0x11 held gives mode 8). Confirmed on the unit (motion test 5): 0x11 is the **TR-REC** button and `FUN_60013168(0x11)` is 1 while it is held.

### Panel mode (TR-REC, INST REC)

The sequencer mode chosen with the mode buttons is **HMI Setup parameter 0** (object `0x60149F38`, global id `0x2A`). Read it with `FUN_6001B12E(0x60149F38, 0)`.

- `FUN_6001961E` (panel button handler) sets it: button 0x11 -> 0, 0x12 -> 1, 0x13 -> 2 (or 8 when the function `FUN_60013168(0x11)` is on), 0x14 -> 3, 0x15 -> 4, 0x16 -> 5. Buttons 0x00-0x0F are the 16 step buttons.
- `FUN_600192BA` (clear a step bit in `STEP_*`/`ACC_*`) returns unless the mode is 0 or 3.
- `FUN_60004D8C` (incoming note/trigger) writes the note into the pattern (`FUN_6001912C`) only in mode 3.
- `FUN_6000FF28` and `prm_storage_sub.cpp` code also read `0x2A` and `0x2B` (role there not analysed).

Conclusion: **0 = TR-REC** (step edit), **3 = INST REC** (real-time record). Modes 1, 2, 4, 5 and 8 are not identified (one of them is INST PLAY, one is probably PATTERN SELECT). `FUN_6004D21C`, `FUN_6004D7C0` and `FUN_6004D814` seem to set 6 and 7 (the decompiler output is unclear there).

Do not confuse with `0x6007E574`: that is the panel **boot mode**, written once at panel task start (setter `0x60014026`, called from `0x60012B46`). `FUN_600143D4` blocks knobs when it is above 3.

Correction: `FUN_6012B12C` and `0x6012B054` are not dead. They are in the fast-code region and run from `0x0100xxxx`, so their callers are in that alias.

## 3. Open questions

1. What does the parameter set (vtable +0x18 of the object at `0x60149F38`) do after storing the value: which task gets the notification, and how fast does it reach the sound engine?
2. Where is the step callback (`+0x14`) installed?
3. Exact mapping of control id -> HMI parameter id -> knob name (`FUN_6001446A` gives the second half).
4. Is the sequencer limited to 16 steps in the sound engine (ROM or DSP side), or only in the main application?
5. Panel mode values 1, 2, 4, 5, 6, 7, 8 (only 0 = TR-REC and 3 = INST REC are identified).
6. What runs on the second processor (`appB`) and over which link?

Answered: integrity checks (1b, 1c); updater button (step [1], from Roland's procedure, 1b); TR-REC flag (2, "Panel mode").
