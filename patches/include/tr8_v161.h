/*
 * Roland TR-8 system v1.61: firmware addresses and functions for patch payloads.
 *
 * Every address is a runtime address of the main application (loaded at 0x60000000).
 * Function pointers have the Thumb bit set. See docs/FINDINGS.md for the evidence
 * behind each entry and docs/DEVELOPING.md for how to use them.
 *
 * Confidence tags:
 *   [unit]  confirmed on a real TR-8
 *   [code]  read from the code, consistent, not tested on a unit
 *   [hyp]   hypothesis
 */
#ifndef TR8_V161_H
#define TR8_V161_H

#include <stdint.h>

/* ---------------------------------------------------------------- sequencer */

/* Sequencer state struct at 0x6007E100. */
#define TR8_SEQ_RUNNING   (*(volatile uint8_t  *)0x6007E102)  /* [unit] 1 while playing      */
#define TR8_SEQ_COUNTER   (*(volatile uint32_t *)0x6007E118)  /* [unit] HALF steps: step = counter >> 1 */
#define TR8_SEQ_LAST      (*(volatile uint32_t *)0x6007E11C)  /* [code] last counter value of the pattern */
#define TR8_SEQ_TICK      (*(volatile uint32_t *)0x6007E120)  /* [code] tick inside the half step */
#define TR8_SEQ_TICKS     (*(volatile uint32_t *)0x6007E130)  /* [code] ticks per half step   */
#define TR8_SEQ_VARIATION (*(volatile uint32_t *)0x6012FA74)  /* [unit] 0 = A, other = B      */

/* Player struct 0x6012FA64 (what FUN_600095F0 and FUN_6000E404 take):
 *   +0x0c VARI: 0 = A, 1 = B, 2 = A+B (the panel setting)
 *   +0x10 effective variation, i.e. TR8_SEQ_VARIATION
 *   +0x14 / +0x18 LAST_A / LAST_B (FUN_600525F8 picks by the effective variation)
 * FUN_600095F0 restarts the pattern: load the panel parameters, apply the variation, read the
 * last step, run the player. It is called at sequencer start (0x600091A2, 0x600098E4) and at
 * every pattern wrap (0x600098CA). */
#define TR8_SEQ_VARI (*(volatile uint32_t *)0x6012FA70)        /* [code] panel VARI            */
typedef void (*tr8_obj_fn)(void *obj);
#define TR8_FN_VARIATION ((tr8_obj_fn)0x6000E405)              /* [code] FUN_6000E404: VARI -> effective, masks -> sound */
#define TR8_FN_APPLY     ((tr8_obj_fn)0x6000E153)              /* [code] FUN_6000E152          */
#define TR8_FN_RESTART   ((tr8_obj_fn)0x600095F1)              /* [code] FUN_600095F0          */

/* Per-step function: called (usually twice) for every step from the clock tick.
 * Hook its call sites 0x60009862 and 0x60009808 to run code once per step. */
typedef uint64_t (*tr8_step_fn)(void *p, int step);
#define TR8_FN_STEP ((tr8_step_fn)0x6000978F)                 /* [unit] FUN_6000978E          */

/* ---------------------------------------------------------------- step player */

/* Step player object (FINDINGS section 7, "Step trigger"). Word indexes into uint32_t *P. */
#define TR8_PLAYER     ((volatile uint32_t *)0x6014A164)      /* [unit] DAT_6000991C          */
#define TR8_PL_RUN     1      /* [unit] != 0: a trigger with step -1 advances the position   */
#define TR8_PL_LAST    3      /* [unit] last step index (FUN_600268F4)                       */
#define TR8_PL_ACCENT  0x20   /* [code] global accent mask (AC row)                          */
#define TR8_PL_INST    0x21   /* [unit] + i: step mask of instrument i (BD SD LT MT HT RS HC CH OH CC RC) */
#define TR8_PL_ACC     0x42   /* [unit] + i: accent mask of instrument i                     */
#define TR8_PL_FLAM    0x67   /* [code] + i: flam mask of instrument i                       */
#define TR8_PL_POS     0x66   /* [unit] current step (0..LAST)                               */
#define TR8_PL_SCATTER 0x1DA  /* [code] BYTE offset of an s16: -1 = no scatter step order    */

/* Trigger one step: step -1 = advance and play the next step, else play `step` (flam != 0:
 * delayed flam hit, tests the flam masks). Tests bit (1 << step) of every mask.
 * Returns bit i = instrument i fired. Called by the sequencer at 0x60009800, 0x6000985A,
 * 0x60009884 (advance) and 0x60009A50 (flam). */
