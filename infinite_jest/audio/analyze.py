"""Measure a render: loudness, peaks, clicks and how much it evolves.

    python3 -m infinite_jest.audio.analyze set.wav [--block 1024]

Reports (numpy only):
  * integrated loudness (ITU BS.1770 K-weighting with gating, in LUFS) and
    the loudest 3-second stretch
  * true peak (4x oversampled, dBTP), DC offset per channel
  * block-edge clicks: compares the waveform's 'jerk' at every audio block
    boundary with everywhere else (a ratio near 1.0 means no edge artefacts)
  * per minute: loudness, spectral centroid, onsets per second, tempo
    estimate, strongest pitch classes, stereo width and low-end mono-ness
  * repetition: chroma and rhythm similarity between minutes, and the most
    similar pair of 8-second windows at least 30 s apart
"""
import argparse
import sys
import wave

import numpy as np

SR = 48000
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def load(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768.0
    x = x.reshape(-1, ch).T
    if ch == 1:
        x = np.vstack([x, x])
    return x, sr


def _biquad_resp(b, a, f, sr):
    z = np.exp(-2j * np.pi * f / sr)
    return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)


def k_weight(f, sr=48000):
    h1 = _biquad_resp([1.53512485958697, -2.69169618940638, 1.19839281085285],
                      [1.0, -1.69065929318241, 0.73248077421585], f, sr)
    h2 = _biquad_resp([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], f, sr)
    return np.abs(h1 * h2) ** 2


def block_loudness(x, sr, win=0.4, hop=0.1):
    """Mean-square K-weighted power per window (via Parseval), both channels summed."""
    n = int(win * sr)
    h = int(hop * sr)
    starts = np.arange(0, x.shape[1] - n + 1, h)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    W = k_weight(f, sr)
    W[1:-1] *= 2.0
    out = np.empty(len(starts))
    for i0 in range(0, len(starts), 256):
        st = starts[i0:i0 + 256]
        idx = st[:, None] + np.arange(n)[None, :]
        p = 0.0
        for c in range(2):
            X = np.fft.rfft(x[c][idx], axis=1)
            p = p + (np.abs(X) ** 2 * W).sum(axis=1) / (n * n)
        out[i0:i0 + 256] = p
    return out


def lufs(pw):
    return -0.691 + 10.0 * np.log10(np.maximum(pw, 1e-12))


def integrated(pw):
    l = lufs(pw)
    g = pw[l > -70.0]
    if not len(g):
        return -70.0
    rel = lufs(np.mean(g)) - 10.0
    g = pw[(l > -70.0) & (l > rel)]
    return float(lufs(np.mean(g))) if len(g) else -70.0


def true_peak(x, chunk=SR * 4):
    pk = 0.0
    for i in range(0, x.shape[1], chunk):
        seg = x[:, max(0, i - 64):i + chunk + 64]
        n = seg.shape[1]
        X = np.fft.rfft(seg, axis=1)
        Z = np.zeros((2, 2 * n + 1), np.complex128)
        Z[:, :X.shape[1]] = X * 4.0
        y = np.fft.irfft(Z, 4 * n, axis=1)
        pk = max(pk, float(np.max(np.abs(y[:, 256:-256]))) if y.shape[1] > 600 else float(np.max(np.abs(y))))
    return pk


def edge_clicks(x, block):
    d = np.abs(np.diff(x, 2, axis=1)).max(axis=0)       # jerk, index i ~ sample i+1
    n = len(d)
    edges = np.arange(block - 1, n, block)
    edges = edges[edges < n]
    near = np.concatenate([edges - 1, edges, edges + 1])
    near = near[(near >= 0) & (near < n)]
    mask = np.ones(n, bool)
    mask[near] = False
    base = d[mask]
    ref = np.percentile(base, 99.9)
    return (float(np.mean(d[near]) / (np.mean(base) + 1e-12)),
            int(np.sum(d[edges] > ref)), len(edges), float(np.sum(base > ref)) / len(base) * len(edges))


