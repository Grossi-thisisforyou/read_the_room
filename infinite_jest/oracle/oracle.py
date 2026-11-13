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

import json
import queue
import sys
import threading
import time
import urllib.request

from . import voice

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


def http_complete(cfg):
    def complete(messages, max_tokens):
        body = json.dumps({"model": cfg["model"], "messages": messages, "max_tokens": max_tokens,
                           "temperature": cfg["temperature"], "stream": False}).encode()
        req = urllib.request.Request(cfg["url"], body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
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
