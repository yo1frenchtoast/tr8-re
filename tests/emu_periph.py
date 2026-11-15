#!/usr/bin/env python3
"""Run the firmware's own serial flash and MIDI UART drivers on the register models of
tests/periph.py (needs: pip install unicorn).

  python3 tests/emu_periph.py work/patched/appA.bin

Works on the stock application and on every patched one: the drivers are firmware code that no
patch changes. Tested here:

  - flash read (FUN_60003EA2) through the memory-mapped window, and the controller mode that
    each driver function leaves behind;
  - a write session as the stock store and the bar chain do it: FUN_600108AA (open), erase
    FUN_60003EDA, program FUN_60003E54, FUN_600108BA (close and protect);
  - the status polling: the drivers wait until the chip is idle before they return;
  - a write to the protected array is dropped (the assumption that tests/emu_chain.py makes);
  - FUN_60003E54 programs in 256-byte commands from the start address, so a write that is not
    page-aligned and crosses a page end wraps inside the page (a pitfall for patches);
  - a power cut halfway through an erase or a program;
  - the MIDI receive interrupt: bytes from the FIFO reach the parser in order, receive errors;
  - the MIDI transmit interrupt: 4-byte packets from the firmware's queue go out on the UART,
    with running status.

The ROM routines and the chip behaviour are guesses [hyp] (tests/periph.py): these tests check
the drivers against our reading of the hardware, not against the unit.
"""
import os, struct, sys
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from periph import RomApi, SerialFlash, MidiUart, ModelError, PowerCut

app = open(sys.argv[1], "rb").read()
uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x60000000, 0x00400000)
uc.mem_write(0x60000000, app)
FAST_LOAD, FAST_RUN, FAST_LEN = 0x601264EC, 0x01000300, 0xA374     # FINDINGS.md section 4
uc.mem_map(0x01000000, 0x30000)
uc.mem_write(FAST_RUN, app[FAST_LOAD - 0x60000000:FAST_LOAD - 0x60000000 + FAST_LEN])
fast = lambda load: load - FAST_LOAD + FAST_RUN
uc.mem_map(0x20000000, 0x10000)                 # tightly coupled RAM
uc.mem_map(0x70000000, 0x10000)                 # stack, scratch and the return trap
RET, SCRATCH = 0x7000F000, 0x70001000
uc.mem_write(RET, b"\xfe\xe7")

rom = RomApi(uc)
flash = SerialFlash(uc, rom)
uart = MidiUart(uc)

r32 = lambda a: struct.unpack("<I", uc.mem_read(a, 4))[0]
w32 = lambda a, v: uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

log = []
STUBS = {0x6000678A: "midi_in", 0x600067CE: "midi_err2", 0x600067EE: "midi_err3"}
def hook(uc, addr, size, _):
    name = STUBS[addr]
    log.append((name, uc.reg_read(UC_ARM_REG_R1) & 0xFF) if name == "midi_in" else (name,))
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
for a in STUBS:
    uc.hook_add(UC_HOOK_CODE, hook, begin=a, end=a)

def call(fn, *args):
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v & 0xFFFFFFFF)
    uc.reg_write(UC_ARM_REG_SP, 0x7000E000)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    uc.emu_start(fn | 1, RET, count=2000000)
    return uc.reg_read(UC_ARM_REG_R0)

fails = 0
def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))

def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc as e:
        return type(e).__name__
    return None

F_READ, F_PROG, F_ERASE = 0x60003EA2, 0x60003E54, 0x60003EDA
F_OPEN, F_CLOSE, F_MODE = 0x600108AA, 0x600108BA, 0x60003D74
OP_RDSR = 0xC8

def flash_read(off, n):
    call(F_READ, off, n, SCRATCH)
    return bytes(uc.mem_read(SCRATCH, n))

def flash_prog(off, data):
    uc.mem_write(SCRATCH, data)
    call(F_PROG, off, len(data), SCRATCH)

def session(fn):
    """Run fn between the firmware's open and close, as the stock store FUN_60010BB6 does."""
    call(F_OPEN)
    fn()
    call(F_CLOSE)

# --- read ------------------------------------------------------------------------------
flash.mem[0x3DB000:0x3DB010] = bytes(range(16))
call(F_MODE, 0)
expect("read: FUN_60003EA2 reads through the window", flash_read(0x3DB000, 16), bytes(range(16)))
expect("read: it switches to mode 3 and back to the caller's mode 0", flash.mode, 0)
call(F_MODE, 3)
flash_read(0x3DB000, 4)
expect("read: called in mode 3, it stays in mode 3", flash.mode, 3)
call(F_MODE, 0)
expect("model: a window read in command mode is refused",
       raises(ModelError, flash._win_rd, uc, 0, 4, None), "ModelError")

# --- a write session ---------------------------------------------------------------------
flash.protect_all()
call(F_MODE, 3)
entry = bytes((i * 7) & 0xFF for i in range(128))
def write_entry():
    call(F_ERASE, 0x3DB000)
    expect("session: the erase cleared the sector", flash_read(0x3DB000, 0x1000), b"\xff" * 0x1000)
    flash_prog(0x3DB080, entry)
session(write_entry)
expect("session: the 128-byte entry is in the flash", bytes(flash.mem[0x3DB080:0x3DB100]), entry)
expect("session: the rest of the sector is erased", bytes(flash.mem[0x3DB000:0x3DB080]), b"\xff" * 128)
expect("session: FUN_600108BA protects the array again", flash.sr & SerialFlash.BP, SerialFlash.BP)
expect("session: and leaves memory-mapped mode", flash.mode, 3)
expect("session: write status, erase, program, write status",
       [(op, st) for op, _, _, st in flash.ops], [(1, "done"), (0x20, "done"), (2, "done"), (1, "done")])
