"""Painted grounds and props.

A ground is a flat saturated field that has been painted by hand: big broad
strokes that leave the canvas tooth showing, a few hard knife edges, a floor
band, painted shadows, and a light that falls off toward the edges without
going to black (projected black is just the wall: see PROJECTION.md).

Grounds are painted once per scene, in steps, so the engine can spread the
work over a few frames: build_ground() is a generator that yields while it
works and returns the finished pygame Surface (StopIteration.value).
"""
import math

import numpy as np
import pygame

from . import brush, palettes


def _noise(w, h, cell, rng):
    """Smooth value noise in 0..1, (w, h). Made on a coarse grid, softened there,
    then scaled up by pygame (fast), so it costs ~1 ms even at full size."""
    gw, gh = w // cell + 4, h // cell + 4
    n = rng.random((gw, gh)).astype(np.float32)
    n = (n + np.roll(n, 1, 0) + np.roll(n, -1, 0)) / 3
    n = (n + np.roll(n, 1, 1) + np.roll(n, -1, 1)) / 3
    n -= n.min()
    n = (n / max(1e-6, n.max()) * 255).astype(np.uint8)
    s = pygame.Surface((gw, gh))
    pygame.surfarray.blit_array(s, np.repeat(n[..., None], 3, 2))
    big = pygame.transform.smoothscale(s, (gw * cell, gh * cell))
    out = pygame.surfarray.pixels_red(big)[cell:cell + w, cell:cell + h].astype(np.float32) / 255.0
    return out


def _streaks(w, h, rng, horizontal=True, length=24):
    """Noise dragged along one direction: the trace of a broad brush."""
    n = rng.random((w, h)).astype(np.float32)
    ax = 0 if horizontal else 1
    c = np.cumsum(n, axis=ax)
    if ax == 0:
        s = np.empty_like(n)
        s[length:] = (c[length:] - c[:-length]) / length
        s[:length] = s[length:2 * length]
    else:
        s = np.empty_like(n)
        s[:, length:] = (c[:, length:] - c[:, :-length]) / length
        s[:, :length] = s[:, length:2 * length]
    s -= s.mean()
    return s / max(1e-6, np.abs(s).max())


