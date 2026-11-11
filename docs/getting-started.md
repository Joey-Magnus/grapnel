# Getting started

Hookshot Builder creates a playable installation on your computer. Start with the
[latest stable release](https://github.com/NotRexed/Hookshot/releases/latest).

## Before you begin

**We do not host, store, or distribute any game files.** This site and repository contain no ROMs, game dumps, or
decryption keys. You must provide your own supported copy; Hookshot builds the game locally on your computer.

You need your own supported copy: program `0400486024DEC000`, update v131072, build `e0f3ccfa`, supplied as a `.nup`
or extracted `romfs` and `exefs` folders. The builder checks the version before building.

The current [requirements](../readme.md#what-you-need) recommend 16 GB RAM, 8 GB VRAM and about 60 GB free during the
build. Use an SSD if available. Windows 10/11 and 64-bit Linux are supported; the Linux AppImage needs glibc 2.35 or
newer and AVX2. Use a current Vulkan driver. GPUs with Vulkan 1.3 and mesh shaders are the main supported path;
older GPUs have [known fallback limitations](common-issues.md#dungeon-walls-or-blocks-are-invisible-on-an-older-gpu).

## Windows

1. Download `HookshotBuilder.exe` from the release page and run it.
2. Select your game from **Found on this PC**, use **Browse**, or choose the extracted-folder option.
3. Choose the installation folder and game language.
4. Select **Build the game**. The README estimates 10–45 minutes, depending on the machine.
5. Select **Play** when the builder finishes. Keep the shortcut for later launches and updates.

See the [full Windows instructions](../readme.md#on-windows) for the builder's choices.

## Linux and SteamOS

1. Download the release's `Hookshot-<version>-x86_64.AppImage`.
2. Make that downloaded file executable in your file manager's properties.
3. Open it, select your `.nup` or extracted folders, and choose the destination and language.
4. Select **Build**, then **Play** after the build completes.

The default destination is `~/Games/Hookshot`. Keep the AppImage in place: the launcher uses it for updates.
The [Linux instructions](../readme.md#on-linux) also link to command-line use.

## Your first launch

Shader preparation takes time on the first start. Let it complete before comparing performance. Press **F1** to open
Hookshot's menu, then visit [Graphics and controls](graphics-and-controls.md). Keep the game frame rate cap at 60
while getting started; higher caps can affect game logic.

If the builder stops or the game closes, use [Common issues and answers](common-issues.md). Keep your game files and
saves local; a bug report normally needs the version, hardware, reproduction steps and log.
