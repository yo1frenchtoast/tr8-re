/*
 * TR-8 v1.61 bar chain: a pattern becomes four bars, each with its own A and B step set.
 *
 * Panel (per pattern; nothing is carried to another pattern):
 *   hold VARIATION A, press pad 1..4 -> bar n is the working copy and plays its A steps; the A
 *                                     side becomes at least n bars long.
 *   hold VARIATION B, press pad 1..4 -> the same bar, its B steps; the B side grows the same way.
 *   hold A + B, press pad 1..4       -> both sides are n bars long (extend or shrink).
 *   hold A + B + CLEAR, press a pad  -> both sides back to stock (no bar sequence).
 *   The numeric display confirms each gesture ("  A1", "  B4", "AB 3", "AB--"); the bar number
 *   gives way to the screen's own text as soon as the variation button is released.
 *
 * Playback: variation A plays bars 1..Na with each bar's A steps, variation B plays bars 1..Nb
 * with each bar's B steps, and A+B plays the A sequence then the B sequence. A sequence loops at
 * its end. A side and B side have their own length, so A can be a two-bar phrase while B is four
 * bars. The length of a side is the highest bar selected on that side (1..4); a pattern whose
 * sides were never selected stays stock.
 *
 * A bar select is also a jump: while playing, the next bar boundary plays the selected bar and
 * the sequence carries on from it; while stopped, the next start begins at the selected bar. A
 * fresh patch state and a pattern change put the playhead back on bar 1.
 *
 * So pattern 1 keeps four private bars (A and B steps each), pattern 2 the same, and each
 * pattern's two sides are its own phrases. A bar that has never been recorded is the pattern
 * itself (its A steps for the A side, its B steps for the B side), so a pattern sounds exactly
 * as before until a bar is edited.
 *
 * How the firmware is made to do this (docs/CHAIN.md, docs/FINDINGS.md section 7):
 *   The working copy of a pattern is area 4 slot 0; TR-REC, the step pads and LAST STEP all
 *   write it. To edit bar n we copy that bar's stored content into slot 0 (masks, LAST_A,
 *   LAST_B, scale, VARI) and the panel is then editing bar n. Selecting a bar saves the one we
 *   leave.
 *   Playback never switches patterns: chain_var replaces "bl FUN_6000E404" inside the restart
 *   FUN_600095F0 (start and every wrap), picks the side and bar, fills the player struct
 *   0x6012FA64 from the bar's content and applies the masks with FUN_6000E152.
 *   chain_wrap replaces the wrap call (0x600098CA) and marks the restart as a wrap, so a start
 *   begins at bar 1 and a wrap advances one bar (then A/B or the A->B handover).
 *   The gesture lives on the press dispatch (0x60013842, before the screen): the screen takes a
 *   bare pad press, so the global button handler never sees it (see the first hardware build).
 *   chain_release swallows the matching release.
 *   While VARIATION A or B is held, all 16 pads become the bar row (the side's bars lit, 5..16
 *   off) by wrapping the four pad setters (chain_led4, see the bar row section).
 *
 * Storage: the pattern's own step content is the pattern record (area 4), which stays the
 * source of the default bar. The two side lengths live in an unused Ptn2 parameter (id 0x138),
 * so the stock area-6 commit saves them with the pattern. Extra bars live in a small log in the
 * unused flash between the application image and the user area (0x3DB000..0x3DFFFF, see
 * docs/CHAIN.md "Storage"):
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
#define CHAIN_COUNTS 17           /* Ptn2 id 0x138: A bars | B bars << 4 */

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

uint8_t chain_pos;        /* position in this pass, 0..na+nb-1 (A+B) or 0..n-1 (A/B) */
uint8_t chain_side;       /* side being played: 0 = A, 1 = B */
uint8_t chain_row[2];     /* bar last selected or played on each side, for the bar row */
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
/* .text.far: the second region is full (see the bar row section). */
__attribute__((section(".text.far"))) static void struct_bar(int pat, int bar)
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

/* Bars of one side: 0 = never selected (that side stays stock), 1..4 = sequence length. */
/* .text.far (the second region is full). */
__attribute__((section(".text.far"))) static int clen(int side)
{
    uint32_t v = TR8_PTN2_CUR[CHAIN_COUNTS] >> (4 * side);
    v &= 0xF;
    return v <= NBARS ? (int)v : NBARS;
}

