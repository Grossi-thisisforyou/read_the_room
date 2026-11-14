"""'held' as a latch: still holders count, a phone hanging or resting doesn't."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'n900'))
from sensors import Sensors, PATHS

FLAT = '18 -36 -1008'
TILT = '0 -420 -900'          # held gently tilted ~25 degrees
LIFT = ['200 -300 -1400', '-150 -500 -700', '100 -400 -1200']


def run(root, s, t, values, seconds, step=0.05):
    end = t + seconds
    i = 0
    out = None
    while t < end:
        open(root + PATHS['accel'], 'w').write(values[i % len(values)])
        out = s.poll(t)
        t += step
        i += 1
    return t, out


def setup():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.dirname(root + PATHS['accel']))
    open(root + PATHS['accel'], 'w').write(FLAT)
    return root, Sensors(root=root)


def test_resting_flat_is_not_held():
    root, s = setup()
    t, out = run(root, s, 0.0, [FLAT], 10)
    assert out['held'] is False


def test_still_holder_stays_held():
    root, s = setup()
    t, out = run(root, s, 0.0, [FLAT], 2)
    t, out = run(root, s, t, LIFT, 0.5)           # the pick-up
    assert out['held'] is True
    t, out = run(root, s, t, [TILT], 30)          # perfectly still in the hand, no visible tremor
    assert out['held'] is True


def test_put_down_flat_ends_held():
    root, s = setup()
    t, out = run(root, s, 0.0, LIFT, 0.5)
    t, out = run(root, s, t, [TILT], 5)
    t, out = run(root, s, t, [FLAT], 6)
    assert out['held'] is False


def test_hanging_dead_still_from_the_tether_ends_held():
    root, s = setup()
    t, out = run(root, s, 0.0, LIFT, 0.5)
    t, out = run(root, s, t, ['0 -1000 -60'], Sensors.HANG_S + 3)   # hanging upright, not moving
    assert out['held'] is False


if __name__ == '__main__':
    for n, f in list(globals().items()):
        if n.startswith('test_'):
            f()
            print('PASS', n)
