# Common issues and answers

Answers below come from **responses in closed issues**, with active trackers checked alongside them on
2026-11-10 (America/Vancouver). A closed issue can mean duplicate, answered or moved; it does not by itself mean
fixed. These reports mainly concern v2.0.14. Check the linked thread and your version before applying an answer.

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

**Answer: check the input copy.** In #1996, the maintainer identified an incomplete `.nup`, not a renderer failure.
Make a fresh copy or dump from your own game, check it completed, and build again. If a complete copy still fails,
report that result with the builder output. The size in that report is specific to that user's file, not a universal
size requirement.

Source: [maintainer response in closed #1996](https://github.com/NotRexed/Hookshot/issues/1996#issuecomment-6781832382).

## NVIDIA's DLSS SDK could not be downloaded

**Answer: retry the download, or build without optional DLSS.** The response to #1962 identifies a connection reset
(`WinError 10054`). Retry later or on another network. Unticking NVIDIA DLSS lets the build proceed without that
optional component; it does not provide DLSS in the resulting build. Report it again if every attempt fails.

Source: [maintainer response in closed #1962](https://github.com/NotRexed/Hookshot/issues/1962#issuecomment-6781832944).

## The builder stays at reading game files

**Status: unresolved in the linked tracker.** #1988 was closed into #1876 for the v2.0.14 update/build stall. Add the
builder output, exact stage and version there. The closing response does not provide a confirmed fix, and this
symptom alone does not establish that your input is incomplete.

Source: [maintainer response in closed #1988](https://github.com/NotRexed/Hookshot/issues/1988#issuecomment-6781829857).
Follow [#1876](https://github.com/NotRexed/Hookshot/issues/1876).

## The game closes immediately after Play

**Status: unresolved in the linked tracker.** #2004 was closed as a duplicate of #1288. Add `hookshot_log.txt` and
your GPU details there; include your OS, driver and exact build. There is no universal repair in that response.

Source: [maintainer response in closed #2004](https://github.com/NotRexed/Hookshot/issues/2004#issuecomment-6783021365).
Follow [#1288](https://github.com/NotRexed/Hookshot/issues/1288).

## Gohma walks into a wall or stops attacking

**Workaround: set the game frame rate cap to 60.** The answer to #1927 connects this fight's behavior with a cap
above 60. Change **Game frame rate cap** in Hookshot's menu, save your progress and apply any requested restart.
This is the game's cap, not the displayed FPS after frame generation.

The active tracker explains that some timers truncate fractional frame steps; above-60 behavior remains under
investigation. Treat 60 as the workaround rather than a claim that every timing problem is fixed.

Sources: [maintainer response in closed #1927](https://github.com/NotRexed/Hookshot/issues/1927#issuecomment-6778842949),
[timer explanation in #1742](https://github.com/NotRexed/Hookshot/issues/1742#issuecomment-6781800673).

## The HUD ghosts or shimmers with frame generation

**Workaround: turn frame generation off while diagnosing it.** The maintainer traced a reported case to 2× frame
generation with frame pacing on. Turning pacing off or using 3× avoided that case; the response to #1976 also
suggests `RX_VK_FSR_FG=0` for the affected path.

These are not universal fixes. In #1953, the reporter initially saw improvement after a restart, then edited the
answer because shimmering returned in new areas. Disabling frame generation was their more consistent option.
Change one option at a time and report whether it stays clear after a scene transition.

Sources: [maintainer response in closed #1976](https://github.com/NotRexed/Hookshot/issues/1976#issuecomment-6781826704),
[narrowed case in closed #1635](https://github.com/NotRexed/Hookshot/issues/1635#issuecomment-6778823477),
[reporter's follow-up in closed #1953](https://github.com/NotRexed/Hookshot/issues/1953#issuecomment-6780086181).

## FPS stays low after changing areas

**Status: unresolved; a restart may temporarily restore performance.** #2023 was closed into #1400. This is different
from a short stutter the first time a shader is needed. Record the areas and transitions that trigger it, compare
with frame generation off, and keep the log from the slow run before starting again.

The [performance-reporting instructions](../readme.md#low-fps-or-stutter) explain which GPU-time and memory lines
are useful. A restart clearing the slowdown is diagnostic evidence, not a permanent fix.

Source: [maintainer response in closed #2023](https://github.com/NotRexed/Hookshot/issues/2023#issuecomment-6783024595).
Follow [#1400](https://github.com/NotRexed/Hookshot/issues/1400).

## Dungeon walls or blocks are invisible on an older GPU

**Status: known limitations in the mesh-shader fallback.** The response to #1900 identifies the GTX 1050 Ti's lack
of mesh shaders and points to #1001, even with a correct dump. Include the GPU model and driver when reporting
missing geometry. Rebuilding the same valid input is not a confirmed solution to this case.

Source: [maintainer response in closed #1900](https://github.com/NotRexed/Hookshot/issues/1900#issuecomment-6778205354).
Follow [#1001](https://github.com/NotRexed/Hookshot/issues/1001).

## Steam Deck freezes or has missing dungeon geometry

**Status: unresolved in the Linux/Steam Deck tracker.** The v2.0.14 Steam Deck OLED report #1956 was closed into
#1000. Follow the current tracker for hardware-specific tests and workarounds; an option that helps one scene or
driver is not established as a fix for every GPU timeout. Include SteamOS version, GPU/driver information, the
affected area and the last log lines.

Source: [maintainer response in closed #1956](https://github.com/NotRexed/Hookshot/issues/1956#issuecomment-6780103592).
Follow [#1000](https://github.com/NotRexed/Hookshot/issues/1000). AMD-on-Windows freezes have their own
[tracker #996](https://github.com/NotRexed/Hookshot/issues/996), as the response to #1976 explains.

## Controller buttons do not match the selected layout

**Status: unresolved in the mapping tracker.** #1923 was closed into #1655 for play and ocarina controls disagreeing
with the selected Xbox/PC layout. Include the controller model, chosen Hookshot layout and bindings, the game's
own control settings, and which actions disagree. The closing response does not confirm that changing layout
alone fixes it.

Source: [maintainer response in closed #1923](https://github.com/NotRexed/Hookshot/issues/1923#issuecomment-6778840222).
Follow [#1655](https://github.com/NotRexed/Hookshot/issues/1655).

## Textures look low resolution or corrupted on AMD

**Status: unresolved in the rendering tracker.** The RX 9060 XT report #1986 was closed into #1006. Supply a
comparison, GPU/driver, upscaler and render resolution. The README's
[RGBA8 workaround](../readme.md#amd-texture-workaround) targets certain blocky or corrupted textures; it is not a
general cure for blurry rendering and can substantially increase VRAM use. Remove the switch to undo that test.

Source: [maintainer response in closed #1986](https://github.com/NotRexed/Hookshot/issues/1986#issuecomment-6781829223).
Follow [#1006](https://github.com/NotRexed/Hookshot/issues/1006).

## Keep the answers current

When updating this page, read the original response **and** the destination tracker. Preserve the affected build
and hardware context. Label a fix as released only when a release or maintainer response establishes that it is.
Link directly to the answer, paraphrase it, and do not copy users' logs, saves or attachments into these docs.
