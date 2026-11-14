"""Live integration test: the real pieces over real sockets, in real time.

    python3 infinite_jest/integration/live_test.py              # ~3.5 minutes
    python3 infinite_jest/integration/live_test.py --fake-llm   # also a stand-in llama-server
    python3 infinite_jest/integration/live_test.py --quick      # shorter holds, no CPU window

What runs:
- the show engine (`python3 -m showengine`) at 1920x1080, SDL dummy video,
  real visuals, real audio (null sink, own process), real profiler in process;
- the oracle (`python3 -m infinite_jest.oracle --ws ...`). Without --fake-llm
  nothing answers on its model url, so it must fall back to the profiler's text;
- the real N900 agent (phone/n900/agent.py) in this process, reading a fake
  sysfs tree that the scenario rewrites to play a visitor;
- two recorders on /ws (roles "control" and "oracle") that log what each side gets;
- the UDP 8766 lane, the TCP 8767 JPEG lane, POST /api/sensor and /api/frame.

Scenario: phone flat (idle) -> picked up, tilted left/right, forward/back,
upside down, shaken, held still -> put down (visit ends, release, wipe) ->
second visit with the proximity sensor covered for 3+ s (opt-out) -> put down
-> the side lanes.

Nothing is written to disk except the temp config, the fake sysfs files and the
engine/oracle logs, all in a temp dir that is deleted at the end (--keep keeps
it). Camera frames are synthetic and stay in memory. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PI_DIR = os.path.join(REPO, "infinite_jest", "pi")
N900_DIR = os.path.join(REPO, "infinite_jest", "phone", "n900")
sys.path.insert(0, N900_DIR)

from agent import Agent, DEFAULTS as AGENT_DEFAULTS  # noqa: E402
from sensors import PATHS  # noqa: E402

HIDDEN = ("bacon", "baselitz", "basquiat", "crown", "skull", "©", "♛", "♔", "☠")
PHASE_ORDER = ["idle", "approach", "profiling", "hook", "release", "wipe", "idle"]


# --------------------------------------------------------------- results --
class Checks:
    def __init__(self):
        self.rows = []

    def __call__(self, ok, what, detail=""):
        self.rows.append((bool(ok), what, detail))
        print(("PASS " if ok else "FAIL ") + what + (("  [" + str(detail) + "]") if detail != "" else ""),
              flush=True)

    @property
    def failed(self):
        return [r for r in self.rows if not r[0]]


def log(*a):
    print("[%6.1f]" % (time.monotonic() - T0), *a, flush=True)


T0 = time.monotonic()


# ------------------------------------------------------------ fake sysfs --
class FakePhone:
    """Writes the N900's sysfs files; the real agent polls them at 20 Hz."""

    def __init__(self, root):
        self.root = root
        self.g = (0.0, 0.0, -1.0)    # gravity direction in g (flat, face up)
        self.noise = 0.0             # hand tremor amplitude in g
        self.shake = 0.0             # violent shaking amplitude in g
        self.near = False
        self.motion = False          # what the front camera sees: something moving
        self.voiced = False
        self.running = True
        for k, p in PATHS.items():
            os.makedirs(os.path.dirname(root + p), exist_ok=True)
        self._w("lux", "40")
        self._w("slide", "closed")
        self._w("lens", "open")
        self._w("battery", "83")
        self.write()

    def _w(self, key, value):
        tmp = self.root + PATHS[key] + ".tmp"
        with open(tmp, "w") as f:
            f.write(value)
        os.replace(tmp, self.root + PATHS[key])   # atomic: the agent never reads half a file

    def tilt(self, beta=0.0, gamma=0.0):
        """Set the gravity vector so the agent derives these angles (degrees)."""
        b, g = math.radians(beta), math.radians(gamma)
        gx = math.sin(g)
        r = math.cos(g)
        self.g = (gx, -r * math.sin(b), -r * math.cos(b))

    def write(self):
        n = self.noise + self.shake
        x, y, z = (v + random.uniform(-n, n) for v in self.g)
        self._w("accel", "%d %d %d" % (x * 1000, y * 1000, z * 1000))
        self._w("proximity", "closed" if self.near else "open")

    def loop(self):
        while self.running:
            self.write()
            time.sleep(0.03)


