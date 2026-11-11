/* (hookshot) The game's .zs files, for the runtime's own reads: a zstd frame, made with one of the game's dictionaries or
   with none. The dictionaries are the members of Pack/ZsDic.pack.zs (a SARC archive in a zstd frame of its own, made
   without one), read from the RomFS once, the first time a frame asks for one (its dictionary id). host/mods.c reads the
   resource size tables with it (the game's and the mods'); nothing else does, so a game without mods never loads them.
   zstd's decoder is third_party/zstd (BSD), built into the executable (nx2/build.py) as into the Vulkan back end.
   hos_zs_write writes a frame of raw blocks, as host/prompts.c does: the game's decoder takes a frame made without its
   dictionary. */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"

extern const char *hos_romfs_dir;   /* nn_fs.c */

typedef struct { unsigned id; ZSTD_DDict *dict; } Dict;
static Dict dicts[8];
static int ndicts, dicts_read;

static uint8_t *read_file(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    const long long size = _ftelli64(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *b = size >= 0 && size < (1ll << 30) ? (uint8_t *)malloc((size_t)size + 1) : NULL;
    if (b && fread(b, 1, (size_t)size, f) != (size_t)size) free(b), b = NULL;
    fclose(f);
    if (b) *n = (size_t)size;
    return b;
}

static uint32_t rd16(const uint8_t *p) { return p[0] | p[1] << 8; }
static uint32_t rd32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

/* The plain decode of a frame (no dictionary): malloc'd, NULL when it is not one or it holds more than limit bytes */
static uint8_t *decode(const uint8_t *z, size_t zn, size_t *n, size_t limit, const ZSTD_DDict *dict) {
    const unsigned long long raw = ZSTD_getFrameContentSize(z, zn);
    if (raw == ZSTD_CONTENTSIZE_ERROR || raw == ZSTD_CONTENTSIZE_UNKNOWN || raw > limit) return NULL;
    uint8_t *d = (uint8_t *)malloc((size_t)raw + 1);
    ZSTD_DCtx *ctx = d ? ZSTD_createDCtx() : NULL;
    size_t got = 0;
    if (ctx) got = dict ? ZSTD_decompress_usingDDict(ctx, d, (size_t)raw, z, zn, dict) : ZSTD_decompressDCtx(ctx, d, (size_t)raw, z, zn);
    if (ctx) ZSTD_freeDCtx(ctx);
    if (!ctx || ZSTD_isError(got) || got != raw) {
        free(d);
        return NULL;
    }
    *n = (size_t)raw;
    return d;
}

/* the dictionaries, out of Pack/ZsDic.pack.zs (SARC: "SARC", u16 header size, u16 BOM, u32 size, u32 data offset; SFAT
   after the header: "SFAT", u16 header size, u16 node count, u32 hash key, nodes of {u32 hash, u32 attributes, u32 start,
   u32 end}; then SFNT and the names) */
static void read_dicts(void) {
    dicts_read = 1;
    char path[MAX_PATH];
    if (!hos_romfs_dir) return;
    snprintf(path, sizeof path, "%s/Pack/ZsDic.pack.zs", hos_romfs_dir);
    size_t zn = 0, n = 0;
    uint8_t *z = read_file(path, &zn), *p = z ? decode(z, zn, &n, 64u << 20, NULL) : NULL;
    free(z);
    if (!p || n < 0x14 || memcmp(p, "SARC", 4) || rd16(p + 6) != 0xfeff) {
        hos_log("zs: no dictionaries (%s)", path);
        free(p);
        return;
    }
    const size_t head = rd16(p + 4), data = rd32(p + 12);
    if (head + 12 > n || memcmp(p + head, "SFAT", 4) || data > n) {
        free(p);
        return;
    }
    const size_t count = rd16(p + head + 6), nodes = head + rd16(p + head + 4);
    for (size_t i = 0; i < count && nodes + i * 16 + 16 <= n && ndicts < (int)(sizeof dicts / sizeof *dicts); i++) {
        const uint8_t *e = p + nodes + i * 16;
        const uint32_t lo = rd32(e + 8), hi = rd32(e + 12);
        if (lo > hi || hi > n - data) continue;
        const unsigned id = ZSTD_getDictID_fromDict(p + data + lo, hi - lo);
        ZSTD_DDict *d = id ? ZSTD_createDDict(p + data + lo, hi - lo) : NULL;
        if (d) dicts[ndicts++] = (Dict){id, d};
    }
    free(p);
    hos_log("zs: %d dictionaries", ndicts);
}

uint8_t *hos_zs_decode(const uint8_t *z, size_t zn, size_t *n, size_t limit) {
    const unsigned id = ZSTD_getDictID_fromFrame(z, zn);
    if (!id) return decode(z, zn, n, limit, NULL);
    static volatile LONG once;
    if (InterlockedCompareExchange(&once, 1, 0) == 0) read_dicts();
    for (int i = 0; i < ndicts; i++)
        if (dicts[i].id == id) return decode(z, zn, n, limit, dicts[i].dict);
    return NULL;
}

uint8_t *hos_zs_read(const char *path, size_t *n, size_t limit) {
    size_t zn = 0;
    uint8_t *z = read_file(path, &zn), *d = z ? hos_zs_decode(z, zn, n, limit) : NULL;
    free(z);
    return d;
}

/* the size a .zs file decompresses to, as its frame says (the game's tools and zstd's write it), from its first bytes;
   4 times the bytes when the frame does not say; the bytes themselves for a file that is not a frame */
uint64_t hos_zs_content_size(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    uint8_t head[18];
    const size_t got = fread(head, 1, sizeof head, f);
    fseek(f, 0, SEEK_END);
    const long long size = _ftelli64(f);
    fclose(f);
    const unsigned long long c = ZSTD_getFrameContentSize(head, got);
    return c == ZSTD_CONTENTSIZE_ERROR ? (uint64_t)size : c == ZSTD_CONTENTSIZE_UNKNOWN ? (uint64_t)size * 4 : c;
}

/* data as a zstd frame of raw blocks of 128 KB: the 4-byte content size, a window of 128 KB (raw blocks never look back) */
int hos_zs_write(const char *path, const uint8_t *data, size_t n) {
    char tmp[MAX_PATH];
    snprintf(tmp, sizeof tmp, "%s.new", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) return 0;
    const uint8_t head[10] = {0x28, 0xB5, 0x2F, 0xFD, 0x80, 7 << 3, (uint8_t)n, (uint8_t)(n >> 8), (uint8_t)(n >> 16),
                              (uint8_t)(n >> 24)};
    int ok = fwrite(head, 1, 10, f) == 10;
    size_t at = 0;
    do {
        const size_t k = n - at < 131072 ? n - at : 131072;
        const uint32_t bh = (uint32_t)(k << 3) | (at + k == n ? 1u : 0u);
        const uint8_t b3[3] = {(uint8_t)bh, (uint8_t)(bh >> 8), (uint8_t)(bh >> 16)};
        ok &= fwrite(b3, 1, 3, f) == 3 && fwrite(data + at, 1, k, f) == k;
        at += k;
    } while (at < n);
    ok &= fclose(f) == 0;
    return ok && MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING);
}
