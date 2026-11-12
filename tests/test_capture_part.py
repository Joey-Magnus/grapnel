"""A capture's late pages wait for the part of a submission that writes them back, not for the submission's last part
(gpu/vk/vk_memory.cpp's capture_make and take_capture, gpu/vk/vk_replay.cpp's vk_part_state and vk_part_wait).

A late page is one the CPU wrote that work still on the GPU writes back: the capture's copy of it must come after that
write-back (OoT's exposure meter page; a copy taken before it put the frame before's GPU words back over the newer ones).
The wait was for the page's submission value, done with its last part: all of the frame before's GPU work. Once the
present no longer holds the game's threads for that same work (the presenter thread), the next frame's replay waited for
it here instead, on the game's main thread and its presentation thread. The statements are cut from the source and run
against stand-ins for the recordings' timeline:

  - a page whose part is done on the GPU is not late: no wait, no second copy;
  - the other late pages wait for the newest of their parts;
  - one late page written in place (no part) makes the wait the submission's value, as before, for all of them;
  - a part not yet submitted (noted, not in the map) counts as late and is waited for; a part the map does not know
    by the time of the wait falls back to the value;
  - RX_VK_CAPTURE_PART=0 gives every page part 0, so the value always;
  - both waits are bounded (250 ms), and a wait that timed out goes on, as the value's wait does.

python -I -B tests/test_capture_part.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """the text from marker to the brace that closes its first '{'"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <map>
#include <mutex>
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
static void logf(const char*, ...) {}

// ---- the recordings' timeline (vk_replay.cpp) ----
struct Dev { int device = 0; } dev;
using VkSemaphore = int;
enum VkResult { VK_SUCCESS = 0, VK_TIMEOUT = 2 };
VkSemaphore rec_timeline = 1;
std::mutex rec_map_mu;
std::map<uint64_t, uint64_t> part_rec;   // (part -> its recording's number on the timeline)
static uint64_t reached;                 // (the recordings the GPU has done)
static bool fences_off;
static bool per_queue_fences_off() { return fences_off; }
static VkResult vkGetSemaphoreCounterValue(int, VkSemaphore, uint64_t* v) { *v = reached; return VK_SUCCESS; }
static uint64_t waited_part, wait_limit;   // (wait_recorded_part's last call)
static int part_known = 1, part_ok = 1;    // (what it answers: the part in the map; reached within the limit)
static bool wait_recorded_part(uint64_t part, uint64_t timeout_ns, int* ok) {
    waited_part = part, wait_limit = timeout_ns;
    if (!part_known) return false;
    *ok = part_ok;
    return true;
}
/* STATE */
/* PART_WAIT */

// ---- the capture's choice (vk_memory.cpp) ----
static uint64_t waited_value;
static void vk_timeline_wait(uint64_t v) { waited_value = v; }
/* LATE_WAIT_STRUCT */
/* LATE_PAGE */
/* LATE_WAIT */

