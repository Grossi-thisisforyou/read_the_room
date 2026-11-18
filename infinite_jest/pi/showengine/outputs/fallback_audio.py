"""Built-in fallback audio for the Infinite Jest show engine.

Used when the full audio module is not installed. It synthesises a one-bar 4/4
loop of dark industrial techno with numpy and plays it through pygame.mixer:

  kick    sine sweep with a click, pushed through tanh distortion
  hats    high-passed noise ticks on 8ths, filling in 16ths as intensity rises
  drone   detuned saws on E1 plus a fifth, low-passed and driven by intensity,
          ducked by the kick (sidechain pump)
  rumble  low-passed noise underneath everything
  clang   inharmonic metallic hit on the off-beats in the hook phase
  blips   short high "computing" beeps in the profiling phase

Every component is built so that the bar loops seamlessly (frequencies are
snapped to whole cycles per bar and filtering is done in the FFT domain, which
is circular). A background thread rebuilds the loop only when the tempo, phase
or intensity bucket changes, and queues it on a mixer channel so the swap
lands on a bar boundary. Idle is a very low drone; wipe is a short white-noise
burst, then silence.

If no audio device is available, start() logs a warning and the object
becomes a no-op. Interface: create(config) -> Audio with on_state(state),
start(), stop(), on_wipe().
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading

import numpy as np
import pygame

log = logging.getLogger("showengine.fallback_audio")

SR = 44100
PHASES = ("idle", "approach", "profiling", "hook", "release", "wipe")
# per-phase layer gains and master level
LAYERS = {
    #            kick  half  hat   drone rumble clang blip  level
    "idle":      (0.0, 0,    0.0,  0.55, 0.7,   0.0,  0.0,  0.22),
    "approach":  (0.8, 1,    0.25, 0.6,  0.6,   0.0,  0.0,  0.6),
    "profiling": (0.9, 0,    0.45, 0.6,  0.45,  0.0,  0.35, 0.78),
    "hook":      (1.0, 0,    0.6,  0.8,  0.5,   0.5,  0.0,  1.0),
    "release":   (0.0, 0,    0.15, 0.7,  0.6,   0.15, 0.0,  0.5),
}


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def _num(v, default):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _lowpass(x, fc, sr, res=0.0, order=4):
    """Circular (loop-seamless) low-pass with an optional resonant bump at fc."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    h = 1.0 / (1.0 + (f / max(fc, 1.0)) ** order)
    if res:
        h = h + res * np.exp(-(((f - fc) / (fc * 0.18)) ** 2))
    return np.fft.irfft(np.fft.rfft(x) * h, n)


