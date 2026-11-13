/*
 * TR-8 v1.61 per-instrument pattern length ("polyrhythm"), saved with each pattern.
 *
 * Panel: hold LAST STEP + an instrument button and press step pad n -> that instrument loops
 * over n steps. The same gesture with the same pad again -> back to the pattern length.
 * LAST STEP + pad without an instrument button keeps its normal meaning (pattern length).
 * While LAST STEP + an instrument with a length are held, the step LEDs show that instrument:
 * steps inside its length lit (green, like the pattern length view), its play position, the
 * rest off.
 *
 * Each instrument with a length L != 0 has its own play head that advances once per step and
 * wraps after L steps, independent of the pattern's last step. Instruments with L = 0 follow
 * the pattern as before. Heads restart at 0 when the sequencer starts or stops.
 *
 * The heads are not stored: poly_n counts the advances since the last start or stop, and the
 * head of instrument i is (poly_n - 1) % L. The tick also runs in the panel task (TAP +
 * START/STOP restarts the pattern from there, docs/POLY.md "Tasks"), so poly_n is the only
 * state two tasks write: the advance is an atomic increment (LDREX/STREX; a task switch clears
 * the exclusive monitor, so an interrupted increment retries) and start/stop is one word store.
 * Whatever the interleaving, the heads equal the number of advances, like the firmware's own
 * position.
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
 *   poly_run  replaces "bl FUN_60026894" at 0x6000966E (start) and 0x600096AE (stop);
 *   poly_last replaces "bl FUN_6001B8D6" at 0x60019A10 (step pad pressed with LAST STEP held);
 *   poly_led  replaces "bl FUN_6001774E" at 0x60016438 (step LED loop of the LAST STEP view);
 *   poly_lsled replaces the tail call "b.w FUN_60017722" at 0x60016B56 (LAST STEP button LED).
 *
 * Storage: the length of instrument i is the Ptn2 parameter of index TR8_PTN2_SPARE + i
 * (global id 0x12B + i), one of the unnamed pattern parameters that the firmware stores
 * with every pattern but never uses. The gesture writes it with the firmware's own Ptn2
 * setter, so the pattern is saved like after any edit; the player reads the current
 * pattern's value from RAM. Values outside 1..16 mean "follow the pattern".
 *
 * Instrument order: BD SD LT MT HT RS HC CH OH CC RC.
 */
#include "tr8_v161.h"

#define NI 11

volatile uint32_t poly_n;     /* advances since the last start or stop */

/* Length of instrument i in the current pattern: 0 = follow the pattern, else 1..16. */
static int len(int i)
{
    uint32_t v = TR8_PTN2_CUR[TR8_PTN2_SPARE + i];
    return v <= 16 ? (int)v : 0;
}

/* Head of instrument i after n advances (0 before the first one or without a length). */
static int head(int i, uint32_t n)
{
    int l = len(i);
    return n && l ? (int)((n - 1) % (uint32_t)l) : 0;
}

static const uint8_t rows[3] = { TR8_PL_INST, TR8_PL_ACC, TR8_PL_FLAM };

/* back = 0: save each mask of a poly instrument and replace bit s with bit pos[i].
 * back = 1: put the saved mask back, unless the mask changed since (a panel edit wins). */
static void swap(volatile uint32_t *p, int s, uint32_t *saved, int back, uint32_t n)
{
    for (int i = 0; i < NI; i++) {
        if (!len(i))
            continue;
        int h = head(i, n);
        for (int k = 0; k < 3; k++) {
            volatile uint32_t *m = &p[rows[k] + i];
            uint32_t *v = &saved[i * 3 + k];
            uint32_t o = back ? *v : *m;
            uint32_t t = (o & ~(1u << s)) | (((o >> h) & 1u) << s);
            if (!back) {
                *v = o;
                *m = t;
            } else if (*m == t) {
                *m = o;
            }
        }
    }
}

