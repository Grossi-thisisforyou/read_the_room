"""The visitor's figure: camera frame in, smeared painted body out.

All arrays here are in pygame's [x, y] layout (width first) so they can be
blitted without transposing. Works on grayscale (the N900 sends gray8) or RGB.
Nothing is stored beyond the last few frames, and wipe() drops everything.
"""
import math

import numpy as np


def _resize_nearest(img, w, h):
    """img is [y, x] or [y, x, c] as delivered by the camera; returns [x, y] gray float32
    of size (w, h), centre-cropped to the target aspect."""
    if img.ndim == 3:
        img = img[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    else:
        img = img.astype(np.float32)
    ih, iw = img.shape
    target = w / h
    if iw / ih > target:  # too wide -> crop sides
        cw = int(ih * target)
        x0 = (iw - cw) // 2
        img = img[:, x0:x0 + cw]
    else:
        ch = int(iw / target)
        y0 = (ih - ch) // 2
        img = img[y0:y0 + ch, :]
    ih, iw = img.shape
    ys = (np.arange(h) * ih / h).astype(np.int32)
    xs = (np.arange(w) * iw / w).astype(np.int32)
    return img[ys][:, xs].T.copy()  # -> [x, y]


def _blur(a, passes=2):
    """Cheap separable box blur via np.roll (3-tap, repeated)."""
    for _ in range(passes):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0)) * (1 / 3)
        a = (a + np.roll(a, 1, 1) + np.roll(a, -1, 1)) * (1 / 3)
    return a


