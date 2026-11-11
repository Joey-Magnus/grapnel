/* Mods, in the layout emulators use, so RomFS mods made for them work as they are:
     <mods>/<name>/romfs/...          files that replace (or add to) the game's RomFS
     <mods>/<name>/exefs/*.ips        ExeFS patches (IPS, IPS32, IPSwitch .pchtxt) for the game's code
     <mods>/<name>/cheats/<id>.txt    Atmosphere cheats (host/cheats.c), <id> the first 8 bytes of the code's build id
   <mods> is the "mods" folder beside the executable, or HOS_MODS=<dir>. A mod may sit deeper, as emulators keep them
   (<mods>/contents/<title id>/<name>/romfs): any folder holding a romfs, exefs or cheats folder is a mod. Folders whose names
   start with '-' or '_' are left out (off).
   (hookshot) The order and the switches: the Insert menu's Mods tab, kept in hookshot_mods.txt in the game folder (one line a
   mod, "on <name>" or "off <name>", in the list's order; lines "cheat <key> on|off" for the cheats). A mod the file does not
   name goes after the named ones, by name, and is on: with no file the order is the folders' names. When two mods have the
   same file, the one lower in the list wins (with no file: the one whose name sorts last, as before). A change in the menu
   applies at the next start (what the game reads is indexed at the start).
   Every mod file is indexed once at the start (no disk lookups per open); nn_fs.c asks hos_mods_romfs for each rom:
   path and lists a folder's mod-only entries with the game's own (hos_mods_dir_extras). HOS_FS_OVERLAY (nn_fs.c) is
   looked at after this, so a test overlay wins over mods.
   (hookshot) The resource size table (restbl.h): when the mods serve files, the game's table (or the button prompts' copy of
   it) is served with every enabled mod's own table merged in (an entry larger than the game's wins) and the entry of every file
   a mod serves raised to what its size needs: two mods that each grow files load together. Written to
   modcache/rsizetable.zs in the game folder at each start that needs it (merge_sizes).
   (hookshot) ExeFS patches are applied when the game is built (nx2/exefs_patches.py: the code is compiled ahead of time from
   the patched instructions, their data writes are in image.bin). The build lists what it applied in exefs_patches.txt in the
   game folder; a patch file the list does not have with the same contents waits for the next build, and the menu says so.
   From Skybound's loader (NotRexed/SkyboundTotk a64-kit/hos/mods.c, MIT): its RomFS part. The list, its order and switches and
   the size table's merge after valentderah/totk-pc-recomp runtime/mods.c and romfs.c (MIT, Copyright (c) 2026 Valiantsin
   Dzerakh; the notice is in restbl.h). */
#include "hos.h"
#include "hos_paths.h"
#include "restbl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

uint8_t *hos_zs_read(const char *path, size_t *n, size_t limit);   /* zs.c */
uint64_t hos_zs_content_size(const char *path);
int hos_zs_write(const char *path, const uint8_t *data, size_t n);
extern const char *hos_romfs_dir;   /* nn_fs.c */

typedef struct { char *key; char *host; char *rel; uint64_t size; int is_dir, logged, mod; } Entry;   /* key: romfs path, lower case, '/' */
static Entry *table;
static size_t table_cap, table_n;

static uint64_t hash_str(const char *s) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (; *s; s++) h = (h ^ (uint8_t)*s) * 0x100000001b3ull;
    return h;
}
static void lower_slash(char *s) {
    for (; *s; s++) *s = *s == '\\' ? '/' : (char)tolower((unsigned char)*s);
}
static const char *last_sep(const char *s) {   /* (a host path: '\' on Windows, '/' from host/posix) */
    const char *b = strrchr(s, '\\'), *f = strrchr(s, '/');
    return b > f ? b : f;
}
static Entry *find(const char *key) {
    if (!table_cap) return NULL;
    for (size_t i = hash_str(key) & (table_cap - 1);; i = (i + 1) & (table_cap - 1)) {
        if (!table[i].key) return NULL;
        if (!strcmp(table[i].key, key)) return &table[i];
    }
}

/* ---- the mods: the folders under root, in the list's order (a mod: a folder holding romfs, exefs or cheats) */
typedef struct {
    char path[MAX_PATH], name[MAX_PATH];
    int enabled, start_enabled;
    int romfs, exefs, cheats;               /* what it has */
    int files, replaced, added, overridden; /* its RomFS files; those the game has, those it has not; those a mod below takes */
    int exefs_files, exefs_built, exefs_waiting, exefs_other, exefs_bad;   /* its ExeFS patch files, by their state */
    char exefs_note[160];
    int cheat_count;                        /* cheats.c: the cheats of its file */
    char detail[320], note[320];            /* the Mods tab's lines (mod_text) */
} Mod;
static Mod *mods;
static int nmods, cap_mods;
static char root_dir[MAX_PATH], state_path[MAX_PATH], cache_dir[MAX_PATH];
static uint64_t start_key;   /* the order and the switches at the start: mods_state_key */

