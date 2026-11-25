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
    import tempfile
    eng.cfg["duet"] = {"models_dir": "/nonexistent", "guest": "", "mood": "calm", "footage_dirs": [],
                       "speech_to_text": False,
                       "mood_file": os.path.join(tempfile.mkdtemp(), "mood.json"), **cfg}
    eng.machine.cfg.release_time, eng.machine.cfg.wipe_time, eng.machine.cfg.max_visit = 40.0, 8.0, 1e9
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
    assert duet.tv == "face" and duet.progress == 0.0       # pieces first; the face comes later
    from showengine import talk
    assert len(audio.said) >= 2 and audio.said[1] in talk.STRANGER     # no guest file: it says so


def test_the_face_comes_late_and_in_bursts_and_the_visit_never_resets():
    eng, clock, duet, audio = duet_engine()
    seen, bursts = [], []
    for _ in range(20 * 60 // 5):                            # twenty minutes in the room
        run(eng, clock, 5, HERE_DATA)
        seen.append(duet.progress)
        bursts.append(eng.state["duet"]["burst"])
    assert eng.machine.phase == "hook" and duet.tv == "face"          # no reset, still the same visit
    t = [i * 5 + 5 for i in range(len(seen))]
    assert max(p for p, s in zip(seen, t) if s < 115) == 0.0          # nothing before two minutes
    assert max(seen) > 0.97                                           # it does arrive
    first_full = next(i for i, p in enumerate(seen) if p > 0.97)
    assert 200 < t[first_full] < 900
    steps = [b - a for a, b in zip(seen, seen[1:])]
    assert sum(1 for d in steps if abs(d) < 0.005) > len(steps) * 0.5  # mostly still, then a step
    assert max(steps) > 0.06 and max(bursts) > 0.3
    assert min(seen[first_full:]) < 0.85                               # afterwards it flows: loses ground, returns
    assert duet.bursts >= 8 and len(audio.said) >= 8


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


def test_mood_is_thrown_per_boot_and_per_day(tmp_path):
    import random
    from showengine import mood
    f = str(tmp_path / "m" / "mood.json")
    a = mood.throw(f, rng=random.Random(1), now=1000.0, boot="A")
    assert a["name"] in mood.MOODS and 0 <= a["dark"] <= 1 and len(a["tint"]) == 3
    assert mood.throw(f, now=1000.0 + 3600, boot="A")["name"] == a["name"]        # same day, same boot
    assert mood.throw(f, now=1000.0 + 25 * 3600, boot="A")["name"] != a["name"]    # a day later
    b = mood.throw(f, now=1000.0, boot="A")
    assert mood.throw(f, now=1001.0, boot="B")["name"] != b["name"]                # after a restart
    assert mood.throw(f, force="dread")["name"] == "dread"
    names = {mood.throw(str(tmp_path / f"x{i}.json"), rng=random.Random(i))["name"] for i in range(60)}
    assert names == set(mood.MOODS)
    for m in mood.MOODS.values():                                                   # nothing a visitor could trace
        assert "heidegger" not in (m["today"] + m["voice"]).lower()


def test_mood_reaches_the_state_and_the_local_model():
    from showengine.duet import LiveWords
    eng, clock, duet, audio = duet_engine(mood="fear")
    run(eng, clock, 2, HERE_DATA)
    assert eng.state["mood"]["name"] == "fear" and eng.state["mood"]["glitch"] > 0.7
    assert duet.status()["mood"] == "fear"
    text = LiveWords()._prompt(None, duet.mood)[1]["content"]
    assert "afraid" in text


def test_footage_glitches_are_short_and_random(tmp_path):
    from showengine.duet import Glitch
    g = Glitch([], rate=1.0, seed=4)
    frames = [np.full((180, 320, 3), 40 * i, np.uint8) for i in range(1, 5)]
    g.runs = [list(frames) for _ in range(400)]
    t, on, starts = 0.0, 0, []
    was = False
    while t < 600.0:
        act = g.update(t, wake=1.0, tv_on=True)
        if act and not was:
            starts.append(t)
        was = act
        on += act
        if act:
            f = g.frame(t)
            assert f is not None and f.shape == (180, 320, 3) and f.dtype == np.uint8
        else:
            assert g.frame(t) is None
        t += 0.02
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert 20 <= len(starts) <= 200 and on * 0.02 / len(starts) < 0.65          # short
    assert max(gaps) > 3 * min(gaps)                                             # not a rhythm
    quiet = Glitch([], rate=0.0, seed=4)
    n = sum(1 for i in range(30000) if quiet.update(i * 0.02, wake=1.0) and not quiet.active(i * 0.02 - 0.02))
    assert n < len(starts)
    g2 = Glitch([], seed=1)                      # no footage: the dream itself tears
    g2.fire(5.0, dur=0.3)
    assert g2.frame(5.1, fallback=frames[0]) is not None and g2.frame(5.1) is None


def test_glitch_reads_clips_in_the_background(tmp_path):
    import shutil
    import subprocess
    import time as T
    from showengine.duet import Glitch
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25", "-t", "40",
                    str(tmp_path / "clip.mp4")], check=True)
    (tmp_path / "._clip.mp4").write_bytes(b"junk")
    g = Glitch([str(tmp_path)], seed=2)
    g.start()
    for _ in range(200):
        if len(g.runs) >= 2:
            break
        T.sleep(0.05)
    g.stop()
    assert len(g.runs) >= 2 and g.runs[0][0].shape == (180, 320, 3)
    g.fire(1.0, dur=0.5)
    assert g.frame(1.2) is not None