int main() {
    // vk_part_state: done, submitted, not known
    part_rec = {{7, 70}, {8, 80}};
    reached = 75;
    check(vk_part_state(7) == 1, "a part whose recording the GPU has done: done");
    check(vk_part_state(8) == 0, "a part submitted and not done: not done");
    check(vk_part_state(9) == -1, "a part not in the map (noted, not submitted yet): not known");
    check(vk_part_state(0) == -1, "no part: not known");
    fences_off = true;
    check(vk_part_state(7) == -1, "without per-queue fences the recordings' timeline is not asked");
    fences_off = false;
    rec_timeline = 0;
    check(vk_part_state(7) == -1, "no timeline of the recordings: not known");
    rec_timeline = 1;

    // late_page: what counts as late, and what the capture then waits for
    {
        LateWait w;
        check(!late_page(w, 100, 7, 1) && !w.value && !w.part && !w.whole, "a page whose part is done is not late");
        check(late_page(w, 101, 8, 0) && w.value == 101 && w.wait_part() == 8, "a page whose part is on the GPU is late: its part");
        check(late_page(w, 100, 9, -1) && w.value == 101 && w.wait_part() == 9, "a part not known yet is late too: the newest part");
        check(late_page(w, 102, 8, 0) && w.value == 102 && w.wait_part() == 9, "the newest value and the newest part are kept apart");
        check(late_page(w, 99, 0, 1) && w.value == 102 && w.whole && w.wait_part() == 0,
              "one late page written in place: the value is waited for (the state of no part is not looked at)");
        check(late_page(w, 103, 10, 0) && w.wait_part() == 0 && w.value == 103, "and stays what is waited for");
    }
    {
        LateWait w;   // (RX_VK_CAPTURE_PART=0: capture_make gives every page part 0)
        check(late_page(w, 100, 0, -1) && late_page(w, 105, 0, -1) && w.wait_part() == 0 && w.value == 105,
              "with every part 0 the newest value is waited for, as before");
    }

    // late_wait and vk_part_wait
    waited_part = waited_value = 0;
    late_wait(102, 9);
    check(waited_part == 9 && !waited_value, "the part is waited for, not the value");
    check(wait_limit == 250000000ull, "the part's wait is bounded: 250 ms");
    waited_part = waited_value = 0, part_ok = 0;
    late_wait(102, 9);
    check(waited_part == 9 && !waited_value, "a part's wait that timed out goes on (the value's wait would time out the same)");
    waited_part = waited_value = 0, part_ok = 1, part_known = 0;
    late_wait(102, 9);
    check(waited_part == 9 && waited_value == 102, "a part the map does not know: the value, as before");
    waited_part = waited_value = 0, part_known = 1;
    late_wait(102, 0);
    check(!waited_part && waited_value == 102, "no part: the value, as before");
    return failures ? 1 : 0;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="g++")
    a = ap.parse_args()
    memory = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")

    def need(ok, what):
        if not ok:
            raise SystemExit("FAIL: " + what)

    # (capture_make: the pages past the GPU's progress, their parts read under the page table's lock and looked up outside it)
    make = block(memory, "std::unique_ptr<Capture> capture_make() {")
    need('getenv("RX_VK_CAPTURE_PART")' in make and "by_part ? wb_parts.get(pages[i]) : 0" in make,
         "the switch RX_VK_CAPTURE_PART=0 does not give every page part 0")
    lock = make.index("std::lock_guard lk(wb_pages_mu);")
    look = make.index("vk_part_state(p.part)")
    need(lock < look and make[lock:look].count("}") >= 3,
         "the recordings' map is looked at with the page table's lock held (two locks in an order nothing else keeps)")
    need("if (pv > done) cand.push_back(" in make, "a page the GPU's completed value already covers is looked at")
    need("if (!late_page(lw, p.value, p.part, seen_state))" in make and "c->late.push_back(p.index);" in make,
         "capture_make does not decide a late page through late_page")
    need("c->late_value = lw.value, c->late_part = lw.wait_part();" in make, "the capture does not carry the part to wait for")
    need("else if (lw.value) late_wait(lw.value, lw.wait_part());" in make, "RX_VK_CAPTURE_WAIT=1's wait on the game's thread ignores the part")
    need("c->late_value = 0, c->late_part = 0;" in make, "a reused capture keeps the part of its last use")
    # (take_capture: the part when the capture has one, else the value; then the late pages are copied again, as before)
    take = block(memory, "bool take_capture(std::unique_ptr<Capture> c, uint64_t value, uint64_t completed) {")
    late = block(take, "if (c->late_value && c->map)")
    need("const bool by_part = c->late_part && vk_part_wait(c->late_part);" in late and
         "if (!by_part) vk_timeline_wait(c->late_value);" in late and
         late.index("vk_part_wait(c->late_part)") < late.index("vk_timeline_wait(c->late_value);") < late.index("for (uint32_t i : c->late)"),
         "take_capture does not wait for the part first, the value otherwise, before it copies the late pages again")
    # (a page's part is the part of its newest write-back: replaced with the value by every note)
    note = block(memory, "void wb_pages_note(uint64_t guest_lo, uint64_t guest_hi, uint64_t value, uint64_t part) {")
    need("wb_pages.set(p, value);" in note and "wb_parts.set(p, part);" in note, "a page's part is not replaced with its value")

    fixture = (FIXTURE.replace("/* STATE */", block(replay, "int vk_part_state(uint64_t part) {"))
               .replace("/* PART_WAIT */", block(replay, "bool vk_part_wait(uint64_t part) {"))
               .replace("/* LATE_WAIT_STRUCT */", block(memory, "struct LateWait {") + ";")
               .replace("/* LATE_PAGE */", block(memory, "bool late_page(LateWait& w, uint64_t value, uint64_t part, int state) {"))
               .replace("/* LATE_WAIT */", block(memory, "void late_wait(uint64_t value, uint64_t part) {")))
    with tempfile.TemporaryDirectory(prefix="capture-part-") as temp:
        src = Path(temp) / "capture_part.cpp"
        exe = Path(temp) / "capture_part.exe"   # (the name llvm-mingw writes on Windows; any name runs on Linux)
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], text=True, capture_output=True, timeout=20)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit(r.returncode)
    print("PASS: a capture's late pages wait for the part that writes them back, the value when one was written in place")


if __name__ == "__main__":
    main()
