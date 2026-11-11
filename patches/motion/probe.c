/*
 * Hardware probe for the motion patch: same hooks as motion.c, audible effects instead of motion.
 *
 *  1. Capture hook + "running" flag: while the sequencer is STOPPED, knob events are swallowed
 *     (knobs do nothing). While it runs, knobs work normally.
 *  2. Step hook + replay path: while the sequencer runs, the last touched control is posted
 *     with 0 and 255 on alternate steps (through the same ADC callback as a real knob).
 *
 * Expected on the unit if every link works: knobs dead when stopped; start, touch one knob,
 * release it: that parameter jumps between minimum and maximum on every step.
 */
#include "tr8_v161.h"

#define SEQ_RUNNING TR8_SEQ_RUNNING
#define SEQ_STEP    TR8_SEQ_COUNTER
#define ORIG_KNOB   TR8_FN_SCREEN_EVENT
#define ORIG_STEP   TR8_FN_STEP
#define POST_CTRL   TR8_POST_CTRL

uint8_t m_last = 0xFF;      /* last step seen (dedupe: the step function runs twice per step) */
uint8_t p_id   = 0xFF;      /* last control touched by the user */
uint8_t p_ph;               /* 0 / 1 alternate */

int motion_knob(int screen, const int16_t *ev)
{
    if (!SEQ_RUNNING)
        return 1;                                 /* swallowed: knobs dead while stopped */
    if ((unsigned)ev[1] < 49 && ev[2] != 0 && ev[2] != 255)
        p_id = (uint8_t)ev[1];                    /* real move (not our 0/255 posts) */
    return ORIG_KNOB(screen, ev);
}

void motion_step(void *p, int step)
{
    ORIG_STEP(p, step);
    if (!SEQ_RUNNING) { m_last = 0xFF; return; }
    uint8_t s = (uint8_t)(SEQ_STEP >> 1);
    if (s == m_last) return;
    m_last = s;
    if (p_id < 49) {
        p_ph ^= 1;
        POST_CTRL(p_id, p_ph ? 255 : 0);
    }
}
