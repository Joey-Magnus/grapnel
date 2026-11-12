"""Prepare progress lines name workers, rate and RSS so player logs diagnose slow builds.

The 10 s lines used to print only done/total/ETA. Near the end the overall ETA blew up (thousands of minutes while
almost finished), and the log never said how many workers or how much RAM the process held — so "all CPUs busy and
near out of memory" could not be confirmed from hookshot_log.txt alone.

Checked here: prepare_progress_log takes a worker count; predict_run and precompile_run pass it; the log format keeps
rate (/s), workers, and RSS; near-complete runs say "finishing" instead of a runaway ETA.

No Vulkan, GPU or game. python -I -B tests/test_prepare_progress_stats.py
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DRAW = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")


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


def main():
    sig = "void prepare_progress_log(const char* what, size_t done, size_t total, std::chrono::steady_clock::time_point t0,"
    if sig not in DRAW:
        raise SystemExit("FAIL: prepare_progress_log signature missing")
    prog = body(DRAW, "void prepare_progress_log(")
    if "unsigned workers" not in prog:
        raise SystemExit("FAIL: prepare_progress_log does not take a worker count")
    if '%.1f/s' not in prog and "%.1f/s" not in prog:
        raise SystemExit("FAIL: prepare_progress_log does not log pipelines/s")
    if "RSS" not in prog:
        raise SystemExit("FAIL: prepare_progress_log does not log RSS")
    if "finishing" not in prog:
        raise SystemExit("FAIL: prepare_progress_log has no finishing ETA near the end")
    if "prepare_mem_mb" not in DRAW:
        raise SystemExit("FAIL: prepare_mem_mb helper missing")

    for fn, label in (("void predict_run(", "predicted pipelines"), ("void precompile_run(", "noted pipelines")):
        text = body(DRAW, fn)
        call = 'prepare_progress_log("%s"' % label
        if call not in text:
            raise SystemExit("FAIL: %s does not call prepare_progress_log for %r" % (fn.split("(")[0], label))
        if not re.search(r"prepare_progress_log\(\"%s\"[^;]*workers\)" % re.escape(label), text, re.S):
            raise SystemExit("FAIL: %s does not pass workers into prepare_progress_log" % fn.split("(")[0])
        if "building %zu on %u workers" not in text:
            raise SystemExit("FAIL: %s does not log its worker count at the start" % fn.split("(")[0])

    prep = body(DRAW, "bool prepare_run(")
    if "preparing shaders on %u workers" not in prep:
        raise SystemExit("FAIL: prepare_run does not log its worker count at the start")

    print("PASS: prepare progress lines name workers, rate and RSS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
