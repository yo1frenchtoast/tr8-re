/* motion + poly in one image.
   Code and initialised data: the two free regions of the developer dump code (docs/MOTION.md).
   Zero-initialised data (.bss, the 1568-byte motion table): patch RAM above the firmware bss,
   freed by moving the RTOS pool start (patches/combo/ram.c). Not in the image. */
MEMORY {
  CAVE_A (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  CAVE_B (rwx) : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
  RAM    (rw)  : ORIGIN = 0x60280A00, LENGTH = 0x60290988 - 0x60280A00
}
SECTIONS {
  .text   : { motion.o(.text*) motion.o(.rodata*) } > CAVE_A
  .data   : { motion.o(.data*) } > CAVE_A
  .text_b : { *(.text*) *(.rodata*) } > CAVE_B
  .data_b : { *(.data*) } > CAVE_B
  .ram (NOLOAD) : ALIGN(4) {
    __ram_start = .;
    *(.cave_b) *(.bss*) *(COMMON)
    . = ALIGN(4);
    __ram_end = .;
  } > RAM
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
