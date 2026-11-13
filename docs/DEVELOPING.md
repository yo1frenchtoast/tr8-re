# Writing your own TR-8 firmware feature

This guide shows how to add a feature to the TR-8 v1.61 firmware with the tools in this
repository. The motion recording patch (`patches/motion/`) is the worked example: read it next
to this guide. All firmware facts are in [FINDINGS.md](FINDINGS.md).

**Risk.** You flash your own code into an instrument. The boot loader and the updater are never
rewritten by an update, so a unit that does not start can be recovered with step [1] at
power-on ([UPDATE.md](UPDATE.md)). A power cut during the flash is the one case this does not
cover. Back up your patterns and kits first.

## 1. Tools

| Tool | For | Needed by |
|---|---|---|
| Python 3 | `tools/tr8fw.py`, `tools/tr8patch.py` | everyone |
| clang + ld.lld (LLVM, any recent version) | compile payloads for `thumbv7m` | patch authors |
| unicorn (`pip install -r requirements-dev.txt`) | emulation tests | patch authors |
| Ghidra (headless) | decompile the application (`tools/analyze.sh`) | research |
| llvm-objdump | disassembly: `llvm-objdump -d --triple=thumbv7m work/appA.elf` | research |

Get the original `tr8_sys_v161.zip` from Roland. Nothing from Roland is in this repository, and
nothing derived from it may be committed: `firmware/`, `work/` and `analysis/` are git-ignored.

```sh
mkdir -p firmware && unzip tr8_sys_v161.zip -d firmware
F=firmware/tr8_sys_v161/TR8_UPD.BIN
python3 -I tools/tr8fw.py info "$F"                 # modules, sums, trailer
python3 -I tools/tr8fw.py extract "$F" work         # work/appA.bin (+ .elf), boot, updater, appB
GHIDRA_HOME=/path/to/ghidra tools/analyze.sh work/appA.elf analysis/appA   # analysis/appA.c, .strings
llvm-objdump -d --triple=thumbv7m work/appA.elf > work/appA.dis
tests/run_all.sh "$F"                               # build every patch and run all tests
```

`analysis/appA.c` has every function as `//==== FUN_<addr> @ <addr>`; `analysis/appA.strings`
has each string with the functions that use it. Assert strings carry the original source file
names, which is the quickest way to find a subsystem.

## 2. How a patch works

```
original TR8_UPD.BIN ──► tr8patch.py ──► patched TR8_UPD.BIN ──► Roland updater (step [1])
                           │  1. check: trailer, module sums, SHA-256 of the application
                           │  2. replace a few 4-byte instructions ("sites")
                           │  3. copy the payload sections into free regions
                           │  4. recompress the application, fix size and byte-sum
                           └─ 5. re-check the output
```

A patch has three parts:

1. **Payload**: C code compiled for Cortex-M3 Thumb, linked at fixed addresses inside free
   regions of the application (`patches/<name>/link.ld`). `elf2payload.py` turns the linked ELF
   into `payload.json` (sections + the symbols the sites need). Users only need the JSON.
2. **Sites**: 4-byte instructions in the application that the patcher replaces, each with its
   original bytes (checked before writing). Usually a `bl` to a firmware function becomes a
   `bl` to your function, which then calls the original function itself.
3. **An entry in `PATCHES`** in `tools/tr8patch.py`: payload path, allowed regions, protected
   ranges, sites.

### The `bl` detour

The safest hook replaces a `bl FUN_x` with `bl my_function`. Your function receives the same
registers (r0-r3), so give it the same C signature as `FUN_x`, do your work, call `FUN_x`, and
return its result. The caller does not see a difference.

```c
#include "tr8_v161.h"

/* replaces "bl FUN_60013242" at 0x600138C8: every control event, before the firmware */
int my_knob(int screen, const int16_t *ev)        /* ev = {10, control id, value 0..255} */
{
    /* ... look at ev[1], ev[2] ... */
    return TR8_FN_SCREEN_EVENT(screen, ev);        /* the original call; return 1 to swallow */
}
```

```python
# tools/tr8patch.py
(0x600138C8, thumb_bl(0x600138C8, 0x60013242), "my_knob"),
```

Find a site in `work/appA.dis`; `thumb_bl(src, dst)` gives the bytes of `bl dst` at `src`, so the
patcher can verify them. Prefer sites where the firmware calls a function on the path you need
(event handlers, per-step functions) over patching inside a function body.

