# CLAUDE.md

Instructions for Claude (and any other AI agent) that writes or reviews code in this
repository. Human contributors: the same rules apply; [docs/DEVELOPING.md](docs/DEVELOPING.md)
explains them in full.

## Project

Reverse engineering of the Roland TR-8 firmware v1.61, and a patcher that adds features to it.
Payloads are C for Cortex-M3 (`patches/<name>/`), hooked into the firmware by `bl` detours
(`tools/tr8patch.py`). Firmware facts are in `docs/FINDINGS.md`; addresses are in
`patches/include/tr8_v161.h`. Each patch has its own document in `docs/`.

## Hard rules

- Never commit anything from Roland or derived from it: `firmware/`, `work/`, `analysis/`,
  `*.bin`, `*.BIN`, `*.elf` stay out of git.
- Every firmware fact has a confidence tag: `[unit]` (seen on a real TR-8), `[code]` (read in
  the disassembly), `[hyp]` (guess). Do not raise a tag without that evidence.
- Code, comments and documents change together. A document that disagrees with the code is a
  bug.
- Run `tests/run_all.sh <path to TR8_UPD.BIN>` before you say a change works. Emulation passing
  is not proof that the unit works: say which one you checked.
- Run Python with `-I`.

## Review criteria

A review of a patch checks these points. An author checks them before opening a pull request.

1. **Tasks** (DEVELOPING.md section 3, "Task context"): the patch document lists the task of each
   hook. No flash access from the sequencer task. No buffer or variable that two tasks write.
2. **Stored data** (DEVELOPING.md section 7): power-cut safety at every flash step, no RAM state
   change on a failed write, every slot checked before use, sequence-number wrap, and a statement
   of what is lost on a power cut, a stock reflash, another patch and a firmware update.
3. **Pitfalls** (DEVELOPING.md section 5, "Pitfalls found in review"): VARI is 0/1/2, side index
   vs. A+B position, unchecked flash slots as indexes.
4. **Tests**: each rule above that has a "Test" line in DEVELOPING.md has an emulation test.
   Each reported bug gets a test that fails before the fix.
5. **Header**: no unused definitions are added to `tr8_v161.h`. An entry point that is known to
   hang the unit is documented in FINDINGS.md, not offered in the header.
6. **Documents**: addresses, sizes and block counts in FINDINGS.md and the patch document match
   the code.

When a review finds a problem that this list does not cover, add it to the list (or to
DEVELOPING.md) in the same change as the fix, so that the next author knows it.
