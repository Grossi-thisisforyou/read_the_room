"""Bristle brush engine, numpy only.

A stroke is a path swept by a comb of bristles. Every bristle is a one-pixel
track with its own colour, its own amount of paint and its own place across the
brush, so a stroke shows streaks, dry breaks where the paint runs out on the
canvas tooth, and a lit ridge on one edge (impasto). A smear stroke carries no
paint of its own: it picks up what is under it and drags it along the path,
leaving a partial erasure behind.

Canvases are numpy views in pygame's [x, y] layout: rgb [W, H, 3] uint8 and an
optional alpha [W, H] uint8 (for the fading paint layers). Strokes are drawn in
batches: N strokes of one family share one call, so the numpy overhead is paid
once per batch, not once per stroke.

Families:
  wipe     broad drag, thin paint, long dry tail; with `src` it smears
  scumble  short dry scrubbing strokes, broken, wandering
  loaded   thick fresh paint, solid body, lit ridge, blob at the start
  knife    flat scraped plane, hard edges, skips across the tooth
  nervous  one or two thin trembling lines
"""
import math

import numpy as np

FAMILIES = {
    #          bristles per px, solid, load decay, dryness, colour var, impasto, wander, start blob
    "wipe":    dict(density=0.6, solid=False, decay=0.7, dry=0.85, var=0.07, imp=0.25, wander=0.04, blob=0.0, alpha=0.85),
    "scumble": dict(density=0.5, solid=False, decay=0.35, dry=1.05, var=0.14, imp=0.15, wander=0.35, blob=0.0, alpha=0.8),
    "loaded":  dict(density=1.25, solid=True, decay=0.25, dry=0.35, var=0.09, imp=1.0, wander=0.06, blob=0.3, alpha=1.0),
    "knife":   dict(density=1.2, solid=True, decay=0.5, dry=0.75, var=0.03, imp=0.9, wander=0.0, blob=0.0, alpha=1.0),
    "nervous": dict(density=0.0, solid=False, decay=0.2, dry=0.3, var=0.05, imp=0.0, wander=0.3, blob=0.0, alpha=0.9),
}

LIGHT = np.array([-0.55, -0.83], np.float32)  # paint is lit from the upper left


def make_tooth(w, h, seed=3):
    """Canvas tooth: an irregular grainy field in 0..1 (fine grain, a little
    stringy in random directions, plus slow patches). Dry paint catches on its
    high points."""
    gen = make_tooth_steps(w, h, seed)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


FINE_PX = 120000   # sizes from this many pixels up split their work into more steps


