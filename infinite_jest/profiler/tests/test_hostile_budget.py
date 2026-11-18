"""Pi-budget regressions for the profiler (found by pi/tools/budget.py).

Run from the repo root: python3 -m unittest infinite_jest.profiler.tests.test_hostile_budget
"""
import random
import time
import unittest

from infinite_jest.profiler import vision
from infinite_jest.profiler.vision import Vision


def _frames(w, h, n, seed=1):
    rng = random.Random(seed)
    wall = [100 + (x * 3 + y) % 20 for y in range(h) for x in range(w)]
    out = []
    for k in range(n):
        px = list(wall)
        if k % 7 not in (0, 1):                      # someone walks through, sometimes nobody
            x0 = (k * 5) % (w - 30)
            for y in range(h // 4, h):
                for x in range(x0, x0 + 25):
                    px[y * w + x] = 30 + rng.randrange(40)
        for _ in range(200):                         # sensor noise
            i = rng.randrange(w * h)
            px[i] = rng.randrange(256)
        out.append(bytes(px))
    return out


class TestVisionFastPath(unittest.TestCase):
    def test_numpy_path_gives_the_same_numbers(self):
        if vision._np is None:
            self.skipTest("numpy not installed")
        for w, h in ((160, 120), (320, 240), (90, 61)):
            fast, slow = Vision(), Vision()
            for px in _frames(w, h, 30):
                a = fast.gray(px, w, h)                 # bytes -> numpy path
                b = slow.gray(list(px), w, h)           # list -> the original loop
                self.assertEqual(a, b)

    def test_frame_analysis_fits_the_pi_budget(self):
        """The pure-Python loop took ~2 ms per 160x120 frame here (~5 ms on a
        Pi 5) on the frame loop's thread; 320x240 ~8 ms (~20 ms on a Pi)."""
        if vision._np is None:
            self.skipTest("numpy not installed")
        v = Vision()
        frames = _frames(320, 240, 10)
        t0 = time.perf_counter()
        for _ in range(5):
            for px in frames:
                v.gray(px, 320, 240)
        per = (time.perf_counter() - t0) / 50
        self.assertLess(per, 0.002)


if __name__ == "__main__":
    unittest.main()
