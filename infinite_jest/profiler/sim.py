"""Simulated visitors, so the profiler can be rehearsed without a room.

Each archetype produces a stream of contract messages ("sensor" kind phone /
touch / choice / keys, and "vision" readings standing in for what vision.py
derives from frames). Engagement responds to the hook the profiler picks, so
the bandit has something real to learn from: each archetype has a hidden
favourite hook.
"""

import math
import random

ARCHETYPES = {
    # name: behaviour knobs, hidden favourite hook
    "performer": dict(pace=0.30, close=0.65, motion=0.55, gaze=0.8, voice=0.45,
                      loud=0.5, touch=10, explore=0.8, choices=["look closer", "the noise", "seen", "upside down", "tell"],
                      latency=1.0, hold=0.4, tilt=60, favourite="scrawl"),
    "lurker":    dict(pace=0.06, close=0.15, motion=0.08, gaze=0.15, voice=0.0,
                      loud=0.0, touch=0, explore=0.1, choices=["look away", "the silence", "forgotten", "right way up", "keep"],
                      latency=4.5, hold=0.0, tilt=0, favourite="void"),
    "nerve":     dict(pace=0.15, close=0.25, motion=0.35, gaze=0.3, voice=0.05,
                      loud=0.2, touch=4, explore=0.3, choices=["look away", "the noise", "forgotten", "upside down", "keep"],
                      latency=1.2, burst=True, hold=0.3, tilt=25, favourite="flesh"),
    "seeker":    dict(pace=0.10, close=0.5, motion=0.25, gaze=0.6, voice=0.1,
                      loud=0.25, touch=6, explore=0.9, choices=["look closer", "the noise", "seen", "upside down", "tell"],
                      latency=2.5, hold=0.5, tilt=80, favourite="inverted"),
}


