"""One-shot sound builders: kicks (five families), rumble, hats, ride, claps,
snares, toms, clanks, metal pipes, data ticks, stabs, impacts, crashes,
risers, reverse swells, breaths and formant 'speech' chops.

Mono builders return float32 arrays normalised to peak 1; the `stereo`
helpers return (2, n) float32 arrays, already decorrelated left/right so
hats and metal get width without any run-time cost. Everything here is
rendered when the bank is (re)built, a few sounds per audio block, never
per sample at playback time.
"""
import numpy as np

from .dsp import (SR, TWO_PI, decorrelate, fft_convolve, fft_filter, fft_peak, oversampled,
                  saw_blep, spectral_noise)

F32 = np.float32


def _t(n):
    return np.arange(n) / SR


def _fade(x, ms=5.0):
    n = min(x.shape[-1], int(ms * SR / 1000.0))
    if n > 1:
        x[..., -n:] *= np.linspace(1.0, 0.0, n)
    return x


def _norm(x, peak=1.0):
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return (x * (peak / m)) if m > 0 else x


def _out(x, fade_ms=5.0):
    return _norm(_fade(np.asarray(x, dtype=np.float64), fade_ms)).astype(F32)


def stereo(x, rng, spread_ms=7.0, haas_ms=0.4):
    """Mono one-shot -> decorrelated stereo (2, n) float32."""
    return _out(decorrelate(np.asarray(x, np.float64), rng, spread_ms, 10, haas_ms), 3)


# ---------------------------------------------------------------- kicks
# m: start pitch as a multiple of the tuned end pitch; t1: main pitch drop
# time; m2/t2: a slower second drop ("knock"); dec/k: amplitude decay and its
# curve (k > 1 holds the body then falls, k = 1 is a plain exponential);
# click: transient layer; mid: industrial noise layer; drv: saturation;
# tail: tuned sub tail level; ln: length in seconds.
KICK_FAMILIES = {
    "punch":  dict(m=5.0, t1=0.015, m2=0.55, t2=0.06, dec=0.19, k=1.7, click=0.45, mid=0.0, drv=2.2, tail=0.12, ln=0.45),
    "boom":   dict(m=3.6, t1=0.028, m2=0.35, t2=0.15, dec=0.36, k=1.35, click=0.18, mid=0.0, drv=1.7, tail=0.55, ln=0.95),
    "hard":   dict(m=6.5, t1=0.011, m2=0.8, t2=0.05, dec=0.24, k=1.9, click=0.6, mid=0.55, drv=4.5, tail=0.2, ln=0.55),
    "nine":   dict(m=3.0, t1=0.022, m2=0.25, t2=0.09, dec=0.28, k=1.0, click=0.55, mid=0.12, drv=1.5, tail=0.25, ln=0.6),
    "tunnel": dict(m=4.2, t1=0.019, m2=0.5, t2=0.11, dec=0.31, k=1.45, click=0.25, mid=0.3, drv=3.0, tail=0.4, ln=0.75),
}


KICK_TRIM_DB = {"punch": 2.0, "boom": -1.4, "hard": -0.9, "nine": 1.7, "tunnel": -1.6}


