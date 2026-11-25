"""Recognise a booked guest who asked to be recognised. Everything else is a stranger.

Rules built into the code:
- A face is enrolled only from photos the guest gave for this purpose, and only if
  their guest file has consent.face == true. No photo is ever taken from the web.
- What is stored is a list of numbers (an embedding) in the guest's own folder,
  private to the Pi's user, deleted with the file. The enrolment photos are not kept.
- Live camera frames are compared in memory and never written to disk.
- An unknown face is not stored, not counted and not remembered. The answer is None.
- A match needs two agreeing frames and a clear margin over the second-best guest.

Models (not in the repo, fetched once by the Mac into ~/models/face/):
  face_detection_yunet_2023mar.onnx and face_recognition_sface_2021dec.onnx
  from the OpenCV model zoo. Needs python3-opencv 4.8 or newer.
"""

import json
import math
import os

DEFAULT_GUESTS = os.path.expanduser("~/.local/share/infinite-jest/guests")
DEFAULT_MODELS = os.path.expanduser("~/models/face")
THRESHOLD = 0.42     # cosine similarity; OpenCV's own SFace threshold is 0.363, we ask for more
MARGIN = 0.08        # the best guest must beat the second best by this much
NEED = 2             # frames in a row that must agree


class SFace:
    """Thin wrapper around OpenCV's detector and embedder. Imported lazily: no cv2, no recognition."""

    def __init__(self, models=DEFAULT_MODELS):
        import cv2
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(os.path.join(models, "face_detection_yunet_2023mar.onnx"), "", (320, 320))
        self.rec = cv2.FaceRecognizerSF.create(os.path.join(models, "face_recognition_sface_2021dec.onnx"), "")

    def embed(self, image):
        """Embedding of the single largest face in a BGR image, or None (no face, or more than one person close)."""
        h, w = image.shape[:2]
        if max(h, w) > 1280:                 # the detector misses faces in very large photos
            k = 1280 / max(h, w)
            image = self.cv2.resize(image, (int(w * k), int(h * k)))
            h, w = image.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(image)
        if faces is None or len(faces) == 0:
            return None
        faces = sorted(faces, key=lambda f: -f[2] * f[3])
        if len(faces) > 1 and faces[1][2] * faces[1][3] > 0.6 * faces[0][2] * faces[0][3]:
            return None      # two people at the same distance: do not guess
        aligned = self.rec.alignCrop(image, faces[0])
        return [float(x) for x in self.rec.feature(aligned).flatten()]

    def read(self, path):
        return self.cv2.imread(path)


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _guest(folder):
    try:
        with open(os.path.join(folder, "guest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def enrol(folder, photos, embedder):
    """Store face numbers for one guest from photos they gave. Returns how many photos worked.
    Refuses unless the guest file carries consent.face == true."""
    g = _guest(folder)
    if not g or g.get("consent", {}).get("face") is not True:
        raise PermissionError("this guest has not agreed to face recognition")
    vectors = []
    for p in photos:
        img = embedder.read(p)
        v = embedder.embed(img) if img is not None else None
        if v:
            vectors.append(v)
    if not vectors:
        return 0
    path = os.path.join(folder, "face.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"vectors": vectors, "delete_after": g.get("delete_after")}, f)
    return len(vectors)


def load_enrolled(root=DEFAULT_GUESTS):
    """{folder name: [vectors]} for guests who agreed and were enrolled. Consent is checked again on every load."""
    out = {}
    if not os.path.isdir(root):
        return out
    for entry in sorted(os.listdir(root)):
        folder = os.path.join(root, entry)
        g = _guest(folder)
        if not g or g.get("consent", {}).get("face") is not True:
            continue
        try:
            with open(os.path.join(folder, "face.json")) as f:
                out[entry] = json.load(f)["vectors"]
        except (OSError, ValueError, KeyError):
            continue
    return out


class Recogniser:
    """Feed camera frames; get a guest folder name once it is sure, else None. Holds nothing about strangers."""

    def __init__(self, embedder, root=DEFAULT_GUESTS, threshold=THRESHOLD, margin=MARGIN, need=NEED):
        self.embedder, self.enrolled = embedder, load_enrolled(root)
        self.threshold, self.margin, self.need = threshold, margin, need
        self.reset()

    def reset(self):
        """Call when the room empties."""
        self._last, self._run, self.decided = None, 0, None

    def best(self, vector):
        scores = sorted(((max(_cos(vector, v) for v in vs), name) for name, vs in self.enrolled.items()), reverse=True)
        if not scores or scores[0][0] < self.threshold:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < self.margin:
            return None
        return scores[0][1]

    def see(self, frame):
        if self.decided or not self.enrolled:
            return self.decided
        vector = self.embedder.embed(frame)
        name = self.best(vector) if vector else None
        del vector                                   # the stranger's numbers are gone here
        self._run = self._run + 1 if name and name == self._last else (1 if name else 0)
        self._last = name
        if name and self._run >= self.need:
            self.decided = name
        return self.decided
