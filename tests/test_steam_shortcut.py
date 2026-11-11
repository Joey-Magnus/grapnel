"""Add to Steam (builder/linux/steam_shortcut.py) writes a shortcuts.vdf Steam loads: the root dict and its two closing 0x08,
the entry's app id crc32(Exe + AppName) | 0x80000000, the entries already there kept byte for byte, the same folder updated in
place (no second entry), a backup of the file as it was, every account, and nothing written while Steam runs. All in a
temporary Steam folder of its own making.

python -I -B tests/test_steam_shortcut.py
"""
import binascii
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

RUN_ALL_SKIP = {"windows": "Steam's Linux folders (the Steam Deck); the Windows builder has no Add to Steam"}

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import steam_shortcut as ss  # noqa: E402


def existing_vdf():
    """A shortcuts.vdf as Steam writes one, with another game in it (built by hand, not through the module)"""
    def s(k, v):
        return b"\x01" + k + b"\x00" + v + b"\x00"

    def i(k, v):
        return b"\x02" + k + b"\x00" + struct.pack("<I", v)
    other = (b"\x000\x00" + i(b"appid", 0x9234ABCD) + s(b"AppName", b"Other Game") + s(b"Exe", b'"/opt/other/run"') +
             s(b"StartDir", b'"/opt/other/"') + b"\x00tags\x00" + s(b"0", b"favorite") + b"\x08" + b"\x08")
    return b"\x00shortcuts\x00" + other + b"\x08\x08", other


class SteamShortcut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.steam = t / "Steam"
        self.vdf = self.steam / "userdata" / "123456" / "config" / "shortcuts.vdf"
        self.vdf.parent.mkdir(parents=True)
        (self.steam / "userdata" / "0").mkdir()   # (Steam's "no account" folder: never written)
        self.game = t / "Games" / "Hookshot"
        self.game.mkdir(parents=True)
        (self.game / "image.bin").write_bytes(b"")
        (self.game / "hookshot").write_text("#!/bin/sh\n")
        (self.game / "hookshot.png").write_bytes(b"\x89PNG")
        self.proc = t / "proc"   # (no Steam process)
        self.proc.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        return ss.add(str(self.game), [str(self.steam)], proc=str(self.proc), now=1700000000, **kw)

    def test_new_file(self):
        done = self.add()
        self.assertEqual(done, [(str(self.vdf), "added")])
        data = self.vdf.read_bytes()
        self.assertTrue(data.startswith(b"\x00shortcuts\x00\x000\x00"))
        self.assertTrue(data.endswith(b"\x08\x08\x08"), "the entry, the root and the document must each end with 0x08")
        entries = ss.read_entries(data)
        self.assertEqual(len(entries), 1)
        e = dict(entries[0][1])
        exe = '"%s"' % (self.game / "hookshot")
        self.assertEqual(e["Exe"], exe)
        self.assertEqual(e["StartDir"], '"%s/"' % self.game)
        self.assertEqual(e["AppName"], ss.NAME)
        self.assertEqual(e["icon"], str(self.game / "hookshot.png"))
        want = (binascii.crc32((exe + ss.NAME).encode()) & 0xFFFFFFFF) | 0x80000000
        self.assertEqual(e["appid"], want)
        self.assertTrue(e["appid"] & 0x80000000)
        self.assertFalse((self.steam / "userdata" / "0" / "config").exists(), "the 0 account was written")
        self.assertFalse(Path(str(self.vdf) + ".bak").exists(), "no backup of a file that was not there")

    def test_existing_kept_and_updated_in_place(self):
        data, other = existing_vdf()
        self.vdf.write_bytes(data)
        self.assertEqual(self.add()[0][1], "added")
        once = self.vdf.read_bytes()
        self.assertIn(other, once, "the other game's entry is not kept as it was")
        self.assertEqual(Path(str(self.vdf) + ".bak").read_bytes(), data, "no backup of the file as it was")
        entries = ss.read_entries(once)
        self.assertEqual([k for k, _ in entries], ["0", "1"])
        self.assertEqual(dict(entries[0][1])["AppName"], "Other Game")
        self.assertEqual(dict(dict(entries[0][1])["tags"]), {"0": "favorite"})
        # (the same folder again: its entry updated, not a second one)
        self.assertEqual(self.add()[0][1], "updated")
        twice = self.vdf.read_bytes()
        self.assertEqual(len(ss.read_entries(twice)), 2)
        self.assertEqual(twice, once)
        self.assertTrue(twice.endswith(b"\x08\x08"))

    def test_round_trip(self):
        data, _ = existing_vdf()
        self.assertEqual(ss.write_entries(ss.read_entries(data)), data)

    def test_steam_running(self):
        (self.steam / "steam.pid").write_text("4242\n")
        (self.proc / "4242").mkdir()
        (self.proc / "4242" / "comm").write_text("steam\n")
        with self.assertRaises(ValueError):
            self.add()
        self.assertFalse(self.vdf.exists(), "written while Steam runs")
        (self.proc / "4242" / "comm").write_text("bash\n")   # (a stale pid file: another process has the number now)
        self.assertEqual(self.add()[0][1], "added")

    def test_every_account_and_none(self):
        second = self.steam / "userdata" / "987" / "config" / "shortcuts.vdf"
        second.parent.mkdir(parents=True)
        self.assertEqual(sorted(f for f, _ in self.add()), sorted([str(self.vdf), str(second)]))
        with self.assertRaises(ValueError):
            ss.add(str(self.game), [str(Path(self.tmp.name) / "nothing")], proc=str(self.proc))

    def test_dry_run_writes_nothing(self):
        self.add(dry_run=True)
        self.assertFalse(self.vdf.exists())

    def test_roots_from_environment(self):
        self.assertEqual(ss.steam_roots(environ={"HOOKSHOT_STEAM_ROOT": str(self.steam)}), [str(self.steam)])
        home = Path(self.tmp.name) / "home"
        (home / ".local" / "share" / "Steam" / "userdata").mkdir(parents=True)
        (home / ".steam").mkdir()
        os.symlink(home / ".local" / "share" / "Steam", home / ".steam" / "steam")
        self.assertEqual(ss.steam_roots(str(home), environ={}), [os.path.realpath(home / ".local" / "share" / "Steam")])

    def test_builder_button(self):
        src = (ROOT / "builder" / "linux" / "hookshot_builder.py").read_text(encoding="utf-8")
        self.assertIn("import steam_shortcut", src)
        self.assertEqual(src.count('text="Add to Steam"'), 2, "Add to Steam on the launcher and on the finished build")


if __name__ == "__main__":
    unittest.main()
