"""Words on the wall: long, accented, non-Latin, empty, and symbols that point
at the sources. Run headless: SDL_VIDEODRIVER=dummy python3 -m pytest -q tests"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from infinite_jest.visuals import engine, scrawl  # noqa: E402

pygame.display.init()


def _ink(surf):
    return pygame.mask.from_surface(surf).count()


def _blank():
    return pygame.Surface((400, 100), pygame.SRCALPHA)


def test_copyright_mark_is_not_drawn():
    s = _blank()
    scrawl.draw_text(s, u"©", 10, 10, 40, (255, 255, 255, 255), random.Random(1))
    assert _ink(s) == 0
    assert not hasattr(scrawl, "draw_copyright")


def test_non_latin_leaves_no_boxes_and_accents_fold():
    s = _blank()
    scrawl.draw_text(s, u"你在看 \U0001F451", 10, 10, 40, (255, 255, 255, 255), random.Random(1))
    assert _ink(s) == 0
    a, b = _blank(), _blank()
    scrawl.draw_text(a, u"CAFÉ", 10, 10, 40, (255, 255, 255, 255), random.Random(2), jitter=0)
    scrawl.draw_text(b, u"CAFE", 10, 10, 40, (255, 255, 255, 255), random.Random(2), jitter=0)
    assert _ink(a) == _ink(b) > 0


def test_long_words_are_shrunk_to_fit():
    word = "X" * 80
    size = scrawl.fit_size(word, 60, 1900)
    assert scrawl.text_width(word, size) <= 1900 + 1e-6
    assert scrawl.fit_size("STAY", 60, 1900) == 60
    assert scrawl.fit_size("", 60, 1900) == 60


def test_renderer_survives_hostile_word_lists():
    v = engine.create((480, 270), {"internal_size": (160, 90)}) if hasattr(engine, "create") \
        else engine.Visuals((480, 270), {"internal_size": (160, 90)})
    screen = pygame.Surface((480, 270))
    lists = [[], [""], ["W" * 80] * 3, [u"你在看"], [u"éèê"], ["   "]]
    for hook in engine.HOOKS:
        for words in lists:
            for phase in ("profiling", "hook", "release"):
                v.on_state({"phase": phase, "phase_t": 3.0, "hook": hook, "scene": hook,
                            "intensity": 0.9, "words": words,
                            "ocean": {"O": 0.9, "C": 0.9, "E": 0.9, "A": 0.2, "N": 0.9}})
                for _ in range(3):
                    v.render(screen, 0.5)


def test_internal_names_not_in_word_lists():
    internal = {"FLESH", "SCRAWL", "INVERTED", "MEAT", "CROWN", "BRUISE", "SODIUM", "BACON",
                "BASQUIAT", "BASELITZ", "SAMO", "SKULL"}
    for lex in (engine.LEX_TENDER, engine.LEX_COLD, engine.LEX_JEST, engine.LEX_IDLE):
        for w in lex:
            assert not internal & set(w.split()), w
