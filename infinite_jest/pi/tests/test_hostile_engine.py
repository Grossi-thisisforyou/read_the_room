"""Hostile input and failure modes: what a broken phone, a stray laptop or a dead
projector does to the engine. Each test is a regression test for a real crash or
leak found by attacking a running engine over its sockets."""
import asyncio
import base64
import io
import json
import logging
import os
import socket
import struct
from pathlib import Path

import aiohttp
import numpy as np
import pygame
import pytest

from showengine import app, config, frames, hub as hubmod, plugins, protocol as P, sdnotify
from showengine.engine import Engine
from showengine.hub import Hub, split_jpegs

from test_core import BUSY, Clock, make_engine, run
from test_hub import free_port


# ---------------------------------------------------------------- protocol
@pytest.mark.parametrize("raw", [
    '{"type":"sensor","data":{"held":NaN}}',
    '{"type":"sensor","data":{"held":Infinity}}',
    '{"type":"sensor","data":{"held":-Infinity}}',
    '{"type":"sensor","data":{"held":1e999}}',
    '{"type":"sensor","data":{"x":' + "[" * 50000 + "]" * 50000 + "}}",
])
def test_decode_rejects_values_that_cannot_be_sent_on(raw):
    with pytest.raises(P.BadMessage):
        P.decode(raw)


def test_decode_survives_absurd_numbers():
    m = P.decode('{"type":"sensor","ts":' + "9" * 400 + ',"data":{"motion":' + "9" * 400 + "}}")
    assert m["ts"] > 0 and P.num(m["data"]["motion"], 0.25) == 0.25


# ---------------------------------------------------------------- engine
def test_hostile_sensor_values_never_reach_the_state_raw():
    eng, clock, sent = make_engine(mode="handheld")
    junk = {"kind": "phone", "held": "A" * 500_000, "proximity": {"near": [1] * 1000},
            "motion": {"a": 1}, "faces": 10 ** 9, "light": -5, "audio": "loud",
            "tilt": {"beta": 10 ** 300, "gamma": "x"}, "accel": [1, 2]}
    for i in range(200):
        d = dict(junk)
        d["junk%d" % i] = "x" * 1000              # a new key every message
        clock.t += 0.1
        eng.handle(P.make(P.SENSOR, d), "phone")
    eng.handle(P.make(P.SENSOR, {"kind": "touch", "x": "A" * 10000, "y": None}), "phone")
    text = P.encode(P.make(P.STATE, eng.state))      # must not raise
    assert len(text) < 4000
    assert not any(k.startswith("junk") for k in eng.sensor)
    s = eng.state["sensor"]
    assert s["held"] == 0.0 and s["proximity"] == {"near": False} and s["faces"] == 16
    assert s["touch"] == {"x": 0.0, "y": 0.0}


def test_unknown_message_types_do_not_pile_up():
    eng, _, _ = make_engine()
    for i in range(500):
        eng.handle(P.make("t%d" % i + "y" * 10000), "phone")
    assert len(eng._unknown_types) <= 32 and all(len(t) <= 40 for t in eng._unknown_types)


def test_profile_and_reveal_only_from_the_profiler():
    eng, clock, _ = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    for role in ("phone", "visuals", "audio", "oracle"):
        eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "evidence": ["PUSHED BY " + role]}), role)
        eng.handle(P.make(P.REVEAL, {"visitor_id": vid, "lines": ["PUSHED"]}), role)
    assert not any("PUSHED" in w for w in eng.state["words"]) and eng.machine.visit.reveal is None
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "evidence": ["real"], "source": ["x"] * 9}), "profiler")
    assert eng.state["words"] == ["real"] and eng.state["profile_source"] == "profiler"


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("on_") or name in ("reset", "render"):
            return lambda *a: self.calls.append((name, a))
        raise AttributeError(name)


