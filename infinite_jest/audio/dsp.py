"""Small vectorised DSP toolkit for the INFINITE JEST sound engine.

numpy only (works with numpy 1.24 as shipped on Raspberry Pi OS Bookworm).
Nothing in here loops over individual samples in Python: recursive filters are
solved per chunk in closed form, and feedback effects use delays longer than
one processing block, so each block is a handful of array operations.
"""
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


def fft_convolve(a, b):
    n = len(a) + len(b) - 1
    nfft = _nfft(n)
    return np.fft.irfft(np.fft.rfft(a, nfft) * np.fft.rfft(b, nfft), nfft)[:n]


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


class Reverb:
    """Freeverb-style stereo reverb: 8 damped combs + 2 allpasses per channel.

    Every delay is longer than the processing block, so a whole block of each
    line can be read from history and written back in one vectorised step.
    """

    RING = 4096

    def __init__(self, block, sr=SR):
        s = sr / 44100.0
        combs = (np.array([1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]) * s).astype(int)
        spread = 23
        self.cd = np.concatenate([combs, combs + spread])
        ap = np.array([1093, 1229])  # > block (1024)
        self.ad = np.array([[ap[0], ap[0] + spread], [ap[1], ap[1] + spread]])
        assert self.cd.min() >= block and self.ad.min() >= block
        self.B = block
        self.ar = np.arange(block)
        self.rows16 = np.arange(16)[:, None]
        self.rows2 = np.arange(2)[:, None]
        self.cbuf = np.zeros((16, self.RING))
        self.abuf = np.zeros((2, 2, self.RING))
        self.w = 0
        self.damp = OnePole(16)

    def reset(self):
        self.cbuf[:] = 0.0
        self.abuf[:] = 0.0
        self.damp.reset()

    def process(self, x, fb, damp_fc):
        """x: (2, B) input. Returns (2, B) wet signal."""
        M = self.RING - 1
        w = self.w
        ridx = (w - self.cd[:, None] + self.ar) & M
        out = self.cbuf[self.rows16, ridx]
        filt = self.damp.process(out, lp_coef(damp_fc))
        widx = (w + self.ar) & M
        inp = np.repeat(x * 0.06, 8, axis=0)
        self.cbuf[:, widx] = inp + filt * fb
        y = out.reshape(2, 8, self.B).sum(axis=1)
        for st in range(2):
            buf = self.abuf[st]
            r2 = (w - self.ad[st][:, None] + self.ar) & M
            bo = buf[self.rows2, r2]
            buf[:, widx] = y + bo * 0.5
            y = bo - y
        self.w = (w + self.B) & M
        return y


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
