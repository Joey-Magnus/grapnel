"""The Linux Builder's hand-over to the Hookshot Launcher (builder/linux/linux_upgrade.py, docs/launcher-upgrade.md), with
the contract's sample files (tests/fixtures/launcher/): the manifest is read as strictly as the setup lists, the import
file from builder.ini is the sample one, the folder's stamp names the launcher, the launcher is installed whole or not at
all, a release without the file is a Builder release, and --launch/--update go to an installed launcher. The game's own
update offer (host/hos_update.c, its installed_launcher compiled here from its text) prefers that launcher too.

No network and no game: downloads are a fetcher the test passes in.

python -I -B tests/test_linux_upgrade.py
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

RUN_ALL_SKIP = {"windows": "the Linux Builder's hand-over: POSIX files and modes"}

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "launcher"
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import linux_upgrade  # noqa: E402

SAMPLE = (FIXTURES / "hookshot-launcher.txt").read_text(encoding="utf-8")
SHA = "a" * 64


def manifest(*lines, tag="v3.0.0", form="1"):
    return "\n".join(["tag " + tag, "format " + form] + list(lines)) + "\n"


def http_error(url, code):
    error = urllib.error.HTTPError(url, code, "GitHub's answer", {}, io.BytesIO(b""))
    error.close()   # (only its code is read)
    return error


def offer(data, url="https://example.invalid/Hookshot.AppImage"):
    text = manifest("launcher linux-x64 %s %d %s" % (hashlib.sha256(data).hexdigest(), len(data), url))
    return linux_upgrade.parse_manifest(text, "v3.0.0")


class Manifest(unittest.TestCase):
    def test_the_sample_is_read_and_its_unknown_platform_skipped(self):
        m = linux_upgrade.parse_manifest(SAMPLE, "v3.0.0")
        self.assertEqual(m.tag, "v3.0.0")
        self.assertEqual(sorted(m.launchers), ["linux-x64", "windows-x64"])
        line = m.line()
        self.assertEqual((line.sha, line.size), ("2" * 64, 73400320))
        self.assertEqual(line.url, "https://github.com/NotRexed/Hookshot/releases/download/v3.0.0/Hookshot-v3.0.0-x86_64.AppImage")
        self.assertEqual(m.line("windows-x64").sha, "1" * 64)
        # (the latest release: any tag that is a version name)
        self.assertEqual(linux_upgrade.parse_manifest(SAMPLE).tag, "v3.0.0")

    def test_a_list_for_another_tag_is_refused(self):
        with self.assertRaises(ValueError):
            linux_upgrade.parse_manifest(SAMPLE, "v3.0.1")

    def test_bad_lines_are_refused(self):
        good = "launcher linux-x64 %s 10 https://example.invalid/a" % SHA
        for text in (
                manifest("launcher linux-x64 %s 10 https://example.invalid/a" % ("A" * 64)),   # (uppercase)
                manifest("launcher linux-x64 %s 10 https://example.invalid/a" % ("a" * 63)),
                manifest("launcher linux-x64 %s 10 http://example.invalid/a" % SHA),             # (not https)
                manifest("launcher linux-x64 %s 10 file:///tmp/a" % SHA),
                manifest("launcher linux-x64 %s ten https://example.invalid/a" % SHA),
                manifest("launcher linux-x64 %s 0 https://example.invalid/a" % SHA),
                manifest("launcher linux-x64 %s 10" % SHA),
                manifest(good, good),                                                          # (twice)
                manifest(good, "part %s 10 . https://example.invalid/a" % SHA),                # (an unknown line)
                manifest(good, tag=".."), manifest(good, tag="v3/../x"), manifest(good, form="one"), manifest(good, form="0"),
                "format 1\n" + good + "\n", "tag v3.0.0\n" + good + "\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                linux_upgrade.parse_manifest(text, "v3.0.0" if "tag v3.0.0" in text else None)

    def test_comments_and_blank_lines_are_skipped(self):
        text = "# a note\n\n" + manifest("", "# another", "launcher linux-x64 %s 10 https://example.invalid/a" % SHA)
        self.assertEqual(linux_upgrade.parse_manifest(text, "v3.0.0").line().size, 10)

    def test_a_higher_format_is_too_new_for_this_builder(self):
        with self.assertRaises(linux_upgrade.TooNew) as said:
            linux_upgrade.parse_manifest(manifest("launcher linux-x64 %s 10 https://example.invalid/a" % SHA, form="2"), "v3.0.0")
        self.assertIn("release page", str(said.exception))

    def test_a_release_without_this_platform_has_no_line(self):
        m = linux_upgrade.parse_manifest(manifest("launcher windows-x64 %s 10 https://example.invalid/a" % SHA,
                                                  "launcher freebsd-x64 %s 10 https://example.invalid/b" % SHA), "v3.0.0")
        with self.assertRaises(ValueError):
            m.line()

    def test_a_local_list_may_name_a_file(self):
        text = manifest("launcher linux-x64 %s 10 file:///tmp/Hookshot.AppImage" % SHA)
        self.assertEqual(linux_upgrade.parse_manifest(text, None, local=True).line().url, "file:///tmp/Hookshot.AppImage")


class Probe(unittest.TestCase):
    def test_the_list_is_asked_for_on_the_tags_release(self):
        asked = []

        def get(url):
            asked.append(url)
            return SAMPLE.replace("v3.0.0", "v3.0.0-rc.1").encode()
        with mock.patch.dict(os.environ, {"HOOKSHOT_LAUNCHER_LIST": ""}):
            self.assertEqual(linux_upgrade.probe("v3.0.0-rc.1", get).tag, "v3.0.0-rc.1")
            nightly = "v2.3.0-12-g1a2b3c4"
            linux_upgrade.probe(nightly, lambda url: asked.append(url) or SAMPLE.replace("v3.0.0", nightly).encode())
            linux_upgrade.probe(None, lambda url: asked.append(url) or SAMPLE.encode())
        self.assertEqual(asked, [
            "https://github.com/NotRexed/Hookshot/releases/download/v3.0.0-rc.1/hookshot-launcher.txt",
            "https://github.com/NotRexed/Hookshot/releases/download/nightly/hookshot-launcher.txt",
            "https://github.com/NotRexed/Hookshot/releases/latest/download/hookshot-launcher.txt"])

    def test_a_404_is_a_builder_release(self):
        def missing(url):
            raise http_error(url, 404)
        with mock.patch.dict(os.environ, {"HOOKSHOT_LAUNCHER_LIST": ""}):
            self.assertIsNone(linux_upgrade.probe("v2.3.0", missing))
            self.assertIsNone(linux_upgrade.probe("v2.3.0", lambda url: None))

            def broken(url):
                raise http_error(url, 503)
            with self.assertRaises(urllib.error.HTTPError):   # (not an answer: the Builder does not take it for one)
                linux_upgrade.probe("v2.3.0", broken)

    def test_the_default_download_takes_a_404_without_retrying(self):
        calls = []

        def request(url, timeout, limit, stop):
            calls.append(url)
            raise http_error(url, 404)
        with mock.patch.object(linux_upgrade.linux_update, "_request", request), \
                mock.patch.object(linux_upgrade.linux_update, "fetch_bytes", side_effect=AssertionError("retried")), \
                mock.patch.dict(os.environ, {"HOOKSHOT_LAUNCHER_LIST": ""}):
            self.assertIsNone(linux_upgrade.probe("v2.3.0"))
        self.assertEqual(len(calls), 1)

    def test_the_button_is_the_upgrade_only_for_an_update_to_that_release(self):
        mode = linux_upgrade.upgrade_mode
        self.assertEqual(mode("update-game", "v3.0.0", "v3.0.0"), "upgrade")
        self.assertEqual(mode("update-builder", "v3.0.0", "v3.0.0"), "upgrade")
        self.assertEqual(mode("update-game", "v3.0.0", "v3.0.1"), "update-game")
        self.assertEqual(mode("update-game", None, "v3.0.0"), "update-game")
        self.assertEqual(mode("build", "v3.0.0", "v3.0.0"), "build")
        self.assertEqual(mode("up-to-date", "v3.0.0", "v3.0.0"), "up-to-date")


class Import(unittest.TestCase):
    def cfg(self):
        return linux_upgrade.read_ini((FIXTURES / "builder.ini").read_text(encoding="utf-8"))

    def test_the_sample_settings_make_the_sample_import(self):
        want = json.loads((FIXTURES / "import-linux.json").read_text(encoding="utf-8"))
        got = linux_upgrade.import_dict(self.cfg(), None, "v2.3.0-4-g1a2b3c4")
        self.assertEqual(got, want)
        self.assertEqual(list(got), list(want))
        self.assertEqual(list(got["settings"]), list(want["settings"]))

    def test_the_folder_is_read_for_its_version_and_language(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-import-") as tmp:
            folder = Path(tmp) / "Games" / "Hookshot é"
            folder.mkdir(parents=True)
            (folder / "hookshot_version.txt").write_text("version=v2.3.0-rc.2\nbuilder=/x\n", encoding="utf-8")
            (folder / "language.txt").write_text("fr-FR\n", encoding="utf-8")
            cfg = {"kind": "nup", "nup": "/home/player/Downloads/game.nup", "romfs": "/r", "out": "/elsewhere"}
            got = linux_upgrade.import_for(cfg, str(folder))
            self.assertEqual((got["folder"], got["version"], got["track"]), (str(folder), "v2.3.0-rc.2", "rc"))
            self.assertEqual(got["settings"]["language"], "fr-FR")
            self.assertEqual((got["settings"]["nup"], got["settings"]["romfs"]), ("/home/player/Downloads/game.nup", None))
            self.assertTrue(got["settings"]["prepareShaders"])
            # (a saved track wins; no folder given: the saved install folder, still handed over when it is no game)
            got = linux_upgrade.import_for(dict(cfg, out=str(folder), track="nightly", language="it-IT"))
            self.assertEqual((got["folder"], got["track"], got["settings"]["language"]), (str(folder), "nightly", "it-IT"))
            got = linux_upgrade.import_for({"out": str(Path(tmp) / "none")})
            self.assertEqual((got["version"], got["track"], got["settings"]["language"]), (None, "release", None))
            self.assertIsNone(linux_upgrade.import_for({}))

    def test_the_import_file_is_written_whole(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-import-") as tmp:
            data = linux_upgrade.import_dict(self.cfg(), None, "v2.3.0")
            path = linux_upgrade.write_import(data, tmp)
            again = linux_upgrade.write_import(data, tmp)   # (the same folder again: its own file replaced)
            self.assertEqual(path, again)
            self.assertEqual(os.listdir(os.path.join(tmp, "import")), [os.path.basename(path)])
            self.assertTrue(path.endswith(".json"))
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8")), data)


class Stamp(unittest.TestCase):
    def rewrite(self, text, launcher="/home/p/.local/share/hookshot/launcher/Hookshot.AppImage"):
        with tempfile.TemporaryDirectory(prefix="hookshot-stamp-") as tmp:
            if text is not None:
                Path(tmp, "hookshot_version.txt").write_text(text, encoding="utf-8")
            done = linux_upgrade.rewrite_stamp(tmp, launcher)
            path = Path(tmp, "hookshot_version.txt")
            return done, path.read_text(encoding="utf-8") if path.exists() else None

    def test_builder_names_the_launcher_and_builder_args_goes(self):
        self.assertEqual(self.rewrite("version=v2.3.0\nbuilder=/old/Hookshot.AppImage\nbuilder_args=x y\nother=1\n", "/L"),
                         (True, "version=v2.3.0\nbuilder=/L\nother=1\n"))
        self.assertEqual(self.rewrite("version=v2.3.0\r\nbuilder=/old\r\n", "/L"), (True, "version=v2.3.0\nbuilder=/L\n"))
        self.assertEqual(self.rewrite("version=v2.3.0\n", "/L"), (True, "version=v2.3.0\nbuilder=/L\n"))

    def test_a_portable_folder_or_one_with_no_stamp_is_left(self):
        text = "version=v2.3.0\nbuilder_local=1\nbuilder=/old\n"
        self.assertEqual(self.rewrite(text), (False, text))
        self.assertEqual(self.rewrite(None), (False, None))


class Install(unittest.TestCase):
    def test_the_launcher_is_installed_whole_and_runs(self):
        data = b"#!/bin/sh\necho launcher\n"
        with tempfile.TemporaryDirectory(prefix="hookshot-launcher-") as tmp:
            home = os.path.join(tmp, "launcher home")
            with mock.patch.dict(os.environ, {"HOOKSHOT_LAUNCHER_HOME": home}):
                self.assertEqual(linux_upgrade.installed_launcher(), "")
                asked = []
                path = linux_upgrade.install(offer(data).line(), lambda url: asked.append(url) or data)
                self.assertEqual(path, os.path.join(home, "Hookshot.AppImage"))
                self.assertEqual(asked, ["https://example.invalid/Hookshot.AppImage"])
                self.assertEqual(Path(path).read_bytes(), data)
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o755)
                self.assertEqual(os.listdir(home), ["Hookshot.AppImage"])
                self.assertEqual(linux_upgrade.installed_launcher(), path)
                # (a newer one replaces it, by rename)
                newer = data + b"# 3.0.1\n"
                linux_upgrade.install(offer(newer).line(), lambda url: newer)
                self.assertEqual(Path(path).read_bytes(), newer)

    def test_a_download_of_the_wrong_size_or_checksum_installs_nothing(self):
        data = b"launcher"
        with tempfile.TemporaryDirectory(prefix="hookshot-launcher-") as tmp:
            home = os.path.join(tmp, "home")
            line = offer(data).line()
            for got in (data + b"!", b"LAUNCHER"):
                with self.subTest(got=got), self.assertRaises(RuntimeError):
                    linux_upgrade.install(line, lambda url: got, home)
                self.assertFalse(os.path.exists(home))
            # (an old launcher stays as it was)
            os.makedirs(home)
            Path(home, "Hookshot.AppImage").write_bytes(b"old")
            with self.assertRaises(RuntimeError):
                linux_upgrade.install(line, lambda url: b"bad", home)
            self.assertEqual(os.listdir(home), ["Hookshot.AppImage"])
            self.assertEqual(Path(home, "Hookshot.AppImage").read_bytes(), b"old")

    def test_a_cancel_as_the_download_ends_installs_nothing(self):
        import threading
        data = b"launcher"
        stop = threading.Event()
        with tempfile.TemporaryDirectory(prefix="hookshot-launcher-") as tmp:
            home = os.path.join(tmp, "home")
            with self.assertRaises(linux_upgrade.linux_update.Cancelled):
                linux_upgrade.install(offer(data).line(), lambda url: stop.set() or data, home, stop)
            self.assertFalse(os.path.exists(home))

    def test_the_whole_upgrade_installs_imports_and_rewrites_the_stamp(self):
        data = b"#!/bin/sh\n"
        with tempfile.TemporaryDirectory(prefix="hookshot-upgrade-") as tmp:
            home, game = os.path.join(tmp, "home"), os.path.join(tmp, "game")
            os.makedirs(game)
            Path(game, "hookshot_version.txt").write_text("version=v2.3.0\nbuilder=/old\nbuilder_args=a\n", encoding="utf-8")
            notes = []
            launcher, folder = linux_upgrade.upgrade(offer(data), game, {"kind": "nup", "nup": "/g.nup"},
                                                     get=lambda url: data, note=notes.append, home=home)
            self.assertEqual((launcher, folder), (os.path.join(home, "Hookshot.AppImage"), game))
            self.assertEqual(Path(game, "hookshot_version.txt").read_text(encoding="utf-8"),
                             "version=v2.3.0\nbuilder=%s\n" % launcher)
            files = os.listdir(os.path.join(home, "import"))
            self.assertEqual(len(files), 1)
            dropped = json.loads(Path(home, "import", files[0]).read_text(encoding="utf-8"))
            self.assertEqual((dropped["folder"], dropped["version"], dropped["settings"]["nup"]), (game, "v2.3.0", "/g.nup"))
            self.assertTrue(notes)

    def test_a_failed_download_changes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-upgrade-") as tmp:
            home, game = os.path.join(tmp, "home"), os.path.join(tmp, "game")
            os.makedirs(game)
            stamp = "version=v2.3.0\nbuilder=/old\n"
            Path(game, "hookshot_version.txt").write_text(stamp, encoding="utf-8")

            def fail(url):
                raise RuntimeError("GitHub answered 502")
            with self.assertRaises(RuntimeError):
                linux_upgrade.upgrade(offer(b"x"), game, {}, get=fail, home=home)
            self.assertFalse(os.path.exists(home))
            self.assertEqual(Path(game, "hookshot_version.txt").read_text(encoding="utf-8"), stamp)

    def test_the_launcher_home(self):
        home = linux_upgrade.launcher_home
        self.assertEqual(home({"HOOKSHOT_LAUNCHER_HOME": "/h", "XDG_DATA_HOME": "/d"}), "/h")
        self.assertEqual(home({"XDG_DATA_HOME": "/d", "HOME": "/u"}), "/d/hookshot/launcher")
        self.assertEqual(home({"HOME": "/u"}), "/u/.local/share/hookshot/launcher")
        # (apart from the Builder's: its pruning never touches the launcher)
        self.assertNotEqual(home({"XDG_DATA_HOME": "/d"}), os.path.join("/d", "hookshot", "builder"))

    def test_the_launcher_starts_without_the_builders_environment(self):
        env = {"APPDIR": "/m", "APPIMAGE": "/a", "LD_LIBRARY_PATH": "/l", "HOOKSHOT_TOOLS": "/t", "EMSDK": "/e",
               "HOOKSHOT_SYSROOT": "/s", "HOME": "/u", "HOOKSHOT_NO_UPDATE_CHECK": "1", "DISPLAY": ":0"}
        self.assertEqual(linux_upgrade.clean_env(env), {"HOME": "/u", "HOOKSHOT_NO_UPDATE_CHECK": "1", "DISPLAY": ":0"})


class Forward(unittest.TestCase):
    def test_launch_and_update_go_to_an_installed_launcher(self):
        f = linux_upgrade.forward_command
        L = "/h/Hookshot.AppImage"
        self.assertEqual(f(["--launch", "/g"], L), [L, "--launch", "/g"])
        self.assertEqual(f(["--update", "/g", "--tag", "v3.0.0"], L), [L, "--update", "/g", "--tag", "v3.0.0"])
        self.assertEqual(f(["--update", "/g", "--tag", "v3.0.0", "--fetched", "--allow-downgrade-from", "v3.1.0"], L),
                         [L, "--update", "/g", "--tag", "v3.0.0", "--fetched"])
        self.assertEqual(f(["--handover", "--update", "/g"], L), [L, "--update", "/g"])
        for args in ([], ["--play"], ["--play", "/g"], ["--launch"], ["--update", ""]):
            self.assertIsNone(f(args, L), args)
        self.assertIsNone(f(["--launch", "/g"], ""))

    def test_the_builder_forwards_before_anything_else(self):
        source = (ROOT / "builder" / "linux" / "hookshot_builder.py").read_text(encoding="utf-8")
        main = source[source.index("def main():"):]
        self.assertLess(main.index("linux_upgrade.forward_command(sys.argv[1:], linux_upgrade.installed_launcher())"),
                        main.index("Builder("))

    def test_apprun_opens_the_bridge_without_the_build_tools(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-bridge-") as tmp:
            root = Path(tmp)
            shutil.copyfile(ROOT / "builder" / "linux" / "AppRun", root / "AppRun")
            (root / "AppRun").chmod(0o755)
            tools = root / "usr" / "share" / "hookshot"
            (tools / "builder" / "linux").mkdir(parents=True)
            python = root / "usr" / "python" / "bin" / "python3"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
            python.chmod(0o755)
            launch = tools / "builder" / "linux" / "hookshot-launch"
            launch.write_text("#!/bin/sh\necho play \"$@\"\n", encoding="utf-8")
            launch.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}

            def run(*args):
                return subprocess.run([str(root / "AppRun"), *args], env=env, capture_output=True, text=True,
                                      check=True).stdout.split()
            builder = str(tools / "builder" / "linux" / "hookshot_builder.py")
            self.assertEqual(run(), ["-I", builder, "--handover"])
            self.assertEqual(run("--update", "/g", "--tag", "v3.0.0", "--fetched"),
                             ["-I", builder, "--handover", "--update", "/g", "--tag", "v3.0.0", "--fetched"])
            self.assertEqual(run("--play", "/g"), ["play", "/g"])
            (tools / "nx2").mkdir()
            (tools / "nx2" / "make_game.py").write_text("", encoding="utf-8")
            self.assertEqual(run("--launch", "/g"), ["-I", builder, "--launch", "/g"])


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Builder(unittest.TestCase):
    """The Tk Builder's own begin_update, apply_mode and main, compiled from its text with no Tk: the window is a stand-in"""

    def functions(self, names, scope, cls=True):
        import ast
        tree = ast.parse((ROOT / "builder" / "linux" / "hookshot_builder.py").read_text(encoding="utf-8"))
        body = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Builder").body if cls else tree.body
        nodes = [n for n in body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual(len(nodes), len(names))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "hookshot_builder.py", "exec"), scope)
        return scope

    def window(self, offer):
        import threading
        import types
        import linux_update
        events = []
        scope = self.functions({"begin_update", "apply_mode", "older_ok"}, dict(
            os=os, linux_update=linux_update, linux_upgrade=linux_upgrade, launcher_offer=lambda tag, quiet=True: offer,
            folder_has_dlss=lambda _: False, tk=types.SimpleNamespace(TclError=RuntimeError),
            messagebox=types.SimpleNamespace(askyesno=lambda *a: events.append("confirm") or True),
            threading=types.SimpleNamespace(Thread=lambda target, daemon: types.SimpleNamespace(start=target))))
        button = types.SimpleNamespace(text="", winfo_exists=lambda: True, configure=lambda **kw: setattr(button, "text", kw.get("text", "")))
        w = types.SimpleNamespace(tools="v2.3.0", latest="v3.0.0", source_picked=False, update_tag=None, fetched=False,
                                  update_folder="", out=Value("/games/Hookshot"), switching=lambda: False, launch_folder="",
                                  build_button=button, status=Value(), stop_update=threading.Event(), launcher=None,
                                  launcher_for=None, mode="build", dlss_toggled=False,
                                  show_progress=lambda title: events.append("progress"),
                                  show_handover=lambda folder, found: events.append(("handover", folder, found)))
        w.lines = types.SimpleNamespace(put=events.append)
        for name in ("begin_update", "apply_mode", "older_ok"):
            setattr(w, name, types.MethodType(scope[name], w))
        return w, events

    def test_an_update_to_a_launcher_release_opens_the_hand_over_and_installs_nothing(self):
        release = linux_upgrade.parse_manifest(SAMPLE, "v3.0.0")
        w, events = self.window(release)
        with mock.patch.object(linux_upgrade.linux_update, "game_version", return_value=("v2.3.0", True)), \
                mock.patch.object(linux_upgrade.linux_update, "install", side_effect=AssertionError("installed")), \
                mock.patch.object(linux_upgrade.linux_update, "startup_manifest", side_effect=AssertionError("listed")):
            w.begin_update("/games/Hookshot")
        self.assertEqual(events, ["progress", ("handover", ("/games/Hookshot", release))])
        # (the target already known to be one: straight to the hand-over, no page and no thread)
        w, events = self.window(None)
        w.launcher, w.launcher_for = release, "v3.0.0"
        w.begin_update("/games/Hookshot")
        self.assertEqual(events, [("handover", "/games/Hookshot", release)])

    def test_the_button_says_upgrade(self):
        w, events = self.window(None)
        with mock.patch.object(linux_upgrade.linux_update, "game_version", return_value=("v2.3.0", True)):
            w.apply_mode()
            self.assertEqual((w.mode, w.build_button.text), ("update-game", "Update"))
            w.launcher, w.launcher_for = linux_upgrade.parse_manifest(SAMPLE, "v3.0.0"), "v3.0.0"
            w.apply_mode()
        self.assertEqual((w.mode, w.build_button.text), ("upgrade", "Upgrade"))
        self.assertIn("Hookshot Launcher", w.status.get())

    def test_main_hands_launch_and_update_to_an_installed_launcher(self):
        import types
        ran = []

        class Started(BaseException):
            pass

        def execve(path, args, env):
            ran.append((path, args, "HOOKSHOT_TOOLS" in env))
            raise Started()
        with tempfile.TemporaryDirectory(prefix="hookshot-forward-") as tmp:
            launcher = Path(tmp, "Hookshot.AppImage")
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o755)
            for argv, forwarded in ((["--launch", "/g"], True), (["--update", "/g", "--tag", "v3.0.0"], True), (["--play"], False)):
                ran.clear()
                scope = self.functions({"main"}, dict(
                    sys=types.SimpleNamespace(argv=["hookshot_builder.py"] + argv), linux_upgrade=linux_upgrade,
                    os=types.SimpleNamespace(execve=execve), _arg=lambda name: None, load_config=dict, game_ready=lambda f: False,
                    Builder=lambda **kw: types.SimpleNamespace(mainloop=lambda: ran.append("window"))), cls=False)
                with mock.patch.dict(os.environ, {"HOOKSHOT_LAUNCHER_HOME": tmp, "HOOKSHOT_TOOLS": "/t"}):
                    if forwarded:
                        self.assertRaises(Started, scope["main"])
                        self.assertEqual(ran, [(str(launcher), [str(launcher)] + argv, False)])
                    else:
                        scope["main"]()
                        self.assertEqual(ran, ["window"])


