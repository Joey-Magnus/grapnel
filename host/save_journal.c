/* (hookshot) Journaled save data, adapted from valentderah/totk-pc-recomp runtime/fs_host.c ("save transactions"), whose
   notice follows. Hookshot's own changes: one journal per user id folder beside the save, the emulators' save layout kept
   for the committed save, no hard links (scripts/oot_saves.py and players write save files in place), the commit made on
   the calling thread, and the file calls written here for Windows and POSIX.

   Copyright (c) 2026 Valiantsin Dzerakh
   (whose fs_host.c is itself adapted from MacNativeGames games/totk/runtime/fs_host.c @ b75be8cf, MIT, Copyright (c) 2026
   MacNativeGames contributors, under the same permission notice)

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

   ---- The layout. The save mount is journaled as on Horizon: the game's changes go to a working copy and become the save
   at Commit, in one step; a crash, a kill or a power cut before that leaves the save as the last Commit left it.

     <user>/save/<uid>/            the committed save: what the next start loads (the emulators' layout, docs/saves.md)
     <user>/save-tx/<uid>/work/    the working copy, the save mount's root; deleted at the last Unmount and at start
     <user>/save-tx/<uid>/new/     a commit's copy of the working copy, being written
     <user>/save-tx/<uid>/ready-<n>/  a finished commit not swapped in yet: the newest save
     <user>/save-tx/<uid>/old/     the committed save a commit replaced, on its way to save-backup
     <user>/save-backup/<uid>/<UTC time>/  the SJ_BACKUPS committed saves before the current one

   Commit: (1) copy work to new and flush every file and folder; (2) rename new to ready-<n>: the commit point; the
   ready-<n> it supersedes is deleted; (3) rename save/<uid> to old; (4) rename ready-<n> to save/<uid>; (5) move old to
   save-backup/<time> and keep the newest SJ_BACKUPS. Each rename is flushed (the folders on POSIX, MOVEFILE_WRITE_THROUGH
   on Windows). Windows refuses (3) while a file in save/<uid> is open in another program (a virus scanner, a sync tool,
   Explorer's preview): it is tried for 200 ms, then ready-<n> stays the newest save, the next working copy is made from it,
   and the next Commit or start tries (3) to (5) again. A working copy equal to the newest save commits nothing.

   The recovery rule at start (sj_recover):
     new present          an unfinished copy: deleted (rolled back);
     ready-<n> present    the highest n is the newest save and (3) to (5) run (rolled forward); the others are deleted;
     save/<uid> absent    with no ready-<n> either, old goes back to save/<uid>;
   then old, if still there, goes to save-backup, and work (changes no Commit took) is deleted. */
#include "save_journal.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define SEP '\\'
#else
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#define SEP '/'
#endif

void (*sj_log)(const char *fmt, ...);
#define LOG(...) do { if (sj_log) sj_log(__VA_ARGS__); } while (0)

enum { K_NONE, K_FILE, K_DIR, K_LINK };
#define MOVE_TRIES 40   /* (2 s of 50 ms waits for a rename another program's open file holds up) */
#define SWAP_TRIES 4    /* (200 ms for (3): the commit is safe in ready-<n> meanwhile) */
#define COPY_CHUNK (1u << 20)

