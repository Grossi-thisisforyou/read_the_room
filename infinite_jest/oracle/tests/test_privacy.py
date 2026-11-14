"""What the local model receives, and what the oracle prints when the model fails.

The oracle README: "The model gets only OCEAN numbers, confidences, the segment
label, the hook name and plain behaviour lines the wall already shows. It never
gets frames, audio, typed text or ids."
"""

import io
import json
import re
import sys
import threading
import time
import unittest
import http.server

from infinite_jest.oracle import oracle as oracle_mod
from infinite_jest.oracle import voice
from infinite_jest.profiler import create, sim


class FakeLlama:
    def __init__(self, fail=False):
        self.bodies = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.bodies.append(body)
                if fail:
                    self.send_response(500, "boom")
                    self.end_headers()
                    self.wfile.write(b"error for prompt: " + body)
                    return
                out = json.dumps({"choices": [{"message": {"content": "stay\nHOLDS STILL\nLEANS IN"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def profiles_with_typing():
    """A live profiler run where the visitor typed a sentinel and answered every prompt."""
    p = create({"seed": 3})
    p.on_visit({"visitor_id": "v-abcd", "phase": "approach"}, 0.0)
    out = []
    t = 0.0
    for i in range(240):
        t += 0.25
        r = p.on_sensor({"kind": "phone", "held": True, "presence": 0.9, "motion": 0.5,
                         "audio": {"level": 0.5, "voiced": i % 3 == 0}}, t)
        if i == 20:
            p.on_sensor({"kind": "keys", "text": "SENTINEL-ORACLE-TYPED my secret"}, t)
        if i in (30, 60, 90, 120):
            pid, opt = [("closer", "look closer"), ("upside", "upside down"),
                        ("seen", "forgotten"), ("secret", "tell")][i // 30 - 1]
            p.on_sensor({"kind": "choice", "prompt_id": pid, "option": opt, "latency_ms": 900}, t)
        if r and r.get("type") == "profile":
            out.append(r)
    return out


class TestWhatTheModelGets(unittest.TestCase):
    def test_every_prompt_is_numbers_labels_and_behaviour_only(self):
        profs = profiles_with_typing()
        for name in sim.ARCHETYPES:
            profs += [m["data"] for m in sim.run(name, seed=4)[0]]
        self.assertGreater(len(profs), 50)
        for prof in profs:
            for msgs in (voice.words_messages(prof), voice.dossier_messages(prof)):
                blob = json.dumps(msgs)
                self.assertNotIn(prof["visitor_id"], blob)
                self.assertNotIn("SENTINEL", blob)
                self.assertNotIn("secret", msgs[1]["content"].lower().replace("never tell", ""))
                self.assertFalse(re.search(r"[A-Za-z0-9+/]{60,}", blob))
                self.assertEqual([m["role"] for m in msgs], ["system", "user"])

    def test_oracle_jobs_through_http_carry_no_ids(self):
        llama = FakeLlama()
        try:
            o = oracle_mod.Oracle({"url": llama.url})
            complete = oracle_mod.http_complete(dict(o.cfg))
            for prof in profiles_with_typing():
                o.handle({"type": "state", "ts": 1, "data": {"visitor_id": "v-abcd", "phase": "profiling"}})
                for kind, vid, msgs, n in o.handle({"type": "profile", "ts": prof.get("seconds", 0) * 10,
                                                   "data": prof}):
                    complete(msgs, n)
            o.handle({"type": "state", "ts": 1, "data": {"visitor_id": "v-abcd", "phase": "hook"}})
            self.assertTrue(llama.bodies)
            for b in llama.bodies:
                self.assertNotIn(b"v-abcd", b)
                self.assertNotIn(b"SENTINEL", b)
                self.assertEqual(set(json.loads(b)), {"model", "messages", "max_tokens", "temperature", "stream"})
        finally:
            llama.close()


class TestErrorPathPrintsNoPrompt(unittest.TestCase):
    def test_run_forever_debug_output_when_the_model_fails(self):
        """llama-server answers 500 and echoes the prompt; the oracle's --debug line must not."""
        from websockets.sync.server import serve

        prof = profiles_with_typing()[-1]
        llama = FakeLlama(fail=True)
        sent = threading.Event()

        def handler(ws):
            ws.recv()  # hello
            ws.send(json.dumps({"type": "state", "ts": 1, "data": {"visitor_id": "v-abcd", "phase": "profiling"}}))
            ws.send(json.dumps({"type": "profile", "ts": 2, "data": prof}))
            ws.send(json.dumps({"type": "state", "ts": 3, "data": {"visitor_id": "v-abcd", "phase": "hook"}}))
            sent.set()
            try:
                for _ in ws:
                    pass
            except Exception:
                pass

        server = serve(handler, "127.0.0.1", 0)
        port = server.socket.getsockname()[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        buf = io.StringIO()
        real_err, real_sleep = sys.stderr, oracle_mod.time.sleep

        def stop_sleep(s):
            raise SystemExit  # end run_forever's reconnect loop quietly

        sys.stderr = buf
        oracle_mod.time.sleep = stop_sleep
        try:
            t = threading.Thread(target=oracle_mod.run_forever,
                                 args=("ws://127.0.0.1:%d/ws" % port, {"url": llama.url}, True), daemon=True)
            t.start()
            deadline = time.time() + 10
            while time.time() < deadline and (len(llama.bodies) < 2 or "model failed" not in buf.getvalue()):
                real_sleep(0.05)
            real_sleep(0.3)
        finally:
            server.shutdown()
            t.join(5)
            sys.stderr = real_err
            oracle_mod.time.sleep = real_sleep
            llama.close()
        out = buf.getvalue()
        self.assertIn("model failed", out)
        self.assertGreaterEqual(len(llama.bodies), 1)
        for leak in ("Visitor profile", "Observed", "Openness", "v-abcd", "error for prompt"):
            self.assertNotIn(leak, out)


if __name__ == "__main__":
    unittest.main()
