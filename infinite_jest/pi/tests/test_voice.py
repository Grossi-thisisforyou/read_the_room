"""The voice of the room, with the real text corpus if it's in the repo (or the project folder)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from showengine import protocol as P
from test_core import BUSY, EMPTY, make_engine, run

CANDIDATES = [Path(__file__).resolve().parents[2] / "text",
              Path(os.environ.get("IJ_TEXT_DIR", "/mnt/project-files/infinite_jest/text"))]


def _corpus():
    for d in CANDIDATES:
        if (d / "__init__.py").exists() and (d / "corpus" / "lines.json").exists():
            spec = importlib.util.spec_from_file_location("ij_text_under_test", d / "__init__.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod.Corpus.load()
    pytest.skip("infinite_jest/text corpus not available")


HOLD = {"kind": "phone", "held": True, "motion": 0.6, "tilt": {"alpha": 0, "beta": 10, "gamma": 5}}


def test_full_arc_with_corpus():
    corpus = _corpus()
    eng, clock, sent = make_engine(mode="handheld", short_ending=False, corpus=corpus)
    run(eng, clock, 40, EMPTY)                          # attract
    assert eng.state["phase"] == "idle" and eng.state["words"], "attract line on the wall"
    run(eng, clock, 30, HOLD)
    assert eng.state["phase"] == "hook"
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "confidence": 0.7, "hook": "flesh",
                                  "ocean": {"O": .6, "C": .4, "E": .7, "A": .5, "N": .6},
                                  "trait_confidence": {"O": .5, "C": .5, "E": .6, "A": .4, "N": .5},
                                  "segment_pole": "E+"}), "profiler")
    run(eng, clock, 100, HOLD)                         # long enough for the hinge
    hooks = {"flesh", "scrawl", "inverted", "mirror", "void"}
    phone = [m["data"].get("text", "") for m, r in sent if m["type"] == P.PHONE]
    assert len(phone) >= 3
    run(eng, clock, 10, {"kind": "phone", "held": False})   # put down -> release after 8 s
    assert eng.state["phase"] == "release"
    run(eng, clock, 20, {"kind": "phone", "held": False})
    rv = eng.state["reveal"]
    assert rv and 1 < len(rv["lines"]) < rv["total"] + 1, "typed line by line"
    run(eng, clock, 30, {"kind": "phone", "held": False})
    assert eng.state["phase"] == "wipe"
    run(eng, clock, 6, {"kind": "phone", "held": False})
    assert eng.state["reveal"]["struck"] > 0
    run(eng, clock, 7, {"kind": "phone", "held": False})
    assert eng.state["phase"] == "idle"
    assert eng.state["words"] and eng.state.get("reveal") is None
    assert eng.voice.reveal == {"wipe": eng.state["words"]}     # only the last line survives, briefly
    run(eng, clock, 45, EMPTY)
    assert eng.voice.reveal is None
    words = " ".join(eng.state["words"]).lower()
    assert not any(h in words.split() for h in hooks)
    assert eng.voice.visits_today == 1 and len(eng.voice.stays) == 1


def test_hinge_darkens_once():
    corpus = _corpus()
    eng, clock, _ = make_engine(mode="handheld", short_ending=False, corpus=corpus)
    run(eng, clock, 30, HOLD)
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "confidence": 0.8, "hook": "void"}), "profiler")
    dark = 0
    for _ in range(1300):
        clock.t += 0.1
        eng.handle(P.make(P.SENSOR, dict(HOLD)), "phone")
        if eng.state.get("hinge"):
            dark += 1
    assert eng.voice.hinge_done and 30 <= dark <= 41


def test_the_real_corpus_loads_through_the_engine_config():
    """The corpus is a library (Corpus), not a create() plugin; it must not be skipped."""
    from showengine import config as _config
    from showengine.voice import load_corpus
    corpus = load_corpus(_config.load(None)["modules"]["text"])
    assert corpus is not None