/* ---- the file calls ---------------------------------------------------------------------------------------------- */
#ifdef _WIN32
/* UTF-8 -> UTF-16, / made \, and long absolute paths given \\?\ (as host/nn_fs.c fs_wide) */
static const wchar_t *wide(const char *p, wchar_t *w, size_t cap) {
    const size_t n = strlen(p);
    const int already = p[0] == '\\' && p[1] == '\\' && p[2] == '?';
    const int unc = !already && p[0] == '\\' && p[1] == '\\';
    const int drive = p[0] && p[1] == ':' && (p[2] == '\\' || p[2] == '/');
    const int extended = !already && n >= 240 && (drive || unc);
    size_t at = 0;
    if (extended) {
        wcscpy(w, unc ? L"\\\\?\\UNC" : L"\\\\?\\");
        at = wcslen(w);
        if (unc) p++;
    }
    if (MultiByteToWideChar(CP_UTF8, 0, p, -1, w + at, (int)(cap - at)) <= 0) w[0] = 0;
    for (wchar_t *q = w + at; *q; q++)
        if (*q == L'/') *q = L'\\';
    return w;
}
#define W(p) wide((p), (wchar_t[SJ_PATH + 8]){0}, SJ_PATH + 8)
static int kind(const char *p) {
    const DWORD a = GetFileAttributesW(W(p));
    if (a == INVALID_FILE_ATTRIBUTES) return K_NONE;
    return (a & FILE_ATTRIBUTE_REPARSE_POINT) ? K_LINK : (a & FILE_ATTRIBUTE_DIRECTORY) ? K_DIR : K_FILE;
}
static int make_dir(const char *p) { return CreateDirectoryW(W(p), NULL) || GetLastError() == ERROR_ALREADY_EXISTS ? 0 : -1; }
static int remove_file(const char *p) {
    const wchar_t *w = W(p);
    SetFileAttributesW(w, FILE_ATTRIBUTE_NORMAL);   /* (a read-only file is not deleted otherwise) */
    return DeleteFileW(w) ? 0 : -1;
}
static int remove_dir(const char *p) { return RemoveDirectoryW(W(p)) ? 0 : -1; }
static int remove_link(const char *p) { const wchar_t *w = W(p); return DeleteFileW(w) || RemoveDirectoryW(w) ? 0 : -1; }
static void sleep_ms(unsigned ms) { Sleep(ms); }
/* NTFS journals its folder entries; flushing the folder's handle is as far as Windows goes */
static void sync_dir(const char *p) {
    HANDLE h = CreateFileW(W(p), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                           FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (h != INVALID_HANDLE_VALUE) FlushFileBuffers(h), CloseHandle(h);
}
static void parent_of(const char *p, char *out) {
    snprintf(out, SJ_PATH, "%s", p);
    char *s = strrchr(out, '\\'), *f = strrchr(out, '/');
    if (f > s) s = f;
    if (s && s != out) *s = 0;
    else snprintf(out, SJ_PATH, "%s", ".");
}
/* 0, -1, or 1 when another program holds a file in it (worth another try). MOVEFILE_WRITE_THROUGH does not flush a rename
   within one volume, so durable renames flush both folders after it, as on POSIX */
static int rename_once(const char *from, const char *to, int durable) {
    wchar_t a[SJ_PATH + 8], b[SJ_PATH + 8];
    wide(from, a, SJ_PATH + 8), wide(to, b, SJ_PATH + 8);
    if (!MoveFileExW(a, b, durable ? MOVEFILE_WRITE_THROUGH : 0)) {
        const DWORD e = GetLastError();
        return e == ERROR_ACCESS_DENIED || e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION ? 1 : -1;
    }
    if (durable) {
        char pa[SJ_PATH], pb[SJ_PATH];
        parent_of(to, pb), parent_of(from, pa);
        sync_dir(pb);
        if (strcmp(pa, pb)) sync_dir(pa);
    }
    return 0;
}
/* A file over another, in one step (the in-place fallback's per-file replace) */
static int replace_file(const char *from, const char *to) {
    return MoveFileExW(W(from), W(to), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) ? 0 : -1;
}
/* The session lock: an exclusive lock on <tx>/lock, held while the process runs. 0 taken, 1 another process holds it */
typedef HANDLE LockH;
#define NO_LOCK INVALID_HANDLE_VALUE
static int lock_take(const char *p, LockH *h) {
    *h = CreateFileW(W(p), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                     OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (*h == INVALID_HANDLE_VALUE) return -1;
    OVERLAPPED o = {0};
    if (LockFileEx(*h, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &o)) return 0;
    CloseHandle(*h), *h = INVALID_HANDLE_VALUE;
    return 1;
}
static void lock_drop(LockH h) { if (h != INVALID_HANDLE_VALUE) CloseHandle(h); }
/* A file's size and last write time (the fingerprint's), 0 when it cannot be read */
static int stat_of(const char *p, uint64_t *size, uint64_t *mtime) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!GetFileAttributesExW(W(p), GetFileExInfoStandard, &d)) return 0;
    *size = (uint64_t)d.nFileSizeHigh << 32 | d.nFileSizeLow;
    *mtime = (uint64_t)d.ftLastWriteTime.dwHighDateTime << 32 | d.ftLastWriteTime.dwLowDateTime;
    return 1;
}
/* Whether two existing folders are on one volume (the renames between them stay renames) */
static int same_volume(const char *a, const char *b) {
    wchar_t va[MAX_PATH + 1], vb[MAX_PATH + 1];
    return GetVolumePathNameW(W(a), va, MAX_PATH + 1) && GetVolumePathNameW(W(b), vb, MAX_PATH + 1) && !_wcsicmp(va, vb);
}
typedef HANDLE FileH;
#define NO_FILE INVALID_HANDLE_VALUE
static FileH open_read(const char *p) {
    return CreateFileW(W(p), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                       FILE_ATTRIBUTE_NORMAL, NULL);
}
static FileH open_new(const char *p) { return CreateFileW(W(p), GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL); }
static long long read_some(FileH h, void *buf, unsigned n) { DWORD got = 0; return ReadFile(h, buf, n, &got, NULL) ? (long long)got : -1; }
static int write_all(FileH h, const void *buf, unsigned n) { DWORD put = 0; return WriteFile(h, buf, n, &put, NULL) && put == n ? 0 : -1; }
static int flush_file(FileH h) { return FlushFileBuffers(h) ? 0 : -1; }
static void close_file(FileH h) { CloseHandle(h); }
static uint64_t now_utc_ms(struct tm *t) {
    SYSTEMTIME s;
    GetSystemTime(&s);
    memset(t, 0, sizeof *t);
    t->tm_year = s.wYear - 1900, t->tm_mon = s.wMonth - 1, t->tm_mday = s.wDay;
    t->tm_hour = s.wHour, t->tm_min = s.wMinute, t->tm_sec = s.wSecond;
    return s.wMilliseconds;
}
/* The names in folder p (not . and ..), with their kinds: n of them, or -1 */
typedef struct { char name[260]; int kind; } Entry;
static int list_dir(const char *p, Entry **out) {
    char pat[SJ_PATH];
    *out = NULL;
    if ((size_t)snprintf(pat, sizeof pat, "%s\\*", p) >= sizeof pat) return -1;
    WIN32_FIND_DATAW fd;
    HANDLE f = FindFirstFileW(W(pat), &fd);
    if (f == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND ? 0 : -1;
    int n = 0, cap = 0;
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        if (n == cap) *out = (Entry *)realloc(*out, sizeof **out * (size_t)(cap = cap ? cap * 2 : 16));
        if (!*out) { FindClose(f); return -1; }
        Entry *e = &(*out)[n];
        if (WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1, e->name, (int)sizeof e->name, NULL, NULL) <= 0) {
            FindClose(f);   /* (a name too long in UTF-8: the listing would be incomplete, so it fails) */
            return -1;
        }
        e->kind = (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) ? K_LINK
                  : (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? K_DIR : K_FILE;
        n++;
    } while (FindNextFileW(f, &fd));
    FindClose(f);
    return n;
}
#else
static void native(const char *p, char *out) {   /* (host/nn_fs.c's paths have \ for /: host/posix's calls turn them) */
    snprintf(out, SJ_PATH, "%s", p);
    for (char *q = out; *q; q++)
        if (*q == '\\') *q = '/';
}
static const char *nat_(const char *p, char *buf) { native(p, buf); return buf; }
#define N(p) nat_((p), (char[SJ_PATH]){0})
static int kind(const char *p) {
    struct stat st;
    if (lstat(N(p), &st)) return K_NONE;
    return S_ISLNK(st.st_mode) ? K_LINK : S_ISDIR(st.st_mode) ? K_DIR : K_FILE;
}
static int make_dir(const char *p) { return mkdir(N(p), 0755) == 0 || errno == EEXIST ? 0 : -1; }
static int remove_file(const char *p) { return unlink(N(p)) ? -1 : 0; }
static int remove_dir(const char *p) { return rmdir(N(p)) ? -1 : 0; }
static int remove_link(const char *p) { return unlink(N(p)) ? -1 : 0; }
static void sleep_ms(unsigned ms) { usleep(ms * 1000u); }
static void sync_dir(const char *p) {
    const int fd = open(N(p), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd >= 0) fsync(fd), close(fd);
}
static void parent_of(const char *p, char *out) {
    native(p, out);
    char *s = strrchr(out, '/');
    if (s && s != out) *s = 0;
    else snprintf(out, SJ_PATH, "%s", s ? "/" : ".");
}
static int rename_once(const char *from, const char *to, int durable) {
    if (rename(N(from), N(to))) return errno == EBUSY ? 1 : -1;
    if (durable) {   /* (the new entry, and the old one's removal when it was in another folder) */
        char a[SJ_PATH], b[SJ_PATH];
        parent_of(to, b), parent_of(from, a);
        sync_dir(b);
        if (strcmp(a, b)) sync_dir(a);
    }
    return 0;
}
/* A file over another, in one step (the in-place fallback's per-file replace) */
static int replace_file(const char *from, const char *to) {
    if (rename(N(from), N(to))) return -1;
    char b[SJ_PATH];
    parent_of(to, b);
    sync_dir(b);
    return 0;
}
/* The session lock: an exclusive flock on <tx>/lock, held while the process runs. 0 taken, 1 another process holds it */
typedef int LockH;
#define NO_LOCK (-1)
static int lock_take(const char *p, LockH *h) {
    *h = open(N(p), O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (*h < 0) return -1;
    if (!flock(*h, LOCK_EX | LOCK_NB)) return 0;
    const int busy = errno == EWOULDBLOCK;
    close(*h), *h = -1;
    return busy ? 1 : -1;
}
static void lock_drop(LockH h) { if (h >= 0) close(h); }
static int stat_of(const char *p, uint64_t *size, uint64_t *mtime) {
    struct stat st;
    if (lstat(N(p), &st)) return 0;
    *size = (uint64_t)st.st_size;
    *mtime = (uint64_t)st.st_mtim.tv_sec * 1000000000u + (uint64_t)st.st_mtim.tv_nsec;
    return 1;
}
static int same_volume(const char *a, const char *b) {
    struct stat sa, sb;
    return !stat(N(a), &sa) && !stat(N(b), &sb) && sa.st_dev == sb.st_dev;
}
typedef int FileH;
#define NO_FILE (-1)
static FileH open_read(const char *p) { return open(N(p), O_RDONLY | O_CLOEXEC); }
static FileH open_new(const char *p) { return open(N(p), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0644); }
static long long read_some(FileH h, void *buf, unsigned n) {
    for (;;) {
        const ssize_t r = read(h, buf, n);
        if (r >= 0 || errno != EINTR) return r;
    }
}
static int write_all(FileH h, const void *buf, unsigned n) {
    for (unsigned done = 0; done < n;) {
        const ssize_t r = write(h, (const char *)buf + done, n - done);
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) return -1;
        done += (unsigned)r;
    }
    return 0;
}
static int flush_file(FileH h) { return fsync(h) ? -1 : 0; }
static void close_file(FileH h) { close(h); }
static uint64_t now_utc_ms(struct tm *t) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    const time_t s = ts.tv_sec;
    gmtime_r(&s, t);
    return (uint64_t)(ts.tv_nsec / 1000000);
}
typedef struct { char name[256]; int kind; } Entry;
static int list_dir(const char *p, Entry **out) {
    *out = NULL;
    DIR *d = opendir(N(p));
    if (!d) return errno == ENOENT ? 0 : -1;
    int n = 0, cap = 0;
    for (struct dirent *e; (e = readdir(d));) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        if (n == cap) *out = (Entry *)realloc(*out, sizeof **out * (size_t)(cap = cap ? cap * 2 : 16));
        if (!*out) { closedir(d); return -1; }
        snprintf((*out)[n].name, sizeof (*out)[n].name, "%s", e->d_name);
        char full[SJ_PATH];
        (*out)[n].kind = (size_t)snprintf(full, sizeof full, "%s/%s", N(p), e->d_name) < sizeof full ? kind(full) : K_NONE;
        n++;
    }
    closedir(d);
    return n;
}
#endif

