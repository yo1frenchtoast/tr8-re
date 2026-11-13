/*
 * TR-8 v1.61 bar chain: a pattern becomes four bars, each with its own A and B step set.
 *
 * Panel (per pattern; nothing is carried to another pattern):
 *   hold VARIATION A, press pad 1..4 -> bar n is the working copy and plays its A steps.
 *   hold VARIATION B, press pad 1..4 -> the same bar, its B steps.
 *   hold A + B, press pad 1..4       -> the chain is n bars long.
 *   hold A + B + CLEAR, press a pad  -> chain off (stock single-bar A/B).
 *   The numeric display confirms each gesture ("  1A", "  4B", "CH 4", "CH--").
 *
 * So pattern 1 keeps four private bars (A and B steps each), pattern 2 the same, and each
 * pattern's chain is its own 4-bar phrase. A bar that has never been recorded is the pattern
 * itself (its A steps for the A side, its B steps for the B side), so a pattern sounds exactly
 * as before until a bar is edited.
 *
 * How the firmware is made to do this (docs/CHAIN.md, docs/FINDINGS.md section 7):
 *   The working copy of a pattern is area 4 slot 0; TR-REC, the step pads and LAST STEP all
 *   write it. To edit bar n we copy that bar's stored content into slot 0 (masks, LAST_A,
 *   LAST_B, scale, VARI) and the panel is then editing bar n. Selecting a bar saves the one we
 *   leave.
 *   Playback never switches patterns: chain_var replaces "bl FUN_6000E404" inside the restart
 *   FUN_600095F0 (start and every wrap), picks the bar and its A/B side, fills the player struct
 *   0x6012FA64 from the bar's content and applies the masks with FUN_6000E152.
 *   chain_wrap replaces the wrap call (0x600098CA) and marks the restart as a wrap, so a start
 *   begins at bar 1 and a wrap advances one bar.
 *   The gesture lives on the press dispatch (0x60013842, before the screen): the screen takes a
 *   bare pad press, so the global button handler never sees it (see the first hardware build).
 *   chain_release swallows the matching release.
 *   While VARIATION A or B is held, all 16 pads become the bar row (bars 1..4 lit, 5..16 off) by
 *   wrapping the four pad setters (chain_led4, see the bar row section).
 *
 * Storage: the pattern's own step content is the pattern record (area 4), which stays the
 * source of the default bar. Extra bars live in a small log in the unused flash between the
 * application image and the user area (0x3DB000..0x3DFFFF, see docs/CHAIN.md "Storage"):
 *   entry (128 bytes): magic, seq | pattern << 16 | bar << 20, LAST_A | LAST_B << 8, checksum,
 *   then 26 words, one per step row: A mask | B mask << 16, then the scale.
 * The log is append-only, so an edit costs one 128-byte program (no erase, the pattern is
 * never lost by a torn write); a full block is compacted into the scratch block. The pattern
 * commit is redirected: instead of copying the working copy into area 4 slot n+1, the entry
 * for (pattern, bar) is appended, which is why slot n+1 keeps the pattern's original A/B steps
 * and can serve as the default for a bar that was never recorded.
 */
#include "tr8_v161.h"

#define NBARS  4
#define ROWS   26
#define CHAIN_BITS 15
#define CHAIN_LEN  16

/* ---------------------------------------------------------------- flash log */

#define FL_TOP 0x3DF000u          /* first block; blocks go down from here */
#define FL_SCR 0x3DB000u          /* scratch block for compaction          */
#define NBLK   4
#define EPB    32                 /* entries per 4 KB block                */
#define NENT   (NBLK * EPB)
#define ENTW   32                 /* words per entry                       */
#define ENTB   (ENTW * 4)
#define EMAGIC 0x31524256u