typedef uint32_t (*tr8_trigger_fn)(volatile uint32_t *p, int step, int flam);
#define TR8_FN_TRIGGER ((tr8_trigger_fn)0x600262F3)            /* [unit] FUN_600262F2          */

/* Set the player run state: run != 0 at start (0x6000966E), 0 at stop (0x600096AE, which
 * also sets the position to LAST so the next advance plays step 0). */
typedef void (*tr8_player_run_fn)(void *p, int unused, int run);
#define TR8_FN_PLAYER_RUN ((tr8_player_run_fn)0x60026895)      /* [unit] FUN_60026894          */

/* ---------------------------------------------------------------- panel controls */

#define TR8_NCTRL 49  /* control ids 0..48, see TR8_CTRL_* and docs/FINDINGS.md "Control ids" */

/* Post a control change exactly like the ADC scan does: event {0x0B, id, value}
 * into the panel FIFO (critical section inside, safe from the sequencer task).
 * The panel task then runs the normal knob path: screen, parameter, sound, display. */
typedef void (*tr8_post_ctrl_fn)(int id, int value /* 0..255 */);
#define TR8_POST_CTRL ((tr8_post_ctrl_fn)0x60000CC1)           /* [unit] ADC change callback   */

/* HMI knob event handler (case 10 of the HMI dispatcher), at 0x60013892:
 *   if (modal) return; store value; if (FUN_60013242(screen, ev) == 0) FUN_60013F6A(id, value);
 * Hook the "bl FUN_60013242" at 0x600138C8 to see every knob event before the firmware. */
typedef int (*tr8_screen_fn)(int screen, const int16_t *ev /* {10, id, value} */);
#define TR8_FN_SCREEN_EVENT ((tr8_screen_fn)0x60013243)         /* [unit] FUN_60013242          */
#define TR8_HOOK_KNOB_EVENT 0x600138C8                          /* [unit] bl site               */

/* Global control -> parameter table (used when the screen does not take the event). */
typedef void (*tr8_ctrl_apply_fn)(int id, int value);
#define TR8_FN_CTRL_APPLY ((tr8_ctrl_apply_fn)0x60013F6B)       /* [code] FUN_60013F6A          */

/* ---------------------------------------------------------------- buttons */

/* 1 while the button is held. Bitmap at 0x6014893C. */
typedef int (*tr8_held_fn)(unsigned id);
#define TR8_BTN_HELD ((tr8_held_fn)0x60013169)                  /* [unit] FUN_60013168          */

#define TR8_BTN_STEP(n)   ((n) - 1)   /* [code] step buttons 1..16 = ids 0x00..0x0F            */
#define TR8_BTN_TR_REC    0x11        /* [unit]                                                */
#define TR8_BTN_VARI_A    0x17        /* [code] writes the panel setting VARI (+0x0C)          */
#define TR8_BTN_VARI_B    0x18        /* [code]                                                */
#define TR8_BTN_CLEAR     0x1C        /* [unit]                                                */
#define TR8_BTN_INST_FIRST 0x1D       /* [code] row buttons 0x1D..0x2B: AC RV EC SC, then 11 instruments */
/* Button of instrument i (player order BD SD LT MT HT RS HC CH OH CC RC). The buttons are
 * 0x21..0x2B in the same order except RS and HC, which are swapped: 0x26 = HC, 0x27 = RS [unit]. */
#define TR8_BTN_INST(i)   (0x21 + ((i) == 5 ? 6 : (i) == 6 ? 5 : (i)))
#define TR8_BTN_LAST_STEP 0x1A        /* [unit] held + step pad -> FUN_6001B8D6 sets LAST_A/B  */

/* Set the pattern's last step (Ptn index 2 + variation) to pad 0..15. Called only from the
 * button handler FUN_6001961E at 0x60019A10, when a step pad is pressed with LAST STEP held. */
typedef void (*tr8_set_last_fn)(void *obj, int pad);
#define TR8_FN_SET_LAST ((tr8_set_last_fn)0x6001B8D7)            /* [code] FUN_6001B8D6          */

