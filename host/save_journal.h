/* (hookshot) Journaled save data: the game's writes go to a working copy, and nn::fs::Commit makes them the save in one
   atomic step. host/save_journal.c has the layout, the steps and the recovery rule; host/nn_fs.c calls it. */
#ifndef HOS_SAVE_JOURNAL_H
#define HOS_SAVE_JOURNAL_H
#include <stddef.h>

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
} SaveJournal;

/* Where messages go (hos_log in the game; NULL: nowhere) */
extern void (*sj_log)(const char *fmt, ...);

/* The paths of user id folder uid (its name) under the data folder user. 0 when they do not fit */
int sj_paths(SaveJournal *j, const char *user, const char *uid);
/* At start, before the save is used: finish or roll back a commit a crash interrupted, and drop the working copy a run
   left (changes no Commit took). Returns what it did, for the log */
const char *sj_recover(SaveJournal *j);
/* The newest save: a finished commit still waiting to be swapped in, else the committed save */
const char *sj_newest(const SaveJournal *j);
/* A fresh working copy of the newest save (the committed save is made, empty, when there is none). 0 on success */
int sj_work_open(SaveJournal *j);
/* The working copy and what it held, gone (the last unmount) */
void sj_work_drop(SaveJournal *j);
/* Commit: the working copy becomes the save. 0 on success (*changed: 0 when it held the save's bytes already, and nothing
   was written); after a failure before the commit point the newest save is as it was. what: a line for the log */
int sj_commit(SaveJournal *j, int *changed, char *what, size_t cap);

#endif
