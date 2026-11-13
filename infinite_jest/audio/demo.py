"""Standalone demo of the INFINITE JEST sound engine.

    python3 -m infinite_jest.audio.demo                      # play live, endless
    python3 -m infinite_jest.audio.demo --render out.wav --seconds 90
    python3 -m infinite_jest.audio.demo --ocean 0.9,0.3,0.4,0.1,0.9 --hook scrawl --seed 3

A fake visitor walks through idle -> approach -> profiling -> hook -> release.
Live mode then wipes and a new visitor (new OCEAN, next hook) arrives.
A slow fake phone-tilt sweep and an occasional 'shake' are included.
"""
import argparse
import math
import sys
import time
import wave

HOOK_CYCLE = ("flesh", "scrawl", "inverted", "mirror", "void")
# (phase, share of the cycle, intensity at start, intensity at end)
ARC = (("idle", 0.11, 0.10, 0.15), ("approach", 0.16, 0.25, 0.40),
       ("profiling", 0.24, 0.45, 0.65), ("hook", 0.36, 0.75, 0.95),
       ("release", 0.13, 0.50, 0.30))


def visitor_ocean(i, fixed=None):
    if fixed:
        return dict(zip("OCEAN", fixed))
    import random
    r = random.Random(1000 + i)
    return {k: round(r.random(), 2) for k in "OCEAN"}


def state_at(t, cycle_s, ocean, hook, vid, tilt=True):
    u = (t % cycle_s) / cycle_s
    acc = 0.0
    phase, i0, i1, share, start = "release", 0.3, 0.3, 1.0, 0.0
    for ph, sh, a, b in ARC:
        if u < acc + sh:
            phase, i0, i1, share, start = ph, a, b, sh, acc
            break
        acc += sh
    k = (u - start) / share
    st = {
        "visitor_id": vid, "phase": phase, "scene": phase,
        "intensity": i0 + (i1 - i0) * k, "ocean": ocean, "hook": hook,
        "phase_t": (u - start) * cycle_s,
        "palette": {"name": "demo", "colors": ["#111111", "#7a0f0f"]},
    }
    if tilt:
        x = math.sin(t * 2 * math.pi / 11.0)
        y = math.sin(t * 2 * math.pi / 17.0 + 1.0)
        shake = 0.8 if (t % 23.0) < 0.4 and phase in ("profiling", "hook") else 0.0
        st["steer"] = {"x": round(x, 3), "y": round(y, 3), "flip": False, "shake": shake}
    return st


def render(path, seconds, ocean, hook, seed, cycle_s, tilt):
    import numpy as np
    from .synth import TechnoSynth, SR
    synth = TechnoSynth(seed=0)
    vid = "demo-%d" % seed
    n_blocks = int(seconds * SR / synth.B)
    out = []
    cpu0 = time.process_time()
    for b in range(n_blocks):
        t = b * synth.B / float(SR)
        if b % 4 == 0:      # ~12 state updates per second, like the show engine
            synth.set_state(state_at(t, cycle_s, ocean, hook, vid, tilt))
        out.append(synth.render_block())
    cpu = time.process_time() - cpu0
    data = np.concatenate(out)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print("wrote %s: %.1f s audio in %.2f s CPU (realtime factor %.1fx)"
          % (path, seconds, cpu, seconds / max(cpu, 1e-9)))


def live(ocean_fixed, hook_fixed, seed, cycle_s, tilt, device):
    from . import create
    eng = create({"audio_device": device})
    eng.start()
    i = 0
    print("playing; Ctrl+C to stop")
    try:
        while True:
            ocean = visitor_ocean(i, ocean_fixed)
            hook = hook_fixed or HOOK_CYCLE[i % len(HOOK_CYCLE)]
            vid = "demo-%d-%d" % (seed, i)
            print("visitor %s hook=%s OCEAN=%s" % (vid, hook, ocean))
            t0 = time.monotonic()
            last = None
            while time.monotonic() - t0 < cycle_s:
                st = state_at(time.monotonic() - t0, cycle_s, ocean, hook, vid, tilt)
                if st["phase"] != last:
                    print("  phase:", st["phase"])
                    last = st["phase"]
                eng.on_state(st)
                time.sleep(0.1)
            print("  wipe")
            eng.on_wipe()
            eng.on_state({"phase": "wipe"})
            time.sleep(3.0)
            i += 1
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", metavar="OUT.wav", help="render offline to a WAV instead of playing")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--ocean", help="O,C,E,A,N each 0..1 (default: changes per visitor)")
    ap.add_argument("--hook", help="flesh|scrawl|inverted|mirror|void (default: cycles)")
    ap.add_argument("--seed", type=int, default=1, help="fake visitor seed (their 'track')")
    ap.add_argument("--cycle", type=float, default=None, help="seconds per visitor arc")
    ap.add_argument("--no-tilt", action="store_true", help="disable the fake phone tilt")
    ap.add_argument("--device", default="default", help="ALSA device for live mode")
    a = ap.parse_args(argv)
    ocean = None
    if a.ocean:
        ocean = [max(0.0, min(1.0, float(v))) for v in a.ocean.split(",")]
        if len(ocean) != 5:
            ap.error("--ocean needs 5 numbers")
    if a.render:
        cyc = a.cycle or a.seconds
        render(a.render, a.seconds, dict(zip("OCEAN", ocean)) if ocean else visitor_ocean(a.seed),
               a.hook or HOOK_CYCLE[a.seed % len(HOOK_CYCLE)], a.seed, cyc, not a.no_tilt)
    else:
        live(ocean, a.hook, a.seed, a.cycle or 90.0, not a.no_tilt, a.device)


if __name__ == "__main__":
    sys.exit(main())
