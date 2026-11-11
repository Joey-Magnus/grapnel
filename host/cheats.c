/* (hookshot) Cheats of the mods' Atmosphere cheat files: <mod>/cheats/<build id>.txt of each mod that was on at the start
   (host/mods.c), the build id the first 8 bytes of the game code's build id in hex (E0F3CCFAF50065AE.txt for 1.1.1), as
   Atmosphere and the emulators name it; the file name's case does not matter. Each cheat is switched in the Insert menu's
   Mods tab; its switch is kept in hookshot_mods.txt ("cheat <key> on|off"), the key "cheat_" and the FNV-1a 32 of
   "<mod folder name>/<cheat name>" (a repeated name "#2", "#3" ...), so two mods' cheats of one name keep their own
   switches. {Master} cheats are always on.

   Data cheats run in a VM after Atmosphere's dmnt cheat VM (opcodes 0-A and C0-C3; C4 and the 0xF.. extensions are not
   supported), at every frame the game presents while their switch is on, with registers and saved registers cleared
   before each cheat; the static registers (C3) stay, shared by all cheats, as dmnt keeps them. Memory is the guest's, at
   its own addresses, and only what the game was given (hos_mem_mapped: the image, the heap, address regions); a read
   outside it ends the cheat's run, a write there is left out. Regions: 0 main (the game's code module), 1 the heap; 2 the
   alias and 3 the ASLR regions have no counterpart here and read as 0 (their cheats find nothing). Writes are marked for
   the GPU's copies as the game's own are (HOS_WRITTEN). Buttons are the HidNpadButton bits the game was last given (the
   cheat format's key masks); they read 0 while the menu is open, as the game's input does.
   A cheat that writes the game's code (opcode 0 below the end of main's code) cannot work here: the code is compiled ahead
   of time, so it is listed as not supported. Make it an ExeFS patch (.pchtxt) instead.

   From valentderah/totk-pc-recomp runtime/cheats.c (MIT; the notice is in host/restbl.h), Copyright (c) 2026 Valiantsin
   Dzerakh: the VM, the opcodes' lengths and the file's parse. */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int hos_mem_mapped(uint64_t addr, uint64_t n);   /* hos_mem.c */
int hos_mod_cheats_dir(int i, char *out, size_t cap, const char **name);   /* mods.c */
int hos_mods_count(void);
void hos_mod_cheat_count(const char *name, int n);
int hos_mods_cheat_switch(const char *key, int otherwise);
void hos_mods_cheat_set(const char *key, int on);
extern volatile uint64_t hos_hid_buttons;   /* nn_hid.c */
extern const char hos_main_build_id[];      /* gen/hos_image.c */
extern const uint64_t hos_main_base, hos_main_size, hos_main_code_end;
int rx_option(int id, int otherwise);

enum { CHEAT_HEADING, CHEAT_DATA, CHEAT_MASTER, CHEAT_UNSUPPORTED };   /* (the Mods tab's kinds: MkwVkCheat.kind) */
enum { OPS_PER_RUN = 1 << 20 };

typedef struct {
    char *name, *mod, key[24], note[96];
    uint32_t *words;
    int n, kind;
    volatile LONG on;
} Cheat;

static Cheat *g_cheats;
static int g_n, g_cap, g_vm;
static uint64_t g_static[256];   /* C3's static registers: 0x00-0x7F loaded by cheats, 0x80-0xFF stored by them */

static uint32_t fnv(const char *s, size_t n) {
    uint32_t h = 0x811C9DC5u;
    for (size_t i = 0; i < n; i++) h = (h ^ (uint8_t)s[i]) * 0x01000193u;
    return h;
}

/* ---- opcodes */

