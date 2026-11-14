"""Long-run regressions found by tools/soak.py (clock skew, phase sequence)."""
import time

import pytest

from showengine import plugins

plugins._ensure_path()     # the repo root, for infinite_jest.profiler

from showengine import protocol as P
from showengine.config import load
from showengine.engine import Engine


def _reading(i):
    return {"kind": "phone", "held": True, "presence": 0.9, "shake": 0.1,
            "tilt": {"alpha": 0, "beta": 20 * (i % 7), "gamma": 5},
            "audio": {"level": 0.3, "voiced": i % 3 == 0}}


@pytest.mark.parametrize("skew", [0.0, 300.0, -3600.0, 86400.0 * 400])
def test_profiling_survives_a_phone_clock_that_is_off(skew, monkeypatch):
    """The N900 and the Pi are offline (no NTP; the Pi has no RTC battery), so
    their clocks disagree. The profiler compared the phone's ts with the Pi's
    time.time(): 5 minutes ahead made it 'reveal' on the 2nd reading and stop
    profiling for the rest of the visit."""
    from infinite_jest import profiler
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: 1.76e9 + clock[0])     # the Pi's wall clock
    prof = profiler.create({"seed": 1})
    eng = Engine(load(None), clock=lambda: clock[0], profiler=prof)
    for i in range(400):
        clock[0] += 0.1
        eng.handle(P.make(P.SENSOR, _reading(i), ts=time.time() + skew), "phone")
    assert eng.machine.phase == "hook"
    assert not prof.revealed
    assert eng.stats["profile"] > 20


def test_forwarded_messages_use_the_pis_receive_time():
    from infinite_jest import profiler
    p = profiler.create({"seed": 1})
    now = time.time()
    p.handle({"type": "visit", "ts": now, "data": {"visitor_id": "v-1", "phase": "approach"}})
    out = []
    for i in range(30):
        out += p.handle({"type": "sensor", "ts": now + 999 + i, "rx_ts": now + i * 0.25,
                         "data": _reading(i)})
    assert not p.revealed
    assert not any(m["type"] == "reveal" for m in out)


def test_status_reports_the_soc_temperature(tmp_path):
    from showengine.hub import cpu_temp
    f = tmp_path / "temp"
    f.write_text("81234\n")
    assert cpu_temp(f) == 81.2
    assert cpu_temp(tmp_path / "missing") is None
    f.write_text("junk")
    assert cpu_temp(f) is None


def test_handheld_chatter_next_to_the_plinth_does_not_start_visits():
    """The N900 agent's own 'presence' mixes in voice (0.7) and camera motion.
    In handheld mode it used to win outright, so a chatty lounge started visit
    after visit with nobody touching the phone."""
    clock = [0.0]
    eng = Engine(load(None), clock=lambda: clock[0])
    assert eng.mode == "handheld"
    lying = {"kind": "phone", "held": False, "presence": 0.7, "shake": 0.0,
             "audio": {"level": 0.4, "voiced": True}, "motion": 0.2, "proximity": {"near": False}}
    for _ in range(3000):                      # 5 minutes of talk around an untouched phone
        clock[0] += 0.1
        eng.handle(P.make(P.SENSOR, dict(lying)), "phone")
    assert eng.stats["visits"] == 0 and eng.machine.phase == "idle"
    for i in range(100):                       # someone picks it up
        clock[0] += 0.1
        eng.handle(P.make(P.SENSOR, _reading(i)), "phone")
    assert eng.stats["visits"] == 1 and eng.machine.phase in ("approach", "profiling")
    for _ in range(400):                       # puts it down, the chatter goes on: the visit still ends
        clock[0] += 0.1
        eng.handle(P.make(P.SENSOR, dict(lying, presence=0.1, audio={"level": 0.05, "voiced": False}, motion=0.0)), "phone")
    assert eng.machine.phase == "idle" and eng.stats["visits"] == 1
