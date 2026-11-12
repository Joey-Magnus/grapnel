"""Compile and run the import trim's rules (gpu/vk/mirror_trim.h; no game/GPU required), and check that vk_memory.cpp still uses
them: a mirrored import mostly outside every game pool for long enough is retired and its live parts imported again with a
mirror wanted at once, each taking its part of the old mirror; nothing is trimmed unless the new mirrors fit the budget beside
the old one; RX_VK_MIRROR_TRIM=0 turns it off.

python -I -B tests/test_mirror_trim.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def order(where, text, needles):
    at = -1
    for needle in needles:
        nxt = text.find(needle, at + 1)
        if nxt < 0:
            raise SystemExit(where + " no longer has, in this order: " + needle)
        at = nxt


def check_source():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    need("vk_memory.cpp", mem, ['#include "mirror_trim.h"'])
    trim = block(mem, "bool mirrors_trim()")
    need("vk_memory.cpp: mirrors_trim()", trim,
         ['getenv("RX_VK_MIRROR_TRIM")', "mirror_trim::pressed(used, allowed)",
          "mirror_trim::live(p.lo, p.hi, chunk, mirror_trim::kJoin, guest_pools)", "mirror_trim::worth(p.hi - p.lo, parts)",
          "mirror_trim::counted(p.trims, mirror_epoch - p.trim_epoch)", "mirror_trim::wait(trims)",
          "mirror_trim::counted(pick->trims, mirror_epoch - pick->trim_epoch) + 1",
          # (only an import with a mirror, and never inside a parallel replay's segments)
          "p.mstate != Pool::MIRROR_ON", "par_active.load(std::memory_order_relaxed)",
          # (room for the new mirrors beside the old one, which stays until the GPU is done with it)
          "if (mirror_bytes + kept > mirror_budget()) return false;"])
    # (every live part is imported before anything is retired: a failed import leaves the old one as it was; then the old one is
    # retired, marked, and each part gets its flags, its page table entries and a mirror wanted now)
    order("vk_memory.cpp: mirrors_trim()", trim,
          ["if (!import_pool(r.lo, r.hi, np)) {", "retire_pool(imported.find(olo));", "retired_pools.back().mapped().trimmed = true;",
           "m.gpu_only = gpu_only, m.gpu_written = gpu_written, m.trims = trims, m.trim_epoch = mirror_epoch;",
           "guest_pages_set(it->second.lo, it->second.hi, it->second.address);", "it->second.mstate = Pool::MIRROR_WANTED;",
           "mirror_wanted.push_back(&it->second);"])
    # (the parts' mirrors are made in the same submission's uploads, before anything is recorded, and only then does the old
    # mirror stop waiting to be inherited)
    begin = block(mem, "void memory_begin_submission()")
    order("vk_memory.cpp: memory_begin_submission()", begin,
          ["const bool trimmed = mirrors_trim();", "for (Pool* p : mirror_wanted) mirror_make(*p);",
           "if (nh.mapped().trimmed) nh.mapped().trimmed = false, nh.mapped().inherit_pending = false;", "mirror_wanted.clear();"])
    # (a trimmed pool's mirror is inherited by each of its parts: the first does not end it)
    need("vk_memory.cpp: mirror_make()", block(mem, "bool mirror_make(Pool& pool) {"), ["if (!r.trimmed) r.inherit_pending = false;"])
    # (an import made again over trimmed ones remembers it, so the wait grows)
    need("vk_memory.cpp: pool_lookup()", block(mem, "Pool* pool_lookup(uint64_t guest, uint64_t size) {"),
         ["p.trims = std::max(p.trims, o->second.trims)", "p.trim_epoch = std::max(p.trim_epoch, o->second.trim_epoch)"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="mirror-trim-") as tmp:
        exe = Path(tmp) / "mirror-trim"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/test_mirror_trim.cpp"), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
