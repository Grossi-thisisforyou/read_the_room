#!/usr/bin/env python3
"""Soak test: run the whole show the way the Pi runs it, for hours or for days.

    # real time, everything as on the Pi (engine + hub + visuals at 1920x1080 on a
    # headless surface + audio child process + in-process profiler + the oracle
    # process against a fake llama-server + a fake N900 over WebSocket):
    python3 infinite_jest/pi/tools/soak.py realtime --minutes 120 --out /tmp/soak-rt

    # accelerated, one process, fake clock: several show days in minutes. Every
    # sensor message and engine tick is real; visuals and audio are sampled.
    python3 infinite_jest/pi/tools/soak.py accel --days 5 --hours 10 --out /tmp/soak-accel

    # summarise a metrics file again (start / end / slope per metric)
    python3 infinite_jest/pi/tools/soak.py report /tmp/soak-rt/metrics.jsonl

Visitors come from Crowd: short visits, long ones past max_visit, people who
never put the phone down, opt-outs (cover the proximity sensor 4 s), rapid
pick-up/put-down, Wi-Fi drop-outs, and long empty stretches. PhaseChecker
checks every visit goes idle -> approach -> ... -> wipe -> idle, that no phase
outlives its limit and that the room returns to idle once the phone is down.

Nothing here writes visitor data anywhere: the only files are metrics and the
truth timeline of the simulated crowd, in --out.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import gc
import json
import math
import os
import random
import resource
import socket
import subprocess
import sys
import threading
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve()
PI_DIR = HERE.parents[1]
REPO = HERE.parents[3]
for p in (str(PI_DIR), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

FPS = 30.0
SENSOR_HZ = 10.0
FRAME_HZ = 4.0
FW, FH = 160, 120


# ============================================================== the crowd
class Crowd:
    """Endless, seeded sequence of (start, end, mode) intervals for the phone.

    mode: "empty" (on the plinth, nobody), "held", "down" (put down briefly,
    visitor still there), "covered" (held, proximity sensor covered), "silent"
    (phone stops sending: Wi-Fi drop). Each visit also records a truth entry.
    """

    KINDS = (("short", 18), ("normal", 34), ("long", 10), ("never", 3), ("optout", 10),
             ("rapid", 8), ("dropout", 7), ("backtoback", 10))

    def __init__(self, seed: int = 1, empty_scale: float = 1.0):
        self.rng = random.Random(seed)
        self.empty_scale = empty_scale
        self.t = 0.0
        self.visits: list[dict] = []

    def _gap(self) -> float:
        r = self.rng.random()
        if r < 0.06:
            return self.rng.uniform(600, 2700) * self.empty_scale    # long empty stretch
        if r < 0.25:
            return self.rng.uniform(60, 400) * self.empty_scale
        return self.rng.uniform(3, 50)

    def intervals(self):
        rng = self.rng
        names = [k for k, _ in self.KINDS]
        weights = [w for _, w in self.KINDS]
        while True:
            kind = rng.choices(names, weights)[0]
            gap = 0.7 if kind == "backtoback" else self._gap()
            yield self.t, self.t + gap, "empty", None
            self.t += gap
            segs: list[tuple[float, str]] = []
            if kind in ("short",):
                segs = [(rng.uniform(2, 15), "held")]
            elif kind in ("normal", "backtoback"):
                segs = [(rng.uniform(30, 120), "held")]
                if rng.random() < 0.3:          # puts it down a moment, picks it up again
                    segs += [(rng.uniform(1, 6), "down"), (rng.uniform(10, 40), "held")]
            elif kind == "long":
                segs = [(rng.uniform(190, 320), "held")]
            elif kind == "never":
                segs = [(rng.uniform(600, 1500), "held")]
            elif kind == "optout":
                segs = [(rng.uniform(4, 25), "held"), (rng.uniform(3.5, 6), "covered"),
                        (rng.uniform(10, 60), "held")]
            elif kind == "rapid":
                for _ in range(rng.randint(8, 25)):
                    segs += [(rng.uniform(0.3, 3), "held"), (rng.uniform(0.3, 3), "down")]
            elif kind == "dropout":
                segs = [(rng.uniform(10, 40), "held"), (rng.uniform(2, 20), "silent"),
                        (rng.uniform(10, 60), "held")]
            start = self.t
            for dur, mode in segs:
                yield self.t, self.t + dur, mode, kind
                self.t += dur
            self.visits.append({"kind": kind, "start": start, "end": self.t})


class Phone:
    """Turns crowd intervals into contract messages at 10 Hz (+ frames at 4 Hz)."""

    def __init__(self, seed: int = 2):
        import numpy as np
        from infinite_jest.visuals.figure import ghost_body
        self.rng = random.Random(seed)
        # pre-render camera frames so making them costs nothing during the run
        self.frames_held = [ghost_body(FW, FH, i * 0.37, seed=i % 5).tobytes() for i in range(48)]
        wall = ghost_body(FW, FH, 0, seed=1, present=0.0)
        self.frames_empty = [np.clip(wall.astype(int) + d, 0, 255).astype("uint8").tobytes()
                             for d in (-2, -1, 0, 1, 2)]
        self.b64_held = [base64.b64encode(f).decode() for f in self.frames_held]
        self.b64_empty = [base64.b64encode(f).decode() for f in self.frames_empty]
        self.prompt_n = 0

    def reading(self, t: float, mode: str, kind: str | None, t_in: float) -> dict | None:
        rng = self.rng
        if mode == "silent":
            return None
        held = mode in ("held", "covered")
        d: dict = {"kind": "phone", "light": round(0.3 + 0.02 * math.sin(t / 900), 3)}
        if held:
            ph = t_in * (0.6 + 0.3 * math.sin(t_in * 0.05))
            beta = 35 * math.sin(ph) + (175 if kind == "long" and 20 < t_in < 26 else 0)
            beta = ((beta + 180) % 360) - 180
            gamma = 30 * math.cos(ph * 1.3)
            shake = round(rng.random() ** 6, 3)
            d.update(held=True, presence=round(rng.uniform(0.75, 1.0), 3),
                     tilt={"alpha": 0, "beta": round(beta, 1), "gamma": round(gamma, 1)},
                     accel={"x": round(math.sin(math.radians(gamma)), 3), "y": round(math.sin(math.radians(beta)), 3),
                            "z": round(math.cos(math.radians(beta)), 3)},
                     shake=shake, motion=round(rng.uniform(0.05, 0.4), 3),
                     proximity={"near": mode == "covered"})
            lvl = round(rng.uniform(0.05, 0.5), 3)
            d["audio"] = {"level": lvl, "voiced": rng.random() < 0.2}
            d["loudness"] = lvl
        else:
            d.update(held=False, presence=round(rng.uniform(0.0, 0.12), 3),
                     tilt={"alpha": 0, "beta": 0.0, "gamma": 0.0},
                     accel={"x": 0.0, "y": 0.0, "z": 1.0}, shake=0.0,
                     motion=round(rng.uniform(0, 0.03), 3), proximity={"near": False})
            lvl = round(rng.uniform(0.01, 0.08), 3)
            d["audio"] = {"level": lvl, "voiced": rng.random() < 0.01}
            d["loudness"] = lvl
        return d

    def events(self, t: float, mode: str) -> list[dict]:
        """Occasional touch / choice / keys while held."""
        rng = self.rng
        out = []
        if mode != "held":
            return out
        if rng.random() < 0.02:
            out.append({"kind": "touch", "x": round(rng.random(), 3), "y": round(rng.random(), 3), "down": True})
        if rng.random() < 0.004:
            self.prompt_n += 1
            out.append({"kind": "choice", "prompt_id": "p%d" % (self.prompt_n % 5),
                        "option": rng.choice(["stay", "leave"]), "latency_ms": rng.randint(400, 5000)})
        if rng.random() < 0.002:
            out.append({"kind": "keys", "text": "x" * rng.randint(3, 30)})
        return out

    def frame(self, i: int, mode: str) -> dict | None:
        if mode == "silent":
            return None
        b = self.b64_held[i % len(self.b64_held)] if mode in ("held", "covered") else \
            self.b64_empty[i % len(self.b64_empty)]
        return {"w": FW, "h": FH, "fmt": "gray8", "b64": b}


# ============================================================== checks
LEGAL = {("idle", "approach"), ("approach", "profiling"), ("approach", "wipe"),
         ("profiling", "hook"), ("profiling", "release"), ("hook", "release"),
         ("release", "wipe"), ("wipe", "idle"),
         # an opted-out visitor who leaves goes straight to the wipe: nothing to reveal
         ("profiling", "wipe"), ("hook", "wipe")}


class PhaseChecker:
    """Validates the phase sequence against the crowd's truth."""

    def __init__(self, vcfg, pcfg):
        self.v, self.p = vcfg, pcfg
        self.phase, self.since, self.visit_start = "idle", 0.0, None
        self.errors: list[str] = []
        self.counts = collections.Counter()
        self.durations: dict[str, list[float]] = collections.defaultdict(list)
        self.visits = 0
        self.completed = 0
        self.down_since: float | None = None   # truth: phone left alone since
        self.max_idle_wait = 0.0

    def limits(self) -> dict:
        v = self.v
        slack = 0.6
        return {"approach": v.approach_time + slack, "profiling": v.profiling_timeout + slack,
                "release": v.release_time + slack, "wipe": v.wipe_time + slack}

    def on_change(self, t: float, old: str, new: str) -> None:
        if old != self.phase:
            self._err(t, "change from %s but checker thought %s" % (old, self.phase))
        if (old, new) not in LEGAL:
            self._err(t, "illegal transition %s -> %s" % (old, new))
        dur = t - self.since
        self.durations[old].append(dur)
        lim = self.limits().get(old)
        if lim is not None and dur > lim:
            self._err(t, "%s lasted %.1f s (limit %.1f)" % (old, dur, lim))
        if old == "release" and dur < self.v.release_time - 0.6:
            self._err(t, "release cut short: %.1f s" % dur)
        if new == "approach":
            self.visits += 1
            self.visit_start = t
        if new == "hook":
            pass
        if new == "idle":
            self.completed += 1
            self.visit_start = None
        self.counts["%s>%s" % (old, new)] += 1
        self.phase, self.since = new, t

    def on_truth(self, t: float, mode: str) -> None:
        """mode of the phone right now (called when it changes)."""
        if mode in ("empty",):
            if self.down_since is None:
                self.down_since = t
        else:
            self.down_since = None

    def tick(self, t: float) -> None:
        if self.phase == "hook" and self.visit_start is not None:
            if t - self.visit_start > self.v.max_visit + 1.0:
                self._err(t, "hook running %.0f s into the visit (max_visit %.0f)" % (t - self.visit_start, self.v.max_visit))
                self.visit_start = t   # report once per overrun
        # the room must be back to idle soon after the phone is left alone:
        # presence off_hold + stale + approach/profiling/release + wipe, with slack
        if self.down_since is not None:
            budget = (self.p.off_hold + self.p.stale_after + self.v.release_time + self.v.wipe_time
                      + 2 * self.p.smoothing + 3.0)
            waited = t - self.down_since
            if self.phase == "idle":
                self.max_idle_wait = max(self.max_idle_wait, 0.0)
            elif waited > budget:
                self._err(t, "room empty %.0f s but still in %s" % (waited, self.phase))
                self.down_since = t    # report once per budget
            else:
                self.max_idle_wait = max(self.max_idle_wait, waited)

    def _err(self, t: float, text: str) -> None:
        if len(self.errors) < 200:
            self.errors.append("t=%.1f %s" % (t, text))
            print("[check] t=%.1f %s" % (t, text), flush=True)

    def summary(self) -> dict:
        def pct(xs, q):
            if not xs:
                return None
            xs = sorted(xs)
            return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)
        return {"visits": self.visits, "completed": self.completed, "errors": len(self.errors),
                "first_errors": self.errors[:40], "transitions": dict(self.counts),
                "max_s": {k: round(max(v), 1) for k, v in self.durations.items() if v},
                "p50_s": {k: pct(v, 0.5) for k, v in self.durations.items()},
                "max_wait_to_idle_s": round(self.max_idle_wait, 1)}


