"""The build records the CPU flags it compiled with, in the game folder and in the binary the log prints.

Game-free. Issue 2576.

    python -I -B tests/test_compile_flags.py
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import compile_flags  # noqa: E402


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


class RecordFile(unittest.TestCase):
    def test_writes_hookshot_flags_beside_the_version_file(self):
        flags = compile_flags.cpu_flags("rocketlake", "", "-mprefer-vector-width=256")
        with tempfile.TemporaryDirectory() as folder:
            version = Path(folder) / "hookshot_version.txt"
            version.write_text("version=v2.1.0\n", encoding="utf-8")
            compile_flags.write(folder, flags)
            recorded = (Path(folder) / "hookshot_flags.txt").read_text(encoding="utf-8")
            self.assertEqual(recorded, "flags=%s\n" % compile_flags.text(flags))
            self.assertEqual(version.read_text(encoding="utf-8"), "version=v2.1.0\n")


class WiredIn(unittest.TestCase):
    def test_the_log_prints_the_recorded_flags(self):
        main = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
        self.assertIn("HOOKSHOT_COMPILE_FLAGS", main)
        self.assertIn('hos_log("compile flags: %s", HOOKSHOT_COMPILE_FLAGS)', main)

    def test_only_hos_main_is_rebuilt_for_a_new_record(self):
        build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        self.assertIn("compile_flags.define(CPU)", build)
        self.assertIn('([stamp_def, flags_def] if os.path.basename(s) == "hos_main.c" else [])', build)
        self.assertNotIn("flags_def", build[build.index("vk_menu.cpp"):])

    def test_the_game_folder_is_where_the_record_is_written(self):
        make_game = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        self.assertIn("compile_flags.write(out)", make_game)


if __name__ == "__main__":
    unittest.main()
