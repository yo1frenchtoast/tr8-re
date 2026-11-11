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
#include <stdint.h>

#define SEQ_RUNNING (*(volatile uint8_t  *)0x6007E102)
#define SEQ_STEP    (*(volatile uint32_t *)0x6007E118)

typedef int      (*screen_fn)(int screen, const int16_t *ev);
typedef uint64_t (*step_fn)(void *p, int step);
typedef void     (*post_fn)(int id, int value);

#define ORIG_KNOB ((screen_fn)0x60013243)
#define ORIG_STEP ((step_fn)0x6000978F)
#define POST_CTRL ((post_fn)0x60000CC1)

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
