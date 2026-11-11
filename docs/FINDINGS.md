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

### Knob input (partly traced)

- ADC driver `driver\ad_drv2.c`: 8 multiplexers x 8 channels, 4-sample median-of-middle filter. Init at `0x60001AD4`.
- Knob table at `0x60054718`: 13 entries x 4 bytes (`[1]` = ADC index, `[2:4]` = scaling parameter).
- `FUN_6012B12C` (and an undeclared twin at `0x6012B054`) convert a raw ADC value to 10 bits with a 7..0x3F8 dead zone, then smooth over 8 samples. **No caller found** in the image: it may be dead BIOS code. The real knob consumer is still unknown.

## 3. Open questions

1. Who reads the knobs in normal operation, and where does a knob value become a sound-engine message (look at the `FUN_600271xx`-`FUN_600273xx` voice functions and their callers)?
2. Where is the step callback (`+0x14`) installed?
3. What exactly do `_GR` and `_SE` mean, and which parameters are the Tune/Decay knobs?
4. Is the sequencer limited to 16 steps in the sound engine (ROM or DSP side), or only in the main application?
5. What other integrity checks does the boot/updater perform?
