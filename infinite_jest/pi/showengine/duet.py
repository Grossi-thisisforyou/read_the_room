"""Two screens (Baby, 2026-11-23/24). Channel 1 = the TV, channel 2 = the projector on the white wall.

  empty room   TV black. The wall dreams slowly and dimly; the room only plays sound.
  someone in   the wall wakes: brighter, faster, it jolts when they move or speak.
  ~45 s in     the TV switches on and says hello. Coarse grey pieces of pictures are
               placed, shifted and stitched together.
  ~2 min in    a face starts to form between them. It comes in bursts, not steadily,
               and with every burst the pieces get clearer and move.
  after that   there is no reset: as long as someone stays it flows freely. The face
               loses ground and finds it again; new lines keep coming.
  leaving      the guest's reveal lines under the finished face, then it dissolves.

Now and then the donated footage cuts in as a short glitch. The room wakes up in a
random mood (mood.py) that colours all of it for the day.

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

from . import mood as moods
from . import hear
from . import plugins
from . import talk

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


def load_talk(guest: dict | None) -> dict:
    """Lines, questions and short facts written for this guest from the research (talk.json next
    to the guest file, kept out of the repo like the file itself)."""
    if not guest or not guest.get("_dir"):
        return {}
    try:
        with open(os.path.join(guest["_dir"], "talk.json")) as f:
            t = json.load(f)
        return {k: [str(x) for x in t.get(k, [])] for k in ("lines", "questions", "facts")}
    except (OSError, ValueError):
        return {}


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
        self._from = self._to = self._z = None
        self._tau = 0.0
        self.active = True

    def set_decoder(self, dec: Any) -> None:
        self.dec = dec

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ij-dream", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _anchors(self):
        a = getattr(self.dec, "anchors", None)
        return a if a is not None and len(a) >= 2 else None

    def jolt(self, amount: float) -> None:
        """Something happened: swerve, and head for a different picture."""
        self.walk.jolt(amount)
        if self._anchors() is not None and self._z is not None:
            self._from, self._to, self._tau = self._z.copy(), None, 0.0

    def make(self, dt: float) -> np.ndarray:
        u = self.walk.step(dt, self.speed)
        anc = self._anchors()
        if anc is None:
            z = self.dec.z_mean + self.dec.z_std * u * self.scale
        else:
            # from one remembered picture to the next, with a live wobble on top
            if self._to is None:
                self._to = anc[int(self.rng.integers(len(anc)))]
                if self._from is None:
                    self._from = anc[int(self.rng.integers(len(anc)))]
            self._tau += min(0.5, dt) * self.speed * 0.22
            if self._tau >= 1.0:
                self._from, self._to, self._tau = self._to, None, 0.0
                return self.make(0.0)
            k = self._tau * self._tau * (3 - 2 * self._tau)
            z = self._from * (1 - k) + self._to * k + self.dec.z_std * u * 0.3 * self.scale
        self._z = z
        t0 = time.perf_counter()
        img = self.dec(z)
        self.ms = self.ms * 0.9 + (time.perf_counter() - t0) * 100.0
        return img

    def _run(self) -> None:
        last = time.monotonic()
        while not self._stop.is_set():
            t0 = time.monotonic()
            if not self.active:                 # nobody sees it: leave the CPU to the rest
                last = t0
                self._stop.wait(0.2)
                continue
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
            s.z_mean, s.z_std, s.anchors = last.z_mean, last.z_std, last.anchors
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
        self.anchors = model.snaps[-1].anchors

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
        self.face_at = float(d.get("face_at_s", 120.0))       # the face starts to form this far into the visit
        self.burst_every = (float(d.get("burst_min_s", 18.0)), float(d.get("burst_max_s", 50.0)))
        self.mood = moods.throw(d.get("mood_file"), force=d.get("mood") or None)
        self.day_mood = self.mood            # the visit of a stranger bends it; the day's mood comes back after
        self.address_every = float(d.get("address_every_s", 24.0))
        self.listen_s = float(d.get("listen_s", 11.0))        # how long it waits for an answer
        self.used: set = set()        # every line it has said since it was switched on: none comes twice
        self.arc = 0.0
        self.wall_size = (int(d.get("wall_w", 960)), int(d.get("wall_h", 540)))
        self.rng = random.Random()
        self.guest = load_guest(str(d.get("guest", "001")) if d.get("guest", "001") else None)
        self.lines = self._lines(self.guest)
        self._want_guest: Any = False         # a guest picked on the control page, applied before the next visit
        self._started = False
        self._faces: dict = {}
        self.wall = self.face = None
        self.wall_fps = float(d.get("wall_fps", 8.0))
        self.face_dreamer = None
        self._models = d.get("models_dir") or os.path.join(IJ, "dream", "models")
        try:
            net = _dream_import()
            p = net.find(self._models, "wall")
            if p:
                self.wall = Dreamer(net.Decoder.load(p), float(d.get("wall_fps", 8.0)))
        except Exception:
            plugins.report(log, "dream-load", "could not load the dreaming networks")
        self._use_face()
        self.words = LiveWords(str(d.get("llm_url", "http://127.0.0.1:8080/v1/chat/completions")))
        foot = list(d.get("footage_dirs", ["/mnt/ij-stick"]))
        self.material = Material([d.get("paint_dir") or os.path.join(IJ, "visuals", "bank")], foot,
                                 float(d.get("material_every_s", 22.0)))
        self.material.footage_share = float(d.get("footage_ghost", 0.6))     # the family footage is a main voice
        self.glitch = Glitch(list(d.get("glitch_dirs", foot)), rate=float(self.mood["glitch"]))
        self.collage = Collage(os.path.join(self.guest["_dir"], "img") if self.guest else None,
                               paint_dirs=self.material.paint_dirs, footage=self.glitch,
                               camera=lambda: getattr(self.engine, "last_frame", None))
        if engine is not None and hasattr(engine, "answer_hooks"):
            engine.answer_hooks.append(self.on_answer)
            engine.control_hooks["guest"] = self.set_guest
        self.busy_file = str(d.get("busy_file", "/tmp/infinite_jest_busy"))
        self._busy_on = False
        log.info("duet: wall network %s, face network %s, guest %s", "yes" if self.wall else "NO",
                 "yes" if self.face else "NO", "yes" if self.guest else "none")
        log.info("duet: today's mood is %s; %d pictures for the collage", self.mood["name"], len(self.collage.paths))
        self.hearing = hear.Hearing(d)
        self.reserve = talk.Reserve(self.mood["name"])
        self.extra = load_talk(self.guest)                   # written for this guest from the research
        self.reset()
        self._fonts: dict[int, Any] = {}
        self._grain: list[Any] = []
        self._vignette: dict[tuple, Any] = {}
        self._holes: dict[tuple, Any] = {}
        self._fb = None

    # ---------------------------------------------------------- the two forks
    @property
    def fork(self) -> str:
        """"vetted": a booked guest with a research file; the show is made from what is known.
        "stranger": nobody the room knows; it asks, and makes the show from the answers."""
        return "vetted" if self.guest else "stranger"

    def _use_face(self) -> None:
        """The face network of the current guest. A stranger has none: their face comes from the
        room's camera, live, and is never stored."""
        gid = str(self.guest.get("guest_id")) if self.guest else None
        if gid and gid not in self._faces:
            self._faces[gid] = (None, None)
            try:
                net = _dream_import()
                sd = os.path.join(self._models, f"face_{gid}_steps")
                if os.path.exists(os.path.join(sd, "index.json")):
                    face = GrowingFace(FaceModel(sd, net))
                    dr = Dreamer(face, float(self.cfg.get("face_fps", 6.0)), reach=0.9)
                    dr.speed, dr.active = 0.35, False
                    if self._started:
                        dr.start()
                    self._faces[gid] = (face, dr)
            except Exception:
                plugins.report(log, "dream-load", "could not load the guest's face network")
        if self.face_dreamer is not None:
            self.face_dreamer.active = False
        self.face, self.face_dreamer = self._faces.get(gid, (None, None)) if gid else (None, None)

    def set_guest(self, guest_id: Any = None, now: float | None = None) -> None:
        """Control page: who is expected next. A guest id (their file is used) or nothing
        (an unknown visitor). It takes effect when the room is empty, never in the middle of a visit."""
        self._want_guest = str(guest_id).strip() if guest_id not in (None, "", "none", "stranger") else None
        if self.tv == "black" and not self._was_in:
            self._apply_guest()

    def _apply_guest(self) -> None:
        if self._want_guest is False:
            return
        want, self._want_guest = self._want_guest, False
        self.guest = load_guest(want) if want else None
        if want and self.guest is None:
            log.info("duet: no usable guest file for that id; treating the visitor as unknown")
        self.lines = self._lines(self.guest)
        self.extra = load_talk(self.guest)
        self.collage.set_pictures(os.path.join(self.guest["_dir"], "img") if self.guest else None)
        self._use_face()
        log.info("duet: next visitor is %s", "a vetted guest" if self.guest else "unknown")

    def on_answer(self, text: str) -> None:
        """Words from the visitor as text (typed on the phone, or from speech recognition if that is
        ever switched on). Kept in memory for this visit only; never written anywhere."""
        text = " ".join(str(text or "").split())[:160]
        if text and self.asking is not None:
            self.asking["text"] = text

    def _learned(self) -> list[str]:
        """What this visit's conversation has given so far, as short notes for the language model."""
        out = []
        for q, kind, text in self.profile[-5:]:
            got = f'they answered "{text}"' if text else {"none": "they stayed silent", "short": "they answered briefly",
                                                          "long": "they talked for a long time"}[kind]
            out.append(f"asked {q} {got}")
        return out

    def _drift(self) -> None:
        """An unknown visitor has no file, so the show is made from how they answer: silence darkens
        and slows the room, talk warms and speeds it. (With words, the local model also picks up on them.)"""
        last = [k for _, k, _ in self.profile[-4:]]
        if not last:
            return
        talk_share = sum({"none": 0.0, "short": 0.5, "long": 1.0}[k] for k in last) / len(last)
        base = self.day_mood
        m = dict(base)
        m["dark"] = min(1.0, max(0.0, base["dark"] + 0.45 * (0.5 - talk_share)))
        m["warm"] = min(1.0, max(0.0, base["warm"] + 0.5 * (talk_share - 0.5)))
        m["pace"] = min(1.0, max(0.0, base["pace"] + 0.4 * (talk_share - 0.4)))
        m["glitch"] = min(1.0, max(0.0, base["glitch"] + 0.3 * (0.5 - talk_share)))
        self.mood = m
        self.glitch.rate = float(m["glitch"])

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
        self._reveal: list = []
        self._next_reveal = 0.0
        self._last_heard = 0.0
        self._was_in = False
        self._today_said = False
        self._visit_said: set = set()       # the guest file's lines: once per visit
        self.asking = None                  # the question it is waiting on: {"q", "from", "until", "voiced", "last"}
        self.profile: list = []             # this visit's conversation: (question, none|short|long, text or "")
        self.echo: list = []                # the visitor's own words, shown back on the TV (this visit only)
        if hasattr(self, "day_mood"):
            self.mood = self.day_mood
            if getattr(self, "glitch", None) is not None:
                self.glitch.rate = float(self.mood["glitch"])
        self.listening = 0.0
        self.turns = 0
        self._wave = None                   # the tide: (start, length, height)
        self._asked_t = 0.0
        self.target = 0.0            # where the face is heading; it moves in bursts
        self.burst = 0.0             # 1 at a burst, fades over a few seconds (picture and music follow)
        self.bursts = 0
        self._next_burst = 0.0
        self._last_now = 0.0
        if getattr(self, "collage", None) is not None:
            self.collage.clear()

    def start(self) -> None:
        self._started = True
        self.hearing.warm()
        for dr in [self.wall, self.glitch] + [f[1] for f in self._faces.values()]:
            if dr is not None:
                dr.start()

    def stop(self) -> None:
        for dr in [self.wall, self.glitch] + [f[1] for f in self._faces.values()]:
            if dr is not None:
                dr.stop()
        self._busy(False)

    # ---------------------------------------------------------- logic
    def _say(self, text: str | None, now: float, show: bool = True) -> None:
        if not text:
            return
        self.used.add(talk.norm(text))
        self._visit_said.add(talk.norm(text))
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
            self._apply_guest()
            self.reset()
            self._was_in = True
            self.words.ask(self.guest, self.mood, avoid=self._recent(), facts=self._facts())   # new lines, now
            self._asked_t = now
        dt = min(1.0, max(0.0, now - self._last_now)) if self._last_now else 0.0
        self._last_now = now
        pace = float(self.mood["pace"])
        self.material.update(self.wake)
        heard = float(state.get("heard", 0.0) or 0.0)
        motion = float((state.get("sensor") or {}).get("motion", 0.0) or 0.0)
        fresh = heard > 0.9 and now - self._last_heard > 1.0       # a new sound, not the tail of the last one
        if fresh:
            self._last_heard = now

        # the wall: asleep, awake, or pushed by the visitor
        want = 0.0 if phase in ("idle", "wipe") else 1.0
        self.wake += (want - self.wake) * min(1.0, 0.02 + (0.06 if want > self.wake else 0.01))
        if self.wall is not None:
            self.wall.speed = (0.12 + 0.55 * self.wake) * (0.7 + 0.6 * pace) * (0.6 + 0.9 * self.arc) \
                + 1.5 * heard + 1.2 * motion
            self.wall.scale = 0.8 + 0.5 * self.wake
            if fresh:
                self.wall.jolt(1.2)

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
                self._reveal = list(self.lines["reveal"])
                if self.fork == "stranger" and self.profile:       # the ending is made from this conversation
                    n, m = len(self.profile), sum(1 for _, k, _ in self.profile if k != "none")
                    made = ["i asked you %d question%s. you answered %s." % (
                        n, "" if n == 1 else "s", "none" if m == 0 else "all of them" if m == n else str(m))]
                    made += ["you said: %s. i am forgetting it now." % t for t in self.echo[-2:]]
                    self._reveal = [x for x in made if talk.norm(x) not in self.used] + self._reveal[-1:]
        tv_on = self.tv in ("hello", "face", "reveal")
        self.tv_level += ((1.0 if tv_on else 0.0) - self.tv_level) * (0.04 if tv_on else 0.03)

        self.burst *= math.exp(-dt / 3.0)
        if self.tv == "face":
            # the face comes in bursts: nothing for a while, then a step at once. When it is all
            # there the visit does not end: it loses ground and finds it again, for as long as they stay.
            if self._next_burst <= 0.0:
                self._next_burst = now + max(1.0, self.face_at - self.tv_at - 5.0)
            if fresh:
                self._next_burst = max(now + 1.0, self._next_burst - 4.0)   # every sound brings the next step closer
            if now >= self._next_burst:
                if self.target >= 0.999:
                    self.target = self.rng.uniform(0.45, 0.8)
                else:
                    self.target = min(1.0, self.target + self.rng.uniform(0.07, 0.2))
                    if self.target > 0.93:
                        self.target = 1.0
                self.burst, self.bursts = 1.0, self.bursts + 1
                self.collage.burst()
                if self.face_dreamer is not None:
                    self.face_dreamer.jolt(0.8)
                lo, hi = self.burst_every
                k = (1.3 - 0.6 * pace) * (1.6 if self.target >= 0.999 else 1.0)
                self._next_burst = now + self.rng.uniform(lo, hi) * k
            self.progress += (self.target - self.progress) * (1.0 - math.exp(-dt / 0.7))
            self._converse(now, dt)
            if (len(self.words.lines) < 3 or len(self.words.questions) < 2) and not self.words.busy \
                    and now - self._asked_t > float(self.cfg.get("words_every_s", 40.0)):
                self.words.ask(self.guest, self.mood, keep=True, avoid=self._recent(), facts=self._facts())
                self._asked_t = now
        elif self.tv == "reveal":
            self.target = 1.0
            self.progress = min(1.0, self.progress + 0.02)
            if now >= self._next_reveal and self._reveal_i < len(self._reveal):
                self._say(self._reveal[self._reveal_i], now)
                self._reveal_i += 1
                self._next_reveal = now + 8.0
        if self.face is not None:
            self.face.progress = self.progress
        if phase == "idle":
            if self._was_in:
                self.profile, self.echo = [], []       # what they said is gone with them
                self.mood = self.day_mood
            self._was_in = False
            self._apply_guest()
        if self.tv in ("black", "gone"):
            self.collage.drop_camera()
        # the painter pauses while someone is here (the picture and the face get the CPU)
        self._busy(in_room or self.tv in ("hello", "face", "reveal"))
        if self.face_dreamer is not None:          # the face is only dreamt while the TV shows it
            self.face_dreamer.active = self.tv in ("hello", "face", "reveal", "gone")
        if self.wall is not None:                 # while the face grows, the wall dreams a little slower (CPU)
            self.wall.fps = self.wall_fps * (0.6 if self.tv in ("hello", "face", "reveal") else 1.0)
            if self.wake < 0.1:                   # empty room, hours on end: dream slowly and keep the Pi cool
                self.wall.fps = min(self.wall.fps, float(self.cfg.get("idle_fps", 2.5)))
        glitching = self.glitch.update(now, self.wake, tv_on=self.tv in ("face", "reveal"))
        state["glitch"] = 1.0 if glitching else 0.0
        state["mood"] = moods.for_state(self.mood)

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
        want_arc = self._tide(now, in_room)
        self.arc += (want_arc - self.arc) * min(1.0, dt / 2.0) if dt else 0.0
        if in_room:
            state["intensity"] = round(0.2 + 0.75 * self.arc, 3)
        if self.tv != "face":
            self.asking, self.listening = None, 0.0
        state["duet"] = {"tv": self.tv, "wake": round(self.wake, 3), "progress": round(self.progress, 3),
                         "burst": round(self.burst, 3), "arc": round(self.arc, 3),
                         "listening": 1 if self.listening else 0}
        state["words"] = []                       # no wall text in this show

    # ---------------------------------------------------------- talking
    def _recent(self) -> list[str]:
        return list(self.used)[-14:]

    def _facts(self) -> list[str]:
        if self.fork == "stranger":
            return self._learned()
        f = list(self.extra.get("facts") or [])
        self.rng.shuffle(f)
        return f[:3] + self._learned()[-2:]

    def _fresh(self, pool: list, once_per_visit: bool = False) -> str | None:
        """The first line in the pool that has not been said (it is taken out of the pool)."""
        seen = self._visit_said if once_per_visit else self.used
        while pool:
            line = pool.pop(0)
            if talk.norm(line) not in seen:
                return line
        return None

    def _statement(self) -> str | None:
        """Something new to say: from the local model, else written for this guest, else its own."""
        if self._address_i == 0 and self.lines.get("greeting"):
            return self.lines["greeting"]
        if self.fork == "stranger" and self._address_i == 0:
            return self._fresh(list(talk.STRANGER)) or "i do not know you."
        if not self._today_said and self.day_mood.get("today"):
            self._today_said = True
            return self.day_mood["today"]
        guest = [x for x in self.lines["address"] if not x.rstrip().endswith("?")]
        own = [x for x in guest if talk.norm(x) not in self._visit_said]
        if own and self.turns % 3 == 0:
            return own[0]                                      # the guest file's lines: once a visit, spread out
        return (self._fresh(self.words.lines) or self._fresh(list(self.extra.get("lines") or []))
                or (own[0] if own else None) or self.reserve.statement(self.used))

    def _question(self) -> str | None:
        guest = [x for x in self.lines["address"] if x.rstrip().endswith("?")]
        return (self._fresh(guest, once_per_visit=True) if self.turns < 2 else None) \
            or self._fresh(self.words.questions) or self._fresh(list(self.extra.get("questions") or [])) \
            or self.reserve.question(self.used) or self._fresh(guest, once_per_visit=True)

    def _voice_now(self) -> bool:
        ls = getattr(self.engine, "listen", None)
        return bool(ls is not None and (getattr(ls, "_voiced", False) or getattr(ls, "_loud", False)))

    def _converse(self, now: float, dt: float) -> None:
        """Its side of a conversation. It says something, then asks, then waits and listens.
        It cannot understand words (nothing is recorded or transcribed): it hears whether the
        visitor answers and for how long, answers that, and lets the local model think of what
        to say and ask next."""
        a = self.asking
        if a is not None:
            text = a.get("text", "")
            if now >= a["from"] or text:
                self.listening = 1.0
                if self._voice_now() and "hearing" not in a:
                    a["voiced"] += dt
                    a["last"] = now
                done = bool(text) or (a["voiced"] > 0.25 and now - a["last"] > 2.2) or now >= a["until"]
                if done and not text and a["voiced"] > 0.25 and "hearing" not in a:
                    # they answered: have the words made out (on the Pi, a few seconds), then go on
                    a["hearing"] = now
                    if self.hearing.listen(now - a["from"] + 1.0, lambda t, a=a: a.__setitem__("text", t) or a.__setitem__("got", True)):
                        return
                if "hearing" in a and not a.get("got") and now - a["hearing"] < 9.0 and self.hearing.busy:
                    return
                if done:
                    kind = "none" if a["voiced"] < 0.25 else "short" if a["voiced"] < 2.5 else "long"
                    if text:
                        kind = "long" if len(text.split()) > 4 else "short"
                        try:
                            from .visit import visible_text
                            shown = visible_text(text.lower())
                        except Exception:
                            shown = ""
                        if shown:
                            self.echo = (self.echo + [shown])[-4:]
                    self.asking, self.listening = None, 0.0
                    self.turns += 1
                    self.profile.append((a["q"], kind, text))
                    if self.fork == "stranger":
                        self._drift()
                    shown = self.echo[-1] if text and self.echo else ""
                    self._say((self.reserve.heard(shown, self.used) if shown else None)
                              or self._fresh(self.words.replies.pop(kind, [])) or self.reserve.reply(kind, self.used), now)
                    self.words.answer(a["q"], kind, self.guest, self.mood, avoid=self._recent(), text=text,
                                      learned=self._learned()[:-1])
                    if kind != "none":
                        self._next_burst = max(now + 1.0, self._next_burst - 6.0)   # an answer brings the face on
                    self._next_address = now + self.address_every * 0.6
            return
        if now < self._next_address:
            return
        ask = self._address_i >= 2 and self._address_i % 2 == 0
        if self.fork == "stranger":                             # it knows nothing: it asks from the start
            ask = self._address_i >= 1 and self._address_i % 3 != 0
        line = self._question() if ask else self._statement()
        if line:
            self._say(line, now)
            if ask:
                start = now + 1.0 + 0.075 * len(line)           # not while it is still speaking itself
                self.asking = {"q": line, "from": start, "until": start + self.listen_s, "voiced": 0.0, "last": now}
        self._address_i += 1
        self._next_address = now + self.address_every

    def _tide(self, now: float, in_room: bool) -> float:
        """The long wave everything rides on: it builds slowly, peaks, falls away, and builds
        again, each time for a different length and to a different height."""
        if not in_room:
            self._wave = None
            return 0.12 + 0.08 * math.sin(now / 47.0)
        if self._wave is None or now >= self._wave[0] + self._wave[1]:
            k = 1.3 - 0.6 * float(self.mood["pace"])
            first = self._wave is None
            self._wave = (now, self.rng.uniform(150.0, 330.0) * k * (0.7 if first else 1.0), self.rng.uniform(0.7, 1.0))
        t0, length, height = self._wave
        x = (now - t0) / length
        if x < 0.62:
            y = 0.08 + 0.92 * (x / 0.62) ** 1.6
        elif x < 0.78:
            y = 1.0
        elif x < 0.9:
            y = 1.0 - 0.92 * ((x - 0.78) / 0.12) ** 0.7
        else:
            y = 0.08
        return y * height

    def _busy(self, on: bool) -> None:
        """While the face grows, the background painter pauses (it watches this file)."""
        if on == self._busy_on:
            return
        self._busy_on = on
        try:
            if on:
                open(self.busy_file, "w").close()
            elif os.path.exists(self.busy_file):
                os.remove(self.busy_file)
        except OSError:
            pass

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

    def _camera_face(self):
        """A stranger's face: what the camera sees now, coarse at first and clearer with every burst.
        Nothing is kept: each frame replaces the last, and the wipe clears it."""
        f = getattr(self.engine, "last_frame", None)
        if f is None or f.ndim != 3 or min(f.shape[:2]) < 16:
            return None
        h, w = f.shape[:2]
        side = min(h, w)
        f = f[(h - side) // 2:(h - side) // 2 + side, (w - side) // 2:(w - side) // 2 + side, :3]
        n = int(6 + 122 * min(1.0, self.progress) ** 1.5)        # 6x6 blocks .. 128x128
        idx = (np.arange(n) * side / n).astype(int)
        small = f[idx][:, idx]
        up = (np.arange(128) * n / 128).astype(int)
        return small[up][:, up]

    def _hole(self, size, k: float):
        """A dark place in the middle of the pieces for the face to stand in (deeper as it forms)."""
        import pygame
        key = (size, int(k * 8))
        v = self._holes.get(key)
        if v is None:
            w, h = size
            ys, xs = np.mgrid[0:h, 0:w]
            r = np.sqrt(((xs - w / 2) / (w / 2)) ** 2 + ((ys - h / 2) / (h / 2)) ** 2)
            m = 1.0 - np.clip(1.15 - r * 1.25, 0, 1) ** 0.8 * (key[1] / 8.0)
            a = (np.repeat(m.T[:, :, None], 3, axis=2) * 255).astype(np.uint8)
            v = self._holes[key] = pygame.surfarray.make_surface(a)
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
        a = self.material.alpha()
        if a > 0.0:
            kind, m = self.material.frame()
            if m is not None:
                f = m.astype(np.float32)
                if kind == "footage":                         # a memory: faded colour, a little warm
                    g = f.mean(axis=2, keepdims=True)
                    f = (g * 0.5 + f * 0.5) * np.array([1.05, 0.96, 0.86], np.float32)
                ms = pygame.surfarray.make_surface(np.clip(f, 0, 255).astype(np.uint8).swapaxes(0, 1))
                ms = pygame.transform.smoothscale(ms, (sw, sh))
                ms.set_alpha(int(255 * a * (0.85 if kind == "footage" else 0.7)))
                big.blit(ms, (0, 0))
        big.set_alpha(int(255 * (0.35 + 0.4 * self.wake)))     # trails: the old dream lingers
        self._fb.blit(big, (-ox, -oy))
        surf.blit(self._fb, (0, 0))
        lvl = 255 * (0.28 + 0.72 * self.wake) * (1.0 - 0.22 * float(self.mood["dark"]))
        surf.fill(tuple(int(min(255, lvl * c)) for c in self.mood["tint"]), special_flags=pygame.BLEND_MULT)
        heard = float(st.get("heard", 0.0) or 0.0)
        if heard > 0.05:                                         # a jolt: a red ghost to one side
            ghost = big.copy()
            ghost.fill((int(255 * heard), 30, 30), special_flags=pygame.BLEND_MULT)
            surf.blit(ghost, (-ox + int(28 * heard), -oy), special_flags=pygame.BLEND_ADD)
        g = self._grains((w, h))
        surf.blit(g[int(now * 24) % len(g)], (0, 0), special_flags=pygame.BLEND_ADD)
        self._draw_glitch(surf, now, img)

    def _draw_glitch(self, surf, now: float, fallback=None) -> None:
        """The footage breaks in: a hard cut over all or a band of the picture."""
        import pygame
        a = self.glitch.frame(now, fallback)
        if a is None:
            return
        w, h = surf.get_size()
        y0, y1 = int(self.glitch.band[0] * h), int(self.glitch.band[1] * h)
        gs = pygame.transform.scale(pygame.surfarray.make_surface(a.swapaxes(0, 1)), (w, h))
        surf.blit(gs, (0, y0), (0, y0, w, max(1, y1 - y0)))

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
        pieces = self.tv in ("face", "reveal", "gone")
        lvl = self.tv_level * (max(0.0, 1.0 - (now - self.tv_t) / 6.0) if self.tv == "gone" else 1.0)
        if pieces:
            self.collage.step(now, (w, h), self.progress, float(self.mood["pace"]))
            self.collage.draw(surf, now, lvl, front=False)
        if pieces:
            live = self.face_dreamer is None
            img = self._camera_face() if live else self.face_dreamer.frame(now)
            if img is not None:
                p = self.progress
                f = img.astype(np.float32)
                grey = f.mean(axis=2, keepdims=True)
                sat = 0.0 if live else min(1.0, p ** 1.4)      # grey first, colour comes last
                f = grey + (f - grey) * sat
                f = f * (0.3 + 0.7 * min(1.0, p * 2.5 + 0.25 * self.burst))   # hardly there at first
                fade = min(1.0, (now - self.tv_t) / 4.0) if self.tv == "face" and p < 0.05 else 1.0
                if self.tv == "gone":
                    fade = max(0.0, 1.0 - (now - self.tv_t) / 6.0)
                f = np.clip(f * fade * self.tv_level, 0, 255).astype(np.uint8)
                s = pygame.surfarray.make_surface(f.swapaxes(0, 1))
                side = int(h * 0.82)
                s = pygame.transform.smoothscale(s, (side, side))
                s.blit(self._vig((side, side)), (0, 0), special_flags=pygame.BLEND_MULT)
                # the face is laid in strips; after a burst they are out of place and settle again
                x0, y0, offs = (w - side) // 2, int(h * 0.03), self.collage.offsets
                surf.blit(self._hole((side, side), min(1.0, 0.35 + p)), (x0, y0), special_flags=pygame.BLEND_MULT)
                sh = side // len(offs) + 1
                for i, o in enumerate(offs):
                    dx = int(o * side * (0.05 + 0.2 * (1.0 - p)))
                    surf.blit(s, (x0 + dx, y0 + i * sh), (0, i * sh, side, sh), special_flags=pygame.BLEND_ADD)
        if pieces:
            self.collage.draw(surf, now, lvl, front=True)
            if self.glitch.on_tv:
                self._draw_glitch(surf, now)
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
        if self.echo and self.tv in ("face", "reveal"):            # their own words, handed back (this visit only)
            f = self._font(int(h * 0.032))
            for i, t in enumerate(self.echo):
                img = f.render(t[:60], True, (150, 146, 138))
                img.set_alpha(int(255 * self.tv_level * (0.35 + 0.65 * (i + 1) / len(self.echo))))
                surf.blit(img, (int(w * (0.06 + 0.11 * (i % 2))), int(h * (0.62 + 0.055 * i))))
        if self.listening and self.tv == "face":                  # it waits for an answer: a line that breathes
            a = self.asking or {}
            k = 0.5 + 0.5 * math.sin(now * 2.2)
            half = int(w * (0.03 + 0.012 * k + min(0.2, 0.05 * float(a.get("voiced", 0.0)))))
            c = int(120 + 100 * k) if not self._voice_now() else 255
            pygame.draw.line(surf, (c, c, c), (w // 2 - half, int(h * 0.955)), (w // 2 + half, int(h * 0.955)), max(1, h // 400))
        if not wall_here:
            g = self._grains((w, h))
            surf.blit(g[int(now * 24) % len(g)], (0, 0), special_flags=pygame.BLEND_ADD)

    def status(self) -> dict:
        out = {"tv": self.tv, "wake": round(self.wake, 2), "progress": round(self.progress, 2),
               "guest": bool(self.guest), "fork": self.fork, "answers": len(self.profile),
               "next_guest": None if self._want_guest is False else (self._want_guest or "unknown"),
               "mood": self.mood["name"], "bursts": self.bursts,
               "glitches": self.glitch.count, "footage_ready": len(self.glitch.runs),
               "pictures": len(self.collage.paths), "new_lines": self.words.got,
               "pieces": dict(self.collage.counts), "clips_ready": len(self.glitch.clips),
               "turns": self.turns, "arc": round(self.arc, 2), "said": len(self.used),
               "speech_to_text": self.hearing.available(), "understood": self.hearing.heard,
               "speech_ms": round(self.hearing.ms)}
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


# ------------------------------------------------------------------ the local language model
class LiveWords:
    """New lines from the local language model (llama-server on 127.0.0.1:8080), all through the
    visit: things to say, questions to ask, and what to say after an answer. Runs in a thread;
    if the model isn't there or is slow, the room uses its own reserve (talk.py)."""

    SYSTEM = ("You are the voice of a dark art installation: a room that watches one visitor and slowly "
              "builds their face on a screen out of old family films and pictures. You speak in the first "
              "person, lowercase, in short plain sentences of at most ten words. You are cold and tender "
              "at once. You talk about yourself and your feelings as much as about them. No names, no "
              "brands, no artists, no emojis, no quotation marks, no explanations.")
    HEARD = {"none": "They stayed silent.", "short": "They answered with only a word or two.",
             "long": "They spoke for a long time."}

    def __init__(self, url: str = "http://127.0.0.1:8080/v1/chat/completions", timeout: float = 40.0):
        self.url = url
        self.timeout = timeout
        self.lines: list[str] = []          # things to say
        self.questions: list[str] = []      # things to ask
        self.replies: dict[str, list[str]] = {}
        self.busy = False
        self.asked = 0
        self.got = 0
        self._lock = threading.Lock()

    def ask(self, guest: dict | None, mood: dict | None = None, keep: bool = False,
            avoid: list[str] | None = None, facts: list[str] | None = None) -> None:
        if self.busy:
            return
        self.busy = True
        if not keep:
            self.lines, self.questions = [], []
        self.asked += 1
        threading.Thread(target=self._run, args=(self._prompt(guest, mood, avoid, facts), None),
                         name="ij-words", daemon=True).start()

    def answer(self, question: str, kind: str, guest: dict | None, mood: dict | None = None,
               avoid: list[str] | None = None, text: str = "", learned: list[str] | None = None) -> None:
        """The visitor has (or has not) answered: think of what to say to that and what to ask next.
        The result goes to the front of the queues."""
        if self.busy:
            return
        self.busy = True
        feel = f"Today you are {mood['voice']}. " if mood and mood.get("voice") else ""
        before = ("Earlier in this conversation: " + "; ".join(learned[-4:]) + ". ") if learned else ""
        if text:
            heard = (f'They answered: "{text}". Write two lines: first what you say now about their answer, '
                     "then one new short question that goes deeper into what they said.")
        else:
            heard = (f"{self.HEARD.get(kind, '')} You cannot understand words, you only hear whether and how long "
                     "they speak. Write two lines: first what you say now about that, then one new short question for them.")
        msgs = [{"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": f"{feel}{before}You asked the visitor: {question} {heard}"
                 + self._avoid(avoid)}]
        threading.Thread(target=self._run, args=(msgs, True), name="ij-words", daemon=True).start()

    @staticmethod
    def _avoid(avoid: list[str] | None) -> str:
        return (" Never repeat any of these: " + " / ".join(avoid[-10:])) if avoid else ""

    def _prompt(self, g: dict | None, mood: dict | None = None, avoid: list[str] | None = None,
                facts: list[str] | None = None) -> list:
        about = ""
        if g:
            bits = [", ".join(g.get("themes") or []), ", ".join(w.lower() for w in (g.get("words") or []))]
            about = "What you know about this visitor: " + "; ".join(b for b in bits if b) + "."
        if facts:
            about += (" From their file and this conversation: " if g else
                      " You do not know this visitor. What this conversation gave you so far: ") + "; ".join(facts) + "."
        elif not g:
            about = "You do not know this visitor at all. You want to find out who they are."
        feel = f"Today you are {mood['voice']}. " if mood and mood.get("voice") else ""
        return [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": f"{about} {feel}Their face is slowly appearing on a screen in front of them. "
             "This is how you sound: today i miss someone i have not met. / i kept a place for you before "
             "i knew you. Write five new things you say and then three short questions you ask them "
             "(each question ends with a question mark). One per line, no numbering." + self._avoid(avoid)},
        ]

    def _run(self, msgs: list, front) -> None:
        import urllib.request
        try:
            body = json.dumps({"messages": msgs, "max_tokens": 80 if front else 220, "temperature": 1.05,
                               "top_p": 0.95, "repeat_penalty": 1.15,
                               "seed": random.randint(0, 2 ** 31 - 1)}).encode()
            req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            new = clean_lines(text)
            qs = [x for x in new if x.endswith("?")]
            st = [x for x in new if not x.endswith("?")]
            with self._lock:
                if front:
                    self.lines = st[:1] + self.lines
                    self.questions = qs[:1] + self.questions
                else:
                    self.lines += [x for x in st if x not in self.lines]
                    self.questions += [x for x in qs if x not in self.questions]
            self.got += len(new)
            log.info("duet: %d new lines from the local model", len(new))
        except Exception as e:
            log.info("duet: local model not available (%s); the room uses its own lines", type(e).__name__)
        finally:
            self.busy = False


def clean_lines(text: str) -> list[str]:
    out = []
    for raw in str(text).splitlines():
        s = raw.strip().lstrip("-*0123456789.) ").strip().strip('"\'').strip().lower()
        if not s or len(s) > 70 or len(s.split()) > 12:
            continue
        try:
            from .visit import visible_text
            s = visible_text(s)
        except Exception:
            pass
        if s:
            out.append(s)
    return out[:8]


# ------------------------------------------------------------------ material that drifts through the dream
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mpg", ".mts", ".3gp")
IMAGE_EXT = (".png", ".jpg", ".jpeg")


class Material:
    """Every so often something surfaces in the wall's dream: the newest painting the Pi
    made (stable-diffusion.cpp, painting in the background), or a few seconds of the
    donated footage, ghostly and grey. Everything is read where it lies; nothing is copied."""

    def __init__(self, paint_dirs: list[str], footage_dirs: list[str], every_s: float = 40.0):
        self.paint_dirs = [os.path.expanduser(p) for p in paint_dirs]
        self.footage_dirs = [os.path.expanduser(p) for p in footage_dirs]
        self.every_s = every_s
        self.rng = random.Random()
        self.kind = None             # "paint" | "footage" | None
        self.img = None              # numpy frame (H, W, 3) uint8
        self.t0 = 0.0
        self.dur = 0.0
        self.next_t = 0.0
        self._videos: list[str] = []
        self._videos_t = -1e9
        self._seen_paint: set = set()
        self._lock = threading.Lock()
        self._busy = False
        self.footage_share = 0.4     # how often the slow ghost is footage rather than a painting

    def alpha(self) -> float:
        if self.kind is None or self.img is None:
            return 0.0
        t = time.monotonic() - self.t0
        if t < 0 or t > self.dur:
            return 0.0
        return min(1.0, t / 3.0, (self.dur - t) / 3.0)

    def update(self, wake: float) -> None:
        now = time.monotonic()
        if self.kind is not None and now - self.t0 > self.dur:
            with self._lock:
                self.kind, self.img = None, None
            self.next_t = now + self.every_s * self.rng.uniform(0.6, 1.3) * (1.4 - 0.6 * wake)
        if self.kind is None and now >= self.next_t and not self._busy:
            self.next_t = now + 10.0
            self._busy = True
            threading.Thread(target=self._pick, args=(now,), name="ij-material", daemon=True).start()

    def _newest_painting(self) -> str | None:
        best, best_t = None, 0.0
        for d in self.paint_dirs:
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if x != "derived"]
                for f in files:
                    if f.lower().endswith(IMAGE_EXT):
                        p = os.path.join(root, f)
                        try:
                            t = os.path.getmtime(p)
                        except OSError:
                            continue
                        if t > best_t and p not in self._seen_paint:
                            best, best_t = p, t
        return best

    def _list_videos(self) -> list[str]:
        if time.monotonic() - self._videos_t > 600:
            found = []
            for d in self.footage_dirs:
                for root, dirs, files in os.walk(d):
                    dirs[:] = [x for x in dirs if not x.startswith(".") and x != "ij-offline"]
                    found += [os.path.join(root, f) for f in files
                              if f.lower().endswith(VIDEO_EXT) and not f.startswith("._")]
                    if len(found) > 5000:
                        break
            self._videos, self._videos_t = found, time.monotonic()
        return self._videos

    def _pick(self, now: float) -> None:
        try:
            p = self._newest_painting()
            vids = self._list_videos()
            if p and (not vids or self.rng.random() >= self.footage_share):
                self._seen_paint.add(p)
                self._show_painting(p, now)
            elif vids and (p is None or self.rng.random() < self.footage_share * 2):
                self._play(self.rng.choice(vids), now)
        except Exception:
            log.info("duet: material skipped", exc_info=True)
        finally:
            self._busy = False

    def _show_painting(self, path: str, now: float) -> None:
        import pygame
        s = pygame.image.load(path)
        a = pygame.surfarray.array3d(s).swapaxes(0, 1)
        with self._lock:
            self.kind, self.img, self.t0, self.dur = "paint", a, time.monotonic(), 14.0

    def _play(self, path: str, now: float) -> None:
        """A few seconds of one clip, from a random point, at 8 fps and 320x180 (ffmpeg)."""
        import shutil
        import subprocess
        ff = shutil.which("ffmpeg")
        dur = self.rng.uniform(14.0, 28.0)
        if ff is None:
            return self._play_cv2(path, dur)
        start = self.rng.uniform(0, 1) * self._length(path)
        w, h = 320, 180
        cmd = [ff, "-v", "error", "-ss", f"{start:.1f}", "-i", path, "-t", f"{dur:.1f}", "-an",
               "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=8",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        first = True
        try:
            while True:
                buf = p.stdout.read(w * h * 3)
                if len(buf) < w * h * 3:
                    break
                frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                with self._lock:
                    if first:
                        self.kind, self.t0, self.dur, first = "footage", time.monotonic(), dur, False
                    self.img = frame
                time.sleep(0.12)
        finally:
            p.kill()

    def _play_cv2(self, path: str, dur: float) -> None:
        try:
            import cv2
        except ImportError:
            return
        cap = cv2.VideoCapture(path)
        try:
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            if n > fps * 20:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(self.rng.uniform(0, n - fps * 16)))
            step = max(1, int(round(fps / 8)))
            t_end, first, i = time.monotonic() + dur, True, 0
            while time.monotonic() < t_end:
                ok, fr = cap.read()
                if not ok:
                    break
                i += 1
                if i % step:
                    continue
                fr = cv2.resize(fr, (320, 180))[:, :, ::-1].copy()
                with self._lock:
                    if first:
                        self.kind, self.t0, self.dur, first = "footage", time.monotonic(), dur, False
                    self.img = fr
                time.sleep(0.1)
        finally:
            cap.release()

    @staticmethod
    def _length(path: str) -> float:
        import shutil
        import subprocess
        fp = shutil.which("ffprobe")
        if fp is None:
            return 0.0
        try:
            out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                 capture_output=True, text=True, timeout=10).stdout
            return max(0.0, float(out.strip()) - 15.0)
        except Exception:
            return 0.0

    def frame(self):
        with self._lock:
            return self.kind, self.img


