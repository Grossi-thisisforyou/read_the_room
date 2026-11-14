"""Film complete simulated visits of INFINITE JEST, with the real modules.

Everything that runs on the Pi runs here, in one process, on a virtual clock:

    real N900 agent (phone/n900/agent.py, its sensors.py reading a fake sysfs
    tree, its capture.py measuring synthetic camera frames and mic chunks)
        -> JSON envelopes, exactly as the agent sends them
    real show engine (pi/showengine: presence, visit machine, tilt, director)
    real profiler (in process, as on the Pi)       real oracle decision logic
    real visuals (visuals/, 1920x1080)             real techno (audio/ TechnoSynth)
        -> engine "phone" / "wipe" messages go back into the agent, whose real
           screen code (phone/n900/screens.py) draws the N900 inset.

Only the person is fake: a scripted visitor who picks the phone up, taps in,
tilts, shakes, turns it over, talks, answers prompts, types, and puts it down.
Each persona reacts to the hook it is shown (it holds the phone steadier and
closer when it gets the one it likes), so the profiler's bandit has something
real to learn from.

Because the clock is virtual, rendering is frame-exact and the sound is in
sync, however slow the machine. Nothing about the "visitor" is written to disk
except the video itself.

    cd read_the_room
    python3 -m infinite_jest.integration.film --persona performer --out out/performer
    python3 -m infinite_jest.integration.film --show --out out/show      # every persona back to back

Each run writes <out>.mp4 (exactly what the projector shows, with the sound),
<out>_explained.mp4 (the same plus the N900 screen and a caption strip), and
<out>.json (timeline: phases, hooks, OCEAN, words, phone texts; no frames).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HERE = os.path.dirname(os.path.abspath(__file__))
IJ = os.path.dirname(HERE)
REPO = os.path.dirname(IJ)
for p in (REPO, os.path.join(IJ, "pi"), os.path.join(IJ, "phone", "n900")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pygame  # noqa: E402

from showengine import config as engine_config  # noqa: E402
from showengine import plugins  # noqa: E402
from showengine.engine import Engine  # noqa: E402

W, H, FPS = 1920, 1080, 30
SENSOR_HZ = 20.0          # the agent's rate_hz
FRAME_FPS = 4.0           # the agent's frame_fps
MIC_HZ = 20.0             # one 50 ms mic chunk per tick
EPOCH = 1794700000.0      # virtual wall clock start (a Monday in Nov 2026)


# --------------------------------------------------------------- the clock --
class VirtualTime:
    """Stands in for the `time` module inside the phone agent and capture code."""

    def __init__(self):
        self.t = 0.0

    def time(self):
        return EPOCH + self.t

    def monotonic(self):
        return self.t

    def sleep(self, s):
        pass

    def __getattr__(self, name):          # anything else: the real module
        return getattr(time, name)


# ------------------------------------------------------------- the visitor --
PERSONAS = {
    # tilt amplitude (deg) and speed (rad/s), tremor (g), shake bursts per minute,
    # flips per minute, voice share, answer latency (s), answer index policy,
    # typed secret, how long they hold the phone (s), favourite hook.
    "performer": dict(label="The performer", amp=(55, 70), speed=1.4, tremor=0.03, shakes=4.0,
                      flips=0.6, voice=0.55, loud=5200, latency=0.9, answer=0,
                      secret="i sing in the shower and i want everyone to hear it",
                      hold=105, favourite="mirror", close=0.75),
    "lurker":    dict(label="The lurker", amp=(6, 8), speed=0.25, tremor=0.004, shakes=0.0,
                      flips=0.0, voice=0.0, loud=0, latency=6.0, answer=1, secret=None,
                      hold=100, favourite="void", close=0.25),
    "nerve":     dict(label="The nervous one", amp=(18, 25), speed=2.2, tremor=0.05, shakes=7.0,
                      flips=0.0, voice=0.08, loud=2500, latency=1.3, answer=1,
                      secret="no", hold=95, favourite="flesh", close=0.4),
    "seeker":    dict(label="The seeker", amp=(80, 85), speed=0.6, tremor=0.01, shakes=0.5,
                      flips=2.0, voice=0.12, loud=3000, latency=2.6, answer=0,
                      secret="i keep a list of rooms i have been happy in",
                      hold=110, favourite="inverted", close=0.55),
    "refuser":   dict(label="The one who says no", amp=(15, 15), speed=0.5, tremor=0.01, shakes=0.0,
                      flips=0.0, voice=0.0, loud=0, latency=3.0, answer=1, secret=None,
                      hold=22, favourite="void", close=0.3, optout_at=12.0),
}


class Visitor:
    """One scripted person. pose(t) says what their hands, voice and face do."""

    def __init__(self, name, start, seed=0):
        self.name = name
        self.p = dict(PERSONAS[name])
        self.rng = random.Random(seed * 101 + len(name))
        self.start = start                      # when they pick the phone up (show time)
        self.end = start + self.p["hold"]       # when they put it down
        self.entered = False
        self.answered = set()
        self.typed = False
        self.pending = None                     # (due_t, prompt_id, index)
        self.next_shake = start + 6 + self.rng.random() * 6
        self.next_flip = start + 25 + self.rng.random() * 10
        self.shake_until = -1.0
        self.flip_until = -1.0
        self.still_until = -1.0
        self.next_still = start + 30 + self.rng.random() * 15

    def holding(self, t):
        return self.start <= t < self.end

    def pose(self, t, hook):
        """-> (beta, gamma, accel_noise_g, near, voiced, voice_amp, close)"""
        p, r = self.p, self.rng
        if not self.holding(t):
            return None
        el = t - self.start
        liked = hook == p["favourite"]
        calm = 0.45 if liked else 1.0          # the right hook holds them: steadier, closer
        a_b, a_g = p["amp"]
        sp = p["speed"] * (0.7 if liked else 1.0)
        # lifting off the plinth for the first second
        lift = min(1.0, el / 1.0)
        beta = lift * (25 + a_b * calm * math.sin(el * sp * 0.73 + 0.4))
        gamma = lift * (a_g * calm * math.sin(el * sp + 1.1))
        noise = p["tremor"] * (1.0 if not liked else 0.6)
        if p["shakes"] and t >= self.next_shake and el > 5:
            self.shake_until = t + 0.6 + r.random() * 0.6
            self.next_shake = t + 60.0 / p["shakes"] * (0.5 + r.random())
        if t < self.shake_until:
            noise += 0.9
        if p["flips"] and t >= self.next_flip and el > 15:
            self.flip_until = t + 4 + r.random() * 3
            self.next_flip = t + 60.0 / p["flips"] * (0.6 + r.random() * 0.8)
        if t < self.flip_until:
            beta = 175 * (1 if math.sin(el) >= 0 else -1)
        if el > 20 and t >= self.next_still:
            self.still_until = t + 6 + r.random() * 3
            self.next_still = t + 35 + r.random() * 15
        if t < self.still_until:
            beta, gamma, noise = 20.0, 2.0, min(noise, 0.002)
        near = "optout_at" in p and p["optout_at"] <= el < p["optout_at"] + 4.0
        talk_phase = (math.sin(el * 0.35 + len(self.name)) + 1) / 2
        voiced = p["voice"] > 0 and talk_phase < p["voice"] * (1.3 if liked else 1.0)
        return beta, gamma, noise, near, voiced, p["loud"], p["close"] + (0.2 if liked else 0)


# ------------------------------------------------------ fake N900 hardware --
class FakeSysfs:
    """The four sysfs files sensors.py reads, kept in a RAM-backed temp dir."""

    PATHS = None

    def __init__(self):
        import sensors as S
        base = "/dev/shm" if os.path.isdir("/dev/shm") else None
        self.root = tempfile.mkdtemp(prefix="ij-n900-", dir=base)
        self.paths = {k: self.root + v for k, v in S.PATHS.items()}
        for path in self.paths.values():
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.write(accel=(0, 0, -1000), lux=40, prox="open", slide="closed", lens="open", battery=88)

    def write(self, accel=None, lux=None, prox=None, slide=None, lens=None, battery=None):
        vals = {"accel": accel and "%d %d %d" % tuple(int(v) for v in accel), "lux": lux,
                "proximity": prox, "slide": slide, "lens": lens, "battery": battery}
        for k, v in vals.items():
            if v is not None:
                with open(self.paths[k], "w") as f:
                    f.write(str(v))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def accel_for(beta, gamma, noise, rng):
    """Gravity vector (milli-g) that sensors.py will read back as (beta, gamma)."""
    b, g = math.radians(beta), math.radians(gamma)
    gx = math.sin(g)
    gy = -math.sin(b) * math.cos(g)
    gz = -math.cos(b) * math.cos(g)
    return [1000 * (v + rng.gauss(0, noise)) for v in (gx, gy, gz)]


def camera_frame(t, visitor, pose, rng):
    """160x120 gray8 of what the front camera sees: ceiling when flat, a face when held."""
    from infinite_jest.visuals.figure import ghost_body
    if pose is None:
        img = np.full((120, 160), 52, np.uint8)            # the gallery ceiling, dim
        img = np.clip(img + rng.normal(0, 2, img.shape), 0, 255).astype(np.uint8)
        return img
    beta, gamma, noise, near, *_rest, close = pose
    if near:
        return np.full((120, 160), 4, np.uint8)            # a thumb over the lens area
    img = ghost_body(160, 120, t, seed=sum(map(ord, visitor.name)) % 50, present=1.0).astype(np.float32)
    # closer = bigger face in frame: zoom about the head (close 0.25 -> 0.85x, 0.95 -> 1.6x)
    k = 0.6 + 1.05 * close
    ys = np.clip(((np.arange(120) - 36) / k + 36).astype(int), 0, 119)
    xs = np.clip(((np.arange(160) - 80) / k + 80).astype(int), 0, 159)
    img = img[ys][:, xs]
    # the hand moves the camera: shift with tilt, jitter with tremor
    dx = int(gamma * 0.5 + rng.normal(0, 30 * noise + 1e-9))
    dy = int((beta - 25) * 0.35 + rng.normal(0, 30 * noise + 1e-9))
    img = np.roll(np.roll(img, dx, axis=1), dy, axis=0)
    if abs(beta) > 120:                                    # phone upside down
        img = img[::-1, ::-1]
    return np.clip(img, 0, 255).astype(np.uint8)


def mic_chunk(voiced, amp, rng, n=400, rate=8000):
    """50 ms of 16-bit PCM: room hiss, or a voice-like buzz while talking."""
    from array import array
    f0 = 140 + rng.random() * 80
    if voiced:
        s = [int(amp * (0.6 * math.sin(2 * math.pi * f0 * i / rate)
                        + 0.3 * math.sin(2 * math.pi * 2.1 * f0 * i / rate))
                 + rng.gauss(0, 60)) for i in range(n)]
    else:
        s = [int(rng.gauss(0, 40)) for _ in range(n)]
    return array("h", [max(-32767, min(32767, v)) for v in s]).tobytes()


# ------------------------------------------------------------ offline sound --
class OfflineAudio:
    """The real audio module's synth, driven exactly as audio.engine's worker does,
    but rendered into memory instead of a sound card."""

    def __init__(self, cfg):
        from infinite_jest.audio import engine as AE
        from infinite_jest.audio.synth import TechnoSynth, SR
        self.SR = SR
        self.keys_state, self.keys_sensor = AE._STATE_KEYS, AE._SENSOR_KEYS
        self.plain = AE._plain
        vol = AE._volume(cfg) * float(cfg.get("master_gain", 1.0))
        self.synth = TechnoSynth(seed=int(cfg.get("audio_seed", 0)), volume=vol)
        self.blocks = []
        self.done = 0
        self._state = self._sensor = None
        self._wipe = False

    def start(self):
        pass

    def stop(self):
        pass

    def on_state(self, state):
        if isinstance(state, dict):
            self._state = {k: self.plain(state[k]) for k in self.keys_state if k in state}

    def on_sensor(self, data):
        if isinstance(data, dict):
            self._sensor = {k: self.plain(data[k]) for k in self.keys_sensor if k in data}

    def on_wipe(self):
        self._wipe = True

    def set_volume(self, volume):
        self.synth.volume = float(volume)

    def render_until(self, samples):
        while self.done < samples:
            # the worker drains the queues once per block, then renders
            if self._state is not None:
                self.synth.set_state(self._state)
                self._state = None
            if self._sensor is not None:
                self.synth.set_sensor(self._sensor)
                self._sensor = None
            if self._wipe:
                self._wipe = False
                self.synth.wipe()
            b = self.synth.render_block()
            self.blocks.append(b)
            self.done += len(b)

    def write_wav(self, path, samples):
        pcm = np.concatenate(self.blocks)[:samples]
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(self.SR)
            w.writeframes(np.ascontiguousarray(pcm, dtype=np.int16).tobytes())


# ----------------------------------------------------------- the N900 inset --
class PhoneScreen:
    def __init__(self):
        import cairo
        import screens
        self.cairo, self.screens = cairo, screens
        self.surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 800, 480)

    def draw(self, snap, local, t):
        cr = self.cairo.Context(self.surf)
        self.screens.draw(cr, 800, 480, snap, local, t)
        self.surf.flush()
        buf = bytes(self.surf.get_data())
        return pygame.image.frombuffer(buf, (800, 480), "BGRA").convert()


# ------------------------------------------------------------------ the rig --
class Rig:
    def __init__(self, seed=0, llm_url=None, explained=True):
        self.vt = VirtualTime()
        self.rng = random.Random(seed)
        self.nrng = np.random.default_rng(seed)
        # the agent and its capture code read the virtual clock
        import agent as A
        import capture as C
        import sensors as S  # noqa: F401
        A.time = self.vt
        C.time = self.vt
        self.A = A
        self.sysfs = FakeSysfs()
        conf = dict(A.DEFAULTS)
        conf.update({"camera": 1, "mic": 1, "keep_awake": 0})
        self.agent = A.Agent(conf, fake=True, sysfs_root=self.sysfs.root)
        self.agent.prompt_i = 0
        self.agent.ui["last_presence_t"] = self.vt.time()

        cfg = engine_config.load(None, {"display": {"width": W, "height": H, "fps": FPS}})
        self.cfg = cfg
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((W, H))
        self.canvas = pygame.Surface((W, H))
        mods = cfg["modules"]
        vmod = plugins.load(mods["visuals"])
        self.visuals = vmod.create((W, H), cfg.get("visuals", {}))
        self.audio = OfflineAudio(cfg.get("audio", {}))
        pmod = plugins.load(mods["profiler"])
        self.profiler = pmod.create(dict(cfg.get("profiler", {}), seed=seed))
        from infinite_jest.oracle.oracle import Oracle, http_complete
        self.oracle = Oracle({"url": llm_url} if llm_url else {})
        self.complete = http_complete(self.oracle.cfg) if llm_url else None
        self.oracle_jobs = []
        self.engine = Engine(cfg, emit=self._emit, clock=self.vt.monotonic,
                             visuals=self.visuals, audio=self.audio, profiler=self.profiler)
        self.phone = PhoneScreen() if explained else None
        self.timeline = []
        self.msgs = {"to_engine": 0, "to_phone": 0, "frames": 0, "bad_json": 0}
        self.phone_texts = []
        self._last_phase = None
        self._last_hook = None
        self.render_ms = []

    # engine -> network
    def _emit(self, msg, roles):
        wire = json.loads(json.dumps(msg))                 # it must survive the wire
        if roles is None or "phone" in roles:
            if wire["type"] in ("state", "phone", "wipe"):
                self.msgs["to_phone"] += 1
                self.agent.handle(wire)
                if wire["type"] == "phone":
                    self.phone_texts.append((round(self.vt.t, 1), wire["data"]))
                    self.timeline.append({"t": round(self.vt.t, 2), "phone": wire["data"]})
        if roles is None or "oracle" in roles:
            for job in self.oracle.handle(wire):
                self.oracle_jobs.append(job)

    def _run_oracle(self):
        # on the Pi these run on a worker thread against llama-server; here, inline
        for kind, vid, messages, max_tokens in self.oracle_jobs:
            if self.complete is None:
                continue
            t0 = time.time()
            try:
                text = self.complete(messages, max_tokens)
            except Exception:
                continue
            out = self.oracle.accept(kind, vid, text, ts=self.vt.time())
            self.timeline.append({"t": round(self.vt.t, 2), "oracle": kind,
                                  "ok": bool(out), "ms": int((time.time() - t0) * 1000)})
            if out:
                self.engine.handle(json.loads(json.dumps(out)), "oracle")
        self.oracle_jobs = []

    # phone -> engine
    def _send(self, msg):
        try:
            wire = json.loads(json.dumps(msg))
        except (TypeError, ValueError):
            self.msgs["bad_json"] += 1
            return
        self.msgs["to_engine"] += 1
        self.engine.handle(wire, "phone")

    def _drain_agent_events(self):
        while True:
            try:
                m = self.agent.events.get_nowait()
            except Exception:
                break
            self._send(m)

    def _visitor_acts(self, v, t):
        ui = self.agent.ui_snapshot()
        if v is None or not v.holding(t):
            return
        el = t - v.start
        if not v.entered and el > 2.0 and ui["screen"] == "consent":
            self.agent.on_consent()
            v.entered = True
        p = ui.get("prompt")
        if p and v.pending is None and p.get("prompt_id") not in v.answered:
            idx = v.p["answer"] if v.rng.random() < 0.8 else 1 - v.p["answer"]
            v.pending = (t + v.p["latency"] * (0.7 + 0.6 * v.rng.random()), p.get("prompt_id"), idx)
        if v.pending and t >= v.pending[0]:
            _due, pid, idx = v.pending
            v.pending = None
            v.answered.add(pid)
            if ui.get("prompt") and ui["prompt"].get("prompt_id") == pid:
                self.agent.on_choice(idx)
        # the engine's profiling question asks for a secret: some type one
        st = self.engine.state
        if (not v.typed and v.p["secret"] and st["phase"] in ("profiling", "hook")
                and el > 14 and self.agent.ui_snapshot()["screen"] == "live"):
            v.typed = True
            self.sysfs.write(slide="open")
            self.agent.on_keys(v.p["secret"], typing_ms=len(v.p["secret"]) * 180,
                               backspaces=v.rng.randint(0, 6))
        if v.typed and el > 22:
            self.sysfs.write(slide="closed")
        if v.entered and v.rng.random() < (0.02 if v.p["shakes"] > 2 else 0.006):
            self.agent.on_touch(v.rng.random(), v.rng.random(), True)

    def run(self, script, out, seconds, title=""):
        """script: list of Visitor. Renders `seconds` of show to out.mp4 (+ explained, + json)."""
        tmp = tempfile.mkdtemp(prefix="ij-film-")
        wav = os.path.join(tmp, "sound.wav")
        # seconds=None: run until the room has wiped and sat idle for 4 s after the last visitor
        n_frames = int(seconds * FPS) if seconds else int((script[-1].end + 240) * FPS)
        idle_since = None
        ff_clean = _ffmpeg(out + ".mp4.video.mp4")
        ff_expl = _ffmpeg(out + "_explained.mp4.video.mp4") if self.phone else None
        font = pygame.font.Font(None, 34)
        small = pygame.font.Font(None, 28)
        next_sensor = next_frame = next_mic = 0.0
        last_seq = -1
        dt = 1.0 / FPS
        wall0 = time.time()
        i = -1
        while i + 1 < n_frames:
            i += 1
            t = i * dt
            self.vt.t = t
            v = None
            for x in script:                       # the latest visitor who has arrived
                if x.start - 6 <= t:
                    v = x
            hook = self.engine.state.get("hook")
            pose = v.pose(t, hook) if v else None
            # hardware
            if pose is None:
                self.sysfs.write(accel=accel_for(0, 0, 0.0004, self.rng), prox="open", lux=40)
            else:
                beta, gamma, noise, near, voiced, amp, close = pose
                self.sysfs.write(accel=accel_for(beta, gamma, noise, self.rng),
                                 prox="closed" if near else "open", lux=3 if near else 60)
            while next_mic <= t:
                voiced = bool(pose and pose[4])
                self.agent.mic._on_chunk(mic_chunk(voiced, pose[5] if pose else 0, self.rng))
                next_mic += 1.0 / MIC_HZ
            while next_frame <= t:
                img = camera_frame(t, v, pose, self.nrng)
                self.agent.camera._on_frame(img.tobytes())
                frame, seq = self.agent.camera.latest()
                if frame is not None and seq != last_seq and not self.agent.opted_out:
                    last_seq = seq
                    self.msgs["frames"] += 1
                    self._send({"type": "frame", "ts": self.vt.time(), "data": {
                        "w": 160, "h": 120, "fmt": "gray8",
                        "b64": base64.b64encode(frame).decode("ascii")}})
                next_frame += 1.0 / FRAME_FPS
            self._visitor_acts(v, t)
            self._drain_agent_events()
            while next_sensor <= t:
                r = self.agent.reading(self.vt.time())
                self.agent.ui_update(reading=r)
                if r.get("presence", 0) > 0.3:
                    self.agent.ui_update(last_presence_t=self.vt.time())
                self._send({"type": "sensor", "ts": self.vt.time(), "data": r})
                self.agent.local_director(self.vt.time())
                next_sensor += 1.0 / SENSOR_HZ
            self._drain_agent_events()
            self._run_oracle()
            st = self.engine.tick(t)
            self._log_state(st)
            # picture
            r0 = time.perf_counter()
            if self.engine.blackout:
                self.canvas.fill((0, 0, 0))
            else:
                plugins.call(self.visuals, "render", self.canvas, dt)
            self.render_ms.append((time.perf_counter() - r0) * 1000)
            ff_clean.stdin.write(pygame.image.tostring(self.canvas, "RGB"))
            if ff_expl:
                self.screen.blit(self.canvas, (0, 0))
                self._explain(st, v, font, small, title)
                ff_expl.stdin.write(pygame.image.tostring(self.screen, "RGB"))
            # sound, sample-exact with the picture
            self.audio.render_until(int(round((i + 1) * self.audio.SR / FPS)))
            if not seconds and t > script[-1].end:
                idle_since = (idle_since or t) if st["phase"] == "idle" else None
                if idle_since is not None and t - idle_since >= 4.0:
                    n_frames = i + 1
            if i % (FPS * 10) == 0:
                print("  %5.0fs  %-9s hook %-8s  (%.1fx realtime)" % (
                    t, st["phase"], st.get("hook") or "-", (t + dt) / max(1e-6, time.time() - wall0)),
                    file=sys.stderr)
        samples = int(round(n_frames * self.audio.SR / FPS))
        self.audio.write_wav(wav, samples)
        for ff, name in ((ff_clean, out + ".mp4"), (ff_expl, out + "_explained.mp4")):
            if ff is None:
                continue
            ff.stdin.close()
            ff.wait()
            _mux(name + ".video.mp4", wav, name)
        shutil.copy(wav, out + ".wav") if os.environ.get("IJ_KEEP_WAV") else None
        shutil.rmtree(tmp, ignore_errors=True)
        report = {
            "title": title, "seconds": round(n_frames / FPS, 2), "fps": FPS, "size": [W, H],
            "visitors": [{"persona": x.name, "label": x.p["label"], "picks_up_at": x.start,
                          "puts_down_at": x.end, "favourite_hook": x.p["favourite"]} for x in script],
            "messages": self.msgs, "engine_counts": self.engine.stats,
            "render_ms": _stats(self.render_ms),
            "wall_seconds": round(time.time() - wall0, 1),
            "timeline": self.timeline,
        }
        with open(out + ".json", "w") as f:
            json.dump(report, f, indent=1)
        return report

    def _log_state(self, st):
        ent = {}
        if st["phase"] != self._last_phase:
            ent["phase"] = st["phase"]
            self._last_phase = st["phase"]
            if st["phase"] in ("hook", "release"):
                ent["ocean"] = st.get("ocean")
                ent["confidence"] = st.get("confidence")
                ent["profile_source"] = st.get("profile_source")
                ent["words"] = st.get("words")[:8]
            if st["phase"] == "release" and st.get("reveal"):
                ent["reveal"] = st["reveal"].get("lines")
        if st.get("hook") != self._last_hook:
            ent["hook"] = st.get("hook")
            self._last_hook = st.get("hook")
        if ent:
            ent["t"] = round(self.vt.t, 2)
            self.timeline.append(ent)

    def _explain(self, st, v, font, small, title):
        """N900 inset bottom-right and a caption strip top-left (explained cut only)."""
        snap = self.agent.ui_snapshot()
        img = self.phone.draw(snap, {}, self.vt.time())
        iw, ih = 560, 336
        img = pygame.transform.smoothscale(img, (iw, ih))
        x, y = W - iw - 40, H - ih - 40
        pygame.draw.rect(self.screen, (18, 18, 18), (x - 22, y - 22, iw + 44, ih + 44), border_radius=18)
        pygame.draw.rect(self.screen, (60, 60, 60), (x - 22, y - 22, iw + 44, ih + 44), 2, border_radius=18)
        self.screen.blit(img, (x, y))
        cap = small.render("the phone in the visitor's hand", True, (170, 170, 170))
        self.screen.blit(cap, (x, y - 50))
        o = st.get("ocean") or {}
        lines = [
            (font, "%s%s" % (title + "  |  " if title else "", v.p["label"] if v else "empty room")),
            (small, "phase %-9s  hook %-8s  intensity %.2f  tempo %.0f" % (
                st["phase"], st.get("hook") or "-", st["intensity"], st["tempo"])),
            (small, "OCEAN guess  " + ("  ".join("%s %.2f" % (k, o[k]) for k in "OCEAN" if k in o) or "-")
             + ("   conf %.2f" % st.get("confidence", 0) if o else "")),
            (small, "tilt x %+.2f  y %+.2f%s%s" % (
                st["steer"].get("x", 0), st["steer"].get("y", 0),
                "  UPSIDE DOWN" if st["steer"].get("flip") else "",
                "  SHAKE" if st["steer"].get("shake", 0) > 0.3 else "")),
        ]
        yy = 24
        pad = pygame.Surface((900, 150), pygame.SRCALPHA)
        pad.fill((0, 0, 0, 170))
        self.screen.blit(pad, (16, 14))
        for f, s in lines:
            im = f.render(s, True, (235, 225, 205))
            self.screen.blit(im, (30, yy))
            yy += im.get_height() + 8

    def close(self):
        self.sysfs.close()


def _ffmpeg(path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2", "-pix_fmt", "yuv420p", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def _mux(video, wav, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", wav,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
                    "-shortest", out], check=True)
    os.remove(video)


def _stats(xs):
    if not xs:
        return {}
    s = sorted(xs)
    return {"median": round(s[len(s) // 2], 2), "p95": round(s[int(len(s) * 0.95)], 2),
            "max": round(s[-1], 2)}


def build_script(names, gap=14.0, first=6.0, seed=0):
    """Visitors one after another; each next one waits until the room has wiped."""
    out, t = [], first
    for i, n in enumerate(names):
        v = Visitor(n, t, seed=seed + i)
        out.append(v)
        # put down -> ~10 s presence hold -> release (the confession, up to ~50 s) -> wipe (~12 s)
        t = v.end + 10 + 55 + 14 + gap
    return out, t - gap + 4


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", choices=sorted(PERSONAS), action="append")
    ap.add_argument("--show", action="store_true", help="every persona, back to back")
    ap.add_argument("--out", required=True, help="output path without extension")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--llm-url", help="a llama-server /v1/chat/completions URL for the oracle")
    ap.add_argument("--no-explained", action="store_true")
    ap.add_argument("--seconds", type=float, help="override the length")
    a = ap.parse_args(argv)
    names = ["lurker", "performer", "refuser", "nerve", "seeker"] if a.show else (a.persona or ["performer"])
    script, _length = build_script(names, seed=a.seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rig = Rig(seed=a.seed, llm_url=a.llm_url, explained=not a.no_explained)
    title = "INFINITE JEST  simulated show" if a.show else "INFINITE JEST  simulated visit"
    try:
        rep = rig.run(script, a.out, a.seconds, title)
    finally:
        rig.close()
    print(json.dumps({k: rep[k] for k in ("seconds", "messages", "engine_counts", "render_ms", "wall_seconds")}))


if __name__ == "__main__":
    main()
