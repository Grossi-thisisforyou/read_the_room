"""The voice of the room: which words go on the wall and the phone, and when.

Uses the text corpus in infinite_jest/text/ (its dramaturgy is text/ARC.md) when
it is installed, one corpus `Visit` per visitor so no line repeats. Without the
corpus it falls back to the [phone_lines] in the config and the profiler's words.

Beats it plays (ARC.md):
  idle       attract (one wall line every 25-40 s; attract.long after 10 min empty)
  approach   phone "lift"
  profiling  phone consent sequence, wall "calibration"/"testing" log lines
  hook       wall "testing" every 8-12 s with the hook's flavour, phone "deepening";
             "lock" once when the same hook wins twice, "stillness" after 5 s still,
             "shake" and "flip" as they happen, and "the hinge" once ~100-120 s in:
             one line, then 4 s near black
  release    the confession typed line by line (2 s per data line, 3.5 s per
             confession line), phone "confession"
  wipe       the dossier struck out bottom to top, the last line held 2 s,
             phone "deletion"

Counters for attract lines (visits_today, avg_stay, max_stay) are counts only.
Everything per visitor is dropped on wipe.
"""
from __future__ import annotations

import logging
import random
from typing import Any

from . import plugins

log = logging.getLogger("showengine.voice")

DATA_LINE_S = 2.0
CONFESSION_LINE_S = 3.5
HINGE_AT = (100.0, 120.0)
HINGE_DARK_S = 4.0


def load_corpus(module_name: str | None) -> Any | None:
    mod = plugins.load(module_name, "Corpus") if module_name else None   # a corpus, not a create() plugin
    if mod is None:
        return None
    try:
        corpus = mod.Corpus.load()
        log.info("voice: corpus %s (%d lines)", module_name, len(corpus.lines_))
        return corpus
    except Exception:
        log.exception("voice: corpus %s failed to load", module_name)
        return None


