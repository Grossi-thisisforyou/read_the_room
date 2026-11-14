"""The oracle: the local language model's seat in the show.

Reads `state` and `profile`, asks a small Qwen under llama.cpp's llama-server
(127.0.0.1:8080, OpenAI-style chat) for short text, and sends

    {"type": "oracle", "data": {"visitor_id", "words": [...], "phone_text": "...",
                                "dossier": [...]}}

Two requests per visitor at most at a time, each capped at ~40-70 tokens so it
lands within a few seconds on a Pi 5:
- words + phone_text: when a visitor's profile first becomes readable and
  whenever the hook changes (at most every 8 s);
- dossier: when the engine enters the hook phase, so it is ready by release.

Model calls run on a worker thread and never block. Results for a visitor that
was wiped meanwhile are thrown away. If the model is missing, slow or says
something it must not, nothing is sent and the engine keeps the profiler's
template text.
"""

import http.client
import json
import queue
import socket
import sys
import threading
import time
import urllib.parse

from . import voice as _fallback_voice

try:  # the shared text corpus has the reviewed prompts and a stricter guard
    from infinite_jest.text import oracle_prompt as _tp
    from infinite_jest.text import style as _ts

    def _both_words(text):
        # Both guards must pass: voice.py's allowlist (hostile-tested) and text's style rules.
        a = _fallback_voice.clean_words(text)
        return a if a and _ts.clean_words(text) else None

    def _both_dossier(text):
        a = _fallback_voice.clean_dossier(text)
        return a if a and _ts.clean_dossier(text) else None

    class voice:  # noqa: N801 - same surface as oracle/voice.py
        words_messages = staticmethod(_tp.words_messages)
        dossier_messages = staticmethod(_tp.dossier_messages)
        clean_words = staticmethod(_both_words)
        clean_dossier = staticmethod(_both_dossier)
except ImportError:
    voice = _fallback_voice

DEFAULTS = {
    "url": "http://127.0.0.1:8080/v1/chat/completions",
    "model": "qwen2.5-1.5b-instruct",   # whatever llama-server loaded; name is informational
    "timeout": 15.0,
    "words_tokens": 40,
    "dossier_tokens": 70,
    "temperature": 0.8,
    "min_confidence": 0.3,
    "words_every": 8.0,
}


MAX_ANSWER_BYTES = 65536   # a 70-token answer is ~1 KB; anything bigger is broken


