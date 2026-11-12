"""Finalized NVN pools, unsegmented image_pool preallocation, and idle capture buffer limits.

1. When the game finalizes an NVN memory pool (`nvnMemoryPoolFinalize`), `retire_finalized_pools()` retires any imported
   pool whose `[lo, hi)` no longer overlaps a live `GuestPool` in `guest_pools` (`inherit = false`), drops its `tex_spans`
   and `shadow` pages, and notifies `texture_pool_finalized(lo, hi)` so one-frame `gpu_written` textures in dead pools are
   marked `released = true` and `gpu_owned` entries in `[lo, hi)` are erased.
2. When `RX_VK_COMPACT` or `RX_VK_TARGET_BLOCKS` is on (and `RX_VK_IMAGE_PREALLOC` is unset), `images_pool()` does not
   preallocate 15% of VRAM (`9` blocks = 1,152 MB on an 8 GB GPU) for the handful of utility/DLSS images left in `image_pool`.
3. `cap_spare_max()` caps spare capture buffers at 128 MB by default above 6 GB VRAM (32 MB on <=6 GB), prewarms 32 and 64 MB
   on first capture, and retires kept `cap_bufs` entries unused for >120 submissions when `cap_bytes > 96 MB`.

python -I -B tests/test_finalized_pools_and_vma_prealloc.py
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class FinalizedPoolsAndVmaPreallocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mem = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
        cls.tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
        cls.hdr = (ROOT / "gpu" / "vk" / "vk_texture.h").read_text(encoding="utf-8")
        cls.vma = (ROOT / "gpu" / "vk" / "vk_vma.cpp").read_text(encoding="utf-8")

    def test_finalized_pools_are_retired_without_inheriting_and_release_their_textures(self):
        retire_fn = block(self.mem, "void retire_finalized_pools()")
        self.assertIn('env_on("RX_VK_KEEP_FINALIZED_POOLS")', retire_fn)
        self.assertIn("guest_pools_gen.load", retire_fn)
        self.assertIn("retire_pool(cur, false);", retire_fn)
        self.assertIn("shadow_drop_range(lo, hi);", retire_fn)
        self.assertIn("texture_pool_finalized(lo, hi);", retire_fn)

        begin = block(self.mem, "void memory_begin_submission() {")
        self.assertLess(begin.index("retire_finalized_pools();"), begin.index("retired_imports_give_back();"))

        self.assertIn("void texture_pool_finalized(uint64_t lo, uint64_t hi);", self.hdr)
        tex_fn = block(self.tex, "void texture_pool_finalized(uint64_t lo, uint64_t hi) {")
        self.assertIn("gpu_owned.erase(it)", tex_fn)
        self.assertIn("t->released = true;", tex_fn)

    def test_images_pool_does_not_preallocate_when_textures_and_targets_have_their_own_pools(self):
        pool = block(self.vma, "VmaPool images_pool() {")
        self.assertIn('getenv("RX_VK_IMAGE_PREALLOC")', pool)
        self.assertIn("split ? 0 :", pool)

    def test_capture_spares_and_stale_capture_buffers_are_bounded(self):
        spare = block(self.mem, "uint64_t cap_spare_max() {")
        self.assertIn('getenv("RX_VK_CAP_SPARE_MB")', spare)
        self.assertIn("32ull << 20 : 128ull << 20", spare)

        get_fn = block(self.mem, "bool cap_buf_get(")
        self.assertIn("for (uint64_t c : {32ull << 20, 64ull << 20}) cap_prewarm_class(c);", get_fn)

        take_fn = block(self.mem, "bool take_capture(")
        self.assertIn("cap_bytes > (96ull << 20) && last_val + 120 <= completed", take_fn)


if __name__ == "__main__":
    unittest.main()
