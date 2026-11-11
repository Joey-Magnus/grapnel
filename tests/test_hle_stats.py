"""HOS_HLE_STATS=1 counts every HLE function's calls (host/hos.h's HLE macro) and every host call, and logs every 5 s how
often each ran (host/hos_hostcall.c), in the lines scripts/cpu_report.py --calls reads. Off (the default) nothing is
counted and host calls keep their direct path. The real macro and the real host-call code are compiled with stubs for
the rest of the runtime; three broken variants must fail.

python -I -B tests/test_hle_stats.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
# (env_on, the switches' rule, before the code cut out of the sources)
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")
LONG_NAME = "_ZN2nn5audio42SetI3dl2ReverbLateReverbDecayHighFrequencyRatioEPNS0_15I3dl2ReverbTypeEf"


def cut(source, start, end, what):
    if start not in source:
        raise SystemExit("FAIL: %s: the anchor %r is gone: update the test" % (what, start))
    i = source.index(start)
    if end not in source[i:]:
        raise SystemExit("FAIL: %s: the anchor %r is gone: update the test" % (what, end))
    return source[i:source.index(end, i)]


def hle_macro(header):
    """hos.h's counter type, switch and HLE macro (the macro's continued lines and the one after)"""
    part = cut(header, "typedef struct HleCount", "#define HLE(sym)", "host/hos.h")
    rest = header[header.index("#define HLE(sym)"):].split("\n")
    n = 0
    while rest[n].endswith("\\"):
        n += 1
    return part + "\n".join(rest[:n + 1]) + "\n"


HARNESS = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef long LONG;
typedef unsigned long DWORD;
typedef void *PVOID;
#define WINAPI
typedef struct { int x; } SRWLOCK;
#define SRWLOCK_INIT {0}
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
static long InterlockedIncrement(volatile long *p) { return ++*p; }
static long InterlockedExchange(volatile long *p, long v) { long o = *p; *p = v; return o; }
static void *InterlockedCompareExchangePointer(void *volatile *p, void *x, void *c) { void *v = *p; if (v == c) *p = x; return v; }
static DWORD GetCurrentThreadId(void) { return 1; }
static void Sleep(DWORD ms) { (void)ms; }
typedef DWORD (*Start)(void *);
static Start started;
static void *CreateThread(void *a, size_t s, Start fn, void *p, DWORD f, DWORD *id) { (void)a; (void)s; (void)p; (void)f; (void)id; started = fn; return (void *)1; }
static char logbuf[1 << 16];
static void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    size_t n = strlen(logbuf);
    vsnprintf(logbuf + n, sizeof logbuf - n, fmt, a);
    va_end(a);
    strcat(logbuf, "\n");
}
static void hos_fatal(void *c, const char *m) { (void)c; puts(m); exit(3); }
static int hos_self(void) { return 0; }
static const char *hos_thread_name(int t) { (void)t; return "main"; }
typedef struct { uint64_t x[31]; } Ctx;
typedef void (*A64Fn)(Ctx *c);
void hos_setjmp_return(Ctx *c, uint64_t target) { (void)c; (void)target; }
int hos_trace;
HLE_MACRO
HOSTCALL
HLE(_ZN2nn2os9LockMutexEPNS0_9MutexTypeE) { c->x[0] += 1; }
HLE(_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE) { c->x[0] += 2; }
HLE(LONG_NAME) { c->x[0] += 4; }
static int submits;
static void submit(Ctx *c, void *user) { (void)c; (void)user; submits++; }
int main(int argc, char **argv) {
    const int on = argc > 1;
    if (on) hos_hle_stats_start();   /* (hos_main.c: before the game, so before any host-call lookup) */
    if (on != (started != NULL)) { puts("FAIL: the 5 s thread started without HOS_HLE_STATS, or not with it"); return 1; }
    Ctx c = {{0}};
    for (int i = 0; i < 30; i++) imp__ZN2nn2os9LockMutexEPNS0_9MutexTypeE(&c);
    for (int i = 0; i < 10; i++) imp__ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(&c);
    imp_LONG_NAME(&c);
    if (c.x[0] != 30 + 20 + 4) { puts("FAIL: an HLE function's body did not run once a call"); return 1; }
    const uint64_t addr = hos_hostcall("nvnQueueSubmit", submit, NULL);
    const A64Fn direct = a64_lookup_host(addr);
    printf("direct %d\n", direct != NULL);
    for (int i = 0; i < 7; i++) {
        if (direct) direct(&c);   /* (as lifted code calls a host call it got from a64_lookup) */
        else a64_call_miss(&c, addr);
    }
    if (submits != 7) { puts("FAIL: a host call did not run"); return 1; }
    hle_stats_report();
    printf("%s---\n", logbuf);
    logbuf[0] = 0;
    imp__ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(&c);
    hle_stats_report();
    printf("%s", logbuf);
    return 0;
}
"""