/* Button press and release dispatch. The type 5 (press) event handler FUN_600137DE sets the
 * held bit, then calls FUN_60013B34(id) (bl at 0x60013842): the active screen is offered the
 * press first and the global button handler FUN_6001961E only runs if the screen declines it
 * (that is why LAST STEP + pad reaches FUN_6001961E but a bare pad press does not). The type 6
 * (release) handler FUN_6001377C calls FUN_60013B56(id) (bl at 0x600137D2) the same way.
 * A patch that must see every press, before the screen, hooks these two calls. */
typedef int (*tr8_btn_fn)(int id);
#define TR8_FN_BTN_PRESS   ((tr8_btn_fn)0x60013B35)              /* [code] FUN_60013B34          */
#define TR8_FN_BTN_RELEASE ((tr8_btn_fn)0x60013B57)              /* [code] FUN_60013B56          */

/* ---------------------------------------------------------------- parameters */

/* Parameter storage (FINDINGS section 6). Every area is a table of 32-bit values, one per
 * global id, stored in "slots": slot 0 is the working copy that the panel edits and the
 * sequencer plays, slot n+1 is pattern n. A slot context is 12 bytes:
 *   +0  pointer to the first value word of that slot
 *   +4  area byte (0..7)
 *   +5  0x25, the type byte the getter/setter check
 *   +8  first global id of the area
 * Read and write a value word directly through the pointer; the getter/setter add range
 * checks and change notifications on top. */
typedef void (*tr8_pctx_fn)(void *ctx, int area, int slot);
#define TR8_FN_PCTX ((tr8_pctx_fn)0x6000F80F)                   /* [code] FUN_6000F80E */
#define TR8_AREA_SETUP   1      /* Setup: word n = Setup[n], global id 0x2A + n            */
#define TR8_AREA_PATTERN 4      /* Ptn: word 0 VARI, 1 scale, 2 LAST_A, 3 LAST_B,          */
                                /*      4..55 = 26 pairs (A mask, B mask) per step row     */
#define TR8_AREA_PTN2    6      /* Ptn2: weak accent, flams, spare ids (POLY.md)           */
#define TR8_SETUP_PATTERN 2     /* [code] Setup[2]: pattern that slot 0 belongs to         */
#define TR8_SETUP_PENDING 3     /* [code] Setup[3]: pattern to load (-1 = none)            */
#define TR8_SETUP_DISPLAY 0xF   /* [code] Setup[0xF]: pattern number shown by the panel    */

/* Copy one slot of an area into another: FUN_6000F3C2 fills a 12-byte descriptor for the
 * destination slot, then FUN_6000F3EC(ctx, area, src_slot, 0) copies (area, src_slot) into
 * the destination and notifies when the destination is slot 0. This is how the firmware
 * loads a pattern: it copies area 4 slot n+1 into slot 0 (FUN_6001B842). RAM only, no flash
 * write. The descriptor is {byte area, pad, word slot, byte 0xFF, ...}: a *storage* address,
 * not the getter context of TR8_FN_PCTX below (which holds a value pointer). */
typedef void (*tr8_copy_ctx_fn)(void *ctx, int area, int dst_slot);
typedef void (*tr8_copy_fn)(void *ctx, int area, int src_slot, int unused);
#define TR8_FN_COPY_CTX ((tr8_copy_ctx_fn)0x6000F3C3)            /* [code] FUN_6000F3C2 */
#define TR8_FN_COPY ((tr8_copy_fn)0x6000F3ED)                   /* [code] FUN_6000F3EC */

/* The notification a copy sends when it lands in slot 0: FUN_60050F70 returns the dispatcher
 * object and FUN_60010148(dispatcher, {u8 slot, u8 area}) walks its observers, which is how the
 * screens learn that slot 0 of an area changed. slot is 0 for the current slot and 1 for
 * another slot of the area (FUN_6000F3EC passes 0, the setters pass 0 or 1 the same way).
 * A patch that writes slot 0 directly has to send this too, or the views keep the old values
 * until something else refreshes them. RAM only, no flash write. */
typedef void (*tr8_notify_fn)(void *dispatcher, const void *event);
typedef void *(*tr8_dispatch_fn)(void);
#define TR8_FN_NOTIFY ((tr8_notify_fn)0x60010149)                /* [code] FUN_60010148 */
#define TR8_FN_DISPATCH ((tr8_dispatch_fn)0x60050F71)            /* [code] FUN_60050F70 */

/* Copy area slot 0 into `slot` and write that slot to the user flash. FUN_6001B7D8(_, n)
 * does this for area 4 and area 6 with slot = n + 1 when the panel changes pattern. The
 * first and last arguments are unused (the firmware passes a database object and 0). */