# ============================================================== metrics
def proc_status(pid: int | str = "self") -> dict:
    out = {}
    try:
        with open("/proc/%s/status" % pid) as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("VmRSS", "VmHWM", "Threads"):
                    out[k] = int(v.split()[0])
        out["fds"] = len(os.listdir("/proc/%s/fd" % pid))
    except OSError:
        pass
    return out


def dir_bytes(path: str | None) -> int:
    if not path or not os.path.isdir(path):
        return 0
    n = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def pcts(xs: list[float]) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    n = len(s)
    return {"n": n, "p50": round(s[n // 2], 2), "p95": round(s[min(n - 1, int(n * 0.95))], 2),
            "p99": round(s[min(n - 1, int(n * 0.99))], 2), "max": round(s[-1], 2)}


class Sampler:
    """Collects process health and writes one JSON line per sample."""

    def __init__(self, out: Path, use_tracemalloc: bool, watch_dirs: list[str]):
        self.f = open(out / "metrics.jsonl", "a")
        self.use_tm = use_tracemalloc
        self.watch = watch_dirs
        self.base_types: collections.Counter | None = None
        self.tm_base = None
        if use_tracemalloc:
            tracemalloc.start(1) if os.environ.get("SOAK_TRACEMALLOC", "1") == "1" else None
        self.t0 = time.monotonic()

    def baseline(self) -> None:
        gc.collect()
        self.base_types = self.types()
        if self.use_tm:
            self.tm_base = tracemalloc.take_snapshot()

    @staticmethod
    def types() -> collections.Counter:
        return collections.Counter(type(o).__name__ for o in gc.get_objects())

    def sample(self, sim_t: float, extra: dict, deep: bool) -> dict:
        rec = {"wall_s": round(time.monotonic() - self.t0, 1), "sim_s": round(sim_t, 1)}
        rec.update(proc_status())
        rec["cpu_s"] = round(sum(resource.getrusage(resource.RUSAGE_SELF)[:2]), 1)
        rec["py_threads"] = threading.active_count()
        rec["disk"] = {d: dir_bytes(d) for d in self.watch}
        rec.update(extra)
        if deep:
            gc.collect()
            now = self.types()
            rec["objects"] = sum(now.values())
            if self.base_types is not None:
                grow = {k: now[k] - self.base_types.get(k, 0) for k in now}
                rec["obj_growth_top"] = dict(sorted(((k, v) for k, v in grow.items() if v), key=lambda kv: -kv[1])[:8])
            if self.use_tm and self.tm_base is not None:
                snap = tracemalloc.take_snapshot()
                stats = snap.compare_to(self.tm_base, "lineno")[:8]
                rec["tm_total_kb"] = round(sum(s.size for s in snap.statistics("filename")) / 1024)
                rec["tm_top"] = ["%s:%d %+.0f KB" % (s.traceback[0].filename.split("infinite_jest/")[-1],
                                                      s.traceback[0].lineno, s.size_diff / 1024) for s in stats]
        self.f.write(json.dumps(rec) + "\n")
        self.f.flush()
        return rec


# ============================================================== shared setup
def soak_cfg(out: Path, mode_cfg: dict | None = None) -> dict:
    from showengine import config
    cfg = config.load(None, mode_cfg or {})
    cfg["visuals"] = dict(cfg.get("visuals", {}), bank_dir=str(out / "bank"),
                          busy_file=str(out / "busy"))
    return cfg


def bank_size(bank) -> int:
    """Images the visuals hold: v1 kept a dict hook -> list, v2 a Bank with .under/.cuts."""
    if bank is None:
        return 0
    if isinstance(bank, dict):
        return sum(len(v) for v in bank.values())
    return sum(len(v) for d in (getattr(bank, "under", {}), getattr(bank, "cuts", {})) for v in d.values())


def make_bank(path: Path, per_hook: int = 12) -> None:
    """A small fake image library like bank_gen leaves behind (512x512 PNGs)."""
    import numpy as np
    import pygame
    for i, hook in enumerate(("flesh", "scrawl", "inverted", "mirror", "void")):
        d = path / hook
        d.mkdir(parents=True, exist_ok=True)
        for j in range(per_hook):
            fn = d / ("20261120-%06d_%d.png" % (j, i))
            if fn.exists():
                continue
            add_bank_image(fn, i * 100 + j)


def add_bank_image(fn: Path, seed: int) -> None:
    import numpy as np
    import pygame
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    s = pygame.transform.smoothscale(pygame.surfarray.make_surface(small), (512, 512))
    pygame.image.save(s, str(fn))


class TimedAudio:
    """Audio as on the Pi (spawned child, real TechnoSynth, null sink pacing),
    plus per-block render timing reported back over a queue."""

    def __init__(self, cfg: dict):
        from infinite_jest.audio.engine import AudioEngine
        self.eng = AudioEngine(dict(cfg, audio_sink="null"))
        ctx = self.eng._ctx
        self.stats_q = ctx.Queue(maxsize=64)
        self.latest: dict = {}

    def start(self) -> None:
        eng = self.eng
        ctx = eng._ctx
        eng._qs = ctx.Queue(maxsize=4)
        eng._qx = ctx.Queue(maxsize=4)
        eng._stop = ctx.Event()
        eng._wipe = ctx.Event()
        eng._proc = ctx.Process(target=timed_audio_worker, name="ij-audio", daemon=True,
                                args=(eng.cfg, eng._qs, eng._qx, eng._stop, eng._wipe, self.stats_q))
        eng._proc.start()

    def poll(self) -> dict:
        import queue
        try:
            while True:
                self.latest = self.stats_q.get_nowait()
        except queue.Empty:
            pass
        return self.latest

    # the engine's plugin interface
    def on_state(self, s):
        self.eng.on_state(s)

    def on_sensor(self, d):
        self.eng.on_sensor(d)

    def on_wipe(self):
        self.eng.on_wipe()

    def set_volume(self, v):
        pass

    def stop(self):
        self.eng.stop()

    @property
    def pid(self):
        return self.eng._proc.pid if self.eng._proc else None


def timed_audio_worker(cfg, q_state, q_sensor, stop_ev, wipe_ev, stats_q):
    """infinite_jest.audio.engine._worker with a stopwatch around render_block."""
    import queue as _q
    from infinite_jest.audio.engine import _drain
    from infinite_jest.audio.sinks import SR, NullSink
    from infinite_jest.audio.synth import TechnoSynth
    synth = TechnoSynth(seed=0, volume=0.9)
    sink = NullSink(synth.B)
    budget_ms = synth.B / SR * 1000.0
    times: list[float] = []
    t_start = time.monotonic()
    rendered = 0
    late = 0
    min_lead = 1e9
    underruns = 0
    last_report = t_start
    wipes = 0
    worst_wipe = 0.0
    nan = 0
    while not stop_ev.is_set():
        st = _drain(q_state)
        if st is not None:
            synth.set_state(st)
        se = _drain(q_sensor)
        if se is not None:
            synth.set_sensor(se)
        if wipe_ev.is_set():
            wipe_ev.clear()
            synth.wipe()
            wipes += 1
        was_wiping = synth.wiping
        t0 = time.perf_counter()
        block = synth.render_block()
        ms = (time.perf_counter() - t0) * 1000
        if was_wiping and not synth.wiping:
            worst_wipe = max(worst_wipe, ms)
        times.append(ms)
        if ms > budget_ms:
            late += 1
        rendered += synth.B
        sink.write(block)
        # how far ahead of the "device" we are: 150 ms buffer like the aplay sink
        lead = rendered / SR - (time.monotonic() - t_start) + 0.15
        if lead < 0:
            underruns += 1
            t_start = time.monotonic() - rendered / SR   # the device restarts after an xrun
        min_lead = min(min_lead, lead)
        now = time.monotonic()
        if now - last_report >= 10:
            s = sorted(times)
            n = len(s)
            rep = {"blocks": n, "budget_ms": round(budget_ms, 2), "p50": round(s[n // 2], 3),
                   "p99": round(s[int(n * 0.99)], 3), "max": round(s[-1], 3), "late": late,
                   "underruns": underruns, "min_lead_ms": round(min_lead * 1000, 1), "wipes": wipes,
                   "worst_wipe_block_ms": round(worst_wipe, 2), "pos": synth.pos,
                   "cpu_frac": round(sum(times) / 1000.0 / (now - last_report), 4)}
            try:
                stats_q.put_nowait(rep)
            except _q.Full:
                pass
            times, late, min_lead, worst_wipe = [], 0, 1e9, 0.0
            last_report = now
    sink.close()
    synth.close()


# ============================================================== accelerated
def run_accel(a) -> dict:
    """Fake clock, one process. Engine, presence, visit machine, profiler and
    the oracle's decision logic see every message; visuals render every
    `--frame-every` simulated seconds; audio renders `--audio-secs` of every
    minute and jumps its sample counter over the rest."""
    import numpy as np
    import pygame
    from infinite_jest import profiler as profmod
    from infinite_jest import visuals as vismod
    from infinite_jest.audio.synth import TechnoSynth
    from infinite_jest.oracle.oracle import Oracle
    from showengine import protocol as P
    from showengine.engine import Engine

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    make_bank(out / "bank")
    cfg = soak_cfg(out)
    pygame.display.init()
    screen = pygame.display.set_mode((1920, 1080))
    vis = vismod.create((1920, 1080), cfg["visuals"])
    prof = profmod.create({"seed": 3})
    synth = TechnoSynth(seed=0)
    sim = {"t": 1000.0}

    def clock():
        return sim["t"]

    oracle = Oracle({})
    pending: list[tuple[float, dict]] = []   # (due, oracle message)
    orng = random.Random(5)
    oracle_stats = collections.Counter()

    def emit(msg, roles):
        if roles is None or "oracle" in roles:
            m = dict(msg)
            m["ts"] = sim["t"]
            for kind, vid, _msgs, _n in oracle.handle(m):
                oracle_stats["asked_" + kind] += 1
                if len(pending) > 1:            # same as run_forever: keep at most one stale job
                    pending.pop(0)
                    oracle_stats["dropped"] += 1
                text = ("you stayed longer than most\nSUBJECT LINGERS\nHANDS NEVER STILL\nSCORE RISING"
                        if kind == "words" else
                        "you held it close\nwe chose this for you\nit worked\nmostly a guess")
                pending.append((sim["t"] + orng.uniform(2, 10), {"kind": kind, "vid": vid, "text": text}))

    eng = Engine(cfg, emit=emit, clock=clock, visuals=vis, audio=None, profiler=prof)
    checker = PhaseChecker(eng.machine.cfg, eng.presence.cfg)
    checker.since = sim["t"]
    orig_on_phase = eng._on_phase

    def on_phase(old, new, now):
        checker.on_change(now, old, new)
        orig_on_phase(old, new, now)
    eng._on_phase = on_phase

    crowd = Crowd(seed=a.seed, empty_scale=a.empty_scale)
    phone = Phone(seed=a.seed + 1)
    total = a.days * a.hours * 3600.0
    sampler = Sampler(out, use_tracemalloc=True, watch_dirs=[str(out / "bank")])
    tick_ms: list[float] = []
    handle_ms: list[float] = []
    render_ms: list[float] = []
    audio_ms: list[float] = []
    frame_i = 0
    next_frame_render = 0.0
    next_sample = 0.0
    next_bank_add = 3600.0
    dt = 1.0 / SENSOR_HZ
    t_sim0 = sim["t"]
    last_mode = None
    audio_skip = 0
    vis_t0 = vis.t
    warm = False
    for start, end, mode, kind in crowd.intervals():
        if start - 0 >= total:
            break
        if mode != last_mode:
            checker.on_truth(t_sim0 + start, mode)
            last_mode = mode
        t = start
        while t < end:
            sim["t"] = t_sim0 + t
            r = phone.reading(t, mode, kind, t - start)
            if r is not None:
                t0 = time.perf_counter()
                eng.handle(P.make(P.SENSOR, r, ts=sim["t"]), "phone")
                for ev in phone.events(t, mode):
                    eng.handle(P.make(P.SENSOR, ev, ts=sim["t"]), "phone")
                handle_ms.append((time.perf_counter() - t0) * 1000)
            # frames at 4 Hz: every other or third sensor tick
            if int(t * FRAME_HZ) != int((t - dt) * FRAME_HZ):
                f = phone.frame(frame_i, mode)
                frame_i += 1
                if f is not None:
                    eng.handle(P.make(P.FRAME, f, ts=sim["t"]), "phone")
            # oracle answers that are due
            while pending and pending[0][0] <= sim["t"]:
                _due, job = pending.pop(0)
                msg = oracle.accept(job["kind"], job["vid"], job["text"], ts=sim["t"])
                oracle_stats["sent" if msg else "stale"] += 1
                if msg:
                    eng.handle(msg, "oracle")
            # the frame loop ticks 3x per sensor reading
            for k in range(3):
                sim["t"] = t_sim0 + t + k * dt / 3
                t0 = time.perf_counter()
                eng.tick(sim["t"])
                tick_ms.append((time.perf_counter() - t0) * 1000)
                checker.tick(sim["t"])
            if t >= next_frame_render:
                next_frame_render = t + a.frame_every
                # carry the visuals' own clock along with the simulated time
                vis.t = vis_t0 + t
                t0 = time.perf_counter()
                for _ in range(2):
                    vis.render(screen, 1.0 / FPS)
                render_ms.append((time.perf_counter() - t0) * 500)
            # audio: render 2 s out of every 60, skip the rest of the sample counter
            sec = int(t)
            if t - sec < dt * 0.5:
                synth.set_state(eng.state)
                if sec % 60 < a.audio_secs:
                    for _ in range(47):
                        t0 = time.perf_counter()
                        blk = synth.render_block()
                        audio_ms.append((time.perf_counter() - t0) * 1000)
                    if not np.isfinite(blk).all():
                        oracle_stats["audio_nan"] += 1
                    audio_skip += 0
                else:
                    # whole internal blocks (v2 renders IB = 2 x B at a time): the ring slices assume it
                    jump = 24 * getattr(synth, "IB", synth.B)
                    if getattr(synth, "_pending", None):
                        synth._pending.clear()
                    synth.pos += jump
                    synth.next_step_at += jump
            if t >= next_bank_add:
                # the overnight generator adds images; bank_gen caps each hook at 400
                next_bank_add = t + 3600.0
                h = ("flesh", "scrawl", "inverted", "mirror", "void")[int(t // 3600) % 5]
                add_bank_image(out / "bank" / h / ("20261121-%09d_9.png" % int(t)), int(t))
            if not warm and t > 600:
                warm = True
                sampler.baseline()
            if t >= next_sample:
                next_sample = t + a.sample_every
                rec = sampler.sample(t, {
                    "visits": checker.visits, "phase_errors": len(checker.errors),
                    "tick_ms": pcts(tick_ms), "handle_ms": pcts(handle_ms),
                    "render_ms": pcts(render_ms), "audio_block_ms": pcts(audio_ms),
                    "vis_marks": len(vis.marks), "bank_imgs": bank_size(vis.bank),
                    "synth_stutters": len(synth.stutters), "synth_pos": synth.pos,
                    "oracle": dict(oracle_stats), "pending_oracle": len(pending),
                    "engine_stats": dict(eng.stats)}, deep=warm)
                tick_ms, handle_ms, render_ms, audio_ms = [], [], [], []
                print("[accel] day %.2f  visits %d  rss %s MB  errors %d" % (
                    t / (a.hours * 3600), checker.visits, rec.get("VmRSS", 0) // 1024, len(checker.errors)),
                    flush=True)
            t += dt
    summ = {"mode": "accel", "sim_hours": round(total / 3600, 1), "checker": checker.summary(),
            "crowd_kinds": dict(collections.Counter(v["kind"] for v in crowd.visits)),
            "oracle": dict(oracle_stats)}
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    return summ


# ============================================================== real time
async def phone_driver(url: str, out: Path, seed: int, minutes: float) -> None:
    """A fake N900 over WebSocket, like phone/n900/agent.py: hello, sensor at
    10 Hz, gray8 160x120 frames at 4 fps, and it reads every state message."""
    import aiohttp
    from showengine import protocol as P
    crowd = Crowd(seed=seed, empty_scale=0.15)
    phone = Phone(seed=seed + 1)
    truth = open(out / "truth.jsonl", "a")
    t_end = time.monotonic() + minutes * 60
    t0 = time.monotonic()
    async with aiohttp.ClientSession() as s:
        while time.monotonic() < t_end:
            try:
                async with s.ws_connect(url, heartbeat=20) as ws:
                    await ws.send_str(P.encode(P.make(P.HELLO, {"role": "phone", "device": "soak"})))

                    async def reader():
                        async for _m in ws:
                            pass
                    rd = asyncio.ensure_future(reader())
                    fi = 0
                    for start, end, mode, kind in crowd.intervals():
                        truth.write(json.dumps({"wall": time.time(), "mode": mode, "kind": kind,
                                                "dur": round(end - start, 2)}) + "\n")
                        truth.flush()
                        while time.monotonic() - t0 < end:
                            t = time.monotonic() - t0
                            r = phone.reading(t, mode, kind, t - start)
                            if r is not None:
                                await ws.send_str(P.encode(P.make(P.SENSOR, r)))
                                for ev in phone.events(t, mode):
                                    await ws.send_str(P.encode(P.make(P.SENSOR, ev)))
                                if int(t * FRAME_HZ) != int((t - 0.1) * FRAME_HZ):
                                    f = phone.frame(fi, mode)
                                    fi += 1
                                    if f:
                                        await ws.send_str(P.encode(P.make(P.FRAME, f)))
                            await asyncio.sleep(max(0.0, (t0 + t + 0.1) - time.monotonic()))
                            if time.monotonic() >= t_end:
                                break
                        if time.monotonic() >= t_end:
                            break
                    rd.cancel()
            except (aiohttp.ClientError, OSError):
                await asyncio.sleep(1)


def fake_llama(port: int) -> None:
    """llama-server's /v1/chat/completions with 2-10 s latency (sometimes worse)."""
    from aiohttp import web
    rng = random.Random(9)
    words = ["you stayed longer than most\nSUBJECT LINGERS\nHANDS NEVER STILL\nSCORE RISING",
             "keep holding it\nTILT DETECTED\nRETURNS TO CENTRE\nPREDICTABLE",
             "1. Line 1: don't go yet\n2. NEVER STILL\n3. SEGMENT B\n4. RETAINED"]
    doss = ["you held it close\nwe chose this scene because it worked\nit is mostly a guess\nnothing is kept",
            "the device rarely left your hands\nwe concluded you like attention\nmostly a guess"]
    busy = asyncio.Lock()   # --parallel 1: one request at a time

    async def chat(request):
        body = await request.json()
        async with busy:
            r = rng.random()
            await asyncio.sleep(rng.uniform(2, 10) if r < 0.93 else rng.uniform(12, 25))
            if r > 0.985:
                return web.json_response({"error": "boom"}, status=500)
        n = body.get("max_tokens", 40)
        text = rng.choice(words if n <= 40 else doss)
        return web.json_response({"choices": [{"message": {"role": "assistant", "content": text}}]})

    async def health(request):
        return web.json_response({"status": "ok"})
    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_get("/health", health)
    web.run_app(app, host="127.0.0.1", port=port, print=None, access_log=None)


async def run_realtime_async(a) -> dict:
    import pygame
    from infinite_jest import profiler as profmod
    from infinite_jest import visuals as vismod
    from showengine import plugins
    from showengine.engine import Engine
    from showengine.hub import Hub

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    make_bank(out / "bank")
    port = a.port
    cfg = soak_cfg(out, {"network": {"host": "127.0.0.1", "port": port, "udp_port": 0, "tcp_port": 0}})
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1920, 1080))
    vis = vismod.create((1920, 1080), cfg["visuals"])
    audio = TimedAudio(cfg["audio"])
    audio.start()
    prof = profmod.create({})
    engine = Engine(cfg, visuals=vis, audio=audio, profiler=prof)
    hub = Hub(engine, cfg)
    await hub.start()
    checker = PhaseChecker(engine.machine.cfg, engine.presence.cfg)
    checker.since = time.monotonic()
    phase_log = open(out / "phases.jsonl", "a")
    orig = engine._on_phase

    def on_phase(old, new, now):
        checker.on_change(now, old, new)
        phase_log.write(json.dumps({"wall": time.time(), "mono": now, "old": old, "new": new,
                                    "hook": engine.machine.visit.hook}) + "\n")
        orig(old, new, now)
    engine._on_phase = on_phase

    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(PI_DIR)]))
    llama_port = port + 1
    procs = {
        "llama": subprocess.Popen([sys.executable, str(HERE), "_llama", "--port", str(llama_port)], env=env),
    }
    time.sleep(1.0)
    procs["oracle"] = subprocess.Popen([sys.executable, "-m", "infinite_jest.oracle", "--ws",
                                        "ws://127.0.0.1:%d/ws" % port, "--url",
                                        "http://127.0.0.1:%d/v1/chat/completions" % llama_port, "--debug"],
                                       env=env, cwd=str(REPO), stderr=open(out / "oracle.log", "a"))
    procs["phone"] = subprocess.Popen([sys.executable, str(HERE), "_phone", "--port", str(port),
                                       "--out", str(out), "--minutes", str(a.minutes), "--seed", str(a.seed)], env=env)
    sampler = Sampler(out, use_tracemalloc=a.tracemalloc, watch_dirs=[str(out / "bank")])
    loop = asyncio.get_running_loop()
    period = 1.0 / FPS
    frame_ms: list[float] = []
    loop_ms: list[float] = []
    by_scene: dict[str, list[float]] = collections.defaultdict(list)
    overruns = 0
    oracle_msgs0 = 0
    t_end = time.monotonic() + a.minutes * 60
    next_sample = time.monotonic() + 30
    t_base = time.monotonic() + 120
    based = False
    last = time.monotonic()
    worst = (0.0, "")
    next_bank_add = time.monotonic() + 900
    n_deep = 0
    t_run0 = time.monotonic()
    wall_off = time.time() - time.monotonic()
    truth_f = None
    next_truth = 0.0
    try:
        while time.monotonic() < t_end:
            now = time.monotonic()
            if now >= next_truth:
                next_truth = now + 0.5
                if truth_f is None and (out / "truth.jsonl").exists():
                    truth_f = open(out / "truth.jsonl", "rb")
                    truth_f.seek(0, 2) if a.resume_truth else None
                while truth_f is not None:
                    line = truth_f.readline()
                    if not line.endswith(b"\n"):
                        if line:
                            truth_f.seek(truth_f.tell() - len(line))
                        break
                    tr = json.loads(line)
                    checker.on_truth(tr["wall"] - wall_off, tr["mode"])
            dt, last = now - last, now
            engine.tick(now)
            t0 = time.perf_counter()
            if engine.blackout:
                screen.fill((0, 0, 0))
            else:
                plugins.call(vis, "render", screen, dt)
            pygame.display.flip()
            ms = (time.perf_counter() - t0) * 1000
            frame_ms.append(ms)
            key = "%s/%s" % (engine.state.get("phase"), vis.hook)
            by_scene[key].append(ms)
            if ms > worst[0]:
                worst = (ms, key)
            busy = (time.monotonic() - now) * 1000
            loop_ms.append(busy)
            if busy > period * 1000:
                overruns += 1
            checker.tick(now)
            if now >= next_bank_add:
                next_bank_add = now + 900
                add_bank_image(out / "bank" / "flesh" / ("20261122-%09d_9.png" % int(now)), int(now))
            if not based and now >= t_base:
                sampler.baseline()
                based = True
            if now >= next_sample:
                next_sample = now + a.sample_every
                n_deep += 1
                extra = {
                    "visits": checker.visits, "phase_errors": len(checker.errors),
                    "frame_ms": pcts(frame_ms), "loop_ms": pcts(loop_ms), "overruns": overruns,
                    "worst_frame": [round(worst[0], 1), worst[1]],
                    "scenes": {k: pcts(v) for k, v in by_scene.items()},
                    "tasks": len(asyncio.all_tasks()), "clients": len(hub.clients),
                    "audio": audio.poll(), "engine_stats": dict(engine.stats),
                    "vis_marks": len(vis.marks), "bank_imgs": bank_size(vis.bank),
                    "children": {k: proc_status(p.pid) for k, p in procs.items()},
                }
                if audio.pid:
                    extra["children"]["audio"] = proc_status(audio.pid)
                rec = sampler.sample(now - t_run0, extra, deep=based and n_deep % 5 == 0)
                print("[rt] %5.1f min visits %d rss %d MB frame p50 %.1f p99 %.1f ms overruns %d "
                      "audio %s errors %d" % (rec["wall_s"] / 60, checker.visits, rec.get("VmRSS", 0) // 1024,
                                              extra["frame_ms"].get("p50", 0), extra["frame_ms"].get("p99", 0),
                                              overruns, extra["audio"].get("underruns"), len(checker.errors)),
                      flush=True)
                frame_ms, loop_ms, overruns, worst = [], [], 0, (0.0, "")
                by_scene = collections.defaultdict(list)
                for name, p in procs.items():
                    if p.poll() is not None and name != "phone":
                        checker._err(now, "child %s exited with %s" % (name, p.returncode))
            await asyncio.sleep(max(0.0, period - (time.monotonic() - now)))
    finally:
        for p in procs.values():
            p.terminate()
        audio.stop()
        await hub.stop()
    summ = {"mode": "realtime", "minutes": a.minutes, "checker": checker.summary(),
            "engine_stats": dict(engine.stats)}
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    return summ


# ============================================================== report
def slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def report(path: str, skip_s: float = 300) -> dict:
    recs = [json.loads(l) for l in open(path) if l.strip()]
    if not recs:
        return {}
    tkey = "sim_s"
    recs = [r for r in recs if r.get(tkey, 0) >= skip_s] or recs

    def series(fn):
        xs, ys = [], []
        for r in recs:
            try:
                v = fn(r)
            except (KeyError, TypeError):
                continue
            if v is not None:
                xs.append(r[tkey] / 3600.0)
                ys.append(float(v))
        if not ys:
            return None
        return {"start": round(ys[0], 2), "end": round(ys[-1], 2), "min": round(min(ys), 2),
                "max": round(max(ys), 2), "slope_per_h": round(slope(xs, ys), 4)}
    out = {
        "samples": len(recs), "hours": round(recs[-1][tkey] / 3600, 2),
        "rss_mb": series(lambda r: r["VmRSS"] / 1024),
        "fds": series(lambda r: r["fds"]),
        "threads": series(lambda r: r["Threads"]),
        "objects": series(lambda r: r.get("objects")),
        "tm_total_kb": series(lambda r: r.get("tm_total_kb")),
        "tasks": series(lambda r: r.get("tasks")),
        "disk_mb": series(lambda r: sum(r["disk"].values()) / 1e6),
        "vis_marks": series(lambda r: r.get("vis_marks")),
    }
    for k in ("frame_ms", "render_ms", "tick_ms", "handle_ms", "audio_block_ms", "loop_ms"):
        if any(k in r for r in recs):
            out[k + ".p50"] = series(lambda r, k=k: r[k].get("p50"))
            out[k + ".p99"] = series(lambda r, k=k: r[k].get("p99"))
            out[k + ".max"] = series(lambda r, k=k: r[k].get("max"))
    if any("audio" in r for r in recs):
        out["audio.p99"] = series(lambda r: r["audio"].get("p99"))
        out["audio.max"] = series(lambda r: r["audio"].get("max"))
        out["audio.worst_wipe_block_ms"] = series(lambda r: r["audio"].get("worst_wipe_block_ms"))
        out["audio.cpu_frac"] = series(lambda r: r["audio"].get("cpu_frac"))
        out["audio.underruns_total"] = max((r["audio"].get("underruns", 0) for r in recs if r.get("audio")), default=0)
        out["audio.late_total"] = sum(r["audio"].get("late", 0) for r in recs if r.get("audio"))
        out["audio.child_rss_mb"] = series(lambda r: r["children"]["audio"]["VmRSS"] / 1024)
        out["oracle.child_rss_mb"] = series(lambda r: r["children"]["oracle"]["VmRSS"] / 1024)
        out["oracle.child_fds"] = series(lambda r: r["children"]["oracle"]["fds"])
    if any("overruns" in r for r in recs):
        out["overruns_total"] = sum(r.get("overruns", 0) for r in recs)
    last = recs[-1]
    for k in ("obj_growth_top", "tm_top", "engine_stats", "oracle", "phase_errors", "visits"):
        if k in last:
            out["last." + k] = last[k]
    return out


# ============================================================== main
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("realtime")
    r.add_argument("--minutes", type=float, default=120)
    r.add_argument("--out", default="soak-out")
    r.add_argument("--port", type=int, default=18765)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--sample-every", type=float, default=60)
    r.add_argument("--resume-truth", action="store_true", help=argparse.SUPPRESS)
    r.add_argument("--tracemalloc", action="store_true", help="slows every frame; off by default")
    c = sub.add_parser("accel")
    c.add_argument("--days", type=float, default=5)
    c.add_argument("--hours", type=float, default=10, help="show hours per day")
    c.add_argument("--out", default="soak-accel")
    c.add_argument("--seed", type=int, default=1)
    c.add_argument("--frame-every", type=float, default=20.0, help="simulated seconds between rendered frames")
    c.add_argument("--audio-secs", type=int, default=1, help="seconds of audio rendered per simulated minute")
    c.add_argument("--sample-every", type=float, default=1800.0, help="simulated seconds between samples")
    c.add_argument("--empty-scale", type=float, default=1.0)
    rp = sub.add_parser("report")
    rp.add_argument("metrics")
    rp.add_argument("--skip", type=float, default=300)
    lp = sub.add_parser("_llama")
    lp.add_argument("--port", type=int)
    pp = sub.add_parser("_phone")
    pp.add_argument("--port", type=int)
    pp.add_argument("--out")
    pp.add_argument("--minutes", type=float)
    pp.add_argument("--seed", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "accel":
        summ = run_accel(a)
        print(json.dumps(summ, indent=1))
        print(json.dumps(report(str(Path(a.out) / "metrics.jsonl"), skip_s=0), indent=1))
    elif a.cmd == "realtime":
        summ = asyncio.run(run_realtime_async(a))
        print(json.dumps(summ, indent=1))
        print(json.dumps(report(str(Path(a.out) / "metrics.jsonl"), skip_s=0), indent=1))
    elif a.cmd == "report":
        print(json.dumps(report(a.metrics, a.skip), indent=1))
    elif a.cmd == "_llama":
        fake_llama(a.port)
    elif a.cmd == "_phone":
        asyncio.run(phone_driver("ws://127.0.0.1:%d/ws" % a.port, Path(a.out), a.seed, a.minutes))


if __name__ == "__main__":
    main()
