"""People in the footage are never recognisable (Baby, 2026-11-25): wherever a face is found, a
black block goes over it before the picture is used anywhere.

Faces are only located (where is a face), never recognised (whose face). The finder is a small
network (CenterFace, MIT licence, the model the "deface" anonymiser uses; it also finds faces
that are turned away or small); the older cascade finder is the reserve. Nothing is kept. In a
short clip every frame gets the blocks found anywhere in the clip, so a face that is missed in
one frame is still covered. If no face finder can be loaded, a broad black block covers the
middle of every picture instead, so the promise holds either way.
"""
from __future__ import annotations

import logging
import os
import sys

import numpy as np

log = logging.getLogger("showengine.cover")
PYLIB = os.path.expanduser("~/.local/share/infinite-jest/pylib")
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haar")
FRONT = ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")
SIDE = "haarcascade_profileface.xml"
NET = "centerface.onnx"
NET_DIRS = [os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dream", "models"),
            HERE, os.path.expanduser("~/models")]


class FaceCover:
    GROW = 0.3           # the block is this much bigger than the face that was found
    SURE = 0.3           # how sure the network must be (low: rather a block too many)
    FINE = True          # enlarge small pictures before looking (finds small faces, costs four times)
    HOLD = 16            # frames a block stays after the face was last found (running footage)

    def __init__(self, models_dir: str | None = None):
        self.net = None                      # CenterFace through OpenCV
        self.cv2 = None
        self.front: list = []
        self.side = None
        self._held: list[list] = []          # [x0, y0, x1, y1, frames left] as shares of the picture
        try:
            try:
                import cv2
            except ImportError:
                if os.path.isdir(PYLIB) and PYLIB not in sys.path:
                    sys.path.append(PYLIB)
                import cv2
            dirs = [HERE, getattr(getattr(cv2, "data", None), "haarcascades", "") or "",
                    "/usr/share/opencv4/haarcascades", "/usr/share/opencv/haarcascades"]

            def load(name):
                for d in dirs:
                    p = os.path.join(d, name)
                    if d and os.path.isfile(p):
                        c = cv2.CascadeClassifier(p)
                        if not c.empty():
                            return c
                return None
            self.front = [c for c in (load(n) for n in FRONT) if c is not None]
            self.side = load(SIDE)
            for d in ([models_dir] if models_dir else []) + NET_DIRS:
                p = os.path.join(d, NET)
                if os.path.isfile(p):
                    try:
                        self.net = cv2.dnn.readNetFromONNX(p)
                        self._net_boxes(cv2, np.zeros((180, 320, 3), np.uint8))      # does it run here?
                    except Exception:
                        log.info("cover: the face network did not load", exc_info=True)
                        self.net = None
                    break
            if self.front or self.net is not None:
                self.cv2 = cv2
        except Exception:
            log.info("cover: no face finder; a fixed block is used instead", exc_info=True)

    @property
    def finder(self) -> bool:
        return self.cv2 is not None

    @property
    def kind(self) -> str:
        return "network" if self.net is not None else "cascade" if self.cv2 is not None else "fixed block"

    def _net_boxes(self, cv2, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        h, w = rgb.shape[:2]
        k = 2 if w < 480 and self.FINE else 1                    # small faces: look at it twice as large
        wn, hn = int(np.ceil(w * k / 32) * 32), int(np.ceil(h * k / 32) * 32)
        blob = cv2.dnn.blobFromImage(np.ascontiguousarray(rgb[:, :, :3]), 1.0, (wn, hn), (0, 0, 0), swapRB=False, crop=False)
        self.net.setInput(blob)
        heat, scale, off, _ = self.net.forward(["537", "538", "539", "540"])
        heat = heat[0, 0]
        out = []
        for cy, cx in zip(*np.where(heat > self.SURE)):
            bh = float(np.exp(min(8.0, float(scale[0, 0, cy, cx]))) * 4)
            bw = float(np.exp(min(8.0, float(scale[0, 1, cy, cx]))) * 4)
            x = (cx + off[0, 1, cy, cx] + 0.5) * 4 - bw / 2
            y = (cy + off[0, 0, cy, cx] + 0.5) * 4 - bh / 2
            gx, gy = bw * self.GROW, bh * self.GROW
            out.append((max(0.0, (x - gx) / wn), max(0.0, (y - gy * 1.2) / hn),
                        min(1.0, (x + bw + gx) / wn), min(1.0, (y + bh + gy) / hn)))
        return out

    def boxes(self, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Faces in the picture as (x0, y0, x1, y1), each 0..1."""
        if self.cv2 is None:
            return [(0.12, 0.04, 0.88, 0.62)]
        cv2 = self.cv2
        if self.net is not None:
            try:
                return self._net_boxes(cv2, rgb)
            except Exception:
                log.info("cover: the face network failed, using the cascades", exc_info=True)
                self.net = None
                if not self.front:
                    self.cv2 = None
                    return self.boxes(rgb)
        g = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY)
        h, w = g.shape
        if w < 640:                          # small faces: look at it twice as large
            g = cv2.resize(g, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
        g = cv2.equalizeHist(g)
        gh, gw = g.shape
        m = max(14, gh // 14)
        found = []
        for c in self.front:
            found += [tuple(r) for r in c.detectMultiScale(g, 1.12, 3, minSize=(m, m))]
        if self.side is not None:
            found += [tuple(r) for r in self.side.detectMultiScale(g, 1.12, 3, minSize=(m, m))]
            fl = g[:, ::-1].copy()
            found += [(gw - x - bw, y, bw, bh) for x, y, bw, bh in self.side.detectMultiScale(fl, 1.12, 3, minSize=(m, m))]
        out = []
        for x, y, bw, bh in found:
            gx, gy = bw * self.GROW, bh * self.GROW
            out.append((max(0.0, (x - gx) / gw), max(0.0, (y - gy * 1.2) / gh),
                        min(1.0, (x + bw + gx) / gw), min(1.0, (y + bh + gy * 1.4) / gh)))
        return out

    @staticmethod
    def _black(rgb: np.ndarray, boxes) -> np.ndarray:
        if not boxes:
            return rgb
        out = np.array(rgb, copy=True)
        h, w = out.shape[:2]
        for x0, y0, x1, y1 in boxes:
            out[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = 0
        return out

    def clip(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        """A short clip: every frame gets every block found anywhere in it."""
        if not frames:
            return frames
        every: list = []
        for f in (frames if len(frames) <= 8 else frames[::2] + frames[-1:]):
            every += self.boxes(f)
            if self.cv2 is None:
                break
        return [self._black(f, every) for f in frames]

    def frame(self, rgb: np.ndarray, look: bool = True) -> np.ndarray:
        """Running footage, frame after frame: a block stays for a while after the face was last found.
        look=False only puts the blocks that are known already (looking costs time)."""
        if look:
            for b in self._held:
                b[4] -= 1
            self._held = [b for b in self._held if b[4] > 0] + [list(b) + [self.HOLD] for b in self.boxes(rgb)]
        return self._black(rgb, [tuple(b[:4]) for b in self._held])

    def cut(self) -> None:
        """A new piece of footage starts: forget where the faces were."""
        self._held = []
