"""Privacy claims the N900 agent makes (phone/README.md, profiler/DATA_HANDLING.md).

    python3 -m pytest -q tests/test_privacy.py

- the camera and microphone pipelines write only to the agent's own pipe, never a file;
- the microphone gives a level and a voiced flag, and keeps no samples;
- nothing reaches the phone's disk and nothing typed reaches its log;
- covering the proximity sensor for 3 s stops all reading, and a wipe from the Pi
  does not restart reading while the same person still holds the phone.
"""
import builtins
import io
import math
import os
import sys
import tempfile
import time
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))

import capture  # noqa: E402
from agent import Agent, DEFAULTS  # noqa: E402

FLAT = '18 -36 -1008'          # lying on the table
TILTED = '400 -600 -700'       # in a hand, not flat


def sysfs(accel=FLAT, prox='open'):
    root = tempfile.mkdtemp()
    files = {
        '/sys/class/i2c-adapter/i2c-3/3-001d/coord': accel,
        '/sys/class/i2c-adapter/i2c-2/2-0029/lux': '35',
        '/sys/devices/platform/gpio-switch/proximity/state': prox,
        '/sys/devices/platform/gpio-switch/slide/state': 'closed',
        '/sys/class/power_supply/bq27200-0/capacity': '81',
    }
    for p, v in files.items():
        os.makedirs(os.path.dirname(root + p))
        with open(root + p, 'w') as f:
            f.write(v)
    return root


def put(root, path, value):
    with open(root + path, 'w') as f:
        f.write(value)


PROX = '/sys/devices/platform/gpio-switch/proximity/state'
ACCEL = '/sys/class/i2c-adapter/i2c-3/3-001d/coord'


def agent(root, **kw):
    conf = dict(DEFAULTS, keep_awake=0, camera=1, mic=1, **kw)
    a = Agent(conf, fake=True, sysfs_root=root)   # fake sources, not started: no threads
    return a


# ------------------------------------------------------------------ pipelines
def test_pipelines_only_write_to_the_agents_pipe():
    v = {'gst': 'gst-launch-0.10', 'device': '/dev/video1', 'fps': 4, 'w': 160, 'h': 120, 'w2': 320, 'h2': 240}
    cmds = [c % v for _m, c in capture.CAMERA_PIPELINES] + [capture.MIC_PIPELINE % {'gst': 'gst'}]
    for c in cmds:
        assert c.rstrip().endswith('fdsink fd=1 sync=false'), c
        for bad in ('filesink', 'multifilesink', 'location=', '/tmp', 'jpegenc', 'wavenc', 'tee', 'oggmux'):
            assert bad not in c, (bad, c)


def test_mic_keeps_only_a_level_and_a_voiced_flag():
    m = capture.Mic(fake=True)
    tone = array('h', [int(6000 * math.sin(2 * math.pi * 180 * i / 8000.0)) for i in range(400)])
    marker = array('h', [12345] * 400)
    for _ in range(30):
        m._on_chunk(tone.tobytes())
    m._on_chunk(marker.tobytes())
    assert 0.0 <= m.level <= 1.0 and isinstance(m.voiced, bool)
    for k, v in vars(m).items():
        assert not isinstance(v, (bytes, bytearray, array, list, memoryview)), (k, type(v))


def test_reading_carries_audio_as_level_and_voiced_only():
    a = agent(sysfs())
    a.mic.level, a.mic.voiced = 0.4, True
    r = a.reading(time.time())
    assert set(r['audio']) == {'level', 'voiced'}
    for k, v in r.items():
        assert not isinstance(v, (bytes, bytearray, array)), k


def test_camera_keeps_only_the_latest_frame_and_wipe_drops_it():
    c = capture.Camera(fake=True)
    for i in range(5):
        c._on_frame(bytes([i]) * (160 * 120))
    frame, seq = c.latest()
    assert frame == bytes([4]) * (160 * 120) and seq == 5
    c.wipe()
    assert c.latest()[0] is None and c.prev is None