def stft_mag(m, sr, n=4096, hop=2048):
    frames = 1 + (len(m) - n) // hop
    if frames < 1:
        return np.zeros((0, n // 2 + 1))
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.abs(np.fft.rfft(m[idx] * np.hanning(n), axis=1))


def onset_env(m, sr, hop=512, n=1024):
    frames = 1 + (len(m) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    S = np.log1p(10.0 * np.abs(np.fft.rfft(m[idx] * np.hanning(n), axis=1))[:, 1:200])
    flux = np.maximum(0.0, np.diff(S, axis=0)).sum(axis=1)
    return flux, sr / hop


def tempo(flux, fps):
    f = flux - np.convolve(flux, np.ones(16) / 16, "same")
    f = np.maximum(f, 0)
    ac = np.correlate(f, f, "full")[len(f) - 1:]
    lags = np.arange(len(ac)) / fps
    ok = (lags > 60.0 / 150.0) & (lags < 60.0 / 112.0)
    if not ok.any() or ac[0] <= 0:
        return 0.0, 0.0
    i = np.argmax(np.where(ok, ac, -np.inf))
    return 60.0 / lags[i], float(ac[i] / ac[0])


def onsets_per_s(flux, fps):
    thr = np.median(flux) + 1.5 * np.std(flux)
    pk = (flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) & (flux[1:-1] > thr)
    return float(pk.sum()) / (len(flux) / fps)


def chroma(m, sr, n=16384):
    """Pitch-class profile from a long FFT (2.9 Hz bins, so low notes are not
    biased towards whichever pitch class a coarse bin happens to land on)."""
    S = stft_mag(m, sr, n, n // 2)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    ok = (f > 50) & (f < 2000)
    pc = (np.round(12 * np.log2(f[ok] / 440.0)) + 9) % 12
    C = np.zeros(12)
    E = (S[:, ok] ** 2).sum(axis=0)
    np.add.at(C, pc.astype(int), E)
    return C / (np.linalg.norm(C) + 1e-12)


def band_env(m, sr, win=0.05):
    """Log energy in 6 bands every 50 ms (rhythm/timbre fingerprint)."""
    n = 2048
    hop = int(win * sr)
    frames = 1 + (len(m) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    S = np.abs(np.fft.rfft(m[idx] * np.hanning(n), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / sr)
    edges = [20, 120, 400, 1200, 3500, 8000, 20000]
    B = np.stack([S[:, (f >= a) & (f < b)].sum(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    return np.log10(B + 1e-9), 1.0 / win


def most_similar(env, fps, win_s=8.0, min_gap_s=30.0, step_s=2.0):
    w = int(win_s * fps)
    st = int(step_s * fps)
    starts = np.arange(0, env.shape[0] - w, st)
    if len(starts) < 3:
        return 0.0, 0, 0
    # per-band means removed: this compares how each band moves in time (the
    # groove / events), not the overall spectral shape, so two sustained drone
    # passages in different keys are not reported as a loop
    W3 = np.stack([env[s:s + w] for s in starts])
    W3 = W3 - W3.mean(axis=1, keepdims=True)
    V = W3.reshape(len(starts), -1)
    act = V.std(axis=1) > 0.05
    V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-12
    C = V @ V.T
    gap = np.abs(starts[:, None] - starts[None, :]) < min_gap_s * fps
    C[gap] = -1.0
    C[~act, :] = -1.0
    C[:, ~act] = -1.0
    i, j = np.unravel_index(np.argmax(C), C.shape)
    return float(C[i, j]), starts[i] / fps, starts[j] / fps


def report(path, block=1024, per=60.0, out=sys.stdout):
    x, sr = load(path)
    dur = x.shape[1] / sr
    pr = lambda *a: print(*a, file=out)
    pr("file: %s  (%.1f s, %d Hz)" % (path, dur, sr))
    pw = block_loudness(x, sr)
    il = integrated(pw)
    st = np.convolve(pw, np.ones(30) / 30, "valid") if len(pw) > 30 else pw
    tp = true_peak(x)
    pr("integrated loudness: %.1f LUFS   loudest 3 s: %.1f LUFS" % (il, lufs(st.max())))
    pr("true peak: %.2f dBTP   sample peak: %.2f dBFS" % (20 * np.log10(tp + 1e-12), 20 * np.log10(np.abs(x).max() + 1e-12)))
    pr("DC offset: L %.5f  R %.5f" % (x[0].mean(), x[1].mean()))
    r, hits, ne, expect = edge_clicks(x, block)
    pr("block edges: jerk ratio %.3f (1.0 = same as elsewhere); edges above the 99.9th percentile: %d of %d (chance level ~%.0f)"
       % (r, hits, ne, expect))
    m = 0.5 * (x[0] + x[1])
    flux, fps = onset_env(m, sr)
    env, efps = band_env(m, sr)
    pr("")
    pr(" min | LUFS  | centroid Hz | onsets/s | bpm (conf) | top pitch classes | width | low mono")
    rows = []
    nper = int(per * sr)
    for k in range(int(np.ceil(x.shape[1] / nper))):
        a, b = k * nper, min(x.shape[1], (k + 1) * nper)
        if b - a < sr * 10:
            break
        seg = x[:, a:b]
        mm = m[a:b]
        S = stft_mag(mm, sr)
        f = np.fft.rfftfreq(4096, 1.0 / sr)
        cen = float((S * f).sum() / (S.sum() + 1e-12))
        fl = flux[int(a / sr * fps):int(b / sr * fps)]
        bpm, conf = tempo(fl, fps)
        ons = onsets_per_s(fl, fps)
        ch = chroma(mm, sr)
        top = "-".join(NOTES[i] for i in np.argsort(ch)[::-1][:3])
        mid = seg[0] + seg[1]
        side = seg[0] - seg[1]
        width = float(np.sqrt(np.mean(side ** 2) / (np.mean(mid ** 2) + 1e-12)))
        Sl = np.fft.rfft(seg, axis=1)
        fr = np.fft.rfftfreq(seg.shape[1], 1.0 / sr)
        lo = fr < 100
        lm = float(np.real(np.sum(Sl[0, lo] * np.conj(Sl[1, lo]))) /
                   (np.sqrt(np.sum(np.abs(Sl[0, lo]) ** 2) * np.sum(np.abs(Sl[1, lo]) ** 2)) + 1e-12))
        pwk = pw[int(a / sr / 0.1):int(b / sr / 0.1)]
        rows.append(dict(ch=ch, fl=fl, env=env[int(a / sr * efps):int(b / sr * efps)]))
        pr(" %3d | %5.1f | %11.0f | %8.2f | %5.1f (%.2f) | %-17s | %.2f  | %.3f"
           % (k, integrated(pwk) if len(pwk) else -70, cen, ons, bpm, conf, top, width, lm))
    pr("")
    if len(rows) >= 3:
        pr("chroma cosine similarity between minutes (1.0 = same harmony):")
        C = np.array([[float(r1["ch"] @ r2["ch"]) for r2 in rows] for r1 in rows])
        for i, r1 in enumerate(C):
            pr("   %2d: %s" % (i, " ".join("%.2f" % v for v in r1)))
        if len(rows) > 8:
            a, b = rows[2], rows[8]
            n = min(len(a["env"]), len(b["env"]))
            ea, eb = a["env"][:n], b["env"][:n]
            ea = (ea - ea.mean(0)) / (ea.std(0) + 1e-9)
            eb = (eb - eb.mean(0)) / (eb.std(0) + 1e-9)
            best = max(float(np.mean(ea[max(0, s):n + min(0, s)] * eb[max(0, -s):n - max(0, s)]))
                       for s in range(-40, 41))
            pr("minute 2 vs minute 8: chroma %.2f, best aligned band-envelope correlation %.2f"
               % (float(a["ch"] @ b["ch"]), best))
    c, t1, t2 = most_similar(env, efps)
    pr("most similar 8 s windows >= 30 s apart (band movement, per-band means removed): r = %.2f at %.0f s and %.0f s "
       "(1.0 = an exact repeat)" % (c, t1, t2))
    return dict(lufs=il, tp=tp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--block", type=int, default=1024)
    ap.add_argument("--per", type=float, default=60.0, help="seconds per row")
    a = ap.parse_args(argv)
    report(a.wav, a.block, a.per)


if __name__ == "__main__":
    sys.exit(main())
