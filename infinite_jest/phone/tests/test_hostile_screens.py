"""The N900 screens drawn into a recording fake cairo (pycairo is not needed).

Checks the artist's standing rule (no crowns, no (c) marks on the phone) and
that hostile or stale engine data never breaks a frame.
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))


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


_install_fake_cairo()
import screens  # noqa: E402


def frames(snap, local=None, n=30):
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


def test_no_crowns_or_copyright_marks_on_any_screen(monkeypatch):
    called = []
    monkeypatch.setattr(screens, 'crown', lambda *a, **k: called.append(a))
    snaps = [{'screen': 'consent'}, {'optout': True}, LIVE]
    for hook in ('', 'scrawl', 'inverted', 'flesh', 'mirror', 'void'):
        s = dict(LIVE)
        s['state'] = dict(LIVE['state'], hook=hook)
        snaps.append(s)
    for snap in snaps:
        for cr in frames(snap, n=5):
            for t in cr.texts:
                assert u'\xa9' not in t and '(c)' not in t.lower(), t
    assert not called, 'crown drawn on the phone'


def test_hostile_engine_data_still_draws_text():
    """Junk the engine (or a bug) could put in state must not blank the screen
    (ui.py swallows a drawing exception, which would leave the frame empty)."""
    snap = dict(LIVE)
    snap['state'] = {'palette': 'nope', 'words': [None, 5, u'☃' * 400], 'intensity': None,
                     'tempo': 0, 'hook': None}
    snap['text'] = 'x' * 160
    for cr in frames(snap, n=5):
        assert cr.texts, 'nothing drawn'