/* Words of the opcode at w (left words remain), 0 when it is cut short */
static int op_len(const uint32_t *w, int left) {
    uint32_t f = w[0];
    int t = f >> 28, width = (f >> 24) & 0xF, n;
    switch (t) {
    case 0: case 1: n = width == 8 ? 4 : 3; break;
    case 2: case 8: n = 1; break;
    case 3: n = width == 0 ? 2 : 1; break;
    case 4: case 6: n = 3; break;
    case 5: case 7: n = 2; break;
    case 9: n = 1 + (((f >> 8) & 0xF) ? (width == 8 ? 2 : 1) : 0); break;
    case 0xA: n = ((f >> 8) & 0xF) == 2 || ((f >> 8) & 0xF) == 4 || ((f >> 8) & 0xF) == 5 ? 2 : 1; break;
    case 0xC:   /* C0TcSX..: an address word for operand types 0 and 2, the value (two words at width 8) for 4 */
        if (((f >> 24) & 0xF) != 0) n = 1;
        else if (((f >> 8) & 0xF) == 0 || ((f >> 8) & 0xF) == 2) n = 2;
        else n = ((f >> 8) & 0xF) == 4 ? (((f >> 20) & 0xF) == 8 ? 3 : 2) : 1;
        break;
    default: n = 1; break;
    }
    return n <= left ? n : 0;
}

/* NULL when the VM runs the opcode, else why not */
static const char *vm_unsupported(const uint32_t *w, char *buf, int n) {
    uint32_t f = w[0];
    int t = f >> 28, width = (f >> 24) & 0xF;
    int ext = f >> 24;   /* 0xC0-0xC3 run; C0's width is at bits 20-23 and its operand type (at most 5) at bits 8-11 */
    if (ext == 0xC0) t = -1, width = (f >> 20) & 0xF;
    if ((t > 0xA && (ext < 0xC1 || ext > 0xC3)) || (t == -1 && ((f >> 8) & 0xF) > 5) ||
        (t == 5 && ((f >> 12) & 0xF) > 1) || (t == 0xA && ((f >> 8) & 0xF) > 5)) {
        snprintf(buf, n, "opcode %08X is not supported", f);
        return buf;
    }
    if ((t <= 1 || t == 5 || t == 6 || t == 7 || t == 9 || t == 0xA) && width != 1 && width != 2 && width != 4 &&
        width != 8) {   /* C0 too (t -1) */
        snprintf(buf, n, "opcode %08X has a bad width", f);
        return buf;
    }
    return NULL;
}

/* heading, data, or unsupported (note says why: an opcode the VM does not run, or a write into the game's code) */
static int classify(Cheat *c) {
    int ops = 0, ends = 0;
    for (int i = 0; i < c->n;) {
        int len = op_len(c->words + i, c->n - i);
        if (!len) {
            snprintf(c->note, sizeof c->note, "opcode %08X is cut short", c->words[i]);
            return CHEAT_UNSUPPORTED;
        }
        uint32_t f = c->words[i];
        ops++;
        ends += f >> 28 == 2;
        if (f >> 28 == 0 && ((f >> 20) & 0xF) == 0) {   /* (a store into main: its code is compiled, not written) */
            uint64_t off = ((uint64_t)(f & 0xFF) << 32) | c->words[i + 1];
            if (off < hos_main_code_end - hos_main_base) {
                snprintf(c->note, sizeof c->note, "it changes the game's code (make it an ExeFS patch instead)");
                return CHEAT_UNSUPPORTED;
            }
        }
        if (vm_unsupported(c->words + i, c->note, sizeof c->note)) return CHEAT_UNSUPPORTED;
        i += len;
    }
    return ops == ends && ops <= 1 ? CHEAT_HEADING : CHEAT_DATA;
}

/* ---- guest memory */

static uint64_t region(int m) {
    switch (m) {
    case 0: return hos_main_base;
    case 1: return HOS_HEAP_BASE;
    default: return 0;   /* (the alias and ASLR regions: none here) */
    }
}

static int rd(uint64_t a, int width, uint64_t *v) {
    if (!a || !hos_mem_mapped(a, (uint64_t)width)) return 0;
    uint64_t x = 0;
    memcpy(&x, GP(a), (size_t)width);
    *v = x;
    return 1;
}

