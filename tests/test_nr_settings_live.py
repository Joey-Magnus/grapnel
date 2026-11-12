#!/usr/bin/env python3
"""DLSS 5 neural rendering's settings: the mapping, and that nothing caches them.

Two bug classes are easy to write in this exact area, and this test is aimed at both.

The first: a backend that reads its switch once into a `static const` and then never looks again, so
every row in the menu does nothing and the feature looks dead. So this checks, in the source, that
each backend's asked() has no static of its own and goes through nr_settings() every call (NGX direct
here; tests/test_opennr_backend.py is the same check for the open backend).

The second: a row whose range does not match what the model accepts -- a Style of 7 where three
exist, a Preset default of 1 that silently pins preset A rather than letting the model choose
(docs/neural-rendering.md). So this checks every row's range and the defaults, and that the Backend
row's saved values are 0 Auto, 1 NGX direct, 2 Open in the menu, the enum and the environment's names.

The mapping itself is compiled from the real accessor, extracted and not retyped, so a change to
nr_settings() changes this test.

python -I -B tests/test_nr_settings_live.py [--cxx g++]
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
MENU_H = ROOT / "gpu" / "vk" / "vk_menu.h"
MENU_CPP = ROOT / "gpu" / "vk" / "vk_menu.cpp"
NR_NGX_CPP = ROOT / "gpu" / "vk" / "vk_dlssnr_ngx.cpp"   # (the NGX direct backend, and nr::, the front)
NR_NGX_H = ROOT / "gpu" / "vk" / "vk_dlssnr_ngx.h"

failures = []


def fail(message):
    failures.append(message)


def gone(what):
    """A marker this test needs is missing: that is a failure, never a silent pass."""
    raise SystemExit("%s is gone from the source: this test no longer checks what it says it does"
                     % what)


def block(text, marker, name):
    """The braced block beginning at marker."""
    if marker not in text:
        gone(name)
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


# ---------------------------------------------------------------- the mapping, compiled for real

PROGRAM = r"""
#include <cstdio>
#include <cmath>
#include "NR_PLAN_H"   // (the Passes row's count, as vk_menu.h includes it)
using namespace mkwvk;
static int bad;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL: %s\n", #c); ++bad; } } while (0)

struct Options {
    int nr = 0, nr_model = 2, nr_style = 0, nr_preset = 0;
    int nr_intensity = 100, nr_local_tone = 100, nr_local_structure = 100, nr_global_tone = 100;
    int nr_skin = 100, nr_auto_mask = 0;
    int nr_passes = 1, nr_scale = 100;
};
static Options opts;

__STRUCT__
__ACCESSOR__

static bool near(float a, float b) { return std::fabs(a - b) < 1e-6f; }