class Voice:
    def __init__(self, corpus: Any | None, phone_lines: dict | None = None, rng: random.Random | None = None):
        self.corpus = corpus
        self.phone_lines = phone_lines or {}
        self.rng = rng or random.Random()
        self.visits_today = 0
        self.stays: list[float] = []
        self.empty_since: float | None = 0.0
        self.attract_line: str | None = None
        self._next_attract = 0.0
        self._reset_visit()

    # ------------------------------------------------------------------ state
    def _reset_visit(self) -> None:
        self.v = None                     # corpus Visit, one per visitor
        self.wall: list[str] = []         # current wall words
        self.big: str | None = None       # one large line (stillness, hinge)
        self.hinge_at: float | None = None
        self.hinge_done = False
        self.hinge_until = -1.0
        self.lock_done = False
        self.last_hooks: list[str] = []
        self.still_said = False
        self.flip_prev = False
        self._next_wall = 0.0
        self._next_phone = 0.0
        self.reveal: dict | None = None   # {"header","lines","wipe","label","n_data"}
        self.hook_started: float | None = None
        self.visit_started: float | None = None

    def _pick(self, ctx: dict | None = None, **tags) -> str | None:
        if self.v is None:
            return None
        try:
            return self.v.pick(ctx or {}, **tags)
        except Exception:
            log.exception("voice: pick %s failed", tags)
            return None

    def _sequence(self, ctx: dict | None = None, **tags) -> list[str]:
        if self.v is None:
            return []
        try:
            return list(self.v.sequence(ctx or {}, **tags))
        except Exception:
            log.exception("voice: sequence %s failed", tags)
            return []

    def _ctx(self, m, now: float) -> dict:
        vis = m.visit
        dwell = 0.0 if self.visit_started is None else now - self.visit_started
        ctx: dict[str, Any] = {"dwell": round(dwell), "vid": vis.visitor_id, "hook": vis.hook,
                               "visits_today": self.visits_today}
        if vis.hook and self.corpus is not None:
            ctx["scene"] = self.corpus.scene_name(vis.hook)
        if vis.ocean:
            ctx["ocean"] = dict(vis.ocean)
        return ctx

    def attract_ctx(self) -> dict:
        n = len(self.stays)
        return {"visits_today": self.visits_today,
                "avg_stay": round(sum(self.stays) / n) if n else 0,
                "max_stay": round(max(self.stays)) if n else 0}

    # ------------------------------------------------------------------ phases
    def on_phase(self, new: str, m, now: float) -> list[dict]:
        """Returns phone messages (data dicts) to send."""
        phone: list[dict] = []
        if new == "approach":
            self._reset_visit()
            self.visits_today += 1
            self.visit_started = now
            self.empty_since = None
            if self.corpus is not None:
                self.v = self.corpus.visit(self.rng)
        if self.corpus is None:
            line = self.phone_lines.get(new)
            return [dict(line)] if isinstance(line, dict) and line else []

        ctx = self._ctx(m, now)
        if new == "approach":
            t = self._pick(ctx, surface="phone", beat="lift")
            if t:
                phone.append({"text": t})
        elif new == "profiling":
            seq = self._sequence(ctx, surface="phone", beat="consent")
            if seq:
                phone.append({"text": "\n".join(seq)})
            self.wall = [w for w in (self._pick(ctx, surface="wall", beat="calibration", register="log"),) if w]
        elif new == "hook":
            self.hook_started = now
            self.hinge_at = now + self.rng.uniform(*HINGE_AT)
        elif new == "release":
            self._build_reveal(m, now)
            seq = self._sequence(ctx, surface="phone", beat="confession")
            t = seq[0] if seq else self._pick(ctx, surface="phone", beat="confession")
            if t:
                phone.append({"text": t})
        elif new == "wipe":
            if self.visit_started is not None:
                self.stays.append(now - self.visit_started)
                self.stays = self.stays[-500:]
            t = self._pick(ctx, surface="phone", beat="deletion")
            if t:
                phone.append({"text": t})
        elif new == "idle":
            last = (self.reveal or {}).get("wipe", [])[-1:]
            self._reset_visit()                 # the dossier itself is gone now
            self.reveal = {"wipe": last} if last else None
            self.empty_since = now
            self._next_attract = now + 8.0      # afterimage first, then attract
        return phone

    def _build_reveal(self, m, now: float) -> None:
        vis = m.visit
        if self.v is None:
            return
        seconds = 0.0 if self.visit_started is None else now - self.visit_started
        p: dict[str, Any] = {"ocean": vis.ocean or {}, "confidence": vis.confidence, "hook": vis.hook,
                             "seconds": seconds, "vid": vis.visitor_id, "visits_today": self.visits_today,
                             "opted_out": vis.opted_out}
        p.update({k: v for k, v in vis.profile_extra.items() if k in
                  ("evidence", "trait_confidence", "segment_pole", "scenes_tried", "choices")})
        if not all(isinstance(e, (list, tuple)) and len(e) == 5 for e in p.get("evidence", [])):
            p.pop("evidence", None)         # the corpus wants (conf, trait, feature, raw, sign) tuples
        try:
            r = self.v.reveal(p)
        except Exception:
            log.exception("voice: reveal failed")
            return
        confession = r.get("n_confession")
        if not isinstance(confession, int) or confession < 0:
            confession = self._sequence_len_guess(r)
        lines = [x for x in ([r.get("header")] + list(r.get("lines", []))) if x]
        confession = min(confession, len(lines))
        self.reveal = {"header": r.get("header", ""), "lines": lines, "wipe": list(r.get("wipe", [])),
                       "label": r.get("label", ""), "n_data": max(0, len(lines) - confession),
                       "started": now}

    @staticmethod
    def _sequence_len_guess(r: dict) -> int:
        # older corpus without "n_confession": the confession is last and usually ~6 lines
        return min(6, len(r.get("lines", [])) // 2)

    # ------------------------------------------------------------------ clock
    def tick(self, m, now: float, steer: dict, phase_t: float) -> list[dict]:
        """Periodic beats. Returns phone messages to send."""
        phone: list[dict] = []
        if self.corpus is None:
            return phone
        p = m.phase
        if p == "idle":
            if now >= self._next_attract:
                long_empty = self.empty_since is not None and now - self.empty_since > 600
                beat = "attract.long" if long_empty else "attract"
                self.v = self.v or self.corpus.visit(self.rng)
                self.attract_line = self._pick(self.attract_ctx(), surface="wall", beat=beat)
                if self.attract_line is None and long_empty:
                    self.attract_line = self._pick(self.attract_ctx(), surface="wall", beat="attract")
                self.reveal = None
                self._next_attract = now + self.rng.uniform(25, 40) * (2 if long_empty else 1)
            return phone
        ctx = self._ctx(m, now)
        if p == "profiling" and now >= self._next_wall:
            w = self._pick(ctx, surface="wall", beat="testing", register="log")
            if w:
                self.wall = (self.wall + [w])[-6:]
            self._next_wall = now + self.rng.uniform(4, 6)
        if p == "hook":
            hook = m.visit.hook
            if hook and (not self.last_hooks or self.last_hooks[-1] != hook):
                self.last_hooks.append(hook)
            if now >= self._next_wall:
                w = self._pick(ctx, surface="wall", beat="testing", hook=hook, register=("log", "whisper")) \
                    or self._pick(ctx, surface="wall", beat="tailored", hook=hook)
                if w:
                    self.wall = (self.wall + [w])[-6:]
                self._next_wall = now + self.rng.uniform(8, 12)
            if now >= self._next_phone:
                t = self._pick(ctx, surface="phone", beat="deepening")
                if t:
                    phone.append({"text": t})
                self._next_phone = now + self.rng.uniform(15, 25)
            # lock: the same hook came back after another was tried
            if not self.lock_done and len(self.last_hooks) >= 3 and self.last_hooks[-1] == self.last_hooks[-3]:
                self.lock_done = True
                w = self._pick(ctx, surface="wall", beat="lock")
                if w:
                    self.wall = (self.wall + [w])[-6:]
            still = float(steer.get("still_s", 0) or 0)
            if still >= 5 and not self.still_said:
                self.still_said = True
                self.big = self._pick(ctx, surface="wall", beat="stillness")
            elif still < 1:
                self.still_said = False
                if self.big and now >= self.hinge_until:
                    self.big = None
            if steer.get("flip") and not self.flip_prev:
                w = self._pick(ctx, surface="wall", beat="flip")
                if w:
                    self.wall = (self.wall + [w])[-6:]
            self.flip_prev = bool(steer.get("flip"))
            if float(steer.get("shake", 0) or 0) > 0.7 and now >= self._next_wall - 6:
                w = self._pick(ctx, surface="wall", beat="shake")
                if w:
                    self.wall = (self.wall + [w])[-6:]
            # the hinge: once, only if the profile is solid enough (ARC: a wrong hinge is worse than none)
            if (not self.hinge_done and self.hinge_at is not None and now >= self.hinge_at
                    and m.visit.confidence >= 0.4 and not m.visit.opted_out):
                self.hinge_done = True
                line = self._pick(ctx, surface="wall", beat="hinge")
                if line:
                    self.big = line
                    self.hinge_until = now + HINGE_DARK_S
        return phone

    # ------------------------------------------------------------------ output
    def apply(self, state: dict, m, now: float) -> None:
        """Write the voice into the state (words, reveal progress, hinge)."""
        if self.corpus is None:
            return
        p = m.phase
        if p == "idle":
            if self.reveal and self.reveal.get("wipe"):        # afterimage: the last line, 8 s
                state["words"] = self.reveal["wipe"][-1:]
            elif self.attract_line:
                state["words"] = [self.attract_line]
            return
        if m.visit.opted_out:
            return
        if p in ("profiling", "hook") and not m.visit.oracle_words and self.wall:
            state["words"] = list(self.wall) + list(state.get("words") or [])[:2]
        if self.big:
            state["big_line"] = self.big
        if now < self.hinge_until:
            state["hinge"] = True
            state["intensity"] = min(state["intensity"], 0.05)
        r = self.reveal
        if p == "release" and r:
            t = now - r["started"]
            nd = r["n_data"]
            shown = int(t // DATA_LINE_S) + 1 if t < nd * DATA_LINE_S else nd + int((t - nd * DATA_LINE_S) // CONFESSION_LINE_S) + 1
            shown = min(len(r["lines"]), shown)
            state["reveal"] = {"header": r["header"], "label": r["label"], "lines": r["lines"][:shown],
                               "total": len(r["lines"])}
            state["words"] = r["lines"][:shown][-8:]
        elif p == "wipe" and r:
            n = len(r["lines"])
            t = m.phase_t(now)
            span = max(0.5, (m.cfg.wipe_time - 2.0 - 2.0))         # strike, then hold the last line 2 s
            struck = min(n, int(n * max(0.0, t) / span))
            state["reveal"] = {"header": r["header"], "label": r["label"], "lines": r["lines"],
                               "struck": struck, "wipe": r["wipe"], "total": n}
            state["words"] = r["wipe"][-1:] if struck >= n else r["lines"][: n - struck][-8:]

    def wipe(self) -> None:
        self._reset_visit()