static int join(char *out, const char *dir, const char *name) {
    return (size_t)snprintf(out, SJ_PATH, "%s%c%s", dir, SEP, name) < SJ_PATH ? 0 : -1;
}
static int exists(const char *p) { return kind(p) != K_NONE; }

/* Rename, flushed; tried every 50 ms while another program holds a file in it. 0 on success */
static int move(const char *from, const char *to, int tries) {
    for (int i = 0; i < tries; i++) {
        const int e = rename_once(from, to, 1);
        if (e <= 0) return e;
        sleep_ms(50);
    }
    return -1;
}

/* Delete a tree; a link goes itself, never what it points to. 0 when nothing is left */
static int remove_tree(const char *p) {
    const int k = kind(p);
    if (k == K_NONE) return 0;
    if (k == K_LINK) return remove_link(p);
    if (k == K_FILE) return remove_file(p);
    Entry *e;
    const int n = list_dir(p, &e);
    for (int i = 0; i < n; i++) {
        char sub[SJ_PATH];
        if (!join(sub, p, e[i].name)) remove_tree(sub);
    }
    free(e);
    remove_dir(p);
    return exists(p) ? -1 : 0;
}
static int remove_tree_retry(const char *p) {   /* (Windows: a scanner holding a file a moment) */
    for (int i = 0; i < MOVE_TRIES; i++) {
        if (!remove_tree(p)) return 0;
        sleep_ms(50);
    }
    return -1;
}