def make_gray(cx, w=160, h=120):
    out = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            out[row + x] = 200 if abs(x - cx) + abs(y - h // 2) < 25 else 30
    return bytes(out)


def install_fakes(agent, phone):
    """Swap the agent's synthetic camera/mic loops for ones the scenario controls."""
    still = make_gray(80)
    moving = [make_gray(c) for c in (40, 70, 100, 130)]

    def cam_loop():
        i = 0
        while phone.running:
            agent.camera._on_frame(moving[i % 4] if phone.motion else still)
            i += 1
            time.sleep(1.0 / agent.camera.fps)

    def mic_loop():
        while phone.running:
            agent.mic.level = 0.35 if phone.voiced else 0.02
            agent.mic.voiced = phone.voiced
            time.sleep(0.05)

    agent.camera._fake_loop = cam_loop
    agent.mic._fake_loop = mic_loop

    rx = {"phone": [], "wipe": 0, "state": 0, "types": {}}
    orig = agent.handle

    def handle(msg):
        t = msg.get("type")
        rx["types"][t] = rx["types"].get(t, 0) + 1
        if t == "phone":
            rx["phone"].append((time.monotonic(), msg.get("data") or {}))
        elif t == "wipe":
            rx["wipe"] += 1
        elif t == "state":
            rx["state"] += 1
        return orig(msg)

    agent.handle = handle
    sent = {"kinds": {}, "optout_periodic": 0, "frames": 0}
    orig_send = agent.send

    def send(msg, allow_udp=True):
        d = msg.get("data") or {}
        if msg.get("type") == "sensor":
            k = d.get("kind")
            sent["kinds"][k] = sent["kinds"].get(k, 0) + 1
            if k == "optout":
                sent["optout_t"] = time.monotonic()
            if k == "phone" and d.get("optout"):
                sent["optout_periodic"] += 1
        elif msg.get("type") == "frame":
            sent["frames"] += 1
        return orig_send(msg, allow_udp)

    agent.send = send
    return rx, sent


# ---------------------------------------------------------- fake llama ----
class FakeLLM(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        user = body.get("messages", [{}])[-1].get("content", "")
        if "Line 1" in user:
            text = "stay a little longer\nKEEPS STILL\nTILTS TOWARD LIGHT\nLINGERS AT EDGE"
        else:
            text = "you kept the device close\nyou turned it over twice\nyou stayed when asked to leave"
        out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


# ------------------------------------------------------------ cpu sampler --
def _ticks(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            parts = f.read().rsplit(")", 1)[1].split()
        return int(parts[11]) + int(parts[12])      # utime + stime
    except (OSError, IndexError, ValueError):
        return None


def find_audio_child(ppid):
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                st = f.read()
            if int(st.rsplit(")", 1)[1].split()[1]) != ppid:
                continue
            with open("/proc/%s/cmdline" % d, "rb") as f:
                cmd = f.read().replace(b"\0", b" ")
        except (OSError, ValueError, IndexError):
            continue
        if b"spawn_main" in cmd and b"resource_tracker" not in cmd:
            return int(d)
    return None


class CPU:
    def __init__(self, pids):
        self.pids = pids
        self.hz = os.sysconf("SC_CLK_TCK")
        self.samples = []      # (t, phase, {name: ticks}, fps)

    def sample(self, phase, fps):
        self.samples.append((time.monotonic(), phase, {n: _ticks(p) for n, p in self.pids.items() if p}, fps))

    def window(self, t0, t1):
        s = [x for x in self.samples if t0 <= x[0] <= t1]
        if len(s) < 2:
            return {}
        a, b = s[0], s[-1]
        dt = b[0] - a[0]
        out = {"seconds": round(dt, 1)}
        for n in b[2]:
            if a[2].get(n) is not None and b[2].get(n) is not None:
                out[n + "_cpu_pct"] = round(100.0 * (b[2][n] - a[2][n]) / self.hz / dt, 1)
        fps = [x[3] for x in s if x[3]]
        if fps:
            out["fps_min"], out["fps_mean"] = min(fps), round(sum(fps) / len(fps), 1)
        return out


# ------------------------------------------------------------- recorders --
async def recorder(url, role, store, stop):
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url) as ws:
            await ws.send_str(json.dumps({"type": "hello", "ts": time.time(),
                                          "data": {"role": role, "name": "live_test"}}))
            while not stop.is_set():
                try:
                    m = await ws.receive(timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                msg = json.loads(m.data)
                store.append((time.monotonic(), msg))


# -------------------------------------------------------------- the test --
async def wait_port(port, timeout=30):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            return True
        except OSError:
            await asyncio.sleep(0.3)
    return False


def jpeg_bytes(i):
    from PIL import Image, ImageDraw
    im = Image.new("L", (320, 240), 20)
    ImageDraw.Draw(im).ellipse((60 + i * 7, 60, 160 + i * 7, 180), fill=210)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()


async def main(a):
    ck = Checks()
    tmp = tempfile.mkdtemp(prefix="ij-live-")
    port, udp_port, tcp_port = a.port, a.port + 1, a.port + 2
    llm_port = a.port + 50
    base = "http://127.0.0.1:%d" % port
    wsurl = "ws://127.0.0.1:%d/ws" % port
    cfg_path = os.path.join(tmp, "engine.toml")
    with open(cfg_path, "w") as f:
        f.write(f"""log_level = "INFO"
mode = "handheld"
[network]
host = "127.0.0.1"
port = {port}
udp_port = {udp_port}
tcp_port = {tcp_port}
[display]
enabled = true
fullscreen = false
width = 1920
height = 1080
fps = 30
[audio]
audio_sink = "null"
[visuals]
""")
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONUNBUFFERED="1",
               PYTHONPATH=REPO)
    procs = []
    elog = open(os.path.join(tmp, "engine.log"), "w")
    eng = subprocess.Popen([sys.executable, "-m", "showengine", "--config", cfg_path],
                           cwd=PI_DIR, env=env, stdout=elog, stderr=subprocess.STDOUT)
    procs.append(eng)
    llm = None
    if a.fake_llm:
        llm = HTTPServer(("127.0.0.1", llm_port), FakeLLM)
        threading.Thread(target=llm.serve_forever, daemon=True).start()
    olog = open(os.path.join(tmp, "oracle.log"), "w")
    try:
        ok = await wait_port(port, 60) and await wait_port(tcp_port, 10)
        ck(ok, "engine is listening on %d/%d" % (port, tcp_port))
        if not ok:
            elog.flush()
            with open(os.path.join(tmp, "engine.log")) as f:
                print(f.read()[-3000:])
            return ck
        orc = subprocess.Popen([sys.executable, "-m", "infinite_jest.oracle", "--ws", wsurl, "--debug",
                                "--url", "http://127.0.0.1:%d/v1/chat/completions" % llm_port],
                               cwd=REPO, env=env, stdout=olog, stderr=subprocess.STDOUT)
        procs.append(orc)

        stop = asyncio.Event()
        ctl, orc_rx = [], []
        recs = [asyncio.ensure_future(recorder(wsurl, "control", ctl, stop)),
                asyncio.ensure_future(recorder(wsurl, "oracle", orc_rx, stop))]

        sess = aiohttp.ClientSession()

        async def status():
            async with sess.get(base + "/status") as r:
                return await r.json()

        await asyncio.sleep(3.0)     # audio child spawns, oracle connects
        audio_pid = find_audio_child(eng.pid)
        cpu = CPU({"engine": eng.pid, "audio": audio_pid})
        st = await status()
        ck(st["modules"]["visuals"] == "infinite_jest.visuals.engine", "real visuals loaded", st["modules"]["visuals"])
        ck(st["modules"]["audio"] == "infinite_jest.audio.engine", "real audio loaded", st["modules"]["audio"])
        ck(st["modules"]["profiler"] == "infinite_jest.profiler.core", "real profiler in process",
           st["modules"]["profiler"])
        ck(audio_pid is not None, "audio runs in its own process", audio_pid)
        ck(st["clients"].get("oracle", 0) >= 2, "oracle connected (plus the oracle-role recorder)", st["clients"])

        # ---- the phone
        root = os.path.join(tmp, "sysfs")
        phone = FakePhone(root)
        conf = dict(AGENT_DEFAULTS, hosts="127.0.0.1", ws_port=port, udp_port=udp_port, keep_awake=0,
                    wifi_powersave_off=0, local_prompts=0)
        agent = Agent(conf, fake=True, sysfs_root=root)
        prx, psent = install_fakes(agent, phone)
        threading.Thread(target=phone.loop, daemon=True).start()
        agent.start()

        phases = []          # (t, phase) from the control recorder, deduped

        def watch_phases():
            seen = phases[-1][1] if phases else None
            for t, m in ctl:
                if m["type"] == "state" and (not phases or t > phases[-1][0]):
                    ph = m["data"].get("phase")
                    if ph != seen:
                        phases.append((t, ph))
                        seen = ph

        async def hold(seconds, label):
            log(label)
            t_end = time.monotonic() + seconds
            while time.monotonic() < t_end:
                await asyncio.sleep(1.0)
                try:
                    s = await status()
                except Exception:
                    continue
                cpu.sample(s["phase"], s.get("fps"))
                watch_phases()

        def states_between(t0, t1):
            return [m["data"] for t, m in ctl if m["type"] == "state" and t0 <= t <= t1]

        # ---------------------------------------------------------- visit 1
        cpu.sample("idle", None)
        t_idle0 = time.monotonic()
        await hold(a.scale * 10, "phone lying flat, nobody there")
        s = await status()
        ck(s["phase"] == "idle", "flat, untouched phone keeps the room idle", s["phase"])
        ck(prx["state"] > 0, "phone receives state", prx["state"])
        t_idle1 = time.monotonic()

        t_v1 = time.monotonic()
        phone.noise, phone.motion = 0.03, True
        phone.tilt(15, 0)
        await hold(4, "picked up")
        s = await status()
        ck(s["phase"] in ("approach", "profiling"), "picking it up starts a visit", s["phase"])

        gestures = []

        async def gesture(label, seconds, **kw):
            t0 = time.monotonic()
            phone.tilt(kw.get("beta", 0), kw.get("gamma", 0))
            phone.shake = kw.get("shake", 0.0)
            phone.noise = kw.get("noise", 0.03)
            await hold(seconds, label)
            phone.shake = 0.0
            gestures.append((label, t0, time.monotonic()))

        g = a.scale
        await gesture("tilt left", 5 * g, gamma=-35)
        await gesture("tilt right", 5 * g, gamma=35)
        await gesture("tilt forward", 5 * g, beta=35)
        await gesture("tilt back", 5 * g, beta=-35)
        await gesture("upside down", 5 * g, beta=178)
        await gesture("shake", 4 * g, beta=20, shake=0.9)
        phone.motion = False
        await gesture("hold still", 9, beta=20, gamma=0, noise=0.0)
        phone.motion = True
        await hold(6 * g, "handling it again")
        s = await status()
        ck(s["phase"] == "hook", "visit reached hook while held", s["phase"])

        # steer checks against the recorded state stream
        def steer_at(label):
            for lab, t0, t1 in gestures:
                if lab == label:
                    st = states_between(t1 - 1.5, t1)
                    return st[-1].get("steer") if st else None
        sl, sr = steer_at("tilt left"), steer_at("tilt right")
        sf, sb = steer_at("tilt forward"), steer_at("tilt back")
        su, ss = steer_at("upside down"), steer_at("shake")
        sh = steer_at("hold still")
        ck(sl and sl["x"] < -0.5, "tilt left -> steer.x < -0.5", sl)
        ck(sr and sr["x"] > 0.5, "tilt right -> steer.x > 0.5", sr)
        ck(sf and sf["y"] > 0.5, "tilt forward -> steer.y > 0.5", sf)
        ck(sb and sb["y"] < -0.5, "tilt back -> steer.y < -0.5", sb)
        ck(su and su.get("flip") is True, "upside down -> steer.flip", su)
        shake_max = max([x.get("steer", {}).get("shake", 0) for x in
                         states_between(*[(t0, t1) for lab, t0, t1 in gestures if lab == "shake"][0])] or [0])
        ck(shake_max > 0.3, "shake -> steer.shake > 0.3", shake_max)
        ck(sh and sh.get("still_s", 0) >= 5, "hold still 9 s -> steer.still_s >= 5", sh)

        v1 = states_between(t_v1, time.monotonic())
        vid1 = next((x["visitor_id"] for x in v1 if x.get("visitor_id")), "")
        hook_states = [x for x in v1 if x["phase"] == "hook"]
        ck(hook_states and hook_states[-1].get("profile_source") == "profiler",
           "hook comes from the profiler, not the fallback",
           hook_states and hook_states[-1].get("profile_source"))
        ck(hook_states and hook_states[-1].get("hook") in ("flesh", "scrawl", "inverted", "mirror", "void"),
           "hook is a contract hook", hook_states and hook_states[-1].get("hook"))
        words = [w for x in v1 for w in (x.get("words") or [])]
        ck(len(words) > 0, "words reach state.words during the visit", sorted(set(words))[:6])
        prof_rx = [m for t, m in orc_rx if m["type"] == "profile" and t >= t_v1]
        ck(len(prof_rx) > 0 and all(m["data"].get("visitor_id") == vid1 for m in prof_rx),
           "oracle receives profiles for the current visitor", len(prof_rx))

        # ---- put down
        t_down = time.monotonic()
        phone.tilt(0, 0)
        phone.noise, phone.motion = 0.0, False
        await hold(a.scale * 26 + 6, "put down flat")
        watch_phases()
        s = await status()
        ck(s["phase"] == "idle", "putting it down ends the visit and returns to idle", s["phase"])
        seq = [p for t, p in phases if t < t_idle0][-1:] + [p for t, p in phases if t >= t_idle0]
        ck(seq[:len(PHASE_ORDER)] == PHASE_ORDER, "phase order idle->approach->profiling->hook->release->wipe->idle",
           seq)
        rel = [t for t, p in phases if p == "release" and t > t_down]
        # contract: put down for 8 s ends it; the agent itself keeps `held` ~2.5 s after the last movement
        ck(rel and rel[0] - t_down <= 13.0, "release within ~8 s (+ the agent's 2.5 s held debounce) of put down",
           "%.1f s" % (rel[0] - t_down) if rel else "never")
        wipes = [(t, m) for t, m in ctl if m["type"] == "wipe" and t > t_down]
        ck(wipes and wipes[0][1]["data"].get("visitor_id") == vid1, "wipe broadcast names the visitor", len(wipes))
        ck(prx["wipe"] >= 1, "phone receives wipe", prx["wipe"])
        texts = [d.get("text") or d.get("ask") for t, d in prx["phone"] if t_v1 <= t]
        ck(len(texts) >= 3, "phone receives phone text through the visit", texts)
        after = states_between(time.monotonic() - 2, time.monotonic())
        leftovers = [x for x in after if x.get("visitor_id") or x.get("words") or x.get("ocean")
                     or x.get("dossier") or x.get("reveal") or x.get("hook")]
        ck(after and not leftovers, "after wipe the state holds no visitor data",
           leftovers[-1] if leftovers else "")
        rel_states = [x for x in v1 + states_between(t_down, time.monotonic()) if x["phase"] == "release"]
        ck(any(x.get("words") for x in rel_states), "release shows words (reveal or oracle)",
           rel_states and rel_states[-1].get("words"))
        t_v1_end = time.monotonic()

        # ---------------------------------------------------------- visit 2: opt-out
        t_v2 = time.monotonic()
        phone.noise, phone.motion = 0.03, True
        phone.tilt(20, 10)
        await hold(a.scale * 22, "visit 2: picked up")
        before = states_between(time.monotonic() - 1.5, time.monotonic())
        log("visit 2 phase before cover:", before and before[-1]["phase"])
        t_cover = time.monotonic()
        phone.near = True
        await hold(4, "covering the proximity sensor")
        phone.near = False
        await hold(3, "uncovered, still holding")
        ck(psent["kinds"].get("optout", 0) >= 1, "agent sent kind optout", psent["kinds"].get("optout"))
        t_opt = psent.get("optout_t", t_cover + 3.0) + 0.5     # the agent waits 3 s covered; allow one hop
        ck(psent["optout_periodic"] > 0, "agent sends periodic phone optout:true", psent["optout_periodic"])
        st_after = states_between(time.monotonic() - 2, time.monotonic())
        ck(st_after and all(x.get("hook") in ("void", None) and not x.get("words") and not x.get("ocean")
                            for x in st_after if x.get("visitor_id")),
           "engine quiets the visit after opt-out (void, no words, no ocean)",
           st_after and {k: st_after[-1].get(k) for k in ("phase", "hook", "words", "ocean", "profile_source")})
        prof_after = [m for t, m in orc_rx if m["type"] == "profile" and t > t_opt
                      and m["data"].get("phase") != "opted_out" and m["data"].get("ocean")]
        ck(not prof_after, "no profile with scores reaches the oracle after opt-out", len(prof_after))
        await hold(a.scale * 16 + 4, "visit 2: still holding after opt-out")
        watch_phases()
        held_seq = [p for t, p in phases if t > t_cover]
        ck(not held_seq, "opted-out visitor still holding the phone: the visit stays (quiet), no wipe/re-read",
           held_seq)
        t_down2 = time.monotonic()
        phone.tilt(0, 0)
        phone.noise, phone.motion = 0.0, False
        await hold(a.scale * 20 + 4, "visit 2: put down")
        watch_phases()
        seq2 = [p for t, p in phases if t >= t_v2]
        ck("wipe" in seq2 and seq2[-1] == "idle" and seq2.count("approach") == 1,
           "opt-out visit ends with wipe and idle, once", seq2)
        w2 = [t for t, p in phases if p == "wipe" and t > t_down2]
        t_end2 = w2[0] if w2 else time.monotonic()
        v2 = states_between(t_opt, t_end2)
        ck(not any(x.get("words") for x in v2), "no words shown to an opted-out visitor (incl. release)",
           next((x["words"] for x in v2 if x.get("words")), ""))
        ck(not any(x.get("reveal") for x in v2), "no reveal for an opted-out visitor",
           next((x["reveal"] for x in v2 if x.get("reveal")), ""))
        lines2 = [d for t, d in prx["phone"] if t_opt < t < t_end2]
        ck(not any("data" in (d.get("text") or "").lower() and "thank" in (d.get("text") or "").lower()
                   for d in lines2), "opted-out visitor is not thanked for their data",
           [d.get("text") or d.get("ask") for d in lines2])

        # ---------------------------------------------------------- side lanes
        s0 = await status()
        agent.stop()
        phone.running = False
        await asyncio.sleep(1.0)
        us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for i, seq_no in enumerate([1, 2, 3, 5, 6]):   # 4 is "lost"
            us.sendto(json.dumps({"type": "sensor", "ts": time.time(), "data": {
                "kind": "phone", "seq": seq_no + 100000, "tilt": {"alpha": 0, "beta": 0, "gamma": -20},
                "light": 0.3}}).encode(), ("127.0.0.1", udp_port))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        s1 = await status()
        ck(s1["udp"]["received"] - s0["udp"]["received"] == 5, "UDP 8766: 5 datagrams received",
           s1["udp"])
        ck(s1["udp"]["lost"] - s0["udp"]["lost"] >= 1, "UDP 8766: the gap is counted as lost", s1["udp"])

        async with sess.post(base + "/api/sensor", data=json.dumps([
                {"type": "sensor", "ts": time.time(), "data": {"kind": "phone", "light": 0.4}},
                {"type": "sensor", "ts": time.time(), "data": {"kind": "touch", "x": 0.2, "y": 0.8, "down": True}},
                {"type": "nonsense", "ts": 0, "data": {}}])) as r:
            body = await r.json()
        ck(r.status == 200 and body.get("accepted") == 2, "POST /api/sensor accepts an array", body)
        async with sess.post(base + "/api/sensor", data="not json") as r:
            ck(r.status == 400, "POST /api/sensor rejects junk with 400", r.status)

        import base64 as b64
        gray = make_gray(50)
        async with sess.post(base + "/api/frame", data=json.dumps({"type": "frame", "ts": time.time(), "data": {
                "w": 160, "h": 120, "fmt": "gray8", "b64": b64.b64encode(gray).decode()}})) as r:
            ck(r.status == 200, "POST /api/frame accepts a gray8 frame", r.status)

        await asyncio.sleep(0.3)                 # the engine analyses at most 10 frames/s
        f0 = (await status())["counts"]["frame"]
        rd, wr = await asyncio.open_connection("127.0.0.1", tcp_port)
        for n in range(6):                       # ~5 fps, each JPEG split across reads like a real stream
            blob = jpeg_bytes(n)
            for i in range(0, len(blob), 1000):
                wr.write(blob[i:i + 1000])
                await wr.drain()
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.15)
        await asyncio.sleep(0.5)
        wr.close()
        f1 = (await status())["counts"]["frame"]
        ck(f1 - f0 == 6, "TCP 8767: 6 back-to-back JPEGs at ~5 fps become 6 frames", f1 - f0)
        async with sess.ws_connect(wsurl) as cws:     # operator volume: the engine calls audio.set_volume
            await cws.send_str(json.dumps({"type": "hello", "ts": 0, "data": {"role": "control"}}))
            await cws.send_str(json.dumps({"type": "control", "ts": time.time(),
                                           "data": {"cmd": "volume", "arg": 0.6}}))
            await asyncio.sleep(0.5)
        await asyncio.sleep(10.0)    # the lanes' readings start a visit or not; let presence go stale

        # ---------------------------------------------------------- privacy scan
        visible = []
        for t, m in ctl:
            if m["type"] == "state":
                d = m["data"]
                visible += list(d.get("words") or []) + list(d.get("dossier") or [])
                if d.get("reveal"):
                    visible += list(d["reveal"].get("lines") or []) + [d["reveal"].get("label") or ""]
        for t, d in prx["phone"]:
            visible += [d.get("text") or "", d.get("ask") or ""] + list(d.get("options") or [])
        bad = sorted({v for v in visible if any(h in v.lower() for h in HIDDEN)})
        ck(not bad, "no artist names, crowns, skulls or (c) in visitor-visible text", bad[:5])

        # ---------------------------------------------------------- oracle path
        with open(os.path.join(tmp, "oracle.log")) as f:
            olines = f.read()
        if a.fake_llm:
            ck("-> sent" in olines, "oracle got model text and sent it", olines.count("-> sent"))
            ow = [w for x in v1 for w in (x.get("words") or [])]
            ck("KEEPS STILL" in ow or any("KEEPS STILL" in (x.get("words") or [])
                                          for t, m in ctl if m["type"] == "state" for x in [m["data"]]),
               "oracle words reach state.words")
            ck(any(d.get("text") == "stay a little longer" for t, d in prx["phone"]),
               "oracle phone_text reaches the phone")
        else:
            ck("model failed" in olines, "oracle notices the model is down and stays quiet",
               olines.count("model failed"))
            ck(orc.poll() is None, "oracle keeps running without its model")

        # ---------------------------------------------------------- measurements
        with open(os.path.join(tmp, "engine.log")) as f:
            elines = f.read()
        errs = [l for l in elines.splitlines() if "Traceback" in l or " ERROR " in l or "failed" in l]
        ck(not errs, "engine log has no errors or plugin failures", errs[:3])
        ck(eng.poll() is None, "engine still running")

        measure = {
            "idle": cpu.window(t_idle0, t_idle1),
            "visit1": cpu.window(t_v1, t_v1_end),
            "whole_run": cpu.window(t_idle0, time.monotonic()),
            "cpu_count": os.cpu_count(),
            "machine": os.uname().machine,
        }
        print("MEASURE " + json.dumps(measure), flush=True)
        print("PHASES " + json.dumps([(round(t - T0, 1), p) for t, p in phases]), flush=True)
        print("ENGINE COUNTS " + json.dumps((await status())["counts"]), flush=True)
        stop.set()
        await asyncio.gather(*recs, return_exceptions=True)
        await sess.close()
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        if llm:
            llm.shutdown()
        elog.close()
        olog.close()
        if a.keep:
            print("kept", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return ck


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=18765, help="engine HTTP/ws port; UDP +1, TCP +2, fake LLM +50")
    ap.add_argument("--fake-llm", action="store_true", help="answer the oracle with a stand-in llama-server")
    ap.add_argument("--quick", action="store_true", help="shorter gestures")
    ap.add_argument("--keep", action="store_true", help="keep the temp dir with the engine/oracle logs")
    args = ap.parse_args()
    args.scale = 0.6 if args.quick else 1.0
    result = asyncio.run(main(args))
    print("\n%d checks, %d failed" % (len(result.rows), len(result.failed)))
    for ok, what, detail in result.failed:
        print("  FAIL", what, detail)
    sys.exit(1 if result.failed else 0)
