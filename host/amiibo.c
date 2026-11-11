/* (hookshot) Amiibo: the player's own NTAG215 dumps, read as the console's NFC reader would read the figure (nn::nfp, nn_nfp.c).
   The Insert menu's Amiibo row (gpu/vk/vk_menu.cpp, MkwVkHost.amiibo_*) lists the dumps of the "amiibo" folder beside the game
   (HOS_AMIIBO_DIR=<folder> for another) and puts the chosen one on the reader; the game reads it the next time it searches,
   and once it has read it and stops searching, the figure is taken off the reader again (or after kOnReaderNs).

   A dump is the tag's 540 bytes (532 and 572 byte dumps, without the password pages or with the signature, are taken too).
   What the game reads of it is what the tag keeps in the clear: its UID, and the amiibo ID at 0x54 (character, variant,
   figure type, model number, series). The registered nickname, the owner's Mii and a game's application area are
   encrypted on the tag with the console's keys, which Hookshot does not have: the nickname is the file's name, the Mii a
   blank one, and an application area the game creates is kept in amiibo/appdata/<UID>.bin, never in the dump itself.

   Ported from valentderah/totk-pc-recomp runtime/amiibo.c (MIT; leonelalej's amiibo support, its PR #235, with Valiantsin
   Dzerakh's fixes), commit 7a37fc3c:
     Copyright (c) 2026 Valiantsin Dzerakh

     Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
     documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
     rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
     persons to whom the Software is furnished to do so, subject to the following conditions:

     The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
     Software.

     THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
     WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
     COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
     OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

   tests/test_amiibo.py compiles this file with stand-ins for the runtime (AMIIBO_TEST) and checks the dump checks, the
   reader's states and the application area against tags of its own making. */
#include "amiibo.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef AMIIBO_TEST
#include "hos.h"
#include "hos_paths.h"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static SRWLOCK lock = SRWLOCK_INIT;
#define LOCK() AcquireSRWLockExclusive(&lock)
#define UNLOCK() ReleaseSRWLockExclusive(&lock)
#define NOW_NS() hos_now_ns()
#define LOG hos_log
#else
#include "amiibo_test_stubs.h"
#endif
#define SEP "/"   /* (Windows takes it too; fopen on Linux takes no backslash) */

#define ON_READER_NS (20LL * 1000000000LL)   /* a figure the game never reads is taken off after this long */

static uint8_t dump[AMIIBO_DUMP_SIZE];
static char dump_name[128];   /* the file's name without .bin: the nickname */
static int has_dump, on_reader, detecting, mounted, was_mounted;
static int64_t placed_ns;
/* the application area: the one the game created on this figure, by its access id (amiibo/appdata/<UID>.bin) */
static uint8_t area[AMIIBO_AREA_SIZE];
static uint32_t area_id, area_size;
static int area_known, area_dirty;

static char list[AMIIBO_MAX_FILES][128];   /* the folder's dumps, by name, as the menu lists them */
static int nlist;

/* the amiibo folder, with its separator */
static int folder(char *out, size_t cap) {
    const char *e = getenv("HOS_AMIIBO_DIR");
    if (e && *e) return snprintf(out, cap, "%s" SEP, e) < (int)cap;
#ifndef AMIIBO_TEST
    char exe[MAX_PATH];
    const DWORD n = hos_game_path_a(exe, MAX_PATH);
    char *slash = n ? (strrchr(exe, '\\') > strrchr(exe, '/') ? strrchr(exe, '\\') : strrchr(exe, '/')) : NULL;
    if (!slash) return 0;
    slash[1] = 0;
    return snprintf(out, cap, "%samiibo" SEP, exe) < (int)cap;
#else
    return 0;
#endif
}