int main() {
    // The quality field is NVIDIA's DLSS mode number, which is what DLSS-NR takes: 1 performance,
    // 2 balanced, 3 quality, 6 DLAA. Not the row's index.
    const unsigned want[4] = {1u, 2u, 3u, 6u};
    for (int m = 0; m < 4; m++) {
        opts.nr_model = m;
        CHECK(nr_settings().quality == want[m]);
    }
    opts.nr_model = 2;
    CHECK(nr_settings().quality == 3u);   // the default row value is Quality

    // Percent rows become 0..1 floats.
    opts.nr_intensity = 0;   CHECK(near(nr_settings().intensity, 0.0f));
    opts.nr_intensity = 55;  CHECK(near(nr_settings().intensity, 0.55f));
    opts.nr_intensity = 100; CHECK(near(nr_settings().intensity, 1.0f));
    opts.nr_local_tone = 40;      CHECK(near(nr_settings().local_tone, 0.40f));
    opts.nr_local_structure = 70; CHECK(near(nr_settings().local_structure, 0.70f));
    opts.nr_global_tone = 10;     CHECK(near(nr_settings().global_tone, 0.10f));
    opts.nr_skin = 100;           CHECK(near(nr_settings().skin, 1.0f));
    opts.nr_skin = 0;             CHECK(near(nr_settings().skin, 0.0f));

    // The switch and the flags.
    opts.nr = 0; CHECK(!nr_settings().on);
    opts.nr = 1; CHECK(nr_settings().on);
    opts.nr_auto_mask = 0; CHECK(!nr_settings().auto_mask);
    opts.nr_auto_mask = 1; CHECK(nr_settings().auto_mask);

    // The Passes row: 1 to 10, read each call like the rest (a file from before the row: 1).
    opts.nr_passes = 1;  CHECK(nr_settings().passes == 1u);
    opts.nr_passes = 4;  CHECK(nr_settings().passes == 4u);
    opts.nr_passes = 0;  CHECK(nr_settings().passes == 1u);
    opts.nr_passes = 99; CHECK(nr_settings().passes == 10u);
    {   // (a change of the row is a change of the settings: the backends make their features again)
        opts.nr_passes = 1;
        const NrSettings one = nr_settings();
        opts.nr_passes = 2;
        CHECK(!(one == nr_settings()));
        opts.nr_passes = 1;
    }

    // Style and preset pass through as the model's own numbers.
    opts.nr_style = 2;  CHECK(nr_settings().style == 2u);
    opts.nr_preset = 7; CHECK(nr_settings().preset == 7u);
    opts.nr_preset = 0; CHECK(nr_settings().preset == 0u);

    // Equality is what lets the backend send the options only when they changed.
    opts.nr_intensity = 50;
    const auto a = nr_settings();
    CHECK(a == nr_settings());
    opts.nr_intensity = 51;
    CHECK(!(a == nr_settings()));

    if (bad == 0) std::printf("mapping ok\n");
    return bad != 0;
}
"""


def check_mapping(cxx):
    text = MENU_H.read_text(encoding="utf-8")
    struct = block(text, "struct NrSettings", "vk_menu.h's NrSettings")
    accessor = block(text, "inline NrSettings nr_settings()", "vk_menu.h's nr_settings()")
    source = PROGRAM.replace("__STRUCT__", struct + ";").replace("__ACCESSOR__", accessor)
    source = source.replace("NR_PLAN_H", str(ROOT / "gpu" / "vk" / "nr_plan.h"))
    with tempfile.TemporaryDirectory(prefix="hookshot-nr-settings-") as temp:
        src = pathlib.Path(temp) / "nr_settings.cpp"
        exe = pathlib.Path(temp) / "nr_settings"
        src.write_text(source, encoding="utf-8")
        build = subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(src),
                                "-o", str(exe)], capture_output=True, text=True)
        if build.returncode:
            fail("the extracted nr_settings() did not compile:\n" + build.stderr)
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode:
            fail("the nr_settings() mapping is wrong:\n" + run.stdout)


# ------------------------------------------------------------- the source facts a compile can't see

def check_nothing_caches():
    check_backend_live(NR_NGX_CPP)


def check_backend_live(path):
    text = path.read_text(encoding="utf-8")
    name = path.name
    asked = block(text, "bool asked()", name + "'s asked()")
    if "static" in asked:
        fail(name + ": asked() holds a static: the Neural rendering row would stop reaching the "
             "frame.\n" + asked)
    if "nr_settings()" not in asked:
        fail(name + ": asked() no longer reads nr_settings(): it cannot see the menu's row.")
    # apply() must read the settings every frame too, not once.
    apply_fn = block(text, "VkImage apply(VkCommandBuffer cmd", name + "'s apply()")
    if "nr_settings()" not in apply_fn:
        fail(name + ": apply() does not read nr_settings(): the model's own rows would never change.")
    if re.search(r"static\s+const\s+\w+\s+\w*(want|opt|setting)", apply_fn):
        fail(name + ": apply() caches its settings in a static.")


ROWS = {
    # row name: (lo, hi)
    "Neural rendering": (0, 1),
    "Backend": (0, 2),     # Auto, NGX direct, Open (OpenDLSS-NR) (vk_dlssnr_ngx.h nr::Backend)
    "Model": (0, 3),
    "Style": (0, 2),       # Default, Natural, Cinematic -- three, not eight
    "Preset": (0, 7),      # Default, then A..G
    "Intensity": (0, 100),
    "Local tone": (0, 100),
    "Local structure": (0, 100),
    "Global tone": (0, 100),
    "Passes": None,              # (their ranges are nr_plan.h's constants: tests/test_nr_plan.py)
    "Resolution scale": None,
    "Skin structure": (0, 100),   # not -1: no source says a negative is a sentinel
    "Auto mask": (0, 1),
}

DEFAULTS = {
    "nr": 0,              # every feature is off out of the box
    "nr_backend": 0,      # Auto: NGX direct where it runs, else the open network
    "nr_model": 2,        # Quality, the model's own default
    "nr_style": 0,
    "nr_preset": 0,       # the model picks; 1 would silently pin preset A
    "nr_skin": 100,       # 1.0, not -1
    "nr_auto_mask": 0,
}


def check_rows():
    text = MENU_CPP.read_text(encoding="utf-8")
    if "TAB_NEURAL" not in text:
        gone("the TAB_NEURAL rows")
    found = {}
    for name, lo, hi in re.findall(
            r'\{TAB_NEURAL,\s*"([^"]+)",\s*&opts\.\w+,\s*(-?\d+),\s*(-?\d+),', text):
        found[name] = (int(lo), int(hi))
    names = re.findall(r'\{TAB_NEURAL,\s*"([^"]+)",', text)
    for name, want in ROWS.items():
        if name not in names:
            fail('the Neural tab has no "%s" row' % name)
        elif want is not None and found.get(name) != want:
            fail('the "%s" row is %s, expected %s (docs/neural-rendering.md says why)'
                 % (name, found.get(name), want))
    for extra in set(names) - set(ROWS):
        fail('an unexpected Neural row "%s": add it to this test with its range' % extra)
    # every Neural row but the switch has a key of its own under nr_ in the options file: "model" or "backend" alone
    # would say nothing there
    key_fn = block(text, "const char* ini_key(const Row& r)", "vk_menu.cpp's ini_key()")
    for field in re.findall(r'\{TAB_NEURAL,\s*"[^"]+",\s*&opts\.(\w+),', text):
        if field != "nr" and not re.search(r'r\.value == &opts\.%s\) return "nr_\w+";' % field, key_fn):
            fail("opts.%s has no nr_ key in ini_key()" % field)


def check_backend_numbers():
    """The Backend row is saved as a number: 0 Auto, 1 NGX direct, 2 Open, with no gap, the same in the menu's labels,
    the front's enum and what RX_VK_DLSS_NR_BACKEND takes."""
    header = NR_NGX_H.read_text(encoding="utf-8")
    if "enum Backend : int { AUTO = 0, NGX = 1, OPEN = 2 };" not in header:
        fail("vk_dlssnr_ngx.h: nr::Backend is not AUTO 0, NGX 1, OPEN 2")
    menu = MENU_CPP.read_text(encoding="utf-8")
    if 'static const char* t[] = {"Auto", "NGX direct", "Open (OpenDLSS-NR)"};' not in block(
            menu, "const char* tx_nr_backend(int v)", "vk_menu.cpp's tx_nr_backend()"):
        fail("vk_menu.cpp: the Backend row's labels are not Auto, NGX direct, Open in the enum's order")
    asked = block(NR_NGX_CPP.read_text(encoding="utf-8"), "int asked_backend()", "nr::asked_backend()")
    for needle in ('!strcmp(e, "ngx") || !strcmp(e, "1")) return NGX;', '!strcmp(e, "open") || !strcmp(e, "2")) return OPEN;'):
        if needle not in asked:
            fail("nr::asked_backend(): RX_VK_DLSS_NR_BACKEND no longer takes %s" % needle)
    if "static" in asked:
        fail("nr::asked_backend() holds a static: the Backend row would stop reaching the frame")


def check_defaults():
    text = MENU_H.read_text(encoding="utf-8")
    for field, want in DEFAULTS.items():
        match = re.search(r"\bint %s\s*=\s*(-?\d+)\s*;" % re.escape(field), text)
        if not match:
            gone("vk_menu.h's opts.%s" % field)
        elif int(match.group(1)) != want:
            fail("opts.%s defaults to %s, expected %s (docs/neural-rendering.md says why)"
                 % (field, match.group(1), want))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_mapping(args.cxx)
    check_nothing_caches()
    check_rows()
    check_backend_numbers()
    check_defaults()
    if failures:
        for message in failures:
            print("FAIL: %s" % message)
        sys.exit(1)
    print("ok: the Neural rows, their defaults and the live mapping")


if __name__ == "__main__":
    main()
