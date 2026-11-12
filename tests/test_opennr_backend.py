"""Open neural rendering's wiring, in the source: what no frame-level check can see.

* the open backend reads the Neural tab live: its asked() and apply() go through nr_settings() every call and hold
  no static copy of it (tests/test_nr_settings_live.py is the same check for NGX direct);
* nr::apply, the present's one call (vk_dlssnr_ngx.cpp), hands the frame to it when it is the backend that runs, and
  the Backend row's Auto falls to it;
* create_device asks it for its extensions before vkCreateDevice and chains its features before the features query,
  and it is told when the device exists;
* THE DEVICE IS MADE FOR IT ONLY WHEN THE PLAYER ASKED FOR IT BY THE START. opennr::selected() is cut out of
  vk_opennr.cpp and run: with Neural rendering off and no model folder it answers no on every vendor, so the three
  device hooks do nothing and vkCreateDevice is given what it is given without this backend (no VK_EXT_shader_float8
  on an AMD or Intel GPU because the code is there). Yes only for the row saved On with Backend Open, or Auto on a GPU
  that is not NVIDIA's, a model folder in place, or RX_VK_DLSS_NR_BACKEND=open. NGX direct's own device extensions
  have the same rule (dlssnr_ngx::device_extensions), and a row turned on later says a restart is needed.

    python -I -B tests/test_opennr_backend.py [--cxx g++]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def fail(text):
    print("FAIL: " + text)
    sys.exit(1)


def blocks(text, head):
    """Every function starting at a line that starts with `head`, by brace matching: [(start, body, whole)]"""
    out = []
    for m in re.finditer(r"^" + re.escape(head), text, re.M):
        open_at = text.index("{", m.start())
        depth, i = 0, open_at
        while True:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        out.append((m.start(), text[open_at:i + 1], text[m.start():i + 1]))
    return out


# opennr::selected() as vk_opennr.cpp has it, with what it reads stubbed: the switch, the Backend row, the GPU's vendor
# and the model folder. It keeps its answer for the process, as the device does, so each case is a run of its own.
SELECTED_PROGRAM = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
namespace nr {
__BACKEND_ENUM__
static int backend;
int asked_backend() { return backend; }
}
static struct { const void* physical; struct { unsigned vendorID; } props; } dev;
static bool on;
static std::string model;
bool asked() { return on; }
std::string model_directory() { return model; }
__SELECTED__
int main(int argc, char** argv) {
    if (argc != 5) return 2;
    on = atoi(argv[1]) != 0;
    nr::backend = atoi(argv[2]);
    dev.physical = &dev, dev.props.vendorID = (unsigned)strtoul(argv[3], nullptr, 16);
    model = argv[4];
    std::printf("%d\n", selected() ? 1 : 0);
    return 0;
}
"""
NVIDIA, AMD, INTEL = "10de", "1002", "8086"
AUTO, NGX, OPEN = 0, 1, 2
# (neural rendering on at the start, the Backend row, the GPU, a model folder there, RX_VK_DLSS_NR_BACKEND) -> made for it
CASES = [
    ((0, AUTO, AMD, False, None), False, "off on an AMD GPU: the device as without the backend (the review of #1833)"),
    ((0, AUTO, INTEL, False, None), False, "off on an Intel GPU"),
    ((0, AUTO, NVIDIA, False, None), False, "off on an NVIDIA GPU"),
    ((0, OPEN, AMD, False, None), False, "off, with Backend left at Open: still off"),
    ((0, OPEN, NVIDIA, False, None), False, "off, Backend Open, NVIDIA"),
    ((1, AUTO, AMD, False, None), True, "on, Auto, a GPU that is not NVIDIA's: Open is its only backend"),
    ((1, AUTO, INTEL, False, None), True, "on, Auto, Intel"),
    ((1, AUTO, NVIDIA, False, None), False, "on, Auto, NVIDIA with no model folder: NGX direct's, not this one"),
    ((1, OPEN, NVIDIA, False, None), True, "on, Backend Open"),
    ((1, NGX, AMD, False, None), False, "on, Backend NGX direct: not this backend"),
    ((0, AUTO, NVIDIA, True, None), True, "a model folder in place at the start"),
    ((0, AUTO, AMD, True, None), True, "a model folder in place, AMD"),
    ((0, AUTO, NVIDIA, False, "open"), True, "RX_VK_DLSS_NR_BACKEND=open"),
    ((0, AUTO, NVIDIA, False, "2"), True, "RX_VK_DLSS_NR_BACKEND=2"),
    ((0, AUTO, AMD, False, "ngx"), False, "RX_VK_DLSS_NR_BACKEND=ngx"),
    ((0, AUTO, AMD, False, "auto"), False, "RX_VK_DLSS_NR_BACKEND=auto"),
]


