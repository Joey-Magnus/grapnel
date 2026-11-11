"""Add to Steam (Linux, the Steam Deck): the game folder as a non-Steam game in Steam's library, so it starts from Steam and
Game Mode with Steam Input. Hookshot Builder's Add to Steam button runs add(); from a shell:

    python3 -I builder/linux/steam_shortcut.py <game folder> [--steam <Steam folder>] [--dry-run]

Steam keeps its non-Steam games in userdata/<account>/config/shortcuts.vdf, binary KeyValues (little-endian): 0x00 a child
dict, 0x01 a string, 0x02 an int32, 0x08 the end of a dict; the file is 0x00 "shortcuts" 0x00, the entries ("0", "1", ...),
then 0x08 0x08. Without the second 0x08 Steam logs "failed to load shortcut file" and loses the file. An entry is keyed by
its app id: crc32(Exe + AppName) with the top bit set, so adding the same folder again updates its entry in place (its grid
art stays attached). Every account on this PC gets the entry; the file as it was is kept beside it as shortcuts.vdf.bak.

Steam writes shortcuts.vdf from memory when it exits, over any change made while it runs: Steam must be closed first, and
add() refuses while it runs.

The reader and writer are lethevimlet's tools/bc250/add_steam_shortcut.py from github.com/lethevimlet/oot-bc250
(GPL-3.0, commit 98cceccfec), made a module: Steam's folders found, every account, the game folder's launcher and icon,
Steam's own quoting of Exe and StartDir, and a check that Steam is not running. tests/test_steam_shortcut.py covers it.
"""
import argparse
import binascii
import os
import shutil
import struct
import sys
import time

T_DICT, T_STR, T_INT, T_END = 0, 1, 2, 8
NAME = "Hookshot (Ocarina of Time)"


def parse(d, p):
    """The pairs of the dict starting at d[p] (after its key), and the offset past its 0x08"""
    out = []
    while p < len(d):
        t = d[p]
        if t == T_END:
            return out, p + 1
        p += 1
        ks = p
        while d[p] != 0:
            p += 1
        key = d[ks:p].decode("utf-8", "replace")
        p += 1
        if t == T_STR:
            vs = p
            while d[p] != 0:
                p += 1
            out.append((key, d[vs:p].decode("utf-8", "replace")))
            p += 1
        elif t == T_INT:
            out.append((key, struct.unpack("<I", d[p:p + 4])[0]))
            p += 4
        elif t == T_DICT:
            sub, p = parse(d, p)
            out.append((key, sub))
        else:
            raise ValueError("unknown type byte %#x at %d" % (t, p - 1))
    raise ValueError("the file ends inside a dict")


def serialize(pairs):
    buf = bytearray()
    for key, val in pairs:
        if isinstance(val, list):
            buf.append(T_DICT)
            buf += key.encode("utf-8") + b"\x00"
            buf += serialize(val)
            buf.append(T_END)
        elif isinstance(val, int):
            buf.append(T_INT)
            buf += key.encode("utf-8") + b"\x00" + struct.pack("<I", val & 0xFFFFFFFF)
        else:
            buf.append(T_STR)
            buf += key.encode("utf-8") + b"\x00" + str(val).encode("utf-8") + b"\x00"
    return bytes(buf)


def read_entries(data):
    """The entries of a shortcuts.vdf's bytes ([] for an empty or missing file)"""
    if not data:
        return []
    if data[0] != T_DICT:
        raise ValueError("not a shortcuts file (its first byte is not a dict)")
    p = 1
    while data[p] != 0:
        p += 1
    if data[1:p] != b"shortcuts":
        raise ValueError("not a shortcuts file (its root is %r)" % data[1:p])
    entries, _ = parse(data, p + 1)
    return entries


def write_entries(entries):
    return bytes([T_DICT]) + b"shortcuts\x00" + serialize(entries) + bytes([T_END, T_END])


