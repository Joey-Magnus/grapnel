"""The Insert menu's Mods tab (gpu/vk/vk_menu.cpp) and what the host gives it (gpu/vk/vk_api.h, host/rx_backend.c).

Builds the tab's lines and keys (mod_lines, mods_step, mods_tick: from the source as it is) against a fake host, and checks:
the mods in their order, then each mod's cheats under a heading (a file's own headings shown, never chosen); Up and Down
step over headings and stop at the ends; Left and Right switch a mod off and on; Enter picks a mod up, Up and Down move it a
place (not past the ends), Enter puts it down; a data cheat switches with Left, Right and Enter, a master code or an
unsupported cheat does not; an older host (version 17) shows no Mods tab. And by text: the API's version and functions, the
host's table, the tab strip's title, the restart question's slot for the mods.

python -I -B tests/test_mods_menu.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

FIXTURE = r'''#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <cstddef>
#include <vector>
#ifndef _Static_assert
#define _Static_assert static_assert   /* (rx_nvn.h is C) */
#endif
#include "vk_api.h"
enum MenuTab { TAB_GRAPHICS = 0, TAB_MODS = 4 };
const MkwVkHost* host;
struct FakeMod { const char* name; int on; };
static FakeMod fmods[3] = {{"a", 1}, {"b", 0}, {"c", 1}};
struct FakeCheat { const char* name; const char* mod; int kind, on; };
static FakeCheat fcheats[3] = {{"Section", "a", MKWVK_CHEAT_HEADING, 0}, {"Rupees", "a", MKWVK_CHEAT_DATA, 0},
                               {"Master", "a", MKWVK_CHEAT_MASTER, 1}};
static int nmods = 3, edits;
static int mod_info(int i, const char** name, const char** detail, const char** note, int* on) {
    if (i < 0 || i >= nmods) return 0;
    *name = fmods[i].name, *detail = "", *note = "", *on = fmods[i].on;
    return 1;
}
static void mod_edit(int i, int op) {
    edits++;
    if (op <= 1) fmods[i].on = op;
    else std::swap(fmods[i], fmods[op == 2 ? i - 1 : i + 1]);
}
static uint64_t mods_changed() { return 0; }
static int cheat_info(int i, const char** name, const char** mod, const char** note, int* kind, int* on) {
    if (i < 0 || i >= 3) return 0;
    *name = fcheats[i].name, *mod = fcheats[i].mod, *note = "", *kind = fcheats[i].kind, *on = fcheats[i].on;
    return 1;
}
static void cheat_set(int i, int on) { fcheats[i].on = on; }
namespace {
''' + "%BODY%" + r'''
}
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
static bool press[17];
static void key(int k) {
    std::fill(press, press + 17, false);
    press[k] = true;
    bool changed = false;
    mods_tick(press, changed);
}
enum { UP = 1, DOWN = 2, LEFT = 3, RIGHT = 4, ESC = 5, ENTER = 7 };
int main() {
    MkwVkHost h{};
    h.version = 17, h.mod_info = mod_info, h.mod_edit = mod_edit, h.mods_changed = mods_changed, h.cheat_info = cheat_info,
    h.cheat_set = cheat_set;
    host = &h;
    CHECK(!tab_shown(TAB_MODS) && tab_shown(TAB_GRAPHICS));   /* (a host before version 18: no Mods tab) */
    h.version = 18;
    CHECK(tab_shown(TAB_MODS));
    const std::vector<ModLine> lines = mod_lines();
    std::string kinds;
    for (const ModLine& l : lines) kinds += l.kind;
    CHECK(kinds == "mmmhscc");
    key(DOWN), key(RIGHT);
    CHECK(mods_sel == 1 && fmods[1].on == 1);
    key(LEFT);
    CHECK(fmods[1].on == 0);
    key(ENTER);
    CHECK(mods_grab == 1);
    key(DOWN);
    CHECK(mods_grab == 2 && mods_sel == 2 && !strcmp(fmods[2].name, "b") && !strcmp(fmods[1].name, "c"));
    const int before = edits;
    key(DOWN);   /* (the last place: nothing) */
    CHECK(mods_grab == 2 && edits == before);
    key(UP), key(UP);
    CHECK(mods_grab == 0 && !strcmp(fmods[0].name, "b"));
    key(UP);
    CHECK(mods_grab == 0 && edits == before + 2);
    key(ENTER);
    CHECK(mods_grab == -1);
    key(DOWN), key(DOWN), key(DOWN);   /* (over the headings to the first cheat) */
    CHECK(mods_sel == 5);
    key(RIGHT);
    CHECK(fcheats[1].on == 1);
    key(ENTER);
    CHECK(fcheats[1].on == 0);
    key(DOWN), key(RIGHT);
    CHECK(mods_sel == 6 && fcheats[2].on == 1);
    key(LEFT);
    CHECK(fcheats[2].on == 1);   /* (a master code: always on) */
    key(DOWN);
    CHECK(mods_sel == 6);
    for (int i = 0; i < 8; i++) key(UP);
    CHECK(mods_sel == 0);
    nmods = 0;
    CHECK(!tab_shown(TAB_MODS));
    printf("PASS: the Mods tab: its lines, the switches, moving a mod, the cheats; hidden without mods or an older host\n");
    return 0;
}
'''


def need(ok, what):
    if not ok:
        raise SystemExit("test_mods_menu: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    ver = int(re.search(r"#define MKWVK_API_VERSION (\d+)", api).group(1))
    need(ver >= 18 and all(f in api for f in ("(*mod_info)", "(*mod_edit)", "(*mods_changed)", "(*cheat_info)", "(*cheat_set)")),
         "MkwVkHost has no Mods tab functions (API version 18)")
    need(re.search(r"host_fps_timing,\s*hos_prompts_live_parts,\s*hos_mod_info,\s*hos_mod_edit,\s*hos_mods_changed,\s*hos_cheat_info,\s*hos_cheat_set", backend),
         "host/rx_backend.c does not give the back end the mods' functions, in MkwVkHost's order")
    titles = re.search(r"tab_titles\[TAB_COUNT\] = \{([^}]*)\}", menu).group(1)
    need('"Mods"' in titles and titles.index('"Mods"') < titles.index('"Debug"'), "the tab strip has no Mods title before Debug")
    need("if (!tab_shown(i)) continue;" in menu and "while (!tab_shown(cur_tab));" in menu,
         "the Mods tab is not left out of the strip and the tab keys without mods")
    need("draw_mods(c, cx0, cx1, hx0, hx1, narrow, hh);" in menu and "mods_tick(press, changed);" in menu,
         "the Mods tab is not drawn or not given its keys")
    need('restart_names[mods_slot] = "the mods"' in menu and "host->mods_changed()" in menu,
         "the restart question does not count the mods' order and switches")
    body = menu[menu.index("bool can_mods() {"):menu.index("/// The Mods tab's rows and help")]
    with tempfile.TemporaryDirectory(prefix="mods-menu-") as tmp:
        tmp = Path(tmp)
        (tmp / "fixture.cpp").write_text(FIXTURE.replace("%BODY%", body), encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cxx, "-std=c++20", "-I", str(ROOT / "gpu/vk"), str(tmp / "fixture.cpp"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_mods_menu: failed (exit %d)" % r.returncode)


if __name__ == "__main__":
    main()