typedef void (*tr8_commit_fn)(int unused, int area, int slot, int unused2);
#define TR8_FN_COMMIT ((tr8_commit_fn)0x6000FC79)               /* [code] FUN_6000FC78 */

/* FUN_6000E0E0(struct, scale) maps the pattern scale word (0..3) to the step grouping
 * written to the player struct at +0x1C: 8, 4, 6, 3. */
typedef void (*tr8_scale_fn)(void *obj, int scale);
#define TR8_FN_SCALE ((tr8_scale_fn)0x6000E0E1)                 /* [code] FUN_6000E0E0 */

/* Player struct 0x6012FA64 (the object that FUN_600095F0 fills and FUN_6000E152 applies):
 *   +0x0C VARI, +0x10 effective variation, +0x14/+0x18 LAST_A/LAST_B, +0x1C scale,
 *   +0x20..+0xAE the 26 A/B mask pairs that FUN_6000E080 writes and FUN_6000E152 reads.
 * FUN_6000E0FE fills the scalars from area 4 slot 0; FUN_6000E4A6 loads the pattern named
 * by +0x08 into slot 0 and fills everything. */
#define TR8_PTN_STRUCT ((volatile uint8_t *)0x6012FA64)         /* [code] DAT_6000991C     */
#define TR8_PTN_VARI   0x0C
#define TR8_PTN_EFF    0x10
#define TR8_PTN_LAST_A 0x14
#define TR8_PTN_LAST_B 0x18
#define TR8_PTN_SCALE  0x1C

/* HMI parameter databases. All take the object pointer as first argument. */
typedef int (*tr8_get_fn)(void *db, int idx, int def);
#define TR8_HMI_SETUP ((void *)0x60149F38)                      /* [code] Setup database object */
#define TR8_SETUP_GET ((tr8_get_fn)0x6001B12F)                  /* [code] Setup idx n = global 0x2A+n */
#define TR8_SYSTEM_GET ((tr8_get_fn)0x6001B433)                 /* [code] FUN_6001B432          */
#define TR8_PTN_GET   ((tr8_get_fn)0x6001B737)                  /* [code] FUN_6001B736          */
#define TR8_PTN2_GET  ((tr8_get_fn)0x6001D3FB)                  /* [code] FUN_6001D3FA          */

/* Generic HMI setter: clamps to the range and writes only on change. */
typedef void (*tr8_set_fn)(void *db, int idx, int value, int sub);
#define TR8_HMI_SET ((tr8_set_fn)0x600186FB)                    /* [code] FUN_600186FA          */

/* Ptn2 database (area 6, global ids 0x127..0x14E, FINDINGS section 6): weak accent, flams,
 * and 16 unnamed ids that no code reads (0x127, 0x128, 0x12B..0x138; 0 in all factory
 * patterns). Each pattern stores the whole area in the user flash, so these ids are saved
 * with the pattern. Index n = global id 0x127 + n.
 * Values of the current pattern (RAM, bank 0 slot 0; the firmware copies a pattern in and
 * out of this slot when it changes patterns): */
#define TR8_PTN2_CUR   ((volatile uint32_t *)0x60146930)        /* [code] table 0x6005D2A4      */
/* Set Ptn2 index idx of the current pattern like a panel edit: range check, then the
 * pattern is marked changed and saved by the firmware. Asserts (hangs) if out of range
 * (0..65535 for the unnamed ids). db is not used. */
typedef void (*tr8_ptn2_set_fn)(void *db, int idx, int value);
#define TR8_PTN2_SET   ((tr8_ptn2_set_fn)0x6001D433)            /* [code] FUN_6001D432          */
#define TR8_PTN2_SPARE 4      /* [code] first unnamed index after WEAK_ACC1/2: ids 0x12B..0x138 */

/* Setup[0] = panel mode: 0 TR-REC, 3 INST REC (others not identified). */
#define TR8_SETUP_MODE 0                                        /* [code]                       */

/* Sound parameters travel as internal MIDI control changes {0x0B, 0xB0, cc, value}.
 * The cc numbers are the TR-8 MIDI implementation numbers (BD tune = 20, ...). */
typedef void (*tr8_cc_fn)(void *unused, int cc, int value);
#define TR8_SEND_CC ((tr8_cc_fn)0x60015907)                     /* [code] FUN_60015906          */

/* ---------------------------------------------------------------- display and LEDs */

/* Show a short string on the display (the factory test mode shows the 4-letter knob
 * names with it). The active screen redraws the display later. */