typedef void (*fl_prog_fn)(uint32_t off, int len, const void *src);
typedef void (*fl_read_fn)(uint32_t off, int len, void *dst);
typedef void (*fl_erase_fn)(uint32_t off);
/* Raw flash (FINDINGS section 6): offsets from 0x03000000, program <= 0x100 bytes, erase one
 * 4 KB block. These three primitives only move data; they do not touch the flash chip's block
 * protection. The firmware's store brackets a write session with FUN_600108AA (write status
 * register 0 = nothing protected, then indirect mode) and FUN_600108BA (memory-mapped mode,
 * write status register 0x3C = protected again), and its erase/program calls in between rely on
 * that. A program or erase issued outside the pair is silently dropped by the chip, which is
 * why the first hardware build saved nothing; the emulated flash accepted everything. */
typedef void (*fl_sess_fn)(void);
#define F_BEGIN ((fl_sess_fn)0x600108AB)   /* [code] FUN_600108AA: unprotect + indirect */
#define F_END   ((fl_sess_fn)0x600108BB)   /* [code] FUN_600108BA: map + protect         */
#define F_PROG  ((fl_prog_fn)0x60003E55)
#define F_READ  ((fl_read_fn)0x60003EA3)
#define F_ERASE ((fl_erase_fn)0x60003EDB)

uint8_t chain_pos;        /* bar being played, 0..len-1 */
uint8_t chain_wrapping;   /* set by chain_wrap around the FUN_600095F0 call */
uint16_t chain_swallow;   /* pads whose press we took: their release is swallowed too */

static uint8_t tab[NBARS * 16];  /* newest entry index + 1 per (pattern, bar), 0 = none */
static uint8_t wr_i;             /* next log entry */
static uint16_t seqn;            /* last sequence number written */
static uint8_t inited;           /* the log has been scanned */
static uint8_t cur_pat = 0xFF;   /* pattern whose bar is in the working copy, 0xFF = unknown */
static uint8_t cur_bar;          /* bar in the working copy */

static uint32_t ebuf[ENTW];

static volatile uint32_t *area_slot(int area, int slot);

static uint32_t ent_off(int i)
{
    return FL_TOP - (uint32_t)(i / EPB) * 0x1000u + (uint32_t)(i % EPB) * ENTB;
}

/* Every program and erase goes through one of these, so the chip is never left protected while
 * a write is pending and never left unprotected when the payload returns to the panel. */
static void fl_erase(uint32_t off)
{
    F_BEGIN();
    F_ERASE(off);
    F_END();
}

static void fl_write(uint32_t off, const uint32_t *src)
{
    F_BEGIN();
    F_PROG(off, ENTB, src);
    F_END();
}

/* Program one log entry and read its magic back: 1 = the chip took it. */
static int fl_put(int i)
{
    fl_write(ent_off(i), ebuf);
    F_READ(ent_off(i), 4, &ebuf[31]);
    return ebuf[31] == EMAGIC;
}

/* .text.far: the second region is full (see the bar row section). */
__attribute__((section(".text.far"))) static uint32_t ecrc(const uint32_t *e)
{
    uint32_t h = 0x811C9DC5u;
    int i;
    for (i = 0; i < ENTW; i++)
        if (i != 3)
            h = (h ^ e[i]) * 0x01000193u;
    return h;
}

static int eok(const uint32_t *e)
{
    return e[0] == EMAGIC && e[3] == ecrc(e);
}

static int e_is(const uint32_t *e, int pat, int bar)
{
    return eok(e) && (int)((e[1] >> 16) & 0xF) == pat && (int)((e[1] >> 20) & 3) == bar;
}

/* Scan the log once: the newest entry per bar, and where to append. The newest entry of a bar
 * is not always the last one in address order: after the ring wraps or a block is compacted, an
 * older duplicate can sit above a newer entry. Sequence numbers decide, compared modulo 2^16 so
 * that the wrap from 0xFFFF to 0 keeps working (entries that coexist in the log are at most a
 * few hundred saves apart). */
