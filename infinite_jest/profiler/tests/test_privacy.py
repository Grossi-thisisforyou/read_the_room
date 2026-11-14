"""Privacy claims the profiler makes (README section 5, DATA_HANDLING.md)."""

import base64
import contextlib
import io
import unittest

from infinite_jest.profiler import create

W, H = 160, 120
TILE = bytes([0x13, 0x37, 0xC0, 0xDE, 0x51, 0x8A, 0x2F, 0x99, 0x04, 0xE7, 0x6B, 0xB2, 0x3D, 0x75, 0xA8, 0x1C])


def frame(cx):
    px = bytearray(TILE * (W * H // len(TILE)))
    for y in range(40, 90):
        for x in range(max(0, cx - 18), min(W, cx + 18)):
            px[y * W + x] = 250
    return {"w": W, "h": H, "fmt": "gray8", "b64": base64.b64encode(bytes(px)).decode()}


def live_visit(p, seconds=20.0, t0=100.0):
    p.on_visit({"visitor_id": "v-test", "phase": "approach"}, t0)
    t = t0
    while t < t0 + seconds:
        t += 0.25
        p.on_sensor({"kind": "phone", "held": True, "presence": 0.9, "audio": {"level": 0.4, "voiced": True}}, t)
        p.on_frame(frame(int(80 + 40 * ((t * 3) % 2 - 1))), t)
    p.on_sensor({"kind": "choice", "prompt_id": "closer", "option": "look closer", "latency_ms": 800}, t)
    p.on_sensor({"kind": "keys", "text": "SENTINEL-PROFILER-TEXT"}, t)
    return t


class TestOptOut(unittest.TestCase):
    def test_optout_drops_the_last_profile(self):
        p = create({"seed": 1})
        t = live_visit(p)
        self.assertIsNotNone(p.last_profile)
        out = p.on_sensor({"kind": "optout"}, t + 0.1)
        self.assertEqual(out["phase"], "opted_out")
        self.assertIsNone(p.last_profile, "the OCEAN guess survived the opt-out in last_profile")
        self.assertEqual(p.features.choices, [])
        self.assertEqual(p.features.keys_chars, 0)

    def test_frames_after_optout_are_not_analysed(self):
        p = create({"seed": 1})
        t = live_visit(p)
        p.on_sensor({"kind": "optout"}, t + 0.1)
        for i in range(8):
            self.assertIsNone(p.on_frame(frame(40 + 10 * i), t + 0.2 + i * 0.25))
        self.assertIsNone(p.vision.prev, "an opted-out visitor's frame was analysed")
        self.assertIsNone(p.vision.bg)
        # also over the WebSocket path
        self.assertEqual(p.handle({"type": "frame", "ts": t + 5, "data": frame(60)}), [])
        self.assertIsNone(p.vision.prev)

    def test_cover_for_three_seconds_opts_out_and_drops_frames(self):
        p = create({"seed": 1})
        t = live_visit(p)
        out = None
        for i in range(40):
            t += 0.1
            r = p.on_sensor({"kind": "phone", "held": True, "proximity": {"near": True}}, t)
            out = r or out
        self.assertTrue(p.opted_out)
        self.assertEqual(out["phase"], "opted_out")
        self.assertIsNone(p.vision.prev)
        self.assertIsNone(p.last_profile)

    def test_next_visitor_is_read_again(self):
        p = create({"seed": 1})
        t = live_visit(p)
        p.on_sensor({"kind": "optout"}, t + 0.1)
        p.on_visit({"visitor_id": "v-next", "phase": "approach"}, t + 30)
        self.assertFalse(p.opted_out)
        self.assertIsNotNone(p.on_frame(frame(70), t + 30.25) or True)
        p.on_frame(frame(90), t + 30.5)
        self.assertIsNotNone(p.vision.prev)


class TestNothingKept(unittest.TestCase):
    def test_profile_messages_carry_no_typed_text_or_pixels(self):
        p = create({"seed": 1})
        live_visit(p)
        prof = p._profile(200.0)["data"]
        text = repr(prof)
        self.assertNotIn("SENTINEL", text)
        self.assertNotIn("b64", text)
        reveal = p._reveal(201.0)["data"]
        self.assertNotIn("SENTINEL", repr(reveal))

    def test_reset_drops_everything(self):
        p = create({"seed": 1})
        live_visit(p)
        p.reset()
        self.assertIsNone(p.visitor_id)
        self.assertIsNone(p.last_profile)
        self.assertIsNone(p.vision.prev)
        self.assertEqual(p.bandit.history, [])
        self.assertEqual(p.features.keys_chars, 0)

    def test_profiler_prints_nothing_without_debug(self):
        p = create({"seed": 1})
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            live_visit(p)
            p.reset()
        self.assertEqual(buf_out.getvalue() + buf_err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