static void make_dirs(const char *p) {
    char tmp[SJ_PATH];
    snprintf(tmp, sizeof tmp, "%s", p);
    for (char *q = tmp + 1; *q; q++)
        if ((*q == '/' || *q == '\\') && q[-1] != ':') {
            const char c = *q;
            *q = 0, make_dir(tmp), *q = c;
        }
    make_dir(tmp);
}

/* The commit's steps, for the tests' crash_at: 1 when the commit is to stop here, as a process killed here would */
static int crashed(SaveJournal *j) {
    if (j->crash_at && ++j->step == j->crash_at) {
        j->dead = 1;
        if (j->crash) j->crash(j->step);
    }
    return j->dead;
}

static int copy_file(const char *src, const char *dst, int durable, uint64_t *bytes) {
    const FileH in = open_read(src);
    if (in == NO_FILE) return -1;
    const FileH out = open_new(dst);
    if (out == NO_FILE) { close_file(in); return -1; }
    char *buf = (char *)malloc(COPY_CHUNK);
    int ok = buf != NULL;
    while (ok) {
        const long long got = read_some(in, buf, COPY_CHUNK);
        if (got < 0) ok = 0;
        if (got <= 0) break;
        if (write_all(out, buf, (unsigned)got)) ok = 0;
        *bytes += (uint64_t)got;
    }
    if (ok && durable && flush_file(out)) ok = 0;
    free(buf);
    close_file(in);
    close_file(out);
    return ok ? 0 : -1;
}

/* Copy tree src to dst, which must not exist; links are left out. durable: every file and folder flushed, and a crash
   point after each file. 0 on success */
static int copy_tree(SaveJournal *j, const char *src, const char *dst, int durable, int *files, uint64_t *bytes) {
    if (make_dir(dst) || kind(dst) != K_DIR) return -1;
    Entry *e;
    const int n = list_dir(src, &e);
    int bad = n < 0;
    for (int i = 0; i < n && !bad; i++) {
        char s[SJ_PATH], d[SJ_PATH];
        if (e[i].kind == K_LINK) {
            LOG("save: %s%c%s is a link: left out of the copy", src, SEP, e[i].name);
            continue;
        }
        if (join(s, src, e[i].name) || join(d, dst, e[i].name)) { bad = 1; break; }
        if (e[i].kind == K_DIR) bad = copy_tree(j, s, d, durable, files, bytes);
        else {
            bad = copy_file(s, d, durable, bytes);
            *files += !bad;
            if (!bad && durable && crashed(j)) bad = 1;
        }
    }
    free(e);
    if (!bad && durable) sync_dir(dst);
    return bad ? -1 : 0;
}

static int same_file(const char *a, const char *b) {
    const FileH ha = open_read(a), hb = open_read(b);
    char *buf = ha != NO_FILE && hb != NO_FILE ? (char *)malloc(2 * (size_t)COPY_CHUNK) : NULL;
    int same = buf != NULL;
    while (same) {
        long long ga = read_some(ha, buf, COPY_CHUNK), gb = read_some(hb, buf + COPY_CHUNK, COPY_CHUNK);
        /* (a short read of one is not the end of it: read on until both have as much) */
        while (ga > 0 && gb > 0 && ga != gb) {
            if (ga < gb) { const long long m = read_some(ha, buf + ga, (unsigned)(gb - ga)); if (m <= 0) break; ga += m; }
            else { const long long m = read_some(hb, buf + COPY_CHUNK + gb, (unsigned)(ga - gb)); if (m <= 0) break; gb += m; }
        }
        if (ga < 0 || gb < 0 || ga != gb || memcmp(buf, buf + COPY_CHUNK, (size_t)ga)) same = 0;
        else if (!ga) break;
    }
    free(buf);
    if (ha != NO_FILE) close_file(ha);
    if (hb != NO_FILE) close_file(hb);
    return same;
}
static int entry_cmp(const void *a, const void *b) { return strcmp(((const Entry *)a)->name, ((const Entry *)b)->name); }
/* Whether trees a and b hold the same names, kinds and bytes (links: never the same) */
static int same_tree(const char *a, const char *b) {
    Entry *ea, *eb;
    const int na = list_dir(a, &ea), nb = list_dir(b, &eb);
    int same = na >= 0 && na == nb;
    if (same) qsort(ea, (size_t)na, sizeof *ea, entry_cmp), qsort(eb, (size_t)nb, sizeof *eb, entry_cmp);
    for (int i = 0; same && i < na; i++) {
        char pa[SJ_PATH], pb[SJ_PATH];
        same = !strcmp(ea[i].name, eb[i].name) && ea[i].kind == eb[i].kind && ea[i].kind != K_LINK &&
               !join(pa, a, ea[i].name) && !join(pb, b, eb[i].name);
        if (same) same = ea[i].kind == K_DIR ? same_tree(pa, pb) : same_file(pa, pb);
    }
    free(ea);
    free(eb);
    return same;
}

