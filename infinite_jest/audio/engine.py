"""AudioEngine: runs TechnoSynth in its own process and feeds it show state.

The parent (show engine, pygame visuals) only pushes small dicts onto queues;
all synthesis happens in a spawned child process, so audio never competes
with the visuals for the GIL.
"""
import multiprocessing as mp
import os
import queue
import sys
import time

_THREAD_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
_CFG_KEYS = ("audio_device", "audio_sink", "audio_latency_ms", "audio_seed",
             "audio_volume", "master_gain")
_STATE_KEYS = ("visitor_id", "phase", "scene", "intensity", "palette", "tempo", "hook",
               "ocean", "phase_t", "tilt", "tilt_energy", "shake", "steer")
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


def _worker(cfg, q_state, q_sensor, stop_ev, wipe_ev):
    from .synth import TechnoSynth
    from .sinks import NullSink, open_sink
    vol = float(cfg.get("audio_volume", 0.9)) * float(cfg.get("master_gain", 1.0))
    synth = TechnoSynth(seed=int(cfg.get("audio_seed", 0)), volume=vol)
    sink = open_sink(cfg, synth.B)
    print("[audio] sink: %s" % sink.name, file=sys.stderr)
    failed_at = None
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
            block = synth.render_block()
            try:
                sink.write(block)
            except Exception as e:      # device vanished: go silent, retry later
                print("[audio] output error: %s" % e, file=sys.stderr)
                sink.close()
                sink = NullSink(synth.B)
                failed_at = time.monotonic()
            if failed_at and time.monotonic() - failed_at > 10:
                failed_at = None
                sink.close()
                sink = open_sink(cfg, synth.B)
        # short fade so stopping does not click
        synth.mg_target = 0.0
        synth.wiping = False
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


class AudioEngine:
    def __init__(self, config=None):
        config = config or {}
        self.cfg = {k: _plain(config[k]) for k in _CFG_KEYS if k in config}
        self._ctx = mp.get_context("spawn")
        self._proc = None

    @property
    def running(self):
        return self._proc is not None and self._proc.is_alive()

    def start(self):
        if self.running:
            return
        ctx = self._ctx
        self._qs = ctx.Queue(maxsize=4)
        self._qx = ctx.Queue(maxsize=4)
        self._stop = ctx.Event()
        self._wipe = ctx.Event()
        self._proc = ctx.Process(target=_worker, name="ij-audio", daemon=True,
                                 args=(self.cfg, self._qs, self._qx, self._stop, self._wipe))
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

    def on_state(self, state):
        if not self.running or not isinstance(state, dict):
            return
        _put_latest(self._qs, {k: _plain(state[k]) for k in _STATE_KEYS if k in state})

    def on_sensor(self, data):
        if not self.running or not isinstance(data, dict):
            return
        _put_latest(self._qx, {k: _plain(data[k]) for k in _SENSOR_KEYS if k in data})

    def on_wipe(self):
        if self.running:
            self._wipe.set()

    def stop(self):
        if self._proc is None:
            return
        self._stop.set()
        self._proc.join(timeout=3)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=1)
        for q in (self._qs, self._qx):
            q.cancel_join_thread()
            q.close()
        self._proc = None