def parse(block):
    """the report as cpu_report.py's hle_calls reads it: the head's numbers and {name: count} in printed order"""
    head = re.search(r"hle: (\d+) calls of (\d+) functions in ([0-9.]+) s", block)
    rows = {}
    for line in block.splitlines():
        if "hle: " in line and not re.search(r"hle: \d+ calls of", line):
            for n, name in re.findall(r"(\d+) ([^;]+?)(?:;|$)", line.split("hle: ", 1)[1]):
                rows[name.strip()] = int(n)
    return head and (int(head.group(1)), int(head.group(2)), float(head.group(3))), rows


def check(out, on):
    """what is wrong with one run's output, or None"""
    first, _, second = out.partition("---\n")
    direct = "direct 1" in first
    head, rows = parse(first.replace("direct 0", "").replace("direct 1", ""))
    if not on:
        if not direct:
            return "off: a host call lost its direct path"
        if head != (0, 0, 5.0) or rows:
            return "off: something was counted: %r %r" % (head, rows)
        return None
    if direct:
        return "on: a host call kept its direct path (not counted)"
    want = {"_ZN2nn2os9LockMutexEPNS0_9MutexTypeE": 30, "_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE": 10,
            "nvnQueueSubmit": 7, LONG_NAME[:64]: 1}
    if head != (48, 4, 5.0) or rows != want:
        return "on: the first report reads %r %r, not (48, 4, 5.0) %r" % (head, rows, want)
    if list(rows.values()) != sorted(rows.values(), reverse=True):
        return "on: not the most called first: %r" % rows
    head, rows = parse(second)
    if head != (1, 1, 5.0) or rows != {"_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE": 1}:
        return "on: the second report is not only the calls since the first: %r %r" % (head, rows)
    return None


def run(compiler, folder, header, hostcall, tag):
    """None when both runs read right, else what went wrong"""
    src = HARNESS.replace("HLE_MACRO", hle_macro(header)).replace("HOSTCALL", hostcall).replace("LONG_NAME", LONG_NAME)
    (folder / (tag + ".cpp")).write_text(src, encoding="utf-8")
    exe = folder / (tag + (".exe" if os.name == "nt" else ""))
    subprocess.run([compiler, "-std=c++17", "-include", ENV_ON_H, "-O1", "-w", str(folder / (tag + ".cpp")), "-o",
                    str(exe)], check=True, timeout=120)
    for on in (False, True):
        result = subprocess.run([str(exe)] + (["on"] if on else []), capture_output=True, text=True, timeout=30)
        if result.returncode:
            return result.stdout.strip() or "exit %d" % result.returncode
        wrong = check(result.stdout, on)
        if wrong:
            return wrong
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    header = (ROOT / "host" / "hos.h").read_text(encoding="utf-8")
    hostcall = cut((ROOT / "host" / "hos_hostcall.c").read_text(encoding="utf-8"), "#define HOS_HOSTCALL_BASE",
                   "/* Call guest code from inside a host function", "host/hos_hostcall.c")
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    if not re.search(r'if \(env_on\("HOS_HLE_STATS"\)\) \{\s*void hos_hle_stats_start\(void\);\s*hos_hle_stats_start\(\);',
                     main_c):
        raise SystemExit("FAIL: host/hos_main.c no longer starts the counters on HOS_HLE_STATS (env_on)")
    if main_c.index('env_on("HOS_HLE_STATS")') > main_c.index("if (!reserve_guest())"):
        raise SystemExit("FAIL: host/hos_main.c starts the counters after the game's memory is set up")

    count = "if (hos_hle_stats) hos_hle_count(&h); "
    broken = (("an HLE macro that never counts", header.replace(count, ""), hostcall),
              ("an HLE macro that counts with the switch off", header.replace(count, "hos_hle_count(&h); "), hostcall),
              ("host calls kept direct with the switch on", header,
               hostcall.replace('|| hos_trace || hos_hle_stats || env_on("HOS_HOSTCALL_SLOW")',
                                '|| hos_trace || env_on("HOS_HOSTCALL_SLOW")')))
    with tempfile.TemporaryDirectory(prefix="hle-stats-") as temporary:
        folder = Path(temporary)
        wrong = run(compiler, folder, header, hostcall, "real")
        if wrong:
            raise SystemExit("FAIL: " + wrong)
        for i, (what, h, c) in enumerate(broken):
            if (h, c) == (header, hostcall):
                raise SystemExit("FAIL: the broken variant '%s' lost its anchor: update the test" % what)
            if not run(compiler, folder, h, c, "broken%d" % i):
                raise SystemExit("FAIL: the check passed " + what)
    print("PASS: HOS_HLE_STATS off counts nothing and keeps host calls direct; on, every HLE function and host call is "
          "counted and each 5 s report has the calls since the last, most called first, names cut at 64 characters; "
          "3 broken variants caught")


if __name__ == "__main__":
    main()