/* ---- backups ----------------------------------------------------------------------------------------------------- */
static int name_cmp(const void *a, const void *b) { return strcmp((const char *)a, (const char *)b); }
/* The backups' folder names (a digit first), oldest first: n, at most 64 */
/* A backup's name as rotate_backup makes them: YYYYMMDD-HHMMSS-mmm, then -NNN... for more in one millisecond. Other
   folders there (a player's own, "unsaved-...", "unapplied-...") are never pruned */
static int backup_name(const char *s) {
    static const char form[] = "dddddddd-dddddd-ddd";
    for (int i = 0; form[i]; i++)
        if (form[i] == 'd' ? s[i] < '0' || s[i] > '9' : s[i] != form[i]) return 0;
    for (s += sizeof form - 1; *s;) {
        if (*s++ != '-' || *s < '0' || *s > '9') return 0;
        while (*s >= '0' && *s <= '9') s++;
    }
    return 1;
}
static int backup_names(SaveJournal *j, char (*names)[48]) {
    Entry *e;
    const int n = list_dir(j->backups, &e);
    int k = 0;
    for (int i = 0; i < n; i++)
        if (e[i].kind == K_DIR && backup_name(e[i].name) && strlen(e[i].name) < 48 && k < 64)
            strcpy(names[k++], e[i].name);
    free(e);
    qsort(names, (size_t)k, sizeof *names, name_cmp);
    return k;
}
/* old to save-backup/<UTC time>, and all but the newest SJ_BACKUPS deleted. A name always sorts after every one there:
   in the newest one's millisecond (or after the clock went back) it is that name and the next -NNN, never one sorting
   lower, which would be pruned first and lose the backup just made */
static void rotate_backup(SaveJournal *j) {
    if (!exists(j->old)) return;
    static char names[64][48];
    make_dirs(j->backups);
    int n = backup_names(j, names);
    struct tm t;
    const unsigned ms = (unsigned)now_utc_ms(&t);
    char name[48], dst[SJ_PATH];
    const int len = snprintf(name, sizeof name, "%04d%02d%02d-%02d%02d%02d-%03u", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday,
                             t.tm_hour, t.tm_min, t.tm_sec, ms);
    const char *newest = n ? names[n - 1] : "";
    if (strcmp(name, newest) <= 0 && strlen(newest) >= (size_t)len) {
        unsigned k = 0;
        sscanf(newest + len, "-%u", &k);
        do snprintf(name, sizeof name, "%.*s-%03u", len, newest, ++k);
        while (strcmp(name, newest) <= 0 && k < 100000);
    }
    if (join(dst, j->backups, name) || move(j->old, dst, MOVE_TRIES)) {
        LOG("save: the replaced save could not be moved to %s: deleted", j->backups);
        remove_tree_retry(j->old);
    }
    n = backup_names(j, names);
    for (int i = 0; i + SJ_BACKUPS < n; i++)
        if (!join(dst, j->backups, names[i])) remove_tree(dst);
}

/* A folder moved into save-backup under <prefix>-<UTC time>, kept (not one rotate_backup prunes). 0 on success */
static int keep_aside(SaveJournal *j, const char *from, const char *prefix) {
    struct tm t;
    const unsigned ms = (unsigned)now_utc_ms(&t);
    char name[64], dst[SJ_PATH];
    snprintf(name, sizeof name, "%s-%04d%02d%02d-%02d%02d%02d-%03u", prefix, t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour,
             t.tm_min, t.tm_sec, ms);
    make_dirs(j->backups);
    return join(dst, j->backups, name) || move(from, dst, MOVE_TRIES) ? -1 : 0;
}

/* ---- the fingerprint of the committed save a commit was made over (S1 of the review: a commit waiting in save-tx is put
   in place only over the save it was made over. One that waited while something else replaced the save (Hookshot with
   HOS_SAVE_JOURNAL=0, an older Hookshot, a copied-in save, the in-place fallback below) would have rolled the older
   progress back over it) ---- */
