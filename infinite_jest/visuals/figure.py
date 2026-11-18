"""The visitor's figure: camera frame in, smeared painted body out.

All arrays here are in pygame's [x, y] layout (width first) so they can be
blitted without transposing. Works on grayscale (the N900 sends gray8, 160x120,
at most 4 fps) or RGB.

What happens to a camera frame (push, at most 4 times a second):
  1. crop to the figure's aspect, bilinear resize to the figure buffer
  2. exposure compensation (the N900 adjusts its own exposure all the time)
  3. background model: running mean and variance per pixel; a pixel is
     "visitor" when it differs from the background by more than its own noise
  4. shadow suppression: darker-but-same-texture pixels are the visitor's
     shadow on the wall, not the visitor
  5. morphology at half size: close the holes, open away the specks
  6. temporal smoothing, and between frames the mask glides from the last
     frame to the new one so the 4 fps camera does not stutter
  7. if the phone itself moves (handheld) or nobody is separable, the figure
     falls back to a portrait: a head-and-shoulders shape that follows the
     most textured part of the frame
Nothing is kept beyond the last two frames and a background estimate, and
wipe() drops everything.
"""
import math

import numpy as np


# ---------------------------------------------------------------- helpers
def _to_gray(img):
    img = np.asarray(img)
    if img.ndim == 3:
        return img[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    return img.astype(np.float32)


def _resize(img, w, h):
    """img [y, x] (camera layout) -> [x, y] float32 (w, h), centre-cropped to the
    target aspect, bilinear."""
    g = _to_gray(img)
    ih, iw = g.shape
    target = w / h
    if iw / ih > target:
        cw = max(2, int(ih * target))
        x0 = (iw - cw) // 2
        g = g[:, x0:x0 + cw]
    else:
        ch = max(2, int(iw / target))
        y0 = (ih - ch) // 2
        g = g[y0:y0 + ch, :]
    ih, iw = g.shape
    if iw >= 2 * w and ih >= 2 * h:  # much bigger: average blocks first
        fx, fy = iw // w, ih // h
        g = g[:h * fy, :w * fx].reshape(h, fy, w, fx).mean((1, 3))
        ih, iw = g.shape
    ys = (np.arange(h, dtype=np.float32) + 0.5) * ih / h - 0.5
    xs = (np.arange(w, dtype=np.float32) + 0.5) * iw / w - 0.5
    ys = np.clip(ys, 0, ih - 1.001)
    xs = np.clip(xs, 0, iw - 1.001)
    y0 = ys.astype(np.int32); x0 = xs.astype(np.int32)
    fy = (ys - y0)[:, None]; fx = (xs - x0)[None, :]
    a = g[y0][:, x0]; b = g[y0][:, x0 + 1]; c = g[y0 + 1][:, x0]; d = g[y0 + 1][:, x0 + 1]
    out = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
    return np.ascontiguousarray(out.T)


def _blur(a, passes=2):
    """Cheap separable 3-tap box blur, repeated."""
    for _ in range(passes):
        b = a.copy()
        b[1:] += a[:-1]; b[:-1] += a[1:]
        b[0] += a[0]; b[-1] += a[-1]
        a = b * (1 / 3)
        b = a.copy()
        b[:, 1:] += a[:, :-1]; b[:, :-1] += a[:, 1:]
        b[:, 0] += a[:, 0]; b[:, -1] += a[:, -1]
        a = b * (1 / 3)
    return a


def _dilate(m):
    o = m.copy()
    o[1:] = np.maximum(o[1:], m[:-1]); o[:-1] = np.maximum(o[:-1], m[1:])
    p = o.copy()
    p[:, 1:] = np.maximum(p[:, 1:], o[:, :-1]); p[:, :-1] = np.maximum(p[:, :-1], o[:, 1:])
    return p


def _erode(m):
    o = m.copy()
    o[1:] = np.minimum(o[1:], m[:-1]); o[:-1] = np.minimum(o[:-1], m[1:])
    p = o.copy()
    p[:, 1:] = np.minimum(p[:, 1:], o[:, :-1]); p[:, :-1] = np.minimum(p[:, :-1], o[:, 1:])
    return p


def _down2(a):
    w, h = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    return a[:w, :h].reshape(w // 2, 2, h // 2, 2).mean((1, 3))


def _up2(a, w, h):
    """Half size -> (w, h), bilinear-ish."""
    ax = np.empty_like(a); ax[:-1] = a[1:]; ax[-1] = a[-1]
    ay = np.empty_like(a); ay[:, :-1] = a[:, 1:]; ay[:, -1] = a[:, -1]
    axy = np.empty_like(a); axy[:, :-1] = ax[:, 1:]; axy[:, -1] = ax[:, -1]
    W2, H2 = a.shape
    out = np.empty((W2 * 2, H2 * 2), np.float32)
    out[0::2, 0::2] = a
    out[1::2, 0::2] = (a + ax) * 0.5
    out[0::2, 1::2] = (a + ay) * 0.5
    out[1::2, 1::2] = (a + ax + ay + axy) * 0.25
    if out.shape == (w, h):
        return out
    o = np.zeros((w, h), np.float32)
    o[:min(w, out.shape[0]), :min(h, out.shape[1])] = out[:w, :h]
    return o


def _smooth_noise(w, h, cell, seed):
    rng = np.random.default_rng(seed)
    n = rng.random((w // cell + 3, h // cell + 3)).astype(np.float32)
    n = np.repeat(np.repeat(n, cell, 0), cell, 1)[:w + cell, :h + cell]
    n = _blur(n, max(2, cell // 2))
    n -= n.min()
    return n / max(1e-6, n.max())


# ---------------------------------------------------------------- stand-in body
def ghost_body(w, h, t, seed=0, present=1.0, close=False, cam_shake=0.0):
    """A procedural stand-in visitor as a gray camera would see them: a
    modelled head (sockets, brow, nose, cheekbones, mouth, hair), neck,
    shoulders, arms and a clothed torso, swaying, nodding and turning. Used when
    no camera is connected and by the demo as a fake N900 frame. close=True
    frames it like a handheld phone: the head big, the room moving behind.
    seed changes the person (hair, clothes, build). Returns [y, x] uint8."""
    rng = np.random.default_rng((int(seed) * 7919 + int(t * 4)) & 0xffffffff)
    who = np.random.default_rng(int(seed) + 101)
    hair_tone = who.choice([30.0, 45.0, 150.0, 0.0])      # 0 = shaved
    hair_len = who.uniform(0.0, 0.8)
    cloth = who.choice([45.0, 70.0, 120.0, 175.0])
    build = who.uniform(0.9, 1.15)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    pan = (math.sin(t * 0.7 + seed) * 0.12 + math.sin(t * 2.3) * 0.03) * w * cam_shake
    tiltc = math.sin(t * 0.5 + seed) * 0.08 * cam_shake
    wx = xx + pan + (yy - h / 2) * tiltc
    wall = 125 + 14 * np.sin(wx / w * 2.4 + seed) + 24 * (np.mod(wx, w * 0.9) > w * 0.62)
    wall = wall - 28 * (yy / h) ** 2 + 10 * np.exp(-((wx - w * 0.2) / (w * 0.3)) ** 2)
    if present <= 0:
        return np.clip(wall + rng.normal(0, 4, (h, w)), 0, 255).astype(np.uint8)
    S = 2.9 if close else 1.0
    sway = math.sin(t * 0.6 + seed) * w * 0.04 + math.sin(t * 0.21 + seed * 2) * w * 0.05
    cx = w * 0.5 + sway * (0.6 if close else 1.0) + (1 - present) * w * 0.8 + pan * 0.15
    hh = h * 0.125 * S                       # head half height
    hw = hh * 0.74                           # head half width
    hy = (h * 0.44) if close else (h * 0.29)
    hy += math.sin(t * 1.3) * h * 0.01
    yaw = math.sin(t * 0.33 + seed) * 0.5
    nod = math.sin(t * 0.5 + seed * 3) * 0.1
    roll = math.sin(t * 0.4 + seed) * 0.12
    dx = xx - cx; dy = yy - hy
    u = (dx * math.cos(roll) + dy * math.sin(roll)) / hw
    v = (-dx * math.sin(roll) + dy * math.cos(roll)) / hh
    r2 = u * u + v * v
    head = r2 < 1
    nz = np.sqrt(np.clip(1 - r2, 0, 1))
    fu = u - yaw * 0.55 * nz                 # features ride the turning sphere
    fv = v + nod * nz

    def bump(cu, cv, su, sv):
        return np.exp(-(((fu - cu) / su) ** 2 + ((fv - cv) / sv) ** 2))
    # sphere shading, light from the upper left front
    L = (-0.45, -0.55, 0.70)
    lam = np.clip(u * L[0] + v * L[1] + nz * L[2], 0, 1)
    skin = 70 + 150 * lam
    skin -= 70 * (bump(-0.36, -0.12, 0.2, 0.12) + bump(0.36, -0.12, 0.2, 0.12))    # sockets
    skin -= 60 * (bump(-0.36, -0.12, 0.07, 0.05) + bump(0.36, -0.12, 0.07, 0.05))  # eyes
    skin -= 45 * (bump(-0.36, -0.33, 0.22, 0.04) + bump(0.36, -0.33, 0.22, 0.04))  # brows
    skin += 40 * bump(-0.05, 0.05, 0.07, 0.25) - 45 * bump(0.08, 0.12, 0.06, 0.2)  # nose lit/shadow side
    skin -= 50 * bump(0, 0.3, 0.12, 0.04)                                          # nostrils
    skin += 25 * (bump(-0.5, 0.12, 0.18, 0.15) + bump(0.5, 0.12, 0.18, 0.15)) * lam  # cheekbones
    mouth = 0.5 + 0.5 * math.sin(t * 0.9 + seed)
    skin -= 55 * bump(0, 0.5, 0.26, 0.03 + 0.05 * mouth)                           # mouth
    skin -= 30 * bump(0, 0.68, 0.3, 0.05)                                          # under the lip
    skin -= 50 * np.clip((r2 - 0.75) * 4, 0, 1)                                    # turning edge
    if hair_tone > 0:
        top = fv < -0.5 + 0.3 * fu * fu
        sides = (np.abs(u) > 0.82 - 0.4 * hair_len * np.clip(fv + 0.3, 0, 1)) & (fv < -0.1 + hair_len)
        hair = head & (top | sides)
        skin = np.where(hair, hair_tone + 25 * lam + 10 * np.sin(u * 14 + v * 4), skin)
        # hair falling below the jaw
        longhair = (np.abs(dx) < hw * 1.05) & (np.abs(dx) > hw * 0.55) & (dy > 0) & (dy < hh * (0.5 + 1.6 * hair_len))
    else:
        longhair = np.zeros_like(head)
    # neck, shoulders, torso, arms
    sh_y = hy + hh * 1.5
    nk = (np.abs(dx + yaw * hw * 0.15) < hw * 0.5) & (dy > hh * 0.5) & (yy < sh_y + hh * 0.4)
    shw = hw * 2.9 * build
    shoulders = ((dx / shw) ** 2 + ((yy - sh_y - hh * 0.75) / (hh * 0.85)) ** 2 < 1) & (yy > sh_y - hh * 0.2)
    torso = (np.abs(dx) < shw * (0.84 - 0.05 * np.clip((yy - sh_y) / h, 0, 1))) & (yy > sh_y + hh * 0.6)
    arm_c = shw * 0.9 + math.sin(t * 0.8 + seed) * w * 0.012
    armd = np.abs(np.abs(dx) - arm_c)
    arms = (armd < hw * 0.55) & (yy > sh_y + hh * 0.4)
    body = shoulders | torso | arms
    xr = np.clip(dx / shw, -1.2, 1.2)
    fold = 14 * np.sin(dx / hw * 2.2 + np.sin(yy / hh * 1.3) * 1.5) * np.clip((yy - sh_y) / hh, 0, 1)
    cl = cloth * (1.05 - 0.45 * (xr + 0.3) ** 2 * 0.6 - 0.25 * np.clip(xr, 0, 1)) + fold
    cl = np.where(arms & ~torso, cl * 0.8 - 12 * np.clip(armd / (hw * 0.55), 0, 1), cl)
    cl = np.where(arms & torso & (armd < hw * 0.08), cl * 0.6, cl)  # the crease where arm meets body
    neckc = 60 + 90 * np.clip(0.4 - 0.5 * dx / hw, 0, 1) - 40 * np.clip((dy - hh * 0.8) / hh, 0, 1)
    img = np.where(head, skin, np.where(longhair, hair_tone + 10, np.where(nk, neckc, np.where(body, cl, wall))))
    img = img * (0.93 + 0.07 * math.sin(t * 0.37))  # auto-exposure breathing
    img = img + rng.normal(0, 5, (h, w))           # sensor noise
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- the figure
class Figure:
    """Background model, mask cleanup, smear and flesh colouring at low resolution."""

    def __init__(self, w=160, h=180):
        self.w, self.h = w, h
        X, Y = np.mgrid[0:w, 0:h].astype(np.float32)
        self.X, self.Y = X, Y
        # slow noise fields: colour zones of the flesh and where the smear drags
        self.zones = _smooth_noise(w * 2, h * 2, 14, 21)
        self.dragz2 = _smooth_noise(w, h, 10, 22)
        self.X2, self.Y2 = np.mgrid[0:w // 2, 0:h // 2].astype(np.float32)
        # the body fades out before the edge of the camera frame (no hard cut)
        bx = np.clip(np.minimum(X, w - 1 - X) / 8.0, 0, 1)
        by = np.clip(np.minimum(Y / 8.0, (h - 1 - Y) / 26.0), 0, 1)
        self.border = (bx * by).astype(np.float32)
        self.centre2 = np.exp(-(((self.X2 - w / 4) / (w * 0.175)) ** 2 + ((self.Y2 - h * 0.21) / (h * 0.2)) ** 2))
        rng = np.random.default_rng(7)
        n = rng.random((w // 3 + 2, h // 10 + 2)).astype(np.float32)
        n = np.repeat(np.repeat(n, 3, 0), 10, 1)[:w, :h]
        self.brush = 0.93 + 0.14 * _blur(n, 1)
        d = rng.random((w // 2 + 2, h // 6 + 2)).astype(np.float32)
        d = np.repeat(np.repeat(d, 2, 0), 6, 1)[:w, :h]
        d = np.roll(d, 3, 1) * 0.5 + d * 0.5
        self.dither = (_blur(d, 1) - 0.5) * 1.2 + 0.5
        self.wipe()

    # ---- state ----
    def wipe(self):
        self.bg = None
        self.var = None
        self.gray = None
        self.prev_gray = None
        self.prev_mask = np.zeros((self.w, self.h), np.float32)
        self.mask2 = np.zeros((self.w // 2, self.h // 2), np.float32)
        self.g2 = None
        self.mask = np.zeros((self.w, self.h), np.float32)
        self.trail_rgb = None
        self.trail_a = np.zeros((self.w, self.h), np.float32)
        self.frames_seen = 0
        self.face = (self.w / 2, self.h * 0.3)
        self.face_size = self.h * 0.3
        self.portrait = False
        self.cam_moving = 0.0
        self.motion = 0.0
        self.centroid = (self.w / 2, self.h / 2)
        self.velocity = (0.0, 0.0)
        self.push_age = 0.0         # seconds since the last frame, advanced by render
        self.static_s = 0.0         # how long the camera image has not changed at all
        self.edge = np.zeros((self.w // 2, self.h // 2), np.float32)
        self.orient = np.zeros((self.w // 2, self.h // 2), np.float32)
        self.gain = 1.0
        self.last_rgb = None
        self.last_a = None
        self._pfx = (self.w / 4, self.h * 0.21)
        self.tm = np.zeros((self.w * self.h, 2), np.float32)
        self.prev_tm = self.tm
        self.present = True        # the engine says a visitor should be there

    @property
    def ready(self):
        return self.gray is not None

    @property
    def stale(self):
        """True when frames stopped coming or the image is frozen."""
        return self.gray is None or self.push_age > 2.5 or self.static_s > 4.0

    def push(self, frame, dt_hint=0.25):
        """Feed a camera frame ([y, x] gray or [y, x, 3] RGB uint8). The room
        model runs at half the figure size; only the tone keeps full size."""
        w, h = self.w, self.h
        g = _resize(frame, w, h)
        g2 = _down2(g)
        if self.gray is not None and float(np.abs(g2[::2, ::2] - self.g2[::2, ::2]).mean()) < 0.15:
            self.static_s += max(self.push_age, dt_hint)
        else:
            self.static_s = 0.0
        if self.bg is None:
            self.bg = g2.copy()
            self.var = np.full_like(g2, 64.0)
        m2prev = self.mask2
        # exposure: compare the frame with the background where it is background
        bgsel = m2prev < 0.2
        if bgsel.sum() > 100:
            gain = float(g2[bgsel].mean() / max(1.0, float(self.bg[bgsel].mean())))
            self.gain = self.gain * 0.5 + min(1.6, max(0.6, gain)) * 0.5
        gc = g2 * (1.0 / self.gain)
        d = gc - self.bg
        z = np.abs(d) / np.sqrt(self.var + 30.0)
        fg = np.clip((z - 2.0) * 0.6, 0, 1)
        # shadows: a little darker by a steady ratio, with the wall's own texture
        ratio = (gc + 1) / (self.bg + 1)
        gxg = np.abs(np.roll(gc, 1, 0) - gc) + np.abs(np.roll(gc, 1, 1) - gc)
        gxb = np.abs(np.roll(self.bg, 1, 0) - self.bg) + np.abs(np.roll(self.bg, 1, 1) - self.bg)
        shadow = (ratio > 0.6) & (ratio < 0.9) & (np.abs(gxg - gxb) < 4 + 0.25 * gxb) & (gxb > 2.5)
        fg[shadow] *= 0.4
        # the phone itself moved: almost everything changed at once
        changed = float((z > 2.5).mean())
        self.cam_moving = self.cam_moving * 0.6 + (1.0 if changed > 0.55 else 0.0) * 0.4
        # morphology: open away specks, close holes
        m2 = _dilate(_erode(fg))
        m2 = _erode(_dilate(_dilate(m2)))
        # a standing body reaches the bottom of the frame: fill each column
        # below the top of the body where the body also touches the bottom
        solid = (m2 > 0.5).astype(np.float32)
        curtain = np.maximum.accumulate(solid, axis=1)
        foot = solid[:, -max(2, solid.shape[1] // 4):].mean(1)
        foot = np.clip(_blur(foot[:, None], 2)[:, 0] * 3, 0, 1)
        m2 = np.maximum(m2, curtain * foot[:, None] * 0.9)
        m2 = np.clip((_blur(m2, 1) - 0.25) * 2.4, 0, 1)
        cover = float(m2.mean())
        # background learning: quick while the room is empty, otherwise slow
        # and frozen under (a dilated) body so a still visitor is not absorbed
        base = 0.02 if self.present else 0.12
        rate = np.where(_dilate(m2) > 0.15, 0.0005, base).astype(np.float32)
        if self.cam_moving > 0.5:
            rate[:] = 0.5  # the view is moving: re-learn the room quickly
        self.bg += (gc - self.bg) * rate
        self.var += (d * d - self.var) * rate
        np.clip(self.var, 16, 2500, out=self.var)
        portrait = self.cam_moving > 0.4 or cover < 0.03 or cover > 0.85
        if portrait:
            m2 = self._portrait_mask(g2)
        elif self.frames_seen > 2:
            # complete the body from the head we found last time
            m2 = np.maximum(m2, self._silhouette(self.face[0] / 2, self.face[1] / 2, self.face_size / 2) * 0.85)
        self.portrait = portrait
        # temporal smoothing
        m2 = m2prev * 0.35 + m2 * 0.65 if self.frames_seen else m2
        self.mask2 = m2.astype(np.float32)
        self.prev_mask = self.mask
        self.mask = np.clip(_up2(self.mask2, w, h), 0, 1)
        prev2 = self.g2 if self.gray is not None else g2
        self.gray = g
        self.g2 = g2
        self.frames_seen += 1
        self.push_age = 0.0
        # tone stretch inside the body, stored with the mask for render()
        inside = self.mask2 > 0.3
        if inside.sum() > 10:
            lo, hi = np.percentile(g2[inside], (3, 97))
        else:
            lo, hi = 40.0, 200.0
        tone = (g - lo) * (1.0 / max(10.0, hi - lo))
        self.prev_tm = self.tm
        self.tm = np.stack([tone.ravel(), self.mask.ravel()], 1).astype(np.float32)
        if self.frames_seen == 1:
            self.prev_tm = self.tm
        self._update_trail()
        # motion energy inside the body, centroid and its velocity
        diff = np.abs(g2 - prev2)
        msum = float(self.mask2.sum())
        self.motion = self.motion * 0.5 + min(1.0, float((diff * self.mask2).sum() / max(1.0, msum)) / 25.0) * 0.5
        if msum > 5:
            cx = float((self.mask2 * self.X2).sum() / msum) * 2
            cy = float((self.mask2 * self.Y2).sum() / msum) * 2
            vx, vy = cx - self.centroid[0], cy - self.centroid[1]
            self.velocity = (self.velocity[0] * 0.5 + vx * 0.5, self.velocity[1] * 0.5 + vy * 0.5)
            self.centroid = (cx, cy)
        self._find_face()
        # orientation field for strokes (half size): along the contours of the form
        gs = g2 * (0.3 + 0.7 * self.mask2)
        ms = self.mask2
        gx = np.roll(gs, -1, 0) - np.roll(gs, 1, 0) + (np.roll(ms, -1, 0) - np.roll(ms, 1, 0)) * 120
        gy = np.roll(gs, -1, 1) - np.roll(gs, 1, 1) + (np.roll(ms, -1, 1) - np.roll(ms, 1, 1)) * 120
        mag = np.sqrt(gx * gx + gy * gy)
        self.orient = (np.arctan2(gy, gx) + math.pi / 2).astype(np.float32)  # along the edge, [w/2, h/2]
        self.edge = (np.clip(mag / 60.0, 0, 1) * np.clip(ms * 2, 0, 1)).astype(np.float32)

    def _silhouette(self, fx, fy, size):
        """A soft head-neck-shoulders-torso shape for a head at (fx, fy) of
        height `size`: fills the holes background subtraction leaves where
        clothes or skin match the wall."""
        X, Y = self.X2, self.Y2
        hr = size * 0.5
        head = 1.25 - (((X - fx) / (hr * 0.78)) ** 2 + ((Y - fy) / hr) ** 2)
        neck = 1.0 - np.maximum(np.abs(X - fx) / (hr * 0.45), np.abs(Y - fy - hr * 1.2) / (hr * 0.6))
        sy = fy + hr * 1.75
        shw = hr * 2.2
        sh = 1.2 - (((X - fx) / shw) ** 2 + ((Y - sy - hr * 0.5) / (hr * 0.75)) ** 2)
        torso = 1.0 - np.maximum(np.abs(X - fx) / (shw * 0.88), (sy + hr * 0.5 - Y) / (hr * 0.4))
        m = np.maximum(np.maximum(head, neck), np.maximum(sh, torso))
        return np.clip(m * 2.0, 0, 1).astype(np.float32)

    def _portrait_mask(self, g2):
        """Head and shoulders following the most textured region (the face of
        whoever holds the phone). Half size."""
        w, h = g2.shape
        X, Y = self.X2, self.Y2
        lo = _blur(g2, 2)
        tex = _blur(np.abs(g2 - lo), 1)
        sal = tex * self.centre2
        s = float(sal.sum())
        if s > 1:
            fx = float((sal * X).sum() / s)
            fy = float((sal * Y).sum() / s)
        else:
            fx, fy = w / 2, h * 0.42
        px, py = getattr(self, "_pfx", (fx, fy))
        fx, fy = px * 0.6 + fx * 0.4, py * 0.6 + fy * 0.4
        self._pfx = (fx, fy)
        m = self._silhouette(fx, fy - h * 0.04, h * 0.62)
        tn = tex * (1.0 / max(1.0, float(tex.max())))
        return np.clip(m * (0.8 + 0.4 * tn), 0, 1).astype(np.float32)

    def _find_face(self):
        """Head = the top of the body; its width a few rows down gives its size."""
        m = self.mask2
        rows = m.sum(0)
        thr = max(1.0, rows.max() * 0.15)
        ys = np.flatnonzero(rows > thr)
        if len(ys) == 0:
            return
        top = int(ys[0])
        H2 = m.shape[1]
        band = m[:, top:min(H2, top + 4)]
        wid = float((band > 0.4).sum(0).mean()) if band.size else m.shape[0] * 0.2
        size = min(H2 * 0.6, max(H2 * 0.12, wid * 1.35))
        y1 = min(H2, int(top + size))
        sub = m[:, top:y1]
        s = float(sub.sum())
        fx = float((sub * self.X2[:, top:y1]).sum() / s) * 2 if s > 2 else self.face[0]
        fy = (top + size * 0.5) * 2
        self.face = (self.face[0] * 0.6 + fx * 0.4, self.face[1] * 0.6 + fy * 0.4)
        self.face_size = self.face_size * 0.6 + size * 2 * 0.4

    # ---- picture ----
    def render(self, t, dt, smear, twist, swipe_angle, lut2, alpha, flip_v=False, flip_h=False,
               taps=4, trail=0.5, contrast=0.6, planes=0.0):
        """Return (rgb [w,h,3] uint8, alpha [w,h] uint8).

        lut2 is a (zones, 256, 3) table from flesh_luts(): luminance picks the
        column, a slow noise field picks the row, so shadows wander between
        violet, green and raw red while highlights stay bone white."""
        w, h = self.w, self.h
        self.push_age += dt
        k = min(1.0, self.push_age / 0.25)
        # glide from the previous camera frame to the latest one (tone already
        # stretched at push time)
        both = self.prev_tm + (self.tm - self.prev_tm) * k  # (w*h, 2): tone, mask
        # flow field at half resolution: a dominant swipe bent by slow noise;
        # drag zones keep some regions crisp and pull others long
        X2, Y2 = self.X2, self.Y2
        # X2, Y2 are float32: reduce the time phases mod 2 pi in float64 first.
        # Added raw, t * 0.6 loses its fraction in float32 after days of uptime
        # (t = 5 days: the smear moves in uneven steps; 2 weeks: every other
        # frame is frozen). Same picture, exact.
        tau = 2 * math.pi
        ang = (swipe_angle
               + 0.8 * np.sin(X2 * 0.09 + (t * 0.6) % tau) * np.cos(Y2 * 0.06 - (t * 0.37) % tau)
               + 0.5 * np.sin((X2 + Y2) * 0.04 + (t * 0.23) % tau))
        ox = int(t * 1.0) % (w // 2)
        oy = int(t * 0.7) % (h // 2)
        mag = smear * np.clip(self.dragz2[ox:ox + w // 2, oy:oy + h // 2] * 2.2 - 0.55, 0.08, 1.4)
        dx = np.repeat(np.repeat(np.cos(ang) * mag, 2, 0), 2, 1)
        dy = np.repeat(np.repeat(np.sin(ang) * (mag * 0.5), 2, 0), 2, 1)
        X, Y = self.X, self.Y
        if abs(twist) > 0.02:
            fx, fy = self.face
            r2 = ((X - fx) ** 2 + (Y - fy) ** 2) * (1.0 / (self.face_size * 0.7) ** 2)
            th = twist * np.exp(-r2)
            c, s = np.cos(th), np.sin(th)
            bx = fx + (X - fx) * c - (Y - fy) * s
            by = fy + (X - fx) * s + (Y - fy) * c
            np.clip(bx, 0, w - 1, out=bx)
            np.clip(by, 0, h - 1, out=by)
        else:
            bx, by = X, Y
        ex = np.clip(bx + dx, 0, w - 1) - bx
        ey = np.clip(by + dy, 0, h - 1) - by
        acc = None
        for i in range(taps):
            f = i / max(1, taps - 1)
            idx = (bx + ex * f).astype(np.int32) * h + (by + ey * f).astype(np.int32)
            v = both[idx.ravel()]
            acc = v if acc is None else acc + v
        acc *= 1.0 / taps
        g = acc[:, 0].reshape(w, h)
        m = acc[:, 1].reshape(w, h)
        # flatten big light/dark masses so a pale face does not sit like a mask
        # on a dark torso; keep (and sharpen) the small modelling
        big = np.repeat(np.repeat(g.reshape(w // 4, 4, h // 4, 4).mean((1, 3)), 4, 0), 4, 1)
        big = _blur(big, 1)
        g = big * (1 - contrast) + 0.52 * contrast + (g - big) * (1.35 + 0.4 * contrast)
        g *= self.brush
        if planes > 0:
            # flat planes of paint: the tone falls into a few values, with
            # stroke-shaped borders (the dither is dragged brush noise)
            q = np.floor(g * 6.0 + self.dither) * (1 / 6.0)
            g = g + (q - g) * planes
        np.clip(g, 0, 0.999, out=g)
        zx = int(t * 1.7) % w
        zy = int(t * 0.9) % h
        zi = self.zones[zx:zx + w, zy:zy + h] * (lut2.shape[0] - 0.01)
        rgb = lut2.reshape(-1, 3)[zi.astype(np.int32) * 256 + (g * 256).astype(np.int32)]
        a = np.clip(m * 1.15, 0, 1) * self.border
        # ghost of where the body just was: a dragged, cooled trail
        if trail > 0 and self.trail_rgb is not None:
            self.trail_a *= math.exp(-dt / 0.9)
            ta = self.trail_a * trail
            show = ta > a + 0.05
            rgb = np.where(show[..., None], self.trail_rgb, rgb)
            a = np.maximum(a, ta)
        self.last_rgb, self.last_a = rgb, a
        rgb = rgb.astype(np.uint8)
        a = (a * (alpha * 255)).astype(np.uint8)
        if flip_v:
            rgb = rgb[:, ::-1]; a = a[:, ::-1]
        if flip_h:
            rgb = rgb[::-1]; a = a[::-1]
        return np.ascontiguousarray(rgb), np.ascontiguousarray(a)

    def _update_trail(self):
        """At each new camera frame: remember the body as it was, cooled."""
        rgb = getattr(self, "last_rgb", None)
        if rgb is None:
            return
        a = self.last_a
        if self.trail_rgb is None:
            self.trail_rgb = np.zeros(rgb.shape, np.float32)
        take = a > self.trail_a
        grey = rgb.mean(-1, keepdims=True)
        cooled = rgb * 0.5 + grey * 0.3 + np.array([44, 34, 70], np.float32) * 0.2
        self.trail_rgb = np.where(take[..., None], cooled, self.trail_rgb)
        self.trail_a = np.where(take, a, self.trail_a)


# ---------------------------------------------------------------- colour
def flesh_lut(pal, rawness=0.5, cold=0.0, shadow=None):
    """256-entry RGB lookup from luminance to paint: tinted shadows, raw reds,
    flesh pinks, bone highlights. pal is the 5-colour palette."""
    p = [np.array(c, np.float32) for c in pal]
    raw = np.array([158, 30, 40], np.float32)
    shade = np.array([52, 26, 78], np.float32) if shadow is None else np.array(shadow, np.float32)
    flesh = np.array([218, 140, 122], np.float32)
    bone = np.array([240, 226, 200], np.float32)
    if cold > 0:
        flesh = flesh * (1 - cold) + np.array([150, 162, 172], np.float32) * cold
        raw = raw * (1 - cold) + np.array([70, 76, 100], np.float32) * cold
    # the darkest stop is a deep coloured shadow, never black: it has to read
    # in a lit room
    deep = shade * 0.55 + p[1] * 0.45
    stops = [
        (0.00, deep * 0.8),
        (0.20, shade * 0.7 + p[1] * 0.3),
        (0.42, raw * rawness + (p[2] * 0.5 + flesh * 0.5) * (1 - rawness)),
        (0.66, flesh * 0.72 + p[3] * 0.28),
        (0.88, bone * 0.65 + p[4] * 0.35),
        (1.00, np.array([252, 246, 236], np.float32)),
    ]
    lut = np.zeros((256, 3), np.float32)
    xs = np.linspace(0, 1, 256)
    for (x0, c0), (x1, c1) in zip(stops[:-1], stops[1:]):
        sel = (xs >= x0) & (xs <= x1)
        f = ((xs[sel] - x0) / (x1 - x0))[:, None]
        lut[sel] = c0 * (1 - f) + c1 * f
    return np.clip(lut, 0, 255).astype(np.uint8)


SHADOWS = [
    (52, 26, 78),    # violet bruise
    (30, 72, 62),    # green shadow
    (96, 20, 42),    # raw red
    (40, 44, 96),    # cold blue
    (74, 52, 30),    # umber
]
MIDS = [
    (222, 142, 124),  # pink flesh
    (206, 160, 104),  # ochre
    (176, 150, 170),  # lilac grey
    (160, 170, 140),  # green grey
    (200, 96, 90),    # raw red
]


def flesh_luts(pal, rawness=0.5, cold=0.0, zones=12, seed=0):
    """A (zones, 256, 3) table: each row is a flesh ramp with its own shadow
    colour and its own mid tone (pink, ochre, lilac, green-grey, raw red);
    neighbouring rows are close so the zones melt into one another. Highlights
    stay bone white in every row."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(SHADOWS))
    order_s = [SHADOWS[i] for i in perm]
    order_m = [MIDS[i] for i in rng.permutation(len(MIDS))]
    p = [np.array(c, np.float32) for c in pal]
    bone = np.array([242, 230, 206], np.float32)
    rows = []
    xs = np.linspace(0, 1, 256)
    for z in range(zones):
        f = z / max(1, zones - 1) * (len(order_s) - 1)
        i = int(f); fr = f - i
        j = min(i + 1, len(order_s) - 1)
        sh = np.array(order_s[i], np.float32) * (1 - fr) + np.array(order_s[j], np.float32) * fr
        md = np.array(order_m[i], np.float32) * (1 - fr) + np.array(order_m[j], np.float32) * fr
        if cold > 0:
            grey = md.mean()
            md = md * (1 - cold) + np.array([grey * 0.9, grey * 0.98, grey * 1.08]) * cold
            sh = sh * (1 - cold * 0.5) + np.array([40, 46, 70], np.float32) * cold * 0.5
        raw = np.array([170, 34, 44], np.float32)
        r = min(1.0, max(0.0, rawness + (fr - 0.5) * 0.3))
        stops = [
            (0.00, sh * 0.62 + p[1] * 0.2),
            (0.22, sh * 0.85 + p[1] * 0.15),
            (0.45, raw * r * 0.7 + md * (1 - r * 0.7)),
            (0.68, md * 0.75 + p[3] * 0.25),
            (0.90, bone * 0.7 + p[4] * 0.3),
            (1.00, np.array([252, 246, 236], np.float32)),
        ]
        lut = np.zeros((256, 3), np.float32)
        for (x0, c0), (x1, c1) in zip(stops[:-1], stops[1:]):
            sel = (xs >= x0) & (xs <= x1)
            fx = ((xs[sel] - x0) / (x1 - x0))[:, None]
            lut[sel] = c0 * (1 - fx) + c1 * fx
        rows.append(np.clip(lut, 0, 255).astype(np.uint8))
    return np.stack(rows)
