import datetime
import json
import os
import socket
import tempfile
import unittest

from infinite_jest.vetter import llm, rules, store, vet, web

OWN = """<html><head><title>Mara Lindqvist</title></head><body><nav>menu</nav>
<p>I make durational work with my body and with written text.</p>
<p>In 2025 I finished an MFA and I directed a new work for a small audience.</p>
<p>I teach a youth workshop every week and I perform on stage with an ensemble.</p>
<p>My mother was a nurse and my father voted conservative.</p>
<script>var x = "Mara Lindqvist secret";</script></body></html>"""
PRESS = """<html><head><title>Mara Lindqvist, the fighter</title></head><body>
<p>Mara Lindqvist performed in Malmo in 2026 and collaborated with a dance company on stage.</p>
<p>Mara Lindqvist plays a murderer in the new series, a cold and withdrawn character.</p>
<p>"I kept going despite the rejection, and I laugh about it now," says Lindqvist in 2025.</p>
<p>Lindqvist was treated for depression, the paper claims.</p>
<p>Lindqvist completed her training in 2025, won a scholarship and organised a festival.</p></body></html>"""
OTHER = """<html><head><title>Mara Lindqvist, dentist</title></head><body>
<p>Mara Lindqvist runs a dental practice in Ohio and insulted a client in 2024.</p></body></html>"""


class FakeWeb:
    def __init__(self):
        self.log, self.pages = [], {"https://mara.example/": OWN, "https://press.example/a": PRESS,
                                   "https://ohio.example/d": OTHER}
        self.queries = []

    def wikipedia(self, name):
        return []

    def search(self, q, n=8):
        self.queries.append(q)
        return ["https://press.example/a", "https://ohio.example/d"]

    def page(self, url):
        if url not in self.pages:
            return None
        self.log.append((url, "read"))
        return web.to_text(self.pages[url])


def run(**kw):
    root = tempfile.mkdtemp()
    args = dict(hints=["Malmo", "performer"], urls=["https://mara.example/"], booked="2026-12-01",
                today=datetime.date(2026, 11, 25), root=root)
    args.update(kw)
    w = FakeWeb()
    data, md = vet.vet("Mara Lindqvist", w, **args)
    return data, md, root, w


class Refusals(unittest.TestCase):
    def test_no_booking_no_research(self):
        w = FakeWeb()
        with self.assertRaises(ValueError):
            vet.vet("Mara Lindqvist", w, booked=None)
        self.assertEqual(w.queries, [])

    def test_single_name_refused(self):
        with self.assertRaises(ValueError):
            vet.vet("Mara", FakeWeb(), booked="2026-12-01")

    def test_model_must_be_on_this_machine(self):
        with self.assertRaises(ValueError):
            llm.LocalModel("https://api.example.com/v1/chat/completions")
        llm.LocalModel("http://127.0.0.1:8080/v1/chat/completions")

    def test_blocked_sites(self):
        for u in ("https://www.spokeo.com/x", "https://www.instagram.com/x", "https://linkedin.com/in/x"):
            self.assertTrue(web.blocked(u))
        self.assertFalse(web.Web().allowed("https://www.whitepages.com/name/x"))


class Pipeline(unittest.TestCase):
    def test_other_person_is_left_out(self):
        data, md, _, _ = run()
        self.assertIn("https://ohio.example/d", data["skipped_other_person"])
        self.assertNotIn("dental", json.dumps(data))

    def test_excluded_topics_never_reach_the_file(self):
        data, md, _, _ = run()
        blob = json.dumps(data) + md
        for word in ("depression", "mother", "nurse", "conservative", "voted"):
            self.assertNotIn(word, blob)
        self.assertGreaterEqual(sum(data["dropped_by_topic"].values()), 2)
        self.assertGreaterEqual(data["dropped_by_topic"].get("health", 0), 1)

    def test_roles_and_headlines_carry_no_weight(self):
        data, _, _, _ = run()
        self.assertFalse(any("murderer" in c["text"] and c["weight"] > 0 for c in data["cues"]))
        self.assertNotIn("fighter", json.dumps(data["cues"]))
        self.assertNotIn("secret", json.dumps(data))      # script contents are not read

    def test_scores_follow_the_rules(self):
        data, _, _, _ = run()
        o = data["ocean_detail"]
        self.assertEqual(data["group"], "performer")
        self.assertGreater(o["E"]["pct"], o["E"]["prior"])           # three or more behaviour cues
        self.assertEqual(o["N"]["pct"], o["N"]["prior"])             # one cue is not enough
        self.assertFalse(o["N"]["moved"])
        for t in "OCEAN":
            self.assertTrue(3 <= o[t]["pct"] <= 97)
        self.assertEqual(data["hook"], "flesh")
        self.assertTrue(data["quotes"])

    def test_three_cue_rule(self):
        two = [{"trait": "E", "dir": 1, "weight": 1.0}] * 2
        self.assertEqual(rules.score(two)["E"]["pct"], 50)
        light = [{"trait": "E", "dir": 1, "weight": 0.2}] * 9
        self.assertEqual(rules.score(light)["E"]["pct"], 50)
        self.assertGreater(rules.score(two + two)["E"]["pct"], 60)

    def test_old_evidence_counts_less(self):
        self.assertEqual(rules.age_weight(2026, 2026), 1.0)
        self.assertEqual(rules.age_weight(2021, 2026), 0.5)
        self.assertEqual(rules.age_weight(2016, 2026), 0.25)

    def test_thin_result_is_flagged(self):
        w = FakeWeb()
        w.pages = {}
        data, _ = vet.vet("Mara Lindqvist", w, booked="2026-12-01", root=tempfile.mkdtemp())
        self.assertTrue(data["thin"])
        self.assertIsNone(data["hook"])

    def test_queries_hold_only_name_and_hints(self):
        _, _, _, w = run()
        for q in w.queries:
            self.assertTrue(q.startswith('"Mara Lindqvist"'))
            self.assertNotIn("@", q)


