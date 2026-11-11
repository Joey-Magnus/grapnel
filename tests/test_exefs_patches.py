"""The mods' ExeFS patches applied when the game is built (nx2/exefs_patches.py), without the game.

- IPS, IPS32 (runs too) and IPSwitch .pchtxt parse to the same writes, offsets less the NSO header, a pchtxt's
  offset_shift, @enabled / @disabled and @stop kept; a cut-short file is refused;
- a file is the game's by its build id (an IPS file's name, a pchtxt's @nsobid, trailing zeros left out or not);
- the mods are host/mods.c's: '-' and '_' folders left out, hookshot_mods.txt's order and switches, the rest by name;
- a synthetic main: code and data writes kept, bytes equal to main's dropped, writes into an explicit-addend relocation's
  word dropped (the dynamic linker writes over them), into a lazily bound pointer, the linker's tables or past the
  image refused;
- applying: the later file wins a byte, a write into the padding after the code makes it code (a cave);
- exefs_patches.txt lines as host/mods.c looks them up ("<mod>\\t<file>\\t<fnv32 %08x>\\t<kind>\\t").

python -I -B tests/test_exefs_patches.py
"""
import json
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import exefs_patches as ep  # noqa: E402

BID = "e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348"


def need(ok, what):
    if not ok:
        raise SystemExit("test_exefs_patches: " + what)


class FakeNso:
    """main as nso.Nso has it: a 0x3000-byte image, .text 0x0-0x1800 (padding to .rodata at 0x2000), .data at 0x2800, a
    MOD0 at 0x2800 whose .dynamic (0x2810) names a RELA table at 0x2900 (one RELATIVE word at 0x2c00, one JUMP_SLOT at 0x2c08)"""

    def __init__(self):
        self.name = "main"
        self.build_id = BID
        self.image = bytearray(0x3000)
        self.image[0x100:0x104] = b"\x1f\x20\x03\xd5"
        self.segments = [(0, 0x1800, ".text"), (0x2000, 0x400, ".rodata"), (0x2800, 0x800, ".data")]
        self.mod0 = 0x2800
        self.image[0x2800:0x2808] = b"MOD0" + struct.pack("<i", 0x10)
        struct.pack_into("<qQqQqQ", self.image, 0x2810, 7, 0x2900, 8, 48, 0, 0)
        self.dynamic = {"RELA": [0x2900], "RELASZ": [48]}
        self.relocs = [{"offset": 0x2c00, "type": "RELATIVE"}, {"offset": 0x2c08, "type": "JUMP_SLOT"}]


