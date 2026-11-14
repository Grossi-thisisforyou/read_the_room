#!/usr/bin/env python3
"""Tests for prompts.py v2 (vocabulary, tags, themes, no repeats, length).

    python3 tests/test_prompts.py -v
"""
import codecs
import datetime
import os
import random
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(ROOT))  # visuals/, for palettes.py
import palettes  # noqa: E402
import prompts  # noqa: E402

# Words that must never appear anywhere in bank_gen (artist rule). Stored
# rot13-encoded so this file doesn't spell them out either.
BANNED_ROT13 = [
    "onfdhvng", "pebja", "pebjaf", "fxhyy", "fxhyyf", "evo", "evof", "evopntr", "pbclevtug",
    "bvy fgvpx", "bvyfgvpx", "bvy-fgvpx", "tenssvgv", "fcenl cnvag", "gnttvat",
    # painter names: describe the look instead
    "onpba", "onfryvgm", "senapvf", "trbet", "cvpnffb", "serhq", "fpuvryr", "tbln",
    "erzoenaqg", "pneninttvb", "zhapu", "xvrsre", "evpugre", "jneubym", "cbyybpx",
]
BANNED = [codecs.decode(w, "rot13") for w in BANNED_ROT13]
BANNED_RE = re.compile(r"\b(%s)\b" % "|".join(re.escape(w) for w in BANNED), re.I)
TEXT_EXT = (".py", ".sh", ".md", ".txt", ".command", ".service", ".html")


def all_vocab_strings():
    out = [prompts.COMMON_STYLE, prompts.NEGATIVE]
    for hook, parts in prompts.HOOK_PARTS.items():
        for v in parts.values():
            out += v if isinstance(v, list) else [v]
    for entry in prompts.PALETTES.values():
        for v in entry.values():
            out += v
    out += [m[1] for m in prompts.MOTIFS]
    out += [t["phrase"] for t in prompts.THEMES.values()]
    out += list(prompts.POSITIONS.values()) + list(prompts.FRAMINGS.values()) + list(prompts.PANELS.values())
    return out


class Vocabulary(unittest.TestCase):
    def test_no_banned_words_in_vocabulary(self):
        for s in all_vocab_strings():
            self.assertIsNone(BANNED_RE.search(s), s)

    def test_no_banned_words_in_any_bank_gen_file(self):
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in files:
                if not n.endswith(TEXT_EXT):
                    continue
                with open(os.path.join(root, n), encoding="utf-8") as f:
                    m = BANNED_RE.search(f.read())
                self.assertIsNone(m, "%s mentions %r" % (os.path.join(root, n), m and m.group(0)))

    def test_palette_names_match_renderer(self):
        for name in prompts.PALETTES:
            self.assertIn(name, palettes.NAMED)
        for hook, weights in prompts.HOOK_PALETTES.items():
            for name in weights:
                self.assertIn(name, prompts.PALETTES, (hook, name))
        for t in prompts.THEMES.values():
            for name in t["palettes"]:
                self.assertIn(name, prompts.PALETTES)
            for m in t["motifs"]:
                self.assertIn(m, prompts.MOTIF_BY_TAG)
            for f in t["framings"]:
                self.assertIn(f, prompts.FRAMINGS)

    def test_every_hook_has_hundreds_of_combinations(self):
        for h in prompts.HOOKS:
            self.assertGreater(prompts.combinations(h), 10000, h)


