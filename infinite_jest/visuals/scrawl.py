"""Hand-scrawled marks: a jittered stroke alphabet, surveillance marks
(reticles, face-detection brackets, barcodes, tallies, redaction bars),
crossings-out and arrows.

Everything is drawn as polylines with pygame.draw, so it needs no font files
and looks hand-made: every letter is wobbled slightly differently each time.
"""
import math
import random
import unicodedata

import pygame

# Stroke alphabet on a 4 x 6 grid (x right, y down). Each glyph is a list of
# polylines; each polyline is a list of (x, y) points.
_G = {
    "A": [[(0, 6), (2, 0), (4, 6)], [(1, 3.5), (3, 3.5)]],
    "B": [[(0, 6), (0, 0), (3, 0), (4, 1), (3, 3), (0, 3)], [(3, 3), (4, 4.5), (3, 6), (0, 6)]],
    "C": [[(4, 0.5), (3, 0), (1, 0), (0, 1.5), (0, 4.5), (1, 6), (3, 6), (4, 5.5)]],
    "D": [[(0, 0), (0, 6), (2.5, 6), (4, 4.5), (4, 1.5), (2.5, 0), (0, 0)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "G": [[(4, 0.5), (3, 0), (1, 0), (0, 1.5), (0, 4.5), (1, 6), (3, 6), (4, 5), (4, 3.5), (2.5, 3.5)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 0), (3, 0)], [(2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "J": [[(4, 0), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "K": [[(0, 0), (0, 6)], [(4, 0), (0, 3.5)], [(1.3, 2.7), (4, 6)]],
    "L": [[(0, 0), (0, 6), (4, 6)]],
    "M": [[(0, 6), (0, 0), (2, 3), (4, 0), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "O": [[(1, 0), (3, 0), (4, 1.5), (4, 4.5), (3, 6), (1, 6), (0, 4.5), (0, 1.5), (1, 0)]],
    "P": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    "Q": [[(1, 0), (3, 0), (4, 1.5), (4, 4.5), (3, 6), (1, 6), (0, 4.5), (0, 1.5), (1, 0)], [(2.5, 4.5), (4.3, 6.5)]],
    "R": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)], [(2, 3), (4, 6)]],
    "S": [[(4, 0.5), (3, 0), (1, 0), (0, 1), (0, 2), (1, 3), (3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5.5)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "U": [[(0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)]],
    "V": [[(0, 0), (2, 6), (4, 0)]],
    "W": [[(0, 0), (1, 6), (2, 2.5), (3, 6), (4, 0)]],
    "X": [[(0, 0), (4, 6)], [(4, 0), (0, 6)]],
    "Y": [[(0, 0), (2, 3), (4, 0)], [(2, 3), (2, 6)]],
    "Z": [[(0, 0), (4, 0), (0, 6), (4, 6)]],
    "0": [[(1, 0), (3, 0), (4, 1.5), (4, 4.5), (3, 6), (1, 6), (0, 4.5), (0, 1.5), (1, 0)], [(4, 1), (0, 5)]],
    "1": [[(1, 1), (2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "2": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (0, 6), (4, 6)]],
    "3": [[(0, 0.5), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1.5, 3)], [(3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5.5)]],
    "4": [[(3, 6), (3, 0), (0, 4), (4, 4)]],
    "5": [[(4, 0), (0.5, 0), (0, 3), (3, 2.7), (4, 3.8), (4, 5), (3, 6), (0, 6)]],
    "6": [[(3.5, 0), (1, 0.5), (0, 3), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3.5)]],
    "7": [[(0, 0), (4, 0), (1.5, 6)]],
    "8": [[(2, 3), (0.5, 2), (0.5, 0.7), (2, 0), (3.5, 0.7), (3.5, 2), (2, 3), (0, 4.3), (0.5, 5.7), (2, 6), (3.5, 5.7), (4, 4.3), (2, 3)]],
    "9": [[(4, 2.5), (1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (3, 6), (0.5, 6)]],
    ".": [[(1.8, 5.6), (2.2, 6)]],
    ",": [[(2, 5.5), (1.5, 7)]],
    ":": [[(1.8, 1.8), (2.2, 2.2)], [(1.8, 4.8), (2.2, 5.2)]],
    "%": [[(4, 0), (0, 6)], [(0.5, 0.5), (1, 1)], [(3, 5), (3.5, 5.5)]],
    "-": [[(0.5, 3), (3.5, 3)]],
    "+": [[(0.5, 3), (3.5, 3)], [(2, 1.5), (2, 4.5)]],
    "?": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (2, 3.5), (2, 4.3)], [(2, 5.6), (2, 6)]],
    "!": [[(2, 0), (2, 4.2)], [(2, 5.6), (2, 6)]],
    "/": [[(4, 0), (0, 6)]],
    "=": [[(0.5, 2), (3.5, 2)], [(0.5, 4), (3.5, 4)]],
    "'": [[(2, 0), (1.7, 1.5)]],
    "#": [[(1.3, 0), (1, 6)], [(3, 0), (2.7, 6)], [(0, 2), (4, 2)], [(0, 4), (4, 4)]],
}


def _wobble(rng, amount):
    return (rng.uniform(-amount, amount), rng.uniform(-amount, amount))


def _polyline(surf, color, pts, width):
    if len(pts) < 2:
        return
    if width <= 1:
        pygame.draw.aalines(surf, color, False, pts)
    else:
        pygame.draw.lines(surf, color, False, pts, width)


def fold(text):
    """Accents off (E for É); anything without a glyph is skipped, never boxed."""
    t = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in t if not unicodedata.combining(c))


def text_width(text, size):
    return len(fold(text)) * size * 0.95


def fit_size(text, size, max_w):
    """Shrink size so the word fits max_w (long words would run off the wall)."""
    w = text_width(text, size)
    return size * max_w / w if w > max_w > 0 else size


def draw_text(surf, text, x, y, size, color, rng=None, jitter=0.35, width=2, slant=0.0):
    """Draw text in the stroke alphabet. size = letter height in pixels.
    jitter is in grid units (0 = clean, 0.6 = very shaky). Returns the bbox."""
    rng = rng or random
    sc = size / 6.0
    cx = x
    drift = 0.0
    for ch in fold(text).upper():
        if ch == " ":
            cx += size * 0.7
            continue
        glyph = _G.get(ch)
        if glyph is None:
            cx += size * 0.6
            continue
        drift += rng.uniform(-0.25, 0.25) * jitter * sc
        letter_scale = 1.0 + rng.uniform(-0.18, 0.18) * jitter
        for line in glyph:
            pts = []
            for gx, gy in line:
                wx, wy = _wobble(rng, jitter)
                px = cx + (gx + wx + slant * (6 - gy)) * sc * letter_scale
                py = y + drift + (gy + wy) * sc * letter_scale
                pts.append((px, py))
            _polyline(surf, color, pts, width)
        cx += size * (0.95 + rng.uniform(-0.1, 0.15) * jitter)
    return pygame.Rect(int(x), int(y - size * 0.2), int(cx - x), int(size * 1.4))


def draw_reticle(surf, cx, cy, r, color, rng=None, width=2):
    """A hand-drawn targeting reticle: wobbly circle plus crosshair ticks."""
    rng = rng or random
    pts = []
    for i in range(20):
        a = i / 18 * 2 * math.pi + rng.uniform(-0.08, 0.08)
        rr = r * (1 + rng.uniform(-0.08, 0.08))
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    _polyline(surf, color, pts, width)
    for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        x0 = cx + math.cos(a) * r * 0.55; y0 = cy + math.sin(a) * r * 0.55
        x1 = cx + math.cos(a) * r * 1.35; y1 = cy + math.sin(a) * r * 1.35
        pygame.draw.line(surf, color, (x0 + rng.uniform(-1, 1), y0), (x1, y1 + rng.uniform(-1, 1)), width)


def draw_barcode(surf, x, y, w, h, color, rng=None):
    """Crude barcode of uneven bars."""
    rng = rng or random
    cx = x
    while cx < x + w:
        bw = rng.choice([1, 1, 2, 3])
        if rng.random() < 0.6:
            pygame.draw.rect(surf, color, (int(cx), int(y + rng.uniform(-1, 1)), bw, int(h)))
        cx += bw + rng.choice([1, 2, 2, 3])


def draw_tally(surf, x, y, h, n, color, rng=None, width=2):
    """Prison-wall tally marks, groups of five."""
    rng = rng or random
    step = h * 0.28
    for i in range(n):
        g, k = divmod(i, 5)
        gx = x + g * step * 6
        if k < 4:
            xx = gx + k * step
            pygame.draw.line(surf, color, (xx + rng.uniform(-1, 1), y), (xx + rng.uniform(-2, 2), y + h), width)
        else:
            pygame.draw.line(surf, color, (gx - step * 0.4, y + h * 0.8), (gx + step * 3.4, y + h * 0.2), width)


def draw_redaction(surf, x, y, w, h, color, rng=None):
    """A rough black redaction bar."""
    rng = rng or random
    pts = [(x + rng.uniform(-2, 2), y + rng.uniform(-1, 1)), (x + w + rng.uniform(-3, 3), y + rng.uniform(-2, 2)),
           (x + w + rng.uniform(-3, 3), y + h + rng.uniform(-2, 2)), (x + rng.uniform(-2, 2), y + h + rng.uniform(-1, 1))]
    pygame.draw.polygon(surf, color, pts)


def draw_face_box(surf, rect, color, rng=None, width=2, label=None, size=12):
    """Face-detection corner brackets with landmark dots and a score label."""
    rng = rng or random
    x, y, w, h = rect
    L = min(w, h) * 0.25
    for (cx, cy, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        j = rng.uniform(-1.5, 1.5)
        pygame.draw.line(surf, color, (cx, cy + j), (cx + dx * L, cy + j), width)
        pygame.draw.line(surf, color, (cx + j, cy), (cx + j, cy + dy * L), width)
    for fx, fy in ((0.33, 0.4), (0.67, 0.4), (0.5, 0.58), (0.38, 0.74), (0.62, 0.74)):
        px = x + w * fx + rng.uniform(-2, 2); py = y + h * fy + rng.uniform(-2, 2)
        pygame.draw.circle(surf, color, (int(px), int(py)), max(1, width))
    if label:
        draw_text(surf, label, x, y - size * 1.5, size, color, rng, 0.15, max(1, width - 1))


def cross_out(surf, rect, color, rng=None, width=3, mode=None):
    """Strike through a word: single bar, double bar, or scribble."""
    rng = rng or random
    mode = mode or rng.choice(["bar", "bar", "bar", "double", "double", "scribble"])
    x0, x1 = rect.left - 3, rect.right + 3
    ym = rect.centery
    if mode == "bar":
        pygame.draw.line(surf, color, (x0, ym + rng.uniform(-2, 2)), (x1, ym + rng.uniform(-3, 3)), width)
    elif mode == "double":
        for dy in (-rect.height * 0.15, rect.height * 0.15):
            pygame.draw.line(surf, color, (x0, ym + dy + rng.uniform(-2, 2)), (x1, ym + dy + rng.uniform(-2, 2)), width)
    else:
        pts = []
        x = x0
        up = True
        while x < x1:
            pts.append((x, rect.top + 2 if up else rect.bottom - 2))
            x += rng.uniform(3, 7)
            up = not up
        _polyline(surf, color, pts, max(1, width - 1))


def draw_arrow(surf, x0, y0, x1, y1, color, rng=None, width=2):
    rng = rng or random
    pygame.draw.line(surf, color, (x0, y0), (x1, y1), width)
    a = math.atan2(y1 - y0, x1 - x0)
    L = 8 + rng.uniform(0, 4)
    for s in (-1, 1):
        aa = a + math.pi + s * 0.5
        pygame.draw.line(surf, color, (x1, y1), (x1 + math.cos(aa) * L, y1 + math.sin(aa) * L), width)
