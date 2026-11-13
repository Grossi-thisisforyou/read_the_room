#!/usr/bin/env python3
"""INFINITE JEST bank generator: grow bank/<hook>/ with images made on the Pi.

Runs stable-diffusion.cpp (CPU) with an SD-Turbo model, one 512x512 image at a
time, at low priority. It only works inside the night-time window (--hours) and
freezes the generator whenever a visitor is present, so the renderer and audio
keep the CPU.

    python3 generate.py --dry-run              # show what it would run
    python3 generate.py --count 1 --anytime    # make one test image now
    python3 generate.py                        # run forever (overnight window)

A visitor is "present" while the pause file exists (default
/tmp/infinite_jest_busy) or, with --state-file, while that JSON file's "phase"
is anything but "idle". While present, the running generator is paused with
SIGSTOP and resumed with SIGCONT. If a pause lasts longer than --abort-after
seconds, that image is abandoned and tried again later.

Python 3 standard library only.
"""
import argparse
import json
import os
import random
import shlex
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prompts  # noqa: E402

HOOKS = prompts.HOOKS
IMAGE_EXT = (".png", ".jpg", ".jpeg")
DEFAULT_BANK = os.path.normpath(os.path.join(HERE, "..", "bank"))
DEFAULT_PAUSE_FILE = "/tmp/infinite_jest_busy"
SD_BIN_CANDIDATES = [  # newer sd.cpp builds name the CLI "sd-cli", older ones "sd"
    "~/stable-diffusion.cpp/build/bin/sd-cli",
    "~/stable-diffusion.cpp/build/bin/sd",
]
MODEL_CANDIDATES = [  # made by install_sdcpp.sh; the quantized one is faster
    "~/sd-models/sd_turbo.q8_0.gguf",
    "~/sd-models/sd_turbo.safetensors",
]
POLL_RUNNING = 2.0   # seconds between busy checks while sd runs
POLL_WAITING = 5.0   # seconds between checks while waiting to start


def log(msg):
    print("%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def first_existing(candidates):
    for c in candidates:
        p = os.path.expanduser(c)
        if os.path.exists(p):
            return p
    return os.path.expanduser(candidates[0])


# ---------------------------------------------------------------- busy / window

class BusyCheck:
    """Is a visitor present? Pause file and/or engine state file."""

    def __init__(self, pause_file, state_file=None, stale_after=0):
        self.pause_file = pause_file
        self.state_file = state_file
        self.stale_after = stale_after
        self.reason = ""

    def __call__(self):
        if self.pause_file:
            try:
                st = os.stat(self.pause_file)
            except FileNotFoundError:
                st = None
            except OSError:
                st = None
            if st is not None:
                age = time.time() - st.st_mtime
                if not self.stale_after or age < self.stale_after:
                    self.reason = "pause file %s" % self.pause_file
                    return True
        if self.state_file:
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
            except FileNotFoundError:
                state = None  # engine not running: nobody to protect
            except (OSError, ValueError):
                # Half-written file: assume busy and look again in a moment.
                self.reason = "state file unreadable"
                return True
            if isinstance(state, dict):
                if state.get("type") == "state" and isinstance(state.get("data"), dict):
                    state = state["data"]
                phase = state.get("phase", "idle")
                if phase != "idle":
                    self.reason = "phase=%s" % phase
                    return True
        self.reason = ""
        return False


def parse_hours(text):
    """'22-8' -> (22, 8). Equal numbers mean all day."""
    try:
        a, b = text.split("-")
        a, b = int(a), int(b)
    except ValueError:
        raise argparse.ArgumentTypeError("--hours wants START-END, e.g. 22-8")
    if not (0 <= a <= 24 and 0 <= b <= 24):
        raise argparse.ArgumentTypeError("--hours values must be 0-24")
    return a % 24, b % 24


def in_window(hours, now=None):
    start, end = hours
    h = (now or time.localtime()).tm_hour
    if start == end:
        return True
    if start < end:
        return start <= h < end
    return h >= start or h < end  # wraps past midnight


# ---------------------------------------------------------------- bank

def images_in(d):
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(IMAGE_EXT) and not n.startswith(".")]


