# Owned native presentation slots

Opt-in RX_VK_ASYNC_PRESENT, three source-format images, no generated frames or
optical-flow/luma work. Each slot owns a timeline: odd value publishes the captured
image, even value completes its presentation read. Reuse waits for the previous
even value. The capture submit flushes previous batched commands and is submitted
before its job is visible to the worker. Vulkan Present executes normally on the
worker; no caller-owned Vulkan structures or semaphores are deferred past return.

The worker retains a slot until its read is submitted and the actual Present call
returns. Hidden/out-of-date surfaces enqueue an empty ready-to-consumed transition,
so no future slot reuse waits for a read that was never submitted. Failed capture
submission is not queued. Source format, crop and native-PQ interpretation travel
with the owned frame. Only successful/suboptimal Presents count as accepted;
these are not physical display measurements. Queue depth is bounded at three.

Source-size/format changes drain queued CPU jobs and the device before replacing
images/timelines. Switching to direct/interpolated output drains old native jobs.
The renderer's existing process-lifetime thread model is retained: no standalone
renderer teardown/unload contract is added. A separate device present queue is
needed to overlap replay submissions while Present itself blocks; otherwise the
renderer still holds its same-queue mutex. The private external layer must also
use per-queue locking (async-slots-20261111), or its device mutex cancels this overlap.

Validation: actual production native queue extraction passed disabled path,
bounded FIFO/backpressure, timeline ready sequence1/1/1/3, source format/crop,
resize drain, partial allocation cleanup and failed capture admission. Renderer
built successfully twice (20s and17s). The latest accepted-present counter correction
was made after those checks; parent requested no more builds/tests during benchmarks.
It still requires its focused rerun and integrated build/full-suite checks.
No Vulkan runtime timeline, resize/failure or game/image/performance proof yet.
Do not install this as a verified speedup. Added CPU/GPU overlap can add bounded
latency and cannot overcome total GPU work exceeding the8.33ms120-FPS budget.

## Concurrency audit and accepted-present telemetry

The worker never acquires replay_mu. Recorder foreign_wait snapshots only W,
not unpublished producer bytes or future producer progress; the decoder executes
vkCmd calls without taking replay_mu/native.mu/dev.present_mu. Native slot waits
therefore do not require producer progress to release an existing worker job.
The source submission passes vkEndCommandBuffer/queue-submit recorder boundaries
before the job is published. Its per-slot reuse signal was already enqueued by
the worker before busy is cleared.

Concrete audit fixes: native image replacement now uses the renderer's existing
device_wait_idle_locked helper, including its present_queue_mu exclusion. Starting
native output drains the previous interpolation jobs first. A frame already chosen
for inline/deferred interpolation cannot also enter native output during a menu
setting transition. With a separate present queue, present_out releases
present_mu before the external Present call; with one queue it remains serialized.
The private layer queue lease covers the actual API operation, not its model wait.

RX_VK_ASYNC_PRESENT_LOG=/absolute/path.csv enables a separate worker trace. Each
row identifies its source frame and monotonic host timestamps for source-call,
enqueue, worker start, actual vkQueuePresent begin/return and worker completion,
plus acceptance and VkResult. Throughput uses accepted present_end_ns intervals;
worker_ns-queued_ns measures worker queueing, queued_ns-source_ns includes capture
and backpressure, and present_end_ns-source_ns is host source-to-acceptance delay.
These are neither display scanout timestamps nor input-to-photon latency. Hidden
or failed presents remain rows with accepted=0 and possibly zero call timestamps.
Opt-in logging flushes each row; keep it enabled in both sides of timed comparisons.

Extended production tests cover framegen-to-native drain, hidden-output counters,
failed-capture rejection, monotonic slot reuse and CSV source-ID/timestamp order.
They passed after the telemetry/counter changes. A fresh build is running; the
small final framegen-admission guard was added after that build began, so rebuild
that translation unit before treating its artifact as the final revision.

Final concurrency/telemetry revision rebuilt successfully after the admission
change: eight seconds, zero compiler failures, renderer linked. No gameplay test
was launched. Build evidence: work/build-concurrency-final.log. The recorder
interaction conclusions above are source/lock-order analysis, not a live race or
Vulkan validation result; those acceptance checks remain required.

## Integration fixture compatibility

The parent integration suite at 47ec0f2e exposed six presentation fixture failures:
one extracted submission lacked the new NativePresentSync declaration; two capture
fixtures required the old literal call/gate; two geometry fixtures lacked the
queued native-PQ snapshot argument; and the result-routing fixture assumed only
one display submission. These were extraction contracts, not observed production
failures. This follow-up changes tests only and does not require a renderer rebuild.

The fixtures now retain the real sync declaration and capture submission statement.
Capture validation covers direct, interpolated, native-worker and headless routes;
pending-shot ownership covers both handoff states. Aspect/geometry tests explicitly
check that queued SDR and PQ snapshots override the changing producer global in
both directions. Result injection covers all ten WSI sites and six result values
per site: non-success display and release submissions must stop before a reset
fence wait or an unreleased slot can be reused. Other WSI result routing remains
covered by the original assertions.

All six requested tests passed on this revision with the bundled clang23 and
Vulkan headers, run at nice 19 with at most two concurrent compilers:
test_fsr_image_retirement (28 backend/case combinations), test_capture_dimensions
(all dimension/window/headless cases and decoded PNG), test_capture_slot_ownership
(both handoff states and immediate/delayed completion), test_present_aspect,
test_present_device_loss (60 injections), and test_present_geometry_trace
(logging unset, disabled and enabled). git diff --check passed. The existing
integration failure log is ../renderer-redesign-integration-tests-20261111.log.
No renderer build or game launch was needed for these fixture changes.

The later leases integration suite exposed three more literal extraction markers:
test_antilag, test_present_ahead and test_present_semaphores named the pre-telemetry
present_out signature/call. Updated those three markers to include the sync
parameter without altering any timing, semaphore ownership, deferred-present or
recreation assertion. All three passed with the bundled clang23/Vulkan headers at
nice 19; no renderer change or rebuild. Parent foreground native smoke separately
observed matching source/accepted cadence, but concurrent tests prevent treating
that smoke as a performance comparison.
