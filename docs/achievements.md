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
