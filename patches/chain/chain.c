/*
 * TR-8 v1.61 bar chain: a pattern becomes up to eight bars, each with its own A and B step set.
 *
 * Panel (per pattern; nothing is carried to another pattern):
 *   hold VARIATION A, press pad 1..8 -> bar n is the working copy and plays its A steps; the A
 *                                     side becomes at least n bars long.
 *   hold VARIATION B, press pad 1..8 -> the same bar, its B steps; the B side grows the same way.
 *   hold A + B, press pad 1..8       -> both sides are n bars long (extend or shrink).
 *   hold A + B + CLEAR, press a pad  -> both sides back to stock (no bar sequence).
 *   The numeric display confirms each gesture ("  A1", "  B4", "AB 3", "AB--"); the bar number
 *   gives way to the screen's own text as soon as the variation button is released.
 *
 * Playback: variation A plays bars 1..Na with each bar's A steps, variation B plays bars 1..Nb
 * with each bar's B steps, and A+B plays the A sequence then the B sequence. A sequence loops at
 * its end. A side and B side have their own length, so A can be a two-bar phrase while B is
 * eight bars. The length of a side is the highest bar selected on that side (1..8); a pattern
 * whose sides were never selected stays stock.
 *
 * A bar select is also a jump: while playing, the next bar boundary plays the selected bar and
 * the sequence carries on from it; while stopped, the next start begins at the selected bar. A
 * fresh patch state and a pattern change put the playhead back on bar 1.
 *
 * So pattern 1 keeps eight private bars (A and B steps each), pattern 2 the same, and each
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
 *   While VARIATION A or B is held, all 16 pads become the bar row (the side's bars lit, 9..16
 *   off) by wrapping the four pad setters (chain_led4, see the bar row section).
 *
 * Storage: the pattern's own step content is the pattern record (area 4), which stays the
 * source of the default bar. The two side lengths live in an unused Ptn2 parameter (id 0x138),
 * so the stock area-6 commit saves them with the pattern. Extra bars live in a small log in the
 * unused flash between the application image and the user area (0x3DA000..0x3DFFFF, see
 * docs/CHAIN.md "Storage"):
 *   entry (128 bytes): magic, seq | pattern << 16 | bar << 20, LAST_A | LAST_B << 8, checksum,
 *   then 26 words, one per step row: A mask | B mask << 16, then the scale.
 * The log is append-only, so an edit costs one 128-byte program (no erase, the pattern is
 * never lost by a torn write); a full block is compacted into the scratch block, and the boot
 * scan finishes an interrupted compaction from that scratch block. The pattern commit is
 * redirected only while that pattern has a side sequence: instead of copying the working copy
 * into area 4 slot n+1, the entry for (pattern, bar) is appended, which is why slot n+1 keeps
 * the pattern's original A/B steps and can serve as the default for a bar that was never
 * recorded. A pattern with no side sequence keeps the stock commit, so its edits survive a
 * reflash.
 *
 * Tasks (docs/DEVELOPING.md section 3): chain_var and chain_wrap run in the sequencer task;
 * chain_view, chain_press, chain_edit, chain_led4, chain_commit and the log/store code run in
 * the panel task. The sequencer never touches the flash: it reads a RAM copy of the bars that
 * the panel task fills (bar_ram). State has one writer: the sequencer writes chain_pos,
 * chain_side, chain_row and chain_wrapping; the panel writes cur_pat, cur_bar, cur_side,
 * chain_sel, chain_jump, chain_swallow and the log index.
 */
#include "tr8_v161.h"

#define NBARS  8
#define ROWS   26
#define CHAIN_COUNTS 17           /* Ptn2 id 0x138: A bars | B bars << 4 */

/* ---------------------------------------------------------------- flash log */

/* The log is the 20 KB at 0x3DB000..0x3E0000, entry i at FL_BASE + i * 128. The eighth build
 * kept four blocks at 0x3DC000..0x3DFFFF (entry i at 0x3DF000 - (i / 32) * 0x1000 + (i % 32) *
 * 128); those are now entries 32..159 — the same bytes at the same addresses — so an upgrade
 * keeps the bars already stored. The scratch block for compaction sits just below. */
#define FL_BASE 0x3DB000u
#define FL_SCR  0x3DA000u
#define NBLK   5
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

