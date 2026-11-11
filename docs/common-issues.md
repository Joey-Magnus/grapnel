# Common issues and answers

These answers are based on **closed GitHub issues** and their linked trackers, checked on 2026-11-10
(America/Vancouver). Most reports concern v2.0.14. Some were closed as duplicates of bugs that are still open.
Check the linked discussion for updates.

## Quick lookup

| Symptom | Answer status |
|---|---|
| [Build reports an incomplete compressed frame](#the-build-says-a-compressed-file-ends-before-its-frame-completes) | Maintainer diagnosis: incomplete input |
| [NVIDIA DLSS SDK download fails](#nvidias-dlss-sdk-could-not-be-downloaded) | Maintainer answer: retry or build without optional DLSS |
| [Builder stays at reading game files](#the-builder-stays-at-reading-game-files) | Open investigation; closed duplicate |
| [Game closes immediately after Play](#the-game-closes-immediately-after-play) | Open investigation; closed duplicate |
| [Gohma walks into a wall](#gohma-walks-into-a-wall-or-stops-attacking) | Maintainer workaround: game cap at 60 |
| [HUD ghosts with frame generation](#the-hud-ghosts-or-shimmers-with-frame-generation) | Workarounds; reports of recurrence |
| [FPS stays low after changing areas](#fps-stays-low-after-changing-areas) | Open investigation; restart may temporarily help |
| [Dungeon walls are invisible on an older GPU](#dungeon-walls-or-blocks-are-invisible-on-an-older-gpu) | Open mesh-fallback investigation |
| [Steam Deck freezes or loses geometry](#steam-deck-freezes-or-has-missing-dungeon-geometry) | Open Linux/Steam Deck tracker |
| [Controller layout does not match actions](#controller-buttons-do-not-match-the-selected-layout) | Open mapping investigation |
| [AMD textures look low resolution](#textures-look-low-resolution-or-corrupted-on-amd) | Open rendering tracker |

## The build says a compressed file ends before its frame completes

**Check that your game copy is complete.** In #1996, the maintainer traced this error to an incomplete `.nup`.
Copy or dump your own game again, then retry the build. If it still fails with a complete copy, include the builder
output in your report. File sizes can differ; the size mentioned in the issue applies to that particular dump.

Source: [maintainer response in closed #1996](https://github.com/NotRexed/Hookshot/issues/1996#issuecomment-6781832382).

## NVIDIA's DLSS SDK could not be downloaded

**Retry the download, or build without DLSS.** In #1962, the connection was reset during the download
(`WinError 10054`). Try again later or on another network. You can also untick NVIDIA DLSS in the builder to
continue without it. Report the problem if it fails every time.

Source: [maintainer response in closed #1962](https://github.com/NotRexed/Hookshot/issues/1962#issuecomment-6781832944).

## The builder stays at reading game files

**Unresolved.** #1988 was closed into #1876 for the v2.0.14 update/build stall. Add the
builder output, exact stage and version there. No fix was confirmed in the response.

Source: [maintainer response in closed #1988](https://github.com/NotRexed/Hookshot/issues/1988#issuecomment-6781829857).
Follow [#1876](https://github.com/NotRexed/Hookshot/issues/1876).

## The game closes immediately after Play

**Unresolved.** #2004 was closed as a duplicate of #1288. Add `hookshot_log.txt` and
your GPU details there, along with your OS, driver and exact build. No fix was confirmed in the response.

Source: [maintainer response in closed #2004](https://github.com/NotRexed/Hookshot/issues/2004#issuecomment-6783021365).
Follow [#1288](https://github.com/NotRexed/Hookshot/issues/1288).

## Gohma walks into a wall or stops attacking

**Workaround: set the game frame rate cap to 60.** The answer to #1927 connects this fight's behavior with a cap
above 60. Change **Game frame rate cap** in Hookshot's menu, save your progress and apply any requested restart.
This is the game's cap, not the displayed FPS after frame generation.

Some game timers do not advance correctly above 60 FPS. The underlying problem is still being investigated.

Sources: [maintainer response in closed #1927](https://github.com/NotRexed/Hookshot/issues/1927#issuecomment-6778842949),
[timer explanation in #1742](https://github.com/NotRexed/Hookshot/issues/1742#issuecomment-6781800673).

## The HUD ghosts or shimmers with frame generation

**Workaround: turn frame generation off while diagnosing it.** The maintainer traced a reported case to 2× frame
generation with frame pacing on. Turning pacing off or using 3× avoided that case; the response to #1976 also
suggests `RX_VK_FSR_FG=0` for the affected path.

Results vary. In #1953, restarting helped at first, but shimmering returned in new areas. That player had better
results with frame generation off. Test one setting at a time and check whether the problem returns after changing areas.

Sources: [maintainer response in closed #1976](https://github.com/NotRexed/Hookshot/issues/1976#issuecomment-6781826704),
[narrowed case in closed #1635](https://github.com/NotRexed/Hookshot/issues/1635#issuecomment-6778823477),
[reporter's follow-up in closed #1953](https://github.com/NotRexed/Hookshot/issues/1953#issuecomment-6780086181).

## FPS stays low after changing areas

**Status: unresolved; a restart may temporarily restore performance.** #2023 was closed into #1400. This is different
from a short stutter the first time a shader is needed. Record the areas and transitions that trigger it, compare
with frame generation off, and keep the log from the slow run before starting again.

The [performance-reporting instructions](../readme.md#low-fps-or-stutter) explain which GPU-time and memory lines
to include. Restarting may help temporarily; it does not fix the underlying problem.

Source: [maintainer response in closed #2023](https://github.com/NotRexed/Hookshot/issues/2023#issuecomment-6783024595).
Follow [#1400](https://github.com/NotRexed/Hookshot/issues/1400).

## Dungeon walls or blocks are invisible on an older GPU

**Known mesh-shader fallback problem.** The response to #1900 identifies the GTX 1050 Ti's lack
of mesh shaders and points to #1001, even with a correct dump. Include the GPU model and driver when reporting
missing geometry. No fix was confirmed in the response.

Source: [maintainer response in closed #1900](https://github.com/NotRexed/Hookshot/issues/1900#issuecomment-6778205354).
Follow [#1001](https://github.com/NotRexed/Hookshot/issues/1001).

## Steam Deck freezes or has missing dungeon geometry

**Unresolved.** The v2.0.14 Steam Deck OLED report #1956 was closed into
#1000. Workarounds depend on the hardware, driver and scene. Check that thread for current advice, and include
your SteamOS version, GPU, driver, affected area and last log lines when reporting the problem.

Source: [maintainer response in closed #1956](https://github.com/NotRexed/Hookshot/issues/1956#issuecomment-6780103592).
Follow [#1000](https://github.com/NotRexed/Hookshot/issues/1000). AMD-on-Windows freezes have their own
[tracker #996](https://github.com/NotRexed/Hookshot/issues/996), as the response to #1976 explains.

## Controller buttons do not match the selected layout

**Unresolved.** #1923 was closed into #1655 for play and ocarina controls disagreeing
with the selected Xbox/PC layout. Include the controller model, chosen Hookshot layout and bindings, the game's
own control settings, and which actions disagree. No fix was confirmed in the response.

Source: [maintainer response in closed #1923](https://github.com/NotRexed/Hookshot/issues/1923#issuecomment-6778840222).
Follow [#1655](https://github.com/NotRexed/Hookshot/issues/1655).

## Textures look low resolution or corrupted on AMD

**Unresolved.** The RX 9060 XT report #1986 was closed into #1006. Supply a
comparison, GPU/driver, upscaler and render resolution. The README's
[RGBA8 workaround](../readme.md#amd-texture-workaround) targets certain blocky or corrupted textures; it is not a
general cure for blurry rendering and can substantially increase VRAM use. Remove the switch to undo that test.

Source: [maintainer response in closed #1986](https://github.com/NotRexed/Hookshot/issues/1986#issuecomment-6781829223).
Follow [#1006](https://github.com/NotRexed/Hookshot/issues/1006).

## Keep the answers current

When updating this page, read the original response **and** the destination tracker. Preserve the affected build
and hardware context. Label a fix as released only when a release or maintainer response establishes that it is.
Link directly to the answer, paraphrase it, and do not copy users' logs, saves or attachments into these docs.
