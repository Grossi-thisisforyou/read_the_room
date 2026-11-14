"""TechnoSynth: the INFINITE JEST live techno generator.

Call set_state(state) whenever the show state changes and render_block() to
get the next 1024 stereo frames (int16). Everything audible glides: voice
levels, filters, tempo and OCEAN-derived parameters follow their targets over
one to two bars; drum patterns are re-drawn on bar boundaries and the bigger
structure (risers, impacts) on 8-bar phrases. Patterns come from an RNG seeded
by the visitor id, so a given visitor always gets 'their' track.
"""
import os
import zlib

import numpy as np

from . import voices as V
from .dsp import (SR, OnePole, PingPong, Reverb, TWO_PI, clamp, lp_coef, midi_hz,
                  saw_blep)

PHASES = ("idle", "approach", "profiling", "hook", "release", "wipe")
OCEAN = ("O", "C", "E", "A", "N")
BPM_MIN, BPM_MAX = 120.0, 145.0

# Target level of each voice per phase (0..1), plus mix/FX settings.
#   verb = reverb send multiplier, vfb = reverb feedback (room size),
#   open = master filter openness, breath = slow amplitude breathing of the
#   drone, hs = how strongly the visitor's hook shapes the arrangement.
_P = ("kick", "rumble", "hat", "ohat", "clap", "clank", "metal", "click", "stab",
      "drone", "riser", "glitch", "verb", "vfb", "open", "breath", "hs")
PHASE_TABLE = {
    "idle":      (0.45, 0.0, 0.0, 0.0, 0.0, 0.12, 0.10, 0.05, 0.0, 0.85, 0.0, 0.0, 0.60, 0.93, 0.25, 1.0, 0.0),
    "approach":  (0.85, 0.70, 0.25, 0.0, 0.0, 0.25, 0.20, 0.20, 0.10, 0.70, 0.35, 0.10, 0.40, 0.90, 0.50, 0.5, 0.25),
    "profiling": (1.00, 0.85, 0.75, 0.30, 0.35, 0.55, 0.40, 1.00, 0.35, 0.50, 0.70, 0.60, 0.30, 0.88, 0.70, 0.2, 0.5),
    "hook":      (1.00, 1.00, 1.00, 0.80, 1.00, 1.00, 0.70, 0.45, 1.00, 0.45, 1.00, 1.00, 0.28, 0.88, 1.00, 0.0, 1.0),
    "release":   (0.00, 0.00, 0.25, 0.00, 0.00, 0.30, 0.20, 0.25, 0.70, 1.00, 0.00, 0.15, 0.80, 0.955, 0.45, 0.8, 0.7),
    "wipe":      (0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.60, 0.90, 0.20, 0.0, 0.0),
}
PHASE_TABLE = {k: dict(zip(_P, v)) for k, v in PHASE_TABLE.items()}

# Hook = arrangement family. Multipliers on voice levels; extras are amounts.
_HK = ("kick", "rumble", "hat", "ohat", "clap", "clank", "metal", "click", "stab",
       "drone", "riser", "glitch", "open", "verb", "level", "sub",
       "vox", "breath", "rev", "offgrid", "broken", "heavy", "bpm")
HOOKS = {
    #            kick rumb hat  ohat clap clnk metl clik stab drone risr glch open verb lvl  sub  vox brth rev  offg brkn hvy bpm
    "default":  (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0),
    "flesh":    (1.15, 1.25, 0.6, 0.4, 0.6, 0.6, 0.8, 0.4, 0.7, 1.6, 0.6, 0.4, 0.7, 1.1, 1.0, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, -5),
    "scrawl":   (0.9, 0.8, 0.9, 0.5, 0.7, 1.0, 1.0, 1.2, 0.6, 0.7, 0.8, 2.0, 1.0, 0.9, 1.0, 1.0, 1.0, 0.0, 0.0, 0.1, 1.0, 0.0, 0),
    "inverted": (1.0, 1.0, 1.0, 0.8, 0.6, 0.9, 0.8, 0.8, 1.0, 1.0, 0.5, 0.8, 0.9, 1.2, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.3, 0.0, 0),
    "mirror":   (0.15, 0.1, 0.25, 0.0, 0.0, 0.25, 0.0, 0.3, 0.35, 0.6, 0.1, 0.1, 0.45, 0.5, 0.7, 1.3, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, -4),
    "void":     (0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.0, 0.12, 0.0, 0.15, 0.0, 0.0, 0.2, 0.7, 0.5, 1.8, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0, -6),
}
HOOKS = {k: dict(zip(_HK, v)) for k, v in HOOKS.items()}
_HOOK_EXTRA = ("vox", "breath", "rev", "offgrid", "broken", "heavy", "bpm")

