#!/usr/bin/env python3
"""CPU budget of the show, measured on this machine, for the Pi 5 estimate.

    python3 infinite_jest/pi/tools/budget.py            # everything, ~2 minutes
    python3 infinite_jest/pi/tools/budget.py --only visuals

Prints milliseconds per frame for every visuals scene at 1920x1080 (the real
module and the engine's built-in fallback), the cost of a full-HD copy (what a
software flip on KMSDRM costs at least), audio render time per second of
audio, the synth's sample-bank rebuilds, and the profiler and engine cost per
message, per camera frame and per tick. Multiply by the Pi 5 factor from
docs (pure Python ~2.4x slower than this reference x86; see README there).
"""
from __future__ import annotations

import argparse
import base64
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
for p in (str(HERE.parents[1]), str(HERE.parents[3])):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

OCEAN = {"O": 0.7, "C": 0.3, "E": 0.6, "A": 0.4, "N": 0.7}


def timeit(fn, n: int, warm: int = 5) -> dict:
    for _ in range(warm):
        fn()
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return {"mean": statistics.fmean(xs), "p50": xs[len(xs) // 2], "p95": xs[int(len(xs) * 0.95)], "max": xs[-1]}


def fmt(d: dict) -> str:
    return "mean %7.2f  p50 %7.2f  p95 %7.2f  max %7.2f ms" % (d["mean"], d["p50"], d["p95"], d["max"])


def state(phase: str, hook: str | None, scene: str, vid: str = "v-abcd") -> dict:
    return {"visitor_id": vid, "phase": phase, "phase_t": 4.0, "scene": scene, "hook": hook,
            "intensity": 0.7, "ocean": OCEAN, "tempo": 132, "words": ["SUBJECT LINGERS", "NEVER STILL"],
            "palette": None, "steer": {"x": 0.2, "y": -0.1, "flip": False, "shake": 0.1}, "mode": "handheld"}


SCENES = [("idle", None, "void"), ("approach", None, "surveil"), ("profiling", None, "dossier"),
          ("hook", "flesh", "flesh"), ("hook", "scrawl", "scrawl"), ("hook", "inverted", "inverted"),
          ("hook", "mirror", "mirror"), ("hook", "void", "void"), ("release", "flesh", "afterimage"),
          ("wipe", None, "erase")]


def bench_visuals(n: int, internal=(640, 360), smooth=True) -> None:
    import numpy as np
    import pygame
    from infinite_jest import visuals
    from infinite_jest.visuals.figure import ghost_body
    from showengine.outputs import fallback_visuals
    pygame.display.init()
    screen = pygame.display.set_mode((1920, 1080))
    print("\n== visuals, real module, output 1920x1080, internal %dx%d, %s" % (
        internal[0], internal[1], "smoothscale" if smooth else "scale"))
    for phase, hook, scene in SCENES:
        v = visuals.create((1920, 1080), {"internal_size": internal, "smooth_scale": smooth,
                                          "bank_dir": "/nonexistent", "busy_file": ""})
        st = state(phase, hook, scene)
        v.on_state(st)
        for i in range(8):
            v.on_frame(ghost_body(160, 120, i * 0.3))
        if phase == "wipe":
            v.on_wipe()

        def frame():
            st["phase_t"] += 1 / 30
            v.on_state(st)
            v.render(screen, 1 / 30)
            if phase == "wipe" and v.wipe_t is None:
                v.on_wipe()
        print("  %-10s %-9s %s" % (phase, hook or "-", fmt(timeit(frame, n))))
    print("\n== visuals, engine fallback (showengine/outputs/fallback_visuals.py), 1920x1080")
    for phase, hook, scene in SCENES:
        v = fallback_visuals.create((1920, 1080), {})
        st = state(phase, hook, scene)
        v.on_state(st)

        def frame():
            v.on_state(st)
            v.render(screen, 1 / 30)
        print("  %-10s %-9s %s" % (scene, "", fmt(timeit(frame, n))))
    print("\n== full-HD copies (lower bound of a software flip on KMSDRM)")
    src = pygame.Surface((1920, 1080)).convert()
    dst = pygame.Surface((1920, 1080)).convert()
    print("  blit 1920x1080 32bpp  %s" % fmt(timeit(lambda: dst.blit(src, (0, 0)), 60)))
    low = pygame.Surface(internal).convert()
    print("  smoothscale %dx%d->1080p %s" % (internal[0], internal[1],
                                             fmt(timeit(lambda: pygame.transform.smoothscale(low, (1920, 1080), dst), 60))))
    print("  scale       %dx%d->1080p %s" % (internal[0], internal[1],
                                             fmt(timeit(lambda: pygame.transform.scale(low, (1920, 1080), dst), 60))))
    a = np.zeros(1920 * 1080 * 4, np.uint8)
    b = np.empty_like(a)
    d = timeit(lambda: np.copyto(b, a), 60)
    print("  numpy memcpy 8.3 MB   %s  (%.1f GB/s)" % (fmt(d), 8.3e6 / (d["p50"] / 1000) / 1e9))


def bench_audio() -> None:
    import numpy as np
    from infinite_jest.audio.synth import TechnoSynth
    print("\n== audio: TechnoSynth, 48 kHz stereo, 1024-frame blocks (budget 21.33 ms per block)")
    for phase, hook in (("idle", None), ("approach", None), ("profiling", None), ("hook", "flesh"),
                        ("hook", "scrawl"), ("hook", "inverted"), ("hook", "mirror"), ("hook", "void"),
                        ("release", "flesh")):
        s = TechnoSynth(seed=1)
        st = {"visitor_id": "v-1234", "phase": phase, "hook": hook, "intensity": 0.8, "ocean": OCEAN,
              "tempo": 134, "steer": {"x": 0.3, "y": 0.2, "shake": 0.0}}
        s.set_state(st)
        for _ in range(300):              # let levels glide in
            s.render_block()
        xs = []
        for _ in range(470):              # 10 s of audio
            t0 = time.perf_counter()
            s.render_block()
            xs.append((time.perf_counter() - t0) * 1000)
        xs.sort()
        print("  %-10s %-9s %6.0f ms CPU per s of audio (%.1f%% of a core)  block p50 %.2f  p99 %.2f  max %.2f ms" % (
            phase, hook or "-", sum(xs) / 10, sum(xs) / 100, xs[len(xs) // 2], xs[int(len(xs) * 0.99)], xs[-1]))
    s = TechnoSynth(seed=1)
    s.set_state({"visitor_id": "v-1", "phase": "hook", "hook": "flesh", "intensity": 0.8, "ocean": OCEAN})
    s.render_block()
    t0 = time.perf_counter()
    s.bank_keys.clear()
    s._build_bank()
    print("  full sample-bank rebuild (every wipe, in _reset_musical_state): %.0f ms" % ((time.perf_counter() - t0) * 1000))
    for k in ("k", "h", "c", "s", "t"):
        s.bank_keys.pop(k, None)
        t0 = time.perf_counter()
        s._build_bank()
        print("    section %s rebuild: %6.1f ms" % (k, (time.perf_counter() - t0) * 1000))


def bench_profiler_engine() -> None:
    import numpy as np
    from infinite_jest import profiler
    from infinite_jest.visuals.figure import ghost_body
    from showengine import protocol as P
    from showengine.config import load
    from showengine.engine import Engine
    print("\n== profiler and engine (pure Python on the main thread)")
    p = profiler.create({"seed": 1})
    p.on_visit({"visitor_id": "v-1", "phase": "approach"}, 1000.0)
    t = [1000.0]
    d = {"kind": "phone", "held": True, "presence": 0.9, "tilt": {"alpha": 0, "beta": 10, "gamma": 5},
         "accel": {"x": 0.1, "y": 0.2, "z": 0.97}, "audio": {"level": 0.2, "voiced": True}, "shake": 0.1,
         "proximity": {"near": False}, "light": 0.3}

    def sensor():
        t[0] += 0.1
        p.on_sensor(d, t[0])
    print("  profiler.on_sensor          %s" % fmt(timeit(sensor, 2000)))
    frames = [{"w": 160, "h": 120, "fmt": "gray8", "b64": base64.b64encode(ghost_body(160, 120, i * 0.3).tobytes()).decode()}
              for i in range(16)]
    k = [0]

    def frame():
        k[0] += 1
        t[0] += 0.25
        p.on_frame(frames[k[0] % 16], t[0])
    print("  profiler.on_frame 160x120   %s" % fmt(timeit(frame, 200)))
    big = {"w": 320, "h": 240, "fmt": "gray8", "b64": base64.b64encode(np.tile(ghost_body(160, 120, 0), (2, 2)).tobytes()).decode()}
    print("  profiler.on_frame 320x240   %s" % fmt(timeit(lambda: p.on_frame(big, t[0]), 60)))
    clock = [5000.0]
    eng = Engine(load(None), clock=lambda: clock[0], profiler=profiler.create({"seed": 2}))

    def h_sensor():
        clock[0] += 0.1
        eng.handle(P.make(P.SENSOR, dict(d), ts=clock[0]), "phone")

    def h_frame():
        clock[0] += 0.25
        k[0] += 1
        eng.handle(P.make(P.FRAME, frames[k[0] % 16], ts=clock[0]), "phone")

    def tick():
        clock[0] += 1 / 30
        eng.tick(clock[0])
    print("  engine.handle(sensor)+prof  %s" % fmt(timeit(h_sensor, 2000)))
    print("  engine.handle(frame)+prof   %s" % fmt(timeit(h_frame, 200)))
    print("  engine.tick                 %s" % fmt(timeit(tick, 3000)))
    eng2 = Engine(load(None), clock=lambda: clock[0])

    def h_frame2():
        clock[0] += 0.25
        k[0] += 1
        eng2.handle(P.make(P.FRAME, frames[k[0] % 16], ts=clock[0]), "phone")
    print("  engine.handle(frame) alone  %s" % fmt(timeit(h_frame2, 200)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("visuals", "audio", "profiler"))
    ap.add_argument("-n", type=int, default=90, help="frames per scene")
    ap.add_argument("--internal", default="640x360", help="visuals internal size, e.g. 480x270")
    ap.add_argument("--no-smooth", action="store_true")
    a = ap.parse_args()
    import platform
    print("python %s on %s" % (platform.python_version(), platform.processor() or platform.machine()))
    if a.only in (None, "visuals"):
        w, h = (int(x) for x in a.internal.lower().split("x"))
        bench_visuals(a.n, (w, h), not a.no_smooth)
    if a.only in (None, "audio"):
        bench_audio()
    if a.only in (None, "profiler"):
        bench_profiler_engine()


if __name__ == "__main__":
    main()
