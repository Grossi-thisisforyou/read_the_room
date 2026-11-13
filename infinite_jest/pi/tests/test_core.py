"""The performance logic, run at thousands of times real speed with a fake clock."""
import base64

import numpy as np
import pytest

from showengine import config, protocol as P
from showengine.engine import Engine
from showengine.hub import split_jpegs
from showengine.presence import Presence, PresenceConfig
from showengine.visit import VisitMachine


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_engine(mode="fixed", **kw):
    clock = Clock()
    sent = []
    eng = Engine(config.load(None, {"mode": mode}), emit=lambda m, roles: sent.append((m, roles)), clock=clock, **kw)
    return eng, clock, sent


def run(eng, clock, seconds, data=None, hz=10):
    for _ in range(int(seconds * hz)):
        clock.t += 1 / hz
        if data is None:
            eng.tick()
        else:
            eng.handle(P.make(P.SENSOR, dict(data)), "phone")


BUSY = {"kind": "phone", "motion": 0.7, "audio": {"level": 0.4}}
EMPTY = {"kind": "phone", "motion": 0.0}


def phases(sent):
    return [m["data"]["phase"] for m, _ in sent if m["type"] == P.STATE]


# ---------------------------------------------------------------- protocol
def test_decode_rejects_junk():
    for raw in ["nope", "[]", '{"type": 3}', '{"type":"x","data":[1]}']:
        with pytest.raises(P.BadMessage):
            P.decode(raw)
    m = P.decode('{"type":"sensor","data":{"motion":0.5}}')
    assert m["data"]["motion"] == 0.5 and isinstance(m["ts"], float)


def test_num_clamps_untrusted_values():
    assert P.num(5) == 1.0 and P.num(-1) == 0.0 and P.num("x", 0.3) == 0.3
    assert P.num(float("nan"), 0.2) == 0.2 and P.num(True, 0.1) == 0.1


# ---------------------------------------------------------------- presence
def test_presence_needs_hold_and_survives_short_stillness():
    p = Presence(PresenceConfig(on_hold=1.0, off_hold=8.0))
    t = 0.0
    p.feed({"motion": 0.9}, t)
    assert not p.present
    for _ in range(20):
        t += 0.1
        p.feed({"motion": 0.9}, t)
    assert p.present
    for _ in range(50):          # 5 s of standing still: still there
        t += 0.1
        p.feed({"motion": 0.0}, t)
    assert p.present
    for _ in range(60):
        t += 0.1
        p.feed({"motion": 0.0}, t)
    assert not p.present


def test_presence_goes_stale_without_data():
    p = Presence(PresenceConfig(on_hold=0.2, off_hold=1.0, stale_after=1.0))
    for i in range(20):
        p.feed({"presence": 1.0}, i * 0.1)
    assert p.present
    t = 2.0
    for _ in range(60):
        t += 0.1
        p.tick(t)
    assert not p.present


def test_presence_reads_contract_shapes():
    assert Presence.raw_score({"proximity": {"near": True}}) == 1.0
    assert Presence.raw_score({"held": True}) == 1.0
    assert Presence.raw_score({"kind": "touch", "x": 0.2}) == 1.0
    assert Presence.raw_score({"audio": {"level": 0.0, "voiced": False}}) == 0.0


# ---------------------------------------------------------------- visit
def test_full_visit_cycle_with_fallback_profile():
    eng, clock, sent = make_engine()
    run(eng, clock, 3, EMPTY)
    assert eng.machine.phase == "idle"
    run(eng, clock, 30, BUSY)                      # arrives, stays past the 20 s timeout
    assert eng.machine.phase == "hook"
    st = eng.state
    assert st["hook"] in {"flesh", "scrawl", "inverted", "mirror", "void"}
    assert st["scene"] == st["hook"] and st["profile_source"] == "fallback"
    assert 0 <= st["intensity"] <= 1 and 120 <= st["tempo"] <= 145
    assert st["visitor_id"].startswith("v-")
    run(eng, clock, 20, EMPTY)                    # leaves
    seq = phases(sent)
    order = [p for i, p in enumerate(seq) if i == 0 or seq[i - 1] != p]
    assert order[:6] == ["idle", "approach", "profiling", "hook", "release", "wipe"]
    run(eng, clock, 10, EMPTY)
    assert eng.machine.phase == "idle" and eng.state["visitor_id"] == ""
    wipes = [m for m, _ in sent if m["type"] == P.WIPE]
    assert len(wipes) == 1 and wipes[0]["data"]["visitor_id"].startswith("v-")


