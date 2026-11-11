"""Journaled save data (host/save_journal.c, called by host/nn_fs.c): a save is replaced whole or not at all.

Builds host/save_journal.c, as it is, into a small driver; each driver run is one game session on a data folder of its
own: the start's recovery, the working copy, the game's changes (a folder copied over the working copy) and Commit. A
crash is a real one: the driver's process ends (exit 3) at the commit's n-th step, for every n the commit has. Checked:

- a save from before the journal (the emulators' layout, no save-tx) loads as it is, and the first commit keeps it in
  save-backup;
- after a crash at any step, the next start has the old save or the new one, whole, never a mix of the two, and the new
  one exactly when the crash came after the commit point; nothing is left in save-tx; a second start changes nothing;
- a working copy the game changed but never committed is not loaded at the next start, and is set aside in save-backup
  (uncommitted-..., the newest 3), never deleted;
- a commit with nothing changed writes nothing and makes no backup; backups rotate to the newest 3, oldest first out;
- a commit the committed save's folder refuses to make way for (POSIX: a folder without write permission; Windows: a
  file held open) waits in save-tx, the game loads it from there, and the next start puts it in place;
- links in a save are left out of the copies; names in UTF-8 (Linux);
- a full disk (Linux: write() fails with ENOSPC from a chosen call on, as a second driver built with it): a Commit that
  cannot be written leaves the save whole (the in-place fallback never part old, part new, at any call it fails at),
  the changes are mounted again as they are in the same run (never replaced by the older save, even with no marker on
  disk), and the next start saves them or, still full, keeps them in save-backup; a commit waiting over a save that was
  replaced since is never loaded, even when it cannot be moved aside.

python -I -B tests/test_save_journal.py [--cc gcc]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
CFLAGS = ["-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_GNU_SOURCE", "-D_CRT_SECURE_NO_WARNINGS"]

ROOT = Path(__file__).resolve().parents[1]
UID = "5a3c9e1f0b7d24680000000000000001"

DRIVER = r'''
#include "save_journal.c"
#ifndef _WIN32
#include <sys/stat.h>
#endif
static void die(int step) { (void)step; fflush(stdout); exit(3); }
static void say(const char *fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); putchar('\n'); }
int main(int argc, char **argv) {
    /* driver <user> <uid> recover | lock <hold s> | unsuitable | session <changes folder or -> <crash at> [commit 0|1]
       [then: "nowork" (the working copy deleted before Commit), "fallback" (a failed Commit written in place, as nn_fs.c
       does), "break-tx" (POSIX: save-tx made read-only before Commit: the commit fails)] */
    SaveJournal j;
    if (argc < 4 || !sj_paths(&j, argv[1], argv[2])) return 2;
    sj_log = say;
    if (!strcmp(argv[3], "unsuitable")) {
        const char *why = sj_unsuitable(&j);
        printf("unsuitable: %s\n", why ? why : "no");
        return 0;
    }
    const int locked = sj_lock(&j);
    printf("lock: %d\n", locked);
    fflush(stdout);
    if (!strcmp(argv[3], "lock")) {
        if (argc > 4) sleep_ms((unsigned)atoi(argv[4]) * 1000u);
        return locked ? 8 : 0;
    }
    if (locked) return 8;   /* (as nn_fs.c: never the journal of a save another process holds) */
    printf("recover: %s\n", sj_recover(&j));
    if (!strcmp(argv[3], "recover")) return 0;
    if (strcmp(argv[3], "session") || argc < 6) return 2;
    const int opened = sj_work_open(&j);
    if (opened) return opened == -2 ? 7 : 4;
    if (strcmp(argv[4], "-")) {   /* (the game's changes: the working copy becomes that folder) */
        int files = 0;
        uint64_t bytes = 0;
        if (remove_tree(j.work) || copy_tree(&j, argv[4], j.work, 0, &files, &bytes)) return 5;
    }
    j.crash_at = atoi(argv[5]);
    j.crash = die;
    if (argc > 6 && !atoi(argv[6])) return 0;   /* (no Commit: the game quit before it) */
    const char *then = argc > 7 ? argv[7] : "";
    if (!strcmp(then, "nowork")) remove_tree(j.work);
#ifndef _WIN32
    if (!strcmp(then, "break-tx")) {   /* (a staging copy that cannot be made, and a save folder that refuses new files) */
        char sub[SJ_PATH], deep[SJ_PATH + 8];
        make_dir(j.fresh), join(sub, j.fresh, "held"), make_dir(sub);
        snprintf(deep, sizeof deep, "%s/x", sub), close(open(deep, O_CREAT | O_WRONLY, 0644));
        chmod(sub, 0555);
        if (argc > 8) chmod(argv[8], 0555);
    }
#endif
    int changed = 0;
    char what[512];
    int r = sj_commit(&j, &changed, what, sizeof what);
    printf("commit: %d changed %d steps %d: %s\n", r, changed, j.step, what);
    if (r && (!strcmp(then, "fallback") || !strcmp(then, "break-tx"))) {
        r = sj_commit_in_place(&j, what, sizeof what);
        printf("in place: %d: %s\n", r, what);
    }
    return r ? 6 : 0;
}
'''

# Fault injection (Linux): every write() of save_journal.c goes through fi_write, which fails with ENOSPC once its budget
# of calls is spent (-1: no limit)
DRIVER_FI = r'''
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#include <stdarg.h>
static long fi_budget = -1;
static ssize_t fi_write(int fd, const void *b, size_t n) {
    if (fi_budget == 0) { errno = ENOSPC; return -1; }
    if (fi_budget > 0) fi_budget--;
    return syscall(SYS_write, fd, b, n);
}
#define write fi_write
#include "save_journal.c"
#undef write
static void say(const char *fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); putchar('\n'); fflush(stdout); }
int main(int argc, char **argv) {
    /* fi <user> <uid> recover <budget>: the start's recovery with that write budget, then the newest save
       fi <user> <uid> session <changes> <commit budget> <in-place budget> [remount]: a session whose Commit gets the
       first budget and, failing, its in-place fallback the second (then marked unsaved, as nn_fs.c does); "remount":
       then, with the marker files gone from disk (as when even they could not be made), the save mounted again in the
       same run (nn_fs.c: the last Unmount kept it, a MountSaveData follows). Ends without Unmount, as a game closed */
    SaveJournal j;
    if (argc < 5 || !sj_paths(&j, argv[1], argv[2])) return 2;
    sj_log = say;
    if (sj_lock(&j)) return 8;
    if (!strcmp(argv[3], "recover")) {
        fi_budget = atol(argv[4]);
        printf("recover: %s\n", sj_recover(&j));
        fi_budget = -1;
        printf("newest: %s\n", sj_newest(&j));
        return 0;
    }
    if (strcmp(argv[3], "session") || argc < 7) return 2;
    printf("recover: %s\n", sj_recover(&j));
    int files = 0, changed = 0;
    uint64_t bytes = 0;
    char what[512];
    if (sj_work_open(&j) || remove_tree(j.work) || copy_tree(&j, argv[4], j.work, 0, &files, &bytes)) return 4;
    fi_budget = atol(argv[5]);
    int r = sj_commit(&j, &changed, what, sizeof what);
    printf("commit: %d: %s\n", r, what);
    if (r) {
        fi_budget = atol(argv[6]);
        r = sj_commit_in_place(&j, what, sizeof what);
        printf("in place: %d: %s\n", r, what);
        if (r) sj_mark_unsaved(&j);
    }
    fi_budget = -1;
    if (argc > 7 && !strcmp(argv[7], "remount")) {
        char p[SJ_PATH];
        join(p, j.tx, "unsaved"), remove_file(p);
        join(p, j.tx, "unsaved.tmp"), remove_file(p);
        printf("remount: %d\n", sj_work_open(&j));
    }
    return r ? 6 : 0;
}
'''


def tree(p):
    """{relative path: bytes, or None for a folder} of a folder; {} when it is not there"""
    out = {}
    p = Path(p)
    if not p.is_dir():
        return out
    for d, dirs, files in os.walk(p):   # (keys with /, as save_a() writes them: Windows' relpath has backslashes)
        for n in dirs:
            out[Path(os.path.relpath(os.path.join(d, n), p)).as_posix()] = None
        for n in files:
            out[Path(os.path.relpath(os.path.join(d, n), p)).as_posix()] = Path(d, n).read_bytes()
    return out


def write_tree(p, files):
    p = Path(p)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    for rel, data in files.items():
        q = p / rel
        if data is None:
            q.mkdir(parents=True, exist_ok=True)
        else:
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(data)


def save_a():   # (the layout of docs/saves.md, made-up bytes)
    return {"account.sav": b"A" * 320, "option.sav": bytes(range(256)) * 160, "slot_00": None,
            "slot_00/progress.sav": b"P0" * 5000, "slot_00/caption.sav": b"C0" * 300, "slot_01": None,
            "slot_01/progress.sav": b"P1" * 5000, "slot_01/caption.sav": b"C1" * 300}


def save_b():   # (A after a save in slot 1 and in a new slot 2, and the settings changed)
    b = dict(save_a())
    b["option.sav"] = bytes(range(255, -1, -1)) * 160
    b["slot_01/progress.sav"] = b"Q1" * 5100
    b["slot_01/caption.sav"] = b"D1" * 300
    b["slot_02"] = None
    b["slot_02/progress.sav"] = b"P2" * 5000
    b["slot_02/caption.sav"] = b"C2" * 300
    return b


class Check:
    def __init__(self, exe, base):
        self.exe, self.base, self.n = exe, Path(base), 0

    def fail(self, msg):
        raise SystemExit("FAIL: " + msg)

    def folder(self, name):
        user = self.base / name
        if user.exists():
            shutil.rmtree(user)
        user.mkdir(parents=True)
        return user

    def run(self, user, *args, code=0):
        r = subprocess.run([str(self.exe), str(user), UID] + [str(a) for a in args], capture_output=True, text=True)
        if r.returncode != code:
            self.fail("driver %s: exit %d, not %d\n%s%s" % (args, r.returncode, code, r.stdout, r.stderr))
        return r.stdout

    def save(self, user):
        return tree(Path(user) / "save" / UID)

    def backups(self, user):
        b = Path(user) / "save-backup" / UID
        return sorted(os.listdir(b)) if b.is_dir() else []

    def clean_tx(self, user, why, allowed=()):
        left = sorted(os.listdir(Path(user) / "save-tx" / UID)) if (Path(user) / "save-tx" / UID).is_dir() else []
        left = [n for n in left if n not in allowed and n not in ("lock", "unsaved.armed")]   # (these stay)
        if left:
            self.fail("%s: left in save-tx: %s" % (why, left))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    cc = shutil.which(a.cc) or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("SKIP: no C compiler")
        return
    posix = os.name != "nt"
    with tempfile.TemporaryDirectory(prefix="save-journal-") as tmp:
        tmp = Path(tmp)
        (tmp / "driver.c").write_text("#include <stdarg.h>\n" + DRIVER, encoding="utf-8")
        exe = tmp / ("driver.exe" if not posix else "driver")
        subprocess.run([cc] + CFLAGS + ["-I", str(ROOT / "host"), str(tmp / "driver.c"), "-o", str(exe)], check=True)
        c = Check(exe, tmp / "runs")
        A, B = save_a(), save_b()
        changes = tmp / "changes-b"
        write_tree(changes, B)

        # A save from before the journal loads as it is; the first commit puts the old one in save-backup
        user = c.folder("old-save")
        write_tree(user / "save" / UID, A)
        out = c.run(user, "recover")
        if "nothing to recover" not in out or c.save(user) != A:
            c.fail("a save from before the journal was touched by the first start:\n" + out)
        out = c.run(user, "session", "-", 0)
        if "commit: 0 changed 0" not in out or c.backups(user):
            c.fail("a session that changed nothing wrote a save or a backup:\n" + out)
        out = c.run(user, "session", changes, 0)
        if "commit: 0 changed 1" not in out or c.save(user) != B:
            c.fail("the commit did not make the working copy the save:\n" + out)
        if len(c.backups(user)) != 1 or tree(user / "save-backup" / UID / c.backups(user)[0]) != A:
            c.fail("the save the commit replaced is not the backup: %s" % c.backups(user))
        c.clean_tx(user, "a commit", allowed=("work",))   # (the working copy stays while the game runs)
        c.run(user, "recover")
        c.clean_tx(user, "the start after a commit")
        print("PASS: a save from before the journal loads unchanged, and a commit replaces it whole (old one backed up)")

        # The commit's step count, from a commit that runs through
        user = c.folder("count")
        write_tree(user / "save" / UID, A)
        out = c.run(user, "session", changes, 1000)
        steps = int(out.split("steps ")[1].split(":")[0])
        if steps < 9:
            c.fail("the commit has %d crash points, fewer than its files" % steps)

        # A crash at every step: the next start has A or B, whole; B exactly after the commit point
        files_b = sum(1 for v in B.values() if v is not None)
        commit_point = files_b + 1   # (each file copied, the copy finished, then the rename: steps after it are past it)
        seen = set()
        for k in range(1, steps + 1):
            user = c.folder("crash-%02d" % k)
            write_tree(user / "save" / UID, A)
            c.run(user, "session", changes, k, code=3)
            out = c.run(user, "recover")
            got = c.save(user)
            if got not in (A, B):
                c.fail("crash at step %d: the save is a mix of the old and the new one (%s)" % (k, out))
            want = B if k > commit_point else A
            if got != want:
                c.fail("crash at step %d (commit point after step %d): the start loaded the %s save\n%s"
                       % (k, commit_point, "old" if got == A else "new", out))
            c.clean_tx(user, "the start after a crash at step %d" % k)
            if got == B and (not c.backups(user) or tree(user / "save-backup" / UID / c.backups(user)[-1]) != A):
                c.fail("crash at step %d: the save the commit replaced is not in save-backup" % k)
            again = c.run(user, "recover")
            if "nothing to recover" not in again or c.save(user) != want:
                c.fail("crash at step %d: a second start changed something: %s" % (k, again))
            seen.add(out.split("recover: ")[1].split("\n")[0])
        print("PASS: a crash at each of the commit's %d steps leaves the old save or the new one, whole (%s)"
              % (steps, "; ".join(sorted(seen))))

        # Changes no Commit took are not loaded at the next start, but set aside (uncommitted-..., the newest 3)
        user = c.folder("uncommitted")
        write_tree(user / "save" / UID, A)
        for i in range(4):
            c.run(user, "session", changes, 0, 0)
            if tree(user / "save-tx" / UID / "work") != B:
                c.fail("the working copy does not hold the game's changes")
            out = c.run(user, "recover")
            aside = [n for n in c.backups(user) if n.startswith("uncommitted-")]
            if c.save(user) != A or "working copy" not in out or len(aside) != min(i + 1, 3):
                c.fail("changes no Commit took reached the save, or were not set aside (%s):\n%s" % (aside, out))
            if any(tree(user / "save-backup" / UID / n) != B for n in aside):
                c.fail("a working copy set aside is not what the game wrote")
            c.clean_tx(user, "the start after an uncommitted session")
        print("PASS: a working copy never committed is not loaded at the next start, but set aside (the newest 3)")

        # A second process on the same data folder: the journal is not its (the session lock), and it touches nothing
        user = c.folder("two-games")
        write_tree(user / "save" / UID, A)
        c.run(user, "session", changes, 0, 0)   # (a run that left its working copy, as a game still running does)
        holder = subprocess.Popen([str(exe), str(user), UID, "lock", "6"], stdout=subprocess.PIPE, text=True)
        if "lock: 0" not in holder.stdout.readline():
            c.fail("the first process did not get the session lock")
        out = c.run(user, "session", changes, 0, code=8)
        if "lock: 1" not in out or c.save(user) != A or tree(user / "save-tx" / UID / "work") != B:
            c.fail("a second process used a journal another process holds:\n" + out)
        holder.wait()
        out = c.run(user, "recover")
        if "lock: 0" not in out or "working copy" not in out:
            c.fail("the lock was not free after the first process ended:\n" + out)
        print("PASS: a second process on the same save gets no journal and leaves the first's working copy alone")

        # A Commit with its working copy gone commits nothing (never an empty save)
        user = c.folder("no-work")
        write_tree(user / "save" / UID, A)
        out = c.run(user, "session", changes, 0, 1, "nowork", code=6)
        if "working copy" not in out or c.save(user) != A or [n for n in os.listdir(user / "save-tx" / UID) if n.startswith("ready")]:
            c.fail("a Commit without its working copy made a save:\n" + out)
        print("PASS: a Commit whose working copy is gone fails and leaves the save as it was")

        # A commit waiting in save-tx is not put over a save something else replaced since (another Hookshot, the journal
        # off, a copied-in save): the newer save stays, the waiting commit goes to save-backup
        user = c.folder("stale-ready")
        write_tree(user / "save" / UID, A)
        c.run(user, "session", changes, commit_point + 1, code=3)   # (dies just after the commit point: ready-<n> waits)
        newer = dict(A)
        newer["slot_00/progress.sav"] = b"N0" * 4000
        write_tree(user / "save" / UID, newer)
        out = c.run(user, "recover")
        aside = [n for n in c.backups(user) if n.startswith("unapplied-")]
        if c.save(user) != newer or len(aside) != 1 or tree(user / "save-backup" / UID / aside[0]) != B:
            c.fail("a waiting commit was rolled over a newer save:\n" + out)
        c.clean_tx(user, "the start after a stale commit")
        print("PASS: a commit waiting over a save that was replaced since is kept aside, not rolled over the newer save")

        # Backups: the newest 3, in order
        user = c.folder("rotate")
        write_tree(user / "save" / UID, A)
        versions = []
        for i in range(5):
            v = dict(A)
            v["slot_00/progress.sav"] = b"V%d" % i * 4000
            versions.append(v)
            write_tree(tmp / "changes-v", v)
            c.run(user, "session", tmp / "changes-v", 0)
        names = c.backups(user)
        if len(names) != 3 or names != sorted(names):
            c.fail("backups: %s, not the newest 3" % names)
        kept = [tree(user / "save-backup" / UID / n) for n in names]
        if kept != versions[1:4] or c.save(user) != versions[4]:
            c.fail("backups do not hold the 3 saves before the current one, oldest first")
        print("PASS: the newest 3 replaced saves are kept in save-backup, oldest first")

        # A committed save that cannot be moved: the commit waits in save-tx and the game loads it from there
        if posix and os.geteuid() != 0:
            user = c.folder("stuck")
            write_tree(user / "save" / UID, A)
            os.chmod(user / "save", 0o555)   # (save/<uid> cannot be renamed away)
            try:
                out = c.run(user, "session", changes, 0)
                ready = [n for n in os.listdir(user / "save-tx" / UID) if n.startswith("ready-") and not n.endswith(".base")]
                if len(ready) != 1 or tree(user / "save-tx" / UID / ready[0]) != B or c.save(user) != A:
                    c.fail("a commit that could not be swapped in is not waiting in save-tx:\n" + out)
                out = c.run(user, "session", "-", 0, 0)   # (the next session's working copy: from the waiting commit)
                if tree(user / "save-tx" / UID / "work") != B:
                    c.fail("the working copy was not made from the commit waiting in save-tx")
            finally:
                os.chmod(user / "save", 0o755)
            out = c.run(user, "recover")
            if c.save(user) != B or "completed a finished commit" not in out:
                c.fail("the next start did not put the waiting commit in place:\n" + out)
            c.clean_tx(user, "the start after a waiting commit")
            print("PASS: a commit the save's folder holds up waits in save-tx, is what the game loads, and lands at the next start")

            # Links in a save are not followed or copied; UTF-8 names
            user = c.folder("links-é漢")
            write_tree(user / "save" / UID, A)
            outside = tmp / "outside"
            write_tree(outside, {"secret.sav": b"x"})
            os.symlink(outside, user / "save" / UID / "slot_09")
            os.symlink(outside / "secret.sav", user / "save" / UID / "linked.sav")
            out = c.run(user, "session", changes, 0)
            if c.save(user) != B or tree(outside) != {"secret.sav": b"x"}:
                c.fail("links in the save were copied or followed:\n" + out)
            print("PASS: links in a save are left out; a data folder with UTF-8 in its name works")

            # A save that is a link (a cloud folder) or on another drive: no journal for it
            user = c.folder("linked")
            write_tree(tmp / "elsewhere" / UID, A)
            (user / "save").mkdir()
            os.symlink(tmp / "elsewhere" / UID, user / "save" / UID)
            out = c.run(user, "unsuitable")
            if "link" not in out:
                c.fail("a linked save folder was taken for the journal:\n" + out)
            out = c.run(c.folder("plain"), "unsuitable")
            if "unsuitable: no" not in out:
                c.fail("a plain save folder was refused:\n" + out)
            print("PASS: a save folder that is a link is refused for the journal (it is written in place, as before)")

            # A Commit that fails is written over the save in place instead (as before the journal)
            user = c.folder("fallback")
            write_tree(user / "save" / UID, A)
            try:
                out = c.run(user, "session", changes, 0, 1, "break-tx")
            finally:
                for d, dirs, _ in os.walk(user):
                    for n in dirs:
                        os.chmod(os.path.join(d, n), 0o755)
            if "commit: -1" not in out or "in place: 0" not in out or c.save(user) != B:
                c.fail("a failed Commit's changes did not reach the save:\n" + out)
            print("PASS: a Commit that fails writes the save in place instead, so the progress is kept")

            # And when that fails too, the next start saves it
            user = c.folder("unsaved")
            write_tree(user / "save" / UID, A)
            try:
                out = c.run(user, "session", changes, 0, 1, "break-tx", user / "save" / UID, code=6)
            finally:
                for d, dirs, _ in os.walk(user):
                    for n in dirs:
                        os.chmod(os.path.join(d, n), 0o755)
                os.chmod(user / "save" / UID, 0o755)
            out2 = c.run(user, "recover")
            if "in place: -1" not in out or "SAVED" not in out2 or c.save(user) != B:
                c.fail("changes no Commit could save were not saved at the next start:\n" + out + out2)
            c.clean_tx(user, "the start that saved a failed Commit's changes")
            print("PASS: changes that could not be saved at all are saved at the next start")

            # A rollback that fails: no save is mounted, never an empty one over the save in save-tx/old
            user = c.folder("stuck-old")
            write_tree(user / "save-tx" / UID / "old", A)
            (user / "save").mkdir()
            os.chmod(user / "save", 0o555)
            try:
                out = c.run(user, "session", "-", 0, 0, code=7)
            finally:
                os.chmod(user / "save", 0o755)
            if tree(user / "save-tx" / UID / "old") != A or (user / "save" / UID).exists():
                c.fail("a failed rollback was followed by a new, empty save:\n" + out)
            print("PASS: a rollback that fails leaves the old save where it is and mounts none")

            # A run without the journal then made an empty save over that failed rollback: the next start puts it back
            os.chmod(user / "save", 0o755)
            (user / "save" / UID).mkdir()
            out = c.run(user, "recover")
            if c.save(user) != A or (user / "save-tx" / UID / "old").exists():
                c.fail("an empty save made over a failed rollback was kept over the real one:\n" + out)
            print("PASS: an empty save made over a failed rollback (journal off) does not push the real one out")
        else:
            print("SKIP: the held-up save and the links (POSIX, not as root)")
        if sys.platform.startswith("linux") and os.geteuid() != 0:
            full_disk(c, cc, tmp, A, B, changes)
        else:
            print("SKIP: the full disk (write() fault injection: Linux, not as root)")


def full_disk(c, cc, tmp, A, B, changes):
    (tmp / "fi.c").write_text(DRIVER_FI, encoding="utf-8")
    fi = Check(tmp / "fi", c.base)
    subprocess.run([cc] + CFLAGS + ["-I", str(ROOT / "host"), str(tmp / "fi.c"), "-o", str(fi.exe)], check=True)

    def work(user):
        return tree(user / "save-tx" / UID / "work")

    # Blocker 1: a full disk at Commit. The save stays A, the changes stay in the working copy, the next start saves them
    user = c.folder("full")
    write_tree(user / "save" / UID, A)
    out = fi.run(user, "session", changes, 0, 0, code=6)
    if c.save(user) != A or work(user) != B or "in place: -1" not in out:
        c.fail("a Commit on a full disk lost the changes or touched the save:\n" + out)
    out2 = fi.run(user, "recover", -1)
    if c.save(user) != B or "SAVED" not in out2:
        c.fail("the next start did not save the changes a full disk held up:\n" + out + out2)
    c.clean_tx(user, "the start that saved them")
    print("PASS: full disk at Commit: the save stays whole, the next start saves the changes")

    # ... and when the disk is still full at the next start: kept in save-backup (a rename needs no space), save whole
    user = c.folder("full-still")
    write_tree(user / "save" / UID, A)
    fi.run(user, "session", changes, 0, 0, code=6)
    out = fi.run(user, "recover", 0)
    kept = [n for n in c.backups(user) if n.startswith("unsaved-")]
    if c.save(user) != A or len(kept) != 1 or tree(user / "save-backup" / UID / kept[0]) != B:
        c.fail("a start on a still-full disk dropped the unsaved changes:\n" + out)
    c.clean_tx(user, "the start that kept them")
    print("PASS: full disk at the next start too: the changes are kept in save-backup, the save stays whole")

    # ... and with no marker on disk at all: the changes are mounted again in the same run (never the older save over
    # them), and the next start, finding a working copy that differs from the save, never deletes it
    user = c.folder("full-remount")
    write_tree(user / "save" / UID, A)
    (user / "save-tx" / UID).mkdir(parents=True)
    out = fi.run(user, "session", changes, 0, 0, "remount", code=6)
    if "remount: 0" not in out or work(user) != B:
        c.fail("a remount in the same run replaced changes no Commit could save:\n" + out)
    for n in ("unsaved", "unsaved.armed", "unsaved.tmp"):
        p = user / "save-tx" / UID / n
        if p.exists():
            p.unlink()
    out = fi.run(user, "recover", 0)
    aside = [n for n in c.backups(user) if n.startswith(("uncommitted-", "unsaved-"))]
    if c.save(user) != A or len(aside) != 1 or tree(user / "save-backup" / UID / aside[0]) != B:
        c.fail("a working copy unlike the save was deleted at the next start:\n" + out)
    print("PASS: unsaved changes are remounted as they are in the same run, and never deleted at the next start")

    # Blocker 2: the in-place fallback failing at each write() call: the save is A or B, whole, never a mix
    seen, k = set(), 0
    while True:
        user = c.folder("partial-%03d" % k)
        write_tree(user / "save" / UID, A)
        r = subprocess.run([str(fi.exe), str(user), UID, "session", str(changes), "0", str(k)], capture_output=True, text=True)
        got = c.save(user)
        if got not in (A, B):
            c.fail("the in-place fallback cut short at write call %d left a mix of the old and new save:\n%s" % (k, r.stdout))
        if got == A and work(user) != B:
            c.fail("the in-place fallback cut short at write call %d lost the changes:\n%s" % (k, r.stdout))
        if [q for q in Path(user / "save" / UID).rglob("*.hs-new")]:
            c.fail("the in-place fallback cut short at write call %d left .hs-new files in the save" % k)
        seen.add("new" if got == B else "old")
        if r.returncode == 0:
            break
        k += 1
        if k > 400:
            c.fail("the in-place fallback never got through")
    print("PASS: the in-place fallback cut short at each of its %d write calls leaves the save whole (%s)"
          % (k, ", ".join(sorted(seen))))

    # Should-fix 1: a commit waiting over a save replaced since, which cannot be moved aside: the newer save is loaded
    user = c.folder("stale-stuck")
    write_tree(user / "save" / UID, A)
    c.run(user, "session", changes, 1000)   # (step count: below, a crash just after the commit point)
    files_b = sum(1 for v in B.values() if v is not None)
    write_tree(user / "save" / UID, A)
    shutil.rmtree(user / "save-backup")
    shutil.rmtree(user / "save-tx")
    c.run(user, "session", changes, files_b + 2, code=3)
    newer = dict(A)
    newer["slot_00/progress.sav"] = b"N0" * 4000
    write_tree(user / "save" / UID, newer)
    (user / "save-backup" / UID).mkdir(parents=True, exist_ok=True)
    os.chmod(user / "save-backup" / UID, 0o555)
    try:
        out = fi.run(user, "recover", -1)
    finally:
        os.chmod(user / "save-backup" / UID, 0o755)
    newest = out.split("newest: ")[1].strip()
    if Path(newest) != user / "save" / UID or c.save(user) != newer:
        c.fail("a stale commit that could not be moved aside is what the game loads:\n" + out)
    print("PASS: a stale waiting commit that cannot be moved aside is not loaded; the newer save is")


if __name__ == "__main__":
    main()
