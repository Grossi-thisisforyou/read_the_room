"""INFINITE JEST visuals: one projector, one visitor at a time.

Layers, back to front. The painting is made at a low internal resolution
(default 640x360) and scaled up; words and surveillance marks are drawn at the
full output resolution on top so they stay sharp.

  1. ground   a hand-painted flat field (room with floor, wall, deep field,
              column of light, or a three-panel triptych), with a slow hue
              drift (glaze) and a light pool; moves a little with the tilt
  2. under    a fading paint layer behind the figure (painted shadows)
  3. props    painted dais, plinth, bench or rug
  4. figures  the visitor from the N900 camera, smeared and coloured as flesh,
              placed by the current scene variant (one to four instances:
              whole body, head, face, eyes or mouth crops, echoes of the
              visitor a few seconds ago, upside down, lying down, mirrored)
  5. over     a fading paint layer on top: bristle strokes that follow the
              body's contours, and arc swipes that drag paint across the face
  6. cage     box, arch, ring, rail or frame lines
  7. finish   scan line while profiling, glitch bursts, flicker, grain
  8. marks    (full resolution) hand-scrawled words, record numbers, face
              boxes, barcodes, tallies, redaction bars, graphs, the big line,
              the visitor's file (reveal) at the end of the visit

Scenes come from scenes.py: several variants per hook, chosen per visitor and
rotated during long hook phases, with painted transitions in between.
All look parameters glide toward targets computed from the latest state.
"""
import math
import os
import random
import time
import zlib

import numpy as np
import pygame

from . import bankimg, brush, ground, palettes, scenes, scrawl
from .governor import LEVELS as _QUALITY, Governor
from .corpus import BLOCK as _BLOCK, WallText
from .figure import Figure, _percentiles, flesh_lut, flesh_luts, ghost_body  # noqa: F401 (flesh_lut kept for callers)

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")

# Words for when neither the language model nor the corpus has any.
LEX_TENDER = ["MADE FOR YOU", "STAY", "ONLY YOU", "WE SAW YOU", "YOURS", "TAILORED",
              "SKIN", "CLOSER", "YOU ARE SEEN", "INTIMACY", "FOR YOU ONLY", "HOLD STILL",
              "KEEP LOOKING", "WE LIKE THIS ONE", "SOFT TARGET"]
LEX_COLD = ["DATA", "PROFILE", "SUBJECT", "HARVEST", "SCORE", "PREDICTED", "CONSENT",
            "SAMPLE", "OPTED IN", "TARGET", "RETAINED", "LEAKED", "SEGMENT", "HOOKED",
            "INVENTORY", "RAW MATERIAL", "PROPERTY OF", "MONETIZE", "NO NAME", "BEHAVIOUR"]
LEX_JEST = ["INFINITE", "JEST", "ENTERTAINMENT", "LOOP", "MORE", "AGAIN", "ONE MORE",
            "THE ENTERTAINMENT", "DONT LOOK AWAY", "PLEASURE"]
LEX_OPTOUT = ["NOT READING YOU", "NOTHING KEPT", "EYE CLOSED"]
LEX_IDLE = ["NOBODY", "WAITING", "EMPTY ROOM", "NEXT", "COME IN", "WE ARE READY"]
LEX_DATA = ["DWELL", "GRIP", "TILT", "MOTION", "HESITATION", "RETURN RATE", "FACE 1",
            "NO MATCH", "LOGGED", "FLAGGED", "REVIEW", "RETAIN 30D", "ANOMALY", "STILL"]


def _lerp(a, b, k):
    return a + (b - a) * k


def _clamp(x, lo=0.0, hi=1.0):
    if x != x:  # NaN
        return lo
    return lo if x < lo else hi if x > hi else x


