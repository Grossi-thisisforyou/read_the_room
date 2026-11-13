"""Small camera frames from the N900 -> motion, light and (optionally) faces.

The phone sends {type:"frame", data:{w, h, fmt:"gray8"|"jpeg", b64}}. Frames are
decoded, measured and handed to the visuals as an RGB array, then dropped. No
frame is ever written to disk or kept past the next one.
Face counting uses OpenCV only if python3-opencv is installed; otherwise faces
are simply not reported.
"""
from __future__ import annotations

import base64
import io
import logging

import numpy as np

from .protocol import num

log = logging.getLogger("showengine.frames")

try:  # optional
    import cv2  # type: ignore
    _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if _CASCADE.empty():
        _CASCADE = None
except Exception:  # pragma: no cover - depends on the Pi's packages
    cv2 = None
    _CASCADE = None

MAX_SIDE = 640


class FrameAnalyzer:
    def __init__(self, detect_faces: bool = True):
        self.detect_faces = detect_faces and _CASCADE is not None
        self.prev: np.ndarray | None = None
        self.count = 0

    def reset(self) -> None:
        self.prev = None

    def decode(self, data: dict) -> np.ndarray | None:
        """Return an HxWx3 uint8 RGB array, or None if the frame is unusable."""
        b64 = data.get("b64") or data.get("jpeg")
        if not isinstance(b64, str):
            return None
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            return None
        fmt = data.get("fmt") or ("jpeg" if "jpeg" in data else "gray8")
        if fmt == "gray8":
            w = int(num(data.get("w"), 0, 0, MAX_SIDE))
            h = int(num(data.get("h"), 0, 0, MAX_SIDE))
            if w <= 0 or h <= 0 or len(raw) < w * h:
                return None
            g = np.frombuffer(raw[: w * h], dtype=np.uint8).reshape(h, w)
            return np.repeat(g[:, :, None], 3, axis=2)
        if fmt in ("jpeg", "jpg", "png"):
            try:
                import pygame
                surf = pygame.image.load(io.BytesIO(raw))
                arr = pygame.surfarray.array3d(surf).swapaxes(0, 1)
            except Exception:
                return None
            if arr.shape[0] > MAX_SIDE or arr.shape[1] > MAX_SIDE:
                return None
            return np.ascontiguousarray(arr, dtype=np.uint8)
        return None

    def analyze(self, rgb: np.ndarray) -> dict:
        """Features in the same shape as a sensor message."""
        gray = rgb.mean(axis=2).astype(np.float32)
        small = gray[::2, ::2] if gray.shape[0] > 120 else gray
        out: dict = {"light": round(float(small.mean() / 255.0), 3)}
        if self.prev is not None and self.prev.shape == small.shape:
            diff = np.abs(small - self.prev)
            # fraction of pixels that changed noticeably, scaled so walking ~ 0.5-1
            out["motion"] = round(min(1.0, float((diff > 18).mean()) * 4.0), 3)
        self.prev = small
        self.count += 1
        if self.detect_faces and self.count % 2 == 0:
            g8 = gray.astype(np.uint8)
            faces = _CASCADE.detectMultiScale(g8, scaleFactor=1.15, minNeighbors=4, minSize=(20, 20))
            out["faces"] = int(len(faces))
        return out