def pick_hook(bank, rng, forced=None):
    """Weighted toward hooks with the fewest images: weight 1/(count+1)."""
    if forced:
        return forced
    counts = {h: len(images_in(os.path.join(bank, h))) for h in HOOKS}
    weights = [1.0 / (counts[h] + 1) for h in HOOKS]
    return rng.choices(HOOKS, weights=weights)[0]


def enforce_cap(hook_dir, cap):
    """Delete the oldest images (by modification time) beyond cap, with sidecars."""
    imgs = images_in(hook_dir)
    if cap <= 0 or len(imgs) <= cap:
        return []
    imgs.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)))
    doomed = imgs[:len(imgs) - cap]
    for p in doomed:
        for q in (p, os.path.splitext(p)[0] + ".json"):
            try:
                os.remove(q)
            except FileNotFoundError:
                pass
    return doomed


def free_mb(path):
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize / 1e6
    except OSError:
        return float("inf")


def looks_like_image(path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8")


# ---------------------------------------------------------------- one image

class Stop(Exception):
    pass


class Generator:
    def __init__(self, args):
        self.a = args
        self.busy = BusyCheck(args.pause_file, args.state_file, args.stale_after)
        self.rng = random.Random()
        self.sysrng = random.SystemRandom()
        self.proc = None
        self.stopping = False

    # -- process control
    def _signal_group(self, sig):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass

    def shutdown(self, signum, _frame):
        log("received signal %d, stopping" % signum)
        self.stopping = True
        self._signal_group(signal.SIGCONT)
        self._signal_group(signal.SIGTERM)

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stopping:
                raise Stop()
            time.sleep(min(0.5, max(0.0, end - time.time())))

    # -- command
    def command(self, prompt, negative, seed, out_path):
        a = self.a
        cmd = []
        if shutil.which("nice"):
            cmd += ["nice", "-n", str(a.nice)]
        if shutil.which("ionice"):
            cmd += ["ionice", "-c3"]
        cmd += [
            a.sd_bin,
            "-m", a.model,
            "-p", prompt,
            "-n", negative,
            "--steps", str(a.steps),
            "--cfg-scale", str(a.cfg),
            "--sampling-method", a.sampler,
            "-W", str(a.width),
            "-H", str(a.height),
            "--seed", str(seed),
            "-t", str(a.threads),
            "-o", out_path,
        ]
        cmd += a.extra
        return cmd

    # -- wait for the right moment
    def wait_until_ready(self):
        said = None
        while True:
            if self.stopping:
                raise Stop()
            if not self.a.anytime and not in_window(self.a.hours):
                msg = "outside generating hours %02d-%02d, waiting" % self.a.hours
                delay = 30
            elif self.busy():
                msg = "visitor present (%s), waiting" % self.busy.reason
                delay = POLL_WAITING
            elif free_mb(self.a.bank) < self.a.min_free_mb:
                msg = "less than %d MB free disk, waiting" % self.a.min_free_mb
                delay = 300
            else:
                if said:
                    log("ready")
                return
            if msg != said:
                log(msg)
                said = msg
            self.sleep(delay)

    # -- one attempt; returns "ok", "aborted" or "failed"
    def make_one(self):
        a = self.a
        hook = pick_hook(a.bank, self.rng, a.hook)
        prompt, negative, parts = prompts.build_prompt(hook, self.rng)
        seed = a.seed if a.seed is not None else self.sysrng.randrange(0, 2**31 - 1)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = "%s_%d" % (stamp, seed)
        hook_dir = os.path.join(a.bank, hook)
        incoming = os.path.join(a.bank, ".incoming")  # dot dir: renderer ignores it
        tmp_png = os.path.join(incoming, name + ".png")
        cmd = self.command(prompt, negative, seed, tmp_png)

        if a.dry_run:
            print("hook:     %s" % hook)
            print("prompt:   %s" % prompt)
            print("negative: %s" % negative)
            print("seed:     %d" % seed)
            print("output:   %s" % os.path.join(hook_dir, name + ".png"))
            print("command:  %s" % shlex.join(cmd))
            return "ok"

        os.makedirs(incoming, exist_ok=True)
        os.makedirs(hook_dir, exist_ok=True)
        sd_log_path = os.path.join(incoming, "last_sd.log")
        log("start  hook=%s seed=%d" % (hook, seed))
        log("prompt %s" % prompt)
        t0 = time.time()
        paused_total = 0.0
        paused_since = None
        with open(sd_log_path, "wb") as sd_log:
            self.proc = subprocess.Popen(cmd, stdout=sd_log, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
            log("sd running, pid %d" % self.proc.pid)
            result = None
            while self.proc.poll() is None:
                if self.stopping:
                    self._signal_group(signal.SIGCONT)
                    self._signal_group(signal.SIGTERM)
                    try:
                        self.proc.wait(10)
                    except subprocess.TimeoutExpired:
                        self._signal_group(signal.SIGKILL)
                        self.proc.wait()
                    self._discard(tmp_png)
                    raise Stop()
                busy = self.busy()
                if busy and paused_since is None:
                    self._signal_group(signal.SIGSTOP)
                    paused_since = time.time()
                    log("paused (%s), sd stopped" % self.busy.reason)
                elif not busy and paused_since is not None:
                    self._signal_group(signal.SIGCONT)
                    paused_total += time.time() - paused_since
                    log("resumed after %.0f s" % (time.time() - paused_since))
                    paused_since = None
                elif paused_since is not None and time.time() - paused_since > a.abort_after:
                    log("paused longer than %d s, abandoning this image" % a.abort_after)
                    self._signal_group(signal.SIGKILL)
                    self._signal_group(signal.SIGCONT)
                    self.proc.wait()
                    result = "aborted"
                    break
                time.sleep(POLL_RUNNING)
        rc = self.proc.returncode
        self.proc = None
        seconds = time.time() - t0
        if result == "aborted":
            self._discard(tmp_png)
            return "aborted"
        if rc != 0 or not looks_like_image(tmp_png):
            log("sd failed (exit code %s) after %.0f s; last lines of %s:" % (rc, seconds, sd_log_path))
            for line in tail(sd_log_path, 8):
                log("  | " + line)
            self._discard(tmp_png)
            return "failed"

        final_png = os.path.join(hook_dir, name + ".png")
        os.replace(tmp_png, final_png)
        sidecar = {
            "hook": hook,
            "prompt": prompt,
            "negative_prompt": negative,
            "parts": parts,
            "seed": seed,
            "model": os.path.basename(a.model),
            "model_path": a.model,
            "steps": a.steps,
            "cfg_scale": a.cfg,
            "sampler": a.sampler,
            "width": a.width,
            "height": a.height,
            "threads": a.threads,
            "seconds": round(seconds - paused_total, 1),
            "paused_seconds": round(paused_total, 1),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "generator": "bank_gen/generate.py (stable-diffusion.cpp)",
        }
        tmp_json = os.path.join(incoming, name + ".json")
        with open(tmp_json, "w") as f:
            json.dump(sidecar, f, indent=2)
        os.replace(tmp_json, os.path.join(hook_dir, name + ".json"))
        removed = enforce_cap(hook_dir, a.max_per_hook)
        log("done   %s (%.0f s working%s)%s" % (
            os.path.relpath(final_png, a.bank), seconds - paused_total,
            ", %.0f s paused" % paused_total if paused_total else "",
            "; removed %d oldest" % len(removed) if removed else ""))
        return "ok"

    @staticmethod
    def _discard(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    # -- main loop
    def run(self):
        a = self.a
        made = 0
        failures = 0
        while a.count is None or made < a.count:
            if not a.dry_run:
                self.wait_until_ready()
            r = self.make_one()
            if r == "ok":
                made += 1
                failures = 0
            elif r == "aborted":
                log("will try again when the room is free")
            else:
                failures += 1
                if a.count is not None and failures >= 3:
                    log("3 failures in a row, giving up")
                    return 1
                delay = min(900, 30 * 2 ** (failures - 1))
                log("waiting %d s before trying again" % delay)
                self.sleep(delay)
        log("made %d image(s)" % made)
        return 0


def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = [ln.strip() for ln in data.replace("\r", "\n").split("\n") if ln.strip()]
    return lines[-n:]


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Grow the INFINITE JEST image bank on the Pi with stable-diffusion.cpp.")
    p.add_argument("--count", type=int, help="make N images then stop (default: forever)")
    p.add_argument("--hook", choices=HOOKS, help="only make images for this hook")
    p.add_argument("--bank", default=DEFAULT_BANK, help="bank folder (default: %(default)s)")
    p.add_argument("--sd-bin", default=None,
                   help="stable-diffusion.cpp CLI (default: first of %s)" % ", ".join(SD_BIN_CANDIDATES))
    p.add_argument("--model", default=None,
                   help="model file (default: first of %s)" % ", ".join(MODEL_CANDIDATES))
    p.add_argument("--steps", type=int, default=4, help="sampling steps, 1-4 for SD-Turbo (default: 4)")
    p.add_argument("--cfg", type=float, default=1.0, help="cfg scale (default: 1.0)")
    p.add_argument("--sampler", default="euler_a", help="sampling method (default: euler_a)")
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--threads", type=int, default=3, help="CPU threads for sd (default: 3 of 4)")
    p.add_argument("--nice", type=int, default=15, help="nice level for sd (default: 15)")
    p.add_argument("--seed", type=int, default=None, help="fixed seed (default: random each image)")
    p.add_argument("--max-per-hook", type=int, default=400,
                   help="keep at most N images per hook, deleting the oldest (default: 400; 0 = no cap)")
    p.add_argument("--hours", type=parse_hours, default=(22, 8),
                   help="only generate between these local hours (default: 22-8)")
    p.add_argument("--anytime", action="store_true", help="ignore --hours")
    p.add_argument("--pause-file", default=DEFAULT_PAUSE_FILE,
                   help="pause while this file exists (default: %(default)s)")
    p.add_argument("--state-file", default=None,
                   help='also pause while this JSON file\'s "phase" is not "idle"')
    p.add_argument("--stale-after", type=float, default=0,
                   help="ignore a pause file not touched for this many seconds (default: 0 = never stale)")
    p.add_argument("--abort-after", type=float, default=600,
                   help="abandon an image paused longer than this many seconds (default: 600)")
    p.add_argument("--min-free-mb", type=int, default=1000,
                   help="wait while the disk has less free space than this (default: 1000)")
    p.add_argument("--dry-run", action="store_true", help="print the command and prompt, run nothing")
    p.add_argument("extra", nargs="*", help="extra arguments passed to sd after --, e.g. -- --vae-tiling")
    a = p.parse_args(argv)

    a.bank = os.path.abspath(os.path.expanduser(a.bank))
    a.sd_bin = os.path.expanduser(a.sd_bin) if a.sd_bin else first_existing(SD_BIN_CANDIDATES)
    a.model = os.path.expanduser(a.model) if a.model else first_existing(MODEL_CANDIDATES)
    if a.dry_run and a.count is None:
        a.count = 1

    if not a.dry_run:
        problems = []
        if not (os.path.isfile(a.sd_bin) and os.access(a.sd_bin, os.X_OK)):
            problems.append("stable-diffusion.cpp program not found: %s (run install_sdcpp.sh, or pass --sd-bin)" % a.sd_bin)
        if not os.path.isfile(a.model):
            problems.append("model not found: %s (run install_sdcpp.sh, or pass --model)" % a.model)
        if problems:
            for m in problems:
                log("ERROR " + m)
            return 2
        os.makedirs(a.bank, exist_ok=True)

    g = Generator(a)
    signal.signal(signal.SIGTERM, g.shutdown)
    signal.signal(signal.SIGINT, g.shutdown)
    if not a.dry_run:
        log("bank %s | model %s | %d steps, cfg %s, %dx%d, %d threads | hours %s | cap %d/hook" % (
            a.bank, os.path.basename(a.model), a.steps, a.cfg, a.width, a.height, a.threads,
            "any" if a.anytime else "%02d-%02d" % a.hours, a.max_per_hook))
    try:
        return g.run()
    except Stop:
        log("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