def kick(rng, family="punch", f_end=48.0, drive=1.0, decay=1.0, length=1.0, click=1.0,
         lowpass=None, tail=1.0):
    """Tuned techno kick. `f_end` is the pitch the body settles on (the key's
    root around 41 to 62 Hz); the other arguments scale the family's values."""
    P = KICK_FAMILIES.get(family, KICK_FAMILIES["punch"])
    n = int(P["ln"] * length * SR)
    t = _t(n)
    fe = float(f_end)
    f = fe * (1.0 + P["m2"] * np.exp(-t / P["t2"])) + fe * (P["m"] - 1.0) * np.exp(-t / P["t1"])
    ph = TWO_PI * np.cumsum(f) / SR
    dec = P["dec"] * decay
    env = np.exp(-(t / dec) ** P["k"]) * (1.0 - np.exp(-t / 0.0004))
    env += P["tail"] * tail * np.exp(-t / (2.4 * dec)) * (1.0 - np.exp(-t / (0.5 * dec)))
    x = np.sin(ph) * env
    if P["click"] * click > 0:
        nc = int(0.006 * SR)
        c = fft_filter(rng.standard_normal(nc), hp=1800.0, order=2) * np.exp(-_t(nc) / 0.0015)
        c += 0.6 * np.sin(TWO_PI * rng.uniform(2600, 3800) * _t(nc)) * np.exp(-_t(nc) / 0.0012)
        x[:nc] += P["click"] * click * 0.35 * c / (np.max(np.abs(c)) + 1e-9)
    if P["mid"] > 0:
        nm = int(0.08 * SR)
        mid = spectral_noise(nm, rng, lambda u: 1600.0 + 0.0 * u, lambda u: 0.8 + 0.0 * u)
        x[:nm] += P["mid"] * 0.18 * mid * np.exp(-_t(nm) / 0.018)
    d = P["drv"] * drive
    x = oversampled(x, lambda u: np.tanh(d * u) / np.tanh(d), 4)
    x = fft_filter(x, hp=22.0, lp=lowpass or 11000.0, order=2)
    return _out(x, 25)


def rumble(rng, kick_sig, beat_n, drive=2.0, cutoff=105.0, decay=0.45, depth=1.0):
    """Warehouse rumble, one beat long and seamless.

    A four-on-the-floor train of this kick is fed into a dark noise reverb
    (computed circularly, so every beat already carries the tails of the
    previous ones), lowpassed, distorted, lowpassed again, then shaped by a
    sidechain curve: silent under the kick, swelling back over the beat and
    ducking just before the next hit.
    """
    L = int(beat_n)
    ir_n = int(min(2.5, 4.0 * decay) * SR)
    ir = fft_filter(rng.standard_normal(ir_n), lp=900.0, order=2) * np.exp(-_t(ir_n) / decay)
    wet = fft_convolve(kick_sig.astype(np.float64), ir)
    per = np.zeros(L)
    for k in range(0, len(wet), L):
        seg = wet[k:k + L]
        per[:len(seg)] += seg
    tiled = np.tile(per, 3)
    tiled = _norm(fft_filter(tiled, lp=cutoff, order=4))
    tiled = np.tanh(drive * 2.5 * tiled)
    tiled = fft_filter(tiled, lp=cutoff * 1.8, hp=28.0, order=2)
    wet = tiled[L:2 * L]
    u = np.arange(L) / float(L)
    s = np.clip((u - 0.06) / 0.46, 0.0, 1.0)
    rise = s * s * (3.0 - 2.0 * s)
    fall = np.clip((1.0 - u) / 0.07, 0.0, 1.0)
    env = (1.0 - depth) + depth * rise ** 1.2 * fall
    return _out(wet * env, 2)


# ---------------------------------------------------------------- metals
_HAT_PARTIALS = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


def hat(rng, decay=0.045, bright=0.5, metal=0.4, drive=1.5, hp=None):
    n = int(max(0.05, decay * 6) * SR)
    t = _t(n)
    noise = rng.standard_normal(n)
    sq = np.zeros(n)
    for f in _HAT_PARTIALS:
        sq += np.sign(np.sin(TWO_PI * f * (1.0 + 0.3 * bright) * t + rng.uniform(0, TWO_PI)))
    x = (1.0 - metal) * noise + metal * sq * 0.4
    x = fft_filter(x, hp=hp or (5000 + 5000 * bright), order=3)
    env = np.exp(-t / decay) * (1.0 - np.exp(-t / 0.0004))
    x = np.tanh(drive * _norm(x * env))
    return _out(x, 3)


