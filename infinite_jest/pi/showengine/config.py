"""Settings: built-in defaults, overridden by a TOML file, overridden by flags.

The installer copies config/default.toml to ~/.config/infinite-jest/engine.toml;
edit that one on the Pi. Unknown keys are kept, so the visuals, audio and
profiler modules can read their own sections ([visuals], [audio], [profiler]).
"""
from __future__ import annotations

import copy
import logging
import tomllib
from pathlib import Path
from typing import Any

log = logging.getLogger("showengine.config")

DEFAULTS: dict[str, Any] = {
    "network": {
        "host": "0.0.0.0",
        "port": 8765,          # HTTP + WebSocket (/ws), phone app at /phone/
        "udp_port": 8766,      # same JSON envelope, one per datagram (sensor only); 0 = off
        "tcp_port": 8767,      # raw back-to-back JPEGs from the N900 camera; 0 = off
        # peers allowed the roles that can wipe the room or write on the wall (see hub.py)
        "privileged_from": ["127.0.0.1", "::1", "192.168.1.0/24"],
    },
    "display": {
        "enabled": True,
        "fullscreen": True,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "show_debug": False,
        "second_screen": True,  # HDMI 1: the room's telemetry; skipped quietly if there's no second display
        "second_display": 1,
        "second_fps": 10,   # overlay with phase / presence; also toggled with D
        "retry_s": 5.0,        # no display (projector off): try again this often
    },
    "presence": {},            # see presence.PresenceConfig
    "visit": {},               # see visit.VisitConfig
    "modules": {
        "visuals": "infinite_jest.visuals",
        "audio": "infinite_jest.audio",
        "profiler": "infinite_jest.profiler",
        "text": "infinite_jest.text",   # the voice of the room (corpus); [phone_lines] if missing
        "use_fallbacks": True,  # built-in look and sound if a module is missing
        "profiler_in_process": True,
    },
    "phone_lines": {
        "approach": {"text": "I see you."},
        "profiling": {"ask": "What do you never tell anyone?"},
        "hook": {"text": "This part was made for you."},
        "release": {"text": "Thank you for your data."},
        "wipe": {"text": "Deleted. Nothing about you was kept."},
    },
    "visuals": {},
    "audio": {"audio_device": "default", "volume": 0.8},
    "profiler": {},
    "mode": "handheld",        # "handheld": picking the N900 up starts a visit; "fixed": camera/room cues do
    "show": "duet",            # "duet": TV (channel 1) face + projector (channel 2) wall; "classic": one projector
    "duet": {
        "tv_display": 0,       # HDMI 0 (next to the power socket): the TV
        "wall_display": 1,     # HDMI 1: the projector on the wall
        "tv_at_s": 45.0,       # seconds of someone being there before the TV wakes up
        "grow_s": 150.0,       # seconds for the grey face to become the guest
        "guest": "001",        # the guest file used for this run ("" for none)
        "wall_fps": 8.0,       # new frames per second from the wall network (cross-faded to 30)
        "face_fps": 6.0,
    },
    "discreet": True,          # gather in the background; show what it learned only in the confession
    "speak": True,             # the room says its answers aloud (audio module + espeak-ng; silent without)
    "invite_after_s": 25.0,    # a silent visitor is asked to speak once, this long into the hook
    "build_s": 90.0,           # seconds for the visitor's figure to come together (state.build 0..1)
    "state_hz": 10,            # how often "state" goes out
    "log_level": "INFO",
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        p = Path(path).expanduser()
        if p.exists():
            with p.open("rb") as f:
                cfg = _merge(cfg, tomllib.load(f))
            log.info("config: %s", p)
        else:
            log.warning("config file %s not found, using defaults", p)
    if overrides:
        cfg = _merge(cfg, overrides)
    return cfg