def make_tooth_steps(w, h, seed=3):
    """make_tooth as a generator that yields between its stages (for work
    spread over frames; only at sizes of FINE_PX and up); returns the tooth
    (StopIteration.value)."""
    fine = w * h >= FINE_PX
    rng = np.random.default_rng(seed)
    n = rng.random((w, h)).astype(np.float32)
    f = (n + np.roll(n, 1, 0) + np.roll(n, 1, 1) + np.roll(n, (1, 1), (0, 1))) * 0.25
    if fine:
        yield
    s1 = (n + np.roll(n, 1, 0) + np.roll(n, 2, 0) + np.roll(n, 3, 0)) * 0.25
    s2 = (n + np.roll(n, (1, 1), (0, 1)) + np.roll(n, (2, 2), (0, 1))) / 3
    if fine:
        yield
    pick = rng.random((w // 6 + 2, h // 6 + 2)) < 0.5
    pick = np.repeat(np.repeat(pick, 6, 0), 6, 1)[:w, :h]
    t = 0.5 * f + 0.5 * np.where(pick, s1, s2)
    del f, s1, s2
    coarse = rng.random((w // 10 + 2, h // 10 + 2)).astype(np.float32)
    coarse = np.repeat(np.repeat(coarse, 10, 0), 10, 1)[:w, :h]
    for ax in (0, 1):
        coarse = (coarse + np.roll(coarse, 5, ax)) * 0.5
    if fine:
        yield
    t = 0.75 * t + 0.25 * coarse
    t = (t + np.roll(t, 1, 0) + np.roll(t, 1, 1)) / 3
    t -= t.min()
    return (t / max(1e-6, t.max())).astype(np.float32)


_N1 = None


def _bristle_noise():
    """A long smooth 1-D noise: each bristle reads it from its own offset, so
    paint runs out in elongated breaks along the stroke, not in dots."""
    global _N1
    if _N1 is None:
        rng = np.random.default_rng(17)
        n = rng.random(8192).astype(np.float32)
        for k in (3, 5, 9):
            n = (np.roll(n, k) + n + np.roll(n, -k)) / 3
        n -= n.min()
        _N1 = n / n.max()
    return _N1


def flow_paths(x0, y0, length, angle_at, steps=7, rng=None, wander=0.0, bend=0.0):
    """Integrate N paths through an orientation field.

    x0, y0, length: arrays (N,). angle_at(x, y) -> angles (N,) in radians; the
    field may be an orientation (mod pi): each step keeps the heading closest
    to the previous one so strokes do not fold back. Returns (N, steps+1, 2)."""
    n = len(x0)
    pts = np.empty((n, steps + 1, 2), np.float32)
    pts[:, 0, 0] = x0
    pts[:, 0, 1] = y0
    seg = (np.asarray(length, np.float32) / steps)
    head = None
    x = np.asarray(x0, np.float32).copy()
    y = np.asarray(y0, np.float32).copy()
    curl = bend * (rng.random(n).astype(np.float32) - 0.5) * 2 if rng is not None else 0.0
    for k in range(steps):
        a = np.asarray(angle_at(x, y), np.float32)
        if wander and rng is not None:
            a = a + (rng.random(n).astype(np.float32) - 0.5) * 2 * wander
        a = a + curl * k / steps
        dx, dy = np.cos(a), np.sin(a)
        if head is not None:
            flip = dx * head[0] + dy * head[1] < 0
            dx = np.where(flip, -dx, dx)
            dy = np.where(flip, -dy, dy)
        head = (dx, dy)
        x = x + dx * seg
        y = y + dy * seg
        pts[:, k + 1, 0] = x
        pts[:, k + 1, 1] = y
    return pts


def arc_path(cx, cy, r, a0, a1, steps=10, squash=1.0, spiral=0.0):
    """One arc as control points (steps+1, 2): the sweep of an arm across a face."""
    t = np.linspace(0, 1, steps + 1, dtype=np.float32)
    a = a0 + (a1 - a0) * t
    rr = r * (1 + spiral * t)
    return np.stack([cx + np.cos(a) * rr, cy + np.sin(a) * rr * squash], 1)


def _resample(ctrl, P):
    """(N, K, 2) control points -> (N, P, 2) samples spaced evenly in parameter,
    plus unit tangents (N, P, 2)."""
    n, K, _ = ctrl.shape
    s = np.linspace(0, K - 1, P, dtype=np.float32)
    i0 = np.minimum(s.astype(np.int32), K - 2)
    f = (s - i0)[None, :, None]
    # Catmull-Rom would be smoother; a light pre-smoothing of the control
    # points plus linear interpolation is close enough at these sizes
    if K > 3:
        c = ctrl.copy()
        c[:, 1:-1] = ctrl[:, 1:-1] * 0.5 + (ctrl[:, :-2] + ctrl[:, 2:]) * 0.25
    else:
        c = ctrl
    p = c[:, i0] * (1 - f) + c[:, i0 + 1] * f
    tg = np.empty_like(p)
    tg[:, 1:-1] = p[:, 2:] - p[:, :-2]
    tg[:, 0] = p[:, 1] - p[:, 0]
    tg[:, -1] = p[:, -1] - p[:, -2]
    ln = np.sqrt((tg ** 2).sum(-1, keepdims=True)) + 1e-6
    return p, tg / ln


def strokes(rgb, alpha, ctrl, width, color, family="loaded", rng=None, tooth=None,
            src=None, color2=None, mix=0.0, opacity=1.0, drag=12, charge=0.25,
            dry_scale=1.0, P=None, light=LIGHT):
    """Draw a batch of strokes of one family. Returns the number of pixels touched.

    rgb    [W, H, 3] uint8 view to paint into (modified in place)
    alpha  [W, H] uint8 view of the layer's alpha, or None for an opaque canvas
    ctrl   (N, K, 2) control points
    width  (N,) brush widths in pixels
    color  (N, 3) paint colours 0..255
    src    optional [W, H, 3] picture to pick up and drag (a smear). Each bristle
           carries what it touched over the last `drag` pixels plus a memory of
           where it started; `charge` is how much fresh paint it still adds.
    color2 optional (N, 3) second colour on the brush ("dirty brush"); `mix` is
           the share of bristles loaded with it
    """
    rng = rng or np.random.default_rng()
    fam = FAMILIES[family]
    ctrl = np.asarray(ctrl, np.float32)
    n = ctrl.shape[0]
    if n == 0:
        return 0
    W, H = rgb.shape[0], rgb.shape[1]
    width = np.broadcast_to(np.asarray(width, np.float32), (n,))
    color = np.broadcast_to(np.asarray(color, np.float32), (n, 3))
    if P is None:
        seglen = np.sqrt((np.diff(ctrl, axis=1) ** 2).sum(-1)).sum(1)
        P = int(min(1400, max(8, seglen.max() * 1.05)))
    pts, tg = _resample(ctrl, P)
    nx, ny = -tg[..., 1], tg[..., 0]  # normals (N, P)
    B = 2 if family == "nervous" else int(max(3, min(36, width.max() * fam["density"])))
    off = (np.arange(B, dtype=np.float32) + 0.5) / B - 0.5
    off = off[None, :] + (rng.random((n, B), dtype=np.float32) - 0.5) * (1.0 / B)  # (N, B)
    s = np.linspace(0, 1, P, dtype=np.float32)
    # width profile along the stroke
    if family == "loaded":
        prof = 0.75 + 0.25 * np.minimum(1, s * 6) + fam["blob"] * np.exp(-((s - 0.06) / 0.07) ** 2) \
            - 0.3 * np.maximum(0, s - 0.7) / 0.3
    elif family == "wipe":
        prof = 0.8 + 0.2 * np.sin(np.minimum(1, s * 1.15) * math.pi)
    elif family == "scumble":
        prof = 0.55 + 0.45 * np.sin(s * math.pi)
    elif family == "nervous":
        prof = 0.5 + 0.5 * np.sqrt(np.abs(np.sin(s * math.pi)))
    else:  # knife: a flat blade, square ends
        prof = np.ones(P, np.float32)
    lat = off[:, None, :] * (width[:, None] * prof[None, :])[..., None]  # (N, P, B)
    if family == "nervous":
        trem = np.sin(s[None, :] * (30 + 40 * rng.random((n, 1))) + rng.random((n, 1)) * 6.3) * 0.45
        lat += trem.astype(np.float32)[..., None]
    B2 = B
    # a little per-sample wobble breaks the moire of evenly spaced bristles
    # (the big (N, P, B) arrays are worked in place: no per-step temporaries)
    wob = rng.random(lat.shape, dtype=np.float32)
    wob -= 0.5
    wob *= 0.9
    lat += wob
    X = np.multiply(nx[..., None], lat, out=wob)
    X += pts[..., 0][..., None]
    Y = np.multiply(ny[..., None], lat, out=lat)
    Y += pts[..., 1][..., None]
    # ---- alpha per sample (N, P, B2) ----
    bl = 0.7 + 0.6 * rng.random((n, 1, B2), dtype=np.float32)  # bristle load
    if family == "knife":
        # even paint, then scrape marks: bands across the blade where it skipped
        ph = rng.random((n, 1, 1), dtype=np.float32) * 6.3
        slen = np.sqrt((np.diff(ctrl, axis=1) ** 2).sum(-1)).sum(1)[:, None, None]
        bands = np.maximum(1.0, slen / 30.0) * (0.8 + 0.4 * bl.mean(-1, keepdims=True))
        skip = np.sin(s[None, :, None] * bands * 6.3 + ph) * 0.5 + 0.5
        load = 0.75 + 0.25 * bl - 0.5 * skip * (s[None, :, None] > 0.35) * fam["dry"] * dry_scale
        load = np.broadcast_to(load, (n, P, B2))
    else:
        load = np.exp(-s * (fam["decay"] * 3.0))[None, :, None] * bl
    ix = X.astype(np.int32)
    iy = Y.astype(np.int32)
    # outside the canvas: negative ints are huge as unsigned, so one test per axis
    out = ix.view(np.uint32) >= W
    out |= iy.view(np.uint32) >= H
    np.clip(ix, 0, W - 1, out=ix)
    np.clip(iy, 0, H - 1, out=iy)
    flat_idx = ix
    flat_idx *= H                 # ix is not needed on its own any more
    flat_idx += iy
    if tooth is not None and family != "knife":
        n1 = _bristle_noise()
        bo = rng.integers(0, 8000, (n, 1, B2))
        step = (np.arange(P, dtype=np.float32) * (0.25 + 0.2 * rng.random())).astype(np.int32)[None, :, None]
        si = bo + step
        si %= 8192
        a = np.take(n1, si).astype(np.float32, copy=False)
        a *= 0.7
        th = np.take(tooth.ravel() if tooth.flags.c_contiguous else np.ascontiguousarray(tooth).ravel(), flat_idx)
        th *= 0.3
        a += th                    # a = th = tooth * 0.3 + streak * 0.7
        dl = 1 - load
        dl *= fam["dry"] * dry_scale
        a -= dl
        a -= 0.05
        a *= 4.0
        a += load * 0.5
        np.clip(a, 0, 1, out=a)
    else:
        a = np.clip(load * 1.2, 0, 1)
    ends = np.minimum(1, s * 12) * np.minimum(1, (1 - s) * 9)
    if family == "knife":
        ends = np.minimum(1, (1 - s) * 30)
    a *= ((0.3 + 0.7 * ends) * (fam["alpha"] * opacity))[None, :, None]
    a[out] = 0
    # ---- colour per bristle (N, B2, 3) ----
    var = fam["var"]
    bc = color[:, None, :] * (1 + rng.normal(0, var, (n, B2, 1))).astype(np.float32) \
        + rng.normal(0, var * 40, (n, B2, 3)).astype(np.float32)
    if color2 is not None and mix > 0:
        c2 = np.broadcast_to(np.asarray(color2, np.float32), (n, 3))
        sel = (rng.random((n, B2)) < mix)[..., None]
        bc = np.where(sel, c2[:, None, :] * (1 + rng.normal(0, var, (n, B2, 1))).astype(np.float32), bc)
    # ---- keep only the samples that leave paint ----
    flat = np.flatnonzero(a.ravel() > 0.04)
    if flat.size == 0:
        return 0
    fi = flat_idx.ravel()[flat]
    ixs = fi // H
    iys = fi - ixs * H
    af = a.ravel()[flat]
    ni = flat // (P * B2)
    pi = (flat // B2) % P
    bi = flat % B2
    if src is not None:
        # smear: running window of what the bristle touched, plus where it started
        # (the window sums need every sample; the rest only the painted ones)
        ixa = flat_idx // H
        under = src[ixa, flat_idx - ixa * H].astype(np.float32)  # (N, P, B2, 3)
        del ixa
        L = int(max(2, min(drag, P - 1)))
        win = np.cumsum(under, axis=1)
        win[:, L:] -= win[:, :-L].copy()
        cnt = np.minimum(np.arange(1, P + 1, dtype=np.float32), L)
        keep = np.exp(-s * 2.2).astype(np.float32) * 0.6
        kp = keep[pi][:, None]
        col = win[ni, pi, bi] / cnt[pi][:, None]
        col = col * (1 - kp) + under[ni, 0, bi] * kp
        if charge > 0:
            col = col * (1 - charge) + bc[ni, bi] * charge
    else:
        col = bc[ni, bi]
    # impasto: lit edge highlight, far edge shadow
    imp = fam["imp"]
    if imp > 0:
        side = np.sign(nx[ni, pi] * light[0] + ny[ni, pi] * light[1])
        edge = off[ni, bi] * 2 * side
        hi = np.clip((edge - 0.55) * 2.2, 0, 1) * imp
        lo = np.clip((-edge - 0.6) * 2.5, 0, 1) * imp
        col = col * (1 + 0.45 * hi - 0.35 * lo)[:, None] + (hi * 45)[:, None]
    np.clip(col, 0, 255, out=col)
    af = af[:, None]
    old = rgb[ixs, iys].astype(np.float32)
    if alpha is not None:
        old_a = alpha[ixs, iys].astype(np.float32) * (1 / 255)
        wmix = af + (1 - af) * (1 - old_a[:, None])  # an empty pixel takes the paint fully
        rgb[ixs, iys] = (old + (col - old) * wmix).astype(np.uint8)
        alpha[ixs, iys] = ((old_a + (1 - old_a) * af[:, 0]) * 255).astype(np.uint8)
    else:
        rgb[ixs, iys] = (old + (col - old) * af).astype(np.uint8)
    return int(flat.size)