def test_collage_places_shifts_and_stitches_pieces(tmp_path):
    pygame = pytest.importorskip("pygame")
    from showengine.duet import Collage
    rng = np.random.default_rng(0)
    for i in range(3):
        a = rng.integers(0, 255, (300, 200 + 60 * i, 3), dtype=np.uint8)
        pygame.image.save(pygame.surfarray.make_surface(a), str(tmp_path / f"p{i}.png"))
    c = Collage(str(tmp_path), seed=3)
    assert len(c.paths) == 3
    s = pygame.Surface((960, 540))
    t = 0.0
    for _ in range(300):
        c.step(t, (960, 540), 0.0)
        t += 1 / 30
    few = len(c.pieces)
    assert 3 <= few <= 5
    c.burst()
    assert any(abs(o) > 0.1 for o in c.offsets)
    for _ in range(300):
        c.step(t, (960, 540), 0.9)
        t += 1 / 30
    assert len(c.pieces) > few + 3
    u = 540 // 9
    assert all(p["tx"] % u == 0 and p["ty"] % u == 0 for p in c.pieces)          # on the grid, edge to edge
    c.draw(s, t, 1.0, front=False)
    c.draw(s, t, 1.0, front=True)
    assert pygame.surfarray.array3d(s).max() > 60
    before = [(p["tx"], p["ty"]) for p in c.pieces]
    c.burst()
    assert before != [(p["tx"], p["ty"]) for p in c.pieces]
    for _ in range(30 * 80):
        c.step(t, (960, 540), 0.0)
        t += 1 / 30
    assert len(c.pieces) <= 5                                                     # old pieces go
    empty = Collage(None)
    empty.step(0.0, (320, 180), 1.0)
    empty.draw(s, 0.0, 1.0, front=False)


def test_collage_mixes_family_footage_paintings_camera_and_photos(tmp_path):
    pygame = pytest.importorskip("pygame")
    from showengine.duet import Collage, Glitch
    rng = np.random.default_rng(0)
    for d in ("img", "bank"):
        (tmp_path / d).mkdir()
        for i in range(3):
            a = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
            pygame.image.save(pygame.surfarray.make_surface(a), str(tmp_path / d / f"p{i}.png"))
    foot = Glitch([], seed=1)
    cam = {"f": rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)}
    c = Collage(str(tmp_path / "img"), seed=5, paint_dirs=[str(tmp_path / "bank")], footage=foot,
                camera=lambda: cam["f"])
    s = pygame.Surface((960, 540))
    t = 0.0
    for i in range(30 * 240):
        if len(foot.clips) < 4:                                # the helper thread's job
            foot.clips.append([np.full((180, 320, 3), (i + k * 9) % 255, np.uint8) for k in range(32)])
        c.step(t, (960, 540), 0.8)
        c.draw(s, t, 1.0, front=False)
        c.draw(s, t, 1.0, front=True)
        t += 1 / 30
    assert all(c.counts[k] >= 1 for k in ("family", "photo", "paint", "camera")), c.counts
    assert c.counts["family"] == max(c.counts.values())        # the family footage leads
    moving = [p for p in c.pieces if p["clip"]]
    assert moving
    i0 = moving[0]["i"]
    c.draw(s, t + 0.5, 1.0, front=moving[0]["front"])
    assert moving[0]["i"] != i0                                 # it plays inside its piece
    c.drop_camera()
    assert not [p for p in c.pieces if p["kind"] == "camera"]
    cam["f"] = None
    c.step(t, (960, 540), 0.8)


