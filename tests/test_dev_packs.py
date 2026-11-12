"""scripts/dev_packs.py: what a change needs, a pack's work folder that skips the lift, and a runtime from a base and packs.

python -I -B tests/test_dev_packs.py
"""
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


packs = load("dev_packs_under_test", ROOT / "scripts" / "dev_packs.py")
make_game = load("make_game_under_test", ROOT / "nx2" / "make_game.py")


def check(what, ok):
    if not ok:
        raise SystemExit("FAIL: " + what)


def test_classify():
    c = packs.classify
    check("a host change builds the game", c(["host/hos_thread.c"]) == {"game"})
    check("a game patch builds the game", c(["nx2/oot_patches.py"]) == {"game"})
    check("a64-kit builds the game", c(["third_party/a64-kit/rt/a64.h"]) == {"game"})
    check("the replay builds the renderer alone", c(["gpu/vk/vk_replay.cpp"]) == {"renderer"})
    check("imgui is the renderer's", c(["third_party/imgui/imgui.cpp"]) == {"renderer"})
    check("the recompiler needs a prepare", c(["gpu/vk/eden/shader_recompiler/ir_opt/x.cpp"]) == {"renderer", "prepare"})
    check("vk_shader.cpp needs a prepare", c(["gpu/vk/vk_shader.cpp"]) == {"renderer", "prepare"})
    check("both", c(["gpu/vk/vk_draw.cpp", "host/nvn_native.c"]) == {"renderer", "game"})
    check("a header both are built from", c(["host/hos_wide_size.h"]) == {"renderer", "game"})
    check("the renderer's ABI: both, and a prepare", c(["gpu/vk/vk_api.h"]) == {"renderer", "game", "prepare"})
    check("docs and tests build nothing", c(["docs/development.md", "tests/test_a.py", "README.md", "scripts/x.py"]) == set())
    check("an unknown path builds the game (both modules)", c(["somewhere/new.c"]) == {"game"})


def test_stamp_matches_build():
    """classify's translator is nx2/build.py's shader stamp: a file added to the stamp and not here would leave a pack's
    runtime with caches the new renderer no longer uses, prepared in play instead"""
    src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    dirs = re.search(r'for top in \(([^)]*)\) for d, _, fs in os\.walk\(os\.path\.join\(vk, top\)\)', src)
    files = re.search(r'\+ \[os\.path\.join\(vk, n\) for n in \(([^)]*)\)\]', src)
    check("nx2/build.py's shader stamp found (anchor: 'for top in (...) for d, _, fs in os.walk(os.path.join(vk, top))')", dirs)
    check("nx2/build.py's shader stamp files found (anchor: '+ [os.path.join(vk, n) for n in (...)]')", files)
    names = lambda s: tuple(re.findall(r'"([^"]+)"', s))
    check("the stamp's folders are dev_packs.STAMP_DIRS", names(dirs.group(1)) == packs.STAMP_DIRS)
    check("the stamp's files are dev_packs.STAMP_FILES", names(files.group(1)) == packs.STAMP_FILES)


def test_both_matches_build():
    """dev_packs.BOTH holds every file both modules are built from, so a change there carries both into the pack"""
    src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    game_reads = re.findall(r'host_deps \+= open\(os\.path\.join\(GPU, "vk", "([^"]+)"\)', src)
    renderer_builds = [f for line in src.splitlines() if "vk_jobs.append(" in line for f in re.findall(r'os\.path\.join\(HOST, "([^"]+)"\)', line)]
    includes = set()
    for p in list((ROOT / "gpu" / "vk").glob("*.cpp")) + list((ROOT / "gpu" / "vk").glob("*.h")):
        includes.update(re.findall(r'#include "\.\./\.\./host/([^"]+)"', p.read_text(encoding="utf-8", errors="replace")))
    check("build.py's game dependencies on gpu/vk found (anchor: 'host_deps += open(os.path.join(GPU, \"vk\", ...')", game_reads)
    check("build.py's host files in the renderer found (anchor: 'vk_jobs.append(... os.path.join(HOST, ...')", renderer_builds)
    for f in ["gpu/vk/" + f for f in game_reads] + ["host/" + f for f in renderer_builds + sorted(includes)]:
        check("%s is in dev_packs.BOTH" % f, f in packs.BOTH)