/* The four-character numeric display. .data: the second region is full, the first has room. */
__attribute__((section(".data.far"))) static char txt[5];

/* "  A1": the side, then the bar. It is only a confirmation of the pad press; releasing the
 * variation button hands the display back to the screen (see chain_release). */
static void show_bar(int n, int is_b)
{
    txt[0] = ' ';
    txt[1] = ' ';
    txt[2] = (char)('A' + is_b);          /* 'A' or 'B' */
    txt[3] = (char)('0' + n);
    TR8_DISPLAY_TEXT(0, txt);
}

/* .text (the second region) now that the row code got smaller. */
static void show_ab(int n)
{
    txt[0] = 'A';
    txt[1] = 'B';
    txt[2] = '-';
    txt[3] = '-';
    if (n) {
        txt[2] = ' ';
        txt[3] = (char)('0' + n);
    }
    TR8_DISPLAY_TEXT(0, txt);
}

/* The chip did not take the bar we just left (see F_BEGIN in the storage section). */
/* .text.far (the second region is full). */
__attribute__((section(".text.far"))) static void show_fail(void)
{
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
        chain_row[0] = 0;
        chain_row[1] = 0;
        slot_load(p, 0, (int)(area_slot(TR8_AREA_PATTERN, 0)[0] & 1));
    }
}

/* Replaces "bl FUN_6000E404" at 0x60009614: choose the bar and the side of this pass.
 * A plays bars 1..Na, B bars 1..Nb, A+B the A sequence then the B one; all start at bar 1. */
void chain_var(void *obj)
{
    int na, nb, v, pos, bar;

    sync();
    v = (int)TR8_SEQ_VARI;
    na = clen(0);
    nb = clen(1);
    if ((!na && !nb) || (v == 0 && !na) || (v == 1 && !nb)) {
        TR8_FN_VARIATION(obj);                  /* side was never selected: stock */
        return;
    }
    /* A wrap advances one bar; a fresh start begins at the bar last selected with A/B + pad
     * (cur_bar, 0-based; it is 0 when nothing was selected, so the phrase starts at bar 1). */
    pos = chain_wrapping ? (int)chain_pos + 1 : (int)cur_bar;
    if (v == 0) {
        if (pos >= na)
            pos = 0;
        chain_side = 0;
        bar = pos;
    } else if (v == 1) {
        if (pos >= nb)
            pos = 0;
        chain_side = 1;
        bar = pos;
    } else {
        if (pos >= na + nb)
            pos = 0;
        if (pos >= na) {
            chain_side = 1;
            bar = pos - na;
        } else {
            chain_side = 0;
            bar = pos;
        }
    }
    chain_pos = (uint8_t)pos;
    chain_row[chain_side] = (uint8_t)bar;
    struct_bar(cur_pat, bar);
    TR8_SEQ_VARIATION = chain_side;
    TR8_FN_APPLY(obj);
}

/* Replaces "bl FUN_600095F0" at 0x600098CA (pattern wrap). */
void chain_wrap(void *obj)
{
    chain_wrapping = 1;
    TR8_FN_RESTART(obj);
    chain_wrapping = 0;
}

/* ---------------------------------------------------------------- bar row LEDs */

/* While exactly one of VARIATION A/B is held the 16 pads are that side's bar row: the bars that
 * side has are green (1, 9, 2) and the bar at that side's head blinks yellow (1, 0, 6): b = 0 is
 * the firmware's blink flag, as in the play colour (1, 0, 2), and c = 6 is yellow. The head is the
 * bar the sequencer is playing on that side, or, stopped, the bar last selected on it. Pads past
 * the side's last bar are off, so only the bars that side has are lit. Releasing the button gives
 * the pads back to whatever the screen wants to show.
 *
 * Every screen paints pads through one of four tiny setters, so the hook is inside them, not on a
 * view: 0x60017748 (raw setter FUN_6001773A), 0x6001776C (palette setter FUN_6001774E),
 * 0x60017E18 (raw copy FUN_60017E08) and 0x60017E3A (palette copy FUN_60017E1E) are all
 * "bl FUN_6004BB4C" with (obj, led, a, b, c). Replacing those four calls with this one function
 * covers the sequencer, PTN SELECT, TR-REC, LAST STEP and every other view, and keeps working
 * after a pattern change (which switches the screen). */