def test_profiler_confidence_hooks_early_and_hook_params_apply():
    eng, clock, sent = make_engine()
    run(eng, clock, 5, BUSY)
    assert eng.machine.phase == "profiling"
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "ocean": {"O": .9, "C": .2, "E": .5, "A": .5, "N": .3},
                                  "confidence": 0.8, "hook": "scrawl", "evidence": ["you lingered 4.1 s"],
                                  "hook_params": {"intensity": 0.9, "tempo_bpm": 141}}), "profiler")
    run(eng, clock, 3, BUSY)
    assert eng.machine.phase == "profiling"      # confident, but the 6 s minimum isn't up
    run(eng, clock, 4, BUSY)
    assert eng.machine.phase == "hook" and eng.state["scene"] == "scrawl"
    assert eng.state["palette"]["name"] == "crown" and eng.state["tempo"] == 141
    assert eng.state["words"] == ["you lingered 4.1 s"]


def test_stale_profile_for_another_visitor_is_ignored():
    eng, clock, _ = make_engine()
    run(eng, clock, 5, BUSY)
    eng.handle(P.make(P.PROFILE, {"visitor_id": "v-dead", "confidence": 1, "hook": "flesh"}), "profiler")
    assert eng.machine.visit.hook is None


def test_hook_min_dwell():
    m = VisitMachine()
    m.present = True
    m.tick(0)
    m.force("hook", 0)
    m.on_profile({"hook": "flesh"}, 1)
    m.on_profile({"hook": "void"}, 3)
    assert m.visit.hook == "flesh"
    m.on_profile({"hook": "void"}, 10)
    assert m.visit.hook == "void"


def test_max_visit_releases_a_lingerer():
    eng, clock, _ = make_engine()
    run(eng, clock, 200, BUSY)
    assert eng.stats["visits"] >= 2     # released, wiped, and a fresh visit began


def test_wipe_forgets_everything():
    eng, clock, sent = make_engine()
    run(eng, clock, 25, BUSY)
    eng.handle(P.make(P.SENSOR, {"kind": "keys", "text": "my secret"}), "phone")
    words = eng.machine.visit.answers
    assert words == ["my secret"]
    eng.handle(P.make(P.CONTROL, {"cmd": "wipe"}), "control")
    assert words == []                       # the old list was emptied in place
    assert eng.machine.visit.answers == [] and eng.machine.visit.ocean is None
    assert eng.fallback.n == 0


def test_control_only_from_control_role():
    eng, clock, _ = make_engine()
    eng.handle(P.make(P.CONTROL, {"cmd": "blackout"}), "phone")
    assert not eng.blackout
    eng.handle(P.make(P.CONTROL, {"cmd": "blackout"}), "control")
    assert eng.blackout and eng.state["intensity"] == 0
    run(eng, clock, 5, BUSY)                 # blackout stops sensing
    assert eng.machine.phase == "idle" and eng.stats["sensor"] == 0


def test_phone_lines_and_forwarding():
    eng, clock, sent = make_engine()
    run(eng, clock, 2, BUSY)
    phone = [m for m, r in sent if r == {"phone"} and m["type"] == P.PHONE]
    assert phone and phone[0]["data"]["text"] == "I see you."
    fwd = [m for m, r in sent if r == {"profiler"} and m["type"] == P.SENSOR]
    assert fwd and "rx_ts" in fwd[0]
    visits = [m for m, r in sent if m["type"] == P.VISIT]
    assert visits[0]["data"]["phase"] == "approach"


def test_unknown_types_and_garbage_values_never_crash():
    eng, clock, _ = make_engine()
    eng.handle(P.make("banana", {"x": 1}), "phone")
    eng.handle(P.make(P.SENSOR, {"motion": "lots", "tilt": "up", "audio": 3, "proximity": [1]}), "phone")
    eng.handle(P.make(P.PROFILE, {"ocean": "nope", "confidence": "high", "hook": 7}), "profiler")
    eng.handle(P.make(P.FRAME, {"fmt": "gray8", "w": 99999, "h": -1, "b64": "!!"}), "phone")
    eng.tick()


# ---------------------------------------------------------------- frames
def test_gray8_frames_drive_motion_and_presence():
    eng, clock, _ = make_engine()
    rng = np.random.default_rng(0)
    for i in range(40):
        clock.t += 0.25
        img = rng.integers(0, 255, (120, 160), dtype=np.uint8)   # every frame different: lots of motion
        eng.handle(P.make(P.FRAME, {"w": 160, "h": 120, "fmt": "gray8",
                                    "b64": base64.b64encode(img.tobytes()).decode()}), "phone")
    assert eng.stats["frame"] == 40 and eng.sensor["motion"] > 0.5
    assert eng.machine.phase in ("approach", "profiling")


def test_split_jpegs_handles_chunk_boundaries():
    a, b = b"\xff\xd8AAAA\xff\xd9", b"\xff\xd8BB\xff\xd9"
    stream = b"junk" + a + b + b"\xff\xd8CC"
    buf = bytearray()
    got = []
    for i in range(0, len(stream), 3):
        buf += stream[i:i + 3]
        got += split_jpegs(buf)
    assert got == [a, b] and bytes(buf).startswith(b"\xff\xd8CC")


