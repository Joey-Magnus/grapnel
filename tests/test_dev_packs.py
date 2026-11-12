"""scripts/dev_packs.py: how a change is built, which modules and files a pack keeps, and a runtime from a base and packs.

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


def write(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_route():
    r = packs.route
    check("the replay alone builds the renderer alone", r(["gpu/vk/vk_replay.cpp", "tests/test_x.py"]) == "renderer")
    check("the recompiler builds the renderer alone", r(["gpu/vk/eden/shader_recompiler/ir_opt/x.cpp"]) == "renderer")
    check("imgui builds the renderer alone", r(["third_party/imgui/imgui.cpp"]) == "renderer")
    check("a host change builds the game", r(["host/hos_thread.c"]) == "game")
    check("a game patch builds the game", r(["nx2/oot_patches.py"]) == "game")
    check("a renderer file and a host file build the game (both modules)", r(["gpu/vk/vk_draw.cpp", "host/nvn_native.c"]) == "game")
    check("the WebGPU renderer is in the game", r(["gpu/render/x.c"]) == "game")
    check("a build script builds the game", r(["nx2/build.py"]) == "game")
    check("docs and tests build nothing", r(["docs/development.md", "tests/test_a.py", "README.md"]) is None)
    check("an unknown path builds the game", r(["somewhere/new.c"]) == "game")


def test_stamp_matches_build():
    """TRANSLATOR is nx2/build.py's shader stamp: a stamp file missing here would leave a runtime unprepared for a new translator"""
    src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    dirs = re.search(r'for top in \(([^)]*)\) for d, _, fs in os\.walk\(os\.path\.join\(vk, top\)\)', src)
    files = re.search(r'\+ \[os\.path\.join\(vk, n\) for n in \(([^)]*)\)\]', src)
    check("nx2/build.py's shader stamp found (anchor: 'for top in (...) for d, _, fs in os.walk(os.path.join(vk, top))')", dirs)
    check("nx2/build.py's shader stamp files found (anchor: '+ [os.path.join(vk, n) for n in (...)]')", files)
    names = lambda s: tuple(re.findall(r'"([^"]+)"', s))
    check("the stamp's folders are dev_packs.STAMP_DIRS", names(dirs.group(1)) == packs.STAMP_DIRS)
    check("the stamp's files are dev_packs.STAMP_FILES", names(files.group(1)) == packs.STAMP_FILES)


def test_renderer_files_the_game_reads():
    """The renderer files the game is built from take the full route, so the runtime gets the game built from them too"""
    found = packs.renderer_read_by_game(str(ROOT))
    for f in ("gpu/vk/vk_api.h", "gpu/vk/dlss_math.h", "gpu/vk/compat/hookshot_env.h"):
        check("%s found as read by the game (%s)" % (f, sorted(found)), f in found)
        check("%s takes the full route" % f, packs.route([f]) == "game")
    check("a renderer file the game does not read stays renderer-only", "gpu/vk/vk_replay.cpp" not in found)


def test_stamped_objects_match_build():
    """The objects named in MODULES as holding the version are the files nx2/build.py gives it to"""
    src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    stamped = re.findall(r'\[stamp_def\] if os\.path\.basename\((?:s|src)\) == "([^"]+)"', src)
    check("nx2/build.py's version files found (anchor: '[stamp_def] if os.path.basename(...) == ...')", stamped)
    check("they are dev_packs.STAMPED_SOURCES", sorted(stamped) == sorted(os.path.basename(s) for s in packs.STAMPED_SOURCES))


def test_caches_named_in_renderer():
    text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "gpu" / "vk").glob("*.cpp"))
    for c in packs.CACHES + (packs.SEED,):
        check("the renderer still names %s" % c.replace(".predicted", ""), c.replace(".predicted", "") in text)
    check("the predicted notes' suffix", '".predicted"' in text)


