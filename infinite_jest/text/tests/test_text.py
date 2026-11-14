"""python3 -m unittest discover -s infinite_jest/text/tests -t ."""

import json
import random
import unittest

from infinite_jest.text import Corpus, build, fill, oracle_prompt, style

SAMPLE = dict(visits_today=14, avg_stay=63, max_stay=171, empty_min=12, vid="v-7f3a",
              handled=.82, tilt_range=140, tilt_speed=55, closeness=.6, approach_time=4,
              touch_rate=12.5, touch_variety=.4, hold_ratio=.3, voice=.2, loudness=.5,
              shake=.12, motion=.3, burstiness=.4, roaming=.2, gaze=.5, choice_speed=1.8,
              typing=12, dwell=72, pace=.3, still_s=6, scene="the meat",
              segment="The Performer", trait="OPENNESS", value=.71, conf=.6, n_scenes=4,
              confidence=.83, seconds=72, option="upside down")


class CorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Corpus.load()

    def test_built_file_is_current(self):
        with open(build.OUT, encoding="utf-8") as f:
            self.assertEqual(f.read(), build.dumps(build.build()),
                             "run python3 -m infinite_jest.text.build")

    def test_every_line_passes_the_style_check(self):
        bad = []
        for e in self.c.all:
            for t in e.get("lines") or [e["text"]]:
                out = fill(t, SAMPLE)
                self.assertIsNotNone(out, "unfillable: " + t)
                if e["register"] == "log":
                    out = out.upper()
                p = style.check(out, e["register"], e.get("max_words"))
                if p:
                    bad.append((e["id"], out, p))
        self.assertEqual(bad, [])

    def test_volume(self):
        n = sum(len(e.get("lines") or [1]) for e in self.c.all)
        self.assertGreater(n, 500)
        self.assertGreaterEqual(len(self.c.prompts()), 25)
        for hook in ("flesh", "scrawl", "inverted", "mirror", "void"):
            self.assertGreaterEqual(len(self.c.lines(beat="testing", hook=hook)), 15, hook)
            self.assertGreaterEqual(len(self.c.scrawl(hook=hook)), 8, hook)
        for pole in ("E+", "E-", "O+", "O-", "C+", "C-", "A+", "A-", "N+", "N-"):
            self.assertGreaterEqual(len(self.c.lines(beat="tailored", pole=pole)), 8, pole)
            self.assertGreaterEqual(len(self.c.lines(beat="infer", pole=pole)), 3, pole)

    def test_every_confession_ends_on_the_refrain(self):
        for e in self.c.lines(beat="confession", surface="wall"):
            self.assertEqual(e["lines"][-1], "it still felt like it knew you.")

    def test_registers_keep_their_pronouns(self):
        for e in self.c.lines(register="whisper"):
            self.assertNotRegex(" " + e["text"] + " ", r"\swe\s")

    def test_prompts_match_profiler_shape(self):
        ids = set()
        for p in self.c.prompts():
            self.assertEqual(len(p["options"]), 2)
            self.assertEqual(len(p["traits"]), 2)
            self.assertNotIn(p["id"], ids)
            ids.add(p["id"])
            self.assertEqual(style.check(p["ask"], "whisper"), [], p["ask"])
            for o in p["options"]:
                self.assertEqual(style.check(o, "whisper"), [], o)
        self.assertTrue({"closer", "scream", "seen", "upside", "secret"} <= ids)

    def test_labels(self):
        for pole, seg in self.c.labels["segments"].items():
            self.assertEqual(style.check(seg["audience"], "confession"), [], pole)
        self.assertEqual(self.c.scene_name("inverted"), "the fall")

    def test_cuts_remove_lines(self):
        e = self.c.lines(beat="lift", surface="phone")[0]
        c2 = Corpus(self.c.all, self.c.prompts(), self.c.labels, cuts=[e["id"]])
        self.assertNotIn(e["id"], [x["id"] for x in c2.lines(beat="lift", surface="phone")])

    def test_german_switch(self):
        c2 = Corpus.load(german=False)
        self.assertFalse([e for e in c2.lines() if e.get("lang") == "de"])

    def test_german_budget(self):
        v = self.c.visit(random.Random(1))
        de = 0
        for _ in range(40):
            v.pick({"vid": "v-1"}, surface="wall", beat=("attract", "lift", "header"))
        de = v.german_used
        self.assertLessEqual(de, 3)


