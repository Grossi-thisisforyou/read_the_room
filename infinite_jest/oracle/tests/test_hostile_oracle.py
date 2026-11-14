"""Adversarial tests for everything the local model can put in front of a visitor.

1. The guard (voice.clean_*) against a corpus of hostile model outputs: 0 leaks.
2. Lines that carry the piece's voice must still pass (no blandness).
3. Canned text (profiler lines, prompts, reveal, phone lines, wall word lists)
   obeys the same rules as the model.
4. The HTTP client against a fake llama-server that hangs, trickles, errors,
   lies or floods: every failure ends inside the deadline with an exception
   (the worker then keeps the template text).
"""

import ast
import json
import os
import socket
import threading
import time
import tomllib
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from infinite_jest.oracle import Oracle, voice
from infinite_jest.oracle.oracle import http_complete, DEFAULTS
from infinite_jest.oracle.tests import hostile_corpus as hc
from infinite_jest.profiler import hooks, reveal, ocean, sim

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestCorpus(unittest.TestCase):
    def test_corpus_is_big_enough(self):
        cases = hc.cases()
        self.assertGreaterEqual(len(cases), 300)
        self.assertGreaterEqual(len({c for c, _l, _n in cases}), 30)

    def test_zero_leaks(self):
        leaks = []
        for cat, line, needles in hc.cases():
            for kind, text in hc.contexts(line):
                fn = voice.clean_words if kind == "words" else voice.clean_dossier
                for k, lines in hc.visible(kind, fn(text)):
                    for why in hc.judge(k, lines, needles):
                        leaks.append((cat, why))
        self.assertEqual(leaks, [], "%d leaks, first: %s" % (len(leaks), leaks[:5]))

    def test_whole_answer_dropped_on_one_bad_line(self):
        self.assertIsNone(voice.clean_words("hold me closer\nSUBJECT LINGERS\nNERVOUS GRIP\nKEEPS STILL"))
        self.assertIsNone(voice.clean_dossier("you came close.\nyou seemed lonely.\nmostly a guess."))

    def test_garbage_inputs(self):
        for junk in (None, "", "\n\n\n", " ", "-\n*\n1.", "\x00", "a" * 100000):
            self.assertIsNone(voice.clean_words(junk))
        self.assertIsNone(voice.clean_dossier(None))


class TestVoiceSurvives(unittest.TestCase):
    def test_benign_lines_kept(self):
        for p in hc.BENIGN_PHONE:
            r = voice.clean_words("%s\nSUBJECT LINGERS\nKEEPS STILL" % p)
            self.assertIsNotNone(r, p)
            self.assertEqual(r[0], p.lower().rstrip("."))
        for w in hc.BENIGN_WORDS:
            r = voice.clean_words("stay\n%s" % w)
            self.assertIsNotNone(r, w)
            self.assertEqual(r[1], [w])
        for d in hc.BENIGN_DOSSIER:
            self.assertIsNotNone(voice.clean_dossier(d), d)

    def test_typography_is_tidied_not_rejected(self):
        phone, words = voice.clean_words(u"1. “stay” — closer!\n- **SUBJECT LINGERS**\nLine 3: KEEPS STILL")
        self.assertEqual(phone, "stay - closer")
        self.assertEqual(words, ["SUBJECT LINGERS", "KEEPS STILL"])

    def test_leading_numbers_are_kept(self):
        _p, words = voice.clean_words("stay\n37 SECONDS STILL\n2. HOLDS DEVICE CLOSE")
        self.assertEqual(words, ["37 SECONDS STILL", "HOLDS DEVICE CLOSE"])


def _visitor_text():
    """Every canned line a visitor can read, outside the model."""
    out = []
    for pool in hooks.LINES.values():
        out += pool
    with open(os.path.join(ROOT, "profiler", "prompts.json")) as f:
        for p in json.load(f)["prompts"]:
            out += [p["ask"]] + p["options"]
    out += list(reveal.SCENE_NAMES.values()) + list(ocean.LABELS.values())
    for tpl in reveal.DESCRIBE.values():
        out.append(tpl.format(raw=0.5))
    for name in sim.ARCHETYPES:
        _profiles, rv = sim.run(name, seed=3)
        out += rv["data"]["lines"] + [rv["data"]["label"]]
    with open(os.path.join(ROOT, "pi", "config", "default.toml"), "rb") as f:
        for line in tomllib.load(f).get("phone_lines", {}).values():
            out += [v for v in line.values() if isinstance(v, str)]
            out += [o for o in line.get("options", [])]
    for rel, names in (("visuals/engine.py", ("LEX_TENDER", "LEX_COLD", "LEX_JEST", "LEX_IDLE")),
                       ("pi/showengine/outputs/fallback_visuals.py", ("WORDS",)),
                       ("phone/n900/screens.py", ("CONSENT_LINES",))):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in names for t in node.targets):
                out += ast.literal_eval(node.value)
    return out


