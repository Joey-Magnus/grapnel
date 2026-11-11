"""Makes picture.png, the picture behind the Linux launcher, from the Windows launcher's (run by hand when that changes):

    python -I builder/linux/launcher/make_picture.py builder/HookshotBuilder/Images/launcher.jpg

Tk reads no JPEG, and draws no picture at 12% as MainWindow.xaml does, so the picture is stored as the window shows it: 12% of
it over the page's colour, in a PNG whose rows launcher_art.read_png undoes with numpy alone. Dim as it is, it packs to about
the JPEG's size. Needs Pillow to read the JPEG (or give it a 24-bit .bmp); numpy as the launcher itself."""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import launcher_art  # noqa: E402

OPACITY = 0.12   # (MainWindow.xaml: the Image's Opacity)


def read(path):
    if path.lower().endswith(".bmp"):
        with open(path, "rb") as f:
            data = f.read()
        offset, = struct.unpack_from("<I", data, 10)
        w, h, _planes, bits = struct.unpack_from("<iiHH", data, 18)
        if bits != 24:
            raise SystemExit("a 24-bit .bmp, not %d-bit" % bits)
        stride = (w * 3 + 3) & ~3
        rows = np.frombuffer(data, dtype=np.uint8, count=stride * abs(h), offset=offset).reshape(abs(h), stride)[:, :w * 3]
        rows = rows.reshape(abs(h), w, 3)[:, :, ::-1]   # (stored blue first)
        return rows[::-1] if h > 0 else rows            # (and bottom row first)
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"))


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    full = read(sys.argv[1]).astype(np.float32)
    page = np.asarray(launcher_art.PAGE, dtype=np.float32)
    dim = np.clip(page + (full - page) * OPACITY + 0.5, 0, 255).astype(np.uint8)
    out = os.path.join(HERE, "picture.png")
    with open(out, "wb") as f:
        f.write(launcher_art.png(dim, level=9, sub=True))
    back = launcher_art.read_png(out)
    assert (back == dim).all(), "picture.png does not read back as written"
    print("%s: %d x %d, %d KB" % (out, dim.shape[1], dim.shape[0], os.path.getsize(out) // 1024))


if __name__ == "__main__":
    main()