static void put(const char *key, const char *host, const char *rel, uint64_t size, int is_dir, int mod) {
    if ((table_n + 1) * 2 > table_cap) {   /* (grow: rehash) */
        Entry *old = table;
        const size_t old_cap = table_cap;
        table_cap = table_cap ? table_cap * 2 : 1024;
        table = (Entry *)calloc(table_cap, sizeof *table);
        table_n = 0;
        for (size_t i = 0; i < old_cap; i++)
            if (old[i].key) {
                size_t j = hash_str(old[i].key) & (table_cap - 1);
                while (table[j].key) j = (j + 1) & (table_cap - 1);
                table[j] = old[i];
                table_n++;
            }
        free(old);
    }
    size_t i = hash_str(key) & (table_cap - 1);
    while (table[i].key && strcmp(table[i].key, key)) i = (i + 1) & (table_cap - 1);
    if (!table[i].key) {
        table[i].key = _strdup(key), table_n++;
    } else {
        if (!is_dir && !table[i].is_dir && table[i].mod >= 0 && table[i].mod != mod) mods[table[i].mod].overridden++;
        free(table[i].host);
        free(table[i].rel);
    }
    table[i].host = _strdup(host);
    table[i].rel = _strdup(rel);
    table[i].size = size;
    table[i].is_dir = is_dir;
    table[i].mod = mod;
}

/* (hookshot) the size tables the mods carry: those for this game version (the game's own name) are merged into it, those for
   another version give only their entries for the files their own mod serves */
typedef struct { char *host, *key; int mod, other; } Shipped;
static Shipped *shipped;
static int nshipped;
static char sizes_rel[MAX_PATH];   /* the game's table, its RomFS path ("System/Resource/ResourceSizeTable...zs"), "" none */
static char sizes_key[MAX_PATH];   /* the same, lower case */
static char sizes_served[MAX_PATH];   /* the table served in the game's place: the merged one, or a mod's as it is (merge_failed) */
static int sizes_merged;              /* sizes_served is the merged table */
static char sizes_fallback[MAX_PATH]; /* no merge: the last enabled mod's own table for this version, served as host/prompts.c makes it */
static int is_sizes(const char *key) {   /* (any version's: lower case) */
    const size_t n = strlen(key);
    return !strncmp(key, "system/resource/resourcesizetable.", 34) && n > 14 && !strcmp(key + n - 14, ".rsizetable.zs");
}

/* the game file a RomFS path names: 1 with its host path */
static int game_file(const char *rel, char *out, size_t cap) {
    if (!hos_romfs_dir) return 0;
    snprintf(out, cap, "%s/%s", hos_romfs_dir, rel);
    const DWORD at = GetFileAttributesA(out);
    return at != INVALID_FILE_ATTRIBUTES && !(at & FILE_ATTRIBUTE_DIRECTORY);
}

/* a mod's romfs folder, recursively: rel is the path inside the RomFS so far ("" at its root) */
static int index_romfs(const char *host_dir, const char *rel, int depth, int mod) {
    if (depth > 32) return 0;   /* (hookshot: no RomFS is this deep) */
    if (!depth) {   /* (hookshot) the romfs folder itself a link (to / in a mod's archive): the walk covered the whole disk */
        const DWORD at = GetFileAttributesA(host_dir);
        if (at != INVALID_FILE_ATTRIBUTES && (at & FILE_ATTRIBUTE_REPARSE_POINT)) {
            hos_log("mods: %s is a link to a folder: left out", host_dir);
            return 0;
        }
    }
    char pat[MAX_PATH];
    snprintf(pat, sizeof pat, "%s\\*", host_dir);
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA(pat, &fd);
    if (f == INVALID_HANDLE_VALUE) return 0;
    int files = 0;
    do {
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, "..")) continue;
        char host[MAX_PATH], key[MAX_PATH], sub_rel[MAX_PATH];
        snprintf(host, sizeof host, "%s\\%s", host_dir, fd.cFileName);
        /* (hookshot) a link to a folder is not followed (two links back up made the walk endless); links to files are
           (mod managers place files as links) */
        if ((fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) && (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
            hos_log("mods: %s is a link to a folder: left out", host);
            continue;
        }
        snprintf(sub_rel, sizeof sub_rel, "%s%s%s", rel, *rel ? "/" : "", fd.cFileName);
        snprintf(key, sizeof key, "%s", sub_rel);
        lower_slash(key);
        const int is_dir = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
        if (!is_dir && is_sizes(key)) {   /* (a size table: merged, never served as it is) */
            shipped = (Shipped *)realloc(shipped, sizeof *shipped * (size_t)(nshipped + 1));
            shipped[nshipped++] = (Shipped){_strdup(host), _strdup(key), mod, strcmp(key, sizes_key) != 0};
            for (char *p = shipped[nshipped - 1].host; *p; p++) if (*p == '\\') *p = '/';   /* (read with fopen: hos_zs_read) */
            continue;   /* (not one of its files: the merged table is served in the game's) */
        }
        put(key, host, sub_rel, ((uint64_t)fd.nFileSizeHigh << 32) | fd.nFileSizeLow, is_dir, mod);
        if (is_dir) {
            files += index_romfs(host, sub_rel, depth + 1, mod);
        } else {
            char game[MAX_PATH];
            if (game_file(sub_rel, game, sizeof game)) mods[mod].replaced++;
            else mods[mod].added++;
            files++;
        }
    } while (FindNextFileA(f, &fd));
    FindClose(f);
    return files;
}

