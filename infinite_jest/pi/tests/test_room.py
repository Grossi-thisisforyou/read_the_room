"""The room's background is ignored, and the room answers a voice."""
from showengine import protocol as P
from showengine.room import Ambient, Floor, Listen

from test_core import make_engine, run


class FakeAudio:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


HUM = {"kind": "phone", "loudness": 0.12, "audio": {"level": 0.12, "voiced": False},
       "tilt": {"alpha": 0.0, "beta": 2.0, "gamma": -3.0}}


def test_floor_learns_the_hum_and_passes_what_stands_out():
    f = Floor()
    out = [f.feed(0.12, t * 0.1) for t in range(6000)]       # ten minutes of hum
    assert out[-1] == 0.0
    assert f.feed(0.6, 600.1) > 0.4                           # a voice over the hum


def test_floor_holds_still_during_a_visit():
    f = Floor()
    for t in range(3000):
        f.feed(0.02, t * 0.1)
    for t in range(3000, 6000):
        g = f.feed(0.5, t * 0.1, frozen=True)
    assert g > 0.4                                            # a visitor never becomes background


def test_voiced_needs_sound_above_the_floor():
    a = Ambient()
    for t in range(3000):
        c = a.sensor({"audio": {"level": 0.2, "voiced": True}}, t * 0.1, frozen=False)
    assert c["audio"] == {"level": 0.0, "voiced": False}


def test_a_humming_flickering_empty_room_gets_no_reactions():
    eng, clock, sent = make_engine()
    run(eng, clock, 600, HUM)
    eng.handle(P.make(P.FRAME, {}), "phone")
    run(eng, clock, 60, HUM)
    assert eng.machine.phase == "idle"
    assert eng.state["sensor"].get("loudness", 0) == 0.0
    assert eng.state["steer"]["shake"] == 0.0
    assert "tilt" not in eng.sensor                           # camera flicker doesn't steer


def test_listen_answers_once_then_waits():
    li = Listen()
    assert li.feed({"level": 0.3, "voiced": True}, 0.0, True)
    assert not li.feed({"level": 0.0, "voiced": False}, 1.0, True)
    assert not li.feed({"level": 0.3, "voiced": True}, 2.0, True)     # cooldown
    assert not li.feed({"level": 0.0, "voiced": False}, 9.0, True)
    assert li.feed({"level": 0.3, "voiced": True}, 10.0, True)
    assert not li.feed({"level": 0.0}, 30.0, False)
    assert not li.feed({"level": 0.3, "voiced": True}, 31.0, False)   # no visit, no answer


def test_the_room_answers_a_voice_in_picture_sound_and_words():
    audio = FakeAudio()
    eng, clock, _ = make_engine(audio=audio)
    busy = {"kind": "phone", "motion": 0.7, "audio": {"level": 0.0, "voiced": False}}
    run(eng, clock, 5, busy)
    assert eng.machine.phase in ("approach", "profiling")
    run(eng, clock, 0.1, {**busy, "audio": {"level": 0.5, "voiced": True}})
    assert eng.state["heard"] > 0.8
    assert eng.state["steer"]["shake"] >= 0.6                 # visuals glitch, music stutters
    assert len(audio.said) == 1 and audio.said[0] == eng.voice.wall[-1]
    run(eng, clock, 4, busy)
    assert eng.state["heard"] < 0.1


def test_a_silent_visitor_is_asked_once():
    audio = FakeAudio()
    eng, clock, _ = make_engine(audio=audio)
    busy = {"kind": "phone", "motion": 0.7, "audio": {"level": 0.0, "voiced": False}}
    run(eng, clock, 90, busy)
    assert eng.machine.phase == "hook"
    assert len(audio.said) == 1


def test_opted_out_visitors_get_no_answers():
    audio = FakeAudio()
    eng, clock, _ = make_engine(audio=audio)
    busy = {"kind": "phone", "motion": 0.7, "audio": {"level": 0.0, "voiced": False}}
    run(eng, clock, 5, busy)
    eng.handle(P.make(P.SENSOR, {"kind": "optout"}), "phone")
    run(eng, clock, 0.1, {**busy, "audio": {"level": 0.5, "voiced": True}})
    assert audio.said == [] and eng.state.get("heard", 0) == 0
