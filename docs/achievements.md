# Hookshot-local Ocarina of Time achievements

Hookshot stores achievement progress on this PC, separately from the game's save slots. Progress is written beside
`hookshot_options.ini` as `hookshot_options.ini.achievements`; the versioned file keeps existing IDs when entries are added.
The menu is Insert → Gameplay → Achievements. It contains the 97 achievements in the Ocarina of Time N64 base set and
one Hookshot original, “Hey, Listen me!”. The list scrolls with Up/Down, Page Up/Page Down, Home, and End.

New unlocks show a four-second on-screen notification. If several unlock together, Hookshot displays them one at a time
in the order they were earned. They are also written to `hookshot_log.txt`.

The game-side polling currently unlocks achievements whose conditions are supported by observed pouch contents,
collectible counts, known songs, or the child/adult GameData flag. This covers the original slice and direct item or
count milestones. Entries that require boss damage/timing rules, minigame results, interaction history, a full run, or
other event-specific evidence are in the catalog but remain locked until Hookshot can observe those events. They are
not unlocked from a boss reward alone, since that would incorrectly award no-hit and restricted-equipment challenges.

Achievement IDs are the indexes in `gpu/vk/oot_achievements.h`. Keep existing IDs stable when adding or changing entries.

## Remaining trigger work

The catalog entries marked `OOT_ACH_MANUAL` need game-event tracking. Implement them in these layers:

1. Identify reliable signals in the running game for boss/minigame start and completion, damage, current hearts, fairy or
   healing use, item/equipment use, falls, score, and results. Use the existing GameData and bank-name readers in
   `host/hos_main.c`; verify each signal against gameplay before relying on it.
2. Add a per-player achievement tracker and tick it from `oot_update_player_cheats` every game frame. Start a boss or
   minigame record only on a confirmed entry signal, update its timer and constraint flags while it runs, and evaluate it
   only after a confirmed win/result signal. Reset the temporary record when the encounter ends or Link leaves.
3. Track session-only conditions, such as Gossip Stone visits, in session state. Persist full-run conditions separately
   per game save slot so they survive closing Hookshot without leaking between slots; clear them only when that save is
   replaced or a new run begins.
4. Give each manual catalog entry a specific trigger and parameters, then call
   `rx_option_set(HOS_OPT_ACHIEVEMENT_BASE + id, 1)` only after its exact condition passes. Keep item-only polling in
   `oot_inventory_refresh` and route all unlocks through the existing notification and local-save path.
5. Verify positive and negative cases for every tracker: for example, a clean boss win unlocks the no-hit entry, while
   taking a hit, healing, using a prohibited item, running out of time, or failing the minigame does not. Check that a
   save/load preserves run progress and that a different slot does not inherit it.