@unittest.skipUnless(shutil.which("cc"), "a C compiler")
class GameOffer(unittest.TestCase):
    """host/hos_update.c on Linux: the update offer starts an installed launcher before the installed 2.x Builder"""

    def test_installed_launcher(self):
        source = (ROOT / "host" / "hos_update.c").read_text(encoding="utf-8")
        start = source.index("static int installed_launcher(")
        piece = source[start:source.index("\n}\n", start) + 3]
        self.assertLess(source.index("installed_launcher(builder, sizeof builder) || installed_builder(builder, sizeof builder)"),
                        source.index("execl(builder, builder, \"--update\""))
        program = ("#include <stdio.h>\n#include <stdlib.h>\n#include <sys/stat.h>\n#include <unistd.h>\n" + piece +
                   "int main(void) { char out[4096]; int ok = installed_launcher(out, sizeof out); "
                   "printf(\"%d %s\\n\", ok, out); return 0; }\n")
        with tempfile.TemporaryDirectory(prefix="hookshot-offer-") as tmp:
            root = Path(tmp)
            (root / "t.c").write_text(program, encoding="utf-8")
            subprocess.run(["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Werror", str(root / "t.c"), "-o",
                            str(root / "t")], check=True)

            def found(**env):
                ran = subprocess.run([str(root / "t")], env=env, capture_output=True, text=True, check=True).stdout.split(" ", 1)
                return ran[0] == "1", ran[1].strip()
            data, home = root / "data", root / "home"
            self.assertEqual(found(XDG_DATA_HOME=str(data)), (False, str(data / "hookshot/launcher/Hookshot.AppImage")))
            appimage = data / "hookshot" / "launcher" / "Hookshot.AppImage"
            appimage.parent.mkdir(parents=True)
            appimage.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertFalse(found(XDG_DATA_HOME=str(data))[0])   # (not executable)
            appimage.chmod(0o755)
            self.assertEqual(found(XDG_DATA_HOME=str(data)), (True, str(appimage)))
            self.assertEqual(found(HOME=str(root / "u")), (False, str(root / "u/.local/share/hookshot/launcher/Hookshot.AppImage")))
            (home / "Hookshot.AppImage").mkdir(parents=True)   # (a folder is no launcher)
            self.assertFalse(found(HOOKSHOT_LAUNCHER_HOME=str(home), XDG_DATA_HOME=str(data))[0])


if __name__ == "__main__":
    unittest.main()
