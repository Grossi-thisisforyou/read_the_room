"""Built-in fallback visuals for the Infinite Jest show engine.

Used when the full visuals module is not installed, so the show still runs end
to end. Everything is generated procedurally (no asset files): pygame draw
primitives for strokes and text, and small numpy fields (about 192 px wide)
scaled up to the projector size for the painterly and sensor-driven scenes.

Scenes (picked from state["scene"], or from the phase when the scene is unknown):
  void        idle: near-black, slow breathing grain, faint scanlines
  surveil     approach: grid, scanning bar, crosshair, flickering subject tags
  dossier     profiling: OCEAN bars being "computed", scrolling pseudo-data
  flesh       smeared meat-red blobs pulsing inside a drawn cage, with trails
  scrawl      crossed-out words, redaction bars, tally marks, jittering black/yellow/red strokes
  inverted    an upside-down crude figure built up from thick gestural strokes
  mirror      live abstraction warped by phone motion/tilt/touch
  afterimage  release: the last frame decays and doubles into black
  erase       wipe: white flash, wipe bars, "DELETED"

Interface: create(size, config) -> Visuals with on_state(state), render(surface, dt)
and on_wipe(). The visuals keep nothing about a visitor after on_wipe().
"""
from __future__ import annotations

import hashlib
import logging
import math
import random

import numpy as np
import pygame

log = logging.getLogger("showengine.fallback_visuals")

DEFAULT_COLORS = ["#060505", "#7a0a0a", "#c9737a", "#f2c200", "#e8dcc0", "#1b2a6b"]
PHASE_SCENE = {
    "idle": "void", "approach": "surveil", "profiling": "dossier", "hook": "flesh",
    "release": "afterimage", "wipe": "erase",
}
SCENES = ("void", "surveil", "dossier", "flesh", "scrawl", "inverted", "mirror",
          "afterimage", "erase")
GRAIN = {"void": 3, "surveil": 1, "dossier": 1, "flesh": 2, "scrawl": 1, "inverted": 2,
         "mirror": 1, "afterimage": 2, "erase": 0}
OCEAN_KEYS = (("O", "OPENNESS"), ("C", "CONSCIENTIOUSNESS"), ("E", "EXTRAVERSION"),
              ("A", "AGREEABLENESS"), ("N", "NEUROTICISM"))
WORDS = ("DATA", "INTIMACY", "YOURS", "SOLD", "MINE", "TENDER", "PROPERTY",
         "FOREVER", "OPT OUT", "KEPT", "SUBJECT")
FADE_S = 0.5
LOW_W = 192


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def _num(v, default):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _hex(c):
    if isinstance(c, (tuple, list)) and len(c) >= 3:
        return tuple(int(_clamp(_num(x, 0), 0, 255)) for x in c[:3])
    s = str(c).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(c)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _scale(c, k):
    return tuple(int(_clamp(x * k, 0, 255)) for x in c)


def _subject_hex(vid):
    if not vid:
        return "0x00"
    return "0x" + hashlib.sha1(str(vid).encode()).hexdigest()[:2].upper()


class _Palette:
    def __init__(self, colors):
        cols = []
        for c in colors or ():
            try:
                cols.append(_hex(c))
            except (ValueError, TypeError):
                pass
        if not cols:
            cols = [_hex(c) for c in DEFAULT_COLORS]
        s = sorted(cols, key=_lum)
        self.colors = cols
        self.bg = s[0] if _lum(s[0]) < 30 else _scale(s[0], 18 / max(_lum(s[0]), 1))
        self.light = s[-1] if _lum(s[-1]) > 140 else (232, 220, 192)
        self.red = max(cols, key=lambda c: c[0] - 1.2 * max(c[1], c[2]))
        if self.red[0] < 90:
            self.red = (150, 14, 14)
        self.yellow = max(cols, key=lambda c: (c[0] + c[1]) / 2 - 1.2 * c[2])
        if self.yellow[0] + self.yellow[1] < 260:
            self.yellow = (242, 194, 0)
        self.accents = [c for c in s[1:] if c != self.light] or [self.red]
        pink = _mix(self.red, self.light, 0.45)
        stops = [self.bg, _scale(self.red, 0.45), self.red, pink, self.light]
        self.lut = self._gradient(stops)

    @staticmethod
    def _gradient(stops):
        xs = np.linspace(0, 1, len(stops))
        t = np.linspace(0, 1, 256)
        arr = np.array(stops, dtype=np.float32)
        lut = np.stack([np.interp(t, xs, arr[:, i]) for i in range(3)], axis=1)
        return lut.astype(np.uint8)


