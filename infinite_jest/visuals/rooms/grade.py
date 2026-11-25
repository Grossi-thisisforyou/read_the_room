"""Colour-grade a dreamt room into the show's palette, so the rooms sit next to the
colour-field abstractions as one body: the photograph keeps its light and its
detail, but its colours are pulled into one of the five-colour palettes of
visuals/palettes.py (dark tones into the palette's shadows, light into its light).

Then film grain, a soft vignette, a 16:9 crop and a gentle upscale to 1280x720.

    python3 grade.py in.png out.png --palette sodium [--strength 0.65] [--seed 3]

Needs numpy and Pillow (both are on the Pi and the Mac).
"""
import argparse

import numpy as np
from PIL import Image, ImageFilter

# Copied from visuals/palettes.py (dark -> light order for the room grades), so this
# file works on its own; kept to the palettes rooms.py uses.
PALETTES = {
    "sodium": ["#050300", "#2b1600", "#a35200", "#ff8c1a", "#fff1d6"],
    "bruise": ["#050507", "#1d1630", "#4b2c5e", "#8a6a9c", "#d8d0c0"],
    "teal": ["#030a0a", "#0f3534", "#1f7c74", "#d9a08c", "#efe7da"],
    "oxblood": ["#0b0304", "#3a0a10", "#8a1a28", "#d08a78", "#efe2d2"],
    "abyss": ["#020308", "#0b123a", "#1d2a78", "#8f8aa8", "#d8d4e8"],
    "abyss_green": ["#010504", "#06231e", "#0f4a40", "#7f9a90", "#d4e2dc"],
    "lilac": ["#0a0710", "#3b2d55", "#8f7bbd", "#e0a898", "#f4ece2"],
    "rose": ["#14070b", "#5e1630", "#cf4f78", "#e8a99a", "#f6e9dc"],
    "ash": ["#000000", "#151515", "#3d3d3d", "#8a8a8a", "#e0e0e0"],
}


def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _ramp(name):
    cols = np.array([_rgb(c) for c in PALETTES.get(name, PALETTES["ash"])], np.float32)
    # 256-step gradient through the five colours
    x = np.linspace(0, 4, 256)
    i = np.clip(np.floor(x).astype(int), 0, 3)
    t = (x - i)[:, None]
    return cols[i] * (1 - t) + cols[i + 1] * t


def grade(img, palette="ash", strength=0.65, seed=None, size=(1280, 720), darken=0.88):
    rng = np.random.default_rng(seed)
    img = img.convert("RGB")
    # 16:9 centre crop (a little above centre: rooms keep their floor)
    w, h = img.size
    tw, th = w, int(round(w * 9 / 16))
    if th > h:
        th, tw = h, int(round(h * 16 / 9))
    top = max(0, int((h - th) * 0.45))
    img = img.crop(((w - tw) // 2, top, (w - tw) // 2 + tw, top + th))
    img = img.resize(size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(img, np.float32)
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    # gentle S-curve on the light, then a little darker overall: the show is dark
    l = lum / 255.0
    l = np.clip(l * l * (3 - 2 * l) * 0.6 + l * 0.4, 0, 1) * darken
    mapped = _ramp(palette)[np.clip(l * 255, 0, 255).astype(np.uint8)]
    keep = a * (l / np.maximum(lum / 255.0, 1e-3))[..., None]      # original colour, new light
    grey = keep.mean(axis=2, keepdims=True)
    keep = grey + (keep - grey) * 0.5                                  # half its own saturation
    out = mapped * strength + keep * (1 - strength)
    # vignette
    yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
    r = np.hypot((xx - size[0] / 2) / (size[0] / 2), (yy - size[1] / 2) / (size[1] / 2))
    out *= np.clip(1.15 - 0.55 * r ** 2, 0.25, 1.0)[..., None]
    # film grain, stronger in the shadows
    g = rng.normal(0, 1, (size[1] // 2, size[0] // 2)).astype(np.float32)
    g = np.asarray(Image.fromarray(g).resize(size, Image.BILINEAR))
    out += (g * (9 + 10 * (1 - l)))[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--palette", default="ash", choices=sorted(PALETTES))
    p.add_argument("--strength", type=float, default=0.65)
    p.add_argument("--seed", type=int)
    a = p.parse_args()
    grade(Image.open(a.src), a.palette, a.strength, a.seed).save(a.dst)


if __name__ == "__main__":
    main()
