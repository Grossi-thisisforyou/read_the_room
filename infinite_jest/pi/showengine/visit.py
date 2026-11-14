"""One visit, one person: the state machine at the heart of the show.

    idle --arrive--> approach --(stays)--> profiling --(profile or timeout)--> hook
      ^                 |                     |                                 |
      |              (leaves)              (leaves)                (leaves / max time)
      |                 v                     v                                 v
      +----- wipe <---------------------- release <-----------------------------+

Pure logic: no I/O and no clock of its own. The engine calls `tick(now)` and the
`on_*` methods with the current time, and reads back what changed. That makes the
whole performance testable in milliseconds.

Everything personal lives in one `Visit` object. `wipe` replaces it with a fresh
one, so nothing about the last visitor survives in the engine.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .protocol import num

PHASES = ("idle", "approach", "profiling", "hook", "release", "wipe")
OCEAN_KEYS = ("O", "C", "E", "A", "N")


@dataclass
class VisitConfig:
    approach_time: float = 3.0        # seconds of presence before profiling starts
    min_profiling: float = 6.0        # never hook before this, even if confident
    profiling_timeout: float = 20.0   # then hook anyway with the fallback profile
    confidence_to_hook: float = 0.5
    hook_min_dwell: float = 8.0       # minimum seconds before a hook may change
    max_visit: float = 180.0          # nobody keeps the room forever
    release_time: float = 50.0        # the confession, typed line by line (text/ARC.md)
    wipe_time: float = 12.0           # the dossier struck out line by line, then idle


@dataclass
class Visit:
    """Everything the engine knows about the current visitor. Memory only."""
    visitor_id: str | None = None
    started: float | None = None
    ocean: dict[str, float] | None = None
    confidence: float = 0.0
    profile_source: str | None = None   # "profiler" or "fallback"
    hook: str | None = None
    hook_since: float | None = None
    hook_params: dict[str, Any] = field(default_factory=dict)
    words: list[str] = field(default_factory=list)
    reveal: dict[str, Any] | None = None
    answers: list[int] = field(default_factory=list)   # character counts only, never the text
    opted_out: bool = False
    profile_extra: dict[str, Any] = field(default_factory=dict)   # evidence tuples etc. for the reveal
    oracle_words: list[str] = field(default_factory=list)
    dossier: list[str] = field(default_factory=list)
    dwell: dict[str, float] = field(default_factory=dict)   # seconds each scene was really on, for the reveal
    dwell_t: float | None = None


def clean_ocean(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    out = {k: num(raw.get(k), 0.5) for k in OCEAN_KEYS}
    return out


# Baby keeps the visual sources hidden from visitors: these never reach the wall or the phone.
HIDDEN = re.compile(r"bacon|baselitz|basquiat|crown|skull|copyright|expressionis|jean[\s.-]*michel|"
                    r"\bsamo\b|\bfrancis\b|\(c\)|\btm\b|\bscrawl", re.I)


def visible_text(raw: Any, limit: int = 80) -> str:
    """One line a visitor may read, or "" if it must not be shown.

    Folds Unicode (full-width, accents, invisible characters) to plain ASCII
    first, so a disguised source name is still caught, and drops what cannot be
    folded (emoji, other scripts): the projector font has no glyphs for them
    and the sources include symbols (crowns, skulls, copyright marks).
    """
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return ""
    t = str(raw)
    if any(c in t for c in "\u00a9\u00ae\u2117\u2122\u24b8\u24d2\U0001f12f"):   # (c) (r) (tm) marks
        return ""
    t = unicodedata.normalize("NFKC", t)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(" " if unicodedata.category(c) == "Cc" else c for c in t
                if not unicodedata.combining(c) and unicodedata.category(c) not in ("Cf", "Co", "Cs", "Cn"))
    t = " ".join(t.split())[:limit]
    if not t or not t.isascii() or HIDDEN.search(t) or HIDDEN.search(re.sub(r"[^a-z]", "", t.lower())):
        return ""
    return t


def clean_words(raw: Any, limit: int = 24, width: int = 80) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = [visible_text(w, width) for w in raw]
    return [w for w in out if w][:limit]


class VisitMachine:
    def __init__(self, cfg: VisitConfig | None = None, now: float = 0.0):
        self.cfg = cfg or VisitConfig()
        self.phase = "idle"
        self.phase_since = now
        self.visit = Visit()
        self.present = False
        self.changes: list[tuple[str, str]] = []   # (old, new) since last drain
        self.last_wiped_id: str | None = None

    # ---- inputs -------------------------------------------------------------
    def on_presence(self, present: bool, now: float) -> None:
        self.present = present
        self.tick(now)

    def on_profile(self, data: dict, now: float) -> bool:
        """Accept a profile for the current visitor. Returns False if ignored."""
        if self.phase not in ("approach", "profiling", "hook"):
            return False
        vid = data.get("visitor_id")
        if vid is not None and vid != self.visit.visitor_id:
            return False  # stale message about someone already wiped
        if data.get("phase") == "opted_out" or data.get("wiped"):
            # the visitor covered the phone: drop what we have, go quiet until they leave
            self._forget_visitor()
            self.visit.hook, self.visit.hook_since, self.visit.opted_out = "void", now, True
            self.tick(now)
            return True
        if self.visit.opted_out:
            return False
        ocean = clean_ocean(data.get("ocean"))
        if ocean is not None:
            self.visit.ocean = ocean
        self.visit.confidence = num(data.get("confidence"), self.visit.confidence)
        src = data.get("source")
        self.visit.profile_source = src[:20] if isinstance(src, str) and src else "profiler"
        if isinstance(data.get("hook_params"), dict):
            self.visit.hook_params = dict(data["hook_params"])
        for k in ("evidence", "trait_confidence", "segment_pole", "scenes_tried", "choices"):
            if k in data:
                self.visit.profile_extra[k] = data[k]
        ev = clean_words(data.get("words")) or clean_words(data.get("evidence"))   # readable lines first
        line = visible_text(self.visit.hook_params.get("line"))
        if line:
            ev = [line] + ev
        if ev:
            self.visit.words = ev[:24]
        hook = data.get("hook")
        if isinstance(hook, str) and hook:
            self._propose_hook(hook[:40], now)
        self.tick(now)
        return True

    def on_reveal(self, data: dict) -> bool:
        vid = data.get("visitor_id")
        if self.phase not in ("hook", "release") or (vid is not None and vid != self.visit.visitor_id):
            return False
        if self.visit.opted_out:
            return False
        self.visit.reveal = {
            # whole sentences: don't cut them mid-word
            "lines": clean_words(data.get("lines"), 12, 160),
            "label": visible_text(data.get("label", "")),
        }
        return True

    def on_oracle(self, data: dict) -> bool:
        """Text from the local language model. Wins over the profiler's canned lines."""
        vid = data.get("visitor_id")
        if self.phase not in ("approach", "profiling", "hook", "release") or self.visit.opted_out:
            return False
        if vid is not None and vid != self.visit.visitor_id:
            return False
        w = clean_words(data.get("words"))
        if w:
            self.visit.oracle_words = w
        d = clean_words(data.get("dossier"))
        if d:
            self.visit.dossier = d
        return True

    def on_answer(self, text: str) -> None:
        if self.phase in ("approach", "profiling", "hook") and text:
            self.visit.answers = (self.visit.answers + [len(str(text))])[-8:]   # the count, not the words

    def force(self, phase: str, now: float) -> None:
        """Operator override (from the control role)."""
        if phase in PHASES:
            if phase in ("approach", "profiling") and self.visit.visitor_id is None:
                self._new_visit(now)
            self._go(phase, now)

    def next(self, now: float) -> None:
        order = {"idle": "approach", "approach": "profiling", "profiling": "hook",
                 "hook": "release", "release": "wipe", "wipe": "idle"}
        self.force(order[self.phase], now)

    # ---- clock --------------------------------------------------------------
    def tick(self, now: float) -> None:
        c = self.cfg
        v = self.visit
        if self.phase == "hook" and v.hook and v.dwell_t is not None:
            v.dwell[v.hook] = v.dwell.get(v.hook, 0.0) + min(1.0, max(0.0, now - v.dwell_t))
        v.dwell_t = now
        t = now - self.phase_since
        p = self.phase
        if p == "idle":
            if self.present:
                self._new_visit(now)
                self._go("approach", now)
        elif p == "approach":
            if not self.present:
                self._go("wipe", now)          # barely here: nothing to reveal
            elif t >= c.approach_time:
                self._go("profiling", now)
        elif p == "profiling":
            if not self.present:
                self._go("wipe" if self.visit.opted_out else "release", now)   # opted out: nothing to reveal
            elif t >= c.min_profiling and self.visit.confidence >= c.confidence_to_hook:
                self._go("hook", now)
            elif t >= c.profiling_timeout:
                self._go("hook", now)
        elif p == "hook":
            if not self.present or self._visit_age(now) >= c.max_visit:
                self._go("wipe" if self.visit.opted_out else "release", now)
        elif p == "release":
            if t >= c.release_time:
                self._go("wipe", now)
        elif p == "wipe":
            if t >= c.wipe_time:
                self._go("idle", now)
                if self.present:              # someone is still (or already) there
                    self._new_visit(now)
                    self._go("approach", now)

    def phase_t(self, now: float) -> float:
        return max(0.0, now - self.phase_since)

    def drain_changes(self) -> list[tuple[str, str]]:
        ch, self.changes = self.changes, []
        return ch

    # ---- internals ----------------------------------------------------------
    def _visit_age(self, now: float) -> float:
        return 0.0 if self.visit.started is None else now - self.visit.started

    def _new_visit(self, now: float) -> None:
        self.visit = Visit(visitor_id="v-" + secrets.token_hex(2), started=now)

    def _propose_hook(self, hook: str, now: float) -> None:
        v = self.visit
        if hook == v.hook:
            return
        if v.hook is None or v.hook_since is None or now - v.hook_since >= self.cfg.hook_min_dwell:
            v.hook = hook
            v.hook_since = now

    def _go(self, phase: str, now: float) -> None:
        if phase == self.phase:
            return
        old = self.phase
        self.phase = phase
        self.phase_since = now
        if phase == "hook" and self.visit.hook is None:
            self.visit.hook_since = now   # director fills hook from fallback
        if phase == "wipe":
            self.wipe()
        self.changes.append((old, phase))

    def _forget_visitor(self) -> None:
        """Drop everything said or guessed about the visitor; the visit itself goes on."""
        v = self.visit
        for lst in (v.words, v.answers, v.oracle_words, v.dossier):
            for i in range(len(lst)):
                lst[i] = ""
            lst.clear()
        v.hook_params.clear()
        v.profile_extra.clear()
        v.dwell.clear()
        if v.ocean:
            v.ocean.clear()
        v.ocean, v.confidence, v.reveal = None, 0.0, None

    def wipe(self) -> None:
        """Forget the visitor. Overwrite lists in place first, then drop the object."""
        self.last_wiped_id = self.visit.visitor_id
        self._forget_visitor()
        self.visit = Visit()