class Visuals:
    def __init__(self, size, config=None):
        self.config = dict(config or {})
        pygame.font.init()
        self._rng = random.Random(0x1A57)
        self._fonts = {}
        self._text_cache = {}
        self._size = None
        self._clock = 0.0
        self._beat = 0.0
        self._last_beat_i = -1
        self._pal_key = None
        self.pal = _Palette(None)
        self._state = {}
        self._scene = "void"
        self._scene_t = 0.0
        self._snapshot = None
        self._fade = 0.0
        self._resize(tuple(int(v) for v in size))
        self._reset_visitor()

    # ------------------------------------------------------------- set-up
    def _resize(self, size):
        w, h = max(16, size[0]), max(16, size[1])
        self._size = (w, h)
        self.w, self.h = w, h
        self.canvas = pygame.Surface((w, h))
        self.canvas.fill((0, 0, 0))
        self.lw = LOW_W
        self.lh = max(8, round(LOW_W * h / w))
        self.aspect = w / h
        gx, gy = np.meshgrid(np.linspace(0, 1, self.lw, dtype=np.float32),
                             np.linspace(0, 1, self.lh, dtype=np.float32), indexing="ij")
        self.gx, self.gy = gx, gy
        self.low = pygame.Surface((self.lw, self.lh))
        self.up = pygame.Surface((w, h))
        rng = np.random.default_rng(7)
        self._streaks = np.repeat(
            np.convolve(rng.random(self.lh + 4), np.ones(5) / 5, "valid")[None, : self.lh],
            self.lw, axis=0).astype(np.float32)
        self._accum = np.zeros((self.lw, self.lh), np.float32)
        self._mirror_prev = np.zeros((self.lw, self.lh), np.float32)
        # grain tiles: [level][frame], additive
        self._grain = []
        for lvl in (6, 14, 24):
            frames = []
            for _ in range(3):
                n = (rng.random((256, 256)) ** 3 * lvl).astype(np.uint8)
                frames.append(pygame.surfarray.make_surface(np.repeat(n[:, :, None], 3, 2)))
            self._grain.append(frames)
        # scanlines (multiply)
        self._scan = pygame.Surface((w, h))
        self._scan.fill((255, 255, 255))
        for y in range(0, h, 3):
            pygame.draw.line(self._scan, (196, 196, 196), (0, y), (w, y))
        self._paint = pygame.Surface((w, h))
        self._paint.fill(self.pal.bg)
        self._paint_fade = pygame.Surface((w, h))
        self._paint_fade.set_alpha(14)
        self._paint_fade_col = None
        self._ghost = None
        self._text_cache.clear()

    def _reset_visitor(self):
        self._vid = None
        self._ocean = None
        self._data_lines = []
        self._scrawl_items = []
        self._scrawl_layer = None
        self._blobs = []
        self._ghost = None
        self._paint.fill(self.pal.bg)
        self._accum[:] = 0
        self._mirror_prev[:] = 0
        self._text_cache.clear()

    def _font(self, px):
        px = max(8, int(px))
        f = self._fonts.get(px)
        if f is None:
            f = self._fonts[px] = pygame.font.Font(None, px)
        return f

    def _text(self, s, px, color):
        key = (s, int(px), color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 600:
                self._text_cache.clear()
            surf = self._text_cache[key] = self._font(px).render(s, True, color)
        return surf

    # ------------------------------------------------------------ interface
    def on_state(self, state):
        state = state or {}
        self._state = state
        pal = state.get("palette") or {}
        colors = pal.get("colors") if isinstance(pal, dict) else None
        key = tuple(colors) if isinstance(colors, (list, tuple)) else None
        if key != self._pal_key:
            self._pal_key = key
            self.pal = _Palette(colors)
        vid = state.get("visitor_id")
        if vid != self._vid:
            self._vid = vid
            self._data_lines = []
            self._scrawl_items = []
            self._scrawl_layer = None
        oc = state.get("ocean")
        self._ocean = oc if isinstance(oc, dict) else None
        self._set_scene(self._pick_scene(state))

    def on_wipe(self):
        self._reset_visitor()
        self._state = {"phase": "wipe"}
        self._set_scene("erase", force=True)

    def render(self, surface, dt):
        dt = _clamp(_num(dt, 1 / 30), 0.0, 0.25)
        if surface.get_size() != self._size:
            self._resize(surface.get_size())
        st = self._state
        self.intensity = _clamp(_num(st.get("intensity"), 0.35))
        tempo = _clamp(_num(st.get("tempo"), 128.0), 40.0, 220.0)
        self._clock += dt
        self._scene_t += dt
        self._beat += dt * tempo / 60.0
        frac = self._beat % 1.0
        self.pulse = math.exp(-6.0 * frac)
        bi = int(self._beat)
        self.new_beat = bi != self._last_beat_i
        self._last_beat_i = bi
        self.t = self._clock
        sensor = st.get("sensor") if isinstance(st.get("sensor"), dict) else {}
        self.sensor = sensor

        getattr(self, "_s_" + self._scene)(self.canvas, dt)

        lvl = GRAIN.get(self._scene, 1)
        if lvl:
            self._apply_grain(self.canvas, lvl - 1)
        if self._scene != "erase":
            self.canvas.blit(self._scan, (0, 0), special_flags=pygame.BLEND_MULT)
        if self._fade > 0 and self._snapshot is not None:
            self._fade = max(0.0, self._fade - dt)
            self._snapshot.set_alpha(int(255 * self._fade / FADE_S))
            self.canvas.blit(self._snapshot, (0, 0))
            if self._fade <= 0:
                self._snapshot = None
        dx = dy = 0
        if self.intensity > 0.6 and self.pulse > 0.75 and self._scene not in ("void", "afterimage"):
            amp = int(self.h * 0.006 * self.intensity)
            dx, dy = self._rng.randint(-amp, amp), self._rng.randint(-amp, amp)
            surface.fill((0, 0, 0))
        surface.blit(self.canvas, (dx, dy))

    # ------------------------------------------------------------- helpers
    def _pick_scene(self, st):
        sc = st.get("scene")
        if sc in SCENES:
            return sc
        hook = st.get("hook")
        if st.get("phase") == "hook" and hook in SCENES:
            return hook
        return PHASE_SCENE.get(st.get("phase"), "void")

    def _set_scene(self, scene, force=False):
        if scene == self._scene and not force:
            return
        prev = self._scene
        self._scene = scene
        self._scene_t = 0.0
        if scene == "erase":
            self._snapshot = self.canvas.copy()  # erase cuts hard; snapshot feeds the glitch
            self._fade = 0.0
        else:
            self._snapshot = self.canvas.copy()
            self._fade = FADE_S
        if scene == "afterimage":
            self._ghost = pygame.transform.smoothscale(self.canvas, (self.w // 4, self.h // 4))
        elif scene == "inverted" and prev != "inverted":
            self._paint.fill(self.pal.bg)
        elif scene == "flesh":
            self._blobs = []

    def _apply_grain(self, surf, level):
        frames = self._grain[int(_clamp(level, 0, 2))]
        tile = frames[self._rng.randrange(3)]
        ox, oy = self._rng.randrange(256), self._rng.randrange(256)
        for y in range(-oy, self.h, 256):
            for x in range(-ox, self.w, 256):
                surf.blit(tile, (x, y), special_flags=pygame.BLEND_ADD)

    def _field_to(self, surf, field, lo, hi, smooth=True):
        idx = np.clip((field - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        pygame.surfarray.blit_array(self.low, self.pal.lut[idx])
        if smooth:
            pygame.transform.smoothscale(self.low, (self.w, self.h), self.up)
        else:
            pygame.transform.scale(self.low, (self.w, self.h), self.up)
        surf.blit(self.up, (0, 0))

    def _jit(self, amt):
        return self._rng.gauss(0, amt)

    # --------------------------------------------------------------- scenes
    def _s_void(self, surf, dt):
        b = 0.5 + 0.5 * math.sin(self.t * 0.55)
        surf.fill(_scale(self.pal.bg, 0.5 + 0.9 * b))
        bh = self.h // 9
        y = int((self.t * self.h * 0.04) % (self.h + bh)) - bh
        pygame.draw.rect(surf, _scale(self.pal.bg, 1.6 + 0.6 * b), (0, y, self.w, bh))
        if self._rng.random() < 0.02 + 0.05 * self.intensity:
            yy = self._rng.randrange(self.h)
            pygame.draw.line(surf, _scale(self.pal.red, 0.35), (0, yy), (self.w, yy))
        if int(self.t * 1.2) % 2 == 0:
            s = self._text("AWAITING SUBJECT", self.h * 0.022, _scale(self.pal.light, 0.16))
            surf.blit(s, (int(self.w * 0.04), int(self.h * 0.93)))

    def _s_surveil(self, surf, dt):
        w, h, p = self.w, self.h, self.pal
        sp = 0.5 + 1.5 * self.intensity
        surf.fill(p.bg)
        grid = _mix(p.bg, p.light, 0.07 + 0.05 * self.pulse)
        step = max(16, h // 12)
        for x in range(0, w, step):
            pygame.draw.line(surf, grid, (x, 0), (x, h))
        for y in range(0, h, step):
            pygame.draw.line(surf, grid, (0, y), (w, y))
        sy = int((self.t * h * 0.35 * sp) % h)
        for k in range(6):
            pygame.draw.line(surf, _mix(p.bg, p.light, 0.6 / (k + 1)), (0, sy - k * 3), (w, sy - k * 3), 2 if k == 0 else 1)
        touch = self.sensor.get("touch") if isinstance(self.sensor.get("touch"), dict) else None
        if touch and "x" in touch:
            tx, ty = _clamp(_num(touch.get("x"), 0.5)), _clamp(_num(touch.get("y"), 0.5))
        else:
            tx = 0.5 + 0.32 * math.sin(self.t * 0.71 * sp)
            ty = 0.5 + 0.28 * math.sin(self.t * 0.53 * sp + 1.3)
        j = 2 + 10 * self.intensity
        cx, cy = int(tx * w + self._jit(j)), int(ty * h + self._jit(j))
        dim = _mix(p.bg, p.light, 0.22)
        pygame.draw.line(surf, dim, (0, cy), (w, cy))
        pygame.draw.line(surf, dim, (cx, 0), (cx, h))
        r = int(h * (0.08 + 0.02 * self.pulse))
        pygame.draw.circle(surf, p.light, (cx, cy), r, 2)
        pygame.draw.circle(surf, p.red, (cx, cy), max(3, r // 8))
        bs, bl = int(h * 0.16), int(h * 0.04)
        for sx, sy2 in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x0, y0 = cx + sx * bs, cy + sy2 * bs
            pygame.draw.line(surf, p.light, (x0, y0), (x0 - sx * bl, y0), 3)
            pygame.draw.line(surf, p.light, (x0, y0), (x0, y0 - sy2 * bl), 3)
        motion = _num(self.sensor.get("motion"), 0.0)
        faces = int(_num(self.sensor.get("faces"), 0))
        tags = [f"SUBJECT {_subject_hex(self._vid)}", f"X{cx:04d} Y{cy:04d}",
                f"DWELL {self._scene_t:05.1f}s", f"MOTION {motion:.2f}", f"FACES {faces}",
                "MATCH %.1f%%" % (60 + 39 * abs(math.sin(self.t * 0.3)))]
        fs = h * 0.03
        for i, tag in enumerate(tags):
            if self._rng.random() < 0.12 + 0.25 * self.intensity:
                continue
            col = p.red if i == 0 and self.pulse > 0.5 else p.light
            surf.blit(self._font(fs).render(tag, True, col), (cx + bs + 12, cy - bs + i * int(fs * 1.05)))
        if int(self.t * 2) % 2 == 0:
            pygame.draw.circle(surf, p.red, (int(w * 0.04), int(h * 0.06)), int(h * 0.012))
        surf.blit(self._text("REC", fs, p.light), (int(w * 0.04 + h * 0.025), int(h * 0.045)))

    def _gen_data_lines(self):
        r = random.Random(str(self._vid))
        lines = []
        kinds = ("hex", "geo", "gaze", "dwell", "like", "pulse", "match", "tag")
        for i in range(80):
            k = r.choice(kinds)
            if k == "hex":
                s = " ".join("%02X" % r.randrange(256) for _ in range(12))
            elif k == "geo":
                s = "loc %.4f %.4f  acc %dm" % (40.73 + r.random() / 100, -73.99 - r.random() / 100, r.randrange(3, 40))
            elif k == "gaze":
                s = "gaze_vec (%.2f, %.2f)  fix %dms" % (r.uniform(-1, 1), r.uniform(-1, 1), r.randrange(80, 900))
            elif k == "dwell":
                s = "dwell 00:%02d.%02d  zone %s" % (r.randrange(60), r.randrange(100), r.choice("ABCDEF"))
            elif k == "like":
                s = "affinity %-10s %.3f" % (r.choice(("loss", "flesh", "noise", "night", "tender", "control", "decay")), r.random())
            elif k == "pulse":
                s = "arousal_est %.2f  conf %.2f" % (r.random(), r.random())
            elif k == "match":
                s = "lookalike cohort #%05d  n=%d" % (r.randrange(99999), r.randrange(40, 9000))
            else:
                s = "tag %s  -> retained" % r.choice(WORDS)
            lines.append(s)
        self._data_lines = lines

    def _s_dossier(self, surf, dt):
        w, h, p = self.w, self.h, self.pal
        surf.fill(p.bg)
        if not self._data_lines:
            self._gen_data_lines()
        fs = h * 0.032
        head = f"DOSSIER // SUBJECT {_subject_hex(self._vid)} // PROFILE IN PROGRESS"
        n = min(len(head), int(self._scene_t * (14 + 20 * self.intensity)))
        txt = head[:n] + ("_" if int(self.t * 3) % 2 == 0 else " ")
        surf.blit(self._font(h * 0.045).render(txt, True, p.light), (int(w * 0.05), int(h * 0.06)))
        prog = _clamp(self._scene_t / (8.0 - 4.0 * self.intensity))
        sm = prog * prog * (3 - 2 * prog)
        seed = int(hashlib.sha1(str(self._vid).encode()).hexdigest()[:8], 16)
        x0, y0, bw, bh = int(w * 0.05), int(h * 0.2), int(w * 0.38), int(h * 0.05)
        for i, (k, name) in enumerate(OCEAN_KEYS):
            target = _num((self._ocean or {}).get(k), ((seed >> (i * 5)) % 97) / 96.0)
            noise = 0.5 + 0.5 * math.sin(self.t * (9 + i * 3.7) + i * 7)
            v = _clamp(noise + (_clamp(target) - noise) * sm + self._jit(0.03 * (1 - sm)))
            y = y0 + i * int(bh * 2.3)
            surf.blit(self._text(name, fs * 0.8, _scale(p.light, 0.7)), (x0, y - int(fs * 0.8)))
            pygame.draw.rect(surf, _mix(p.bg, p.light, 0.12), (x0, y, bw, bh))
            col = p.red if v < 0.75 else p.yellow
            pygame.draw.rect(surf, col, (x0, y, int(bw * v), bh))
            pygame.draw.rect(surf, p.light, (x0, y, bw, bh), 1)
            surf.blit(self._font(fs).render("%.3f" % v, True, p.light), (x0 + bw + 14, y + 4))
        ly = y0 + 5 * int(bh * 2.3)
        surf.blit(self._text("MODELLING DESIRE", fs, p.light), (x0, ly))
        pygame.draw.rect(surf, p.light, (x0, ly + int(fs * 1.2), bw, 6), 1)
        pygame.draw.rect(surf, p.red, (x0, ly + int(fs * 1.2), int(bw * prog), 6))
        # scrolling data column
        cx, lh = int(w * 0.55), int(fs * 1.05)
        speed = 30 + 120 * self.intensity
        off = self._scene_t * speed
        first = int(off // lh)
        rows = h // lh + 2
        col_dim = _mix(p.bg, p.light, 0.45)
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(cx, int(h * 0.15), w - cx, int(h * 0.8)))
        for r_ in range(rows):
            idx = (first + r_) % len(self._data_lines)
            y = int(h * 0.15) + r_ * lh - int(off % lh)
            hot = (idx * 7 + int(self._beat)) % 23 == 0
            surf.blit(self._text(self._data_lines[idx], fs * 0.8, p.red if hot else col_dim), (cx, y))
        surf.set_clip(clip)

    def _s_flesh(self, surf, dt):
        w, h, p = self.w, self.h, self.pal
        n = 4 + int(self.intensity * 5)
        if len(self._blobs) != n:
            r = random.Random(str(self._vid) + "flesh")
            self._blobs = [(r.uniform(0.42, 0.58), r.uniform(0.35, 0.65), r.uniform(0.07, 0.13),
                            r.uniform(0.04, 0.14), r.uniform(0.04, 0.12), r.uniform(0.2, 0.9),
                            r.uniform(0, 6.28)) for _ in range(n)]
        sp = 0.4 + 1.6 * self.intensity
        puff = 1.0 + 0.25 * self.pulse * (0.4 + self.intensity)
        gx, gy, a2 = self.gx, self.gy, self.aspect * self.aspect
        field = np.zeros_like(gx)
        for cx, cy, rad, ax, ay, f, ph in self._blobs:
            x = cx + ax * math.sin(self.t * f * sp + ph)
            y = cy + ay * math.sin(self.t * f * 0.8 * sp + ph * 1.7)
            rr = (rad * puff) ** 2
            field += rr / ((gx - x) ** 2 * a2 + (gy - y) ** 2 + 0.002)
        s = 2 + int(3 + 5 * self.intensity)  # directional smear, Bacon-ish drag of the paint
        sk = int(3 * math.sin(self.t * 0.4))
        field = (field + np.roll(field, s, 0) * 0.8 + np.roll(field, (2 * s, sk), (0, 1)) * 0.6
                 + np.roll(field, (-s, -sk), (0, 1)) * 0.5) / 2.9
        decay = 0.86 - 0.1 * self.intensity
        self._accum *= decay
        self._accum += field * (1 - decay)
        v = self._accum * (0.8 + 0.4 * self._streaks) + 0.12 * np.sin(gy * 40 + gx * 6 + self.t)
        self._field_to(surf, v, 0.3, 5.5)
        # cage: a perspective box drawn over the figure, slightly unsteady
        j = 1 + 4 * self.intensity
        fx0, fy0, fx1, fy1 = w * 0.24, h * 0.1, w * 0.76, h * 0.9
        bx0, by0, bx1, by1 = w * 0.34, h * 0.18, w * 0.66, h * 0.7
        front = [(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1)]
        back = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        col = _mix(p.light, p.red, 0.15)
        jt = lambda q: (q[0] + self._jit(j), q[1] + self._jit(j))
        pygame.draw.lines(surf, col, True, [jt(q) for q in front], 3)
        pygame.draw.lines(surf, _scale(col, 0.6), True, [jt(q) for q in back], 2)
        for a, b in zip(front, back):
            pygame.draw.line(surf, _scale(col, 0.75), jt(a), jt(b), 2)
        pygame.draw.ellipse(surf, _scale(col, 0.5), (w * 0.38, h * 0.74, w * 0.24, h * 0.07), 2)
        for k in range(1, 6):
            x = bx0 + (bx1 - bx0) * k / 6
            pygame.draw.line(surf, _scale(col, 0.35), (x, by0), (x, by1), 1)

    def _make_scrawl_item(self, r):
        w, h, p = self.w, self.h, self.pal
        kind = r.choice(("redact", "tally", "word", "word", "word", "strokes"))
        col = r.choice((p.yellow, p.red, p.light, p.light))
        it = {"kind": kind, "x": r.uniform(0.08, 0.85) * w, "y": r.uniform(0.1, 0.85) * h,
              "s": r.uniform(0.6, 1.4) * h * 0.12, "col": col, "seed": r.random()}
        if kind == "word":
            words = list(WORDS)
            if self._vid:
                words.append(_subject_hex(self._vid))
            # live words from the profiler/oracle (already visitor-safe); never the hook name
            words += [str(x).upper()[:24] for x in (self._state.get("words") or [])[:6] if x]
            it["text"] = r.choice(words)
            it["cross"] = r.random() < 0.75
        return it

    def _build_scrawl_layer(self, r):
        w, h, p = self.w, self.h, self.pal
        layer = pygame.Surface((w, h))
        layer.fill(p.bg)
        for _ in range(r.randint(2, 4)):
            col = _scale(r.choice(p.accents + [p.red, p.yellow]), r.uniform(0.25, 0.55))
            rw, rh = r.uniform(0.15, 0.45) * w, r.uniform(0.15, 0.5) * h
            pygame.draw.rect(layer, col, (r.uniform(0, w - rw), r.uniform(0, h - rh), rw, rh))
        for _ in range(30):
            x, y = r.uniform(0, w), r.uniform(0, h)
            pygame.draw.line(layer, _scale(p.light, 0.25), (x, y), (x + r.uniform(-80, 80), y + r.uniform(-40, 40)), r.randint(1, 4))
        self._scrawl_layer = layer

    def _s_scrawl(self, surf, dt):
        w, h, p = self.w, self.h, self.pal
        r = self._rng
        if self._scrawl_layer is None or (self.new_beat and int(self._beat) % 8 == 0 and r.random() < 0.5):
            self._build_scrawl_layer(r)
        n = 5 + int(7 * self.intensity)
        while len(self._scrawl_items) < n:
            self._scrawl_items.append(self._make_scrawl_item(r))
        del self._scrawl_items[n:]
        if self.new_beat and r.random() < 0.3 + 0.6 * self.intensity:
            self._scrawl_items[r.randrange(n)] = self._make_scrawl_item(r)
        surf.blit(self._scrawl_layer, (0, 0))
        j = 1.5 + 7 * self.intensity + 6 * self.pulse * self.intensity
        lw = max(3, int(h * 0.007))
        for it in self._scrawl_items:
            x, y, s, col = it["x"] + self._jit(j), it["y"] + self._jit(j), it["s"], it["col"]
            k = it["kind"]
            if k == "redact":
                bw, bh = s * 2.2, s * 0.32
                pygame.draw.rect(surf, (0, 0, 0), (x, y, bw, bh))
                pygame.draw.rect(surf, col, (x, y, bw, bh), max(1, lw // 2))
            elif k == "tally":
                for n in range(5):
                    xx = x + n * s * 0.22
                    pygame.draw.line(surf, col, (xx + self._jit(j * 0.4), y), (xx, y + s), lw)
                pygame.draw.line(surf, col, (x - s * 0.1, y + s * 0.8), (x + s, y + s * 0.2), lw)
            elif k == "word":
                ts = self._text(it["text"], s * 0.9, col)
                surf.blit(ts, (x, y))
                if it["cross"]:
                    tw, th = ts.get_size()
                    tilt = (it["seed"] - 0.5) * th * 0.6
                    pygame.draw.line(surf, p.light if col != p.light else p.red,
                                     (x - 8, y + th * 0.5 - tilt + self._jit(j)), (x + tw + 8, y + th * 0.5 + tilt), lw + 1)
            else:
                rs = random.Random(it["seed"])
                for _ in range(4):
                    a = (x + rs.uniform(-s, s), y + rs.uniform(-s, s))
                    b = (a[0] + rs.uniform(-s, s) * 1.5, a[1] + rs.uniform(-s, s) * 0.5)
                    pygame.draw.line(surf, col, (a[0] + self._jit(j), a[1]), b, lw + rs.randint(0, 6))

    _BODY = {
        "head": (0.5, 0.13), "neck": (0.5, 0.24), "lsh": (0.36, 0.29), "rsh": (0.64, 0.29),
        "lel": (0.3, 0.45), "rel": (0.7, 0.44), "lha": (0.27, 0.6), "rha": (0.75, 0.56),
        "lhip": (0.43, 0.6), "rhip": (0.57, 0.6), "lkn": (0.41, 0.78), "rkn": (0.6, 0.79),
        "lft": (0.37, 0.96), "rft": (0.65, 0.95),
    }
    _BONES = (("neck", "lsh"), ("neck", "rsh"), ("lsh", "lel"), ("lel", "lha"), ("rsh", "rel"),
              ("rel", "rha"), ("lsh", "lhip"), ("rsh", "rhip"), ("lhip", "rhip"), ("lhip", "lkn"),
              ("lkn", "lft"), ("rhip", "rkn"), ("rkn", "rft"), ("neck", "head"), ("lsh", "rhip"))

    def _s_inverted(self, surf, dt):
        w, h, p, r = self.w, self.h, self.pal, self._rng
        fh = h * 0.86
        sway = math.sin(self.t * 0.3) * w * 0.03

        def pt(name):  # upside down: y -> 1 - y
            x, y = self._BODY[name]
            return (w / 2 + sway + (x - 0.5) * fh * 1.5, h * 0.07 + (1 - y) * fh)

        if int(self.t * 4) != int((self.t - dt) * 4):  # slow decay, 4x a second
            if self._paint_fade_col != p.bg:
                self._paint_fade.fill(p.bg)
                self._paint_fade_col = p.bg
            self._paint.blit(self._paint_fade, (0, 0))
        colors = [p.light, p.light, _mix(p.red, p.light, 0.4), _mix(p.red, p.light, 0.4), p.red, p.red, p.yellow] + p.accents
        k = 3 + int(self.intensity * 10 + self.pulse * 4 * self.intensity)
        for _ in range(k):
            col = r.choice(colors) if r.random() > 0.08 else p.bg
            width = r.randint(max(4, h // 120), max(8, h // 30))
            if r.random() < 0.18:  # head: thick ring of strokes
                cx, cy = pt("head")
                rad = fh * 0.08
                a0 = r.uniform(0, 6.28)
                a1 = a0 + r.uniform(0.6, 2.0)
                pts = [(cx + math.cos(a) * rad + self._jit(4), cy + math.sin(a) * rad + self._jit(4))
                       for a in np.linspace(a0, a1, 6)]
                pygame.draw.lines(self._paint, col, False, pts, width)
                continue
            a, b = (pt(n) for n in r.choice(self._BONES))
            t0, t1 = sorted((r.uniform(-0.1, 0.7), r.uniform(0.3, 1.1)))
            jj = h * (0.006 + 0.02 * self.intensity)
            pa = (a[0] + (b[0] - a[0]) * t0 + self._jit(jj), a[1] + (b[1] - a[1]) * t0 + self._jit(jj))
            pb = (a[0] + (b[0] - a[0]) * t1 + self._jit(jj), a[1] + (b[1] - a[1]) * t1 + self._jit(jj))
            pygame.draw.line(self._paint, col, pa, pb, width)
            pygame.draw.line(self._paint, _scale(col, 0.7), (pa[0] + width * 0.4, pa[1]), (pb[0] + width * 0.4, pb[1]), max(1, width // 4))
            if r.random() < 0.12:  # drip (down on the canvas, so "up" for the figure)
                dl = r.uniform(0.03, 0.15) * h
                pygame.draw.line(self._paint, col, pb, (pb[0], pb[1] + dl), max(2, width // 5))
        surf.blit(self._paint, (0, 0))

    def _s_mirror(self, surf, dt):
        s = self.sensor
        tilt = s.get("tilt") if isinstance(s.get("tilt"), dict) else {}
        touch = s.get("touch") if isinstance(s.get("touch"), dict) else {}
        drift = self.t * 0.2
        beta = _num(tilt.get("beta"), 25 * math.sin(drift))
        gamma = _num(tilt.get("gamma"), 25 * math.cos(drift * 0.7))
        alpha = math.radians(_num(tilt.get("alpha"), drift * 30))
        motion = _clamp(_num(s.get("motion"), 0.2 + 0.2 * math.sin(drift * 1.3)))
        loud = _clamp(_num(s.get("loudness"), 0.3))
        if "x" in touch:
            cx, cy = _clamp(_num(touch.get("x"), 0.5)), _clamp(_num(touch.get("y"), 0.5))
        else:
            cx, cy = 0.5 + _clamp(gamma / 90, -1, 1) * 0.3, 0.5 + _clamp(beta / 180, -1, 1) * 0.3
        gx, gy = self.gx, self.gy
        dxa, dy = (gx - cx) * self.aspect, gy - cy
        d = np.sqrt(dxa * dxa + dy * dy)
        ang = np.arctan2(dy, dxa)
        sp = 1.5 + 5 * self.intensity
        v = (np.sin(d * (18 + 50 * motion) - self.t * sp)
             + 0.7 * np.sin(ang * (3 + int(6 * loud)) + alpha + self.t * 0.5)
             + 0.4 * np.sin(gx * 9 + gy * 5 + self.t * 0.8))
        v = v * (0.6 + 0.6 * self.pulse * self.intensity)
        sx = int(round(_clamp(gamma / 30, -2, 2)))
        sy = int(round(_clamp(beta / 45, -2, 2)))
        prev = np.roll(self._mirror_prev, (sx, sy), (0, 1))
        self._mirror_prev = 0.55 * v + 0.45 * prev
        self._field_to(surf, self._mirror_prev, -0.6, 2.2, smooth=False)
        t = self._text("YOU", self.h * 0.05, self.pal.light)
        if self._rng.random() > 0.2:
            surf.blit(t, (int(cx * self.w) - t.get_width() // 2, int(cy * self.h) - t.get_height() // 2))

    def _s_afterimage(self, surf, dt):
        p = self.pal
        if self._ghost is None:
            self._ghost = pygame.Surface((self.w // 4, self.h // 4))
            self._ghost.fill(_scale(p.red, 0.5))
        k = int(_clamp(255 * math.exp(-dt * 0.5), 200, 252))
        self._ghost.fill((k, k, k), special_flags=pygame.BLEND_MULT)
        pygame.transform.smoothscale(self._ghost, (self.w, self.h), self.up)
        surf.fill(p.bg)
        surf.blit(self.up, (0, 0), special_flags=pygame.BLEND_MAX)
        off = int(self.w * 0.012 * math.sin(self.t * 0.7) + self.w * 0.004)
        surf.blit(self.up, (off, int(off * 0.3)), special_flags=pygame.BLEND_MAX)
        a = _clamp(self._scene_t / 3.0) * _clamp(1.5 - self._scene_t / 8.0)
        if a > 0:
            t = self._text("WE WILL REMEMBER YOU", self.h * 0.05, p.light).copy()
            t.set_alpha(int(150 * a))
            surf.blit(t, ((self.w - t.get_width()) // 2, int(self.h * 0.85)))

    def _s_erase(self, surf, dt):
        w, h, p, pt = self.w, self.h, self.pal, self._scene_t
        if pt < 0.25:
            surf.fill((255, 255, 255) if pt < 0.12 or int(pt * 40) % 2 == 0 else (0, 0, 0))
            return
        if pt < 1.4:
            src = self._snapshot
            if src is not None:
                surf.blit(src, (0, 0))
            else:
                surf.fill(p.bg)
            nb = 14
            bh = h / nb + 1
            r = random.Random(42)
            for i in range(nb):
                d = r.uniform(0, 0.45)
                q = _clamp((pt - 0.25 - d) / 0.4)
                y = int(i * h / nb)
                if src is not None and 0 < q < 1:
                    surf.blit(src, (int(w * q * 0.3 * (1 if i % 2 else -1)), y), (0, y, w, int(bh)))
                bw = int(w * q)
                x = 0 if i % 2 == 0 else w - bw
                pygame.draw.rect(surf, (0, 0, 0), (x, y, bw, int(bh)))
                if 0 < q < 1:
                    pygame.draw.line(surf, (255, 255, 255), (x + (bw if i % 2 == 0 else 0), y), (x + (bw if i % 2 == 0 else 0), y + bh), 3)
            return
        surf.fill((0, 0, 0))
        on = pt > 2.6 or self._rng.random() > 0.35
        if on and pt < 9.0:
            b = _clamp(1.0 - (pt - 4.0) / 5.0) if pt > 4.0 else 1.0
            t = self._text("DELETED", h * 0.16, _scale(p.light, b))
            surf.blit(t, ((w - t.get_width()) // 2, (h - t.get_height()) // 2))
            s = self._text("NOTHING OF YOU WAS KEPT", h * 0.03, _scale(p.red, b))
            surf.blit(s, ((w - s.get_width()) // 2, (h + t.get_height()) // 2 + 10))


def create(size, config):
    return Visuals(size, config)