A call at the end of a function is often a tail call: `pop.w {..., lr}` then `b.w target`. Hook
it with a `b.w` of your own, never a `bl`, which would overwrite the restored `lr` and lose the
way back. The replacement `"b:my_fn"` writes `b.w my_fn`, and `thumb_bl(src, dst, link=False)`
gives the original bytes; `my_fn` then returns to the caller of the hooked function. Example: the
LAST STEP LED hook at `0x60016B56` (`patches/poly`, [POLY.md](POLY.md)).

### Compiling

`patches/motion/build.sh` is the template:

```sh
clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -Os -ffreestanding -fno-builtin \
      -fno-common -ffunction-sections -fdata-sections -nostdlib -Wall -Wextra -I../include \
      -c my.c -o my.o
ld.lld -T link.ld --gc-sections -e my_entry -u my_other_entry my.o -o my.elf
python3 -I ../../tools/elf2payload.py my.elf my_entry my_other_entry > payload.json
```

Rules for payload code:

- No C library. Clang can still turn a large copy or zeroing loop into a `memset`/`memcpy`
  call; the link then fails with an undefined symbol. Write simpler loops or provide the function.
- Initialized globals (`.data`) and zeroed globals (`.bss`) work: the patcher writes their
  initial bytes into the image, and the application is reloaded from flash at every boot.
- Keep large tables in a separate section (the motion patch uses `.cave_b`) and place it in the
  linker script.
- Call firmware functions through pointers with the Thumb bit set (`(fn)0x60013243`).
  `patches/include/tr8_v161.h` defines the known ones.
- After a change, compare the listing (`llvm-objdump -d --triple=thumbv7m my.elf`) and check the
  sizes the patcher prints against the free regions.

### Code space

The developer dump cave holds 788 + 1838 bytes. The motion patch alone uses most of it; the
`motion-poly` patch moves all zeroed data to 64 KB of patch RAM taken from the RTOS pool
([COMBO.md](COMBO.md)) and leaves about 1.5 KB of code space. A single patch can make the same
move when its state does not fit: that is how the earlier eight-bar chain kept its 128-byte bar
index.

The **grow the image** method is now used by the chain and is the way to give a new feature its
own space without taking the cave from the others ([FINDINGS.md](FINDINGS.md) section 12):

1. Link the payload at `0x60281200`, above the firmware bss (`0x601264EC`-`0x60280987`, which the
   startup code zeroes) and above `motion-poly`'s patch RAM (`0x60280A00`-`0x60281183`). The link
   script is a single region, `patches/chain/link.ld`.
2. List the region in the patch spec's `allowed` bounds. `tr8patch.py` and the web flasher extend
   the application byte array with zeros when a payload lies beyond the current image end, then
   recompress it with the larger decompressed size. The boot loader decompresses any size up to
   its destination, so no loader change is needed.
3. Move the RTOS pool start literal (`0x600104A8`, `0x60280988` -> `0x60290988`) so the pool
   never covers the region. The existing startup zero-fill does not reach it.
4. Keep `.bss` in the region: the image is reloaded from flash at every boot, so it arrives
   zeroed. No `ram_init` hook is needed. A patch that needs RAM outside the image can still use
   patch RAM ([COMBO.md](COMBO.md)).

To combine such a patch with a cave patch, give each variant its own payload JSON that is the
union of the parts (`tools/merge_payloads.py`) and make its site list the union of the parts'
sites (`tools/tr8patch.py` `_merge_sites`; identical duplicates such as the pool literal are
allowed, conflicting ones are an error). Rebuild the parts first: the merged file is generated
from their payload JSONs.

Data that must survive power off can go in unused pattern parameters, as the poly patch does
([POLY.md](POLY.md) "Storage"). A feature that needs neither method can use a new free region
(find dead code, replace its call sites with `nop.w`, keep its literal pools). Patches that use
the same region or disagree about a site cannot be combined.

The image-growth path works on a unit: the bar chain uses it, alone and combined with motion and
poly ([CHAIN.md](CHAIN.md) "Hardware check for the image build").

## 3. Firmware API

`patches/include/tr8_v161.h` lists every address with a confidence tag. The most useful:

