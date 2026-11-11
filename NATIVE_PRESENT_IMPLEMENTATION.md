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