static void wr(uint64_t a, int width, uint64_t v) {
    uint64_t now;
    if (!rd(a, width, &now) || !memcmp(&now, &v, (size_t)width)) return;   /* (unchanged: no write) */
    if (a >= hos_main_base && a < hos_main_code_end) return;   /* (the code: compiled, never read from here) */
    memcpy(GP(a), &v, (size_t)width);
    HOS_WRITTEN(GP(a), (size_t)width);
}

static uint64_t masked(int width, uint64_t v) { return width >= 8 ? v : v & ((1ull << (8 * width)) - 1); }

static uint64_t arith(int op, uint64_t a, uint64_t b) {
    switch (op) {
    case 0: return a + b;
    case 1: return a - b;
    case 2: return a * b;
    case 3: return b < 64 ? a << b : 0;
    case 4: return b < 64 ? a >> b : 0;
    case 5: return a & b;
    case 6: return a | b;
    case 7: return ~a;
    case 8: return a ^ b;
    default: return a;   /* 9: move */
    }
}

static int compare(int cond, uint64_t a, uint64_t b) {
    switch (cond) {
    case 1: return a > b;
    case 2: return a >= b;
    case 3: return a < b;
    case 4: return a <= b;
    case 5: return a == b;
    case 6: return a != b;
    default: return 0;
    }
}

/* From i (after a failed condition, or an else reached while running), the opcode to continue at: after the matching else
   (else_ok) or end. Conditions 1, 8 and C0 open a block, as in Atmosphere's dmnt (CheatVirtualMachine::SkipConditionalBlock),
   which steps over whole opcodes so that an operand word reading 20000000 ends nothing */
static int skip(const uint32_t *w, int n, int i, int else_ok) {
    int depth = 0;
    while (i < n) {
        int len = op_len(w + i, n - i);
        if (!len) return n;
        uint32_t f = w[i];
        int t = f >> 28;
        i += len;
        if (t == 1 || t == 8 || f >> 24 == 0xC0) depth++;
        else if (t == 2 && ((f >> 24) & 0xF) == 1) {   /* else; any other 2x000000 ends, as dmnt decodes is_else */
            if (depth == 0 && else_ok) return i;
        } else if (t == 2 && depth-- == 0) {
            return i;
        }
    }
    return n;
}

static uint64_t imm64(const uint32_t *w) { return (uint64_t)w[0] << 32 | w[1]; }

/* C0TcSX..: if register S <cond c> operand X, all cut to width T (dmnt's BeginRegisterConditionalBlock). X: 0 region M + a,
   1 region M + register r, 2 register R + a, 3 register R + register r, 4 the value V, 5 register R. A read the guest cannot
   make compares as 0, as in dmnt */
static int reg_cond(const uint32_t *w, const uint64_t *r) {
    uint32_t f = w[0];
    int width = (f >> 20) & 0xF, cond = (f >> 16) & 0xF, a4 = (f >> 4) & 0xF, a0 = f & 0xF;
    uint64_t src = masked(width, r[(f >> 12) & 0xF]), b = 0, addr;
    switch ((f >> 8) & 0xF) {
    case 0: addr = region(a4) + (((uint64_t)a0 << 32) | w[1]); break;
    case 1: addr = region(a4) + r[a0]; break;
    case 2: addr = r[a4] + (((uint64_t)a0 << 32) | w[1]); break;
    case 3: addr = r[a4] + r[a0]; break;
    case 4: return compare(cond, src, width == 8 ? imm64(w + 1) : masked(width, w[1]));
    default: return compare(cond, src, masked(width, r[a4]));
    }
    if (!rd(addr, width, &b)) b = 0;
    return compare(cond, src, b);
}

