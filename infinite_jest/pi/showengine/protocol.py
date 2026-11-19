"""The message format every part of the installation speaks.

One JSON object per message: {"type": str, "ts": float unix seconds, "data": {...}}.
Over WebSocket one message per frame, over UDP one per datagram, over HTTP POST
one envelope (or a JSON array of them) per request. See docs/CONTRACT.md.
"""
from __future__ import annotations

import json
import time
from typing import Any

# Types the engine understands. Anything else is ignored (and logged once).
SENSOR = "sensor"      # phone -> engine
FRAME = "frame"        # phone -> engine: one small camera image (gray8 or JPEG, base64)
ANSWER = "answer"      # phone -> engine: text the visitor typed on the slide-out keyboard
PROFILE = "profile"    # profiler -> engine
REVEAL = "reveal"      # profiler -> engine: end-of-visit lines
CONTROL = "control"    # Baby's laptop -> engine
HELLO = "hello"        # any client, first message: data["role"]
STATE = "state"        # engine -> everyone
VISIT = "visit"        # engine -> profiler: a visit began/changed phase
WIPE = "wipe"          # engine -> everyone: drop all visitor data now
ORACLE = "oracle"      # oracle (local Qwen) -> engine: {visitor_id, words, phone_text, dossier}
PHONE = "phone"        # engine/profiler/control -> phone: {text?, ask?, mood?} shown on the phone

ROLES = {"phone", "profiler", "visuals", "audio", "control", "oracle"}

MAX_MESSAGE_BYTES = 512 * 1024  # a 320x240 JPEG in base64 is ~30 KB


class BadMessage(ValueError):
    pass


def make(type_: str, data: dict[str, Any] | None = None, ts: float | None = None) -> dict:
    return {"type": type_, "ts": time.time() if ts is None else ts, "data": data or {}}


def encode(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"), allow_nan=False)


def _no_constants(name: str) -> Any:
    # Python's json accepts NaN / Infinity; they would poison every later encode()
    raise ValueError(f"{name} is not valid JSON")


def _finite_float(text: str) -> float:
    v = float(text)
    if v != v or v in (float("inf"), float("-inf")):   # 1e999 overflows to inf
        raise ValueError("number out of range")
    return v


def loads(raw: str | bytes) -> Any:
    """Strict JSON from untrusted input: size-capped, no NaN/Infinity, no stack-busting nesting."""
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise BadMessage("message too large")
        raw = raw.decode("utf-8", "replace")
    elif len(raw) > MAX_MESSAGE_BYTES:
        raise BadMessage("message too large")
    try:
        return json.loads(raw, parse_constant=_no_constants, parse_float=_finite_float)
    except (ValueError, TypeError, RecursionError) as e:
        raise BadMessage(f"not JSON: {str(e)[:80]}") from None


def decode(raw: str | bytes) -> dict:
    """Parse and sanity-check one message. Raises BadMessage."""
    return check(loads(raw))


def check(msg: Any) -> dict:
    """Sanity-check one already-parsed envelope. Raises BadMessage."""
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise BadMessage("needs an object with a string 'type'")
    data = msg.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BadMessage("'data' must be an object")
    ts = num(msg.get("ts"), -1.0, None, None)
    if ts < 0:
        ts = time.time()
    return {"type": msg["type"], "ts": ts, "data": data}


def num(value: Any, default: float = 0.0, lo: float | None = 0.0, hi: float | None = 1.0) -> float:
    """Read a number from untrusted input, clamped; default if missing or junk."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        v = float(value)
    except OverflowError:       # a 400-digit integer from the network
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v
