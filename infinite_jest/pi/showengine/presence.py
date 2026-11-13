"""Is someone in the room? A small, forgiving detector with hysteresis.

It takes whatever the phone sends (an explicit presence guess, motion, faces from
the camera, loudness, the phone being picked up or covered) and turns it into one
smoothed score. "Present" switches on above `on_threshold` held for `on_hold`
seconds and off below `off_threshold` held for `off_hold` seconds, so a visitor
standing still for a moment doesn't get wiped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import num


@dataclass
class PresenceConfig:
    on_threshold: float = 0.45
    off_threshold: float = 0.2
    on_hold: float = 1.0
    off_hold: float = 8.0
    smoothing: float = 0.6      # seconds; time constant of the score's low-pass
    stale_after: float = 3.0    # no sensor data for this long counts as score 0
    handheld: bool = False      # set from the contract mode; "handheld": picking the phone up starts a visit


@dataclass
class Presence:
    cfg: PresenceConfig = field(default_factory=PresenceConfig)
    score: float = 0.0
    present: bool = False
    _since_cross: float | None = None
    _last_t: float | None = None
    _last_data_t: float | None = None
    _raw: float = 0.0

    def score_of(self, d: dict) -> float:
        s = self.raw_score(d)
        if self.cfg.handheld and "presence" not in d:
            # handheld: the camera and the mic alone only half-count; holding the phone counts
            cam = max(min(1.0, Presence._num_motion(d) * 1.6), 0.9 if num(d.get("faces"), 0, 0, None) >= 1 else 0.0)
            hand = Presence.raw_score({k: d[k] for k in ("held", "shake", "kind", "proximity") if k in d})
            s = max(hand, min(cam, 0.4))
        return s

    @staticmethod
    def _num_motion(d: dict) -> float:
        return num(d.get("motion"))

    @staticmethod
    def raw_score(d: dict) -> float:
        """One reading -> 0..1. An explicit `presence` wins; otherwise mix cues."""
        if "presence" in d:
            return num(d.get("presence"))
        audio = d.get("audio") if isinstance(d.get("audio"), dict) else {}
        prox = d.get("proximity")
        near = prox.get("near") if isinstance(prox, dict) else prox
        kind = d.get("kind")
        cues = [
            num(d.get("motion")) * 1.6,
            0.9 if num(d.get("faces"), 0, 0, None) >= 1 else 0.0,
            max(num(d.get("loudness")), num(audio.get("level"))) * 0.8,
            0.7 if audio.get("voiced") is True else 0.0,
            1.0 if d.get("held") is True else num(d.get("held")),
            1.0 if near is True else num(near),
            num(d.get("shake")),
            1.0 if kind in ("touch", "keys", "choice") else 0.0,
        ]
        return min(1.0, max(cues))

    def feed(self, data: dict, now: float) -> None:
        self._raw = self.score_of(data)
        self._last_data_t = now
        self.tick(now)

    def tick(self, now: float) -> bool | None:
        """Advance the clock. Returns True on arrival, False on departure, else None."""
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        raw = self._raw
        if self._last_data_t is None or now - self._last_data_t > self.cfg.stale_after:
            raw = 0.0
        a = 1.0 if self.cfg.smoothing <= 0 else min(1.0, dt / self.cfg.smoothing)
        # rise fast, fall at the normal rate: arrivals should feel immediate
        if raw > self.score:
            a = min(1.0, a * 3)
        self.score += (raw - self.score) * a

        crossing = (not self.present and self.score >= self.cfg.on_threshold) or (
            self.present and self.score <= self.cfg.off_threshold
        )
        if not crossing:
            self._since_cross = None
            return None
        if self._since_cross is None:
            self._since_cross = now
        hold = self.cfg.off_hold if self.present else self.cfg.on_hold
        if now - self._since_cross >= hold:
            self.present = not self.present
            self._since_cross = None
            return self.present
        return None

    def reset(self) -> None:
        self.score = 0.0
        self._raw = 0.0
        self.present = False
        self._since_cross = None