# instrument -> (phase/hook voice key, base level, dry, reverb send, delay send)
INST = {
    "kick":     ("kick", 0.30, 1.0, 0.04, 0.0),
    "kick_far": ("kick", 0.30, 0.7, 0.60, 0.15),
    "rumble":   ("rumble", 0.24, 1.0, 0.0, 0.0),
    "hat":      ("hat", 0.42, 1.0, 0.08, 0.05),
    "ohat":     ("ohat", 0.26, 1.0, 0.15, 0.05),
    "clap":     ("clap", 0.55, 1.0, 0.35, 0.10),
    "clank":    ("clank", 0.40, 1.0, 0.35, 0.25),
    "metal":    ("metal", 0.32, 1.0, 0.50, 0.20),
    "tick":     ("click", 0.30, 1.0, 0.15, 0.30),
    "stab":     ("stab", 0.75, 1.0, 0.35, 0.45),
    "vox":      ("vox", 0.45, 1.0, 0.20, 0.35),
    "breath":   ("breath", 0.30, 1.0, 0.25, 0.0),
    "swell":    ("rev", 0.30, 1.0, 0.30, 0.0),
    "impact":   (None, 0.35, 1.0, 0.60, 0.0),
}
PERC = {"hat", "ohat", "clap", "clank", "metal", "tick", "vox"}

_CONS = np.array([12, 19, 27, 31, 34], dtype=float)   # minor: oct, 5th, m3, 5th, m7
_DISS = np.array([13, 18, 23, 25, 30], dtype=float)   # b9, tritone, maj7 cluster


def seed_for(visitor_id, user_seed=0):
    if visitor_id is None:
        return int(user_seed) & 0x7FFFFFFF
    return (zlib.crc32(str(visitor_id).encode("utf-8")) ^ int(user_seed)) & 0x7FFFFFFF


class DNA:
    """Per-visitor musical fingerprint, fixed for the whole visit."""

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


def _prep_init():
    try:
        os.nice(5)          # the helper yields to the render loop and the visuals
    except OSError:
        pass


def _noop():
    return True


class _Prep:
    """Slow sample generation (bank sections, risers) in a helper process.

    A rebuilt clank/metal/swell section takes ~200 ms on a fast x86 and about
    three times that on a Pi 5; done inside render_block it drains the 150 ms
    output buffer and the sound drops out mid-visit. A thread does not help:
    the helper holds the GIL and render_block's many small numpy calls queue
    behind it (measured: worse). So one helper process makes the samples and
    render_block keeps the old ones until the new ones have arrived. One job
    runs at a time; a newer request for the same name replaces a queued one.
    """

    ORDER = ("riser", "shake", "bank:k", "bank:h", "bank:s", "bank:c", "bank:t")

    def __init__(self):
        import concurrent.futures as cf
        import multiprocessing as mp
        self._ex = cf.ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), initializer=_prep_init)
        self._queued = {}        # name -> (key, fn, args)
        self._running = None     # (name, key, future)
        self._done = {}          # name -> (key, result)
        self.broken = False
        self._running = ("warmup", None, self._ex.submit(_noop))

    def submit(self, name, key, fn, *args):
        self._queued[name] = (key, fn, args)
        self.poll()

    def poll(self):
        """Collect a finished job and start the next one. Cheap; call often."""
        if self.broken:
            return
        if self._running is not None:
            name, key, fut = self._running
            if not fut.done():
                return
            self._running = None
            try:
                res = fut.result()
            except Exception:          # helper died: fall back to building inline
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

    def take(self, name, key=None):
        """The finished (key, result) for name, or None. With key: only that one."""
        self.poll()
        got = self._done.get(name)
        if got is None or (key is not None and got[0] != key):
            return None
        return self._done.pop(name)

    def has(self, name):
        """Requested, being made, or ready."""
        return name in self._done or name in self._queued or (
            self._running is not None and self._running[0] == name)

    def forget(self):
        self._queued.clear()
        self._done.clear()

    def idle(self):
        self.poll()
        return not self._queued and self._running is None

    def close(self):
        self._ex.shutdown(wait=False, cancel_futures=True)


def _riser(seed, vbar, n, tension, sps2, salt=9):
    rng = np.random.default_rng([seed, vbar, salt])
    return V.riser(rng, n, tension=tension, sps=sps2)