def _abort(held):
    for sock in held:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def http_complete(cfg):
    u = urllib.parse.urlsplit(cfg["url"])
    host, port, path = u.hostname or "127.0.0.1", u.port or 80, u.path or "/"

    def complete(messages, max_tokens):
        body = json.dumps({"model": cfg["model"], "messages": messages, "max_tokens": max_tokens,
                           "temperature": cfg["temperature"], "stream": False}).encode()
        conn = http.client.HTTPConnection(host, port, timeout=cfg["timeout"])
        # A socket timeout only bounds each read, so a server that trickles a byte
        # now and then would hold the worker (and every later visitor) forever.
        # The watchdog shuts the socket at the deadline, whatever it is doing.
        # (http.client hands the socket to the response and forgets it, so hold it here.)
        held = []
        watchdog = threading.Timer(cfg["timeout"], _abort, (held,))
        watchdog.daemon = True
        t0 = time.monotonic()
        watchdog.start()
        try:
            conn.connect()
            held.append(conn.sock)
            conn.request("POST", path, body, {"Content-Type": "application/json"})
            r = conn.getresponse()
            if r.status != 200:
                raise OSError("llama-server answered HTTP %d" % r.status)
            raw = r.read(MAX_ANSWER_BYTES + 1)
            if time.monotonic() - t0 >= cfg["timeout"]:
                raise TimeoutError("llama-server too slow")
            if len(raw) > MAX_ANSWER_BYTES:
                raise ValueError("llama-server answer too long")
            content = json.loads(raw.decode("utf-8"))["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("llama-server answer has no text")
            return content
        finally:
            watchdog.cancel()
            conn.close()
    return complete


class Oracle:
    """Pure decision logic; call handle(msg) and run the returned jobs."""

    def __init__(self, config=None):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(config or {})
        self.reset()

    def reset(self):
        self.visitor_id = None
        self.last_hook = None
        self.last_words_t = None
        self.dossier_asked = False
        self.profile = None
        self.result = {}

    def handle(self, m):
        """Return a list of jobs: (kind, visitor_id, messages, max_tokens)."""
        t, d = m.get("type"), m.get("data") or {}
        ts = float(m.get("ts") or time.time())
        if t == "wipe" or (t == "state" and d.get("phase") in ("idle", "wipe")):
            self.reset()
            return []
        if t == "state":
            vid = d.get("visitor_id")
            if vid and vid != self.visitor_id:
                self.reset()
                self.visitor_id = vid
            if d.get("phase") == "hook" and not self.dossier_asked and self.profile:
                self.dossier_asked = True
                return [("dossier", self.visitor_id, voice.dossier_messages(self.profile),
                         self.cfg["dossier_tokens"])]
            return []
        if t == "profile" and "ocean" in d and d.get("phase") not in ("opted_out", "ended"):
            vid = d.get("visitor_id") or self.visitor_id
            if vid != self.visitor_id:
                self.reset()
                self.visitor_id = vid
            self.profile = d
            if d.get("confidence", 0) < self.cfg["min_confidence"]:
                return []
            if d.get("hook") != self.last_hook and (
                    self.last_words_t is None or ts - self.last_words_t >= self.cfg["words_every"]):
                self.last_hook = d.get("hook")
                self.last_words_t = ts
                return [("words", vid, voice.words_messages(d), self.cfg["words_tokens"])]
        if t == "profile" and d.get("phase") == "opted_out":
            self.reset()
        return []

    def accept(self, kind, visitor_id, text, ts=None):
        """Turn model text into an oracle message, or None."""
        if visitor_id != self.visitor_id or visitor_id is None:
            return None  # wiped or moved on meanwhile
        if kind == "words":
            r = voice.clean_words(text)
            if not r:
                return None
            self.result["phone_text"], self.result["words"] = r
        else:
            r = voice.clean_dossier(text)
            if not r:
                return None
            self.result["dossier"] = r
        data = {"visitor_id": visitor_id, "words": [], "phone_text": "", "dossier": []}
        data.update(self.result)
        return {"type": "oracle", "ts": ts or time.time(), "data": data}


def run_forever(url, config=None, debug=False):
    from infinite_jest.profiler.ws_client import MiniWS
    cfg = dict(DEFAULTS)
    cfg.update(config or {})
    complete = http_complete(cfg)
    oracle = Oracle(cfg)
    jobs = queue.Queue()
    lock = threading.Lock()
    conn = {"ws": None}

    def worker():
        while True:
            kind, vid, messages, max_tokens = jobs.get()
            t0 = time.time()
            try:
                text = complete(messages, max_tokens)
            except Exception as e:  # model down or slow: template text stays
                if debug:
                    print("oracle: model failed:", e, file=sys.stderr)
                continue
            with lock:
                out = oracle.accept(kind, vid, text)
                if out and conn["ws"]:
                    try:
                        conn["ws"].send(json.dumps(out))
                    except OSError:
                        pass
            if debug:
                print("oracle: {} in {:.1f}s -> {}".format(kind, time.time() - t0,
                                                         "sent" if out else "dropped"), file=sys.stderr)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            ws = MiniWS(url)
            with lock:
                conn["ws"] = ws
                ws.send(json.dumps({"type": "hello", "ts": time.time(),
                                    "data": {"role": "oracle", "name": "infinite_jest.oracle",
                                             "version": "1.0"}}))
            print("oracle: connected to", url, file=sys.stderr)
            while True:
                try:
                    m = json.loads(ws.recv())
                except ValueError:
                    continue
                with lock:
                    new = oracle.handle(m)
                for job in new:
                    while jobs.qsize() > 1:  # stale requests are useless; keep it fresh
                        try:
                            jobs.get_nowait()
                        except queue.Empty:
                            break
                    jobs.put(job)
        except KeyboardInterrupt:
            return 0
        except (OSError, ConnectionError) as e:
            with lock:
                conn["ws"] = None
                oracle.reset()
            print("oracle: {} - retrying in 2 s".format(e), file=sys.stderr)
            time.sleep(2)