static int dir_exists(const char *path) {
    const DWORD at = GetFileAttributesA(path);
    return at != INVALID_FILE_ATTRIBUTES && (at & FILE_ATTRIBUTE_DIRECTORY);
}

static void find_mods(const char *dir, const char *name, int depth) {
    char probe[MAX_PATH];
    snprintf(probe, sizeof probe, "%s\\romfs", dir);
    const int has_romfs = dir_exists(probe);
    snprintf(probe, sizeof probe, "%s\\exefs", dir);
    const int has_exefs = dir_exists(probe);
    snprintf(probe, sizeof probe, "%s\\cheats", dir);
    const int has_cheats = dir_exists(probe);
    if ((has_romfs || has_exefs || has_cheats) && depth > 0) {
        if (nmods == cap_mods) mods = (Mod *)realloc(mods, sizeof *mods * (size_t)(cap_mods = cap_mods ? cap_mods * 2 : 16));
        Mod *m = &mods[nmods++];
        memset(m, 0, sizeof *m);
        snprintf(m->path, MAX_PATH, "%s", dir);
        snprintf(m->name, MAX_PATH, "%s", name);
        m->romfs = has_romfs, m->exefs = has_exefs, m->cheats = has_cheats;
        m->enabled = 1;
        return;
    }
    if (depth >= 4) return;
    char pat[MAX_PATH];
    snprintf(pat, sizeof pat, "%s\\*", dir);
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA(pat, &fd);
    if (f == INVALID_HANDLE_VALUE) return;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.cFileName[0] == '.') continue;
        if (fd.cFileName[0] == '-' || fd.cFileName[0] == '_') {
            hos_log("mods: %s\\%s is off (its name starts with %c)", dir, fd.cFileName, fd.cFileName[0]);
            continue;
        }
        char sub[MAX_PATH], sub_name[MAX_PATH];
        snprintf(sub, sizeof sub, "%s\\%s", dir, fd.cFileName);
        snprintf(sub_name, sizeof sub_name, "%s%s%s", name, *name ? "/" : "", fd.cFileName);
        find_mods(sub, sub_name, depth + 1);
    } while (FindNextFileA(f, &fd));
    FindClose(f);
}
static int mod_cmp(const void *a, const void *b) { return _stricmp(((const Mod *)a)->name, ((const Mod *)b)->name); }

/* ---- hookshot_mods.txt: the order and the switches (and the cheats', cheats.c) */
typedef struct { char *key; int on; } CheatSwitch;
static CheatSwitch *cheat_switches;
static int ncheat_switches;

static char *read_text(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *s = n >= 0 && n < (16 << 20) ? (char *)malloc((size_t)n + 1) : NULL;
    if (s) s[fread(s, 1, (size_t)n, f)] = 0;
    fclose(f);
    return s;
}

/* the list in the file's order (the named first, the rest by name, on), the switches as it says */
static void read_state(void) {
    qsort(mods, (size_t)nmods, sizeof *mods, mod_cmp);
    char *text = read_text(state_path);
    if (!text) return;
    int placed = 0;
    for (char *line = text; line && *line;) {
        char *end = strpbrk(line, "\r\n"), *next = end ? end + strspn(end, "\r\n") : NULL;
        if (end) *end = 0;
        const int on = !strncmp(line, "on ", 3), off = !strncmp(line, "off ", 4);
        if (on || off) {
            const char *name = line + (on ? 3 : 4);
            for (int i = placed; i < nmods; i++)
                if (!strcmp(mods[i].name, name)) {
                    Mod m = mods[i];
                    memmove(&mods[placed + 1], &mods[placed], sizeof *mods * (size_t)(i - placed));
                    m.enabled = on;
                    mods[placed++] = m;
                    break;
                }
        } else if (!strncmp(line, "cheat ", 6)) {
            char key[64], sw[8];
            if (sscanf(line + 6, "%63s %7s", key, sw) == 2) {
                cheat_switches = (CheatSwitch *)realloc(cheat_switches, sizeof *cheat_switches * (size_t)(ncheat_switches + 1));
                cheat_switches[ncheat_switches++] = (CheatSwitch){_strdup(key), !strcmp(sw, "on")};
            }
        }
        line = next;
    }
    free(text);
}

