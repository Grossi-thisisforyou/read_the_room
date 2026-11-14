"""Long-run regressions for the visuals (a 5-day unattended show on a Pi 5).

Ported from the v1 soak findings (pi/tools/soak.py) to the v2 engine:
time phases after days of uptime, underpainting flicker, bank reloads that
froze the frame loop, the painted body at the wipe, hook flapping, and the
visitor's file card running off its edge.

    SDL_VIDEODRIVER=dummy python3 -m unittest infinite_jest.visuals.tests.test_hostile_soak -v
"""
import math
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from infinite_jest import visuals  # noqa: E402
from infinite_jest.visuals import bankimg, engine  # noqa: E402
from infinite_jest.visuals.figure import Figure, flesh_luts, ghost_body  # noqa: E402

PAL = [(10, 10, 10), (60, 13, 13), (140, 28, 28), (217, 130, 107), (239, 230, 220)]
OCEAN = {"O": 0.5, "C": 0.5, "E": 0.9, "A": 0.5, "N": 0.5}
HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")


def setUpModule():
    pygame.display.init()
    pygame.display.set_mode((320, 180))


def _bank(root, n_per_hook, size=(32, 32), cut_every=0):
    """bank/<hook>/derived/<name>.poster.png (+ .cutout.png), names sorting by time."""
    for hi, hook in enumerate(HOOKS):
        d = os.path.join(root, hook, "derived")
        os.makedirs(d, exist_ok=True)
        for i in range(n_per_hook):
            base = os.path.join(d, "2026112%d-%04d_1" % (i % 9, i))
            if not os.path.exists(base + ".poster.png"):
                s = pygame.Surface(size)
                s.fill((i * 7 % 255, 40 * hi, 200))
                pygame.draw.line(s, (255, 255, 255), (0, i % size[1]), (size[0], 0))
                pygame.image.save(s, base + ".poster.png")
                if cut_every and i % cut_every == 0:
                    c = pygame.Surface((size[0] // 2, size[1]), pygame.SRCALPHA)
                    pygame.draw.ellipse(c, (200, 120, 90, 255), c.get_rect().inflate(-4, -4))
                    pygame.image.save(c, base + ".cutout.png")
    return root


def _state(phase, phase_t=0.0, vid="v-0001", hook="flesh", **kw):
    st = {"visitor_id": vid, "phase": phase, "phase_t": phase_t, "hook": hook, "scene": hook,
          "intensity": 0.6, "ocean": dict(OCEAN)}
    st.update(kw)
    return st


def _n_bank(v):
    return sum(len(x) for x in v.bank.under.values())


class TimePrecision(unittest.TestCase):
    def _motion(self, fig, t, n=8):
        lut = flesh_luts(PAL, 0.5, 0.2)
        fig.push_age = 10.0          # the camera glide is finished: only the smear moves
        frames = [fig.render(t + k / 30, 1 / 30, 10, 0.3, 0.2, lut, 1.0, trail=0.0)[0].astype(np.float32)
                  for k in range(n)]
        return [float(np.abs(b - a).mean()) for a, b in zip(frames, frames[1:])]

    def test_smear_keeps_moving_smoothly_after_days_of_uptime(self):
        fig = Figure(160, 180)
        for i in range(6):
            fig.push(ghost_body(160, 120, i * 0.3))
        base = self._motion(fig, 10.0)
        self.assertGreater(min(base), 0.0)
        for days in (5, 14):
            late = self._motion(fig, days * 86400.0 + 10.0)   # same fractional phase as base
            # same speed, no frozen frames, no doubled jumps
            self.assertGreater(min(late), 0.6 * min(base), (days, late, base))
            self.assertLess(max(late), 1.6 * max(base), (days, late, base))

    def test_whole_picture_still_moves_every_frame_after_two_weeks(self):
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent"})
        screen = pygame.Surface((320, 180))
        for t0 in (0.0, 14 * 86400.0):
            v.t = t0
            v.on_state(_state("hook", 40.0))
            for i in range(40):
                if i % 3 == 0:
                    v.on_frame(ghost_body(160, 120, v.t, present=1.0))
                v.render(screen, 1 / 30)
            still = 0
            prev = pygame.surfarray.array3d(v.fig_surf).astype(np.int16)
            for i in range(10):
                v.render(screen, 1 / 30)
                cur = pygame.surfarray.array3d(v.fig_surf).astype(np.int16)
                still += int(np.abs(cur - prev).mean() < 0.05)
                prev = cur
            self.assertEqual(still, 0, "frozen figure frames at t0=%r" % t0)


class Underpainting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_underpainting_does_not_flicker_while_the_room_lights_up(self):
        """One library underpainting per scene: the ground is never rebuilt with
        a new random image on consecutive frames (v1 flickered through the
        library at every phase change), even while the profiler's hook guess
        flaps every few frames."""
        v = visuals.create((320, 180), {"bank_dir": _bank(self.tmp, 8), "busy_file": "",
                                        "internal_size": (160, 90)})
        screen = pygame.Surface((320, 180))
        v.on_state(_state("idle", vid="", hook=None))
        for _ in range(30):
            v.render(screen, 1 / 30)
        picked, installs = [], []
        real_pick, real_install = v.bank.pick, v._install

        def pick(kind, hook, pal, rng):
            s = real_pick(kind, hook, pal, rng)
            if kind == "under":
                picked.append(id(s))
            return s
        v.bank.pick = pick
        v._install = lambda key, *a, **k: installs.append((key, v.t)) or real_install(key, *a, **k)
        for i in range(30):                         # profiling: one scene
            v.on_state(_state("profiling", i / 30))
            v.render(screen, 1 / 30)
        for i in range(300):                        # 10 s of hook, guess flapping every 0.3 s
            v.on_state(_state("hook", i / 30, hook=HOOKS[(i // 9) % 2]))
            v.render(screen, 1 / 30)
        self.assertLessEqual(len(set(picked)), 1, picked)       # one underpainting for this visitor's hook scene
        self.assertLessEqual(len(installs), 2, installs)         # profiling scene + one hook scene
        for (k1, t1), (k2, t2) in zip(installs, installs[1:]):
            self.assertGreater(t2 - t1, 0.5, installs)           # never on consecutive frames


class BankReload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bank_reload_on_wipe_reads_only_new_files_off_the_frame_thread(self):
        path = _bank(self.tmp, 10)
        v = visuals.create((320, 180), {"bank_dir": path, "busy_file": "", "internal_size": (160, 90)})
        self.assertEqual(_n_bank(v), 50)
        _bank(self.tmp, 25)                          # the overnight generator added 75 images
        loads = []
        real = pygame.image.load
        with mock.patch.object(pygame.image, "load",
                               lambda *a: loads.append((a[0], threading.current_thread())) or real(*a)):
            v.bank_loaded -= 601
            t0 = time.perf_counter()
            v.on_wipe()
            wipe_s = time.perf_counter() - t0
            frame_thread = [x for x in loads if x[1] is threading.current_thread()]
            self.assertEqual(frame_thread, [])           # nothing read on the frame thread
            self.assertLess(wipe_s, 0.05)
            bank = v.bank_loader.wait(30)
        self.assertIsNotNone(bank)
        self.assertEqual(len(loads), 75, len(loads))     # only the new files; the 50 are reused
        self.assertEqual(sum(len(x) for x in bank.under.values()), 5 * 25)
        self.assertEqual(_n_bank(v), 50)                 # not swapped in behind the frame's back ...
        v.bank_loader._result = bank
        v.render(pygame.Surface((320, 180)), 1 / 30)
        self.assertEqual(_n_bank(v), 125)                # ... but at the next frame

    def test_frames_stay_short_while_visitors_cycle_with_a_200_image_bank(self):
        """Visitors come and go (every wipe reloads, the generator keeps adding
        images); no frame may stall on the library. v1 froze ~2 s here on x86."""
        path = _bank(self.tmp, 40, size=(256, 144), cut_every=2)   # 200 underpaintings + 100 cutouts
        v = visuals.create((640, 360), {"bank_dir": path, "busy_file": "", "internal_size": (160, 90),
                                        "bank_reload_s": 0, "min_scene_s": 3, "hook_hold_s": 1})
        screen = pygame.Surface((640, 360))
        worst, worst_wipe = 0.0, 0.0
        segs = [("approach", 1), ("profiling", 2), ("hook", 6), ("release", 2), ("wipe", 2), ("idle", 1)]
        L = sum(d for _, d in segs)
        for i in range(int(3 * L * 30)):
            t = i / 30
            k, tv = divmod(t, L)
            acc = 0
            for ph, d in segs:
                if tv < acc + d:
                    break
                acc += d
            if ph == "hook" and abs(tv - acc - 1) < 1 / 60:
                _bank(self.tmp, 40 + 3 * int(k) + 3, size=(256, 144))     # new overnight images
            st = _state(ph, tv - acc, "v-%d" % k, HOOKS[(int(k) + int((tv - acc) // 2)) % 5])
            a = time.perf_counter()
            v.on_state(st)
            if ph == "wipe" and tv - acc < 1 / 30:
                worst_wipe = max(worst_wipe, time.perf_counter() - a)
            if i % 3 == 0:
                v.on_frame(ghost_body(160, 120, t, present=1.0))
            v.render(screen, 1 / 30)
            if i > 30:
                worst = max(worst, time.perf_counter() - a)
        self.assertLess(worst_wipe, 0.05)
        self.assertLess(worst, 0.25, "a frame took %.0f ms" % (worst * 1000))   # generous: CI machines vary
        v.bank_loader.wait(30)


class WipeDropsTheVisitor(unittest.TestCase):
    def test_visuals_drop_the_painted_body_at_the_wipe(self):
        """The stroke canvas and the figure surface are painted from the
        visitor's camera figure; they must not wait to fade out (a next visitor
        arriving right after the wipe would see them)."""
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent"})
        screen = pygame.Surface((320, 180))
        for i in range(300):
            v.on_state(_state("hook", 10 + i / 30, intensity=1.0))
            if i % 3 == 0:
                v.on_frame(ghost_body(160, 120, i / 30, present=1.0))
            v.render(screen, 1 / 30)
        self.assertGreater(pygame.mask.from_surface(v.fig_surf, 1).count(), 0, "test setup: no figure")
        self.assertGreater(pygame.mask.from_surface(v.paint, 1).count(), 0, "test setup: no strokes")
        v.on_state(_state("wipe", 0.0))
        v.render(screen, 1 / 30)
        self.assertEqual(pygame.mask.from_surface(v.paint, 1).count(), 0, "paint layer still holds strokes")
        self.assertEqual(pygame.mask.from_surface(v.under, 1).count(), 0, "under layer still holds strokes")
        self.assertEqual(pygame.mask.from_surface(v.fig_surf, 1).count(), 0, "last figure still held")
        self.assertEqual(v.echoes, [])
        self.assertEqual(v.ghosts, [])
        self.assertIsNone(v.snap)
        for _ in range(30):                          # and nothing paints it back during the wipe
            v.render(screen, 1 / 30)
        self.assertEqual(pygame.mask.from_surface(v.paint, 1).count(), 0)
        self.assertEqual(pygame.mask.from_surface(v.fig_surf, 1).count(), 0)


class HookHysteresis(unittest.TestCase):
    def _run(self, v, seconds, hook_at, t0=0.0, shake_at=None):
        screen = pygame.Surface((320, 180))
        hooks = []
        for i in range(int(seconds * 30)):
            pt = t0 + i / 30
            steer = {"x": 0, "y": 0, "flip": False, "shake": 0.9 if shake_at and abs(pt - shake_at) < 0.05 else 0.0}
            v.on_state(_state("hook", pt, hook=hook_at(pt), steer=steer))
            v.render(screen, 1 / 30)
            hooks.append((pt, v.scene_key[0] if v.scene_key else None))
        return hooks

    def _changes(self, hooks):
        return [(t, b) for (_, a), (t, b) in zip(hooks, hooks[1:]) if a != b]

    def test_a_flapping_profiler_does_not_cut_the_picture_every_8_s(self):
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent"})
        flap = lambda pt: ("flesh", "mirror", "void")[int(pt // 8) % 3]
        hooks = self._run(v, 64, flap)
        ch = self._changes(hooks)
        # 8 requests in 64 s; with a 20 s minimum per scene at most 3 cuts
        self.assertLessEqual(len(ch), 3, ch)
        times = [0.0] + [t for t, _ in ch]
        for a, b in zip(times[1:], times[2:]):
            self.assertGreaterEqual(b - a, 19.5, ch)

    def test_a_short_lived_guess_never_takes_over_and_a_shake_forces_the_cut(self):
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent"})
        blip = lambda pt: "void" if 25 <= pt < 29 else "flesh"   # 4 s < hook_hold_s
        hooks = self._run(v, 40, blip)
        self.assertNotIn("void", {h for _, h in hooks[60:]})
        # now the guess changes and the visitor shakes the phone at once: no waiting
        hooks = self._run(v, 4, lambda pt: "scrawl", t0=40.0, shake_at=40.5)
        first = next(t for t, h in hooks if h == "scrawl")
        self.assertLess(first - 40.0, 1.5, hooks[:50])

    def test_hook_to_hook_is_a_slow_crossfade(self):
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent",
                                        "min_scene_s": 0, "hook_hold_s": 0})
        self._run(v, 10, lambda pt: "flesh", t0=5.0)
        self._run(v, 0.5, lambda pt: "inverted", t0=15.0)
        self.assertIsNotNone(v.trans)
        self.assertEqual(v.trans[0], "fade")
        self.assertAlmostEqual(v.trans[2], 2.5)

    def test_phase_change_takes_the_new_hook_at_once(self):
        v = visuals.create((320, 180), {"busy_file": "", "internal_size": (160, 90), "bank_dir": "/nonexistent"})
        self._run(v, 8, lambda pt: "flesh", t0=10.0)
        screen = pygame.Surface((320, 180))
        v.on_state(_state("release", 0.0, hook="void"))
        v.render(screen, 1 / 30)
        self.assertEqual(v.hook, "void")


class RevealCard(unittest.TestCase):
    LONG = ["CONSCIENTIOUSNESS 0.42   CONFIDENCE 0.81 OVER 3 SAMPLES AND RISING",
            "WE TRIED 1 SCENES ON YOU. THE WOUND HELD YOUR GAZE LONGEST, 41 SECONDS",
            "X" * 90,
            "OPENNESS 0.88 EXTRAVERSION 0.12 AGREEABLENESS 0.30 NEUROTICISM 0.95 RETAINED",
            "YOU LOOKED AWAY 3 TIMES AND CAME BACK EVERY TIME; WE NOTED EACH RETURN"] * 3

    def _card(self, phase, lines, main_cx=None, **rv):
        v = visuals.create((1920, 1080), {"busy_file": "", "internal_size": (320, 180), "bank_dir": "/nonexistent"})
        v.on_state(_state(phase, 20.0, reveal=dict({"header": "FILE 0427 " + "H" * 50, "label": "L" * 80,
                                                    "lines": lines, "total": 999}, **rv)))
        v.phase = phase
        v.t = 100.0
        if main_cx is not None:
            v.main = type("M", (), {"cx": main_cx})()
        surf = pygame.Surface((1920, 1080), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        v._draw_reveal(surf, 1.0)
        v.t += 30.0                                  # the newest line has typed itself out
        surf.fill((0, 0, 0, 0))
        v._draw_reveal(surf, 1.0)
        return v, surf

    def _check(self, v, surf):
        r = v.reveal_rect
        safe = pygame.Rect(96, 54, 1920 - 192, 1080 - 108)
        self.assertTrue(safe.contains(r), (r, safe))
        card = pygame.Rect(0, 0, r.w, r.h)
        inner = card.inflate(-20, -20)
        for bb in v.reveal_boxes:
            if bb.w and bb.h:
                self.assertTrue(inner.contains(bb), (bb, card))
        # nothing at all lands on the screen outside the card
        a = pygame.surfarray.pixels_alpha(surf)
        outside = a.copy()
        del a
        outside[r.left:r.right, r.top:r.bottom] = 0
        self.assertEqual(int(outside.max()), 0)

    def test_long_reveal_lines_wrap_inside_the_card(self):
        for cx in (None, 10, 300):          # the card shifts away from the figure: still inside
            v, surf = self._card("release", self.LONG, cx)
            self._check(v, surf)
            rows = v.reveal_cache["layout"][2]
            self.assertGreater(len(rows), 13)            # wrapped, not cut off
            self.assertTrue(any("CONFIDENCE" in r for _, r in rows) or any("0.81" in r for _, r in rows))

    def test_long_lines_struck_out_in_the_wipe_with_deletion_notes(self):
        v, surf = self._card("wipe", self.LONG, 10, struck=5,
                             wipe=["DELETED: EVERY FRAME OF YOUR FACE AND EVERY SECOND YOU STOOD HERE " * 2] * 4)
        self._check(v, surf)

    def test_short_file_keeps_its_size(self):
        v, surf = self._card("release", ["O 0.42", "C 0.10"])
        self._check(v, surf)
        self.assertAlmostEqual(v.reveal_cache["layout"][0], 34.0)


class BenchAdvice(unittest.TestCase):
    def test_bench_suggests_smooth_scale_off_before_a_smaller_picture(self):
        from infinite_jest.visuals import bench
        fast = {"flesh": (12.0, 15.0)}
        slow = {"flesh": (38.0, 45.0)}           # a Pi 5 at 1080p: 22-30 fps
        mid = {"flesh": (30.0, 34.0)}
        adv = bench.recommend({(640, 360): fast}, {(640, 360): fast})
        self.assertEqual(adv["internal_size"], [640, 360])
        self.assertNotIn("smooth_scale", adv)
        # slow with smoothing, fine without: turn smoothing off first
        adv = bench.recommend({(640, 360): slow, (480, 270): mid}, {(640, 360): mid})
        self.assertEqual(adv, {"internal_size": [640, 360], "smooth_scale": False})
        # still slow without smoothing: then the smaller internal size
        adv = bench.recommend({(640, 360): slow, (480, 270): slow}, {(640, 360): slow, (480, 270): fast})
        self.assertEqual(adv, {"internal_size": [480, 270], "smooth_scale": False})


if __name__ == "__main__":
    unittest.main()
