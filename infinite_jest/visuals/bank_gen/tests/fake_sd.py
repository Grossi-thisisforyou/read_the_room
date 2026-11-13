#!/usr/bin/env python3
"""Stand-in for stable-diffusion.cpp's CLI, for testing generate.py only.

Accepts the same arguments, sleeps FAKE_SD_SECONDS (default 8) printing
progress, then writes a small solid-colour PNG to the -o path using only the
standard library. Exit code FAKE_SD_EXIT (default 0) can simulate a failure.
"""
import os
import struct
import sys
import time
import zlib


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main(argv):
    out, seed = None, 0
    for i, arg in enumerate(argv):
        if arg in ("-o", "--output"):
            out = argv[i + 1]
        elif arg in ("-s", "--seed"):
            seed = int(argv[i + 1])
    if not out:
        print("fake_sd: no -o given", file=sys.stderr)
        return 1
    secs = float(os.environ.get("FAKE_SD_SECONDS", "8"))
    steps = 8
    print("fake_sd: pid %d, args %s" % (os.getpid(), " ".join(argv[:4])), flush=True)
    for s in range(1, steps + 1):
        time.sleep(secs / steps)
        print("  |%s%s| %d/%d" % ("=" * s, " " * (steps - s), s, steps), flush=True)
    rc = int(os.environ.get("FAKE_SD_EXIT", "0"))
    if rc:
        print("fake_sd: simulated failure", flush=True)
        return rc
    write_png(out, 16, 16, (seed % 256, 40, 60))
    print("fake_sd: saved %s" % out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
