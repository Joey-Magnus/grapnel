"""The CPU flags a build compiled with are recorded, and only the log's file is rebuilt for them.

nx2/compile_flags.py is the one list. nx2/build.py compiles every object with that list, and passes
-DHOOKSHOT_COMPILE_FLAGS to host/hos_main.c alone, the same way -DHOOKSHOT_VERSION reaches the menu
(tests/test_shader_stamp_cache.py checks the menu, and that the renderer does not get this define).
hos_main.c prints it as the log's second line. nx2/make_game.py writes hookshot_flags.txt even when
there is no release name for hookshot_version.txt. The compiler check passes that -D as one argument,
quotes included, as nx2/build.py's compile_one does. Game-free.

    python -I -B tests/test_compile_flags.py [--cc gcc]
"""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import warnings
from types import SimpleNamespace
from unittest import mock

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import compile_flags  # noqa: E402
import host_cpu  # noqa: E402

CC = "gcc"
BUILD = ROOT / "nx2" / "build.py"
LOG_LINE = 'hos_log("compile flags: %s", HOOKSHOT_COMPILE_FLAGS);'
VERSION_LINE = 'hos_log("hookshot %s", HOOKSHOT_VERSION);'


def source_of(path):
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text, filename=str(path))


def segment(text, node):
    found = ast.get_source_segment(text, node)
    if not found:
        raise AssertionError("no source for %s" % type(node).__name__)
    return found


class CpuFlags(unittest.TestCase):
    def test_march_contract_and_extra(self):
        flags = compile_flags.cpu_flags("rocketlake", "", "-mprefer-vector-width=256")
        self.assertEqual(flags, ["-march=rocketlake", "-ffp-contract=off", "-mprefer-vector-width=256"])

    def test_mtune_when_set(self):
        flags = compile_flags.cpu_flags("x86-64-v3", "znver2", "")
        self.assertEqual(flags, ["-march=x86-64-v3", "-ffp-contract=off", "-mtune=znver2"])

    def test_contract_stays_off(self):
        flags = compile_flags.cpu_flags("x86-64-v3", "", "-ffp-contract=fast -mprefer-vector-width=256")
        self.assertEqual(flags.count("-ffp-contract=off"), 1)
        self.assertNotIn("-ffp-contract=fast", flags)
        self.assertIn("-mprefer-vector-width=256", flags)

    def test_include_paths_are_not_cpu_flags(self):
        flags = compile_flags.cpu_flags("x86-64-v3", "", "-I/tmp --sysroot=/tmp -mprefer-vector-width=256")
        self.assertEqual(flags, ["-march=x86-64-v3", "-ffp-contract=off", "-mprefer-vector-width=256"])

    def test_text_is_safe_for_a_c_string(self):
        flags = compile_flags.cpu_flags('x86-64-v3"\\', "", "")
        text = compile_flags.text(flags)
        self.assertNotIn('"', text)
        self.assertNotIn("\\", text)
        self.assertNotIn("\n", text)
        self.assertTrue(text.startswith("-march="))
        self.assertIn("-ffp-contract=off", text)

    def test_define_matches_the_text(self):
        flags = compile_flags.cpu_flags("rocketlake", "", "-mprefer-vector-width=256")
        self.assertEqual(compile_flags.define(flags), '-DHOOKSHOT_COMPILE_FLAGS="%s"' % compile_flags.text(flags))

    def test_current_follows_the_build_environment(self):
        env = {"RX_MARCH": "rocketlake", "RX_MTUNE": "znver2", "RX_CPU_FLAGS": "-mprefer-vector-width=256"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(compile_flags.current(),
                             ["-march=rocketlake", "-ffp-contract=off", "-mtune=znver2", "-mprefer-vector-width=256"])

    def test_current_uses_this_pc_when_nothing_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(host_cpu, "host_march", return_value="x86-64-v2"), \
                mock.patch.object(host_cpu, "host_mtune", return_value=""):
            self.assertEqual(compile_flags.current(), ["-march=x86-64-v2", "-ffp-contract=off"])

    def test_steam_deck_tune_is_recorded_when_no_tune_was_set(self):
        with mock.patch.dict(os.environ, {"RX_MARCH": "x86-64-v3", "RX_STEAMDECK": "1"}, clear=True):
            self.assertEqual(compile_flags.current(),
                             ["-march=x86-64-v3", "-ffp-contract=off", "-mtune=znver2"])


class RecordFile(unittest.TestCase):
    def recorded(self, folder, flags):
        data = (Path(folder) / "hookshot_flags.txt").read_bytes()
        self.assertNotIn(b"\r", data)   # (newline="\n": Windows does not rewrite the line)
        self.assertEqual(data.decode("utf-8"), "flags=%s\n" % compile_flags.text(flags))

    def test_writes_hookshot_flags_beside_the_version_file(self):
        flags = compile_flags.cpu_flags("rocketlake", "", "-mprefer-vector-width=256")
        with tempfile.TemporaryDirectory() as folder:
            version = Path(folder) / "hookshot_version.txt"
            version.write_text("version=v2.1.0\n", encoding="utf-8")
            compile_flags.write(folder, flags)
            self.recorded(folder, flags)
            self.assertEqual(version.read_text(encoding="utf-8"), "version=v2.1.0\n")

    def test_a_folder_without_a_version_file_still_gets_the_flags(self):
        flags = compile_flags.cpu_flags("x86-64-v3", "", "")
        with tempfile.TemporaryDirectory() as folder:
            compile_flags.write(folder, flags)
            self.recorded(folder, flags)
            self.assertFalse((Path(folder) / "hookshot_version.txt").exists())

    def test_write_without_a_list_uses_the_environment(self):
        env = {"RX_MARCH": "rocketlake", "RX_MTUNE": "znver2", "RX_CPU_FLAGS": "-mprefer-vector-width=256"}
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, env, clear=True):
            compile_flags.write(folder)
            self.recorded(folder, compile_flags.current())


