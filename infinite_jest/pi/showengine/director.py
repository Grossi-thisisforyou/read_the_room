"""Turns the visit (phase, profile, hook) and the live sensors into one "state".

The state is what the visuals and the sound follow: scene, intensity, palette,
tempo. Each phase has a shape over time (a ramp in, a decay out) and the hook
phase is tuned to the visitor's OCEAN scores. Edit PALETTES / SCENES here to
change the look without touching anything else.
"""
from __future__ import annotations

from typing import Any

from .protocol import num
from .visit import VisitMachine

# The contract's named palettes (docs/CONTRACT.md), plus which one each scene uses.
PALETTES: dict[str, list[str]] = {
    "meat":   ["#0b0b0b", "#3a0d0d", "#8c1c1c", "#d9826b", "#efe6dc"],   # Bacon
    "bruise": ["#050507", "#1d1630", "#4b2c5e", "#8a6a9c", "#d8d0c0"],   # Baselitz
    "crown":  ["#0a0a0a", "#1a1a1a", "#e8c547", "#c0392b", "#f2f2f2"],   # Basquiat
    "ash":    ["#000000", "#151515", "#3d3d3d", "#8a8a8a", "#e0e0e0"],
    "sodium": ["#050300", "#2b1600", "#a35200", "#ff8c1a", "#fff1d6"],
}

SCENE_PALETTE = {
    "void": "ash", "surveil": "sodium", "dossier": "ash",
    "flesh": "meat", "scrawl": "crown", "inverted": "bruise", "mirror": "sodium",
    "afterimage": "bruise", "erase": "ash",
}

PHASE_SCENE = {
    "idle": "void",
    "approach": "surveil",
    "profiling": "dossier",
    "release": "afterimage",
    "wipe": "erase",
}

# (tempo bpm, intensity at start of phase, intensity it ramps to, ramp seconds)
PHASE_SHAPE = {
    "idle":      (120.0, 0.05, 0.05, 1.0),
    "approach":  (126.0, 0.12, 0.30, 5.0),
    "profiling": (130.0, 0.30, 0.55, 20.0),
    "hook":      (134.0, 0.55, 0.85, 30.0),
    "release":   (112.0, 0.50, 0.08, 12.0),
    "wipe":      (140.0, 1.00, 0.00, 1.5),
}


def _ramp(a: float, b: float, t: float, dur: float) -> float:
    if dur <= 0:
        return b
    x = min(1.0, max(0.0, t / dur))
    x = x * x * (3 - 2 * x)  # smoothstep
    return a + (b - a) * x


def build_state(m: VisitMachine, now: float, sensor: dict[str, Any] | None = None,
                override_scene: str | None = None, blackout: bool = False,
                tilt: dict[str, Any] | None = None, shake: float = 0.0) -> dict:
    v = m.visit
    t = m.phase_t(now)
    tempo, i0, i1, dur = PHASE_SHAPE[m.phase]
    intensity = _ramp(i0, i1, t, dur)
    scene = PHASE_SCENE.get(m.phase, "void")

    if m.phase == "hook":
        scene = v.hook or "void"
        o = v.ocean or {}
        arousal = (num(o.get("E"), 0.5) + num(o.get("N"), 0.5)) / 2
        tempo = 128.0 + 14.0 * arousal                     # 128..142
        hp = v.hook_params
        if "tempo_bpm" in hp:
            tempo = num(hp.get("tempo_bpm"), tempo, 90, 160)
        target = num(hp.get("intensity"), 0.6 + 0.35 * arousal) if "intensity" in hp else 0.6 + 0.35 * arousal
        intensity = _ramp(i0, target, t, dur)

    s = sensor or {}
    if m.phase in ("approach", "profiling", "hook"):
        # the room pushes back: movement and noise lift the intensity a little
        moved = num((tilt or {}).get("energy"))
        intensity = min(1.0, intensity + 0.15 * num(s.get("motion")) + 0.1 * num(s.get("loudness"))
                         + 0.2 * max(moved, shake))

    if override_scene:
        scene = override_scene
    if blackout:
        intensity = 0.0
        scene = "void"

    palette_name = SCENE_PALETTE.get(scene, "ash")
    # oracle (local Qwen) first, then the profiler's reveal / evidence lines as the fallback
    words = list(v.oracle_words) or list(v.words)
    if m.phase == "release" and not v.oracle_words and v.reveal and v.reveal.get("lines"):
        words = list(v.reveal["lines"])

    return {
        "visitor_id": v.visitor_id or "",
        "phase": m.phase,
        "phase_t": round(t, 2),
        "scene": scene,
        "intensity": round(intensity, 3),
        "palette": {"name": palette_name, "colors": PALETTES[palette_name]},
        "tempo": round(tempo, 1),
        "hook": v.hook,
        "ocean": dict(v.ocean) if v.ocean else None,
        "confidence": round(v.confidence, 3),
        "profile_source": v.profile_source,
        "words": words,
        "reveal": dict(v.reveal) if v.reveal else None,
        "dossier": list(v.dossier),
        "blackout": blackout,
        "tilt": tilt or {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "x": 0.0, "y": 0.0, "energy": 0.0},
        "shake": round(shake, 3),
        "sensor": {k: s[k] for k in ("motion", "loudness", "faces", "light", "touch", "held", "proximity") if k in s},
    }
