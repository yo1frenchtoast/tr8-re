/*
 * TR-8 v1.61 bar chain: play a pattern as a sequence of more than two bars.
 *
 * Panel: hold VARIATION A and press step pad n -> bar n plays variation A.
 *        hold VARIATION B and press step pad n -> bar n plays variation B.
 *        hold VARIATION A + B and press step pad n -> the chain is n bars long.
 *        hold VARIATION A + B + CLEAR and press a pad -> chain off (stock A/B behaviour).
 * The numeric display confirms each step ("  3A", " 12B", "CH 4", "CH12", "CH--").
 *
 * A plain A or B press still selects that variation for editing and playback, exactly as
 * before; A+B plays the chain (stock: alternates A/B, which is the chain A,B).
 *
 * How (docs/CHAIN.md, docs/FINDINGS.md section 7):
 *   FUN_600095F0 restarts the pattern (sequencer start and every pattern wrap). It copies the
 *   panel parameters into the player struct 0x6012FA64, then FUN_6000E404 applies the
 *   variation: if VARI (+0x0c) is 2 it toggles the effective variation (+0x10), else it
 *   stores VARI, then FUN_6000E152 re-applies the step masks to the sound. The last step used
 *   for the new pass is read after that with FUN_600525F8 (LAST_A at +0x14, LAST_B at +0x18),
 *   so the variation has to be set before FUN_600095F0 returns.
 *   chain_var replaces "bl FUN_6000E404" inside FUN_600095F0: with a chain and VARI = 2 it
 *   picks the bar's variation and applies it; otherwise it calls the original.
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
 * Storage: the chain is two Ptn2 parameters of the current pattern, the unnamed ids that no
 * code reads but the firmware stores with every pattern (POLY.md "Storage"):
 *   index 15 (id 0x136): bit n = bar n+1 is B (0 = A)
 *   index 16 (id 0x137): 0 = no chain, 1..16 = number of bars
 * So the chain is saved with the pattern like any other edit. The poly patch uses indices
 * 4..14 (ids 0x12B..0x135) and leaves these two alone.
 */
#include "tr8_v161.h"

#define CHAIN_BITS 15
#define CHAIN_LEN  16

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

/* Replaces "bl FUN_6000E404" at 0x60009614: choose the variation of this pass. */
void chain_var(void *obj)
{
    int len = clen();
    if (!len || TR8_SEQ_VARI != 2) {           /* no chain, or the panel selected A or B */
        TR8_FN_VARIATION(obj);
        return;
    }
    int pos = chain_wrapping ? (chain_pos + 1) % len : 0;
    chain_pos = (uint8_t)pos;
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

/* A or B + pad: paint bar n. A+B + pad: chain length. A+B+CLEAR + pad: chain off.
 * a = VARIATION A held, b = VARIATION B held. */
static void chain_edit(int pad, int a, int b)
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
    if (b)
        bits |= 1u << pad;
    else
        bits &= ~(1u << pad);
    TR8_PTN2_SET(0, CHAIN_BITS, (int)bits);
    if (n > clen())
        TR8_PTN2_SET(0, CHAIN_LEN, n);
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

int chain_pad_c(int pad)
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
