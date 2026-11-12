"""The 2.x Builder's hand-over to the Hookshot Launcher (3.0), on Linux: the contract is docs/launcher-upgrade.md, and its
sample files are in tests/fixtures/launcher/.

A release that ships the launcher carries hookshot-launcher.txt (a 404 means a Builder release, updated as before):

    tag <tag>
    format 1
    launcher <platform> <sha256> <bytes> <https url>

The upgrade downloads this platform's file and checks it, installs it as <launcher home>/Hookshot.AppImage, drops an
import file for the game folder in <launcher home>/import/, points the folder's hookshot_version.txt at the launcher, and
starts it with --launch <folder>. Standard library only: the functions here are small, and the tests call them.
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.error

import linux_update

LIST_NAME = "hookshot-launcher.txt"
FORMAT = 1
PLATFORM = "linux-x64"
PLATFORMS = ("windows-x64", "linux-x64")   # (any other platform's line is skipped)
APPIMAGE = "Hookshot.AppImage"
RELEASES_PAGE = "https://github.com/NotRexed/Hookshot/releases"
MAX_LIST = 64 << 10   # (the file is a few lines)


class TooNew(ValueError):
    """A format this Builder does not know: it does not upgrade, and says to download the launcher from the release page."""


class Launcher(object):
    def __init__(self, platform, sha, size, url):
        self.platform, self.sha, self.size, self.url = platform, sha, size, url


class Manifest(object):
    def __init__(self, tag, launchers):
        self.tag, self.launchers = tag, launchers   # launchers: platform -> Launcher

    def line(self, platform=PLATFORM):
        """This platform's launcher, or ValueError when the release has none for it."""
        found = self.launchers.get(platform)
        if found is None:
            raise ValueError("This release has no Hookshot Launcher for %s. Download it from the release page." % platform)
        return found


