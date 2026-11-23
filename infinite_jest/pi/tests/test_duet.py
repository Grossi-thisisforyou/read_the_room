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
    from showengine import plugins
    real = plugins.report

    def loud(logger, key, text, *a, **k):        # a failing hook must fail the test, not hide
        if key == "state-hook":
            raise
        return real(logger, key, text, *a, **k)
    plugins.report = loud
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


def test_demo_button_pretends_a_visitor():
    eng, clock, duet, audio = duet_engine()
    eng.handle(P.make(P.CONTROL, {"cmd": "demo"}), "control")
    run(eng, clock, 60)
    assert eng.machine.phase in ("profiling", "hook") and duet.tv in ("hello", "face")
    eng.handle(P.make(P.CONTROL, {"cmd": "demo"}), "control")
    run(eng, clock, 80)
    assert eng.machine.phase in ("release", "wipe", "idle")


def test_live_words_from_a_local_model(monkeypatch):
    import http.server
    import json as J
    import threading
    import time as T
    from showengine.duet import LiveWords, clean_lines

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = J.dumps({"choices": [{"message": {"content":
                    "1. You hold still for me.\n- \"i see the second face\"\nThis line is far too long to ever be shown on the wall of the room ok\n"}}]})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    w = LiveWords(f"http://127.0.0.1:{srv.server_port}/v1/chat/completions", timeout=5)
    w.ask({"themes": ["hold still"], "words": ["SHOWS NOTHING"]})
    for _ in range(100):
        if not w.busy:
            break
        T.sleep(0.05)
    srv.shutdown()
    assert w.lines == ["you hold still for me.", "i see the second face"]
    assert clean_lines("") == []


def test_material_shows_the_newest_painting_and_footage(tmp_path):
    import shutil
    import subprocess
    import time as T
    pygame = pytest.importorskip("pygame")
    from showengine.duet import Material
    paint = tmp_path / "bank" / "void"
    paint.mkdir(parents=True)
    surf = pygame.Surface((64, 64))
    surf.fill((200, 10, 10))
    pygame.image.save(surf, str(paint / "a.png"))
    m = Material([str(tmp_path / "bank")], [str(tmp_path / "none")], every_s=1)
    m.update(0.0)
    for _ in range(100):
        if m.kind:
            break
        T.sleep(0.02)
    assert m.kind == "paint" and m.img.shape == (64, 64, 3)
    if shutil.which("ffmpeg"):
        vid = tmp_path / "foot"
        vid.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "30",
                        str(vid / "clip.mp4")], check=True)
        m2 = Material([str(tmp_path / "nopaint")], [str(tmp_path)], every_s=1)
        m2.update(0.0)
        for _ in range(200):
            if m2.kind:
                break
            T.sleep(0.05)
        assert m2.kind == "footage" and m2.img.shape == (180, 320, 3)
