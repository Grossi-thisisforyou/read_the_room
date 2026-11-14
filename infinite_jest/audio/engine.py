"""AudioEngine: runs TechnoSynth in its own process and feeds it show state.

The parent (show engine, pygame visuals) only pushes small dicts onto queues;
all synthesis happens in a spawned child process, so audio never competes
with the visuals for the GIL.

Built for an unattended multi-day show:
  * if no audio device can be opened (USB DAC not plugged in yet, or it
    disappears), the child keeps running silently in real time and retries
    every `audio_retry_s` seconds (7 by default), picking the device up as
    soon as it appears;
  * a watchdog thread in the parent restarts the child if it dies, with
    backoff (1, 2, 4 ... 30 s), logs why, and re-sends the last show state.
    on_state / on_sensor / on_wipe / stop are safe to call at any time,
    including during a restart.
"""
import threading
import multiprocessing as mp
import os
import queue
import sys
import time

_THREAD_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
_CFG_KEYS = ("audio_device", "audio_sink", "audio_latency_ms", "audio_seed",
             "audio_volume", "volume", "master_gain", "audio_retry_s", "audio_test_crash")
_STATE_KEYS = ("visitor_id", "phase", "scene", "intensity", "palette", "tempo", "hook",
               "ocean", "phase_t", "tilt", "tilt_energy", "shake", "steer", "hinge")
_SENSOR_KEYS = ("steer", "tilt", "tilt_energy", "shake", "accel")


def _plain(v, depth=0):
    """Copy to plain picklable python types (defensive against odd objects)."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if depth > 3:
        return None
    if isinstance(v, dict):
        return {str(k): _plain(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x, depth + 1) for x in v]
    try:
        return float(v)
    except Exception:
        return str(v)


def _put_latest(q, item):
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()          # drop the stalest one
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


def _drain(q):
    last = None
    try:
        while True:
            last = q.get_nowait()
    except (queue.Empty, EOFError, OSError):
        pass
    return last


def _volume(cfg):
    """audio_volume, or the show engine's own [audio] volume key."""
    return float(cfg.get("audio_volume", cfg.get("volume", 0.9)))


def _worker(cfg, q_state, q_sensor, stop_ev, wipe_ev, incarnation=0, vol_val=None):
    from .synth import TechnoSynth
    from . import sinks
    gain = float(cfg.get("master_gain", 1.0))
    vol = _volume(cfg)
    synth = TechnoSynth(seed=int(cfg.get("audio_seed", 0)), volume=vol * gain, threaded=True)
    sys.setswitchinterval(0.002)     # the bank thread must not hold the GIL for long
    retry_s = float(cfg.get("audio_retry_s", 7.0))
    want_real = str(cfg.get("audio_sink", "auto")).lower() != "null"
    crash_after = int(cfg.get("audio_test_crash", 0) or 0) if incarnation == 0 else 0
    sink = sinks.open_sink(cfg, synth.B)
    print("[audio] sink: %s" % sink.name, file=sys.stderr)
    retry_at = time.monotonic() + retry_s if (want_real and sink.name == "null") else None
    blocks = 0
    try:
        while not stop_ev.is_set():
            st = _drain(q_state)
            if st is not None:
                synth.set_state(st)
            se = _drain(q_sensor)
            if se is not None:
                synth.set_sensor(se)
            if wipe_ev.is_set():
                wipe_ev.clear()
                synth.wipe()
            if vol_val is not None and vol_val.value != vol:   # control "volume" (glides in the synth)
                vol = vol_val.value
                synth.volume = vol * gain
            block = synth.render_block()
            blocks += 1
            if crash_after and blocks >= crash_after:
                raise RuntimeError("audio_test_crash: simulated child failure")
            try:
                sink.write(block)
            except Exception as e:      # device vanished: go silent, retry later
                print("[audio] output error: %s; retrying every %.1f s" % (e, retry_s), file=sys.stderr)
                sink.close()
                sink = sinks.NullSink(synth.B)
                retry_at = time.monotonic() + retry_s
            if retry_at is not None and time.monotonic() >= retry_at:
                new = sinks.open_sink(cfg, synth.B, quiet=True)
                if new.name != "null":
                    print("[audio] output back: %s" % new.name, file=sys.stderr)
                    sink.close()
                    sink = new
                    retry_at = None
                else:
                    retry_at = time.monotonic() + retry_s
        # short fade so stopping does not click
        synth.mg_target = 0.0
        for _ in range(8):
            synth.mg = max(0.0, synth.mg - 0.15)
            try:
                sink.write(synth.render_block())
            except Exception:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        synth.close()


