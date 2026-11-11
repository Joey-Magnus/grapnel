"""The mods' Atmosphere cheats (host/cheats.c): the file's parse and the cheat VM, over a fake guest memory.

Builds cheats.c's VM and parse, from the source as it is, with a fake game module (main, its code below code_end) and heap,
and checks: a store into the heap; a button condition; a pointer chain (load, then store through the register); a loop with
a register store; register conditions (C0) with else; a read outside the guest's memory ending the run; a write into the
game's code listed as not supported (the code is compiled) and never made; headings and {master} codes; a cut-short opcode.

python -I -B tests/test_cheat_vm.py [--cc gcc]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef long LONG;
#define InterlockedExchange(p, v) __atomic_exchange_n((p), (v), __ATOMIC_SEQ_CST)
#define _strdup strdup
#define HOS_HEAP_BASE 0x1000000000ULL
static uint8_t main_mem[0x10000], heap_mem[0x1000];
static const uint64_t hos_main_base = 0x80020000ULL, hos_main_size = 0x10000, hos_main_code_end = 0x80024000ULL;
static int written;
static void *GP(uint64_t a) {
    if (a >= hos_main_base && a < hos_main_base + sizeof main_mem) return main_mem + (a - hos_main_base);
    if (a >= HOS_HEAP_BASE && a < HOS_HEAP_BASE + sizeof heap_mem) return heap_mem + (a - HOS_HEAP_BASE);
    abort();   /* (a read or write the VM did not check) */
}
static int hos_mem_mapped(uint64_t a, uint64_t n) {
    return (a >= hos_main_base && a + n <= hos_main_base + sizeof main_mem) || (a >= HOS_HEAP_BASE && a + n <= HOS_HEAP_BASE + sizeof heap_mem);
}
#define HOS_WRITTEN(p, n) (written += (int)(n))
'''

MAIN = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static uint32_t heap32(int off) { uint32_t v; memcpy(&v, heap_mem + off, 4); return v; }
static Cheat *named(const char *name) {
    for (int i = 0; i < g_n; i++) if (!strcmp(g_cheats[i].name, name)) return &g_cheats[i];
    return NULL;
}
int main(void) {
    char text[] =
        "[Section]\n"
        "{Master code}\n04100000 00000004 0000002A\n"
        "[Rupees 999]\n04100000 00000010 000003E7\n"
        "[Hold A]\n80000001\n04100000 00000020 00000005\n20000000\n"
        "[Pointer]\n58100000 00000040\n64000000 00000000 00000007\n"
        "[Loop]\n40010000 00000000 00000000\n30020000 00000003\n74010000 00000001\n31020000\nA4100410 00000090\n"
        "[Register else]\n40030000 00000000 00000009\nC0453400 00000009\n04100000 000000A0 00000001\n21000000\n04100000 000000A0 00000002\n20000000\n"
        "[Broken chain]\n58100000 00000048\n58001000 00000000\n04100000 000000B0 00000003\n"
        "[Code write]\n04000000 00000100 D503201F\n"
        "[Cut short]\n04100000 00000010\n"
        "[Rupees 999]\n04100000 000000C0 00000001\n";
    parse(text, "mod-a");
    CHECK(g_n == 11);
    for (int i = 0; i < g_n; i++) {
        const int master = g_cheats[i].kind == CHEAT_MASTER;
        g_cheats[i].kind = classify(&g_cheats[i]);
        if (master && g_cheats[i].kind == CHEAT_DATA) g_cheats[i].kind = CHEAT_MASTER;
    }
    CHECK(named("Section")->kind == CHEAT_HEADING && named("Master code")->kind == CHEAT_MASTER);
    CHECK(named("Code write")->kind == CHEAT_UNSUPPORTED && strstr(named("Code write")->note, "game's code"));
    CHECK(named("Cut short")->kind == CHEAT_UNSUPPORTED && strstr(named("Cut short")->note, "cut short"));
    CHECK(strcmp(g_cheats[2].key, g_cheats[10].key) != 0);   /* (a repeated name: its own key, "#2") */
    uint64_t target = HOS_HEAP_BASE + 0x80, broken = 0x5000000000ULL;
    memcpy(heap_mem + 0x40, &target, 8);
    memcpy(heap_mem + 0x48, &broken, 8);
    for (int i = 0; i < g_n; i++)
        if (g_cheats[i].kind == CHEAT_DATA || g_cheats[i].kind == CHEAT_MASTER) run(&g_cheats[i], 0);
    CHECK(heap32(0x04) == 42 && heap32(0x10) == 999 && heap32(0x20) == 0);   /* (A not held) */
    CHECK(heap32(0x80) == 7 && heap32(0x90) == 3 && heap32(0xA0) == 1);
    CHECK(heap32(0xB0) == 0);   /* (the chain read outside the guest: the run ended there) */
    run(named("Hold A"), 1);
    CHECK(heap32(0x20) == 5);
    run(named("Code write"), 0);   /* (never run as a data cheat; even so the code stays as it is) */
    CHECK(main_mem[0x100] == 0);
    const int before = written;
    run(named("Rupees 999"), 0);   /* (the same value again: no write) */
    CHECK(written == before);
    printf("PASS: the cheat VM: stores, buttons, pointer chains, loops, register conditions; code writes refused\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host/cheats.c").read_text(encoding="utf-8")
    body = src[src.index("enum { CHEAT_HEADING"):src.index("/* the file named <build id>.txt")]
    with tempfile.TemporaryDirectory(prefix="cheat-vm-") as tmp:
        tmp = Path(tmp)
        (tmp / "fixture.c").write_text(PRELUDE + body + MAIN, encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable", str(tmp / "fixture.c"),
                        "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_cheat_vm: failed (exit %d)" % r.returncode)


if __name__ == "__main__":
    main()
