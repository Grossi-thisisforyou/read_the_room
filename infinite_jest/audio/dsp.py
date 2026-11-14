"""Small vectorised DSP toolkit for the INFINITE JEST sound engine.

numpy only (works with numpy 1.24 as shipped on Raspberry Pi OS Bookworm).
Nothing in here loops over individual samples in Python: recursive filters are
solved per chunk in closed form, and feedback effects use delays longer than
one processing block, so each block is a handful of array operations.

Main pieces
-----------
OnePole      one-pole lowpass, chunked closed-form scan (no per-sample loop)
Reso         resonant 2-pole LP/BP/HP (RBJ biquad), solved as a complex
             one-pole "phasor" scan, coefficients constant per 64-sample chunk
Oversampler  2x halfband up/down sampler for distortion
Saturator    two-band saturation: clean-ish lows, 2x oversampled highs
Room         warehouse reverb: early reflections + modulated 8-line FDN
PingPong     stereo feedback delay
Glue         gentle RMS bus compressor (chunk-rate gain computer)
Limiter      look-ahead, true-peak-aware brickwall limiter
MonoLow      keeps everything below ~120 Hz in mono (M/S)
"""
import cmath
import math

import numpy as np

SR = 48000
TWO_PI = 2.0 * np.pi


def midi_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=np.float64) - 69.0) / 12.0)


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lp_coef(fc, sr=SR):
    """Pole of a one-pole lowpass with cutoff fc (Hz)."""
    fc = min(max(float(fc), 1.0), 0.45 * sr)
    return max(0.01, float(np.exp(-TWO_PI * fc / sr)))


def ramp(a, b, m):
    """m values gliding from a (exclusive) to b (inclusive), geometric when both > 0."""
    u = np.arange(1, m + 1) / float(m)
    if a > 0 and b > 0:
        return a * (b / a) ** u
    return a + (b - a) * u


class OnePole:
    """One-pole lowpass y[n] = a*y[n-1] + (1-a)*x[n] for (channels, n) blocks.

    Each 64-sample chunk is solved in closed form with a scaled cumulative sum,
    and the carries between chunks are resolved with one small matrix product,
    so there is no Python loop at all.
    """

    def __init__(self, channels, chunk=64):
        self.z = np.zeros(channels)
        self.L = chunk
        self._a = None
        self._m = None

    def reset(self):
        self.z[:] = 0.0

    def _prep(self, a, m):
        # reuse coefficients for tiny cutoff moves (inaudible, saves CPU)
        if m != self._m or self._a is None or abs(a - self._a) > 0.002 * (1.0 - a):
            k = np.arange(self.L, dtype=np.float64)
            self._up = a ** (-k)
            self._dn = (a ** k) * (1.0 - a)
            self._carry = a ** (k + 1.0)
            aL = a ** self.L
            i = np.arange(m)
            e = (i[:, None] - i[None, :]).astype(np.float64)
            # T[i, j] = aL^(i-j) for j <= i: chunk-end carries as one matmul
            self._T = np.where(e >= 0, aL ** np.maximum(e, 0.0), 0.0).T
            self._z0 = aL ** (i + 1.0)
            self._a, self._m = a, m

    def process(self, x, a):
        ch, n = x.shape
        m = n // self.L
        self._prep(a, m)
        a = self._a
        loc = np.cumsum(x.reshape(ch, m, self.L) * self._up, axis=2) * self._dn
        Z = loc[:, :, -1] @ self._T + self.z[:, None] * self._z0
        carry = np.empty((ch, m))
        carry[:, 0] = self.z
        carry[:, 1:] = Z[:, :-1]
        self.z = Z[:, -1].copy()
        return (loc + carry[:, :, None] * self._carry).reshape(ch, n)