/* Sequencer task only (see the "Tasks" note in the header). */
volatile uint8_t chain_pos;      /* position in this pass, 0..na+nb-1 (A+B) or 0..n-1 (A/B) */
volatile uint8_t chain_side;     /* side being played: 0 = A, 1 = B */
volatile uint8_t chain_row[2];   /* bar last played on each side, for the bar row */
volatile uint8_t chain_wrapping; /* set by chain_wrap around the FUN_600095F0 call */

/* Panel task only. chain_jump and chain_sel are the panel's hand-off to the sequencer (each a
 * single byte, written last after the data it describes); the sequencer only reads them. */
volatile uint8_t chain_jump;     /* (bar + 1) | toggle | side << 5, 0 = no jump asked for yet */
volatile uint8_t chain_sel[2];   /* bar last selected on each side, for the stopped bar row */
uint8_t chain_swallow;           /* bit n: pad n's press was taken, its release swallowed too */
static uint8_t chain_tog;        /* panel: toggles bit 4, so two selects of one bar differ */

/* Newest entry index + 1 per (pattern, bar), 0 = none: 16 patterns x 8 bars. The patch lives in
 * the application image above the firmware bss (0x60281200, see link.ld): the patcher grows the
 * image to cover it and the RTOS pool start moves by 64 KB, so this memory is neither zeroed at
 * boot nor handed to the pool. store_init clears the index before its first use anyway. */
static uint8_t tab[NBARS * 16];
static uint8_t wr_i;             /* next log entry */
static uint8_t flash_bad;        /* a compaction step did not land: keep the scratch block */
static uint16_t seqn;            /* last sequence number written */
static volatile uint8_t inited;  /* the log has been scanned (panel task) */
static volatile uint8_t cur_pat = 0xFF; /* pattern whose bars are loaded, 0xFF = unknown */
static volatile uint8_t cur_bar; /* bar in the working copy */
static volatile uint8_t cur_side;/* side the working copy was loaded for */
static uint32_t clean;           /* wchash() of the working copy when it was loaded */

/* Playback copy of each bar's log entry, filled by the panel task. Two buffers per bar: the
 * panel writes the one the sequencer is not using and then flips cache_idx[bar] (one byte,
 * written last), so the sequencer never reads flash and never sees a half-written bar
 * (DEVELOPING.md section 3, rule 3). A buffer whose first word is not EMAGIC means the bar has
 * no log entry and the pattern's own steps are the default. */
static volatile uint8_t cache_idx[NBARS];
static volatile uint32_t bar_ram[2][NBARS][ENTW];

static uint8_t jump_seen;        /* sequencer: last chain_jump value it acted on */
static uint8_t view_hold;        /* panel: sync() just changed pattern, skip one follow */

static uint32_t ebuf[ENTW];

static volatile uint32_t *area_slot(int area, int slot);

static uint32_t ent_off(int i)
{
    return FL_BASE + (uint32_t)i * ENTB;
}

/* Publish bar `bar` for the sequencer: copy the entry into the buffer it is not reading, then
 * flip the index. A null entry marks the bar as "no log entry". Panel task only. */
static void cache_put(int bar, const uint32_t *e)
{
    volatile uint32_t *d = bar_ram[cache_idx[bar] ^ 1u][bar];
    int i;

    for (i = 0; i < ENTW; i++)
        d[i] = e ? e[i] : 0;
    cache_idx[bar] ^= 1u;              /* published last */
}

/* Every program and erase goes through one of these, so the chip is never left protected while
 * a write is pending and never left unprotected when the payload returns to the panel. */
static void fl_erase(uint32_t off)
{
    F_BEGIN();
    F_ERASE(off);
    F_END();
}

static void fl_write(uint32_t off)
{
    F_BEGIN();
    F_PROG(off, ENTB, ebuf);
    F_END();
}

/* Program one log entry and read its magic back: 1 = the chip took it. */
static int fl_put(int i)
{
    fl_write(ent_off(i));
    F_READ(ent_off(i), 4, ebuf);           /* word 0 again: is the magic really there? */
    return ebuf[0] == EMAGIC;
}

/* FNV-1a over an entry, skipping the checksum word. */
static uint32_t ecrc(const uint32_t *e)
{
    uint32_t h = 0x811C9DC5u;
    int i;
    for (i = 0; i < ENTW; i++)
        if (i != 3)
            h = (h ^ e[i]) * 0x01000193u;
    return h;
}

/* (pattern, bar) of an entry, as an index into tab[]. */
static int ekey(const uint32_t *e)
{
    return (int)((e[1] >> 16) & 0xF) * NBARS + (int)((e[1] >> 20) & 0xF);
}