def _num(v, default=0.0):
    """A finite float from whatever arrived (strings, None, NaN, junk)."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def _text(v, limit=120):
    if v is None or isinstance(v, (dict, list, tuple, set)):
        return ""
    return str(v)[:limit]


def _alpha(surf, a):
    """set_alpha that drops the surface alpha of an opaque (non-SRCALPHA) surface
    at 255: blitted with alpha 255 it takes SDL's slow blend path (~20x slower).
    (Not for SRCALPHA surfaces: set_alpha(None) there turns blending off.)"""
    if a >= 255 and not surf.get_flags() & pygame.SRCALPHA:
        surf.set_alpha(None)
    else:
        surf.set_alpha(min(255, max(0, int(a))))


def _smooth(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


class _Euro:
    """One-euro filter: smooth when the phone is held still, immediate when it
    moves fast. Gives the tilt a direct feel (well under 100 ms) without
    jitter from the 10 Hz state updates."""

    def __init__(self, min_cut=2.2, beta=6.0, d_cut=8.0):
        self.min_cut, self.beta, self.d_cut = min_cut, beta, d_cut
        self.x = None
        self.dx = 0.0

    @staticmethod
    def _a(cut, dt):
        tau = 1.0 / (2 * math.pi * cut)
        return 1.0 / (1.0 + tau / max(dt, 1e-4))

    def __call__(self, raw, dt):
        if self.x is None:
            self.x = raw
            return raw
        d = (raw - self.x) / max(dt, 1e-4)
        self.dx += (d - self.dx) * self._a(self.d_cut, dt)
        cut = self.min_cut + self.beta * abs(self.dx)
        self.x += (raw - self.x) * self._a(cut, dt)
        return self.x


class _Inst:
    """Where one figure instance sits on screen, and how to map figure-buffer
    pixels to screen pixels (for strokes, swipes and face boxes)."""

    def __init__(self, spec, crop, center, height, rot, mirror):
        self.spec = spec
        self.crop = crop                  # (x, y, w, h) in figure-buffer pixels
        self.cx, self.cy = center
        self.th = max(4, int(height))
        self.tw = max(4, int(height * crop[2] / max(1, crop[3])))
        self.scale = self.th / max(1, crop[3])
        self.rot = rot
        self.mirror = mirror
        r = math.radians(rot)
        self.c, self.s = math.cos(r), math.sin(r)

    def to_screen(self, bx, by):
        u = (np.asarray(bx, np.float32) - self.crop[0]) * self.scale - self.tw / 2
        v = (np.asarray(by, np.float32) - self.crop[1]) * self.scale - self.th / 2
        if self.mirror:
            u = -u
        # pygame rotates counter-clockwise on screen (y down)
        x = u * self.c + v * self.s
        y = -u * self.s + v * self.c
        return x + self.cx, y + self.cy

    def rect(self):
        w = abs(self.tw * self.c) + abs(self.th * self.s)
        h = abs(self.tw * self.s) + abs(self.th * self.c)
        return pygame.Rect(int(self.cx - w / 2), int(self.cy - h / 2), int(w), int(h))


class Visuals:
    def __init__(self, size, config=None):
        config = config or {}
        self.config = config
        self.size = tuple(size)
        iw, ih = config.get("internal_size", (640, 360))
        self.W, self.H = int(iw), int(ih)
        self.u = self.W / 640.0                     # unit: one pixel at 640x360
        self.M = int(24 * self.u)                   # ground margin for parallax
        self.smooth_cfg = self.smooth = bool(config.get("smooth_scale", True))
        self.upscale_full = bool(config.get("upscale_full", False))
        self._mid = None
        self.base_internal = (self.W, self.H)
        # quality governor: steps the picture down when frames run over budget (see governor.py)
        self.governor = Governor(_num(config.get("frame_budget_ms", 28.0), 28.0), smooth=self.smooth_cfg,
                                 can_shrink=self.W * self.H > 480 * 270)
        self.q = dict(_QUALITY[0])
        self.fig = Figure(int(config.get("figure_w", 160)), int(config.get("figure_h", 180)))
        self.low = pygame.Surface((self.W, self.H))
        self.under = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        self.over = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        self.cover = pygame.Surface((self.W, self.H), pygame.SRCALPHA)  # the wipe's house paint
        # where each paint layer may hold paint (None: empty): blits and fades touch only that
        self.over_rect = self.under_rect = self.cover_rect = None
        self.over_faded = self.under_faded = 0
        self.tooth = brush.make_tooth(self.W, self.H, 9)
        self.prng = np.random.default_rng(5)       # paint randomness
        # words at the full output resolution
        self.TW, self.TH = self.size
        self.k = self.TW / self.W
        self.text = pygame.Surface((self.TW, self.TH), pygame.SRCALPHA)
        self.marks = []  # [surface, (x, y), birth time]
        self._dirty = None
        self.tilt = [0.0, 0.0]
        self.tilt_in = [0.0, 0.0]
        self._eu = (_Euro(), _Euro())
        self.tilt_energy = 0.0
        self.steer_flip = False
        self.flipk = 0.0
        self.shake_t = -10.0
        self.last_shake = -10.0
        self.fig_surf = pygame.Surface((self.fig.w, self.fig.h), pygame.SRCALPHA)
        self.fig.shifts = tuple(self.fig_surf.get_shifts())   # the figure writes packed pixels straight in
        self.echoes = []          # the visitor a few seconds ago (memory only)
        self.echo_t = 0.0
        self.ghosts = []          # screen-space motion trail of the main figure
        self.last_center = None
        self.grain = self._make_grain()
        self.t = 0.0
        self.state = {}
        self.extra_words = []
        self.next_mark = 0.0
        self.wipe_t = None
        self.rng = random.Random(1)
        self.vseed = 1
        self.visitor = None
        self.visits = 0
        self.lut = None
        self.lut_key = None
        self.bank_dir = config.get("bank_dir")
        self.bank_max = int(config.get("bank_max_per_hook", 40))
        self.bank_reload_s = float(config.get("bank_reload_s", 600))
        self.bank_loader = bankimg.Loader()
        self.bank = self._load_bank(self.bank_dir)
        self.bank_loaded = time.monotonic()
        self.corpus = WallText(config)
        self.scene_cut = None
        self.pal_name = None
        # while a visitor is present, keep this file fresh so the overnight image
        # generator (bank_gen) pauses and leaves the CPU to picture and sound
        self.busy_file = config.get("busy_file", "/tmp/infinite_jest_busy")
        self.busy_touched = 0.0
        self.p = dict(fig_alpha=0.0, smear=6.0, twist=0.0, swipe=0.0, cage=0.7, cage_jit=0.2,
                      stroke_rate=0.0, flicker=0.0, glitch=0.0, scale=1.0, ground_lum=1.0,
                      mark_rate=0.3, jitter=0.35, text_fade=0.996, scan=0.0, hinge=0.0, reveal=0.0)
        self.hook = "flesh"
        self.hook_req, self.hook_req_t = "flesh", 0.0
        self.hook_hold_s = _num(config.get("hook_hold_s", 6.0), 6.0)
        self.min_scene_s = _num(config.get("min_scene_s", 20.0), 20.0)
        self.hook_fade_s = _num(config.get("hook_fade_s", 2.5), 2.5)
        self._hook_force = False
        self._hold_flip = False
        self._hold_phase, self._hold_vid = "idle", None
        self.scene_t = 0.0
        self.phase = "idle"
        self.pt = 0.0
        self.inten = 0.4
        self.oc = {k: 0.5 for k in "OCEAN"}
        self.pal = palettes.get("triptych")
        self.frame_ms = 0.0
        # scenes
        self.scene = None
        self.scene_key = None
        self.scene_pal = self.pal
        self.ground_surf = None
        self.glaze_surf = None
        self.glaze_period = 60.0
        self.light = None
        self.props = []
        self.pending = None
        self.rotation = 0
        self.next_rotation = 35.0
        self.snap = None
        self.trans = None
        self.main = None
        self.insts = []
        self.swipes = []
        self.ghost_feed = False
        self.ghost_t = 0.0
        self.hist = []            # (motion, tilt energy) samples, one per half second, this visit only
        self.hist_t = 0.0
        self.big_cache = None
        self.reveal_cache = None
        self._reveal_job = None
        self._gcomp = self._gcomp_key = None
        self._light_s = self._light_key = None
        self.fade_acc = 0.0
        self.ufade_acc = 0.0
        self._stroke_debt = 0
        self.stroke_cap = int(config.get("stroke_cap", 4))   # figure strokes painted per frame at most (v2: 10)
        self._wipe_queue = None
        self._install_now(("idle",), scenes.idle_scene(random.Random(0)), self.pal)

    # ---- engine interface -------------------------------------------------
    def on_state(self, state):
        if not isinstance(state, dict):
            return
        if state.get("type") == "state" and isinstance(state.get("data"), dict):
            state = state["data"]
        vid = state.get("visitor_id")
        if vid != self.visitor:
            self.visitor = vid
            self.vseed = zlib.crc32(str(vid).encode())
            self.rng = random.Random(self.vseed)
            self.rotation = 0
            self.next_rotation = 30 + self.rng.uniform(0, 15)
            if vid:
                self.visits += 1
        if state.get("phase") == "wipe" and self.state.get("phase") != "wipe":
            self.on_wipe()
        elif state.get("opted_out") and not self.state.get("opted_out"):
            self.on_wipe()          # they said no: their painted body goes now, not at the wipe
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
        """Optional: raw phone sensor dict (contract kind "phone"). The
        engine's state.steer wins; raw tilt is only used when no steer has
        arrived for a second (two sources at once would make the figure flicker)."""
        if isinstance(data, dict):
            self._read_tilt(data, raw=True)

    def _read_tilt(self, d, raw=False):
        st = d.get("steer")  # contract 1.3: {x, y, flip, shake}
        if isinstance(st, dict):
            self.tilt_in = [_clamp(_num(st.get("x")), -1, 1), _clamp(_num(st.get("y")), -1, 1)]
            self.steer_flip = st.get("flip") is True or st.get("flip") in (1, "true", "True")
            self.tilt_energy = max(self.tilt_energy, _clamp(_num(st.get("shake"))))
            self.steer_t = self.t
            return
        if raw and self.t - getattr(self, "steer_t", -99.0) < 1.0:
            return
        t = d.get("tilt")
        if isinstance(t, dict):
            if "x" in t or "y" in t:          # engine format, -1..1
                self.tilt_in = [_clamp(_num(t.get("x")), -1, 1), _clamp(_num(t.get("y")), -1, 1)]
            elif "gamma" in t or "beta" in t:  # raw degrees from the phone
                beta = _num(t.get("beta"))
                self.tilt_in = [_clamp(_num(t.get("gamma")) / 60, -1, 1), _clamp(beta / 60, -1, 1)]
                self.steer_flip = abs(beta) > 150
        for key in ("tilt_energy", "shake"):
            if key in d:
                self.tilt_energy = max(self.tilt_energy, _clamp(_num(d[key])))

    def on_frame(self, frame):
        """frame: numpy [h, w] gray or [h, w, 3] RGB uint8 (N900 sends gray8)."""
        try:
            if self.ghost_feed:      # a real camera is back: forget the stand-in
                self.fig.wipe()
                self.ghost_feed = False
            self.fig.present = self.phase not in ("idle", "wipe")
            self.fig.push(frame)
        except Exception:
            pass

    def on_text(self, words):
        if isinstance(words, str):
            words = [words]
        try:
            self.extra_words = [_text(w, 60) for w in list(words)[-24:] if _text(w, 60).strip()]
        except TypeError:
            self.extra_words = []

    @property
    def paint(self):
        """The paint layer on top of the figure (painted from the visitor)."""
        self.over_rect = pygame.Rect(0, 0, self.W, self.H)   # someone may paint into it
        self.over_faded = 0
        return self.over

    def on_wipe(self):
        """Drop everything held about the visitor and paint the room over."""
        self.fig.wipe()
        # everything painted from the visitor's camera goes at once, not by fading
        self.over.fill((0, 0, 0, 0))
        self.under.fill((0, 0, 0, 0))
        self.over_rect = self.under_rect = None
        self._stroke_debt = 0
        self.fig_surf.fill((0, 0, 0, 0))
        self._fig_rgb = None
        self.snap = None
        self.trans = None
        self.echoes = []
        self.ghosts = []
        self.hist = []
        self.swipes = []
        self.extra_words = []
        self.main = None
        self.wipe_t = self.t
        if time.monotonic() - self.bank_loaded > self.bank_reload_s:  # pick up new overnight images and words
            # on a background thread, reading only new files; swapped in by _render
            self.bank_loader.start(self._bank_path(), self._bank_size(), self.bank_max, self.H,
                                   getattr(self.bank, "cache", {}))
            self.corpus.reload(self.config)
            self.bank_loaded = time.monotonic()

    def render(self, surface, dt):
        t0 = time.perf_counter()
        dt = min(max(_num(dt, 1 / 30), 0.0), 0.2)
        self.t += dt
        try:
            self._render(surface, dt)
        except Exception as e:  # the wall must never go dark because of one bad frame
            if os.environ.get("IJ_VISUALS_STRICT"):
                raise
            if not getattr(self, "_err_logged", False):
                import sys
                print("visuals: frame error (continuing): %r" % (e,), file=sys.stderr)
                self._err_logged = True
            try:
                pygame.transform.scale(self.low, surface.get_size(), surface)
            except Exception:
                pass
        ms = (time.perf_counter() - t0) * 1000
        self.frame_ms = self.frame_ms * 0.9 + ms * 0.1
        lvl = self.governor.observe(ms, self.t)
        if lvl is not None:
            try:
                self._apply_quality(lvl)
            except Exception as e:  # never let a quality change take the wall down
                if os.environ.get("IJ_VISUALS_STRICT"):
                    raise
                import sys
                print("visuals: quality change failed: %r" % (e,), file=sys.stderr)

    # ---- quality governor ---------------------------------------------------
    def _apply_quality(self, level):
        q = dict(_QUALITY[level])
        self.q = q
        self.smooth = self.smooth_cfg and q["smooth"]
        target = (480, 270) if q["small"] else self.base_internal
        if target != (self.W, self.H):
            self._resize(*target)

    def _resize(self, W, H):
        """Change the internal picture size while running. Everything sized to
        it is scaled over at once (the paint layers keep their paint); the
        current scene is then repainted at the new size in the background (same
        key: the same painting) and comes in with a transition."""
        sx = W / float(self.W)
        sy = H / float(self.H)
        self.W, self.H = int(W), int(H)
        self.u = self.W / 640.0
        self.M = int(24 * self.u)
        self.k = self.TW / self.W
        sm = pygame.transform.smoothscale
        self.low = pygame.Surface((self.W, self.H))
        for name in ("under", "over", "cover"):
            setattr(self, name, sm(getattr(self, name), (self.W, self.H)))
            r = getattr(self, name + "_rect")
            if r is not None:
                r = pygame.Rect(int(r.x * sx) - 2, int(r.y * sy) - 2, int(r.w * sx) + 4, int(r.h * sy) + 4)
                setattr(self, name + "_rect", r.clip(pygame.Rect(0, 0, self.W, self.H)))
        self.tooth = brush.make_tooth(self.W, self.H, 9)
        self.grain = self._make_grain()
        gs = (self.W + 2 * self.M, self.H + 2 * self.M)
        if self.ground_surf is not None:
            self.ground_surf = sm(self.ground_surf, gs)
        if self.glaze_surf is not None:
            self.glaze_surf = sm(self.glaze_surf, gs)
        if self.light is not None:
            n = max(8, int(self.light.get_width() * sy))
            self.light = pygame.transform.scale(self.light, (n, n))
        self.props = [(pd, sm(spr, (max(8, int(spr.get_width() * sx)), max(8, int(spr.get_height() * sy)))))
                      for pd, spr in self.props]
        if self.scene_cut is not None:
            self.scene_cut = sm(self.scene_cut, (max(2, int(self.scene_cut.get_width() * sy)),
                                                 max(2, int(self.scene_cut.get_height() * sy))))
        self.snap = None
        self.trans = None
        self.ghosts = []
        self.swipes = []
        self._wipe_queue = None
        self.last_center = None
        self._gcomp = self._gcomp_key = None
        self._light_s = self._light_key = None
        self._resized_key = self.scene_key
        self.scene_key = None            # repaint the same scene at the new size
        self.pending = None

    def _render(self, surface, dt):
        nb = self.bank_loader.poll()
        if nb is not None:              # a background reload finished: the next scene uses it
            self.bank = nb
        self._update_params(dt)
        self._camera(dt)
        self._schedule(dt)
        self._draw_ground()
        self._draw_figures(dt)
        self._paint(dt)
        if self.over_rect is not None:
            self.low.blit(self.over, self.over_rect.topleft, self.over_rect)
        if self.wipe_t is not None and self.cover_rect is not None:
            self.low.blit(self.cover, self.cover_rect.topleft, self.cover_rect)
        self._draw_cage()
        self._draw_transition()
        self._finish(dt)
        self._upscale(surface)
        self._update_text(dt)
        self._blit_marks(surface)
        self._overlay(surface)

    def _upscale(self, surface):
        """The painting, scaled up to the output. Smooth scaling costs in
        proportion to the output's pixels (~3.2 ms for 640x360 -> 1080p on x86,
        about a quarter of a Pi 5 frame), so by default it smooth-scales to half
        the output size (still 1.5x the painting) and doubles that with a plain
        pixel copy: ~1.8 ms, the same picture to within ~2 levels on average
        (config "upscale_full": true for the single smooth scale)."""
        size = surface.get_size()
        if size == (self.W, self.H):
            surface.blit(self.low, (0, 0))
        elif not self.smooth:
            pygame.transform.scale(self.low, size, surface)
        else:
            mid = (size[0] // 2, size[1] // 2)
            if (not self.upscale_full and size[0] % 2 == 0 and size[1] % 2 == 0
                    and mid[0] >= self.W * 1.25 and mid[1] >= self.H * 1.25):
                if self._mid is None or self._mid.get_size() != mid:
                    self._mid = pygame.Surface(mid)
                pygame.transform.smoothscale(self.low, mid, self._mid)
                pygame.transform.scale(self._mid, size, surface)
            else:
                pygame.transform.smoothscale(self.low, size, surface)

    # ---- state -> look ----------------------------------------------------
    def _ocean(self):
        o = self.state.get("ocean")
        if not isinstance(o, dict):
            o = {}
        return {k: _clamp(_num(o.get(k), 0.5)) for k in "OCEAN"}

    def _update_params(self, dt):
        s = self.state
        oc = self._ocean()
        O, C, E, A, N = (oc[k] for k in "OCEAN")
        phase = s.get("phase", "idle")
        if phase not in ("idle", "approach", "profiling", "hook", "release", "wipe"):
            phase = "idle" if not phase else "hook"
        pt = max(0.0, _num(s.get("phase_t"), 0.0))
        inten = _clamp(_num(s.get("intensity"), 0.4))
        hook = _text(s.get("hook")) or _text(s.get("scene")) or "flesh"
        if hook not in HOOKS:
            # unknown hook name: a stable choice among the five so it is never blank
            hook = HOOKS[zlib.crc32(str(hook).encode()) % 4]
        hook = self.hook = self._hold_hook(hook, phase, pt)
        pal = s.get("palette")
        name = palettes.pick_for(oc, hook)
        try:
            if pal:
                self.pal = palettes.get(pal)
                name = pal if isinstance(pal, str) else (pal.get("name") if isinstance(pal, dict) else None)
            else:
                self.pal = palettes.get(name)
        except Exception:
            self.pal = palettes.get(name)
        self.pal_name = name if isinstance(name, str) else None
        tg = {}
        # release now lasts long: the figure fades behind the visitor's file and holds
        present = {"idle": 0.0, "approach": _clamp(pt / 3.0), "profiling": 1.0, "hook": 1.0,
                   "release": max(0.3, 1 - pt / 10.0), "wipe": max(0.0, 0.3 - pt / 4.0)}.get(phase, 0.0)
        tg["fig_alpha"] = present
        tg["smear"] = 2 + 17 * (0.35 * O + 0.35 * N + 0.3 * inten) * (1.6 if phase == "approach" else 1.0)
        tg["twist"] = (N - 0.3) * 1.2 * (1.0 if hook in ("flesh", "inverted") else 0.4) + (0.6 if phase == "release" else 0)
        tg["swipe"] = math.sin(self.t * 0.05 + self.vseed % 7) * 0.5
        tg["cage"] = 0.6 + 0.4 * C
        tg["cage_jit"] = (1 - C) * 0.8
        tg["stroke_rate"] = (12 + 55 * inten) * present * (0.4 if phase == "release" else 1.0)
        tg["flicker"] = N * inten * (1.0 if phase == "hook" else 0.3)
        tg["glitch"] = max(0.0, N - 0.5) * 1.4 * inten
        tg["scale"] = 0.9 + 0.2 * E
        tg["mark_rate"] = (0.1 + 0.35 * inten + 0.25 * E) * (1.05 if hook == "scrawl" else 1.0) * \
            (1.8 if phase == "profiling" else 0.25 if phase in ("release", "wipe") else 1.0)
        tg["jitter"] = 0.15 + 0.55 * (1 - C)
        tg["text_fade"] = 0.9955 if hook == "scrawl" else 0.993
        tg["scan"] = 1.0 if phase == "profiling" else 0.0
        tg["hinge"] = 1.0 if s.get("hinge") else 0.0
        rv = s.get("reveal")
        tg["reveal"] = 1.0 if (isinstance(rv, dict) and phase in ("release", "wipe") and rv.get("lines") is not None
                               and not (phase == "wipe" and pt > 8.5)) else 0.0
        # tilt: one-euro filtered, immediate on big moves, steady when held
        self.tilt[0] = self._eu[0](self.tilt_in[0], dt)
        self.tilt[1] = self._eu[1](self.tilt_in[1], dt)
        te = self.tilt_energy
        self.tilt_energy *= math.exp(-dt * 2.5)
        if te > 0.55 and self.t - self.last_shake > 1.2:
            self._on_shake()
        self.last_shake = self.t if te > 0.55 else self.last_shake
        tg["swipe"] += self.tilt[0] * 1.3
        tg["smear"] += 12 * te
        tg["glitch"] += 0.5 * te
        # the phone turned upside down: a slow half turn of the figures
        fk = 1.0 if self.steer_flip else 0.0
        self.flipk += _clamp(fk - self.flipk, -dt / 1.8, dt / 1.8)
        k = 1 - math.exp(-dt * 1.6)
        for key, v in tg.items():
            rate = k
            if key == "hinge":
                rate = 1 - math.exp(-dt * 5)
            elif key == "reveal":
                rate = 1 - math.exp(-dt * 2.5)
            self.p[key] = _lerp(self.p[key], v, rate)
        self.oc, self.phase, self.pt, self.inten = oc, phase, pt, inten

    def _hold_hook(self, req, phase, pt):
        """Hysteresis on the hook: the profiler sometimes flips its guess every
        few seconds, and every flip was a scene cut. During hook and release a
        new hook takes over only once it has been asked for continuously for
        hook_hold_s and the current scene has been up for min_scene_s, unless
        the phase just changed (or is less than 2 s old), a new visitor came,
        or a shake or a phone flip forces a cut."""
        if req != self.hook_req:
            self.hook_req, self.hook_req_t = req, self.t
        flip = self.steer_flip != self._hold_flip
        self._hold_flip = self.steer_flip
        force, self._hook_force = self._hook_force or flip, False
        new_phase = phase != self._hold_phase or self.visitor != self._hold_vid
        self._hold_phase, self._hold_vid = phase, self.visitor
        if req == self.hook:
            return req
        if phase not in ("hook", "release") or new_phase or pt < 2.0 or force:
            return req
        if (self.t - self.hook_req_t >= self.hook_hold_s
                and self.t - self.scene_t >= self.min_scene_s):
            return req
        return self.hook

    def _on_shake(self):
        """A shake: glitch burst, a scatter of data, and a cut to the next scene."""
        self.shake_t = self.t
        self._hook_force = True
        if self.phase == "hook":
            self.rotation += 1
            self.next_rotation = self.pt + 30 + self.rng.uniform(0, 15)
            self._trans_mode = "cut"
        for _ in range(3):
            self._add_mark(force_data=True)
            self._harvest()

    # ---- camera ------------------------------------------------------------
    def _camera(self, dt):
        """If no real camera frames arrive while someone should be there, a
        procedural stand-in feeds the figure so the room is never empty."""
        f = self.fig
        f.present = self.phase not in ("idle", "wipe")
        if self.phase in ("idle", "wipe"):
            if self.ghost_feed and f.ready:
                f.push_age += dt
            return
        if (not f.ready or f.stale) and not self.ghost_feed:
            f.wipe()
            self.ghost_feed = True
        if self.ghost_feed:
            self.ghost_t += dt
            if self.ghost_t >= 0.25:
                self.ghost_t = 0.0
                f.push(self._stand_in())

    def _stand_in(self):
        """A camera frame for when there is no camera: a painted figure from
        the overnight library if there is one, else the procedural body."""
        if self.bank and getattr(self, "_stand_vid", None) != self.visitor:
            self._stand_vid = self.visitor
            cut = self.bank.any_cut(random.Random(self.vseed))
            self._stand = None
            if cut is not None:
                try:
                    a = pygame.surfarray.pixels_alpha(cut).astype(np.float32) / 255.0
                    g = pygame.surfarray.array3d(cut).astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
                    frame = np.full((cut.get_width(), cut.get_height()), 120.0, np.float32)
                    frame = frame * (1 - a) + g * a
                    self._stand = frame.T.astype(np.uint8)  # camera layout [y, x]
                except Exception:
                    self._stand = None
        st = getattr(self, "_stand", None)
        if st is not None:
            # the library figure sways a little so it is not a still
            dx = int(math.sin(self.t * 0.6) * st.shape[1] * 0.04)
            noise = np.random.default_rng(int(self.t * 4)).normal(0, 4, st.shape)
            return np.clip(np.roll(st, dx, axis=1) + noise, 0, 255).astype(np.uint8)
        return ghost_body(160, 120, self.t, seed=self.vseed % 97, present=1.0)

    # ---- scenes ------------------------------------------------------------
    def _want(self):
        ph = self.phase
        if ph == "idle" or (ph == "wipe" and self.pt > 9):
            return ("idle",)
        if ph in ("approach", "profiling"):
            return ("profiling", self.vseed)
        if ph == "hook" and self.pt > self.next_rotation:
            self.rotation += 1
            self.next_rotation = self.pt + 28 + self.rng.uniform(0, 17)
        return (self.hook, self.vseed, self.rotation)

    def _scene_pal(self, key):
        r = random.Random(zlib.crc32(repr(key).encode()))
        if key[0] == "idle":
            names = ["triptych", "papal", "rose", "teal", "oxblood", "lilac", "sodium"]
            base = palettes.get(names[(self.visits + int(self.t // 600)) % len(names)])
            return palettes.shift(base, r.uniform(-8, 8), 0.85, 0.9)
        return palettes.shift(self.pal, r.uniform(-12, 12), r.uniform(0.95, 1.12), r.uniform(0.95, 1.05))

    def _build_scene(self, key):
        r = random.Random(zlib.crc32(repr(key).encode()))
        if key[0] == "idle":
            return scenes.idle_scene(r)
        if key[0] == "profiling":
            return scenes.profiling_scene(r, self.hook)
        fv = self.config.get("force_variant")
        if fv is not None:  # demo / stills: show one particular variant
            lst = scenes.VARIANTS.get(key[0]) or scenes.VARIANTS["flesh"]
            return lst[int(fv) % len(lst)](r, self.oc)
        sc, _ = scenes.pick(key[0], key[1], key[2], r, self.oc)
        return sc

    def _schedule(self, dt):
        want = self._want()
        if want != self.scene_key and (self.pending is None or self.pending[0] != want):
            sc = self._build_scene(want)
            pal = self._scene_pal(want)
            spec = dict(sc["ground"])
            spec["pal"] = pal
            spec["seed"] = zlib.crc32(repr(want).encode()) & 0xffff
            gen = self._prepare(want, sc, pal, spec)
            self.pending = (want, sc, pal, gen)
        if self.pending is not None:
            want, sc, pal, gen = self.pending
            # one step per frame; after a shake, as many as fit in ~5 ms (the whole scene at once
            # took 60-90 ms: a visible hitch on the cut)
            budget = 0.005 if self._trans_mode_now() == "cut" else 0.0
            t0 = time.perf_counter()
            try:
                while True:
                    next(gen)
                    if time.perf_counter() - t0 >= budget:
                        break
            except StopIteration as e:
                self.pending = None
                self._install(want, sc, pal, e.value)

    def _prepare(self, key, sc, pal, spec):
        """Everything a new scene needs, a slice per frame: the ground (itself
        a generator), the library underpainting and cutout, the glaze, the
        light pool and the props. Returns the pieces for _install."""
        surf = yield from ground.build_ground(self.W + 2 * self.M, self.H + 2 * self.M, self._ground_spec(spec), None)
        out = dict(surf=surf, cut=None)
        hook = key[0] if key[0] in HOOKS else None
        rb = random.Random(zlib.crc32(repr(key).encode()) + 11)
        bank = self.bank
        if hook and bank:
            # one underpainting per scene (seeded by its key): never re-picked frame to frame
            img = bank.pick("under", hook, self.pal_name, rb)
            if img is not None:
                img = img if img.get_size() == surf.get_size() else bankimg.crop_fill(img, surf.get_size())
                img.set_alpha(55)
                surf.blit(img, (0, 0))
            yield
            cut = bank.pick("cut", hook, self.pal_name, rb)
            if cut is not None:
                out["cut"] = yield from self._paint_cut_steps(cut, pal, rb.randrange(1 << 16))
                yield
        r = random.Random(zlib.crc32(repr(key).encode()) + 3)
        out["glaze"] = yield from ground.glaze_steps(surf, r.choice([-24, -16, 16, 24]), 1.15)
        out["glaze_period"] = r.uniform(40, 90)
        yield
        lc = palettes.mix(pal[3], pal[4], 0.5)
        out["light"] = ground.light_pool(int(self.H * 0.45), [c * 0.14 for c in lc])
        props = []
        for pd in sc.get("props", []):
            yield
            w = pd["w"] * self.W; h = pd["h"] * self.H
            spr = yield from ground.build_prop_steps(pd["kind"], w, h, pal, r.randrange(1000))
            props.append((pd, spr))
        out["props"] = props
        return out

    def _trans_mode_now(self):
        return getattr(self, "_trans_mode", None)

    def _ground_spec(self, spec):
        # the spec's positions are in frame fractions; the ground has a margin
        W, H, M = self.W, self.H, self.M
        fx = lambda x: (x * W + M) / (W + 2 * M)
        fy = lambda y: (y * H + M) / (H + 2 * M)
        out = dict(spec)
        if "light" in spec:
            lx, ly, lr = spec["light"]
            out["light"] = (fx(lx), fy(ly), lr)
        if spec.get("shadow"):
            sx, sy, rx, ry = spec["shadow"]
            out["shadow"] = (fx(sx), fy(sy), rx * W / (W + 2 * M), ry * H / (H + 2 * M))
        if "horizon" in spec:
            out["horizon"] = fy(spec["horizon"])
        return out

    def _install_now(self, key, sc, pal):
        spec = dict(sc["ground"]); spec["pal"] = pal; spec["seed"] = 1
        gen = self._prepare(key, sc, pal, spec)
        prep = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            prep = e.value
        self._install(key, sc, pal, prep, transition=False)

    def _install(self, key, sc, pal, prep, transition=True):
        if transition and self.scene is not None:
            self.snap = self.low.copy()
            mode = self._trans_mode_now() or random.Random(zlib.crc32(repr(key).encode())).choice(
                ["fade", "wipe", "drag", "fade", "wipe"])
            dur = {"fade": 1.6, "wipe": 1.4, "drag": 1.2, "cut": 0.5}[mode]
            old = self.scene_key[0] if self.scene_key else None
            if mode != "cut" and old in HOOKS and key[0] in HOOKS and old != key[0]:
                mode, dur = "fade", self.hook_fade_s      # one hook into another: a slow crossfade
            self.trans = (mode, self.t, dur)
        self._trans_mode = None
        if key != getattr(self, "_resized_key", None):
            self.scene_t = self.t        # (a repaint after a size change is not a new scene)
        self._resized_key = None
        self.scene_key = key
        self.scene = sc
        self.scene_pal = pal
        self.scene_cut = prep["cut"]
        self.ground_surf = prep["surf"]
        self.glaze_surf = prep["glaze"]
        self.glaze_period = prep["glaze_period"]
        self.light = prep["light"]
        self.props = prep["props"]
        self.under.fill((0, 0, 0, 0))
        self.under_rect = None
        self._gcomp_key = None
        if key[0] == "idle":
            self.cover.fill((0, 0, 0, 0))
            self.cover_rect = None
            self._wipe_queue = None
            self.wipe_t = None
            self.reveal_cache = None
            self._reveal_job = None
        self.lut_key = None

    # ---- layers -----------------------------------------------------------
    def _draw_ground(self):
        M = self.M
        ox = int(-M + self.tilt[0] * M * 0.85)
        oy = int(-M - self.tilt[1] * M * 0.6)
        a = 0.5 + 0.5 * math.sin(self.t * 2 * math.pi / self.glaze_period)
        ga = int(130 * a)
        # the glaze drifts by one alpha step every ~0.1-0.3 s: the ground with its
        # glaze is composed once per step and blitted opaque in between
        gkey = (id(self.ground_surf), id(self.glaze_surf), ga if ga > 8 else 0)
        if self._gcomp_key != gkey:
            if self._gcomp is None or self._gcomp.get_size() != self.ground_surf.get_size():
                self._gcomp = self.ground_surf.copy()
            else:
                self._gcomp.blit(self.ground_surf, (0, 0))
            if ga > 8:
                self.glaze_surf.set_alpha(ga)
                self._gcomp.blit(self.glaze_surf, (0, 0))
            self._gcomp_key = gkey
        self.low.blit(self._gcomp, (ox, oy))
        # the light pool follows the figure and the tilt, breathing slowly
        if self.light is not None:
            breath = 0.75 + 0.25 * math.sin(self.t * 2 * math.pi / (6.0 if self.hook == "void" else 11.0))
            if self.hook == "void":
                breath = 0.45 + 0.55 * math.sin(self.t * 2 * math.pi / 6.0) ** 2
            lx = self.W * 0.5 + self.tilt[0] * self.W * 0.18
            if self.main is not None:
                lx = self.main.cx * 0.7 + lx * 0.3
            ly = self.H * 0.42 + self.tilt[1] * self.H * 0.1
            lw = self.light.get_width()
            if breath > 0.05:
                light = self.light
                if breath < 0.98:
                    s = int(lw * (0.8 + 0.2 * breath))
                    if self._light_key != (id(self.light), s):
                        self._light_s = pygame.transform.scale(self.light, (s, s))
                        self._light_key = (id(self.light), s)
                    light = self._light_s
                self.low.blit(light, (int(lx - light.get_width() / 2), int(ly - light.get_height() / 2)),
                              special_flags=pygame.BLEND_RGB_ADD)

    def _lut(self):
        oc = self.oc
        key = (tuple(map(tuple, self.scene_pal)), round(oc["A"], 1), round(oc["N"], 1), self.hook, self.vseed % 5)
        if key != self.lut_key:
            raw = 0.35 + 0.5 * oc["N"] * (1 - 0.5 * oc["A"])
            cold = 0.55 if self.hook in ("mirror", "void") else max(0.0, 0.5 - oc["A"]) * 0.6
            if self.hook == "scrawl":
                cold = 0.7
            self.lut = flesh_luts(self.scene_pal, raw, cold, seed=self.vseed % 5)
            self.lut_key = key
        return self.lut

    def _instances(self):
        """Screen placement of every figure in the current scene."""
        sc = self.scene
        out = []
        f = self.fig
        W, H = self.W, self.H
        zoom = 1.0 + 0.22 * self.tilt[1]
        flip_extra = 180.0 * _smooth(self.flipk)
        for i, sp in enumerate(sc["figs"]):
            mv = sp.get("move", 1.0)
            crop = scenes.crop_rect(sp.get("crop"), f.face, f.face_size, f.w, f.h)
            h = sp["h"] * H * self.p["scale"] * (1 + (zoom - 1) * mv)
            if sp.get("crop") is None:
                h *= 1.0
            cx = sp["cx"] * W + self.tilt[0] * W * 0.13 * mv + math.sin(self.t * 0.13 + i) * W * 0.012
            cy = sp["cy"] * H + self.tilt[1] * H * 0.07 * mv
            if sp.get("panel") is not None and sc["ground"].get("panels") == 3:
                pr = ground.panel_rects(W, H, 3)[sp["panel"]]
                cx = max(pr.left + 10, min(pr.right - 10, cx))
            rot = sp.get("rot", 0.0) - self.tilt[0] * 24 * mv + flip_extra
            out.append(_Inst(sp, crop, (cx, cy), h, rot, sp.get("mirror", False)))
        return out

    def _src_surface(self, name):
        if name and name.startswith("echo") and self.echoes:
            k = int(name[4:] or 1)
            return self.echoes[max(0, len(self.echoes) - k)]
        return self.fig_surf

    def _draw_figures(self, dt):
        self.main = None
        self.insts = []
        sc = self.scene
        if self.under_rect is not None:
            self.low.blit(self.under, self.under_rect.topleft, self.under_rect)
        for pd, spr in self.props:
            # props move with the figure they belong to, a little less than it does
            x = pd["x"] * self.W + self.tilt[0] * self.W * 0.11 - spr.get_width() / 2
            y = pd["y"] * self.H + self.tilt[1] * self.H * 0.05
            self.low.blit(spr, (int(x), int(y)))
        if not sc["figs"] or not self.fig.ready or self.p["fig_alpha"] < 0.02 or self.phase == "wipe":
            self.last_center = None
            return
        insts = self._instances()
        paint_i = next((i for i, s in enumerate(sc["figs"]) if s.get("paint")), len(insts) - 1)
        mains = insts[paint_i]
        smear = self.p["smear"] * mains.spec.get("smear", 1.0) / max(0.4, mains.scale / 2.0) ** 0.3
        pix = self.fig.render_packed(self.t, dt, smear, self.p["twist"], self.p["swipe"], self._lut(),
                                     self.p["fig_alpha"], trail=0.55 if self.hook != "void" else 0.8,
                                     contrast=(0.25 if not mains.spec.get("crop") else 0.0) if self.hook != "void" else 0.6,
                                     planes=0.65 if not mains.spec.get("crop") else 0.2, taps=self.q["taps"])
        px = pygame.surfarray.pixels2d(self.fig_surf)
        px[:] = pix
        del px
        self._fig_rgb = pix            # packed; strokes unpack the few pixels they sample
        # echoes: the visitor a few seconds ago (memory only, dropped on wipe)
        if self.t - self.echo_t > 1.6 and self.phase in ("hook", "profiling", "release"):
            self.echo_t = self.t
            self.echoes.append(self.fig_surf.copy())
            if len(self.echoes) > 4:
                del self.echoes[0]
        for i, inst in enumerate(insts):
            sp = inst.spec
            cut = self.scene_cut if sp.get("src") == "bank" else None
            if cut is not None:
                # a painted figure from the overnight library, collaged in
                cw, ch = cut.get_size()
                fs = pygame.transform.smoothscale(cut, (max(2, int(inst.th * cw / ch)), inst.th))
            else:
                src = self._src_surface(sp.get("fallback") if sp.get("src") == "bank" else sp.get("src"))
                cx0, cy0, cw, ch = inst.crop
                if (cw, ch) != src.get_size():
                    # a crop: feather its borders so it never shows a hard rectangle
                    sub = src.subsurface((cx0, cy0, cw, ch)).copy()
                    self._stretch_crop(sub)
                    sa = pygame.surfarray.pixels_alpha(sub)
                    sa[:] = (sa * self._feather(cw, ch)).astype(np.uint8)
                    del sa
                else:
                    sub = src
                fs = pygame.transform.smoothscale(sub, (inst.tw, inst.th))
            if inst.mirror:
                fs = pygame.transform.flip(fs, True, False)
            if abs(((inst.rot + 180) % 360) - 180) > 0.5:
                fs = pygame.transform.rotate(fs, inst.rot)
            r = fs.get_rect(center=(int(inst.cx), int(inst.cy)))
            alpha = sp.get("alpha", 1.0)
            # (scenes ask for a drop "shadow"; v2 drew it as fs.copy() filled with
            # (40, 30, 50, 0) under BLEND_RGBA_MIN, which zeroes its alpha: it never
            # showed. The ~0.6 ms of work per frame is skipped; the look is unchanged.)
            if i == paint_i:
                self._motion_ghosts(fs, r)
            if alpha < 0.99:
                fs.set_alpha(int(255 * alpha))
            self.low.blit(fs, r)
        self.insts = insts
        self.main = mains

    @staticmethod
    def _stretch_crop(sub):
        """A close-up is a few camera pixels blown up: stretch its own tones so the
        sockets, mouth and hairline stay dark and it doesn't wash out to milk."""
        px = pygame.surfarray.pixels3d(sub)
        lum = px[::2, ::2].mean(axis=2)
        lo, hi = _percentiles(lum, (6, 97))
        if hi - lo > 4:
            k = min(3.0, 215.0 / (hi - lo))
            # one value in, one value out: a 256-entry table instead of a power per pixel
            f = (np.arange(256, dtype=np.float32) - lo) * k + 18.0
            # a little extra weight in the darks: paint, not a photocopy
            f = 255.0 * (np.clip(f, 0, 255) / 255.0) ** 1.25
            px[:] = f.astype(np.uint8)[px]
        del px

    def _feather(self, w, h):
        """An oval vignette for crops: soft all round, so a close-up never shows its rectangle."""
        key = (w, h)
        if getattr(self, "_feather_key", None) != key:
            x = (np.arange(w, dtype=np.float32) - (w - 1) / 2) / max(1.0, w / 2)
            y = (np.arange(h, dtype=np.float32) - (h - 1) / 2) / max(1.0, h / 2)
            r = np.sqrt(x[:, None] ** 2 * 0.85 + y[None, :] ** 2)
            k = np.clip((1.0 - r) / 0.45, 0, 1)
            self._feather_arr = (k * k * (3 - 2 * k)).astype(np.float32)
            self._feather_key = key
        return self._feather_arr

    def _paint_cut(self, cut, pal, seed):
        """_paint_cut_steps, all at once."""
        gen = self._paint_cut_steps(cut, pal, seed)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            return e.value

    def _paint_cut_steps(self, cut, pal, seed):
        """A library cutout recoloured in this scene's flesh and dragged a
        little, so it sits in the painting instead of on it. Generator (yields
        between stages; returns the painted cutout)."""
        try:
            lut = flesh_luts(pal, 0.5, 0.2, zones=2, seed=seed % 5)[0]
            rgb = pygame.surfarray.array3d(cut).astype(np.float32)
            g = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
            lo, hi = np.percentile(g, (5, 95))
            g = np.clip((g - lo) / max(10.0, hi - lo), 0, 0.999)
            out = cut.copy()
            pygame.surfarray.blit_array(out, lut[(g * 255).astype(np.int32)])
            w, h = out.get_size()
            if w * h >= brush.FINE_PX // 4:
                yield
            tooth = yield from brush.make_tooth_steps(w, h, seed % 7)
            av = pygame.surfarray.pixels_alpha(out)
            rv = pygame.surfarray.pixels3d(out)
            w, h = out.get_size()
            rng = np.random.default_rng(seed)
            n = 10
            x0 = rng.uniform(0.1, 0.9, n) * w; y0 = rng.uniform(0.05, 0.9, n) * h
            ctrl = brush.flow_paths(x0, y0, rng.uniform(0.2, 0.5, n) * w, lambda x, y: np.full_like(x, 0.4), steps=4, rng=rng)
            brush.strokes(rv, None, ctrl, rng.uniform(0.04, 0.1, n) * w, np.array([pal[3]] * n), "wipe", rng,
                          tooth, src=rv.copy(), charge=0.2, opacity=0.8)
            del av, rv
            return out
        except Exception:
            return cut

    def _motion_ghosts(self, fs, r):
        """When the figure moves across the screen, it leaves dragged copies of
        itself behind for a moment."""
        c = r.center
        if self.last_center is not None:
            d = math.hypot(c[0] - self.last_center[0], c[1] - self.last_center[1])
            if d > 1.5 * self.u and (not self.ghosts or self.t - self.ghosts[-1][2] > 0.1):
                g = fs.copy()
                self.ghosts.append([g, r.copy(), self.t])
                if len(self.ghosts) > 4:
                    del self.ghosts[0]
        self.last_center = c
        keep = []
        for g in self.ghosts:
            age = self.t - g[2]
            if age > 0.7:
                continue
            g[0].set_alpha(int(120 * (1 - age / 0.7)))
            self.low.blit(g[0], g[1])
            keep.append(g)
        self.ghosts = keep

    # ---- paint ------------------------------------------------------------
    def _fade_layers(self, dt):
        sc = self.scene
        fade = sc.get("fade", 40.0) * (2.5 if self.phase == "wipe" else 1.0)
        self.fade_acc += fade * dt
        step = int(self.fade_acc)
        if step >= 1:
            self.fade_acc -= step
            self._fade("over", step)
        self.ufade_acc += 12.0 * dt
        step = int(self.ufade_acc)
        if step >= 4:                    # the under layer fades in coarse steps
            self.ufade_acc -= step
            self._fade("under", step)

    def _fade(self, name, step):
        """Saturating subtract of step from a paint layer's alpha, only where it
        holds paint; once everything there has faded out the layer is empty."""
        r = getattr(self, name + "_rect")
        if r is None:
            return
        a = pygame.surfarray.pixels_alpha(getattr(self, name))[r.left:r.right, r.top:r.bottom]
        np.maximum(a, step, out=a)   # two cheap passes
        a -= step
        del a
        faded = getattr(self, name + "_faded") + step
        setattr(self, name + "_faded", faded)
        if faded >= 255:
            setattr(self, name + "_rect", None)

    def _paint_dirty(self, name, ctrl, width):
        """Grow a paint layer's paint rect by the strokes about to be drawn."""
        c = np.asarray(ctrl, np.float32).reshape(-1, 2)
        if not len(c):
            return
        m = float(np.max(width)) * 0.85 + 4
        x0, y0 = c.min(0) - m
        x1, y1 = c.max(0) + m
        r = pygame.Rect(int(x0), int(y0), int(x1 - x0) + 2, int(y1 - y0) + 2).clip(pygame.Rect(0, 0, self.W, self.H))
        old = getattr(self, name + "_rect")
        setattr(self, name + "_rect", r if old is None else old.union(r))
        setattr(self, name + "_faded", 0)

    def _paint(self, dt):
        self._fade_layers(dt)
        if self.wipe_t is not None:
            self._paint_wipe()
            return
        m = self.main
        if m is None:
            return
        sc = self.scene
        weights = sc.get("strokes") or {}
        rate = self.p["stroke_rate"] * (0.25 + 0.75 * self.p["fig_alpha"]) * self.q["strokes"]
        n = (np.random.poisson(rate * dt) if rate > 0 else 0) + self._stroke_debt
        # at most a few strokes per frame: a Poisson burst of 6-10 was a 5 ms frame;
        # the rest are painted over the next frames (same rate, no visible delay)
        cap = max(2, int(self.stroke_cap * self.q["strokes"] + 0.5))
        self._stroke_debt = min(8, max(0, int(n) - cap))
        n = min(int(n), cap)
        swipe_rate = sc.get("swipes", 0) / 24.0 * (0.3 + 0.7 * self.inten) * (0.4 + 0.8 * self.oc["N"] + 0.3 * self.oc["O"])
        if self.phase == "hook" and swipe_rate > 0 and random.random() < swipe_rate * dt and len(self.swipes) < 3:
            self._new_swipe()
        if n <= 0 and not self.swipes:
            return
        rgbv = pygame.surfarray.pixels3d(self.over)
        av = pygame.surfarray.pixels_alpha(self.over)
        src = pygame.surfarray.pixels3d(self.low)
        try:
            if n > 0 and weights:
                fams = list(weights.keys())
                w = np.array([weights[f] for f in fams], np.float64)
                if w.sum() > 0:
                    fam = fams[int(np.searchsorted(np.cumsum(w / w.sum()), random.random()))]
                    self._figure_strokes(rgbv, av, src, fam, n)
            self._paint_swipes(rgbv, av, src, dt)
        finally:
            del rgbv, av, src

    def _sample_points(self, n):
        """Points on the body, weighted toward its edges and modelling."""
        f = self.fig
        key = f.frames_seen
        if getattr(self, "_cdf_key", None) != key:
            w = (f.mask2 * (0.25 + 1.5 * f.edge)).ravel().astype(np.float64)
            s = w.sum()
            self._cdf = np.cumsum(w / s) if s > 0 else None
            self._cdf_key = key
        if self._cdf is None:
            return None
        idx = np.minimum(np.searchsorted(self._cdf, self.prng.random(n)), len(self._cdf) - 1)
        h2 = f.mask2.shape[1]
        bx = (idx // h2) * 2 + self.prng.random(n) * 2
        by = (idx % h2) * 2 + self.prng.random(n) * 2
        return bx.astype(np.float32), by.astype(np.float32)

    def _figure_strokes(self, rgbv, av, src, fam, n):
        m = self.main
        f = self.fig
        pts = self._sample_points(n * 2)
        if pts is None:
            return
        bx, by = pts
        cx0, cy0, cw, ch = m.crop
        ok = (bx >= cx0) & (bx < cx0 + cw) & (by >= cy0) & (by < cy0 + ch)
        bx, by = bx[ok][:n], by[ok][:n]
        if len(bx) == 0:
            return
        n = len(bx)
        u = self.u
        sz = m.scale / 2.0  # screen px per figure px, relative to a whole figure on screen
        L = {"loaded": (22, 60), "wipe": (40, 100), "scumble": (12, 30), "knife": (16, 40), "nervous": (30, 80)}[fam]
        Wd = {"loaded": (3, 6.5), "wipe": (9, 20), "scumble": (5, 11), "knife": (6, 12), "nervous": (1.6, 2.4)}[fam]
        rng = self.prng
        Ls = rng.uniform(*L, n) * u * (0.6 + 0.4 * min(3.0, sz))
        ws = rng.uniform(*Wd, n) * u * (0.6 + 0.4 * min(3.0, sz))
        orient = f.orient
        sw = self.p["swipe"]
        contour = {"loaded": 0.85, "scumble": 0.6, "nervous": 0.9, "knife": 1.0, "wipe": 0.2}[fam]

        def ang_at(x, y):
            ix = np.clip((x * 0.5).astype(np.int32), 0, orient.shape[0] - 1)
            iy = np.clip((y * 0.5).astype(np.int32), 0, orient.shape[1] - 1)
            a = orient[ix, iy]
            if contour >= 1.0:
                return a
            # blend with the smear flow (as vectors, orientation-safe)
            c = np.cos(2 * a) * contour + np.cos(2 * sw) * (1 - contour)
            s = np.sin(2 * a) * contour + np.sin(2 * sw) * (1 - contour)
            return 0.5 * np.arctan2(s, c)

        steps = 2 if fam == "knife" else 6
        ctrl = brush.flow_paths(bx, by, Ls / max(0.3, m.scale), ang_at, steps=steps, rng=rng,
                                wander=brush.FAMILIES[fam]["wander"] * 0.5)
        # strokes stay on the body: once a path leaves the mask it stops there
        m2 = f.mask2
        ix2 = np.clip((ctrl[..., 0] * 0.5).astype(np.int32), 0, m2.shape[0] - 1)
        iy2 = np.clip((ctrl[..., 1] * 0.5).astype(np.int32), 0, m2.shape[1] - 1)
        inside = m2[ix2, iy2] > (0.12 if fam != "wipe" else 0.03)
        inside[:, :2] = True
        alive = np.logical_and.accumulate(inside, axis=1)
        last = alive.sum(1) - 1
        idx = np.minimum(np.arange(ctrl.shape[1])[None, :], last[:, None])
        ctrl = np.take_along_axis(ctrl, idx[..., None].repeat(2, -1), axis=1)
        sx, sy = m.to_screen(ctrl[..., 0], ctrl[..., 1])
        ctrl = np.stack([sx, sy], -1)
        # colour: the figure's own paint at that point, pushed apart in value
        ix = np.clip(bx.astype(np.int32), 0, f.w - 1)
        iy = np.clip(by.astype(np.int32), 0, f.h - 1)
        col = f.unpack(self._fig_rgb[ix, iy]).astype(np.float32)
        lum = col.mean(1, keepdims=True)
        push = np.where(lum > 140, 1.12, 0.85)
        col = np.clip(lum + (col - lum) * 1.2, 0, 255) * push
        pal = self.scene_pal
        c2 = np.array([pal[1] if l < 130 else pal[4] for l in lum[:, 0]], np.float32)
        opac = 0.9 if fam != "wipe" else 0.7
        self._paint_dirty("over", ctrl, ws)
        if fam == "wipe":
            brush.strokes(rgbv, av, ctrl, ws, col, "wipe", rng, self.tooth, src=src, charge=0.35, drag=14,
                          opacity=opac)
        else:
            brush.strokes(rgbv, av, ctrl, ws, col, fam, rng, self.tooth, color2=c2, mix=0.18, opacity=opac)

    def _new_swipe(self):
        m = self.main
        f = self.fig
        fx, fy = m.to_screen(f.face[0], f.face[1])
        size = f.face_size * m.scale
        if size < 6 * self.u:
            return
        r = random.Random()
        kind = r.choice(["smear", "smear", "smear", "erase", "bone"])
        rad = size * r.uniform(0.5, 1.1)
        a0 = r.uniform(0, 2 * math.pi)
        span = r.uniform(1.1, 2.6) * r.choice([-1, 1])
        self.swipes.append(dict(t0=self.t, dur=r.uniform(0.5, 1.3), cx=float(fx) + r.uniform(-0.4, 0.4) * size,
                                cy=float(fy) + r.uniform(-0.3, 0.5) * size, r=rad, a0=a0, a1=a0 + span,
                                w=size * r.uniform(0.35, 0.75), sq=r.uniform(0.6, 1.0), done=0.0, kind=kind))

    def _paint_swipes(self, rgbv, av, src, dt):
        keep = []
        pal = self.scene_pal
        for s in self.swipes:
            k = min(1.0, (self.t - s["t0"]) / s["dur"])
            k = 1 - (1 - k) ** 2  # fast start, slow end, like an arm
            if k - s["done"] > 0.02:
                a0 = s["a0"] + (s["a1"] - s["a0"]) * s["done"]
                a1 = s["a0"] + (s["a1"] - s["a0"]) * k
                ctrl = brush.arc_path(s["cx"], s["cy"], s["r"], a0, a1, 6, squash=s["sq"])[None]
                self._paint_dirty("over", ctrl, [s["w"]])
                if s["kind"] == "smear":
                    brush.strokes(rgbv, av, ctrl, [s["w"]], [pal[3]], "wipe", self.prng, self.tooth, src=src,
                                  charge=0.08, drag=int(18 * self.u), opacity=1.0, dry_scale=0.35)
                elif s["kind"] == "erase":
                    # partial erasure: the ground colour dragged over the face
                    brush.strokes(rgbv, av, ctrl, [s["w"] * 0.8], [pal[2]], "wipe", self.prng, self.tooth, src=src,
                                  charge=0.55, drag=int(10 * self.u), opacity=0.95, dry_scale=0.5)
                else:
                    brush.strokes(rgbv, av, ctrl, [s["w"] * 0.35], [(244, 236, 220)], "loaded", self.prng, self.tooth,
                                  color2=[pal[3]], mix=0.25, opacity=0.9)
                s["done"] = k
            if k < 1.0:
                keep.append(s)
        self.swipes = keep

    def _paint_wipe(self):
        """End of visit: broad house-painter strokes in the ground colour cover
        everything, then the paint layers are cleared."""
        age = self.t - self.wipe_t
        if self.phase == "wipe":
            # the file is struck out first, then the house paint comes
            k = _clamp((self.pt - 3.0) / 6.0)
            rate = 0.15 + 0.85 * k
        else:  # a control wipe outside the phase: three seconds of paint
            k = age / 3.0
            rate = 0.7
            if k >= 1:
                self.cover.fill((0, 0, 0, 0))
                self.cover_rect = None
                self.marks = []
                self.wipe_t = None
                return
        if k > 0.6:
            self.marks = [m for m in self.marks if random.random() < 0.97]
        q = self._wipe_queue
        if q is not None:
            # the second stroke of the last pass (one ~1.5 ms knife stroke per frame)
            self._wipe_queue = None
            rgbv = pygame.surfarray.pixels3d(self.cover)
            av = pygame.surfarray.pixels_alpha(self.cover)
            try:
                brush.strokes(rgbv, av, q[0], q[1], q[2], "knife", self.prng, self.tooth, opacity=0.95)
            finally:
                del rgbv, av
            return
        if random.random() < rate:
            pal = self.scene_pal
            rgbv = pygame.surfarray.pixels3d(self.cover)
            av = pygame.surfarray.pixels_alpha(self.cover)
            try:
                n = 2
                y0 = self.prng.uniform(0, self.H, n)
                x0 = np.full(n, -20.0)
                ctrl = brush.flow_paths(x0, y0, np.full(n, self.W * 1.1), lambda x, y: np.full_like(x, 0.03),
                                        steps=3, rng=self.prng, wander=0.05)
                col = np.array([pal[2]] * n, np.float32) * self.prng.uniform(0.92, 1.05, (n, 1))
                ws = self.prng.uniform(30, 60, n) * self.u
                self._paint_dirty("cover", ctrl, ws)
                self.cover_faded = 0
                brush.strokes(rgbv, av, ctrl[:1], ws[:1], col[:1], "knife", self.prng, self.tooth, opacity=0.95)
                self._wipe_queue = (ctrl[1:], ws[1:], col[1:])
            finally:
                del rgbv, av

    # ---- cage --------------------------------------------------------------
    def _draw_cage(self):
        kind = self.scene.get("cage")
        if not kind:
            return
        if self.main is not None:
            r = self.main.rect()
        else:
            h = int(self.H * 0.7)
            r = pygame.Rect(self.W // 2 - h // 3, self.H - h - int(self.H * 0.12), h * 2 // 3, h)
            r.x += int(self.tilt[0] * self.W * 0.11)
        col = tuple(int(c) for c in self.scene_pal[4])
        dark = tuple(int(c * 0.45) for c in self.scene_pal[1])
        jit = self.p["cage_jit"] * 2.5 * self.u
        rr = random.Random(int(self.t * 12))

        def tube(p0, p1, w=1):
            # a painted tube: a dark line with a lit line on its upper edge
            j = lambda: rr.uniform(-jit, jit)
            a = (p0[0] + j(), p0[1] + j()); b = (p1[0] + j(), p1[1] + j())
            pygame.draw.line(self.low, dark, (a[0] + self.u, a[1] + self.u), (b[0] + self.u, b[1] + self.u), max(1, int(2 * self.u)))
            pygame.draw.line(self.low, col, a, b, max(1, int(w * self.u)))

        if kind == "box":
            cx, cy = r.centerx, r.centery + r.h * 0.05
            hw, hh, hd = r.w * 0.6, r.h * 0.5, r.w * 0.45
            yaw = self.t * 0.07 * (1.3 - self.oc["C"]) + 0.4 + self.tilt[0] * 1.1
            pitch = -0.18 - self.tilt[1] * 0.6
            f, d = 520.0 * self.u, 900.0 * self.u
            verts = []
            for sx in (-1, 1):
                for sy in (-1, 1):
                    for sz in (-1, 1):
                        x, y, z = sx * hw, sy * hh, sz * hd
                        x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
                        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
                        k = f / (d + z)
                        verts.append((cx + x * k, cy + y * k))
            for i in range(8):
                for j in range(i + 1, 8):
                    if bin(i ^ j).count("1") == 1:
                        tube(verts[i], verts[j])
        elif kind == "arch":
            x0, x1 = r.left - r.w * 0.2, r.right + r.w * 0.2
            top = r.top - r.h * 0.08
            base = r.bottom + r.h * 0.04
            off = self.tilt[0] * 14 * self.u
            tube((x0, base), (x0 + off, top)); tube((x1, base), (x1 + off, top)); tube((x0 + off, top), (x1 + off, top))
            tube((x0 + off, top), (x0 + off + r.w * 0.25, top - r.h * 0.06)); tube((x1 + off, top), (x1 + off + r.w * 0.25, top - r.h * 0.06))
            tube((x0 + off + r.w * 0.25, top - r.h * 0.06), (x1 + off + r.w * 0.25, top - r.h * 0.06))
        elif kind == "ring":
            cy = r.bottom - r.h * 0.12
            rx, ry = r.w * 0.85, r.h * 0.12
            pts = [(r.centerx + math.cos(a / 24 * 2 * math.pi + self.t * 0.1) * rx,
                    cy + math.sin(a / 24 * 2 * math.pi + self.t * 0.1) * ry * (1 + self.tilt[1] * 0.6)) for a in range(25)]
            for p0, p1 in zip(pts[:-1], pts[1:]):
                tube(p0, p1)
            for a in (0.3, 2.8):
                x = r.centerx + math.cos(a) * rx
                tube((x, cy + math.sin(a) * ry), (x, r.top + r.h * 0.1))
        elif kind == "rail":
            side = 1 if r.centerx < self.W / 2 else -1
            x = r.centerx + side * r.w * 0.7
            pts = [(x, r.bottom), (x, r.top + r.h * 0.25), (x - side * r.w * 0.3, r.top + r.h * 0.1),
                   (x - side * r.w * 1.0, r.top + r.h * 0.1)]
            for p0, p1 in zip(pts[:-1], pts[1:]):
                tube(p0, p1, 2)
        elif kind == "frame":
            g = r.inflate(int(r.w * 0.16), int(r.h * 0.08))
            tube(g.topleft, g.topright); tube(g.topright, g.bottomright)
            tube(g.bottomright, g.bottomleft); tube(g.bottomleft, g.topleft)

    # ---- transitions and finish -------------------------------------------
    def _draw_transition(self):
        if self.trans is None or self.snap is None:
            return
        mode, t0, dur = self.trans
        k = (self.t - t0) / dur
        if k >= 1:
            self.trans = None
            self.snap = None
            return
        W, H = self.W, self.H
        if mode == "fade":
            _alpha(self.snap, int(255 * (1 - _smooth(k))))
            self.low.blit(self.snap, (0, 0))
        elif mode == "wipe":
            # the new scene is painted in with broad horizontal strokes
            band = max(6, int(22 * self.u))
            rr = random.Random(int(t0 * 10))
            for y in range(0, H, band):
                edge = int(W * _clamp(k * 1.6 - rr.uniform(0, 0.6)))
                if edge < W:
                    self.low.blit(self.snap, (edge, y), (edge, y, W - edge, band))
        elif mode == "drag":
            dx = int(W * 0.35 * k * k)
            _alpha(self.snap, int(255 * (1 - k)))
            self.low.blit(self.snap, (dx, 0))
        elif mode == "cut":
            if k < 0.25:
                self.low.blit(self.snap, (0, 0))

    def _finish(self, dt):
        p = self.p
        W, H = self.W, self.H
        if p["scan"] > 0.05:
            y = int((self.t * 70 * self.u) % H)
            pygame.draw.line(self.low, (235, 235, 235), (0, y), (W, y), 1)
            pygame.draw.line(self.low, (120, 255, 140), (0, y + 2), (W, y + 2), 1)
        burst = max(0.0, 1 - (self.t - self.shake_t) / 0.6)
        g = p["glitch"] + burst * 2
        if g > 0.05 and random.random() < min(1.0, g * 0.5):
            arr = pygame.surfarray.pixels3d(self.low)
            for _ in range(random.randint(1, 3 + int(burst * 6))):
                y0 = random.randint(0, H - 20); h = random.randint(3, int(28 * self.u) + 4)
                arr[:, y0:y0 + h] = np.roll(arr[:, y0:y0 + h], random.randint(-40, 40) * (1 + int(burst * 2)), axis=0)
            if burst > 0.2:
                # colour planes slip apart
                s = int(6 * burst * self.u) + 1
                arr[:, :, 0] = np.roll(arr[:, :, 0], s, axis=0)
                arr[:, :, 2] = np.roll(arr[:, :, 2], -s, axis=1)
            del arr
        if burst > 0.85:
            self._solid_blend(60, pygame.BLEND_RGB_ADD)
        if p["flicker"] > 0.05 and random.random() < p["flicker"] * 0.2:
            v = random.randint(30, 90)
            self._solid_blend(v, pygame.BLEND_RGB_SUB)
        if p["hinge"] > 0.02:
            # the hinge: everything drops away to near black
            v = int(235 * p["hinge"])
            self._solid_blend(v, pygame.BLEND_RGB_SUB)
        self.low.blit(self.canvas, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        gx = random.randint(0, 63); gy = random.randint(0, 63)
        self.low.blit(self.grain, (-gx, -gy), special_flags=pygame.BLEND_RGB_SUB)

    def _solid_blend(self, v, flags):
        """low.fill((v, v, v), special_flags=flags), as a blit of a solid surface:
        fill with a blend flag takes a slow path (~1.2 ms at 640x360 vs ~0.05)."""
        sol = getattr(self, "_solid", None)
        if sol is None or sol.get_size() != (self.W, self.H):
            sol = self._solid = pygame.Surface((self.W, self.H))
        sol.fill((v, v, v))
        self.low.blit(sol, (0, 0), special_flags=flags)

    def _make_grain(self):
        rng = np.random.default_rng(11)
        g = (rng.random((self.W + 64, self.H + 64)) ** 8 * 18).astype(np.uint8)
        arr = np.repeat(g[..., None], 3, 2)
        s = pygame.Surface((self.W + 64, self.H + 64))
        pygame.surfarray.blit_array(s, arr)
        # the canvas itself: a fixed weave that every layer of paint sits in
        cv = (246 + (self.tooth - 0.5) * 18).clip(0, 255).astype(np.uint8)
        self.canvas = pygame.Surface((self.W, self.H))
        pygame.surfarray.blit_array(self.canvas, np.repeat(cv[..., None], 3, 2))
        return s

    # ---- words ------------------------------------------------------------
    def _words(self):
        # the piece's internal names (hooks, palettes) never go on the wall,
        # whoever sent the words
        return [w for w in self._words_raw() if not (_BLOCK & set(str(w).upper().split()))]

    def _words_raw(self):
        s = self.state
        sw = s.get("words")
        if isinstance(sw, str):
            sw = [sw]
        if not isinstance(sw, (list, tuple)):
            sw = []
        if s.get("opted_out"):
            # the visitor covered the eye: no tailored or reactive lines, only the fact
            return list(LEX_OPTOUT)
        words = [w for w in (_text(x, 60) for x in sw) if w.strip()] + self.extra_words
        oc = self.oc
        tone = "tender" if oc["A"] >= 0.5 else "cold"
        hook = self.hook
        corp = self.corpus.words(hook if self.phase in ("hook", "release") else None, self.phase, tone)
        if self.phase == "idle":
            return corp or LEX_IDLE
        if self.phase == "profiling":
            data = ["%s %.2f" % (k, oc[k]) for k in "OCEAN"]
            data += ["DWELL %dS" % int(self.pt + 3), "CONFIDENCE %d%%" % int(40 + 50 * self.inten),
                     "SUBJECT %s" % str(s.get("visitor_id", "?"))[-4:].upper()]
            return words + data + corp[:12]
        base = corp or ((LEX_TENDER if tone == "tender" else LEX_COLD) + LEX_JEST + (LEX_COLD if oc["N"] > 0.6 else []))
        return words * 3 + base

    def _harvest(self):
        """Cut whatever was just drawn on the scratch sheet into a mark."""
        area = self._dirty or self.text.get_rect()
        area = area.clip(self.text.get_rect())
        self._dirty = None
        if not area.w or not area.h:
            return
        r = self.text.subsurface(area).get_bounding_rect().move(area.topleft)
        if r.w and r.h:
            self.marks.append([self.text.subsurface(r).copy(), r.topleft, self.t])
            self.text.fill((0, 0, 0, 0), r)
        while len(self.marks) > (20 if self.hook == "scrawl" else 26):
            del self.marks[0]

    def _blit_marks(self, surface):
        fade = self.p["text_fade"]
        drop = max(self.p["hinge"], self.p["reveal"] * 0.85)
        wipe_k = 1.0 - drop
        if self.wipe_t is not None:
            wipe_k *= max(0.0, 1 - (self.t - self.wipe_t) / 1.5)
        sx = surface.get_width() / self.TW
        keep = []
        for m in self.marks:
            a = 255 * fade ** ((self.t - m[2]) * 30) * wipe_k
            if a < 6 and wipe_k > 0.5:
                continue
            keep.append(m)
            if a < 6:
                continue
            if sx == 1:
                surface.blit(self._mark_surf(m, int(a)), m[1])
            else:  # demo window smaller than 1080p
                _alpha(m[0], int(a))
                w, h = m[0].get_size()
                surface.blit(pygame.transform.smoothscale(m[0], (max(1, int(w * sx)), max(1, int(h * sx)))),
                             (int(m[1][0] * sx), int(m[1][1] * sx)))
        self.marks = keep

    @staticmethod
    def _mark_surf(m, a):
        """The mark at alpha a. A per-pixel-alpha surface blitted with a surface
        alpha below 255 takes SDL's slow path (~5x), so the fade is baked
        into a copy's alpha channel instead, re-baked only when it has moved by
        6 levels (every ~4 frames: the steps do not show)."""
        if a >= 250:
            m[0].set_alpha(255)          # (never None: that would switch blending off)
            return m[0]
        if len(m) < 6:
            m[0].set_alpha(255)
            m.extend([m[0].copy(), 999, pygame.surfarray.array_alpha(m[0])])
        if abs(m[4] - a) >= 6:
            lut = (np.arange(256, dtype=np.uint16) * a // 255).astype(np.uint8)
            v = pygame.surfarray.pixels_alpha(m[3])
            v[...] = lut[m[5]]
            del v
            m[4] = a
        return m[3]

    def _update_text(self, dt):
        if self.phase in ("hook", "profiling", "release") and self.t - self.hist_t > 0.5:
            self.hist_t = self.t
            self.hist.append((self.fig.motion, abs(self.tilt[0]) + abs(self.tilt[1])))
            if len(self.hist) > 400:
                del self.hist[0]
        if self.p["hinge"] > 0.5 or self.p["reveal"] > 0.5:
            return
        if self.scene.get("text") == "line":
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
        w = random.choice(self._words() or LEX_IDLE)
        size = scrawl.fit_size(w, 42 * self.TW / 1920.0, self.TW * 0.9)
        x = (self.TW - scrawl.text_width(w, size)) / 2
        y = self.TH * random.choice([0.82, 0.18, 0.5]) if self.scene["name"] != "void/line" else self.TH * 0.82
        scrawl.draw_text(self.text, w, x, y, size, tuple(self.scene_pal[4]) + (255,), random, 0.1, self._lw(2))
        self._dirty = pygame.Rect(0, int(y - size), self.TW, int(size * 3))
        self._harvest()

    def _lw(self, w):
        """line width scaled from internal pixels to output pixels"""
        return max(1, int(round(w * self.k * 0.8 / self.u)))

    def _ink(self):
        p = self.scene_pal
        if self.hook == "scrawl" and self.phase in ("hook", "release"):
            return random.choice([p[0], p[0], p[0], p[0], p[1], p[3]])
        light = sum(p[2]) / 3 > 140
        return random.choice([p[0], p[0], p[1]] if light else [p[4], p[4], p[4], p[3]])

    def _add_mark(self, force_data=False):
        W, H = self.TW, self.TH
        k = self.k / self.u * self.u  # output px per internal px
        u = self.TW / 1920.0          # output px per 1080p px
        rng = random
        oc = self.oc
        ink = tuple(int(c) for c in self._ink()) + (255,)
        fr = self.main.rect() if self.main is not None else pygame.Rect(self.W // 3, self.H // 6, self.W // 3, self.H * 2 // 3)
        r = pygame.Rect(int(fr.x * self.k), int(fr.y * self.k), int(fr.w * self.k), int(fr.h * self.k))
        mode = self.scene.get("text", "free")
        roll = rng.random()
        surveil = self.hook == "scrawl" and self.phase in ("hook", "release")
        if force_data or roll < 0.06 + 0.08 * oc["E"] + (0.25 if surveil else 0):
            x = rng.uniform(120 * u, W - 120 * u); y = rng.uniform(120 * u, H - 120 * u)
            cw = rng.uniform(80, 170) * u
            kinds = ["reticle", "barcode", "tally", "redact"]
            if surveil:
                kinds += ["record", "record", "graph", "timestamp", "ring"]
            kind = rng.choice(kinds)
            if mode == "redact" and rng.random() < 0.5:
                kind = "redact"
                x = r.centerx + rng.uniform(-0.3, 0.3) * r.w; y = r.top + rng.uniform(0.05, 0.5) * r.h
            if kind == "reticle":
                scrawl.draw_reticle(self.text, x, y, cw * 0.5, ink, rng, self._lw(2))
            elif kind == "barcode":
                scrawl.draw_barcode(self.text, x - cw, y - cw * 0.3, cw * 2, cw * 0.6, ink, rng)
            elif kind == "tally":
                scrawl.draw_tally(self.text, x - cw, y - cw * 0.4, cw * 0.8, rng.randint(3, 17), ink, rng, self._lw(2))
            elif kind == "redact":
                scrawl.draw_redaction(self.text, x - cw, y - cw * 0.2, cw * rng.uniform(1.6, 3.2), cw * 0.4, ink, rng)
            elif kind == "record":
                size = 26 * u
                lines = ["SUBJECT %04d" % (self.vseed % 10000), "VISIT %d" % self.visits,
                         rng.choice(LEX_DATA) + " %d" % rng.randint(2, 99)]
                for i, ln in enumerate(lines):
                    scrawl.draw_text(self.text, ln, x - cw, y - cw * 0.4 + i * size * 1.5, size, ink, rng, 0.25, self._lw(1.5))
                pygame.draw.line(self.text, ink, (x - cw - 8 * u, y - cw * 0.4 - 10 * u), (x - cw - 8 * u, y - cw * 0.4 + size * 4.3), self._lw(1.5))
            elif kind == "graph":
                vals = [m for m, _ in self.hist[-40:]] or [0.1, 0.3, 0.2]
                scrawl.draw_graph(self.text, (x - cw, y - cw * 0.3, cw * 2, cw * 0.8), vals, ink, None, self._lw(1.5),
                                  rng.choice(["MOTION", "STILLNESS", "GRIP", "ATTENTION"]), 20 * u, seed=rng.randrange(9999))
            elif kind == "timestamp":
                scrawl.draw_timestamp(self.text, x - cw, y, self.pt + 3, ink, rng, 30 * u, self._lw(1.5))
            else:
                scrawl.draw_ring(self.text, r.centerx + rng.uniform(-0.3, 0.3) * r.w, r.top + rng.uniform(0.1, 0.6) * r.h,
                                 cw * 0.5, ink, rng, self._lw(2))
                x, y = r.centerx, r.centery
                cw = max(cw, r.w * 0.6)
            self._dirty = pygame.Rect(int(x - cw * 2), int(y - cw * 1.6), int(cw * 5), int(cw * 3.4))
            return
        if roll < 0.13 and oc["O"] > 0.5:
            x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
            x1, y1 = x0 + rng.uniform(-300, 300) * u, y0 + rng.uniform(-200, 200) * u
            scrawl.draw_arrow(self.text, x0, y0, x1, y1, ink, rng, self._lw(2))
            self._dirty = pygame.Rect(int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0))).inflate(60, 60)
            return
        word = rng.choice(self._words() or LEX_JEST)
        size = rng.uniform(40, 62 + 70 * oc["E"]) * u * (1.25 if self.hook == "scrawl" else 1.0)
        size = scrawl.fit_size(word, size, W - 80 * u)
        tw = scrawl.text_width(word, size)
        margin = 40 * u
        for _ in range(8):
            if mode == "band":
                x = rng.uniform(margin, max(margin + 1, W - tw - margin))
                y = rng.choice([rng.uniform(margin, H * 0.2), rng.uniform(H * 0.72, H - size - margin)])
            elif mode == "margins":
                x = rng.choice([rng.uniform(margin, W * 0.2), rng.uniform(W * 0.68, max(W * 0.69, W - tw - margin))])
                y = rng.uniform(margin, H - size - margin)
            elif oc["C"] > 0.65:  # orderly visitor: words line up on a grid
                x = round(rng.uniform(margin, max(margin + 1, W - tw - margin)) / (110 * u)) * 110 * u + margin * 0.5
                y = round(rng.uniform(margin, H - size - margin) / (92 * u)) * 92 * u + margin * 0.4
            else:
                x = rng.uniform(margin * 0.5, max(margin, W - tw - margin * 0.5)); y = rng.uniform(margin * 0.5, H - size - margin * 0.5)
            if self.hook == "scrawl" or not r.inflate(-r.w * 0.3, -r.h * 0.2).colliderect((x, y, tw, size)):
                break
        if self.hook == "mirror" and self.phase == "hook":
            word = rng.choice(["YOU", "ONLY YOU", "STAY", "CLOSER", word, word])
        bbox = scrawl.draw_text(self.text, word, x, y, size, ink, rng, self.p["jitter"],
                                self._lw(3 if size > 65 * u else 2),
                                slant=rng.uniform(-0.15, 0.15) - 0.3 * self.tilt[0])
        self._dirty = pygame.Rect(int(x - size), int(y - size), int(tw + size * 3), int(size * 3))
        crossed = rng.random() < 0.08 + 0.3 * oc["N"] + (0.35 if self.phase == "release" else 0)
        if crossed:
            scrawl.cross_out(self.text, bbox, ink, rng, self._lw(3))
        elif rng.random() < 0.2 + (0.3 if self.hook == "scrawl" else 0):
            # a hand-written record number after the word, like a file tag
            scrawl.draw_text(self.text, "#%04d" % rng.randrange(10000), bbox.right + size * 0.4, bbox.top + size * 0.35,
                             size * 0.5, ink, rng, 0.2, self._lw(1))

    # ---- live overlay at full resolution -----------------------------------
    def _overlay(self, surface):
        """Marks redrawn every frame at output resolution: the face box that
        follows the visitor, live graphs, the case-file furniture, the big
        line, the hinge line and the visitor's file at the end."""
        sx = surface.get_width() / self.TW
        if sx != 1:
            return self._overlay_small(surface)
        u = self.TW / 1920.0
        hinge = self.p["hinge"]
        rv = self.p["reveal"]
        pal = self.scene_pal
        light = sum(pal[2]) / 3 > 140
        ink = tuple(int(c) for c in (pal[0] if light else pal[4]))
        m = self.main
        k = self.k
        quiet = hinge > 0.3 or rv > 0.3
        if m is not None and not quiet and (self.phase == "profiling" or (self.hook == "scrawl" and self.phase == "hook")):
            f = self.fig
            fx, fy = m.to_screen(f.face[0], f.face[1])
            fs = f.face_size * m.scale * k
            rr = random.Random(int(self.t * 4))
            box = (float(fx) * k - fs * 0.5, float(fy) * k - fs * 0.62, fs, fs * 1.2)
            scrawl.draw_face_box(surface, box, ink, rr, max(2, int(3 * u)),
                                 "FACE 1  %.2f" % (0.55 + 0.4 * self.inten + 0.04 * math.sin(self.t * 3)), 26 * u)
            if self.hook == "scrawl" and self.phase == "hook":
                mode = self.scene.get("text")
                if len(self.hist) > 3:
                    gr = (60 * u, self.TH - 260 * u, 420 * u, 150 * u) if mode != "file" else (1120 * u, 640 * u, 640 * u, 220 * u)
                    scrawl.draw_graph(surface, gr, [h for h, _ in self.hist[-60:]], ink, None, max(2, int(2 * u)),
                                      "DWELL %02d:%02d" % (int(self.pt + 20) // 60, int(self.pt + 20) % 60), 24 * u,
                                      seed=len(self.hist))
                if mode == "file":
                    r = m.rect()
                    scrawl.draw_height_chart(surface, r.right * k + 20 * u, r.bottom * k, r.top * k, ink,
                                             random.Random(3), max(1, int(2 * u)), 18 * u)
                    rr2 = random.Random(self.vseed)
                    lines = ["FILE %04d-%02d" % (self.vseed % 10000, self.visits % 100),
                             "DWELL %dS" % int(self.pt + 20)] + ["%s %.2f" % (kk, self.oc[kk]) for kk in "OCEAN"]
                    for i, ln in enumerate(lines):
                        scrawl.draw_text(surface, ln, 1120 * u, 120 * u + i * 62 * u, 40 * u, ink, rr2, 0.18, max(2, int(3 * u)))
                if mode == "timeline":
                    for i, inst in enumerate(self.insts):
                        x = inst.cx * k - 80 * u
                        y = (inst.cy + inst.th * 0.55) * k
                        scrawl.draw_timestamp(surface, x, y, max(0, self.pt + 20 - (len(self.insts) - 1 - i) * 1.6),
                                              ink, random.Random(i), 26 * u, max(2, int(2 * u)))
                    pygame.draw.line(surface, ink, (60 * u, self.TH * 0.86), (self.TW - 60 * u, self.TH * 0.86), max(2, int(2 * u)))
        big = _text(self.state.get("big_line"), 60).strip()
        if hinge > 0.3 and not big:
            sw = self.state.get("words")
            ws = [w for w in (sw if isinstance(sw, (list, tuple)) else [sw]) if _text(w).strip()]
            big = _text(ws[-1], 60) if ws else "STILL HERE"
        if big and rv < 0.5:
            self._draw_big(surface, str(big), ink if hinge < 0.5 else (236, 232, 224))
        if rv > 0.05:
            self._draw_reveal(surface, rv, budget_ms=3.0)

    def _overlay_small(self, surface):
        """Demo window smaller than 1080p: only the big line, scaled."""
        big = self.state.get("big_line")
        if big:
            self._draw_big(self.text, str(big), (236, 232, 224))

    def _draw_big(self, surface, text, ink):
        key = (text, ink)
        if self.big_cache is None or self.big_cache[0] != key:
            u = self.TW / 1920.0
            size = scrawl.fit_size(text, 130 * u, self.TW - 160 * u)
            tw = scrawl.text_width(text, size)
            surf = pygame.Surface((int(tw + size * 2), int(size * 2.4)), pygame.SRCALPHA)
            scrawl.draw_text(surf, text, size * 0.5, size * 0.5, size, tuple(ink) + (255,), random.Random(zlib.crc32(text.encode())),
                             0.18, max(3, int(size / 11)))
            self.big_cache = (key, surf, self.t)
        surf, t0 = self.big_cache[1], self.big_cache[2]
        a = _clamp((self.t - t0) / 0.8)
        surf.set_alpha(int(255 * a))
        surface.blit(surf, ((self.TW - surf.get_width()) // 2, int(self.TH * 0.62)))

    @staticmethod
    def _wrap(text, size, max_w):
        """Word-wrap one line to max_w (scrawl.text_width, with a little slack
        for the hand jitter); a word longer than a row is split."""
        lim = max_w * 0.93
        rows, cur = [], ""
        for word in text.split():
            while scrawl.text_width(word, size) > lim and len(word) > 1:
                n = max(1, int(lim / (size * 0.95)))
                if cur:
                    rows.append(cur)
                    cur = ""
                rows.append(word[:n])
                word = word[n:]
            cand = (cur + " " + word) if cur else word
            if cur and scrawl.text_width(cand, size) > lim:
                rows.append(cur)
                cur = word
            else:
                cur = cand
        if cur or not rows:
            rows.append(cur)
        return rows

    def _reveal_layout(self, lines, n_dele, W, H, u):
        """Rows for the file's lines: wrapped to the card, the font shrunk until
        the newest lines fit above the deletion notes; the oldest lines drop
        off the top when even the smallest size cannot hold them all.
        Returns (size, line height, [(line index, row text)], top)."""
        top = 170 * u
        bottom = H - 30 * u - (n_dele * 48 * u + 20 * u if n_dele else 0)
        avail = W - 130 * u - 40 * u
        vis = lines[-13:]
        first = len(lines) - len(vis)
        size = 34 * u
        while True:
            lh = size * 58.0 / 34.0
            rows = []
            for i, ln in enumerate(vis):
                rows += [(first + i, r) for r in self._wrap(ln, size, avail)]
            if len(rows) * lh <= bottom - top + lh * 0.3 or size <= 18 * u:
                break
            size = max(18 * u, size * 0.9)
        while len(rows) * lh > bottom - top + lh * 0.3 and len(rows) > 1:
            drop = rows[0][0]                       # the oldest whole line goes
            rows = [r for r in rows if r[0] != drop] or rows[-1:]
        return size, lh, rows, top

    def _draw_reveal(self, surface, amount, budget_ms=None):
        """The visitor's file: a hand-ruled record, lines typed in one by one;
        in wipe, lines are struck out from the bottom, then deletion lines.
        Long lines wrap to the card (the font shrinks when they would not fit)
        and the card stays inside a 5% safe margin of the output.

        The card is drawn once per change of its contents (a new line, a new
        strike) and kept. With budget_ms (the show), a changed card is drawn a
        few rows per frame while the previous one stays up, so a new line never
        costs one long frame (a whole card is ~16 ms of drawing on x86)."""
        rv = self.state.get("reveal")
        if not isinstance(rv, dict):
            rv = (self.reveal_cache or {}).get("rv") or {}
        u = self.TW / 1920.0

        def _lst(v):
            if isinstance(v, str):
                return [_text(v, 240)]
            return [_text(x, 240) for x in v] if isinstance(v, (list, tuple)) else []
        header = _text(rv.get("header", "FILE"), 40) or "FILE"
        label = _text(rv.get("label", ""), 60)
        lines = _lst(rv.get("lines"))
        total = int(_clamp(_num(rv.get("total"), len(lines)), 0, 999))
        struck = int(_clamp(_num(rv.get("struck")), 0, 999)) if self.phase == "wipe" else 0
        dele = _lst(rv.get("wipe"))[:4] if self.phase == "wipe" else []
        key = (header, label, tuple(lines[:-1]), lines[-1] if lines else None, total, struck, tuple(dele))
        pal = self.scene_pal
        W = int(min(1180 * u, self.TW * 0.9))
        H = int(min(940 * u, self.TH * 0.9))
        if self.reveal_cache is None or self.reveal_cache.get("key") != key:
            job = getattr(self, "_reveal_job", None)
            if job is None or job[0] != key:
                job = (key, self._reveal_build(key, rv, header, label, lines, total, struck, dele, pal, W, H, u))
                self._reveal_job = job
            t0 = time.perf_counter()
            try:
                while True:
                    next(job[1])
                    if budget_ms is not None and (time.perf_counter() - t0) * 1000 >= budget_ms \
                            and self.reveal_cache is not None:
                        break
            except StopIteration as e:
                self.reveal_cache = e.value
                self._reveal_job = None
        c = self.reveal_cache
        if c is None:
            return
        # type and place the card that is ready (the previous one while a new one is drawn)
        lines, struck = c["lines"], c["struck"]
        W, H = c["surf"].get_size()
        ink = (26, 22, 24)
        red = c["red"]
        lw = max(2, int(3 * u))
        tx = 130 * u
        right = W - 40 * u
        boxes = c["boxes"]
        size, lh, rows, top = c["layout"]
        newest = len(lines) - 1
        n = 999 if self.phase == "wipe" else int((self.t - c["t_last"]) * 28) + 1
        need = sum(len(r) + 1 for li, r in rows if li == newest)
        if lines and n >= need and "full" in c:
            s, boxes = c["full"]                    # typed out: reuse the finished card
        elif lines:
            typed = n >= need
            blink = (int(self.t * 3) % 2 == 0) and not typed
            tkey = (min(n, need), blink)
            if c.get("tkey") != tkey:
                # the newest line types itself out, row by row (in the wipe nothing
                # is added any more: the file is shown whole). Only its rows are
                # redrawn: the band they sit in is restored from the static card.
                work = c.get("work")
                mine = [j for j, (li, _) in enumerate(rows) if li == newest]
                if work is None:
                    work = c["surf"].copy()
                    c["work"] = work
                elif mine:
                    y0 = int(top + mine[0] * lh - size * 1.05 - size * 0.6)
                    y1 = int(top + mine[-1] * lh - size * 1.05 + size * 1.9)
                    band = pygame.Rect(0, y0, W, y1 - y0).clip(work.get_rect())
                    work.blit(c["surf"], band, band)
                rr = random.Random(len(lines))
                tb = list(c["boxes"])
                bb = None
                k = n
                for j, (li, row) in enumerate(rows):
                    if li != newest or k <= 0:
                        continue
                    part = row[:k]
                    k -= len(row) + 1
                    bb = scrawl.draw_text(work, part, tx, top + j * lh - size * 1.05, size, ink, rr, 0.18, lw)
                    tb.append(bb)
                    if struck >= 1:
                        scrawl.cross_out(work, bb, red, rr, max(3, int(4 * u)), mode="bar")
                if bb is not None and k < 0 and blink:
                    cx = min(bb.right + 6 * u, right)
                    pygame.draw.line(work, ink, (cx, bb.top + 4 * u), (cx, bb.bottom - 4 * u), lw)
                c["tkey"], c["tboxes"] = tkey, tb
                if typed:
                    c["full"] = (work, tb)
            s, boxes = c["work"], c["tboxes"]
        else:
            s = c["surf"]
        a = int(255 * _clamp(amount * 1.2))
        s.set_alpha(a if a < 255 else None)        # an opaque card with alpha 255 blits ~20x slower
        x = int(self.TW * 0.5 - W / 2 + (self.TW * 0.18 if self.main is not None and self.main.cx < self.W * 0.45 else -self.TW * 0.12 if self.main is not None and self.main.cx > self.W * 0.55 else 0))
        y = int((self.TH - H) / 2)
        mx, my = int(math.ceil(self.TW * 0.05)), int(math.ceil(self.TH * 0.05))
        x = max(mx, min(self.TW - mx - W, x))
        y = max(my, min(self.TH - my - H, y))
        self.reveal_rect = pygame.Rect(x, y, W, H)
        self.reveal_boxes = boxes                  # card-local text boxes (tests check they stay on the card)
        surface.blit(s, (x, y))

    def _reveal_build(self, key, rv, header, label, lines, total, struck, dele, pal, W, H, u):
        """Generator: draws the static card (everything but the newest line, which
        types itself out per frame), yielding between rows; returns the cache."""
        paper = tuple(int(c) for c in palettes.mix(pal[4], (236, 232, 222), 0.6))
        ink = (26, 22, 24)
        red = tuple(int(c) for c in palettes.mix(pal[3], (170, 30, 30), 0.6))
        lw = max(2, int(3 * u))
        tx = 130 * u
        right = W - 40 * u                          # nothing is written past this
        rr = random.Random(zlib.crc32(header.encode()))
        size, lh, rows, top = self._reveal_layout(lines, len(dele), W, H, u)
        s = pygame.Surface((W, H))
        s.fill(paper)
        boxes = []
        # hand-ruled lines and a margin
        y = top
        while y < H - 30 * u:
            pygame.draw.line(s, palettes.mix(paper, (120, 140, 170), 0.45), (30 * u, y + rr.uniform(-1, 1)),
                             (W - 30 * u, y + rr.uniform(-2, 2)), max(1, int(2 * u)))
            y += lh
        pygame.draw.line(s, red, (110 * u, 20 * u), (112 * u + rr.uniform(-2, 2), H - 20 * u), max(1, int(2 * u)))
        count = "%d/%d" % (len(lines), max(total, len(lines)))
        csize = scrawl.fit_size(count, 40 * u, 240 * u)
        cx = right - scrawl.text_width(count, csize) * 1.06
        boxes.append(scrawl.draw_text(s, header, tx, 22 * u, scrawl.fit_size(header, 48 * u, (cx - 30 * u - tx) * 0.93),
                                      ink, rr, 0.15, max(3, int(4 * u))))
        yield
        if label:
            boxes.append(scrawl.draw_text(s, label, tx, 84 * u, scrawl.fit_size(label, 26 * u, (right - tx) * 0.93),
                                          red, rr, 0.15, lw))
            yield
        n_struck_from = len(lines) - struck          # lines at or after this index are struck
        newest = len(lines) - 1
        for j, (li, row) in enumerate(rows):
            if li == newest:
                continue                             # typed in per frame
            bb = scrawl.draw_text(s, row, tx, top + j * lh - size * 1.05, size, ink, rr, 0.18, lw)
            boxes.append(bb)
            if struck and li >= n_struck_from:
                scrawl.cross_out(s, bb, red, rr, max(3, int(4 * u)), mode="bar")
            yield
        for j, ln in enumerate(dele):
            ds = scrawl.fit_size(ln, 28 * u, (right - tx) * 0.93)
            boxes.append(scrawl.draw_text(s, ln, tx, H - 30 * u - (len(dele) - j) * 48 * u, ds, red, rr, 0.2, lw))
            yield
        boxes.append(scrawl.draw_text(s, count, cx, 44 * u, csize, red, rr, 0.12, lw))
        return dict(key=key, surf=s, rv=rv, t_last=self.t, last=lines[-1] if lines else "",
                    layout=(size, lh, rows, top), boxes=boxes, lines=lines, struck=struck, red=red)

    def _load_bank(self, path):
        """Optional overnight images (bank/<hook>/ and its derived/ versions):
        faint underpainting in the grounds, and painted cutout figures for
        collage and as a stand-in when the camera is missing. See bankimg.py."""
        try:
            return bankimg.Bank(self._bank_path(path), self._bank_size(), self.bank_max, fig_h=self.H)
        except Exception:
            return bankimg.Bank(None, (1, 1))

    def _bank_path(self, path=None):
        return path or self.bank_dir or os.path.join(os.path.dirname(__file__), "bank")

    def _bank_size(self):
        return (self.W + 2 * self.M, self.H + 2 * self.M)
