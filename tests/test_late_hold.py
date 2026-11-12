"""The replay's submits are held for a capture's late page instead of the capture waiting for the GPU
(gpu/vk/vk_replay.cpp's late_hold; gpu/vk/vk_memory.cpp's take_capture, late_hold_arm).

A capture's late page is one the CPU wrote that a part still on the GPU writes back (OoT's exposure meter page, written
back by the last part of the frame before). take_capture waited for that part on the game's main thread, so the next
frame's replay did not start before the GPU had finished the frame before. Now the capture is taken as it is, the replay
records at once, and what it submits is held until the part is done and the page has been copied again. The functions
are cut from the source and run against a stand-in for the queue and the recordings' timeline:

  - a hold is armed only with nothing held, no hold armed, the part's recording sent and not yet done, and never with
    batched submits;
  - while it is armed every submit_recording is held, in order, and can be found by waiters only once it is in the list;
  - the page's copy comes before anything held reaches the queue, and the held submits go out in the order they were made,
    before the first submit that is not held;
  - a submit_recording or a progress poll that finds the part done ends the hold without a wait; a poll never waits;
  - a flush that must send waits for the part (once, with a limit), then copies and sends; a timed-out wait copies and
    sends all the same; a flush with nothing to send does not wait;
  - the cap on held command buffers forces a flush;
  - vk_memory.cpp: take_capture arms the hold or waits as before, the copy is the capture's own late pages, and a held
    page the CPU writes again before its copy stops further holds.

python -I -B tests/test_late_hold.py --headers <Vulkan-Headers include> [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def between(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start) + len(last)]


FIXTURE = r"""
#include <vulkan/vulkan.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
static void logf(const char*, ...) {}
struct { VkDevice device{}; VkQueue queue{}; std::mutex present_mu; } dev;
static void device_lost() { check(false, "no device is lost here"); }
#define PROF(x) ((void)0)
namespace fps_stats { constexpr int kGpuWait = 0; }
struct FpsWait { explicit FpsWait(int) {} };