/* A valid entry: magic, checksum, and the (pattern, bar) it claims to be, unless k is negative
 * (the log scan takes any bar). One function instead of two saves a call and a literal pool. */
static int eok(const uint32_t *e, int k)
{
    return e[0] == EMAGIC && e[3] == ecrc(e) && (k < 0 || ekey(e) == k);
}

/* FNV-1a over the value words a stored bar has (1..55: scale, LAST_A, LAST_B, the 26 A/B mask
 * pairs). The working copy is untouched while the hash still matches the one taken when the bar
 * was loaded, so a bar boundary that nobody edited costs no flash write. Word 0 is the variation,
 * which is not part of a bar. */
static uint32_t wchash(const volatile uint32_t *s)
{
    uint32_t h = 0x811C9DC5u;
    int i;

    for (i = 1; i < 56; i++)
        h = (h ^ s[i]) * 0x01000193u;
    return h;
}

/* Move the write pointer to the next erased slot. It is called only after a compaction or when
 * recovering the scratch block, both of which leave a run of erased slots at or above wr_i. */
static int find_free(void)
{
    int n = 0;

    while (n < NENT) {
        F_READ(ent_off(wr_i), 4, ebuf);
        if (ebuf[0] == 0xFFFFFFFFu)
            return 1;
        wr_i = (uint8_t)((wr_i + 1) % NENT);
        n++;
    }
    return 0;
}

/* Scan the log once: the newest entry per bar, and where to append. The newest entry of a bar
 * is not always the last one in address order: after the ring wraps or a block is compacted, an
 * older duplicate can sit above a newer entry. Sequence numbers decide, compared modulo 2^16 so
 * that the wrap from 0xFFFF to 0 keeps working (entries that coexist in the log are at most a
 * few hundred saves apart). The write pointer is the lowest erased slot (the scan runs downwards,
 * so the last erased slot it sees is the lowest one), so the appends fill the log from the bottom;
 * the sequence number is the highest one stored. */
static void store_init(void)
{
    int i, k, have = 0;
    uint32_t w;

    for (i = 0; i < NBARS * 16; i++)
        tab[i] = 0;
    wr_i = 0;
    for (i = NENT - 1; i >= 0; i--) {
        F_READ(ent_off(i), ENTB, ebuf);
        if (!eok(ebuf, -1)) {
            wr_i = (uint8_t)i;      /* any erased slot will do; the appends go here */
            continue;
        }
        k = ekey(ebuf);
        w = ebuf[1] & 0xFFFF;
        if (!have || (int16_t)(w - seqn) > 0) {
            seqn = (uint16_t)w;
            have = 1;
        }
        if (!tab[k]) {
            tab[k] = (uint8_t)(i + 1);
            continue;
        }
        F_READ(ent_off(tab[k] - 1), ENTB, ebuf);   /* the entry known so far */
        if (eok(ebuf, -1) && (int16_t)(w - (ebuf[1] & 0xFFFF)) > 0)
            tab[k] = (uint8_t)(i + 1);
    }
    /* Finish an interrupted compaction. store_gc copies the live entries to the scratch block,
     * erases their block and writes them back; a power cut between the erase and the end of the
     * copy-back leaves the only copy in the scratch block. An entry that the live log no longer
     * has (tab[k] == 0) is appended again with its old sequence number, so nothing that was
     * stored before the cut is lost. A duplicate that the log still has is ignored: the scan
     * above already chose the newest copy. */
    for (i = 0; i < EPB; i++) {
        F_READ(FL_SCR + (uint32_t)i * ENTB, ENTB, ebuf);
        if (!eok(ebuf, -1))
            continue;
        w = ebuf[1] & 0xFFFF;
        if (!have || (int16_t)(w - seqn) > 0) {
            seqn = (uint16_t)w;
            have = 1;
        }
        k = ekey(ebuf);
        if (tab[k])
            continue;
        if (!find_free())
            break;                  /* no free slot: the five blocks always keep one */
        F_READ(FL_SCR + (uint32_t)i * ENTB, ENTB, ebuf);   /* find_free() used ebuf */
        if (!eok(ebuf, -1))
            continue;
        if (!fl_put((int)wr_i)) {
            flash_bad = 1;          /* keep the scratch block: retry on the next boot */
            break;
        }
        tab[k] = (uint8_t)(wr_i + 1);
        wr_i = (uint8_t)((wr_i + 1) % NENT);
    }
    inited = 1;
}

