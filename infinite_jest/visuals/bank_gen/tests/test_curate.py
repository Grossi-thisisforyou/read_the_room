#!/usr/bin/env python3
"""Tests for curate.py (contact sheet, delete/keep list, trash, restore) and
the keep flag in generate.py's per-hook cap.

    python3 tests/test_curate.py -v
"""
import json
import os
import re
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
import curate  # noqa: E402
import fakeimg  # noqa: E402
import generate  # noqa: E402
import postprocess  # noqa: E402

CURATE = os.path.join(ROOT, "curate.py")


class CurateTests(unittest.TestCase):
    def setUp(self):
        self.bank = tempfile.mkdtemp(prefix="bankcur-test-")
        self.paths = {}
        for hook in ("flesh", "void"):
            for i in range(3):
                p = fakeimg.save(os.path.join(self.bank, hook, "%s_%d.png" % (hook, i)),
                                 fakeimg.figure_on_ground(24, 24, seed=i))
                fakeimg.sidecar(p, prompt="prompt %s %d" % (hook, i),
                                tag_list=["hook:" + hook, "palette:ash", "motif:barcode"])
                self.paths["%s_%d" % (hook, i)] = p

    def tearDown(self):
        shutil.rmtree(self.bank, ignore_errors=True)

    def lines(self):
        out = []
        return out, out.append

    # -- sheet
    def test_sheet_lists_everything_and_escapes(self):
        fakeimg.sidecar(self.paths["flesh_0"], prompt='</script><script>alert(1)</script> & "q" __DATA__',
                        tag_list=["hook:flesh", "palette:<b>"])
        out, n = curate.build_sheet(self.bank)
        self.assertEqual(n, 6)
        self.assertEqual(out, os.path.join(self.bank, "contact_sheet.html"))
        with open(out, encoding="utf-8") as f:
            page = f.read()
        self.assertEqual(page.count('class="card"'), 6)
        self.assertEqual(page.count("<script>alert"), 0)        # escaped everywhere
        self.assertEqual(len(re.findall(r"</script>", page)), 2)  # only our two blocks end
        self.assertIn('src="flesh/flesh_0.png"', page)           # relative: works offline
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))
        data = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
        items = json.loads(data)["items"]
        self.assertEqual(len(items), 6)
        self.assertIn("__DATA__", next(i["prompt"] for i in items if i["path"] == "flesh/flesh_0.png"))

    def test_sheet_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        out, _ = curate.build_sheet(self.bank)
        with open(out, encoding="utf-8") as f:
            page = f.read()
        js = page[page.rindex("<script>") + 8:page.rindex("</script>")]
        tmp = os.path.join(self.bank, "sheet.js")
        with open(tmp, "w") as f:
            f.write(js)
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_sheet_elsewhere_keeps_bank_relative_list(self):
        other = tempfile.mkdtemp(prefix="bankcur-out-")
        try:
            out, _ = curate.build_sheet(self.bank, os.path.join(other, "sheet.html"))
            with open(out, encoding="utf-8") as f:
                page = f.read()
            rel = os.path.relpath(self.bank, other)
            self.assertIn('src="%s/flesh/flesh_0.png"' % rel, page)
            self.assertIn('lines.push("delete " + p)', page)
        finally:
            shutil.rmtree(other)

    def test_sheet_derived(self):
        postprocess.run(self.bank, engine=postprocess.PureEngine(),
                        opts=postprocess.Options(size=(32, 18), quiet=True), out=lambda *_: None)
        _, n_plain = curate.build_sheet(self.bank)
        _, n_all = curate.build_sheet(self.bank, derived=True)
        self.assertEqual(n_plain, 6)
        self.assertGreater(n_all, 6)

    # -- list parsing and safety
    def test_parse_list(self):
        entries = curate.parse_list("# comment\n\ndelete flesh/a.png\nkeep void/b.png\nunkeep void/c.png\nflesh/d.png\n")
        self.assertEqual(entries, [("delete", "flesh/a.png"), ("keep", "void/b.png"),
                                   ("unkeep", "void/c.png"), ("delete", "flesh/d.png")])

    def test_refuses_paths_outside_bank(self):
        for bad in ("../etc/passwd", "/etc/passwd", "flesh/../../x.png", "~/x.png", "flesh_0.json",
                    "flesh/flesh_0.json", "notahook/x.png"):
            with self.assertRaises(curate.CurateError, msg=bad):
                curate.resolve(self.bank, bad)
        d, k, u, problems = curate.plan(self.bank, [("delete", "../../etc/passwd"), ("delete", "flesh/nope.png")])
        self.assertEqual((d, k, u), ([], [], []))
        self.assertEqual(len(problems), 2)

    # -- apply / restore / empty
    def test_apply_moves_to_trash_with_sidecar_and_versions(self):
        postprocess.run(self.bank, engine=postprocess.PureEngine(),
                        opts=postprocess.Options(size=(32, 18), quiet=True), out=lambda *_: None)
        out, say = self.lines()
        batch = curate.apply(self.bank, [("delete", "flesh/flesh_1.png"), ("keep", "void/void_2.png")], out=say)
        self.assertFalse(os.path.exists(self.paths["flesh_1"]))
        self.assertFalse(os.path.exists(bankfiles.sidecar_path(self.paths["flesh_1"])))
        self.assertEqual(bankfiles.derived_files(os.path.join(self.bank, "flesh"), "flesh_1"), [])
        self.assertTrue(os.path.exists(os.path.join(batch, "flesh", "flesh_1.png")))
        self.assertTrue(os.path.exists(os.path.join(batch, "flesh", "derived", "flesh_1.wide.png")))
        self.assertTrue(bankfiles.read_sidecar(self.paths["void_2"])["keep"])
        self.assertTrue(os.path.exists(self.paths["flesh_0"]))  # others untouched
        # the renderer and generator never see the trash
        self.assertEqual(len(generate.images_in(os.path.join(self.bank, "flesh"))), 2)
        # undo
        curate.restore(self.bank, out=say)
        self.assertTrue(os.path.exists(self.paths["flesh_1"]))
        self.assertTrue(os.path.exists(os.path.join(self.bank, "flesh", "derived", "flesh_1.cutout.png")))
        self.assertEqual(curate.batches(self.bank), [])

    def test_unkeep(self):
        curate.set_keep(self.paths["flesh_0"], True)
        curate.apply(self.bank, [("unkeep", "flesh/flesh_0.png")], out=lambda *_: None)
        self.assertNotIn("keep", bankfiles.read_sidecar(self.paths["flesh_0"]))

    def test_delete_promoted_wide_takes_original(self):
        postprocess.run(self.bank, hooks=["void"], engine=postprocess.PureEngine(),
                        opts=postprocess.Options(size=(32, 18), wide_to_hook=True, quiet=True), out=lambda *_: None)
        self.assertTrue(os.path.exists(os.path.join(self.bank, "void", "void_0.wide.png")))
        curate.apply(self.bank, [("delete", "void/void_0.wide.png")], out=lambda *_: None)
        left = os.listdir(os.path.join(self.bank, "void", "derived"))
        self.assertFalse([n for n in left if n.startswith("void_0")], left)

    def test_cli_apply_needs_yes_without_terminal(self):
        lst = os.path.join(self.bank, "curate_list.txt")
        with open(lst, "w") as f:
            f.write("delete flesh/flesh_0.png\n")
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "apply", lst],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertTrue(os.path.exists(self.paths["flesh_0"]))
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "apply", lst, "--dry-run"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(self.paths["flesh_0"]))
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "apply", lst, "--yes"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(self.paths["flesh_0"]))
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "empty-trash", "--yes"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.bank, ".trash")))
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "restore"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("trash is empty", r.stdout)

    def test_cli_sheet(self):
        r = subprocess.run([sys.executable, CURATE, "--bank", self.bank, "sheet"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("6 pictures", r.stdout)


class KeepProtectsFromCap(unittest.TestCase):
    def test_cap_skips_kept(self):
        d = tempfile.mkdtemp(prefix="bankcap-")
        try:
            now = time.time()
            for i in range(5):
                p = os.path.join(d, "old%d.png" % i)
                open(p, "w").close()
                with open(os.path.join(d, "old%d.json" % i), "w") as f:
                    json.dump({"keep": i in (0, 1)}, f)
                os.utime(p, (now - 100 + i, now - 100 + i))
            removed = generate.enforce_cap(d, 3)
            self.assertEqual(sorted(os.path.basename(p) for p in removed), ["old2.png", "old3.png"])
            left = sorted(n for n in os.listdir(d) if n.endswith(".png"))
            self.assertEqual(left, ["old0.png", "old1.png", "old4.png"])
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
