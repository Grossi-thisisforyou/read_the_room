"""The room's form of the day (Baby, 2026-11-24).

The room does not choose how it feels. At every start, and again after a day, it
finds itself thrown into one mood, at random, and everything it does that day is
coloured by it: how the wall dreams, how the music moves, how quickly the face
comes, how often the old footage breaks in, and what it says.

The mood is kept in a small file so that a restart on the same day and the same
boot keeps it. Nothing about visitors is in that file.
"""
from __future__ import annotations

import json
import os
import random
import time

# dark: share of dark music and dark picture; pace: speed of change; warm: warm/open vs cold/thin;
# glitch: how often the footage and the sound break; tint: colour cast on the wall (r, g, b)
MOODS: dict[str, dict] = {
    "dread": {"dark": 0.9, "pace": 0.35, "warm": 0.15, "glitch": 0.6, "tint": (0.82, 0.9, 1.08),
              "today": "today i am afraid, and not of anything.",
              "voice": "anxious without an object; everything familiar has slipped away"},
    "boredom": {"dark": 0.45, "pace": 0.1, "warm": 0.35, "glitch": 0.15, "tint": (0.92, 0.92, 0.9),
                "today": "today nothing pulls at me. stay anyway.",
                "voice": "deeply bored; time is long and everything is equally indifferent"},
    "calm": {"dark": 0.1, "pace": 0.2, "warm": 0.8, "glitch": 0.05, "tint": (1.04, 0.98, 0.9),
             "today": "today i am quiet. you can be quiet with me.",
             "voice": "calm and settled; letting things be what they are"},
    "wonder": {"dark": 0.2, "pace": 0.5, "warm": 0.75, "glitch": 0.25, "tint": (1.0, 1.0, 1.06),
               "today": "today i am surprised that there is anything at all.",
               "voice": "astonished that anything exists at all, and that this visitor exists"},
    "longing": {"dark": 0.4, "pace": 0.3, "warm": 0.6, "glitch": 0.2, "tint": (1.08, 0.94, 0.86),
                "today": "today i miss someone i have not met.",
                "voice": "homesick and longing for something it never had"},
    "fear": {"dark": 0.75, "pace": 0.8, "warm": 0.2, "glitch": 0.85, "tint": (1.1, 0.84, 0.82),
             "today": "today something is coming. i think it is you.",
             "voice": "afraid of something definite that is approaching; jumpy"},
    "elation": {"dark": 0.15, "pace": 0.85, "warm": 0.9, "glitch": 0.4, "tint": (1.08, 1.02, 0.88),
                "today": "today everything is light. i could carry you.",
                "voice": "lifted, light, almost giddy; everything seems possible"},
}
NEUTRAL = {"dark": 0.5, "pace": 0.5, "warm": 0.5, "glitch": 0.5, "tint": (1.0, 1.0, 1.0), "today": "", "voice": ""}
DAY_S = 24 * 3600.0


def _boot_id() -> str:
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


def throw(path: str | None = None, force: str | None = None, rng: random.Random | None = None,
          now: float | None = None, boot: str | None = None) -> dict:
    """The mood the room finds itself in. A new one is drawn after a reboot or after 24 hours
    (the Pi's clock may be wrong, but it still counts hours), never the same twice in a row."""
    rng = rng or random.Random()
    now = time.time() if now is None else now
    boot = _boot_id() if boot is None else boot
    path = os.path.expanduser(path or "~/.config/infinite-jest/mood.json")
    old: dict = {}
    try:
        with open(path) as f:
            old = json.load(f)
    except (OSError, ValueError):
        pass
    if force in MOODS:
        name, seed, at = force, int(old.get("seed") or rng.randrange(1, 2 ** 31)), now
    elif (old.get("name") in MOODS and old.get("boot") == boot
          and 0 <= now - float(old.get("at") or 0) < DAY_S):
        name, seed, at = old["name"], int(old.get("seed") or 1), float(old["at"])
    else:
        name = rng.choice([m for m in MOODS if m != old.get("name")])
        seed, at = rng.randrange(1, 2 ** 31), now
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"name": name, "seed": seed, "at": at, "boot": boot}, f)
    except OSError:
        pass
    return describe(name, seed, at)


def describe(name: str, seed: int = 1, at: float = 0.0) -> dict:
    m = dict(MOODS.get(name, NEUTRAL))
    m.update(name=name if name in MOODS else "neutral", seed=int(seed), at=float(at))
    return m


def for_state(m: dict) -> dict:
    """The part that travels in the show state (to the music)."""
    return {"name": m["name"], "dark": m["dark"], "pace": m["pace"], "warm": m["warm"],
            "glitch": m["glitch"], "seed": m["seed"]}
