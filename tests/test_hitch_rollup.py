"""Slow submits and presents keep a ranked rollup after the per-event log stops.

Checked here: SlowWatch still ignores work under 15 ms and the first 600 presents, still logs
`vk: slow`, and calls hitch_note before the 80-line cap so `vk: hitch rollup` keeps ranking the
phase that took the time.

No Vulkan, GPU or game. python -I -B tests/test_hitch_rollup.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    note = replay.find("void hitch_note(")
    watch = replay.find("~SlowWatch()")
    if note < 0 or watch < 0 or note > watch:
        raise SystemExit("FAIL: hitch_note is not defined before SlowWatch")
    body = replay[watch:replay.find("void submit_memory_work(", watch)]
    gate = body.find("ms < 15.0 || presents_now < 600")
    call = body.find("hitch_note(")
    cap = body.find("logged >= 80")
    if gate < 0 or call < 0 or cap < 0 or not (gate < call < cap):
        raise SystemExit("FAIL: hitch_note must run after the 15 ms / 600 present gate and before the 80-line cap")
    if "vk: slow %s:" not in body:
        raise SystemExit("FAIL: per-event vk: slow line is gone")
    if 'logf("vk: hitch rollup:' not in replay:
        raise SystemExit("FAIL: vk: hitch rollup line is gone")
    if "hitch.n % 10" not in replay:
        raise SystemExit("FAIL: rollup is not printed every 10 slow submits")
    print("PASS: hitch rollup ranks slow submits after the per-event cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
