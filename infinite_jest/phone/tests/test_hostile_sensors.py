"""Junk from the N900's sysfs files, and the no-json fallback of Python 2.5."""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))

import compat  # noqa: E402
from sensors import Sensors, PATHS  # noqa: E402


def tree(values):
    root = tempfile.mkdtemp()
    for k, v in values.items():
        p = root + PATHS[k]
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        open(p, 'w').write(v)
    return root


def finite_tree(o):
    if isinstance(o, float):
        return math.isfinite(o)
    if isinstance(o, dict):
        return all(finite_tree(v) for v in o.values())
    return True


def test_accel_junk_never_poisons_tilt():
    root = tree({'accel': '0 0 -1000'})
    s = Sensors(root=root)
    t = 0.0
    for junk in ['nan nan nan', 'inf 0 0', '-inf -inf 5', 'garbage', '1 2', '', '0 0 0',
                 '99999999 0 0', '\x00\x01', '12 -40']:
        open(root + PATHS['accel'], 'w').write(junk)
        t += 0.05
        r = s.poll(t)
        assert finite_tree(r), (junk, r)
        assert json.loads(compat.dumps(r), parse_constant=lambda c: 1 / 0) is not None
    open(root + PATHS['accel'], 'w').write('0 0 -1000')
    for i in range(40):
        t += 0.05
        r = s.poll(t)
    assert abs(r['tilt']['beta']) < 2 and abs(r['tilt']['gamma']) < 2, r


def test_all_zero_accel_is_finite():
    s = Sensors(root=tree({'accel': '0 0 0'}))
    for i in range(20):
        r = s.poll(i * 0.05)
    assert finite_tree(r)


def test_no_sysfs_at_all_still_polls():
    s = Sensors(root=tempfile.mkdtemp())
    assert s.poll(0.0) == {}


def test_lux_and_battery_junk():
    s = Sensors(root=tree({'lux': 'nan', 'battery': 'inf'}))
    r = s.poll(100.0)
    assert 'light' not in r and 'battery' not in r


def test_face_down_still_is_not_held():
    root = tree({'accel': '0 0 1000', 'proximity': 'closed'})
    s = Sensors(root=root)
    for i in range(100):
        r = s.poll(i * 0.05)
    assert r['held'] is False and abs(abs(r['tilt']['beta']) - 180) < 5


def test_fallback_json_without_json_module(monkeypatch):
    """Python 2.5 has no json; without simplejson the hand-written codec runs."""
    monkeypatch.setattr(compat, '_json', None)
    obj = {'type': 'phone', 'ts': 1.5, 'data': {'text': u'caf\xe9 ☃ "q" \\ \n',
                                                'options': ['a', 'b'], 'n': None, 'ok': True,
                                                'x': [1, -2.25, {'y': []}]}}
    s = compat.dumps(obj)
    assert json.loads(s) == compat.loads(s)
    assert compat.loads(s)['data']['text'] == obj['data']['text']
    # garbage raises (the agent catches it), never loops forever
    for junk in ['', '{', '{"a":', '[1,', 'NaN', '{"a" 1}', '"\\u12', 'nul']:
        try:
            compat.loads(junk)
        except Exception:
            pass
    # the encoder never emits NaN/Infinity (the Pi's json rejects them)
    s = compat.dumps({'a': float('nan'), 'b': [float('inf'), -float('inf')]})
    assert json.loads(s, parse_constant=lambda c: 1 / 0) == {'a': None, 'b': [None, None]}