int amiibo_check(const uint8_t *d, size_t n) {
    if (n < AMIIBO_DUMP_MIN || n > AMIIBO_DUMP_MAX) return 0;
    /* the Capability Container at page 3: an amiibo's is F1 10 FF EE (not the E1 of a plain NDEF tag); it is not encrypted */
    static const uint8_t cc[4] = {0xF1, 0x10, 0xFF, 0xEE};
    if (memcmp(d + 0x0C, cc, 4)) return 0;
    int zero = 1, ones = 1;   /* (the UID: bytes 0 to 2, then 4 to 7) */
    for (int i = 0; i < 8; i++)
        if (i != 3) zero &= d[i] == 0, ones &= d[i] == 0xFF;
    if (zero || ones) return 0;
    /* ISO 14443-3 check bytes: BCC0 = 0x88 ^ UID0 ^ UID1 ^ UID2 (byte 3), BCC1 = UID3 ^ UID4 ^ UID5 ^ UID6 (byte 8) */
    return d[3] == (uint8_t)(0x88 ^ d[0] ^ d[1] ^ d[2]) && d[8] == (uint8_t)(d[4] ^ d[5] ^ d[6] ^ d[7]);
}

static void uid_of(uint8_t out[7], const uint8_t *d) {
    memcpy(out, d, 3);
    memcpy(out + 3, d + 4, 4);
}

static int appdata_path(char *out, size_t cap) {
    char dir[512];
    uint8_t u[7];
    if (!folder(dir, sizeof dir)) return 0;
    uid_of(u, dump);
    return snprintf(out, cap, "%sappdata" SEP "%02X%02X%02X%02X%02X%02X%02X.bin", dir, u[0], u[1], u[2], u[3], u[4], u[5], u[6]) < (int)cap;
}

/* (under the lock) the application area kept for this figure: u32 access id, u32 size, the bytes */
static void area_load(void) {
    area_known = 0, area_dirty = 0, area_size = 0, area_id = 0;
    char path[640];
    if (!appdata_path(path, sizeof path)) return;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    uint8_t head[8];
    if (fread(head, 1, 8, f) == 8) {
        uint32_t id, n;
        memcpy(&id, head, 4), memcpy(&n, head + 4, 4);
        if (n <= AMIIBO_AREA_SIZE && fread(area, 1, n, f) == n) area_id = id, area_size = n, area_known = 1;
    }
    fclose(f);
}

int amiibo_load(const char *path, const char *name) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        LOG("amiibo: cannot open %s", path);
        return 0;
    }
    uint8_t d[AMIIBO_DUMP_MAX + 1];
    const size_t n = fread(d, 1, sizeof d, f);
    fclose(f);
    if (!amiibo_check(d, n)) {
        LOG("amiibo: %s is not an amiibo dump (%zu bytes; one is 540, with its UID check bytes and an amiibo's capability "
            "container)", path, n);
        return 0;
    }
    LOCK();
    memset(dump, 0, sizeof dump);
    memcpy(dump, d, n < AMIIBO_DUMP_SIZE ? n : AMIIBO_DUMP_SIZE);
    snprintf(dump_name, sizeof dump_name, "%s", name ? name : "amiibo");
    has_dump = 1, mounted = 0, was_mounted = 0;
    area_load();
    UNLOCK();
    LOG("amiibo: %s: character %02x%02x%02x, figure type %02x, model %02x%02x, series %02x%s", name ? name : path, d[0x54],
        d[0x55], d[0x56], d[0x57], d[0x58], d[0x59], d[0x5A], area_known ? ", with this game's application area" : "");
    return 1;
}

/* ---- the reader, as the game sees it (nn_nfp.c) */
void amiibo_place(void) {
    LOCK();
    if (has_dump) on_reader = 1, mounted = 0, was_mounted = 0, placed_ns = NOW_NS();
    UNLOCK();
    LOG("amiibo: %s placed on the reader", dump_name);
}
void amiibo_take_off(void) {
    LOCK();
    const int was = on_reader;
    on_reader = 0, mounted = 0;
    UNLOCK();
    if (was) LOG("amiibo: %s taken off the reader", dump_name);
}
/* (under the lock) a figure left too long goes; one the game read goes once it stops searching */
static void expire(void) {
    if (on_reader && !mounted && NOW_NS() - placed_ns > ON_READER_NS) {
        on_reader = 0;
        LOG("amiibo: %s taken off the reader (the game did not read it)", dump_name);
    }
}
void amiibo_detect(int on) {
    LOCK();
    static int starts;
    if (on && ++starts <= 3) LOG("amiibo: the game searches for a figure");
    if (!on && was_mounted && on_reader) {   /* (read, and the game is done with the reader: lifted off, as a player would) */
        on_reader = 0, mounted = 0;
        LOG("amiibo: %s read by the game, taken off the reader", dump_name);
    }
    detecting = on;
    if (!on) mounted = 0;
    UNLOCK();
}
int amiibo_state(void) {
    LOCK();
    expire();
    const int s = mounted ? AMIIBO_MOUNTED : detecting && on_reader ? AMIIBO_ACTIVE : detecting ? AMIIBO_SEARCHING
                                                                                      : AMIIBO_INITIALIZED;
    UNLOCK();
    return s;
}
int amiibo_mount(void) {
    LOCK();
    expire();
    const int ok = has_dump && on_reader && detecting;
    if (ok) mounted = 1, was_mounted = 1;
    UNLOCK();
    if (ok) LOG("amiibo: %s mounted", dump_name);
    return ok;
}
void amiibo_unmount(void) {
    LOCK();
    mounted = 0;
    UNLOCK();
}
int amiibo_mounted(void) {
    LOCK();
    const int m = mounted;
    UNLOCK();
    return m;
}
int amiibo_tag_seen(void) {
    LOCK();
    expire();
    const int s = has_dump && on_reader && detecting;
    UNLOCK();
    return s;
}

