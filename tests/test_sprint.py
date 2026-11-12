"""Sprint (host/nn_hid.c, the Controls page's row): a control past the Switch's buttons with keys and a gamepad input
that, held while the left stick is pushed, holds A, the game's own run.

host/nn_hid.c's binding table is compiled alone, as tests/test_bound_keys.py does, against a fake hookshot_options.ini
for each case: a new install's defaults (Shift and the left stick's press Sprint, V B, LS no gamepad input); a file from
before Sprint that still has the old defaults (Shift B, the press LS) moved to the new ones; one whose player bound B
elsewhere, or whose V is taken, keeping theirs with no Sprint key over another control's; a version 7 file kept as
written; and a gamepad input bound to Sprint swapping with the Switch button that had it. The sources are checked for
the rest: read_input reads Sprint's key and gamepad input, npad_states hands sprint_step the stick, the menu
has the row and writes its pad_ line, and the file says options_version=7. sprint_step is compiled alone: A only while
steered, the stick let go for its first 120 ms (A down with Link standing: no roll), the key held, the gamepad input a
toggle that ends when Link stops and wants a new press while he moves.
python -I -B tests/test_sprint.py   (needs a C compiler)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_bound_keys  # noqa: E402  (its PRELUDE and the helpers that cut code out of a source)

MAIN = r"""
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s line %d: %s\n", which, __LINE__, #c); fails++; } } while (0)
#define KEY(b) hos_binding(HOS_BIND_KEY, b, 0)
#define KEY2(b) hos_binding(HOS_BIND_KEY, b, 1)
#define PAD(b) hos_binding(HOS_BIND_PAD, b, 0)
int main(int argc, char **argv) {
    (void)argc;
    ini_dir = argv[1];
    const char *which = argv[2];
    binds_load();
    if (!strcmp(which, "new")) {
        CHECK(KEY(HOS_KEY_SPRINT) == VK_SHIFT && KEY2(HOS_KEY_SPRINT) == 0);
        CHECK(PAD(HOS_KEY_SPRINT) == HOS_PAD_LSTICK);
        CHECK(KEY(HOS_SW_B) == 'V' && PAD(HOS_SW_B) == HOS_PAD_SOUTH);
        CHECK(PAD(HOS_SW_LS) == -1 && KEY(HOS_SW_LS) == VK_CONTROL);
        CHECK(PAD(HOS_KEY_MOVE_UP) == -1);   /* (still keys only) */
        /* a gamepad input bound to Sprint swaps with the Switch button that had it */
        hos_bind(HOS_BIND_PAD, HOS_KEY_SPRINT, 0, HOS_PAD_SOUTH);
        CHECK(PAD(HOS_KEY_SPRINT) == HOS_PAD_SOUTH && PAD(HOS_SW_B) == HOS_PAD_LSTICK);
        /* a key bound to Sprint is taken from the button that had it */
        hos_bind(HOS_BIND_KEY, HOS_KEY_SPRINT, 1, 'E');
        CHECK(KEY2(HOS_KEY_SPRINT) == 'E' && KEY(HOS_SW_A) == 0);
        hos_bind(HOS_BIND_PAD, HOS_KEY_MOVE_UP, 0, HOS_PAD_NORTH);   /* no gamepad input for a keys-only control */
        CHECK(PAD(HOS_KEY_MOVE_UP) == -1 && PAD(HOS_SW_X) == HOS_PAD_NORTH);
        hos_bind(HOS_BIND_KEY, -1, 0, 0);   /* Reset to defaults */
        CHECK(KEY(HOS_KEY_SPRINT) == VK_SHIFT && PAD(HOS_KEY_SPRINT) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == -1);
    } else if (!strcmp(which, "old")) {   /* the old defaults, as a menu from before Sprint wrote them */
        CHECK(KEY(HOS_SW_B) == 'V' && KEY(HOS_KEY_SPRINT) == VK_SHIFT);
        CHECK(PAD(HOS_SW_LS) == -1 && PAD(HOS_KEY_SPRINT) == HOS_PAD_LSTICK);
        CHECK(PAD(HOS_SW_B) == HOS_PAD_SOUTH && KEY(HOS_SW_A) == 'E');
    } else if (!strcmp(which, "rebound")) {   /* B on the B key, Shift on X, LS on the right stick's press */
        CHECK(KEY(HOS_SW_B) == 'B' && KEY(HOS_SW_X) == VK_SHIFT);
        CHECK(KEY(HOS_KEY_SPRINT) == 0);   /* (Shift is X's) */
        CHECK(PAD(HOS_SW_LS) == HOS_PAD_RSTICK && PAD(HOS_SW_RS) == HOS_PAD_LSTICK);
        CHECK(PAD(HOS_KEY_SPRINT) == -1);   /* (the press is RS's) */
    } else if (!strcmp(which, "v-taken")) {   /* V already Y's: B keeps Shift, Sprint gets no key */
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && KEY2(HOS_SW_Y) == 'V');
        CHECK(KEY(HOS_KEY_SPRINT) == 0);
    } else if (!strcmp(which, "v6")) {   /* the menu's last version before Sprint: moved as "old" is */
        CHECK(KEY(HOS_SW_B) == 'V' && KEY(HOS_KEY_SPRINT) == VK_SHIFT);
        CHECK(PAD(HOS_SW_LS) == -1 && PAD(HOS_KEY_SPRINT) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "v7")) {   /* written with Sprint: as it is */
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && KEY(HOS_KEY_SPRINT) == 'G');
        CHECK(PAD(HOS_SW_LS) == HOS_PAD_LSTICK && PAD(HOS_KEY_SPRINT) == -1);
    } else {
        CHECK(!"no such case");
    }
    if (!fails) printf("PASS %s\n", which);
    return fails != 0;
}
"""

CASES = {
    "new": None,
    "old": "pad_a=1\nkey_a=69,0\npad_b=0\nkey_b=16,0\npad_ls=7\nkey_ls=17,0\noptions_version=4\n",
    "rebound": "key_b=66,0\nkey_x=16,0\npad_ls=8\npad_rs=7\noptions_version=4\n",
    "v-taken": "key_b=16,0\nkey_y=1,86\npad_ls=7\noptions_version=4\n",
    "v6": "pad_b=0\nkey_b=16,0\npad_ls=7\nkey_ls=17,0\noptions_version=6\n",   # (the menu's last version before Sprint)
    "v7": "key_b=16,0\npad_ls=7\nkey_sprint=71,0\npad_sprint=-1\noptions_version=7\n",
}

class SprintTests(unittest.TestCase):
    def test_sources(self):
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        read = test_bound_keys.block(hid, "static void read_input(")
        self.assertIn("bound_down(HOS_KEY_SPRINT, captured)", read, "read_input does not read Sprint's keys")
        self.assertEqual(read.count("sprint_now = pad_sprint_down();"), 2,
                         "read_input does not read Sprint's gamepad input, in front and behind another window")
        npad = test_bound_keys.block(hid, "static void npad_states(")
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn("const int sprint_held = rx_option(HOS_OPT_SPRINT, 1) ? sprint_now : 0;", npad,
                      "the Controls tab's Sprint row does not turn Sprint off")
        self.assertIn("sprint_step(&buttons, stick, sprint_held, steered, menu_open, hos_now_ns());", npad,
                      "npad_states does not give Sprint the stick as the game will get it")
        self.assertIn('{TAB_CONTROLS, "Sprint", &opts.sprint, 0, 1, 1, tx_onoff,', menu, "the Controls tab has no Sprint row")
        replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
        self.assertIn("if (id == HOS_OPT_SPRINT) return opts.sprint;", replay, "the host cannot see the Sprint row")
        self.assertLess(npad.index("const int steered ="), npad.index("sprint_step("),
                        "Sprint must see the stick before it lets it go")
        names = test_bound_keys.block(hid, "static const char *const bind_names[HOS_KEY_N]")
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        menu_names = test_bound_keys.block(menu, "const char* const bind_names[HOS_KEY_N]")
        self.assertEqual(re.findall(r'"(\w+)"', names), re.findall(r'"(\w+)"', menu_names),
                         "the menu writes other names than host/nn_hid.c reads")
        self.assertEqual(re.findall(r'"(\w+)"', names)[-1], "sprint", "Sprint's lines are not pad_sprint and key_sprint")
        self.assertIn('{HOS_KEY_SPRINT, "Sprint"}', menu, "the Controls page has no Sprint row")
        self.assertIn("|| i == HOS_KEY_SPRINT) {\n                const int alternate", menu, "the menu does not write pad_sprint")
        self.assertIn('fprintf(f, "options_version=7\\n");', menu, "the options file does not say it has Sprint")
        api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
        self.assertIn("HOS_KEY_OC_NOTE_X, HOS_KEY_SPRINT, HOS_KEY_N };", api, "Sprint is not the control after the ocarina's notes")

    def test_bindings(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        code = test_bound_keys.between(hid, "static const char *const bind_names[HOS_KEY_N]", "\nvoid hos_bind(")
        code = code.replace("GetModuleFileNameA(NULL,", "GetModuleFileNameA(0,")
        with tempfile.TemporaryDirectory(prefix="hookshot-sprint-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(test_bound_keys.PRELUDE + code + MAIN, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wno-unused-function", "-I", str(ROOT / "gpu" / "vk"),
                                    "-I", str(ROOT / "gpu"), str(tmp / "t.c"), "-o", str(binary)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for name, ini in CASES.items():
                with self.subTest(case=name):
                    folder = tmp / name
                    folder.mkdir()
                    if ini is not None:
                        (folder / "hookshot_options.ini").write_text(ini, encoding="utf-8")
                    run = subprocess.run([str(binary), str(folder), name], text=True, capture_output=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


STEP_MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
enum { B_A = 0 };
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
static uint64_t b;
static int32_t st[4];
static void step(int held, int steered, int menu, int64_t ms) {
    b = 0, st[0] = steered ? 30000 : 0, st[1] = 0;
    sprint_step(&b, st, held, steered, menu, ms * 1000000);
}
#define RUNS (b & 1)
#define STILL (st[0] == 0)
int main(void) {
    /* the key: A while held and steered; the stick let go for the first 120 ms, then back with A held */
    step(SPRINT_KEY, 0, 0, 0);       CHECK(!RUNS);   /* standing: nothing */
    step(SPRINT_KEY, 1, 0, 1000);    CHECK(RUNS && STILL);
    step(SPRINT_KEY, 1, 0, 1100);    CHECK(RUNS && STILL);
    step(SPRINT_KEY, 1, 0, 1130);    CHECK(RUNS && !STILL);
    step(0, 1, 0, 1200);             CHECK(!RUNS && !STILL);   /* let go: walks */
    step(SPRINT_KEY, 1, 0, 1300);    CHECK(RUNS && STILL);     /* again: a new start */
    step(SPRINT_KEY, 1, 1, 1500);    CHECK(!RUNS);             /* not with the menu open */
    step(0, 1, 0, 1600);
    /* the gamepad input: a toggle while steered */
    step(SPRINT_PAD, 1, 0, 2000);    CHECK(RUNS && STILL);
    step(0, 1, 0, 2050);             CHECK(RUNS && STILL);     /* let go: still runs */
    step(0, 1, 0, 2200);             CHECK(RUNS && !STILL);
    step(SPRINT_PAD, 1, 0, 2300);    CHECK(RUNS);              /* held on: no change */
    step(0, 1, 0, 2400);             CHECK(RUNS);
    step(0, 0, 0, 2500);             CHECK(!RUNS);             /* stopped: off */
    step(0, 1, 0, 2600);             CHECK(!RUNS);             /* moving again: wants a new press */
    step(SPRINT_PAD, 0, 0, 2700);    CHECK(!RUNS);             /* pressed standing: nothing */
    step(SPRINT_PAD, 1, 0, 2800);    CHECK(!RUNS);             /* (still the same press) */
    step(0, 1, 0, 2900);
    step(SPRINT_PAD, 1, 0, 3000);    CHECK(RUNS && STILL);     /* a new press while moving */
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


class SprintStepTests(unittest.TestCase):
    def test_step(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        code = test_bound_keys.block(hid, "enum { SPRINT_KEY") + ";\n" + test_bound_keys.block(hid, "static void sprint_step(")
        head, body = STEP_MAIN.split("static int fails;", 1)
        with tempfile.TemporaryDirectory(prefix="hookshot-sprint-step-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(head + code + "\nstatic int fails;" + body, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Werror", str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = {k: v for k, v in os.environ.items() if k != "HOS_SPRINT_STILL_MS"}
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
