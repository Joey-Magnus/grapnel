"""Mods that grow files load together: host/mods.c's list, order and switches, and the resource size table it merges.

Linux only (built over host/posix/win32_posix.c's file functions). Builds host/mods.c (from its index on), host/restbl.c,
host/zs.c's reads and writes and zstd's decoder (third_party/zstd) into one program, makes a synthetic game folder (a
RomFS with a synthetic RESTBL table and synthetic .zs files: no game data) and mods, and checks:

- two mods that grow the same file and one that grows another: the file served is the lower mod's, and the merged table's
  entries fit each served file (in proportion to the game's own allowance); a mod's own table is merged in (its larger entry
  wins), a file a mod adds gets an estimate; the merged table is what the game's table's path serves;
- the mods' counts (replaced, added, taken by a lower mod) and the Mods tab's lines;
- hookshot_mods.txt: the menu's moves and switches written at once, the next start's order and switches read from it (a
  mod switched off serves nothing), "changed since the start" is 0 when moved back;
- ExeFS patch files against the build's exefs_patches.txt: built in, or waiting for the next build;
- with no mods folder nothing is served and nothing is written.

python -I -B tests/test_mods_sizes.py [--cc gcc]
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZSTD = ROOT / "third_party/zstd/lib"
ZSTD_FILES = ("common/debug.c", "common/entropy_common.c", "common/error_private.c", "common/fse_decompress.c", "common/xxhash.c",
              "common/zstd_common.c", "decompress/huf_decompress.c", "decompress/zstd_ddict.c", "decompress/zstd_decompress.c",
              "decompress/zstd_decompress_block.c")
TABLE = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def raw_frame(data):
    """data as a zstd frame of raw blocks (what host/zs.c writes; zstd's decoder reads it)"""
    out = bytearray(b"\x28\xb5\x2f\xfd\x80" + bytes([7 << 3]) + struct.pack("<I", len(data)))
    at = 0
    while True:
        k = min(len(data) - at, 131072)
        last = at + k == len(data)
        bh = (k << 3) | (1 if last else 0)
        out += bytes([bh & 0xFF, (bh >> 8) & 0xFF, (bh >> 16) & 0xFF]) + data[at:at + k]
        at += k
        if last:
            return bytes(out)


def restbl(entries):
    """a RESTBL of {key: size} (all hashed)"""
    hashed = sorted((zlib.crc32(k.encode()), v) for k, v in entries.items())
    b = b"RESTBL" + struct.pack("<IIII", 1, 160, len(hashed), 0)
    return b + b"".join(struct.pack("<II", h, v) for h, v in hashed)


FIXTURE_MAIN = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static uint32_t entry_of(Restbl *t, const char *key) { uint32_t v = 0; return restbl_get(t, key, &v) ? v : 0; }
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    snprintf(game_root, sizeof game_root, "%s/", argv[1]);
    static char romfs[1024];
    snprintf(romfs, sizeof romfs, "%s/romfs", argv[1]);
    hos_romfs_dir = romfs;
    const char *mode = argv[2];
    hos_mods_init(NULL);
    char out[1024];
    const char *table = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs";
    if (!strcmp(mode, "none")) {
        CHECK(!hos_mods_romfs(table, out, sizeof out) && !hos_mods_romfs("Model/A.bfres.zs", out, sizeof out));
        char cache[1100];
        snprintf(cache, sizeof cache, "%s/modcache", argv[1]);
        CHECK(GetFileAttributesA(cache) == INVALID_FILE_ATTRIBUTES);
        printf("PASS: no mods: nothing served, nothing written\n");
        return 0;
    }
    CHECK(hos_mods_romfs(table, out, sizeof out) && strstr(out, "modcache/rsizetable.zs"));
    size_t n = 0;
    uint8_t *raw = hos_zs_read(out, &n, 64u << 20);
    Restbl *t = raw ? restbl_parse(raw, n) : NULL;
    CHECK(t);
    const char *name, *detail, *note;
    int on;
    if (!strcmp(mode, "first")) {
        CHECK(hos_mods_romfs("Model/A.bfres.zs", out, sizeof out) && strstr(out, "02-second"));   /* (the lower mod's) */
        CHECK(hos_mods_romfs("Tex/B.bntx.zs", out, sizeof out) && strstr(out, "01-first"));
        CHECK(hos_mods_romfs("New/D.bgyml.zs", out, sizeof out) && strstr(out, "03-added"));
        CHECK(!hos_mods_romfs("Other/C.byml.zs", out, sizeof out));                              /* (the game's) */
        CHECK(entry_of(t, "Model/A.bfres") >= 5000 + 300 && entry_of(t, "Model/A.bfres") >= 1300 * 5);   /* (5000 bytes now) */
        CHECK(entry_of(t, "Tex/B.bntx") >= 600 * 4);                                             /* (500 -> 2000) */
        CHECK(entry_of(t, "Other/C.byml") == 9000);                                              /* (02-second's own table) */
        CHECK(entry_of(t, "New/D.bgyml") >= 700 * 10 && entry_of(t, "Keep/E.bntx") == 777);      /* (an estimate; untouched) */
        CHECK(hos_mod_info(0, &name, &detail, &note, &on) && !strcmp(name, "01-first") && on);
        CHECK(strstr(note, "1 of its files are taken by a mod lower in the list"));
        CHECK(strstr(detail, "RomFS: 2 files (2 replace the game's, 0 added)"));
        CHECK(strstr(detail, "ExeFS: 2 patch files, some built into the game"));
        CHECK(strstr(note, "1 ExeFS patch file is not in the game yet"));
        CHECK(hos_mod_info(1, &name, &detail, &note, &on) && !strcmp(name, "02-second") && !*note);
        CHECK(!hos_mod_info(3, &name, &detail, &note, &on));
        CHECK(hos_mods_changed() == 0);
        hos_mod_edit(1, 2);   /* (02-second up a place) */
        CHECK(hos_mods_changed() != 0 && hos_mod_info(0, &name, &detail, &note, &on) && !strcmp(name, "02-second"));
        hos_mod_edit(0, 3);   /* (and back) */
        CHECK(hos_mods_changed() == 0);
        hos_mod_edit(2, 2), hos_mod_edit(0, 0);   /* (03-added over 02-second; 01-first off: for the next start) */
        hos_mods_cheat_set("cheat_0badf00d", 1);
        CHECK(hos_mods_changed() != 0);
        printf("PASS: two mods that grow the same file and a third that adds one: one merged table fits them all\n");
    } else {
        /* (the next start, from hookshot_mods.txt: 01-first off; 03-added before 02-second) */
        CHECK(hos_mod_info(0, &name, &detail, &note, &on) && !strcmp(name, "01-first") && !on);
        CHECK(hos_mod_info(1, &name, &detail, &note, &on) && !strcmp(name, "03-added") && on);
        CHECK(hos_mod_info(2, &name, &detail, &note, &on) && !strcmp(name, "02-second") && on);
        CHECK(hos_mods_cheat_switch("cheat_0badf00d", 0) == 1 && hos_mods_cheat_switch("cheat_other", 0) == 0);
        CHECK(!hos_mods_romfs("Tex/B.bntx.zs", out, sizeof out));                               /* (01-first is off) */
        CHECK(hos_mods_romfs("Model/A.bfres.zs", out, sizeof out) && strstr(out, "02-second"));
        CHECK(entry_of(t, "Model/A.bfres") >= 5000 && entry_of(t, "Tex/B.bntx") == 600);
        printf("PASS: the order and switches of hookshot_mods.txt at the next start\n");
    }
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    if os.name == "nt" or sys.platform == "darwin":
        print("SKIP: the posix layer's checks run on Linux")
        return
    posix = (ROOT / "host/posix/win32_posix.c").read_text(encoding="utf-8")
    mods = (ROOT / "host/mods.c").read_text(encoding="utf-8")
    zs = (ROOT / "host/zs.c").read_text(encoding="utf-8")
    pieces = [
        block(posix, "static DWORD error_of(int e) {"),
        "static BOOL fail_errno(void) { last_error = error_of(errno); return FALSE; }",
        "enum { H_THREAD = 0x48540001, H_EVENT, H_SEMA, H_TIMER, H_FILE, H_FIND };",
        "typedef struct { int type; } HObj;",
        "static int is(HANDLE h, int type) { return h && h != INVALID_HANDLE_VALUE && (uintptr_t)h > 0x10000 && ((HObj *)h)->type == type; }",
        block(posix, "static void slashes(char *dst, size_t cap, const char *src) {"),
        block(posix, "DWORD GetFileAttributesA(LPCSTR name) {"),
        block(posix, "BOOL CreateDirectoryA(LPCSTR name, void *attr) {"),
        block(posix, "BOOL MoveFileExA(LPCSTR from, LPCSTR to, DWORD flags) {"),
        "typedef struct { HObj h; DIR *d; char dir[PATH_MAX], pat[256]; } HFind;",
        block(posix, "static BOOL find_next(HFind *f, WIN32_FIND_DATAA *fd) {"),
        block(posix, "HANDLE FindFirstFileA(LPCSTR pattern, WIN32_FIND_DATAA *fd) {"),
        block(posix, "BOOL FindNextFileA(HANDLE h, WIN32_FIND_DATAA *fd) {"),
        block(posix, "BOOL FindClose(HANDLE h) {"),
        zs[zs.index("typedef struct { unsigned id; ZSTD_DDict *dict; } Dict;"):],
        mods[mods.index("typedef struct { char *key; char *host; char *rel;"):],
    ]
    fixture = r'''#define _GNU_SOURCE
#include <windows.h>
#include <dirent.h>
#include <errno.h>
#include <fnmatch.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>
#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"
#include "restbl.h"
static DWORD last_error;
static char game_root[1024];
const char *hos_romfs_dir;
static void hos_log(const char *f, ...) { if (getenv("MODS_TEST_LOG")) { va_list a; va_start(a, f); vfprintf(stderr, f, a); va_end(a); fputc(10, stderr); } }
static int64_t hos_now_ns(void) { return 0; }
static DWORD hos_game_path_a(char *buf, DWORD size) { return (DWORD)snprintf(buf, size, "%shookshot", game_root); }
int hos_prompts_romfs(const char *key, const char *mod, char *out, size_t cap) { (void)key; (void)mod; (void)out; (void)cap; return 0; }
''' + "\n".join(pieces) + FIXTURE_MAIN
    with tempfile.TemporaryDirectory(prefix="mods-sizes-") as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.c"
        src.write_text(fixture, encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=gnu11", "-O1", "-I", str(ROOT / "host/posix"), "-I", str(ROOT / "host"), "-I", str(ZSTD),
                        "-DZSTD_DISABLE_ASM", "-DZSTD_LEGACY_SUPPORT=0", "-DZSTD_MULTITHREAD=0", "-Wno-unused-function",
                        str(src), str(ROOT / "host/restbl.c")] + [str(ZSTD / f) for f in ZSTD_FILES] + ["-o", str(exe)],
                       check=True)

        def put(path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        game = tmp / "game"
        romfs = game / "romfs"
        put(romfs / TABLE, raw_frame(restbl({"Model/A.bfres": 1300, "Tex/B.bntx": 600, "Other/C.byml": 500, "Keep/E.bntx": 777})))
        put(romfs / "Model/A.bfres.zs", raw_frame(bytes(1000)))
        put(romfs / "Tex/B.bntx.zs", raw_frame(bytes(500)))
        put(romfs / "Other/C.byml.zs", raw_frame(bytes(400)))
        m = game / "mods"
        put(m / "01-first/romfs/Model/A.bfres.zs", raw_frame(bytes(3000)))   # (both grow A: 02-second's wins)
        put(m / "01-first/romfs/Tex/B.bntx.zs", raw_frame(bytes(2000)))
        put(m / "01-first/exefs/built.pchtxt", b"@nsobid-00\n")
        put(m / "01-first/exefs/new.ips", b"PATCHEOF")
        put(m / "02-second/romfs/Model/A.bfres.zs", raw_frame(bytes(5000)))
        put(m / "02-second/romfs" / TABLE, raw_frame(restbl({"Other/C.byml": 9000, "Tex/B.bntx": 100})))
        put(m / "03-added/romfs/New/D.bgyml.zs", raw_frame(bytes(700)))
        put(m / "-off/romfs/Model/A.bfres.zs", raw_frame(bytes(99999)))       # (off by its name: never seen)
        h = 0x811C9DC5
        for b in b"@nsobid-00\n":
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
        (game / "exefs_patches.txt").write_text("# list\n01-first\tbuilt.pchtxt\t%08x\tcode\t\n" % h, encoding="utf-8")

        def run(mode, root):
            r = subprocess.run([str(exe), str(root), mode], capture_output=True, text=True, timeout=60)
            print(r.stdout, end="")
            if r.returncode:
                print(r.stderr, end="")
                raise SystemExit("test_mods_sizes: %s failed (exit %d)" % (mode, r.returncode))

        run("first", game)
        state = (game / "hookshot_mods.txt").read_text(encoding="utf-8")
        lines = [line for line in state.splitlines() if not line.startswith("#")]
        if lines != ["off 01-first", "on 03-added", "on 02-second", "cheat cheat_0badf00d on"]:
            raise SystemExit("test_mods_sizes: hookshot_mods.txt is %r" % lines)
        run("next", game)
        bare = tmp / "bare"
        put(bare / "romfs" / TABLE, raw_frame(restbl({"Model/A.bfres": 1300})))
        run("none", bare)


if __name__ == "__main__":
    main()
