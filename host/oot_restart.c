/* (hookshot) Restart in place: the Insert menu's Restart (gpu/vk/vk_menu.cpp) with its "Restart in place" row on.

   Restart used to save the options and start the game again at its title: the player loaded his save by hand and stood
   where the game had last saved, not where he was. Now, while Link is in play:

   The process that is asked to restart
     1. The menu says so: the renderer's option HOS_OPT_RESTART_PLACE reads HOS_RESTART_SAVE (gpu/vk/vk_api.h).
     2. At Link's next update (host/hos_main.c, a game thread) the game is asked for its own autosave: the request its
        event node OneShotAutoSaveMgrRequestAutoSave makes, made only when the game's own check of that request passes
        and no event (a cutscene, a talk, a map change) plays. For some time after an autosave the game takes no other
        (1800 updates: 30 s at 60 a second): while that is the one thing in the way the menu shows the wait, and the
        request is made as soon as it passes (kAskMs at most). Nothing else is waited for: a refusal goes back to the
        menu, which asks the player whether to restart at the title after all.
     3. The game writes a slot's progress.sav and commits the save (host/nn_fs.c tells). Then the menu is told to go
        on, the window closes as at any restart, and host/hos_relaunch.c starts the game again with a note in its
        environment (HOS_RESTART_NOTE): when Restart was pressed, the slot and its file time, and where Link stood.
     Before any game was in play (the title, the first load) there is nothing to save: the restart goes on at once, as
     before. Nothing restarts into the save unless the game wrote it.

   The game started again
     The note holds only while the save it names is still the newest one (host/oot_autoload.c: hos_oot_newest_save).
     Then the Skip title screen row's presses (#1560, oot_autoload.c) run for this start whatever that row says, and
     the log says when Link is back and how far from where he stood.

   What the game's autosave keeps is the game's business: the place Link stands at, the time of day and what its save
   holds; not the enemies, not things in flight. */
#if !defined(_WIN32) && !defined(_GNU_SOURCE) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L   /* (unsetenv, where the compiler is held to plain C) */
#endif
#include "oot_restart.h"
#include "oot_autoload.h"       /* (hos_oot_newest_save) */
#include "../gpu/vk/vk_api.h"   /* (HOS_OPT_RESTART_PLACE and what it carries) */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern const char *hos_user_dir;   /* (host/nn_fs.c) */
extern void hos_log(const char *fmt, ...);
extern int64_t hos_now_ns(void);   /* (host/hos_thread.c) */
extern int rx_option(int id, int otherwise);   /* (host/rx_backend.c) */
extern void rx_option_set(int id, int value);
extern int hos_oot_player_seen(void);   /* (host/hos_main.c: Link was updated in the last quarter second) */

/* (how long the request may wait for the game to allow it: the pause after an autosave is 1800 updates, a minute at 30
   a second; how long Link may go without an update while it waits; how long the game has to begin writing once it took
   the request, and to finish; the quiet after its commit) */
enum { kAskMs = 90000, kUnseenMs = 1000, kWriteMs = 10000, kSaveMs = 30000, kQuietMs = 300 };

enum { R_OFF, R_ASK, R_SAVING, R_GONE };
static int r_state, r_busy, r_told, r_seen_ever;
static int64_t r_asked_ns, r_seen_ns, r_taken_ns, r_file_ns, r_commit_ns, r_fs_ns, r_cool_ns;
static long long r_asked_ms;   /* (the clock's time Restart was pressed, in ms since 1970) */
static float r_cool0, r_pos[3];
static char r_note[160];
static int64_t r_note_ns;

