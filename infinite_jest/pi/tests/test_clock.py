"""The N900 has no network time: its timestamps must not drive the profiler's timers."""
import sys
from pathlib import Path

from showengine import config, protocol as P
from showengine.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from infinite_jest.profiler import create  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_phone_clock_days_off_does_not_trigger_instant_reveal():
    clock = Clock()
    eng = Engine(config.load(None, {"mode": "handheld"}), clock=clock, profiler=create({"seed": 1}))
    phone_ts = 2.0e9          # the phone thinks it is 2033
    profiles = 0
    for i in range(40 * 10):  # 40 s at 10 Hz, phone held and tilted
        clock.t += 0.1
        phone_ts += 0.1
        eng.handle(P.make(P.SENSOR, {"kind": "phone", "held": True, "presence": 0.9,
                                     "tilt": {"alpha": 0, "beta": 30 + i % 40, "gamma": 10}}, ts=phone_ts), "phone")
        profiles = eng.stats["profile"]
    assert eng.machine.phase == "hook"
    assert eng.state["profile_source"] == "profiler"
    assert profiles >= 20            # about one a second, not one then a reveal
    assert eng.machine.visit.reveal is None
