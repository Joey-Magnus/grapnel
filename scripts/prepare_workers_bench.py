"""A/B the prepare's worker count and write hookshot_prepare_workers.txt for the next start.

Part 1 self-test from the measurement plan: run `hookshot --prepare-shaders` at several
HOOKSHOT_SHADER_WORKERS values, parse wall time and process peak from hookshot_log.txt, pick the
fastest count that stays under a peak working-set cap, and write that count beside the game.

Fair pipe/s needs a cold-ish driver shader cache between runs (NVIDIA/AMD control panel, or delete
the driver's VkCache folder named in the log). Warm runs still rank relative cost. Explicit
HOOKSHOT_SHADER_WORKERS always wins over the written file.

    python -I scripts/prepare_workers_bench.py --game D:\\Hookshot_OOT --workers 4,8,12,16,24
    python -I scripts/prepare_workers_bench.py --game D:\\Hookshot_OOT --parse-only

No game files are copied. Standard library only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

PREDICT_DONE = re.compile(
    r"predicted pipelines:\s+(\d+)\s+of\s+(\d+)\s+pipelines in\s+(\d+(?:\.\d+)?)\s+s",
    re.I,
)
PREPARE_DONE = re.compile(
    r"prepared\s+(\d+)\s+shader programs.*?in\s+(\d+(?:\.\d+)?)\s+s",
    re.I,
)
RESOURCES = re.compile(
    r"prepare resources.*process\s+(\d+)\s+MB\s+\(peak\s+(\d+)\)",
    re.I,
)
MEMORY = re.compile(
    r"memory:\s+working set\s+(\d+)\s+MB\s+\(peak\s+(\d+)\)",
    re.I,
)
WORKERS = re.compile(
    r"(?:preparing shaders|predicted pipelines: building|noted pipelines: building).*?\bon\s+(\d+)\s+workers\s+\(([^)]+)\)",
    re.I,
)


def game_exe(game: Path) -> Path:
    for cand in (game / "bin" / "hookshot.exe", game / "hookshot.exe", game / "bin" / "hookshot", game / "hookshot"):
        if cand.is_file():
            return cand
    raise SystemExit("no hookshot executable under %s" % game)


def log_path(game: Path) -> Path:
    return game / "hookshot_log.txt"


def workers_file(game: Path) -> Path:
    return game / "hookshot_prepare_workers.txt"


def parse_log(text: str) -> dict:
    out = {
        "predict_done": None,
        "predict_total": None,
        "predict_s": None,
        "prepare_programs": None,
        "prepare_s": None,
        "process_peak_mb": None,
        "workers": None,
        "workers_why": None,
    }
    for m in PREDICT_DONE.finditer(text):
        out["predict_done"] = int(m.group(1))
        out["predict_total"] = int(m.group(2))
        out["predict_s"] = float(m.group(3))
    for m in PREPARE_DONE.finditer(text):
        out["prepare_programs"] = int(m.group(1))
        out["prepare_s"] = float(m.group(2))
    for m in RESOURCES.finditer(text):
        out["process_peak_mb"] = int(m.group(2))
    for m in MEMORY.finditer(text):
        out["process_peak_mb"] = int(m.group(2))
    for m in WORKERS.finditer(text):
        out["workers"] = int(m.group(1))
        out["workers_why"] = m.group(2).strip()
    if out["predict_s"] and out["predict_done"]:
        out["pipe_per_s"] = out["predict_done"] / out["predict_s"]
    else:
        out["pipe_per_s"] = None
    return out


def rotate_log(game: Path) -> None:
    log = log_path(game)
    if not log.is_file():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = game / ("hookshot_log.bench-%s.txt" % stamp)
    shutil.move(str(log), str(dest))
    print("moved prior log to %s" % dest.name, flush=True)


def run_one(game: Path, exe: Path, workers: int, timeout: int) -> dict:
    env = os.environ.copy()
    env["HOOKSHOT_SHADER_WORKERS"] = str(workers)
    # (bench must not pick up a previous file recommendation or RAM guard while measuring)
    env.pop("HOOKSHOT_PREPARE_RAM_GUARD", None)
    env.pop("RX_VK_PREPARE_RAM_GUARD", None)
    env.pop("RX_VK_PREPARE_WORKERS", None)
    rotate_log(game)
    cmd = [str(exe), "--prepare-shaders"]
    print("\n=== workers=%d: %s ===" % (workers, " ".join(cmd)), flush=True)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(game), env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("TIMEOUT after %d s" % timeout, flush=True)
        proc = None
    wall = time.time() - t0
    text = log_path(game).read_text(encoding="utf-8", errors="replace") if log_path(game).is_file() else ""
    stats = parse_log(text)
    stats["wall_s"] = wall
    stats["exit"] = None if proc is None else proc.returncode
    stats["asked_workers"] = workers
    print(
        "exit=%s wall=%.1fs predict=%s/%s in %ss (%.1f pipe/s) peak_ws=%s why=%s"
        % (
            stats["exit"],
            wall,
            stats["predict_done"],
            stats["predict_total"],
            stats["predict_s"],
            stats["pipe_per_s"] or 0.0,
            stats["process_peak_mb"],
            stats.get("workers_why"),
        ),
        flush=True,
    )
    return stats


def choose(rows: list[dict], max_peak_mb: int | None) -> dict | None:
    ok = [r for r in rows if r.get("pipe_per_s")]
    if max_peak_mb is not None:
        capped = [r for r in ok if r.get("process_peak_mb") is None or r["process_peak_mb"] <= max_peak_mb]
        if capped:
            ok = capped
    if not ok:
        return None
    return max(ok, key=lambda r: (r["pipe_per_s"], -r["asked_workers"]))


def write_choice(game: Path, workers: int, note: str) -> None:
    path = workers_file(game)
    path.write_text("workers=%d\n# %s\n" % (workers, note), encoding="utf-8")
    print("wrote %s" % path, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", type=Path, required=True, help="game folder (image.bin / hookshot_log.txt)")
    ap.add_argument("--workers", default="4,8,12,16,24", help="comma-separated HOOKSHOT_SHADER_WORKERS values")
    ap.add_argument("--timeout", type=int, default=7200, help="seconds per prepare run")
    ap.add_argument("--max-peak-mb", type=int, default=0, help="reject runs whose process peak exceeds this (0: no cap)")
    ap.add_argument("--parse-only", action="store_true", help="only parse the current hookshot_log.txt")
    ap.add_argument("--write", type=int, default=0, help="write this worker count to hookshot_prepare_workers.txt and exit")
    a = ap.parse_args()
    game = a.game.resolve()
    if not game.is_dir():
        raise SystemExit("game folder not found: %s" % game)
    if a.write:
        write_choice(game, a.write, "manual")
        return 0
    if a.parse_only:
        text = log_path(game).read_text(encoding="utf-8", errors="replace")
        stats = parse_log(text)
        print(stats)
        return 0
    exe = game_exe(game)
    counts = [int(x) for x in a.workers.split(",") if x.strip()]
    if not counts:
        raise SystemExit("no --workers values")
    rows = [run_one(game, exe, n, a.timeout) for n in counts]
    print("\n=== summary ===", flush=True)
    print("%8s %10s %10s %10s %8s" % ("workers", "pipe/s", "predict_s", "peak_MB", "exit"), flush=True)
    for r in rows:
        print(
            "%8d %10s %10s %10s %8s"
            % (
                r["asked_workers"],
                ("%.1f" % r["pipe_per_s"]) if r["pipe_per_s"] else "-",
                ("%.0f" % r["predict_s"]) if r["predict_s"] is not None else "-",
                r["process_peak_mb"] if r["process_peak_mb"] is not None else "-",
                r["exit"],
            ),
            flush=True,
        )
    cap = a.max_peak_mb or None
    best = choose(rows, cap)
    if not best:
        print("no usable run to recommend", flush=True)
        return 1
    note = "bench pipe/s=%.1f peak=%s on %s" % (
        best["pipe_per_s"],
        best["process_peak_mb"],
        time.strftime("%Y-%m-%d"),
    )
    write_choice(game, best["asked_workers"], note)
    print("recommended workers=%d (%s)" % (best["asked_workers"], note), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
