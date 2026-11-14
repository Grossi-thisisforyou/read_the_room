"""The words of INFINITE JEST, as data the show can load.

    from infinite_jest.text import Corpus
    corpus = Corpus.load()                       # applies cuts.json
    visit = corpus.visit()                       # one per visitor: no repeats, German budget
    visit.pick(surface="wall", beat="testing", hook="flesh", register="log")
    visit.pick(surface="phone", beat="lift")
    visit.reveal(profile_like_dict)              # the whole confession, line by line
    corpus.scrawl(hook="flesh", tone="cold")     # short static lines for hand-lettering
    corpus.prompts()                             # either/or prompts, profiler format

Lines and their tags live in corpus/lines.json (built from src/*.txt).
Read VOICE.md for the voice and ARC.md for when each beat plays.
Standard library only, Python 3.7+.
"""

import json
import os
import random
import string

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")

GERMAN_BUDGET = 3          # at most this many German moments per visit (VOICE.md)
TRAITS = ("O", "C", "E", "A", "N")

__all__ = ["Corpus", "Visit", "fill", "load"]


class _Missing(KeyError):
    pass


class _Ctx(dict):
    def __missing__(self, key):
        raise _Missing(key)


def _derive(ctx):
    """Values the corpus uses that are computed from other values."""
    c = _Ctx((k, v) for k, v in (ctx or {}).items() if v is not None)
    feats = c.get("features")
    if isinstance(feats, dict):
        for k, v in feats.items():
            c.setdefault(k, v)
    if "dwell" in c and "clock" not in c:
        s = int(round(float(c["dwell"])))
        c["clock"] = "{:02d}:{:02d}".format(s // 60, s % 60)
    for low, up in (("scene", "SCENE"), ("segment", "SEGMENT"), ("trait", "TRAIT")):
        if low in c and up not in c:
            c[up] = str(c[low]).upper()
    return c


def fill(text, ctx=None):
    """Fill {placeholders} from ctx (and ctx['features']). None if a value is missing."""
    c = ctx if isinstance(ctx, _Ctx) else _derive(ctx)
    try:
        return string.Formatter().vformat(text, (), c)
    except (_Missing, ValueError, TypeError, IndexError):
        return None


def _needs_met(entry, ctx):
    choices = ctx.get("choices") or {}
    for n in entry.get("needs", []):
        if n.startswith("choice:"):
            spec = n[len("choice:"):]
            pid, _, opt = spec.partition("=")
            if pid not in choices or (opt and choices.get(pid) != opt):
                return False
        elif n not in ctx or ctx.get(n) in (None, "", False):
            return False
    return True


def _render(entry, text, ctx):
    out = fill(text, ctx)
    if out is None:
        return None
    return out.upper() if entry.get("register") == "log" else out


class Corpus:
    def __init__(self, lines, prompts, labels, oracle=None, cuts=(), german=True):
        self.cuts = set(cuts)
        self.german = german
        self.all = list(lines)
        self.lines_ = [e for e in lines if e["id"] not in self.cuts
                       and (german or e.get("lang", "en") != "de")]
        self.by_id = {e["id"]: e for e in self.all}
        self._prompts = [p for p in prompts if p.get("id") not in self.cuts]
        self.labels = labels
        self.oracle = oracle or {}

    @classmethod
    def load(cls, folder=CORPUS, german=True, cuts_file=None):
        def read(name, default):
            p = os.path.join(folder, name)
            if not os.path.exists(p):
                return default
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        lines = read("lines.json", {"lines": []})["lines"]
        prompts = read("prompts.json", {"prompts": []})["prompts"]
        labels = read("labels.json", {})
        oracle = read("oracle.json", {})
        cuts = read(cuts_file or "cuts.json", {"cut": []})
        return cls(lines, prompts, labels, oracle, cuts.get("cut", []), german)

    # ---- selection -----------------------------------------------------------
    def lines(self, **tags):
        """Entries whose tags match. A tag value may be a tuple of allowed values.

        surface="wall" also matches lines tagged surface=any.
        """
        out = []
        for e in self.lines_:
            good = True
            for k, want in tags.items():
                if want is None:
                    continue
                have = e.get(k)
                allowed = want if isinstance(want, (tuple, list, set)) else (want,)
                if k == "surface" and have == "any":
                    continue
                if have not in allowed:
                    good = False
                    break
            if good:
                out.append(e)
        return out

    def prompts(self, pace=None):
        if pace is None:
            return list(self._prompts)
        return [p for p in self._prompts if p.get("pace", "any") in ("any", pace)]

    def scene_name(self, hook):
        return self.labels.get("scenes", {}).get(hook, "the dark")

    def segment(self, pole):
        """pole like 'E+' -> {'label', 'alt', 'audience'}"""
        return self.labels.get("segments", {}).get(pole, {"label": "unread", "audience": ""})

    def scrawl(self, hook=None, phase=None, tone=None, max_chars=24, register=("log", "whisper")):
        """Short static lines for the visuals' hand-lettered layer, UPPERCASE."""
        out = []
        for e in self.lines(hook=hook, phase=phase, tone=tone, register=register, lang="en"):
            if e.get("static") and e.get("chars", 99) <= max_chars and "text" in e:
                out.append(e["text"].upper())
        return out

    def visit(self, rng=None):
        return Visit(self, rng)


class Visit:
    """Text for one visitor: never the same line twice, German at most 3 times."""

    def __init__(self, corpus, rng=None):
        self.c = corpus
        self.rng = rng or random.Random()
        self.used = set()
        self.german_used = 0

    def pick(self, ctx=None, **tags):
        """One filled line (str) matching the tags, or None. Prefers unused lines."""
        c = _derive(ctx)
        pool = [e for e in self.c.lines(**tags) if "text" in e and _needs_met(e, c)]
        if self.german_used >= GERMAN_BUDGET:
            pool = [e for e in pool if e.get("lang") != "de"]
        fresh = [e for e in pool if e["id"] not in self.used] or pool
        self.rng.shuffle(fresh)
        for e in fresh:
            out = _render(e, e["text"], c)
            if out is not None:
                self._use(e)
                return out
        return None

    def pick_entry(self, ctx=None, **tags):
        """Like pick() but returns (entry, text) so callers can see the id and tags."""
        c = _derive(ctx)
        pool = [e for e in self.c.lines(**tags) if "text" in e and _needs_met(e, c)]
        fresh = [e for e in pool if e["id"] not in self.used] or pool
        self.rng.shuffle(fresh)
        for e in fresh:
            out = _render(e, e["text"], c)
            if out is not None:
                self._use(e)
                return e, out
        return None, None

    def sequence(self, ctx=None, prefer_needs=True, **tags):
        """One version of a sequence (consent, confession, wipe) as a list of lines.

        Versions with a specific need that is met (e.g. the visitor chose
        'forgotten') win over generic ones.
        """
        c = _derive(ctx)
        pool = [e for e in self.c.lines(**tags) if "lines" in e and _needs_met(e, c)]
        if self.german_used >= GERMAN_BUDGET:
            pool = [e for e in pool if e.get("lang") != "de"]
        if prefer_needs:
            special = [e for e in pool if any(n.startswith("choice:") for n in e.get("needs", []))]
            pool = special or pool
        self.rng.shuffle(pool)
        for e in pool:
            out = [_render(e, t, c) for t in e["lines"]]
            if all(o is not None for o in out):
                self._use(e)
                return out
        return []

    def _use(self, e):
        self.used.add(e["id"])
        if e.get("lang") == "de":
            self.german_used += 1

    # ---- the confession ---------------------------------------------------
    def reveal(self, p):
        """Build the full reveal from a profile-like dict.

        Keys (all optional): evidence [(conf, trait, feature, raw, sign)],
        ocean {O..N}, trait_confidence {O..N}, confidence, segment_pole 'E+',
        hook, scenes_tried, seconds, choices {prompt_id: option}, vid,
        visits_today, opted_out.
        Returns {"header", "lines", "wipe", "label", "n_confession"}: the last
        n_confession entries of "lines" are the confession proper (type them
        slower); the ones before are evidence, numbers, segment and scene.
        """
        ctx = dict(p)
        ctx.setdefault("dwell", p.get("seconds"))
        seconds = float(p.get("seconds") or 0)
        lines = []
        if p.get("opted_out"):
            lines = self.sequence(ctx, surface="wall", beat="confession.optout")
            return {"header": "", "lines": lines,
                    "wipe": ["nothing about you was kept."], "label": "", "n_confession": len(lines)}
        header = self.pick(ctx, surface="wall", beat="header") or "FILE"
        if seconds and seconds < 15:
            lines = self.sequence(ctx, surface="wall", beat="confession.short")
            return {"header": header, "lines": lines,
                    "wipe": self.sequence(ctx, surface="wall", beat="deletion") or
                    ["nothing about you was kept."], "label": "", "n_confession": len(lines)}

        seen = set()
        for ev in p.get("evidence", [])[:12]:
            _c, trait, feat, raw, sign = ev
            if feat in seen or len(seen) >= 4:
                continue
            fctx = dict(ctx)
            if feat.startswith("choice:"):
                fctx["option"] = raw
                need = "option"
            else:
                fctx[feat] = raw
                need = feat
            cands = [x for x in self.c.lines(surface="wall", beat="observe") if need in x.get("needs", [])]
            self.rng.shuffle(cands)
            obs = None
            for x in cands:
                obs = _render(x, x["text"], _derive(fctx))
                if obs:
                    self._use(x)
                    break
            if not obs:
                continue
            pole = "{}{}".format(trait, "+" if sign > 0 else "-")
            inf = self.pick(ctx, surface="wall", beat="infer", pole=pole) or ""
            seen.add(feat)
            lines.append("{}. {}".format(obs, inf).strip())

        ocean = p.get("ocean") or {}
        conf = p.get("trait_confidence") or {}
        names = self.c.labels.get("traits", {})
        for t in TRAITS:
            if t in ocean:
                tl = self.pick({"trait": names.get(t, t), "value": ocean[t], "conf": conf.get(t, 0)},
                               surface="wall", beat="traits")
                if tl:
                    lines.append(tl)
        label = ""
        if p.get("segment_pole"):
            seg = self.c.segment(p["segment_pole"])
            label = seg.get("label", "")
            sl = self.pick({"segment": label}, surface="wall", beat="segment")
            if sl:
                lines.append(sl)
            if seg.get("audience"):
                lines.append(seg["audience"])
        if p.get("hook"):
            sc = self.pick({"scene": self.c.scene_name(p["hook"]),
                            "n_scenes": p.get("scenes_tried") or 1},
                           surface="wall", beat="scene")
            if sc:
                lines.append(sc)
            why = self.pick(ctx, surface="wall", beat="why")
            if why:
                lines.append(why)
        confession = self.sequence(ctx, surface="wall", beat="confession")
        lines += confession
        wipe = self.sequence(ctx, surface="wall", beat="deletion") or ["nothing about you was kept."]
        return {"header": header, "lines": lines, "wipe": wipe, "label": label,
                "n_confession": len(confession)}


def load(**kw):
    return Corpus.load(**kw)
