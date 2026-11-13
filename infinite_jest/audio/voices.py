"""One-shot sound builders: kicks, rumble, hats, claps, clanks, metal pipes,
data ticks, stabs, impacts, risers, breaths and formant 'speech' chops.

All return mono float32 arrays normalised to peak 1 (the riser is stereo).
They are rendered at startup and whenever the visitor or a parameter bucket
changes (on a bar boundary), never per sample at playback time.
"""
import numpy as np

from .dsp import SR, TWO_PI, fft_convolve, fft_filter, saw_blep, spectral_noise

F32 = np.float32


def _t(n):
    return np.arange(n) / SR


def _fade(x, ms=5.0):
    n = min(len(x), int(ms * SR / 1000.0))
    if n > 1:
        x[-n:] *= np.linspace(1.0, 0.0, n)
    return x


def _norm(x, peak=1.0):
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return (x * (peak / m)) if m > 0 else x


def _out(x, fade_ms=5.0):
    return _norm(_fade(np.asarray(x, dtype=np.float64), fade_ms)).astype(F32)


def kick(rng, drive=2.0, f0=155.0, f1=46.0, ptau=0.03, decay=0.36, length=0.55,
         click=0.3, lowpass=None):
    n = int(length * SR)
    t = _t(n)
    f = f1 + (f0 - f1) * np.exp(-t / ptau)
    ph = TWO_PI * np.cumsum(f) / SR
    amp = np.exp(-t / decay) * (1.0 - np.exp(-t / 0.0008))
    x = np.sin(ph) * amp
    if click > 0:
        c = rng.standard_normal(n) * np.exp(-t / 0.0025)
        c[1:] -= c[:-1].copy()
        x += click * 0.5 * c
    x = np.tanh(drive * x) / np.tanh(drive)
    if lowpass:
        x = fft_filter(x, lp=lowpass, order=2)
    return _out(x, 25)


def rumble(rng, kick_sig, beat_n, drive=2.0, cutoff=105.0):
    """Classic warehouse rumble: kick into a dark reverb, lowpassed, distorted,
    then shaped so it swells between kicks (pre-baked sidechain)."""
    ir_n = int(0.8 * SR)
    ir = rng.standard_normal(ir_n) * np.exp(-_t(ir_n) / 0.28)
    wet = fft_convolve(kick_sig.astype(np.float64), ir)
    wet = _norm(fft_filter(wet, lp=cutoff, order=4))
    wet = np.tanh(drive * 2.5 * wet)
    wet = fft_filter(wet, lp=cutoff * 1.8, order=2)
    if len(wet) < beat_n:
        wet = np.pad(wet, (0, beat_n - len(wet)))
    wet = wet[:beat_n]
    u = np.arange(beat_n) / float(beat_n)
    env = np.clip((u - 0.12) / 0.2, 0, 1) ** 1.5 * np.clip((1.0 - u) / 0.45, 0, 1)
    return _out(wet * env, 3)


def hat(rng, decay=0.045, bright=0.5, metal=0.4, drive=1.5):
    n = int(max(0.05, decay * 6) * SR)
    t = _t(n)
    noise = rng.standard_normal(n)
    sq = np.zeros(n)
    for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
        sq += np.sign(np.sin(TWO_PI * f * (1.0 + 0.3 * bright) * t + rng.uniform(0, TWO_PI)))
    x = (1.0 - metal) * noise + metal * sq * 0.4
    x = fft_filter(x, hp=5000 + 5000 * bright, order=3)
    env = np.exp(-t / decay) * (1.0 - np.exp(-t / 0.0004))
    x = np.tanh(drive * _norm(x * env))
    return _out(x, 3)


def clap(rng, tail=0.12, tone=1500.0):
    n = int(0.45 * SR)
    t = _t(n)
    env = np.zeros(n)
    for o in (0.0, 0.009, 0.019, 0.030):
        env += (t >= o) * np.exp(-np.clip(t - o, 0, None) / 0.0035)
    env += 0.6 * (t >= 0.03) * np.exp(-np.clip(t - 0.03, 0, None) / tail)
    x = fft_filter(rng.standard_normal(n) * env, hp=tone * 0.6, lp=tone * 2.4, order=2)
    return _out(np.tanh(2.0 * _norm(x)), 10)


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


def stab(rng, root_hz, intervals, detune_cents=8.0, cutoff=1500.0, decay=0.35,
         drive=1.5, length=1.0):
    """Detuned saw chord (or cluster), filtered and saturated."""
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