/* one run of a cheat's opcodes; keys: the buttons held */
static void run(const Cheat *c, uint64_t keys) {
    uint64_t r[16] = {0}, saved[16] = {0};
    int loop[16] = {0};
    const uint32_t *w = c->words;
    int n = c->n, budget = OPS_PER_RUN;
    for (int i = 0; i < n && budget-- > 0;) {
        int len = op_len(w + i, n - i);
        if (!len) return;
        uint32_t f = w[i];
        int t = f >> 28, width = (f >> 24) & 0xF, x = (f >> 20) & 0xF, y = (f >> 16) & 0xF, z = (f >> 12) & 0xF;
        uint64_t rel = ((uint64_t)(f & 0xFF) << 32) | (len > 1 ? w[i + 1] : 0), v;
        switch (t) {
        case 0:   /* 0TMR00AA AAAAAAAA V..: store a value at region M + A + register R */
            wr(region(x) + rel + r[y], width, width == 8 ? imm64(w + i + 2) : w[i + 2]);
            break;
        case 1:   /* 1TMC00AA AAAAAAAA V..: if (region M + A) <cond C> V */
            if (!rd(region(x) + rel, width, &v) || !compare(y, v, width == 8 ? imm64(w + i + 2) : w[i + 2])) {
                i = skip(w, n, i + len, 1);
                continue;
            }
            break;
        case 2:   /* 20000000 end, 21000000 else: an else reached while running skips to the end */
            if (width == 1) {
                i = skip(w, n, i + len, 0);
                continue;
            }
            break;
        case 3:   /* 300R0000 VVVVVVVV loop start, 310R0000 loop end */
            if (width == 0) {
                r[y] = w[i + 1];
                loop[y] = i + len;
            } else if (r[y] && --r[y]) {
                i = loop[y];
                continue;
            }
            break;
        case 4:   /* 400R0000 V V: register R = V */
            r[y] = imm64(w + i + 1);
            break;
        case 5:   /* 5TMRI0AA AAAAAAAA: R = (I ? R : region M) + A, read */
            if (!rd(z ? r[y] + rel : region(x) + rel, width, &v)) return;   /* (a broken pointer chain: nothing more) */
            r[y] = v;
            break;
        case 6: {   /* 6T0RIor0 V V: store V at R (+ register r); I: R += width */
            uint64_t a = r[y] + (((f >> 8) & 0xF) ? r[(f >> 4) & 0xF] : 0);
            wr(a, width, imm64(w + i + 1));
            if (z) r[y] += (uint64_t)width;
            break;
        }
        case 7:   /* 7T0RC000 VVVVVVVV: R = R <op C> V */
            r[y] = masked(width, arith(z, r[y], w[i + 1]));
            break;
        case 8:   /* 8kkkkkkk: if the buttons are held */
            if ((keys & (f & 0x0FFFFFFF)) != (f & 0x0FFFFFFF)) {
                i = skip(w, n, i + len, 1);
                continue;
            }
            break;
        case 9: {   /* 9TCRS0s0 / 9TCRS100 V..: R = S <op C> (s or V) */
            uint64_t b = (f >> 8) & 0xF ? (width == 8 ? imm64(w + i + 1) : w[i + 1]) : r[(f >> 4) & 0xF];
            r[y] = masked(width, arith(x, r[z], b));
            break;
        }
        case 0xA: {   /* ATSRIOxa (aaaaaaaa): store register S at an address of type O */
            int o = (f >> 8) & 0xF, m = (f >> 4) & 0xF;
            uint64_t imm = ((uint64_t)(f & 0xF) << 32) | (len > 1 ? w[i + 1] : 0), a;
            switch (o) {
            case 0: a = r[y]; break;
            case 1: a = r[y] + r[m]; break;
            case 2: a = r[y] + imm; break;
            case 3: a = region(m) + r[y]; break;
            case 4: a = region(m) + imm; break;
            default: a = region(m) + r[y] + imm; break;
            }
            wr(a, width, r[x]);
            if (z) r[y] += (uint64_t)width;
            break;
        }
        case 0xC:   /* C1-C3 as dmnt's Execute runs SaveRestoreRegister(Mask) and ReadWriteStaticRegister */
            switch (f >> 24) {
            case 0xC0:
                if (!reg_cond(w + i, r)) {
                    i = skip(w, n, i + len, 1);
                    continue;
                }
                break;
            case 0xC1: {   /* C10D0Sx0: x 0 register D = saved S, 1 saved D = register S, 2 saved D = 0, 3 register D = 0 */
                int d = (f >> 16) & 0xF, s = (f >> 8) & 0xF, op = (f >> 4) & 0xF;
                if (op == 1) saved[d] = r[s];
                else if (op == 2) saved[d] = 0;
                else if (op == 3) r[d] = 0;
                else r[d] = saved[s];   /* (dmnt restores for any other x too) */
                break;
            }
            case 0xC2: {   /* C2x0XXXX: for each register in the mask X, x as C1 with D = S = that register */
                int op = (f >> 20) & 0xF;
                for (int k = 0; k < 16; k++) {
                    if (!(f >> k & 1)) continue;
                    if (op == 1) saved[k] = r[k];
                    else if (op == 2) saved[k] = 0;
                    else if (op == 3) r[k] = 0;
                    else r[k] = saved[k];
                }
                break;
            }
            case 0xC3: {   /* C3000XXx: static register XX < 0x80 into register x, else register x into it */
                int s = (f >> 4) & 0xFF;
                if (s < 0x80) r[f & 0xF] = g_static[s];
                else g_static[s] = r[f & 0xF];
                break;
            }
            default:
                return;
            }
            break;
        default:
            return;
        }
        i += len;
    }
}

