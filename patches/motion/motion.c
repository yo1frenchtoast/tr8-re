/*
 * TR-8 v1.61 motion recording (RAM only, one global motion buffer). Works on a real unit.
 *
 * Rules (default build):
 *   TR-REC held + sequencer running + control moved -> value stored at the current step.
 *   CLEAR held + control moved (running or stopped)  -> that control's motion is erased (A and B).
 *   No button held                                   -> live change; the motion is kept and replayed.
 * Variants: -DMOTION_MODE records while TR-REC mode is active (Setup[0] == 0) and erases by moving
 * a control while stopped in that mode; -DMOTION_DIAG records always (diagnostic build).
 *
 * Replay: on each step, every lane with a value at this step is posted as the same event the ADC
 * scan posts ({0x0B, id, value}), so the normal knob path applies it (sound, display).
 * A lane is not replayed for 2 steps after it was recorded, so playback does not fight the hand.
 * Storage: 49 controls x (16 steps x 2 variations) values plus a 32-bit mask per control.
 *
 * Firmware facts this code depends on (docs/FINDINGS.md, docs/MOTION.md "History"):
 *   - the sequencer counter counts half steps: step = counter >> 1;
 *   - the per-step function usually runs twice per step: replay once per slot (m_last);
 *   - our own replay comes back through motion_knob: the pending flag/value filters that echo.
 *
 * Hooks (tools/tr8patch.py):
 *   motion_knob replaces "bl FUN_60013242" at 0x600138C8 (HMI knob event, before the active screen
 *               and the global control -> parameter table);
 *   motion_step replaces "bl FUN_6000978E" at 0x60009862 and 0x60009808 (once per step).
 */
#include "tr8_v161.h"

#define NCTRL TR8_NCTRL
#define NSLOT 32                                  /* 16 steps x 2 variations */

#define SEQ_RUNNING   TR8_SEQ_RUNNING
#define SEQ_STEP      TR8_SEQ_COUNTER
#define SEQ_VARIATION TR8_SEQ_VARIATION
#define ORIG_KNOB     TR8_FN_SCREEN_EVENT
#define ORIG_STEP     TR8_FN_STEP
#define POST_CTRL     TR8_POST_CTRL
#define BTN_HELD      TR8_BTN_HELD
#define BTN_TR_REC    TR8_BTN_TR_REC
#define BTN_CLEAR     TR8_BTN_CLEAR

/* Large table in the second cave region; everything else in the first one. */
__attribute__((section(".cave_b"))) uint8_t m_val[NCTRL][NSLOT];
uint32_t m_mask[NCTRL];
uint8_t  m_hold[NCTRL];
uint8_t  m_pend[NCTRL];
uint8_t  m_pendval[NCTRL];
uint8_t  m_last = 0xFF;                           /* slot replayed last, 0xFF = none */

static inline int cur_slot(void)
{
    return (SEQ_VARIATION ? 16 : 0) + (int)((SEQ_STEP >> 1) & 15);
}

static inline int rec_on(void)
{
#if defined(MOTION_DIAG)
    return 1;
#elif defined(MOTION_MODE)
    return TR8_SETUP_GET(TR8_HMI_SETUP, TR8_SETUP_MODE, 0) == 0;   /* 0 = TR-REC */
#else
    return BTN_HELD(BTN_TR_REC);
#endif
}

static inline int erase_on(void)
{
#if defined(MOTION_DIAG) || defined(MOTION_MODE)
    return !SEQ_RUNNING && rec_on();
#else
    return BTN_HELD(BTN_CLEAR);
#endif
}

/* ev = HMI event {s16 10, s16 control id, s16 value} */
int motion_knob(int screen, const int16_t *ev)
{
    int id = ev[1], value = ev[2];
    if ((unsigned)id < NCTRL) {
        if (m_pend[id] && m_pendval[id] == (uint8_t)value) {
            m_pend[id] = 0;                       /* echo of our own playback event */
        } else {
            m_pend[id] = 0;
            if (erase_on()) {
                m_mask[id] = 0;                   /* erase this lane (A and B) */
            } else if (SEQ_RUNNING && rec_on()) {
                int s = cur_slot();
                m_val[id][s] = (uint8_t)value;
                m_mask[id] |= 1u << s;
                m_hold[id] = 2;
            }                                     /* else live tweak only, keep the motion */
        }
    }
    return ORIG_KNOB(screen, ev);
}

void motion_step(void *p, int step)
{
    ORIG_STEP(p, step);
    if (!SEQ_RUNNING) {
        m_last = 0xFF;
        return;
    }
    int s = cur_slot();
    if (s == m_last)
        return;                                   /* second call for the same step */
    m_last = (uint8_t)s;
    uint32_t bit = 1u << s;
    for (int id = 0; id < NCTRL; id++) {
        if (m_hold[id]) { m_hold[id]--; continue; }
        if (m_mask[id] & bit) {
            uint8_t v = m_val[id][s];
            m_pendval[id] = v;
            m_pend[id] = 1;
            POST_CTRL(id, v);
        }
    }
}