def test_opt_out_clears_oracle_text_and_stops_reading_the_visitor():
    vis, prof = Recorder(), Recorder()
    eng, clock, sent = make_engine(visuals=vis, profiler=prof)
    run(eng, clock, 25, BUSY)
    assert eng.machine.phase == "hook"
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["SUBJECT LINGERS"], "dossier": ["fast: E 0.7"]}), "oracle")
    eng.handle(P.make(P.SENSOR, {"kind": "keys", "text": "a secret"}), "phone")
    eng.machine.visit.reveal = {"lines": ["the watcher"], "label": "x"}
    assert eng.state["words"] == ["SUBJECT LINGERS"]

    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "phase": "opted_out", "wiped": True}), "profiler")
    v = eng.machine.visit
    assert eng.state["words"] == [] and eng.state["dossier"] == [] and eng.state["reveal"] is None
    assert v.answers == [] and v.oracle_words == [] and v.ocean is None and eng.state["scene"] == "void"
    assert ("on_wipe", ()) in vis.calls

    # after the opt-out: no frames analysed or forwarded, sensors only feed presence
    sent.clear()
    prof.calls.clear()
    n_frames = eng.stats["frame"]
    gray = base64.b64encode(bytes(160 * 120)).decode()
    eng.handle(P.make(P.FRAME, {"w": 160, "h": 120, "fmt": "gray8", "b64": gray}), "phone")
    eng.handle(P.make(P.SENSOR, BUSY), "phone")
    eng.handle(P.make(P.SENSOR, {"kind": "keys", "text": "more"}), "phone")
    eng.handle(P.make(P.ANSWER, {"text": "more"}), "phone")
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "ocean": {"O": 1}, "confidence": 1}), "profiler")
    eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["AGAIN"]}), "oracle")
    assert eng.stats["frame"] == n_frames
    assert not [c for c in prof.calls if c[0] in ("on_sensor", "on_frame")]
    assert not [m for m, r in sent if m["type"] in (P.FRAME, P.SENSOR, P.ANSWER)]
    assert v.answers == [] and v.ocean is None and eng.state["words"] == []
    assert eng.presence.present   # still watching for them to leave


def test_profiler_gets_the_engines_clock_not_the_senders():
    prof = Recorder()
    eng, clock, _ = make_engine(profiler=prof)
    msg = P.make(P.SENSOR, BUSY, ts=4102444800.0)     # the N900 thinks it is 2100
    clock.t = 1234.5
    eng.handle(msg, "phone")
    ts = [a[1] for name, a in prof.calls if name == "on_sensor"]
    assert ts == [1234.5]
    visits = [a[1] for name, a in prof.calls if name == "on_visit"]
    assert all(t <= clock.t for t in visits)


def test_plugin_that_throws_every_frame_logs_once_a_minute(caplog):
    class Broken:
        def on_state(self, s):
            raise RuntimeError("boom")
    plugins._last_report.clear()
    eng, clock, _ = make_engine(visuals=Broken())
    with caplog.at_level(logging.ERROR, logger="showengine.plugins"):
        for _ in range(300):
            clock.t += 1 / 30
            eng.tick()
    assert len([r for r in caplog.records if "on_state failed" in r.getMessage()]) == 1


# ---------------------------------------------------------------- frames
def _jpeg(w, h):
    surf = pygame.Surface((w, h))
    surf.fill((90, 90, 90))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "x.jpg")
    return buf.getvalue()


def _claim_size(jpeg, w, h):
    """The decompression bomb: keep the file tiny, make the header claim w x h."""
    b = bytearray(jpeg)
    i = 2
    while i < len(b):
        m, ln = b[i + 1], struct.unpack(">H", b[i + 2:i + 4])[0]
        if m in (0xC0, 0xC1, 0xC2):
            b[i + 5:i + 9] = struct.pack(">HH", h, w)
        if m == 0xDA:
            return bytes(b[:i + 2 + ln + 64]) + b"\xff\xd9"
        i += 2 + ln
    raise AssertionError("no scan")


