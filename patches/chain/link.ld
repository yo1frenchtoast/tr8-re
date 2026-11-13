/* First free region of the motion patch (former developer dump code, see docs/MOTION.md).
   The chain test build uses it alone, so it cannot be combined with motion or poly yet. */
MEMORY {
  CHAIN (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
}
SECTIONS {
  .text : { *(.text*) *(.rodata*) } > CHAIN
  .data : { *(.data*) } > CHAIN
  .bss  : { *(.bss*) *(COMMON) } > CHAIN
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