// ---- the queue and the two timelines ----
static VkSemaphore timeline = (VkSemaphore)1, rec_timeline = (VkSemaphore)2, batch_tl = (VkSemaphore)3;
static uint64_t gpu_rec_done;                 // (the recordings the GPU has done: rec_timeline's counter)
static std::vector<std::string> events;       // ("copy", "wait", and each command buffer as it reaches the queue)
static int waits;
static VkResult wait_result = VK_SUCCESS;
VKAPI_ATTR VkResult VKAPI_CALL vkGetSemaphoreCounterValue(VkDevice, VkSemaphore s, uint64_t* v) {
    *v = s == rec_timeline ? gpu_rec_done : 0;
    return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL vkWaitSemaphores(VkDevice, const VkSemaphoreWaitInfo* wi, uint64_t timeout) {
    check(wi->pSemaphores[0] == rec_timeline && timeout == 250000000ull, "a wait for the hold is on the recordings' timeline, 250 ms at most");
    waits++, events.push_back("wait");
    if (wait_result == VK_SUCCESS) gpu_rec_done = std::max(gpu_rec_done, wi->pValues[0]);   // (the GPU gets there)
    return wait_result;
}
VKAPI_ATTR VkResult VKAPI_CALL vkQueueSubmit2(VkQueue, uint32_t, const VkSubmitInfo2* si, VkFence) {
    for (uint32_t j = 0; j < si->commandBufferInfoCount; j++)
        events.push_back("cb" + std::to_string((uintptr_t)si->pCommandBufferInfos[j].commandBuffer));
    return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL vkEndCommandBuffer(VkCommandBuffer) { return VK_SUCCESS; }

// ---- what submit_recording and the flushes use ----
struct Recording { int slot = 0; VkCommandBuffer cmd{}, upload{}; VkFence fence{}; uint64_t value = 0, batch = 0, part = 0; bool submitted = false; };
static void draw_flush_recording(int) {}
static bool texture_uploads_recorded() { return false; }
static void gprof_submitted(int, bool) {}
static void gpu_time_end(Recording&) {}
static uint64_t rec_seq;
static std::mutex rec_map_mu;
static std::map<uint64_t, uint64_t> value_rec, part_rec;
static std::condition_variable rec_map_cv;
static std::set<uint64_t> rec_open_values;
static std::atomic<bool> pend_held{false};
static struct { std::vector<VkCommandBufferSubmitInfo> cbs; uint64_t signal = 0; bool any_signal = false; uint64_t rec = 0; uint64_t reflex = 0; } pend;
static uint64_t batch_next, batch_flushed;
static std::chrono::steady_clock::time_point pend_since;
static int64_t st_flushes, st_batched_cbs;
enum { FR_OTHER, FR_POLL, FR_WAIT, FR_SLOT, FR_PRESENT, FR_CAP, FR_VALUE, FR_COUNT };
static int64_t st_reason[FR_COUNT];
static int flush_reason = FR_OTHER;
static bool batched;
static bool batch_on() { return batched; }
static bool batch_gpu_idle() { return false; }
static bool per_queue_fences_off() { return false; }
static int par_threads() { return 0; }
static uint64_t reflex_frame() { return 0; }
static const void* reflex_submit_id(const void* next, uint64_t = ~0ull) { return next; }
static void note_timeline_sent(uint64_t) {}
/* HOLD_STATE */
/* HOLD_END */
/* FLUSH */
/* POLL */
/* SUBMIT */
/* ARM */

static uintptr_t next_cmd = 10;
static Recording make(uint64_t value) {
    Recording r;
    r.cmd = (VkCommandBuffer)next_cmd++, r.value = value, r.part = value + 100;
    return r;
}
static std::string joined() {
    std::string s;
    for (const auto& e : events) s += (s.empty() ? "" : " ") + e;
    return s;
}
static int copies;
static std::function<void()> copy_fn() { return [] { copies++, events.push_back("copy"); }; }
/// the part of the frame before, sent and not done: recording 5 of the timeline, the GPU at 4
static void frame_before() {
    events.clear(), pend.cbs.clear(), pend_held = false, late_hold = LateHold{}, copies = waits = 0, wait_result = VK_SUCCESS;
    batched = false, flush_reason = FR_OTHER;
    part_rec.clear(), value_rec.clear();
    part_rec[50] = 5, rec_seq = 5, gpu_rec_done = 4;
}

int main() {
    // ---- when a hold is armed ----
    frame_before();
    check(!vk_late_hold(0, copy_fn()) && !vk_late_hold(51, copy_fn()), "no part, or a part not sent yet: not armed");
    gpu_rec_done = 5;
    check(!vk_late_hold(50, copy_fn()), "a part already done: not armed (the caller copies at once)");
    gpu_rec_done = 4, batched = true;
    check(!vk_late_hold(50, copy_fn()), "batched submits: not armed");
    batched = false;
    pend.cbs.push_back({});
    check(!vk_late_hold(50, copy_fn()), "something held already (the part's own recording may be among it): not armed");
    pend.cbs.clear();
    check(vk_late_hold(50, copy_fn()) && late_hold.armed && late_hold.seq == 5, "the part sent and not done, nothing held: armed");
    check(!vk_late_hold(50, copy_fn()), "one hold at a time");
    check(!copies, "arming copies nothing");

    // ---- held submits, sent in order after the copy at the next submit that finds the part done ----
    Recording a = make(1), b = make(2), c = make(3);
    submit_recording(a);
    submit_recording(b);
    check(events.empty() && pend.cbs.size() == 2 && pend_held.load(), "while armed the submits are held, and said to be");
    check(part_rec.count(a.part) && part_rec.count(b.part), "a held recording can be found once it is in the list");
    check(a.batch && a.submitted, "a held recording's slot waits for its batch");
    gpu_rec_done = 5;   // (the GPU has finished the frame before)
    submit_recording(c);
    check(joined() == "copy cb10 cb11 cb12", "the copy first, then the held submits in order, then the one that found the part done");
    check(!late_hold.armed && pend.cbs.empty() && !pend_held.load() && c.batch == 0 && !waits, "the hold has ended, without a wait");
    Recording d = make(4);
    submit_recording(d);
    check(events.back() == "cb13" && pend.cbs.empty(), "after it submits go straight to the queue again");

    // ---- a progress poll ----
    frame_before();
    vk_late_hold(50, copy_fn());
    a = make(1);
    submit_recording(a);
    queue_flush_poll();
    check(events.empty() && late_hold.armed && !waits && flush_reason == FR_OTHER, "a poll with the part not done sends nothing and does not wait");
    gpu_rec_done = 5;
    queue_flush_poll();
    check(joined() == "copy cb14" && !late_hold.armed && !waits, "a poll with the part done copies and sends, however short the submit was held");

    // ---- a flush that must send ----
    frame_before();
    vk_late_hold(50, copy_fn());
    flush_reason = FR_WAIT;
    queue_flush_locked();
    check(events.empty() && late_hold.armed && !waits, "a flush with nothing to send does not wait for the part");
    a = make(1);
    submit_recording(a);
    flush_reason = FR_WAIT;
    queue_flush_locked();
    check(joined() == "wait copy cb15" && waits == 1 && !late_hold.armed, "a flush that must send waits for the part, copies, sends");
    frame_before();
    vk_late_hold(50, copy_fn());
    a = make(1);
    submit_recording(a);
    wait_result = VK_TIMEOUT;
    queue_flush_locked();   // (no reason given: one that must send, as a present's or another submit's)
    check(joined() == "wait copy cb16" && !late_hold.armed, "a wait that timed out copies and sends all the same");

    // ---- the cap ----
    frame_before();
    vk_late_hold(50, copy_fn());
    for (size_t i = 0; i + 1 < kLateHoldMax; i++) {
        Recording r = make(1);
        submit_recording(r);
    }
    check(events.empty() && pend.cbs.size() == kLateHoldMax - 1, "held up to the cap");
    Recording last = make(1);
    submit_recording(last);
    check(waits == 1 && !late_hold.armed && pend.cbs.empty() && events.size() == kLateHoldMax + 2 && events[0] == "wait" && events[1] == "copy",
          "at the cap a flush waits for the part, copies and sends");
    return failures ? 1 : 0;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="g++")
    ap.add_argument("--headers", type=Path, required=True)
    a = ap.parse_args()
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    memory = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")

    def need(ok, what):
        if not ok:
            raise SystemExit("FAIL: " + what)

    # (every other submit on the replay's queue sends the held ones first, under the queue's lock: they would overtake them)
    import re
    for m in re.finditer(r"vkQueueSubmit2\(dev\.queue", replay):
        before = replay[max(0, m.start() - 2600):m.start()]
        need("queue_flush_locked();" in before or "pend.cbs.push_back" in before or "si.pCommandBufferInfos = pend.cbs.data();" in before,
             "a submit on the replay's queue without the held submits sent first")
    poll = block(replay, "void queue_flush_poll() {")
    need("if (!late_hold.armed && us > 0" in poll, "a poll keeps submits held for a late page for the batch's 2 ms")
    arm = block(replay, "bool vk_late_hold(uint64_t part, std::function<void()> copy) {")
    need('getenv("RX_VK_CAPTURE_HOLD")' in arm, "the switch RX_VK_CAPTURE_HOLD is gone")
    need("batch_on() || par_threads() > 1" in arm, "a hold is armed with batched submits or a parallel replay (its segments' submits pass the held list)")
    mk, lk = arm.index("std::lock_guard mk(rec_map_mu);"), arm.index("std::lock_guard lk(dev.present_mu);")
    need(mk < lk and "\n    }\n" in arm[mk:lk],
         "vk_late_hold holds rec_map_mu while it takes dev.present_mu (submit_recording takes them the other way round)")
    # (vk_memory.cpp: arm or wait; the copy; the page written again)
    take = block(memory, "bool take_capture(std::unique_ptr<Capture> c, uint64_t value, uint64_t completed) {")
    need("if (c->late_value && c->map && late_hold_arm(*c)) {\n        st_tk_held++;\n    } else if (c->late_value && c->map) {" in take,
         "take_capture does not arm the hold first and wait otherwise")
    need(take.index("late_hold_arm(*c)") < take.index("std::lock_guard lk(pools_mu);"),
         "the hold is armed with pools_mu held (the replay's queue lock is taken inside)")
    arm_m = block(memory, "bool late_hold_arm(const Capture& c) {")
    need("!c.late_part || c.copied.empty() || !c.map" in arm_m,
         "a hold is armed for a capture whose buffer is not kept, or whose late pages wait for a whole submission")
    need("for (uint32_t i : c.late) lc->pages.emplace_back(i, c.pages[i]);" in arm_m, "the copy is not of the capture's late pages")
    need("if (in_tex_merged((uint64_t)c.pages[i] << 12)) return false;" in arm_m,
         "a hold is armed for a texture's storage page, which take_capture reads from the capture at once")
    need(arm_m.index("late_hold_live.store(true") < arm_m.index("vk_late_hold(c.late_part"),
         "the held pages are listed after the hold is armed: a capture on another thread could miss a write")
    copy = block(memory, "void late_hold_copy(const LateCopy& lc) {")
    need("guarded_copy((uint8_t*)lc.map + (uint64_t)slot * 4096, base + ((uint64_t)page << kPageShift), 4096);" in copy and
         copy.index("guarded_copy(") < copy.index("flush_mapped(lc.alloc, lc.nbytes);") < copy.index("late_hold_live.store(false"),
         "the copy does not copy the pages, flush them, then end the hold's page list")
    written = block(memory, "void late_hold_written(const uint32_t* pages, int64_t n) {")
    need("late_hold_broken.exchange(true)" in written, "a held page written again does not stop further holds")
    need("late_hold_broken.load(" in arm_m, "a stopped hold is armed again")
    make = block(memory, "std::unique_ptr<Capture> capture_make() {")
    need("if (n > 0) late_hold_written(pages, n);" in make, "capture_make does not look for a held page among the written ones")

    fixture = (FIXTURE.replace("/* HOLD_STATE */", between(replay, "struct LateHold {", "double st_hold_ms, st_hold_wait_ms;"))
               .replace("/* HOLD_END */", block(replay, "bool late_hold_end_locked(bool must) {"))
               .replace("/* FLUSH */", block(replay, "void queue_flush_locked() {"))
               .replace("/* POLL */", block(replay, "void queue_flush_poll() {"))
               .replace("/* SUBMIT */", block(replay, "void submit_recording("))
               .replace("/* ARM */", block(replay, "bool vk_late_hold(uint64_t part, std::function<void()> copy) {")))
    with tempfile.TemporaryDirectory(prefix="late-hold-") as temp:
        src = Path(temp) / "late_hold.cpp"
        exe = Path(temp) / "late_hold.exe"   # (the name llvm-mingw writes on Windows; any name runs on Linux)
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-include", ENV_ON_H, "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-Wno-unused-function", "-Wno-unused-variable", "-I" + str(a.headers), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], text=True, capture_output=True, timeout=20)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit(r.returncode)
    print("PASS: the replay's submits are held for a capture's late page, copied before any of them is sent, in order")


if __name__ == "__main__":
    main()
