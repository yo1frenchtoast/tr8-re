/*
 * Patch RAM for combined patches (motion + poly).
 *
 * The RTOS memory pool starts right after the firmware bss (0x60280988, literal at 0x600104A8,
 * read by the pool setup FUN_60010430). The combined patch moves that start up by 64 KB
 * (tools/tr8patch.py, site 0x600104A8), so 0x60280988-0x60290987 belongs to the patches.
 * This RAM is not in the image and not zeroed by the startup code: ram_init zeroes the
 * patches' .ram section, then creates the pool as before.
 *
 * Hook: ram_init replaces "bl FUN_60010430" at 0x60010482 (boot, before the RTOS starts).
 */
#include "tr8_v161.h"

extern uint32_t __ram_start[], __ram_end[];

typedef void (*pool_fn)(void);
#define ORIG_POOL_INIT ((pool_fn)0x60010431)                /* FUN_60010430 */

void ram_init(void)
{
    for (volatile uint32_t *p = __ram_start; p < __ram_end; p++)
        *p = 0;
    ORIG_POOL_INIT();
}