def build_ground(W, H, spec, tooth=None):
    """Generator: paints the ground described by spec and returns a Surface of
    size (W, H). spec keys (all optional):
      kind     'room' (field and floor), 'field', 'wall', 'deep', 'column'
      pal      5 colours, dark to light
      horizon  0..1, where the floor starts (room)
      panels   1 or 3 (a triptych: three panels with gaps)
      shadow   (x, y, rx, ry) in 0..1: a painted shadow pool
      light    (x, y, r) in 0..1: where the light falls
      seed     int
      busy     0..1 how many visible strokes
    """
    rng = np.random.default_rng(spec.get("seed", 0))
    pal = [np.array(c, np.float32) for c in spec.get("pal", palettes.get("triptych"))]
    kind = spec.get("kind", "room")
    horizon = spec.get("horizon", 0.7)
    busy = spec.get("busy", 0.5)
    hz = int(H * horizon)
    fine = W * H >= brush.FINE_PX     # big grounds: more, smaller steps (smaller ones as v2)
    X = np.arange(W, dtype=np.float32)[:, None] / W
    Y = np.arange(H, dtype=np.float32)[None, :] / H
    field = pal[2].copy()
    if kind == "deep":
        field = pal[2] * 0.55 + pal[1] * 0.45
    # The field is worked as three colour planes [W, H] (contiguous, in place):
    # the same arithmetic as on an [W, H, 3] array, without the 3.3 MB
    # temporaries per step that made scene changes hitch.
    planes = [np.full((W, H), field[c], np.float32) for c in range(3)]
    floor = None
    if kind == "room":
        floor = pal[1] * 0.55 + pal[2] * 0.45
        # the floor darkens toward the viewer a little, a painted perspective
        fl = (1.0 - 0.18 * ((Y[:, hz:] - horizon) / max(1e-3, 1 - horizon)))
        for c in range(3):
            planes[c][:, hz:] = floor[c]
            planes[c][:, hz:] *= fl
    elif kind == "column":
        floor = pal[1] * 0.7 + pal[2] * 0.3
        for c in range(3):
            planes[c][:, hz:] = floor[c]
    yield
    # hand-painted flatness: a slow value wobble and brush drag in the paint
    lo = _noise(W, H, 48, rng)
    lo *= 0.1
    lo += 0.95
    for c in range(3):
        planes[c] *= lo
    yield
    st = _streaks(W, H, rng, horizontal=kind != "wall", length=28)
    if fine:
        yield
    st *= 0.04
    st += 1
    for c in range(3):
        planes[c] *= st
    yield
    # hue drift across the field: one side a little warmer, the other cooler
    warm = np.array([1.04, 1.0, 0.95], np.float32)
    cool = np.array([0.96, 0.99, 1.05], np.float32)
    k = _noise(W, H, 90, rng)
    yield
    tmp = np.empty((W, H), np.float32)
    for c in range(3):
        np.multiply(k, warm[c] - cool[c], out=tmp)
        tmp += cool[c]
        planes[c] *= tmp
    yield
    # light: a pool where the figure stands, falling off toward the edges into
    # a darker, *more* saturated version of the ground rather than black
    lx, ly, lr = spec.get("light", (0.5, 0.45, 0.6))
    d2 = ((X - lx) / lr) ** 2 + ((Y - ly) / (lr * 0.9)) ** 2
    fall = np.exp(-d2 * 0.9)
    yield
    if kind == "column":
        cx = spec.get("light", (0.5,))[0]
        col = np.exp(-((X - cx) / 0.16) ** 2)            # (W, 1)
        for c in range(3):
            planes[c] *= (0.5 + 0.75 * col)
            planes[c] += pal[3][c] * 0.15 * col
    else:
        # dark = arr * m + p;  arr = dark + (arr * 1.06 - dark) * F
        #      = arr * (m + (1.06 - m) F) + p (1 - F)
        mul = np.array([0.72, 0.62, 0.66], np.float32)
        F = fall
        F *= 0.65
        F += 0.35
        for c in range(3):
            p = pal[1][c] * 0.12
            np.multiply(F, 1.06 - mul[c], out=tmp)
            tmp += mul[c]
            planes[c] *= tmp
            np.multiply(F, -p, out=tmp)
            tmp += p
            planes[c] += tmp
    sh = spec.get("shadow")
    if sh:
        yield
        sx, sy, srx, sry = sh
        # the pool is zero outside the ellipse d < 1.25: work only on its box
        e = math.sqrt(1.25)
        bx0 = max(0, int((sx - srx * e) * W) - 1); bx1 = min(W, int((sx + srx * e) * W) + 2)
        by0 = max(0, int((sy - sry * e) * H) - 1); by1 = min(H, int((sy + sry * e) * H) + 2)
        if bx1 > bx0 and by1 > by0:
            d = ((X[bx0:bx1] - sx) / srx) ** 2 + ((Y[:, by0:by1] - sy) / sry) ** 2
            pool = np.clip(1.25 - d, 0, 1) ** 0.8
            shade = pal[0] * 0.5 + pal[1] * 0.5
            keep = 1 - 0.62 * pool
            pool *= 0.62
            for c in range(3):
                planes[c][bx0:bx1, by0:by1] *= keep
                planes[c][bx0:bx1, by0:by1] += shade[c] * pool
    yield
    rgb = np.empty((W, H, 3), np.uint8)
    for c in range(3):
        np.clip(planes[c], 0, 255, out=planes[c])
        rgb[..., c] = planes[c]
    del planes, tmp
    if tooth is None or tooth.shape != (W, H):
        tooth = yield from brush.make_tooth_steps(W, H, spec.get("seed", 0) + 5)
    yield
    # big visible strokes across the field: same paint, a shade off
    nb = int(6 + 14 * busy)
    for chunk in range(2):
        n = nb // 2
        x0 = rng.uniform(-0.1, 0.9, n) * W
        y0 = rng.uniform(0.0, horizon if kind == "room" else 1.0, n) * H
        base_a = rng.normal(0, 0.12, n) + (0 if kind != "wall" else math.pi / 2 * (rng.random(n) < 0.4))
        L = rng.uniform(0.25, 0.6, n) * W
        ctrl = brush.flow_paths(x0, y0, L, lambda x, y, a=base_a: a + 0.15 * np.sin(y * 0.02), steps=5,
                                rng=rng, wander=0.05)
        wid = rng.uniform(22, 48, n)
        colv = np.array([field * rng.uniform(0.84, 1.14) for _ in range(n)])
        colv += rng.normal(0, 9, (n, 3))
        # a few strokes carry the shadow colour, a few the light one
        alt = rng.random(n)
        colv[alt < 0.15] = colv[alt < 0.15] * 0.6 + pal[1] * 0.4
        colv[alt > 0.88] = colv[alt > 0.88] * 0.7 + pal[3] * 0.3
        brush.strokes(rgb, None, ctrl, wid, colv, "wipe", rng, tooth, opacity=0.8, dry_scale=1.1,
                      color2=np.array([pal[3]] * n), mix=0.06)
        yield
    if kind == "room":
        # the horizon: one long hard knife edge, slightly crooked
        y = hz + rng.uniform(-2, 2)
        ctrl = np.array([[[-10, y], [W * 0.35, y + rng.uniform(-3, 3)], [W * 0.7, y + rng.uniform(-3, 3)], [W + 10, y + rng.uniform(-2, 2)]]], np.float32)
        brush.strokes(rgb, None, ctrl, [4], [pal[1] * 0.6 + pal[2] * 0.2], "loaded", rng, tooth, opacity=0.7)
        if fine:
            yield
        # floor strokes, flatter and darker
        n = int(4 + 6 * busy)
        x0 = rng.uniform(-0.1, 0.8, n) * W
        y0 = rng.uniform(horizon + 0.03, 1.0, n) * H
        ctrl = brush.flow_paths(x0, y0, rng.uniform(0.3, 0.6, n) * W, lambda x, y: np.full_like(x, 0.02), steps=4, rng=rng, wander=0.03)
        colv = np.array([floor * rng.uniform(0.85, 1.12) for _ in range(n)])
        brush.strokes(rgb, None, ctrl, rng.uniform(18, 36, n), colv, "wipe", rng, tooth, opacity=0.6)
        yield
    if kind == "wall":
        # painted-over patches: knife planes of the palette's other colours
        n = int(5 + 7 * busy)
        for i in range(n):
            x = rng.uniform(0, W); y = rng.uniform(0, H)
            L = rng.uniform(40, 160); a = rng.choice([0.0, math.pi / 2]) + rng.normal(0, 0.05)
            ctrl = np.array([[[x, y], [x + math.cos(a) * L, y + math.sin(a) * L]]], np.float32)
            c = pal[rng.choice([3, 4, 4, 1, 2])] * rng.uniform(0.9, 1.05)
            brush.strokes(rgb, None, ctrl, [rng.uniform(20, 70)], [c], "knife", rng, tooth, opacity=rng.uniform(0.5, 0.9))
            if i % 3 == 2:
                if fine:
                    yield
        yield
    if sh:
        # the shadow is painted, not airbrushed: scrubbed dark strokes over the pool
        sx, sy, srx, sry = sh
        n = 8
        ang = rng.normal(0, 0.25, n)
        x0 = (sx + rng.uniform(-srx, srx * 0.4, n)) * W
        y0 = (sy + rng.uniform(-sry * 0.6, sry * 0.6, n)) * H
        ctrl = brush.flow_paths(x0, y0, rng.uniform(srx * 0.6, srx * 1.2, n) * W, lambda x, y, a=ang: a, steps=4, rng=rng)
        shade = pal[0] * 0.55 + pal[1] * 0.45
        brush.strokes(rgb, None, ctrl, rng.uniform(10, 22, n), np.array([shade] * n), "scumble", rng, tooth, opacity=0.7)
        yield
    panels = int(spec.get("panels", 1))
    if panels == 3:
        # triptych: three canvases with gaps; each panel its own shade of the ground
        gap = max(4, W // 90)
        pw = (W - 2 * gap) // 3
        gapc = (pal[0] * 0.5 + pal[1] * 0.5).astype(np.uint8)
        for i in range(3):
            x0 = i * (pw + gap)
            shade = np.array([1.0, 0.95, 1.05][i] * rng.uniform(0.96, 1.04), np.float32)
            seg = rgb[x0:x0 + pw].astype(np.float32) * shade
            rgb[x0:x0 + pw] = np.clip(seg, 0, 255).astype(np.uint8)
            if i < 2:
                rgb[x0 + pw:x0 + pw + gap] = gapc
    surf = pygame.Surface((W, H))
    pygame.surfarray.blit_array(surf, rgb)
    return surf


def panel_rects(W, H, panels):
    """Pixel rects of the panels of a ground (1 or 3)."""
    if panels != 3:
        return [pygame.Rect(0, 0, W, H)]
    gap = max(4, W // 90)
    pw = (W - 2 * gap) // 3
    return [pygame.Rect(i * (pw + gap), 0, pw, H) for i in range(3)]


# ------------------------------------------------------------------ props
def build_prop(kind, w, h, pal, seed=0):
    """build_prop_steps, all at once: returns the sprite."""
    gen = build_prop_steps(kind, w, h, pal, seed)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def build_prop_steps(kind, w, h, pal, seed=0):
    """Generator (yields between stages, returns the sprite).
    A painted prop as an SRCALPHA sprite of size (w, h):
      'dais'   a round low platform seen from above, lit rim
      'plinth' a box pedestal
      'bench'  a long low bed / bench with a mattress edge
      'rug'    a flat oval mat
      'rail'   a bent tubular rail (drawn per frame by the engine instead)
    """
    rng = np.random.default_rng(seed)
    w, h = max(8, int(w)), max(8, int(h))
    fine = w * h >= brush.FINE_PX
    rgb = np.zeros((w, h, 3), np.uint8)
    a = np.zeros((w, h), np.uint8)
    tooth = yield from brush.make_tooth_steps(w, h, seed + 1)
    if fine:
        yield
    p = [np.array(c, np.float32) for c in pal]
    X = (np.arange(w, dtype=np.float32)[:, None] + 0.5) / w
    Y = (np.arange(h, dtype=np.float32)[None, :] + 0.5) / h
    if kind in ("dais", "rug"):
        d = ((X - 0.5) / 0.5) ** 2 + ((Y - 0.5) / 0.5) ** 2
        inside = d < 1
        top = p[1] * 0.5 + p[2] * 0.25 + p[0] * 0.25 if kind == "dais" else p[3] * 0.4 + p[1] * 0.6
        col = np.broadcast_to(top, (w, h, 3)) * (0.9 + 0.2 * (1 - Y))[..., None]
        rgb[:] = np.clip(col, 0, 255).astype(np.uint8)
        a[inside] = 255
        # strokes round the platform, following its curve
        n = 10
        ang0 = rng.uniform(0, 2 * math.pi, n)
        ctrl = np.stack([brush.arc_path(w / 2, h / 2, rr * w / 2, a0, a0 + rng.uniform(0.8, 2.0), 8, squash=h / w)
                         for rr, a0 in zip(rng.uniform(0.3, 0.9, n), ang0)])
        cols = np.array([top * rng.uniform(0.85, 1.2) for _ in range(n)])
        brush.strokes(rgb, a, ctrl, rng.uniform(4, 9, n) * w / 200, cols, "wipe", rng, tooth, opacity=0.7)
        if kind == "dais":
            # the lit rim
            rim = np.stack([brush.arc_path(w / 2, h / 2, w / 2 - 2, math.pi * 0.05, math.pi * 0.95, 12, squash=(h - 4) / (w - 4))])
            brush.strokes(rgb, a, rim, [max(2, w / 70)], [p[4] * 0.8 + p[3] * 0.2], "loaded", rng, tooth)
            back = np.stack([brush.arc_path(w / 2, h / 2, w / 2 - 2, math.pi * 1.1, math.pi * 1.9, 10, squash=(h - 4) / (w - 4))])
            brush.strokes(rgb, a, back, [max(2, w / 90)], [p[3]], "nervous", rng, tooth)
        a[~inside] = 0
    elif kind == "plinth":
        # a box: top face lighter, front darker
        top_h = int(h * 0.22)
        rgb[:, :top_h] = np.clip(p[4] * 0.55 + p[2] * 0.3, 0, 255).astype(np.uint8)
        rgb[:, top_h:] = np.clip(p[1] * 0.7 + p[2] * 0.2, 0, 255).astype(np.uint8)
        a[:] = 255
        n = 6
        x0 = rng.uniform(0, w * 0.3, n); y0 = rng.uniform(top_h, h, n)
        ctrl = brush.flow_paths(x0, y0, rng.uniform(w * 0.5, w, n), lambda x, y: np.full_like(x, 0.0), steps=3, rng=rng)
        brush.strokes(rgb, a, ctrl, rng.uniform(6, 14, n) * w / 160, np.array([p[1] * rng.uniform(0.7, 1.2) for _ in range(n)]),
                      "knife", rng, tooth, opacity=0.6)
        edge = np.array([[[2, top_h], [w - 2, top_h]]], np.float32)
        brush.strokes(rgb, a, edge, [max(2, w / 80)], [p[4]], "loaded", rng, tooth)
    elif kind == "bench":
        # a low bed: mattress (light, soft) on a dark frame with legs
        mat_h = int(h * 0.45)
        rgb[:, :mat_h] = np.clip(p[4] * 0.7 + p[3] * 0.3, 0, 255).astype(np.uint8)
        a[:, :mat_h] = 255
        frame_y = mat_h
        rgb[:, frame_y:frame_y + int(h * 0.18)] = np.clip(p[0] * 0.6 + p[1] * 0.4, 0, 255).astype(np.uint8)
        a[:, frame_y:frame_y + int(h * 0.18)] = 255
        for lx in (int(w * 0.04), int(w * 0.93)):
            rgb[lx:lx + max(2, w // 60), frame_y:] = np.clip(p[0] * 0.8, 0, 255).astype(np.uint8)
            a[lx:lx + max(2, w // 60), frame_y:] = 255
        n = 7
        x0 = rng.uniform(0, w * 0.4, n); y0 = rng.uniform(2, mat_h - 2, n)
        ctrl = brush.flow_paths(x0, y0, rng.uniform(w * 0.4, w * 0.8, n), lambda x, y: np.full_like(x, 0.03), steps=4, rng=rng, wander=0.1)
        brush.strokes(rgb, a, ctrl, rng.uniform(4, 10, n) * w / 200, np.array([p[4] * rng.uniform(0.75, 1.0) for _ in range(n)]),
                      "scumble", rng, tooth, opacity=0.8, color2=np.array([p[3]] * n), mix=0.3)
        edge = np.array([[[0, mat_h], [w * 0.5, mat_h + 1], [w, mat_h]]], np.float32)
        brush.strokes(rgb, a, edge, [max(2, w / 90)], [p[0] * 0.5 + p[1] * 0.5], "loaded", rng, tooth)
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.surfarray.blit_array(surf, rgb)
    sa = pygame.surfarray.pixels_alpha(surf)
    sa[:] = a
    del sa
    return surf


def light_pool(r, color, strength=1.0):
    """A soft additive light: blit with BLEND_RGB_ADD."""
    r = max(4, int(r))
    X = np.arange(2 * r, dtype=np.float32)[:, None] - r + 0.5
    Y = np.arange(2 * r, dtype=np.float32)[None, :] - r + 0.5
    d = np.sqrt(X ** 2 + Y ** 2) / r
    k = np.clip(1 - d, 0, 1) ** 1.8 * strength
    arr = (np.array(color, np.float32)[None, None, :] * k[..., None]).clip(0, 255).astype(np.uint8)
    s = pygame.Surface((2 * r, 2 * r))
    pygame.surfarray.blit_array(s, arr)
    return s


def glaze(surf, hue_deg, sat=1.1):
    """glaze_steps, all at once."""
    gen = glaze_steps(surf, hue_deg, sat)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def glaze_steps(surf, hue_deg, sat=1.1):
    """The same ground in a shifted hue, blended over it at a drifting alpha
    so the colour breathes slowly without re-painting."""
    src = pygame.surfarray.pixels3d(surf)
    # cheap hue rotation in YIQ space
    th = math.radians(hue_deg)
    c, s = math.cos(th), math.sin(th)
    T = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]], np.float32)
    Ti = np.linalg.inv(T).astype(np.float32)
    R = np.array([[1, 0, 0], [0, c * sat, -s * sat], [0, s * sat, c * sat]], np.float32)
    M = (Ti @ R @ T) / np.float32(255.0)
    # channel by channel (a 3x3 matmul over [W, H, 3] floats is slow and churns memory)
    chans = [src[..., k].astype(np.float32) for k in range(3)]
    del src
    out = np.empty(surf.get_size() + (3,), np.uint8)
    acc = np.empty_like(chans[0])
    fine = acc.size >= brush.FINE_PX
    for o in range(3):
        if o and fine:
            yield
        np.multiply(chans[0], M[o, 0], out=acc)
        acc += chans[1] * M[o, 1]
        acc += chans[2] * M[o, 2]
        np.clip(acc, 0, 1, out=acc)
        acc *= 255
        out[..., o] = acc
    g = pygame.Surface(surf.get_size())
    pygame.surfarray.blit_array(g, out)
    return g