| Need | Use | Notes |
|---|---|---|
| Is the sequencer playing? | `TR8_SEQ_RUNNING` | byte, 1 while playing [unit] |
| Current step | `TR8_SEQ_COUNTER >> 1` | the counter counts half steps [unit] |
| Variation A/B | `TR8_SEQ_VARIATION` | 0 = A [unit] |
| Run code once per step | detour `bl FUN_6000978E` at `0x60009862` and `0x60009808` | runs twice per step: dedupe on the step number [unit] |
| See every control move | detour `bl FUN_60013242` at `0x600138C8` | before the screen and the global table [unit] |
| Move a control from code | `TR8_POST_CTRL(id, value)` | same event as the hardware; safe from the sequencer task [unit] |
| Is a button held? | `TR8_BTN_HELD(id)` | TR-REC 0x11, CLEAR 0x1C [unit] |
| Read the panel mode | `TR8_SETUP_GET(TR8_HMI_SETUP, 0, 0)` | 0 = TR-REC, 3 = INST REC |
| Set a sound parameter directly | `TR8_SEND_CC(0, cc, value)` | internal MIDI CC (FINDINGS section 10) |
| Read pattern data | `TR8_PTN_GET(obj, index, 0)` | step masks (FINDINGS section 6) |
| Show text | `TR8_DISPLAY_TEXT(0, "Hi ")` | the screen overwrites it later |

Control ids and names: [FINDINGS.md](FINDINGS.md) section 8. Buttons: section 9.

### Task context

The firmware is multi-task. The sequencer clock code (`FUN_6000989C` and the per-step functions)
must stay short and should not change HMI state directly. To act on the panel side from the
sequencer, post an event (`TR8_POST_CTRL`): the panel FIFO push is inside a critical section and
the panel task applies it with the normal code. The motion patch does exactly this.

**Know the task of every hook.** A patch with two or more hooks often has hooks in different
tasks, and then any state they share is shared between tasks. Before you write a hook, find which
task runs its site, and write it down in the patch document (a table: hook, site, task, tag).

| Site | Task | Tag |
|---|---|---|
| Per-step code, `bl FUN_6000978E` at `0x60009862` / `0x60009808` | sequencer | [unit] |
| Clock tick `FUN_6000989C` and everything it calls (`FUN_600095F0` on a wrap) | sequencer, and panel through `FUN_600099B6` (button 0x1B, FINDINGS section 5) | [code] |
| Control event, `bl FUN_60013242` at `0x600138C8` | panel | [unit] |
| HMI dispatcher, screens, button press/release | panel | [code] |

A function with more than one caller can run in more than one task: `FUN_600095F0` runs on a
wrap (sequencer) and on a start; check every caller before you assume one task.
`python3 -I tools/callgraph.py up 0x600095F0` prints the caller tree from your local disassembly,
and `refs` finds a function that is only reached through a pointer (a task table, a vtable).

**Priorities** (FINDINGS.md section 5, [code]): the sequencer task has priority 10 and the panel
task 15, and a lower number wins. The sequencer can therefore interrupt a panel-task payload
function at any instruction, and a sequencer-task function always runs to its end before the
panel task continues. Design shared state for that direction: the panel must leave every value
the sequencer reads consistent at every instruction (write the data first, then publish it with
one byte or word), while the sequencer may write several values in a row.

Not known yet (needs a `[code]` or `[unit]` answer before a patch depends on it):

- Whether a flash read through the mapping is safe while another task has a write session open
  (`FUN_600108AA` switches the chip to indirect mode, see FINDINGS.md). Because the sequencer can
  preempt the panel in the middle of a session, assume it is not.

Use these rules:

1. **Flash program and erase only in the panel task.** The raw primitives have no lock.
2. **No flash access from the sequencer task**, reads included. Read what the sequencer needs in
   the panel task, into RAM, before the sequencer needs it.
3. **No buffer or variable that two tasks write.** Give each task its own buffer. A value that
   one task writes and the other only reads must be one aligned word or byte, written last, after
   the data it describes.

## 4. Testing

### Emulation (before every flash)

`tests/emu_motion.py` is the template. It loads the patched application into Unicorn at
`0x60000000`, replaces the firmware functions the payload calls with stubs that log their
arguments, writes the RAM state each scenario needs, and calls the payload functions.

Two kinds of tests are needed:

1. **Unit scenarios**: call your functions directly with chosen state.
2. **Integration**: run the **firmware's own code** that calls your hook (for example the event
   handler `0x60013892`), with only its far callees stubbed. This checks that your hook is on
   the path you think. The first motion prototype passed all unit scenarios and did nothing on
   the unit, because its hook was on a path normal play does not use.

`tests/run_all.sh TR8_UPD.BIN` builds every patch variant and runs all tests.

### On the unit

1. Flash ([UPDATE.md](UPDATE.md)), check that the unit starts and plays normally.
2. Test the feature with a short, written checklist.
3. If nothing happens, do not guess: build variants that remove conditions (`motion-diag`) or a
   probe that makes each link audible (`motion-probe`, `patches/motion/probe.c`). One flash per
   question.
4. Recover with step [1] at power-on and the original file whenever needed.
5. Record the result, even a failure, in the patch document ("History" in
   [MOTION.md](MOTION.md)) and update the confidence tags in FINDINGS.md.

