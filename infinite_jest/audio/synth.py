"""TechnoSynth: the INFINITE JEST live techno generator.

Call set_state(state) whenever the show state changes and render_block() to
get the next 1024 stereo frames (int16).

Layers, from slow to fast:
  SetClock (compose.py)  the room's hours-long drift: key, mode, idle tempo,
                         kit, energy, room size, grit
  Arranger (compose.py)  8 to 32-bar sections, fills, sweeps, chord changes
  bar patterns (here)    drum, stab and bass patterns, re-evaluated every bar
                         from stable per-phrase dice against the current
                         intensity / OCEAN, so grooves repeat and evolve
  render_block (here)    buses, live voices (drone, bass, tension noise),
                         room, delay and the master chain

Everything audible glides: voice levels, filters, tempo and OCEAN-derived
parameters follow their targets over one to two bars; the phone (tilt)
follows within ~50 ms. Patterns and the personal motif come from an RNG
seeded by the visitor id, so a given visitor always gets 'their' track.
"""
import os
import sys
import threading
import time
import zlib

import numpy as np

from . import voices as V
from .bass import BassVoice
from .compose import KITS, MODES, Arranger, Dice, SetClock
from .dsp import (SR, TWO_PI, Glue, Limiter, OnePole, PingPong, Reso, Room,
                  Saturator, clamp, lp_coef, midi_hz, saw_blep)

PHASES = ("idle", "approach", "profiling", "hook", "release", "wipe")
OCEAN = ("O", "C", "E", "A", "N")
BPM_MIN, BPM_MAX = 120.0, 145.0

# Target level of each voice per phase (0..1), plus mix/FX settings.
#   verb = reverb send multiplier, vfb = room size (0.88..0.96 -> T60),
#   open = master filter openness, breath = slow amplitude breathing of the
#   drone, hs = how strongly the visitor's hook shapes the arrangement.
_P = ("kick", "rumble", "hat", "ohat", "ride", "clap", "snare", "clank", "metal", "click",
      "stab", "bass", "drone", "riser", "glitch", "verb", "vfb", "open", "breath", "hs")
PHASE_TABLE = {
    #            kick rumb hat  ohat ride clap snr  clnk metl clik stab bass dron risr glch verb vfb   open brth hs
    "idle":      (0.5, 0.0, 0.45, 0.0, 0.0, 0.0, 0.0, 0.3, 0.25, 0.2, 0.5, 0.0, 0.6, 0.0, 0.0, 0.6, 0.93, 0.3, 1.0, 0.0),
    "approach":  (0.85, 0.7, 0.35, 0.0, 0.0, 0.0, 0.3, 0.3, 0.2, 0.2, 0.2, 0.5, 0.7, 0.35, 0.1, 0.4, 0.90, 0.5, 0.5, 0.25),
    "profiling": (1.0, 0.85, 0.75, 0.3, 0.2, 0.35, 0.6, 0.55, 0.4, 1.0, 0.35, 0.7, 0.5, 0.7, 0.6, 0.3, 0.88, 0.7, 0.2, 0.5),
    "hook":      (1.0, 1.0, 1.0, 0.8, 0.7, 1.0, 0.8, 1.0, 0.7, 0.45, 1.0, 1.0, 0.35, 1.0, 1.0, 0.28, 0.88, 1.0, 0.0, 1.0),
    "release":   (0.5, 0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.35, 0.25, 0.3, 0.6, 0.2, 0.55, 0.0, 0.15, 0.7, 0.95, 0.45, 0.8, 0.5),
    "wipe":      (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.0, 0.0, 0.6, 0.93, 0.3, 1.0, 0.0),
}
PHASE_TABLE = {k: dict(zip(_P, v)) for k, v in PHASE_TABLE.items()}

# Hook = arrangement family. Multipliers on voice levels; extras are amounts.
_HK = ("kick", "rumble", "hat", "ohat", "ride", "clap", "snare", "clank", "metal", "click", "stab",
       "bass", "drone", "riser", "glitch", "open", "verb", "level", "sub",
       "vox", "breath", "rev", "offgrid", "broken", "heavy", "acid", "roll", "bpm")
HOOKS = {
    #            kick rumb hat  ohat ride clap snr  clnk metl clik stab bass dron risr glch open verb lvl  sub  vox brth rev  offg brkn hvy  acid roll bpm
    "default":  (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0),
    "flesh":    (1.15, 1.3, 0.6, 0.4, 0.5, 0.6, 0.8, 0.6, 0.8, 0.4, 0.7, 1.2, 1.3, 0.6, 0.4, 0.7, 1.1, 1.0, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, -5),
    "scrawl":   (0.9, 0.8, 0.9, 0.5, 0.8, 0.7, 1.2, 1.0, 1.0, 1.2, 0.6, 1.0, 0.7, 0.8, 2.0, 1.0, 0.9, 1.0, 1.0, 1.0, 0.0, 0.0, 0.1, 1.0, 0.0, 1.0, 0.0, 0),
    "inverted": (1.0, 1.0, 1.0, 0.8, 1.0, 0.6, 1.0, 0.9, 0.8, 0.8, 1.0, 1.0, 1.0, 0.5, 0.8, 0.9, 1.2, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.3, 0.0, 0.6, 0.0, 0),
    "mirror":   (0.15, 0.1, 0.25, 0.0, 0.0, 0.0, 0.2, 0.25, 0.0, 0.3, 0.35, 0.3, 0.8, 0.1, 0.1, 0.45, 0.5, 0.95, 1.3, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -4),
    "void":     (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.0, 0.12, 0.0, 0.0, 0.15, 0.0, 0.0, 0.2, 0.7, 0.5, 1.8, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -6),
}
HOOKS = {k: dict(zip(_HK, v)) for k, v in HOOKS.items()}
_HOOK_EXTRA = ("vox", "breath", "rev", "offgrid", "broken", "heavy", "acid", "roll", "bpm")

# instrument -> (phase/hook voice key, arranger layer, base level, dry, reverb send, delay send)
INST = {
    "kick":     ("kick", "kick", 0.46, 1.0, 0.03, 0.0),
    "kick_far": ("kick", "far", 0.30, 0.7, 0.55, 0.12),
    "rumble":   ("rumble", "rumble", 0.36, 1.0, 0.0, 0.0),
    "hat":      ("hat", "hat", 0.48, 1.0, 0.07, 0.05),
    "ohat":     ("ohat", "ohat", 0.24, 1.0, 0.12, 0.05),
    "ride":     ("ride", "ride", 0.17, 1.0, 0.12, 0.04),
    "clap":     ("clap", "clap", 0.50, 1.0, 0.30, 0.10),
    "snare":    ("snare", "snare", 0.42, 1.0, 0.25, 0.08),
    "roll":     ("snare", None, 0.36, 1.0, 0.30, 0.0),
    "tom":      ("snare", None, 0.42, 1.0, 0.35, 0.10),
    "clank":    ("clank", "clank", 0.38, 1.0, 0.33, 0.25),
    "metal":    ("metal", "metal", 0.22, 1.0, 0.45, 0.20),
    "tick":     ("click", "click", 0.28, 1.0, 0.15, 0.30),
    "stab":     ("stab", "stab", 0.52, 1.0, 0.33, 0.45),
    "vox":      ("vox", "vox", 0.42, 1.0, 0.20, 0.35),
    "breath":   ("breath", "breath", 0.30, 1.0, 0.25, 0.0),
    "swell":    ("rev", None, 0.30, 1.0, 0.30, 0.0),
    "impact":   (None, None, 0.34, 1.0, 0.55, 0.0),
    "heart":    (None, None, 0.30, 1.0, 0.45, 0.08),
    "crash":    (None, None, 0.16, 1.0, 0.40, 0.0),
}
PERC = {"hat", "ohat", "ride", "clap", "snare", "roll", "tom", "clank", "metal", "tick", "vox"}
STEREO_BANKS = {"hat", "hat_r", "ohat", "ride", "metal", "tick", "crash"}

_CONS = np.array([12, 19, 27, 31, 34], dtype=float)   # minor: oct, 5th, m3, 5th, m7
_DISS = np.array([13, 18, 23, 25, 30], dtype=float)   # b9, tritone, maj7 cluster
_DRONE_IV = np.concatenate([_CONS, _CONS, _DISS, _DISS])
_DRONE_SG = np.concatenate([np.full(5, -1.0), np.full(5, 1.0), np.full(5, -1.0), np.full(5, 1.0)])
_DRONE_PAN = np.tile(np.array([-0.6, 0.6, -0.3, 0.3, 0.0]), 4) * _DRONE_SG


def seed_for(visitor_id, user_seed=0):
    if not visitor_id:
        return int(user_seed) & 0x7FFFFFFF
    return (zlib.crc32(str(visitor_id).encode("utf-8")) ^ int(user_seed)) & 0x7FFFFFFF


def _wrap(semis):
    """Chord offsets into -5..+6 semitones, for smooth voice leading."""
    s = int(semis) % 12
    return s - 12 if s > 6 else s


# ------------------------------------------------------------ helper process
def _helper_init(parent_pid):
    """Runs in the helper process: yield the CPU to the render loop, and exit
    if the audio process that started us is gone (killed by the watchdog)."""
    try:
        os.nice(5)
    except (OSError, AttributeError):
        pass

    def watch():
        while True:
            time.sleep(2.0)
            if os.getppid() != parent_pid:
                os._exit(0)
    threading.Thread(target=watch, name="ij-helper-watch", daemon=True).start()


def _noop():
    return True


def build_section(g, key, ctx):
    """One sample-bank section ('k', 'h', 'c', 's' or 't'), as {name: [arrays]}.
    Module level so the helper process can run it; same result wherever it runs."""
    ent = {}
    for name, val in getattr(TechnoSynth, "_build_" + g)(key, ctx):
        if val is not None and not name[-1].isdigit():
            ent[name] = val
    return ent


def make_riser(seed, var, n, tension, sps2, salt):
    rng = np.random.default_rng([seed, var, salt])
    return V.riser(rng, n, tension=tension, sps=sps2)


