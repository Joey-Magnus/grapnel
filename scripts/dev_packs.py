"""Development builds as a base and small packs over it: build the game once, then build only what a change touches and run it
from a copy of that base. For development and A/B tests only: it calls nx2/make_game.py and nx2/build.py as they are and
changes nothing in what players build (docs/development.md, *Testing a change against a base*).

    python -I scripts/dev_packs.py base <dir> --romfs <romfs> --exefs <exefs> [--seed <game folder>]
        Build this checkout (clean, at the commit to compare against) into <dir>/game, keeping its work folder <dir>/work.
        --seed copies the shader caches of an earlier game folder first, as a player's update keeps them: the prepare then
        only does what changed, instead of starting cold (an hour on some GPUs).
    python -I scripts/dev_packs.py adopt <dir> --work <work> --game <game> --romfs <romfs> --exefs <exefs>
        Use a full build of this checkout's commit that already exists (built with HOOKSHOT_KEEP_BUILD_FILES=1) as the base.
    python -I scripts/dev_packs.py pack <dir> <name> [--tree <checkout>] [--prepare | --no-prepare]
        Build a change (a checkout whose history contains the base's commit) and keep only the modules that differ from the base,
        in <dir>/packs/<name>. What is built follows the files changed since the base:
          - the shader translator (what nx2/build.py stamps the shader caches with): the renderer, and a prepare in the runtime;
          - the rest of gpu/ and the renderer's third_party: the renderer alone (RX_VK_ONLY: no lift, no game; minutes);
          - docs/, tests/, scripts/, builder/: nothing;
          - anything else (host/, nx2/ game patches, a64-kit): the game, with HOOKSHOT_NO_PREPARE, in one work folder shared
            by the base's packs (pack_folders): the base's compiled objects are reused, and after the first game pack the lift
            is skipped while the translator, the HLE list and the hot list stay the same.
    python -I scripts/dev_packs.py rt <dir> <runtime> [<pack>...]
        A game folder to run: the base's, its romfs hard-linked (read-only), the rest copied (the caches are written in play),
        the packs' modules over it. Prepared again when a pack changed the shader translator.
    python -I scripts/dev_packs.py ls <dir>

A pack's modules come from the same base as the rest of the runtime, so the game and the renderer always match
(MKWVK_API_VERSION). Two packs that bring the same module are refused: merge their branches and build one pack.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"
# (the game's own caches beside it, kept between runs and stamped by the translator (gpu/vk/vk_progcache.cpp): a stale one is
# not used, so a base can start from an older base's)
CACHES = ("hookshot_programs.bin", "hookshot_programs.idx", "hookshot_pipelines.bin", "hookshot_pipelines.bin.predicted",
          "hookshot_computes.bin", "hookshot_pipeline_states.bin", "hookshot_prepared.bin", "mkw_vk_pipelines.bin")
MODULES = ((("hookshot.exe", "hookshot.map"), ("hookshot_vk.dll", "hookshot_vk.map")) if WINDOWS else
           (("hookshot", None), ("hookshot_vk.so", None)))
GAME, RENDERER = MODULES[0][0], MODULES[1][0]
# (nx2/build.py's shader stamp: every file in gpu/vk/{eden,sirit,compat}/ and these four; tests/test_dev_packs.py checks they agree)
STAMP_DIRS = ("eden", "sirit", "compat")
STAMP_FILES = ("vk_shader.cpp", "vk_bank.cpp", "vk_state.h", "vk_api.h")
TRANSLATOR = tuple("gpu/vk/%s/" % d for d in STAMP_DIRS) + tuple("gpu/vk/" + f for f in STAMP_FILES)
RENDERER_PATHS = ("gpu/", "third_party/imgui/", "third_party/fidelityfx", "third_party/fonts/", "third_party/kenney_input")
NO_MODULE = ("docs/", "tests/", "scripts/", "builder/", ".github/", ".claude/")
# (files both modules are built from, each found by tests/test_dev_packs.py: the renderer's ABI and DLSS jitter, which nx2/build.py
# adds to the game's dependencies; the host header and C file nx2/build.py compiles into the renderer)
BOTH = ("gpu/vk/vk_api.h", "gpu/vk/dlss_math.h", "host/hos_wide_size.h", "host/mingw_msvc_shims.c")


def load_make_game():
    spec = importlib.util.spec_from_file_location("make_game_for_packs", os.path.join(ROOT, "nx2", "make_game.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def classify(paths):
    """What a change needs, from the paths it changed: a subset of {"game", "renderer", "prepare"}. A path not known to be the
    renderer's or no module's is the game's. By paths, not by the modules' bytes: every build names its sources' fingerprint in
    both modules (nx2/version.py), so any change makes both differ"""
    need = set()
    for p in paths:
        if p in BOTH:
            need |= {"game", "renderer"}
        if p.startswith(TRANSLATOR):
            need |= {"renderer", "prepare"}
        elif p.startswith(RENDERER_PATHS):
            need.add("renderer")
        elif not (p.startswith(NO_MODULE) or ("/" not in p and p.endswith(".md"))):
            need.add("game")
    return need


def git(tree, *args):
    return subprocess.run(["git", "-C", tree] + list(args), check=True, capture_output=True, text=True).stdout.strip()


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def run(cmd, cwd, env=None):
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, env=dict(os.environ, **(env or {})))


def make_game(tree, b, work, game, env):
    run([sys.executable, "-I", "nx2/make_game.py", "--romfs", b["romfs"], "--exefs", b["exefs"], "--work", work, "--out", game,
         "--language", b.get("language", "en-US")], tree, dict(env, HOOKSHOT_KEEP_BUILD_FILES="1"))


def read_base(d):
    with open(os.path.join(d, "base.json"), encoding="utf-8") as f:
        return json.load(f)


def write_base(d, b):
    b["modules"] = {m: sha(os.path.join(b["game"], m)) for m, _ in MODULES}
    with open(os.path.join(d, "base.json"), "w", encoding="utf-8") as f:
        json.dump(b, f, indent=1)


def pack_folders(d):
    """Where a base's packs are built: one work folder for the game and one for the renderer, the same for every pack. The lift key
    (make_game.lift_key) hashes the work and game folders' paths with the lift's environment, so a translation is reused only in
    the folder, and for the game folder, it was made for: a game pack after the first on a base skips the lift while the translator,
    the HLE list and the hot list are the base's. One pack builds at a time"""
    return {"game_work": os.path.join(d, "game-work"), "game_out": os.path.join(d, "game-out"),
            "renderer_work": os.path.join(d, "renderer-work")}