class Reso:
    """Resonant 2-pole filter (RBJ cookbook LP / BP / HP), no per-sample loop.

    A biquad with complex-conjugate poles p, p* is split into partial
    fractions; its all-pole part is then 2*Re(u) where u is a complex one-pole
    ("phasor") recursion u[n] = p*u[n-1] + k*x[n]. A complex one-pole can be
    solved per chunk with the same scaled-cumsum trick as OnePole, and the
    carries between chunks with one small matrix (built in the log domain so
    it never overflows). The numerator (1,2,1), (1,0,-1) or (1,-2,1) is a
    3-tap FIR.

    Trade-off (documented on purpose): cutoff and Q are constant within each
    64-sample chunk (1.3 ms, i.e. a 750 Hz control rate) and are interpolated
    chunk to chunk, which is plenty for envelopes, tilt and sweeps. Because
    the state is the rotating phasor, moving the cutoff never makes the output
    jump (the Mathews-Smith phasor-filter property). There is no non-linearity
    inside the feedback loop, so unlike an analog ladder it cannot "scream"
    into self-oscillation; drive goes before and after the filter instead.
    Q is kept between 0.55 and 24.
    """

    MODES = ("lp", "bp", "hp")

    def __init__(self, channels, chunk=64, sr=SR):
        self.ch = channels
        self.L = chunk
        self.sr = float(sr)
        self.k = np.arange(chunk, dtype=np.float64)
        self.u = np.zeros(channels, np.complex128)
        self.yh = np.zeros((channels, 2))
        self._key = None
        self._cache = {}
        self._tri = None
        self.fc_last = None
        self.q_last = None

    def reset(self):
        self.u[:] = 0.0
        self.yh[:] = 0.0

    def _coefs(self, fc, q, mode):
        w0 = TWO_PI * np.clip(fc, 12.0, 0.46 * self.sr) / self.sr
        cw, sw = np.cos(w0), np.sin(w0)
        q = np.clip(q, 0.55, 24.0)
        alpha = sw / (2.0 * q)
        a0 = 1.0 + alpha
        im = sw * np.sqrt(1.0 - 1.0 / (4.0 * q * q)) / a0
        p = cw / a0 + 1j * im
        c = p / (2j * im)
        if mode == "lp":
            G = (1.0 - cw) * 0.5 / a0
        elif mode == "hp":
            G = (1.0 + cw) * 0.5 / a0
        else:
            G = alpha / a0
        return p, G * c

    def _prep(self, fc, q, m, mode):
        """Per-chunk coefficients (fc, q arrays of m values)."""
        p, kc = self._coefs(fc, q, mode)
        lp = np.log(p)
        E = np.exp(np.multiply.outer(lp, self.k))              # p^k, (m, L)
        self._inj = kc[:, None] / E                            # k * p^-k
        self._E = E
        self._Ep = E * p[:, None]                              # p^(k+1)
        lc = np.cumsum(lp * self.L)
        D = lc[:, None] - lc[None, :]
        if self._tri is None or self._tri.shape[0] != m:
            self._tri = np.tri(m, dtype=bool)
            self._ii = np.arange(m)
            self._ee = (self._ii[:, None] - self._ii[None, :]).astype(np.float64)
        self._T = np.exp(np.where(self._tri, D, -np.inf)).T    # (m, m)
        self._z0 = np.exp(lc)
        self._key = None

    def _prep_scalar(self, fc, q, m, mode):
        """Block-constant coefficients, cached (most filters sit still)."""
        key = (fc, q, mode, m)
        if key == self._key:
            return
        hit = self._cache.get(key)
        if hit is None:
            w0 = TWO_PI * min(max(fc, 12.0), 0.46 * self.sr) / self.sr
            cw, sw = math.cos(w0), math.sin(w0)
            q = min(max(q, 0.55), 24.0)
            alpha = sw / (2.0 * q)
            a0 = 1.0 + alpha
            im = sw * math.sqrt(1.0 - 1.0 / (4.0 * q * q)) / a0
            p = complex(cw / a0, im)
            G = ((1.0 - cw) * 0.5 if mode == "lp" else (1.0 + cw) * 0.5 if mode == "hp" else alpha) / a0
            kc = G * p / (2j * im)
            E = np.exp(cmath.log(p) * self.k)
            if self._tri is None or self._tri.shape[0] != m:
                self._tri = np.tri(m, dtype=bool)
                self._ii = np.arange(m)
                self._ee = (self._ii[:, None] - self._ii[None, :]).astype(np.float64)
            lP = cmath.log(p) * self.L
            pw = np.exp(lP * self._ii)
            T = np.where(self._tri, pw[np.maximum(self._ee, 0).astype(int)], 0.0).T
            hit = ((kc / E)[None, :], E[None, :], (E * p)[None, :], T, pw * cmath.exp(lP))
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = hit
        self._inj, self._E, self._Ep, self._T, self._z0 = hit
        self._key = key

    def process(self, x, fc, q, mode="lp"):
        """x: (ch, n). fc, q: scalars (block-constant, quantised to 1/96 octave
        and 2% so the coefficients can be cached) or arrays of n // chunk
        values (per-chunk)."""
        ch, n = x.shape
        m = n // self.L
        if np.ndim(fc) == 0 and np.ndim(q) == 0:
            fq = 2.0 ** (round(math.log2(max(float(fc), 12.0)) * 48.0) / 48.0)
            qq = round(float(q) * 50.0) / 50.0
            self._prep_scalar(fq, qq, m, mode)
        else:
            fc = np.broadcast_to(np.asarray(fc, np.float64), (m,))
            q = np.broadcast_to(np.asarray(q, np.float64), (m,))
            self._prep(fc, q, m, mode)
        loc = np.cumsum(x.reshape(ch, m, self.L) * self._inj, axis=2) * self._E
        U = loc[:, :, -1] @ self._T + self.u[:, None] * self._z0
        prev = np.empty((ch, m), np.complex128)
        prev[:, 0] = self.u
        prev[:, 1:] = U[:, :-1]
        self.u = U[:, -1].copy()
        y = 2.0 * (loc + prev[:, :, None] * self._Ep).real.reshape(ch, n)
        ext = np.concatenate([self.yh, y], axis=1)
        self.yh = ext[:, -2:].copy()
        if mode == "lp":
            return ext[:, 2:] + 2.0 * ext[:, 1:-1] + ext[:, :-2]
        if mode == "hp":
            return ext[:, 2:] - 2.0 * ext[:, 1:-1] + ext[:, :-2]
        return ext[:, 2:] - ext[:, :-2]

    def glide(self, x, fc, q, mode="lp"):
        """Like process(), but glides fc and q from the previous call's values."""
        m = x.shape[1] // self.L
        f0 = self.fc_last if self.fc_last is not None else fc
        q0 = self.q_last if self.q_last is not None else q
        self.fc_last, self.q_last = fc, q
        if abs(np.log2(max(fc, 1.0) / max(f0, 1.0))) < 1.0 / 32.0 and abs(q0 - q) < 0.05 * q:
            return self.process(x, fc, q, mode)
        return self.process(x, ramp(f0, fc, m), ramp(q0, q, m), mode)


