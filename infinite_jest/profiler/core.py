"""The profiler: sensor messages in, profile / reveal messages out.

Interface agreed with the Pi show engine:

    p = create(config)
    out = p.on_sensor(data, ts)   # data = message["data"] of a "sensor" msg
    out = p.on_visit(data, ts)    # data = {"visitor_id", "phase"} from engine
    p.reset()                     # wipe; called by the engine between visitors

In-process, on_sensor / on_frame / on_visit return the newest message's data
dict with a "type" key ("profile" or "reveal"), or None. As a separate process,
handle(message) takes any contract envelope and returns a list of envelopes to
send back. All state lives in this object, in memory, and reset() drops it.
"""

import json
import os
import random
import uuid

from . import ocean as oc
from . import reveal as rv
from .features import Features
from .hooks import HOOKS, HookBandit, affinity, params
from .vision import Vision

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "emit_every": 1.0,          # seconds between profile messages
    "absence_end": 6.0,         # seconds of nobody before a visit ends
    "reveal_at": 80.0,          # auto-reveal if the engine never asks
    "hook_min_dwell": 8.0,      # seconds a hook runs before it may change
    "optout_cover_seconds": 3.0,  # cover the phone's sensor this long = opt out
    "seed": None,               # set for reproducible simulations
    "mode": "handheld",         # contract default; state.mode overrides
    "prompts_file": os.path.join(HERE, "prompts.json"),
}


def load_prompts(path):
    try:
        with open(path) as f:
            return {p["id"]: p for p in json.load(f)["prompts"]}
    except (OSError, ValueError, KeyError):
        return {}