def synth_bar(sr, tempo, phase, level, seed=0):
    """Return one seamless bar as float32 stereo (n, 2) in -1..1."""
    tempo = _clamp(_num(tempo, 128.0), 60.0, 200.0)
    kick_g, half, hat_g, drone_g, rum_g, clang_g, blip_g, master = LAYERS.get(phase, LAYERS["idle"])
    inten = _clamp(level / 4.0)
    beat = 60.0 / tempo
    n = int(round(sr * beat * 4 / 64.0)) * 64  # FFT-friendly length; tempo error < 0.1%
    T = n / sr
    t = np.arange(n, dtype=np.float64) / sr
    rng = np.random.default_rng(seed)
    left = np.zeros(n)
    right = np.zeros(n)

    def snap(freq):
        return max(1, round(freq * T)) / T

    def saw(freq, ph=0.0):
        return 2.0 * ((snap(freq) * t + ph) % 1.0) - 1.0

    # sidechain pump from the kick grid
    pump = 1.0 - (0.65 * kick_g) * np.exp(-((t % beat) / beat) * 7.0)

    # drone: detuned saws on E1 plus a fifth, filter and drive follow intensity
    f0 = 41.2
    fc = 70 + 1100 * inten ** 1.6
    drive = 1.5 + 7.0 * inten
    for side, det, ph in ((left, (1.0, 1.008, 2.003), 0.0), (right, (0.994, 1.0, 1.498), 0.37)):
        raw = saw(f0 * det[0], ph) + saw(f0 * det[1], ph * 0.5) + 0.5 * saw(f0 * det[2], ph * 0.3)
        d = _lowpass(raw, fc, sr, res=0.6 + 1.2 * inten)
        d = np.tanh(drive * d) / math.tanh(drive)
        side += drone_g * 0.5 * d * pump

    # rumble
    rum = _lowpass(rng.standard_normal(n), 55 + 90 * inten, sr)
    rum *= rum_g * 0.9 / (np.abs(rum).max() + 1e-9)
    left += rum * pump
    right += np.roll(rum, n // 7) * pump

    # kick
    if kick_g:
        period = beat * (2 if half else 1)
        tt = t % period
        ph = 2 * math.pi * (44 * tt + (160 / 32.0) * (1 - np.exp(-32 * tt)))
        k = np.sin(ph) * np.exp(-tt * (6.0 - 2.0 * inten)) + 0.5 * np.exp(-tt * 300)
        kdrive = 1.5 + 5 * inten
        k = np.tanh(kdrive * k) / math.tanh(kdrive) * kick_g * 0.95
        left += k
        right += k

    step = beat / 4.0
    tt16 = t % step
    idx16 = np.minimum((t // step).astype(int), 15)

    # hats: high-passed noise
    if hat_g:
        mask = np.zeros(16)
        mask[2::4] = 1.0
        extra = rng.random(16) < 0.15 + 0.7 * inten
        mask = np.maximum(mask, extra * 0.45)
        mask[0::4] *= 0.3
        noise = rng.standard_normal(n)
        hp = noise - _lowpass(noise, 6500, sr, order=2)
        h = hp * np.exp(-tt16 * (90 - 40 * inten)) * mask[idx16] * hat_g * 0.35
        left += h * 0.8
        right += np.roll(h, 40)

    # metallic clang on the "and" of 2 and 4
    if clang_g:
        hits = (6, 14) if inten < 0.6 else (3, 6, 11, 14)
        tc = np.full(n, 10.0)
        for hstep in hits:
            s0 = hstep * step
            m = t >= s0
            tc = np.where(m & (t - s0 < tc), t - s0, tc)
        env = np.exp(-tc * 7.0)
        base = 210.0
        c = sum(a * np.sin(2 * math.pi * snap(base * r) * t)
                for r, a in ((1.0, 1.0), (2.76, 0.7), (5.40, 0.5), (8.93, 0.35), (13.3, 0.2)))
        c = np.tanh(2.5 * c * env) * clang_g * 0.5
        left += c
        right += np.roll(c, 300)

    # profiling blips
    if blip_g:
        on = rng.random(16) < 0.35 + 0.3 * inten
        freqs = rng.choice([1320.0, 1760.0, 2640.0, 3520.0], 16)
        f = freqs[idx16]
        b = np.sin(2 * math.pi * f * tt16) * np.exp(-tt16 * 70) * on[idx16] * blip_g * 0.4
        left += np.roll(b, 0)
        right += np.roll(b, 220)

    out = np.stack([left, right], axis=1)
    out = np.tanh(out * 1.1) * (0.9 * master)
    return out.astype(np.float32)


def noise_burst(sr, seconds=0.35, seed=None):
    n = int(sr * seconds)
    t = np.arange(n) / sr
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1, 1, (n, 2)) * np.exp(-t * 7.0)[:, None] * 0.9
    return x.astype(np.float32)


class Audio:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.volume = _clamp(_num(self.config.get("volume", 0.8), 0.8))
        self._ok = False
        self._own_mixer = False
        self._thread = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._halt = threading.Event()
        self._want = ("idle", 128, 1, 0)
        self._wipe_req = False
        self._last_phase = None
        self._loop_ch = None
        self._fx_ch = None
        self._current = None
        self._have = None
        self._sr = SR
        self._channels = 2

    # ------------------------------------------------------------ interface
    @property
    def active(self):
        return self._ok

    def start(self):
        if self._ok:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=1024)
                self._own_mixer = True
            freq, size, channels = pygame.mixer.get_init()
            if size not in (-16, 16):
                raise RuntimeError(f"unsupported mixer sample size {size}")
            self._sr, self._channels = int(freq), int(channels)
            if pygame.mixer.get_num_channels() < 8:
                pygame.mixer.set_num_channels(8)
            pygame.mixer.set_reserved(2)
            self._loop_ch = pygame.mixer.Channel(0)
            self._fx_ch = pygame.mixer.Channel(1)
        except Exception as e:  # no device, no driver, unexpected format
            log.warning("fallback audio disabled: %s", e)
            self._ok = False
            return
        self._ok = True
        self._halt.clear()
        self._have = None
        self._thread = threading.Thread(target=self._run, name="fallback-audio", daemon=True)
        self._thread.start()

    def stop(self):
        if not self._ok:
            return
        self._halt.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None
        try:
            for ch in (self._loop_ch, self._fx_ch):
                if ch is not None:
                    ch.stop()
            if self._own_mixer:
                pygame.mixer.quit()
                self._own_mixer = False
        except pygame.error as e:
            log.debug("mixer stop: %s", e)
        self._current = None
        self._ok = False

    def on_state(self, state):
        state = state or {}
        phase = state.get("phase") or "idle"
        if phase not in PHASES:
            phase = "idle"
        if phase == "wipe":
            if self._last_phase != "wipe":
                self.on_wipe()
            self._last_phase = phase
            return
        self._last_phase = phase
        tempo = int(round(_clamp(_num(state.get("tempo"), 128.0), 60.0, 200.0)))
        bucket = int(_clamp(_num(state.get("intensity"), 0.35)) * 4.999)
        vid = state.get("visitor_id")
        seed = int(hashlib.sha1(str(vid).encode()).hexdigest()[:8], 16) if vid else 0
        with self._lock:
            self._want = (phase, tempo, bucket, seed)
        self._wake.set()

    def on_wipe(self):
        with self._lock:
            self._wipe_req = True
            self._want = ("wipe", 0, 0, 0)
        self._last_phase = "wipe"
        self._wake.set()

    # --------------------------------------------------------------- worker
    def _make_sound(self, data):
        x = np.clip(data * (32767 * self.volume), -32767, 32767).astype(np.int16)
        if self._channels == 1:
            x = x.mean(axis=1).astype(np.int16)
        elif self._channels > 2:
            x = np.tile(x, (1, self._channels // 2 + 1))[:, : self._channels]
        return pygame.sndarray.make_sound(np.ascontiguousarray(x))

    def _run(self):
        while not self._halt.is_set():
            self._wake.wait(0.05)
            self._wake.clear()
            try:
                self._tick()
            except Exception:  # never let the audio thread take the show down
                log.exception("fallback audio tick failed")
                self._halt.wait(0.5)

    def _tick(self):
        with self._lock:
            want = self._want
            wipe = self._wipe_req
            self._wipe_req = False
        if wipe:
            self._loop_ch.stop()
            self._current = None
            self._fx_ch.play(self._make_sound(noise_burst(self._sr)))
            self._have = want
        if want != self._have:
            self._have = want
            if want[0] == "wipe":
                self._current = None
                self._loop_ch.fadeout(300)
            else:
                phase, tempo, bucket, seed = want
                snd = self._make_sound(synth_bar(self._sr, tempo, phase, bucket, seed))
                self._current = snd
                if self._loop_ch.get_busy():
                    self._loop_ch.queue(snd)  # replaces any queued bar; swaps at the bar line
                else:
                    self._loop_ch.play(snd)
        cur = self._current
        if cur is not None and self._loop_ch.get_queue() is None:
            if self._loop_ch.get_busy():
                self._loop_ch.queue(cur)
            else:
                self._loop_ch.play(cur)


def create(config):
    return Audio(config)
