"""prepare_pool_workers keeps the old auto sizes and honours HOOKSHOT_SHADER_WORKERS / RX_VK_PREPARE_WORKERS.

The prepare's translate pool used half the usable CPUs; predicted/noted pipelines used every usable CPU; in-play
background translation used a quarter (2 to 4). Those stay the default. An override sets every pool to the same count
so players can A/B fewer workers when RAM is tight (Part 1), without a rebuild. HOOKSHOT_PREPARE_RAM_GUARD (opt-in) caps
the auto sizes by available RAM; a critical floor still applies under 2 GB even without it.

Checked here: prepare_pool_workers, extracted unmodified, against a stand-in mask, env and RAM; and that prepare_run,
predict_run, precompile_run, warm_libraries and state_list_prepare size their pools through it.

No Vulkan, GPU or game. python -I -B tests/test_prepare_pool_workers.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
ENV_H = ROOT / "gpu/vk/compat/hookshot_env.h"


def _with_cache(path):
    parts = [path.read_text(encoding="utf-8")]
    for name in ("vk_progcache.cpp", "vk_progcache.h"):
        if (path.parent / name).exists():
            parts.append((path.parent / name).read_text(encoding="utf-8"))
    return "\n".join(parts)


def body(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: expected one %r" % marker)
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


CHECK = r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "hookshot_env.h"
typedef uintptr_t DWORD_PTR;
typedef void* HANDLE;
static unsigned fake_hw = 24;
static uint64_t fake_mask = 0;
static bool fake_ok = true;
static uint64_t fake_avail_mb = 32000;
static uint64_t fake_total_mb = 32000;
static HANDLE GetCurrentProcess() { return (HANDLE)(intptr_t)-1; }
static int GetProcessAffinityMask(HANDLE, DWORD_PTR* proc, DWORD_PTR* sys) {
    *proc = (DWORD_PTR)fake_mask, *sys = ~(DWORD_PTR)0;
    return fake_ok;
}
// (stand-in: the real prepare_ram_mb reads GlobalMemoryStatusEx /proc; here the test drives avail/total)
void prepare_ram_mb(uint64_t* avail_mb, uint64_t* total_mb) {
    if (avail_mb) *avail_mb = fake_avail_mb;
    if (total_mb) *total_mb = fake_total_mb;
}
static void clear_overrides() {
#ifdef _WIN32
    _putenv("HOOKSHOT_SHADER_WORKERS=");
    _putenv("RX_VK_PREPARE_WORKERS=");
    _putenv("HOOKSHOT_PREPARE_RAM_GUARD=");
    _putenv("RX_VK_PREPARE_RAM_GUARD=");
    _putenv("HOOKSHOT_PREPARE_WORKER_MB=");
    _putenv("HOOKSHOT_PREPARE_RESERVE_MB=");
    _putenv("HOOKSHOT_MEM_RESERVE_GB=");
#else
    unsetenv("HOOKSHOT_SHADER_WORKERS");
    unsetenv("RX_VK_PREPARE_WORKERS");
    unsetenv("HOOKSHOT_PREPARE_RAM_GUARD");
    unsetenv("RX_VK_PREPARE_RAM_GUARD");
    unsetenv("HOOKSHOT_PREPARE_WORKER_MB");
    unsetenv("HOOKSHOT_PREPARE_RESERVE_MB");
    unsetenv("HOOKSHOT_MEM_RESERVE_GB");
#endif
}
static void set_env(const char* name, const char* value) {
    char buf[128];
    std::snprintf(buf, sizeof buf, "%s=%s", name, value ? value : "");
#ifdef _WIN32
    _putenv(buf);
#else
    if (!value || !*value) unsetenv(name);
    else setenv(name, value, 1);
#endif
}
#include "cpus.inc"
#define CHECK(c) do { if (!(c)) { std::printf("CHECK failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)
int main() {
    clear_overrides();
    fake_hw = 24, fake_mask = (1ull << 24) - 1, fake_avail_mb = 32000, fake_total_mb = 32000;
    const char* why = nullptr;
    CHECK(prepare_pool_workers(PreparePool::Translate, &why) == 12 && why && !std::strcmp(why, "auto half"));
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 24 && why && !std::strcmp(why, "auto usable"));
    CHECK(prepare_pool_workers(PreparePool::Background, &why) == 4 && why && !std::strcmp(why, "auto background"));
    set_env("HOOKSHOT_SHADER_WORKERS", "8");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 8 && why && !std::strcmp(why, "HOOKSHOT_SHADER_WORKERS"));
    CHECK(prepare_pool_workers(PreparePool::Translate, &why) == 8);
    clear_overrides();
    set_env("RX_VK_PREPARE_WORKERS", "3");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 3 && why && !std::strcmp(why, "RX_VK_PREPARE_WORKERS"));
    set_env("RX_VK_PREPARE_WORKERS", "0");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 1);   // (clamp: never none)
    set_env("RX_VK_PREPARE_WORKERS", "99");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 64);  // (clamp: at most 64)
    clear_overrides();
    fake_mask = 0x3F;   // (6 usable)
    CHECK(prepare_pool_workers(PreparePool::Translate, &why) == 6);
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 6);
    // (RAM guard: room 5000-2000 = 3000 MB / 500 MB = 6 workers, below auto usable 24)
    fake_hw = 24, fake_mask = (1ull << 24) - 1, fake_avail_mb = 5000, fake_total_mb = 16000;
    set_env("HOOKSHOT_PREPARE_RAM_GUARD", "1");
    set_env("HOOKSHOT_PREPARE_RESERVE_MB", "2000");
    set_env("HOOKSHOT_PREPARE_WORKER_MB", "500");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 6 && why && !std::strcmp(why, "RAM guard"));
    // (override still wins over the guard)
    set_env("HOOKSHOT_SHADER_WORKERS", "10");
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 10 && why && !std::strcmp(why, "HOOKSHOT_SHADER_WORKERS"));
    clear_overrides();
    // (critical floor under 1 GB even without the guard)
    fake_avail_mb = 800;
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 1 && why && !std::strcmp(why, "RAM critical"));
    fake_avail_mb = 1500;
    CHECK(prepare_pool_workers(PreparePool::Pipelines, &why) == 2 && why && !std::strcmp(why, "RAM low"));
    std::printf("prepare_pool_workers: ok\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default=os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++") or "g++")
    a = p.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    shader = _with_cache(ROOT / "gpu/vk/vk_shader.cpp")
    pieces = [
        "#include <cstdlib>\n#include \"hookshot_env.h\"\n",
        "enum class PreparePool : unsigned { Translate, Pipelines, Background };\n",
        "void prepare_ram_mb(uint64_t* avail_mb, uint64_t* total_mb);\n",
        body(shader, "unsigned usable_cpus() {"),
        body(shader, "unsigned half_cpus() {"),
        body(shader, "static unsigned prepare_worker_peak_mb()"),
        body(shader, "static unsigned prepare_reserve_mb("),
        body(shader, "static bool prepare_ram_guard_on()"),
        body(shader, "unsigned prepare_pool_workers("),
    ]
    code = "\n".join(pieces).replace("std::thread::hardware_concurrency()", "fake_hw")
    if "fake_hw" not in code:
        raise SystemExit("FAIL: prepare pool helpers no longer read the PC's CPU count")
    if "RAM guard" not in code:
        raise SystemExit("FAIL: prepare_pool_workers no longer applies the RAM guard")

    for fn in ("bool prepare_run(", "void state_list_prepare(", "bool warm_libraries(", "void predict_run(",
               "void precompile_run("):
        text = body(draw, fn)
        if "prepare_pool_workers(" not in text:
            raise SystemExit("FAIL: %s does not size its workers by prepare_pool_workers" % fn.split("(")[0])
        if "const unsigned cpus = std::max(1u, std::thread::hardware_concurrency());" in text:
            raise SystemExit("FAIL: %s counts every CPU of the PC, not those the process may use" % fn.split("(")[0])

    with tempfile.TemporaryDirectory(prefix="hookshot-prepare-pool-") as temp:
        temp = Path(temp)
        (temp / "hookshot_env.h").write_text(ENV_H.read_text(encoding="utf-8"), encoding="utf-8")
        (temp / "cpus.inc").write_text(code + "\n", encoding="utf-8")
        (temp / "check.cpp").write_text(CHECK, encoding="utf-8")
        exe = temp / ("check.exe" if os.name == "nt" else "check")
        # (-D_CRT_SECURE_NO_WARNINGS: MSVC CRT marks getenv deprecated under -Werror on Windows CI)
        cmd = [a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
               "-D_CRT_SECURE_NO_WARNINGS", "-I" + str(temp), str(temp / "check.cpp"), "-o", str(exe)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode:
            print(result.stdout + result.stderr)
            return 1
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        sys.stdout.write(run.stdout + run.stderr)
        if run.returncode:
            return 1
    print("PASS: prepare_pool_workers keeps auto sizes, overrides and the RAM guard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
