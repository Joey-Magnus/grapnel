"""The game folder's launcher page draws its hero from the player's own folder, never from art the repository ships
(CONTRIBUTING.md, "The rule with no exceptions"), and the window drives it the way the mockup lays it out.

python -I -B tests/test_builder_launch_hero.py
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "builder" / "py" / "hookshot_builder" / "launch_page.py").read_text(encoding="utf-8")
WINDOW = (ROOT / "builder" / "py" / "hookshot_builder" / "window.py").read_text(encoding="utf-8")


def body_of(source, start_marker, end_marker):
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start + len(start_marker))]


class LaunchHeroTests(unittest.TestCase):
    def test_hero_is_read_from_the_game_folder_only(self):
        body = body_of(PAGE, "def hero_file", "\n\n")
        self.assertIn("os.path.join(folder, HERO_FILE)", body)
        self.assertNotIn("ASSETS", body)
        self.assertIn('HERO_FILE = "hookshot_hero.png"', PAGE)

    def test_the_builder_ships_no_hero_art(self):
        """The launcher's own assets are the hookshot item and the fonts; no hero picture, no screenshot of the game."""
        assets = ROOT / "builder" / "py" / "hookshot_builder" / "assets"
        names = [p.name.lower() for p in assets.rglob("*") if p.is_file()]
        self.assertFalse([n for n in names if n.startswith("hero") or n.endswith((".jpg", ".jpeg"))])

    def test_the_window_drives_the_new_page(self):
        body = body_of(WINDOW, "def _launch_page", "\n    def ")
        self.assertIn("launch_page.LaunchPage", body)
        self.assertIn("self.launch_page.set_hero(folder)", WINDOW)   # (show_launcher: the folder's own picture, if any)
        self.assertIn("self.launch_page.set_ready(", WINDOW)
        self.assertIn("Hookshot: Update available:", WINDOW)          # (the footer strip's sentence)
        self.assertIn("Version %s → %s", WINDOW)                      # (the mockup's version chain)

    def test_the_preview_fakes_a_built_folder_not_a_game(self):
        """HOOKSHOT_UI_PREVIEW=launch invents the names a built folder keeps; nothing is read from a dump (no game in CI)."""
        body = body_of(WINDOW, "def preview_game_folder", "\n    # ================= 1: game files")
        for made_up in ("hookshot_version.txt", '"bin"', ".hookshot_exefs", "romfs"):
            self.assertIn(made_up, body)
        for game_data in (".nup", ".nca", ".xci", "work/", "image.bin"):
            self.assertNotIn(game_data, body)


if __name__ == "__main__":
    unittest.main()
