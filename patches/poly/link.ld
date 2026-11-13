/* The two free regions of the developer dump code (docs/MOTION.md): the code in the first, the
   LAST STEP LED hook and the data in the second (the first is full). The standalone poly build
   has both to itself; motion + poly is patches/combo. */
MEMORY {
  POLY   (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  POLY_B (rwx) : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
}
SECTIONS {
  .text_b : { *(.text.poly_lsled) } > POLY_B
  .text   : { *(.text*) *(.rodata*) } > POLY
  .data : { *(.data*) } > POLY_B
  .bss  : { *(.bss*) *(COMMON) } > POLY_B
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
