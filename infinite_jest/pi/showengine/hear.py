"""The room understands what is said to it (Baby's decision, 2026-11-25).

Only after the room has asked a question, and only for the seconds it waits for the
answer: the sound of those seconds is taken from the room's microphone program
(ij-room keeps the last half minute in memory and hands it over on 127.0.0.1), turned
into text by a small speech model on the Pi itself (faster-whisper, offline), and the
sound is dropped at once. The text lives in memory for the visit and is wiped with it.
Nothing is written to disk, nothing leaves the Pi, and nothing is logged.

Needs: the faster_whisper package (wheels unpacked to ~/.local/share/infinite-jest/pylib
by dream/install_ai.sh) and a model folder (model.bin etc.) in ~/models/whisper/<name>/.
Without them the room goes on as before: it hears that someone speaks, not what.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading

import numpy as np

log = logging.getLogger("showengine.hear")
PYLIB = os.path.expanduser("~/.local/share/infinite-jest/pylib")
MODEL_DIRS = ("~/models/whisper", "/mnt/ij-stick/ij-offline/whisper")
RATE = 16000
# what small speech models make up when there was no real speech
GHOSTS = {"you", "thank you", "thanks for watching", "thank you for watching", "bye", "so", "the", "okay",
          "thanks", "i", "uh", "um", "hmm", "oh"}


def find_model(want: str = "") -> str | None:
    for d in MODEL_DIRS:
        d = os.path.expanduser(d)
        try:
            names = sorted(n for n in os.listdir(d) if os.path.exists(os.path.join(d, n, "model.bin")))
        except OSError:
            continue
        for n in names:
            if want and want in n:
                return os.path.join(d, n)
        if names:
            return os.path.join(d, names[0])
    return None


def fetch(seconds: float, addr=("127.0.0.1", 8769), timeout: float = 2.0) -> np.ndarray | None:
    """The last `seconds` of the microphone from ij-room's memory: float32 mono at 16 kHz."""
    try:
        with socket.create_connection(addr, timeout=timeout) as s:
            s.sendall(("%.1f\n" % max(0.5, min(30.0, seconds))).encode())
            s.settimeout(timeout)
            parts = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                parts.append(b)
        raw = b"".join(parts)
        raw = raw[: len(raw) // 2 * 2]
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0 if raw else None
    except OSError:
        return None


def clean(text: str) -> str:
    text = " ".join(str(text or "").split()).strip(" .,!?-").strip()
    if text.lower() in GHOSTS or len(text) < 2 or text.startswith(("[", "(")):
        return ""
    return text[:160]


class Hearing:
    def __init__(self, cfg: dict | None = None, model=None, fetch_fn=None):
        cfg = cfg or {}
        self.on = bool(cfg.get("speech_to_text", True))
        self.lang = cfg.get("speech_language", "en") or None   # "" in the config: the model works it out
        self.threads = int(cfg.get("speech_threads", 2))
        self.want = str(cfg.get("speech_model", ""))
        self._model = model
        self._tried = model is not None
        self._fetch = fetch_fn or fetch
        self._lock = threading.Lock()
        self.busy = False
        self.heard = 0
        self.ms = 0.0

    def available(self) -> bool:
        return self.on and (self._model is not None or (not self._tried and find_model(self.want) is not None))

    def warm(self) -> None:
        """Load the model before the first visitor (a few seconds)."""
        if self.on and not self._tried:
            threading.Thread(target=self._load, name="ij-hear-load", daemon=True).start()

    def _load(self):
        with self._lock:
            if self._tried:
                return self._model
            self._tried = True
            path = find_model(self.want)
            if path is None:
                return None
            try:
                if os.path.isdir(PYLIB) and PYLIB not in sys.path:
                    sys.path.append(PYLIB)
                from faster_whisper import WhisperModel
                self._model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=self.threads)
                log.info("speech to text: %s", os.path.basename(path))
            except Exception as e:
                log.warning("speech to text is not available (%s: %s)", type(e).__name__, e)
            return self._model

    def listen(self, seconds: float, done) -> bool:
        """Turn the last `seconds` into text and call done(text) from a helper thread
        ("" when nothing was understood). False when it cannot even try."""
        if not self.on or self.busy or (self._tried and self._model is None):
            return False
        self.busy = True
        threading.Thread(target=self._run, args=(seconds, done), name="ij-hear", daemon=True).start()
        return True

    def _run(self, seconds: float, done) -> None:
        import time
        text = ""
        try:
            model = self._load()
            audio = self._fetch(seconds) if model is not None else None
            if audio is not None and len(audio) > RATE // 3:
                t0 = time.perf_counter()
                segs, _info = model.transcribe(audio, language=self.lang, beam_size=1, vad_filter=False,
                                               condition_on_previous_text=False, without_timestamps=True)
                text = clean(" ".join(s.text for s in segs if getattr(s, "no_speech_prob", 0.0) < 0.6))
                self.ms = (time.perf_counter() - t0) * 1000.0
                audio = None                                   # the sound is gone; only the words remain
                if text:
                    self.heard += 1
        except Exception as e:
            log.warning("speech to text failed (%s)", type(e).__name__)   # never the words, never the sound
        finally:
            self.busy = False
            try:
                done(text)
            except Exception:
                pass
