"""The engine: takes every incoming message, runs the visit, emits "state".

No sockets and no window in here. The hub (hub.py) feeds it messages and gives
it an `emit` function; the runner (app.py) calls `tick()` every frame. Tests
drive it directly with a fake clock.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Callable

from . import director, plugins, protocol as P
from .fallback_profile import FallbackProfiler
from .frames import FrameAnalyzer
from .presence import Presence, PresenceConfig
from .tilt import Tilt
from .visit import VisitConfig, VisitMachine

log = logging.getLogger("showengine")

Emit = Callable[[dict, "set[str] | None"], None]   # (message, roles or None = everyone)


# The contract's periodic phone fields, each read into a known shape. Anything else
# a sender puts in a sensor message is not kept (it would pile up and be rebroadcast).
OPT_OUT_COVER_S = 3.0   # docs/CONTRACT.md privacy promise; the profiler uses the same number
_UNIT = ("motion", "presence", "loudness", "light", "shake", "battery")


def clean_sensor(d: dict) -> dict:
    out: dict[str, Any] = {}
    for k in _UNIT:
        if k in d:
            out[k] = P.num(d[k])
    if "faces" in d:
        out["faces"] = int(P.num(d["faces"], 0, 0, 16))
    for k in ("held", "slide"):
        if k in d:
            v = d[k]
            out[k] = v if isinstance(v, bool) else P.num(v)
    if "audio" in d:
        a = d["audio"] if isinstance(d["audio"], dict) else {}
        out["audio"] = {"level": P.num(a.get("level")), "voiced": a.get("voiced") is True}
    if "proximity" in d:
        p = d["proximity"]
        near = p.get("near") if isinstance(p, dict) else p
        out["proximity"] = {"near": near is True or P.num(near) >= 0.5}
    if isinstance(d.get("accel"), dict):
        out["accel"] = {k: P.num(d["accel"].get(k), 0.0, -8.0, 8.0) for k in ("x", "y", "z")}
    if isinstance(d.get("tilt"), dict):
        out["tilt"] = {k: P.num(d["tilt"].get(k), 0.0, -360.0, 360.0) for k in ("alpha", "beta", "gamma")}
    return out


def _dataclass_kwargs(cls: type, raw: dict) -> dict:
    fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
    return {k: float(v) for k, v in (raw or {}).items() if k in fields}


class Engine:
    def __init__(self, cfg: dict, emit: Emit | None = None, clock: Callable[[], float] = time.monotonic,
                 visuals: Any = None, audio: Any = None, profiler: Any = None):
        self.cfg = cfg
        self.emit: Emit = emit or (lambda msg, roles: None)
        self.clock = clock
        now = clock()
        self.mode = cfg.get("mode", "handheld")
        pcfg = PresenceConfig(**_dataclass_kwargs(PresenceConfig, cfg.get("presence", {})))
        pcfg.handheld = self.mode == "handheld"
        self.presence = Presence(pcfg)
        self.machine = VisitMachine(VisitConfig(**_dataclass_kwargs(VisitConfig, cfg.get("visit", {}))), now)
        self.fallback = FallbackProfiler()
        self.frames = FrameAnalyzer()
        self.tilt = Tilt()
        self.visuals, self.audio, self.profiler = visuals, audio, profiler
        self.sensor: dict[str, Any] = {}       # latest periodic reading (merged)
        self.blackout = False
        self.override_scene: str | None = None
        self.state: dict = director.build_state(self.machine, now)
        self.stats = {"sensor": 0, "frame": 0, "profile": 0, "oracle": 0, "bad": 0, "visits": 0}
        self.last_sensor_ts: float | None = None
        self._state_period = 1.0 / max(1.0, float(cfg.get("state_hz", 10)))
        self._last_state_emit = -1e9
        self._last_frame_t = -1e9
        self._last_frame_in = -1e9
        self._near_since: float | None = None
        self._unknown_types: set[str] = set()

    # ------------------------------------------------------------------ input
    def handle(self, msg: dict, role: str = "phone") -> None:
        """One decoded envelope from any transport."""
        t, d, now = msg["type"], msg["data"], self.clock()
        if t == P.SENSOR:
            self._on_sensor(msg, now)
        elif t == P.FRAME:
            self._on_frame_msg(msg, now)
        elif t == P.PROFILE:
            if role != "profiler":
                return   # a profile decides the hook and the words on the wall
            self.stats["profile"] += 1
            self._on_profile(d, now)
            self.emit(self._fwd(msg), {"oracle"})
        elif t == P.ORACLE:
            if role in ("oracle", "profiler") and self.machine.on_oracle(d):
                self.stats["oracle"] += 1
                text = d.get("phone_text")
                if isinstance(text, str) and text.strip():
                    self.emit(P.make(P.PHONE, {"text": text.strip()[:120]}), {"phone"})
        elif t == P.REVEAL:
            if role != "profiler":
                return
            self.machine.on_reveal(d)
        elif t == P.ANSWER:
            if self.machine.visit.opted_out:
                return   # opted out: their words go nowhere
            self.machine.on_answer(str(d.get("text", "")))
            self.emit(self._fwd(msg), {"profiler"})
        elif t == P.PHONE:
            if role in ("profiler", "control"):
                self.emit(P.make(P.PHONE, d), {"phone"})
        elif t == P.CONTROL:
            if role == "control":
                self._on_control(d, now)
            else:
                plugins.report(log, "control-role", f"control message from role {role} ignored",
                               exc_info=False, level=logging.WARNING)
        elif t == P.HELLO:
            pass  # the hub records the role and sends the current state
        else:
            t = t[:40]
            if t not in self._unknown_types and len(self._unknown_types) < 32:
                self._unknown_types.add(t)
                log.info("ignoring message type %r", t)
            return
        self.tick(now)

    def _fwd(self, msg: dict) -> dict:
        out = dict(msg)
        out["rx_ts"] = time.time()
        return out

    def _on_sensor(self, msg: dict, now: float) -> None:
        if self.blackout:
            return  # blackout stops sensing
        d = msg["data"]
        self.stats["sensor"] += 1
        self.last_sensor_ts = time.time()
        kind = d.get("kind", "phone")
        if kind == "phone":
            clean = clean_sensor(d)
            self.sensor.update(clean)
            self._watch_cover(clean, now)
            d = {**d, **clean}            # the modules get the contract fields in their contract shapes
            msg = {**msg, "data": d}
            self.tilt.feed(d, now)
            plugins.call(self.visuals, "on_sensor", d)
            plugins.call(self.audio, "on_sensor", d)
        elif kind == "touch":
            d = {**d, "x": P.num(d.get("x")), "y": P.num(d.get("y"))}
            msg = {**msg, "data": d}
            self.sensor["touch"] = {"x": d["x"], "y": d["y"]}
        elif kind == "keys" and not self.machine.visit.opted_out:
            self.machine.on_answer(str(d.get("text", "")))
        elif kind == "choice" and not self.machine.visit.opted_out:
            self.machine.on_answer(str(d.get("option", "")))
        self.presence.feed(d, now)       # still needed after an opt-out: to see them leave
        if self.machine.visit.opted_out:
            return   # opted out: nothing more is read about them until the visit ends
        if self.machine.phase in ("approach", "profiling", "hook"):
            self.fallback.feed(d)
        if self.profiler is not None:
            # the engine's clock, not the sender's ts: the N900's clock can be years off
            self._from_profiler(plugins.call(self.profiler, "on_sensor", d, now), now)
        self.emit(self._fwd(msg), {"profiler"})

    def _watch_cover(self, clean: dict, now: float) -> None:
        """Covering the proximity sensor for 3 s opts out. The profiler watches for it too;
        this makes the promise hold when no profiler is running (fallback mode)."""
        if "proximity" in clean:
            near = clean["proximity"]["near"]
            self._near_since = (self._near_since if self._near_since is not None else now) if near else None
        m = self.machine
        if (self._near_since is not None and now - self._near_since >= OPT_OUT_COVER_S
                and m.phase in ("approach", "profiling", "hook") and not m.visit.opted_out):
            vid = m.visit.visitor_id
            self._on_profile({"visitor_id": vid, "phase": "opted_out", "wiped": True}, now)
            visit = {"visitor_id": vid, "phase": m.phase, "opt_out": True}
            self.emit(P.make(P.VISIT, visit), {"profiler"})
            self.emit(P.make(P.PROFILE, {"visitor_id": vid, "phase": "opted_out", "wiped": True}), {"oracle"})
            plugins.call(self.profiler, "on_visit", visit, now)

    def _from_profiler(self, result: Any, now: float) -> None:
        """What an in-process profiler hands back: a profile, a reveal, or None."""
        if not isinstance(result, dict):
            return
        result.setdefault("visitor_id", self.machine.visit.visitor_id)
        if result.get("type") == P.REVEAL:
            self.machine.on_reveal(result)
        else:
            self.stats["profile"] += 1
            self._on_profile(result, now)
            self.emit(P.make(P.PROFILE, {k: v for k, v in result.items() if k != "type"}), {"oracle"})

    def _on_profile(self, d: dict, now: float) -> None:
        was_out = self.machine.visit.opted_out
        self.machine.on_profile(d, now)
        if self.machine.visit.opted_out and not was_out:
            # covered the phone: the frames and the figure drawn from them go now, not at the end
            self.frames.reset()
            self.fallback.reset()
            plugins.call(self.visuals, "on_wipe")

    def _on_frame_msg(self, msg: dict, now: float) -> None:
        if self.blackout or self.machine.visit.opted_out:
            return   # covered the phone: no more pictures of them, not even in RAM
        if now - self._last_frame_in < 0.09:
            return   # the phone sends at most 4 fps; a flood shouldn't eat the Pi's CPU
        self._last_frame_in = now
        self.emit(self._fwd(msg), {"profiler"})
        if self.profiler is not None:
            self._from_profiler(plugins.call(self.profiler, "on_frame", msg["data"], now), now)
        rgb = self.frames.decode(msg["data"])
        if rgb is not None:
            self._use_frame(rgb, now)

    def on_jpeg(self, jpeg: bytes) -> None:
        """A JPEG from the raw TCP camera stream (port 8767)."""
        now = self.clock()
        if self.blackout or self.machine.visit.opted_out or now - self._last_frame_t < 0.1:   # at most 10 fps
            return
        data = {"fmt": "jpeg", "b64": base64.b64encode(jpeg).decode("ascii")}
        self._on_frame_msg(P.make(P.FRAME, data), now)
        self.tick(now)

    def _use_frame(self, rgb, now: float) -> None:
        self._last_frame_t = now
        self.stats["frame"] += 1
        feats = self.frames.analyze(rgb)
        # camera cues join the phone's reading; the explicit "presence" from the phone still wins
        merged = dict(self.sensor)
        for k, v in feats.items():
            merged[k] = max(v, merged.get(k, 0)) if k in ("motion", "faces") else v
        merged.pop("kind", None)
        self.sensor.update(feats)
        self.presence.feed(merged, now)
        plugins.call(self.visuals, "on_frame", rgb)

    def _on_control(self, d: dict, now: float) -> None:
        cmd, arg = d.get("cmd"), d.get("arg")
        log.info("control: %s %s", cmd, "" if arg is None else arg)
        if cmd == "wipe":
            self.machine.force("wipe", now)
        elif cmd == "next":
            self.machine.next(now)
        elif cmd == "blackout":
            self.blackout = (not self.blackout) if arg is None else bool(arg)
            if self.blackout:
                self.presence.reset()
                self.tilt.reset()
                self.sensor.clear()
                self.frames.reset()
        elif cmd == "scene":
            self.override_scene = str(arg)[:40] if arg else None
        elif cmd == "hook":
            if arg:
                self.machine.visit.hook = str(arg)[:40]
                self.machine.visit.hook_since = now
        elif cmd == "volume":
            plugins.call(self.audio, "set_volume", P.num(arg, 0.8))

    # ------------------------------------------------------------------ clock
    def tick(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        flip = self.presence.tick(now)
        if flip is not None:
            log.info("presence %s (score %.2f)", "on" if flip else "off", self.presence.score)
        self.machine.on_presence(self.presence.present, now)
        changes = self.machine.drain_changes()
        for old, new in changes:
            self._on_phase(old, new, now)
        self.tilt.tick(now)
        self.state = director.build_state(self.machine, now, self.sensor,
                                          self.override_scene, self.blackout,
                                          self.tilt.state(), round(self.tilt.shake, 3))
        self.state["steer"] = self.tilt.steer()
        self.state["mode"] = self.mode
        plugins.call(self.visuals, "on_state", self.state)
        plugins.call(self.audio, "on_state", self.state)
        if changes or now - self._last_state_emit >= self._state_period:
            self._last_state_emit = now
            self.emit(P.make(P.STATE, self.state), None)
        return self.state

    def _on_phase(self, old: str, new: str, now: float) -> None:
        log.info("phase %s -> %s", old, new)   # no visitor ids in the log
        m = self.machine
        if new == "approach":
            self.stats["visits"] += 1
            self.fallback.reset()
        if new == "hook" and m.visit.hook is None:
            prof = self.fallback.profile()
            if m.visit.ocean is None:
                m.visit.ocean = prof["ocean"]
                m.visit.confidence = prof["confidence"]
                m.visit.profile_source = "fallback"
            from .fallback_profile import pick_hook
            m.visit.hook = pick_hook(m.visit.ocean)
            m.visit.hook_since = now
        vid = m.visit.visitor_id or m.last_wiped_id
        if new != "idle":
            visit = {"visitor_id": vid, "phase": new}
            if new == "release":
                visit["reveal"] = True
            self.emit(P.make(P.VISIT, visit), {"profiler"})
            if self.profiler is not None:
                self._from_profiler(plugins.call(self.profiler, "on_visit", visit, now), now)
        line = self.cfg.get("phone_lines", {}).get(new)
        if isinstance(line, dict) and line:
            self.emit(P.make(P.PHONE, dict(line)), {"phone"})
        if new == "wipe":
            self._wipe_everything(m.last_wiped_id)

    def _wipe_everything(self, visitor_id: str | None) -> None:
        self._near_since = None
        self.fallback.reset()
        self.frames.reset()
        for k in ("touch",):
            self.sensor.pop(k, None)
        self.override_scene = None
        self.emit(P.make(P.WIPE, {"visitor_id": visitor_id or ""}), None)
        plugins.call(self.visuals, "on_wipe")
        plugins.call(self.audio, "on_wipe")
        plugins.call(self.profiler, "reset")

    def status(self) -> dict:
        return {
            "phase": self.machine.phase,
            "phase_t": round(self.machine.phase_t(self.clock()), 1),
            "present": self.presence.present,
            "presence_score": round(self.presence.score, 3),
            "blackout": self.blackout,
            "last_sensor_ts": self.last_sensor_ts,
            "counts": dict(self.stats),
            "modules": {
                "visuals": type(self.visuals).__module__ if self.visuals else None,
                "audio": type(self.audio).__module__ if self.audio else None,
                "profiler": type(self.profiler).__module__ if self.profiler else None,
            },
        }
