/* The code and its state live in the application image itself, above the firmware bss.
   The developer-dump cave (docs/FINDINGS.md section 12) is too small now: motion, poly and the
   bar chain together need more than its 2.6 KB, so the chain moved here. The patcher grows the
   image to cover this region (tools/tr8patch.py, docs/CHAIN.md "Code space") and moves the RTOS
   pool start from 0x60280988 to 0x60290988 (literal 0x600104A8), the same 64 KB reservation
   motion-poly uses. 0x60280988-0x60281183 stays below this region for motion-poly's patch RAM;
   the startup zero-fill ends at 0x60280987, so nothing written here is erased. */
MEMORY {
  IMAGE (rwx) : ORIGIN = 0x60281200, LENGTH = 0x2000
}
SECTIONS {
  .text : { *(.text*) *(.rodata*) } > IMAGE
  .data : { *(.data*) } > IMAGE
  .bss  : { *(.bss*) *(COMMON) } > IMAGE
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
