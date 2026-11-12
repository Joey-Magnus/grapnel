"""The launcher fetches AMD's FSR runtime itself for a release whose make_game.py cannot (builder/HookshotBuilder/FfxRuntime.cs):
the same pinned release, files and SHA-256s as scripts/ffx_sdk.py, which a newer make_game.py runs. One changed without the
other would put a different AMD runtime in the game folder depending on which release built it.

python -I -B tests/test_ffx_runtime_pins.py
"""
import importlib.util
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ffx_sdk", ROOT / "scripts" / "ffx_sdk.py")
ffx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ffx)
cs = (ROOT / "builder" / "HookshotBuilder" / "FfxRuntime.cs").read_text(encoding="utf-8")

failed = []
commit = re.search(r'const string Commit = "([0-9a-f]{40})"', cs)
if not commit or commit.group(1) != ffx.COMMIT:
    failed.append("the pinned commit differs: %s against ffx_sdk.py's %s" % (commit and commit.group(1), ffx.COMMIT))
if 'FidelityFX-SDK/" + Commit' not in cs or not ffx.BASE.endswith("FidelityFX-SDK/" + ffx.COMMIT):
    failed.append("the download base differs")
files = re.findall(r'\("([^"]+)",\s*"([0-9a-f]{64})",\s*"([^"]+)"\)', cs)
if [tuple(f) for f in files] != [tuple(f) for f in ffx.FILES]:
    failed.append("the files differ:\n  FfxRuntime.cs %r\n  ffx_sdk.py    %r" % (files, ffx.FILES))
if failed:
    print("\n".join(failed))
    sys.exit(1)
print("the launcher's AMD FSR runtime is ffx_sdk.py's: %d files at %s" % (len(files), ffx.COMMIT[:8]))