class VisitTest(unittest.TestCase):
    def setUp(self):
        self.v = Corpus.load().visit(random.Random(7))

    def test_no_repeats_until_exhausted(self):
        n = len(self.v.c.lines(surface="phone", beat="lift"))
        got = [self.v.pick(surface="phone", beat="lift") for _ in range(n)]
        self.assertEqual(len(set(got)), n)

    def test_missing_values_skip_lines(self):
        for _ in range(30):
            line = self.v.pick(surface="wall", beat="calibration")
            self.assertNotIn("{", line)

    def test_log_is_uppercased_after_filling(self):
        line = self.v.pick({"scene": "the meat"}, surface="wall", beat="lock", register="log")
        self.assertEqual(line, line.upper())

    def test_reveal(self):
        r = self.v.reveal(dict(
            evidence=[(.6, "E", "handled", .82, 1), (.5, "O", "choice:upside", "upside down", 1),
                      (.4, "N", "shake", .11, -1)],
            ocean=dict(O=.71, C=.38, E=.66, A=.52, N=.41),
            trait_confidence=dict(O=.55, C=.3, E=.7, A=.2, N=.25), confidence=.83,
            segment_pole="E+", hook="mirror", scenes_tried=4, seconds=96,
            choices={"seen": "forgotten"}, vid="v-7f3a", visits_today=14))
        text = "\n".join(r["lines"])
        self.assertIn("82%", text)
        self.assertIn("upside down", text)
        self.assertIn("THE PERFORMER", text)
        self.assertIn("the mirror", text)
        self.assertTrue(r["lines"][-1].startswith("it still felt like it knew you"))
        self.assertEqual(r["wipe"][0], "you asked to be forgotten.")
        self.assertNotIn("mirror", " ".join(r["wipe"]))

    def test_short_and_optout_reveals(self):
        r = self.v.reveal({"seconds": 9})
        self.assertTrue(any("9" in l for l in r["lines"]))
        r = self.v.reveal({"opted_out": True})
        self.assertTrue(r["lines"])
        self.assertNotIn("CONFIDENCE", " ".join(r["lines"]))


class StyleTest(unittest.TestCase):
    def test_catches(self):
        for line, rule in [
            ("you seem nervous.", "emotion"), ("you are a young woman.", "demographic"),
            ("your hair moves.", "body"), ("pathetic.", "insult"), ("this is like Bacon", "source"),
            ("the crown is yours", "source"), ("DARK DATA ©", "source"),
            ("as an ai i cannot", "leak"), ("your soul is here", "cliche"),
            ("you will die here", "violence"), ("stay!", "punctuation")]:
            rules = [p[0] for p in style.check(line)]
            self.assertIn(rule, rules, line)

    def test_registers(self):
        self.assertTrue(style.check("we see you.", "whisper"))
        self.assertTrue(style.check("i saw you.", "confession"))
        self.assertTrue(style.check("Stay.", "whisper"))
        self.assertTrue(style.check("hands still", "log"))
        self.assertFalse(style.check("Cambridge Analytica sold this as mind reading.", "confession"))
        self.assertFalse(style.check("HOLDS THE PHONE CLOSE", "log"))
        self.assertFalse(style.check("hold me still.", "whisper"))

    def test_clean_words(self):
        good = "Line 1: Stay. it gets better.\n- HOLDS STILL\n- GRIP 82%\n- comes close"
        self.assertEqual(style.clean_words(good),
                         ("stay. it gets better", ["HOLDS STILL", "GRIP 82%", "COMES CLOSE"]))
        self.assertIsNone(style.clean_words("you seem lonely.\nSAD SUBJECT\nALONE"))
        self.assertIsNone(style.clean_words("one line only"))
        self.assertIsNone(style.clean_words("stay.\nTHIS FRAGMENT IS FAR TOO LONG"))

    def test_clean_dossier(self):
        out = style.clean_dossier("You held it 80% of the time.\nA model reads that as extraversion.")
        self.assertEqual(out[-1], "this profile is being deleted now.")
        self.assertIsNone(style.clean_dossier("i think you are anxious."))


class OracleTest(unittest.TestCase):
    profile = {"ocean": {"O": .7, "C": .4, "E": .8, "A": .5, "N": .4},
               "trait_confidence": {"E": .7}, "confidence": .8, "hook": "inverted",
               "segment": "The Performer", "hook_params": {"prompt_style": "social"},
               "features": {"handled": .82, "tilt_range": 150},
               "evidence": ["handled -> E+", "tilt_range -> O+", "voice -> E+"],
               "visitor_id": "v-secret", "frames": "never"}

    def test_messages(self):
        m = oracle_prompt.words_messages(self.profile)
        self.assertEqual(m[0]["role"], "system")
        self.assertEqual(m[-1]["role"], "user")
        last = m[-1]["content"]
        self.assertIn("the fall", last)
        self.assertIn("82%", last)
        self.assertIn("150 degrees", last)
        blob = json.dumps(m)
        self.assertNotIn("v-secret", blob)
        self.assertNotIn("inverted", blob)
        # static prefix identical across visitors (prompt cache)
        m2 = oracle_prompt.words_messages(dict(self.profile, hook="void"))
        self.assertEqual(m[:-1], m2[:-1])

    def test_dossier_messages(self):
        m = oracle_prompt.dossier_messages(self.profile)
        self.assertIn("80%", m[-1]["content"])
        self.assertIn("the performer", m[-1]["content"])

    def test_examples_pass_own_filter(self):
        cfg = oracle_prompt.config()
        for ex in cfg["words"]["examples"]:
            self.assertIsNotNone(style.clean_words(ex["assistant"]), ex["assistant"])
        for ex in cfg["dossier"]["examples"]:
            self.assertIsNotNone(style.clean_dossier(ex["assistant"]), ex["assistant"])


if __name__ == "__main__":
    unittest.main()
