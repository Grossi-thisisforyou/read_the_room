"""The room's background, and the room answering a voice.

Ambient: a camera always sees a little flicker and a mic always hears a little hum
(and, in the room, the show's own speaker). Each reading has a floor that follows
quiet quickly and loud slowly, frozen while a visit is on, so a visitor standing
there doesn't become the background (the camera's floor; the mic's keeps learning,
because the show's own speaker is part of what it hears). Only what is above the floor reaches the
show, so an empty, quiet room gets no reactions (Baby, 2026-11-19: "if nothing
comes in there is no reactions to nothing").

Listen: the room answers a voice. It only ever sees a level and a voiced flag
(contract privacy rule 3: never recorded; words are only made out by hear.py, for the seconds after the room asks a question). When someone starts
to speak or makes a sound during a visit it gives one pulse: the picture jolts,
the sound stutters, one whispered line goes on the wall. Then it waits a while
before it answers again, so it stays an answer and not a meter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Floor:
    margin: float = 0.03        # this much above the floor still counts as nothing
    down_s: float = 3.0         # the floor drops to a quieter room in a few seconds
    up_s: float = 120.0         # and rises to a louder one over minutes (fans, traffic, the speaker)
    cap: float = 0.35           # the background is never louder than this: above it is always someone
    value: float | None = None
    _t: float | None = None

    def feed(self, v: float, now: float, frozen: bool = False) -> float:
        """One reading -> the part of it above the background, 0..1."""
        dt = 0.0 if self._t is None else max(0.0, min(5.0, now - self._t))
        self._t = now
        if self.value is None:
            self.value = 0.0          # assume a quiet room at start; a visitor there at boot stays a visitor
        if v < self.value:
            self.value += (v - self.value) * (1.0 - math.exp(-dt / self.down_s))
        elif not frozen:
            self.value += (min(v, self.cap) - self.value) * (1.0 - math.exp(-dt / self.up_s))
        top = max(0.05, 1.0 - self.value - self.margin)
        return round(min(1.0, max(0.0, v - self.value - self.margin) / top), 3)


class Ambient:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.motion = Floor(margin=float(cfg.get("motion_margin", 0.03)))
        self.sound = Floor(margin=float(cfg.get("sound_margin", 0.03)))
        self.voice_min = float(cfg.get("voice_min", 0.02))    # "voiced" needs this much sound above the floor
        self.moved_t = -1e9                                   # last time the camera saw real movement

    def sensor(self, clean: dict, now: float, frozen: bool) -> dict:
        """The contract fields with the background taken out (in place, and returned)."""
        if "motion" in clean:
            clean["motion"] = self.camera(clean["motion"], now, frozen)
        lvl = None
        if "audio" in clean:
            lvl = clean["audio"]["level"]
        elif "loudness" in clean:
            lvl = clean["loudness"]
        if lvl is not None:
            # never frozen: the show's own speaker gets louder during a visit and must fade
            # into the background too; a voice is short and stands out of a slow floor
            g = self.sound.feed(lvl, now)
            if "loudness" in clean:
                clean["loudness"] = g
            if "audio" in clean:
                clean["audio"] = {"level": g, "voiced": clean["audio"]["voiced"] and g >= self.voice_min}
        return clean

    def camera(self, motion: float, now: float, frozen: bool) -> float:
        g = self.motion.feed(motion, now, frozen)
        if g > 0.0:
            self.moved_t = now
        return g

    def moving(self, now: float, within: float = 1.0) -> bool:
        return now - self.moved_t <= within


class Listen:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.cooldown_s = float(cfg.get("listen_cooldown_s", 8.0))
        self.onset = float(cfg.get("listen_onset", 0.12))     # a sound this far above the floor counts
        self.decay_s = 1.2
        self.reset()

    onset_t = -1e9
    voice_t = -1e9

    def reset(self) -> None:
        self.pulse = 0.0
        self.heard_t = -1e9
        self.heard_n = 0          # this visit: how many times it answered
        self.quiet_since: float | None = None
        self._voiced = False
        self._loud = False
        self._t: float | None = None

    def feed(self, audio: dict | None, now: float, active: bool) -> bool:
        """One mic reading. True when the room should answer now."""
        if not isinstance(audio, dict):
            return False
        voiced = bool(audio.get("voiced"))
        lvl = float(audio.get("level") or 0.0)
        loud = lvl >= self.onset if not self._loud else lvl >= self.onset * 0.5
        was_voiced = self._voiced
        start = (voiced and not self._voiced) or (loud and not self._loud)
        self._voiced, self._loud = voiced, loud
        if start:
            self.onset_t = now               # every new sound, visit or not
        if voiced and not was_voiced:
            self.voice_t = now               # a voice begins (the duet listens for a hello)
        if voiced or loud:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = now
        if not active or not start or now - self.heard_t < self.cooldown_s:
            return False
        self.heard_t = now
        self.heard_n += 1
        self.pulse = 1.0
        return True

    def tick(self, now: float) -> float:
        dt = 0.0 if self._t is None else max(0.0, now - self._t)
        self._t = now
        self.pulse *= math.exp(-dt / self.decay_s)
        if self.pulse < 0.01:
            self.pulse = 0.0
        return self.pulse

    def quiet_for(self, now: float) -> float:
        return 0.0 if self.quiet_since is None else now - self.quiet_since