SPEAKS = {"kind": "phone", "motion": 0.6, "audio": {"level": 0.6, "voiced": True}}


def test_it_never_says_the_same_sentence_twice():
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 40 * 60, HERE_DATA, hz=5)                  # forty minutes, no language model
    said = [x for x in audio.said if x]
    assert len(said) > 60
    assert len(set(said)) == len(said)
    run(eng, clock, 60, EMPTY, hz=5)                            # they leave; someone else comes
    run(eng, clock, 5 * 60, HERE_DATA, hz=5)
    again = [x for x in audio.said if x]
    rep = [x for x in set(again) if again.count(x) > 1]
    assert set(rep) <= {"hello.", duet.mood["today"]} | set(duet.lines["reveal"]) | set(duet.lines["address"])


def test_it_asks_listens_and_answers_what_it_heard():
    from showengine import talk
    eng, clock, duet, audio = duet_engine()
    run(eng, clock, 50, HERE_DATA)
    kinds = []
    for speak_s in (0.0, 1.0, 6.0):
        for _ in range(1200):
            run(eng, clock, 0.1, HERE_DATA)
            if duet.asking:
                break
        q = duet.asking["q"]
        assert q.endswith("?") and audio.said[-1] == q
        n = len(audio.said)
        while clock.t < duet.asking["from"] + 0.2:
            run(eng, clock, 0.1, HERE_DATA)
        assert eng.state["duet"]["listening"] == 1
        if speak_s:
            run(eng, clock, speak_s, SPEAKS)
        for _ in range(200):
            if not duet.asking:
                break
            run(eng, clock, 0.1, HERE_DATA)
        assert not duet.asking and eng.state["duet"]["listening"] == 0
        assert len(audio.said) == n + 1                          # one answer, nothing else in between
        kinds.append(audio.said[-1])
    assert kinds[0] in talk.REPLIES["none"] and kinds[1] in talk.REPLIES["short"] and kinds[2] in talk.REPLIES["long"]
    assert duet.turns == 3


def test_the_local_model_writes_statements_questions_and_answers():
    import http.server
    import json as J
    import threading
    import time as T
    from showengine.duet import LiveWords
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            req = J.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(req["messages"][1]["content"])
            text = ("i heard your breath, not the word.\nwho taught you to wait?" if "You asked the visitor" in seen[-1]
                    else "i kept the tape running.\nwhat did you leave at home?\ni am not finished with you.")
            body = J.dumps({"choices": [{"message": {"content": text}}]})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    w = LiveWords(f"http://127.0.0.1:{srv.server_port}/v1/chat/completions", timeout=5)

    def wait():
        for _ in range(100):
            if not w.busy:
                return
            T.sleep(0.05)

    w.ask({"themes": ["hold still"]}, {"voice": "homesick"}, avoid=["stay."], facts=["trained as an electrician"])
    wait()
    assert w.lines == ["i kept the tape running.", "i am not finished with you."]
    assert w.questions == ["what did you leave at home?"]
    assert "electrician" in seen[0] and "homesick" in seen[0] and "stay." in seen[0]
    w.answer("are you here alone?", "long", None, None)
    wait()
    srv.shutdown()
    assert w.lines[0] == "i heard your breath, not the word." and w.questions[0] == "who taught you to wait?"
    assert "spoke for a long time" in seen[1]