void poly_last(void *obj, int pad)
{
    static char txt[5] = "L   ";
    int n = pad + 1, l = -1;
    for (int i = 0; i < NI; i++) {
        if (TR8_BTN_HELD(TR8_BTN_INST(i)) != 1)
            continue;
        l = (len(i) == n) ? 0 : n;
        TR8_PTN2_SET(0, TR8_PTN2_SPARE + i, l);
    }
    if (l < 0) {                                  /* no instrument held: pattern last step */
        TR8_FN_SET_LAST(obj, pad);
        return;
    }
    txt[1] = l ? ' ' : 'O';                       /* "L 12", "L  3" or "LOFF" */
    txt[2] = l ? (l >= 10 ? '1' : ' ') : 'F';
    txt[3] = l ? '0' + l % 10 : 'F';
    TR8_DISPLAY_TEXT(0, txt);
}

/* Step LED loop of the LAST STEP view (FUN_60016386 runs it only while LAST STEP is held). */
void poly_led(int led, unsigned colour)
{
    for (int i = 0; i < NI; i++) {
        int l = len(i);
        if (!l || TR8_BTN_HELD(TR8_BTN_INST(i)) != 1)
            continue;
        int u = led - TR8_LED_STEP(0);
        colour = (TR8_SEQ_RUNNING && u == head(i, poly_n)) ? TR8_COL_PLAY
               : u < l                                  ? TR8_COL_IN
               :                                          TR8_COL_OFF;
        break;
    }
    TR8_FN_STEP_LED(led, colour);
}

/* Replaces the tail call "b.w FUN_60017722" at 0x60016B56 at the end of the panel repaint
 * FUN_600169A4 (bit 0x02). With LAST STEP released it sets LED 9 (lit if the pattern is shorter
 * than 16 steps); with LAST STEP held the same call sets LED 7. In TR-REC, when the selected row
 * is an instrument with its own length, LAST STEP blinks instead. Panel task. A row press
 * requests this repaint (FUN_6001961E ORs 0x16 into the panel bits). */
void poly_lsled(int id, int a, int b)
{
    if (id == TR8_LED_LASTSTEP &&
        TR8_SETUP_GET(TR8_HMI_SETUP, TR8_SETUP_MODE, 0) == 0) {
        int t = TR8_SETUP_GET(TR8_HMI_SETUP, TR8_SETUP_ROW, 0) - 4;   /* button order */
        if (t >= 0 && t < NI && len(t == 5 ? 6 : t == 6 ? 5 : t)) {  /* RS/HC swapped */
            a = 1;
            b = 0;                                /* blink flag */
        }
    }
    TR8_FN_LED3(id, a, b);
}

void poly_run(void *p, int a, int run)
{
    poly_n = 0;                                   /* the next advance is every head's step 1 */
    TR8_FN_PLAYER_RUN(p, a, run);
}

uint32_t poly_trig(volatile uint32_t *p, int step, int flam)
{
    int s = step;
    uint32_t n = poly_n;                          /* a flam hit uses the heads of the last advance */
    if (step == -1) {
        s = (int)p[TR8_PL_POS];
        if (p[TR8_PL_RUN]) {
            s = (s >= (int)p[TR8_PL_LAST]) ? 0 : s + 1;   /* what the firmware will do */
            n = __atomic_add_fetch(&poly_n, 1, __ATOMIC_RELAXED);
        }
        if (*(volatile int16_t *)((volatile uint8_t *)p + TR8_PL_SCATTER) != -1)
            s = -1;                               /* scatter reorders steps: leave it alone */
    }
    if ((unsigned)s > 15)
        return TR8_FN_TRIGGER(p, step, flam);

    uint32_t saved[NI * 3];
    swap(p, s, saved, 0, n);
    uint32_t r = TR8_FN_TRIGGER(p, step, flam);
    swap(p, s, saved, 1, n);
    return r;
}
