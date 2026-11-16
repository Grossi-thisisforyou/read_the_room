"""The quality governor: steps the picture down when frames run over budget
(a Pi 5 that also runs the language model) and back up when there is room.

    SDL_VIDEODRIVER=dummy python3 -m unittest infinite_jest.visuals.tests.test_governor -v
"""
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from infinite_jest import visuals  # noqa: E402
from infinite_jest.visuals import engine  # noqa: E402
from infinite_jest.visuals.figure import ghost_body  # noqa: E402
from infinite_jest.visuals.governor import Governor  # noqa: E402


def setUpModule():
    pygame.display.init()


def _feed(g, ms_at, t0, t1, fps=30):
    """Feed render times ms_at(t) from t0 to t1; returns [(t, level)] changes."""
    out = []
    n = int((t1 - t0) * fps)
    for i in range(n):
        t = t0 + i / fps
        lvl = g.observe(ms_at(t), t)
        if lvl is not None:
            out.append((t, lvl))
    return out


class GovernorSteps(unittest.TestCase):
    def test_steps_down_one_notch_at_a_time_and_never_faster_than_hold(self):
        g = Governor(28, quiet=True)
        ch = _feed(g, lambda t: 45.0, 0, 60)
        self.assertEqual([lvl for _, lvl in ch], [1, 2, 3])          # all the way down, in order
        for (a, _), (b, _) in zip(ch, ch[1:]):
            self.assertGreaterEqual(b - a, 10.0 - 1e-6, ch)
        self.assertEqual(g.settings["taps"], 3)
        self.assertFalse(g.settings["smooth"])
        self.assertTrue(g.settings["small"])
        self.assertEqual(len(g.log), 3)

    def test_steps_back_up_only_after_a_long_comfortable_stretch(self):
        g = Governor(28, up_s=30, quiet=True)
        _feed(g, lambda t: 45.0, 0, 3)                               # one step down (at ~1.5 s)
        self.assertEqual(g.level, 1)
        ch = _feed(g, lambda t: 12.0, 3, 30)
        self.assertEqual(ch, [])                                       # ~25 s comfortable is not long enough
        ch = _feed(g, lambda t: 12.0, 30, 60)
        self.assertEqual([lvl for _, lvl in ch], [0])

    def test_no_see_saw_a_failed_step_up_doubles_the_wait(self):
        """Full quality runs at 34 ms, the first step at 17 ms: the governor must
        not flip between them every few seconds."""
        g = Governor(28, up_s=30, quiet=True)
        ms = lambda t: 34.0 if g.level == 0 else 17.0
        ch = _feed(g, ms, 0, 600)
        # changes at least 10 s apart, and each retry waits longer than the last
        for (a, _), (b, _) in zip(ch, ch[1:]):
            self.assertGreaterEqual(b - a, 10.0 - 1e-6)
        ups = [t for t, lvl in ch if lvl == 0]
        gaps = [b - a for a, b in zip(ups, ups[1:])]
        self.assertTrue(all(y > x for x, y in zip(gaps, gaps[1:])), gaps)
        self.assertLessEqual(len(ch), 10, ch)                          # ~a handful in 10 minutes

    def test_levels_that_change_nothing_are_skipped(self):
        g = Governor(28, smooth=False, can_shrink=False, quiet=True)
        ch = _feed(g, lambda t: 60.0, 0, 60)
        self.assertEqual([lvl for _, lvl in ch], [1])                 # only fewer strokes and taps is left

    def test_budget_zero_turns_it_off(self):
        g = Governor(0, quiet=True)
        self.assertEqual(_feed(g, lambda t: 500.0, 0, 30), [])


class _Clock:
    """time for the engine with an artificial slowdown added inside render."""

    def __init__(self):
        self.off = 0.0

    def perf_counter(self):
        return time.perf_counter() + self.off

    def monotonic(self):
        return time.monotonic()


class GovernorInTheEngine(unittest.TestCase):
    def test_artificial_slowdown_steps_down_to_480x270_and_recovers(self):
        v = visuals.create((640, 360), {"busy_file": "", "bank_dir": "/nonexistent", "frame_budget_ms": 28})
        v.governor.quiet = True
        v.governor.hold_s, v.governor.up_s0, v.governor.up_s = 2.0, 3.0, 3.0
        screen = pygame.Surface((640, 360))
        clock = _Clock()
        real = v._render
        slow = {"ms": 40.0}

        def slowed(surface, dt):
            real(surface, dt)
            clock.off += slow["ms"] / 1000.0          # this frame "took" 40 ms longer

        v._render = slowed
        oc = {"O": 0.6, "C": 0.4, "E": 0.6, "A": 0.4, "N": 0.7}
        with mock.patch.object(engine, "time", clock), mock.patch.dict(os.environ, {"IJ_VISUALS_STRICT": "1"}):
            def run(seconds, t0):
                for i in range(int(seconds * 30)):
                    pt = t0 + i / 30
                    v.on_state({"visitor_id": "g", "phase": "hook", "phase_t": pt, "hook": "flesh",
                                "intensity": 0.8, "ocean": oc})
                    if i % 8 == 0:
                        v.on_frame(ghost_body(160, 120, pt, present=1.0))
                    v.render(screen, 1 / 30)
            run(9, 0.0)
            self.assertEqual(v.governor.level, 3, v.governor.log)
            self.assertEqual((v.W, v.H), (480, 270))
            self.assertFalse(v.smooth)
            self.assertEqual(v.q["taps"], 3)
            self.assertEqual(v.low.get_size(), (480, 270))
            # the scene is repainted at the new size and the picture keeps going
            self.assertEqual(v.ground_surf.get_size(), (480 + 2 * v.M, 270 + 2 * v.M))
            slow["ms"] = 0.0
            run(25, 9.0)
            self.assertEqual(v.governor.level, 0, v.governor.log)
            self.assertEqual((v.W, v.H), (640, 360))
            self.assertTrue(v.smooth)
            self.assertEqual(v.low.get_size(), (640, 360))
            self.assertEqual(v.ground_surf.get_size(), (640 + 2 * v.M, 360 + 2 * v.M))
            self.assertFalse(getattr(v, "_err_logged", False))
            # never two changes within hold_s
            ts = [float(line.split("s ")[0][2:]) for line in v.governor.log]
            for a, b in zip(ts, ts[1:]):
                self.assertGreaterEqual(b - a, 2.0 - 0.05, v.governor.log)


if __name__ == "__main__":
    unittest.main()