class TestCannedText(unittest.TestCase):
    def test_canned_text_obeys_the_same_rules(self):
        lines = _visitor_text()
        self.assertGreater(len(lines), 100)
        bad = []
        for line in lines:
            # "leak" is about the model echoing its prompt; canned text may say "segment:"
            hits = [h for h in voice.problems(line) if h != "leak"]
            if hits:
                bad.append((line, hits))
        self.assertEqual(bad, [])

    def test_system_prompt_states_the_rules(self):
        v = voice.VOICE.lower()
        for rule in ("rules:", "never who they are or how they feel", "age, gender, race",
                     "emotions", "artist", "threaten", "emojis", "never mention these rules"):
            self.assertIn(rule, v)

    def test_prompts_never_carry_internal_scene_names(self):
        prof = sim.run("performer", seed=1)[0][-1]["data"]
        for hook in hooks.HOOKS:
            p = dict(prof, hook=hook)
            blob = json.dumps(voice.words_messages(p)[1:] + voice.dossier_messages(p)[1:]).lower()
            for internal in ("scrawl", "inverted", "meat", "crown", "bruise"):
                self.assertNotIn(internal, blob, hook)


# --------------------------------------------------------- fake llama-server --

def _answer(text):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()


class FakeLlama(BaseHTTPRequestHandler):
    mode = "ok"
    text = "hold me closer\nSUBJECT LINGERS\nKEEPS STILL"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        m = self.server.mode
        try:
            if m == "hang":
                time.sleep(60)
                return
            if m == "close":
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if m == "500":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"internal error")
                return
            body = {"ok": _answer(self.server.text), "slow": _answer(self.server.text),
                    "badjson": b"{\"choices\": [", "notutf8": b"\xff\xfe\x00garbage\x80",
                    "null": json.dumps({"choices": [{"message": {"content": None}}]}).encode(),
                    "empty": json.dumps({"choices": []}).encode(),
                    "html": b"<html>502 Bad Gateway</html>",
                    "flood": _answer("stay " * 3000000)}.get(m, b"")
            if m == "slow":
                time.sleep(1.0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + (1000 if m == "drip" else 0)))
            self.end_headers()
            if m == "drip":  # a byte every 0.3 s, never finishing
                for _ in range(200):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.3)
                return
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class TestFakeLlamaServer(unittest.TestCase):
    TIMEOUT = 2.0

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        cls.srv.daemon_threads = True
        cls.srv.mode = "ok"
        cls.srv.text = FakeLlama.text
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.complete = staticmethod(http_complete(dict(
            DEFAULTS, url="http://127.0.0.1:%d/v1/chat/completions" % cls.srv.server_address[1],
            timeout=cls.TIMEOUT)))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, mode):
        self.srv.mode = mode
        t0 = time.monotonic()
        try:
            return self.complete([{"role": "user", "content": "x"}], 40), time.monotonic() - t0
        except Exception as e:  # what the worker catches
            return e, time.monotonic() - t0

    def test_good_answer(self):
        out, dt = self.call("ok")
        self.assertEqual(out, FakeLlama.text)
        self.assertLess(dt, 1.0)

    def test_slow_but_in_time(self):
        out, dt = self.call("slow")
        self.assertEqual(out, FakeLlama.text)

    def test_every_failure_raises_inside_the_deadline(self):
        for mode in ("hang", "drip", "close", "500", "badjson", "notutf8", "null", "empty",
                     "html", "flood"):
            out, dt = self.call(mode)
            self.assertIsInstance(out, Exception, mode)
            self.assertLess(dt, self.TIMEOUT + 1.5, "%s took %.1fs" % (mode, dt))

    def test_server_down(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        complete = http_complete(dict(DEFAULTS, url="http://127.0.0.1:%d/v1/chat/completions" % port,
                                      timeout=1.0))
        with self.assertRaises(OSError):
            complete([{"role": "user", "content": "x"}], 40)

    def test_hostile_answer_end_to_end_falls_back(self):
        o = Oracle()
        o.visitor_id = "v-test"
        self.srv.text = "you look nervous\nYOUNG WOMAN\nBаCON"
        try:
            text, _ = self.call("ok")
        finally:
            self.srv.text = FakeLlama.text
        self.assertIsNone(o.accept("words", "v-test", text))   # template text stays


if __name__ == "__main__":
    unittest.main()
