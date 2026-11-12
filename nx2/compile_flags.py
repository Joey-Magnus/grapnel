"""The CPU flags a build compiled with, recorded beside the game and in the binary.

hookshot_flags.txt in the game folder is that line. hos_main.c prints the same text
(HOOKSHOT_COMPILE_FLAGS, given to that file only) so the log says what produced the binary.
Issue 2576.

-march and -ffp-contract=off are always there. -mtune is there when this PC or RX_MTUNE
set one. RX_CPU_FLAGS adds further flags after those (for example -mprefer-vector-width=256).
Include paths and another -ffp-contract are left out: the lifted code is proved with
contraction off.
"""
import os
import re


def cpu_flags(march, mtune, extra):
    """The CPU flags for this build, in the order clang receives them."""
    flags = ["-march=" + march, "-ffp-contract=off"]
    if mtune:
        flags.append("-mtune=" + mtune)
    for part in (extra or "").split():
        if part.startswith("-I") or part.startswith("--sysroot") or part.startswith("-ffp-contract"):
            continue
        flags.append(part)
    return flags


def text(flags):
    """One line, safe as a C string and as the flags= value."""
    return re.sub(r"[^A-Za-z0-9 ._+=,/:-]", "_", " ".join(flags))


def define(flags):
    return '-DHOOKSHOT_COMPILE_FLAGS="%s"' % text(flags)


def current():
    """The flags this process would compile with (RX_MARCH, RX_MTUNE, RX_CPU_FLAGS, else this PC)."""
    from host_cpu import host_march, host_mtune
    march = os.environ.get("RX_MARCH") or host_march()
    mtune = os.environ.get("RX_MTUNE") or host_mtune()
    return cpu_flags(march, mtune, os.environ.get("RX_CPU_FLAGS", ""))


def write(folder, flags=None):
    """hookshot_flags.txt in the game folder. The version file beside it is left as it is."""
    flags = current() if flags is None else flags
    path = os.path.join(folder, "hookshot_flags.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("flags=%s\n" % text(flags))
    return path
