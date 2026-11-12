"""Frames whose uploads take over 50 ms keep a ranked rollup after the per-frame log stops.

Checked here: upload_frame_report still logs `vk: a frame's uploads took` under the 300-line cap, and
calls the `vk: upload rollup` ranking on the first such frame and every 10, outside that cap.

No Vulkan, GPU or game. python -I -B tests/test_upload_rollup.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    text = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    start = text.find("void upload_frame_report()")
    end = text.find("bool upload_inner(", start)
    if start < 0 or end < 0:
        raise SystemExit("FAIL: upload_frame_report is missing")
    body = text[start:end]
    roll = body.find('vk: upload rollup:')
    cap = body.find("logged < 300")
    if roll < 0 or cap < 0 or roll > cap:
        raise SystemExit("FAIL: upload rollup must be logged before the 300-line cap")
    if "ns >= 50000000" not in body[:roll]:
        raise SystemExit("FAIL: upload rollup no longer waits for a frame over 50 ms")
    if "acc.n == 1 || acc.n % 10 == 0" not in body:
        raise SystemExit("FAIL: upload rollup is not printed on the first frame and every 10")
    if 'vk: a frame\'s uploads took' not in body:
        raise SystemExit("FAIL: per-frame upload line is gone")
    if "ASTC on the GPU" not in body or "unswizzled on the GPU" not in body or "on the CPU" not in body:
        raise SystemExit("FAIL: upload rollup routes are gone")
    print("PASS: upload rollup ranks ASTC, GPU unswizzle and CPU after the per-frame cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
