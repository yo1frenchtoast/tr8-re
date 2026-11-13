/*
 * Hardware probe for the bar chain patch: same hook sites, display instead of edits.
 * Flash this build when a gesture does nothing, to see which link is missing.
 *
 *  1. Pattern restart (chain_var): calls the stock variation code, then on a start (not on
 *     every pattern wrap) shows "St" VARI effective, e.g. "St20" = panel VARI 2 (A+B) and the
 *     effective variation of the new pass 0 (A). VARI is Ptn parameter 0xC3, loaded into the
 *     player struct by FUN_6000E0FE just before this call.
 *
 *  2. Every button press (chain_press): shows pad number, which variation buttons the firmware
 *     reports as held, and whether LAST STEP is held:
 *
 *        " 1A-"   pad 1, VARIATION A held
 *        "12B-"   pad 12, VARIATION B held
 *        " 3C-"   pad 3, both variation buttons held
 *        " 3CL"   pad 3, both held and LAST STEP held
 *        " 3--"   pad 3, nothing held: the press hook runs and sees no modifier
 *
 *     This is the site that decides the gesture: 0x60013B34 is called for every press before
 *     the screen, while the old pad hook inside FUN_6001961E only runs when the screen lets a
 *     pad press through (LAST STEP + pad). A pad with A/B held is shown and swallowed; a plain
 *     pad or LAST STEP + pad goes to the firmware first and the text is written afterwards, so
 *     it is the last thing written to the display. The text is shown but nothing is edited: no
 *     step, no pattern length, no chain is ever written by this build.
 */
#include "tr8_v161.h"

uint8_t chain_pos;
uint8_t chain_wrapping;
uint16_t chain_swallow;

/* Same names and sites as chain.c so the patcher entry does not change. */
void chain_var(void *obj)
{
    TR8_FN_VARIATION(obj);                 /* stock behaviour, no chain */
    if (!chain_wrapping) {
        static char txt[5];
        uint32_t vari = TR8_SEQ_VARI, eff = TR8_SEQ_VARIATION;
        txt[0] = 'S';
        txt[1] = 't';
        txt[2] = (char)('0' + (vari < 10 ? vari : 9));
        txt[3] = (char)('0' + (eff < 10 ? eff : 9));
        TR8_DISPLAY_TEXT(0, txt);
    }
}

void chain_wrap(void *obj)
{
    chain_wrapping = 1;
    TR8_FN_RESTART(obj);
    chain_wrapping = 0;
}

static void show_pad(int pad, int a, int b, int last)
{
    static char txt[5];
    int n = pad + 1;

    txt[0] = n >= 10 ? '1' : ' ';
    txt[1] = (char)('0' + n % 10);
    txt[2] = a && b ? 'C' : a ? 'A' : b ? 'B' : '-';
    txt[3] = last ? 'L' : '-';
    TR8_DISPLAY_TEXT(0, txt);
}

/* Replaces "bl FUN_60013B34" at 0x60013842: button press, id in r0. */
int chain_press(int id)
{
    if ((unsigned)id < 16) {
        int a = TR8_BTN_HELD(TR8_BTN_VARI_A) == 1;
        int b = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1;
        int last = TR8_BTN_HELD(TR8_BTN_LAST_STEP) == 1;

        if ((a || b) && !last) {
            show_pad(id, a, b, last);
            chain_swallow |= (uint16_t)(1u << id);
            return 1;                      /* taken, like the chain build */
        }
        int r = TR8_FN_BTN_PRESS(id);      /* plain pad: the firmware answers it */
        show_pad(id, a, b, last);          /* then show what was seen */
        return r;
    }
    return TR8_FN_BTN_PRESS(id);
}

/* Replaces "bl FUN_60013B56" at 0x600137D2: button release, id in r0. */
int chain_release(int id)
{
    if ((unsigned)id < 16 && (chain_swallow & (1u << id))) {
        chain_swallow &= (uint16_t)~(1u << id);
        return 0;
    }
    return TR8_FN_BTN_RELEASE(id);
}

int chain_pad_c(int pad);

/* Replaces "bl FUN_60013168" at 0x600199F6 (LAST STEP check of the pad branch). */
__attribute__((naked)) void chain_pad(void)
{
    __asm__("mov r0, r6\n\tb chain_pad_c\n");
}

int chain_pad_c(int pad)
{
    show_pad(pad, TR8_BTN_HELD(TR8_BTN_VARI_A) == 1, TR8_BTN_HELD(TR8_BTN_VARI_B) == 1,
             TR8_BTN_HELD(TR8_BTN_LAST_STEP) == 1);
    return 0;                              /* handled and ignored: never edit anything */
}
