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


# ---- rendered into a recording fake cairo (no pycairo needed) ----
import types  # noqa: E402


class _Grad(object):
    def __init__(self, *a):
        pass

    def add_color_stop_rgba(self, *a):
        pass


class Ctx(object):
    def __init__(self):
        self.texts = []
        self.size = 10.0

    def set_font_size(self, s):
        self.size = s

    def text_extents(self, s):
        w = len(s) * self.size * 0.5
        return (0, 0, w, self.size, w, 0)

    def show_text(self, s):
        self.texts.append(s)

    def __getattr__(self, name):
        return lambda *a, **k: None


def _install_fake_cairo():
    if 'cairo' in sys.modules and not getattr(sys.modules['cairo'], 'FAKE', False):
        return
    m = types.ModuleType('cairo')
    m.FAKE = True
    for n in ('FONT_SLANT_NORMAL', 'FONT_WEIGHT_BOLD', 'FONT_WEIGHT_NORMAL',
              'LINE_CAP_ROUND', 'LINE_JOIN_ROUND'):
        setattr(m, n, 0)
    m.LinearGradient = _Grad
    m.RadialGradient = _Grad
    sys.modules['cairo'] = m




def frames(snap, local=None, n=30):
    _install_fake_cairo()
    import screens
    out = []
    for i in range(n):
        cr = Ctx()
        screens.draw(cr, 800, 480, snap, local or {}, 1000.0 + i * 0.37)
        out.append(cr)
    return out


LIVE = {'screen': 'live', 'link': 'ws', 'text': 'you came back', 'text_t': 990.0,
        'state': {'hook': '', 'words': ['seen', 'watched', 'kept'], 'intensity': 0.7,
                  'palette': {'colors': ['#c0503f']}},
        'reading': {'tilt': {'beta': 10, 'gamma': -4}, 'held': True, 'presence': 0.9}}


def test_no_copyright_marks_in_any_rendered_frame():
    snaps = [{'screen': 'consent'}, {'optout': True}, LIVE]
    for hook in ('', 'scrawl', 'inverted', 'flesh', 'mirror', 'void'):
        s = dict(LIVE)
        s['state'] = dict(LIVE['state'], hook=hook)
        snaps.append(s)
    for snap in snaps:
        for cr in frames(snap, n=5):
            for t in cr.texts:
                assert u'\xa9' not in t and '(c)' not in t.lower(), t


def test_hostile_engine_data_still_draws_text():
    """Junk the engine (or a bug) could put in state must not blank the screen
    (ui.py swallows a drawing exception, which would leave the frame empty)."""
    snap = dict(LIVE)
    snap['state'] = {'palette': 'nope', 'words': [None, 5, u'☃' * 400], 'intensity': None,
                     'tempo': 0, 'hook': None}
    snap['text'] = 'x' * 160
    for cr in frames(snap, n=5):
        assert cr.texts, 'nothing drawn'
