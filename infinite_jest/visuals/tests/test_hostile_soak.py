"""Long-run regressions for the visuals (found by pi/tools/soak.py).

Run: python3 -m pytest -q infinite_jest/visuals/tests/test_hostile_soak.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import numpy as np  # noqa: E402
import pygame  # noqa: E402
import pytest  # noqa: E402

from infinite_jest import visuals  # noqa: E402
from infinite_jest.visuals.figure import Figure, flesh_lut, ghost_body  # noqa: E402

PAL = [(10, 10, 10), (60, 13, 13), (140, 28, 28), (217, 130, 107), (239, 230, 220)]


@pytest.fixture(scope="module", autouse=True)
def display():
    pygame.display.init()
    yield pygame.display.set_mode((320, 180))


def _motion(fig, t, n=8):
    lut = flesh_lut(PAL)
    angs = [fig.render(t + k / 30, 10, 0.3, 0.2, lut, 1.0)[2] for k in range(n)]
    return [float(np.abs(b - a).mean()) for a, b in zip(angs, angs[1:])]


def test_smear_keeps_moving_smoothly_after_days_of_uptime():
    fig = Figure(160, 180)
    for i in range(6):
        fig.push(ghost_body(160, 120, i * 0.3))
    base = _motion(fig, 10.0)
    for days in (5, 14):
        late = _motion(fig, days * 86400.0)
        # same speed, no frozen frames, no doubled jumps
        assert min(late) > 0.6 * min(base), (days, late, base)
        assert max(late) < 1.6 * max(base), (days, late, base)


class _Spy(pygame.Surface):
    used = []

    def copy(self):
        _Spy.used.append(self.tag)
        return pygame.Surface.copy(self)


def _bank(tmp_path, n_per_hook):
    for hook in ("flesh", "scrawl", "inverted", "mirror", "void"):
        d = tmp_path / hook
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n_per_hook):
            fn = d / ("2026112%d-%04d_1.png" % (i % 9, i))
            if not fn.exists():
                s = pygame.Surface((32, 32))
                s.fill((i * 7 % 255, 80, 200))
                pygame.image.save(s, str(fn))
    return str(tmp_path)


def _state(phase, phase_t=0.0, vid="v-0001"):
    return {"visitor_id": vid, "phase": phase, "phase_t": phase_t, "hook": "flesh" if phase == "hook" else None,
            "scene": "flesh", "intensity": 0.6, "ocean": {"O": 0.5, "C": 0.5, "E": 0.9, "A": 0.5, "N": 0.5}}


def test_underpainting_does_not_flicker_while_the_room_lights_up(tmp_path):
    v = visuals.create((320, 180), {"bank_dir": _bank(tmp_path, 8), "busy_file": "", "internal_size": (160, 90)})
    for hook, imgs in v.bank.items():
        spies = []
        for i, im in enumerate(imgs):
            sp = _Spy(im.get_size())
            sp.blit(im, (0, 0))
            sp.tag = (hook, i)
            spies.append(sp)
        v.bank[hook] = spies
    screen = pygame.Surface((320, 180))
    v.on_state(_state("idle", vid=""))
    for _ in range(30):
        v.render(screen, 1 / 30)
    rebuilds = []
    orig = v._make_ground
    v._make_ground = lambda hook: rebuilds.append(hook) or orig(hook)
    _Spy.used = []
    for i in range(150):                       # idle -> hook: ground_lum glides 0.55 -> ~1.1
        v.on_state(_state("hook", i / 30))
        v.render(screen, 1 / 30)
    assert len(set(_Spy.used)) == 1, set(_Spy.used)      # one underpainting for this visitor
    assert len(rebuilds) <= 20, len(rebuilds)


def test_bank_reload_on_wipe_reads_only_new_files(tmp_path, monkeypatch):
    path = _bank(tmp_path, 10)
    v = visuals.create((320, 180), {"bank_dir": path, "busy_file": "", "internal_size": (160, 90),
                                    "bank_new_per_reload": 3})
    assert sum(len(x) for x in v.bank.values()) == 50
    _bank(tmp_path, 25)                        # the overnight generator added 75 images
    loads = []
    real = pygame.image.load
    monkeypatch.setattr(pygame.image, "load", lambda *a: loads.append(a[0]) or real(*a))
    v.bank_loaded -= 601
    v.on_wipe()
    assert len(loads) <= 3                     # the picture freezes for 3 images, not 120
    assert sum(len(x) for x in v.bank.values()) >= 50
    for _ in range(40):                        # later wipes pick up the rest, a few at a time
        v.bank_loaded -= 601
        v.on_wipe()
    assert sum(len(x) for x in v.bank.values()) == 5 * 25      # all of them (bank_max_per_hook is 40)
