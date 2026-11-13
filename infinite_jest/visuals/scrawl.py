"""Hand-scrawled marks in the spirit of Basquiat: a jittered stroke alphabet,
crowns, copyright marks, crossings-out, arrows and rib-cage diagrams.

Everything is drawn as polylines with pygame.draw, so it needs no font files
and looks hand-made: every letter is wobbled slightly differently each time.
"""
import math
import random

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


def text_width(text, size):
    return len(text) * size * 0.95


def draw_text(surf, text, x, y, size, color, rng=None, jitter=0.35, width=2, slant=0.0):
    """Draw text in the stroke alphabet. size = letter height in pixels.
    jitter is in grid units (0 = clean, 0.6 = very shaky). Returns the bbox."""
    rng = rng or random
    sc = size / 6.0
    cx = x
    drift = 0.0
    for ch in text.upper():
        if ch == " ":
            cx += size * 0.7
            continue
        if ch == "©":
            draw_copyright(surf, cx + size * 0.4, y + size * 0.45, size * 0.45, color, rng, width)
            cx += size * 1.0
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


def draw_copyright(surf, cx, cy, r, color, rng, width=2):
    n = 14
    pts = []
    for i in range(n + 2):
        a = i / n * 2 * math.pi + rng.uniform(-0.1, 0.1)
        rr = r * (1 + rng.uniform(-0.12, 0.12))
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    _polyline(surf, color, pts, width)
    draw_text(surf, "C", cx - r * 0.45, cy - r * 0.55, r * 1.1, color, rng, 0.3, max(1, width - 1))


def draw_crown(surf, cx, cy, w, color, rng=None, width=2):
    """Three-pointed crown, the famous mark. cx, cy = centre of the base."""
    rng = rng or random
    h = w * 0.62
    j = w * 0.06
    base_l = (cx - w / 2 + rng.uniform(-j, j), cy + rng.uniform(-j, j))
    base_r = (cx + w / 2 + rng.uniform(-j, j), cy + rng.uniform(-j, j))
    pts = [base_l,
           (cx - w / 2 + rng.uniform(-j, j), cy - h + rng.uniform(-j, j)),
           (cx - w / 4 + rng.uniform(-j, j), cy - h * 0.45 + rng.uniform(-j, j)),
           (cx + rng.uniform(-j, j), cy - h * 1.08 + rng.uniform(-j, j)),
           (cx + w / 4 + rng.uniform(-j, j), cy - h * 0.45 + rng.uniform(-j, j)),
           (cx + w / 2 + rng.uniform(-j, j), cy - h + rng.uniform(-j, j)),
           base_r, base_l]
    _polyline(surf, color, pts, width)
    # little balls on the points
    for p in (pts[1], pts[3], pts[5]):
        pygame.draw.circle(surf, color, (int(p[0]), int(p[1] - w * 0.06)), max(1, int(w * 0.05)), max(1, width - 1))


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


def draw_ribs(surf, cx, cy, w, color, rng=None, width=2):
    """An anatomical rib-cage diagram: spine plus curved ribs."""
    rng = rng or random
    h = w * 1.1
    pygame.draw.line(surf, color, (cx, cy - h / 2), (cx + rng.uniform(-3, 3), cy + h / 2), width)
    for i in range(6):
        yy = cy - h / 2 + (i + 0.6) * h / 7
        rw = w / 2 * (0.65 + 0.35 * math.sin((i + 1) / 7 * math.pi))
        for s in (-1, 1):
            pts = []
            for k in range(7):
                t = k / 6
                pts.append((cx + s * rw * math.sin(t * math.pi * 0.55) + rng.uniform(-1, 1),
                            yy + rw * 0.35 * (1 - math.cos(t * math.pi * 0.8)) + rng.uniform(-1, 1)))
            _polyline(surf, color, pts, width)


def draw_skull(surf, cx, cy, r, color, rng=None, width=2):
    """Crude frontal skull: oval, eye sockets, teeth grid."""
    rng = rng or random
    pts = []
    for i in range(19):
        a = math.pi + i / 18 * math.pi * 2
        rx = r * (1.0 if math.sin(a) < 0.2 else 0.72)
        pts.append((cx + math.cos(a) * rx + rng.uniform(-1.5, 1.5), cy + math.sin(a) * r * 1.1 + rng.uniform(-1.5, 1.5)))
    _polyline(surf, color, pts, width)
    for s in (-1, 1):
        pygame.draw.circle(surf, color, (int(cx + s * r * 0.38), int(cy - r * 0.05)), max(2, int(r * 0.22)), width)
    ty = cy + r * 0.55
    pygame.draw.line(surf, color, (cx - r * 0.45, ty), (cx + r * 0.45, ty), width)
    for k in range(6):
        tx = cx - r * 0.45 + k * r * 0.18
        pygame.draw.line(surf, color, (tx, ty - r * 0.15), (tx, ty + r * 0.18), max(1, width - 1))
