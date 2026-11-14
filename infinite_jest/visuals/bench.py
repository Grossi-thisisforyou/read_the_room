"""Speed test for the Pi: how fast do picture and sound render on this machine?

    python3 -m infinite_jest.visuals.bench            # about 1 minute
    python3 -m infinite_jest.visuals.bench --quick    # about 20 seconds

Renders every hook at 1920x1080 with no window, at a few internal resolutions,
times the techno engine, then prints a recommendation for the show config.
Run it on the Pi with the language model running too, to get honest numbers.
"""
import argparse
import os
import platform
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

HOOKS = ["flesh", "scrawl", "inverted", "mirror", "void"]
BUDGET_MS = 25.0  # one core, leaves room for the engine loop at 30 fps


def bench_visuals(internal, seconds_per_hook, out_size=(1920, 1080)):
    import numpy as np
    import pygame
    from . import create
    from .figure import ghost_body
    pygame.display.init()
    pygame.font.init()
    target = pygame.Surface(out_size)
    vis = create(out_size, {"internal_size": internal, "busy_file": None})
    times = {}
    t = 0.0
    dt = 1 / 30
    oc = {"O": 0.7, "C": 0.3, "E": 0.6, "A": 0.3, "N": 0.8}
    for hook in HOOKS:
        samples = []
        n = int(seconds_per_hook * 30)
        for i in range(n):
            st = {"visitor_id": "bench", "phase": "hook", "phase_t": i * dt, "hook": hook,
                  "intensity": 0.9, "ocean": oc, "words": ["LINGERED 41S", "LOOKED AWAY 3X"],
                  "steer": {"x": np.sin(t), "y": np.cos(t * 0.7) * 0.5, "flip": False, "shake": 0.0}}
            vis.on_state(st)
            if i % 8 == 0:
                vis.on_frame(ghost_body(160, 120, t, present=1.0))
            t0 = time.perf_counter()
            vis.render(target, dt)
            samples.append((time.perf_counter() - t0) * 1000)
            t += dt
        samples = sorted(samples[10:]) or [0]
        times[hook] = (samples[len(samples) // 2], samples[int(len(samples) * 0.95)])
    return times


def bench_audio(seconds):
    try:
        from ..audio.synth import TechnoSynth, SR
    except Exception as e:  # audio module missing
        return None, str(e)
    synth = TechnoSynth(seed=0)
    st = {"visitor_id": "bench", "phase": "hook", "hook": "flesh", "intensity": 0.9,
          "ocean": {"O": 0.7, "C": 0.3, "E": 0.6, "A": 0.3, "N": 0.8}}
    synth.set_state(st)
    n = int(seconds * SR / synth.B)
    c0 = time.process_time()
    for _ in range(n):
        synth.render_block()
    cpu = time.process_time() - c0
    return seconds / max(cpu, 1e-9), None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    per_hook = 1.5 if args.quick else 4.0
    print("Machine: %s %s, %d cores" % (platform.machine(), platform.processor() or "", os.cpu_count() or 0))
    results = {}
    for internal in [(640, 360), (480, 270), (960, 540)]:
        res = bench_visuals(internal, per_hook)
        results[internal] = res
        worst = max(p95 for _, p95 in res.values())
        print("\nPicture at internal %dx%d (output 1920x1080):" % internal)
        for hook, (med, p95) in res.items():
            print("  %-9s median %5.1f ms   slowest 5%% %5.1f ms   (~%d fps)" % (hook, med, p95, 1000 / max(med, 1)))
        print("  worst case %.1f ms" % worst)
        if args.quick and internal == (480, 270):
            break
    rt, err = bench_audio(10 if args.quick else 30)
    print()
    if rt is None:
        print("Sound: could not test (%s)" % err)
    else:
        print("Sound: renders %.1fx faster than real time, so it uses about %d%% of one core"
              % (rt, min(100, round(100 / rt))))
    # recommendation
    pick = None
    for internal in [(960, 540), (640, 360), (480, 270)]:
        if internal in results and max(m for m, _ in results[internal].values()) <= BUDGET_MS:
            pick = internal
            break
    print("\nRecommendation:")
    if pick:
        print('  visuals config: {"internal_size": [%d, %d]}' % pick)
    else:
        print('  too slow even at 480x270: use {"internal_size": [480, 270], "smooth_scale": false}')
    if rt is not None and rt < 3:
        print("  sound is heavy here: close other programs or lower the language model's threads")


if __name__ == "__main__":
    main()