## 5. Lessons from the motion patch

- The decompiler can make a function look like the only path. Check the callers and the
  dispatchers: `FUN_6001446A` maps controls to parameters but is only used by some screens; the
  normal path is the HMI event handler and `FUN_60013F6A`.
- The sequencer counter counts half steps, and the per-step code runs twice per step.
- Your own posted events come back through your hook: filter the echo.
- Conditions taken from one code path (boot mode, knob redirect) can be wrong on another path.
  Remove what you cannot justify on the path you hook.
- The button-held bitmap (`FUN_60013168`) makes button combinations easy and was confirmed on the
  unit.

### Pitfalls found in review

- `VARI` (the panel variation) is 0 = A, 1 = B, **2 = A+B**. Do not reduce it with `& 1`, and do
  not write a 0/1 side back into it. Keep the panel setting and the side being played as two
  different values (`TR8_SEQ_VARI` and `TR8_SEQ_VARIATION` are two different words).
- When A+B plays two sequences one after the other, a bar index inside one side is not a position
  in the A+B sequence. Convert between them in one function, and test a start and a jump on the
  B side with VARI = 2.
- A value read from flash is not valid until its magic and its checksum are checked. Never use a
  field of an unchecked slot as an array index: an erased slot reads `0xFFFFFFFF`.
- When a patch stops redirecting a save, the data it stored before must not be loaded over the
  data the stock save now keeps: the next stock save would write the old data into the slot. Check
  the condition (for example "this pattern has a sequence") on every load path, not only on the
  save.
- A comment or a document that describes the code must change in the same commit as the code.
  Addresses, block counts and sizes in FINDINGS.md that no longer match the code mislead the next
  author and the reviewer.

## 6. Adding a patch: checklist

1. Find the hook sites and the state you need; write them down in FINDINGS.md with tags. For each
   hook, write down its task (section 3, "Task context").
2. Create `patches/<name>/` with the C file, `link.ld`, `build.sh` (copy from `motion`).
3. Add the `PATCHES` entry in `tools/tr8patch.py` (sites with original bytes, allowed regions,
   protected ranges).
4. Write `tests/emu_<name>.py` with unit and integration scenarios; add it to `tests/run_all.sh`.
5. Write `docs/<NAME>.md`: use, behaviour, how it works, limitations, history. If the patch
   stores data, add the section 7 items.
6. Before a pull request, read section 7 (if the patch stores data), the pitfalls in section 5
   and [CLAUDE.md](../CLAUDE.md) "Review criteria": a review checks the same list.
7. Flash, test, record the result.
8. To offer it on the web flasher, add it to `SHOWN` in `tools/build_site.py`, run
   `python3 -I tools/build_site.py` and commit `site/patches.json`. `tests/run_all.sh` checks that
   the site builds the same file as `tr8patch.py` (needs Node). Add a tutorial for a new feature
   to `site/tutorials.js` (English and French, taken from the "Use" section of its document), and
   update it when the gestures change. Pushing `site/` to `main` publishes it
   (`.github/workflows/pages.yml`).

## 7. Patches that store data: the contract

A patch that keeps data across a power cycle (unused pattern parameters, or its own flash area)
must meet each rule below. Write in the patch document how it meets each one, and add an
emulation test for each rule that has a "Test" line.

1. **A power cut at any point loses nothing that was already stored.** This includes every step
   of a compaction or garbage collection. If live data is moved to a scratch area and its old
   place is erased, the boot scan must also read the scratch area.
   Test: stop the payload after each flash program and each erase, rescan, check every bar or
   value.
2. **A failed write changes no state in RAM.** Update the index, the "clean" hash and the write
   pointer only after the read-back confirms the write, so that the next save tries again. Show
   the failure to the user.
   Test: a flash that drops one program.
3. **Every slot is checked before use** (magic, checksum, the key it claims). Erased and torn
   slots are skipped everywhere, not only in the boot scan.
   Test: a block with erased and half-written slots, then a compaction of it.
4. **Sequence numbers survive their wrap.** Take the first valid entry as the starting point of
   the newest-entry search, not 0.
   Test: entries near 0x7FFF, 0x8000 and 0xFFFF.
5. **Flash program and erase run only in the panel task** (section 3).
6. **State what is lost, and when.** The patch document must say, for the patch's own data and for
   the stock data (patterns, kits), what happens on: a power cut, flashing the stock firmware,
   flashing another patch, and a firmware update. Note that the updater rewrites flash
   `0x30000`-`0x3DFFFF` (FINDINGS.md section 3), so any data stored there is erased by every
   update.
