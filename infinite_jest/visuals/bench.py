"""Speed test for the Pi: how fast do picture and sound render on this machine?

    python3 -m infinite_jest.visuals.bench            # about 1 minute
    python3 -m infinite_jest.visuals.bench --quick    # about 20 seconds

Renders every hook at 1920x1080 with no window, at a few internal resolutions
with smooth scaling on and off,
times the techno engine, then prints a recommendation for the show config.
Run it on the Pi with the language model running too, to get honest numbers.
"""
import argparse
import json
import os
import platform
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

HOOKS = ["flesh", "scrawl", "inverted", "mirror", "void"]
BUDGET_MS = 30.0      # median frame on ~one core: 30 fps with a little room for the engine loop
BUDGET_P95_MS = 40.0  # the slowest 5%: an occasional 25 fps frame is fine on a projector


def bench_visuals(internal, seconds_per_hook, out_size=(1920, 1080), smooth=True):
    import numpy as np
    import pygame
    from . import create
    from .figure import ghost_body
    pygame.display.init()
    pygame.font.init()
    target = pygame.Surface(out_size)
    vis = create(out_size, {"internal_size": internal, "busy_file": None, "smooth_scale": smooth})
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
    """Real-time factor of the render loop as it runs in the show: slow sounds
    come from the synth's helper process, so they are left out of the time
    (after a short warm-up, so the visitor's first sounds have arrived)."""
    try:
        from ..audio.synth import TechnoSynth, SR
    except Exception as e:  # audio module missing
        return None, str(e)
    synth = TechnoSynth(seed=0, threaded=True)
    try:
        st = {"visitor_id": "bench", "phase": "hook", "hook": "flesh", "intensity": 0.9,
              "ocean": {"O": 0.7, "C": 0.3, "E": 0.6, "A": 0.3, "N": 0.8}}
        synth.set_state(st)
        for _ in range(int(2 * SR / synth.B)):
            synth.render_block()
            time.sleep(0.002)
        n = int(seconds * SR / synth.B)
        c0 = time.process_time()
        for _ in range(n):
            synth.render_block()
        cpu = time.process_time() - c0
    finally:
        synth.close()
    return seconds / max(cpu, 1e-9), None


# The knobs, in the order to turn them: smoothing off first (about -25% frame
# time at 1080p on a Pi 5, hardly visible on a projector), then the smaller
# internal picture. Measured on a Pi 5: hook frames 30-45 ms at 1080p with
# the defaults (22-30 fps).
CANDIDATES = [((960, 540), True), ((640, 360), True), ((640, 360), False), ((480, 270), False)]


def _fits(res):
    return (max(m for m, _ in res.values()) <= BUDGET_MS
            and max(p for _, p in res.values()) <= BUDGET_P95_MS)


def recommend(smooth, rough):
    """smooth / rough: {internal_size: {hook: (median ms, p95 ms)}} measured with
    smooth_scale on / off. Returns the visuals config to use; adds
    "too_slow": True when even the cheapest setting misses the budget."""
    for internal, sm in CANDIDATES:
        res = (smooth if sm else rough).get(internal)
        if res and _fits(res):
            out = {"internal_size": list(internal)}
            if not sm:
                out["smooth_scale"] = False
            return out
    return {"internal_size": [480, 270], "smooth_scale": False, "too_slow": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    per_hook = 1.5 if args.quick else 4.0
    print("Machine: %s %s, %d cores" % (platform.machine(), platform.processor() or "", os.cpu_count() or 0))
    smooth, rough = {}, {}
    runs = [((640, 360), True), ((640, 360), False), ((480, 270), False)]
    if not args.quick:
        runs = [((960, 540), True)] + runs + [((480, 270), True)]
    for internal, sm in runs:
        res = bench_visuals(internal, per_hook, smooth=sm)
        (smooth if sm else rough)[internal] = res
        worst = max(p95 for _, p95 in res.values())
        print("\nPicture at internal %dx%d, smooth_scale %s (output 1920x1080):"
              % (internal[0], internal[1], "on" if sm else "off"))
        for hook, (med, p95) in res.items():
            print("  %-9s median %5.1f ms   slowest 5%% %5.1f ms   (~%d fps)" % (hook, med, p95, 1000 / max(med, 1)))
        print("  worst case %.1f ms" % worst)
    rt, err = bench_audio(10 if args.quick else 30)
    print()
    if rt is None:
        print("Sound: could not test (%s)" % err)
    else:
        print("Sound: renders %.1fx faster than real time, so it uses about %d%% of one core"
              % (rt, min(100, round(100 / rt))))
    adv = recommend(smooth, rough)
    print("\nRecommendation (budget: median <= %.0f ms, slowest 5%% <= %.0f ms per frame):" % (BUDGET_MS, BUDGET_P95_MS))
    cfg = {k: v for k, v in adv.items() if k != "too_slow"}
    print("  visuals config: %s" % json.dumps(cfg))
    if adv.get("too_slow"):
        print("  still too slow at 480x270 without smoothing: lower the language model's threads,"
              " or project at 1280x720")
    if rt is not None and rt < 8:
        print("  sound has little headroom here (under 8x real time): close other programs or"
              " lower the language model's threads")


if __name__ == "__main__":
    main()
