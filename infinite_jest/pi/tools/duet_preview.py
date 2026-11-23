#!/usr/bin/env python3
"""Render the two-screen show offline into a video: TV on top, wall below (or side by side).

    python3 tools/duet_preview.py --out preview.mp4 --seconds 260 [--models DIR]

A fake visitor walks in at 6 s, speaks now and then, stays for the whole visit and
leaves; the real Engine, the real Duet and the real networks run on a fake clock,
so the result is what the Pi would show (at whatever speed this machine has).
Needs ffmpeg on the PATH.
"""
import argparse
import os
import subprocess
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from showengine import config, protocol as P  # noqa: E402
from showengine.duet import Duet  # noqa: E402
from showengine.engine import Engine  # noqa: E402


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class SayLog:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append((Clock.t, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=260)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--models")
    ap.add_argument("--leave", type=float, default=230, help="when the visitor leaves (s)")
    ap.add_argument("--stills", help="also save PNG stills at these seconds, comma separated")
    a = ap.parse_args()
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((16, 16))
    over = {"mode": "fixed", "modules": {"text": None}, "show": "duet",
            "visit": {"max_visit": 300.0, "release_time": 40.0, "wipe_time": 8.0}, "speak": False}
    if a.models:
        over["duet"] = {"models_dir": a.models}
    cfg = config.load(None, over)
    clock = Clock()
    audio = SayLog()
    eng = Engine(cfg, audio=audio, clock=clock)
    duet = Duet(cfg, eng)
    eng.state_hooks.append(duet.update)
    tv = pygame.Surface((960, 540))
    wall = pygame.Surface((960, 540))
    W, H = 960, 1080 + 0
    canvas = pygame.Surface((W, H))
    font = pygame.font.Font(None, 26)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(a.fps), "-i", "-", "-c:v", "libx264", "-pix_fmt",
                           "yuv420p", "-crf", "23", a.out], stdin=subprocess.PIPE)
    stills = {float(x) for x in a.stills.split(",")} if a.stills else set()
    next_wall = next_face = 0.0
    dt = 1.0 / a.fps
    rng = np.random.default_rng(3)
    n = int(a.seconds * a.fps)
    for i in range(n):
        t = i * dt
        clock.t = 1000.0 + t
        here = 6.0 <= t < a.leave
        voiced = here and (t % 23.0) < 0.6
        data = {"kind": "phone", "motion": (0.25 + 0.2 * rng.random()) if here else 0.0,
                "audio": {"level": 0.5 if voiced else 0.0, "voiced": voiced}}
        eng.handle(P.make(P.SENSOR, data), "phone")
        if duet.wall is not None and clock.t >= next_wall:
            duet.wall.push(duet.wall.make(1.0 / duet.wall.fps), clock.t)
            next_wall = clock.t + 1.0 / duet.wall.fps
        if duet.face_dreamer is not None and clock.t >= next_face:
            duet.face_dreamer.push(duet.face_dreamer.make(1.0 / duet.face_dreamer.fps), clock.t)
            next_face = clock.t + 1.0 / duet.face_dreamer.fps
        duet.draw_tv(tv, clock.t)
        duet.draw_wall(wall, clock.t)
        canvas.fill((0, 0, 0))
        canvas.blit(tv, (0, 0))
        canvas.blit(wall, (0, 540))
        pygame.draw.line(canvas, (60, 60, 60), (0, 540), (W, 540), 2)
        lab = f"{t:5.1f}s  room: {eng.machine.phase}  TV: {duet.tv}  face {duet.progress:.2f}"
        canvas.blit(font.render("CHANNEL 1  TV", True, (120, 120, 120)), (10, 8))
        canvas.blit(font.render("CHANNEL 2  WALL (projector)", True, (120, 120, 120)), (10, 548))
        canvas.blit(font.render(lab, True, (200, 170, 60)), (10, H - 26))
        ff.stdin.write(pygame.image.tostring(canvas, "RGB"))
        for s in list(stills):
            if abs(t - s) < dt / 2:
                pygame.image.save(canvas, os.path.splitext(a.out)[0] + f"-{int(s):03d}s.png")
    ff.stdin.close()
    ff.wait()
    for t, s in audio.said:
        print(f"{t - 1000:6.1f}s  says: {s}")


if __name__ == "__main__":
    main()
