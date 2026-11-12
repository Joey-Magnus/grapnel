"""Restart in place: the Insert menu's Restart has the game save first and the game comes back in play at that save.

host/oot_restart.c is the part between the menu, the game and the restart: it is compiled here with host/oot_autoload.c
and run against a made-up game (a clock, the menu's option and the words sent back to it, Link seen or not, the game's
answers to the autosave request, its file calls) and temporary save folders. What must hold:

  the process asked to restart
    - no game in play yet (the title): the restart goes on at once, with no note for the new process
    - in play: nothing restarts before the game wrote a slot's progress.sav, committed, and 300 ms passed; then the menu
      is told to go on and the note names the newest slot, its file time and where Link stood
    - the pause after an autosave: the menu is told to wait, with the seconds once the count's pace is known
    - an event playing, the game's check refusing, Link no longer updated, a request taken but no save written, a save on
      disk that is not from now: the menu is told the game takes no save, and there is no note
    - the menu taking the request back: nothing is told, nothing restarts, no note
    - a run without a window: the restart is started from here, once
  the game started again
    - a note whose slot and file time are the newest save's: this start continues (the title's presses run with the Skip
      title screen row off), the variable is taken out of the environment, and Link's first update is logged with the
      distance from where he stood
    - a note for a save that is no longer the newest, a note that does not read, no note: the title stays
  the restart's command (host/hos_relaunch.h): the note is set once, an older one replaced, and taken out when there is none

and by the sources: the menu's row and its option, the game's side asking only what the game's own check allows.

    python -I -B tests/test_restart_in_place.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "oot_autoload.h"
#include "oot_restart.h"
#include "hos_relaunch.h"
#include "vk_api.h"
#include <time.h>
#include <utime.h>

static int64_t fake_now_ns = 1000000000;
static int want, skip_row, player, taps, told[64], ntold;
static char logged[16384];
const char *hos_user_dir = "";

int64_t hos_now_ns(void) { return fake_now_ns; }
int rx_option(int id, int otherwise) {
    if (id == HOS_OPT_RESTART_PLACE) return want;
    if (id == HOS_OPT_SKIP_TITLE) return skip_row;
    if (id == 1) return 0;
    return otherwise;
}
/* (the menu: it stops asking at the game's side's go or refusal, as gpu/vk/vk_menu.cpp's menu_option_set does) */
void rx_option_set(int id, int value) {
    if (id != HOS_OPT_RESTART_PLACE) return;
    if (ntold < 64) told[ntold++] = value;
    if (value == HOS_RESTART_GO || value == HOS_RESTART_REFUSED) want = 0;
}
int hos_oot_player_seen(void) { return player; }
void hos_hid_tap(const char *presses) { (void)presses, taps++; }
void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const size_t n = strlen(logged);
    vsnprintf(logged + n, sizeof logged - n, fmt, ap);
    va_end(ap);
    if (strlen(logged) + 2 < sizeof logged) strcat(logged, "\n");
}

static int failures;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); failures++; } } while (0)

static void ms(int64_t more) { fake_now_ns += more * 1000000; }
static void tick(void) { hos_oot_restart_input(); }
static int last(void) { return ntold ? told[ntold - 1] : 0; }
static int said(int word) {
    for (int i = 0; i < ntold; i++)
        if (told[i] == word) return 1;
    return 0;
}
static void fresh(const char *user) {
    hos_oot_restart_reset(), hos_oot_autoload_reset();
    hos_user_dir = user, want = 0, player = 0, taps = 0, ntold = 0, logged[0] = 0;
}
static void slot_path(char *path, size_t size, const char *user, const char *slot) {
    snprintf(path, size, "%s/save/00000000000000000000000000000000/%s/progress.sav", user, slot);
}
/* the game writes a slot: the file anew (its time now; the other slot's made 100 s old, as file times are whole seconds on
   some file systems and the newest must be this one), and what nn_fs.c tells */
static void game_writes(const char *user, const char *slot) {
    char path[600], guest[64];
    struct utimbuf old;
    old.actime = old.modtime = time(NULL) - 100;
    slot_path(path, sizeof path, user, strcmp(slot, "slot_00") ? "slot_00" : "slot_01");
    utime(path, &old);
    slot_path(path, sizeof path, user, slot);
    FILE *f = fopen(path, "wb");
    CHECK(f != NULL);
    if (f) fputs("saved", f), fclose(f);
    snprintf(guest, sizeof guest, "save:/%s/progress.sav", slot);
    hos_oot_restart_file(guest);
}
static const float kPos[3] = {-29.5f, 111.6f, 13.9f};
/* Restart pressed in play, and the game's side asking: 1 when Link's update would now ask the game */
static int ask_in_play(const char *user) {
    fresh(user);
    player = 1, tick();   /* (Link has been seen: a game is in play) */
    want = HOS_RESTART_SAVE, ms(16), tick();
    return hos_oot_restart_asking();
}
static void set_note(const char *value) {
#ifdef _WIN32
    _putenv_s(HOS_RESTART_NOTE, value ? value : "");
#else
    if (value) setenv(HOS_RESTART_NOTE, value, 1);
    else unsetenv(HOS_RESTART_NOTE);
#endif
}

int main(int argc, char **argv) {
    CHECK(argc == 3);
    if (argc != 3) return 2;
    const char *user = argv[1], *old = argv[2];   /* (old: its newest save is an hour old and stays so) */

    /* the title: no game in play yet, nothing to save, the restart goes on at once and nothing is handed on */
    fresh(user);
    want = HOS_RESTART_SAVE, tick();
    CHECK(ntold == 1 && last() == HOS_RESTART_GO && !hos_oot_restart_asking() && !hos_oot_restart_note());
    tick(), tick();
    CHECK(ntold == 1);

    /* in play: the game takes the request, writes, commits; the restart only after all three and the quiet */
    CHECK(ask_in_play(user));
    CHECK(ntold == 0);
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    CHECK(last() == HOS_RESTART_SAVING && !hos_oot_restart_asking());
    ms(200), tick();
    CHECK(!said(HOS_RESTART_GO) && !hos_oot_restart_note());
    ms(100), game_writes(user, "slot_01"), ms(50), tick();
    CHECK(!said(HOS_RESTART_GO));   /* (written, not committed) */
    hos_oot_restart_commit(), ms(299), tick();
    CHECK(!said(HOS_RESTART_GO));   /* (committed, the quiet not over) */
    ms(1), tick();
    CHECK(last() == HOS_RESTART_GO);
    {
        const char *note = hos_oot_restart_note();
        long long asked = 0;
        unsigned long long mtime = 0;
        char slot[32] = "", path[600];
        double x = 0, y = 0, z = 0;
        CHECK(note != NULL);
        CHECK(note && sscanf(note, "%lld %llu %31s %lf %lf %lf", &asked, &mtime, slot, &x, &y, &z) == 6);
        CHECK(!strcmp(slot, "slot_01") && mtime == hos_oot_newest_save(user, path, sizeof path));
        CHECK(x > -29.6 && x < -29.4 && y > 111.5 && y < 111.7 && z > 13.8 && z < 14.0);
        ms(100000);
        CHECK(hos_oot_restart_note() != NULL);   /* (the window's close may take its time) */
        ms(21000);
        CHECK(!hos_oot_restart_note());   /* (a note is for the restart that follows, not for one much later) */
    }

    /* the pause after an autosave: wait, with the seconds once a second of the count has been seen; then the save */
    CHECK(ask_in_play(user));
    hos_oot_restart_answer(HOS_RESTART_ANS_COOLDOWN, 1800, kPos);
    CHECK(last() == HOS_RESTART_WAIT && hos_oot_restart_asking());
    ms(1000), tick(), hos_oot_restart_answer(HOS_RESTART_ANS_COOLDOWN, 1740, kPos);
    CHECK(last() == HOS_RESTART_WAIT + 29);   /* (60 a second: 1740 more are 29 s) */
    ms(29000), tick();
    CHECK(hos_oot_restart_asking());
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    game_writes(user, "slot_00"), hos_oot_restart_commit(), ms(300), tick();
    CHECK(last() == HOS_RESTART_GO && hos_oot_restart_note() && strstr(hos_oot_restart_note(), " slot_00 "));
    /* ... but not for ever: 90 s without the game allowing it */
    CHECK(ask_in_play(user));
    for (int i = 0; i < 91 && hos_oot_restart_asking(); i++) hos_oot_restart_answer(HOS_RESTART_ANS_COOLDOWN, 1800, kPos), ms(1000), tick();
    CHECK(last() == HOS_RESTART_REFUSED && !hos_oot_restart_asking() && !hos_oot_restart_note());

    /* the game's side says no: an event plays, the game's check refuses, no manager */
    for (int answer = HOS_RESTART_ANS_NONE; answer <= HOS_RESTART_ANS_REFUSED; answer++) {
        CHECK(ask_in_play(user));
        hos_oot_restart_answer(answer, 0, kPos);
        CHECK(ntold == 1 && last() == HOS_RESTART_REFUSED && !hos_oot_restart_asking());
        ms(60000), tick();
        CHECK(ntold == 1 && !hos_oot_restart_note());
    }

    /* Link is in a game but not updated now (a pause, a loading screen): refused at once; and when he stops being updated
       while the request waits: after a second */
    fresh(user);
    player = 1, tick(), player = 0, ms(2000), tick();
    want = HOS_RESTART_SAVE, tick();
    CHECK(ntold == 1 && last() == HOS_RESTART_REFUSED && !hos_oot_restart_asking());
    CHECK(ask_in_play(user));
    player = 0, ms(900), tick();
    CHECK(ntold == 0 && hos_oot_restart_asking());
    ms(200), tick();
    CHECK(last() == HOS_RESTART_REFUSED && !hos_oot_restart_asking());

    /* the request taken, but the game writes nothing: no restart into an older save */
    CHECK(ask_in_play(user));
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    ms(9999), tick();
    CHECK(last() == HOS_RESTART_SAVING);
    ms(2), tick();
    CHECK(last() == HOS_RESTART_REFUSED && !hos_oot_restart_note());

    /* the game commits, but the newest save on disk is an hour old (not what it just wrote): no restart into it */
    CHECK(ask_in_play(old));
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    hos_oot_restart_file("save:/slot_00/progress.sav"), hos_oot_restart_commit(), ms(300), tick();
    CHECK(last() == HOS_RESTART_REFUSED && !hos_oot_restart_note());

    /* files of the save that are not a slot's progress.sav do not count as the save */
    CHECK(ask_in_play(user));
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    hos_oot_restart_file("save:/option.sav"), hos_oot_restart_file("save:/slot_00/caption.sav"), hos_oot_restart_commit();
    ms(5000), tick();
    CHECK(last() == HOS_RESTART_SAVING);

    /* the menu takes it back (Esc, another row, closed) while the game saves: nothing is told, nothing restarts */
    CHECK(ask_in_play(user));
    hos_oot_restart_requesting(), hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);
    want = 0, ms(100), tick();
    game_writes(user, "slot_01"), hos_oot_restart_commit(), ms(1000), tick();
    CHECK(ntold == 1 && last() == HOS_RESTART_SAVING && !hos_oot_restart_note());
    /* ... and while the request still waits: the game is not asked any more */
    CHECK(ask_in_play(user));
    want = 0, ms(100), tick();
    CHECK(!hos_oot_restart_asking() && ntold == 0);
    hos_oot_restart_answer(HOS_RESTART_ANS_TAKEN, 0, kPos);   /* (the answer of an update that was already under way) */
    ms(1000), tick();
    CHECK(ntold == 0 && !hos_oot_restart_note());

    /* ---- the game started again ---- */
    char path[600], note[200];
    game_writes(user, "slot_01");
    const unsigned long long newest = hos_oot_newest_save(user, path, sizeof path);
    CHECK(newest > 0 && strstr(path, "slot_01"));

    /* the note names the newest save: this start continues, with the Skip title screen row off; Link's first update logged */
    fresh(user);
    snprintf(note, sizeof note, "%lld %llu slot_01 -29.500 111.600 13.900", 1700000000000LL, newest);
    set_note(note);
    CHECK(hos_oot_restart_continue() == 1 && hos_oot_restart_continuing());
    CHECK(getenv(HOS_RESTART_NOTE) == NULL || !*getenv(HOS_RESTART_NOTE));
    skip_row = 0;
    CHECK(!hos_oot_autoload_alone());
    hos_oot_autoload_input();
    CHECK(hos_oot_autoload_alone());   /* (the title gets these presses alone: nn_hid.c leaves the player's out) */
    for (int i = 0; i < 400 && taps < 2; i++) ms(100), hos_oot_autoload_input();
    CHECK(taps == 2 && hos_oot_autoload_alone());
    player = 1;
    hos_oot_restart_player(kPos);
    CHECK(!hos_oot_restart_continuing());
    CHECK(strstr(logged, "back in play") && strstr(logged, "0.00 m from where he stood"));
    ms(2000), hos_oot_autoload_input();
    CHECK(taps == 2 && !hos_oot_autoload_alone());
    /* (the Skip title screen row's own presses, with no note: the player's input stays) */
    fresh(user);
    set_note(NULL), skip_row = 1;
    hos_oot_autoload_input(), ms(20000), hos_oot_autoload_input();
    CHECK(taps == 1 && !hos_oot_autoload_alone());
    skip_row = 0;

    /* the same note, but the game has saved another slot since: the title stays, and nothing is pressed */
    fresh(user);
    set_note(note);
    game_writes(user, "slot_00");
    CHECK(hos_oot_restart_continue() == 0 && !hos_oot_restart_continuing());
    hos_oot_autoload_input(), ms(30000), hos_oot_autoload_input();
    CHECK(taps == 0 && strstr(logged, "the title stays"));

    /* a note that does not read, and none */
    fresh(user);
    set_note("soon");
    CHECK(hos_oot_restart_continue() == 0 && strstr(logged, "does not read"));
    fresh(user);
    set_note(NULL);
    CHECK(hos_oot_restart_continue() == 0 && !logged[0]);
    hos_oot_autoload_input(), ms(30000), hos_oot_autoload_input();
    CHECK(taps == 0);

    /* ---- the restart's command: one note, an older one replaced, none when there is none ---- */
    {
        HosRelaunch r;
        static const char env[] = "A=1\0" HOS_RESTART_NOTE "=old note\0B=2\0";
        memset(&r, 0, sizeof r);
        r.env = (char *)malloc(sizeof env);
        memcpy(r.env, env, sizeof env);
        r.envc = hos_relaunch_split(r.env, sizeof env - 1, &r.envp);
        CHECK(r.envc == 3);
        CHECK(hos_relaunch_setenv(&r, HOS_RESTART_NOTE, "new note"));
        CHECK(r.envc == 3 && !strcmp(r.envp[0], "A=1") && !strcmp(r.envp[1], "B=2") &&
              !strcmp(r.envp[2], HOS_RESTART_NOTE "=new note") && !r.envp[3]);
        CHECK(hos_relaunch_setenv(&r, HOS_RESTART_NOTE, NULL));
        CHECK(r.envc == 2 && !strcmp(r.envp[0], "A=1") && !strcmp(r.envp[1], "B=2") && !r.envp[2]);
        CHECK(hos_relaunch_setenv(&r, "A", NULL) && r.envc == 1 && !strcmp(r.envp[0], "B=2"));   /* (A, not a name that starts with A) */
    }
    /* ---- Windows' restart: the note into the block the game started with, at its place by name, an older one out
       whatever its case; none when there is none ---- */
    {
        static const wchar_t saved[] = L"A=1\0hos_restart_continue=old\0HOS_RESTART_OF=9\0";
        static const wchar_t *const with[] = {L"A=1", L"" HOS_RESTART_NOTE L"=new", L"HOS_RESTART_OF=9"};
        static const wchar_t *const without[] = {L"A=1", L"HOS_RESTART_OF=9"};
        wchar_t *b = hos_relaunch_env_block(saved, L"" HOS_RESTART_NOTE, L"new");
        const wchar_t *e = b;
        for (int i = 0; i < 3; i++, e += wcslen(e) + 1) CHECK(!wcscmp(e, with[i]));
        CHECK(!*e);
        wchar_t *c = hos_relaunch_env_block(b, L"" HOS_RESTART_NOTE, NULL);
        e = c;
        for (int i = 0; i < 2; i++, e += wcslen(e) + 1) CHECK(!wcscmp(e, without[i]));
        CHECK(!*e);
        free(b), free(c);
        b = hos_relaunch_env_block(L"" HOS_RESTART_NOTE L"=old\0", L"" HOS_RESTART_NOTE, NULL);   /* (nothing left: two NULs) */
        CHECK(b && !b[0] && !b[1]);
        free(b);
    }

    if (!failures) puts("restart in place: all checks passed");
    return failures ? 1 : 0;
}
"""