def main():
    ips = b"PATCH" + bytes([0, 0x02, 0x00, 0, 4]) + b"\x00\x00\x80\xd2" + bytes([0, 0x30, 0x00, 0, 0, 0, 3, 0xAA]) + b"EOF"
    need(ep.parse_ips(ips) == {0x100: 0, 0x101: 0, 0x102: 0x80, 0x103: 0xd2, 0x2F00: 0xAA, 0x2F01: 0xAA, 0x2F02: 0xAA},
         "IPS (a record and a run) does not parse to its writes less the NSO header")
    ips32 = b"IPS32" + struct.pack(">IH", 0x200, 4) + b"\x00\x00\x80\xd2" + b"EEOF"
    need(ep.parse_ips(ips32) == {0x100: 0, 0x101: 0, 0x102: 0x80, 0x103: 0xd2}, "IPS32 does not parse")
    try:
        ep.parse_ips(b"PATCH" + bytes([0, 2, 0, 0, 9]) + b"ab")
        need(False, "a cut-short IPS file is accepted")
    except ValueError:
        pass
    bid, w = ep.parse_pchtxt("@nsobid-E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348\n@flag offset_shift 0x100\n// a comment\n"
                             "@enabled\n00000100 1F2003D5\n@disabled\n00000200 FFFFFFFF\n@enabled\n00000300 \"ab\\n\"\n@stop\n"
                             "00000400 01\n")
    need(bid.lower() == BID and w == {0x100: 0x1f, 0x101: 0x20, 0x102: 0x03, 0x103: 0xd5, 0x300: 0x61, 0x301: 0x62, 0x302: 10},
         "pchtxt: %r" % w)
    need(ep.same_build("E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348", BID) and ep.same_build(BID + "000000000000000000000000", BID)
         and not ep.same_build("e0f3ccfa", BID) and not ep.same_build("zz", BID), "build ids are not matched as emulators match them")

    m = ep.Main(FakeNso())
    need(m.classify({0x100: 0x1f}) == ("empty", "", {}), "a byte equal to main's is kept")
    need(m.classify({0x100: 0x00})[0] == "code" and m.classify({0x2f00: 1})[0] == "data", "code and data are not told apart")
    need(m.classify({0x2c00: 5, 0x2f00: 1}) == ("data", "", {0x2f00: 1}), "a relocated word's bytes are kept (rtld writes over them)")
    need(m.classify({0x2c09: 1})[0] == "unsupported", "a lazily bound pointer can be written")
    need(m.classify({0x2814: 1})[0] == "unsupported", "the dynamic section can be written")
    need(m.classify({0x2905: 1})[0] == "unsupported", "a relocation table can be written")
    need(m.classify({0x3000: 1})[0] == "unsupported", "a write past main's image is accepted")

    with tempfile.TemporaryDirectory(prefix="exefs-patches-") as tmp:
        mods = os.path.join(tmp, "mods")
        for d in ("b-mod/exefs", "a-mod/exefs", "_off/exefs", "deep/contents/0400486024DEC000/c-mod/exefs", "plain"):
            os.makedirs(os.path.join(mods, d))
        open(os.path.join(mods, "a-mod/exefs", BID.upper() + ".ips"), "wb").write(ips)
        open(os.path.join(mods, "a-mod/exefs", "notes.txt"), "w").write("x")
        open(os.path.join(mods, "b-mod/exefs", "x.pchtxt"), "w").write("@nsobid-%s\n@enabled\n00000100 01020304\n" % BID)
        found = ep.find_mods(mods)
        need([n for n, _ in found] == ["a-mod", "b-mod", "deep/contents/0400486024DEC000/c-mod"], "mods found: %r" % found)
        state = os.path.join(tmp, "hookshot_mods.txt")
        open(state, "w").write("# x\non b-mod\noff a-mod\non gone\n")
        order = ep.ordered(found, state)
        need([(n, on) for n, _, on in order] == [("b-mod", True), ("a-mod", False), ("deep/contents/0400486024DEC000/c-mod", True)],
             "the order and switches of hookshot_mods.txt: %r" % order)
        need(ep.patch_files(dict(found)["a-mod"]) == [BID.upper() + ".ips"], "patch files: only .ips and .pchtxt")

        # (applying: a-mod and b-mod both write main+0x100: the later in the list wins; b-mod writes a cave after .text)
        files = [{"mod": "a", "file": "1.ips", "hash": "0", "kind": "code", "note": "", "on": True, "writes": [[0x100, 0xAA], [0x101, 0xBB]]},
                 {"mod": "b", "file": "2.ips", "hash": "0", "kind": "code", "note": "", "on": True, "writes": [[0x100, 0xCC], [0x1900, 1]]},
                 {"mod": "c", "file": "3.ips", "hash": "0", "kind": "other", "note": "", "on": True, "writes": [[0x100, 0xDD]]}]
        path = os.path.join(tmp, "p.json")
        json.dump(files, open(path, "w"))
        n = FakeNso()
        ep.apply([n], path, log=lambda *_: None)
        need(n.image[0x100] == 0xCC and n.image[0x101] == 0xBB and n.image[0x1900] == 1, "the later file does not win a byte")
        need(n.segments[0] == (0, 0x1904, ".text"), "a code cave does not become code: %r" % (n.segments[0],))
        listing = os.path.join(tmp, "exefs_patches.txt")
        files[0]["hash"] = "%08x" % ep.fnv32(ips)
        files[1]["on"] = False
        ep.write_list(files, listing)
        text = open(listing, encoding="utf-8").read()
        need(("a\t1.ips\t%08x\tcode\t\n" % ep.fnv32(ips)) in text and "2.ips" not in text,
             "exefs_patches.txt is not as host/mods.c reads it:\n" + text)
    need(ep.fnv32(b"") == 0x811C9DC5 and ep.fnv32(b"a") == 0xE40C292C, "FNV-1a 32 is not host/mods.c's")
    print("PASS: ExeFS patches: IPS, IPS32 and pchtxt; build ids; the mods' order; main's code, data and tables; caves")


if __name__ == "__main__":
    main()