# ------------------------------------------------------------------ disk + log
def test_agent_writes_nothing_and_never_logs_typed_text(monkeypatch, capsys):
    root = sysfs()
    writes = []
    real_open, real_os_open = builtins.open, os.open

    def fake_open(file, mode='r', *x, **kw):
        if any(ch in str(mode) for ch in 'wax+'):
            writes.append(file)
        return real_open(file, mode, *x, **kw)

    def fake_os_open(path, flags, *x, **kw):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(path)
        return real_os_open(path, flags, *x, **kw)

    monkeypatch.setattr(builtins, 'open', fake_open)
    monkeypatch.setattr(io, 'open', fake_open)
    monkeypatch.setattr(os, 'open', fake_os_open)
    a = agent(root)
    secret = 'SENTINEL-PHONE-' + os.urandom(3).hex()
    t = time.time()
    for i in range(50):
        a.reading(t + i * 0.05)
    a.on_consent()
    a.on_keys(secret, 2000, 1)
    a.handle({'type': 'phone', 'data': {'text': secret}})     # even if the Pi echoed it
    a.handle({'type': 'wipe', 'data': {'visitor_id': 'v-1'}})
    a.wipe()
    out = capsys.readouterr()
    assert writes == [os.devnull] * writes.count(os.devnull), writes
    assert secret not in out.out + out.err
    # and the wipe drops it from the screen state and the send queue
    assert secret not in repr(a.ui_snapshot())
    assert a.events.qsize() == 0


# ------------------------------------------------------------------ opt-out
def cover(a, root, t, seconds=3.4, step=0.05):
    put(root, PROX, 'closed')
    end = t + seconds
    while t < end:
        t += step
        a.reading(t)
    return t


def test_optout_stops_every_reading_and_frame():
    root = sysfs()
    a = agent(root)
    a.camera._on_frame(b'\x10' * (160 * 120))
    a.on_consent()
    t = cover(a, root, time.time())
    assert a.opted_out and a.ui_snapshot()['optout']
    assert a.camera.latest()[0] is None
    sent = []
    while not a.events.empty():
        sent.append(a.events.get_nowait())
    assert {'kind': 'optout'} in [m['data'] for m in sent]
    put(root, PROX, 'open')
    assert a.reading(t + 0.1) == {'kind': 'phone', 'optout': True}
    a.on_keys('SENTINEL-AFTER-OPTOUT')
    a.on_touch(0.5, 0.5, True)
    a.ui_update(prompt={'prompt_id': 'closer', 'ask': 'x', 'options': ['a', 'b'], 't': t})
    a.on_choice(0)
    assert a.events.empty(), 'events sent after opt-out'


def test_optout_survives_a_pi_wipe_while_still_held():
    """The engine ends the visit ~18 s after the opt-out (the phone stops reporting presence)
    and sends wipe. The same person still holding the phone must not be read again."""
    root = sysfs(accel=TILTED)
    a = agent(root)
    a.on_consent()
    t = cover(a, root, time.time())
    put(root, PROX, 'open')
    for i in range(20):                 # still in the hand
        t += 0.05
        a.reading(t)
    a.handle({'type': 'wipe', 'data': {'visitor_id': 'v-1'}})
    assert a.opted_out, 'a wipe from the Pi restarted reading of the opted-out visitor'
    assert a.reading(t + 0.1) == {'kind': 'phone', 'optout': True}
    assert a.ui_snapshot()['optout']


def test_optout_ends_once_the_phone_is_put_down():
    root = sysfs(accel=TILTED)
    a = agent(root)
    a.on_consent()
    t = cover(a, root, time.time())
    put(root, PROX, 'open')
    put(root, ACCEL, FLAT)
    end = t + DEFAULTS['optout_release_s'] + 3.5      # handling decays ~2.5 s, then the release time
    while t < end:
        t += 0.05
        a.reading(t)
    assert not a.opted_out
    assert a.ui_snapshot()['screen'] == 'consent' and not a.ui_snapshot()['optout']
    assert 'optout' not in a.reading(t + 0.1)


def test_wipe_after_optout_on_a_table_clears_at_once():
    """Covered while lying on the table (nobody holding it): a wipe ends the opt-out as before."""
    root = sysfs(accel=FLAT)
    a = agent(root)
    a.on_consent()
    t = cover(a, root, time.time())
    put(root, PROX, 'open')
    a.reading(t + 0.1)
    a.handle({'type': 'wipe', 'data': {'visitor_id': 'v-1'}})
    assert not a.opted_out and a.ui_snapshot()['screen'] == 'consent'