/* Move the live entries of the block with the fewest of them out of the way, erase it, put them
 * back at its start and continue there. There are at most 128 live entries (16 patterns x 8 bars)
 * in 160 slots, so the block with the fewest of them always keeps a free slot: compacting the
 * block at the write pointer would not help when all of its entries are live. A slot is live when
 * tab[] names it; any other valid entry in the block is an older duplicate and is dropped.
 *
 * Every copy is read back. A copy that did not land stops the compaction and sets flash_bad: the
 * scratch block keeps the only copy of the entries that were not written back, so no later save
 * may erase it (that would lose them). store_init picks them up on the next boot. 1 = the block
 * was compacted, 0 = a write failed and nothing else may be written this boot. */
static int store_gc(void)
{
    int i, k, n = 0, blk = 0, b, cnt, bestn = EPB + 1;

    for (b = 0; b < NBLK; b++) {
        cnt = 0;
        for (i = 0; i < NBARS * 16; i++)
            cnt += tab[i] > b * EPB && tab[i] <= (b + 1) * EPB;
        if (cnt < bestn) { bestn = cnt; blk = b; }
    }
    fl_erase(FL_SCR);
    for (i = 0; i < EPB; i++) {
        int idx = blk * EPB + i;
        F_READ(ent_off(idx), ENTB, ebuf);
        if (!eok(ebuf, -1))            /* erased or torn: its key is not an index */
            continue;
        if (tab[k = ekey(ebuf)] == idx + 1) {
            fl_write(FL_SCR + (uint32_t)n * ENTB);
            F_READ(FL_SCR + (uint32_t)n * ENTB, ENTB, ebuf);
            if (!eok(ebuf, -1)) {      /* the copy did not land: the block is still whole */
                flash_bad = 1;
                return 0;
            }
            n++;
        }
    }
    fl_erase(FL_BASE + (uint32_t)blk * 0x1000u);
    for (i = 0; i < n; i++) {
        F_READ(FL_SCR + (uint32_t)i * ENTB, ENTB, ebuf);
        k = ekey(ebuf);
        if (!fl_put(blk * EPB + i)) {  /* the rest is only in the scratch block */
            flash_bad = 1;
            return 0;
        }
        tab[k] = (uint8_t)(blk * EPB + i + 1);
    }
    wr_i = (uint8_t)(blk * EPB + n);
    return 1;
}

/* Append the working copy (area 4 slot 0) as bar `bar` of pattern `pat`. 1 = the entry is in
 * the flash (it was read back) or the bar was not edited since it was loaded, 0 = the chip did
 * not take it. */
static int store_save(int pat, int bar)
{
    volatile uint32_t *s = area_slot(TR8_AREA_PATTERN, 0);
    uint32_t h;
    int i, ok;
    uint32_t idx;

    if (!inited)
        store_init();
    if (flash_bad)
        return 0;                          /* a compaction step failed: retry after a reboot */
    h = wchash(s);
    if (h == clean)
        return 1;                          /* nobody touched the bar: it is already stored */
    idx = wr_i;
    F_READ(ent_off((int)idx), 4, ebuf);
    if (ebuf[0] != 0xFFFFFFFFu) {          /* block still in use: reclaim one */
        if (!store_gc())
            return 0;                      /* index and clean hash untouched */
        idx = wr_i;
    }
    ebuf[0] = EMAGIC;
    ebuf[1] = (uint32_t)(++seqn & 0xFFFF) | ((uint32_t)pat << 16) | ((uint32_t)bar << 20);
    ebuf[2] = (s[2] & 0xFF) | ((s[3] & 0xFF) << 8);
    for (i = 0; i < ROWS; i++)
        ebuf[4 + i] = (s[4 + 2 * i] & 0xFFFF) | ((s[5 + 2 * i] & 0xFFFF) << 16);
    ebuf[30] = s[1] & 3;              /* scale: the redirect never writes the pattern slot */
    ebuf[3] = ecrc(ebuf);
    ok = fl_put((int)idx);
    /* The pointer moves past a failed slot too: a torn program cannot be reused without an
     * erase. The index and the clean hash are not touched, so the next save tries this bar again
     * in the next slot (DEVELOPING.md section 7, rule 2). */
    wr_i = (uint8_t)((idx + 1) % NENT);
    if (ok) {
        tab[pat * NBARS + bar] = (uint8_t)(idx + 1);
        clean = h;
        cache_put(bar, ebuf);              /* the bar the sequencer will play next */
    }
    return ok;
}