def test_image_size_reads_headers():
    assert frames.image_size(_jpeg(64, 48)) == (64, 48)
    png = io.BytesIO()
    pygame.image.save(pygame.Surface((30, 20)), png, "x.png")
    assert frames.image_size(png.getvalue()) == (30, 20)
    for junk in (b"", b"\xff\xd8", b"\xff\xd8\xff\xda\x00\x02", b"\xff\xd8\x00\x00", b"GIF89a", b"\xff\xd8\xff\xe0\x00\x00"):
        assert frames.image_size(junk) is None


def test_jpeg_bomb_is_refused_before_decoding(monkeypatch):
    bomb = _claim_size(_jpeg(64, 48), 20000, 20000)       # ~1 KB that decodes to 1.2 GB
    assert len(bomb) < 2000 and frames.image_size(bomb) == (20000, 20000)

    def no_decode(*a, **k):
        raise AssertionError("decoded an oversized image")
    monkeypatch.setattr(pygame.image, "load", no_decode)
    fa = frames.FrameAnalyzer()
    assert fa.decode({"fmt": "jpeg", "b64": base64.b64encode(bomb).decode()}) is None


def test_split_jpegs_handles_markers_split_across_reads():
    a, b = _jpeg(16, 16), _jpeg(8, 8)
    stream = b"junk\xff" + a + b"\x00\xff" + b
    for step in (1, 2, 3, 7):
        buf, out = bytearray(), []
        for i in range(0, len(stream), step):
            buf += stream[i:i + step]
            out += split_jpegs(buf)
        assert out == [a, b], step


# ---------------------------------------------------------------- hub, over real sockets
def _cfg(**over):
    port, udp, tcp = free_port(), free_port(socket.SOCK_DGRAM), free_port()
    net = {"host": "127.0.0.1", "port": port, "udp_port": udp, "tcp_port": tcp}
    net.update(over)
    return config.load(None, {"mode": "handheld", "network": net})


def test_nan_and_deep_json_over_every_lane_leave_the_show_running():
    asyncio.run(_nan_scenario())


async def _nan_scenario():
    cfg = _cfg()
    net = cfg["network"]
    eng = Engine(cfg)
    hub = Hub(eng, cfg)
    await hub.start()
    base = f"http://127.0.0.1:{net['port']}"
    try:
        async with aiohttp.ClientSession() as s:
            oracle = await s.ws_connect(f"{base}/ws")
            await oracle.send_str(P.encode(P.make(P.HELLO, {"role": "oracle"})))
            await oracle.receive()
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.sendto(b'{"type":"sensor","data":{"kind":"phone","held":NaN}}', ("127.0.0.1", net["udp_port"]))
            u.sendto(("[" * 30000 + "]" * 30000).encode(), ("127.0.0.1", net["udp_port"]))
            u.close()
            deep = '{"type":"sensor","data":{"x":' + "[" * 100000 + "]" * 100000 + "}}"
            await oracle.send_str(deep)
            r = await s.post(f"{base}/api/sensor", data='[{"type":"sensor","data":{"held":Infinity}}]')
            assert r.status == 400
            r = await s.post(f"{base}/api/sensor", data="[" * 100000 + "]" * 100000)
            assert r.status == 400
            await asyncio.sleep(0.2)
            eng.tick()
            P.encode(P.make(P.STATE, eng.state))
            assert eng.stats["bad"] >= 3 and not oracle.closed
            # still talking: a new client gets its hello answered, the old one still gets state
            late = await s.ws_connect(f"{base}/ws")
            await late.send_str(P.encode(P.make(P.HELLO, {"role": "visuals"})))
            assert P.decode((await asyncio.wait_for(late.receive(), 2)).data)["type"] == P.STATE
            eng.tick(eng.clock() + 1)
            got = P.decode((await asyncio.wait_for(oracle.receive(), 2)).data)
            assert got["type"] in (P.STATE, P.VISIT, P.PHONE)
            await late.close()
            await oracle.close()
    finally:
        await hub.stop()


