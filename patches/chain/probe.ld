/* Hardware probe only: the old developer-dump cave build. The real chain now lives in the
   application image (link.ld); this script keeps the probe standalone, as a diagnostic that can
   be flashed alone to see what the gesture and the panel hand it.
   Two free regions, both former developer dump code (see docs/MOTION.md): motion and poly use
   the same pair. The gap 0x60011464..0x60011488 holds live firmware data and is never written.
   The probe has no bar index and no patch RAM, so the pool start stays stock. */
MEMORY {
  CHAIN  (rwx) : ORIGIN = 0x60011150, LENGTH = 0x60011464 - 0x60011150
  CHAIN2 (rwx) : ORIGIN = 0x60011488, LENGTH = 0x60011BB6 - 0x60011488
}
SECTIONS {
  /* .text.far first: the first matching clause wins, so .text* below does not take it. */
  .text.far : { *(.text.far*) } > CHAIN
  .data : { *(.data*) } > CHAIN
  .text : { *(.text*) *(.rodata*) } > CHAIN2
  .bss : { *(.bss*) *(COMMON) } > CHAIN2
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
