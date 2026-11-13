"""Standalone demo of the visuals, no engine or phone needed.

  python3 -m infinite_jest.visuals.demo                 # window, fake visitors
  python3 -m infinite_jest.visuals.demo --fullscreen
  python3 -m infinite_jest.visuals.demo --image me.jpg  # use a photo as the "camera"
  python3 -m infinite_jest.visuals.demo --webcam        # laptop webcam (needs opencv-python)
  python3 -m infinite_jest.visuals.demo --stills out/   # save PNG stills of every hook, no window
  python3 -m infinite_jest.visuals.demo --capture a.mp4 --seconds 60 [--audio techno.wav]

Keys: 1-5 hooks (flesh scrawl inverted mirror void), P cycle phase, W wipe,
O C E A N raise a trait (shift lowers), V new visitor, F fullscreen, Esc quit.
The mouse stands in for the phone's tilt (left/right leans and smears, up/down zooms).
"""
import argparse
import math
import os
import random
import sys
import time

import numpy as np

HOOKS = ["flesh", "scrawl", "inverted", "mirror", "void"]
PHASES = [("idle", 6), ("approach", 4), ("profiling", 10), ("hook", 40), ("release", 6), ("wipe", 3)]


class FakeShow:
    """Pretends to be the engine: walks through phases, invents a visitor."""

    def __init__(self, hook=None, seed=0):
        self.rng = random.Random(seed)
        self.new_visitor()
        self.fixed_hook = hook
        self.pi = 0
        self.pt = 0.0
        self.mouse = None  # in the window demo, the mouse stands in for phone tilt

    def new_visitor(self):
        r = self.rng
        self.vid = "v%04x" % r.randrange(65536)
        self.ocean = {k: round(r.random(), 2) for k in "OCEAN"}
        self.hook = r.choice(HOOKS)

    def step(self, dt):
        self.pt += dt
        name, dur = PHASES[self.pi]
        if self.pt > dur:
            self.next_phase()

    def next_phase(self):
        self.pi = (self.pi + 1) % len(PHASES)
        self.pt = 0.0
        if PHASES[self.pi][0] == "approach":
            self.new_visitor()

    def state(self):
        name = PHASES[self.pi][0]
        inten = {"idle": 0.15, "approach": 0.4, "profiling": 0.55, "hook": 0.85, "release": 0.4, "wipe": 0.1}[name]
        return {"visitor_id": self.vid, "phase": name, "phase_t": self.pt,
                "hook": self.fixed_hook or self.hook, "scene": self.fixed_hook or self.hook,
                "intensity": inten, "ocean": dict(self.ocean), "tempo": 124 + 16 * self.ocean["E"],
                "words": ["LINGERED %dS" % int(self.pt + 4), "LEFT HAND", "LOOKED AWAY 3X"],
                "steer": self.steer()}

    def steer(self):
        """A visitor slowly tilting the phone, with the odd shake."""
        t = self.pt + self.pi * 10
        x = 0.8 * math.sin(t * 0.45) if PHASES[self.pi][0] == "hook" else 0.0
        y = 0.5 * math.sin(t * 0.31 + 1) if PHASES[self.pi][0] == "hook" else 0.0
        if self.mouse is not None:
            x, y = self.mouse
        shake = 1.0 if (PHASES[self.pi][0] == "hook" and int(t) % 17 == 0 and t % 1 < 0.1) else 0.0
        return {"x": x, "y": y, "flip": False, "shake": shake}


def camera_source(args):
    """Returns a function t -> frame (numpy [h, w] or [h, w, 3]) or None."""
    from .figure import ghost_body
    if args.image:
        import pygame
        img = pygame.image.load(args.image)
        arr = np.transpose(pygame.surfarray.array3d(img), (1, 0, 2))
        wall = np.full_like(arr, 118)
        # first second: empty wall so background subtraction has something to learn
        return lambda t, present: wall if present < 0.5 else arr
    if args.webcam:
        try:
            import cv2
        except ImportError:
            sys.exit("--webcam needs: pip install opencv-python")
        cap = cv2.VideoCapture(0)

        def grab(t, present):
            ok, fr = cap.read()
            return cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY) if ok else None
        return grab
    return lambda t, present: ghost_body(120, 160, t, seed=5, present=present)


def run_window(args):
    import pygame
    from . import create
    pygame.display.init(); pygame.font.init()  # not pygame.init(): keep ALSA free for the audio
    flags = pygame.FULLSCREEN if args.fullscreen else 0
    size = (0, 0) if args.fullscreen else (1280, 720)
    screen = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("INFINITE JEST visuals demo")
    vis = create(screen.get_size(), {})
    show = FakeShow(args.hook, args.seed)
    cam = camera_source(args)
    clock = pygame.time.Clock()
    last_frame = 0.0
    t = 0.0
    font = pygame.font.Font(None, 22)
    while True:
        dt = clock.tick(30) / 1000.0
        t += dt
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                pygame.quit(); return
            if ev.type == pygame.KEYDOWN:
                ch = ev.unicode.lower()
                if ch in "12345" and ch:
                    show.fixed_hook = HOOKS[int(ch) - 1]
                elif ch == "p":
                    show.next_phase()
                elif ch == "w":
                    vis.on_wipe(); show.new_visitor()
                elif ch == "v":
                    show.new_visitor()
                elif ch == "f":
                    pygame.display.toggle_fullscreen()
                elif ch and ch in "ocean":
                    k = ch.upper()
                    d = -0.15 if ev.mod & pygame.KMOD_SHIFT else 0.15
                    show.ocean[k] = round(min(1, max(0, show.ocean[k] + d)), 2)
        if pygame.mouse.get_focused():
            mx, my = pygame.mouse.get_pos()
            sw, sh = screen.get_size()
            show.mouse = (mx / sw * 2 - 1, my / sh * 2 - 1)
        show.step(dt)
        st = show.state()
        vis.on_state(st)
        if t - last_frame > 0.25:  # the N900 sends at most 4 fps
            present = 1.0 if st["phase"] in ("approach", "profiling", "hook", "release") else 0.0
            fr = cam(t, present)
            if fr is not None:
                vis.on_frame(fr)
            last_frame = t
        vis.render(screen, dt)
        if not args.clean:
            o = st["ocean"]
            info = "%s  %s  t=%.0f  O%.2f C%.2f E%.2f A%.2f N%.2f  %.0f ms" % (
                st["phase"], st["hook"], st["phase_t"], o["O"], o["C"], o["E"], o["A"], o["N"], vis.frame_ms)
            screen.blit(font.render(info, True, (255, 255, 255), (0, 0, 0)), (8, 8))
        pygame.display.flip()


