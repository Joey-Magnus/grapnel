# Local Linux runtime API

The opt-in runtime API supports reproducible tests in disposable sessions. It does
not provide a remote service or ship game-derived addresses, bindings or saves.
Build the host using the normal instructions in [development.md](development.md).

## Starting and observing a session

```sh
python3 -I scripts/analysis_api.py start --game /path/to/private/game \
  --save /path/to/account --saved-aspect --frame-generation 0 --present-trace
python3 -I scripts/analysis_api.py status /path/returned/as/session.json
python3 -I scripts/analysis_api.py shot /path/returned/as/session.json
python3 -I scripts/analysis_api.py stop /path/returned/as/session.json
```

The save folder must contain `account.sav`. The launcher copies it into a unique
ignored `work/runs/` directory and holds a shared local game lock for the session.
Player saves are not used as writable test profiles. `stop` rejects descriptors
marked as player sessions and checks process identity before signaling a process.
It terminates a test; it does not issue an in-game save command.

The default launch is minimized, silent and 16:9. Python callers can select
`start_minimized=False` and `audio_enabled=True`. `--saved-aspect` preserves the
test game folder's saved Ultrawide preference. Match the copied graphics options
and actual window dimensions to the baseline before making performance claims.
The status records the initial swapchain configuration, not every later resize.

Status includes native presents, frame/poll ages and input ownership. A stale FPS
value does not prove progress. `shot` waits for a new complete periodic PNG;
`dump` acknowledges a renderer trigger, whose GPU readback may still be pending.
Renderer screenshots precede external DLSS processing.

`HOS_DEBUG_SOCKET` enables an abstract Unix `SOCK_SEQPACKET` endpoint. The server
checks peer UID; the client checks server PID and process start time. Requests and
memory reads are bounded. Other platforms retain no-op diagnostics stubs.

## Input ownership

```sh
python3 -I scripts/analysis_api.py control SESSION exclusive
python3 -I scripts/analysis_api.py press SESSION A --ms 80
python3 -I scripts/analysis_api.py input SESSION --sticks 0 16000 0 0 --ms 400
python3 -I scripts/analysis_api.py control SESSION player
```

`exclusive` excludes physical input, `shared` merges focused physical input, and
`player` clears injected input and returns control. Holds begin at the first Npad
poll and carry sequence acknowledgements. Cancellation cannot overwrite a newer
client's input. A poll acknowledgement is not proof of movement or scene arrival;
inspect captures and game state. On failure, release controls and retain evidence.

## Image-bound scene and event operations

`scene_catalog.py --game GAME` reads local binary YAML assets and writes a catalogue
under ignored `work/scene-api/` (requires `zstandard`). It preserves duplicate
entrance names and checks image identity. Asset presence does not prove loadability.
Rebuild the catalogue after replacing assets, even if the image hash is unchanged.

`start --scene-bindings LOCAL_JSON` enables typed guest dispatch with a profile
identified for that exact game image. The launcher validates and copies the profile;
the host checks build identity and in-image function/pointer bounds. All addresses,
selectors and game-derived identifiers remain local. Authored profiles in the tests
illustrate the format without distributing game content.

| Operation | Purpose |
| --- | --- |
| `scenes SESSION` | List catalogue maps and entrances. |
| `scene-state SESSION` | Read current and pending scene fields. |
| `scene-load SESSION SCENE ENTRANCE` | Request a validated map transition. |
| `event-state SESSION` | Observe the active event and its progress. |
| `event-start SESSION EVENT --scene-id SCENE` | Submit an event start. |
| `event-play SESSION EVENT --scene-id SCENE` | Start and observe the configured event sequence. |
| `event-wait SESSION EVENT --scene-id SCENE` | Observe an already-running event. |
| `value-read SESSION NAME` | Read a named, typed scalar binding. |
| `value-write SESSION NAME JSON_VALUE` | Apply a validated scalar operation on the guest worker. |

Mutations require a disposable session, exclusive neutral input, fresh frames,
matching bindings and an available guest worker. Scene loads require a unique
entrance and no conflicting reservation. Game calls run at the configured worker's
Npad boundary, with context restoration; the socket thread never calls game code.
Memory reads are bounded but not atomic. Manager replacement, stale frames and
ambiguous cancellation must fail rather than silently retry a mutation.

`memory-info` and `read-memory ADDRESS LENGTH` are read-only diagnostics; a read is
limited to 1--256 bytes and fails for inaccessible/partial memory. There is no
generic memory-write command. Typed operations do not make arbitrary writes safe.

The Python API also provides `scene_ready`, `navigate_ui`, actor operations and
scene playlists. Readiness requires the expected map, empty transition fields,
an idle event manager, neutral input and advancing frames. UI recipes describe
explicit observed states and bounded actions; they are not blind key sequences.
A playlist must verify its destination and completed event chain. Acknowledged
submission alone never establishes completion or restored gameplay.

Tests in `test_scene_*`, `test_event_*`, `test_game_values.py` and `test_ui_*` use
authored profiles. Keep real bindings, fixtures, captures and reports in `work/`.

## Performance evidence and optional DLSS

See [performance-tests.md](performance-tests.md) for interval analysis and A/B
comparison requirements. CPU instrumentation changes timing; compare against a run
with it disabled. Native present-call intervals do not measure physical display
cadence or GPU execution time. `--fps-target 60..240` is a diagnostic limiter setting,
not a promise of that throughput or correct animation above 60 FPS.

