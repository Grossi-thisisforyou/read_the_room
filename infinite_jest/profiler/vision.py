"""Tiny camera analysis for 160x120 grayscale frames from the N900.

Pure Python (no numpy needed) so it runs anywhere; at 160x120 and 4 fps this
costs a few milliseconds per frame on a Pi 5. It produces the "vision"
features the profiler uses: present, cx, size, motion, face.

- motion: mean absolute difference to the previous frame.
- present / cx / size: pixels that differ from a slowly updated background
  ("foreground"), their horizontal centre and vertical extent.
- face: only if OpenCV is installed, a Haar cascade *detection* (a box, never
  identity, no landmarks, no templates). Without OpenCV, face is None and the
  gaze feature is simply missing.

Frames are held only as the previous frame and the background, in memory.
"""

import base64

try:  # optional
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if _CASCADE.empty():
        _CASCADE = None
except Exception:  # pragma: no cover - depends on the Pi
    cv2 = None
    _CASCADE = None

try:  # optional speed-up; the pure-Python path below gives the same numbers
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover
    _np = None

STEP = 2          # sample every 2nd pixel in both directions
DIFF_T = 28       # grey levels that count as "changed"
BG_RATE = 0.03    # background learning rate per frame


class Vision:
    def __init__(self, face_every=2):
        self.face_every = face_every
        self.reset()

    def reset(self):
        self.prev = None
        self.bg = None
        self.n = 0
        self.last_face = None

    def frame(self, data):
        """data = frame message data. Returns a vision dict or None."""
        w, h = int(data.get("w", 0)), int(data.get("h", 0))
        fmt = data.get("fmt", "gray8")
        try:
            raw = base64.b64decode(data.get("b64", ""))
        except (ValueError, TypeError):
            return None
        if fmt == "jpeg":
            raw, w, h = _decode_jpeg(raw)
            if raw is None:
                return None
        if w <= 0 or h <= 0 or len(raw) < w * h:
            return None
        return self.gray(raw, w, h)

    def gray(self, px, w, h):
        if _np is not None and isinstance(px, (bytes, bytearray, memoryview)):
            return self._gray_np(px, w, h)
        self.n += 1
        samples = [(x, y, px[y * w + x]) for y in range(0, h, STEP) for x in range(0, w, STEP)]
        vals = [s[2] for s in samples]
        motion = 0.0
        if self.prev is not None and len(self.prev) == len(vals):
            motion = sum(abs(a - b) for a, b in zip(vals, self.prev)) / len(vals) / 40.0
        if self.bg is None or len(self.bg) != len(vals):
            self.bg = [float(v) for v in vals]
        fg_n = 0
        sx = 0
        ymin, ymax = h, -1
        bg = self.bg
        for i, (x, y, v) in enumerate(samples):
            if abs(v - bg[i]) > DIFF_T:
                fg_n += 1
                sx += x
                if y < ymin:
                    ymin = y
                if y > ymax:
                    ymax = y
            bg[i] += (v - bg[i]) * BG_RATE
        self.prev = vals
        frac = fg_n / len(samples)
        present = frac > 0.02
        out = {"kind": "vision", "present": present, "motion": round(min(1.0, motion), 3)}
        if present:
            out["cx"] = round(sx / fg_n / w, 3)
            out["size"] = round((ymax - ymin + STEP) / h, 3)
        else:
            out["cx"], out["size"] = 0.5, 0.0
        return self._finish(out, px, w, h)


    def _finish(self, out, px, w, h):
        if _CASCADE is not None:
            if self.n % self.face_every == 0:
                self.last_face = _detect_face(px, w, h)
            out["face"] = bool(self.last_face)
            if self.last_face:  # a face box is a better distance cue than blobs
                out["size"] = max(out["size"], round(min(1.0, self.last_face * 3.0), 3))
                out["present"] = True
        return out

    def _gray_np(self, px, w, h):
        """Vision.gray with numpy: the same numbers ~50x faster (2 ms -> 0.05 ms
        per 160x120 frame here; the pure-Python loop costs ~5 ms on a Pi 5 and
        ~20 ms at 320x240, on the frame loop's thread)."""
        self.n += 1
        img = _np.frombuffer(bytes(px[: w * h]), _np.uint8).reshape(h, w)
        vals = img[::STEP, ::STEP].astype(_np.int64).ravel()
        n = len(vals)
        motion = 0.0
        prev = self.prev
        if prev is not None and len(prev) == n:
            prev = _np.asarray(prev, _np.int64)
            motion = int(_np.abs(vals - prev).sum()) / n / 40.0
        if self.bg is None or len(self.bg) != n:
            self.bg = vals.astype(_np.float64)
        bg = _np.asarray(self.bg, _np.float64)
        fg = _np.abs(vals - bg) > DIFF_T
        self.bg = bg + (vals - bg) * BG_RATE
        self.prev = vals
        fg_n = int(fg.sum())
        frac = fg_n / n
        present = frac > 0.02
        out = {"kind": "vision", "present": present, "motion": round(min(1.0, motion), 3)}
        if present:
            cols = _np.arange(0, w, STEP)
            rows = _np.arange(0, h, STEP)
            fg2 = fg.reshape(len(rows), len(cols))
            xs = _np.broadcast_to(cols, fg2.shape)[fg2]
            ys = rows[fg2.any(axis=1)]
            out["cx"] = round(int(xs.sum()) / fg_n / w, 3)
            out["size"] = round((int(ys.max()) - int(ys.min()) + STEP) / h, 3)
        else:
            out["cx"], out["size"] = 0.5, 0.0
        return self._finish(out, px, w, h)


def _decode_jpeg(raw):
    if cv2 is None:
        return None, 0, 0
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, 0, 0
    h, w = img.shape
    return img.tobytes(), w, h


def _detect_face(px, w, h):
    """Return the height fraction of the largest frontal face box, or 0."""
    img = np.frombuffer(bytes(px[: w * h]), np.uint8).reshape(h, w)
    faces = _CASCADE.detectMultiScale(img, 1.15, 4, minSize=(16, 16))
    if len(faces) == 0:
        return 0.0
    return max(f[3] for f in faces) / float(h)