def test_the_tide_builds_peaks_ebbs_and_builds_again():
    eng, clock, duet, audio = duet_engine()
    arc = []
    for _ in range(25 * 60 // 5):
        run(eng, clock, 5, HERE_DATA, hz=5)
        arc.append(eng.state["duet"]["arc"])
    peaks = [i for i in range(1, len(arc) - 1) if arc[i] > 0.65 and arc[i] >= arc[i - 1] and arc[i] > arc[i + 1]]
    lows = [i for i in range(1, len(arc) - 1) if arc[i] < 0.15 and arc[i] <= arc[i - 1] and arc[i] < arc[i + 1]]
    assert len(peaks) >= 3 and len(lows) >= 2
    assert max(arc) > 0.7 and min(arc[12:]) < 0.15
    assert 0.2 <= eng.state["intensity"] <= 0.95


def guest_dir(tmp_path, monkeypatch, gid="007"):
    from showengine import duet as D
    g = tmp_path / "guests" / "kim"
    (g / "img").mkdir(parents=True)
    (g / "guest.json").write_text(json_dumps({"guest_id": gid, "name_spoken": "Kim", "delete_after": "2099-01-01",
                                              "address": ["you came back, kim."], "themes": ["leaving"]}))
    (g / "talk.json").write_text(json_dumps({"lines": ["you packed twice."], "questions": ["what did you pack?"],
                                             "facts": ["they moved eleven times"]}))
    monkeypatch.setattr(D, "IJ", str(tmp_path))


def json_dumps(x):
    import json
    return json.dumps(x)


def test_two_forks_vetted_guest_and_stranger(tmp_path, monkeypatch):
    from showengine import talk
    guest_dir(tmp_path, monkeypatch)
    eng, clock, duet, audio = duet_engine(guest="007")
    assert duet.fork == "vetted" and duet.status()["fork"] == "vetted"
    run(eng, clock, 150, HERE_DATA)
    assert audio.said[0] == "hello, kim." and "you came back, kim." in audio.said
    assert not set(audio.said) & set(talk.STRANGER)
    assert "they moved eleven times" in duet._facts()
    # the control page says: the next one is unknown. Not in the middle of this visit.
    eng.handle(P.make(P.CONTROL, {"cmd": "guest", "arg": None}), "control")
    assert duet.fork == "vetted" and duet.status()["next_guest"] == "unknown"
    run(eng, clock, 70, EMPTY)
    assert eng.machine.phase == "idle" and duet.fork == "stranger"
    n = len(audio.said)
    run(eng, clock, 150, HERE_DATA)
    new = audio.said[n:]
    assert new[0] == "hello." and new[1] in talk.STRANGER and "kim" not in " ".join(new).lower()
    assert sum(x.endswith("?") for x in new) >= 2                    # it asks, because it knows nothing
    assert duet.face_dreamer is None and duet.collage.paths == []
    run(eng, clock, 70, EMPTY)
    eng.handle(P.make(P.CONTROL, {"cmd": "guest", "arg": "007"}), "control")
    assert duet.fork == "vetted"                                     # empty room: at once
    eng.handle(P.make(P.CONTROL, {"cmd": "guest", "arg": "nobody-has-this-id"}), "control")
    assert duet.fork == "stranger"


def test_a_stranger_shapes_the_show_by_answering_and_nothing_is_kept():
    eng, clock, duet, audio = duet_engine(mood="calm")
    eng.last_frame = np.random.default_rng(1).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    run(eng, clock, 50, HERE_DATA)
    day = dict(duet.day_mood)
    seen_prompts = []
    duet.words.answer = lambda q, kind, guest, mood, **k: seen_prompts.append((q, kind, k))
    for i in range(4):                                               # four questions, never an answer
        for _ in range(1500):
            run(eng, clock, 0.1, HERE_DATA)
            if duet.asking:
                break
        for _ in range(300):
            if not duet.asking:
                break
            run(eng, clock, 0.1, HERE_DATA)
    assert len(duet.profile) == 4 and all(k == "none" for _, k, _ in duet.profile)
    assert duet.mood["dark"] > day["dark"] + 0.15 and duet.mood["warm"] < day["warm"]
    assert eng.state["mood"]["dark"] == duet.mood["dark"]             # the music gets it
    # now they type an answer on the phone: the words reach the model and come back on the TV
    for _ in range(1500):
        run(eng, clock, 0.1, HERE_DATA)
        if duet.asking:
            break
    q = duet.asking["q"]
    eng.handle(P.make(P.ANSWER, {"text": "my grandmother's kitchen in Kassel"}), "phone")
    run(eng, clock, 0.3, HERE_DATA)
    assert not duet.asking and duet.profile[-1] == (q, "long", "my grandmother's kitchen in Kassel")
    assert seen_prompts[-1][2]["text"] == "my grandmother's kitchen in Kassel"
    assert duet.echo == ["my grandmother's kitchen in kassel"]
    assert any("kitchen" in x for x in duet._learned())
    face = duet._camera_face()
    assert face is not None and face.shape == (128, 128, 3)
    run(eng, clock, 90, EMPTY)                                         # they leave
    assert eng.machine.phase == "idle" and duet.profile == [] and duet.echo == []
    assert duet.mood == duet.day_mood and eng.last_frame is None


def test_the_model_is_told_what_the_stranger_said():
    from showengine.duet import LiveWords
    w = LiveWords()
    seen = []
    w._run = lambda msgs, front: seen.append(msgs[1]["content"])
    import threading
    real = threading.Thread
    w.answer("where is home?", "short", None, None, text="a boat", learned=["asked who sent you? they stayed silent"])
    for _ in range(50):
        if seen:
            break
        __import__("time").sleep(0.02)
    assert "a boat" in seen[0] and "goes deeper" in seen[0] and "stayed silent" in seen[0]
    text = w._prompt(None, None, None, ["asked where is home? they answered \"a boat\""])[1]["content"]
    assert "do not know this visitor" in text and "a boat" in text
    assert "do not know this visitor at all" in w._prompt(None)[1]["content"]


def test_spoken_answers_are_understood_on_the_pi_and_only_kept_for_the_visit():
    import time as T
    from showengine import hear

    class Seg:
        def __init__(self, text, p=0.1):
            self.text, self.no_speech_prob = text, p

    class FakeModel:
        calls = []

        def transcribe(self, audio, **kw):
            FakeModel.calls.append((len(audio), kw))
            return [Seg(" I grew up by the sea."), Seg(" thank you", 0.9)], None

    eng, clock, duet, audio = duet_engine()
    asked = []
    duet.hearing = hear.Hearing({}, model=FakeModel(), fetch_fn=lambda s: asked.append(s) or np.zeros(int(16000 * s), np.float32))
    duet.words.answer = lambda *a, **k: None
    run(eng, clock, 50, HERE_DATA)
    for _ in range(1500):
        run(eng, clock, 0.1, HERE_DATA)
        if duet.asking:
            break
    q = duet.asking["q"]
    while clock.t < duet.asking["from"] + 0.2:
        run(eng, clock, 0.1, HERE_DATA)
    run(eng, clock, 3.0, SPEAKS)
    for _ in range(100):
        run(eng, clock, 0.1, HERE_DATA)
        T.sleep(0.005)
        if not duet.asking:
            break
    assert duet.profile[-1][0] == q and duet.profile[-1][2] == "I grew up by the sea"
    assert duet.echo == ["i grew up by the sea"]
    assert 3.0 < asked[0] < 12.0 and FakeModel.calls[0][1]["beam_size"] == 1
    assert duet.status()["understood"] == 1
    run(eng, clock, 90, EMPTY)
    assert duet.profile == [] and duet.echo == []
    # made-up words on silence are thrown away; without a model it simply does not try
    assert hear.clean("Thank you.") == "" and hear.clean(" [BLANK_AUDIO] ") == "" and hear.clean("my mother") == "my mother"
    assert hear.Hearing({"speech_to_text": False}).listen(3, lambda t: None) is False
    assert hear.fetch(1.0, addr=("127.0.0.1", 9), timeout=0.2) is None
