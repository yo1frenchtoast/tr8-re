/* Two free regions, both former developer dump code (see docs/MOTION.md): the motion patch uses
   the same pair. The chain test build uses them alone, so it cannot be combined with motion or
   poly yet. The gap 0x60011464..0x60011488 holds live firmware data and is never written.
   The first region is small, so it takes the marked .text.far functions (and .data); the second
   one takes the bulk of the code and the state. */
MEMORY {
  CHAIN  (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  CHAIN2 (rwx) : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
}
SECTIONS {
  /* .text.far first: the first matching clause wins, so .text* below does not take it. */
  .text.far : { *(.text.far*) } > CHAIN
  .data : { *(.data*) } > CHAIN
  .text : { *(.text*) *(.rodata*) } > CHAIN2
  .bss  : { *(.bss*) *(COMMON) } > CHAIN2
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