/* ---- the files */

static void add_word(Cheat *c, uint32_t v, int *cap) {
    if (c->n == *cap) {
        *cap = *cap ? *cap * 2 : 16;
        c->words = (uint32_t *)realloc(c->words, sizeof *c->words * (size_t)*cap);
    }
    c->words[c->n++] = v;
}

/* the cheats of one mod's file appended; mod: its folder name (kept) */
static void parse(char *s, const char *mod) {
    int first = g_n, wcap = 0;
    for (char *line = s; line && *line;) {
        char *end = strchr(line, '\n'), *next = end ? end + 1 : NULL;
        if (end) *end = 0;
        while (*line == ' ' || *line == '\t') line++;
        size_t len = strlen(line);
        while (len && (line[len - 1] == '\r' || line[len - 1] == ' ' || line[len - 1] == '\t')) line[--len] = 0;
        if (len >= 2 && (line[0] == '[' || line[0] == '{') && (line[len - 1] == ']' || line[len - 1] == '}')) {
            if (g_n == g_cap) {
                g_cap = g_cap ? g_cap * 2 : 32;
                g_cheats = (Cheat *)realloc(g_cheats, sizeof *g_cheats * (size_t)g_cap);
            }
            Cheat *c = &g_cheats[g_n++];
            memset(c, 0, sizeof *c);
            line[len - 1] = 0;
            char *name = line + 1;
            while (*name == ' ' || *name == '\t') name++;
            size_t k = strlen(name);
            while (k && (name[k - 1] == ' ' || name[k - 1] == '\t')) name[--k] = 0;
            c->name = _strdup(name);
            c->mod = (char *)mod;
            c->kind = line[0] == '{' ? CHEAT_MASTER : CHEAT_HEADING;
            int dup = 1;   /* (a repeated name: "#2", "#3" ... in its key) */
            for (int j = first; j < g_n - 1; j++) dup += !strcmp(g_cheats[j].name, c->name);
            char named[600];
            snprintf(named, sizeof named, dup > 1 ? "%s/%s#%d" : "%s/%s", mod, c->name, dup);
            snprintf(c->key, sizeof c->key, "cheat_%08x", fnv(named, strlen(named)));
            wcap = 0;
        } else if (g_n > first) {
            for (char *tok = strtok(line, " \t"); tok; tok = strtok(NULL, " \t")) {
                char *e;
                unsigned long v = strtoul(tok, &e, 16);
                if (e - tok == 8 && !*e) add_word(&g_cheats[g_n - 1], (uint32_t)v, &wcap);
            }
        }
        line = next;
    }
}

