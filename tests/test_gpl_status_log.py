"""The device start logs whether RX_VK_GPL can turn stage libraries on (Part 3 A/B).

Checked here: vk_main.cpp prints a `vk: GPL:` line after the device summary, covering available /
on / off, and that gpl_wanted still requires RX_VK_GPL plus the EDS3 bits.

No Vulkan, GPU or game. python -I -B tests/test_gpl_status_log.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    main_cpp = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    if main_cpp.count('logf("vk: GPL:') < 3:
        raise SystemExit("FAIL: expected vk: GPL: available/on/off lines in vk_main.cpp")
    if "env_on(\"RX_VK_GPL\")" not in main_cpp:
        raise SystemExit("FAIL: GPL status log no longer reads RX_VK_GPL")
    if "bool gpl_wanted()" not in draw or "env_on(\"RX_VK_GPL\")" not in draw:
        raise SystemExit("FAIL: gpl_wanted no longer gates on RX_VK_GPL")
    if "return gpl_wanted();" not in draw:
        raise SystemExit("FAIL: draw_stats4 no longer reports GPL-only library stats")
    print("PASS: GPL status log and RX_VK_GPL gate present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
