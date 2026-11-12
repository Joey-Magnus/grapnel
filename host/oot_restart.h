/* (hookshot) Restart in place: the Insert menu's Restart saves by the game's own autosave and the game comes back in play
   where that save put the player (oot_restart.c). */
#pragma once
#include <stddef.h>
#include <stdint.h>

/* The variable that tells the game started again which save was made for it (hos_relaunch.c puts it into the new process's
   environment and takes any older one out) */
#define HOS_RESTART_NOTE "HOS_RESTART_CONTINUE"

/* What the game said to the request (hos_main.c, at Link's update): no autosave manager; an event plays (a cutscene, a talk,
   a map change); the game's own check refuses; only the pause after its last autosave is in the way; the request is taken */
enum { HOS_RESTART_ANS_NONE, HOS_RESTART_ANS_EVENT, HOS_RESTART_ANS_REFUSED, HOS_RESTART_ANS_COOLDOWN, HOS_RESTART_ANS_TAKEN };

/* ---- the process that is asked to restart ---- */
/* At each controller read (nn_hid.c, read_input): the menu's request taken up, its time limits, the restart once the game
   has saved. */
void hos_oot_restart_input(void);
/* Link's update asks the game while this is 1 (hos_main.c), says so just before it makes the request, and gives the game's
   answer with the pause's remaining updates and where Link stands. */
int hos_oot_restart_asking(void);
void hos_oot_restart_requesting(void);
void hos_oot_restart_answer(int answer, float cooldown, const float pos[3]);
/* nn_fs.c: the game opened a file of a mount it may write for writing (the guest's path), and committed a mount. */
void hos_oot_restart_file(const char *guest_path);
void hos_oot_restart_commit(void);
/* hos_relaunch.c, as it starts the game again: the note for the new process, NULL when this restart made no save. */
const char *hos_oot_restart_note(void);

/* ---- the game started again ---- */
/* 1 when this start continues from the save made for it: the note is read once, taken out of the environment, and holds
   only while the save it names is still the newest one. oot_autoload.c then presses through the title. */
int hos_oot_restart_continue(void);
/* 1 until Link is seen (hos_main.c asks before it reads his place), then the place for the log's "back in play" line. */
int hos_oot_restart_continuing(void);
void hos_oot_restart_player(const float pos[3]);

/* (tests) forget everything, as a new process. */
void hos_oot_restart_reset(void);