/* nn::nfp::TagInfo (0x58): the UID (10 bytes, 7 used) and its length at 0x0A, the protocol (Type A: 1) at 0x20 and the tag
   type (Type 2: 2) at 0x24 */
void amiibo_tag_info(uint8_t *out) {
    LOCK();
    memset(out, 0, 0x58);
    uid_of(out, dump);
    out[0x0A] = 7;
    out[0x20] = 1, out[0x24] = 2;
    UNLOCK();
}
/* nn::nfp::ModelInfo (0x40): the character ID and variant as on the tag, the series, the model number little-endian (it
   is big-endian on the tag), the figure type */
void amiibo_model_info(uint8_t *out) {
    LOCK();
    memset(out, 0, 0x40);
    memcpy(out, dump + 0x54, 3);
    out[3] = dump[0x5A];
    out[4] = dump[0x59], out[5] = dump[0x58];
    out[6] = dump[0x57];
    UNLOCK();
}
/* nn::nfp::CommonInfo (0x40): the last write's date (u16 year, u8 month, u8 day), the write counter, the version, the
   application area's size */
void amiibo_common_info(uint8_t *out) {
    LOCK();
    memset(out, 0, 0x40);
    const uint16_t year = 2026, writes = (uint16_t)(dump[0x10] << 8 | dump[0x11]);   /* (the tag's write counter, in the clear) */
    memcpy(out, &year, 2);
    out[2] = 1, out[3] = 1;
    memcpy(out + 4, &writes, 2);
    out[6] = dump[0x5B];
    const uint32_t size = AMIIBO_AREA_SIZE;
    memcpy(out + 8, &size, 4);
    UNLOCK();
}
/* nn::nfp::RegisterInfo (0x100): the owner's Mii (0x58, a blank one), the date it was registered, the nickname (40 bytes and
   its 0, at 0x5C): the file's name */
void amiibo_register_info(uint8_t *out) {
    LOCK();
    memset(out, 0, 0x100);
    const uint16_t year = 2026;
    memcpy(out + 0x58, &year, 2);
    out[0x5A] = 1, out[0x5B] = 1;
    snprintf((char *)out + 0x5C, 41, "%s", dump_name);
    UNLOCK();
}