class Profiler:
    def __init__(self, config=None):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(config or {})
        self.prompts = load_prompts(self.cfg["prompts_file"])
        self.rng = random.Random(self.cfg["seed"])
        self.features = Features(self.cfg["mode"])
        self.vision = Vision()
        self.bandit = HookBandit(seed=self.cfg["seed"], min_dwell=self.cfg["hook_min_dwell"])
        self.reset()

    # ------------------------------------------------------------- lifecycle
    def reset(self):
        """Forget everything about the current visitor."""
        self.features.reset()
        self.vision.reset()
        self.bandit.reset()
        self.visitor_id = None
        self.engine_ids = False
        self.phase = "idle"
        self.opted_out = False
        self.revealed = False
        self.last_emit = None
        self.last_seen = None
        self.visit_start = None
        self.last_profile = None

    def _start(self, ts, visitor_id=None):
        self.features.reset()
        self.bandit.reset()
        self.visitor_id = visitor_id or uuid.UUID(int=self.rng.getrandbits(128)).hex[:8]
        self.phase = "observing"
        self.opted_out = False
        self.revealed = False
        self.last_emit = None
        self.visit_start = ts
        self.last_seen = ts

    def _end(self, ts):
        self.bandit.finish(ts)
        vid = self.visitor_id
        self.reset()
        return [msg("profile", ts, {"visitor_id": vid, "phase": "ended", "wiped": True})]

    # ----------------------------------------------------------------- input
    def handle(self, message):
        """Dispatch one contract message {type, ts, data}; return replies."""
        t = message.get("type")
        # rx_ts is the Pi's receive time, added by the engine when it forwards
        # a phone message; the phone's own ts can be far off (no network time).
        ts = float(message.get("rx_ts") or message.get("ts") or 0.0)
        data = message.get("data") or {}
        if t == "sensor":
            return self._sensor(data, ts)
        if t == "answer":  # engine's name for a forwarded prompt answer
            return self._sensor(dict(data, kind="choice"), ts)
        if t == "frame":
            return self._frame(data, ts)
        if t in ("state", "visit"):
            return self._visit(data, ts)
        if t == "wipe":
            if not data.get("visitor_id") or data.get("visitor_id") == self.visitor_id:
                return self._end(ts) if self.visitor_id else []
            return []
        if t == "control" and data.get("cmd") in ("blackout", "wipe"):
            return self._end(ts) if self.visitor_id else []
        return []

    def _frame(self, data, ts):
        v = self.vision.frame(data)
        return self._sensor(v, ts) if v else []

    def _visit(self, data, ts):
        """Engine visit state. Contract phases: idle, approach, profiling,
        hook, release, wipe. 'reveal' is accepted too."""
        vid = data.get("visitor_id")
        phase = data.get("phase")
        if data.get("mode") in ("handheld", "fixed"):
            self.features.mode = data["mode"]
        out = []
        if phase in ("end", "ended", "wipe", "idle"):
            return self._end(ts) if self.visitor_id else []
        if vid and vid != self.visitor_id:
            self._start(ts, vid)
        if vid:
            self.engine_ids = True
        if data.get("opt_out"):
            return self._opt_out(ts)
        if (phase in ("reveal", "release") or data.get("reveal")) and not self.revealed and not self.opted_out \
                and self.visitor_id:
            out.append(self._reveal(ts))
        return out

    def _sensor(self, data, ts):
        if not isinstance(data, dict):
            return []
        kind = data.get("kind")
        # the N900 sends kind "optout" once, then {"kind": "phone", "optout": true} until the wipe
        if kind == "optout" or data.get("opt_out") or data.get("optout"):
            if self.opted_out:
                return []
            if self.visitor_id is None:
                self._start(ts)
            return self._opt_out(ts)
        present = self._presence(data)
        out = []
        if present:
            if self.visitor_id is None:
                self._start(ts)
            self.last_seen = ts
        elif (self.visitor_id is not None and not self.engine_ids
              and self.last_seen is not None
              and ts - self.last_seen > self.cfg["absence_end"]):
            return self._end(ts)
        if self.visitor_id is None or self.opted_out or self.revealed:
            return out
        self.features.add(data, ts)
        if self.features.covered_for(ts) >= self.cfg["optout_cover_seconds"]:
            return self._opt_out(ts)
        self.bandit.observe(self.features.engagement())
        if self.last_emit is None or ts - self.last_emit >= self.cfg["emit_every"]:
            out.append(self._profile(ts))
        if (not self.revealed and ts - self.visit_start >= self.cfg["reveal_at"]):
            out.append(self._reveal(ts))
        return out

    # ------------------------------------------- in-process engine interface
    # The engine calls these directly. Each returns the newest message's data
    # dict (a profile, or a reveal with "lines") or None.
    def on_sensor(self, data, ts):
        return _last(self._sensor(data, ts))

    def on_frame(self, data, ts):
        return _last(self._frame(data, ts))

    def on_visit(self, data, ts=None):
        return _last(self._visit(data, ts if ts is not None else (self.features.t_last or 0.0)))

    @staticmethod
    def _presence(data):
        kind = data.get("kind")
        if kind == "vision":
            return bool(data.get("present", True))
        if kind == "phone":
            if data.get("held") is True:
                return True
            p = data.get("presence")
            return bool(p) and (p is True or float(p) > 0.5)
        if kind in ("touch", "choice", "keys"):
            return True
        return False

    # ---------------------------------------------------------------- output
    def _estimate(self):
        return oc.estimate(self.features.summary(), self.features.choices, self.prompts)

    def _profile(self, ts):
        ocean, conf, overall, evidence = self._estimate()
        hook = self.bandit.choose(ocean, overall, ts)
        if self.phase == "observing" and overall >= 0.6:
            self.phase = "hooking"
        label = oc.segment(ocean, conf)[0] if overall >= 0.2 else "unread"
        self.last_emit = ts
        data = {
            "visitor_id": self.visitor_id,
            "phase": "reveal" if self.revealed else self.phase,
            "ocean": ocean,
            "confidence": overall,
            "trait_confidence": conf,
            "hook": hook,
            "hook_params": params(hook, ocean, conf, self.rng),
            "engagement": round(self.features.engagement(), 3),
            "segment": label,
            "hook_scores": {h: round(affinity(h, ocean), 3) for h in HOOKS},
            "features": {f: round(v[2], 3) for f, v in self.features.summary().items()},
            "evidence": ["{} -> {}{}".format(f, t, "+" if s > 0 else "-")
                         for _c, t, f, _r, s in evidence[:5]],
            "words": wall_words(evidence[:5]),
            "seconds": round(ts - self.visit_start, 1),
        }
        self.last_profile = data
        return msg("profile", ts, data)

    def _reveal(self, ts):
        ocean, conf, overall, evidence = self._estimate()
        self.bandit.finish(ts)
        r = rv.build(ocean, conf, overall, evidence, self.bandit.history,
                     self.bandit.ranking(), ts - self.visit_start)
        self.revealed = True
        self.phase = "reveal"
        r.update({"visitor_id": self.visitor_id, "ocean": ocean, "confidence": overall,
                  "trait_confidence": conf})
        return msg("reveal", ts, r)

    def _opt_out(self, ts):
        """Stop profiling this visitor and drop what was gathered."""
        vid = self.visitor_id
        self.features.reset()
        self.vision.reset()
        self.bandit.reset()
        self.opted_out = True
        self.phase = "opted_out"
        return [msg("profile", ts, {"visitor_id": vid, "phase": "opted_out",
                                    "hook": "void", "confidence": 0.0,
                                    "wiped": True})]


def wall_words(evidence):
    """The evidence as lines for the wall: what you did, and the trait it moved.
    e.g. "YOU TURNED IT THROUGH 140 DEGREES  O+". The engine scrawls these
    when the local model has nothing to say."""
    out, seen = [], set()
    for _c, trait, feat, raw, sign in evidence:
        line = rv._describe(feat, raw)
        line = line.split(" (")[0].upper()
        if line in seen:
            continue
        seen.add(line)
        out.append("{}  {}{}".format(line, trait, "+" if sign > 0 else "-")[:60])
    return out


def _last(msgs):
    if not msgs:
        return None
    m = msgs[-1]
    return dict(m["data"], type=m["type"])


def msg(type_, ts, data):
    return {"type": type_, "ts": ts, "data": data}


def create(config=None):
    return Profiler(config)