typedef void (*tr8_text_fn)(void *unused, const char *s);
#define TR8_DISPLAY_TEXT ((tr8_text_fn)0x60015981)              /* [code] FUN_60015980          */

/* Step LED colour: led = 0x1D + step (0..15). Colours seen in the step LED function
 * FUN_60016386: 0 = play position, 0x2A = inside the pattern length (LAST STEP view),
 * 0x2D = off, 1/2/3/4 = steps 1-4/5-8/9-12/13-16 in the normal view (red/orange/yellow/white
 * groups of the panel) [code]. */
typedef void (*tr8_step_led_fn)(int led, unsigned colour);
#define TR8_FN_STEP_LED ((tr8_step_led_fn)0x6001774F)            /* [code] FUN_6001774E          */
#define TR8_LED_STEP(n) (0x1D + (n))
#define TR8_COL_PLAY  0x00   /* [unit] blinks while playing */
#define TR8_COL_RED   0x01   /* [unit] red, POLY.md test 3 */
#define TR8_COL_YELLOW 0x03  /* [unit] steps 9-12 group, the panel's yellow */
#define TR8_COL_IN    0x2A   /* [unit] green */
#define TR8_COL_OFF   0x2D

/* Raw LED setter behind everything: both wrappers below end in "bl FUN_6004BB4C", a veneer to
 * the fast-code function 0x01000537: FUN_6004BB4C(obj, led, a, b, c) with the LED object
 * 0x601488D0. FUN_6001773A / FUN_60017E08 pass raw levels, FUN_6001774E / FUN_60017E1E look a
 * palette colour up first. [code] */
typedef void (*tr8_led_set_fn)(void *obj, int led, int a, int b, int c);
#define TR8_FN_LED_SET ((tr8_led_set_fn)0x6004BB4D)              /* [code] FUN_6004BB4C veneer   */
#define TR8_LED_OBJ    ((void *)0x601488D0)                      /* [code] LED object            */

/* LED control, arguments not decoded: FUN_6001A7EC(id, a, b, c). */
typedef void (*tr8_led_fn)(int id, int a, int b, int c);
#define TR8_LED ((tr8_led_fn)0x6001A7ED)                        /* [hyp]                        */

/* ---------------------------------------------------------------- control ids */

enum {
    TR8_CTRL_VOLM = 0,  TR8_CTRL_ACLV = 1,  TR8_CTRL_GRGT = 2,  TR8_CTRL_GRLV = 3,
    TR8_CTRL_GRTM = 4,  TR8_CTRL_SETM = 5,  TR8_CTRL_SEFB = 6,  TR8_CTRL_SELV = 7,
    TR8_CTRL_BDTU = 8,  TR8_CTRL_BDAT = 9,  TR8_CTRL_BDCO = 10, TR8_CTRL_BDDC = 11,
    TR8_CTRL_BDLV = 12, TR8_CTRL_SDTU = 13, TR8_CTRL_SDSN = 14, TR8_CTRL_SDCO = 15,
    TR8_CTRL_SDDC = 16, TR8_CTRL_SDLV = 17, TR8_CTRL_LTTU = 18, TR8_CTRL_LTDC = 19,
    TR8_CTRL_LTLV = 20, TR8_CTRL_MTTU = 21, TR8_CTRL_MTDC = 22, TR8_CTRL_MTLV = 23,
    TR8_CTRL_HTTU = 24, TR8_CTRL_HTDC = 25, TR8_CTRL_HTLV = 26, TR8_CTRL_RSTU = 27,
    TR8_CTRL_RSDC = 28, TR8_CTRL_RSLV = 29, TR8_CTRL_HCTU = 30, TR8_CTRL_HCDC = 31,
    TR8_CTRL_HCLV = 32, TR8_CTRL_CHTU = 33, TR8_CTRL_CHDC = 34, TR8_CTRL_CHLV = 35,
    TR8_CTRL_OHTU = 36, TR8_CTRL_OHDC = 37, TR8_CTRL_OHLV = 38, TR8_CTRL_CCTU = 39,
    TR8_CTRL_CCDC = 40, TR8_CTRL_CCLV = 41, TR8_CTRL_RCTU = 42, TR8_CTRL_RCDC = 43,
    TR8_CTRL_RCLV = 44, TR8_CTRL_SHFL = 45, TR8_CTRL_FINE = 46, TR8_CTRL_EXLV = 47,
    TR8_CTRL_EXSC = 48,
};

#endif