static void store_init(void)
{
    int i, k, best = 0;
    uint16_t bseq = 0;
    uint32_t w;

    for (i = 0; i < NBARS * 16; i++)
        tab[i] = 0;
    for (i = 0; i < NENT; i++) {
        F_READ(ent_off(i), ENTB, ebuf);
        if (!eok(ebuf))
            continue;
        k = (int)((ebuf[1] >> 16) & 0xF) * NBARS + (int)((ebuf[1] >> 20) & 3);
        w = ebuf[1] & 0xFFFF;
        if (!best || (int16_t)(w - bseq) > 0) { bseq = (uint16_t)w; best = i + 1; }
        if (!tab[k]) {
            tab[k] = (uint8_t)(i + 1);
            continue;
        }
        F_READ(ent_off(tab[k] - 1), ENTB, ebuf);   /* the entry known so far */
        if (eok(ebuf) && (int16_t)(w - (ebuf[1] & 0xFFFF)) > 0)
            tab[k] = (uint8_t)(i + 1);
    }
    seqn = bseq;
    wr_i = (uint8_t)(best % NENT);
    inited = 1;
}

/* Move the live entries of the block with the fewest of them out of the way, erase it, put them
 * back at its start and continue there. There are at most 64 live entries (16 patterns x 4 bars),
 * so this block always ends up with fewer than EPB of them and keeps a free slot: compacting the
 * block at the write pointer would not help when all of its entries are live. */
static void store_gc(void)
{
    uint8_t pr[EPB];
    int i, p, n = 0, blk, b, cnt, bestn = EPB + 1;

    for (b = 0; b < NBLK; b++) {
        cnt = 0;
        for (p = 0; p < NBARS * 16; p++) {
            int d = (int)tab[p] - 1;
            if (tab[p] && d >= b * EPB && d < (b + 1) * EPB)
                cnt++;
        }
        if (cnt < bestn) { bestn = cnt; blk = b; }
    }
    fl_erase(FL_SCR);
    for (i = 0; i < EPB; i++) {
        int idx = blk * EPB + i;
        for (p = 0; p < NBARS * 16; p++)
            if (tab[p] == idx + 1)
                break;
        if (p == NBARS * 16)
            continue;
        F_READ(ent_off(idx), ENTB, ebuf);
        fl_write(FL_SCR + (uint32_t)n * ENTB, ebuf);
        pr[n++] = (uint8_t)p;
    }
    fl_erase(FL_TOP - (uint32_t)blk * 0x1000u);
    for (i = 0; i < n; i++) {
        F_READ(FL_SCR + (uint32_t)i * ENTB, ENTB, ebuf);
        fl_put(blk * EPB + i);
        tab[pr[i]] = (uint8_t)(blk * EPB + i + 1);
    }
    wr_i = (uint8_t)(blk * EPB + n);
}

/* Append the working copy (area 4 slot 0) as bar `bar` of pattern `pat`. 1 = the entry is in
 * the flash (it was read back), 0 = the chip did not take it. */
static int store_save(int pat, int bar)
{
    volatile uint32_t *s = area_slot(TR8_AREA_PATTERN, 0);
    int i, ok;
    uint32_t idx;

    if (!inited)
        store_init();
    idx = wr_i;
    F_READ(ent_off((int)idx), 4, ebuf);
    if (ebuf[0] != 0xFFFFFFFFu) {          /* block still in use: reclaim one */
        store_gc();
        idx = wr_i;
    }
    ebuf[0] = EMAGIC;
    ebuf[1] = (uint32_t)(++seqn & 0xFFFF) | ((uint32_t)pat << 16) | ((uint32_t)bar << 20);
    ebuf[2] = (s[2] & 0xFF) | ((s[3] & 0xFF) << 8);
    for (i = 0; i < ROWS; i++)
        ebuf[4 + i] = (s[4 + 2 * i] & 0xFFFF) | ((s[5 + 2 * i] & 0xFFFF) << 16);
    ebuf[30] = s[1] & 3;              /* scale: the redirect never writes the pattern slot */
    ebuf[31] = 0;                     /* the two words after the rows are part of the checksum */
    ebuf[3] = ecrc(ebuf);
    ok = fl_put((int)idx);
    tab[pat * NBARS + bar] = (uint8_t)(idx + 1);
    wr_i = (uint8_t)((idx + 1) % NENT);
    return ok;
}

