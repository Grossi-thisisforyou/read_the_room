"""Phone screens: no source symbols, no internal names, hostile text survives.
Run: cd infinite_jest/phone && python3 -m pytest -q tests/test_hostile_screens.py"""
import ast
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
N900 = os.path.join(HERE, "..", "n900")
sys.path.insert(0, N900)


def _strings(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_no_crowns_or_copyright_marks_drawn():
    src = open(os.path.join(N900, "screens.py"), encoding="utf-8").read()
    assert "crown(" not in src
    for s in _strings(os.path.join(N900, "screens.py")):
        if s.startswith(('"""', "Basquiat", "Bacon", "Baselitz")) or "\n" in s:
            continue  # docstrings and comments are fine
        assert not re.search(u"[©™®]|\\(c\\)", s), s
    html = open(os.path.join(HERE, "..", "index.html"), encoding="utf-8").read()
    assert "crown(" not in html and "&copy;" not in html and u"©" not in html


def test_web_phone_never_prints_hook_or_scene_names():
    html = open(os.path.join(HERE, "..", "index.html"), encoding="utf-8").read()
    assert "textContent=d.hook" not in html
    assert "S.scene||" not in html


def test_screens_survive_hostile_text():
    cairo = pytest.importorskip("cairo")
    import screens
    long = "W" * 500
    for words in ([], None, [""], [long] * 6, [u"你在看"] * 3, [None, 3, 4.5]):
        for hook in ("flesh", "scrawl", "inverted", "mirror", "void", "", "nonsense"):
            snap = {"screen": "live", "link": "ws",
                    "state": {"hook": hook, "words": words, "palette": {"colors": ["zz", "#fff"]}},
                    "reading": {}, "text": long, "text_t": 0,
                    "prompt": {"ask": long, "options": [long, u"留"]} if hook == "void" else None}
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 800, 480)
            screens.draw(cairo.Context(surf), 800, 480, snap, {"typing": True, "buffer": long}, 1000.0)
