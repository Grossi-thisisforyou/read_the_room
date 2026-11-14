"""Privacy claims, checked end to end with simulated visits.

These tests drive the whole Pi side the way the show runs it: the engine with
the real in-process profiler, the real visuals module (headless), the audio
synth, and the oracle talking HTTP to a fake llama-server. Each visit carries
sentinel values (a typed text, a distinctive camera frame pattern, choice
answers). The tests then check the promises in profiler/DATA_HANDLING.md:

- nothing about a visitor reaches disk or the logs;
- the wipe really leaves nothing behind in memory;
- the model never receives frames or typed text;
- covering the phone (opt-out) stops the profiling and clears the wall.
"""
from __future__ import annotations

import base64
import builtins
import gc
import http.server
import io
import json
import logging
import os
import pickle
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import types
import wave

import numpy as np
import pygame
import pytest

from showengine import config, engine as engine_mod, plugins, protocol as P
from showengine.engine import Engine

plugins._ensure_path()

from infinite_jest import profiler as profiler_mod  # noqa: E402
from infinite_jest import visuals as visuals_mod  # noqa: E402
from infinite_jest.audio.synth import TechnoSynth  # noqa: E402
from infinite_jest.oracle.oracle import Oracle, http_complete  # noqa: E402

W, H = 160, 120
# A frame background nobody's camera would produce: a 16-byte tile, repeated.
TILE = bytes([0x13, 0x37, 0xC0, 0xDE, 0x51, 0x8A, 0x2F, 0x99, 0x04, 0xE7, 0x6B, 0xB2, 0x3D, 0x75, 0xA8, 0x1C])
TILE_RGB = bytes(b for b in TILE for _ in range(3))          # the engine repeats gray into RGB
TILE_B64 = base64.b64encode(TILE * 3).decode()               # 48 bytes -> aligned base64 run
PROMPTS = {"closer": "look closer", "upside": "upside down", "seen": "forgotten"}

LLAMA_ANSWER = "stay a little longer\nHOLDS DEVICE CLOSE\nTILTS OFTEN\nLINGERS NEAR"


