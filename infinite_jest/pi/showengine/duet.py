"""Two screens (Baby, 2026-11-23). Channel 1 = the TV, channel 2 = the projector on the white wall.

  empty room   TV black. The wall dreams slowly and dimly; the room only plays sound.
  someone in   the wall wakes: brighter, faster, it jolts when they move or speak.
  ~45 s in     the TV switches on and says hello. A grey, featureless face appears
               and, step by step, takes the visitor's form.
  the end      the guest's reveal lines under the finished face, then it dissolves.

Both pictures are generated live on the Pi by small neural networks (dream/net.py),
so the stream is different every time. The wall network learned the show's own
painted look; the face network learned one guest's face, and its training
snapshots run from a grey blob to the guest, so "taking form" is the network
remembering them.

With only one screen connected the wall is shown on it, and the face comes over it.
"""
from __future__ import annotations

import datetime
import json
import logging
import math
import os
import random
import threading
import time
from typing import Any

import numpy as np

from . import plugins

log = logging.getLogger("showengine.duet")

HERE = os.path.dirname(os.path.abspath(__file__))
IJ = os.path.dirname(os.path.dirname(HERE))          # .../infinite_jest
IN_ROOM = ("approach", "profiling", "hook")

GENERIC = {
    "hello": "hello.",
    "greeting": None,
    "address": ["stay.", "i am still learning you.", "every sound you make, i start again.",
                "hold still.", "closer."],
    "reveal": ["you came in as a guest. you leave as a file.",
               "everything i made, i made from you.",
               "this was made for one person. it is being deleted now."],
}


def _dream_import():
    try:
        from infinite_jest.dream import net      # type: ignore
        return net
    except Exception:
        import importlib.util
        p = os.path.join(IJ, "dream", "net.py")
        spec = importlib.util.spec_from_file_location("ij_dream_net", p)
        if spec is None or spec.loader is None:
            raise
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def load_guest(guest_id: str | None, today: datetime.date | None = None) -> dict | None:
    """The guest file for this run, or None. Past its delete_after date it is not used."""
    if not guest_id:
        return None
    for root in (os.path.join(IJ, "guests"), os.path.expanduser("~/.config/infinite-jest/guests")):
        for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            p = os.path.join(root, d, "guest.json")
            try:
                with open(p) as f:
                    g = json.load(f)
            except (OSError, ValueError):
                continue
            if str(g.get("guest_id")) != str(guest_id) and d != str(guest_id):
                continue
            until = g.get("delete_after")
            try:
                if until and (today or datetime.date.today()) > datetime.date.fromisoformat(until):
                    log.info("guest file past its delete date: not used")
                    return None
            except ValueError:
                pass
            g["_dir"] = os.path.join(root, d)
            return g
    return None


# ------------------------------------------------------------------ the dreaming
class Walk:
    """A smooth wander through the network's number space (velocity with friction)."""

    def __init__(self, n: int, rng: np.random.Generator, reach: float = 1.6):
        self.rng = rng
        self.u = rng.standard_normal(n).astype(np.float32) * 0.5
        self.v = np.zeros(n, np.float32)
        self.reach = reach

    def step(self, dt: float, speed: float) -> np.ndarray:
        dt = min(0.5, dt) * speed
        self.v += (self.rng.standard_normal(self.v.shape).astype(np.float32) * 1.4 - self.v * 0.8) * dt
        self.u += self.v * dt
        over = np.abs(self.u) > self.reach               # soft walls: come back towards the pictures
        self.v[over] -= np.sign(self.u[over]) * 0.6 * dt
        return self.u

    def jolt(self, amount: float) -> None:
        self.v += self.rng.standard_normal(self.v.shape).astype(np.float32) * amount