def render_stills(args):
    """Headless: render each hook for a few visitors and save PNGs."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from . import create
    pygame.display.init(); pygame.font.init()  # not pygame.init(): keep ALSA free for the audio
    out = args.stills
    os.makedirs(out, exist_ok=True)
    W, H = 1920, 1080
    target = pygame.Surface((W, H))
    visitors = [
        ("high-N-low-A", {"O": 0.55, "C": 0.3, "E": 0.45, "A": 0.15, "N": 0.9}),
        ("high-O-high-E", {"O": 0.9, "C": 0.35, "E": 0.85, "A": 0.6, "N": 0.4}),
        ("high-C-low-E", {"O": 0.3, "C": 0.9, "E": 0.2, "A": 0.7, "N": 0.3}),
    ]
    cam = camera_source(args)
    timings = []
    for vname, oc in visitors:
        for hook in HOOKS:
            random.seed(hash((vname, hook)) & 0xffff)
            vis = create((W, H), {})
            t = 0.0
            dt = 1 / 15
            seq = [("idle", 1.0), ("approach", 3.0), ("profiling", 4.0), ("hook", 9.0)]
            for phase, dur in seq:
                pt = 0.0
                while pt < dur:
                    st = {"visitor_id": vname, "phase": phase, "phase_t": pt, "hook": hook,
                          "intensity": 0.85 if phase == "hook" else 0.5, "ocean": oc,
                          "words": ["LINGERED 41S", "LOOKED AWAY 3X", "LEFT EARLY"]}
                    vis.on_state(st)
                    if int(t * 4) != int((t - dt) * 4):
                        vis.on_frame(cam(t, 0.0 if phase == "idle" else 1.0))
                    t0 = time.perf_counter()
                    vis.render(target, dt)
                    timings.append(time.perf_counter() - t0)
                    t += dt; pt += dt
                    if phase == "profiling" and abs(pt - 3.0) < dt / 2 and hook == "flesh":
                        pygame.image.save(target, os.path.join(out, "%s_profiling.png" % vname))
            pygame.image.save(target, os.path.join(out, "%s_%s.png" % (vname, hook)))
            print("saved", vname, hook)
    timings.sort()
    print("render ms: median %.1f  p95 %.1f (this machine, %dx%d out)" % (
        timings[len(timings) // 2] * 1000, timings[int(len(timings) * 0.95)] * 1000, W, H))


def capture(args):
    """Headless: run the fake show and write an MP4 with ffmpeg (optionally with a WAV)."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import subprocess
    import pygame
    from . import create
    pygame.display.init(); pygame.font.init()  # not pygame.init(): keep ALSA free for the audio
    W, H, fps = 1920, 1080, 15
    target = pygame.Surface((W, H))
    vis = create((W, H), {})
    show = FakeShow(args.hook, args.seed)
    cam = camera_source(args)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-"]
    if args.audio:
        cmd += ["-i", args.audio, "-shortest", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", args.capture]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    dt = 1.0 / fps
    t = 0.0
    for i in range(int(args.seconds * fps)):
        show.step(dt)
        st = show.state()
        if not args.hook and st["phase"] == "hook":  # tour all five hooks, 8 s each
            st["hook"] = st["scene"] = HOOKS[int(st["phase_t"] // 8) % 5]
        vis.on_state(st)
        if i % (fps // 4) == 0:
            present = 1.0 if st["phase"] in ("approach", "profiling", "hook", "release") else 0.0
            fr = cam(t, present)
            if fr is not None:
                vis.on_frame(fr)
        vis.render(target, dt)
        ff.stdin.write(pygame.image.tostring(target, "RGB"))
        t += dt
    ff.stdin.close()
    ff.wait()
    print("wrote", args.capture)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--hook", choices=HOOKS)
    ap.add_argument("--image")
    ap.add_argument("--webcam", action="store_true")
    ap.add_argument("--stills", metavar="DIR")
    ap.add_argument("--capture", metavar="OUT.mp4", help="record a video of the fake show, no window")
    ap.add_argument("--audio", metavar="WAV", help="with --capture: mux this audio in")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--clean", action="store_true", help="hide the info line")
    args = ap.parse_args()
    if args.stills:
        render_stills(args)
    elif args.capture:
        capture(args)
    else:
        run_window(args)


if __name__ == "__main__":
    main()