def test_caches_named_in_renderer():
    text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "gpu" / "vk").glob("*.cpp"))
    for c in packs.CACHES:
        base = c.replace(".predicted", "")
        check("the renderer still names %s" % c, base in text)
    check("the predicted notes' suffix", '".predicted"' in text)


def write(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_pack_folders(d):
    """The lift key hashes the work and game folders' paths (make_game passes them to the lift as OOT_WORK and OOT_DUMP): a game
    pack reuses a translation only when every pack of a base builds in the same two folders"""
    f = packs.pack_folders(str(d))
    check("the same folders for every pack", f == packs.pack_folders(str(d)) and not f["game_work"].startswith(os.path.join(str(d), "packs")))
    exefs, work, out = d / "exefs", Path(f["game_work"]), Path(f["game_out"])
    write(exefs / "main", b"NSO0 one")
    env = lambda w, o: {"OOT_WORK": str(w), "OOT_DUMP": str(o), "RX_RELEASE": "1", "A64_HOT_CHUNK": "1"}
    key = make_game.lift_key(str(exefs), str(work), env(work, out))
    check("the key is the same in the same folders", key == make_game.lift_key(str(exefs), str(work), env(work, out)))
    check("...and differs in another (why packs share one folder)",
          key != make_game.lift_key(str(exefs), str(d / "other"), env(d / "other", out)))
    base = d / "base-work"
    write(base / "objcache" / "ab" / "abcdef.o", b"object")
    write(base / "system_headers.txt", b"headers")
    write(base / "sa" / "gen" / "code_0001.c", b"lifted")
    packs.link_objects(str(base), str(work))
    check("the base's objects, hard-linked", os.path.samefile(work / "objcache" / "ab" / "abcdef.o", base / "objcache" / "ab" / "abcdef.o"))
    check("the compiler's header note copied", (work / "system_headers.txt").read_bytes() == b"headers")
    check("no lifted C of the base's (another folder's key)", not (work / "sa").exists())
    (work / "objcache" / "ab" / "mine.o").write_bytes(b"pack")
    packs.link_objects(str(base), str(work))
    check("a work folder already there is left as it is", (work / "objcache" / "ab" / "mine.o").exists())


def test_runtime(d):
    game_mod, vk_mod = packs.GAME, packs.RENDERER
    base_dir, game = d / "base", d / "base" / "game"
    write(game / "romfs" / "a" / "data.bin", b"romfs")
    write(game / game_mod, b"base game")
    write(game / vk_mod, b"base renderer")
    write(game / "hookshot_programs.bin", b"cache")
    b = {"commit": "c" * 40, "work": str(base_dir / "work"), "game": str(game), "romfs": "r", "exefs": "e"}
    packs.write_base(str(base_dir), b)
    for name, mod, data, on in (("cpu", game_mod, b"pack game", b["commit"]), ("cpu2", game_mod, b"other game", b["commit"]),
                                ("old", vk_mod, b"old renderer", "o" * 40)):
        write(base_dir / "packs" / name / mod, data)
        (base_dir / "packs" / name / "pack.json").write_text(json.dumps({"base": on, "need": ["game"], "files": {mod: "h"}}))
    rt = d / "rt"
    packs.main(["rt", str(base_dir), str(rt), "cpu"])
    check("the pack's game", (rt / game_mod).read_bytes() == b"pack game")
    check("the base's renderer", (rt / vk_mod).read_bytes() == b"base renderer")
    check("romfs hard-linked", os.path.samefile(rt / "romfs" / "a" / "data.bin", game / "romfs" / "a" / "data.bin"))
    check("the caches copied, not linked (the game writes them)", not os.path.samefile(rt / "hookshot_programs.bin", game / "hookshot_programs.bin"))
    for packs_asked, what in ((["cpu", "cpu2"], "two packs with the same module"), (["old"], "a pack on another base")):
        try:
            packs.main(["rt", str(base_dir), str(d / ("rt-" + packs_asked[-1])), *packs_asked])
        except SystemExit as e:
            check(what + " refused with a reason", isinstance(e.code, str))
        else:
            check(what + " refused", False)


def main():
    test_classify()
    test_stamp_matches_build()
    test_both_matches_build()
    test_caches_named_in_renderer()
    with tempfile.TemporaryDirectory(prefix="hookshot-dev-packs-") as d:
        test_pack_folders(Path(d))
        test_runtime(Path(d))
    print("test_dev_packs: ok")


if __name__ == "__main__":
    main()