def build_section(name, s, I, O, E, A, N, bpm):
    """One sample-bank section, from the visitor seed s and the (gliding)
    parameters. Module level so the helper process can run it."""
    d = DNA(s)
    if name == "k":
        drive = round((1.5 + 2.5 * I) * 2) / 2.0
        bq = int(bpm // 2)
        rng = np.random.default_rng([s, 1, int(drive * 2), bq])
        k0 = V.kick(rng, drive=drive)
        return {"kick": [k0, V.kick(rng, drive=drive, f0=130, f1=50, decay=0.2, length=0.35),
                         V.kick(rng, drive=drive + 1.5, f0=120, f1=38, decay=0.6, length=0.8)],
                "kick_far": [V.kick(rng, drive=1.2, decay=0.5, length=0.7, click=0.0, lowpass=180)],
                "rumble": [V.rumble(rng, k0, int(SR * 60.0 / (bq * 2 + 1)), drive=drive)]}
    if name == "h":
        hk = (round(E * 4), round(I * 4))
        rng = np.random.default_rng([s, 2, hk[0], hk[1]])
        b, dr = E, 1.0 + 2.0 * I
        hs = [V.hat(rng, 0.032, b, 0.3, dr), V.hat(rng, 0.05, b, 0.5, dr), V.hat(rng, 0.022, b, 0.8, dr)]
        return {"hat": hs, "hat_r": [h[::-1].copy() for h in hs],
                "ohat": [V.hat(rng, 0.22, b, 0.45, dr)],
                "clap": [V.clap(rng, 0.12, 1300 + 600 * E), V.clap(rng, 0.2, 1100 + 500 * E)]}
    if name == "c":
        ck = (round(O * 4), round(A * 4))
        rng = np.random.default_rng([s, 3, ck[0], ck[1]])
        Oq, Aq = ck[0] / 4.0, ck[1] / 4.0
        root_hz = float(midi_hz(d.root + 36))
        scale = (0, 3, 5, 7, 10, 12, 15)
        out = []
        for i in range(6):
            if rng.random() < Aq:   # tonal, tuned to the visitor's root
                fc = root_hz * 2.0 ** (scale[int(rng.integers(len(scale)))] / 12.0)
                ratio = float(rng.choice([1.0, 2.0, 3.0, 1.5]))
            else:                   # atonal metal
                fc = rng.uniform(180.0, 1800.0)
                ratio = float(d.clank_ratios[i])
            ratio += Oq * rng.uniform(-0.4, 0.6)
            out.append(V.clank(rng, fc, max(0.3, ratio), index=2 + 6 * Oq * rng.random() + 4 * (1 - Aq),
                               decay=0.12 + 0.3 * rng.random(), ring=(1 - Aq) * 0.7))
        return {"clank": out, "clank_r": [c[::-1].copy() for c in out],
                "metal": [V.metal(rng, rng.uniform(150, 700), harsh=1 - Aq) for _ in range(3)],
                "swell": [V.swell(rng), V.swell(rng, 2.4)]}
    if name == "s":
        sk = (round(A * 4), round(N * 4), round(I * 3))
        rng = np.random.default_rng([s, 4, sk[0], sk[1], sk[2]])
        Aq, Nq, Iq = sk[0] / 4.0, sk[1] / 4.0, sk[2] / 3.0
        if Aq > 0.62:
            voicings = [[0, 3, 7, 10], [0, 3, 7, 14], [-2, 3, 7, 10]]
        elif Aq < 0.38:
            voicings = [[0, 1, 6, 11], [0, 1, 2, 7], [0, 6, 11, 13]]
        else:
            voicings = [[0, 3, 7, 13], [0, 3, 7, 10, 13], [-2, 3, 6, 10]]
        root = float(midi_hz(d.root + 24))
        st = [V.stab(rng, root, v, 6 + 35 * Nq, 500 + 2500 * Iq, 0.18 + 0.25 * rng.random())
              for v in voicings]
        return {"stab": st, "stab_r": [x[::-1].copy() for x in st]}
    rng = np.random.default_rng([s, 5])
    return {"tick": [V.tick(rng, rng.uniform(1500, 9000), rng.uniform(0.003, 0.012),
                            rng.random() < 0.4) for _ in range(8)],
            "impact": [V.impact(rng)],
            "vox": [V.vox(rng, rng.uniform(0.06, 0.16)) for _ in range(8)],
            "breath": [V.breath(rng, 1.3, 800), V.breath(rng, 1.6, 1300)]}


class TechnoSynth:
    def __init__(self, block=1024, seed=0, volume=0.9, helper=True):
        self.B = int(block)
        assert self.B % 64 == 0
        self.R = 1 << 19                      # ~10.9 s scheduling ring
        self.M = self.R - 1
        self.user_seed = int(seed)
        self.volume = float(volume)
        self.ar = np.arange(self.B)
        self.prep = None
        if helper:
            try:
                self.prep = _Prep()
            except Exception:       # no processes allowed here: build inline as before
                self.prep = None
        self.gen = 0                          # bumped on every reset: stale prep results are ignored
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
        self._reset_musical_state(snap=True)

    # ------------------------------------------------------------------ setup
    def _alloc(self):
        R = self.R
        self.dry = np.zeros((2, R), np.float32)
        self.fx = np.zeros((2, R), np.float32)
        self.syn = np.zeros((2, R), np.float32)     # stabs: live tilt-filtered bus
        self.slp1, self.slp2 = OnePole(2), OnePole(2)
        self.vsend = np.zeros(R, np.float32)
        self.dsend = np.zeros(R, np.float32)
        self.duck = np.zeros(R, np.float32)
        self.reverb = Reverb(self.B)
        self.delay = PingPong(self.B)
        self.mlp1, self.mlp2, self.dc = OnePole(2), OnePole(2), OnePole(2)
        self.dlp1, self.dlp2 = OnePole(2), OnePole(2)
        self.H = 16384
        self.hist = np.zeros((2, self.H))
        nd = 2 * (len(_CONS) + len(_DISS))
        self.drone_ph = np.zeros(nd)
        self.sub_ph = 0.0
        self.lfo = 0.0
        self.lfo2 = 0.0
        self.pos = 0
        self.next_step_at = 0.0
        self.step = 0
        self.limg = 1.0

    def _reset_musical_state(self, snap=False):
        for a in (self.dry, self.fx, self.syn, self.vsend, self.dsend, self.duck, self.hist):
            a[:] = 0.0
        self.reverb.reset()
        self.delay.reset()
        for f in (self.mlp1, self.mlp2, self.dc, self.dlp1, self.dlp2, self.slp1, self.slp2):
            f.reset()
        self.stutters = []
        self.pattern = [[] for _ in range(16)]
        self.vbar = 0
        self.phase_bars = 0
        self.bar_phase = self.phase
        self.riser_due = False
        self.bank = {}
        self.bank_keys = {}
        self.bank_asked = {}
        self.gen += 1
        if self.prep is not None:
            self.prep.forget()
        self.hw = {h: (1.0 if h == "default" else 0.0) for h in HOOKS}
        self._set_visitor(self.visitor, force=True)
        if snap or not hasattr(self, "p"):
            self.p = dict(PHASE_TABLE[self.phase])
            for k in ("I", "O", "C", "E", "A", "N"):
                self.p[k] = self.targets[k]
            self.p["bpm"] = self._bpm_target()
            self.p["level"] = 1.0
        self.drone_g = 0.0
        self.fx_g = 0.0
        self.sens = dict(x=0.0, y=0.0, e=0.0, f=0.0)   # smoothed tilt / motion / flip
        self.sens_t = dict(x=0.0, y=0.0, e=0.0, f=0.0)
        self.shake_cool = 0
        self._build_bank(sync=True)

    def _set_visitor(self, vid, force=False):
        if vid == self.visitor and not force and hasattr(self, "dna"):
            return
        self.visitor = vid
        self.seed = seed_for(vid, self.user_seed)
        self.dna = DNA(self.seed)
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

    def wipe(self):
        """Fade to silence over ~2 s, then forget the visitor and return to idle."""
        if not self.wiping:
            self.wiping = True
            self.mg_target = 0.0

    def _finish_wipe(self):
        self.wiping = False
        self.visitor = None
        self.targets.update(I=0.15, O=0.5, C=0.5, E=0.5, A=0.5, N=0.5, bpm=None)
        self.hook = "default"
        self.phase = "idle"
        self._reset_musical_state(snap=True)
        st = self.last_state
        if isinstance(st, dict) and st.get("phase") not in (None, "wipe"):
            self.set_state(st)
        self.mg_target = 1.0

    # --------------------------------------------------------------- helpers
    def _bpm_target(self):
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

    def _vgain(self, key):
        if key is None:
            return 1.0
        if key in ("vox", "breath", "rev"):
            return self._hookmod(key)
        return self.p[key] * self._hookmod(key)

    def _smooth(self):
        p = self.p
        bar_s = 240.0 / p["bpm"]
        k = self.B / float(SR)
        a1 = 1.0 - np.exp(-k / (bar_s * 0.8))
        a2 = 1.0 - np.exp(-k / (bar_s * 1.6))
        if not self.wiping:
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
        a_s = 1.0 - np.exp(-k / 0.15)               # ~150 ms slew for the phone
        for key in ("x", "y", "e", "f"):
            self.sens[key] += (self.sens_t[key] - self.sens[key]) * a_s
        # master fade: 2 s down for a wipe, 3 s back up
        step = k / (2.0 if self.mg_target < self.mg else 3.0)
        self.mg = max(self.mg - step, self.mg_target) if self.mg_target < self.mg \
            else min(self.mg + step, self.mg_target)

    # ------------------------------------------------------------ sample bank
    def _bank_keys(self):
        """section -> key; a section is rebuilt when its key changes."""
        p, s = self.p, self.seed
        I, O, E, A, N = p["I"], p["O"], p["E"], p["A"], p["N"]
        return {"k": (s, round((1.5 + 2.5 * I) * 2) / 2.0, int(p["bpm"] // 2)),
                "h": (s, round(E * 4), round(I * 4)),
                "c": (s, round(O * 4), round(A * 4)),
                "s": (s, round(A * 4), round(N * 4), round(I * 3)),
                "t": s}

    def _build_bank(self, sync=False):
        """Bring the sample bank up to date with the gliding parameters.

        sync (start, wipe, silent anyway): build now. Otherwise out-of-date
        sections are made by the helper process and swapped in at a later bar;
        until then the current samples keep playing, so render_block never
        stalls on them."""
        keys, asked, prep = self.bank_keys, self.bank_asked, self.prep
        if prep is not None and prep.broken:
            prep = self.prep = None
        if prep is not None:
            for name in ("k", "h", "c", "s", "t"):
                got = prep.take("bank:" + name)
                if got is not None and got[0][0] == self.gen:
                    self.bank.update(got[1])
                    keys[name] = got[0][1]
        p = self.p
        args = (self.seed, p["I"], p["O"], p["E"], p["A"], p["N"], p["bpm"])
        for name, key in self._bank_keys().items():
            if keys.get(name) == key:
                continue
            if sync or prep is None or name not in keys:
                self.bank.update(build_section(name, *args))
                keys[name] = key
            elif asked.get(name) != key:
                asked[name] = key
                prep.submit("bank:" + name, (self.gen, key), build_section, name, *args)

    # -------------------------------------------------------------- patterns
    def _bar_start(self):
        if self.phase != self.bar_phase:
            self.phase_bars = 0
            self.bar_phase = self.phase
        bip = self.vbar % 8
        self._build_bank()
        self._prefetch(bip)
        p, d = self.p, self.dna
        I, O, C, E, A, N = (p[k] for k in ("I", "O", "C", "E", "A", "N"))
        rng = np.random.default_rng([self.seed, self.vbar % 4096, 77])
        hm = self._hookmod
        pat = [[] for _ in range(16)]
        phase = self.phase

        def hit(s, inst, var=0, gain=1.0, pan=0.0, off=0.0):
            pat[int(s) % 16].append((inst, var, gain, pan, off))

        swing = (1.0 - C) ** 1.5 * 0.22          # low C -> swing
        jit = (1.0 - C) * 0.05

        def off_for(s):
            o = swing if s % 2 == 1 else 0.0
            return o + rng.uniform(0.0, jit)

        rev, offg, broken, heavy = hm("rev"), hm("offgrid"), hm("broken"), hm("heavy")
        rev = max(rev, self.sens["f"])                    # phone upside down -> reversed
        voxa, brth = hm("vox"), hm("breath")
        mirror_far = self.hw.get("mirror", 0) * p["hs"] > 0.5

        # --- kick
        if phase == "idle":
            if I > 0.08 and self.vbar % 2 == 0:
                hit(0, "kick_far", 0, 0.9)
                if rng.random() < O * 0.3:
                    hit(10, "kick_far", 0, 0.5)
        elif phase in ("approach", "profiling", "hook"):
            steps = (0, 8) if (phase == "approach" and self.phase_bars < 2) else (0, 4, 8, 12)
            if rng.random() < broken * 0.8:
                steps = d.broken_kick
            elif O > 0.7 and rng.random() < 0.15 * O:
                steps = (0, 4, 8, 11, 14)
            for s in steps:
                if mirror_far:
                    hit(s, "kick_far", 0, 0.6)
                    continue
                v = 2 if rng.random() < heavy else 0
                hit(s, "kick", v, 1.0)
                if s % 4 == 0:
                    hit(s, "rumble", 0, 1.0)
            if rng.random() < (1 - C) * 0.35 * I:
                hit(int(rng.choice([7, 14, 15])), "kick", 1, 0.45, 0, off_for(1))

        # --- hats (E: more of them; C: tight vs swung/ghosted; inverted: off-grid/reversed)
        if p["hat"] * hm("hat") > 0.03:
            prob16 = clamp(E * 1.1 * I + 0.1 - 0.2)
            for s in range(16):
                o = off_for(s) + (rng.uniform(0.15, 0.5) if rng.random() < offg else 0.0)
                inst = "hat"
                if s % 4 == 2:
                    hit(s, inst, int(rng.integers(2)), 0.9 * (0.6 + 0.4 * d.hat_acc[s]), 0.0, o)
                elif rng.random() < prob16:
                    hit(s, inst, int(rng.integers(3)), 0.3 + 0.35 * d.hat_acc[s],
                        rng.uniform(-0.3, 0.3) * (0.3 + O), o)
                elif rng.random() < (1 - C) * 0.25:
                    hit(s, inst, 1, 0.15, rng.uniform(-0.5, 0.5), o)
            if rng.random() < N * 0.4 + E * 0.15:      # ratchet roll
                s = int(rng.integers(12, 16))
                k = int(rng.choice([2, 3, 4]))
                for j in range(k):
                    hit(s, "hat", 2, 0.25 + 0.4 * (1 - j / k), 0.0, j / float(k))
        if E > 0.4 and p["ohat"] > 0.03:
            for s in ((2, 6, 10, 14) if E > 0.75 else (2, 10)):
                if rng.random() < 0.8:
                    hit(s, "ohat", 0, 0.5 + 0.5 * E, 0.0, off_for(s))
        # --- claps (E)
        if p["clap"] > 0.03:
            if E > 0.35:
                for s in (4, 12):
                    hit(s, "clap", 0, 0.4 + 0.6 * E)
                    if C < 0.4:
                        hit(s, "clap", 1, 0.35, 0.2, 0.06 + 0.1 * (0.4 - C))
            elif self.vbar % 2 == 1:
                hit(12, "clap", 1, 0.5)
        # --- clank (O: 3-over-4 / odd polyrhythm; C: regular vs dropouts)
        if p["clank"] > 0.03:
            if O < 0.45:
                cs = d.clank_fixed
            else:
                period = 3 if O < 0.8 else d.odd_period
                cs = [s for s in range(16) if (self.vbar * 16 + s) % period == 0]
            for i, s in enumerate(cs):
                if rng.random() < 0.6 + 0.4 * C:
                    var = int(rng.integers(6)) if rng.random() < 0.3 + 0.7 * O else i % 2
                    inst = "clank_r" if rng.random() < rev * 0.6 else "clank"
                    hit(s, inst, var, (0.55 + 0.45 * O) * rng.uniform(0.7, 1.0), d.pans[i % 8], off_for(s))
        # --- harsh metal (low A)
        if p["metal"] > 0.03:
            for _ in range(int(rng.poisson((1.0 - A) * 2.2 * (0.3 + I)))):
                hit(int(rng.integers(16)), "metal", int(rng.integers(3)), (1.0 - A), rng.uniform(-0.8, 0.8))
        # --- data ticks
        if p["click"] > 0.03:
            dens = 0.25 + 0.5 * I + 0.2 * N
            for s in range(16):
                if C > 0.6:
                    play, k = bool(d.click_mask[s]), int(d.click_div[s])
                else:
                    play = rng.random() < dens
                    k = int(rng.choice([1, 2, 3, 4, 6], p=[0.4 - 0.2 * N, 0.25, 0.15, 0.1 + 0.1 * N, 0.1 + 0.1 * N]))
                if play:
                    for j in range(k):
                        hit(s, "tick", int(rng.integers(8)), 0.3 + 0.5 * rng.random(),
                            rng.uniform(-0.9, 0.9), j / float(k))
        # --- stabs (A: chord vs cluster, tuned to the visitor root)
        if p["stab"] > 0.03:
            sst = list(d.stab_steps)
            if phase == "release":
                sst = sst[:1] if self.vbar % 2 == 0 else []
            if rng.random() < O * 0.5 and sst:
                i = int(rng.integers(len(sst)))
                sst[i] = (sst[i] + int(rng.choice([-1, 1]))) % 16
            for s in sst:
                inst = "stab_r" if rng.random() < rev * 0.5 else "stab"
                hit(s, inst, self.vbar % 3, 1.0, rng.uniform(-0.4, 0.4), off_for(s))
        # --- hook extras
        if voxa > 0.05:     # scrawl: chopped spoken fragments
            for _ in range(int(rng.poisson(3.0 * voxa))):
                s = int(rng.integers(16))
                var = int(rng.integers(8))
                k = int(rng.choice([1, 1, 2, 3, 4]))
                for j in range(k):
                    hit(s, "vox", var, voxa * (1.0 - 0.15 * j), rng.uniform(-0.6, 0.6), j * 0.5)
        if brth > 0.05 and self.vbar % 2 == 0:   # mirror: breathing close to the ear
            hit(0, "breath", 0, brth, -0.2)
            hit(8, "breath", 1, brth * 0.8, 0.2)
        if rev > 0.2 and rng.random() < rev * 0.7 and (p["hs"] > 0.2 or self.sens["f"] > 0.5):  # inverted: swell into the next bar
            n = len(self.bank["swell"][self.vbar % 2])
            hit(0, "swell", self.vbar % 2, 1.0, 0.0, 16.0 - n / self.sps())
        # --- phrase structure: risers (N), impacts
        if self.phase_bars == 0 and phase in ("hook", "release") and self.vbar > 0:
            hit(0, "impact", 0, 1.0 if phase == "hook" else 0.6)
        elif bip == 0 and self.riser_due:
            hit(0, "impact", 0, 0.7)
        self.riser_due = False
        if bip == 4 and p["riser"] * hm("riser") > 0.1 and rng.random() < 0.25 + 0.75 * N:
            hit(0, "riser", 0, 1.0)
            self.riser_due = True
        # --- glitch stutters (N)
        g = N * I * 1.1 * p["glitch"] * hm("glitch")
        if rng.random() < g:
            s = int(rng.choice([12, 13, 14, 15, int(rng.integers(16))]))
            hit(s, "stutter", (int(rng.choice([1, 2, 4])), int(rng.choice([2, 4, 8, 16]))))
            if g > 1.0 and rng.random() < g - 1.0:
                hit(int(rng.integers(4, 12)), "stutter", (1, int(rng.choice([4, 8]))))
        self.pattern = pat

    def _add(self, bus, sig, at, gain):
        R, M = self.R, self.M
        n = len(sig) if sig.ndim == 1 else sig.shape[1]
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
            bus[i:j] += gain * sig[:k]
            if k < n:
                bus[:n - k] += gain * sig[k:]

    def _play_step(self, s, t):
        sps = self.sps()
        p = self.p
        perc = (0.5 + 0.5 * p["I"]) * (0.8 + 0.4 * p["E"]) * (1.0 + 0.25 * self.sens["y"])
        for inst, var, gain, pan, off in self.pattern[s]:
            at = int(t + off * sps)
            if inst == "stutter":
                nst, div = var
                self.stutters.append([at, at + int(nst * sps), max(64, int(sps / div)), None])
                continue
            if inst == "riser":
                got = self.prep.take("riser", (self.gen, self.vbar)) if self.prep is not None else None
                if got is not None:
                    sig = got[1]          # made a bar ahead by _prefetch
                else:
                    sig = _riser(self.seed, self.vbar, int(min(8.5 * SR, 64 * sps)), p["N"], sps / 2.0)
                g = 0.3 * self.p["riser"] * self._hookmod("riser")
                self._add(self.fx, sig, at, (g, g))
                self._add(self.vsend, sig[0], at, g * 0.3)
                continue
            base = inst[:-2] if inst.endswith("_r") else inst
            key, lvl, dry, vs, ds = INST[base]
            g = gain * lvl * self._vgain(key)
            if base in PERC:
                g *= perc
            if g < 1e-4:
                continue
            bank = self.bank[inst]
            sig = bank[var % len(bank)]
            if base in PERC or base in ("stab", "kick_far"):
                pan = pan + 0.7 * self.sens["x"]          # phone left/right moves the hits
            a = (clamp(pan, -1.0, 1.0) + 1.0) * np.pi / 4.0
            self._add(self.syn if base == "stab" else self.dry, sig, at, (g * dry * np.cos(a) * 1.414, g * dry * np.sin(a) * 1.414))
            vmul = p["verb"] * 2.0 * self._hookmod("verb") * (1.0 + 0.6 * self.sens["y"])
            if vs > 0:
                self._add(self.vsend, sig, at, g * vs * vmul)
            if ds > 0:
                self._add(self.dsend, sig, at, g * ds)
            if base == "kick" and inst == "kick":
                n = min(len(sig), int(sps * 3))
                u = np.arange(n) / float(n)
                self._add(self.duck, (np.exp(-u * 3.0) * np.clip(u * 60, 0, 1)).astype(np.float32),
                          at, min(1.0, g))

    # ------------------------------------------------------------- continuous
    def _drone(self):
        B, p = self.B, self.p
        target = p["drone"] * self._hookmod("drone") * self.mg_target_ok()
        sub_t = (0.3 + 0.7 * p["drone"]) * self._hookmod("sub") * (1.0 if self.phase != "wipe" else 0.0)
        g0 = self.drone_g
        self.drone_g = target
        s0 = getattr(self, "sub_g", 0.0)
        self.sub_g = sub_t
        if max(g0, target, s0, sub_t) < 1e-4:
            return None
        A, N, O, I = p["A"], p["N"], p["O"], p["I"]
        self.lfo = (self.lfo + B / SR * 0.07) % 1.0
        self.lfo2 = (self.lfo2 + B / SR * 0.31) % 1.0
        br = 0.5 + 0.5 * np.sin(TWO_PI * self.lfo)
        breath = 1.0 - p["breath"] * 0.6 * (1.0 - br)
        det = (4.0 + 30.0 * N) / 100.0
        wob = N * 0.12 * np.sin(TWO_PI * self.lfo2)
        iv = np.concatenate([_CONS, _CONS, _DISS, _DISS])
        sg = np.concatenate([np.full(5, -1.0), np.full(5, 1.0), np.full(5, -1.0), np.full(5, 1.0)])
        wa = clamp(A) ** 1.3
        w = np.concatenate([np.full(10, wa), np.full(10, 1.0 - wa)]) / 7.0
        f = midi_hz(self.dna.root + iv + sg * det + wob)
        dt = f / SR
        on = w > 0.015                       # skip inaudible voices (saves CPU)
        on &= max(g0, target) > 1e-4
        pan = np.tile(np.array([-0.6, 0.6, -0.3, 0.3, 0.0]), 4) * sg
        a = (pan + 1.0) * np.pi / 4.0
        if on.any():
            d = dt[on][:, None]
            ph = (self.drone_ph[on][:, None] + d * (self.ar + 1)) % 1.0
            s = saw_blep(ph, d)
            wo, ao = w[on], a[on]
            x = np.stack([(wo * np.cos(ao)) @ s, (wo * np.sin(ao)) @ s])
        else:
            x = np.zeros((2, B))
        self.drone_ph = (self.drone_ph + dt * B) % 1.0
        fc = 90.0 + (250.0 + 1600.0 * I * p["open"] + 600.0 * O) * (1.0 - 0.5 * p["breath"] * (1.0 - br))
        fc *= 2.0 ** (1.0 * self.sens["y"] + 0.6 * self.sens["x"])
        c = lp_coef(fc)
        x = self.dlp2.process(self.dlp1.process(x, c), c)
        x = np.tanh(x * (1.0 + N)) / (1.0 + 0.5 * N)
        ramp = (g0 + (target - g0) * (self.ar / B)) * breath
        x *= ramp
        fs = float(midi_hz(self.dna.root))
        sph = self.sub_ph + TWO_PI * fs / SR * (self.ar + 1)
        self.sub_ph = float(sph[-1] % TWO_PI)
        x += 0.2 * (s0 + (sub_t - s0) * (self.ar / B)) * breath * np.sin(sph)
        return x

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
            got = self.prep.take("shake", None) if self.prep is not None else None
            if got is not None and got[0][0] == self.gen:
                sig = got[1]              # made ahead by _prefetch; a new one is ordered next bar
            else:
                rng = np.random.default_rng([self.seed, b0 & 0xFFFFFF, 11])
                sig = V.riser(rng, int(16 * sps), tension=0.6, sps=sps / 2.0)
            g = 0.22 * e
            self._add(self.dry, sig, b0 + self.B, (g, g))
            self.shake_cool = int(16 * sps / self.B)   # at most once per bar

    def _prefetch(self, bip):
        """At a bar start: order the noise risers that may be needed soon, so
        render_block never makes one itself (an 8 s riser costs ~120 ms on x86)."""
        prep = self.prep
        if prep is None:
            return
        sps = self.sps()
        if bip == 3 and self.p["riser"] * self._hookmod("riser") > 0.05:
            n = int(min(8.5 * SR, 64 * sps))
            prep.submit("riser", (self.gen, self.vbar + 1), _riser, self.seed, self.vbar + 1, n, self.p["N"], sps / 2.0)
        if not prep.has("shake") and self.phase in ("approach", "profiling", "hook"):
            prep.submit("shake", (self.gen, self.vbar), _riser, self.seed, self.vbar & 0xFFFFFF,
                        int(16 * sps), 0.6, sps / 2.0, 11)

    def mg_target_ok(self):
        return 1.0

    # ----------------------------------------------------------------- master
    def _stutter(self, x, b0):
        B, H = self.B, self.H
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
        self.hist = np.concatenate([self.hist[:, B:], x], axis=1)
        return x

    def render_block(self):
        """Render the next block. Returns int16 array of shape (B, 2)."""
        B = self.B
        b0 = self.pos
        b1 = b0 + B
        if self.prep is not None:
            self.prep.poll()
        self._smooth()
        p = self.p
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
            self.next_step_at += self.sps()

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

        g0 = self.fx_g
        self.fx_g = p["riser"] * self._hookmod("riser")
        mix = dry + fx * (g0 + (self.fx_g - g0) * (self.ar / B))
        duckg = 1.0 - 0.6 * np.clip(duck, 0.0, 1.0)
        sx, sy = self.sens["x"], self.sens["y"]
        cs = lp_coef(clamp(2200.0 * 2.0 ** (2.2 * sy + 0.8 * sx), 150.0, 16000.0))
        mix += self.slp2.process(self.slp1.process(syn, cs), cs)

        drone = self._drone()
        vin = np.stack([vs, vs])
        if drone is not None:
            mix += drone * duckg
            vin += drone * (0.25 * p["verb"])
        fb = clamp(p["vfb"], 0.0, 0.97)
        wet = self.reverb.process(vin, fb, 2500.0 + 3000.0 * p["open"])
        mix += wet * (0.9 + 0.1 * duckg)
        D = int(round(3 * self.sps()))
        mix += 0.4 * self.delay.process(ds, D, 0.35 + 0.35 * p["verb"], 1800.0 + 2000.0 * p["E"])

        # master: DC block, drive (intensity, low A), filter (openness), stutter, limiter
        mix -= self.dc.process(mix, lp_coef(18.0))
        drv = 1.0 + 0.9 * p["I"] + 0.5 * (1.0 - p["A"])     # gentle glue, harsher when low A
        mix = np.tanh(mix * (0.8 * drv)) / (0.8 * drv) * (1.0 + 0.2 * (drv - 1.0))
        op = clamp(p["open"] * self._hookmod("open") * (0.55 + 0.45 * p["I"]) * (0.8 + 0.3 * p["E"]))
        op = clamp(op * (1.0 + 0.45 * self.sens["y"]))    # phone forward = brighter mix
        c = lp_coef(250.0 + 17500.0 * op * op)
        mix = self.mlp2.process(self.mlp1.process(mix, c), c)
        mix = self._stutter(mix, b0)

        gain = self.volume * p["level"]
        mg0 = getattr(self, "_mg_prev", self.mg)
        mix *= gain * (mg0 + (self.mg - mg0) * (self.ar / B))
        self._mg_prev = self.mg
        if self.wiping and self.mg <= 0.0:
            self._finish_wipe()

        peak = float(np.max(np.abs(mix))) + 1e-9
        tg = min(1.0, 0.89 / peak)
        g_prev = self.limg
        self.limg = tg if tg < g_prev else g_prev + (tg - g_prev) * 0.02
        mix *= g_prev + (self.limg - g_prev) * (self.ar / B)
        ax = np.abs(mix)
        over = ax > 0.8
        if over.any():
            mix[over] = np.sign(mix[over]) * (0.8 + 0.17 * np.tanh((ax[over] - 0.8) / 0.17))
        self.pos = b1
        return (mix.T * 32767.0).astype(np.int16)

    def close(self):
        """Stop the helper process (the audio worker calls this on stop)."""
        if self.prep is not None:
            self.prep.close()
            self.prep = None

    def silence(self):
        return np.zeros((self.B, 2), np.int16)
