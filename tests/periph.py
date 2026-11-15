"""Register models of two ESC2 peripherals, for Unicorn tests that run the firmware's own drivers.

  SerialFlash  the serial flash controller at 0x40005000, the 4 MB chip behind it and its
               memory-mapped window at 0x03000000
  MidiUart     the MIDI UART at 0x40029800
  RomApi       the on-chip ROM function table at 0x02003000 (only the entries these drivers call)

The register layout comes from the drivers (docs/FINDINGS.md, "Processor and peripherals"). What
the drivers do not show is a guess, marked [hyp] here and in FINDINGS.md: a test that passes on
these models checks the firmware against our reading of the hardware, not against the hardware.

Usage:
    rom = RomApi(uc)
    flash = SerialFlash(uc, rom)
    uart = MidiUart(uc)
A model error (a command in the wrong mode, a read while the chip is busy...) raises ModelError
out of uc.emu_start().
"""
import struct


class ModelError(Exception):
    """The firmware used a peripheral in a way the model (or the hardware) does not allow."""


class PowerCut(Exception):
    """Raised by SerialFlash when the power cut that a test asked for happens."""


class RomApi:
    """The ROM function table at 0x02003000 [code: the drivers call through it].

    The ROM itself is not in the firmware file. Each table entry points to a 'bx lr' stub, and a
    code hook runs the Python handler that a model registered for that offset. Calling an entry
    with no handler raises ModelError, so a test cannot silently depend on a ROM routine.
    """
    TABLE, STUBS, SIZE = 0x02003000, 0x02003800, 0x200

    def __init__(self, uc):
        from unicorn import UC_HOOK_CODE
        self.uc, self.handlers, self.calls = uc, {}, []
        uc.mem_map(self.TABLE, 0x1000)
        for off in range(0, self.SIZE, 4):
            uc.mem_write(self.TABLE + off, struct.pack("<I", (self.STUBS + off // 2) | 1))
            uc.mem_write(self.STUBS + off // 2, b"\x70\x47")          # bx lr
        uc.hook_add(UC_HOOK_CODE, self._hook, begin=self.STUBS, end=self.STUBS + self.SIZE // 2)

    def on(self, off, fn):
        self.handlers[off] = fn

    def _hook(self, uc, addr, size, _):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2
        off = (addr - self.STUBS) * 2
        if off not in self.handlers:
            raise ModelError(f"ROM entry +{off:#x} called, but no model handles it")
        args = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        self.calls.append((off, args))
        ret = self.handlers[off](*args)
        uc.reg_write(UC_ARM_REG_R0, (ret or 0) & 0xFFFFFFFF)


class SerialFlash:
    """Serial flash controller (0x40005000) and a 4 MB SPI NOR chip.

    Registers [code: FUN_60003D74-FUN_60003F8A]:
      +0x00 CTRL  bits 29-30 = mode: 0 command (indirect), 3 memory-mapped read. The driver
                  writes the whole word last: 0x80001000 (mode 0) or 0xE0001000 (mode 3).
      +0x08 FIFO  read: bits 0-4 = transmit FIFO level. Write 0x7F0000: clear (the driver does it
                  after each command) [hyp: clear].
      +0x10 LEN   bits 0-28 = data bytes; 0x60000000 = with an address phase [hyp].
      +0x18 OPC   SPI opcode; writing it starts the command.
      +0x1C ADDR  flash address (offset from 0x03000000).
      +0x30 DATA  transmit FIFO, 4 bytes per write, little-endian.
    The driver writes the first data word before OPC and the rest after it; the command runs when
    LEN bytes have arrived.

    ROM entries [hyp: from how the driver uses them]:
      +0xCC(cs)  write enable (the driver calls it before every command; no 0x06 opcode is
                 ever written to OPC)
      +0xF0()    controller busy: 0 = idle. The model finishes each transfer at once.
      +0xC8(cs)  read the chip status register: bit 0 = write in progress.

    Chip [hyp: standard SPI NOR; IC4's marking is not readable]: opcodes 0x01 write status,
    0x02 page program (wraps inside its 256-byte page, can only clear bits), 0x20 sector erase
    (4 KB). Each needs write enable, which it clears. Status bits 2-5 (0x3C) protect the array:
    the firmware only writes 0x00 (open) and 0x3C (all protected). A write to a protected array
    is dropped without an error: the third bar-chain build lost its writes so on the unit
    (docs/CHAIN.md, History). Other protection values depend on the chip part, so they
    raise ModelError.

    Test controls:
      busy_polls   status reads that still show 'write in progress' after a program or erase
      cut_at = k   operation k (0 = the next one) loses power halfway: an erase leaves the first
                   half of its sector erased, a program stores its first half, then PowerCut
      ops          log of (opcode, address, length, done) for every chip operation
    """
    BASE, WINDOW, SIZE = 0x40005000, 0x03000000, 0x400000
    WIP, WEL, BP = 0x01, 0x02, 0x3C

    def __init__(self, uc, rom, busy_polls=2):
        self.uc = uc
        self.mem = bytearray(b"\xff" * self.SIZE)
        self.ctrl, self.len, self.addr, self.opc = 0xE0001000, 0, 0, None
        self.fifo = bytearray()
        self.sr, self.busy, self.busy_polls = 0, 0, busy_polls
        self.cut_at, self.ops, self.window_reads = None, [], 0
        uc.mmio_map(self.BASE, 0x1000, self._rd, None, self._wr, None)
        uc.mmio_map(self.WINDOW, self.SIZE, self._win_rd, None, self._win_wr, None)
        rom.on(0xCC, self._wren)
        rom.on(0xF0, lambda *a: 0)
        rom.on(0xC8, self._rdsr)

    mode = property(lambda self: (self.ctrl >> 29) & 3)

    def protect_all(self):
        """Set the status register as a powered-up unit has it (the firmware protects the array
        after each write session)."""
        self.sr = (self.sr & ~self.BP) | self.BP

    # --- ROM routines
    def _wren(self, cs, *_):
        if self.busy:
            raise ModelError("write enable while the chip is busy")
        self.sr |= self.WEL

    def _rdsr(self, cs, *_):
        if self.busy:
            self.busy -= 1
            return self.sr | self.WIP
        return self.sr

    # --- registers
    def _rd(self, uc, off, size, _):
        if off == 0x00:
            return self.ctrl
        if off == 0x08:
            return 0                                   # FIFO drained at once
        return {0x10: self.len, 0x1C: self.addr, 0x18: self.opc or 0}.get(off, 0)

    def _wr(self, uc, off, size, val, _):
        if off == 0x00:
            self.ctrl = val
        elif off == 0x08:
            if val == 0x7F0000:
                self.fifo.clear()
        elif off == 0x10:
            self.len = val
        elif off == 0x1C:
            self.addr = val
        elif off == 0x30:
            self.fifo += struct.pack("<I", val)
            self._run()
        elif off == 0x18:
            if self.mode != 0:
                raise ModelError(f"opcode {val:#x} written in mode {self.mode}, not command mode")
            if self.busy:
                raise ModelError(f"opcode {val:#x} written while the chip is busy")
            self.opc = val
            self._run()
        else:
            raise ModelError(f"write {val:#x} to unknown flash register +{off:#x}")

    def _protected(self):
        bp = self.sr & self.BP
        if bp not in (0, self.BP):
            raise ModelError(f"status protection bits {bp:#x}: partial protection depends on "
                             "the chip part, not modelled")
        return bp == self.BP

    def _run(self):
        n = self.len & 0x1FFFFFFF
        if self.opc is None or len(self.fifo) < n:
            return
        op, data, self.opc = self.opc, bytes(self.fifo[:n]), None
        self.fifo.clear()
        if op not in (0x01, 0x02, 0x20):
            raise ModelError(f"opcode {op:#x} not modelled")
        if not self.sr & self.WEL:
            self.ops.append((op, self.addr, n, "no write enable"))
            return
        self.sr &= ~self.WEL
        cut = self.cut_at == 0
        if self.cut_at is not None:
            self.cut_at -= 1
        if op == 0x01:
            if not cut:
                self.sr = (self.sr & 0x03) | (data[0] & 0xBC)
        elif self._protected():
            self.ops.append((op, self.addr, n, "protected"))
            return
        elif op == 0x20:
            a = self.addr & ~0xFFF & (self.SIZE - 1)
            k = 0x800 if cut else 0x1000
            self.mem[a:a + k] = b"\xff" * k
        else:
            page, a = self.addr & ~0xFF & (self.SIZE - 1), self.addr & 0xFF
            for b in data[:n // 2 if cut else n]:
                self.mem[page + a] &= b
                a = (a + 1) & 0xFF
        self.ops.append((op, self.addr, n, "cut" if cut else "done"))
        self.busy = self.busy_polls
        if cut:
            raise PowerCut

    # --- memory-mapped window
    def _win_rd(self, uc, off, size, _):
        if self.mode != 3:
            raise ModelError(f"window read at {self.WINDOW + off:#x} in mode {self.mode}")
        if self.busy:
            raise ModelError("window read while the chip is busy")
        self.window_reads += 1
        return int.from_bytes(self.mem[off:off + size], "little")

    def _win_wr(self, uc, off, size, val, _):
        raise ModelError(f"write to the read-only flash window at {self.WINDOW + off:#x}")


class MidiUart:
    """MIDI UART at 0x40029800 [code: the interrupt at load address 0x6012F074 and the
    transmit service at 0x6012F0CE; the midi_drv.cpp init].

      +0x04 STAT  bits 11-13 = receive errors (the interrupt reports bit 11 as error 3, the
                  others as error 2) [hyp: framing, parity, overrun]. Writing bit 15 clears them.
      +0x08 DATA  read: next received byte. Write: transmit a byte.
      +0x14 CTRL  bit 9 = transmit interrupt enable (cleared when the queue is empty), bit 10
                  cleared on each transmit interrupt [hyp: transmit-done flag]. The error path
                  sets bits 1 and 3 [hyp: receiver restart].
      +0x18 LEVEL bits 8-15 = bytes in the receive FIFO.
    The rest of the block (0x40029800 control, the 0x40029880 timer that midi_drv.cpp starts) is
    stored and read back without behaviour.

    Test controls: receive(bytes) fills the receive FIFO, error(bit) sets a receive error,
    tx collects the transmitted bytes.
    """
    BASE = 0x40029800

    def __init__(self, uc):
        self.rx, self.tx, self.stat, self.regs = bytearray(), bytearray(), 0, {}
        uc.mmio_map(0x40029000, 0x1000, self._rd, None, self._wr, None)

    def receive(self, data):
        self.rx += bytes(data)

    def error(self, bit):
        self.stat |= 1 << bit

    def _rd(self, uc, off, size, _):
        a = 0x40029000 + off
        if a == self.BASE + 0x04:
            return self.stat
        if a == self.BASE + 0x08:
            if not self.rx:
                raise ModelError("MIDI data read with an empty receive FIFO")
            b = self.rx[0]
            del self.rx[0]
            return b
        if a == self.BASE + 0x18:
            return min(len(self.rx), 0xFF) << 8
        return self.regs.get(a, 0)

    def _wr(self, uc, off, size, val, _):
        a = 0x40029000 + off
        if a == self.BASE + 0x04:
            if val & 0x8000:
                self.stat &= ~0x3800
        elif a == self.BASE + 0x08:
            self.tx.append(val & 0xFF)
        else:
            self.regs[a] = val
