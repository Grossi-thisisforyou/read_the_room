#!/usr/bin/env python3
"""Tests for the Mac pipeline (mac/) using a fake painter: no torch, no model.

    python3 tests/test_mac.py -v

Checks that mac_generate.py writes the same folders and sidecars as
generate.py, balances hooks, applies themes and post-processing, and that
the shell scripts at least parse. The real diffusers path can only be tried
on a Mac (see README).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAC = os.path.join(ROOT, "mac")
sys.path.insert(0, ROOT)
import prompts  # noqa: E402

GEN = os.path.join(MAC, "mac_generate.py")


def run(*args, timeout=60):
    return subprocess.run([sys.executable, GEN, "--fake", *args], capture_output=True, text=True,
                          timeout=timeout)


class MacGenerateTests(unittest.TestCase):
    def setUp(self):
        self.bank = tempfile.mkdtemp(prefix="bankmac-test-")

    def tearDown(self):
        shutil.rmtree(self.bank, ignore_errors=True)

    def pngs(self, hook):
        d = os.path.join(self.bank, hook)
        return sorted(n for n in os.listdir(d) if n.endswith(".png")) if os.path.isdir(d) else []

    def test_count_and_sidecars(self):
        r = run("--count", "10", "--bank", self.bank)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        total = 0
        for h in prompts.HOOKS:
            for n in self.pngs(h):
                total += 1
                self.assertRegex(n, r"^\d{8}-\d{6}_\d+\.png$")   # same names as generate.py
                with open(os.path.join(self.bank, h, n[:-4] + ".json")) as f:
                    meta = json.load(f)
                self.assertEqual(meta["hook"], h)
                self.assertEqual(meta["tags"]["hook"], h)
                self.assertEqual(str(meta["seed"]), n[:-4].split("_")[1])
                for k in ("prompt", "negative_prompt", "tag_list", "signature", "steps", "model",
                          "device", "created", "generator"):
                    self.assertIn(k, meta)
                self.assertEqual(meta["steps"], 2)
        self.assertEqual(total, 10)
        self.assertEqual(os.listdir(os.path.join(self.bank, ".incoming")), [])
        self.assertIn("copy_to_pi.sh", r.stdout)

    def test_per_hook_tops_up_evenly(self):
        r = run("--per-hook", "3", "--bank", self.bank)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([len(self.pngs(h)) for h in prompts.HOOKS], [3] * 5)
        r = run("--per-hook", "3", "--bank", self.bank)  # nothing more to do
        self.assertIn("every hook has at least 3", r.stdout)
        self.assertEqual(sum(len(self.pngs(h)) for h in prompts.HOOKS), 15)

    def test_hook_and_theme(self):
        r = run("--count", "6", "--hook", "mirror", "--theme", "afterglow", "--bank", self.bank)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = self.pngs("mirror")
        self.assertEqual(len(names), 6)
        for n in names:
            with open(os.path.join(self.bank, "mirror", n[:-4] + ".json")) as f:
                meta = json.load(f)
            self.assertEqual(meta["theme"], "afterglow")
            self.assertIn("theme:afterglow", meta["tag_list"])
        sigs = set()
        for n in names:
            with open(os.path.join(self.bank, "mirror", n[:-4] + ".json")) as f:
                sigs.add(json.load(f)["signature"])
        self.assertEqual(len(sigs), 6)

    def test_postprocess_flag(self):
        r = run("--count", "2", "--hook", "flesh", "--postprocess", "--bank", self.bank)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = os.path.join(self.bank, "flesh", "derived")
        self.assertTrue(any(n.endswith(".wide.png") for n in os.listdir(d)), os.listdir(d))

    def test_bad_options(self):
        self.assertNotEqual(run("--theme", "nonsense", "--bank", self.bank).returncode, 0)
        self.assertNotEqual(run("--size", "500x500", "--bank", self.bank).returncode, 0)

    def test_without_torch_says_what_to_do(self):
        try:
            import torch  # noqa: F401
            self.skipTest("torch is installed here")
        except ImportError:
            pass
        r = subprocess.run([sys.executable, GEN, "--count", "1", "--bank", self.bank],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("install_mac.sh", r.stdout)


class ScriptTests(unittest.TestCase):
    SCRIPTS = ("install_mac.sh", "generate_mac.sh", "copy_to_pi.sh", "make_images.command")

    def test_scripts_parse_and_are_executable(self):
        for s in self.SCRIPTS:
            p = os.path.join(MAC, s)
            r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "%s: %s" % (s, r.stderr))
            self.assertTrue(os.access(p, os.X_OK), "%s is not executable" % s)

    def test_install_is_mac_only_and_idempotent_by_design(self):
        with open(os.path.join(MAC, "install_mac.sh")) as f:
            text = f.read()
        self.assertIn('uname -s)" = "Darwin"', text)
        self.assertIn("brew list --versions", text)          # skips installed Python
        self.assertIn('[ -x "$VENV/bin/python" ]', text)     # skips an existing venv
        self.assertIn(".ij-requirements", text)               # skips installed packages
        if sys.platform != "darwin":
            r = subprocess.run(["bash", os.path.join(MAC, "install_mac.sh")], capture_output=True,
                               text=True, timeout=30)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("for macOS", r.stderr)

    def test_copy_target(self):
        with open(os.path.join(MAC, "copy_to_pi.sh")) as f:
            text = f.read()
        self.assertIn("pi@inartwetrust.local", text)
        self.assertIn("read_the_room/infinite_jest/visuals/bank", text)
        self.assertNotIn("--delete", text)  # never deletes on the Pi

    def test_requirements_pinned(self):
        with open(os.path.join(MAC, "requirements-mac.txt")) as f:
            reqs = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        names = {re.split(r"[<>=]", r)[0] for r in reqs}
        self.assertTrue({"torch", "diffusers", "transformers", "accelerate", "pillow"} <= names, names)


if __name__ == "__main__":
    unittest.main()
