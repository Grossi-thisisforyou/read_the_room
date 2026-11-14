import base64
import json
import os
import random
import socket
import threading
import unittest

from infinite_jest.profiler import create, sim
from infinite_jest.profiler.features import Features
from infinite_jest.profiler.hooks import HOOKS, HookBandit
from infinite_jest.profiler.ocean import TRAITS, estimate
from infinite_jest.profiler.vision import Vision


def last_profile(profiles):
    return profiles[-1]["data"]


class TestEstimates(unittest.TestCase):
    def test_lively_vs_withdrawn_extraversion(self):
        perf, _ = sim.run("performer", seed=1)
        lurk, _ = sim.run("lurker", seed=1)
        self.assertGreater(last_profile(perf)["ocean"]["E"], 0.7)
        self.assertLess(last_profile(lurk)["ocean"]["E"], 0.35)

    def test_scores_and_confidence_in_range(self):
        for name in sim.ARCHETYPES:
            profiles, _ = sim.run(name, seed=2)
            for p in profiles:
                d = p["data"]
                self.assertEqual(set(d["ocean"]), set(TRAITS))
                for t in TRAITS:
                    self.assertTrue(0.0 <= d["ocean"][t] <= 1.0)
                    self.assertTrue(0.0 <= d["trait_confidence"][t] <= 1.0)
                self.assertTrue(0.0 <= d["confidence"] <= 1.0)
                self.assertIn(d["hook"], HOOKS)

    def test_no_evidence_is_neutral(self):
        ocean, conf, overall, ev = estimate({})
        self.assertEqual(overall, 0.0)
        self.assertTrue(all(v == 0.5 for v in ocean.values()))

    def test_hard_traits_stay_humble(self):
        profiles, _ = sim.run("performer", seed=3)
        tc = last_profile(profiles)["trait_confidence"]
        self.assertLessEqual(tc["N"], 0.5)
        self.assertLessEqual(tc["A"], 0.5)
        self.assertGreater(tc["E"], tc["N"])

    def test_confidence_grows(self):
        profiles, _ = sim.run("seeker", seed=4)
        self.assertLess(profiles[0]["data"]["confidence"], profiles[-1]["data"]["confidence"])
        crossed = [p["data"]["seconds"] for p in profiles if p["data"]["confidence"] >= 0.6]
        self.assertTrue(crossed and crossed[0] < 25, "engine expects >=0.6 within ~25 s")


class TestBandit(unittest.TestCase):
    def test_learns_favourite(self):
        wins = 0
        for seed in range(8):
            b = HookBandit(seed=seed, min_dwell=1.0)
            ocean = dict.fromkeys(TRAITS, 0.5)
            rng = random.Random(seed)
            t = 0.0
            for _ in range(60):
                h = b.choose(ocean, 0.0, t)
                for _ in range(4):
                    b.observe(0.8 if h == "mirror" else 0.3 + 0.1 * rng.random())
                t += 1.0
            b.finish(t)
            wins += b.ranking()[0] == "mirror"
        self.assertGreaterEqual(wins, 7)

    def test_prior_follows_profile(self):
        b = HookBandit(seed=0)
        introvert = {"O": 0.5, "C": 0.8, "E": 0.1, "A": 0.5, "N": 0.4}
        picks = [HookBandit(seed=s).choose(introvert, 1.0, 0.0) for s in range(40)]
        self.assertEqual(max(set(picks), key=picks.count), "void")


