/*
 * TR-8 v1.61 bar chain: play a pattern as a sequence of bars taken from the patterns.
 *
 * Panel: hold VARIATION A and press step pad n -> bar n plays variation A of pattern n.
 *        hold VARIATION B and press step pad n -> bar n plays variation B of pattern n.
 *        hold VARIATION A + B and press step pad n -> the chain is n bars long.
 *        hold VARIATION A + B + CLEAR and press a pad -> chain off (stock A/B behaviour).
 * The numeric display confirms each step ("  3A", " 12B", "CH 4", "CH12", "CH--").
 *
 * A bar is a pattern variation: 16 patterns x 2 variations = a pool of 32 bars, shared by all
 * songs. The song is the chain in the current pattern's spare Ptn2 ids (see "Storage"), and bar
 * n is pattern n (pattern 1 = pad 1). So "A + pads 1..4, then B + pads 5..8" gives an eight-bar
 * song: four A bars from patterns 1..4 and four B bars from patterns 5..8, each bar with its
 * own steps, scale and length.
 *
 * A plain A or B press still selects that variation for editing and playback, exactly as
 * before; A+B plays the chain (stock: alternates A/B, which is the chain A,B). Painting a bar
 * sets the panel to that bar's variation, so the song is heard by pressing A+B after painting.
 *
 * How (docs/CHAIN.md, docs/FINDINGS.md section 7):
 *   FUN_600095F0 restarts the pattern (sequencer start and every pattern wrap). It fills the
 *   player struct 0x6012FA64 from area 4 slot 0, then FUN_6000E404 applies the variation:
 *   if VARI (+0x0c) is 2 it toggles the effective variation (+0x10), else it stores VARI, then
 *   FUN_6000E152 re-applies the step masks to the sound. The last step used for the new pass is
 *   read after that with FUN_600525F8 (LAST_A at +0x14, LAST_B at +0x18, picked by +0x10), so
 *   the variation and the masks have to be in the struct before FUN_600095F0 returns.
 *   chain_var replaces "bl FUN_6000E404" inside FUN_600095F0: with a chain and VARI = 2 it
 *   picks the bar's variation, fills the struct from the bar's pattern slot and applies it;
 *   otherwise it calls the original.
 *   chain_wrap replaces the "bl FUN_600095F0" of the wrap path (0x600098CA) and marks the
 *   restart as a wrap. Both start paths (0x600091A2, 0x600098E4) go through the same
 *   function: without the mark the chain restarts at bar 1.
 *   chain_press replaces the "bl FUN_60013B34" at 0x60013842, the first thing the button press
 *   event does after setting the held bit. That is *before* the screen is offered the press:
 *   the screen takes a bare pad press (step edit / sound), and the global button handler
 *   FUN_6001961E only sees the presses the screen declines (LAST STEP + pad, variation A/B).
 *   That is why the gesture cannot live in FUN_6001961E: on the unit it never got there.
 *   chain_release replaces the matching "bl FUN_60013B56" at 0x600137D2 so a swallowed press
 *   is not followed by a release the screen never saw a press for.
 *   chain_pad still replaces the "bl FUN_60013168" (LAST STEP check) at the head of the
 *   step-pad branch of FUN_6001961E: it keeps the stock LAST STEP path (return 1) and is a
 *   fallback if a press ever reaches that branch with A/B held.
 *
 * Editing a bar means editing its pattern: the working copy (area 4 slot 0) has to hold the
 * bar's pattern, or TR-REC would record into the wrong one. So the gesture saves the pattern it
 * leaves (area 4 and area 6, FUN_6000FC78, the firmware's own pattern save), copies the bar's
 * slots into slot 0 (FUN_6000F3C2/F3EC, the firmware's own slot copy) and points
 * Setup[2]/Setup[0xF] at it, so the panel shows the bar's pattern. area 6 is loaded too, so the
 * weak accents, the flams and the next save stay consistent; the song (which also lives in area
 * 6) is written again afterwards, so it moves with the selection. Playback never switches
 * patterns: chain_var reads the bar's slot and fills the struct, so the song is not disturbed.
 *
 * Storage: the chain is two Ptn2 parameters of the current pattern, the unnamed ids that no code
 * reads but the firmware stores with every pattern (POLY.md "Storage"):
 *   index 15 (id 0x136): bit n = bar n+1 plays variation B (0 = A)
 *   index 16 (id 0x137): 0 = no chain, 1..16 = number of bars
 * The chain is saved with the pattern like any other edit, and every gesture carries it to the
 * pattern it selects (the one the panel shows), so the last painted bar's pattern holds the
 * whole song. The poly patch uses indices 4..14 (ids 0x12B..0x135) and leaves these two alone.
 *
 * Limit: only the step content moves with a bar (masks, scale, LAST STEP, variation). The kit
 * stays with the current pattern.
 */
