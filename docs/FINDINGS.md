# Findings: TR-8 firmware v1.61

## 1. Container (`TR8_UPD.BIN`, 4,194,320 bytes)

A 0x10-byte prefix, then a 4 MiB flash image. Offsets below are file offsets (flash offset + 0x10 in the prefix case is already included).

| Offset | Content |
|---|---|
| 0x0000 / 0x4000 | Boot image "ESC91.000", plaintext. Vector table at +0x30 (SP `0x01011718`, reset `0x01000BD9`). Code base `0x01000000`. Contains the LZSS decompressor (function at `0x01000C76`). |
| 0x8000 | `TR-8:Updater 12-0801` (compressed), 180 KB decompressed |
| 0x30000 | `TR-8:Appli 18-0926_11:19:43` = v1.61 main application (compressed), 1,243,616 bytes decompressed |
| 0x280000 | Second `TR-8:Appli` module, 1,074,732 bytes. Contains `BSSESC2` strings: probably the build for the ESC2 hardware revision (hypothesis). |
| 0x2F8010 - end | 0xFF fill |

Module header (0x40 bytes): name (0x28), load address `0x60000000`, header size, compressed size, **byte-sum32 of the compressed payload**, destination address, decompressed size.
All three checksums verified. Compression is Okumura LZSS: 4096-byte ring, initial position `0xFEE`, flag bit 1 = literal, match = 12-bit absolute ring position + 4-bit length (+3). The ring starts zeroed.

CPU: ARMv7-M class (Thumb-2, `msr basepri`). The application runs from RAM at `0x60000000`. RTOS calls (`thunk_EXT_FUN_01000xxx`, `...01007752`) go to a mask ROM at `0x01000000+` that is not in the image.

Integrity: only the module byte-sum was found. The boot code may check more (not analysed in depth). No signature or encryption seen.

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
| +0x18 | current step |
| +0x1C | last step |
| +0x20 | tick counter inside the step |
| +0x24, +0x2C | tick period and timing values (tempo derived, float math) |
| +0x28 | scale/clock mode (0x32 seen) |
| +0x30 | ticks per step |

- `FUN_6000989C(ctx)`: per-clock-tick handler. Increments `+0x20`; when it reaches `+0x30` it advances `+0x18`, wraps at `+0x1C` (`FUN_600095F0` resets), then `FUN_6000981E` calls the callback.
- `FUN_60009746`: builds the triggers for the step, then `FUN_6000DE34(ctx, mask, levels[11], accentMask)` fires the 11 voices through `FUN_60027120`..`FUN_60027384`. Voice functions end in `thunk_EXT_FUN_01007752` (float-converted parameter message to the sound engine in ROM).
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
4. **Panel FIFO.** The `task_panel` listener (`FUN_60012D94`, 0x400-byte `pdw_fifo`) queues the event. On pop, the callback `0x60014114` -> `0x6001406C` dispatches on the event byte. Event 0x0B goes to `FUN_60013DE0(id, value)`, which pushes the HMI event `{u16 0x0A, u16 id, s16 value}` into the HMI ring (`FUN_60013B94`, 256 x 12 bytes).
5. **Screen handler.** The active screen receives the event. The default knob handler `FUN_600141DE` calls `FUN_6001446A(ctx, id, value)` unless the screen overrides it (vtable +0x48, for example while an instrument button is held). `FUN_600143D4` blocks knobs in some panel modes (mode >= 4).
6. **Control to parameter.** `FUN_6001446A` maps the control id to an HMI parameter id (0x06 .. 0x5E), with a rescale for ids 45 (`*101/255`) and 46 (`*21/255 - 10`). It then calls `FUN_600186FA(DAT_60014668, param, value, 0)`.
7. **Parameter set.** `FUN_600186FA(obj, id, value, sub)` is the generic setter of the HMI parameter manager (object at `0x60149F38`): it asks the range (vtable +0x1C), clamps, reads the current value (+0x08) and writes only on change (+0x18). The same setter is used elsewhere, for example the tempo (`FUN_600089E6`: ids 0x12 and 10).

Names of the controls (short-name table at `0x6007D698`): `<inst>TU` (tune), `<inst>DC` (decay), `BDAT` (BD attack), `BDCO`/`SDCO` (comp), `SDSN` (snappy), `SHFL`, `FINE`, `VOLM`, `SETM`, `GRTM`, `GRGT`, `SEFB`, `EXSC`, and the level names `ACLV`, `SELV`, `GRLV`, `EXLV`. The exact control id -> name pairing is not mapped yet.

HMI parameter databases (names at `0x6007EC0C`): System, Setup, Efx, Patch, Ptn, Patch2, Ptn2, Testmode, TMP.

Dead code: `FUN_6012B12C` and its twin at `0x6012B054` (a second ADC filter in the BIOS area) have no caller.

## 3. Open questions

1. What does the parameter set (vtable +0x18 of the object at `0x60149F38`) do after storing the value: which task gets the notification, and how fast does it reach the sound engine?
2. Where is the step callback (`+0x14`) installed?
3. Exact mapping of control id -> HMI parameter id -> knob name (`FUN_6001446A` gives the second half).
4. Is the sequencer limited to 16 steps in the sound engine (ROM or DSP side), or only in the main application?
5. What other integrity checks does the boot/updater perform?