def ride(rng, decay=0.55, bright=0.5):
    """Shimmering industrial ride: ringing inharmonic squares over noise."""
    n = int(decay * 4.0 * SR)
    t = _t(n)
    x = np.zeros(n)
    base = rng.uniform(300, 420)
    for r in (1.0, 1.483, 1.932, 2.546, 2.630, 3.897, 4.21):
        x += np.sign(np.sin(TWO_PI * base * r * (1 + 0.25 * bright) * t + rng.uniform(0, TWO_PI)))
    x = 0.5 * x / 7.0 + 0.5 * rng.standard_normal(n)
    x = fft_filter(x, hp=3200 + 2500 * bright, order=3)
    env = 0.25 * np.exp(-t / 0.01) + np.exp(-t / decay)
    return _out(np.tanh(1.6 * _norm(x * env)), 20)


def crash(rng, length=2.4):
    """Noise crash for drops: bright burst with a long metallic wash."""
    n = int(length * SR)
    t = _t(n)
    x = ride(rng, decay=length / 4.0, bright=0.8).astype(np.float64)
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    nz = fft_filter(rng.standard_normal(n), hp=2500.0, order=2)
    x = 0.6 * x + 0.4 * _norm(nz) * np.exp(-t / (length / 3.5))
    return _out(x * (1.0 - np.exp(-t / 0.0008)), 60)


def clap(rng, tail=0.12, tone=1500.0):
    n = int(0.45 * SR)
    t = _t(n)
    env = np.zeros(n)
    for o in (0.0, 0.009, 0.019, 0.030):
        env += (t >= o) * np.exp(-np.clip(t - o, 0, None) / 0.0035)
    env += 0.6 * (t >= 0.03) * np.exp(-np.clip(t - 0.03, 0, None) / tail)
    x = fft_filter(rng.standard_normal(n) * env, hp=tone * 0.6, lp=tone * 2.4, order=2)
    return _out(np.tanh(2.0 * _norm(x)), 10)


SNARE_KINDS = ("noise", "industrial", "rim")


def snare(rng, kind="industrial", tune=1.0, length=0.35):
    """Snares for backbeats and rolls. `tune` shifts body and resonances."""
    n = int(length * SR)
    t = _t(n)
    if kind == "rim":
        x = np.sin(TWO_PI * 1700 * tune * t) + 0.7 * np.sin(TWO_PI * 455 * tune * t)
        x = x * np.exp(-t / 0.012) + 0.3 * fft_filter(rng.standard_normal(n), hp=3000) * np.exp(-t / 0.006)
        return _out(np.tanh(2.5 * x), 10)
    f = 185.0 * tune * (1.0 + 0.6 * np.exp(-t / 0.012))
    body = np.sin(TWO_PI * np.cumsum(f) / SR) * np.exp(-t / 0.05)
    nz = rng.standard_normal(n)
    if kind == "noise":
        nz = fft_filter(nz, hp=1200.0 * tune, lp=11000.0, order=2) * np.exp(-t / 0.13)
        x = 0.35 * body + nz * 0.9
        return _out(np.tanh(1.8 * _norm(x)), 20)
    nz = fft_filter(nz, hp=1800.0 * tune, lp=9000.0, order=2) * np.exp(-t / 0.085)
    nz = fft_peak(nz, 3100.0 * tune, 6.0, 9.0)
    x = 0.55 * body + nz
    return _out(np.tanh(3.0 * _norm(x)), 20)


def tom(rng, f=110.0, decay=0.22):
    """Distorted industrial tom for fills."""
    n = int(decay * 4.0 * SR)
    t = _t(n)
    fr = f * (1.0 + 0.7 * np.exp(-t / 0.03))
    x = np.sin(TWO_PI * np.cumsum(fr) / SR) * np.exp(-t / decay)
    x += 0.25 * fft_filter(rng.standard_normal(n), hp=800, lp=5000) * np.exp(-t / 0.02)
    return _out(np.tanh(2.2 * x), 20)