expect("session: the window sees the entry", flash_read(0x3DB080, 128), entry)

# --- the drivers wait for the chip --------------------------------------------------------
flash.busy_polls, rom.calls[:] = 5, []
session(lambda: call(F_ERASE, 0x3DC000))
polls = [c for c in rom.calls if c[0] == OP_RDSR]
expect("busy: each command polls the status until the chip is idle (3 commands x 6 reads)",
       len(polls), 18)
expect("busy: the chip is idle when the session returns", flash.busy, 0)
flash.busy_polls = 2

# --- protected array ----------------------------------------------------------------------
flash.ops.clear()
flash.mem[0x3DD000] = 0x00
call(F_MODE, 0)
call(F_ERASE, 0x3DD000)
flash_prog(0x3DD100, b"\x00" * 16)
call(F_MODE, 3)
expect("protect: erase and program outside a session are dropped",
       [st for _, _, _, st in flash.ops], ["protected", "protected"])
expect("protect: the flash is unchanged", (flash.mem[0x3DD000], bytes(flash.mem[0x3DD100:0x3DD110])),
       (0x00, b"\xff" * 16))

# --- page wrap ----------------------------------------------------------------------------
big = bytes((i * 13 + 1) & 0xFF for i in range(0x300))
session(lambda: (call(F_ERASE, 0x3DE000), flash_prog(0x3DE000, big)))
expect("page: an aligned 0x300-byte write lands as 3 page programs",
       (bytes(flash.mem[0x3DE000:0x3DE300]), sum(op == 2 for op, *_ in flash.ops[-4:])), (big, 3))
data = bytes((i + 1) & 0xFF for i in range(0x100))
session(lambda: (call(F_ERASE, 0x3DF000), flash_prog(0x3DF080, data)))
expect("page: an unaligned 256-byte write wraps inside its page (bytes 0x80.. land at the start)",
       (bytes(flash.mem[0x3DF080:0x3DF100]), bytes(flash.mem[0x3DF000:0x3DF080]),
        flash.mem[0x3DF100]), (data[:0x80], data[0x80:], 0xFF))

# --- power cut ----------------------------------------------------------------------------
flash.mem[0x3DA000:0x3DB000] = b"\x00" * 0x1000
call(F_OPEN)
flash.cut_at = 0
expect("cut: the erase raises PowerCut", raises(PowerCut, call, F_ERASE, 0x3DA000), "PowerCut")
expect("cut: half the sector is erased, half keeps its old bytes",
       (bytes(flash.mem[0x3DA000:0x3DA800]) == b"\xff" * 0x800,
        bytes(flash.mem[0x3DA800:0x3DB000]) == b"\x00" * 0x800), (True, True))
flash.busy = 0
call(F_ERASE, 0x3DA000)
flash.cut_at = 0
expect("cut: a program raises PowerCut", raises(PowerCut, flash_prog, 0x3DA000, b"\x11" * 64), "PowerCut")
expect("cut: half the bytes are programmed", bytes(flash.mem[0x3DA000:0x3DA040]),
       b"\x11" * 32 + b"\xff" * 32)
flash.busy = 0
call(F_CLOSE)

# --- MIDI receive -------------------------------------------------------------------------
RX_ISR, TX_ISR = fast(0x6012F074), fast(0x6012F0CE)
log.clear()
uart.receive([0x90, 0x24, 0x7F, 0xFE])
call(RX_ISR)
expect("rx: the interrupt hands each byte to the parser, in order", log,
       [("midi_in", 0x90), ("midi_in", 0x24), ("midi_in", 0x7F), ("midi_in", 0xFE)])
expect("rx: the receive FIFO is empty", len(uart.rx), 0)
log.clear()
uart.receive([0x80])
uart.error(11)
call(RX_ISR)
expect("rx: error bit 11 is reported as error 3 and the byte is not parsed", log, [("midi_err3",)])
expect("rx: the interrupt clears the error and restarts the receiver (CTRL bits 1, 3)",
       (uart.stat, uart.regs.get(0x40029814, 0) & 0xA), (0, 0xA))
log.clear()
uart.error(12)
call(RX_ISR)
expect("rx: error bit 12 is reported as error 2", log, [("midi_err2",)])
uart.rx.clear()

# --- MIDI transmit ------------------------------------------------------------------------
# The transmit queue of the MIDI context 0x200057E4 (+4): a ring of 4-byte USB-MIDI packets,
# {vtable, start, end, read, write}; vtable = {lock, unlock}. Packets go in through the
# firmware's own FUN_6000758A.
CTX, RING, VT, BUF, NOP = 0x200057E4, 0x2000F000, 0x2000F040, 0x2000F100, 0x2000F080
uc.mem_write(NOP, b"\x70\x47")
w32(VT, NOP | 1); w32(VT + 4, NOP | 1)
for i, v in enumerate((VT, BUF, BUF + 0x100, BUF, BUF)):
    w32(RING + 4 * i, v)
w32(CTX + 4, RING)
uc.mem_write(CTX + 0x160, b"\x00")
for pkt in (0x7F249009, 0x40269009, 0x6407B00B):         # note on, note on (same status), CC
    w32(SCRATCH, pkt)
    expect(f"tx: FUN_6000758A queues packet {pkt:08X}", call(0x6000758A, RING, SCRATCH), 1)
w32(0x40029814, 0x600)
call(TX_ISR)
expect("tx: the bytes go out with running status (the second 0x90 is left out)",
       bytes(uart.tx), bytes([0x90, 0x24, 0x7F, 0x26, 0x40, 0xB0, 0x07, 0x64]))
expect("tx: the empty queue turns the transmit interrupt off (CTRL bits 9, 10 cleared)",
       r32(0x40029814) & 0x600, 0)

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