#include "tr8_v161.h"

#define CHAIN_BITS 15
#define CHAIN_LEN  16
#define PTN_MASKS  26

uint8_t chain_pos;        /* bar being played, 0..len-1 */
uint8_t chain_wrapping;   /* set by chain_wrap around the FUN_600095F0 call */
uint16_t chain_swallow;   /* pads whose press we took: their release is swallowed too */

static int clen(void)
{
    uint32_t v = TR8_PTN2_CUR[CHAIN_LEN];
    return v <= 16 ? (int)v : 0;
}

static uint32_t cbits(void)
{
    return TR8_PTN2_CUR[CHAIN_BITS] & 0xFFFF;
}

static void show_bar(int n, int is_b)
{
    static char txt[5];
    txt[0] = ' ';
    txt[1] = n >= 10 ? '1' : ' ';
    txt[2] = (char)('0' + n % 10);
    txt[3] = is_b ? 'B' : 'A';
    TR8_DISPLAY_TEXT(0, txt);
}

static void show_len(int n)
{
    static char txt[5];
    txt[0] = 'C';
    txt[1] = 'H';
    txt[2] = n ? (n >= 10 ? '1' : ' ') : '-';
    txt[3] = n ? (char)('0' + n % 10) : '-';
    TR8_DISPLAY_TEXT(0, txt);
}

/* Value words of a parameter slot: slot 0 is the working copy, slot n+1 is pattern n.
 * Setup word n = Setup[n]; pattern word 0 = VARI, 1 = scale, 2 = LAST_A, 3 = LAST_B,
 * 4..55 = the 26 step rows as (A mask, B mask). */
static volatile uint32_t *area_slot(int area, int slot)
{
    uint32_t ctx[3];
    TR8_FN_PCTX(ctx, area, slot);
    return (volatile uint32_t *)ctx[0];
}

/* Fill the player struct with the step content of area 4 slot: the 26 A/B mask pairs, the
 * last steps and the scale. Returns the slot words (word 0 is the variation). */
static volatile uint32_t *bar_fill(int slot)
{
    volatile uint32_t *s = area_slot(TR8_AREA_PATTERN, slot);
    volatile uint8_t *d = TR8_PTN_STRUCT;
    int i;

    for (i = 0; i < PTN_MASKS; i++) {
        int off = i < 4 ? 0x20 + 4 * i : 0x30 + 6 * (i - 4);
        *(volatile uint16_t *)(d + off) = (uint16_t)s[4 + 2 * i];
        *(volatile uint16_t *)(d + off + 2) = (uint16_t)s[5 + 2 * i];
    }
    *(volatile uint32_t *)(d + TR8_PTN_LAST_A) = s[2];
    *(volatile uint32_t *)(d + TR8_PTN_LAST_B) = s[3];
    TR8_FN_SCALE((void *)d, (int)s[1]);
    return s;
}

/* Make bar n (pad n, pattern n-1) the working copy so TR-REC records into it. The pattern we
 * leave is saved first (the two commits are what the firmware's own pattern save does:
 * FUN_6001B7D8 -> FUN_6000FC78 for area 4 and area 6), then the bar's pattern is loaded the
 * way FUN_6001B842 does it (area 4 and, when enabled, area 6). area 6 carries the weak accents,
 * the flams and the chain, so it has to be loaded too or the next save would write the previous
 * pattern's area 6 into this one. */
static void bar_switch(int n)
{
    uint32_t ctx[3];
    int p = n - 1;                                      /* pattern index, 0..15 */
    int cur = (int)(area_slot(TR8_AREA_SETUP, 0)[TR8_SETUP_PATTERN] & 0xF);
    volatile uint32_t *setup;

    if (p == cur)
        return;
    TR8_FN_COMMIT(0, TR8_AREA_PATTERN, cur + 1, 0);     /* save the pattern we leave */
    TR8_FN_COMMIT(0, TR8_AREA_PTN2, cur + 1, 0);
    TR8_FN_COPY_CTX(ctx, TR8_AREA_PATTERN, 0);          /* destination: working copy */
    TR8_FN_COPY(ctx, TR8_AREA_PATTERN, n, 0);           /* source: pattern p = slot n */
    TR8_FN_COPY_CTX(ctx, TR8_AREA_PTN2, 0);
    TR8_FN_COPY(ctx, TR8_AREA_PTN2, n, 0);
    setup = area_slot(TR8_AREA_SETUP, 0);
    setup[TR8_SETUP_PATTERN] = (uint32_t)p;
    setup[TR8_SETUP_DISPLAY] = (uint32_t)p;
}

