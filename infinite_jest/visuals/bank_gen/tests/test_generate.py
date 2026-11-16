#!/usr/bin/env python3
"""Tests for generate.py using tests/fake_sd.py instead of stable-diffusion.cpp.

    python3 tests/test_generate.py -v

Linux only (reads /proc/<pid>/stat). Uses its own pause file (passed with
--pause-file), never the installation's /tmp/infinite_jest_busy, so it is safe
to run next to a live show. Everything it writes goes to a temporary bank
folder that is deleted afterwards.
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import generate  # noqa: E402
import prompts  # noqa: E402

GEN = os.path.join(ROOT, "generate.py")
FAKE = os.path.join(HERE, "fake_sd.py")
BUSY = os.path.join(tempfile.gettempdir(), "infinite_jest_busy_test_%d" % os.getpid())


def proc_state(pid):
    """Single-letter state from /proc/<pid>/stat (R, S, T, Z...), or None if gone."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            data = f.read()
    except FileNotFoundError:
        return None
    return data[data.rindex(")") + 2]


class Run:
    """generate.py in the background, its log lines collected."""

    def __init__(self, bank, *extra, fake_seconds=8):
        env = dict(os.environ, FAKE_SD_SECONDS=str(fake_seconds))
        self.model = os.path.join(bank, "fake-model.gguf")
        open(self.model, "w").close()
        cmd = [sys.executable, GEN, "--bank", bank, "--sd-bin", FAKE, "--model", self.model,
               "--anytime", "--pause-file", BUSY, *extra]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, env=env)
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.lines.append(line.rstrip())

    def wait_for(self, pattern, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            for ln in self.lines:
                m = re.search(pattern, ln)
                if m:
                    return m
            time.sleep(0.2)
        raise AssertionError("no log line matching %r; log:\n%s" % (pattern, self.text()))

    def sd_pid(self):
        return int(self.wait_for(r"sd running, pid (\d+)").group(1))

    def finish(self, timeout=60):
        self.p.wait(timeout)
        time.sleep(0.3)
        return self.p.returncode

    def text(self):
        return "\n".join(self.lines)

    def kill(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(15)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self.p.stdout.close()


class GenerateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(BUSY):
            os.remove(BUSY)

    def setUp(self):
        self.bank = tempfile.mkdtemp(prefix="bankgen-test-")
        self.runs = []

    def tearDown(self):
        for r in self.runs:
            r.kill()
        if os.path.exists(BUSY):
            os.remove(BUSY)
        shutil.rmtree(self.bank, ignore_errors=True)

    def start(self, *extra, **kw):
        r = Run(self.bank, *extra, **kw)
        self.runs.append(r)
        return r

    def hook_files(self, hook):
        d = os.path.join(self.bank, hook)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    # 1. image + sidecar land in the right hook folder
    def test_image_and_sidecar(self):
        r = self.start("--count", "1", "--hook", "scrawl", fake_seconds=2)
        self.assertEqual(r.finish(), 0, r.text())
        files = self.hook_files("scrawl")
        pngs = [f for f in files if f.endswith(".png")]
        self.assertEqual(len(pngs), 1, files)
        self.assertRegex(pngs[0], r"^\d{8}-\d{6}_\d+\.png$")
        side = os.path.join(self.bank, "scrawl", pngs[0][:-4] + ".json")
        with open(side) as f:
            meta = json.load(f)
        self.assertEqual(meta["hook"], "scrawl")
        self.assertEqual(str(meta["seed"]), pngs[0][:-4].split("_")[1])
        self.assertEqual(meta["model"], "fake-model.gguf")
        self.assertIn("prompt", meta)
        self.assertGreater(meta["seconds"], 1)
        with open(os.path.join(self.bank, "scrawl", pngs[0]), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        for h in prompts.HOOKS:  # nothing in the other hooks, nothing left in .incoming
            if h != "scrawl":
                self.assertEqual(self.hook_files(h), [])
        leftovers = [f for f in os.listdir(os.path.join(self.bank, ".incoming")) if f != "last_sd.log"]
        self.assertEqual(leftovers, [])

    # 1b. v2 sidecar: tags, theme, signature; --postprocess makes the versions
    def test_tags_theme_postprocess(self):
        r = self.start("--count", "1", "--hook", "flesh", "--theme", "ledger", "--postprocess", fake_seconds=1)
        self.assertEqual(r.finish(), 0, r.text())
        pngs = [f for f in self.hook_files("flesh") if f.endswith(".png")]
        with open(os.path.join(self.bank, "flesh", pngs[0][:-4] + ".json")) as f:
            meta = json.load(f)
        self.assertEqual(meta["theme"], "ledger")
        self.assertEqual(meta["tags"]["hook"], "flesh")
        self.assertIn("theme:ledger", meta["tag_list"])
        self.assertEqual(meta["prompt_version"], 2)
        self.assertIn("theme ledger", r.text())
        derived = os.listdir(os.path.join(self.bank, "flesh", "derived"))
        self.assertIn(pngs[0][:-4] + ".wide.png", derived)
        self.assertIn("post   ", r.text())

    # 2. pause file stops sd (state T); removing it resumes
    def test_pause_and_resume(self):
        r = self.start("--count", "1", "--hook", "flesh", fake_seconds=8)
        pid = r.sd_pid()
        time.sleep(1)
        self.assertIn(proc_state(pid), ("R", "S"))
        open(BUSY, "w").close()
        time.sleep(3)  # checker polls every 2 s
        self.assertEqual(proc_state(pid), "T", r.text())
        time.sleep(4)  # stays stopped
        self.assertEqual(proc_state(pid), "T")
        os.remove(BUSY)
        time.sleep(3)
        self.assertIn(proc_state(pid), ("R", "S", None), r.text())
        self.assertEqual(r.finish(), 0, r.text())
        self.assertIn("paused (pause file", r.text())
        self.assertIn("resumed after", r.text())
        self.assertEqual(len([f for f in self.hook_files("flesh") if f.endswith(".png")]), 1)
        side = [f for f in self.hook_files("flesh") if f.endswith(".json")][0]
        with open(os.path.join(self.bank, "flesh", side)) as f:
            self.assertGreaterEqual(json.load(f)["paused_seconds"], 5)

    # 2b. the --state-file phase also pauses
    def test_state_file_pauses(self):
        state = os.path.join(self.bank, "state.json")
        with open(state, "w") as f:
            json.dump({"phase": "idle"}, f)
        r = self.start("--count", "1", "--hook", "void", "--state-file", state, fake_seconds=6)
        pid = r.sd_pid()
        with open(state, "w") as f:
            json.dump({"type": "state", "data": {"phase": "profiling"}}, f)
        time.sleep(3)
        self.assertEqual(proc_state(pid), "T", r.text())
        with open(state, "w") as f:
            json.dump({"phase": "idle"}, f)
        self.assertEqual(r.finish(), 0, r.text())
        self.assertIn("phase=profiling", r.text())

    # 3. --abort-after kills the paused sd, then retries once the room is free
    def test_abort_after(self):
        r = self.start("--count", "1", "--hook", "mirror", "--abort-after", "3", fake_seconds=6)
        pid = r.sd_pid()
        open(BUSY, "w").close()
        r.wait_for(r"abandoning this image", timeout=15)
        time.sleep(0.5)
        self.assertIn(proc_state(pid), (None, "Z"), "sd still alive after abort")
        self.assertEqual(self.hook_files("mirror"), [])
        r.wait_for(r"visitor present", timeout=10)  # waiting, not starting a new one
        os.remove(BUSY)
        self.assertEqual(r.finish(), 0, r.text())
        self.assertEqual(len(re.findall(r"sd running, pid", r.text())), 2)
        self.assertEqual(len([f for f in self.hook_files("mirror") if f.endswith(".png")]), 1)

    # 4. per-hook cap deletes the oldest image and its sidecar
    def test_cap_deletes_oldest(self):
        d = os.path.join(self.bank, "inverted")
        os.makedirs(d)
        now = time.time()
        for i in range(4):
            base = os.path.join(d, "old%d" % i)
            for ext in (".png", ".json"):
                open(base + ext, "w").close()
                os.utime(base + ext, (now - 1000 + i, now - 1000 + i))
        r = self.start("--count", "1", "--hook", "inverted", "--max-per-hook", "3", fake_seconds=1)
        self.assertEqual(r.finish(), 0, r.text())
        files = self.hook_files("inverted")
        pngs = [f for f in files if f.endswith(".png")]
        self.assertEqual(len(pngs), 3, files)
        for gone in ("old0.png", "old0.json", "old1.png", "old1.json"):
            self.assertNotIn(gone, files)
        self.assertIn("old2.png", files)
        self.assertIn("old3.png", files)
        self.assertIn("removed 2 oldest", r.text())

    # stopping generate.py (e.g. systemctl stop) also ends sd, even while paused
    def test_sigterm_stops_sd(self):
        r = self.start("--hook", "flesh", fake_seconds=30)
        pid = r.sd_pid()
        open(BUSY, "w").close()
        time.sleep(3)
        self.assertEqual(proc_state(pid), "T")
        r.p.terminate()
        self.assertEqual(r.finish(timeout=20), 0, r.text())
        time.sleep(0.5)
        self.assertIn(proc_state(pid), (None, "Z"))
        self.assertEqual(self.hook_files("flesh"), [])
        self.assertEqual(os.listdir(os.path.join(self.bank, ".incoming")), ["last_sd.log"])

    # sd failure is reported and nothing lands in the bank
    def test_failure_reported(self):
        os.environ["FAKE_SD_EXIT"] = "3"
        try:
            r = self.start("--count", "1", "--hook", "flesh", fake_seconds=0.2)
            r.wait_for(r"sd failed \(exit code 3\)", timeout=15)
            r.wait_for(r"simulated failure")
        finally:
            del os.environ["FAKE_SD_EXIT"]
        self.assertEqual(self.hook_files("flesh"), [])

    def test_dry_run(self):
        out = subprocess.run([sys.executable, GEN, "--dry-run", "--hook", "void", "--bank", self.bank,
                              "--sd-bin", "/nonexistent/sd-cli", "--model", "/nonexistent/m.gguf"],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("command:  nice -n 15", out.stdout)
        for flag in ("-m /nonexistent/m.gguf", "--steps 4", "--cfg-scale 1.0", "-W 512", "-H 512",
                     "-t 3", "--seed", "-o "):
            self.assertIn(flag, out.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.bank, "void")))

    def test_missing_binary_is_clear(self):
        out = subprocess.run([sys.executable, GEN, "--count", "1", "--bank", self.bank,
                              "--sd-bin", "/nonexistent/sd-cli", "--model", "/nonexistent/m.gguf"],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 2)
        self.assertIn("program not found", out.stdout)


class UnitTests(unittest.TestCase):
    def test_window(self):
        def at(h):
            return time.struct_time((2026, 1, 1, h, 0, 0, 0, 1, -1))
        w = generate.parse_hours("22-8")
        self.assertTrue(all(generate.in_window(w, at(h)) for h in (22, 23, 0, 3, 7)))
        self.assertFalse(any(generate.in_window(w, at(h)) for h in (8, 12, 21)))
        d = generate.parse_hours("9-17")
        self.assertTrue(generate.in_window(d, at(9)))
        self.assertFalse(generate.in_window(d, at(17)))
        self.assertTrue(generate.in_window(generate.parse_hours("0-24"), at(13)))

    def test_pick_hook_prefers_empty(self):
        bank = tempfile.mkdtemp(prefix="bankgen-unit-")
        try:
            for h in prompts.HOOKS:
                os.makedirs(os.path.join(bank, h))
                if h != "void":
                    for i in range(30):
                        open(os.path.join(bank, h, "%d.png" % i), "w").close()
            rng = random.Random(1)
            picks = [generate.pick_hook(bank, rng) for _ in range(2000)]
            self.assertGreater(picks.count("void") / len(picks), 0.8)
            self.assertEqual(generate.pick_hook(bank, rng, "flesh"), "flesh")
        finally:
            shutil.rmtree(bank)

    def test_prompts(self):
        rng = random.Random(0)
        for h in prompts.HOOKS:
            for _ in range(50):
                p, n, parts = prompts.build_prompt(h, rng)
                self.assertTrue(p and n)
                self.assertLess(len(p.split()), 70, p)  # stays near CLIP's 77-token window


if __name__ == "__main__":
    unittest.main()