/* Store the working copy, if the panel changed it since it was loaded. Kept out of line so
 * chain_edit does not have to pass the bar. */
static int save_dirty(void)
{
    return store_save(cur_pat, cur_bar);
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
 * steps (area 4 slot pat+1), which the redirect in chain_commit keeps untouched. */
static void slot_load(int pat, int bar, int side)
{
    volatile uint32_t *d = area_slot(TR8_AREA_PATTERN, 0);
    volatile uint32_t *src;
    uint8_t idx = tab[pat * NBARS + bar];
    int i;

    if (idx) {
        F_READ(ent_off(idx - 1), ENTB, ebuf);
        if (eok(ebuf, pat * NBARS + bar)) {
            for (i = 0; i < ROWS; i++) {
                d[4 + 2 * i] = ebuf[4 + i] & 0xFFFF;
                d[5 + 2 * i] = ebuf[4 + i] >> 16;
            }
            d[1] = ebuf[30] & 3;
            d[2] = ebuf[2] & 0xFF;
            d[3] = (ebuf[2] >> 8) & 0xFF;
            d[0] = (uint32_t)side;
            cache_put(bar, ebuf);
            clean = wchash(d);
            return;
        }
    }
    src = area_slot(TR8_AREA_PATTERN, pat + 1);
    for (i = 0; i < 56; i++)
        d[i] = src[i];
    d[0] = (uint32_t)side;
    cache_put(bar, 0);
    clean = wchash(d);
}

/* Load the pattern's own steps (area 4 slot pat+1) into the working copy, ignoring the log.
 * Used when a side sequence is reset to stock, so that the stock commit that the Ptn2 setter
 * triggers writes the pattern itself and not the bar that happened to be loaded. */
static void pattern_load(int pat, int side)
{
    volatile uint32_t *d = area_slot(TR8_AREA_PATTERN, 0);
    volatile uint32_t *src = area_slot(TR8_AREA_PATTERN, pat + 1);
    int i;

    for (i = 0; i < 56; i++)
        d[i] = src[i];
    d[0] = (uint32_t)side;
    clean = wchash(d);
}

/* Fill the player struct from bar `bar` of pattern `pat`, without touching the working copy.
 * This runs in the sequencer task, so it reads the panel's RAM copy and never the flash. */
static void struct_bar(int pat, int bar)
{
    volatile uint32_t *def = area_slot(TR8_AREA_PATTERN, pat + 1);
    volatile uint8_t *d = TR8_PTN_STRUCT, *p = d;
    const uint32_t *e = (const uint32_t *)bar_ram[cache_idx[bar]][bar];
    int i, ok = eok(e, pat * NBARS + bar);

    /* The player struct has 4-byte A/B pairs for the first four rows (0x20..0x2F), then 6-byte
     * ones (0x30..): walking a pointer is shorter than computing the offset of every row. */
    p = d + 0x20;
    for (i = 0; i < ROWS; i++) {
        uint32_t a, b;
        if (ok) {
            a = e[4 + i] & 0xFFFF;
            b = e[4 + i] >> 16;
        } else {
            a = def[4 + 2 * i] & 0xFFFF;
            b = def[5 + 2 * i] & 0xFFFF;
        }
        *(volatile uint16_t *)p = (uint16_t)a;
        *(volatile uint16_t *)(p + 2) = (uint16_t)b;
        p += i < 4 ? 4 : 6;
    }
    *(volatile uint32_t *)(d + TR8_PTN_LAST_A) = ok ? (e[2] & 0xFF) : def[2];
    *(volatile uint32_t *)(d + TR8_PTN_LAST_B) = ok ? ((e[2] >> 8) & 0xFF) : def[3];
    TR8_FN_SCALE((void *)d, ok ? (int)(e[30] & 3) : (int)def[1]);
}

/* ---------------------------------------------------------------- chain */

/* Bars of one side: 0 = never selected (that side stays stock), 1..8 = sequence length. */
static int clen(int side)
{
    uint32_t v = TR8_PTN2_CUR[CHAIN_COUNTS] >> (4 * side);
    v &= 0xF;
    return v <= NBARS ? (int)v : NBARS;
}

/* The four-character numeric display. The bytes are stored as one word (the display reads the
 * string, so txt[4] stays 0), which is why a message is a word: "  A1" is 0x31_2041_2020. */
static char txt[5];

static void show4(uint32_t w)
{
    *(uint32_t *)txt = w;
    TR8_DISPLAY_TEXT(0, txt);
}

/* "  A1": the side, then the bar. It is only a confirmation of the pad press; releasing the
 * variation button hands the display back to the screen (see chain_release). */
static void show_bar(int n, int is_b)
{
    show4(0x2020u | ((uint32_t)('A' + is_b) << 16) | ((uint32_t)('0' + n) << 24));
}

/* "AB 3", or "AB--" for stock. */
static void show_ab(int n)
{
    show4(n ? (0x204241u | ((uint32_t)('0' + n) << 24)) : 0x2D2D4241u);
}

/* The chip did not take the bar we just left (see F_BEGIN in the storage section). */
static void show_fail(void)
{
    show4(0x4C494146u);                   /* "FAIL" */
}

/* Fill the playback cache for pattern `pat`. Panel task only: it is the only flash reader. */
static void cache_load(int pat)
{
    int i;

    for (i = 0; i < NBARS; i++) {
        uint8_t t = tab[pat * NBARS + i];
        const uint32_t *e = 0;

        if (t) {
            F_READ(ent_off(t - 1), ENTB, ebuf);
            if (eok(ebuf, pat * NBARS + i))
                e = ebuf;
        }
        cache_put(i, e);
    }
}

/* The panel changed pattern: the working copy is now that pattern's own steps, so bar 1 (or
 * the bar the user selects next) has to be loaded before anything edits or plays it. The cache
 * carries the bars to the sequencer, and cur_pat is written last, after the cache. Panel task
 * only. */
static void sync(void)
{
    int p = (int)(area_slot(TR8_AREA_SETUP, 0)[TR8_SETUP_PATTERN] & 0xF);

    if (!inited)
        store_init();
    if (p != cur_pat) {
        volatile uint32_t *wc = area_slot(TR8_AREA_PATTERN, 0);
        uint32_t vari = wc[0];             /* the pattern's own VARI: 0 = A, 1 = B, 2 = A+B */
        int side = vari == 1;              /* A+B starts on the A side */

        cache_load(p);
        cur_bar = 0;
        cur_side = (uint8_t)side;
        chain_sel[0] = 0;
        chain_sel[1] = 0;
        slot_load(p, 0, side);
        wc[0] = vari;                      /* slot_load wrote the side: keep A+B */
        cur_pat = (uint8_t)p;
        view_hold = 1;                     /* this pass must not follow the old row */
    }
}

/* Replaces "bl FUN_6000E404" at 0x60009614: choose the bar and the side of this pass.
 * A plays bars 1..Na, B bars 1..Nb, A+B the A sequence then the B one; all start at bar 1. */
void chain_var(void *obj)
{
    int na, nb, v, pos, bar, side;
    uint8_t j;

    /* The panel task owns the flash scan and the bar cache. Until it has seen this pattern
     * (first start after power-on, or a start from MIDI), play one stock pass and ask the panel
     * to catch up; the next bar boundary uses the chain. No flash access from here. */
    if (!inited || (int)(area_slot(TR8_AREA_SETUP, 0)[TR8_SETUP_PATTERN] & 0xF) != (int)cur_pat) {
        *TR8_HMI_PANEL |= TR8_HMI_REPAINT_PADS;
        TR8_FN_VARIATION(obj);
        return;
    }
    v = (int)TR8_SEQ_VARI;
    na = clen(0);
    nb = clen(1);
    if ((!na && !nb) || (v == 0 && !na) || (v == 1 && !nb)) {
        TR8_FN_VARIATION(obj);                  /* side was never selected: stock */
        return;
    }
    /* A wrap advances one bar; a fresh start begins at the bar last selected with A/B + pad
     * (cur_bar, 0-based; it is 0 when nothing was selected, so the phrase starts at bar 1). In
     * A+B, cur_bar is an index inside one side, so a B-side selection adds the A length. A new
     * chain_jump overrides both: it is the bar the panel just selected, and its side bit says
     * whether that was the B side of an A+B phrase. */
    j = chain_jump;
    if (j != jump_seen) {
        jump_seen = j;
        pos = (int)(j & 0x0F) - 1;              /* bar 1..8 -> 0..7; 0 bits = bar 1 */
        if (pos < 0)
            pos = 0;
        if (v == 2 && (j & 0x20))
            pos += na;                          /* selected on the B side */
    } else {
        pos = chain_wrapping ? (int)chain_pos + 1
                             : (int)cur_bar + (v == 2 && cur_side ? na : 0);
    }
    if (v == 0) {
        if (pos >= na)
            pos = 0;
        side = 0;
        bar = pos;
    } else if (v == 1) {
        if (pos >= nb)
            pos = 0;
        side = 1;
        bar = pos;
    } else {
        if (pos >= na + nb)
            pos = 0;
        if (pos >= na) {
            side = 1;
            bar = pos - na;
        } else {
            side = 0;
            bar = pos;
        }
    }
    chain_pos = (uint8_t)pos;
    struct_bar(cur_pat, bar);
    TR8_SEQ_VARIATION = (uint32_t)side;
    TR8_FN_APPLY(obj);
    /* Publish the pass for the panel (row then side, so a reader never pairs a new side with
     * an old row), then ask it to paint the step pads. Only that bit, so the text is left
     * alone. */
    chain_row[side] = (uint8_t)bar;
    chain_side = (uint8_t)side;
    *TR8_HMI_PANEL |= TR8_HMI_REPAINT_PADS;
}

/* Replaces "bl FUN_600095F0" at 0x600098CA (pattern wrap). */
void chain_wrap(void *obj)
{
    chain_wrapping = 1;
    TR8_FN_RESTART(obj);
    chain_wrapping = 0;
}

/* ---------------------------------------------------------------- playhead follow */

/* Replaces "bl FUN_60016386" at 0x60016C44 (bit 0x04 of the panel object): the panel is about to
 * paint the step pads, so put the bar that is playing into the working copy first and then paint
 * it, exactly as the stock view does. The working copy, and with it the step view, TR-REC and
 * LAST STEP, then belongs to the bar being played; the bar we leave is stored first if the panel
 * edited it (store_save writes nothing otherwise), so steady playback leaves the flash alone.
 *
 * This must run here, in the panel task: the sequencer task must never touch the flash (the log's
 * erase/program primitives have no lock and the panel task writes the same chip for pattern
 * saves). Stopped, the working copy belongs to the bar the panel selected and this does nothing. */
void chain_view(void *obj)
{
    int side, bar;

    sync();                        /* the panel may have switched pattern: not our bar's copy */
    if (view_hold) {               /* sync() just loaded bar 1 of the new pattern */
        view_hold = 0;
    } else {
        side = (int)chain_side;
        bar = (int)chain_row[side];
        if (TR8_SEQ_RUNNING && (bar != (int)cur_bar || side != (int)cur_side)) {
            if (!store_save(cur_pat, cur_bar))  /* keep the bar being left, if it was edited */
                show_fail();
            cur_bar = (uint8_t)bar;
            cur_side = (uint8_t)side;
            slot_load(cur_pat, bar, side);
        }
    }
    TR8_FN_STEPVIEW(obj);
}

/* ---------------------------------------------------------------- bar row LEDs */

/* While exactly one of VARIATION A/B is held the 16 pads are that side's bar row: the bars that
 * side has are green (1, 9, 2) and the bar at that side's head blinks yellow (1, 0, 6): b = 0 is
 * the firmware's blink flag, as in the play colour (1, 0, 2), and c = 6 is yellow. The head is the
 * bar the sequencer is playing on that side (chain_row), or, stopped, the bar last selected on
 * it (chain_sel). Pads past the side's last bar are off, so only that side's bars are lit.
 * Releasing the button gives the pads back to whatever screen wants to show.
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

    if ((unsigned)p <= 15 && (TR8_BTN_HELD(TR8_BTN_VARI_A)) != hb) {
        int n = clen(hb);                  /* holding B shows the B side's bars */
        int cur;

        if (!n)
            n = 1;                         /* nothing selected: the pattern itself */
        cur = (int)(TR8_SEQ_RUNNING ? chain_row[hb] : chain_sel[hb]);
        if ((unsigned)cur >= (unsigned)n)
            cur = n - 1;                   /* the side shrank: blink its last bar */
        a = p < n;                         /* pads past the last bar: off */
        b = p == cur ? 0 : a ? 9 : 0;      /* 0 = blink (the play flag), 9 = steady */
        c = p == cur ? 6 : 2;              /* head: yellow, other bars: green, off: 2 */
    }
    TR8_FN_LED_SET(obj, led, a, b, c);
}

