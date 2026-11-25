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
import threading
import time

import numpy as np

log = logging.getLogger("showengine.cover")
PYLIB = os.path.expanduser("~/.local/share/infinite-jest/pylib")
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haar")
FRONT = ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")
SIDE = "haarcascade_profileface.xml"
NET = "centerface.onnx"
LOCK = threading.RLock()     # one for the whole show: OpenCV's finders crash when two threads use them at once
NET_DIRS = [os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dream", "models"),
            HERE, os.path.expanduser("~/models")]


class FaceCover:
    GROW = 0.3           # the block is this much bigger than the face that was found
    SURE = 0.3           # how sure the network must be (low: rather a block too many)
    FINE = True          # enlarge small pictures before looking (finds small faces, costs four times)
    HOLD = 3             # frames a block stays after the face was last found (running footage)

    def __init__(self, models_dir: str | None = None, finder: str = "network"):
        self._lock = LOCK                    # the finders are not safe to use from two threads at once
        self.looked_t = -1e9                 # when it last really looked (frame)
        self.ort = None                      # CenterFace through onnxruntime (the Pi's OpenCV cannot run it)
        self.yunet = None                    # OpenCV's own face network, if its model file is on this machine
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
            try:
                cv2.setNumThreads(1)                         # one core, never all of them (measured on the Pi)
            except Exception:
                pass
            blank = np.zeros((180, 320, 3), np.uint8)
            use_net = finder != "cascade" and os.environ.get("IJ_COVER_NET", "1") != "0"
            for d in (([models_dir] if models_dir else []) + NET_DIRS) if use_net else []:
                p = os.path.join(d, NET)
                if not os.path.isfile(p):
                    continue
                try:                                         # OpenCV's own runner (measured on the Pi: ~0.1 s)
                    self.net = cv2.dnn.readNetFromONNX(p)
                    self._net_boxes(cv2, blank)
                except Exception as e:
                    log.info("cover: the face network does not run with OpenCV (%s)", type(e).__name__)
                    self.net = None
                    try:                                     # the same network through onnxruntime
                        if os.path.isdir(PYLIB) and PYLIB not in sys.path:
                            sys.path.append(PYLIB)
                        import onnxruntime as ort
                        ort.set_default_logger_severity(3)
                        so = ort.SessionOptions()
                        so.intra_op_num_threads = so.inter_op_num_threads = 1
                        self.ort = ort.InferenceSession(p.replace(".onnx", "-dyn.onnx"), so, providers=["CPUExecutionProvider"])
                        self._net_boxes(cv2, blank)
                    except Exception as e2:
                        log.info("cover: nor with onnxruntime (%s)", type(e2).__name__)
                        self.ort = None
                break
            if use_net and self.ort is None and self.net is None and hasattr(cv2, "FaceDetectorYN"):
                import glob
                for p in sorted(glob.glob(os.path.expanduser("~/models/face/*yunet*.onnx"))):
                    try:
                        self.yunet = cv2.FaceDetectorYN.create(p, "", (640, 384), 0.5, 0.3, 50)
                        self._yunet_boxes(cv2, blank)
                        break
                    except Exception as e:
                        log.info("cover: YuNet does not run here (%s)", type(e).__name__)
                        self.yunet = None
            if self.front or self.net is not None or self.ort is not None or self.yunet is not None:
                self.cv2 = cv2
        except Exception:
            log.info("cover: no face finder; a fixed block is used instead", exc_info=True)

    @property
    def finder(self) -> bool:
        return self.cv2 is not None

    @property
    def kind(self) -> str:
        return ("network" if self.ort is not None or self.net is not None else "network (yunet)" if self.yunet is not None
                else "cascade" if self.cv2 is not None else "fixed block")

    def _yunet_boxes(self, cv2, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        h, w = rgb.shape[:2]
        big = cv2.resize(np.ascontiguousarray(rgb[:, :, 2::-1]), (640, 384))
        _, faces = self.yunet.detect(big)
        out = []
        for f in (faces if faces is not None else []):
            x, y, bw, bh = (float(v) for v in f[:4])
            gx, gy = bw * self.GROW, bh * self.GROW
            out.append((max(0.0, (x - gx) / 640), max(0.0, (y - gy * 1.2) / 384),
                        min(1.0, (x + bw + gx) / 640), min(1.0, (y + bh + gy) / 384)))
        return out

    def _net_boxes(self, cv2, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        h, w = rgb.shape[:2]
        k = 2 if w < 480 and self.FINE else 1                    # small faces: look at it twice as large
        wn, hn = int(np.ceil(w * k / 32) * 32), int(np.ceil(h * k / 32) * 32)
        blob = cv2.dnn.blobFromImage(np.ascontiguousarray(rgb[:, :, :3]), 1.0, (wn, hn), (0, 0, 0), swapRB=False, crop=False)
        if self.net is None and self.ort is not None:
            heat, scale, off, _ = self.ort.run(["537", "538", "539", "540"], {"input.1": blob})
        else:
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
        with self._lock:
            return self._boxes(rgb)

    def _boxes(self, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        if self.cv2 is None:
            return [(0.12, 0.04, 0.88, 0.62)]
        cv2 = self.cv2
        for name, fn in (("net", self._net_boxes), ("ort", self._net_boxes), ("yunet", self._yunet_boxes)):
            if getattr(self, name) is None:
                continue
            try:
                return fn(cv2, rgb)
            except Exception:
                log.info("cover: a face finder failed and is switched off", exc_info=True)
                setattr(self, name, None)
        if not self.front:
            self.cv2 = None
            return [(0.12, 0.04, 0.88, 0.62)]
        try:
            return self._cascade_boxes(cv2, rgb)
        except Exception:                    # rather a block too many than a face shown
            log.info("cover: the cascades failed on a picture; it gets the fixed block", exc_info=True)
            return [(0.12, 0.04, 0.88, 0.62)]

    def _cascade_boxes(self, cv2, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
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
        # looking costs a third of a second on the Pi: a few frames spread over the clip, and every
        # frame gets every block that was found
        n = len(frames)
        for i in sorted({0, n // 3, (2 * n) // 3, n - 1}):
            every += self.boxes(frames[i])
            if self.cv2 is None:
                break
        return [self._black(f, every) for f in frames]

    def frame(self, rgb: np.ndarray, look: bool = True) -> np.ndarray:
        """Running footage, frame after frame: a block stays for a while after the face was last found.
        look=False only puts the blocks that are known already (looking costs time). HOLD counts looks."""
        if look:
            found = self.boxes(rgb)
            self.looked_t = time.monotonic()
            with self._lock:
                for b in self._held:
                    b[4] -= 1
                self._held = [b for b in self._held if b[4] > 0] + [list(b) + [self.HOLD] for b in found]
        return self._black(rgb, [tuple(b[:4]) for b in self._held])

    def cut(self) -> None:
        """A new piece of footage starts: forget where the faces were."""
        self._held = []