class Building(unittest.TestCase):
    def test_length_fits_clip(self):
        rng = random.Random(3)
        deck = prompts.PromptDeck(rng)
        for h in prompts.HOOKS:
            for theme in (None, "mix", "watched", "harvest"):
                for _ in range(400):
                    r = prompts.make(h, deck=deck, theme=theme)
                    p = r["prompt"]
                    self.assertLessEqual(len(p.split()), prompts.MAX_WORDS, p)
                    self.assertLessEqual(prompts.estimate_tokens(p), prompts.MAX_TOKENS, p)
                    # the essentials are never dropped
                    self.assertTrue(p.startswith(r["parts"]["figure"]), p)
                    self.assertIn(r["parts"]["style"], p)
                    self.assertIn(r["parts"]["palette"], p)

    def test_tags(self):
        rng = random.Random(5)
        for h in prompts.HOOKS:
            for _ in range(200):
                r = prompts.make(h, rng=rng, theme="mix")
                t = r["tags"]
                self.assertEqual(t["hook"], h)
                self.assertIn(t["palette"], prompts.HOOK_PALETTES[h])
                comp = t["composition"]
                self.assertIn(comp["position"], prompts.HOOK_COMPOSITION[h]["position"])
                self.assertIn(comp["framing"], prompts.HOOK_COMPOSITION[h]["framing"])
                self.assertIn(comp["panel"], prompts.HOOK_COMPOSITION[h]["panel"])
                for m in t["motifs"]:
                    hooks = prompts.MOTIF_BY_TAG[m][2]
                    self.assertTrue(hooks is None or h in hooks, (h, m))
                    self.assertIn(prompts.MOTIF_BY_TAG[m][1], r["prompt"])  # tag means it's in the prompt
                self.assertIn("hook:" + h, r["tag_list"])
                self.assertIn("palette:" + t["palette"], r["tag_list"])
                self.assertIn("position:" + comp["position"], r["tag_list"])
                if t["theme"]:
                    self.assertIn("theme:" + t["theme"], r["tag_list"])
                fields = prompts.sidecar_fields(r)
                for k in ("prompt", "negative_prompt", "tags", "tag_list", "signature", "prompt_version"):
                    self.assertIn(k, fields)

    def test_triptych_panels_exist_for_flesh(self):
        rng = random.Random(9)
        panels = {prompts.make("flesh", rng=rng)["tags"]["composition"]["panel"] for _ in range(300)}
        self.assertTrue({"single", "triptych-left", "triptych-centre", "triptych-right"} <= panels, panels)

    def test_deck_does_not_repeat(self):
        deck = prompts.PromptDeck(random.Random(11))
        for h in prompts.HOOKS:
            sigs, subjects, prompts_seen = [], [], set()
            n_fig = len(prompts.HOOK_PARTS[h]["figure"])
            for _ in range(300):
                r = prompts.make(h, deck=deck)
                sigs.append(r["signature"])
                subjects.append(r["parts"]["figure"])
                prompts_seen.add(r["prompt"])
            self.assertEqual(len(set(sigs)), 300, h)
            # figures are dealt like cards, so they come up about equally often
            counts = [subjects.count(f) for f in prompts.HOOK_PARTS[h]["figure"]]
            self.assertLessEqual(max(counts) - min(counts), 4, (h, counts))
            self.assertGreaterEqual(min(counts), 300 // n_fig - 4, (h, counts))
            for a, b in zip(subjects, subjects[1:]):
                self.assertNotEqual(a, b)

    def test_deck_avoids_remembered(self):
        rng = random.Random(1)
        first = prompts.make("void", rng=random.Random(1), deck=prompts.PromptDeck(random.Random(1)))
        deck = prompts.PromptDeck(rng)
        deck.remember(first["signature"])
        again = prompts.make("void", deck=deck)
        self.assertNotEqual(again["signature"], first["signature"])

    def test_old_interface(self):
        p, n, parts = prompts.build_prompt("scrawl", random.Random(0))
        self.assertTrue(p and n)
        self.assertEqual(parts["tags"]["hook"], "scrawl")


class Themes(unittest.TestCase):
    def test_night_boundary(self):
        evening = datetime.datetime(2026, 11, 20, 22, 30)
        morning = datetime.datetime(2026, 11, 21, 7, 45)
        next_evening = datetime.datetime(2026, 11, 21, 22, 30)
        self.assertEqual(prompts.theme_for_night(evening), prompts.theme_for_night(morning))
        self.assertNotEqual(prompts.theme_for_night(evening), prompts.theme_for_night(next_evening))
        self.assertEqual(prompts.resolve_theme("auto", evening), prompts.theme_for_night(evening))

    def test_every_theme_comes_round(self):
        start = datetime.datetime(2026, 11, 1, 23, 0)
        seen = {prompts.theme_for_night(start + datetime.timedelta(days=d)) for d in range(len(prompts.THEMES))}
        self.assertEqual(seen, set(prompts.THEMES))

    def test_theme_makes_batch_coherent(self):
        rng = random.Random(2)
        deck = prompts.PromptDeck(rng)
        for name, t in prompts.THEMES.items():
            results = [prompts.make("flesh", deck=deck, theme=name) for _ in range(200)]
            self.assertTrue(all(r["tags"]["theme"] == name for r in results))
            allowed = [p for p in t["palettes"] if p in prompts.HOOK_PALETTES["flesh"]]
            if allowed:
                share = sum(r["tags"]["palette"] in allowed for r in results) / 200.0
                base = sum(prompts.HOOK_PALETTES["flesh"][p] for p in allowed) / float(
                    sum(prompts.HOOK_PALETTES["flesh"].values()))
                self.assertGreater(share, base, name)
            motifs = [m for r in results for m in r["tags"]["motifs"]]
            themed = [m for m in motifs if m in t["motifs"]]
            if any(prompts.MOTIF_BY_TAG[m][2] is None or "flesh" in prompts.MOTIF_BY_TAG[m][2] for m in t["motifs"]):
                self.assertGreater(len(themed), len(motifs) * 0.5, name)

    def test_bad_theme(self):
        with self.assertRaises(ValueError):
            prompts.resolve_theme("nonsense")
        self.assertIsNone(prompts.resolve_theme("none"))


if __name__ == "__main__":
    unittest.main()
