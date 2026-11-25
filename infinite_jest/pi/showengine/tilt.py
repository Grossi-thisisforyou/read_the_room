"""The N900 is meant to be picked up and moved: its tilt is a live input.

Turns the phone's raw tilt (beta/gamma in degrees) into a smooth -1..1 position
(x = roll, y = pitch, 0,0 = lying flat) and an "energy" 0..1 for how much it is
being moved right now. Ticked every frame so the picture moves at 30 fps even
though readings arrive at about 10 Hz.
"""
from __future__ import annotations

import math

from .protocol import num

RANGE_DEG = 45.0     # tilting 45 degrees reaches the edge (-1 or 1)


class Tilt:
    def __init__(self, smoothing: float = 0.12, energy_decay: float = 0.6):
        self.smoothing = smoothing
        self.energy_decay = energy_decay
        self.reset()

    def reset(self) -> None:
        self.raw = {"alpha": 0.0, "beta": 0.0, "gamma": 0.0}
        self.target = (0.0, 0.0)
        self.x = self.y = 0.0
        self.energy = 0.0
        self.shake = 0.0
        self.flip = False
        self.still_since: float | None = None
        self._now = 0.0
        self._prev: tuple[float, float, float] | None = None   # (t, beta, gamma)
        self._last_t: float | None = None

    def feed(self, d: dict, now: float) -> None:
        if "shake" in d:
            self.shake = max(self.shake, num(d.get("shake")))
        t = d.get("tilt")
        if not isinstance(t, dict):
            return
        b = num(t.get("beta"), 0.0, -180, 180)
        g = num(t.get("gamma"), 0.0, -180, 180)
        self.raw = {"alpha": num(t.get("alpha"), 0.0, -360, 360), "beta": b, "gamma": g}
        self.target = (max(-1.0, min(1.0, g / RANGE_DEG)), max(-1.0, min(1.0, b / RANGE_DEG)))
        self.flip = abs(b) > 150          # upside down: the Baselitz flip
        if self._prev is not None:
            dt = max(0.02, now - self._prev[0])
            speed = math.hypot(b - self._prev[1], g - self._prev[2]) / dt     # degrees per second
            self.energy = max(self.energy, min(1.0, speed / 90.0))
        self._prev = (now, b, g)

    def tick(self, now: float) -> None:
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        a = 1.0 if self.smoothing <= 0 else min(1.0, dt / self.smoothing)
        self.x += (self.target[0] - self.x) * a
        self.y += (self.target[1] - self.y) * a
        k = math.exp(-dt / self.energy_decay) if self.energy_decay > 0 else 0.0
        self.energy *= k
        self.shake *= k
        self._now = now
        if self._prev is None or self.energy > 0.08 or self.shake > 0.1:
            self.still_since = None
        elif self.still_since is None:
            self.still_since = now

    def steer(self) -> dict:
        """The contract's state.steer: what visuals and audio follow."""
        still = 0.0 if self.still_since is None else self._now - self.still_since
        return {"x": round(self.x, 3), "y": round(self.y, 3), "flip": self.flip,
                "shake": round(max(self.shake, self.energy if self.energy > 0.7 else 0.0), 3),
                "still_s": round(still, 1)}

    def state(self) -> dict:
        return {**{k: round(v, 1) for k, v in self.raw.items()},
                "x": round(self.x, 3), "y": round(self.y, 3), "energy": round(self.energy, 3)}
