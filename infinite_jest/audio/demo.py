"""Standalone demo of the INFINITE JEST sound engine.

    python3 -m infinite_jest.audio.demo                      # play live, endless
    python3 -m infinite_jest.audio.demo --render out.wav --seconds 90
    python3 -m infinite_jest.audio.demo --ocean 0.9,0.3,0.4,0.1,0.9 --hook scrawl --seed 3
    python3 -m infinite_jest.audio.demo --evening set.wav    # 10-minute simulated evening

A fake visitor walks through the show's phases with its real timings:
idle -> approach (3 s) -> profiling -> hook (with a 4 s 'hinge' held breath
100 s in, if the hook lasts that long) -> release (50 s) -> wipe (12 s).
A fake phone tilt sweeps the sound around; occasional shakes and flips.
"""
import argparse
import math
import random
import sys
import time
import wave

HOOK_CYCLE = ("flesh", "scrawl", "inverted", "mirror", "void")
APPROACH_S, RELEASE_S, WIPE_S = 3.0, 50.0, 12.0
HINGE_AT, HINGE_S = 100.0, 4.0


def visitor_ocean(i, fixed=None):
    if fixed:
        return dict(zip("OCEAN", fixed))
    r = random.Random(1000 + i)
    return {k: round(r.random(), 2) for k in "OCEAN"}


class Visit:
    """One visitor's timeline, in seconds from their arrival."""

    def __init__(self, vid, ocean, hook, profiling=16.0, hook_s=110.0, release=RELEASE_S,
                 wipe=WIPE_S, hinge_at=HINGE_AT, tilt=True, flip_at=None, seed=0):
        self.vid, self.ocean, self.hook = vid, ocean, hook
        self.segs = [("approach", APPROACH_S, 0.25, 0.35), ("profiling", profiling, 0.45, 0.65),
                     ("hook", hook_s, 0.75, 0.95), ("release", release, 0.5, 0.25),
                     ("wipe", wipe, 0.2, 0.1)]
        self.length = sum(s[1] for s in self.segs)
        self.hinge_at = hinge_at
        self.tilt = tilt
        self.flip_at = flip_at
        self.r = random.Random(seed)
        self.tempo = round(126.0 + 14.0 * ocean.get("E", 0.5), 1)

    def state(self, t):
        acc = 0.0
        for ph, dur, i0, i1 in self.segs:
            if t < acc + dur:
                break
            acc += dur
        k = min(1.0, max(0.0, (t - acc) / dur))
        pt = t - acc
        # the profiler's guess converges from neutral during profiling
        conv = 0.0 if ph == "approach" else (min(1.0, pt / max(1.0, dur * 0.8)) if ph == "profiling" else 1.0)
        oc = {key: round(0.5 + (v - 0.5) * conv, 3) for key, v in self.ocean.items()}
        st = {"visitor_id": self.vid if ph != "wipe" else "", "phase": ph, "scene": ph,
              "phase_t": round(pt, 2), "intensity": round(i0 + (i1 - i0) * k, 3), "ocean": oc,
              "hook": self.hook if ph in ("profiling", "hook", "release") else "",
              "tempo": self.tempo, "hinge": False,
              "palette": {"name": "ash", "colors": ["#000000", "#151515"]}}
        if ph == "hook" and self.hinge_at is not None and self.hinge_at <= pt < self.hinge_at + HINGE_S:
            st["hinge"] = True
        if self.tilt and ph in ("approach", "profiling", "hook", "release"):
            x = math.sin(t * 2 * math.pi / 11.0) * (0.4 + 0.5 * math.sin(t / 7.0) ** 2)
            y = math.sin(t * 2 * math.pi / 17.0 + 1.0) * 0.8
            shake = 0.8 if (t % 23.0) < 0.4 and ph in ("profiling", "hook") else 0.0
            flip = self.flip_at is not None and self.flip_at <= t < self.flip_at + 6.0
            st["steer"] = {"x": round(x, 3), "y": round(y, 3), "flip": flip, "shake": shake}
        return st


class Evening:
    """Idle gaps and visits laid end to end."""

    def __init__(self, items):
        self.items = items              # list of ("idle", seconds) or Visit

    def state(self, t):
        acc = 0.0
        for it in self.items:
            dur = it[1] if isinstance(it, tuple) else it.length
            if t < acc + dur:
                if isinstance(it, tuple):
                    return {"visitor_id": "", "phase": "idle", "scene": "idle", "intensity": 0.12,
                            "phase_t": round(t - acc, 2), "tempo": 128, "hook": "", "hinge": False,
                            "steer": {"x": 0.0, "y": 0.0, "flip": False, "shake": 0.0}}
                return it.state(t - acc)
            acc += dur
        return {"visitor_id": "", "phase": "idle", "intensity": 0.12}

    @property
    def length(self):
        return sum(it[1] if isinstance(it, tuple) else it.length for it in self.items)


def evening_10min():
    """The 10-minute simulated evening used for the artist renders."""
    return Evening([
        ("idle", 40.0),
        Visit("v-a17c", dict(O=0.4, C=0.5, E=0.35, A=0.2, N=0.85), "flesh", 16.0, 106.0, seed=1),
        ("idle", 30.0),
        Visit("v-3e90", dict(O=0.85, C=0.2, E=0.6, A=0.5, N=0.5), "inverted", 10.0, 64.0,
              hinge_at=None, flip_at=40.0, seed=2),
        ("idle", 20.0),
        Visit("v-c4d2", dict(O=0.9, C=0.35, E=0.75, A=0.45, N=0.6), "scrawl", 18.0, 105.0, seed=3),
    ])


