"""Build metadata survives publication and is the same text the compiled host logs; no game files."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import build_flags


class BuildFlagsTests(unittest.TestCase):
    def test_record_keeps_cpu_and_distinct_optimization_flags(self):
        spec = importlib.util.spec_from_file_location("build_flags_under_test", ROOT / "nx2" / "build.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        cpu = ["-march=rocketlake", "-mtune=znver2", "-ffp-contract=off", "-mprefer-vector-width=256"]
        base = cpu + ["-I" + str(ROOT / "host"), "--sysroot=/temporary mount", "-O1"]
        record = build_flags.describe(cpu, base, base[:-1] + ["-O2"], cpu + ["-O2"], build.flag_text)
        data = json.loads(record)
        self.assertEqual(data["cpu"], cpu)
        self.assertIn("-O1", data["lifted"])
        self.assertIn("-O2", data["hot"])
        self.assertIn("--sysroot=<sysroot>", data["lifted"])
        self.assertNotIn(str(ROOT), record)
        self.assertNotIn("temporary mount", record)
        self.assertNotIn('"-I', record)

    def test_compiled_definition_matches_published_record(self):
        # Quotes, slashes, controls and non-ASCII text must remain data in the compiler argument.
        cpu = ['-march=example"\\\n\t\u6f22%PATH%']
        record = build_flags.describe(cpu, cpu, cpu, cpu, " ".join)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "flags.cpp"
            exe = Path(folder) / ("flags.exe" if os.name == "nt" else "flags")
            source.write_text('#include <stdio.h>\nint main() { return puts(HOOKSHOT_BUILD_FLAGS) < 0; }\n', encoding="utf-8")
            subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", build_flags.define(record),
                            str(source), "-o", str(exe)], check=True, capture_output=True)
            build_flags.write(folder, record)
            compiled = subprocess.check_output([str(exe)]).decode("ascii").replace("\r\n", "\n")
            self.assertEqual(compiled, (Path(folder) / build_flags.FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(json.loads(compiled)["cpu"], cpu)

    def test_failed_publication_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / build_flags.FILENAME
            path.write_text("previous build\n", encoding="utf-8")
            with mock.patch.object(build_flags.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    build_flags.write(folder, "new build")
            self.assertEqual(path.read_text(encoding="utf-8"), "previous build\n")
            self.assertEqual(list(Path(folder).iterdir()), [path])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args, remaining = parser.parse_known_args()
    CXX = args.cxx
    unittest.main(argv=[sys.argv[0]] + remaining)
