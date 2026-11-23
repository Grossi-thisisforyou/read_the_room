"""The two-screen show: TV black until ~45 s of company, then hello, the face, the reveal."""
import os

import numpy as np
import pytest

from showengine import protocol as P
from showengine.duet import Duet, Dreamer, FaceModel, GrowingFace, load_guest

from test_core import make_engine, run

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


class FakeDec:
    latent = 4
    z_mean = np.zeros(4, np.float32)
    z_std = np.ones(4, np.float32)

    def __call__(self, z):
        return np.full((6, 10, 3), int(abs(float(z[0])) * 40) % 255, np.uint8)


class SayLog:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def duet_engine(**cfg):
    audio = SayLog()
    eng, clock, sent = make_engine(audio=audio)
    eng.cfg["duet"] = {"models_dir": "/nonexistent", "guest": "", **cfg}
    eng.machine.cfg.release_time, eng.machine.cfg.wipe_time, eng.machine.cfg.max_visit = 40.0, 8.0, 300.0
    duet = Duet(eng.cfg, eng)
    duet.wall = Dreamer(FakeDec(), 8.0, seed=1)
    eng.state_hooks.append(duet.update)
    return eng, clock, duet, audio


HERE_DATA = {"kind": "phone", "motion": 0.6, "audio": {"level": 0.0, "voiced": False}}
EMPTY = {"kind": "phone", "motion": 0.0, "audio": {"level": 0.0, "voiced": False}}


def test_tv_stays_black_in_an_empty_room():
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 120, EMPTY)
    assert duet.tv == "black" and duet.tv_level < 0.01 and audio.said == []
    assert eng.state["words"] == []


def test_tv_wakes_after_45_seconds_and_says_hello():
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 30, HERE_DATA)
    assert duet.tv == "black" and duet.wake > 0.5            # the wall reacted already
    run(eng, clock, 20, HERE_DATA)
    assert duet.tv in ("hello", "face") and audio.said[0] == "hello."
    run(eng, clock, 60, HERE_DATA)
    assert duet.tv == "face" and 0.2 < duet.progress < 1.0
    assert len(audio.said) >= 2


def test_leaving_ends_with_the_reveal_then_black():
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 90, HERE_DATA)
    run(eng, clock, 15, EMPTY)
    assert duet.tv == "reveal"
    run(eng, clock, 40, EMPTY)
    assert any("deleted" in s for s in audio.said)
    run(eng, clock, 30, EMPTY)
    assert duet.tv == "black" and eng.machine.phase == "idle"


def test_a_voice_jolts_the_wall():
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 10, HERE_DATA)
    v0 = float(np.abs(duet.wall.walk.v).sum())
    run(eng, clock, 0.1, {**HERE_DATA, "audio": {"level": 0.6, "voiced": True}})
    assert float(np.abs(duet.wall.walk.v).sum()) > v0
    assert audio.said == []                                  # it does not speak before the TV is on


def test_drawing_does_not_crash_without_networks():
    pygame = pytest.importorskip("pygame")
    pygame.display.init()
    pygame.font.init()
    eng, clock, duet, audio = duet_engine()
    duet.wall.push(duet.wall.make(0.1), clock.t)
    s = pygame.Surface((320, 180))
    for secs in (5, 50, 60):
        run(eng, clock, secs, HERE_DATA)
        duet.draw_tv(s, clock.t)
        duet.draw_tv(s, clock.t, wall_here=True)
        duet.draw_wall(s, clock.t)


def test_guest_file_past_its_date_is_not_used(tmp_path, monkeypatch):
    import datetime
    from showengine import duet as D
    g = tmp_path / "guests" / "x"
    g.mkdir(parents=True)
    (g / "guest.json").write_text('{"guest_id": "009", "delete_after": "2026-12-23", "name_spoken": "Kim"}')
    monkeypatch.setattr(D, "IJ", str(tmp_path))
    assert load_guest("009", datetime.date(2026, 12, 1))["name_spoken"] == "Kim"
    assert load_guest("009", datetime.date(2026, 12, 24)) is None
    assert Duet._lines({"name_spoken": "Kim"})["hello"] == "hello, kim."
