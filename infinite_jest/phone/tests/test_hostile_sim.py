"""Adversarial runs of the N900 agent's logic against the REAL show engine,
both on fake clocks (minutes or days of show time in seconds).

Each test wires agent.reading()/events/local_director() to
showengine.engine.Engine.handle(), and the engine's messages back to
agent.handle(), with fake sysfs files for the phone's sensors.

    cd infinite_jest/phone && python3 -m pytest -q tests/test_hostile_sim.py
"""
import gc
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'pi'))

import agent as agent_mod  # noqa: E402
import compat  # noqa: E402
from agent import Agent, DEFAULTS  # noqa: E402
from sensors import PATHS  # noqa: E402

showengine = pytest.importorskip('showengine.engine')
from showengine import config as eng_config, protocol as P  # noqa: E402

ACC, PROX = PATHS['accel'], PATHS['proximity']
FACE_UP = '0 0 -1000'
FACE_DOWN = '0 0 1000'


class FakeTime(object):
    """Stands in for the `time` module inside agent.py."""

    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Rig(object):
    def __init__(self, monkeypatch, mode='handheld', phone_clock_offset=0.0):
        self.root = tempfile.mkdtemp()
        self.write(ACC, FACE_UP)
        self.write(PROX, 'open')
        self.write(PATHS['lux'], '40')
        self.write(PATHS['battery'], '80')
        self.ft = FakeTime(1763000000.0 + phone_clock_offset)
        monkeypatch.setattr(agent_mod, 'time', self.ft)
        self.wall = [1763000000.0]   # the Pi's clock
        monkeypatch.setattr(P.time, 'time', lambda: self.wall[0])
        conf = dict(DEFAULTS, keep_awake=0)
        self.agent = Agent(conf, fake=True, sysfs_root=self.root)
        self.agent.presence.t = self.ft.t
        self.agent.ui['last_presence_t'] = self.ft.t
        self.eng_t = [1000.0]
        self.to_phone = []
        self.engine = showengine.Engine(eng_config.load(None, {'mode': mode}),
                                        emit=self._emit, clock=lambda: self.eng_t[0])
        self.sent = []          # what the phone sent (type, data)
        self.phases = []

    def _emit(self, m, roles):
        if roles is None or 'phone' in roles:
            self.to_phone.append(m)
        if m['type'] == 'state':
            ph = m['data'].get('phase')
            if not self.phases or self.phases[-1] != ph:
                self.phases.append(ph)

    def write(self, path, value):
        p = self.root + path
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        f = open(p, 'w')
        f.write(value)
        f.close()

    def step(self, dt=0.1):
        self.ft.t += dt
        self.wall[0] += dt
        self.eng_t[0] += dt
        a = self.agent
        t = self.ft.t
        while True:
            try:
                m = a.events.get_nowait()
            except Exception:
                break
            self._to_engine(m)
        r = a.reading(t)
        a.ui_update(reading=r)
        if r.get('presence', 0) > 0.45:
            a.ui_update(last_presence_t=t)
        self._to_engine({'type': 'sensor', 'ts': a.now(), 'data': r})
        a.local_director(t)
        out, self.to_phone = self.to_phone, []
        for m in out:
            a.handle(compat.loads(compat.dumps(m)))

    def _to_engine(self, m):
        self.sent.append((m['type'], m['data'], m['ts']))
        self.engine.handle(P.decode(compat.dumps(m)), 'phone')

    def run(self, seconds, dt=0.1):
        for _ in range(int(seconds / dt)):
            self.step(dt)

    def visits(self):
        return self.engine.stats['visits']


def pick_up(rig):
    """A visitor holds the phone: tilted, a little hand tremor."""
    rig.write(ACC, '120 -500 -850')


def tremor(rig, i):
    rig.write(ACC, '%d %d -850' % (120 + (i % 3) * 25, -500 + (i % 2) * 30))


# ------------------------------------------------------------ face-down ---

def test_phone_left_face_down_does_not_loop_visits(monkeypatch):
    """A visitor puts the phone down screen-first: the plinth covers the
    proximity sensor. Before the fix: opt-out every 3 s, the engine started a
    visit, ended it, wiped, the phone re-opted out... all night."""
    rig = Rig(monkeypatch)
    rig.write(ACC, FACE_DOWN)
    rig.write(PROX, 'closed')
    rig.run(600)
    optouts = [d for (ty, d, ts) in rig.sent if d.get('kind') == 'optout']
    assert rig.visits() == 0, (rig.visits(), rig.phases[:12])
    assert len(optouts) <= 1


def test_lounge_traffic_alone_does_not_start_visits(monkeypatch):
    """Handheld mode: people walking past the front camera and talking in the
    lounge while nobody touches the phone must not start a visit."""
    rig = Rig(monkeypatch)
    rig.agent.camera.motion = 0.5
    rig.agent.mic.voiced = True
    rig.agent.mic.level = 0.5
    rig.run(300)
    assert rig.visits() == 0, rig.phases
    # and in fixed mode the room does count, as the contract says
    rig2 = Rig(monkeypatch, mode='fixed')
    rig2.agent.camera.motion = 0.5
    rig2.run(60)
    assert rig2.visits() >= 1


def test_pickup_still_starts_a_visit(monkeypatch):
    rig = Rig(monkeypatch)
    rig.run(5)
    for i in range(200):
        tremor(rig, i)
        rig.step()
    assert rig.visits() == 1 and rig.engine.machine.phase != 'idle'


