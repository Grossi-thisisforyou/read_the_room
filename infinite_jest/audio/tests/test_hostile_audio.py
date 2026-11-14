"""Long-run / Pi-budget regressions for the synth (a 5-day unattended show on a
Pi 5, where the audio child gets about one core and the output buffer is
~80-150 ms). Ported from the v1 soak findings to the v2 synth.

    python3 -m unittest infinite_jest.audio.tests.test_hostile_audio -v
"""
import multiprocessing as mp
import time
import unittest
from unittest import mock

import numpy as np

from infinite_jest.audio import engine as E
from infinite_jest.audio import synth as S
from infinite_jest.audio import voices as V

HOOK = {"visitor_id": "v-1234", "phase": "hook", "hook": "flesh", "intensity": 0.8, "tempo": 134,
        "ocean": {"O": 0.9, "C": 0.2, "E": 0.8, "A": 0.1, "N": 0.9}}
SLOW = ("kick", "hat", "ride", "clap", "snare", "clank", "metal", "swell", "stab", "tom", "tick",
        "impact", "crash", "vox", "breath", "riser", "rumble")


def _settle(synth, blocks):
    """Render blocks, giving the helper the time real playback would."""
    for _ in range(blocks):
        out = synth.render_block()
        assert np.isfinite(out).all()
        deadline = time.monotonic() + 5
        while not synth.helper.idle() and time.monotonic() < deadline:
            time.sleep(0.003)


def _helper_kind(q):
    synth = S.TechnoSynth(seed=1, threaded=True)
    try:
        q.put(type(synth.helper).__name__)
    finally:
        synth.close()