/* Replaces "bl FUN_6000E404" at 0x60009614: choose the variation of this pass and its content. */
void chain_var(void *obj)
{
    int len = clen();
    if (!len || TR8_SEQ_VARI != 2) {           /* no chain, or the panel selected A or B */
        TR8_FN_VARIATION(obj);
        return;
    }
    int pos = chain_wrapping ? (chain_pos + 1) % len : 0;
    int cur = (int)(area_slot(TR8_AREA_SETUP, 0)[TR8_SETUP_PATTERN] & 0xF);
    chain_pos = (uint8_t)pos;
    bar_fill(pos == cur ? 0 : pos + 1);        /* the bar's own step content */
    TR8_SEQ_VARIATION = (cbits() >> pos) & 1;
    TR8_FN_APPLY(obj);
}

/* Replaces "bl FUN_600095F0" at 0x600098CA (pattern wrap). */
void chain_wrap(void *obj)
{
    chain_wrapping = 1;
    TR8_FN_RESTART(obj);
    chain_wrapping = 0;
}

int chain_pad_c(int pad);

/* Replaces "bl FUN_60013168" at 0x600199F6 (step pad branch of FUN_6001961E, id still in r6). */
__attribute__((naked)) void chain_pad(void)
{
    __asm__("mov r0, r6\n\tb chain_pad_c\n");
}

/* A or B + pad: paint bar n and make its pattern the one TR-REC edits. A+B + pad: chain length.
 * A+B+CLEAR + pad: chain off. a = VARIATION A held, b = VARIATION B held. */
/* In the second free region (link.ld): the first one is full. */
__attribute__((section(".text.far"))) static void chain_edit(int pad, int a, int b)
{
    int n = pad + 1;                           /* pad 1..16 */
    if (a && b) {
        if (TR8_BTN_HELD(TR8_BTN_CLEAR) == 1) {
            TR8_PTN2_SET(0, CHAIN_LEN, 0);
            show_len(0);
        } else {
            TR8_PTN2_SET(0, CHAIN_LEN, n);
            show_len(n);
        }
        return;
    }

    uint32_t bits = cbits();                   /* A or B + pad: paint one bar */
    int len = clen();
    if (b)
        bits |= 1u << pad;
    else
        bits &= ~(1u << pad);
    if (n > len)
        len = n;

    /* bar_switch saves the pattern we leave (with the song as it stands) and loads the bar's
     * pattern, whose own chain replaces ours, so the song is written again afterwards. */
    bar_switch(n);
    TR8_PTN2_SET(0, CHAIN_BITS, (int)bits);
    TR8_PTN2_SET(0, CHAIN_LEN, len);
    volatile uint32_t *s = bar_fill(0);
    s[0] = TR8_SEQ_VARI = (uint32_t)(b ? 1 : 0);   /* edit this variation now */
    TR8_SEQ_VARIATION = s[0];
    TR8_FN_APPLY((void *)TR8_PTN_STRUCT);
    show_bar(n, b);
}

/* Replaces "bl FUN_60013B34" at 0x60013842: button press, id in r0, held bit already set.
 * Runs before the screen, so this is the first code that can take the pad. */
int chain_press(int id)
{
    if ((unsigned)id < 16) {
        int a = TR8_BTN_HELD(TR8_BTN_VARI_A) == 1;
        int b = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1;
        if ((a || b) && TR8_BTN_HELD(TR8_BTN_LAST_STEP) != 1) {
            chain_edit(id, a, b);
            chain_swallow |= (uint16_t)(1u << id);
            return 1;                          /* taken: the screen never sees this pad */
        }
    }
    return TR8_FN_BTN_PRESS(id);
}

/* Replaces "bl FUN_60013B56" at 0x600137D2: button release, id in r0. */
int chain_release(int id)
{
    if ((unsigned)id < 16 && (chain_swallow & (1u << id))) {
        chain_swallow &= (uint16_t)~(1u << id);
        return 0;                              /* the press was taken: swallow the release too */
    }
    return TR8_FN_BTN_RELEASE(id);
}

/* In the second free region (link.ld): the first one is full. */
__attribute__((section(".text.far"))) int chain_pad_c(int pad)
{
    int a = TR8_BTN_HELD(TR8_BTN_VARI_A) == 1; /* VARIATION A */
    int b = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1; /* VARIATION B */

    if (!a && !b)                              /* normal pad: return the stock condition */
        return TR8_BTN_HELD(TR8_BTN_LAST_STEP) == 1;
    if (TR8_BTN_HELD(TR8_BTN_LAST_STEP) == 1)  /* LAST STEP wins (also the poly gesture) */
        return 1;

    chain_edit(pad, a, b);
    return 0;
}