class FakeProfiler:
    """Shaped like infinite_jest/profiler: returns dicts with a "type" key."""
    def __init__(self):
        self.n, self.visits, self.resets = 0, [], 0

    def on_sensor(self, data, ts):
        self.n += 1
        if self.n > 30:
            return {"type": "profile", "ocean": {"O": .2, "C": .8, "E": .2, "A": .5, "N": .4},
                    "confidence": .7, "hook": "void", "hook_params": {"line": "you stood still for us"}}

    def on_visit(self, visit, ts):
        self.visits.append(visit["phase"])
        if visit.get("reveal"):
            return {"type": "reveal", "lines": ["calm", "watchful"], "label": "the quiet one"}

    def reset(self):
        self.resets += 1
        self.n = 0


def test_in_process_profiler_profile_reveal_and_reset():
    prof = FakeProfiler()
    eng, clock, _ = make_engine(profiler=prof)
    run(eng, clock, 12, BUSY)
    assert eng.machine.phase == "hook" and eng.state["hook"] == "void"
    assert eng.state["profile_source"] == "profiler" and eng.state["words"][0] == "you stood still for us"
    run(eng, clock, 9, EMPTY)
    assert eng.machine.phase == "release" and eng.state["words"] == ["calm", "watchful"]
    run(eng, clock, 8, EMPTY)
    assert prof.resets == 1 and prof.visits[:4] == ["approach", "profiling", "hook", "release"]


def test_opt_out_goes_quiet():
    eng, clock, _ = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "phase": "opted_out", "hook": "void", "wiped": True}), "profiler")
    assert eng.state["scene"] == "void" and eng.state["ocean"] is None
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "confidence": .9, "hook": "flesh"}), "profiler")
    assert eng.state["scene"] == "void"


# ---------------------------------------------------------------- handheld + tilt + oracle
def test_handheld_pickup_starts_and_putdown_ends():
    eng, clock, _ = make_engine(mode="handheld")
    run(eng, clock, 10, {"kind": "phone", "motion": 0.8, "held": False})   # camera alone isn't enough
    assert eng.machine.phase == "idle"
    run(eng, clock, 6, {"kind": "phone", "held": True, "tilt": {"beta": 10, "gamma": -20}})
    assert eng.machine.phase in ("approach", "profiling")
    run(eng, clock, 20, {"kind": "phone", "held": False})                  # put down
    assert eng.machine.phase in ("release", "wipe", "idle")


def test_tilt_steers_and_flips():
    eng, clock, _ = make_engine(mode="handheld")
    run(eng, clock, 2, {"kind": "phone", "held": True, "tilt": {"alpha": 0, "beta": 0, "gamma": 45}})
    st = eng.state["steer"]
    assert st["x"] > 0.9 and abs(st["y"]) < 0.05 and not st["flip"] and eng.state["mode"] == "handheld"
    run(eng, clock, 1, {"kind": "phone", "held": True, "tilt": {"beta": 170, "gamma": 0}})
    assert eng.state["steer"]["flip"] and eng.state["tilt"]["energy"] > 0
    run(eng, clock, 8, {"kind": "phone", "held": True, "tilt": {"beta": 170, "gamma": 0}})
    assert eng.state["steer"]["still_s"] > 3          # holding still is a gesture too


def test_oracle_words_win_and_phone_text_forwarded():
    eng, clock, sent = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "evidence": ["canned line"]}), "profiler")
    assert eng.state["words"] == ["canned line"]
    eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["SUBJECT LINGERS"], "phone_text": "turn me over",
                                 "dossier": ["approached fast"]}), "oracle")
    assert eng.state["words"] == ["SUBJECT LINGERS"] and eng.state["dossier"] == ["approached fast"]
    assert any(m["type"] == P.PHONE and m["data"].get("text") == "turn me over" for m, r in sent if r == {"phone"})
    eng.handle(P.make(P.ORACLE, {"visitor_id": "v-0000", "words": ["someone else"]}), "oracle")
    eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["from a phone"]}), "phone")
    assert eng.state["words"] == ["SUBJECT LINGERS"]
    assert any(r == {"oracle"} and m["type"] == P.PROFILE for m, r in sent)
    eng.handle(P.make(P.CONTROL, {"cmd": "wipe"}), "control")
    assert eng.state["words"] == [] and eng.state["dossier"] == []


def test_visual_sources_never_reach_visitors():
    eng, clock, sent = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["like Bacon", "YOU STAYED", "a crown for you"]}), "oracle")
    assert eng.state["words"] == ["YOU STAYED"]
    hooks = {"flesh", "scrawl", "inverted", "mirror", "void"}
    for m, _ in sent:
        if m["type"] == P.PHONE:
            assert not any(h in str(m["data"]).lower() for h in hooks)
