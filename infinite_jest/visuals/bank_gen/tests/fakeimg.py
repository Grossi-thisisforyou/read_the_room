"""Fake images for the tests, made with the standard library (bank_gen/pngio.py)."""
import json
import os
import random
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pngio  # noqa: E402

ORANGE = (212, 98, 42)
PINK = (225, 150, 140)

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def figure_on_ground(w=96, h=96, ground=ORANGE, figure=PINK, box=None, noise=4, seed=0):
    """A flat ground with a rectangular 'figure', a little paint noise."""
    rng = random.Random(seed)
    box = box or (w * 3 // 10, h // 5, w * 6 // 10, h * 9 // 10)
    data = bytearray()
    for y in range(h):
        for x in range(w):
            c = figure if box[0] <= x < box[2] and box[1] <= y < box[3] else ground
            n = rng.randint(-noise, noise) if noise else 0
            data += bytes(max(0, min(255, v + n)) for v in c)
    return pngio.Raw(w, h, 3, data)


def noise_image(w=64, h=64, seed=1):
    rng = random.Random(seed)
    return pngio.Raw(w, h, 3, bytearray(rng.getrandbits(8) for _ in range(w * h * 3)))


def save(path, img):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pngio.write(path, img)
    return path


def sidecar(path, **fields):
    data = {"hook": os.path.basename(os.path.dirname(path)), "prompt": "a test prompt"}
    data.update(fields)
    with open(os.path.splitext(path)[0] + ".json", "w") as f:
        json.dump(data, f)


def filtered_png(img, filters):
    """Encode img with the given PNG row filter per row (cycled), to test the
    decoder against all five filter types."""
    bpp = img.channels
    stride = img.w * bpp
    out = bytearray()
    prev = bytearray(stride)
    for y in range(img.h):
        row = img.data[y * stride:(y + 1) * stride]
        ft = filters[y % len(filters)]
        enc = bytearray(stride)
        for i in range(stride):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ft == 0:
                pred = 0
            elif ft == 1:
                pred = a
            elif ft == 2:
                pred = b
            elif ft == 3:
                pred = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            enc[i] = (row[i] - pred) & 0xFF
        out.append(ft)
        out += enc
        prev = row

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ctype = {3: 2, 4: 6}[img.channels]
    return (pngio.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out))) + chunk(b"IEND", b""))
