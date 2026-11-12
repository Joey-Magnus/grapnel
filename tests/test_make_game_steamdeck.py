"""The optional Deck preparation flags fail early without reading game data."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_game_deck", ROOT / "nx2/make_game.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)


class DeckArgumentsTests(unittest.TestCase):
    def parse(self, *args, linux=True):
        with mock.patch.object(sys, "argv", ["make_game.py", *args]), mock.patch.object(make, "LINUX", linux):
            return make.parse_args()

    def refused(self, *args, linux=True):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            self.parse(*args, linux=linux)
        return output.getvalue()

    def test_default_build_does_not_request_ssh_or_deck_preparation(self):
        self.assertIsNone(self.parse("--out", "game").steamdeck)

    def test_host_is_preserved_as_one_argument(self):
        self.assertEqual(self.parse("--steamdeck", "deck@192.168.1.20").steamdeck, "deck@192.168.1.20")

    def test_conflicting_preparation_options_are_rejected(self):
        self.assertIn("cannot be combined", self.refused("--steamdeck", "deck@steamdeck", "--no-prepare-shaders"))

    def test_windows_target_is_rejected_before_a_build(self):
        self.assertIn("native Linux build", self.refused("--steamdeck", "deck@steamdeck", linux=False))

    def test_ssh_options_and_shell_syntax_are_rejected(self):
        self.assertIn("SSH address", self.refused("--steamdeck", "deck@host; command"))
        self.assertIn('SSH address', self.refused('--steamdeck', ''))


if __name__ == "__main__":
    unittest.main()
