/* First free region of the motion patch (former developer dump code, see docs/MOTION.md).
   The poly test build uses it alone, so it cannot be combined with motion yet. */
MEMORY {
  POLY (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
}
SECTIONS {
  .text : { *(.text*) *(.rodata*) } > POLY
  .data : { *(.data*) } > POLY
  .bss  : { *(.bss*) *(COMMON) } > POLY
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