def _halfband(taps=31, beta=8.0):
    n = np.arange(taps) - (taps - 1) // 2
    h = 0.5 * np.sinc(n / 2.0) * np.kaiser(taps, beta)
    return h / h.sum()


class Oversampler:
    """2x up/down sampling with a 31-tap halfband (Kaiser) for non-linearities.

    process(x, fn) upsamples, applies fn at 2x, filters and decimates.
    Polyphase: a halfband's taps are zero at every other index except the
    centre, so each direction is one 16-tap convolution at the base rate
    plus a delayed copy. The round trip delays the signal by DELAY samples.
    """

    H = _halfband()
    DELAY = (len(H) - 1) // 2          # 15 samples at 2x per stage = 15 at 1x total

    def __init__(self, channels):
        self.ch = channels
        self.he = self.H[0::2].copy()            # 16 taps (even indices)
        self.hc = float(self.H[len(self.H) // 2])  # centre tap (odd index 15)
        self.hx = np.zeros((channels, 15))
        self.hye = np.zeros((channels, 15))
        self.hyo = np.zeros((channels, 8))

    def reset(self):
        self.hx[:] = 0.0
        self.hye[:] = 0.0
        self.hyo[:] = 0.0

    def process(self, x, fn):
        ch, n = x.shape
        ext = np.concatenate([self.hx, x], axis=1)
        self.hx = ext[:, -15:].copy()
        up = np.empty((ch, 2 * n))
        for i in range(ch):
            up[i, 0::2] = np.convolve(ext[i], self.he, "valid")
        up[:, 0::2] *= 2.0
        up[:, 1::2] = (2.0 * self.hc) * ext[:, 8:8 + n]
        y = fn(up)
        ee = np.concatenate([self.hye, y[:, 0::2]], axis=1)
        eo = np.concatenate([self.hyo, y[:, 1::2]], axis=1)
        self.hye = ee[:, -15:].copy()
        self.hyo = eo[:, -8:].copy()
        out = np.empty((ch, n))
        for i in range(ch):
            out[i] = np.convolve(ee[i], self.he, "valid")
        return out + self.hc * eo[:, :n]


def tanh_adaa(x, prev):
    """First-order antiderivative-antialiased tanh (cheap alias reduction).

    x: (ch, n); prev: (ch,) last input sample of the previous block.
    Returns (y, new_prev). Adds half a sample of delay.
    """
    xp = np.concatenate([prev[:, None], x], axis=1)
    ax = np.abs(xp)
    F = ax + np.log1p(np.exp(-2.0 * ax)) - 0.6931471805599453   # log(cosh(x))
    dx = xp[:, 1:] - xp[:, :-1]
    small = np.abs(dx) < 1e-5
    y = np.where(small, np.tanh(0.5 * (xp[:, 1:] + xp[:, :-1])),
                 (F[:, 1:] - F[:, :-1]) / np.where(small, 1.0, dx))
    return y, x[:, -1].copy()


class Saturator:
    """Two-band master saturation.

    Below ~120 Hz: folded to mono and a soft tanh at the base rate (the kick
    and sub stay round and centred).
    Above: an asymmetric soft clipper (adds even and odd harmonics, the
    "warehouse PA pushed hard" grit), run at 2x through the halfband
    oversampler so the distortion does not alias. The low band is delayed to
    stay phase-aligned with the oversampled band.
    """

    def __init__(self, xover=120.0):
        self.lp1 = OnePole(2)
        self.c = lp_coef(xover)
        self.os = Oversampler(2)
        self.dl = np.zeros((2, Oversampler.DELAY))

    def reset(self):
        self.lp1.reset()
        self.os.reset()
        self.dl[:] = 0.0

    def process(self, x, drive, asym=0.15, low_drive=1.2, mono_low=True):
        lo = self.lp1.process(x, self.c)
        hi = x - lo
        if mono_low:                 # everything below ~120 Hz in mono (club / single-speaker safe)
            lo = np.broadcast_to(0.5 * (lo[0] + lo[1]), lo.shape)
        ext = np.concatenate([self.dl, lo], axis=1)
        self.dl = ext[:, -Oversampler.DELAY:].copy()
        lo = ext[:, :x.shape[1]]
        d = max(1e-3, float(drive))
        b = float(asym)
        off = np.tanh(d * b)
        norm = 1.0 / (d * (1.0 - off * off))       # unity small-signal gain

        def shape(u):
            return (np.tanh(d * (u + b)) - off) * norm

        hi = self.os.process(hi, shape)
        ld = max(1e-3, float(low_drive))
        return np.tanh(lo * ld) / ld + hi


def _nfft(n):
    return 1 << int(np.ceil(np.log2(max(2, n))))


def fft_filter(x, lp=None, hp=None, order=2, sr=SR):
    """Zero-phase Butterworth-shaped filtering of a one-shot (offline use)."""
    n = len(x)
    nfft = _nfft(n) * 2
    X = np.fft.rfft(x, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    f[0] = 1e-3
    if lp:
        X *= 1.0 / np.sqrt(1.0 + (f / lp) ** (2 * order))
    if hp:
        X *= 1.0 / np.sqrt(1.0 + (hp / f) ** (2 * order))
    return np.fft.irfft(X, nfft)[:n]


def fft_peak(x, fc, q, gain_db, sr=SR):
    """Zero-phase resonant peak (offline): boosts a band around fc."""
    n = len(x)
    nfft = _nfft(n) * 2
    X = np.fft.rfft(x, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    g = 10.0 ** (gain_db / 20.0) - 1.0
    X *= 1.0 + g / (1.0 + (q * (f / fc - fc / np.maximum(f, 1e-3))) ** 2)
    return np.fft.irfft(X, nfft)[:n]


def fft_convolve(a, b):
    n = len(a) + len(b) - 1
    nfft = _nfft(n)
    return np.fft.irfft(np.fft.rfft(a, nfft) * np.fft.rfft(b, nfft), nfft)[:n]


def oversampled(x, fn, factor=4):
    """Apply a waveshaper to a one-shot at `factor`x via FFT resampling (offline)."""
    n = len(x)
    nfft = _nfft(n)
    X = np.fft.rfft(x, nfft)
    Xu = np.zeros(nfft * factor // 2 + 1, np.complex128)
    Xu[:len(X)] = X * factor
    y = fn(np.fft.irfft(Xu, nfft * factor))
    Y = np.fft.rfft(y)[:len(X)] / factor
    Y[-1] = 0.0
    return np.fft.irfft(Y, nfft)[:n]


def saw_blep(phase, dt):
    """Band-limited sawtooth (polyBLEP). phase in [0,1), dt = f/sr (broadcastable)."""
    y = 2.0 * phase - 1.0
    dtb = np.broadcast_to(dt, phase.shape)
    m = phase < dtb
    t = phase[m] / dtb[m]
    y[m] -= t + t - t * t - 1.0
    m = phase > 1.0 - dtb
    t = (phase[m] - 1.0) / dtb[m]
    y[m] -= t * t + t + t + 1.0
    return y


def spectral_noise(n, rng, center_fn, width_fn, nfft=1024, sr=SR):
    """Noise whose band (centre Hz, width in octaves) moves over time.

    Built by short-time spectral synthesis: random-phase spectra with a
    log-gaussian band per frame, sqrt-Hann windows, 50% overlap-add. Fully
    vectorised; used for risers, sweeps, breaths and formant chops.
    """
    hop = nfft // 2
    frames = n // hop + 2
    u = np.linspace(0.0, 1.0, frames)
    c = np.asarray(center_fn(u), dtype=np.float64).reshape(-1, 1)
    w = np.asarray(width_fn(u), dtype=np.float64).reshape(-1, 1)
    f = np.fft.rfftfreq(nfft, 1.0 / sr).reshape(1, -1)
    f[0, 0] = 1.0
    mag = np.exp(-0.5 * (np.log2(f / c) / w) ** 2)
    ph = rng.uniform(0.0, TWO_PI, mag.shape)
    win = np.sqrt(np.hanning(nfft + 1)[:nfft])
    fr = np.fft.irfft(mag * np.exp(1j * ph), nfft, axis=1) * win
    out = np.zeros((frames + 1, hop))
    out[:-1] += fr[:, :hop]
    out[1:] += fr[:, hop:]
    out = out.reshape(-1)[:n]
    r = np.sqrt(np.mean(out ** 2)) + 1e-12
    return out / r


def decorrelate(x, rng, spread_ms=7.0, taps=10, haas_ms=0.4):
    """Mono one-shot -> stereo (2, n) with two different sparse 'velvet' FIRs.

    Keeps the transient (shared first tap), widens the tail. Offline use.
    """
    n = len(x)
    L = int(spread_ms * SR / 1000.0)
    out = []
    for side in range(2):
        ir = np.zeros(L + 1)
        ir[0] = 0.8
        pos = rng.integers(8, L, taps)
        g = rng.choice([-1.0, 1.0], taps) * np.exp(-pos / (0.45 * L)) * 0.45
        np.add.at(ir, pos, g)
        if side == 1:
            ir = np.concatenate([np.zeros(int(haas_ms * SR / 1000.0)), ir])
        out.append(fft_convolve(x, ir)[:n])
    y = np.stack(out)
    return y / (np.max(np.abs(y)) + 1e-12)


def _hadamard(n):
    h = np.array([[1.0]])
    while h.shape[0] < n:
        h = np.block([[h, h], [h, -h]])
    return h / np.sqrt(n)


class Room:
    """Warehouse reverb: sparse early reflections + modulated 8-line FDN tail.

    Early reflections are a fixed pattern of concrete-wall taps (11 to 140 ms,
    different left and right, darkened); they give the "big empty hall"
    character. The late tail is a feedback delay network (8 lines, Hadamard
    mixing, per-line T60 gains, a gentle damping filter in every line and
    slow delay modulation so the tail never rings metallic). Every FDN line
    is longer than one block, so a whole block is read and written in one
    step. Buffers are linear (shifted once per block) so reads are plain
    strided windows. The input is low-cut so the room never muddies the kick.
    """

    D = np.array([1153, 1399, 1667, 1999, 2381, 2843, 3361, 3989])
    ER_MS = np.array([11.3, 17.9, 23.1, 31.7, 39.2, 47.5, 58.1, 66.4, 79.0, 93.3, 111.0, 139.0])

    def __init__(self, block, seed=7):
        rng = np.random.default_rng(seed)
        self.B = block
        self.ar = np.arange(block)
        self.rows = np.arange(8)[:, None]
        self.mod_depth = 7.0
        # every line must be longer than one block (feedback is read a whole
        # block at a time): for bigger blocks the hall simply gets bigger
        sc = max(1.0, (block + 2 * self.mod_depth + 8) / float(self.D.min()))
        self.D = (self.D * sc).astype(int) | 1
        self.NL = int(self.D.max() + self.mod_depth + 4) + block
        self.buf = np.zeros((8, self.NL))
        self.H = _hadamard(8)
        self.inlp = OnePole(1)
        self.erlp = OnePole(1)
        self.mod_rate = rng.uniform(0.06, 0.3, 8)
        self.mod_ph = rng.uniform(0, TWO_PI, 8)
        self.t = 0.0
        self.inj = rng.choice([-1.0, 1.0], 8) / np.sqrt(8)
        self.outm = np.stack([np.array([1, -1, 1, -1, 1, -1, 1, -1], float),
                              np.array([1, 1, -1, -1, 1, 1, -1, -1], float)]) / np.sqrt(8)
        er = []
        for side in range(2):
            j = rng.uniform(0.9, 1.1, len(self.ER_MS))
            er.append((self.ER_MS * j * SR / 1000.0).astype(int))
        self.er_taps = np.concatenate(er)                     # (24,)
        self.NE = int(self.er_taps.max()) + block
        self.erbuf = np.zeros(self.NE)
        self.er_start = self.NE - block - self.er_taps          # window start per tap
        g = 0.85 * np.exp(-self.ER_MS / 70.0) * rng.choice([-1.0, 1.0], len(self.ER_MS))
        self.er_g = np.zeros((2, 2 * len(self.ER_MS)))
        self.er_g[0, :len(self.ER_MS)] = g
        self.er_g[1, len(self.ER_MS):] = g[::-1] * np.exp(-self.ER_MS[::-1] / 300.0)
        self.last = np.zeros(8)
        self._sw = np.lib.stride_tricks.sliding_window_view

    def reset(self):
        self.buf[:] = 0.0
        self.erbuf[:] = 0.0
        self.last[:] = 0.0
        self.inlp.reset()
        self.erlp.reset()

    def process(self, x, t60=2.5, damp=0.35, er=0.6, late=1.0):
        """x: (n,) mono send. damp 0..0.5 = high-frequency loss per pass.
        Returns (2, n) wet."""
        B = self.B
        x = x[None, :]
        x = x - self.inlp.process(x, lp_coef(170.0))
        xd = self.erlp.process(x, lp_coef(5200.0))[0]       # concrete walls eat the top
        x = x[0]
        # early reflections (linear buffer, shifted by one block)
        eb = self.erbuf
        eb[:-B] = eb[B:]
        eb[-B:] = xd
        e = self.er_g @ self._sw(eb, B)[self.er_start]
        # late FDN: block-constant fractional delay per line (moves < 0.05
        # samples per block, so no zipper), read as two strided windows
        self.t += B / SR
        d = self.D + self.mod_depth * np.sin(self.mod_ph + TWO_PI * self.mod_rate * self.t)
        di = np.floor(d).astype(np.int64)
        fr = (d - di)[:, None]
        buf = self.buf
        buf[:, :-B] = buf[:, B:]
        start = self.NL - B - di                    # index of x(t - di) for the block's first sample
        idx = start[:, None] + self.ar[None, :]
        a = buf[self.rows, idx]
        b = buf[self.rows, idx - 1]
        out = a + fr * (b - a)
        g = 10.0 ** (-3.0 * self.D / (max(0.2, t60) * SR))
        prev = np.concatenate([self.last[:, None], out[:, :-1]], axis=1)
        self.last = out[:, -1].copy()
        filt = out - damp * (out - prev)            # 2-tap damping in the loop
        fb = self.H @ (filt * g[:, None])
        inp = 0.5 * (e[0] + e[1]) + 0.35 * x
        buf[:, -B:] = fb + self.inj[:, None] * inp[None, :]
        return er * e + late * (self.outm @ out)


class PingPong:
    """Stereo ping-pong feedback delay with a darkening, saturating loop."""

    RING = 1 << 17

    def __init__(self, block, sr=SR):
        self.B = block
        self.ar = np.arange(block)
        self.buf = np.zeros((2, self.RING))
        self.w = 0
        self.D = 3 * 6000
        self.lp = OnePole(2)

    def reset(self):
        self.buf[:] = 0.0
        self.lp.reset()

    def process(self, x, D, fb, fc):
        M = self.RING - 1
        w = self.w
        D = max(int(D), self.B)
        out = self.buf[:, (w - D + self.ar) & M]
        if D != self.D:
            old = self.buf[:, (w - self.D + self.ar) & M]
            r = self.ar / float(self.B)
            out = old * (1.0 - r) + out * r
            self.D = D
        f = np.tanh(self.lp.process(out, lp_coef(fc)) * 1.3) / 1.3
        widx = (w + self.ar) & M
        self.buf[0, widx] = x + fb * f[1]
        self.buf[1, widx] = fb * f[0]
        self.w = (w + self.B) & M
        return out


class MonoLow:
    """Folds the side signal below fc to mono (club-style low end)."""

    def __init__(self, fc=120.0):
        self.l1, self.l2 = OnePole(1), OnePole(1)
        self.c = lp_coef(fc)

    def reset(self):
        self.l1.reset()
        self.l2.reset()

    def process(self, x, width=1.0):
        mid = 0.5 * (x[0] + x[1])
        side = 0.5 * (x[0] - x[1])
        s = side[None, :]
        s = (s - self.l2.process(self.l1.process(s, self.c), self.c))[0] * width
        return np.stack([mid + s, mid - s])


class Glue:
    """Gentle bus compressor: RMS detector per 64-sample chunk, soft knee,
    attack/release on the chunk-rate gain (a 16-step scalar loop per block),
    gain interpolated per sample. 2:1 above the threshold by default."""

    def __init__(self, chunk=64, thr_db=-16.0, ratio=2.0, knee=8.0, att=0.010, rel=0.18):
        self.L = chunk
        self.thr, self.ratio, self.knee = thr_db, ratio, knee
        ct = chunk / float(SR)
        self.aa = float(np.exp(-ct / att))
        self.ar_ = float(np.exp(-ct / rel))
        self.g = 0.0          # current gain reduction in dB (<= 0)
        self.lin = 1.0
        self.gr_db = 0.0      # last block's average gain reduction (for metering)

    def reset(self):
        self.g = 0.0
        self.lin = 1.0

    def process(self, x, thr_db=None):
        ch, n = x.shape
        m = n // self.L
        thr = self.thr if thr_db is None else thr_db
        ms = np.mean((x * x).reshape(ch, m, self.L), axis=(0, 2)) + 1e-12
        lv = 10.0 * np.log10(ms) + 3.0                       # RMS -> ~peak-ish dB
        over = lv - thr
        k = self.knee
        slope = 1.0 - 1.0 / self.ratio
        tgt = np.where(over <= -k / 2, 0.0,
                       np.where(over >= k / 2, -slope * over, -slope * (over + k / 2) ** 2 / (2 * k)))
        g = self.g
        out = np.empty(m)
        aa, ar_ = self.aa, self.ar_
        for i in range(m):
            t = tgt[i]
            g = (aa if t < g else ar_) * (g - t) + t
            out[i] = g
        self.g = g
        self.gr_db = float(out.mean())
        lin = 10.0 ** (out / 20.0)
        pts = np.concatenate([[self.lin], lin])
        self.lin = float(lin[-1])
        gs = np.interp(np.arange(1, n + 1) / self.L, np.arange(m + 1), pts)
        return x * gs


def _tp_kernels():
    k = np.arange(-8, 8)
    t = np.stack([np.sinc(k + fr) * np.kaiser(16, 6.0) for fr in (0.5,)])
    return t / t.sum(axis=1, keepdims=True)


class Limiter:
    """Look-ahead brickwall limiter with an inter-sample peak estimate.

    Peaks are measured on the samples and on 4-point interpolated half-sample
    points (a cheap true-peak estimate). The needed gain is the running
    minimum over a W-sample look-ahead window, smoothed with a W-sample moving
    average (which provably never overshoots), then released slowly. Adds W
    samples (1.3 ms) of latency. Ceiling defaults to -1 dBFS so the true peak
    of the output stays below about -0.5 dBFS.
    """

    def __init__(self, ceiling_db=-1.0, look=64, release_s=0.12):
        self.c = 10.0 ** (ceiling_db / 20.0)
        self.W = look
        self.Hn = 2 * look + 8
        self.hist = np.zeros((2, self.Hn))
        self.rel = OnePole(1)
        self.rel.z[:] = 1.0
        self.rc = float(np.exp(-1.0 / (release_s * SR)))
        self.gmin = 1.0

    def reset(self):
        self.hist[:] = 0.0
        self.rel.z[:] = 1.0

    # 4x polyphase (Kaiser-windowed sinc, 16 taps) for the in-between points
    TP = _tp_kernels()

    def process(self, x):
        W = self.W
        n = x.shape[1]
        ext = np.concatenate([self.hist, x], axis=1)
        N = ext.shape[1]
        pk = np.abs(ext).max(axis=0)
        # inter-sample points between ext[i+7] and ext[i+8]: estimate of the true peak
        for c in range(2):
            for h in self.TP:
                v = np.abs(np.convolve(ext[c], h[::-1], "valid"))      # length N - 15
                np.maximum(pk[7:7 + len(v)], v, out=pk[7:7 + len(v)])
                np.maximum(pk[8:8 + len(v)], v, out=pk[8:8 + len(v)])
        g = np.minimum(1.0, self.c / np.maximum(pk, 1e-9))
        s = 1
        mn = g
        while s < W:                              # sliding min, window doubles
            mn = np.minimum(mn[:-s], mn[s:])
            s *= 2
        cs = np.concatenate([[0.0], np.cumsum(mn)])
        j = np.arange(self.Hn - W, self.Hn - W + n)
        box = (cs[j + 1] - cs[j + 1 - W]) / W
        sm = self.rel.process(box[None, :], self.rc)[0]
        gain = np.minimum(box, sm)
        self.gmin = float(gain.min())
        out = ext[:, self.Hn - W:self.Hn - W + n] * gain
        self.hist = ext[:, -self.Hn:].copy()
        return np.clip(out, -0.995, 0.995)
