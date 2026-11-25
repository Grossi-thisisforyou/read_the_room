import json
import os
import tempfile
import unittest

from infinite_jest.recognise import core


class Fake:
    """Stands in for the camera model: a 'photo' or 'frame' is already a vector, or None for no face."""
    def read(self, path):
        return json.load(open(path))

    def embed(self, image):
        return image


def guest(root, name, face):
    d = os.path.join(root, name)
    os.makedirs(d)
    json.dump({"name": name, "consent": {"research": True, "face": face}, "delete_after": "2026-12-23"},
              open(os.path.join(d, "guest.json"), "w"))
    return d


def photo(vec):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(vec, f)
    f.close()
    return f.name


A, B, STRANGER = [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]


class Consent(unittest.TestCase):
    def test_no_consent_no_enrolment(self):
        root = tempfile.mkdtemp()
        d = guest(root, "anna", False)
        with self.assertRaises(PermissionError):
            core.enrol(d, [photo(A)], Fake())
        self.assertFalse(os.path.exists(os.path.join(d, "face.json")))

    def test_withdrawn_consent_stops_matching(self):
        root = tempfile.mkdtemp()
        d = guest(root, "anna", True)
        self.assertEqual(core.enrol(d, [photo(A)], Fake()), 1)
        self.assertEqual(os.stat(os.path.join(d, "face.json")).st_mode & 0o777, 0o600)
        self.assertIn("anna", core.load_enrolled(root))
        json.dump({"name": "anna", "consent": {"face": False}}, open(os.path.join(d, "guest.json"), "w"))
        self.assertEqual(core.load_enrolled(root), {})


class Matching(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        core.enrol(guest(self.root, "anna", True), [photo(A)], Fake())
        core.enrol(guest(self.root, "ben", True), [photo(B)], Fake())
        self.r = core.Recogniser(Fake(), self.root)

    def test_needs_two_frames(self):
        self.assertIsNone(self.r.see([0.98, 0.1, 0, 0]))
        self.assertEqual(self.r.see([0.97, 0.12, 0, 0]), "anna")

    def test_stranger_is_none_and_leaves_nothing(self):
        before = sorted(os.listdir(self.root))
        for _ in range(5):
            self.assertIsNone(self.r.see(STRANGER))
        self.assertIsNone(self.r.see(None))
        self.assertEqual(sorted(os.listdir(self.root)), before)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "anna"))), ["face.json", "guest.json"])

    def test_lookalike_between_two_guests_is_not_guessed(self):
        for _ in range(4):
            self.assertIsNone(self.r.see([0.7, 0.68, 0, 0]))

    def test_reset_forgets(self):
        self.r.see(A), self.r.see(A)
        self.r.reset()
        self.assertIsNone(self.r.see(STRANGER))


if __name__ == "__main__":
    unittest.main()