static uint64_t fp_mix(uint64_t h, const void *p, size_t n) {
    for (size_t i = 0; i < n; i++) h = (h ^ ((const unsigned char *)p)[i]) * 0x100000001b3ULL;
    return h;
}
static uint64_t fp_tree(const char *dir, const char *rel, uint64_t h) {
    Entry *e;
    const int n = list_dir(dir, &e);
    if (n < 0) return fp_mix(h, "?", 1);
    qsort(e, (size_t)n, sizeof *e, entry_cmp);
    for (int i = 0; i < n; i++) {
        char p[SJ_PATH], r[SJ_PATH];
        if (join(p, dir, e[i].name)) continue;
        snprintf(r, sizeof r, "%s/%s", rel, e[i].name);
        h = fp_mix(h, e[i].kind == K_DIR ? "D" : e[i].kind == K_LINK ? "L" : "F", 1);
        h = fp_mix(h, r, strlen(r) + 1);
        uint64_t size = 0, mtime = 0;
        if (e[i].kind == K_FILE && stat_of(p, &size, &mtime)) h = fp_mix(fp_mix(h, &size, 8), &mtime, 8);
        if (e[i].kind == K_DIR) h = fp_tree(p, r, h);
    }
    free(e);
    return h;
}
static void fingerprint(const char *dir, char *out, size_t cap) {
    if (kind(dir) != K_DIR) snprintf(out, cap, "absent");
    else snprintf(out, cap, "%016llx", (unsigned long long)fp_tree(dir, "", 0xcbf29ce484222325ULL));
}
static int write_text(const char *path, const char *text) {   /* (durable: a temporary file, flushed, renamed over) */
    char tmp[SJ_PATH];
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", path) >= sizeof tmp) return -1;
    remove_file(tmp);
    const FileH h = open_new(tmp);
    if (h == NO_FILE) return -1;
    const int bad = write_all(h, text, (unsigned)strlen(text)) || flush_file(h);
    close_file(h);
    return bad || replace_file(tmp, path) ? -1 : 0;
}
static int read_text(const char *path, char *out, size_t cap) {
    const FileH h = open_read(path);
    if (h == NO_FILE) return -1;
    const long long n = read_some(h, out, (unsigned)cap - 1);
    close_file(h);
    if (n < 0) return -1;
    out[n] = 0;
    return 0;
}
static void base_path(const char *ready, char *out) {   /* (tx is at most SJ_PATH - 32 long: sj_paths) */
    if ((size_t)snprintf(out, SJ_PATH, "%s.base", ready) >= SJ_PATH) *out = 0;
}

/* ---- the journal ------------------------------------------------------------------------------------------------- */
int sj_paths(SaveJournal *j, const char *user, const char *uid) {
    memset(j, 0, sizeof *j);
    int bad = (size_t)snprintf(j->save, SJ_PATH, "%s%csave%c%s", user, SEP, SEP, uid) >= SJ_PATH;
    bad |= (size_t)snprintf(j->tx, SJ_PATH, "%s%csave-tx%c%s", user, SEP, SEP, uid) >= SJ_PATH - 32;
    bad |= (size_t)snprintf(j->backups, SJ_PATH, "%s%csave-backup%c%s", user, SEP, SEP, uid) >= SJ_PATH - 48;
    if (bad) return 0;
    join(j->work, j->tx, "work"), join(j->fresh, j->tx, "new"), join(j->old, j->tx, "old");
    return 1;
}

const char *sj_newest(const SaveJournal *j) { return *j->ready ? j->ready : j->save; }

/* Steps (3) to (5). 0 on success; on failure j->ready stays the newest save */
static int swap_in(SaveJournal *j) {
    if (!*j->ready) return 0;
    rotate_backup(j);   /* (an old a failed (5) left: (3) needs its name) */
    char base[SJ_PATH], was[64], now[64];
    base_path(j->ready, base);
    if (kind(j->save) == K_DIR && !read_text(base, was, sizeof was)) {
        fingerprint(j->save, now, sizeof now);
        if (strcmp(was, now)) {   /* (the save changed since this commit was made over it: it is the newer one) */
            const int kept = !keep_aside(j, j->ready, "unapplied");
            LOG("save: a commit waiting in %s was made over an older save than %s, which something replaced since (another "
                "Hookshot, HOS_SAVE_JOURNAL=0, a copied-in save): the newer save is kept, the waiting commit %s", j->ready, j->save,
                kept ? "moved to save-backup (unapplied-...)" : "COULD NOT be moved aside and stays in save-tx");
            if (!kept) return -1;
            remove_file(base);
            *j->ready = 0;
            return 0;
        }
    }
    if (exists(j->save) && move(j->save, j->old, SWAP_TRIES)) {
        LOG("save: the committed save %s cannot be replaced now (a file in it is open in another program?): the commit waits "
            "in %s, which the game loads, and the next Commit or start tries again", j->save, j->ready);
        return -1;
    }
    if (crashed(j)) return -1;
    if (move(j->ready, j->save, MOVE_TRIES)) {
        LOG("save: the finished commit cannot be moved to %s: it waits in %s", j->save, j->ready);
        move(j->old, j->save, MOVE_TRIES);   /* (else the next start rolls forward) */
        return -1;
    }
    remove_file(base);
    *j->ready = 0;
    if (crashed(j)) return -1;
    rotate_backup(j);
    return 0;
}