class WiredIn(unittest.TestCase):
    def test_the_log_prints_the_recorded_flags_second(self):
        main = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
        self.assertIn('#define HOOKSHOT_COMPILE_FLAGS ""', main)
        version_at = main.index(VERSION_LINE)
        flags_at = main.index(LOG_LINE)
        self.assertLess(version_at, flags_at)
        between = main[version_at + len(VERSION_LINE):flags_at]
        self.assertNotIn("hos_log(", between)

    def test_build_uses_the_one_list(self):
        text, tree = source_of(BUILD)
        assign = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "CPU" for t in n.targets))
        ns = {"os": os, "compile_flags": compile_flags, "MARCH": "rocketlake", "MTUNE": "znver2"}
        with mock.patch.dict(os.environ, {"RX_CPU_FLAGS": "-mprefer-vector-width=256"}, clear=True):
            exec(segment(text, assign), ns)
        self.assertEqual(ns["CPU"], compile_flags.cpu_flags("rocketlake", "znver2", "-mprefer-vector-width=256"))
        self.assertIn('print("compile flags: %s" % compile_flags.text(CPU), flush=True)', text)

    def test_every_object_gets_the_list_and_only_hos_main_gets_the_define(self):
        text, tree = source_of(BUILD)
        names = {"flags", "flag_text", "object_key"}
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in functions}, names)
        host_job = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.AugAssign) and isinstance(n.value, ast.ListComp)
                        and "flags_def" in (ast.get_source_segment(text, n) or "")
                        and "hos_main.c" in (ast.get_source_segment(text, n) or ""))
        ns = {"os": os, "hashlib": hashlib, "kit": SimpleNamespace(ROOT="/repo", KIT="/kit"), "NX2_RT": "/nx2rt",
              "WRITE_TRACK": ["-DA64_WRITE_TRACK"], "target": lambda: ["--target=x86_64-linux-gnu"]}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(BUILD), "exec"), ns)
        cpu = ["-march=rocketlake", "-ffp-contract=off", "-mprefer-vector-width=256"]
        ns["CPU"] = cpu
        lifted = ns["flags"]("gen", "rt64", "O1", True)
        self.assertEqual(lifted[:1 + len(cpu)], ["--target=x86_64-linux-gnu"] + cpu)
        self.assertFalse(any(f.startswith("-DHOOKSHOT_COMPILE_FLAGS=") for f in lifted))

        with tempfile.TemporaryDirectory() as folder:
            host = Path(folder)
            srcs = []
            for name in ("hos_main.c", "prompts.c", "nn_video.c", "other.c"):
                path = host / name
                path.write_text("int %s;\n" % name[:-2], encoding="utf-8")
                srcs.append(str(path))
            first = '-DHOOKSHOT_COMPILE_FLAGS="-march=rocketlake -ffp-contract=off"'
            second = '-DHOOKSHOT_COMPILE_FLAGS="-march=x86-64-v3 -ffp-contract=off"'
            before = self.host_jobs(text, host_job, ns, srcs, first)
            after = self.host_jobs(text, host_job, ns, srcs, second)
        self.assertEqual(set(before), {"hos_main.c", "prompts.c", "nn_video.c", "other.c"})
        self.assertIn(first, before["hos_main.c"]["flags"])
        self.assertIn('-DHOOKSHOT_VERSION="test"', before["hos_main.c"]["flags"])
        for name in ("prompts.c", "nn_video.c", "other.c"):
            self.assertNotIn(first, before[name]["flags"], name)
        changed = {name for name in before if before[name]["key"] != after[name]["key"]}
        self.assertEqual(changed, {"hos_main.c"})

    def host_jobs(self, text, node, ns, srcs, flags_def):
        job_ns = dict(ns)
        job_ns.update({"jobs": [], "cc": "clang", "host_srcs": srcs, "obj_dir": "/obj", "host_fl": ["-O2"],
                       "OPUS": "/opus", "FFMPEG": "", "LINUX": False, "FFMPEG_LX": None,
                       "stamp_def": '-DHOOKSHOT_VERSION="test"', "flags_def": flags_def, "ZSTD": "/zstd",
                       "dav1d_fl": ["-DHOOKSHOT_DAV1D"], "host_deps": b"deps", "zstd_api": b"zstd"})
        exec(segment(text, node), job_ns)
        # (object_key opens the source for the hash and does not close it: the same as test_shader_stamp_cache.py)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            return {os.path.basename(src): {"flags": flags, "key": job_ns["object_key"](src, flags, deps)}
                    for _, src, _, flags, deps in job_ns["jobs"]}

    def test_the_game_folder_is_where_the_record_is_written(self):
        text, tree = source_of(ROOT / "nx2" / "make_game.py")
        self.assertIn("import compile_flags\n", text)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "compile_flags"
                 and n.func.attr == "write"]
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual([isinstance(a, ast.Name) and a.id == "out" for a in call.args], [True])
        self.assertEqual(call.keywords, [])   # (no flag list: the file is what this build compiled with)
        at = call
        while at in parents:
            at = parents[at]
            if isinstance(at, ast.If) and any(isinstance(n, ast.Name) and n.id == "tag" for n in ast.walk(at.test)):
                self.fail("compile_flags.write sits inside if tag: a source build with no VERSION file records nothing")