void chain_led4(void *obj, int led, int a, int b, int c)
{
    int p = led - TR8_LED_STEP(0);
    int hb = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1;

    if ((unsigned)p <= 15 && (TR8_BTN_HELD(TR8_BTN_VARI_A) == 1) != hb) {
        int n = clen(hb);                  /* holding B shows the B side's bars */
        int cur;

        if (!n)
            n = 1;                         /* nothing selected: the pattern itself */
        cur = (int)chain_row[hb];
        if ((unsigned)cur >= (unsigned)n)
            cur = n - 1;                   /* the side shrank: blink its last bar */
        a = p < n;                         /* pads past the last bar: off */
        b = p == cur ? 0 : 9;              /* 0 = blink (the play flag), 9 = steady */
        c = p == cur ? 6 : 2;              /* head: yellow, other bars: green */
        if (!a) {
            b = 0;
            c = 2;                         /* palette 0x2D = (0, 0, 2), off */
        }
    }
    TR8_FN_LED_SET(obj, led, a, b, c);
}

/* A or B + pad 1..4: make bar n the working copy and paint it with that side; that side becomes
 * at least n bars long. A+B + pad: both sides n bars. A+B+CLEAR + pad: both sides stock.
 * a = VARIATION A held, b = VARIATION B held. */
/* .text.far (the first region, link.ld); noinline keeps clang from folding it into chain_press,
 * which overflowed the second region. */
__attribute__((section(".text.far"), noinline)) static void chain_edit(int pad, int a, int b)
{
    int bar = pad;
    int saved;

    if (a && b) {
        int n = TR8_BTN_HELD(TR8_BTN_CLEAR) == 1 ? 0 : bar + 1;

        TR8_PTN2_SET(0, CHAIN_COUNTS, n | (n << 4));
        show_ab(n);
        return;
    }

    saved = store_save(cur_pat, cur_bar);      /* keep the bar being left */
    cur_bar = (uint8_t)bar;
    chain_row[b] = (uint8_t)bar;               /* the row follows the bar being edited */
    chain_pos = (uint8_t)(bar - 1);            /* selecting a bar is also a jump: the next bar
                                                * boundary (and the next start) plays this one */
    slot_load(cur_pat, bar, b);
    struct_slot0();
    TR8_SEQ_VARI = (uint32_t)(b ? 1 : 0);
    TR8_SEQ_VARIATION = (uint32_t)(b ? 1 : 0);
    TR8_FN_APPLY((void *)TR8_PTN_STRUCT);
    {
        uint32_t w = TR8_PTN2_CUR[CHAIN_COUNTS];
        int na = (int)(w & 0xF);
        int nb = (int)((w >> 4) & 0xF);

        if (b) {
            if (bar + 1 > nb)
                nb = bar + 1;
        } else {
            if (bar + 1 > na)
                na = bar + 1;
        }
        TR8_PTN2_SET(0, CHAIN_COUNTS, na | (nb << 4));
    }
    /* The bar is in slot 0 and in the player struct; ask the panel to repaint its step pads on
     * its next pass instead of notifying the screens from inside the press dispatch (that
     * synchronous observer walk is what froze the unit). Only the pads: the display was just
     * written with the bar number, so leave the text alone. */
    *TR8_HMI_PANEL |= TR8_HMI_REPAINT_PADS;
    show_bar(bar + 1, b);               /* the confirmation of the pad press */
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
    int r;

    if ((unsigned)id < 16 && (chain_swallow & (1u << id))) {
        chain_swallow &= (uint16_t)~(1u << id);
        return 0;                              /* the press was taken: swallow the release too */
    }
    r = TR8_FN_BTN_RELEASE(id);
    /* The bar number on the display is only the confirmation of the pad press. Releasing the
     * variation button asks the panel to repaint its own view, so the default text comes back;
     * this is the firmware's own helper (0x44: step pads and numeric text), so the patch never
     * writes a firmware object by hand. */
    if ((unsigned)(id - TR8_BTN_VARI_A) < 2)
        TR8_FN_REPAINT();
    return r;
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
