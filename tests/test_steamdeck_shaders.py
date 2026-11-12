"""Game-free checks of Deck driver capture, isolation and cache compatibility."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("steamdeck_shaders", ROOT / "nx2/steamdeck_shaders.py")
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)


class DeckShadersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("sys", SimpleNamespace(platform="linux", executable=sys.executable)),
                            ("platform", SimpleNamespace(machine=lambda: "x86_64"))):
            patch = mock.patch.object(deck, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.root = Path(self.tmp.name)
        self.profile = dict(api=1, driver=2, vendor=0x1002, device=0x163f, name="authored test device",
                            cache_uuid="0123456789abcdef" * 2)
        self.data = {name: b"authored library placeholder: " + name.encode()
                     for name in ("libvulkan_radeon.so", "libamdgpu_noop_drm_shim.so")}
        self.manifest = dict(profile=self.profile, files=[
            dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in self.data.items()])

    def test_ssh_destination_does_not_accept_options_or_shell_code(self):
        for value in ("-oProxyCommand=bad", "deck@host;echo bad", "deck@host\nbad", "user@host:22", "$(id)"):
            with self.subTest(value=value), self.assertRaises(deck.DeckError):
                deck.target(value)
        self.assertEqual(deck.target(" deck@192.168.1.20 "), "deck@192.168.1.20")
        with mock.patch.object(deck.shutil, "which", return_value="/usr/bin/ssh"):
            args = deck.ssh_command("deck@steamdeck", "print('quoted $ remains data')")
        self.assertEqual(args[-2], "deck@steamdeck")
        self.assertIn("--", args)
        self.assertTrue(args[-1].startswith("python3 -c "))

    def test_snapshot_refuses_paths_core_libc_and_bad_checksums(self):
        for name in ("../libbad.so", "/usr/lib/libbad.so", "libc.so.6", "libbad.so;touch"):
            manifest = json.loads(json.dumps(self.manifest))
            manifest["files"][0]["name"] = name
            with self.subTest(name=name), self.assertRaises(deck.DeckError):
                deck.validate_manifest(manifest)
        self.manifest["files"][0]["sha256"] = "not a checksum"
        with self.assertRaises(deck.DeckError):
            deck.validate_manifest(self.manifest)

    def test_only_the_prepare_child_receives_the_driver_environment(self):
        original = dict(PATH="/usr/bin", HOME="/home/player", DISPLAY=":0", WAYLAND_DISPLAY="wayland-0",
                        VK_ICD_FILENAMES="/wrong.json", RADV_PERFTEST="test", MESA_VK_DEVICE_SELECT="other",
                        LD_PRELOAD="/overlay.so", KEPT="yes")
        env = deck.driver_environment(self.root, original)
        self.assertEqual(original["DISPLAY"], ":0")
        self.assertNotIn("DISPLAY", env)
        self.assertNotIn("VK_ICD_FILENAMES", env)
        self.assertNotIn("RADV_PERFTEST", env)
        self.assertEqual(env["AMDGPU_GPU_ID"], "vangogh")
        self.assertNotIn('MESA_SHADER_CACHE_DISABLE', env)
        # Temporary paths can use Windows 8.3 aliases; the helper resolves its bundle.
        self.assertEqual(env["LD_PRELOAD"], str(self.root.resolve() / "libamdgpu_noop_drm_shim.so"))
        self.assertEqual(env["KEPT"], "yes")

    def test_driver_environment_uses_resolved_bundle_paths(self):
        bundle = self.root / "driver with spaces é"
        (bundle / "child").mkdir(parents=True)
        alias = bundle / "child" / ".."
        env = deck.driver_environment(alias, {})
        resolved = bundle.resolve()
        self.assertEqual(env["LD_LIBRARY_PATH"], str(resolved))
        self.assertEqual(env["LD_PRELOAD"], str(resolved / "libamdgpu_noop_drm_shim.so"))
        self.assertEqual(env["VK_DRIVER_FILES"], str(resolved / "radv-deck.json"))
        self.assertEqual(env["XDG_CACHE_HOME"], str(resolved / "cache"))

    def fake_ssh(self, args, **kw):
        if "stdout" not in kw:
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.manifest), stderr="")
        command = args[-1]
        name = next(name for name in self.data if "/usr/lib/" + name in command)
        kw["stdout"].write(self.data[name])
        return subprocess.CompletedProcess(args, 0, stderr=b"")

    def test_verified_driver_is_reused_and_corruption_is_downloaded_again(self):
        with mock.patch.object(deck.shutil, "which", return_value="/usr/bin/ssh"), \
                mock.patch.object(deck.subprocess, "run", side_effect=self.fake_ssh) as run, \
                mock.patch.object(deck, "check_driver") as check:
            first = deck.fetch_driver("deck@steamdeck", self.root, note=lambda text: None)
            self.assertEqual(run.call_count, 3)
            run.reset_mock()
            self.assertEqual(deck.fetch_driver("deck@steamdeck", self.root), first)
            self.assertEqual(run.call_count, 1)
            (first / "libvulkan_radeon.so").write_bytes(b"corrupt")
            run.reset_mock()
            deck.fetch_driver("deck@steamdeck", self.root, note=lambda text: None)
            self.assertEqual(run.call_count, 3)
            self.assertEqual((first / "libvulkan_radeon.so").read_bytes(), self.data["libvulkan_radeon.so"])
            self.assertEqual(check.call_count, 3)

    def test_changed_remote_library_does_not_publish_a_driver_bundle(self):
        self.manifest["files"][0]["sha256"] = "0" * 64
        with mock.patch.object(deck.shutil, "which", return_value="/usr/bin/ssh"), \
                mock.patch.object(deck.subprocess, "run", side_effect=self.fake_ssh), \
                self.assertRaisesRegex(deck.DeckError, "changed while it was copied"):
            deck.fetch_driver("deck@steamdeck", self.root, note=lambda text: None)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_different_offline_device_is_rejected(self):
        other = dict(self.profile, device=0x747e)
        with mock.patch.object(deck.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps([other]))), \
                self.assertRaisesRegex(deck.DeckError, "does not match"):
            deck.check_driver(self.root, self.manifest)

    def test_memory_limit_is_required_and_reserves_half_the_available_ram(self):
        with mock.patch.object(Path, 'read_text', return_value='MemAvailable: 12582912 kB\n'):
            self.assertEqual(deck.memory_limit(), 6 * 1024**3)
        with mock.patch.object(Path, 'read_text', return_value='MemAvailable: 33554432 kB\n'):
            self.assertEqual(deck.memory_limit(), 8 * 1024**3)
        with mock.patch.object(Path, 'read_text', return_value='MemAvailable: 1048576 kB\n'), \
                self.assertRaisesRegex(deck.DeckError, 'at least 8 GiB'):
            deck.memory_limit()
        with mock.patch.object(deck.shutil, 'which', return_value='/usr/bin/systemd-run'):
            args = deck.worker_command(['/game/hookshot', '--prepare-shaders'], self.root,
                                       dict(LD_PRELOAD='/private/shim.so', SECRET_TOKEN='private'), 1234)
        self.assertIn('--property=MemoryMax=1234', args)
        self.assertIn('--property=MemorySwapMax=0', args)
        self.assertIn('--property=OOMPolicy=kill', args)
        self.assertIn('LD_PRELOAD=/private/shim.so', args)
        self.assertIn('--expand-environment=no', args)
        self.assertEqual(args[args.index('/usr/bin/env') + 1], '-i')
        self.assertFalse(any('SECRET_TOKEN' in arg for arg in args))

    def test_preparation_failure_and_faults_cannot_replace_existing_caches(self):
        game, bundle = self.caches()
        for name in ('hookshot', 'hookshot_vk.so'):
            (game / name).write_bytes(b'authored fixture')
        marker = game / 'hookshot_pipelines.bin.running'
        marker.write_text('2\n')
        original = (game / 'hookshot_programs.bin').read_bytes()
        for result, fault in ((137, False), (0, True), (0, False)):
            def run(command, folder):
                stage = Path(folder)
                self.assertNotEqual(stage, game)
                self.assertFalse((stage / 'user').exists())
                self.assertIn('MESA_SHADER_CACHE_DIR=' + str(stage / deck.DRIVER_CACHE), command)
                self.assertIn('MESA_SHADER_CACHE_DISABLE=false', command)
                (stage / deck.DRIVER_CACHE / 'authored-driver-cache').write_bytes(b'compiled fixture')
                (stage / 'hookshot_programs.bin').write_bytes(original + b'new data')
                if fault:
                    (stage / 'hookshot_driver_faults.txt').write_text('# test fault\n123456789abcdef0\n')
                return result
            with mock.patch.object(deck, 'check_worker', return_value=8 * 1024**3), \
                    mock.patch.object(deck.shutil, 'which', return_value='/usr/bin/systemd-run'), \
                    mock.patch.object(deck, 'stop_worker') as stop:
                if result or fault:
                    with self.assertRaises(deck.DeckError):
                        deck.prepare_game(game, bundle, self.root / 'work', runner=run)
                    self.assertEqual((game / 'hookshot_programs.bin').read_bytes(), original)
                    self.assertTrue(marker.exists())
                    self.assertFalse((game / deck.DRIVER_CACHE).exists())
                else:
                    with mock.patch.object(deck, 'PREPARE_BATCHES', 1):
                        deck.prepare_game(game, bundle, self.root / 'work', runner=run)
                    self.assertEqual((game / 'hookshot_programs.bin').read_bytes(), original + b'new data')
                    self.assertFalse(marker.exists())
                    self.assertEqual((game / deck.DRIVER_CACHE / 'authored-driver-cache').read_bytes(), b'compiled fixture')
                stop.assert_called_once()
            self.assertEqual(list((self.root / 'work').iterdir()), [])

    def test_private_copy_is_independent_of_its_source(self):
        source, dest = self.root / 'source', self.root / 'copy'
        source.write_bytes(b'old contents')
        deck.copy_private(source, dest)
        dest.write_bytes(b'new contents')
        self.assertEqual(source.read_bytes(), b'old contents')

    def test_all_batches_must_finish_before_any_cache_is_published(self):
        game, bundle = self.caches()
        for name in ('hookshot', 'hookshot_vk.so'):
            (game / name).write_bytes(b'authored fixture')
        for fail_at in (3, None):
            batches = []
            def run(command, folder):
                index = int(next(arg.split('=', 1)[1] for arg in command
                                 if arg.startswith('HOOKSHOT_DECK_BATCH_INDEX=')))
                self.assertIn('HOOKSHOT_DECK_BATCH_COUNT=8', command)
                self.assertFalse((game / deck.DRIVER_CACHE).exists())
                batches.append(index)
                (Path(folder) / deck.DRIVER_CACHE / str(index)).write_bytes(b'compiled batch')
                return 9 if index == fail_at else 0
            with mock.patch.object(deck, 'check_worker', return_value=8 * 1024**3), \
                    mock.patch.object(deck.shutil, 'which', return_value='/usr/bin/systemd-run'), \
                    mock.patch.object(deck, 'stop_worker') as stop:
                if fail_at is not None:
                    with self.assertRaises(deck.DeckError):
                        deck.prepare_game(game, bundle, self.root / 'work', runner=run)
                    self.assertEqual(batches, list(range(4)))
                    self.assertFalse((game / deck.DRIVER_CACHE).exists())
                else:
                    deck.prepare_game(game, bundle, self.root / 'work', runner=run)
                    self.assertEqual(batches, list(range(8)))
                    self.assertEqual(len(list((game / deck.DRIVER_CACHE).iterdir())), 8)
                self.assertEqual(stop.call_count, len(batches))

    def caches(self):
        game, bundle = self.root / "game", self.root / "driver"
        game.mkdir()
        bundle.mkdir()
        (bundle / "manifest.json").write_text(json.dumps(self.manifest))
        (game / "hookshot_programs.bin").write_bytes(b"HSP1" + bytes(4) + struct.pack("<Q", 42))
        (game / 'hookshot_shaders.bin').write_bytes(b'12')
        (game / "hookshot_prepared.bin").write_bytes(struct.pack("<6Q", 42, 1, 2, 3, 4, 5))
        (game / "mkw_vk_pipelines.bin").write_bytes(struct.pack("<4I", 32, 1, 0x1002, 0x163f) +
                                                  bytes.fromhex(self.profile["cache_uuid"]))
        return game, bundle

    def test_only_finished_caches_for_the_target_driver_are_marked(self):
        game, bundle = self.caches()
        deck.check_caches(game, bundle)
        self.assertEqual(json.loads((game / "hookshot_steamdeck_driver.json").read_text()), self.profile)
        (game / "hookshot_steamdeck_driver.json").unlink()
        pipeline = game / "mkw_vk_pipelines.bin"
        data = pipeline.read_bytes()
        pipeline.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaisesRegex(deck.DeckError, "another GPU or driver"):
            deck.check_caches(game, bundle)
        self.assertFalse((game / "hookshot_steamdeck_driver.json").exists())
        pipeline.write_bytes(data)
        (game / "hookshot_prepared.bin").write_bytes(bytes(48))
        with self.assertRaisesRegex(deck.DeckError, "did not finish"):
            deck.check_caches(game, bundle)
        (game / 'hookshot_prepared.bin').write_bytes(struct.pack('<6Q', 42, 1, 999, 3, 4, 5))
        with self.assertRaisesRegex(deck.DeckError, 'different shader list'):
            deck.check_caches(game, bundle)
        (game / 'hookshot_prepared.bin').write_bytes(struct.pack('<6Q', 42, 1, 2, 3, 4, 0))
        with self.assertRaisesRegex(deck.DeckError, 'driver preparation did not finish'):
            deck.check_caches(game, bundle)


if __name__ == "__main__":
    unittest.main()
