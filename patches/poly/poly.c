/*
 * TR-8 v1.61 per-instrument pattern length ("polyrhythm"), test build: fixed lengths, RAM only.
 *
 * Each instrument with a length L != 0 has its own play head that advances once per step and
 * wraps after L steps, independent of the pattern's last step. Instruments with L = 0 follow
 * the pattern as before. Heads restart at 0 when the sequencer starts or stops.
 *
 * How (docs/FINDINGS.md section 7, "Step trigger"):
 *   The trigger function FUN_600262F2(P, step, flam) owns the play position P[0x66]. With
 *   step = -1 it advances it (when P[1] != 0, wrap after P[3]), then tests ONE bit
 *   (1 << step) in each instrument mask: P[0x21 + i] (steps), P[0x42 + i] (accents),
 *   P[0x67 + i] (flams, only with flam != 0). Return value: bit i = instrument i fired.
 *   poly_trig predicts the step the firmware will use, puts bit pos[i] of each mask of a
 *   poly instrument at that step, calls the firmware, then restores the masks.
 *   Masks are only restored if nobody changed them meanwhile (an edit from the panel wins).
 *
 * Hooks (tools/tr8patch.py):
 *   poly_trig replaces "bl FUN_600262F2" at 0x60009800, 0x6000985A, 0x60009884 (step advance)
 *             and 0x60009A50 (delayed flam trigger);
 *   poly_run  replaces "bl FUN_60026894" at 0x6000966E (start) and 0x600096AE (stop).
 *
 * Instrument order: BD SD LT MT HT RS HC CH OH CC RC.
 */
#include "tr8_v161.h"

#define NI 11

#ifndef POLY_LENGTHS                              /* test lengths: RS 5 steps, CH 3 steps */
#define POLY_LENGTHS { 0, 0, 0, 0, 0, 5, 0, 3, 0, 0, 0 }
#endif

uint8_t poly_len[NI] = POLY_LENGTHS;              /* 0 = follow the pattern, else 1..16 */
uint8_t poly_pos[NI];
uint8_t poly_reset = 1;

static const uint8_t rows[3] = { TR8_PL_INST, TR8_PL_ACC, TR8_PL_FLAM };

/* back = 0: save each mask of a poly instrument and replace bit s with bit pos[i].
 * back = 1: put the saved mask back, unless the mask changed since (a panel edit wins). */
static void swap(volatile uint32_t *p, int s, uint32_t *saved, int back)
{
    for (int i = 0; i < NI; i++) {
        if (!poly_len[i])
            continue;
        for (int k = 0; k < 3; k++) {
            volatile uint32_t *m = &p[rows[k] + i];
            uint32_t *v = &saved[i * 3 + k];
            uint32_t o = back ? *v : *m;
            uint32_t t = (o & ~(1u << s)) | (((o >> poly_pos[i]) & 1u) << s);
            if (!back) {
                *v = o;
                *m = t;
            } else if (*m == t) {
                *m = o;
            }
        }
    }
}

void poly_run(void *p, int a, int run)
{
    poly_reset = 1;
    TR8_FN_PLAYER_RUN(p, a, run);
}

uint32_t poly_trig(volatile uint32_t *p, int step, int flam)
{
    int s = step, i;
    if (step == -1) {
        s = (int)p[TR8_PL_POS];
        if (p[TR8_PL_RUN]) {
            s = (s >= (int)p[TR8_PL_LAST]) ? 0 : s + 1;   /* what the firmware will do */
            for (i = 0; i < NI; i++) {
                int n = poly_pos[i] + 1;
                poly_pos[i] = (poly_reset || n >= poly_len[i]) ? 0 : n;
            }
            poly_reset = 0;
        }
        if (*(volatile int16_t *)((volatile uint8_t *)p + TR8_PL_SCATTER) != -1)
            s = -1;                               /* scatter reorders steps: leave it alone */
    }
    if ((unsigned)s > 15)
        return TR8_FN_TRIGGER(p, step, flam);

    uint32_t saved[NI * 3];
    swap(p, s, saved, 0);
    uint32_t r = TR8_FN_TRIGGER(p, step, flam);
    swap(p, s, saved, 1);
    return r;
}