/* "ready-<n>": n; 0 for any other name */
static unsigned ready_number(const char *name) {
    char *end;
    if (strncmp(name, "ready-", 6) || name[6] < '0' || name[6] > '9') return 0;
    const unsigned long n = strtoul(name + 6, &end, 10);
    return *end || n > 0xffffffffu ? 0 : (unsigned)n;
}
/* The newest finished commit into j->ready; older ones, which it supersedes, deleted */
static void ready_scan(SaveJournal *j) {
    Entry *e;
    const int n = list_dir(j->tx, &e);
    *j->ready = 0, j->ready_seq = 0;
    for (int i = 0; i < n; i++)
        if (e[i].kind == K_DIR && ready_number(e[i].name) > j->ready_seq) j->ready_seq = ready_number(e[i].name);
    for (int i = 0; i < n; i++) {
        const unsigned k = e[i].kind == K_DIR ? ready_number(e[i].name) : 0;
        char p[SJ_PATH], base[SJ_PATH];
        if (!k || join(p, j->tx, e[i].name)) continue;
        if (k == j->ready_seq) snprintf(j->ready, SJ_PATH, "%s", p);
        else remove_tree(p), base_path(p, base), remove_file(base);
    }
    free(e);
}

static const char *recover(SaveJournal *j);
const char *sj_recover(SaveJournal *j) {   /* (the tests' crash points are the commit's, not the recovery's) */
    const int crash_at = j->crash_at;
    j->crash_at = j->step = j->dead = 0;
    const char *did = recover(j);
    j->crash_at = crash_at;
    return did;
}
static const char *recover(SaveJournal *j) {
    const char *did = "nothing to recover";
    if (!exists(j->tx)) return did;   /* (a save from before the journal, or none yet) */
    ready_scan(j);
    int has_save = kind(j->save) == K_DIR;
    if (exists(j->fresh)) {
        remove_tree_retry(j->fresh);
        did = "rolled back an unfinished commit";
    }
    if (!has_save && !*j->ready && kind(j->old) == K_DIR) {
        if (!move(j->old, j->save, MOVE_TRIES)) has_save = 1;
        did = has_save ? "rolled back an interrupted commit (the save before it is back)"
                       : "COULD NOT roll back an interrupted commit: the save is in save-tx/old";
    } else if (exists(j->old) && (has_save || *j->ready)) {
        did = "moved the save an interrupted commit replaced to save-backup";
        rotate_backup(j);
    }
    if (*j->ready)
        did = swap_in(j) ? "a finished commit waits in save-tx: the game loads it from there" : "completed a finished commit";
    char unsaved[SJ_PATH];
    join(unsaved, j->tx, "unsaved");
    if (exists(j->work) && exists(unsaved)) {   /* (a run whose Commit failed and whose changes could not be written at all) */
        if (!keep_aside(j, j->work, "unsaved")) {
            did = "KEPT the last run's working copy, whose Commit failed, in save-backup (unsaved-...): copy it over the save "
                  "to have its progress";
            remove_file(unsaved);
        } else
            did = "the last run's working copy, whose Commit failed, stays in save-tx/work";
        return did;
    }
    remove_file(unsaved);
    if (exists(j->work)) {
        if (remove_tree_retry(j->work)) LOG("save: the last run's working copy %s could not be deleted", j->work);
        if (!strcmp(did, "nothing to recover")) did = "dropped the last run's working copy (changes after its last Commit)";
    }
    return did;
}

int sj_work_open(SaveJournal *j) {
    int files = 0;
    uint64_t bytes = 0;
    make_dirs(j->tx);
    if (!*j->ready && !exists(j->save) && exists(j->old)) {   /* (a rollback that failed: never an empty save over it) */
        LOG("save: %s is missing and the save before it is still in %s: no save is mounted", j->save, j->old);
        return -2;
    }
    char unsaved[SJ_PATH];
    join(unsaved, j->tx, "unsaved");
    if (exists(unsaved) && exists(j->work)) {
        LOG("save: %s holds a run's changes that were never saved: it is not replaced", j->work);
        return -2;
    }
    if (!*j->ready && !exists(j->save)) make_dirs(j->save);   /* (no save yet: the game makes one, empty, as on a console) */
    if (remove_tree_retry(j->work) || copy_tree(j, sj_newest(j), j->work, 0, &files, &bytes)) {
        LOG("save: the working copy %s could not be made from %s", j->work, sj_newest(j));
        return -1;
    }
    LOG("save: working copy of %s: %d files, %llu KB", sj_newest(j), files, (unsigned long long)(bytes >> 10));
    return 0;
}

void sj_work_drop(SaveJournal *j) {
    if (remove_tree_retry(j->work)) LOG("save: the working copy %s was not deleted whole (a file still open?)", j->work);
}

