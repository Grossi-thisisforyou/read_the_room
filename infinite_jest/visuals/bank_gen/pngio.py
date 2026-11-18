"""Tiny PNG reader/writer in pure Python (standard library only).

Used by postprocess.py when Pillow isn't installed, and by the tests to make
fake images. Reads 8-bit, non-interlaced PNGs of every colour type (grey,
RGB, palette, grey+alpha, RGBA); writes RGB and RGBA. That covers what
stable-diffusion.cpp and diffusers write. Anything else raises PNGError.

An image here is Raw(w, h, channels, data) with data a bytearray of rows,
channels 3 (RGB) or 4 (RGBA).
"""
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PNGError(ValueError):
    pass


class Raw:
    __slots__ = ("w", "h", "channels", "data")

    def __init__(self, w, h, channels, data):
        self.w, self.h, self.channels = w, h, channels
        self.data = data if isinstance(data, bytearray) else bytearray(data)
        if len(self.data) != w * h * channels:
            raise PNGError("data size %d does not match %dx%dx%d" % (len(self.data), w, h, channels))

    @property
    def mode(self):
        return "RGBA" if self.channels == 4 else "RGB"

    def pixel(self, x, y):
        i = (y * self.w + x) * self.channels
        return tuple(self.data[i:i + self.channels])


def _chunk(kind, data):
    c = struct.pack(">I", len(data)) + kind + data
    return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode(img, level=6):
    color_type = {1: 0, 3: 2, 4: 6}.get(img.channels)
    if color_type is None:
        raise PNGError("can only write grey, RGB or RGBA")
    stride = img.w * img.channels
    raw = bytearray()
    for y in range(img.h):
        raw.append(0)
        raw += img.data[y * stride:(y + 1) * stride]
    return (SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, color_type, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), level))
            + _chunk(b"IEND", b""))


def write(path, img, level=6):
    with open(path, "wb") as f:
        f.write(encode(img, level))


def size(path):
    """(width, height) from the header, without decoding. None if not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(SIGNATURE) or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(data, w, h, bpp):
    stride = w * bpp
    out = bytearray(stride * h)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        if pos >= len(data):
            raise PNGError("image data too short")
        ft = data[pos]
        line = bytearray(data[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if len(line) != stride:
            raise PNGError("image data too short")
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        else:
            raise PNGError("bad filter type %d" % ft)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def decode(blob):
    if not blob.startswith(SIGNATURE):
        raise PNGError("not a PNG file")
    pos = 8
    ihdr = None
    plte = None
    trns = None
    idat = []
    while pos + 8 <= len(blob):
        length, kind = struct.unpack(">I4s", blob[pos:pos + 8])
        data = blob[pos + 8:pos + 8 + length]
        if len(data) != length:
            raise PNGError("truncated chunk %r" % kind)
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif kind == b"PLTE":
            plte = data
        elif kind == b"tRNS":
            trns = data
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            break
    if not ihdr or not idat:
        raise PNGError("missing header or image data")
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8:
        raise PNGError("only 8-bit PNGs are supported (this one is %d-bit)" % depth)
    if interlace:
        raise PNGError("interlaced PNGs are not supported")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if bpp is None:
        raise PNGError("unknown colour type %d" % ctype)
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise PNGError("corrupt image data: %s" % e)
    px = _unfilter(raw, w, h, bpp)
    if ctype == 2:
        return Raw(w, h, 3, px)
    if ctype == 6:
        return Raw(w, h, 4, px)
    if ctype == 0:
        out = bytearray(w * h * 3)
        out[0::3] = px
        out[1::3] = px
        out[2::3] = px
        return Raw(w, h, 3, out)
    if ctype == 4:
        out = bytearray(w * h * 4)
        out[0::4] = px[0::2]
        out[1::4] = px[0::2]
        out[2::4] = px[0::2]
        out[3::4] = px[1::2]
        return Raw(w, h, 4, out)
    # palette
    if not plte:
        raise PNGError("palette image without palette")
    n = len(plte) // 3
    alpha = bytearray(trns or b"") + bytearray([255] * n)
    has_alpha = bool(trns)
    ch = 4 if has_alpha else 3
    table = [bytes(plte[i * 3:i * 3 + 3]) + (bytes([alpha[i]]) if has_alpha else b"") for i in range(n)]
    out = bytearray()
    for v in px:
        if v >= n:
            raise PNGError("palette index out of range")
        out += table[v]
    return Raw(w, h, ch, out)


def read(path):
    with open(path, "rb") as f:
        return decode(f.read())