class AudioEngine:
    def __init__(self, config=None):
        config = config or {}
        self.cfg = {k: _plain(config[k]) for k in _CFG_KEYS if k in config}
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._lock = threading.RLock()
        self._wanted = False
        self._watch = None
        self._last_state = None
        self.restarts = 0
        self.incarnation = 0

    @property
    def running(self):
        p = self._proc
        return p is not None and p.is_alive()

    def _spawn(self):
        ctx = self._ctx
        self._qs = ctx.Queue(maxsize=4)
        self._qx = ctx.Queue(maxsize=4)
        self._stop = ctx.Event()
        self._wipe = ctx.Event()
        self._vol = ctx.Value("d", _volume(self.cfg), lock=False)
        self._proc = ctx.Process(target=_worker, name="ij-audio", daemon=True,
                                 args=(self.cfg, self._qs, self._qx, self._stop, self._wipe,
                                       self.incarnation, self._vol))
        # keep numpy's BLAS single-threaded in the audio child (the Pi also runs an LLM)
        saved = {k: os.environ.get(k) for k in _THREAD_VARS}
        for k in _THREAD_VARS:
            os.environ[k] = "1"
        try:
            self._proc.start()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        if self._last_state is not None:
            _put_latest(self._qs, self._last_state)

    def _close_queues(self):
        for q in (getattr(self, "_qs", None), getattr(self, "_qx", None)):
            if q is not None:
                try:
                    q.cancel_join_thread()
                    q.close()
                except Exception:
                    pass

    def _watchdog(self):
        backoff = 1.0
        healthy_since = time.monotonic()
        while True:
            time.sleep(0.5)
            with self._lock:
                if not self._wanted:
                    return
                p = self._proc
                alive = p is not None and p.is_alive()
                if alive:
                    if time.monotonic() - healthy_since > 60.0:
                        backoff = 1.0            # stable for a minute: reset the backoff
                    continue
                code = p.exitcode if p is not None else None
            print("[audio] child process died (exit code %s); restarting in %.0f s" % (code, backoff),
                  file=sys.stderr)
            time.sleep(backoff)
            backoff = min(30.0, backoff * 2.0)
            with self._lock:
                if not self._wanted:
                    return
                self._close_queues()
                self.incarnation += 1
                self.restarts += 1
                try:
                    self._spawn()
                except Exception as e:
                    print("[audio] restart failed: %r" % (e,), file=sys.stderr)
                healthy_since = time.monotonic()

    def start(self):
        with self._lock:
            if self.running:
                return
            self._wanted = True
            self._spawn()
            if self._watch is None or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._watchdog, name="ij-audio-watchdog", daemon=True)
                self._watch.start()

    def on_state(self, state):
        if not isinstance(state, dict):
            return
        st = {k: _plain(state[k]) for k in _STATE_KEYS if k in state}
        self._last_state = st
        if self.running:
            try:
                _put_latest(self._qs, st)
            except Exception:
                pass

    def on_sensor(self, data):
        if not self.running or not isinstance(data, dict):
            return
        try:
            _put_latest(self._qx, {k: _plain(data[k]) for k in _SENSOR_KEYS if k in data})
        except Exception:
            pass

    def set_volume(self, volume):
        """The engine's control "volume" command, 0..1 (applies smoothly, survives restarts)."""
        try:
            v = min(1.0, max(0.0, float(volume)))
        except (TypeError, ValueError):
            return
        self.cfg["audio_volume"] = v
        if self.running:
            try:
                self._vol.value = v
            except Exception:
                pass

    def on_wipe(self):
        self._last_state = None          # a restarted child must not resurrect the visitor
        if self.running:
            try:
                self._wipe.set()
            except Exception:
                pass

    def stop(self):
        with self._lock:
            self._wanted = False
            if self._proc is None:
                return
            try:
                self._stop.set()
            except Exception:
                pass
            self._proc.join(timeout=3)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=1)
            self._close_queues()
            self._proc = None
