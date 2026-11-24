#!/usr/bin/env python3
"""Draw the INFINITE JEST boot splash.

Runs on any computer with Python 3 and Pillow (pip install pillow).
On the Pi itself you do not need this: plymouth/splash.png is already in the repo.

    python3 make_splash.py              # from this folder: writes plymouth/splash.png (1920x1080)
    python3 make_splash.py --seed 7     # a different smear, same layout

The look, in three layers:
  1. Bacon: a smeared, fleshy figure trapped in a thin "space frame" cage.
  2. Baselitz: the figure hangs upside down.
  3. Scrawled caps and crossed-out words.
Everything sits on near-black so the projector shows a dark room, not a
bright rectangle, while the Pi boots.
"""
import argparse
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
BLACK = (8, 6, 7)
FLESH = [(150, 52, 60), (196, 98, 92), (120, 30, 44), (226, 150, 128), (84, 20, 30)]
BONE = (226, 214, 196)
RUST = (170, 60, 28)
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def wobbly_line(d, p0, p1, rnd, width, fill, wobble=4.0, steps=18):
    """A hand-drawn line: many short segments with a bit of drift."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = p0[0] + (p1[0] - p0[0]) * t + rnd.uniform(-wobble, wobble)
        y = p0[1] + (p1[1] - p0[1]) * t + rnd.uniform(-wobble, wobble)
        pts.append((x, y))
    d.line(pts, fill=fill, width=width, joint="curve")


def drag(layer, length):
    """Horizontal motion blur: average copies shifted left and right."""
    acc = layer
    for i, k in enumerate(range(-length, length + 1, 10)):
        shifted = ImageChops.offset(layer, k, 0)
        acc = Image.blend(acc, shifted, 1.0 / (i + 2))
    return Image.blend(layer, acc, 0.65)


def smear_figure(rnd):
    """Bacon layer: blobs of flesh dragged sideways, then upside down."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = W * 0.5, H * 0.47
    # torso, head, an arm: drawn upright, flipped later (Baselitz)
    parts = [
        (cx, cy + 40, 150, 210),   # torso
        (cx + 10, cy - 210, 85, 100),  # head
        (cx - 150, cy + 10, 50, 170),  # arm
        (cx + 140, cy + 80, 45, 140),  # arm
    ]
    for (x, y, rx, ry) in parts:
        for _ in range(60):
            c = rnd.choice(FLESH)
            a = rnd.randint(70, 160)
            px = x + rnd.gauss(0, rx * 0.4)
            py = y + rnd.gauss(0, ry * 0.4)
            r = rnd.uniform(14, 48)
            d.ellipse([px - r * 1.6, py - r, px + r * 1.6, py + r], fill=c + (a,))
    # mouth: the scream, a dark hole with teeth
    mx, my = cx + 10, cy - 190
    d.ellipse([mx - 38, my - 22, mx + 38, my + 30], fill=(20, 4, 8, 235))
    for i in range(6):
        tx = mx - 28 + i * 11
        d.rectangle([tx, my - 18, tx + 6, my - 8], fill=BONE + (220,))
    layer = layer.filter(ImageFilter.GaussianBlur(9))
    layer = drag(layer, 70)
    # drag the paint sideways in strips, like a dry brush pulled across
    out = layer.copy()
    for y in range(0, H, 6):
        if rnd.random() < 0.55:
            shift = int(rnd.gauss(0, 40))
            strip = layer.crop((0, y, W, y + 6))
            out.paste(ImageChops.offset(strip, shift, 0), (0, y), strip)
    return out.rotate(180)


def space_frame(d, rnd):
    """Bacon's cage: a thin perspective box around the figure."""
    x0, y0, x1, y1 = 640, 210, 1280, 900
    dx, dy = 120, -70
    col = BONE + (150,)
    front = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    back = [(x + dx, y + dy) for (x, y) in front]
    for i in range(4):
        wobbly_line(d, front[i], front[(i + 1) % 4], rnd, 2, col, 1.5)
        wobbly_line(d, back[i], back[(i + 1) % 4], rnd, 2, col, 1.5)
        wobbly_line(d, front[i], back[i], rnd, 2, col, 1.5)
    # the floor plane Bacon puts under his sitters
    d.polygon([(x0 - 60, y1), (x1 + 60, y1), (x1 + dx + 80, y1 + dy), (x0 + dx - 80, y1 + dy)],
              fill=(60, 14, 18, 70))


def scrawl(img, text, x, y, size, rnd, fill, tilt=4):
    """Hand-lettered caps: each letter its own size, tilt and baseline."""
    f = font(size)
    cx = x
    for ch in text:
        if ch == " ":
            cx += size * 0.45
            continue
        s = int(size * rnd.uniform(0.85, 1.15))
        g = Image.new("RGBA", (s * 2, s * 2), (0, 0, 0, 0))
        ImageDraw.Draw(g).text((s * 0.4, s * 0.2), ch, font=font(s), fill=fill)
        g = g.rotate(rnd.uniform(-tilt, tilt), resample=Image.BICUBIC)
        img.alpha_composite(g, (int(cx - s * 0.4), int(y + rnd.uniform(-6, 6) - s * 0.2)))
        cx += f.getlength(ch) * rnd.uniform(0.9, 1.05)
    return cx


def strike(d, x0, x1, y, rnd, fill):
    wobbly_line(d, (x0 - 10, y), (x1 + 10, y + rnd.uniform(-8, 8)), rnd, 6, fill, 2, 10)


def grain(img, rnd, amount=14):
    noise = Image.effect_noise((W, H), amount).convert("L")
    noise = Image.merge("RGBA", (noise, noise, noise, Image.new("L", (W, H), 22)))
    img.alpha_composite(noise)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1312)
    ap.add_argument("--out", default="plymouth/splash.png")
    ap.add_argument("--title", default="INFINITE JEST")
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    img = Image.new("RGBA", (W, H), BLACK + (255,))
    d = ImageDraw.Draw(img)
    space_frame(d, rnd)
    img.alpha_composite(smear_figure(rnd))
    d = ImageDraw.Draw(img)

    # lettering layer
    scrawl(img, args.title, 172, 112, 92, rnd, BONE + (240,))
    x = scrawl(img, "DARK DATA", 172, 900, 54, rnd, RUST + (230,), tilt=6)
    strike(d, 172, x, 930, rnd, BONE + (210,))
    scrawl(img, "CUSTOM MADE INTIMACY", 172, 966, 40, rnd, BONE + (200,), tilt=5)
    rx = scrawl(img, "IN ART WE TRUST", 1340, 966, 40, rnd, BONE + (190,), tilt=5)
    strike(d, 1340 + 40 * 3.6, rx, 990, rnd, RUST + (220,))  # cross out "WE TRUST"

    # vignette so the corners fall into the dark room
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-260, -300, W + 260, H + 300], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGBA", (W, H), BLACK + (255,))
    img = Image.composite(img, dark, vig)
    grain(img, rnd)
    img.convert("RGB").save(args.out, optimize=True)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