class Dreamer:
    """Runs a decoder in a background thread at a few frames per second. numpy's matrix
    products release the GIL, so the 30 fps picture loop keeps going."""

    def __init__(self, decoder: Any, fps: float, reach: float = 1.6, seed: int | None = None):
        self.dec = decoder
        self.fps = fps
        self.rng = np.random.default_rng(seed if seed is not None else int(time.time() * 1000) & 0xFFFFFFFF)
        self.walk = Walk(decoder.latent, self.rng, reach)
        self.speed = 0.2
        self.scale = 1.0          # how far from the centre of the pictures it may go
        self.prev = self.cur = None
        self.t_cur = 0.0
        self.energy = 0.0         # mean brightness of the newest frame, 0..1 (steers the sound)
        self.centroid = (0.0, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames = 0
        self.ms = 0.0

    def set_decoder(self, dec: Any) -> None:
        self.dec = dec

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ij-dream", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def make(self, dt: float) -> np.ndarray:
        u = self.walk.step(dt, self.speed)
        z = self.dec.z_mean + self.dec.z_std * u * self.scale
        t0 = time.perf_counter()
        img = self.dec(z)
        self.ms = self.ms * 0.9 + (time.perf_counter() - t0) * 100.0
        return img

    def _run(self) -> None:
        last = time.monotonic()
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                img = self.make(t0 - last)
            except Exception:
                plugins.report(log, "dream", "the dreaming network failed")
                self._stop.wait(2.0)
                continue
            last = t0
            self.push(img, t0)
            self._stop.wait(max(0.0, 1.0 / self.fps - (time.monotonic() - t0)))

    def push(self, img: np.ndarray, now: float) -> None:
        g = img.mean(axis=2)
        e = float(g.mean() / 255.0)
        tot = float(g.sum()) or 1.0
        ys, xs = np.indices(g.shape)
        cx = float((g * xs).sum() / tot) / g.shape[1] * 2 - 1
        cy = float((g * ys).sum() / tot) / g.shape[0] * 2 - 1
        with self._lock:
            self.prev, self.cur, self.t_cur = self.cur, img, now
            self.energy, self.centroid = e, (cx, cy)
            self.frames += 1

    def frame(self, now: float) -> np.ndarray | None:
        """The picture right now: a cross-fade between the last two generated frames."""
        with self._lock:
            prev, cur, t = self.prev, self.cur, self.t_cur
        if cur is None:
            return None
        if prev is None:
            return cur
        a = min(1.0, max(0.0, (now - t) * self.fps))
        if a >= 1.0:
            return cur
        return (prev.astype(np.float32) * (1 - a) + cur.astype(np.float32) * a).astype(np.uint8)


class FaceModel:
    """The face network's training snapshots, blended by progress 0 (grey blob) .. 1 (the guest)."""

    def __init__(self, steps_dir: str, net: Any):
        with open(os.path.join(steps_dir, "index.json")) as f:
            idx = json.load(f)
        self.snaps = [net.Decoder.load(os.path.join(steps_dir, s)) for s in idx["steps"]]
        last = self.snaps[-1]
        for s in self.snaps:                  # every snapshot walks where the finished face lives
            s.z_mean, s.z_std = last.z_mean, last.z_std
        self.latent = last.latent
        self.z_mean, self.z_std = last.z_mean, last.z_std
        self._p = -1.0
        self._dec = self.snaps[0]

    def at(self, p: float) -> Any:
        p = min(1.0, max(0.0, p))
        if abs(p - self._p) < 0.01 and self._dec is not None:
            return self._dec
        x = p * (len(self.snaps) - 1)
        i = min(len(self.snaps) - 2, int(x))
        self._dec = self.snaps[i].blend(self.snaps[i + 1], x - i)
        self._p = p
        return self._dec


class GrowingFace:
    """Decoder-like wrapper the Dreamer can run: always the face at the current progress."""

    def __init__(self, model: FaceModel):
        self.model = model
        self.progress = 0.0
        self.latent = model.latent
        self.z_mean, self.z_std = model.z_mean, model.z_std

    def __call__(self, z):
        return self.model.at(self.progress)(z)


# ------------------------------------------------------------------ the show
class Duet:
    def __init__(self, cfg: dict, engine: Any = None):
        d = cfg.get("duet") if isinstance(cfg.get("duet"), dict) else {}
        self.cfg = d
        self.engine = engine
        if engine is not None:
            engine.cfg["speak"] = False      # the room's generic answers stay quiet: the TV speaks here
        self.tv_at = float(d.get("tv_at_s", 45.0))
        self.grow_s = float(d.get("grow_s", 150.0))
        self.address_every = float(d.get("address_every_s", 30.0))
        self.wall_size = (int(d.get("wall_w", 960)), int(d.get("wall_h", 540)))
        self.rng = random.Random()
        self.guest = load_guest(str(d.get("guest", "001")) if d.get("guest", "001") else None)
        self.lines = self._lines(self.guest)
        net = None
        self.wall = self.face = None
        self.face_dreamer = None
        models = d.get("models_dir") or os.path.join(IJ, "dream", "models")
        try:
            net = _dream_import()
            p = net.find(models, "wall")
            if p:
                self.wall = Dreamer(net.Decoder.load(p), float(d.get("wall_fps", 8.0)))
            gid = self.guest.get("guest_id") if self.guest else None
            for name in ([f"face_{gid}_steps"] if gid else []) + ["face_steps"]:
                sd = os.path.join(models, name)
                if os.path.exists(os.path.join(sd, "index.json")):
                    self.face = GrowingFace(FaceModel(sd, net))
                    self.face_dreamer = Dreamer(self.face, float(d.get("face_fps", 6.0)), reach=0.9)
                    self.face_dreamer.speed = 0.35
                    break
        except Exception:
            plugins.report(log, "dream-load", "could not load the dreaming networks")
        log.info("duet: wall network %s, face network %s, guest %s", "yes" if self.wall else "NO",
                 "yes" if self.face else "NO", "yes" if self.guest else "none")
        self.reset()
        self._fonts: dict[int, Any] = {}
        self._grain: list[Any] = []
        self._vignette: dict[tuple, Any] = {}
        self._fb = None

    @staticmethod
    def _lines(g: dict | None) -> dict:
        out = {k: (list(v) if isinstance(v, list) else v) for k, v in GENERIC.items()}
        if g:
            name = str(g.get("name_spoken") or "").strip()
            out["hello"] = f"hello, {name.lower()}." if name else "hello."
            if g.get("greeting"):
                out["greeting"] = str(g["greeting"])
            if g.get("address"):
                out["address"] = [str(x) for x in g["address"]] + ([str(g["personal_question"])]
                                                                 if g.get("personal_question") else [])
            if g.get("reveal"):
                out["reveal"] = [str(x) for x in g["reveal"]]
        try:
            from .visit import visible_text      # no artist names, no marks on any screen
            for k, v in list(out.items()):
                if isinstance(v, list):
                    out[k] = [visible_text(x) for x in v if visible_text(x)]
                elif isinstance(v, str):
                    out[k] = visible_text(v)
        except Exception:
            pass
        return out

    def reset(self) -> None:
        self.tv = "black"            # black | hello | face | reveal | gone
        self.tv_t = 0.0
        self.wake = 0.0              # wall energy 0 (empty room) .. 1
        self.tv_level = 0.0          # TV picture brightness
        self.progress = 0.0
        self.caption = ""
        self.caption_t = 0.0
        self.said: set = set()
        self._next_address = 0.0
        self._address_i = 0
        self._reveal_i = 0
        self._next_reveal = 0.0
        self._last_heard = 0.0
        self._was_in = False

    def start(self) -> None:
        for dr in (self.wall, self.face_dreamer):
            if dr is not None:
                dr.start()

    def stop(self) -> None:
        for dr in (self.wall, self.face_dreamer):
            if dr is not None:
                dr.stop()

    # ---------------------------------------------------------- logic
    def _say(self, text: str | None, now: float, show: bool = True) -> None:
        if not text:
            return
        if show:
            self.caption, self.caption_t = text, now
        eng = self.engine
        if eng is not None:
            plugins.call(eng.audio, "say", text)

    def update(self, state: dict, now: float) -> None:
        """Called from the engine's tick with the fresh state (before audio and visuals get it)."""
        eng = self.engine
        m = eng.machine if eng is not None else None
        phase = state.get("phase", "idle")
        started = getattr(getattr(m, "visit", None), "started", None)
        in_room = phase in IN_ROOM
        t = (now - started) if (in_room or phase == "release") and started is not None else 0.0
        if in_room and not self._was_in:
            self.reset()
            self._was_in = True
        heard = float(state.get("heard", 0.0) or 0.0)
        motion = float((state.get("sensor") or {}).get("motion", 0.0) or 0.0)

        # the wall: asleep, awake, or pushed by the visitor
        want = 0.0 if phase in ("idle", "wipe") else 1.0
        self.wake += (want - self.wake) * min(1.0, 0.02 + (0.06 if want > self.wake else 0.01))
        if self.wall is not None:
            self.wall.speed = 0.12 + 0.55 * self.wake + 1.5 * heard + 1.2 * motion
            self.wall.scale = 0.8 + 0.5 * self.wake
            if heard > 0.9 and now - self._last_heard > 1.0:
                self.wall.walk.jolt(1.2)
                self._last_heard = now

        # the TV
        prev = self.tv
        if phase in ("idle",):
            self.tv = "black"
        elif phase == "wipe":
            self.tv = "gone" if self.tv != "black" else "black"
        elif phase == "release":
            if self.tv in ("face", "hello", "black") and t >= self.tv_at * 0.5:
                self.tv = "reveal"
        elif in_room:
            if self.tv == "black" and t >= self.tv_at:
                self.tv = "hello"
            elif self.tv == "hello" and now - self.tv_t >= 5.0:
                self.tv = "face"
        if self.tv != prev:
            self.tv_t = now
            if self.tv == "hello":
                self._say(self.lines["hello"], now)
                self._next_address = now + 9.0
            elif self.tv == "face":
                self.caption = ""
                self._next_address = max(self._next_address, now + 6.0)
            elif self.tv == "reveal":
                self._reveal_i, self._next_reveal = 0, now + 2.0
        tv_on = self.tv in ("hello", "face", "reveal")
        self.tv_level += ((1.0 if tv_on else 0.0) - self.tv_level) * (0.04 if tv_on else 0.03)

        if self.tv == "face":
            self.progress = min(1.0, max(self.progress, (now - self.tv_t) / self.grow_s))
            if heard > 0.9:
                self.progress = min(1.0, self.progress + 0.01)     # every sound you make, it learns a little
            if now >= self._next_address:
                lines = self.lines["address"]
                if self._address_i == 0 and self.lines.get("greeting"):
                    self._say(self.lines["greeting"], now)
                elif lines:
                    self._say(lines[(self._address_i - 1) % len(lines)] if self.lines.get("greeting")
                              else lines[self._address_i % len(lines)], now)
                self._address_i += 1
                self._next_address = now + self.address_every
        elif self.tv == "reveal":
            self.progress = min(1.0, self.progress + 0.02)
            if now >= self._next_reveal and self._reveal_i < len(self.lines["reveal"]):
                self._say(self.lines["reveal"][self._reveal_i], now)
                self._reveal_i += 1
                self._next_reveal = now + 8.0
        if self.face is not None:
            self.face.progress = self.progress
        if phase == "idle":
            self._was_in = False

        # the sound follows the dream: in an empty room the network's picture leads the music
        if self.wall is not None and self.wall.cur is not None:
            e = self.wall.energy
            cx, cy = self.wall.centroid
            idle_drive = 0.12 + 0.35 * e
            state["intensity"] = round(float(state.get("intensity", 0.0)) * self.wake + idle_drive * (1 - self.wake), 3)
            steer = dict(state.get("steer") or {})
            steer["x"] = round(float(steer.get("x", 0.0)) * self.wake + cx * (1 - self.wake), 3)
            steer["y"] = round(float(steer.get("y", 0.0)) * self.wake + cy * (1 - self.wake), 3)
            state["steer"] = steer
        state["duet"] = {"tv": self.tv, "wake": round(self.wake, 3), "progress": round(self.progress, 3)}
        state["words"] = []                       # no wall text in this show

    # ---------------------------------------------------------- drawing
    def _font(self, px: int):
        import pygame
        f = self._fonts.get(px)
        if f is None:
            f = self._fonts[px] = pygame.font.Font(None, px)
        return f

    def _grains(self, size):
        import pygame
        if not self._grain or self._grain[0].get_size() != size:
            self._grain = []
            rng = np.random.default_rng(7)
            for _ in range(6):
                n = rng.integers(0, 22, (size[0], size[1]), dtype=np.uint8)
                a = np.repeat(n[:, :, None], 3, axis=2)
                self._grain.append(pygame.surfarray.make_surface(a))
        return self._grain

    def _vig(self, size):
        import pygame
        v = self._vignette.get(size)
        if v is None:
            w, h = size
            ys, xs = np.mgrid[0:h, 0:w]
            r = np.sqrt(((xs - w / 2) / (w / 2)) ** 2 + ((ys - h / 2) / (h / 2)) ** 2)
            k = np.clip(1.25 - r * 1.25, 0, 1) ** 1.3        # round, black at the edges
            a = (np.repeat(k.T[:, :, None], 3, axis=2) * 255).astype(np.uint8)
            v = self._vignette[size] = pygame.surfarray.make_surface(a)
        return v

    def draw_wall(self, surf, now: float) -> None:
        import pygame
        w, h = surf.get_size()
        img = self.wall.frame(now) if self.wall is not None else None
        if img is None:
            surf.fill((0, 0, 0))
            return
        s = pygame.surfarray.make_surface(img.swapaxes(0, 1))
        st = self.engine.state if self.engine is not None else {}
        steer = st.get("steer") or {}
        zoom = 1.06 + 0.06 * self.wake
        sw, sh = int(w * zoom), int(h * zoom)
        big = pygame.transform.smoothscale(s, (sw, sh))
        ox = int((sw - w) / 2 * (1 + float(steer.get("x", 0.0)) * self.wake * 0.9))
        oy = int((sh - h) / 2 * (1 + float(steer.get("y", 0.0)) * self.wake * 0.9))
        if self._fb is None or self._fb.get_size() != (w, h):
            self._fb = pygame.Surface((w, h))
            self._fb.fill((0, 0, 0))
        big.set_alpha(int(255 * (0.35 + 0.4 * self.wake)))     # trails: the old dream lingers
        self._fb.blit(big, (-ox, -oy))
        surf.blit(self._fb, (0, 0))
        lvl = int(255 * (0.28 + 0.72 * self.wake))
        surf.fill((lvl, lvl, lvl), special_flags=pygame.BLEND_MULT)
        heard = float(st.get("heard", 0.0) or 0.0)
        if heard > 0.05:                                         # a jolt: a red ghost to one side
            ghost = big.copy()
            ghost.fill((int(255 * heard), 30, 30), special_flags=pygame.BLEND_MULT)
            surf.blit(ghost, (-ox + int(28 * heard), -oy), special_flags=pygame.BLEND_ADD)
        g = self._grains((w, h))
        surf.blit(g[int(now * 24) % len(g)], (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_tv(self, surf, now: float, wall_here: bool = False) -> None:
        import pygame
        w, h = surf.get_size()
        if wall_here:
            self.draw_wall(surf, now)
            if self.tv_level > 0.01:
                k = int(255 * (1 - 0.75 * self.tv_level))
                surf.fill((k, k, k), special_flags=pygame.BLEND_MULT)
        else:
            surf.fill((0, 0, 0))
        if self.tv_level <= 0.01:
            return
        if self.tv in ("face", "reveal", "gone") and self.face_dreamer is not None:
            img = self.face_dreamer.frame(now)
            if img is not None:
                p = self.progress
                f = img.astype(np.float32)
                grey = f.mean(axis=2, keepdims=True)
                sat = min(1.0, p ** 1.4)                 # grey first, colour comes last
                f = grey + (f - grey) * sat
                f = f * (0.6 + 0.4 * p)                  # dim and dull at first
                fade = min(1.0, (now - self.tv_t) / 4.0) if self.tv == "face" and p < 0.05 else 1.0
                if self.tv == "gone":
                    fade = max(0.0, 1.0 - (now - self.tv_t) / 6.0)
                f = np.clip(f * fade * self.tv_level, 0, 255).astype(np.uint8)
                s = pygame.surfarray.make_surface(f.swapaxes(0, 1))
                side = int(h * 0.82)
                s = pygame.transform.smoothscale(s, (side, side))
                s.blit(self._vig((side, side)), (0, 0), special_flags=pygame.BLEND_MULT)
                surf.blit(s, ((w - side) // 2, int(h * 0.03)), special_flags=pygame.BLEND_ADD if wall_here else 0)
        if self.caption and self.tv in ("hello", "face", "reveal"):
            age = now - self.caption_t
            shown = self.caption[: int(age * 18) + 1]               # typed
            alpha = max(0.0, min(1.0, (11.0 - age) / 2.0)) if self.tv != "hello" else 1.0
            if self.tv == "hello":
                px, y = int(h * 0.12), int(h * 0.44)
            else:
                px, y = int(h * 0.045), int(h * 0.88)
            img = self._font(px).render(shown, True, (215, 210, 200))
            img.set_alpha(int(255 * alpha * self.tv_level))
            surf.blit(img, ((w - img.get_width()) // 2, y))
        if not wall_here:
            g = self._grains((w, h))
            surf.blit(g[int(now * 24) % len(g)], (0, 0), special_flags=pygame.BLEND_ADD)

    def status(self) -> dict:
        out = {"tv": self.tv, "wake": round(self.wake, 2), "progress": round(self.progress, 2),
               "guest": bool(self.guest)}
        for name, dr in (("wall", self.wall), ("face", self.face_dreamer)):
            if dr is not None:
                out[name + "_frames"] = dr.frames
                out[name + "_ms"] = round(dr.ms, 1)
        return out


# ------------------------------------------------------------------ channel 2
from .second_screen import SecondScreen   # noqa: E402  (same window code, different picture)


class WallScreen(SecondScreen):
    """The projector: the wall picture drawn small (960x540) and scaled up by the GPU."""

    def __init__(self, duet: Duet, display_index: int = 1, fps: float = 30.0):
        super().__init__(display_index, fps)
        self.duet = duet

    def open(self) -> bool:
        ok = super().open()
        if ok and self.surface is not None and self.surface.get_size() != self.duet.wall_size:
            import pygame
            self.surface = pygame.Surface(self.duet.wall_size)
        return ok

    def update(self, state: dict, status=None, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if now < self._next or not self.open():
            return
        self._next = now + self.period
        try:
            self.duet.draw_wall(self.surface, now)
            self._present()
        except Exception as e:
            log.warning("wall screen failed (%s); closing it", e)
            self.close()
            self.failed = True

    def _present(self) -> None:
        if self.renderer is not None:
            from pygame._sdl2 import video
            tex = video.Texture.from_surface(self.renderer, self.surface)
            self.renderer.clear()
            tex.draw(dstrect=(0, 0, *self.size))
            self.renderer.present()
        else:
            import pygame
            ws = self.window.get_surface()
            pygame.transform.scale(self.surface, ws.get_size(), ws)
            self.window.flip()
