# Updates and saves

## Update an installation

Use **Update** in the launcher when a new release is offered. It downloads the changed parts and rebuilds in the
existing folder. Your saves, settings and mods are kept. Copy your saves somewhere safe before updating.

| Platform | Default save location |
|---|---|
| Windows | `user` inside the game folder |
| Linux | `~/.local/share/hookshot` |

On Linux, `XDG_DATA_HOME` can change that data location. A custom `--user` path also changes where the game keeps
saves. See the [save guide](saves.md#where-the-saves-are) for the complete paths.

An update can take about as long as the first build because temporary build files are normally removed after a
successful build. See [Updating](../readme.md#updating) and [Where the files go](../readme.md#where-the-files-go).

## Stable and development builds

Use [stable releases](https://github.com/NotRexed/Hookshot/releases/latest) for normal play.
[Nightly builds](https://github.com/NotRexed/Hookshot/releases/tag/nightly) include changes that have not reached
a stable release. Back up first and record the exact version in any report. The
[development-build instructions](../readme.md#latest-development-build) describe the required launcher arguments.

## Transfer saves

The [save transfer guide](saves.md) explains supported ports and emulators, discovery, backups and dry runs.
Close both programs before copying. The transfer tool copies files; it does not convert saves.

## Mods

Follow the [mods reference](../readme.md#mods) for folder structure and load order. A larger replacement file may
also need a matching resource-size table. Test without mods when diagnosing a problem, and name any mods you used
in a report. Do not attach their game-derived content.
