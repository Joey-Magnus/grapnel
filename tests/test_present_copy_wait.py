"""A present made on the replay's queue waits for its copy's fence first, with the queue's lock let go
(gpu/vk/vk_replay.cpp's present_out, present_copy_wait_on).

NVIDIA's driver on Linux waits inside vkQueuePresentKHR until the frame's copy into the window is done on the GPU. Made with
dev.present_mu held, that wait held every submit of the replay: with frame interpolation at 4x the game's presentation thread
waited for the lock at 17 % of all instants, 3.8 ms a frame. The source is read:

  - present_image and present_commit give present_out the fence of the copy they present, and take it away after;
  - a copy whose submit failed gives none (nothing signals its fence);
  - present_out lets the queue's lock go for the wait and takes it again before the present, after the presents in order
    (the presenter thread's drain) and never for a present on the presents' own queue;
  - the wait has a limit and sees a lost device;
  - on by default only with NVIDIA's driver on Linux; RX_VK_PRESENT_COPY_WAIT=0 / 1 over it;
  - the presenter thread's hand-off still goes by present_copy_done, which present_commit never sets.

python -I -B tests/test_present_copy_wait.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")

    def need(ok, what):
        if not ok:
            raise SystemExit("FAIL: " + what)

    image = block(replay, "void present_image(")
    need("present_copy_fence = res == VK_SUCCESS ? f.done : VK_NULL_HANDLE;" in image,
         "present_image does not give its copy's fence to present_out, or gives one nothing signals (a failed submit)")
    need(image.index("present_copy_fence = res == VK_SUCCESS") < image.index("present_out(index, qk);") <
         image.rindex("present_copy_fence = VK_NULL_HANDLE;"), "the fence outlives present_image's present")
    commit = block(replay, "bool present_commit(")
    need("present_copy_fence = p.done;" in commit and
         commit.index("present_copy_fence = p.done;") < commit.index("present_out(p.index, qk);") <
         commit.index("present_copy_fence = VK_NULL_HANDLE;"), "frame generation's paced presents do not wait for their copy")
    need("present_copy_done" not in commit, "frame generation's paced presents could be handed to the presenter thread")
    for fn in (image, commit):
        need("std::lock_guard lk(present_image_mu);" in fn, "the fence is set without present_image_mu (it is reset under it)")
    out = block(replay, "static bool present_out(uint32_t index, std::unique_lock<std::mutex>& qk) {")
    need("if (present_copy_fence && !dev.present_queue_supported && present_copy_wait_on()) {\n        qk.unlock();\n"
         "        present_copy_wait(present_copy_fence);\n        qk.lock();" in out,
         "the wait for the copy holds the queue's lock (every submit of the replay waits behind it), or runs for the presents' own queue")
    wait_at = out.index("present_copy_wait(present_copy_fence);")
    need(out.index("present_thread_drain();") < wait_at < out.index("vkQueuePresentKHR(dev.queue, &pi)"),
         "the copy is not waited for before the present on the replay's queue, after the presents in order")
    need(out.index("present_hand_off(") < wait_at, "a present handed to the presenter thread waits for its copy on the game's thread")
    on = block(replay, "static bool present_copy_wait_on() {")
    need('getenv("RX_VK_PRESENT_COPY_WAIT")' in on and "e ? atoi(e) != 0 : by_default" in on and
         "#ifdef _WIN32\n        const bool by_default = false;\n#else\n        const bool by_default = dev.props.vendorID == 0x10DE;" in on,
         "the copy wait is not NVIDIA-on-Linux by default with RX_VK_PRESENT_COPY_WAIT over it")
    wait_fn = block(replay, "static void present_copy_wait(VkFence copy) {")
    need("UINT64_MAX" not in wait_fn and "1000000000ull" in wait_fn and "VK_ERROR_DEVICE_LOST" in wait_fn,
         "the wait for the copy has no limit, or misses a device lost")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    need("`RX_VK_PRESENT_COPY_WAIT=0` / `=1`" in docs, "the switch is not in docs/development.md")
    print("PASS: a present on the replay's queue waits for its copy with the queue's lock let go, NVIDIA on Linux by default")


if __name__ == "__main__":
    main()