class Helper(unittest.TestCase):
    def test_render_block_never_builds_samples_itself(self):
        """A rebuilt bank section or an 8 s riser costs 50-200 ms on x86 (x2.4-3.5
        on a Pi 5): made inside render_block it empties the output buffer. Live,
        they must come from the helper process, never inline (a thread in the
        same process is not good enough either: it competes for the GIL)."""
        synth = S.TechnoSynth(seed=1, threaded=True)
        try:
            self.assertIsInstance(synth.helper, S._Helper)
            synth.set_state(dict(HOOK))
            _settle(synth, 200)                       # first visitor sections arrive
            called = []

            def boom(name):
                def f(*a, **k):
                    called.append(name)
                    raise AssertionError(name + " made inside render_block")
                return f
            played = []
            stock = synth._stock_riser
            synth._stock_riser = lambda name, n: played.append(name) or stock(name, n)
            with mock.patch.multiple(V, **{n: boom(n) for n in SLOW}):
                st = dict(HOOK, ocean={"O": 0.1, "C": 0.9, "E": 0.9, "A": 0.15, "N": 0.95}, intensity=1.0)
                synth.set_state(st)                   # the sections' keys change as the traits glide
                _settle(synth, 1500)                  # ~32 s: several 8-bar phrases, a riser among them
                st = dict(st, steer={"x": 0.0, "y": 0.0, "shake": 0.95})
                synth.set_state(st)                   # phone shake: stutter + noise riser
                _settle(synth, 80)
                synth.set_state(dict(st, visitor_id="v-9999"))   # a new identity: all sections rebuilt
                _settle(synth, 200)
            self.assertEqual(called, [])
            self.assertIn("riser", played)            # a phrase riser was played (from stock)
            self.assertIn("shake", played)
            want = synth._desired_keys()
            for g in "khcst":
                self.assertEqual(synth.bank_keys[g], want[g], g)   # the new samples did arrive
        finally:
            synth.close()

    def test_helper_starts_inside_the_daemon_audio_child(self):
        """The audio engine runs the synth in a daemon process, and
        multiprocessing refuses to let daemons have children: the helper must
        still start there (v1 silently fell back to building inline)."""
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_helper_kind, args=(q,), daemon=True)
        p.start()
        try:
            self.assertEqual(q.get(timeout=60), "_Helper")
        finally:
            p.join(10)

    def test_helper_samples_match_inline_samples(self):
        """Same seed and parameters -> the same sounds, whichever process made them."""
        import concurrent.futures as cf
        synth = S.TechnoSynth(seed=7)
        ctx = dict(dna=synth.dna, mode=synth.mode, grit=synth.clock.grit)
        keys = synth._desired_keys()
        with cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
            for g in ("c", "s"):
                inline = S.build_section(g, keys[g], ctx)
                remote = ex.submit(S.build_section, g, keys[g], ctx).result()
                self.assertEqual(inline.keys(), remote.keys())
                for k in inline:
                    for a, b in zip(inline[k], remote[k]):
                        np.testing.assert_array_equal(a, b)
                # and the same as the offline (inline, one sound per block) path built
                for k in inline:
                    for a, b in zip(inline[k], synth.bank[k]):
                        np.testing.assert_array_equal(a, b)

    def test_without_helper_is_unchanged_and_deterministic(self):
        a = S.TechnoSynth(seed=3)
        b = S.TechnoSynth(seed=3)
        self.assertIsNone(a.helper)
        for s in (a, b):
            s.set_state(dict(HOOK))
        for _ in range(300):
            np.testing.assert_array_equal(a.render_block(), b.render_block())

    def test_wipe_drops_helper_results_for_the_old_visitor(self):
        synth = S.TechnoSynth(seed=1, threaded=True)
        try:
            synth.set_state(dict(HOOK))
            _settle(synth, 50)
            gen = synth.gen
            synth.set_state(dict(HOOK, ocean={"O": 0.0, "C": 1.0, "E": 0.0, "A": 1.0, "N": 0.0}))
            synth.render_block()
            synth.render_block()                     # new sections for the old visitor are on order
            synth.set_state({"visitor_id": "", "phase": "wipe"})   # as the engine sends it
            for _ in range(800):                     # ~10 s dissolve, then forget
                synth.render_block()
                if not synth.wiping:
                    break
            self.assertFalse(synth.wiping)
            self.assertGreater(synth.gen, gen)
            self.assertIsNone(synth.visitor)
            _settle(synth, 40)
            for g, key in synth.bank_keys.items():
                self.assertEqual(key[0], synth.seed, g)   # every section is the room's again
        finally:
            synth.close()

    def test_a_dead_helper_falls_back_to_a_thread(self):
        synth = S.TechnoSynth(seed=1, threaded=True)
        try:
            synth.set_state(dict(HOOK))
            _settle(synth, 20)
            synth.helper.broken = True
            synth.set_state(dict(HOOK, visitor_id="v-2"))
            for _ in range(200):
                synth.render_block()
            self.assertIsInstance(synth.helper, S._ThreadHelper)
            _settle(synth, 20)
            self.assertEqual(synth.bank_keys["c"], synth._desired_keys()["c"])
        finally:
            synth.close()


class Risers(unittest.TestCase):
    def test_fitted_riser_keeps_its_end_on_the_drop(self):
        sig = np.vstack([np.linspace(0, 1, 1000, dtype=np.float32)] * 2)
        out, lag = S._fit_riser(sig, 800)
        self.assertEqual((out.shape[-1], lag), (800, 0))
        self.assertEqual(out[0, -1], sig[0, -1])
        self.assertEqual(out[0, 0], 0.0)                 # faded in, no click
        out, lag = S._fit_riser(sig, 1200)
        self.assertEqual((out.shape[-1], lag), (1000, 200))

    def test_risers_come_from_stock_and_are_reordered(self):
        synth = S.TechnoSynth(seed=1, threaded=True)
        try:
            synth.set_state(dict(HOOK, steer={"x": 0, "y": 0, "shake": 0.0}))
            _settle(synth, 100)
            self.assertIn("shake", synth.risers)
            self.assertIn("riser", synth.risers)
            first = synth.risers["shake"][1]
            synth.set_state(dict(HOOK, steer={"x": 0, "y": 0, "shake": 0.95}))
            _settle(synth, 4)
            self.assertFalse(synth.risers["shake"][2] and synth.risers["shake"][1] is first)
            _settle(synth, 120)                       # a fresh one arrived for the next shake
            self.assertTrue(synth.risers["shake"][2])
            self.assertIsNot(synth.risers["shake"][1], first)
        finally:
            synth.close()