`--dlss5` requires the separately supplied `scripts/dlss5_api.py` adapter. It copies model preferences
into the private session. `--dlss-preferences FILE` selects a baseline and
`--dlss-base DIRECTORY` selects an isolated candidate. No layer or model is downloaded
or installed. Native frames, helper evaluations and displayed frames are distinct.

### Renderer wall/CPU stage trace

`start --stage-trace` (Python: `HookshotAPI.launch(..., stage_trace=True)`)
sets `RX_VK_STAGE_TRACE` to the private run's `renderer-stages.csv` and also
records `native-presents.csv`. It requires a renderer built with this collector;
setting an environment variable alone does not prove support. Check that the
CSV contains rows. This is opt-in diagnostic instrumentation, not a performance
improvement or a zero-overhead benchmark mode.

The trace separates submission memory work, capture retirement/stamping,
texture-shadow invalidation/update, and presentation lock/fence/acquire/queue
stages. Every interval has monotonic start/end times and calling-thread CPU
consumption. Capture rows also contain dirty/copied/late page counts and the actual source
allocation memory-property flags (`source_memory_flags`; bit 0x8 is HOST_CACHED).
Zero on noncapture operations does not describe a memory allocation. The analyzer
keeps different source memory flags separate. One rotating
copied page per capture is eligible for `shadow_page_sample`, splitting lookup /
allocation from a 4096-byte copy; nontexture pages are skipped. These are samples,
not totals or automatically extrapolated estimates. Output occurs after the
instrumented capture/presentation locks are released. Output is buffered, flushed
approximately once a second, and capped at one million rows. Forced termination
can lose the buffered tail. A capped trace is incomplete.

On Linux the timestamps use `CLOCK_MONOTONIC`, matching native present timestamps;
CPU uses `CLOCK_THREAD_CPUTIME_ID`. Windows CPU time uses `GetThreadTimes` and can
be coarse for short stages. Thread identifiers are process-local hashes.
Wall minus CPU time includes descheduling as well as waits; it is not proof of
GPU waiting. Explicit wait stages narrow that interpretation. GPU execution time
requires Vulkan timestamps (the existing `RX_VK_PASS_TIMING` diagnostics), not
CPU time spent invoking Vulkan.

```sh
python3 scripts/analyze_stage_trace.py RUN/renderer-stages.csv RUN/native-presents.csv \
    --first 3000 --last 3600 --output RUN/stage-analysis.json
```

The analyzer keeps nested operations separate and lists stages overlapping the
ten slowest native present intervals. Overlap is temporal correlation, not a
causal assignment to a displayed frame: work can execute concurrently or ahead
of presentation. `submit_memory/take_capture_inclusive` contains `take_capture`
stages; sampled page work is contained in `shadow_update`. Never add these levels
together. Boundary-crossing stages are excluded from window totals and retained
in overlap evidence. Instrumentation overhead needs a matching disabled run.

### Bounded CPU snapshots for uncached capture buffers

`start --cpu-uncached on|off` (Python: `cpu_uncached=True|False`) explicitly
selects `RX_VK_CAPTURE_CPU_UNCACHED`. Omitting it follows the renderer default;
this candidate is currently opt-in. The selection is made at process startup.

When Vulkan gives a capture buffer without `HOST_CACHED`, the candidate first
captures into ordinary CPU memory, then uploads the same valid-page runs to the
Vulkan buffer. Texture shadows read the CPU snapshot. Cached Vulkan buffers keep
the original path. Late GPU write-back updates both copies after the existing
wait; guest writes after submission cannot replace ordinary captured bytes.

Snapshot payload storage is limited to 128 MiB per capture and 256 MiB across all
concurrent captures. Reservations are atomic and released on allocation failure,
reset or destruction. Exhaustion falls back to the original mapped-buffer path;
it does not skip required copies or synchronization. These limits describe the
additional snapshot payload, not total process RSS or allocator overhead.

Stage traces identify this path as `take_capture_cpu_shadow`. Its per-page sample
is `shadow_page_cpu_sample` with memory flags 0 (ordinary CPU storage); the outer
capture still records the Vulkan allocation's flags. Do not interpret the sample
as a read from the uncached Vulkan mapping.

### Virtual-core wait ownership diagnostics

`HOS_VCORE_TRACE_MS=20` enables bounded ownership snapshots for virtual-core
acquisitions that are still waiting after 20 ms. Optional
`HOS_VCORE_TRACE_THREAD='Presentation Thread'` restricts the waiting thread by
exact name. These variables belong in the analysis process environment; they do
not change scheduler priorities, escape limits or the number of virtual cores.

Each acquisition captures at most once, with a process limit of 256 snapshots.
`vcore-wait` records the snapshot's monotonic timestamp, native waiter TID,
elapsed wait at capture, total wait and eventual held core (core index plus one,
zero means no core). `vcore-owner` rows copy each allowed core's owner TID, name,
priority and kick state under the scheduler lock. Owner TID zero denotes a free
core. Formatting and logging happen after releasing that lock and after the
wait completes; log line order is not the snapshot timestamp. No concurrently
changing guest CPU register context is inspected.

Use `python3 scripts/analyze_vcore_waits.py GAME_LOG NATIVE_PRESENTS_CSV` to join
snapshots to native present intervals from the same process. Ownership is only
proven at the snapshot instant, not for the entire wait. A missing record does
not prove no wait occurred: filtering, the cap and waits that end before the
capture check limit coverage. Missing owner rows are reported as incomplete.
An external stack capture can perturb scheduling; it is separate diagnostic
evidence, not an unperturbed FPS measurement. Disabled tracing adds no clocks
beyond the scheduler's existing timing calls.
