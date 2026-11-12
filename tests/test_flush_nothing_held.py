"""A flush with no submit held does not take dev.present_mu (gpu/vk/vk_replay.cpp's queue_flush_for, queue_flush_poll).

A present holds dev.present_mu for as long as it takes (4 ms a frame in Hyrule Field). Held submits exist only with batched
submits (RX_VK_BATCH, on with RADV), but every flush took the mutex to find that out: a readback whose recording was long
done, and the host's copy bookkeeping asking how far the replay is under its own lock (rx_nvn_replayed), waited there for
the present, and the game's other job threads behind them. pend_held says whether anything is held. Reads the source:

  - both flushes test it before they take the mutex;
  - submit_recording raises it before its recording is in value_rec / part_rec (a thread that finds the recording there
    and waits for it must not skip the flush), and again once the submit is in the list, under the mutex (a flush of
    older ones may have come in between);
  - only queue_flush_locked lowers it, after it has sent what was held.

python -I -B tests/test_flush_nothing_held.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(src, signature):
    """the text of the function that starts with signature, up to its closing brace at column 0"""
    start = src.index(signature)
    return src[start:src.index("\n}\n", start)]


def main():
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    test = "if (!pend_held.load(std::memory_order_acquire)) return;"
    for name in ("void queue_flush_for(int why) {", "void queue_flush_poll() {"):
        f = body(replay, name)
        if test not in f or f.index(test) > f.index("std::lock_guard lk(dev.present_mu);"):
            raise SystemExit("%s takes dev.present_mu before it knows a submit is held" % name.split("(")[0][5:])
    submit = body(replay, "void submit_recording(")
    up = "pend_held.store(true, std::memory_order_release);"
    first = submit.index(up)
    if first > submit.index("std::lock_guard mk(rec_map_mu);"):
        raise SystemExit("submit_recording says a submit is held only after its recording is in the maps: a thread that "
                         "waits for it in between skips the flush its wait needs")
    if "if (batch_on()) " + up not in submit:
        raise SystemExit("submit_recording raises pend_held without batched submits: every flush takes the mutex again")
    again = submit.index(up, first + 1)
    push = submit.index("pend.cbs.push_back(cb[i]);")
    if not submit.index("std::lock_guard lk(dev.present_mu);") < push < again:
        raise SystemExit("submit_recording does not raise pend_held again once the submit is in the list, under the mutex")
    lowered = "pend_held.store(false, std::memory_order_release);"
    if replay.count(lowered) != 1:
        raise SystemExit("pend_held is lowered somewhere else than queue_flush_locked")
    flush = body(replay, "void queue_flush_locked() {")
    if lowered not in flush or flush.index(lowered) < flush.index("pend.cbs.clear()"):
        raise SystemExit("queue_flush_locked lowers pend_held before it has sent what was held")
    print("PASS: a flush with nothing held leaves dev.present_mu alone, and a held submit is known before it can be waited for")


if __name__ == "__main__":
    main()