def test_module_changed(d):
    base, mine = d / "base-build", d / "pack-build"
    for build in (base, mine):
        write(build / "obj" / "a.o", b"same a")
        write(build / "obj" / "host_hos_main.o", b"version " + build.name.encode())
        (build / "objs.rsp").write_text("".join('"%s"\n' % (build / "obj" / n) for n in ("a.o", "host_hos_main.o")))
    mc = lambda changed_source=False: packs.module_changed(str(base), str(mine), "objs.rsp", "host_hos_main.o", changed_source)
    check("only the version differs: the base's module", not mc())
    check("the version's own source changed: the pack's", mc(True))
    write(mine / "obj" / "a.o", b"other a")
    check("another object differs: the pack's", mc())
    write(mine / "obj" / "a.o", b"same a")
    write(mine / "obj" / "b.o", b"new")
    (mine / "objs.rsp").write_text("".join('"%s"\n' % (mine / "obj" / n) for n in ("a.o", "b.o", "host_hos_main.o")))
    check("another set of objects: the pack's", mc())
    check("no link list in the base: the pack's", packs.module_changed(str(d / "none"), str(mine), "objs.rsp", "host_hos_main.o", False))


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


def test_generated_and_runtime(d):
    game_mod, vk_mod = packs.GAME, packs.RENDERER
    base_dir, game, out = d / "base", d / "base" / "game", d / "out"
    write(game / "romfs" / "a" / "data.bin", b"romfs")
    write(game / "romfs" / "prompts" / "icon.bntx", b"base icon")
    write(game / game_mod, b"base game")
    write(game / vk_mod, b"base renderer")
    write(game / "hookshot_programs.bin", b"cache")
    write(game / "language.txt", b"en-US")
    os.makedirs(out / "romfs" / "a")
    os.link(game / "romfs" / "a" / "data.bin", out / "romfs" / "a" / "data.bin")
    write(out / "romfs" / "prompts" / "icon.bntx", b"new icon")
    write(out / game_mod, b"built game")
    write(out / "hookshot_programs.bin", b"other cache")
    write(out / "language.txt", b"en-US")
    gen = packs.generated_changes(str(game), str(out))
    check("a regenerated file is kept, the same ones, the modules and the caches are not: %s" % gen, gen == ["romfs/prompts/icon.bntx"])
    b = {"commit": "c" * 40, "work": str(base_dir / "work"), "game": str(game), "romfs": "r", "exefs": "e"}
    packs.write_base(str(base_dir), b)
    for name, files, generated, on in (("cpu", {game_mod: "h"}, ["romfs/prompts/icon.bntx"], b["commit"]),
                                       ("cpu2", {game_mod: "h"}, [], b["commit"]), ("old", {vk_mod: "h"}, [], "o" * 40)):
        p = base_dir / "packs" / name
        for m in files:
            write(p / m, b"pack " + name.encode())
        for rel in generated:
            write(p / "files" / rel, b"new icon")
        (p / "pack.json").write_text(json.dumps({"base": on, "files": files, "generated": generated, "prepare": False}))
    rt = d / "rt"
    packs.main(["rt", str(base_dir), str(rt), "cpu"])
    check("the pack's game", (rt / game_mod).read_bytes() == b"pack cpu")
    check("the base's renderer", (rt / vk_mod).read_bytes() == b"base renderer")
    check("romfs hard-linked", os.path.samefile(rt / "romfs" / "a" / "data.bin", game / "romfs" / "a" / "data.bin"))
    check("the caches copied, not linked (the game writes them)", not os.path.samefile(rt / "hookshot_programs.bin", game / "hookshot_programs.bin"))
    check("the pack's generated file", (rt / "romfs" / "prompts" / "icon.bntx").read_bytes() == b"new icon")
    check("...not written through the base's hard link", (game / "romfs" / "prompts" / "icon.bntx").read_bytes() == b"base icon")
    for asked, what in ((["cpu", "cpu2"], "two packs with the same module"), (["old"], "a pack on another base")):
        try:
            packs.main(["rt", str(base_dir), str(d / ("rt-" + asked[-1])), *asked])
        except SystemExit as e:
            check(what + " refused with a reason", isinstance(e.code, str))
        else:
            check(what + " refused", False)


def main():
    test_route()
    test_stamp_matches_build()
    test_renderer_files_the_game_reads()
    test_stamped_objects_match_build()
    test_caches_named_in_renderer()
    with tempfile.TemporaryDirectory(prefix="hookshot-dev-packs-") as d:
        d = Path(d)
        for name, t in (("mc", test_module_changed), ("pf", test_pack_folders), ("rt", test_generated_and_runtime)):
            (d / name).mkdir()
            t(d / name)
    print("test_dev_packs: ok")


if __name__ == "__main__":
    main()
