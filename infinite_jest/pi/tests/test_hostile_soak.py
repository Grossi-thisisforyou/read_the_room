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