int sj_commit(SaveJournal *j, int *changed, char *what, size_t cap) {
    int files = 0;
    uint64_t bytes = 0;
    j->step = j->dead = 0;
    *changed = 0;
    snprintf(what, cap, "?");
    char unsaved[SJ_PATH];
    join(unsaved, j->tx, "unsaved");
    if (kind(j->work) != K_DIR) {   /* (never an empty or partial save from a working copy that is gone) */
        snprintf(what, cap, "the working copy %s is missing: nothing was committed", j->work);
        return -1;
    }
    const char *base = sj_newest(j);
    if (kind(base) == K_DIR && same_tree(j->work, base)) {   /* (the game wrote what the save holds: no commit, no backup) */
        const int waits = swap_in(j);
        snprintf(what, cap, "nothing changed%s", waits ? "; the newest save still waits in save-tx" : "");
        return j->dead ? -1 : 0;
    }
    if (remove_tree_retry(j->fresh) || copy_tree(j, j->work, j->fresh, 1, &files, &bytes)) {
        if (j->dead) return -1;
        remove_tree(j->fresh);
        snprintf(what, cap, "the working copy could not be copied (disk full?): the save is as it was");
        return -1;
    }
    if (crashed(j)) return -1;
    char ready[SJ_PATH], base_file[SJ_PATH], fp[64];
    fingerprint(j->save, fp, sizeof fp);   /* (the save this commit replaces: swap_in checks it is still that one) */
    if ((size_t)snprintf(ready, sizeof ready, "%s%cready-%010u", j->tx, SEP, j->ready_seq + 1) >= sizeof ready ||
        (base_path(ready, base_file), write_text(base_file, fp)) || move(j->fresh, ready, MOVE_TRIES)) {
        remove_tree(j->fresh);
        remove_file(base_file);
        snprintf(what, cap, "the finished copy could not be renamed: the save is as it was");
        return -1;
    }
    /* (the commit point: from here the next start loads this) */
    j->ready_seq++;
    if (*j->ready) {   /* (superseded: the working copy was made from it and had all of it) */
        char old_base[SJ_PATH];
        base_path(j->ready, old_base);
        remove_tree(j->ready), remove_file(old_base);
    }
    remove_file(unsaved);
    snprintf(j->ready, SJ_PATH, "%s", ready);
    *changed = 1;
    if (crashed(j)) return -1;
    const int waits = swap_in(j);
    if (j->dead) return -1;
    snprintf(what, cap, "%d files, %llu KB%s", files, (unsigned long long)(bytes >> 10),
             waits ? "; it waits in save-tx until the committed save can be replaced" : "");
    return 0;
}

int sj_lock(SaveJournal *j) {
    char p[SJ_PATH];
    make_dirs(j->tx);
    if (join(p, j->tx, "lock")) return -1;
    LockH h;
    const int r = lock_take(p, &h);
    if (!r) {
        j->lock = (intptr_t)h;
        j->locked = 1;
    }
    return r;
}

void sj_unlock(SaveJournal *j) {
    if (j->locked) {
        lock_drop((LockH)j->lock);
        j->locked = 0;
    }
}

const char *sj_unsuitable(SaveJournal *j) {
    char save_dir[SJ_PATH], tx_dir[SJ_PATH], backup_dir[SJ_PATH];
    parent_of(j->save, save_dir), parent_of(j->tx, tx_dir), parent_of(j->backups, backup_dir);
    if (kind(j->save) == K_LINK) return "the save folder is a link (a junction or a symbolic link)";
    if (kind(save_dir) == K_LINK) return "the folder of saves is a link (a junction or a symbolic link)";
    make_dirs(save_dir), make_dirs(tx_dir), make_dirs(backup_dir);
    if (!same_volume(save_dir, tx_dir) || !same_volume(save_dir, backup_dir))
        return "the save folder is on another drive than save-tx and save-backup beside it";
    return NULL;
}

static int copy_over(const char *src, const char *dst, uint64_t *bytes, int *files) {
    if (make_dir(dst) || kind(dst) != K_DIR) return -1;
    Entry *e, *d;
    const int n = list_dir(src, &e);
    if (n < 0) return -1;
    int bad = 0;
    for (int i = 0; i < n && !bad; i++) {
        char s[SJ_PATH], t[SJ_PATH], tmp[SJ_PATH];
        if (e[i].kind == K_LINK) continue;
        if (join(s, src, e[i].name) || join(t, dst, e[i].name)) { bad = 1; break; }
        if (e[i].kind == K_DIR) { bad = copy_over(s, t, bytes, files); continue; }
        if ((size_t)snprintf(tmp, sizeof tmp, "%s.hs-new", t) >= sizeof tmp) { bad = 1; break; }
        remove_file(tmp);
        bad = copy_file(s, tmp, 1, bytes) || replace_file(tmp, t);   /* (each file replaced whole, as before the journal) */
        if (bad) remove_file(tmp);
        else ++*files;
    }
    const int m = bad ? 0 : list_dir(dst, &d);   /* (what the game deleted goes too) */
    for (int i = 0; i < m; i++) {
        char s[SJ_PATH], t[SJ_PATH];
        if (d[i].kind == K_LINK || join(s, src, d[i].name) || join(t, dst, d[i].name)) continue;
        if (!exists(s)) remove_tree(t);
    }
    if (m > 0) free(d);
    free(e);
    return bad ? -1 : 0;
}

int sj_commit_in_place(SaveJournal *j, char *what, size_t cap) {
    int files = 0;
    uint64_t bytes = 0;
    char unsaved[SJ_PATH];
    join(unsaved, j->tx, "unsaved");
    if (kind(j->work) != K_DIR) {
        snprintf(what, cap, "the working copy is missing");
        return -1;
    }
    if (copy_over(j->work, sj_newest(j), &bytes, &files)) {
        write_text(unsaved, "the last Commit failed and its changes could not be written: the next start keeps work\n");
        snprintf(what, cap, "could not be written in place either: the changes stay in %s, and the next start keeps them in "
                 "save-backup", j->work);
        return -1;
    }
    remove_file(unsaved);
    snprintf(what, cap, "written in place over %s instead, file by file, as before the journal (%d files, %llu KB)",
             sj_newest(j), files, (unsigned long long)(bytes >> 10));
    return 0;
}

void sj_mark_unsaved(SaveJournal *j) {
    char unsaved[SJ_PATH];
    if (!join(unsaved, j->tx, "unsaved")) write_text(unsaved, "a Commit failed: the next start keeps the working copy\n");
}
