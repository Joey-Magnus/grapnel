"""A Quality preset's VRAM budget stays within the renderer's own rule, and no preset sets the Profile.

The presets' budgets were 2.2 / 3.6 / 4.8 / 7.5 / 11 GB, past what Auto gives the card each is named for (gpu/vk/vk_texture.cpp
texture_frame: 45% of what the driver allows on 8 GB or less, 70% above, at most 6 GB): 4.8 GB on an 8 GB card is the 5.1 GB
that paged an RTX 3060 Ti and #1400's RTX 4050, 11 GB on a 16 GB card the fill-up of #105. Minimum keeps 2.2 GB, which #1358
measured as right for a 4 GB card (Auto's 1.5 GB evicted Kokiri Forest's textures). Minimum and Low also set the handheld
profile, which gave a GTX 1050 a black picture, so the first start kept docked while the menu's own choice did not. Read the
tables and apply_preset from gpu/vk/vk_menu.cpp and check both. No game or GPU is needed.

python -I -B tests/test_preset_budget_caps.py
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO_CAP_MB = 6144   # (texture_frame: at most 6 GB)
EIGHT_GB_AUTO_MB = 3600   # (45% of the ~7.3 GB an 8 GB card's driver allows is 3.3 GB: the row's stop nearest above it)
MINIMUM_MB = 2200   # (#1358: a 4 GB card needs it)


def block(text, start):
    opening = text.index("{", start)
    depth = 0
    for at in range(opening, len(text)):
        depth += text[at] == "{"
        depth -= text[at] == "}"
        if depth == 0:
            return text[start:at + 1]
    raise SystemExit("unterminated block at %d" % start)


def int_list(text, name):
    match = re.search(re.escape(name) + r"[^=]*=\s*\{([^}]*)\}", text)
    if not match:
        raise SystemExit("%s: not found in vk_menu.cpp" % name)
    return [int(v) for v in re.findall(r"-?\d+", match.group(1))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    menu = (args.source / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    textures = int_list(menu, "constexpr int kVramTextureMb")
    of = int_list(block(menu, menu.index("int preset_vram_budget(int p)")), "static const int of[]")
    if len(of) != 6 or of[0] != 0:
        raise SystemExit("preset_vram_budget: six presets, Custom first, expected (%s)" % of)
    names = ["Custom", "Minimum (4GB)", "Low (6GB)", "Balanced (8GB)", "High (12GB)", "Ultra (16GB+)"]
    fail = []
    budgets = [textures[i] for i in of]
    for name, mb in zip(names[1:], budgets[1:]):
        if mb > AUTO_CAP_MB:
            fail.append("%s: %d MB of textures, past Auto's %d MB cap" % (name, mb, AUTO_CAP_MB))
    if budgets[1] != MINIMUM_MB:
        fail.append("Minimum (4GB): %d MB, not the %d MB a 4 GB card needs (#1358)" % (budgets[1], MINIMUM_MB))
    if budgets[3] > EIGHT_GB_AUTO_MB:
        fail.append("Balanced (8GB): %d MB, more than the %d MB Auto's 45%% rule gives an 8 GB card" % (budgets[3], EIGHT_GB_AUTO_MB))
    if budgets != sorted(budgets):
        fail.append("the presets' budgets do not grow with the preset: %s" % budgets)
    preset = block(menu, menu.index("void apply_preset(int p)"))
    if re.search(r"opts\.handheld\s*=(?!=)", preset):
        fail.append("apply_preset sets opts.handheld: the Profile is the player's (a GTX 1050 got a black picture from it)")
    if fail:
        raise SystemExit("FAIL:\n  " + "\n  ".join(fail))
    print("PASS: the presets' texture budgets %s MB stay within Auto's rule; no preset sets the Profile" % budgets[1:])


if __name__ == "__main__":
    main()
