/* Two free regions, both former developer dump code (see docs/MOTION.md): the motion patch uses
   the same pair. The chain test build uses them alone, so it cannot be combined with motion or
   poly yet. The gap 0x60011464..0x60011488 holds live firmware data and is never written.
   The first region is small, so it takes the marked .text.far functions (and .data); the second
   one takes the bulk of the code and the state.
   The bar index (tab, 128 bytes) does not fit in either region, so it is patch RAM above the
   firmware bss: the patcher moves the RTOS pool start from 0x60280988 to 0x60290988 (the same
   64 KB reservation as motion-poly, docs/COMBO.md). Patch RAM is not in the image. */
MEMORY {
  CHAIN  (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  CHAIN2 (rwx) : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
  RAM    (rw)  : ORIGIN = 0x60280A00, LENGTH = 0x60290988 - 0x60280A00
}
SECTIONS {
  /* .text.far first: the first matching clause wins, so .text* below does not take it. */
  .text.far : { *(.text.far*) } > CHAIN
  .data : { *(.data*) } > CHAIN
  .text : { *(.text*) *(.rodata*) } > CHAIN2
  .bss  : { *(.bss*) *(COMMON) } > CHAIN2
  .ram (NOLOAD) : ALIGN(4) { *(.ram*) } > RAM
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