class Export(unittest.TestCase):
    def make(self):
        import zipfile
        path = os.path.join(tempfile.mkdtemp(), "ig.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("your_instagram_activity/content/posts_1.json", json.dumps([
                {"media": [{"title": "I rehearsed every day and performed on stage for a new audience tonight", "creation_timestamp": 1790000000}]},
                {"media": [{"title": "My sister and I went to church together on a sunny day", "creation_timestamp": 1790000000}]},
                {"media": [{"title": "I performed this old piece on stage long ago in another city", "creation_timestamp": 1400000000}]}]))
            z.writestr("connections/followers_and_following/following.json", json.dumps(
                {"relationships_following": [{"string_list_data": [{"value": "dance_archive", "timestamp": 1}]},
                                             {"string_list_data": [{"value": "bodyworks", "timestamp": 1}]}]}))
            z.writestr("your_instagram_activity/messages/inbox/a/message_1.json", json.dumps(
                {"messages": [{"content": "private talk about Mara Lindqvist", "text": "this private message must never be read"}]}))
        return path

    def test_own_download_is_read_and_filtered(self):
        data, md, _, _ = run(export=self.make(), today=datetime.date(2027, 1, 5))
        blob = json.dumps(data) + md
        self.assertIn("rehearsed every day", blob)
        self.assertNotIn("private message", blob)       # messages are never opened
        self.assertNotIn("sister", blob)                # family and religion dropped
        self.assertNotIn("long ago", blob)              # older than the terms allow
        self.assertNotIn("dance_archive", blob)         # names of followed accounts are not kept
        self.assertEqual(data["social"]["counts"]["follows"], 2)


class Search(unittest.TestCase):
    def test_bot_check_is_logged_as_blocked(self):
        w = web.Web(delay=0)
        w._get = lambda url: '<div class="anomaly-modal__title">Select all squares</div>'
        self.assertEqual(w.search('"Mara Lindqvist"'), [])
        self.assertIn("blocked", w.log[-1][1])

    def test_pictures_are_not_pages(self):
        links = web.same_site_links('<a href="/img/a.jpg">x</a><a href="/about.html">y</a>', "https://m.example/")
        self.assertEqual(links, ["https://m.example/about.html"])

    def test_no_quotes_and_no_movement_is_thin(self):
        w = FakeWeb()
        w.pages = {"https://mara.example/": "<html><title>Mara Lindqvist</title><body>" +
                   "<p>Mara Lindqvist is listed here with a date and a place and not much more than that.</p>" * 9 + "</body></html>"}
        data, _ = vet.vet("Mara Lindqvist", w, urls=["https://mara.example/"], booked="2026-12-01", root=tempfile.mkdtemp())
        self.assertTrue(data["thin"])


class Store(unittest.TestCase):
    def test_files_are_private_and_deletable(self):
        data, _, root, _ = run()
        d = store.folder("Mara Lindqvist", root)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(d, "guest.json")).st_mode & 0o777, 0o600)
        self.assertIn("Mara Lindqvist", store.show("Mara Lindqvist", root))
        self.assertTrue(store.delete("Mara Lindqvist", root))
        self.assertIsNone(store.show("Mara Lindqvist", root))

    def test_purge_after_the_delete_date(self):
        _, _, root, _ = run()
        self.assertEqual(store.purge("2026-12-23", root), [])
        self.assertEqual(store.purge("2026-12-24", root), ["mara-lindqvist"])
        self.assertFalse(os.path.exists(store.folder("Mara Lindqvist", root)))

    def test_writing_a_file_opens_no_connection(self):
        real = socket.socket

        def boom(*a, **k):
            raise AssertionError("network used")
        socket.socket = boom
        try:
            run()
        finally:
            socket.socket = real


if __name__ == "__main__":
    unittest.main()