static void write_state(void) {
    if (!state_path[0]) return;
    char tmp[MAX_PATH];
    snprintf(tmp, sizeof tmp, "%s.new", state_path);
    FILE *f = fopen(tmp, "wb");
    if (!f) {
        hos_log("mods: cannot write %s", tmp);
        return;
    }
    fputs("# Hookshot's mods: their order and switches, as the Mods tab sets them (Insert menu). One line a mod, top of the\n"
          "# list first: \"on <folder>\" or \"off <folder>\". A mod lower in the list wins a file two mods have. Applies at the\n"
          "# next start.\n", f);
    for (int i = 0; i < nmods; i++) fprintf(f, "%s %s\n", mods[i].enabled ? "on" : "off", mods[i].name);
    for (int i = 0; i < ncheat_switches; i++) fprintf(f, "cheat %s %s\n", cheat_switches[i].key, cheat_switches[i].on ? "on" : "off");
    const int ok = fclose(f) == 0;
    if (!ok || !MoveFileExA(tmp, state_path, MOVEFILE_REPLACE_EXISTING)) hos_log("mods: cannot write %s", state_path);
}

/* the order and the switches as one number: what the menu compares with the start's */
static uint64_t state_key(void) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (int i = 0; i < nmods; i++) {
        for (const char *p = mods[i].name; *p; p++) h = (h ^ (uint8_t)*p) * 0x100000001b3ull;
        h = (h ^ (uint64_t)(mods[i].enabled ? 0x101 : 0x100)) * 0x100000001b3ull;
    }
    return h;
}

/* ---- ExeFS patches: what the build applied (exefs_patches.txt, nx2/exefs_patches.py) against the files there now */
static uint32_t fnv32_file(const char *path, int *ok) {
    FILE *f = fopen(path, "rb");
    uint32_t h = 0x811C9DC5u;
    *ok = f != NULL;
    if (!f) return h;
    int c;
    while ((c = getc(f)) != EOF) h = (h ^ (uint8_t)c) * 0x01000193u;
    fclose(f);
    return h;
}
static int ends_ci(const char *s, const char *tail) {
    const size_t n = strlen(s), t = strlen(tail);
    return n >= t && !_stricmp(s + n - t, tail);
}

/* each ExeFS patch file of each mod against the build's list: applied (code, data), another game version's, unusable, or
   waiting for the next build; and the files the build applied that are no longer there as they were */
static void exefs_status(const char *game_dir) {
    char list_path[MAX_PATH];
    snprintf(list_path, sizeof list_path, "%sexefs_patches.txt", game_dir);
    char *built = read_text(list_path);
    int stale = 0;
    for (int i = 0; i < nmods; i++) {
        Mod *m = &mods[i];
        if (!m->exefs) continue;
        char pat[MAX_PATH];
        snprintf(pat, sizeof pat, "%s\\exefs\\*", m->path);
        WIN32_FIND_DATAA fd;
        HANDLE f = FindFirstFileA(pat, &fd);
        if (f == INVALID_HANDLE_VALUE) continue;
        do {
            if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || !(ends_ci(fd.cFileName, ".ips") || ends_ci(fd.cFileName, ".pchtxt")))
                continue;
            char path[MAX_PATH], want[MAX_PATH + 64];
            snprintf(path, sizeof path, "%s/exefs/%s", m->path, fd.cFileName);
            for (char *p = path; *p; p++) if (*p == '\\') *p = '/';
            int ok;
            const uint32_t h = fnv32_file(path, &ok);
            if (!ok) continue;
            m->exefs_files++;
            snprintf(want, sizeof want, "%s\t%s\t%08x\t", m->name, fd.cFileName, h);
            const char *line = built ? strstr(built, want) : NULL;
            while (line && line != built && line[-1] != '\n') line = strstr(line + 1, want);
            const char *kind = line ? line + strlen(want) : "";
            if (!line) {
                m->exefs_waiting++;
            } else if (!strncmp(kind, "code", 4) || !strncmp(kind, "data", 4)) {
                m->exefs_built++;
                if (!m->enabled) stale++;
            } else if (!strncmp(kind, "other", 5)) {
                m->exefs_other++;
            } else if (!strncmp(kind, "empty", 5)) {
                m->exefs_built++;
            } else {
                m->exefs_bad++;
                const char *tab = strchr(kind, '\t'), *end = tab ? strchr(tab + 1, '\n') : NULL;
                if (tab && !m->exefs_note[0])
                    snprintf(m->exefs_note, sizeof m->exefs_note, "%.*s", (int)(end ? end - tab - 1 : (long)strlen(tab + 1)), tab + 1);
            }
            hos_log("mods: %s: ExeFS %s: %s", m->name, fd.cFileName, !line ? "not in the game yet: it is applied when the game is built again"
                    : !strncmp(kind, "code", 4) || !strncmp(kind, "data", 4) ? "built into the game"
                    : !strncmp(kind, "other", 5) ? "for another game version: not used"
                    : !strncmp(kind, "empty", 5) ? "changes nothing in this version" : "cannot be applied");
        } while (FindNextFileA(f, &fd));
        FindClose(f);
    }
    if (built) {   /* (applied files whose mod is gone or off: their code stays in the game until it is built again) */
        for (const char *line = built; *line;) {
            const char *end = strchr(line, '\n');
            const size_t len = end ? (size_t)(end - line) : strlen(line);
            const char *tab = memchr(line, '\t', len);
            if (tab && line[0] != '#') {
                const char *kind = line;
                for (int t = 0; t < 3 && kind; t++) kind = memchr(kind, '\t', len - (size_t)(kind - line)), kind = kind ? kind + 1 : NULL;
                int found = 0;
                for (int i = 0; i < nmods && !found; i++)
                    found = strlen(mods[i].name) == (size_t)(tab - line) && !strncmp(mods[i].name, line, (size_t)(tab - line));
                if (!found && kind && (!strncmp(kind, "code", 4) || !strncmp(kind, "data", 4))) stale++;
            }
            line = end ? end + 1 : line + len;
        }
        if (stale)
            hos_log("mods: %d ExeFS patch files built into the game belong to mods that are off or gone: they stay in it until it is "
                    "built again", stale);
    }
    free(built);
}

