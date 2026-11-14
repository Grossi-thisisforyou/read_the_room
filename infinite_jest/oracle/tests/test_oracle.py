import json
import unittest

from infinite_jest.oracle import Oracle
from infinite_jest.oracle import voice
from infinite_jest.profiler import sim


def sim_profiles(name="performer"):
    profiles, reveal = sim.run(name, seed=1)
    return profiles


class TestVoice(unittest.TestCase):
    def test_prompt_has_no_ids_or_raw_data(self):
        prof = sim_profiles()[-1]["data"]
        blob = json.dumps(voice.words_messages(prof) + voice.dossier_messages(prof))
        self.assertNotIn(prof["visitor_id"], blob)
        self.assertIn("Extraversion", blob)
        self.assertTrue(voice.observed(prof))

    def test_guard_rejects_identity_guesses(self):
        self.assertIsNone(voice.clean_words("stay a little longer\nYOUNG WOMAN\nLEANS IN\nLOOKS"))
        self.assertIsNone(voice.clean_dossier("you seemed sad"))
        self.assertIsNone(voice.clean_words(""))

    def test_inspiration_stays_hidden(self):
        prof = sim_profiles()[-1]["data"]
        blob = json.dumps(voice.words_messages(prof) + voice.dossier_messages(prof)).lower()
        for name in ("bacon", "basquiat", "baselitz", "crown"):
            self.assertNotIn(name, blob)
        self.assertIsNone(voice.clean_words("look at the crown\nSUBJECT LINGERS"))
        self.assertIsNone(voice.clean_dossier("this felt like basquiat"))

    def test_guard_accepts_good_output(self):
        phone, words = voice.clean_words("1. stay, the screen is warmer now.\n2. subject lingers\n3. HOLDS DEVICE CLOSE\n4. wants to be seen")
        self.assertEqual(phone, "stay, the screen is warmer now")
        self.assertEqual(words, ["SUBJECT LINGERS", "HOLDS DEVICE CLOSE", "WANTS TO BE SEEN"])
        d = voice.clean_dossier("you came close.\nwe called you a performer.\nthe writing worked.\nmostly a guess.")
        self.assertIn("deleted", d[-1])


class TestOracleFlow(unittest.TestCase):
    def test_jobs_and_wipe(self):
        o = Oracle()
        o.handle({"type": "state", "ts": 1000, "data": {"visitor_id": "v-sim", "phase": "profiling"}})
        jobs = []
        for p in sim_profiles():
            jobs += o.handle(p)
        kinds = [j[0] for j in jobs]
        self.assertIn("words", kinds)
        self.assertLessEqual(len(jobs), 12, "rate limited to one words call per 8 s")
        jobs = o.handle({"type": "state", "ts": 1030, "data": {"visitor_id": "v-sim", "phase": "hook"}})
        self.assertEqual(jobs[0][0], "dossier")
        out = o.accept("dossier", "v-sim", "you came close\nmostly a guess")
        self.assertEqual(out["type"], "oracle")
        self.assertEqual(out["data"]["visitor_id"], "v-sim")
        o.handle({"type": "wipe", "ts": 1080, "data": {"visitor_id": "v-sim"}})
        self.assertIsNone(o.accept("words", "v-sim", "late line\nSUBJECT GONE"))

    def test_low_confidence_no_calls(self):
        o = Oracle()
        p = sim_profiles()[0]
        p["data"]["confidence"] = 0.1
        self.assertEqual(o.handle(p), [])


if __name__ == "__main__":
    unittest.main()
