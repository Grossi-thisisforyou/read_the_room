"""Live bassline voice: acid (squelchy resonant 303-ish line) or rolling
(off-beat sixteenths under the kick, the Berlin 'rolling bass').

Notes are scheduled with exact sample times by synth.py; render() turns them
into one block of audio: a band-limited saw/square oscillator with glide,
an amplitude envelope, a per-note filter envelope driving the resonant Reso
filter at chunk rate, and antialiased (ADAA) tanh drive. No per-sample loops.
"""
import numpy as np

from .dsp import SR, TWO_PI, OnePole, Reso, lp_coef, saw_blep, tanh_adaa


class BassVoice:
    def __init__(self, block):
        self.B = block
        self.ar = np.arange(block)
        self.filt = Reso(1)
        self.post = OnePole(1)
        self.notes = []          # [start, gate_end, hz, accent, slide, env_origin]
        self.ph = 0.0
        self.f_last = 55.0
        self.adaa = np.zeros(1)
        self.level = 0.0
        self.cut_last = None

    def reset(self):
        self.notes = []
        self.filt.reset()
        self.post.reset()
        self.adaa[:] = 0.0
        self.cut_last = None

    def note(self, start, length, hz, accent=0.0, slide=False):
        start = int(start)
        origin = start
        if slide and self.notes:
            prev = self.notes[-1]
            if prev[1] >= start - int(0.02 * SR):
                origin = prev[5]
                prev[1] = max(prev[1], start)
        self.notes.append([start, start + int(length), float(hz), float(accent), bool(slide), origin])

    def render(self, b0, style, cutoff, envmod, q, decay, drive, wave, sub, gain):
        """Returns mono (B,) or None. All parameters are plain floats."""
        B = self.B
        b1 = b0 + B
        g0 = self.level
        self.level = gain
        # drop finished notes (keep the last one for glide reference)
        while len(self.notes) > 1 and self.notes[1][0] <= b0 and self.notes[0][1] + 0.02 * SR < b0:
            self.notes.pop(0)
        if max(g0, gain) < 1e-4 or not self.notes:
            if self.notes and self.notes[-1][1] < b0:
                self.notes = self.notes[-1:]
            return None
        f = np.full(B, self.f_last)
        amp = np.zeros(B)
        tenv = np.full(B, 10.0)          # seconds since the note's envelope origin
        acc = np.zeros(B)
        rel = int(0.004 * SR)
        for i, (st, ge, hz, ac, sl, org) in enumerate(self.notes):
            nxt = self.notes[i + 1][0] if i + 1 < len(self.notes) else 1 << 62
            end = min(nxt, ge + rel)
            lo, hi = max(st, b0), min(end, b1)
            if hi <= lo:
                continue
            idx = slice(lo - b0, hi - b0)
            t = (np.arange(lo, hi) - st) / SR
            if sl and i > 0:
                fp = self.notes[i - 1][2]
                f[idx] = hz * (fp / hz) ** np.exp(-t / 0.045)
            else:
                f[idx] = hz
            te = (np.arange(lo, hi) - org) / SR
            tenv[idx] = te
            a = np.exp(-te / (decay * (0.6 if ac > 0.5 else 1.0) * 2.5)) * (1.0 + 0.5 * ac)
            a *= np.clip(te / 0.002, 0.0, 1.0)
            gate = np.clip((ge + rel - np.arange(lo, hi)) / float(rel), 0.0, 1.0)
            amp[idx] = a * gate
            acc[idx] = ac
        self.f_last = float(f[-1])
        dt = f / SR
        ph = (self.ph + np.cumsum(dt)) % 1.0
        self.ph = float(ph[-1])
        osc = saw_blep(ph.copy(), dt)
        if wave > 0.01:
            sq = osc - saw_blep((ph + 0.5) % 1.0, dt)
            osc = (1.0 - wave) * osc + wave * 0.7 * sq
        x = (osc * amp)[None, :]
        # filter envelope at chunk rate
        L = self.filt.L
        m = B // L
        tc = tenv.reshape(m, L)[:, L // 2]
        ac = acc.reshape(m, L)[:, L // 2]
        fe = np.exp(-tc / (decay * (0.5 if style == "acid" else 0.35)))
        fc = cutoff * 2.0 ** (envmod * fe * (1.0 + 0.6 * ac))
        fc = np.clip(fc, 40.0, 9000.0)
        qq = q * (1.0 + 0.5 * ac)
        y = self.filt.process(x, fc, qq, "lp")
        y = self.post.process(y, lp_coef(min(12000.0, cutoff * 6.0 + 2000.0)))
        y, self.adaa = tanh_adaa(y * drive, self.adaa)
        y = y[0] / max(1.0, np.tanh(drive) * drive * 0.6)
        if sub > 0:
            y = y + sub * np.sin(TWO_PI * ph) * amp
        ramp = g0 + (gain - g0) * (self.ar / B)
        return y * ramp