def test_privileged_roles_need_an_allowed_address():
    eng = Engine(config.load(None))
    hub = Hub(eng, config.load(None))
    for peer in ("127.0.0.1", "::1", "192.168.1.20", "192.168.1.57", "::ffff:192.168.1.30"):
        assert hub._grant("control", peer) == "control", peer
    for peer in ("10.0.0.5", "172.16.0.9", None, "garbage"):
        assert hub._grant("control", peer) == "phone"
        assert hub._grant("oracle", peer) == "phone"
        assert hub._grant("profiler", peer) == "phone"
        assert hub._grant("visuals", peer) == "visuals"
    narrow = Hub(eng, config.load(None, {"network": {"privileged_from": ["127.0.0.1", "192.168.1.50", "bogus"]}}))
    assert narrow._grant("control", "192.168.1.50") == "control"
    assert narrow._grant("control", "192.168.1.20") == "phone"
    everyone = Hub(eng, config.load(None, {"network": {"privileged_from": ["0.0.0.0/0", "::/0"]}}))
    assert everyone._grant("control", "10.1.2.3") == "control"


def test_a_client_that_stops_reading_does_not_grow_memory():
    asyncio.run(_slow_scenario())


async def _slow_scenario():
    class Stuck:
        closed = False

        def __init__(self):
            self.started = 0

        async def send_str(self, text):
            self.started += 1
            await asyncio.Event().wait()      # never drains

    eng = Engine(config.load(None))
    hub = Hub(eng, config.load(None))
    ws = Stuck()
    hub.clients[ws] = "profiler"
    for _ in range(1000):
        hub.emit(P.make(P.FRAME, {"b64": "x" * 1000}), {"profiler"})
    await asyncio.sleep(0)
    assert ws.started == hubmod.MAX_PENDING and hub.dropped == 1000 - hubmod.MAX_PENDING
    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()


# ---------------------------------------------------------------- systemd + display
def test_sdnotify_is_a_no_op_outside_systemd(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sdnotify.notify("WATCHDOG=1") is False
    path = str(tmp_path / "notify")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    try:
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        assert sdnotify.notify("READY=1") is True
        assert srv.recv(64) == b"READY=1"
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "gone"))
        assert sdnotify.notify("WATCHDOG=1") is False
    finally:
        srv.close()


def test_service_never_gives_up_and_has_a_watchdog():
    unit = (Path(__file__).resolve().parents[1] / "systemd" / "infinite-jest.service").read_text()
    sections, cur = {}, None
    for line in unit.splitlines():
        line = line.strip()
        if line.startswith("["):
            cur = line
        elif "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            sections.setdefault(cur, {})[k] = v
    assert sections["[Unit]"]["StartLimitIntervalSec"] == "0"
    assert "StartLimitIntervalSec" not in sections["[Service]"]
    assert sections["[Service]"]["Restart"] == "always" and int(sections["[Service]"]["WatchdogSec"]) >= 30


def test_hdmi_status_reads_drm_connectors(tmp_path):
    assert app.hdmi_status(str(tmp_path / "none")) is None
    for name, st in (("card1-HDMI-A-1", "disconnected"), ("card1-HDMI-A-2", "disconnected"), ("card1-Writeback-1", "connected")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "status").write_text(st + "\n")
    assert app.hdmi_status(str(tmp_path)) is False
    (tmp_path / "card1-HDMI-A-1" / "status").write_text("connected\n")
    assert app.hdmi_status(str(tmp_path)) is True


