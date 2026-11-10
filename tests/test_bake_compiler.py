"""Check the compiler choice used by the offline shader-bake helper."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import bake_mimo


class BakeCompilerSelectionTests(unittest.TestCase):
    def test_bake_cxx_overrides_cxx(self):
        with patch.dict(os.environ, {"BAKE_CXX": "custom-bake-cxx", "CXX": "g++"}):
            self.assertEqual(bake_mimo.cxx(), "custom-bake-cxx")

    def test_standard_cxx_environment_is_honored(self):
        with patch.dict(os.environ, {"BAKE_CXX": "", "CXX": "g++"}):
            self.assertEqual(bake_mimo.cxx(), "g++")

    def test_gcc_is_the_default_when_no_compiler_is_selected(self):
        found = {"g++": "/usr/bin/g++", "clang++": "/usr/bin/clang++"}
        with patch.dict(os.environ, {"BAKE_CXX": "", "CXX": ""}), \
             patch.object(bake_mimo.shutil, "which", side_effect=found.get):
            self.assertEqual(bake_mimo.cxx(), "/usr/bin/g++")


if __name__ == "__main__":
    unittest.main(verbosity=2)