/* ---- the size table */
static int fit_sizes(const char *game_dir) {
    if (!sizes_rel[0]) return 0;
    int any = nshipped > 0;
    for (size_t i = 0; i < table_cap && !any; i++) any = table[i].key && !table[i].is_dir;
    if (!any) return 0;
    const int64_t t0 = hos_now_ns();
    char path[MAX_PATH];
    size_t n = 0;
    snprintf(path, sizeof path, "%s/%s", hos_romfs_dir, sizes_rel);
    uint8_t *raw = hos_zs_read(path, &n, 64u << 20);
    Restbl *base = raw ? restbl_parse(raw, n) : NULL;
    free(raw);
    /* (what is served without mods: the button prompts' copy where they made one, with room for their fonts; else the game's) */
    /* (prompts.c hos_prompts_romfs serves prompts/rsizetable.zs whenever the build made one: read here, not through it, as its
       first call chooses the controller's face, which is not known yet) */
    char prompts_table[MAX_PATH];
    snprintf(prompts_table, sizeof prompts_table, "%sprompts/rsizetable.zs", game_dir);
    Restbl *out = NULL;
    if ((raw = hos_zs_read(prompts_table, &n, 64u << 20)) != NULL) {
        out = restbl_parse(raw, n);
        free(raw);
    }
    if (!out && (raw = hos_zs_read(path, &n, 64u << 20))) {
        out = restbl_parse(raw, n);
        free(raw);
    }
    if (!base || !out) {   /* (as without the merge: the last enabled mod's own table, sizes_fallback) */
        hos_log("mods: cannot read the resource size table %s: %s", sizes_rel,
                sizes_fallback[0] ? "the last mod's own table is served" : "mod files larger than the game's may not load");
        restbl_free(base);
        restbl_free(out);
        return 0;
    }
    int tables = 0, merged = 0, raised = 0, estimated = 0;
    for (int s = 0; s < nshipped; s++) {
        raw = hos_zs_read(shipped[s].host, &n, 64u << 20);
        Restbl *t = raw ? restbl_parse(raw, n) : NULL;
        free(raw);
        if (!t) {
            hos_log("mods: %s is not a resource size table: left out", shipped[s].host);
            continue;
        }
        tables++;
        if (!shipped[s].other && mods[shipped[s].mod].enabled) {
            merged += restbl_merge(out, base, t);
        } else if (mods[shipped[s].mod].enabled) {   /* (another version's: the entries of its own mod's files) */
            for (size_t i = 0; i < table_cap; i++) {
                char key[MAX_PATH];
                uint32_t size;
                if (table[i].key && !table[i].is_dir && table[i].mod == shipped[s].mod &&
                    restbl_get(t, restbl_key(table[i].rel, key, sizeof key), &size))
                    merged += restbl_raise(out, key, size);
            }
        }
        restbl_free(t);
    }
    for (size_t i = 0; i < table_cap; i++) {   /* (each file a mod serves: the entry its size needs) */
        const Entry *e = &table[i];
        if (!e->key || e->is_dir) continue;
        char key[MAX_PATH], game[MAX_PATH], host[MAX_PATH];
        restbl_key(e->rel, key, sizeof key);
        snprintf(host, sizeof host, "%s", e->host);
        for (char *p = host; *p; p++) if (*p == '\\') *p = '/';
        const int zs = ends_ci(e->rel, ".zs");
        const uint64_t now = zs ? hos_zs_content_size(host) : e->size;
        uint32_t entry, want;
        if (game_file(e->rel, game, sizeof game)) {
            if (!restbl_get(base, key, &entry)) continue;   /* (the game sizes it without the table: streamed) */
            uint64_t was = 0;
            if (zs) was = hos_zs_content_size(game);
            else {
                FILE *g = fopen(game, "rb");
                if (g) fseek(g, 0, SEEK_END), was = (uint64_t)_ftelli64(g), fclose(g);
            }
            want = restbl_grow(key, entry, was, now);
        } else {   /* (a file the game has not: an estimate, unless a mod's own table gives it) */
            uint32_t have;
            if (restbl_get(out, key, &have)) continue;
            want = restbl_estimate(key, now);
            estimated += want != 0;
        }
        raised += want && restbl_raise(out, key, want);
    }
    restbl_free(base);
    int served = 0;
    if (merged || raised) {
        size_t rn = 0;
        uint8_t *bytes = restbl_write(out, &rn);
        CreateDirectoryA(cache_dir, NULL);
        snprintf(sizes_served, sizeof sizes_served, "%srsizetable.zs", cache_dir);
        served = sizes_merged = bytes && hos_zs_write(sizes_served, bytes, rn);
        free(bytes);
        if (!served) {
            hos_log("mods: cannot write %s: the last mod's own table is served, if one has it", sizes_served);
            sizes_served[0] = 0;
        }
    }
    restbl_free(out);
    hos_log("mods: resource size table: %d tables of mods merged (%d entries), %d entries raised for mod files (%d added files "
            "estimated)%s, %.0f ms", tables, merged, raised, estimated, served ? ", served from modcache" : ": the game's fits",
            (hos_now_ns() - t0) / 1e6);
    return served;
}

