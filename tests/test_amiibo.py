"""Amiibo (host/amiibo.c, the Insert menu's Amiibo row): a dump is taken only when it is an amiibo's NTAG215 (its size, its
capability container, its UID check bytes), the reader's states follow the game's calls as nn::nfp's do (searching, the
figure found while it searches, mounted, taken off once read), the model info is the amiibo ID's fields in the SDK's order,
and an application area the game makes is kept beside the dumps (amiibo/appdata/<UID>.bin), never in the dump. Every tag
here is made by the test (made-up UID and ID); no real figure's dump is used.

python -I -B tests/test_amiibo.py [--cc <C or C++ compiler>]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "{cxx}"]   # (a C++ driver, the file compiled as C: -x c)
RUN_ALL_SKIP = {"windows": "POSIX stand-ins for the folder listing (the runtime's own are Win32's)"}

ROOT = Path(__file__).resolve().parents[1]

STUBS = r"""
#pragma once
#include <dirent.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#define LOCK() ((void)0)
#define UNLOCK() ((void)0)
extern int64_t test_now;
#define NOW_NS() (test_now)
static void LOG(const char *fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); printf("\n"); }
#define _stricmp strcasecmp
#define MAX_PATH 4096
#define FILE_ATTRIBUTE_DIRECTORY 0x10
#define INVALID_HANDLE_VALUE ((HANDLE)0)
typedef DIR *HANDLE;
typedef struct { char cFileName[260]; unsigned dwFileAttributes, nFileSizeLow, nFileSizeHigh; char dir[600]; } WIN32_FIND_DATAA;
static int fill(HANDLE h, WIN32_FIND_DATAA *fd) {
    struct dirent *e;
    while ((e = readdir(h))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char p[1000]; struct stat st;
        snprintf(p, sizeof p, "%s/%s", fd->dir, e->d_name);
        if (stat(p, &st)) continue;
        snprintf(fd->cFileName, sizeof fd->cFileName, "%s", e->d_name);
        fd->dwFileAttributes = S_ISDIR(st.st_mode) ? FILE_ATTRIBUTE_DIRECTORY : 0;
        fd->nFileSizeLow = (unsigned)st.st_size, fd->nFileSizeHigh = 0;
        return 1;
    }
    return 0;
}
static HANDLE FindFirstFileA(const char *pat, WIN32_FIND_DATAA *fd) {
    snprintf(fd->dir, sizeof fd->dir, "%s", pat);
    char *star = strrchr(fd->dir, '*'); if (star) *star = 0;
    size_t n = strlen(fd->dir); if (n && (fd->dir[n - 1] == '\\' || fd->dir[n - 1] == '/')) fd->dir[n - 1] = 0;
    HANDLE h = opendir(fd->dir);
    if (!h) return 0;
    if (!fill(h, fd)) { closedir(h); return 0; }
    return h;
}
static int FindNextFileA(HANDLE h, WIN32_FIND_DATAA *fd) { return fill(h, fd); }
static void FindClose(HANDLE h) { closedir(h); }
static int CreateDirectoryA(const char *p, void *a) { (void)a; return mkdir(p, 0755) == 0; }
"""

MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "amiibo.h"
int64_t test_now;
#define CHECK(x) do { if (!(x)) { printf("FAILED: %s (line %d)\n", #x, __LINE__); return 1; } } while (0)
static void tag(uint8_t *d, const uint8_t uid[7], const uint8_t id[8]) {
    memset(d, 0, 540);
    d[0] = uid[0], d[1] = uid[1], d[2] = uid[2], d[3] = 0x88 ^ uid[0] ^ uid[1] ^ uid[2];
    d[4] = uid[3], d[5] = uid[4], d[6] = uid[5], d[7] = uid[6], d[8] = uid[3] ^ uid[4] ^ uid[5] ^ uid[6];
    d[0x0C] = 0xF1, d[0x0D] = 0x10, d[0x0E] = 0xFF, d[0x0F] = 0xEE;
    memcpy(d + 0x54, id, 8);
}
static void save(const char *path, const uint8_t *d, size_t n) { FILE *f = fopen(path, "wb"); fwrite(d, 1, n, f); fclose(f); }
int main(int argc, char **argv) {
    const char *dir = argv[1];
    char path[1200];
    static const uint8_t uid[7] = {0x04, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
    static const uint8_t id[8] = {0x01, 0x23, 0x45, 0x02, 0x0A, 0xBC, 0x07, 0x02};   /* made up: character 0123, variant 45 */
    uint8_t d[600];
    tag(d, uid, id);
    CHECK(amiibo_check(d, 540) && amiibo_check(d, 532) && amiibo_check(d, 572));
    CHECK(!amiibo_check(d, 531) && !amiibo_check(d, 573));
    d[3] ^= 1; CHECK(!amiibo_check(d, 540)); d[3] ^= 1;
    d[8] ^= 1; CHECK(!amiibo_check(d, 540)); d[8] ^= 1;
    d[0x0C] = 0xE1; CHECK(!amiibo_check(d, 540)); d[0x0C] = 0xF1;   /* (a plain NDEF tag, not an amiibo) */
    uint8_t z[540] = {0}; z[3] = 0x88; z[0x0C] = 0xF1, z[0x0D] = 0x10, z[0x0E] = 0xFF, z[0x0F] = 0xEE;
    CHECK(!amiibo_check(z, 540));   /* (an all-zero UID) */

    snprintf(path, sizeof path, "%s/b figure.bin", dir); save(path, d, 540);
    snprintf(path, sizeof path, "%s/a broken.bin", dir); save(path, d, 100);   /* (too small: not listed) */
    snprintf(path, sizeof path, "%s/notes.txt", dir); save(path, d, 540);      /* (not a .bin: not listed) */
    uint8_t bad[540]; memcpy(bad, d, 540); bad[8] ^= 0xFF;
    snprintf(path, sizeof path, "%s/c bad.bin", dir); save(path, bad, 540);     /* (listed by its size; refused when chosen) */
    CHECK(amiibo_rescan() == 2);
    CHECK(!strcmp(amiibo_file(0), "b figure.bin") && !strcmp(amiibo_file(1), "c bad.bin") && !*amiibo_file(2));
    CHECK(!amiibo_choose(1));
    CHECK(amiibo_menu_state() == 0);

    /* the reader: nothing found until the game searches with a figure on it */
    CHECK(amiibo_state() == AMIIBO_INITIALIZED);
    CHECK(amiibo_choose(0) && amiibo_menu_state() == 1);
    CHECK(amiibo_state() == AMIIBO_INITIALIZED && !amiibo_mount());
    amiibo_detect(1);
    CHECK(amiibo_state() == AMIIBO_ACTIVE && amiibo_tag_seen() && amiibo_menu_state() == 2);
    uint8_t info[0x100];
    amiibo_tag_info(info);
    CHECK(!memcmp(info, uid, 7) && info[0x0A] == 7 && info[0x20] == 1 && info[0x24] == 2);
    CHECK(amiibo_area_open(0x1234) == AMIIBO_RESULT_WRONG_STATE);   /* (not mounted) */
    CHECK(amiibo_mount() && amiibo_state() == AMIIBO_MOUNTED);
    amiibo_model_info(info);
    CHECK(info[0] == 0x01 && info[1] == 0x23 && info[2] == 0x45 && info[3] == 0x07 && info[4] == 0xBC && info[5] == 0x0A && info[6] == 0x02);
    amiibo_register_info(info);
    CHECK(!strcmp((char *)info + 0x5C, "b figure"));
    amiibo_common_info(info);
    CHECK(info[8] == 0xD8 && info[6] == 0x02);

    /* the application area: none yet, made, read back, kept beside the dump */
    CHECK(amiibo_area_open(0x1234) == AMIIBO_RESULT_NEED_CREATE);
    const char init[] = "hookshot test area";
    CHECK(amiibo_area_create(0x1234, init, sizeof init, 0) == 0);
    CHECK(amiibo_area_create(0x1234, init, sizeof init, 0) == AMIIBO_RESULT_AREA_EXISTS);
    CHECK(amiibo_area_open(0x9999) == AMIIBO_RESULT_WRONG_AREA_ID && amiibo_area_open(0x1234) == 0);
    uint8_t area[0xD8]; uint32_t got = 0;
    CHECK(amiibo_area_get(area, sizeof area, &got) == 0 && got == 0xD8 && !memcmp(area, init, sizeof init));
    CHECK(amiibo_area_set("x", 0xD9) == AMIIBO_RESULT_WRONG_AREA_SIZE);
    CHECK(amiibo_area_set("second", 7) == 0 && amiibo_flush() == 0);
    snprintf(path, sizeof path, "%s/appdata/04112233445566.bin", dir);
    FILE *f = fopen(path, "rb"); CHECK(f); fclose(f);
    snprintf(path, sizeof path, "%s/b figure.bin", dir);
    f = fopen(path, "rb"); uint8_t back[600]; CHECK(fread(back, 1, sizeof back, f) == 540); fclose(f);
    CHECK(!memcmp(back, d, 540));   /* (the dump itself never written) */

    /* the game done with it: taken off once it stops searching */
    amiibo_detect(0);
    CHECK(amiibo_menu_state() == 0 && amiibo_state() == AMIIBO_INITIALIZED);
    amiibo_detect(1);
    CHECK(amiibo_state() == AMIIBO_SEARCHING && !amiibo_tag_seen());

    /* on again (loaded again: its area read back from appdata); a figure the game never reads goes after 20 s */
    test_now = 1000;
    CHECK(amiibo_choose(0) && amiibo_state() == AMIIBO_ACTIVE);
    CHECK(amiibo_mount() && amiibo_area_open(0x1234) == 0);
    CHECK(amiibo_area_get(area, sizeof area, &got) == 0 && !strcmp((char *)area, "second"));
    amiibo_detect(0);
    test_now = 2000;
    CHECK(amiibo_choose(0));
    amiibo_detect(1);
    test_now = 2000 + 21LL * 1000000000LL;
    CHECK(amiibo_state() == AMIIBO_SEARCHING && amiibo_menu_state() == 0);
    CHECK(amiibo_choose(-1) && amiibo_menu_state() == 0);
    printf("ok\n");
    return 0;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default=shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"))
    a = ap.parse_args()
    if not a.cc:
        print("SKIP: no C compiler")
        return 0
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "amiibo_test_stubs.h").write_text(STUBS)
        (t / "main.c").write_text(MAIN)
        exe = t / "amiibo_test"
        flags = ["-x", "c", "-std=c11", "-D_DEFAULT_SOURCE", "-DAMIIBO_TEST", "-I", str(t), "-I", str(ROOT / "host"), "-Wall",
                 "-Wno-unused-function", "-Wno-format-truncation", "-c"]
        objs = []
        for src in (t / "main.c", ROOT / "host" / "amiibo.c"):   # (each compiled as C, then linked: g++ took the second as C++)
            objs.append(str(t / (src.stem + ".o")))
            r = subprocess.run([a.cc] + flags + ["-o", objs[-1], str(src)], capture_output=True, text=True)
            if r.returncode:
                print(r.stdout + r.stderr)
                print("FAILED: %s does not compile" % src.name)
                return 1
        r = subprocess.run([a.cc, "-o", str(exe)] + objs, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr)
            print("FAILED: does not link")
            return 1
        dumps = t / "amiibo"
        dumps.mkdir()
        env = dict(os.environ, HOS_AMIIBO_DIR=str(dumps))
        r = subprocess.run([str(exe), str(dumps)], capture_output=True, text=True, env=env)
        print(r.stdout + r.stderr)
        if r.returncode or "ok" not in r.stdout:
            print("FAILED")
            return 1
    nfp = (ROOT / "host" / "nn_nfp.c").read_text(encoding="utf-8")
    for sym in ("_ZN2nn3nfp10InitializeEv", "_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii",
                "_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE", "_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE",
                "_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE",
                "_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE"):
        if "HLE(%s)" % sym not in nfp:
            print("FAILED: host/nn_nfp.c does not define %s" % sym)
            return 1
    print("test_amiibo: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
