"""Menu size is Small, Medium or Large, Medium by default, whatever the input:

    python -I -B tests/test_menu_size.py [--cxx g++]

It was Auto by default, Large in fullscreen at 1080 lines and up while a controller opened the menu: the menu changed size
with the input that opened it. And the banner's version, too long beside five tabs for a source build, shrinks to fit at
Small and Medium (vk_ui.h fit_px) instead of going. gpu/vk/vk_ui.h's unit and fit_px and vk_menu.cpp's tx_menu_size, cut out
and compiled; the rest read from the source. Game-free.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    ui = (ROOT / "gpu/vk/vk_ui.h").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")

    check("int menu_size = 2;" in header, "Menu size is not Medium by default")
    check('"Menu size", &opts.menu_size, 1, 3, 1,' in menu, "the Menu size row is not Small to Large")
    check("auto_pad" not in menu and "auto_large" not in menu, "Menu size still follows the input")
    init = block(menu, "void menu_init(")
    check('!strcmp(line, "menu_size") && atoi(eq + 1) == 0' in init and "if (menu_auto) opts.menu_size = 2;" in init,
          "an options file's menu_size=0 (Auto) does not load as Medium")

    head = block(menu, "MenuHeader menu_header(")
    draw = block(menu, "void draw_options(")
    check("const MenuHeader mh = menu_header(c);" in draw and "mh.text.c_str()" in draw and "if (fit > 0)" not in draw,
          "the banner's header (icon and version) is not always drawn")
    check("ui::logo(&aspect)" in draw and "AddImage(icon->GetTexRef()" in draw, "the banner's header has no icon")
    check('{"Hookshot " + full, full, release}' in head, "the header does not give up \"Hookshot \" before the git suffix")
    check("std::max((c.w - total) * 0.5f, mh.end + keys_w)" in draw, "the tabs do not start after the header")
    check("kVersionMinPt" not in menu, "the version still has a size under which it is hidden")

    src = "#include <cmath>\n#include <cstdio>\n#include <cstring>\n" + block(ui, "inline float unit(") + "\n" + \
          "#include <string>\n" + \
          "template <class Width>\n" + block(ui, "float fit_px(") + "\n" + block(menu, "const char* tx_menu_size(") + "\n" + \
          block(menu, "std::string version_release(") + r'''
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
// (a stand-in font: a text n characters long, 0.5 em a character, its glyphs rounded up to whole pixels as an atlas's are)
static float width_of(int n, float px) { return n * std::ceil(px * 0.5f); }
int main() {
    {   // (shrink to fit: at its size when it fits; else the largest half-point step that fits; 0 below the least)
        const float s = 1.5f, px = 15 * s;   // (Medium at 1080 lines)
        auto release = [](float p) { return width_of(16, p); };   // ("Hookshot v2.0.12": as it was)
        CHECK(fit_px(px, 10 * s, 0.5f * s, 317, release) == px);
        auto source = [](float p) { return width_of(35, p); };    // ("Hookshot v2.0.11-821-g7b81752-dirty")
        const float f = fit_px(px, 10 * s, 0.5f * s, 317, source);
        CHECK(f > 0 && f < px && source(f) <= 317 && source(f + 0.5f * s) > 317);   // (the largest step that fits)
        CHECK(std::fabs(f / (0.5f * s) - std::round(f / (0.5f * s))) < 1e-3f);    // (on a step)
        CHECK(fit_px(px, 10 * s, 0.5f * s, 100, source) == 0);   // (it would be under 10 points: not drawn)
        CHECK(fit_px(px, px, 0.5f * s, 317, source) == 0);        // (Large: at its size or not at all)
        CHECK(fit_px(px, px, 0.5f * s, 317, release) == px);
        CHECK(fit_px(px, 10 * s, 0.5f * s, 0, source) == 0 && fit_px(px, 10 * s, 0, 317, source) == 0);
        auto rounding = [](float p) { return 8 * std::ceil(p * 0.5f) + 3; };   // (rounding past the first guess: steps on down)
        const float g = fit_px(px, 10 * s, 0.5f * s, 70, rounding);
        CHECK(g > 0 && rounding(g) <= 70);
    }
    // (the header's shortest version: the release, the git suffix past it cut to "...", the source note gone)
    CHECK(version_release("v2.1.0-rc.3-95-g2ed98c4-dirty") == "v2.1.0-rc.3...");
    CHECK(version_release("v2.1.0-rc.3-95-g2ed98c4-dirty (source e939301d)") == "v2.1.0-rc.3...");
    CHECK(version_release("v2.0.11-821-g7b81752") == "v2.0.11...");
    CHECK(version_release("v2.0.12") == "v2.0.12" && version_release("v2.0.12 (x)") == "v2.0.12");
    CHECK(version_release("v2.0-gold") == "v2.0-gold");   // (a -g not after "-<count>": not a git suffix)
    float m = 0;
    CHECK(unit(1080, 2, &m) == 1.5f && m == 1080 * 0.025f);    // (Medium)
    CHECK(unit(1080, 0, &m) == 1.5f && m == 1080 * 0.025f);    // (an older file's Auto, or anything else: Medium)
    CHECK(unit(1080, 7, &m) == 1.5f);
    CHECK(unit(2160, 3, &m) == 2160 / 720.0f * 1.3f && m == 2160 * 0.05f);   // (Large)
    CHECK(unit(720, 1, &m) == 0.85f);   // (Small)
    CHECK(!strcmp(tx_menu_size(1), "Small") && !strcmp(tx_menu_size(2), "Medium") && !strcmp(tx_menu_size(3), "Large"));
    CHECK(!strcmp(tx_menu_size(0), "Medium") && !strcmp(tx_menu_size(4), "Medium"));
    printf("menu size: Small, Medium, Large; Medium otherwise, whatever the input; the header's version shortens to fit\n");
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="menu-size-") as tmp:
        path = Path(tmp) / "menu_size.cpp"
        path.write_text(src, encoding="utf-8")
        exe = Path(tmp) / "menu_size.exe"
        subprocess.run([a.cxx, "-std=c++17", "-Wall", "-Werror", "-o", str(exe), str(path)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        check(r.returncode == 0, "menu_size.cpp: " + r.stderr.strip())
    print("ok")


if __name__ == "__main__":
    main()
