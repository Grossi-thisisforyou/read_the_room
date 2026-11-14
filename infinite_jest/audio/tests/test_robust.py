"""Robustness tests for an unattended show.

    python3 -m unittest infinite_jest.audio.tests.test_robust -v
"""
import threading
import time
import unittest

from infinite_jest.audio import engine, sinks


class RecordingSink:
    name = "recording"

    def __init__(self, fail_after=None):
        self.frames = 0
        self.fail_after = fail_after
        self.closed = False

    def write(self, block):
        if self.fail_after is not None and self.frames >= self.fail_after:
            raise IOError("device unplugged (simulated)")
        self.frames += 1
        time.sleep(0.002)

    def close(self):
        self.closed = True


class _Ev:
    def __init__(self):
        self.e = threading.Event()

    def is_set(self):
        return self.e.is_set()

    def set(self):
        self.e.set()

    def clear(self):
        self.e.clear()


class _Q:
    def get_nowait(self):
        import queue
        raise queue.Empty


class SinkRetryTest(unittest.TestCase):
    def test_sink_appears_late_and_comes_back(self):
        """No device at start -> silent + retry; device dies -> retry; picked up again."""
        opened = []
        first = RecordingSink(fail_after=5)      # appears on the 3rd try, then is unplugged
        second = RecordingSink()                 # plugged back in
        plan = [None, None, first, None, second]

        def fake_open(cfg, block=1024, quiet=False):
            item = plan.pop(0) if plan else None
            opened.append(item)
            return item if item is not None else sinks.NullSink(block)

        orig = sinks.open_sink
        sinks.open_sink = fake_open
        stop = _Ev()
        try:
            t = threading.Thread(target=engine._worker,
                                 args=({"audio_sink": "auto", "audio_retry_s": 0.15}, _Q(), _Q(), stop, _Ev()))
            t.start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and second.frames < 10:
                time.sleep(0.05)
            stop.set()
            t.join(10)
        finally:
            sinks.open_sink = orig
        self.assertEqual(first.frames, 5)
        self.assertTrue(first.closed)
        self.assertGreaterEqual(second.frames, 10, "the re-plugged device never got audio")
        self.assertGreaterEqual(len(opened), 5)


class ChildRestartTest(unittest.TestCase):
    def test_crashing_child_is_restarted(self):
        eng = engine.AudioEngine({"audio_sink": "null", "audio_test_crash": 40})
        eng.start()
        try:
            eng.on_state({"phase": "approach", "visitor_id": "v-test", "intensity": 0.4})
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not (eng.restarts >= 1 and eng.running):
                eng.on_state({"phase": "approach", "visitor_id": "v-test"})   # safe during restarts
                eng.on_wipe()
                eng.set_volume(0.5)
                time.sleep(0.2)
            self.assertGreaterEqual(eng.restarts, 1)
            self.assertTrue(eng.running)
            time.sleep(2.0)                      # the second incarnation does not crash
            self.assertTrue(eng.running)
            eng.on_wipe()
            eng.set_volume(0.8)
        finally:
            eng.stop()
        self.assertFalse(eng.running)


if __name__ == "__main__":
    unittest.main()