def _fit_riser(sig, n):
    """A riser made for a slightly different length: keep its end on the drop.
    Longer -> drop the (near-silent) start; shorter -> start it later.
    Returns (signal, start offset)."""
    m = sig.shape[-1]
    if m <= n:
        return sig, n - m
    out = sig[:, m - n:].copy()
    e = min(n, 256)
    out[:, :e] *= np.linspace(0.0, 1.0, e, dtype=np.float32)
    return out, 0


class _Helper:
    """Slow sample generation (bank sections, risers) in one spawned process.

    Building a section of the sample bank takes 50-200 ms on x86 and two to
    three times that on a Pi 5; an 8 s riser ~75 ms. Inside render_block that
    empties the output buffer. A thread is not enough: it holds the GIL while
    it runs Python between numpy calls, and render_block's many small numpy
    calls queue up behind it. So a helper process makes them and the render
    loop keeps playing the samples it has until the new ones arrive. One job
    runs at a time; a newer request under the same name replaces a queued one.
    All calls are cheap (no waiting).
    """

    ORDER = ("riser", "shake", "bank:k", "bank:h", "bank:s", "bank:c", "bank:t")

    def __init__(self):
        import concurrent.futures as cf
        import multiprocessing as mp
        cur = mp.current_process()
        was_daemon = cur.daemon
        # The audio child is a daemon process, and multiprocessing refuses to
        # let a daemon start children. The helper watches its parent and exits
        # with it (see _helper_init), which is what the flag would guarantee.
        if was_daemon:
            cur.daemon = False
        try:
            self._ex = cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"),
                                              initializer=_helper_init, initargs=(os.getpid(),))
            self._running = ("warmup", None, self._ex.submit(_noop))
            self._running[2].result(timeout=60)     # the process really starts here
        finally:
            if was_daemon:
                cur.daemon = True
        self._queued = {}        # name -> (key, fn, args)
        self._done = {}          # name -> (key, result)
        self.broken = False

    def submit(self, name, key, fn, *args):
        self._queued[name] = (key, fn, args)
        self.poll()

    def poll(self):
        """Collect a finished job and start the next one."""
        if self.broken:
            return
        if self._running is not None:
            name, key, fut = self._running
            if not fut.done():
                return
            self._running = None
            try:
                res = fut.result()
            except Exception as e:          # helper died: the synth falls back
                print("[audio] helper process failed: %r" % (e,), file=sys.stderr)
                self.broken = True
                return
            if name != "warmup":
                self._done[name] = (key, res)
        for name in self.ORDER:
            if name in self._queued:
                key, fn, args = self._queued.pop(name)
                try:
                    self._running = (name, key, self._ex.submit(fn, *args))
                except Exception:
                    self.broken = True
                return

    def take(self, name):
        """The finished (key, result) for name, or None."""
        self.poll()
        return self._done.pop(name, None)

    def pending(self, name):
        """(key) requested or being made under this name, else None."""
        if name in self._queued:
            return self._queued[name][0]
        if self._running is not None and self._running[0] == name:
            return self._running[1]
        return None

    def forget(self):
        self._queued.clear()
        self._done.clear()

    def idle(self):
        self.poll()
        return self.broken or (not self._queued and self._running is None)

    def close(self):
        try:
            self._ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


class _ThreadHelper:
    """The same jobs on a background thread: the fallback when no helper
    process can be started (or it died). Worse for the GIL, better than
    building inside render_block."""

    ORDER = _Helper.ORDER

    def __init__(self):
        self._cv = threading.Condition()
        self._queued = {}
        self._running = None      # (name, key)
        self._done = {}
        self._closed = False
        self.broken = False
        threading.Thread(target=self._loop, name="ij-bank", daemon=True).start()

    def _loop(self):
        while True:
            with self._cv:
                while not self._queued and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                name = next(n for n in self.ORDER if n in self._queued)
                key, fn, args = self._queued.pop(name)
                self._running = (name, key)
            try:
                res = fn(*args)
            except Exception as e:           # never let a build kill the audio
                print("[audio] build failed: %r" % (e,), file=sys.stderr)
                res = None
            with self._cv:
                self._running = None
                if res is not None:
                    self._done[name] = (key, res)

    def submit(self, name, key, fn, *args):
        with self._cv:
            self._queued[name] = (key, fn, args)
            self._cv.notify()

    def poll(self):
        pass

    def take(self, name):
        with self._cv:
            return self._done.pop(name, None)

    def pending(self, name):
        with self._cv:
            if name in self._queued:
                return self._queued[name][0]
            if self._running is not None and self._running[0] == name:
                return self._running[1]
        return None

    def forget(self):
        with self._cv:
            self._queued.clear()
            self._done.clear()

    def idle(self):
        with self._cv:
            return not self._queued and self._running is None

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify()


class DNA:
    """Per-visitor musical fingerprint (the personal motif), fixed for the visit."""

    def __init__(self, seed):
        rng = np.random.default_rng([seed, 4242])
        self.root = 28 + int(rng.integers(0, 8))          # E1..B1
        self.stab_steps = sorted(int(s) for s in rng.choice(
            [2, 3, 6, 7, 10, 11, 14, 15], size=int(rng.integers(2, 4)), replace=False))
        self.clank_fixed = [[3, 11], [7, 15], [5, 13], [6, 14]][int(rng.integers(4))]
        self.odd_period = int(rng.choice([5, 7]))
        self.clank_ratios = rng.uniform(1.17, 3.9, 6)
        self.hat_acc = rng.uniform(0.3, 1.0, 16)
        self.click_mask = rng.random(16) < 0.5
        self.click_div = rng.choice([1, 2, 3, 4], 16)
        self.broken_kick = [[0, 3, 8, 11], [0, 6, 10], [0, 3, 7, 10, 14], [0, 5, 8, 13]][int(rng.integers(4))]
        self.pans = rng.uniform(-0.7, 0.7, 8)
        # v2: kit preference and the melodic motif (bass, tonal clanks)
        self.kit = int(rng.integers(len(KITS)))
        self.kit_follow_room = bool(rng.random() < 0.35)
        dens = rng.uniform(0.5, 0.75)
        self.motif_on = rng.random(16) < dens
        self.motif_on[0] = True
        self.motif_deg = rng.choice([0, 0, 0, 0, 2, 4, 4, 6, 1, 3, 5], 16)
        self.motif_oct = rng.choice([0, 0, 0, 1, 1, -1], 16)
        self.motif_acc = rng.random(16) < 0.32
        self.motif_slide = rng.random(16) < 0.22
        self.bass_wave = float(rng.uniform(0.0, 1.0))
        self.bass_pref = str(rng.choice(["acid", "roll", "none", "any"]))
        self.roll_oct = rng.random(4) < 0.3