def link_objects(base_work, work):
    """A new work folder with the base's compiled objects (hard links: the object cache's keys hold no folder path) and the note of
    the compiler's headers they were made with, so only what a change touches compiles"""
    if os.path.isdir(work):
        return
    src = os.path.join(base_work, "objcache")
    for top, _, fs in os.walk(src):
        dst = os.path.join(work, "objcache", os.path.relpath(top, src))
        os.makedirs(dst, exist_ok=True)
        for f in fs:
            os.link(os.path.join(top, f), os.path.join(dst, f))
    os.makedirs(work, exist_ok=True)
    if os.path.isfile(os.path.join(base_work, "system_headers.txt")):
        shutil.copy2(os.path.join(base_work, "system_headers.txt"), os.path.join(work, "system_headers.txt"))


def cmd_base(a):
    tree = os.path.abspath(a.tree)
    if git(tree, "status", "--porcelain", "--untracked-files=no"):
        sys.exit("%s has uncommitted changes: a base is a commit" % tree)
    d = os.path.abspath(a.dir)
    work, game = os.path.join(d, "work"), os.path.join(d, "game")
    os.makedirs(game, exist_ok=True)
    if a.seed:
        for c in CACHES:
            if os.path.isfile(os.path.join(a.seed, c)) and not os.path.exists(os.path.join(game, c)):
                shutil.copy2(os.path.join(a.seed, c), os.path.join(game, c))
    b = {"commit": git(tree, "rev-parse", "HEAD"), "work": work, "game": game, "romfs": os.path.abspath(a.romfs),
         "exefs": os.path.abspath(a.exefs), "seeded_from": a.seed}
    t = time.time()
    make_game(tree, b, work, game, {})
    b["build_s"] = round(time.time() - t)
    for mod, mp in MODULES:   # (the maps beside the modules, for profilers)
        if mp:
            shutil.copy2(os.path.join(work, "sa", "build", mp), os.path.join(game, mp))
    write_base(d, b)
    print("base %s in %s: %d min" % (b["commit"][:8], d, b["build_s"] // 60))


def cmd_adopt(a):
    d = os.path.abspath(a.dir)
    os.makedirs(d, exist_ok=True)
    write_base(d, {"commit": git(os.path.abspath(a.tree), "rev-parse", "HEAD"), "work": os.path.abspath(a.work),
                   "game": os.path.abspath(a.game), "romfs": os.path.abspath(a.romfs), "exefs": os.path.abspath(a.exefs)})


def cmd_pack(a):
    d, tree = os.path.abspath(a.dir), os.path.abspath(a.tree)
    b = read_base(d)
    if subprocess.run(["git", "-C", tree, "merge-base", "--is-ancestor", b["commit"], "HEAD"]).returncode:
        sys.exit("%s is not built on the base %s: rebase it on the base, or make a new base" % (tree, b["commit"][:8]))
    changed = set(git(tree, "diff", "--name-only", b["commit"]).split())   # (the commits since the base and what is not committed)
    need = classify(changed)
    if a.prepare is not None:
        need = (need | {"renderer", "prepare"}) if a.prepare else need - {"prepare"}
    pack = os.path.join(d, "packs", a.name)
    os.makedirs(pack, exist_ok=True)
    print("%d files changed since the base: %s" % (len(changed), ", ".join(sorted(need)) or "no module to build"), flush=True)
    t, built, w = time.time(), None, pack_folders(d)
    if "game" in need:
        link_objects(b["work"], w["game_work"])
        make_game(tree, b, w["game_work"], w["game_out"], {"HOOKSHOT_NO_PREPARE": "1"})
        built = os.path.join(w["game_work"], "sa", "build")
    elif "renderer" in need:
        link_objects(b["work"], w["renderer_work"])
        run([sys.executable, "-I", "nx2/build.py", "--standalone"], tree,
            {"OOT_WORK": w["renderer_work"], "RX_RELEASE": "1", "RX_VK_ONLY": "1", "HOOKSHOT_KEEP_BUILD_FILES": "1"})
        built = os.path.join(w["renderer_work"], "sa", "build")
    files = {}
    for (mod, mp), kind in zip(MODULES, ("game", "renderer")):
        for f in (mod, mp):   # (an earlier build of this pack may have brought a module this one does not)
            if f and os.path.exists(os.path.join(pack, f)):
                os.remove(os.path.join(pack, f))
        if kind in need:
            for f in (mod, mp):
                if f:
                    shutil.copy2(os.path.join(built, f), os.path.join(pack, f))
            files[mod] = sha(os.path.join(pack, mod))
    with open(os.path.join(pack, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"base": b["commit"], "tree": tree, "head": git(tree, "rev-parse", "HEAD"), "changed": sorted(changed),
                   "need": sorted(need), "files": files, "build_s": round(time.time() - t)}, f, indent=1)
    print("pack %s: %s, in %d s" % (a.name, ", ".join(files) or "nothing to build", time.time() - t))


def cmd_rt(a):
    d, rt = os.path.abspath(a.dir), os.path.abspath(a.runtime)
    b = read_base(d)
    if os.path.exists(rt):
        sys.exit("%s exists: delete it first" % rt)
    over, prepare = {}, False
    for p in a.packs:
        with open(os.path.join(d, "packs", p, "pack.json"), encoding="utf-8") as f:
            meta = json.load(f)
        if meta["base"] != b["commit"]:
            sys.exit("pack %s was built on %s, not the base %s: build it again" % (p, meta["base"][:8], b["commit"][:8]))
        for mod in meta["files"]:
            if mod in over:
                sys.exit("packs %s and %s both bring %s: merge their branches and build one pack" % (over[mod], p, mod))
            over[mod] = p
        prepare |= "prepare" in meta["need"]
    os.makedirs(rt)
    for top, _, fs in os.walk(os.path.join(b["game"], "romfs")):
        dst = os.path.join(rt, os.path.relpath(top, b["game"]))
        os.makedirs(dst, exist_ok=True)
        for f in fs:
            os.link(os.path.join(top, f), os.path.join(dst, f))
    for name in os.listdir(b["game"]):
        s = os.path.join(b["game"], name)
        if os.path.isfile(s) and name not in over:
            shutil.copy2(s, os.path.join(rt, name))
        elif os.path.isdir(s) and name != "romfs":
            shutil.copytree(s, os.path.join(rt, name))
    for mod, p in over.items():
        for f in (mod, dict(MODULES)[mod]):
            if f and os.path.isfile(os.path.join(d, "packs", p, f)):
                shutil.copy2(os.path.join(d, "packs", p, f), os.path.join(rt, f))
    if prepare:   # (as make_game.py prepares: the game's own environment, without the build's switches)
        print("+ %s --prepare-shaders" % GAME, flush=True)
        subprocess.run([os.path.join(rt, GAME), "--prepare-shaders"], cwd=rt, check=True, env=load_make_game().game_env())
    with open(os.path.join(rt, "dev_packs.json"), "w", encoding="utf-8") as f:
        json.dump({"base": b["commit"], "packs": a.packs, "modules": {m: sha(os.path.join(rt, m)) for m, _ in MODULES}}, f, indent=1)
    print("%s: the base %s%s" % (rt, b["commit"][:8], "".join(", %s from %s" % kv for kv in over.items())))


def cmd_ls(a):
    d = os.path.abspath(a.dir)
    b = read_base(d)
    print("base %s: %s" % (b["commit"][:8], b["game"]))
    packs = os.path.join(d, "packs")
    for p in sorted(os.listdir(packs)) if os.path.isdir(packs) else ():
        try:
            with open(os.path.join(packs, p, "pack.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except OSError:
            continue
        print("  pack %s (%s, %s): %s" % (p, meta["head"][:8], "on the base" if meta["base"] == b["commit"] else "on another base",
                                          ", ".join(meta["files"]) or "-"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("base", "adopt"):
        s = sub.add_parser(name)
        s.add_argument("dir")
        s.add_argument("--romfs", required=True)
        s.add_argument("--exefs", required=True)
        s.add_argument("--tree", default=ROOT)
        if name == "base":
            s.add_argument("--seed")
        else:
            s.add_argument("--work", required=True)
            s.add_argument("--game", required=True)
    s = sub.add_parser("pack")
    s.add_argument("dir")
    s.add_argument("name")
    s.add_argument("--tree", default=ROOT)
    s.add_argument("--prepare", action="store_true", default=None)
    s.add_argument("--no-prepare", dest="prepare", action="store_false")
    s = sub.add_parser("rt")
    s.add_argument("dir")
    s.add_argument("runtime")
    s.add_argument("packs", nargs="*")
    s = sub.add_parser("ls")
    s.add_argument("dir")
    a = ap.parse_args(argv)
    {"base": cmd_base, "adopt": cmd_adopt, "pack": cmd_pack, "rt": cmd_rt, "ls": cmd_ls}[a.cmd](a)


if __name__ == "__main__":
    main()
