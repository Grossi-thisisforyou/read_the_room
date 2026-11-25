"""The dreaming networks in processes of their own.

In one process the networks, the picture loop, the voice and the ears all wait for each other
(measured on the Pi on 2026-11-25: 1 to 3 pictures a second with someone in the room). Here each
network runs in its own process, on one core at most and at a lower priority, and hands its
pictures over a pipe. The show keeps the same object to talk to (fps, speed, rest, active,
jolt, frame); if the process cannot be started the network runs inside the show as before.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import time

import numpy as np

log = logging.getLogger("showengine.dreamproc")
KEYS = ("fps", "speed", "scale", "rest", "active", "progress")


def _child(conn, kind: str, path: str, fps: float, reach: float) -> None:
    try:
        os.nice(5)
    except OSError:
        pass
    parent = os.getppid()
    try:                                     # die with the show, also when the show is killed
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)
    except Exception:
        pass
    from showengine import duet as D
    net = D._dream_import()
    dec = net.Decoder.load(path) if kind == "wall" else D.GrowingFace(D.FaceModel(path, net))
    dr = D.Dreamer(dec, fps, reach)
    conn.send(("ready", int(dec.latent)))
    last = time.monotonic()
    wait = 0.0
    while True:
        try:
            while conn.poll(wait):
                wait = 0.0
                msg = conn.recv()
                if msg is None:
                    return
                for k, v in msg.items():
                    if k == "jolt":
                        dr.jolt(float(v))
                    elif k == "progress":
                        if hasattr(dec, "progress"):
                            dec.progress = float(v)
                    elif k in KEYS:
                        setattr(dr, k, v)
        except (EOFError, OSError):
            return
        if os.getppid() != parent:
            return
        t0 = time.monotonic()
        if not dr.active:
            last, wait = t0, 0.25
            continue
        img = dr.make(t0 - last)
        last = t0
        spent = time.monotonic() - t0
        try:
            conn.send((img.shape, img.tobytes(), spent * 1000.0))
        except (EOFError, OSError):
            return
        wait = max(spent * float(dr.rest), 1.0 / max(0.2, float(dr.fps)) - spent)


def make(base, kind: str, path: str, fps: float, reach: float = 1.6):
    """A Dreamer whose network lives in another process. `base` is duet.Dreamer."""

    class ProcDreamer(base):
        def __init__(self):
            self.kind, self.path, self.reach = kind, path, reach
            self.fps, self.speed, self.scale, self.rest, self.active = fps, 0.2, 1.0, 1.0, True
            self.progress = 0.0                  # only the face uses it
            self.prev = self.cur = None
            self.t_cur = 0.0
            self.energy, self.centroid = 0.0, (0.0, 0.0)
            self._lock = threading.Lock()
            self._stop = threading.Event()
            self._thread = None
            self.frames, self.ms = 0, 0.0
            self.dec = None
            self._jolts: list = []
            self._proc = self._conn = None
            self._sent: dict = {}
            self.restarts = 0

        def jolt(self, amount: float) -> None:
            self._jolts.append(float(amount))

        def set_decoder(self, dec) -> None:
            pass

        def _spawn(self) -> None:
            ctx = mp.get_context("spawn")
            parent, child = ctx.Pipe()
            env = {k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")}
            os.environ["OPENBLAS_NUM_THREADS"] = os.environ["OMP_NUM_THREADS"] = "1"     # one core each, never more
            try:
                self._proc = ctx.Process(target=_child, args=(child, self.kind, self.path, self.fps, self.reach),
                                         name=f"ij-dream-{self.kind}", daemon=True)
                self._proc.start()
            finally:
                for k, v in env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            child.close()
            self._conn, self._sent = parent, {}

        def start(self) -> None:
            if self._thread is None:
                self._spawn()
                self._thread = threading.Thread(target=self._pump, name=f"ij-dream-{self.kind}", daemon=True)
                self._thread.start()

        def stop(self) -> None:
            self._stop.set()
            try:
                self._conn.send(None)
            except Exception:
                pass

        def _pump(self) -> None:
            while not self._stop.is_set():
                try:
                    now_state = {k: getattr(self, k) for k in KEYS}
                    change = {k: v for k, v in now_state.items() if self._sent.get(k) != v}
                    if self._jolts:
                        change["jolt"] = max(self._jolts)
                        self._jolts = []
                    if change:
                        self._conn.send(change)
                        self._sent.update(now_state)
                    if self._conn.poll(0.1):
                        msg = self._conn.recv()
                        if msg[0] != "ready":
                            shape, raw, ms = msg
                            self.ms = self.ms * 0.9 + ms * 0.1
                            self.push(np.frombuffer(raw, np.uint8).reshape(shape), time.monotonic())
                    elif not self._proc.is_alive():
                        raise EOFError
                except (EOFError, OSError, BrokenPipeError):
                    if self._stop.is_set():
                        return
                    self.restarts += 1
                    log.warning("dream process %s ended; starting it again", self.kind)
                    self._stop.wait(5.0)
                    try:
                        self._spawn()
                    except Exception:
                        log.warning("dream process %s could not be started", self.kind, exc_info=True)
                        self._stop.wait(30.0)

    return ProcDreamer()
