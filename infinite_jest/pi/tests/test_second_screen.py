"""The second screen draws every phase without crashing, and fails soft without a display."""
import pygame

from showengine.second_screen import SecondScreen


def states():
    base = {"intensity": 0.5, "phase_t": 3.2, "visitor_id": "v-1a2b", "confidence": 0.62, "profile_source": "profiler",
            "sensor": {"loudness": 0.4, "motion": 0.3}, "tilt": {"energy": 0.2}}
    yield {**base, "phase": "idle", "visitor_id": "", "ocean": None, "words": ["pick me up"]}
    yield {**base, "phase": "hook", "ocean": {"O": .7, "C": .3, "E": .5, "A": .4, "N": .8}, "words": ["YOU STAYED"],
           "dossier": ["approached fast"], "big_line": "you turn me faster when it gets loud."}
    yield {**base, "phase": "release", "reveal": {"lines": ["a", "b", "c"], "total": 9}}
    yield {**base, "phase": "wipe", "reveal": {"lines": ["a", "b", "c"], "struck": 2, "wipe": ["gone"]}}
    yield {**base, "blackout": True}
    yield {}


def test_draws_every_phase():
    pygame.font.init()
    s = SecondScreen()
    surf = pygame.Surface((1920, 1080))
    status = {"counts": {"visits": 3, "sensor": 100, "frame": 4}, "clients": {"phone": 1}, "fps": 30}
    for st in states():
        s._record(st)
        s._draw(surf, st, status)


def test_fails_soft_without_second_display():
    pygame.display.init()
    pygame.font.init()
    s = SecondScreen(display_index=7)
    s.update({"phase": "idle"}, lambda: {}, now=1.0)
    assert s.failed and s.window is None
    s.update({"phase": "idle"}, lambda: {}, now=2.0)   # stays quiet
