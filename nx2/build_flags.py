"""The flags of the built game, embedded in its log and published beside hookshot_version.txt.

The CPU list is kept as arguments for a future update to reuse; the other fields describe the lifted code, hot code
and host runtime separately. They use build.py's object-key normalization, excluding include folders and temporary
sysroot paths. This describes the game, not a separately built or prebuilt renderer.
"""
import json
import os
import tempfile

FILENAME = "hookshot_build_flags.json"


def describe(cpu, lifted, hot, host, flag_text):
    return json.dumps({"format": 1, "cpu": cpu, "lifted": flag_text(lifted),
                       "hot": flag_text(hot), "host": flag_text(host)}, ensure_ascii=True, sort_keys=True)


def define(record):
    # record is already ASCII JSON. Encoding it again quotes its backslashes and quotes for a C string literal;
    # passing this as one compiler argument does not involve a shell.
    return "-DHOOKSHOT_BUILD_FLAGS=" + json.dumps(record, ensure_ascii=True)


def write(folder, record):
    """Only publish after a successful link; a failed write leaves the previous build's record intact."""
    path = os.path.join(folder, FILENAME)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", newline="\n", dir=folder,
                                         prefix="." + FILENAME + ".", delete=False) as stream:
            temporary = stream.name
            stream.write(record + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.remove(temporary)
