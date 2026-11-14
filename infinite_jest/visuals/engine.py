"""INFINITE JEST visuals: one projector, one visitor at a time.

Layers, back to front (all drawn at a low internal resolution, then scaled):
  1. ground   flat saturated field + floor band + dais (Bacon), or white wall
              with painted-over patches (scrawl), or near-black pulse (void)
  2. paint    a persistent canvas of raw strokes sampled from the visitor's
              colours: the longer someone stays, the more of them is painted
  3. figure   the visitor from the N900 camera, smeared along a flow field,
              twisted at the face, mapped to flesh colours; upside-down for
              the Baselitz hook, mirrored and huge for the mirror hook
  4. cage     a rotating space-frame box around the figure
  5. scrawl   hand-drawn words, crossings-out, reticles, barcodes, tallies,
              redaction bars, face-detection brackets
  6. finish   scan line while profiling, flicker and slice glitches with
              neuroticism, grain

All look parameters glide toward targets computed from the latest state
(phase, hook, intensity, palette, OCEAN, words), so nothing jumps.
"""
import math
import os
import random
import time
import zlib

import numpy as np
import pygame

from . import palettes, scrawl
from .figure import Figure, flesh_lut, ghost_body

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")

# Words for when the profiler sends none. Dark data and custom-made intimacy.
LEX_TENDER = ["MADE FOR YOU", "STAY", "ONLY YOU", "WE SAW YOU", "YOURS", "TAILORED",
              "SKIN", "CLOSER", "YOU ARE SEEN", "INTIMACY", "FOR YOU ONLY", "HOLD STILL",
              "KEEP LOOKING", "WE LIKE THIS ONE", "SOFT TARGET"]
LEX_COLD = ["DATA", "PROFILE", "SUBJECT", "HARVEST", "SCORE", "PREDICTED", "CONSENT",
            "SAMPLE", "OPTED IN", "TARGET", "RETAINED", "LEAKED", "SEGMENT", "HOOKED",
            "RAW MATERIAL", "PROPERTY OF", "MONETIZE", "NO NAME", "BEHAVIOUR"]
LEX_JEST = ["INFINITE", "JEST", "ENTERTAINMENT", "LOOP", "MORE", "AGAIN", "ONE MORE",
            "THE ENTERTAINMENT", "DONT LOOK AWAY", "PLEASURE"]
LEX_IDLE = ["NOBODY", "WAITING", "EMPTY ROOM", "NEXT", "COME IN", "WE ARE READY"]


def _lerp(a, b, k):
    return a + (b - a) * k


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