/* the game's table: the one System/Resource/ResourceSizeTable.*.rsizetable.zs of the RomFS */
static void find_sizes(void) {
    if (!hos_romfs_dir) return;
    char pat[MAX_PATH];
    snprintf(pat, sizeof pat, "%s\\System\\Resource\\ResourceSizeTable.*", hos_romfs_dir);
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA(pat, &fd);
    if (f == INVALID_HANDLE_VALUE) return;
    do {
        if (ends_ci(fd.cFileName, ".rsizetable.zs")) {
            snprintf(sizes_rel, sizeof sizes_rel, "System/Resource/%s", fd.cFileName);
            snprintf(sizes_key, sizeof sizes_key, "%s", sizes_rel);
            lower_slash(sizes_key);
            break;
        }
    } while (FindNextFileA(f, &fd));
    FindClose(f);
}

static void mod_text(Mod *m);

/* hos_main.c, once the image is loaded (image_path: unused; ExeFS patches are applied when the game is built) */
void hos_mods_init(const char *image_path) {
    (void)image_path;
    char game_dir[MAX_PATH];
    hos_game_path_a(game_dir, sizeof game_dir);
    char *slash = (char *)last_sep(game_dir);
    if (!slash) return;
    slash[1] = 0;
    if (getenv("HOS_MODS")) snprintf(root_dir, sizeof root_dir, "%s", getenv("HOS_MODS"));
    else snprintf(root_dir, sizeof root_dir, "%smods", game_dir);
    snprintf(state_path, sizeof state_path, "%shookshot_mods.txt", game_dir);
    snprintf(cache_dir, sizeof cache_dir, "%smodcache/", game_dir);
    if (GetFileAttributesA(root_dir) == INVALID_FILE_ATTRIBUTES) return;
    find_mods(root_dir, "", 0);
    if (!nmods) {
        hos_log("mods: none in %s (a mod: <name>\\romfs, <name>\\exefs or <name>\\cheats)", root_dir);
        return;
    }
    read_state();
    find_sizes();
    for (int i = 0; i < nmods; i++) mods[i].start_enabled = mods[i].enabled;
    start_key = state_key();
    for (int i = 0; i < nmods; i++) {
        Mod *m = &mods[i];
        if (!m->enabled) {
            hos_log("mods: %s: off (the Mods tab)", m->name);
            continue;
        }
        if (m->romfs) {
            char dir[MAX_PATH];
            snprintf(dir, sizeof dir, "%s\\romfs", m->path);
            m->files = index_romfs(dir, "", 0, i);
        }
        hos_log("mods: %s: %d RomFS files (%d replace the game's, %d added)%s%s", m->name, m->files, m->replaced, m->added,
                m->exefs ? ", ExeFS patches" : "", m->cheats ? ", cheats" : "");
    }
    exefs_status(game_dir);
    /* (the table served when no merged one is: the last enabled mod's own, host/prompts.c merging the prompts' entries into it.
       Without the game's RomFS to tell its name, the first table a mod has stands for it) */
    if (!sizes_key[0] && nshipped) {
        snprintf(sizes_key, sizeof sizes_key, "%s", shipped[0].key);
        for (int s = 0; s < nshipped; s++) shipped[s].other = strcmp(shipped[s].key, sizes_key) != 0;
    }
    for (int s = 0; s < nshipped; s++)
        if (!shipped[s].other && mods[shipped[s].mod].enabled) snprintf(sizes_fallback, sizeof sizes_fallback, "%s", shipped[s].host);
    if (fit_sizes(game_dir)) {
        /* (served in the game's table's place: hos_mods_romfs) */
    }
    for (int i = 0; i < nmods; i++) mod_text(&mods[i]);
    hos_log("mods: %d mods from %s: %zu RomFS entries", nmods, root_dir, table_n);
}

