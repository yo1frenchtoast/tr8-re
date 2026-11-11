/*
 * TR-8 v1.61 motion recording prototype (RAM only, one global motion buffer).
 *
 * Rules:
 *  - Recording and erasing happen only in TR-REC mode (Setup parameter 0 == 0).
 *  - TR-REC, sequencer running + knob moved  -> value stored at the current step of that lane.
 *  - TR-REC, sequencer stopped + knob moved  -> that control's lane is erased.
 *  - Other modes: the knob acts as usual (live tweak), the motion is kept and still replayed.
 *  - On each step, every lane with a value at this step is replayed by posting the same
 *    event the ADC scan posts ({0x0B, id, value}), so the normal knob path applies it.
 *  - A lane is not replayed for 2 steps after the user touched its knob (no fight while recording).
 *  - Slots: 16 steps x 2 variations (A/B) per control, 49 controls.
 *  - The sequencer counter (+0x18) counts half steps: step = counter >> 1.
 *  - The per-step function runs twice per step (FUN_6000981E also calls FUN_600097DA):
 *    a lane is replayed only once per step.
 *  - Build with -DMOTION_DIAG for a diagnostic variant without any mode condition.
 *
 * Hooks (see docs/MOTION.md):
 *  - motion_knob replaces "bl FUN_6001446a" at 0x60014204 (panel task, default knob handler).
 *  - motion_step replaces "bl FUN_6000978e" at 0x60009862 and 0x60009808 (sequencer, once per step).
 */
#include <stdint.h>

#define NCTRL 49
#define NSLOT 32

/* Firmware addresses (v1.61 application, loaded at 0x60000000). Thumb bit set on functions. */
#define SEQ_RUNNING   (*(volatile uint8_t  *)0x6007E102)   /* sequencer state +0x02          */
#define SEQ_STEP      (*(volatile uint32_t *)0x6007E118)   /* sequencer state +0x18          */
#define SEQ_VARIATION (*(volatile uint32_t *)0x6012FA74)   /* pattern state +0x10 (0 / not 0)*/
#define PANEL_MODE    (*(volatile int32_t  *)0x6007E574)   /* read by FUN_60014054           */
#define KNOB_REDIRECT (*(volatile uint8_t  *)0x6007E580)   /* FUN_6001465c(DAT_600143c4)     */

typedef void     (*knob_fn)(void *ctx, int id, int value);
typedef uint64_t (*step_fn)(void *p, int step);
typedef void     (*post_fn)(int id, int value);
typedef int      (*getprm_fn)(void *db, int idx, int def);

#define ORIG_KNOB ((knob_fn)0x6001446B)   /* FUN_6001446a: control id -> HMI parameter        */
#define ORIG_STEP ((step_fn)0x6000978F)   /* FUN_6000978e: original per-step call             */
#define POST_CTRL ((post_fn)0x60000CC1)   /* ADC change callback: posts {0x0B, id, value}     */
#define SETUP_GET ((getprm_fn)0x6001B12F) /* FUN_6001b12e: read HMI Setup parameter           */
#define HMI_SETUP ((void *)0x60149F38)    /* HMI Setup database object                        */
#define MODE_TR_REC 0                     /* Setup[0]: 0 TR-REC, 3 INST REC (FUN_6001961e)    */

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

void motion_knob(void *ctx, int id, int value)
{
#ifdef MOTION_DIAG
    if ((unsigned)id < NCTRL) {
#else
    if ((unsigned)id < NCTRL && PANEL_MODE <= 3) {
#endif
        if (m_pend[id] && m_pendval[id] == (uint8_t)value) {
            m_pend[id] = 0;                       /* echo of our own playback event */
        } else {
            m_pend[id] = 0;
#ifdef MOTION_DIAG
            if (0) {
#else
            if (SETUP_GET(HMI_SETUP, 0, 0) != MODE_TR_REC) {
#endif
                /* not TR-REC: live tweak only, keep the motion */
            } else if (SEQ_RUNNING) {
                int s = cur_slot();
                m_val[id][s] = (uint8_t)value;
                m_mask[id] |= 1u << s;
                m_hold[id] = 2;
            } else {
                m_mask[id] = 0;                   /* stopped: erase this lane */
            }
        }
    }
    ORIG_KNOB(ctx, id, value);
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
#ifndef MOTION_DIAG
    if (KNOB_REDIRECT || PANEL_MODE > 3)
        return;
#endif
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