def check_selected(cxx, opennr, header):
    selected = blocks(opennr, "bool selected()")
    enum = re.search(r"enum Backend : int \{[^}]*\};", header)
    if len(selected) != 1 or not enum:
        fail("opennr::selected() or nr::Backend not found")
    source = SELECTED_PROGRAM.replace("__SELECTED__", selected[0][2]).replace("__BACKEND_ENUM__", enum.group(0))
    with tempfile.TemporaryDirectory(prefix="hookshot-opennr-selected-") as temp:
        temp = Path(temp)
        (temp / "selected.cpp").write_text(source, encoding="utf-8")
        exe = temp / "selected"
        build = subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(temp / "selected.cpp"), "-o", str(exe)],
                               capture_output=True, text=True)
        if build.returncode:
            fail("the extracted opennr::selected() did not compile:\n" + build.stderr)
        model = temp / "nr-model"
        model.mkdir()
        (model / "manifest.json").write_text("{}", encoding="utf-8")
        for (on, backend, vendor, has_model, env_backend), want, what in CASES:
            env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
            if env_backend:
                env["RX_VK_DLSS_NR_BACKEND"] = env_backend
            run = subprocess.run([str(exe), str(on), str(backend), vendor, str(model if has_model else temp / "none")],
                                 capture_output=True, text=True, env=env)
            if run.returncode or run.stdout.strip() != ("1" if want else "0"):
                fail("opennr::selected() is %s for: %s (the device would be made %s the network's extensions)"
                     % (run.stdout.strip() or run.returncode, what, "without" if want else "with"))
    return len(CASES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    opennr = (VK / "vk_opennr.cpp").read_text(encoding="utf-8")
    asked = blocks(opennr, "bool asked()")
    apply = blocks(opennr, "VkImage apply(VkCommandBuffer cmd")
    if len(asked) != 1 or len(apply) != 1:
        fail("vk_opennr.cpp: expected one asked() and one apply(), found %d and %d" % (len(asked), len(apply)))
    if "nr_settings()" not in asked[0][1] or re.search(r"\bstatic\b", asked[0][1]):
        fail("opennr::asked() must read nr_settings() every call, with no static")
    if "nr_settings()" not in apply[0][1]:
        fail("opennr::apply() does not read nr_settings(): the Neural tab's rows would never reach the network")
    if re.search(r"static[^;]*NrSettings", apply[0][1]):
        fail("opennr::apply() caches the settings in a static")

    # (the frame reaches the open backend through the Backend row's one dispatch point, nr::apply in vk_dlssnr_ngx.cpp:
    #  the row's Open, and Auto's fall to it)
    ngx = (VK / "vk_dlssnr_ngx.cpp").read_text(encoding="utf-8")
    nr_apply = blocks(ngx, "VkImage apply(VkCommandBuffer cmd, VkImage src, uint32_t sw, uint32_t sh, const int crop[4], VkImageView* out_view,\n              uint32_t* out_w, uint32_t* out_h) {\n    static int told")
    if len(nr_apply) != 1:
        fail("vk_dlssnr_ngx.cpp: nr::apply not found")
    # (through the one lambda that calls whichever backend runs, on the frame or on the Resolution scale's smaller copy)
    if "b == OPEN ? opennr::apply(cmd, from, w, h, view) : dlssnr_ngx::apply(cmd, from, w, h, view)" not in nr_apply[0][1]:
        fail("nr::apply does not hand the frame to the open backend when it is the one running")
    # (with the row off no backend is asked anything: the switch is read before the backend is worked out)
    if not 0 < nr_apply[0][1].find("if (!wanted()) return VK_NULL_HANDLE;") < nr_apply[0][1].find("running_backend()"):
        fail("nr::apply must read the switch before it asks which backend runs")
    if "opennr::ready()" not in ngx:
        fail("the Backend row's Auto never falls to the open backend (nr::running_backend)")
    main_cpp = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    create = blocks(main_cpp, "bool create_device()")
    if len(create) != 1:
        fail("vk_main.cpp: create_device() not found")
    body = create[0][1]
    at = {name: body.find(name) for name in ("opennr::device_extensions(want, exts)", "opennr::device_features(tail)",
                                             "opennr::device_created()", "vkGetPhysicalDeviceFeatures2(dev.physical, &f)",
                                             "vkCreateDevice(dev.physical", "optional(VK_KHR_COOPERATIVE_MATRIX",
                                             "dlssnr_ngx::device_extensions(dev.instance, dev.physical",
                                             "dlssnr_ngx::device_created(want)")}
    missing = [n for n, i in at.items() if i < 0]
    if missing:
        fail("create_device() lacks %s" % missing)
    if not (at["optional(VK_KHR_COOPERATIVE_MATRIX"] < at["opennr::device_extensions(want, exts)"] <
            at["vkCreateDevice(dev.physical"]):
        fail("opennr::device_extensions must come after the cooperative-matrix extension and before vkCreateDevice")
    if not at["opennr::device_features(tail)"] < at["vkGetPhysicalDeviceFeatures2(dev.physical, &f)"]:
        fail("opennr::device_features must chain its structs before the features query fills them")
    if not at["vkCreateDevice(dev.physical"] < at["opennr::device_created()"]:
        fail("opennr::device_created must come after the device is made")
    if not (at["dlssnr_ngx::device_extensions(dev.instance, dev.physical"] < at["vkCreateDevice(dev.physical"] <
            at["dlssnr_ngx::device_created(want)"]):
        fail("NGX direct's extensions must be asked before vkCreateDevice, and the device's told to it after")

    # ---- device creation: nothing of this backend unless it was asked for by the start
    # each of the three hooks does nothing first, unless selected()
    for head in ("void device_extensions(", "void device_features(", "void device_created("):
        hook = blocks(opennr, head)
        if len(hook) != 1 or not re.match(r"\{\s*if \(!selected\(\)\) return;", hook[0][1]):
            fail("vk_opennr.cpp %s...) must return at once when the backend was not asked for at the start" % head)
    # nothing else in the file adds to the device's extensions or chains a feature struct
    outside = opennr
    for head in ("void device_extensions(", "void device_features("):
        outside = outside.replace(blocks(opennr, head)[0][2], "")
    if "want.push_back" in outside or "tail = &" in outside:
        fail("vk_opennr.cpp asks for a device extension or feature outside its two gated hooks")
    # and selected() itself, run: off with no model folder is "no" on every vendor
    header = (VK / "vk_dlssnr_ngx.h").read_text(encoding="utf-8")
    cases = check_selected(args.cxx, opennr, header)
    if "MERGE:" in opennr:
        fail("vk_opennr.cpp still has a MERGE marker")
    # a row turned on without the device made for it says so, and that it takes a restart
    why = blocks(opennr, "const char* why()")
    if len(why) != 1 or not re.search(r'if \(!selected\(\)\)\s*return "[^"]*restart[^"]*";', why[0][1]):
        fail("opennr::why() must say a restart is needed when the device was made without the network's extensions")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    hint = blocks(menu, "const char* hn_nr(int v, int variant)")
    if len(hint) != 1 or "nr::why()" not in hint[0][1] or why[0][1].split('return "')[1].split('"')[0] not in hint[0][1]:
        fail("the Neural rendering row's hint must show nr::why(), and hold its restart line for the menu's height")

    # NGX direct's device extensions: the same rule (asked of NGX only with the row on at the start, on an NVIDIA GPU,
    # with a Backend that can be NGX direct), and a row turned on later is checked against what the device has
    ngx_exts = [b for b in blocks(ngx, "size_t device_extensions(VkInstance instance") if "ngx::device_extensions(" in b[1]]
    gate = "if (!nr::wanted() || nr::asked_backend() == nr::OPEN || dev.props.vendorID != 0x10de) return 0;"
    if len(ngx_exts) != 1 or not 0 < ngx_exts[0][1].find(gate) < ngx_exts[0][1].find("ngx::device_extensions("):
        fail("dlssnr_ngx::device_extensions must ask NGX nothing unless neural rendering is on at the start")
    probe = blocks(ngx, "bool probe(State& s)")
    if len(probe) != 1 or "if (!s.asked_at_start) {" not in probe[0][1] or "restart the game" not in probe[0][1]:
        fail("dlssnr_ngx's probe must check a row turned on later against the device's extensions, and ask for a restart")
    print("open neural rendering: settings read live, dispatched from nr::apply (the Backend row), device hooks in "
          "order and gated; selected() right in %d cases (off with no model folder: the device as without it)" % cases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
