/* Two free regions inside the v1.61 application (former developer dump code, see docs/MOTION.md).
   The literal pool 0x60011464-0x60011483 between them is still used and must not be touched. */
MEMORY {
  CAVE_A (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  CAVE_B (rw)  : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
}
SECTIONS {
  .text   : { *(.text.motion_knob) *(.text.motion_step) *(.text*) *(.rodata*) } > CAVE_A
  .data   : { *(.data*) } > CAVE_A
  .bss    : { *(.bss*) *(COMMON) } > CAVE_A
  .cave_b : { *(.cave_b) } > CAVE_B
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