/* A or B + pad 1..8: make bar n the working copy and paint it with that side; that side becomes
 * at least n bars long. A/B + CLEAR + pad n: that side becomes exactly n bars long (shrink).
 * A+B + pad: both sides n bars. A+B+CLEAR + pad: both sides stock.
 * a = VARIATION A held, b = VARIATION B held. */
/* noinline keeps clang from folding this into chain_press. */
__attribute__((noinline)) static void chain_edit(int pad, int a, int b)
{
    int bar = pad;
    int saved;
    int ex = TR8_BTN_HELD(TR8_BTN_CLEAR) == 1;

    if (a && b) {
        int n = ex ? 0 : bar + 1;

        if (!n) {
            /* Back to stock: the working copy must be the pattern's own steps again before the
             * Ptn2 setter triggers the pattern save (chain_commit then keeps the stock commit),
             * and the pending jump must not point at a bar any more. */
            pattern_load(cur_pat, 0);
            cur_bar = 0;
            cur_side = 0;
            chain_sel[0] = 0;
            chain_sel[1] = 0;
            chain_tog ^= 0x10;
            chain_jump = chain_tog;            /* no bar bits: the next pass starts at bar 1 */
            *TR8_HMI_PANEL |= TR8_HMI_REPAINT_PADS;
        }
        TR8_PTN2_SET(0, CHAIN_COUNTS, n | (n << 4));
        show_ab(n);
        return;
    }

    saved = save_dirty();                      /* keep the bar being left, if it was edited */
    cur_bar = (uint8_t)bar;
    cur_side = (uint8_t)b;
    chain_sel[b] = (uint8_t)bar;               /* the row follows the bar being edited */
    slot_load(cur_pat, bar, b);
    struct_bar(cur_pat, bar);                 /* the same bar, into the player struct */
    TR8_SEQ_VARI = (uint32_t)(b ? 1 : 0);
    TR8_SEQ_VARIATION = (uint32_t)(b ? 1 : 0);
    TR8_FN_APPLY((void *)TR8_PTN_STRUCT);
    {
        uint32_t w = TR8_PTN2_CUR[CHAIN_COUNTS];
        int na = (int)(w & 0xF);
        int nb = (int)((w >> 4) & 0xF);
        int n = ex ? bar + 1 : 0;          /* CLEAR: exactly this bar, so the side can shrink */

        if (b) {
            if (n || bar + 1 > nb)
                nb = bar + 1;
        } else {
            if (n || bar + 1 > na)
                na = bar + 1;
        }
        TR8_PTN2_SET(0, CHAIN_COUNTS, na | (nb << 4));
    }
    /* Hand the bar to the sequencer last: it may already be running, and this is the value that
     * makes the next bar boundary play the bar just selected (see chain_var). */
    chain_tog ^= 0x10;
    chain_jump = (uint8_t)((bar + 1) | chain_tog | (b << 5));
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
    sync();                            /* every press: the panel may have switched pattern */
    if ((unsigned)id < 16) {
        int a, b;

        if ((unsigned)id >= NBARS)
            goto stock;
        a = TR8_BTN_HELD(TR8_BTN_VARI_A) == 1;
        b = TR8_BTN_HELD(TR8_BTN_VARI_B) == 1;
        if ((a || b) && !TR8_BTN_HELD(TR8_BTN_LAST_STEP)) {
            chain_edit(id, a, b);
            chain_swallow |= (uint8_t)(1u << id);
            return 1;                          /* taken: the screen never sees this pad */
        }
    }
stock:
    return TR8_FN_BTN_PRESS(id);
}

