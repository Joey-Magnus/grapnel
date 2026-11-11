"""The data folder (host/hos_data.c): which folder a run keeps its saves, settings, log and caches in, and the one-time move of
what a build from before kept in the game folder.

host/hos_data.c is built with the Linux stand-ins (host/posix/win32_posix.c) into a small program that prints the folder it
chose and the saves' folder. The program is copied into game folders built in a temporary folder, as the builder makes them
(image.bin beside it, or the game in bin/ beside image.bin), and run there:

- --user <folder> wins, and nothing is moved; a run given its image.bin uses "user" in the current folder;
- a builder's folder uses $XDG_DATA_HOME/hookshot; the settings and logs go there, the caches to its shaders/ (the play
  files by their prefix too), the saves from <game>/user, and a note is left; language.txt (the builder's) stays, and the
  prompts made from the player's controls are deleted;
- a file already in the data folder is not written over: the game folder's copy stays where it is;
- when a save entry cannot move (one of that name is there already), the saves stay in <game>/user together;
- the game in bin/: the files come from the folder above it, the one with image.bin.

python -I -B tests/test_data_dir.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "builds host/hos_data.c with the Linux stand-ins (host/posix); the Windows branch is the platform folder alone"}

ROOT = Path(__file__).resolve().parents[1]

MAIN = r"""
#include <stdarg.h>
#include <stdio.h>
void hos_data_init(int argc, char **argv);
const char *hos_data_dir(void);
void hos_data_log_migration(void);
const char *hos_user_dir;   /* (host/nn_fs.c) */
void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    printf("log: ");
    vprintf(fmt, a);
    printf("\n");
    va_end(a);
}
int main(int argc, char **argv) {
    hos_data_init(argc, argv);
    hos_data_log_migration();
    printf("data=%s\nuser=%s\n", hos_data_dir(), hos_user_dir);
    return 0;
}
"""


def run(exe, args, cwd, xdg):
    env = dict(os.environ, XDG_DATA_HOME=str(xdg))
    out = subprocess.run([str(exe)] + args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line and not line.startswith("log:"))
    return Path(values["data"]), Path(values["user"]), out


def game_folder(root, built, in_bin=False):
    """A builder's folder: image.bin, the game (in bin/ when asked), and what a build from before left beside it"""
    root.mkdir(parents=True)
    (root / "image.bin").write_bytes(b"image")
    where = root / "bin" if in_bin else root
    where.mkdir(exist_ok=True)
    exe = where / "hookshot"
    shutil.copy2(built, exe)
    files = {
        "hookshot_options.ini": "vsync=1\n", "hookshot_env.txt": "RX_VK_X=1\n", "hookshot_log.txt": "log\n",
        "hookshot_log.1.txt": "log 1\n", "language.txt": "fr\n", "mkw_vk_pipelines.bin": "driver",
        "mkw_vk_pipelines_play_3.bin": "play", "hookshot_programs.bin": "programs", "hookshot_programs.idx": "index",
        "hookshot_programs.bin.lock": "", "hookshot_pipelines.bin": "notes", "hookshot_prepared.bin": "prepared",
        "hookshot_shaders.bin": "seed", "hookshot_pipeline_states_shipped.bin": "shipped",
    }
    for name, text in files.items():
        (root / name).write_text(text)
    (root / "prompts").mkdir()
    (root / "prompts" / "Common.key").write_text("k")
    (root / "prompts" / "Common.bntx").write_text("game's")
    (root / "user" / "save" / "0100").mkdir(parents=True)
    (root / "user" / "save" / "0100" / "file").write_text("my save")
    (root / "user" / "mouse_sens.txt").write_text("1.5\n")
    return exe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="hookshot-data-dir-") as tmp:
        tmp = Path(tmp)
        main_c = tmp / "main.c"
        main_c.write_text(MAIN)
        built = tmp / "data_dir"
        subprocess.run([a.cc, "-std=gnu11", "-I", str(ROOT / "host" / "posix"), "-I", str(ROOT / "host"),
                        str(ROOT / "host" / "hos_data.c"), str(ROOT / "host" / "posix" / "win32_posix.c"), str(main_c),
                        "-o", str(built), "-lpthread", "-ldl"], check=True)

        # --user wins, made absolute; nothing moves out of the game folder
        game = tmp / "a" / "game"
        exe = game_folder(game, built)
        data, user, _ = run(exe, ["--user", "mine"], tmp / "a", tmp / "a" / "xdg")
        assert data == tmp / "a" / "mine" and user == data, (data, user)
        assert (data / "shaders").is_dir() and (game / "hookshot_options.ini").exists() and not (tmp / "a" / "xdg").exists()

        # a development run, given its image.bin: "user" in the current folder
        data, user, _ = run(exe, [str(game / "image.bin")], tmp / "a", tmp / "a" / "xdg")
        assert data == tmp / "a" / "user" and user == data, (data, user)
        assert (game / "hookshot_programs.bin").exists()

        # a builder's folder: everything per-PC moves to $XDG_DATA_HOME/hookshot
        game = tmp / "b" / "game"
        exe = game_folder(game, built)
        xdg = tmp / "b" / "xdg"
        data, user, out = run(exe, [], tmp / "b", xdg)
        assert data == xdg / "hookshot" and user == data, (data, user, out)
        for name in ("hookshot_options.ini", "hookshot_env.txt", "hookshot_log.txt", "hookshot_log.1.txt"):
            assert (data / name).exists() and not (game / name).exists(), name
        for name in ("mkw_vk_pipelines.bin", "mkw_vk_pipelines_play_3.bin", "hookshot_programs.bin", "hookshot_programs.idx",
                     "hookshot_pipelines.bin", "hookshot_prepared.bin"):
            assert (data / "shaders" / name).exists() and not (game / name).exists(), name
        assert (data / "save" / "0100" / "file").read_text() == "my save" and (data / "mouse_sens.txt").exists()
        assert not (game / "user").exists()
        for name in ("language.txt", "hookshot_shaders.bin", "hookshot_pipeline_states_shipped.bin", "image.bin"):
            assert (game / name).exists() and not (data / name).exists(), name   # (the build's own)
        assert not (game / "hookshot_programs.bin.lock").exists() and not (game / "prompts" / "Common.key").exists()
        assert (game / "prompts" / "Common.bntx").exists()
        assert "Hookshot's saves" in (game / "files-moved.txt").read_text()
        assert "moved from the game folder" in out and "the saves moved" in out, out
        # a second start: nothing left to move, the same folder
        data2, _, out = run(exe, [], tmp / "b", xdg)
        assert data2 == data and "moved" not in out, out

        # what the data folder has already is not written over; saves that cannot all move stay together
        game = tmp / "c" / "game"
        exe = game_folder(game, built)
        xdg = tmp / "c" / "xdg"
        (xdg / "hookshot" / "save").mkdir(parents=True)
        (xdg / "hookshot" / "hookshot_options.ini").write_text("mine\n")
        data, user, out = run(exe, [], tmp / "c", xdg)
        assert data == xdg / "hookshot" and user == game / "user", (data, user)
        assert (data / "hookshot_options.ini").read_text() == "mine\n" and (game / "hookshot_options.ini").exists()
        assert (game / "user" / "save" / "0100" / "file").exists() and (game / "user" / "mouse_sens.txt").exists()
        assert (data / "shaders" / "hookshot_programs.bin").exists()
        assert "the saves stay in" in out and "stayed in the game folder" in out, out

        # the game in bin/ beside image.bin (the launcher's layout): the folder above bin/ is the game folder
        game = tmp / "d" / "game"
        exe = game_folder(game, built, in_bin=True)
        xdg = tmp / "d" / "xdg"
        data, user, _ = run(exe, [], tmp / "d", xdg)
        assert data == xdg / "hookshot" and (data / "hookshot_options.ini").exists() and not (game / "hookshot_options.ini").exists()
        assert (data / "save" / "0100" / "file").exists()
    print("PASS: --user and a development run keep their folder; a builder's folder moves its settings, logs, caches and saves "
          "to the data folder once, writes nothing over, keeps the saves together, and finds the folder above bin/")


if __name__ == "__main__":
    main()