# ------------------------------------------------------------------ fakes
class FakeClock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class FakeLlama:
    """A llama-server stand-in on 127.0.0.1 that records every request body."""

    def __init__(self):
        self.bodies: list[bytes] = []
        self.fail = False
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.bodies.append(body)
                if outer.fail:
                    # a hostile server echoes the prompt back in its error body
                    self.send_response(500, "boom")
                    self.end_headers()
                    self.wfile.write(b"error for prompt: " + body)
                    return
                out = json.dumps({"choices": [{"message": {"content": LLAMA_ANSWER}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class DiskWatch:
    """Records every way the process could put bytes on disk or hand them to a child."""

    WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def __init__(self, monkeypatch):
        self.events: list[tuple[str, str]] = []
        mp = monkeypatch
        real_open, real_os_open, real_write = builtins.open, os.open, os.write

        def rec(kind, what):
            self.events.append((kind, str(what)[:2000]))

        def fake_open(file, mode="r", *a, **kw):
            if any(c in str(mode) for c in "wax+"):
                rec("open", "%s mode=%s" % (file, mode))
            return real_open(file, mode, *a, **kw)

        def fake_os_open(path, flags, *a, **kw):
            if flags & self.WRITE_FLAGS:
                rec("os.open", path)
            return real_os_open(path, flags, *a, **kw)

        def fake_write(fd, data):
            if fd > 2:
                rec("os.write", bytes(data)[:2000])
            return real_write(fd, data)

        mp.setattr(builtins, "open", fake_open)
        mp.setattr(io, "open", fake_open)
        mp.setattr(os, "open", fake_os_open)
        mp.setattr(os, "write", fake_write)

        def recorder(kind, real):
            def f(*a, **kw):
                rec(kind, a)
                return real(*a, **kw)
            return f

        for mod, names in ((tempfile, ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile",
                                       "SpooledTemporaryFile", "TemporaryDirectory")),
                           (shutil, ("copy", "copy2", "copyfile", "copytree", "move")),
                           (os, ("replace", "rename", "system", "popen", "mkdir", "makedirs")),
                           (sqlite3, ("connect",)), (pickle, ("dump",)), (np, ("save", "savez", "savetxt")),
                           (pygame.image, ("save",))):
            for n in names:
                if hasattr(mod, n):
                    mp.setattr(mod, n, recorder("%s.%s" % (mod.__name__, n), getattr(mod, n)))

        real_wave_open = wave.open

        def fake_wave_open(f, mode=None):
            if mode and "w" in mode:
                rec("wave.open", f)
            return real_wave_open(f, mode)
        mp.setattr(wave, "open", fake_wave_open)

        real_popen_init = subprocess.Popen.__init__

        def fake_popen_init(self_, args, *a, **kw):
            rec("subprocess", args)
            return real_popen_init(self_, args, *a, **kw)
        mp.setattr(subprocess.Popen, "__init__", fake_popen_init)


class LogCatch(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:
            self.lines.append(str(record.msg))
        if record.exc_info:
            self.lines.append(logging.Formatter().formatException(record.exc_info))


# ------------------------------------------------------------------ the rig
def make_frame(t: float) -> bytes:
    """Distinctive background with a bright moving blob (so the camera sees someone)."""
    px = bytearray(TILE * (W * H // len(TILE)))
    cx = int(W / 2 + 40 * np.sin(t * 0.8))
    for y in range(40, 90):
        row = y * W
        for x in range(max(0, cx - 18), min(W, cx + 18)):
            px[row + x] = 250
    return bytes(px)


class Rig:
    """Engine + in-process profiler + real visuals + oracle over HTTP to a fake llama-server."""

    def __init__(self, monkeypatch, with_profiler=True, overrides=None):
        self.clock = FakeClock()
        fake_time = types.SimpleNamespace(time=self.clock, monotonic=self.clock)
        monkeypatch.setattr(engine_mod, "time", fake_time)   # the engine stamps profiler calls with time.time()
        self.llama = FakeLlama()
        self.oracle = Oracle({"url": self.llama.url, "timeout": 5})
        self.complete = http_complete(dict(self.oracle.cfg))
        self.jobs: list = []
        self.sent: list[tuple[dict, set | None]] = []
        self.surface = pygame.Surface((320, 180))
        self.visuals = visuals_mod.create((320, 180), {"busy_file": None})
        self.synth = TechnoSynth(seed=0)
        self.profiler = profiler_mod.create({"seed": 1}) if with_profiler else None
        cfg = config.load(None, dict({"mode": "handheld"}, **(overrides or {})))
        self.engine = Engine(cfg, emit=self.emit, clock=self.clock, visuals=self.visuals,
                             audio=None, profiler=self.profiler)
        self.vids: set[str] = set()
        self.oracle_errors: list[str] = []
        self.render = True

    def emit(self, msg, roles):
        self.sent.append((msg, roles))
        if roles is None or "oracle" in roles:
            self.jobs.extend(self.oracle.handle(json.loads(P.encode(msg))))
        if msg["type"] == P.STATE:
            self.synth.set_state(msg["data"])
            if msg["data"].get("visitor_id"):
                self.vids.add(msg["data"]["visitor_id"])
        if msg["type"] == P.WIPE:
            self.synth.wipe()

    def run_jobs(self):
        jobs, self.jobs = self.jobs, []
        for kind, vid, messages, n in jobs:
            try:
                text = self.complete(messages, n)
            except Exception as e:   # what run_forever's worker would print with --debug
                self.oracle_errors.append("oracle: model failed: %s" % e)
                continue
            out = self.oracle.accept(kind, vid, text, ts=self.clock.t)
            if out:
                self.engine.handle(out, "oracle")

    def phone(self, data):
        self.engine.handle(P.make(P.SENSOR, data, ts=self.clock.t), "phone")

    def step(self, dt=0.1, render=True):
        self.clock.t += dt
        self.engine.tick(self.clock.t)
        if render and self.render:
            self.visuals.render(self.surface, dt)
        n = 0
        while self.synth.wiping and n < 200:    # the audio process keeps rendering through its fade-out
            self.synth.render_block()
            n += 1
        self.run_jobs()

    def visit(self, keys_text, seconds=55.0, optout_at=None, after=20.0):
        """One visitor: picks the phone up, tilts it, talks, answers, types, puts it down."""
        t0 = self.clock.t
        frame_t = -1.0
        events = {6.0: {"kind": "touch", "x": 0.3, "y": 0.6, "down": True},
                  9.0: {"kind": "choice", "prompt_id": "closer", "option": PROMPTS["closer"], "latency_ms": 900},
                  13.0: {"kind": "keys", "text": keys_text, "typing_ms": 4000, "backspaces": 2},
                  16.0: {"kind": "choice", "prompt_id": "upside", "option": PROMPTS["upside"], "latency_ms": 700},
                  21.0: {"kind": "keys", "text": keys_text + " again", "typing_ms": 3000},
                  24.0: {"kind": "choice", "prompt_id": "seen", "option": PROMPTS["seen"], "latency_ms": 1500}}
        opted = False
        while self.clock.t - t0 < seconds:
            el = self.clock.t - t0
            if optout_at is not None and el >= optout_at and not opted:
                # what the N900 agent sends once the proximity sensor was covered for 3 s
                for k in range(30):
                    self.phone({"kind": "phone", "held": True, "proximity": {"near": True}})
                    self.step()
                self.phone({"kind": "optout"})
                opted = True
            if opted:
                self.phone({"kind": "phone", "optout": True})
            else:
                self.phone({"kind": "phone", "held": True, "presence": 0.9, "motion": 0.4,
                            "audio": {"level": 0.3 + 0.2 * np.sin(el), "voiced": int(el) % 3 == 0},
                            "loudness": 0.4, "tilt": {"alpha": 0, "beta": 20 * np.sin(el), "gamma": 15},
                            "accel": {"x": 0.1, "y": 0.2, "z": 0.95}, "shake": 0.1, "light": 0.5,
                            "proximity": {"near": False}, "slide": el > 12})
                for at in [a for a in events if el - 0.1 < a <= el]:
                    self.phone(dict(events[at]))
                if el - frame_t >= 0.25:
                    frame_t = el
                    self.engine.handle(P.make(P.FRAME, {"w": W, "h": H, "fmt": "gray8",
                                                        "b64": base64.b64encode(make_frame(el)).decode()},
                                              ts=self.clock.t), "phone")
            self.step()
        # put down: the phone keeps reporting, nobody is there
        t1 = self.clock.t
        while self.clock.t - t1 < after:
            self.phone({"kind": "phone", "held": False, "presence": 0.0, "motion": 0.0,
                        "audio": {"level": 0.0, "voiced": False}, "proximity": {"near": False}})
            self.step()

    def close(self):
        self.llama.close()


@pytest.fixture
def rig(monkeypatch):
    r = Rig(monkeypatch)
    yield r
    r.close()


@pytest.fixture
def logs():
    h = LogCatch()
    root = logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    saved = {}
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger):
            saved[name] = lg.level
            lg.setLevel(logging.DEBUG)
    yield h
    root.removeHandler(h)
    root.setLevel(old)
    for name, lvl in saved.items():
        logging.getLogger(name).setLevel(lvl)


def sentinel():
    # built at run time so the value never sits in this module's constants
    return "SENTINEL-KEYS-" + secrets.token_hex(3).upper()


# ------------------------------------------------------------------ memory scan
def scan_memory(needles_str, needles_bytes, ignore=()):
    """Every live str/bytes/array reachable from a gc-tracked container that holds a needle.

    Returns a list of (holder type, holder repr snippet, found) tuples.
    """
    gc.collect()
    ignore_ids = {id(x) for x in ignore} | {id(needles_str), id(needles_bytes)}
    hits = []
    seen = set()
    for holder in gc.get_objects():
        if id(holder) in ignore_ids or isinstance(holder, types.FrameType):
            continue
        for obj in gc.get_referents(holder):
            if id(obj) in seen or id(obj) in ignore_ids:
                continue
            found = None
            if isinstance(obj, str):
                if len(obj) < 3 or len(obj) > 2_000_000:
                    continue
                found = next((n for n in needles_str if n in obj), None)
            elif isinstance(obj, (bytes, bytearray, memoryview)):
                b = bytes(obj)
                found = next((repr(n[:8]) for n in needles_bytes if n in b), None)
            elif isinstance(obj, np.ndarray) and obj.size >= 16:
                arr = obj
                if arr.dtype != np.uint8:
                    if not np.issubdtype(arr.dtype, np.number):
                        continue
                    if not np.all(np.mod(arr, 1) == 0) or arr.min() < 0 or arr.max() > 255:
                        continue
                    arr = arr.astype(np.uint8)
                b = np.ascontiguousarray(arr).tobytes()
                bt = np.ascontiguousarray(arr.T).tobytes() if arr.ndim >= 2 else b
                found = next((repr(n[:8]) for n in needles_bytes if n in b or n in bt), None)
            elif isinstance(obj, list) and len(obj) >= 16 and all(type(v) is int for v in obj[:16]):
                try:
                    b = bytes(v for v in obj if 0 <= v < 256)
                except (TypeError, ValueError):
                    continue
                found = next((repr(n[:8]) for n in needles_bytes if n in b), None)
            if found is not None:
                seen.add(id(obj))
                hits.append((type(holder).__name__, repr(holder)[:160], found))
    return hits


# ================================================================== 1. disk + logs
def test_full_visits_write_nothing_and_log_nothing_about_the_visitor(rig, logs, monkeypatch, capfd):
    watch = DiskWatch(monkeypatch)
    keys = [sentinel() for _ in range(3)]
    for k in keys:
        rig.visit(k)
    out, err = capfd.readouterr()
    assert rig.vids, "the rig never started a visit"
    assert len(rig.llama.bodies) >= 3, "the oracle never reached the model"
    # disk: no write of any kind (visuals busy_file is turned off in the rig)
    assert watch.events == [], watch.events[:10]
    text = "\n".join(logs.lines) + out + err
    for needle in keys + sorted(rig.vids) + [TILE_B64]:
        assert needle not in text, "found %r in logs/stdout" % needle
    assert "ocean" not in text.lower() and "'O':" not in text


def test_visuals_busy_flag_file_holds_no_visitor_data(monkeypatch, tmp_path):
    """The one file the show touches during a visit is an empty 'busy' marker."""
    busy = tmp_path / "busy"
    r = Rig(monkeypatch)
    try:
        r.visuals.busy_file = str(busy)
        watch = DiskWatch(monkeypatch)
        r.visit(sentinel(), seconds=20)
        paths = {e[1].split(" mode=")[0] for e in watch.events if e[0] == "open"}
        assert paths <= {str(busy)}, watch.events
        assert not any(e[0] in ("os.write",) for e in watch.events)
        assert not busy.exists() or busy.read_bytes() == b""
    finally:
        r.close()


def test_oracle_error_path_does_not_leak_the_prompt(rig, logs, capfd):
    """llama-server failing (and echoing the prompt in its error body) must not put the prompt in a log."""
    rig.render = False
    rig.llama.fail = True
    rig.visit(sentinel(), seconds=40)
    assert rig.oracle_errors, "the model should have been asked and failed"
    for e in rig.oracle_errors:
        assert "Observed" not in e and "Visitor profile" not in e and "OPENNESS" not in e.upper(), e
    out, err = capfd.readouterr()
    assert "Visitor profile" not in "\n".join(logs.lines) + out + err


# ================================================================== 2. the wipe
def test_wipe_leaves_no_sentinel_frame_or_visitor_id_in_memory(rig):
    keys = sentinel()
    rig.visit(keys, after=30.0)       # put down long enough for release -> wipe -> idle
    assert rig.engine.machine.phase == "idle"
    for _ in range(40):               # the wall keeps drawing in idle
        rig.step()
    vids = sorted(rig.vids)
    # the last wiped id is kept on purpose to stamp the wipe message; drop that one known holder
    rig.engine.machine.last_wiped_id = None
    rig.sent.clear()
    rig.llama.bodies.clear()
    needles_s = [keys, TILE_B64] + vids
    needles_b = [TILE, TILE_RGB, TILE[::2] * 2]   # [::2]: the profiler samples every 2nd pixel
    hits = scan_memory(needles_s, needles_b, ignore=(rig.vids, globals(), vids))
    assert hits == [], "\n".join(map(str, hits[:20]))


def test_wipe_clears_each_module(rig):
    rig.visit(sentinel(), after=30.0)
    for _ in range(40):
        rig.step()
    e, p, v, o, s = rig.engine, rig.profiler, rig.visuals, rig.oracle, rig.synth
    assert e.machine.visit.visitor_id is None and e.machine.visit.answers == []
    assert e.frames.prev is None
    assert p.visitor_id is None and p.last_profile is None and p.features.choices == [] \
        and p.features.keys_chars == 0 and p.vision.prev is None and p.bandit.history == []
    # the figure may hold the procedural stand-in body again, never the camera's pixels
    tile_vals = np.array(sorted(set(TILE)), np.float32)
    for name in ("gray", "bg", "trail"):
        a = getattr(v.fig, name)
        if a is not None:
            assert np.isin(a, tile_vals).mean() < 0.3, "visuals.fig.%s still holds the camera frame" % name
    assert o.visitor_id is None and o.profile is None and o.result == {}
    assert not s.visitor
    # the visitor's painted body strokes must not linger for the next visitor
    assert pygame.mask.from_surface(v.paint, 8).count() == 0, "paint layer still holds strokes"
    assert pygame.mask.from_surface(v.fig_surf, 8).count() == 0, "last figure still held"


def test_wall_and_phone_show_nothing_visitor_derived_after_wipe(rig):
    rig.visit(sentinel(), after=30.0)
    rig.sent.clear()
    for _ in range(30):
        rig.step()
    for m, _roles in rig.sent:
        d = m["data"]
        if m["type"] == P.STATE:
            assert d["visitor_id"] == "" and d["ocean"] is None and d["words"] == [] \
                and d["dossier"] == [] and d["reveal"] is None


# ================================================================== 3. opt-out
def test_optout_drops_the_profile_and_clears_the_wall(rig):
    keys = sentinel()
    rig.visit(keys, seconds=12.0, optout_at=11.0, after=0.0)
    rig.sent.clear()
    for _ in range(50):              # opted out, still holding the phone
        rig.phone({"kind": "phone", "optout": True})
        rig.step()
    v = rig.engine.machine.visit
    assert v.opted_out and v.ocean is None
    p = rig.profiler
    assert p.opted_out and p.features.choices == [] and p.vision.prev is None
    assert p.last_profile is None, "opted-out profile kept in profiler.last_profile"
    for m, roles in rig.sent:
        if m["type"] == P.PHONE:
            raise AssertionError("visitor-derived phone text after opt-out: %r" % m)


@pytest.mark.xfail(strict=True, reason="engine keeps oracle words / dossier on the wall after opt-out "
                                       "(VisitMachine.on_profile opt-out branch, visit.py)")
def test_optout_clears_oracle_words_from_the_wall(rig):
    rig.visit(sentinel(), seconds=12.0, optout_at=11.0, after=0.0)
    rig.sent.clear()
    for _ in range(50):
        rig.phone({"kind": "phone", "optout": True})
        rig.step()
    v = rig.engine.machine.visit
    assert v.oracle_words == [] and v.dossier == []
    for m, roles in rig.sent:
        if m["type"] == P.STATE:
            d = m["data"]
            assert d["ocean"] is None and d["words"] == [] and d["dossier"] == [] and d["reveal"] is None


def test_optout_frames_after_cover_reach_no_one(rig):
    """If a frame still arrives after opt-out, the profiler must ignore it."""
    rig.visit(sentinel(), seconds=12.0, optout_at=11.0, after=0.0)
    p = rig.profiler
    rig.engine.handle(P.make(P.FRAME, {"w": W, "h": H, "fmt": "gray8",
                                       "b64": base64.b64encode(make_frame(1.0)).decode()}, ts=rig.clock.t), "phone")
    assert p.vision.prev is None, "profiler analysed a frame after the visitor opted out"


@pytest.mark.xfail(strict=True, reason="engine keeps feeding frames after opt-out (engine tester owns engine.py)")
def test_optout_engine_stops_feeding_visuals_frames(rig):
    """Engine side (owner: engine tester). After opt-out the engine still hands camera frames to
    the visuals (mirror figure) and keeps its frame analyser running."""
    rig.visit(sentinel(), seconds=12.0, optout_at=11.0, after=0.0)
    rig.visuals.fig.wipe()
    rig.engine.handle(P.make(P.FRAME, {"w": W, "h": H, "fmt": "gray8",
                                       "b64": base64.b64encode(make_frame(1.0)).decode()}, ts=rig.clock.t), "phone")
    assert rig.visuals.fig.gray is None and rig.engine.frames.prev is None


@pytest.mark.xfail(strict=True, reason="engine ignores the phone's optout event without a profiler (engine.py)")
def test_optout_without_in_process_profiler_still_stops_profiling(monkeypatch):
    """Engine side (owner: engine tester). The engine only learns about opt-out from the profiler.
    With no profiler (import failed, or it runs as its own process and is down) the 'optout'
    event is ignored, the fallback guess drives the hook and the wall."""
    r = Rig(monkeypatch, with_profiler=False)
    try:
        r.visit(sentinel(), seconds=40.0, optout_at=4.0, after=0.0)
        assert r.engine.machine.visit.opted_out
    finally:
        r.close()


def test_typed_text_reaches_no_one_but_the_count(rig):
    """DATA_HANDLING: 'If a visitor types something, only the character count is used.'"""
    keys = sentinel()
    rig.visit(keys, seconds=30.0, after=0.0)
    for m, roles in rig.sent:
        if roles is not None and roles <= {"profiler"}:
            continue   # the raw sensor stream forwarded to an out-of-process profiler (RAM, localhost)
        assert keys not in P.encode(m), "typed text sent to %s: %s" % (roles, m["type"])
    assert keys not in json.dumps(rig.engine.state)


@pytest.mark.xfail(strict=True, reason="visit.answers keeps typed text (visit.py/engine.py)")
def test_engine_keeps_only_the_count_of_typed_text(rig):
    """Engine side (owner: engine tester). VisitMachine.on_answer stores up to 200 characters of
    each typed text in visit.answers until the wipe, and nothing reads it. The school note says
    only the character count is used."""
    keys = sentinel()
    rig.visit(keys, seconds=30.0, after=0.0)
    assert not any(keys in a for a in rig.engine.machine.visit.answers)


# ================================================================== 4. what the model sees
def test_model_never_receives_frames_typed_text_or_ids(rig):
    rig.render = False
    keys = [sentinel() for _ in range(4)]
    for k in keys:
        rig.visit(k, seconds=60.0)
    assert len(rig.llama.bodies) >= 6
    allowed_roles = {"system", "user"}
    for raw in rig.llama.bodies:
        body = raw.decode()
        for k in keys:
            assert k not in body
        for vid in rig.vids:
            assert vid not in body
        assert TILE_B64 not in body and "b64" not in body and "base64" not in body
        req = json.loads(body)
        assert set(req) == {"model", "messages", "max_tokens", "temperature", "stream"}
        assert {m["role"] for m in req["messages"]} <= allowed_roles
        user = req["messages"][-1]["content"]
        # long runs of base64-looking characters would mean image data
        import re
        assert not re.search(r"[A-Za-z0-9+/]{60,}", user), user
        assert "Visitor profile:" in user or "Observed:" in user
        # choice answers reach it only as the question asked, never the visitor's words
        assert "SENTINEL" not in user


# ================================================================== the instruments work
def test_instruments_catch_what_they_are_meant_to(monkeypatch, tmp_path):
    """Positive controls, so a green run above means something."""
    keys = sentinel()
    planted = {"held": "x" + keys + "y", "frame": np.frombuffer(TILE * 4, np.uint8).astype(np.float32),
               "sampled": list(TILE[::2] * 4)}
    hits = scan_memory([keys], [TILE, TILE[::2] * 2], ignore=(globals(),))
    found = {h[2] for h in hits if "held" in h[1] or "frame" in h[1] or "sampled" in h[1]}
    assert keys in found and repr(TILE[:8]) in found and repr((TILE[::2] * 2)[:8]) in found, hits
    del planted
    watch = DiskWatch(monkeypatch)
    with tempfile.NamedTemporaryFile(dir=tmp_path):
        pass
    with open(tmp_path / "x", "w") as f:
        f.write("1")
    kinds = {e[0] for e in watch.events}
    assert {"tempfile.NamedTemporaryFile", "open"} <= kinds, watch.events


def test_visuals_drop_the_painted_body_at_the_wipe(rig):
    """The stroke canvas is painted from the visitor's camera figure; it must not wait to fade out
    (a next visitor arriving right after the wipe would see it)."""
    rig.visit(sentinel(), seconds=50.0, after=0.0)
    for _ in range(400):
        rig.phone({"kind": "phone", "held": False, "presence": 0.0})
        rig.step()
        if rig.engine.machine.phase == "wipe":
            break
    assert rig.engine.machine.phase == "wipe"
    rig.step()
    v = rig.visuals
    assert pygame.mask.from_surface(v.paint, 1).count() == 0, "paint layer still holds strokes"
    assert pygame.mask.from_surface(v.fig_surf, 1).count() == 0, "last figure still held"


# ================================================================== opt-out, phone to wall
def _phone_agent(accel):
    """The real N900 agent with fake sysfs sensors and no threads."""
    import sys as _sys
    n900 = str(plugins.REPO_ROOT / "infinite_jest" / "phone" / "n900")
    if n900 not in _sys.path:
        _sys.path.insert(0, n900)
    from agent import Agent, DEFAULTS
    root = tempfile.mkdtemp()
    files = {"/sys/class/i2c-adapter/i2c-3/3-001d/coord": accel,
             "/sys/devices/platform/gpio-switch/proximity/state": "open",
             "/sys/devices/platform/gpio-switch/slide/state": "closed"}
    for p, v in files.items():
        os.makedirs(os.path.dirname(root + p))
        with open(root + p, "w") as f:
            f.write(v)
    a = Agent(dict(DEFAULTS, keep_awake=0, mic=0), fake=True, sysfs_root=root)
    return a, root


def test_optout_end_to_end_the_holder_is_not_read_again(rig):
    """Phone agent -> engine -> profiler -> wall, and engine -> phone. The visitor covers the eye,
    keeps holding the phone for a minute: no new visit is profiled, no frame is analysed."""
    a, root = _phone_agent("400 -600 -700")          # tilted in a hand: held
    prox = root + "/sys/devices/platform/gpio-switch/proximity/state"
    to_phone = []
    real_emit = rig.engine.emit

    def emit(msg, roles):
        real_emit(msg, roles)
        if roles is None or "phone" in roles:
            to_phone.append(json.loads(P.encode(msg)))
    rig.engine.emit = emit
    a.on_consent()

    def tick(seconds, cover=False):
        end = rig.clock.t + seconds
        while rig.clock.t < end:
            with open(prox, "w") as f:
                f.write("closed" if cover else "open")
            r = a.reading(rig.clock.t)
            rig.phone(r)
            while not a.events.empty():
                m = a.events.get_nowait()
                rig.engine.handle(P.make(m["type"], m["data"], ts=rig.clock.t), "phone")
            if not a.opted_out and int(rig.clock.t * 10) % 3 == 0:
                a.camera._on_frame(make_frame(rig.clock.t))
                frame, _ = a.camera.latest()
                rig.engine.handle(P.make(P.FRAME, {"w": W, "h": H, "fmt": "gray8",
                                                   "b64": base64.b64encode(frame).decode()},
                                         ts=rig.clock.t), "phone")
            for m in to_phone:
                a.handle(m)
            to_phone.clear()
            rig.step(render=False)

    tick(15.0)
    assert rig.engine.machine.phase in ("profiling", "hook")
    first = rig.engine.machine.visit.visitor_id
    tick(3.5, cover=True)
    assert a.opted_out and rig.engine.machine.visit.opted_out
    frames_before = rig.engine.stats["frame"]
    tick(60.0)                                         # still holding it, eye uncovered
    assert a.opted_out, "the phone stopped honouring the opt-out"
    assert rig.engine.stats["frame"] == frames_before, "frames analysed after the opt-out"
    later = rig.vids - {first}
    phases_with_new_ids = rig.engine.machine.phase
    assert not later or rig.profiler.features.phone_n == 0, \
        "a new visit profiled the opted-out holder (%s, phase %s)" % (later, phases_with_new_ids)
    assert rig.profiler.last_profile is None