/* nn_fs.c: the mod file for a RomFS path ("UI/x.zs", no mount, no leading slash), or 0 */
int hos_mods_romfs(const char *rel, char *out, size_t cap) {
    char key[MAX_PATH];
    snprintf(key, sizeof key, "%s", rel);
    lower_slash(key);
    int hos_prompts_romfs(const char *key, const char *mod, char *out, size_t cap);   /* prompts.c: the button prompts */
    if (sizes_served[0] && !strcmp(key, sizes_key)) {   /* (the merged size table: the prompts' entries are in it) */
        snprintf(out, cap, "%s", sizes_served);
        static volatile LONG told;
        if (InterlockedIncrement(&told) == 1) hos_log("mods: %s <- %s (merged)", rel, sizes_served);
        return 1;
    }
    if (sizes_fallback[0] && !strcmp(key, sizes_key)) {   /* (no merge: the last mod's own table, the prompts' merged in) */
        const int merged = hos_prompts_romfs(key, sizes_fallback, out, cap);
        if (!merged) snprintf(out, cap, "%s", sizes_fallback);
        static volatile LONG told_fallback;
        if (InterlockedIncrement(&told_fallback) == 1)
            hos_log("mods: %s <- %s%s", rel, sizes_fallback, merged ? " (with the button prompts' sizes merged in)" : "");
        return 1;
    }
    Entry *e = table_n ? find(key) : NULL;
    if (!e || e->is_dir) return hos_prompts_romfs(key, NULL, out, cap);
    const int merged = hos_prompts_romfs(key, e->host, out, cap);   /* (the size table: the prompts' entries merged in) */
    if (!merged) snprintf(out, cap, "%s", e->host);
    static volatile LONG logged;
    if (!e->logged && InterlockedIncrement(&logged) <= 200)
        hos_log("mods: %s <- %s%s", rel, e->host, merged ? " (with the button prompts' sizes merged in)" : "");
    e->logged = 1;
    return 1;
}

/* prompts.c: the mod file (out) whose key (lower case, '/') starts with prefix and ends with suffix, 1 with one. The size
   table: none when the merged one is served (it keeps the prompts' entries), else the last mod's own (sizes_fallback) */
int hos_mods_find(const char *prefix, const char *suffix, char *out, size_t cap) {
    const size_t pn = strlen(prefix), sn = strlen(suffix);
    if (sizes_key[0] && !strncmp(sizes_key, prefix, pn)) {
        if (!sizes_fallback[0]) return 0;
        snprintf(out, cap, "%s", sizes_fallback);
        return 1;
    }
    for (size_t i = 0; i < table_cap; i++) {
        const char *k = table[i].key;
        const size_t kn = k ? strlen(k) : 0;
        if (k && !table[i].is_dir && kn >= pn + sn && !strncmp(k, prefix, pn) && !strcmp(k + kn - sn, suffix)) {
            snprintf(out, cap, "%s", table[i].host);
            return 1;
        }
    }
    return 0;
}

/* nn_fs.c, listing a RomFS folder: fn(arg, name, is_dir, size) for each mod entry directly in it that the game's own
   folder (base_dir, a host path; may not exist) does not have. Returns how many. */
int hos_mods_dir_extras(const char *rel, const char *base_dir, void (*fn)(void *, const char *, int, uint64_t),
                        void *arg) {
    if (!table_n) return 0;
    char prefix[MAX_PATH];
    snprintf(prefix, sizeof prefix, "%s", rel);
    lower_slash(prefix);
    size_t pn = strlen(prefix);
    while (pn && prefix[pn - 1] == '/') prefix[--pn] = 0;
    int n = 0;
    for (size_t i = 0; i < table_cap; i++) {
        const Entry *e = &table[i];
        if (!e->key) continue;
        const char *k = e->key;
        if (pn && (strncmp(k, prefix, pn) || k[pn] != '/')) continue;
        const char *name = pn ? k + pn + 1 : k;
        if (!*name || strchr(name, '/')) continue;   /* (deeper) */
        const char *real = last_sep(e->host);   /* (the name as the mod spells it) */
        real = real ? real + 1 : e->host;
        char base[MAX_PATH];
        snprintf(base, sizeof base, "%s\\%s", base_dir, real);
        if (GetFileAttributesA(base) != INVALID_FILE_ATTRIBUTES) continue;
        fn(arg, real, e->is_dir, e->size);
        n++;
    }
    return n;
}

/* ---- the Mods tab (gpu/vk/vk_menu.cpp through host/rx_backend.c) and cheats.c */