# ------------------------------------------------------------------ the footage breaks in
class Glitch:
    """Now and then the donated footage cuts into the picture for a fraction of a second:
    hard, torn, repeated, gone. Which clip, which moment and when are all random.

    A helper thread keeps a few short runs of frames ready (read from the stick where they
    lie, never copied to disk), so a glitch costs nothing at the moment it fires. Without
    footage the dream itself tears instead."""

    SIZE = (320, 180)

    def __init__(self, footage_dirs: list[str], rate: float = 0.5, seed: int | None = None):
        self.dirs = [os.path.expanduser(p) for p in footage_dirs]
        self.rate = rate                 # 0 (rare) .. 1 (often): the mood of the day
        self.rng = random.Random(seed)
        self.runs: list[list[np.ndarray]] = []
        self.want_runs = 3
        self.clips: list[list[np.ndarray]] = []      # a few seconds each, for the moving pieces on the TV
        self.want_clips = 4
        self.t0 = self.t1 = -1.0         # the running glitch, engine time
        self.next_t = 0.0
        self.run: list[np.ndarray] = []
        self.band = (0.0, 1.0)           # the part of the picture it takes (top, bottom)
        self.on_tv = False
        self.count = 0
        self._tear = 0
        self._videos: list[str] = []
        self._len: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._fill, name="ij-glitch", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def active(self, now: float) -> bool:
        return self.t0 <= now < self.t1

    def update(self, now: float, wake: float, tv_on: bool = False) -> bool:
        """Call every tick. Returns True while a glitch is running."""
        if self.next_t <= 0.0:
            self.next_t = now + self._gap(wake)
        if now >= self.next_t and not self.active(now):
            self.fire(now, tv_on=tv_on and self.rng.random() < 0.35)
            self.next_t = now + self._gap(wake)
        return self.active(now)

    def _gap(self, wake: float) -> float:
        mean = (45.0 - 36.0 * self.rate) * (3.0 - 2.0 * min(1.0, max(0.0, wake)))
        return max(2.0, self.rng.expovariate(1.0 / mean))

    def fire(self, now: float, dur: float | None = None, tv_on: bool = False) -> None:
        with self._lock:
            self.run = self.runs.pop(self.rng.randrange(len(self.runs))) if self.runs else []
        self.t0 = now
        self.t1 = now + (dur if dur is not None else self.rng.uniform(0.1, 0.6))
        y0 = self.rng.choice((0.0, 0.0, self.rng.uniform(0.0, 0.6)))
        self.band = (y0, 1.0 if y0 == 0.0 and self.rng.random() < 0.7 else min(1.0, y0 + self.rng.uniform(0.2, 0.5)))
        self.on_tv = tv_on
        self._tear = self.rng.randrange(1 << 30)
        self.count += 1

    def frame(self, now: float, fallback: np.ndarray | None = None) -> np.ndarray | None:
        """The torn picture for this moment (H, W, 3 uint8), or None when no glitch runs."""
        if not self.active(now):
            return None
        k = int((now - self.t0) * 12.0)
        if self.run:
            src = self.run[(k // 2 * 2 if self._tear & 1 else k) % len(self.run)]      # some stutter
        elif fallback is not None:
            src = fallback
        else:
            return None
        rng = np.random.default_rng(self._tear + k)
        a = src.astype(np.int16)
        a = np.clip((a - 110) * 1.5 + 120, 0, 255).astype(np.uint8)                  # harsh
        h = a.shape[0]
        for _ in range(int(rng.integers(2, 6))):                                     # torn rows
            y = int(rng.integers(0, h - 4))
            hh = int(rng.integers(3, max(4, h // 4)))
            a[y:y + hh] = np.roll(a[y:y + hh], int(rng.integers(-a.shape[1] // 3, a.shape[1] // 3)), axis=1)
        a[:, :, 0] = np.roll(a[:, :, 0], int(rng.integers(2, 9)), axis=1)             # colours come apart
        a[:, :, 2] = np.roll(a[:, :, 2], -int(rng.integers(2, 9)), axis=1)
        return a

    # -- the helper thread
    def _list(self) -> list[str]:
        found = []
        for d in self.dirs:
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if not x.startswith(".") and x != "ij-offline"]
                found += [os.path.join(root, f) for f in files
                          if f.lower().endswith(VIDEO_EXT) and not f.startswith("._")]
                if len(found) > 5000:
                    break
        return found

    def _fill(self) -> None:
        listed = -1e9
        while not self._stop.is_set():
            if time.monotonic() - listed > 600 or not self._videos:
                try:
                    self._videos = self._list()
                except OSError:
                    self._videos = []
                listed = time.monotonic()
            need_clip = len(self.clips) < self.want_clips
            if not self._videos or (len(self.runs) >= self.want_runs and not need_clip):
                self._stop.wait(1.0 if self._videos else 20.0)
                continue
            long = need_clip and (len(self.runs) >= self.want_runs or len(self.clips) <= len(self.runs))
            try:
                run = self._grab(self.rng.choice(self._videos), 32 if long else 8, 8 if long else 12)
            except Exception:
                log.info("duet: a clip could not be read", exc_info=True)
                run = []
            if run:
                with self._lock:
                    (self.clips if long else self.runs).append(run)
            else:
                self._stop.wait(5.0)

    def take_clip(self) -> list[np.ndarray] | None:
        """A few seconds of footage for a moving piece (a new one is read in its place)."""
        with self._lock:
            return self.clips.pop(self.rng.randrange(len(self.clips))) if self.clips else None

    def _grab(self, path: str, n: int = 8, fps: int = 12) -> list[np.ndarray]:
        import shutil
        import subprocess
        w, h = self.SIZE
        ff = shutil.which("ffmpeg")
        if ff is None:
            return self._grab_cv2(path, n)
        if path not in self._len:
            self._len[path] = Material._length(path)
        start = self.rng.uniform(0.0, 1.0) * self._len[path]
        cmd = [ff, "-v", "error", "-threads", "1", "-ss", f"{start:.2f}", "-i", path, "-an", "-frames:v", str(n),
               "-vf", f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        out = subprocess.run(cmd, capture_output=True, timeout=30).stdout
        size = w * h * 3
        return [np.frombuffer(out[i * size:(i + 1) * size], np.uint8).reshape(h, w, 3)
                for i in range(len(out) // size)]

    def _grab_cv2(self, path: str, n: int) -> list[np.ndarray]:
        try:
            import cv2
        except ImportError:
            return []
        cap = cv2.VideoCapture(path)
        try:
            total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if total > 200:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(self.rng.uniform(0, total - 100)))
            out = []
            for i in range(n * 2):
                ok, fr = cap.read()
                if not ok:
                    break
                if i % 2 == 0:
                    out.append(cv2.resize(fr, self.SIZE)[:, :, ::-1].copy())
            return out
        finally:
            cap.release()


# ------------------------------------------------------------------ the pieces on the TV
class Collage:
    """Pieces of pictures that are placed on the TV next to and over the face the network is
    growing: cut out, shifted, stitched edge to edge. Four kinds of material are mixed:

      family   a few seconds of the donated footage, moving inside its piece (most of them)
      photo    the guest's own pictures (guests/<name>/img, kept out of the repo and not
               used past the guest file's date); coarse and grey until the face has formed
      paint    paintings the Pi's own image model made in the background
      camera   what the room's camera sees right now (only in memory, gone with the visit)

    The further the face has come, the more pieces there are. Everything is drawn with
    pygame, in the draw call."""

    WEIGHTS = {"family": 0.45, "photo": 0.25, "paint": 0.2, "camera": 0.1}

    SHAPES = ((1.0, 1.0), (1.0, 1.4), (1.5, 1.0), (2.2, 1.0), (0.6, 1.6), (1.0, 0.45))

    def __init__(self, img_dir: str | None, seed: int | None = None, max_pieces: int = 12,
                 paint_dirs: list[str] | None = None, footage: Any = None, camera: Any = None):
        self.rng = random.Random(seed)
        self.paint_dirs = [os.path.expanduser(p) for p in (paint_dirs or [])]
        self.footage = footage           # a Glitch (its take_clip), or None
        self.camera = camera             # a function returning the newest camera picture (H, W, 3) or None
        self._paints: list[str] = []
        self._paints_t = -1e9
        self.counts = {k: 0 for k in self.WEIGHTS}
        self.paths: list[str] = []
        if img_dir and os.path.isdir(img_dir):
            self.paths = sorted(os.path.join(img_dir, f) for f in os.listdir(img_dir)
                                if f.lower().endswith(IMAGE_EXT) and not f.startswith("."))
        self.max_pieces = max_pieces
        self.pieces: list[dict] = []
        self._src: dict[str, Any] = {}
        self._size = (0, 0)
        self._next_add = 0.0
        self._bursts = 0
        self.offsets = [0.0] * 6         # how far each strip of the face is out of place (-1..1)

    def set_pictures(self, img_dir: str | None) -> None:
        """Another guest (or nobody the room knows): their pictures replace the last guest's."""
        self.paths = []
        self._src = {}
        if img_dir and os.path.isdir(img_dir):
            self.paths = sorted(os.path.join(img_dir, f) for f in os.listdir(img_dir)
                                if f.lower().endswith(IMAGE_EXT) and not f.startswith("."))
        self.pieces = [p for p in self.pieces if p["kind"] != "photo"]

    def clear(self) -> None:
        self.pieces = []
        self._next_add = 0.0
        self.offsets = [0.0] * len(self.offsets)

    def _load(self, path: str):
        import pygame
        s = self._src.get(path)
        if s is None:
            s = pygame.image.load(path)
            w, h = s.get_size()
            k = 900.0 / max(w, h)
            if k < 1.0:
                s = pygame.transform.smoothscale(s, (int(w * k), int(h * k)))
            self._src[path] = s
        return s

    def burst(self) -> None:
        """The face just came a step further: everything moves, new pieces arrive at once."""
        self._bursts += 1
        self.offsets = [self.rng.uniform(-1.0, 1.0) for _ in self.offsets]
        for p in self.pieces:
            self._shift(p, hard=self.rng.random() < 0.6)
        self._next_add = 0.0

    def _shift(self, p: dict, hard: bool) -> None:
        u = p["u"]
        axis = self.rng.choice("xy")
        step = self.rng.choice((-2, -1, 1, 2)) * u
        w, h = self._size
        if axis == "x":
            p["tx"] = float(round(min(max(p["tx"] + step, -p["w"] * 0.3), w - p["w"] * 0.7) / u) * u)
        else:
            p["ty"] = float(round(min(max(p["ty"] + step, -p["h"] * 0.3), h - p["h"] * 0.7) / u) * u)
        if hard:
            p["x"], p["y"] = p["tx"], p["ty"]

    def _paintings(self) -> list[str]:
        if time.monotonic() - self._paints_t > 60:
            found = []
            for d in self.paint_dirs:
                for root, dirs, files in os.walk(d):
                    dirs[:] = [x for x in dirs if x != "derived"]
                    found += [os.path.join(root, f) for f in files if f.lower().endswith(IMAGE_EXT)]
            try:
                found.sort(key=os.path.getmtime)
            except OSError:
                pass
            self._paints, self._paints_t = found[-40:], time.monotonic()      # the newest ones
        return self._paints

    def _source(self):
        """Pick what the next piece is made of: (kind, pygame surface or None, clip or None)."""
        import pygame
        have = {"photo": bool(self.paths), "paint": bool(self._paintings()),
                "family": self.footage is not None and bool(self.footage.clips),
                "camera": self.camera is not None and self.camera() is not None}
        kinds = [k for k in self.WEIGHTS if have[k]]
        if not kinds:
            return None, None, None
        wts = dict(self.WEIGHTS, camera=0.1 if have["photo"] else 0.35)     # no pictures of them: the camera's eye
        kind = self.rng.choices(kinds, [wts[k] for k in kinds])[0]
        if kind == "family":
            clip = self.footage.take_clip()
            if clip:
                return kind, pygame.surfarray.make_surface(clip[0].swapaxes(0, 1)), clip
            kind = "photo" if have["photo"] else None
        if kind == "camera":
            f = self.camera()
            return kind, pygame.surfarray.make_surface(np.ascontiguousarray(f[:, :, :3]).swapaxes(0, 1)), None
        if kind == "paint":
            path = self.rng.choice(self._paints)
            try:
                return kind, self._load(path), None
            except Exception:
                self._paints = [x for x in self._paints if x != path]
                kind = "photo" if have["photo"] else None
        if kind == "photo":
            return kind, self._load(self.rng.choice(self.paths)), None
        return None, None, None

    @staticmethod
    def _look(a: np.ndarray, kind: str, progress: float, colour: bool) -> np.ndarray:
        """How a piece is printed: float array in, uint8 out."""
        grey = a.mean(axis=2, keepdims=True)
        if kind == "family":                                  # an old film: soft colour, a little warm
            a = (grey + (a - grey) * 0.55) * np.array([1.05, 0.98, 0.88], np.float32)
        elif kind == "camera":                                # the watcher's eye: hard grey
            a = np.repeat((grey - 128.0) * 1.5 + 118.0, 3, axis=2)
        elif kind == "photo":
            a = grey + (a - grey) * (min(1.0, progress) if colour else 0.0)
            a = (a - 10.0) * (0.9 + 0.2 * progress)
        return np.clip(a, 0, 255).astype(np.uint8)

    def _add(self, now: float, progress: float) -> None:
        import pygame
        w, h = self._size
        u = max(8, h // 9)                                   # the grid everything snaps to
        kind, src, clip = self._source()
        if src is None:
            return
        sw, sh = src.get_size()
        ax, ay = self.rng.choice(self.SHAPES)
        units = self.rng.choice((2, 3, 3, 4, 4, 5))
        pw, ph = int(units * u * ax), int(units * u * ay)
        k = self.rng.uniform(0.3, 0.75 if kind != "photo" else 0.6) * min(sw / ax, sh / ay)   # how much it shows
        cw, ch = max(8, int(k * ax)), max(8, int(k * ay))
        cx = int(self.rng.uniform(0, max(1, sw - cw)))
        cy = int((self.rng.betavariate(1.6, 2.6) if kind == "photo" else self.rng.random()) * max(1, sh - ch))
        rect = (cx, cy, min(cw, sw - cx), min(ch, sh - cy))
        colour = progress >= 0.55 and self.rng.random() < 0.5
        a = self._look(pygame.surfarray.array3d(src.subsurface(rect)).astype(np.float32), kind, progress, colour)
        s = pygame.surfarray.make_surface(a)
        if kind in ("photo", "camera") and progress < 0.3:   # the guest is not developed yet: coarse
            n = max(6, int(8 + progress * 120))
            s = pygame.transform.smoothscale(s, (n, max(3, int(n * ay / ax))))
            s = pygame.transform.scale(s, (pw, ph)) if self.rng.random() < 0.5 else pygame.transform.smoothscale(s, (pw, ph))
        else:
            s = pygame.transform.smoothscale(s, (pw, ph))
        # where: stitched to the side of a piece that is already there, or near the middle
        if self.pieces and self.rng.random() < 0.6:
            o = self.rng.choice(self.pieces)
            side = self.rng.choice("lrtb")
            x = o["tx"] - pw if side == "l" else o["tx"] + o["w"] if side == "r" else o["tx"] + self.rng.choice((0, u, -u))
            y = o["ty"] - ph if side == "t" else o["ty"] + o["h"] if side == "b" else o["ty"] + self.rng.choice((0, u, -u))
        else:
            x = w / 2 + self.rng.uniform(-0.45, 0.45) * w - pw / 2
            y = h / 2 + self.rng.uniform(-0.45, 0.3) * h - ph / 2
        x = round(min(max(x, -pw * 0.25), w - pw * 0.75) / u) * u
        y = round(min(max(y, -ph * 0.25), h * 0.84 - ph * 0.75) / u) * u
        self.counts[kind] += 1
        self.pieces.append({"s": s, "x": float(x), "y": float(y), "tx": float(x), "ty": float(y), "w": pw, "h": ph,
                            "u": u, "born": now, "life": self.rng.uniform(25.0, 70.0) if clip is None else self.rng.uniform(14.0, 40.0),
                            "front": self.rng.random() < (0.2 if kind != "family" else 0.35),
                            "next": now + self.rng.uniform(6.0, 20.0), "a": 1.0, "kind": kind, "clip": clip,
                            "rect": rect, "i": 0, "progress": progress, "colour": colour, "live_t": now})

    def _move(self, p: dict, now: float) -> None:
        """Footage plays inside its piece (back and forth); a camera piece keeps looking."""
        import pygame
        a = None
        if p["clip"]:
            n = len(p["clip"])
            i = int((now - p["born"]) * 8.0) % max(1, 2 * n - 2)
            i = i if i < n else 2 * n - 2 - i
            if i != p["i"]:
                p["i"] = i
                x, y, w, h = p["rect"]
                a = p["clip"][i][y:y + h, x:x + w].swapaxes(0, 1)
        elif p["kind"] == "camera" and now - p["live_t"] > 0.25 and self.camera is not None:
            p["live_t"] = now
            f = self.camera()
            x, y, w, h = p["rect"]
            if f is not None and f.shape[0] >= y + h and f.shape[1] >= x + w:
                a = f[y:y + h, x:x + w, :3].swapaxes(0, 1)
        if a is not None:
            s = pygame.surfarray.make_surface(self._look(a.astype(np.float32), p["kind"], p["progress"], p["colour"]))
            p["s"] = pygame.transform.scale(s, (p["w"], p["h"]))

    def drop_camera(self) -> None:
        """The visit is over: what the camera saw goes at once."""
        self.pieces = [p for p in self.pieces if p["kind"] != "camera"]

    def step(self, now: float, size: tuple, progress: float, pace: float = 0.5) -> None:
        if size != self._size:
            self._size = size
            self.pieces = []
        self.pieces = [p for p in self.pieces if now - p["born"] < p["life"]]
        for i, o in enumerate(self.offsets):                 # the strips of the face settle again
            self.offsets[i] = o * 0.985
        for p in self.pieces:
            p["x"] += (p["tx"] - p["x"]) * 0.12
            p["y"] += (p["ty"] - p["y"]) * 0.12
            if now >= p["next"]:
                self._shift(p, hard=self.rng.random() < 0.35)
                p["next"] = now + self.rng.uniform(6.0, 24.0) * (1.4 - 0.8 * pace)
        want = min(self.max_pieces, 5 + int(progress * 7))
        if len(self.pieces) < want and now >= self._next_add:
            try:
                self._add(now, progress)
            except Exception:
                log.info("duet: a collage piece failed", exc_info=True)
            self._next_add = now + (0.15 if self._bursts else self.rng.uniform(2.0, 5.0))
            if len(self.pieces) >= want:
                self._bursts = 0

    def draw(self, surf, now: float, level: float, front: bool) -> None:
        import pygame
        for p in self.pieces:
            if p["front"] != front:
                continue
            age, left = now - p["born"], p["life"] - (now - p["born"])
            a = min(1.0, age / 0.25, left / 2.0) * p["a"] * level
            if a <= 0.01:
                continue
            self._move(p, now)
            p["s"].set_alpha(None if a > 0.97 else int(255 * a))      # mostly opaque: a hard cut-out, and fast
            x, y = int(p["x"]), int(p["y"])
            surf.blit(p["s"], (x, y))
            c = int(170 * a)                                 # the stitches along the seams
            st = max(6, p["u"] // 5)
            for sx in range(x + st, x + p["w"], st * 2):
                pygame.draw.line(surf, (c, c, c), (sx, y - 3), (sx + 2, y + 3))
            for sy in range(y + st, y + p["h"], st * 2):
                pygame.draw.line(surf, (c, c, c), (x - 3, sy), (x + 3, sy + 2))