# --------------------------------------------------------------- opt-out ---

def test_optout_holds_while_visitor_still_holds_the_phone(monkeypatch):
    """Cover the eye 3 s, keep holding the phone: no reading of this visitor
    may resume (camera, mic, sensors) until they put it down and leave."""
    rig = Rig(monkeypatch)
    for i in range(100):
        tremor(rig, i)
        rig.step()
    assert rig.visits() == 1
    rig.write(PROX, 'closed')
    for i in range(35):
        tremor(rig, i)
        rig.step()
    assert rig.agent.opted_out
    rig.write(PROX, 'open')
    n0 = len(rig.sent)
    for i in range(1200):          # two more minutes in their hands
        tremor(rig, i)
        rig.step()
    after = [d for (ty, d, ts) in rig.sent[n0:] if ty == 'sensor']
    leaked = [d for d in after if d.get('kind') == 'phone' and not d.get('optout')]
    assert not leaked, 'readings resumed while the visitor still held the phone: %r' % leaked[:1]
    assert rig.agent.camera.paused and rig.agent.mic.paused
    # put it down and walk away: after optout_release_s the phone resets
    rig.write(ACC, FACE_UP)
    rig.run(DEFAULTS['optout_release_s'] + 10)   # 'held' fades ~4 s after the last movement, then the release clock runs
    assert not rig.agent.opted_out and not rig.agent.camera.paused
    assert rig.agent.ui_snapshot()['screen'] == 'consent'


def test_optout_on_the_consent_screen_with_engine_down_resets(monkeypatch):
    """Opt-out before tapping in, Pi unreachable: must not stay opted out forever."""
    rig = Rig(monkeypatch)
    rig.agent.handle = lambda m: None   # engine never answers
    rig.run(1)
    rig.write(PROX, 'closed')
    rig.run(5)
    assert rig.agent.opted_out
    rig.write(PROX, 'open')
    rig.run(DEFAULTS['optout_release_s'] + 4)
    assert not rig.agent.opted_out


def test_brief_covers_while_holding_do_not_opt_out(monkeypatch):
    """A thumb passing over the sensor (< 3 s, with gaps) is not an opt-out."""
    rig = Rig(monkeypatch)
    pattern = ['closed'] * 25 + ['open'] * 2     # 2.5 s covered, 0.2 s open, repeat
    for i in range(1200):
        tremor(rig, i)
        rig.write(PROX, pattern[i % len(pattern)])
        rig.step()
    assert not rig.agent.opted_out


# ------------------------------------------------------------------ clock --

def test_wrong_phone_clock_is_corrected_from_engine_state(monkeypatch):
    """N900 clock 3 years behind after a battery pull: once the engine's state
    arrives, outgoing ts is on the Pi's clock (the contract's reference)."""
    rig = Rig(monkeypatch, phone_clock_offset=-3 * 365 * 86400.0)
    rig.run(3)
    ts = [ts for (ty, d, ts) in rig.sent if ty == 'sensor'][-1]
    assert abs(ts - rig.wall[0]) < 1.0, ts - rig.wall[0]


def test_clock_jump_backwards_does_not_freeze_presence(monkeypatch):
    rig = Rig(monkeypatch)
    for i in range(50):
        tremor(rig, i)
        rig.step()
    rig.ft.t -= 5 * 86400        # the phone's clock jumps back 5 days
    rig.write(ACC, FACE_UP)
    rig.run(120)
    assert rig.agent.presence.v <= 1.0
    assert rig.agent.ui_snapshot()['reading'].get('presence', 1) < 0.2


# ------------------------------------------------------------- long run ---

def test_three_days_of_visitors_no_growth_no_stale_screen(monkeypatch):
    """72 h of show time at 1 Hz: a visitor every 10 minutes for 2 minutes,
    some typing prompts, some opting out. Check buffers stay bounded and the
    screen never keeps a previous visitor's text."""
    rig = Rig(monkeypatch)
    a = rig.agent
    sizes = []
    stale = 0
    period = 600
    for k in range(int(72 * 3600 / period)):
        # visitor
        for i in range(120):
            tremor(rig, i)
            if i == 2:
                a.on_consent()
            if i == 30:
                a.handle({'type': 'phone', 'ts': 0, 'data': {'text': 'you came back %d' % k}})
            if k % 7 == 3 and 50 <= i < 55:
                rig.write(PROX, 'closed')
            else:
                rig.write(PROX, 'open')
            if i % 20 == 0:
                a.on_touch(0.4, 0.6, False, 'tap', 80)
            rig.step(1.0)
        rig.write(ACC, FACE_UP)
        rig.write(PROX, 'open')
        rig.run(period - 120, dt=2.0)
        snap = a.ui_snapshot()
        if snap['text'] or snap['screen'] != 'consent' or snap['optout']:
            stale += 1
        if k % 36 == 0:
            gc.collect()
            sizes.append(len(gc.get_objects()))
        del rig.sent[:]
    assert stale == 0
    assert a.events.qsize() == 0
    # live Python objects after day 3 vs after the first 6 hours
    assert sizes[-1] < sizes[1] * 1.05 + 500, sizes
    assert len(compat.dumps(a.ui_snapshot())) < 4000