def hook_sample(hook, seed=1, ocean=None):
    """~90 s: a short idle, then one visitor on this hook, hinge included."""
    oc = ocean or {"flesh": dict(O=0.4, C=0.5, E=0.35, A=0.2, N=0.85),
                   "scrawl": dict(O=0.9, C=0.35, E=0.75, A=0.45, N=0.6),
                   "inverted": dict(O=0.85, C=0.2, E=0.6, A=0.5, N=0.5),
                   "mirror": dict(O=0.5, C=0.5, E=0.85, A=0.6, N=0.4),
                   "void": dict(O=0.3, C=0.85, E=0.2, A=0.5, N=0.3)}.get(hook, visitor_ocean(seed))
    return Evening([("idle", 5.0),
                    Visit("v-%s" % hook, oc, hook, 12.0, 56.0, hinge_at=40.0, seed=seed)])


def render_script(path, script, seconds, quiet=False):
    import numpy as np
    from .synth import TechnoSynth, SR
    synth = TechnoSynth(seed=0)
    n_blocks = int(seconds * SR / synth.B)
    out = np.empty((n_blocks * synth.B, 2), np.int16)
    cpu0 = time.process_time()
    worst = 0.0
    for b in range(n_blocks):
        t = b * synth.B / float(SR)
        if b % 4 == 0:      # ~12 state updates per second, like the show engine
            st = script.state(t)
            if st.get("phase") == "wipe" and not synth.wiping and synth.in_phase != "wipe":
                synth.wipe()
            synth.set_state(st)
        c0 = time.perf_counter()
        out[b * synth.B:(b + 1) * synth.B] = synth.render_block()
        worst = max(worst, time.perf_counter() - c0)
    cpu = time.process_time() - cpu0
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(out.tobytes())
    if not quiet:
        print("wrote %s: %.1f s audio in %.2f s CPU (realtime factor %.1fx, worst block %.1f ms of %.1f)"
              % (path, seconds, cpu, seconds / max(cpu, 1e-9), worst * 1000, synth.B * 1000.0 / SR))
    return seconds / max(cpu, 1e-9)


def live(ocean_fixed, hook_fixed, seed, tilt, device):
    from . import create
    eng = create({"audio_device": device})
    eng.start()
    i = 0
    print("playing; Ctrl+C to stop")
    try:
        while True:
            idle = 8.0
            t0 = time.monotonic()
            while time.monotonic() - t0 < idle:
                eng.on_state({"visitor_id": "", "phase": "idle", "intensity": 0.12})
                time.sleep(0.1)
            ocean = visitor_ocean(i, ocean_fixed)
            hook = hook_fixed or HOOK_CYCLE[i % len(HOOK_CYCLE)]
            v = Visit("demo-%d-%d" % (seed, i), ocean, hook, 14.0, 70.0, hinge_at=50.0, tilt=tilt, seed=i)
            print("visitor %s hook=%s OCEAN=%s" % (v.vid, hook, ocean))
            t0 = time.monotonic()
            last = None
            while time.monotonic() - t0 < v.length:
                st = v.state(time.monotonic() - t0)
                if st["phase"] != last:
                    print("  phase:", st["phase"])
                    if st["phase"] == "wipe":
                        eng.on_wipe()
                    last = st["phase"]
                eng.on_state(st)
                time.sleep(0.1)
            i += 1
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", metavar="OUT.wav", help="render offline to a WAV instead of playing")
    ap.add_argument("--evening", metavar="OUT.wav", help="render the 10-minute simulated evening")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--ocean", help="O,C,E,A,N each 0..1 (default: changes per visitor)")
    ap.add_argument("--hook", help="flesh|scrawl|inverted|mirror|void (default: cycles)")
    ap.add_argument("--seed", type=int, default=1, help="fake visitor seed (their 'track')")
    ap.add_argument("--no-tilt", action="store_true", help="disable the fake phone tilt")
    ap.add_argument("--device", default="default", help="ALSA device for live mode")
    a = ap.parse_args(argv)
    ocean = None
    if a.ocean:
        ocean = [max(0.0, min(1.0, float(v))) for v in a.ocean.split(",")]
        if len(ocean) != 5:
            ap.error("--ocean needs 5 numbers")
    if a.evening:
        ev = evening_10min()
        render_script(a.evening, ev, min(a.seconds if a.seconds != 90.0 else 600.0, ev.length))
    elif a.render:
        hook = a.hook or HOOK_CYCLE[a.seed % len(HOOK_CYCLE)]
        oc = dict(zip("OCEAN", ocean)) if ocean else None
        sc = hook_sample(hook, a.seed, oc)
        if a.no_tilt:
            for it in sc.items:
                if isinstance(it, Visit):
                    it.tilt = False
        render_script(a.render, sc, a.seconds)
    else:
        live(ocean, a.hook, a.seed, not a.no_tilt, a.device)


if __name__ == "__main__":
    sys.exit(main())