/* ---- the application area. 0, or an AMIIBO_RESULT_* code */
int amiibo_area_open(uint32_t access_id) {
    LOCK();
    const int r = !mounted ? AMIIBO_RESULT_WRONG_STATE : !area_known ? AMIIBO_RESULT_NEED_CREATE
                  : area_id != access_id ? AMIIBO_RESULT_WRONG_AREA_ID : 0;
    UNLOCK();
    return r;
}
int amiibo_area_get(void *buf, uint32_t cap, uint32_t *size) {
    LOCK();
    const int r = !mounted ? AMIIBO_RESULT_WRONG_STATE : !area_known ? AMIIBO_RESULT_NEED_CREATE : 0;
    if (!r) {
        const uint32_t n = cap < area_size ? cap : area_size;
        memcpy(buf, area, n);
        *size = n;
    }
    UNLOCK();
    return r;
}
int amiibo_area_set(const void *data, uint32_t n) {
    if (n > AMIIBO_AREA_SIZE) return AMIIBO_RESULT_WRONG_AREA_SIZE;
    LOCK();
    const int r = !mounted ? AMIIBO_RESULT_WRONG_STATE : !area_known ? AMIIBO_RESULT_NEED_CREATE : 0;
    if (!r) memset(area, 0, sizeof area), memcpy(area, data, n), area_size = AMIIBO_AREA_SIZE, area_dirty = 1;
    UNLOCK();
    return r;
}
int amiibo_area_create(uint32_t access_id, const void *data, uint32_t n, int recreate) {
    if (n > AMIIBO_AREA_SIZE) return AMIIBO_RESULT_WRONG_AREA_SIZE;
    LOCK();
    const int r = !mounted ? AMIIBO_RESULT_WRONG_STATE : area_known && !recreate ? AMIIBO_RESULT_AREA_EXISTS : 0;
    if (!r) {
        memset(area, 0, sizeof area);
        if (data && n) memcpy(area, data, n);
        area_id = access_id, area_size = AMIIBO_AREA_SIZE, area_known = 1, area_dirty = 1;
    }
    UNLOCK();
    if (!r) LOG("amiibo: %s: the game made its application area (access id %08x)", dump_name, access_id);
    return r;
}
/* Flush: the area to amiibo/appdata/<UID>.bin (never into the dump) */
int amiibo_flush(void) {
    LOCK();
    int r = !mounted ? AMIIBO_RESULT_WRONG_STATE : 0;
    if (!r && area_dirty) {
        char path[640], dir[600];
        if (appdata_path(path, sizeof path) && folder(dir, sizeof dir)) {
            strncat(dir, "appdata", sizeof dir - strlen(dir) - 1);
            CreateDirectoryA(dir, NULL);
            FILE *f = fopen(path, "wb");
            if (f) {
                fwrite(&area_id, 4, 1, f), fwrite(&area_size, 4, 1, f), fwrite(area, 1, area_size, f);
                fclose(f);
                area_dirty = 0;
            }
        }
        if (area_dirty) LOG("amiibo: could not write the application area to %s", path);
    }
    UNLOCK();
    return r;
}

/* ---- the menu's list (MkwVkHost.amiibo_count / amiibo_name / amiibo_choose) */
static int by_name(const void *a, const void *b) { return _stricmp((const char *)a, (const char *)b); }
int amiibo_rescan(void) {
    char dir[512], pat[600];
    nlist = 0;
    if (!folder(dir, sizeof dir)) return 0;
    snprintf(pat, sizeof pat, "%s*", dir);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        const size_t n = strlen(fd.cFileName);
        if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || n < 5 || n >= sizeof list[0]) continue;
        if (_stricmp(fd.cFileName + n - 4, ".bin") && _stricmp(fd.cFileName + n - 4, ".nfc")) continue;
        if (fd.nFileSizeLow < AMIIBO_DUMP_MIN || fd.nFileSizeLow > AMIIBO_DUMP_MAX || fd.nFileSizeHigh) continue;
        if (nlist < AMIIBO_MAX_FILES) snprintf(list[nlist++], sizeof list[0], "%s", fd.cFileName);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    qsort(list, (size_t)nlist, sizeof list[0], by_name);
    return nlist;
}
const char *amiibo_file(int i) { return i >= 0 && i < nlist ? list[i] : ""; }
/* i: the list's file onto the reader (loaded again, so an edited file counts); -1: the figure off the reader */
int amiibo_choose(int i) {
    if (i < 0 || i >= nlist) {
        amiibo_take_off();
        return 1;
    }
    char dir[512], path[700], name[128];
    if (!folder(dir, sizeof dir)) return 0;
    snprintf(path, sizeof path, "%s%s", dir, list[i]);
    snprintf(name, sizeof name, "%s", list[i]);
    name[strlen(name) - 4] = 0;
    if (!amiibo_load(path, name)) return 0;
    amiibo_place();
    return 1;
}
/* the menu's state line: 0 no figure, 1 on the reader (the game not searching), 2 on the reader while it searches, 3 read */
int amiibo_menu_state(void) {
    LOCK();
    expire();
    const int s = !on_reader ? 0 : was_mounted ? 3 : detecting ? 2 : 1;
    UNLOCK();
    return s;
}