def visitor(name, profiler_hook=lambda: None, seconds=70, hz=4, seed=0, visitor_id="v-sim"):
    """Yield (ts, message) for one simulated visit.

    profiler_hook: callable returning the hook currently shown, so the
    simulated person can react to it.
    """
    a = ARCHETYPES[name]
    rng = random.Random(seed)
    t0 = 1000.0
    yield t0, {"type": "state", "ts": t0, "data": {"visitor_id": visitor_id, "phase": "approach",
                                             "mode": "fixed"}}
    cx = 0.0 if rng.random() < 0.5 else 1.0
    direction = 1 if cx == 0.0 else -1
    size = 0.05
    prompts = ["closer", "scream", "seen", "upside", "secret"]
    next_prompt = 12.0
    n_choice = 0
    for i in range(int(seconds * hz)):
        t = t0 + i / hz
        el = t - t0
        hook = profiler_hook()
        liked = 1.0 if hook == a["favourite"] else 0.0
        # walk in, then wander
        if el < 8:
            cx += direction * a["pace"] / hz
        else:
            cx += rng.gauss(0, 0.02 + 0.05 * a["explore"])
        cx = min(1.0, max(0.0, cx))
        target = a["close"] + 0.2 * liked
        size += (target - size) * 0.08
        motion = a["motion"] * (0.3 if liked and el > 15 else 1.0)
        if a.get("burst") and rng.random() < 0.15:
            motion = min(1.0, motion * 3)
        motion = max(0.0, motion + rng.gauss(0, 0.04))
        gaze = min(1.0, a["gaze"] + 0.3 * liked)
        yield t, {"type": "sensor", "ts": t, "data": {
            "kind": "vision", "present": True, "cx": round(cx, 3),
            "size": round(max(0.0, size + rng.gauss(0, 0.02)), 3),
            "motion": round(motion, 3), "face": rng.random() < gaze}}
        if i % max(1, hz // 2) == 0:
            voiced = rng.random() < a["voice"]
            held = el > 10 and (math.sin(el / 7.0) + 1) / 2 < a["hold"]
            ph = el * a["tilt"] / 30.0
            yield t, {"type": "sensor", "ts": t, "data": {
                "kind": "phone", "audio": {"level": a["loud"] if voiced else 0.05,
                                           "voiced": voiced},
                "proximity": {"near": False}, "held": held,
                "tilt": {"alpha": 0, "beta": round(a["tilt"] * math.sin(ph), 1) if held else 0,
                         "gamma": round(a["tilt"] * 0.6 * math.cos(ph * 1.3), 1) if held else 0},
                "accel": {"x": 0.0, "y": 0.0, "z": 1.0 + (rng.gauss(0, 0.2) if a.get("burst") else rng.gauss(0, 0.05))}}}
        if a["touch"] and rng.random() < a["touch"] / 60.0 / hz * 1.0 * (1 + liked):
            x, y = rng.random() * a["explore"] + 0.5 * (1 - a["explore"]), rng.random()
            yield t, {"type": "sensor", "ts": t, "data": {"kind": "touch", "x": x, "y": y, "down": True}}
            dur = 0.1 if rng.random() > 0.2 else 1.2
            yield t + dur, {"type": "sensor", "ts": t + dur, "data": {"kind": "touch", "x": x, "y": y, "down": False}}
        if el >= next_prompt and n_choice < len(prompts):
            yield t, {"type": "sensor", "ts": t, "data": {
                "kind": "choice", "prompt_id": prompts[n_choice],
                "option": a["choices"][n_choice],
                "latency_ms": int(a["latency"] * 1000 * (0.7 + 0.6 * rng.random()))}}
            if prompts[n_choice] == "secret" and a["choices"][n_choice] == "tell":
                yield t, {"type": "sensor", "ts": t, "data": {"kind": "keys", "text": "x" * rng.randint(10, 40)}}
            n_choice += 1
            next_prompt += 9.0
    t = t0 + seconds
    yield t, {"type": "state", "ts": t, "data": {"visitor_id": visitor_id, "phase": "release"}}
    yield t + 6, {"type": "wipe", "ts": t + 6, "data": {"visitor_id": visitor_id}}


def run(name, seed=0, seconds=70, profiler=None, verbose=False):
    """Run one simulated visit through a profiler. Returns (profiles, reveal)."""
    from .core import create
    p = profiler or create({"seed": seed})
    current = {"hook": None}
    profiles, reveal = [], None
    for _ts, m in visitor(name, lambda: current["hook"], seconds=seconds, seed=seed):
        for out in p.handle(m):
            if out["type"] == "profile" and "ocean" in out["data"]:
                current["hook"] = out["data"]["hook"]
                profiles.append(out)
                if verbose and len(profiles) % 5 == 0:
                    d = out["data"]
                    print("{:5.1f}s  {}  conf {:.2f}  hook {:8s} eng {:.2f}  {}".format(
                        d["seconds"], " ".join("{}{:.2f}".format(k, v) for k, v in d["ocean"].items()),
                        d["confidence"], d["hook"], d["engagement"], d["segment"]))
            elif out["type"] == "reveal":
                reveal = out
    return profiles, reveal


# ------------------------------------------------------------ handheld mode --
# Mirrors the integration film's personas (infinite_jest/integration/film.py):
# the visitor holds the N900; the scene they like makes them steadier (tilt
# amplitude x0.45, speed x0.7, tremor x0.6). The camera sees a face of fixed
# size, moved by the hand, so frame motion follows tilt speed.
HANDHELD = {
    "performer": dict(amp=(55, 70), speed=1.4, tremor=0.03, shakes=4.0, voice=0.55, favourite="mirror",
                      choices=["look closer", "the noise", "seen", "upside down", "tell"], latency=0.9),
    "lurker":    dict(amp=(6, 8), speed=0.25, tremor=0.004, shakes=0.0, voice=0.0, favourite="void",
                      choices=["look away", "the silence", "forgotten", "right way up", "keep"], latency=6.0),
    "nerve":     dict(amp=(18, 25), speed=2.2, tremor=0.05, shakes=7.0, voice=0.08, favourite="flesh",
                      choices=["look away", "the noise", "forgotten", "upside down", "keep"], latency=1.3),
    "seeker":    dict(amp=(80, 85), speed=0.6, tremor=0.01, shakes=0.5, voice=0.12, favourite="inverted",
                      choices=["look closer", "the noise", "seen", "upside down", "tell"], latency=2.6),
}


def handheld_visitor(name, profiler_hook=lambda: None, seconds=100, hz=10, seed=0, visitor_id="v-hh"):
    a = HANDHELD[name]
    rng = random.Random(seed)
    t0 = 1000.0
    yield t0, {"type": "state", "ts": t0, "data": {"visitor_id": visitor_id, "phase": "approach",
                                                    "mode": "handheld"}}
    prev = None
    shake_until, next_shake = -1, t0 + 6 + rng.random() * 6
    prompts = ["closer", "scream", "seen", "upside", "secret"]
    next_prompt, n_choice = 12.0, 0
    for i in range(int(seconds * hz)):
        t = t0 + i / hz
        el = t - t0
        liked = profiler_hook() == a["favourite"]
        calm = 0.45 if liked else 1.0
        sp = a["speed"] * (0.7 if liked else 1.0)
        beta = 25 + a["amp"][0] * calm * math.sin(el * sp * 0.73 + 0.4)
        gamma = a["amp"][1] * calm * math.sin(el * sp + 1.1)
        noise = a["tremor"] * (0.6 if liked else 1.0)
        if a["shakes"] and t >= next_shake and el > 5:
            shake_until = t + 0.6 + rng.random() * 0.6
            next_shake = t + 60.0 / a["shakes"] * (0.5 + rng.random())
        if t < shake_until:
            noise += 0.9
        voiced = a["voice"] > 0 and (math.sin(el * 0.35) + 1) / 2 < a["voice"] * (1.3 if liked else 1.0)
        yield t, {"type": "sensor", "ts": t, "data": {
            "kind": "phone", "held": True, "presence": 1.0,
            "tilt": {"alpha": 0, "beta": round(beta, 1), "gamma": round(gamma, 1)},
            "accel": {"x": 0.0, "y": 0.0, "z": 1.0 + rng.gauss(0, noise)},
            "audio": {"level": 0.5 if voiced else 0.05, "voiced": voiced},
            "proximity": {"near": False}}}
        if i % max(1, hz // 4) == 0:  # ~4 fps frames
            mot = 0.0 if prev is None else min(1.0, (abs(beta - prev[0]) + abs(gamma - prev[1])) / 40.0
                                               + noise * 3 + rng.gauss(0, 0.02))
            prev = (beta, gamma)
            yield t, {"type": "sensor", "ts": t, "data": {
                "kind": "vision", "present": True, "cx": round(0.5 + gamma / 400, 3),
                "size": 0.55, "motion": round(max(0.0, mot), 3), "face": rng.random() < 0.7}}
        if el >= next_prompt and n_choice < len(prompts):
            lat = int(a["latency"] * 1000 * (0.7 + 0.6 * rng.random()))
            yield t, {"type": "sensor", "ts": t, "data": {"kind": "choice", "prompt_id": prompts[n_choice],
                                                          "option": a["choices"][n_choice], "latency_ms": lat}}
            n_choice += 1
            next_prompt += 12.0
    t = t0 + seconds
    yield t, {"type": "state", "ts": t, "data": {"visitor_id": visitor_id, "phase": "release"}}
    yield t + 6, {"type": "wipe", "ts": t + 6, "data": {"visitor_id": visitor_id}}


def run_handheld(name, seed=0, seconds=100, profiler=None):
    """Run one handheld visit. Returns (profiles, reveal)."""
    from .core import create
    p = profiler or create({"seed": seed})
    current = {"hook": None}
    profiles, reveal = [], None
    for _ts, m in handheld_visitor(name, lambda: current["hook"], seconds=seconds, seed=seed):
        for out in p.handle(m):
            if out["type"] == "profile" and "ocean" in out["data"]:
                current["hook"] = out["data"]["hook"]
                profiles.append(out)
            elif out["type"] == "reveal":
                reveal = out
    return profiles, reveal