/* ---------------------------------------------------------------- pattern view */

/* Value words of a parameter slot: slot 0 is the working copy, slot n+1 is pattern n. */
static volatile uint32_t *area_slot(int area, int slot)
{
    uint32_t ctx[3];
    TR8_FN_PCTX(ctx, area, slot);
    return (volatile uint32_t *)ctx[0];
}

/* Load a bar into the working copy: the log entry if there is one, else the pattern's own
 * steps (area 4 slot pat+1), which the redirect in chain_commit keeps untouched. In the first
 * free region: both callers (sync, chain_edit) are there and the second region is full. */
__attribute__((section(".text.far"))) static void slot_load(int pat, int bar, int side)
{
    volatile uint32_t *d = area_slot(TR8_AREA_PATTERN, 0);
    volatile uint32_t *src;
    uint8_t idx = tab[pat * NBARS + bar];
    int i;

    if (idx) {
        F_READ(ent_off(idx - 1), ENTB, ebuf);
        if (e_is(ebuf, pat, bar)) {
            for (i = 0; i < ROWS; i++) {
                d[4 + 2 * i] = ebuf[4 + i] & 0xFFFF;
                d[5 + 2 * i] = ebuf[4 + i] >> 16;
            }
            d[1] = ebuf[30] & 3;
            d[2] = ebuf[2] & 0xFF;
            d[3] = (ebuf[2] >> 8) & 0xFF;
            d[0] = (uint32_t)side;
            return;
        }
    }
    src = area_slot(TR8_AREA_PATTERN, pat + 1);
    for (i = 0; i < 56; i++)
        d[i] = src[i];
    d[0] = (uint32_t)side;
}

/* Fill the player struct from the working copy (the bar being edited). */
static void struct_slot0(void)
{
    volatile uint32_t *s = area_slot(TR8_AREA_PATTERN, 0);
    volatile uint8_t *d = TR8_PTN_STRUCT;
    int i;

    for (i = 0; i < ROWS; i++) {
        int off = i < 4 ? 0x20 + 4 * i : 0x30 + 6 * (i - 4);
        *(volatile uint16_t *)(d + off) = (uint16_t)s[4 + 2 * i];
        *(volatile uint16_t *)(d + off + 2) = (uint16_t)s[5 + 2 * i];
    }
    *(volatile uint32_t *)(d + TR8_PTN_LAST_A) = s[2];
    *(volatile uint32_t *)(d + TR8_PTN_LAST_B) = s[3];
    TR8_FN_SCALE((void *)d, (int)s[1]);
}

/* Fill the player struct from bar `bar` of pattern `pat`, without touching the working copy. */
static void struct_bar(int pat, int bar)
{
    volatile uint32_t *def = area_slot(TR8_AREA_PATTERN, pat + 1);
    volatile uint8_t *d = TR8_PTN_STRUCT;
    uint8_t idx = tab[pat * NBARS + bar];
    int i, ok = 0;

    if (idx) {
        F_READ(ent_off(idx - 1), ENTB, ebuf);
        ok = e_is(ebuf, pat, bar);
    }
    for (i = 0; i < ROWS; i++) {
        int off = i < 4 ? 0x20 + 4 * i : 0x30 + 6 * (i - 4);
        uint32_t a, b;
        if (ok) {
            a = ebuf[4 + i] & 0xFFFF;
            b = ebuf[4 + i] >> 16;
        } else {
            a = def[4 + 2 * i] & 0xFFFF;
            b = def[5 + 2 * i] & 0xFFFF;
        }
        *(volatile uint16_t *)(d + off) = (uint16_t)a;
        *(volatile uint16_t *)(d + off + 2) = (uint16_t)b;
    }
    *(volatile uint32_t *)(d + TR8_PTN_LAST_A) = ok ? (ebuf[2] & 0xFF) : def[2];
    *(volatile uint32_t *)(d + TR8_PTN_LAST_B) = ok ? ((ebuf[2] >> 8) & 0xFF) : def[3];
    TR8_FN_SCALE((void *)d, ok ? (int)(ebuf[30] & 3) : (int)def[1]);
}