class CompiledDefine(unittest.TestCase):
    def run_fixture(self, define):
        host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
        block = re.search(r"#ifndef HOOKSHOT_COMPILE_FLAGS\b.*?#endif\n", host, re.S)
        self.assertIsNotNone(block, "host/hos_main.c has no default for HOOKSHOT_COMPILE_FLAGS")
        src = block.group(0) + r'''
#include <stdio.h>
int main(void) {
    printf("compile flags: %s\n", HOOKSHOT_COMPILE_FLAGS);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            path, exe = Path(folder) / "flags.c", Path(folder) / "flags.exe"
            path.write_text(src, encoding="utf-8")
            cmd = [CC, "-std=c11", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(exe)]
            if define:
                cmd.insert(1, define)   # (one argument, as compile_one's [cc] + flags)
            built = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
            return ran.stdout

    def test_the_define_compiles_to_the_log_line(self):
        flags = compile_flags.cpu_flags("rocketlake", "", "-mprefer-vector-width=256")
        self.assertEqual(self.run_fixture(compile_flags.define(flags)),
                         "compile flags: %s\n" % compile_flags.text(flags))

    def test_without_the_define_the_log_line_is_empty(self):
        self.assertEqual(self.run_fixture(None), "compile flags: \n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args, rest = parser.parse_known_args()
    CC = args.cc
    unittest.main(argv=[sys.argv[0], *rest])