def ghost_body(w, h, t, seed=0, present=1.0):
    """A procedural stand-in figure (head + shoulders + torso) used when no camera
    is connected, and by the demo as a fake N900 frame. Returns [y, x] uint8 gray
    with a flat grey 'wall' behind, like a real static camera would see."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    wall = 118 + 10 * np.sin(xx / w * 3.1) + rng.normal(0, 3, (h, w))
    if present <= 0:
        return np.clip(wall, 0, 255).astype(np.uint8)
    sway = math.sin(t * 0.6 + seed) * w * 0.05
    cx = w * 0.5 + sway + (1 - present) * w * 0.6
    hy = h * 0.30 + math.sin(t * 1.3) * h * 0.01
    tilt = math.sin(t * 0.4 + seed) * 0.25
    # head
    dx = (xx - cx); dy = (yy - hy)
    rx = dx * math.cos(tilt) + dy * math.sin(tilt)
    ry = -dx * math.sin(tilt) + dy * math.cos(tilt)
    head = ((rx / (w * 0.13)) ** 2 + (ry / (h * 0.17)) ** 2) < 1
    # neck + shoulders + torso
    neck = (np.abs(xx - cx) < w * 0.05) & (yy > hy) & (yy < hy + h * 0.22)
    sh_y = hy + h * 0.24
    shoulders = ((((xx - cx) / (w * 0.36)) ** 2 + ((yy - sh_y - h * 0.1) / (h * 0.14)) ** 2) < 1) & (yy > sh_y - h * 0.02)
    torso = (np.abs(xx - cx) < w * (0.30 + 0.05 * (yy - sh_y) / h)) & (yy > sh_y + h * 0.06)
    body = head | neck | shoulders | torso
    # shading: light from the upper left, eye sockets, mouth
    shade = 150 - 70 * ((xx - cx) / (w * 0.4)) + 35 * np.cos((yy - hy) / h * 6)
    for s in (-1, 1):
        ex = cx + s * w * 0.05; ey = hy - h * 0.02
        shade -= 80 * np.exp(-(((xx - ex) / (w * 0.025)) ** 2 + ((yy - ey) / (h * 0.02)) ** 2))
    mouth_open = 0.5 + 0.5 * math.sin(t * 0.9)
    shade -= 90 * np.exp(-(((xx - cx) / (w * 0.045)) ** 2 + ((yy - hy - h * 0.09) / (h * (0.01 + 0.02 * mouth_open))) ** 2))
    skin = head | neck
    clothes = 55 + 25 * np.cos((xx - cx) / w * 9) - 20 * ((yy - sh_y) / h)
    img = np.where(skin, shade + 30, np.where(body, clothes, wall)) + rng.normal(0, 6, (h, w))
    return np.clip(img, 0, 255).astype(np.uint8)


class Figure:
    """Background subtraction + Bacon smear + flesh colouring at low resolution."""

    def __init__(self, w=160, h=180):
        self.w, self.h = w, h
        X, Y = np.mgrid[0:w, 0:h].astype(np.float32)  # [x, y]
        self.X, self.Y = X, Y
        self.ellipse = np.clip(1.25 - (((X - w / 2) / (w * 0.42)) ** 2 + ((Y - h * 0.55) / (h * 0.5)) ** 2), 0, 1)
        rng = np.random.default_rng(7)
        # directional "brush" texture: stretched noise gives visible strokes
        n = rng.random((w // 4 + 2, h // 16 + 2)).astype(np.float32)
        n = np.repeat(np.repeat(n, 4, 0), 16, 1)[:w, :h]
        self.brush = 0.82 + 0.36 * _blur(n, 1)
        self.wipe()

    def wipe(self):
        self.bg = None
        self.gray = None
        self.trail = None
        self.frames_seen = 0
        self.face = (self.w / 2, self.h * 0.3)
        self.mask = np.zeros((self.w, self.h), np.float32)

    def push(self, frame):
        """Feed a camera frame ([y, x] gray or [y, x, 3] RGB uint8)."""
        g = _resize_nearest(np.asarray(frame), self.w, self.h)
        if self.bg is None:
            self.bg = g.copy()
        diff = np.abs(g - self.bg)
        m = np.clip((diff - 14) / 26, 0, 1)
        m = _blur(m, 3)
        m = np.clip((m - 0.18) * 2.2, 0, 1)
        # background learns fast where empty, very slowly under the visitor
        rate = np.where(m > 0.3, 0.004, 0.06).astype(np.float32)
        self.bg += (g - self.bg) * rate
        cover = float(m.mean())
        if cover < 0.02:
            # nobody separable (or the phone moved): treat the frame as a portrait
            m = self.ellipse * (1 if self.frames_seen > 3 else 0)
        self.mask = m.astype(np.float32)
        self.gray = g
        self.trail = g if self.trail is None else self.trail * 0.7 + g * 0.3
        self.frames_seen += 1
        # face estimate: centroid of the upper third of the mask
        top = self.mask[:, : self.h // 3]
        s = top.sum()
        if s > 5:
            fx = float((top * self.X[:, : self.h // 3]).sum() / s)
            fy = float((top * self.Y[:, : self.h // 3]).sum() / s)
            self.face = (self.face[0] * 0.8 + fx * 0.2, self.face[1] * 0.8 + fy * 0.2)

    @property
    def ready(self):
        return self.gray is not None

    def render(self, t, smear, twist, swipe_angle, lut, alpha, trail_mix=0.4,
               flip_v=False, flip_h=False, taps=5):
        """Return (rgb [w,h,3] uint8, alpha [w,h] uint8, angle field [w,h])."""
        w, h = self.w, self.h
        X, Y = self.X, self.Y
        src = self.gray * (1 - trail_mix) + self.trail * trail_mix
        msk = self.mask
        # flow field: a dominant swipe direction bent by slow noise
        # X, Y are float32: reduce the time phases in float64 first, or after a
        # few days of uptime t*0.7 loses its fraction in float32 and the smear
        # stutters (5 days: frame-to-frame motion alternates 0.006/0.014;
        # 2 weeks: it freezes on every other frame)
        tau = 2 * math.pi
        ang = (swipe_angle
               + 0.9 * np.sin(X * 0.05 + (t * 0.7) % tau) * np.cos(Y * 0.031 - (t * 0.43) % tau)
               + 0.6 * np.sin((X + Y) * 0.021 + (t * 0.29) % tau))
        dx = np.cos(ang) * smear
        dy = np.sin(ang) * smear * 0.55
        # twist around the face: the scream / turned head
        fx, fy = self.face
        r2 = ((X - fx) ** 2 + (Y - fy) ** 2) / (w * 0.22) ** 2
        th = twist * np.exp(-r2)
        c, s = np.cos(th), np.sin(th)
        bx = fx + (X - fx) * c - (Y - fy) * s
        by = fy + (X - fx) * s + (Y - fy) * c
        acc = np.zeros((w, h), np.float32)
        macc = np.zeros((w, h), np.float32)
        for k in range(taps):
            f = k / max(1, taps - 1)
            ix = np.clip((bx + dx * f).astype(np.int32), 0, w - 1)
            iy = np.clip((by + dy * f).astype(np.int32), 0, h - 1)
            acc += src[ix, iy]
            macc += msk[ix, iy]
        g = acc / taps
        m = macc / taps
        # stretch contrast inside the body so the flesh LUT gets a full range
        inside = m > 0.3
        if inside.any():
            lo, hi = np.percentile(g[inside], (4, 96))
        else:
            lo, hi = 40.0, 200.0
        g = np.clip((g - lo) / max(8.0, hi - lo), 0, 1)
        g = np.clip(g * self.brush, 0, 1) ** 1.35  # pull highlights down into flesh
        rgb = lut[(g * 255).astype(np.uint8)]
        a = np.clip(m * alpha * 255, 0, 255).astype(np.uint8)
        if flip_v:
            rgb = rgb[:, ::-1]; a = a[:, ::-1]; ang = -ang[:, ::-1]
        if flip_h:
            rgb = rgb[::-1]; a = a[::-1]; ang = math.pi - ang[::-1]
        return rgb, a, ang


def flesh_lut(pal, rawness=0.5, cold=0.0):
    """256-entry RGB lookup from luminance to paint: bruise shadows, raw reds,
    flesh pinks, bone highlights. pal is the 5-colour palette."""
    p = [np.array(c, np.float32) for c in pal]
    raw = np.array([150, 28, 34], np.float32)
    bruise = np.array([46, 24, 70], np.float32)
    flesh = np.array([214, 138, 120], np.float32)
    bone = np.array([238, 222, 196], np.float32)
    if cold > 0:
        flesh = flesh * (1 - cold) + np.array([150, 160, 170], np.float32) * cold
        raw = raw * (1 - cold) + np.array([60, 70, 90], np.float32) * cold
    stops = [
        (0.00, p[0]),
        (0.18, bruise * 0.6 + p[1] * 0.4),
        (0.40, raw * rawness + p[2] * (1 - rawness) * 0.5 + flesh * (1 - rawness) * 0.5),
        (0.66, flesh * 0.7 + p[3] * 0.3),
        (0.88, bone * 0.6 + p[4] * 0.4),
        (1.00, np.array([255, 250, 240], np.float32)),
    ]
    lut = np.zeros((256, 3), np.float32)
    xs = np.linspace(0, 1, 256)
    for (x0, c0), (x1, c1) in zip(stops[:-1], stops[1:]):
        sel = (xs >= x0) & (xs <= x1)
        f = ((xs[sel] - x0) / (x1 - x0))[:, None]
        lut[sel] = c0 * (1 - f) + c1 * f
    return np.clip(lut, 0, 255).astype(np.uint8)