def test_projector_switched_on_late_and_flip_errors_reopen_the_display(monkeypatch):
    real_set_mode, real_flip = pygame.display.set_mode, pygame.display.flip
    calls = {"set_mode": 0, "flip": 0}

    def set_mode(*a, **k):
        calls["set_mode"] += 1
        if calls["set_mode"] <= 2:                 # projector still off at boot
            raise pygame.error("No available video device")
        return real_set_mode(*a, **k)

    def flip():
        calls["flip"] += 1
        if calls["flip"] == 5:                     # unplugged mid-show
            raise pygame.error("video system not initialized")
        return real_flip()

    monkeypatch.setattr(pygame.display, "set_mode", set_mode)
    monkeypatch.setattr(pygame.display, "flip", flip)
    cfg = _cfg()
    cfg = config.load(None, {"network": cfg["network"], "display": {"fullscreen": False, "width": 160, "height": 90,
                                                                    "retry_s": 0.1},
                             "modules": {"visuals": "", "audio": "", "profiler": ""}})
    runner = app.Runner(cfg, audio=False)
    states = []

    async def drive():
        task = asyncio.ensure_future(runner.run())
        for _ in range(100):
            await asyncio.sleep(0.03)
            states.append(runner.screen is not None)
        runner.stop()
        await task

    asyncio.run(drive())
    assert states[0] is False and calls["set_mode"] >= 4    # failed twice, opened, lost, reopened
    assert calls["flip"] > 10 and states[-1] is True
    assert runner.engine.visuals is not None                  # visuals built once the display came
    assert runner.engine.machine.phase == "idle"


# ---------------------------------------------------------------- visits that go wrong
HELD = {"kind": "phone", "held": True, "tilt": {"beta": 10, "gamma": 5}}


def test_phone_goes_silent_mid_visit_ends_the_visit():
    eng, clock, sent = make_engine(mode="handheld")
    run(eng, clock, 30, HELD)
    assert eng.machine.phase == "hook"
    run(eng, clock, 12)                       # Wi-Fi drops: no data at all, only frame ticks
    assert eng.machine.phase in ("release", "wipe")
    run(eng, clock, 12)
    assert eng.machine.phase == "idle" and eng.state["visitor_id"] == "" and eng.state["words"] == []


def test_phone_never_put_down_still_cycles_visitors():
    eng, clock, sent = make_engine(mode="handheld")
    run(eng, clock, 200, HELD)
    ids = {m["data"]["visitor_id"] for m, _ in sent if m["type"] == P.STATE} - {""}
    assert "release" in [m["data"]["phase"] for m, _ in sent if m["type"] == P.STATE]
    assert len(ids) >= 2                       # max_visit ended the first, a fresh one began


def test_nobody_for_hours_stays_idle_and_small():
    eng, clock, sent = make_engine(mode="handheld")
    for _ in range(6 * 3600):                  # six hours at 1 Hz ticks
        clock.t += 1.0
        eng.tick()
    assert eng.machine.phase == "idle" and len(eng.sensor) == 0


def test_frame_flood_is_analysed_at_most_ten_times_a_second():
    eng, clock, sent = make_engine()
    gray = base64.b64encode(bytes(160 * 120)).decode()
    for _ in range(500):
        clock.t += 0.001
        eng.handle(P.make(P.FRAME, {"w": 160, "h": 120, "fmt": "gray8", "b64": gray}), "phone")
    assert eng.stats["frame"] <= 6            # 0.5 s of flood


def test_covering_the_phone_opts_out_even_without_a_profiler():
    eng, clock, sent = make_engine(mode="handheld")         # no profiler: fallback mode
    run(eng, clock, 12, HELD)
    vid = eng.state["visitor_id"]
    assert eng.machine.phase == "profiling" and not eng.machine.visit.opted_out
    run(eng, clock, 2, dict(HELD, proximity={"near": True}))
    assert not eng.machine.visit.opted_out                   # 2 s is not enough
    run(eng, clock, 1.5, dict(HELD, proximity={"near": True}))
    assert eng.machine.visit.opted_out and eng.state["ocean"] is None and eng.state["words"] == []
    assert any(m["type"] == P.VISIT and m["data"].get("opt_out") and r == {"profiler"} for m, r in sent)
    run(eng, clock, 30, dict(HELD, proximity={"near": False}))
    assert eng.state["scene"] == "void" and eng.state["visitor_id"] == vid   # quiet until they leave
