"""Optional wall-text corpus for the hand-lettered layer.

The words thread keeps its lines in infinite_jest/text/corpus/lines.json
(entries tagged phase, hook, tone, register; `scrawl: true` marks short static
lines meant for hand-lettering). This module finds them, if they are there:

  1. config["corpus_path"]: a lines.json file or a folder holding one
  2. the infinite_jest.text package (Corpus.load(), which applies cuts.json)
  3. infinite_jest/text/corpus/lines.json next to this package

and gives back UPPERCASE short lines for a hook, phase and tone. If nothing is
found, or anything goes wrong, words() returns [] and the engine uses its own
built-in vocabulary. It never raises.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# the piece's internal names (hooks, palettes) never go on the wall
BLOCK = {"MEAT", "FLESH", "SCRAWL", "INVERTED", "HOOK", "CROWN", "SKULL", "BRUISE", "SODIUM"}


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _entries_from_file(path):
    if os.path.isdir(path):
        folder = path if os.path.exists(os.path.join(path, "lines.json")) else os.path.join(path, "corpus")
        path = os.path.join(folder, "lines.json")
    data = _read_json(path, None)
    if data is None:
        return None
    lines = data.get("lines", []) if isinstance(data, dict) else data
    cuts = _read_json(os.path.join(os.path.dirname(path), "cuts.json"), {}) or {}
    cut = set(cuts.get("cut", [])) if isinstance(cuts, dict) else set()
    out = []
    for e in lines:
        if isinstance(e, str):
            out.append({"text": e, "scrawl": len(e) <= 24})
        elif isinstance(e, dict) and e.get("id") not in cut:
            out.append(e)
    return out


class WallText:
    def __init__(self, config=None):
        self.entries = []
        self.source = None
        self._cache = {}
        self.reload(config)

    def reload(self, config=None):
        config = config or {}
        entries = None
        try:
            path = config.get("corpus_path")
            if path:
                entries = _entries_from_file(path)
                self.source = path if entries else None
            if not entries:
                try:
                    from ..text import Corpus  # the words thread's package, if installed
                    entries = list(Corpus.load().lines())
                    self.source = "infinite_jest.text"
                except Exception:
                    entries = None
            if not entries:
                p = os.path.join(os.path.dirname(HERE), "text", "corpus", "lines.json")
                entries = _entries_from_file(p)
                self.source = p if entries else None
        except Exception:
            entries = None
        self.entries = entries or []
        self._cache = {}

    def words(self, hook=None, phase=None, tone=None, max_chars=24):
        """Short UPPERCASE lines: the ones tagged for this hook first, then the
        general ones (no hook tag), matching phase and tone where tagged."""
        key = (hook, phase, tone, max_chars)
        if key in self._cache:
            return self._cache[key]
        own, general = [], []
        try:
            for e in self.entries:
                text = e.get("text")
                if not text or e.get("lang", "en") != "en":
                    continue
                if not (e.get("scrawl") or (e.get("static") and e.get("chars", len(text)) <= max_chars)):
                    continue
                if len(text) > max_chars or "{" in text:
                    continue
                if BLOCK & set(text.upper().replace(",", " ").replace(".", " ").split()):
                    continue
                if phase and e.get("phase") not in (None, phase):
                    continue
                if tone and e.get("tone") not in (None, tone):
                    continue
                h = e.get("hook")
                if h == hook and hook:
                    own.append(text.upper())
                elif h is None:
                    general.append(text.upper())
        except Exception:
            own, general = [], []
        out = own * 2 + general  # hook lines count double
        self._cache[key] = out
        return out
