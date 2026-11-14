"""Composition layer: the part that makes hours of sound feel like a DJ set.

Three time scales sit above the bar-level drum patterns in synth.py:

SetClock   the room's slow clock (minutes to hours). It drifts the key and
           mode, the idle tempo, the drum kit, an "energy" macro, the room
           size and the amount of grit. It keeps running across visitors;
           only idle uses its key, tempo and kit directly.
Arranger   sections of 8 to 32 bars (ambient, pulse, dub, intro, build,
           predrop, drop, peak, break, outro), picked from the show phase,
           the intensity and the visitor's profile. It decides which layers
           play, where the fills go (snare rolls, tom runs, kick drop-outs,
           reverse swells, stutters, dub echo throws), the master filter
           sweeps, the long tension noise before a drop, the chord changes,
           and which "groove" (set of pattern dice) the bar uses.
Dice       stable random numbers for one groove: patterns are re-evaluated
           every bar against the current intensity and OCEAN values, but the
           dice stay the same for the whole phrase, so the groove repeats
           like real techno (with more or fewer hits as things change)
           instead of being re-rolled at random every bar.
"""
import zlib

import numpy as np

# scales (semitones above the root), all dark
MODES = {
    "aeolian":  (0, 2, 3, 5, 7, 8, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "dorian":   (0, 2, 3, 5, 7, 9, 10),
    "locrian":  (0, 1, 3, 5, 6, 8, 10),
    "harmonic": (0, 2, 3, 5, 7, 8, 11),
}
MODE_NAMES = tuple(MODES)
# chord-root progressions (semitones above the tonic), per mode, for drones,
# stabs and bass. Peaks mostly sit on the tonic; breaks and idle wander.
PROGRESSIONS = {
    "aeolian":  ((0,), (0, 8), (0, 5), (0, 10, 8, 10), (0, 3, 8, 7), (0, 0, 8, 10)),
    "phrygian": ((0,), (0, 1), (0, 1, 0, 10), (0, 8, 1, 0)),
    "dorian":   ((0,), (0, 10), (0, 5), (0, 3, 10, 5)),
    "locrian":  ((0,), (0, 1), (0, 6, 1, 0)),
    "harmonic": ((0,), (0, 8), (0, 7), (0, 8, 7, 0)),
}

# Drum kits: kick family, hat flavour (brightness, metal), snare kind,
# whether claps or snares carry the backbeat, and ride usage.
KITS = (
    dict(name="concrete", kick="boom",   bright=0.35, metal=0.35, snare="noise",      clap=0.7, ride=0.4),
    dict(name="steel",    kick="hard",   bright=0.6,  metal=0.75, snare="industrial", clap=0.3, ride=0.7),
    dict(name="bunker",   kick="punch",  bright=0.5,  metal=0.45, snare="rim",        clap=0.8, ride=0.3),
    dict(name="machine",  kick="nine",   bright=0.7,  metal=0.3,  snare="industrial", clap=0.6, ride=0.6),
    dict(name="tunnel",   kick="tunnel", bright=0.25, metal=0.6,  snare="noise",      clap=0.4, ride=0.5),
)


def _h(*parts):
    return zlib.crc32(repr(parts).encode("utf-8")) & 0x7FFFFFFF


class Dice:
    """Named, stable random arrays for one groove (seeded, order independent)."""

    def __init__(self, *seed):
        self.seed = [int(s) & 0x7FFFFFFF for s in seed]
        self.cache = {}

    def u(self, name, n=16):
        k = (name, n)
        v = self.cache.get(k)
        if v is None:
            v = np.random.default_rng(self.seed + [_h(name)]).random(n)
            self.cache[k] = v
        return v

    def pick(self, name, options):
        return options[int(self.u(name, 1)[0] * len(options)) % len(options)]


class SetClock:
    """The room's slow clock: drifts key, mode, idle tempo, kit and macros."""

    def __init__(self, seed):
        self.rng = np.random.default_rng([int(seed) & 0x7FFFFFFF, 9001])
        r = self.rng
        self.bar = 0
        self.root = 28 + int(r.integers(0, 8))          # E1..B1
        self.mode = str(r.choice(["aeolian", "phrygian", "aeolian", "dorian"]))
        self.bpm_center = float(r.uniform(124.0, 130.0))
        self.bpm = self.bpm_center
        self.kit = int(r.integers(len(KITS)))
        self.epoch = 0
        self.energy = float(r.uniform(0.3, 0.6))
        self.energy_t = self.energy
        self.room = float(r.uniform(0.4, 0.7))
        self.room_t = self.room
        self.grit = float(r.uniform(0.3, 0.6))
        self.grit_t = self.grit
        self.pending_key = None
        self.next_key = int(r.integers(64, 128))
        self.next_kit = int(r.integers(320, 640))
        self.next_tempo = int(r.integers(96, 192))
        self.next_macro = 32

    def advance(self, idle):
        """Call once per bar. Returns a list of event names (for logging)."""
        r = self.rng
        self.bar += 1
        ev = []
        if self.bar >= self.next_macro:
            self.next_macro = self.bar + int(r.integers(24, 72))
            self.energy_t = float(np.clip(self.energy_t + r.normal(0, 0.25), 0.05, 0.95))
            self.room_t = float(np.clip(self.room_t + r.normal(0, 0.2), 0.15, 0.95))
            self.grit_t = float(np.clip(self.grit_t + r.normal(0, 0.2), 0.1, 0.9))
        k = 1.0 / 24.0
        self.energy += (self.energy_t - self.energy) * k
        self.room += (self.room_t - self.room) * k
        self.grit += (self.grit_t - self.grit) * k
        if self.bar >= self.next_tempo:
            self.next_tempo = self.bar + int(r.integers(96, 256))
            self.bpm_center = float(np.clip(self.bpm_center + r.normal(0, 3.0), 121.0, 136.0))
            ev.append("tempo")
        self.bpm += (self.bpm_center - self.bpm) * (1.0 / 48.0)
        if self.bar >= self.next_key and self.pending_key is None:
            self.next_key = self.bar + int(r.integers(80, 200))
            # move by a fourth/fifth/tone; the key's root must stay E1..B1 (28..35)
            # so the kick and the sub stay in their sweet spot
            moves = [int(m) for m in r.permutation([5, -5, 7, -7, 2, -2, 3, -3, 0])]
            root = self.root
            for mv in moves:
                cand = 28 + (self.root + mv - 28) % 12
                if cand <= 35:
                    root, move = cand, mv
                    break
            else:
                move = 0
            if move in (0, 2, -2) or r.random() < 0.3:
                mode = str(r.choice(MODE_NAMES, p=[0.35, 0.25, 0.15, 0.1, 0.15]))
            else:
                mode = self.mode
            self.pending_key = (root, mode)
            ev.append("key")
        if self.bar >= self.next_kit and idle:
            self.next_kit = self.bar + int(r.integers(320, 700))
            self.kit = (self.kit + int(r.integers(1, len(KITS)))) % len(KITS)
            self.epoch += 1
            ev.append("kit")
        return ev

    def apply_key(self):
        if self.pending_key:
            self.root, self.mode = self.pending_key
            self.pending_key = None
            return True
        return False


# Layers: multipliers on the phase-table levels for each voice group.
_LAYER_KEYS = ("kick", "far", "rumble", "hat", "ohat", "ride", "clap", "snare", "clank", "metal",
               "click", "stab", "bass", "drone", "vox", "breath", "tension")
_SECTIONS = {
    #          kick far  rumb hat  ohat ride clap snr  clnk metl clik stab bass dron vox  brth tens
    "silence": (0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0),
    "ambient": (0,   0,   0,   0,   0,   0,   0,   0,   0.6, 0.7, 0.5, 0,   0,   1.1, 0,   0.3, 0),
    "pulse":   (0,   1.0, 0,   0.35, 0,  0,   0,   0,   0.4, 0.4, 0.7, 0,   0,   0.85, 0,  0,   0),
    "dub":     (0,   0.5, 0,   0.2, 0,   0,   0,   0,   0.3, 0.2, 0.5, 1.0, 0,   0.9, 0,   0,   0),
    "intro":   (1.0, 0,   0.6, 0.55, 0,  0,   0,   0,   0.6, 0.5, 0.8, 0.3, 0.45, 0.85, 0.5, 1,  0.3),
    "build":   (1.0, 0,   0.6, 1.0, 0.5, 0,  0.6, 0.5, 0.9, 0.7, 1.0, 0.6, 0.7, 0.6, 0.8, 1,   1.0),
    "predrop": (0,   0,   0,   1.0, 0.6, 0,   0,   1.0, 0.5, 0.3, 1.0, 0.4, 0.3, 0.5, 1.0, 1,   1.0),
    "drop":    (1.0, 0,   1.0, 1.0, 1.0, 0.7, 1.0, 0.6, 1.0, 1.0, 0.7, 1.0, 1.0, 0.45, 1.0, 1,  0),
    "peak":    (1.0, 0,   1.0, 1.0, 1.0, 1.0, 1.0, 0.6, 1.0, 1.0, 1.0, 1.0, 1.0, 0.45, 1.0, 1,  0),
    "break":   (0,   0,   0,   0.4, 0,   0,   0,   0,   0.6, 0.5, 0.6, 1.0, 0.35, 1.0, 0.6, 1,  0.4),
    "afterglow": (0, 0.8, 0,   0.2, 0,   0,   0,   0,   0.45, 0.35, 0.45, 1.0, 0.3, 1.1, 0.4, 1,  0),
    "outro":   (0,   0,   0,   0.25, 0,  0,   0,   0,   0.4, 0.3, 0.3, 0.8, 0.2, 1.2, 0.3, 1,   0),
}
SECTIONS = {k: dict(zip(_LAYER_KEYS, v)) for k, v in _SECTIONS.items()}
ROTATABLE = ("clank", "stab", "ohat", "click", "metal", "ride", "clap", "bass", "hat")


class BarPlan:
    __slots__ = ("section", "bis", "slen", "layers", "fill", "kick_from", "drop", "hp", "lp",
                 "q", "riser", "groove", "loop", "chord", "throw", "tension", "first",
                 "half_kick", "hat_style", "phrase", "rotated")

    def __repr__(self):
        return "<%s %d/%d fill=%s chord=%d groove=%d>" % (self.section, self.bis, self.slen,
                                                          self.fill, self.chord, self.groove)


class Arranger:
    """Chooses sections, fills, sweeps and chords bar by bar."""

    def __init__(self, seed):
        self.seed = int(seed) & 0x7FFFFFFF
        self.reset(seed)

    def reset(self, seed=None):
        if seed is not None:
            self.seed = int(seed) & 0x7FFFFFFF
        self.section = None
        self.bis = 0
        self.slen = 0
        self.nsec = 0
        self.groove = 0
        self.phase = None
        self.prog = (0,)
        self.prog_i = 0
        self.tension_bars = 0
        self.hook_bars = 0
        self.prev_hp = 20.0
        self.queue = []
        self.salt = 0

    def new_identity(self, seed):
        """A new visitor (or the room's next motif): restart the counters that
        seed sections and grooves, so the same visitor always gets the same
        arrangement whatever happened before they arrived."""
        self.seed = int(seed) & 0x7FFFFFFF
        self.nsec = 0
        self.groove = 0
        self.tension_bars = 0
        self.hook_bars = 0

    def _rng(self, *k):
        return np.random.default_rng([self.seed, self.nsec, self.bis, self.salt] + [int(x) for x in k])

    def _start(self, name, length, rng, mode):
        self.section = name
        self.slen = int(length)
        self.bis = 0
        self.nsec += 1
        self.groove += 1
        progs = PROGRESSIONS.get(mode, PROGRESSIONS["aeolian"])
        if name in ("peak", "drop", "intro", "predrop"):
            self.prog = progs[0] if rng.random() < 0.75 else progs[int(rng.integers(len(progs)))]
        elif name in ("build",):
            self.prog = progs[int(rng.integers(len(progs)))] if rng.random() < 0.5 else (0,)
        elif name == "silence":
            self.prog = (0,)
        else:
            self.prog = progs[int(rng.integers(1, len(progs)))] if len(progs) > 1 else progs[0]
        self.prog_i = 0

    def _next_idle(self, rng, clock, I):
        e = clock.energy if clock else 0.5
        w = np.array([0.45 * (1.2 - e), 0.15 + 0.6 * e * (0.5 + I), 0.25])
        w /= w.sum()
        name = ("ambient", "pulse", "dub")[int(rng.choice(3, p=w))]
        if name == self.section and rng.random() < 0.6:
            name = ("ambient", "pulse", "dub")[int(rng.choice(3, p=w))]
        return name, int(rng.choice([16, 32, 32]))

    def plan(self, phase, I, oc, hook, clock, mode, phase_bars, hookw, slam=False):
        """Called on every bar start. Returns a BarPlan. slam=True forces a
        drop on this bar (the end of a 'hinge' held breath)."""
        O, C, E, A, N = (oc[k] for k in "OCEAN")
        # idle choices also follow the room's clock, so idle never replays itself;
        # a visit depends only on the visitor (same visitor -> same arrangement)
        self.salt = (clock.bar if clock else 0) if phase in ("idle", "wipe") else 0
        rng = self._rng(17)
        changed = phase != self.phase
        prev_phase = self.phase
        self.phase = phase
        if slam:
            changed = False
            self.queue = []
            self._start("drop", 8, rng, mode)
        # ------------------------------------------------ section choice
        if phase == "wipe":
            if self.section != "silence":
                self._start("silence", 4, rng, mode)
        elif changed:
            self.queue = []
            if phase == "idle":
                n, L = self._next_idle(rng, clock, I)
                self._start(n, L, rng, mode)
            elif phase == "approach":
                self._start("intro", 16, rng, mode)
            elif phase == "profiling":
                self.tension_bars = 0
                self._start("build", 8, rng, mode)
            elif phase == "hook":
                self.hook_bars = 0
                if prev_phase in ("profiling", "approach", "idle", None) or self.section in ("build", "intro", "break"):
                    self._start("predrop", 1, rng, mode)
                    self.queue = [("drop", 8)]
                else:
                    self._start("drop", 8, rng, mode)
            elif phase == "release":
                # ~50 s: breakdown -> dub afterglow with a heartbeat kick -> dissolving outro
                self._start("break", 8, rng, mode)
                self.queue = [("afterglow", 8), ("outro", 16)]
        elif self.bis >= self.slen:
            if self.queue:
                n, L = self.queue.pop(0)
                self._start(n, L, rng, mode)
            elif phase == "idle":
                n, L = self._next_idle(rng, clock, I)
                self._start(n, L, rng, mode)
            elif phase == "approach":
                self._start("intro", 16, rng, mode)
            elif phase == "profiling":
                self._start("build", 8, rng, mode)
            elif phase == "hook":
                if self.section in ("drop", "peak"):
                    brk = I < 0.9 and rng.random() < 0.35 + 0.3 * (1.0 - I) and self.hook_bars > 24
                    if brk:
                        self._start("break", 8, rng, mode)
                        self.queue = [("predrop", 1), ("drop", 8)]
                    else:
                        self._start("peak", int(rng.choice([16, 16, 32])), rng, mode)
                else:
                    self._start("peak", 16, rng, mode)
            elif phase == "release":
                self._start("outro", 16, rng, mode)
            else:
                self._start("silence", 4, rng, mode)
        sec = self.section or "ambient"
        bis, slen = self.bis, self.slen
        rng = self._rng(23)

        pl = BarPlan()
        pl.section, pl.bis, pl.slen = sec, bis, slen
        pl.first = bis == 0
        pl.layers = dict(SECTIONS[sec])
        pl.phrase = bis // 8
        pl.rotated = ()
        # groove: new dice per 8-bar phrase in long sections
        pl.groove = self.groove * 16 + (bis // 8 if sec in ("peak", "ambient", "pulse", "dub", "build") else 0)
        if self.salt:
            pl.groove += 7919 * (self.salt // 32)
        pl.loop = 1 if C > 0.7 else (2 if C > 0.35 else 4)
        pl.half_kick = sec == "intro" and bis < 4
        pl.hat_style = None
        # ------------------------------------------------ chords
        if sec in ("peak", "drop"):
            per = 8
        elif sec in ("ambient", "dub", "outro", "break", "afterglow"):
            per = 4 if sec == "break" else 8
        else:
            per = 4
        if bis % per == 0 and bis > 0:
            self.prog_i += 1
        pl.chord = int(self.prog[self.prog_i % len(self.prog)])
        # ------------------------------------------------ layer rotation (peaks)
        if sec == "peak":
            rr = np.random.default_rng([self.seed, self.nsec, bis // 8, 31])
            k = 1 + int(rr.random() < 0.5)
            cand = list(ROTATABLE)
            out = tuple(cand[i] for i in rr.choice(len(cand), size=k, replace=False))
            for v in out:
                pl.layers[v] *= 0.15 if v != "hat" else 0.55
            spot = cand[int(rr.integers(len(cand)))]
            if spot not in out:
                pl.layers[spot] *= 1.2
            pl.rotated = out
            pl.hat_style = int(rr.integers(4))
        if sec == "build":
            # each successive build phrase adds pressure
            self.tension_bars += 1
            tb = self.tension_bars
            pl.layers["ohat"] *= min(1.0, tb / 16.0)
            pl.layers["clap"] *= min(1.0, tb / 12.0)
            pl.layers["snare"] *= min(1.0, tb / 16.0)
        if sec in ("drop", "peak"):
            self.hook_bars += 1
        # ------------------------------------------------ fills
        last = bis == slen - 1
        phrase_end = (bis % 8 == 7) or last
        pl.fill = None
        pl.kick_from = 16
        pl.throw = False
        pl.drop = (sec == "drop" and bis == 0)
        nxt = self.queue[0][0] if (last and self.queue) else None
        if sec == "predrop":
            pl.fill = "roll"
            pl.kick_from = 0
        elif last and nxt in ("drop", "predrop"):
            pl.fill = "roll"
            pl.kick_from = 8
        elif phrase_end and sec in ("intro", "build", "drop", "peak", "break", "dub", "pulse", "afterglow"):
            big = last or bis % 16 == 15
            opts = ["none", "kick_beat", "flam", "tom", "stutter", "swell", "throw", "hatonly"]
            w = np.array([
                0.25 + 0.6 * C,                       # none
                0.6,                                  # kick out on the last beat
                0.4 + 0.3 * E,                        # snare flam
                0.2 + 0.6 * O,                        # tom run
                0.1 + 0.9 * N + 1.0 * hookw.get("scrawl", 0.0),
                0.2 + 1.2 * hookw.get("inverted", 0.0) + 0.3 * O,
                0.3 + 0.4 * A,                        # dub echo throw
                0.15 + 0.3 * E,
            ])
            if big:
                opts += ["roll_half", "kick_bar"]
                w = np.concatenate([w * 0.6, [0.5 + 0.5 * E, 0.4]])
            if sec in ("dub", "pulse", "break", "afterglow"):
                keep = {"none", "throw", "swell", "stutter"}
                w = np.array([wi if o in keep else 0.0 for o, wi in zip(opts, w)])
            w = w / w.sum()
            f = opts[int(rng.choice(len(opts), p=w))]
            pl.fill = None if f == "none" else f
            if f == "kick_beat":
                pl.kick_from = 12
            elif f == "kick_bar":
                pl.kick_from = 0
            elif f == "roll_half":
                pl.kick_from = 12
            elif f == "throw":
                pl.throw = True
        # ------------------------------------------------ sweeps and tension
        u0, u1 = bis / max(1, slen), (bis + 1) / max(1, slen)
        pl.q = 0.9
        pl.hp = (20.0, 20.0)
        pl.lp = (1.0, 1.0)
        pl.tension = (0.0, 0.0)
        pl.riser = False
        if sec == "build":
            tb = self.tension_bars
            h0 = 20.0 * 2.0 ** min(3.0, (tb - 1) / 10.0)
            h1 = 20.0 * 2.0 ** min(3.0, tb / 10.0)
            pl.hp = (h0, h1)
            pl.q = 1.4
            t0 = min(1.0, (tb - 1) / 14.0)
            pl.tension = (t0, min(1.0, tb / 14.0))
            pl.riser = (bis % 8 == 4) and rng.random() < 0.3 + 0.5 * N
        elif sec == "predrop":
            pl.hp = (max(40.0, self.prev_hp), 520.0)
            pl.q = 3.2
            pl.tension = (0.8, 1.0)
        elif last and nxt in ("drop", "predrop"):
            pl.hp = (20.0, 260.0)
            pl.q = 2.5
            pl.tension = (0.4, 0.8)
        elif sec == "break":
            pl.lp = (0.35 + 0.45 * u0 ** 2, 0.35 + 0.45 * u1 ** 2)
            pl.q = 2.2
            pl.tension = (0.5 * u0, 0.5 * u1)
        elif sec == "outro":
            pl.lp = (1.0 - 0.6 * u0, 1.0 - 0.6 * u1)
            pl.q = 1.6
        elif sec == "afterglow":
            w = 0.5 + 0.5 * np.sin(np.pi * (bis + 0.5) / max(1, slen))
            pl.lp = (0.55 + 0.3 * w, 0.55 + 0.3 * w)
            pl.q = 2.6
        elif sec == "intro" and bis < 8:
            pl.lp = (0.45 + 0.07 * bis, 0.45 + 0.07 * (bis + 1))
            pl.q = 1.8
        elif sec in ("peak",) and bis % 16 >= 12 and bis % 32 >= 28 and rng.random() < 0.5:
            pl.hp = (20.0 * 2 ** ((bis % 4) * 0.6), 20.0 * 2 ** ((bis % 4 + 1) * 0.6))   # 4-bar wash-out
            pl.q = 1.8
        self.prev_hp = pl.hp[1]
        if phase == "hook" and sec in ("drop", "peak") and pl.fill is None and bis % 32 == 31:
            pl.fill = "roll_half"
            pl.kick_from = 12
        self.bis += 1
        return pl