static long long unix_ms(void) {
    struct timespec ts;
    timespec_get(&ts, TIME_UTC);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static int64_t get(const int64_t *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static void put(int64_t *p, int64_t v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }
static int state(void) { return __atomic_load_n(&r_state, __ATOMIC_ACQUIRE); }
static int state_from(int from, int to) {
    return __atomic_compare_exchange_n(&r_state, &from, to, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}
/* The host's word to the menu (HOS_RESTART_GO and the rest), each said once */
static void tell(int word) {
    if (__atomic_exchange_n(&r_told, word, __ATOMIC_ACQ_REL) != word) rx_option_set(HOS_OPT_RESTART_PLACE, word);
}
static void refuse(int from, const char *why) {
    if (!state_from(from, R_OFF)) return;
    hos_log("restart: %s: the menu asks whether to restart at the title", why);
    tell(HOS_RESTART_REFUSED);
}

int hos_oot_restart_asking(void) { return state() == R_ASK; }

void hos_oot_restart_requesting(void) {
    put(&r_file_ns, 0), put(&r_commit_ns, 0);
    put(&r_taken_ns, hos_now_ns());
}

void hos_oot_restart_answer(int answer, float cooldown, const float pos[3]) {
    const int64_t now = hos_now_ns();
    if (answer == HOS_RESTART_ANS_TAKEN) {
        memcpy(r_pos, pos, sizeof r_pos);
        if (!state_from(R_ASK, R_SAVING)) return;   /* (cancelled meanwhile: the game's save goes on as any of its own) */
        hos_log("restart: the game took the autosave request %.0f ms after Restart, Link at %.2f %.2f %.2f",
                (double)(now - get(&r_asked_ns)) / 1e6, pos[0], pos[1], pos[2]);
        tell(HOS_RESTART_SAVING);
    } else if (answer == HOS_RESTART_ANS_COOLDOWN) {
        if (state() != R_ASK) return;
        /* (the seconds left, from how fast the count falls: over a second at least, the game's update rate is not ours to
           know) */
        int secs = 0;
        if (!get(&r_cool_ns)) {
            r_cool0 = cooldown, put(&r_cool_ns, now);
            hos_log("restart: the game saved a moment ago and takes no autosave for another %.0f updates: waiting", cooldown);
        } else if (now - get(&r_cool_ns) >= 1000000000 && r_cool0 > cooldown) {
            const double rate = (double)(r_cool0 - cooldown) / ((double)(now - get(&r_cool_ns)) / 1e9);
            secs = (int)ceil((double)cooldown / rate);
            if (secs < 1) secs = 1;
            if (secs > 600) secs = 600;
        }
        tell(HOS_RESTART_WAIT + secs);
    } else {
        refuse(R_ASK, answer == HOS_RESTART_ANS_EVENT ? "an event is playing (a cutscene, a talk, a map change)"
                      : answer == HOS_RESTART_ANS_NONE ? "the game's autosave manager was not found"
                                                       : "the game's own check refuses an autosave here");
    }
}

void hos_oot_restart_file(const char *guest_path) {
    const int st = state();
    if (st != R_ASK && st != R_SAVING) return;
    const int64_t now = hos_now_ns();
    const char *name = strrchr(guest_path, '/');
    put(&r_fs_ns, now);
    if (name && !strcmp(name, "/progress.sav") && strstr(guest_path, "/slot_") && get(&r_taken_ns) && !get(&r_file_ns)) {
        put(&r_file_ns, now);
        hos_log("restart: the game writes %s, %.0f ms after Restart", guest_path, (double)(now - get(&r_asked_ns)) / 1e6);
    }
}

void hos_oot_restart_commit(void) {
    const int st = state();
    if ((st != R_ASK && st != R_SAVING) || !get(&r_file_ns)) return;
    const int64_t now = hos_now_ns();
    put(&r_commit_ns, now), put(&r_fs_ns, now);
}

const char *hos_oot_restart_note(void) {
    /* (for the restart that follows the menu's go: the window's close can take its seconds, a pipeline cache written on the
       way; two minutes later it is another restart's business) */
    const int64_t at = get(&r_note_ns);
    return at && hos_now_ns() - at < 120000000000LL && r_note[0] ? r_note : NULL;
}

/* The folder of a slot's file ("slot_03" of .../slot_03/progress.sav) */
static void slot_of(const char *path, char *slot, size_t size) {
    const char *end = path + strlen(path);
    while (end > path && end[-1] != '/' && end[-1] != '\\') end--;
    const char *start = end > path ? end - 1 : path;
    while (start > path && start[-1] != '/' && start[-1] != '\\') start--;
    size_t n = end > start ? (size_t)(end - start - 1) : 0;
    if (n >= size) n = size - 1;
    memcpy(slot, start, n);
    slot[n] = 0;
}

/* The game has saved: the note for the new process, and the menu goes on with the restart */
static void saved(int64_t now) {
    char path[512] = "", slot[32];
    const uint64_t mtime = hos_oot_newest_save(hos_user_dir, path, sizeof path);
    slot_of(path, slot, sizeof slot);
    /* (the newest save has to be the one just written: a file time a few seconds before Restart at the earliest, as file
       times are whole seconds on some file systems) */
    if (!mtime || (long long)mtime * 1000 + 2000 < r_asked_ms || strncmp(slot, "slot_", 5) || strchr(slot, ' ')) {
        refuse(R_SAVING, "the game committed its save, but the newest save on disk is not from now");
        return;
    }
    if (!state_from(R_SAVING, R_GONE)) return;
    snprintf(r_note, sizeof r_note, "%lld %llu %s %.3f %.3f %.3f", r_asked_ms, (unsigned long long)mtime, slot, (double)r_pos[0],
             (double)r_pos[1], (double)r_pos[2]);
    put(&r_note_ns, now);
    hos_log("restart: the game saved %s %.0f ms after Restart: restarting to continue there", slot,
            (double)(now - get(&r_asked_ns)) / 1e6);
    tell(HOS_RESTART_GO);
}

void hos_oot_restart_input(void) {
    if (__atomic_exchange_n(&r_busy, 1, __ATOMIC_ACQUIRE)) return;   /* (another thread's read is at it) */
    const int64_t now = hos_now_ns();
    const int seen = hos_oot_player_seen();
    if (seen) r_seen_ever = 1, put(&r_seen_ns, now);
    const int want = rx_option(HOS_OPT_RESTART_PLACE, 0);
    const int st = state();
    if (st == R_OFF) {
        if (want == HOS_RESTART_SAVE) {
            __atomic_store_n(&r_told, 0, __ATOMIC_RELEASE);
            if (!r_seen_ever) {   /* (the title, the first load: nothing to save) */
                hos_log("restart: no game is in play yet: the game starts again at its title");
                r_note[0] = 0;
                if (state_from(R_OFF, R_GONE)) tell(HOS_RESTART_GO);
            } else if (now - get(&r_seen_ns) > (int64_t)kUnseenMs * 1000000) {
                hos_log("restart: Link is not in play now (a loading screen, a pause, a scene without him): the menu asks "
                        "whether to restart at the title");
                tell(HOS_RESTART_REFUSED);
            } else {
                r_asked_ms = unix_ms();
                put(&r_asked_ns, now), put(&r_taken_ns, 0), put(&r_file_ns, 0), put(&r_commit_ns, 0), put(&r_cool_ns, 0);
                if (state_from(R_OFF, R_ASK)) hos_log("restart: asked with Restart in place on: the game is asked to save first");
            }
        }
    } else if (want != HOS_RESTART_SAVE) {   /* (the menu took it back, or went on after HOS_RESTART_GO) */
        if (st != R_GONE)
            hos_log("restart: cancelled %.0f ms after Restart%s", (double)(now - get(&r_asked_ns)) / 1e6,
                    st == R_SAVING ? "; the save the game took goes on as any of its own" : "");
        __atomic_store_n(&r_state, R_OFF, __ATOMIC_RELEASE);
    } else if (st == R_ASK) {
        if (now - get(&r_asked_ns) > (int64_t)kAskMs * 1000000) refuse(R_ASK, "the game allowed no autosave in 90 s");
        else if (now - get(&r_seen_ns) > (int64_t)kUnseenMs * 1000000)
            refuse(R_ASK, "Link is no longer in play (a loading screen, a pause, a scene without him)");
    } else if (st == R_SAVING) {
        const int64_t taken = get(&r_taken_ns), file = get(&r_file_ns), commit = get(&r_commit_ns);
        if (file && commit >= file && now - get(&r_fs_ns) >= (int64_t)kQuietMs * 1000000) saved(now);
        else if (!file && now - taken > (int64_t)kWriteMs * 1000000) refuse(R_SAVING, "the game took the request but wrote no save in 10 s");
        else if (now - taken > (int64_t)kSaveMs * 1000000) refuse(R_SAVING, "the game's save did not finish in 30 s");
    }
    __atomic_store_n(&r_busy, 0, __ATOMIC_RELEASE);
}

/* ---- the game started again ---- */
static int c_state = -1;   /* (-1 not looked yet, 0 no note or not good, 1 continuing: Link not seen yet, 2 he was) */
static long long c_asked_ms;
static float c_pos[3];

int hos_oot_restart_continuing(void) { return __atomic_load_n(&c_state, __ATOMIC_ACQUIRE) == 1; }

int hos_oot_restart_continue(void) {
    if (__atomic_load_n(&c_state, __ATOMIC_ACQUIRE) >= 0) return hos_oot_restart_continuing();
    char note[160] = "";
    const char *env = getenv(HOS_RESTART_NOTE);
    if (env) snprintf(note, sizeof note, "%s", env);
    /* (not passed on: hos_relaunch.c sets its own or none; a program the game starts has no use for it) */
#ifdef _WIN32
    SetEnvironmentVariableA(HOS_RESTART_NOTE, NULL);
    _putenv(HOS_RESTART_NOTE "=");
#else
    unsetenv(HOS_RESTART_NOTE);
#endif
    int good = 0;
    if (note[0]) {
        long long asked = 0;
        unsigned long long mtime = 0;
        char slot[32] = "", path[512] = "", newest[32];
        double x = 0, y = 0, z = 0;
        const uint64_t have = hos_oot_newest_save(hos_user_dir, path, sizeof path);
        slot_of(path, newest, sizeof newest);
        if (sscanf(note, "%lld %llu %31s %lf %lf %lf", &asked, &mtime, slot, &x, &y, &z) != 6 || strncmp(slot, "slot_", 5)) {
            hos_log("restart: the note \"%s\" does not read: the title stays", note);
        } else if (!have || have != mtime || strcmp(slot, newest)) {
            hos_log("restart: the save made for this restart (%s, file time %llu) is not the newest one now (%s, %llu): the "
                    "title stays", slot, mtime, have ? newest : "none", (unsigned long long)have);
        } else {
            c_asked_ms = asked, c_pos[0] = (float)x, c_pos[1] = (float)y, c_pos[2] = (float)z;
            hos_log("restart: Restart was pressed %.1f s ago with Restart in place on: continuing from %s, saved for it",
                    (double)(unix_ms() - asked) / 1000.0, slot);
            good = 1;
        }
    }
    __atomic_store_n(&c_state, good, __ATOMIC_RELEASE);
    return good;
}

void hos_oot_restart_player(const float pos[3]) {
    int one = 1;
    if (!__atomic_compare_exchange_n(&c_state, &one, 2, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    const double dx = pos[0] - c_pos[0], dy = pos[1] - c_pos[1], dz = pos[2] - c_pos[2];
    hos_log("restart: back in play %.1f s after Restart: Link at %.2f %.2f %.2f, %.2f m from where he stood (%.2f %.2f %.2f)",
            (double)(unix_ms() - c_asked_ms) / 1000.0, pos[0], pos[1], pos[2], sqrt(dx * dx + dy * dy + dz * dz), c_pos[0],
            c_pos[1], c_pos[2]);
}

void hos_oot_restart_reset(void) {
    r_state = R_OFF, r_busy = r_told = r_seen_ever = 0;
    r_asked_ns = r_seen_ns = r_taken_ns = r_file_ns = r_commit_ns = r_fs_ns = r_cool_ns = r_note_ns = 0;
    r_asked_ms = 0, r_cool0 = 0, r_note[0] = 0;
    c_state = -1, c_asked_ms = 0;
}