def clank(rng, fc, ratio, index=4.0, decay=0.22, ring=0.3, drive=1.6, length=0.9):
    """Inharmonic FM + ring-modulated metal hit."""
    n = int(length * SR)
    t = _t(n)
    m = index * np.exp(-t / (decay * 0.35)) * np.sin(TWO_PI * fc * ratio * t)
    car = np.sin(TWO_PI * fc * t + m)
    r = np.sin(TWO_PI * fc * ratio * 1.731 * t)
    x = car * (1.0 - ring) + car * r * ring
    x += 0.4 * rng.standard_normal(n) * np.exp(-t / 0.002)
    x = np.tanh(drive * x * np.exp(-t / decay))
    return _out(x, 20)


def metal(rng, f=300.0, fb=0.985, harsh=0.5, length=0.9):
    """Struck pipe: noise burst through three resonant comb 'pipes'."""
    n = int(length * SR)
    t = _t(n)
    exc = rng.standard_normal(n) * np.exp(-t / 0.004)
    ir = np.zeros(n)
    for mul in (1.0, 1.37, 2.13):
        D = SR / (f * mul)
        K = int(n / D)
        idx = (np.arange(K) * D).astype(int)
        ir[idx] += fb ** np.arange(K)
    x = fft_convolve(exc, ir)[:n]
    x = fft_filter(x, hp=150.0)
    x = np.tanh((1.0 + 3.0 * harsh) * _norm(x) * np.exp(-t / 0.35))
    return _out(x, 20)


def tick(rng, f, length=0.006, square=False):
    n = max(16, int(length * SR))
    t = _t(n)
    x = np.sin(TWO_PI * f * t)
    if square:
        x = np.sign(x)
    return _out(x * np.exp(-t / (length / 4.0)), 1)


# ---------------------------------------------------------------- tonal
def stab(rng, root_hz, intervals, detune_cents=8.0, cutoff=1500.0, decay=0.35,
         drive=1.5, length=1.0, reso=0.0):
    """Detuned saw chord (or cluster), filtered and saturated; `reso` adds a
    resonant peak at the cutoff (the 'singing' dub-chord colour)."""
    n = int(length * SR)
    t = _t(n)
    x = np.zeros(n)
    for iv in intervals:
        f = root_hz * 2.0 ** (iv / 12.0)
        for d in (-1.0, 0.0, 1.0):
            fd = f * 2.0 ** (d * detune_cents / 1200.0)
            x += saw_blep((rng.random() + fd * t) % 1.0, fd / SR)
    env = np.exp(-t / decay) * (1.0 - np.exp(-t / 0.002))
    x = fft_filter(x * env, lp=cutoff, hp=70.0, order=2)
    if reso > 0:
        x = fft_peak(x, cutoff, 4.0 + 6.0 * reso, 4.0 + 8.0 * reso)
    return _out(np.tanh(drive * _norm(x)), 30)


def impact(rng, length=2.2):
    n = int(length * SR)
    t = _t(n)
    sweep = spectral_noise(n, rng, lambda u: 9000.0 * (80.0 / 9000.0) ** (u ** 0.5),
                           lambda u: 0.6 + 0.0 * u)
    boom = np.sin(TWO_PI * np.cumsum(28.0 + 55.0 * np.exp(-t / 0.4)) / SR) * np.exp(-t / 0.5)
    x = 0.15 * sweep * np.exp(-t / 0.6) + boom
    return _out(np.tanh(1.5 * x), 50)