def parse_manifest(text, tag=None, local=False):
    """hookshot-launcher.txt (section 1), as strictly as the setup lists: tag must be the tag asked for (None: the latest
    release, any version name), format 1 (a higher one is TooNew), one launcher line a platform. local: a list from this PC
    (HOOKSHOT_LAUNCHER_LIST), whose links may be file:// ones; a downloaded one's are https."""
    found, form, launchers = "", None, {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        bits = line.split()
        if bits[0] == "tag" and len(bits) == 2 and not found:
            found = bits[1]
        elif bits[0] == "format" and len(bits) == 2 and form is None:
            if not re.fullmatch(r"[0-9]{1,6}", bits[1]):
                raise ValueError("the launcher list's format is not a number")
            form = int(bits[1])
        elif bits[0] == "launcher" and len(bits) == 5:
            platform, sha, size, url = bits[1:]
            if platform not in PLATFORMS:
                continue
            if platform in launchers:
                raise ValueError("the launcher list names %s twice" % platform)
            if (not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(r"[1-9][0-9]{0,11}", size) or
                    not url.startswith(("https://", "file://") if local else "https://")):
                raise ValueError("a launcher line has a bad checksum, size or link")
            launchers[platform] = Launcher(platform, sha, int(size), url)
        else:
            raise ValueError("unknown launcher list line")
    if not found or form is None:
        raise ValueError("the launcher list has no tag or format")
    if not re.fullmatch(r"[0-9A-Za-z._+-]{1,128}", found) or found in (".", ".."):
        raise ValueError("the launcher list's tag is not a version name")
    if tag and found != tag:
        raise ValueError("the launcher list is %s, not the %s asked for" % (found, tag))
    if form > FORMAT:
        raise TooNew("Hookshot %s needs a newer Builder to move over to its launcher. Download the Hookshot Launcher from "
                     "the release page." % found)
    if form < 1:
        raise ValueError("the launcher list's format is not 1")
    return Manifest(found, launchers)


def list_url(tag=None):
    """Where a release's hookshot-launcher.txt is: the release that holds the tag's files (the nightly's are on nightly)."""
    if not tag:
        return "https://github.com/NotRexed/Hookshot/releases/latest/download/" + LIST_NAME
    return "https://github.com/NotRexed/Hookshot/releases/download/%s/%s" % (linux_update.release_of(tag), LIST_NAME)


def release_page(tag=None):
    return RELEASES_PAGE + ("/tag/" + linux_update.release_of(tag) if tag else "/latest")


def _get_list(url, stop=None):
    """The list's bytes, or None for a 404. One plain download first, so a missing file (a Builder release) costs one
    request and no API call; anything else goes through fetch_bytes' retries."""
    try:
        return linux_update._request(url, 15, MAX_LIST, stop)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
    except linux_update.Cancelled:
        raise
    except Exception:
        pass
    return linux_update.fetch_bytes(url, 15, stop)


def probe(tag=None, get=None, stop=None):
    """The launcher release a tag is, or None when it is a Builder release (no hookshot-launcher.txt: a 404). get(url):
    the list's bytes, None or urllib.error.HTTPError 404 for none. Raises TooNew or ValueError for a list it cannot use,
    and the download's error when GitHub did not answer. HOOKSHOT_LAUNCHER_LIST: a list on this PC instead (testing)."""
    override = os.environ.get("HOOKSHOT_LAUNCHER_LIST")
    if override:
        with open(override, encoding="utf-8") as handle:
            return parse_manifest(handle.read(), None, local=True)
    get = get or (lambda url: _get_list(url, stop))
    try:
        data = get(list_url(tag))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        data = None
    if data is None:
        return None
    return parse_manifest(data.decode("utf-8"), tag)


def upgrade_mode(mode, offered_for, target):
    """The Builder's button: an update (of the game or of the Builder) whose target is a launcher release is the upgrade.
    offered_for: the tag probe found a launcher release for, else None."""
    if offered_for and offered_for == target and mode in ("update-game", "update-builder"):
        return "upgrade"
    return mode


# ---- where the launcher lives (section 2) ----
def launcher_home(environ=None):
    environ = os.environ if environ is None else environ
    home = environ.get("HOOKSHOT_LAUNCHER_HOME")
    if home:
        return home
    base = environ.get("XDG_DATA_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "hookshot", "launcher")


def installed_launcher(environ=None):
    """<home>/Hookshot.AppImage when it is installed (a file that runs), else ""."""
    path = os.path.join(launcher_home(environ), APPIMAGE)
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else ""


def forward_command(args, launcher):
    """What the Builder runs instead of itself once the launcher is installed (section 4): --launch <folder>, and
    --update <folder> [--tag <tag>] [--fetched], passed to the launcher. None: anything else, or no launcher."""
    if not launcher:
        return None

    def value(name):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args) and args[i + 1]:
                return args[i + 1]
        return None
    folder = value("--update")
    if folder is not None:
        tag = value("--tag")
        return [launcher, "--update", folder] + (["--tag", tag] if tag else []) + (["--fetched"] if "--fetched" in args else [])
    folder = value("--launch")
    if folder is not None:
        return [launcher, "--launch", folder]
    return None


# ---- what the Builder remembered, handed over (section 3) ----
def read_ini(text):
    """builder.ini as the Builder reads it (hookshot_builder.load_config): key=value lines."""
    cfg = {}
    for line in text.splitlines():
        k, eq, v = line.partition("=")
        if eq:
            cfg[k] = v
    return cfg


def _stamp_value(folder, name):
    try:
        with open(os.path.join(folder, "hookshot_version.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line[len(name) + 1:].strip() or None
    except (OSError, UnicodeDecodeError):
        pass
    return None


def _first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def _path(value):
    return os.path.abspath(os.path.expanduser(value)) if value else None


def import_dict(cfg, folder, version, folder_language=None):
    """The import file (section 3) from builder.ini's values, the game folder (None: the saved install folder), its
    stamp's version and its language.txt."""
    kind = cfg.get("kind", "nup")
    track = cfg.get("track")
    return {
        "format": 1,
        "folder": _path(folder or cfg.get("out")),
        "version": version,
        "track": track if track in linux_update.TRACKS else linux_update.track_of(version),
        "default": True,
        "settings": {
            "nup": _path(cfg.get("nup")) if kind == "nup" else None,
            "romfs": _path(cfg.get("romfs")) if kind == "folders" else None,
            "exefs": _path(cfg.get("exefs")) if kind == "folders" else None,
            "language": cfg.get("language") or folder_language or None,
            "dlss": cfg.get("dlss") == "1",
            "dlssLicense": cfg.get("nvidia_license") == "1",
            "fsr": False,
            "fsrLicense": False,
            "prepareShaders": cfg.get("prepare") != "0",
            "memoryGb": None,
            "jobs": None,
            "work": None,
        },
    }


def import_for(cfg, folder=None):
    """import_dict for a folder on this PC: its version and language read from it."""
    folder = _path(folder or cfg.get("out"))
    if not folder:
        return None
    return import_dict(cfg, folder, _stamp_value(folder, "version"), _first_line(os.path.join(folder, "language.txt")))


def _write_atomic(path, data):
    part = path + ".part"
    with open(part, "wb") as handle:
        handle.write(data)
    os.replace(part, path)


def write_import(data, home=None):
    """<home>/import/<name>.json, written as .json.part and renamed, one name a folder (so a second upgrade of the same
    folder replaces its file rather than adding one)."""
    folder = os.path.join(home or launcher_home(), "import")
    os.makedirs(folder, exist_ok=True)
    name = "builder-%s.json" % hashlib.sha256(data["folder"].encode("utf-8")).hexdigest()[:16]
    path = os.path.join(folder, name)
    _write_atomic(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return path


def rewrite_stamp(folder, launcher):
    """hookshot_version.txt (section 4): builder= names the launcher, builder_args= goes, every other line stays. A
    portable folder (builder_local=1), or one with no stamp, is left as it is. True when it was rewritten."""
    path = os.path.join(folder, "hookshot_version.txt")
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    if any(line.strip() == "builder_local=1" for line in lines):
        return False
    out, named = [], False
    for line in lines:
        if line.startswith("builder_args="):
            continue
        if line.startswith("builder="):
            if named:
                continue
            line, named = "builder=" + launcher, True
        out.append(line)
    if not named:
        out.append("builder=" + launcher)
    _write_atomic(path, ("\n".join(out) + "\n").encode("utf-8"))
    return True


# ---- installing it (section 2) ----
def _local_or_fetch(url, stop=None):
    if url.startswith("file://") and os.environ.get("HOOKSHOT_LAUNCHER_LIST"):
        with open(url[len("file://"):], "rb") as handle:
            return handle.read()
    return linux_update.fetch_bytes(url, 120, stop)


def install(line, get=None, home=None, stop=None):
    """The launcher AppImage downloaded, checked for size and SHA-256, written as Hookshot.AppImage.part, made executable
    and renamed over Hookshot.AppImage. Nothing is written before the check, and a failure leaves no .part."""
    data = (get or (lambda url: _local_or_fetch(url, stop)))(line.url)
    if len(data) != line.size or hashlib.sha256(data).hexdigest() != line.sha:
        raise RuntimeError("The Hookshot Launcher did not download correctly (its size or checksum differs).")
    linux_update._stopped(stop)   # (a Cancel that came as the download ended: nothing installed either)
    home = home or launcher_home()
    os.makedirs(home, exist_ok=True)
    path = os.path.join(home, APPIMAGE)
    part = path + ".part"
    try:
        with open(part, "wb") as handle:
            handle.write(data)
        os.chmod(part, 0o755)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return path


def upgrade(manifest, folder, cfg, get=None, note=None, home=None, stop=None):
    """Section 6, steps 3 and 4: the launcher installed, then the folder's import file and stamp. Returns the launcher and
    the folder handed over (None: none known). A failure while installing changes nothing; one after it leaves the
    launcher, which imports the Builder's settings itself on its first start."""
    note = note or (lambda message: None)
    line = manifest.line()
    note("Downloading the Hookshot Launcher %s (%d MB)" % (manifest.tag, line.size >> 20))
    launcher = install(line, get, home, stop)
    note("Handing your game folder over")
    data = import_for(cfg, folder)
    try:
        if data is not None:
            write_import(data, home)
            rewrite_stamp(data["folder"], launcher)
    except OSError:
        pass
    return launcher, data["folder"] if data is not None else None


# (what the 2.x AppImage's AppRun sets for its own tools and Python: not the launcher's)
OWN_ENV = ("APPDIR", "APPIMAGE", "ARGV0", "OWD", "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "HOOKSHOT_TOOLS", "EMSDK",
           "HOOKSHOT_SYSROOT", "HOOKSHOT_FFMPEG", "HOOKSHOT_VK_PREBUILT", "HOOKSHOT_SDL2", "HOOKSHOT_BUILDER_EXE")


def clean_env(environ=None):
    return {k: v for k, v in (os.environ if environ is None else environ).items() if k not in OWN_ENV}


def start(launcher, folder=None):
    """The launcher, on its own (it outlives the Builder), opened on the folder."""
    subprocess.Popen([launcher] + (["--launch", folder] if folder else []), env=clean_env(), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