class Visuals:
    def __init__(self, size, config=None):
        config = config or {}
        self.size = tuple(size)
        iw, ih = config.get("internal_size", (640, 360))
        self.W, self.H = int(iw), int(ih)
        self.smooth = bool(config.get("smooth_scale", True))
        self.fig = Figure(int(config.get("figure_w", 160)), int(config.get("figure_h", 180)))
        self.low = pygame.Surface((self.W, self.H))
        self.paint = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        # words are drawn at the full output resolution so they stay crisp at 1080p
        self.TW, self.TH = self.size
        self.k = self.TW / self.W
        # marks are drawn onto this scratch sheet, then cut out into small
        # surfaces with their own age-based alpha (fading a whole 1080p sheet
        # every frame costs too much on a Pi)
        self.text = pygame.Surface((self.TW, self.TH), pygame.SRCALPHA)
        self.marks = []  # [surface, (x, y), birth time]
        self.tilt = [0.0, 0.0]      # smoothed x (left/right), y (forward/back), -1..1
        self.tilt_in = [0.0, 0.0]
        self.tilt_energy = 0.0
        self.fig_surf = pygame.Surface((self.fig.w, self.fig.h), pygame.SRCALPHA)
        self.grain = self._make_grain()
        self.t = 0.0
        self.state = {}
        self.extra_words = []
        self.next_mark = 0.0
        self.wipe_t = None
        self.rng = random.Random(1)
        self.visitor = None
        self.ground = None
        self.ground_key = None
        self.lut = None
        self.lut_key = None
        self.bank_dir = config.get("bank_dir")
        self.bank_max = int(config.get("bank_max_per_hook", 40))
        self.bank = self._load_bank(self.bank_dir)
        self.bank_loaded = time.monotonic()
        # while a visitor is present, keep this file fresh so the overnight image
        # generator (bank_gen) pauses and leaves the CPU to picture and sound
        self.busy_file = config.get("busy_file", "/tmp/infinite_jest_busy")
        self.busy_touched = 0.0
        # gliding look parameters
        self.p = dict(fig_alpha=0.0, smear=6.0, twist=0.0, swipe=0.0, cage=0.7, cage_jit=0.2,
                      stroke_rate=0.0, flicker=0.0, glitch=0.0, flip=0.0, scale=1.0,
                      ground_lum=1.0, mark_rate=0.3, jitter=0.35, text_fade=0.996, scan=0.0)
        self.hook = "flesh"
        self.pal = palettes.get("triptych")
        self.frame_ms = 0.0

    # ---- engine interface -------------------------------------------------
    def on_state(self, state):
        if not isinstance(state, dict):
            return
        if state.get("type") == "state" and isinstance(state.get("data"), dict):
            state = state["data"]
        vid = state.get("visitor_id")
        if vid != self.visitor:
            self.visitor = vid
            self.rng = random.Random(zlib.crc32(str(vid).encode()))
        if state.get("phase") == "wipe" and self.state.get("phase") != "wipe":
            self.on_wipe()
        self.state = state
        self._read_tilt(state)
        self._busy(state.get("phase", "idle") not in ("idle", None))

    def _busy(self, busy):
        if not self.busy_file:
            return
        now = time.monotonic()
        try:
            if busy and now - self.busy_touched > 5:
                with open(self.busy_file, "a"):
                    os.utime(self.busy_file, None)
                self.busy_touched = now
            elif not busy and self.busy_touched:
                os.remove(self.busy_file)
                self.busy_touched = 0.0
        except OSError:
            pass

    def on_sensor(self, data):
        """Optional: raw phone sensor dict (contract kind "phone")."""
        if not isinstance(data, dict):
            return
        if getattr(self, "steer_t", None) is not None and time.monotonic() - self.steer_t < 1.0:
            # the engine's state.steer (smoothed, +-45 deg range) is driving; the raw degrees
            # (/60) arriving in between made the target jump between two scales every frame
            data = {k: data[k] for k in ("shake", "tilt_energy") if k in data}
        self._read_tilt(data)

    def _read_tilt(self, d):
        st = d.get("steer")  # contract 1.3: {x, y, flip, shake}
        if isinstance(st, dict):
            self.steer_t = time.monotonic()
            self.tilt_in = [_clamp(float(st.get("x", 0)), -1, 1), _clamp(float(st.get("y", 0)), -1, 1)]
            self.steer_flip = bool(st.get("flip", False))
            try:
                self.tilt_energy = max(self.tilt_energy, _clamp(float(st.get("shake", 0))))
            except (TypeError, ValueError):
                pass
            return
        t = d.get("tilt")
        if isinstance(t, dict):
            if "x" in t or "y" in t:          # engine format, -1..1
                self.tilt_in = [_clamp(float(t.get("x", 0)), -1, 1), _clamp(float(t.get("y", 0)), -1, 1)]
            elif "gamma" in t or "beta" in t:  # raw degrees from the phone
                self.tilt_in = [_clamp(float(t.get("gamma", 0)) / 60, -1, 1), _clamp(float(t.get("beta", 0)) / 60, -1, 1)]
        for key in ("tilt_energy", "shake"):
            if key in d:
                try:
                    self.tilt_energy = max(self.tilt_energy, _clamp(float(d[key])))
                except (TypeError, ValueError):
                    pass

    def on_frame(self, frame):
        """frame: numpy [h, w] gray or [h, w, 3] RGB uint8 (N900 sends gray8)."""
        try:
            self.fig.push(frame)
        except Exception:
            pass

    def on_text(self, words):
        self.extra_words = [str(w) for w in words][-24:]

    def on_wipe(self):
        """Drop everything held about the visitor and paint the room over."""
        self.fig.wipe()
        self.extra_words = []
        self.wipe_t = self.t
        if time.monotonic() - self.bank_loaded > 600:  # pick up new overnight images
            self.bank = self._load_bank(self.bank_dir)
            self.bank_loaded = time.monotonic()

    def render(self, surface, dt):
        t0 = time.perf_counter()
        dt = min(max(dt, 0.0), 0.2)
        self.t += dt
        self._update_params(dt)
        self._draw_ground()
        self._draw_paint(dt)
        self._draw_figure()
        self._draw_cage()
        self._update_text(dt)
        self._draw_wipe()
        self._finish()
        if surface.get_size() == (self.W, self.H):
            surface.blit(self.low, (0, 0))
        elif self.smooth:
            pygame.transform.smoothscale(self.low, surface.get_size(), surface)
        else:
            pygame.transform.scale(self.low, surface.get_size(), surface)
        self._blit_marks(surface)
        self.frame_ms = self.frame_ms * 0.9 + (time.perf_counter() - t0) * 100

    # ---- state -> look ----------------------------------------------------
    def _ocean(self):
        o = self.state.get("ocean") or {}
        return {k: _clamp(float(o.get(k, 0.5))) for k in "OCEAN"}

    def _update_params(self, dt):
        s = self.state
        oc = self._ocean()
        O, C, E, A, N = (oc[k] for k in "OCEAN")
        phase = s.get("phase", "idle")
        pt = float(s.get("phase_t", 0.0))
        inten = _clamp(float(s.get("intensity", 0.4)))
        hook = s.get("hook") or s.get("scene") or "flesh"
        if hook not in HOOKS:
            # unknown hook name: a stable choice among the five so it is never blank
            hook = HOOKS[zlib.crc32(str(hook).encode()) % 4]
        self.hook = hook
        pal = s.get("palette")
        self.pal = palettes.get(pal) if pal else palettes.get(palettes.pick_for(oc, hook))

        tg = {}
        present = {"idle": 0.0, "approach": _clamp(pt / 3.0), "profiling": 1.0,
                   "hook": 1.0, "release": _clamp(1 - pt / 6.0), "wipe": 0.0}.get(phase, 0.0)
        if not self.fig.ready and phase != "idle":
            # no camera yet: a ghost stands in so the room is never empty
            self.fig.push(ghost_body(120, 160, self.t, seed=3, present=1.0))
        tg["fig_alpha"] = present * (0.25 if hook == "void" else 1.0)
        tg["smear"] = 2 + 19 * (0.35 * O + 0.35 * N + 0.3 * inten) * (1.6 if phase == "approach" else 1.0) * (0.5 if hook == "mirror" else 1.0)
        tg["twist"] = (N - 0.3) * 1.3 * (1.0 if hook in ("flesh", "inverted") else 0.4) + (0.8 if phase == "release" else 0)
        tg["swipe"] = math.sin(self.t * 0.05 + self.rng.random()) * 0.5
        tg["cage"] = (1.0 if hook == "flesh" else 0.35 if hook in ("inverted", "scrawl") else 0.0) * (0.6 + 0.4 * C)
        if phase == "profiling":
            tg["cage"] = max(tg["cage"], 0.8)
        tg["cage_jit"] = (1 - C) * 0.8
        tg["stroke_rate"] = (6 + 50 * inten) * (2.5 if hook == "inverted" else 1.0) * present * (0 if hook == "void" else 1)
        tg["flicker"] = N * inten * (1.0 if phase in ("hook", "release") else 0.3)
        tg["glitch"] = max(0.0, N - 0.45) * 1.8 * inten
        tg["flip"] = 1.0 if (hook == "inverted" or getattr(self, "steer_flip", False) or (phase == "release" and O > 0.6)) else 0.0
        tg["scale"] = (1.55 if hook == "mirror" else 0.85 + 0.35 * E)
        tg["ground_lum"] = (0.55 if phase == "idle" else 1.0) * (0.7 + 0.45 * E if hook != "void" else 1.0)
        tg["mark_rate"] = (0.15 + 0.6 * inten + 0.4 * E) * (1.6 if hook == "scrawl" else 0.15 if hook == "void" else 1.0) * (1.8 if phase == "profiling" else 1.0)
        tg["jitter"] = 0.15 + 0.55 * (1 - C)
        tg["text_fade"] = 0.998 if hook == "scrawl" else 0.993
        tg["scan"] = 1.0 if phase == "profiling" else 0.0
        # tilt: fast but smooth, so moving the phone feels like moving the picture
        kt = 1 - math.exp(-dt * 8)
        self.tilt[0] += (self.tilt_in[0] - self.tilt[0]) * kt
        self.tilt[1] += (self.tilt_in[1] - self.tilt[1]) * kt
        te = self.tilt_energy
        self.tilt_energy *= math.exp(-dt * 2.5)
        tg["swipe"] += self.tilt[0] * 1.3
        tg["scale"] *= 1.0 + 0.22 * self.tilt[1]   # forward/back tilt = zoom
        tg["smear"] += 14 * te
        tg["glitch"] += 0.6 * te
        k = 1 - math.exp(-dt * 1.6)
        for key, v in tg.items():
            self.p[key] = _lerp(self.p[key], v, k if key != "flip" else 1 - math.exp(-dt * 0.7))
        self.oc, self.phase, self.pt, self.inten = oc, phase, pt, inten

    # ---- layers -----------------------------------------------------------
    def _draw_ground(self):
        hook = self.hook
        key = (hook, tuple(self.pal[2]), tuple(self.pal[1]), round(self.p["ground_lum"], 2))
        if key != self.ground_key:
            self.ground = self._make_ground(hook)
            self.ground_key = key
        self.low.blit(self.ground, (0, 0))
        if hook == "void":
            pulse = 0.5 + 0.5 * math.sin(self.t * 2 * math.pi / 6.0)
            r = int(self.H * (0.25 + 0.15 * pulse))
            col = [int(c * (0.15 + 0.25 * pulse)) for c in self.pal[2]]
            c = (int(self.W / 2 + self.tilt[0] * self.W * 0.3), int(self.H / 2 + self.tilt[1] * self.H * 0.3))
            pygame.draw.circle(self.low, col, c, r)

    def _make_ground(self, hook):
        W, H = self.W, self.H
        p = self.pal
        lum = self.p["ground_lum"]
        rng = np.random.default_rng(zlib.crc32(hook.encode()))
        n = rng.random((W // 32 + 2, H // 8 + 2)).astype(np.float32)
        n = np.repeat(np.repeat(n, 32, 0), 8, 1)[:W, :H]
        n = (n + np.roll(n, 9, 0) + np.roll(n, 5, 1)) / 3
        tex = (0.9 + 0.2 * n)[..., None]
        if hook == "void":
            base = np.array(p[0], np.float32)[None, None, :] * 0.6 + 4
            arr = np.repeat(np.repeat(base, W, 0), H, 1) * tex
        elif hook == "scrawl":
            base = np.array(p[2], np.float32)
            arr = np.ones((W, H, 3), np.float32) * base * tex
            # rough colour patches like painted-over plywood
            for i in range(7):
                x0 = rng.integers(0, W - 60); y0 = rng.integers(0, H - 40)
                w = rng.integers(40, 180); h = rng.integers(25, 120)
                col = np.array(p[[3, 4, 1, 3, 4, 2, 1][i]], np.float32)
                arr[x0:x0 + w, y0:y0 + h] = arr[x0:x0 + w, y0:y0 + h] * 0.25 + col * 0.75 * tex[x0:x0 + w, y0:y0 + h]
        else:
            top = np.array(p[2], np.float32)
            floor = np.array(p[1], np.float32) * 0.8 + np.array(p[2], np.float32) * 0.2
            horizon = int(H * (0.70 if hook != "mirror" else 0.86))
            arr = np.empty((W, H, 3), np.float32)
            arr[:, :horizon] = top
            arr[:, horizon:] = floor
            arr *= tex
            if hook == "mirror":
                # dark room with a soft column of light: intimate, close
                X = np.arange(W, dtype=np.float32)[:, None]
                arr *= (0.45 + 0.85 * np.exp(-((X - W / 2) / (W * 0.30)) ** 2))[..., None]
        arr *= lum
        surf = pygame.Surface((W, H))
        pygame.surfarray.blit_array(surf, np.clip(arr, 0, 255).astype(np.uint8))
        if hook in ("flesh", "inverted"):
            # the dais / rug ellipse the figure sits on
            dcol = [int(c * 0.55) for c in p[1]]
            pygame.draw.ellipse(surf, dcol, (W * 0.30, H * 0.78, W * 0.40, H * 0.14))
            pygame.draw.ellipse(surf, [min(255, int(c * 1.1)) for c in p[3]], (W * 0.30, H * 0.78, W * 0.40, H * 0.14), 2)
        if self.bank and hook in self.bank:
            img = self.rng.choice(self.bank[hook])
            img = pygame.transform.smoothscale(img, (W, H))
            img.set_alpha(110)
            surf.blit(img, (0, 0))
        return surf

    def _fig_rect(self):
        sc = self.p["scale"]
        h = int(self.H * 0.92 * sc)
        w = int(h * self.fig.w / self.fig.h)
        x = (self.W - w) // 2 + int(math.sin(self.t * 0.13) * self.W * 0.03 + self.tilt[0] * self.W * 0.16)
        y = self.H - h - int(self.H * 0.06) if self.hook != "mirror" else self.H - h + int(self.H * 0.38)
        y += int(self.tilt[1] * self.H * 0.08)
        return pygame.Rect(x, y, w, h)

    def _lut(self):
        oc = self.oc
        key = (tuple(map(tuple, self.pal)), round(oc["A"], 1), round(oc["N"], 1), self.hook)
        if key != self.lut_key:
            raw = 0.35 + 0.5 * oc["N"] * (1 - 0.5 * oc["A"])
            cold = 0.6 if self.hook in ("mirror", "void") else max(0.0, 0.5 - oc["A"]) * 0.6
            if self.hook == "scrawl":
                cold = 0.85  # skeletal, chalky
            self.lut = flesh_lut(self.pal, raw, cold)
            self.lut_key = key
        return self.lut

    def _draw_figure(self):
        self._fig_cache = None
        if not self.fig.ready or self.p["fig_alpha"] < 0.02:
            return
        rgb, a, ang = self.fig.render(
            self.t, self.p["smear"], self.p["twist"], self.p["swipe"], self._lut(),
            self.p["fig_alpha"], flip_v=self.p["flip"] > 0.5, flip_h=self.hook == "mirror")
        pygame.surfarray.blit_array(self.fig_surf, rgb)
        alpha = pygame.surfarray.pixels_alpha(self.fig_surf)
        alpha[:] = a
        del alpha
        r = self._fig_rect()
        self._fig_cache = (rgb, a, ang, r)
        self.low.blit(self.paint, (0, 0))
        fs = pygame.transform.smoothscale(self.fig_surf, r.size)
        ang_deg = -self.tilt[0] * 28
        if abs(ang_deg) > 0.5:  # the phone's tilt leans the body
            fs = pygame.transform.rotate(fs, ang_deg)
            self.low.blit(fs, fs.get_rect(center=r.center))
        else:
            self.low.blit(fs, r.topleft)
        if self.hook == "scrawl":
            # the machine's reading of the body, scratched on by hand
            ink = self.pal[0]
            rng = random.Random(int(self.t * 3))
            fx, fy = self.fig.face
            fx = r.left + fx / self.fig.w * r.w
            if self.p["flip"] > 0.5:
                fy = self.fig.h - fy
            fy = r.top + fy / self.fig.h * r.h
            fw = r.w * 0.42
            scrawl.draw_face_box(self.low, (fx - fw / 2, fy - fw * 0.6, fw, fw * 1.2), ink, rng, 2,
                                 "%.2f" % (0.5 + 0.45 * self.inten), 9)
            pygame.draw.line(self.low, ink, (r.left + r.w * 0.1, r.top + r.h * 0.7), (r.right - r.w * 0.1, r.top + r.h * 0.7), 1)

    def _draw_paint(self, dt):
        # fade the stroke canvas; slower while the visitor is held by the hook
        keep = 0.996 if self.phase == "hook" else 0.985
        a = int(255 * keep ** (dt * 30))
        self.paint.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
        if not getattr(self, "_fig_cache", None):
            return
        rgb, al, ang, r = self._fig_cache
        n = int(self.p["stroke_rate"] * dt * 3)
        if n <= 0:
            return
        ys, xs = None, None
        idx = np.argwhere(al > 90)
        if len(idx) == 0:
            return
        pick = idx[np.random.randint(0, len(idx), n)]
        sx = r.w / self.fig.w
        sy = r.h / self.fig.h
        thick = 3 if self.hook != "inverted" else 6
        for fx, fy in pick:
            col = rgb[fx, fy]
            col = (int(col[0]), int(col[1]), int(col[2]), 235)
            a0 = float(ang[fx, fy]) + random.uniform(-0.4, 0.4)
            L = random.uniform(5, 26) * (1.5 if self.hook == "inverted" else 1)
            x0 = r.left + fx * sx; y0 = r.top + fy * sy
            x1 = x0 + math.cos(a0) * L; y1 = y0 + math.sin(a0) * L
            pygame.draw.line(self.paint, col, (x0, y0), (x1, y1), random.randint(2, thick + 2))

    def _draw_cage(self):
        amt = self.p["cage"]
        if amt < 0.05:
            return
        r = self._fig_rect()
        cx, cy = r.centerx, r.centery + r.h * 0.05
        shrink = 1.0 - 0.25 * self.p["scan"]
        hw, hh, hd = r.w * 0.75 * shrink, r.h * 0.52 * shrink, r.w * 0.6 * shrink
        yaw = self.t * 0.07 * (1.3 - self.oc["C"]) + 0.4 + self.tilt[0] * 1.1
        pitch = -0.18 + self.tilt[1] * 0.6
        f, d = 520.0, 900.0
        jit = self.p["cage_jit"] * 3
        verts = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    x, y, z = sx * hw, sy * hh, sz * hd
                    x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
                    y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
                    k = f / (d + z)
                    verts.append((cx + x * k + random.uniform(-jit, jit), cy + y * k + random.uniform(-jit, jit)))
        col = tuple(int(c) for c in self.pal[4])
        lw = 1 if amt < 0.6 else 2
        for i in range(8):
            for j in range(i + 1, 8):
                if bin(i ^ j).count("1") == 1:
                    pygame.draw.line(self.low, col, verts[i], verts[j], lw)
                    if self.p["cage_jit"] > 0.45:
                        o = random.uniform(1, 3)
                        pygame.draw.aaline(self.low, col, (verts[i][0] + o, verts[i][1]), (verts[j][0] + o, verts[j][1] + o))

    # ---- words ------------------------------------------------------------
    def _words(self):
        s = self.state
        words = [str(w) for w in (s.get("words") or [])] + self.extra_words
        oc = self.oc
        if self.phase == "idle":
            return LEX_IDLE
        if self.phase == "profiling":
            data = ["%s %.2f" % (k, oc[k]) for k in "OCEAN"]
            data += ["DWELL %dS" % int(self.pt + 3), "CONFIDENCE %d%%" % int(40 + 50 * self.inten),
                     "SUBJECT %s" % str(s.get("visitor_id", "?"))[-4:].upper()]
            return words + data
        tone = LEX_TENDER if oc["A"] >= 0.5 else LEX_COLD
        return words * 3 + tone + LEX_JEST + (LEX_COLD if oc["N"] > 0.6 else [])

    def _harvest(self):
        """Cut whatever was just drawn on the scratch sheet into a mark."""
        area = getattr(self, "_dirty", None) or self.text.get_rect()
        area = area.clip(self.text.get_rect())
        self._dirty = None
        if not area.w or not area.h:
            return
        r = self.text.subsurface(area).get_bounding_rect().move(area.topleft)
        if r.w and r.h:
            self.marks.append([self.text.subsurface(r).copy(), r.topleft, self.t])
            self.text.fill((0, 0, 0, 0), r)
        if len(self.marks) > 60:
            del self.marks[0]

    def _blit_marks(self, surface):
        fade = self.p["text_fade"]
        wipe_k = 1.0
        if self.wipe_t is not None:
            wipe_k = max(0.0, 1 - (self.t - self.wipe_t) / 1.5)
        sx = surface.get_width() / self.TW
        keep = []
        for m in self.marks:
            a = 255 * fade ** ((self.t - m[2]) * 30) * wipe_k
            if a < 6:
                continue
            keep.append(m)
            m[0].set_alpha(int(a))
            if sx == 1:
                surface.blit(m[0], m[1])
            else:  # demo window smaller than 1080p
                w, h = m[0].get_size()
                surface.blit(pygame.transform.smoothscale(m[0], (max(1, int(w * sx)), max(1, int(h * sx)))),
                             (int(m[1][0] * sx), int(m[1][1] * sx)))
        self.marks = keep

    def _update_text(self, dt):
        if self.hook == "void":
            self._void_line()
            return
        if self.t < self.next_mark:
            return
        self.next_mark = self.t + random.expovariate(max(0.05, self.p["mark_rate"]))
        self._add_mark()
        self._harvest()

    def _void_line(self):
        if self.t < self.next_mark:
            return
        self.next_mark = self.t + 7.0
        self.marks = []
        w = random.choice(self._words())
        size = 14 * self.k
        x = (self.TW - scrawl.text_width(w, size)) / 2
        scrawl.draw_text(self.text, w, x, self.TH * 0.82, size, tuple(self.pal[4]) + (255,), random, 0.1, self._lw(2))
        self._dirty = pygame.Rect(0, int(self.TH * 0.82 - size), self.TW, int(size * 3))
        self._harvest()

    def _lw(self, w):
        """line width scaled from internal pixels to output pixels"""
        return max(1, int(round(w * self.k * 0.8)))

    def _ink(self):
        p = self.pal
        if self.hook == "scrawl":
            return random.choice([p[0], p[0], p[0], p[0], p[1], p[3]])
        light = sum(p[2]) / 3 > 140
        return random.choice([p[0], p[0], p[1]] if light else [p[4], p[4], p[4], p[3]])

    def _add_mark(self):
        W, H = self.TW, self.TH
        k = self.k
        rng = random
        oc = self.oc
        ink = tuple(int(c) for c in self._ink()) + (255,)
        fr = self._fig_rect()
        r = pygame.Rect(int(fr.x * k), int(fr.y * k), int(fr.w * k), int(fr.h * k))
        roll = rng.random()
        if roll < 0.06 + 0.08 * oc["E"]:
            x = rng.uniform(40 * k, W - 40 * k); y = rng.uniform(40 * k, H * 0.45)
            cw = rng.uniform(28, 60) * k
            kind = rng.choice(["reticle", "barcode", "tally", "redact"])
            if kind == "reticle":
                scrawl.draw_reticle(self.text, x, y, cw * 0.5, ink, rng, self._lw(2))
            elif kind == "barcode":
                scrawl.draw_barcode(self.text, x - cw, y - cw * 0.3, cw * 2, cw * 0.6, ink, rng)
            elif kind == "tally":
                scrawl.draw_tally(self.text, x - cw, y - cw * 0.4, cw * 0.8, rng.randint(3, 17), ink, rng, self._lw(2))
            else:
                scrawl.draw_redaction(self.text, x - cw, y - cw * 0.2, cw * 2.4, cw * 0.4, ink, rng)
            self._dirty = pygame.Rect(int(x - cw * 2), int(y - cw * 1.2), int(cw * 5), int(cw * 2.4))
            return
        if roll < 0.13 and oc["O"] > 0.5:
            x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
            x1, y1 = x0 + rng.uniform(-300, 300) * k / 3, y0 + rng.uniform(-200, 200) * k / 3
            scrawl.draw_arrow(self.text, x0, y0, x1, y1, ink, rng, self._lw(2))
            self._dirty = pygame.Rect(int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0))).inflate(40, 40)
            return
        word = rng.choice(self._words())
        size = rng.uniform(14, 22 + 26 * oc["E"]) * (1.25 if self.hook == "scrawl" else 1.0) * k
        tw = scrawl.text_width(word, size)
        for _ in range(6):
            if oc["C"] > 0.65:  # orderly visitor: words line up on a grid
                x = round(rng.uniform(10 * k, max(11 * k, W - tw - 10 * k)) / (40 * k)) * 40 * k + 10 * k
                y = round(rng.uniform(10 * k, H - size - 10 * k) / (34 * k)) * 34 * k + 8 * k
            else:
                x = rng.uniform(6 * k, max(7 * k, W - tw - 6 * k)); y = rng.uniform(6 * k, H - size - 6 * k)
            if self.hook == "scrawl" or not r.inflate(-r.w * 0.3, -r.h * 0.2).colliderect((x, y, tw, size)):
                break
        if self.hook == "mirror" and self.phase == "hook":
            word = rng.choice(["YOU", "ONLY YOU", "STAY", "CLOSER", word])
        bbox = scrawl.draw_text(self.text, word, x, y, size, ink, rng, self.p["jitter"],
                                self._lw(3 if size > 24 * k else 2),
                                slant=rng.uniform(-0.15, 0.15) - 0.25 * self.tilt[0])
        self._dirty = pygame.Rect(int(x - size), int(y - size), int(tw + size * 3), int(size * 3))
        crossed = rng.random() < 0.08 + 0.3 * oc["N"] + (0.35 if self.phase == "release" else 0)
        if crossed:
            scrawl.cross_out(self.text, bbox, ink, rng, self._lw(3))
        elif rng.random() < 0.2:
            # a hand-written record number after the word, like a file tag
            scrawl.draw_text(self.text, "#%04d" % rng.randrange(10000), bbox.right + size * 0.4, bbox.top + size * 0.35,
                             size * 0.5, ink, rng, 0.2, self._lw(1))

    # ---- wipe and finish --------------------------------------------------
    def _draw_wipe(self):
        if self.wipe_t is None:
            return
        k = (self.t - self.wipe_t) / 2.5
        if k >= 1:
            self.paint.fill((0, 0, 0, 0))
            self.marks = []
            self.wipe_t = None
            return
        col = tuple(int(c) for c in self.pal[2])
        # broad house-painter strokes across everything
        n = int(6 + 30 * k)
        for i in range(n):
            y = (i * 37 + int(self.wipe_t * 100)) % self.H
            w = int(self.W * min(1, k * 1.6 + (i % 5) * 0.05))
            pygame.draw.line(self.low, col, (0, y), (w, y + random.randint(-6, 6)), 26)

    def _finish(self):
        p = self.p
        if p["scan"] > 0.05:
            y = int((self.t * 70) % self.H)
            pygame.draw.line(self.low, (235, 235, 235), (0, y), (self.W, y), 1)
            pygame.draw.line(self.low, (120, 255, 140), (0, y + 2), (self.W, y + 2), 1)
        if p["glitch"] > 0.05 and random.random() < p["glitch"] * 0.5:
            arr = pygame.surfarray.pixels3d(self.low)
            for _ in range(random.randint(1, 4)):
                y0 = random.randint(0, self.H - 20); h = random.randint(4, 30)
                arr[:, y0:y0 + h] = np.roll(arr[:, y0:y0 + h], random.randint(-40, 40), axis=0)
            del arr
        if p["flicker"] > 0.05 and random.random() < p["flicker"] * 0.25:
            v = random.randint(40, 140)
            self.low.fill((v, v, v), special_flags=pygame.BLEND_RGB_SUB)
        gx = random.randint(0, 63); gy = random.randint(0, 63)
        self.low.blit(self.grain, (-gx, -gy), special_flags=pygame.BLEND_RGB_SUB)

    def _make_grain(self):
        rng = np.random.default_rng(11)
        g = (rng.random((self.W + 64, self.H + 64)) ** 6 * 40).astype(np.uint8)
        arr = np.repeat(g[..., None], 3, 2)
        s = pygame.Surface((self.W + 64, self.H + 64))
        pygame.surfarray.blit_array(s, arr)
        return s

    def _load_bank(self, path):
        """Optional pre-generated images: bank/<hook>/*.png|jpg, used as faint
        underpainting behind that hook's ground. Made offline on the Mac."""
        path = path or os.path.join(os.path.dirname(__file__), "bank")
        out = {}
        if not os.path.isdir(path):
            return out
        for hook in HOOKS:
            d = os.path.join(path, hook)
            if not os.path.isdir(d):
                continue
            imgs = []
            files = sorted(f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg")))
            # newest half plus a random sample of the rest, bounded for RAM and start-up time
            half = self.bank_max // 2
            newest, older = files[-half:] if half else [], files[:-half] if half else files
            files = newest + random.sample(older, min(len(older), self.bank_max - len(newest)))
            for fn in files:
                if True:
                    try:
                        im = pygame.image.load(os.path.join(d, fn))
                        imgs.append(pygame.transform.smoothscale(im, (self.W, self.H)))
                    except Exception:
                        pass
            if imgs:
                out[hook] = imgs
        return out
