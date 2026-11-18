"""A crude OCEAN guess made on the Pi when the real profiler isn't running.

It only looks at how the visitor moves around the phone: how much, how jittery,
whether they touch it, tilt it, type on it, get close. It's deliberately simple,
and says so: confidence never goes above 0.45 and the source is "fallback".
The real work belongs to infinite_jest/profiler/.
"""
from __future__ import annotations

import math

from .protocol import num

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")


class FallbackProfiler:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.n = 0
        self.motion_sum = 0.0
        self.motion_sq = 0.0
        self.loud_sum = 0.0
        self.touches = 0
        self.keys = 0
        self.near = 0.0
        self.tilt_prev: tuple[float, float] | None = None
        self.tilt_travel = 0.0

    def feed(self, d: dict) -> None:
        kind = d.get("kind", "phone")
        if kind in ("touch", "choice"):
            self.touches += 1
            return
        if kind == "keys":
            self.keys += len(str(d.get("text", "")))
            return
        m = max(num(d.get("motion")), num(d.get("shake")))
        self.n += 1
        self.motion_sum += m
        self.motion_sq += m * m
        audio = d.get("audio") if isinstance(d.get("audio"), dict) else {}
        self.loud_sum += max(num(d.get("loudness")), num(audio.get("level")))
        prox = d.get("proximity")
        near = prox.get("near") if isinstance(prox, dict) else prox
        held = d.get("held")
        self.near += max(1.0 if near is True else num(near), 1.0 if held is True else num(held))
        tilt = d.get("tilt")
        if isinstance(tilt, dict):
            b = num(tilt.get("beta"), 0, -180, 180)
            g = num(tilt.get("gamma"), 0, -180, 180)
            if self.tilt_prev is not None:
                self.tilt_travel += abs(b - self.tilt_prev[0]) + abs(g - self.tilt_prev[1])
            self.tilt_prev = (b, g)

    def profile(self) -> dict:
        n = max(1, self.n)
        mean = self.motion_sum / n
        var = max(0.0, self.motion_sq / n - mean * mean)
        jitter = min(1.0, math.sqrt(var) * 3)
        loud = self.loud_sum / n
        play = min(1.0, (self.touches + self.keys * 0.5) / max(5.0, n * 0.1) + self.tilt_travel / (n * 20 + 1))
        near = min(1.0, self.near / n * 2)
        ocean = {
            "O": _mix(0.5, play, 0.6),
            "C": _mix(0.5, 1 - jitter, 0.5),
            "E": _mix(0.5, min(1.0, mean * 1.5 + loud * 0.5), 0.6),
            "A": _mix(0.5, near, 0.5),
            "N": _mix(0.5, jitter, 0.6),
        }
        hook = pick_hook(ocean)
        confidence = min(0.45, n / 250)
        return {"ocean": ocean, "confidence": confidence, "hook": hook, "source": "fallback"}


def _mix(a: float, b: float, w: float) -> float:
    return round(a * (1 - w) + b * w, 3)


def pick_hook(ocean: dict) -> str:
    """Which imagery should pull this person in? A plain lookup, easy to tune."""
    score = {
        "flesh": ocean["N"] * 1.0 + (1 - ocean["A"]) * 0.4,         # Bacon: anxiety, the body
        "scrawl": ocean["O"] * 1.0 + ocean["E"] * 0.3,               # Basquiat: curiosity, noise
        "inverted": ocean["C"] * 0.8 + (1 - ocean["O"]) * 0.4,       # Baselitz: order turned over
        "mirror": ocean["E"] * 0.9 + ocean["A"] * 0.3,               # the show plays them back
        "void": (1 - ocean["E"]) * 0.8 + ocean["N"] * 0.2,           # the quiet ones
    }
    return max(score, key=score.get)