def appid(exe, name):
    """Steam's id of a non-Steam game: crc32 of the Exe as Steam stores it (quoted) and the name, the top bit set"""
    return (binascii.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def quoted(path):
    return '"%s"' % path


def entry_for(folder, name=NAME, now=None):
    """The entry of a game folder: its launcher (hookshot: Play, and Update when a newer release is out), run from the folder"""
    folder = os.path.abspath(folder)
    exe = quoted(os.path.join(folder, "hookshot"))
    icon = os.path.join(folder, "hookshot.png")
    return [
        ("appid", appid(exe, name)),
        ("AppName", name),
        ("Exe", exe),
        ("StartDir", quoted(folder + "/")),
        ("icon", icon if os.path.isfile(icon) else ""),
        ("ShortcutPath", ""),
        ("LaunchOptions", ""),
        ("IsHidden", 0),
        ("AllowDesktopConfig", 1),
        ("AllowOverlay", 1),
        ("OpenVR", 0),
        ("Devkit", 0),
        ("DevkitGameID", ""),
        ("DevkitOverrideAppID", 0),
        ("LastPlayTime", int(time.time() if now is None else now)),
        ("FlatpakAppID", ""),
        ("sortas", ""),
        ("tags", []),
    ]


def merged(entries, new):
    """entries with new in place of the entry of its app id (the first one), or after the others; (entries, updated)"""
    target = dict(new)["appid"]
    out, found = [], False
    for key, ent in entries:
        if not found and isinstance(ent, list) and any(k.lower() == "appid" and v == target for k, v in ent):
            out.append((key, new))
            found = True
        else:
            out.append((key, ent))
    if not found:
        used = {k for k, _ in out}
        n = 0
        while str(n) in used:
            n += 1
        out.append((str(n), new))
    return out, found


def steam_roots(home=None, environ=os.environ):
    """Steam's folders on this PC (HOOKSHOT_STEAM_ROOT for one of your choosing): the native install, the old ~/.steam link,
    the Flatpak's; each once"""
    if environ.get("HOOKSHOT_STEAM_ROOT"):
        return [environ["HOOKSHOT_STEAM_ROOT"]]
    home = home or os.path.expanduser("~")
    seen, out = set(), []
    for p in (os.path.join(home, ".local", "share", "Steam"), os.path.join(home, ".steam", "steam"),
              os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")):
        real = os.path.realpath(p)
        if os.path.isdir(os.path.join(real, "userdata")) and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def accounts(root):
    """The shortcuts.vdf of each Steam account in a Steam folder (the file need not exist yet)"""
    userdata = os.path.join(root, "userdata")
    try:
        ids = sorted(d for d in os.listdir(userdata) if d.isdigit() and d != "0")
    except OSError:
        return []
    return [os.path.join(userdata, d, "config", "shortcuts.vdf") for d in ids]


def steam_running(root, proc="/proc"):
    """Whether Steam runs from this folder's install: its steam.pid (in the folder or ~/.steam) names a live steam process"""
    for pid_file in (os.path.join(root, "steam.pid"), os.path.join(os.path.dirname(root), "steam.pid"),
                     os.path.expanduser("~/.steam/steam.pid")):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip() or "0")
            with open(os.path.join(proc, str(pid), "comm")) as f:
                if "steam" in f.read().lower():
                    return True
        except (OSError, ValueError):
            continue
    return False


def add(folder, roots=None, dry_run=False, proc="/proc", now=None):
    """The game folder in every account's shortcuts.vdf: a list of (file, "added" or "updated"). ValueError when there is no
    Steam account or Steam runs (it would write its own copy over the change when it exits)"""
    roots = steam_roots() if roots is None else roots
    files = [(r, f) for r in roots for f in accounts(r)]
    if not files:
        raise ValueError("No Steam account found on this PC (no userdata folder in %s)." % (", ".join(roots) or "~/.local/share/Steam"))
    for r in roots:
        if steam_running(r, proc):
            raise ValueError("Steam is running. Close it (Steam menu, Exit), then add the game again: Steam writes its own list "
                             "over a change when it closes.")
    new = entry_for(folder, now=now)
    done = []
    for _, vdf in files:
        try:
            with open(vdf, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = b""
        entries, updated = merged(read_entries(data), new)
        if not dry_run:
            os.makedirs(os.path.dirname(vdf), exist_ok=True)
            if data:
                shutil.copy2(vdf, vdf + ".bak")
            tmp = vdf + ".new"
            with open(tmp, "wb") as f:
                f.write(write_entries(entries))
            os.replace(tmp, vdf)
        done.append((vdf, "updated" if updated else "added"))
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add a Hookshot game folder to Steam as a non-Steam game.")
    ap.add_argument("folder")
    ap.add_argument("--steam", action="append", help="a Steam folder (with userdata in it); default: the ones found")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isfile(os.path.join(a.folder, "image.bin")):
        print("%s is not a built game folder (no image.bin)" % a.folder, file=sys.stderr)
        return 1
    try:
        done = add(a.folder, a.steam, a.dry_run)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    for vdf, what in done:
        print("%s %s in %s" % (NAME, what, vdf))
    print("Start Steam: the game is in the library, under Non-Steam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