/* ---------------------------------------------------------------- chain */

static int clen(void)
{
    uint32_t v = TR8_PTN2_CUR[CHAIN_LEN];
    return v <= NBARS ? (int)v : 0;
}

static uint32_t cbits(void)
{
    return TR8_PTN2_CUR[CHAIN_BITS] & 0xF;
}

static void show_bar(int n, int is_b)
{
    static char txt[5];
    txt[0] = ' ';
    txt[1] = ' ';
    txt[2] = (char)('0' + n);
    txt[3] = is_b ? 'B' : 'A';
    TR8_DISPLAY_TEXT(0, txt);
}

static void show_len(int n)
{
    static char txt[5];
    txt[0] = 'C';
    txt[1] = 'H';
    txt[2] = n ? ' ' : '-';
    txt[3] = n ? (char)('0' + n) : '-';
    TR8_DISPLAY_TEXT(0, txt);
}

/* The chip did not take the bar we just left (see F_BEGIN in the storage section). */
static void show_fail(void)
{
    static char txt[5];
    txt[0] = 'F';
    txt[1] = 'A';
    txt[2] = 'I';
    txt[3] = 'L';
    TR8_DISPLAY_TEXT(0, txt);
}

/* The panel changed pattern: the working copy is now that pattern's own steps, so bar 1 (or
 * the bar the user selects next) has to be loaded before anything edits or plays it. */
__attribute__((section(".text.far"))) static void sync(void)
{
    int p = (int)(area_slot(TR8_AREA_SETUP, 0)[TR8_SETUP_PATTERN] & 0xF);

    if (!inited)
        store_init();
    if (p != cur_pat) {
        cur_pat = (uint8_t)p;
        cur_bar = 0;
        slot_load(p, 0, (int)(area_slot(TR8_AREA_PATTERN, 0)[0] & 1));
    }
}

/* Replaces "bl FUN_6000E404" at 0x60009614: choose the bar and the side of this pass. */
void chain_var(void *obj)
{
    int len;

    sync();
    len = clen();
    if (!len || TR8_SEQ_VARI != 2) {           /* no chain, or the panel selected A or B */
        TR8_FN_VARIATION(obj);
        return;
    }
    {
        int pos = chain_wrapping ? (chain_pos + 1) % len : 0;
        chain_pos = (uint8_t)pos;
        struct_bar(cur_pat, pos);
        TR8_SEQ_VARIATION = (cbits() >> pos) & 1;
        TR8_FN_APPLY(obj);
    }
}

/* Replaces "bl FUN_600095F0" at 0x600098CA (pattern wrap). */
void chain_wrap(void *obj)
{
    chain_wrapping = 1;
    TR8_FN_RESTART(obj);
    chain_wrapping = 0;
}

/* ---------------------------------------------------------------- bar row LEDs */

/* While exactly one of VARIATION A/B is held the 16 pads are the bar row: pads 1..4 show the four
 * bars (the selected one in the firmware's blinking play colour 0, the other three in the panel's
 * yellow 3) and pads 5..16 are off, so only the four bars are lit. Releasing the button gives the
 * pads back to whatever the screen wants to show.
 *
 * Every screen paints pads through one of four tiny setters, so the hook is inside them, not on a
 * view: 0x60017748 (raw setter FUN_6001773A), 0x6001776C (palette setter FUN_6001774E),
 * 0x60017E18 (raw copy FUN_60017E08) and 0x60017E3A (palette copy FUN_60017E1E) are all
 * "bl FUN_6004BB4C" with (obj, led, a, b, c). Replacing those four calls with this one function
 * covers the sequencer, PTN SELECT, TR-REC, LAST STEP and every other view, and keeps working
 * after a pattern change (which switches the screen). The raw triples are the palette entries:
 * 0 = (1, 0, 2) blinking play, 3 = (1, 9, 6) yellow, 0x2D = (0, 0, 2) off. */
