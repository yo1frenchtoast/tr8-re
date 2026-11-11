/*
 * TR-8 v1.61 motion recording prototype (RAM only, one global motion buffer).
 *
 * Rules:
 *  - Default build (works on the unit, hardware test 5):
 *      TR-REC (button 0x11) held + sequencer running + knob moved -> value stored at the current step.
 *      CLEAR  (button 0x1C) held + knob moved (running or not)    -> that control's lane is erased.
 *  - -DMOTION_MODE: record while TR-REC mode is active (HMI Setup[0] == 0); erase = knob moved
 *    while stopped in TR-REC mode. -DMOTION_DIAG: record always; erase = knob moved while stopped.
 *  - Otherwise the knob acts as usual (live tweak), the motion is kept and still replayed.
 *  - On each step, every lane with a value at this step is replayed by posting the same
 *    event the ADC scan posts ({0x0B, id, value}), so the normal knob path applies it.
 *  - A lane is not replayed for 2 steps after the user touched its knob (no fight while recording).
 *  - Slots: 16 steps x 2 variations (A/B) per control, 49 controls.
 *  - The sequencer counter (+0x18) counts half steps: step = counter >> 1.
 *  - The per-step function runs twice per step (FUN_6000981E also calls FUN_600097DA):
 *    a lane is replayed only once per step.
 *  - No panel boot mode (0x6007E574) or knob redirect (0x6007E580) test: those belong to the
 *    FUN_6001446A path, which normal play does not use (hardware test 4, docs/MOTION.md).
 *
 * Hooks (see docs/MOTION.md):
 *  - motion_knob replaces "bl FUN_60013242" at 0x600138C8: HMI event 10 (knob) handler, before the
 *    active screen and the global control->parameter table FUN_60013F6A see the event.
 *    (The first prototype hooked FUN_6001446A, which only some screens use: nothing was recorded.)
 *  - motion_step replaces "bl FUN_6000978e" at 0x60009862 and 0x60009808 (sequencer, once per step).
 */
#include <stdint.h>

#define NCTRL 49
#define NSLOT 32

/* Firmware addresses (v1.61 application, loaded at 0x60000000). Thumb bit set on functions. */
#define SEQ_RUNNING   (*(volatile uint8_t  *)0x6007E102)   /* sequencer state +0x02          */
#define SEQ_STEP      (*(volatile uint32_t *)0x6007E118)   /* sequencer state +0x18          */
#define SEQ_VARIATION (*(volatile uint32_t *)0x6012FA74)   /* pattern state +0x10 (0 / not 0)*/

typedef int      (*screen_fn)(int screen, const int16_t *ev);
typedef uint64_t (*step_fn)(void *p, int step);
typedef void     (*post_fn)(int id, int value);
typedef int      (*getprm_fn)(void *db, int idx, int def);
typedef int      (*held_fn)(unsigned id);

#define ORIG_KNOB ((screen_fn)0x60013243) /* FUN_60013242: pass the event to the active screen */
#define ORIG_STEP ((step_fn)0x6000978F)   /* FUN_6000978e: original per-step call             */
#define POST_CTRL ((post_fn)0x60000CC1)   /* ADC change callback: posts {0x0B, id, value}     */
#define SETUP_GET ((getprm_fn)0x6001B12F) /* FUN_6001b12e: read HMI Setup parameter           */
#define HMI_SETUP ((void *)0x60149F38)    /* HMI Setup database object                        */
#define MODE_TR_REC 0                     /* Setup[0]: 0 TR-REC, 3 INST REC (FUN_6001961e)    */
#define BTN_HELD  ((held_fn)0x60013169)   /* FUN_60013168: 1 while button id is held          */
#define BTN_TR_REC 0x11                   /* TR-REC button (confirmed, hardware test 5)       */
#define BTN_CLEAR  0x1C                   /* CLEAR button (clear-row modifier in FUN_6001961E)*/

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
    return SETUP_GET(HMI_SETUP, 0, 0) == MODE_TR_REC;
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