class TechnoSynth:
    def __init__(self, block=1024, seed=0, volume=0.9, threaded=False, internal=2, helper=True):
        # .B is what render_block() returns (1024 frames, the public contract);
        # internally the synth renders `internal` x larger blocks and hands
        # them out in pieces, which halves numpy's per-call overhead.
        self.B = int(block)
        self.IB = self.B * max(1, int(internal))
        assert self.IB % 64 == 0
        self._pending = []
        self.R = 1 << 19                      # ~10.9 s scheduling ring
        self.M = self.R - 1
        self.user_seed = int(seed)
        self.volume = float(volume)
        self.ar = np.arange(self.IB)
        self.ramp = self.ar / float(self.IB)
        self.clock = SetClock(self.user_seed)
        self.arr = Arranger(self.user_seed)
        self._alloc()
        self.targets = dict(I=0.15, O=0.5, C=0.5, E=0.5, A=0.5, N=0.5, bpm=None)
        self.phase = "idle"
        self.in_phase = "idle"
        self.hook = "default"
        self.visitor = None
        self.last_state = None
        self.mg = 0.0          # master fade gain (wipe / start-up)
        self.mg_target = 1.0
        self.wiping = False
        self.wg = 1.0          # wipe dissolve gain (groove only; the drone stays)
        self.wipe_t = 0.0
        self.hinge = False
        self.hg = 1.0          # hinge gain (everything except the sub)
        self.slam_due = False
        self.jobs = []
        self.gen = 0               # bumped at every reset: late results for an older state are dropped
        self.helper = None
        self.risers = {}           # "riser"/"shake" -> [job key, signal, unused]
        self.rvar = 0
        self._reset_musical_state(snap=True, sync=True)
        # Live: sounds (bank sections, risers) are made by a helper process and
        # render_block keeps the samples it has until new ones arrive, so a slow
        # build never delays an audio block (see _Helper). Offline renders build
        # one sound per block inline instead (deterministic).
        self.threaded = bool(threaded)
        if self.threaded:
            self._start_helper(process=bool(helper))

    def _start_helper(self, process=True):
        old = self.helper
        self.helper = None
        if old is not None:
            old.close()
        if process:
            try:
                self.helper = _Helper()
            except Exception as e:
                print("[audio] no helper process (%r); building on a thread" % (e,), file=sys.stderr)
        if self.helper is None:
            self.helper = _ThreadHelper()
        self._queue_bank()
        self._order_risers()

    def close(self):
        """Stop the helper (the audio worker calls this when it stops)."""
        if self.helper is not None:
            self.helper.close()
            self.helper = None

    # ------------------------------------------------------------------ setup
    def _alloc(self):
        R, B = self.R, self.IB
        self.dry = np.zeros((2, R), np.float32)
        self.fx = np.zeros((2, R), np.float32)
        self.syn = np.zeros((2, R), np.float32)     # stabs: live tilt-filtered bus
        self.vsend = np.zeros(R, np.float32)
        self.dsend = np.zeros(R, np.float32)
        self.duck = np.zeros(R, np.float32)
        self.room = Room(B)
        self.delay = PingPong(B)
        self.sreso = Reso(2)                        # stab bus filter (tilt x)
        self.DS = 4                                 # the drone runs at 12 kHz, then is upsampled
        self.dreso = Reso(2, 64, SR / self.DS)      # drone filter
        self.dlast = np.zeros((2, 1))
        nd = self.IB // self.DS
        self.d_ar = np.arange(nd)
        u = (np.arange(self.IB) + 1) / float(self.DS)       # position in low-rate samples
        self.d_i0 = np.floor(u).astype(int) - 1             # index into [last, x...] minus one
        self.d_w = u - np.floor(u)
        self.treso = Reso(2)                        # tension noise
        self.hp = Reso(2)                           # master sweep high-pass
        self.mlp = Reso(2)                          # master resonant low-pass (tilt)
        self.sat = Saturator()
        self.dc = OnePole(2)
        self.dc2 = OnePole(2)
        self.dc3 = OnePole(2)
        self.glue = Glue(thr_db=-9.0, ratio=2.0, knee=6.0)
        self.lim = Limiter(-1.5)
        self.bass = BassVoice(B)
        self.H = 16384
        self.hist = np.zeros((2, self.H))
        self.drone_ph = np.zeros(len(_DRONE_IV))
        self.sub_ph = 0.0
        self.lfo = 0.0
        self.lfo2 = 0.0
        self.pos = 0
        self.next_step_at = 0.0
        self.step = 0
        self.gbar = 0
        self.noise_rng = np.random.default_rng(12345)
        self.hp_on = False

    def _reset_musical_state(self, snap=False, sync=False, keep_tails=False):
        for a in (self.dry, self.fx, self.syn, self.vsend, self.dsend, self.duck, self.hist):
            a[:] = 0.0
        if not keep_tails:          # after a wipe the room, delay, drone and master keep running
            for f in (self.room, self.delay, self.sreso, self.dreso, self.treso, self.hp, self.mlp,
                      self.sat, self.dc, self.dc2, self.dc3, self.glue):
                f.reset()
        self.bass.reset()
        self.stutters = []
        self.pattern = [[] for _ in range(16)]
        self.vbar = 0
        self.phase_bars = 0
        self.bar_phase = self.phase
        self.riser_due = False
        if not hasattr(self, "bank"):
            self.bank = {}
            self.bank_keys = {}
        self.tcache = {}
        self.hw = {h: (1.0 if h == "default" else 0.0) for h in HOOKS}
        self._set_visitor(self.visitor, force=True)
        if snap or not hasattr(self, "p"):
            self.p = dict(PHASE_TABLE[self.phase])
            for k in ("I", "O", "C", "E", "A", "N"):
                self.p[k] = self.targets[k]
            self.p["bpm"] = self._bpm_target()
            self.p["level"] = 1.0
        if not keep_tails:
            self.drone_g = 0.0
            self.sub_g = 0.0
        self.fx_g = 0.0
        self.tens_g = 0.0
        self.sens = dict(x=0.0, y=0.0, e=0.0, f=0.0)   # smoothed tilt / motion / flip
        self.sens_t = dict(x=0.0, y=0.0, e=0.0, f=0.0)
        self.flip_prev = 0.0
        self.flip_evt = False
        self.shake_cool = 0
        self.layers = {}
        self.plan = None
        self.bar_t0 = float(self.pos)
        self.bar_len = 16.0 * self.sps()
        self.throw_until = -1
        self.slam_flag = False
        self.bass_style = None
        self.mode = self.clock.mode
        self.key_root = self.clock.root
        if not keep_tails:
            self.root_s = float(self.key_root)
        self.chord = 0
        self.kit = KITS[self.clock.kit]
        if not keep_tails:
            self.mlp.fc_last = None
        self.arr.reset(self.seed)
        self.gen = getattr(self, "gen", 0) + 1
        if getattr(self, "helper", None) is not None:
            self.helper.forget()
        self._queue_bank(sync=sync)
        self._order_risers()

    def _room_seed(self):
        return (seed_for(None, self.user_seed) * 31 + 7919 * self.clock.epoch) & 0x7FFFFFFF

    def _set_visitor(self, vid, force=False):
        vid = vid or None
        if vid == self.visitor and not force and hasattr(self, "dna"):
            return
        self.visitor = vid
        self.seed = seed_for(vid, self.user_seed) if vid else self._room_seed()
        self.dna = DNA(self.seed)
        self.arr.new_identity(self.seed)
        self.vbar = 0

    # ------------------------------------------------------------ state input
    def set_state(self, state):
        if not isinstance(state, dict):
            return
        self.last_state = state
        ph = state.get("phase")
        if ph in PHASES:
            if ph == "wipe" and self.in_phase != "wipe":
                self.wipe()
            self.in_phase = ph
            if ph != "wipe" and not self.wiping:
                self.phase = ph
        if self.wiping or self.in_phase == "wipe":
            return          # during/after a wipe, forget the visitor until a new phase
        if "visitor_id" in state:
            self._set_visitor(state.get("visitor_id"))
        self._apply_values(state)

    def _apply_values(self, state):
        t = self.targets
        try:
            if state.get("intensity") is not None:
                t["I"] = clamp(float(state["intensity"]))
        except (TypeError, ValueError):
            pass
        oc = state.get("ocean")
        if isinstance(oc, dict):
            for k in OCEAN:
                try:
                    if oc.get(k) is not None:
                        t[k] = clamp(float(oc[k]))
                except (TypeError, ValueError):
                    pass
        try:
            bpm = state.get("tempo")
            t["bpm"] = clamp(float(bpm), BPM_MIN, BPM_MAX) if bpm is not None else None
        except (TypeError, ValueError):
            t["bpm"] = None
        self._apply_sensor(state)
        hg = state.get("hinge")
        if hg is not None:
            on = bool(hg) and hg not in ("false", "0", 0)
            if self.hinge and not on:
                self.slam_due = True
            self.hinge = on
        hk = state.get("hook")
        if hk is not None:
            hk = str(hk).strip().lower()
            self.hook = hk if hk in HOOKS else "default"

    def set_sensor(self, data):
        """Raw phone sensor dict (tilt, tilt_energy/shake, accel). Applied immediately."""
        if isinstance(data, dict) and not self.wiping:
            self._apply_sensor(data)

    def _apply_sensor(self, d):
        t = self.sens_t
        steer = d.get("steer")
        if isinstance(steer, dict):                       # contract 1.3: preferred
            try:
                for k in ("x", "y"):
                    if steer.get(k) is not None:
                        t[k] = clamp(float(steer[k]), -1.0, 1.0)
                if steer.get("flip") is not None:
                    t["f"] = 1.0 if steer.get("flip") else 0.0
                if steer.get("shake") is not None:
                    t["e"] = clamp(float(steer["shake"]))
            except (TypeError, ValueError):
                pass
            return
        tilt = d.get("tilt")
        try:
            if isinstance(tilt, dict):
                if "x" in tilt or "y" in tilt:          # primary: normalised -1..1
                    if tilt.get("x") is not None:
                        t["x"] = clamp(float(tilt["x"]), -1.0, 1.0)
                    if tilt.get("y") is not None:
                        t["y"] = clamp(float(tilt["y"]), -1.0, 1.0)
                else:                                     # fallback: degrees
                    if tilt.get("gamma") is not None:
                        t["x"] = clamp(float(tilt["gamma"]) / 90.0, -1.0, 1.0)
                    if tilt.get("beta") is not None:
                        t["y"] = clamp(float(tilt["beta"]) / 90.0, -1.0, 1.0)
            e = d.get("tilt_energy", d.get("shake"))
            if e is not None:
                t["e"] = clamp(float(e))
        except (TypeError, ValueError):
            pass

    WIPE_FADE_S = 9.0      # the groove dissolves over this long ...
    WIPE_S = 10.5          # ... and the visitor is forgotten after this long

    def wipe(self):
        """Dissolve over ~10 s: the groove fades into its own reverb while the
        drone carries on; then forget the visitor and return to idle."""
        if not self.wiping:
            self.wiping = True
            self.wipe_t = 0.0
            self.hinge = False
            self.slam_due = False

    def _finish_wipe(self):
        self.wiping = False
        self.visitor = None
        self.targets.update(I=0.15, O=0.5, C=0.5, E=0.5, A=0.5, N=0.5, bpm=None)
        self.hook = "default"
        self.phase = "idle"
        self._reset_musical_state(snap=False, keep_tails=True)
        self.wg = 1.0
        st = self.last_state
        if isinstance(st, dict) and st.get("phase") not in (None, "wipe"):
            self.set_state(st)

    # --------------------------------------------------------------- helpers
    def _visiting(self):
        return self.visitor is not None and self.phase in ("approach", "profiling", "hook", "release")

    def _bpm_target(self):
        if not self._visiting():
            b = self.clock.bpm
        else:
            b = self.targets.get("bpm")
            if b is None:
                b = 126.0 + 14.0 * self.targets["E"]
        hs = PHASE_TABLE[self.phase]["hs"]
        b += hs * HOOKS[self.hook]["bpm"]
        return clamp(b, BPM_MIN, BPM_MAX)

    def sps(self):
        return SR * 60.0 / self.p["bpm"] / 4.0

    def _hookmod(self, key):
        m = 0.0
        for h, w in self.hw.items():
            if w > 1e-4:
                m += w * HOOKS[h][key]
        hs = self.p["hs"]
        if key in _HOOK_EXTRA:
            return hs * m
        return 1.0 + hs * (m - 1.0)

    def _vgain(self, key, layer):
        lay = self.layers.get(layer, 1.0) if layer else 1.0
        if key is None:
            return lay
        if key in ("vox", "breath", "rev"):
            return self._hookmod(key) * lay
        return self.p[key] * self._hookmod(key) * lay

    def _smooth(self):
        p = self.p
        bar_s = 240.0 / p["bpm"]
        k = self.IB / float(SR)
        a1 = 1.0 - np.exp(-k / (bar_s * 0.8))
        a2 = 1.0 - np.exp(-k / (bar_s * 1.6))
        if True:
            tgt = PHASE_TABLE[self.phase]
            for key in _P:
                p[key] += (tgt[key] - p[key]) * a1
            p["I"] += (self.targets["I"] - p["I"]) * a1
            for key in OCEAN:
                p[key] += (self.targets[key] - p[key]) * a2
            p["bpm"] += (self._bpm_target() - p["bpm"]) * a2
            for h in self.hw:
                self.hw[h] += ((1.0 if h == self.hook else 0.0) - self.hw[h]) * a1
            p["level"] += (self._hookmod("level") - p["level"]) * a1
        a_s = 1.0 - np.exp(-k / 0.05)               # ~50 ms slew for the phone
        for key in ("x", "y", "e", "f"):
            self.sens[key] += (self.sens_t[key] - self.sens[key]) * a_s
        if self.sens_t["f"] > 0.5 and self.flip_prev <= 0.5:
            self.flip_evt = True
        self.flip_prev = self.sens_t["f"]
        rt = self.key_root + _wrap(self.chord)
        self.root_s += (rt - self.root_s) * (1.0 - np.exp(-k / (bar_s * 0.7)))
        if self.wiping:
            self.wipe_t += k
            self.wg = max(0.0, 1.0 - self.wipe_t / self.WIPE_FADE_S) ** 1.6
        # hinge: everything but the sub drops out in ~120 ms
        self.hg += ((0.0 if self.hinge else 1.0) - self.hg) * (1.0 - np.exp(-k / 0.12))
        # master fade (start-up 3 s, stop 2 s)
        step = k / (2.0 if self.mg_target < self.mg else 3.0)
        self.mg = max(self.mg - step, self.mg_target) if self.mg_target < self.mg \
            else min(self.mg + step, self.mg_target)

    # ------------------------------------------------------------ sample bank
    def _desired_keys(self):
        p, s = self.p, self.seed
        I, O, E, A, N = p["I"], p["O"], p["E"], p["A"], p["N"]
        kit = self.kit
        root = int(self.key_root)
        drive = round((0.8 + 0.6 * I + 0.4 * self.clock.grit) * 2) / 2.0
        bq = int(p["bpm"] // 4)
        return {
            "k": (s, kit["kick"], drive, root, bq),
            "h": (s, kit["name"], round(E * 3), round(I * 2)),
            "c": (s, round(O * 3), round(A * 3), root),
            "s": (s, round(A * 3), round(N * 3), round(I * 2), root, self.mode),
            "t": (s, root),
        }

    def _queue_bank(self, sync=False):
        want = self._desired_keys()
        ctx = dict(dna=self.dna, mode=self.mode, grit=self.clock.grit)
        h = getattr(self, "helper", None)
        if h is not None and not sync:
            if h.broken:                     # the helper process died: carry on with a thread
                self._start_helper(process=False)
                return
            for g, key in want.items():
                job = (self.gen, key)
                if self.bank_keys.get(g) == key or h.pending("bank:" + g) == job:
                    continue
                h.submit("bank:" + g, job, build_section, g, key, ctx)
            return
        pending = {j[0]: j[1] for j in self.jobs}
        for g, key in want.items():
            if self.bank_keys.get(g) == key or pending.get(g) == key:
                continue
            self.jobs = [j for j in self.jobs if j[0] != g]
            self.jobs.append([g, key, getattr(self, "_build_" + g)(key, ctx), {}])
        if sync:
            while self.jobs:
                self._run_job(1 << 30)

    # Risers are long noise sweeps (8.5 s: ~75 ms to make on x86). Live, one of
    # each kind is kept in stock, made ahead by the helper for the current
    # seed / tension / tempo; when one is played the next one is ordered.
    def _riser_spec(self, name):
        bpm = int(round(self.p["bpm"]))
        sps = SR * 60.0 / bpm / 4.0
        if name == "riser":
            tq = round(self.p["N"] * 8) / 8.0
            return (self.seed, tq, bpm), (int(min(8.5 * SR, 64 * sps)), tq, sps / 2.0, 9)
        return (self.seed, bpm), (int(16 * sps), 0.6, sps / 2.0, 11)

    def _order_risers(self):
        h = getattr(self, "helper", None)
        if h is None or not hasattr(self, "risers"):
            return
        for name in ("riser", "shake"):
            want, (n, tension, sps2, salt) = self._riser_spec(name)
            cur = self.risers.get(name)
            if cur is not None and cur[2] and cur[0][0] == want:
                continue                     # a fresh one for these settings is in stock
            pend = h.pending(name)
            if pend is not None and pend[0] == want:
                continue
            self.rvar = (self.rvar + 1) & 0xFFFFFF
            h.submit(name, (want, self.rvar), make_riser, self.seed, self.rvar, n, tension, sps2, salt)

    def _stock_riser(self, name, n):
        """A riser from stock fitted to n samples, as (signal, offset), or None."""
        cur = self.risers.get(name)
        if cur is None:
            self._order_risers()
            return None
        cur[2] = False
        self._order_risers()
        return _fit_riser(cur[1], n)

    def _run_job(self, budget=1):
        """Live: collect what the helper has made. Offline: advance the inline
        builder by `budget` sounds (one per audio block)."""
        h = getattr(self, "helper", None)
        if h is not None:
            for g in "khsct":
                got = h.take("bank:" + g)
                if got is not None and got[0][0] == self.gen:
                    self.bank.update(got[1])
                    self.bank_keys[g] = got[0][1]
                    if g == "s":
                        self.tcache = {}
            for name in ("riser", "shake"):
                got = h.take(name)
                if got is not None:
                    self.risers[name] = [got[0], got[1], True]
            return
        while self.jobs and budget > 0:
            job = self.jobs[0]
            try:
                name, val = next(job[2])
                if val is not None and not name[-1].isdigit():
                    job[3][name] = val
                budget -= 1
            except StopIteration:
                self.bank.update(job[3])
                self.bank_keys[job[0]] = job[1]
                if job[0] == "s":
                    self.tcache = {}
                self.jobs.pop(0)

    @staticmethod
    def _build_k(key, ctx):
        s, fam, drive, root, bq = key
        rng = np.random.default_rng([s, 1, int(drive * 4), root, bq, sum(map(ord, fam))])
        bq = bq * 2 + 1
        fe = float(midi_hz(root))
        # equal loudness across families and keys (measured, K-weighted)
        trim = 10.0 ** ((V.KICK_TRIM_DB.get(fam, 0.0) - 0.25 * (root - 31)) / 20.0)
        k0 = V.kick(rng, fam, fe, drive) * trim
        yield "kick0", k0
        k1 = V.kick(rng, fam, fe * 1.06, drive, decay=0.55, length=0.6) * trim
        yield "kick1", k1
        k2 = V.kick(rng, fam, fe * 0.94, drive * 1.4, decay=1.5, length=1.3, tail=1.4) * trim * 0.85
        yield "kick", [k0, k1, k2]
        yield "kick_far", [V.kick(rng, "boom", fe, 0.7, decay=1.2, click=0.0, lowpass=170)]
        beat = int(SR * 60.0 / (bq * 2 + 1))
        yield "rumble", [V.rumble(rng, k0 / trim, beat, drive=1.4 + drive, cutoff=95.0 + 25.0 * ctx["grit"])]

    @staticmethod
    def _build_h(key, ctx):
        s, kname, Eq, Iq = key
        kit = next(k for k in KITS if k["name"] == kname)
        rng = np.random.default_rng([s, 2, Eq, Iq, sum(map(ord, kname))])
        b = 0.6 * Eq / 3.0 + 0.4 * kit["bright"]
        dr = 1.0 + 2.0 * Iq / 2.0
        mt = kit["metal"]
        hats = []
        for dec, m in ((0.03, mt * 0.7), (0.05, mt), (0.022, min(1.0, mt + 0.3))):
            hats.append(V.stereo(V.hat(rng, dec, b, m, dr), rng))
            yield "hat%d" % len(hats), None
        yield "hat", hats
        yield "hat_r", [h[:, ::-1].copy() for h in hats]
        yield "ohat", [V.stereo(V.hat(rng, 0.2, b, mt, dr), rng, 9.0)]
        yield "ride", [V.stereo(V.ride(rng, 0.45 + 0.2 * rng.random(), b), rng, 11.0)]
        yield "clap", [V.clap(rng, 0.12, 1300 + 600 * Eq / 3.0), V.clap(rng, 0.2, 1100 + 500 * Eq / 3.0)]
        yield "snare", [V.snare(rng, kit["snare"], t) for t in (1.0, 1.12, 1.26)]
        yield "roll", [V.snare(rng, "noise", t, 0.18) for t in (1.0, 1.12, 1.26)]

    @staticmethod
    def _build_c(key, ctx):
        s, Oq, Aq, root = key
        rng = np.random.default_rng([s, 3, Oq, Aq, root])
        d = ctx["dna"]
        Oq, Aq = Oq / 3.0, Aq / 3.0
        root_hz = float(midi_hz(root + 36))
        scale = MODES.get(ctx["mode"], MODES["aeolian"]) + (12, 15)
        clanks = []
        for i in range(6):
            if rng.random() < Aq:   # tonal, tuned to the key
                fc = root_hz * 2.0 ** (scale[int(rng.integers(len(scale)))] / 12.0)
                ratio = float(rng.choice([1.0, 2.0, 3.0, 1.5]))
            else:                   # atonal metal
                fc = rng.uniform(180.0, 1800.0)
                ratio = float(d.clank_ratios[i])
            ratio += Oq * rng.uniform(-0.4, 0.6)
            clanks.append(V.clank(rng, fc, max(0.3, ratio), index=2 + 6 * Oq * rng.random() + 4 * (1 - Aq),
                                  decay=0.12 + 0.3 * rng.random(), ring=(1 - Aq) * 0.7))
            yield "clank%d" % i, None
        yield "clank", clanks
        yield "clank_r", [c[::-1].copy() for c in clanks]
        mets = []
        for _ in range(3):
            mets.append(V.stereo(V.metal(rng, rng.uniform(150, 700), harsh=1 - Aq), rng, 12.0, 0.7))
            yield "metal0", None
        yield "metal", mets
        yield "swell", [V.swell(rng), V.swell(rng, 2.4)]

    @staticmethod
    def _build_s(key, ctx):
        s, Aq, Nq, Iq, root, mode = key
        rng = np.random.default_rng([s, 4, Aq, Nq, Iq, root])
        Aq, Nq, Iq = Aq / 3.0, Nq / 3.0, Iq / 2.0
        sc = MODES.get(mode, MODES["aeolian"])
        third, fifth, sev = sc[2], sc[4], sc[6]
        if Aq > 0.62:
            voicings = [[0, third, fifth, sev], [0, third, fifth, 14], [-2, third, fifth, sev]]
        elif Aq < 0.38:
            voicings = [[0, 1, 6, 11], [0, 1, 2, 7], [0, 6, 11, 13]]
        else:
            voicings = [[0, third, fifth, 13], [0, third, fifth, sev, 13], [-2, third, 6, sev]]
        rhz = float(midi_hz(root + 24))
        st = []
        for v in voicings:
            st.append(V.stab(rng, rhz, v, 6 + 35 * Nq, 500 + 2500 * Iq, 0.18 + 0.25 * rng.random(),
                             reso=0.3 + 0.5 * rng.random()))
            yield "stab0", None
        yield "stab", st
        yield "stab_r", [x[::-1].copy() for x in st]
        toms = [V.tom(rng, float(midi_hz(root + 24 + iv))) for iv in (0, sc[2], sc[4], 12)]
        yield "tom", toms

    @staticmethod
    def _build_t(key, ctx):
        s, root = key
        rng = np.random.default_rng([s, 5])
        ticks = []
        for _ in range(8):
            ticks.append(V.stereo(V.tick(rng, rng.uniform(1500, 9000), rng.uniform(0.003, 0.012),
                                         rng.random() < 0.4), rng, 3.0, 0.2))
        yield "tick", ticks
        yield "impact", [V.impact(rng)]
        yield "crash", [V.stereo(V.crash(rng), rng, 15.0, 0.8)]
        yield "vox", [V.vox(rng, rng.uniform(0.06, 0.16)) for _ in range(8)]
        yield "breath", [V.breath(rng, 1.3, 800), V.breath(rng, 1.6, 1300)]

    # ----------------------------------------------------- identity decisions
    def _choose_mode(self):
        p = self.p
        A, N = p["A"], p["N"]
        if A < 0.2:
            return "locrian"
        if A < 0.38 and N > 0.5:
            return "phrygian"
        if N > 0.75 and A > 0.4:
            return "harmonic"
        if A > 0.72:
            return "dorian"
        return "aeolian"

    def _choose_bass(self):
        p, d = self.p, self.dna
        O, C, E, N = p["O"], p["C"], p["E"], p["N"]
        acid = 0.6 * O + 0.4 * (1.0 - C) - 0.35 + 0.5 * self._hookmod("acid") + (0.15 if d.bass_pref == "acid" else 0.0)
        roll = 0.75 * E + 0.2 * N - 0.3 + 0.5 * self._hookmod("roll") + (0.15 if d.bass_pref == "roll" else 0.0)
        if d.bass_pref == "none":
            acid -= 0.2
            roll -= 0.2
        if max(acid, roll) < 0.32:
            return None
        return "acid" if acid > roll else "roll"

    # -------------------------------------------------------------- patterns
    def _bar_start(self):
        if self.phase != self.bar_phase:
            self.phase_bars = 0
            self.bar_phase = self.phase
        visiting = self._visiting()
        self.clock.advance(idle=not visiting)
        if not visiting and self.visitor is None:
            rs = self._room_seed()
            if rs != self.seed:                 # the room's motif moves on with the kit
                self.seed = rs
                self.dna = DNA(rs)
                self.arr.new_identity(rs)
        p, d = self.p, self.dna
        I, O, C, E, A, N = (p[k] for k in ("I", "O", "C", "E", "A", "N"))
        oc = {k: p[k] for k in OCEAN}
        slam = self.slam_flag
        self.slam_flag = False
        plan = self.arr.plan(self.phase, I, oc, self.hook, self.clock,
                             self.mode, self.phase_bars, {h: w * p["hs"] for h, w in self.hw.items()},
                             slam=slam)
        self.plan = plan
        if plan.first:
            if visiting:
                self.key_root = d.root
                self.mode = self._choose_mode()
                self.kit = KITS[self.clock.kit if d.kit_follow_room else d.kit]
                self.bass_style = self._choose_bass()
            else:
                if plan.section in ("ambient", "dub", "pulse", "silence", "outro"):
                    self.clock.apply_key()
                self.key_root = self.clock.root
                self.mode = self.clock.mode
                self.kit = KITS[self.clock.kit]
                self.bass_style = None
        self.chord = plan.chord
        self.layers = plan.layers
        self.bar_t0 = float(self.next_step_at)
        self.bar_len = 16.0 * self.sps()
        self._queue_bank()
        self._order_risers()

        D = Dice(self.seed, plan.groove, plan.bis % plan.loop)
        G = Dice(self.seed, plan.groove)
        hum = np.random.default_rng([self.seed, self.vbar % 65536, 77])
        hm = self._hookmod
        L = plan.layers
        pat = [[] for _ in range(16)]
        phase = self.phase
        kit = self.kit

        def hit(s, inst, var=0, gain=1.0, pan=0.0, off=0.0, x=None):
            pat[int(s) % 16].append((inst, var, gain, pan, off, x))

        swing = (1.0 - C) ** 1.5 * 0.22          # low C -> swing
        jit = (1.0 - C) * 0.05

        def off_for(s):
            o = swing if s % 2 == 1 else 0.0
            return o + hum.uniform(0.0, jit)

        rev, offg, broken, heavy = hm("rev"), hm("offgrid"), hm("broken"), hm("heavy")
        rev = max(rev, self.sens["f"])                    # phone upside down -> reversed
        voxa, brth = hm("vox"), hm("breath")
        mirror_far = self.hw.get("mirror", 0) * p["hs"] > 0.5
        kick_from = plan.kick_from
        if self.flip_evt:                                  # flipping the phone drops the kick for a bar
            self.flip_evt = False
            kick_from = 0
            hit(0, "swell", 0, 1.0, 0.0, 16.0 - len(self.bank["swell"][0]) / self.sps())

        # --- kick
        far = L.get("far", 0.0)
        if far > 0.05:
            if plan.section == "pulse":
                steps = (0, 4, 8, 12)
            elif plan.section == "afterglow":
                steps = (0, 3) if plan.bis % 2 == 0 else (0, 3, 8, 11)      # a slowing heartbeat
            else:
                steps = (0, 10) if G.u("fk", 1)[0] < 0.5 else (0,)
            for s in steps:
                hit(s, "kick_far", 0, 0.9 if s % 8 == 0 else 0.7)
        elif phase == "idle" and plan.section == "ambient" and I > 0.08:
            if self.vbar % 4 == 0 and G.u("amb", 1)[0] < 0.6:
                hit(0, "kick_far", 0, 0.6)
        voidw = self.hw.get("void", 0.0) * p["hs"]
        if voidw > 0.4 and self.vbar % 2 == 0 and plan.section not in ("silence",):
            hit(0, "heart", 0, voidw)                      # void: a slow, distant pulse
            hit(3, "heart", 0, 0.6 * voidw)
        if L.get("kick", 0.0) > 0.05:
            steps = (0, 8) if plan.half_kick else (0, 4, 8, 12)
            if G.u("kbrk", 1)[0] < broken * 0.8:
                steps = d.broken_kick
            elif O > 0.7 and G.u("kvar", 1)[0] < 0.25 * O:
                steps = (0, 4, 8, 11, 14)
            hv = G.u("heavy")
            for s in steps:
                if s >= kick_from:
                    continue
                if mirror_far:
                    hit(s, "kick_far", 0, 0.6)
                    continue
                v = 2 if (hv[s] < heavy or (plan.drop and s == 0)) else 0
                hit(s, "kick", v, 1.0)
                if s % 4 == 0:
                    hit(s, "rumble", 0, 1.0)
            if D.u("kgh", 1)[0] < (1 - C) * 0.4 * I:
                s = int(G.pick("kghs", (7, 14, 15)))
                if s < kick_from:
                    hit(s, "kick", 1, 0.45, 0, off_for(1))

        # --- hats (E: more of them; C: tight vs swung/ghosted; inverted: off-grid/reversed)
        if p["hat"] * hm("hat") * L.get("hat", 0) > 0.03:
            style = plan.hat_style if plan.hat_style is not None else int(G.pick("hst", (0, 0, 1, 2, 3)))
            prob16 = clamp(E * 1.1 * I - 0.1) * (0.5 if style == 3 else 1.0)
            u16, uo, uv, ug = D.u("hat16"), D.u("offg"), D.u("offv"), D.u("hvar")
            for s in range(16):
                o = off_for(s) + ((0.15 + 0.35 * uv[s]) if uo[s] < offg else 0.0)
                q = s % 4
                core = q == 2 or (style == 1 and q == 3) or (style == 2 and q != 0)
                if style == 3:
                    core = s in (2, 10)
                inst = "hat_r" if (rev > 0.3 and uo[s] < rev * 0.5) else "hat"
                if core:
                    hit(s, inst, int(ug[s] * 2), 0.9 * (0.6 + 0.4 * d.hat_acc[s]), 0.0, o)
                elif u16[s] < prob16:
                    hit(s, inst, int(ug[s] * 3), 0.3 + 0.35 * d.hat_acc[s],
                        (uv[s] - 0.5) * 0.6 * (0.3 + O), o)
                elif hum.random() < (1 - C) * 0.25:
                    hit(s, inst, 1, 0.15, hum.uniform(-0.5, 0.5), o)
            if G.u("roll", 1)[0] < N * 0.4 + E * 0.15:      # ratchet roll
                s = 12 + int(G.u("rolls", 1)[0] * 4)
                k = int(G.pick("rollk", (2, 3, 4)))
                for j in range(k):
                    hit(s, "hat", 2, 0.25 + 0.4 * (1 - j / k), 0.0, j / float(k))
        if E > 0.4 and p["ohat"] * L.get("ohat", 0) > 0.03:
            uo = D.u("ohat")
            for s in ((2, 6, 10, 14) if E > 0.75 else (2, 10)):
                if uo[s] < 0.85:
                    hit(s, "ohat", 0, 0.5 + 0.5 * E, 0.0, off_for(s))
        if p["ride"] * L.get("ride", 0) * kit["ride"] > 0.05 and E > 0.3:
            for s in ((2, 6, 10, 14) if E > 0.55 else (2, 10)):
                hit(s, "ride", 0, 0.6 + 0.4 * E, 0.25, off_for(s))
            if E > 0.8:
                for s in (0, 4, 8, 12):
                    hit(s, "ride", 0, 0.25, 0.25)
        # --- backbeat: claps or snares (kit), flams for low C
        cl, sn = p["clap"] * L.get("clap", 0), p["snare"] * L.get("snare", 0)
        if max(cl, sn) > 0.03:
            use_clap = G.u("cs", 1)[0] < kit["clap"]
            inst = "clap" if use_clap else "snare"
            if E > 0.35 or plan.section == "build":
                for s in (4, 12):
                    hit(s, inst, 0, 0.4 + 0.6 * E)
                    if C < 0.4:
                        hit(s, inst, 1, 0.35, 0.2, 0.06 + 0.1 * (0.4 - C))
            elif self.vbar % 2 == 1:
                hit(12, inst, 1, 0.5)
            if sn > 0.03 and use_clap and G.u("snl", 1)[0] < 0.4:       # snare layer on 12
                hit(12, "snare", 0, 0.5)
        # --- clank (O: 3-over-4 / odd polyrhythm; C: regular vs dropouts)
        if p["clank"] * L.get("clank", 0) > 0.03:
            if O < 0.45:
                cs = d.clank_fixed
            else:
                period = 3 if O < 0.8 else d.odd_period
                cs = [s for s in range(16) if (self.vbar * 16 + s) % period == 0]
            u, uv, ur = D.u("clk"), D.u("clkv"), D.u("clkr")
            for i, s in enumerate(cs):
                if u[s] < 0.6 + 0.4 * C:
                    var = int(uv[s] * 6) if uv[s] < 0.3 + 0.7 * O else i % 2
                    inst = "clank_r" if ur[s] < rev * 0.6 else "clank"
                    hit(s, inst, var, (0.55 + 0.45 * O) * (0.7 + 0.3 * u[s]), d.pans[i % 8], off_for(s))
        # --- harsh metal (low A)
        if p["metal"] * L.get("metal", 0) > 0.03:
            pm = (1.0 - A) * 2.2 * (0.3 + I) / 16.0
            u, uv = D.u("met"), D.u("metv")
            for s in range(16):
                if u[s] < pm:
                    hit(s, "metal", int(uv[s] * 3), (1.0 - A), (uv[s] - 0.5) * 1.6)
        # --- data ticks
        if p["click"] * L.get("click", 0) > 0.03:
            dens = 0.25 + 0.5 * I + 0.2 * N
            u, uk, uv = D.u("tck"), D.u("tckk"), D.u("tckv", 64)
            for s in range(16):
                if C > 0.6:
                    play, k = bool(d.click_mask[s]), int(d.click_div[s])
                else:
                    play = u[s] < dens
                    k = (1, 1, 2, 3, 4, 6)[min(5, int(uk[s] * (5 + 2 * N)))]
                if play:
                    for j in range(k):
                        r = uv[(s * 4 + j) % 64]
                        hit(s, "tick", int(r * 8), 0.3 + 0.5 * r, (r - 0.5) * 1.8, j / float(k))
        # --- stabs (A: chord vs cluster, tuned to the key; follow the chords)
        semis = _wrap(plan.chord)
        if p["stab"] * L.get("stab", 0) > 0.03:
            sst = list(d.stab_steps)
            if phase == "release" or plan.section in ("break", "outro"):
                sst = sst[:1] if self.vbar % 2 == 0 else sst[1:2]
            if plan.section == "dub":
                sst = sst[:1] + ([sst[-1]] if G.u("dub2", 1)[0] < 0.5 else [])
            if G.u("stv", 1)[0] < O * 0.5 and sst:
                i = int(G.u("sti", 1)[0] * len(sst))
                sst[i] = (sst[i] + (1 if G.u("std", 1)[0] < 0.5 else -1)) % 16
            ur = D.u("str")
            for s in sst:
                inst = "stab_r" if ur[s] < rev * 0.5 else "stab"
                hit(s, inst, (self.vbar // 2) % 3, 1.0, (ur[s] - 0.5) * 0.8, off_for(s), semis)
        # --- bassline (only some profiles): acid motif or rolling offbeats
        bl = p["bass"] * hm("bass") * L.get("bass", 0)
        if self.bass_style and bl > 0.03:
            sc = MODES.get(self.mode, MODES["aeolian"])
            base = self.key_root + 12 + semis
            if self.bass_style == "acid":
                mut = D.u("bmut")
                for s in range(16):
                    on = bool(d.motif_on[s]) != bool(mut[s] < O * 0.12)
                    if not on:
                        continue
                    deg = int(d.motif_deg[s])
                    if mut[s] > 1.0 - O * 0.1:
                        deg = (deg + 2) % 7
                    note = base + sc[deg % 7] + 12 * int(d.motif_oct[s])
                    nxt_slide = bool(d.motif_slide[(s + 1) % 16]) and bool(d.motif_on[(s + 1) % 16])
                    hit(s, "bass", 0, 1.0, 0.0, off_for(s) * 0.5,
                        (note, 1.0 if d.motif_acc[s] else 0.0, bool(d.motif_slide[s]), 1.05 if nxt_slide else 0.55))
            else:
                for b in range(4):
                    if 4 * b >= kick_from and plan.section != "break":
                        continue
                    for j in (1, 2, 3):
                        s = 4 * b + j
                        note = base + (12 if (j == 3 and d.roll_oct[b]) else 0)
                        if j == 3 and G.u("r5", 4)[b] < 0.2 * O:
                            note = base + sc[4]
                        hit(s, "bass", 0, 0.8 + 0.2 * (j == 2), 0.0, off_for(s) * 0.3,
                            (note, 1.0 if j == 2 else 0.0, False, 0.6))
        # --- hook extras
        if voxa > 0.05 and L.get("vox", 0) > 0.05:     # scrawl: chopped spoken fragments
            u = D.u("vox", 32)
            n = int(3.0 * voxa * u[0] * 2.0 + 0.5)
            for i in range(n):
                s = int(u[1 + i] * 16)
                var = int(u[10 + i] * 8)
                k = (1, 1, 2, 3, 4)[int(u[20 + i] * 5)]
                for j in range(k):
                    hit(s, "vox", var, voxa * (1.0 - 0.15 * j), (u[(5 + i) % 32] - 0.5) * 1.2, j * 0.5)
        if brth > 0.05 and self.vbar % 2 == 0:   # mirror: breathing close to the ear
            hit(0, "breath", 0, brth, -0.2)
            hit(8, "breath", 1, brth * 0.8, 0.2)
        if rev > 0.2 and G.u("swl", 1)[0] < rev * 0.7 and (p["hs"] > 0.2 or self.sens["f"] > 0.5):
            n = len(self.bank["swell"][self.vbar % 2])
            hit(0, "swell", self.vbar % 2, 1.0, 0.0, 16.0 - n / self.sps())
        # --- fills and transitions
        f = plan.fill
        if f == "roll":
            for s in range(16):
                k = 1 if s < 8 else (1 if s < 12 else 2)
                if s < 8 and s % 2:
                    continue
                for j in range(k):
                    g = 0.3 + 0.7 * ((s + j / 2.0) / 16.0) ** 1.6
                    hit(s, "roll", 0 if s < 8 else (1 if s < 12 else 2), g, 0.15 * ((s % 3) - 1), j * 0.5)
            n = len(self.bank["swell"][1])
            hit(0, "swell", 1, 0.8, 0.0, 16.0 - n / self.sps())
        elif f == "roll_half":
            for s in range(8, 16):
                for j in range(1 if s < 12 else 2):
                    hit(s, "roll", 1 if s < 12 else 2, 0.35 + 0.6 * ((s - 8) / 8.0), 0.0, j * 0.5)
        elif f == "flam":
            hit(14, "snare", 1, 0.6, -0.1)
            hit(15, "snare", 2, 0.8, 0.1)
            hit(15, "snare", 0, 0.5, 0.0, 0.5)
        elif f == "tom":
            u = G.u("tom", 4)
            for i, s in enumerate((12, 13, 14, 15) if u[0] < 0.5 else (12, 13, 14)):
                hit(s, "tom", 3 - i if u[1] < 0.7 else i, 0.8, (i - 1.5) * 0.3, (u[2] * 0.33) if i else 0.0)
        elif f == "stutter":
            hit(12, "stutter", (4, int(G.pick("sdv", (4, 8, 8, 16)))))
        elif f == "swell":
            n = len(self.bank["swell"][0])
            hit(0, "swell", 0, 1.0, 0.0, 16.0 - n / self.sps())
        elif f == "hatonly":
            for s in range(8, 16):
                pat[s] = [h for h in pat[s] if h[0] not in ("kick", "rumble", "clap", "snare", "stab", "bass")]
        if plan.throw:
            self.throw_until = int(self.bar_t0 + self.bar_len)
        # --- phrase structure: risers (N), impacts, crashes
        if plan.drop:
            hit(0, "impact", 0, 1.0)
            hit(0, "crash", 0, 1.0)
        elif plan.first and plan.section in ("break", "outro") and self.vbar > 0:
            hit(0, "impact", 0, 0.6)
            hit(0, "crash", 0, 0.5)
        elif plan.bis % 8 == 0 and self.riser_due:
            hit(0, "impact", 0, 0.7)
            hit(0, "crash", 0, 0.6)
        self.riser_due = False
        if plan.riser or (plan.bis % 8 == 4 and plan.section in ("peak",) and
                          p["riser"] * hm("riser") > 0.1 and G.u("ris", 1)[0] < 0.1 + 0.5 * N):
            hit(0, "riser", 0, 1.0)
            self.riser_due = True
        # --- glitch stutters (N)
        g = N * I * 1.1 * p["glitch"] * hm("glitch")
        if D.u("gl", 1)[0] < g:
            u = D.u("glu", 4)
            s = (12, 13, 14, 15, int(u[1] * 16))[int(u[0] * 5)]
            hit(s, "stutter", ((1, 2, 4)[int(u[2] * 3)], (2, 4, 8, 16)[int(u[3] * 4)]))
        self.pattern = pat

    def _add(self, bus, sig, at, gain):
        R, M = self.R, self.M
        n = sig.shape[-1]
        i = at & M
        j = min(R, i + n)
        k = j - i
        if bus.ndim == 2:
            g = np.asarray(gain, np.float32).reshape(2, 1)
            if sig.ndim == 1:
                sig = sig[None, :]
            bus[:, i:j] += g * sig[:, :k]
            if k < n:
                bus[:, :n - k] += g * sig[:, k:]
        else:
            if sig.ndim == 2:
                sig = sig[0]
            bus[i:j] += gain * sig[:k]
            if k < n:
                bus[:n - k] += gain * sig[k:]

    def _transposed(self, inst, var, semis):
        if semis == 0:
            return self.bank[inst][var % len(self.bank[inst])]
        k = (inst, var, semis)
        sig = self.tcache.get(k)
        if sig is None:
            bank = self.bank[inst]
            sig = V.resample(bank[var % len(bank)], semis)
            self.tcache[k] = sig
        return sig

    def _play_step(self, s, t):
        sps = self.sps()
        p = self.p
        perc = (0.5 + 0.5 * p["I"]) * (0.8 + 0.4 * p["E"]) * (1.0 + 0.25 * self.sens["y"])
        throw = t < self.throw_until
        for inst, var, gain, pan, off, x in self.pattern[s]:
            at = int(t + off * sps)
            if inst == "stutter":
                nst, div = var
                self.stutters.append([at, at + int(nst * sps), max(64, int(sps / div)), None])
                continue
            if inst == "riser":
                n = int(min(8.5 * SR, 64 * sps))
                if self.helper is not None:          # made ahead, never here
                    got = self._stock_riser("riser", n)
                    if got is None:
                        continue
                    sig, lag = got
                    at += lag
                else:
                    rng = np.random.default_rng([self.seed, self.vbar, 9])
                    sig = V.riser(rng, n, tension=p["N"], sps=sps / 2.0)
                g = 0.3 * self.p["riser"] * self._hookmod("riser")
                self._add(self.fx, sig, at, (g, g))
                self._add(self.vsend, sig[0], at, g * 0.3)
                continue
            if inst == "bass":
                note, acc, slide, gate = x
                self.bass.note(at, gate * sps, float(midi_hz(note)), acc, slide)
                continue
            base = inst[:-2] if inst.endswith("_r") else inst
            key, layer, lvl, dry, vs, ds = INST[base]
            g = gain * lvl * self._vgain(key, layer)
            if base in PERC:
                g *= perc
            if g < 1e-4:
                continue
            if base == "stab":
                sig = self._transposed(inst, var, x or 0)
            elif base == "heart":
                sig = self.bank["kick_far"][0]
            else:
                bank = self.bank[inst]
                sig = bank[var % len(bank)]
            if base in PERC or base in ("stab", "kick_far", "crash"):
                pan = pan + 0.7 * self.sens["x"]          # phone left/right moves the hits
            a = (clamp(pan, -1.0, 1.0) + 1.0) * np.pi / 4.0
            gl, gr = g * dry * np.cos(a) * 1.414, g * dry * np.sin(a) * 1.414
            self._add(self.syn if base == "stab" else self.dry, sig, at, (gl, gr))
            vmul = p["verb"] * 2.0 * self._hookmod("verb") * (1.0 + 0.6 * self.sens["y"])
            if vs > 0:
                self._add(self.vsend, sig, at, g * vs * vmul)
            if ds > 0 or throw:
                dsg = g * (ds * (3.0 if throw else 1.0) + (0.25 if throw and base in PERC else 0.0))
                if dsg > 1e-4:
                    self._add(self.dsend, sig, at, dsg)
            if inst == "kick":
                n = min(sig.shape[-1], int(sps * 3.5))
                u = np.arange(n) / float(sps * 4.0)        # fraction of a beat
                env = np.exp(-(u / 0.42) ** 2) * np.clip(u * 400.0, 0.0, 1.0)
                self._add(self.duck, env.astype(np.float32), at, min(1.0, g * 3.0))

    # ------------------------------------------------------------- continuous
    def _drone(self):
        B, p = self.IB, self.p
        lay = self.layers.get("drone", 1.0)
        target = p["drone"] * self._hookmod("drone") * lay
        sub_t = (0.15 + 0.85 * p["drone"]) * self._hookmod("sub") * (0.6 + 0.4 * min(1.0, lay)) * \
            (1.0 if self.phase != "wipe" else 0.0)
        g0, s0 = self.drone_g, self.sub_g
        self.drone_g, self.sub_g = target, sub_t
        if max(g0, target, s0, sub_t) < 1e-4:
            return None, None
        A, N, O, I = p["A"], p["N"], p["O"], p["I"]
        # breathing rate wanders with the room clock and the section, so the
        # drone's swell never settles into one fixed period over the hours
        cl = self.clock
        rate = 0.045 + 0.06 * cl.energy + 0.025 * np.sin(cl.bar * 0.0137 + self.seed % 7)
        self.lfo = (self.lfo + B / SR * rate) % 1.0
        self.lfo2 = (self.lfo2 + B / SR * (0.21 + 0.17 * cl.room)) % 1.0
        br = 0.5 + 0.5 * np.sin(TWO_PI * self.lfo)
        breath = 1.0 - p["breath"] * 0.6 * (1.0 - br)
        det = (4.0 + 30.0 * N) / 100.0
        wob = N * 0.12 * np.sin(TWO_PI * self.lfo2)
        wa = clamp(A) ** 1.3
        w = np.concatenate([np.full(10, wa), np.full(10, 1.0 - wa)]) / 7.0
        f = midi_hz(self.root_s + _DRONE_IV + _DRONE_SG * det + wob)
        DS = self.DS
        nd = B // DS
        dt = f * (DS / SR)
        on = (w > 0.015) & (max(g0, target) > 1e-4)
        if on.any():
            d = dt[on][:, None]
            ph = (self.drone_ph[on][:, None] + d * (self.d_ar + 1)) % 1.0
            s = saw_blep(ph, d)
            a = (_DRONE_PAN[on] + 1.0) * np.pi / 4.0
            wo = w[on]
            x = np.stack([(wo * np.cos(a)) @ s, (wo * np.sin(a)) @ s])
        else:
            x = np.zeros((2, nd))
        self.drone_ph = (self.drone_ph + dt * nd) % 1.0
        fc = 90.0 + (250.0 + 1600.0 * I * p["open"] + 600.0 * O) * (1.0 - 0.5 * p["breath"] * (1.0 - br))
        fc = min(4800.0, fc * 2.0 ** (1.0 * self.sens["y"] + 0.6 * self.sens["x"]))
        q = 0.9 + 1.6 * br * (0.4 + 0.6 * p["breath"]) + 1.2 * N
        x = self.dreso.glide(x, fc, q)
        # back to 48 kHz (linear interpolation; the 12 kHz images sit > 40 dB down
        # because the filter above already removed everything over a few kHz)
        ext = np.concatenate([self.dlast, x], axis=1)
        self.dlast = x[:, -1:].copy()
        x = ext[:, self.d_i0 + 1] * self.d_w + ext[:, self.d_i0] * (1.0 - self.d_w)
        x = np.tanh(x * (1.0 + N)) / (1.0 + 0.5 * N)
        x *= (g0 + (target - g0) * self.ramp) * breath
        fs = float(midi_hz(self.root_s))
        sph = self.sub_ph + TWO_PI * fs / SR * (self.ar + 1)
        self.sub_ph = float(sph[-1] % TWO_PI)
        sub = 0.2 * (s0 + (sub_t - s0) * self.ramp) * breath * np.sin(sph)
        return x, sub

    def _tension(self, u):
        """Rising band-noise wash before drops (and on shakes)."""
        pl = self.plan
        lay = self.layers.get("tension", 0.0)
        t0, t1 = (pl.tension if pl else (0.0, 0.0))
        tv = (t0 + (t1 - t0) * u) * lay
        sh = self.sens["e"] if self.sens["e"] > 0.3 else 0.0
        tgt = max(tv, 0.6 * sh) * (1.0 if self.mg_target > 0 else 0.0)
        g0 = self.tens_g
        self.tens_g = tgt
        if max(g0, tgt) < 1e-3:
            return None
        n = self.noise_rng.standard_normal((2, self.IB))
        lvl = max(tv, sh)
        fc = 300.0 * 2.0 ** (4.6 * lvl)
        y = self.treso.glide(n, fc, 1.5 + 3.0 * lvl, "bp")
        return y * (0.08 * (g0 + (tgt - g0) * self.ramp))[None, :]

    def _shake(self, b0):
        """Phone motion: a burst of stutter plus a one-bar noise riser."""
        e = self.sens_t["e"]
        if self.shake_cool > 0:
            self.shake_cool -= 1
            return
        if e > 0.45 and self.mg > 0.2:
            sps = self.sps()
            div = 4 if e < 0.7 else (8 if e < 0.9 else 16)
            self.stutters.append([b0, b0 + int(sps * (1 + 2 * e)), int(sps / div), None])
            lag = 0
            if self.helper is not None:              # made ahead, never here
                got = self._stock_riser("shake", int(16 * sps))
                sig, lag = got if got is not None else (None, 0)
            else:
                rng = np.random.default_rng([self.seed, b0 & 0xFFFFFF, 11])
                sig = V.riser(rng, int(16 * sps), tension=0.6, sps=sps / 2.0)
            g = 0.22 * e
            if sig is not None:
                self._add(self.dry, sig, b0 + self.IB + lag, (g, g))
            self.shake_cool = int(16 * sps / self.IB)   # at most once per bar

    # ----------------------------------------------------------------- master
    def _stutter(self, x, b0):
        B, H = self.IB, self.H
        if self.stutters:
            ext = np.concatenate([self.hist, x], axis=1)
            keep = []
            for st in self.stutters:
                start, end, L, sl = st
                if start >= b0 + B:
                    keep.append(st)
                    continue
                if sl is None:
                    i = H + (start - b0)
                    L = min(L, i)
                    sl = ext[:, i - L:i].copy()
                    e = min(48, L // 2)
                    win = np.sin(np.linspace(0, np.pi / 2, e)) ** 2
                    sl[:, :e] *= win
                    sl[:, L - e:] *= win[::-1]
                    st[2], st[3] = L, sl
                lo, hi = max(start, b0), min(end, b0 + B)
                if hi > lo:
                    idx = (np.arange(lo, hi) - start) % L
                    x[:, lo - b0:hi - b0] = sl[:, idx]
                if end > b0 + B:
                    keep.append(st)
            self.stutters = keep
        self.hist[:, :-B] = self.hist[:, B:]
        self.hist[:, -B:] = x
        return x

    def render_block(self):
        """Return the next B (1024) stereo frames as int16, shape (B, 2)."""
        if not self._pending:
            big = self._render()
            self._pending = [big[i:i + self.B] for i in range(0, self.IB, self.B)]
        return self._pending.pop(0)

    def _render(self):
        """Render one internal block (IB frames)."""
        B = self.IB
        b0 = self.pos
        b1 = b0 + B
        self._smooth()
        p = self.p
        if self.slam_due:                       # end of a hinge: restart the bar grid right now
            self.slam_due = False
            if self.phase in ("hook", "profiling", "approach", "release") and not self.wiping:
                if self.step % 16:
                    self.step += 16 - self.step % 16
                    self.vbar += 1
                    self.phase_bars += 1
                self.next_step_at = float(b0)
                for a in (self.dry, self.fx, self.syn, self.vsend, self.dsend, self.duck):
                    a[:] = 0.0
                self.stutters = []
                self.bass.reset()
                self.slam_flag = True
                self.hg = 1.0
        while self.next_step_at < b1:
            t = max(self.next_step_at, float(b0))
            s = self.step % 16
            if s == 0:
                self._bar_start()
            self._play_step(s, t)
            self.step += 1
            if s == 15:
                self.vbar += 1
                self.phase_bars += 1
                self.gbar += 1
            self.next_step_at += self.sps()
        self._run_job(1)

        i0 = b0 & self.M
        sl = slice(i0, i0 + B)
        self._shake(b0)
        dry = self.dry[:, sl].astype(np.float64)
        syn = self.syn[:, sl].astype(np.float64)
        fx = self.fx[:, sl].astype(np.float64)
        vs = self.vsend[sl].astype(np.float64)
        ds = self.dsend[sl].astype(np.float64)
        duck = self.duck[sl].astype(np.float64)
        for a in (self.dry, self.fx, self.syn):
            a[:, sl] = 0.0
        for a in (self.vsend, self.dsend, self.duck):
            a[sl] = 0.0
        u = clamp((b0 - self.bar_t0) / max(1.0, self.bar_len))
        sx, sy = self.sens["x"], self.sens["y"]
        I, N = p["I"], p["N"]
        if self.wiping:                         # the groove dissolves; its reverb rings out
            w0 = getattr(self, "_wg_prev", self.wg)
            wr = w0 + (self.wg - w0) * self.ramp
            dry *= wr
            syn *= wr
            fx *= wr
            vs *= wr
            ds *= wr
            self._wg_prev = self.wg
        else:
            self._wg_prev = 1.0

        g0 = self.fx_g
        self.fx_g = p["riser"] * self._hookmod("riser")
        mix = dry + fx * (g0 + (self.fx_g - g0) * self.ramp)
        dk = np.clip(duck, 0.0, 1.0)
        duckg = 1.0 - 0.6 * dk
        # stab bus: tilt left/right sweeps its resonant low-pass
        if np.any(syn):
            fcs = clamp(2200.0 * 2.0 ** (2.2 * sy + 1.2 * sx), 150.0, 16000.0)
            mix += self.sreso.glide(syn, fcs, 0.8 + 2.5 * abs(sx)) * (1.0 - 0.3 * dk)
        else:
            self.sreso.glide(syn, 2200.0, 0.8)
        # bassline
        if self.bass_style:
            acid = self.bass_style == "acid"
            bl = p["bass"] * self._hookmod("bass") * self.layers.get("bass", 0.0)
            if acid:
                cut = 140.0 * 2.0 ** (1.3 * sx + 1.4 * I + 0.8 * p["O"] + 0.5 * sy)
                bsig = self.bass.render(b0, "acid", cut, 2.6 + 1.2 * N, 5.0 + 9.0 * (0.4 + 0.6 * p["O"]) * (0.6 + 0.4 * abs(sx) + 0.2 * N),
                                        0.16 + 0.12 * p["O"], 1.8 + 1.5 * (1.0 - p["A"]), self.dna.bass_wave, 0.0,
                                        0.15 * bl)
            else:
                cut = 180.0 * 2.0 ** (0.7 * sx + 0.8 * I + 0.3 * sy)
                bsig = self.bass.render(b0, "roll", cut, 1.6, 1.1 + 0.6 * abs(sx), 0.09, 1.3,
                                        0.3 * self.dna.bass_wave, 0.5, 0.21 * bl)
            if bsig is not None:
                if self.wiping:
                    bsig = bsig * self.wg
                mix += (bsig * (1.0 - (0.85 if not acid else 0.5) * dk))[None, :]
        tens = self._tension(u)
        if tens is not None:
            if self.wiping:
                tens = tens * self.wg
            mix += tens
        drone, sub = self._drone()
        vin = vs.copy()
        if drone is not None:
            mix += drone * duckg
            vin += (drone[0] + drone[1]) * (0.12 * p["verb"])
        if tens is not None:
            vin += tens[0] * 0.5
        rm = self.clock.room
        t60 = 0.8 + 38.0 * (clamp(p["vfb"], 0.85, 0.97) - 0.85) * (0.7 + 0.6 * rm)
        wet = self.room.process(vin, t60, 0.45 - 0.3 * p["open"], 0.45 + 0.4 * rm)
        mix += wet * (0.8 + 0.2 * duckg)
        D = int(round(3 * self.sps()))
        throw = b0 < self.throw_until
        mix += 0.4 * self.delay.process(ds, D, (0.62 if throw else 0.35 + 0.35 * p["verb"]),
                                        1800.0 + 2000.0 * p["E"])
        # hinge (held breath): everything but the sub drops out
        h0 = getattr(self, "_hg_prev", self.hg)
        if h0 < 0.999 or self.hg < 0.999:
            mix *= (h0 + (self.hg - h0) * self.ramp)[None, :]
        self._hg_prev = self.hg
        if sub is not None:                      # the sub ducks under the kick (it shares its note)
            mix += (sub * (1.0 - 0.85 * dk))[None, :] * (1.0 + 0.6 * (1.0 - self.hg))

        # ---- master: sweep HP, resonant LP (tilt), saturation, stutter, mono-low, DC, glue, limiter
        pl = self.plan
        h0, h1 = pl.hp if pl else (20.0, 20.0)
        hfc = h0 * (h1 / h0) ** u
        if hfc > 21.0 or self.hp_on:
            if not self.hp_on:
                self.hp.reset()
                self.hp.fc_last = None
            self.hp_on = hfc > 21.0
            mix = self.hp.glide(mix, max(12.0, hfc), pl.q if pl else 0.9, "hp")
        l0, l1 = pl.lp if pl else (1.0, 1.0)
        lpm = l0 + (l1 - l0) * u
        op = clamp(p["open"] * self._hookmod("open") * (0.55 + 0.45 * I) * (0.8 + 0.3 * p["E"]))
        op = clamp(op * (1.0 + 0.45 * sy)) * lpm
        mfc = 250.0 + 11500.0 * op * op         # a dark room: the top stays under ~12 kHz
        mq = max(pl.q if pl and pl.lp != (1.0, 1.0) else 0.75, 0.75 + 3.2 * abs(sx) ** 1.5 + 0.8 * N * I)
        mix = self.mlp.glide(mix, mfc, mq, "lp")
        if mq > 1.0:
            mix *= 1.0 / (1.0 + 0.12 * (mq - 1.0))       # keep resonance from jumping out
        drv = 1.2 + 1.6 * I + 0.8 * (1.0 - p["A"]) + 0.8 * self.clock.grit
        mix = self.sat.process(mix * 0.9, drv, 0.12 + 0.2 * self.clock.grit, 1.1 + 0.4 * I)
        mix = self._stutter(mix, b0)
        mix -= self.dc.process(mix, lp_coef(10.0))      # the asymmetric drive makes a little DC
        mix = self.glue.process(mix)

        v0 = getattr(self, "_vol_s", self.volume)       # volume changes glide (~60 ms)
        self._vol_s = v0 + (self.volume - v0) * 0.3
        mg0 = getattr(self, "_mg_prev", self.mg)
        mix *= p["level"] * 1.5 * (v0 + (self._vol_s - v0) * self.ramp) * (mg0 + (self.mg - mg0) * self.ramp)
        self._mg_prev = self.mg
        if self.wiping and self.wipe_t >= self.WIPE_S:
            self._finish_wipe()
        mix -= self.dc2.process(mix, lp_coef(6.0))       # DC guard after the glue's gain riding
        mix = self.lim.process(mix)
        mix -= self.dc3.process(mix, lp_coef(2.5))       # removes the limiter's own tiny DC
        self.pos = b1
        return (mix.T * 32767.0).astype(np.int16)

    def silence(self):
        return np.zeros((self.B, 2), np.int16)
