/*
 * Hardware probe for the bar chain patch: same hook sites, display instead of edits.
 * Flash this build when a gesture does nothing, to see which link is missing.
 *
 *  1. Pattern restart (chain_var): calls the stock variation code, then on a start (not on
 *     every pattern wrap) shows "St" VARI effective, e.g. "St20" = panel VARI 2 (A+B) and the
 *     effective variation of the new pass 0 (A). VARI is Ptn parameter 0xC3, loaded into the
 *     player struct by FUN_6000E0FE just before this call.
 *
 *  2. Any step pad (chain_pad): shows the pad number, which variation buttons the firmware
 *     reports as held, and whether LAST STEP is held:
 *
 *        " 1A-"   pad 1, VARIATION A held
 *        "12B-"   pad 12, VARIATION B held
 *        " 3C-"   pad 3, both variation buttons held
 *        " 3CL"   pad 3, both held and LAST STEP held
 *        " 3--"   pad 3, nothing held (the hook runs, but the modifier is not seen)
 *
 *     The pad is always reported as handled and ignored, so this build never edits a step,
 *     never sets the pattern length and never writes the chain.
 *
 * Nothing appears on a pad press in pattern-select mode: the button handler returns before
 * this branch (0x60019622 -> 0x600196C2) while that screen is open.
 */
#include "tr8_v161.h"

uint8_t chain_pos;
uint8_t chain_wrapping;

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

int chain_pad_c(int pad);

__attribute__((naked)) void chain_pad(void)
{
    __asm__("mov r0, r6\n\tb chain_pad_c\n");
}

int chain_pad_c(int pad)
{
    static char txt[5];
    int a = TR8_BTN_HELD(TR8_BTN_VARI_A) == 1;
    int b = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1;
    int last = TR8_BTN_HELD(TR8_BTN_LAST_STEP) == 1;
    int n = pad + 1;

    txt[0] = n >= 10 ? '1' : ' ';
    txt[1] = (char)('0' + n % 10);
    txt[2] = a && b ? 'C' : a ? 'A' : b ? 'B' : '-';
    txt[3] = last ? 'L' : '-';
    TR8_DISPLAY_TEXT(0, txt);
    return 0;                              /* handled and ignored: never edit anything */
}