/* the file named <build id>.txt (any case) in folder, into out */
static int find_file(const char *folder, const char *file, char *out, size_t cap) {
    char pat[MAX_PATH];
    snprintf(pat, sizeof pat, "%s/*", folder);
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA(pat, &fd);
    if (f == INVALID_HANDLE_VALUE) return 0;
    int found = 0;
    do found = !(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && !_stricmp(fd.cFileName, file);
    while (!found && FindNextFileA(f, &fd));
    FindClose(f);
    if (found) snprintf(out, cap, "%s/%s", folder, fd.cFileName);
    return found;
}

/* hos_main.c, after hos_mods_init */
void hos_cheats_init(void) {
    char file[32];
    snprintf(file, sizeof file, "%.16s.txt", hos_main_build_id);
    for (char *p = file; *p; p++) *p = (char)(*p >= 'a' && *p <= 'f' ? *p - 32 : *p);
    int files = 0;
    for (int k = 0; k < hos_mods_count(); k++) {   /* (the list's order) */
        char dir[MAX_PATH], path[MAX_PATH];
        const char *mod;
        if (!hos_mod_cheats_dir(k, dir, sizeof dir, &mod)) continue;
        if (!find_file(dir, file, path, sizeof path)) {
            hos_log("cheats: %s: no %s in its cheats folder (the cheats of this game version)", mod, file);
            continue;
        }
        FILE *f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END);
        const long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        char *text = n >= 0 && n < (4 << 20) ? (char *)malloc((size_t)n + 1) : NULL;
        if (text) text[fread(text, 1, (size_t)n, f)] = 0;
        fclose(f);
        if (!text) continue;
        const int before = g_n;
        parse(!strncmp(text, "\xEF\xBB\xBF", 3) ? text + 3 : text, _strdup(mod));
        free(text);
        hos_mod_cheat_count(mod, g_n - before);
        files++;
    }
    int counts[4] = {0}, on = 0;
    for (int i = 0; i < g_n; i++) {
        Cheat *c = &g_cheats[i];
        const int master = c->kind == CHEAT_MASTER;
        c->kind = classify(c);
        if (master && c->kind == CHEAT_DATA) c->kind = CHEAT_MASTER;
        c->on = c->kind == CHEAT_MASTER || (c->kind == CHEAT_DATA && hos_mods_cheat_switch(c->key, 0));
        g_vm |= c->on;
        on += c->on;
        counts[c->kind]++;
        if (c->kind == CHEAT_UNSUPPORTED) hos_log("cheats: %s/%s: not supported: %s", c->mod, c->name, c->note);
    }
    if (files)
        hos_log("cheats: %s in %d mods: %d cheats, %d on; %d data, %d master, %d headings, %d not supported", file, files, g_n, on,
                counts[CHEAT_DATA], counts[CHEAT_MASTER], counts[CHEAT_HEADING], counts[CHEAT_UNSUPPORTED]);
}

/* nn_vi.c, at each frame the game presents: the cheats that are on */
void hos_cheats_frame(void) {
    if (!g_vm) return;
    static int64_t frames;
    if (++frames < 60) return;   /* (the game's first frames: nothing it set up yet) */
    const uint64_t keys = rx_option(1, 0) ? 0 : hos_hid_buttons;
    for (int i = 0; i < g_n; i++)
        if (g_cheats[i].on && (g_cheats[i].kind == CHEAT_DATA || g_cheats[i].kind == CHEAT_MASTER)) run(&g_cheats[i], keys);
}

/* the Mods tab: cheat i, its kind and switch; 0 past the end */
int hos_cheat_info(int i, const char **name, const char **mod, const char **note, int *kind, int *on) {
    if (i < 0 || i >= g_n) return 0;
    *name = g_cheats[i].name, *mod = g_cheats[i].mod, *note = g_cheats[i].note, *kind = g_cheats[i].kind;
    *on = g_cheats[i].on != 0;
    return 1;
}

void hos_cheat_set(int i, int on) {
    if (i < 0 || i >= g_n || g_cheats[i].kind != CHEAT_DATA) return;
    InterlockedExchange(&g_cheats[i].on, on != 0);
    if (on) g_vm = 1;
    hos_mods_cheat_set(g_cheats[i].key, on != 0);
    hos_log("cheats: %s/%s %s", g_cheats[i].mod, g_cheats[i].name, on ? "on" : "off");
}