class TestLifecycleAndPrivacy(unittest.TestCase):
    def test_reveal_then_wipe(self):
        p = create({"seed": 1})
        profiles, reveal = sim.run("performer", seed=1, profiler=p)
        self.assertIsNotNone(reveal)
        lines = reveal["data"]["lines"]
        # Works with the built-in templates and with infinite_jest/text's corpus.
        self.assertGreater(len(lines), 5)
        self.assertTrue(any("r = .2" in l for l in lines))
        text = " ".join(lines).lower()
        for hidden in ("bacon", "basquiat", "baselitz", "crown", "scrawl", "flesh", "inverted",
                       "tremor", "shook", "shake"):
            self.assertNotIn(hidden, text)
        # after the sim's wipe message nothing is left
        self.assertIsNone(p.visitor_id)
        self.assertEqual(p.features.summary(), {})
        self.assertIsNone(p.vision.prev)

    def test_keys_text_never_kept(self):
        f = Features()
        f.add({"kind": "keys", "text": "my secret is 1234"}, 1.0)
        self.assertNotIn("secret", json.dumps(f.__dict__, default=str))
        self.assertEqual(f.keys_chars, 17)

    def test_opt_out_by_covering_sensor(self):
        p = create({"seed": 1})
        out = []
        for i in range(30):
            ts = 10 + i * 0.25
            out += p.handle({"type": "sensor", "ts": ts, "data": {"kind": "vision", "present": True,
                                                                 "cx": 0.5, "size": 0.3, "motion": 0.2}})
        for i in range(16):
            ts = 18 + i * 0.25
            out += p.handle({"type": "sensor", "ts": ts, "data": {"kind": "phone", "proximity": {"near": True}}})
        opted = [m for m in out if m["data"].get("phase") == "opted_out"]
        self.assertTrue(opted)
        self.assertEqual(p.features.summary(), {})
        # further sensing produces nothing for this visitor
        self.assertEqual(p.handle({"type": "sensor", "ts": 30, "data": {"kind": "vision", "present": True,
                                                                        "cx": 0.5, "size": 0.3, "motion": 0.2}}), [])

    def test_own_visit_ends_after_absence(self):
        p = create({"seed": 1})
        p.handle({"type": "sensor", "ts": 0, "data": {"kind": "vision", "present": True, "cx": .5, "size": .2, "motion": .1}})
        self.assertIsNotNone(p.visitor_id)
        out = p.handle({"type": "sensor", "ts": 10, "data": {"kind": "vision", "present": False}})
        self.assertTrue(out and out[0]["data"].get("wiped"))
        self.assertIsNone(p.visitor_id)

    def test_rate_limit_2hz(self):
        profiles, _ = sim.run("performer", seed=5)
        ts = [p["ts"] for p in profiles]
        self.assertTrue(all(b - a >= 0.5 for a, b in zip(ts, ts[1:])))

    def test_contract_touch_down_up(self):
        f = Features()
        f.add({"kind": "touch", "x": .2, "y": .2, "down": True}, 1.0)
        f.add({"kind": "touch", "x": .2, "y": .2, "down": False}, 2.5)
        self.assertEqual(f.touches[0][1], "hold")


class TestInProcessInterface(unittest.TestCase):
    def test_engine_calls(self):
        p = create({"seed": 2})
        self.assertIsNone(p.on_visit({"visitor_id": "v-7f3a", "phase": "approach"}, 0.0))
        d = None
        for i in range(80):
            d = p.on_sensor({"kind": "vision", "present": True, "cx": 0.4 + i * 0.003,
                             "size": 0.5, "motion": 0.4, "face": True}, i * 0.25) or d
        self.assertEqual(d["type"], "profile")
        self.assertEqual(d["visitor_id"], "v-7f3a")
        r = p.on_visit({"visitor_id": "v-7f3a", "phase": "release", "reveal": True}, 20.0)
        self.assertEqual(r["type"], "reveal")
        self.assertTrue(r["lines"])
        p.reset()
        self.assertIsNone(p.visitor_id)


class TestHandheld(unittest.TestCase):
    def test_handheld_drops_walking_features_and_uses_tilt(self):
        p = create({"seed": 1})
        p.handle({"type": "state", "ts": 0, "data": {"visitor_id": "v-1", "phase": "approach",
                                                       "mode": "handheld"}})
        for i in range(120):
            ts = i * 0.1
            p.handle({"type": "sensor", "ts": ts, "data": {"kind": "vision", "present": True,
                      "cx": 0.2 + (i % 10) * 0.06, "size": 0.6, "motion": 0.3, "face": True}})
            p.handle({"type": "sensor", "ts": ts, "data": {"kind": "phone", "held": True,
                      "tilt": {"alpha": 0, "beta": 40 * ((i % 20) - 10) / 10, "gamma": 10},
                      "accel": {"x": 0, "y": 0, "z": 1.1}}})
        s = p.features.summary()
        for k in ("pace", "roaming", "approach_time"):
            self.assertNotIn(k, s)
        for k in ("handled", "tilt_range", "tilt_speed", "gaze"):
            self.assertIn(k, s)