def function(source, start):
    at = source.find(start)
    if at < 0:
        raise SystemExit("no " + start)
    body = source[at:]
    return body[:body.index("\n}\n")]


def check_sources():
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    if not re.search(r'\{TAB_GAMEPLAY, "Restart in place", &opts\.restart_in_place, 0, 1, 1, tx_onoff,', menu):
        raise SystemExit("vk_menu.cpp: no Gameplay row for Restart in place")
    if "int restart_in_place = 1;" not in header:
        raise SystemExit("vk_menu.h: Options has no restart_in_place, On by default")
    if "enum { HOS_OPT_RESTART_PLACE = 64 };" not in api:
        raise SystemExit("vk_api.h: no HOS_OPT_RESTART_PLACE")
    if "if (id == HOS_OPT_RESTART_PLACE) return menu_restart_place();" not in replay:
        raise SystemExit("vk_replay.cpp: the renderer does not answer HOS_OPT_RESTART_PLACE")
    # the menu: with the row off, or after the game's refusal, Restart is the restart it was; the game's side's go and
    # refusal count only while the menu asks
    tick = function(menu, "void menu_tick() {")
    for need in ("opts.restart_in_place && place != 2", "restart_in_place();", "restart_go();", "place_cancel();",
                 "PostMessageA(app_window(), WM_APP + 9"):
        if need not in tick:
            raise SystemExit("menu_tick: Restart in place lacks " + need)
    setter = function(menu, "void menu_option_set(int id, int value) {")
    if "place_state.compare_exchange_strong(asked, 3)" not in setter or "place_state.compare_exchange_strong(asked, 2)" not in setter:
        raise SystemExit("menu_option_set: the game's side's go or refusal is taken whatever the menu's state")
    # the game's side: nothing is asked while an event plays; the request is made only after the game's own check of
    # kind 6 passed, and is kind 6 (kind 0 only ever goes to the check)
    game = function((ROOT / "host" / "hos_main.c").read_text(encoding="utf-8"), "static void oot_restart_request(Ctx *c, uint64_t actor) {")
    event, checked, asked = game.find("if (!oot_events_quiet(c)) {"), game.find("if (!passes[0]) {"), game.find("request(c);")
    if not 0 <= event < checked < asked:
        raise SystemExit("oot_restart_request: the request is not after the event test and the game's own check")
    if "c->x[0] = mgr, c->x[1] = 6, c->x[2] = 0;\n    request(c);" not in game or game.count("request(c);") != 1:
        raise SystemExit("oot_restart_request: the request is not the event node's kind 6, once")
    fs = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
    if "if (want_write) hos_oot_restart_file(g);" not in function(fs, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci) {") or \
            "hos_oot_restart_commit();" not in function(fs, "HLE(_ZN2nn2fs6CommitEPKc) {"):
        raise SystemExit("nn_fs.c: the game's save is not told to oot_restart.c (a file opened for writing, the commit)")
    relaunch = (ROOT / "host" / "hos_relaunch.c").read_text(encoding="utf-8")
    windows = relaunch[relaunch.index("static void relaunch(void) {"):relaunch.index("#else")]
    if "SetEnvironmentVariableA(HOS_RESTART_NOTE, note);" not in windows or \
            "hos_relaunch_env_block(env, L\"\" HOS_RESTART_NOTE, note ? wide : NULL)" not in windows or \
            "hos_relaunch_setenv(&r, HOS_RESTART_NOTE, hos_oot_restart_note());" not in relaunch:
        raise SystemExit("hos_relaunch.c: the note is not set, or not taken out, on both systems")
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    if "hos_oot_restart_input();" not in function(hid, "static void read_input(uint64_t *buttons, int32_t stick[4]) {"):
        raise SystemExit("nn_hid.c: read_input does not run oot_restart.c")
    if "Restart in place" not in (ROOT / "readme.md").read_text(encoding="utf-8"):
        raise SystemExit("readme.md: the Restart in place row is not documented")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    a = p.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory(prefix="restart-in-place-") as tmp:
        root = Path(tmp).resolve()
        for name, ages in (("user", {"slot_00": 3600, "slot_01": 7200}), ("old", {"slot_00": 3600})):
            for slot, age in ages.items():
                d = root / name / "save" / ("0" * 32) / slot
                d.mkdir(parents=True)
                (d / "progress.sav").write_bytes(b"save")
                when = time.time() - age
                os.utime(d / "progress.sav", (when, when))
        src = root / "restart_in_place_test.c"
        exe = root / "restart_in_place_test"
        src.write_text(HARNESS, encoding="utf-8")
        windows = os.name == "nt"
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if windows else 0
        extra = {"creationflags": flags} if windows else {}
        build = subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"),
                                "-I", str(ROOT / "gpu" / "vk"), str(src), str(ROOT / "host" / "oot_restart.c"),
                                str(ROOT / "host" / "oot_autoload.c"), "-lm", "-o", str(exe)], **extra)
        if build.returncode:
            raise SystemExit("the host did not compile: see the compiler's output above")
        run = subprocess.run([str(exe), (root / "user").as_posix(), (root / "old").as_posix()], capture_output=True, text=True, **extra)
        print(run.stdout, end="")
        print(run.stderr, end="")
        if run.returncode:
            raise SystemExit("the restart in place host check failed")
    print("PASS: Restart in place saves by the game's own answer, and the game started again continues only from that save")


if __name__ == "__main__":
    main()
