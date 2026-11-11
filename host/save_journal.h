/* (hookshot) Journaled save data: the game's writes go to a working copy, and nn::fs::Commit makes them the save in one
   atomic step. host/save_journal.c has the layout, the steps and the recovery rule; host/nn_fs.c calls it. */
#ifndef HOS_SAVE_JOURNAL_H
#define HOS_SAVE_JOURNAL_H
#include <stddef.h>
#include <stdint.h>

#define SJ_PATH 1024
#define SJ_BACKUPS 3   /* (the committed saves before the current one kept in save-backup) */

typedef struct {
    char save[SJ_PATH];      /* <user>/save/<uid>: the committed save, the folder the emulators' layout has */
    char tx[SJ_PATH];        /* <user>/save-tx/<uid>: the working copy and a commit's staging */
    char work[SJ_PATH];      /* <tx>/work: the working copy, the save mount's root */
    char fresh[SJ_PATH];     /* <tx>/new: a commit's copy of the working copy, being written */
    char old[SJ_PATH];       /* <tx>/old: the committed save a commit replaced, on its way to save-backup */
    char backups[SJ_PATH];   /* <user>/save-backup/<uid>: the SJ_BACKUPS saves before the current one */
    char ready[SJ_PATH];     /* <tx>/ready-<n>: a finished commit not swapped in yet (the newest save), "" when none */
    unsigned ready_seq;      /* the highest ready-<n> made or found */
    int crash_at, step, dead;   /* (tests: the commit stops at its crash_at-th step, as a process killed there would) */
    void (*crash)(int step);    /* (and calls this there, when set: HOS_SAVE_CRASH_AT ends the process) */
    intptr_t lock;              /* (the session lock's file, while locked) */
    int locked;
} SaveJournal;

/* Where messages go (hos_log in the game; NULL: nowhere) */
extern void (*sj_log)(const char *fmt, ...);

/* The paths of user id folder uid (its name) under the data folder user. 0 when they do not fit */
int sj_paths(SaveJournal *j, const char *user, const char *uid);
/* The session lock, <tx>/lock, held until the process ends (or sj_unlock): 0 taken; 1 another process (a second Hookshot on
   the same data folder) holds it, and this one must leave the journal alone: no recovery, no working copy; -1 an error */
int sj_lock(SaveJournal *j);
void sj_unlock(SaveJournal *j);
/* Why the journal cannot be used for this save, or NULL: the save folder or the folder of saves is a link, or it is on
   another volume than save-tx and save-backup (a rename between them would be a copy) */
const char *sj_unsuitable(SaveJournal *j);
/* At start, before the save is used: finish or roll back a commit a crash interrupted, and drop the working copy a run
   left (changes no Commit took). Returns what it did, for the log */
const char *sj_recover(SaveJournal *j);
/* The newest save: a finished commit still waiting to be swapped in, else the committed save */
const char *sj_newest(const SaveJournal *j);
/* A fresh working copy of the newest save (the committed save is made, empty, when there is none). 0 on success; -2 when
   no save may be mounted at all (a rollback that failed left the save in <tx>/old, or a run's unsaved changes are still in
   <tx>/work): nothing is changed */
int sj_work_open(SaveJournal *j);
/* The working copy and what it held, gone (the last unmount) */
void sj_work_drop(SaveJournal *j);
/* Commit: the working copy becomes the save. 0 on success (*changed: 0 when it held the save's bytes already, and nothing
   was written); after a failure before the commit point the newest save is as it was. what: a line for the log */
int sj_commit(SaveJournal *j, int *changed, char *what, size_t cap);
/* After a Commit that failed: the working copy written over the newest save file by file, each file replaced whole (what
   Hookshot did before the journal), so the game's progress is not lost. 0 on success; on failure the working copy is
   marked, and the next start keeps it in save-backup (unsaved-<time>) instead of dropping it */
int sj_commit_in_place(SaveJournal *j, char *what, size_t cap);
/* The working copy marked as holding changes no Commit could save (the next start keeps it in save-backup) */
void sj_mark_unsaved(SaveJournal *j);

#endif