class Budget(unittest.TestCase):
    def test_worst_render_block_with_visitors_hinge_and_shakes(self):
        """60 s of a visit at playback pace x8: two visitors, hook changes,
        a hinge, shakes. The worst block must stay far inside the buffer
        (v1/v2 before the helper: 75-90 ms blocks on x86 at riser starts)."""
        synth = S.TechnoSynth(seed=0, threaded=True)
        try:
            B = synth.B
            n = int(60 * S.SR / B)
            t0 = time.perf_counter()
            worst = []
            hooks = ("flesh", "scrawl", "inverted", "mirror", "void")
            for b in range(n):
                t = b * B / S.SR
                if b % 4 == 0:
                    st = dict(HOOK, visitor_id="v-a" if t < 30 else "v-b", hook=hooks[int(t // 9) % 5],
                              hinge=17 < t % 30 < 21, phase_t=t % 30,
                              ocean={"O": 0.5 + 0.4 * np.sin(t / 7), "C": 0.3, "E": 0.6, "A": 0.5 + 0.4 * np.cos(t / 5),
                                     "N": 0.7},
                              steer={"x": float(np.sin(t)), "y": 0.0, "shake": 0.9 if t % 11 < 0.3 else 0.0})
                    synth.set_state(st)
                a = time.perf_counter()
                out = synth.render_block()
                worst.append(time.perf_counter() - a)
                self.assertTrue(np.isfinite(out).all())
                d = t0 + (b + 1) * B / S.SR / 8 - time.perf_counter()
                if d > 0:
                    time.sleep(d)
            worst = np.array(worst[50:]) * 1000
            self.assertLess(worst.max(), 50.0, "worst block %.1f ms, p99 %.1f ms" % (worst.max(), np.percentile(worst, 99)))
        finally:
            synth.close()


class LongUptime(unittest.TestCase):
    def test_sample_counter_after_days(self):
        """The sample counter and step clock run for days: no drift, no NaN, the
        ring-buffer slices stay whole."""
        for days in (0, 5, 30):
            with self.subTest(days=days):
                synth = S.TechnoSynth(seed=2)
                jump = int(days * 86400 * S.SR) // synth.IB * synth.IB
                synth.pos += jump
                synth.next_step_at += jump
                synth.bar_t0 += jump
                synth.set_state(dict(HOOK))
                rms = []
                for _ in range(600):
                    out = synth.render_block()
                    self.assertEqual(out.shape, (synth.B, 2))
                    rms.append(float(np.sqrt(np.mean(out.astype(np.float64) ** 2))))
                self.assertTrue(np.isfinite(rms).all())
                self.assertGreater(max(rms), 100)
                # steps still land on the 16th grid: the scheduler kept up
                self.assertLess(synth.next_step_at - synth.pos, 2 * synth.sps() + synth.IB)
                for ph in (synth.lfo, synth.lfo2, synth.sub_ph, float(synth.bass.ph)):
                    self.assertTrue(0.0 <= ph < 2 * np.pi + 1e-9)   # phases stay wrapped

    def test_same_sound_after_days_of_uptime(self):
        """Offsetting the clock by days must not change the music at all
        (positions are integers, phases are wrapped)."""
        a = S.TechnoSynth(seed=4)
        b = S.TechnoSynth(seed=4)
        jump = int(14 * 86400 * S.SR) // b.IB * b.IB
        b.pos += jump
        b.next_step_at += jump
        b.bar_t0 += jump
        for s in (a, b):
            s.set_state(dict(HOOK))
        for _ in range(400):
            np.testing.assert_allclose(a.render_block().astype(np.int32), b.render_block().astype(np.int32), atol=1)


class Config(unittest.TestCase):
    def test_volume_fallback_and_set_volume(self):
        self.assertEqual(E._volume({"volume": 0.3}), 0.3)
        self.assertEqual(E._volume({"audio_volume": 0.5, "volume": 0.3}), 0.5)
        self.assertEqual(E._volume({}), 0.9)
        eng = E.AudioEngine({"volume": 0.4})
        self.assertEqual(eng.cfg.get("volume"), 0.4)
        eng.set_volume(7)
        self.assertEqual(eng.cfg["audio_volume"], 1.0)
        eng.set_volume("junk")
        self.assertEqual(eng.cfg["audio_volume"], 1.0)


if __name__ == "__main__":
    unittest.main()
