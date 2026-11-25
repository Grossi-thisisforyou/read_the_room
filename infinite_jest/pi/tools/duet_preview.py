#!/usr/bin/env python3
"""Render the two-screen show offline into a video: TV on top, wall below (or side by side).

    python3 tools/duet_preview.py --out preview.mp4 --seconds 540 [--models DIR] [--mood dread]
                                  [--footage DIR] [--states states.jsonl]

A fake visitor walks in at 6 s, speaks now and then, stays for the whole visit and
leaves; the real Engine, the real Duet and the real networks run on a fake clock,
so the result is what the Pi would show (at whatever speed this machine has).
Needs ffmpeg on the PATH.
"""
import argparse
import json
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
    def __init__(self, clock):
        self.said = []
        self.clock = clock

    def say(self, text):
        self.said.append((self.clock.t, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=540)
    ap.add_argument("--mood", help="force the mood of the day")
    ap.add_argument("--footage", help="folder with clips (the family footage, or a stand-in)")
    ap.add_argument("--paintings", help="folder with paintings (the Pi paints its own)")
    ap.add_argument("--stranger", action="store_true", help="the unknown-visitor fork: no guest file, a pretend camera, spoken answers")
    ap.add_argument("--camera", help="a picture or clip to stand in for the room's camera (with --stranger)")
    ap.add_argument("--states", help="write the show state per frame here (to render the music afterwards)")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--models")
    ap.add_argument("--arrive", type=float, default=6.0, help="when the visitor comes in (s)")
    ap.add_argument("--leave", type=float, default=490, help="when the visitor leaves (s)")
    ap.add_argument("--stills", help="also save PNG stills at these seconds, comma separated")
    a = ap.parse_args()
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((16, 16))
    over = {"mode": "fixed", "modules": {"text": None}, "show": "duet",
            "visit": {"max_visit": 1e9, "release_time": 40.0, "wipe_time": 8.0}, "speak": False}
    over["duet"] = {"footage_dirs": [a.footage] if a.footage else [], "mood_file": os.devnull}
    if a.paintings:
        over["duet"]["paint_dir"] = a.paintings
    if a.models:
        over["duet"]["models_dir"] = a.models
    if a.mood:
        over["duet"]["mood"] = a.mood
    over["duet"]["speech_to_text"] = False
    over["duet"]["dream_process"] = False        # the preview steps the networks itself
    if a.stranger:
        over["duet"]["guest"] = ""
    cfg = config.load(None, over)
    clock = Clock()
    audio = SayLog(clock)
    eng = Engine(cfg, audio=audio, clock=clock)
    duet = Duet(cfg, eng)
    eng.state_hooks.append(duet.update)
    duet.glitch.start()
    states = open(a.states, "w") if a.states else None
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
    cam = None
    if a.stranger and a.camera:
        cam = pygame.surfarray.array3d(pygame.transform.smoothscale(pygame.image.load(a.camera), (320, 240))).swapaxes(0, 1)
    answers = ["a small town. you would not know it.", "", "my grandmother, i think.", "i left my phone outside.",
               "", "nobody. i came alone.", "the kitchen, in the morning.", "not really.", "i used to sing."]
    answered = set()
    for i in range(n):
        t = i * dt
        clock.t = 1000.0 + t
        here = a.arrive <= t < a.leave
        voiced = here and (t % 47.0) < 0.6
        q = duet.asking                      # the pretend visitor answers most questions, short or long
        if here and q and clock.t >= q["from"] + 1.0:
            talk_for = (0.0, 1.2, 5.0, 3.0)[hash(q["q"]) % 4]
            voiced = clock.t < q["from"] + 1.0 + talk_for
        data = {"kind": "phone", "motion": (0.25 + 0.2 * rng.random()) if here else 0.0,
                "audio": {"level": 0.5 if voiced else 0.0, "voiced": voiced}}
        eng.handle(P.make(P.SENSOR, data), "phone")
        if a.stranger:
            if cam is not None and here:                 # the pretend camera: the same picture, a little alive
                eng.last_frame = np.clip(cam.astype(np.int16) + rng.integers(-12, 12, cam.shape), 0, 255).astype(np.uint8)
            if here and q and id(q) not in answered and clock.t >= q["from"] + 3.0:
                answered.add(id(q))                      # what speech recognition would hand over
                txt = answers[(len(answered) - 1) % len(answers)]
                if txt:
                    duet.on_answer(txt)
        if duet.wall is not None and clock.t >= next_wall:
            duet.wall.push(duet.wall.make(1.0 / duet.wall.fps), clock.t)
            next_wall = clock.t + 1.0 / duet.wall.fps
        if duet.face_dreamer is not None and clock.t >= next_face:
            duet.face_dreamer.push(duet.face_dreamer.make(1.0 / duet.face_dreamer.fps), clock.t)
            next_face = clock.t + 1.0 / duet.face_dreamer.fps
        if states:
            st = eng.state
            states.write(json.dumps({"t": round(t, 3), **{k: st.get(k) for k in (
                "phase", "intensity", "heard", "steer", "duet", "glitch", "mood")}}) + "\n")
        duet.draw_tv(tv, clock.t)
        duet.draw_wall(wall, clock.t)
        canvas.fill((0, 0, 0))
        canvas.blit(tv, (0, 0))
        canvas.blit(wall, (0, 540))
        pygame.draw.line(canvas, (60, 60, 60), (0, 540), (W, 540), 2)
        lab = (f"{int(t) // 60}:{t % 60:04.1f}  room: {eng.machine.phase}  TV: {duet.tv}  face {duet.progress:.2f}"
               f"  mood today: {duet.mood['name']}")
        canvas.blit(font.render("CHANNEL 1  TV", True, (120, 120, 120)), (10, 8))
        canvas.blit(font.render("CHANNEL 2  WALL (projector)", True, (120, 120, 120)), (10, 548))
        canvas.blit(font.render(lab, True, (200, 170, 60)), (10, H - 26))
        ff.stdin.write(pygame.image.tostring(canvas, "RGB"))
        for s in list(stills):
            if abs(t - s) < dt / 2:
                pygame.image.save(canvas, os.path.splitext(a.out)[0] + f"-{int(s):03d}s.png")
    ff.stdin.close()
    ff.wait()
    if states:
        states.close()
    for t, s in audio.said:
        print(f"{t - 1000:6.1f}s  says: {s}")
    if a.states:
        with open(os.path.splitext(a.states)[0] + "-said.json", "w") as f:
            json.dump([[round(t - 1000, 2), s] for t, s in audio.said], f)


if __name__ == "__main__":
    main()
