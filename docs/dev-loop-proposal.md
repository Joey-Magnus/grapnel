# Proposal: a faster development loop

Status: proposal, reviewed 2026-11-11 (the decisions below are settled); not started. §2 is meant to move into F1's
subsystem maps when they are written, and the proposal then keeps only the plan.

**Why.** Today, a one-line change to the renderer or the host means relinking a 426 MB exe. Then comes a cold start
and a walk back to the scene being worked on. Small slips cost much more: an `RX_VK_*` switch left in the shell, or one
failed build, and the next build translates the whole game again. This proposal makes the common edits cheap and
predictable, and makes the code easier to find your way around, for people and agents alike. It changes nothing
players build or run.

**Where the facts come from.** Everything in [§2](#2-how-it-works-today) was read from the source at `7297d93d`
(2026-11-11), partly by AI agents, and checked by hand where the plan depends on it. Nothing here was measured.
Timings are quoted from the PRs that measured them (#2324, #2518) and say so. Code is named by file and function, not
line, so the references survive edits.

---

## Decisions

Settled in review (#2636, 2026-11-11):

1. **What agents may read (F6): strict.** Agents never read `work/` or anything made from the game's files: lifted C,
   `functions.txt`, `image.bin`, a build's linker maps, dumps, captures with game data. That follows from
   CONTRIBUTING.md, and it is how [`scripts/cpu_categories.py`](../scripts/cpu_categories.py) already treats "a map of
   the game's code".
   - **The same answer covers a hand-written table of game-function addresses with names and meanings.** It is a map of
     the game's code, so it stays in a local file outside the repo, not in `docs/`. A local tool may read it with
     `--local`, and F4 is narrowed to that.
2. **The developer entry point is `nx2/dev.py`.** It imports make_game's profiles (`nx2/profiles.py`); `scripts/` is for standalone tools.
3. **Scenario files go in `tests/scenarios/`.** They are marked as needing the game, so `run_all.py` skips them in CI like the other game-only checks.
4. **Warnings and clang-tidy (E4) are advisory to start.** Once the baseline has settled, a PR of its own makes new findings in changed renderer files fail CI.
5. **No dev-only host split (C2) for now.** A no-op build on Linux, both links included, takes 18 s in a maintainer's setup. Decide only if Phase 0's Windows link times show the exe link is the bottleneck.
6. **The asynchronous update check (C3) goes ahead,** as its own player-facing PR with a worklist row, measured on a slow network.

Across all of it: anything shared or dev-only stays opt-in, and players' paths and the work-folder layout the Builders
use don't change.

---

## Contents

1. [Summary](#1-summary)
2. [How it works today](#2-how-it-works-today)
3. [Goals, non-goals and constraints](#3-goals-non-goals-and-constraints)
4. [Target design](#4-target-design)
5. [Workstream A: the build graph](#5-workstream-a-the-build-graph)
6. [Workstream B: renderer and shader reload](#6-workstream-b-renderer-and-shader-reload)
7. [Workstream C: host and game code](#7-workstream-c-host-and-game-code)
8. [Workstream D: testing](#8-workstream-d-testing)
9. [Workstream E: diagnostics and analysis](#9-workstream-e-diagnostics-and-analysis)
10. [Workstream F: documentation and code maps](#10-workstream-f-documentation-and-code-maps)
11. [Rollout](#11-rollout)
12. [Verification](#12-verification)
13. [Risks and open questions](#13-risks-and-open-questions)

---

## 1. Summary

Four loops, each with a target:

| Loop | Today | Target | Main levers |
|---|---|---|---|
| **Inner**: an edit, then the game-free checks that cover it | a full `tests/run_all.py` (about 488 checks), or picking checks by hand | only the checks that read the changed files | D1 `--changed`, D2 one source-cutting helper |
| **Middle**: a renderer edit, then the game at the scene being worked on | rebuild, relink both binaries, start cold, walk or script the way back | one command: rebuild the DLL, relaunch, arrive by script through the control bridge | A4 link skip, A6 depfiles, A9 `dev.py`, B1, B2 |
| **Outer**: a host or translator edit, then a running game | relink the 426 MB exe; a stray switch or a failed build relifts | no accidental relift; a host edit relinks only what it must | A2, A7, A4, C1, (C2) |
| **Finding**: a question about the code, then the file, the doc and the checks that guard it | grep, across about 638 switch names and 227 test files that cut source by text | one command (`dev.py where`) answering from maps that checks keep true | F1–F7 |

Six workstreams, each a series of small PRs ordered in [§11](#11-rollout):

- **A: the build graph.** An opt-in object store shared by every checkout and worktree. No unneeded relifts, links, rehashing or broad header rebuilds, and no full rebuild after a failed link.
- **B: renderer and shader reload.** A relaunch to a scripted scene, built on the control bridge, then shader overrides from disk. A live swap of the renderer DLL is designed but deferred.
- **C: host and game code.** Debug info and a console in dev builds, a shorter boot, and an optional dev-only host split.
- **D: testing.** Run only the checks a change affects, one shared source-cutting helper, a sanitizer lane, scenario files, and run summaries that can be compared.
- **E: diagnostics.** A list of every switch, a header on captures, memory counters, warnings and clang-tidy on our own code, and `compile_commands.json`.
- **F: documentation and code maps.** A docs index and subsystem maps, generated files that name their generator, a repo map for agents, the data boundary written down, and checks across `docs/`.

**What doesn't change:** the release profile `make_game.py` and the Builders use. Same flags, same layout, the single
exe, same performance. The few items that reach players say so, and are scored separately (below).

**How this scores.** [workflow.md](workflow.md) scores problems by severity × reach × confidence, with reach as a share
of *players' hardware*. Contributor tooling is S3 (polish, features) with no player reach, so as one row it would sit at
the bottom of the [worklist](worklist.md), and it shouldn't take that row from anyone. The case for it is throughput:
every row above it is fixed through this loop. The pieces that do reach players get their own worklist rows, scored
normally:

| Item | What players see | Suggested S | Reach | Confidence |
|---|---|---|---|---|
| A7 (remaining) | after a failed link, the next build translates and compiles everything again | S3 | the builds that fail at the link | 1.0 (read in the source) |
| C3 | the update check blocks start-up for up to about 3 s on a slow network | S3 | 1.0 (every start) | 1.0 (read; measure first) |
| A3 | the lift's emit runs in one process on Windows | S3 | Windows builds that relift (fewer since #2324) | 1.0 (read; #2324 measured a single-process emit of 56–84 s on Linux) |

---

## 2. How it works today

### 2.1 The build

The product build is custom Python, with no CMake, ninja or make. [`nx2/make_game.py`](../nx2/make_game.py) runs the
phases as subprocesses: read and unpack, then the lift (`nx2/lift.py`, `nx2/split_hot.py`), then compile and link
(`nx2/build.py`), then finish, then prepare shaders. The Builders parse its `@@stage`, `@@file`, `@@plan`, `@@eta` and
`@@times` lines.

**Compiling** ([`nx2/build.py`](../nx2/build.py)):

- **Objects are keyed by content.** `object_key` is a sha1 of the source, the normalised flags and a blob of headers. Objects are hard-linked from `<work>/objcache/<key>.o` when present (a home-grown ccache).
- **The cache belongs to one work folder** (`OBJ_CACHE`), although `flag_text` already makes the keys independent of the folder. A fresh worktree therefore starts from an empty cache.
- **Scheduling.** Longest jobs first, under a memory gate ([compiler-memory-accounting.md](compiler-memory-accounting.md)).
- **Flags:**

  | Code | Flags |
  |---|---|
  | Lifted chunks | `-O1 -g0` |
  | The eight hot pieces | `-O2` with the shipped PGO profile; [development.md](development.md#a-faster-build-for-development)'s `RX_HOT_OPT=O1` builds them like the rest |
  | Host | `-O2 -g0` |
  | Renderer | `-std=c++20 -O2 -g0 -DNDEBUG` |

  `-Wno-everything` on every target. No LTO, and no debug-info build; symbols come from the linker maps.
- **Where the time goes.** #2518 measured the hot pieces at about 1,270–1,810 s of a cold compile, against 2,820–3,750 s for all the other lifted files.
- **Header dependencies are blobs, not per-file:**
  - Lifted code depends on every header in `gen/` and `rt64/`.
  - Host code depends on those **plus every `host/*.h`**, plus `vk_api.h`, `dlss_math.h`, `compat/hookshot_env.h` and the FFmpeg and dav1d version headers.
  - The renderer depends on every header under `gpu/vk`, `gpu/render` and `gpu/compat`; eden and sirit get a narrower blob of their own.
- **No** depfiles, no `compile_commands.json` and no stat cache. The fingerprint and `migrate_stamps` read every lifted chunk on every run.

**Linking:**

- `hookshot.exe` is one static link of everything but the renderer: lifted code, the a64 runtime, generated tables, `host/*.c`, opus.
- `hookshot_vk.dll` is a separate shared link.
- **Both are relinked on every `build.py` run**, even when nothing was compiled. There is no link key.
- `RX_VK_ONLY=1` builds and links the DLL alone, with no lift, as CI does.

**The lift and its key** (`lift_key`, `lift_sources` in make_game.py):

- **Since #2324 the key hashes the modules the lift imports** (`lift_sources`, checked by [`tests/test_lift_cache.py`](../tests/test_lift_cache.py)). Editing `build.py`, `make_game.py` or an `nx2/test_*.py` no longer relifts.
- It still hashes every `.c/.h/.cpp/.hpp/.txt/.json` under `nx2/` and a64-kit, whether the lift reads it or not.
- It still hashes **every `A64_*`, `OOT_*` and `RX_*` variable** in the environment, except `COMPILE_ONLY_ENV = ("RX_HOT_OPT", "RX_PGO")` (#2518). So `RX_RELEASE`, or an `RX_VK_*` switch left set in the shell, still relifts.
- It also hashes **make_game's own environment, which carries paths**: `OOT_WORK`, `OOT_EXEFS`, `OOT_ROMFS`, `OOT_DUMP`. The exefs files' contents are hashed as well, so the paths add nothing but a difference: two checkouts of the same tree, or a moved work folder, never share a lift.
- **Updates keep the lift** (#2324, `keep_translation` / `kept_before`, `build.py --kept-lift`). An update with an unchanged key skips it; #2324 measured an update going from 100 s to 9 s.
- **The emit is single-process on Windows.** `emit_jobs` returns 1 where there is no `fork`. The per-file passes (`split_big`, the patches and edits) run as spawn workers since #2324 (`file_jobs`).

**After a failure** (`forget_failed_build`):

- **The lift key is always removed,** so the next build relifts after any failure, even a typo in a host file.
- **A compile failure keeps the finished objects.**
- **A link failure (or a later step) wipes `objcache` and `sa/build/obj`,** because of issues 1197 and 1176: a lifted file cut short, a stale runtime object linked in, and lifted C left by another builder.

### 2.2 What an edit costs today

For a development checkout with a kept work folder, run through `make_game.py`:

| Edit | What reruns | Why |
|---|---|---|
| One `gpu/vk/*.cpp` body | that object; **both** binaries relinked | no link key |
| One `gpu/vk/*.h` | every renderer `.cpp`; both relinked | the header blob |
| One `host/*.c` body | that object; both relinked | no link key |
| One `host/*.h` | every host object; both relinked | the header blob |
| An `imp_` / `HLE()` added or removed in `host/*.c` | **relift** | correct: the lift hooks them |
| An `nx2` `.py` the lift doesn't import (tests, `build.py`, `make_game.py`) | nothing extra (since #2324) | `lift_sources` |
| An `nx2` `.c/.h/.json/.txt` the lift doesn't read | **relift** | every data file is hashed |
| `RX_VK_*` or `RX_RELEASE` set or changed in the shell | **relift** | every `RX_*` but `RX_HOT_OPT`/`RX_PGO` is in the key |
| A generated runtime header (`a64_fpx.h`, `a64.h`) | **every lifted chunk** | correct: all include them |
| A compile error anywhere | the next build **relifts**; finished objects are kept | `forget_failed_build` always drops the key |
| A link failure | the next build **relifts and recompiles everything** | `forget_failed_build` with `linked` |
| `build.py` by hand with an environment unlike make_game's | host and renderer objects recompile; hot pieces lose the profile | `OOT_WORK`, `RX_PGO`, `RX_RELEASE` change keys |

### 2.3 The executable at run time

- **One exe holds the host and the game.** `hookshot.exe` links the lifted game and the host statically.
  - `image.bin` must match the lift exactly (`main` in `host/hos_main.c` checks its end).
  - Lifted code reaches guest memory through `A64_MEM` and the write-watch array `a64_dirty` directly.
  - `a64_lookup` caches 32-bit offsets from itself, so code more than 2 GB away (another DLL) is never cached.
- **The renderer DLL's boundary is clean but one-way.**
  - `load_vulkan` (`host/rx_backend.c`) loads `hookshot_vk.dll`, calls `mkwvk_init` and checks `MKWVK_API_VERSION`. It is 19 today: five bumps since 14, each of which invalidates players' `hookshot_programs.bin` once, because `vk_api.h` is in the shader stamp.
  - Every `rx_*` call goes through the renderer's table.
  - There is **no teardown**: no `vkDestroyDevice` in our renderer code, no export that stops its threads, no `FreeLibrary`. `mkwvk_close_asked` only stops preparation, saves the pipeline cache and closes DLSS frame generation.
- **The renderer owns state the host can't rebuild:**
  - the device, the swapchain and the VMA pools;
  - imported guest pools, with their VRAM mirrors and write-back shadows;
  - textures the GPU wrote, whose content is not in guest memory;
  - fence timelines whose values the guest has stored;
  - the registrations the host sent once.

  `rx_backend.c` keeps a journal of early calls, but only until the renderer starts.
- **Built-in shaders are compiled in** as 50 checked-in `gpu/vk/shaders/*_spv.h` headers. They carry only glslang's version line (`movie_upscale_comp_spv.h` not even that). The four `host_shaders` headers carry a provenance banner. There is no load-from-disk override on the Vulkan side; the WebGPU renderer has `RX_WGSL_OVERRIDE`.
- **No save states.** Guest call chains live on host C stacks, 64 MB per guest thread, so a memory snapshot could not resume.
- **Getting to a scene: the control bridge** ([control.md](control.md), #926).
  - `HOS_CONTROL` opens a local socket. `scripts/hookshot_ctl.py` (standard library only) uses it to launch a game folder into a run folder of its own, press and sequence inputs timed in frames, wait for `in_play` or a map, teleport, take screenshots, list saves and slots, set options and quit.
  - The older `HOS_INPUT_LIVE` file still takes `!` commands (`!cheat`, `!shots` and others). Neither has a relaunch.
  - Relaunch itself exists (`host/hos_relaunch.c`, the Insert menu's Restart): it restarts the process with the same command line and environment.
- **Start-up costs a dev run can skip:**
  - the synchronous update check (`hos_update_check`, a timeout of about 2.5–3 s; `HOOKSHOT_NO_UPDATE_CHECK=1` skips it);
  - start-up shader preparation (`RX_VK_PRECOMPILE=0`);
  - a cold program cache. Any edit to the translator files in the shader stamp invalidates it whole.

### 2.4 Tests and CI

- [`tests/run_all.py`](../tests/run_all.py) runs about 488 checks, each in its own process:
  - 457 `tests/test_*.py`
  - 26 `nx2/test_*.py`
  - 4 C++ unit tests
  - a byte-compile of every tracked Python file

  Tests declare `RUN_ALL_ARGS` / `RUN_ALL_SKIP` / `RUN_ALL_MODULES`, which the runner reads with `ast`.
- **CI** (#2124) shards Linux and Windows, uses ccache and a Windows renderer object cache, keeps `tests/run_all_times.json` for both, and skips builds on docs-only PRs. There is no `--changed` mode.
- **Tests read the source.** 227 test files define a function that cuts text out of a source file. `def block(` alone is in 165 of them, in several variants, and there is no shared helper.
  - `vk_replay.cpp` is named by 64 tests, and `vk_menu.cpp` by 48. AGENTS.md says 17; it predates most of them.
- **Sanitizers are offered but unused.** 11 tests accept `--sanitize`; nothing in CI or `run_all.py` passes it.
- **No** `.clang-format`, `.clang-tidy`, ruff or pre-commit.
- **Switches:**
  - About 638 distinct names, outside eden and sirit, read through `getenv(` (182 in host, 521 in `gpu/vk`), `env_on(` (309) and `env_int(` (9).
  - #2042 brought in `env_on`/`env_int` (`gpu/vk/compat/hookshot_env.h`), with `test_env_on.py` and `test_program_stamp_knobs.py` checking parts.
  - There is no central list.

### 2.5 How the code is documented today

- **Entry points:**
  - [AGENTS.md](../AGENTS.md) for agents;
  - [CONTRIBUTING.md](../CONTRIBUTING.md) for everyone;
  - [development.md](development.md) for commands and switches;
  - [design.md](design.md) for the architecture and the replay's rules;
  - [workflow.md](workflow.md) and [worklist.md](worklist.md) for what to work on.
- **About 45 topic notes in `docs/`,** most paired with a test, and no index.
- **[cpu-profile.md](cpu-profile.md) already has generated sections between markers** (`<!-- MEASURED:... -->`), a precedent for generated docs.
- **Profiles are already named.** `scripts/cpu_report.py` names Hookshot's own functions from the linker maps and `scripts/cpu_functions.json`. Game code is passed in with `--guest-map` and kept local.
- **Most source files open with a comment saying what they are,** and every `scripts/*.py` opens with a docstring. Nothing checks either.
- **Generated files don't all say where they come from** (§2.3). AGENTS.md says the shaders' tests show the regenerate command, so the commands are spread across tests.
- **The local layer.** `work/` (lifted C, `functions.txt`, `image.bin`, a build's linker maps, runs) is made from the game and never leaves the PC. AGENTS.md's new "Team updates" section keeps `work/` content out of chat posts, but nothing yet says what an agent may *read*. For an agent, reading a file sends it to the model's provider.

### 2.6 Where the loop loses time

In rough order of how often it bites:

1. **Links are never skipped.** Every build relinks the 426 MB exe and the DLL.
2. **Any failure relifts.** A link failure also recompiles everything.
3. **Accidental relifts** from `RX_*` variables in the shell, and from `nx2` data files the lift doesn't read.
4. **Broad header blobs.** One `host/*.h` rebuilds the host; one `gpu/vk` header rebuilds the renderer.
5. **Environment drift** when `build.py` is run by hand.
6. **Cold starts.** Every renderer test pays for boot, preparation and getting to the scene; the bridge scripts the last part.
7. **Choosing checks by hand,** or waiting for all of them.
8. **Finding things:** which tests cut a function, what a switch does, what a header is generated from.
9. **No debugger-friendly build.**
10. **Rehashing** 1.4 GB of lifted C, and the single-process emit on Windows when a relift does happen.

**Not measured:** each link's time, the hashing cost, and boot to a scene with the control bridge. Phase 0
([§11](#11-rollout)) measures them, and the order of A3, A5 and C2 depends on the numbers.

---

## 3. Goals, non-goals and constraints

**Goals**

- **G1.** A renderer `.cpp` edit reaches a running game at a chosen scene with one command, with no unrelated compile and no unneeded link.
- **G2.** The build is predictable. The same sources and the same profile give the same keys, and `dev.py status` names the reason for every rebuild and relift.
- **G3.** A host `.c` edit doesn't rebuild the rest of the host, and doesn't relink what it needn't.
- **G4.** The inner loop runs only the checks that read what changed. The full run is still required before a PR ([workflow.md](workflow.md), step 4).
- **G5.** Every diagnostic has one shape: a listed switch, a capture with a header, a reader, a check and a doc row.
- **G6.** The code answers questions about itself. From a file, a function, a switch or a header, one command gives its definition, its docs, the checks that read it and what it is generated from. Every map behind that is generated or checked.

**Non-goals**

- **No change to what the release profile produces.**
- **No new build system.** The Python build already has content keys, a memory gate, a kept lift and output the Builders parse; we extend it.
- **No save states.** Lifted code runs on host stacks. The control bridge's scripted arrival covers the need.
- **No hot reload of lifted code.** An edit to it is a translator edit, which is the outer loop.
- **No renaming in the code or the build.** No names are written into lifted C, and no link-time aliases: a doc edit must never trigger a rebuild.

**Constraints**

- **No game data leaves the PC.** That covers everything under `work/`: lifted C, objects, `image.bin`, dumps, program caches and captures. Scenario files and the switch list are text that names nothing beyond what the source already names.
- **Two platforms:** Windows (llvm-mingw and the MSVC-target route) and Linux (clang/gcc). Paths are UTF-8.
- **Tooling uses only the standard library,** apart from the pipeline's existing dependencies (CONTRIBUTING.md). Run it with `python -I`.
- **Hardware tiers** ([workflow.md](workflow.md)): no Tier 1 regression; runtime changes are tested on Tier 1 before merge.
- **Renderer interface changes bump `MKWVK_API_VERSION`,** and each bump invalidates players' program caches once. Batch any such change into one bump.
- **Tests read the source:** a refactor updates the checks that cut the code it reshapes, in the same PR.
- **The Builders parse `make_game.py`'s `@@` lines,** which keep their format.

---

## 4. Target design

### 4.1 Build profiles

| | `release` (unchanged) | `dev` |
|---|---|---|
| Who | the Builders, `make_game.py`, CI release jobs | contributors, through `dev.py` |
| Lifted chunks | `-O1 -g0` | **the same**, so `objcache` entries are shared |
| Hot pieces | `-O2` + the shipped profile | the same by default. `RX_HOT_OPT=O1` stays an opt-in for faster cold builds, with objects of its own |
| Host | `-O2 -g0`, no console | `-O2 -g1`, console, warnings ([E4](#e4-warnings-and-clang-tidy-on-our-own-code-m)) |
| Renderer | `-O2 -g0 -DNDEBUG -DHOOKSHOT_RELEASE` | `-O2 -g1`, no `HOOKSHOT_RELEASE` (no start-up preparation), warnings |
| Links | skipped when their inputs are unchanged ([A4](#a4-skip-links-whose-inputs-are-unchanged-s)) | the same |
| Failure | [A7](#a7-no-relift-after-a-failure-that-isnt-the-lifts-s-reaches-players)'s narrower handling | the same; `dev.py status` names the failing object |

- **Dev and release share the lifted objects.** They are most of the compile time, and the cache is content-keyed, so switching profiles costs only the host and renderer objects.
- **That needs the lift key to stop hashing `RX_RELEASE`.** [A2](#a2-a-lift-key-that-hashes-only-what-changes-the-lifted-c-m) does that.
- **A profile is named in one place,** `nx2/profiles.py`, imported by `make_game.py`, `build.py` and `dev.py`.

### 4.2 One entry point: `nx2/dev.py`

```
python -I nx2/dev.py status                      # what is stale and why: lift key parts, objects, links
python -I nx2/dev.py build [renderer|host|all]   # dev profile
python -I nx2/dev.py run <scenario> [--watch]    # build what is stale, launch through hookshot_ctl, play the scenario
python -I nx2/dev.py test [--changed|--all]      # run_all.py; --changed by default
python -I nx2/dev.py shaders [--check|--watch]   # wraps host_shaders.py and fsr3_shaders.py
python -I nx2/dev.py compdb                      # compile_commands.json (A8)
python -I nx2/dev.py times [--compare <run>]     # per-phase build times (A1)
python -I nx2/dev.py where <thing>               # definition, docs, tests that cut it, switches, includers (F5)
python -I nx2/dev.py docs [--check]              # fill generated doc sections; check links and references (F1, F3, F7)
```

Design rules:

- **Thin.** The work stays in `lift.py`, `build.py`, `hookshot_ctl.py` and the scripts, which keep their own command lines.
- **`status` comes first:** every "why did this rebuild?" gets an answer.
- **Standard library only,** on both platforms.

### 4.3 Module layout

Today, and in release always:

```
hookshot.exe    = lifted game + a64 runtime + generated tables + host/*.c + opus [+ WebGPU]   (426 MB, static)
hookshot_vk.dll = renderer (gpu/vk + eden + sirit + imgui + zstd)                            (loaded once)
```

Optionally in dev, only if Phase 0 shows the exe link dominates host edits ([C2](#c2-a-dev-only-split-of-the-host-l-gated)):

```
hookshot.exe      = lifted game + a64 runtime + generated tables + the host's hot paths
hookshot_host.dll = the host's cold subsystems (menus, saves, fs, audio, display, update, mods, input)
hookshot_vk.dll   = renderer (unchanged)
```

### 4.4 The middle loop, end to end

1. `python -I nx2/dev.py run kokiri-day --watch`
2. `dev.py` builds what is stale. A `vk_draw.cpp` edit compiles one object and links only the DLL.
3. It launches the game folder through `hookshot_ctl.py launch` with the scenario's environment file:
   - the update check off;
   - start-up preparation off;
   - the program cache warm.

   It then plays the scenario through the bridge: wait for `in_play`, load the slot, teleport, wait for the map.
4. When a watched file changes, it builds the DLL under a staging name and sends the bridge a `relaunch`. The game restarts through its existing relaunch path, loads the new DLL, and the scenario plays again.
5. The run's summary (fps, frame times, counters, screenshots) goes to `work/runs/<scenario>/<n>/`, and is compared with the last run's.

---

## 5. Workstream A: the build graph

Sizes: S under a day, M a few days, L a week or more.

### A1. Per-phase timing (S): first

- **What:** `record_times` already stores per-module seconds and the compile and total seconds, and `lift.py` prints its steps through `took()`. Add the remaining phases to `build_times.json`:
  - read and unpack;
  - the lift's steps (image, discovery, emit, the per-file passes, split_hot);
  - planning and hashing;
  - each link on its own;
  - finish;
  - prepare shaders.

  End the build with one table. `dev.py times --compare` puts two runs side by side.
- **Safety:** the `@@times` line keeps its format; new fields are added beside it, and the Builders ignore unknown ones (checked).
- **Test:** game-free: the timings file has the new fields; `Runner.cs`'s parser accepts a file with extra keys.

### A2. A lift key that hashes only what changes the lifted C (M)

- **Files: mostly done (#2324).** `lift_sources` hashes the imported modules, and `test_lift_cache.py` checks the import walk. What's left: the `nx2` and a64-kit `.c/.h/.json/.txt` files the lift never reads are still hashed. Narrow that list to the files the imported modules open, found the same way.
- **Environment:** replace "every `A64_*`, `OOT_*` and `RX_*` variable but `COMPILE_ONLY_ENV`" with `LIFT_ENV`, an allow-list of the variables **whose values change the lifted C**, e.g. `A64_HOT_CHUNK` and `A64_HOT_FUNCS`.
  - **Path-valued inputs are hashed by what they point to, never by the path.** The exefs files' contents already are, and the hot list and the chunk boundaries are. So `OOT_WORK`, `OOT_EXEFS`, `OOT_ROMFS` and `OOT_DUMP` leave the key, and two checkouts of one tree share a lift. In a maintainer's setup, a lift keyed without the paths gave byte-identical lifted C across folders.
  - **The check:** a test greps `os.environ` / `getenv` across `lift_sources()` and fails on a name it reads that isn't in `LIFT_ENV` and isn't a path whose target is hashed. It is the inverse of `test_lift_cache.py`'s existing check that lift sources don't read `COMPILE_ONLY_ENV`.
- **Open point:** does the lift read `RX_RELEASE`? make_game puts it in the lift's environment. If the lift doesn't read it, it leaves the key, and dev and release share a lift.
- **Then, optional: a lift snapshot shared across work folders.** A finished lift is snapshotted under its path-free key (reflinks where the file system has them, hard links or copies otherwise). A new work folder with the same key takes the snapshot, and `make_game` skips the lift. Same opt-in rule as [A10](#a10-an-opt-in-object-store-shared-across-work-folders-m).
- **Payoff:** `RX_VK_*` switches in the shell, moving between profiles, or a new checkout of the same tree stop relifting.

### A3. A parallel emit on Windows (M–L; reaches players; gated)

- **What:** `emit_jobs` returns 1 where there is no `fork`. Give the emit spawn workers like `file_jobs`'s: each maps `image.bin` read-only, loads `functions.json` and the chunk plan, and receives its chunk list.
- **Why safe:** same boundaries (`chunks.txt`), same emitter. **Test:** byte-for-byte lifted C from one process and from N, compared locally. A game-free test of the worker protocol on a synthetic image.
- **Gate:** since #2324 updates with an unchanged key skip the lift, so this helps only builds that relift. Phase 0 measures the Windows emit (#2324 measured 56–84 s single-process on Linux).

### A4. Skip links whose inputs are unchanged (S)

- **What:** a key per link, written beside the output (`hookshot.exe.linkkey`):
  - the ordered object keys (the `.o.sha1` stamps exist);
  - the normalised link line, using `linker()`'s;
  - the libraries' sizes and mtimes.

  Skip the link when the key matches and the output exists with its recorded size. The exe and the DLL have separate keys.
- **Test:** game-free: a synthetic object set. No change: skipped. One object changed: relinked. A flag changed: relinked. Output deleted: relinked.
- **Payoff:** a fixed cost off every build. **A data point:** in a maintainer's Linux setup, a whole build with nothing to compile took 18 s, both links included, so lld links the exe in seconds there. A4 is still worth doing (it's S). Windows' link time is the number to measure in Phase 0.

### A5. A stat cache in front of content hashing (S–M; gated)

- **What:** a manifest of path → (size, mtime_ns, file id, sha1); rehash only on a stat change. Anything written within 2 s of the manifest is always rehashed (git's "racy" rule). Used by `plan_jobs`, the fingerprint and `migrate_stamps`.
- **Gate:** A1 measures the hashing first. If it is a few seconds, this waits.

### A6. Header dependencies from depfiles (M)

- **What:** host, renderer, opus and runtime objects compile with `-MD -MF <obj>.d`. Their key covers the headers in the last compile's depfile; with no depfile it uses today's blob, so the first build is as conservative as today. Lifted chunks keep their blob: every chunk includes the runtime headers.
- **Why safe:** the depfile is clang's record of what it read. A newly added `#include` changes the source, so the key changes anyway.
- **Test:** game-free: two sources, two headers. Edit one header and check only its includer recompiles.
- **Payoff:** a `host/hos.h` edit rebuilds its includers, not the whole host; likewise one renderer header. **Seen in practice:** one `gpu/vk` header edit plus one `.cpp` rebuilt 16 renderer objects in a maintainer's setup, because of the blob.

### A7. No relift after a failure that isn't the lift's (S; reaches players)

- **Done (on main):** a compile failure keeps the finished objects (`forget_failed_build`).
- **Left:**
  1. **Keep the lift key when the failure is a compile error in a tracked source** (`host/`, `gpu/`, `third_party/`). The lift is not suspect, so a typo in a host file shouldn't relift.
  2. **Classify link failures.** Undefined `f_*` / `a64_*` symbols, or an error in a generated file (`sa/gen`, `rt64`), keep today's wipe; those are the 1197 and 1176 causes. Any other link failure keeps the caches. Unknown failures keep today's behaviour.
- **Also:** find why issue 1197's stale runtime object kept its key. A generated input missing from that object's dependencies is the likely gap, and A6's depfiles would cover it.
- **Test:** game-free: the classifier on recorded failure texts (a host compile error, an undefined `f_7100001234`, a truncated generated file).

### A8. `compile_commands.json` (S)

- **What:** `build.py` already holds each command as `(cc, src, obj, fl, deps)`. Write them to `<work>/sa/build/compile_commands.json`; `dev.py compdb` links it to the repo root (git-ignored).
- **Caveat:** host and lifted entries need a lift (`sa/gen`, `rt64`); renderer entries don't.
- **For:** clangd, and clang-tidy (E4).

### A9. Profiles in one place, and `nx2/dev.py` (M)

- **What:** move the environment make_game builds for the lift and the compile into `nx2/profiles.py`, which `make_game.py` imports. Then `dev.py` with `status`, `build` and `times`.
- **Test:** game-free: the `release` profile's environment equals what `make_game.py` built before the change, for fixed inputs.

### A10. An opt-in object store shared across work folders (M)

The biggest single lever for the worktree-per-PR workflow that people and agents use. It changes nothing for players.

- **What:** one content-addressed object store shared by every checkout and worktree, behind a switch such as `HOOKSHOT_OBJ_STORE=<folder>`. Unset, `OBJ_CACHE` stays `<work>/objcache`, as today. The objects' names are already independent of the folder (`object_key` over `flag_text`), so every workspace produces the same names.
- **No races:** each build gets a private object folder, hard-linked from the store before it starts. Its new objects are linked back into the store atomically as they finish, every few seconds. Two builds at once never write the same entry.
- **Two catches, from a maintainer's setup:**
  - **Seed the git-ignored inputs.** `hot_funcs.txt`, `hot_order.txt` and `image/chunks.txt` must reach a new checkout's work folder. `make_game.py` copies them from `ROOT/work`, which is empty in a fresh worktree, and without them the chunk boundaries differ, and so does every lifted object's name.
  - **The PGO profile's path ends up in the hot pieces' keys,** so the profile has to sit at a content-addressed path to be shared.
- **Measured** (a maintainer's setup, Linux, `main`, 22 jobs):

  | Build | Time |
  |---|---|
  | A fresh worktree, cold store (renderer 81 s, lift 107 s, compile 515 s) | ~720 s |
  | The same `main` in a second fresh worktree, warm store (0 of 258 files compiled, the lift reused, both links) | **18 s** |
  | One `gpu/vk` header and one `.cpp` changed (16 renderer objects, because of the header blob) | 26 s |

  The outputs were byte-identical either way.
- **Who:** hckrman101 offered to upstream their wrapper as an opt-in on `build.py` / `make_game.py`, in a PR of its own.
- **Test:** game-free: two work folders over one store build the same synthetic sources. The second compiles nothing, and its objects are links to the first's. A build killed mid-link-back leaves no partial entry.

---

## 6. Workstream B: renderer and shader reload

B1 and B2 are the plan. B3 is designed here so that it can be decided on facts, but it is deferred.

### B1. Relaunch to a scene, on the control bridge (M)

The bridge already does the hard part: launch, wait for `in_play` or a map, teleport, screenshots, saves. B1 adds:

1. **A `relaunch` command** in the bridge (`host/control.c`) and in `hookshot_ctl.py`. It takes the Restart path the Insert menu uses, and the client reconnects to the new process.
2. **A staged DLL swap, dev only** (`HOS_DEV_DLL_SWAP`). `dev.py` builds `hookshot_vk.dll.new`. At start-up, before `load_vulkan`, the host renames it over the old DLL. The existing `HOS_RESTART_OF` wait already orders that after the old process has exited. Release never looks for `.new`.
   - **Check the symbols before the rename, not just `MKWVK_API_VERSION`.** On Linux the renderer `.so` also resolves symbols from the exe, and it is opened with `RTLD_NOW`. A `.so` and an exe built from different trees therefore fail at `dlopen`, before `mkwvk_init`'s version check runs, and to the user the game just never opens a window.
     - `dev.py` checks that every undefined, non-runtime symbol of the `.new` file, as `nm -D --undefined-only` lists it, is one the running exe exports. This is the pairing check that `build.py`'s `check_vk_symbols` can't make at build time. If one is missing, it keeps the old DLL and names the symbol.
     - Windows gets the equivalent over the DLL's imports from the exe, where there are any.
   - **Name the missing symbol when loading fails.** The POSIX `LoadLibraryA` shim (`host/posix/win32_posix.c`) records `ERROR_FILE_NOT_FOUND` for any `dlopen` failure and drops `dlerror()`'s text. It should keep that text, and `load_vulkan`'s failure line should print it.
3. **A dev environment file** (C3): the update check off, preparation off, audio off, optionally headless.
4. **Measure it.** Phase 0 times save → scene on a Tier 1 PC with a warm cache. If it is fast enough, B3 stays shelved.

**Tests:**

- `tests/test_control.py`'s fake game gets the `relaunch` command, and `test_hookshot_ctl.py` gets the client side.
- A check that the `.new` swap only happens under its switch.
- The symbol check refuses a fixture `.so` that names a symbol the fixture exe doesn't export.
- The full loop is run in the game locally and reported.

### B2. Built-in shaders from disk (S–M)

- **What:** with `RX_VK_SHADER_DIR=<folder>` set, each built-in shader is taken from `<folder>/<NAME>.spv` when that file exists, and the log names it; this mirrors `RX_WGSL_OVERRIDE`. One lookup function serves every `*_SPV` use: `vk_draw`, `vk_framegen`, `vk_fsr3`, `vk_fsr3fi`, `vk_fsr3_inputs`, `vk_memory`, `vk_reactive`, `vk_temporal` and `vk_texture`.
  - `dev.py shaders --watch` recompiles the changed shader into that folder, and B1's relaunch picks it up without a DLL build.
- **Later:** rebuild those pipelines live at a frame boundary on a bridge command. Built-in shaders don't depend on guest state, so this is far easier than B3.
- **Test:** game-free: the lookup returns the compiled-in words when the folder is unset or the file is missing, and the file's words when it is valid (the magic number, a size that is a multiple of 4, `spirv-val`).
- **The shipped headers are still generated** from the sources; the override is for iteration only.

### B3. A live renderer swap (L, deferred)

What a swap mid-run would need:

1. **A teardown export, `mkwvk_shutdown`.** It would:
   - drain the recorder and the replay, and finish all work;
   - write textures the GPU wrote back to guest memory, or accept a glitched frame;
   - release every guest import (the host's `FreeMemoryPages` checks them);
   - destroy the device and the instance;
   - join every renderer thread.

   None of this exists today.
2. **A lifetime journal of registrations** in `rx_backend.c`, replayed into the new renderer.
3. **Fence continuity:** the new timeline starts above the old one's last value. That needs a new `MkwVkHost` field, so an API bump.
4. **Loading from a shadow copy,** then `FreeLibrary`.

**Recommendation:** don't start B3 until B1 has been used for weeks and someone has written down why it isn't enough.
If it is started, the teardown export goes first, on its own; it also gives a clean exit and helps tests.

---

## 7. Workstream C: host and game code

### C1. Debug info and a console in dev (S)

- **What:** host and renderer objects get `-g1` in the dev profile; lifted chunks stay `-g0`. On Windows, CodeView and a PDB (`-gcodeview`, `-Wl,--pdb=`); on Linux, DWARF.
- **Test:** a game-free check of the dev profile's flags.

### C2. A dev-only split of the host (L, gated)

**Not now (decision 5).** It is kept here only in case Phase 0's Windows link times show the exe link dominates host
edits even after A4. On Linux, a no-op build with both links takes 18 s, which says it won't be needed there.

- **Must stay in the exe**, because lifted code reaches it directly:
  - `A64_MEM`, `a64_dirty` and the a64 runtime;
  - the HLE functions the lift hooks;
  - the virtual-core polls;
  - `call_guest`;
  - the submission path in `nvn_native.c`.
- **Can move** to `hookshot_host.dll` behind a small versioned table, as `MkwVkHost` is: the menus, saves, the file system, mods, update, Discord, audio, display, input and prompts.
- **A check** fails when a moved file defines a symbol that lifted code or the runtime references.
- **Costs:**
  - **Dev and release perform differently,** so numbers for PRs and `tested-configurations.md` come from release builds, and the run summary names the profile.
  - **One more interface** to keep in step.
- **Try first:** whether lld's `--threads`, or dev-only link options, make the monolithic link fast enough.

### C3. A shorter boot (S)

- **What:** a dev environment template, `docs/dev_env.txt.example`, passed by `dev.py run` through `HOS_ENV_FILE`. It turns off the update check and start-up preparation, keeps audio muted, and optionally runs headless.
- **Separately, and for players (decision 6: agreed):** make the update check asynchronous. It is a blocking network call at start-up, with a timeout of about 2.5–3 s. It gets its own PR and its own worklist row, measured on a slow network.

### C4. Lifted code (reference)

Lifted code changes only when the translator, the hot list, the chunk boundaries or the runtime headers change. #2324
already made that path faster: the kept lift, kept hot pieces and parallel per-file passes. A2, A3 and A6 take it
further. `nx2/test_leaf.py` and `test_insn.py` already check the translator without building the game.

---

## 8. Workstream D: testing

### D1. `run_all.py --changed` (S–M)

- **What:** map the changed files to the checks that read them.
  - Changed files come from `git diff --name-only` against the merge base with `main`, plus untracked files.
  - The map comes from scanning each test for path literals and file names. Tests already name the files they cut from.
  - An optional `RUN_ALL_READS = (...)` declaration covers what the scan can't see; it is read by `ast` like the others.
- **Always included:** the byte-compile check, changed tests themselves, and everything when `run_all.py`, `build.py` or a shared fixture changed.
- **Not a replacement for the full run** before a PR; `--changed` prints that reminder.
- **Test:** a fixture tree of fake tests, and the selection for a few diffs.

### D2. One source-cutting helper (M, gradual)

- **What:** `tests/srccut.py` (standard library), with `block`, `function` and `between`. It handles braces inside strings, character literals and comments, and preprocessor lines. A marker that is missing, or appears twice, gives one clear error naming the file and the marker.
- **Migration:** grouped by source file, all the `vk_menu.cpp` readers together. A script checks that every migrated test cuts exactly the same text as before.
- **Why:** this is the trap AGENTS.md warns about. One helper gives one failure message, and one place to improve.

### D3. A sanitizer lane (S)

- **What:** a Linux CI job running the checks that offer `--sanitize`, with it on. A `RUN_ALL_SANITIZE = True` declaration replaces a hand-kept list. Locally: `dev.py test --sanitize`.
- **Later:** a dev-profile ASan build of the renderer for in-game runs. That needs sanitizer runtimes in the Linux toolchain (`scripts/linux/deps.sh` builds LLVM without them).

### D4. Scenario files on the control bridge (M)

- **What:** text files in `tests/scenarios/` (decision 3), marked as needing the game so `run_all.py` skips them in CI. Each names:
  - an environment (merged over C3's template);
  - a `hookshot_ctl` sequence: wait, load a slot, teleport, wait for the map, presses;
  - a duration;
  - captures: screenshots at given frames, `RX_VK_FRAME_LOG`, `HOS_PRESENT_TRACE`, E3's counters;
  - optional log assertions.

  `dev.py run <scenario>` plays one, on Windows and Linux, replacing ad hoc `run-vk.ps1` runs.
- **A fresh copy of a clean save for every run,** in the scenario's own local user folder, so no run starts from what the last one left.
- **In-session A/B as a first-class option** (`ab: <switch> every <seconds>`). One game session flips a switch through a file every N seconds, and the results are reported per half. Both halves then see the same scenes and the same load.
  - **Why not compare separate runs:** in a maintainer's measurements of a flicker-type metric, counts varied 5–20x between sessions of the same build. In-session A/B was the only comparison that held up.
  - This needs the switch to be read live (from a file) rather than once at start-up. Each switch that takes part says so in E1's list.
- **A starting set:** title to gameplay (boot time), Kokiri Forest by day, Hyrule Field by night, the Castle Town flower field (the regmap regression), and a walk through the menus.
- **Data:** results stay in `work/runs/`. Screenshots may go in PRs, as today; dumps and probes stay local.

### D5. Run summaries that can be compared (S–M)

- **What:** each scenario run writes `summary.json`:
  - the build (git hash, profile, API version) and the PC (GPU, driver, OS);
  - fps, and frame times at p50, p95 and p99;
  - the counters;
  - the assertion results.

  A `tested-configurations.md` row comes from a summary. `scripts/cpu_report.py` and `chain.py` stay the tools for CPU questions; the summary links to their output where a run made it.
- **Comparisons:**
  - **The halves of an in-session A/B (D4) are the comparison to trust.**
  - **`dev.py run --compare <run>` across sessions also reports each metric's spread,** so a difference inside the noise is shown as such.
- **A sanity metric beside every target metric.** The default is mean luma: in a maintainer's runs, it caught a "fix" whose 0 flashes came from a blown-out exposure. A summary shows the target metric, its spread, and the sanity metric together.
- **Test:** game-free: a synthetic frame-log fixture gives a known summary, and an A/B fixture gives known per-half results.

### D6. Timing runs never share the machine with a build (S)

- **What:** fps and frame-time numbers taken beside a compile are worthless, and `dev.py run --watch` rebuilds on save, so this would happen by default. `dev.py` takes a lock in `work/`:
  - builds and plain runs share it;
  - a timing run, meaning any scenario with captures or A/B, takes it exclusively;
  - a build started during a timing run waits, and a timing run waits for builds.

  The summary records whether the run held the lock exclusively.
- **Test:** game-free: two `dev.py` processes against fixture commands. The timing one waits for the build, and a build waits for the timing one.

---

## 9. Workstream E: diagnostics and analysis

### E1. One list of switches (M)

- **What:** `host/switches.def`, an X-macro list: name, type, default, area, scope (`player`, `test` or `experiment`), and what it does. It is read by C, C++ and Python.
  - A reader generates `development.md`'s switch tables between markers, as `cpu-profile.md` does.
  - `hookshot_env.txt`'s allow-list (`env_line_allowed`) takes its blocked names from the list.
- **The check:** every name read through `getenv`, `env_on` or `env_int` in `host/` and `gpu/vk` (outside eden and sirit) is listed, and every listed name is still read. It extends what `test_env_on.py` does.
- **Migration:** one PR lists all about 638 names, taking each description from the comment where the switch is read.

### E2. A header on every capture (S per tool)

- **What:** each capture the game writes starts with a common header:
  - the tool and format version;
  - the git hash and profile;
  - the GPU and driver;
  - the switches set;
  - `game_data: yes|no`.

  It covers `HOS_SAMPLE_ALL`, `RX_VK_FRAME_LOG`, `HOS_PRESENT_TRACE`, `RX_VK_PROBE`, `HOS_CHAIN` and E3. The readers (`crit.py`, `probe.py`, `framelog.py`, `vkprof.py`, `hotlist.py`, `chain.py`) check the version.
- **Data:** `game_data: yes` captures stay in the run folder, and `dev.py` never copies them out of `work/`.

### E3. Memory counters (M)

- **What:** `HOS_COUNTERS=<seconds>` writes one line of JSON per interval, with E2's header. It brings together numbers logged today at different rates and in different places:
  - guest commit (`HOS_MEM_MAP`), heap size and regions in use;
  - VMA budgets and usage, and image blocks;
  - the texture cache against `RX_VK_VRAM_MB`;
  - mirror, sync and write-back bytes (`memory_stats`);
  - pipeline and program counts and cache hits;
  - the virtual-core line, and process memory.

  `scripts/counters.py` prints a table, the difference between two points (a leak check across a D4 loop), or a chart for a PR.
- **Rule:** zero cost when unset. Every counter is read where it is already kept.

### E4. Warnings and clang-tidy on our own code (M)

- **Warnings:** in the dev profile, host and renderer objects (not lifted code, `third_party`, eden or sirit) build with `-Wall -Wextra -Wno-unused-parameter -Wshadow -Wimplicit-fallthrough -Wformat=2`. No `-Werror`; `dev.py build` shows only the warnings in files changed against `main`.
- **clang-tidy:** a short `.clang-tidy` of checks that find bugs, not style: `bugprone-*` minus the noisy ones, `clang-analyzer-core.*` and `unix.*`, `performance-unnecessary-copy-initialization`.
  - It runs from A8's `compile_commands.json` on changed files, locally and in CI. CI covers the renderer only, since the host's flags need a lift.
  - **Advisory to start (decision 4).** Everything builds with `-Wno-everything` today, so the first baseline will be large. Once it has settled, a PR of its own makes new findings in changed renderer files fail CI.
- **Python:** no new linter; CONTRIBUTING.md says to match the file you are editing.

---

## 10. Workstream F: documentation and code maps

Two kinds of reader need the same things:

- **People** new to a subsystem.
- **LLM agents.** They start each session without memory and reach for whole files. A good map lets them read the right forty lines instead.

Both need to know where a thing is, what it does, what reads it (here, above all, which tests cut it out of the
source), what is generated from what, and what they may read.

Three principles:

1. **Docs describe; checks keep them true.** Every map here has a game-free check. For an agent, a map that has gone stale is worse than none.
2. **Generate what can be generated, write what can't.** Switch tables, tool lists, provenance and the test-to-source map are generated. Meanings and reasons are written by people.
3. **One data boundary.** The repo is the shareable layer, and `work/` is the local layer. A tool may point into `work/` on the PC, but never copies from it into the repo or anything posted.

### F1. A docs index and subsystem maps (S–M)

- **A docs index:** `docs/README.md` lists every file in `docs/`, one line each, grouped:
  - start here: AGENTS, CONTRIBUTING, workflow, development;
  - architecture: design and the maps below;
  - topic notes, each with its test;
  - process.

  The topic notes' lines are generated from each note's first line. A check fails on a file missing from the index, or an entry naming a file that doesn't exist. AGENTS.md and the readme link to it.
- **Subsystem maps:** `docs/map-host.md`, `map-renderer.md`, `map-lift.md` and `map-build.md`. Each has the same five parts:
  1. what it is, in two sentences;
  2. the entry points (`main` in `hos_main.c`, `load_vulkan`, `mkwvk_init`, make_game's `main`, `lift.py`);
  3. the data flow;
  4. the rules it keeps, linking to [design.md](design.md) §4 rather than repeating it;
  5. where to start for common tasks: add a switch, add an Insert menu row, add an HLE function, add a built-in shader, add a bridge command. Each names the files to touch, the check to update, and whether `MKWVK_API_VERSION` moves.

  §2 of this proposal is most of the raw material.
- **The generated sections** (tools index, switch tables, capture formats) use `cpu-profile.md`'s marker style.

### F2. Anchors from code to docs (S)

- **What:** a comment, `// doc: docs/design.md#4-the-gpu-replay`, at the few functions that enforce a documented rule. For example:
  - the submit path, for the cross-queue `WaitEvent` rule;
  - the capture path, for "nothing the replay reads comes from live guest memory";
  - the memory gate, for compiler-memory-accounting.md.
- **The check:** every anchor resolves to a file and a heading.
- **Why it helps agents:** an agent reading the function sees where its rule is written. It is much less likely to "simplify" away a capture or a wait that looks redundant.

### F3. Every generated file names its generator (S)

- **What:** `docs/generated.md` lists each checked-in generated file or glob, with its sources, the command that regenerates it, and the check that proves it current. Today that is:
  - `gpu/vk/shaders/*_spv.h`;
  - `gpu/vk/host_shaders/*_spv.h`;
  - the FSR 3 headers;
  - the shipped pipeline-state list.

  It also lists, as local only, what the lift generates under `work/sa/` (`code_*.c`, `a64_table.c`, `a64_hooks.c`, `hos_image.c`, `nvn2_exports.c`, `rt64/a64.h` and the rest), each with its generator. A build error in `code_042.c` then says where its text came from.
- **Banners:** every checked-in generated file starts with the banner the `host_shaders` headers already use: "Generated by `<command>` from `<sources>`. Do not edit: regenerate. Nothing in it comes from the game."
  - The 50 `shaders/*_spv.h` gain it at their next regeneration through `dev.py shaders`.
  - A comment leaves the SPIR-V words unchanged, and these headers aren't in the shader stamp, so players' caches are unaffected.
- **The check:** files matching a glob in the list have the banner, and files with a banner are in the list. The existing `--check` modes prove the words are current.

### F4. Game functions: local lookups only (S)

Decision 1 settles this: a table of game-function addresses with names and meanings is a map of the game's code, so it
stays in a local file outside the repo. Nothing in `docs/` lists game functions, and nothing in the repo renames them.
What F4 keeps is tooling that reads a person's own local map when one exists:

- **`dev.py fn --local <address|name>`** reads the local map (its path from `HOOKSHOT_GAME_MAP`, which is never inside the repo), and lists the repo code that names the address. That covers the `patch_…` in `nx2/oot_*.py` that hooks it, and the host code that calls it (`guest_call` / `a64_lookup` sites).
  - It prints only to the local terminal, and says so on its first line.
  - Agents don't run it (decision 1).
- **`scripts/oot_annotate.py --map <local file>`**, an optional filter, entirely separate from the profilers. It appends the local map's name to each `f_<address>` in its input and passes everything else through, so its output is as local as its input. `prof.py`, `crit.py`, `hotlist.py` and `cpu_report.py` stay as they are, in the way `cpu_report.py --guest-map` already takes game code from a local file.
- **No renaming:** comments in lifted C would change the text `object_key` hashes, and link-time aliases would make a doc edit relink. The tools keep printing `f_<address>`.

### F5. A repo map for agents: `dev.py where` (M)

- **What:** a local index in `work/index/` (git-ignored; rebuilt by `dev.py index` in seconds). It joins what the other items produce:

  | Relation | Comes from |
  |---|---|
  | Definitions of our functions, types and macros, with file:line (`host/`, `gpu/vk` outside eden and sirit, `gpu/render`, `nx2/`, `scripts/`, `tests/`, `builder/`) | a standard-library scanner using D2's `srccut.py` |
  | **Tests that cut each file, and each function** | D1's map, refined to the function level by each test's markers |
  | Who includes each header | A6's depfiles, else `#include` lines |
  | Switches each file reads, and their rows | E1 |
  | What each generated file comes from | F3 |
  | Which doc explains a file or a function | F1, F2 |

- **`dev.py where <thing>`** takes a path, `file:function`, a switch or a header. Its answer is short, cites file:line, and leads with what agents most often get wrong:

  ```
  $ python -I nx2/dev.py where vk_menu.cpp:draw_row
  gpu/vk/vk_menu.cpp:<line>  static void draw_row(...)
  doc     docs/map-renderer.md#the-insert-menu
  cut by  tests/test_<a>.py (marker "static void draw_row("), tests/test_<b>.py, ... (n)
  reads   RX_VK_UI_PROMPTS, RX_VK_UI_GAME_FONT
  note    reshaping this function: update the n checks above in the same PR (AGENTS.md)
  ```
  (Illustrative: the function, the tests and the counts are placeholders.)
- **Why our own:** general code-graph tools index definitions and calls. They can't know this repo's own relations, which are exactly the ones agents break things over: tests that read source by text, switches by name, generated provenance. `where` is standard library only, deterministic, and checked in CI against fixtures.

### F6. The data boundary for agents, written down (S, first)

- **What:** decision 1 as an AGENTS.md section:

  | Layer | Examples | An agent may |
  |---|---|---|
  | Shareable | the repo's source and docs, `hookshot_log.txt` (CONTRIBUTING: no game data), screenshots | read, quote, post |
  | Local | `work/` and anything made from the game's files: lifted C, `functions.txt`, `image.bin`, a build's linker maps, dumps, `game_data: yes` captures, program caches, saves, and maps of the game's code such as a table of function addresses | **never read** |

- **Tools follow it mechanically:** local-layer output only behind `--local`, labelled on its first line; nothing writes from `work/` or a local map into the repo.

### F7. Checks across `docs/` (S)

- **Links:** every relative link and `#anchor` in every `.md` resolves.
- **Code references:** a doc naming `path` with a function (``vk_replay.cpp `submit_job` ``) names one that exists. Line-number links are allowed only in dated documents that name their commit.
- **Switches:** a switch named in prose is in E1's list.
- **Completeness:** the docs index (F1) and the generated-files list (F3).
- All text-only and fast, run in every shard.

---

## 11. Rollout

Each PR is claimed in #dev-work before work starts, as [workflow.md](workflow.md) asks. The player-reaching items
(A3, A7, C3) also get their worklist rows.

### Phase 0: measure (about a week)

| PR | Content | Done when |
|---|---|---|
| 0.1 | **A1** per-phase timing | each phase and both links in `build_times.json`; three runs recorded on Windows and Linux: a clean build, a no-op rebuild, a one-file renderer edit |
| 0.2 | the numbers, added to this file | link times, above all **Windows' exe link** (decision 5), hashing, the Windows emit, and save → scene through the bridge |

**Gate:** if Windows' no-op rebuild is mostly the exe link even after A4, C2 is reconsidered. Otherwise it stays dropped (Linux: 18 s for a whole no-op build).

### Phase 1: quick wins (2–3 weeks)

| PR | Content | Depends on |
|---|---|---|
| 1.1 | **F6** the data boundary in AGENTS.md (decision 1: strict) | — |
| 1.2 | **A10** the opt-in shared object store (offered by hckrman101) | — |
| 1.3 | **A4** skip unchanged links | 0.1 |
| 1.4 | **A9** `profiles.py` + `dev.py status/build/times` | — |
| 1.5 | **D6** the lock between builds and timing runs | 1.4 |
| 1.6 | **A7** keep the lift after source compile errors; classify link failures | — |
| 1.7 | **A8** `compile_commands.json` | 1.4 |
| 1.8 | **D1** `run_all.py --changed` | — |
| 1.9 | **B1** bridge `relaunch`, the staged DLL swap with its symbol check (dev), `dlerror()` in the loader's failure line, **C3**'s template, `dev.py run --watch` | 1.3, 1.4, 1.5 |
| 1.10 | **F1** `docs/README.md` index + its check | — |

**Exit:**

- a renderer `.cpp` edit links only the DLL;
- `dev.py status` names every rebuild's reason;
- a compile typo doesn't relift;
- relaunch to a scene is timed.

### Phase 2: the build graph and the inner loop (3–4 weeks)

| PR | Content | Depends on |
|---|---|---|
| 2.1 | **A2** the `LIFT_ENV` allow-list without path variables + its check; narrower data-file hashing; then, optionally, the shared lift snapshot | 1.4 |
| 2.2 | **A6** depfiles | — |
| 2.3 | **A5** stat cache (if 0.2 says so) | 0.2 |
| 2.4 | **B2** `RX_VK_SHADER_DIR` + `dev.py shaders --watch` | 1.9 |
| 2.5 | **D2** `tests/srccut.py` + the `vk_menu.cpp` readers | — |
| 2.6 | **D3** sanitizer lane | — |
| 2.7 | **E1** the switch list, its check, generated tables | — |
| 2.8 | **F3** `docs/generated.md`, banners, check | 2.4 |
| 2.9 | **F7** link and reference checks across `docs/` | — |

**Exit:**

- `RX_VK_*` in the shell doesn't relift;
- a header edit rebuilds only its includers;
- a built-in shader edit shows on relaunch without a DLL build;
- every generated file says how to regenerate it.

### Phase 3: scenarios, diagnostics, maps (in parallel)

| PR | Content |
|---|---|
| 3.1 | **D4** scenario files in `tests/scenarios/` + the starting set; in-session A/B (offered by hckrman101) |
| 3.2 | **D5** run summaries with spread and a sanity metric, `--compare`, tested-configurations rows |
| 3.3 | **E2** capture headers |
| 3.4 | **E3** memory counters + `scripts/counters.py` |
| 3.5 | **E4** dev warnings; `.clang-tidy` + baseline; CI on the renderer |
| 3.6 | **C1** debug info in dev |
| 3.7 | **F1** subsystem maps; generated doc sections |
| 3.8 | **D2** remaining migrations |
| 3.9 | **F5** `dev.py index` / `where` |
| 3.10 | **F2** `doc:` anchors + check |
| 3.11 | **F4** `dev.py fn --local` and `oot_annotate.py --map`, over a person's local map |

### Phase 4: only with a measured reason

| PR | Content | Gate |
|---|---|---|
| 4.1 | **A3** parallel emit on Windows | 0.2: the emit is minutes |
| 4.2 | **C2** dev-only host split: not now (decision 5) | only if 0.2's Windows numbers show the exe link dominates host edits after A4 |
| 4.3 | **C3** asynchronous update check (players) | agreed (decision 6); its own worklist row; measured on a slow network |
| 4.4 | **B3** teardown export, then the live swap | B1 used for weeks, with a written reason it isn't enough; one API bump, batched |

---

## 12. Verification

**Every PR:** a game-free check that fails without the change, a full `python -I -B tests/run_all.py`, and a note of
what couldn't be tested (workflow.md, step 4).

**Build items (A1–A9):**

- **Release output unchanged.** A release build of the same tree, before and after, gives the same lifted-chunk and hot-piece object keys and byte-identical lifted C. Checked locally (it needs the game) and reported.
- **Every toolchain.** Windows with llvm-mingw and with the MSVC-target route, and Linux with clang. CI's `linux-appimage.yml` and the Windows `vulkan` job cover the renderer-only path.
- **The Builders still parse the output,** including their progress and times screens.

**Runtime items (B1, B2, C3, E3):**

- **Tier 1 before merge:** RTX 20–50 and RX 6000–9000, on Windows and Linux, and the Steam Deck. A `tested-configurations.md` row for each tier tested.
- **Off by default, and zero cost when off.** Each switch is unset in release; a check proves the release profile never sets it. Frame times from `RX_VK_FRAME_LOG` are compared with the switch unset and set.

**Docs and map items (F1–F7):** game-free and text-only.

- F2's anchors and F3's banners are comments: lifted-code keys don't change, and renderer and host keys change once.
- A check fails when `docs/` or a tool's default output holds content that could only come from `work/`.

**Player-reaching items (A3, A7, C3):** a release update build from the previous release's work folder, timed on
Windows and Linux against the previous version. For A3, lifted C byte-for-byte from one process and from N.

---

## 13. Risks and open questions

### Risks

| Risk | Where | Mitigation |
|---|---|---|
| A narrower lift key misses an input, and a stale lift runs wrong (the 1197/1176 class) | A2 | The `LIFT_ENV` check ships in the same PR; `dev.py build --relift` stays available |
| Dev and release drift | §4.1, C1, C2 | Lifted objects are shared by construction; PR numbers come from release; C2 is gated |
| The failure classifier keeps a bad cache | A7 | Unknown failures keep today's behaviour; it only relaxes for source compile errors and named link causes |
| Link skipping keeps a stale binary | A4 | The key covers every object key, the link line and the libraries; a missing or resized output relinks |
| Teardown bugs | B3 | Deferred; teardown first; dev only |
| The switch list becomes a chore | E1 | Seeded in one PR from the existing comments; the check names the missing row |
| D2's migration breaks tests | D2 | A script compares cut text before and after for every migrated test |
| Maps go stale and mislead agents | F1–F7 | No map without a check; generated sections are never hand-edited; `where`'s index is rebuilt, not committed |
| Local content reaches a provider or the repo | F4–F6 | F6 first; local output only behind `--local`; nothing writes from `work/` into `docs/` |
| Interface changes invalidate players' caches | B1, B3, C2 | Batch into one `MKWVK_API_VERSION` bump; C2 has its own table and leaves `vk_api.h` alone |
| A renderer from another tree is swapped in and never loads | B1 | The symbol check before the rename keeps the old DLL; the loader's failure line names the missing symbol |
| Two builds race on the shared store | A10 | Each build writes a private folder and links entries back atomically; a killed build leaves no partial entry |
| A new checkout's objects never match the store | A10 | Seed `hot_funcs.txt`, `hot_order.txt` and `chunks.txt`; keep the PGO profile at a content-addressed path |
| Timing numbers taken beside a build | D4, D5 | D6's lock; the summary records whether the run held it exclusively |

### Open questions

1. Does the lift read `RX_RELEASE`, or any `RX_*` beyond `COMPILE_ONLY_ENV`? (A2's check answers it.)
2. What share of a no-op rebuild on **Windows** is the exe link, the DLL link and the hashing? On Linux the whole no-op build is 18 s. (Phase 0; decides whether C2 is ever reconsidered)
3. How long is the Windows emit on the same PC as a Linux one? (Phase 0; decides A3)
4. How long is save → scene through the bridge with the dev template and a warm cache? (Phase 0; decides whether B3 is ever needed)
5. Why did issue 1197's stale runtime object keep its key? (A7, A6)
6. Can the Linux CI toolchain carry sanitizer runtimes without growing the AppImage's LLVM build? (D3)