/* Replaces "bl FUN_60013B56" at 0x600137D2: button release, id in r0. */
int chain_release(int id)
{
    int r;

    if ((unsigned)id < 16 && (chain_swallow & (1u << id))) {
        chain_swallow &= (uint8_t)~(1u << id);
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
 * While this pattern has a side sequence the working copy is one bar, not the pattern, so it is
 * appended to the log instead of being copied over area 4 slot n+1; that slot keeps the
 * pattern's own A/B steps, which is what an unrecorded bar plays. area 6 (weak accents, flams,
 * this pattern's chain) is saved as before. Without a side sequence, and for a pattern the panel
 * only just selected (the firmware saves it before the patch has loaded a bar), the working copy
 * is the pattern itself and the stock commit is the right thing. */
void chain_commit(int a, int area, int slot, int b)
{
    /* Redirect only while this pattern has a side sequence. With no sequence the working copy
     * is the pattern itself (sync/pattern_load loaded it there), so the stock commit is right
     * and its slot keeps the pattern across an update/reflash. */
    if (area == TR8_AREA_PATTERN && slot >= 1 && slot - 1 == (int)cur_pat &&
        (clen(0) || clen(1))) {
        store_save(slot - 1, cur_bar);
        return;
    }
    TR8_FN_COMMIT(a, area, slot, b);
}