def swell(rng, length=1.6):
    """Reversed reverb swell: a noise-and-metal burst's tail, played backwards."""
    n = int(length * SR)
    t = _t(n)
    burst = metal(rng, f=rng.uniform(120, 400), harsh=0.3, length=length).astype(np.float64)
    tail = spectral_noise(n, rng, lambda u: 2500.0 * (300.0 / 2500.0) ** u,
                          lambda u: 1.2 + 0.0 * u) * np.exp(-t / 0.5)
    x = (0.6 * burst + 0.4 * _norm(tail))[::-1].copy()
    x *= np.linspace(0.0, 1.0, n) ** 1.5
    return _out(x, 4)


def breath(rng, length=1.3, tone=900.0):
    """Close, intimate breath: soft band noise with slow inhale envelope."""
    n = int(length * SR)
    u = np.arange(n) / float(n)
    x = spectral_noise(n, rng, lambda v: tone * (1.0 + 0.4 * np.sin(np.pi * v)),
                       lambda v: 0.9 + 0.0 * v)
    env = np.sin(np.pi * u) ** 2 * (1.0 + 0.2 * np.sin(TWO_PI * 3.0 * u))
    return _out(x * env, 10)


# rough vowel formants (F1, F2, F3) in Hz
_VOWELS = ((730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240),
           (530, 1840, 2480), (570, 840, 2410), (660, 1720, 2410))


def vox(rng, length=0.12):
    """A 'spoken fragment': buzzy pulse + noise through two random vowel formants
    that morph, chopped short. Not speech, but reads as a cut-up voice."""
    n = int(length * SR)
    t = _t(n)
    f0 = rng.uniform(90, 180)
    pulse = saw_blep((f0 * t) % 1.0, f0 / SR) + 0.6 * rng.standard_normal(n)
    v1 = _VOWELS[rng.integers(len(_VOWELS))]
    v2 = _VOWELS[rng.integers(len(_VOWELS))]
    nfft = 1 << int(np.ceil(np.log2(n * 2)))
    X = np.fft.rfft(pulse, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / SR)
    mag = np.zeros_like(f)
    for a, b, g in zip(v1, v2, (1.0, 0.7, 0.4)):
        fc = 0.5 * (a + b)
        mag += g * np.exp(-0.5 * ((f - fc) / (0.12 * fc + 60)) ** 2)
    x = np.fft.irfft(X * mag, nfft)[:n]
    env = np.clip(t / 0.004, 0, 1) * np.clip((length - t) / 0.02, 0, 1)
    return _out(np.tanh(2.0 * _norm(x * env)), 2)


def riser(rng, n, tension=0.5, sps=6000):
    """Stereo noise riser over n samples; tension adds gating and a pitch sweep."""
    u = np.arange(n) / float(n)
    L = spectral_noise(n, rng, lambda v: 250.0 * (9000.0 / 250.0) ** v, lambda v: 1.2 - 0.8 * v)
    R = spectral_noise(n, rng, lambda v: 250.0 * (9000.0 / 250.0) ** v, lambda v: 1.2 - 0.8 * v)
    amp = u ** 2.2
    if tension > 0.35:
        rate = np.where(u > 0.75, sps / 2.0, sps)
        gate = (np.floor(np.arange(n) / rate) % 2 == 0).astype(np.float64)
        amp = amp * (1.0 - min(0.8, tension) * (1.0 - gate) * u)
        sw = np.sin(TWO_PI * np.cumsum(100.0 * (20.0 ** u)) / SR) * tension * 0.8
        L = L + sw
        R = R + sw
    out = np.stack([L * amp, R * amp])
    out = out / (np.max(np.abs(out)) + 1e-9)
    out[:, -int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    return out.astype(F32)


def resample(x, semis):
    """Pitch a one-shot by resampling (used to move stabs with the chords)."""
    if abs(semis) < 1e-3:
        return x
    r = 2.0 ** (semis / 12.0)
    n = x.shape[-1]
    m = int(n / r)
    pos = np.arange(m) * r
    if x.ndim == 1:
        return np.interp(pos, np.arange(n), x).astype(F32)
    return np.stack([np.interp(pos, np.arange(n), c) for c in x]).astype(F32)