void chain_led4(void *obj, int led, int a, int b, int c)
{
    int p = led - TR8_LED_STEP(0);

    if ((unsigned)p <= 15
        && (TR8_BTN_HELD(TR8_BTN_VARI_A) == 1) != (TR8_BTN_HELD(TR8_BTN_VARI_B) == 1)) {
        int row = p < NBARS;
        int yel = row && p != (int)cur_bar;

        a = row;                       /* pads 5..16: off (palette 0x2D = 0, 0, 2) */
        b = yel ? 9 : 0;
        c = 2 + (yel ? 4 : 0);         /* row: 1,0,2 play or 1,9,6 yellow */
    }
    TR8_FN_LED_SET(obj, led, a, b, c);
}

/* A or B + pad 1..4: make bar n the working copy and paint it with that side. A+B + pad:
 * chain length. A+B+CLEAR + pad: chain off. a = VARIATION A held, b = VARIATION B held. */
/* .text.far (the first region, link.ld); noinline keeps clang from folding it into chain_press,
 * which overflowed the second region. */
__attribute__((section(".text.far"), noinline)) static void chain_edit(int pad, int a, int b)
{
    int bar = pad;
    int saved;

    if (a && b) {
        if (TR8_BTN_HELD(TR8_BTN_CLEAR) == 1) {
            TR8_PTN2_SET(0, CHAIN_LEN, 0);
            show_len(0);
        } else {
            TR8_PTN2_SET(0, CHAIN_LEN, bar + 1);
            show_len(bar + 1);
        }
        return;
    }

    saved = store_save(cur_pat, cur_bar);      /* keep the bar being left */
    cur_bar = (uint8_t)bar;
    slot_load(cur_pat, bar, b);
    struct_slot0();
    TR8_SEQ_VARI = (uint32_t)(b ? 1 : 0);
    TR8_SEQ_VARIATION = (uint32_t)(b ? 1 : 0);
    TR8_FN_APPLY((void *)TR8_PTN_STRUCT);
    {
        uint32_t bits = cbits();
        int len = clen();
        if (b)
            bits |= 1u << bar;
        else
            bits &= ~(1u << bar);
        if (bar + 1 > len)
            len = bar + 1;
        TR8_PTN2_SET(0, CHAIN_BITS, (int)bits);
        TR8_PTN2_SET(0, CHAIN_LEN, len);
    }
    show_bar(bar + 1, b);
    if (!saved)
        show_fail();
}

/* Replaces "bl FUN_60013B34" at 0x60013842: button press, id in r0, held bit already set.
 * Runs before the screen, so this is the first code that can take the pad. */
int chain_press(int id)
{
    if ((unsigned)id < 16)
        sync();
    if ((unsigned)id < NBARS) {
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

/* Replaces "bl FUN_6000FC78" at 0x6001B7F4 (the firmware's pattern save, FUN_6001B7D8).
 * The working copy is one bar, not the pattern, so it is appended to the log instead of being
 * copied over area 4 slot n+1; that slot keeps the pattern's own A/B steps, which is what an
 * unrecorded bar plays. area 6 (weak accents, flams, this pattern's chain) is saved as before.
 * The guard matters: the firmware also saves a pattern the panel only just selected, before the
 * patch has seen a pad and loaded that pattern's bar 1. The working copy is then the pattern
 * itself, not a bar, so the stock commit is the right thing (and is a no-op copy in practice). */
__attribute__((section(".text.far"))) void chain_commit(int a, int area, int slot, int b)
{
    if (area == TR8_AREA_PATTERN && slot >= 1 && slot - 1 == (int)cur_pat) {
        store_save(slot - 1, cur_bar);
        return;
    }
    TR8_FN_COMMIT(a, area, slot, b);
}
