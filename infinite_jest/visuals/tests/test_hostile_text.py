"""Words on the wall: long, accented, non-Latin, empty, and symbols that point
at the sources; internal names never reach the wall.

    SDL_VIDEODRIVER=dummy python3 -m unittest infinite_jest.visuals.tests.test_hostile_text -v
"""
import ast
import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from infinite_jest.visuals import engine, scrawl  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = {"FLESH", "SCRAWL", "INVERTED", "MEAT", "CROWN", "BRUISE", "SODIUM", "BACON",
            "BASQUIAT", "BASELITZ", "SAMO", "SKULL"}


def setUpModule():
    pygame.display.init()


def _ink(surf):
    return pygame.mask.from_surface(surf).count()


def _blank():
    return pygame.Surface((400, 100), pygame.SRCALPHA)


class HostileText(unittest.TestCase):
    def test_copyright_mark_is_not_drawn(self):
        s = _blank()
        scrawl.draw_text(s, u"©", 10, 10, 40, (255, 255, 255, 255), random.Random(1))
        self.assertEqual(_ink(s), 0)
        self.assertFalse(hasattr(scrawl, "draw_copyright"))

    def test_non_latin_leaves_no_boxes_and_accents_fold(self):
        s = _blank()
        scrawl.draw_text(s, u"你在看 \U0001F451", 10, 10, 40, (255, 255, 255, 255), random.Random(1))
        self.assertEqual(_ink(s), 0)
        a, b = _blank(), _blank()
        scrawl.draw_text(a, u"CAFÉ", 10, 10, 40, (255, 255, 255, 255), random.Random(2), jitter=0)
        scrawl.draw_text(b, u"CAFE", 10, 10, 40, (255, 255, 255, 255), random.Random(2), jitter=0)
        self.assertEqual(_ink(a), _ink(b))
        self.assertGreater(_ink(a), 0)

    def test_long_words_are_shrunk_to_fit(self):
        word = "X" * 80
        size = scrawl.fit_size(word, 60, 1900)
        self.assertLessEqual(scrawl.text_width(word, size), 1900 + 1e-6)
        self.assertEqual(scrawl.fit_size("STAY", 60, 1900), 60)
        self.assertEqual(scrawl.fit_size("", 60, 1900), 60)

    def test_renderer_survives_hostile_word_lists(self):
        v = engine.Visuals((480, 270), {"internal_size": (160, 90), "busy_file": "", "bank_dir": "/nonexistent"})
        screen = pygame.Surface((480, 270))
        lists = [[], [""], ["W" * 80] * 3, [u"你在看"], [u"éèê"], ["   "]]
        for hook in engine.HOOKS:
            for words in lists:
                for phase in ("profiling", "hook", "release"):
                    v.on_state({"phase": phase, "phase_t": 3.0, "hook": hook, "scene": hook,
                                "intensity": 0.9, "words": words,
                                "reveal": {"lines": words, "header": words[0] if words else ""},
                                "ocean": {"O": 0.9, "C": 0.9, "E": 0.9, "A": 0.2, "N": 0.9}})
                    for _ in range(3):
                        v.render(screen, 0.5)

    def test_internal_names_not_in_word_lists(self):
        for lex in (engine.LEX_TENDER, engine.LEX_COLD, engine.LEX_JEST, engine.LEX_IDLE, engine.LEX_DATA):
            for w in lex:
                self.assertFalse(INTERNAL & set(w.split()), w)
        self.assertIn("INVENTORY", engine.LEX_COLD)
        self.assertIn("RAW MATERIAL", engine.LEX_COLD)

    def test_meat_is_in_no_built_in_wall_text(self):
        """Every upper-case string literal (the wall text: word lists, overlay
        labels, data lines) is free of MEAT. The corpus blocklist that keeps it
        off the wall is the one place that must name it. (Lower-case literals
        are identifiers, e.g. the palette id the image library tags with.)"""
        for fn in sorted(os.listdir(HERE)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(HERE, fn), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            block = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "BLOCK" for t in node.targets):
                    block |= {id(n) for n in ast.walk(node.value)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in block
                        and node.value == node.value.upper()):
                    self.assertNotIn("MEAT", node.value, (fn, node.value))

    def test_internal_names_sent_as_words_never_reach_the_wall(self):
        v = engine.Visuals((480, 270), {"internal_size": (160, 90), "busy_file": "", "bank_dir": "/nonexistent"})
        v.on_state({"phase": "hook", "phase_t": 3.0, "hook": "flesh", "intensity": 0.9,
                    "words": ["MEAT", "FRESH MEAT", "STAY", "SKULL CROWN"]})
        v.render(pygame.Surface((480, 270)), 1 / 30)
        ws = v._words()
        self.assertIn("STAY", ws)
        for w in ws:
            self.assertFalse(INTERNAL & set(w.upper().split()), w)


if __name__ == "__main__":
    unittest.main()