/* the tab's two lines of a mod: what it has, and what of it is not used (and why) */
static void mod_text(Mod *m) {
    size_t k = 0;
    char *d = m->detail;
    const size_t dn = sizeof m->detail;
#define ADD(...) (k += (size_t)snprintf(d + k, k < dn ? dn - k : 0, __VA_ARGS__), k = k < dn ? k : dn - 1)
    if (m->romfs && m->start_enabled) ADD("RomFS: %d file%s (%d replace%s the game's, %d added). ", m->files, m->files == 1 ? "" : "s",
                                         m->replaced, m->replaced == 1 ? "s" : "", m->added);
    else if (m->romfs) ADD("RomFS files. ");
    if (m->exefs_files) ADD("ExeFS: %d patch file%s%s. ", m->exefs_files, m->exefs_files == 1 ? "" : "s",
                            m->exefs_built ? (m->exefs_built == m->exefs_files ? ", built into the game" : ", some built into the game") : "");
    else if (m->exefs) ADD("ExeFS: no patch files (.ips, .pchtxt). ");
    if (m->cheat_count) ADD("Cheats: %d. ", m->cheat_count);
    else if (m->cheats) ADD("Cheats: no file for this game version. ");
    if (k && d[k - 1] == ' ') d[--k] = 0;
    if (!k) ADD("Nothing Hookshot uses.");
    k = 0, d = m->note;
    if (m->overridden) ADD("%d of its files are taken by a mod lower in the list. ", m->overridden);
    if (m->exefs_waiting)
        ADD("%d ExeFS patch file%s %s not in the game yet: build the game again (Hookshot Builder) to apply %s. ", m->exefs_waiting,
            m->exefs_waiting == 1 ? "" : "s", m->exefs_waiting == 1 ? "is" : "are", m->exefs_waiting == 1 ? "it" : "them");
    if (m->exefs_built && !m->enabled)
        ADD("Its ExeFS patches stay in the game until it is built again. ");
    if (m->exefs_other) ADD("%d ExeFS patch file%s for another game version. ", m->exefs_other, m->exefs_other == 1 ? " is" : "s are");
    if (m->exefs_bad) ADD("ExeFS: %s. ", m->exefs_note[0] ? m->exefs_note : "a patch file cannot be applied");
    if (k && d[k - 1] == ' ') d[--k] = 0;
#undef ADD
}

int hos_mods_count(void) { return nmods; }
const char *hos_mods_dir(void) { return root_dir; }

/* mod i (the list's order): its name, its two lines, whether it is on; 0 past the end */
int hos_mod_info(int i, const char **name, const char **detail, const char **note, int *enabled) {
    if (i < 0 || i >= nmods) return 0;
    mod_text(&mods[i]);
    *name = mods[i].name, *detail = mods[i].detail, *note = mods[i].note, *enabled = mods[i].enabled;
    return 1;
}

/* the menu's change of mod i: op 0 off, 1 on, 2 up a place, 3 down a place; kept in hookshot_mods.txt at once, applied at
   the next start */
void hos_mod_edit(int i, int op) {
    if (i < 0 || i >= nmods) return;
    if (op == 0 || op == 1) {
        if (mods[i].enabled == op) return;
        mods[i].enabled = op;
        hos_log("mods: %s switched %s (at the next start)", mods[i].name, op ? "on" : "off");
    } else {
        const int j = op == 2 ? i - 1 : i + 1;
        if (j < 0 || j >= nmods) return;
        const Mod t = mods[i];
        mods[i] = mods[j], mods[j] = t;
        for (size_t e = 0; e < table_cap; e++)   /* (the index's mod numbers follow: the size table and cheats name them) */
            if (table[e].key) table[e].mod = table[e].mod == i ? j : table[e].mod == j ? i : table[e].mod;
        for (int s = 0; s < nshipped; s++) shipped[s].mod = shipped[s].mod == i ? j : shipped[s].mod == j ? i : shipped[s].mod;
        hos_log("mods: %s moved %s (at the next start)", mods[j].name, op == 2 ? "up" : "down");
    }
    write_state();
}

/* 0 while the order and the switches are the start's, else a number for them (the menu's restart question) */
uint64_t hos_mods_changed(void) {
    const uint64_t k = state_key();
    return k == start_key ? 0 : k | 1;
}

/* cheats.c: the cheats folder of each mod that was on at the start, in the list's order, and the cheats' switches */
int hos_mod_cheats_dir(int i, char *out, size_t cap, const char **name) {
    if (i < 0 || i >= nmods || !mods[i].start_enabled || !mods[i].cheats) return 0;
    snprintf(out, cap, "%s/cheats", mods[i].path);
    for (char *p = out; *p; p++) if (*p == '\\') *p = '/';
    *name = mods[i].name;
    return 1;
}
void hos_mod_cheat_count(const char *name, int n) {
    for (int i = 0; i < nmods; i++)
        if (!strcmp(mods[i].name, name)) mods[i].cheat_count = n;
}
int hos_mods_cheat_switch(const char *key, int otherwise) {
    for (int i = 0; i < ncheat_switches; i++)
        if (!strcmp(cheat_switches[i].key, key)) return cheat_switches[i].on;
    return otherwise;
}
void hos_mods_cheat_set(const char *key, int on) {
    int i = 0;
    while (i < ncheat_switches && strcmp(cheat_switches[i].key, key)) i++;
    if (i == ncheat_switches) {
        cheat_switches = (CheatSwitch *)realloc(cheat_switches, sizeof *cheat_switches * (size_t)(ncheat_switches + 1));
        cheat_switches[ncheat_switches++] = (CheatSwitch){_strdup(key), on};
    }
    cheat_switches[i].on = on;
    write_state();
}