class TestJunkInput(unittest.TestCase):
    def test_junk_never_raises(self):
        rng = random.Random(0)
        junk = [None, {}, [], "x", "nan", float("nan"), float("inf"), -1e308, {"a": 1}, [1, 2], True, 10 ** 400]
        kinds = ["vision", "phone", "touch", "choice", "keys", "accel", "proximity", "audio", "optout", None, 5]
        fields = ["present", "cx", "size", "motion", "face", "presence", "audio", "accel", "proximity",
                  "held", "tilt", "x", "y", "down", "gesture", "duration_ms", "prompt_id", "option",
                  "latency_ms", "text", "level", "voiced", "near", "z"]
        p = create({"seed": 0})
        for i in range(3000):
            data = {"kind": rng.choice(kinds)}
            for f in rng.sample(fields, 6):
                data[f] = rng.choice(junk)
            m = {"type": rng.choice(["sensor", "frame", "state", "wipe", "answer", None]),
                 "ts": rng.choice(junk + [i * 0.1]), "rx_ts": rng.choice([None, i * 0.1]),
                 "data": rng.choice([data, None, "x", []])}
            p.handle(m)
        self.assertTrue(True)

    def test_rx_ts_wins_over_phone_clock(self):
        p = create({"seed": 0})
        p.handle({"type": "state", "ts": 0, "rx_ts": 100.0, "data": {"visitor_id": "v-1", "phase": "approach"}})
        out = p.handle({"type": "sensor", "ts": 9e9, "rx_ts": 101.0,
                        "data": {"kind": "vision", "present": True, "cx": .5, "size": .3, "motion": .2}})
        self.assertFalse([m for m in out if m["type"] == "reveal"])


class TestVision(unittest.TestCase):
    def frame(self, w, h, box=None, val=200):
        px = bytearray([30] * (w * h))
        if box:
            x0, y0, x1, y1 = box
            for y in range(y0, y1):
                for x in range(x0, x1):
                    px[y * w + x] = val
        return {"w": w, "h": h, "fmt": "gray8", "b64": base64.b64encode(bytes(px)).decode()}

    def test_person_blob(self):
        v = Vision()
        v.frame(self.frame(160, 120))
        out = v.frame(self.frame(160, 120, (100, 20, 140, 110)))
        self.assertTrue(out["present"])
        self.assertAlmostEqual(out["cx"], 0.75, delta=0.05)
        self.assertGreater(out["size"], 0.6)
        self.assertGreater(out["motion"], 0.1)

    def test_empty_room(self):
        v = Vision()
        v.frame(self.frame(160, 120))
        out = v.frame(self.frame(160, 120))
        self.assertFalse(out["present"])

    def test_bad_frame_ignored(self):
        self.assertIsNone(Vision().frame({"w": 160, "h": 120, "fmt": "gray8", "b64": "AAAA"}))


class TestWebSocketClient(unittest.TestCase):
    def test_round_trip_with_fake_engine(self):
        from infinite_jest.profiler.ws_client import MiniWS
        import hashlib
        import struct
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        got = {}

        def engine():
            c, _ = srv.accept()
            req = c.recv(4096).decode()
            key = [l.split(": ")[1] for l in req.split("\r\n") if l.lower().startswith("sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
            b1, b2 = c.recv(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", c.recv(2))[0]
            mask = c.recv(4)
            data = b""
            while len(data) < n:
                data += c.recv(n - len(data))
            got["msg"] = bytes(x ^ mask[i % 4] for i, x in enumerate(data)).decode()
            reply = b'{"type":"wipe","ts":1,"data":{}}'
            c.sendall(bytes([0x81, len(reply)]) + reply)
            c.close()

        th = threading.Thread(target=engine)
        th.start()
        ws = MiniWS("ws://127.0.0.1:%d/ws" % port)
        ws.send(json.dumps({"type": "hello", "data": {"role": "profiler"}}))
        self.assertEqual(json.loads(ws.recv())["type"], "wipe")
        th.join(2)
        srv.close()
        self.assertIn("profiler", got["msg"])


if __name__ == "__main__":
    unittest.main()
