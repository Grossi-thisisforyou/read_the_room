"""Long-run / Pi-budget regressions for the synth (found by pi/tools/soak.py).

Run: python3 -m pytest -q infinite_jest/audio/tests
"""
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from infinite_jest.audio import synth as S  # noqa: E402
from infinite_jest.audio import voices as V  # noqa: E402

HOOK = {"visitor_id": "v-1234", "phase": "hook", "hook": "flesh", "intensity": 0.8, "tempo": 134,
        "ocean": {"O": 0.9, "C": 0.2, "E": 0.8, "A": 0.1, "N": 0.9}}


def _settle(synth, blocks):
    """Render blocks, giving the helper the time real playback would."""
    for _ in range(blocks):
        out = synth.render_block()
        assert np.isfinite(out).all()
        deadline = time.monotonic() + 5
        while not synth.prep.idle() and time.monotonic() < deadline:
            time.sleep(0.003)


def test_render_block_never_builds_samples_itself(monkeypatch):
    """A rebuilt bank section or an 8 s riser costs 100-200 ms on x86 (x2.4-3.5
    on a Pi 5): made inside render_block it empties the 150 ms output buffer.
    With the helper they must come from the helper process, never inline."""
    synth = S.TechnoSynth(seed=1)
    try:
        assert synth.prep is not None
        synth.set_state(dict(HOOK))
        _settle(synth, 200)                       # first visitor sections arrive
        called = []

        def boom(name):
            def f(*a, **k):
                called.append(name)
                raise AssertionError(name + " made inside render_block")
            return f
        for name in ("kick", "hat", "clap", "clank", "metal", "swell", "stab", "tick", "impact",
                     "vox", "breath", "riser", "rumble"):
            monkeypatch.setattr(V, name, boom(name))
        st = dict(HOOK, ocean={"O": 0.1, "C": 0.9, "E": 0.1, "A": 0.95, "N": 0.05}, intensity=0.3)
        synth.set_state(st)                       # every section's key changes as the traits glide
        _settle(synth, 700)                       # ~15 s: several 8-bar phrases with risers
        st = dict(st, steer={"x": 0.0, "y": 0.0, "shake": 0.95})
        synth.set_state(st)                       # phone shake: stutter + noise riser
        _settle(synth, 60)
        assert called == []
        assert synth.bank_keys["c"] == synth._bank_keys()["c"]   # the new samples did arrive
    finally:
        synth.close()


def test_helper_samples_match_inline_samples():
    """Same seed and parameters -> the same sounds, whichever process made them."""
    import concurrent.futures as cf
    import multiprocessing as mp
    args = ("c", 12345, 0.7, 0.4, 0.6, 0.2, 0.8, 131.0)
    inline = S.build_section(*args)
    with cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
        remote = ex.submit(S.build_section, *args).result()
    assert inline.keys() == remote.keys()
    for k in inline:
        for a, b in zip(inline[k], remote[k]):
            np.testing.assert_array_equal(a, b)


def test_without_helper_is_unchanged_and_deterministic():
    a = S.TechnoSynth(seed=3, helper=False)
    b = S.TechnoSynth(seed=3, helper=False)
    for s in (a, b):
        s.set_state(dict(HOOK))
    for _ in range(300):
        np.testing.assert_array_equal(a.render_block(), b.render_block())


def test_wipe_drops_helper_results_for_the_old_visitor():
    synth = S.TechnoSynth(seed=1)
    try:
        synth.set_state(dict(HOOK))
        _settle(synth, 50)
        gen = synth.gen
        synth.set_state(dict(HOOK, ocean={"O": 0.0, "C": 1.0, "E": 0.0, "A": 1.0, "N": 0.0}))
        synth.render_block()
        synth.render_block()
        synth.set_state({"visitor_id": "v-1234", "phase": "wipe"})   # as the engine sends it
        for _ in range(200):                      # 2 s fade, then forget
            synth.render_block()
            if not synth.wiping:
                break
        assert synth.gen > gen and synth.visitor is None
        _settle(synth, 20)
        assert all(not isinstance(k, tuple) or k[0] == synth.seed for k in synth.bank_keys.values())
    finally:
        synth.close()


@pytest.mark.parametrize("days", [0, 5, 30])
def test_sample_counter_after_days(days):
    """The sample counter and step clock run for days: no drift, no NaN, the
    ring-buffer slices stay whole."""
    synth = S.TechnoSynth(seed=2, helper=False)
    jump = int(days * 86400 * S.SR) // synth.B * synth.B
    synth.pos += jump
    synth.next_step_at += jump
    synth.set_state(dict(HOOK))
    rms = []
    for _ in range(600):
        out = synth.render_block()
        assert out.shape == (synth.B, 2)
        rms.append(float(np.sqrt(np.mean(out.astype(np.float64) ** 2))))
    assert np.isfinite(rms).all() and max(rms) > 100
    # steps still land on the 16th grid: the scheduler kept up
    assert synth.next_step_at - synth.pos < 2 * synth.sps()
