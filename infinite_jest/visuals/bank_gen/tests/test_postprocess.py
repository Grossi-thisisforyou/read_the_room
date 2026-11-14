#!/usr/bin/env python3
"""Tests for pngio.py and postprocess.py with fake images.

    python3 tests/test_postprocess.py -v

Runs every image test twice: with the pure-Python engine, and with Pillow
when it is installed (skipped otherwise).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import bankfiles  # noqa: E402
import fakeimg  # noqa: E402
import pngio  # noqa: E402
import postprocess  # noqa: E402

PP = os.path.join(ROOT, "postprocess.py")


class PNGTests(unittest.TestCase):
    def test_roundtrip_rgb_rgba(self):
        for ch in (3, 4):
            img = pngio.Raw(5, 4, ch, bytes(range(5 * 4 * ch)))
            back = pngio.decode(pngio.encode(img))
            self.assertEqual((back.w, back.h, back.channels), (5, 4, ch))
            self.assertEqual(back.data, img.data)

    def test_all_filter_types(self):
        for ch in (3, 4):
            img = fakeimg.noise_image(13, 11)
            if ch == 4:
                d = bytearray()
                for i in range(13 * 11):
                    d += img.data[i * 3:i * 3 + 3] + bytes([i % 256])
                img = pngio.Raw(13, 11, 4, d)
            blob = fakeimg.filtered_png(img, [0, 1, 2, 3, 4])
            self.assertEqual(pngio.decode(blob).data, img.data)

    @unittest.skipUnless(fakeimg.HAVE_PIL, "Pillow not installed")
    def test_reads_pillow_pngs(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        try:
            src = fakeimg.figure_on_ground(40, 30, noise=30)
            im = Image.frombytes("RGB", (40, 30), bytes(src.data))
            for mode in ("RGB", "RGBA", "L", "LA", "P"):
                p = os.path.join(tmp, mode + ".png")
                im.convert(mode).save(p, optimize=True)
                got = pngio.read(p)
                ref = Image.open(p).convert("RGBA" if got.channels == 4 else "RGB")
                self.assertEqual(bytes(got.data), ref.tobytes(), mode)
        finally:
            shutil.rmtree(tmp)

    def test_rejects_garbage(self):
        with self.assertRaises(pngio.PNGError):
            pngio.decode(b"not a png at all")
        with self.assertRaises(pngio.PNGError):
            pngio.decode(pngio.SIGNATURE + b"\x00\x00")

    def test_size(self):
        tmp = tempfile.mkdtemp()
        try:
            p = fakeimg.save(os.path.join(tmp, "x.png"), fakeimg.noise_image(17, 9))
            self.assertEqual(pngio.size(p), (17, 9))
        finally:
            shutil.rmtree(tmp)


class MathTests(unittest.TestCase):
    def test_crop_box(self):
        self.assertEqual(postprocess.crop_box(512, 512), (0, 112, 512, 288))
        self.assertEqual(postprocess.crop_box(512, 512, bias=0.3), (0, 67, 512, 288))
        self.assertEqual(postprocess.crop_box(1920, 1080), (0, 0, 1920, 1080))
        x, y, w, h = postprocess.crop_box(2000, 500)
        self.assertEqual((y, h), (0, 500))
        self.assertAlmostEqual(w / h, 16 / 9, places=2)

    def test_ground(self):
        g, flat = postprocess.ground_from_border([(10, 10, 10)] * 9 + [(200, 0, 0)])
        self.assertEqual(g, (10, 10, 10))
        self.assertAlmostEqual(flat, 0.9)

    def test_poster_lut_uses_palette(self):
        cols = [(0, 0, 0), (50, 0, 0), (100, 0, 0), (150, 0, 0), (200, 0, 0)]
        lr, lg, lb = postprocess.poster_lut(cols)
        self.assertEqual(set(lr), {0, 50, 100, 150, 200})
        self.assertEqual(lr[0], 0)
        self.assertEqual(lr[255], 200)
        # stretched: 100..150 now spans all five colours
        lr, _, _ = postprocess.poster_lut(cols, 100, 150)
        self.assertEqual((lr[100], lr[150], lr[0], lr[255]), (0, 200, 0, 200))
        self.assertEqual(set(lr[100:151]), {0, 50, 100, 150, 200})

    def test_stretch_range(self):
        hist = [0] * 256
        hist[10], hist[100], hist[200] = 1, 500, 500
        self.assertEqual(postprocess.stretch_range(hist), (100, 200))
        self.assertEqual(postprocess.stretch_range([0] * 256), (0, 255))


class EngineMixin:
    engine_name = None

    def setUp(self):
        if self.engine_name == "pillow" and not fakeimg.HAVE_PIL:
            self.skipTest("Pillow not installed")
        self.engine = postprocess.pick_engine(self.engine_name)
        self.bank = tempfile.mkdtemp(prefix="bankpp-test-")

    def tearDown(self):
        shutil.rmtree(self.bank, ignore_errors=True)

    def add(self, hook, name, img, **side):
        p = fakeimg.save(os.path.join(self.bank, hook, name + ".png"), img)
        if side is not None:
            fakeimg.sidecar(p, **side)
        return p

    def load(self, path):
        img = pngio.read(path)
        return img

    def run_pp(self, **kw):
        opts = postprocess.Options(**kw)
        lines = []
        c = postprocess.run(self.bank, engine=self.engine, opts=opts, out=lines.append)
        return c, lines

    # -- the four variants
    def test_variants(self):
        src = self.add("flesh", "a_1", fakeimg.figure_on_ground(96, 96),
                       tags={"hook": "flesh", "palette": "papal", "composition": {"framing": "full-body"}},
                       tag_list=["hook:flesh", "palette:papal"])
        c, lines = self.run_pp(size=(64, 36))
        self.assertEqual(c["failed"], 0, lines)
        d = os.path.join(self.bank, "flesh", "derived")
        for v in ("wide", "mono", "poster", "cutout"):
            p = os.path.join(d, "a_1.%s.png" % v)
            self.assertTrue(os.path.exists(p), (v, os.listdir(d)))
            with open(os.path.join(d, "a_1.%s.json" % v)) as f:
                side = json.load(f)
            self.assertEqual(side["variant"], v)
            self.assertEqual(side["derived_from"], "a_1.png")
            self.assertIn("variant:" + v, side["tag_list"])
            self.assertIn("palette:papal", side["tag_list"])
            self.assertEqual(side["tags"]["variant"], v)
            self.assertEqual(side["prompt"], "a test prompt")
        wide = self.load(os.path.join(d, "a_1.wide.png"))
        self.assertEqual((wide.w, wide.h, wide.channels), (64, 36, 3))
        mono = self.load(os.path.join(d, "a_1.mono.png"))
        self.assertEqual((mono.w, mono.h, mono.channels), (64, 36, 3))  # RGB so pygame can smoothscale it
        self.assertTrue(all(mono.data[i] == mono.data[i + 1] == mono.data[i + 2]
                            for i in range(0, len(mono.data), 3)))
        poster = self.load(os.path.join(d, "a_1.poster.png"))
        papal = set(postprocess.NAMED_PALETTES["papal"])
        cols = {poster.pixel(x, y) for x in range(poster.w) for y in range(poster.h)}
        self.assertTrue(cols <= papal, cols - papal)
        self.assertGreaterEqual(len(cols), 2)  # figure and ground in different colours
        cut = self.load(os.path.join(d, "a_1.cutout.png"))
        self.assertEqual(cut.channels, 4)
        self.assertEqual(cut.pixel(0, 0)[3], 0)                       # ground is transparent
        self.assertEqual(cut.pixel(cut.w // 2, cut.h // 2)[3], 255)   # figure is solid
        self.assertLess(cut.w, 96)                                     # cropped to the figure
        self.assertTrue(src)

    def test_cutout_skipped_on_busy_ground(self):
        self.add("void", "n_1", fakeimg.noise_image(48, 48))
        c, lines = self.run_pp(variants=("cutout",))
        self.assertEqual(c["skipped"], 1, lines)
        self.assertFalse(os.path.exists(os.path.join(self.bank, "void", "derived", "n_1.cutout.png")))
        meta = bankfiles.read_sidecar(os.path.join(self.bank, "void", "n_1.png"))
        self.assertIn("not flat", meta["cutout_skipped"])
        # not retried on the next run
        c, lines = self.run_pp(variants=("cutout",))
        self.assertEqual(c["skipped"], 0, lines)

    def test_idempotent_and_force(self):
        self.add("mirror", "m_1", fakeimg.figure_on_ground(32, 32))
        c1, _ = self.run_pp(size=(32, 18))
        c2, _ = self.run_pp(size=(32, 18))
        self.assertGreater(c1["made"], 0)
        self.assertEqual(c2["made"], 0)
        c3, _ = self.run_pp(size=(32, 18), force=True)
        self.assertEqual(c3["made"], c1["made"])

    def test_fail_soft(self):
        os.makedirs(os.path.join(self.bank, "scrawl"))
        with open(os.path.join(self.bank, "scrawl", "broken.png"), "wb") as f:
            f.write(pngio.SIGNATURE + b"rubbish")
        self.add("scrawl", "ok_1", fakeimg.figure_on_ground(32, 32))
        c, lines = self.run_pp(size=(32, 18))
        self.assertEqual(c["failed"], 1)
        self.assertTrue(any("FAILED scrawl/broken.png" in ln for ln in lines), lines)
        self.assertTrue(os.path.exists(os.path.join(self.bank, "scrawl", "derived", "ok_1.wide.png")))

    def test_derived_are_not_sources(self):
        self.add("flesh", "a_1", fakeimg.figure_on_ground(32, 32))
        self.run_pp(size=(32, 18))
        srcs = bankfiles.sources(os.path.join(self.bank, "flesh"))
        self.assertEqual([os.path.basename(s) for s in srcs], ["a_1.png"])

    def test_prune(self):
        p = self.add("flesh", "a_1", fakeimg.figure_on_ground(32, 32))
        self.run_pp(size=(32, 18))
        os.remove(p)
        os.remove(bankfiles.sidecar_path(p))
        gone = postprocess.prune(self.bank, ["flesh"])
        self.assertEqual(len(gone), 8)  # 4 images + 4 sidecars
        self.assertEqual(os.listdir(os.path.join(self.bank, "flesh", "derived")), [])

    def test_wide_to_hook(self):
        self.add("inverted", "i_1", fakeimg.figure_on_ground(32, 32), tags={"hook": "inverted"})
        self.run_pp(size=(32, 18), wide_to_hook=True)
        hook_dir = os.path.join(self.bank, "inverted")
        top = sorted(n for n in os.listdir(hook_dir) if n.endswith(".png"))
        self.assertEqual(top, ["i_1.wide.png"])  # the renderer only sees the 16:9 copy
        moved = os.path.join(hook_dir, "derived", "i_1.png")
        self.assertTrue(os.path.exists(moved))
        self.assertTrue(bankfiles.read_sidecar(moved)["moved_for_wide"])
        with open(os.path.join(hook_dir, "i_1.wide.json")) as f:
            self.assertEqual(json.load(f)["derived_from"], "derived/i_1.png")
        # running again doesn't redo anything or treat the wide copy as a source
        c, lines = self.run_pp(size=(32, 18), wide_to_hook=True)
        self.assertEqual(c["made"], 0, lines)
        # generate.py's cap deletes the wide copy -> prune retires the original
        os.remove(os.path.join(hook_dir, "i_1.wide.png"))
        os.remove(os.path.join(hook_dir, "i_1.wide.json"))
        postprocess.prune(self.bank, ["inverted"])
        self.assertEqual(os.listdir(os.path.join(hook_dir, "derived")), [])


class PureEngineTests(EngineMixin, unittest.TestCase):
    engine_name = "pure"

    def test_jpeg_skipped_without_pillow(self):
        os.makedirs(os.path.join(self.bank, "flesh"))
        with open(os.path.join(self.bank, "flesh", "photo.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0fake")
        c, lines = self.run_pp()
        self.assertEqual(c["failed"], 1)
        self.assertTrue(any("needs Pillow" in ln for ln in lines), lines)


class PillowEngineTests(EngineMixin, unittest.TestCase):
    engine_name = "pillow"

    def test_jpeg_source(self):
        from PIL import Image
        img = fakeimg.figure_on_ground(64, 64, noise=0)
        os.makedirs(os.path.join(self.bank, "flesh"))
        Image.frombytes("RGB", (64, 64), bytes(img.data)).save(
            os.path.join(self.bank, "flesh", "photo.jpg"), quality=95)
        c, lines = self.run_pp(size=(64, 36))
        self.assertEqual(c["failed"], 0, lines)
        self.assertTrue(os.path.exists(os.path.join(self.bank, "flesh", "derived", "photo.wide.png")))


class CLITests(unittest.TestCase):
    def test_cli_pure_and_dry_run(self):
        bank = tempfile.mkdtemp(prefix="bankpp-cli-")
        try:
            fakeimg.save(os.path.join(bank, "void", "v_1.png"), fakeimg.figure_on_ground(40, 40, ground=(5, 5, 8),
                                                                                         figure=(90, 90, 100)))
            out = subprocess.run([sys.executable, PP, "--bank", bank, "--engine", "pure", "--dry-run",
                                  "--size", "32x18"], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("would make", out.stdout)
            self.assertFalse(os.path.exists(os.path.join(bank, "void", "derived", "v_1.wide.png")))
            t0 = time.time()
            out = subprocess.run([sys.executable, PP, "--bank", bank, "--engine", "pure", "--size", "32x18"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("built-in PNG code", out.stdout)
            self.assertTrue(os.path.exists(os.path.join(bank, "void", "derived", "v_1.cutout.png")), out.stdout)
            self.assertLess(time.time() - t0, 30)
            out = subprocess.run([sys.executable, PP, "--bank", os.path.join(bank, "nope")],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 2)
        finally:
            shutil.rmtree(bank)

    def test_full_size_pure_speed(self):
        """A real-sized 512x512 image through every variant without Pillow."""
        bank = tempfile.mkdtemp(prefix="bankpp-speed-")
        try:
            fakeimg.save(os.path.join(bank, "flesh", "big.png"), fakeimg.figure_on_ground(512, 512))
            t0 = time.time()
            c = postprocess.run(bank, engine=postprocess.PureEngine(), opts=postprocess.Options(quiet=True),
                                out=lambda *_: None)
            took = time.time() - t0
            self.assertEqual(c["made"], 4)
            wide = pngio.read(os.path.join(bank, "flesh", "derived", "big.wide.png"))
            self.assertEqual((wide.w, wide.h), (1280, 720))
            self.assertLess(took, 60, "pure-Python postprocess took %.0f s" % took)
        finally:
            shutil.rmtree(bank)


if __name__ == "__main__":
    unittest.main()
